"""Round-4 research helpers (research/round4.py): DNP reasons, the RAPM prior split, the logistic fit, the
expected-rotation aggregation (it must match models/informed.Rotation.expected) and the probit offset fit."""

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.basketball.models import informed as INF
from oddsmarkets.basketball.research import round4 as R4


@pytest.mark.parametrize("why,cat", [
    ("COACH'S DECISION", "coach"), ("LEFT ANKLE SPRAIN", "injury"), ("RIGHT KNEE SURGERY", "major"),
    ("LEFT HAMSTRING TEAR", "major"), ("ILLNESS", "ill"), ("REST", "rest"), ("LEFT KNEE INJURY MANAGEMENT", "rest"),
    ("NOT WITH TEAM", "personal"), ("SUSPENDED BY LEAGUE", "susp"), ("ASSIGNED TO G LEAGUE", "gleague"),
    ("DID NOT DRESS", "inactive"), ("", "inactive"), (None, "inactive")])
def test_reason_cat(why, cat):
    assert R4.reason_cat(why) == cat


def test_split_od_keeps_net():
    o, d = R4._split_od([3.0, 1.0, 0.5])
    assert o + d == pytest.approx(3.0)
    assert o - d == pytest.approx(0.5)


def test_logit_fit_recovers_coefficients():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(20000, 2))
    p = 1 / (1 + np.exp(-(0.5 + 1.2 * X[:, 0] - 0.7 * X[:, 1])))
    y = (rng.random(20000) < p).astype(float)
    th = R4.logit_fit(X, y, l2=1e-6)
    assert th == pytest.approx([0.5, 1.2, -0.7], abs=0.06)
    assert R4.logit_pred(X[:3], th).shape == (3,)


def test_expected_S_matches_rotation():
    vals = {"a": [4.0, 2.5, 1.5, 900], "b": [1.0, 0.0, 1.0, 900], "c": [-1.0, -0.5, -0.5, 900], "d": [2.0, 1.0, 1.0, 900],
            "e": [0.0, 0.0, 0.0, 900], "f": [-2.0, -1.0, -1.0, 900]}
    rot = INF.Rotation("nba", vals, {"T": {}}, {}, {})
    mpg = {"a": 36.0, "b": 34.0, "c": 30.0, "d": 28.0, "e": 25.0, "f": 20.0}
    streak = {"a": 0, "b": 1, "c": 0, "d": 3, "e": 0, "f": 0}
    for pid, m in mpg.items():
        rot.st["T"][pid] = {"mpg": m, "streak": streak[pid]}
    want = rot.expected("T")
    pr = pd.DataFrame({"event_id": "g", "side": "h", "pid": list(mpg), "mpg": list(mpg.values()),
                       "streak": [streak[p] for p in mpg],
                       "v_static_net": [vals[p][0] for p in mpg], "v_static_o": [vals[p][1] for p in mpg],
                       "v_static_d": [vals[p][2] for p in mpg]})
    got = R4.expected_S(pr, R4.streak_rate(pr, "nba"), "static", "nba").iloc[0]
    assert [got.S_net, got.S_o, got.S_d] == pytest.approx(list(want), abs=1e-9)


def test_design_has_no_outcome_and_buckets_streaks():
    pr = pd.DataFrame({"streak": [0, 1, 4, 12], "reason": ["none", "injury", "major", "absent"], "mpg": [30.0, 20, 10, 5],
                       "last_min": [32.0, 0, 0, 0], "min7": [90.0, 20, 0, 0], "b2b": [1, 0, 0, 0], "age": [33.0, 25, np.nan, 22],
                       "phase": [0.95, 0.5, 0.2, 0.1], "wp": [0.3, 0.5, 0.5, 0.5], "stype": ["reg", "reg", "post", "reg"],
                       "tg": [70, 40, 3, 20], "gp": [65, 30, 1, 2], "days_off": [1, 3, 15, 40], "moved": [0, 0, 0, 1],
                       "played": [1, 0, 0, 0]})
    X, names = R4.design(pr)
    assert X.shape == (4, len(names))
    assert "played" not in names
    assert list(R4._sb(pr.streak.to_numpy())) == [0, 1, 4, 6]


def test_probit_offset_fit_finds_signal():
    rng = np.random.default_rng(1)
    mu = rng.normal(0, 6, 8000)
    x = rng.normal(0, 1, 8000)
    y = (mu - 2.0 * x + rng.normal(0, 11.5, 8000) > 0).astype(float)
    assert R4.probit_offset_fit(mu, 11.5, x, y) == pytest.approx(-2.0, abs=0.6)
