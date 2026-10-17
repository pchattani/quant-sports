"""
Win probability (WP), our own, for the team in possession.

Label: the possession team won the game (ties are left out of fitting and scoring). Features, per play
state: score differential, seconds left in the game and in the half, the half (overtime is the third),
down, distance, yard line, both teams' timeouts, home, the pregame spread from the possession team's side
(nflverse `spread_line` is the home side's expected margin), whether the possession team receives the
second-half kickoff, era, nflfastR's two time interactions (spread_time = spread * exp(-4 e) and
diff_time = score_diff * exp(4 e), e = elapsed share of regulation) and a Brownian-motion prior
bm_z = (score_diff + spread * (1 - e)) / (BM_SIGMA sqrt(1 - e)), which carries the spread's information
through the game in the scale the trees need (added in wp-2: it cut the gap to nflfastR's vegas_wp
in the first quarter). LightGBM binary, monotone
increasing in score differential, spread and diff_time, decreasing in yard line (closer is better) and
in the defence's timeouts, increasing in the offence's timeouts. Cross-fitted by season like EP.

Not a feature (since wp-3): receive_2h_ko. In the data it carries selection, not just the extra
possession: in a tied first half, the side that kicked off to open the game has the ball only after a
stop, and it went on to win 60% of such games against 48% for the other side (pick'ems, 2010-2025), so
the model learnt about 3.7 WP points from it on average and up to 8 in a counterfactual 4th-down state.
That history is fixed across the options a coach chooses between, so in the decision model it inflated the
value of keeping the ball; dropping it cost little log-loss (see the validation). It is still computed
(`receive_2h_ko`) for payloads.

`receive_2h_ko`: nflverse `home_opening_kickoff` = 1 when the home side kicked off to open the game, so
it receives the second-half kickoff; when that column is missing the first kickoff of the game decides it.

Validation (`validate`): log-loss, Brier and calibration of ours (cross-fitted) against nflfastR's `wp`
(no spread) and `vegas_wp` (with spread) on the same plays, overall, by season and by quarter;
nflfastR's model is in-sample on its training seasons.

`state_wp(fit, states)`: vectorised WP for counterfactual states (used by fourth_down): a frame of
states with nflverse column names (score_differential, game_seconds_remaining, half_seconds_remaining,
qtr, down, ydstogo, yardline_100, posteam_timeouts_remaining, defteam_timeouts_remaining, home,
pos_spread, receive_2h_ko, season).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io
from oddsmarkets.nfl.models.ep import half_of

MODEL_VERSION = "wp-3"
FEATURES = ["score_differential", "game_seconds_remaining", "half_seconds_remaining", "half", "down", "ydstogo",
            "yardline_100", "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home", "pos_spread",
            "spread_time", "diff_time", "bm_z", "era"]
MONOTONE = {"score_differential": 1, "pos_spread": 1, "diff_time": 1, "spread_time": 1, "bm_z": 1, "yardline_100": -1,
            "posteam_timeouts_remaining": 1, "defteam_timeouts_remaining": -1}
PARAMS = {"objective": "binary", "learning_rate": 0.08, "num_leaves": 63, "min_data_in_leaf": 300, "lambda_l2": 5.0}
ROUNDS = 800
K_FOLDS = 5
SCRIMMAGE = {"pass", "run", "punt", "field_goal", "no_play", "qb_kneel", "qb_spike"}
BM_SIGMA = 13.5             # points: the s.d. of an NFL final margin about the spread
HOK_HOME_RECEIVES = True     # nflverse home_opening_kickoff = 1 when the home side received the opening kickoff


def receive_2h_ko(df: pd.DataFrame) -> np.ndarray:
    """1 when the possession team receives the second-half kickoff and the play is in the first half.
    The team that kicked off to open the game receives in the second half: taken from the game's first
    kickoff (nflverse's posteam on a kickoff is the receiving team), else from `home_opening_kickoff`
    read as HOK_HOME_RECEIVES says (checked on the data: see the module docstring)."""
    home = pd.to_numeric(df["home"], errors="coerce").to_numpy(float)
    home_kicked = pd.Series(np.nan, index=df.index)
    if "play_type" in df and "game_id" in df:
        k = df[(df["play_type"].astype(str) == "kickoff") & df["posteam"].notna()]
        if "qtr" in k:
            k = k[pd.to_numeric(k["qtr"], errors="coerce") == 1]
        k = k.sort_values(["game_id", "play_id"]).drop_duplicates("game_id")
        first = dict(zip(k["game_id"], (k["posteam"].astype(str) != k["home_team"].astype(str)).astype(float)))
        home_kicked = df["game_id"].map(first).astype(float)
    if "home_opening_kickoff" in df:
        hok = pd.to_numeric(df["home_opening_kickoff"], errors="coerce")
        home_kicked = home_kicked.fillna(1 - hok if HOK_HOME_RECEIVES else hok)
    hk = home_kicked.to_numpy(float)
    first_half = half_of(df["qtr"]) == 1
    rec = np.where(home == 1, hk, 1 - hk)
    return np.where(first_half, np.nan_to_num(rec, nan=0.5), 0.0)


def features(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in ("score_differential", "game_seconds_remaining", "half_seconds_remaining", "down", "ydstogo",
              "yardline_100", "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home", "pos_spread"):
        X[c] = pd.to_numeric(df[c], errors="coerce").astype(float) if c in df else np.nan
    X["half"] = df["half"].astype(float) if "half" in df else half_of(df["qtr"])
    gsr = X["game_seconds_remaining"].clip(lower=0)
    e = np.clip(1 - gsr / 3600.0, 0, 1)
    e = np.where(X["half"] == 3, 1.0, e)
    X["spread_time"] = X["pos_spread"].fillna(0) * np.exp(-4 * e)
    X["diff_time"] = X["score_differential"] * np.exp(4 * e)
    # a Brownian-motion prior: (lead + spread x share of the game left) / (BM_SIGMA sqrt(share left))
    u = np.clip(1 - e, 0, 1)
    X["bm_z"] = (X["score_differential"] + X["pos_spread"].fillna(0) * u) / (BM_SIGMA * np.sqrt(u + 0.005))
    X["era"] = pd.to_numeric(df["season"], errors="coerce").astype(float)
    return X[FEATURES]


def label(df: pd.DataFrame) -> np.ndarray:
    """1 / 0 when the possession team won / lost; NaN on ties and unfinished games."""
    r = pd.to_numeric(df["result"], errors="coerce").to_numpy(float)
    home = pd.to_numeric(df["home"], errors="coerce").to_numpy(float)
    m = np.where(home == 1, r, -r)
    return np.where(np.isfinite(m) & (m != 0), (m > 0).astype(float), np.nan)


def is_model_play(df: pd.DataFrame) -> np.ndarray:
    d = pd.to_numeric(df["down"], errors="coerce").to_numpy(float)
    pt = df["play_type"].astype(str).to_numpy()
    tp = pd.to_numeric(df["two_point_attempt"], errors="coerce").fillna(0).to_numpy() if "two_point_attempt" in df else 0
    return np.isin(d, [1, 2, 3, 4]) & np.isin(pt, list(SCRIMMAGE)) & df["posteam"].notna().to_numpy() & (tp != 1)


def training_rows(d: pd.DataFrame) -> pd.DataFrame:
    d = d.reset_index(drop=True)
    X = features(d)
    m = is_model_play(d)
    out = X[m].reset_index(drop=True)
    out["y"] = label(d)[m]
    out["season"] = pd.to_numeric(d["season"], errors="coerce").to_numpy(float)[m]
    out["qtr"] = pd.to_numeric(d["qtr"], errors="coerce").to_numpy(float)[m]
    out["game_id"] = d["game_id"].astype(str).to_numpy()[m]
    out["play_id"] = pd.to_numeric(d["play_id"], errors="coerce").to_numpy(float)[m]
    for c in ("wp", "vegas_wp"):
        out[f"nf_{c}"] = pd.to_numeric(d[c], errors="coerce").to_numpy(float)[m] if c in d else np.nan
    return out


def fit_table(t: pd.DataFrame, k: int = K_FOLDS, rounds: int = ROUNDS) -> tuple[dict, np.ndarray]:
    t = t[np.isfinite(t["y"].to_numpy(float))].reset_index(drop=True)
    X, y = t[FEATURES], t["y"].to_numpy(float)
    folds = _io.fold_ids(t["season"].to_numpy(int), t["game_id"].to_numpy(), k)
    oof, infos = _io.crossfit(X, y, folds, t["game_id"].to_numpy(), "binary", PARAMS, rounds=rounds, monotone=MONOTONE)
    best = int(np.mean([i["best_iter"] for i in infos])) if infos else 300
    model, _ = _io.fit_full(X, y, "binary", PARAMS, rounds=best, monotone=MONOTONE)
    fit = {"ok": True, "version": MODEL_VERSION, "features": FEATURES, "monotone": MONOTONE, "n": int(len(t)),
           "seasons": sorted(set(int(s) for s in t["season"])), "best_iter": best, "folds": infos,
           "models": {"main": model}, "importance": _io.importances(model, FEATURES)}
    return fit, oof


def predict(fit: dict, df: pd.DataFrame) -> np.ndarray:
    X = df[FEATURES] if set(FEATURES) <= set(df.columns) else features(df)
    return _io.lgb_predict(fit["models"]["main"], X)


def state_wp(fit: dict, states: pd.DataFrame) -> np.ndarray:
    """WP of the possession team for synthetic states. Game over (no time left, not in a tied regulation)
    is resolved exactly."""
    p = predict(fit, states)
    gsr = pd.to_numeric(states["game_seconds_remaining"], errors="coerce").to_numpy(float)
    sd = pd.to_numeric(states["score_differential"], errors="coerce").to_numpy(float)
    over = (gsr <= 0) & (sd != 0)
    return np.where(over, (sd > 0).astype(float), np.where((gsr <= 0) & (sd == 0), 0.5, p))


# ============================================================================ validation

def _block(y, p) -> dict:
    return {"logloss": round(_io.log_loss(y, p), 5), "brier": round(_io.brier(y, p), 5),
            "calibration": _io.calibration(y, p, 10)}


def compare(t: pd.DataFrame, p: np.ndarray) -> dict:
    y = t["y"].to_numpy(float)
    nf, nv = t["nf_wp"].to_numpy(float), t["nf_vegas_wp"].to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(p)
    out = {"n": int(ok.sum()), "ours": _block(y[ok], p[ok])}
    if np.isfinite(nf[ok]).any():
        o2 = ok & np.isfinite(nf) & np.isfinite(nv)
        out["n_common"] = int(o2.sum())
        out["ours_common"] = {"logloss": round(_io.log_loss(y[o2], p[o2]), 5), "brier": round(_io.brier(y[o2], p[o2]), 5)}
        out["nflfastr_wp"] = _block(y[o2], nf[o2])
        out["nflfastr_vegas_wp"] = _block(y[o2], nv[o2])
    return out


def validate(t: pd.DataFrame, p: np.ndarray, split: int = 2020) -> dict:
    s = t["season"].to_numpy(int)
    q = t["qtr"].to_numpy(float)
    out = {"all": compare(t, p)}
    for name, m in ((f"pre_{split}", s < split), (f"from_{split}", s >= split)):
        if m.any():
            out[name] = compare(t[m].reset_index(drop=True), p[m])
    out["by_quarter"] = {}
    for qq in (1, 2, 3, 4, 5):
        m = q == qq
        if m.sum() > 100:
            c = compare(t[m].reset_index(drop=True), p[m])
            out["by_quarter"][qq] = {"n": c["n"], "ours": c.get("ours_common", c["ours"]).get("logloss"),
                                     "wp": (c.get("nflfastr_wp") or {}).get("logloss"),
                                     "vegas_wp": (c.get("nflfastr_vegas_wp") or {}).get("logloss")}
    by = {}
    for yv in np.unique(s):
        m = s == yv
        c = compare(t[m].reset_index(drop=True), p[m])
        by[int(yv)] = {"n": c.get("n_common", c["n"]), "ours": c.get("ours_common", c["ours"]).get("logloss"),
                       "wp": (c.get("nflfastr_wp") or {}).get("logloss"),
                       "vegas_wp": (c.get("nflfastr_vegas_wp") or {}).get("logloss")}
    out["by_season"] = by
    return out


# ============================================================================ pipeline

def fit(seasons=None, k: int = K_FOLDS, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("wp", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    t = _io.stack(seasons, training_rows)
    fitd, oof = fit_table(t, k)
    fitd["key"] = key
    tt = t[np.isfinite(t["y"].to_numpy(float))].reset_index(drop=True)
    fitd["validation"] = validate(tt, oof)
    for s in np.unique(tt["season"].to_numpy(int)):
        m = tt["season"].to_numpy(int) == s
        o = pd.DataFrame({"game_id": tt["game_id"][m].to_numpy(), "play_id": tt["play_id"][m].to_numpy(),
                          "wp_ours": oof[m].astype("float32")})
        p = _io.cache_root() / "wp_oof" / f"{int(s)}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        o.to_parquet(p, index=False)
    _io.store_fit("wp", fitd)
    del t, tt, oof
    return fitd


def current_fit() -> dict | None:
    return _io.get_fit("wp", MODEL_VERSION)


def for_season(season: int, d: pd.DataFrame | None = None) -> pd.DataFrame:
    """game_id, play_id, wp_ours for one season's model plays (cross-fitted where available; ties and
    unfinished games predicted by the production model)."""
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame(columns=["game_id", "play_id", "wp_ours"])
    m = is_model_play(d)
    s = d[m]
    X = features(d)[m]            # on the whole season: the second-half receiver comes from the kickoffs
    base = pd.DataFrame({"game_id": s["game_id"].astype(str).to_numpy(), "play_id": pd.to_numeric(s["play_id"], errors="coerce").to_numpy(float)})
    p = _io.cache_root() / "wp_oof" / f"{int(season)}.parquet"
    o = None
    if p.exists():
        try:
            o = pd.read_parquet(p)
        except Exception:  # noqa: BLE001
            o = None
    if o is not None:
        base = base.merge(o, on=["game_id", "play_id"], how="left")
    else:
        base["wp_ours"] = np.nan
    # the cached column can come back float32 or object; float64 takes the fresh predictions without a lossy cast
    base["wp_ours"] = pd.to_numeric(base["wp_ours"], errors="coerce").astype("float64")
    miss = base["wp_ours"].isna().to_numpy()
    if miss.any():
        f = current_fit()
        if f is not None:
            base.loc[miss, "wp_ours"] = predict(f, X[miss])
    return base


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("wp", f)
    return {k: v for k, v in f.items() if k != "models"}
