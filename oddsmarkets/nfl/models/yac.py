"""
Expected yards after catch (xYAC), our own, and YAC over expected (YACOE).

Rows: completions with yards after the catch recorded; target: YAC clipped to [-10, room] (room = the
yard line minus air yards: a catch can't gain more than the distance to the goal line). LightGBM
regression (squared error: the conditional mean) in feature tiers like completion.py:

* base (1999->): air yards, room, yard line, distance, down, whether the catch is past the line to gain,
  pass location, seconds left in the half, score, shotgun, QB hit, roof, era;
* participation (2016-2025): + box count, pass rushers, coverage shell, man/zone;
* FTN (2022->): + screen, play action, motion, contested;
* FTN + participation (2022-2025).

Validation: RMSE of ours (cross-fitted) and nflverse's `xyac_mean_yardage` against actual YAC on the same
completions; correlation of receiver-season YACOE with NGS avg_yac_above_expectation (2016->).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "xyac-1"
BASE = ["air_yards", "room", "yardline_100", "ydstogo", "down", "past_sticks", "loc_code", "half_seconds_remaining",
        "score_differential", "shotgun", "qb_hit", "roof_code", "era"]
PART = ["p_box", "p_rushers", "cov_code", "mz_code"]
FTN = ["f_screen", "f_pa", "f_motion", "f_contested"]
TIERS = [{"name": "base", "lo": 1999, "hi": None, "features": BASE},
         {"name": "part", "lo": 2016, "hi": 2025, "features": BASE + PART},
         {"name": "ftn", "lo": 2022, "hi": None, "features": BASE + FTN},
         {"name": "ftn_part", "lo": 2022, "hi": 2025, "features": BASE + FTN + PART}]
PARAMS = {"objective": "regression", "learning_rate": 0.06, "num_leaves": 31, "min_data_in_leaf": 300, "lambda_l2": 5.0}
MIN_REC = 40


def rows(d: pd.DataFrame) -> pd.DataFrame:
    c = pd.to_numeric(d["complete_pass"], errors="coerce").fillna(0) == 1
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1 if "two_point_attempt" in d else False
    m = c & ~tp & pd.to_numeric(d["yards_after_catch"], errors="coerce").notna() & pd.to_numeric(d["air_yards"], errors="coerce").notna()
    s = d[m]
    out = pd.DataFrame(index=s.index)
    for col in ("air_yards", "yardline_100", "ydstogo", "down", "loc_code", "half_seconds_remaining", "score_differential",
                "shotgun", "qb_hit", "roof_code", "p_box", "p_rushers", "f_screen", "f_pa", "f_motion", "f_contested"):
        out[col] = pd.to_numeric(s[col], errors="coerce").astype(float) if col in s else np.nan
    out["room"] = out["yardline_100"] - out["air_yards"]
    out["past_sticks"] = (out["air_yards"] >= out["ydstogo"]).astype(float)
    out["era"] = pd.to_numeric(s["season"], errors="coerce").astype(float)
    out["cov_code"] = s["p_coverage"].map(_io.COVERAGE_CODE).astype(float) if "p_coverage" in s else np.nan
    out["mz_code"] = s["p_manzone"].map(_io.MANZONE_CODE).astype(float) if "p_manzone" in s else np.nan
    yac = pd.to_numeric(s["yards_after_catch"], errors="coerce").astype(float)
    out["yac"] = yac
    out["y"] = np.clip(yac, -10, np.maximum(out["room"], 0))
    out["season"] = out["era"]
    out["game_id"] = s["game_id"].astype(str)
    out["play_id"] = pd.to_numeric(s["play_id"], errors="coerce").astype(float)
    out["receiver"] = s["receiver_player_id"].astype(object)
    out["receiver_name"] = s["receiver_player_name"].astype(object) if "receiver_player_name" in s else None
    out["team"] = s["posteam"].astype(object)
    out["nf_xyac"] = pd.to_numeric(s.get("xyac_mean_yardage"), errors="coerce").astype(float) if "xyac_mean_yardage" in s else np.nan
    return out.reset_index(drop=True)


def fit(seasons=None, k: int = 5, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("yac", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    t = _io.stack(seasons, rows)
    fitd, oof = _io.fit_tiers(t, TIERS, "regression", PARAMS, k)
    t["xyac"] = oof
    fitd.update({"ok": True, "version": MODEL_VERSION, "key": key, "seasons": seasons, "n": int(len(t)), "validation": validate(t)})
    for s in np.unique(t["season"].to_numpy(int)):
        m = t["season"].to_numpy(int) == s
        _io.oof_store("xyac", int(s), t.loc[m, ["game_id", "play_id", "xyac"]].reset_index(drop=True))
    _io.store_fit("yac", fitd)
    del t
    return fitd


def current_fit() -> dict | None:
    return _io.get_fit("yac", MODEL_VERSION)


def season_rows(season: int, d: pd.DataFrame | None = None, fit_: dict | None = None) -> pd.DataFrame:
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame()
    t = rows(d)
    o = _io.oof_load("xyac", season)
    t = t.merge(o, on=["game_id", "play_id"], how="left") if o is not None and len(o) else t.assign(xyac=np.nan)
    miss = t["xyac"].isna().to_numpy()
    f = fit_ or current_fit()
    if miss.any() and f is not None:
        t.loc[miss, "xyac"] = _io.predict_tiers(f, t[miss], TIERS)
    return t


def receiver_table(t: pd.DataFrame) -> pd.DataFrame:
    x = t[t["receiver"].notna()].assign(oe=lambda z: z["yac"] - z["xyac"], noe=lambda z: z["yac"] - z["nf_xyac"])
    g = x.groupby(["receiver", "season"]).agg(name=("receiver_name", "last"), team=("team", "last"), rec=("yac", "size"),
                                             yac=("yac", "sum"), xyac=("xyac", "sum"), yacoe=("oe", "mean"),
                                             yacoe_nflverse=("noe", "mean")).reset_index()
    g["yacoe_total"] = g["yac"] - g["xyac"]
    return g.sort_values("rec", ascending=False).reset_index(drop=True)


def validate(t: pd.DataFrame) -> dict:
    y, p, n = t["yac"].to_numpy(float), t["xyac"].to_numpy(float), t["nf_xyac"].to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(p) & np.isfinite(n)
    out = {"n": int(ok.sum())}
    if ok.any():
        out["rmse_ours"] = float(np.sqrt(np.mean((y[ok] - p[ok]) ** 2)))
        out["rmse_nflverse"] = float(np.sqrt(np.mean((y[ok] - n[ok]) ** 2)))
        out["mae_ours"] = float(np.mean(np.abs(y[ok] - p[ok])))
        out["mae_nflverse"] = float(np.mean(np.abs(y[ok] - n[ok])))
        out["mean_actual"], out["mean_ours"], out["mean_nflverse"] = float(y[ok].mean()), float(p[ok].mean()), float(n[ok].mean())
    rt = receiver_table(t)
    q = rt[rt["rec"] >= MIN_REC]
    out["rec_yacoe_corr_nflverse"] = _io.pearson(q["yacoe"], q["yacoe_nflverse"])
    n = _io.load_ngs("receiving")
    if n is not None and len(n) and "avg_yac_above_expectation" in n:
        n = n.copy()
        if "week" in n:
            n = n[pd.to_numeric(n["week"], errors="coerce").fillna(0) == 0]
        if "season_type" in n:
            n = n[n["season_type"].astype(str) == "REG"]
        n = n.rename(columns={"player_gsis_id": "receiver"})
        n["season"] = pd.to_numeric(n["season"], errors="coerce")
        j = q.merge(n[["receiver", "season", "avg_yac_above_expectation"]], on=["receiver", "season"], how="inner")
        if len(j) >= 10:
            out["rec_yacoe_corr_ngs"] = {"n": int(len(j)), "ours": _io.pearson(j["yacoe"], j["avg_yac_above_expectation"]),
                                         "nflverse": _io.pearson(j["yacoe_nflverse"], j["avg_yac_above_expectation"])}
    return out


def for_season(season: int, use_cache: bool = True) -> dict:
    f = current_fit()
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION, (f or {}).get("key"))

    def build():
        t = season_rows(season, fit_=f)
        return {"receivers": _io.clean(receiver_table(t).to_dict("records")) if len(t) else []}
    return _io.cached("yac", str(int(season)), key, build, use_cache)


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("yac", f)
    return {k: v for k, v in f.items() if k != "models"}
