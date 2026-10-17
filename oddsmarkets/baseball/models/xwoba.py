"""
xwOBA+: expected wOBA per batted ball from how it was hit, how long it hung and where it was hit.

Savant's xwOBA uses exit velocity and launch angle (plus sprint speed on weakly hit balls). xwOBA+ uses,
per batted ball (BIP):

* exit velocity, launch angle and hang time from launch physics (`_c.flight`: drag plus backspin lift);
* the park: the venue's five fence distances (LF, LCF, CF, RCF, RF), mean wall height, elevation and roof
  from the store (the park as a category when the store has no dimensions);
* sprint speed from Savant's sprint-speed leaderboard (ft/s) on every ball, when builder A cached it.

Direction was tested and left out (SPRAY_MODE = "park_dims"; the other modes remain switchable). On the
predictive test below, every way of using a ball's own direction predicted next-period wOBA worse or no
better: the exact hit-coordinate angle, 15-degree bands, air balls only, the batter's cross-fitted
direction tendency, and the fence distance at the ball's angle. A ball's exact landing angle mostly
records whether it found a hole or a glove, which is placement luck. An outcome-based speed proxy
(ground-ball hit rate over expectation) also hurt and is off (USE_SPEED_PROXY). Strong regularisation
helped: leaves of >= 1,500 balls and 7 leaves per tree learn less luck. Pearson r with next-period wOBA,
hitters with >= MIN_PA (200) PA in the first period and >= MIN_PA_NEXT (100) in the next (Savant xwOBA / xwOBA+),
from the committed calibration (`checks.xwoba`, computed 1 October 2026): 2024 H1->H2 .408/.400, 2025 .471/.476,
2026 .237/.225, 2024 H2->2025 H1 .433/.439, 2025 H2->2026 H1 .337/.338. The direction tests above were run on an
earlier sample; quote the calibration file, which the Calibration page shows.

Model: LightGBM multiclass over {out, 1B, 2B, 3B, HR} (classes follow Savant's woba_value, so reaching
on an error or a fielder's choice is the single class, as Savant scores it), fitted per season with K-fold
cross-fitting by game (every BIP is predicted by a model that did not see it). Calibration: the class
probabilities are raked (iterative proportional scaling) so each class's mean probability equals its
observed share; with constant class weights this makes league xwOBA on contact equal league wOBA on
contact exactly. Weights per class are the season's own means of Savant's woba_value (so we sit on
Savant's scale); full xwOBA adds walks and HBP at their woba_value and strikeouts at 0 over the wOBA
denominator:

    xwOBA+ = (sum_BIP sum_c p_c w_c + sum_BB,HBP woba_value) / sum woba_denom

The park-neutral variant (`xwoba_n`) re-predicts every ball with league-standard park features
(fences 330/375/400/375/330, 8 ft walls, the median elevation, open roof); batting value uses it.

Validation (`predictive_test`): split each season at its median date; fit xwOBA+ on the first half
only; for hitters with >= MIN_PA PA in the first half and >= MIN_PA_NEXT in the second, correlate
first-half wOBA, Savant xwOBA and xwOBA+ with second-half wOBA (Pearson r and RMSE); also each
season's second half against the next season's first half.
"""
from __future__ import annotations

import gzip
import math

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "xwoba-3"
CLASSES = ["out", "1B", "2B", "3B", "HR"]
HIT_CLASS = {"single": 1, "double": 2, "triple": 3, "home_run": 4}
STD_DIMS = {"lf": 330.0, "lcf": 375.0, "cf": 400.0, "rcf": 375.0, "rf": 330.0}
STD_WALL = 8.0
DIM_ANGLES = [-45.0, -22.5, 0.0, 22.5, 45.0]
DIM_KEYS = ["lf", "lcf", "cf", "rcf", "rf"]
N_FOLDS = 3
# How a ball's direction enters: "park_dims" (not at all: the park enters as its five fence distances, mean wall
# height, elevation and roof; the default, chosen on the predictive test), "fence" (through the fence distance
# and wall height at the ball's angle), "exact" (the hit-coordinate angle itself), "air" (exact, air balls only),
# "band" (15-degree bands), "air_band", "tendency" (the batter's cross-fitted air-ball direction), "park_cat".
SPRAY_MODE = "park_dims"
SPRAY_BAND = 15.0
USE_SPEED_PROXY = False
SPEED_SHRINK_GB = 40.0
MIN_PA = 200
MIN_PA_NEXT = 100
LGB_PARAMS = {"objective": "multiclass", "num_class": 5, "learning_rate": 0.06, "num_leaves": 7,
              "min_data_in_leaf": 1500, "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1,
              "lambda_l2": 1.0, "verbose": -1, "num_threads": 8, "seed": 7}
N_ROUNDS = 250
COLUMNS = ["game_pk", "game_date", "at_bat_number", "pitch_number", "batter", "pitcher", "stand", "p_throws",
           "home_team", "away_team", "inning_topbot", "events", "description", "bb_type", "launch_speed",
           "launch_angle", "hc_x", "hc_y", "hit_distance_sc", "woba_value", "woba_denom",
           "estimated_woba_using_speedangle", "if_fielding_alignment", "of_fielding_alignment"]
FEATS_BASE = ["launch_speed", "launch_angle", "hang"]
FEATS_SPRAY = ["spray", "pull"]
FEATS_PARK = ["wall_dist", "wall_h", "elev", "roof"]
FEATS_PARK_DIMS = ["_d_lf", "_d_lcf", "_d_cf", "_d_rcf", "_d_rf", "wall_mean", "elev", "roof"]
FEATS_SPEED = ["speed"]


# ============================================================================ park lookup

def park_info(store: dict | None) -> tuple[dict, dict]:
    """(game_pk -> venue dict, team abbr -> venue dict) from a store."""
    if not store:
        return {}, {}
    venues = store.get("venues") or {}
    by_game = {}
    for gpk, g in (store.get("games") or {}).items():
        v = venues.get(str(g.get("venue"))) if g else None
        if v:
            by_game[int(gpk)] = v
    by_team = {}
    for tid, t in (store.get("teams") or {}).items():
        v = venues.get(str(t.get("venue")))
        if v and t.get("abbr"):
            by_team[str(t["abbr"])] = v
    return by_game, by_team


def _dims_vec(v: dict | None) -> np.ndarray:
    d = (v or {}).get("dims") or {}
    try:
        return np.array([float(d[k]) for k in DIM_KEYS])
    except (KeyError, TypeError, ValueError):
        return np.full(5, np.nan)


def _walls_vec(v: dict | None) -> np.ndarray:
    w = (v or {}).get("walls") or {}
    out = []
    for k in DIM_KEYS:
        x = w.get(k) if isinstance(w, dict) else None
        if isinstance(x, dict):
            x = x.get("h") or x.get("height")
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            out.append(STD_WALL)
    return np.array(out)


def _interp_rows(spray: np.ndarray, table: np.ndarray) -> np.ndarray:
    """Per-row linear interpolation of a (n, 5) table over the five fence angles."""
    s = np.clip(np.nan_to_num(spray, nan=0.0), -45, 45)
    j = np.clip(np.searchsorted(DIM_ANGLES, s, side="right") - 1, 0, 3)
    a0 = np.asarray(DIM_ANGLES)[j]
    w = (s - a0) / 22.5
    r = np.arange(len(s))
    return table[r, j] * (1 - w) + table[r, j + 1] * w


# ============================================================================ features

def batted_balls(pitches: pd.DataFrame) -> pd.DataFrame:
    """Rows of the pitch table that are balls in play ending a PA (wOBA-relevant events)."""
    ev = pitches["events"].astype(object).fillna("").astype(str)
    m = ev.isin(_c.BIP_EVENTS)
    if "description" in pitches:
        m &= pitches["description"].astype(str).str.startswith("hit_into_play") | pitches["description"].isna()
    if "woba_denom" in pitches and pd.to_numeric(pitches["woba_denom"], errors="coerce").notna().any():
        m &= pd.to_numeric(pitches["woba_denom"], errors="coerce").fillna(0).to_numpy() > 0     # sacrifice bunts are outside wOBA
    b = pitches[m].copy()
    cls = ev[m].map(HIT_CLASS).fillna(0).astype(int).to_numpy()
    if "woba_value" in b:
        # Savant credits reaching on an error or a fielder's choice at the single weight: classes follow woba_value
        wv = pd.to_numeric(b["woba_value"], errors="coerce").to_numpy()
        cls = np.where(np.isfinite(wv) & (wv <= 0), 0, np.where(np.isfinite(wv) & (wv > 0) & (cls == 0), 1, cls))
    b["cls"] = cls
    return b


def add_features(b: pd.DataFrame, store: dict | None = None, speed: dict | None = None,
                 spray_mode: str | None = None) -> pd.DataFrame:
    b = b.copy()
    mode = spray_mode or SPRAY_MODE
    mode = "exact" if mode in ("fence", "park_dims", "park_cat") else mode
    spray = _c.spray_angle(b["hc_x"], b["hc_y"])
    b["spray_exact"] = spray
    if "band" in mode:
        spray = np.round(spray / SPRAY_BAND) * SPRAY_BAND
    if mode.startswith("air"):
        la = pd.to_numeric(b["launch_angle"], errors="coerce").to_numpy(float)
        ground = (b["bb_type"].astype(str).to_numpy() == "ground_ball") | (np.isfinite(la) & (la < 10))
        spray = np.where(ground, np.nan, spray)
    b["spray"] = spray
    b["pull"] = _c.pull_angle(b["spray"], b["stand"])
    fl = _c.flight(b["launch_speed"].to_numpy(float), b["launch_angle"].to_numpy(float))
    b["hang"] = np.where(b["launch_speed"].notna() & b["launch_angle"].notna(), fl["hang"], np.nan)
    by_game, by_team = park_info(store)
    gpk = b["game_pk"].astype(np.int64).to_numpy()
    home = b["home_team"].astype(str).to_numpy()
    venues = [by_game.get(int(g)) or by_team.get(h) for g, h in zip(gpk, home)]
    dims = np.array([_dims_vec(v) for v in venues]) if len(venues) else np.zeros((0, 5))
    walls = np.array([_walls_vec(v) for v in venues]) if len(venues) else np.zeros((0, 5))
    for j, k in enumerate(DIM_KEYS):
        b[f"_d_{k}"] = dims[:, j] if len(b) else []
        b[f"_w_{k}"] = walls[:, j] if len(b) else []
    b["wall_mean"] = np.nanmean(walls, axis=1) if len(b) else []
    b["wall_dist"] = _interp_rows(b["spray"].to_numpy(float), dims) if len(b) else []
    b["wall_h"] = _interp_rows(b["spray"].to_numpy(float), walls) if len(b) else []
    nos = ~np.isfinite(b["spray"].to_numpy(float)) if len(b) else np.zeros(0, bool)
    b.loc[nos, ["wall_dist", "wall_h"]] = np.nan
    b["elev"] = [float((v or {}).get("elev_ft") or np.nan) if v else np.nan for v in venues]
    b["roof"] = [1.0 if str((v or {}).get("roof") or "").lower() in ("dome", "closed", "retractable-closed", "fixed") else 0.0
                 for v in venues]
    b["park"] = pd.factorize(home)[0]
    if speed is not None:
        b["speed"] = b["batter"].astype(str).map(speed).astype(float)
    return b


def neutral_features(b: pd.DataFrame, elev: float | None = None) -> pd.DataFrame:
    n = b.copy()
    std = np.tile([STD_DIMS[k] for k in DIM_KEYS], (len(n), 1))
    n["wall_dist"] = _interp_rows(n["spray"].to_numpy(float), std) if len(n) else []
    n["wall_h"] = STD_WALL
    nos = ~np.isfinite(n["spray"].to_numpy(float)) if len(n) else np.zeros(0, bool)
    n.loc[nos, ["wall_dist", "wall_h"]] = np.nan
    n["elev"] = float(np.nanmedian(b["elev"])) if elev is None and b["elev"].notna().any() else (elev or np.nan)
    n["roof"] = 0.0
    for k in DIM_KEYS:
        n[f"_d_{k}"] = STD_DIMS[k]
    n["wall_mean"] = STD_WALL
    return n


def _has_dims(b: pd.DataFrame) -> bool:
    if not len(b):
        return False
    has = np.isfinite(b["spray"].to_numpy(float))
    return bool(has.any()) and float(b.loc[has, "wall_dist"].notna().mean()) >= 0.8


def feature_list(b: pd.DataFrame, spray: bool = True, park: bool = True, speed: bool = True) -> list[str]:
    f = list(FEATS_BASE)
    if spray and SPRAY_MODE not in ("fence", "park_dims", "park_cat"):
        f += FEATS_SPRAY
    if park:
        if SPRAY_MODE == "park_dims" and "_d_cf" in b and b["_d_cf"].notna().mean() >= 0.8:
            f += FEATS_PARK_DIMS
        elif SPRAY_MODE == "park_cat":
            f += ["park", "elev", "roof"]
        else:
            f += FEATS_PARK if _has_dims(b) else ["park"]
    if speed and "speed" in b:
        f += FEATS_SPEED
    return f


# ============================================================================ fit / predict

def _lgb():
    import lightgbm as lgb
    return lgb


def _train(X: pd.DataFrame, y: np.ndarray, rounds: int = N_ROUNDS, params: dict | None = None):
    lgb = _lgb()
    p = dict(LGB_PARAMS, **(params or {}))
    cat = ["park"] if "park" in X.columns else "auto"
    ds = lgb.Dataset(X.astype(float), label=y, categorical_feature=cat, free_raw_data=True)
    return lgb.train(p, ds, num_boost_round=rounds)


def rake(P: np.ndarray, target: np.ndarray, iters: int = 2000, tol: float = 1e-12) -> tuple[np.ndarray, np.ndarray]:
    """Scale class columns so mean(P[:, c]) = target[c] while rows still sum to 1. Returns (P', multipliers)."""
    m = np.ones(P.shape[1])
    Q = P
    for _ in range(iters):
        Q = P * m
        Q /= Q.sum(axis=1, keepdims=True)
        cur = Q.mean(axis=0)
        if np.max(np.abs(cur - target)) < tol:
            break
        m *= np.where(cur > 0, target / np.maximum(cur, 1e-12), 1.0)
    Q = P * m
    Q /= Q.sum(axis=1, keepdims=True)
    return Q, m


def apply_rake(P: np.ndarray, m: np.ndarray) -> np.ndarray:
    Q = P * np.asarray(m)
    return Q / Q.sum(axis=1, keepdims=True)


def class_weights(bip: pd.DataFrame) -> np.ndarray:
    """Season wOBA weight per class (out = 0): the mean of Savant's woba_value over the batted balls of
    each class (`bip` from `batted_balls`); defaults when absent."""
    w = np.array([0.0, 0.88, 1.25, 1.58, 2.03])
    if "woba_value" not in bip or "cls" not in bip:
        return w
    v = pd.to_numeric(bip["woba_value"], errors="coerce")
    for c in range(1, 5):
        x = v[(bip["cls"] == c) & v.notna()]
        if len(x) >= 5:
            w[c] = float(x.mean())
    return w


def speed_proxy(b: pd.DataFrame, folds: np.ndarray, store: dict | None = None) -> np.ndarray:
    """Per-row batter speed proxy from *other* folds: shrunk ground-ball hit rate over a
    first-stage expectation (launch, spray, park; no speed). Returns an array aligned with b."""
    feats = feature_list(b, speed=False)
    y = (b["cls"].to_numpy() > 0).astype(int)
    p1 = np.full(len(b), np.nan)
    lgb = _lgb()
    params = {"objective": "binary", "learning_rate": 0.08, "num_leaves": 15, "min_data_in_leaf": 80, "verbose": -1,
              "num_threads": 8, "seed": 3}
    for k in np.unique(folds):
        tr, te = folds != k, folds == k
        ds = lgb.Dataset(b.loc[tr, feats].astype(float), label=y[tr], categorical_feature=["park"] if "park" in feats else "auto")
        m = lgb.train(params, ds, num_boost_round=120)
        p1[te] = m.predict(b.loc[te, feats].astype(float))
    gb = (b["bb_type"].astype(str) == "ground_ball").to_numpy() | (b["launch_angle"].astype(float) < 10).to_numpy()
    res = np.where(gb, y - p1, np.nan)
    bat = b["batter"].astype(str).to_numpy()
    out = np.zeros(len(b))
    for k in np.unique(folds):
        other = (folds != k) & gb
        df = pd.DataFrame({"bat": bat[other], "r": res[other]})
        agg = df.groupby("bat")["r"].agg(["sum", "count"])
        val = (agg["sum"] / (agg["count"] + SPEED_SHRINK_GB)).to_dict()
        te = folds == k
        out[te] = [val.get(x, 0.0) for x in bat[te]]
    return out


def fold_ids(game_pk: pd.Series, k: int = N_FOLDS) -> np.ndarray:
    g = game_pk.astype(np.int64).to_numpy()
    return (g * 2654435761 % 2 ** 32) % k


TENDENCY_K = 25.0     # pseudo air balls shrinking a batter's direction tendency toward the league


def _tendency_spray(b: pd.DataFrame, fid: np.ndarray) -> None:
    """Replace each ball's spray by its batter's air-ball direction tendency (pull angle, from the *other* folds,
    shrunk with TENDENCY_K pseudo balls), mapped back to the field for his side; walls follow."""
    la = pd.to_numeric(b["launch_angle"], errors="coerce").to_numpy(float)
    air = np.isfinite(la) & (la >= 10) & np.isfinite(b["spray_exact"].to_numpy(float))
    pull = _c.pull_angle(b["spray_exact"], b["stand"])
    bat = b["batter"].astype(str).to_numpy()
    lg = float(np.nanmean(pull[air])) if air.any() else 0.0
    tend = np.full(len(b), lg)
    for k in np.unique(fid):
        other = (fid != k) & air
        agg = pd.DataFrame({"b": bat[other], "p": pull[other]}).groupby("b")["p"].agg(["sum", "count"])
        val = ((agg["sum"] + TENDENCY_K * lg) / (agg["count"] + TENDENCY_K)).to_dict()
        te = fid == k
        tend[te] = [val.get(x, lg) for x in bat[te]]
    lefty = b["stand"].astype(str).str.upper().str.startswith("L").to_numpy()
    b["pull"] = tend
    b["spray"] = np.where(lefty, tend, -tend)
    dims = b[[f"_d_{k}" for k in DIM_KEYS]].to_numpy(float)
    walls = b[[f"_w_{k}" for k in DIM_KEYS]].to_numpy(float)
    b["wall_dist"] = _interp_rows(b["spray"].to_numpy(float), dims)
    b["wall_h"] = _interp_rows(b["spray"].to_numpy(float), walls)


def fit_predict(b: pd.DataFrame, store: dict | None = None, speed_map: dict | None = None, folds: int = N_FOLDS,
                rounds: int = N_ROUNDS, spray: bool = True, park: bool = True, use_speed: bool = True,
                neutral: bool = True, final_model: bool = False, spray_mode: str | None = None) -> dict:
    """Cross-fitted class probabilities for the batted balls `b` (output of `batted_balls`).
    Returns {"P" (n,5 raked), "P_n" (park-neutral) or None, "feats", "rake", "weights", "model" (full fit, optional)}."""
    b = add_features(b, store, speed_map, "exact" if (spray_mode or SPRAY_MODE) == "tendency" else spray_mode)
    fid = fold_ids(b["game_pk"], folds)
    if (spray_mode or SPRAY_MODE) == "tendency":
        _tendency_spray(b, fid)
    if use_speed and "speed" not in b and USE_SPEED_PROXY:
        b["speed"] = speed_proxy(b, fid, store)
    elif use_speed and "speed" not in b:
        use_speed = False
    elif use_speed:
        b["speed"] = b["speed"].astype(float)
    feats = feature_list(b, spray=spray, park=park, speed=use_speed)
    y = b["cls"].to_numpy(int)
    P = np.zeros((len(b), 5)); Pn = np.zeros((len(b), 5)) if neutral and park else None
    bn = neutral_features(b) if Pn is not None else None
    for k in np.unique(fid):
        tr, te = fid != k, fid == k
        m = _train(b.loc[tr, feats], y[tr], rounds)
        P[te] = m.predict(b.loc[te, feats].astype(float))
        if Pn is not None:
            if "park" in feats:
                Pn[te] = _park_average(m, b.loc[te, feats])
            else:
                Pn[te] = m.predict(bn.loc[te, feats].astype(float))
    target = np.bincount(y, minlength=5) / max(len(y), 1)
    Pr, mult = rake(P, target)
    out = {"P": Pr, "P_raw": P, "feats": feats, "rake": mult.tolist(), "bip": b,
           "P_n": apply_rake(Pn, mult) if Pn is not None else None}
    if final_model:
        out["model"] = _train(b[feats], y, rounds)
    return out


def _park_average(model, X: pd.DataFrame) -> np.ndarray:
    parks = np.unique(X["park"].to_numpy())
    acc = np.zeros((len(X), 5))
    for p in parks:
        Z = X.copy()
        Z["park"] = p
        acc += model.predict(Z.astype(float))
    return acc / max(len(parks), 1)


def log_loss(P: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(P[np.arange(len(y)), y], 1e-12, 1))))


def ablation(b: pd.DataFrame, store: dict | None = None, speed_map: dict | None = None, rounds: int = 150) -> dict:
    """Cross-fitted multiclass log loss (lower is better) and xwOBA-on-contact RMSE against
    woba_value for nested feature sets: launch only; + spray; + park; + speed (full)."""
    out = {}
    w = class_weights(b)
    global SPRAY_MODE
    keep = SPRAY_MODE
    for name, mode, kw in (("launch", "exact", dict(spray=False, park=False, use_speed=False)),
                           ("launch+spray", "exact", dict(spray=True, park=False, use_speed=False)),
                           ("launch+spray+park", "exact", dict(spray=True, park=True, use_speed=False)),
                           ("launch+fence+park", "fence", dict(spray=True, park=True, use_speed=False)),
                           ("full", keep, dict(spray=True, park=True, use_speed=True))):
        SPRAY_MODE = mode
        try:
            r = fit_predict(b, store, speed_map, rounds=rounds, neutral=False, **kw)
        finally:
            SPRAY_MODE = keep
        y = r["bip"]["cls"].to_numpy(int)
        xw = r["P"] @ w
        out[name] = {"logloss": log_loss(r["P"], y), "rmse": float(np.sqrt(np.mean((xw - w[y]) ** 2))),
                     "feats": r["feats"]}
    return out


# ============================================================================ PA level and players

def score_season(pitches: pd.DataFrame, store: dict | None = None, speed_map: dict | None = None,
                 final_model: bool = False, rounds: int = N_ROUNDS) -> dict:
    """xwOBA+ for every PA of a season's pitch table. Returns {"pa": PA frame with xwoba, xwoba_n,
    savant_x, woba, denom; "bip": per-BIP frame; "weights"; "fit"}."""
    pitches = pitches if "cls" in pitches else pitches
    b = batted_balls(pitches)
    w = class_weights(b)
    fit = fit_predict(b, store, speed_map, final_model=final_model, rounds=rounds)
    bip = fit["bip"]
    P = fit["P"]
    bip["xwoba"] = P @ w
    bip["xwoba_n"] = (fit["P_n"] @ w) if fit["P_n"] is not None else bip["xwoba"]
    for j, c in enumerate(CLASSES):
        bip[f"p_{c}"] = P[:, j]
        bip[f"pn_{c}"] = fit["P_n"][:, j] if fit["P_n"] is not None else P[:, j]
    pa = pa_xwoba(pitches, bip)
    return {"pa": pa, "bip": bip, "weights": w.tolist(), "fit": fit}


def pa_xwoba(pitches: pd.DataFrame, bip: pd.DataFrame) -> pd.DataFrame:
    """One row per PA-ending pitch with woba, denom, xwoba (ours), xwoba_n and savant_x."""
    ev = pitches["events"].astype(object).fillna("").astype(str)
    den = pitches["woba_denom"].astype(float).fillna(0.0)
    last = pitches[(ev != "") & (den > 0)].copy() if "woba_denom" in pitches else pitches[ev.isin(_c.PA_EVENTS)].copy()
    last["woba"] = last["woba_value"].astype(float).fillna(0.0)
    last["denom"] = last["woba_denom"].astype(float).fillna(1.0)
    key = ["game_pk", "at_bat_number"]
    bx = bip.drop_duplicates(key).set_index(key)
    idx = pd.MultiIndex.from_frame(last[key])
    is_bip = last["events"].astype(str).isin(_c.BIP_EVENTS).to_numpy()
    ours = bx["xwoba"].reindex(idx).to_numpy()
    ours_n = bx["xwoba_n"].reindex(idx).to_numpy()
    last["xwoba"] = np.where(is_bip, ours, last["woba"])
    last["xwoba_n"] = np.where(is_bip, ours_n, last["woba"])
    sv = last["estimated_woba_using_speedangle"].astype(float) if "estimated_woba_using_speedangle" in last else pd.Series(np.nan, index=last.index)
    bbm = last.loc[is_bip].groupby(last.loc[is_bip, "bb_type"].astype(str))["woba"].mean() if is_bip.any() else pd.Series(dtype=float)
    fill = last["bb_type"].astype(str).map(bbm).astype(float).fillna(last.loc[is_bip, "woba"].mean() if is_bip.any() else 0.3)
    last["savant_x"] = np.where(is_bip, sv.fillna(fill).to_numpy(), last["woba"])
    last["is_bip"] = is_bip
    for c in ("xwoba", "xwoba_n"):
        last[c] = last[c].fillna(last["woba"])
    return last.reset_index(drop=True)


def player_table(pa: pd.DataFrame, by: str = "batter", min_pa: int = 1) -> pd.DataFrame:
    g = pa.groupby(pa[by].astype(str))
    t = pd.DataFrame({"pa": g.size(), "den": g["denom"].sum(), "woba_num": g["woba"].sum(),
                      "x_num": g["xwoba"].sum(), "xn_num": g["xwoba_n"].sum(), "sv_num": g["savant_x"].sum(),
                      "bip": g["is_bip"].sum()})
    den = t["den"].replace(0, np.nan)
    t["woba"] = t["woba_num"] / den
    t["xwoba"] = t["x_num"] / den
    t["xwoba_n"] = t["xn_num"] / den
    t["savant_xwoba"] = t["sv_num"] / den
    t = t[t["pa"] >= min_pa]
    return t[["pa", "bip", "den", "woba", "xwoba", "xwoba_n", "savant_xwoba"]].reset_index().rename(columns={by: "pid"})


# ============================================================================ predictive test

def half_split(pitches: pd.DataFrame) -> pd.Series:
    d = pd.to_datetime(pitches["game_date"].astype(str))
    med = d.sort_values().iloc[len(d) // 2] if len(d) else None
    return d < med


def period_players(pitches: pd.DataFrame, store: dict | None = None, speed_map: dict | None = None,
                   rounds: int = N_ROUNDS) -> pd.DataFrame:
    """Player rows (batter) for one period: xwOBA+ fitted on that period only (cross-fitted)."""
    r = score_season(pitches, store, speed_map, rounds=rounds)
    return player_table(r["pa"], "batter")


def predictive_compare(cur: pd.DataFrame, nxt: pd.DataFrame, min_pa: int = MIN_PA, min_pa_next: int = MIN_PA_NEXT) -> dict:
    m = cur.merge(nxt[["pid", "pa", "woba"]], on="pid", suffixes=("", "_next"))
    m = m[(m["pa"] >= min_pa) & (m["pa_next"] >= min_pa_next)]
    y = m["woba_next"].to_numpy(float)
    out = {"n": int(len(m))}
    for k in ("woba", "savant_xwoba", "xwoba"):
        x = m[k].to_numpy(float)
        out[k] = {"r": _c.pearson(x, y), "rmse": float(np.sqrt(np.mean((x - y) ** 2))) if len(m) else None,
                  "rmse_wtd": float(np.sqrt(np.average((x - y) ** 2, weights=m["pa_next"]))) if len(m) else None}
    out["winner"] = ("xwoba+" if (out["xwoba"]["r"] or -1) > (out["savant_xwoba"]["r"] or -1) else "savant") if len(m) else None
    return out


def predictive_test(level: str = "mlb", seasons: list[int] | None = None, min_pa: int = MIN_PA,
                    min_pa_next: int = MIN_PA_NEXT, rounds: int = N_ROUNDS, pitch_loader=None) -> dict:
    """First half -> second half within each season, and second half -> next season's first half.
    One season of pitches in memory at a time; player aggregates carried between seasons."""
    seasons = seasons or _c.pitch_seasons(level)
    loader = pitch_loader or (lambda s: _c.load_pitches(level, s, COLUMNS))
    res = {"within": {}, "across": {}}
    prev_h2 = None
    for s in sorted(seasons):
        p = loader(s)
        if p is None or not len(p):
            prev_h2 = None
            continue
        store = _c.load_store(level, s) if pitch_loader is None else None
        sm = sprint_map(s)
        first = half_split(p)
        h1 = period_players(p[first.to_numpy()], store, sm, rounds)
        h2 = period_players(p[~first.to_numpy()], store, sm, rounds)
        del p
        res["within"][str(s)] = predictive_compare(h1, h2, min_pa, min_pa_next)
        if prev_h2 is not None:
            res["across"][f"{s - 1}H2->{s}H1"] = predictive_compare(prev_h2, h1, min_pa, min_pa_next)
        prev_h2 = h2
    # pooled
    for kind in ("within", "across"):
        rows = [v for v in res[kind].values() if v.get("n")]
        if rows:
            n = sum(v["n"] for v in rows)
            res[f"{kind}_pooled"] = {k: {"r": sum((v[k]["r"] or 0) * v["n"] for v in rows) / n,
                                         "rmse": math.sqrt(sum((v[k]["rmse"] or 0) ** 2 * v["n"] for v in rows) / n)}
                                     for k in ("woba", "savant_xwoba", "xwoba")}
            res[f"{kind}_pooled"]["n"] = n
    return res


def sprint_map(season: int) -> dict | None:
    lb = _c.leaderboard("sprint_speed", season)
    if lb is None or not len(lb):
        return None
    idc = next((c for c in ("player_id", "mlbam_id", "batter", "pid") if c in lb), None)
    vc = next((c for c in ("sprint_speed", "speed", "r_sprint_speed_top50percent") if c in lb), None)
    if not idc or not vc:
        return None
    return {str(int(a)): float(v) for a, v in zip(lb[idc], lb[vc]) if pd.notna(a) and pd.notna(v)}


# ============================================================================ season driver / fits

def season_result(level: str, season: int, pitches: pd.DataFrame | None = None, store: dict | None = None,
                  final_model: bool = False) -> dict | None:
    if pitches is None:
        pitches = _c.load_pitches(level, season, COLUMNS)
        if pitches is None or not len(pitches):
            return None
        store = store or _c.load_store(level, season)
    else:
        pitches = _c.prepare_pitches(pitches.copy())
    return score_season(pitches, store, sprint_map(season), final_model=final_model)


def bip_cache_path(level: str, season: int):
    return _c.cache_root() / "xwoba" / f"{level}_{season}_bip.parquet"


BIP_OUT = ["game_pk", "at_bat_number", "batter", "pitcher", "stand", "home_team", "events", "bb_type", "launch_speed",
           "launch_angle", "spray", "pull", "hang", "wall_dist", "speed", "xwoba", "xwoba_n", "p_out", "p_1B", "p_2B",
           "p_3B", "p_HR", "pn_1B", "pn_2B", "pn_3B", "pn_HR", "hit_distance_sc", "game_date",
           "estimated_woba_using_speedangle", "woba_value"]


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    """Cached JSON: league numbers, hitters and pitchers (PA, wOBA, xwOBA+, park-neutral, Savant xwOBA),
    and the per-BIP Parquet written alongside (cache/xwoba/<level>_<season>_bip.parquet)."""
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {"ok": False, "reason": f"no pitch table for {level} {season}"}

    def build():
        r = season_result(level, season)
        if r is None:
            return {"ok": False, "reason": "empty"}
        try:
            bp = bip_cache_path(level, season)
            bp.parent.mkdir(parents=True, exist_ok=True)
            r["bip"][[c for c in BIP_OUT if c in r["bip"]]].to_parquet(bp, index=False)
        except Exception:
            pass
        pa = r["pa"]
        lg = {"woba": float(pa["woba"].sum() / pa["denom"].sum()), "xwoba": float(pa["xwoba"].sum() / pa["denom"].sum()),
              "xwoba_n": float(pa["xwoba_n"].sum() / pa["denom"].sum()),
              "savant_xwoba": float(pa["savant_x"].sum() / pa["denom"].sum()), "pa": int(len(pa)),
              "bip": int(pa["is_bip"].sum()), "weights": r["weights"], "feats": r["fit"]["feats"]}
        hit = player_table(pa, "batter")
        pit = player_table(pa, "pitcher")
        return {"ok": True, "version": MODEL_VERSION, "league": lg, "hitters": _c.frame_rows(hit),
                "pitchers": _c.frame_rows(pit)}
    return _c.cached("xwoba", f"{level}_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def load_bip(level: str, season: int) -> pd.DataFrame | None:
    p = bip_cache_path(level, season)
    if not p.exists():
        for_season(level, season)
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def export_fits(level: str = "mlb", season: int | None = None) -> dict:
    """Train the full-season model for `season` (default latest) and write
    models/fitted/xwoba_<level>.txt.gz (LightGBM text) + xwoba_<level>.json (features, rake, weights)."""
    seasons = _c.pitch_seasons(level)
    season = season or (seasons[-1] if seasons else None)
    if season is None:
        return {"ok": False, "reason": "no seasons"}
    r = season_result(level, season, final_model=True)
    if r is None:
        return {"ok": False, "reason": "empty"}
    m = r["fit"]["model"]
    _c.FITTED.mkdir(parents=True, exist_ok=True)
    with gzip.open(_c.FITTED / f"xwoba_{level}.txt.gz", "wt", encoding="utf-8") as fh:
        fh.write(m.model_to_string())
    meta = {"version": MODEL_VERSION, "season": season, "feats": r["fit"]["feats"], "rake": r["fit"]["rake"],
            "weights": r["weights"], "classes": CLASSES}
    _c.write_fit(f"xwoba_{level}", meta)
    return {"ok": True, **meta}


def load_fitted(level: str = "mlb"):
    """(booster, meta) from models/fitted, or (None, None)."""
    meta = _c.read_fit(f"xwoba_{level}")
    p = _c.FITTED / f"xwoba_{level}.txt.gz"
    if not meta or not p.exists():
        return None, None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        s = fh.read()
    return _lgb().Booster(model_str=s), meta


def predict_fitted(pitches: pd.DataFrame, store: dict | None = None, level: str = "mlb") -> pd.DataFrame | None:
    """Score batted balls with the committed model (CI path, no refit). Speed falls back to 0 (proxy scale)."""
    m, meta = load_fitted(level)
    if m is None:
        return None
    b = add_features(batted_balls(pitches), store, None)
    if not len(b):                          # only fouls carry a launch speed here
        return None
    if "speed" in meta["feats"] and "speed" not in b:
        b["speed"] = 0.0
    for f in meta["feats"]:
        if f not in b:
            b[f] = np.nan
    P = apply_rake(m.predict(b[meta["feats"]].astype(float)), np.asarray(meta["rake"]))
    b["xwoba"] = P @ np.asarray(meta["weights"])
    return b
