"""
Hitters catalogue (hitters.json): about 170 metrics per hitter and season, regular season only.

Groups: traditional; plate discipline; decision value (builder B's swing model); contact quality; expected
stats (builder C's xwOBA+ against Savant's xwOBA); batted-ball profile and spray; bat tracking (builder B,
adjusted for count, location and pitch speed); swing path; by pitch family, velocity band and attack zone;
platoon; clutch (builder C's WPA and leverage); baserunning; defence (builder C's catch probability and
framing, Savant's arm strength); Bullpen WAR; projections (builder D).

Percentiles (PAYLOADS "pct" / "pct_role"): direction-aware (100 = best), placed against the reference pool
(hitters with at least 2.1 PA per team game, floor 50 PA), and against the same position group
("pct_role": C, 1B, 2B, 3B, SS, CF, LF/RF, DH). A hitter gets a percentile on a metric only once his sample
for it reaches the floor (FLOORS), and the value placed is shrunk toward the pool mean with the metric's
stabilisation constant k (stabilise.py): (n v + k m) / (n + k). "qualified" is MLB's rule (3.1 PA per team game).
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import catalog as CT
from oddsmarkets.baseball.analytics.context import SeasonContext, frame_rows

M = an.metric
OAA_K = an.OAA_K
FLOORS = {"pa": 50, "bip": 25, "pitches": 150, "swings": 75, "bat_swings": 50, "oz": 60, "iz": 60, "pa_l": 30, "pa_r": 30,
          "chances": 20, "called": 500, "fb": 60, "br": 40, "os": 30, "v95": 40, "v90": 40, "vlo": 40, "heart": 40,
          "chase": 40, "shadow": 40, "waste": 30, "runs": 1, "games": 10}
REF_PA_PER_G = 2.1
QUAL_PA_PER_G = 3.1

METRICS: list[dict] = [
    # traditional
    M("g", "Games", "Traditional", "int", desc="Games with a plate appearance."),
    M("pa", "PA", "Traditional", "int", desc="Plate appearances."),
    M("ab", "AB", "Traditional", "int", desc="At-bats: PA minus walks, HBP, sacrifices and catcher's interference."),
    M("h", "H", "Traditional", "int", desc="Hits."),
    M("b1", "1B", "Traditional", "int", desc="Singles."),
    M("b2", "2B", "Traditional", "int", desc="Doubles."),
    M("b3", "3B", "Traditional", "int", desc="Triples."),
    M("hr", "HR", "Traditional", "int", desc="Home runs."),
    M("bb", "uBB", "Traditional", "int", desc="Unintentional walks (MLB's BB includes IBB: add the IBB column)."),
    M("ibb", "IBB", "Traditional", "int", desc="Intentional walks."),
    M("hbp", "HBP", "Traditional", "int", desc="Hit by pitch."),
    M("so", "SO", "Traditional", "int", lower=True, desc="Strikeouts."),
    M("sf", "SF", "Traditional", "int", desc="Sacrifice flies."),
    M("sh", "SH", "Traditional", "int", desc="Sacrifice bunts."),
    M("gidp", "GIDP", "Traditional", "int", lower=True, desc="Grounded into double play."),
    M("avg", "AVG", "Traditional", "3", den="pa", k=910, desc="H / AB."),
    M("obp", "OBP", "Traditional", "3", den="pa", k=460, desc="(H + BB + IBB + HBP) / (AB + BB + IBB + HBP + SF)."),
    M("slg", "SLG", "Traditional", "3", den="pa", k=320, desc="Total bases / AB."),
    M("ops", "OPS", "Traditional", "3", den="pa", k=380, desc="OBP + SLG."),
    M("iso", "ISO", "Traditional", "3", den="pa", k=160, desc="SLG - AVG."),
    M("babip", "BABIP", "Traditional", "3", den="bip", stab="babip", desc="(H - HR) / (AB - SO - HR + SF)."),
    M("woba", "wOBA", "Traditional", "3", den="pa", stab="woba", desc="Savant's woba_value summed over woba_denom: linear "
      "weights of each PA result, scaled to OBP."),
    M("k_pct", "K%", "Traditional", "pct", lower=True, den="pa", stab="k_rate", desc="Strikeouts per PA."),
    M("bb_pct", "BB%", "Traditional", "pct", den="pa", stab="bb_rate", desc="Walks (incl. intentional) per PA."),
    M("bb_k", "BB/K", "Traditional", "2", den="pa", k=150, desc="Walks per strikeout."),
    M("hr_pa", "HR/PA", "Traditional", "pct", den="pa", k=170, desc="Home runs per PA."),
    M("xbh_pa", "XBH/PA", "Traditional", "pct", den="pa", k=300, desc="Extra-base hits per PA."),
    M("hbp_pct", "HBP%", "Traditional", "pct", den="pa", stab="hbp_rate", desc="Hit by pitch per PA."),
    # discipline
    M("swing_pct", "Swing%", "Discipline", "pct", den="pitches", stab="swing_rate", scope="statcast", desc="Swings per pitch."),
    M("zone_pct", "Zone% seen", "Discipline", "pct", den="pitches", k=600, scope="statcast",
      desc="Share of pitches seen in the strike zone (Savant zones 1-9)."),
    M("z_swing_pct", "Z-Swing%", "Discipline", "pct", den="iz", stab="zswing_rate", scope="statcast", desc="Swings at pitches in the zone."),
    M("chase_pct", "Chase%", "Discipline", "pct", lower=True, den="oz", stab="chase_rate", scope="statcast",
      desc="Swings at pitches outside the zone (O-Swing%)."),
    M("contact_pct", "Contact%", "Discipline", "pct", den="swings", k=100, scope="statcast", desc="Contact (fouls and balls in play) per swing."),
    M("z_contact_pct", "Z-Contact%", "Discipline", "pct", den="swings", k=150, scope="statcast", desc="Contact per swing in the zone."),
    M("o_contact_pct", "O-Contact%", "Discipline", "pct", den="swings", k=120, scope="statcast", desc="Contact per swing outside the zone."),
    M("whiff_pct", "Whiff%", "Discipline", "pct", lower=True, den="swings", stab="whiff_rate", scope="statcast",
      desc="Swinging strikes (incl. foul tips) per swing."),
    M("swstr_pct", "SwStr%", "Discipline", "pct", lower=True, den="pitches", k=300, scope="statcast", desc="Swinging strikes per pitch."),
    M("cstr_pct", "Called strike%", "Discipline", "pct", lower=True, den="pitches", k=400, scope="statcast", desc="Called strikes per pitch seen."),
    M("csw_pct", "CSW% against", "Discipline", "pct", lower=True, den="pitches", k=350, scope="statcast", desc="Called strikes plus whiffs per pitch."),
    M("fp_swing_pct", "First-pitch swing%", "Discipline", "pct", den="pa", k=200, scope="statcast", desc="Swings at the first pitch of a PA."),
    M("fp_strike_pct", "First-pitch strike% seen", "Discipline", "pct", lower=True, den="pa", k=300, scope="statcast",
      desc="First pitches that were strikes (called, swinging, foul or in play)."),
    M("p_pa", "Pitches/PA", "Discipline", "2", den="pa", k=150, scope="statcast", desc="Pitches seen per plate appearance."),
    M("s2_whiff_pct", "Two-strike whiff%", "Discipline", "pct", lower=True, den="swings", k=150, scope="statcast",
      desc="Whiffs per swing with two strikes."),
    M("heart_swing_pct", "Heart swing%", "Discipline", "pct", den="heart", k=100, scope="statcast",
      desc="Swings at pitches in the heart of the zone (attack zones)."),
    M("chase_zone_swing_pct", "Chase-zone swing%", "Discipline", "pct", lower=True, den="chase", k=150, scope="statcast",
      desc="Swings in the chase band (133-200 % of the zone)."),
    M("waste_swing_pct", "Waste swing%", "Discipline", "pct", lower=True, den="waste", k=150, scope="statcast",
      desc="Swings at waste pitches (beyond 200 % of the zone)."),
    # decision value (builder B)
    M("dv", "Decision value", "Decisions", "rv", den="pitches", k=1500, scope="model",
      desc="Runs gained by swing/take choices alone (swing model, centred on the league): for every pitch, the run value "
      "of the choice made minus the expected value of the league's swing probability there; contact quality is excluded."),
    M("dv100", "Decision value /100", "Decisions", "2", den="pitches", k=1500, scope="model", desc="Decision value per 100 pitches."),
    M("dv_zone", "Zone decisions", "Decisions", "rv", den="pitches", k=1500, scope="model", desc="Decision value on pitches in the zone."),
    M("dv_chase", "Chase decisions", "Decisions", "rv", den="pitches", k=1500, scope="model", desc="Decision value on pitches outside the zone."),
    M("x_swing_pct", "Expected swing%", "Decisions", "pct", den="pitches", k=600, scope="model",
      desc="The league swing probability for the pitches he saw (location, count, pitch shape)."),
    M("swing_oe", "Swing% over expected", "Decisions", "pct", den="pitches", k=600, scope="model",
      desc="Swing% minus expected swing%: aggression beyond what the pitches called for."),
    M("should_swing_pct", "Bad-take rate", "Decisions", "pct", den="pitches", k=600, scope="model", lower=True,
      desc="Share of his takes on which swinging had the higher expected run value (lower is better)."),
    M("should_take_pct", "Bad-swing rate", "Decisions", "pct", den="swings", k=600, scope="model", lower=True,
      desc="Share of his swings on which taking had the higher expected run value."),
    # contact quality
    M("ev", "Exit velocity", "Contact", "mph", den="bip", stab="ev", scope="statcast", desc="Mean exit velocity on balls in play."),
    M("ev90", "EV90", "Contact", "mph", den="bip", k=40, scope="statcast", desc="90th percentile exit velocity."),
    M("ev_max", "Max EV", "Contact", "mph", den="bip", k=60, scope="statcast", desc="Hardest-hit ball."),
    M("la", "Launch angle", "Contact", "deg", den="bip", stab="la", scope="statcast", desc="Mean launch angle."),
    M("la_sd", "Launch angle SD", "Contact", "deg", den="bip", k=80, scope="statcast", lower=True,
      desc="Spread of launch angles (lower = more consistent)."),
    M("hard_pct", "Hard-hit%", "Contact", "pct", den="bip", stab="hard_hit", scope="statcast", desc="Balls in play at 95+ mph."),
    M("barrel_pct", "Barrel%", "Contact", "pct", den="bip", stab="barrel", scope="statcast",
      desc="Barrels (Savant launch_speed_angle 6: the speed/angle combinations worth a .500 AVG and 1.500 SLG) per ball in play."),
    M("barrel_pa", "Barrels/PA", "Contact", "pct", den="pa", k=250, scope="statcast", desc="Barrels per plate appearance."),
    M("sweet_pct", "Sweet-spot%", "Contact", "pct", den="bip", k=120, scope="statcast", desc="Launch angle 8-32 degrees."),
    M("solid_pct", "Solid contact%", "Contact", "pct", den="bip", k=200, scope="statcast", desc="launch_speed_angle 5."),
    M("flare_pct", "Flare/burner%", "Contact", "pct", den="bip", k=150, scope="statcast", desc="launch_speed_angle 4."),
    M("under_pct", "Under%", "Contact", "pct", den="bip", k=150, scope="statcast", lower=True, desc="launch_speed_angle 3: hit under."),
    M("topped_pct", "Topped%", "Contact", "pct", den="bip", k=150, scope="statcast", lower=True, desc="launch_speed_angle 2."),
    M("weak_pct", "Weak%", "Contact", "pct", den="bip", k=150, scope="statcast", lower=True, desc="launch_speed_angle 1."),
    M("hr_dist", "HR distance", "Contact", "ft", scope="statcast", desc="Mean projected home-run distance."),
    M("fb_dist", "Fly-ball distance", "Contact", "ft", den="bip", k=80, scope="statcast", desc="Mean distance of fly balls."),
    M("dist_max", "Longest ball", "Contact", "ft", scope="statcast", desc="Longest projected distance."),
    # expected stats (builder C v Savant)
    M("xwoba_plus", "xwOBA+ (ours)", "Expected", "3", den="pa", stab="xwoba", scope="model",
      desc="Our expected wOBA: each ball in play scored from exit velocity, launch angle, hang time, the park (its five fence "
      "distances, mean wall height, elevation and roof) and sprint speed; walks, HBP and strikeouts at their wOBA values."),
    M("xwoba_n", "xwOBA+ (park-neutral)", "Expected", "3", den="pa", stab="xwoba", scope="model",
      desc="xwOBA+ with every ball re-scored in a standard park (330/375/400 ft, 8 ft walls, median elevation, open roof)."),
    M("xwoba_savant", "xwOBA (Savant)", "Expected", "3", den="pa", stab="savant_xwoba", scope="statcast",
      desc="Savant's xwOBA (estimated_woba_using_speedangle on balls in play)."),
    M("xwoba_diff", "xwOBA+ minus xwOBA (Savant)", "Expected", "3", den="pa", k=300, scope="model",
      desc="xwOBA+ minus Savant's xwOBA: what hang time, the park and sprint speed add to exit velocity and launch angle."),
    M("woba_minus_x", "wOBA minus xwOBA+", "Expected", "3", den="pa", k=300, scope="model",
      desc="Results above expectation (positive = outperforming contact quality; regresses)."),
    M("xba", "xBA", "Expected", "3", den="pa", k=500, scope="statcast", desc="Savant expected batting average."),
    M("xslg", "xSLG", "Expected", "3", den="pa", k=300, scope="statcast", desc="Savant expected slugging."),
    M("xwobacon_plus", "xwOBAcon+", "Expected", "3", den="bip", stab="xwobacon", scope="model", desc="xwOBA+ on balls in play."),
    M("xwobacon_savant", "xwOBAcon (Savant)", "Expected", "3", den="bip", stab="savant_xwobacon", scope="statcast",
      desc="Savant's xwOBA on balls in play."),
    # batted-ball profile / spray
    M("gb_pct", "GB%", "Batted ball", "pct", den="bip", stab="gb_rate", scope="statcast", lower=True, desc="Ground balls per ball in play."),
    M("ld_pct", "LD%", "Batted ball", "pct", den="bip", k=600, scope="statcast", desc="Line drives."),
    M("fb_pct", "FB%", "Batted ball", "pct", den="bip", stab="fb_rate", scope="statcast", desc="Fly balls."),
    M("pu_pct", "PU%", "Batted ball", "pct", den="bip", k=250, scope="statcast", lower=True, desc="Pop-ups."),
    M("pull_pct", "Pull%", "Spray", "pct", den="bip", stab="pull_rate", scope="statcast",
      desc="Spray angle more than 15 degrees to the pull side."),
    M("cent_pct", "Straightaway%", "Spray", "pct", den="bip", k=200, scope="statcast", desc="Within 15 degrees of centre."),
    M("oppo_pct", "Oppo%", "Spray", "pct", den="bip", k=200, scope="statcast", desc="More than 15 degrees to the opposite field."),
    M("pull_air_pct", "Pull-air%", "Spray", "pct", den="bip", k=150, scope="statcast",
      desc="Pulled line drives and fly balls per ball in play (the most valuable batted-ball direction)."),
    M("oppo_air_pct", "Oppo-air%", "Spray", "pct", den="bip", k=200, scope="statcast", desc="Opposite-field line drives and fly balls."),
    M("hr_fb", "HR/FB", "Spray", "pct", den="bip", k=300, scope="statcast", desc="Home runs per fly ball."),
    # bat tracking (builder B)
    M("bat_speed", "Bat speed", "Bat tracking", "mph", den="bat_swings", stab="bat_speed", scope="tracking",
      desc="Mean bat speed (sweet spot, competitive swings with 50+ mph)."),
    M("bat_speed_adj", "Adjusted bat speed", "Bat tracking", "mph", den="bat_swings", k=50, scope="model",
      desc="Bat speed relative to the expectation for his pitches (count, location, pitch speed), shrunk with 50 swings, "
      "plus the league mean."),
    M("fast_swing_pct", "Fast-swing%", "Bat tracking", "pct", den="bat_swings", k=60, scope="tracking", desc="Swings at 75+ mph."),
    M("swing_length", "Swing length", "Bat tracking", "ft", den="bat_swings", k=60, scope="tracking", lower=True,
      desc="Distance the bat head travels (ft)."),
    M("swing_length_adj", "Adjusted swing length", "Bat tracking", "ft", den="bat_swings", k=50, scope="model", lower=True,
      desc="Swing length relative to the expectation for his pitches."),
    M("sq_contact", "Squared-up% (contact)", "Bat tracking", "pct", den="bat_swings", k=100, scope="tracking",
      desc="Contact with 80 %+ of the attainable exit velocity (1.23 bat speed + 0.23 pitch speed)."),
    M("sq_swing", "Squared-up% (swing)", "Bat tracking", "pct", den="bat_swings", k=120, scope="tracking", desc="Squared-up per swing."),
    M("sq_oe", "Squared-up over expected", "Bat tracking", "pct", den="bat_swings", k=150, scope="model",
      desc="Squared-up rate minus the model's expectation for the pitches he made contact with."),
    M("attack_angle", "Attack angle", "Swing path", "deg", den="bat_swings", k=50, scope="tracking",
      desc="Vertical angle of the bat's path at contact."),
    M("path_mismatch", "Path mismatch", "Swing path", "deg", den="bat_swings", k=80, scope="model", lower=True,
      desc="Mean |attack angle + pitch VAA|: how far his swing plane is from the pitch plane."),
    M("path_matched_pct", "Path matched%", "Swing path", "pct", den="bat_swings", k=80, scope="model",
      desc="Swings within 5 degrees of the pitch plane."),
    M("attack_direction", "Attack direction", "Swing path", "deg", den="bat_swings", k=50, scope="tracking",
      desc="Horizontal angle of the bat path (+ toward the pull side)."),
    M("swing_tilt", "Swing-path tilt", "Swing path", "deg", den="bat_swings", k=50, scope="tracking", desc="Tilt of the swing plane."),
    M("intercept_rel", "Contact point (rel.)", "Swing path", "in", den="bat_swings", k=50, scope="model",
      desc="Intercept point in front of the body relative to the league (in; + = out front)."),
    # by pitch family
    *[m for f, nm in (("fb", "fastballs"), ("br", "breaking balls"), ("os", "offspeed")) for m in (
        M(f"{f}_xwoba", f"xwOBA v {nm}", "By pitch", "3", den=f, k=300, scope="statcast", desc=f"Savant xwOBA on PAs ending with {nm}."),
        M(f"{f}_whiff_pct", f"Whiff% v {nm}", "By pitch", "pct", den=f, k=150, lower=True, scope="statcast", desc=f"Whiffs per swing v {nm}."),
        M(f"{f}_rv100", f"Run value/100 v {nm}", "By pitch", "2", den=f, k=400, scope="statcast",
          desc=f"Batting run value (Savant delta_run_exp) per 100 {nm} seen."),
        M(f"{f}_chase_pct", f"Chase% v {nm}", "By pitch", "pct", den=f, k=150, lower=True, scope="statcast",
          desc=f"Swings at {nm} outside the zone."))],
    # velocity bands
    *[m for b, nm in (("v95", "95+ mph"), ("v90", "90-95 mph"), ("vlo", "under 90 mph")) for m in (
        M(f"{b}_xwoba", f"xwOBA v {nm}", "By velocity", "3", den=b, k=300, scope="statcast", desc=f"Savant xwOBA on PAs ending with a pitch at {nm}."),
        M(f"{b}_whiff_pct", f"Whiff% v {nm}", "By velocity", "pct", den=b, k=150, lower=True, scope="statcast", desc=f"Whiffs per swing at {nm}."))],
    # attack zones
    *[m for z in ("heart", "shadow", "chase", "waste") for m in (
        M(f"{z}_rv100", f"Run value/100 ({z})", "By location", "2", den=z, k=400, scope="statcast",
          desc=f"Batting run value per 100 pitches in the {z} attack zone."),)],
    M("shadow_swing_pct", "Shadow swing%", "By location", "pct", den="shadow", k=150, scope="statcast",
      desc="Swings at pitches on the edges (shadow attack zone)."),
    # platoon
    M("woba_vl", "wOBA v LHP", "Platoon", "3", den="pa_l", stab="woba", desc="wOBA against left-handed pitchers."),
    M("woba_vr", "wOBA v RHP", "Platoon", "3", den="pa_r", stab="woba", desc="wOBA against right-handed pitchers."),
    M("xwoba_vl", "xwOBA v LHP", "Platoon", "3", den="pa_l", stab="savant_xwoba", scope="statcast", desc="Savant xwOBA v LHP."),
    M("xwoba_vr", "xwOBA v RHP", "Platoon", "3", den="pa_r", stab="savant_xwoba", scope="statcast", desc="Savant xwOBA v RHP."),
    M("k_pct_vl", "K% v LHP", "Platoon", "pct", lower=True, den="pa_l", stab="k_rate", desc="Strikeouts per PA v LHP."),
    M("k_pct_vr", "K% v RHP", "Platoon", "pct", lower=True, den="pa_r", stab="k_rate", desc="Strikeouts per PA v RHP."),
    M("pa_vl_share", "PA share v LHP", "Platoon", "pct", desc="Share of his PAs against left-handers."),
    M("platoon_gap", "Platoon gap", "Platoon", "3", lower=True, den="pa_l", k=600,
      desc="|wOBA v same-handed pitchers - wOBA v opposite-handed| (switch hitters: |v LHP - v RHP|)."),
    # clutch (builder C)
    M("wpa", "WPA", "Clutch", "2", den="pa", k=300, scope="model",
      desc="Win probability added: the change in our win expectancy (Markov model on inning, half, outs, bases, score) over his PAs."),
    M("wpa_li", "WPA/LI", "Clutch", "2", den="pa", k=300, scope="model", desc="Context-neutral wins: sum of WPA / leverage."),
    M("clutch", "Clutch", "Clutch", "2", den="pa", k=600, scope="model", desc="WPA / pLI - WPA/LI (FanGraphs' definition)."),
    M("pli", "pLI", "Clutch", "2", desc="Average leverage index of his PAs (1 = average)."),
    M("re24", "RE24", "Clutch", "rv", den="pa", k=300, scope="model", desc="Run expectancy added over his PAs (runs)."),
    M("re24_pa", "RE24/PA", "Clutch", "3", den="pa", k=300, scope="model", desc="RE24 per plate appearance."),
    M("woba_hilev", "wOBA high leverage", "Clutch", "3", den="pa", k=600, scope="model", desc="wOBA in PAs with LI >= 1.5."),
    # baserunning
    M("sprint_speed", "Sprint speed", "Baserunning", "1", scope="statcast", desc="Savant sprint speed (ft/s, top two-thirds of competitive runs)."),
    M("hp_to_1b", "Home to first", "Baserunning", "2", lower=True, scope="statcast", desc="Savant home-to-first time (s)."),
    M("bsr", "Baserunning runs", "Baserunning", "1", scope="model",
      desc="Steals (wSB) plus extra bases taken on hits against the league for the same hit, base and outs (builder C)."),
    M("wsb", "wSB", "Baserunning", "1", scope="model", desc="Stolen-base runs above average (FanGraphs' constants)."),
    M("ebt_runs", "Extra-base runs", "Baserunning", "1", scope="model", desc="Runs from taking extra bases on hits."),
    M("sb", "SB", "Baserunning", "int", scope="model",
      desc="Stolen bases: MLB's official line (Stats API); estimated from the pitch data only when no official line is on file."),
    M("cs", "CS", "Baserunning", "int", lower=True, scope="model",
      desc="Caught stealing: MLB's official line (Stats API); estimated from the pitch data only when no official line is on file."),
    # defence
    M("oaa", "OAA", "Defence", "1", den="chances", k=OAA_K, scope="model",
      desc="Outs above average from our catch-probability model (landing spot, hang time, alignment-inferred start)."),
    M("fielding_runs", "Fielding runs", "Defence", "1", den="chances", k=OAA_K, scope="model", desc="OAA converted to runs with the season's linear weights."),
    M("sra", "Success rate added", "Defence", "pct", den="chances", k=OAA_K, scope="model", desc="OAA per chance."),
    M("oaa_back", "OAA going back", "Defence", "1", scope="model", desc="OAA on plays moving back."),
    M("oaa_in", "OAA coming in", "Defence", "1", scope="model", desc="OAA on plays moving in."),
    M("oaa_3b", "OAA toward 3B", "Defence", "1", scope="model", desc="OAA moving toward the third-base line."),
    M("oaa_1b", "OAA toward 1B", "Defence", "1", scope="model", desc="OAA moving toward the first-base line."),
    M("oaa_savant", "Savant OAA", "Defence", "int", scope="statcast", desc="Savant's published outs above average (for comparison)."),
    M("arm", "Arm strength", "Defence", "mph", scope="statcast", desc="Savant arm strength (top throws, mph)."),
    M("framing_runs", "Framing runs", "Defence", "1", den="called", stab="c_frame", scope="model",
      desc="Catchers: called strikes added over the league surface (location, count, pitch, umpire, pitcher, batter effects) "
      "times the run value of a strike."),
    M("framing_rate", "Strike rate added", "Defence", "pct", den="called", stab="c_frame", scope="model", desc="Catchers: strikes added per called pitch."),
    # value (builder C)
    M("war", "WAR", "Value", "war", scope="model", desc="Bullpen WAR (regressed): (batting + baserunning + fielding + framing + "
      "positional + league + replacement runs) / runs per win, with batting from regressed park-neutral xwOBA+."),
    M("war_results", "WAR (results)", "Value", "war", scope="model",
      desc="Bullpen WAR with results-based batting runs (wOBA, park-adjusted) in place of the regressed xwOBA+ batting runs."),
    M("rar", "RAR", "Value", "1", scope="model", desc="Runs above replacement."),
    M("batting_runs", "Batting runs", "Value", "1", scope="model",
      desc="True-talent batting runs: park-neutral xwOBA+ regressed with the stabilisation PA, against the league, per PA."),
    M("batting_results", "Batting runs (results)", "Value", "1", scope="model", desc="Results-based batting runs (wOBA, park-adjusted)."),
    M("pos_runs", "Positional runs", "Value", "1", scope="model", desc="Positional adjustment prorated by games at each position."),
    M("repl_runs", "Replacement runs", "Value", "1", scope="model", desc="Replacement level credited per PA."),
    M("war_600", "WAR/600", "Value", "1", den="pa", k=600, scope="model", desc="WAR per 600 plate appearances."),
    # projections (builder D)
    M("proj_woba", "Projected wOBA", "Projection", "3", scope="model",
      desc="Next-season wOBA from the component projections (each skill regressed at its own rate, aging applied)."),
    M("proj_iso", "Projected ISO", "Projection", "3", scope="model", desc="Projected isolated power."),
    M("proj_babip", "Projected BABIP", "Projection", "3", scope="model", desc="Projected BABIP."),
    M("proj_k_pct", "Projected K%", "Projection", "pct", lower=True, scope="model", desc="Projected strikeout rate."),
    M("proj_bb_pct", "Projected BB%", "Projection", "pct", scope="model", desc="Projected walk rate."),
    M("proj_hr_pa", "Projected HR/PA", "Projection", "pct", scope="model", desc="Projected home runs per PA."),
    M("pre_woba", "Preseason projected wOBA", "Projection", "3", scope="model",
      desc="The projection made before this season from earlier seasons only."),
]
KEYS = [m["key"] for m in METRICS]


def _rate(a, b):
    return an.div(a, b)


def _woba(num, den):
    return an.div(num, den)


def _official_lines(ctx: SeasonContext) -> dict:
    """{pid: official hitting line} for the season from the Stats API cache (analytics/mlbapi.py; no network here: the
    fantasy layer refreshes it), or {} when none is on file."""
    try:
        from oddsmarkets.baseball.analytics import mlbapi
        return mlbapi.season_lines(ctx.level, ctx.season, "hitting") or {}
    except Exception:                                            # noqa: BLE001 - a missing / unreadable cache
        return {}


def build(ctx: SeasonContext) -> dict:
    A = ctx.agg()
    bat = A.get("bat") if A else None
    if bat is None or not len(bat):
        return {"ok": False, "reason": f"no pitch data for {ctx.level} {ctx.season}", "level": ctx.level, "season": ctx.season}
    ex = A.get("bat_ex", pd.DataFrame())
    last = A.get("bat_last", pd.Series(dtype=object))
    war = CT.lookup(ctx.model("war").get("batters"))
    rpw = an.fnum((ctx.model("war").get("constants") or {}).get("rpw"))
    xw = CT.lookup(ctx.model("xwoba").get("hitters"))
    sw = CT.lookup(ctx.model("swing").get("hitters"))
    bt = CT.lookup(ctx.model("battrack").get("hitters"))
    fld = CT.lookup(ctx.model("catchprob").get("fielders"))
    frm = CT.lookup(ctx.model("framing").get("catchers"))
    proj = (ctx.model("proj_next").get("hitters") or {}) if ctx.full else {}
    pre = (ctx.model("proj_pre").get("hitters") or {}) if ctx.full else {}
    spr = CT.leaderboard("sprint_speed", ctx.season)
    arm = CT.leaderboard("arm-strength", ctx.season)
    oaa_sv = CT.leaderboard("outs_above_average", ctx.season)
    xwc = _xwobacon(ctx)
    clutch = _clutch(ctx)
    tg = ctx.team_games() or 1
    official = _official_lines(ctx)
    rows: dict[str, dict] = {}
    role_of: dict[str, str] = {}
    for pid, r in bat.iterrows():
        pa = float(r["pa"])
        if pa < 1:
            continue
        info = ctx.players.get(pid) or {}
        wr = war.get(pid) or {}
        pos = CT.pos_of(ctx, pid, wr.get("pos"))
        if (info.get("pos") == "P" and pa < 50 and pos in (None, "P")):
            continue
        v: dict[str, Any] = {}
        ab = float(r["ab"])
        h = float(r["h"])
        bbs = float(r["bb"] + r["ibb"])
        v.update(g=_g(ex, pid), pa=pa, ab=ab, h=h, b1=r["b1"], b2=r["b2"], b3=r["b3"], hr=r["hr"], bb=r["bb"], ibb=r["ibb"],
                 hbp=r["hbp"], so=r["k"], sf=r["sf"], sh=r["sh"], gidp=r["gidp"])
        v["avg"] = _rate(h, ab)
        obp_den = ab + bbs + r["hbp"] + r["sf"]
        v["obp"] = _rate(h + bbs + r["hbp"], obp_den)
        v["slg"] = _rate(r["tb"], ab)
        v["ops"] = (v["obp"] or 0) + (v["slg"] or 0) if v["obp"] is not None and v["slg"] is not None else None
        v["iso"] = v["slg"] - v["avg"] if v["slg"] is not None and v["avg"] is not None else None
        v["babip"] = _rate(h - r["hr"], ab - r["k"] - r["hr"] + r["sf"])
        v["woba"] = _woba(r["w_num"], r["w_den"])
        v["k_pct"] = _rate(r["k"], pa)
        v["bb_pct"] = _rate(bbs, pa)
        v["bb_k"] = _rate(bbs, r["k"])
        v["hr_pa"] = _rate(r["hr"], pa)
        v["xbh_pa"] = _rate(r["b2"] + r["b3"] + r["hr"], pa)
        v["hbp_pct"] = _rate(r["hbp"], pa)
        # discipline
        v["swing_pct"] = _rate(r["swing"], r["pitches"])
        v["zone_pct"] = _rate(r["in_zone"], r["zone_n"])
        v["z_swing_pct"] = _rate(r["z_swing"], r["in_zone"])
        v["chase_pct"] = _rate(r["o_swing"], r["out_zone"])
        v["contact_pct"] = _rate(r["contact"], r["swing"])
        v["z_contact_pct"] = _rate(r["z_contact"], r["z_swing"])
        v["o_contact_pct"] = _rate(r["o_contact"], r["o_swing"])
        v["whiff_pct"] = _rate(r["whiff"], r["swing"])
        v["swstr_pct"] = _rate(r["whiff"], r["pitches"])
        v["cstr_pct"] = _rate(r["called"], r["pitches"])
        v["csw_pct"] = _rate(r["csw"], r["pitches"])
        v["fp_swing_pct"] = _rate(r["fp_swing"], r["fp"])
        v["fp_strike_pct"] = _rate(r["fp_strike"], r["fp"])
        v["p_pa"] = _rate(r["pitches_all"], pa)
        v["s2_whiff_pct"] = _rate(r["s2_whiff"], r["s2_swing"])
        v["heart_swing_pct"] = _rate(r["heart_sw"], r["heart_n"])
        v["chase_zone_swing_pct"] = _rate(r["chase_sw"], r["chase_n"])
        v["waste_swing_pct"] = _rate(r["waste_sw"], r["waste_n"])
        v["shadow_swing_pct"] = _rate(r["shadow_sw"], r["shadow_n"])
        # decisions
        s = sw.get(pid) or {}
        if s:
            v["dv"] = CT.g(s, "dv_c")
            v["dv100"] = CT.g(s, "dv_c100")
            v["dv_zone"] = CT.g(s, "dv_zone")
            v["dv_chase"] = CT.g(s, "dv_chase")
            v["x_swing_pct"] = CT.g(s, "x_swing")
            if CT.g(s, "swing") is not None and CT.g(s, "x_swing") is not None:
                v["swing_oe"] = CT.g(s, "swing") - CT.g(s, "x_swing")
            v["should_swing_pct"] = CT.g(s, "should_swing")
            v["should_take_pct"] = CT.g(s, "should_take")
        # contact
        v["ev"] = _rate(r["ev_sum"], r["ev_n"])
        v["ev90"] = _exv(ex, pid, "ev90")
        v["ev_max"] = _exv(ex, pid, "ev_max")
        v["la"] = _rate(r["la_sum"], r["la_n"])
        if r["la_n"] >= 2:
            var = r["la_sq"] / r["la_n"] - (r["la_sum"] / r["la_n"]) ** 2
            v["la_sd"] = float(np.sqrt(max(var, 0.0)))
        bip = float(r["bip"])
        v["hard_pct"] = _rate(r["hard"], r["ev_n"])
        v["barrel_pct"] = _rate(r["barrel"], r["lsa_n"])
        v["barrel_pa"] = _rate(r["barrel"], pa)
        v["sweet_pct"] = _rate(r["sweet"], r["la_n"])
        for k in ("solid", "flare", "under", "topped", "weak"):
            v[f"{k}_pct"] = _rate(r[k], r["lsa_n"])
        v["hr_dist"] = _rate(r["hr_dist_sum"], r["hr_dist_n"])
        v["fb_dist"] = _rate(r["fb_dist_sum"], r["fb_dist_n"])
        v["dist_max"] = _exv(ex, pid, "dist_max")
        # expected
        x = xw.get(pid) or {}
        v["xwoba_plus"] = CT.g(x, "xwoba")
        v["xwoba_n"] = CT.g(x, "xwoba_n")
        v["xwoba_savant"] = _rate(r["xw_num"], r["w_den"])
        if v["xwoba_plus"] is not None and v["xwoba_savant"] is not None:
            v["xwoba_diff"] = v["xwoba_plus"] - v["xwoba_savant"]
        if v["xwoba_plus"] is not None and v["woba"] is not None:
            v["woba_minus_x"] = v["woba"] - v["xwoba_plus"]
        v["xba"] = _rate(r["xba_num"], ab)
        v["xslg"] = _rate(r["xslg_num"], ab)
        v["xwobacon_plus"] = xwc.get(pid)
        v["xwobacon_savant"] = _rate(r["xwc_sum"], r["xwc_n"])
        # batted ball
        for k, c in (("gb_pct", "gb"), ("ld_pct", "ld"), ("fb_pct", "fbb"), ("pu_pct", "pu")):
            v[k] = _rate(r[c], r["bbt_n"])
        for k, c in (("pull_pct", "pull"), ("cent_pct", "cent"), ("oppo_pct", "oppo"), ("pull_air_pct", "pull_air"),
                     ("oppo_air_pct", "oppo_air")):
            v[k] = _rate(r[c], r["spray_n"])
        v["hr_fb"] = _rate(r["hr_fb"], r["fbb"])
        # bat tracking
        b = bt.get(pid) or {}
        v["bat_speed"] = _rate(r["bs_sum"], r["bs_n"])
        v["fast_swing_pct"] = _rate(r["fast"], r["bs_n"])
        v["swing_length"] = _rate(r["sl_sum"], r["sl_n"])
        if b:
            v["bat_speed_adj"] = CT.g(b, "bat_speed_adj")
            v["swing_length_adj"] = CT.g(b, "swing_length_adj")
            v["sq_contact"] = CT.g(b, "sq_contact")
            v["sq_swing"] = CT.g(b, "sq_swing")
            v["sq_oe"] = CT.g(b, "sq_oe")
            v["attack_angle"] = CT.g(b, "attack_angle")
            v["path_mismatch"] = CT.g(b, "abs_mismatch")
            v["path_matched_pct"] = CT.g(b, "matched")
            v["attack_direction"] = CT.g(b, "attack_direction")
            v["swing_tilt"] = CT.g(b, "swing_path_tilt")
            v["intercept_rel"] = CT.g(b, "intercept_y_rel")
        # by pitch family / velocity / zone
        for f in ("fb", "br", "os"):
            v[f"{f}_xwoba"] = _rate(r[f"{f}_xw"], r[f"{f}_den"])
            v[f"{f}_whiff_pct"] = _rate(r[f"{f}_wh"], r[f"{f}_sw"])
            v[f"{f}_rv100"] = 100 * r[f"{f}_rv"] / r[f"{f}_n"] if r[f"{f}_n"] else None
            v[f"{f}_chase_pct"] = _rate(r[f"{f}_osw"], r[f"{f}_oz"])
        for bnd in ("v95", "v90", "vlo"):
            v[f"{bnd}_xwoba"] = _rate(r[f"{bnd}_xw"], r[f"{bnd}_den"])
            v[f"{bnd}_whiff_pct"] = _rate(r[f"{bnd}_wh"], r[f"{bnd}_sw"])
        for z in ("heart", "shadow", "chase", "waste"):
            v[f"{z}_rv100"] = 100 * r[f"{z}_rv"] / r[f"{z}_n"] if r[f"{z}_n"] else None
        # platoon
        v["woba_vl"] = _rate(r["vlhp_wn"], r["vlhp_wd"])
        v["woba_vr"] = _rate(r["vrhp_wn"], r["vrhp_wd"])
        v["xwoba_vl"] = _rate(r["vlhp_xn"], r["vlhp_wd"])
        v["xwoba_vr"] = _rate(r["vrhp_xn"], r["vrhp_wd"])
        v["k_pct_vl"] = _rate(r["vlhp_k"], r["vlhp_pa"])
        v["k_pct_vr"] = _rate(r["vrhp_k"], r["vrhp_pa"])
        v["pa_vl_share"] = _rate(r["vlhp_pa"], pa)
        if v["woba_vl"] is not None and v["woba_vr"] is not None:
            v["platoon_gap"] = abs(v["woba_vl"] - v["woba_vr"])
        # clutch
        c = clutch.get(pid) or {}
        v.update({k: c.get(k) for k in ("wpa", "wpa_li", "clutch", "pli", "re24", "re24_pa", "woba_hilev")})
        # baserunning
        sp = spr.get(pid) or {}
        v["sprint_speed"] = CT.g(sp, "sprint_speed")
        v["hp_to_1b"] = CT.g(sp, "hp_to_1b")
        v["bsr"] = CT.g(wr, "baserunning")
        v["wsb"] = CT.g(wr, "wsb")
        v["ebt_runs"] = CT.g(wr, "ebt_runs")
        ol = official.get(str(pid))
        if ol is not None:            # the pitch-data estimate counts wild pitches and indifference as steals (+2.6 a player)
            v["sb"], v["cs"] = an.fnum(ol.get("sb")), an.fnum(ol.get("cs"))
        else:
            v["sb"] = CT.g(wr, "sb_est")
            v["cs"] = CT.g(wr, "cs_est")
        # defence
        fr = fld.get(pid) or {}
        if fr:
            v["oaa"] = CT.g(fr, "oaa")
            v["fielding_runs"] = CT.g(fr, "runs")
            v["sra"] = CT.g(fr, "sra")
            v["oaa_back"] = CT.g(fr, "oaa_back")
            v["oaa_in"] = CT.g(fr, "oaa_in")
            v["oaa_3b"] = CT.g(fr, "oaa_toward_3b")
            v["oaa_1b"] = CT.g(fr, "oaa_toward_1b")
        v["oaa_savant"] = CT.g(oaa_sv.get(pid), "outs_above_average")
        v["arm"] = CT.g(arm.get(pid), "arm_overall")
        fm = frm.get(pid) or {}
        if fm:
            v["framing_runs"] = CT.g(fm, "runs")
            v["framing_rate"] = CT.g(fm, "strike_rate_added")
        # value
        if wr:
            v["war"] = CT.g(wr, "war")
            if v["war"] is not None and CT.g(wr, "bat_results") is not None and CT.g(wr, "batting") is not None and rpw:
                v["war_results"] = v["war"] + (CT.g(wr, "bat_results") - CT.g(wr, "batting")) / rpw
            v["rar"] = CT.g(wr, "rar")
            v["batting_runs"] = CT.g(wr, "batting")
            v["batting_results"] = CT.g(wr, "bat_results")
            v["pos_runs"] = CT.g(wr, "pos_runs")
            v["repl_runs"] = CT.g(wr, "replacement")
            if v["war"] is not None:
                v["war_600"] = 600 * v["war"] / pa
        # projections
        pj = proj.get(pid) or {}
        if pj:
            v["proj_woba"] = CT.g(pj, "wOBA")
            v["proj_iso"] = CT.g(pj, "ISO")
            v["proj_babip"] = CT.g(pj, "BABIP")
            rates = ((pj.get("rates") or {}).get("all")) or []
            if len(rates) >= 7:
                v["proj_k_pct"], v["proj_bb_pct"], v["proj_hr_pa"] = rates[0], rates[1] + 0.0, rates[6]
        if pre.get(pid):
            v["pre_woba"] = CT.g(pre[pid], "wOBA")
        n = {"pa": pa, "bip": bip, "pitches": float(r["pitches"]), "swings": float(r["swing"]), "bat_swings": float(r["bs_n"]),
             "oz": float(r["out_zone"]), "iz": float(r["in_zone"]), "pa_l": float(r["vlhp_pa"]), "pa_r": float(r["vrhp_pa"]),
             "chances": an.fnum(fr.get("chances")) if fr else None, "called": an.fnum(fm.get("called")) if fm else None,
             "heart": float(r["heart_n"]), "shadow": float(r["shadow_n"]), "chase": float(r["chase_n"]), "waste": float(r["waste_n"]),
             "fb": float(r["fb_n"]), "br": float(r["br_n"]), "os": float(r["os_n"]), "v95": float(r["v95_n"]),
             "v90": float(r["v90_n"]), "vlo": float(r["vlo_n"])}
        team_abbr = last.get(pid) if len(last) else None
        rows[pid] = {"name": ctx.name(pid), "team": ctx.tid(team_abbr), "team_abbr": team_abbr, "pos": pos,
                     "bats": info.get("bats"), "age": an.age_on(info.get("dob") or (ctx.people.get(pid) or {}).get("birth"), ctx.season),
                     "pa": int(pa), "qualified": pa >= QUAL_PA_PER_G * tg, "values": v, "n": n}
        role_of[pid] = CT.POS_GROUP.get(pos or "", "DH")
    ref_pa = max(FLOORS["pa"], REF_PA_PER_G * tg)
    reference = [p for p, r in rows.items() if r["pa"] >= ref_pa]
    if len(reference) < 20:                     # early season / small samples: the top PA hitters
        reference = sorted(rows, key=lambda p: -rows[p]["pa"])[:max(20, len(rows) // 3)]
    means = CT.finish(ctx, rows, METRICS, reference, role_of, FLOORS)
    for r in rows.values():
        r["n"] = {k: (int(v) if v is not None else None) for k, v in r["n"].items()}
    return {**CT.season_meta(ctx), "kind": "hitter", "metrics": [an.public_metric(m) for m in METRICS], "players": rows,
            "reference": {"rule": f"PA >= {REF_PA_PER_G} per team game (floor {FLOORS['pa']})", "n": len(reference),
                          "min_pa": round(ref_pa), "means": {k: an.rnd(v, 4) for k, v in means.items()}},
            "floors": FLOORS, "roles": sorted(set(role_of.values()))}


def _g(ex: pd.DataFrame, pid: str):
    try:
        return int(ex.at[pid, "games"])
    except (KeyError, ValueError, TypeError):
        return None


def _exv(ex: pd.DataFrame, pid: str, col: str):
    try:
        return an.fnum(ex.at[pid, col])
    except KeyError:
        return None


def _xwobacon(ctx: SeasonContext) -> dict[str, float]:
    b = ctx.bip()
    if b is None or not len(b) or "xwoba" not in b:
        return {}
    return b.groupby("batter")["xwoba"].mean().to_dict()


def _clutch(ctx: SeasonContext, by: str = "batter") -> dict[str, dict]:
    """WPA, WPA/LI, clutch, pLI, RE24 per player from builder C's per-PA table (batting side; pitchers get the
    negative)."""
    w = ctx.wpa()
    if w is None or not len(w) or "wpa" not in w:
        return {}
    sign = 1.0 if by == "batter" else -1.0
    d = w[[by, "wpa", "li", "re24", "game_pk", "at_bat_number"]].copy()
    d["wpa"] = sign * d["wpa"].astype(float)
    d["re24"] = sign * d["re24"].astype(float)
    d["li"] = d["li"].astype(float).clip(lower=0.05)
    d["wpa_li"] = d["wpa"] / d["li"]
    g = d.groupby(by)
    t = pd.DataFrame({"wpa": g["wpa"].sum(), "wpa_li": g["wpa_li"].sum(), "pli": g["li"].mean(), "re24": g["re24"].sum(),
                      "n": g.size()})
    t["clutch"] = t["wpa"] / t["pli"] - t["wpa_li"]
    t["re24_pa"] = t["re24"] / t["n"]
    if by == "batter":
        pa = (ctx.agg() or {}).get("pa")
        if pa is not None and len(pa):
            hi = d[d["li"] >= 1.5][["game_pk", "at_bat_number", by]]
            j = hi.merge(pa[["game_pk", "at_bat_number", "woba_value", "woba_denom"]], on=["game_pk", "at_bat_number"], how="left")
            gg = j.groupby(by)
            t["woba_hilev"] = gg["woba_value"].sum() / gg["woba_denom"].sum().replace(0, np.nan)
    return {str(k): {c: an.fnum(v) for c, v in r.items()} for k, r in t.to_dict("index").items()}
