"""
Completion probability (cp) and completion percentage over expected (CPOE), our own.

Rows: every targeted pass (pass attempt with a receiver, not a sack or spike or try, air yards known; as
nflfastR, so throwaways and batted balls without a target are out); label: completed. Air yards are
recorded from 2006, but in 2006-2008 only on completions (an "aimed pass" then is 99.8% complete), so cp
starts in 2009 (CP_FIRST).
LightGBM binary in feature tiers, each fitted on the seasons its data covers and cross-fitted by season;
every pass is predicted by the richest tier available for its season:

* base (1999->): air yards, yard line, room past the target (yard line - air yards), distance, down,
  goal to go, seconds left in the half, score, pass location (left/middle/right), QB hit, shotgun,
  no-huddle, roof, wind, era;
* participation (2016-2025): + pressure, time to throw, pass rushers, box count, coverage shell and
  man/zone;
* FTN (2022->): + blitzers, pass rushers, box, out of pocket, play action, screen;
* FTN + participation (2022-2025): both.

Pressure, blitz and coverage are inputs, so CPOE credits a QB for completing under pressure rather than
penalising him for it (and does not credit him for avoiding it: sack and pressure rates are separate in
pressure.py). Each season's predictions are recentred (one logit shift per season) so the league's
mean cp equals its completion rate: CPOE is measured against that season's league, and the shift absorbs
year-to-year drift a cross-fitted model can't see (`season_shift`, reported per season; for the season
in progress it uses the passes so far). Drops (FTN, 2022->) are not inputs; `cpoe_drop_adj` removes dropped passes from both sides
of the QB's CPOE. Receivers get catch rate over expected (CROE) on their targets.

Validation: log-loss and calibration of our cp against nflverse's `cp` on the same passes (nflfastR's cp
model was trained on earlier seasons: in-sample there), and the correlation of QB-season CPOE (ours,
nflverse's, NGS's completion_percentage_above_expectation from 2016) for QBs with >= MIN_ATT attempts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "cp-3"
CP_FIRST = 2009            # 2006-2008 pbp carries air yards on completions only (checked: 99.8% complete)
BASE = ["air_yards", "yardline_100", "room", "ydstogo", "down", "goal_to_go", "half_seconds_remaining",
        "score_differential", "loc_code", "qb_hit", "shotgun", "no_huddle", "roof_code", "wind", "era"]
PART = ["p_pressure", "p_ttt", "p_rushers", "p_box", "cov_code", "mz_code"]
FTN = ["f_blitzers", "f_rushers", "f_box", "f_oop", "f_pa", "f_screen"]
TIERS = [{"name": "base", "lo": 2009, "hi": None, "features": BASE},
         {"name": "part", "lo": 2016, "hi": 2025, "features": BASE + PART},
         {"name": "ftn", "lo": 2022, "hi": None, "features": BASE + FTN},
         {"name": "ftn_part", "lo": 2022, "hi": 2025, "features": BASE + FTN + PART}]
MONOTONE = {"air_yards": -1}
PARAMS = {"objective": "binary", "learning_rate": 0.06, "num_leaves": 31, "min_data_in_leaf": 300, "lambda_l2": 5.0}
MIN_ATT = 200


def rows(d: pd.DataFrame) -> pd.DataFrame:
    pa = pd.to_numeric(d["pass_attempt"], errors="coerce").fillna(0) == 1
    sk = pd.to_numeric(d["sack"], errors="coerce").fillna(0) == 1
    sp = pd.to_numeric(d.get("qb_spike"), errors="coerce").fillna(0) == 1 if "qb_spike" in d else False
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1 if "two_point_attempt" in d else False
    ay = pd.to_numeric(d["air_yards"], errors="coerce")
    m = pa & ~sk & ~sp & ~tp & ay.notna() & (pd.to_numeric(d["season"], errors="coerce") >= CP_FIRST) & d["passer_player_id"].notna() & d["receiver_player_id"].notna()
    s = d[m]
    out = pd.DataFrame(index=s.index)
    for c in ("air_yards", "yardline_100", "ydstogo", "down", "goal_to_go", "half_seconds_remaining", "score_differential",
              "loc_code", "qb_hit", "shotgun", "no_huddle", "roof_code", "wind", "p_pressure", "p_ttt", "p_rushers", "p_box",
              "f_blitzers", "f_rushers", "f_box", "f_oop", "f_pa", "f_screen", "f_drop", "f_int_worthy", "f_catchable"):
        out[c] = pd.to_numeric(s[c], errors="coerce").astype(float) if c in s else np.nan
    out["room"] = out["yardline_100"] - out["air_yards"]
    out["era"] = pd.to_numeric(s["season"], errors="coerce").astype(float)
    out["cov_code"] = s["p_coverage"].map(_io.COVERAGE_CODE).astype(float) if "p_coverage" in s else np.nan
    out["mz_code"] = s["p_manzone"].map(_io.MANZONE_CODE).astype(float) if "p_manzone" in s else np.nan
    out["y"] = pd.to_numeric(s["complete_pass"], errors="coerce").fillna(0).astype(float)
    out["season"] = out["era"]
    out["game_id"] = s["game_id"].astype(str)
    out["play_id"] = pd.to_numeric(s["play_id"], errors="coerce").astype(float)
    out["passer"] = s["passer_player_id"].astype(object)
    out["passer_name"] = s["passer_player_name"].astype(object) if "passer_player_name" in s else None
    out["receiver"] = s["receiver_player_id"].astype(object)
    out["receiver_name"] = s["receiver_player_name"].astype(object) if "receiver_player_name" in s else None
    out["team"] = s["posteam"].astype(object)
    out["nf_cp"] = pd.to_numeric(s.get("cp"), errors="coerce").astype(float) if "cp" in s else np.nan
    return out.reset_index(drop=True)


def fit(seasons=None, k: int = 5, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION, k)
    if use_cache:
        f = _io.get_fit("completion", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    t = _io.stack(seasons, rows)
    fitd, oof = _io.fit_tiers(t, TIERS, "binary", PARAMS, k, monotone=MONOTONE)
    t["cp_raw"] = oof
    t["cp_ours"], shifts = recentre(t)
    fitd["season_shift"] = shifts
    fitd.update({"ok": True, "version": MODEL_VERSION, "key": key, "seasons": seasons, "n": int(len(t)),
                 "validation": validate(t)})
    for s in np.unique(t["season"].to_numpy(int)):
        m = t["season"].to_numpy(int) == s
        _io.oof_store("cp", int(s), t.loc[m, ["game_id", "play_id", "cp_raw"]].reset_index(drop=True))
    _io.store_fit("completion", fitd)
    del t
    return fitd


def current_fit() -> dict | None:
    return _io.get_fit("completion", MODEL_VERSION)


def season_rows(season: int, d: pd.DataFrame | None = None, fit_: dict | None = None) -> pd.DataFrame:
    """One season's aimed passes with cp_ours (cross-fitted when available, else the production tiers)."""
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return pd.DataFrame()
    t = rows(d)
    o = _io.oof_load("cp", season)
    if o is not None and len(o) and "cp_raw" in o:
        t = t.merge(o, on=["game_id", "play_id"], how="left")
    else:
        t["cp_raw"] = np.nan
    miss = t["cp_raw"].isna().to_numpy()
    f = fit_ or current_fit()
    if miss.any() and f is not None:
        t.loc[miss, "cp_raw"] = _io.predict_tiers(f, t[miss], TIERS)
    t["cp_ours"], _ = recentre(t)
    return t


def recentre(t: pd.DataFrame) -> tuple[np.ndarray, dict]:
    """Per season, the logit shift that makes mean cp equal the completion rate; (cp, {season: shift})."""
    p = t["cp_raw"].to_numpy(float)
    y = t["y"].to_numpy(float)
    s = t["season"].to_numpy(float)
    out = p.copy()
    shifts = {}
    for yv in np.unique(s[np.isfinite(s)]):
        m = (s == yv) & np.isfinite(p)
        if m.sum() < 50:
            continue
        lp = _io.logit(p[m])
        target = y[m].mean()
        lo, hi = -2.0, 2.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if _io.sigmoid(lp + mid).mean() < target:
                lo = mid
            else:
                hi = mid
        d = (lo + hi) / 2
        out[m] = _io.sigmoid(lp + d)
        shifts[str(int(yv))] = round(float(d), 5)
    return out, shifts


def passer_table(t: pd.DataFrame) -> pd.DataFrame:
    x = t.assign(res=t["y"] - t["cp_ours"], nres=t["y"] - t["nf_cp"])
    nd = x["f_drop"].fillna(0) != 1
    x["res_nd"] = np.where(nd, x["res"], np.nan)
    g = x.groupby(["passer", "season"]).agg(name=("passer_name", "last"), team=("team", "last"), att=("y", "size"),
                                           comp=("y", "sum"), exp=("cp_ours", "sum"), cpoe=("res", "mean"),
                                           cpoe_nflverse=("nres", "mean"), cpoe_drop_adj=("res_nd", "mean"),
                                           adot=("air_yards", "mean")).reset_index()
    for c in ("cpoe", "cpoe_nflverse", "cpoe_drop_adj"):
        g[c] = 100 * g[c]
    return g.sort_values("att", ascending=False).reset_index(drop=True)


def receiver_table(t: pd.DataFrame) -> pd.DataFrame:
    x = t[t["receiver"].notna()].assign(res=lambda z: z["y"] - z["cp_ours"])
    g = x.groupby(["receiver", "season"]).agg(name=("receiver_name", "last"), team=("team", "last"), targets=("y", "size"),
                                             rec=("y", "sum"), exp=("cp_ours", "sum"), croe=("res", "mean"),
                                             adot=("air_yards", "mean"), drops=("f_drop", "sum")).reset_index()
    g["croe"] = 100 * g["croe"]
    return g.sort_values("targets", ascending=False).reset_index(drop=True)


def validate(t: pd.DataFrame) -> dict:
    y, p, n = t["y"].to_numpy(float), t["cp_ours"].to_numpy(float), t["nf_cp"].to_numpy(float)
    ok = np.isfinite(p) & np.isfinite(n)
    out = {"n": int(ok.sum())}
    if ok.any():
        out["ours"] = {"logloss": round(_io.log_loss(y[ok], p[ok]), 5), "brier": round(_io.brier(y[ok], p[ok]), 5),
                       "calibration": _io.calibration(y[ok], p[ok])}
        if "cp_raw" in t:
            r = t["cp_raw"].to_numpy(float)
            out["ours_before_recentring"] = {"logloss": round(_io.log_loss(y[ok], r[ok]), 5),
                                             "calibration": _io.calibration(y[ok], r[ok])}
        out["nflverse_cp"] = {"logloss": round(_io.log_loss(y[ok], n[ok]), 5), "brier": round(_io.brier(y[ok], n[ok]), 5),
                              "calibration": _io.calibration(y[ok], n[ok])}
    s = t["season"].to_numpy(int)
    by = {}
    for yv in np.unique(s):
        m = (s == yv) & ok
        if m.sum() > 100:
            by[int(yv)] = {"n": int(m.sum()), "ours": round(_io.log_loss(y[m], p[m]), 5), "nflverse": round(_io.log_loss(y[m], n[m]), 5)}
    out["by_season"] = by
    pt = passer_table(t)
    q = pt[pt["att"] >= MIN_ATT]
    out["qb_cpoe_corr_nflverse"] = _io.pearson(q["cpoe"], q["cpoe_nflverse"])
    out["n_qb_seasons"] = int(len(q))
    ngs = ngs_compare(q)
    if ngs:
        out["qb_cpoe_corr_ngs"] = ngs
    return out


def ngs_compare(q: pd.DataFrame) -> dict | None:
    """Correlation of QB-season CPOE with NGS completion_percentage_above_expectation (season rows, week 0)."""
    n = _io.load_ngs("passing")
    if n is None or not len(n) or "completion_percentage_above_expectation" not in n:
        return None
    n = n.copy()
    if "week" in n:
        n = n[pd.to_numeric(n["week"], errors="coerce").fillna(0) == 0]
    if "season_type" in n:
        n = n[n["season_type"].astype(str) == "REG"]
    n = n.rename(columns={"player_gsis_id": "passer"})
    n["season"] = pd.to_numeric(n["season"], errors="coerce")
    j = q.merge(n[["passer", "season", "completion_percentage_above_expectation"]], on=["passer", "season"], how="inner")
    if len(j) < 10:
        return None
    return {"n": int(len(j)), "ours": _io.pearson(j["cpoe"], j["completion_percentage_above_expectation"]),
            "nflverse": _io.pearson(j["cpoe_nflverse"], j["completion_percentage_above_expectation"]),
            "note": "NGS season rows include the postseason only when season_type allows; REG season compared with all games"}


def for_season(season: int, use_cache: bool = True) -> dict:
    f = current_fit()
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION, (f or {}).get("key"))

    def build():
        t = season_rows(season, fit_=f)
        if not len(t):
            return {"passers": [], "receivers": []}
        return {"passers": _io.clean(passer_table(t).to_dict("records")),
                "receivers": _io.clean(receiver_table(t).to_dict("records"))}
    return _io.cached("completion", str(int(season)), key, build, use_cache)


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("completion", f)
    return {k: v for k, v in f.items() if k != "models"}
