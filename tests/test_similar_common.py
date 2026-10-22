"""oddsmarkets/common/similar.py: the spec's weighted similar-players recipe shared by the site builders."""
from __future__ import annotations

import math

import numpy as np

from oddsmarkets.common import similar as SIM


def test_group_config_reads_spec_weights_floored():
    cfg = SIM.group_config("hockey", "forwards")
    assert cfg["features"][0] == "gar_60" and cfg["k"] == 6
    assert cfg["weights"]["hits60"] == 0.91
    cfg = SIM.group_config("basketball", "nba_guards")              # weights as a dict under "weights"
    assert cfg["weights"]["ast_pct"] == 0.88
    cfg = SIM.group_config("baseball", "hitters_all")               # weights from the metrics' yoy_r
    assert all(w >= 0.2 for w in cfg["weights"].values())
    assert SIM.group_config("hockey", "nope") is None
    fb = SIM.group_config("nosport", "x", fallback={"features": ["a", "b"], "weights": {"a": 0.1}, "k": 3})
    assert fb == {"features": ["a", "b"], "weights": {"a": 0.2, "b": 0.2}, "k": 3}


def test_zscore_within_groups_and_constant_columns():
    X = np.array([[1.0, 5.0], [3.0, 5.0], [10.0, np.nan], [30.0, 7.0]])
    Z = SIM.zscore(X, groups=[1, 1, 2, 2])
    assert np.allclose(Z[:2, 0], [-1 / math.sqrt(2), 1 / math.sqrt(2)])
    assert np.allclose(Z[:2, 1], [0.0, 0.0])                       # no spread in season 1
    assert np.isnan(Z[2, 1]) and Z[3, 1] == 0.0                    # one value: no spread


def test_weighted_distance_and_nearest():
    Z = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [np.nan, 0.1]])
    w = np.array([0.8, 0.2])
    d = SIM.distances(Z, 0, w, min_weight=0.1)
    assert d[0] == math.inf
    assert math.isclose(d[1], math.sqrt(0.8))                      # the heavier feature counts more
    assert math.isclose(d[2], math.sqrt(0.2))
    assert math.isclose(d[3], 0.1)                                 # only the shared feature counts
    assert SIM.distances(Z, 0, w, min_weight=0.5)[3] == math.inf   # shares only 20% of the weight
    nb = SIM.nearest(Z, 0, w, k=2, min_weight=0.1)
    assert [j for j, _ in nb] == [3, 2]
    nb = SIM.nearest(Z, 0, w, k=5, allowed=np.array([True, True, False, False]), min_weight=0.1)
    assert [j for j, _ in nb] == [1]
    assert SIM.similarity(0.0) == 100.0 and SIM.similarity(math.inf) == 0.0
