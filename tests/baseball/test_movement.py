"""Player movement (analytics/movement.py) and the shared engine (common/movement.py): labels from transactions,
walk-forward without look-ahead, the pass rule, target ranking."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from oddsmarkets.baseball.analytics import movement as BM
from oddsmarkets.common import movement as MV

MLB = {"1", "2", "3"}


def ev(d, kind, f=None, to=None):
    return {"date": d, "kind": kind, "from": f, "to": to}


def test_replay_trade_claim_release_and_free_agency():
    lo, hi = date(2024, 10, 20), date(2025, 3, 27)
    cur, first, _, joined = BM.replay([ev("2024-12-01", "trade", "1", "2")], "1", lo, hi, MLB)
    assert (cur, first, joined) == ("2", "trade", ["2"])
    cur, first, _, _ = BM.replay([ev("2024-11-04", "claim", "1", "3")], "1", lo, hi, MLB)
    assert (cur, first) == ("3", "release")
    # outrighted, then elected free agency: a release or waiver, not a free-agent departure
    cur, first, _, _ = BM.replay([ev("2024-11-01", "outright", "1", "999"), ev("2024-11-05", "free_agency", None, "1")], "1", lo, hi, MLB)
    assert (cur, first) == (None, "release")
    cur, first, _, _ = BM.replay([ev("2024-11-02", "free_agency", None, "1")], "1", lo, hi, MLB)
    assert (cur, first) == (None, "free_agency")
    # elected free agency and re-signed: back with the club by opening day
    cur, first, _, _ = BM.replay([ev("2024-11-02", "free_agency", None, "1"), ev("2025-01-10", "signing", None, "1")], "1", lo, hi, MLB)
    assert cur == "1" and first == "free_agency"
    # a move before the window or after it is ignored
    cur, first, _, _ = BM.replay([ev("2024-10-01", "trade", "1", "2"), ev("2025-04-10", "trade", "1", "3")], "1", lo, hi, MLB)
    assert (cur, first) == ("1", None)


def _synthetic(n_seasons=8, n=600, seed=0, signal=1.5):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(2010, 2010 + n_seasons):
        x = rng.normal(size=n)
        p = 1 / (1 + np.exp(-(-1.0 + signal * x)))
        y = (rng.random(n) < p).astype(float)
        for i in range(n):
            rows.append({"season": s, "tid": str(i % 30), "pid": f"{s}-{i}", "x": x[i], "y": y[i]})
    return pd.DataFrame(rows)


def test_walk_forward_uses_only_earlier_seasons():
    df = _synthetic()
    df.loc[df["season"] == 2017, "y"] = 1.0                 # a season whose labels would leak if it were in training
    r = MV.wf_binary(df, "y", ["x"], [], [2017], 1.0)
    assert abs(r["p0"].iloc[0] - df.loc[df["season"] < 2017, "y"].mean()) < 1e-12


def test_pass_rule_signal_and_noise():
    good = MV.evaluate_binary(_synthetic(), "y", ["x"], [], [2013, 2014], [2015, 2016, 2017])
    assert good["test_eval"]["passed"] and good["test_eval"]["ll_gain"][1] > 0
    noise = MV.evaluate_binary(_synthetic(signal=0.0, seed=3), "y", ["x"], [], [2013, 2014], [2015, 2016, 2017])
    assert not noise["test_eval"]["passed"]


def test_calibration_rule_catches_a_shifted_rate():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.05, 0.3, 4000)
    y = (rng.random(4000) < np.clip(p + 0.08, 0, 1)).astype(float)       # predictions 8 points too low
    m = MV.binary_metrics(y, p, np.full_like(p, y.mean()), [str(i % 40) for i in range(4000)], n_boot=200)
    assert not m["calibrated"] and not m["passed"]


def test_type_model_and_poisson_and_clogit():
    rng = np.random.default_rng(2)
    n = 3000
    x = rng.normal(size=(n, 1))
    Z = np.column_stack([np.zeros(n), 1.5 * x[:, 0], -1.5 * x[:, 0]])
    P = np.exp(Z) / np.exp(Z).sum(axis=1, keepdims=True)
    y = np.array([rng.choice(3, p=pp) for pp in P])
    B = MV.fit_mnl(x, y, 3, 0.1)
    assert B[1, 0] > 1.0 and B[1, 1] < -1.0
    lam = np.exp(0.2 + 0.7 * x[:, 0])
    b = MV.fit_poisson(x, rng.poisson(lam), 0.1)
    assert abs(b[1] - 0.7) < 0.1
    # conditional logit: the alternative with the larger feature is chosen more often
    Xs, ch = [], []
    for _ in range(800):
        X = rng.normal(size=(5, 1))
        u = 2.0 * X[:, 0] + rng.gumbel(size=5)
        Xs.append(X)
        ch.append(int(np.argmax(u)))
    bc = MV.fit_clogit(Xs, ch, 0.1)
    assert 1.5 < bc[0] < 2.5
    pr = MV.pred_clogit(bc, np.array([[1.0], [0.0], [-1.0]]))
    assert abs(pr.sum() - 1) < 1e-9 and pr[0] > pr[1] > pr[2]


def test_topk_eval_against_baselines():
    groups = []
    for g in range(40):
        pool = [f"c{i}" for i in range(50)]
        hits = {"c0", "c1"}
        groups.append({"key": str(g), "hits": hits, "pool": 50,
                       "rankings": {"model": pool, "need_value": list(reversed(pool))}})
    t = MV.topk_eval(groups, k=10, n_boot=200)
    assert t["model"]["precision"] == 0.2 and t["need_value"]["precision"] == 0.0
    assert t["need_value"]["model_minus_this"][1] > 0 and t["model_minus_chance"][0] > 0


def test_team_blocks_and_targets():
    rows = []
    for t, wp in (("1", 0.6), ("2", 0.4), ("3", 0.5)):
        for i, (pos, v) in enumerate((("SS", 3.0 if t == "2" else 0.5), ("C", 1.0), ("SP", 2.0), ("SP", 1.5), ("SP", 1.0), ("SP", 0.5),
                                      ("SP", 0.2))):
            rows.append({"season": 2026, "tid": t, "pid": f"{t}{i}", "pos": pos, "vnow": v, "age": 30.0, "team_wp": wp,
                         "team_turn": 0.3, "p_next": 0.4 if t == "2" else 0.2, "yrs": 6})
    df = pd.DataFrame(rows)
    tp = MV.team_pos_table(df, BM.SLOTS)
    sp = tp[(tp["tid"] == "1") & (tp["pos"] == "SP")].iloc[0]
    assert sp["incumbent"] == 0.2 and abs(sp["strength"] - 5.2) < 1e-9          # the 5th starter, the top five
    ranks = MV.rank_targets(df, tp, {"1": "AL", "2": "AL", "3": "NL"}, None)
    top = ranks["1"]["model"][0]
    assert top[0] == "20" and top[2] > 2.0                                          # the rebuilding club's shortstop
    assert all(r[2] > 0 for t in ranks for r in ranks[t]["model"])                 # only upgrades are candidates
    assert MV.status_of(BM.CFG, 0.6) == "contending" and MV.status_of(BM.CFG, 0.4) == "rebuilding"


def test_published_flags_follow_the_rule():
    ok = {"test_eval": {"passed": True}}
    bad = {"test_eval": {"passed": False, "ll_gain": [0.01, 0.005, 0.02], "mean_p": 0.1, "rate": 0.12, "cal_tol": 0.012, "cal_slope": 1.1}}
    res = {"next": ok, "deadline": bad, "type": ok, "arrivals": ok,
           "targets": {"test_eval": {"model": {"precision": 0.03}, "need_value": {"model_minus_this": [0.02, 0.01, 0.03]},
                                     "model_minus_chance": [0.02, 0.01, 0.03]}}}
    pub = MV.published(res)
    assert pub == {"next": True, "deadline": False, "type": True, "arrivals": True, "targets": True}
    assert "calibration rule" in MV.reason(bad["test_eval"])


def test_inseason_gap_leaves_out_the_unsettled_season():
    df = _synthetic()
    df.loc[df["season"] == 2016, "y"] = 1.0                 # the season before: unsettled at an in-season snapshot
    r = MV.wf_binary(df, "y", ["x"], [], [2017], 1.0, gap=1)
    assert abs(r["p0"].iloc[0] - df.loc[df["season"] < 2016, "y"].mean()) < 1e-12
    assert MV.gap_of(BM.CFG, "inseason") == 1 and MV.gap_of(BM.CFG, "offseason") == 0
