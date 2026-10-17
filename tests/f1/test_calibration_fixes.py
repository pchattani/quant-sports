"""The October 2026 re-tune: circuit reference laps, the decomposition's team-round term and fixed walk step,
pace conversion by the circuit's lap, the round-1 carry, the pre-qualifying grid mix, fitted constants and
the backtest's temperature and memory bookkeeping. Offline, planted inputs."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from oddsmarkets.f1.models import backtest as bt
from oddsmarkets.f1.models import circuits as circ
from oddsmarkets.f1.models import decomposition as dec
from oddsmarkets.f1.models import race_sim as rs

YEAR = 2030


@pytest.fixture(autouse=True)
def _no_data_checks(monkeypatch):
    monkeypatch.setattr(rs, "fastest_lap_point_in_data", lambda year: None)


# ---------------------------------------------------------------- reference lap

def test_reference_lap_prefers_the_circuits_latest_race():
    mine = [{"year": 2020, "round": 3, "ref_lap_s": 80.0}, {"year": 2024, "round": 5, "ref_lap_s": 78.5}, {"year": 2025, "round": 6}]
    others = [{"year": 2025, "round": r, "ref_lap_s": v} for r, v in ((1, 90.0), (2, 100.0), (3, 95.0))]
    assert circ.reference_lap(mine, mine + others) == (78.5, "circuit")
    assert circ.reference_lap([], others) == (95.0, "season median")
    assert circ.reference_lap([], []) == (circ.REF_LAP_DEFAULT, "default")


def test_race_record_keeps_the_median_green_lap():
    laps = {f"d{i}": [100000 + 500 * i] + [90000 + 100 * i] * 9 for i in range(6)}
    race = {"circuit": {"id": "x"}, "laps": laps,
            "results": [{"driver": f"d{i}", "constructor": "t", "position": i + 1, "position_text": str(i + 1), "grid": i + 1,
                         "laps": 10, "status": "Finished"} for i in range(6)]}
    rec = circ.race_record(2015, "1", race)
    assert rec["ref_lap_s"] == pytest.approx(90.25, abs=0.01)


# ---------------------------------------------------------------- decomposition

def _season_with_track_swings(seed=4, rounds=16):
    """Flat cars; every team gets a large one-round circuit swing shared by both drivers."""
    rng = np.random.default_rng(seed)
    teams = ["A", "B", "C", "D", "E"]
    level = {t: 0.4 * k - 0.8 for k, t in enumerate(teams)}
    obs = []
    for r in range(1, rounds + 1):
        for t in teams:
            u = rng.normal(0, 0.45)
            for i in (1, 2):
                obs.append((r, f"{t}{i}", t, level[t] + u + rng.normal(0, 0.1), 0.05))
    return obs, level


def test_team_round_term_keeps_the_latest_car_state_near_the_level(monkeypatch):
    obs, level = _season_with_track_swings()
    monkeypatch.setitem(dec.Q_FIXED, "race", None)
    err = {}
    for flag in (False, True):
        monkeypatch.setattr(dec, "TEAM_ROUND_NOISE", flag)
        fit = dec.fit_effects(obs, "race")
        err[flag] = math.sqrt(np.mean([(fit["car"][t][-1]["effect"] - level[t]) ** 2 for t in level]))
        if flag:
            assert fit["params"]["kappa"] > 0.2
            assert fit["params"]["q"] < 0.2
        else:
            assert fit["params"]["kappa"] is None
    assert err[True] < 0.7 * err[False]


def test_fixed_walk_step_is_respected(monkeypatch):
    obs, _ = _season_with_track_swings(rounds=6)
    monkeypatch.setitem(dec.Q_FIXED, "race", 0.06)
    assert dec.fit_effects(obs, "race")["params"]["q"] == pytest.approx(0.06, abs=1e-4)


# ---------------------------------------------------------------- race simulator inputs

def _components(ref, a=None, a_carry=None, grid=None, gd=None):
    drivers = [f"d{i}" for i in range(6)]
    team = {d: f"t{i // 2}" for i, d in enumerate(drivers)}
    obs = [(d, team[d], "race", -1.0 + 0.4 * i, 1.0, 0, 0) for i, d in enumerate(drivers)]
    rsd = {"obs": obs, "starts": {}, "n_races": 1, "reset": False}
    circuit = {"laps": 30, "sprint_laps": 10, "ref_lap_s": ref, "sc_rate_per_lap": 0.0, "vsc_rate_per_lap": 0.0, "p_wet": 0.0,
               "lap1_incident_by_grid": [0.0] * 26}
    return {"year": YEAR, "round": 3, "session": "race", "before_quali": grid is None, "drivers": drivers, "team": team,
            "circuit": circuit, "ref_lap_s": ref, "rs": rsd, "a": a, "a_carry": a_carry, "grid": grid, "grid_dist": gd, "meta": {}}


def test_pace_converts_with_the_circuits_reference_lap():
    short = rs.inputs_from_components(_components(70.0))
    long_ = rs.inputs_from_components(_components(105.0))
    for d in short.drivers:
        assert long_.pace_mu[d] == pytest.approx(short.pace_mu[d] * 105.0 / 70.0)
        assert short.meta["pace_pct"][d] == long_.meta["pace_pct"][d]
    assert short.ref_lap_s == 70.0


def test_blend_weight_and_round_one_carry(monkeypatch):
    drivers = [f"d{i}" for i in range(6)]
    a = {"mu_pct": {d: (-2.0 if d == "d5" else 0.0) for d in drivers}, "sd_pct": {d: 0.1 for d in drivers}, "n_rounds": 4.0, "carry": False}
    monkeypatch.setattr(rs, "A_BLEND_K", 4.0)
    inp = rs.inputs_from_components(_components(90.0, a=a))
    fb = rs.inputs_from_components(_components(90.0))
    assert inp.meta["pace_pct"]["d5"] == pytest.approx(0.5 * -2.0 + 0.5 * fb.meta["pace_pct"]["d5"])
    carry = {**a, "n_rounds": 0.0, "carry": True}
    monkeypatch.setattr(rs, "A_CARRY_ROUNDS", 0.0)
    assert rs.inputs_from_components(_components(90.0, a_carry=carry)).source == "results"
    monkeypatch.setattr(rs, "A_CARRY_ROUNDS", 4.0)
    got = rs.inputs_from_components(_components(90.0, a_carry=carry))
    assert "carried" in got.source and got.meta["pace_pct"]["d5"] == pytest.approx(inp.meta["pace_pct"]["d5"])


def test_pre_grid_blend_draws_a_permutation(monkeypatch):
    drivers = [f"d{i}" for i in range(6)]
    gd = {d: [1.0 if k == i else 0.0 for k in range(6)] for i, d in enumerate(drivers)}       # quali model: d0 on pole
    monkeypatch.setattr(rs, "PRE_GRID", "blend")
    monkeypatch.setattr(rs, "PRE_GRID_MIX", 0.5)
    inp = rs.inputs_from_components(_components(90.0, gd=gd))
    res = rs.simulate_race(inp, n=500, seed=3, return_samples=True)
    pos = res["_samples"]["pos"]
    assert (np.sort(pos, axis=1) == np.arange(1, 7)).all()
    monkeypatch.setattr(rs, "PRE_GRID", "results")
    assert rs.inputs_from_components(_components(90.0, gd=gd)).grid_dist is None


def test_sim_noise_scales_with_the_lap():
    """The same pace in % of lap gives the same win probabilities on a short and a long lap."""
    out = {}
    for ref in (70.0, 105.0):
        inp = rs.inputs_from_components(_components(ref, grid={f"d{i}": i + 1 for i in range(6)}))
        out[ref] = rs.simulate_race(inp, n=4000, seed=5)["drivers"]
    for d in out[70.0]:
        assert out[70.0][d]["p_win"] == pytest.approx(out[105.0][d]["p_win"], abs=0.06)


def test_fitted_constants_override_defaults(tmp_path, monkeypatch):
    f = tmp_path / "race_params.json"
    f.write_text(json.dumps({"params": {"A_BLEND_K": 2.5, "LAP_SD": 0.2, "not_a_constant_xyz": 1}}), encoding="utf-8")
    old = {k: getattr(rs, k) for k in ("A_BLEND_K", "LAP_SD")}
    monkeypatch.setattr(rs, "FITTED_PATH", f)
    try:
        rs._load_fitted()
        assert rs.A_BLEND_K == 2.5 and rs.LAP_SD == 0.2 and not hasattr(rs, "not_a_constant_xyz")
        prev = rs.set_params(LAP_SD=0.3)
        assert prev == {"LAP_SD": 0.2} and rs.LAP_SD == 0.3
        with pytest.raises(KeyError):
            rs.set_params(NOT_A_PARAM=1)
    finally:
        rs.set_params(**old)


# ---------------------------------------------------------------- backtest bookkeeping

def test_win_temperature_detects_timid_and_bold_forecasts():
    rng = np.random.default_rng(0)
    timid, bold, fair = [], [], []
    for _ in range(400):
        s = rng.normal(0, 1.2, 10)
        p = np.exp(s) / np.exp(s).sum()
        w = f"d{rng.choice(10, p=p)}"
        names = [f"d{i}" for i in range(10)]
        for out, t in ((fair, 1.0), (timid, 0.5), (bold, 2.0)):
            q = p ** t / np.sum(p ** t)
            out.append((dict(zip(names, q)), w))
    assert 0.8 < bt.win_temperature(fair) < 1.25
    assert bt.win_temperature(timid) > 1.6
    assert bt.win_temperature(bold) < 0.65


def test_rss_is_measurable():
    m = bt._rss_mb()
    assert m is None or m > 1


def test_shared_strategy_and_lap1_tail_firm_up_a_clear_favourite(monkeypatch):
    """Independent stop counts per car and a full-spread Gaussian lap 1 reshuffle the front far more than races do."""
    comp = _components(90.0, grid={f"d{i}": i + 1 for i in range(6)})
    comp["circuit"].update({"typical_stops": 1.6, "lap1_sd_by_grid": [2.2, 3.2, 2.7, 2.3, 3.2, 3.0] + [3.0] * 20,
                            "lap1_mean_by_grid": [0.5] * 26})
    inp = rs.inputs_from_components(comp)
    monkeypatch.setattr(rs, "STOP_DEV_P", None)
    monkeypatch.setattr(rs, "LAP1_SD_MULT", 1.0)
    monkeypatch.setattr(rs, "LAP1_BAD_P", 0.0)
    old = rs.simulate_race(inp, n=4000, seed=9)["drivers"]["d0"]["p_win"]
    monkeypatch.setattr(rs, "STOP_DEV_P", 0.1)
    monkeypatch.setattr(rs, "LAP1_SD_MULT", 0.4)
    monkeypatch.setattr(rs, "LAP1_BAD_P", 0.10)
    new = rs.simulate_race(inp, n=4000, seed=9)["drivers"]["d0"]["p_win"]
    assert new > old + 0.05
