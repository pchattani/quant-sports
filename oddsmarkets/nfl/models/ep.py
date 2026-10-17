"""
Expected points (EP), our own: a multinomial next-score model.

For every scrimmage play (downs 1-4) the label is the next score in the same half (overtime is its own
half), from the possession team's point of view, as one of seven classes

    TD (+7), FG (+3), safety (+2), no score (0), opp safety (-2), opp FG (-3), opp TD (-7)

(a touchdown is valued at 7: the try is a separate play). The scoring team is `td_team` on a touchdown,
the kicking side (`posteam`) on a made field goal and the defence on a safety. EP = sum_c p_c v_c.

Model: LightGBM multiclass on down, distance (and goal to go), yard line, seconds left in the half, the
half, score differential, both teams' timeouts, home, roof and era (season). Cross-fitted by season (5
folds of seasons dealt round-robin: every play is predicted by a model that never saw its season), with
early stopping on a 10% game holdout of the training seasons; the production model is refitted on every
completed season at the folds' mean best iteration and applied to the current season.

Validation (`validate`) on the same plays: multiclass log-loss of the next-score class and calibration
of the class probabilities and of EP (binned predicted EP against the realised next-score value), ours
(cross-fitted) against nflfastR's published class probabilities (`td_prob` ... `no_score_prob`) and `ep`.
nflfastR's model was fitted on 1999-2019 seasons, so its numbers on those seasons are in-sample;
the comparison is reported separately for 2020 onward.

`epa_ours(df)` turns our EP into EPA: EP after the play (the next scrimmage play's EP, sign-flipped on a
change of possession; the points on a scoring play; 0 at the end of a half) minus EP before.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "ep-1"
CLASSES = ["td", "fg", "safety", "none", "opp_safety", "opp_fg", "opp_td"]
VALUES = np.array([7.0, 3.0, 2.0, 0.0, -2.0, -3.0, -7.0])
NFLFASTR_COLS = ["td_prob", "fg_prob", "safety_prob", "no_score_prob", "opp_safety_prob", "opp_fg_prob", "opp_td_prob"]
FEATURES = ["down", "ydstogo", "goal_to_go", "yardline_100", "half_seconds_remaining", "half", "score_differential",
            "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home", "roof_code", "era"]
SCRIMMAGE = {"pass", "run", "punt", "field_goal", "no_play", "qb_kneel", "qb_spike"}
PARAMS = {"objective": "multiclass", "num_class": 7, "learning_rate": 0.1, "num_leaves": 63, "min_data_in_leaf": 400,
          "lambda_l2": 5.0, "feature_fraction": 0.9}
ROUNDS = 600
K_FOLDS = 5


# ============================================================================ labels and features

def half_of(qtr) -> np.ndarray:
    q = pd.to_numeric(pd.Series(qtr), errors="coerce").to_numpy(float)
    return np.where(q <= 2, 1.0, np.where(q <= 4, 2.0, 3.0))


def score_events(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(event class value 7/3/2 or 0, scoring team) per row: TD (td_team), made FG (posteam), safety (defteam).
    Tries (extra points, two-point attempts) are not events."""
    n = len(df)
    try_ = (df["play_type"].astype(str).to_numpy() == "extra_point")
    if "two_point_attempt" in df:
        try_ |= pd.to_numeric(df["two_point_attempt"], errors="coerce").fillna(0).to_numpy() == 1
    td = (pd.to_numeric(df.get("touchdown"), errors="coerce").fillna(0).to_numpy() == 1) & df["td_team"].notna().to_numpy() & ~try_
    fg = (df["field_goal_result"].astype(str).to_numpy() == "made") & ~try_
    sf = (pd.to_numeric(df.get("safety"), errors="coerce").fillna(0).to_numpy() == 1) & ~try_
    val = np.where(td, 7.0, np.where(fg, 3.0, np.where(sf, 2.0, 0.0)))
    team = np.where(td, df["td_team"].astype(object).to_numpy(),
                    np.where(fg, df["posteam"].astype(object).to_numpy(),
                             np.where(sf, df["defteam"].astype(object).to_numpy(), None)))
    return val, team


def next_score(df: pd.DataFrame) -> pd.DataFrame:
    """Adds `ns_class` (index into CLASSES) and `ns_value` per row; df must be sorted by game and play.
    Rows without a possession team get NaN."""
    val, team = score_events(df)
    g = df["game_id"].astype(str).to_numpy()
    h = half_of(df["qtr"])
    key = pd.Series(pd.factorize(pd.Series(g) + "_" + pd.Series(h).astype(str))[0])
    idx = pd.Series(np.where(val > 0, np.arange(len(df)), np.nan))
    nxt = idx.groupby(key).bfill().to_numpy()
    has = np.isfinite(nxt)
    j = np.where(has, nxt, 0).astype(int)
    v = np.where(has, val[j], 0.0)
    st = np.where(has, team[j], None)
    pos = df["posteam"].astype(object).to_numpy()
    same = np.array([a is not None and a == b for a, b in zip(st, pos)])
    signed = np.where(has, np.where(same, v, -v), 0.0)
    cls = np.select([signed == 7, signed == 3, signed == 2, signed == 0, signed == -2, signed == -3, signed == -7],
                    [0, 1, 2, 3, 4, 5, 6], default=3).astype(float)
    nopos = pd.isna(df["posteam"]).to_numpy()
    cls[nopos] = np.nan
    signed = signed.astype(float)
    signed[nopos] = np.nan
    df["ns_class"] = cls
    df["ns_value"] = signed
    return df


def is_model_play(df: pd.DataFrame) -> np.ndarray:
    d = pd.to_numeric(df["down"], errors="coerce").to_numpy(float)
    pt = df["play_type"].astype(str).to_numpy()
    yl = pd.to_numeric(df["yardline_100"], errors="coerce").to_numpy(float)
    tp = pd.to_numeric(df.get("two_point_attempt"), errors="coerce").fillna(0).to_numpy() if "two_point_attempt" in df else 0
    return (np.isin(d, [1, 2, 3, 4]) & np.isin(pt, list(SCRIMMAGE)) & (yl >= 1) & (yl <= 99)
            & df["posteam"].notna().to_numpy() & (tp != 1))


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Model features from a prepared play frame (or from synthetic states with the same columns)."""
    X = pd.DataFrame(index=df.index)
    X["down"] = pd.to_numeric(df["down"], errors="coerce").astype(float)
    X["ydstogo"] = pd.to_numeric(df["ydstogo"], errors="coerce").astype(float)
    yl = pd.to_numeric(df["yardline_100"], errors="coerce").astype(float)
    gtg = df["goal_to_go"] if "goal_to_go" in df else (X["ydstogo"] >= yl).astype(float)
    X["goal_to_go"] = pd.to_numeric(gtg, errors="coerce").astype(float)
    X["yardline_100"] = yl
    X["half_seconds_remaining"] = pd.to_numeric(df["half_seconds_remaining"], errors="coerce").astype(float)
    X["half"] = df["half"].astype(float) if "half" in df else half_of(df["qtr"])
    X["score_differential"] = pd.to_numeric(df["score_differential"], errors="coerce").astype(float)
    X["posteam_timeouts_remaining"] = pd.to_numeric(df["posteam_timeouts_remaining"], errors="coerce").astype(float)
    X["defteam_timeouts_remaining"] = pd.to_numeric(df["defteam_timeouts_remaining"], errors="coerce").astype(float)
    X["home"] = pd.to_numeric(df["home"], errors="coerce").astype(float) if "home" in df else np.nan
    X["roof_code"] = pd.to_numeric(df["roof_code"], errors="coerce").astype(float) if "roof_code" in df else np.nan
    X["era"] = pd.to_numeric(df["season"], errors="coerce").astype(float)
    return X[FEATURES]


def training_rows(d: pd.DataFrame) -> pd.DataFrame:
    """One season's labelled model plays: features + label + ids + nflfastR's columns for comparison."""
    d = d.sort_values(["game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    d = next_score(d)
    m = is_model_play(d)
    s = d[m]
    out = features(s).reset_index(drop=True)
    out["y"] = s["ns_class"].to_numpy()
    out["season"] = s["season"].to_numpy(float)
    out["game_id"] = s["game_id"].astype(str).to_numpy()
    out["play_id"] = s["play_id"].to_numpy(float)
    for c in ["ep", *NFLFASTR_COLS]:
        out[f"nf_{c}"] = pd.to_numeric(s[c], errors="coerce").to_numpy(float) if c in s else np.nan
    return out


# ============================================================================ fit / predict

def fit_table(t: pd.DataFrame, k: int = K_FOLDS, rounds: int = ROUNDS) -> tuple[dict, np.ndarray]:
    """Cross-fit on a training table then refit on all of it. Returns (fit, out-of-fold class probs)."""
    t = t[np.isfinite(t["y"].to_numpy(float))].reset_index(drop=True)
    X = t[FEATURES]
    y = t["y"].to_numpy(int)
    folds = _io.fold_ids(t["season"].to_numpy(int), t["game_id"].to_numpy(), k)
    oof, infos = _io.crossfit(X, y, folds, t["game_id"].to_numpy(), "multiclass", PARAMS, rounds=rounds, n_class=7)
    best = int(np.mean([i["best_iter"] for i in infos])) if infos else 200
    model, _ = _io.fit_full(X, y, "multiclass", PARAMS, rounds=best)
    seasons = sorted(set(int(s) for s in t["season"]))
    fit = {"ok": True, "version": MODEL_VERSION, "classes": CLASSES, "values": VALUES.tolist(), "features": FEATURES,
           "seasons": seasons, "n": int(len(t)), "best_iter": best, "folds": infos, "models": {"main": model},
           "importance": _io.importances(model, FEATURES)}
    return fit, oof


def predict_proba(fit: dict, df: pd.DataFrame) -> np.ndarray:
    X = features(df) if not set(FEATURES) <= set(df.columns) or "era" not in df else df[FEATURES]
    P = _io.lgb_predict(fit["models"]["main"], X)
    return P.reshape(len(X), -1) if len(X) else np.zeros((0, 7))


def ep_from_proba(P: np.ndarray) -> np.ndarray:
    return np.asarray(P, float) @ VALUES


def predict(fit: dict, df: pd.DataFrame) -> np.ndarray:
    """EP for each row of a play/state frame (columns as nflverse names, prepared)."""
    return ep_from_proba(predict_proba(fit, df))


# ============================================================================ validation

def compare(t: pd.DataFrame, P: np.ndarray) -> dict:
    """Ours (P) against nflfastR's class probabilities on the rows where both exist."""
    y = t["y"].to_numpy(int)
    nf = t[[f"nf_{c}" for c in NFLFASTR_COLS]].to_numpy(float)
    ok = np.isfinite(P).all(axis=1) & np.isfinite(nf).all(axis=1) & (nf.sum(axis=1) > 0.5)
    out = {"n": int(ok.sum())}
    if not ok.any():
        ok = np.isfinite(P).all(axis=1)
        out["n"] = int(ok.sum())
        out["ours"] = _summary(y[ok], P[ok], t["y"].to_numpy(float)[ok])
        return out
    out["ours"] = _summary(y[ok], P[ok])
    out["nflfastr"] = _summary(y[ok], nf[ok])
    ep_nf = t["nf_ep"].to_numpy(float)[ok]
    if np.isfinite(ep_nf).all():
        out["nflfastr"]["ep_calibration"] = _ep_cal(VALUES[y[ok]], ep_nf)
        out["nflfastr"]["ep_mse"] = float(np.mean((VALUES[y[ok]] - ep_nf) ** 2))
    out["ep_corr"] = _io.pearson(ep_from_proba(P[ok]), ep_nf)
    return out


def _summary(y: np.ndarray, P: np.ndarray, _unused=None) -> dict:
    P = P / P.sum(axis=1, keepdims=True)
    ep = ep_from_proba(P)
    v = VALUES[y]
    cls = {}
    for i, c in enumerate(CLASSES):
        cls[c] = {"mean_pred": round(float(P[:, i].mean()), 5), "obs": round(float((y == i).mean()), 5),
                  "ece": _io.calibration((y == i).astype(float), P[:, i], 20)["ece"]}
    return {"logloss": round(_io.mlog_loss(y, P), 5), "ep_mse": round(float(np.mean((v - ep) ** 2)), 4),
            "ep_calibration": _ep_cal(v, ep), "classes": cls}


def _ep_cal(v: np.ndarray, ep: np.ndarray) -> dict:
    """Binned EP (1-point bins from -3 to 7): mean predicted against mean realised next-score value."""
    b = np.clip(np.floor(ep), -3, 6)
    rows, err = [], 0.0
    for k in np.unique(b):
        m = b == k
        mp, mo = float(ep[m].mean()), float(v[m].mean())
        rows.append([float(k), round(mp, 3), round(mo, 3), int(m.sum())])
        err += m.sum() * abs(mp - mo)
    return {"bins": rows, "mae_weighted": round(err / max(len(v), 1), 4)}


def validate(t: pd.DataFrame, P: np.ndarray, split: int = 2020) -> dict:
    s = t["season"].to_numpy(int)
    out = {"all": compare(t, P)}
    for name, m in (("pre_%d" % split, s < split), ("from_%d" % split, s >= split)):
        if m.any():
            out[name] = compare(t[m].reset_index(drop=True), P[m])
    by = {}
    for yv in np.unique(s):
        m = s == yv
        c = compare(t[m].reset_index(drop=True), P[m])
        by[int(yv)] = {"n": c["n"], "ours": c.get("ours", {}).get("logloss"),
                       "nflfastr": (c.get("nflfastr") or {}).get("logloss")}
    out["by_season"] = by
    return out


# ============================================================================ EPA from our EP

def epa_ours(df: pd.DataFrame, ep_col: str = "ep_ours") -> np.ndarray:
    """EPA from our EP on a game/play-sorted frame: EP after (next scrimmage play's EP, flipped on a change
    of possession; points on a scoring play; 0 at the end of a half) minus EP before. NaN off model plays."""
    d = df
    ep = d[ep_col].to_numpy(float)
    m = is_model_play(d)
    val, team = score_events(d)
    pos = d["posteam"].astype(object).to_numpy()
    g = d["game_id"].astype(str).to_numpy()
    h = half_of(d["qtr"])
    idx = np.flatnonzero(m)
    out = np.full(len(d), np.nan)
    if not len(idx):
        return out
    nxt = np.append(idx[1:], -1)
    for a, b in ((idx, nxt),):
        valid_next = (b >= 0)
        bb = np.where(valid_next, b, 0)
        same_half = valid_next & (g[bb] == g[a]) & (h[bb] == h[a])
        same_pos = np.array([pos[i] == pos[j] for i, j in zip(a, bb)])
        after = np.where(same_half, np.where(same_pos, ep[bb], -ep[bb]), 0.0)
        scoring = val[a] > 0
        sgn = np.array([1.0 if team[i] == pos[i] else -1.0 for i in a])
        after = np.where(scoring, sgn * val[a], after)
        out[a] = after - ep[a]
    return out


# ============================================================================ pipeline

def _table(seasons) -> pd.DataFrame:
    return _io.stack(seasons, training_rows)


def fit(seasons=None, k: int = K_FOLDS, use_cache: bool = True) -> dict:
    """Cross-fit and refit on `seasons` (completed seasons on disk by default); writes per-season
    out-of-fold predictions to the cache (`ep_oof/<season>.parquet`) and the fit to the cache."""
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("ep", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    t = _table(seasons)
    fitd, oof = fit_table(t, k)
    fitd["key"] = key
    fitd["validation"] = validate(t, oof)
    for s in np.unique(t["season"].to_numpy(int)):
        m = t["season"].to_numpy(int) == s
        o = pd.DataFrame({"game_id": t["game_id"][m].to_numpy(), "play_id": t["play_id"][m].to_numpy()})
        for i, c in enumerate(CLASSES):
            o[f"p_{c}"] = oof[m, i].astype("float32")
        o["ep_ours"] = ep_from_proba(oof[m]).astype("float32")
        _write_oof(int(s), o, key)
    _io.store_fit("ep", fitd)
    del t, oof
    return fitd


def _oof_path(season: int):
    return _io.cache_root() / "ep_oof" / f"{int(season)}.parquet"


def _write_oof(season: int, o: pd.DataFrame, key: str) -> None:
    p = _oof_path(season)
    p.parent.mkdir(parents=True, exist_ok=True)
    o.to_parquet(p, index=False)
    p.with_suffix(".key").write_text(key)


def current_fit() -> dict | None:
    return _io.get_fit("ep", MODEL_VERSION)


def for_season(season: int, d: pd.DataFrame | None = None) -> pd.DataFrame:
    """game_id, play_id, p_<class>, ep_ours and epa_ours for one season's model plays: the cross-fitted
    prediction when this season was in the fit, else the production model's."""
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame(columns=["game_id", "play_id", "ep_ours", "epa_ours"])
    d = d.sort_values(["game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    p = _oof_path(season)
    o = None
    if p.exists():
        try:
            o = pd.read_parquet(p)
        except Exception:  # noqa: BLE001
            o = None
    if o is None:
        f = current_fit()
        if f is None:
            return pd.DataFrame(columns=["game_id", "play_id", "ep_ours", "epa_ours"])
        m = is_model_play(d)
        s = d[m]
        P = predict_proba(f, s)
        o = pd.DataFrame({"game_id": s["game_id"].astype(str).to_numpy(), "play_id": s["play_id"].to_numpy(float)})
        for i, c in enumerate(CLASSES):
            o[f"p_{c}"] = P[:, i]
        o["ep_ours"] = ep_from_proba(P)
    d2 = d.merge(o[["game_id", "play_id", "ep_ours"]], on=["game_id", "play_id"], how="left")
    o2 = d2[["game_id", "play_id"]].copy()
    o2["epa_ours"] = epa_ours(d2)
    return o.merge(o2, on=["game_id", "play_id"], how="left")


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("ep", f)
    return {k: v for k, v in f.items() if k != "models"}
