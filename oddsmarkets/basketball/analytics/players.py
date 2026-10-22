"""
Player season catalogue (`players.json`) and the per-player career files (`players/<pid>.json`).

Rates
-----
Box rates use the player's on-floor share of each game, f = sec / (team player-seconds / 5), so a
player's share of team and opponent events is summed game by game:

    poss_on   = sum f * team possessions                    (FGA - OREB + TOV + 0.44 FTA, both teams averaged)
    USG%      = (FGA + 0.44 FTA + TOV) / sum f * (TmFGA + 0.44 TmFTA + TmTOV)
    AST%      = AST / (sum f * TmFGM - FGM)
    ORB%      = ORB / sum f * (TmORB + OppDRB)      DRB% = DRB / sum f * (TmDRB + OppORB)     TRB% likewise
    STL%      = STL / sum f * OppPoss               BLK% = BLK / sum f * (OppFGA - Opp3PA)
    TOV%      = TOV / (FGA + 0.44 FTA + TOV)        TS% = PTS / (2 (FGA + 0.44 FTA))          eFG% = (FGM + 0.5 3PM) / FGA
    TS add    = (TS - league TS) * 2 (FGA + 0.44 FTA) * 100 / poss_on       (points per 100 possessions)
    Game Score (Hollinger) = PTS + 0.4 FGM - 0.7 FGA - 0.4 (FTA - FTM) + 0.7 ORB + 0.3 DRB + STL + 0.7 AST
                             + 0.7 BLK - 0.4 PF - TOV

Shot diet and shot-making come from the season's shot table (play-by-play era, scope "pbp") with
xPTS from `models/shots.py`: zones rim (< 4 ft), short mid-range (other 2s inside 14 ft), long mid-range
(2s from 14 ft), corner 3, above-the-break 3 (heaves included); "vs lg" is the player's FG% in the
zone minus the league's. On/off and the on-floor defence come from the lineup stints; HPM, RAPM and
box impact from `models/impact.py`; WPA and clutch from the play-by-play pass (`pbpx.py`).

Percentiles
-----------
Qualified players have at least `min_floor` minutes = MIN_FLOOR_SHARE x the season's most minutes
(so the floor scales through a season). Every player is placed against the qualified players, on
the whole league (`pct`) and on his position pool G / F / C (`pct_pool`); 100 = best, with `lower`
metrics reversed (`analytics.add_percentiles`). `rank` is among qualified players.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import lineups as LU
from oddsmarkets.basketball.analytics.context import SeasonContext
from oddsmarkets.basketball.models import _io

logger = logging.getLogger(__name__)
MIN_FLOOR_SHARE = 0.2
_m = an.metric

GROUPS = ["Scoring", "Shot diet", "Playmaking", "Ball security", "Rebounding", "Defence", "Impact", "Clutch", "Availability",
          "Team context", "Career"]

METRICS: list[dict] = [
    # Scoring
    _m("pts_g", "Points per game", "Scoring", "1"),
    _m("pts36", "Points per 36", "Scoring", "1"),
    _m("pts100", "Points per 100 possessions", "Scoring", "1"),
    _m("ts", "True shooting %", "Scoring", "pct"),
    _m("efg", "Effective FG %", "Scoring", "pct"),
    _m("fg", "FG %", "Scoring", "pct"),
    _m("fg2", "2-point FG %", "Scoring", "pct"),
    _m("fg3", "3-point FG %", "Scoring", "pct"),
    _m("ft", "Free-throw %", "Scoring", "pct"),
    _m("usg", "Usage %", "Scoring", "pct"),
    _m("ts_add", "TS points added per 100", "Scoring", "2"),
    _m("pps", "Points per field-goal attempt", "Scoring", "3"),
    _m("ftr", "Free-throw rate (FTA / FGA)", "Scoring", "3"),
    _m("tpar", "3-point attempt rate", "Scoring", "pct"),
    _m("fta100", "Free-throw attempts per 100", "Scoring", "1"),
    _m("tpm_g", "3-pointers made per game", "Scoring", "1"),
    _m("pox100", "Points over expected per 100 shots", "Scoring", "1", scope="pbp"),
    _m("xpps", "Expected points per shot (shot quality)", "Scoring", "3", scope="pbp"),
    _m("and1_100", "And-ones per 100 possessions", "Scoring", "2", scope="pbp"),
    _m("unassisted_share", "Unassisted share of made FG", "Scoring", "pct", scope="pbp"),
    # Shot diet
    _m("rim_freq", "Rim frequency (< 4 ft)", "Shot diet", "pct", scope="pbp"),
    _m("rim_fg", "Rim FG %", "Shot diet", "pct", scope="pbp"),
    _m("rim_fg_diff", "Rim FG % vs league", "Shot diet", "pct", scope="pbp"),
    _m("smid_freq", "Short mid-range frequency (4-14 ft)", "Shot diet", "pct", scope="pbp"),
    _m("smid_fg", "Short mid-range FG %", "Shot diet", "pct", scope="pbp"),
    _m("smid_fg_diff", "Short mid-range FG % vs league", "Shot diet", "pct", scope="pbp"),
    _m("lmid_freq", "Long mid-range frequency (14 ft+ 2s)", "Shot diet", "pct", scope="pbp"),
    _m("lmid_fg", "Long mid-range FG %", "Shot diet", "pct", scope="pbp"),
    _m("lmid_fg_diff", "Long mid-range FG % vs league", "Shot diet", "pct", scope="pbp"),
    _m("c3_freq", "Corner-3 frequency", "Shot diet", "pct", scope="pbp"),
    _m("c3_fg", "Corner-3 FG %", "Shot diet", "pct", scope="pbp"),
    _m("c3_fg_diff", "Corner-3 FG % vs league", "Shot diet", "pct", scope="pbp"),
    _m("ab3_freq", "Above-the-break 3 frequency", "Shot diet", "pct", scope="pbp"),
    _m("ab3_fg", "Above-the-break 3 FG %", "Shot diet", "pct", scope="pbp"),
    _m("ab3_fg_diff", "Above-the-break 3 FG % vs league", "Shot diet", "pct", scope="pbp"),
    _m("avg_dist", "Average shot distance (ft)", "Shot diet", "1", scope="pbp"),
    _m("dunk_freq", "Dunk frequency", "Shot diet", "pct", scope="pbp"),
    _m("layup_freq", "Layup and tip frequency", "Shot diet", "pct", scope="pbp"),
    _m("float_hook_freq", "Floater and hook frequency", "Shot diet", "pct", scope="pbp"),
    _m("jumper_freq", "Jump-shot frequency", "Shot diet", "pct", scope="pbp"),
    _m("pullup_freq", "Pull-up frequency", "Shot diet", "pct", scope="pbp"),
    _m("iso_freq", "Step-back / fadeaway / turnaround frequency", "Shot diet", "pct", scope="pbp"),
    _m("assisted_share", "Assisted share of made FG", "Shot diet", "pct", scope="pbp"),
    _m("putback_freq", "Putback frequency", "Shot diet", "pct", scope="pbp"),
    _m("transition_freq", "Transition shot frequency", "Shot diet", "pct", scope="pbp"),
    # Playmaking
    _m("ast_g", "Assists per game", "Playmaking", "1"),
    _m("ast36", "Assists per 36", "Playmaking", "1"),
    _m("ast100", "Assists per 100 possessions", "Playmaking", "1"),
    _m("ast_pct", "Assist %", "Playmaking", "pct"),
    _m("ast_usg", "Assist % to usage", "Playmaking", "2"),
    _m("ast_tov", "Assist-to-turnover ratio", "Playmaking", "2"),
    _m("ast_pts100", "Points created by assists per 100", "Playmaking", "1", scope="pbp"),
    _m("ast_rim_share", "Share of assists to rim makes", "Playmaking", "pct", scope="pbp"),
    _m("ast_3_share", "Share of assists to 3-pointers", "Playmaking", "pct", scope="pbp"),
    # Ball security
    _m("tov_g", "Turnovers per game", "Ball security", "1", True),
    _m("tov100", "Turnovers per 100 possessions", "Ball security", "1", True),
    _m("tov_pct", "Turnover %", "Ball security", "pct", True),
    _m("live_tov_share", "Live-ball share of turnovers", "Ball security", "pct", True, "pbp"),
    _m("off_foul100", "Offensive fouls per 100", "Ball security", "2", True, "pbp"),
    # Rebounding
    _m("reb_g", "Rebounds per game", "Rebounding", "1"),
    _m("reb36", "Rebounds per 36", "Rebounding", "1"),
    _m("orb_pct", "Offensive rebound %", "Rebounding", "pct"),
    _m("drb_pct", "Defensive rebound %", "Rebounding", "pct"),
    _m("trb_pct", "Total rebound %", "Rebounding", "pct"),
    _m("oreb100", "Offensive rebounds per 100", "Rebounding", "1"),
    _m("dreb100", "Defensive rebounds per 100", "Rebounding", "1"),
    _m("putback100", "Putback makes per 100", "Rebounding", "2", scope="pbp"),
    # Defence
    _m("stl_g", "Steals per game", "Defence", "1"),
    _m("blk_g", "Blocks per game", "Defence", "1"),
    _m("stl_pct", "Steal %", "Defence", "pct"),
    _m("blk_pct", "Block %", "Defence", "pct"),
    _m("stl100", "Steals per 100", "Defence", "1"),
    _m("blk100", "Blocks per 100", "Defence", "1"),
    _m("pf100", "Personal fouls per 100", "Defence", "1", True),
    _m("hpm_d", "Defensive HPM", "Defence", "2"),
    _m("rapm_d", "Defensive RAPM", "Defence", "2", scope="pbp"),
    _m("box_d", "Defensive box impact", "Defence", "2"),
    _m("opp_rim_fg_on", "Opponent rim FG % with him on the floor", "Defence", "pct", True, "pbp"),
    _m("opp_xpps_on", "Opponent xPTS per shot with him on the floor", "Defence", "3", True, "pbp"),
    _m("opp_fg3_on", "Opponent 3-point % with him on the floor", "Defence", "pct", True, "pbp"),
    _m("on_drtg", "Team defensive rating with him on", "Defence", "1", True, "pbp"),
    _m("dwpa", "Defensive WPA", "Defence", "3", scope="pbp"),
    # Impact
    _m("hpm", "Hardwood Plus-Minus (HPM)", "Impact", "2"),
    _m("hpm_o", "Offensive HPM", "Impact", "2"),
    _m("hpm_se", "HPM standard error", "Impact", "2", True),
    _m("rapm", "RAPM", "Impact", "2", scope="pbp"),
    _m("rapm_o", "Offensive RAPM", "Impact", "2", scope="pbp"),
    _m("box_impact", "Box impact", "Impact", "2"),
    _m("box_o", "Offensive box impact", "Impact", "2"),
    _m("hpm_next", "Projected HPM next season (aging)", "Impact", "2"),
    _m("on_net", "Team net rating with him on", "Impact", "1", scope="pbp"),
    _m("off_net", "Team net rating with him off", "Impact", "1", True, "pbp"),
    _m("on_off", "On/off net difference", "Impact", "1", scope="pbp"),
    _m("wpa", "Win probability added", "Impact", "3", scope="pbp"),
    _m("li_wpa", "Leverage-weighted WPA", "Impact", "3", scope="pbp"),
    _m("pm_g", "Plus-minus per game", "Impact", "1"),
    _m("pm100", "Plus-minus per 100 possessions", "Impact", "1"),
    _m("gmsc", "Game Score per game", "Impact", "1"),
    # Clutch
    _m("clutch_min", "Clutch minutes", "Clutch", "1", scope="pbp"),
    _m("clutch_pts", "Clutch points", "Clutch", "int", scope="pbp"),
    _m("clutch_ts", "Clutch true shooting %", "Clutch", "pct", scope="pbp"),
    _m("clutch_net", "Clutch on-floor net rating", "Clutch", "1", scope="pbp"),
    _m("clutch_wpa", "Clutch WPA", "Clutch", "3", scope="pbp"),
    _m("clutch_poss", "Clutch possessions", "Clutch", "int", scope="pbp"),
    # Availability
    _m("gp", "Games played", "Availability", "int"),
    _m("gs", "Games started", "Availability", "int"),
    _m("min", "Minutes", "Availability", "int"),
    _m("mpg", "Minutes per game", "Availability", "1"),
    _m("start_share", "Share of games started", "Availability", "pct"),
    _m("avail", "Share of team games played", "Availability", "pct"),
    _m("games_missed", "Team games missed", "Availability", "int", True),
    _m("injury_dnp", "Games out injured or ill", "Availability", "int", True),
    _m("gmsc_sd", "Game Score standard deviation", "Availability", "1", True),
    _m("b2b_gmsc_diff", "Game Score on a back-to-back minus rest", "Availability", "1"),
    # Team context
    _m("pts_share", "Share of team points", "Team context", "pct"),
    _m("min_share", "Share of team minutes", "Team context", "pct"),
    _m("ast_share", "Share of team assists", "Team context", "pct"),
    _m("reb_share", "Share of team rebounds", "Team context", "pct"),
    _m("team_win_pct", "Team win %", "Team context", "pct"),
    _m("team_net", "Team net rating (model)", "Team context", "1"),
    _m("lineup_net", "Best lineup net with him (25+ poss)", "Team context", "1", scope="pbp"),
    # Career
    _m("age", "Age (season end)", "Career", "1"),
    _m("seasons", "Seasons in the league", "Career", "int"),
    _m("career_hpm", "Career HPM (minutes-weighted, to date)", "Career", "2"),
    _m("hpm_delta", "HPM change on last season", "Career", "2"),
]
METRIC_KEYS = [m["key"] for m in METRICS]
PBP_KEYS = [m["key"] for m in METRICS if m["scope"] == "pbp"]

SIMILAR_KEYS = ["pts100", "ts", "usg", "tpar", "ftr", "ast_pct", "tov_pct", "orb_pct", "drb_pct", "stl_pct", "blk_pct", "hpm_o",
                "hpm_d", "rim_freq", "ab3_freq", "c3_freq", "smid_freq", "lmid_freq", "assisted_share", "avg_dist"]


# ---------------------------------------------------------------------------------------------- box aggregation

def box_aggregate(bf: pd.DataFrame) -> pd.DataFrame:
    """Per-player sums and on-floor-weighted team / opponent sums (module docstring)."""
    if bf is None or bf.empty:
        return pd.DataFrame()
    bf = bf.copy()
    stats = ["sec", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"]
    tg = bf.groupby(["game_id", "team"])[stats].sum().reset_index()
    opp = tg.rename(columns={c: f"o_{c}" for c in stats}).rename(columns={"team": "opp"})
    tg = tg.rename(columns={c: f"t_{c}" for c in stats})
    bf = bf.merge(tg, on=["game_id", "team"], how="left").merge(opp, on=["game_id", "opp"], how="left")
    f = bf["sec"] / (bf["t_sec"] / 5.0).clip(lower=1.0)
    bf["f"] = f
    bf["poss_on"] = f * bf["team_poss"]
    bf["x_usg"] = f * (bf["t_fga"] + 0.44 * bf["t_fta"] + bf["t_tov"])
    bf["x_fgm"] = f * bf["t_fgm"]
    bf["x_orb"] = f * (bf["t_oreb"] + bf["o_dreb"].fillna(0))
    bf["x_drb"] = f * (bf["t_dreb"] + bf["o_oreb"].fillna(0))
    bf["x_stl"] = f * bf["team_poss"]
    bf["x_blk"] = f * (bf["o_fga"].fillna(0) - bf["o_tpa"].fillna(0))
    bf["gmsc"] = (bf["pts"] + 0.4 * bf["fgm"] - 0.7 * bf["fga"] - 0.4 * (bf["fta"] - bf["ftm"]) + 0.7 * bf["oreb"] + 0.3 * bf["dreb"]
                  + bf["stl"] + 0.7 * bf["ast"] + 0.7 * bf["blk"] - 0.4 * bf["pf"] - bf["tov"])
    bf["t_reb"] = bf["t_oreb"] + bf["t_dreb"]
    played = bf[bf["sec"] > 0]
    g = played.groupby("player_id")
    agg = g[stats + ["pm", "starter", "poss_on", "x_usg", "x_fgm", "x_orb", "x_drb", "x_stl", "x_blk", "team_pts", "t_ast", "t_reb",
                     "t_sec"]].sum()
    agg["gp"] = g.size()
    agg["gmsc_mean"] = g["gmsc"].mean()
    agg["gmsc_sd"] = g["gmsc"].std()
    return agg


def _primary_team(bf: pd.DataFrame) -> pd.Series:
    tm = bf[bf["sec"] > 0].groupby(["player_id", "team"])["sec"].sum().reset_index().sort_values("sec")
    return tm.drop_duplicates("player_id", keep="last").set_index("player_id")["team"]


def _latest_team(bf: pd.DataFrame) -> pd.Series:
    """{player: team of his latest box-score row (a DNP is not a row)}: where a traded player plays now."""
    pl = bf.assign(_gid=bf["game_id"].astype(str)).sort_values(["date", "_gid"])
    return pl.drop_duplicates("player_id", keep="last").set_index("player_id")["team"]


def _b2b_flags(ctx: SeasonContext) -> dict[tuple[str, str], bool]:
    """{(team, game_id): second night of a back-to-back} from the season's game days."""
    from oddsmarkets.basketball.models._games import local_day
    by: dict[str, list] = {}
    for gid, g in ctx.games.items():
        if g.get("status") != "post":
            continue
        d = local_day(g)
        for t in (str(g.get("home")), str(g.get("away"))):
            by.setdefault(t, []).append((d, gid))
    out = {}
    for t, v in by.items():
        v.sort(key=lambda x: (str(x[0]), x[1]))
        for k, (d, gid) in enumerate(v):
            out[(t, gid)] = k > 0 and d is not None and v[k - 1][0] is not None and (d - v[k - 1][0]).days == 1
    return out


def _injury_dnps(ctx: SeasonContext) -> dict[str, int]:
    out: dict[str, int] = {}
    for g in ctx.games.values():
        if g.get("status") != "post" or g.get("stype") != "reg":
            continue
        for b in (g.get("box") or {}).values():
            for r in b.get("dnp") or []:
                reason = str(r[1] if len(r) > 1 else "").lower()
                if any(w in reason for w in ("injur", "ill", "sore", "sprain", "strain", "surgery", "concussion", "knee", "ankle",
                                              "hamstring", "back", "foot", "hip", "wrist", "shoulder", "rest", "protocol")) \
                        and "coach" not in reason:
                    out[str(r[0])] = out.get(str(r[0]), 0) + 1
    return out


def _team_games(ctx: SeasonContext) -> dict[str, tuple[int, int]]:
    """{team: (games played, wins)} in the catalogue stypes."""
    out: dict[str, list[int]] = {}
    for g in ctx.games.values():
        if g.get("status") != "post" or g.get("stype") != "reg" or g.get("hs") is None:
            continue
        h, a = str(g["home"]), str(g["away"])
        hw = int(g["hs"]) > int(g["as"])
        for t, w in ((h, hw), (a, not hw)):
            o = out.setdefault(t, [0, 0])
            o[0] += 1
            o[1] += int(w)
    return {t: (v[0], v[1]) for t, v in out.items()}


# ---------------------------------------------------------------------------------------------- shots

ZONE_BUCKETS = ("rim", "smid", "lmid", "c3", "ab3")
TYPE_BUCKETS = {"dunk": ("dunk",), "layup": ("layup", "tip"), "float_hook": ("floater", "hook"), "jumper": ("jumper",),
                "pullup": ("pullup",), "iso": ("stepback", "fadeaway", "turnaround")}


def shot_buckets(df: pd.DataFrame) -> pd.Series:
    z = df["zone"].astype(str)
    two = df["value"] == 2
    d = pd.to_numeric(df["dist_ft"], errors="coerce").fillna(0)
    return pd.Series(np.select([z == "rim", two & (d < 14), two, z == "corner3"], ["rim", "smid", "lmid", "c3"], "ab3"), index=df.index)


def shot_metrics(shots: pd.DataFrame) -> dict[str, dict]:
    """{pid: {metric: value}} for the shot-diet and shot-making metrics, plus league references."""
    if shots is None or shots.empty:
        return {}
    df = shots.copy()
    df["bucket"] = shot_buckets(df)
    lg_fg = df.groupby("bucket")["made"].mean().to_dict()
    out: dict[str, dict] = {}
    g = df.groupby("shooter")
    n = g.size()
    made = g["made"].sum()
    for pid in n.index:
        out[str(pid)] = {"_fga": float(n[pid]), "_fgm": float(made[pid])}
    cnt = df.groupby(["shooter", "bucket"])["made"].agg(["size", "mean"])
    for (pid, b), r in cnt.iterrows():
        o = out[str(pid)]
        o[f"{b}_freq"] = r["size"] / o["_fga"]
        o[f"{b}_fg"] = r["mean"]
        o[f"{b}_fg_diff"] = r["mean"] - lg_fg.get(b, np.nan)
    for pid, o in out.items():
        for b in ZONE_BUCKETS:
            o.setdefault(f"{b}_freq", 0.0)
    tt = df.groupby(["shooter", "shot_type"]).size()
    for pid in n.index:
        o = out[str(pid)]
        for key, types in TYPE_BUCKETS.items():
            o[f"{key}_freq"] = float(sum(tt.get((pid, t), 0) for t in types)) / o["_fga"]
    o_dist = g["dist_ft"].mean()
    mk = df[df["made"] == 1].groupby("shooter")["assisted"].mean()
    pb = g["putback"].mean()
    tr = g["transition"].mean()
    pbm = df[(df["putback"] == 1) & (df["made"] == 1)].groupby("shooter").size()
    for pid in n.index:
        o = out[str(pid)]
        o["avg_dist"] = float(o_dist.get(pid, np.nan))
        o["assisted_share"] = float(mk.get(pid, np.nan)) if pid in mk.index else None
        o["unassisted_share"] = (1.0 - o["assisted_share"]) if o["assisted_share"] is not None else None
        o["putback_freq"] = float(pb.get(pid, 0.0))
        o["transition_freq"] = float(tr.get(pid, 0.0))
        o["_putback_makes"] = float(pbm.get(pid, 0))
    if "xpts" in df:
        xs = g["xpts"].sum()
        ps = g["pts"].sum()
        for pid in n.index:
            o = out[str(pid)]
            o["xpps"] = float(xs[pid] / n[pid])
            o["pox100"] = float(100 * (ps[pid] - xs[pid]) / n[pid])
    # assists: who created which shots
    am = df[(df["made"] == 1) & (df["assisted"] == 1) & df["assister"].notna()]
    if not am.empty:
        am = am.assign(assister=am["assister"].astype(str))
        ga = am.groupby("assister")
        pts = ga["value"].sum()
        tot = ga.size()
        rim = am[am["bucket"] == "rim"].groupby("assister").size()
        three = am[am["value"] == 3].groupby("assister").size()
        for pid in tot.index:
            o = out.setdefault(str(pid), {})
            o["_ast_pts"] = float(pts[pid])
            o["ast_rim_share"] = float(rim.get(pid, 0) / tot[pid])
            o["ast_3_share"] = float(three.get(pid, 0) / tot[pid])
    return out


def defence_on_floor(ctx: SeasonContext) -> dict[str, dict]:
    """{pid: {"opp_rim_fg_on","opp_xpps_on","opp_fg3_on","_opp_shots"}} from opponents' shots with him on the floor."""
    sh = ctx.season_shots
    if sh is None or sh.empty or ctx.season_stints is None or ctx.season_stints.empty:
        return {}
    on = LU.shots_on_floor(sh, ctx.season_stints, ctx.games)
    df = pd.concat([sh[["made", "value", "zone"] + (["xpts"] if "xpts" in sh else [])], on], axis=1)
    df = df[df["d1"].notna()]
    long = pd.concat([df.assign(pid=df[f"d{i}"]) for i in range(1, 6)], ignore_index=True)
    g = long.groupby("pid")
    out: dict[str, dict] = {}
    n = g.size()
    rim = long[long["zone"] == "rim"].groupby("pid")["made"].agg(["size", "mean"])
    three = long[long["value"] == 3].groupby("pid")["made"].agg(["size", "mean"])
    xs = g["xpts"].mean() if "xpts" in long else None
    for pid in n.index:
        o = {"_opp_shots": float(n[pid])}
        if pid in rim.index and rim.at[pid, "size"] >= 10:
            o["opp_rim_fg_on"] = float(rim.at[pid, "mean"])
        if pid in three.index and three.at[pid, "size"] >= 10:
            o["opp_fg3_on"] = float(three.at[pid, "mean"])
        if xs is not None:
            o["opp_xpps_on"] = float(xs[pid])
        out[str(pid)] = o
    return out


# ---------------------------------------------------------------------------------------------- the catalogue

def _age(dob: Any, league: str, season: int) -> float | None:
    try:
        d = date.fromisoformat(str(dob)[:10])
    except (TypeError, ValueError):
        return None
    end = date(season, 4, 15) if league == "nba" else date(season, 9, 1)
    return (end - d).days / 365.25


def build(ctx: SeasonContext, history: dict | None = None, lineup_tables: dict | None = None) -> dict:
    """players.json for one league-season (PAYLOADS.md). `history` = {"seasons": {pid: n earlier seasons},
    "career": {pid: (minutes, hpm x minutes) before this season}, "prev_hpm": {pid: last season's HPM}}."""
    league, season = ctx.league, ctx.season
    bf = ctx.box
    history = history or {}
    meta = {"ok": True, "league": league, "season": season, "updated_at": an.now(), "metrics": METRICS,
            "groups": GROUPS, "pools": {p: {"label": an.POOL_LABELS[p], "n": 0} for p in an.POOLS}, "min_floor": 0, "players": {}}
    if bf is None or bf.empty:
        meta["note"] = "no regular-season box scores yet"
        return meta
    agg = box_aggregate(bf)
    prim = _primary_team(bf)
    # The shown team: in the current season the team a player plays for now (a traded player's latest game; WNBA
    # 2026 listed 12 traded players, Kelsey Plum and DeWanna Bonner among them, under the team they left), in past
    # seasons the team he played most for. Team-context metrics (availability, team win %) keep the primary team.
    shown = _latest_team(bf) if ctx.season >= ctx.current else prim
    b2b = _b2b_flags(ctx)
    bfp = bf[bf["sec"] > 0].copy()
    bfp["gmsc"] = (bfp["pts"] + 0.4 * bfp["fgm"] - 0.7 * bfp["fga"] - 0.4 * (bfp["fta"] - bfp["ftm"]) + 0.7 * bfp["oreb"]
                   + 0.3 * bfp["dreb"] + bfp["stl"] + 0.7 * bfp["ast"] + 0.7 * bfp["blk"] - 0.4 * bfp["pf"] - bfp["tov"])
    bfp["b2b"] = [b2b.get((t, g), False) for t, g in zip(bfp["team"], bfp["game_id"])]
    b2b_split = bfp.groupby(["player_id", "b2b"])["gmsc"].mean().unstack()
    inj = _injury_dnps(ctx)
    tgames = _team_games(ctx)
    lg_tsa = float((agg["fga"] + 0.44 * agg["fta"]).sum())
    lg_ts = float(agg["pts"].sum() / max(2 * lg_tsa, 1e-9))
    gmin = _io.game_minutes(league)
    shots = shot_metrics(ctx.season_shots)
    dfl = defence_on_floor(ctx)
    oo = LU.on_off(ctx.season_team_stints) if ctx.season_team_stints is not None and not ctx.season_team_stints.empty else {}
    tot = ctx.pbp_totals or {}
    ev, wpa = tot.get("players") or {}, tot.get("wpa") or {}
    rteams = (ctx.ratings or {}).get("teams") or {}
    best_unit: dict[str, float] = {}
    for tid, units in (lineup_tables or {}).items():
        for u in units:
            if u.get("qualified") and u.get("net") is not None:
                for p in u["players"]:
                    best_unit[p] = max(best_unit.get(p, -1e9), u["net"])
    players = ctx.players
    rows: dict[str, dict] = {}
    for pid, a in agg.iterrows():
        pid = str(pid)
        info = players.get(pid) or {}
        gp = float(a["gp"])
        mins = float(a["sec"]) / 60.0
        poss = float(a["poss_on"])
        fga, fta, tov = float(a["fga"]), float(a["fta"]), float(a["tov"])
        tsa = fga + 0.44 * fta
        team = str(prim.get(pid)) if pid in prim.index else None
        tg = tgames.get(team or "", (0, 0))
        v: dict[str, Any] = {}
        v["pts_g"] = a["pts"] / gp
        v["pts36"] = an.div(36 * a["pts"], mins)
        v["pts100"] = an.per100(a["pts"], poss)
        v["ts"] = an.div(a["pts"], 2 * tsa)
        v["efg"] = an.div(a["fgm"] + 0.5 * a["tpm"], fga)
        v["fg"] = an.div(a["fgm"], fga)
        v["fg2"] = an.div(a["fgm"] - a["tpm"], fga - a["tpa"])
        v["fg3"] = an.div(a["tpm"], a["tpa"])
        v["ft"] = an.div(a["ftm"], fta)
        v["usg"] = an.div(tsa + tov, a["x_usg"])
        v["ts_add"] = (v["ts"] - lg_ts) * 2 * tsa * 100 / poss if v["ts"] is not None and poss > 0 else None
        v["pps"] = an.div(2 * (a["fgm"] - a["tpm"]) + 3 * a["tpm"], fga)
        v["ftr"] = an.div(fta, fga)
        v["tpar"] = an.div(a["tpa"], fga)
        v["fta100"] = an.per100(fta, poss)
        v["tpm_g"] = a["tpm"] / gp
        v["ast_g"] = a["ast"] / gp
        v["ast36"] = an.div(36 * a["ast"], mins)
        v["ast100"] = an.per100(a["ast"], poss)
        v["ast_pct"] = an.div(a["ast"], a["x_fgm"] - a["fgm"])
        v["ast_usg"] = an.div(v["ast_pct"], v["usg"]) if v["ast_pct"] is not None else None
        v["ast_tov"] = an.div(a["ast"], tov)
        v["tov_g"] = tov / gp
        v["tov100"] = an.per100(tov, poss)
        v["tov_pct"] = an.div(tov, tsa + tov)
        reb = a["oreb"] + a["dreb"]
        v["reb_g"] = reb / gp
        v["reb36"] = an.div(36 * reb, mins)
        v["orb_pct"] = an.div(a["oreb"], a["x_orb"])
        v["drb_pct"] = an.div(a["dreb"], a["x_drb"])
        v["trb_pct"] = an.div(reb, a["x_orb"] + a["x_drb"])
        v["oreb100"] = an.per100(a["oreb"], poss)
        v["dreb100"] = an.per100(a["dreb"], poss)
        v["stl_g"] = a["stl"] / gp
        v["blk_g"] = a["blk"] / gp
        v["stl_pct"] = an.div(a["stl"], a["x_stl"])
        v["blk_pct"] = an.div(a["blk"], a["x_blk"])
        v["stl100"] = an.per100(a["stl"], poss)
        v["blk100"] = an.per100(a["blk"], poss)
        v["pf100"] = an.per100(a["pf"], poss)
        v["pm_g"] = a["pm"] / gp if ctx.has_pm else None
        v["pm100"] = an.per100(a["pm"], poss) if ctx.has_pm else None
        v["gmsc"] = a["gmsc_mean"]
        v["gp"], v["gs"], v["min"], v["mpg"] = gp, float(a["starter"]), mins, mins / gp
        v["start_share"] = a["starter"] / gp
        v["avail"] = an.div(gp, tg[0]) if tg[0] else None
        if v["avail"] is not None:
            v["avail"] = min(1.0, v["avail"])
        v["games_missed"] = max(0.0, tg[0] - gp) if tg[0] else None
        v["injury_dnp"] = float(inj.get(pid, 0))
        v["gmsc_sd"] = a["gmsc_sd"] if gp >= 5 else None
        if pid in b2b_split.index and True in b2b_split.columns and False in b2b_split.columns:
            x, y = b2b_split.at[pid, True], b2b_split.at[pid, False]
            v["b2b_gmsc_diff"] = float(x - y) if pd.notna(x) and pd.notna(y) else None
        v["pts_share"] = an.div(a["pts"], a["team_pts"])
        v["min_share"] = an.div(a["sec"], a["t_sec"])
        v["ast_share"] = an.div(a["ast"], a["t_ast"])
        v["reb_share"] = an.div(reb, a["t_reb"])
        v["team_win_pct"] = an.div(tg[1], tg[0]) if tg[0] else None
        v["team_net"] = (rteams.get(team or "") or {}).get("net")
        # shots
        s = shots.get(pid) or {}
        for k in ("rim", "smid", "lmid", "c3", "ab3"):
            for suf in ("_freq", "_fg", "_fg_diff"):
                if s.get("_fga"):
                    v[k + suf] = s.get(k + suf)
        for k in ("avg_dist", "dunk_freq", "layup_freq", "float_hook_freq", "jumper_freq", "pullup_freq", "iso_freq", "assisted_share",
                  "unassisted_share", "putback_freq", "transition_freq", "xpps", "pox100", "ast_rim_share", "ast_3_share"):
            if k in s:
                v[k] = s[k]
        if "_putback_makes" in s:
            v["putback100"] = an.per100(s["_putback_makes"], poss)
        if "_ast_pts" in s:
            v["ast_pts100"] = an.per100(s["_ast_pts"], poss)
        d = dfl.get(pid) or {}
        for k in ("opp_rim_fg_on", "opp_xpps_on", "opp_fg3_on"):
            v[k] = d.get(k)
        o = oo.get(pid) or {}
        if o:
            v["on_drtg"], v["on_net"], v["off_net"], v["on_off"] = o.get("on_drtg"), o.get("on_net"), o.get("off_net"), o.get("diff")
        v["lineup_net"] = best_unit.get(pid)
        # impact
        h = ctx.hpm.get(pid) or (ctx.impact.get("players") or {}).get(pid) or {}
        if h.get("t") is not None:
            v["hpm"], v["hpm_o"], v["hpm_d"], v["hpm_se"] = h.get("t"), h.get("o"), h.get("d"), h.get("se")
            bo, bd = h.get("box_o"), h.get("box_d")
            v["box_o"], v["box_d"] = bo, bd
            v["box_impact"] = (bo + bd) if bo is not None and bd is not None else None
        rp = h.get("rapm") or {}
        if rp:
            v["rapm"], v["rapm_o"], v["rapm_d"] = rp.get("t"), rp.get("o"), rp.get("d")
        pj = h.get("proj") or {}
        v["hpm_next"] = pj.get("hpm_next")
        # play-by-play events and WPA
        e = ev.get(pid)
        if e is not None:
            v["and1_100"] = an.per100(e.get("and1", 0.0), poss)
            v["off_foul100"] = an.per100(e.get("off_foul", 0.0), poss)
            v["live_tov_share"] = an.div(e.get("tov_live", 0.0), e.get("tov_pbp", 0.0))
            v["clutch_min"] = e.get("c_sec", 0.0) / 60.0
            v["clutch_pts"] = e.get("c_pts", 0.0)
            v["clutch_ts"] = an.div(e.get("c_pts", 0.0), 2 * (e.get("c_fga", 0.0) + 0.44 * e.get("c_fta", 0.0)))
            po, pdf = e.get("c_poss_o", 0.0), e.get("c_poss_d", 0.0)
            v["clutch_poss"] = 0.5 * (po + pdf)
            if po >= 5 and pdf >= 5:
                v["clutch_net"] = 100 * (e.get("c_pf", 0.0) / po - e.get("c_pa", 0.0) / pdf)
        w = wpa.get(pid)
        if w is not None:
            v["wpa"], v["li_wpa"], v["clutch_wpa"], v["dwpa"] = w.get("wpa"), w.get("li_wpa"), w.get("clutch_wpa"), w.get("dwpa")
        # career
        age = _age(info.get("dob"), league, season)
        v["age"] = age
        v["seasons"] = float((history.get("seasons") or {}).get(pid, 0) + 1)
        cm, ch = (history.get("career") or {}).get(pid, (0.0, 0.0))
        if v.get("hpm") is not None:
            v["career_hpm"] = (ch + v["hpm"] * mins) / (cm + mins) if cm + mins > 0 else None
            prev = (history.get("prev_hpm") or {}).get(pid)
            v["hpm_delta"] = (v["hpm"] - prev) if prev is not None else None
        team_now = str(shown.get(pid)) if pid in shown.index else team
        rows[pid] = {"name": info.get("name") or pid, "team": team_now, "pos": info.get("pos"), "pool": info.get("pool") or "F",
                     "age": an.rnd(age, 1), "gp": int(gp), "min": int(round(mins)), "values": an.round_values(v, METRICS)}
    max_min = max((r["min"] for r in rows.values()), default=0)
    floor = int(round(MIN_FLOOR_SHARE * max_min))
    qual = [p for p, r in rows.items() if r["min"] >= floor and r["min"] > 0]
    for p, r in rows.items():
        r["qualified"] = p in rows and r["min"] >= floor and r["min"] > 0
    an.add_percentiles(rows, METRICS, qual, {p: r["pool"] for p, r in rows.items()})
    for pl in an.POOLS:
        meta["pools"][pl]["n"] = sum(1 for p in qual if rows[p]["pool"] == pl)
    meta["min_floor"] = floor
    meta["n_qualified"] = len(qual)
    meta["league_ts"] = round(lg_ts, 4)
    meta["has_pbp"] = bool(shots) or bool(ev)
    meta["players"] = rows
    return meta


# ---------------------------------------------------------------------------------------------- the current-season block

ZONE_ORDER = ["rim", "paint", "mid", "corner3", "ab3", "heave"]


def zones_table(df: pd.DataFrame, league_df: pd.DataFrame | None = None) -> dict:
    """ZONES = {zone: {"freq","fg","pps","league_pps"}} for a shot subset."""
    out = {}
    if df is None or df.empty:
        return out
    n = len(df)
    lg = None
    if league_df is not None and not league_df.empty:
        lg = league_df.groupby("zone").apply(lambda s: float((s["made"] * s["value"]).mean()), include_groups=False).to_dict()
    for z, s in df.groupby("zone"):
        out[str(z)] = {"freq": round(len(s) / n, 4), "fg": round(float(s["made"].mean()), 4),
                       "pps": round(float((s["made"] * s["value"]).mean()), 3),
                       "league_pps": round(lg[z], 3) if lg and z in lg else None, "n": int(len(s))}
    return {z: out[z] for z in ZONE_ORDER if z in out} | {z: v for z, v in out.items() if z not in ZONE_ORDER}


def types_table(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    out = {}
    for t, s in df.groupby("shot_type"):
        out[str(t)] = {"n": int(len(s)), "fg": round(float(s["made"].mean()), 4), "pps": round(float((s["made"] * s["value"]).mean()), 3)}
    return out


def grid_payload(grid: pd.DataFrame) -> dict | None:
    if grid is None or grid.empty:
        return None
    cols = [c for c in ("x", "y", "n", "fg", "pps", "xpps", "share", "lg_fg", "lg_pps", "fg_diff", "pps_diff") if c in grid]
    rows = []
    for r in grid[cols].itertuples(index=False):
        rows.append([None if (isinstance(x, float) and not math.isfinite(x)) else (round(float(x), 3) if isinstance(x, float) else x)
                     for x in r])
    return {"cols": cols, "rows": rows}


def current_blocks(ctx: SeasonContext, catalogue: dict, lineup_tables: dict | None = None, award_p: dict | None = None,
                   grid_size: float = 1.5) -> dict[str, dict]:
    """{pid: the "current" block of players/<pid>.json} for every player in the catalogue."""
    from oddsmarkets.basketball.models import shots as SH
    out: dict[str, dict] = {}
    rows = (catalogue or {}).get("players") or {}
    if not rows:
        return out
    ba = ctx.box_all
    sums = ctx.pbp_summaries or {}
    sh = ctx.season_shots
    ref = None
    if sh is not None and not sh.empty:
        try:
            ref = SH.league_grid(sh, None, "hex", grid_size)
        except Exception:  # noqa: BLE001
            ref = None
    by_shooter = dict(tuple(sh.groupby("shooter"))) if sh is not None and not sh.empty else {}
    oo = LU.on_off(ctx.season_team_stints) if ctx.season_team_stints is not None and not ctx.season_team_stints.empty else {}
    unit_by_player: dict[str, list] = {}
    for tid, units in (lineup_tables or {}).items():
        for u in units:
            for p in u["players"]:
                unit_by_player.setdefault(p, []).append(u)
    logs: dict[str, list] = {}
    if ba is not None and not ba.empty:
        b = ba[ba["sec"] > 0].sort_values(["date", "game_id"])
        for r in b.itertuples(index=False):
            pid = str(r.player_id)
            gs = (r.pts + 0.4 * r.fgm - 0.7 * r.fga - 0.4 * (r.fta - r.ftm) + 0.7 * r.oreb + 0.3 * r.dreb + r.stl + 0.7 * r.ast
                  + 0.7 * r.blk - 0.4 * r.pf - r.tov)
            w = (((sums.get(str(r.game_id)) or {}).get("wpa") or {}).get(pid) or {}).get("wpa")
            logs.setdefault(pid, []).append({
                "game": str(r.game_id), "date": r.date, "opp": str(r.opp), "home": bool(r.home), "min": round(r.sec / 60.0, 1),
                "pts": int(r.pts), "reb": int(r.oreb + r.dreb), "ast": int(r.ast), "stl": int(r.stl), "blk": int(r.blk), "tov": int(r.tov),
                "fgm": int(r.fgm), "fga": int(r.fga), "tpm": int(r.tpm), "tpa": int(r.tpa), "ftm": int(r.ftm), "fta": int(r.fta),
                "pm": int(r.pm) if ctx.has_pm else None, "game_score": round(float(gs), 1), "wpa": an.rnd(w, 4)})
    for pid, row in rows.items():
        v = row.get("values") or {}
        ps = by_shooter.get(pid)
        shots_block = None
        if ps is not None and len(ps):
            grid = None
            try:
                grid = grid_payload(SH.league_grid(ps, None, "hex", grid_size, ref=ref))
            except Exception:  # noqa: BLE001
                grid = None
            shots_block = {"grid": grid, "zones": zones_table(ps, sh), "types": types_table(ps), "n": int(len(ps))}
        o = oo.get(pid)
        units = sorted(unit_by_player.get(pid, []), key=lambda u: -u["poss"])[:5]
        h = ctx.hpm.get(pid) or (ctx.impact.get("players") or {}).get(pid) or {}
        out[pid] = {
            "season": ctx.season, "team": row.get("team"),
            "log": logs.get(pid, []),
            "shots": shots_block,
            "on_off": {k: an.rnd(o.get(k), 2) for k in ("on_net", "off_net", "diff", "on_ortg", "on_drtg", "off_ortg", "off_drtg",
                                                         "poss_on", "poss_off")} if o else None,
            "lineups": [_unit_out(u) for u in units],
            "clutch": {"min": v.get("clutch_min"), "pts": v.get("clutch_pts"), "ts": v.get("clutch_ts"), "net": v.get("clutch_net"),
                       "wpa": v.get("clutch_wpa"), "poss": v.get("clutch_poss")} if v.get("clutch_min") is not None else None,
            "projection": _io.clean(h.get("proj"), 3) if h.get("proj") else None,
            "hpm": {k: an.rnd(h.get(k), 3) for k in ("t", "o", "d", "se", "se_o", "se_d", "box_o", "box_d", "w_rapm_o", "w_rapm_d")} if h else None,
            "rapm": _io.clean(h.get("rapm"), 3) if h.get("rapm") else None,
            "awards": {a: p.get(pid) for a, p in (award_p or {}).items() if p.get(pid)},
        }
    return out


def _unit_out(u: dict) -> dict:
    return {"players": u["players"], "poss": an.rnd(u["poss"], 1), "net": an.rnd(u.get("net"), 2), "ortg": an.rnd(u.get("ortg"), 2),
            "drtg": an.rnd(u.get("drtg"), 2), "shrunk_net": an.rnd(u.get("shrunk_net"), 2), "sec": an.rnd(u.get("sec"), 0)}


# ---------------------------------------------------------------------------------------------- careers

def season_row(season: int, row: dict) -> dict:
    v = row.get("values") or {}
    return {"season": season, "team": row.get("team"), "gp": row.get("gp"), "min": row.get("min"), "pts": v.get("pts_g"),
            "reb": v.get("reb_g"), "ast": v.get("ast_g"), "ts": v.get("ts"), "hpm": v.get("hpm"), "o": v.get("hpm_o"),
            "d": v.get("hpm_d"), "rapm": v.get("rapm"), "box_impact": v.get("box_impact"), "wpa": v.get("wpa"),
            "qualified": row.get("qualified")}


def similar_index(catalogues: dict[int, dict], keys: list[str] = SIMILAR_KEYS) -> tuple[np.ndarray, list[tuple[str, int]], list[str]]:
    """(matrix of pool percentiles, [(pid, season)], key list) over every qualified player-season (missing -> 50)."""
    ids, vecs = [], []
    for s, cat in catalogues.items():
        for pid, r in ((cat or {}).get("players") or {}).items():
            if not r.get("qualified"):
                continue
            pct = r.get("pct") or {}
            if sum(1 for k in keys if k in pct) < len(keys) // 2:
                continue
            ids.append((pid, int(s)))
            vecs.append([float(pct.get(k, 50)) for k in keys])
    return (np.array(vecs, float) if vecs else np.zeros((0, len(keys)))), ids, keys


def similar(pid: str, season: int, row: dict, index: tuple, names: dict[str, str], k: int = 6) -> list[dict]:
    """Nearest neighbours (other players, any season) by RMS distance between field-percentile vectors."""
    M, ids, keys = index
    if not len(ids) or not row.get("qualified"):
        return []
    pct = row.get("pct") or {}
    x = np.array([float(pct.get(kk, 50)) for kk in keys])
    d = np.sqrt(np.mean((M - x[None, :]) ** 2, axis=1))
    order = np.argsort(d)
    out = []
    for j in order:
        p, s = ids[j]
        if p == pid:
            continue
        out.append({"id": p, "name": names.get(p, p), "season": s, "distance": round(float(d[j]), 2)})
        if len(out) >= k:
            break
    return out
