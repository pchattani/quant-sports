"""
The Quant Paddock glossary: one plain-English definition for every driver and team metric in
the catalogues and for the model terms the site uses. Written site-wide as glossary.json
({"groups": [{"name", "entries": [{key, label, desc, fmt, lower, scope}]}], "model": [{key, label,
desc, group}]}) and attached to every catalogue entry as `desc`.

`scope` says from when a metric can exist: results (1950-), qualifying (classification, ~1994-),
segments (Q1/Q2/Q3, 2006-), fastest (fastest-lap ranks, 2004-), laps (lap times, 1996-), pit (pit
stops, 2011-), sprint (2021-), openf1 (timing, stints, race control, 2023-), telemetry (car data,
2023-), model (needs the models' forecasts or effects).

Like the football glossary this module imports nothing from the catalogues at import time
(they import it to decorate their metrics); `build_glossary` imports them when it runs.
"""
from __future__ import annotations

from datetime import datetime, timezone

_PR = "Season value is the mean over the races where it can be measured."

DRIVER_DEFINITIONS: dict[str, str] = {
    # Results
    "races": "Grand Prix starts in the season (entries that did not start are not counted).",
    "wins": "Grand Prix wins.",
    "podiums": "Top-three Grand Prix finishes.",
    "win_rate": "Wins divided by starts.",
    "podium_rate": "Podiums divided by starts.",
    "top5_rate": "Top-five finishes divided by starts.",
    "avg_finish": "Mean finishing position over the races the driver was classified in. Retirements are left out, so read it with the DNF rate. Lower is better.",
    "median_finish": "Median finishing position over classified finishes; less pulled about by one bad afternoon than the mean. Lower is better.",
    "best_finish": "Best finishing position of the season.",
    "avg_grid": "Mean starting slot. A pit-lane start counts as the last slot. Lower is better.",
    "laps_led": "Laps completed in the lead (first across the line at the end of the lap), from lap-by-lap positions.",
    "laps_led_share": "Laps led as a share of the laps the driver completed.",
    "race_h2h": "Share of races the driver finished ahead of his team-mate. Counted when at least one of them was classified; a retirement loses to a finish.",
    "fastest_laps": "Races in which the driver set the fastest lap.",
    "avg_fastest_rank": "Mean rank of the driver's fastest lap in each race (1 = the race's fastest lap). A raw-speed signal that ignores fuel and tyres. Lower is better.",
    "elo": "Field Elo after the driver's last race of the season: a rating of the finishing order against the whole field, so it rates driver plus car. 1500 is average.",
    "elo_teammate": "Team-mate Elo after the driver's last race of the season: updated only on head-to-heads with team-mates (same car), the cleaner driver rating. 1500 is average.",
    # Qualifying
    "poles": "Qualifying sessions topped (before grid penalties).",
    "front_row_rate": "Share of qualifying sessions finished first or second.",
    "q3_rate": "Share of qualifying sessions in which the driver reached Q3 (2006 onwards).",
    "q1_exit_rate": "Share of qualifying sessions in which the driver was knocked out in Q1 (2006 onwards). Lower is better.",
    "avg_quali": "Mean qualifying position. Lower is better.",
    "quali_gap_pole_pct": "Gap to the pole-sitter in percent of the lap: 100 x (driver's time / pole time - 1), compared in the deepest segment the driver set a time in (Q3, else Q2, else Q1) so both laps were run on the same track. Season value is the median. Lower is better.",
    "quali_gap_tm_ms": "Gap to the team-mate in qualifying, in milliseconds: driver's time minus team-mate's time in the deepest segment both set a time in. Negative means faster. Season value is the median over the weekends. Lower is better.",
    "quali_gap_tm_pct": "The team-mate gap in percent of the lap: 100 x (driver's time / team-mate's time - 1), median over the season. Negative means faster. Lower is better.",
    "quali_h2h": "Share of qualifying sessions in which the driver out-qualified his team-mate (by classification).",
    "quali_pace": "Corrected one-lap pace in percent of the lap against the field mean: every driver's Q1/Q2/Q3 times become gaps to each segment's fastest time and a segment offset is removed, so drivers knocked out early are compared fairly. Negative is faster. " + _PR + " Lower is better.",
    "quali_pace_rank": "Rank of the driver's corrected qualifying pace in each session (1 = fastest). " + _PR + " Lower is better.",
    "quali_driver_effect": "The driver part of the season's qualifying-pace decomposition: how much faster (negative) or slower than his team-mate(s) the driver was over one lap, in percent of the lap, shrunk toward zero when the evidence is thin. Lower is better.",
    "grid_drop": "Mean starting slot minus qualifying position: places lost to grid penalties (or gained from others' penalties). Lower is better.",
    # Race pace
    "race_pace": "Corrected race pace in seconds per lap against the field mean, from the lap-time model: each clean lap is explained by car and driver, fuel load, tyre compound and age, track evolution and traffic, and the car-plus-driver term is the pace. Negative is faster. " + _PR + " Lower is better.",
    "race_pace_pct": "Corrected race pace in percent of the reference (median clean) lap. Negative is faster. Lower is better.",
    "race_pace_rank": "Rank of the driver's corrected race pace in each race (1 = fastest). " + _PR + " Lower is better.",
    "race_pace_season_rank": "Rank of the driver's season-mean race pace among drivers with a pace in at least a third of the races (1 = fastest).",
    "race_pace_best_rank": "Best single-race pace rank of the season.",
    "race_pace_tm_delta": "Race pace minus the team-mate's race pace in the same race, seconds per lap. Negative means quicker than the team-mate in the same car. " + _PR + " Lower is better.",
    "race_pace_h2h": "Share of races in which the driver's corrected race pace beat his team-mate's.",
    "driver_effect": "The driver part of the season's race-pace decomposition: pace relative to the team-mate(s) in percent of the lap, after the car's round-by-round level is taken out, shrunk toward zero. Lower is better.",
    "consistency": "Lap-time scatter: standard deviation of the driver's clean laps after removing the fitted fuel and tyre-wear effects, in seconds. Smaller means metronomic. Lower is better.",
    "traffic_cost": "Seconds per race the lap-time model attributes to running in dirty air (within 1.5 s of the car ahead at the start of a lap). Lower is better.",
    "wet_pace_rank": "Mean race-pace rank in races flagged wet (rain in at least 10% of the race's weather samples, or a quarter of the field on intermediates or wets). Lower is better.",
    "sector_best_share": "Sector strength: of the driver's personal-best sector times in each race and qualifying session, the share that were the fastest of the session.",
    "sector_rank": "Mean rank of the driver's personal-best sector times among the session's drivers (1 = the session's best). Lower is better.",
    # Racecraft
    "pos_gained": "Grid slot minus finishing position, over classified finishes. Positive means places gained. " + _PR,
    "lap1_gain": "Grid slot minus running position at the end of lap 1: the start and first lap. " + _PR,
    "late_gain": "Positions gained after lap 1: positions gained minus the lap-1 gain.",
    "overtakes_made": "On-track passes made per race (OpenF1's overtakes, with position changes caused by a pit stop removed).",
    "overtakes_suffered": "Times the driver was passed on track per race. Lower is better.",
    "net_overtakes": "Overtakes made minus overtakes suffered, per race.",
    "pass_difficulty": "Mean pace deficit on the passes the driver made: the overtaker's corrected race pace minus the overtaken car's, seconds per lap. Positive means he passed cars that were faster than him on the day.",
    "overtakes_per_pace": "Overtakes per unit pace deficit: overtakes made per race divided by (0.25 s + the mean pace advantage he had over the cars he passed, floored at zero). High when a driver passes a lot without a big pace edge.",
    "penalties": "Penalties handed down by the stewards in the race and sprint, counted from race-control notices that name the driver's car (served-penalty and no-further-action notices excluded). Lower is better.",
    "penalties_per_race": "Penalties per race. Lower is better.",
    # Tyres
    "deg_soft": "Tyre degradation on the soft compound: seconds per lap lost for every lap of tyre age, from the lap-time model (fuel burn removed). " + _PR + " Lower is better.",
    "deg_medium": "Tyre degradation on the medium compound, seconds per lap per lap of age. Lower is better.",
    "deg_hard": "Tyre degradation on the hard compound, seconds per lap per lap of age. Lower is better.",
    "tyre_mgmt": "Tyre management index: minus 1000 x the mean gap between the driver's degradation and the field median on the same compound in the same race, in milliseconds per lap per lap of age. Positive means his tyres fell away more slowly than the field's.",
    "stint_v_field": "Mean stint length minus the field's median stint on the same compound in the same race, in laps. Positive means longer stints. A final stint cut short by a retirement is left out.",
    "avg_stint": "Mean stint length in laps.",
    "stops_per_race": "Pit stops per race started. Fewer stops for the same result usually means kinder tyre use, so lower ranks higher.",
    "pit_lane_ms": "Median time from pit entry to pit exit for the driver's stops. Lower is better.",
    # Reliability
    "finish_rate": "Share of starts that ended classified.",
    "dnf_rate": "Share of starts that ended unclassified (retired, or disqualified). Lower is better.",
    "dnf_driver": "Retirements the status records as driver-caused: accident, collision, spun off. Lower is better.",
    "dnf_mech": "Retirements the status records as mechanical: engine, gearbox, hydraulics and so on. Lower is better.",
    "dnf_unknown": "Retirements with no published cause (recent seasons only publish 'Retired') and disqualifications. Lower is better.",
    "dns": "Entries that did not start. Lower is better.",
    "laps_share": "Laps completed as a share of the race distances of the races started.",
    "points_lost_dnf": "Expected points (from the forecast at lights-out) in the races the driver did not finish: what the retirements were worth. Lower is better.",
    # Telemetry style
    "brake_earliness": "Braking-point earliness: for each corner, how far before the apex the driver starts braking (median over his laps) minus the field median, averaged over corners, in metres. Negative means later braking than the field.",
    "corner_speed_delta": "Minimum corner speed against the field: the driver's median slowest speed through each corner minus the field median, averaged over corners, km/h. Positive means more speed carried.",
    "full_throttle": "Share of the lap spent at full throttle (98% or more), median over the driver's laps.",
    "braking_share": "Share of the lap spent on the brakes, median over the driver's laps.",
    "coasting": "Share of the lap spent coasting (off the throttle and off the brakes), median over the driver's laps. Lower is better.",
    "speed_trap_kph": "Top speed-trap reading per session (race and qualifying), averaged over the season, km/h.",
    "speed_trap_rank": "Rank of the driver's top speed-trap reading in each session (1 = fastest), averaged. Lower is better.",
    # Points
    "points": "Championship points as awarded (Grand Prix, sprint and fastest-lap points), before any dropped-score rule.",
    "points_per_race": "Points divided by starts.",
    "points_rate": "Share of starts that scored points.",
    "team_points_share": "The driver's share of his team's points in the season.",
    "champ_pos": "Position in the drivers' championship. Lower is better.",
    "exp_points": "Expected points: the sum of the walk-forward forecast's expected points at lights-out (post-qualifying), race by race.",
    "points_v_expected": "Points minus expected points (post-qualifying forecast), summed over the season: points scored beyond what the car, grid slot and form predicted.",
    "points_v_expected_pre": "Points minus the pre-qualifying forecast's expected points: like points v expected, but also credits qualifying.",
    "sprint_points": "Points from sprint races.",
    "sprint_gain": "Sprint grid slot minus sprint finishing position, over classified sprint finishes.",
}

TEAM_DEFINITIONS: dict[str, str] = {
    "points": "Constructors' points as awarded (Grand Prix, sprint and fastest-lap points of every car).",
    "points_per_race": "Points divided by rounds entered.",
    "wins": "Grand Prix wins by either car.",
    "podiums": "Podium finishes by any car.",
    "poles": "Pole positions by any car.",
    "one_twos": "Races the team finished first and second.",
    "both_points_rate": "Share of rounds in which every car that started scored points.",
    "avg_best_finish": "Mean finishing position of the team's better-placed classified car. Lower is better.",
    "avg_best_grid": "Mean starting slot of the team's better-placed car. Lower is better.",
    "exp_points": "Sum of the walk-forward forecast's expected points for the team's cars.",
    "points_v_expected": "Points minus expected points, summed over the team's car-races.",
    "car_race_pace": "The car part of the season's race-pace decomposition, in percent of the lap against the field (negative is faster), averaged over the rounds it was observed. The car's level is a random walk from round to round, so upgrades and circuit swings show up as movement. Lower is better.",
    "car_race_rank": "Mean rank of the car's race-pace state among the teams at each round (1 = fastest). Lower is better.",
    "car_quali_pace": "The car part of the qualifying-pace decomposition, percent of the lap against the field. Lower is better.",
    "car_quali_rank": "Mean rank of the car's qualifying-pace state at each round. Lower is better.",
    "car_pace_trend": "Car race pace over the last third of the rounds minus the first third, percent of the lap. Negative means the car got faster relative to the field. Lower is better.",
    "car_pace_latest": "The car's race-pace state at the latest modelled round, percent of the lap. Lower is better.",
    "top_speed": "Mean of the team's drivers' top speed-trap readings, km/h.",
    "speed_trap_rank": "Mean speed-trap rank of the team's drivers. Lower is better.",
    "corner_speed": "Mean of the team's drivers' minimum-corner-speed deltas against the field (telemetry), km/h.",
    "straightline_bias": "Straight-line v cornering profile: z-score of top speed minus z-score of minimum corner speed across the teams. Positive means a car quicker on the straights than through the corners (low drag); negative a downforce car. Descriptive rather than good or bad.",
    "tyre_mgmt": "Mean of the team's drivers' tyre management index (milliseconds per lap per lap of age better than the field median degradation).",
    "deg_soft": "Mean soft-compound degradation of the team's drivers, seconds per lap per lap of age. Lower is better.",
    "deg_medium": "Mean medium-compound degradation, seconds per lap per lap of age. Lower is better.",
    "deg_hard": "Mean hard-compound degradation, seconds per lap per lap of age. Lower is better.",
    "pit_stop_ms": "Median stationary time of the team's pit stops (OpenF1, wheels stopped to wheels moving). Lower is better.",
    "pit_best_ms": "Fastest stationary pit stop of the season. Lower is better.",
    "pit_under_2500": "Share of the team's stationary times under 2.5 seconds.",
    "pit_slow": "Stops with a stationary time over 4 seconds. Lower is better.",
    "pit_lane_ms": "Median time from pit entry to pit exit for the team's stops. Lower is better.",
    "pit_lane_v_field": "Median over races of the team's median pit-lane time minus the race's median, milliseconds. Negative means quicker through the pit lane than the field. Lower is better.",
    "stops": "Pit stops made by the team's cars.",
    "strategy_gain": "Places gained through the pit stops against the race's norm, per car-race: for each stop, running position the lap before it minus running position two laps after it, less the race's average for a stop.",
    "stops_per_race": "Stops per car-race.",
    "finish_rate": "Share of the team's starts that ended classified.",
    "dnf_rate": "Share of the team's starts that ended unclassified. Lower is better.",
    "dnfs": "Retirements and disqualifications. Lower is better.",
    "dnf_mech": "Retirements recorded as mechanical. Lower is better.",
    "car_share": "How much of the team's model-expected points the car explains, from a Shapley split of simulated expected points between the car and each driver: |car| / (|car| + sum of |drivers|).",
    "lead_driver_share": "Share of the team's points scored by its top-scoring driver. Near 0.5 is a balanced line-up.",
    "quali_h2h_split": "Share of qualifying head-to-heads won by the team's stronger qualifier. Near 0.5 is a close pairing.",
}

MODEL_TERMS: list[dict] = [
    {"key": "lap_time_model", "label": "Lap-time model", "group": "Pace",
     "desc": "Every clean race lap is written as car + driver + fuel load + tyre compound offset + (compound, team and driver degradation) x tyre age + track evolution + traffic + noise, and fitted by robust weighted least squares with ridge shrinkage. The car + driver term, measured against the field mean, is a driver's corrected race pace."},
    {"key": "clean_lap", "label": "Clean lap", "group": "Pace",
     "desc": "A lap the pace model uses: not lap 1, not an in- or out-lap, not under a safety car, virtual safety car or red flag (nor the restart lap after one), and within 93-110% of the race's median clean lap. Other outliers are down-weighted rather than trusted."},
    {"key": "fuel_correction", "label": "Fuel correction", "group": "Pace",
     "desc": "Cars get lighter as fuel burns, about 0.06 s per lap for each lap of fuel on board. The model estimates the coefficient in every race (with a weak prior around 0.06), and since track rubbering-in is also linear in lap number the reported coefficient is the net linear lap trend."},
    {"key": "tyre_degradation", "label": "Tyre degradation", "group": "Pace",
     "desc": "The time a tyre loses per lap of age, seconds per lap per lap, estimated per compound with team and driver adjustments shrunk toward the compound's slope. Tyre age comes from OpenF1 stints (2023 on) or laps since the last stop."},
    {"key": "traffic", "label": "Traffic (dirty air)", "group": "Pace",
     "desc": "Running close behind another car costs time. On each lap the model uses max(0, 1 - interval / 1.5 s) with the interval to the car ahead at the start of the lap, so a car right behind pays the full cost and one 1.5 s back pays nothing."},
    {"key": "track_evolution", "label": "Track evolution", "group": "Pace",
     "desc": "The track gets quicker as rubber goes down. The curved part of that trend over the race is fitted with Legendre polynomials in lap number; its straight-line part is absorbed by the fuel coefficient."},
    {"key": "car_effect", "label": "Car effect", "group": "Pace",
     "desc": "A team's pace in percent of the lap against the field, shared by its drivers. It is modelled as a random walk from round to round, so it can move with upgrades and circuit types, and the posterior is computed exactly by generalised least squares."},
    {"key": "driver_effect", "label": "Driver effect", "group": "Pace",
     "desc": "A driver's pace relative to his team-mate(s) in the same car, one value per season, shrunk toward zero: two equally quick team-mates both get zero and the car carries their level. A driver who changes team links the two cars."},
    {"key": "random_walk", "label": "Random walk", "group": "Pace",
     "desc": "A quantity that moves by an independent random step every round: car(r) = car(r - 1) + noise with sd q x sqrt(rounds apart). q is estimated from the data; it says how fast a car's competitiveness can change."},
    {"key": "shrinkage", "label": "Shrinkage", "group": "Statistics",
     "desc": "Pulling an estimate toward a sensible default (zero, the team-mate, the field average) in proportion to how little data there is. A driver with three races barely moves from the prior; one with twenty is judged on his own laps."},
    {"key": "elo_field", "label": "Field Elo", "group": "Ratings",
     "desc": "An Elo rating on the finishing order against the whole field, updated after every Grand Prix from every pair of drivers (1500 = average, 400 points = 10:1 odds in a straight fight). Mostly a rating of driver plus car."},
    {"key": "elo_teammate", "label": "Team-mate Elo", "group": "Ratings",
     "desc": "An Elo rating updated only on head-to-heads between team-mates, who had the same car: the cleaner driver signal. Ratings flow between teams as drivers change seats; mechanical retirements do not count."},
    {"key": "elo_quali", "label": "Qualifying Elo", "group": "Ratings",
     "desc": "Field Elo on qualifying positions: one-lap pace, car included. Before qualifying classifications exist (pre-1994) the starting grid stands in."},
    {"key": "plackett_luce", "label": "Plackett-Luce", "group": "Ratings",
     "desc": "A model of a finishing order as a sequence of choices: the winner is drawn with probability proportional to each driver's strength, then second from the rest, and so on. Fitted to past results it gives win, podium and points probabilities; used as a cross-check on the race simulator."},
    {"key": "monte_carlo_race_sim", "label": "Monte Carlo race simulation", "group": "Simulation",
     "desc": "The race is run lap by lap thousands of times: each car's lap time draws from its pace and uncertainty, tyres wear, cars stop, overtaking needs a pace margin, safety cars and retirements arrive at random. Win, podium and points probabilities are the shares of simulated races in which they happen."},
    {"key": "safety_car_hazard", "label": "Safety-car hazard", "group": "Simulation",
     "desc": "The chance per lap that a safety car (or virtual safety car) is deployed, estimated per circuit from race control and lap times with a Gamma-Poisson shrinkage to the global rate (about 1.1% per lap). The chance of at least one in a race is 1 - exp(-rate x laps)."},
    {"key": "pit_loss", "label": "Pit loss", "group": "Simulation",
     "desc": "Time a pit stop costs against staying out: (in-lap + out-lap) - 2 x a normal lap, per circuit, shrunk toward 22 s. Under a safety car the loss roughly halves, which is why stops cluster there."},
    {"key": "overtaking_threshold", "label": "Overtaking threshold", "group": "Simulation",
     "desc": "How much quicker a car must be to pass: the simulator passes with probability sigmoid((pace delta - threshold) / 0.25 s), the threshold calibrated per circuit so a typical opportunity passes at the circuit's observed rate. High at Monaco, low at Bahrain."},
    {"key": "dnf_hazard", "label": "Retirement hazard", "group": "Simulation",
     "desc": "The per-lap chance a car retires, split into mechanical (by team) and incident (by driver), each shrunk toward the field's rate, with a separate lap-1 incident rate by grid slot."},
    {"key": "walk_forward", "label": "Walk-forward forecast", "group": "Simulation",
     "desc": "A forecast made only with information available before the event: for a past race, the model is re-run as it stood before qualifying (pre) or before the start (post), never seeing the race itself."},
    {"key": "expected_points", "label": "Expected points", "group": "Simulation",
     "desc": "The mean points a driver scores across the simulated races (sum over positions of probability x points). Points v expected compares what he actually scored."},
    {"key": "championship_sim", "label": "Championship simulation", "group": "Simulation",
     "desc": "The remaining Grands Prix and sprints are simulated together, thousands of seasons at once, with each team's and driver's form drifting through the season so that a team's season stays coherent. Title probabilities are the shares of seasons won."},
    {"key": "magic_number", "label": "Magic number", "group": "Championship",
     "desc": "Points a driver still needs to be sure of the title whatever the rivals do: the most any rival can reach (current points + every point left) minus his points, plus one. Clinched when it reaches zero; eliminated when even winning everything cannot catch the leader."},
    {"key": "countback", "label": "Countback", "group": "Championship",
     "desc": "The FIA tie-break when drivers finish level on points: most wins, then most second places, then thirds and so on (sprint results do not count)."},
    {"key": "dropped_scores", "label": "Dropped scores", "group": "Championship",
     "desc": "Until 1990 only a driver's best results counted (best 4 of the season in 1950, best 11 of 16 in the 1980s, split halves in the 1960s and 70s). Standings for those seasons use the counted points; the raw total is shown alongside."},
    {"key": "de_vig", "label": "De-vig", "group": "Markets",
     "desc": "Market prices add up to more than 100% (the bookmaker's or market's margin). De-vigging rescales them so they sum to one: p_i = price_i / sum of all prices."},
    {"key": "edge", "label": "Edge", "group": "Markets",
     "desc": "The model's probability relative to the market's: model / market - 1. A positive edge means the model rates the runner higher than the market does. Not betting advice."},
    {"key": "midpoint", "label": "Two-sided midpoint", "group": "Markets",
     "desc": "The price used for a prediction market: the mid of the best bid and best ask, only when both exist and the spread is at most 12 cents. A last trade is never used as a price."},
    {"key": "log_loss", "label": "Log-loss", "group": "Calibration",
     "desc": "The forecast scoring rule -mean(y ln p + (1 - y) ln(1 - p)): it punishes confident misses hard. Lower is better; a coin flip scores 0.693."},
    {"key": "brier", "label": "Brier score", "group": "Calibration",
     "desc": "Mean squared error of probability forecasts, mean((p - y)^2). Lower is better; it is gentler than log-loss on confident misses."},
    {"key": "calibration", "label": "Calibration", "group": "Calibration",
     "desc": "Whether events forecast at p% happen p% of the time. Forecasts are binned (0-10%, 10-20%...) and each bin's mean forecast is plotted against how often the event happened; a calibrated model sits on the diagonal."},
    {"key": "baseline", "label": "Baselines", "group": "Calibration",
     "desc": "Simple forecasts the model must beat: grid order (post-qualifying), previous results (pre-qualifying), Elo and Plackett-Luce. A model that cannot beat the grid order adds nothing."},
    {"key": "percentile", "label": "Percentile", "group": "Statistics",
     "desc": "Where a value sits in the season's field from 0 to 100, with 100 always the best (for metrics where lower is better the scale is flipped): 100 x (drivers worse + half the ties) / (drivers - 1). The team-mate percentile does the same within the team."},
    {"key": "standard_error", "label": "Standard error", "group": "Statistics",
     "desc": "The uncertainty of an estimate: roughly two standard errors either side covers the true value 95% of the time."},
    {"key": "car_driver_split", "label": "Car/driver split", "group": "Pace",
     "desc": "A Shapley split of a team's model-expected points between its car and its drivers: every combination of 'average car / own car' and 'average driver / own driver' is simulated and each player's average marginal contribution is his share."},
    {"key": "pace_above_teammate", "label": "Pace above team-mate", "group": "Value",
     "desc": "Minus the decomposition's driver effect, % of a lap (positive = faster): the driver's pace against the team-mate who shares "
             "his car, shrunk toward zero. Measured only within a team, so a driver beside a weak team-mate looks better than he is."},
    {"key": "pace_above_field", "label": "Pace above the field", "group": "Value",
     "desc": "Minus (the car's latest race-pace state + the driver effect), % of a lap: what the driver and his car are worth together now."},
    {"key": "driver_swap", "label": "Driver swap", "group": "Value",
     "desc": "Two drivers on different teams swap seats through the championship simulation of the remaining rounds: each takes the "
             "other's seat pace (plus the driver difference), grid distribution, mechanical risk and team. 1,000 runs a pair with common "
             "random numbers against a baseline; the change is added to the published championship."},
]

_GROUP_ORDER = ["Results", "Qualifying", "Race pace", "Racecraft", "Tyres", "Reliability", "Telemetry style", "Points"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_glossary() -> dict:
    """glossary.json: driver metrics by catalogue group, then the team metrics, then the model terms."""
    from oddsmarkets.f1.analytics.drivers import METRICS as DM
    from oddsmarkets.f1.analytics.teams import METRICS as TM
    groups: dict[str, list[dict]] = {}
    for m in DM:
        groups.setdefault(m["group"], []).append({"key": m["key"], "label": m["label"], "desc": DRIVER_DEFINITIONS.get(m["key"], ""),
                                                  "fmt": m["fmt"], "lower": bool(m["lower"]), "scope": m["scope"], "group": m["group"],
                                                  "kind": "driver"})
    ordered = [g for g in _GROUP_ORDER if g in groups] + [g for g in groups if g not in _GROUP_ORDER]
    out = [{"name": g, "entries": groups[g]} for g in ordered]
    out.append({"name": "Team metrics", "entries": [
        {"key": m["key"], "label": m["label"], "desc": TEAM_DEFINITIONS.get(m["key"], ""), "fmt": m["fmt"], "lower": bool(m["lower"]),
         "scope": m["scope"], "group": m["group"], "kind": "team"} for m in TM]})
    return {"groups": out, "model": MODEL_TERMS, "updated_at": _now()}
