"""
Models and scores for the edge research.

Margin and total models: linear (ridge, lambda 1) on decision-time features, refitted per season on earlier
seasons only (`walk_forward`). Outcome distributions are discretised normals (integer margins, no ties;
integer totals) so integer lines push with the right probability.

Market conversions: a spread or total line with two prices -> the market's implied mean (the mean for which
the discretised normal reproduces the de-vigged cover probability) -> P(win), P(push), P(loss) at any other
line. CLV of a bet = expected profit per unit stake at the CLOSING fair probabilities (positive = beat the
close); also reported: fair_p_close (win prob conditional on no push) against 1 / price.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

from oddsmarkets.basketball.research.lines import am_to_dec, devig2

EPS = 1e-4


# ── feature preparation ─────────────────────────────────────────────────────

def prep(df: pd.DataFrame, w_rapm: float = 0.5) -> pd.DataFrame:
    d = df.copy()
    k = d["pace_g"] / 100.0
    d["hca"] = (~d["neutral"].astype(bool)).astype(float)
    for nm in ("rapm", "box"):
        d[f"x_dS_{nm}"] = (d[f"dS_{nm}_h"] - d[f"dS_{nm}_a"]) * k
        d[f"x_dSe_{nm}"] = (d[f"dS_{nm}_h"] * d["prior_share_h"] - d[f"dS_{nm}_a"] * d["prior_share_a"]) * k
    d["x_dS"] = w_rapm * d["x_dS_rapm"] + (1 - w_rapm) * d["x_dS_box"]
    d["x_dSe"] = w_rapm * d["x_dSe_rapm"] + (1 - w_rapm) * d["x_dSe_box"]
    d["x_dSl"] = d["x_dS"] - d["x_dSe"]                      # availability part (in-season)
    # totals: O adds to own points, D (points taken off the opponent) subtracts from the opponent's
    d["x_tot_dS"] = (d["dS_o_h"] + d["dS_o_a"] - d["dS_d_h"] - d["dS_d_a"]) * k
    d["x_rest_sum"] = d[["rest_h", "rest_a"]].clip(upper=3).sum(axis=1)
    d["x_b2b_sum"] = d["b2b_h"].fillna(0) + d["b2b_a"].fillna(0)
    d["x_early"] = ((d["gp_h"] + d["gp_a"]) < 20).astype(float)
    d["x_post"] = (d["stype"] == "post").astype(float)
    d["x_alt_tot"] = d["altitude"]
    return d


MARGIN_BASE = ["rating", "hca", "b2b", "rest", "travel_1000km", "tz", "altitude"]
TOTAL_BASE = ["base_total"]


def ridge(X: np.ndarray, y: np.ndarray, lam: float = 1.0, intercept: bool = False) -> np.ndarray:
    if intercept:
        X = np.column_stack([np.ones(len(X)), X])
    P = np.eye(X.shape[1]) * lam
    if intercept:
        P[0, 0] = 1e-8
    return np.linalg.solve(X.T @ X + P, X.T @ y)


def walk_forward(df: pd.DataFrame, feats: Sequence[str], target: str, test_seasons: Iterable[int],
                 intercept: bool = False, min_train: int = 300, train_from: int | None = None) -> pd.DataFrame:
    """Per test season: fit on all earlier seasons (from `train_from`), predict that season.
    Returns df rows of the test seasons with columns pred, sigma."""
    out = []
    for s in sorted(test_seasons):
        tr = df[(df.season < s) & df[target].notna()]
        if train_from is not None:
            tr = tr[tr.season >= train_from]
        te = df[df.season == s].copy()
        if len(tr) < min_train or te.empty:
            continue
        X = tr[list(feats)].fillna(0).to_numpy(float)
        b = ridge(X, tr[target].to_numpy(float), intercept=intercept)
        Xt = te[list(feats)].fillna(0).to_numpy(float)
        Xtr = np.column_stack([np.ones(len(X)), X]) if intercept else X
        Xte = np.column_stack([np.ones(len(Xt)), Xt]) if intercept else Xt
        res = tr[target].to_numpy(float) - Xtr @ b
        te["pred"] = Xte @ b
        te["sigma"] = float(np.sqrt(np.mean(res ** 2)))
        te["coef"] = [dict(zip((["const"] if intercept else []) + list(feats), np.round(b, 4)))] * len(te)
        out.append(te)
    return pd.concat(out) if out else df.iloc[0:0]


# ── discretised normal outcome model ────────────────────────────────────────

def margin_probs(mu, sd, line, side_sign=1.0, no_tie=True):
    """P(win), P(push), P(loss) for 'home covers' (side_sign=+1: margin + line > 0) under margin ~ discretised
    N(mu, sd) on the integers (0 excluded when no_tie). Vectorised over arrays."""
    mu, sd, line = np.broadcast_arrays(np.asarray(mu, float), np.asarray(sd, float), np.asarray(line, float))
    thr = -line                                     # home covers if margin > thr
    cdf = lambda k: norm.cdf((k + 0.5 - mu) / sd)  # P(M <= k)
    p0 = cdf(0) - cdf(-1) if no_tie else 0.0
    z = 1 - p0 if no_tie else 1.0
    fl = np.floor(thr)
    is_int = np.isclose(thr, np.round(thr))
    # P(M > thr)
    gt = np.where(is_int, 1 - cdf(np.round(thr)), 1 - cdf(fl))
    eq = np.where(is_int, cdf(np.round(thr)) - cdf(np.round(thr) - 1), 0.0)
    if no_tie:
        # remove the mass at 0 from whichever region it falls in
        gt = gt - np.where(0 > thr, p0, 0.0)
        eq = eq - np.where(is_int & np.isclose(np.round(thr), 0), p0, 0.0)
    gt, eq = gt / z, eq / z
    lt = 1 - gt - eq
    if side_sign < 0:
        gt, lt = lt, gt
    return gt, eq, lt


def total_probs(mu, sd, line):
    """P(over), P(push), P(under) for an integer-valued total ~ discretised N(mu, sd)."""
    mu, sd, line = np.broadcast_arrays(np.asarray(mu, float), np.asarray(sd, float), np.asarray(line, float))
    cdf = lambda k: norm.cdf((k + 0.5 - mu) / sd)
    is_int = np.isclose(line, np.round(line))
    over = np.where(is_int, 1 - cdf(np.round(line)), 1 - cdf(np.floor(line)))
    push = np.where(is_int, cdf(np.round(line)) - cdf(np.round(line) - 1), 0.0)
    return over, push, 1 - over - push


def implied_mean(p_cover_nopush: float, line: float, sd: float, kind: str) -> float | None:
    """Mean of the discretised normal under which P(win | no push) for the home side (spread) / over (total)
    equals the de-vigged probability."""
    if p_cover_nopush is None or not (0.001 < p_cover_nopush < 0.999) or line is None or not math.isfinite(line):
        return None

    def f(m):
        if kind == "spread":
            w, e, l_ = margin_probs(m, sd, line)
        else:
            w, e, l_ = total_probs(m, sd, line)
        return float(w / (w + l_)) - p_cover_nopush

    base = -line if kind == "spread" else line
    try:
        return brentq(f, base - 60, base + 60, xtol=1e-6)
    except ValueError:
        return None


# ── scores ───────────────────────────────────────────────────────────────────

def logloss(p, y) -> float:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y) -> float:
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def boot_ci(values: np.ndarray, groups: np.ndarray | None = None, n: int = 2000, seed: int = 0, stat=np.mean) -> tuple[float, float, float]:
    """(estimate, lo95, hi95); cluster bootstrap over `groups` (e.g. game days) when given."""
    v = np.asarray(values, float)
    if len(v) == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    est = float(stat(v))
    if groups is None:
        idx = rng.integers(0, len(v), size=(n, len(v)))
        bs = np.array([stat(v[i]) for i in idx])
    else:
        g = pd.Series(v).groupby(np.asarray(groups))
        sums = g.sum().to_numpy()
        cnts = g.count().to_numpy()
        k = len(sums)
        idx = rng.integers(0, k, size=(n, k))
        bs = sums[idx].sum(1) / cnts[idx].sum(1)
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def paired_ll_diff(p_a, p_b, y, groups) -> tuple[float, float, float]:
    """Log-loss of a minus log-loss of b with a day-clustered bootstrap CI (negative = a better)."""
    pa = np.clip(np.asarray(p_a, float), EPS, 1 - EPS)
    pb = np.clip(np.asarray(p_b, float), EPS, 1 - EPS)
    y = np.asarray(y, float)
    la = -(y * np.log(pa) + (1 - y) * np.log(1 - pa))
    lb = -(y * np.log(pb) + (1 - y) * np.log(1 - pb))
    return boot_ci(la - lb, groups)


def ev(p_win, p_loss, dec):
    """Expected profit per unit stake."""
    return np.asarray(p_win) * (np.asarray(dec) - 1) - np.asarray(p_loss)


def dec(a):
    return np.array([am_to_dec(x) if x is not None and not (isinstance(x, float) and math.isnan(x)) else np.nan for x in a], float)


def fair_two(a_series, b_series):
    out_a, out_b = [], []
    for a, b in zip(a_series, b_series):
        a = None if a is None or (isinstance(a, float) and math.isnan(a)) else a
        b = None if b is None or (isinstance(b, float) and math.isnan(b)) else b
        r = devig2(a, b)
        out_a.append(r[0] if r else np.nan)
        out_b.append(r[1] if r else np.nan)
    return np.array(out_a), np.array(out_b)


def ols(X: np.ndarray, y: np.ndarray, groups=None, const: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """OLS coefficients and (cluster-robust when `groups`) standard errors."""
    X = np.asarray(X, float)
    if X.ndim == 1:
        X = X[:, None]
    if const:
        X = np.column_stack([np.ones(len(X)), X])
    y = np.asarray(y, float)
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    if groups is None:
        S = (X * e[:, None]).T @ (X * e[:, None])
    else:
        codes = pd.factorize(np.asarray(groups))[0]
        U = np.zeros((codes.max() + 1, X.shape[1]))
        np.add.at(U, codes, X * e[:, None])
        S = U.T @ U
    V = XtX_inv @ S @ XtX_inv
    return b, np.sqrt(np.diag(V))
