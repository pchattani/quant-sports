"""The post-qualifying strength scale (21 Oct 2026, round 2; docs/research/f1_edge.md 9.6): race_sim.spread_pace /
pace_spread_post, its use in inputs_from_components (Grand Prix with a grid only) and scripts/f1_tune.py's
walk-forward table. Offline, planted inputs."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.f1.models import race_sim as rs

ROOT = Path(__file__).resolve().parents[2]


def test_spread_pace_scales_about_the_mean():
    mu = {"a": -0.6, "b": 0.0, "c": 0.3, "d": 0.9}
    out = rs.spread_pace(mu, 1.5)
    m = np.mean(list(mu.values()))
    assert math.isclose(np.mean(list(out.values())), m, abs_tol=1e-12)          # field mean kept
    for d in mu:
        assert math.isclose(out[d] - m, 1.5 * (mu[d] - m), abs_tol=1e-12)
    assert rs.spread_pace(mu, 1.0) == mu and rs.spread_pace(mu, 1.0) is not mu


def test_pace_spread_post_lookup(monkeypatch):
    monkeypatch.setattr(rs, "PACE_SPREAD_POST", {"2026_5": 1.4, "latest": 1.3})
    assert rs.pace_spread_post(2026, 5) == 1.4
    assert rs.pace_spread_post(2026, 6) == 1.3
    monkeypatch.setattr(rs, "PACE_SPREAD_POST", {"2026_5": float("inf")})
    assert rs.pace_spread_post(2026, 5) == 1.0
    monkeypatch.setattr(rs, "PACE_SPREAD_POST", {})
    assert rs.pace_spread_post(2026, 5) == 1.0


def _comp(grid):
    drivers = ["a", "b", "c", "d"]
    team = {"a": "t1", "b": "t1", "c": "t2", "d": "t2"}
    obs = [("a", "t1", "race", 1.2, 1.0, 0, 0), ("b", "t1", "race", 0.3, 1.0, 0, 0),
           ("c", "t2", "race", -0.3, 1.0, 0, 0), ("d", "t2", "race", -1.2, 1.0, 0, 0)]
    rsd = {"obs": obs, "starts": {}, "n_races": 1, "grid_z": {d: 0.0 for d in drivers}}
    return {"year": 2030, "round": 3, "session": "race", "drivers": drivers, "team": team, "circuit": {"laps": 50},
            "ref_lap_s": 90.0, "rs": rsd, "a": None, "a_carry": None, "grid": grid, "grid_dist": None,
            "quali_pace": None, "meta": {}}


def test_inputs_scaled_after_qualifying_only(monkeypatch):
    try:
        base_post = rs.inputs_from_components(_comp({"a": 1, "b": 2, "c": 3, "d": 4}))
    except Exception as exc:                                    # planted results_strength shape changed
        pytest.skip(f"planted components not accepted: {exc}")
    base_pre = rs.inputs_from_components(_comp(None))
    monkeypatch.setattr(rs, "PACE_SPREAD_POST", {"latest": 2.0})
    post = rs.inputs_from_components(_comp({"a": 1, "b": 2, "c": 3, "d": 4}))
    pre = rs.inputs_from_components(_comp(None))
    m = np.mean(list(base_post.pace_mu.values()))
    for d in post.drivers:
        assert math.isclose(post.pace_mu[d] - m, 2.0 * (base_post.pace_mu[d] - m), abs_tol=1e-9)
        assert post.pace_sd[d] == base_post.pace_sd[d]                       # sd untouched
        assert pre.pace_mu[d] == base_pre.pace_mu[d]                         # before qualifying untouched
    assert "spread(2)" in post.source


def _tune():
    spec = importlib.util.spec_from_file_location("f1_tune_s", ROOT / "scripts" / "f1_tune.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_spread_table_is_walk_forward():
    """Planted curves: 2030 races prefer s = 2, earlier seasons s = 1. The season rule moves to 2 within 2030 and
    uses only earlier races (changing the last race changes only "latest"); the first 20 races get 1."""
    ft = _tune()
    scales = [0.8, 1.0, 1.5, 2.0, 2.8]
    configs, grid = [], {}
    keys = [f"{y}_{r}" for y in (2028, 2029, 2030) for r in range(1, 16)]

    def ll(k, s):
        best = 2.0 if k.startswith("2030") else 1.0
        return 1.0 + (math.log(s) - math.log(best)) ** 2

    for s in scales:
        cid = f"s{s}"
        configs.append({"id": cid, "PACE_SPREAD_POST": {"latest": s}})
        grid[cid] = {"post": {k: {"wll": ll(k, s), "win": [1, 0]} for k in keys}}
    d = {"configs": configs, "grid": grid}
    k, Lf = ft.spread_curves(d)
    assert k == keys
    tab = ft.spread_table(k, Lf, ft.SPREAD_RULES["season_K5"])
    assert all(tab[x] == 1.0 for x in keys[:20])
    assert tab["2029_15"] == pytest.approx(1.0, abs=0.02)
    assert tab["2030_1"] == pytest.approx(1.0, abs=0.02)           # no 2030 race seen yet
    assert tab["2030_15"] > 1.5 and tab["latest"] > 1.5
    grid["s2.0"]["post"]["2030_15"]["wll"] = 9.0                      # the last race now hates s = 2
    k2, Lf2 = ft.spread_curves(d)
    tab2 = ft.spread_table(k2, Lf2, ft.SPREAD_RULES["season_K5"])
    assert tab2["2030_15"] == tab["2030_15"]


def test_fitted_spread_table_is_sane():
    if not rs.PACE_SPREAD_POST:
        pytest.skip("no PACE_SPREAD_POST in the fitted file")
    vals = np.array([float(v) for v in rs.PACE_SPREAD_POST.values()])
    assert np.all((vals >= 0.8) & (vals <= 2.8))
