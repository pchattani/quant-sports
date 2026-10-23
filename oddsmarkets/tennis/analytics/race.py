"""
data/<T>/race.json: C's rest-of-season simulation (season_sim.for_tour) with the markets beside it.

{"n_sims","finals_qual": {pid: p},"year_end_no1": {pid: p},"rank_dist": {pid: [p by rank 1..20, 21+]},
 "points": {pid: {"mean","p05","p95","now"}},"remaining_events": [{"id","name","level","start","method"}],
 "market": {"finals_qual": BINARY | null,"year_end_no1": TITLE | null},
 plus "race" {pid: {"now","mean","p05","p95"}}, "finals_title", "simplifications", "basis", "snapshot", "as_of",
 "history": [{"as_of","n_sims","finals_qual": {pid: p},"year_end_no1": {pid: p}}]}

"history" is a rolling series of the season simulation's year-end chances, one snapshot per simulation date (a later
run on the same date replaces that date's snapshot), oldest first, for a chance-over-time chart. Each run carries the
previous race.json's series forward and appends its own; only the season of the current snapshot is kept (at most
HISTORY_MAX dates), and players are listed at HISTORY_MIN_P or above. It starts with the first build that has it
(22 Oct 2026): earlier runs were not stored. A failed simulation keeps the series unchanged.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from oddsmarkets.tennis import analytics as an

logger = logging.getLogger(__name__)
HISTORY_MAX = 400
HISTORY_MIN_P = 0.001


def simulate(td: an.TourData, n: int = 10000, ctx=None) -> dict:
    from oddsmarkets.tennis.models import season_sim as SS
    stores = {y: td.store(y) for y in (td.current, td.current - 1) if y in td.years}
    return SS.for_tour(td.tour, as_of=td.today, n=n, stores=stores, ctx=ctx or td.today_context())


def _title(t: dict | None) -> dict | None:
    if not t or not isinstance(t, dict):
        return None
    keep = ("available", "reason", "probs", "sources", "by_source", "implied_total", "overround", "markets", "kind", "field",
            "quoted", "unmatched")
    return {k: t.get(k) for k in keep if k in t}


def _snap(probs: dict | None) -> dict:
    return {p: an.prob(v) for p, v in sorted((probs or {}).items()) if v is not None and float(v) >= HISTORY_MIN_P}


def history(prev: dict | None, sim: dict | None) -> list[dict]:
    """The previous race.json's "history" with this simulation's snapshot added (module docstring)."""
    old = [h for h in ((prev or {}).get("history") or []) if isinstance(h, dict) and h.get("as_of")]
    if not sim or not sim.get("ok") or not sim.get("as_of"):
        return old
    as_of = str(sim["as_of"])[:10]
    snap = {"as_of": as_of, "n_sims": sim.get("n_sims"), "finals_qual": _snap(sim.get("finals_qual")),
            "year_end_no1": _snap(sim.get("year_end_no1"))}
    keep = [h for h in old if str(h["as_of"])[:4] == as_of[:4] and str(h["as_of"])[:10] < as_of]
    return (keep + [snap])[-HISTORY_MAX:]


def build(td: an.TourData, sim: dict | None, futures: dict | None = None, prev: dict | None = None) -> dict:
    """race.json; `prev` is the race.json on disk (its "history" is carried forward)."""
    hist = history(prev, sim)
    if not sim or not sim.get("ok"):
        return {"ok": False, "reason": (sim or {}).get("reason") or "the season simulation did not run", "tour": td.tour,
                **({"history": hist} if hist else {})}
    evs = td.events(td.current)
    prev = {}
    if td.current - 1 in td.years:
        for eid, ev in td.events(td.current - 1).items():
            prev[ev.get("tid") or eid.rsplit("-", 1)[0]] = ev
    rem = []
    for e in sim.get("events") or []:
        ev = evs.get(e.get("id"))
        if ev is None:                      # a future event listed from last season's calendar (shifted 52 weeks)
            old = prev.get(str(e.get("id") or "").rsplit("-", 1)[0]) or {}
            d = an.day(old.get("start"))
            ev = dict(old, start=e.get("start") or ((d + timedelta(days=364)).isoformat() if d else None))
        rem.append({"id": e.get("id"), "name": ev.get("name"), "level": ev.get("level"), "start": ev.get("start"),
                    "surface": ev.get("surface"), "method": e.get("method"), "draw_size": e.get("draw_size")})
    fut = futures or {}
    rd = sim.get("rank_dist") or {}
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "as_of": sim.get("as_of"), "n_sims": sim.get("n_sims"),
            "finals_qual": {p: an.prob(v) for p, v in (sim.get("finals_qual") or {}).items()},
            "year_end_no1": {p: an.prob(v) for p, v in (sim.get("year_end_no1") or {}).items()},
            "finals_title": {p: an.prob(v) for p, v in (sim.get("finals_title") or {}).items()},
            "rank_dist": {p: [an.prob(x) for x in v] for p, v in rd.items()},
            "rank_dist_labels": sim.get("rank_dist_labels") or list(range(1, 21)) + ["21+"],
            "points": sim.get("points") or {}, "race": sim.get("race") or {}, "remaining_events": rem,
            "market": {"finals_qual": _title(fut.get("finals_qual")), "year_end_no1": _title(fut.get("year_end_no1")),
                       "finals_winner": _title(fut.get("finals_winner")), "top10": _title(fut.get("top10"))},
            "simplifications": sim.get("simplifications") or [], "basis": sim.get("basis"), "snapshot": sim.get("snapshot"),
            "runtime_s": sim.get("runtime_s"), "history": hist}


def proj_ranks(sim: dict | None) -> dict[str, int]:
    """Projected year-end rank = order of mean simulated year-end points."""
    pts = (sim or {}).get("points") or {}
    order = sorted(pts, key=lambda p: -(pts[p].get("mean") or 0))
    return {p: i + 1 for i, p in enumerate(order)}
