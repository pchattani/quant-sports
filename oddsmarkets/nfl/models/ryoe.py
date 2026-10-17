"""
Rushing yards over expected (RYOE), our own.

Rows: designed runs (play_type run, not a QB scramble, kneel or try); target: rushing yards clipped to
[-15, yard line] (a run can't gain more than the distance to the goal line). LightGBM regression (the
conditional mean) in feature tiers, cross-fitted by season, richest tier per season:

* base (1999->): yard line, distance, down, goal to go, seconds left in the half, score, run location and
  gap, shotgun, no-huddle, roof, era;
* participation (2016-2025): + defenders in the box, offensive personnel (RB / TE / WR counts), formation;
* FTN (2022->): + box count, backfield count, motion, RPO, QB sneak;
* FTN + participation (2022-2025).

Team strength and the defence's quality are deliberately not inputs: RYOE credits the rusher and his
blocking together (NGS's tracking-based RYOE also sees the defenders' positions and speeds, which we
can't). Validation: RMSE against nflverse-free baselines (a situation-only model is tier base itself) and
the correlation of rusher-season RYOE per attempt with NGS rush_yards_over_expected_per_att (2016->).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "ryoe-1"
BASE = ["yardline_100", "ydstogo", "down", "goal_to_go", "half_seconds_remaining", "score_differential",
        "run_loc_code", "gap_code", "shotgun", "no_huddle", "roof_code", "era"]
PART = ["p_box", "n_rb", "n_te", "n_wr", "form_code"]
FTN = ["f_box", "f_backfield", "f_motion", "f_rpo", "f_sneak"]
TIERS = [{"name": "base", "lo": 1999, "hi": None, "features": BASE},
         {"name": "part", "lo": 2016, "hi": 2025, "features": BASE + PART},
         {"name": "ftn", "lo": 2022, "hi": None, "features": BASE + FTN},
         {"name": "ftn_part", "lo": 2022, "hi": 2025, "features": BASE + FTN + PART}]
MONOTONE = {"p_box": -1, "f_box": -1}
PARAMS = {"objective": "regression", "learning_rate": 0.06, "num_leaves": 31, "min_data_in_leaf": 300, "lambda_l2": 5.0}
FORMATIONS = {"SHOTGUN": 0, "SINGLEBACK": 1, "I_FORM": 2, "PISTOL": 3, "EMPTY": 4, "JUMBO": 5, "WILDCAT": 6, "UNDER CENTER": 7}
MIN_ATT = 100


def rows(d: pd.DataFrame) -> pd.DataFrame:
    pt = d["play_type"].astype(str)
    scr = pd.to_numeric(d.get("qb_scramble"), errors="coerce").fillna(0) == 1 if "qb_scramble" in d else False
    kn = pd.to_numeric(d.get("qb_kneel"), errors="coerce").fillna(0) == 1 if "qb_kneel" in d else False
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1 if "two_point_attempt" in d else False
    ry = pd.to_numeric(d["rushing_yards"], errors="coerce")
    ry = ry.fillna(pd.to_numeric(d["yards_gained"], errors="coerce"))
    m = (pt == "run") & ~scr & ~kn & ~tp & ry.notna() & d["rusher_player_id"].notna()
    s = d[m]
    out = pd.DataFrame(index=s.index)
    for c in ("yardline_100", "ydstogo", "down", "goal_to_go", "half_seconds_remaining", "score_differential", "run_loc_code",
              "gap_code", "shotgun", "no_huddle", "roof_code", "p_box", "f_box", "f_backfield", "f_motion", "f_rpo", "f_sneak"):
        out[c] = pd.to_numeric(s[c], errors="coerce").astype(float) if c in s else np.nan
    pc = _io.personnel_counts(s["p_off_personnel"]) if "p_off_personnel" in s else pd.DataFrame(index=s.index, columns=["n_rb", "n_te", "n_wr"])
    for c in ("n_rb", "n_te", "n_wr"):
        out[c] = pc[c].astype(float)
    out["form_code"] = s["p_formation"].map(FORMATIONS).astype(float) if "p_formation" in s else np.nan
    out["era"] = pd.to_numeric(s["season"], errors="coerce").astype(float)
    yards = ry[m].astype(float)
    out["yards"] = yards
    out["y"] = np.clip(yards, -15, out["yardline_100"])
    out["season"] = out["era"]
    out["game_id"] = s["game_id"].astype(str)
    out["play_id"] = pd.to_numeric(s["play_id"], errors="coerce").astype(float)
    out["rusher"] = s["rusher_player_id"].astype(object)
    out["rusher_name"] = s["rusher_player_name"].astype(object) if "rusher_player_name" in s else None
    out["team"] = s["posteam"].astype(object)
    out["epa"] = pd.to_numeric(s.get("epa"), errors="coerce").astype(float) if "epa" in s else np.nan
    out["success"] = (out["epa"] > 0).astype(float)
    return out.reset_index(drop=True)


def fit(seasons=None, k: int = 5, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("ryoe", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    t = _io.stack(seasons, rows)
    fitd, oof = _io.fit_tiers(t, TIERS, "regression", PARAMS, k, monotone=MONOTONE)
    t["xry"] = oof
    fitd.update({"ok": True, "version": MODEL_VERSION, "key": key, "seasons": seasons, "n": int(len(t)), "validation": validate(t)})
    for s in np.unique(t["season"].to_numpy(int)):
        m = t["season"].to_numpy(int) == s
        _io.oof_store("ryoe", int(s), t.loc[m, ["game_id", "play_id", "xry"]].reset_index(drop=True))
    _io.store_fit("ryoe", fitd)
    del t
    return fitd


def current_fit() -> dict | None:
    return _io.get_fit("ryoe", MODEL_VERSION)


def season_rows(season: int, d: pd.DataFrame | None = None, fit_: dict | None = None) -> pd.DataFrame:
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame()
    t = rows(d)
    o = _io.oof_load("ryoe", season)
    t = t.merge(o, on=["game_id", "play_id"], how="left") if o is not None and len(o) else t.assign(xry=np.nan)
    miss = t["xry"].isna().to_numpy()
    f = fit_ or current_fit()
    if miss.any() and f is not None:
        t.loc[miss, "xry"] = _io.predict_tiers(f, t[miss], TIERS)
    return t


def rusher_table(t: pd.DataFrame) -> pd.DataFrame:
    x = t.assign(oe=t["yards"] - t["xry"], oe_c=t["y"] - t["xry"])
    g = x.groupby(["rusher", "season"]).agg(name=("rusher_name", "last"), team=("team", "last"), att=("yards", "size"),
                                           yards=("yards", "sum"), exp=("xry", "sum"), ryoe_per_att=("oe", "mean"),
                                           ryoe_clipped_per_att=("oe_c", "mean"), success=("success", "mean"),
                                           box=("p_box", "mean")).reset_index()
    g["ryoe"] = g["yards"] - g["exp"]
    return g.sort_values("att", ascending=False).reset_index(drop=True)


def validate(t: pd.DataFrame) -> dict:
    y, p = t["y"].to_numpy(float), t["xry"].to_numpy(float)
    ok = np.isfinite(y) & np.isfinite(p)
    out = {"n": int(ok.sum()), "rmse": float(np.sqrt(np.mean((y[ok] - p[ok]) ** 2))) if ok.any() else None,
           "rmse_mean_only": float(np.std(y[ok])) if ok.any() else None}
    rt = rusher_table(t)
    q = rt[rt["att"] >= MIN_ATT]
    n = _io.load_ngs("rushing")
    if n is not None and len(n) and "rush_yards_over_expected_per_att" in n:
        n = n.copy()
        if "week" in n:
            n = n[pd.to_numeric(n["week"], errors="coerce").fillna(0) == 0]
        if "season_type" in n:
            n = n[n["season_type"].astype(str) == "REG"]
        n = n.rename(columns={"player_gsis_id": "rusher"})
        n["season"] = pd.to_numeric(n["season"], errors="coerce")
        j = q.merge(n[["rusher", "season", "rush_yards_over_expected_per_att"]], on=["rusher", "season"], how="inner")
        if len(j) >= 5:
            out["ngs"] = {"n": int(len(j)), "corr": _io.pearson(j["ryoe_per_att"], j["rush_yards_over_expected_per_att"]),
                          "corr_ypc": _io.pearson(j["yards"] / j["att"], j["rush_yards_over_expected_per_att"])}
    return out


def for_season(season: int, use_cache: bool = True) -> dict:
    f = current_fit()
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION, (f or {}).get("key"))

    def build():
        t = season_rows(season, fit_=f)
        return {"rushers": _io.clean(rusher_table(t).to_dict("records")) if len(t) else []}
    return _io.cached("ryoe", str(int(season)), key, build, use_cache)


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("ryoe", f)
    return {k: v for k, v in f.items() if k != "models"}
