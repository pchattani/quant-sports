"""The MLB market layer (models/market_layer.py): ratings from past closing lines, walk-forward without look-ahead,
the published adjustments. No network, no data on disk (synthetic games)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball.models import market_layer as ML

TEAMS = [str(100 + i) for i in range(10)]


def _games(n_days: int = 80, seed: int = 0, strength: dict | None = None, sp_eff: dict | None = None) -> pd.DataFrame:
    """Synthetic history: the market's residual over the simulation is team + starter effects plus noise."""
    rng = np.random.default_rng(seed)
    strength = strength or {t: v for t, v in zip(TEAMS, np.linspace(-0.3, 0.3, len(TEAMS)))}
    sp_eff = sp_eff or {}
    rows = []
    d0 = date(2025, 4, 1)
    for k in range(n_days):
        order = rng.permutation(TEAMS)
        for j in range(0, len(order), 2):
            h, a = order[j], order[j + 1]
            sh, sa = f"p{h}{k % 5}", f"p{a}{k % 5}"
            r = 0.03 + strength[h] - strength[a] + sp_eff.get(sh, 0.0) - sp_eff.get(sa, 0.0) + rng.normal(0, 0.05)
            rows.append({"gpk": f"{k}-{j}", "date": (d0 + timedelta(days=k)).isoformat(), "season": 2025, "home": h, "away": a,
                         "sp_home": sh, "sp_away": sa, "venue": f"v{h}", "r_c": r, "r_t": 0.5 if h == TEAMS[0] else -0.1})
    return pd.DataFrame(rows)


def test_fit_ratings_recovers_team_effects():
    hist = _games()
    coef = ML.fit_ratings(hist, "r_c", "ml", "2025-06-30", ML.CFG_ML)
    assert coef is not None and coef["n"] == len(hist)
    est = np.array([coef[("team", t)] for t in TEAMS])
    true = np.linspace(-0.3, 0.3, len(TEAMS))
    assert np.corrcoef(est, true)[0, 1] > 0.98
    assert abs(coef["_"] - 0.03) < 0.02


def test_fit_ratings_uses_only_earlier_games_and_min_rows():
    hist = _games(n_days=80)
    # on the 30th day only 29 days x 5 games = 145 rows are earlier: below MIN_ROWS
    assert ML.fit_ratings(hist, "r_c", "ml", "2025-04-30", ML.CFG_ML) is None
    a = ML.fit_ratings(hist, "r_c", "ml", "2025-06-01", ML.CFG_ML)
    # changing games on or after the as-of date must not change the fit
    h2 = hist.copy()
    h2.loc[h2["date"] >= "2025-06-01", "r_c"] += 5.0
    b = ML.fit_ratings(h2, "r_c", "ml", "2025-06-01", ML.CFG_ML)
    assert a["n"] == b["n"] and all(abs(a[k] - b[k]) < 1e-12 for k in a if k != "n")


def test_rolling_matches_single_day_fit_and_has_no_lookahead():
    hist = _games(n_days=90)
    pred = ML.rolling(hist, "r_c", "ml", ML.CFG_ML)
    day = "2025-06-15"
    coef = ML.fit_ratings(hist, "r_c", "ml", day, ML.CFG_ML)
    sub = hist[hist["date"] == day]
    for i, r in sub.iterrows():
        p = ML.predict(coef, ML.ml_terms(r.home, r.away, r.sp_home, r.sp_away))
        assert abs(p - pred[i]) < 1e-6
    # perturbing the future leaves earlier predictions unchanged
    h2 = hist.copy()
    h2.loc[h2["date"] >= day, "r_c"] = 9.0
    pred2 = ML.rolling(h2, "r_c", "ml", ML.CFG_ML)
    early = (hist["date"] <= day).to_numpy()
    assert np.allclose(np.nan_to_num(pred[early]), np.nan_to_num(pred2[early]))


def test_starter_effects_and_unknown_keys():
    sp = {"p1001": 0.4}
    hist = _games(n_days=90, sp_eff=sp)
    coef = ML.fit_ratings(hist, "r_c", "ml", "2025-07-01", ML.CFG_ML)
    assert coef[("sp", "p1001")] > 0.2
    # an unseen starter or a missing probable contributes nothing
    base = ML.predict(coef, ML.ml_terms("100", "101", None, None))
    assert base == pytest.approx(ML.predict(coef, ML.ml_terms("100", "101", "nobody", "None")))


def test_totals_venue_effect():
    hist = _games(n_days=90)
    coef = ML.fit_ratings(hist, "r_t", "tot", "2025-07-01", ML.CFG_TOT)
    v0 = ML.predict(coef, ML.tot_terms(TEAMS[0], TEAMS[1], None, None, f"v{TEAMS[0]}"))
    v1 = ML.predict(coef, ML.tot_terms(TEAMS[1], TEAMS[0], None, None, f"v{TEAMS[1]}"))
    assert v0 - v1 > 0.4


def test_shift_dist_and_totals_curve():
    dist = np.zeros(31)
    dist[5:14] = [0.05, 0.08, 0.12, 0.15, 0.16, 0.15, 0.12, 0.1, 0.07]
    dist /= dist.sum()
    mean = float(np.arange(31) @ dist)
    sh = ML.shift_dist(dist, 0.7)
    assert sh.sum() == pytest.approx(1.0)
    assert float(np.arange(31) @ sh) == pytest.approx(mean + 0.7, abs=0.02)
    # no recalibration: the curve is the shifted distribution
    c0, m0 = ML.totals_curve(dist, 0.7, None)
    assert np.allclose(c0, sh)
    # a shrinking recalibration pulls P(over) near the mean toward 1/2 and keeps tails monotone
    c1, _ = ML.totals_curve(dist, 0.0, [0.0, 0.3])
    L = round(mean) + 1.5
    assert abs(ML.p_over_dist(c1, L) - 0.5) < abs(ML.p_over_dist(dist, L) - 0.5)
    tails = [ML.p_over_dist(c1, x + 0.5) for x in range(3, 16)]
    assert all(a >= b - 1e-12 for a, b in zip(tails, tails[1:]))


def test_layer_apply_keeps_sim_and_is_consistent():
    hist = _games(n_days=90)
    lay = ML.Layer(ML.fit_ratings(hist, "r_c", "ml", "2025-07-01", ML.CFG_ML), ML.fit_ratings(hist, "r_t", "tot", "2025-07-01", ML.CFG_TOT),
                   {"platt": [0.0, 1.0], "tot_recal": [0.0, 0.5], "runline": [0.0, 1.0, 1.0]}, "2025-07-01")
    dist = [0.0] * 3 + [0.02, 0.04, 0.07, 0.1, 0.12, 0.13, 0.13, 0.11, 0.09, 0.07, 0.05, 0.03, 0.02, 0.01, 0.01] + [0.0] * 23
    mu = float(np.arange(len(dist)) @ np.array(dist))
    s = {"p_home": 0.5, "p_away": 0.5, "runline": {"home_-1.5": 0.33, "away_+1.5": 0.67, "home_+1.5": 0.68, "away_-1.5": 0.32},
         "runs": {"home": mu / 2, "away": mu / 2, "total": mu}, "total_dist": dist,
         "over": {"8.5": 0.5}}
    g = {"home": TEAMS[-1], "away": TEAMS[0], "probables": {"home": None, "away": None}, "venue": "elsewhere"}
    out = lay.apply(s, g)
    assert out["sim"]["p_home"] == 0.5 and out["p_home"] > 0.6            # strongest v weakest team
    assert out["p_home"] + out["p_away"] == pytest.approx(1.0)
    rl = out["runline"]
    assert rl["home_-1.5"] + rl["away_+1.5"] == pytest.approx(1.0) and rl["home_-1.5"] > 0.33
    assert rl["home_-1.5"] < out["p_home"] < rl["home_+1.5"]
    assert sum(out["total_dist"]) == pytest.approx(1.0, abs=1e-3)
    assert out["runs"]["total"] == pytest.approx(out["runs"]["home"] + out["runs"]["away"], abs=1e-3)
    assert "8.5" in out["over"] and "8.0" in out["over"]
    # the input summary is not modified
    assert s["p_home"] == 0.5 and s["runline"]["home_-1.5"] == 0.33
    json.dumps(out)


def test_layer_off_without_history(monkeypatch):
    monkeypatch.setattr(ML, "history", lambda *a, **k: pd.DataFrame())
    assert ML.build("mlb", 2027, {"games": {}}, as_of="2027-04-01") is None
    assert ML.build("aaa", 2027, {"games": {}}, as_of="2027-04-01") is None


def test_committed_fit_is_sane():
    fit = ML.load_fit()
    assert fit is not None and fit["version"] == ML.VERSION
    a, b = fit["platt"]
    assert abs(a) < 0.1 and 0.7 < b < 1.2
    assert 0 < fit["tot_recal"][1] < 1.0
    assert len(fit["runline"]) == 3 and fit["runline"][1] > 0 and fit["runline"][2] > 0
