"""
glossary.json: a definition for every player, team and lineup metric in the catalogues and for every
model term the site uses. `{"groups": [{"name","entries":[{key,label,desc,fmt,lower,scope,kind}]}],
"model": [{key,label,group,desc}]}`. A test checks that every catalogue key has an entry.
"""
from __future__ import annotations

from oddsmarkets.basketball import analytics as an

POSS = "Possessions are FGA - OREB + TOV + 0.44 FTA, averaged over both teams; a player's are their on-floor share of each game's."
PBP = " Play-by-play era only (about 2017 on)."

PLAYER = {
    "pts_g": "Points per game played.",
    "pts36": "Points per 36 minutes on the floor.",
    "pts100": "Points per 100 possessions on the floor. " + POSS,
    "ts": "True shooting: PTS / (2 x (FGA + 0.44 FTA)), scoring efficiency counting threes and free throws.",
    "efg": "Effective field-goal percentage: (FGM + 0.5 x 3PM) / FGA, a three worth 1.5 twos.",
    "fg": "Field goals made / attempted.",
    "fg2": "Two-point field goals made / attempted.",
    "fg3": "Three-pointers made / attempted.",
    "ft": "Free throws made / attempted.",
    "usg": "Usage: share of the team's possessions the player ends with a shot, free throws or a turnover while on the floor: "
           "(FGA + 0.44 FTA + TOV) / on-floor team (FGA + 0.44 FTA + TOV).",
    "ts_add": "True-shooting points added per 100 possessions: (TS - league TS) x 2 x (FGA + 0.44 FTA) x 100 / possessions.",
    "pps": "Points per field-goal attempt (free throws excluded).",
    "ftr": "Free-throw rate: FTA / FGA, how often the player gets to the line.",
    "tpar": "Share of the player's field-goal attempts that are threes.",
    "fta100": "Free-throw attempts per 100 possessions.",
    "tpm_g": "Three-pointers made per game.",
    "pox100": "Shot-making: actual points minus expected points (xPTS) per 100 field-goal attempts. Positive = the player makes harder "
              "shots than the league would from the same spots." + PBP,
    "xpps": "Shot quality: average expected points per field-goal attempt from the xPTS model (location, angle, shot type, "
            "putback, transition, clock, score). Higher = easier shots." + PBP,
    "and1_100": "And-ones per 100 possessions: made field goals followed by a lone free throw by the shooter." + PBP,
    "unassisted_share": "Share of the player's made field goals without an assist (self-created)." + PBP,
    "rim_freq": "Share of the player's shots at the rim (under 4 ft)." + PBP,
    "rim_fg": "FG% at the rim." + PBP,
    "rim_fg_diff": "Rim FG% minus the league's rim FG%." + PBP,
    "smid_freq": "Share of the player's shots that are short mid-range twos (4-14 ft)." + PBP,
    "smid_fg": "FG% on short mid-range twos." + PBP,
    "smid_fg_diff": "Short mid-range FG% minus the league's." + PBP,
    "lmid_freq": "Share of the player's shots that are long twos (14 ft out to the arc)." + PBP,
    "lmid_fg": "FG% on long twos." + PBP,
    "lmid_fg_diff": "Long-two FG% minus the league's." + PBP,
    "c3_freq": "Share of the player's shots that are corner threes." + PBP,
    "c3_fg": "Corner-three FG%." + PBP,
    "c3_fg_diff": "Corner-three FG% minus the league's." + PBP,
    "ab3_freq": "Share of the player's shots that are above-the-break threes (heaves included)." + PBP,
    "ab3_fg": "Above-the-break three FG%." + PBP,
    "ab3_fg_diff": "Above-the-break three FG% minus the league's." + PBP,
    "avg_dist": "Average shot distance in feet from the rim." + PBP,
    "dunk_freq": "Share of the player's shots that are dunks." + PBP,
    "layup_freq": "Share of the player's shots that are layups or tip-ins." + PBP,
    "float_hook_freq": "Share of the player's shots that are floaters or hooks." + PBP,
    "jumper_freq": "Share of the player's shots that are standard jump shots." + PBP,
    "pullup_freq": "Share of the player's shots that are pull-up jumpers." + PBP,
    "iso_freq": "Share of the player's shots that are step-backs, fadeaways or turnarounds." + PBP,
    "assisted_share": "Share of the player's made field goals that were assisted." + PBP,
    "putback_freq": "Share of the player's shots that are putbacks (within 3 s of an offensive rebound)." + PBP,
    "transition_freq": "Share of the player's shots in transition (within 6 s of a possession that began on a live rebound or steal)." + PBP,
    "ast_g": "Assists per game.",
    "ast36": "Assists per 36 minutes.",
    "ast100": "Assists per 100 possessions.",
    "ast_pct": "Assist percentage: share of team-mates' field goals the player assisted while on the floor: AST / (on-floor team FGM - FGM).",
    "ast_usg": "Assist % divided by usage %: playmaking relative to how much the player has the ball.",
    "ast_tov": "Assists per turnover.",
    "ast_pts100": "Points from the shots the player assisted (2 or 3 each) per 100 possessions." + PBP,
    "ast_rim_share": "Share of the player's assists that led to rim makes." + PBP,
    "ast_3_share": "Share of the player's assists that led to made threes." + PBP,
    "tov_g": "Turnovers per game.",
    "tov100": "Turnovers per 100 possessions.",
    "tov_pct": "Turnover percentage: TOV / (FGA + 0.44 FTA + TOV), turnovers per play the player ends.",
    "live_tov_share": "Share of the player's turnovers that were steals (live-ball turnovers lead to opponent transition)." + PBP,
    "off_foul100": "Offensive fouls (charges, illegal screens) per 100 possessions." + PBP,
    "reb_g": "Rebounds per game.",
    "reb36": "Rebounds per 36 minutes.",
    "orb_pct": "Offensive rebound %: share of available offensive rebounds the player grabbed while on the floor.",
    "drb_pct": "Defensive rebound %: share of available defensive rebounds the player grabbed while on the floor.",
    "trb_pct": "Total rebound %.",
    "oreb100": "Offensive rebounds per 100 possessions.",
    "dreb100": "Defensive rebounds per 100 possessions.",
    "putback100": "Made putbacks per 100 possessions." + PBP,
    "stl_g": "Steals per game.",
    "blk_g": "Blocks per game.",
    "stl_pct": "Steal %: steals per opponent possession while on the floor.",
    "blk_pct": "Block %: share of opponent two-point attempts the player blocked while on the floor.",
    "stl100": "Steals per 100 possessions.",
    "blk100": "Blocks per 100 possessions.",
    "pf100": "Personal fouls per 100 possessions.",
    "hpm_d": "Defensive Hardwood Plus-Minus: points per 100 possessions the player saves the team on defence (see HPM).",
    "rapm_d": "Defensive RAPM: ridge-regressed points per 100 the player takes off opponents, from lineup stints." + PBP,
    "box_d": "Defensive box impact: the defensive part of the regression of RAPM on box-score rates.",
    "opp_rim_fg_on": "Opponents' FG% at the rim while the player is on the floor (10+ attempts)." + PBP,
    "opp_xpps_on": "Opponents' expected points per shot while the player is on the floor: the quality of shots the player's defence allows." + PBP,
    "opp_fg3_on": "Opponents' three-point % while the player is on the floor (10+ attempts)." + PBP,
    "on_drtg": "Team points allowed per 100 possessions with the player on the floor." + PBP,
    "dwpa": "Defensive win probability added: the player's share of the win-probability swing on the other team's plays (blocks, steals)." + PBP,
    "hpm": "Hardwood Plus-Minus: points per 100 possessions the player adds to the team's margin relative to an average player. A "
           "precision-weighted blend of box impact (the prior) and RAPM (the evidence), offence and defence separately.",
    "hpm_o": "Offensive HPM: points per 100 possessions the player adds to the team's offence.",
    "hpm_se": "Standard error of HPM: the uncertainty left after combining box impact and RAPM.",
    "rapm": "Regularised adjusted plus-minus: a ridge regression of every stint's scoring on the ten players on the floor, with "
            "home court and last season's estimate as the prior." + PBP,
    "rapm_o": "Offensive RAPM." + PBP,
    "box_impact": "Box impact (our BPM): RAPM predicted from per-100 box rates (and, from 2017, shot profile), with a team "
                  "adjustment so the minutes-weighted five add up to the team's rating.",
    "box_o": "Offensive box impact.",
    "hpm_next": "Projected HPM next season: this season's HPM plus the aging curve's expected change at the player's age.",
    "on_net": "Team net rating (points per 100 possessions) with the player on the floor." + PBP,
    "off_net": "Team net rating with the player off the floor." + PBP,
    "on_off": "On-court net rating minus off-court net rating. Noisy and context-dependent (it rewards backups of stars)." + PBP,
    "wpa": "Win probability added: the sum of the changes in the team's win probability on the plays the player took part in "
           "(split between shooter and assister, actor and defender)." + PBP,
    "li_wpa": "WPA divided by each play's leverage: credit for the plays themselves, not for when they happened." + PBP,
    "pm_g": "Box-score plus-minus per game (team margin while the player played).",
    "pm100": "Box-score plus-minus per 100 possessions.",
    "gmsc": "Hollinger's Game Score per game: PTS + 0.4 FGM - 0.7 FGA - 0.4 (FTA - FTM) + 0.7 ORB + 0.3 DRB + STL + 0.7 AST + "
            "0.7 BLK - 0.4 PF - TOV.",
    "clutch_min": "Minutes in clutch time (last 5:00 of the 4th quarter or overtime, margin within 5)." + PBP,
    "clutch_pts": "Points in clutch time." + PBP,
    "clutch_ts": "True shooting % in clutch time." + PBP,
    "clutch_net": "Team net rating per 100 possessions with the player on the floor in clutch time." + PBP,
    "clutch_wpa": "WPA on clutch-time plays." + PBP,
    "clutch_poss": "Clutch possessions with the player on the floor (offence and defence averaged)." + PBP,
    "gp": "Games played.",
    "gs": "Games started.",
    "min": "Minutes played.",
    "mpg": "Minutes per game played.",
    "start_share": "Share of the games played that were starts.",
    "avail": "Share of the (main) team's games the player played.",
    "games_missed": "Games of the main team the player did not play.",
    "injury_dnp": "Games in which the player was listed as out with an injury, illness or rest reason.",
    "gmsc_sd": "Standard deviation of the player's Game Score: lower = more consistent.",
    "b2b_gmsc_diff": "Average Game Score on the second night of a back-to-back minus on other nights.",
    "pts_share": "Share of the team's points in the games the player played.",
    "min_share": "Share of the team's available player-minutes in the games the player played.",
    "ast_share": "Share of the team's assists in the games the player played.",
    "reb_share": "Share of the team's rebounds in the games the player played.",
    "team_win_pct": "The main team's win % this season.",
    "team_net": "The main team's model net rating (opponent- and home-adjusted).",
    "lineup_net": "Net rating of the best five-man unit the player played in (25+ possessions)." + PBP,
    "age": "Age at the end of the regular season (from ESPN's date of birth).",
    "seasons": "Seasons in the league up to and including this one (from 1997 on, our stores).",
    "career_hpm": "Minutes-weighted average HPM over the player's seasons to date.",
    "hpm_delta": "HPM this season minus last season.",
}

TEAM = {
    "ortg": "Points scored per 100 possessions.", "drtg": "Points allowed per 100 possessions.", "net": "ORtg - DRtg.",
    "pace": "Possessions per 48 minutes (NBA) or 40 minutes (WNBA).",
    "model_off": "Offensive rating adjusted for opponents and home court, time-decayed (models/ratings.py).",
    "model_def": "Defensive rating (points allowed) adjusted for opponents and home court.",
    "model_net": "Adjusted net rating: the strength the game model and season simulation use.",
    "model_se": "Standard error of the adjusted net rating.", "elo": "Game Elo after the team's latest game (1997 on).",
    "net_7d_change": "Change in the adjusted net rating over the last 7 days.",
    "w": "Wins (regular season, NBA Cup group games included).", "l": "Losses.", "win_pct": "Wins / games.",
    "pyth_wins": "Pythagorean wins: games x PF^k / (PF^k + PA^k), k = 14 NBA / 13 WNBA.",
    "luck": "Wins minus Pythagorean wins: close-game fortune.", "home_win_pct": "Win % at home.", "away_win_pct": "Win % away.",
    "close_win_pct": "Win % in games decided by 5 points or fewer.", "mov": "Average margin of victory.",
    "efg": "Effective FG%: (FGM + 0.5 3PM) / FGA.", "tov_pct": "Turnovers per possession.",
    "orb_pct": "Offensive rebounds / (own ORB + opponent DRB).", "ftr": "Free-throw rate as a Four Factor: FTM / FGA.",
    "opp_efg": "Opponents' effective FG%.", "opp_tov_pct": "Opponent turnovers per possession (forced turnovers).",
    "drb_pct": "Defensive rebounds / (own DRB + opponent ORB).", "opp_ftr": "Opponents' FTM / FGA.",
    "fg3": "Three-point %.", "tpar": "Share of field-goal attempts that are threes.", "fg2": "Two-point %.", "ft": "Free-throw %.",
    "ast_rate": "Assists per made field goal.", "opp_fg3": "Opponents' three-point %.", "opp_tpar": "Opponents' three-point attempt rate.",
    "stl_pct": "Steals per opponent possession.", "blk_pct": "Blocks per opponent two-point attempt.",
    "xpps": "Expected points per shot from the xPTS model: offensive shot quality." + PBP,
    "pox100": "Points over expected per 100 shots: shot-making or shooting luck." + PBP,
    "opp_xpps": "Opponents' expected points per shot: the shot quality the defence allows." + PBP,
    "opp_pox100": "Opponents' points over expected per 100 shots: positive = opponents shot better than expected." + PBP,
    "rim_freq": "Share of shots at the rim." + PBP, "mid_freq": "Share of shots that are non-rim twos." + PBP,
    "c3_freq": "Share of shots that are corner threes." + PBP, "opp_rim_freq": "Share of opponents' shots at the rim." + PBP,
    "opp_three_freq": "Share of opponents' shots that are threes." + PBP, "avg_dist": "Average shot distance (ft)." + PBP,
    "tr_share": "Share of possessions in transition (live-ball start, first action within 6 s)." + PBP,
    "tr_ppp": "Points per transition possession." + PBP, "hc_ppp": "Points per half-court possession." + PBP,
    "ato_ppp": "Points per possession straight after a timeout (10+ possessions)." + PBP,
    "pts_paint_g": "Points in the paint per game (ESPN).", "pts_fb_g": "Fast-break points per game (ESPN).",
    "pts_off_tov_g": "Points off turnovers per game (ESPN).",
    "clutch_net": "Net rating in clutch time (last 5:00 of the 4th / OT within 5 points)." + PBP,
    "clutch_poss": "Clutch possessions played." + PBP, "clutch_games": "Games that reached clutch time." + PBP,
    "depth": "Players averaging 10+ minutes.", "starter_min_share": "Share of minutes played by the night's starters.",
    "continuity": "Share of minutes played by players who were on the team last season.",
    "top_lineup_share": "Share of possessions played by the most-used five." + PBP,
    "best_lineup_net": "Net rating of the best five-man unit with 25+ possessions." + PBP, "players_used": "Players who have played.",
    "sos": "Strength of schedule: average adjusted net rating of opponents played.",
    "sos_remaining": "Average adjusted net rating of the opponents still to play.", "home_net": "Net rating at home.",
    "away_net": "Net rating away.", "b2b_net": "Net rating on the second night of back-to-backs (3+ games).",
    "rest_net": "Net rating with at least one day of rest.",
    "inj_adj_net": "Adjusted net rating minus the impact of players listed out: (HPM - replacement) x expected minutes share.",
    "lead_changes_g": "Lead changes per game (ESPN).", "exp_w": "Projected final wins (season simulation).",
    "p_playoffs": "Probability of reaching the playoffs (after the play-in where there is one).",
    "p_conf": "Probability of reaching the Finals.", "p_title": "Probability of winning the title (season simulation).",
    "p_title_market": "Market title probability (reference): two-sided prediction-market midpoints with the margin removed.",
    "title_edge": "Model title probability minus the market's.",
}

LINEUP = [
    {"key": "poss", "label": "Possessions", "desc": "Possessions played: the average of offensive and defensive possessions.", "fmt": "1"},
    {"key": "net", "label": "Net rating", "desc": "Points scored minus allowed per 100 possessions with the unit on the floor.", "fmt": "1"},
    {"key": "ortg", "label": "Offensive rating", "desc": "Points per 100 offensive possessions.", "fmt": "1"},
    {"key": "drtg", "label": "Defensive rating", "desc": "Points allowed per 100 defensive possessions.", "fmt": "1"},
    {"key": "hpm_sum", "label": "HPM sum", "desc": "The unit's summed HPM (2- and 3-man units fill the other slots with the team's "
                                                    "minutes-weighted average HPM): what the players' impact predicts.", "fmt": "2"},
    {"key": "shrunk_net", "label": "Shrunk net", "desc": "(net x poss + 150 x HPM sum) / (poss + 150): the net rating pulled towards "
                                                         "the HPM sum, by less as possessions accumulate.", "fmt": "2"},
]

MODEL = [
    ("ratings", "Team ratings", "Ratings", "Offence and defence per 100 possessions from a ridge regression of every game's scoring on "
     "both teams, home court and a time decay (half-life 75 days NBA / 45 WNBA), shrunk to a preseason prior; pace likewise."),
    ("rating_path", "Rating path", "Ratings", "A Kalman filter on the net rating vector: the estimate and its standard error after "
     "each game."),
    ("preseason_prior", "Preseason prior", "Ratings", "Last season's net rating times the fitted season-to-season carry-over slope, "
     "blended with the roster's minutes-weighted HPM."),
    ("game_model", "Game model", "Games", "Expected margin = rating difference x pace + home court + rest + back-to-back + travel + "
     "time zones + altitude + injuries; margin ~ Normal(mu, sigma) with sigma fitted walk-forward. Gives win probability, "
     "expected margin and expected total."),
    ("spread_to_p", "Market probability", "Games", "A DraftKings spread s converts to P(home) = Phi(-s / sigma_m), sigma_m the sd "
     "of margin + spread over history; moneylines have the margin removed; prediction markets use two-sided midpoints."),
    ("season_sim", "Season simulation", "Season", "The remaining schedule played 20,000 times with correlated team strength (a "
     "season-level draw and a weekly random walk per team), the real tiebreakers, the play-in and best-of series."),
    ("magic", "Magic number", "Season", "Wins by the team plus losses by its rival that clinch a target, assuming the team loses "
     "the tiebreak; tragic is the mirror for elimination."),
    ("elo", "Elo", "Ratings", "FiveThirtyEight-style game Elo from 1997: K = 20, margin-of-victory multiplier, home advantage "
     "(100 NBA / 90 WNBA) and a 25 % (30 % WNBA) regression to the mean between seasons."),
    ("xpts", "xPTS", "Shots", "A penalised logistic model of make probability on distance and angle splines, zone, shot type, "
     "putback, transition, period, clock and margin (not whether it was assisted: assists exist only on makes); "
     "xPTS = P(make) x value."),
    ("rapm", "RAPM", "Impact", "Ridge regression of stint scoring per 100 on the ten players (offence and defence), lambda by "
     "cross-validation, centred on last season's estimate x 0.8."),
    ("box_impact", "Box impact", "Impact", "RAPM regressed on box-score rates (and shot profile), applied to every season, with a "
     "team adjustment."),
    ("hpm", "HPM", "Impact", "Hardwood Plus-Minus = (box / tau^2 + RAPM / se^2) / (1 / tau^2 + 1 / se^2), offence and defence "
     "separately: leans on RAPM as possessions accumulate."),
    ("projection", "Projections", "Impact", "Per-36 rates exponentially weighted over recent games and regressed to the position "
     "mean (250 pseudo-minutes), expected minutes and availability, and an aging curve."),
    ("win_probability", "Win probability", "Games", "logit P(home) from margin, time left, possession and the pregame spread with "
     "time-varying coefficients (scaled by 1 / sqrt(time left + K)), fitted on past play-by-play."),
    ("wpa", "WPA", "Games", "Each play's change in win probability, credited to its participants (shooter 70 % / assister 30 % "
     "of the acting side; defenders share half when involved)."),
    ("leverage", "Leverage index", "Games", "How much one point moves win probability at that moment, relative to an average "
     "possession."),
    ("clutch", "Clutch time", "Games", "The last 5:00 of the 4th quarter or overtime with the margin within 5 points."),
    ("awards_model", "Award races", "Awards", "A conditional logit on pool-standardised features (HPM value, points, team wins, ...) "
     "fitted on past winners, projected to season end by simulation; the NBA 65-game rule applied."),
    ("percentile", "Percentiles", "Catalogue", "100 = best in the league among qualified players (minutes floor = 20 % of the "
     "season's most minutes), reversed for metrics where lower is better; the pool view compares guards, forwards and centres "
     "separately."),
    ("backtest", "Backtest", "Calibration", "Walk-forward: ratings refitted weekly from games strictly before, coefficients from "
     "earlier seasons only; scored by log-loss and Brier against Elo and the DraftKings spread."),
    ("game_awards", "Game awards", "Games", "Player of the game (Game Score + 20 x WPA), biggest swing (largest WP change), shot "
     "maker (points over xPTS), unluckiest (margin below the shot-quality expectation), stopper (defensive WPA)."),
    ("war", "WAR", "Value", "Wins above replacement: (HPM + 2.0) x possessions on the floor / 100, divided by the points of margin "
     "per win (the game model's margin sd x sqrt(2 pi): 31.1 NBA, 30.1 WNBA). Possessions = minutes x league pace / 48 (40 "
     "WNBA). Replacement = -2.0 per 100, the level the injury and roster models use."),
    ("par", "PAR", "Value", "Points above replacement: (HPM + 2.0) x possessions / 100; PAR per game divides by games played."),
    ("position_groups", "Guards, wings, bigs", "Value", "ESPN lists only G, F and C. Guards are G, bigs are C plus the forwards whose "
     "box profile (rebounds, blocks, rim attempts, few threes and assists) is closer to the centres' than to the guards'; "
     "the other forwards are wings."),
    ("team_grades", "Strengths and needs", "Value", "Each position group and unit (offence, defence, starting five, bench) valued as "
     "projected WAR over a full season from the rotation's rest-of-season HPM and minutes, placed against the league (A top "
     "20 %, B, C, D, F bottom 20 %); trade targets ranked by what each would add in the team's depth chart."),
    ("trade_sim", "Trade simulator", "Value", "Players move; incoming players take minutes from the lowest-rated players at "
     "their position, outgoing minutes go to the next players up (each at most a quarter of a game more, capped at 80 % of a game), any shortfall at replacement. "
     "The change in the rotation's HPM-weighted minutes shifts the team's rating; wins and chances come from re-running the "
     "season simulation at shifted ratings. The salary cap is not checked."),
    ("valuation_v2", "Valuation over four seasons", "Value", "A player's projected WAR over four season slots (the rest of this "
     "season, then full seasons), discounted 0.9 a season: today's rest-of-season HPM aged along the fitted ageing curve, "
     "times depth-chart minutes, availability (games played over two seasons, regressed) and the chance the player is still "
     "playing (logistic in age, HPM and minutes); future seasons floored at replacement; a Monte Carlo band (10th-90th "
     "percentile). Ages from ESPN's athlete records."),
    ("ageing_curve", "Ageing curve", "Value", "The average change in HPM from one season to the next by age, for players with 500+ "
     "minutes in both (weighted by the harmonic mean of the minutes), shrunk towards zero and smoothed over neighbouring ages."),
    ("vorp_position", "VORP at position", "Value", "Value measured from the replacement level of the player's own position group: "
     "the mean rate of the position's next tier of playing time after the league's rotations. Scarcity = the league "
     "replacement level (-2.0) minus the position's."),
    ("trade_rating", "Trade rating", "Moves", "Each side of a trade valued three ways in four-season WAR: at the time (no "
     "hindsight: the last completed season's HPM aged and shrunk, minutes before the date), realised since (that season's HPM "
     "x the player's possessions for the new team after the date) and today's view (realised + today's projection of the window "
     "while the player is still there). Grade = share of the deal's value received: A >= 65 %, B >= 55 %, C 45-55 %, D >= 35 %, F."),
    ("pick_curve", "Pick-value curve", "Moves", "Expected WAR of each draft slot over its first four seasons (each floored at "
     "zero, discounted 0.9), from our value of every pick ESPN lists (a pick who never played counts zero), made "
     "non-increasing and smoothed. Future picks of unknown slot count their round's mean; swaps and considerations zero."),
    ("fantasy_projection", "Fantasy projection", "Fantasy", "Per game: per-minute rates (impact model) x depth-chart minutes "
     "(injury report applied, usage redistributed while teammates are out) x opponent pace and category defence x rest "
     "factors, blended 50/50 (from 20 games) with the season-to-date line; rest of season and weeks sum the schedule "
     "with the chance of playing."),
    ("nine_cat", "9-category value", "Fantasy", "Sum of per-category z-scores (PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO) against "
     "the top 156 players; FG% and FT% weighted by attempts, turnovers negative; punting drops a category."),
    ("shooting_luck", "Shooting luck", "Fantasy", "Points a game from shooting above or below expectation: points per shot minus "
     "(the shot model's expected points per shot + the player's shot-making over two previous seasons, shrunk), times shots "
     "a game, plus free throws against the player's previous percentage. Negative = buy low, positive = sell high."),
]


def build_glossary() -> dict:
    from oddsmarkets.basketball.analytics import players as PL
    from oddsmarkets.basketball.analytics import teams as TM
    groups: dict[str, list] = {}
    for m in PL.METRICS:
        groups.setdefault(f"Players: {m['group']}", []).append({**m, "desc": PLAYER.get(m["key"]) or m["label"], "kind": "player"})
    for m in TM.METRICS:
        groups.setdefault(f"Teams: {m['group']}", []).append({**m, "desc": TEAM.get(m["key"]) or m["label"], "kind": "team"})
    groups["Lineups"] = [{**e, "lower": False, "scope": "pbp", "group": "Lineups", "kind": "lineup"} for e in LINEUP]
    return {"ok": True, "updated_at": an.now(), "groups": [{"name": k, "entries": v} for k, v in groups.items()],
            "model": [{"key": k, "label": l, "group": g, "desc": d} for k, l, g, d in MODEL]}
