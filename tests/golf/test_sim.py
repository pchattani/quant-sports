import numpy as np

from oddsmarkets.golf.models import sim


def test_equal_players_share_the_win_and_better_players_win_more():
    eq = sim.simulate(np.zeros(10), 2.8, cut_round=0, n=20000, seed=1)
    assert abs(eq["win"].sum() - 1) < 1e-9 and np.allclose(eq["win"], 0.1, atol=0.015)
    assert (eq["top5"] >= 0.5 - 0.02).all()          # ties count, so at least half the field is top 5 on average
    sk = sim.simulate(np.array([3.0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), 2.8, cut_round=0, n=20000, seed=2)
    assert sk["win"][0] > 0.4 and sk["rank"][0] < sk["rank"][1:].min()


def test_cut_keeps_the_count_and_ties():
    r = np.linspace(2, -2, 100)
    out = sim.simulate(r, 2.8, cut_round=2, cut_count=65, n=4000, seed=3)
    assert 65 <= out["make_cut"].sum() <= 75
    assert out["make_cut"][0] > out["make_cut"][-1] and out["make_cut"][0] > 0.9
    small = sim.simulate(np.zeros(50), 2.8, cut_round=2, cut_count=65, n=1000, seed=4)
    assert np.allclose(small["make_cut"], 1.0)
