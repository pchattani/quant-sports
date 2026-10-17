"""
Goalies: goals saved above expected (GSAx), overall, by danger band and by shot type, shrunk.

Every unblocked attempt on a manned net is charged to the goalie in it (`goalie` on the event, else the defending
side's goalie slot). Per goalie and season:

    fa (unblocked attempts faced), sa (shots on goal faced), ga (goals against), xga (summed xG)
    gsax = xga - ga                                     (positive = better than an average goalie)
    gsax_low / gsax_med / gsax_high                     by xG band (low < 0.08 <= medium < 0.20 <= high)
    gsax_<shot type>, gsax_rebound, gsax_rush           by shot type and situation
    sv_pct, xsv_pct (1 - xG on shots on goal / shots on goal), dsv_pct = sv_pct - xsv_pct
    gsax100 = 100 * gsax / fa, gsax60 (per 60 minutes in net, from the stints)
    talent = gsax / (fa + k), gsax_shrunk = fa * talent  (k: stabilise "gsax100", attempts faced)

The bands and the shot types partition the attempts, so each set of components sums to gsax exactly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io
from oddsmarkets.nhl.models.shooting import frame_rows

MODEL_VERSION = "nhlgoal-1"
BANDS = ("low", "medium", "high")
TYPES = ["wrist", "snap", "slap", "backhand", "tip-in", "deflected", "wrap-around", "other"]


def faced(sh: pd.DataFrame) -> pd.DataFrame:
    """Attempts on a manned net with the goalie charged (column `g`)."""
    s = sh[sh["empty_net"].to_numpy(float) == 0].copy()
    g = pd.to_numeric(s["goalie"], errors="coerce").to_numpy(float)
    if "hg" in s and "ag" in s:
        slot = np.where(s["is_home"].to_numpy(float) == 1, s["ag"].to_numpy(float), s["hg"].to_numpy(float))
        g = np.where(np.isfinite(g), g, slot)
    s["g"] = g
    s = s[np.isfinite(s["g"].to_numpy(float)) & np.isfinite(s["xg"].to_numpy(float))]
    s["stype"] = s["shot_type"].map(lambda v: v if v in TYPES else "other")
    return s


def table(sh: pd.DataFrame, k: float | None = None, toi: pd.Series | None = None) -> pd.DataFrame:
    from oddsmarkets.nhl.models import stabilise
    from oddsmarkets.nhl.models.xg import DANGER
    k = float(k if k is not None else stabilise.shrink_k("gsax100"))
    s = faced(sh)
    if not len(s):
        return pd.DataFrame(columns=["player_id"])
    s["sog"] = s["type"].isin(["goal", "shot-on-goal"]).astype(float)
    s["sx"] = s["xg"] - s["goal"]
    band = np.where(s["xg"] >= DANGER[1], "high", np.where(s["xg"] >= DANGER[0], "medium", "low"))
    s["band"] = band
    grp = s.groupby("g")
    t = grp.agg(fa=("goal", "size"), sa=("sog", "sum"), ga=("goal", "sum"), xga=("xg", "sum"))
    t["gsax"] = t["xga"] - t["ga"]
    for b in BANDS:
        m = s["band"] == b
        t[f"gsax_{b}"] = s[m].groupby("g")["sx"].sum().reindex(t.index).fillna(0.0)
        t[f"fa_{b}"] = s[m].groupby("g").size().reindex(t.index).fillna(0.0)
        sog = s[m & (s["sog"] == 1)]
        t[f"sv_pct_{b}"] = 1 - sog.groupby("g")["goal"].mean().reindex(t.index)
    for ty in TYPES:
        t[f"gsax_{ty}"] = s[s["stype"] == ty].groupby("g")["sx"].sum().reindex(t.index).fillna(0.0)
    for c in ("rebound", "rush"):
        t[f"gsax_{c}"] = s[s[c].to_numpy(float) == 1].groupby("g")["sx"].sum().reindex(t.index).fillna(0.0)
    opp = s.assign(gt=np.where(s["is_home"].to_numpy(float) == 1, s["away_team"], s["home_team"]))
    gt = opp.groupby(["g", "gt"]).size().reset_index(name="n").sort_values("n").drop_duplicates("g", keep="last")
    t["team"] = gt.set_index("g")["gt"].reindex(t.index)
    sog = s[s["sog"] == 1]
    t["sv_pct"] = 1 - t["ga"] / t["sa"].where(t["sa"] > 0)
    t["xsv_pct"] = 1 - sog.groupby("g")["xg"].sum().reindex(t.index) / t["sa"].where(t["sa"] > 0)
    t["dsv_pct"] = t["sv_pct"] - t["xsv_pct"]
    t["gsax_med"] = t["gsax_medium"]                 # the short name builder D's catalogue reads
    t["gsax100"] = 100 * t["gsax"] / t["fa"]
    t["talent"] = t["gsax"] / (t["fa"] + k)
    t["gsax_shrunk"] = t["fa"] * t["talent"]
    if toi is not None:
        t["toi"] = toi.reindex(t.index).astype(float)
        t["gsax60"] = 3600 * t["gsax"] / t["toi"].where(t["toi"] > 0)
    else:
        t["toi"] = np.nan
        t["gsax60"] = np.nan
    t["k"] = k
    t.index = [int(p) for p in t.index]
    t.index.name = "player_id"
    return t.reset_index().sort_values("gsax", ascending=False).reset_index(drop=True)


def goalie_toi(st: pd.DataFrame) -> pd.Series:
    if st is None or not len(st):
        return pd.Series(dtype=float)
    a = pd.concat([pd.DataFrame({"g": st["hg"].to_numpy(float), "d": st["dur"].to_numpy(float)}),
                   pd.DataFrame({"g": st["ag"].to_numpy(float), "d": st["dur"].to_numpy(float)})])
    a = a[np.isfinite(a["g"])]
    return a.groupby("g")["d"].sum()


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import stabilise, xg
    season = _io.sid(season)
    if not _io.events_path(season).exists():
        return {"ok": False, "reason": "no events for this season"}
    f = xg.current_fit() or {}
    k = stabilise.shrink_k("gsax100")
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), MODEL_VERSION, f.get("key"), k)

    def build():
        sh = xg.shot_table(season, use_cache)
        if not len(sh) or sh["xg"].isna().all():
            return {"ok": False, "reason": "no xG for this season"}
        toi = goalie_toi(_io.stints_raw(season)) if _io.stints_path(season).exists() else None
        t = table(sh, k, toi)
        return {"ok": True, "season": season, "k": k, "n": int(len(t)), "goalies": frame_rows(t)}

    return _io.cached("goalies", str(season), key, build, use_cache)
