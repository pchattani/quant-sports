"""
ESPN's public JSON APIs for NBA and WNBA: schedules, box scores, play-by-play,
win probability, DraftKings lines, injuries, rosters and standings.

No key and no stated rate limit; every call goes through one `Client`, which
spaces requests (`interval`, 0.5 s by default = 2 a second), retries with
back-off, counts calls against a `budget` and never raises on a bad game (it
logs and returns None). Running out of budget raises `BudgetExhausted` so a
backfill stops cleanly and resumes next time.

Endpoints (league = "nba" | "wnba"):
  site    https://site.api.espn.com/apis/site/v2/sports/basketball/{league}/
            scoreboard?dates=YYYYMMDD    one day per call (multi-day ranges answer non-JSON);
                                         leagues[0].calendar whitelists the season's game days
            summary?event=ID             box, plays, winprobability, pickcenter, injuries, header
            teams, teams/ID/roster, injuries
  v2      https://site.api.espn.com/apis/v2/sports/basketball/{league}/standings?season=Y&level=3
                                         conferences and (NBA) divisions of any season
  core    https://sports.core.api.espn.com/v2/sports/basketball/leagues/{league}/seasons/Y[/types/N]
                                         season and season-type start and end dates

Shapes verified on 1 Oct 2026 (NBA 401859967, 401810433-445, 400975384, 230115023;
WNBA 401857068): box minutes are whole minutes; games before about 2017 have no
plays (one "Start Period" row); before about 2007 `plusMinus` is 0 for everyone
(stored as null) and points in the paint are -1 (null); old team box scores put
every turnover under `teamTurnovers`, so the team `tov` here is `totalTurnovers`
and `team_tov` is that minus the players' turnovers. Summary `injuries` and
`standings` describe today, not the game's date, so injuries are kept only for
games not yet final.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import requests

from .. import canon

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball"
SITE_V2 = "https://site.api.espn.com/apis/v2/sports/basketball"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues"
HEADERS = {"User-Agent": "The Quant Hardwood (pchattani.github.io/the-quant-hardwood)"}
TIMEOUT = 30
NO_COORD = -1_000_000          # ESPN marks plays without a location with about -2.1e8
MIN_PBP_PLAYS = 50             # fewer plays than this = no real play-by-play


class BudgetExhausted(RuntimeError):
    pass


class Client:
    """Paced GET with retries and back-off; `budget` caps calls per run; `used`, `seconds` and
    `failures` are counters for sizing backfills."""

    def __init__(self, budget: int = 2000, interval: float = 0.5, retries: int = 4):
        self.budget, self.interval, self.retries = budget, interval, retries
        self.used, self.failures, self.seconds, self._last = 0, 0, 0.0, 0.0

    def get(self, url: str, params: dict | None = None) -> dict | None:
        if self.used >= self.budget:
            raise BudgetExhausted(f"ESPN budget of {self.budget} calls spent")
        for attempt in range(self.retries):
            if self.used >= self.budget:
                raise BudgetExhausted(f"ESPN budget of {self.budget} calls spent")
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = t0 = time.monotonic()
            self.used += 1
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException as exc:
                self.seconds += time.monotonic() - t0
                logger.warning("espn %s %s: %s (attempt %d)", url, params, exc, attempt + 1)
                time.sleep(3 * (attempt + 1))
                continue
            self.seconds += time.monotonic() - t0
            if r.status_code == 429 or r.status_code >= 500:
                back = int(r.headers.get("Retry-After") or 0) or 10 * (attempt + 1)
                logger.warning("espn %s answered %s; sleeping %ds", url, r.status_code, back)
                time.sleep(back)
                continue
            if r.status_code != 200:
                logger.warning("espn %s %s answered %s", url, params, r.status_code)
                self.failures += 1
                return None
            try:
                d = r.json()
            except ValueError:
                logger.warning("espn %s %s answered non-JSON", url, params)
                self.failures += 1
                return None
            return d if isinstance(d, dict) else None
        self.failures += 1
        return None


# ── fetchers ────────────────────────────────────────────────────────────────

def scoreboard_raw(c: Client, league: str, yyyymmdd: str) -> dict | None:
    """The whole scoreboard answer for one day (events plus the season calendar)."""
    return c.get(f"{SITE}/{league}/scoreboard", {"dates": str(yyyymmdd), "limit": 200})


def scoreboard(c: Client, league: str, yyyymmdd: str) -> list[dict]:
    """Raw events for one day ([] on failure); `compact_event` turns one into a GAME skeleton."""
    d = scoreboard_raw(c, league, yyyymmdd)
    return list((d or {}).get("events") or [])


def calendar(raw_scoreboard: dict | None) -> list[str]:
    """YYYYMMDD game days of the season a scoreboard answer belongs to (ESPN's whitelist)."""
    out = []
    for lg in (raw_scoreboard or {}).get("leagues") or []:
        for x in lg.get("calendar") or []:
            s = x if isinstance(x, str) else (x or {}).get("startDate") or ""
            if len(s) >= 10:
                out.append(s[:10].replace("-", ""))
    return sorted(set(out))


def summary(c: Client, league: str, event_id: str) -> dict | None:
    d = c.get(f"{SITE}/{league}/summary", {"event": str(event_id)})
    if d and not d.get("header"):
        logger.warning("espn summary %s/%s has no header", league, event_id)
        return None
    return d


def teams(c: Client, league: str) -> dict[str, dict]:
    d = c.get(f"{SITE}/{league}/teams", {"limit": 100}) or {}
    out = {}
    for sp in d.get("sports") or []:
        for lg in sp.get("leagues") or []:
            for t in lg.get("teams") or []:
                t = t.get("team") or t
                if t.get("id"):
                    out[str(t["id"])] = team_rec(t)
    return out


def roster(c: Client, league: str, team_id: str) -> list[dict]:
    d = c.get(f"{SITE}/{league}/teams/{team_id}/roster") or {}
    out = []
    for a in d.get("athletes") or []:
        if isinstance(a, dict) and "items" in a:          # some leagues group the roster by position
            out.extend(player_rec(x, team_id) for x in a.get("items") or [])
        elif isinstance(a, dict):
            out.append(player_rec(a, team_id))
    return [p for p in out if p.get("id")]


def injuries(c: Client, league: str) -> dict[str, list[list]]:
    """{team_id: [[player_id, status, detail]]} as of now."""
    d = c.get(f"{SITE}/{league}/injuries") or {}
    out: dict[str, list[list]] = {}
    for t in d.get("injuries") or []:
        tid = str(t.get("id") or "")
        for x in t.get("injuries") or []:
            pid = _athlete_id(x.get("athlete") or {})
            if tid and pid:
                out.setdefault(tid, []).append([pid, x.get("status"), _injury_detail(x)])
    return out


def season_dates(c: Client, league: str, year: int) -> dict[str, list[str | None]]:
    """{"season": [start, end], "pre"|"reg"|"post"|"playin": [start, end]} as YYYY-MM-DD (US dates)."""
    out: dict[str, list[str | None]] = {}
    d = c.get(f"{CORE}/{league}/seasons/{int(year)}")
    if not d:
        return out
    out["season"] = [_us_date(d.get("startDate")), _us_date(d.get("endDate"))]
    for n in (1, 2, 3, 5):
        t = c.get(f"{CORE}/{league}/seasons/{int(year)}/types/{n}")
        if t and t.get("startDate"):
            out[canon.SEASON_TYPES[n]] = [_us_date(t.get("startDate")), _us_date(t.get("endDate"))]
    return out


def standings(c: Client, league: str, season: int) -> dict[str, dict]:
    """{team_id: {"conference", "division"}} for any season (conference only where there are no divisions)."""
    d = c.get(f"{SITE_V2}/{league}/standings", {"season": int(season), "level": 3})
    out: dict[str, dict] = {}

    def walk(node: dict, conf: str | None, div: str | None, depth: int) -> None:
        name = node.get("name")
        if depth == 1:
            conf = name
        elif depth >= 2:
            div = name
        for e in (node.get("standings") or {}).get("entries") or []:
            tid = str((e.get("team") or {}).get("id") or "")
            if tid:
                out[tid] = {"conference": _conf(conf), "division": div}
        for ch in node.get("children") or []:
            walk(ch, conf, div, depth + 1)

    if d:
        walk(d, None, None, 0)
    return out


def _conf(name: str | None) -> str | None:
    if not name:
        return None
    n = name.lower()
    return "East" if "east" in n else "West" if "west" in n else name


# ── parsing helpers ─────────────────────────────────────────────────────────

def _int(v: Any) -> int | None:
    try:
        if v is None or v == "" or v == "--":
            return None
        return int(float(str(v).replace("+", "")))
    except (TypeError, ValueError):
        return None


def _pair(v: Any) -> tuple[int | None, int | None]:
    """'31-87' -> (31, 87)."""
    m = re.match(r"^\s*(-?\d+)\s*-\s*(\d+)\s*$", str(v or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _secs(v: Any) -> int | None:
    """Box minutes ('33' or '33:21') as seconds."""
    s = str(v or "").strip()
    if not s or s == "--":
        return None
    m = re.match(r"^(\d+):(\d{1,2})$", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    try:
        return int(round(float(s) * 60))
    except ValueError:
        return None


def clock_s(v: Any) -> float:
    """Game clock display ('12:00', '1:05.3', '28.6') as seconds remaining."""
    s = str(v or "0").strip()
    m = re.match(r"^(\d+):(\d+(?:\.\d+)?)$", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(s)
    except ValueError:
        return 0.0


def _iso(s: Any) -> str | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return str(s)


def _us_date(s: Any) -> str | None:
    """ESPN's '2026-04-03T07:00Z' boundaries are US-Pacific midnights: the date part is the US date."""
    return str(s)[:10] if s else None


def _colour(v: Any) -> str | None:
    s = str(v or "").strip().lstrip("#")
    return f"#{s.lower()}" if re.match(r"^[0-9a-fA-F]{6}$", s) else None


def _athlete_id(a: dict) -> str | None:
    if a.get("id"):
        return str(a["id"])
    for ln in a.get("links") or []:
        m = re.search(r"/id/(\d+)", ln.get("href") or "")
        if m:
            return m.group(1)
    return None


def _injury_detail(x: dict) -> str | None:
    det = x.get("details") or {}
    parts = [det.get("type"), det.get("location"), det.get("detail"), det.get("side")]
    s = " ".join(str(p) for p in parts if p and p != "Not Specified")
    if det.get("returnDate"):
        s = (s + f" (return {det['returnDate']})").strip()
    return s or x.get("shortComment") or None


def team_rec(t: dict) -> dict:
    return {"name": t.get("displayName") or " ".join(x for x in (t.get("location"), t.get("name")) if x) or None,
            "abbr": t.get("abbreviation"), "location": t.get("location"),
            "colour": _colour(t.get("color")), "alt_colour": _colour(t.get("alternateColor")),
            "conference": None, "division": None}


def player_rec(a: dict, team_id: str | None = None) -> dict:
    pos = (a.get("position") or {}).get("abbreviation")
    dob = a.get("dateOfBirth")
    return {"id": _athlete_id(a), "name": a.get("displayName") or a.get("fullName"), "short": a.get("shortName"),
            "pos": pos, "pool": canon.pool(pos), "jersey": a.get("jersey"), "dob": str(dob)[:10] if dob else None,
            "teams": [str(team_id)] if team_id else []}


def _status(st: dict) -> str:
    t = (st or {}).get("type") or {}
    name = str(t.get("name") or "").upper()
    if "POSTPONED" in name:
        return "postponed"
    if "CANCELED" in name or "CANCELLED" in name or "FORFEIT" in name:
        return "canceled"
    if "SUSPENDED" in name:
        return "in"
    state = t.get("state")
    return state if state in ("pre", "in", "post") else "pre"


def _headline(comp: dict) -> str | None:
    for n in comp.get("notes") or []:
        if n.get("headline"):
            return n["headline"]
    return None


def _series(comp: dict, event_id: str) -> dict | None:
    ss = comp.get("series") or []
    for s in [ss] if isinstance(ss, dict) else ss:
        if s.get("type") != "playoff":
            continue
        if not s.get("events"):                 # the scoreboard form: no event list
            return {"round": s.get("description") or s.get("title"), "game": None, "summary": s.get("summary")}
        ids = [str(e.get("id")) for e in s.get("events") or []]
        if str(event_id) not in ids:            # a series listed for context, not this game's
            continue
        game = ids.index(str(event_id)) + 1
        return {"round": s.get("description") or s.get("title"), "game": game, "summary": s.get("summary")}
    return None


def compact_event(ev: dict) -> dict:
    """A GAME skeleton from a scoreboard event: everything but box, odds detail and play-by-play."""
    comp = (ev.get("competitions") or [{}])[0]
    cs = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    h, a = cs.get("home") or {}, cs.get("away") or {}
    status = _status(comp.get("status") or ev.get("status") or {})
    scored = status in ("in", "post")
    lh = [_int(x.get("value") if x.get("value") is not None else x.get("displayValue")) or 0 for x in h.get("linescores") or []]
    la = [_int(x.get("value") if x.get("value") is not None else x.get("displayValue")) or 0 for x in a.get("linescores") or []]
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    season = ev.get("season") or {}
    st = canon.stype(season.get("type"), _headline(comp))
    return {
        "id": str(ev.get("id")), "date": _iso(comp.get("date") or ev.get("date")), "status": status,
        "stype": st, "neutral": bool(comp.get("neutralSite")),
        "home": str((h.get("team") or {}).get("id") or h.get("id") or ""), "away": str((a.get("team") or {}).get("id") or a.get("id") or ""),
        "hs": _int(h.get("score")) if scored else None, "as": _int(a.get("score")) if scored else None,
        "periods": max(len(lh), len(la)) or (_int((comp.get("status") or {}).get("period")) if scored else 0) or 0,
        "line": {"home": lh, "away": la}, "box": {}, "odds": _odds_scoreboard(comp, cs), "injuries": {},
        "venue": {"id": str(venue["id"]), "name": venue.get("fullName"), "city": addr.get("city"), "state": addr.get("state")} if venue.get("id") else None,
        "attendance": _int(comp.get("attendance")) or None, "series": _series(comp, ev.get("id")) if st == "post" else None, "has_pbp": False,
    }


def _odds_scoreboard(comp: dict, cs: dict) -> dict | None:
    for o in comp.get("odds") or []:
        prov = (o.get("provider") or {}).get("name")
        spread = o.get("spread")
        return {"provider": prov, "spread_home": _float(spread), "total": _float(o.get("overUnder")),
                "ml_home": _int(((o.get("homeTeamOdds") or {}).get("moneyLine"))),
                "ml_away": _int(((o.get("awayTeamOdds") or {}).get("moneyLine")))}
    return None


def _float(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _odds(raw: dict) -> dict | None:
    """DraftKings (or the first provider) from pickcenter; spread_home is the home team's line (negative = favourite)."""
    picks = raw.get("pickcenter") or []
    if not picks:
        return None
    pick = next((p for p in picks if "draftkings" in str((p.get("provider") or {}).get("name", "")).lower()), picks[0])
    ho, ao = pick.get("homeTeamOdds") or {}, pick.get("awayTeamOdds") or {}
    spread = _float(pick.get("spread"))
    if spread is not None and spread != 0:
        if ho.get("favorite") is True and spread > 0 or ao.get("favorite") is True and spread < 0:
            spread = -spread
    return {"provider": (pick.get("provider") or {}).get("name"), "spread_home": spread, "total": _float(pick.get("overUnder")),
            "ml_home": _int(ho.get("moneyLine")), "ml_away": _int(ao.get("moneyLine"))}


_TEAM_STAT = {"offensiveRebounds": "oreb", "defensiveRebounds": "dreb", "assists": "ast", "steals": "stl", "blocks": "blk",
              "totalTurnovers": "tov", "fouls": "pf", "pointsInPaint": "pts_paint", "fastBreakPoints": "pts_fastbreak",
              "turnoverPoints": "pts_off_tov", "largestLead": "largest_lead", "leadChanges": "lead_changes"}


def _team_box(stats: list[dict], players: list[list]) -> dict:
    """Team line. Counting stats are the players' sums (ESPN's team lines are garbled in some
    seasons, e.g. 2017-18 shifts assists/steals/blocks by a column); turnovers add the team
    turnovers; the extras (paint, fast break, off turnovers, largest lead, lead changes) are ESPN's."""
    t: dict[str, Any] = {k: None for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov",
                                           "team_tov", "pf", "pts_paint", "pts_fastbreak", "pts_off_tov", "largest_lead", "lead_changes")}
    raw = {s.get("name"): s.get("displayValue") for s in stats or []}
    espn = {}
    espn["fgm"], espn["fga"] = _pair(raw.get("fieldGoalsMade-fieldGoalsAttempted"))
    espn["tpm"], espn["tpa"] = _pair(raw.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
    espn["ftm"], espn["fta"] = _pair(raw.get("freeThrowsMade-freeThrowsAttempted"))
    for k, f in _TEAM_STAT.items():
        v = _int(raw.get(k))
        espn[f] = None if v is None or v < 0 else v
    idx = {"fgm": 4, "fga": 5, "tpm": 6, "tpa": 7, "ftm": 8, "fta": 9, "oreb": 10, "dreb": 11, "ast": 12, "stl": 13, "blk": 14, "pf": 16}
    for k, i in idx.items():
        vals = [r[i] for r in players]
        t[k] = sum(v or 0 for v in vals) if players and any(v is not None for v in vals) else espn.get(k)
    for k in ("pts_paint", "pts_fastbreak", "pts_off_tov", "largest_lead", "lead_changes"):
        t[k] = espn.get(k)
    ptov = sum(r[15] or 0 for r in players)
    total, team_only = espn.get("tov"), _int(raw.get("teamTurnovers"))
    if total is not None and total >= ptov:
        t["tov"] = total
    elif players:
        t["tov"] = ptov + max(0, team_only or 0)
    t["team_tov"] = None if t["tov"] is None else max(0, t["tov"] - ptov)
    return t


def _player_row(a: dict, keys: list[str]) -> list | None:
    stats = a.get("stats") or []
    if not stats:
        return None
    v = dict(zip(keys, stats))
    fgm, fga = _pair(v.get("fieldGoalsMade-fieldGoalsAttempted"))
    tpm, tpa = _pair(v.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
    ftm, fta = _pair(v.get("freeThrowsMade-freeThrowsAttempted"))
    oreb, dreb = _int(v.get("offensiveRebounds")), _int(v.get("defensiveRebounds"))
    return [_athlete_id(a.get("athlete") or {}), 1 if a.get("starter") else 0, _secs(v.get("minutes")), _int(v.get("points")),
            fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, _int(v.get("assists")), _int(v.get("steals")), _int(v.get("blocks")),
            _int(v.get("turnovers")), _int(v.get("fouls")), _int(v.get("plusMinus"))]


def compact_game(raw: dict) -> dict:
    """The contract GAME record from a raw summary (see CONTRACT.md section 1)."""
    header = raw.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    ev = {"id": header.get("id") or comp.get("id"), "season": header.get("season") or {}, "competitions": [comp]}
    g = compact_event(ev)
    # A summary carries its label in header.gameNote, not in competition notes
    # (e.g. "WNBA Commissioner's Cup Championship", which must not count in the standings).
    if header.get("gameNote") and not _headline(comp):
        g["stype"] = canon.stype((header.get("season") or {}).get("type"), header.get("gameNote"))
    gi = raw.get("gameInfo") or {}
    venue = gi.get("venue") or {}
    if venue.get("id"):
        addr = venue.get("address") or {}
        g["venue"] = {"id": str(venue["id"]), "name": venue.get("fullName"), "city": addr.get("city"), "state": addr.get("state")}
    if gi.get("attendance"):
        g["attendance"] = _int(gi.get("attendance")) or None
    g["odds"] = _odds(raw) or g.get("odds")
    g["predictor"] = _predictor(raw, g.get("home"))
    box: dict[str, dict] = {}
    stats_by_team = {str((t.get("team") or {}).get("id")): t.get("statistics") or [] for t in (raw.get("boxscore") or {}).get("teams") or []}
    for tp in (raw.get("boxscore") or {}).get("players") or []:
        tid = str((tp.get("team") or {}).get("id"))
        rows, dnp = [], []
        for st in (tp.get("statistics") or [])[:1]:
            keys = st.get("keys") or []
            for a in st.get("athletes") or []:
                pid = _athlete_id(a.get("athlete") or {})
                if not pid:
                    continue
                row = None if a.get("didNotPlay") else _player_row(a, keys)
                if row is None or (row[2] in (None, 0) and not any(row[3:17])):
                    if a.get("didNotPlay") or not a.get("stats"):
                        dnp.append([pid, a.get("reason")])
                        continue
                rows.append(row)
        box[tid] = {"players": rows, "dnp": dnp, "team": _team_box(stats_by_team.get(tid, []), rows)}
    # Before about 2007 ESPN has no plus-minus and writes 0 for everyone: store null.
    all_pm = [r[17] for b in box.values() for r in b["players"]]
    if all_pm and all(v in (0, None) for v in all_pm):
        for b in box.values():
            for r in b["players"]:
                r[17] = None
    g["box"] = box
    if g["status"] != "post":
        inj: dict[str, list[list]] = {}
        for t in raw.get("injuries") or []:
            tid = str((t.get("team") or {}).get("id") or "")
            for x in t.get("injuries") or []:
                pid = _athlete_id(x.get("athlete") or {})
                if tid and pid:
                    inj.setdefault(tid, []).append([pid, x.get("status"), _injury_detail(x)])
        g["injuries"] = inj
    plays = raw.get("plays") or []
    g["has_pbp"] = sum(1 for p in plays if str((p.get("type") or {}).get("id")) not in ("411", "412", "402")) >= MIN_PBP_PLAYS
    if g["status"] == "post" and (g["hs"] is None or g["as"] is None):
        h, a = box.get(g["home"]), box.get(g["away"])
        if h and a:
            g["hs"] = g["hs"] if g["hs"] is not None else sum(r[3] or 0 for r in h["players"])
            g["as"] = g["as"] if g["as"] is not None else sum(r[3] or 0 for r in a["players"])
    return g


def _predictor(raw: dict, home: str | None) -> dict | None:
    """ESPN's pregame matchup predictor as {"home": P(home wins)} (summary "predictor": homeTeam.gameProjection, in %),
    or None when the summary has none (ESPN drops it from many finished games, so the pregame fetch is what keeps it)."""
    pr = raw.get("predictor") or {}
    ht, at = pr.get("homeTeam") or {}, pr.get("awayTeam") or {}
    try:
        p = float(ht.get("gameProjection"))
    except (TypeError, ValueError):
        try:
            p = 100.0 - float(at.get("gameProjection"))
        except (TypeError, ValueError):
            return None
    if ht.get("id") and home and str(ht.get("id")) != str(home):
        p = 100.0 - p
    return {"home": round(p / 100.0, 4)} if 0.0 <= p <= 100.0 else None


def teams_from_summary(raw: dict) -> dict[str, dict]:
    out = {}
    comp = ((raw.get("header") or {}).get("competitions") or [{}])[0]
    for c in comp.get("competitors") or []:
        t = c.get("team") or {}
        if t.get("id"):
            out[str(t["id"])] = team_rec(t)
    return out


def teams_from_event(ev: dict) -> dict[str, dict]:
    out = {}
    for c in ((ev.get("competitions") or [{}])[0]).get("competitors") or []:
        t = c.get("team") or {}
        if t.get("id"):
            out[str(t["id"])] = team_rec(t)
    return out


def players_from_summary(raw: dict) -> dict[str, dict]:
    out = {}
    for tp in (raw.get("boxscore") or {}).get("players") or []:
        tid = str((tp.get("team") or {}).get("id"))
        for st in (tp.get("statistics") or [])[:1]:
            for a in st.get("athletes") or []:
                p = player_rec(a.get("athlete") or {}, tid)
                if p["id"]:
                    out[p["id"]] = p
    return out


def compact_pbp(raw: dict) -> dict | None:
    """Play-by-play rows (CONTRACT.md section 1) or None when the game has no real play-by-play.

    row = [seq, period, clock_s, type_id, team_id|null, [participant ids], x|null, y|null, score_value,
           shooting(0/1), scoring(0/1), home_score, away_score, text, points_attempted]
    plus "types": {type_id: ESPN type text} and "wp": {seq: home win probability}.
    """
    plays = raw.get("plays") or []
    header = raw.get("header") or {}
    gid = str(header.get("id") or "")
    if sum(1 for p in plays if str((p.get("type") or {}).get("id")) not in ("411", "412", "402")) < MIN_PBP_PLAYS:
        return None
    rows, types, seq_of = [], {}, {}
    for i, p in enumerate(plays):
        seq = _int(p.get("sequenceNumber"))
        seq = i if seq is None else seq
        ty = p.get("type") or {}
        tid = _int(ty.get("id")) or 0
        if tid and ty.get("text"):
            types[str(tid)] = str(ty["text"]).replace("\n", " ")
        c = p.get("coordinate") or {}
        x, y = _float(c.get("x")), _float(c.get("y"))
        if x is None or y is None or x < NO_COORD or y < NO_COORD or not p.get("shootingPlay"):
            x = y = None
        parts = [str((q.get("athlete") or {}).get("id")) for q in p.get("participants") or [] if (q.get("athlete") or {}).get("id")]
        team = (p.get("team") or {}).get("id")
        rows.append([seq, _int((p.get("period") or {}).get("number")) or 0, clock_s((p.get("clock") or {}).get("displayValue")), tid,
                     str(team) if team else None, parts, x, y, _int(p.get("scoreValue")) or 0, 1 if p.get("shootingPlay") else 0,
                     1 if p.get("scoringPlay") else 0, _int(p.get("homeScore")) or 0, _int(p.get("awayScore")) or 0,
                     str(p.get("text") or "").replace("\n", " ").strip(), _int(p.get("pointsAttempted")) or 0])
        if p.get("id"):
            seq_of[str(p["id"])] = seq
    wp = {}
    for w in raw.get("winprobability") or []:
        s = seq_of.get(str(w.get("playId")))
        if s is not None and w.get("homeWinPercentage") is not None:
            wp[str(s)] = round(float(w["homeWinPercentage"]), 4)
    periods = max((r[1] for r in rows), default=0)
    return {"id": gid, "periods": periods, "plays": rows, "types": types, "wp": wp}


def season_of(raw: dict) -> int | None:
    return _int(((raw.get("header") or {}).get("season") or {}).get("year"))


def event_season(ev: dict) -> int | None:
    return _int((ev.get("season") or {}).get("year"))


# ── athletes, drafts and transactions (valuation v2, trade ratings; scripts/bb_bio.py, analytics/moves.py) ──
#
#   core  .../leagues/{league}/athletes/{id}           dateOfBirth, draft {year, round, selection, team $ref},
#                                                      debutYear (verified 16 Oct 2026; WNBA records carry no draft)
#   site  .../{league}/draft?season=Y                   picks [{overall, round, pick, teamId, traded, tradeNote,
#                                                      athlete {alternativeId = the ESPN athlete id, displayName}}]
#                                                      (NBA 2003 on; WNBA about 2017 on; earlier years answer 404)
#   site  .../{league}/transactions?season=Y&limit=200&page=N
#                                                      Y = CALENDAR year; newest first; free text only:
#                                                      [{date, description, team {id, abbreviation}}]

def athlete_raw(c: Client, league: str, athlete_id: str) -> dict | None:
    return c.get(f"{CORE}/{league}/athletes/{athlete_id}")


def parse_athlete(raw: dict | None) -> dict | None:
    """{"dob", "draft": [year, round, pick, team_id] | None, "debut"} from a core athlete record."""
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    dob = raw.get("dateOfBirth")
    dr = raw.get("draft") or {}
    draft = None
    if dr.get("year"):
        m = re.search(r"/teams/(\d+)", str((dr.get("team") or {}).get("$ref") or ""))
        draft = [_int(dr.get("year")), _int(dr.get("round")), _int(dr.get("selection")), m.group(1) if m else None]
    return {"dob": str(dob)[:10] if dob else None, "draft": draft, "debut": _int(raw.get("debutYear"))}


def draft_raw(c: Client, league: str, year: int) -> dict | None:
    return c.get(f"{SITE}/{league}/draft", {"season": int(year)})


def parse_draft(raw: dict | None) -> list[list]:
    """[[overall, round, pick, team_id, athlete_id, name, traded]] in pick order ([] when ESPN has no draft)."""
    out = []
    for p in (raw or {}).get("picks") or []:
        a = p.get("athlete") or {}
        out.append([_int(p.get("overall")), _int(p.get("round")), _int(p.get("pick")), str(p.get("teamId") or "") or None,
                    str(a.get("alternativeId") or "") or None, a.get("displayName"), bool(p.get("traded"))])
    return sorted([r for r in out if r[0]], key=lambda r: r[0])


def transactions_page(c: Client, league: str, year: int, page: int = 1, limit: int = 200) -> dict | None:
    return c.get(f"{SITE}/{league}/transactions", {"season": int(year), "limit": int(limit), "page": int(page)})


def parse_transactions(raw: dict | None) -> list[dict]:
    """[{"date": "YYYY-MM-DD", "team": team_id, "abbr", "text"}] from one transactions page."""
    out = []
    for x in (raw or {}).get("transactions") or []:
        t = x.get("team") or {}
        txt = str(x.get("description") or "").strip()
        if not txt:
            continue
        out.append({"date": str(x.get("date") or "")[:10], "team": str(t.get("id") or "") or None, "abbr": t.get("abbreviation"),
                    "text": txt})
    return out
