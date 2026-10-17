"""
Expected goals (xG) for unblocked shot attempts (goals, shots on goal, missed shots).

Rows: every unblocked attempt with coordinates outside the shootout and penalty shots (fewer than three
skaters on the ice in total). Label: goal.

Features (all from the shooting team's frame: x, y normalised so it attacks +x towards the net at (89, 0)):
  distance, angle (degrees off the goal line normal; > 90 behind the net), x, |y|, shot type (categorical),
  rebound (previous event an attempt by the same team within 3 s) and the angle change on it, rush (previous
  event in the neutral or defensive zone within 4 s), seconds and feet since the previous event, its speed,
  its type (categorical) and x, skaters for and against, empty net (no goalie in the defending net), score
  state (shooter's lead, clipped to +-3), home, period and game seconds, and the shooter's handedness as
  hand_y = y for a left shot, -y for a right shot (positive = shooting from his off wing; NaN when unknown).

Arena adjustment (`arena_adjust`): coordinates before 2023-24 (_io.TRACKING_FIRST) carry rink-specific biases.
Schuckers-style quantile matching per arena-season: the distances of all attempts in a team's home games are
mapped through their empirical CDF onto the quantiles of the distances in the same team's road games (the same
team's shots and its opponents', recorded by other rinks' scorers), two passes so the reference rinks are
themselves adjusted; the angle is kept and (x, y) recomputed at the new distance. Seasons from 2023-24 are left
alone; the bias table is reported for every season. The cut-off is read from that table: the spread of arenas'
home/road distance ratios is ~0.07 (sd) through 2021-22 and 0.04 in 2022-23, despite the NHL's 2020-21 tracking
roll-out, and reaches the sampling-noise floor (~0.025) only in 2023-24.

Model: LightGBM binary, cross-fitted by season (each season predicted by a model that never saw it; by game
with fewer than three seasons), early-stopped on a 10% game holdout of the training folds, then Platt
recalibration (a + b logit p) fitted on the pooled out-of-fold predictions. The production model is refitted
on every season at the folds' mean best iteration; `event_xg(season)` returns the cross-fitted xG for a season in
the fit and the production model's otherwise.

Benchmark (`benchmark_moneypuck`): MoneyPuck's xGoal on the same shots (matched on game, period, second and
shooter) — log-loss and AUC on the matched shots, and team-season and player-season correlation of summed xG.
MoneyPuck's model was trained on earlier seasons, so on those its numbers are in-sample (as reported).
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io

MODEL_VERSION = "nhlxg-3"            # 3: arena adjustment through 2022-23 (_io.TRACKING_FIRST 20232024)
FEATURES = ["distance", "angle", "x", "abs_y", "shot_type_code", "rebound", "rebound_angle", "rush", "dt_prev",
            "dist_prev", "speed_prev", "prev_type_code", "prev_x", "sk_for", "sk_against", "empty_net", "score_state",
            "is_home", "period", "sec", "hand_y"]
CATEGORICAL = ["shot_type_code", "prev_type_code"]
PARAMS = {"learning_rate": 0.04, "num_leaves": 31, "min_data_in_leaf": 300, "lambda_l2": 10.0, "feature_fraction": 0.85,
          "max_cat_to_onehot": 16, "cat_smooth": 20.0}
ROUNDS = 1500
K_FOLDS = 5
REBOUND_S = 3.0
RUSH_S = 4.0
ARENA_Q = np.linspace(0.01, 0.99, 99)
ARENA_PASSES = 2
ARENA_MIN_SHOTS = 300
DANGER = (0.08, 0.20)               # low < 0.08 <= medium < 0.20 <= high (MoneyPuck's bands)


# ============================================================================ geometry and the arena adjustment

def geometry(x, y) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    dx = _io.GOAL_X - x
    return np.hypot(dx, y), np.degrees(np.arctan2(np.abs(y), dx))


def _qmap(vals: np.ndarray, src_q: np.ndarray, ref_q: np.ndarray) -> np.ndarray:
    """Quantile matching with linear extrapolation by the end offsets."""
    sq, rq = np.maximum.accumulate(src_q), np.maximum.accumulate(ref_q)
    out = np.interp(vals, sq, rq)
    lo, hi = vals < sq[0], vals > sq[-1]
    out[lo] = vals[lo] * (rq[0] / sq[0] if sq[0] > 0 else 1.0)
    out[hi] = vals[hi] + (rq[-1] - sq[-1])
    return np.maximum(out, 0.5)


def arena_maps(dist: np.ndarray, game_ids: np.ndarray, home: np.ndarray, away: np.ndarray,
               passes: int = ARENA_PASSES, min_shots: int = ARENA_MIN_SHOTS) -> tuple[np.ndarray, dict]:
    """Adjusted distances and {arena: {"n", "ratio_before", "ratio_after"}} for one season's attempts.
    `home` is each attempt's arena (the home team's rink; neutral-site games carry their own label and stay
    unadjusted), `away` the road team, whose road games are the reference sample of the rink named after it."""
    d = np.asarray(dist, float).copy()
    home = np.asarray(home, object)
    away = np.asarray(away, object)
    arenas = [a for a in pd.unique(home) if a is not None]
    before = {}
    for a in arenas:
        ina, road = home == a, away == a
        if ina.sum() >= min_shots and road.sum() >= min_shots:
            before[a] = float(np.median(d[ina]) / np.median(d[road]))
    for _ in range(passes):
        new = d.copy()
        for a in arenas:
            ina, road = home == a, away == a
            if ina.sum() < min_shots or road.sum() < min_shots:
                continue
            new[ina] = _qmap(d[ina], np.quantile(d[ina], ARENA_Q), np.quantile(d[road], ARENA_Q))
        d = new
    info = {}
    for a in arenas:
        ina, road = home == a, away == a
        if a in before:
            info[str(a)] = {"n": int(ina.sum()), "ratio_before": before[a],
                            "ratio_after": float(np.median(d[ina]) / np.median(d[road]))}
    return d, info


def arena_adjust(sh: pd.DataFrame, season: int, force: bool | None = None) -> tuple[pd.DataFrame, dict]:
    """Adds x_adj, y_adj (and distance/angle from them) to an attempts frame of one season. Applied to
    seasons before tracking (or when `force`); the bias table is computed either way."""
    dist, ang = geometry(sh["x"], sh["y"])  # raw (scorer-recorded) coordinates
    ok = np.isfinite(dist)
    adj_d = dist.copy()
    apply = (_io.sid(season) < _io.TRACKING_FIRST) if force is None else bool(force)
    info: dict = {}
    arena = sh["home_team"].to_numpy(object).copy()
    road = sh["away_team"].to_numpy(object)
    try:
        g = _io.games(season)
        neutral = set(g.loc[g["neutral"].fillna(False).astype(bool), "game_id"].tolist()) if "neutral" in g else set()
    except Exception:  # noqa: BLE001
        neutral = set()
    if neutral:
        isn = np.isin(sh["game_id"].to_numpy(), list(neutral))
        arena[isn] = np.array([f"neutral:{x}" for x in sh["game_id"].to_numpy()[isn]], dtype=object)
    if ok.sum():
        ad, info = arena_maps(dist[ok], sh["game_id"].to_numpy()[ok], arena[ok], road[ok])
        if apply:
            adj_d[ok] = ad
    a = np.radians(ang)
    sgn = np.where(sh["y"].to_numpy(float) < 0, -1.0, 1.0)
    out = sh.copy()
    out["x_adj"] = np.where(ok, _io.GOAL_X - adj_d * np.cos(a), sh["x"].to_numpy(float))
    out["y_adj"] = np.where(ok, sgn * adj_d * np.sin(a), sh["y"].to_numpy(float))
    bias = [abs(np.log(v["ratio_before"])) for v in info.values()]
    after = [abs(np.log(v["ratio_after"])) for v in info.values()]
    return out, {"applied": apply, "arenas": info,
                 "mean_abs_log_ratio_before": float(np.mean(bias)) if bias else None,
                 "mean_abs_log_ratio_after": float(np.mean(after)) if after and apply else None}


# ============================================================================ features

def _flip_zone(z: np.ndarray) -> np.ndarray:
    return np.where(z == "O", "D", np.where(z == "D", "O", z))


def attempts(ev: pd.DataFrame, season: int | None = None, adjust: bool | None = None) -> tuple[pd.DataFrame, dict]:
    """Model rows (unblocked attempts) with features, label `goal` and keys (game_id, idx), from one season's
    canonical events. Returns (frame, arena info)."""
    if ev is None or not len(ev):
        return pd.DataFrame(columns=["game_id", "idx", "goal", *FEATURES]), {}
    season = _io.sid(season or int(ev["season"].iloc[0]))
    e = ev[ev["type"].notna() & (ev["shootout"] == 0)].reset_index(drop=True)
    g = e["game_id"].to_numpy()
    per = e["period"].to_numpy(float)
    same = np.r_[False, (g[1:] == g[:-1]) & (per[1:] == per[:-1])]
    team = e["team"].to_numpy(object)
    prev = lambda a: np.r_[a[:1], a[:-1]]  # noqa: E731 - shift by one row (no arrays captured)
    pteam = prev(team)
    sameteam = same & (pteam == team)
    ptype = np.where(same, prev(e["type"].to_numpy(object)), None)
    psec = np.where(same, prev(e["sec"].to_numpy(float)), np.nan)
    px = prev(e["x"].to_numpy(float))
    py = prev(e["y"].to_numpy(float))
    px = np.where(same, np.where(sameteam, px, -px), np.nan)
    py = np.where(same, np.where(sameteam, py, -py), np.nan)
    pz = prev(e["zone"].to_numpy(object))
    pz = np.where(same, np.where(sameteam, pz, _flip_zone(pz)), None)
    m = e["type"].isin(_io.UNBLOCKED).to_numpy() & np.isfinite(e["x"].to_numpy(float)) & np.isfinite(e["y"].to_numpy(float))
    ih = e["is_home"].to_numpy(float)
    skf = np.where(ih == 1, e["sk_h"], e["sk_a"]).astype(float)
    ska = np.where(ih == 1, e["sk_a"], e["sk_h"]).astype(float)
    m &= ((skf + ska) >= 3) & (e["penalty_shot"].to_numpy(float) != 1)
    sh = e.loc[m, ["season", "game_id", "idx", "period", "sec", "type", "team", "home_team", "away_team", "is_home", "x", "y",
                   "shot_type", "shooter", "goalie", "assist1", "assist2", *_io.SLOTS_H, *_io.SLOTS_A, "hg", "ag",
                   "sk_h", "sk_a", "g_h", "g_a", "score_h", "score_a"]].copy()
    idx = np.flatnonzero(m)
    sh, ainfo = arena_adjust(sh, season, adjust)
    d, a = geometry(sh["x_adj"], sh["y_adj"])
    X = pd.DataFrame(index=sh.index)
    X["distance"] = d
    X["angle"] = a
    X["x"] = sh["x_adj"].to_numpy(float)
    X["abs_y"] = np.abs(sh["y_adj"].to_numpy(float))
    stc = {t: i for i, t in enumerate(_io.SHOT_TYPES)}
    X["shot_type_code"] = sh["shot_type"].map(lambda v: stc.get(v, len(stc)) if v is not None else np.nan).astype(float)
    dt = sh["sec"].to_numpy(float) - psec[idx]
    pt = ptype[idx]
    is_att = np.isin(pt.astype(str), list(_io.ATTEMPTS))
    reb = sameteam[idx] & is_att & (dt <= REBOUND_S)
    X["rebound"] = reb.astype(float)
    ang_now = np.degrees(np.arctan2(sh["y"].to_numpy(float), _io.GOAL_X - sh["x"].to_numpy(float)))
    ang_prev = np.degrees(np.arctan2(py[idx], _io.GOAL_X - px[idx]))
    X["rebound_angle"] = np.where(reb, np.abs(ang_now - ang_prev), 0.0)
    X["rush"] = (np.isin(pz[idx].astype(str), ["N", "D"]) & (dt <= RUSH_S)).astype(float)
    X["dt_prev"] = dt
    dp = np.hypot(sh["x"].to_numpy(float) - px[idx], sh["y"].to_numpy(float) - py[idx])
    X["dist_prev"] = dp
    X["speed_prev"] = dp / np.maximum(dt, 1.0)
    X["prev_type_code"] = np.array([_io.TYPE_CODE.get(t, len(_io.TYPE_CODE)) if t is not None else np.nan for t in pt], float)
    X["prev_x"] = px[idx]
    X["sk_for"] = skf[idx]
    X["sk_against"] = ska[idx]
    ga = np.where(ih[idx] == 1, sh["g_a"], sh["g_h"]).astype(float)
    X["empty_net"] = (ga == 0).astype(float)
    sf = np.where(ih[idx] == 1, sh["score_h"] - sh["score_a"], sh["score_a"] - sh["score_h"]).astype(float)
    X["score_state"] = np.clip(sf, -3, 3)
    X["is_home"] = ih[idx]
    X["period"] = np.minimum(sh["period"].to_numpy(float), 4)
    X["sec"] = sh["sec"].to_numpy(float)
    try:
        hand = _io.players(season)["shoots"]
        sgn = sh["shooter"].map(lambda p: {"L": 1.0, "R": -1.0}.get(hand.get(int(p)) if p == p else None, np.nan)).to_numpy(float)
    except Exception:  # noqa: BLE001
        sgn = np.full(len(sh), np.nan)
    X["hand_y"] = sgn * sh["y_adj"].to_numpy(float)
    sh = sh.rename(columns={"x": "x_raw"})
    sh = sh.drop(columns=[c for c in FEATURES if c in sh.columns])
    out = pd.concat([sh.reset_index(drop=True), X[FEATURES].reset_index(drop=True).astype("float32")], axis=1)
    out["goal"] = (out["type"] == "goal").astype(float)
    return out, ainfo


def _season_rows(season: int) -> tuple[pd.DataFrame, dict]:
    ev = _io.events(season)
    if not len(ev):
        return pd.DataFrame(), {}
    return attempts(ev, season)


# ============================================================================ fit, predict, validate

EN_PRIOR = np.array([1.2, -0.02, -0.01])   # empty-net logistic prior centre (intercept, distance, angle)


def _en_design(X: pd.DataFrame) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X["distance"].to_numpy(float), X["angle"].to_numpy(float)])


def en_fit(X: pd.DataFrame, y: np.ndarray, ridge: float = 5.0) -> list[float]:
    """Empty-net shots: a small ridge logistic (intercept, distance, angle) shrunk to EN_PRIOR; boosted trees
    see too few of them."""
    Z = _en_design(X)
    y = np.asarray(y, float)
    b = EN_PRIOR.copy()
    R = np.diag([ridge / 100.0, ridge, ridge])
    for _ in range(50):
        mu = _io.sigmoid(Z @ b)
        g = Z.T @ (y - mu) - R @ (b - EN_PRIOR)
        H = Z.T @ (Z * (mu * (1 - mu))[:, None]) + R
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return [float(v) for v in b]


def en_predict(coef, X: pd.DataFrame) -> np.ndarray:
    return _io.sigmoid(_en_design(X) @ np.asarray(coef if coef is not None else EN_PRIOR, float))


def predict_raw(fit: dict, X: pd.DataFrame) -> np.ndarray:
    """Calibrated xG: the boosted model for shots on a manned net, the empty-net logistic otherwise."""
    p = _io.apply_platt(_io.lgb_predict(fit["models"]["main"], X[FEATURES]), fit.get("platt"))
    en = X["empty_net"].to_numpy(float) == 1
    if en.any():
        p[en] = en_predict(fit.get("empty_net"), X.loc[en])
    return p


def summary(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    base = np.full(len(y), y.mean()) if len(y) else y
    return {"n": int(len(y)), "goals": float(y.sum()), "xg": float(p.sum()), "log_loss": _io.log_loss(y, p),
            "log_loss_base": _io.log_loss(y, base), "auc": _io.auc(y, p), "brier": _io.brier(y, p)}


def validate(t: pd.DataFrame, p: np.ndarray) -> dict:
    y = t["goal"].to_numpy(float)
    out = {"overall": summary(y, p), "calibration": _io.calibration(y, p), "by_season": {}, "by_strength": {}}
    s = t["season"].to_numpy(int)
    for v in np.unique(s):
        m = s == v
        out["by_season"][str(v)] = summary(y[m], p[m])
    skf, ska, en = t["sk_for"].to_numpy(float), t["sk_against"].to_numpy(float), t["empty_net"].to_numpy(float)
    groups = {"5v5": (skf == 5) & (ska == 5) & (en == 0), "pp": (skf > ska) & (en == 0), "pk": (skf < ska) & (en == 0),
              "empty_net": en == 1}
    for k, m in groups.items():
        out["by_strength"][k] = summary(y[m], p[m]) | {"calibration_ece": _io.calibration(y[m], p[m])["ece"]}
    return out


def fit(seasons=None, k: int = K_FOLDS, use_cache: bool = True, rounds: int = ROUNDS) -> dict:
    """Cross-fit and refit on `seasons` (all on disk by default). Writes per-season out-of-fold xG to the
    cache (`xg_oof/<season>.parquet`) and the fit to the cache."""
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[_io.events_path(s) for s in seasons], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("xg", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    parts, arenas = [], {}
    for s in seasons:
        r, ai = _season_rows(s)
        if len(r):
            parts.append(r[["season", "game_id", "idx", "goal", *FEATURES]])
            arenas[str(s)] = ai
        del r
    if not parts:
        return {"version": MODEL_VERSION, "ok": False, "reason": "no events on disk"}
    t = pd.concat(parts, ignore_index=True)
    del parts
    y = t["goal"].to_numpy(float)
    folds = _io.fold_ids(t["season"].to_numpy(int), t["game_id"].to_numpy(), k)
    en = t["empty_net"].to_numpy(float) == 1
    oof_raw = np.full(len(t), np.nan)
    mn = ~en
    oof_raw[mn], infos = _io.crossfit(t.loc[mn, FEATURES], y[mn], folds[mn], t["game_id"].to_numpy()[mn], "binary", PARAMS,
                                      rounds, CATEGORICAL)
    ok = np.isfinite(oof_raw) & mn
    ab = _io.platt(y[ok], oof_raw[ok]) if ok.sum() > 1000 else (0.0, 1.0)
    oof = _io.apply_platt(oof_raw, ab)
    for f_ in np.unique(folds[en]):                      # empty net: cross-fitted logistic
        te = en & (folds == f_)
        tr = en & (folds != f_)
        oof[te] = en_predict(en_fit(t.loc[tr], y[tr]) if tr.sum() >= 20 else None, t.loc[te])
    oof_raw[en] = oof[en]
    en_coef = en_fit(t.loc[en], y[en]) if en.sum() >= 20 else list(EN_PRIOR)
    best = int(np.mean([i["best_iter"] for i in infos])) if infos else 300
    model, _ = _io.fit_full(t.loc[mn, FEATURES], y[mn], "binary", PARAMS, rounds=best, categorical=CATEGORICAL)
    fitd = {"version": MODEL_VERSION, "ok": True, "key": key, "seasons": [int(s) for s in seasons], "features": FEATURES,
            "platt": list(ab), "empty_net": en_coef, "best_iter": best, "folds": infos, "models": {"main": model},
            "importance": _io.importances(model, FEATURES), "arena": arenas,
            "validation": validate(t, oof), "validation_uncalibrated": summary(y, oof_raw)}
    for s in np.unique(t["season"].to_numpy(int)):
        m = t["season"].to_numpy(int) == s
        o = pd.DataFrame({"game_id": t["game_id"].to_numpy()[m], "idx": t["idx"].to_numpy()[m],
                          "xg": oof[m].astype("float32")})
        _write_oof(int(s), o, key)
    _io.store_fit("xg", fitd)
    del t
    return fitd


def _oof_path(season: int) -> Path:
    return _io.cache_root() / "xg_oof" / f"{_io.sid(season)}.parquet"


def _write_oof(season: int, o: pd.DataFrame, key: str) -> None:
    p = _oof_path(season)
    p.parent.mkdir(parents=True, exist_ok=True)
    o.to_parquet(p, index=False)
    p.with_suffix(".key").write_text(key)


def current_fit() -> dict | None:
    return _io.get_fit("xg", MODEL_VERSION)


def shots(season: int, ev: pd.DataFrame | None = None) -> pd.DataFrame:
    """Unblocked attempts of one season with features and `xg` (cross-fitted when the season was in the fit and
    the events are unchanged, else the production model). Empty frame without a fit."""
    season = _io.sid(season)
    ev = _io.events(season) if ev is None else ev
    t, _ = attempts(ev, season)
    if not len(t):
        return t.assign(xg=np.array([], float))
    f = current_fit()
    p = _oof_path(season)
    o = None
    if f is not None and p.exists() and p.with_suffix(".key").exists():
        try:
            if p.with_suffix(".key").read_text().strip() == f.get("key"):
                o = pd.read_parquet(p)
        except (OSError, ValueError):
            o = None
    if o is not None and len(o):
        t = t.merge(o, on=["game_id", "idx"], how="left")
        miss = t["xg"].isna().to_numpy()
        if miss.any() and f is not None:
            t.loc[miss, "xg"] = predict_raw(f, t.loc[miss])
    elif f is not None and f.get("models"):
        t["xg"] = predict_raw(f, t)
    else:
        t["xg"] = np.nan
    t["danger"] = np.where(t["xg"] >= DANGER[1], "high", np.where(t["xg"] >= DANGER[0], "medium", "low"))
    return t


def event_xg(season: int, ev: pd.DataFrame | None = None) -> pd.DataFrame:
    """game_id, idx, xg for one season's unblocked attempts."""
    s = shots(season, ev)
    return s[["game_id", "idx", "xg"]] if len(s) else pd.DataFrame(columns=["game_id", "idx", "xg"])


SHOT_COLS = ["season", "game_id", "idx", "period", "sec", "type", "team", "home_team", "away_team", "is_home", "x_raw", "y",
             "x_adj", "y_adj", "shot_type", "shooter", "goalie", "hg", "ag", "assist1", "assist2", "sk_for", "sk_against",
             "empty_net", "score_state", "rebound", "rush", "distance", "angle", "goal", "xg", "danger"]


def shot_table(season: int, use_cache: bool = True) -> pd.DataFrame:
    """Cached shot table of one season (SHOT_COLS): the input of shooting, goalies and stabilise."""
    season = _io.sid(season)
    f = current_fit() or {}
    key = _io.file_key(_io.events_path(season), _io.store_path(season), MODEL_VERSION, f.get("key"), f.get("platt"))
    return _io.cached_frame("xg_shots", str(season), key, lambda: _shot_cols(season), use_cache)


def _shot_cols(season: int) -> pd.DataFrame:
    s = shots(season)
    return s[[c for c in SHOT_COLS if c in s]] if len(s) else pd.DataFrame(columns=SHOT_COLS)


def for_season(season: int, use_cache: bool = True) -> dict:
    """{"ok", "season", "shots": DataFrame (SHOT_COLS: game_id, idx, xg, goal, ...), "validation" (this season,
    cross-fitted), "benchmark" (v MoneyPuck when its file is on disk), "arena"}."""
    season = _io.sid(season)
    if not _io.events_path(season).exists():
        return {"ok": False, "reason": "no events for this season"}
    f = current_fit()
    if f is None:
        return {"ok": False, "reason": "xG model not fitted"}
    sh = shot_table(season, use_cache)
    if not len(sh):
        return {"ok": False, "reason": "no shots"}
    key = _io.file_key(_io.events_path(season), *moneypuck_files(season), MODEL_VERSION, f.get("key"))
    bench = _io.cached("xg_bench", str(season), key, lambda: _io.clean(benchmark_moneypuck(season, sh), 6), use_cache)
    val = (f.get("validation") or {}).get("by_season", {}).get(str(season))
    return {"ok": True, "season": season, "shots": sh, "validation": val, "benchmark": bench,
            "arena": (f.get("arena") or {}).get(str(season)), "model": {"version": MODEL_VERSION, "seasons": f.get("seasons")}}


def score_events(ev: pd.DataFrame) -> np.ndarray:
    """xG aligned to any events frame keyed by game_id and the per-game index `idx` (builder C / D's normalised
    events): NaN for rows that are not unblocked attempts or seasons without xG."""
    gid = pd.to_numeric(ev["game_id"], errors="coerce")
    out = np.full(len(ev), np.nan)
    if "idx" not in ev:
        return out
    key = pd.DataFrame({"game_id": gid.to_numpy(), "idx": pd.to_numeric(ev["idx"], errors="coerce").to_numpy(),
                        "_r": np.arange(len(ev))})
    for s in pd.unique(gid.dropna().astype("int64").map(_io.season_of_game)):
        if not _io.events_path(int(s)).exists() or current_fit() is None:
            continue
        sh = shot_table(int(s))[["game_id", "idx", "xg"]]
        m = key.merge(sh, on=["game_id", "idx"], how="inner")
        out[m["_r"].to_numpy()] = m["xg"].to_numpy(float)
    return out


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    if f.get("ok"):
        _io.export_fit("xg", f)
    return {k: v for k, v in f.items() if k != "models"}


# ============================================================================ MoneyPuck benchmark

MP_COLS = ["season", "game_id", "period", "time", "shooterPlayerId", "xGoal", "goal", "event", "teamCode", "isHomeTeam",
           "homeTeamCode", "awayTeamCode", "shotOnEmptyNet", "xCordAdjusted", "yCordAdjusted", "isPlayoffGame", "nhl_game_id"]


def moneypuck_files(season: int) -> list[Path]:
    root = _io.raw_root() / "moneypuck"
    if not root.exists():
        return []
    full = str(_io.sid(season))
    y0 = full[:4]
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".csv", ".zip", ".parquet", ".gz")]
    hit = [p for p in files if full in p.name]
    if not hit:          # start-year names (MoneyPuck's own: shots_2023.zip)
        hit = [p for p in files if "".join(ch for ch in p.stem if ch.isdigit()) == y0]
    return sorted(hit)


def load_moneypuck(season: int) -> pd.DataFrame:
    """MoneyPuck shots for one season (benchmark only; "Data from MoneyPuck.com"), with our full game id."""
    frames = []
    for p in moneypuck_files(season):
        try:
            if p.suffix.lower() == ".parquet":
                df = pd.read_parquet(p)
            elif p.suffix.lower() == ".zip":
                with zipfile.ZipFile(p) as z:
                    name = next(n for n in z.namelist() if n.endswith(".csv"))
                    df = pd.read_csv(io.BytesIO(z.read(name)), usecols=lambda c: c in MP_COLS, low_memory=False)
            else:
                df = pd.read_csv(p, usecols=lambda c: c in MP_COLS, low_memory=False)
        except Exception:  # noqa: BLE001
            continue
        frames.append(df[[c for c in MP_COLS if c in df]])
    if not frames:
        return pd.DataFrame(columns=MP_COLS)
    mp = pd.concat(frames, ignore_index=True)
    s = pd.to_numeric(mp["season"], errors="coerce")
    gid = pd.to_numeric(mp["game_id"], errors="coerce")
    mp["gid"] = np.where(gid < 1_000_000, s * 1_000_000 + gid, gid).astype("int64")
    if "nhl_game_id" in mp:
        ng = pd.to_numeric(mp["nhl_game_id"], errors="coerce")
        mp["gid"] = np.where(ng.notna(), ng, mp["gid"]).astype("int64")
    mp = mp[(s == _io.sid(season) // 10000)]
    return mp.drop_duplicates(["gid", "period", "time", "shooterPlayerId", "event"])


def benchmark_moneypuck(season: int, sh: pd.DataFrame | None = None) -> dict:
    """Ours (cross-fitted) v MoneyPuck xGoal on matched unblocked attempts of one season."""
    mp = load_moneypuck(season)
    if not len(mp):
        return {"ok": False, "reason": "no MoneyPuck file on disk"}
    sh = shot_table(season) if sh is None else sh
    if not len(sh) or sh["xg"].isna().all():
        return {"ok": False, "reason": "no xG"}
    a = sh[["game_id", "period", "sec", "shooter", "team", "goal", "xg", "empty_net"]].copy()
    a["t"] = np.round(a["sec"].to_numpy(float)).astype("int64")
    a["shooter"] = pd.to_numeric(a["shooter"], errors="coerce")
    b = pd.DataFrame({"game_id": mp["gid"].to_numpy(), "period": pd.to_numeric(mp["period"], errors="coerce"),
                      "t": pd.to_numeric(mp["time"], errors="coerce").round().astype("Int64"),
                      "shooter": pd.to_numeric(mp["shooterPlayerId"], errors="coerce"),
                      "mp_xg": pd.to_numeric(mp["xGoal"], errors="coerce"),
                      "mp_goal": pd.to_numeric(mp["goal"], errors="coerce"),
                      "mp_team": mp["teamCode"].astype(str).to_numpy()})
    b = b.dropna(subset=["t", "shooter", "mp_xg"])
    b["t"] = b["t"].astype("int64")
    b = b.drop_duplicates(["game_id", "period", "t", "shooter"], keep=False)
    a = a.drop_duplicates(["game_id", "period", "t", "shooter"], keep=False)
    m = a.merge(b, on=["game_id", "period", "t", "shooter"], how="inner")
    m = m[np.isfinite(m["xg"].to_numpy(float))]
    if len(m) < 100:
        return {"ok": False, "reason": f"only {len(m)} matched shots", "n_ours": int(len(sh)), "n_mp": int(len(mp))}
    y = m["goal"].to_numpy(float)
    out = {"ok": True, "season": _io.sid(season), "n_ours": int(len(sh)), "n_mp": int(len(mp)), "n_matched": int(len(m)),
           "label_agreement": float(np.mean(y == m["mp_goal"].to_numpy(float))),
           "ours": summary(y, m["xg"].to_numpy(float)), "moneypuck": summary(y, m["mp_xg"].to_numpy(float)),
           "shot_corr": _io.pearson(m["xg"], m["mp_xg"])}
    ne = m["empty_net"].to_numpy(float) == 0
    out["ours_non_empty_net"] = summary(y[ne], m["xg"].to_numpy(float)[ne])
    out["moneypuck_non_empty_net"] = summary(y[ne], m["mp_xg"].to_numpy(float)[ne])
    tm = m.groupby("team")[["xg", "mp_xg", "goal"]].sum()
    out["team_season"] = {"n": int(len(tm)), "r_ours_mp": _io.pearson(tm["xg"], tm["mp_xg"]),
                          "r_ours_goals": _io.pearson(tm["xg"], tm["goal"]), "r_mp_goals": _io.pearson(tm["mp_xg"], tm["goal"])}
    pl = m.groupby("shooter")[["xg", "mp_xg", "goal"]].sum()
    pl = pl[m.groupby("shooter").size() >= 50]
    out["player_season"] = {"n": int(len(pl)), "r_ours_mp": _io.pearson(pl["xg"], pl["mp_xg"]),
                            "r_ours_goals": _io.pearson(pl["xg"], pl["goal"]), "r_mp_goals": _io.pearson(pl["mp_xg"], pl["goal"])}
    return out
