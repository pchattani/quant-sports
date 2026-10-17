"""
Pitcher fatigue and health signals (descriptive, not medical).

All on the pitcher's primary fastball (prep.fastball_refs) unless stated.

* Within game: the slope of velocity, spin, release height, arm-side release side and extension against
  the pitcher's pitch count in the game, with each game's own level removed (a within-game regression:
  y - game mean on game_pitch - game mean), per 100 pitches; shrunk toward the league slope by the slope's
  sampling variance (empirical-Bayes weight w = tau^2 / (tau^2 + se^2)). League velocity by pitch-count band.
* Season: per game, the fastball's mean velocity / spin / release height / extension; baseline = the
  pitcher's season mean over games; `last3` = mean of the last three games minus baseline; `trend` the
  slope of game velocity per 30 days.
* Times through the order: xwOBA per plate appearance (estimated_woba_using_speedangle on balls in play,
  woba_value otherwise) by n_thruorder_pitcher (1, 2, 3+), each shrunk toward the league value by K_PA
  plate appearances; penalty = 3rd-time minus 1st-time.
* Workload flag: last3 velocity <= VELO_FLAG mph or spin <= SPIN_FLAG rpm against baseline, over at least
  MIN_GAMES games.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io, prep

MODEL_VERSION = "fatigue-1"
K_PA = 100
VELO_FLAG = -1.0
SPIN_FLAG = -75.0
MIN_GAMES = 5
MIN_PITCHES = 150
SIGNALS = {"velo": "release_speed", "spin": "release_spin_rate", "rel_z": "release_pos_z", "rel_side": "release_side_arm",
           "ext": "release_extension"}
BANDS = [0, 25, 50, 75, 100, 125, 400]


def fastballs(df: pd.DataFrame) -> pd.DataFrame:
    d = df[(df["pitch_type"] == df["fb_type"]) & df["release_speed"].notna()].copy()
    for c in SIGNALS.values():
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d


def within_game(fb: pd.DataFrame, min_pitches: int = MIN_PITCHES) -> tuple[pd.DataFrame, dict]:
    d = fb.copy()
    d["gp"] = d["game_pitch"].astype(float) / 100.0
    key = ["pitcher", "game_pk"]
    d["gp_c"] = d["gp"] - d.groupby(key)["gp"].transform("mean")
    res = {}
    league = {}
    for name, col in SIGNALS.items():
        y = d[col] - d.groupby(key)[col].transform("mean")
        ok = y.notna() & d["gp_c"].notna()
        t = pd.DataFrame({"p": d.loc[ok, "pitcher"], "x": d.loc[ok, "gp_c"], "y": y[ok]})
        t["xy"] = t["x"] * t["y"]
        t["xx"] = t["x"] ** 2
        g = t.groupby("p").agg(n=("x", "size"), sxy=("xy", "sum"), sxx=("xx", "sum"))
        lb = float(t["xy"].sum() / max(t["xx"].sum(), 1e-9))
        g["slope"] = g["sxy"] / g["sxx"].replace(0, np.nan)
        # residual variance per pitcher -> se of slope
        t["r"] = t["y"] - t["x"] * t["p"].map(g["slope"]).fillna(lb)
        s2 = t.groupby("p")["r"].var()
        g["se"] = np.sqrt(s2 / g["sxx"].replace(0, np.nan))
        q = g[g["n"] >= min_pitches]
        tau2 = max(float(q["slope"].var() - (q["se"] ** 2).mean()), 1e-6) if len(q) > 5 else float(g["slope"].var() or 1.0)
        w = tau2 / (tau2 + g["se"].fillna(np.inf) ** 2)
        g["shrunk"] = lb + w.fillna(0) * (g["slope"].fillna(lb) - lb)
        res[name] = g[["n", "slope", "se", "shrunk"]]
        league[name] = {"slope_per100": lb, "tau": float(np.sqrt(tau2))}
    bands = pd.cut(d["game_pitch"], BANDS, right=False)
    dv = d["release_speed"] - d.groupby("pitcher")["release_speed"].transform("mean")
    league["velo_by_band"] = {str(k): round(float(v), 3) for k, v in dv.groupby(bands, observed=True).mean().items()}
    out = pd.concat({k: v["shrunk"] for k, v in res.items()}, axis=1).add_suffix("_per100")
    out["n_fb"] = res["velo"]["n"]
    out["velo_per100_raw"] = res["velo"]["slope"]
    return out, league


def season_trend(fb: pd.DataFrame) -> pd.DataFrame:
    g = fb.groupby(["pitcher", "game_date", "game_pk"]).agg(n=("release_speed", "size"), velo=("release_speed", "mean"),
                                                             spin=("release_spin_rate", "mean"), rel_z=("release_pos_z", "mean"),
                                                             ext=("release_extension", "mean")).reset_index()
    g = g[g["n"] >= 5].sort_values(["pitcher", "game_date", "game_pk"])
    rows = {}
    for pid, x in g.groupby("pitcher"):
        base = x[["velo", "spin", "rel_z", "ext"]].mean()
        last = x.tail(3)[["velo", "spin", "rel_z", "ext"]].mean()
        days = (pd.to_datetime(x["game_date"]) - pd.to_datetime(x["game_date"]).min()).dt.days.to_numpy(float)
        v = x["velo"].to_numpy(float)
        trend = float(np.polyfit(days, v, 1)[0] * 30) if len(x) >= 3 and days.std() > 0 else np.nan
        rows[pid] = {"games": int(len(x)), "velo_base": base["velo"], "spin_base": base["spin"],
                     "velo_last3": last["velo"] - base["velo"], "spin_last3": last["spin"] - base["spin"],
                     "rel_z_last3_in": (last["rel_z"] - base["rel_z"]) * 12, "ext_last3_in": (last["ext"] - base["ext"]) * 12,
                     "rel_z_game_sd_in": float(x["rel_z"].std() * 12) if len(x) > 1 else np.nan,
                     "velo_trend_30d": trend,
                     "series": [[r.game_date, round(float(r.velo), 2), None if pd.isna(r.spin) else round(float(r.spin))]
                                for r in x.itertuples()]}
    out = pd.DataFrame.from_dict(rows, orient="index")
    if len(out):
        out["flag"] = (out["games"] >= MIN_GAMES) & ((out["velo_last3"] <= VELO_FLAG) | (out["spin_last3"] <= SPIN_FLAG))
    return out


def tto(df: pd.DataFrame, k: float = K_PA) -> tuple[pd.DataFrame, dict]:
    pa = df[(pd.to_numeric(df["woba_denom"], errors="coerce") == 1)].copy()
    xw = pd.to_numeric(pa.get("estimated_woba_using_speedangle"), errors="coerce")
    pa["xw"] = np.where(pa["inplay"].astype(bool) & xw.notna(), xw, pd.to_numeric(pa["woba_value"], errors="coerce"))
    t = pd.to_numeric(pa["n_thruorder_pitcher"], errors="coerce")
    pa["tto"] = np.clip(t, 1, 3)
    pa = pa[pa["tto"].notna() & pa["xw"].notna()]
    lg = pa.groupby("tto")["xw"].mean()
    g = pa.groupby(["pitcher", "tto"])["xw"].agg(["sum", "size"]).unstack()
    out = pd.DataFrame(index=g.index)
    for i in (1, 2, 3):
        if ("sum", i) in g:
            s, n = g[("sum", i)].fillna(0), g[("size", i)].fillna(0)
            out[f"xwoba_tto{i}"] = (s + k * lg.get(i, np.nan)) / (n + k)
            out[f"pa_tto{i}"] = n
    if "xwoba_tto1" in out and "xwoba_tto3" in out:
        out["tto_penalty"] = out["xwoba_tto3"] - out["xwoba_tto1"]
    league = {f"tto{int(i)}": float(v) for i, v in lg.items()}
    league["penalty"] = float(lg.get(3, np.nan) - lg.get(1, np.nan))
    return out, league


def analyse(df: pd.DataFrame) -> dict[str, Any]:
    fb = fastballs(df)
    wg, lw = within_game(fb)
    st = season_trend(fb)
    tt, lt = tto(df)
    return {"within": wg, "season": st, "tto": tt, "league": {"within": lw, "tto": lt}}


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    """{"ok","level","season","league": {...}, "pitchers": {pid: {within-game slopes, season trend, last3,
    flag, series, TTO}}, "flags": [pid...]}."""
    try:
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        key = _io.file_key(MODEL_VERSION, src)

        def build():
            df = prep.prepared(level, season)
            a = analyse(df)
            del df
            j = a["season"].join(a["within"], how="outer").join(a["tto"], how="outer")
            flags = [str(p) for p in j.index[j.get("flag", pd.Series(False, index=j.index)).fillna(False).astype(bool)]]
            return _io.clean({"ok": True, "level": level, "season": season, "version": MODEL_VERSION, "league": a["league"],
                              "pitchers": {str(k): v for k, v in j.to_dict("index").items()}, "flags": flags}, 4)

        return _io.cached("fatigue", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
