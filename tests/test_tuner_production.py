"""
The tuner must score the model the build publishes.

Until 21 October 2026 `scripts/tune_league_models.py` fitted plain goals/xG frames while
the build added market-rate rows (weight 96, own decay 0.03), so a re-run of the tuner
would have chosen parameters for a model nobody publishes. Both now make their Dixon-Coles
frames and fits through `oddsmarkets.football.competitions.league.fitting`. These tests
pin that: the tuner's fold frame is the production frame, built with the live market-rate
constants and the candidate xi; the build's own, pooled and Argentine fits go through the
same functions; the tuner's folds see nothing from the day they score; and every club fit
holds the separately estimated rho (docs/MODELS.md 2.4-2.5, 5.1).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from oddsmarkets.football.competitions.league import fitting  # noqa: E402
from oddsmarkets.football.core import DixonColesModel  # noqa: E402
from oddsmarkets.football.sources import market_rates as mr  # noqa: E402
from oddsmarkets.sports.world_cup.models.dixon_coles import estimate_rho  # noqa: E402

SLUG = "premier-league"
TEAMS = [f"T{i:02d}" for i in range(10)]


def _dc_scores(rng, lh, la, rho, max_goals=10):
    """Sample scorelines from the Dixon-Coles distribution (Poisson x Poisson x tau)."""
    from scipy.stats import poisson
    k = np.arange(max_goals + 1)
    out = []
    for a, b in zip(lh, la):
        m = np.outer(poisson.pmf(k, a), poisson.pmf(k, b))
        m[0, 0] *= 1 - a * b * rho
        m[1, 0] *= 1 + b * rho
        m[0, 1] *= 1 + a * rho
        m[1, 1] *= 1 - rho
        m = np.clip(m, 0, None).ravel()
        c = rng.choice(len(m), p=m / m.sum())
        out.append(divmod(int(c), max_goals + 1))
    return np.array(out)


def _league(rounds: int = 4, seed: int = 3, rho: float = -0.1, xg: bool = True) -> pd.DataFrame:
    """A double round-robin repeated `rounds` times, one match day every 3-4 days, xG on every match."""
    rng = np.random.default_rng(seed)
    att = dict(zip(TEAMS, rng.normal(0, 0.25, len(TEAMS))))
    dfn = dict(zip(TEAMS, rng.normal(0, 0.2, len(TEAMS))))
    rows = []
    day = pd.Timestamp("2025-08-01 14:00", tz="UTC")
    gid = 0
    for _ in range(rounds):
        for h in TEAMS:
            for a in TEAMS:
                if h == a:
                    continue
                gid += 1
                lh = float(np.exp(0.15 + att[h] + dfn[a]) * 1.3)
                la = float(np.exp(att[a] + dfn[h]) * 1.1)
                rows.append({"game_id": str(gid), "home_team": h, "away_team": a, "lh": lh, "la": la,
                             "match_date": day + pd.Timedelta(days=(gid // 5) * 3.5)})
    df = pd.DataFrame(rows)
    sc = _dc_scores(rng, df.lh.to_numpy(), df.la.to_numpy(), rho)
    df["home_goals"], df["away_goals"] = sc[:, 0], sc[:, 1]
    df["weight"] = 1.0
    if xg:
        df["home_xg"], df["away_xg"] = df.lh.round(2), df.la.round(2)
    return df.drop(columns=["lh", "la"]).sort_values("match_date", kind="stable").reset_index(drop=True)


@pytest.fixture()
def prices(monkeypatch):
    """Closing-line rates for every second match, served by the production loader's seam."""
    df = _league()
    p = pd.DataFrame({"game_id": df.game_id[::2], "mkt_h": 1.2 + 0.1 * (df.index[::2] % 7),
                      "mkt_a": 0.9 + 0.05 * (df.index[::2] % 5)})
    monkeypatch.setattr(mr, "_league_prices", lambda slug: p)
    return df


def _tuner():
    import tune_league_models as t
    return t


def test_tuner_fold_frame_is_the_production_frame(prices):
    t = _tuner()
    df = prices
    ev = t.LeagueEvaluator(df, folds=4, min_train=120, slug=SLUG, market=True)
    assert ev.folds
    for i, (s, _) in enumerate(ev.folds):
        xi = 0.002
        got = ev.fit_frame(i, xi)
        want = mr.with_market_rows(df.iloc[:s], SLUG, xi_fit=xi, now=ev.as_of[i])
        pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True))
        extra = got[got.game_id.str.endswith(":mkt")]
        assert len(extra) > 0
        days = (ev.as_of[i] - extra.match_date).dt.total_seconds().to_numpy() / 86400
        # the fit weighs a row exp(-xi d): with the factor the market rows weigh W_MKT exp(-XI_MKT d)
        assert np.allclose(np.exp(-xi * days) * extra.weight.to_numpy(), mr.W_MKT * np.exp(-mr.XI_MKT * days))


def test_tuner_reads_the_live_market_constants(prices, monkeypatch):
    t = _tuner()
    ev = t.LeagueEvaluator(prices, folds=3, min_train=120, slug=SLUG, market=True)
    before = ev.fit_frame(0, 0.0035)
    monkeypatch.setattr(mr, "W_MKT", mr.W_MKT * 2)
    after = ev.fit_frame(0, 0.0035)
    m = before.game_id.str.endswith(":mkt")
    assert np.allclose(after.weight[m].to_numpy(), 2 * before.weight[m].to_numpy())
    plain = t.LeagueEvaluator(prices, folds=3, min_train=120, slug=SLUG, market=False).fit_frame(0, 0.0035)
    assert not plain.game_id.str.endswith(":mkt").any()


def test_tuner_folds_see_nothing_from_the_scored_day(prices):
    t = _tuner()
    df = prices
    for s, e, as_of in t._day_folds(df.match_date, folds=5, min_train=100):
        assert (df.match_date.iloc[:s] < as_of).all()
        assert (df.match_date.iloc[s:e] >= as_of).all()
        assert as_of == as_of.normalize()
    ev = t.LeagueEvaluator(df, folds=5, min_train=100, slug=SLUG)
    for (s, _), cal in zip(ev.folds, ev.cals):
        assert cal == t.empirical_calibration(df.iloc[:s])


def test_tuner_fit_is_the_build_fit(prices):
    t = _tuner()
    ev = t.LeagueEvaluator(prices, folds=3, min_train=150, slug=SLUG)
    dc = ev.dc_fits(0.0035, 1.0)[0]
    assert dc.analytic_grad and dc.fixed_rho == fitting.club_rho()
    ref = fitting.fit_dc(fitting.dc_frame(prices.iloc[:ev.folds[0][0]], SLUG, 0.0035, now=ev.as_of[0]), 0.0035, 1.0,
                         as_of=ev.as_of[0].to_pydatetime())
    assert dc.params_ == ref.params_


def test_build_fits_go_through_the_shared_module(monkeypatch):
    import build_site_all as b
    import build_site_liga as bl

    calls = []
    real_frame, real_part, real_new = fitting.dc_frame, fitting.pooled_part, fitting.new_dc
    monkeypatch.setattr(fitting, "dc_frame", lambda *a, **k: calls.append(("frame", a[1], a[2])) or real_frame(*a, **k))
    monkeypatch.setattr(fitting, "pooled_part", lambda *a, **k: calls.append(("part", a[1], a[2])) or real_part(*a, **k))
    monkeypatch.setattr(fitting, "new_dc", lambda *a, **k: calls.append(("new",) + a) or real_new(*a, **k))
    df = _league(rounds=2)
    cfg = b.LEAGUES[SLUG]
    params = {**b.DEFAULT_PARAMS, "xi": 0.004, "ridge": 0.7}
    model, _ = b.build_model(df, TEAMS, {}, cfg, params)
    assert ("new", 0.004, 0.7) in calls and ("frame", SLUG, 0.004) in calls
    assert model.dc.fixed_rho == fitting.club_rho() and model.dc.params_["rho"] == pytest.approx(fitting.club_rho())
    # the pooled frame: each league's share through pooled_part, with the pooled fit's xi
    src = inspect.getsource(b.pooled_training_frame) + inspect.getsource(b.fit_pooled)
    assert "fitting.pooled_part(" in src and "fitting.new_dc(" in src and "xi=float(params[\"xi\"])" in src
    # Argentina
    assert "fitting.new_dc(" in inspect.getsource(bl.build_model) and "fitting.dc_frame(" in inspect.getsource(bl.build_model)
    # no club Dixon-Coles built around the shared module in the build's league paths
    for fn in (b.build_model, b.fit_pooled, bl.build_model):
        assert "DixonColesModel(" not in inspect.getsource(fn)


def test_tuner_has_no_fit_of_its_own():
    t = _tuner()
    src = inspect.getsource(t)
    assert "DixonColesModel(" not in src and "with_market_rows(" not in src
    assert "fitting.fit_dc(" in src and "fitting.dc_frame(" in src and "fitting.pooled_part(" in src


def test_estimate_rho_recovers_rho():
    rng = np.random.default_rng(7)
    lh = rng.uniform(0.8, 2.0, 6000)
    la = rng.uniform(0.6, 1.6, 6000)
    sc = _dc_scores(rng, lh, la, -0.13)
    r = estimate_rho(sc[:, 0], sc[:, 1], lh, la, np.ones(len(lh)))
    assert abs(r - (-0.13)) < 0.05
    assert np.isnan(estimate_rho([3], [2], [1.0], [1.0], [1.0]))


def test_club_rho_comes_from_model_params():
    import json
    mp = json.loads(fitting.PARAMS_PATH.read_text(encoding="utf-8"))
    assert fitting.club_rho() == pytest.approx(mp["dixon_coles_rho"]["rho"])
    assert -0.3 < fitting.club_rho() < 0.0


def test_free_rho_is_unidentified_when_every_match_has_xg_and_fixed_rho_holds():
    df = _league(rounds=8, rho=-0.2)
    as_of = (df.match_date.max() + pd.Timedelta(days=1)).to_pydatetime()
    old = DixonColesModel(xi=0.0035, ridge=1.0, analytic_grad=True)
    old.fit(df, as_of=as_of)
    # the root cause: no goals rows, so rho never leaves the optimiser's starting value
    assert old.params_["rho"] == pytest.approx(-0.1)
    # two matches without xG are enough to push a free rho around (to a bound, at worst)
    few = df.copy()
    few.loc[few.index[:2], ["home_xg", "away_xg"]] = np.nan
    free = DixonColesModel(xi=0.0035, ridge=1.0, analytic_grad=True)
    free.fit(few, as_of=as_of)
    assert free.params_["rho"] != pytest.approx(-0.1)
    held = DixonColesModel(xi=0.0035, ridge=1.0, analytic_grad=True, fixed_rho=-0.04)
    held.fit(few, as_of=as_of)
    assert held.params_["rho"] == pytest.approx(-0.04)
    # with every match on xG, holding rho changes nothing else
    held_all = DixonColesModel(xi=0.0035, ridge=1.0, analytic_grad=True, fixed_rho=-0.04)
    held_all.fit(df, as_of=as_of)
    assert {k: round(v, 6) for k, v in held_all.params_.items() if k != "rho"} ==         {k: round(v, 6) for k, v in old.params_.items() if k != "rho"}
    # the numeric-gradient path honours it too
    num = DixonColesModel(xi=0.0035, ridge=1.0, fixed_rho=-0.04)
    num.fit(few, as_of=as_of)
    assert num.params_["rho"] == pytest.approx(-0.04)
