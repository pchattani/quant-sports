"""
ESPN's public NFL JSON: live game state (drives, plays, clock, win probability per play, predictor,
injuries), DraftKings open/close from the summary's pickcenter, and the core odds history by book, fetched from
the 2017 season (`canon.ESPN_ODDS_FROM`; scripts/nfl_fetch.py --espn-from). The endpoint also answers for 2016 events,
as the provider notes below record, but the site's ESPN lines start in 2017.
No key, CORS *; paced at <= 1 request a second.

Endpoints (verified 1 Oct 2026):
  site  https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=YYYYMMDD   (US Eastern day)
        .../scoreboard?dates=<season>&seasontype=<2|3>&week=<n>     one week (playoffs: week 1 WC, 2 DIV, 3 CON, 5 SB)
        .../summary?event=ID      drives.previous[].plays[] (start/end down, distance, yardsToEndzone, scores),
                                  winprobability [{playId, homeWinPercentage, tiePercentage}], pickcenter
                                  (DraftKings: spread/total/moneyline with open and close), predictor (FPI, not
                                  always present), injuries, gameInfo (venue, officials, weather), header (status)
  core  https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/ID/competitions/ID/odds
          items per provider. 2016-2019 offshore and Nevada books (5Dimes, Bovada, Westgate, "Opening", ...),
          2019-2024 US books (DraftKings, Caesars, MGM, SugarHouse, ESPN BET, ...), 2026 DraftKings only.
          `spread` is the HOME handicap, signed (home favourite negative): verified on 2016, 2019, 2023 and 2026
          events against the moneyline favourite. initialSpread / initialOverUnder (2016-2018) and open/close
          blocks (2023->) give opening and closing lines; otherwise `current` is the last pre-game line, read
          after the game. Rows named "... Live Odds" are in-play and dropped; a book whose spread or total sits
          far from the other books' median (in-play captures, typos) is flagged `suspect` and never chosen.
          consensus / teamrankings / numberfire / accuscore / SportsInsights carry no prices of their own.

ESPN events map to nflverse game ids through the schedules' `espn` column; failing that, by season, week
and the two teams (ESPN team id -> nflverse abbreviation of that season), then by teams and the nearest
kickoff within a day and a half.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Any

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
INTERVAL = 1.0
PREFERRED = ("100", "40", "58", "38", "31", "45", "47", "41", "36", "25", "20", "18", "19", "26", "15", "4", "3", "1",
             "28", "35", "32", "37", "52", "57", "48", "53")   # DraftKings first, then ESPN BET, Caesars, MGM, ...
NO_PRICE = {"1001", "1002", "1003", "1004", "1007", "2000"}         # accuscore, teamrankings, numberfire, consensus, ...
OPENING = "23"                                                       # the "Opening" provider (Westgate opener, 2016-2018)
POST_WEEK = {1: "WC", 2: "DIV", 3: "CON", 5: "SB"}                   # ESPN seasontype 3 weeks (4 = Pro Bowl)


def _int(v: Any) -> int | None:
    try:
        return int(round(float(str(v).replace("+", ""))))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        s = str(v).strip().lower().lstrip("ou").replace("+", "")
        if s in ("pk", "pick", "even"):
            return 0.0
        return float(s)
    except (TypeError, ValueError):
        return None


def _am(node: Any) -> int | None:
    """American odds from {"american": "-117"} / {"odds": "+250"} / a number; "EVEN" -> 100."""
    if isinstance(node, dict):
        v = node.get("american", node.get("odds", node.get("alternateDisplayValue")))
    else:
        v = node
    if v in (None, ""):
        return None
    if str(v).strip().lower() == "even":
        return 100
    return _int(v)


def _iso(s: Any) -> datetime | None:
    if not s:
        return None
    for fmt in (None, "%Y-%m-%dT%H:%MZ"):
        try:
            if fmt is None:
                return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
            return datetime.strptime(str(s), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ── fetchers ────────────────────────────────────────────────────────────────

def scoreboard(c: Client, date: str | None = None, week: int | None = None, season: int | None = None,
               seasontype: int = 2) -> list[dict] | None:
    """Events of a day (YYYYMMDD, US Eastern) or of a season week."""
    if week is not None:
        params = {"dates": str(season), "seasontype": int(seasontype), "week": int(week), "limit": 100}
    else:
        params = {"dates": str(date), "limit": 100}
    d = c.get(f"{SITE}/scoreboard", params)
    return None if d is None else list(d.get("events") or [])


def summary(c: Client, event_id: str) -> dict | None:
    return c.get(f"{SITE}/summary", {"event": str(event_id)})


def odds(c: Client, event_id: str) -> dict | None:
    return c.get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds", {"limit": 100})


def transactions(c: Client, year: int, limit: int = 1000, max_pages: int = 8) -> list[dict] | None:
    """Every transaction ESPN lists for a calendar year (verified 16 Oct 2026):
    site .../transactions?season=<year>&limit=<n>&page=<p> -> {"count", "pageCount", "transactions": [{"date"
    (ISO, UTC), "description" (one or more sentences: "Traded WR X and a 2027 sixth-round draft pick to Houston for
    ..."), "team": {"abbreviation", "displayName", ...}}]}. `season` is the calendar year (2025 runs 1 Jan - 31 Dec
    2025); the text is free-form, so parsing lives in analytics/transactions.py. None when the first page fails."""
    out: list[dict] = []
    page, pages = 1, 1
    while page <= min(pages, max_pages):
        d = c.get(f"{SITE}/transactions", {"season": int(year), "limit": int(limit), "page": page})
        if d is None:
            return None if page == 1 else out
        pages = int(d.get("pageCount") or 1)
        for t in d.get("transactions") or []:
            tm = t.get("team") or {}
            out.append({"date": t.get("date"), "text": t.get("description"), "team": tm.get("abbreviation"),
                        "team_name": tm.get("displayName")})
        page += 1
    return out


# ── events -> game ids ──────────────────────────────────────────────────────

def event_ref(ev: dict, season: int | None = None) -> dict | None:
    """A scoreboard event (or a summary header) -> {id, start, season, seasontype, week, home, away, state,
    hs, as, status}."""
    comp = (ev.get("competitions") or [{}])[0]
    side = {x.get("homeAway"): x for x in comp.get("competitors") or []}
    h, a = side.get("home") or {}, side.get("away") or {}
    he = str((h.get("team") or {}).get("id") or h.get("id") or "")
    ae = str((a.get("team") or {}).get("id") or a.get("id") or "")
    if not he or not ae:
        return None
    sea = ev.get("season") or {}
    yr = season or sea.get("year")
    st = (ev.get("status") or comp.get("status") or {}).get("type") or {}
    return {"id": str(ev.get("id")), "start": ev.get("date") or comp.get("date"), "season": yr,
            "seasontype": sea.get("type"), "week": (ev.get("week") or {}).get("number"),
            "home": canon.abbr_from_espn(he, yr) if yr else None, "away": canon.abbr_from_espn(ae, yr) if yr else None,
            "state": st.get("state"), "status": st.get("name"), "completed": st.get("completed"),
            "hs": _int(h.get("score")), "as": _int(a.get("score")), "neutral": comp.get("neutralSite")}


def nflverse_id(season: int, week: int, away: str, home: str) -> str:
    return f"{int(season)}_{int(week):02d}_{away}_{home}"


def map_game_id(espn_event: dict, crosswalk: dict[str, str] | None = None, games: dict[str, dict] | None = None) -> str | None:
    """nflverse game_id of an ESPN event: the schedules' espn column first (`crosswalk` espn id -> game id),
    then season + week + teams, then teams + nearest kickoff among `games` (GAME records)."""
    ref = espn_event if "competitions" not in espn_event and "home" in espn_event else event_ref(espn_event)
    if not ref:
        return None
    if crosswalk and ref["id"] in crosswalk:
        return crosswalk[ref["id"]]
    if not ref.get("home") or not ref.get("away") or not ref.get("season"):
        return None
    season = int(ref["season"])
    if ref.get("week"):
        wk = int(ref["week"])
        if ref.get("seasontype") == 3:
            gt = POST_WEEK.get(wk)
            wk = canon.formats(season)["post_weeks"].get(gt) if gt else None
        if wk:
            gid = nflverse_id(season, wk, ref["away"], ref["home"])
            if games is None or gid in games:
                return gid
            gid2 = nflverse_id(season, wk, ref["home"], ref["away"])   # neutral sites: nflverse may flip sides
            if gid2 in games:
                return gid2
    if games:
        t = _iso(ref.get("start"))
        best = None
        for gid, g in games.items():
            if {g.get("home"), g.get("away")} != {ref["home"], ref["away"]}:
                continue
            gt = _iso(g.get("kickoff")) or _iso((g.get("date") or "") + "T17:00:00Z")
            if t is None or gt is None:
                continue
            dh = abs((t - gt).total_seconds()) / 3600
            if dh <= 36 and (best is None or dh < best[0]):
                best = (dh, gid)
        if best:
            return best[1]
    return None


# ── lines ───────────────────────────────────────────────────────────────────

def _side_block(item: dict, when: str) -> dict | None:
    """Open / close / current numbers of a core odds item -> {spread_home, total, ml_home, ml_away,
    spread_price, total_price} (None when the block is absent)."""
    h, a = (item.get("homeTeamOdds") or {}).get(when) or {}, (item.get("awayTeamOdds") or {}).get(when) or {}
    tot = item.get(when) or {}
    if not h and not a and not tot:
        return None
    sp = _float(((h.get("pointSpread") or {}).get("american")))
    if sp is None:
        asp = _float(((a.get("pointSpread") or {}).get("american")))
        sp = -asp if asp is not None else None
    rec = {"spread_home": sp, "total": _float(((tot.get("total") or {}).get("american"))),
           "ml_home": _am(h.get("moneyLine")), "ml_away": _am(a.get("moneyLine")),
           "spread_price": [_am(h.get("spread")), _am(a.get("spread"))],
           "total_price": [_am(tot.get("over")), _am(tot.get("under"))]}
    if all(rec[k] is None for k in ("spread_home", "total", "ml_home", "ml_away")):
        return None
    return rec


def _book(item: dict) -> dict | None:
    prov = item.get("provider") or {}
    pid, name = str(prov.get("id") or ""), prov.get("name")
    if pid in NO_PRICE or "live" in str(name or "").lower():
        return None
    h, a = item.get("homeTeamOdds") or {}, item.get("awayTeamOdds") or {}
    b = {"id": pid, "name": name, "spread_home": _float(item.get("spread")), "total": _float(item.get("overUnder")),
         "ml_home": _int(h.get("moneyLine")), "ml_away": _int(a.get("moneyLine")),
         "spread_price": [_int(h.get("spreadOdds")), _int(a.get("spreadOdds"))],
         "total_price": [_int(item.get("overOdds")), _int(item.get("underOdds"))]}
    if b["total"] == 0:
        b["total"] = None
    if all(b[k] is None for k in ("spread_home", "total", "ml_home", "ml_away")):
        return None
    op = _side_block(item, "open")
    if op is None and (item.get("initialSpread") is not None or item.get("initialOverUnder") is not None):
        op = {"spread_home": _float(item.get("initialSpread")), "total": _float(item.get("initialOverUnder")),
              "ml_home": None, "ml_away": None, "spread_price": [None, None], "total_price": [None, None]}
    cl = _side_block(item, "close")
    if op:
        b["open"] = op
    if cl:
        b["close"] = cl
    return b


def _flag_suspects(books: list[dict]) -> None:
    sp = [b["spread_home"] for b in books if b["spread_home"] is not None]
    to = [b["total"] for b in books if b["total"] is not None]
    msp = statistics.median(sp) if len(sp) >= 3 else None
    mto = statistics.median(to) if len(to) >= 3 else None
    for b in books:
        bad = False
        if msp is not None and b["spread_home"] is not None and abs(b["spread_home"] - msp) > 3.5:
            bad = True
        if mto is not None and b["total"] is not None and abs(b["total"] - mto) > 5.0:
            bad = True
        ml_h, ml_a = b["ml_home"], b["ml_away"]
        if ml_h is not None and ml_a is not None and b["spread_home"] is not None and b["spread_home"] != 0:
            # the moneyline favourite must be the spread favourite (a stale or in-play row breaks this)
            fav_ml_home = ml_h < ml_a
            if fav_ml_home != (b["spread_home"] < 0) and abs(b["spread_home"]) >= 2.5:
                bad = True
        if bad:
            b["suspect"] = True


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


def compact_lines(raw: dict | None) -> dict | None:
    """The ESPN half of a GAME's lines from a core odds answer:
    {"espn_src", "open", "close", "books", "consensus"} plus the main book's current numbers
    (spread_home, total, ml_home, ml_away) for callers that want a single line."""
    items = (raw or {}).get("items") or []
    opening = next((i for i in items if str((i.get("provider") or {}).get("id")) == OPENING), None)
    books = [b for b in (_book(i) for i in items if str((i.get("provider") or {}).get("id")) != OPENING) if b]
    if not books and opening is None:
        return None
    _flag_suspects(books)
    rank = {p: k for k, p in enumerate(PREFERRED)}
    good = [b for b in books if not b.get("suspect") and b["spread_home"] is not None]
    main = sorted(good or books, key=lambda b: (rank.get(b["id"], 99), b["id"]))[0] if books else None
    cur = {k: (main or {}).get(k) for k in ("spread_home", "total", "ml_home", "ml_away", "spread_price", "total_price")}
    op = (main or {}).get("open")
    if op is None and opening is not None:
        ob = _book({**opening, "provider": {"id": "op", "name": "Opening"}})
        if ob:
            op = {k: ob[k] for k in ("spread_home", "total", "ml_home", "ml_away", "spread_price", "total_price")}
            if ob.get("open"):                       # initialSpread of the Opening row is the opener
                op.update({k: v for k, v in ob["open"].items() if v is not None and k in ("spread_home", "total")})
    if op is not None:
        op = {**op, "src": (main or {}).get("name") if (main or {}).get("open") else "Opening"}
    cl = (main or {}).get("close") or (dict(cur) if main else None)
    if cl is not None:
        cl = {**cl, "src": main["name"]}
    pool = good or books
    cons = {"spread_home": _median([b["spread_home"] for b in pool]), "total": _median([b["total"] for b in pool]),
            "ml_home": _median([b["ml_home"] for b in pool]), "ml_away": _median([b["ml_away"] for b in pool]),
            "n_books": len(pool)} if pool else None
    out = {**cur, "espn_src": (main or {}).get("name"), "open": op, "close": cl, "consensus": cons,
           "books": [{k: b.get(k) for k in ("id", "name", "spread_home", "total", "ml_home", "ml_away", "spread_price",
                                             "total_price", "open", "close", "suspect") if b.get(k) is not None}
                     for b in books]}
    return out


def lines_from_pickcenter(summary_raw: dict | None) -> dict | None:
    """DraftKings (or the first provider) from a summary's pickcenter: current spread/total/moneyline, and
    the open and close blocks ({"odds": "+250"}, {"line": "-7", "odds": "+102"}, {"line": "o47.5", ...})."""
    picks = (summary_raw or {}).get("pickcenter") or []
    if not picks:
        return None
    rank = {p: k for k, p in enumerate(PREFERRED)}
    p = sorted(picks, key=lambda x: rank.get(str((x.get("provider") or {}).get("id")), 99))[0]
    h, a = p.get("homeTeamOdds") or {}, p.get("awayTeamOdds") or {}
    rec = {"provider": (p.get("provider") or {}).get("name"), "spread_home": _float(p.get("spread")),
           "total": _float(p.get("overUnder")), "ml_home": _int(h.get("moneyLine")), "ml_away": _int(a.get("moneyLine")),
           "spread_price": [_int(h.get("spreadOdds")), _int(a.get("spreadOdds"))],
           "total_price": [_int(p.get("overOdds")), _int(p.get("underOdds"))]}
    ml, ps, tot = p.get("moneyline") or {}, p.get("pointSpread") or {}, p.get("total") or {}
    for when in ("open", "close"):
        blk = {"spread_home": _float(((ps.get("home") or {}).get(when) or {}).get("line")),
               "total": _float(((tot.get("over") or {}).get(when) or {}).get("line")),
               "ml_home": _am(((ml.get("home") or {}).get(when) or {})),
               "ml_away": _am(((ml.get("away") or {}).get(when) or {})),
               "spread_price": [_am(((ps.get("home") or {}).get(when) or {})), _am(((ps.get("away") or {}).get(when) or {}))],
               "total_price": [_am(((tot.get("over") or {}).get(when) or {})), _am(((tot.get("under") or {}).get(when) or {}))]}
        if any(blk[k] is not None for k in ("spread_home", "total", "ml_home", "ml_away")):
            rec[when] = blk
    return rec


# ── summary -> compact live record ──────────────────────────────────────────

def _clock_s(display: Any) -> int | None:
    try:
        m, s = str(display).split(":")
        return int(m) * 60 + int(float(s))
    except (ValueError, AttributeError):
        return None


def compact_summary(raw: dict | None, game_id: str | None = None, season: int | None = None) -> dict | None:
    """CONTRACT live record from a summary answer."""
    if not raw:
        return None
    hdr = (raw.get("header") or {})
    comp = (hdr.get("competitions") or [{}])[0]
    yr = season or (hdr.get("season") or {}).get("year")
    side = {x.get("homeAway"): x for x in comp.get("competitors") or []}
    h, a = side.get("home") or {}, side.get("away") or {}
    hid, aid = str((h.get("team") or {}).get("id") or h.get("id") or ""), str((a.get("team") or {}).get("id") or a.get("id") or "")
    st = (comp.get("status") or {})
    stype = st.get("type") or {}
    state = stype.get("state")
    status = {"pre": "scheduled", "in": "live", "post": "final"}.get(state, state)
    if stype.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED"):
        status = "postponed"
    team = lambda tid: canon.abbr_from_espn(tid, yr) if (tid and yr) else None  # noqa: E731
    drives, plays = [], []
    seq = 0
    for d in ((raw.get("drives") or {}).get("previous") or []) + ([raw["drives"]["current"]] if (raw.get("drives") or {}).get("current") else []):
        dteam = team(str((d.get("team") or {}).get("id") or ""))
        start, end = d.get("start") or {}, d.get("end") or {}
        drives.append({"id": str(d.get("id")), "team": dteam, "result": d.get("result") or d.get("displayResult"),
                       "plays": d.get("offensivePlays"), "yards": d.get("yards"), "score": bool(d.get("isScore")),
                       "start_q": (start.get("period") or {}).get("number"), "start_clock": _clock_s((start.get("clock") or {}).get("displayValue")),
                       "start_yl100": start.get("yardLine") if dteam is None else _yl100(start, dteam, team(hid)),
                       "end_q": (end.get("period") or {}).get("number"), "end_clock": _clock_s((end.get("clock") or {}).get("displayValue")),
                       "elapsed": (d.get("timeElapsed") or {}).get("displayValue")})
        for p in d.get("plays") or []:
            ps = p.get("start") or {}
            pteam = team(str((ps.get("team") or {}).get("id") or "")) or dteam
            plays.append([int(p.get("sequenceNumber") or seq), (p.get("period") or {}).get("number"),
                          _clock_s((p.get("clock") or {}).get("displayValue")), pteam, ps.get("down"), ps.get("distance"),
                          ps.get("yardsToEndzone"), (p.get("type") or {}).get("text"), p.get("text"),
                          p.get("homeScore"), p.get("awayScore"), None, str(p.get("id"))])
            seq += 1
    wp = {str(x.get("playId")): x.get("homeWinPercentage") for x in raw.get("winprobability") or []}
    for row in plays:
        row[11] = wp.get(row[12])
    plays = [r[:12] for r in plays]
    sit = comp.get("situation") or raw.get("situation") or {}
    last = plays[-1] if plays else None
    rec = {"espn_id": str(comp.get("id") or hdr.get("id") or ""), "game_id": game_id, "status": status,
           "detail": stype.get("shortDetail") or stype.get("detail"),
           "period": st.get("period"), "clock": st.get("displayClock"),
           "possession": team(str(sit.get("possession") or "")) if sit.get("possession") else (last[3] if last and status == "live" else None),
           "down": sit.get("down") if sit else (last[4] if last and status == "live" else None),
           "distance": sit.get("distance") if sit else (last[5] if last and status == "live" else None),
           "yardline_100": sit.get("yardsToEndzone") if sit else (last[6] if last and status == "live" else None),
           "home": team(hid), "away": team(aid), "home_score": _int(h.get("score")), "away_score": _int(a.get("score")),
           "drives": drives, "plays": plays,
           "wp_home": (raw.get("winprobability") or [{}])[-1].get("homeWinPercentage") if raw.get("winprobability") else None,
           "odds": lines_from_pickcenter(raw), "predictor": _predictor(raw), "injuries": _injuries(raw, yr),
           "linescores": {"home": _linescores(h), "away": _linescores(a)}, "box": _boxscore(raw, yr)}
    return rec


def _linescores(c: dict) -> list[int] | None:
    ls = [_int((x or {}).get("displayValue", (x or {}).get("value"))) for x in c.get("linescores") or []]
    return ls if ls and all(v is not None for v in ls) else None


def _boxscore(raw: dict, season: int | None) -> dict | None:
    """ESPN's box score, compact: {team: {"players": {category: {"keys": [...], "rows": [[espn_id, name, *stats]]}},
    "team": [[stat name, display value], ...]}}. Stats stay as ESPN displays them ("20/30", "3-25")."""
    bx = raw.get("boxscore") or {}
    out: dict[str, dict] = {}
    for t in bx.get("players") or []:
        ab = canon.abbr_from_espn(str((t.get("team") or {}).get("id") or ""), season) if season else None
        if not ab:
            continue
        cats = {}
        for c in t.get("statistics") or []:
            rows = [[str((x.get("athlete") or {}).get("id") or ""), (x.get("athlete") or {}).get("displayName"), *(x.get("stats") or [])]
                    for x in c.get("athletes") or []]
            if c.get("name") and c.get("keys"):
                cats[c["name"]] = {"keys": list(c["keys"]), "rows": rows}
        out.setdefault(ab, {})["players"] = cats
    for t in bx.get("teams") or []:
        ab = canon.abbr_from_espn(str((t.get("team") or {}).get("id") or ""), season) if season else None
        if ab:
            out.setdefault(ab, {})["team"] = [[s.get("name"), s.get("displayValue")] for s in t.get("statistics") or [] if s.get("name")]
    return out or None


def _yl100(start: dict, dteam: str | None, home: str | None) -> int | None:
    """Drive start as yards from the offence's goal line (yardsToEndzone when ESPN gives it, else from
    ESPN's 0-100 yardLine measured from the home end zone... kept as ESPN gives it when unknown)."""
    if start.get("yardsToEndzone") is not None:
        return start.get("yardsToEndzone")
    return start.get("yardLine")


def _predictor(raw: dict) -> dict | None:
    p = raw.get("predictor") or {}
    if not p:
        return None
    h, a = p.get("homeTeam") or {}, p.get("awayTeam") or {}
    return {"header": p.get("header"), "home_proj": _float(h.get("gameProjection")), "away_proj": _float(a.get("gameProjection")),
            "home_tie": _float(h.get("teamChanceTie"))}


def _injuries(raw: dict, season: int | None) -> dict | None:
    out = {}
    for t in raw.get("injuries") or []:
        ab = canon.abbr_from_espn(str((t.get("team") or {}).get("id") or ""), season) if season else None
        rows = []
        for inj in t.get("injuries") or []:
            ath = inj.get("athlete") or {}
            rows.append({"espn_athlete": str(ath.get("id") or ""), "name": ath.get("displayName"),
                         "pos": (ath.get("position") or {}).get("abbreviation"), "status": inj.get("status"),
                         "date": inj.get("date"), "detail": ((inj.get("details") or {}).get("type"))})
        if ab:
            out[ab] = rows
    return out or None
