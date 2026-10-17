"""
Bat tracking beyond the raw columns (Statcast bat tracking: bat_speed, swing_length, attack_angle,
attack_direction, swing_path_tilt, intercept positions; present from 2023-24, absent before -> {"ok": False}).

Competitive swings: non-bunt swings with a bat speed >= MIN_BAT_SPEED (drops checked and defensive swings).

* Adjusted bat speed / swing length: a league LightGBM regression of bat speed (swing length) on what the
  pitch and count demand (pitch speed at the plate, x_away, z_rel, plate_z, balls, strikes, family,
  platoon), fitted on the season's competitive swings; a hitter's adjusted value is the league mean plus
  his mean residual shrunk by K_SWINGS pseudo-swings: (sum r) / (n + K_SWINGS).
* Squared-up: launch speed >= 80% of the maximum possible exit velocity for the swing,
  max_ev = 1.23 bat_speed + 0.23 plate_speed (Savant's definition). Rates per contact and per swing
  (whiffs count as not squared up), each against an expectation from a league model of P(squared-up | the
  pitch: speed, movement, location, count, family; and the swing: bat speed, swing length) on contact, so
  sq_oe = actual - expected per contact measures contact precision for the swings the hitter took (a harder
  swing raises the bar, so without the swing terms fast swingers would read as imprecise).
* Swing-path fit: mismatch = attack_angle + VAA (VAA is negative for a descending pitch; a swing path that
  matches the pitch's plane has attack_angle = -VAA). Per hitter mean attack angle, mean |mismatch| and the
  share within MATCH_DEG; league squared-up rate and xwOBAcon by |mismatch| band.
* Intercept point: intercept_ball_minus_batter_pos_y_inches (how far in front of the batter's body the
  ball is met) per hitter and pitch family / type, against the league (positive = further out front).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, prep

MODEL_VERSION = "battrack-2"

MIN_BAT_SPEED = 50.0
K_SWINGS = 50
MATCH_DEG = 5.0
FEATURES = ["plate_speed", "x_away", "z_rel", "plate_z", "balls", "strikes", "fam", "platoon"]
SQ_FEATURES = ["plate_speed", "ivb", "hb_arm", "x_away", "z_rel", "plate_z", "balls", "strikes", "fam", "platoon",
               "bat_speed", "swing_length"]
LGB = {"num_leaves": 31, "learning_rate": 0.08, "min_data_in_leaf": 300, "lambda_l2": 10.0}


def has_tracking(df: pd.DataFrame) -> bool:
    return "bat_speed" in df and pd.to_numeric(df["bat_speed"], errors="coerce").notna().sum() >= 200


def competitive(df: pd.DataFrame) -> pd.DataFrame:
    bs = pd.to_numeric(df["bat_speed"], errors="coerce")
    return df[df["swing"].astype(bool) & ~df["bunt"].astype(bool) & (bs >= MIN_BAT_SPEED) & df["family"].notna()].copy()


def _X(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.to_numeric(df[c], errors="coerce").astype(np.float32) for c in cols}, index=df.index)


def _fit_pred(X: pd.DataFrame, y: np.ndarray, obj: str) -> tuple[np.ndarray, dict]:
    vm = np.random.default_rng(17).random(len(X)) < 0.1
    bst, info = _io.lgb_train(X[~vm], y[~vm], obj, LGB, X[vm], y[vm], rounds=300, early=30)
    ms = _io.booster_dump(bst)
    return _io.lgb_predict(ms, X), {"importance": _io.importances(ms, list(X.columns)), **info}


def analyse(df: pd.DataFrame) -> dict[str, Any]:
    """Everything on an enriched season with bat tracking. Returns DataFrames and league tables."""
    sw = competitive(df)
    for c in ("bat_speed", "swing_length", "attack_angle", "attack_direction", "swing_path_tilt", "launch_speed",
              "intercept_ball_minus_batter_pos_y_inches", "intercept_ball_minus_batter_pos_x_inches"):
        sw[c] = pd.to_numeric(sw[c], errors="coerce") if c in sw else np.nan
    info: dict[str, Any] = {"n_swings": int(len(sw))}
    X = _X(sw, FEATURES)
    for col in ("bat_speed", "swing_length"):
        m = sw[col].notna().to_numpy()
        pred = np.full(len(sw), np.nan)
        if m.sum() >= 200:
            pred[m], inf = _fit_pred(X[m], sw.loc[m, col].to_numpy(float), "regression")
            info[col] = {"league_mean": float(sw.loc[m, col].mean()), **inf}
        sw[f"{col}_exp"] = pred
        sw[f"{col}_res"] = sw[col] - pred
    # squared up
    max_ev = 1.23 * sw["bat_speed"] + 0.23 * sw["plate_speed"]
    con = sw["contact"].astype(bool) & sw["launch_speed"].notna()
    sw["sq"] = np.where(con, (sw["launch_speed"] >= 0.8 * max_ev).astype(float), np.nan)
    sw["sq_swing"] = np.where(con, sw["sq"], np.where(sw["whiff"].astype(bool), 0.0, np.nan))
    sw["sq_exp"] = np.nan
    if con.sum() >= 200:
        Xs = _X(sw[con], SQ_FEATURES)
        sw.loc[con, "sq_exp"], inf = _fit_pred(Xs, sw.loc[con, "sq"].to_numpy(float), "binary")
        info["squared_up"] = {"rate_contact": float(sw.loc[con, "sq"].mean()), **inf}
    # swing path v pitch plane
    sw["mismatch"] = sw["attack_angle"] + sw["vaa"]
    sw["abs_mis"] = sw["mismatch"].abs()
    sw["matched"] = np.where(sw["abs_mis"].notna(), (sw["abs_mis"] <= MATCH_DEG).astype(float), np.nan)
    bands = pd.cut(sw["abs_mis"], [0, 2.5, 5, 7.5, 10, 15, 20, 90], include_lowest=True)
    xw = sw["xwoba_con"] if "xwoba_con" in sw else pd.Series(np.nan, index=sw.index)
    tab = sw.assign(_xw=xw).groupby(bands, observed=True).agg(n=("sq", "size"), sq=("sq", "mean"), xwoba_con=("_xw", "mean"))
    info["mismatch_bands"] = {str(k): v for k, v in tab.round(4).to_dict("index").items()}
    return {"swings": sw, "info": info}


def hitters(sw: pd.DataFrame, info: dict, min_n: int = 1) -> pd.DataFrame:
    sw = sw.copy()
    sw["icpt_y"] = sw["intercept_ball_minus_batter_pos_y_inches"]
    g = sw.groupby("batter")
    out = pd.DataFrame({"n": g.size(), "bat_speed": g["bat_speed"].mean(), "swing_length": g["swing_length"].mean(),
                        "bs_res_sum": g["bat_speed_res"].sum(), "bs_res_n": g["bat_speed_res"].count(),
                        "sl_res_sum": g["swing_length_res"].sum(), "sl_res_n": g["swing_length_res"].count(),
                        "sq_contact": g["sq"].mean(), "sq_exp": g["sq_exp"].mean(), "sq_swing": g["sq_swing"].mean(),
                        "sq_n": g["sq"].count(), "attack_angle": g["attack_angle"].mean(),
                        "abs_mismatch": g["abs_mis"].mean(), "matched": g["matched"].mean(),
                        "attack_direction": g["attack_direction"].mean(), "swing_path_tilt": g["swing_path_tilt"].mean(),
                        "intercept_y": g["icpt_y"].mean()})
    bm = (info.get("bat_speed") or {}).get("league_mean", np.nan)
    lm = (info.get("swing_length") or {}).get("league_mean", np.nan)
    out["bat_speed_adj"] = bm + out["bs_res_sum"] / (out["bs_res_n"] + K_SWINGS)
    out["swing_length_adj"] = lm + out["sl_res_sum"] / (out["sl_res_n"] + K_SWINGS)
    out["sq_oe"] = out["sq_contact"] - out["sq_exp"]
    lg_icpt = sw["icpt_y"].mean()
    out["intercept_y_rel"] = out["intercept_y"] - lg_icpt
    by_fam = sw.groupby(["batter", "family"])["icpt_y"].mean().unstack()
    for f in by_fam.columns:
        out[f"intercept_y_{f}"] = by_fam[f]
    out = out.drop(columns=["bs_res_sum", "bs_res_n", "sl_res_sum", "sl_res_n"])
    return out[out["n"] >= min_n]


def intercept_by_type(sw: pd.DataFrame, min_n: int = 25) -> dict:
    """{batter: {pitch_type: mean intercept y (in)}} plus the league by type."""
    d = sw[sw["intercept_ball_minus_batter_pos_y_inches"].notna()]
    g = d.groupby(["batter", "pitch_type"])["intercept_ball_minus_batter_pos_y_inches"].agg(["mean", "size"])
    g = g[g["size"] >= min_n].reset_index()
    out: dict[str, dict] = {}
    for r in g.itertuples():
        out.setdefault(str(r.batter), {})[r.pitch_type] = round(float(r.mean), 2)
    lg = d.groupby("pitch_type")["intercept_ball_minus_batter_pos_y_inches"].mean().round(2).to_dict()
    return {"batters": out, "league": lg}


def for_season(level: str, season: int, use_cache: bool = True, min_n: int = 50) -> dict:
    """{"ok","level","season","info": {league means, importances, mismatch bands}, "hitters": {pid: {...}},
    "intercept": {...}, "leaders": {"bat_speed_adj", "sq_oe"}}; {"ok": False} without bat tracking."""
    try:
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        key = _io.file_key(MODEL_VERSION, src, min_n)

        def build():
            df = prep.prepared(level, season)
            if not has_tracking(df):
                return {"ok": False, "reason": "no bat tracking this season"}
            a = analyse(df)
            del df
            sw = a["swings"]
            h = hitters(sw, a["info"], min_n)
            q = h[h["n"] >= 200] if (h["n"] >= 200).sum() >= 20 else h
            return _io.clean({"ok": True, "level": level, "season": season, "version": MODEL_VERSION, "info": a["info"],
                              "hitters": {str(k): v for k, v in h.to_dict("index").items()},
                              "intercept": intercept_by_type(sw),
                              "leaders": {"bat_speed_adj": q.sort_values("bat_speed_adj", ascending=False).head(15).reset_index().to_dict("records"),
                                          "sq_oe": q[q["sq_n"] >= 50].sort_values("sq_oe", ascending=False).head(15).reset_index().to_dict("records")}}, 4)

        return _io.cached("battrack", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
