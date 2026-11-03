"""The call-up model ranks a better line above a worse one, and stays a probability.
Counting-line catalogues (levels with no pitch table) produce the same rate columns the pages show."""
import numpy as np

from oddsmarkets.baseball.analytics.lines_catalog import _hitter, _pitcher
from oddsmarkets.baseball.models import callup


def test_counting_lines_fill_the_catalogue_rates():
    v, n, pa = _hitter({"pa": 100, "ab": 90, "h": 30, "d": 8, "t": 1, "hr": 4, "bb": 8, "hbp": 1, "so": 20, "sf": 1, "g": 25})
    assert pa == 100 and n["pa"] == 100
    assert abs(v["avg"] - 30 / 90) < 1e-9
    assert v["woba"] and v["ops"]
    v, n, bf = _pitcher({"bf": 100, "outs": 75, "h": 20, "hr": 2, "bb": 8, "hbp": 1, "so": 25, "r": 10,
                         "g": 10, "gs": 5, "w": 2, "l": 1, "sv": 0})
    assert bf == 100 and abs(v["ip"] - 25) < 1e-9
    assert v["fip"] > 0 and abs(v["whip"] - (20 + 8) / 25) < 1e-9


def test_logit_ranks_the_better_line():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(400, 2))
    y = (x[:, 1] + rng.normal(scale=0.4, size=400) > 0).astype(float)
    X = np.column_stack([np.ones(400), x])
    coef = callup.logit_fit(X, y)
    low = callup.prob(coef, [1.0, 0.0, -2.0])
    high = callup.prob(coef, [1.0, 0.0, 2.0])
    assert 0.0 < low < high < 1.0


def test_level_only_width_is_the_level_dummies():
    rows = []
    for i, lv in enumerate(("a", "hia", "aa", "aaa")):
        feats = [1.0, float(lv == "aaa"), float(lv == "aa"), float(lv == "hia"), float(lv == "a"), 0, 0, 0, 0, 0, 0]
        for n in range(60):
            rows.append((2018, feats, lv, 1.0 if lv in ("aa", "aaa") else 0.0, None, str(i * 100 + n), {}))
            rows.append((2021, feats, lv, 1.0 if lv in ("aa", "aaa") else 0.0, None, str(500 + i * 100 + n), {}))
    chosen = callup._choose(rows, 3)
    assert chosen["validation"]["n"] == 240
    assert chosen["width"] == 5
    assert 0.0 < callup.prob(np.array(chosen["coef"]), rows[0][1]) < 1.0
