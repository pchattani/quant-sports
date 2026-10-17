"""
RAPM: regularised adjusted plus-minus on 5v5 stints, offence and defence separately.

Each 5v5 stint (both nets manned, five skaters a side) gives two observations, one per attacking side:

    y = 3600 * metric_for / duration          (per 60: xG, goals or shot attempts of the attacking side)
      = mu + sum_{i in attackers} O_i - sum_{j in defenders} D_j
        + h * home_attack + z_O * OZ start + z_D * DZ start + z_N * NZ start      (faceoff at the stint's start,
                                                                                   attacking side's view; on the
                                                                                   fly is the baseline)
        + sum_s c_s * [attacking side's lead = s]  (s in -2-, -1, +1, +2+; tied baseline)
        + b_a * attacking team on a back-to-back + b_d * defending team on a back-to-back + e
    weight = duration (minutes)

O_i (xGF/60 a skater adds to his side), D_j (xGA/60 he takes off the opponent's; positive = good defence),
net = O + D. Ridge (Bayesian) least squares: O_i, D_i ~ N(m_i, sigma^2 / lambda) with m = PRIOR_CARRY x last
season's estimate (sequential multi-season fits; a first season or a new player centres on 0) and the controls
nearly unpenalised. lambda from RIDGE_GRID by 5-fold cross-validation over games (weighted squared error per
minute; with fewer than MIN_GAMES_CV games, early in a season, lambda is the last completed season's). Solve (X'WX + Lambda) b = X'Wy + Lambda m by Cholesky on the dense normal matrix (2P + 12 columns);
posterior covariance sigma^2 (X'WX + Lambda)^-1, sigma^2 the weighted residual variance per minute, gives se
for O, D and net (with the O-D covariance). Three targets: xG (the headline), goals (GF/GA: with the defending
goalie as an extra defence-only column, so skaters are not charged for goaltending) and shot attempts (CF/CA).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import scipy.linalg
import scipy.sparse as sp

from oddsmarkets.nhl.models import _io, _stints

MODEL_VERSION = "nhlrapm-2"
RIDGE_GRID = [60.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0, 16000.0]
CTRL_RIDGE = 1e-3
CV_FOLDS = 5
PRIOR_CARRY = 0.7
TARGETS = {"xg": "xg", "gf": "gf", "cf": "cf"}
CONTROLS = ["mu", "home", "zs_O", "zs_D", "zs_N", "lead_m2", "lead_m1", "lead_p1", "lead_p2", "b2b_att", "b2b_def"]
MIN_DUR = 1.0
MAX_SEASONS_BACK = 6
MIN_GAMES_CV = 150          # fewer games (a season's first weeks): no CV, lambda from the last completed season
DEFAULT_RIDGE = 1000.0


def design(st: pd.DataFrame, target: str = "xg", goalies: bool = False) -> dict:
    """Sparse design from enriched stints (5v5 only). Returns X, y (per 60), w (minutes), games, ids (skaters),
    gids (goalies, defence-only columns when `goalies`)."""
    s = st[(st["strength"] == "5v5") & (st["dur"].to_numpy(float) >= MIN_DUR)]
    H = s[_io.SLOTS_H[:5]].to_numpy(float)
    A = s[_io.SLOTS_A[:5]].to_numpy(float)
    ok = np.isfinite(H).all(axis=1) & np.isfinite(A).all(axis=1)
    s, H, A = s[ok], H[ok], A[ok]
    ids = np.unique(np.concatenate([H.ravel(), A.ravel()]))
    P = len(ids)
    hi = np.searchsorted(ids, H)
    ai = np.searchsorted(ids, A)
    gids = np.unique(np.concatenate([s["hg"].to_numpy(float), s["ag"].to_numpy(float)])) if goalies else np.zeros(0)
    gids = gids[np.isfinite(gids)]
    G = len(gids)
    n = len(s)
    dur = s["dur"].to_numpy(float)
    yh = 3600.0 * s[f"h_{target}"].to_numpy(float) / dur
    ya = 3600.0 * s[f"a_{target}"].to_numpy(float) / dur
    zs = s["zs_h"].to_numpy(object)
    lead_h = np.clip(s["score_h0"].to_numpy(float) - s["score_a0"].to_numpy(float), -2, 2)
    b2bh, b2ba = s["b2b_h"].to_numpy(float), s["b2b_a"].to_numpy(float)
    C = len(CONTROLS)
    ncol = 2 * P + G + C
    rows, cols, vals = [], [], []
    for side in ("h", "a"):
        att, dfn = (hi, ai) if side == "h" else (ai, hi)
        r0 = 0 if side == "h" else n
        r = np.arange(n) + r0
        rows += [np.repeat(r, 5), np.repeat(r, 5)]
        cols += [att.ravel(), P + dfn.ravel()]
        vals += [np.ones(5 * n), -np.ones(5 * n)]
        if goalies:
            gd = s["ag" if side == "h" else "hg"].to_numpy(float)
            m = np.isfinite(gd)
            rows.append(r[m])
            cols.append(2 * P + np.searchsorted(gids, gd[m]))
            vals.append(-np.ones(int(m.sum())))
        z = zs if side == "h" else np.where(zs == "O", "D", np.where(zs == "D", "O", zs))
        lead = lead_h if side == "h" else -lead_h
        ctrl = np.column_stack([np.ones(n), np.full(n, 1.0 if side == "h" else 0.0), (z == "O").astype(float),
                                (z == "D").astype(float), (z == "N").astype(float), (lead <= -2).astype(float),
                                (lead == -1).astype(float), (lead == 1).astype(float), (lead >= 2).astype(float),
                                b2bh if side == "h" else b2ba, b2ba if side == "h" else b2bh])
        rr, cc = np.nonzero(ctrl)
        rows.append(r[rr])
        cols.append(2 * P + G + cc)
        vals.append(ctrl[rr, cc])
    X = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(2 * n, ncol))
    games = np.concatenate([s["game_id"].to_numpy(), s["game_id"].to_numpy()])
    return {"X": X, "y": np.concatenate([yh, ya]), "w": np.concatenate([dur, dur]) / 60.0, "games": games, "ids": ids,
            "gids": gids, "P": P, "G": G}


def _normal(X: sp.csr_matrix, y: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    Xw = sp.diags(w) @ X
    return (X.T @ Xw).toarray(), np.asarray(X.T @ (w * y)).ravel(), float(w.sum())


def _lam_vec(lam: float, P: int, G: int) -> np.ndarray:
    v = np.full(2 * P + G + len(CONTROLS), float(lam))
    v[2 * P + G:] = CTRL_RIDGE
    return v


def _solve(Gm: np.ndarray, r: np.ndarray, lv: np.ndarray, m: np.ndarray):
    A = Gm + np.diag(lv)
    c = scipy.linalg.cho_factor(A, check_finite=False)
    return scipy.linalg.cho_solve(c, r + lv * m, check_finite=False), c


def prior_vector(ids: np.ndarray, gids: np.ndarray, prior: dict | None, P: int, G: int) -> np.ndarray:
    m = np.zeros(2 * P + G + len(CONTROLS))
    if prior:
        for k, pid in enumerate(ids):
            p = prior.get(str(int(pid)))
            if p:
                m[k] = float(p.get("o") or 0.0)
                m[P + k] = float(p.get("d") or 0.0)
        for k, gid in enumerate(gids):
            p = prior.get(f"g{int(gid)}")
            if p:
                m[2 * P + k] = float(p.get("d") or 0.0)
    return m


def fit(st: pd.DataFrame, target: str = "xg", prior: dict | None = None, ridge=None, folds: int = CV_FOLDS,
        seed: int = 0) -> dict:
    """RAPM on one season's enriched stints. `prior` {pid: {"o","d"}} (goalies keyed "g<pid>"); `ridge` a lambda
    (no CV), a list (CV over it) or None (CV over RIDGE_GRID)."""
    d = design(st, TARGETS[target], goalies=(target == "gf"))
    X, y, w, games, P, G = d["X"], d["y"], d["w"], d["games"], d["P"], d["G"]
    if P == 0 or X.shape[0] < 50:
        return {"ok": False, "reason": "too few 5v5 stints", "players": {}}
    m = prior_vector(d["ids"], d["gids"], prior, P, G)
    grid = RIDGE_GRID if ridge is None else ([float(ridge)] if np.isscalar(ridge) else [float(v) for v in ridge])
    if ridge is None and len(np.unique(games)) < MIN_GAMES_CV:
        grid = [committed_ridge(target)]
    cv: dict[float, float] = {}
    if len(grid) > 1:
        ug = np.unique(games)
        rng = np.random.default_rng(seed)
        fold_of = dict(zip(ug.tolist(), (rng.permutation(len(ug)) % folds).tolist()))
        fid = np.array([fold_of[g] for g in games.tolist()])
        parts = []
        for k in range(folds):
            msk = fid == k
            parts.append((_normal(X[msk], y[msk], w[msk]), msk))
        G_all = sum(p[0][0] for p in parts)
        r_all = sum(p[0][1] for p in parts)
        for lam in grid:
            sse = tot = 0.0
            lv = _lam_vec(lam, P, G)
            for (Gk, rk, wk), msk in parts:
                b, _ = _solve(G_all - Gk, r_all - rk, lv, m)
                res = y[msk] - X[msk] @ b
                sse += float(np.sum(w[msk] * res ** 2))
                tot += wk
            cv[lam] = sse / max(tot, 1e-9)
        del parts, G_all, r_all
        lam = min(cv, key=cv.get)
    else:
        lam = grid[0]
    Gm, r, _ = _normal(X, y, w)
    lv = _lam_vec(lam, P, G)
    b, cf = _solve(Gm, r, lv, m)
    res = y - X @ b
    Ainv = scipy.linalg.cho_solve(cf, np.eye(len(b)), check_finite=False)
    edf = float(np.sum(Ainv * Gm))                       # trace(Ainv @ G) for symmetric matrices
    sigma2 = float(np.sum(w * res ** 2) / max(X.shape[0] - edf, 1.0))
    var = sigma2 * np.diag(Ainv)
    cov_od = sigma2 * np.array([Ainv[k, P + k] for k in range(P)])
    toi = np.asarray(abs(X[:, :P]).T @ w).ravel() / 2.0 + np.asarray(abs(X[:, P:2 * P]).T @ w).ravel() / 2.0
    out = {}
    for k, pid in enumerate(d["ids"]):
        vo, vd = var[k], var[P + k]
        out[str(int(pid))] = {"o": float(b[k]), "d": float(b[P + k]), "t": float(b[k] + b[P + k]),
                              "se_o": math.sqrt(max(vo, 0.0)), "se_d": math.sqrt(max(vd, 0.0)),
                              "se": math.sqrt(max(vo + vd + 2 * cov_od[k], 0.0)), "toi": float(toi[k]),
                              "prior_o": float(m[k]), "prior_d": float(m[P + k])}
    gout = {}
    for k, gid in enumerate(d["gids"]):
        gout[f"g{int(gid)}"] = {"d": float(b[2 * P + k]), "se_d": math.sqrt(max(var[2 * P + k], 0.0))}
    ctrl = {c: float(b[2 * P + G + i]) for i, c in enumerate(CONTROLS)}
    ctrl_se = {c: math.sqrt(max(var[2 * P + G + i], 0.0)) for i, c in enumerate(CONTROLS)}
    return {"ok": True, "target": target, "players": out, "goalies": gout, "ridge": lam,
            "cv": {str(k): v for k, v in cv.items()}, "controls": ctrl, "controls_se": ctrl_se, "sigma": math.sqrt(sigma2),
            "n_rows": int(X.shape[0]), "n_players": int(P), "league_rate": float(np.sum(w * y) / np.sum(w))}


def committed_ridge(target: str) -> float:
    """lambda of the last completed season's fit (models/fitted/rapm_prior.json), DEFAULT_RIDGE without one."""
    f = _io.read_fit("rapm_prior")
    try:
        v = float(((f or {}).get(target) or {}).get("ridge") or 0)
    except (TypeError, ValueError):
        v = 0.0
    return v if v > 0 else DEFAULT_RIDGE


def carry_prior(prev: dict | None, factor: float = PRIOR_CARRY) -> dict:
    """Last season's estimates x factor: the next season's ridge centres."""
    out = {}
    for p, v in ((prev or {}).get("players") or {}).items():
        out[p] = {"o": factor * float(v.get("o") or 0.0), "d": factor * float(v.get("d") or 0.0)}
    for g, v in ((prev or {}).get("goalies") or {}).items():
        out[g] = {"d": factor * float(v.get("d") or 0.0)}
    return out


# ============================================================================ seasons

def season_fit(season: int, prior_fits: dict | None = None, use_cache: bool = True) -> dict:
    """The three RAPM fits of one season ({"xg","gf","cf"}), each centred on the previous season's (prior_fits)."""
    from oddsmarkets.nhl.models import xg as xgm
    season = _io.sid(season)
    f = xgm.current_fit() or {}
    pk = _io.file_key(json_key(prior_fits))
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), _io.store_path(season), MODEL_VERSION,
                       f.get("key"), f.get("platt"), pk)
    return _io.cached("rapm", str(season), key, lambda: _build_season(season, prior_fits), use_cache, gz=True)


def json_key(prior_fits: dict | None) -> str:
    if not prior_fits:
        return "none"
    return str(prior_fits.get("key") or "")


def _build_season(season: int, prior_fits: dict | None) -> dict:
    st = _stints.for_season(season)
    if st is None or not len(st):
        return {"ok": False, "reason": "no stints", "season": season}
    out = {"ok": True, "season": season, "version": MODEL_VERSION}
    for t in TARGETS:
        pr = carry_prior((prior_fits or {}).get(t)) if prior_fits else None
        out[t] = fit(st, t, pr)
    out["key"] = _io.file_key(season, MODEL_VERSION, *[out[t].get("ridge") for t in TARGETS],
                              *[round(out[t].get("sigma") or 0, 6) for t in TARGETS],
                              json_key(prior_fits), len((out["xg"].get("players") or {})))
    return _io.clean(out, 7)


def chain(season: int, use_cache: bool = True) -> dict:
    """Sequential fits from the earliest season on disk (at most MAX_SEASONS_BACK back) to `season`; the first
    season of the chain is centred on the committed prior (models/fitted/rapm_prior.json) when it is the season
    after it, else on zero. Iterative (one season of stints in memory at a time)."""
    season = _io.sid(season)
    have = [s for s in _io.seasons_on_disk(need_stints=True) if s <= season]
    if season not in have:
        return {"ok": False, "reason": "no stints for this season"}
    have = have[-(MAX_SEASONS_BACK + 1):]
    prev = None
    committed = _io.read_fit("rapm_prior")
    if isinstance(committed, dict) and committed.get("version") == MODEL_VERSION and \
            int(committed.get("season", 0)) == _prev_season(have[0]):
        prev = committed
    res = None
    for s in have:
        if prev is not None and int(prev.get("season", 0)) != _prev_season(s):
            prev = None            # a gap in the chain: start afresh
        res = season_fit(s, prev, use_cache)
        prev = res if res.get("ok") else None
    return res or {"ok": False, "reason": "no fit"}


def _prev_season(s: int) -> int:
    y = _io.sid(s) // 10000
    return (y - 1) * 10000 + y


def player_rows(res: dict) -> pd.DataFrame:
    """One row per skater: player_id, off, def, net (xG/60), se's, toi5 (minutes), gf/ga (goals RAPM), cf/ca."""
    xg_ = (res.get("xg") or {}).get("players") or {}
    gf_ = (res.get("gf") or {}).get("players") or {}
    cf_ = (res.get("cf") or {}).get("players") or {}
    rows = []
    for p, v in xg_.items():
        g = gf_.get(p) or {}
        c = cf_.get(p) or {}
        rows.append({"player_id": int(p), "off": v["o"], "def": v["d"], "net": v["t"], "off_se": v["se_o"],
                     "def_se": v["se_d"], "net_se": v["se"], "toi5": v["toi"], "gf": g.get("o"), "ga": g.get("d"),
                     "g_net": g.get("t"), "cf": c.get("o"), "ca": c.get("d"), "c_net": c.get("t")})
    return pd.DataFrame(rows).sort_values("net", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models.shooting import frame_rows
    res = chain(season, use_cache)
    if not res.get("ok"):
        return res
    t = player_rows(res)
    meta = {k: {kk: (res.get(k) or {}).get(kk) for kk in ("ridge", "cv", "controls", "controls_se", "sigma", "n_rows",
                                                           "n_players", "league_rate")} for k in TARGETS}
    gl = [{"player_id": int(g[1:]), "gsa_rapm": v["d"], "se": v["se_d"]} for g, v in ((res.get("gf") or {}).get("goalies") or {}).items()]
    return {"ok": True, "season": res["season"], "units": "per 60 at 5v5 (xG, goals, shot attempts)",
            "players": frame_rows(t) if len(t) else {"cols": [], "rows": []}, "goalies": gl, "fits": meta}


def export_fits(season: int | None = None) -> dict:
    """Commit the last completed season's estimates as the next season's prior (models/fitted/rapm_prior.json)."""
    seasons = _io.seasons_on_disk(need_stints=True)
    if not seasons:
        return {"ok": False, "reason": "no stints on disk"}
    season = _io.sid(season) if season else seasons[-1]
    res = chain(season)
    if not res.get("ok"):
        return res
    out = {"version": MODEL_VERSION, "season": season, "key": res.get("key")}
    for t in TARGETS:
        r = res.get(t) or {}
        out[t] = {"players": {p: {"o": round(v["o"], 5), "d": round(v["d"], 5)} for p, v in (r.get("players") or {}).items()},
                  "goalies": {g: {"d": round(v["d"], 5)} for g, v in (r.get("goalies") or {}).items()},
                  "ridge": r.get("ridge")}
    _io.write_fit("rapm_prior", out)
    return {"ok": True, "season": season, "players": len(out["xg"]["players"])}
