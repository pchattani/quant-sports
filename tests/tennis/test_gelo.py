"""Game-share Elo (models/gelo.py) and its term in the match price (predict.py, backtest.py)."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.tennis.models import backtest as BT
from oddsmarkets.tennis.models import gelo as G
from oddsmarkets.tennis.models import match_chain as mc
from oddsmarkets.tennis.models import predict as PR


def _m(i, d, p1, p2, sets, status="done", surface="hard"):
    return {"id": f"m{i}", "date": d, "p1": p1, "p2": p2, "sets": sets, "status": status, "surface": surface}


def test_margin_moves_the_rating_and_is_zero_sum():
    ms = [_m(1, "2024-01-01", "a", "b", [[6, 0], [6, 0]]), _m(2, "2024-01-02", "c", "d", [[7, 6], [7, 6]])]
    h = G.history("atp", matches=ms)
    cur = h["current"]
    assert cur["a"]["all"] > cur["c"]["all"] > 0          # a 6-0 6-0 moves more than a 7-6 7-6
    assert cur["a"]["all"] == pytest.approx(-cur["b"]["all"])
    assert cur["a"]["hard"] > 0 and cur["a"]["clay"] == 0.0
    assert G.pre_match(h) == {"m1": 0.0, "m2": 0.0}       # nobody rated before


def test_walkovers_skip_and_retirements_count_half():
    ms = [_m(1, "2024-01-01", "a", "b", [], status="wo"), _m(2, "2024-01-02", "a", "b", [[6, 2], [3, 0]], status="ret"),
          _m(3, "2024-01-02", "c", "d", [[6, 2], [3, 0]])]
    h = G.history("atp", matches=ms)
    assert [g[0] for g in h["rows"]] == ["m2", "m3"]
    assert 0 < h["current"]["a"]["all"] < h["current"]["c"]["all"]


def test_pre_match_and_ratings_at_are_walk_forward():
    ms = [_m(1, "2024-01-01", "a", "b", [[6, 1], [6, 1]]), _m(2, "2024-01-05", "a", "b", [[6, 1], [6, 1]])]
    h = G.history("wta", matches=ms)
    pre = G.pre_match(h)
    assert pre["m1"] == 0.0 and pre["m2"] > 0
    r = G.ratings_at(h, "2024-01-03")
    assert G.diff(r["a"], r["b"], "hard", G.params("wta")) == pytest.approx(pre["m2"], abs=1e-4)
    assert G.diff(r["a"], None) == 0.0                     # an unrated player carries no information
    assert G.ratings_at(h, "2024-01-01") == {}


def test_blend_third_term_and_fit_recovers_it():
    rng = np.random.default_rng(3)
    n = 30000
    e = rng.uniform(0.1, 0.9, n)
    s = np.clip(e + rng.normal(0, 0.15, n), 0.02, 0.98)
    g = rng.normal(0, 0.5, n)
    p = PR.blend(e, s, 0.6, 0.3, g, 0.4)
    y = (rng.random(n) < p).astype(int)
    f = PR.fit_blend(e, s, y, gdiff=g)
    assert abs(f["w_elo"] - 0.6) < 0.12 and abs(f["w_sr"] - 0.3) < 0.12 and abs(f["w_gelo"] - 0.4) < 0.08
    assert "w_gelo" not in PR.fit_blend(e, s, y)
    assert PR.blend(0.7, 0.6, 0.6, 0.3) == pytest.approx(PR.blend(0.7, 0.6, 0.6, 0.3, 1.0, 0.0))


def test_predict_uses_the_game_share_term_symmetrically():
    kw = dict(elo_fn=lambda a, b, s, bo: 0.6 if a == "a" else 0.4,
              p_srv_fn=lambda a, b, s, l, bo: (0.64, 0.62) if a == "a" else (0.62, 0.64),
              gelo_fn=lambda a, b, s: 0.5 if a == "a" else -0.5)
    on = PR.Context("atp", "2026-10-01", blend={"w_elo": 0.6, "w_sr": 0.4, "w_gelo": 0.3}, **kw)
    off = PR.Context("atp", "2026-10-01", blend={"w_elo": 0.6, "w_sr": 0.4}, **kw)
    a = PR.predict("atp", "a", "b", "hard", ctx=on)
    b = PR.predict("atp", "b", "a", "hard", ctx=on)
    c = PR.predict("atp", "a", "b", "hard", ctx=off)
    sr = mc.match(0.64, 0.62)["p1_win"]
    assert a["p1_win"] == pytest.approx(float(PR.blend(0.6, sr, 0.6, 0.4, 0.5, 0.3)), abs=1e-6)
    assert a["p1_win"] + b["p1_win"] == pytest.approx(1.0, abs=1e-6)
    assert a["p1_win"] > c["p1_win"] and a["gelo_diff"] == 0.5
    M = PR.prob_matrix(on, ["a", "b"], "hard", 3, "250")
    assert np.allclose(M + M.T, 1.0)


def test_backtest_evaluate_fits_and_applies_the_third_weight():
    rng = np.random.default_rng(5)
    rows = []
    for i in range(4000):
        e, s, g = float(rng.uniform(0.2, 0.8)), float(rng.uniform(0.2, 0.8)), float(rng.normal(0, 0.6))
        p = float(PR.blend(e, s, 0.6, 0.3, g, 0.5))
        win = rng.random() < p                              # store rows have p1 = winner: flip when p2 won
        fl = not win
        rows.append({"year": 2010 + i // 2000, "elo": e if not fl else 1 - e, "sr": s if not fl else 1 - s,
                     "gelo": g if not fl else -g, "flip": fl, "rank_x": 0.0, "books": {}, "level": "250"})
    ev = BT.evaluate(rows, [2011], tour="atp")
    w = ev["blend_by_year"]["2011"]
    assert w["fitted"] and abs(w["w_gelo"] - 0.5) < 0.2
    r = ev["_scored"][0]
    assert r["_model"] == pytest.approx(float(PR.blend(r["elo"], r["sr"], w["w_elo"], w["w_sr"], r["gelo"], w["w_gelo"])),
                                        abs=1e-3)
