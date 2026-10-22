"""
Pitchers catalogue (pitchers.json): about 150 metrics per pitcher and season (regular season), plus the
arsenal per pitch type.

Groups: traditional (W/L/SV from the store's decisions; runs are all runs scored while he pitched, so RA9 not
ERA); pitch models (builder B: stuff, location and pitching scores, 100 = league average, 10 = one SD of
pitcher-pitch-type quality); primary fastball shape and VAA; release and extension (consistency); tunneling;
usage by count and batter hand; plate discipline induced; run value and whiffs by family; contact allowed;
expected stats (builder C's xwOBA+ against v Savant's); times through the order and fatigue signals
(builder B); Bullpen WAR (RA9- and xwOBA+-based, builder C); clutch; projections (builder D).

Percentiles as for hitters: reference pool = pitchers with at least 1.25 batters faced per team game (floor
50 BF), "pct_role" against the same role (SP: half or more of his games started, else RP), sample floors per
metric, stabilisation shrinkage. "qualified" is MLB's rule (1 IP per team game).

FIP is on the RA9 scale (the constant makes league FIP equal league RA9, since the pitch data has no earned
runs): FIP = (13 HR + 3 (BB + HBP) - 2 K) / IP + c. xFIP replaces home runs with fly balls x the league HR/FB.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext
from oddsmarkets.baseball.analytics.hitters import _clutch

M = an.metric
FLOORS = {"bf": 50, "bip": 25, "pitches": 200, "swings": 80, "oz": 80, "fb": 100, "br": 60, "os": 50, "ip": 10,
          "tto3": 30, "games": 3, "bf_l": 30, "bf_r": 30}
REF_BF_PER_G = 1.25
QUAL_IP_PER_G = 1.0
FB_TYPES = ("FF", "SI", "FC")

METRICS: list[dict] = [
    # traditional
    M("g", "G", "Traditional", "int", desc="Games pitched."),
    M("gs", "GS", "Traditional", "int", desc="Games started."),
    M("w", "W", "Traditional", "int", desc="Wins (official decisions)."),
    M("l", "L", "Traditional", "int", lower=True, desc="Losses."),
    M("sv", "SV", "Traditional", "int", desc="Saves."),
    M("ip", "IP", "Traditional", "1", desc="Innings pitched (outs / 3; shown as decimal innings)."),
    M("bf", "BF", "Traditional", "int", desc="Batters faced."),
    M("h", "H", "Traditional", "int", lower=True, desc="Hits allowed."),
    M("hr", "HR", "Traditional", "int", lower=True, desc="Home runs allowed."),
    M("bb", "uBB", "Traditional", "int", lower=True, desc="Unintentional walks (MLB's BB includes IBB: add the IBB column)."),
    M("ibb", "IBB", "Traditional", "int", lower=True, desc="Intentional walks."),
    M("hbp", "HBP", "Traditional", "int", lower=True, desc="Hit batters."),
    M("so", "SO", "Traditional", "int", desc="Strikeouts."),
    M("r", "R", "Traditional", "int", lower=True, desc="Runs scored while he pitched (no inherited-runner reassignment)."),
    M("ra9", "RA9", "Traditional", "2", lower=True, den="bf", k=1000, desc="Runs allowed per nine innings."),
    M("whip", "WHIP", "Traditional", "2", lower=True, den="bf", k=600, desc="(Walks + hits) per inning."),
    M("k_pct", "K%", "Traditional", "pct", den="bf", stab="p_k_rate", desc="Strikeouts per batter faced."),
    M("bb_pct", "BB%", "Traditional", "pct", lower=True, den="bf", stab="p_bb_rate", desc="Walks (incl. intentional) per batter faced."),
    M("k_bb_pct", "K-BB%", "Traditional", "pct", den="bf", k=150, desc="K% minus BB%."),
    M("k9", "K/9", "Traditional", "1", den="bf", stab="p_k_rate", desc="Strikeouts per nine innings."),
    M("bb9", "BB/9", "Traditional", "1", lower=True, den="bf", stab="p_bb_rate", desc="Walks per nine innings."),
    M("hr9", "HR/9", "Traditional", "2", lower=True, den="bf", k=1300, desc="Home runs per nine innings."),
    M("avg_against", "AVG against", "Traditional", "3", lower=True, den="bf", k=1000, desc="Batting average allowed."),
    M("obp_against", "OBP against", "Traditional", "3", lower=True, den="bf", k=600, desc="On-base percentage allowed."),
    M("slg_against", "SLG against", "Traditional", "3", lower=True, den="bf", k=600, desc="Slugging allowed."),
    M("woba_against", "wOBA against", "Traditional", "3", lower=True, den="bf", stab="p_woba", desc="wOBA allowed."),
    M("babip_against", "BABIP against", "Traditional", "3", lower=True, den="bip", k=2000, desc="BABIP allowed."),
    M("fip", "FIP", "Traditional", "2", lower=True, den="bf", k=500, desc="Fielding-independent pitching on the RA9 scale."),
    M("xfip", "xFIP", "Traditional", "2", lower=True, den="bf", k=400, desc="FIP with home runs replaced by fly balls x league HR/FB."),
    M("pitches", "Pitches", "Traditional", "int", desc="Pitches thrown."),
    M("p_ip", "Pitches/IP", "Traditional", "1", lower=True, den="bf", k=300, desc="Pitches per inning."),
    M("p_start", "Pitches/start", "Traditional", "1", desc="Mean pitch count per start."),
    # pitch models (builder B)
    M("pitching_plus", "Pitching+", "Pitch models", "plus", den="pitches", k=600, scope="model",
      desc="Expected run value of each pitch from stuff, location, count and sequence together (count-neutral), scaled "
      "100 = league average, 10 = one SD of pitcher-pitch-type means."),
    M("stuff_plus", "Stuff+", "Pitch models", "plus", den="pitches", k=300, scope="model",
      desc="Expected run value from the pitch's physical characteristics alone (velocity, movement, spin, extension, release, "
      "arm angle, VAA, differences from his fastball), per pitch family, scaled like Pitching+."),
    M("location_plus", "Location+", "Pitch models", "plus", den="pitches", k=1000, scope="model",
      desc="Expected run value of the location given count, pitch family and platoon, scaled like Pitching+."),
    M("xrv100", "xRV/100", "Pitch models", "2", den="pitches", k=600, scope="model",
      desc="Pitching model expected runs per 100 pitches relative to the count (negative is good for the pitcher)."),
    M("rv100", "RV/100", "Pitch models", "2", lower=True, den="pitches", k=2000, scope="statcast",
      desc="Actual run value per 100 pitches (Savant delta_run_exp, batting side: lower is better)."),
    M("fb_stuff", "Fastball Stuff+", "Pitch models", "plus", den="fb", k=300, scope="model", desc="Stuff+ of his primary fastball."),
    M("fb_location", "Fastball Location+", "Pitch models", "plus", den="fb", k=1000, scope="model", desc="Location+ of his primary fastball."),
    M("fb_pitching", "Fastball Pitching+", "Pitch models", "plus", den="fb", k=600, scope="model", desc="Pitching+ of his primary fastball."),
    M("best_secondary_stuff", "Best secondary Stuff+", "Pitch models", "plus", den="pitches", k=300, scope="model",
      desc="Highest Stuff+ among his non-fastballs thrown 5 %+ of the time."),
    # fastball shape (builder B physics, primary fastball)
    M("fb_velo", "Fastball velo", "Fastball", "mph", den="fb", stab="p_velo", scope="statcast", desc="Primary fastball velocity."),
    M("fb_velo_max", "Max velo", "Fastball", "mph", scope="statcast", desc="Fastest pitch (95th percentile of his primary fastball)."),
    M("fb_spin", "Fastball spin", "Fastball", "rpm", den="fb", k=60, scope="statcast", desc="Primary fastball spin rate."),
    M("fb_ivb", "Fastball IVB", "Fastball", "in", den="fb", k=60, scope="statcast", desc="Induced vertical break (gravity removed)."),
    M("fb_hb", "Fastball arm-side run", "Fastball", "in", den="fb", k=60, scope="statcast", desc="Horizontal break toward the arm side."),
    M("fb_vaa", "Fastball VAA", "Fastball", "deg", den="fb", k=100, scope="statcast",
      desc="Vertical approach angle at the plate (flatter = closer to 0 = harder to hit up in the zone)."),
    M("fb_spin_eff", "Fastball spin efficiency", "Fastball", "pct", den="fb", k=100, scope="model",
      desc="Share of spin that produces movement (transverse spin over total), from the trajectory fit."),
    M("fb_axis_dev", "Fastball seam-shifted wake", "Fastball", "deg", den="fb", k=100, scope="model",
      desc="Gap between the observed movement direction and the measured spin axis."),
    M("n_types", "Pitch types", "Arsenal", "int", desc="Pitch types thrown 5 %+ of the time."),
    M("fb_usage", "Fastball%", "Arsenal", "pct", den="pitches", k=300, scope="statcast", desc="Fastballs (four-seam, sinker, cutter)."),
    M("br_usage", "Breaking%", "Arsenal", "pct", den="pitches", k=300, scope="statcast", desc="Sliders, sweepers, curveballs."),
    M("os_usage", "Offspeed%", "Arsenal", "pct", den="pitches", k=300, scope="statcast", desc="Changeups, splitters, others."),
    M("velo_gap", "FB-offspeed velo gap", "Arsenal", "mph", scope="statcast", desc="Primary fastball minus his slowest regular pitch."),
    # release (builder B)
    M("rel_height", "Release height", "Release", "ft", scope="statcast", desc="Mean release height."),
    M("rel_side", "Release side", "Release", "ft", scope="statcast", desc="Release side (arm side positive)."),
    M("extension", "Extension", "Release", "ft", den="pitches", k=100, scope="statcast", desc="Release extension toward the plate."),
    M("arm_angle", "Arm angle", "Release", "deg", scope="statcast", desc="Savant arm angle."),
    M("rel_spread", "Release spread", "Release", "in", lower=True, den="pitches", k=300, scope="model",
      desc="SD of the release point (in): lower = more repeatable."),
    M("rel_type_spread", "Release gap between types", "Release", "in", lower=True, scope="model",
      desc="Largest distance between two pitch types' mean release points (tipping risk)."),
    # tunneling (builder B)
    M("tunnel_index", "Tunnel index", "Tunneling", "plus", scope="model",
      desc="Separation of consecutive pitches at the plate relative to their separation at the decision point "
      "(167 ms before the plate), against the league curve; 100 = average, 10 = one SD."),
    M("tunnel_in", "Tunnel score (in)", "Tunneling", "1", scope="model", desc="Plate separation beyond what the decision-point gap predicts."),
    # usage by count / hand
    M("fb_ahead", "Fastball% ahead", "Usage", "pct", scope="statcast", desc="Fastball share when ahead in the count."),
    M("fb_behind", "Fastball% behind", "Usage", "pct", scope="statcast", desc="Fastball share when behind."),
    M("fb_even", "Fastball% even", "Usage", "pct", scope="statcast", desc="Fastball share in even counts."),
    M("br_two", "Breaking% two strikes", "Usage", "pct", scope="statcast", desc="Breaking-ball share with two strikes."),
    M("fb_vl", "Fastball% v LHB", "Usage", "pct", scope="statcast", desc="Fastball share against left-handed batters."),
    M("fb_vr", "Fastball% v RHB", "Usage", "pct", scope="statcast", desc="Fastball share against right-handed batters."),
    M("os_vl", "Offspeed% v LHB", "Usage", "pct", scope="statcast", desc="Offspeed share against left-handed batters."),
    M("br_vr", "Breaking% v RHB", "Usage", "pct", scope="statcast", desc="Breaking share against right-handed batters."),
    # discipline induced
    M("zone_pct", "Zone%", "Discipline", "pct", den="pitches", stab="p_zone_rate", scope="statcast", desc="Pitches in the zone."),
    M("chase_pct", "Chase%", "Discipline", "pct", den="oz", k=300, scope="statcast", desc="Swings induced outside the zone."),
    M("z_swing_pct", "Z-Swing%", "Discipline", "pct", lower=True, den="pitches", k=400, scope="statcast", desc="Swings at his pitches in the zone."),
    M("whiff_pct", "Whiff%", "Discipline", "pct", den="swings", stab="p_whiff_rate", scope="statcast", desc="Whiffs per swing."),
    M("swstr_pct", "SwStr%", "Discipline", "pct", den="pitches", k=300, scope="statcast", desc="Swinging strikes per pitch."),
    M("csw_pct", "CSW%", "Discipline", "pct", den="pitches", stab="p_csw", scope="statcast", desc="Called strikes plus whiffs per pitch."),
    M("cstr_pct", "Called strike%", "Discipline", "pct", den="pitches", k=400, scope="statcast", desc="Called strikes per pitch."),
    M("contact_pct", "Contact%", "Discipline", "pct", lower=True, den="swings", k=200, scope="statcast", desc="Contact per swing."),
    M("z_contact_pct", "Z-Contact%", "Discipline", "pct", lower=True, den="swings", k=250, scope="statcast", desc="Contact per swing in the zone."),
    M("fp_strike_pct", "First-pitch strike%", "Discipline", "pct", den="bf", k=300, scope="statcast", desc="First pitches that were strikes."),
    M("edge_pct", "Edge%", "Discipline", "pct", den="pitches", k=400, scope="statcast", desc="Pitches in the shadow attack zone."),
    M("heart_pct", "Heart%", "Discipline", "pct", lower=True, den="pitches", k=400, scope="statcast", desc="Pitches in the heart of the zone."),
    M("waste_pct", "Waste%", "Discipline", "pct", lower=True, den="pitches", k=400, scope="statcast", desc="Pitches in the waste attack zone."),
    M("o_contact_pct", "O-Contact% allowed", "Discipline", "pct", lower=True, den="swings", k=250, scope="statcast",
      desc="Contact per swing outside the zone."),
    M("s2_whiff_pct", "Two-strike whiff%", "Discipline", "pct", den="swings", k=200, scope="statcast", desc="Whiffs per swing with two strikes."),
    M("chase_band_pct", "Chase-band%", "Discipline", "pct", den="pitches", k=400, scope="statcast",
      desc="Pitches in the chase attack zone (133-200 % of the zone)."),
    M("p_bf", "Pitches/BF", "Discipline", "2", lower=True, den="bf", k=200, scope="statcast", desc="Pitches per batter faced."),
    # platoon
    M("woba_vl", "wOBA v LHB", "Platoon", "3", lower=True, den="bf_l", stab="p_woba", desc="wOBA allowed to left-handed batters."),
    M("woba_vr", "wOBA v RHB", "Platoon", "3", lower=True, den="bf_r", stab="p_woba", desc="wOBA allowed to right-handed batters."),
    M("xwoba_vl", "xwOBA v LHB", "Platoon", "3", lower=True, den="bf_l", k=400, scope="statcast", desc="Savant xwOBA allowed to LHB."),
    M("xwoba_vr", "xwOBA v RHB", "Platoon", "3", lower=True, den="bf_r", k=400, scope="statcast", desc="Savant xwOBA allowed to RHB."),
    M("k_pct_vl", "K% v LHB", "Platoon", "pct", den="bf_l", stab="p_k_rate", desc="Strikeouts per LHB faced."),
    M("k_pct_vr", "K% v RHB", "Platoon", "pct", den="bf_r", stab="p_k_rate", desc="Strikeouts per RHB faced."),
    M("bf_vl_share", "BF share v LHB", "Platoon", "pct", desc="Share of batters faced who hit left-handed."),
    # by family
    *[m for f, nm in (("fb", "fastballs"), ("br", "breaking balls"), ("os", "offspeed")) for m in (
        M(f"{f}_rv100", f"RV/100 {nm}", "By pitch", "2", lower=True, den=f, k=600, scope="statcast",
          desc=f"Run value per 100 {nm} (batting side: lower is better)."),
        M(f"{f}_whiff_pct", f"Whiff% {nm}", "By pitch", "pct", den=f, k=150, scope="statcast", desc=f"Whiffs per swing on {nm}."),
        M(f"{f}_csw_pct", f"CSW% {nm}", "By pitch", "pct", den=f, k=200, scope="statcast", desc=f"Called strikes plus whiffs per {nm}."),
        M(f"{f}_xwoba", f"xwOBA {nm}", "By pitch", "3", lower=True, den=f, k=300, scope="statcast",
          desc=f"Savant xwOBA on PAs ending with {nm}."))],
    # contact allowed
    M("ev", "Exit velocity", "Contact allowed", "mph", lower=True, den="bip", stab="p_ev", scope="statcast", desc="Mean exit velocity allowed."),
    M("ev90", "EV90 allowed", "Contact allowed", "mph", lower=True, den="bip", k=80, scope="statcast", desc="90th percentile exit velocity allowed."),
    M("la", "Launch angle", "Contact allowed", "deg", den="bip", k=80, scope="statcast", desc="Mean launch angle allowed."),
    M("hard_pct", "Hard-hit%", "Contact allowed", "pct", lower=True, den="bip", k=300, scope="statcast", desc="Balls in play at 95+ mph."),
    M("barrel_pct", "Barrel%", "Contact allowed", "pct", lower=True, den="bip", k=400, scope="statcast", desc="Barrels per ball in play."),
    M("sweet_pct", "Sweet-spot%", "Contact allowed", "pct", lower=True, den="bip", k=300, scope="statcast", desc="Launch angle 8-32."),
    M("gb_pct", "GB%", "Contact allowed", "pct", den="bip", stab="p_gb_rate", scope="statcast", desc="Ground balls per ball in play."),
    M("ld_pct", "LD%", "Contact allowed", "pct", lower=True, den="bip", k=800, scope="statcast", desc="Line drives."),
    M("fb_pct", "FB%", "Contact allowed", "pct", den="bip", k=150, scope="statcast", desc="Fly balls."),
    M("pu_pct", "PU%", "Contact allowed", "pct", den="bip", k=250, scope="statcast", desc="Pop-ups."),
    M("pull_air_pct", "Pull-air% allowed", "Contact allowed", "pct", lower=True, den="bip", k=300, scope="statcast",
      desc="Pulled line drives and fly balls."),
    M("hr_fb", "HR/FB", "Contact allowed", "pct", lower=True, den="bip", k=1000, scope="statcast", desc="Home runs per fly ball."),
    # expected (builder C v Savant)
    M("xwoba_plus", "xwOBA+ against (ours)", "Expected", "3", lower=True, den="bf", stab="p_xwoba", scope="model",
      desc="Our expected wOBA allowed (see hitters' xwOBA+)."),
    M("xwoba_n", "xwOBA+ against (park-neutral)", "Expected", "3", lower=True, den="bf", stab="p_xwoba", scope="model",
      desc="xwOBA+ allowed in a standard park."),
    M("xwoba_savant", "xwOBA against (Savant)", "Expected", "3", lower=True, den="bf", k=400, scope="statcast", desc="Savant's xwOBA allowed."),
    M("woba_minus_x", "wOBA minus xwOBA+", "Expected", "3", lower=True, den="bf", k=600, scope="model",
      desc="Results allowed above expectation (positive = unlucky or poor defence)."),
    M("xba", "xBA against", "Expected", "3", lower=True, den="bf", k=800, scope="statcast", desc="Savant expected batting average allowed."),
    M("xslg", "xSLG against", "Expected", "3", lower=True, den="bf", k=500, scope="statcast", desc="Savant expected slugging allowed."),
    M("xra9", "xRA9", "Expected", "2", lower=True, den="bf", k=500, scope="model",
      desc="Expected runs per nine from xwOBA+ against (builder C's xruns over innings)."),
    M("xwobacon_savant", "xwOBAcon against (Savant)", "Expected", "3", lower=True, den="bip", k=300, scope="statcast",
      desc="Savant xwOBA on contact allowed."),
    # TTO and fatigue (builder B)
    M("xwoba_tto1", "xwOBA 1st time through", "Times through order", "3", lower=True, scope="model",
      desc="xwOBA allowed the first time through the order, shrunk with 100 PA to the league's TTO1."),
    M("xwoba_tto2", "xwOBA 2nd time through", "Times through order", "3", lower=True, scope="model", desc="Second time through."),
    M("xwoba_tto3", "xwOBA 3rd+ time through", "Times through order", "3", lower=True, den="tto3", k=100, scope="model",
      desc="Third time and later."),
    M("tto_penalty", "TTO penalty", "Times through order", "3", lower=True, den="tto3", k=100, scope="model",
      desc="xwOBA 3rd+ time minus 1st time."),
    M("velo_per100", "Velo change /100 pitches", "Fatigue", "2", scope="model",
      desc="Within-game fastball velocity slope per 100 pitches, shrunk to the league (mph)."),
    M("spin_per100", "Spin change /100 pitches", "Fatigue", "1", scope="model", desc="Within-game fastball spin slope per 100 pitches (rpm)."),
    M("velo_last3", "Velo last 3 games", "Fatigue", "2", scope="model", desc="Last three games' fastball velocity minus his season mean."),
    M("spin_last3", "Spin last 3 games", "Fatigue", "1", scope="model", desc="Last three games' spin minus his season mean."),
    M("rel_z_last3", "Release height drift", "Fatigue", "2", scope="model", desc="Last three games' release height minus season mean (in)."),
    M("velo_trend_30d", "Velo trend /30 days", "Fatigue", "2", scope="model", desc="Season slope of game fastball velocity per 30 days."),
    M("workload_flag", "Workload flag", "Fatigue", "int", lower=True, scope="model",
      desc="1 when the last three games' velocity is 1+ mph or spin 75+ rpm below his season baseline (descriptive, not medical)."),
    # value (builder C)
    M("war", "WAR (RA9)", "Value", "war", scope="model",
      desc="Bullpen WAR, results-based (RA9): runs allowed against a replacement RA9 solved so pitchers share 43 % of 1,000 WAR per "
      "2,430 games, park-adjusted, relievers scaled by (1 + gmLI) / 2."),
    M("war_x", "WAR (xwOBA+)", "Value", "war", scope="model", desc="Bullpen WAR, regressed: expected runs from xwOBA+ against instead of runs allowed."),
    M("gmli", "gmLI", "Value", "2", scope="model", desc="Average leverage index when entering a game (relievers)."),
    M("war_200", "WAR/200 IP", "Value", "1", den="bf", k=600, scope="model", desc="WAR per 200 innings."),
    # clutch
    M("wpa", "WPA", "Clutch", "2", den="bf", k=300, scope="model", desc="Win probability added (pitching side)."),
    M("wpa_li", "WPA/LI", "Clutch", "2", den="bf", k=300, scope="model", desc="Context-neutral wins."),
    M("re24", "RE24 saved", "Clutch", "rv", den="bf", k=300, scope="model", desc="Run expectancy saved over his PAs."),
    M("pli", "pLI", "Clutch", "2", scope="model", desc="Average leverage of the PAs he pitched."),
    # projections (builder D)
    M("proj_k_pct", "Projected K%", "Projection", "pct", scope="model", desc="Next-season strikeout rate (component projection)."),
    M("proj_bb_pct", "Projected BB%", "Projection", "pct", lower=True, scope="model", desc="Next-season walk rate."),
    M("proj_hr_bf", "Projected HR/BF", "Projection", "pct", lower=True, scope="model", desc="Next-season home runs per batter faced."),
    M("proj_woba", "Projected wOBA against", "Projection", "3", lower=True, scope="model", desc="Next-season wOBA allowed."),
    M("pre_woba", "Preseason projected wOBA", "Projection", "3", lower=True, scope="model", desc="The projection made before this season."),
]
ARSENAL_KEYS = ["n", "usage", "velo", "velo_max", "spin", "ivb", "hb", "vaa", "haa", "ext", "rel_z", "rel_side", "arm_angle",
                "spin_eff", "axis_meas", "axis_move", "axis_dev", "ssw", "plate_speed", "stuff", "location", "pitching", "xrv100",
                "rv100", "whiff", "csw", "chase", "zone", "xwoba", "hard", "usage_vl", "usage_vr", "usage_ahead", "usage_behind",
                "usage_two", "spread_in", "stuff_pct", "whiff_pct_type", "d_velo", "d_ivb", "d_hb"]


def build(ctx: SeasonContext) -> dict:
    A = ctx.agg()
    pit = A.get("pit") if A else None
    if pit is None or not len(pit):
        return {"ok": False, "reason": f"no pitch data for {ctx.level} {ctx.season}", "level": ctx.level, "season": ctx.season}
    ex = A.get("pit_ex", pd.DataFrame())
    lines = A.get("lines", pd.DataFrame())
    last = A.get("pit_last", pd.Series(dtype=object))
    ppt = A.get("pit_pt", pd.DataFrame())
    pm = CT.lookup(ctx.model("pitching").get("pitchers"))
    sm = CT.lookup(ctx.model("stuff").get("pitchers")) if not pm else {}
    lm = CT.lookup(ctx.model("location").get("pitchers")) if not pm else {}
    ph = CT.lookup(ctx.model("physics").get("pitchers"))
    tn = CT.lookup(ctx.model("tunneling").get("pitchers"))
    fa = CT.lookup(ctx.model("fatigue").get("pitchers"))
    war = CT.lookup(ctx.model("war").get("pitchers"))
    xw = CT.lookup(ctx.model("xwoba").get("pitchers"))
    proj = (ctx.model("proj_next").get("pitchers") or {}) if ctx.full else {}
    pre = (ctx.model("proj_pre").get("pitchers") or {}) if ctx.full else {}
    clutch = _clutch(ctx, "pitcher")
    dec = _decisions(ctx)
    velo_max = _velo_max(ctx)
    p_start = _p_starts(A.get("pa"))
    # league constants for FIP / xFIP
    lg = pit.sum()
    lg_outs = float(lines["outs"].sum()) if len(lines) else 0.0
    lg_runs = float(lines["runs"].sum()) if len(lines) else 0.0
    lg_ra9 = 27 * lg_runs / lg_outs if lg_outs else 4.4
    lg_ip = lg_outs / 3 if lg_outs else 1.0
    fip_raw = (13 * lg["hr"] + 3 * (lg["bb"] + lg["ibb"] + lg["hbp"]) - 2 * lg["k"]) / lg_ip if lg_ip else 0.0
    c_fip = lg_ra9 - fip_raw
    lg_hr_fb = an.div(lg["hr_fb"], lg["fbb"]) or 0.12
    by_pt = _by_type(ppt)
    tg = ctx.team_games() or 1
    rows: dict[str, dict] = {}
    role_of: dict[str, str] = {}
    arsenal: dict[str, dict] = {}
    for pid, r in pit.iterrows():
        bf = float(r["pa"])
        if bf < 1:
            continue
        ln = lines.loc[pid] if pid in lines.index else None
        outs = float(ln["outs"]) if ln is not None else 0.0
        ip = outs / 3
        runs = float(ln["runs"]) if ln is not None else None
        gms = int(ln["g"]) if ln is not None else None
        gs = int(ln["gs"]) if ln is not None else 0
        info = ctx.players.get(pid) or {}
        v: dict[str, Any] = {}
        d = dec.get(pid) or {}
        bbs = float(r["bb"] + r["ibb"])
        v.update(g=gms, gs=gs, w=d.get("w", 0), l=d.get("l", 0), sv=d.get("s", 0), ip=round(int(outs) // 3 + (int(outs) % 3) / 10, 1),
                 bf=bf, h=r["h"], hr=r["hr"], bb=r["bb"], ibb=r["ibb"], hbp=r["hbp"], so=r["k"], r=runs, pitches=r["pitches_all"])
        v["ip"] = round(ip, 2)
        v["ra9"] = 27 * runs / outs if outs and runs is not None else None
        v["whip"] = (bbs + r["h"]) / ip if ip else None
        v["k_pct"] = an.div(r["k"], bf)
        v["bb_pct"] = an.div(bbs, bf)
        if v["k_pct"] is not None and v["bb_pct"] is not None:
            v["k_bb_pct"] = v["k_pct"] - v["bb_pct"]
        v["k9"] = 9 * r["k"] / ip if ip else None
        v["bb9"] = 9 * bbs / ip if ip else None
        v["hr9"] = 9 * r["hr"] / ip if ip else None
        v["avg_against"] = an.div(r["h"], r["ab"])
        v["obp_against"] = an.div(r["h"] + bbs + r["hbp"], r["ab"] + bbs + r["hbp"] + r["sf"])
        v["slg_against"] = an.div(r["tb"], r["ab"])
        v["woba_against"] = an.div(r["w_num"], r["w_den"])
        v["babip_against"] = an.div(r["h"] - r["hr"], r["ab"] - r["k"] - r["hr"] + r["sf"])
        if ip:
            v["fip"] = (13 * r["hr"] + 3 * (bbs + r["hbp"]) - 2 * r["k"]) / ip + c_fip
            v["xfip"] = (13 * r["fbb"] * lg_hr_fb + 3 * (bbs + r["hbp"]) - 2 * r["k"]) / ip + c_fip
        v["p_ip"] = r["pitches_all"] / ip if ip else None
        v["p_start"] = p_start.get(pid) if gs else None
        # pitch models
        p = pm.get(pid) or {}
        if p:
            v["pitching_plus"] = CT.g(p, "pitching")
            v["stuff_plus"] = CT.g(p, "stuff")
            v["location_plus"] = CT.g(p, "location")
            v["xrv100"] = CT.g(p, "xrv100")
        else:
            v["stuff_plus"] = CT.g(sm.get(pid), "stuff")
            v["location_plus"] = CT.g(lm.get(pid), "location")
        v["rv100"] = 100 * r["rv"] / r["pitches"] if r["pitches"] else None
        types = by_pt.get(pid, {})
        prim = _primary(types)
        phys_t = ((ph.get(pid) or {}).get("types") or {})
        mod_t = (p.get("types") if p else (sm.get(pid) or {}).get("types")) or {}
        if prim:
            pf = phys_t.get(prim) or {}
            mt = mod_t.get(prim) or {}
            v["fb_stuff"] = CT.g(mt, "stuff")
            v["fb_location"] = CT.g(mt, "location")
            v["fb_pitching"] = CT.g(mt, "pitching")
            tp = types.get(prim) or {}
            v["fb_velo"] = CT.g(pf, "velo") or CT.g(mt, "velo") or CT.g(tp, "velo")
            v["fb_spin"] = CT.g(pf, "spin") or CT.g(tp, "spin")
            v["fb_ivb"] = CT.g(pf, "ivb") if pf else CT.g(tp, "ivb")
            v["fb_hb"] = CT.g(pf, "hb") if pf else CT.g(tp, "hb")
            v["fb_vaa"] = CT.g(pf, "vaa") if pf else CT.g(tp, "vaa")
            v["fb_spin_eff"] = CT.g(pf, "spin_eff")
            v["fb_axis_dev"] = CT.g(pf, "axis_dev")
            v["fb_velo_max"] = velo_max.get(pid)
        sec = [CT.g(mod_t.get(t), "stuff") for t, tr in types.items() if t not in FB_TYPES and tr["usage"] >= 0.05]
        sec = [x for x in sec if x is not None]
        v["best_secondary_stuff"] = max(sec) if sec else None
        v["n_types"] = sum(1 for tr in types.values() if tr["usage"] >= 0.05)
        v["fb_usage"] = an.div(r["fb_n"], r["pitches"])
        v["br_usage"] = an.div(r["br_n"], r["pitches"])
        v["os_usage"] = an.div(r["os_n"], r["pitches"])
        reg = [CT.g(phys_t.get(t), "velo") or tr.get("velo") for t, tr in types.items() if tr["usage"] >= 0.05]
        reg = [x for x in reg if x is not None]
        if v.get("fb_velo") is not None and reg:
            v["velo_gap"] = v["fb_velo"] - min(reg)
        rel = (ph.get(pid) or {}).get("release") or {}
        v["rel_height"] = CT.g(rel, "release_height")
        v["extension"] = CT.g(rel, "extension")
        v["arm_angle"] = CT.g(rel, "arm_angle")
        v["rel_spread"] = CT.g(rel, "spread_in")
        v["rel_type_spread"] = CT.g(rel, "type_spread_in")
        if prim:
            v["rel_side"] = CT.g(phys_t.get(prim), "rel_side") if phys_t.get(prim) else CT.g(types.get(prim), "rel_side")
        if v["rel_height"] is None and prim:
            v["rel_height"] = CT.g(types.get(prim), "rel_z")
        if v["extension"] is None:
            v["extension"] = an.div(r["ext_sum"], r["ext_n"])
        t = tn.get(pid) or {}
        v["tunnel_index"] = CT.g(t, "index")
        v["tunnel_in"] = CT.g(t, "tunnel")
        v["fb_ahead"] = an.div(r["ahead_fb"], r["ahead_n"])
        v["fb_behind"] = an.div(r["behind_fb"], r["behind_n"])
        v["fb_even"] = an.div(r["even_fb"], r["even_n"])
        v["br_two"] = an.div(r["two_br"], r["two_n"])
        v["fb_vl"] = an.div(r["vlhb_fb"], r["vlhb_n"])
        v["fb_vr"] = an.div(r["vrhb_fb"], r["vrhb_n"])
        v["os_vl"] = an.div(r["vlhb_os"], r["vlhb_n"])
        v["br_vr"] = an.div(r["vrhb_br"], r["vrhb_n"])
        v["zone_pct"] = an.div(r["in_zone"], r["zone_n"])
        v["chase_pct"] = an.div(r["o_swing"], r["out_zone"])
        v["z_swing_pct"] = an.div(r["z_swing"], r["in_zone"])
        v["whiff_pct"] = an.div(r["whiff"], r["swing"])
        v["swstr_pct"] = an.div(r["whiff"], r["pitches"])
        v["csw_pct"] = an.div(r["csw"], r["pitches"])
        v["cstr_pct"] = an.div(r["called"], r["pitches"])
        v["contact_pct"] = an.div(r["contact"], r["swing"])
        v["z_contact_pct"] = an.div(r["z_contact"], r["z_swing"])
        v["fp_strike_pct"] = an.div(r["fp_strike"], r["fp"])
        v["o_contact_pct"] = an.div(r["o_contact"], r["o_swing"])
        v["s2_whiff_pct"] = an.div(r["s2_whiff"], r["s2_swing"])
        v["chase_band_pct"] = an.div(r["chase_n"], r["pitches"])
        v["p_bf"] = an.div(r["pitches_all"], bf)
        v["woba_vl"] = an.div(r["vlhb_wn"], r["vlhb_wd"])
        v["woba_vr"] = an.div(r["vrhb_wn"], r["vrhb_wd"])
        v["xwoba_vl"] = an.div(r["vlhb_xn"], r["vlhb_wd"])
        v["xwoba_vr"] = an.div(r["vrhb_xn"], r["vrhb_wd"])
        v["k_pct_vl"] = an.div(r["vlhb_k"], r["vlhb_pa"])
        v["k_pct_vr"] = an.div(r["vrhb_k"], r["vrhb_pa"])
        v["bf_vl_share"] = an.div(r["vlhb_pa"], bf)
        v["edge_pct"] = an.div(r["shadow_n"], r["pitches"])
        v["heart_pct"] = an.div(r["heart_n"], r["pitches"])
        v["waste_pct"] = an.div(r["waste_n"], r["pitches"])
        for f in ("fb", "br", "os"):
            v[f"{f}_rv100"] = 100 * r[f"{f}_rv"] / r[f"{f}_n"] if r[f"{f}_n"] else None
            v[f"{f}_whiff_pct"] = an.div(r[f"{f}_wh"], r[f"{f}_sw"])
            v[f"{f}_csw_pct"] = an.div(r[f"{f}_csw"], r[f"{f}_n"])
            v[f"{f}_xwoba"] = an.div(r[f"{f}_xw"], r[f"{f}_den"])
        v["ev"] = an.div(r["ev_sum"], r["ev_n"])
        try:
            v["ev90"] = an.fnum(ex.at[pid, "ev90"])
        except KeyError:
            pass
        v["la"] = an.div(r["la_sum"], r["la_n"])
        v["hard_pct"] = an.div(r["hard"], r["ev_n"])
        v["barrel_pct"] = an.div(r["barrel"], r["lsa_n"])
        v["sweet_pct"] = an.div(r["sweet"], r["la_n"])
        for k, c in (("gb_pct", "gb"), ("ld_pct", "ld"), ("fb_pct", "fbb"), ("pu_pct", "pu")):
            v[k] = an.div(r[c], r["bbt_n"])
        v["pull_air_pct"] = an.div(r["pull_air"], r["spray_n"])
        v["hr_fb"] = an.div(r["hr_fb"], r["fbb"])
        x = xw.get(pid) or {}
        v["xwoba_plus"] = CT.g(x, "xwoba")
        v["xwoba_n"] = CT.g(x, "xwoba_n")
        v["xwoba_savant"] = an.div(r["xw_num"], r["w_den"])
        if v["xwoba_plus"] is not None and v["woba_against"] is not None:
            v["woba_minus_x"] = v["woba_against"] - v["xwoba_plus"]
        v["xba"] = an.div(r["xba_num"], r["ab"])
        v["xslg"] = an.div(r["xslg_num"], r["ab"])
        v["xwobacon_savant"] = an.div(r["xwc_sum"], r["xwc_n"])
        f = fa.get(pid) or {}
        if f:
            v["xwoba_tto1"] = CT.g(f, "xwoba_tto1")
            v["xwoba_tto2"] = CT.g(f, "xwoba_tto2")
            v["xwoba_tto3"] = CT.g(f, "xwoba_tto3")
            v["tto_penalty"] = CT.g(f, "tto_penalty")
            v["velo_per100"] = CT.g(f, "velo_per100")
            v["spin_per100"] = CT.g(f, "spin_per100")
            v["velo_last3"] = CT.g(f, "velo_last3")
            v["spin_last3"] = CT.g(f, "spin_last3")
            v["rel_z_last3"] = CT.g(f, "rel_z_last3_in")
            v["velo_trend_30d"] = CT.g(f, "velo_trend_30d")
            fl = f.get("flag")
            v["workload_flag"] = None if fl is None else int(bool(fl))
        w = war.get(pid) or {}
        if w:
            v["war"] = CT.g(w, "war_ra9")
            v["war_x"] = CT.g(w, "war_x")
            v["gmli"] = CT.g(w, "gmli")
            v["xra9"] = CT.g(w, "ra9_x")
            if v["war"] is not None and ip:
                v["war_200"] = 200 * v["war"] / ip
        c = clutch.get(pid) or {}
        v["wpa"], v["wpa_li"], v["re24"], v["pli"] = c.get("wpa"), c.get("wpa_li"), c.get("re24"), c.get("pli")
        pj = proj.get(pid) or {}
        if pj:
            rates = ((pj.get("rates") or {}).get("all")) or []
            if len(rates) >= 7:
                v["proj_k_pct"], v["proj_bb_pct"], v["proj_hr_bf"] = rates[0], rates[1], rates[6]
            v["proj_woba"] = CT.g(pj, "wOBA")
        if pre.get(pid):
            v["pre_woba"] = CT.g(pre[pid], "wOBA")
        role = "SP" if gs and gms and gs >= 0.5 * gms else "RP"
        n = {"bf": bf, "bip": float(r["bip"]), "pitches": float(r["pitches"]), "swings": float(r["swing"]), "oz": float(r["out_zone"]),
             "fb": float(r["fb_n"]), "br": float(r["br_n"]), "os": float(r["os_n"]), "ip": ip, "games": gms,
             "tto3": CT.g(f, "pa_tto3"), "bf_l": float(r["vlhb_pa"]), "bf_r": float(r["vrhb_pa"])}
        team_abbr = last.get(pid) if len(last) else None
        rows[pid] = {"name": ctx.name(pid), "team": ctx.tid(team_abbr), "team_abbr": team_abbr, "pos": info.get("pos") or "P",
                     "role": role, "throws": info.get("throws"),
                     "age": an.age_on(info.get("dob") or (ctx.people.get(pid) or {}).get("birth"), ctx.season),
                     "bf": int(bf), "qualified": ip >= QUAL_IP_PER_G * tg, "primary": prim, "values": v, "n": n}
        role_of[pid] = role
        arsenal[pid] = _arsenal(types, phys_t, mod_t, prim)
    ref_bf = max(FLOORS["bf"], REF_BF_PER_G * tg)
    reference = [p for p, r in rows.items() if r["bf"] >= ref_bf]
    if len(reference) < 20:
        reference = sorted(rows, key=lambda p: -rows[p]["bf"])[:max(20, len(rows) // 3)]
    means = CT.finish(ctx, rows, METRICS, reference, role_of, FLOORS)
    _arsenal_pct(arsenal)
    for r in rows.values():
        r["n"] = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in r["n"].items()}
    league_types = _league_types(ppt, ctx)
    return {**CT.season_meta(ctx), "kind": "pitcher", "metrics": [an.public_metric(m) for m in METRICS], "players": rows,
            "arsenal": arsenal, "arsenal_keys": ARSENAL_KEYS, "league_types": league_types,
            "reference": {"rule": f"BF >= {REF_BF_PER_G} per team game (floor {FLOORS['bf']})", "n": len(reference),
                          "min_bf": round(ref_bf), "means": {k: an.rnd(v, 4) for k, v in means.items()}},
            "constants": {"lg_ra9": round(lg_ra9, 3), "c_fip": round(c_fip, 3), "lg_hr_fb": round(lg_hr_fb, 4)},
            "floors": FLOORS, "roles": ["SP", "RP"]}


def _by_type(ppt: pd.DataFrame) -> dict[str, dict]:
    """{pid: {pt: {n, usage, whiff, csw, chase, zone, xwoba, hard, usage_vl, ...}}} from the pitcher x type sums."""
    out: dict[str, dict] = {}
    if ppt is None or not len(ppt):
        return out
    tot: dict[str, float] = {}
    for key, r in ppt.iterrows():
        pid, pt = key.split("|", 1)
        if pt in ("", "nan", "PO", "IN", "AB"):
            continue
        tot[pid] = tot.get(pid, 0.0) + float(r["pitches"])
    totl: dict[str, tuple] = {}
    for key, r in ppt.iterrows():
        pid, _ = key.split("|", 1)
        a = totl.get(pid, (0.0, 0.0, 0.0, 0.0, 0.0))
        totl[pid] = (a[0] + r["vlhb_n"], a[1] + r["vrhb_n"], a[2] + r["ahead_n"], a[3] + r["behind_n"], a[4] + r["two_n"])
    for key, r in ppt.iterrows():
        pid, pt = key.split("|", 1)
        if pt in ("", "nan", "PO", "IN", "AB") or not r["pitches"]:
            continue
        tl = totl.get(pid)
        out.setdefault(pid, {})[pt] = {
            "n": int(r["pitches"]), "usage": r["pitches"] / tot[pid] if tot.get(pid) else None,
            "whiff": an.div(r["whiff"], r["swing"]), "csw": an.div(r["csw"], r["pitches"]), "chase": an.div(r["o_swing"], r["out_zone"]),
            "zone": an.div(r["in_zone"], r["zone_n"]), "xwoba": an.div(r["xw_num"], r["w_den"]), "hard": an.div(r["hard"], r["ev_n"]),
            "rv100_actual": 100 * r["rv"] / r["pitches"],
            "usage_vl": an.div(r["vlhb_n"], tl[0]) if tl else None, "usage_vr": an.div(r["vrhb_n"], tl[1]) if tl else None,
            "usage_ahead": an.div(r["ahead_n"], tl[2]) if tl else None, "usage_behind": an.div(r["behind_n"], tl[3]) if tl else None,
            "usage_two": an.div(r["two_n"], tl[4]) if tl else None, "swings": int(r["swing"]), "pa": int(r["pa"]),
            "velo": an.div(r["velo_sum"], r["velo_n"]), "spin": an.div(r["spin_sum"], r["spin_n"]), "ivb": an.div(r["ivb_sum"], r["ivb_n"]),
            "hb": an.div(r["hb_sum"], r["hb_n"]), "ext": an.div(r["ext_sum"], r["ext_n"]), "vaa": an.div(r["vaa_sum"], r["vaa_n"]),
            "rel_z": an.div(r["relz_sum"], r["relz_n"]), "rel_side": an.div(r["rels_sum"], r["rels_n"])}
    return out


def _primary(types: dict) -> str | None:
    fb = [(tr["n"], t) for t, tr in types.items() if t in FB_TYPES]
    if fb:
        return max(fb)[1]
    return max(((tr["n"], t) for t, tr in types.items()), default=(0, None))[1]


def _arsenal(types: dict, phys: dict, mod: dict, prim: str | None) -> dict:
    out = {}
    pf = phys.get(prim) or {} if prim else {}
    for t, tr in sorted(types.items(), key=lambda kv: -kv[1]["n"]):
        if tr["n"] < 10:
            continue
        p = phys.get(t) or {}
        m = mod.get(t) or {}
        def ph(k):
            for src in (p, m, tr):
                x = an.fnum(src.get(k))
                if x is not None:
                    return x
            return None
        row = {"n": tr["n"], "usage": an.rnd(tr["usage"], 3), "velo": an.rnd(ph("velo"), 1),
               "spin": an.inum(ph("spin")), "ivb": an.rnd(ph("ivb"), 1),
               "hb": an.rnd(ph("hb"), 1), "vaa": an.rnd(ph("vaa"), 2), "haa": an.rnd(p.get("haa"), 2),
               "ext": an.rnd(ph("ext"), 2), "rel_z": an.rnd(ph("rel_z"), 2), "rel_side": an.rnd(ph("rel_side"), 2),
               "arm_angle": an.rnd(p.get("arm_angle"), 1), "spin_eff": an.rnd(p.get("spin_eff"), 3), "axis_meas": an.rnd(p.get("axis_meas"), 0),
               "axis_move": an.rnd(p.get("axis_move"), 0), "axis_dev": an.rnd(p.get("axis_dev"), 1), "ssw": an.rnd(p.get("ssw"), 3),
               "plate_speed": an.rnd(p.get("plate_speed"), 1), "spread_in": an.rnd(p.get("spread_in"), 2),
               "stuff": an.inum(m.get("stuff")), "location": an.inum(m.get("location")), "pitching": an.inum(m.get("pitching")),
               "xrv100": an.rnd(m.get("xrv100"), 2), "rv100": an.rnd(tr.get("rv100_actual"), 2),
               "whiff": an.rnd(tr["whiff"], 3), "csw": an.rnd(tr["csw"], 3), "chase": an.rnd(tr["chase"], 3), "zone": an.rnd(tr["zone"], 3),
               "xwoba": an.rnd(tr["xwoba"], 3), "hard": an.rnd(tr["hard"], 3), "usage_vl": an.rnd(tr["usage_vl"], 3),
               "usage_vr": an.rnd(tr["usage_vr"], 3), "usage_ahead": an.rnd(tr["usage_ahead"], 3),
               "usage_behind": an.rnd(tr["usage_behind"], 3), "usage_two": an.rnd(tr["usage_two"], 3)}
        if prim and t != prim:
            pp = {**(types.get(prim) or {}), **{k: v for k, v in pf.items() if v is not None}}
            for k, c in (("d_velo", "velo"), ("d_ivb", "ivb"), ("d_hb", "hb")):
                a, b = an.fnum(row.get(c)), an.fnum(pp.get(c))
                row[k] = an.rnd(a - b, 1) if a is not None and b is not None else None
        out[t] = row
    return out


def _arsenal_pct(arsenal: dict) -> None:
    """Percentile of each pitch's Stuff+ and whiff% among the league's pitches of the same type (100+ thrown)."""
    by: dict[str, dict[str, list]] = {}
    for pid, a in arsenal.items():
        for t, r in a.items():
            if r["n"] >= 100:
                by.setdefault(t, {"stuff": [], "whiff": []})
                if r.get("stuff") is not None:
                    by[t]["stuff"].append(r["stuff"])
                if r.get("whiff") is not None:
                    by[t]["whiff"].append(r["whiff"])
    for t in by:
        for k in by[t]:
            by[t][k].sort()
    for a in arsenal.values():
        for t, r in a.items():
            ref = by.get(t)
            if not ref or r["n"] < 50:
                continue
            if r.get("stuff") is not None and len(ref["stuff"]) >= 5:
                r["stuff_pct"] = an._place(ref["stuff"], r["stuff"], False)
            if r.get("whiff") is not None and len(ref["whiff"]) >= 5:
                r["whiff_pct_type"] = an._place(ref["whiff"], r["whiff"], False)


def _league_types(ppt: pd.DataFrame, ctx: SeasonContext) -> dict:
    """League norms per pitch type: pitches, usage, whiff, CSW, and builder B's stuff / physics means."""
    if ppt is None or not len(ppt):
        return {}
    pt = ppt.index.str.split("|").str[1]
    g = ppt.groupby(pt.to_numpy()).sum()
    tot = float(g["pitches"].sum()) or 1.0
    stuff_lg = (ctx.model("stuff").get("league") or {})
    phys_lg = (ctx.model("physics").get("league") or {})
    out = {}
    for t, r in g.iterrows():
        if t in ("", "nan") or r["pitches"] < 100:
            continue
        p = phys_lg.get(t) or {}
        out[t] = {"n": int(r["pitches"]), "usage": round(float(r["pitches"]) / tot, 4), "whiff": an.rnd(an.div(r["whiff"], r["swing"]), 3),
                  "csw": an.rnd(an.div(r["csw"], r["pitches"]), 3), "xwoba": an.rnd(an.div(r["xw_num"], r["w_den"]), 3),
                  "stuff": an.rnd((stuff_lg.get(t) or {}).get("stuff"), 1), "velo": an.rnd(p.get("velo"), 1),
                  "ivb": an.rnd(p.get("ivb"), 1), "hb": an.rnd(p.get("hb"), 1), "spin": an.inum(p.get("spin")),
                  "vaa": an.rnd(p.get("vaa"), 2)}
    return out


def _decisions(ctx: SeasonContext) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for g in ctx.games.values():
        if (g or {}).get("gtype") != "R" or g.get("status") != "final":
            continue
        for k, pid in ((g.get("decisions") or {}).items()):
            if pid:
                d = out.setdefault(str(pid), {})
                d[k] = d.get(k, 0) + 1
    return out


def _velo_max(ctx: SeasonContext) -> dict[str, float]:
    """95th percentile velocity of each pitcher's fastballs (robust maximum)."""
    df = ctx.frame()
    if not len(df):
        return {}
    pt = df["pitch_type"].astype(object)
    m = pt.isin(FB_TYPES).to_numpy()
    v = pd.to_numeric(df.loc[m, "release_speed"], errors="coerce")
    q = v.groupby(df.loc[m, "pitcher"].astype(str)).quantile(0.95)
    return {k: float(x) for k, x in q.items() if np.isfinite(x)}


def _p_starts(pa: pd.DataFrame | None) -> dict[str, float]:
    """Mean pitch count per start for every starter (the first pitcher of his team's half-innings)."""
    if pa is None or not len(pa):
        return {}
    firsts = pa.sort_values(["game_pk", "half", "at_bat_number"]).drop_duplicates(["game_pk", "half"])
    st = firsts[["game_pk", "half", "pitcher"]]
    j = pa.merge(st, on=["game_pk", "half", "pitcher"], how="inner")
    x = j.groupby([j["pitcher"].astype(str), "game_pk"])["n_pitches"].sum()
    return {k: float(v) for k, v in x.groupby(level=0).mean().items()}
