"""
The team catalogue (`teams.json`): car pace, straight-line v cornering profile, tyres and pit
crew, strategy, reliability, points and the car/driver split, per constructor per season,
with field percentiles (100 = best; `lower` metrics rank the smallest value best).

Definitions
-----------
* car race / quali pace: the decomposition's car effect (% of lap v the field, negative =
  faster; a random walk by round); season value = mean over modelled rounds; rank = mean of the
  per-round rank among teams; trend = mean of the last third of rounds - mean of the first third
  (negative = the car got faster); latest = the last round's state.
* top speed = mean of the team's drivers' speed-trap means (km/h); corner speed = mean of their
  minimum-corner-speed deltas v the field (km/h, telemetry); straight-line bias =
  z(top speed) - z(corner speed) across the teams with both (positive = a straight-line car,
  negative = a cornering car; descriptive, ranked with higher = more straight-line).
* tyre management = mean of the drivers' tyre management index; degradation per compound = mean
  of the drivers' race_pace slopes.
* pit crew: stationary times (OpenF1 stop_ms, 1.5-30 s kept): median, best, share under 2.5 s,
  slow stops (> 4 s); pit-lane time (OpenF1 lane_ms or Jolpica duration, 8-60 s kept): median, and
  "pit lane v field" = median over races of (team's median lane time - race median), ms.
* strategy = mean over car-races of awards.strategy_gains (places gained through the stops v the
  race's norm).
* reliability: DNF rate = non-classified starts / starts; mechanical DNFs from `status`.
* both-car points rate = share of races where every car that started scored; one-twos.
* points v expected = sum over car-races of (points - walk-forward exp_points).
* car/driver split (Shapley on simulated expected points): at every finished round each car's
  score is car_{t,r} + drv_i + N(0, tau^2) (race effects; qualifying effects when there is no race
  pace), finishing orders are simulated (2,000 draws, common random numbers) and scored with the
  season's points table. For a team the players are its car and each of its drivers that round;
  v(S) = the team's expected points when the effects in S are switched on (the rest set to 0 =
  an average car / driver; every other team unchanged), and each player's Shapley value
  phi_j = sum over S not containing j of |S|! (k - |S| - 1)! / k! * (v(S + j) - v(S)).
  Car and driver values are summed over rounds; they add up to the model's expected points minus
  the all-average baseline. car_share = |car| / (|car| + sum |drivers|).
"""
from __future__ import annotations

import itertools
import logging
import math
from collections import defaultdict
from typing import Any

import numpy as np

from oddsmarkets.f1 import canon
from oddsmarkets.f1.analytics import context, fnum, mean, median, percentiles, rnd as _r, team_name
from oddsmarkets.f1.analytics.season import _alt as season_alt

logger = logging.getLogger(__name__)


def _m(key, label, group, fmt, lower=False, scope="results"):
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": lower, "scope": scope}


GROUPS = ["Results", "Car pace", "Profile", "Tyres and pit crew", "Strategy", "Reliability", "Drivers"]

METRICS: list[dict] = [
    _m("points", "Points", "Results", "1"),
    _m("points_per_race", "Points per race", "Results", "2"),
    _m("wins", "Wins", "Results", "int"),
    _m("podiums", "Podiums", "Results", "int"),
    _m("poles", "Poles", "Results", "int", False, "qualifying"),
    _m("one_twos", "One-twos", "Results", "int"),
    _m("both_points_rate", "Both cars in the points", "Results", "prob"),
    _m("avg_best_finish", "Average best-car finish", "Results", "1", True),
    _m("avg_best_grid", "Average best-car grid", "Results", "1", True),
    _m("exp_points", "Expected points", "Results", "1", False, "model"),
    _m("points_v_expected", "Points v expected", "Results", "signed", False, "model"),
    _m("car_race_pace", "Car race pace (% v field)", "Car pace", "3", True, "laps"),
    _m("car_race_rank", "Car race-pace rank", "Car pace", "1", True, "laps"),
    _m("car_quali_pace", "Car qualifying pace (% v field)", "Car pace", "3", True, "qualifying"),
    _m("car_quali_rank", "Car qualifying-pace rank", "Car pace", "1", True, "qualifying"),
    _m("car_pace_trend", "Car pace trend (%)", "Car pace", "3", True, "laps"),
    _m("car_pace_latest", "Car race pace, latest (%)", "Car pace", "3", True, "laps"),
    _m("top_speed", "Top speed (km/h)", "Profile", "1", False, "openf1"),
    _m("speed_trap_rank", "Speed-trap rank", "Profile", "1", True, "openf1"),
    _m("corner_speed", "Minimum corner speed v field (km/h)", "Profile", "1", False, "telemetry"),
    _m("straightline_bias", "Straight-line bias", "Profile", "2", False, "telemetry"),
    _m("tyre_mgmt", "Tyre management index", "Tyres and pit crew", "1", False, "laps"),
    _m("deg_soft", "Degradation: soft (s/lap/lap)", "Tyres and pit crew", "3", True, "openf1"),
    _m("deg_medium", "Degradation: medium (s/lap/lap)", "Tyres and pit crew", "3", True, "openf1"),
    _m("deg_hard", "Degradation: hard (s/lap/lap)", "Tyres and pit crew", "3", True, "openf1"),
    _m("pit_stop_ms", "Pit stop, stationary (median)", "Tyres and pit crew", "ms", True, "openf1"),
    _m("pit_best_ms", "Best pit stop", "Tyres and pit crew", "ms", True, "openf1"),
    _m("pit_under_2500", "Stops under 2.5 s", "Tyres and pit crew", "prob", False, "openf1"),
    _m("pit_slow", "Slow stops (> 4 s)", "Tyres and pit crew", "int", True, "openf1"),
    _m("pit_lane_ms", "Pit-lane time (median)", "Tyres and pit crew", "ms", True, "pit"),
    _m("pit_lane_v_field", "Pit-lane time v field", "Tyres and pit crew", "gap", True, "pit"),
    _m("stops", "Pit stops", "Tyres and pit crew", "int", False, "pit"),
    _m("strategy_gain", "Places gained through the stops", "Strategy", "2", False, "laps"),
    _m("stops_per_race", "Stops per car-race", "Strategy", "2", True, "pit"),
    _m("finish_rate", "Finish rate", "Reliability", "prob"),
    _m("dnf_rate", "DNF rate", "Reliability", "prob", True),
    _m("dnfs", "DNFs", "Reliability", "int", True),
    _m("dnf_mech", "Mechanical DNFs", "Reliability", "int", True),
    _m("car_share", "Car share of points (Shapley)", "Drivers", "prob", False, "model"),
    _m("lead_driver_share", "Lead driver's share of points", "Drivers", "prob", False),
    _m("quali_h2h_split", "Qualifying head-to-head balance", "Drivers", "prob", False, "qualifying"),
]
METRIC_KEYS = [m["key"] for m in METRICS]


# ============================================================================== car / driver split

def car_driver_split(year: int, effects: dict, n_sims: int = 2000, seed: int = 7) -> dict[str, dict]:
    """{team: {"points", "car", "drivers": {driverId: pts}, "model_points", "baseline", "car_share", "source"}} (module docstring)."""
    from oddsmarkets.f1.models.decomposition import _points_table
    car, drv = (effects or {}).get("car") or {}, (effects or {}).get("driver") or {}
    params = ((effects or {}).get("params") or {}).get("race") or {}
    source = "race"
    if not car:
        car, drv = (effects or {}).get("quali_car") or {}, (effects or {}).get("quali_driver") or {}
        params, source = ((effects or {}).get("params") or {}).get("quali") or {}, "quali"
    out: dict[str, dict] = {}
    actual: dict[str, float] = defaultdict(float)
    for r in canon.completed_rounds(year):
        race = canon.race(year, r)
        for row in (race.get("results") or []) + (race.get("sprint") or []):
            if row.get("constructor"):
                actual[row["constructor"]] += fnum(row.get("points")) or 0.0
    if not car:
        return {t: {"points": _r(p, 1), "car": None, "drivers": {}, "model_points": None, "baseline": None, "car_share": None,
                    "source": None} for t, p in actual.items()}
    tau = float(params.get("tau") or 0.3)
    pts = np.array(_points_table(year), float)
    rng = np.random.default_rng(seed)
    acc: dict[str, dict] = defaultdict(lambda: {"car": 0.0, "drivers": defaultdict(float), "model": 0.0, "base": 0.0})

    def car_at(t: str, r: int) -> float:
        states = car.get(t) or []
        prev = [s for s in states if s["round"] <= r]
        s = prev[-1] if prev else (states[0] if states else None)
        return float(s["effect"]) if s else 0.0

    for r in canon.completed_rounds(year):
        res = canon.race(year, r).get("results") or []
        lineup = [(row["driver"], row["constructor"]) for row in res if row.get("driver") and row.get("constructor")]
        if len(lineup) < 2:
            continue
        n = len(lineup)
        c = np.array([car_at(t, r) for _, t in lineup])
        dv = np.array([float((drv.get(d) or {}).get("effect", 0.0)) for d, _ in lineup])
        noise = rng.normal(0.0, tau, size=(n_sims, n))
        table = np.zeros(n)
        table[: min(n, len(pts))] = pts[: min(n, len(pts))]
        for t in sorted({t for _, t in lineup}):
            mine = [j for j, (_, tt) in enumerate(lineup) if tt == t]
            players = ["car"] + [lineup[j][0] for j in mine]
            k = len(players)
            if k > 6:                                            # 2^k worlds: skip the odd many-car entry
                continue
            vals: dict[frozenset, float] = {}
            for size in range(k + 1):
                for S in itertools.combinations(players, size):
                    s = c + dv
                    on = set(S)
                    for j in mine:
                        s[j] = (c[j] if "car" in on else 0.0) + (dv[j] if lineup[j][0] in on else 0.0)
                    ranks = np.argsort(np.argsort(s[None, :] + noise, axis=1), axis=1)
                    vals[frozenset(S)] = float(table[ranks][:, mine].sum(axis=1).mean())
            phi = {}
            for p in players:
                others = [q for q in players if q != p]
                tot = 0.0
                for size in range(len(others) + 1):
                    w = math.factorial(size) * math.factorial(k - size - 1) / math.factorial(k)
                    for S in itertools.combinations(others, size):
                        tot += w * (vals[frozenset(S) | {p}] - vals[frozenset(S)])
                phi[p] = tot
            a = acc[t]
            a["car"] += phi["car"]
            for p in players[1:]:
                a["drivers"][p] += phi[p]
            a["model"] += vals[frozenset(players)]
            a["base"] += vals[frozenset()]
    for t in set(actual) | set(acc):
        a = acc.get(t) or {"car": 0.0, "drivers": {}, "model": 0.0, "base": 0.0}
        den = abs(a["car"]) + sum(abs(x) for x in a["drivers"].values())
        out[t] = {"points": _r(actual.get(t, 0.0), 1), "car": _r(a["car"], 2), "drivers": {d: _r(x, 2) for d, x in a["drivers"].items()},
                  "model_points": _r(a["model"], 2), "baseline": _r(a["base"], 2),
                  "car_share": _r(abs(a["car"]) / den, 3) if den > 0 else None, "source": source}
    return out


# ============================================================================== catalogue

def _rank_by_round(series: dict[str, list[dict]]) -> dict[str, list[tuple[int, int]]]:
    by_round: dict[int, dict[str, float]] = defaultdict(dict)
    for t, states in series.items():
        for s in states:
            if s.get("observed", True):
                by_round[int(s["round"])][t] = float(s["effect"])
    out: dict[str, list] = defaultdict(list)
    for r, vals in sorted(by_round.items()):
        for k, t in enumerate(sorted(vals, key=lambda t: vals[t]), 1):
            out[t].append((r, k))
    return out


def _z(vals: dict[str, float]) -> dict[str, float]:
    v = [x for x in vals.values() if x is not None]
    if len(v) < 2:
        return {k: 0.0 for k in vals}
    m = sum(v) / len(v)
    s = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) or 1.0
    return {k: (x - m) / s for k, x in vals.items() if x is not None}


def build(year: int, records: dict[str, dict[int, dict]], driver_values: dict[str, dict] | None = None, effects: dict | None = None,
          colours: dict[str, str] | None = None, split: dict | None = None, forecasts: dict | None = None) -> dict:
    """teams.json (PAYLOADS: metrics, teams{name, colour, values, pct, pit{median_ms, best_ms, p_under_2500, stops}, log})."""
    from oddsmarkets.f1.analytics.awards import strategy_gains
    from oddsmarkets.f1.analytics.glossary import TEAM_DEFINITIONS
    store = canon.season(year)
    eff = effects or {}
    dv = driver_values or {}
    # car-race rows: team -> round -> [driver records]
    tr: dict[str, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for d, recs in records.items():
        for r, rec in recs.items():
            if rec.get("team"):
                tr[rec["team"]][r].append({**rec, "driver": d})
    rounds = sorted({r for recs in records.values() for r in recs})
    strat: dict[int, dict[str, float]] = {}
    lane_v: dict[int, dict[str, float]] = {}
    pit_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rounds:
        try:
            ctx = context.get(year, r)
            strat[r] = strategy_gains(ctx)
            pits = ctx.pits()
            lanes = [p["lane_ms"] for p in pits if p.get("lane_ms") and 8000 <= p["lane_ms"] <= 60000]
            race_med = median(lanes)
            per_team: dict[str, list[int]] = defaultdict(list)
            for p in pits:
                t = ctx.team_of(p["driver"])
                if t:
                    pit_rows[t].append({**p, "round": r})
                    if p.get("lane_ms") and 8000 <= p["lane_ms"] <= 60000:
                        per_team[t].append(p["lane_ms"])
            lane_v[r] = {t: median(v) - race_med for t, v in per_team.items() if race_med is not None}
        except Exception as exc:
            logger.warning("team pit/strategy %s/%s failed: %s", year, r, exc)
    car_r, car_q = eff.get("car") or {}, eff.get("quali_car") or {}
    rank_r, rank_q = _rank_by_round(car_r), _rank_by_round(car_q)
    split = split if split is not None else {}

    values: dict[str, dict] = {}
    logs: dict[str, list] = {}
    pits_out: dict[str, dict] = {}
    for t, by_r in tr.items():
        v: dict[str, Any] = {k: None for k in METRIC_KEYS}
        rows = [x for r in sorted(by_r) for x in by_r[r]]
        starts = [x for x in rows if x["started"]]
        n_r = len(by_r)
        pts = sum(x["points"] + x.get("sprint_points", 0.0) for x in rows)
        v["points"] = pts
        v["points_per_race"] = pts / n_r if n_r else None
        cls = [x for x in starts if x["classified"]]
        v["wins"] = sum(1 for x in cls if x.get("pos") == 1)
        v["podiums"] = sum(1 for x in cls if (x.get("pos") or 99) <= 3)
        v["poles"] = sum(1 for x in rows if x.get("quali_pos") == 1)
        both, onetwo, best_fin, best_grid = 0, 0, [], []
        for r in sorted(by_r):
            xs = [x for x in by_r[r] if x["started"]]
            if xs and all(x["points"] > 0 for x in xs) and len(xs) >= 2:
                both += 1
            ps = sorted(x["pos"] for x in xs if x["classified"] and x.get("pos"))
            if ps[:2] == [1, 2]:
                onetwo += 1
            if ps:
                best_fin.append(ps[0])
            gs = [x["grid"] for x in xs if x.get("grid")]
            if gs:
                best_grid.append(min(gs))
        v["both_points_rate"] = both / n_r if n_r else None
        v["one_twos"] = onetwo
        v["avg_best_finish"], v["avg_best_grid"] = mean(best_fin), mean(best_grid)
        ex = [x for x in starts if x.get("exp_points") is not None]
        if ex:
            v["exp_points"] = sum(x["exp_points"] for x in ex)
            v["points_v_expected"] = sum(x["points"] - x["exp_points"] for x in ex)
        # car pace
        sr = [s for s in car_r.get(t) or [] if s.get("observed", True)]
        if sr:
            v["car_race_pace"] = mean(s["effect"] for s in sr)
            k3 = max(1, len(sr) // 3)
            v["car_pace_trend"] = (mean(s["effect"] for s in sr[-k3:]) - mean(s["effect"] for s in sr[:k3])) if len(sr) >= 3 else None
            v["car_pace_latest"] = sr[-1]["effect"]
            v["car_race_rank"] = mean(k for _, k in rank_r.get(t, []))
        sq = [s for s in car_q.get(t) or [] if s.get("observed", True)]
        if sq:
            v["car_quali_pace"] = mean(s["effect"] for s in sq)
            v["car_quali_rank"] = mean(k for _, k in rank_q.get(t, []))
        # profile from the drivers
        team_drivers = sorted({x["driver"] for x in rows})
        dvs = [dv.get(d) or {} for d in team_drivers]
        v["top_speed"] = mean(x.get("speed_trap_kph") for x in dvs)
        v["speed_trap_rank"] = mean(x.get("speed_trap_rank") for x in dvs)
        v["corner_speed"] = mean(x.get("corner_speed_delta") for x in dvs)
        v["tyre_mgmt"] = mean(x.get("tyre_mgmt") for x in dvs)
        for c in ("soft", "medium", "hard"):
            v[f"deg_{c}"] = mean(x.get(f"deg_{c}") for x in dvs)
        # pit crew
        prs = pit_rows.get(t, [])
        stat = [p["stop_ms"] for p in prs if p.get("stop_ms") and 1500 <= p["stop_ms"] <= 30000]
        lane = [p["lane_ms"] for p in prs if p.get("lane_ms") and 8000 <= p["lane_ms"] <= 60000]
        if stat:
            v["pit_stop_ms"], v["pit_best_ms"] = median(stat), min(stat)
            v["pit_under_2500"] = sum(1 for x in stat if x < 2500) / len(stat)
            v["pit_slow"] = sum(1 for x in stat if x > 4000)
        if lane:
            v["pit_lane_ms"] = median(lane)
        lv = [lane_v[r][t] for r in lane_v if t in lane_v[r]]
        v["pit_lane_v_field"] = median(lv)
        stops = [x["stops"] for x in starts if "stops" in x]
        if stops:
            v["stops"], v["stops_per_race"] = sum(stops), mean(stops)
        sg = [strat[r][x["driver"]] for r in strat for x in by_r.get(r, []) if x["driver"] in strat[r]]
        v["strategy_gain"] = mean(sg)
        # reliability
        if starts:
            dnf = [x for x in starts if not x["classified"]]
            v["finish_rate"], v["dnf_rate"] = len(cls) / len(starts), len(dnf) / len(starts)
            v["dnfs"], v["dnf_mech"] = len(dnf), sum(1 for x in dnf if x["kind"] == "dnf_mech")
        # drivers
        sp = split.get(t) or {}
        v["car_share"] = sp.get("car_share")
        by_d: dict[str, float] = defaultdict(float)
        for x in rows:
            by_d[x["driver"]] += x["points"] + x.get("sprint_points", 0.0)
        v["lead_driver_share"] = max(by_d.values()) / pts if pts > 0 else None
        qh = []
        for r in by_r:
            qs = sorted((x["quali_pos"], x["driver"]) for x in by_r[r] if x.get("quali_pos"))
            if len(qs) >= 2:
                qh.append(qs[0][1])
        if qh:
            top = max(set(qh), key=qh.count)
            v["quali_h2h_split"] = qh.count(top) / len(qh)
        values[t] = v
        cr = {s["round"]: s["effect"] for s in car_r.get(t) or []}
        cq = {s["round"]: s["effect"] for s in car_q.get(t) or []}
        logs[t] = [{"round": r, "points": _r(sum(x["points"] + x.get("sprint_points", 0.0) for x in by_r[r]), 1),
                    "car_pace": _r(cr.get(r), 4), "quali_pace": _r(cq.get(r), 4),
                    "dnfs": sum(1 for x in by_r[r] if x["started"] and not x["classified"]),
                    "drivers": [x["driver"] for x in by_r[r]]} for r in sorted(by_r)]
        pits_out[t] = {"median_ms": int(median(stat)) if stat else None, "best_ms": min(stat) if stat else None,
                       "p_under_2500": _r(v["pit_under_2500"], 4), "stops": len(prs),
                       "lane_median_ms": int(median(lane)) if lane else None,
                       "stop_ms": [p["stop_ms"] for p in prs if p.get("stop_ms") and 1500 <= p["stop_ms"] <= 30000],
                       "stop_rounds": [p.get("round") for p in prs if p.get("stop_ms") and 1500 <= p["stop_ms"] <= 30000]}
    zt = _z({t: v["top_speed"] for t, v in values.items() if v["top_speed"] is not None and v["corner_speed"] is not None})
    zc = _z({t: v["corner_speed"] for t, v in values.items() if v["top_speed"] is not None and v["corner_speed"] is not None})
    for t in zt:
        values[t]["straightline_bias"] = zt[t] - zc.get(t, 0.0)
    pct: dict[str, dict] = defaultdict(dict)
    for m in METRICS:
        for t, x in percentiles({t: v[m["key"]] for t, v in values.items()}, m["lower"]).items():
            pct[t][m["key"]] = x
    out = {}
    for t, v in values.items():
        rv = {}
        for m in METRICS:
            x = v[m["key"]]
            rv[m["key"]] = None if x is None else (int(round(x)) if m["fmt"] in ("int", "ms", "gap") else round(float(x), 4))
        out[t] = {"name": team_name(store, t), "colour": (colours or {}).get(t), **season_alt(t), "drivers": sorted({x["driver"] for r in tr[t].values() for x in r}),
                  "values": rv, "pct": dict(pct.get(t, {})), "pit": pits_out.get(t), "log": logs.get(t, []),
                  "split": split.get(t)}
    metrics = [{**m, "desc": TEAM_DEFINITIONS.get(m["key"], "")} for m in METRICS]
    return {"ok": True, "year": year, "metrics": metrics, "groups": GROUPS, "teams": out}
