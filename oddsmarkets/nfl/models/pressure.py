"""
Pressure and sacks: rates allowed (offence, QB) and created (defence, pass rushers), where the data allows.

Per dropback (nflverse `qb_dropback`: pass attempts, sacks and scrambles):
* sack (all seasons), QB hit (all seasons; nflverse `qb_hit` includes sacks), pressure (participation
  `was_pressure`, 2016-2025), out of pocket and blitz (FTN, 2022->), pass rushers (participation / FTN),
  time to throw (participation);
* expected sack rate: the league rate in the same down x distance-bucket x field-zone cell that season
  (situations differ: 3rd and long draws pressure), so sack rate over expected (SROE) is actual - expected;
* pressure-to-sack rate for QBs (sacks / pressured dropbacks, 2016-2025: the share of pressure the QB
  turns into sacks, largely his).

Individuals: sacks (a half sack is 0.5), QB hits by player, and, with participation (2016-2025), the
dropbacks a defender was on the field for (from `defense_players`), so sacks and hits per pass-rush snap.
FTN `is_qb_fault_sack` (2022->) gives the share of sacks charted as the QB's fault.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "press-1"
TOGO_EDGES = [0, 3, 6, 10, 99]
ZONES = [0, 20, 50, 80, 100]


def dropbacks(d: pd.DataFrame) -> pd.DataFrame:
    db = pd.to_numeric(d["qb_dropback"], errors="coerce").fillna(0) == 1
    tp = pd.to_numeric(d.get("two_point_attempt"), errors="coerce").fillna(0) == 1 if "two_point_attempt" in d else False
    s = d[db & ~tp]
    f = lambda c: pd.to_numeric(s[c], errors="coerce").to_numpy(float) if c in s else np.full(len(s), np.nan)  # noqa: E731
    out = pd.DataFrame({
        "season": f("season"), "game_id": s["game_id"].astype(str).to_numpy(), "play_id": f("play_id"),
        "team": s["posteam"].astype(object).to_numpy(), "opp": s["defteam"].astype(object).to_numpy(),
        "passer": s["passer_player_id"].astype(object).to_numpy(),
        "passer_name": s["passer_player_name"].astype(object).to_numpy() if "passer_player_name" in s else None,
        "down": f("down"), "ydstogo": f("ydstogo"), "yardline_100": f("yardline_100"),
        "sack": np.nan_to_num(f("sack")), "qb_hit": np.nan_to_num(f("qb_hit")), "pressure": f("p_pressure"),
        "ttt": f("p_ttt"), "rushers": np.where(np.isfinite(f("f_rushers")), f("f_rushers"), f("p_rushers")),
        "blitz": np.where(np.isfinite(f("f_blitzers")), (f("f_blitzers") > 0).astype(float), np.nan),
        "oop": f("f_oop"), "qb_fault": f("f_qb_fault_sack"), "scramble": np.nan_to_num(f("qb_scramble")),
        "def_players": s["p_def_players"].astype(object).to_numpy() if "p_def_players" in s else None,
    })
    tb = np.searchsorted(TOGO_EDGES, np.nan_to_num(out["ydstogo"].to_numpy(), nan=10), side="left")
    zb = np.searchsorted(ZONES, np.nan_to_num(out["yardline_100"].to_numpy(), nan=50), side="left")
    out["cell"] = np.nan_to_num(out["down"].to_numpy(), nan=0) * 100 + tb * 10 + zb
    out["x_sack"] = out.groupby(["season", "cell"])["sack"].transform("mean")
    return out


def _rates(x: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = x.groupby(by).agg(dropbacks=("sack", "size"), sacks=("sack", "sum"), x_sacks=("x_sack", "sum"),
                          hits=("qb_hit", "sum"), pressured=("pressure", "sum"),
                          charted=("pressure", lambda s: int(s.notna().sum())), blitz_rate=("blitz", "mean"),
                          oop_rate=("oop", "mean"), ttt=("ttt", "mean"), rushers=("rushers", "mean")).reset_index()
    g["sack_rate"] = g["sacks"] / g["dropbacks"]
    g["sroe"] = (g["sacks"] - g["x_sacks"]) / g["dropbacks"]
    g["hit_rate"] = g["hits"] / g["dropbacks"]
    g["pressure_rate"] = np.where(g["charted"] > 0, g["pressured"] / g["charted"].clip(lower=1), np.nan)
    return g


def team_tables(x: pd.DataFrame) -> dict:
    return {"offense": _rates(x, ["team", "season"]), "defense": _rates(x, ["opp", "season"]).rename(columns={"opp": "team"})}


def qb_table(x: pd.DataFrame) -> pd.DataFrame:
    g = _rates(x[x["passer"].notna()], ["passer", "season"])
    names = x.groupby(["passer", "season"])["passer_name"].last().reset_index()
    p = x[x["pressure"] == 1].groupby(["passer", "season"])["sack"].mean().rename("p2s").reset_index()
    qf = x[x["sack"] == 1].groupby(["passer", "season"])["qb_fault"].mean().rename("qb_fault_share").reset_index()
    return g.merge(names, on=["passer", "season"], how="left").merge(p, on=["passer", "season"], how="left") \
            .merge(qf, on=["passer", "season"], how="left")


def rusher_table(d: pd.DataFrame, x: pd.DataFrame) -> pd.DataFrame:
    """Sacks and hits per defender; per pass-rush snap when participation lists the defenders on the field."""
    rows = []
    for col, w in (("sack_player_id", 1.0), ("half_sack_1_player_id", 0.5), ("half_sack_2_player_id", 0.5)):
        if col in d:
            s = d[d[col].notna()]
            rows.append(pd.DataFrame({"player": s[col].astype(str), "season": pd.to_numeric(s["season"], errors="coerce"),
                                      "team": s["defteam"], "sacks": w, "hits": 0.0}))
    for col in ("qb_hit_1_player_id", "qb_hit_2_player_id"):
        if col in d:
            s = d[d[col].notna()]
            rows.append(pd.DataFrame({"player": s[col].astype(str), "season": pd.to_numeric(s["season"], errors="coerce"),
                                      "team": s["defteam"], "sacks": 0.0, "hits": 1.0}))
    if not rows:
        return pd.DataFrame(columns=["player", "season", "team", "sacks", "hits", "snaps"])
    r = pd.concat(rows, ignore_index=True)
    g = r.groupby(["player", "season"]).agg(team=("team", "last"), sacks=("sacks", "sum"), hits=("hits", "sum")).reset_index()
    dp = x["def_players"] if "def_players" in x else None
    if dp is not None and pd.Series(dp).notna().any():
        ser = pd.Series(dp).dropna().astype(str)
        ser = ser[ser.str.len() > 0]
        if len(ser):
            seasons = x.loc[ser.index, "season"]
            ex = ser.str.split(";").explode()
            snaps = pd.DataFrame({"player": ex.to_numpy(), "season": seasons.reindex(ex.index).to_numpy()}) \
                .groupby(["player", "season"]).size().rename("snaps").reset_index()
            g = g.merge(snaps, on=["player", "season"], how="left")
            g["sacks_per_100"] = 100 * g["sacks"] / g["snaps"]
            g["hits_per_100"] = 100 * g["hits"] / g["snaps"]
    return g.sort_values("sacks", ascending=False).reset_index(drop=True)


def season_tables(season: int, d: pd.DataFrame | None = None) -> dict:
    d = _io.plays(season) if d is None else d
    if d is None or not len(d):
        return {}
    x = dropbacks(d)
    t = team_tables(x)
    return {"team_offense": t["offense"], "team_defense": t["defense"], "qbs": qb_table(x), "rushers": rusher_table(d, x)}


def for_season(season: int, use_cache: bool = True) -> dict:
    key = _io.file_key(*_io.source_files(season), MODEL_VERSION)

    def build():
        t = season_tables(season)
        return {k: _io.clean(v.drop(columns=[c for c in ("def_players",) if c in v]).to_dict("records")) for k, v in t.items()}
    return _io.cached("pressure", str(int(season)), key, build, use_cache)
