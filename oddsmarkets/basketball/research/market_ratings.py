"""
Market-implied team ratings from past CLOSING lines (known before the decision time), walk-forward by day.

Spread:  -close_spread_home(g) = h * [not neutral] + r_home - r_away + e
Total:    close_total(g)       = c + t_home + t_away + e
Weighted ridge (weights 0.5 ** (age / half_life)), team effects shrunk towards a prior: last season's final
market ratings times `carry` (0 for a team without one), with `ridge` games-equivalents. Fitted each US day on
games of days <= D - lag with a close line. Returns, per game, the market-rating spread mean (home margin) and total.

Close line per game: the fetched close (`close_sp_h`, `close_tot`) else the store's line (`store_sp_h`,
`store_tot`, which is the close where both exist: NBA 2026 99.3 %, WNBA 2026 100 %).
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd


def _solve(n_teams, hi, ai, y, w, neutral, prior, lam, kind):
    T = n_teams
    if kind == "spread":
        # params: h, r_0..r_{T-1}
        X = np.zeros((len(y), T + 1))
        X[:, 0] = (~neutral).astype(float)
        X[np.arange(len(y)), 1 + hi] += 1.0
        X[np.arange(len(y)), 1 + ai] -= 1.0
    else:
        X = np.zeros((len(y), T + 1))
        X[:, 0] = 1.0
        X[np.arange(len(y)), 1 + hi] += 1.0
        X[np.arange(len(y)), 1 + ai] += 1.0
    A = X.T @ (X * w[:, None])
    b = X.T @ (w * y)
    P = np.eye(T + 1) * lam
    P[0, 0] = 1e-6
    pr = np.concatenate([[0.0], prior])
    A = A + P
    b = b + P @ pr
    if kind == "spread":
        A[0, 0] += 1e-3
        b[0] += 1e-3 * 2.5
    else:
        A[0, 0] += 1e-6
    return np.linalg.solve(A, b)


def fit(df: pd.DataFrame, half_life: float = 30.0, ridge: float = 4.0, carry: float = 0.6, lag: int = 1) -> pd.DataFrame:
    """Adds mk_mu (market-rating home margin), mk_tot (market-rating total), mk_n (lines used) to a copy of df."""
    d = df.sort_values(["season", "day", "event_id"]).copy()
    d["_sp"] = d["close_sp_h"].where(d["close_sp_h"].notna(), d["store_sp_h"]) if "close_sp_h" in d else d["store_sp_h"]
    d["_tot"] = d["close_tot"].where(d["close_tot"].notna(), d["store_tot"]) if "close_tot" in d else d["store_tot"]
    out_mu, out_tot, out_n = {}, {}, {}
    last_r: dict[str, float] = {}
    last_t: dict[str, float] = {}
    for s, g in d.groupby("season", sort=True):
        teams = sorted(set(g.home) | set(g.away))
        idx = {t: i for i, t in enumerate(teams)}
        pr_r = np.array([carry * last_r.get(t, 0.0) for t in teams])
        pr_t = np.array([carry * last_t.get(t, 0.0) for t in teams])
        hi_all = g.home.map(idx).to_numpy()
        ai_all = g.away.map(idx).to_numpy()
        days = g.day.to_numpy()
        sp = g._sp.to_numpy(float)
        tot = g._tot.to_numpy(float)
        neu = g.neutral.astype(bool).to_numpy()
        ids = g.event_id.to_numpy()
        tot_mean_prior = np.nanmean(tot[: min(len(tot), 60)]) if np.isfinite(tot[:60]).any() else np.nan
        sol_r = sol_t = None
        for D in sorted(set(days)):
            cut = D - timedelta(days=lag)
            m = days <= cut
            age = np.array([(D - x).days for x in days[m]], float)
            w = 0.5 ** (age / half_life)
            ms = m & np.isfinite(sp)
            if ms.sum() >= 1:
                ww = 0.5 ** (np.array([(D - x).days for x in days[ms]], float) / half_life)
                sol_r = _solve(len(teams), hi_all[ms], ai_all[ms], -sp[ms], ww, neu[ms], pr_r, ridge, "spread")
            else:
                sol_r = np.concatenate([[2.5], pr_r])
            mt = m & np.isfinite(tot)
            if mt.sum() >= 1:
                ww = 0.5 ** (np.array([(D - x).days for x in days[mt]], float) / half_life)
                sol_t = _solve(len(teams), hi_all[mt], ai_all[mt], tot[mt], ww, neu[mt], pr_t, ridge, "total")
                c_ok = True
            else:
                sol_t = None
                c_ok = False
            today = days == D
            for k in np.where(today)[0]:
                h, a = hi_all[k], ai_all[k]
                out_mu[ids[k]] = sol_r[0] * (0.0 if neu[k] else 1.0) + sol_r[1 + h] - sol_r[1 + a]
                out_tot[ids[k]] = (sol_t[0] + sol_t[1 + h] + sol_t[1 + a]) if c_ok else np.nan
                out_n[ids[k]] = int(ms.sum())
        if sol_r is not None:
            last_r = {t: float(sol_r[1 + i] - sol_r[1:].mean()) for t, i in idx.items()}
        if sol_t is not None:
            last_t = {t: float(sol_t[1 + i] - sol_t[1:].mean()) for t, i in idx.items()}
    res = df.copy()
    res["mk_mu"] = res.event_id.map(out_mu)
    res["mk_tot"] = res.event_id.map(out_tot)
    res["mk_n"] = res.event_id.map(out_n)
    return res
