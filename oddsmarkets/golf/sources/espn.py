"""
ESPN's public golf JSON (no key). Two calls make a season:

  https://site.api.espn.com/apis/site/v2/sports/golf/{tour}/scoreboard?dates=YYYY
      every event of the season (49 for the PGA Tour in 2025, about 38 MB) with each player's rounds and, on the PGA
      Tour, every hole: linescores[round].linescores[hole] = {value: strokes, period: hole, scoreType.displayValue:
      the hole against par ("E", "-1", "+2")}. No positions, statuses or course.
  https://site.web.api.espn.com/apis/site/v2/sports/golf/leaderboard?league={tour}&event={id}
      one event (about 0.2 MB): purse, major, rounds, cut round, line and count; the courses with each hole's par and
      yardage; per player the position ("T5", isTie), status (finish, cut, wd, dq), total, earnings, FedEx Cup points
      and each round's strokes, nines and tee time. No holes.

Shapes verified on 4 Nov 2026 (PGA 2001, 2010, 2025, 2026; DP World 2025; LIV 2025). Every call goes through the
paced client, which never raises on a bad answer; `BudgetExhausted` stops a backfill cleanly.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from oddsmarkets.tennis.sources._client import BudgetExhausted, Client  # noqa: F401 - re-exported for scripts

from .. import canon

logger = logging.getLogger(__name__)

SITE = "https://site.api.espn.com/apis/site/v2/sports/golf"
WEB = "https://site.web.api.espn.com/apis/site/v2/sports/golf"
UA = "The Quant Sports golf (pchattani.github.io; golf analytics, non-commercial)"


def client(budget: int = 2000, interval: float = 1.0) -> Client:
    return Client(budget=budget, interval=interval, name="espn-golf", headers={"User-Agent": UA})


# ── fetchers ────────────────────────────────────────────────────────────────

def season_scoreboard(c: Client, tour: str, year: int) -> dict | None:
    return c.get(f"{SITE}/{canon.tour_key(tour)}/scoreboard", {"dates": str(int(year))})


def week_scoreboard(c: Client, tour: str) -> dict | None:
    """This week's events only (a few hundred KB, where the season's PGA Tour scoreboard is about 40 MB)."""
    return c.get(f"{SITE}/{canon.tour_key(tour)}/scoreboard")


def leaderboard(c: Client, tour: str, event_id: str) -> dict | None:
    return c.get(f"{WEB}/leaderboard", {"league": canon.tour_key(tour), "event": str(event_id)})


# ── parsing ─────────────────────────────────────────────────────────────────

def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _rel(s) -> int | None:
    """A hole or round against par from its display value: "E" 0, "-1", "+2"."""
    s = str(s or "").strip()
    if s == "E":
        return 0
    m = re.match(r"^([+-]?\d+)$", s)
    return int(m.group(1)) if m else None


def _status(raw: dict, table: dict) -> str | None:
    name = (((raw or {}).get("type") or {}).get("name")) or ""
    return table.get(name, name.replace("STATUS_", "").lower() or None)


def _country(athlete: dict) -> str | None:
    f = (athlete or {}).get("flag") or {}
    return f.get("alt") or None


def parse_scoreboard(raw: dict | None, tour: str) -> dict:
    """{"events": [{id, name, start, end, status, season_type}], "players": {pid: {name, country}},
    "rounds": [{event, pid, round, strokes}], "holes": [{event, pid, round, hole, strokes, par}]}."""
    out: dict[str, Any] = {"events": [], "players": {}, "rounds": [], "holes": []}
    for e in (raw or {}).get("events") or []:
        eid = str(e.get("id") or "")
        if not eid:
            continue
        comp = (e.get("competitions") or [{}])[0]
        while isinstance(comp, list):
            comp = comp[0] if comp else {}
        field: list[str] = []
        out["events"].append({"id": eid, "tour": tour, "name": e.get("name"), "start": str(e.get("date") or "")[:10] or None,
                              "end": str(e.get("endDate") or "")[:10] or None,
                              "status": _status(e.get("status") or comp.get("status"), canon.EVENT_STATUS),
                              "season_type": ((e.get("season") or {}).get("slug")), "field": field})
        for c in comp.get("competitors") or []:
            pid = str(c.get("id") or "")
            if not pid or c.get("type") not in (None, "athlete"):
                continue
            field.append(pid)
            a = c.get("athlete") or {}
            out["players"].setdefault(pid, {"name": a.get("displayName") or a.get("fullName"), "country": _country(a)})
            for r in c.get("linescores") or []:
                rnd = int(r.get("period") or 0)
                holes = r.get("linescores") or []
                strokes = _num(r.get("value"))
                if rnd and strokes is not None and strokes > 0:
                    out["rounds"].append({"event": eid, "pid": pid, "round": rnd, "strokes": int(strokes), "holes": len(holes)})
                for h in holes:
                    v, rel = _num(h.get("value")), _rel((h.get("scoreType") or {}).get("displayValue"))
                    hole = int(h.get("period") or 0)
                    if not hole or v is None or v <= 0:
                        continue
                    out["holes"].append({"event": eid, "pid": pid, "round": rnd, "hole": hole, "strokes": int(v),
                                         "par": int(v) - rel if rel is not None else None})
    return out


def _pos(raw: dict) -> tuple[int | None, bool]:
    p = (raw or {}).get("position") or {}
    m = re.match(r"^T?(\d+)$", str(p.get("displayName") or ""))
    return (int(m.group(1)) if m else None), bool(p.get("isTie"))


def parse_leaderboard(raw: dict | None, tour: str) -> dict | None:
    """{"event": {...meta, courses}, "players": {...}, "results": [...], "rounds": [...]}, or None for an empty answer."""
    evs = (raw or {}).get("events") or []
    if not evs:
        return None
    e = evs[0]
    t = e.get("tournament") or {}
    comp = (e.get("competitions") or [{}])[0]
    while isinstance(comp, list):
        comp = comp[0] if comp else {}
    courses = []
    for c in e.get("courses") or []:
        courses.append({"id": str(c.get("id") or ""), "name": c.get("name"), "par": c.get("shotsToPar"), "yards": c.get("totalYards"),
                        "host": bool(c.get("host")),
                        "holes": [[h.get("number"), h.get("shotsToPar"), h.get("totalYards")] for h in c.get("holes") or []]})
    win = e.get("winner") or {}
    event = {"id": str(e.get("id") or ""), "tour": tour, "name": e.get("name"), "short": e.get("shortName"),
             "start": str(e.get("date") or "")[:10] or None, "end": str(e.get("endDate") or "")[:10] or None,
             "status": _status(e.get("status") or comp.get("status"), canon.EVENT_STATUS),
             "purse": _num(e.get("purse")), "major": bool(t.get("major")), "tournament_id": str(t.get("id") or "") or None,
             "tournament": t.get("displayName"), "rounds": t.get("numberOfRounds"), "cut_round": t.get("cutRound"),
             "cut_score": t.get("cutScore"), "cut_count": t.get("cutCount"),
             "scoring": ((t.get("scoringSystem") or {}).get("name")), "playoff": bool(e.get("playoffType")),
             "winner": str(((win.get("athlete") or win).get("id")) or "") or None, "courses": courses}
    comps = [c for c in comp.get("competitors") or [] if isinstance(c, dict)]
    # team formats (the Zurich Classic's pairs): team scores, no player's own; the event is kept, its rows are not
    event["team"] = any("~t:" in str(c.get("uid") or "") or not c.get("athlete") for c in comps)
    out: dict[str, Any] = {"event": event, "players": {}, "results": [], "rounds": []}
    for c in [] if event["team"] else comps:
        pid = str(c.get("id") or "")
        if not pid:
            continue
        a = c.get("athlete") or {}
        out["players"][pid] = {"name": a.get("displayName"), "country": _country(a), "amateur": bool(c.get("amateur") or a.get("amateur"))}
        st = c.get("status") or {}
        pos, tie = _pos(st)
        stats = {s.get("name"): s for s in c.get("statistics") or [] if isinstance(s, dict)}
        sc = c.get("score") or {}
        out["results"].append({"event": event["id"], "pid": pid, "pos": pos, "tie": tie, "status": _status(st, canon.STATUS),
                               "strokes": _num(sc.get("value")) if isinstance(sc, dict) else None,
                               "to_par": _num((stats.get("scoreToPar") or {}).get("value")),
                               "earnings": _num(c.get("earnings")), "points": _num((stats.get("cupPoints") or {}).get("value")),
                               "amateur": bool(c.get("amateur")), "order": c.get("sortOrder")})
        for r in c.get("linescores") or []:
            v = _num(r.get("value"))
            rnd = int(r.get("period") or 0)
            if not rnd or v is None or v <= 0 or r.get("isPlayoff"):
                continue
            out["rounds"].append({"event": event["id"], "pid": pid, "round": rnd, "strokes": int(v),
                                  "out": _num(r.get("outScore")), "in": _num(r.get("inScore")),
                                  "tee_time": r.get("teeTime"), "to_par": _rel(r.get("displayValue"))})
    return out
