"""
ESPN's public NHL JSON: game lines (moneyline, puck line, total; open and close; several books) and attendance.
No key, CORS *; paced at <= 1 request a second.

Endpoints (verified 1 Oct 2026):
  site  https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD   events of a US day
          (ESPN team ids, UTC start, status, scores, attendance, scoreboard odds for upcoming games)
        .../summary?event=ID      pickcenter (DraftKings: moneyline / puck line / total with open and close blocks
                                  {"odds": "-148"}, {"line": "-1.5", "odds": "+180"}, {"line": "o6.5", ...}),
                                  plays with coordinates and strength, onIce, gameInfo (attendance, venue)
  core  https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events/ID/competitions/ID/odds
          items per provider. 2019-20 offshore / international books (Bet365, BetStars, Betradar, Caesars, ...),
          2022-23 -> US books with open / close blocks (1,288 of 1,400 games in 2022-23; all from 2023-24) (Caesars, BetMGM, ESPN BET, DraftKings, ...). `spread` is the
          HOME puck line, signed (home favoured -1.5): verified on 2019-10-15 MIN@TOR (TOR -1.5, -161), 2023-10-20
          CGY@CBJ (CBJ +1.5, +190) and 2026-09-30 PIT@PHI (PHI -1.5, -148). Rows named "... Live Odds" are in-play
          and dropped; books whose "current" numbers are in-play captures (moneyline overround outside 1.00-1.15, a
          total a goal from the median) are flagged `suspect` and never chosen as the main line (2023-10-20 CGY@CBJ:
          DraftKings, Bet365, SugarHouse show +190 / +105); consensus / teamrankings / numberfire rows carry no prices of their own.

ESPN events map to NHL gameIds by the two teams (ESPN team id -> NHL code of the season) and the nearest UTC start
within 30 hours (each game used once).
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Any

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl"
CORE = "https://sports.core.api.espn.com/v2/sports/hockey/leagues/nhl"
INTERVAL = 1.0
PREFERRED = ("100", "40", "58", "38", "31", "45", "52", "47", "41", "36", "1001", "39", "37", "50", "25", "20")
NO_PRICE = {"1002", "1003", "1004", "1007", "2000"}


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

def scoreboard(c: Client, yyyymmdd: str) -> list[dict] | None:
    d = c.get(f"{SITE}/scoreboard", {"dates": str(yyyymmdd).replace("-", ""), "limit": 100})
    return None if d is None else list(d.get("events") or [])


def summary(c: Client, event_id: str) -> dict | None:
    return c.get(f"{SITE}/summary", {"event": str(event_id)})


def odds(c: Client, event_id: str) -> dict | None:
    return c.get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds", {"limit": 100})


# ── events -> gameId ────────────────────────────────────────────────────────

def event_ref(ev: dict, season: int | None = None) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    side = {x.get("homeAway"): x for x in comp.get("competitors") or []}
    h, a = side.get("home") or {}, side.get("away") or {}
    ht, at = h.get("team") or {}, a.get("team") or {}
    he, ae = str(ht.get("id") or h.get("id") or ""), str(at.get("id") or a.get("id") or "")
    if not he or not ae:
        return None
    st = (ev.get("status") or comp.get("status") or {}).get("type") or {}
    return {"id": str(ev.get("id")), "start": ev.get("date") or comp.get("date"),
            "home": canon.abbr_from_espn(he, ht.get("abbreviation"), season),
            "away": canon.abbr_from_espn(ae, at.get("abbreviation"), season),
            "state": st.get("state"), "completed": st.get("completed"), "hs": _int(h.get("score")),
            "as": _int(a.get("score")), "attendance": _int(comp.get("attendance")) or None,
            "odds": comp.get("odds")}


def match_events(events: list[dict], games: dict[str, dict], max_hours: float = 30.0,
                 season: int | None = None) -> dict[str, str]:
    """ESPN event id -> NHL gameId (str), by the two teams and the nearest start (each game used once)."""
    by_pair: dict[tuple, list[tuple[str, dict]]] = {}
    for gid, g in games.items():
        by_pair.setdefault((g.get("home"), g.get("away")), []).append((gid, g))
    cands = []
    for ev in events:
        ref = ev if "competitions" not in ev and "home" in ev else event_ref(ev, season)
        if not ref or not ref.get("home") or not ref.get("away"):
            continue
        t = _iso(ref["start"])
        for gid, g in by_pair.get((ref["home"], ref["away"]), []):
            gt = _iso(g.get("start")) or _iso((g.get("date") or "") + "T23:00:00Z")
            if t is None or gt is None:
                continue
            dh = abs((t - gt).total_seconds()) / 3600
            if dh <= max_hours:
                cands.append((dh, ref["id"], gid))
    out: dict[str, str] = {}
    used: set[str] = set()
    for dh, eid, gid in sorted(cands):
        if eid in out or gid in used:
            continue
        out[eid] = gid
        used.add(gid)
    return out


# ── lines ───────────────────────────────────────────────────────────────────
# Lines record (GAME.lines): {"src", "ml": [home, away], "puck_line": {"home", "price": [home, away]} | None,
#  "total": {"line", "over", "under"} | None, "open": {ml, puck_line, total} | None, "close": {...} | None,
#  "books": [{id, name, ml, puck_line, total, open?, close?, suspect?}], "consensus": {...} | None}

# Plausible hockey numbers: some 2022-23 core-odds close blocks carry American prices in the line fields
# (close.total.line 110, close.puck_line.home -250); such a line is dropped, never stored as a line.
PL_MAX = 4.5
TOTAL_RANGE = (3.0, 12.0)


def plausible_pl(x) -> bool:
    return x is not None and 0 < abs(float(x)) <= PL_MAX


def plausible_total(x) -> bool:
    return x is not None and TOTAL_RANGE[0] <= float(x) <= TOTAL_RANGE[1]


def _pl(home_line: float | None, hp: int | None, ap: int | None) -> dict | None:
    if home_line is None or home_line == 0 or not plausible_pl(home_line):
        return None
    return {"home": home_line, "price": [hp, ap]}


def _tot(line: float | None, over: int | None, under: int | None) -> dict | None:
    if not line or not plausible_total(line):
        return None
    return {"line": line, "over": over, "under": under}


def repair_lines(lines: dict | None) -> int:
    """Drop implausible puck lines and totals (prices stored as lines) from a stored GAME.lines record and its
    books' main / open / close blocks, in place. Returns the number of fields dropped."""
    if not isinstance(lines, dict):
        return 0
    n = 0

    def fix(blk):
        nonlocal n
        if not isinstance(blk, dict):
            return
        pl = blk.get("puck_line")
        if isinstance(pl, dict) and not plausible_pl(pl.get("home")):
            blk["puck_line"] = None
            n += 1
        tot = blk.get("total")
        if isinstance(tot, dict) and not plausible_total(tot.get("line")):
            blk["total"] = None
            n += 1
    for blk in (lines, lines.get("open"), lines.get("close")):
        fix(blk)
    for b in lines.get("books") or []:
        for blk in (b, b.get("open"), b.get("close")):
            fix(blk)
    for k in ("open", "close"):
        if isinstance(lines.get(k), dict) and not any(lines[k].get(x) for x in ("ml", "puck_line", "total")):
            lines[k] = None
    return n


def _block(item: dict, when: str) -> dict | None:
    h, a = (item.get("homeTeamOdds") or {}).get(when) or {}, (item.get("awayTeamOdds") or {}).get(when) or {}
    tot = item.get(when) or {}
    if not h and not a and not tot:
        return None
    sp = _float((h.get("pointSpread") or {}).get("american"))
    if sp is None:
        asp = _float((a.get("pointSpread") or {}).get("american"))
        sp = -asp if asp is not None else None
    ml = [_am(h.get("moneyLine")), _am(a.get("moneyLine"))]
    rec = {"ml": ml if any(x is not None for x in ml) else None,
           "puck_line": _pl(sp, _am(h.get("spread")), _am(a.get("spread"))),
           "total": _tot(_float((tot.get("total") or {}).get("american")), _am(tot.get("over")), _am(tot.get("under")))}
    return rec if any(rec.values()) else None


def _book(item: dict) -> dict | None:
    prov = item.get("provider") or {}
    pid, name = str(prov.get("id") or ""), prov.get("name")
    if pid in NO_PRICE or "live" in str(name or "").lower():
        return None
    h, a = item.get("homeTeamOdds") or {}, item.get("awayTeamOdds") or {}
    ml = [_int(h.get("moneyLine")), _int(a.get("moneyLine"))]
    sp = _float(item.get("spread"))
    cur_h = (h.get("current") or {}).get("pointSpread") or {}
    if cur_h.get("american") not in (None, ""):
        sp = _float(cur_h.get("american"))
    b = {"id": pid, "name": name, "ml": ml if any(x is not None for x in ml) else None,
         "puck_line": _pl(sp, _int(h.get("spreadOdds")), _int(a.get("spreadOdds"))),
         "total": _tot(_float(item.get("overUnder")), _int(item.get("overOdds")), _int(item.get("underOdds")))}
    if not b["ml"] and not b["puck_line"] and not b["total"]:
        return None
    for when in ("open", "close"):
        blk = _block(item, when)
        if blk:
            b[when] = blk
    if b["ml"] and None not in b["ml"] and b["puck_line"] and b["ml"][0] != b["ml"][1]:
        if (b["ml"][0] < b["ml"][1]) != (b["puck_line"]["home"] < 0) and abs(b["puck_line"]["home"]) <= 1.5:
            b["suspect"] = True          # the moneyline favourite should lay the 1.5 goals
    return b


def _implied(american: int | None) -> float | None:
    if american is None or american == 0:
        return None
    return 100 / (american + 100) if american > 0 else -american / (-american + 100)


def overround(ml: list | None) -> float | None:
    """Sum of the two implied probabilities of a moneyline pair (pre-game books sit at about 1.02-1.08)."""
    if not ml or None in ml:
        return None
    a, b = _implied(ml[0]), _implied(ml[1])
    return None if a is None or b is None else a + b


def _flag_suspects(books: list[dict]) -> None:
    """In-play or stale captures: a moneyline pair whose overround is outside 1.00-1.15 (both sides plus money
    after a game started), or a total a goal or more from the other books' median."""
    tots = [b["total"]["line"] for b in books if b.get("total")]
    med = statistics.median(tots) if len(tots) >= 3 else None
    for b in books:
        ov = overround(b.get("ml"))
        if ov is not None and not 1.0 <= ov <= 1.15:
            b["suspect"] = True
        if med is not None and b.get("total") and abs(b["total"]["line"] - med) >= 1.0:
            b["suspect"] = True


def _median(vals):
    vals = [v for v in vals if v is not None]
    return statistics.median(vals) if vals else None


LINES_VERSION = 2          # 2: in-play books flagged suspect and never chosen


def _assemble(books: list[dict]) -> dict | None:
    if not books:
        return None
    _flag_suspects(books)
    rank = {p: k for k, p in enumerate(PREFERRED)}
    good = [b for b in books if not b.get("suspect") and b.get("ml") and None not in b["ml"]]
    main = sorted(good or books, key=lambda b: (rank.get(b["id"], 99), b["id"]))[0]
    pool = good or books
    cons = {"ml": [_median([b["ml"][0] for b in pool if b.get("ml")]), _median([b["ml"][1] for b in pool if b.get("ml")])],
            "total": _median([(b.get("total") or {}).get("line") for b in pool]), "n_books": len(pool)}
    return {"src": main["name"], "ml": main.get("ml"), "puck_line": main.get("puck_line"), "total": main.get("total"),
            "open": main.get("open"), "close": main.get("close"), "consensus": cons, "v": LINES_VERSION,
            "books": [{k: b[k] for k in ("id", "name", "ml", "puck_line", "total", "open", "close", "suspect") if k in b}
                      for b in books]}


def compact_lines(raw: dict | None) -> dict | None:
    """GAME.lines from a core odds answer: the preferred sound book's lines with open / close, every book, consensus."""
    items = (raw or {}).get("items") or []
    return _assemble([b for b in (_book(i) for i in items) if b])


def reselect(lines: dict | None) -> dict | None:
    """Re-flag the stored books of a core-odds lines record and re-pick its main line (no network)."""
    if not lines or not lines.get("books"):
        return lines
    books = [{k: v for k, v in b.items() if k != "suspect"} for b in lines["books"]]
    return _assemble(books) or lines


def lines_from_pickcenter(summary_raw: dict | None) -> dict | None:
    """GAME.lines from a summary's pickcenter (DraftKings first), with its open and close blocks."""
    picks = (summary_raw or {}).get("pickcenter") or []
    if not picks:
        return None
    rank = {p: k for k, p in enumerate(PREFERRED)}
    p = sorted(picks, key=lambda x: rank.get(str((x.get("provider") or {}).get("id")), 99))[0]
    h, a = p.get("homeTeamOdds") or {}, p.get("awayTeamOdds") or {}
    ml = [_int(h.get("moneyLine")), _int(a.get("moneyLine"))]
    rec = {"src": (p.get("provider") or {}).get("name"), "ml": ml if any(x is not None for x in ml) else None,
           "puck_line": _pl(_float(p.get("spread")), _int(h.get("spreadOdds")), _int(a.get("spreadOdds"))),
           "total": _tot(_float(p.get("overUnder")), _int(p.get("overOdds")), _int(p.get("underOdds"))),
           "open": None, "close": None, "books": None, "consensus": None}
    mlb, ps, tot = p.get("moneyline") or {}, p.get("pointSpread") or {}, p.get("total") or {}
    for when in ("open", "close"):
        g = lambda node, side: ((node.get(side) or {}).get(when) or {})  # noqa: E731
        blk_ml = [_am(g(mlb, "home")), _am(g(mlb, "away"))]
        blk = {"ml": blk_ml if any(x is not None for x in blk_ml) else None,
               "puck_line": _pl(_float(g(ps, "home").get("line")), _am(g(ps, "home")), _am(g(ps, "away"))),
               "total": _tot(_float(g(tot, "over").get("line")), _am(g(tot, "over")), _am(g(tot, "under")))}
        if any(blk.values()):
            rec[when] = blk
    if not rec["ml"] and not rec["puck_line"] and not rec["total"]:
        return None
    return rec


def lines_from_scoreboard(ev: dict) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    return compact_lines({"items": comp.get("odds") or []})


def attendance_from_summary(summary_raw: dict | None) -> int | None:
    return _int(((summary_raw or {}).get("gameInfo") or {}).get("attendance")) or None
