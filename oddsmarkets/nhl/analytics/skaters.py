"""
skaters.json: the skater catalogue (~120 metrics) for one season's regular season.

Values come from the season's events and stints (tables.tables: individual counts, on-ice counts by strength, time
on ice by strength), builder B's models (shooting talent, score- and venue-adjusted on-ice rates, RAPM, Rink value)
and NHL EDGE tracking (2021-22 onward, from builder A's raw EDGE files when on disk).

Percentiles: 100 = best (reversed where lower is better), placed against the qualified pool (5v5 TOI at least
`QUAL_5V5_MIN` minutes per 82 team games, prorated), each value shrunk toward the pool mean with the metric's
stabilisation constant (builder B's stabilise.k when fitted, else the fixed k below, in the metric's unit); a metric
needs its sample floor before it gets a percentile; metrics with no denominator (counting stats, RAPM, Rink value)
need FLOORS["gp"] games, so a one-game sample is never ranked. pct_pos compares forwards with forwards and defencemen with
defencemen.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import adapters, edge, tables
from oddsmarkets.nhl.analytics.context import SeasonContext

logger = logging.getLogger(__name__)
M = an.metric
QUAL_5V5_MIN = 250.0
FLOORS = {"toi5": 3000.0, "toi": 6000.0, "shots": 20.0, "att": 20.0, "fo": 50.0, "toipp": 1200.0, "toipk": 1200.0, "gp": 5.0}
MIN = 60.0                         # k for time denominators are in seconds

METRICS = [
    # production (all situations)
    M("gp", "Games", "Production", "int", den="gp", pct=False, desc="Games played (regular season)."),
    M("toi_gp", "TOI / GP", "Production", "toi_min", den="gp", k=10, desc="Minutes per game, all situations."),
    M("g", "Goals", "Production", "int", pct=True, desc="Goals, all situations."),
    M("a", "Assists", "Production", "int", desc="Assists, all situations."),
    M("a1", "Primary assists", "Production", "int", desc="First assists."),
    M("a2", "Secondary assists", "Production", "int", desc="Second assists."),
    M("p", "Points", "Production", "int", desc="Goals plus assists."),
    M("p60", "Points / 60", "Production", "p60", den="toi", k=400 * MIN, stab="p60", desc="Points per 60 minutes, all situations."),
    M("g60", "Goals / 60", "Production", "p60", den="toi", k=600 * MIN, stab="g60", desc="Goals per 60, all situations."),
    M("p1_60", "Primary points / 60", "Production", "p60", den="toi", k=400 * MIN, stab="p1_60", desc="Goals and first assists per 60."),
    M("p60_5v5", "5v5 points / 60", "Production", "p60", den="toi5", k=500 * MIN, stab="p60_5v5", desc="Points per 60 at 5v5."),
    M("g60_5v5", "5v5 goals / 60", "Production", "p60", den="toi5", k=700 * MIN, desc="Goals per 60 at 5v5."),
    M("a1_60_5v5", "5v5 primary assists / 60", "Production", "p60", den="toi5", k=600 * MIN, desc="First assists per 60 at 5v5."),
    M("ipp", "IPP (5v5)", "Production", "pct", den="toi5", k=400 * MIN, stab="ipp", desc="Individual points percentage: the share of "
      "5v5 goals scored with the player on ice on which he had a point."),
    M("pts_pace", "Points pace", "Production", "1", pct=False, desc="Points per game times the season's games."),
    # shooting
    M("sog", "Shots on goal", "Shooting", "int", desc="Shots on goal (goals included)."),
    M("iff", "Unblocked attempts", "Shooting", "int", desc="Individual Fenwick: goals, shots on goal and misses."),
    M("icf", "Shot attempts", "Shooting", "int", desc="Individual Corsi: every attempt, blocked ones included."),
    M("ixg", "ixG", "Shooting", "goals", desc="Individual expected goals, all situations (sum of the xG of the player's unblocked attempts)."),
    M("ixg60", "ixG / 60 (5v5)", "Shooting", "p60", den="toi5", k=250 * MIN, stab="ixg60", desc="Individual xG per 60 at 5v5."),
    M("ixg60_all", "ixG / 60", "Shooting", "p60", den="toi", k=250 * MIN, desc="Individual xG per 60, all situations."),
    M("icf60", "Attempts / 60 (5v5)", "Shooting", "p60", den="toi5", k=150 * MIN, stab="icf60", desc="Individual shot attempts per 60 at 5v5."),
    M("iff60", "Unblocked / 60 (5v5)", "Shooting", "p60", den="toi5", k=150 * MIN, desc="Individual unblocked attempts per 60 at 5v5."),
    M("sog60", "Shots / 60 (5v5)", "Shooting", "p60", den="toi5", k=150 * MIN, desc="Shots on goal per 60 at 5v5."),
    M("sh_pct", "Shooting %", "Shooting", "pct", den="shots", k=375, stab="sh_pct", desc="Goals per shot on goal."),
    M("fsh_pct", "Fenwick shooting %", "Shooting", "pct", den="att", k=500, desc="Goals per unblocked attempt."),
    M("xfsh_pct", "Expected Fenwick sh%", "Shooting", "pct", den="att", k=150, desc="ixG per unblocked attempt: shot quality."),
    M("gax", "Goals above xG", "Shooting", "goals", desc="Goals minus ixG, all situations (unshrunk)."),
    M("shooting_talent", "Shooting talent", "Shooting", "goals", desc="Shrunk finishing: goals above xG on a manned net "
      "regressed toward the league by the stabilisation constant of finishing, gax x attempts / (attempts + k)."),
    M("shot_dist", "Avg shot distance", "Shooting", "ft", lower=True, den="att", k=60, desc="Mean distance (ft) of unblocked attempts."),
    M("hd_att60", "High-danger attempts / 60", "Shooting", "p60", den="toi", k=250 * MIN, desc="Unblocked attempts with xG of 0.20 or more, per 60."),
    M("hd_sh_pct", "High-danger finishing", "Shooting", "pct", den="att", k=120, desc="Goals per high-danger unblocked attempt."),
    M("reb60", "Rebound attempts / 60", "Shooting", "p60", den="toi", k=400 * MIN, desc="Attempts within 3 s of a team-mate's or own attempt."),
    M("rush60", "Rush attempts / 60", "Shooting", "p60", den="toi", k=400 * MIN, desc="Attempts within 4 s of a neutral- or defensive-zone event."),
    M("wrist_share", "Wrist / snap share", "Shooting", "pct", pct=False, desc="Share of unblocked attempts that were wrist or snap shots."),
    M("slap_share", "Slap share", "Shooting", "pct", pct=False, desc="Share of unblocked attempts that were slap shots."),
    M("tip_share", "Tip / deflection share", "Shooting", "pct", pct=False, desc="Share of unblocked attempts that were tips or deflections."),
    M("miss_rate", "Miss rate", "Shooting", "pct", lower=True, den="att", k=200, desc="Missed shots per unblocked attempt."),
    M("blocked_rate", "Blocked rate", "Shooting", "pct", lower=True, den="att", k=200, desc="Attempts blocked per attempt."),
    # 5v5 on ice
    M("toi5", "5v5 TOI", "On ice (5v5)", "toi_min", pct=False, desc="Minutes at 5v5."),
    M("toi5_gp", "5v5 TOI / GP", "On ice (5v5)", "toi_min", den="gp", k=10, desc="5v5 minutes per game."),
    M("cf60", "CF / 60", "On ice (5v5)", "p60", den="toi5", k=400 * MIN, stab="cf60", desc="On-ice shot attempts for per 60 at 5v5."),
    M("ca60", "CA / 60", "On ice (5v5)", "p60", lower=True, den="toi5", k=400 * MIN, stab="ca60", desc="On-ice shot attempts against per 60."),
    M("cf_pct", "CF%", "On ice (5v5)", "pct", den="toi5", k=400 * MIN, stab="cf_pct", desc="On-ice share of shot attempts at 5v5."),
    M("ff_pct", "FF%", "On ice (5v5)", "pct", den="toi5", k=450 * MIN, desc="On-ice share of unblocked attempts at 5v5."),
    M("sf60", "SF / 60", "On ice (5v5)", "p60", den="toi5", k=450 * MIN, desc="On-ice shots on goal for per 60."),
    M("sa60", "SA / 60", "On ice (5v5)", "p60", lower=True, den="toi5", k=450 * MIN, desc="On-ice shots on goal against per 60."),
    M("sf_pct", "SF%", "On ice (5v5)", "pct", den="toi5", k=450 * MIN, desc="On-ice share of shots on goal."),
    M("gf60", "GF / 60", "On ice (5v5)", "p60", den="toi5", k=1500 * MIN, desc="On-ice goals for per 60."),
    M("ga60", "GA / 60", "On ice (5v5)", "p60", lower=True, den="toi5", k=1500 * MIN, desc="On-ice goals against per 60."),
    M("gf_pct", "GF%", "On ice (5v5)", "pct", den="toi5", k=1500 * MIN, stab="gf_pct", desc="On-ice share of goals."),
    M("xgf60", "xGF / 60", "On ice (5v5)", "p60", den="toi5", k=500 * MIN, stab="xgf60", desc="On-ice expected goals for per 60."),
    M("xga60", "xGA / 60", "On ice (5v5)", "p60", lower=True, den="toi5", k=500 * MIN, stab="xga60", desc="On-ice expected goals against per 60."),
    M("xgf_pct", "xGF%", "On ice (5v5)", "pct", den="toi5", k=500 * MIN, stab="xgf_pct", desc="On-ice share of expected goals."),
    M("hdf60", "HDCF / 60", "On ice (5v5)", "p60", den="toi5", k=500 * MIN, desc="On-ice high-danger (xG 0.20+) attempts for per 60."),
    M("hda60", "HDCA / 60", "On ice (5v5)", "p60", lower=True, den="toi5", k=500 * MIN, desc="On-ice high-danger attempts against per 60."),
    M("on_sh_pct", "On-ice sh%", "On ice (5v5)", "pct", den="toi5", k=2000 * MIN, desc="Team shooting % with the player on ice."),
    M("on_sv_pct", "On-ice sv%", "On ice (5v5)", "pct", den="toi5", k=2000 * MIN, desc="Team save % with the player on ice."),
    M("pdo", "PDO", "On ice (5v5)", "3", pct=False, desc="On-ice sh% + sv% (luck indicator; 1.000 = average)."),
    M("gax_onice", "On-ice G - xG", "On ice (5v5)", "goals", desc="On-ice goal differential minus expected goal differential."),
    # relative
    M("cf_pct_rel", "CF% rel", "Relative (5v5)", "pct", den="toi5", k=500 * MIN, desc="CF% on ice minus the team's CF% without him "
      "(in his games)."),
    M("xgf_pct_rel", "xGF% rel", "Relative (5v5)", "pct", den="toi5", k=600 * MIN, stab="xgf_pct_rel", desc="xGF% on minus off ice."),
    M("gf_pct_rel", "GF% rel", "Relative (5v5)", "pct", den="toi5", k=1800 * MIN, desc="GF% on minus off ice."),
    M("xgf60_rel", "xGF/60 rel", "Relative (5v5)", "p60", den="toi5", k=600 * MIN, desc="xGF/60 on minus off ice."),
    M("xga60_rel", "xGA/60 rel", "Relative (5v5)", "p60", lower=True, den="toi5", k=600 * MIN, desc="xGA/60 on minus off ice."),
    M("cf60_rel", "CF/60 rel", "Relative (5v5)", "p60", den="toi5", k=500 * MIN, desc="CF/60 on minus off ice."),
    M("ca60_rel", "CA/60 rel", "Relative (5v5)", "p60", lower=True, den="toi5", k=500 * MIN, desc="CA/60 on minus off ice."),
    # adjusted (builder B)
    M("adj_xgf60", "Adj. xGF / 60", "Adjusted (5v5)", "p60", den="toi5", k=500 * MIN, desc="Score- and venue-adjusted on-ice xGF/60."),
    M("adj_xga60", "Adj. xGA / 60", "Adjusted (5v5)", "p60", lower=True, den="toi5", k=500 * MIN, desc="Score- and venue-adjusted on-ice xGA/60."),
    M("adj_xgf_pct", "Adj. xGF%", "Adjusted (5v5)", "pct", den="toi5", k=500 * MIN, desc="Score- and venue-adjusted xGF%."),
    M("adj_cf60", "Adj. CF / 60", "Adjusted (5v5)", "p60", den="toi5", k=400 * MIN, desc="Score- and venue-adjusted CF/60."),
    M("adj_ca60", "Adj. CA / 60", "Adjusted (5v5)", "p60", lower=True, den="toi5", k=400 * MIN, desc="Score- and venue-adjusted CA/60."),
    # RAPM (builder B)
    M("rapm_off", "RAPM offence", "RAPM", "2", desc="Regularised adjusted plus-minus: the player's isolated effect on his team's 5v5 "
      "xG for per 60 (teammates, opponents, zone starts and score controlled; ridge with multi-season priors)."),
    M("rapm_def", "RAPM defence", "RAPM", "2", desc="Isolated effect on xG against per 60, signed so that higher is better (fewer "
      "chances allowed)."),
    M("rapm_net", "RAPM net", "RAPM", "2", desc="Offence plus defence: isolated xG differential per 60."),
    M("rapm_off_se", "RAPM offence SE", "RAPM", "2", pct=False, desc="Posterior standard error of RAPM offence."),
    M("rapm_def_se", "RAPM defence SE", "RAPM", "2", pct=False, desc="Posterior standard error of RAPM defence."),
    M("rapm_net_se", "RAPM net SE", "RAPM", "2", pct=False, desc="Posterior standard error of RAPM net (with the offence-defence covariance)."),
    M("rapm_cf", "RAPM CF", "RAPM", "2", desc="Isolated effect on shot attempts for per 60."),
    M("rapm_ca", "RAPM CA", "RAPM", "2", desc="Isolated effect on shot attempts against per 60 (higher is better)."),
    M("rapm_pp", "RAPM power play", "RAPM", "2", desc="Isolated effect on PP xG for per 60."),
    M("rapm_pk", "RAPM penalty kill", "RAPM", "2", desc="Isolated effect on PK xG against per 60 (higher is better)."),
    # deployment
    M("ozs_pct", "OZ start %", "Deployment", "pct", pct=False, desc="Offensive-zone share of the 5v5 faceoffs (O + D) taken with the player on ice."),
    M("dzs_share", "DZ start share", "Deployment", "pct", pct=False, desc="Defensive-zone share of all 5v5 on-ice faceoffs."),
    M("ozs", "OZ faceoffs on ice", "Deployment", "int", pct=False, desc="5v5 offensive-zone faceoffs with the player on ice."),
    M("dzs", "DZ faceoffs on ice", "Deployment", "int", pct=False, desc="5v5 defensive-zone faceoffs with the player on ice."),
    M("qoc_toi", "QoC (TOI)", "Deployment", "toi_min", pct=False, desc="TOI-weighted mean 5v5 TOI per game of the opponents faced."),
    M("qot_toi", "QoT (TOI)", "Deployment", "toi_min", pct=False, desc="TOI-weighted mean 5v5 TOI per game of the team-mates on ice."),
    M("qoc_xgf", "QoC (xGF%)", "Deployment", "pct", pct=False, desc="TOI-weighted mean xGF% of the opponents faced."),
    M("qot_xgf", "QoT (xGF%)", "Deployment", "pct", pct=False, desc="TOI-weighted mean xGF% of the team-mates on ice."),
    M("toi_share", "5v5 TOI share", "Deployment", "pct", pct=False, desc="Share of the team's 5v5 time in his games."),
    M("shift_len", "Avg shift (s)", "Deployment", "sec", pct=False, desc="Mean shift length in seconds (stint segments joined)."),
    M("shifts_gp", "Shifts / GP", "Deployment", "1", pct=False, desc="On-ice segments per game."),
    # physical and possession
    M("hits60", "Hits / 60", "Physical", "p60", den="toi", k=150 * MIN, stab="hits60", desc="Hits delivered per 60."),
    M("hits_taken60", "Hits taken / 60", "Physical", "p60", den="toi", k=150 * MIN, desc="Hits received per 60."),
    M("blocks60", "Blocks / 60", "Physical", "p60", den="toi", k=200 * MIN, stab="blocks60", desc="Shots blocked per 60."),
    M("give60", "Giveaways / 60", "Physical", "p60", lower=True, den="toi", k=300 * MIN, desc="Giveaways per 60 (scorer-recorded)."),
    M("take60", "Takeaways / 60", "Physical", "p60", den="toi", k=300 * MIN, desc="Takeaways per 60 (scorer-recorded)."),
    M("hits", "Hits", "Physical", "int", desc="Hits delivered."),
    M("blocks", "Blocks", "Physical", "int", desc="Shots blocked."),
    # faceoffs
    M("fo_taken", "Faceoffs taken", "Faceoffs", "int", pct=False, desc="Faceoffs taken."),
    M("fo_pct", "Faceoff %", "Faceoffs", "pct", den="fo", k=140, stab="fo_pct", desc="Faceoffs won per faceoff taken."),
    M("fo_pct_oz", "OZ faceoff %", "Faceoffs", "pct", den="fo", k=200, desc="Offensive-zone faceoff win share."),
    M("fo_pct_dz", "DZ faceoff %", "Faceoffs", "pct", den="fo", k=200, desc="Defensive-zone faceoff win share."),
    M("fo_pct_nz", "NZ faceoff %", "Faceoffs", "pct", den="fo", k=200, desc="Neutral-zone faceoff win share."),
    M("fo_net", "Faceoff net", "Faceoffs", "int", pct=False, desc="Faceoffs won minus lost."),
    # penalties
    M("pen_taken60", "Penalties taken / 60", "Penalties", "p60", lower=True, den="toi", k=600 * MIN, stab="pen_taken60",
      desc="Minor penalties taken per 60."),
    M("pen_drawn60", "Penalties drawn / 60", "Penalties", "p60", den="toi", k=600 * MIN, stab="pen_drawn60", desc="Minor penalties drawn per 60."),
    M("pen_diff60", "Penalty differential / 60", "Penalties", "p60", den="toi", k=600 * MIN, desc="Drawn minus taken per 60."),
    M("pim", "PIM", "Penalties", "int", pct=False, desc="Penalty minutes."),
    M("pen_net", "Penalty net", "Penalties", "int", desc="Minor penalties drawn minus taken."),
    # special teams
    M("toi_pp_gp", "PP TOI / GP", "Special teams", "toi_min", pct=False, desc="Power-play minutes per game."),
    M("toi_sh_gp", "PK TOI / GP", "Special teams", "toi_min", pct=False, desc="Penalty-kill minutes per game."),
    M("pp_p", "PP points", "Special teams", "int", desc="Power-play points."),
    M("pp_p60", "PP points / 60", "Special teams", "p60", den="toipp", k=300 * MIN, stab="pp_p60", desc="Power-play points per 60."),
    M("pp_ixg60", "PP ixG / 60", "Special teams", "p60", den="toipp", k=200 * MIN, desc="Power-play individual xG per 60."),
    M("pp_xgf60", "PP xGF / 60", "Special teams", "p60", den="toipp", k=200 * MIN, desc="On-ice power-play xG for per 60."),
    M("pp_cf60", "PP CF / 60", "Special teams", "p60", den="toipp", k=150 * MIN, desc="On-ice power-play attempts for per 60."),
    M("pk_xga60", "PK xGA / 60", "Special teams", "p60", lower=True, den="toipk", k=250 * MIN, desc="On-ice penalty-kill xG against per 60."),
    M("pk_ca60", "PK CA / 60", "Special teams", "p60", lower=True, den="toipk", k=200 * MIN, desc="On-ice penalty-kill attempts against per 60."),
    M("sh_p", "SH points", "Special teams", "int", pct=False, desc="Short-handed points."),
    # EDGE tracking
    M("edge_max_speed", "Top speed", "EDGE tracking", "mph", stab="edge_max_speed", k=None, desc="Fastest skating burst (mph), NHL EDGE (2021-22 onward)."),
    M("edge_bursts_20", "20+ mph bursts", "EDGE tracking", "int", desc="Skating bursts of 20 mph or more."),
    M("edge_shot_speed", "Hardest shot", "EDGE tracking", "mph", desc="Hardest shot (mph)."),
    M("edge_distance60", "Distance / 60", "EDGE tracking", "2", desc="Miles skated per 60 minutes."),
    M("edge_oz_time", "OZ time %", "EDGE tracking", "pct", desc="Share of 5v5 time in the offensive zone (EDGE)."),
    # value (builder B)
    M("gar", "Rink value (GAR)", "Value", "1", desc="Goals above replacement: RAPM offence and defence at 5v5, power play, penalty kill, "
      "shooting talent, penalties and faceoffs, against a replacement-level skater."),
    M("war", "Rink value (WAR)", "Value", "2", desc="GAR in wins (goals per win from the season's scoring)."),
    M("gar_60", "GAR / 60", "Value", "2", den="toi", k=600 * MIN, desc="Goals above replacement per 60."),
    M("gar_ev_off", "GAR EV offence", "Value", "1", desc="Even-strength offence component."),
    M("gar_ev_def", "GAR EV defence", "Value", "1", desc="Even-strength defence component."),
    M("gar_pp", "GAR power play", "Value", "1", desc="Power-play component."),
    M("gar_pk", "GAR penalty kill", "Value", "1", desc="Penalty-kill component."),
    M("gar_shooting", "GAR shooting", "Value", "1", desc="Finishing component."),
    M("gar_pen", "GAR penalties", "Value", "1", desc="Penalty component (drawn minus taken)."),
    # projections
    M("proj_pts", "Projected points", "Projection", "1", pct=False, desc="Rest-of-season projection: points so far plus remaining games "
      "times a points rate regressed toward the position average by the rate's stabilisation constant."),
    M("proj_g", "Projected goals", "Projection", "1", pct=False, desc="Goals so far plus remaining games times a regressed goal rate."),
    M("proj_xgf_pct", "Projected xGF%", "Projection", "pct", pct=False, desc="5v5 xGF% regressed toward 50 % by its stabilisation constant."),
]
KEYS = [m["key"] for m in METRICS]
SIGN_FLIP: set[str] = set()       # the RAPM defence coefficients are already signed so that higher is better


def _pct(a, b):
    a, b = an.fnum(a), an.fnum(b)
    if a is None or b is None or a + b <= 0:
        return None
    return a / (a + b)


def player_values(r: dict, team_tot: dict | None) -> dict:
    """The event / stint metrics of one player's season row (a dict of the summed tables.season_agg columns)."""
    f = lambda k: an.fnum(r.get(k)) or 0.0  # noqa: E731
    toi, toi5, toipp, toish = f("toi"), f("toi_5v5"), f("toi_PP"), f("toi_SH")
    gp = f("gp")
    g, a1, a2 = f("g"), f("a1"), f("a2")
    a = a1 + a2
    p = g + a
    v: dict = {"gp": gp, "g": g, "a": a, "a1": a1, "a2": a2, "p": p}
    v["toi_gp"] = toi / 60.0 / gp if gp and toi else None
    v["p60"], v["g60"] = an.per60(p, toi), an.per60(g, toi)
    v["p1_60"] = an.per60(g + a1, toi)
    g5, a15, a25 = f("g_5v5"), f("a1_5v5"), f("a2_5v5")
    v["p60_5v5"], v["g60_5v5"], v["a1_60_5v5"] = an.per60(g5 + a15 + a25, toi5), an.per60(g5, toi5), an.per60(a15, toi5)
    gf5 = f("gf_5v5")
    v["ipp"] = (g5 + a15 + a25) / gf5 if gf5 else None
    v["sog"], v["iff"], v["icf"], v["ixg"] = f("sog"), f("iff"), f("icf"), f("ixg")
    v["ixg60"] = an.per60(f("ixg_5v5"), toi5)
    v["ixg60_all"] = an.per60(f("ixg"), toi)
    v["icf60"], v["iff60"], v["sog60"] = an.per60(f("icf_5v5"), toi5), an.per60(f("iff_5v5"), toi5), an.per60(f("sog_5v5"), toi5)
    v["sh_pct"] = an.div(g, f("sog"))
    v["fsh_pct"] = an.div(g, f("iff"))
    v["xfsh_pct"] = an.div(f("ixg"), f("iff"))
    v["gax"] = g - f("ixg") if f("iff") else None
    v["shot_dist"] = an.div(f("sdist"), f("ndist"))
    v["hd_att60"] = an.per60(f("hd_att"), toi)
    v["hd_sh_pct"] = an.div(f("hd_g"), f("hd_att"))
    v["reb60"], v["rush60"] = an.per60(f("reb_att"), toi), an.per60(f("rush_att"), toi)
    v["wrist_share"], v["slap_share"], v["tip_share"] = an.div(f("wrist"), f("iff")), an.div(f("slap"), f("iff")), an.div(f("tip"), f("iff"))
    v["miss_rate"] = an.div(f("miss"), f("iff"))
    v["blocked_rate"] = an.div(f("blocked_by"), f("icf"))
    # on ice 5v5
    v["toi5"] = toi5 / 60.0 if toi5 else None
    v["toi5_gp"] = toi5 / 60.0 / gp if gp and toi5 else None
    cf, ca, ff, fa, sf, sa = f("cf_5v5"), f("ca_5v5"), f("ff_5v5"), f("fa_5v5"), f("sf_5v5"), f("sa_5v5")
    gf, ga, xgf, xga = f("gf_5v5"), f("ga_5v5"), f("xgf_5v5"), f("xga_5v5")
    if toi5:
        v.update(cf60=an.per60(cf, toi5), ca60=an.per60(ca, toi5), sf60=an.per60(sf, toi5), sa60=an.per60(sa, toi5),
                 gf60=an.per60(gf, toi5), ga60=an.per60(ga, toi5), xgf60=an.per60(xgf, toi5), xga60=an.per60(xga, toi5),
                 hdf60=an.per60(f("hdf_5v5"), toi5), hda60=an.per60(f("hda_5v5"), toi5))
    v["cf_pct"], v["ff_pct"], v["sf_pct"], v["gf_pct"], v["xgf_pct"] = _pct(cf, ca), _pct(ff, fa), _pct(sf, sa), _pct(gf, ga), _pct(xgf, xga)
    v["on_sh_pct"] = an.div(gf, sf)
    v["on_sv_pct"] = 1 - ga / sa if sa else None
    v["pdo"] = (v["on_sh_pct"] + v["on_sv_pct"]) if v["on_sh_pct"] is not None and v["on_sv_pct"] is not None else None
    v["gax_onice"] = (gf - ga) - (xgf - xga) if toi5 else None
    # relative: off-ice = team totals in his games minus on-ice
    if team_tot and toi5:
        off_t = team_tot.get("toi_5v5", 0.0) - toi5
        if off_t > 600:
            o = {k: team_tot.get(k, 0.0) - f(k) for k in ("cf_5v5", "ca_5v5", "gf_5v5", "ga_5v5", "xgf_5v5", "xga_5v5")}
            ocf, oxg, ogf = _pct(o["cf_5v5"], o["ca_5v5"]), _pct(o["xgf_5v5"], o["xga_5v5"]), _pct(o["gf_5v5"], o["ga_5v5"])
            v["cf_pct_rel"] = v["cf_pct"] - ocf if v["cf_pct"] is not None and ocf is not None else None
            v["xgf_pct_rel"] = v["xgf_pct"] - oxg if v["xgf_pct"] is not None and oxg is not None else None
            v["gf_pct_rel"] = v["gf_pct"] - ogf if v["gf_pct"] is not None and ogf is not None else None
            v["xgf60_rel"] = v["xgf60"] - an.per60(o["xgf_5v5"], off_t)
            v["xga60_rel"] = v["xga60"] - an.per60(o["xga_5v5"], off_t)
            v["cf60_rel"] = v["cf60"] - an.per60(o["cf_5v5"], off_t)
            v["ca60_rel"] = v["ca60"] - an.per60(o["ca_5v5"], off_t)
        v["toi_share"] = toi5 / team_tot.get("toi_5v5") if team_tot.get("toi_5v5") else None
    ozs, dzs, nzs = f("ozs"), f("dzs"), f("nzs")
    v["ozs"], v["dzs"] = ozs, dzs
    v["ozs_pct"] = _pct(ozs, dzs)
    v["dzs_share"] = an.div(dzs, ozs + dzs + nzs)
    v["shifts_gp"] = an.div(f("shifts"), gp)
    v["shift_len"] = an.div(toi, f("shifts"))
    # physical
    v["hits"], v["blocks"] = f("hits"), f("blocks")
    v["hits60"], v["hits_taken60"], v["blocks60"] = an.per60(f("hits"), toi), an.per60(f("hits_taken"), toi), an.per60(f("blocks"), toi)
    v["give60"], v["take60"] = an.per60(f("give"), toi), an.per60(f("take"), toi)
    # faceoffs
    fow, fol = f("fow"), f("fol")
    v["fo_taken"] = fow + fol
    v["fo_pct"] = _pct(fow, fol) if fow + fol else None
    v["fo_pct_oz"] = _pct(f("fow_oz"), f("fol_oz")) if f("fow_oz") + f("fol_oz") >= 10 else None
    v["fo_pct_dz"] = _pct(f("fow_dz"), f("fol_dz")) if f("fow_dz") + f("fol_dz") >= 10 else None
    v["fo_pct_nz"] = _pct(f("fow_nz"), f("fol_nz")) if f("fow_nz") + f("fol_nz") >= 10 else None
    v["fo_net"] = fow - fol if fow + fol else None
    # penalties
    v["pen_taken60"], v["pen_drawn60"] = an.per60(f("pen_taken"), toi), an.per60(f("pen_drawn"), toi)
    v["pen_diff60"] = an.per60(f("pen_drawn") - f("pen_taken"), toi)
    v["pim"], v["pen_net"] = f("pim"), f("pen_drawn") - f("pen_taken")
    # special teams
    v["toi_pp_gp"] = toipp / 60.0 / gp if gp else None
    v["toi_sh_gp"] = toish / 60.0 / gp if gp else None
    ppp = f("g_PP") + f("a1_PP") + f("a2_PP")
    v["pp_p"] = ppp
    v["pp_p60"] = an.per60(ppp, toipp)
    v["pp_ixg60"] = an.per60(f("ixg_PP"), toipp)
    v["pp_xgf60"] = an.per60(f("xgf_PP"), toipp)
    v["pp_cf60"] = an.per60(f("cf_PP"), toipp)
    v["pk_xga60"] = an.per60(f("xga_SH"), toish)
    v["pk_ca60"] = an.per60(f("ca_SH"), toish)
    v["sh_p"] = f("g_SH") + f("a1_SH") + f("a2_SH")
    return v


def build(ctx: SeasonContext) -> dict | None:
    T = tables.tables(ctx)
    pg = T["pg"]
    if not len(pg):
        return None
    agg = tables.season_agg(pg, "REG")
    if not len(agg):
        return None
    tg = T["tg"]
    # team totals in each player's games (for relative and TOI share)
    tg_reg = tg[tg["gt"] == "REG"].set_index(["game_id", "team"]) if len(tg) else None
    P = pg[pg["gt"] == "REG"]
    team_tot: dict[float, dict] = {}
    if tg_reg is not None and len(P):
        cols = {"toi_5v5": "toi_5v5", "cf_5v5": "cf_5v5", "ca_5v5": "ca_5v5", "gf_5v5": "gf_5v5", "ga_5v5": "ga_5v5",
                "xgf_5v5": "xgf_5v5", "xga_5v5": "xga_5v5"}
        have = [c for c in cols if c in tg_reg.columns]
        J = P[["game_id", "team", "pid"]].join(tg_reg[have], on=["game_id", "team"])
        for pid, row in J.groupby("pid")[have].sum().iterrows():
            team_tot[pid] = row.to_dict()
    models = adapters.player_tables(ctx)
    ed = edge.skaters(ctx)
    tg_n = ctx.team_games() or 1
    n_season = ctx.season_games()
    qual_sec = QUAL_5V5_MIN * 60.0 * min(1.0, tg_n / 82.0)
    rows: dict[str, dict] = {}
    pos_of: dict[str, str] = {}
    reference: list[str] = []
    xgf_of: dict[float, float] = {}
    toi_of: dict[float, float] = {}
    for pid, r in agg.iterrows():
        rd = r.to_dict()
        p = an.sid(pid)
        v = player_values(rd, team_tot.get(pid))
        info = ctx.players.get(p) or {}
        grp = an.pos_group(info.get("pos") or T["pos"].get(pid))
        if grp == "G":
            continue
        for k, d in models.items():
            if p in d and k in KEYS:
                v[k] = -d[p] if k in SIGN_FLIP else d[p]
        if "rapm_net" not in models and v.get("rapm_off") is not None and v.get("rapm_def") is not None:
            v["rapm_net"] = v["rapm_off"] + v["rapm_def"]
        if v.get("gar_60") is None and v.get("gar") is not None and rd.get("toi"):
            v["gar_60"] = an.per60(v["gar"], rd["toi"])
        e = ed.get(p) or {}
        for k, x in e.items():
            if k in KEYS:
                v[k] = x
        if e.get("edge_distance") is not None and rd.get("toi"):
            v["edge_distance60"] = an.per60(e["edge_distance"], rd["toi"])
        toi5 = an.fnum(rd.get("toi_5v5")) or 0.0
        gp = an.fnum(rd.get("gp")) or 0.0
        v["pts_pace"] = v["p"] / gp * n_season if gp else None
        if toi5 and gp:
            toi_of[pid] = toi5 / gp / 60.0
            if v.get("xgf_pct") is not None:
                xgf_of[pid] = v["xgf_pct"]
        n = {"toi": rd.get("toi") or 0.0, "toi5": toi5, "toipp": rd.get("toi_PP") or 0.0, "toipk": rd.get("toi_SH") or 0.0,
             "shots": rd.get("sog") or 0.0, "att": rd.get("iff") or 0.0, "fo": (rd.get("fow") or 0.0) + (rd.get("fol") or 0.0), "gp": gp}
        qualified = bool(T["has_toi"] and toi5 >= qual_sec) or bool(not T["has_toi"] and gp >= 0.5 * tg_n)
        rows[p] = {"name": ctx.player_name(p) or p, "team": rd.get("team"), "teams": rd.get("teams"), "pos": info.get("pos") or grp,
                   "group": grp, "age": an.age_on(info.get("dob"), ctx.season), "gp": int(gp), "toi": an.rnd((rd.get("toi") or 0) / 60.0, 1),
                   "qualified": qualified, "values": v, "n": n}
        pos_of[p] = grp
        if qualified:
            reference.append(p)
    # competition (QoC / QoT) on TOI per game and xGF%
    st = T["st"]
    if len(st):
        st_reg = st[st["game_id"].astype(str).str[4:6] == "02"]
        from oddsmarkets.nhl.analytics import box
        for mk, src in (("toi", toi_of), ("xgf", xgf_of)):
            comp = box.competition(st_reg, src)
            for rr in comp.to_dict("records"):
                p = an.sid(rr["pid"])
                if p in rows:
                    rows[p]["values"][f"qot_{mk}"] = rr.get("qot")
                    rows[p]["values"][f"qoc_{mk}"] = rr.get("qoc")
    _projections(ctx, rows, reference, n_season, tg_n)
    an.finish(rows, METRICS, reference, pos_of, FLOORS)
    for r in rows.values():
        r["pct_pos"] = r.pop("pct_pos", {})
    ref_n = len(reference)
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "team_games": tg_n, "kind": "skater",
            "metrics": [an.public_metric(m) for m in METRICS], "players": rows,
            "reference": {"n": ref_n, "min_toi5": round(qual_sec / 60.0, 0), "floors": {k: (v / 60.0 if k.startswith("toi") else v)
                                                                                      for k, v in FLOORS.items()}},
            "xg_source": ctx.xg_source, "coverage": {"events": T["has_events"], "shifts": T["has_toi"], "edge": bool(ed)},
            "model_errors": dict(ctx.model_errors)}


def _projections(ctx, rows: dict, reference: list[str], n_season: int, tg_n: int) -> None:
    """Rest-of-season projections: rates regressed toward the position-group mean of the qualified pool."""
    left = max(0, n_season - tg_n)
    by_grp: dict[str, list] = {}
    for p in reference:
        r = rows[p]
        by_grp.setdefault(r["group"], []).append(r)
    means = {}
    for grp, rs in by_grp.items():
        gp = sum(x["gp"] for x in rs) or 1
        means[grp] = {"p_gp": sum(x["values"]["p"] for x in rs) / gp, "g_gp": sum(x["values"]["g"] for x in rs) / gp}
    for r in rows.values():
        v, gp = r["values"], r["gp"]
        mu = means.get(r["group"]) or {"p_gp": 0.5, "g_gp": 0.2}
        kp, kg = 30.0, 45.0                                    # games at which a per-game rate is half signal
        p_rate = (v["p"] + kp * mu["p_gp"]) / (gp + kp)
        g_rate = (v["g"] + kg * mu["g_gp"]) / (gp + kg)
        share = min(1.0, gp / max(tg_n, 1)) if tg_n else 0.0
        v["proj_pts"] = v["p"] + left * share * p_rate if gp else None
        v["proj_g"] = v["g"] + left * share * g_rate if gp else None
        toi5 = r["n"]["toi5"]
        if v.get("xgf_pct") is not None:
            k = 500 * MIN
            v["proj_xgf_pct"] = (toi5 * v["xgf_pct"] + k * 0.5) / (toi5 + k)
