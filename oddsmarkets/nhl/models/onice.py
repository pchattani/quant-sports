"""
On-ice rates: 5v5, power play and penalty kill, per 60, raw and score- and venue-adjusted, relative to team.

From the enriched stints (`_stints`): for every skater and strength role (5v5; pp = his side has more skaters with
both nets manned; pk the reverse) the time on ice and the on-ice counts for and against — shot attempts (CF/CA),
unblocked attempts (FF/FA), shots on goal (SF/SA), goals (GF/GA) and expected goals (xGF/xGA) — as per-60 rates and
shares (CF%, FF%, xGF%, GF%). `_adj` columns use the score/venue-adjusted counts (each event weighted 0.5 / the
league's share for a side in that score state at that venue, at 5v5; `_stints.adjust_weights`).

Relative to team (5v5): for each player-team, off-ice = the team's 5v5 totals minus the player's on-ice totals;
rel per 60 = on - off, rel % = on% - off%; a traded player's rel values are TOI-weighted across his teams.
Deployment: oz_start_pct = offensive-zone faceoff starts / (offensive + defensive) of the stints he started.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io, _stints
from oddsmarkets.nhl.models.shooting import frame_rows

MODEL_VERSION = "nhlonice-1"
PAIRS = [("cf", "ca"), ("ff", "fa"), ("sf", "sa"), ("gf", "ga"), ("xgf", "xga")]
ROLES = ("5v5", "pp", "pk")


def _per60(n, toi_s):
    return 3600.0 * np.asarray(n, float) / np.where(np.asarray(toi_s, float) > 0, toi_s, np.nan)


def _pct(f, a):
    f, a = np.asarray(f, float), np.asarray(a, float)
    return f / np.where(f + a > 0, f + a, np.nan)


def team_totals(st: pd.DataFrame) -> pd.DataFrame:
    """Per team and role: toi (s) and for/against sums (raw and adjusted), from the stints (one row per side)."""
    parts = []
    for side in ("h", "a"):
        o = "a" if side == "h" else "h"
        role = np.array([_stints.ROLE.get(s, ("other", "other"))[0 if side == "h" else 1] for s in st["strength"]], dtype=object)
        d = {"team": st["home_team" if side == "h" else "away_team"].to_numpy(object), "role": role,
             "toi": st["dur"].to_numpy(float)}
        for k in _stints.METRICS:
            f, a = ("xgf", "xga") if k == "xg" else (f"{k[0]}f", f"{k[0]}a")
            for suf in ("", "_adj"):
                d[f + suf] = st[f"{side}_{k}{suf}"].to_numpy(float)
                d[a + suf] = st[f"{o}_{k}{suf}"].to_numpy(float)
        parts.append(pd.DataFrame(d))
    t = pd.concat(parts, ignore_index=True)
    return t.groupby(["team", "role"]).sum(numeric_only=True)


def player_table(st: pd.DataFrame) -> pd.DataFrame:
    """One row per player: TOI and on-ice rates by role, adjusted rates, relative-to-team (5v5), deployment."""
    g = _stints.player_sums(st, ("team", "role"), ROLES)
    if not len(g):
        return pd.DataFrame(columns=["player_id"])
    g = g.reorder_levels(["player", "team", "role"])
    tt = team_totals(st)
    rows = {}
    for role in ROLES:
        if role not in g.index.get_level_values("role"):
            continue
        r = g.xs(role, level="role")
        pre = "" if role == "5v5" else f"{role}_"
        ptot = r.groupby(level="player").sum()
        cols = {f"{pre}toi": ptot["dur"].to_numpy(float) / 60.0}
        for f, a in PAIRS:
            for suf in ("", "_adj"):
                cols[f"{pre}{f}60{suf}"] = _per60(ptot[f + suf], ptot["dur"])
                cols[f"{pre}{a}60{suf}"] = _per60(ptot[a + suf], ptot["dur"])
                cols[f"{pre}{f}_pct{suf}"] = _pct(ptot[f + suf], ptot[a + suf])
        out = pd.DataFrame(cols, index=ptot.index)
        if role == "5v5":
            out["oz_start_pct"] = ptot["oz"] / (ptot["oz"] + ptot["dz"]).where(ptot["oz"] + ptot["dz"] > 0)
            # relative to team, per player-team then TOI-weighted
            team = tt.xs(role, level="role")
            pt = r.reset_index()
            tm = team.reindex(pt["team"].to_numpy())
            off_toi = tm["toi"].to_numpy(float) - pt["dur"].to_numpy(float)
            rel = pd.DataFrame({"player": pt["player"].to_numpy(), "w": pt["dur"].to_numpy(float)})
            for f, a in (("cf", "ca"), ("xgf", "xga"), ("gf", "ga")):
                for suf in ("", "_adj"):
                    of = tm[f + suf].to_numpy(float) - pt[f + suf].to_numpy(float)
                    oa = tm[a + suf].to_numpy(float) - pt[a + suf].to_numpy(float)
                    rel[f"{f}60_rel{suf}"] = _per60(pt[f + suf], pt["dur"]) - _per60(of, off_toi)
                    rel[f"{a}60_rel{suf}"] = _per60(pt[a + suf], pt["dur"]) - _per60(oa, off_toi)
                    rel[f"{f}_pct_rel{suf}"] = _pct(pt[f + suf], pt[a + suf]) - _pct(of, oa)
            vals = [c for c in rel.columns if c not in ("player", "w")]
            extra = {}
            for c in vals:
                v = rel[c].to_numpy(float)
                ok = np.isfinite(v)
                num = pd.Series(np.where(ok, v * rel["w"].to_numpy(float), 0.0)).groupby(rel["player"].to_numpy()).sum()
                den = pd.Series(np.where(ok, rel["w"].to_numpy(float), 0.0)).groupby(rel["player"].to_numpy()).sum()
                extra[c] = (num / den.where(den > 0)).reindex(out.index)
            out = pd.concat([out, pd.DataFrame(extra, index=out.index)], axis=1)
            team_main = r["dur"].reset_index().sort_values("dur").drop_duplicates("player", keep="last").set_index("player")["team"]
            out["team"] = team_main.reindex(out.index)
        rows[role] = out.copy()
    res = None
    for role in ROLES:
        if role in rows:
            res = rows[role] if res is None else res.join(rows[role], how="outer")
    res.index = [int(p) for p in res.index]
    res.index.name = "player_id"
    res = res.reset_index()
    for c in ("toi", "pp_toi", "pk_toi"):
        if c in res:
            res[c] = res[c].fillna(0.0)
    lead = ["player_id", "team", "toi", "pp_toi", "pk_toi"]
    return res[[c for c in lead if c in res] + [c for c in res.columns if c not in lead]]


def team_table(st: pd.DataFrame) -> pd.DataFrame:
    tt = team_totals(st).reset_index()
    tt = tt[tt["role"].isin(ROLES)]
    out = pd.DataFrame({"team": tt["team"], "role": tt["role"], "toi": tt["toi"] / 60.0})
    for f, a in PAIRS:
        for suf in ("", "_adj"):
            out[f"{f}60{suf}"] = _per60(tt[f + suf], tt["toi"])
            out[f"{a}60{suf}"] = _per60(tt[a + suf], tt["toi"])
            out[f"{f}_pct{suf}"] = _pct(tt[f + suf], tt[a + suf])
    return out.reset_index(drop=True)


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import xg
    season = _io.sid(season)
    if not _io.stints_path(season).exists():
        return {"ok": False, "reason": "no stints for this season"}
    f = xg.current_fit() or {}
    key = _io.file_key(_io.events_path(season), _io.stints_path(season), _io.store_path(season), MODEL_VERSION, f.get("key"),
                       f.get("platt"))

    def build():
        st = _stints.for_season(season, use_cache)
        if not len(st):
            return {"ok": False, "reason": "no stints"}
        p = player_table(st)
        t = team_table(st)
        return {"ok": True, "season": season, "n": int(len(p)), "players": frame_rows(p), "teams": frame_rows(t),
                "unattributed_attempts": int(st.attrs.get("unattributed", 0))}

    return _io.cached("onice", str(season), key, build, use_cache)
