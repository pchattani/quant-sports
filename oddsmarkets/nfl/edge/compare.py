"""
Paired comparisons of forecasters on the same games (model-improvement program, Oct 2026).

Every comparison is per game and market (moneyline: P(home wins), ties left out; ATS: P(home covers the given line),
pushes left out; totals: P(over the given line), pushes left out), on the games where every forecaster has a value.
Differences are a - b (negative = a better) with a 95% bootstrap CI resampling season-weeks (block bootstrap,
2,000 resamples), for log-loss and Brier. Calibration: logistic regression of the outcome on logit(p) ->
intercept and slope (1 and 0 = calibrated), with standard errors.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-4


def _ll_vec(p, y):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _block_ci(d: np.ndarray, groups: np.ndarray, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    """Percentile CI of the mean of d, resampling whole groups (weeks)."""
    codes, uniq = pd.factorize(pd.Series(groups))
    sums = np.bincount(codes, weights=d, minlength=len(uniq))
    cnts = np.bincount(codes, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(uniq), (n, len(uniq)))
    vals = sums[pick].sum(1) / np.maximum(cnts[pick].sum(1), 1)
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def calibration(p, y) -> dict:
    """Logistic recalibration fit y ~ a + b logit(p): intercept a, slope b (1 = calibrated), their se."""
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    x = np.log(p / (1 - p))
    a, b = 0.0, 1.0
    for _ in range(50):
        z = a + b * x
        q = 1 / (1 + np.exp(-z))
        w = q * (1 - q)
        g = np.array([np.sum(y - q), np.sum((y - q) * x)])
        H = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]]) + np.eye(2) * 1e-9
        st = np.linalg.solve(H, g)
        a, b = a + st[0], b + st[1]
        if np.abs(st).max() < 1e-10:
            break
    cov = np.linalg.inv(H)
    # expected calibration error, 10 equal-width bins
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = float(sum(abs(p[bins == k].mean() - y[bins == k].mean()) * (bins == k).mean() for k in range(10) if (bins == k).any()))
    return {"intercept": float(a), "slope": float(b), "se_intercept": float(np.sqrt(cov[0, 0])),
            "se_slope": float(np.sqrt(cov[1, 1])), "ece": ece}


def paired(pa, pb, y, groups, n_boot: int = 2000) -> dict:
    """Log-loss and Brier of a and b, and a - b with block-bootstrap CIs."""
    pa, pb, y = (np.asarray(v, float) for v in (pa, pb, y))
    la, lb = _ll_vec(pa, y), _ll_vec(pb, y)
    ba, bb = (pa - y) ** 2, (pb - y) ** 2
    out = {"n": int(len(y)), "ll_a": float(la.mean()), "ll_b": float(lb.mean()), "brier_a": float(ba.mean()),
           "brier_b": float(bb.mean())}
    d = la - lb
    out["ll_diff"] = float(d.mean())
    out["ll_lo"], out["ll_hi"] = _block_ci(d, groups, n_boot)
    d = ba - bb
    out["brier_diff"] = float(d.mean())
    out["brier_lo"], out["brier_hi"] = _block_ci(d, groups, n_boot, seed=1)
    return out


def fmt_row(r: dict, scale: int = 4) -> str:
    f = lambda x: f"{x:+.{scale}f}"  # noqa: E731
    return (f"n {r['n']}, LL {r['ll_a']:.4f} v {r['ll_b']:.4f}, diff {f(r['ll_diff'])} [{f(r['ll_lo'])}, {f(r['ll_hi'])}]; "
            f"Brier {r['brier_a']:.4f} v {r['brier_b']:.4f}, diff {f(r['brier_diff'])} [{f(r['brier_lo'])}, {f(r['brier_hi'])}]")


def game_probs(P: pd.DataFrame, pre: str = "nfv") -> pd.DataFrame:
    """Per game: the model's P(home), P(home covers) and P(over) at the `pre` market's lines (nfv = nflverse close,
    eo = ESPN opener, ec = ESPN close), the market's de-vigged probabilities of the same, and the outcomes
    (NaN for ties / pushes). P: fit.wf_predict output with prices merged (experiments.predict_kw)."""
    from oddsmarkets.nfl.edge import fit as FT
    from oddsmarkets.nfl.edge import prices as PR
    out = pd.DataFrame({"game_id": P["game_id"].to_numpy(), "season": P["season"].to_numpy(), "week": P["week"].to_numpy(),
                        "gtype": P["gtype"].to_numpy()})
    played = P["played"].astype(bool).to_numpy()
    m = P["margin"].to_numpy(float)
    out["p_ml"] = P["p_home"].to_numpy(float)
    out["mk_ml"], _ = PR.devig2(P[f"{pre}_ml_h"], P[f"{pre}_ml_a"])
    out["y_ml"] = np.where(played & (m != 0) & np.isfinite(m), (m > 0).astype(float), np.nan)
    L = P[f"{pre}_spread_home"].to_numpy(float)
    pc, _ = FT.cover_probs(P.assign(_L=L), "_L")
    out["p_ats"] = pc
    out["mk_ats"], _ = PR.devig2(P[f"{pre}_sp_h"], P[f"{pre}_sp_a"])
    adj = m + L
    out["y_ats"] = np.where(played & np.isfinite(adj) & (np.abs(adj) > 1e-9), (adj > 0).astype(float), np.nan)
    T = P[f"{pre}_total"].to_numpy(float)
    po, _ = FT.over_probs(P.assign(_T=T), "_T")
    out["p_tot"] = po
    out["mk_tot"], _ = PR.devig2(P[f"{pre}_ov"], P[f"{pre}_un"])
    tt = P["total"].to_numpy(float) - T
    out["y_tot"] = np.where(played & np.isfinite(tt) & (np.abs(tt) > 1e-9), (tt > 0).astype(float), np.nan)
    out["mu"], out["mu_t"], out["line"], out["total_line"] = P["mu"].to_numpy(float), P["mu_t"].to_numpy(float), -L, T
    return out


def wf_platt(p, y, seasons, first_apply: int = 2009, min_rows: int = 500) -> tuple[np.ndarray, dict]:
    """Walk-forward Platt recalibration: for each season s >= first_apply, logit p' = a + b logit p with (a, b) fitted
    on every earlier season's (p, y) (y NaN rows skipped). Earlier seasons keep p. Returns (p', {season: (a, b)})."""
    p, y, seasons = (np.asarray(v, float) for v in (p, y, seasons))
    out = p.copy()
    coefs = {}
    for s in sorted(set(seasons[np.isfinite(p)].astype(int))):
        if s < first_apply:
            continue
        tr = (seasons < s) & np.isfinite(p) & np.isfinite(y)
        if tr.sum() < min_rows:
            continue
        c = calibration(p[tr], y[tr])
        a, b = c["intercept"], c["slope"]
        te = (seasons == s) & np.isfinite(p)
        q = np.clip(p[te], EPS, 1 - EPS)
        out[te] = 1 / (1 + np.exp(-(a + b * np.log(q / (1 - q)))))
        coefs[s] = (a, b)
    return out, coefs
