"""
Experiment harness: rows (edge/walk.py) + extra features -> walk-forward predictions per decision mode -> scores.

Split (stated once, used everywhere): coefficients are refitted walk-forward every week on earlier rows only; design
choices (feature sets, half-lives, shrinkage) are chosen on 2006-2016 outcomes and on the close-line fit there, and
reported on 2017-2026 (close decision) and 2023-2026 (open decision, the only seasons with ESPN openers).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.edge import evaluate as EV
from oddsmarkets.nfl.edge import fit as FT
from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.edge import prices as PR

TUNE = (2006, 2016)
TEST = (2017, 2026)


def predict(rows: pd.DataFrame, prices: pd.DataFrame, mfeats=FT.MFEATS, tfeats=FT.TFEATS, start: int = 2006) -> pd.DataFrame:
    P = FT.wf_predict(rows.copy(), mfeats, tfeats, start=start)
    at = dict(P.attrs)
    P = FT.probs(P)
    drop = [c for c in ("kickoff",) if c in P.columns]
    P = P.drop(columns=drop).merge(prices.drop(columns=["season", "week", "gtype", "home", "away"]), on="game_id", how="left")
    P.attrs = at
    return P


def _wk(d: pd.DataFrame) -> np.ndarray:
    return (d["season"].astype(str) + "_" + d["week"].astype(str)).to_numpy()


def close_metrics(P: pd.DataFrame) -> dict:
    """Close decision against the nflverse close: ML, ATS and totals log-loss (model - market, CI by week)."""
    out = {}
    d = P[P["played"].astype(bool) & (P["margin"] != 0)]
    fh, _ = PR.devig2(d["nfv_ml_h"], d["nfv_ml_a"])
    y = (d["margin"] > 0).astype(float).to_numpy()
    for nm, (lo, hi) in (("tune", TUNE), ("test", TEST)):
        k = np.isfinite(fh) & d["season"].between(lo, hi).to_numpy()
        r = EV.ll_diff_ci(d["p_home"].to_numpy()[k], fh[k], y[k], _wk(d)[k])
        out[f"ml_{nm}"] = {"n": r["n"], "model": EV.ll(d["p_home"].to_numpy()[k], y[k]), "market": EV.ll(fh[k], y[k]),
                           "diff": r["diff"], "lo": r["lo"], "hi": r["hi"]}
    # ATS at the nflverse close line
    pc, _ = FT.cover_probs(P.assign(_L=P["nfv_spread_home"]), "_L")
    adj = P["margin"].to_numpy(float) + P["nfv_spread_home"].to_numpy(float)
    msp, _ = PR.devig2(P["nfv_sp_h"], P["nfv_sp_a"])
    ok = P["played"].astype(bool).to_numpy() & np.isfinite(adj) & (np.abs(adj) > 1e-9) & np.isfinite(pc)
    mk = np.where(np.isfinite(msp), msp, 0.5)
    ya = (adj > 0).astype(float)
    for nm, (lo, hi) in (("tune", TUNE), ("test", TEST)):
        k = ok & P["season"].between(lo, hi).to_numpy()
        r = EV.ll_diff_ci(pc[k], mk[k], ya[k], _wk(P)[k])
        out[f"ats_{nm}"] = {"n": r["n"], "model": EV.ll(pc[k], ya[k]), "market": EV.ll(mk[k], ya[k]), "diff": r["diff"],
                            "lo": r["lo"], "hi": r["hi"]}
    po, _ = FT.over_probs(P.assign(_T=P["nfv_total"]), "_T")
    tt = P["total"].to_numpy(float) - P["nfv_total"].to_numpy(float)
    mov, _ = PR.devig2(P["nfv_ov"], P["nfv_un"])
    ok = P["played"].astype(bool).to_numpy() & np.isfinite(tt) & (np.abs(tt) > 1e-9) & np.isfinite(po)
    mk = np.where(np.isfinite(mov), mov, 0.5)
    yt = (tt > 0).astype(float)
    for nm, (lo, hi) in (("tune", TUNE), ("test", TEST)):
        k = ok & P["season"].between(lo, hi).to_numpy()
        r = EV.ll_diff_ci(po[k], mk[k], yt[k], _wk(P)[k])
        out[f"tot_{nm}"] = {"n": r["n"], "model": EV.ll(po[k], yt[k]), "market": EV.ll(mk[k], yt[k]), "diff": r["diff"],
                            "lo": r["lo"], "hi": r["hi"]}
    for nm, (lo, hi) in (("tune", TUNE), ("test", TEST)):
        k = P["season"].between(lo, hi) & P["nfv_spread_home"].notna() & P["played"].astype(bool)
        out[f"rmse_{nm}"] = {"margin_model": float(np.sqrt(np.mean((P["mu"][k] - P["margin"][k]) ** 2))),
                             "margin_close": float(np.sqrt(np.mean((-P["nfv_spread_home"][k] - P["margin"][k]) ** 2))),
                             "model_v_close_line": float(np.sqrt(np.mean((P["mu"][k] + P["nfv_spread_home"][k]) ** 2))),
                             "total_model_v_close": float(np.sqrt(np.nanmean((P["mu_t"][k] - P["nfv_total"][k]) ** 2)))}
    return out


def open_metrics(P: pd.DataFrame, lm: MK.LineMap, decision: str, thresholds=(0.0, 0.02)) -> dict:
    """CLV of bets at the ESPN opener (2023 ->), and how well model - open predicts the move to the close."""
    sub = P[P["eo_spread_home"].notna() | P["eo_total"].notna() | P["eo_ml_h"].notna()]
    S = EV.selections(sub, "eo", "ec", lm, "espn_open", decision)
    out = {"n_games": int(len(sub))}
    for thr in thresholds:
        B = EV.bet_table(S, thr)
        out[f"bets_{thr}"] = EV.summarise_bets(B).round(5).to_dict("records")
    o = sub[sub["eo_spread_home"].notna() & sub["ec_spread_home"].notna()]
    mv = -(o["ec_spread_home"] - o["eo_spread_home"]).to_numpy(float)
    x = (o["mu"] + o["eo_spread_home"]).to_numpy(float)
    t = sub[sub["eo_total"].notna() & sub["ec_total"].notna()]
    mvt = (t["ec_total"] - t["eo_total"]).to_numpy(float)
    xt = (t["mu_t"] - t["eo_total"]).to_numpy(float)
    out["move_spread"] = {"n": int(len(o)), "slope": float(np.polyfit(x, mv, 1)[0]) if len(o) > 5 else None,
                          "corr": float(np.corrcoef(x, mv)[0, 1]) if len(o) > 5 else None}
    out["move_total"] = {"n": int(len(t)), "slope": float(np.polyfit(xt, mvt, 1)[0]) if len(t) > 5 else None,
                         "corr": float(np.corrcoef(xt, mvt)[0, 1]) if len(t) > 5 else None}
    # fair-probability edge vs fair CLV over all selections (does the model's edge point the way the line moves?)
    s = S[S["fair_p_close"].notna() & S["fair_p_decision"].notna()]
    e = s["model_p"] - s["fair_p_decision"]
    m = s["fair_p_close"] - s["fair_p_decision"]
    out["edge_vs_move"] = {mk: {"n": int((s["market"] == mk).sum()),
                                "slope": float(np.polyfit(e[s["market"] == mk], m[s["market"] == mk], 1)[0]),
                                "corr": float(np.corrcoef(e[s["market"] == mk], m[s["market"] == mk])[0, 1])}
                           for mk in ("moneyline", "spread", "total") if (s["market"] == mk).sum() > 10}
    return out


def headline(res: dict) -> dict:
    """A compact line for the experiment log."""
    c = res.get("close", {})
    h = {k: round(c[k]["diff"], 5) for k in ("ml_tune", "ml_test", "ats_test", "tot_test") if k in c}
    h["ml_test_model"] = round(c.get("ml_test", {}).get("model", np.nan), 5)
    for mode in ("openA", "openB"):
        o = res.get(mode) or {}
        for r in o.get("bets_0.0", []):
            h[f"{mode}_{r['market']}_clv"] = round(r["clv"], 4)
            h[f"{mode}_{r['market']}_fairclv"] = round(r["fair_clv"], 4)
    return h


def predict_kw(rows: pd.DataFrame, prices: pd.DataFrame, mfeats=FT.MFEATS, tfeats=FT.TFEATS, start: int = 2006,
               **kw) -> pd.DataFrame:
    """predict() with fit.wf_predict keyword options (key-number toggles, ridge penalty)."""
    P = FT.wf_predict(rows.copy(), mfeats, tfeats, start=start, **kw)
    at = dict(P.attrs)
    P = FT.probs(P)
    drop = [c for c in ("kickoff",) if c in P.columns]
    P = P.drop(columns=drop).merge(prices.drop(columns=["season", "week", "gtype", "home", "away"]), on="game_id", how="left")
    P.attrs = at
    return P
