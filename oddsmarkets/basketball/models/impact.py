"""
Player impact: RAPM, box impact, Hardwood Plus-Minus (HPM), projections and roster impact.

RAPM (regularised adjusted plus-minus)
--------------------------------------
Each lineup stint (contract STINT / stints.json row) gives two observations, one per offence:

    y = 100 * pts_off / poss_off  -  league ORtg
      = sum_{i on offence} O_i  -  sum_{j on defence} D_j  +  (hca / 2) * s  +  e,
    weight = poss_off,  Var(e) = sigma^2 / poss_off,  s = +1 home offence, -1 away offence

O_i is points per 100 possessions a player adds to his team's offence, D_j points per 100 he
takes off the opponent's (positive = good defence); total T = O + D. The fit is ridge
(Bayesian) least squares with the prior O_i, D_i ~ N(m_i, sigma^2 / lambda): m = 0 for a first
season or the previous season's estimate times PRIOR_CARRY (the multi-season prior), hca with a
near-flat prior. lambda is chosen from RIDGE_GRID by K-fold cross-validation over held-out games
(weighted squared error per possession). Solve: (X'WX + Lambda) b = X'Wy + Lambda m with X sparse
(scipy.sparse) and a dense Cholesky on the (2P + 1)^2 normal matrix (P ~ 550 for an NBA season:
milliseconds). Posterior covariance sigma^2 (X'WX + Lambda)^-1 with sigma^2 the weighted residual
variance gives se for O, D and T (including the O-D covariance). Players with few possessions stay
near their prior: that is the shrinkage.

Box impact (our BPM)
--------------------
A possession-weighted ridge regression of RAPM O and D on per-100 box rates (BOX_FEATURES:
points, true-shooting points added, 3PA and FT rates, assists, turnovers, offensive and defensive
rebounds, steals, blocks, fouls, usage, position pool) plus, in the play-by-play era, shot features
(SHOT_FEATURES: rim and three frequency, shrunk shot-making) — two variants, "full" and "box", the
second applicable to box-only seasons (1997-2016). As in BPM, a team adjustment then adds one
constant per team so that the minutes-weighted five-man sum of box impact equals the team's
actual offensive / defensive rating margin. The residual variance tau^2 (weighted variance of
RAPM - box minus the mean RAPM se^2, floored) is the prior variance HPM uses.

HPM
---
Precision-weighted combination, offence and defence separately:
    HPM = (box / tau^2 + RAPM / se^2) / (1 / tau^2 + 1 / se^2),   se_HPM = (1 / tau^2 + 1 / se^2)^-1/2
so HPM lies between its inputs and leans to RAPM as possessions accumulate. Players with no RAPM
(box-only seasons) get box impact with se tau. (RAPM is itself ridge-shrunk to its prior, so this is
the simple "two noisy measurements" combination, not a joint posterior.)

Projections and roster impact
-----------------------------
`projections` gives per-player per-36 rates from exponentially weighted games (half-life
HALF_LIFE_GAMES) regressed to the position-pool mean with PRIOR_MINUTES pseudo-minutes, expected
minutes (half-life MINUTES_HALF_LIFE games), availability, age and an aging adjustment (AGE_CURVE,
per-season change in HPM, hand-set from the public aging literature). `roster_impact(team_players,
minutes)` is the five-man HPM sum per 100 possessions over expected minutes, with any unfilled
minutes at REPLACEMENT_HPM: builder B's preseason prior and injury adjustment use differences of it.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy.linalg
import scipy.sparse as sp

from oddsmarkets.basketball.models import _io

MODEL_VERSION = "impact-1"
BOX_VERSION = 2               # box rates / impact: missing box scores left out (_io.box_frame); team adjustment needs 10 box games

RIDGE_GRID = [250.0, 500.0, 1000.0, 2000.0, 3500.0, 6000.0, 10000.0]
DEFAULT_RIDGE = 2000.0
CV_FOLDS = 5
HCA_RIDGE = 1e-3
PRIOR_CARRY = 0.8            # previous season's RAPM carried as this season's ridge centre, times 0.8
MIN_STINT_POSS = 0.0

BOX_FEATURES = ["pts100", "ts_add", "tpar", "ftr", "ast100", "tov100", "oreb100", "dreb100", "stl100", "blk100", "pf100",
                "usg", "pool_G", "pool_F"]
SHOT_FEATURES = ["rim_freq", "three_freq", "pox100_shrunk"]
BOX_RIDGE = 5.0              # on standardised features, in units of total weight / 1000
BOX_WEIGHT_CAP = 4000.0      # possessions; cap the regression weight of heavy-minute players
MIN_TEAM_BOX_GAMES = 10       # team adjustment of box impact needs this many games with a box score
TAU2_FLOOR = 0.25
RATE_PSEUDO_FGA = 20.0       # shrink 3PA rate and FT rate toward the league with 20 pseudo-FGA
TS_PSEUDO = 50.0             # TS attempts of league-average shooting added before ts_add

HALF_LIFE_GAMES = 60.0
MINUTES_HALF_LIFE = 12.0
PRIOR_MINUTES = 250.0
REPLACEMENT_HPM = -2.0
PROJ_STATS = ["pts", "fga", "tpa", "fta", "fgm", "tpm", "ftm", "ast", "tov", "oreb", "dreb", "stl", "blk", "pf"]
# per-season change in HPM by age (points per 100), linear between knots
AGE_CURVE = [(19, 1.2), (21, 0.9), (23, 0.6), (25, 0.3), (27, 0.0), (29, -0.25), (31, -0.6), (33, -1.0), (35, -1.4), (38, -2.0)]


# ============================================================================ RAPM

def as_stints(stints: Any) -> pd.DataFrame:
    """Stints as a DataFrame in stints.json column order (game_id, t0, t1, h1..h5, a1..a5, poss_h,
    poss_a, pts_h, pts_a). Accepts the {"cols","rows"} file, row lists, a DataFrame or contract
    STINT dicts ({"home":[5],"away":[5],"poss_home",...}, with optional "game_id")."""
    if isinstance(stints, list) and stints and isinstance(stints[0], dict) and "home" in stints[0]:
        rows = []
        for s in stints:
            h, a = list(s["home"])[:5], list(s["away"])[:5]
            rows.append([s.get("game_id", s.get("game")), s.get("t0"), s.get("t1"), *h, *a,
                         s.get("poss_home", 0), s.get("poss_away", 0), s.get("pts_home", 0), s.get("pts_away", 0)])
        stints = rows
    df = _io.as_frame(stints, _io.STINT_COLS)
    if df.empty:
        return pd.DataFrame(columns=_io.STINT_COLS)
    for c in ("poss_h", "poss_a", "pts_h", "pts_a"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    for c in _io.STINT_COLS[3:13]:
        df[c] = df[c].astype(str)
    df["game_id"] = df["game_id"].astype(str)
    return df


def _rapm_design(df: pd.DataFrame, pidx: dict[str, int]) -> tuple[sp.csr_matrix, np.ndarray, np.ndarray, np.ndarray, float]:
    """Sparse X (rows = offence observations), y (centred per-100), w (possessions), game ids, league ORtg."""
    P = len(pidx)
    H = df[["h1", "h2", "h3", "h4", "h5"]].to_numpy()
    A = df[["a1", "a2", "a3", "a4", "a5"]].to_numpy()
    hi = np.vectorize(pidx.__getitem__)(H) if len(df) else np.zeros((0, 5), int)
    ai = np.vectorize(pidx.__getitem__)(A) if len(df) else np.zeros((0, 5), int)
    ph, pa = df["poss_h"].to_numpy(float), df["poss_a"].to_numpy(float)
    sh, sa = df["pts_h"].to_numpy(float), df["pts_a"].to_numpy(float)
    keep_h, keep_a = ph > MIN_STINT_POSS, pa > MIN_STINT_POSS
    off = np.concatenate([hi[keep_h], ai[keep_a]])
    dfn = np.concatenate([ai[keep_h], hi[keep_a]])
    s = np.concatenate([np.full(keep_h.sum(), 0.5), np.full(keep_a.sum(), -0.5)])
    poss = np.concatenate([ph[keep_h], pa[keep_a]])
    pts = np.concatenate([sh[keep_h], sa[keep_a]])
    games = np.concatenate([df["game_id"].to_numpy()[keep_h], df["game_id"].to_numpy()[keep_a]])
    n = len(poss)
    lg = 100.0 * pts.sum() / max(poss.sum(), 1e-9)
    y = 100.0 * pts / np.maximum(poss, 1e-9) - lg
    rows = np.repeat(np.arange(n), 11)
    cols = np.concatenate([off, P + dfn, np.full((n, 1), 2 * P)], axis=1).ravel()
    vals = np.concatenate([np.ones((n, 5)), -np.ones((n, 5)), s[:, None]], axis=1).ravel()
    X = sp.csr_matrix((vals, (rows, cols)), shape=(n, 2 * P + 1))
    return X, y, poss, games, lg


def _normal(X: sp.csr_matrix, y: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    Xw = X.multiply(w[:, None]).tocsr()
    return (X.T @ Xw).toarray(), np.asarray(X.T @ (w * y)).ravel(), float(np.sum(w * y * y)), float(w.sum())


def _solve(G: np.ndarray, r: np.ndarray, lam_vec: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, Any]:
    A = G + np.diag(lam_vec)
    c = scipy.linalg.cho_factor(A, check_finite=False)
    return scipy.linalg.cho_solve(c, r + lam_vec * m, check_finite=False), c


def _prior_vec(players: list[str], prior: dict | None) -> np.ndarray:
    P = len(players)
    m = np.zeros(2 * P + 1)
    if prior:
        for k, pid in enumerate(players):
            p = prior.get(pid)
            if p:
                m[k] = float(p.get("o") or 0.0)
                m[P + k] = float(p.get("d") or 0.0)
    return m


def rapm_fit(stints: Any, players: Iterable[str] | dict | None = None, ridge: float | Iterable[float] | None = None,
             prior: dict | None = None, folds: int = CV_FOLDS, seed: int = 0) -> dict:
    """
    Fit RAPM on stints. `ridge` = one lambda (no CV), a list of lambdas (CV over them) or None (CV over
    RIDGE_GRID). `prior` = {pid: {"o","d"}} ridge centres (see `carry_prior`). `players` optionally
    restricts the output (all players in the stints are always in the fit).
    Returns {"players": {pid: {"o","d","t","se_o","se_d","se","poss","poss_o","poss_d"}}, "ridge", "cv":
    {lambda: mse}, "hca", "league_ortg", "sigma", "n_rows", "n_players"}.
    """
    df = as_stints(stints)
    if df.empty:
        return {"players": {}, "ridge": None, "cv": {}, "hca": None, "league_ortg": None, "sigma": None, "n_rows": 0, "n_players": 0}
    ids = sorted(set(np.unique(df[_io.STINT_COLS[3:13]].to_numpy().ravel())))
    pidx = {p: i for i, p in enumerate(ids)}
    P = len(ids)
    X, y, w, games, lg = _rapm_design(df, pidx)
    m = _prior_vec(ids, prior)
    yc = y   # prior centres enter through the penalty
    grid = RIDGE_GRID if ridge is None else ([float(ridge)] if np.isscalar(ridge) else [float(v) for v in ridge])

    def lam_vec(lam):
        v = np.full(2 * P + 1, lam)
        v[-1] = HCA_RIDGE
        return v

    cv: dict[float, float] = {}
    if len(grid) > 1:
        ug = np.unique(games)
        rng = np.random.default_rng(seed)
        fold_of_game = dict(zip(ug, rng.permutation(len(ug)) % folds))
        fid = np.array([fold_of_game[g] for g in games])
        parts = []
        for k in range(folds):
            msk = fid == k
            parts.append((_normal(X[msk], yc[msk], w[msk]), msk))
        G_all = sum(p[0][0] for p in parts)
        r_all = sum(p[0][1] for p in parts)
        for lam in grid:
            sse = tot = 0.0
            for (Gk, rk, _yy, wk), msk in parts:
                b, _ = _solve(G_all - Gk, r_all - rk, lam_vec(lam), m)
                res = yc[msk] - X[msk] @ b
                sse += float(np.sum(w[msk] * res ** 2))
                tot += wk
            cv[lam] = sse / max(tot, 1e-9)
        lam = min(cv, key=cv.get)
    else:
        lam = grid[0]
    G, r, _yy, _wt = _normal(X, yc, w)
    lv = lam_vec(lam)
    b, cf = _solve(G, r, lv, m)
    res = yc - X @ b
    Ainv = scipy.linalg.cho_solve(cf, np.eye(2 * P + 1), check_finite=False)
    edf = float(np.trace(Ainv @ G))
    n = X.shape[0]
    sigma2 = float(np.sum(w * res ** 2) / max(n - edf, 1.0))
    cov = sigma2 * Ainv
    poss_o = np.asarray(abs(X[:, :P]).T @ w).ravel()
    poss_d = np.asarray(abs(X[:, P:2 * P]).T @ w).ravel()
    want = set(players) if players is not None else None
    out = {}
    for k, pid in enumerate(ids):
        if want is not None and pid not in want:
            continue
        vo, vd, cod = cov[k, k], cov[P + k, P + k], cov[k, P + k]
        out[pid] = {"o": float(b[k]), "d": float(b[P + k]), "t": float(b[k] + b[P + k]),
                    "se_o": math.sqrt(max(vo, 0.0)), "se_d": math.sqrt(max(vd, 0.0)),
                    "se": math.sqrt(max(vo + vd + 2 * cod, 0.0)),
                    "poss": float(poss_o[k] + poss_d[k]), "poss_o": float(poss_o[k]), "poss_d": float(poss_d[k])}
    return {"players": out, "ridge": lam, "cv": {str(k): v for k, v in cv.items()}, "hca": float(b[-1]), "league_ortg": lg,
            "sigma": math.sqrt(sigma2), "n_rows": int(n), "n_players": P}


def rapm(stints: Any, players: Iterable[str] | dict | None = None, ridge: float | Iterable[float] | None = None,
         prior: dict | None = None) -> dict:
    """Contract shape: {pid: {"o","d","t","poss","se", ...}} (see `rapm_fit`)."""
    return rapm_fit(stints, players, ridge, prior)["players"]


def carry_prior(prev: dict | None, factor: float = PRIOR_CARRY) -> dict:
    """Last season's {pid: {"o","d"}} scaled by `factor`: the next season's ridge centre."""
    return {p: {"o": factor * float(v.get("o") or 0.0), "d": factor * float(v.get("d") or 0.0)} for p, v in (prev or {}).items()}


def rapm_seasons(stints_by_season: dict, ridge=None, carry: float = PRIOR_CARRY) -> dict:
    """Sequential multi-season RAPM: each season's fit is centred on the previous season's estimate x carry."""
    out, prev = {}, None
    for s in sorted(stints_by_season):
        out[s] = rapm_fit(stints_by_season[s], ridge=ridge, prior=carry_prior(prev, carry) if prev else None)
        prev = out[s]["players"]
    return out


# ============================================================================ box rates and box impact

def box_rates(games: Any, players: dict | None = None, shots_profile: pd.DataFrame | None = None,
              stypes: Iterable[str] = ("reg",)) -> pd.DataFrame:
    """Per-player season rates from GAME box scores (dict of games or a `_io.box_frame` DataFrame).
    Index player_id; columns: team (most minutes), games, starts, minutes, mpg, poss (on-floor, both
    ends counted once), per-100 rates (pts100, fga100, tpa100, fta100, ast100, tov100, oreb100, dreb100,
    stl100, blk100, pf100), ts, ts_add, tpar, ftr, usg, pool and pool dummies, team_ortg/team_drtg/team_net
    (per 100, primary team), lg_ortg, plus the shot profile columns when given."""
    bf = games if isinstance(games, pd.DataFrame) else _io.box_frame(games, stypes)
    if bf.empty:
        return pd.DataFrame(columns=["team", "games", "minutes", "poss"] + BOX_FEATURES)
    bf = bf.copy()
    # game length (s) = the team's player-seconds / 5 (regulation + overtime, any league)
    gsec = bf.groupby(["game_id", "team"])["sec"].transform("sum") / 5.0
    bf["on_poss"] = bf["team_poss"] * bf["sec"] / gsec.clip(lower=1.0)
    played = bf[bf["sec"] > 0]
    g = played.groupby("player_id")
    tot = g[["sec", "on_poss", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf",
             "starter"]].sum()
    out = pd.DataFrame(index=tot.index)
    out["games"] = g.size()
    out["starts"] = tot["starter"]
    out["minutes"] = tot["sec"] / 60.0
    out["mpg"] = out["minutes"] / out["games"]
    out["poss"] = tot["on_poss"]
    pp = out["poss"].clip(lower=1.0)
    for s in ("pts", "fga", "tpa", "fta", "ast", "tov", "oreb", "dreb", "stl", "blk", "pf"):
        out[f"{s}100"] = 100 * tot[s] / pp
    lg_tsa = float((played["fga"] + 0.44 * played["fta"]).sum())
    lg_ts = float(played["pts"].sum() / max(2 * lg_tsa, 1e-9))
    tsa = tot["fga"] + 0.44 * tot["fta"]
    out["ts"] = tot["pts"] / (2 * tsa).where(tsa > 0)
    ts_shr = (tot["pts"] + 2 * TS_PSEUDO * lg_ts) / (2 * (tsa + TS_PSEUDO))
    out["ts_add"] = (ts_shr - lg_ts) * 2 * 100 * tsa / pp
    lg_tpar = float(played["tpa"].sum() / max(played["fga"].sum(), 1e-9))
    lg_ftr = float(played["fta"].sum() / max(played["fga"].sum(), 1e-9))
    out["tpar"] = (tot["tpa"] + RATE_PSEUDO_FGA * lg_tpar) / (tot["fga"] + RATE_PSEUDO_FGA)
    out["ftr"] = (tot["fta"] + RATE_PSEUDO_FGA * lg_ftr) / (tot["fga"] + RATE_PSEUDO_FGA)
    out["usg"] = 100 * (tot["fga"] + 0.44 * tot["fta"] + tot["tov"]) / pp
    # primary team and its ratings
    tm = played.groupby(["player_id", "team"])["sec"].sum().reset_index().sort_values("sec").drop_duplicates("player_id", keep="last")
    out["team"] = tm.set_index("player_id")["team"].reindex(out.index)
    tg = bf.drop_duplicates(["game_id", "team"])
    tt = tg.groupby("team")[["team_pts", "opp_pts", "team_poss"]].sum()
    tt["box_games"] = tg.groupby("team").size()
    lg_ortg = 100 * float(tt["team_pts"].sum() / max(tt["team_poss"].sum(), 1e-9))
    tt["ortg"] = 100 * tt["team_pts"] / tt["team_poss"].clip(lower=1.0)
    tt["drtg"] = 100 * tt["opp_pts"] / tt["team_poss"].clip(lower=1.0)
    out["team_ortg"] = out["team"].map(tt["ortg"])
    out["team_drtg"] = out["team"].map(tt["drtg"])
    out["team_net"] = out["team_ortg"] - out["team_drtg"]
    out["team_box_games"] = out["team"].map(tt["box_games"])
    out["lg_ortg"] = lg_ortg
    out["lg_ts"] = lg_ts
    # team-minute fraction (five-man share) on the primary team
    tsec = played.groupby("team")["sec"].sum()
    psec = played.groupby(["player_id", "team"])["sec"].sum()
    out["frac"] = [5.0 * psec.get((p, t), 0.0) / max(tsec.get(t, 0.0), 1e-9) for p, t in zip(out.index, out["team"])]
    pools = {}
    for pid in out.index:
        info = (players or {}).get(pid) or {}
        pools[pid] = str(info.get("pool") or "F")[:1]
    out["pool"] = pd.Series(pools)
    out["pool_G"] = (out["pool"] == "G").astype(float)
    out["pool_F"] = (out["pool"] == "F").astype(float)
    if shots_profile is not None and not shots_profile.empty:
        sp_ = shots_profile.copy()
        sp_.index = sp_.index.astype(str)
        for c in SHOT_FEATURES:
            if c in sp_:
                out[c] = sp_[c].reindex(out.index)
    out.index.name = "player_id"
    return out


def _wridge(Z: np.ndarray, y: np.ndarray, w: np.ndarray, lam: float) -> np.ndarray:
    """Weighted ridge with a free intercept; Z already standardised."""
    n, k = Z.shape
    Xa = np.column_stack([np.ones(n), Z])
    L = np.diag([0.0] + [lam] * k)
    A = Xa.T @ (Xa * w[:, None]) + L
    return np.linalg.solve(A + 1e-9 * np.eye(k + 1), Xa.T @ (w * y))


def _variant_fit(rates: pd.DataFrame, rp: dict, feats: list[str], lam: float) -> dict:
    df = rates.loc[[p for p in rates.index if p in rp]].copy()
    df = df[df[feats].notna().all(axis=1) & (df["poss"] > 0)]
    if len(df) < len(feats) + 5:
        return {"ok": False, "reason": f"only {len(df)} players with RAPM and features"}
    Z = df[feats].to_numpy(float)
    w = np.minimum(df["poss"].to_numpy(float), BOX_WEIGHT_CAP)
    mu = np.average(Z, axis=0, weights=w)
    sd = np.sqrt(np.average((Z - mu) ** 2, axis=0, weights=w))
    sd[sd < 1e-9] = 1.0
    Zs = (Z - mu) / sd
    lam_eff = lam * w.sum() / 1000.0
    out = {"ok": True, "features": feats, "mu": mu.tolist(), "sd": sd.tolist(), "n": int(len(df))}
    for side in ("o", "d"):
        y = np.array([rp[p][side] for p in df.index], float)
        coef = _wridge(Zs, y, w, lam_eff)
        out[f"coef_{side}"] = coef.tolist()
    model = {"variants": {"x": out}}
    pred = box_impact(df, model, team_adjust=True, variant="x")
    for side in ("o", "d"):
        y = np.array([rp[p][side] for p in df.index], float)
        se2 = np.array([rp[p].get(f"se_{side}", 0.0) ** 2 for p in df.index], float)
        r = y - pred[side].reindex(df.index).to_numpy(float)
        tau2 = float(np.average(r ** 2, weights=w) - np.average(se2, weights=w))
        out[f"tau2_{side}"] = max(tau2, TAU2_FLOOR)
        out[f"r2_{side}"] = float(1 - np.average(r ** 2, weights=w) / max(np.average((y - np.average(y, weights=w)) ** 2, weights=w), 1e-12))
    return out


def box_impact_fit(box_rates: pd.DataFrame | list[pd.DataFrame], rapm: dict | list[dict], lam: float = BOX_RIDGE) -> dict:
    """Fit box impact on one or more seasons (lists of equal length: per-season box_rates and RAPM
    {pid: {"o","d","se_o","se_d"}}). Player-season rows are pooled; index keys get a season suffix.
    Returns {"variants": {"full": {...}, "box": {...}}} with coefficients on standardised features,
    the residual variances tau2_o / tau2_d and in-sample r2."""
    rl = box_rates if isinstance(box_rates, list) else [box_rates]
    pl = rapm if isinstance(rapm, list) else [rapm]
    frames, rp = [], {}
    for k, (br, r) in enumerate(zip(rl, pl)):
        f = br.copy()
        f.index = [f"{p}@{k}" for p in f.index]
        f["season_k"] = k
        if "team" in f:
            f["team"] = [f"{t}@{k}" for t in f["team"]]
        frames.append(f)
        for p, v in (r or {}).items():
            rp[f"{p}@{k}"] = v
    rates = pd.concat(frames)
    variants = {}
    full = BOX_FEATURES + SHOT_FEATURES
    if all(c in rates for c in SHOT_FEATURES) and rates[SHOT_FEATURES].notna().any(axis=None):
        v = _variant_fit(rates, rp, full, lam)
        if v.get("ok"):
            variants["full"] = v
    v = _variant_fit(rates, rp, BOX_FEATURES, lam)
    if v.get("ok"):
        variants["box"] = v
    return {"version": MODEL_VERSION, "variants": variants, "ok": bool(variants)}


def box_impact(box_rates: pd.DataFrame, model: dict, team_adjust: bool = True, variant: str | None = None) -> pd.DataFrame:
    """Box impact per player: DataFrame [o, d, t, variant] (points per 100). Uses the "full" variant
    where the shot features are present, else "box". With team_adjust, a constant per team makes the
    five-man (minutes-weighted) sums match the team's ORtg - league and league - DRtg."""
    vs = model.get("variants") or {}
    out = pd.DataFrame(index=box_rates.index, columns=["o", "d"], dtype=float)
    used = pd.Series("", index=box_rates.index, dtype=object)
    order = [variant] if variant else ["full", "box"]
    for name in order:
        v = vs.get(name)
        if not v:
            continue
        feats = v["features"]
        if not all(c in box_rates for c in feats):
            continue
        rows = box_rates[feats].notna().all(axis=1) & out["o"].isna()
        if not rows.any():
            continue
        Z = (box_rates.loc[rows, feats].to_numpy(float) - np.array(v["mu"])) / np.array(v["sd"])
        for side in ("o", "d"):
            c = np.array(v[f"coef_{side}"])
            out.loc[rows, side] = c[0] + Z @ c[1:]
        used[rows] = name
    if team_adjust and {"team", "frac", "team_ortg", "team_drtg", "lg_ortg"} <= set(box_rates.columns):
        for t, idx in box_rates.groupby("team").groups.items():
            sub = box_rates.loc[idx]
            ok = out.loc[idx, "o"].notna()
            if not ok.any() or pd.isna(sub["team_ortg"].iloc[0]):
                continue
            if "team_box_games" in sub and float(sub["team_box_games"].iloc[0] or 0) < MIN_TEAM_BOX_GAMES:
                continue                      # too few box scores (NBA 2015-16 CHI has one): no team adjustment
            frac = sub["frac"].to_numpy(float)
            lg = float(sub["lg_ortg"].iloc[0])
            so = float(np.nansum(out.loc[idx, "o"].to_numpy(float) * frac))
            sd_ = float(np.nansum(out.loc[idx, "d"].to_numpy(float) * frac))
            out.loc[idx, "o"] += (float(sub["team_ortg"].iloc[0]) - lg - so) / 5.0
            out.loc[idx, "d"] += (lg - float(sub["team_drtg"].iloc[0]) - sd_) / 5.0
    out["t"] = out["o"] + out["d"]
    out["variant"] = used
    return out


# ============================================================================ HPM

def hpm(box: pd.DataFrame | dict, rapm: dict | None, model: dict) -> dict:
    """Combine box impact (prior) and RAPM (likelihood) by precision, offence and defence separately.
    `box`: box_impact output (or {pid: {"o","d","variant"}}); `rapm`: {pid: {"o","d","se_o","se_d"}};
    `model`: box_impact_fit output (tau2 per variant). Returns {pid: {"o","d","t","se_o","se_d","se",
    "box_o","box_d","rapm_o","rapm_d","w_rapm_o","w_rapm_d"}}."""
    if isinstance(box, pd.DataFrame):
        box = {str(p): r for p, r in box.to_dict(orient="index").items()}
    vs = model.get("variants") or {}
    rapm = rapm or {}
    out = {}
    for pid in set(box) | set(rapm):
        b = box.get(pid) or {}
        v = vs.get(b.get("variant") or "") or vs.get("full") or vs.get("box") or {}
        r = rapm.get(pid)
        rec: dict[str, Any] = {}
        for side in ("o", "d"):
            tau2 = float(v.get(f"tau2_{side}", 4.0))
            bv = b.get(side)
            bv = float(bv) if bv is not None and np.isfinite(bv) else None
            prec_b = 1.0 / tau2 if bv is not None else 0.0
            if r is not None and r.get(f"se_{side}"):
                se2 = float(r[f"se_{side}"]) ** 2
                prec_r, rv = 1.0 / se2, float(r[side])
            else:
                prec_r, rv = 0.0, 0.0
            if prec_b + prec_r == 0:
                val, se = 0.0, math.sqrt(tau2)
            else:
                val = ((bv or 0.0) * prec_b + rv * prec_r) / (prec_b + prec_r)
                se = 1.0 / math.sqrt(prec_b + prec_r)
            rec[side], rec[f"se_{side}"] = val, se
            rec[f"box_{side}"] = bv
            rec[f"rapm_{side}"] = float(r[side]) if r is not None else None
            rec[f"w_rapm_{side}"] = prec_r / (prec_b + prec_r) if prec_b + prec_r > 0 else 0.0
        rec["t"] = rec["o"] + rec["d"]
        rec["se"] = math.sqrt(rec["se_o"] ** 2 + rec["se_d"] ** 2)
        out[pid] = rec
    return out


# ============================================================================ projections

def aging_delta(age: float | None) -> float:
    """Expected change in HPM over the next season at `age` (AGE_CURVE, linear between knots)."""
    if age is None or not np.isfinite(age):
        return 0.0
    xs, ys = zip(*AGE_CURVE)
    return float(np.interp(age, xs, ys))


def _age(dob: str | None, asof: str) -> float | None:
    try:
        d = date.fromisoformat(str(dob)[:10])
        a = date.fromisoformat(str(asof)[:10])
        return (a - d).days / 365.25
    except (TypeError, ValueError):
        return None


def projections(games: Any, asof: str | None = None, players: dict | None = None, hpm_values: dict | None = None,
                half_life: float = HALF_LIFE_GAMES, stypes: Iterable[str] = ("reg", "post", "playin", "cup")) -> dict:
    """Per-player projections at `asof` (YYYY-MM-DD, exclusive) from one or more seasons of GAME boxes
    (dict of games, list of dicts, or a `_io.box_frame`). For each player:
    {"rates": {stat: per-36}, "min": expected minutes when available, "avail": share of his current team's
     last 20 games played, "games", "team", "pool", "age", "aging": aging_delta, "hpm", "hpm_next"}.
    Rates are exponentially weighted (half-life `half_life` of the player's games) and regressed to the
    pool mean with PRIOR_MINUTES pseudo-minutes."""
    if isinstance(games, pd.DataFrame):
        bf = games
    else:
        gl = list(games.values()) if isinstance(games, dict) else list(games)
        bf = _io.box_frame(gl, stypes)
    if bf.empty:
        return {}
    if asof:
        bf = bf[bf["date"] < str(asof)[:10]]
    asof = asof or str(bf["date"].max())
    bf = bf.sort_values(["date", "game_id"])
    played = bf[bf["sec"] > 0].copy()
    players = players or {}
    played["pool"] = played["player_id"].map(lambda p: str((players.get(p) or {}).get("pool") or "F")[:1])
    played["min"] = played["sec"] / 60.0
    pool_rate = {}
    for pool, sub in played.groupby("pool"):
        m = sub["min"].sum()
        pool_rate[pool] = {s: float(sub[s].sum() / max(m, 1e-9)) for s in PROJ_STATS}
    lg_rate = {s: float(played[s].sum() / max(played["min"].sum(), 1e-9)) for s in PROJ_STATS}
    played["k"] = played.groupby("player_id").cumcount(ascending=False)
    played["w"] = 0.5 ** (played["k"] / half_life)
    played["wm"] = 0.5 ** (played["k"] / MINUTES_HALF_LIFE)
    # availability on current team: share of the team's last 20 games he played
    team_games = bf.drop_duplicates(["game_id", "team"]).groupby("team")["game_id"].apply(lambda s: list(s)[-20:])
    out = {}
    for pid, sub in played.groupby("player_id"):
        pool = sub["pool"].iloc[0]
        prior = pool_rate.get(pool, lg_rate)
        wmin = float((sub["w"] * sub["min"]).sum())
        rates = {s: 36.0 * float(((sub["w"] * sub[s]).sum() + PRIOR_MINUTES * prior[s]) / (wmin + PRIOR_MINUTES)) for s in PROJ_STATS}
        exp_min = float((sub["wm"] * sub["min"]).sum() / sub["wm"].sum())
        team = sub["team"].iloc[-1]
        tg = team_games.get(team, [])
        mine = set(sub["game_id"])
        avail = float(np.mean([g in mine for g in tg])) if tg else 1.0
        info = players.get(pid) or {}
        age = _age(info.get("dob"), asof)
        h = (hpm_values or {}).get(pid)
        hv = float(h["t"] if isinstance(h, dict) else h) if h is not None else None
        ad = aging_delta(age)
        out[pid] = {"rates": rates, "min": exp_min, "avail": avail, "games": int(len(sub)), "team": team, "pool": pool,
                    "age": age, "aging": ad, "hpm": hv, "hpm_next": (hv + ad) if hv is not None else None}
    return out


def roster_impact(team_players: dict | Iterable[str], minutes: dict, league: str = "nba",
                  replacement: float = REPLACEMENT_HPM, hpm_values: dict | None = None) -> dict:
    """Five-man HPM sum per 100 possessions for a roster over expected minutes.
    `team_players`: {pid: HPM total | {"t","o","d"}} (or a list of pids with `hpm_values` given);
    `minutes`: {pid: expected minutes per game}. Minutes are scaled down to 5 x game length if they exceed
    it; any shortfall is filled at `replacement`. Returns {"net","off","def","minutes","fill_minutes","players"}.
    The difference between a full and an injury-depleted roster is the injury adjustment."""
    if not isinstance(team_players, dict):
        team_players = {p: (hpm_values or {}).get(p, replacement) for p in team_players}
    gm = _io.game_minutes(league)
    cap = 5.0 * gm
    mins = {p: max(0.0, float(minutes.get(p, 0.0) or 0.0)) for p in team_players}
    tot = sum(mins.values())
    scale = cap / tot if tot > cap else 1.0
    net = off = dfn = 0.0
    det = {}
    for p, v in team_players.items():
        if isinstance(v, dict):
            t = float(v.get("t", (v.get("o") or 0.0) + (v.get("d") or 0.0)))
            o = float(v.get("o", t / 2))
            d = float(v.get("d", t - o))
        else:
            t = float(v if v is not None else replacement)
            o, d = t / 2, t / 2
        m = mins[p] * scale
        net += t * m / gm
        off += o * m / gm
        dfn += d * m / gm
        det[p] = {"min": m, "hpm": t, "contrib": t * m / gm}
    fill = max(0.0, cap - tot * scale)
    net += replacement * fill / gm
    off += replacement / 2 * fill / gm
    dfn += replacement / 2 * fill / gm
    return {"net": net, "off": off, "def": dfn, "minutes": tot * scale, "fill_minutes": fill, "players": det}


# ============================================================================ season loader

def _season_rapm(league: str, season: int, use_cache: bool, depth: int = 0) -> dict | None:
    path = _io.data_root() / league / str(season) / "stints.json"
    if not _io.exists(path):
        return None
    prev = _season_rapm(league, season - 1, use_cache, depth + 1) if depth < 12 else None
    key = _io.file_key(MODEL_VERSION, path, (prev or {}).get("key_hash"))

    def build():
        st = _io.read_json(path)
        res = rapm_fit(st, prior=carry_prior(prev["players"]) if prev else None)
        res["key_hash"] = key
        return res

    return _io.cached("rapm", f"{league}_{season}", key, build, use_cache)


def box_model(league: str, use_cache: bool = True) -> dict:
    """Box impact fitted on every season on disk with stints (play-by-play era), pooled; cached on the
    input files. Seasons without stints (1997-2016) use its "box" variant."""
    from oddsmarkets.basketball.models import shots as shots_mod
    root = _io.data_root() / league
    seasons = sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit() and _io.exists(p / "stints.json"))         if root.exists() else []
    key = _io.file_key(MODEL_VERSION, BOX_VERSION, *[root / str(s) / f for s in seasons for f in ("store.json", "stints.json", "shots.json")])

    def build():
        rl, pl = [], []
        for s in seasons:
            r = _season_rapm(league, s, use_cache)
            if not r or not r.get("players"):
                continue
            st = _io.read_json(root / str(s) / "store.json") or {}
            sh = shots_mod.for_season(league, s, use_cache=use_cache)
            prof = pd.DataFrame.from_dict(sh["players"], orient="index") if sh.get("ok") else None
            rl.append(box_rates(st.get("games") or {}, st.get("players") or {}, prof))
            pl.append(r["players"])
        return _io.clean(box_impact_fit(rl, pl), 8) if rl else {"ok": False, "variants": {}, "reason": "no seasons with stints"}

    return _io.cached("impact", f"box_model_{league}", key, build, use_cache)


def for_season(league: str, season: int, through: str | None = None, use_cache: bool = True) -> dict:
    """RAPM (multi-season prior), box impact (fitted on every play-by-play season on disk), HPM and
    projections for one league-season. Returns {"ok","league","season","players": {pid: {...}},
    "rapm": {ridge, hca, league_ortg, sigma, cv}, "box_model": {...}} or {"ok": False, "reason"}.
    `through` limits box rates and projections to games on or before that date (RAPM uses the stints file
    as committed)."""
    try:
        root = _io.data_root() / league
        store = _io.read_json(root / str(season) / "store.json")
        if not store:
            return {"ok": False, "reason": "no store.json"}
        games = {k: g for k, g in (store.get("games") or {}).items() if not through or str(g.get("date") or "")[:10] <= through}
        # dates of birth: only the current season's store has them; scripts/bb_bio.py fills the rest (data/<L>/bio.json)
        from oddsmarkets.basketball.analytics import bio as _bio
        players = _bio.fill_dob(league, store.get("players") or {})
        from oddsmarkets.basketball.models import shots as shots_mod
        seasons = sorted(int(p.name) for p in root.iterdir() if p.is_dir() and p.name.isdigit()) if root.exists() else []
        key = _io.file_key(MODEL_VERSION, BOX_VERSION, through, *[root / str(s) / f for s in seasons for f in ("store.json", "stints.json", "shots.json")],
                           root / "bio.json")

        def build():
            bm = box_model(league, use_cache)
            sh = shots_mod.for_season(league, season, through=through, use_cache=use_cache)
            prof = pd.DataFrame.from_dict(sh["players"], orient="index") if sh.get("ok") else None
            br = box_rates(games, players, prof)
            bi = box_impact(br, bm) if bm.get("ok") and not br.empty else pd.DataFrame()
            r = _season_rapm(league, season, use_cache)
            h = hpm(bi, (r or {}).get("players"), bm) if not bi.empty or r else {}
            prev_games = (_io.read_json(root / str(season - 1) / "store.json") or {}).get("games") or {}
            pj = projections(list(prev_games.values()) + list(games.values()), asof=None if not through else through,
                             players=players, hpm_values=h)
            out = {}
            for pid in set(h) | set(br.index):
                rec = dict(h.get(pid) or {})
                if pid in br.index:
                    b = br.loc[pid]
                    rec.update({"team": b["team"], "games": int(b["games"]), "minutes": float(b["minutes"]), "poss": float(b["poss"])})
                rr = ((r or {}).get("players") or {}).get(pid)
                if rr:
                    rec["rapm"] = rr
                if pid in pj:
                    rec["proj"] = pj[pid]
                out[pid] = rec
            meta = {k: (r or {}).get(k) for k in ("ridge", "hca", "league_ortg", "sigma", "cv", "n_rows", "n_players")}
            return _io.clean({"ok": True, "league": league, "season": int(season), "through": through, "players": out,
                              "rapm": meta, "box_model": bm})

        return _io.cached("impact", f"{league}_{season}_{through or 'all'}", key, build, use_cache)
    except Exception as exc:                                          # pragma: no cover - defensive
        return {"ok": False, "reason": f"impact failed: {exc}"}
