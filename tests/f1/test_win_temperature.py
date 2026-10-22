"""The post-qualifying win temperature (21 Oct 2026, docs/research/f1_edge.md "Model-improvement program"):
race_sim.temper_win / win_temp_post and scripts/f1_tune.py's walk-forward table. Offline, planted inputs."""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.f1.models import race_sim as rs

ROOT = Path(__file__).resolve().parents[2]


def _drivers(pw, pod=None):
    pod = pod or [min(1.0, 3 * p) for p in pw]
    return {f"d{i}": {"p_win": p, "p_podium": q, "p_points": 0.5} for i, (p, q) in enumerate(zip(pw, pod))}


def test_temper_win_sharpens_and_sums_to_one():
    d = _drivers([0.5, 0.3, 0.15, 0.05])
    rs.temper_win(d, 1.5)
    p = [d[k]["p_win"] for k in sorted(d)]
    assert math.isclose(sum(p), 1.0, abs_tol=1e-9)
    assert p[0] > 0.5 and p[3] < 0.05                     # favourite up, outsider down
    assert p == sorted(p, reverse=True)                    # order kept
    assert all(d[k]["p_points"] == 0.5 for k in d)         # nothing else touched


def test_temper_win_identity_and_podium_cap():
    d = _drivers([0.5, 0.5])
    assert rs.temper_win(d, 1.0) is d and d["d0"]["p_win"] == 0.5
    d = _drivers([0.8, 0.2], pod=[0.82, 0.9])
    rs.temper_win(d, 3.0)
    assert d["d0"]["p_win"] <= 0.82                        # a win is a podium


def test_win_temp_post_lookup(monkeypatch):
    monkeypatch.setattr(rs, "WIN_TEMP_POST", {"2026_5": 1.2, "latest": 1.15})
    assert rs.win_temp_post(2026, 5) == 1.2
    assert rs.win_temp_post(2026, 6) == 1.15               # not in the table: the latest fit
    monkeypatch.setattr(rs, "WIN_TEMP_POST", {"2026_5": float("nan")})
    assert rs.win_temp_post(2026, 5) == 1.0                # unusable -> off
    monkeypatch.setattr(rs, "WIN_TEMP_POST", {})
    assert rs.win_temp_post(2026, 5) == 1.0


def _tune():
    spec = importlib.util.spec_from_file_location("f1_tune_t", ROOT / "scripts" / "f1_tune.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_win_temp_table_is_walk_forward():
    """Races where the favourite wins more often than forecast (8 in 10 at 60%): the table's T rises above 1 and
    uses only earlier races (the first min_races entries are 1.0; changing the last race's outcome changes only
    "latest")."""
    ft = _tune()
    races = {}
    pattern = [0, 0, 1, 0, 0, 0, 2, 0, 0, 0]
    for i in range(40):
        w = [0, 0, 0]
        w[pattern[i % 10]] = 1
        races[f"2030_{i + 1}"] = {"wll": 1.0, "pw": [0.6, 0.25, 0.15], "win": w}
    grid = {"c": {"post": races}}
    tab = ft.win_temp_table(grid, "c", min_races=5)
    assert all(tab[f"2030_{i + 1}"] == 1.0 for i in range(5))
    assert tab["2030_20"] > 1.2 and tab["latest"] > 1.2
    races["2030_40"] = {"wll": 1.0, "pw": [0.5, 0.3, 0.2], "win": [0, 0, 1]}
    tab2 = ft.win_temp_table(grid, "c", min_races=5)
    assert tab2["2030_40"] == tab["2030_40"] and tab2["latest"] < tab["latest"]


def test_fitted_table_is_sane():
    if not rs.WIN_TEMP_POST:
        pytest.skip("no WIN_TEMP_POST in the fitted file")
    vals = np.array([float(v) for v in rs.WIN_TEMP_POST.values()])
    assert np.all((vals >= 0.5) & (vals <= 3.0))
