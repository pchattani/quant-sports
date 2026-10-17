"""
Fallback shot xG used only when builder B's xg model does not score a season (CI cold cache, a model error, or a
season before B's coverage). A ridge-penalised logistic regression on the season's own unblocked attempts:
distance (linear, log, squared), angle, distance x angle, shot type, rebound (an attempt by the same team within 3 s
of the previous one), rush (within 4 s of an event in the neutral or defensive zone), strength (PP / SH / EV / empty
net). Fitted by iteratively reweighted least squares; payloads say xg_source = "fallback" when it is used.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHOT_TYPES = ("wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "poke", "bat", "between-legs", "cradle")


def features(ev: pd.DataFrame) -> np.ndarray:
    d = ev["dist"].to_numpy(float)
    d = np.where(np.isnan(d), 35.0, np.clip(d, 1.0, 190.0))
    a = ev["angle"].to_numpy(float)
    a = np.where(np.isnan(a), 30.0, a)
    st = ev["shot_type"].astype(str).str.lower() if "shot_type" in ev else pd.Series("", index=ev.index)
    cols = [np.ones(len(ev)), d / 10, np.log(d), (d / 10) ** 2, a / 10, d * a / 1000]
    for t in SHOT_TYPES[:7]:
        cols.append((st == t).to_numpy(float))
    reb, rush = rebound_rush(ev)
    cols += [reb, rush, reb * (a / 10)]
    s = ev["st"].astype(str).to_numpy() if "st" in ev else np.array(["EV"] * len(ev))
    cols += [(s == "PP").astype(float), (s == "SH").astype(float), (s == "EN").astype(float)]
    return np.column_stack(cols)


def rebound_rush(ev: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Rebound and rush flags from the event sequence (the table's own flags when it has them)."""
    n = len(ev)
    if "rebound" in ev and ev["rebound"].notna().any():
        reb = ev["rebound"].fillna(0).to_numpy(float)
    else:
        g = ev["game_id"].to_numpy()
        t = ev["sec"].to_numpy(float)
        team = ev["team"].astype(str).to_numpy()
        is_att = ev["type"].isin(("GOAL", "SHOT", "MISS", "BLOCK")).to_numpy()
        reb = np.zeros(n)
        same_g = np.r_[False, g[1:] == g[:-1]]
        prev_att = np.r_[False, is_att[:-1]]
        prev_team = np.r_[team[:1], team[:-1]]
        dt = np.r_[np.inf, t[1:] - t[:-1]]
        reb = (same_g & prev_att & (prev_team == team) & (dt <= 3) & (dt >= 0)).astype(float)
    if "rush" in ev and ev["rush"].notna().any():
        rush = ev["rush"].fillna(0).to_numpy(float)
    else:
        g = ev["game_id"].to_numpy()
        t = ev["sec"].to_numpy(float)
        x = ev["x"].to_numpy(float)
        same_g = np.r_[False, g[1:] == g[:-1]]
        dt = np.r_[np.inf, t[1:] - t[:-1]]
        prev_x = np.r_[np.nan, x[:-1]]
        # the previous event's x is in its own team's frame; a neutral-zone event is |x| < 25 in any frame
        rush = (same_g & (dt <= 4) & (dt >= 0) & (np.abs(prev_x) < 25)).astype(float)
    return reb, rush


def _pll(X: np.ndarray, y: np.ndarray, b: np.ndarray, P: np.ndarray) -> float:
    z = np.clip(X @ b, -30, 30)
    return float(np.sum(y * z - np.logaddexp(0, z)) - 0.5 * b @ P @ b)


def fit(X: np.ndarray, y: np.ndarray, lam: float = 5.0, iters: int = 50) -> np.ndarray:
    """Ridge logistic regression on standardised columns (the first column is the intercept), Newton steps with
    step halving on the penalised log-likelihood; returns coefficients on the original scale."""
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    mu[0], sd[0] = 0.0, 1.0
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    Z[:, 0] = 1.0
    b = np.zeros(X.shape[1])
    b[0] = np.log(max(y.mean(), 1e-3) / max(1 - y.mean(), 1e-3))
    P = lam * np.eye(X.shape[1])
    P[0, 0] = 0.0
    cur = _pll(Z, y, b, P)
    for _ in range(iters):
        z = np.clip(Z @ b, -30, 30)
        p = 1 / (1 + np.exp(-z))
        w = np.clip(p * (1 - p), 1e-6, None)
        H = Z.T @ (Z * w[:, None]) + P
        g = Z.T @ (y - p) - P @ b
        step = np.linalg.solve(H, g)
        t = 1.0
        while t > 1e-4:
            nb = b + t * step
            nv = _pll(Z, y, nb, P)
            if nv >= cur - 1e-9:
                break
            t /= 2
        b, gain, cur = nb, nv - cur, nv
        if abs(gain) < 1e-7:
            break
    beta = b / sd
    beta[0] = b[0] - np.sum(b[1:] * mu[1:] / sd[1:])
    return beta


def score(ev: pd.DataFrame) -> np.ndarray:
    """xG for every unblocked attempt of the frame (NaN elsewhere); empty-net goals keep their fitted value."""
    fen = ev["type"].isin(("GOAL", "SHOT", "MISS")).to_numpy()
    out = np.full(len(ev), np.nan)
    if fen.sum() < 200:
        return out
    X = features(ev)
    y = (ev["type"] == "GOAL").to_numpy(float)
    b = fit(X[fen], y[fen])
    out[fen] = 1 / (1 + np.exp(-np.clip(X[fen] @ b, -30, 30)))
    return out
