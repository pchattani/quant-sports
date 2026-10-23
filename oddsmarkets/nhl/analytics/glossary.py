"""
glossary.json: every catalogue metric (skaters, goalies) grouped as "<Kind>: <group>", each entry {key, label, desc,
fmt, lower, scope, stabilises_at, unit, kind}; the team unit ratings; the model entries (how each model works, in one
paragraph); and the percentile, stabilisation, qualification and strength rules.

stabilises_at: the sample (in the metric's unit: 5v5 minutes, minutes, shots, unblocked attempts, faceoffs,
unblocked attempts faced) at which split-half reliability reaches 0.7, n_0.7 = 0.7 k / 0.3, with k from builder B's
stabilise.py when fitted, else the fixed k this layer shrinks with.
"""
from __future__ import annotations

from oddsmarkets.nhl import analytics as an

TEAM_UNITS = [
    ("rating", "Rating", "Team strength (goal differential per game against an average opponent) or, without the model, xG "
     "differential per game.", False),
    ("off5", "5v5 offence", "Expected goals for per 60 at 5v5.", False), ("def5", "5v5 defence", "Expected goals against per 60 at 5v5.", True),
    ("pp", "Power play", "Expected goals for per 60 on the power play.", False),
    ("pk", "Penalty kill", "Expected goals against per 60 short-handed.", True),
    ("goalie", "Goaltending", "Team goals saved above expected per 60.", False),
    ("xgf_pct5", "5v5 xGF%", "Share of 5v5 expected goals.", False), ("cf_pct5", "5v5 CF%", "Share of 5v5 shot attempts.", False),
]
MODEL = [
    ("xg", "Expected goals (xG)", "Shots", "The probability that an unblocked attempt becomes a goal (LightGBM) from distance, "
     "angle, shot type, rebound (time and angle change since the previous attempt), rush (time since a neutral- or defensive-zone "
     "event), time since and type and location of the previous event, strength, score state and an arena adjustment for scorer bias (seasons before 2023-24); "
     "cross-fitted by season so no shot is scored by a model that saw it; benchmarked against MoneyPuck's xGoal (credit: "
     "xG benchmark data from MoneyPuck.com). When the model does not score a season the build uses a logistic fallback fitted on "
     "the season's own attempts and says so (xg_source)."),
    ("shooting", "Shooting talent", "Shots", "Goals above expected per unblocked attempt, regressed toward the league by the "
     "stabilisation constant of finishing (most of a season's goals-above-xG is noise)."),
    ("goalies", "GSAx", "Goaltending", "Goals saved above expected: the xG of the unblocked attempts a goalie faces minus the goals "
     "the goalie allows, overall, by danger band (xG under 0.08, 0.08-0.20, 0.20+), by shot type and by strength; empty-net goals excluded."),
    ("onice", "On-ice rates", "Skaters", "Shot attempts, unblocked attempts, shots, goals and xG for and against per 60 with the player "
     "on the ice at 5v5, on the power play and short-handed; the adjusted versions are score- and venue-adjusted (each event weighted "
     "by how its score state and venue inflate or deflate rates league-wide)."),
    ("rapm", "RAPM", "Skaters", "Regularised adjusted plus-minus: a ridge regression on 5v5 stints where every skater "
     "has an offence and a defence coefficient, with team-mates, opponents, zone starts, score state and home ice controlled, and "
     "priors from earlier seasons; the coefficients are isolated xG for and against per 60."),
    ("value", "Rink value", "Value", "Goals above replacement (GAR) and wins (WAR): RAPM offence and defence, power play and penalty "
     "kill, shooting talent, penalties drawn and taken and faceoffs, in goals over a replacement-level player (the level of the "
     "players outside each team's regular lineup); goalies from GSAx against replacement goaltending."),
    ("lines", "Lines", "Skaters", "Forward trios and defence pairs from the shift charts: every 5v5 stint with three forwards and two "
     "defencemen on a side counts toward that line and that pair."),
    ("team_strength", "Team strength", "Teams", "Score- and venue-adjusted xG and shot rates by strength, special teams, "
     "a goaltending component with the expected starter as an input, and schedule effects (rest, travel, back-to-backs)."),
    ("game", "Game model", "Prediction", "Goals for each side from the team-strength components, starters and context, "
     "with correlation, empty-net and late-game effects; outputs the win probability, regulation result, overtime and shootout "
     "probabilities, puck line and total."),
    ("live", "Win probability", "Prediction", "A Markov model of the remaining goals at every event from score, time, strength and the pre-game "
     "expectation; without it the page uses a Poisson model of the remaining goals at the pre-game rates (labelled)."),
    ("season_sim", "Season simulation", "Prediction", "The remaining schedule simulated game by game (84 games from "
     "2026-27), points (win 2, OT / SO loss 1), the NHL tiebreak procedure, divisional and wild-card seeding, best-of-seven series, "
     "the Presidents' Trophy and the draft lottery; magic numbers and next-game chances."),
    ("awards", "Award races", "Prediction", "Hart, Vezina, Norris, Calder, Art Ross, Maurice Richard and Selke "
     "probabilities from the projected season and a fit on verified past winners."),
    ("percentile", "Percentiles", "Catalogue", "100 = best, reversed where lower is better; placed against the qualified pool "
     "(skaters: 250 minutes at 5v5 per 82 team games, prorated; goalies: a quarter of the team's minutes) after shrinking the value "
     "toward the pool mean with the metric's stabilisation constant: (n v + k m) / (n + k); a metric needs its sample floor (50 "
     "minutes at 5v5, 20 shots, 50 faceoffs, 20 PP or PK minutes, 100 unblocked attempts faced) before it gets a percentile. "
     "Rink value (GAR, WAR and their parts) needs 200 minutes (goalies 600) per 82-game schedule, not prorated: early in a "
     "season nearly everyone is within a few hundredths of a win of zero and one game would reorder them. "
     "pct_pos compares forwards with forwards and defencemen with defencemen."),
    ("stabilisation", "Stabilisation", "Catalogue", "The sample at which split-half reliability reaches 0.7: r(n) = n / (n + k), "
     "n_0.7 = 0.7 k / 0.3 (k fitted per metric over seasons)."),
    ("strength", "Strength states", "Catalogue", "5v5: five skaters a side with both goalies in net; PP / SH: the player's team has "
     "more / fewer skaters; other: 4v4, 3v3, empty net. Regular-season shootouts are excluded from every count."),
    ("game_score", "Game score", "Games", "Three stars: 0.75 G + 0.7 A1 + 0.55 A2 + 0.075 SOG + 0.05 BLK + 0.15 penalties drawn - 0.15 "
     "taken + 0.01 FOW - 0.01 FOL + 0.05 CF - 0.05 CA + 0.15 GF - 0.15 GA (5v5 on-ice terms); goalies -0.75 GA + 0.1 saves."),
    ("team_grades", "Strengths and needs", "Value", "Each club's centres, wings, defence and goalies and its 5v5 offence, 5v5 defence, "
     "power play and penalty kill, valued as projected GAR over a full season (rest-of-season GAR per 60 x projected ice time) "
     "and placed against the league (A top 20 %, B, C, D, F bottom 20 %); trade targets ranked by what each would add in the "
     "club's depth chart."),
    ("trade_sim", "Trade simulator", "Value", "Players move; incoming players take ice time from the lowest-rated players at their "
     "position (a better goalie takes the starts), outgoing minutes go to the next players up, any shortfall at replacement. "
     "The change in the rotation's GAR per 60 x minutes shifts the club's rating in goals a game; points and chances come from "
     "re-running the season simulation at shifted ratings. The salary cap is not checked."),
    ("aging", "Aging curve", "Value", "The change in GAR per 60 from one season to the next by age (delta method on consecutive "
     "seasons, minute-weighted), centred on the all-ages mean and shrunk; used for next season's value in the trade simulator."),
    ("valuation", "Valuation (multi-season)", "Value", "A player's projected on-field value in WAR over the rest of this season and "
     "the next three, discounted 0.9 a season: rest-of-season GAR per 60 aged on the ageing curve, times projected minutes, "
     "availability (games-played share, regressed) and survival (the chance the player is still an NHL regular); a 10th-90th percentile "
     "band from simulated careers. Not contracts or the salary cap."),
    ("vorp", "VORP (positional)", "Value", "Value over the replacement level at the player's own position (C, LW, RW, D, G): the "
     "minute-weighted GAR per 60 of players outside the league's top N at that position by ice time."),
    ("scarcity", "Scarcity index", "Value", "How much better a position's starters are than its replacement level, relative to all "
     "skaters (1 = average; above 1, good players at that position are harder to replace)."),
    ("survival", "Survival", "Value", "The chance a player who is an NHL regular this season (games played >= 25 % of team games; goalies "
     "12 %) is still one next season, from a logistic regression on age, the player's rate and minutes over every pair of completed seasons."),
    ("availability", "Availability", "Value", "The expected share of the team's games a skater plays: games played this season and the "
     "last two, regressed to the league mean of regulars with 30 pseudo-games, less the games an injury is expected to cost."),
    ("trade_grade", "Trade grade", "Moves", "A club's share of the value a trade moved, rescaled to two sides: A >= 65 %, B >= 55 %, "
     "C 45-55 %, D >= 35 %, F below; 'minor' when the deal moved under 0.25 WAR. Graded at the time (valuation as of the trade "
     "date, no hindsight) and now (realised since + what is still projected in the original window)."),
    ("pick_value", "Pick-value curve", "Moves", "What a draft slot is worth: the mean discounted WAR of each overall pick over its first "
     "seven seasons (2010-2019 drafts, picks who never played count zero), fitted with a smooth decreasing curve; future picks of "
     "unknown slot are valued at the round's average, discounted by the seasons until the draft."),
    ("realised_value", "Realised value", "Moves", "Since a trade: the player's GAR per 60 that season x the player's minutes for the new club "
     "after the trade date / goals per win."),
    ("fantasy_points", "Fantasy points (ours)", "Fantasy", "Our own default scoring, not any platform's: G 2, A 1.5, +/- 0.5, PPP 0.5, "
     "SOG 0.3, HIT 0.2, BLK 0.4; goalies W 4, GA -1, SV 0.2, SO 3. Every weight can be changed on the page."),
    ("fantasy_vor", "Fantasy VOR", "Fantasy", "Rest-of-season points over the best player left at the position after a greedy draft of "
     "twelve standard rosters (C 2, LW 2, RW 2, D 4, UTIL 1, G 2, bench 4)."),
    ("tiers", "Tiers", "Fantasy", "Groups of similar value: a new tier starts where the drop to the next player is among the largest "
     "10 % of drops in the top 240 (at least three a tier)."),
    ("buy_low", "Buy low / sell high", "Fantasy", "Players whose results run far from what their chances support: goals 2+ away from "
     "finishing-adjusted expected goals or an on-ice 5v5 PDO beyond 0.950 / 1.050, with the projection 0.4+ points a game away from "
     "their pace; goalies with GSAx 4+ goals from what their save talent implies."),
    ("pp_unit", "PP unit", "Fantasy", "PP1 / PP2 from each skater's recency-weighted power-play minutes ranked within the club (1-5 PP1, 6-10 PP2)."),
    ("streaming", "Streaming goalies", "Fantasy", "Goalies outside the top 24 ranked by this week's projected starts x matchups: start "
     "probability from recent start share (a back-to-back's second game moved to the backup by the fitted ratio), wins from the game "
     "model's win probability, goals against from team defence, opponent offence and save talent."),
]


def build() -> dict:
    from oddsmarkets.nhl.analytics import goalies, skaters
    groups: dict[str, list] = {}
    for kind, mets in (("Skaters", skaters.METRICS), ("Goalies", goalies.METRICS)):
        for m in mets:
            e = an.public_metric(m)
            e["kind"] = kind.lower().rstrip("s")
            groups.setdefault(f"{kind}: {m['group']}", []).append(e)
    groups["Teams: Units"] = [{"key": k, "label": l, "desc": d, "lower": lo, "fmt": "2", "kind": "team", "stabilises_at": None}
                              for k, l, d, lo in TEAM_UNITS]
    return {"ok": True, "updated_at": an.now(), "groups": [{"name": k, "entries": v} for k, v in groups.items()],
            "model": [{"key": k, "label": l, "group": g, "desc": d} for k, l, g, d in MODEL],
            "notices": {"moneypuck": an.MONEYPUCK_CREDIT, "nhl": "NHL data shown for informational, non-commercial use; no affiliation "
                        "with the NHL, NHLPA, teams, players, ESPN or bookmakers."}}
