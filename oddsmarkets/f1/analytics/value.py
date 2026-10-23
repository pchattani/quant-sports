"""
Driver value, constructors ranked by car pace, constructors' strengths and needs, and the driver-swap simulator
(docs/VALUE_SECTIONS.md sections 1-3; payloads in PAYLOADS.md "As built": value.json, swap.json, needs.json).

Driver value (no positions in F1)
---------------------------------
From the season's car/driver decomposition (models/decomposition.py), in percent of a lap, signs turned so that
POSITIVE = FASTER:
* pace above team-mate: minus the driver effect (race pace; qualifying separately). Team-mates share the car, so the
  driver effect is identified only within a team and shrunk toward 0 (drv ~ N(0, sigma_d^2)): a driver beside a
  weak team-mate looks better than he is, and two equal team-mates both read 0. Its standard error is shown.
* pace above the field: minus (the car's latest race-pace state + the driver effect): what the driver and car are
  worth together now.
* constructors: minus the car's latest race-pace state (the random walk's last round), its season mean, the latest
  qualifying state and the change over the last five rounds (development).
0.1% of a lap is about 0.09 s on a 90-second lap.

Driver-swap simulator: exact swaps through the championship simulation
----------------------------------------------------------------------
"Put driver X in car Y": X swaps seats with W, one of Y's drivers. For every remaining round's race inputs
(championship._events) the swap gives X the seat W had (W's pace in that car, plus the decomposition's driver
difference: mu_X' = mu_W + (drv_X - drv_W) x ref lap / 100; W likewise in X's car), the seat's qualifying grid
distribution (or grid slot), the car's share of the retirement risk (mechanical) with the driver's own incident
risk, and the team label (so the team's form walk and constructors' points follow the car). Every pair of current
drivers on different teams is simulated with the same seed as a baseline run (common random numbers), and the page
adds each swap's change to the published 20,000-run championship. Cached on the race inputs' numbers, so a
season whose inputs have not changed is not re-simulated.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

VERSION = "f1value-1"
SWAP_N = 1000
MIN_RACES = 5
GRADE_CUTS = ((80, "A"), (60, "B"), (40, "C"), (20, "D"), (0, "F"))
SWAP_COLS = ["a_pts", "a_title", "a_pos", "b_pts", "b_title", "b_pos", "ta_pts", "ta_title", "tb_pts", "tb_title"]
AREAS = [  # key, label, teams.json metric (its pct is direction-aware, 100 = best), what it measures
    ("race_pace", "Race pace (car)", "car_race_pace", "the car's race-pace effect, % of a lap against the field"),
    ("quali_pace", "Qualifying pace (car)", "car_quali_pace", "the car's qualifying-pace effect, % of a lap"),
    ("development", "Development through the season", "car_pace_trend", "change in the car's race-pace state over the season"),
    ("reliability", "Reliability", "dnf_mech", "mechanical retirements"),
    ("tyres", "Tyre management", "tyre_mgmt", "degradation against the field across compounds"),
    ("pit", "Pit stops", "pit_stop_ms", "median stationary time"),
    ("strategy", "Strategy", "strategy_gain", "places gained or lost through the pit cycle"),
    ("straights", "Straight-line speed", "top_speed", "speed-trap and top speeds"),
    ("corners", "Cornering", "corner_speed", "minimum corner speeds against the field (telemetry)"),
]
LABEL = ("Model suggestions from on-track pace only: driver contracts, availability, money and team politics are not "
         "considered. F1 has no trade market; a swap is a what-if.")


def grade(p: Any) -> str | None:
    if p is None:
        return None
    for cut, g in GRADE_CUTS:
        if p >= cut:
            return g
    return "F"


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _rnd(x: Any, nd: int = 3) -> float | None:
    v = _num(x)
    return None if v is None else round(v, nd)


def percentiles(values: dict[str, float | None]) -> dict[str, int]:
    """100 = best (highest), (below + half the ties) / (n - 1); a lone entry gets 50."""
    vals = {k: v for k, v in values.items() if v is not None}
    n = len(vals)
    if n <= 1:
        return {k: 50 for k in vals}
    xs = sorted(vals.values())
    out = {}
    for k, v in vals.items():
        below = sum(1 for x in xs if x < v)
        tie = sum(1 for x in xs if x == v) - 1
        out[k] = int(round(100.0 * (below + 0.5 * tie) / (n - 1)))
    return out


def latest(series: list[dict] | None) -> dict | None:
    rows = [r for r in (series or []) if _num(r.get("effect")) is not None]
    return max(rows, key=lambda r: r.get("round") or 0) if rows else None


def _trend(series: list[dict] | None, back: int = 5) -> float | None:
    rows = sorted([r for r in (series or []) if _num(r.get("effect")) is not None], key=lambda r: r.get("round") or 0)
    if len(rows) < 2:
        return None
    a = rows[max(0, len(rows) - 1 - back)]
    return -(rows[-1]["effect"] - a["effect"])                     # positive = got faster


# ---------------------------------------------------------------------------------------------- the value page

DRIVER_COLS = ["id", "name", "team", "races", "pace_tm", "pace_tm_se", "quali_tm", "quali_tm_se", "pace_field", "pct", "trend",
               "points", "exp_points", "p_title", "elo_tm"]
TEAM_COLS = ["id", "name", "car", "car_se", "car_mean", "quali_car", "trend", "rank", "points", "p_title"]


def value_payload(year: int, effects: dict, prev_effects: dict | None, dcat: dict | None, tcat: dict | None, champ: dict | None,
                  current: bool) -> dict:
    eff_d = effects.get("driver") or {}
    eff_q = effects.get("quali_driver") or {}
    car = effects.get("car") or {}
    qcar = effects.get("quali_car") or {}
    D = (dcat or {}).get("drivers") or {}
    T = (tcat or {}).get("teams") or {}
    chd = ((champ or {}).get("drivers") or {}) if champ else {}
    cht = ((champ or {}).get("constructors") or {}) if champ else {}
    prev = (prev_effects or {}).get("driver") or {}
    rows = []
    for d, e in eff_d.items():
        info = D.get(d) or {}
        t = info.get("team") or (chd.get(d) or {}).get("team")
        cl = latest(car.get(t)) if t else None
        q = eff_q.get(d) or {}
        pv = prev.get(d)
        vals = info.get("values") or {}
        rows.append({"id": d, "name": info.get("name") or d, "team": t, "races": int(e.get("races") or 0),
                     "pace_tm": -e["effect"], "pace_tm_se": e.get("se"), "quali_tm": -q["effect"] if q.get("effect") is not None else None,
                     "quali_tm_se": q.get("se"), "pace_field": -(cl["effect"] + e["effect"]) if cl else None,
                     "trend": (-e["effect"] + pv["effect"]) if pv and pv.get("effect") is not None and (pv.get("races") or 0) >= MIN_RACES else None,
                     "points": vals.get("points"), "exp_points": (chd.get(d) or {}).get("exp_points"), "p_title": (chd.get(d) or {}).get("p_title"),
                     "elo_tm": vals.get("elo_teammate")})
    pct = percentiles({r["id"]: r["pace_tm"] for r in rows if r["races"] >= MIN_RACES})
    for r in rows:
        r["pct"] = pct.get(r["id"])
    rows.sort(key=lambda r: -(r["pace_field"] if r["pace_field"] is not None else -9))
    teams = []
    for t, s in car.items():
        cl = latest(s)
        ql = latest(qcar.get(t))
        eff = [x["effect"] for x in s if _num(x.get("effect")) is not None and x.get("observed", True)]
        teams.append({"id": t, "name": (T.get(t) or {}).get("name") or t, "car": -cl["effect"] if cl else None, "car_se": (cl or {}).get("se"),
                      "car_mean": -float(np.mean(eff)) if eff else None, "quali_car": -ql["effect"] if ql else None, "trend": _trend(s),
                      "points": ((T.get(t) or {}).get("values") or {}).get("points"), "p_title": (cht.get(t) or {}).get("p_title")})
    teams.sort(key=lambda r: -(r["car"] if r["car"] is not None else -9))
    for i, r in enumerate(teams, 1):
        r["rank"] = i
    best_tm = [r["id"] for r in sorted([r for r in rows if r["races"] >= MIN_RACES], key=lambda r: -r["pace_tm"])[:10]]
    best_field = [r["id"] for r in rows if r["races"] >= MIN_RACES and r["pace_field"] is not None][:10]

    def pack(rs, cols, nd):
        return [[(_rnd(r.get(c), nd.get(c, 4)) if isinstance(r.get(c), float) else r.get(c)) for c in cols] for r in rs]
    nd = {"pace_tm": 3, "pace_tm_se": 3, "quali_tm": 3, "quali_tm_se": 3, "pace_field": 3, "trend": 3, "points": 1, "exp_points": 1,
          "p_title": 4, "elo_tm": 0, "car": 3, "car_se": 3, "car_mean": 3, "quali_car": 3}
    return {"ok": True, "year": year, "updated_at": _now(), "version": VERSION, "current": current,
            "unit": "% of a lap; positive = faster (0.1% is about 0.09 s on a 90-second lap)",
            "driver_cols": DRIVER_COLS, "drivers": pack(rows, DRIVER_COLS, nd), "team_cols": TEAM_COLS, "teams": pack(teams, TEAM_COLS, nd),
            "best": {"pace_tm": best_tm, "pace_field": best_field}, "min_races": MIN_RACES,
            "params": (effects.get("params") or {}),
            "notes": {"teammate": "Pace above team-mate is the decomposition's driver effect: team-mates share the car, so it is measured only "
                                  "against the team-mate and shrunk toward zero. A driver beside a weak team-mate looks better than they are.",
                      "field": "Pace above the field adds the car's latest race-pace state: the driver and the car together now.",
                      "trend": "Trend: pace above team-mate against last season's (both seasons with at least five races)."}}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------------------------- swaps

def swap_events(events: list, x: str, w: str, drv_eff: dict[str, float]) -> list:
    """The championship's remaining events with drivers x and w in each other's seats (see the module docstring)."""
    out = []
    for rnd, kind, inp in events:
        if x not in inp.drivers or w not in inp.drivers or inp.team.get(x) == inp.team.get(w):
            out.append((rnd, kind, inp))
            continue
        k = float(inp.ref_lap_s or (inp.meta or {}).get("ref_lap_s") or 90.0) / 100.0
        dx, dw = float(drv_eff.get(x, 0.0)), float(drv_eff.get(w, 0.0))
        mu = dict(inp.pace_mu)
        mu[x] = float(inp.pace_mu[w]) + (dx - dw) * k
        mu[w] = float(inp.pace_mu[x]) + (dw - dx) * k
        team = dict(inp.team)
        team[x], team[w] = inp.team[w], inp.team[x]

        def sw(dd):
            if not dd:
                return dd
            o = dict(dd)
            o[x], o[w] = dd.get(w), dd.get(x)
            return o
        haz = dict(inp.dnf_hazard)
        split = (inp.meta or {}).get("dnf_split") or {}
        if split.get(x) and split.get(w):
            c = inp.circuit or {}
            laps = int(c.get("sprint_laps") if kind == "sprint" else c.get("laps") or 57) or 57
            for d, seat in ((x, w), (w, x)):
                p = min(0.6, float(split[seat]["mech"]) + float(split[d]["incident"]))
                haz[d] = -math.log(1 - p) / max(laps, 1)
        out.append((rnd, kind, dataclasses.replace(inp, pace_mu=mu, team=team, grid=sw(inp.grid), grid_dist=sw(inp.grid_dist),
                                                   grid_strength=sw(inp.grid_strength), dnf_hazard=haz, stops=sw(inp.stops), deg=sw(inp.deg))))
    return out


def _events_key(year: int, state: dict, events: list, drv_eff: dict, n: int, seed: int) -> str:
    h = hashlib.sha1()
    h.update(json.dumps([VERSION, year, n, seed, sorted(state.get("driver_points", {}).items()), sorted(state.get("team_points", {}).items()),
                         state.get("remaining")], default=str).encode())
    for rnd, kind, inp in events:
        h.update(json.dumps([rnd, kind, inp.drivers, sorted(inp.team.items()), sorted((d, round(v, 4)) for d, v in inp.pace_mu.items()),
                             sorted((d, round(v, 4)) for d, v in inp.pace_sd.items()), sorted((inp.grid or {}).items()),
                             sorted((d, [round(p, 4) for p in (v or [])]) for d, v in (inp.grid_dist or {}).items()),
                             sorted((d, round(v, 6)) for d, v in inp.dnf_hazard.items())], default=str).encode())
    h.update(json.dumps(sorted((d, round(v, 4)) for d, v in drv_eff.items())).encode())
    return h.hexdigest()[:16]


def swap_table(year: int, effects: dict, n: int = SWAP_N, seed: int | None = None, cache_dir: Path | None = None,
               max_pairs: int | None = None) -> dict:
    """Every swap of two current drivers on different teams, simulated with common random numbers against a baseline:
    {"ok", "n", "lineup" {driver: team}, "cols", "pairs" {"a|b": [changes]}, "base" {...}, "runtime_s"}. Never raises."""
    from oddsmarkets.f1.models import championship as CH
    t0 = time.perf_counter()
    try:
        seed = int(year if seed is None else seed)
        st = CH.season_state(year)
        events = CH._events(year, st["remaining"])
        if not events:
            return {"ok": False, "reason": "no rounds left to simulate"}
        drv_eff = {d: float(v["effect"]) for d, v in (effects.get("driver") or {}).items() if _num(v.get("effect")) is not None}
        lineup = dict(events[0][2].team)
        key = _events_key(year, st, events, drv_eff, n, seed)
        cp = (cache_dir / f"swaps_{year}_{key}.json") if cache_dir else None
        if cp is not None and cp.exists():
            got = json.loads(cp.read_text(encoding="utf-8"))
            if got.get("ok"):
                got["cached"] = True
                return got
        base = CH.simulate_championship(year, n=n, seed=seed, state=st, events=events)
        drivers = sorted(lineup)
        pairs = [(a, b) for i, a in enumerate(drivers) for b in drivers[i + 1:] if lineup[a] != lineup[b]]
        if max_pairs is not None:
            pairs = pairs[:max_pairs]
        bd, bt = base["drivers"], base["constructors"]
        out: dict[str, list] = {}
        for a, b in pairs:
            r = CH.simulate_championship(year, n=n, seed=seed, state=st, events=swap_events(events, a, b, drv_eff))
            rd, rt = r["drivers"], r["constructors"]
            ta, tb = lineup[a], lineup[b]
            out[f"{a}|{b}"] = [
                round(rd[a]["exp_points"] - bd[a]["exp_points"], 2), round(rd[a]["p_title"] - bd[a]["p_title"], 4),
                round(rd[a]["exp_pos"] - bd[a]["exp_pos"], 2),
                round(rd[b]["exp_points"] - bd[b]["exp_points"], 2), round(rd[b]["p_title"] - bd[b]["p_title"], 4),
                round(rd[b]["exp_pos"] - bd[b]["exp_pos"], 2),
                round(rt[ta]["exp_points"] - bt[ta]["exp_points"], 2), round(rt[ta]["p_title"] - bt[ta]["p_title"], 4),
                round(rt[tb]["exp_points"] - bt[tb]["exp_points"], 2), round(rt[tb]["p_title"] - bt[tb]["p_title"], 4)]
        res = {"ok": True, "year": int(year), "n": int(n), "seed": seed, "lineup": lineup, "cols": SWAP_COLS, "pairs": out,
               "drv_effect": {d: round(v, 4) for d, v in drv_eff.items() if d in lineup},
               "remaining": [list(x) for x in st["remaining"]], "runtime_s": round(time.perf_counter() - t0, 1),
               "base_crn": {"drivers": {d: [round(v["exp_points"], 2), round(v["p_title"], 4), round(v["exp_pos"], 2)] for d, v in bd.items()},
                            "constructors": {t: [round(v["exp_points"], 2), round(v["p_title"], 4)] for t, v in bt.items()}}}
        if cp is not None:
            try:
                cp.parent.mkdir(parents=True, exist_ok=True)
                for old in cp.parent.glob(f"swaps_{year}_*.json"):
                    old.unlink(missing_ok=True)
                cp.write_text(json.dumps(res), encoding="utf-8")
            except OSError:
                pass
        return res
    except Exception as exc:                                     # noqa: BLE001
        logger.exception("swap table failed")
        return {"ok": False, "reason": f"error: {exc}"}


def swap_payload(year: int, table: dict, champ: dict | None, names: dict[str, str]) -> dict:
    """swap.json: the published championship (the baseline the page adds each swap's change to), the lineup and every
    pair's changes."""
    if not table.get("ok"):
        return {"ok": False, "reason": table.get("reason") or "no swap table", "year": year}
    chd, cht = (champ or {}).get("drivers") or {}, (champ or {}).get("constructors") or {}
    return {"ok": True, "year": year, "updated_at": _now(), "version": VERSION, "n": table["n"], "remaining": table.get("remaining"),
            "lineup": table["lineup"], "names": {d: names.get(d) or d for d in table["lineup"]}, "drv_effect": table.get("drv_effect"),
            "cols": table["cols"], "pairs": table["pairs"],
            "published": {"n": (champ or {}).get("n"),
                          "drivers": {d: [_rnd(v.get("exp_points"), 2), _rnd(v.get("p_title"), 4), _rnd(v.get("exp_pos"), 2),
                                          _rnd(v.get("current_points"), 1)] for d, v in chd.items()},
                          "constructors": {t: [_rnd(v.get("exp_points"), 2), _rnd(v.get("p_title"), 4), _rnd(v.get("current_points"), 1)]
                                           for t, v in cht.items()}},
            "label": LABEL}


# ---------------------------------------------------------------------------------------------- strengths and needs

def team_swaps(team: str, table: dict, names: dict[str, str], top: int = 5) -> list[dict]:
    """The swaps that add the most expected constructors' points to `team` (its driver out, another team's in)."""
    if not table.get("ok"):
        return []
    lineup, out = table["lineup"], []
    for key, v in table["pairs"].items():
        a, b = key.split("|")
        if lineup.get(a) == team:            # a leaves team; b arrives; team = ta
            inn, out_d, gain, gain_t, other, other_gain = b, a, v[6], v[7], lineup.get(b), v[8]
        elif lineup.get(b) == team:
            inn, out_d, gain, gain_t, other, other_gain = a, b, v[8], v[9], lineup.get(a), v[6]
        else:
            continue
        out.append({"in": inn, "in_name": names.get(inn) or inn, "out": out_d, "out_name": names.get(out_d) or out_d, "from": other,
                    "gain_pts": gain, "gain_title": gain_t, "other_change": other_gain})
    out.sort(key=lambda r: -r["gain_pts"])
    return out[:top]


def needs_payload(year: int, tcat: dict | None, dcat: dict | None, table: dict, names: dict[str, str]) -> dict:
    T = (tcat or {}).get("teams") or {}
    D = (dcat or {}).get("drivers") or {}
    # drivers: the mean team-mate Elo of the team's drivers this season (chained across career team-mates), ranked
    elo = {}
    for t in T:
        xs = [_num((v.get("values") or {}).get("elo_teammate")) for v in D.values() if v.get("team") == t]
        xs = [x for x in xs if x is not None]
        elo[t] = float(np.mean(xs)) if xs else None
    elo_pct = percentiles(elo)
    out = {}
    for t, x in T.items():
        pc, vals = x.get("pct") or {}, x.get("values") or {}
        areas = []
        for key, label, mk, stat in AREAS:
            p = pc.get(mk)
            if p is None or vals.get(mk) is None:
                continue
            areas.append({"key": key, "label": label, "metric": mk, "value": vals.get(mk), "pct": p, "grade": grade(p), "stat": stat})
        if elo.get(t) is not None:
            areas.append({"key": "drivers", "label": "Drivers", "metric": "elo_teammate", "value": round(elo[t], 0), "pct": elo_pct.get(t),
                          "grade": grade(elo_pct.get(t)), "stat": "mean team-mate Elo of its drivers (head-to-heads chained across career team-mates)"})
        rq = {a["key"]: a["pct"] for a in areas}
        balance = None
        if rq.get("race_pace") is not None and rq.get("quali_pace") is not None:
            gap = rq["quali_pace"] - rq["race_pace"]
            balance = ("qualifies better than it races" if gap >= 25 else "races better than it qualifies" if gap <= -25 else "qualifies and races alike")
        srt = sorted(areas, key=lambda a: -a["pct"])
        strengths = [a for a in srt if a["pct"] >= 60][:3]
        weak = [a for a in sorted(areas, key=lambda a: a["pct"]) if a["pct"] <= 40][:3]
        swaps = team_swaps(t, table, names)
        improve = []
        for w in weak:
            if w["key"] == "drivers":
                improve.append({"key": w["key"], "label": w["label"], "swaps": swaps,
                                "note": "Swaps through the championship simulation: the expected constructors' points over the remaining rounds."})
            else:
                improve.append({"key": w["key"], "label": w["label"], "swaps": [],
                                "note": "A car or operations area: there is no market for it, only development. Our models measure it but "
                                        "cannot put a number on an upgrade."})
        out[t] = {"name": x.get("name") or t, "areas": areas, "balance": balance, "strengths": strengths, "weaknesses": weak,
                  "improve": improve, "best_swaps": swaps}
    return {"ok": True, "year": year, "updated_at": _now(), "version": VERSION, "label": LABEL, "grades": [list(g) for g in GRADE_CUTS],
            "swaps_n": table.get("n") if table.get("ok") else None, "teams": out}
