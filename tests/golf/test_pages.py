import numpy as np
import pandas as pd

from oddsmarkets.golf import pages
from oddsmarkets.golf.models import sim


def test_live_sim_from_the_scores_so_far():
    r = np.zeros(4)
    base = np.array([-10.0, 0.0, 0.0, -3.0])
    left = np.full(4, 1.0)
    on = np.array([True, True, True, False])
    out = sim.simulate_live(r, 3.0, base, np.zeros(4), left, on, n=4000, seed=1)
    assert out["win"][0] > 0.9                       # ten clear with a round to play
    assert out["win"][3] == 0 and out["make_cut"][3] == 0
    assert abs(out["win"].sum() - 1) < 1e-9
    done = sim.simulate_live(r, 3.0, base, np.zeros(4), np.zeros(4), on, n=200, seed=1)
    assert done["win"][0] == 1.0                     # nothing left to play: the leader has won


def test_live_sim_applies_a_pending_cut():
    r = np.zeros(6)
    base = np.array([-6.0, -5.0, -4.0, 4.0, 5.0, 6.0])
    out = sim.simulate_live(r, 0.5, base, np.full(6, 0.25), np.full(6, 2.0), np.ones(6, bool), cut_count=3, n=2000, seed=2)
    assert (out["make_cut"][:3] > 0.99).all() and (out["make_cut"][3:] < 0.01).all()


def test_cut_rule_defaults():
    assert pages._cut_rule({"cut_round": 2, "cut_count": 70}, "pga", 150) == (2, 70)
    assert pages._cut_rule({"status": "upcoming"}, "pga", 144) == (2, 65)
    assert pages._cut_rule({"status": "upcoming"}, "pga", 72) == (0, 0)          # a small field: no cut
    assert pages._cut_rule({"status": "upcoming"}, "liv", 54) == (0, 0)
    assert pages._cut_rule({"status": "final"}, "pga", 150) == (0, 0)            # a final event names its own cut


def test_offsets_average_the_trailing_year():
    d = pd.to_datetime(["2024-01-01", "2024-06-01", "2025-03-01"])
    sg = pd.DataFrame({"tour": ["pga", "pga", "pga"], "date": d, "pre": [1.0, 3.0, 5.0]})
    off = pages.Offsets(sg, "pga")
    assert off.at("2024-01-01") == 0.0                                           # nothing before
    assert off.at("2024-07-01") == 2.0
    assert off.at("2025-06-02") == 5.0                                           # 2024-01 and 2024-06 have aged out
