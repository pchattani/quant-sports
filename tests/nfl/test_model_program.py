"""Model-improvement program (21 Oct 2026): total key numbers, market-line calibration, starters out, comparisons."""
import numpy as np
import pandas as pd

from oddsmarkets.nfl.edge import compare as CP
from oddsmarkets.nfl.edge import starters as SO
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import backtest as BT


def test_total_pmf_without_keys_is_the_old_normal():
    d = GM.total_prob(44.3, 13.4, 44.5)
    assert abs(d["over"] + d["under"] + d["push"] - 1) < 1e-12 and d["push"] == 0.0
    assert 0.45 < d["over"] < 0.55


def test_total_keys_recover_a_lumpy_distribution():
    rng = np.random.default_rng(0)
    mu = rng.normal(44, 3, 20000)
    y = np.rint(mu + rng.normal(0, 13, len(mu)))
    y[rng.random(len(y)) < 0.05] = 41.0                       # a key number
    tk = GM.fit_total_keys(mu, y, 13.0)
    assert tk[41] > 1.5 and abs(tk[60] - 1) < 0.35
    p_key = GM.total_prob(44.0, 13.0, 41.0, tk)["push"]
    assert p_key > GM.total_prob(44.0, 13.0, 41.0)["push"] * 1.5


def test_market_cover_calibration_shrinks_toward_half():
    p = {"cal_ats": [0.0, 0.2], "keys": None}
    raw = GM.cover_prob(5.0, 13.0, -1.5)
    cal = GM.market_cover(5.0, 13.0, -1.5, p=p)
    rc, cc = raw["home"] / (1 - raw["push"]), cal["home"] / (1 - cal["push"])
    assert 0.5 < cc < rc
    assert abs(cal["home"] + cal["away"] + cal["push"] - 1) < 1e-12
    assert GM.market_cover(5.0, 13.0, -1.5, p={"cal_ats": None}) == GM.cover_prob(5.0, 13.0, -1.5)


def test_market_over_uses_total_keys_and_calibration():
    tk = np.ones(len(GM.TOT_SUPPORT))
    tk[44] = 2.0
    d = GM.market_over(47.0, 13.0, 44.0, p={"tkeys": tk.tolist(), "cal_tot": [0.0, 0.3]})
    raw = GM.total_prob(47.0, 13.0, 44.0, tk)
    assert abs(d["push"] - raw["push"]) < 1e-12
    assert 0.5 < d["over"] / (1 - d["push"]) < raw["over"] / (1 - raw["push"])


def test_backtest_market_calibration_is_walk_forward():
    rng = np.random.default_rng(1)
    rows = []
    for s in range(2006, 2012):
        p = rng.uniform(0.3, 0.7, 400)
        y = (rng.random(400) < 0.5).astype(float)            # the raw p carries no information
        rows += [(a, b, s) for a, b in zip(p, y)]
    cal, ab = BT.market_calibration(rows)
    a = np.array(cal)
    assert np.allclose(a[a[:, 2] < 2008, 0], np.array(rows)[np.array(rows)[:, 2] < 2008, 0])   # < 500 earlier rows: raw
    late = a[a[:, 2] >= 2009, 0]
    assert np.abs(late - 0.5).mean() < 0.05                  # shrunk to ~0.5
    assert abs(ab[1]) < 0.5


def test_wf_platt_uses_only_earlier_seasons():
    rng = np.random.default_rng(2)
    n = 3000
    sea = np.repeat(np.arange(2006, 2012), n // 6)
    p = rng.uniform(0.2, 0.8, n)
    y = (rng.random(n) < p).astype(float)
    q, co = CP.wf_platt(p, y, sea, first_apply=2008)
    assert set(co) == set(range(2008, 2012))
    assert np.allclose(q[sea < 2008], p[sea < 2008])
    assert all(abs(b - 1) < 0.3 for _, b in co.values())


def test_paired_ci_brackets_the_mean():
    rng = np.random.default_rng(3)
    y = (rng.random(2000) < 0.5).astype(float)
    pa = np.clip(0.5 + 0.1 * (y - 0.5) + rng.normal(0, 0.05, 2000), 0.01, 0.99)
    r = CP.paired(pa, np.full(2000, 0.5), y, np.repeat(np.arange(100), 20))
    assert r["ll_lo"] <= r["ll_diff"] <= r["ll_hi"] and r["ll_diff"] < 0


def test_starters_attach_home_minus_away_and_open_rows_zero():
    L = pd.DataFrame({"season": [2015, 2015], "week": [3, 3], "team": ["NE", "NYJ"],
                      "out_ol": [1.0, 0.0], "out_rec": [0.0, 0.0], "out_rb": [0.0, 0.0],
                      "out_dl": [0.0, 0.85], "out_lb": [0.0, 0.0], "out_db": [0.0, 0.0]})
    R = pd.DataFrame({"game_id": ["g", "g"], "season": [2015, 2015], "week": [3, 3], "home": ["NE", "NE"],
                      "away": ["NYJ", "NYJ"], "mode": ["close", "openA"]})
    out = SO.attach(R, L)
    assert out.loc[0, "f_so_off"] == 1.0 and abs(out.loc[0, "f_so_def"] + 0.85) < 1e-12
    assert out.loc[1, "f_so_off"] == 0.0 and out.loc[1, "f_so_def"] == 0.0


def test_team_alias_by_season():
    assert SO.team_alias("OAK", 2019) == "OAK" and SO.team_alias("OAK", 2021) == "LV"
    assert SO.team_alias("LAR", 2020) == "LA" and SO.team_alias("SD", 2016) == "SD"
