"""
The glossary: one plain-English definition for every player metric in the
catalogue, the team metrics the analytics tab uses, and the model terms the
site leans on. Emitted site-wide as glossary.json and attached to every
METRICS entry (`desc`) so the leaderboards can explain themselves.

This module deliberately imports nothing from players.py at import time:
players.py reads PLAYER_DEFINITIONS to decorate its catalogue, and a module
level import in both directions would be a cycle. `build_glossary` imports the
catalogue when it runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ── player metrics ───────────────────────────────────────────────────────────

_P90 = "per 90 minutes played"

PLAYER_DEFINITIONS: dict[str, str] = {
    # Scoring
    "goals": "Goals scored, penalties included. Own goals are not counted.",
    "goals_90": f"Goals scored {_P90}: goals divided by minutes, times 90. Higher is better.",
    "npg": "Non-penalty goals: goals scored minus goals from the penalty spot.",
    "npg_90": f"Non-penalty goals {_P90}. Higher is better.",
    "xg": "Expected goals: the sum over a player's shots of the chance each one had of being scored, judged from where and how it was taken (Sofascore's model).",
    "xg_90": f"Expected goals {_P90}: how many goals a player's shots are worth every full match. Higher is better.",
    "npxg": "Non-penalty expected goals: xG with 0.79 subtracted for every penalty taken, since a penalty is a chance the player did not create.",
    "npxg_90": f"Non-penalty expected goals {_P90}. Higher is better.",
    "xgot": "Expected goals on target: the value of a player's shots on target after accounting for where in the goal they went. A well-placed shot is worth more than its xG; an off-target shot is worth zero.",
    "xgot_90": f"Expected goals on target {_P90}. Higher is better.",
    "g_minus_xg": "Goals minus expected goals: how many more (or fewer) goals a player has scored than their chances were worth. Positive means finishing above expectation; it tends to fade over a season.",
    "shots": "Shots attempted, on and off target, blocked shots included.",
    "shots_90": f"Shots attempted {_P90}. Higher means a bigger part of the attack.",
    "sot": "Shots on target: shots that would have gone in without a save (blocked shots do not count).",
    "sot_90": f"Shots on target {_P90}.",
    "sot_pct": "Shots on target as a percentage of all shots attempted (denominator: shots). Higher is better.",
    "xg_per_shot": "Expected goals divided by shots: the average quality of the chances a player takes. Higher means closer, better chances.",
    "big_chances_missed": "Big chances (situations where a goal is expected) that the player failed to score. Lower is better.",
    "pens": "Goals scored from the penalty spot, counted from the match incidents.",
    # Creating
    "assists": "Passes that directly led to a goal.",
    "assists_90": f"Assists {_P90}. Higher is better.",
    "xa": "Expected assists: the sum over a player's passes of the chance the shot each one set up had of being scored. It credits the pass regardless of whether the shooter finished.",
    "xa_90": f"Expected assists {_P90}. Higher is better.",
    "key_passes": "Passes that led directly to a shot by a team-mate.",
    "key_passes_90": f"Key passes {_P90}. Higher is better.",
    "big_chances": "Big chances created: passes that put a team-mate in a situation where a goal is expected.",
    "big_chances_90": f"Big chances created {_P90}. Higher is better.",
    # Passing
    "passes": "Passes attempted, successful or not.",
    "passes_90": f"Passes attempted {_P90}: how involved a player is in moving the ball.",
    "pass_pct": "Pass completion: successful passes as a percentage of passes attempted (denominator: passes attempted). Higher is better, but long passers run lower.",
    "opp_half_passes_90": f"Successful passes in the opposition half {_P90}. Higher means more of the player's passing happens in dangerous areas.",
    "long_balls_90": f"Successful long balls {_P90}.",
    "long_ball_pct": "Long-ball accuracy: successful long balls as a percentage of long balls attempted (denominator: long balls attempted). Higher is better.",
    "crosses_90": f"Successful crosses {_P90}.",
    "cross_pct": "Cross accuracy: crosses that found a team-mate as a percentage of crosses attempted (denominator: crosses attempted). Higher is better.",
    # Carrying
    "touches": "Touches of the ball.",
    "touches_90": f"Touches {_P90}: how much of the game goes through the player.",
    "dribbles": "Dribbles completed: take-ons where the player beat the defender.",
    "dribbles_90": f"Dribbles completed {_P90}. Higher is better.",
    "dribble_pct": "Dribble success: completed dribbles as a percentage of dribbles attempted (denominator: dribbles attempted). Higher is better.",
    "carries_90": f"Ball carries {_P90}: sequences of the player moving with the ball at their feet.",
    "prog_carries_90": f"Progressive carries {_P90}: carries that move the ball substantially towards the opponent's goal. Higher is better.",
    "carry_dist_90": f"Metres carried with the ball {_P90}.",
    "dispossessed_90": f"Times tackled off the ball {_P90}. Lower is better.",
    "poss_lost_90": f"Times possession was lost {_P90}, by a bad touch, a failed dribble, a misplaced pass or being tackled. Lower is better.",
    # Defending
    "tackles": "Tackles attempted, won or lost.",
    "tackles_90": f"Tackles attempted {_P90}. Higher means more defensive engagement, which also depends on how often the team is without the ball.",
    "tackle_pct": "Tackle success: tackles won as a percentage of tackles attempted (denominator: tackles attempted). Higher is better.",
    "interceptions": "Interceptions: opposition passes cut out before they reached their target.",
    "interceptions_90": f"Interceptions {_P90}. Higher is better.",
    "clearances_90": f"Clearances {_P90}: the ball kicked or headed clear of danger.",
    "blocks_90": f"Shots blocked by an outfield player {_P90}.",
    "recoveries": "Ball recoveries: loose balls picked up to regain possession.",
    "recoveries_90": f"Ball recoveries {_P90}. Higher is better.",
    "errors": "Errors that led directly to an opposition shot or goal. Lower is better.",
    # Duels
    "duels_won": "Duels won: one-against-one contests for the ball, on the ground or in the air, that the player came out of with possession.",
    "duels_won_90": f"Duels won {_P90}. Higher is better.",
    "duel_pct": "Duel success: duels won as a percentage of duels contested (denominator: duels won plus duels lost). Higher is better.",
    "aerials_won_90": f"Aerial duels won {_P90}. Higher is better.",
    "aerial_pct": "Aerial success: aerial duels won as a percentage of aerial duels contested (denominator: aerials won plus aerials lost). Higher is better.",
    "fouls_90": f"Fouls committed {_P90}. Lower is better.",
    "fouled_90": f"Fouls suffered {_P90}: how often the player draws a foul.",
    # Goalkeeping
    "saves": "Saves made by a goalkeeper.",
    "saves_90": f"Saves {_P90}. A high number says as much about the defence in front of the keeper as about the keeper.",
    "save_pct": "Save percentage: saves as a percentage of shots on target faced (denominator: saves plus goals conceded). Higher is better.",
    "goals_prevented": "Goals prevented: the expected goals on target a keeper faced minus the goals actually conceded. Positive means the keeper has saved more than an average keeper would have from the same shots.",
    "goals_prevented_90": f"Goals prevented {_P90}. Higher is better.",
    "conceded": "Goals conceded while the keeper was on the pitch, pro-rated by minutes when they did not play the whole match. Lower is better.",
    "conceded_90": f"Goals conceded {_P90}. Lower is better.",
    "saves_in_box": "Saves from shots taken inside the penalty area, usually the hardest to make.",
    "sweeper_90": f"Sweeper-keeper actions {_P90}: times the keeper came off their line to deal with the ball outside the area.",
    "high_claims_90": f"High balls (crosses and long passes) the keeper claimed cleanly {_P90}.",
    "punches": "Crosses and high balls the keeper punched clear.",
    # Physical
    "km": "Total distance covered in kilometres, over every match played.",
    "km_90": f"Distance covered in kilometres {_P90}.",
    "hsr_km_90": f"Kilometres covered at high speed or sprinting {_P90}: the intense part of a player's running.",
    "sprints": "Number of sprints over the season.",
    "sprints_90": f"Sprints {_P90}.",
    "top_speed": "The fastest speed recorded for the player in any match, in km/h.",
    # Advanced
    "npxg_xa_90": f"Non-penalty expected goals plus expected assists {_P90}: a player's total expected involvement in goals, with penalties left out. Higher is better.",
    "ga_90": f"Goals plus assists {_P90}: the realised counterpart of npxG + xA. Higher is better.",
    "finishing": "Finishing: non-penalty goals minus non-penalty xG, divided by non-penalty shots. Positive means the player scores more than their chances are worth, per shot so volume shooters are not favoured.",
    "placement": "Shot placement: expected goals on target minus expected goals, divided by shots. Positive means the player's shots are placed better than the average shot from the same spots.",
    "xa_per_kp": "Expected assists divided by key passes: the average quality of the chances a player creates, independent of how many they create.",
    "shot_creation_90": f"Shots plus key passes {_P90}: everything a player does that ends in a shot, their own or a team-mate's.",
    "prog_actions_90": f"Progressive carries plus completed dribbles {_P90}: how often a player moves the ball forward on their own.",
    "def_actions_90": f"Tackles, interceptions, blocks and clearances added together {_P90}: raw defensive volume.",
    "padj_tkl_int_90": f"Possession-adjusted tackles plus interceptions {_P90}: each match's tackles and interceptions are scaled by 50 divided by the opponent's possession, so a player on a team that rarely has the ball is not credited for simply having more to defend. Higher is better.",
    "ball_wins_90": f"Tackles won plus interceptions plus ball recoveries {_P90}: how often a player wins the ball back. Higher is better.",
    "duels_90": f"Duels contested {_P90}, won or lost: the volume behind the duel success rate.",
    "aerials_90": f"Aerial duels contested {_P90}, won or lost: the volume behind the aerial success rate.",
    "loss_per_100": "Possession lost per 100 touches: how often a player gives the ball away, scaled by how often they have it. Lower is better.",
    # Rating, discipline, playing time
    "rating": "Sofascore's 1-10 match rating, averaged over the season with each match weighted by the minutes played in it. Around 7 is an ordinary performance; above 8 is a very good one.",
    "yellow": "Yellow cards, counted from the match incidents. Lower is better.",
    "red": "Red cards, counted from the match incidents. Lower is better.",
    "minutes": "Minutes played over the season, the basis for every per-90 rate.",
    "matches": "Appearances: matches in which the player was on the pitch for at least a minute.",
    "starts": "Matches the player started.",
}

# ── team metrics (the analytics tab) ─────────────────────────────────────────
# Per-match averages over played matches with a team sheet; ratios are computed
# from the summed numerators and denominators rather than averaging match ratios.

TEAM_METRICS: list[dict[str, Any]] = [
    {"key": "xg_for", "label": "xG for", "fmt": "2", "lower": False, "group": "Attack",
     "desc": "Expected goals created per match: the sum of the chance each shot had of being scored. Higher is better."},
    {"key": "xg_against", "label": "xG against", "fmt": "2", "lower": True, "group": "Defence",
     "desc": "Expected goals conceded per match: the value of the chances the opponent had. Lower is better."},
    {"key": "xg_diff", "label": "xG difference", "fmt": "2", "lower": False, "group": "Results",
     "desc": "xG for minus xG against per match: the underlying margin between a team and its opponents. Higher is better."},
    {"key": "goals_for", "label": "Goals for", "fmt": "2", "lower": False, "group": "Attack",
     "desc": "Goals scored per match."},
    {"key": "goals_against", "label": "Goals against", "fmt": "2", "lower": True, "group": "Defence",
     "desc": "Goals conceded per match. Lower is better."},
    {"key": "finishing", "label": "Finishing", "fmt": "2", "lower": False, "group": "Attack",
     "desc": "Goals scored minus expected goals, per match: positive means the team has scored more than its chances were worth."},
    {"key": "keeping", "label": "Keeping", "fmt": "2", "lower": False, "group": "Defence",
     "desc": "Expected goals against minus goals conceded, per match: positive means the team has conceded less than the chances it allowed were worth. Higher is better."},
    {"key": "xpts_per_match", "label": "xPts per match", "fmt": "2", "lower": False, "group": "Results",
     "desc": "Expected points per match: for each match, the points a team would earn on average if its xG and its opponent's xG were replayed as Poisson goal counts. Higher is better."},
    {"key": "luck", "label": "Luck", "fmt": "2", "lower": False, "group": "Results",
     "desc": "Points minus expected points, per match: how far results have run ahead of (positive) or behind (negative) the underlying performance."},
    {"key": "possession", "label": "Possession", "fmt": "pct", "lower": False, "group": "Style",
     "desc": "Share of the ball, averaged over matches, as a percentage."},
    {"key": "field_tilt", "label": "Field tilt", "fmt": "pct", "lower": False, "group": "Style",
     "desc": "Touches in the opponent's box as a percentage of touches in both boxes (own box touches divided by own plus opponent box touches). Above 50 means the team spends more of the game in the dangerous end than its opponents do."},
    {"key": "ppda", "label": "PPDA", "fmt": "1", "lower": True, "group": "Style",
     "desc": "Passes per defensive action: the opponent's passes divided by the team's tackles, interceptions and fouls. A low number means the team presses (it lets the opponent make few passes before engaging). Lower is better for a pressing side."},
    {"key": "shots", "label": "Shots", "fmt": "1", "lower": False, "group": "Attack",
     "desc": "Shots attempted per match."},
    {"key": "shots_against", "label": "Shots against", "fmt": "1", "lower": True, "group": "Defence",
     "desc": "Shots faced per match. Lower is better."},
    {"key": "shot_quality", "label": "Shot quality", "fmt": "2", "lower": False, "group": "Attack",
     "desc": "xG per shot: the average quality of the chances a team takes. Higher means better chances, not necessarily more."},
    {"key": "shot_quality_against", "label": "Shot quality against", "fmt": "2", "lower": True, "group": "Defence",
     "desc": "xG per shot faced: the average quality of the chances a team allows. Lower is better."},
    {"key": "sot_pct", "label": "Shots on target %", "fmt": "pct", "lower": False, "group": "Attack",
     "desc": "Shots on target as a percentage of shots attempted (denominator: shots)."},
    {"key": "big_chances", "label": "Big chances", "fmt": "2", "lower": False, "group": "Attack",
     "desc": "Big chances created per match: situations where a goal is expected."},
    {"key": "big_chances_missed", "label": "Big chances missed", "fmt": "2", "lower": True, "group": "Attack",
     "desc": "Big chances not scored per match. Lower is better."},
    {"key": "corners", "label": "Corners", "fmt": "1", "lower": False, "group": "Attack",
     "desc": "Corners won per match."},
    {"key": "aerial_pct", "label": "Aerial duels won", "fmt": "pct", "lower": False, "group": "Defence",
     "desc": "Aerial duels won as a percentage of aerial duels contested (denominator: aerial duels contested)."},
    {"key": "ground_duel_pct", "label": "Ground duels won", "fmt": "pct", "lower": False, "group": "Defence",
     "desc": "Ground duels won as a percentage of ground duels contested (denominator: ground duels contested)."},
    {"key": "passes", "label": "Passes", "fmt": "int", "lower": False, "group": "Style",
     "desc": "Passes attempted per match."},
    {"key": "pass_pct", "label": "Pass completion", "fmt": "pct", "lower": False, "group": "Style",
     "desc": "Successful passes as a percentage of passes attempted (denominator: passes attempted)."},
    {"key": "long_ball_share", "label": "Long-ball share", "fmt": "pct", "lower": False, "group": "Style",
     "desc": "Long balls attempted as a percentage of passes attempted (denominator: passes attempted): a direct side runs high, a possession side low. Neither is better."},
    {"key": "crosses", "label": "Crosses", "fmt": "1", "lower": False, "group": "Style",
     "desc": "Crosses attempted per match."},
    {"key": "dribbles", "label": "Dribbles", "fmt": "1", "lower": False, "group": "Style",
     "desc": "Dribbles completed per match."},
    {"key": "fouls", "label": "Fouls", "fmt": "1", "lower": True, "group": "Discipline",
     "desc": "Fouls committed per match. Lower is better."},
    {"key": "cards", "label": "Cards", "fmt": "2", "lower": True, "group": "Discipline",
     "desc": "Card points per match: one for a yellow, two for a red. Lower is better."},
    {"key": "km", "label": "Distance (km)", "fmt": "1", "lower": False, "group": "Physical",
     "desc": "Kilometres covered by the whole team per match."},
    {"key": "sprints", "label": "Sprints", "fmt": "int", "lower": False, "group": "Physical",
     "desc": "Sprints by the whole team per match."},
    {"key": "rating", "label": "Rating", "fmt": "2", "lower": False, "group": "Results",
     "desc": "Sofascore's average 1-10 team rating per match."},
]

# ── model terms ──────────────────────────────────────────────────────────────

MODEL_TERMS: list[dict[str, str]] = [
    {"key": "xg", "label": "xG (expected goals)", "group": "Chances",
     "desc": "The chance a shot had of being scored, judged from where and how it was taken, so a tap-in is worth about 0.9 and a hopeful 30-yarder about 0.03. Added up over a match or a season it says how many goals the chances were worth."},
    {"key": "npxg", "label": "npxG (non-penalty xG)", "group": "Chances",
     "desc": "Expected goals with penalties taken out (each penalty is worth 0.79). A penalty is a chance that was awarded, not created, so it flatters whoever takes them."},
    {"key": "xgot", "label": "xGOT (expected goals on target)", "group": "Chances",
     "desc": "The value of a shot after seeing where in the goal it went: a shot into the top corner is worth more than the same shot straight at the keeper. Off-target shots are worth zero. Comparing xGOT with xG measures shot placement; comparing it with goals measures the goalkeeper."},
    {"key": "xa", "label": "xA (expected assists)", "group": "Chances",
     "desc": "The xG of the shot a pass set up, credited to the passer whether or not the shot went in. A creator with high xA and few assists has been let down by the finishing."},
    {"key": "xpts", "label": "Expected points (xPts)", "group": "Results",
     "desc": "The points a team would earn on average if a match were replayed with goals drawn at random from each side's xG. 3 times the probability of winning plus the probability of a draw. Over a season it is the table the chances deserved."},
    {"key": "luck", "label": "Luck", "group": "Results",
     "desc": "Points minus expected points. Positive means results have been better than the chances justified; it usually fades, which is why a lucky team is a candidate to slide."},
    {"key": "strength", "label": "Strength", "group": "Ratings",
     "desc": "The expected points per game a team would take against an average opponent at a neutral venue, from the match model. It is the site's single number for how good a team is, on the same scale for every competition."},
    {"key": "elo", "label": "Elo", "group": "Ratings",
     "desc": "A rating updated after every match: the winner takes points from the loser, more when the result was a surprise. A quick, robust view of form that needs no shot data."},
    {"key": "attack_defence", "label": "Attack and defence parameters", "group": "Match model",
     "desc": "The match model gives every team an attack number and a defence number. The goals a team is expected to score is its attack times the opponent's defence (times home advantage when at home); the model's whole prediction follows from those two numbers per team."},
    {"key": "home_advantage", "label": "Home advantage", "group": "Match model",
     "desc": "The multiplier the model applies to the home side's expected goals, fitted from results in that competition. Typically 1.2 to 1.4, and 1 at a neutral venue."},
    {"key": "rho", "label": "Rho (Dixon-Coles correction)", "group": "Match model",
     "desc": "Treating each side's goals as independent gets low-scoring results slightly wrong: 0-0 and 1-1 happen more often than the plain numbers say, 1-0 and 0-1 less. Rho is the small correction to those four scores."},
    {"key": "time_decay", "label": "Time decay (xi)", "group": "Match model",
     "desc": "Older matches count for less when the model is fitted: each match's weight falls off with age at a rate set by xi. A larger xi means the model reacts faster to recent form and forgets faster."},
    {"key": "ridge", "label": "Ridge", "group": "Match model",
     "desc": "A penalty that pulls every team's attack and defence numbers towards average unless the results argue otherwise. It stops a team with few matches getting an extreme rating from a couple of freak scores."},
    {"key": "pooled_scale", "label": "Pooled scale", "group": "Match model",
     "desc": "One model fitted over every league at once, with cup matches between clubs from different leagues tying the leagues together. It is what puts a Premier League club and a Brazilian club on the same strength scale; where few cup matches connect two regions the comparison leans on the ridge and is less certain."},
    {"key": "scoring_factor", "label": "Scoring factor (league adjustment)", "group": "Match model",
     "desc": "How much harder it is to score in one league than in the pool as a whole, from the pooled fit's defence numbers. A player's attacking rates are multiplied by it for the global leaderboards, so a goal in a stingy league counts for more than one in a leaky one."},
    {"key": "fair_odds", "label": "Fair odds", "group": "Odds",
     "desc": "The decimal odds that match the model's probability exactly, with no bookmaker margin: 1 divided by the probability. A 40% chance is fair odds of 2.50."},
    {"key": "de_vig", "label": "De-vig", "group": "Odds",
     "desc": "Removing the bookmaker's margin from a set of odds so the implied probabilities add up to 100%. Quoted odds imply more than 100% in total; de-vigging scales them back so they can be compared with the model."},
    {"key": "edge", "label": "Edge", "group": "Odds",
     "desc": "The model's probability minus the market's de-vigged probability. A positive edge means the model thinks the outcome is more likely than the price says. It is information, not advice: the market is usually right."},
    {"key": "consensus", "label": "Consensus", "group": "Odds",
     "desc": "The average of several bookmakers' de-vigged probabilities, used as the market's view of a match rather than any one book's."},
    {"key": "percentile", "label": "Percentile", "group": "Players",
     "desc": "Where a player's number sits among positional peers in the same competition, from 0 (the lowest) to 100 (the highest). A 90th-percentile figure is better than 90% of comparable players. For metrics where less is better the scale is flipped, so 100 is always best."},
    {"key": "minutes_floor", "label": "Minutes floor", "group": "Players",
     "desc": "The minutes a player needs before their rates are compared with others: 30% of the minutes his competition has played so far (the most anyone has played), at least 90. It rises with the season, so a league thirty rounds in and one seven rounds in rank players on a like share of their seasons. Below it a per-90 number is too noisy to rank."},
    {"key": "shrinkage", "label": "Shrinkage", "group": "Players",
     "desc": "In the Player lab, a player's rates are blended with the positional average in proportion to minutes played, as if 450 minutes of average play were added to their record. A player with few minutes is pulled towards average; one with a full season barely moves."},
    {"key": "field_tilt", "label": "Field tilt", "group": "Teams",
     "desc": "A team's touches in the opponent's box as a share of touches in both boxes. It says which end of the pitch the game is being played in, which possession alone does not."},
    {"key": "ppda", "label": "PPDA", "group": "Teams",
     "desc": "Passes per defensive action: the opponent's passes divided by the team's tackles, interceptions and fouls. A pressing side lets the opponent make few passes before engaging, so its PPDA is low."},
    {"key": "monte_carlo", "label": "Monte Carlo simulation", "group": "Simulation",
     "desc": "The rest of the season is played out thousands of times with every remaining match's result drawn at random from the model's probabilities. The share of runs in which a team finishes first is its title probability, and so on for every outcome."},
    {"key": "position_distribution", "label": "Position distribution", "group": "Simulation",
     "desc": "For each team, the share of simulated seasons that ended in each league position. The table's median finish and its 5th-95th percentile range come from it."},
    {"key": "bands", "label": "Bands", "group": "Simulation",
     "desc": "The finishing positions that mean something: the title, Champions League places, other European places, the play-offs, relegation. Each team's probability of landing in each band is summed from its position distribution."},
    {"key": "expected_result", "label": "Expected result", "group": "Matches",
     "desc": "On a match page, the score the shots deserved: each side's xG replayed as random goals gives a probability for the home win, the draw and the away win, and the most likely score. A 1-0 with an expected result of 0.3 home win was a smash-and-grab."},
    {"key": "rating", "label": "Rating", "group": "Matches",
     "desc": "Sofascore's 1-10 match rating for each player, built from their actions in the game. Around 6.5 to 7 is an ordinary performance, 8 a very good one, 9 and above a match-winning one. Season ratings weight each match by minutes played."},
    {"key": "formation", "label": "Formation", "group": "Matches",
     "desc": "The starting shape, written defenders-midfielders-forwards (4-3-3, 3-5-2), as recorded in the lineups. The team of the week picks the shape that fits its best eleven."},
    {"key": "form", "label": "Form", "group": "Teams",
     "desc": "Recent results, usually the last five or six matches, shown with the xG of each so a run of wins built on thin chances can be told from a deserved one."},
    {"key": "goals_added", "label": "Goals added (GA)", "group": "Player value",
     "desc": "The site's player value, in goals of non-penalty expected goal difference: sixteen actions per match (xG, xA, key passes, carries, dribbles, passes in the opposition half, possession lost, tackles, interceptions, blocks, clearances, recoveries, aerials, errors, and for keepers goals prevented and claims) plus the match rating, each weighted by how well it predicted later matches. Centred on each competition and moved by its strength on the pooled scale."},
    {"key": "gar", "label": "GAR/90 (goals above replacement per 90)", "group": "Player value",
     "desc": "Goals added per 90 minutes minus the replacement level of the player's role: what he adds over a player a club could find cheaply. Projected GAR/90 shrinks it toward replacement by 900 minutes of evidence, so a short good spell is not taken at face value."},
    {"key": "par", "label": "PAR (points above replacement)", "group": "Player value",
     "desc": "Goals above replacement turned into league points: one goal of goal difference is worth about 0.65 to 0.75 points, the slope of expected points on goal difference at the league's scoring rate (two Poisson sides)."},
    {"key": "replacement_level", "label": "Replacement level", "group": "Player value",
     "desc": "For each role (GK, CB, FB, DM, CM, AM, W, ST), the value per 90 of the 20th-percentile regular (900+ minutes in the last 12 months) across every followed competition: roughly the player a club could sign or promote without paying for quality."},
    {"key": "role", "label": "Role", "group": "Player value",
     "desc": "Goalkeeper, centre-back, full-back or wing-back, defensive, central or attacking midfielder, winger, striker: read from the starting formation, since Sofascore lists each line of an XI right to left. A player's role is where he starts most; without a start it falls back to Sofascore's defender, midfielder or forward."},
    {"key": "unit_grade", "label": "Unit grade", "group": "Player value",
     "desc": "On a club page, each unit (goalkeeper, centre-backs, full-backs, central midfield, attacking midfield and wingers, strikers) graded against the other clubs of its league on the projected value of the current players used there this season, weighted by their minutes: A is the top fifth, E the bottom fifth."},
    {"key": "fair_value_index", "label": "Fair value index (FVI)", "group": "Player value",
     "desc": "Expected points above replacement over the next four seasons at 2,500 minutes a season, discounted 15% a year, with the ageing curve and the chance of still being a regular each year; 100 is the median regular of the top five leagues. The first version of the fair value; the fair fee in euros (fitted on real fees) now stands beside it, and the index is the fallback when too few fees are available."},
    {"key": "sensitivity_curve", "label": "Sensitivity curve", "group": "Player value",
     "desc": "A club's title, European, relegation and expected-points numbers re-simulated with its strength shifted up and down (2,000 runs per shift, common random numbers). The transfer simulator turns a change in goals per match into a shift and reads the curve."},
    {"key": "value_v2", "label": "Value (valuation v2)", "group": "Transfers",
     "desc": "Expected points above replacement over the next four seasons, discounted 15% a year: the projected GAR/90 drawn from its uncertainty, moved each year by the ageing curve, times the minutes his availability promises (3,400 a season at full availability) and the chance he is still a regular; a 10-90% band from 400 draws."},
    {"key": "availability", "label": "Availability", "group": "Transfers",
     "desc": "The share of his clubs' minutes a player played in the last 12 months, each club counted from his first to his last appearance there and his current club up to today, shrunk toward 50% by eight matches."},
    {"key": "fair_fee", "label": "Fair fee", "group": "Transfers",
     "desc": "What a club would pay in euros, from a model fitted on real transfer fees in Sofascore's data: the player's value at the time, age, position, minutes and both clubs' strength. Out of sample it misses a typical fee by a factor of about 1.8 (a league-and-position median misses by 2.4)."},
    {"key": "deal_grade", "label": "Deal grade", "group": "Transfers",
     "desc": "For each club in a move of the last 12 months: the fee against the fair fee at the time, then the value the player has delivered since the move, weighted in as his minutes accumulate. A is the best fifth of the year's deals, E the worst."},
    {"key": "transfer_budget", "label": "Transfer budget", "group": "Transfers",
     "desc": "A club's likely gross spend in a window, from a model fitted across the followed clubs on the latest summer window (its previous window's spending and sales, the league's and the club's strength, the squad's market value once enough squads are valued), with a 25-75% range."},
    {"key": "fantasy_points", "label": "Fantasy points", "group": "Fantasy",
     "desc": "FPL's 2025/26 scoring applied by us to Sofascore's match data (minutes, goals by position, assists, clean sheets, goals conceded, saves, cards, own goals, missed penalties, defensive contributions), with the bonus replaced by 3/2/1 for the three best match ratings."},
    {"key": "fantasy_price", "label": "Fantasy price", "group": "Fantasy",
     "desc": "Our own price proxy: expected points above replacement next season from the value model, ranked within the league and position and mapped onto FPL-like ranges. Official FPL prices and ownership are not used (the Premier League's terms forbid reusing its material)."},
]

_GROUP_ORDER = ["Scoring", "Creating", "Passing", "Carrying", "Defending", "Duels", "Goalkeeping", "Physical",
                "Advanced", "Rating", "Discipline", "Playing time"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_glossary() -> dict:
    """
    glossary.json: player metrics grouped as in the catalogue, then the team
    metrics, then the model terms.
    """
    from oddsmarkets.football.analytics.players import METRICS  # local: players.py imports this module

    groups: dict[str, list[dict]] = {}
    for m in METRICS:
        groups.setdefault(m["group"], []).append({
            "key": m["key"], "label": m["label"], "desc": PLAYER_DEFINITIONS.get(m["key"], ""),
            "fmt": m.get("fmt"), "scope": m.get("scope", "all"), "lower": bool(m.get("lower")), "group": m["group"],
        })
    ordered = [g for g in _GROUP_ORDER if g in groups] + [g for g in groups if g not in _GROUP_ORDER]
    out_groups = [{"name": g, "entries": groups[g]} for g in ordered]
    out_groups.append({"name": "Team metrics", "entries": [
        {"key": t["key"], "label": t["label"], "desc": t["desc"], "fmt": t["fmt"], "scope": "team",
         "lower": bool(t.get("lower")), "group": t["group"]}
        for t in TEAM_METRICS
    ]})
    return {"groups": out_groups, "model": MODEL_TERMS, "updated_at": _now()}
