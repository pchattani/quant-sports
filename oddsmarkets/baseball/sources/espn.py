"""
ESPN's public MLB JSON: game lines (moneyline, run line, total; open and close; several books, 2015->)
and ESPN's win probability. No key, CORS *; paced at <= 1 request a second.

Endpoints (verified 1 Oct 2026):
  site  https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD
          events with ESPN team ids, UTC start, status, series summary (one call per day)
        .../summary?event=ID      pickcenter (DraftKings ml / run line / total), winprobability (~1 MB: used
                                  only for current-season games)
  core  https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/events/ID/competitions/ID/odds
          items per provider (~7 KB): 2015-2019 offshore books (5Dimes, Bovada, Pinnacle, ...), 2020-2024 US books
          (Caesars, DraftKings (old), FanDuel, MGM, ...), 2026 DraftKings only; consensus / teamrankings /
          numberfire rows carry no prices of their own. homeTeamOdds/awayTeamOdds.open/close hold the opening and
          closing moneyline and run line (2023->); item.open/close hold the total.

Run-line sign: items carry `spread` unsigned (1.5); the side comes from pointSpread when given and non-zero,
else the moneyline favourite lays the runs.

ESPN events map to gamePk by the two teams (ESPN team id -> MLBAM id) and the nearest UTC start within 30 hours
either side (`match_events`, max_hours; doubleheaders resolve by start time). ESPN dates are UTC: a 8 pm ET game is the next day.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .. import canon
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb"
CORE = "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb"
INTERVAL = 1.0
PREFERRED = ("100", "40", "1005", "47", "1001", "2", "45", "31", "20", "18", "19")   # DraftKings first, then FanDuel, MGM, ...
NO_PRICE = {"1002", "1003", "1004"}                                              # teamrankings, numberfire, consensus


def _int(v: Any) -> int | None:
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _am(node: Any) -> int | None:
    """American odds from a node {"american": "-117", ...} or a number."""
    if isinstance(node, dict):
        v = node.get("american") or node.get("alternateDisplayValue")
        if v in (None, "", "EVEN", "even"):
            return 100 if v and v.lower() == "even" else None
        return _int(str(v).replace("+", ""))
    return _int(node)


def _point(node: Any) -> float | None:
    if not isinstance(node, dict):
        return None
    v = node.get("american") or node.get("alternateDisplayValue")
    f = _float(str(v).replace("+", "")) if v not in (None, "") else None
    return None if f is None or f == 0 else f


def _iso(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(str(s), "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


# ── fetchers ────────────────────────────────────────────────────────────────

def scoreboard(c: Client, yyyymmdd: str) -> list[dict] | None:
    d = c.get(f"{SITE}/scoreboard", {"dates": str(yyyymmdd), "limit": 100})
    return None if d is None else list(d.get("events") or [])


def summary(c: Client, event_id: str) -> dict | None:
    return c.get(f"{SITE}/summary", {"event": str(event_id)})


def odds(c: Client, event_id: str) -> dict | None:
    return c.get(f"{CORE}/events/{event_id}/competitions/{event_id}/odds", {"limit": 50})


# ── events -> gamePk ────────────────────────────────────────────────────────

def event_ref(ev: dict) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    side = {x.get("homeAway"): x for x in comp.get("competitors") or []}
    h, a = side.get("home") or {}, side.get("away") or {}
    he, ae = str((h.get("team") or {}).get("id") or h.get("id") or ""), str((a.get("team") or {}).get("id") or a.get("id") or "")
    if not he or not ae:
        return None
    st = (ev.get("status") or comp.get("status") or {}).get("type") or {}
    return {"id": str(ev.get("id")), "start": ev.get("date") or comp.get("date"), "home": canon.tid_from_espn(he),
            "away": canon.tid_from_espn(ae), "state": st.get("state"), "hs": _int(h.get("score")), "as": _int(a.get("score")),
            "odds": comp.get("odds")}


def match_events(events: list[dict], games: dict[str, dict], max_hours: float = 30.0) -> dict[str, str]:
    """ESPN event id -> gamePk, by the two teams and the nearest start (each game used once)."""
    by_pair: dict[tuple, list[tuple[str, dict]]] = {}
    for gpk, g in games.items():
        by_pair.setdefault((g.get("home"), g.get("away")), []).append((gpk, g))
    cands = []
    for ev in events:
        ref = ev if "home" in ev and "start" in ev and "competitions" not in ev else event_ref(ev)
        if not ref or not ref["home"] or not ref["away"]:
            continue
        t = _iso(ref["start"])
        for gpk, g in by_pair.get((ref["home"], ref["away"]), []):
            gt = _iso(g.get("start")) or _iso((g.get("date") or "") + "T23:00:00Z")
            if t is None or gt is None:
                continue
            dh = abs((t - gt).total_seconds()) / 3600
            if dh <= max_hours:
                cands.append((dh, ref["id"], gpk))
    out: dict[str, str] = {}
    used: set[str] = set()
    for dh, eid, gpk in sorted(cands):
        if eid in out or gpk in used:
            continue
        out[eid] = gpk
        used.add(gpk)
    return out


# ── lines ───────────────────────────────────────────────────────────────────

def _signed(point: float | None, hml: int | None, aml: int | None) -> float | None:
    """The home run line: the moneyline favourite lays the runs. ESPN's pointSpread signs are flipped in
    many pre-2026 payloads (a -130 favourite shown at +1.5 priced +160), so only its size is trusted; the
    sign is kept as given only for a pick'em moneyline."""
    if point is None:
        return None
    size = abs(point)
    if hml is None or aml is None or hml == aml:
        return point
    return -size if hml < aml else size


def _book(item: dict) -> dict | None:
    pid = str((item.get("provider") or {}).get("id") or "")
    name = (item.get("provider") or {}).get("name")
    h, a = item.get("homeTeamOdds") or {}, item.get("awayTeamOdds") or {}
    hml, aml = _int(h.get("moneyLine")), _int(a.get("moneyLine"))
    if hml is None and aml is None and item.get("overUnder") is None:
        return None
    total = _float(item.get("overUnder"))
    total = None if not total else total
    spread = _float(item.get("spread"))
    spread = abs(spread) if spread else None
    cur_h, cur_a = h.get("current") or {}, a.get("current") or {}
    hp = _signed(_point(cur_h.get("pointSpread")) or spread, hml, aml)
    rl = None
    if hp is not None:
        rl = {"home": hp, "price": [_am(cur_h.get("spread")), _am(cur_a.get("spread"))]}
    b = {"id": pid, "name": name, "ml": [hml, aml], "rl": rl,
         "total": {"line": total, "over": _int(item.get("overOdds")), "under": _int(item.get("underOdds"))} if total else None}
    for when in ("open", "close"):
        oh, oa, ot = h.get(when) or {}, a.get(when) or {}, item.get(when) or {}
        ml = [_am(oh.get("moneyLine")), _am(oa.get("moneyLine"))]
        p = _signed(_point(oh.get("pointSpread")), ml[0], ml[1])
        tl = _float(((ot.get("total") or {}).get("american")) if isinstance(ot.get("total"), dict) else None)
        rec = {"ml": ml if any(x is not None for x in ml) else None,
               "rl": {"home": p, "price": [_am(oh.get("spread")), _am(oa.get("spread"))]} if p is not None else None,
               "total": {"line": tl, "over": _am(ot.get("over")), "under": _am(ot.get("under"))} if tl else None}
        if any(rec.values()):
            b[when] = rec
    return b


def compact_lines(raw: dict | None) -> dict | None:
    """The GAME "lines" record from a core odds answer: the preferred book's ml / rl / total, its open and
    close when ESPN keeps them, and every book's current line."""
    items = (raw or {}).get("items") or []
    books = [b for b in (_book(i) for i in items) if b]
    if not books:
        return None
    priced = [b for b in books if b["id"] not in NO_PRICE and b["ml"][0] is not None]
    rank = {p: k for k, p in enumerate(PREFERRED)}
    main = sorted(priced or books, key=lambda b: rank.get(b["id"], 99))[0]
    cons = next((b for b in books if b["id"] == "1004"), None)
    out = {"src": main["name"], "ml": main["ml"], "rl": main["rl"], "total": main["total"],
           "open": main.get("open"), "close": main.get("close"),
           "books": [{k: b[k] for k in ("id", "name", "ml", "rl", "total")} for b in books]}
    if cons:
        out["consensus"] = {"ml": cons["ml"], "total": (cons["total"] or {}).get("line") if cons["total"] else None}
    return out


def lines_from_pickcenter(summary_raw: dict | None) -> dict | None:
    """DraftKings (or the first provider) from a summary's pickcenter, as a lines record."""
    picks = (summary_raw or {}).get("pickcenter") or []
    if not picks:
        return None
    return compact_lines({"items": picks})


def lines_from_scoreboard(ev: dict) -> dict | None:
    comp = (ev.get("competitions") or [{}])[0]
    return compact_lines({"items": comp.get("odds") or []})


def win_probability(summary_raw: dict | None) -> list[list] | None:
    """ESPN's win probability per play: [[playId, home_win_pct], ...]."""
    wp = (summary_raw or {}).get("winprobability") or []
    out = [[str(x.get("playId")), _float(x.get("homeWinPercentage"))] for x in wp if x.get("homeWinPercentage") is not None]
    return out or None
