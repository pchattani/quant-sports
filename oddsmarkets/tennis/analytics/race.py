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

The race page's "how the race is shaping up" fields (24 Oct 2026; season_sim.race_extras has the definitions):
 "bounds" {pid: [certain Race points, most still reachable]}, "status" {pid: "in" | "out"} (mathematically
 certain only), "stakes" [chance conditioned on a result at an event in progress or starting within ten days; an
 in-progress row carries "next" {"id", "opp", "round", "date"}: the player's next scheduled match there],
 "left" {"future_max", "in_progress_max", "near"};
 "week" {pid: [[event id, round, "W" | "L" | "A"]]}: each tracked player's tour-level results in the seven days to
 the simulation date, one row per event: the last round played and won it ("W", a title when the round is "F"),
 lost it ("L"), or still in the draw ("A", the round of the next match). Results only, no look-ahead;
 "profiles" {"keys": [...], "rows": {pid: [...]}, "floor"}: the season catalogue's numbers (players.json values and
 percentiles among the season's qualified players, the METRICS_SPEC tennis peer group) for the Race top 40 and the
 official top 100, positional on "keys" to stay small (profile()).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from oddsmarkets.tennis import analytics as an

logger = logging.getLogger(__name__)
HISTORY_MAX = 400
HISTORY_MIN_P = 0.001
WEEK_DAYS = 7
WEEK_TOP = 40
# profile keys: ("v", key) is the season value, ("p", key) its percentile (players.json values / pct)
PROFILE_KEYS = [("p", "elo"), ("p", "games_won_pct"), ("p", "hold"), ("p", "brk"), ("p", "win_v_top50"),
                ("p", "elo_hard"), ("p", "elo_clay"), ("p", "elo_grass"), ("p", "serve_rating"), ("p", "return_rating"),
                ("p", "tb_pct"), ("p", "dec_pct"), ("p", "close_sets_pct"), ("p", "tb_per_set"),
                ("v", "elo"), ("v", "elo_hard"), ("v", "elo_clay"), ("v", "elo_grass"), ("v", "serve_rating"),
                ("v", "return_rating"), ("v", "hold"), ("v", "brk"), ("v", "woe_pm"), ("v", "wins_over_exp"),
                ("v", "tb_over"), ("v", "dec_over"), ("v", "elo_d30"), ("v", "elo_d90"), ("v", "matches"),
                ("v", "wins"), ("v", "losses")]


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


def week_results(td: an.TourData, as_of, pids) -> dict[str, list]:
    """{pid: [[event id, round, "W" | "L" | "A"]]} for the seven days to `as_of` (module docstring)."""
    d = an.day(as_of)
    want = {str(p) for p in pids}
    if d is None or not want:
        return {}
    lo = d - timedelta(days=WEEK_DAYS)
    last: dict = {}
    for m in td.matches(td.current).values():
        if not an.is_tour_level(m) or str(m.get("level")) not in an.POINT_LEVELS:
            continue
        md = an.day(m.get("date"))
        st = m.get("status")
        if st not in an.FINISHED and st not in ("live", "upcoming"):
            continue
        # results to the simulation date; a scheduled match up to three days on still says "in the draw"
        if md is None or md < lo or md > (d if st in an.FINISHED else d + timedelta(days=3)):
            continue
        for p in (m.get("p1"), m.get("p2")):
            p = str(p or "")
            if p not in want:
                continue
            key = (p, m.get("event"))
            r = an.ROUND_ORDER.get(str(m.get("round")), -1)
            res = ("W" if str(m.get("winner") or "") == p else "L") if st in an.FINISHED else "A"
            old = last.get(key)
            if old is None or r > old[0] or (r == old[0] and res == "A"):
                last[key] = (r, str(m.get("round") or ""), res, str(md))
    out: dict = {}
    for (p, eid), (r, rnd, res, md) in sorted(last.items(), key=lambda kv: kv[1][3]):
        if res == "W" and rnd != "F":
            res = "A"                     # won the last match on record and not yet out: still in the draw
        out.setdefault(p, []).append([eid, rnd, res])
    return out


def next_match(td: an.TourData, pid: str, eid: str) -> dict | None:
    """The player's next scheduled match at an event in progress: {"id", "opp", "round", "date"}, or None."""
    best = None
    for m in td.matches(td.current).values():
        if m.get("event") != eid or m.get("status") not in ("live", "upcoming"):
            continue
        p1, p2 = str(m.get("p1") or ""), str(m.get("p2") or "")
        if pid not in (p1, p2):
            continue
        k = (an.ROUND_ORDER.get(str(m.get("round")), 99), str(m.get("date") or ""))
        if best is None or k < best[0]:
            best = (k, {"id": m.get("id"), "opp": p2 if pid == p1 else p1 or None, "round": m.get("round"),
                        "date": m.get("date")})
    return best[1] if best else None


def profiles(cat: dict | None, pids) -> dict:
    """The race page's player profiles from the season catalogue (module docstring), {} without one."""
    players = (cat or {}).get("players") or {}
    rows = {}
    for p in pids:
        r = players.get(str(p))
        if not r:
            continue
        v, pc = r.get("values") or {}, r.get("pct") or {}
        rows[str(p)] = [(pc if k == "p" else v).get(key) for k, key in PROFILE_KEYS] + [1 if r.get("qualified") else 0]
    if not rows:
        return {}
    return {"keys": [f"{k}:{key}" for k, key in PROFILE_KEYS] + ["qualified"], "rows": rows,
            "floor": (cat or {}).get("floor"), "year": (cat or {}).get("year")}


def profile_ids(rankings_rows, race_rows, top_rank: int = 100, top_race: int = WEEK_TOP) -> list[str]:
    """The official top `top_rank` and the Race top `top_race`, Race order first."""
    out = [str(p) for p, _ in (race_rows or [])[:top_race]]
    for r in rankings_rows or []:
        if int(r[0]) <= top_rank and str(r[1]) not in out:
            out.append(str(r[1]))
    return out


def build(td: an.TourData, sim: dict | None, futures: dict | None = None, prev: dict | None = None,
          cat: dict | None = None, profile_pids=None) -> dict:
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
            "runtime_s": sim.get("runtime_s"), "history": hist, **shaping(td, sim, cat, profile_pids)}


def shaping(td: an.TourData, sim: dict, cat: dict | None = None, profile_pids=None) -> dict:
    """The "how the race is shaping up" fields (module docstring); each is left out when it has nothing."""
    out: dict = {}
    for k in ("bounds", "status", "left"):
        if sim.get(k):
            out[k] = sim[k]
    stakes = []
    for r in sim.get("stakes") or []:
        r = dict(r)
        if r.get("in_progress"):
            nx = next_match(td, str(r["pid"]), str(r["event"]))
            if nx:
                r["next"] = nx
        stakes.append(r)
    if stakes:
        out["stakes"] = stakes
    race_now = sim.get("race") or {}
    top = sorted(race_now, key=lambda p: -(race_now[p].get("now") or 0))[:WEEK_TOP]
    week = week_results(td, sim.get("as_of"), top)
    if week:
        out["week"] = week
    prof = profiles(cat, profile_pids if profile_pids is not None else top)
    if prof:
        out["profiles"] = prof
    return out


def proj_ranks(sim: dict | None) -> dict[str, int]:
    """Projected year-end rank = order of mean simulated year-end points."""
    pts = (sim or {}).get("points") or {}
    order = sorted(pts, key=lambda p: -(pts[p].get("mean") or 0))
    return {p: i + 1 for i, p in enumerate(order)}
