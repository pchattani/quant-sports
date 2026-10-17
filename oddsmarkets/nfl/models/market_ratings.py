"""
Market-implied team ratings: what earlier CLOSING lines say about each team (a market-blend input).

Spread ratings: before each week, a weighted ridge on every earlier closing line of the season,
    line_g - qadj_g = hfa + r_home - r_away + e,      line = home favoured by (points)
weights 0.5^(age in weeks / half-life); the ridge pulls r toward a prior = rho x the team's final rating of the
previous season (franchise-mapped) with weight lam (in games). qadj_g = s_qb * NP * (QB_home - QB_away) is the game
model's value of each side's starting QB in that game, so a rating is "the team with an average QB" and the upcoming
game adds back its own expected starters (`qb_mode`). Total ratings likewise on closing totals:
    total_g = c + t_home + t_away + e.
Every input is a closing price of a game PLAYED before the week (`played` must be true: a caller simulating "as of"
a date marks later games unplayed), so the ratings are known at any decision time in the week (the open included,
once the previous week's games are final). Defaults (half-life 2 weeks, lam 0.3 games, rho 0.8, QB scale 0.77) were
chosen on 2006-2016 by RMSE against the closing line (2.54 points with the listed QBs; docs/research/nfl_edge.md).

Used by the game model as the feature `mr` (game.attach_market) and by the edge research (oddsmarkets/nfl/edge/).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

DEFAULTS = {"hl": 2.0, "lam": 0.3, "rho": 0.8, "hl_t": 2.0, "lam_t": 0.3, "rho_t": 0.8}
QB_S = 0.77                      # points per (EPA/dropback x dropbacks): the game model's net-rating coefficient


def _fit(y, hi, ai, w, T, lam, prior, home_ind, total: bool = False):
    n = len(y)
    X = np.zeros((n, T + 1))
    X[:, 0] = home_ind if not total else 1.0
    X[np.arange(n), 1 + hi] += 1.0
    X[np.arange(n), 1 + ai] += (-1.0 if not total else 1.0)
    L = np.concatenate([[1e-6], np.full(T, lam)])
    pr = np.concatenate([[0.0], prior])
    A = X.T @ (X * w[:, None]) + np.diag(L)
    b = X.T @ (w * y) + L * pr
    return np.linalg.solve(A, b)


def ratings(G: pd.DataFrame, prm: dict | None = None, qadj: pd.Series | None = None, delay_weeks: int = 0) -> pd.DataFrame:
    """For every game in G (needs game_id, season, week, date, home, away, neutral, line (home favoured by, close),
    total_line, played): mr_line (hfa + r_h - r_a, before QB add-back) and mr_total from earlier closing lines.
    `delay_weeks` = 1 builds the ratings from games before the PREVIOUS week (look-ahead openers)."""
    p = {**DEFAULTS, **(prm or {})}
    G = G.sort_values(["season", "week", "date", "game_id"]).reset_index(drop=True)
    qa = qadj.reindex(G["game_id"]).to_numpy(float) if qadj is not None else np.zeros(len(G))
    qa = np.where(np.isfinite(qa), qa, 0.0)
    out_line = np.full(len(G), np.nan)
    out_tot = np.full(len(G), np.nan)
    out_hfa = np.full(len(G), np.nan)
    prev_final: dict[str, float] = {}
    prev_final_t: dict[str, float] = {}
    last_ct = np.nan
    for s in sorted(G["season"].unique()):
        gs = G[G["season"] == s]
        teams = sorted(set(gs["home"]) | set(gs["away"]))
        ti = {t: i for i, t in enumerate(teams)}
        T = len(teams)
        prior = np.array([p["rho"] * prev_final.get(D.franchise(t), 0.0) for t in teams])
        prior_t = np.array([p["rho_t"] * prev_final_t.get(D.franchise(t), 0.0) for t in teams])
        weeks = sorted(gs["week"].unique())
        hfa_fallback = 2.0
        ct_fallback = last_ct
        for k, w in enumerate(weeks):
            cut_w = weeks[k - delay_weeks] if k - delay_weeks >= 0 else None
            idx_w = gs.index[gs["week"] == w]
            thr = gs.loc[gs["week"] == cut_w, "date"].min() if cut_w is not None else None
            hist = gs[(gs["date"] < thr) & gs["line"].notna() & gs["played"].astype(bool)] if thr is not None else gs.iloc[0:0]
            if len(hist):
                age = (thr - hist["date"]).dt.days.to_numpy(float) / 7.0
                wts = 0.5 ** (age / p["hl"])
                hi = hist["home"].map(ti).to_numpy(int)
                ai = hist["away"].map(ti).to_numpy(int)
                hind = (~hist["neutral"].astype(bool)).to_numpy(float)
                beta = _fit(hist["line"].to_numpy(float) - qa[hist.index], hi, ai, wts, T, p["lam"], prior, hind)
                hf = beta[0]
                r = beta[1:]
                ht = hist[hist["total_line"].notna()]
                wt = 0.5 ** ((thr - ht["date"]).dt.days.to_numpy(float) / 7.0 / p["hl_t"])
                bt = _fit(ht["total_line"].to_numpy(float), ht["home"].map(ti).to_numpy(int), ht["away"].map(ti).to_numpy(int),
                          wt, T, p["lam_t"], prior_t, None, total=True)
                ct, rt = bt[0], bt[1:]
                hfa_fallback, ct_fallback = hf, ct
            else:
                hf, r = hfa_fallback, prior.copy()
                ct, rt = ct_fallback, prior_t.copy()
            gw = G.loc[idx_w]
            hi = gw["home"].map(ti).to_numpy(int)
            ai = gw["away"].map(ti).to_numpy(int)
            hind = (~gw["neutral"].astype(bool)).to_numpy(float)
            out_line[idx_w] = hf * hind + r[hi] - r[ai]
            out_hfa[idx_w] = hf
            out_tot[idx_w] = ct + rt[hi] + rt[ai] if np.isfinite(ct) else np.nan
        # end-of-season ratings for next season's prior
        hist = gs[gs["line"].notna() & gs["played"].astype(bool)]
        if len(hist):
            thr = hist["date"].max() + pd.Timedelta(days=1)
            wts = 0.5 ** ((thr - hist["date"]).dt.days.to_numpy(float) / 7.0 / p["hl"])
            beta = _fit(hist["line"].to_numpy(float) - qa[hist.index], hist["home"].map(ti).to_numpy(int),
                        hist["away"].map(ti).to_numpy(int), wts, T, p["lam"], prior,
                        (~hist["neutral"].astype(bool)).to_numpy(float))
            prev_final = {D.franchise(t): float(beta[1 + i]) for t, i in ti.items()}
            ht = hist[hist["total_line"].notna()]
            wt = 0.5 ** ((thr - ht["date"]).dt.days.to_numpy(float) / 7.0 / p["hl_t"])
            bt = _fit(ht["total_line"].to_numpy(float), ht["home"].map(ti).to_numpy(int), ht["away"].map(ti).to_numpy(int),
                      wt, T, p["lam_t"], prior_t, None, total=True)
            prev_final_t = {D.franchise(t): float(bt[1 + i]) for t, i in ti.items()}
            last_ct = float(bt[0])
    return pd.DataFrame({"game_id": G["game_id"], "mr_line": out_line, "mr_total": out_tot, "mr_hfa": out_hfa})
