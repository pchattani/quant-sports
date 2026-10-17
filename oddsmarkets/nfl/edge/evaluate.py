"""
Scoring against outcomes and against later prices (CLV), with bootstrap confidence intervals.

Selections: moneyline home/away, spread home/away at the decision's line, total over/under at the decision's line.
For each the table carries model_p (conditional on no push for spreads / totals), the decision price (decimal),
fair_p_decision (multiplicative de-vig of the two sides at the decision), fair_p_close (the close's de-vigged
probability of the same selection AT THE DECISION'S LINE, through market.LineMap) and the outcome (1, 0, 0.5 push).

CLV of a bet = fair_p_close * price_dec - 1 (expected return per unit if the close is the truth);
"fair CLV" = fair_p_close - fair_p_decision (the line move in probability, vig-free).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.edge import fit as FT
from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.edge import prices as PR

EPS = 1e-4


def ll(p, y) -> float:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def boot_ci(x: np.ndarray, groups: np.ndarray | None = None, n: int = 2000, seed: int = 0, stat=np.mean) -> tuple:
    """Percentile 95% CI of stat(x), resampling `groups` (e.g. weeks) when given, else rows."""
    x = np.asarray(x, float)
    if len(x) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    if groups is None:
        idx = rng.integers(0, len(x), (n, len(x)))
        vals = np.array([stat(x[i]) for i in idx])
    else:
        g = pd.Series(np.arange(len(x))).groupby(np.asarray(groups)).apply(list).tolist()
        vals = []
        for _ in range(n):
            pick = rng.integers(0, len(g), len(g))
            ii = np.concatenate([g[k] for k in pick])
            vals.append(stat(x[ii]))
        vals = np.array(vals)
    return (float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5)))


def ll_diff_ci(p_a, p_b, y, groups=None, n=2000, seed=0) -> dict:
    """Mean log-loss difference a - b with a bootstrap CI (paired)."""
    pa, pb = np.clip(np.asarray(p_a, float), EPS, 1 - EPS), np.clip(np.asarray(p_b, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    d = -(y * np.log(pa) + (1 - y) * np.log(1 - pa)) + (y * np.log(pb) + (1 - y) * np.log(1 - pb))
    lo, hi = boot_ci(d, groups, n, seed)
    return {"n": int(len(d)), "diff": float(d.mean()), "lo": lo, "hi": hi}


def selections(P: pd.DataFrame, pre_dec: str, pre_close: str, lm: MK.LineMap, src: str, decision: str) -> pd.DataFrame:
    """Per-selection rows for one decision: prices with prefix `pre_dec` (e.g. 'eo', 'nfv', 'ec'), closing prices with
    `pre_close`. P carries model columns from fit.wf_predict (mu, sigma, mu_t, sigma_t, p_home) and outcomes."""
    out = []
    y_home = np.where(P["margin"] > 0, 1.0, np.where(P["margin"] < 0, 0.0, 0.5))
    base = {"event_id": P["game_id"].to_numpy(), "season": P["season"].to_numpy(), "week": P["week"].to_numpy(),
            "start_time": P["kickoff"].to_numpy(), "gtype": P["gtype"].to_numpy()}
    # moneyline
    dh, da = P[f"{pre_dec}_ml_h"].to_numpy(float), P[f"{pre_dec}_ml_a"].to_numpy(float)
    fh, fa = PR.devig2(dh, da)
    ch, ca = PR.devig2(P[f"{pre_close}_ml_h"].to_numpy(float), P[f"{pre_close}_ml_a"].to_numpy(float))
    ph = P["p_home"].to_numpy(float)
    for sel, mp, d, f, c, y in (("home", ph, dh, fh, ch, y_home), ("away", 1 - ph, da, fa, ca, 1 - y_home)):
        out.append(pd.DataFrame({**base, "market": "moneyline", "selection": sel, "line": np.nan, "model_p": mp, "p_push": 0.0,
                                 "price_dec": d, "fair_p_decision": f, "fair_p_close": c, "outcome": y}))
    # spread (home handicap at the decision line)
    L = P[f"{pre_dec}_spread_home"].to_numpy(float)
    pc, pp = FT.cover_probs(P.assign(_L=L), "_L")
    dsh, dsa = P[f"{pre_dec}_sp_h"].to_numpy(float), P[f"{pre_dec}_sp_a"].to_numpy(float)
    fsh, _ = PR.devig2(dsh, dsa)
    Lc = P[f"{pre_close}_spread_home"].to_numpy(float)
    csh, _ = PR.devig2(P[f"{pre_close}_sp_h"].to_numpy(float), P[f"{pre_close}_sp_a"].to_numpy(float))
    same = np.isfinite(L) & np.isfinite(Lc) & (np.abs(L - Lc) < 1e-9)
    c_at = np.where(same, csh, np.nan)
    move = ~same & np.isfinite(L) & np.isfinite(Lc) & np.isfinite(csh)
    if move.any():
        c_at[move] = lm.spread_at(Lc[move], csh[move], L[move])[0]
    adj = P["margin"].to_numpy(float) + L
    y_sp = np.where(adj > 0, 1.0, np.where(adj < 0, 0.0, 0.5))
    for sel, mp, d, f, c, y in (("home", pc, dsh, fsh, c_at, y_sp), ("away", 1 - pc, dsa, 1 - fsh, 1 - c_at, 1 - y_sp)):
        out.append(pd.DataFrame({**base, "market": "spread", "selection": sel, "line": L if sel == "home" else -L,
                                 "model_p": mp, "p_push": pp, "price_dec": d, "fair_p_decision": f, "fair_p_close": c,
                                 "outcome": np.where(np.isfinite(adj), y, np.nan)}))
    # totals
    T = P[f"{pre_dec}_total"].to_numpy(float)
    po, ppt = FT.over_probs(P.assign(_T=T), "_T")
    dov, dun = P[f"{pre_dec}_ov"].to_numpy(float), P[f"{pre_dec}_un"].to_numpy(float)
    fov, _ = PR.devig2(dov, dun)
    Tc = P[f"{pre_close}_total"].to_numpy(float)
    cov, _ = PR.devig2(P[f"{pre_close}_ov"].to_numpy(float), P[f"{pre_close}_un"].to_numpy(float))
    same = np.isfinite(T) & np.isfinite(Tc) & (np.abs(T - Tc) < 1e-9)
    c_at = np.where(same, cov, np.nan)
    move = ~same & np.isfinite(T) & np.isfinite(Tc) & np.isfinite(cov)
    if move.any():
        c_at[move] = lm.total_at(Tc[move], cov[move], T[move])[0]
    tt = P["total"].to_numpy(float) - T
    y_t = np.where(tt > 0, 1.0, np.where(tt < 0, 0.0, 0.5))
    for sel, mp, d, f, c, y in (("over", po, dov, fov, c_at, y_t), ("under", 1 - po, dun, 1 - fov, 1 - c_at, 1 - y_t)):
        out.append(pd.DataFrame({**base, "market": "total", "selection": sel, "line": T, "model_p": mp, "p_push": ppt,
                                 "price_dec": d, "fair_p_decision": f, "fair_p_close": c,
                                 "outcome": np.where(np.isfinite(tt), y, np.nan)}))
    S = pd.concat(out, ignore_index=True)
    S["price_src"] = src
    S["decision"] = decision
    S["price_close"] = np.nan
    return S[np.isfinite(S["price_dec"]) & np.isfinite(S["model_p"])].reset_index(drop=True)


def bet_table(S: pd.DataFrame, min_edge: float = 0.0, edge_on: str = "price") -> pd.DataFrame:
    """One bet per (event, market): the selection with the larger model EV, kept when EV > min_edge.
    EV = model_p * price - 1 ('price') or model_p - fair_p_decision ('fair')."""
    S = S.copy()
    S["ev"] = S["model_p"] * S["price_dec"] - 1 if edge_on == "price" else S["model_p"] - S["fair_p_decision"]
    S = S.sort_values("ev", ascending=False).drop_duplicates(["event_id", "market"])
    B = S[S["ev"] > min_edge].copy()
    B["clv"] = B["fair_p_close"] * B["price_dec"] - 1
    B["fair_clv"] = B["fair_p_close"] - B["fair_p_decision"]
    B["ret"] = np.where(B["outcome"] == 0.5, 0.0, B["outcome"] * B["price_dec"] - 1)
    return B


def summarise_bets(B: pd.DataFrame, by=("market",)) -> pd.DataFrame:
    rows = []
    B = B[B["outcome"].notna()]
    for k, g in B.groupby(list(by)):
        wk = (g["season"].astype(str) + "_" + g["week"].astype(str)).to_numpy()
        c = g["clv"].dropna()
        rows.append({**dict(zip(by, k if isinstance(k, tuple) else (k,))), "n": len(g),
                     "clv": c.mean(), "clv_lo": boot_ci(c.to_numpy(), wk[g["clv"].notna().to_numpy()])[0],
                     "clv_hi": boot_ci(c.to_numpy(), wk[g["clv"].notna().to_numpy()])[1],
                     "fair_clv": g["fair_clv"].mean(), "beat_close": float((g["fair_clv"] > 0).mean()),
                     "roi": g["ret"].mean(), "roi_lo": boot_ci(g["ret"].to_numpy(), wk)[0],
                     "roi_hi": boot_ci(g["ret"].to_numpy(), wk)[1]})
    return pd.DataFrame(rows)
