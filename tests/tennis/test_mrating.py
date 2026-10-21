"""Market rating (models/mrating.py) and its term in the match price (predict.py, backtest.py)."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.tennis.models import backtest as BT
from oddsmarkets.tennis.models import mrating as MR
from oddsmarkets.tennis.models import predict as PR


def _m(i, d, p1, p2, odds=None, status="done", winner=None, surface="hard", bo=3, r1=None, r2=None):
    return {"id": f"m{i}", "date": d, "p1": p1, "p2": p2, "status": status, "winner": winner or p1,
            "surface": surface, "best_of": bo, "odds": odds or {}, "rank1": r1, "rank2": r2, "sets": [[6, 4], [6, 4]]}


def test_power_devig_and_book_order():
    p = MR.close_p1({"ps": [1.5, 2.8]})
    q = 1 / 1.5
    assert 0.6 < p < q                                       # de-vigged below the raw implied probability
    assert MR.close_p1({"avg": [1.5, 2.8], "ps": [2.0, 1.9]}) == pytest.approx(MR.close_p1({"ps": [2.0, 1.9]}))
    assert MR.close_p1({"ps": [1.2, 1.2]}) is None           # a 66 % margin fails the sanity check, no other book
    assert MR.close_p1({"ps": [1.2, 1.2], "avg": [1.5, 2.8]}) == pytest.approx(p)


def test_close_moves_the_rating_and_the_pair_is_antisymmetric():
    prm = MR.params("atp")
    ms = [_m(1, "2024-01-01", "a", "b", {"ps": [1.3, 3.8]}, r1=50, r2=50),
          _m(2, "2024-01-05", "a", "b", status="upcoming", r1=50, r2=50)]
    h = MR.history("atp", matches=ms, prm=prm)
    pre = MR.pre_match(h)
    assert pre["m1"] == pytest.approx(0.0)                  # same rank: no difference before any price
    assert pre["m2"] > 0.5                                  # the 1.3 favourite (and winner) is now rated above
    cur = h["current"]
    assert MR.diff(cur["a"], cur["b"], "hard", prm) == pytest.approx(-MR.diff(cur["b"], cur["a"], "hard", prm))
    assert MR.diff(cur["a"], cur["b"], "hard", prm) == pytest.approx(pre["m2"], abs=1e-6)


def test_walk_forward_a_match_never_sees_its_own_price_or_result():
    ms = [_m(1, "2024-01-01", "a", "b", {"ps": [1.1, 8.0]}, r1=100, r2=100)]
    h = MR.history("wta", matches=ms)
    assert MR.pre_match(h)["m1"] == pytest.approx(0.0)
    lag = MR.run(MR.prepare(ms), MR.params("wta"), day_lag=False)["pre"]
    assert lag["m1"][0] == pytest.approx(0.0)


def test_results_move_unpriced_matches_and_walkovers_do_nothing():
    prm = MR.params("atp")
    ms = [_m(1, "2024-01-01", "a", "b", r1=300, r2=300), _m(2, "2024-01-01", "c", "d", status="wo", r1=300, r2=300)]
    cur = MR.history("atp", matches=ms, prm=prm)["current"]
    assert cur["a"][0] > cur["b"][0]
    assert cur["c"][0] == pytest.approx(cur["d"][0])
    assert cur["a"][1] < prm["p0"]                          # the result shrank the variance


def test_rank_prior_and_unknown_players():
    prm = MR.params("atp")
    assert MR.rating(MR.prior(prm, 10.0), "hard", prm) > MR.rating(MR.prior(prm, 200.0), "hard", prm)
    assert MR.diff(None, None, "clay", prm) == 0.0
    assert MR.rating(None, "hard", prm) == pytest.approx(MR.rating(MR.prior(prm), "hard", prm))
    assert MR.scale(5, prm) == prm["s5"] and MR.scale(3, prm) == 1.0


def test_snapshots_are_the_states_before_the_day():
    prm = MR.params("atp")
    ms = [_m(1, "2024-01-01", "a", "b", {"ps": [1.3, 3.8]}), _m(2, "2024-01-10", "a", "b", {"ps": [1.3, 3.8]})]
    prep = MR.prepare(ms)
    from datetime import date
    snap = MR.snapshots(prep, prm, {date(2024, 1, 1).toordinal(): {"a"}, date(2024, 1, 10).toordinal(): {"a", "b"}})
    assert snap[date(2024, 1, 1).toordinal()] == {}
    s2 = snap[date(2024, 1, 10).toordinal()]
    pre = MR.pre_match(MR.history("atp", matches=ms, prm=prm))
    assert MR.diff(s2["a"], s2["b"], "hard", prm) == pytest.approx(pre["m2"], abs=1e-5)


def test_blend_fourth_term_fit_and_predict():
    rng = np.random.default_rng(7)
    n = 30000
    e = rng.uniform(0.1, 0.9, n)
    s = np.clip(e + rng.normal(0, 0.15, n), 0.02, 0.98)
    g = rng.normal(0, 0.5, n)
    m = rng.normal(0, 0.8, n)
    p = PR.blend(e, s, 0.4, 0.2, g, 0.5, m, 0.6)
    y = (rng.random(n) < p).astype(int)
    f = PR.fit_blend(e, s, y, gdiff=g, mdiff=m)
    assert abs(f["w_mr"] - 0.6) < 0.08 and abs(f["w_gelo"] - 0.5) < 0.1
    assert "w_mr" not in PR.fit_blend(e, s, y, gdiff=g)
    kw = dict(elo_fn=lambda a, b, s_, bo: 0.6 if a == "a" else 0.4,
              p_srv_fn=lambda a, b, s_, l, bo: (0.64, 0.62) if a == "a" else (0.62, 0.64),
              gelo_fn=lambda a, b, s_: 0.0, mr_fn=lambda a, b, s_, bo: 0.8 if a == "a" else -0.8)
    on = PR.Context("atp", "2026-10-01", blend={"w_elo": 0.5, "w_sr": 0.3, "w_gelo": 0.0, "w_mr": 0.5}, **kw)
    off = PR.Context("atp", "2026-10-01", blend={"w_elo": 0.5, "w_sr": 0.3}, **kw)
    a, b = PR.predict("atp", "a", "b", "hard", ctx=on), PR.predict("atp", "b", "a", "hard", ctx=on)
    assert a["p1_win"] + b["p1_win"] == pytest.approx(1.0, abs=1e-6)
    assert a["p1_win"] > PR.predict("atp", "a", "b", "hard", ctx=off)["p1_win"] and a["mr_diff"] == 0.8
    M = PR.prob_matrix(on, ["a", "b"], "hard", 3, "250")
    assert np.allclose(M + M.T, 1.0)


def test_context_states_price_unknowns_with_the_prior():
    prm = MR.params("wta")
    st = {"a": [1.0, 0.1, 0.2, 0.0, 0.0, 0.05, 0.05, 0.05, 0, 3, 3]}
    ctx = PR.Context("wta", "2026-10-01", blend={"w_elo": 0.5, "w_sr": 0.3, "w_mr": 0.5}, mr_states=st, mr_params=prm)
    assert ctx.mr_diff("a", "zz", "hard", 3) == pytest.approx(1.2 - MR.rating(MR.prior(prm), "hard", prm))
    assert ctx.mr_diff("a", "zz", "clay", 3) == pytest.approx(1.0 - MR.rating(MR.prior(prm), "clay", prm))


def test_backtest_evaluate_fits_the_market_weight_and_scores_the_fundamental_blend():
    rng = np.random.default_rng(11)
    rows = []
    for i in range(4000):
        e, s, g, m = (float(rng.uniform(0.2, 0.8)), float(rng.uniform(0.2, 0.8)), float(rng.normal(0, 0.6)),
                      float(rng.normal(0, 0.8)))
        p = float(PR.blend(e, s, 0.5, 0.2, g, 0.4, m, 0.7))
        fl = not (rng.random() < p)
        rows.append({"year": 2010 + i // 2000, "elo": e if not fl else 1 - e, "sr": s if not fl else 1 - s,
                     "gelo": g if not fl else -g, "mr": m if not fl else -m, "flip": fl, "rank_x": 0.0,
                     "books": {}, "level": "250"})
    ev = BT.evaluate(rows, [2011], tour="atp")
    w = ev["blend_by_year"]["2011"]
    assert w["fitted"] and abs(w["w_mr"] - 0.7) < 0.2
    r = ev["_scored"][0]
    assert r["_model"] == pytest.approx(float(PR.blend(r["elo"], r["sr"], w["w_elo"], w["w_sr"], r["gelo"], w["w_gelo"],
                                                       r["mr"], w["w_mr"])), abs=1e-3)
    assert ev["metrics"]["model"]["logloss"] < ev["metrics"]["model_fund"]["logloss"]
