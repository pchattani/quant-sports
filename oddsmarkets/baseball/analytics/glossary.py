"""
glossary.json: every catalogue metric (hitters, pitchers, fielders, teams, umpires) grouped as "<Kind>: <group>",
each entry {key,label,desc,fmt,lower,scope,stabilises_at,unit,kind}, plus the model entries (how each model works,
in one paragraph) and the percentile, stabilisation and qualification rules.

stabilises_at: the sample (in the metric's unit: PA, balls in play, pitches, swings, batters faced, called pitches)
at which a player's split-half reliability reaches 0.7, from builder C's stabilise.py (n_0.7 = 0.7 k / 0.3); for
metrics stabilise.py does not fit, the k used for shrinkage comes from published split-half studies and the same
formula.
"""
from __future__ import annotations

from oddsmarkets.baseball import analytics as an

MODEL = [
    ("stuff", "Stuff+", "Pitch models", "LightGBM models per pitch family (fastball, breaking, offspeed) of swing, whiff, foul, "
     "called-strike and in-play xwOBA probabilities from physical characteristics only, combined into an expected run value per "
     "pitch with the training seasons' run values of each outcome; trained on the seasons before the one scored; 100 = league "
     "average, 10 = one SD of pitcher-pitch-type quality."),
    ("location", "Location+", "Pitch models", "Expected run value of the location (batter-relative horizontal position, height in "
     "the batter's zone) given count, pitch family and platoon, relative to the count's average; scaled like Stuff+."),
    ("pitching", "Pitching+", "Pitch models", "Stuff, location, count and sequence (the previous pitch's type, speed and movement "
     "differences and the trajectory gaps at the decision point and at the plate) in one model of the de-lucked run value."),
    ("physics", "Trajectory physics", "Pitch models", "Every pitch rebuilt from Savant's nine-parameter fit (constant acceleration): "
     "approach angles, induced vertical and horizontal break with gravity removed, plate speed, flight time, the decision-point "
     "position 167 ms before the plate, spin efficiency and the seam-shifted-wake gap between observed movement and spin axis."),
    ("tunneling", "Tunneling", "Pitch models", "For consecutive pitches of a plate appearance, the distance between their positions at "
     "the decision point against their distance at the plate; the tunnel score is the plate separation beyond the league curve's "
     "expectation for the decision-point gap."),
    ("swing", "Swing decisions", "Hitting models", "P(swing) and the run values of swinging and taking at each location, count "
     "and pitch shape (LightGBM); decision value = run value of the choice minus the league-expected value at that pitch."),
    ("battrack", "Bat tracking (adjusted)", "Hitting models", "Bat speed and swing length relative to expectations for count, "
     "location and pitch speed (shrunk with 50 swings); squared-up = exit velocity at 80 %+ of 1.23 bat speed + 0.23 pitch speed; "
     "swing path against the pitch plane (attack angle + VAA)."),
    ("xwoba_plus", "xwOBA+ (ours)", "Batted balls", "Multiclass LightGBM (out, 1B, 2B, 3B, HR) on exit velocity, launch angle, "
     "hang time, the park (its five fence distances, mean wall height, elevation and roof) and sprint speed; cross-fitted by game, "
     "raked so each class's league share is exact, weighted with the season's wOBA values. The ball's direction is not a "
     "feature. Shown next to xwOBA (Savant); the predictive test is on the Calibration page."),
    ("catchprob", "Catch probability and OAA", "Defence", "P(out) for every batted ball from landing spot, hang time and the "
     "fielder's distance and speed required from their alignment-inferred start; OAA = outs minus the summed probabilities, "
     "credited to the responsible fielder; fielding runs with the season's linear weights."),
    ("framing", "Framing and umpires", "Defence", "A penalised logistic called-strike surface (location by batter hand, count, "
     "pitch family, hands) with catcher, umpire, pitcher and batter random effects; framing = strikes added by the catcher's "
     "effect times the run value of a strike; umpire accuracy against the rulebook zone, expected accuracy from the surface."),
    ("re24", "Run and win expectancy", "Value", "RE24 from complete half-innings; linear and wOBA weights per season (wOBA scaled to "
     "OBP); win expectancy from a Markov model of half-inning run distributions (automatic runner in extra innings from 2020); "
     "leverage index normalised to 1; WPA per plate appearance."),
    ("war", "Bullpen WAR", "Value", "Batting from regressed park-neutral xwOBA+, baserunning (steals and extra bases taken), "
     "fielding (OAA runs) and framing, positional adjustment, a league adjustment to zero, and replacement level at 57 % of 1,000 "
     "WAR per 2,430 games for position players and 43 % for pitchers (RA9- and xwOBA+-based)."),
    ("parks", "Park factors", "Value", "Contact factors per outcome and batter hand from observed over park-neutral expected counts "
     "(regressed with pseudo-events, three seasons); runs, K and BB from home and road games."),
    ("projections", "Projections", "Prediction", "Component projections (K, BB, HBP, ground balls, xwOBAcon, HR per ball in play, "
     "hits and extra bases on balls in play, bat speed), each regressed at its own stabilisation rate over three weighted seasons, "
     "slow components shrunk toward targets predicted by fast ones, aging curves fitted by the delta method, Triple-A counts "
     "translated."),
    ("game_model", "Game model", "Prediction", "A plate-appearance Monte Carlo (20,000 games) with projected lineups, the starter's "
     "pitch-count exit model, bullpen tiers by availability, park, weather, umpire and home field; outputs win, run line, total and "
     "first-five distributions."),
    ("live", "Live win probability", "Prediction", "An exact Markov chain over half-inning run distributions from the pre-game "
     "spec's lineups and pitchers, evaluated at every plate appearance's state (inning, outs, bases, score)."),
    ("season_sim", "Season and postseason simulation", "Prediction", "Unplayed games and the 12-team bracket simulated with "
     "game-model or rating probabilities and a team-strength error held for the season; series chances in closed form; magic numbers "
     "deterministic; next-game chances interventional."),
    ("awards", "Award races", "Prediction", "A conditional logit over each league's candidates on Bullpen WAR, traditional voting "
     "features and team success, fitted on verified past winners."),
    ("percentile", "Percentiles", "Catalogue", "100 = best, reversed where lower is better; placed against the reference pool "
     "(hitters with 2.1 PA per team game, pitchers with 1.25 BF per team game) after shrinking the value toward the pool mean with "
     "the metric's stabilisation constant: (n v + k m) / (n + k); a metric needs its sample floor (e.g. 50 PA, 25 balls in play) "
     "before it gets a percentile. pct_role compares hitters at the same position group and pitchers in the same role (SP / RP)."),
    ("stabilisation", "Stabilisation", "Catalogue", "The sample at which split-half reliability reaches 0.7: r(n) = n / (n + k), "
     "n_0.7 = 0.7 k / 0.3, k fitted per metric over seasons (builder C)."),
    ("qualified", "Qualified", "Catalogue", "MLB's rules: 3.1 PA per team game (hitters), 1 inning per team game (pitchers)."),
    ("attack_zones", "Attack zones", "Catalogue", "Heart (inner 67 % of the zone), shadow (67-133 %), chase (133-200 %), waste "
     "(beyond), on coordinates normalised by the plate half-width plus a ball radius and the batter's zone height."),
]


def build() -> dict:
    from oddsmarkets.baseball.analytics import fielders, hitters, pitchers, teams, umpires
    groups: dict[str, list] = {}
    for kind, mets in (("Hitters", hitters.METRICS), ("Pitchers", pitchers.METRICS), ("Fielders", fielders.METRICS),
                       ("Teams", teams.METRICS), ("Umpires", umpires.METRICS)):
        for m in mets:
            e = an.public_metric(m)
            e["kind"] = kind.lower().rstrip("s")
            groups.setdefault(f"{kind}: {m['group']}", []).append(e)
    return {"ok": True, "updated_at": an.now(), "groups": [{"name": k, "entries": v} for k, v in groups.items()],
            "model": [{"key": k, "label": l, "group": g, "desc": d} for k, l, g, d in MODEL],
            "notices": {"retrosheet": an.RETRO_NOTICE, "chadwick": an.CHADWICK_ATTRIBUTION, "lahman": an.LAHMAN_ATTRIBUTION}}
