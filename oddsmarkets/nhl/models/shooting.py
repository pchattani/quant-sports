"""
Shooting: goals above expected (GAx) per shooter, with stabilisation shrinkage.

On a manned net (empty-net attempts carry no finishing signal and are excluded), per shooter and season:

    attempts  unblocked attempts (Fenwick), shots on goal (incl. goals), goals, ixG (summed xG)
    gax       goals - ixG
    talent    shrunk finishing per attempt = gax / (attempts + k)       (regressed to 0, the league mean)
    gax_shrunk = attempts * talent = gax * attempts / (attempts + k)

k is stabilise.py's split-half constant for "finishing" (goals - xG per unblocked attempt): with r(n) =
n / (n + k), talent is the posterior mean under a normal prior on finishing skill. Also reported: sh% (goals per
shot on goal), xsh% (ixG per attempt), fsh% (goals per attempt), sh% shrunk (shots, stabilise "sh_pct"), and the
5v5 / power-play split of GAx.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _io

MODEL_VERSION = "nhlshoot-1"
COLS = ["player_id", "team", "attempts", "shots", "goals", "ixg", "gax", "gax_per_att", "talent", "gax_shrunk", "sh_pct",
        "sh_pct_shrunk", "xsh_pct", "fsh_pct", "gax_5v5", "gax_pp", "ixg_5v5", "attempts_5v5", "k"]


def table(sh: pd.DataFrame, k: float | None = None, k_sh: float | None = None) -> pd.DataFrame:
    """Per-shooter table from a shot frame with shooter, team, type, goal, xg, empty_net, sk_for, sk_against."""
    from oddsmarkets.nhl.models import stabilise
    k = float(k if k is not None else stabilise.shrink_k("finishing"))
    k_sh = float(k_sh if k_sh is not None else stabilise.shrink_k("sh_pct"))
    s = sh[(sh["empty_net"].to_numpy(float) == 0) & sh["shooter"].notna() & np.isfinite(sh["xg"].to_numpy(float))].copy()
    if not len(s):
        return pd.DataFrame(columns=COLS)
    s["sog"] = s["type"].isin(["goal", "shot-on-goal"]).astype(float)
    five = (s["sk_for"].to_numpy(float) == 5) & (s["sk_against"].to_numpy(float) == 5)
    pp = s["sk_for"].to_numpy(float) > s["sk_against"].to_numpy(float)
    s["g5"] = s["goal"] * five
    s["x5"] = s["xg"] * five
    s["n5"] = five.astype(float)
    s["gp"] = s["goal"] * pp
    s["xp"] = s["xg"] * pp
    g = s.groupby("shooter")
    t = g.agg(attempts=("goal", "size"), shots=("sog", "sum"), goals=("goal", "sum"), ixg=("xg", "sum"), g5=("g5", "sum"),
              x5=("x5", "sum"), n5=("n5", "sum"), gp=("gp", "sum"), xp=("xp", "sum"))
    team = s.groupby(["shooter", "team"]).size().reset_index(name="n").sort_values("n").drop_duplicates("shooter", keep="last")
    t["team"] = team.set_index("shooter")["team"].reindex(t.index)
    lg_sh = float(t["goals"].sum() / max(t["shots"].sum(), 1.0))
    out = pd.DataFrame({"player_id": [int(p) for p in t.index], "team": t["team"].to_numpy(object)})
    n = t["attempts"].to_numpy(float)
    gax = (t["goals"] - t["ixg"]).to_numpy(float)
    out["attempts"] = n
    out["shots"] = t["shots"].to_numpy(float)
    out["goals"] = t["goals"].to_numpy(float)
    out["ixg"] = t["ixg"].to_numpy(float)
    out["gax"] = gax
    out["gax_per_att"] = gax / np.maximum(n, 1.0)
    out["talent"] = gax / (n + k)
    out["gax_shrunk"] = n * out["talent"]
    out["sh_pct"] = out["goals"] / out["shots"].where(out["shots"] > 0)
    out["sh_pct_shrunk"] = (out["goals"] + k_sh * lg_sh) / (out["shots"] + k_sh)
    out["xsh_pct"] = out["ixg"] / np.maximum(n, 1.0)
    out["fsh_pct"] = out["goals"] / np.maximum(n, 1.0)
    out["gax_5v5"] = (t["g5"] - t["x5"]).to_numpy(float)
    out["gax_pp"] = (t["gp"] - t["xp"]).to_numpy(float)
    out["ixg_5v5"] = t["x5"].to_numpy(float)
    out["attempts_5v5"] = t["n5"].to_numpy(float)
    out["k"] = k
    return out[COLS].sort_values("gax_shrunk", ascending=False).reset_index(drop=True)


def frame_rows(df: pd.DataFrame, nd: int = 4) -> dict:
    """{"cols", "rows"} (JSON-ready) from a DataFrame."""
    return {"cols": list(df.columns), "rows": _io.clean(df.astype(object).where(df.notna(), None).values.tolist(), nd)}


def for_season(season: int, use_cache: bool = True) -> dict:
    from oddsmarkets.nhl.models import stabilise, xg
    season = _io.sid(season)
    if not _io.events_path(season).exists():
        return {"ok": False, "reason": "no events for this season"}
    f = xg.current_fit() or {}
    k, ks = stabilise.shrink_k("finishing"), stabilise.shrink_k("sh_pct")
    key = _io.file_key(_io.events_path(season), MODEL_VERSION, f.get("key"), k, ks)

    def build():
        sh = xg.shot_table(season, use_cache)
        if not len(sh) or sh["xg"].isna().all():
            return {"ok": False, "reason": "no xG for this season"}
        t = table(sh, k, ks)
        return {"ok": True, "season": season, "k": k, "k_sh_pct": ks, "n": int(len(t)), "players": frame_rows(t)}

    return _io.cached("shooting", str(season), key, build, use_cache)
