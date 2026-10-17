"""The October 2026 edge research (docs/research/f1_edge.md): practice pace from session records, the practice
shift in the qualifying model, and this round's qualifying pace in the race simulator after qualifying.
Offline, planted inputs."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.f1.models import practice as pr
from oddsmarkets.f1.models import qualifying as q
from oddsmarkets.f1.models import race_sim as rs

YEAR = 2030


@pytest.fixture(autouse=True)
def _no_data_checks(monkeypatch):
    monkeypatch.setattr(rs, "fastest_lap_point_in_data", lambda year: None)


# ---------------------------------------------------------------- practice pace

def _session(offsets_ms: dict[str, float], long_run: bool = True, seed: int = 0) -> tuple[dict, dict]:
    """A practice session record: each car does a 3-lap push run (stint 1) and, if long_run, a 12-lap run on
    another compound (stint 2) with 0.05 s/lap of degradation. Car i is offsets_ms[driver] slower per lap."""
    rng = np.random.default_rng(seed)
    laps, stints, ids = {}, [], {}
    for k, (d, off) in enumerate(offsets_ms.items()):
        num = str(10 + k)
        ids[num] = d
        rows, lap = [], 1
        # stint 1: out-lap, two push laps, in-lap
        for j, ms in enumerate([120000, 80000 + off, 80050 + off, 110000]):
            rows.append([lap, 0, ms, None, None, None, None, None, None, 1 if j == 0 else 0])
            lap += 1
        stints.append([int(num), 1, 1, 4, "SOFT", 0])
        if long_run:
            start = lap
            for j in range(14):
                ms = 84000 + off + 50 * j + rng.normal(0, 40)
                if j == 0:
                    ms = 125000                                   # out-lap
                rows.append([lap, 0, ms, None, None, None, None, None, None, 1 if j == 0 else 0])
                lap += 1
            stints.append([int(num), 2, start, lap - 1, "MEDIUM", 0])
        laps[num] = rows
    return {"laps": laps, "stints": stints, "session": {"session_key": 1}}, ids


def test_short_runs_are_best_lap_gaps_centred_on_the_field():
    offs = {f"d{i}": 100.0 * i for i in range(6)}
    rec, ids = _session(offs, long_run=False)
    sr = pr.short_runs(rec, ids)
    assert set(sr) == set(offs)
    assert sum(sr.values()) == pytest.approx(0.0, abs=1e-9)
    # 100 ms on an 80 s lap is 0.125% per step
    assert sr["d5"] - sr["d0"] == pytest.approx(5 * 0.125, abs=1e-6)


def test_short_runs_drop_cars_outside_107_percent():
    offs = {f"d{i}": 0.0 for i in range(5)} | {"slow": 7000.0}
    rec, ids = _session(offs, long_run=False)
    assert "slow" not in pr.short_runs(rec, ids)


def test_long_runs_recover_the_planted_pace_order():
    offs = {f"d{i}": 150.0 * i for i in range(6)}
    rec, ids = _session(offs)
    lr, meta = pr.long_runs(rec, ids)
    assert set(lr) == set(offs)
    vals = [lr[f"d{i}"][0] for i in range(6)]
    assert vals == sorted(vals)
    assert vals[5] - vals[0] == pytest.approx(5 * 150 / 84000 * 100, rel=0.15)
    assert meta["deg_pct_per_lap"] == pytest.approx(50 / 84000 * 100, rel=0.3)


def test_blend_pct_moves_toward_the_measurement_and_keeps_the_level():
    mu = {"a": -0.5, "b": 0.0, "c": 0.5, "z": 1.0}
    x = {"a": 0.5, "b": 0.0, "c": -0.5}                          # reversed order, same level
    out = pr.blend_pct(mu, x, 0.5)
    assert out["a"] == pytest.approx(0.0) and out["c"] == pytest.approx(0.0)
    assert out["z"] == 1.0                                       # no measurement: unchanged
    assert pr.blend_pct(mu, x, 0.0) == mu


def test_practice_shift_moves_pole_odds_toward_practice(monkeypatch):
    field = {f"d{i}": f"t{i // 2}" for i in range(6)}
    cars = {f"t{j}": (0.0, 0.01) for j in range(3)}
    drivers = {d: (0.0, 0.01) for d in field}
    feats = {"drivers": {d: {"short_pct": (-1.0 if d == "d5" else 0.2)} for d in field}, "sessions": [{"name": "Practice 3"}]}
    monkeypatch.setattr(pr, "practice_features", lambda year, rnd: feats)
    shifted, info = q.practice_shift(YEAR, 3, field, cars, drivers, 0.15, w=0.5)
    assert info["w"] == 0.5 and info["drivers"] == 6
    base = q.simulate_quali(field, cars, drivers, 0.1, n_sims=4000, seed=1)["drivers"]
    new = q.simulate_quali(field, cars, shifted, 0.1, n_sims=4000, seed=1)["drivers"]
    assert new["d5"]["p_pole"] > 0.8 > base["d5"]["p_pole"]
    same, info0 = q.practice_shift(YEAR, 3, field, cars, drivers, 0.15, w=0.0)
    assert same is drivers and info0 is None


def test_practice_shift_needs_half_the_field(monkeypatch):
    field = {f"d{i}": "t0" for i in range(10)}
    monkeypatch.setattr(pr, "practice_features", lambda year, rnd: {"drivers": {"d0": {"short_pct": -1.0}}})
    drivers = {d: (0.0, 0.01) for d in field}
    assert q.practice_shift(YEAR, 3, field, {}, drivers, 0.15, w=0.5) == (drivers, None)


# ---------------------------------------------------------------- qualifying pace after qualifying

def _components(grid=None, quali_pace=None):
    drivers = [f"d{i}" for i in range(6)]
    team = {d: f"t{i // 2}" for i, d in enumerate(drivers)}
    obs = [(d, team[d], "race", -1.0 + 0.4 * i, 1.0, 0, 0) for i, d in enumerate(drivers)]
    rsd = {"obs": obs, "starts": {}, "n_races": 1, "reset": False}
    circuit = {"laps": 30, "sprint_laps": 10, "ref_lap_s": 90.0, "sc_rate_per_lap": 0.0, "vsc_rate_per_lap": 0.0,
               "p_wet": 0.0, "lap1_incident_by_grid": [0.0] * 26}
    return {"year": YEAR, "round": 3, "session": "race", "before_quali": grid is None, "drivers": drivers, "team": team,
            "circuit": circuit, "ref_lap_s": 90.0, "rs": rsd, "a": None, "a_carry": None, "grid": grid, "grid_dist": None,
            "quali_pace": quali_pace, "meta": {}}


def test_quali_pace_blend_after_qualifying_only(monkeypatch):
    monkeypatch.setattr(rs, "QUALI_PACE_W", 0.4)
    monkeypatch.setattr(rs, "QUALI_PACE_SD_MULT", 0.5)
    grid = {f"d{i}": i + 1 for i in range(6)}
    qp = {f"d{i}": (-1.5 if i == 5 else 0.3) for i in range(6)}   # the slowest by results tops qualifying
    plain = rs.inputs_from_components(_components(grid=grid))
    got = rs.inputs_from_components(_components(grid=grid, quali_pace=qp))
    off = np.mean([plain.meta["pace_pct"][d] for d in qp]) - np.mean(list(qp.values()))
    for d in qp:
        want = 0.6 * plain.meta["pace_pct"][d] + 0.4 * (qp[d] + off)
        assert got.meta["pace_pct"][d] == pytest.approx(want)
        assert got.pace_sd[d] == pytest.approx(0.5 * plain.pace_sd[d])
    assert "quali_pace" in got.source
    # without a grid (before qualifying) the qualifying pace is ignored
    pre = rs.inputs_from_components(_components(quali_pace=qp))
    assert pre.meta["pace_pct"] == rs.inputs_from_components(_components()).meta["pace_pct"]
    monkeypatch.setattr(rs, "QUALI_PACE_W", 0.0)
    assert rs.inputs_from_components(_components(grid=grid, quali_pace=qp)).meta["pace_pct"] == plain.meta["pace_pct"]


def test_round_quali_pace_reads_the_rounds_qualifying(monkeypatch):
    store = {"races": {"3": {"qualifying": [
        {"driver": f"d{i}", "position": i + 1, "q1": 80000 + 100 * i, "q2": None, "q3": None} for i in range(6)]}}}
    monkeypatch.setattr(rs._circ, "load_store", lambda year: store)
    qp = rs.round_quali_pace(YEAR, 3, [f"d{i}" for i in range(6)])
    assert qp is not None and set(qp) == {f"d{i}" for i in range(6)}
    assert qp["d0"] < qp["d5"]
    monkeypatch.setattr(rs._circ, "load_store", lambda year: {"races": {}})
    assert rs.round_quali_pace(YEAR, 3, ["d0"]) is None


def test_practice_features_skip_sessions_after_qualifying(monkeypatch):
    """2023 sprint weekends: Grand Prix qualifying on Friday, sprint qualifying and the sprint after it."""
    offs = {f"d{i}": 100.0 * i for i in range(6)}
    rec, ids = _session(offs, long_run=False)
    starts = {"Practice 1": "2023-04-28T09:30:00+00:00", "Qualifying": "2023-04-28T13:00:00+00:00",
              "Sprint Qualifying": "2023-04-29T08:30:00+00:00", "Sprint": "2023-04-29T13:30:00+00:00"}

    def find(year, rnd, name):
        if name not in starts:
            return None
        return {**rec, "session": {"session_key": 1, "session_name": name, "date_start": starts[name]}}
    monkeypatch.setattr(pr.canon, "find_session", find)
    monkeypatch.setattr(pr.canon, "session_driver_ids", lambda year, r, rnd=None: ids)
    monkeypatch.setattr(pr.canon, "lineup", lambda year, rnd: {d: "t" for d in offs})
    got = pr.practice_features(2023, 4)
    assert [s["name"] for s in got["sessions"]] == ["Practice 1"]
