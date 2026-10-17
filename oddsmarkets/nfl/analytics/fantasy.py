"""
Fantasy football (docs/VALUE_SECTIONS.md section 5): PPR / half-PPR / standard projections for the coming week and the
rest of the season from our play-level data and game model, rankings, start/sit, waiver targets, buy-low / sell-high,
streaming D/ST and kickers, schedule strength, our picks, and a walk-forward backtest. Payloads: <S>/fantasy.json and
fantasy_backtest.json (PAYLOADS.md "As built").

Sources: nflverse play-by-play and weekly player / team stats (computed by nflfastR from the NFL's play-by-play,
CC-BY 4.0), nflverse injury reports and weekly rosters (the NFL's), our game model's implied team totals
(schedule.json: walk-forward for past games). Left out, with the reason shown on the page:
  * snap counts: nflverse's come from Pro Football Reference (load_snap_counts: "provided by Pro Football Reference"),
    whose terms forbid building websites or tools on its data;
  * routes run: no public play-level source in season (participation data arrive after the season);
  * fantasy-platform data (ADP, ownership, salaries): every platform's terms restrict reuse, so availability for
    waiver targets is our proxy (outside the top scorers at the position), labelled as such.

Scoring (points per unit): passing yard 0.04, passing TD 4, interception -2, rushing / receiving yard 0.1, rushing /
receiving TD 6, fumble lost -2, two-point conversion 2; reception 1 (PPR), 0.5 (half) or 0 (standard). Kickers: FG
0-39 yards 3, 40-49 4, 50+ 5, extra point 1, missed FG or XP -1. D/ST: sack 1, interception 2, fumble recovery 2,
safety 2, defensive or special-teams TD 6, blocked kick 2; points allowed 0: 10, 1-6: 7, 7-13: 4, 14-20: 1, 21-27: 0,
28-34: -1, 35+: -4.

The model, per player and week (everything from games before that week)
------------------------------------------------------------------------
Usage. A player's shares of his team's targets, carries, expected receiving TDs and expected rushing TDs (QBs: pass
attempts) in the games he played, weighted by recency (half-life HL weeks), with last season's shares as a prior worth
PRIOR_G games. Expected TDs come from a play-level table (fitted on the three seasons before): the chance a target
scores given its yard line and air yards, a carry given its yard line; so red-zone usage enters through them.
Team volume. The team's targets and carries per game (recency-weighted, last season as a prior), shifted by game
script: the expected margin from our game model (team implied points minus the opponent's) moves pass and run volume
by fitted slopes. Team offensive TDs per game = a + b x implied points (fitted), split into passing and rushing by the
team's expected-TD mix.
Efficiency, shrunk. Catch rate and yards per target toward the player's own expected values (from where his targets
are thrown), yards per carry toward his expected yards per carry, QB yards per attempt and interception rate toward
the league, each with a shrinkage constant in attempts.
Opponent. Fantasy points the opponent allows to the position per game against the league average (recency-weighted,
shrunk with K_OPP games, last season as a prior), applied to yards and TDs with exponent ALPHA (fitted), not volume.
Availability. Injury report: out 0; doubtful and questionable at the fitted rate players with that status played;
injured reserve, PUP, suspension and similar 0. Targets and carries a missing player leaves are shared among his
team-mates in proportion to their shares, and each team's shares are capped at what teams actually spread.
Starting QB: the game card's QB (our depth chart), else the QB with the team's most recent start.
Floor and ceiling: the 10th and 90th percentiles of a normal around the projection with SD = c0 + c1 x projection by
position, fitted on the backtest residuals.

Backtest. Every week of the evaluation seasons is projected from the games before it only (game-model prices are
walk-forward too); compared with actual points (0 when a player did not play) for the players who were fantasy-relevant
going in (top 32 QB, 64 RB, 96 WR, 32 TE by season-to-date or last-season points per game), against two baselines:
season-to-date points per game and last season's points per game. Parameters were tuned on 2014-2018 only.
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an

logger = logging.getLogger(__name__)

VERSION = "fantasy-1"
POS4 = ("QB", "RB", "WR", "TE")
FORMATS = ("ppr", "half", "std")
REC_PTS = {"ppr": 1.0, "half": 0.5, "std": 0.0}
DST_PA = ((0, 10.0), (6, 7.0), (13, 4.0), (20, 1.0), (27, 0.0), (34, -1.0), (999, -4.0))   # (max points allowed, pts)
TUNE = (2014, 2018)
EVAL_FIRST = 2019
FRAME_FIRST = 2013
PARAMS: dict[str, float] = {
    "HL": 4.0, "PRIOR_G": 3.0, "ALPHA": 0.5, "K_OPP": 4.0, "TEAM_PRIOR_G": 4.0, "TEAM_HL": 6.0,
    "K_CATCH": 40.0, "K_YPT": 60.0, "K_YPC": 100.0, "K_YPA": 200.0, "K_INT": 400.0,
    "B_PASS": -0.45, "B_RUSH": 0.55, "TD_A": -0.35, "TD_B": 0.125, "P_Q": 0.88, "P_D": 0.25, "FL_RATE": 0.0055,
    "K_A": 2.6, "K_B": 0.24, "DST_SD": 9.5, "TGT_CAP": 0.96, "CAR_CAP": 0.97,
}
REG_WEEKS = 18
PREV_W = 0.5            # last season's efficiency counts half


# ---------------------------------------------------------------------------------------------- scoring

def points(stat: dict | pd.DataFrame, fmt: str = "ppr"):
    """Fantasy points of a stat line (dict or frame columns): pass_yds, pass_td, ints, rush_yds, rush_td, rec, rec_yds,
    rec_td, fl, two_pt."""
    g = (lambda k: stat.get(k, 0.0) if isinstance(stat, dict) else (stat[k] if k in stat else 0.0))
    std = (0.04 * g("pass_yds") + 4.0 * g("pass_td") - 2.0 * g("ints") + 0.1 * (g("rush_yds") + g("rec_yds")) +
           6.0 * (g("rush_td") + g("rec_td")) - 2.0 * g("fl") + 2.0 * g("two_pt"))
    return std + REC_PTS[fmt] * g("rec")


def dst_pa_points(pa: float) -> float:
    for mx, p in DST_PA:
        if pa <= mx:
            return p
    return DST_PA[-1][1]


def dst_pa_expected(mu: float, sd: float) -> float:
    """Expected points-allowed score when the opponent's points ~ Normal(mu, sd), integrated over the buckets."""
    from scipy.special import ndtr
    edges = [-1e9] + [mx + 0.5 for mx, _ in DST_PA[:-1]] + [1e9]
    out = 0.0
    for i, (_, p) in enumerate(DST_PA):
        lo, hi = edges[i], edges[i + 1]
        out += p * float(ndtr((hi - mu) / sd) - ndtr((lo - mu) / sd))
    return out


def kicker_points(r: dict | pd.Series) -> float:
    g = (lambda k: float(r.get(k) or 0.0))
    made = 3 * (g("fg_made_0_19") + g("fg_made_20_29") + g("fg_made_30_39")) + 4 * g("fg_made_40_49") + \
        5 * (g("fg_made_50_59") + g("fg_made_60_"))
    return made + g("pat_made") - g("fg_missed") - g("pat_missed")


# ---------------------------------------------------------------------------------------------- play-level tables

YBINS = [0, 2, 5, 10, 20, 40, 100]          # yardline_100 upper edges: 1-2, 3-5, 6-10, 11-20, 21-40, 41-99
ABINS = [-100, 0, 5, 10, 15, 20, 30, 100]   # air yards: <0, 0-4, 5-9, 10-14, 15-19, 20-29, 30+


def _ybin(y: pd.Series) -> pd.Series:
    return pd.cut(pd.to_numeric(y, errors="coerce").fillna(75), YBINS, labels=False, include_lowest=True).fillna(5).astype(int)


def _abin(a: pd.Series) -> pd.Series:
    return pd.cut(pd.to_numeric(a, errors="coerce").fillna(5), ABINS, labels=False, right=False).fillna(1).astype(int)


PBP_COLS = ["game_id", "week", "season_type", "posteam", "defteam", "play_type", "pass_attempt", "rush_attempt", "sack", "qb_scramble",
            "two_point_attempt", "receiver_player_id", "rusher_player_id", "passer_player_id", "air_yards", "yardline_100", "complete_pass",
            "yards_gained", "pass_touchdown", "rush_touchdown", "td_player_id", "qb_kneel", "receiving_yards", "rushing_yards"]


def opportunities(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Regular-season targets T (receiver, yard-line and air-yards bins, caught, yards, TD) and carries C (rusher,
    yard-line bin, yards, TD) of a season's play-by-play (two-point tries, kneels and sacks excluded)."""
    from oddsmarkets.nfl.analytics.context import load_pbp
    df = load_pbp(season, PBP_COLS)
    if df is None or not len(df):
        return pd.DataFrame(), pd.DataFrame()
    df = df[(df["season_type"] == "REG") & (pd.to_numeric(df["two_point_attempt"], errors="coerce").fillna(0) == 0)]
    num = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0)   # noqa: E731
    tm = (num("pass_attempt") == 1) & (num("sack") == 0) & df["receiver_player_id"].notna()
    T = pd.DataFrame({"pid": df.loc[tm, "receiver_player_id"].astype(str), "team": df.loc[tm, "posteam"].astype(str),
                      "opp": df.loc[tm, "defteam"].astype(str), "game_id": df.loc[tm, "game_id"].astype(str),
                      "week": num("week")[tm].astype(int), "yb": _ybin(df.loc[tm, "yardline_100"]), "ab": _abin(df.loc[tm, "air_yards"]),
                      "air": pd.to_numeric(df.loc[tm, "air_yards"], errors="coerce").fillna(0.0),
                      "catch": num("complete_pass")[tm], "yds": pd.to_numeric(df.loc[tm, "receiving_yards"], errors="coerce").fillna(0.0),
                      "td": ((num("pass_touchdown") == 1) & (num("complete_pass") == 1))[tm].astype(float)})
    cm = (num("rush_attempt") == 1) & df["rusher_player_id"].notna() & (num("qb_kneel") == 0)
    C = pd.DataFrame({"pid": df.loc[cm, "rusher_player_id"].astype(str), "team": df.loc[cm, "posteam"].astype(str),
                      "opp": df.loc[cm, "defteam"].astype(str), "game_id": df.loc[cm, "game_id"].astype(str),
                      "week": num("week")[cm].astype(int), "yb": _ybin(df.loc[cm, "yardline_100"]),
                      "yds": pd.to_numeric(df.loc[cm, "rushing_yards"], errors="coerce").fillna(pd.to_numeric(df.loc[cm, "yards_gained"], errors="coerce")).fillna(0.0),
                      "td": (num("rush_touchdown") == 1)[cm].astype(float)})
    return T.reset_index(drop=True), C.reset_index(drop=True)


def fit_tables(Ts: list[pd.DataFrame], Cs: list[pd.DataFrame], min_n: int = 150) -> dict:
    """Expected outcome per opportunity: targets by (yard-line bin, air-yards bin) -> catch, yards, TD (cells with
    fewer than min_n targets fall back to the yard-line bin); carries by yard-line bin -> yards, TD."""
    T = pd.concat([t for t in Ts if len(t)], ignore_index=True) if any(len(t) for t in Ts) else pd.DataFrame()
    C = pd.concat([c for c in Cs if len(c)], ignore_index=True) if any(len(c) for c in Cs) else pd.DataFrame()
    out: dict[str, Any] = {"t": {}, "c": {}}
    if len(T):
        yb = T.groupby("yb")[["catch", "yds", "td"]].mean()
        cell = T.groupby(["yb", "ab"]).agg(n=("catch", "size"), catch=("catch", "mean"), yds=("yds", "mean"), td=("td", "mean"))
        for yi in range(len(YBINS) - 1):
            for ai in range(len(ABINS) - 1):
                if (yi, ai) in cell.index and cell.loc[(yi, ai), "n"] >= min_n:
                    r = cell.loc[(yi, ai)]
                elif yi in yb.index:
                    r = yb.loc[yi]
                else:
                    r = pd.Series({"catch": 0.64, "yds": 7.0, "td": 0.04})
                out["t"][f"{yi}|{ai}"] = [round(float(r["catch"]), 4), round(float(r["yds"]), 3), round(float(r["td"]), 4)]
        out["t_mean"] = [float(T["catch"].mean()), float(T["yds"].mean()), float(T["td"].mean())]
    if len(C):
        cb = C.groupby("yb")[["yds", "td"]].mean()
        for yi in range(len(YBINS) - 1):
            r = cb.loc[yi] if yi in cb.index else pd.Series({"yds": 4.3, "td": 0.03})
            out["c"][str(yi)] = [round(float(r["yds"]), 3), round(float(r["td"]), 4)]
        out["c_mean"] = [float(C["yds"].mean()), float(C["td"].mean())]
    return out


def apply_tables(T: pd.DataFrame, C: pd.DataFrame, tab: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    if len(T):
        key = T["yb"].astype(str) + "|" + T["ab"].astype(str)
        m = tab.get("t") or {}
        dflt = tab.get("t_mean") or [0.64, 7.0, 0.04]
        vals = np.array([m.get(k, dflt) for k in key], float) if len(key) else np.zeros((0, 3))
        T = T.assign(xcatch=vals[:, 0], xyds=vals[:, 1], xtd=vals[:, 2], rz=(T["yb"] <= 3).astype(float))
    if len(C):
        m = tab.get("c") or {}
        dflt = tab.get("c_mean") or [4.3, 0.03]
        vals = np.array([m.get(str(k), dflt) for k in C["yb"]], float) if len(C) else np.zeros((0, 2))
        C = C.assign(xyds=vals[:, 0], xtd=vals[:, 1], rz=(C["yb"] <= 3).astype(float), gl=(C["yb"] <= 1).astype(float))
    return T, C


# ---------------------------------------------------------------------------------------------- the weekly frames

SP_COLS = ["player_id", "player_display_name", "position", "season_type", "week", "game_id", "team", "opponent_team", "completions", "attempts",
           "passing_yards", "passing_tds", "passing_interceptions", "sack_fumbles_lost", "carries", "rushing_yards", "rushing_tds",
           "rushing_fumbles_lost", "receptions", "targets", "receiving_yards", "receiving_tds", "receiving_fumbles_lost",
           "passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions", "special_teams_tds", "fantasy_points",
           "fantasy_points_ppr", "fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
           "fg_missed", "fg_att", "pat_made", "pat_missed", "pat_att"]


def _canon(t: Any, season: int) -> str:
    from oddsmarkets.nfl.analytics import teamsref
    return teamsref.canon_abbr(str(t), season) if t is not None else t


def stats_frame(season: int) -> pd.DataFrame:
    """Regular-season player-weeks from nflverse's weekly player stats, with our stat line columns and fantasy points
    in the three formats (and the kicker's points)."""
    from oddsmarkets.nfl.analytics.context import load_release
    df = load_release("stats_player", season, SP_COLS)
    if df is None or not len(df):
        return pd.DataFrame()
    df = df[df["season_type"] == "REG"].copy()
    n = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0.0) if c in df else 0.0   # noqa: E731
    out = pd.DataFrame({"pid": df["player_id"].astype(str), "name": df["player_display_name"].astype(str),
                        "pos": df["position"].astype(str), "week": pd.to_numeric(df["week"], errors="coerce").astype(int),
                        "game_id": df["game_id"].astype(str), "team": [_canon(t, season) for t in df["team"]],
                        "opp": [_canon(t, season) for t in df["opponent_team"]],
                        "att": n("attempts"), "cmp": n("completions"), "pass_yds": n("passing_yards"), "pass_td": n("passing_tds"),
                        "ints": n("passing_interceptions"), "car": n("carries"), "rush_yds": n("rushing_yards"), "rush_td": n("rushing_tds"),
                        "rec": n("receptions"), "tgt": n("targets"), "rec_yds": n("receiving_yards"), "rec_td": n("receiving_tds"),
                        "fl": n("sack_fumbles_lost") + n("rushing_fumbles_lost") + n("receiving_fumbles_lost"),
                        "two_pt": n("passing_2pt_conversions") + n("rushing_2pt_conversions") + n("receiving_2pt_conversions"),
                        "st_td": n("special_teams_tds"), "fp_nv": n("fantasy_points"), "fp_nv_ppr": n("fantasy_points_ppr")})
    for c in ("fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_", "fg_missed", "fg_att",
              "pat_made", "pat_missed", "pat_att"):
        out[c] = n(c)
    out["pos"] = out["pos"].replace({"FB": "RB", "HB": "RB"})
    for f in FORMATS:
        out["fp_" + f] = points(out, f) + 6.0 * out["st_td"]
    out["fp_k"] = (3 * (out["fg_made_0_19"] + out["fg_made_20_29"] + out["fg_made_30_39"]) + 4 * out["fg_made_40_49"]
                   + 5 * (out["fg_made_50_59"] + out["fg_made_60_"]) + out["pat_made"] - out["fg_missed"] - out["pat_missed"])
    return out.reset_index(drop=True)


def player_weeks(season: int, tab: dict) -> pd.DataFrame:
    """stats_frame joined with the play-level usage of the week: red-zone targets and carries, goal-line carries, air
    yards, expected catches / receiving yards / receiving TDs / rushing yards / rushing TDs, and the team's totals of
    the week (targets, carries, expected TDs, pass attempts)."""
    S = stats_frame(season)
    if not len(S):
        return S
    T, C = opportunities(season)
    T, C = apply_tables(T, C, tab)
    if len(T):
        T = T.assign(team=[_canon(t, season) for t in T["team"]])
        tp = T.groupby(["pid", "week"]).agg(tgt_pbp=("catch", "size"), rz_tgt=("rz", "sum"), air=("air", "sum"), xrec=("xcatch", "sum"),
                                             xrec_yds=("xyds", "sum"), xrec_td=("xtd", "sum")).reset_index()
        tt = T.groupby(["team", "week"]).agg(team_tgt=("catch", "size"), team_rz_tgt=("rz", "sum"), team_xrec_td=("xtd", "sum"),
                                              team_air=("air", "sum")).reset_index()
    else:
        tp = pd.DataFrame(columns=["pid", "week", "tgt_pbp", "rz_tgt", "air", "xrec", "xrec_yds", "xrec_td"])
        tt = pd.DataFrame(columns=["team", "week", "team_tgt", "team_rz_tgt", "team_xrec_td", "team_air"])
    if len(C):
        C = C.assign(team=[_canon(t, season) for t in C["team"]])
        cp = C.groupby(["pid", "week"]).agg(car_pbp=("yds", "size"), rz_car=("rz", "sum"), gl_car=("gl", "sum"), xrush_yds=("xyds", "sum"),
                                             xrush_td=("xtd", "sum")).reset_index()
        ct = C.groupby(["team", "week"]).agg(team_car=("yds", "size"), team_rz_car=("rz", "sum"), team_xrush_td=("xtd", "sum")).reset_index()
    else:
        cp = pd.DataFrame(columns=["pid", "week", "car_pbp", "rz_car", "gl_car", "xrush_yds", "xrush_td"])
        ct = pd.DataFrame(columns=["team", "week", "team_car", "team_rz_car", "team_xrush_td"])
    out = S.merge(tp, on=["pid", "week"], how="left").merge(cp, on=["pid", "week"], how="left")
    out = out.merge(tt, on=["team", "week"], how="left").merge(ct, on=["team", "week"], how="left")
    ta = S.groupby(["team", "week"])["att"].sum().rename("team_att").reset_index()
    out = out.merge(ta, on=["team", "week"], how="left")
    for c in ("tgt_pbp", "rz_tgt", "air", "xrec", "xrec_yds", "xrec_td", "car_pbp", "rz_car", "gl_car", "xrush_yds", "xrush_td",
              "team_tgt", "team_rz_tgt", "team_xrec_td", "team_air", "team_car", "team_rz_car", "team_xrush_td", "team_att"):
        out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0.0)
    out["xfp_ppr"] = out["xrec"] + 0.1 * (out["xrec_yds"] + out["xrush_yds"]) + 6.0 * (out["xrec_td"] + out["xrush_td"])
    out["season"] = season
    return out


def team_weeks(season: int, pw: pd.DataFrame, games: dict[str, dict]) -> pd.DataFrame:
    """Per team and week: points scored and allowed, the opponent, D/ST stats and points (nflverse weekly team stats),
    kicker points, and the game model's implied points for both sides."""
    from oddsmarkets.nfl.analytics.context import load_release
    rows = []
    for gid, g in games.items():
        if g.get("gtype") not in (None, "REG") or g.get("week") is None:
            continue
        m = g.get("model") or {}
        for side, oside in (("home", "away"), ("away", "home")):
            t, o = g.get(side), g.get(oside)
            if not t or not o:
                continue
            pf, pa = (g.get("hs"), g.get("as")) if side == "home" else (g.get("as"), g.get("hs"))
            imp = m.get("home_pts") if side == "home" else m.get("away_pts")
            oimp = m.get("away_pts") if side == "home" else m.get("home_pts")
            rows.append({"team": t, "opp": o, "week": int(g["week"]), "game_id": gid, "pf": pf, "pa": pa, "imp": imp, "oimp": oimp,
                         "final": g.get("status") == "final", "home": side == "home", "kickoff": g.get("kickoff")})
    tw = pd.DataFrame(rows)
    if not len(tw):
        return tw
    st = load_release("stats_team", season, ["team", "week", "season_type", "def_sacks", "def_interceptions", "fumble_recovery_opp",
                                              "def_tds", "special_teams_tds", "def_safeties", "def_fg_blocks", "def_punt_blocks", "def_pat_blocks"])
    if st is not None and len(st):
        st = st[st["season_type"] == "REG"].copy()
        st["team"] = [_canon(t, season) for t in st["team"]]
        st["week"] = pd.to_numeric(st["week"], errors="coerce").astype(int)
        for c in ("def_sacks", "def_interceptions", "fumble_recovery_opp", "def_tds", "special_teams_tds", "def_safeties", "def_fg_blocks",
                  "def_punt_blocks", "def_pat_blocks"):
            st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0.0) if c in st else 0.0
        st = st.groupby(["team", "week"]).sum(numeric_only=True).reset_index()
        tw = tw.merge(st, on=["team", "week"], how="left")
    for c in ("def_sacks", "def_interceptions", "fumble_recovery_opp", "def_tds", "special_teams_tds", "def_safeties", "def_fg_blocks",
              "def_punt_blocks", "def_pat_blocks"):
        tw[c] = pd.to_numeric(tw[c], errors="coerce").fillna(0.0) if c in tw else 0.0
    tw["blk"] = tw["def_fg_blocks"] + tw["def_punt_blocks"] + tw["def_pat_blocks"]
    tw["takeaways"] = tw["def_interceptions"] + tw["fumble_recovery_opp"]
    pa = pd.to_numeric(tw["pa"], errors="coerce")
    tw["dst_pts"] = (tw["def_sacks"] + 2 * tw["takeaways"] + 2 * tw["def_safeties"] + 6 * (tw["def_tds"] + tw["special_teams_tds"]) + 2 * tw["blk"]
                     + pa.map(lambda x: dst_pa_points(x) if pd.notna(x) else np.nan))
    if pw is not None and len(pw):
        kp = pw[pw["fg_att"] + pw["pat_att"] > 0].groupby(["team", "week"])["fp_k"].sum().rename("k_pts").reset_index()
        tw = tw.merge(kp, on=["team", "week"], how="left")
        # offensive TDs and the sacks the offence allowed
        off = pw.groupby(["team", "week"]).agg(off_td=("rush_td", "sum"), rec_td=("rec_td", "sum")).reset_index()
        off["off_td"] = off["off_td"] + off["rec_td"]
        tw = tw.merge(off[["team", "week", "off_td", "rec_td"]], on=["team", "week"], how="left")
        opp_stats = tw[["team", "week", "def_sacks", "takeaways"]].rename(columns={"team": "opp", "def_sacks": "sacked", "takeaways": "gave"})
        tw = tw.merge(opp_stats, on=["opp", "week"], how="left")
    tw["season"] = season
    return tw


# ---------------------------------------------------------------------------------------------- caches

def _sig(season: int) -> str:
    from oddsmarkets.nfl.analytics.context import release_files
    parts = [VERSION]
    for rel in ("pbp", "stats_player", "stats_team"):
        for p in release_files(rel, season)[:2]:
            try:
                st = p.stat()
                parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
            except OSError:
                pass
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


_MEM: dict[tuple, Any] = {}


def season_opps(season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    k = ("opps", season)
    if k not in _MEM:
        _MEM[k] = opportunities(season)
    return _MEM[k]


def tables_for(season: int) -> dict:
    """The expected-outcome tables for a season: fitted on the three seasons before it."""
    k = ("tab", season)
    if k in _MEM:
        return _MEM[k]
    Ts, Cs = [], []
    for s in range(season - 3, season):
        T, C = season_opps(s)
        Ts.append(T)
        Cs.append(C)
    _MEM[k] = fit_tables(Ts, Cs)
    return _MEM[k]


def frames(season: int, games: dict[str, dict] | None = None, use_cache: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(player weeks, team weeks) of a season, cached as parquet under <cache>/analytics/fantasy keyed on the input
    files (the current season is rebuilt whenever its files change)."""
    d = an.an_cache() / "fantasy"
    sig = _sig(season)
    pp, tp = d / f"pw_{season}_{sig}.parquet", d / f"tw_{season}_{sig}.parquet"
    if use_cache and pp.exists() and tp.exists() and games is None:
        try:
            return pd.read_parquet(pp), pd.read_parquet(tp)
        except Exception:                                        # noqa: BLE001
            pass
    pw = player_weeks(season, tables_for(season))
    if games is None:
        games = season_games(season)
    tw = team_weeks(season, pw, games)
    if use_cache and len(pw):
        d.mkdir(parents=True, exist_ok=True)
        for old in list(d.glob(f"pw_{season}_*.parquet")) + list(d.glob(f"tw_{season}_*.parquet")):
            try:
                old.unlink()
            except OSError:
                pass
        pw.to_parquet(pp, index=False)
        tw.to_parquet(tp, index=False)
    return pw, tw


def season_games(season: int) -> dict[str, dict]:
    """The season's game cards from schedule.json (model blocks: walk-forward for games played, the game model for
    the coming ones); the schedules release when schedule.json is missing."""
    d = an.read_json(an.data_root() / str(season) / "schedule.json") or {}
    out = {}
    for g in d.get("games") or []:
        if g.get("game_id"):
            out[g["game_id"]] = g
    if out:
        return out
    from oddsmarkets.nfl.analytics.context import games_from_schedule
    try:
        gs = games_from_schedule(season)
    except Exception:                                            # noqa: BLE001
        gs = {}
    for gid, g in gs.items():
        out[gid] = {"game_id": gid, "week": g.get("week"), "gtype": g.get("gtype") or g.get("game_type"), "home": g.get("home"),
                    "away": g.get("away"), "hs": g.get("home_score"), "as": g.get("away_score"), "status": g.get("status"), "model": {}}
    return out
