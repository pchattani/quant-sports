"""Offline tests of the football edge research code (no network)."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from oddsmarkets.football.research import evaluate as ev
from oddsmarkets.football.research import fastdc
from oddsmarkets.football.research import walkforward as wf
from oddsmarkets.sports.world_cup.models.dixon_coles import DixonColesModel


def _league(n_teams=8, rounds=4, seed=3):
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(n_teams)]
    att = rng.normal(0, 0.3, n_teams)
    dfn = rng.normal(0, 0.3, n_teams)
    rows = []
    day = pd.Timestamp("2024-08-10 15:00", tz="UTC")
    for r in range(rounds):
        for i in range(n_teams):
            for j in range(n_teams):
                if i == j:
                    continue
                lh = np.exp(0.2 + att[i] + dfn[j])
                la = np.exp(att[j] + dfn[i])
                rows.append({"home": teams[i], "away": teams[j], "hg": rng.poisson(lh), "ag": rng.poisson(la),
                             "start_time": day})
                day += pd.Timedelta(hours=20)
    return pd.DataFrame(rows)


def test_fastdc_matches_production_optimum():
    L = _league()
    asof = L.start_time.max() + pd.Timedelta(days=1)
    m = DixonColesModel(xi=0.0035, ridge=1.0)
    m.fit(L.rename(columns={"home": "home_team", "away": "away_team", "hg": "home_goals", "ag": "away_goals",
                            "start_time": "match_date"}), as_of=asof.to_pydatetime())
    idx = {t: i for i, t in enumerate(m.teams_)}
    n = len(idx)
    w = np.exp(-0.0035 * ((asof - L.start_time).dt.total_seconds() / 86400).to_numpy())
    x = fastdc.fit(fastdc.FitData(hi=L.home.map(idx).to_numpy(), ai=L.away.map(idx).to_numpy(),
                                  hg=L.hg.to_numpy(float), ag=L.ag.to_numpy(float), wg=w), n, 1.0)
    att = np.array([m.params_[f"attack_{t}"] for t in m.teams_])
    assert np.abs(att - x[:n]).max() < 5e-3
    assert abs(m.params_["home_adv"] - x[2 * n]) < 5e-3


def test_fastdc_gradient():
    L = _league(rounds=2)
    idx = {t: i for i, t in enumerate(sorted(set(L.home)))}
    n = len(idx)
    d = fastdc.FitData(hi=L.home.map(idx).to_numpy(), ai=L.away.map(idx).to_numpy(), hg=L.hg.to_numpy(float),
                       ag=L.ag.to_numpy(float), wg=np.ones(len(L)), rh=L.hg.to_numpy(float) * 0.9 + 0.1,
                       ra=L.ag.to_numpy(float) * 0.9 + 0.1, wr=np.full(len(L), 0.5))
    x = fastdc.fit(d, n, 1.0)  # converges without error, rho inside its bounds
    assert -0.99 <= x[-1] <= 0.0
    M = fastdc.score_matrix(np.array([1.4]), np.array([1.1]), x[-1])
    p = fastdc.outcome_probs(M)
    assert abs(p.sum() - 1) < 1e-9


def test_snapshot_time_rules():
    k = pd.Series(pd.to_datetime(["2025-03-08 15:00", "2025-03-10 20:00", "2025-03-12 19:45", "2025-03-07 11:00"], utc=True))
    s = wf.snapshot_time(k)
    assert str(s[0]) == "2025-03-07 12:00:00+00:00"   # Saturday -> Friday noon
    assert str(s[1]) == "2025-03-07 12:00:00+00:00"   # Monday -> Friday noon
    assert str(s[2]) == "2025-03-11 12:00:00+00:00"   # Wednesday -> Tuesday noon
    assert s[3] < k[3]                                 # never after kickoff


def test_ah_outcomes_quarter_lines():
    gd = np.array([1, 0, 0, -1])
    w, p = ev._ah_outcome(gd, np.array([-0.75, -0.25, 0.0, 0.25]), True)
    # -0.75 with a 1-goal win: half won (-0.5), half pushed (-1)
    assert w[0] == 0.5 and p[0] == 0.5
    # -0.25 with a draw: half lost, half pushed
    assert w[1] == 0.0 and p[1] == 0.5
    assert w[2] == 0.0 and p[2] == 1.0
    assert w[3] == 0.0 and p[3] == 0.0


def test_implied_rates_roundtrip():
    M = fastdc.score_matrix(np.array([1.6]), np.array([0.9]), -0.05, max_goals=12)
    p = fastdc.outcome_probs(M)
    po = fastdc.over_prob(M)
    lh, la = wf.implied_rates(p, po)
    assert abs(lh[0] - 1.6) < 0.05 and abs(la[0] - 0.9) < 0.05


def test_boot_ci_groups():
    x = np.array([1.0, 1.0, -1.0, -1.0])
    m, lo, hi = ev.boot_ci(x, np.array([1, 1, 2, 2]), n=200)
    assert m == 0.0 and lo <= 0 <= hi


def test_analytic_gradient_matches_numeric_fit():
    L = _league(rounds=3).rename(columns={"home": "home_team", "away": "away_team", "hg": "home_goals",
                                          "ag": "away_goals", "start_time": "match_date"})
    L["weight"] = 1.0
    L.loc[::4, "home_xg"] = 1.3
    L.loc[::4, "away_xg"] = 0.9
    asof = (L.match_date.max() + pd.Timedelta(days=1)).to_pydatetime()
    a = DixonColesModel(xi=0.0035, ridge=1.0)
    a.fit(L, as_of=asof)
    b = DixonColesModel(xi=0.0035, ridge=1.0, analytic_grad=True)
    b.fit(L, as_of=asof)
    assert max(abs(a.params_[k] - b.params_[k]) for k in a.params_) < 2e-3


def test_market_rows_only_for_matched_games(monkeypatch):
    from oddsmarkets.football.sources import market_rates as mr

    train = pd.DataFrame({"game_id": ["1", "2", "3"], "home_team": ["A", "B", "C"], "away_team": ["B", "C", "A"],
                          "home_goals": [1, 0, 2], "away_goals": [0, 0, 1], "weight": 1.0,
                          "match_date": pd.to_datetime(["2025-01-01", "2025-01-08", "2025-01-15"], utc=True)})
    prices = pd.DataFrame({"game_id": ["2", "3"], "mkt_h": [1.4, 1.9], "mkt_a": [1.1, 0.8]})
    monkeypatch.setattr(mr, "_league_prices", lambda slug: prices)
    out = mr.with_market_rows(train, "premier-league")
    assert len(out) == 5
    extra = out[out.game_id.str.endswith(":mkt")]
    assert sorted(extra.home_xg) == [1.4, 1.9] and (extra.weight == mr.W_MKT).all()
    assert out[~out.game_id.str.endswith(":mkt")].home_xg.isna().all()
    # unknown league or no prices: the frame comes back unchanged
    assert mr.with_market_rows(train, "saudi-pro-league") is train
    monkeypatch.setattr(mr, "_league_prices", lambda slug: pd.DataFrame())
    assert mr.with_market_rows(train, "premier-league") is train


def test_closing_probs_fallback_order():
    from oddsmarkets.football.sources import market_rates as mr

    nan = np.nan
    df = pd.DataFrame({
        "psc_h": [2.0, nan], "psc_d": [3.5, nan], "psc_a": [4.0, nan],
        "bfec_h": [nan, 1.5], "bfec_d": [nan, 4.5], "bfec_a": [nan, 7.0],
        "avgc_h": [2.1, 1.45], "avgc_d": [3.3, 4.2], "avgc_a": [3.8, 6.5],
        "pc_o25": [nan, nan], "pc_u25": [nan, nan], "bfec_o25": [nan, 1.8], "bfec_u25": [nan, 2.2],
        "avgc_o25": [1.9, 1.75], "avgc_u25": [1.9, 2.05], "maxc_o25": [2.0, 1.9], "maxc_u25": [2.0, 2.1],
    })
    p1, po = mr.closing_probs(df)
    assert abs(p1[0, 0] - (1 / 2.0) / (1 / 2.0 + 1 / 3.5 + 1 / 4.0)) < 1e-12   # Pinnacle first
    assert abs(p1[1, 0] - (1 / 1.5) / (1 / 1.5 + 1 / 4.5 + 1 / 7.0)) < 1e-12   # then Betfair
    assert abs(po[0] - 0.5) < 1e-12 and abs(po[1] - (1 / 1.8) / (1 / 1.8 + 1 / 2.2)) < 1e-12
