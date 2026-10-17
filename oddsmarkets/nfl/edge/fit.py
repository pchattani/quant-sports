"""
Walk-forward coefficient fits on decision-time rows (edge/walk.py), with any feature list.

Margin: ridge of the home margin on `mfeats` + home field (constant, a trend per decade from 2015, one term per season
penalised toward 0 by game.LAM_HFA), refitted before every week on all earlier played rows of the same decision mode
(rows whose ratings had no game of the season yet are left out of fitting, as in production). Key-number multipliers
once per season from earlier seasons. Total: ridge of (total - base) on `tfeats` + a constant; total key multipliers
once per season. Nothing from a game's own week enters its coefficients.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.models import game as GM

MFEATS = ("f_net", "f_sr", "f_div", "f_rest", "f_bye", "f_short", "f_travel", "f_tz")
TFEATS = ("t_off", "t_wind", "t_cold", "t_dome")


def _design_margin(r: pd.DataFrame, mfeats, seasons_list):
    hfa = r["f_hfa"].to_numpy(float)
    sea = r["season"].to_numpy(int)
    cols = [r[c].to_numpy(float) for c in mfeats] + [hfa, (sea - 2015.0) / 10.0 * hfa]
    cols += [(sea == s) * hfa for s in seasons_list]
    return np.column_stack(cols)


def _ridge(X, y, lam):
    A = X.T @ X + np.diag(lam)
    return np.linalg.solve(A, X.T @ y)


def wf_predict(rows: pd.DataFrame, mfeats=MFEATS, tfeats=TFEATS, start: int = 2006, lam: float = 1.0,
               fit_from: int = 1999, extra_fit_mask: pd.Series | None = None, total_keys: bool = True,
               margin_keys: bool = True) -> pd.DataFrame:
    """rows: one decision mode. Returns rows (season >= start) with mu, sigma, mu_t, sigma_t, season keys index."""
    rows = rows.sort_values(["season", "week", "date", "game_id"]).reset_index(drop=True)
    fitmask = rows["played"].astype(bool) & rows["margin"].notna() & (rows["n_games_rated"] > 0) & (rows["season"] >= fit_from)
    if extra_fit_mask is not None:
        fitmask &= extra_fit_mask.reindex(rows.index).fillna(False).astype(bool)
    for c in list(mfeats) + list(tfeats):
        rows[c] = pd.to_numeric(rows[c], errors="coerce").fillna(0.0)
    out = []
    keys_by, tkeys_by = {}, {}
    for s in sorted(rows.loc[rows["season"] >= start, "season"].unique()):
        hist = rows[fitmask & (rows["season"] < s)]
        # season-level keys from the earlier seasons' fitted means
        us = sorted(hist["season"].unique())
        X = _design_margin(hist, mfeats, us)
        lamv = np.concatenate([np.full(len(mfeats), lam), [1e-6, lam], np.full(len(us), GM.LAM_HFA)])
        b = _ridge(X, hist["margin"].to_numpy(float), lamv)
        res = hist["margin"].to_numpy(float) - X @ b
        sig = float(np.sqrt(np.mean(res ** 2)))
        kk = GM.fit_keys(X @ b, hist["margin"].to_numpy(float), sig) if margin_keys else GM.keys({"keys": [0.08] + [1.0] * GM.KEY_MAX})
        Xt = np.column_stack([hist[c].to_numpy(float) for c in tfeats] + [np.ones(len(hist))])
        yt = hist["total"].to_numpy(float) - hist["base"].to_numpy(float)
        bt = _ridge(Xt, yt, np.concatenate([np.full(len(tfeats), lam), [1e-6]]))
        sig_t = float(np.sqrt(np.mean((yt - Xt @ bt) ** 2)))
        tk = MK.fit_total_keys(hist["base"].to_numpy(float) + Xt @ bt, hist["total"].to_numpy(float), sig_t) if total_keys else None
        keys_by[int(s)], tkeys_by[int(s)] = kk, tk
        rs = rows[rows["season"] == s]
        for w in sorted(rs["week"].unique()):
            tr = rows[fitmask & ((rows["season"] < s) | ((rows["season"] == s) & (rows["week"] < w)))]
            us = sorted(tr["season"].unique())
            X = _design_margin(tr, mfeats, us)
            lamv = np.concatenate([np.full(len(mfeats), lam), [1e-6, lam], np.full(len(us), GM.LAM_HFA)])
            b = _ridge(X, tr["margin"].to_numpy(float), lamv)
            k = len(mfeats) + 2
            sig = float(np.sqrt(np.sum((tr["margin"].to_numpy(float) - X @ b) ** 2) / max(len(tr) - k, 1)))
            Xt = np.column_stack([tr[c].to_numpy(float) for c in tfeats] + [np.ones(len(tr))])
            yt = tr["total"].to_numpy(float) - tr["base"].to_numpy(float)
            bt = _ridge(Xt, yt, np.concatenate([np.full(len(tfeats), lam), [1e-6]]))
            sig_t = float(np.sqrt(np.sum((yt - Xt @ bt) ** 2) / max(len(tr) - len(tfeats) - 1, 1)))
            gw = rows[(rows["season"] == s) & (rows["week"] == w)]
            Xg = _design_margin(gw, mfeats, us)
            mu = Xg @ b
            Xtg = np.column_stack([gw[c].to_numpy(float) for c in tfeats] + [np.ones(len(gw))])
            mt = gw["base"].to_numpy(float) + Xtg @ bt
            out.append(gw.assign(mu=mu, sigma=sig, mu_t=mt, sigma_t=sig_t, keys_season=int(s)))
    P = pd.concat(out, ignore_index=True)
    P.attrs["keys"] = keys_by
    P.attrs["tkeys"] = tkeys_by
    return P


def probs(P: pd.DataFrame) -> pd.DataFrame:
    """p_home (ML, a tie counted half), and the margin pmf-based functions need keys: adds p_home."""
    ph = np.full(len(P), np.nan)
    for s, idx in P.groupby("keys_season").groups.items():
        g = P.loc[idx]
        kk = P.attrs["keys"][int(s)]
        po = g["gtype"].astype(str).ne("REG").to_numpy()
        a, t = GM.win_probs(g["mu"].to_numpy(float), float(g["sigma"].iloc[0]), po, kk) if g["sigma"].nunique() == 1 else (None, None)
        if a is None:
            a = np.zeros(len(g)); t = np.zeros(len(g))
            for j, (m, sg, p_) in enumerate(zip(g["mu"], g["sigma"], po)):
                x, y = GM.win_probs(np.array([m]), float(sg), np.array([p_]), kk)
                a[j], t[j] = x[0], y[0]
        ph[P.index.get_indexer(idx)] = a + t / 2.0
    P = P.copy()
    P["p_home"] = ph
    return P


def cover_probs(P: pd.DataFrame, spread_col: str) -> tuple[np.ndarray, np.ndarray]:
    """Model P(home covers | no push), P(push) at the line in `spread_col` (home handicap)."""
    pc, pp = np.full(len(P), np.nan), np.full(len(P), np.nan)
    for j, r in enumerate(P[["mu", "sigma", "keys_season", spread_col]].itertuples(index=False)):
        if not np.isfinite(r[3]):
            continue
        row = GM.margin_pmf(np.array([r[0]]), float(r[1]), P.attrs["keys"][int(r[2])])
        a, b = MK.cover_home(row, np.array([r[3]]))
        pc[j], pp[j] = a[0], b[0]
    return pc, pp


def over_probs(P: pd.DataFrame, total_col: str) -> tuple[np.ndarray, np.ndarray]:
    po, pp = np.full(len(P), np.nan), np.full(len(P), np.nan)
    for j, r in enumerate(P[["mu_t", "sigma_t", "keys_season", total_col]].itertuples(index=False)):
        if not np.isfinite(r[3]):
            continue
        row = MK.total_pmf(np.array([r[0]]), float(r[1]), P.attrs["tkeys"][int(r[2])])
        a, b = MK.over_prob(row, np.array([r[3]]))
        po[j], pp[j] = a[0], b[0]
    return po, pp
