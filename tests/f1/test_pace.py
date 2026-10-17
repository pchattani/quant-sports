"""Builder A: lap-time model, decomposition, qualifying model and identity, on synthetic
races where the truth is planted. Offline; no store or session files are read."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.f1 import canon
from oddsmarkets.f1.models import decomposition as dec
from oddsmarkets.f1.models import laptime as lt
from oddsmarkets.f1.models import qualifying as qm

N_LAPS = 50
BASE = 90.0
FUEL = 0.07
COMP = {"SOFT": (-0.6, 0.08), "MEDIUM": (0.0, 0.05), "HARD": (0.4, 0.03)}
TEAM = {"t1": -0.8, "t2": -0.4, "t3": 0.0, "t4": 0.4, "t5": 0.8}
DRIVER = {"a1": -0.15, "a2": 0.15, "b1": 0.1, "b2": -0.1, "c1": 0.0, "c2": 0.0, "d1": -0.2, "d2": 0.2, "e1": 0.05, "e2": -0.05}
TEAM_OF = {d: "t" + str("abcde".index(d[0]) + 1) for d in DRIVER}
NUM = {d: str(10 + k) for k, d in enumerate(sorted(DRIVER))}
TRAFFIC = 0.5


def _strategy(k: int) -> list[tuple[int, int, str]]:
    """Stints (start, end, compound): one- and two-stop strategies at varied laps."""
    s1 = 14 + 2 * (k % 6)
    if k % 3 == 0:
        s2 = s1 + 14 + (k % 4)
        return [(1, s1, "SOFT"), (s1 + 1, s2, "MEDIUM"), (s2 + 1, N_LAPS, "HARD")]
    first = ("MEDIUM", "HARD") if k % 2 else ("SOFT", "HARD")
    return [(1, s1 + 6, first[0]), (s1 + 7, N_LAPS, first[1])]


def synthetic_race(seed: int = 1, sc_laps=(30, 31, 32), vsc_lap: int | None = None, traffic: bool = True, noise: float = 0.15,
                   compounds: bool = True):
    """A planted race as an OpenF1-like session record plus a store race entry."""
    rng = np.random.default_rng(seed)
    sess = {"session": {"session_name": "Race", "date_start": "2026-01-01T12:00:00+00:00"}, "drivers": {}, "laps": {}, "lap_end": {},
            "stints": [], "pit": [], "race_control": []}
    race = {"results": [], "laps": {}, "pitstops": []}
    leader_t: dict[int, int] = {}
    for k, d in enumerate(sorted(DRIVER)):
        num = NUM[d]
        sess["drivers"][num] = {"name_acronym": d.upper()}
        stints = _strategy(k)
        t, rows, ends = 0, [], []
        for si, (a, b, c) in enumerate(stints):
            sess["stints"].append([int(num), si + 1, a, b, c, 0])
            if si > 0:
                sess["pit"].append([int(num), a - 1, None, 22000, 2500])
        for lap in range(1, N_LAPS + 1):
            st = next(s for s in stints if s[0] <= lap <= s[1])
            age = lap - st[0]
            off, deg = COMP[st[2]] if compounds else (0.0, 0.05)
            u = 2 * (lap - 1) / (N_LAPS - 1) - 1
            iv = float(rng.uniform(0.2, 4.0))
            tr = max(0.0, 1 - iv / 1.5) if traffic else 0.0
            x = (BASE + TEAM[TEAM_OF[d]] + DRIVER[d] + FUEL * (N_LAPS - lap) + off + deg * age + 0.2 * 0.5 * (3 * u * u - 1)
                 + TRAFFIC * tr + rng.normal(0, noise))
            if lap == 1:
                x += 6.0
            if any(s[0] - 1 == lap for s in stints[1:]):
                x += 20.0                                   # in-lap
            if any(s[0] == lap for s in stints[1:]):
                x += 18.0                                   # out-lap
            if lap in sc_laps:
                x += 25.0                                   # safety car: everyone slow
            if vsc_lap is not None and lap in (vsc_lap, vsc_lap + 1):
                x *= 1.03                                   # a VSC slow enough to hurt, not enough for the 107% rule
            ms = int(round(x * 1000))
            pit_out = 1 if any(s[0] == lap for s in stints[1:]) else 0
            rows.append([lap, t, ms, None, None, None, None, None, None, pit_out])
            ends.append([lap - 1, 1.0, iv])                 # interval at the end of the previous lap
            if d == sorted(DRIVER)[0]:
                leader_t[lap] = t
            t += ms
        sess["laps"][num] = rows
        sess["lap_end"][num] = ends
        race["laps"][d] = [r[2] for r in rows]
        for s in stints[1:]:
            race["pitstops"].append({"driver": d, "stop": 1, "lap": s[0] - 1, "duration_ms": 22000})
        race["results"].append({"driver": d, "constructor": TEAM_OF[d], "number": int(num), "laps": N_LAPS, "position": k + 1})
    if vsc_lap is not None:
        sess["race_control"] = [[leader_t[vsc_lap] + 1000, vsc_lap, "SafetyCar", None, None, None, None, "VSC DEPLOYED"],
                                [leader_t[vsc_lap + 1] + 60000, vsc_lap + 1, "SafetyCar", None, None, None, None, "VSC ENDING"]]
    ids = {NUM[d]: d for d in DRIVER}
    return race, sess, ids


def _planted_pace() -> dict[str, float]:
    raw = {d: TEAM[TEAM_OF[d]] + DRIVER[d] for d in DRIVER}
    m = np.mean(list(raw.values()))
    return {d: v - m for d, v in raw.items()}


# ---------------------------------------------------------------- lap-time model

def test_laptime_recovers_planted_effects():
    race, sess, ids = synthetic_race(seed=3)
    rows, info = lt.assemble(race, sess, ids, TEAM_OF, 2026)
    assert info["source"] == "openf1" and info["traffic"]
    out = lt.fit_race(rows, info["n_laps"], traffic=True)
    truth = _planted_pace()
    for d, v in out["drivers"].items():
        assert abs(v["pace"] - truth[d]) < 0.12, (d, v["pace"], truth[d])
        assert 0 < v["se"] < 0.2
    assert abs(out["fuel_coef"] - FUEL) < 0.015
    assert abs(out["traffic_coef"] - TRAFFIC) < 0.12
    for c, (off, deg) in COMP.items():
        assert abs(out["compound_deg"][c] - deg) < 0.015, (c, out["compound_deg"][c])
        rel = out["compound_offset"][c] - out["compound_offset"]["MEDIUM"]
        assert abs(rel - (off - COMP["MEDIUM"][0])) < 0.2, (c, rel)
    # per-driver degradation shrunk towards the compound mean
    for v in out["drivers"].values():
        for c, g in v["deg"].items():
            assert abs(g - COMP[c][1]) < 0.03


def test_pit_and_neutralised_laps_excluded():
    race, sess, ids = synthetic_race(seed=4, sc_laps=(30, 31, 32))
    rows, _ = lt.assemble(race, sess, ids, TEAM_OF, 2026)
    clean = [r for r in rows if r["excl"] is None]
    assert not any(r["lap"] == 1 for r in clean)
    assert not any(r["lap"] in (30, 31, 32, 33) for r in clean)          # SC laps and the restart lap
    for r in clean:
        assert r["lap_s"] < BASE + 15                                     # no pit or SC lap survives
    pit = {(r["driver"], r["lap"]) for r in rows if r["excl"] == "pit"}
    for p in sess["pit"]:
        d = ids[str(p[0])]
        assert (d, p[1]) in pit and (d, p[1] + 1) in pit


def test_race_control_vsc_window_excludes_laps():
    race, sess, ids = synthetic_race(seed=5, sc_laps=(), vsc_lap=20)
    rows, info = lt.assemble(race, sess, ids, TEAM_OF, 2026)
    assert 20 not in info["neutral_laps"]                                  # too mild for the 107% rule ...
    neut = {r["lap"] for r in rows if r["excl"] == "neutralised"}
    assert 20 in neut                                                      # ... but race control catches it


def test_red_flag_and_unclosed_safety_car_windows():
    """Monza 2026 style: SC deployed, red flag via an 'Other' message, restart by SessionStatus,
    and the SC is never declared 'in this lap'."""
    rc = [[400_000, 3, "SafetyCar", None, None, None, None, "SAFETY CAR DEPLOYED"],
          [460_000, 3, "SessionStatus", None, None, None, None, "SESSION ABORTED"],
          [463_000, 3, "Other", None, None, None, None, "RED FLAG - RACE SUSPENDED"],
          [1_670_000, 4, "Other", None, None, None, None, "RACE WILL RESUME AT 15:39"],
          [2_040_000, 4, "Other", None, None, None, None, "SAFETY CAR LIGHTS ON"],
          [2_340_000, 4, "SessionStatus", None, None, None, None, "SESSION STARTED"]]
    wins, _ = lt._neutral_windows(rc, 90_000)
    red = [w for w in wins if w[0] == 460_000.0]
    assert red and red[0][1] == 2_340_000 + 90_000                         # "WILL RESUME" does not end it
    assert any(w[0] == 400_000.0 and w[1] == float("inf") for w in wins)   # resolved later from lap times


def test_pre2023_store_only_path():
    race, _sess, _ids = synthetic_race(seed=6, traffic=False, compounds=False)   # compounds are unknown before 2023
    rows, info = lt.assemble(race, None, {}, TEAM_OF, 2015)
    assert info["source"] == "jolpica" and not info["traffic"]
    assert {r["compound"] for r in rows} == {lt.UNKNOWN}
    out = lt.fit_race(rows, info["n_laps"], traffic=False)
    truth = _planted_pace()
    for d, v in out["drivers"].items():
        assert abs(v["pace"] - truth[d]) < 0.2, (d, v["pace"], truth[d])
    assert out["excluded"]["neutralised"] >= 3 * len(DRIVER)


def test_refuelling_era_infers_pits_without_pit_table():
    race, _s, _i = synthetic_race(seed=7, traffic=False)
    race["pitstops"] = []
    rows, info = lt.assemble(race, None, {}, TEAM_OF, 2005)
    assert info.get("pits_inferred") and info["refuel"]
    assert all(r["lap_s"] < BASE + 15 for r in rows if r["excl"] is None)


def test_fit_with_too_few_laps_returns_reason():
    out = lt.fit_race([{"driver": "x", "team": "t", "lap": 2, "lap_s": 90.0, "compound": "UNKNOWN", "age": 1, "fuel": 1, "excl": None}])
    assert out["drivers"] == {} and out["reason"]


def test_race_pace_missing_round(monkeypatch):
    monkeypatch.setattr(canon, "race", lambda y, r: {})
    monkeypatch.setattr(canon, "find_session", lambda y, r, name="Race": None)
    out = lt.race_pace(2026, 99, use_cache=False)
    assert out["drivers"] == {} and "reason" in out


# ---------------------------------------------------------------- decomposition

def _planted_season(seed: int = 2, rounds: int = 14):
    rng = np.random.default_rng(seed)
    teams = ["A", "B", "C", "D", "E", "F"]
    car = {t: np.cumsum(np.r_[rng.normal(0, 0.6), rng.normal(0, 0.15, rounds - 1)]) for t in teams}
    drivers = {f"{t}{i}": (0.25 if i == 1 else -0.25) * (1 if k % 2 else -1) * (0.5 + 0.2 * k) for k, t in enumerate(teams) for i in (1, 2)}
    drivers["swap"] = 0.3
    obs = []
    for r in range(1, rounds + 1):
        lineup = {d: d[0] for d in drivers if d != "swap"}
        if r > rounds // 2:                                   # "swap" replaces F2 at team F, after A2 ... mid-season move
            lineup.pop("F2")
            lineup["swap"] = "F"
        else:
            lineup.pop("A2")
            lineup["swap"] = "A"
        for d, t in lineup.items():
            se = 0.05
            obs.append((r, d, t, car[t][r - 1] + drivers[d] + rng.normal(0, np.hypot(se, 0.08)), se))
    return obs, car, drivers


def test_decomposition_recovers_car_walk_and_drivers():
    obs, car, drivers = _planted_season()
    fit = dec.fit_effects(obs, "race")
    errs = []
    for t, path in fit["car"].items():
        for s in path:
            errs.append(s["effect"] - car[t][s["round"] - 1])
    assert np.sqrt(np.mean(np.square(errs))) < 0.12
    for d, v in fit["driver"].items():
        assert abs(v["effect"] - drivers[d]) < 0.15, (d, v, drivers[d])
        assert v["se"] > 0
    est = np.array([fit["driver"][d]["effect"] for d in drivers])
    assert np.corrcoef(est, np.array(list(drivers.values())))[0, 1] > 0.95
    assert fit["driver"]["swap"]["races"] == 14
    assert 0.05 < fit["params"]["q"] < 0.4


def test_quali_pace_handles_segment_evolution():
    truth = {f"d{k}": 0.1 * k for k in range(20)}
    base = 80000.0
    rows = []
    for k, (d, g) in enumerate(truth.items()):
        q1 = base * (1 + g / 100)
        q2 = base * 0.994 * (1 + g / 100) if k < 15 else None         # track 0.6% faster in Q2
        q3 = base * 0.99 * (1 + g / 100) if k < 10 else None
        rows.append({"driver": d, "q1": q1, "q2": q2, "q3": q3})
    qp = dec.quali_pace(rows)
    m = np.mean(list(truth.values()))
    for d, g in truth.items():
        assert abs(qp[d]["pace"] - (g - m)) < 1e-6


# ---------------------------------------------------------------- qualifying model

def test_quali_model_probabilities():
    field = {"fast": "T1", "fast2": "T1", "mid": "T2", "mid2": "T2", "slow": "T3", "slow2": "T3"}
    cars = {"T1": (-0.6, 0.01), "T2": (0.0, 0.01), "T3": (0.6, 0.01)}
    drivers = {"fast": (-0.1, 0.002), "fast2": (0.1, 0.002)}
    out = qm.simulate_quali(field, cars, drivers, tau=0.15, n_sims=20000)["drivers"]
    assert abs(sum(v["p_pole"] for v in out.values()) - 1) < 1e-6
    for v in out.values():
        assert abs(sum(v["grid_dist"]) - 1) < 1e-6 and len(v["grid_dist"]) == len(field)
    for k in range(len(field)):
        assert abs(sum(v["grid_dist"][k] for v in out.values()) - 1) < 1e-6
    assert max(out, key=lambda d: out[d]["p_pole"]) == "fast"
    assert out["fast"]["exp_grid"] < out["mid"]["exp_grid"] < out["slow"]["exp_grid"]
    assert out["slow2"]["mu_gap_pct"] > out["fast"]["mu_gap_pct"]


def test_quali_model_flat_prior_without_effects(monkeypatch):
    monkeypatch.setattr(qm.canon, "lineup", lambda y, r: {"x": "A", "y": "B"})
    monkeypatch.setattr(qm, "season_effects", lambda y, upto_round=None: {"quali_car": {}, "quali_driver": {}, "params": {}})
    out = qm.quali_model(2026, 3, n_sims=2000)
    assert set(out["drivers"]) == {"x", "y"}
    assert abs(sum(v["p_pole"] for v in out["drivers"].values()) - 1) < 1e-6


# ---------------------------------------------------------------- identity

def _store(rows_by_round: dict[int, list[tuple[str, str, int]]]) -> dict:
    return {"races": {str(r): {"date": f"2020-03-{10 + r:02d}", "results": [{"driver": d, "constructor": c, "number": n} for d, c, n in rows]}
                      for r, rows in rows_by_round.items()}, "drivers": {}}


@pytest.fixture
def two_seasons(monkeypatch):
    stores = {
        2019: _store({1: [("old_five", "teamx", 5), ("ham", "merc", 44)], 2: [("old_five", "teamx", 5), ("ham", "merc", 44)]}),
        2020: _store({1: [("new_five", "teamy", 5), ("ham", "merc", 44)],
                      2: [("new_five", "teamy", 5), ("sub", "merc", 89)],          # substitute with his own number
                      3: [("new_five", "teamz", 5), ("ham", "merc", 44)]}),        # mid-season team change
    }
    monkeypatch.setattr(canon, "season", lambda y: stores.get(int(y), {"races": {}, "drivers": {}}))
    return stores


def test_canon_number_reused_across_seasons(two_seasons):
    assert canon.driver_for_number(2019, 5) == "old_five"
    assert canon.driver_for_number(2020, 5) == "new_five"
    assert canon.driver_for_number(2020, 89, rnd=2) == "sub"
    assert canon.driver_for_number(2020, 44, rnd=2) == "ham"               # falls back to the season map
    assert canon.driver_for_number(2020, 77) is None
    assert canon.number_map(2020)[44] == "ham"


def test_canon_team_for_and_session_rekey(two_seasons):
    assert canon.team_for(2020, 1, "new_five") == "teamy"
    assert canon.team_for(2020, 3, "new_five") == "teamz"
    assert canon.team_for(2020, 2, "ham") == "merc"                       # absent in round 2 -> nearest round
    assert canon.team_for(2020, 1, "nobody") is None
    rec = {"session": {"date_start": "2020-03-12T14:00:00+00:00"}, "drivers": {"5": {"name_acronym": "NEW"}, "89": {"name_acronym": "SUB"}},
           "laps": {"5": [[1]], "89": [[1]]}}
    assert canon.session_round(2020, rec) == 2
    assert canon.rekey(2020, rec, rec["laps"]) == {"new_five": [[1]], "sub": [[1]]}
