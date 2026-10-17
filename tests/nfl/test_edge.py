"""NFL edge research helpers and the market-rating feature: no network, synthetic data only."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nfl.edge import blend as BL
from oddsmarkets.nfl.edge import evaluate as EV
from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.edge import prices as PR
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import market_ratings as MR


def _season(seed=0, n_weeks=10, season=2030):
    rng = np.random.default_rng(seed)
    teams = [f"T{i:02d}" for i in range(8)]
    true = dict(zip(teams, np.linspace(-6, 6, 8)))
    rows = []
    d0 = pd.Timestamp(f"{season}-09-10")
    for w in range(1, n_weeks + 1):
        perm = rng.permutation(teams)
        for k in range(4):
            h, a = perm[2 * k], perm[2 * k + 1]
            line = 2.0 + true[h] - true[a]
            rows.append({"game_id": f"{season}_{w:02d}_{a}_{h}", "season": season, "week": w,
                         "date": d0 + pd.Timedelta(days=7 * (w - 1)), "home": h, "away": a, "neutral": False,
                         "line": line + rng.normal(0, 0.5), "total_line": 44 + rng.normal(0, 1), "played": True})
    return pd.DataFrame(rows), true


def test_devig_and_prices():
    assert PR.am_to_dec(-110) == pytest.approx(1 + 100 / 110)
    assert PR.am_to_dec(150) == pytest.approx(2.5)
    assert np.isnan(PR.am_to_dec(50))
    a, b = PR.devig2(1.91, 1.91)
    assert a == pytest.approx(0.5) and a + b == pytest.approx(1.0)


def test_market_ratings_learn_and_never_see_their_own_week():
    G, true = _season()
    r = MR.ratings(G).merge(G, on="game_id")
    late = r[r["week"] >= 6]
    assert np.corrcoef(late["mr_line"], late["line"])[0, 1] > 0.95
    # changing week 7's lines (and later) must not move week 7's ratings
    G2 = G.copy()
    G2.loc[G2["week"] >= 7, "line"] += 30.0
    r2 = MR.ratings(G2).set_index("game_id")
    w7 = G.loc[G["week"] == 7, "game_id"]
    assert np.allclose(r.set_index("game_id").loc[w7, "mr_line"], r2.loc[w7, "mr_line"])
    # unplayed games never enter
    G3 = G.copy()
    G3.loc[G3["week"] == 5, "played"] = False
    G3.loc[G3["week"] == 5, "line"] = 99.0
    r3 = MR.ratings(G3).set_index("game_id")
    w6 = G.loc[G["week"] == 6, "game_id"]
    assert np.abs(r3.loc[w6, "mr_line"]).max() < 20


def test_market_ratings_delay_uses_older_games():
    G, _ = _season()
    a = MR.ratings(G).set_index("game_id")
    b = MR.ratings(G, delay_weeks=1).set_index("game_id")
    G2 = G.copy()
    G2.loc[G2["week"] == 6, "line"] += 30.0           # week 6 is the "previous week" of week 7
    b2 = MR.ratings(G2, delay_weeks=1).set_index("game_id")
    w7 = G.loc[G["week"] == 7, "game_id"]
    assert np.allclose(b.loc[w7, "mr_line"], b2.loc[w7, "mr_line"])
    assert not np.allclose(a.loc[w7, "mr_line"], b.loc[w7, "mr_line"])


def test_game_model_market_feature_falls_back_and_is_inert_unfitted():
    df = pd.DataFrame({"net_h": [3.0], "net_a": [-1.0], "neutral": [False], "rest_h": [7], "rest_a": [7],
                       "bye_h": [False], "bye_a": [False], "short_h": [False], "short_a": [False], "km_h": [0.0],
                       "km_a": [800.0], "tz_h": [0.0], "tz_a": [1.0], "div_game": [0]})
    F = GM.margin_features(df)
    assert F["mr"].iloc[0] == pytest.approx(0.77 * 4.0 + 2.0)
    p = GM.params({"mr": 0.0, "hfa_by_season": {}})
    p2 = dict(p, mr=0.0)
    assert GM.mu_margin(F, np.array([2030]), p)[0] == pytest.approx(GM.mu_margin(F, np.array([2030]), p2)[0])
    F2 = GM.margin_features(df.assign(f_mr=[5.5]))
    assert F2["mr"].iloc[0] == 5.5
    a = GM.mu_margin(F2, np.array([2030]), dict(p, mr=0.5))[0] - GM.mu_margin(F2, np.array([2030]), dict(p, mr=0.0))[0]
    assert a == pytest.approx(2.75)


def test_linemap_is_consistent():
    kk = GM.keys({"keys": [0.08, 1.0, 1.0, 2.8] + [1.0] * 3 + [1.8] + [1.0] * 23})
    lm = MK.LineMap(13.2, kk, 13.5, None)
    p, _ = lm.spread_at(np.array([-3.0]), np.array([0.55]), np.array([-3.0]))
    assert p[0] == pytest.approx(0.55, abs=2e-3)
    # laying more points is worth less, and crossing 3 costs more than crossing 5
    p35, _ = lm.spread_at(np.array([-3.0]), np.array([0.55]), np.array([-3.5]))
    p25, _ = lm.spread_at(np.array([-3.0]), np.array([0.55]), np.array([-2.5]))
    assert p35[0] < 0.55 < p25[0]
    q45, _ = lm.spread_at(np.array([-5.0]), np.array([0.55]), np.array([-5.5]))
    assert (0.55 - p35[0]) > (0.55 - q45[0])
    o, _ = lm.total_at(np.array([44.5]), np.array([0.5]), np.array([47.5]))
    assert o[0] < 0.5


def test_bet_table_clv_and_returns():
    S = pd.DataFrame({"event_id": ["g1", "g1"], "season": [2030, 2030], "week": [1, 1], "market": ["spread", "spread"],
                      "selection": ["home", "away"], "model_p": [0.56, 0.44], "price_dec": [1.91, 1.91],
                      "fair_p_decision": [0.5, 0.5], "fair_p_close": [0.54, 0.46], "outcome": [1.0, 0.0]})
    B = EV.bet_table(S, 0.0)
    assert len(B) == 1 and B["selection"].iloc[0] == "home"
    assert B["clv"].iloc[0] == pytest.approx(0.54 * 1.91 - 1)
    assert B["ret"].iloc[0] == pytest.approx(0.91)
    S.loc[0, "outcome"] = 0.5
    assert EV.bet_table(S, 0.0)["ret"].iloc[0] == 0.0


def test_residual_blend_recovers_signal_and_is_walk_forward():
    rng = np.random.default_rng(1)
    n = 6000
    seasons = np.repeat(np.arange(2000, 2012), n // 12)
    pm = rng.uniform(0.2, 0.8, n)
    z = rng.normal(0, 0.5, n)
    from scipy.special import expit, logit
    y = (rng.uniform(size=n) < expit(logit(pm) + 0.6 * z)).astype(float)
    pmod = expit(logit(pm) + z)
    out, co = BL.residual_close(pmod, pm, y, seasons, first_test=2005)
    assert np.isnan(out["p_blend"].to_numpy()[seasons < 2005]).all()
    assert 0.4 < co[2011][1] < 0.8
