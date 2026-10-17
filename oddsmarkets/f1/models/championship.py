"""
Championship simulation: current points from the season store plus every remaining sprint and Grand Prix
simulated with ``race_sim``, all sharing one season-level draw per simulation so a team's season is coherent.

Current state
-------------
Points are summed from the store's ``results`` and ``sprint`` rows exactly as awarded (fastest-lap and sprint
points included as that season awarded them; ``race_sim.points_system`` gives the tables for the simulated
rounds and checks the fastest-lap bonus against the data: 2019-2024 had it, 2025 removed it). Constructor
points are the sum over that constructor's rows (a driver who changed team scores for each in turn).

Remaining rounds
----------------
Every calendar round without results is simulated; a round whose ``sessions`` has ``sprint`` and no sprint
results gets a sprint first. A round whose qualifying is already in the store uses the actual grid.

Season-level correlation (per simulation s)
-------------------------------------------
``offset_{s,d,r} = sd_{d,r} * z_{s,d} + F_{s,team(d),r} + G_{s,d,r}`` where ``z ~ N(0,1)`` is drawn once per
season (the pace estimate's error persists across the remaining rounds), ``F`` is a team random walk
``F_r = F_{r-1} + N(0, 0.06)`` s/lap per round (development race) and ``G`` a driver walk with step 0.03 s/lap.
Each race then adds its own day-to-day noise inside ``simulate_race`` (``draw_param=False``).

Ranking and countback
---------------------
Final order by points, ties broken by the number of Grand Prix wins, then second places, and so on (sprint
results do not count), exactly as the FIA countback; encoded per simulation as an integer key
``(2*points) << 50 | c1 << 45 | ... | c10`` (5 bits per count; constructors use 6 bits for 8 places).

Magic numbers (no simulation)
-----------------------------
``R_d`` = the most points driver d can still score (max race points + fastest-lap point where awarded per GP,
max sprint points per sprint). ``magic_d = max_{r != d}(P_r + R_r) - P_d + 1``: if d scores that many more
points, no rival can reach him even by winning everything left (the +1 ignores countback, so it is
conservative). ``clinched`` when magic <= 0; ``eliminated`` when ``P_d + R_d < max_r P_r``. Constructors use
both cars' maxima.

Conditionals
------------
``p_title_if_win[r]`` / ``p_title_if_not_win[r]``: the share of simulations in which the driver is champion
among those where he does / does not win round r's Grand Prix (reported for the leader for every remaining
round, and for each contender for the next round).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from oddsmarkets.f1.models import circuits as _circ
from oddsmarkets.f1.models import race_sim as _rs

logger = logging.getLogger(__name__)

TEAM_FORM_STEP, DRIVER_FORM_STEP = 0.06, 0.03
CB_PLACES_DRV, CB_BITS_DRV = 10, 5
CB_PLACES_TEAM, CB_BITS_TEAM = 8, 6
QUANTILES = (5, 25, 50, 75, 95)


# ----------------------------------------------------------------------------------------------- state

def season_state(year: int) -> dict:
    st = _circ.load_store(year)
    dp: dict[str, float] = {}
    tp: dict[str, float] = {}
    dc: dict[str, list[int]] = {}
    tc: dict[str, list[int]] = {}
    dteam: dict[str, str] = {}
    remaining: list[tuple[int, str]] = []
    completed: list[int] = []
    for k in sorted((st.get("races") or {}), key=lambda x: int(x) if str(x).isdigit() else 999):
        if not str(k).isdigit():
            continue
        race = st["races"][k]
        rnd = int(k)
        res = race.get("results") or []
        spr = race.get("sprint") or []
        has_sprint = bool((race.get("sessions") or {}).get("sprint"))
        for rows in (spr, res):
            for r in rows:
                d, t, p = r.get("driver"), r.get("constructor"), float(r.get("points") or 0)
                if not d:
                    continue
                dp[d] = dp.get(d, 0.0) + p
                tp[t] = tp.get(t, 0.0) + p
                dteam[d] = t
                dp.setdefault(d, 0.0)
        for r in res:
            if _circ.status_kind(r) == "finished":
                try:
                    pos = int(r.get("position") or 0)
                except (TypeError, ValueError):
                    pos = 0
                if 1 <= pos <= CB_PLACES_DRV:
                    dc.setdefault(r["driver"], [0] * CB_PLACES_DRV)[pos - 1] += 1
                if 1 <= pos <= CB_PLACES_TEAM:
                    tc.setdefault(r.get("constructor"), [0] * CB_PLACES_TEAM)[pos - 1] += 1
        if res:
            completed.append(rnd)
        else:
            if has_sprint and not spr:
                remaining.append((rnd, "sprint"))
            remaining.append((rnd, "race"))
    for t in set(dteam.values()):
        tp.setdefault(t, 0.0)
    return {"year": int(year), "driver_points": dp, "team_points": tp, "driver_counts": dc, "team_counts": tc, "driver_team": dteam,
            "completed": completed, "remaining": remaining}


def max_remaining(year: int, remaining: list[tuple[int, str]]) -> dict:
    ps = _rs.points_system(year)
    race_max = ps["race"][0] + (1 if ps["fastest_lap"] else 0)
    race_team = ps["race"][0] + ps["race"][1] + (1 if ps["fastest_lap"] else 0)
    spr = ps["sprint"] or [0]
    sprint_team = spr[0] + (spr[1] if len(spr) > 1 else 0)
    d = sum(race_max if kind == "race" else spr[0] for _, kind in remaining)
    t = sum(race_team if kind == "race" else sprint_team for _, kind in remaining)
    return {"driver": d, "team": t}


def magic_numbers(points: dict[str, float], max_left: float) -> dict[str, dict]:
    """Points each contender needs from the remaining rounds to be sure of the title (see module docstring)."""
    out = {}
    if not points:
        return out
    lead = max(points.values())
    for d, p in points.items():
        rivals = [q + max_left for r, q in points.items() if r != d]
        rival_max = max(rivals) if rivals else 0.0
        magic = rival_max - p + 1
        out[d] = {"points": p, "max_possible": p + max_left, "magic_number": max(0.0, magic),
                  "clinched": magic <= 0, "eliminated": p + max_left < lead,
                  "can_clinch_alone": magic <= max_left}
    return out


# ----------------------------------------------------------------------------------------------- ranking

def countback_key(points: np.ndarray, counts: np.ndarray, places: int, bits: int) -> np.ndarray:
    """Integer key (higher = better) per (sim, competitor): points, then wins, seconds, ... (FIA countback)."""
    key = np.round(points * 2).astype(np.int64) << (places * bits)
    cap = (1 << bits) - 1
    for j in range(places):
        key |= np.minimum(counts[..., j], cap).astype(np.int64) << ((places - 1 - j) * bits)
    return key


def rank_by_key(key: np.ndarray, rng: np.random.Generator | None = None) -> np.ndarray:
    """0-based final position per (sim, competitor), higher key first; identical keys split at random."""
    rng = rng or np.random.default_rng(0)
    key = np.atleast_2d(key)
    n, m = key.shape
    o1 = np.argsort(rng.random((n, m)), axis=1)                       # random tie order
    o2 = np.argsort(np.take_along_axis(-key, o1, axis=1), axis=1, kind="stable")
    order = np.take_along_axis(o1, o2, axis=1)
    pos = np.empty_like(order)
    pos[np.arange(n)[:, None], order] = np.arange(m)[None, :]
    return pos


# ----------------------------------------------------------------------------------------------- simulation

def _events(year: int, remaining: list[tuple[int, str]]) -> list[tuple[int, str, _rs.RaceInputs]]:
    st = _circ.load_store(year)
    out = []
    for rnd, kind in remaining:
        race = (st.get("races") or {}).get(str(rnd)) or {}
        before_quali = not race.get("qualifying") if kind == "race" else not race.get("sprint")
        try:
            inp = _rs.race_inputs(year, rnd, before_quali=before_quali, session=kind)
        except Exception as exc:
            logger.warning("race_inputs %s/%s %s failed: %s", year, rnd, kind, exc)
            continue
        if inp.drivers:
            out.append((rnd, kind, inp))
    return out


def simulate_championship(year: int, n: int = 20000, seed: int | None = None, *, state: dict | None = None,
                          events: list[tuple[int, str, _rs.RaceInputs]] | None = None) -> dict:
    """Drivers' and constructors' title probabilities, final position distributions, expected points, points
    quantiles, per-remaining-round expected points, magic numbers and leader conditionals. Never raises on
    missing data (an empty season returns empty tables).

    ``state`` / ``events`` override the store (tests): state as returned by ``season_state``; events a list of
    ``(round, "race"|"sprint", RaceInputs)``.
    """
    t0 = time.perf_counter()
    rng = np.random.default_rng(seed)
    state = state or season_state(year)
    if events is None:
        events = _events(year, state["remaining"])
    remaining = [(r, k) for r, k, _ in events] if events else list(state.get("remaining") or [])
    dp, tp = dict(state["driver_points"]), dict(state["team_points"])
    drivers = sorted(set(dp) | {d for _, _, inp in events for d in inp.drivers})
    teams = sorted(set(tp) | {inp.team.get(d, d) for _, _, inp in events for d in inp.drivers})
    di = {d: i for i, d in enumerate(drivers)}
    ti = {t: i for i, t in enumerate(teams)}
    D, T = len(drivers), len(teams)
    if D == 0:
        return {"year": year, "drivers": {}, "constructors": {}, "remaining": [], "n": 0, "reason": "no drivers"}

    P = np.tile(np.array([dp.get(d, 0.0) for d in drivers], float), (n, 1))
    PT = np.tile(np.array([tp.get(t, 0.0) for t in teams], float), (n, 1))
    C = np.zeros((n, D, CB_PLACES_DRV), np.int16)
    CT = np.zeros((n, T, CB_PLACES_TEAM), np.int16)
    for d, c in (state.get("driver_counts") or {}).items():
        if d in di:
            C[:, di[d], :] += np.array(c[:CB_PLACES_DRV], np.int16)
    for t, c in (state.get("team_counts") or {}).items():
        if t in ti:
            CT[:, ti[t], :] += np.array(c[:CB_PLACES_TEAM], np.int16)

    # season-level draws
    z = rng.standard_normal((n, D))
    F = np.zeros((n, T))
    G = np.zeros((n, D))
    per_round: dict[str, dict[str, np.ndarray]] = {}
    race_wins: dict[int, np.ndarray] = {}                 # round -> (n,) winner index (GP only)
    last_round = None
    for k_ev, (rnd, kind, inp) in enumerate(events):
        if rnd != last_round:
            F += TEAM_FORM_STEP * rng.standard_normal((n, T))
            G += DRIVER_FORM_STEP * rng.standard_normal((n, D))
            last_round = rnd
        cols = np.array([di[d] for d in inp.drivers])
        tcols = np.array([ti[inp.team.get(d, d)] for d in inp.drivers])
        sd = np.array([float(inp.pace_sd.get(d, 0.0)) for d in inp.drivers])
        off = sd * z[:, cols] + F[:, tcols] + G[:, cols]
        sub_seed = int(rng.integers(0, 2 ** 31 - 1))
        res = _rs.simulate_race(inp, n=n, seed=sub_seed, offsets=off, draw_param=False, return_samples=True, sprint=(kind == "sprint"))
        smp = res["_samples"]
        pts = smp["points"].astype(float)
        P[:, cols] += pts
        for j, tc in enumerate(tcols):
            PT[:, tc] += pts[:, j]
        pr = per_round.setdefault(str(rnd), {})
        pr[kind] = pts.mean(axis=0), cols
        if kind == "race":
            pos = smp["pos"].astype(int)                      # 1-based
            cls = smp["classified"]
            for place in range(1, CB_PLACES_DRV + 1):
                hit = (pos == place) & cls
                C[:, cols, place - 1] += hit.astype(np.int16)
                if place <= CB_PLACES_TEAM:
                    for j, tc in enumerate(tcols):
                        CT[:, tc, place - 1] += hit[:, j].astype(np.int16)
            winner_local = np.argmin(pos, axis=1)
            race_wins[rnd] = cols[winner_local]

    kD = countback_key(P, C, CB_PLACES_DRV, CB_BITS_DRV)
    kT = countback_key(PT, CT, CB_PLACES_TEAM, CB_BITS_TEAM)
    posD = rank_by_key(kD, rng)
    posT = rank_by_key(kT, rng)
    champD = np.argmin(posD, axis=1)
    champT = np.argmin(posT, axis=1)

    ml = max_remaining(year, remaining)
    magic_d = magic_numbers(dp, ml["driver"]) if dp else {}
    magic_t = magic_numbers(tp, ml["team"]) if tp else {}

    out_d: dict[str, Any] = {}
    for d, i in di.items():
        fin = P[:, i]
        out_d[d] = {
            "team": state.get("driver_team", {}).get(d) or next((inp.team.get(d) for _, _, inp in events if d in inp.team), None),
            "current_points": dp.get(d, 0.0), "p_title": float(np.mean(champD == i)), "exp_points": float(fin.mean()),
            "points_q": {f"q{q}": float(np.percentile(fin, q)) for q in QUANTILES},
            "pos_dist": [round(float(x), 5) for x in np.bincount(posD[:, i], minlength=D)[:D] / n],
            "exp_pos": float(posD[:, i].mean() + 1),
            "per_round_exp_points": {r: round(float(sum(v[0][list(v[1]).index(i)] for v in kinds.values() if i in v[1])), 3)
                                     for r, kinds in per_round.items()},
            **({"magic": magic_d[d]} if d in magic_d else {}),
        }
    out_t: dict[str, Any] = {}
    for t, i in ti.items():
        fin = PT[:, i]
        out_t[t] = {"current_points": tp.get(t, 0.0), "p_title": float(np.mean(champT == i)), "exp_points": float(fin.mean()),
                    "points_q": {f"q{q}": float(np.percentile(fin, q)) for q in QUANTILES},
                    "pos_dist": [round(float(x), 5) for x in np.bincount(posT[:, i], minlength=T)[:T] / n],
                    "exp_pos": float(posT[:, i].mean() + 1), **({"magic": magic_t[t]} if t in magic_t else {})}

    # conditionals
    cond: dict[str, Any] = {}
    if dp:
        leader = max(dp, key=lambda d: (dp[d], out_d[d]["p_title"]))
        li = di[leader]
        lead_c = {}
        for r, w in race_wins.items():
            won = w == li
            lead_c[str(r)] = {"p_win_round": float(won.mean()),
                              "p_title_if_win": float(np.mean(champD[won] == li)) if won.any() else None,
                              "p_title_if_not_win": float(np.mean(champD[~won] == li)) if (~won).any() else None}
        cond["leader"] = {"driver": leader, "by_round": lead_c}
        if race_wins:
            nxt = min(race_wins)
            w = race_wins[nxt]
            cont = {}
            for d, i in di.items():
                if out_d[d]["p_title"] < 0.005:
                    continue
                won = w == i
                cont[d] = {"p_win_next": float(won.mean()), "p_title": out_d[d]["p_title"],
                           "p_title_if_win_next": float(np.mean(champD[won] == i)) if won.any() else None,
                           "p_title_if_not_win_next": float(np.mean(champD[~won] == i)) if (~won).any() else None}
            cond["next_round"] = {"round": nxt, "contenders": cont}

    return {"year": int(year), "n": int(n), "drivers": out_d, "constructors": out_t, "remaining": [list(x) for x in remaining],
            "completed": state.get("completed", []), "max_points_left": ml, "conditionals": cond,
            "points_system": _rs.points_system(year), "runtime_s": round(time.perf_counter() - t0, 2),
            "sources": sorted({inp.source for _, _, inp in events})}
