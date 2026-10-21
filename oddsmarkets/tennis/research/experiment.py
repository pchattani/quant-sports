"""
Walk-forward experiments for the tennis edge research (docs/research/tennis_edge.md).

Every spec is a ridge logistic regression without intercept on antisymmetric features (A minus B, or a product
with logit of a probability), so swapping A and B flips the prediction exactly. The weights for year Y are fitted
on years [first_train, Y) only, then frozen for Y (an annual refit; the inputs themselves are already walk-forward,
see base.py and features.py). Split, fixed before any test result was looked at:

* dev years 2012-2017: every hyperparameter choice (feature lists, half-lives, ridge, clipping) is made here;
* test years 2018-2025: reported once per spec, never used for a choice. 2026 has no Pinnacle price in
  tennis-data (Pinnacle stopped being published in January 2026), so it is reported against Betfair / average only.

Scores: log-loss (natural log) on the matches with a Pinnacle closing price, the paired difference to Pinnacle's
de-vigged close with a 95 % bootstrap CI resampled by event (matches in one event share players and conditions).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from oddsmarkets.tennis.research import base as B
from oddsmarkets.tennis.research import features as F
from oddsmarkets.tennis.research import mfeats as MF
from oddsmarkets.common.edge import devig as _dv

DEV = tuple(range(2012, 2018))
TEST = tuple(range(2018, 2026))
EPS = 1e-6


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sig(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, float)))


def devig_mult(a, b):
    return _dv.multiplicative_pair(a, b)[0]          # common/edge/devig.py


def devig_power(a, b, iters: int = 40):
    """Power de-vig: find k with (1/a)^k + (1/b)^k = 1; returns P(A). Vectorised bisection."""
    ia, ib = 1.0 / np.asarray(a, float), 1.0 / np.asarray(b, float)
    lo, hi = np.full(ia.shape, 0.5), np.full(ia.shape, 2.0)
    for _ in range(iters):
        k = (lo + hi) / 2
        s = ia ** k + ib ** k
        lo = np.where(s > 1, k, lo)
        hi = np.where(s > 1, hi, k)
    k = (lo + hi) / 2
    return ia ** k


def load(tour: str) -> pd.DataFrame:
    base = B.base_frame(tour)
    feats = F.build(tour)
    df = F.orient(base, feats, tour)
    df = MF.add(df, tour)                                  # market-rating features (Oct 2026)
    df = df[(df["year"] >= 2010) & df["model"].notna()].copy()
    ok = df["ps_A"].notna() & df["ps_B"].notna()
    df["ps_fair"] = np.where(ok, devig_mult(df["ps_A"], df["ps_B"]), np.nan)
    df["ps_pow"] = np.where(ok, devig_power(df["ps_A"].fillna(2), df["ps_B"].fillna(2)), np.nan)
    for k in ("max", "avg", "b365", "bfe"):
        okk = df[f"{k}_A"].notna() & df[f"{k}_B"].notna()
        df[f"{k}_fair"] = np.where(okk, devig_mult(df[f"{k}_A"], df[f"{k}_B"]), np.nan)
    df["tour"] = tour
    return df.reset_index(drop=True)


# ── design ───────────────────────────────────────────────────────────────────

def _clip(x, lo, hi):
    return np.clip(np.nan_to_num(np.asarray(x, float), nan=0.0), lo, hi)


def design(df: pd.DataFrame, names: list[str]) -> np.ndarray:
    """Feature matrix for `names` (each antisymmetric in A/B)."""
    lm = logit(df["model"])
    cols = []
    for n in names:
        if n == "model":
            v = lm
        elif n == "elo":
            v = logit(df["elo"])
        elif n == "sr":
            v = logit(df["sr"].fillna(df["elo"]))
        elif n == "ps":
            v = logit(df["ps_fair"])
        elif n == "ps_pow":
            v = logit(df["ps_pow"])
        elif n == "avg":
            v = logit(df["avg_fair"])
        elif n == "gelo":
            v = np.nan_to_num(df["d_gelo"].to_numpy(float))
        elif n == "form":
            v = np.nan_to_num(df["d_form"].to_numpy(float)) * 5
        elif n == "rest":            # log days since last match, capped 1..60
            a = np.log(np.clip(df["days_A"].fillna(60), 1, 60))
            b = np.log(np.clip(df["days_B"].fillna(60), 1, 60))
            v = (a - b).to_numpy()
        elif n == "m7":
            v = _clip(df["d_m7"], -6, 6)
        elif n == "m30":
            v = _clip(df["d_m30"], -15, 15) / 5
        elif n == "g3":
            v = _clip(df["g3_A"], 0, 90) / 30 - _clip(df["g3_B"], 0, 90) / 30
        elif n == "g7":
            v = _clip(df["g7_A"], 0, 150) / 50 - _clip(df["g7_B"], 0, 150) / 50
        elif n == "min3":
            v = _clip(df["min3_A"], 0, 400) / 120 - _clip(df["min3_B"], 0, 400) / 120
        elif n == "prev":            # games in the previous round of this event (0 when none)
            v = _clip(df["prev_games_A"], 0, 70) / 25 - _clip(df["prev_games_B"], 0, 70) / 25
        elif n == "prev_sets":
            v = _clip(df["prev_sets_A"], 0, 5) - _clip(df["prev_sets_B"], 0, 5)
        elif n == "b2b":
            v = df["d_b2b"].to_numpy(float)
        elif n == "ret":
            v = df["d_ret_last"].to_numpy(float)
        elif n == "wo":
            v = df["d_wo_given30"].to_numpy(float)
        elif n == "layoff":
            v = df["d_layoff60"].to_numpy(float)
        elif n == "layoff120":
            v = df["d_layoff120"].to_numpy(float)
        elif n == "since_layoff":   # first 5 matches back from a 60+ day layoff
            v = ((df["since_layoff_A"] < 5).astype(float) - (df["since_layoff_B"] < 5).astype(float)).to_numpy()
        elif n == "qual":
            v = df["d_qual"].to_numpy(float)
        elif n == "home":
            v = df["d_home"].to_numpy(float)
        elif n == "h2h":
            a, b = df["h2h_w_A"].to_numpy(float), df["h2h_w_B"].to_numpy(float)
            v = (a - b) / (a + b + 3.0)
        elif n == "rank":
            ra = np.log(df["rank_A"].fillna(300).clip(1, 2000))
            rb = np.log(df["rank_B"].fillna(300).clip(1, 2000))
            v = (rb - ra).to_numpy()
        elif n == "pts":
            pa = np.log(df["pts_A"].fillna(1).clip(1, None))
            pb = np.log(df["pts_B"].fillna(1).clip(1, None))
            v = (pa - pb).to_numpy()
        elif n == "x_bo5":
            v = lm * (df["bo"].to_numpy() == 5)
        elif n == "x_tb":            # pace: favourites' edge shrinks on fast courts
            v = lm * (np.nan_to_num(df["ev_tb_rate"].to_numpy(float), nan=0.17) - 0.17) * 10
        elif n == "x_indoor":
            v = lm * df["indoor"].to_numpy(float)
        elif n == "x_new":           # either player with few game-Elo matches: shrink
            n_ = np.minimum(df["gelo_n_A"].to_numpy(float), df["gelo_n_B"].to_numpy(float))
            v = lm * (n_ < 30)
        elif n == "x_early":
            v = lm * df["round"].isin(["R128", "R64", "R32"]).to_numpy(float)
        elif n == "x_level250":
            v = lm * (df["level"].to_numpy() == "250")
        elif n in ("mr", "mr_nm", "mr_avg", "mr_ol3", "mr_seq"):   # market rating, the match's logit scale
            v = df[n].to_numpy(float)
        elif n == "mr_xV":           # the market rating, damped where its variance is high
            v = df["mr"].to_numpy(float) * np.exp(-np.nan_to_num(df["mr_V"].to_numpy(float), nan=2.0))
        elif n == "x_ps_model":      # interaction for the market blend: sharpen/shrink by disagreement
            v = (logit(df["ps_fair"]) - lm) * np.abs(logit(df["ps_fair"]) - lm)
        else:
            raise KeyError(n)
        cols.append(np.asarray(v, float))
    return np.column_stack(cols)


def fit_logit(X: np.ndarray, y: np.ndarray, ridge: float = 1.0, iters: int = 50) -> np.ndarray:
    """Ridge logistic regression without intercept (Newton). Ridge on every coefficient except the first."""
    k = X.shape[1]
    w = np.zeros(k)
    w[0] = 1.0
    R = np.eye(k) * ridge
    R[0, 0] = 1e-6
    for _ in range(iters):
        p = sig(X @ w)
        g = X.T @ (y - p) - R @ w
        H = -(X.T * (p * (1 - p))) @ X - R
        step = np.linalg.solve(H, g)
        w -= step
        if np.max(np.abs(step)) < 1e-9:
            break
    return w


@dataclass
class Spec:
    name: str
    feats: list[str]
    ridge: float = 5.0
    train_from: int = 2010
    note: str = ""
    rows: str = "all"            # "all" or "ps": restrict training to rows with a Pinnacle price (market specs)


def walk_forward(df: pd.DataFrame, spec: Spec, years=None) -> pd.Series:
    """Out-of-sample prediction P(A) for every row in `years` (dev + test by default)."""
    years = years or (DEV + TEST + (2026,))
    out = pd.Series(np.nan, index=df.index)
    need_ps = spec.rows == "ps" or any(f in ("ps", "ps_pow", "x_ps_model") for f in spec.feats)
    base_ok = df["ps_fair"].notna() if need_ps else pd.Series(True, index=df.index)
    X = design(df.assign(ps_fair=df["ps_fair"].fillna(0.5), ps_pow=df["ps_pow"].fillna(0.5)), spec.feats)
    y = df["y"].to_numpy(float)
    yr = df["year"].to_numpy()
    for Y in years:
        tr = (yr >= spec.train_from) & (yr < Y) & base_ok.to_numpy()
        te = (yr == Y) & base_ok.to_numpy()
        if tr.sum() < 500 or te.sum() == 0:
            continue
        w = fit_logit(X[tr], y[tr], spec.ridge)
        out[te] = sig(X[te] @ w)
    return out


def ll_vec(p, y):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boot_ci(diff: np.ndarray, groups: np.ndarray, n: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95 % CI of the mean of `diff`, resampling whole groups."""
    rng = np.random.default_rng(seed)
    codes, inv = np.unique(groups, return_inverse=True)
    s = np.bincount(inv, weights=diff)
    c = np.bincount(inv)
    G = len(codes)
    means = np.empty(n)
    for i in range(n):
        idx = rng.integers(0, G, G)
        means[i] = s[idx].sum() / c[idx].sum()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def score(df: pd.DataFrame, pred: pd.Series, years, ref: str = "ps_fair") -> dict:
    m = df["year"].isin(years) & pred.notna() & df[ref].notna()
    y = df.loc[m, "y"].to_numpy(float)
    a = ll_vec(pred[m], y)
    b = ll_vec(df.loc[m, ref], y)
    base_m = ll_vec(df.loc[m, "model"], y)
    d = a - b
    lo, hi = boot_ci(d, df.loc[m, "event"].astype(str).to_numpy())
    d0 = a - base_m
    lo0, hi0 = boot_ci(d0, df.loc[m, "event"].astype(str).to_numpy(), seed=1)
    return {"n": int(m.sum()), "ll": round(float(a.mean()), 5), "ll_ref": round(float(b.mean()), 5),
            "ll_prod": round(float(base_m.mean()), 5),
            "d_ref": round(float(d.mean()), 5), "d_ref_ci": [round(lo, 5), round(hi, 5)],
            "d_prod": round(float(d0.mean()), 5), "d_prod_ci": [round(lo0, 5), round(hi0, 5)]}


def run(df: pd.DataFrame, spec: Spec) -> dict:
    pred = walk_forward(df, spec)
    return {"spec": spec.name, "feats": spec.feats, "ridge": spec.ridge, "note": spec.note,
            "dev": score(df, pred, DEV), "test": score(df, pred, TEST), "_pred": pred}


def coefs(df: pd.DataFrame, spec: Spec, through: int = 2025) -> dict:
    need_ps = any(f in ("ps", "ps_pow", "x_ps_model") for f in spec.feats) or spec.rows == "ps"
    m = (df["year"] >= spec.train_from) & (df["year"] < through) & (df["ps_fair"].notna() if need_ps else True)
    X = design(df[m].assign(ps_fair=df.loc[m, "ps_fair"].fillna(0.5), ps_pow=df.loc[m, "ps_pow"].fillna(0.5)), spec.feats)
    w = fit_logit(X, df.loc[m, "y"].to_numpy(float), spec.ridge)
    return {f: round(float(v), 4) for f, v in zip(spec.feats, w)}
