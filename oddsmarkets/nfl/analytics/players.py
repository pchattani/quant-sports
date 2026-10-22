"""
players.json: the season catalogue by position group (QB, RB, WR, TE, K, P, DEF).

Values are computed from the season's regular-season plays (nflverse play-by-play, with FTN charting from 2022 and
participation 2016-2025 joined) and our models where they score: our completion probability (CPOE), expected
YAC, rush yards over expected, field-goal make probability, player value and the QB composite. NGS season rows add
time to throw, aggressiveness, separation, cushion and NGS RYOE (2016 onward).

Percentiles: direction-aware (100 = best), placed against the group's reference pool after shrinking the value toward
the pool mean with the metric's stabilisation constant ((n v + k m) / (n + k)); a metric needs its sample floor
before it gets a percentile. pct_pos compares within the listed position (defence: DL, LB, DB; receivers: WR, TE).
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl import analytics as an
from oddsmarkets.nfl.analytics import adapters, people
from oddsmarkets.nfl.analytics.context import SeasonContext, flag, num

logger = logging.getLogger(__name__)
M = an.metric
GROUPS = ("QB", "RB", "WR", "TE", "K", "P", "DEF")

QB_METRICS = [
    M("composite", "QB composite", "Value", "1", scope="QB", desc="Gridiron QB composite: EPA per dropback, CPOE, sack avoidance and "
      "turnover-worthy plays, each stabilisation-shrunk, on a 100 = average, 10 = one SD scale (our qb model; a blend of "
      "the same components when it is not available)."),
    M("composite_epa", "Composite forecast", "Value", "epa", scope="QB", desc="Our QB composite in its own unit: the "
      "forecast of next season's EPA per dropback from this season's stabilisation-shrunk components (null when the model is "
      "not available)."),
    M("value", "Gridiron Value", "Value", "1", scope="QB RB WR TE", desc="Expected points added credited to the player, adjusted for "
      "opponent and supporting cast (our player_value; raw EPA credit when the model is not available)."),
    M("epa_db", "EPA / dropback", "Passing", "epa", scope="QB", den="dropbacks", stab="epa_per_db",
      desc="Expected points added per dropback (passes, sacks and scrambles)."),
    M("epa_play", "EPA / play", "Passing", "epa", scope="QB", den="plays", stab="epa_per_play",
      desc="EPA per dropback or designed run."),
    M("epa_total", "Total EPA", "Passing", "1", scope="QB", desc="EPA summed over dropbacks and designed runs."),
    M("success", "Success rate", "Passing", "pct", scope="QB", den="dropbacks", stab="success",
      desc="Share of dropbacks with positive EPA."),
    M("cpoe", "CPOE", "Accuracy", "1", scope="QB", den="att", stab="cpoe",
      desc="Completion percentage over expected, in percentage points (our completion model; nflfastR's cp when ours is not ready)."),
    M("comp_pct", "Completion %", "Accuracy", "pct", scope="QB", den="att", stab="cpoe", desc="Completions per attempt."),
    M("adot", "aDOT", "Style", "yds", scope="QB", den="att", stab="adot", desc="Average depth of target (air yards per attempt)."),
    M("deep_rate", "Deep rate", "Style", "pct", scope="QB", den="att", stab="adot", desc="Share of attempts 20+ air yards downfield."),
    M("ttt", "Time to throw", "Style", "sec", scope="QB", lower=True, desc="NGS average time from snap to throw (seconds)."),
    M("aggressiveness", "Aggressiveness", "Style", "pct", scope="QB", desc="NGS share of attempts into tight windows (a defender "
      "within one yard)."),
    M("sack_rate", "Sack rate", "Pressure", "pct", lower=True, scope="QB", den="dropbacks", stab="sack_rate",
      desc="Sacks per dropback."),
    M("pressure_rate", "Pressure rate", "Pressure", "pct", lower=True, scope="QB", den="dropbacks", stab="pressure_rate",
      desc="Share of dropbacks under pressure (participation data 2016-2025; our pressure model otherwise)."),
    M("epa_pressure", "EPA under pressure", "Pressure", "epa", scope="QB", desc="EPA per dropback when pressured."),
    M("epa_clean", "EPA clean pocket", "Pressure", "epa", scope="QB", desc="EPA per dropback when not pressured."),
    M("pa_rate", "Play-action rate", "Play action", "pct", scope="QB", den="dropbacks", stab="pa_rate",
      desc="Share of dropbacks with play action (FTN charting, 2022 onward)."),
    M("epa_pa", "EPA on play action", "Play action", "epa", scope="QB", desc="EPA per play-action dropback (FTN)."),
    M("epa_no_pa", "EPA without play action", "Play action", "epa", scope="QB", desc="EPA per dropback without play action (FTN)."),
    M("scramble_rate", "Scramble rate", "Scrambles", "pct", scope="QB", den="dropbacks", stab="scramble_rate",
      desc="Scrambles per dropback."),
    M("scramble_epa", "Scramble EPA", "Scrambles", "1", scope="QB", desc="EPA summed over scrambles."),
    M("rush_epa_qb", "Designed-run EPA", "Scrambles", "1", scope="QB", desc="EPA summed over designed QB runs (sneaks included)."),
    M("int_rate", "INT rate", "Turnovers", "pct", lower=True, scope="QB", den="att", stab="int_rate", desc="Interceptions per attempt."),
    M("twp_rate", "Turnover-worthy rate", "Turnovers", "pct", lower=True, scope="QB", den="att", stab="twp_rate",
      desc="FTN interception-worthy throws per attempt (2022 onward)."),
    M("att", "Attempts", "Volume", "int", scope="QB", desc="Pass attempts."),
    M("pass_yds", "Passing yards", "Volume", "int", scope="QB", desc="Passing yards."),
    M("pass_td", "Passing TD", "Volume", "int", scope="QB", desc="Passing touchdowns."),
    M("ints", "Interceptions", "Volume", "int", scope="QB", desc="Interceptions thrown."),
    M("anya", "ANY/A", "Volume", "2", scope="QB", den="dropbacks", stab="epa_per_db",
      desc="Adjusted net yards per attempt: (yards + 20 TD - 45 INT - sack yards) / (attempts + sacks)."),
]
RB_METRICS = [
    M("value", "Gridiron Value", "Value", "1", scope="QB RB WR TE", desc="EPA credited to the player, adjusted for opponent and "
      "supporting cast (our player_value; raw EPA credit otherwise)."),
    M("rush_epa", "EPA / carry", "Rushing", "epa", scope="RB", den="carries", stab="rush_epa", desc="EPA per designed run."),
    M("rush_success", "Rush success", "Rushing", "pct", scope="RB", den="carries", stab="rush_success",
      desc="Share of carries with positive EPA."),
    M("ryoe", "RYOE / carry", "Rushing", "2", scope="RB", den="carries", stab="ryoe", desc="Rush yards over expected per carry (our "
      "rushing model; NGS RYOE 2016 onward when ours is not ready)."),
    M("ypc", "Yards / carry", "Rushing", "2", scope="RB", den="carries", stab="ryoe", desc="Rushing yards per carry."),
    M("explosive", "Explosive rate", "Rushing", "pct", scope="RB", den="carries", stab="explosive", desc="Carries of 10+ yards."),
    M("stuff_rate", "Stuff rate", "Rushing", "pct", lower=True, scope="RB", den="carries", stab="rush_success",
      desc="Carries for no gain or a loss."),
    M("box8", "8+ in box", "Rushing", "pct", scope="RB", desc="NGS share of carries against eight or more defenders in the box."),
    M("carries", "Carries", "Volume", "int", scope="RB", desc="Designed runs."),
    M("rush_yds", "Rushing yards", "Volume", "int", scope="RB", desc="Rushing yards."),
    M("rush_td", "Rushing TD", "Volume", "int", scope="RB", desc="Rushing touchdowns."),
    M("rec_epa_tgt", "EPA / target", "Receiving", "epa", scope="RB WR TE", den="targets", stab="rec_epa",
      desc="EPA per target (the receiver's share of the play)."),
    M("target_share", "Target share", "Receiving", "pct", scope="RB WR TE", den="targets", stab="target_share",
      desc="Targets per team pass attempt in his games."),
    M("targets", "Targets", "Volume", "int", scope="RB WR TE", desc="Targets."),
    M("rec", "Receptions", "Volume", "int", scope="RB WR TE", desc="Receptions."),
    M("rec_yds", "Receiving yards", "Volume", "int", scope="RB WR TE", desc="Receiving yards."),
]
REC_METRICS = [
    M("value", "Gridiron Value", "Value", "1", scope="QB RB WR TE", desc="EPA credited to the player, adjusted for opponent and "
      "supporting cast (our player_value; raw EPA credit otherwise)."),
    M("rec_epa_tgt", "EPA / target", "Receiving", "epa", scope="RB WR TE", den="targets", stab="rec_epa", desc="EPA per target."),
    M("rec_epa", "Receiving EPA", "Receiving", "1", scope="WR TE", desc="EPA summed over targets."),
    M("target_share", "Target share", "Usage", "pct", scope="RB WR TE", den="targets", stab="target_share",
      desc="Targets per team pass attempt in his games."),
    M("air_share", "Air-yards share", "Usage", "pct", scope="WR TE", den="targets", stab="target_share",
      desc="Share of the team's intended air yards in his games."),
    M("wopr", "WOPR", "Usage", "3", scope="WR TE", den="targets", stab="target_share",
      desc="Weighted opportunity rating: 1.5 target share + 0.7 air-yards share."),
    M("adot", "aDOT", "Usage", "yds", scope="WR TE", den="targets", stab="adot", desc="Average depth of target."),
    M("catch_rate", "Catch rate", "Hands", "pct", scope="WR TE", den="targets", stab="catch_rate", desc="Receptions per target."),
    M("croe", "Catch rate over expected", "Hands", "pct", scope="WR TE", den="targets", stab="catch_rate",
      desc="Receptions minus expected receptions (completion model) per target."),
    M("drop_rate", "Drop rate", "Hands", "pct", lower=True, scope="WR TE", den="catchable", stab="drop_rate",
      desc="FTN drops per catchable target (2022 onward)."),
    M("contested_rate", "Contested catch rate", "Hands", "pct", scope="WR TE", den="contested", stab="contested",
      desc="FTN contested targets caught (2022 onward)."),
    M("yac_rec", "YAC / reception", "After the catch", "yds", scope="WR TE", den="rec", stab="yacoe", desc="Yards after catch per reception."),
    M("yacoe", "YAC over expected", "After the catch", "2", scope="WR TE", den="rec", stab="yacoe",
      desc="Yards after catch minus expected YAC per reception (our xYAC; nflfastR's xYAC otherwise)."),
    M("separation", "Separation", "NGS", "yds", scope="WR TE", desc="NGS average separation at the catch or incompletion (yards)."),
    M("cushion", "Cushion", "NGS", "yds", scope="WR TE", desc="NGS average cushion at the snap (yards)."),
    M("yptpa", "Yards / team attempt", "Volume", "2", scope="WR TE", den="targets", stab="yprr",
      desc="Receiving yards per team pass attempt in his games (a route-free YPRR proxy)."),
    M("targets", "Targets", "Volume", "int", scope="RB WR TE", desc="Targets."),
    M("rec", "Receptions", "Volume", "int", scope="RB WR TE", desc="Receptions."),
    M("rec_yds", "Receiving yards", "Volume", "int", scope="RB WR TE", desc="Receiving yards."),
    M("rec_td", "Receiving TD", "Volume", "int", scope="WR TE", desc="Receiving touchdowns."),
]
K_METRICS = [
    M("fg_oe", "FG over expected", "Kicking", "2", scope="K", den="fga", stab="fg_oe",
      desc="Field goals made minus expected (our make-probability model by distance and conditions)."),
    M("pts_oe", "Points over expected", "Kicking", "1", scope="K", desc="3 x FG over expected + extra points over expected."),
    M("fg_pct", "FG %", "Kicking", "pct", scope="K", den="fga", stab="fg_oe", desc="Field goals made per attempt."),
    M("fg_50", "50+ made", "Kicking", "int", scope="K", desc="Field goals of 50+ yards made."),
    M("fg_50_pct", "50+ %", "Kicking", "pct", scope="K", desc="Field goals of 50+ yards made per attempt."),
    M("avg_dist", "Average attempt", "Kicking", "yds", scope="K", desc="Average field-goal attempt distance."),
    M("xp_pct", "XP %", "Kicking", "pct", scope="K", desc="Extra points made per attempt."),
    M("fga", "FG attempts", "Volume", "int", scope="K", desc="Field-goal attempts."),
    M("fgm", "FG made", "Volume", "int", scope="K", desc="Field goals made."),
]
P_METRICS = [
    M("epa_punt", "EPA / punt", "Punting", "epa", scope="P", den="punts", stab="punt_net", desc="EPA per punt for the punting team."),
    M("net", "Net average", "Punting", "yds", scope="P", den="punts", stab="punt_net",
      desc="Gross distance less return yards and 20 yards per touchback."),
    M("gross", "Gross average", "Punting", "yds", scope="P", den="punts", stab="punt_net", desc="Average punt distance."),
    M("inside20", "Inside 20", "Punting", "pct", scope="P", den="punts", stab="punt_net", desc="Punts downed or returned inside the 20."),
    M("touchback_rate", "Touchback rate", "Punting", "pct", lower=True, scope="P", den="punts", stab="punt_net", desc="Touchbacks per punt."),
    M("net_oe", "Net over expected", "Punting", "2", scope="P", den="punts", stab="punt_net",
      desc="Opponent field position over expected per punt, in yards (our punt model by launch spot)."),
    M("punt_epa", "Punting EPA", "Punting", "1", scope="P", desc="EPA summed over punts for the punting team."),
    M("punts", "Punts", "Volume", "int", scope="P", desc="Punts."),
]
DEF_METRICS = [
    M("def_value", "Splash EPA", "Value", "1", scope="DEF", desc="EPA prevented on plays the player made (sack, interception, forced "
      "fumble, pass defensed, tackle for loss), shared among the credited players. Individual defensive value is limited by the data."),
    M("splash_pg", "Splash plays / game", "Value", "2", scope="DEF", den="games", k=6.0,
      desc="Sacks, interceptions, forced fumbles, passes defensed and tackles for loss per game."),
    M("sacks", "Sacks", "Pass rush", "1", scope="DEF", desc="Sacks (half sacks count 0.5)."),
    M("qb_hits", "QB hits", "Pass rush", "int", scope="DEF", desc="QB hits."),
    M("pressures_pg", "Sacks + hits / game", "Pass rush", "2", scope="DEF", den="games", k=6.0, desc="Sacks and QB hits per game."),
    M("tfl", "Tackles for loss", "Run defence", "int", scope="DEF", desc="Tackles for loss."),
    M("tackles", "Tackles", "Run defence", "int", scope="DEF",
      desc="Solo and assisted tackles, special teams included (the official count)."),
    M("ints", "Interceptions", "Coverage", "int", scope="DEF", desc="Interceptions."),
    M("pd", "Passes defensed", "Coverage", "int", scope="DEF", desc="Passes defensed."),
    M("ff", "Forced fumbles", "Coverage", "int", scope="DEF", desc="Forced fumbles."),
]
for _m in DEF_METRICS + QB_METRICS + RB_METRICS + REC_METRICS + K_METRICS + P_METRICS:
    if _m["fmt"] == "int" and _m["key"] in ("fg_50", "sacks"):
        _m["_pct_int"] = True


def all_metrics() -> list[dict]:
    seen, out = set(), []
    for ms in (QB_METRICS, RB_METRICS, REC_METRICS, K_METRICS, P_METRICS, DEF_METRICS):
        for m in ms:
            if m["key"] not in seen:
                seen.add(m["key"])
                out.append(m)
    return out


GROUP_METRICS = {"QB": QB_METRICS, "RB": RB_METRICS, "WR": REC_METRICS, "TE": REC_METRICS, "K": K_METRICS, "P": P_METRICS,
                 "DEF": DEF_METRICS}


# ---------------------------------------------------------------------------------------------- inputs

def reg_plays(ctx: SeasonContext) -> pd.DataFrame:
    P = ctx.plays()
    if not len(P) or "season_type" not in P:
        return P
    return P[P["season_type"].astype(str).str.upper() == "REG"]


def scrimmage(P: pd.DataFrame, two_point: bool = True) -> pd.DataFrame:
    """Pass and run plays; two_point=False drops two-point tries (they are not attempts, carries or targets in the
    official count, and nflverse's player stats leave them out)."""
    if "play_type" not in P:
        return P.iloc[0:0]
    S = P[P["play_type"].isin(["pass", "run"])]
    if not two_point and "two_point_attempt" in S:
        S = S[flag(S, "two_point_attempt").fillna(0) != 1]
    return S


def pass_yards(D: pd.DataFrame) -> pd.Series:
    """Passing yards per play: nflfastR's passing_yards (official credit), else yards gained on a completion."""
    fb = num(D, "yards_gained").fillna(0).where(flag(D, "complete_pass").fillna(0) == 1, 0)
    return num(D, "passing_yards").fillna(fb).fillna(0)


def rec_yards(X: pd.DataFrame) -> pd.Series:
    """Receiving yards credited to the targeted receiver: nflfastR's receiving_yards (a lateral's yards go to the
    lateral receiver), else yards gained on a completion."""
    c = flag(X, "complete_pass").fillna(0) == 1
    return num(X, "receiving_yards").where(c).fillna(num(X, "yards_gained").where(c)).fillna(0).where(c, 0)


def rush_yards(R: pd.DataFrame) -> pd.Series:
    """Rushing yards credited to the ball carrier: nflfastR's rushing_yards, else yards gained."""
    return num(R, "rushing_yards").fillna(num(R, "yards_gained")).fillna(0)


def td_credit(df: pd.DataFrame, col: str) -> pd.Series:
    """A touchdown flag credited to the play's player only when he scored it (td_player_id; a lateral's scorer is
    credited by lateral_yards(..., tds=True))."""
    td = flag(df, col).fillna(0)
    if "td_player_id" not in df:
        return td
    who = df["td_player_id"]
    me = df["pid"] if "pid" in df else None
    if me is None:
        return td
    return td.where(who.isna() | (who.astype(object) == me.astype(object)), 0.0)


def lateral_yards(df: pd.DataFrame, kind: str, tds: bool = False) -> pd.Series:
    """Yards after a lateral credited to the lateral receiver (kind 'receiving' or 'rushing'), by (pid, game_id);
    tds=True: the lateral receiver's touchdowns instead."""
    if kind == "receiving":
        idc, yc = "lateral_receiver_player_id", "lateral_receiving_yards"
    else:
        idc, yc = "lateral_rusher_player_id", "lateral_rushing_yards"
    if idc not in df or yc not in df or not len(df):
        return pd.Series(dtype=float)
    m = df[idc].notna()
    if not m.any():
        return pd.Series(dtype=float)
    d = df[m]
    if tds:
        if "td_player_id" not in d:
            return pd.Series(dtype=float)
        v = (d["td_player_id"].astype(object) == d[idc].astype(object)).astype(float)
        v = v[v > 0]
        return v.groupby([d.loc[v.index, idc].astype(str), d.loc[v.index, "game_id"]]).sum()
    return num(d, yc).fillna(0).groupby([d[idc].astype(str), d["game_id"]]).sum()


def _pid(df: pd.DataFrame, *cols: str) -> pd.Series:
    """The first non-missing id across cols, in order (nflfastR's passer_id is empty on spikes, its rusher_id on
    scrambles; on an aborted snap rusher_id names the player who fumbled it, rusher_player_id the official carrier)."""
    out = None
    for c in cols:
        if c in df:
            s = df[c].astype(object)
            s = s.where(s.notna(), None)
            out = s if out is None else out.where(out.notna(), s)
    return out if out is not None else pd.Series(None, index=df.index, dtype=object)


def _team_last(df: pd.DataFrame, idcol: str, teamcol: str) -> dict[str, str]:
    if not len(df):
        return {}
    d = df[[idcol, teamcol, "game_id"]].dropna().sort_values("game_id")
    return d.groupby(idcol)[teamcol].last().to_dict()


def _games(frames: list[tuple[pd.DataFrame, str]]) -> dict[str, int]:
    parts = []
    for df, c in frames:
        if c in df and len(df):
            parts.append(df[[c, "game_id"]].dropna().rename(columns={c: "pid"}))
    if not parts:
        return {}
    a = pd.concat(parts).drop_duplicates()
    return a.groupby("pid")["game_id"].nunique().to_dict()


def ngs_map(ctx: SeasonContext, kind: str) -> dict[str, dict]:
    df = ctx.ngs(kind)
    if df is None or not len(df):
        return {}
    idc = "player_gsis_id" if "player_gsis_id" in df else ("gsis_id" if "gsis_id" in df else None)
    if not idc:
        return {}
    return {str(r[idc]): r for r in df.to_dict("records") if an.sid(r.get(idc))}


# ---------------------------------------------------------------------------------------------- groups

def qb_rows(ctx: SeasonContext, P: pd.DataFrame, tg: int) -> dict[str, dict]:
    S = scrimmage(P, two_point=False)
    if not len(S):
        return {}
    pid = _pid(S, "passer_id", "passer_player_id")
    db = flag(S, "qb_dropback").fillna(0) == 1
    D = S[db & pid.notna()].copy()
    D["pid"] = pid[db & pid.notna()]
    if not len(D):
        return {}
    D["epa_"] = num(D, "epa")
    D["sack_"] = flag(D, "sack").fillna(0)
    D["scr_"] = flag(D, "qb_scramble").fillna(0)
    D["int_"] = flag(D, "interception").fillna(0)
    D["cmp_"] = flag(D, "complete_pass").fillna(0)
    D["att_"] = ((D["sack_"] == 0) & (D["scr_"] == 0) & (D.get("play_type") == "pass")).astype(float)
    D["air_"] = num(D, "air_yards").where(D["att_"] == 1)
    D["deep_"] = (D["air_"] >= 20).astype(float).where(D["att_"] == 1)
    cp = num(D, "cp_ours") if "cp_ours" in D and D["cp_ours"].notna().any() else num(D, "cp")
    D["cpoe_"] = (D["cmp_"] - cp).where((D["att_"] == 1) & cp.notna())
    D["succ_"] = (D["epa_"] > 0).astype(float).where(D["epa_"].notna())
    D["pyd_"] = pass_yards(D).where(D["att_"] == 1, 0)
    D["ptd_"] = flag(D, "pass_touchdown").fillna(0)
    D["sackyds_"] = (-num(D, "yards_gained").fillna(0)).where(D["sack_"] == 1, 0)
    pr = flag(D, "was_pressure")
    if "pressure_ours" in D and D["pressure_ours"].notna().any():
        pr = pr.fillna(num(D, "pressure_ours"))
    D["press_"] = pr
    D["pa_"] = flag(D, "is_play_action")
    D["twp_"] = flag(D, "is_interception_worthy").where(D["att_"] == 1)
    g = D.groupby("pid")
    out: dict[str, dict] = {}
    agg = pd.DataFrame({
        "dropbacks": g.size(), "epa_sum": g["epa_"].sum(), "epa_db": g["epa_"].mean(), "success": g["succ_"].mean(),
        "att": g["att_"].sum(), "cmp": g["cmp_"].sum(), "sacks": g["sack_"].sum(), "scr": g["scr_"].sum(), "ints": g["int_"].sum(),
        "adot": g["air_"].mean(), "deep": g["deep_"].mean(), "cpoe": g["cpoe_"].mean(), "pyd": g["pyd_"].sum(), "ptd": g["ptd_"].sum(),
        "sackyds": g["sackyds_"].sum(), "press_n": g["press_"].count(), "press": g["press_"].mean(), "pa_n": g["pa_"].count(),
        "pa": g["pa_"].mean(), "twp_n": g["twp_"].count(), "twp": g["twp_"].sum(),
    })
    scr_epa = D[D["scr_"] == 1].groupby("pid")["epa_"].sum()
    ep_pr = D[D["press_"] >= 0.5].groupby("pid")["epa_"].mean()
    ep_cl = D[D["press_"] < 0.5].groupby("pid")["epa_"].mean()
    ep_pa = D[D["pa_"] == 1].groupby("pid")["epa_"].mean()
    ep_npa = D[D["pa_"] == 0].groupby("pid")["epa_"].mean()
    # designed QB runs
    R = S[(S.get("play_type") == "run") & (flag(S, "qb_scramble").fillna(0) == 0)]
    rid = _pid(R, "rusher_player_id", "rusher_id")
    R = R.assign(pid=rid)
    rq = R[R["pid"].isin(agg.index)].groupby("pid")
    run_epa = rq.apply(lambda x: num(x, "epa").sum()) if len(R[R["pid"].isin(agg.index)]) else pd.Series(dtype=float)
    run_n = rq.size() if len(R[R["pid"].isin(agg.index)]) else pd.Series(dtype=float)
    # spikes are pass attempts (incomplete) in the official count
    K = P[P["play_type"] == "qb_spike"] if "play_type" in P else P.iloc[0:0]
    kid = _pid(K, "passer_id", "passer_player_id")
    spikes = kid[kid.notna()].astype(str).value_counts() if len(K) else pd.Series(dtype=float)
    ngs = ngs_map(ctx, "passing")
    games = _games([(D, "pid"), (R, "pid")])
    team = _team_last(D, "pid", "posteam")
    for p, r in agg.iterrows():
        att, dbs = r["att"] + float(spikes.get(str(p), 0) or 0), r["dropbacks"]
        n_runs = float(run_n.get(p, 0) or 0)
        ng = ngs.get(p) or {}
        epa_tot = r["epa_sum"] + float(run_epa.get(p, 0) or 0)
        vals = {
            "epa_db": r["epa_db"], "epa_play": epa_tot / (dbs + n_runs) if dbs + n_runs else None, "epa_total": epa_tot,
            "success": r["success"], "cpoe": None if pd.isna(r["cpoe"]) else 100 * r["cpoe"], "comp_pct": an.div(r["cmp"], att),
            "adot": r["adot"], "deep_rate": r["deep"], "ttt": an.fnum(ng.get("avg_time_to_throw")),
            "aggressiveness": (an.fnum(ng.get("aggressiveness")) or 0) / 100 if ng.get("aggressiveness") is not None else None,
            "sack_rate": an.div(r["sacks"], dbs), "pressure_rate": r["press"] if r["press_n"] >= 0.5 * dbs else None,
            "epa_pressure": ep_pr.get(p) if r["press_n"] >= 0.5 * dbs else None,
            "epa_clean": ep_cl.get(p) if r["press_n"] >= 0.5 * dbs else None,
            "pa_rate": r["pa"] if r["pa_n"] >= 0.5 * dbs else None, "epa_pa": ep_pa.get(p) if r["pa_n"] >= 0.5 * dbs else None,
            "epa_no_pa": ep_npa.get(p) if r["pa_n"] >= 0.5 * dbs else None,
            "scramble_rate": an.div(r["scr"], dbs), "scramble_epa": float(scr_epa.get(p, 0) or 0),
            "rush_epa_qb": float(run_epa.get(p, 0) or 0), "int_rate": an.div(r["ints"], att),
            "twp_rate": an.div(r["twp"], r["twp_n"]) if r["twp_n"] >= 0.5 * att and att else None,
            "att": att, "pass_yds": r["pyd"], "pass_td": r["ptd"], "ints": r["ints"],
            "anya": an.div(r["pyd"] + 20 * r["ptd"] - 45 * r["ints"] - r["sackyds"], att + r["sacks"]),
            "value": epa_tot,
        }
        out[p] = {"values": vals, "n": {"dropbacks": dbs, "plays": dbs + n_runs, "att": att}, "team": team.get(p),
                  "games": games.get(p, 0), "qualified": att >= 14 * max(tg, 1), "ref": dbs >= max(40, 10 * tg),
                  "fallback_name": None}
    return out


def rush_rows(ctx: SeasonContext, P: pd.DataFrame, tg: int) -> tuple[dict[str, dict], pd.DataFrame]:
    S = scrimmage(P, two_point=False)
    R = S[(S.get("play_type") == "run") & (flag(S, "qb_scramble").fillna(0) == 0)].copy() if len(S) else S
    R["pid"] = _pid(R, "rusher_player_id", "rusher_id")
    R = R[R["pid"].notna()]
    if not len(R):
        return {}, R
    R["epa_"] = num(R, "epa")
    R["yds_"] = rush_yards(R)
    R["succ_"] = (R["epa_"] > 0).astype(float).where(R["epa_"].notna())
    R["exp_"] = (R["yds_"] >= 10).astype(float)
    R["stuff_"] = (R["yds_"] <= 0).astype(float)
    R["td_"] = td_credit(R, "rush_touchdown")
    R["ryoe_"] = (R["yds_"] - num(R, "xrush_ours")) if "xrush_ours" in R and R["xrush_ours"].notna().any() else np.nan
    g = R.groupby("pid")
    agg = pd.DataFrame({"carries": g.size(), "epa": g["epa_"].mean(), "epa_sum": g["epa_"].sum(), "succ": g["succ_"].mean(),
                        "yds": g["yds_"].sum(), "exp": g["exp_"].mean(), "stuff": g["stuff_"].mean(), "td": g["td_"].sum(),
                        "ryoe": g["ryoe_"].mean(), "ryoe_n": g["ryoe_"].count()})
    lat = lateral_yards(S, "rushing")
    if len(lat):
        agg["yds"] = agg["yds"] + lat.groupby(level=0).sum().reindex(agg.index.astype(str)).fillna(0).to_numpy()
    ngs = ngs_map(ctx, "rushing")
    team = _team_last(R, "pid", "posteam")
    out = {}
    for p, r in agg.iterrows():
        ng = ngs.get(p) or {}
        ryoe = r["ryoe"] if r["ryoe_n"] >= 0.5 * r["carries"] else an.fnum(ng.get("rush_yards_over_expected_per_att"))
        b8 = an.fnum(ng.get("percent_attempts_gte_eight_defenders"))
        out[p] = {"values": {"rush_epa": r["epa"], "rush_success": r["succ"], "ryoe": ryoe, "ypc": an.div(r["yds"], r["carries"]),
                             "explosive": r["exp"], "stuff_rate": r["stuff"], "box8": b8 / 100 if b8 is not None and b8 > 1 else b8,
                             "carries": r["carries"], "rush_yds": r["yds"], "rush_td": r["td"], "rush_epa_sum": r["epa_sum"]},
                  "n": {"carries": r["carries"]}, "team": team.get(p)}
    return out, R


def rec_rows(ctx: SeasonContext, P: pd.DataFrame, tg: int) -> tuple[dict[str, dict], pd.DataFrame]:
    S = scrimmage(P, two_point=False)
    T = S[(S.get("play_type") == "pass") & (flag(S, "sack").fillna(0) == 0)].copy() if len(S) else S
    T["pid"] = _pid(T, "receiver_id", "receiver_player_id")
    if not len(T):
        return {}, T
    # team volume per (game, team) for shares
    T["air_"] = num(T, "air_yards")
    team_g = T.groupby(["game_id", "posteam"]).agg(team_att=("play_id", "size"), team_air=("air_", lambda s: s.clip(lower=0).sum()))
    X = T[T["pid"].notna()].copy()
    if not len(X):
        return {}, X
    X["epa_"] = num(X, "epa")
    X["cmp_"] = flag(X, "complete_pass").fillna(0)
    X["yds_"] = rec_yards(X)
    X["yac_"] = num(X, "yards_after_catch").where(X["cmp_"] == 1)
    xyac = num(X, "xyac_ours") if "xyac_ours" in X and X["xyac_ours"].notna().any() else num(X, "xyac_mean_yardage")
    X["yacoe_"] = (X["yac_"] - xyac).where(X["cmp_"] == 1)
    cp = num(X, "cp_ours") if "cp_ours" in X and X["cp_ours"].notna().any() else num(X, "cp")
    X["croe_"] = (X["cmp_"] - cp).where(cp.notna())
    X["td_"] = td_credit(X, "pass_touchdown")
    X["catchable_"] = flag(X, "is_catchable_ball")
    X["drop_"] = flag(X, "is_drop")
    X["cont_"] = flag(X, "is_contested_ball")
    X["contc_"] = (X["cont_"] == 1) & (X["cmp_"] == 1)
    g = X.groupby("pid")
    agg = pd.DataFrame({"targets": g.size(), "rec": g["cmp_"].sum(), "yds": g["yds_"].sum(), "epa": g["epa_"].mean(),
                        "epa_sum": g["epa_"].sum(), "adot": g["air_"].mean(), "air": g["air_"].sum(), "yac": g["yac_"].mean(),
                        "yacoe": g["yacoe_"].mean(), "croe": g["croe_"].mean(), "td": g["td_"].sum(),
                        "catchable": g["catchable_"].sum(), "catchable_n": g["catchable_"].count(), "drops": g["drop_"].sum(),
                        "cont": g["cont_"].sum(), "contc": g["contc_"].sum()})
    lat = lateral_yards(S, "receiving")
    if len(lat):
        agg["yds"] = agg["yds"] + lat.groupby(level=0).sum().reindex(agg.index.astype(str)).fillna(0).to_numpy()
    ltd = lateral_yards(S, "receiving", tds=True)
    if len(ltd):
        agg["td"] = agg["td"] + ltd.groupby(level=0).sum().reindex(agg.index.astype(str)).fillna(0).to_numpy()
    pg = X[["pid", "game_id", "posteam"]].drop_duplicates().merge(team_g.reset_index(), on=["game_id", "posteam"], how="left")
    vol = pg.groupby("pid").agg(team_att=("team_att", "sum"), team_air=("team_air", "sum"))
    ngs = ngs_map(ctx, "receiving")
    team = _team_last(X, "pid", "posteam")
    out = {}
    for p, r in agg.iterrows():
        ta, tair = an.fnum(vol["team_att"].get(p)), an.fnum(vol["team_air"].get(p))
        ts, ash = an.div(r["targets"], ta), an.div(max(r["air"], 0), tair)
        ng = ngs.get(p) or {}
        has_ftn = r["catchable_n"] >= 0.5 * r["targets"]
        out[p] = {"values": {"rec_epa_tgt": r["epa"], "rec_epa": r["epa_sum"], "target_share": ts, "air_share": ash,
                             "wopr": (1.5 * ts + 0.7 * ash) if ts is not None and ash is not None else None, "adot": r["adot"],
                             "catch_rate": an.div(r["rec"], r["targets"]), "croe": r["croe"],
                             "drop_rate": an.div(r["drops"], r["catchable"]) if has_ftn else None,
                             "contested_rate": an.div(r["contc"], r["cont"]) if has_ftn and r["cont"] >= 1 else None,
                             "yac_rec": r["yac"], "yacoe": r["yacoe"], "separation": an.fnum(ng.get("avg_separation")),
                             "cushion": an.fnum(ng.get("avg_cushion")), "yptpa": an.div(r["yds"], ta), "targets": r["targets"],
                             "rec": r["rec"], "rec_yds": r["yds"], "rec_td": r["td"]},
                  "n": {"targets": r["targets"], "rec": r["rec"], "catchable": r["catchable"] if has_ftn else 0,
                        "contested": r["cont"] if has_ftn else 0},
                  "team": team.get(p)}
    return out, X


def kick_rows(ctx: SeasonContext, P: pd.DataFrame, tg: int) -> dict[str, dict]:
    if "play_type" not in P:
        return {}
    F = P[P["play_type"] == "field_goal"].copy()
    XP = P[P["play_type"] == "extra_point"].copy()
    F["pid"] = _pid(F, "kicker_player_id")
    XP["pid"] = _pid(XP, "kicker_player_id")
    F = F[F["pid"].notna()]
    if not len(F):
        return {}
    F["made_"] = (F["field_goal_result"].astype(str) == "made").astype(float)
    F["dist_"] = num(F, "kick_distance")
    if "fg_prob_ours" in F and F["fg_prob_ours"].notna().any():
        F["xp_"] = num(F, "fg_prob_ours")
    else:
        F["xp_"] = league_fg_curve(F)
    XP["made_"] = (XP.get("extra_point_result", pd.Series(index=XP.index, dtype=object)).astype(str) == "good").astype(float)
    xp_rate = XP["made_"].mean() if len(XP) else None
    g = F.groupby("pid")
    agg = pd.DataFrame({"fga": g.size(), "fgm": g["made_"].sum(), "exp": g["xp_"].sum(), "dist": g["dist_"].mean()})
    f50 = F[F["dist_"] >= 50].groupby("pid")["made_"].agg(["sum", "count"])
    xg = XP.groupby("pid")["made_"].agg(["sum", "count"]) if len(XP) else pd.DataFrame(columns=["sum", "count"])
    team = _team_last(F, "pid", "posteam")
    games = _games([(F, "pid"), (XP, "pid")])
    out = {}
    for p, r in agg.iterrows():
        fg_oe = r["fgm"] - r["exp"] if pd.notna(r["exp"]) else None
        xs, xc = (float(xg["sum"].get(p, 0) or 0), float(xg["count"].get(p, 0) or 0)) if len(xg) else (0.0, 0.0)
        xp_oe = (xs - xc * xp_rate) if xp_rate is not None and xc else 0.0
        out[p] = {"values": {"fg_oe": fg_oe, "pts_oe": (3 * fg_oe + xp_oe) if fg_oe is not None else None, "fg_pct": an.div(r["fgm"], r["fga"]),
                             "fg_50": float(f50["sum"].get(p, 0) or 0) if len(f50) else 0.0,
                             "fg_50_pct": an.div(f50["sum"].get(p), f50["count"].get(p)) if len(f50) and p in f50.index else None,
                             "avg_dist": r["dist"], "xp_pct": an.div(xs, xc), "fga": r["fga"], "fgm": r["fgm"]},
                  "n": {"fga": r["fga"]}, "team": team.get(p), "games": games.get(p, 0)}
    return out


def league_fg_curve(F: pd.DataFrame) -> pd.Series:
    """P(make | distance) from a logistic fit on the frame's own attempts (a fallback when our kicking model
    does not score); a fixed modern-era curve when the frame is too small."""
    d = num(F, "kick_distance")
    y = (F["field_goal_result"].astype(str) == "made").astype(float)
    ok = d.notna()
    a, b = 6.6, -0.105                                           # ~ 2015-2025 league curve: 95 % at 33, 79 % at 48, 63 % at 55
    if ok.sum() >= 150:
        try:
            x = d[ok].to_numpy(float)
            t = y[ok].to_numpy(float)
            w = np.array([a, b])
            X = np.column_stack([np.ones_like(x), x])
            for _ in range(25):
                p = 1 / (1 + np.exp(-(X @ w)))
                W = p * (1 - p) + 1e-9
                H = X.T @ (X * W[:, None]) + np.eye(2) * 1e-3
                w = w + np.linalg.solve(H, X.T @ (t - p))
            a, b = float(w[0]), float(w[1])
        except Exception:                                        # noqa: BLE001
            pass
    return 1 / (1 + np.exp(-(a + b * d)))


def punt_rows(ctx: SeasonContext, P: pd.DataFrame, tg: int) -> dict[str, dict]:
    if "play_type" not in P:
        return {}
    U = P[P["play_type"] == "punt"].copy()
    U["pid"] = _pid(U, "punter_player_id")
    U = U[U["pid"].notna()]
    if not len(U):
        return {}
    U["gross_"] = num(U, "kick_distance")
    U["ret_"] = num(U, "return_yards").fillna(0)
    U["tb_"] = flag(U, "touchback").fillna(0)
    U["net_"] = U["gross_"] - U["ret_"] - 20 * U["tb_"]
    yl = num(U, "yardline_100")
    end = (yl - U["gross_"] + U["ret_"]).where(U["tb_"] == 0, 20)
    U["in20_"] = ((end <= 20) & (U["tb_"] == 0)).astype(float).where(U["gross_"].notna())
    U["epa_"] = num(U, "epa")
    g = U.groupby("pid")
    agg = pd.DataFrame({"punts": g.size(), "gross": g["gross_"].mean(), "net": g["net_"].mean(), "in20": g["in20_"].mean(),
                        "tb": g["tb_"].mean(), "epa": g["epa_"].mean()})
    team = _team_last(U, "pid", "posteam")
    games = _games([(U, "pid")])
    return {p: {"values": {"epa_punt": r["epa"], "net": r["net"], "gross": r["gross"], "inside20": r["in20"], "touchback_rate": r["tb"],
                           "punts": r["punts"], "punt_epa": r["epa"] * r["punts"]}, "n": {"punts": r["punts"]}, "team": team.get(p),
                "games": games.get(p, 0)} for p, r in agg.iterrows()}


DEF_CREDIT = {
    "sack_player_id": ("sacks", 1.0, True), "half_sack_1_player_id": ("sacks", 0.5, True), "half_sack_2_player_id": ("sacks", 0.5, True),
    "qb_hit_1_player_id": ("qb_hits", 1.0, False), "qb_hit_2_player_id": ("qb_hits", 1.0, False),
    "tackle_for_loss_1_player_id": ("tfl", 1.0, True), "tackle_for_loss_2_player_id": ("tfl", 1.0, True),
    "interception_player_id": ("ints", 1.0, True),
    "pass_defense_1_player_id": ("pd", 1.0, True), "pass_defense_2_player_id": ("pd", 1.0, True),
    "forced_fumble_player_1_player_id": ("ff", 1.0, True), "forced_fumble_player_2_player_id": ("ff", 1.0, True),
    "solo_tackle_1_player_id": ("tackles", 1.0, False), "solo_tackle_2_player_id": ("tackles", 1.0, False),
    "assist_tackle_1_player_id": ("tackles", 1.0, False), "assist_tackle_2_player_id": ("tackles", 1.0, False),
    "assist_tackle_3_player_id": ("tackles", 1.0, False), "assist_tackle_4_player_id": ("tackles", 1.0, False),
    "tackle_with_assist_1_player_id": ("tackles", 1.0, False), "tackle_with_assist_2_player_id": ("tackles", 1.0, False),
}
CREDIT_COLUMNS = ["pid", "game_id", "team", "stat", "w", "splash", "epa", "key", "scrim"]


def def_credits(P: pd.DataFrame) -> pd.DataFrame:
    """Every defensive credit on every play (special teams included, as in the official count and nflverse's player
    stats): pid, game_id, team, stat, w, splash, epa, key (game|play), scrim (a pass or run play, two-point tries out).
    The credited player's team comes from nflfastR's per-credit team column where it has one (a tackle after an
    interception or on a punt is made by the offence / kicking team), else the play's defteam."""
    if not len(P) or "game_id" not in P:
        return pd.DataFrame(columns=CREDIT_COLUMNS)
    epa = num(P, "epa")
    scrim = P["play_type"].isin(["pass", "run"]) if "play_type" in P else pd.Series(False, index=P.index)
    if "two_point_attempt" in P:
        scrim = scrim & (flag(P, "two_point_attempt").fillna(0) != 1)
    dteam = P["defteam"] if "defteam" in P else pd.Series(None, index=P.index, dtype=object)
    play = P["play_id"].astype(str) if "play_id" in P else pd.Series(P.index.astype(str), index=P.index)
    parts = []
    for col, (stat, w, splash) in DEF_CREDIT.items():
        if col not in P:
            continue
        m = P[col].notna()
        if not m.any():
            continue
        tcol = col.replace("_player_id", "_team")
        team = dteam[m]
        if tcol != col and tcol in P:
            team = P.loc[m, tcol].where(P.loc[m, tcol].notna(), team)
        parts.append(pd.DataFrame({"pid": P.loc[m, col].astype(str), "game_id": P.loc[m, "game_id"], "team": team, "stat": stat,
                                   "w": w, "splash": splash, "epa": epa[m], "key": P.loc[m, "game_id"].astype(str) + "|" + play[m],
                                   "scrim": scrim[m]}))
    if not parts:
        return pd.DataFrame(columns=CREDIT_COLUMNS)
    return pd.concat(parts, ignore_index=True)


def def_rows(ctx: SeasonContext, P: pd.DataFrame, tg: int) -> dict[str, dict]:
    if "play_type" not in P or not P["play_type"].isin(["pass", "run"]).any():
        return {}
    C = def_credits(P)
    if not len(C):
        return {}
    stats = C.pivot_table(index="pid", columns="stat", values="w", aggfunc="sum", fill_value=0)
    # splash value and splash plays: scrimmage plays only
    sp = C[C["splash"].astype(bool) & C["scrim"].astype(bool)]
    # splash EPA: -EPA of the play shared among its splash-credited players (one share per player per play)
    sp_u = sp.drop_duplicates(["pid", "key"])
    share = sp_u.groupby("key")["pid"].transform("size")
    sp_u = sp_u.assign(val=-sp_u["epa"].fillna(0) / share)
    val = sp_u.groupby("pid")["val"].sum()
    nspl = sp_u.groupby("pid").size()
    games = C.groupby("pid")["game_id"].nunique()
    team = C.sort_values("game_id").groupby("pid")["team"].last()
    out = {}
    for p in stats.index:
        r = stats.loc[p]
        gp = int(games.get(p, 0) or 0)
        sk, qh = float(r.get("sacks", 0)), float(r.get("qb_hits", 0))
        out[p] = {"values": {"def_value": float(val.get(p, 0) or 0), "splash_pg": an.div(nspl.get(p, 0), gp),
                             "sacks": sk, "qb_hits": qh, "pressures_pg": an.div(sk + qh, gp), "tfl": float(r.get("tfl", 0)),
                             "tackles": float(r.get("tackles", 0)), "ints": float(r.get("ints", 0)), "pd": float(r.get("pd", 0)),
                             "ff": float(r.get("ff", 0))},
                  "n": {"games": gp}, "team": team.get(p), "games": gp}
    return out


# ---------------------------------------------------------------------------------------------- the catalogue

def group_for(g: Any, default: str) -> str:
    """A player's catalogue group: his listed group when it is one of ours; the default when unknown; a known group
    outside ours (OL, long snappers) stays out: a centre who tackles after an interception or falls on a fumbled
    snap is not a defender or a running back."""
    return g if g in GROUPS else (default if not g else str(g))


def build(ctx: SeasonContext) -> dict | None:
    P = reg_plays(ctx)
    if not len(P):
        return {"ok": False, "reason": f"no play-by-play for {ctx.season}", "season": ctx.season}
    tg = max(ctx.team_games(), int(P.groupby("posteam")["game_id"].nunique().max()) if "posteam" in P else 0, 1)
    roster = people.season_roster(ctx)
    raw: dict[str, dict] = {}
    qb = qb_rows(ctx, P, tg)
    rushers, R = rush_rows(ctx, P, tg)
    recs, X = rec_rows(ctx, P, tg)
    kick = kick_rows(ctx, P, tg)
    punt = punt_rows(ctx, P, tg)
    dfn = def_rows(ctx, P, tg)
    games_all = _games([(R, "pid"), (X, "pid")])
    # names from the play table where the crosswalk lacks them
    names: dict[str, str] = {}
    for c_id, c_nm in (("passer_player_id", "passer_player_name"), ("rusher_player_id", "rusher_player_name"),
                       ("receiver_player_id", "receiver_player_name"), ("kicker_player_id", "kicker_player_name"),
                       ("punter_player_id", "punter_player_name")):
        if c_id in P and c_nm in P:
            d = P[[c_id, c_nm]].dropna().drop_duplicates(c_id)
            names.update(dict(zip(d[c_id].astype(str), d[c_nm].astype(str))))

    def group_of(pid: str, default: str) -> str:
        return group_for(people.info(pid, roster).get("group"), default)

    # QBs: dropback passers whose listed position is QB (or unknown with 20+ dropbacks)
    for p, r in qb.items():
        if group_of(p, "QB") == "QB" or (people.info(p, roster).get("pos") is None and r["n"]["dropbacks"] >= 20):
            raw[p] = {**r, "group": "QB"}
    for p, r in rushers.items():
        grp = group_of(p, "RB")
        if grp == "QB" or grp not in GROUPS:
            continue
        base = raw.get(p) or {"values": {}, "n": {}, "team": r.get("team"), "group": grp}
        base["values"].update(r["values"])
        base["n"].update(r["n"])
        raw[p] = base
    for p, r in recs.items():
        grp = group_of(p, "WR")
        if grp in ("QB", "K", "P", "DEF") or grp not in GROUPS:
            continue
        base = raw.get(p) or {"values": {}, "n": {}, "team": r.get("team"), "group": grp}
        base["values"].update(r["values"])
        base["n"].update(r["n"])
        base["team"] = base.get("team") or r.get("team")
        raw[p] = base
    for p, r in kick.items():
        raw[p] = {**r, "group": "K"}
    for p, r in punt.items():
        raw.setdefault(p, {**r, "group": "P"}) if p not in kick else None
    for p, r in dfn.items():
        if group_of(p, "DEF") == "DEF":
            raw[p] = {**r, "group": "DEF"}
    # placeholder ids ("0" where early play-by-play records no tackler, etc.) pool unknown players: not a player
    from oddsmarkets.nfl.analytics.careers import real_pid
    raw = {p: r for p, r in raw.items() if real_pid(p)}
    # our player-level models (isolated; a metric B does not answer keeps the play-by-play value)
    ext = adapters.player_tables(ctx) or {}
    used: dict[str, int] = {}
    over = {"QB": ("cpoe", "pressure_rate", "ttt", "composite", "value"), "RB": ("ryoe", "value"), "WR": ("croe", "yacoe", "value"),
            "TE": ("croe", "yacoe", "value"), "K": ("fg_oe", "pts_oe"), "P": ("net_oe",)}
    for p, r in raw.items():
        v = r["values"]
        if r["group"] in ("RB", "WR", "TE"):
            v["value"] = (v.get("rush_epa_sum") or 0) + (v.get("rec_epa") or 0)
        v.pop("rush_epa_sum", None)
        for k in over.get(r["group"], ()):
            x = (ext.get(k) or {}).get(p)
            if x is not None:
                v[k] = x
                used[k] = used.get(k, 0) + 1
    comp_src = "model" if used.get("composite") else "fallback"
    # rows, qualification and reference pools
    rows: dict[str, dict] = {}
    for p, r in raw.items():
        grp = r["group"]
        info = people.info(p, roster, names.get(p))
        n = r.get("n") or {}
        q = r.get("qualified")
        if q is None:
            q = {"RB": (n.get("carries") or 0) >= 6.25 * tg, "WR": (n.get("targets") or 0) >= 3.0 * tg,
                 "TE": (n.get("targets") or 0) >= 2.0 * tg, "K": (n.get("fga") or 0) >= 0.8 * tg, "P": (n.get("punts") or 0) >= 2.0 * tg,
                 "DEF": (n.get("games") or 0) >= 0.5 * tg and ((r["values"].get("tackles") or 0) + 3 * (r["values"].get("sacks") or 0)
                                                               + 3 * (r["values"].get("pd") or 0)) >= 2.5 * tg}.get(grp, False)
        ref = r.get("ref")
        if ref is None:
            ref = {"RB": (n.get("carries") or 0) >= max(20, 4 * tg), "WR": (n.get("targets") or 0) >= max(12, 2.5 * tg),
                   "TE": (n.get("targets") or 0) >= max(8, 1.5 * tg), "K": (n.get("fga") or 0) >= max(5, 0.6 * tg),
                   "P": (n.get("punts") or 0) >= max(10, 1.5 * tg), "DEF": bool(q)}.get(grp, False)
        pos = info.get("pos") or grp
        rows[p] = {"name": info["name"], "team": r.get("team"), "pos": pos, "group": grp, "age": an.age_on(info.get("dob"), ctx.season),
                   "games": int(r.get("games") or games_all.get(p) or (n.get("games") or 0)), "qualified": bool(q), "_ref": bool(ref),
                   "values": r["values"], "n": n}
    if comp_src == "model":
        _scale_composite({p: r for p, r in rows.items() if r["group"] == "QB"})
    else:
        _fallback_composite({p: r for p, r in rows.items() if r["group"] == "QB"})
    floors = {"dropbacks": 50, "plays": 60, "att": 40, "carries": 30, "targets": 15, "rec": 10, "catchable": 12, "contested": 4,
              "fga": 5, "punts": 10, "games": 3}
    means = {}
    for grp in GROUPS:
        mem = {p: r for p, r in rows.items() if r["group"] == grp}
        if not mem:
            continue
        ref = [p for p, r in mem.items() if r["_ref"]]
        pos_of = {p: (people.DEF_POS.get(str(r["pos"]).upper(), "DB") if grp == "DEF" else str(r["pos"])) for p, r in mem.items()}
        if grp in ("WR", "TE"):
            continue
        means[grp] = an.finish(mem, GROUP_METRICS[grp], ref, pos_of, floors)
    # receivers: one pool for WR and TE (pct), pct_pos within WR or TE
    rec_mem = {p: r for p, r in rows.items() if r["group"] in ("WR", "TE")}
    if rec_mem:
        ref = [p for p, r in rec_mem.items() if r["_ref"]]
        means["WR/TE"] = an.finish(rec_mem, REC_METRICS, ref, {p: r["group"] for p, r in rec_mem.items()}, floors)
    for r in rows.values():
        r.pop("n", None)
        r.pop("_ref", None)
    groups = {g: [m["key"] for m in GROUP_METRICS[g]] for g in GROUPS}
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "team_games": tg,
            "metrics": [an.public_metric(m) for m in all_metrics()], "groups": groups, "players": rows,
            "reference": {g: {k: an.rnd(v, 4) for k, v in m.items()} for g, m in means.items()},
            "composite_source": comp_src, "model_metrics": used, "model_errors": dict(ctx.model_errors),
            "qualification": {"QB": "14 attempts per team game", "RB": "6.25 carries per team game", "WR": "3 targets per team game",
                              "TE": "2 targets per team game", "K": "0.8 FG attempts per team game", "P": "2 punts per team game",
                              "DEF": "half the team's games and 2.5 tackles-equivalent per team game"},
            "credits": [an.NFLVERSE_CREDIT] + ([an.FTN_CREDIT] if ctx.season >= 2022 else []) + ([an.NGS_CREDIT] if ctx.season >= 2016 else [])}


def _scale_composite(qbs: dict[str, dict]) -> None:
    """Our composite (forecast EPA / dropback) kept as composite_epa and put on the 100 + 10 z scale of the
    qualified pool as composite."""
    ref = [an.fnum(r["values"].get("composite")) for r in qbs.values() if r.get("_ref")]
    ref = [x for x in ref if x is not None]
    if len(ref) < 5:
        return
    mu, sd = float(np.mean(ref)), float(np.std(ref)) or 1.0
    for r in qbs.values():
        x = an.fnum(r["values"].get("composite"))
        r["values"]["composite_epa"] = x
        r["values"]["composite"] = None if x is None else 100 + 10 * (x - mu) / sd


def _fallback_composite(qbs: dict[str, dict]) -> None:
    """QB composite when our qb model is not available: 100 + 10 z of a blend of shrunk EPA / dropback (0.55),
    CPOE (0.2), sack avoidance (0.1) and turnover avoidance (0.15: turnover-worthy rate, else INT rate)."""
    ref = [p for p, r in qbs.items() if r.get("_ref")]
    if len(ref) < 5:
        return

    def comp(key: str, nkey: str, kname: str, sign: float) -> dict[str, float]:
        vals = {p: an.fnum(r["values"].get(key)) for p, r in qbs.items()}
        rv = [vals[p] for p in ref if vals.get(p) is not None]
        if len(rv) < 5:
            return {}
        mu = float(np.mean(rv))
        k = an.DEFAULT_K.get(kname, 200.0)
        sh = {p: an.shrunk(v, an.fnum((qbs[p].get("n") or {}).get(nkey)) or 0, k, mu) for p, v in vals.items() if v is not None}
        rs = [sh[p] for p in ref if p in sh]
        sd = float(np.std(rs)) or 1.0
        return {p: sign * (v - mu) / sd for p, v in sh.items()}
    parts = [(comp("epa_db", "dropbacks", "epa_per_db", 1), 0.55), (comp("cpoe", "att", "cpoe", 1), 0.2),
             (comp("sack_rate", "dropbacks", "sack_rate", -1), 0.1)]
    tw = comp("twp_rate", "att", "twp_rate", -1)
    parts.append((tw if len(tw) >= 5 else comp("int_rate", "att", "int_rate", -1), 0.15))
    raw = {}
    for p in qbs:
        acc, wsum = 0.0, 0.0
        for d, w in parts:
            if p in d:
                acc += w * d[p]
                wsum += w
        if wsum >= 0.6:
            raw[p] = acc / wsum
    rv = [raw[p] for p in ref if p in raw]
    if len(rv) < 5:
        return
    mu, sd = float(np.mean(rv)), float(np.std(rv)) or 1.0
    for p, v in raw.items():
        qbs[p]["values"]["composite"] = 100 + 10 * (v - mu) / sd


def headline(cat: dict | None, keys: list[str], groups: tuple[str, ...] | None = None, n: int = 10) -> dict:
    """Top n per metric among qualified players: {key: [[pid, value], ...]}."""
    out = {}
    if not cat or not cat.get("players"):
        return out
    mets = {m["key"]: m for m in cat.get("metrics") or []}
    for k in keys:
        m = mets.get(k)
        if not m:
            continue
        cand = [(p, r["values"].get(k)) for p, r in cat["players"].items() if r.get("qualified") and r["values"].get(k) is not None
                and (groups is None or r.get("group") in groups) and k in (cat.get("groups") or {}).get(r.get("group"), [k])]
        cand.sort(key=lambda x: x[1], reverse=not m.get("lower"))
        out[k] = [[p, v] for p, v in cand[:n]]
    return out
