# Models: technical reference (F1)

This document covers every statistical model behind The Quant Paddock. It is
written for whoever maintains or extends the models. Each parameter and formula
below was read from the code under `oddsmarkets/f1/` and `oddsmarkets/common/`.
Where the code, its docstrings and the site's Methodology page
(`docs/paddock/assets/js/docs.js`) disagree, this document follows the code;
section 17 lists every disagreement found.

Paths are relative to the repository root. "The build" is
`scripts/build_paddock.py`. Units: race pace is seconds per lap against the field
mean; decomposition effects and qualifying pace are percent of lap time; negative
is faster in both.

---

## 1. Overview

### 1.1 How the models feed each other

```
season stores (Jolpica)            OpenF1 session records (2023-)
  │                                  │
  ├──────────── canon.py (numbers → driverIds, sessions → rounds) ─────────────┐
  │                                                                            │
  ├─► laptime.race_pace(year, round) ── corrected pace per driver, deg, traffic ◄┤
  │        │                                                                    │
  │        ▼                                                                    │
  │   decomposition.season_effects ── car random walk + driver effect (race) ───┤
  │   decomposition.quali_pace ─────── car random walk + driver effect (quali)  │
  │        │                │                                                   │
  │        │                └─► qualifying.quali_model ── grid distribution     │
  │        ▼                                │                                   │
  ├─► race_sim.results_strength (results-only estimator)                        │
  │        │                                │                                   │
  │        ▼                                ▼                                   │
  │   race_sim.race_inputs ◄── circuits.circuit_profile (history, shrunk) ◄─────┘
  │        │
  │        ├─► race_sim.simulate_race ─► analytics/forecasts (pre / post / sprint, walk-forward)
  │        │                                 └─► race centre, expected points, awards, markets
  │        ├─► championship.simulate_championship ─► season.json, markets.json
  │        └─► backtest.backtest ─► calibration.json
  │
  ├─► elo.elo_history (field, teammate, qualifying Elo from 1950) ─► elo.json, careers, backtest baseline
  ├─► common/ranking (Plackett-Luce) ─► backtest baseline
  └─► sources/markets (Kalshi, Polymarket) ─► markets.json (model v market)
```

### 1.2 Model inventory

| Model | Code | Used by |
|---|---|---|
| Lap-time (corrected race pace) | `oddsmarkets/f1/models/laptime.py` | decomposition, driver and team catalogues, race centre, awards |
| Car/driver decomposition | `oddsmarkets/f1/models/decomposition.py` | race simulator blend, qualifying model, catalogues, season.json |
| Qualifying (pre-qualifying grid) | `oddsmarkets/f1/models/qualifying.py` | race simulator before qualifying |
| Circuit profiles | `oddsmarkets/f1/models/circuits.py` | race simulator, circuit pages |
| Race simulator | `oddsmarkets/f1/models/race_sim.py` | forecasts, championship, backtest |
| Championship simulator | `oddsmarkets/f1/models/championship.py` | season.json, markets.json |
| Elo | `oddsmarkets/f1/models/elo.py` | elo.json, careers, catalogues, backtest |
| Plackett-Luce | `oddsmarkets/common/ranking.py` | backtest |
| Car/driver points split | `oddsmarkets/f1/analytics/teams.py` (site); `decomposition.car_driver_split` (not used by the build) | teams.json, season.json |
| Walk-forward forecasts | `oddsmarkets/f1/analytics/forecasts.py` | race centre, catalogues, awards, markets |
| Backtest | `oddsmarkets/f1/models/backtest.py` | calibration.json |
| Markets | `oddsmarkets/f1/sources/markets.py`, `oddsmarkets/common/{markets,prediction_markets}.py` | markets.json |
| Telemetry processing | `oddsmarkets/f1/telemetry.py` | telemetry summaries, telemetry-style metrics |

Every public model function returns empty results with a `reason` rather than
raising on missing data.

---

## 2. Lap-time model: `models/laptime.py`

**Purpose.** Corrected race pace per driver for one Grand Prix: what each car
and driver was worth per lap once fuel, tyres, track evolution and traffic are
taken out.

**Entry point.** `race_pace(year, round)` → `{"drivers": {driverId: {"pace", "se",
"laps", "deg": {compound: s/lap/lap}, "traffic_cost", "pace_pct", "team"}},
"fuel_coef", "excluded", "traffic_coef", "compound_offset", "compound_deg",
"track_evo", "sigma", "rho", "ref_lap_s", "n_clean", "n_laps", "source",
"neutral_laps"}`. Cached in `data/f1/cache/pace/<year>_<round>.json` under a SHA-1
of `MODEL_VERSION = "laptime-2"`, the race's store rows and the session record.

**Inputs.** The OpenF1 race session when it is on disk (2023 onward) and at least
`max(3, half of its car numbers)` map to drivers; otherwise the season store's
Jolpica laps and pit stops.

### 2.1 Equation

For driver i (team t) on lap L, on compound c with tyre age a:

```
lap_{i,L} = team_t + dev_i
          + fuel · F_{i,L}
          + off_c + (g_c + tdeg_{t,c} + ddeg_{i,c}) · a
          + e2 · P2(u_L) + e3 · P3(u_L)
          + k · traffic_{i,L}
          + eps_{i,L}
```

- `F` is laps of fuel on board: laps remaining `N − L` from 2010, laps to the
  driver's next stop (or the flag) in the refuelling era 1994–2009.
- `u_L = 2(L − 1)/(N − 1) − 1`; `P2 = (3u² − 1)/2`, `P3 = (5u³ − 3u)/2`. The linear
  part of track evolution cannot be separated from fuel burn, so `fuel_coef` is
  the net linear lap trend ("s per lap of fuel on board, net of linear track
  evolution"). In the refuelling era a linear `P1(u) = u` term is added.
- Tyre age: OpenF1 `tyre_age_at_start` plus laps into the stint (2023 on);
  before that, laps since the last stop on one compound `"UNKNOWN"` (new tyres
  assumed). OpenF1 compounds `NONE`, empty and `TEST_UNKNOWN` also become
  `UNKNOWN`. `off_c` is relative to the most-used compound.
- `traffic = max(0, 1 − interval / 1.5 s)` from the OpenF1 `lap_end` interval at
  the end of lap L − 1 (`TRAFFIC_WINDOW_S = 1.5`); the term is fitted only when
  intervals exist and some lap has traffic.

### 2.2 Priors (ridge penalties), `PRIOR_SD` and `PRIOR_MEAN`

| Term | Prior mean | Prior sd |
|---|---|---|
| team intercept | 0 | 100 s (effectively free) |
| `dev` (driver relative to team) | 0 | 0.5 s |
| fuel | 0.06 s per lap of fuel (≈1.7 kg/lap at ≈0.035 s/kg) | 0.05 |
| compound offset | 0 | 10 s |
| compound slope `g` | 0 | 1.0 s/lap |
| team slope deviation `tdeg` | 0 | 0.03 s/lap |
| driver slope deviation `ddeg` | 0 | 0.02 s/lap |
| traffic `k` | 0 | 10 s |
| track evolution (P2, P3, P1) | 0 | 0.5 s |

### 2.3 Clean laps (`assemble`)

Each lap gets at most one exclusion, checked in this order: `missing`; `lap1`;
`pit` (the in-lap or the out-lap after it; in-laps from the Jolpica and OpenF1 pit
tables, the lap before an OpenF1 `pit_out` lap, the lap before any stint after the
first; with no pit data at all, before 2011, a green lap above 110% of the
driver's median with at least 5 such laps); `neutralised`; `outlier` (outside
`CLEAN_BAND = (0.93, 1.10)` of the median clean lap).

Neutralised laps come from three rules:

- **Field median** (every season): a lap whose median over at least 3 cars exceeds
  `NEUTRAL_FIELD_RATIO = 1.07` × the race's median lap, plus the lap after each
  neutralised block (the restart).
- **Race control** (OpenF1, `_neutral_windows`): SC from "SAFETY CAR DEPLOYED" to
  "SAFETY CAR IN THIS LAP" / "ENDING" / "ENDED" plus 1.5 reference laps; VSC from
  "VSC DEPLOYED" to "VSC ENDING" plus 20 s; red flag from flag RED, a "RED FLAG"
  message or SessionStatus "ABORTED"/"SUSPENDED" until a track GREEN or
  SessionStatus "STARTED"/"RESUMED", plus one reference lap. A lap whose time span
  overlaps a window is excluded.
- **Unclosed windows** end at the leader's start of the first green lap after
  them, else 5 reference laps after they opened. The Monza 2026 case in
  `tests/f1/test_pace.py` (red flag as an "Other" message, a safety car never
  declared "in this lap") is the reason this exists.

### 2.4 Fit (`fit_race`)

At least 10 clean laps, else no pace. Ridge-regularised weighted least squares with
Huber IRLS (`HUBER_K = 1.345`):

```
beta = (X'WX + Lambda)^-1 (X'Wy + Lambda mu0),   Lambda = diag(sigma² / prior_sd²)
```

Starting at sigma = 0.5 s; each iteration solves for beta, sets sigma to
1.4826 × MAD of the residuals (floor 0.02 s), and reweights (1 inside 1.345 sigma,
1.345/|z| outside). At most 15 iterations; stops when weights and sigma move less
than 1e-4. Laps with final weight below 0.5 are counted as `downweighted`.

Standard errors: residual variance `sum(w r²) / (sum w − p)`; covariance
`sigma² (X'WX + Lambda)^-1`, inflated by `(1 + rho)/(1 − rho)` for the lag-1
autocorrelation of a driver's consecutive residuals (estimated with more than 10
pairs, clipped to [0, 0.6]). `pace_i = (team_t + dev_i) − mean over drivers`, with
its se from the same contrast. `pace_pct = 100 × pace / median clean lap`.

---

## 3. Car/driver decomposition: `models/decomposition.py`

**Purpose.** Split a season's pace into a car effect per constructor that moves
from round to round, and a driver effect per driver that is fixed for the season,
for race pace and for qualifying pace separately.

```
y_{i,r} = car_{t,r} + u_{t,r} + drv_i + e_{i,r},   e ~ N(0, se_{i,r}² + tau²)
car_{t,r} = car_{t,r'} + eta,               eta ~ N(0, q² (r − r'))     r' = previous modelled round
u_{t,r} ~ N(0, kappa²)                      this round only: the car's fit to the circuit, shared by team-mates
car_{t,first} ~ N(0, 2²)  (CAR0_SD = 2.0),  drv_i ~ N(0, sigma_d²)
```

- **Race observations**: `100 × race_pace / ref_lap_s` with the se converted the
  same way, for every completed round with pace.
- **Qualifying observations** (`quali_pace`): each driver's Q1/Q2/Q3 times as %
  gaps to the segment's best, dropping times above `QUALI_SEG_CUTOFF = 1.05` ×
  best; `gap_{i,s} = a_i + b_s` solved by least squares (`b_Q1 = 0`), `a` centred
  on the field mean, `se = QUALI_OBS_SD / sqrt(segments) = 0.10% / sqrt(n)`.
- **Identification**: team-mates share `car_{t,r}`, so `drv_i` is the within-team
  difference; a driver who changes team mid-season links both cars. Equal
  team-mates both get `drv = 0`.
- **Estimation**: exact GLS on the stacked state vector (car states, driver effects,
  one u per team and round) with the random-walk prior as a banded precision matrix
  (the Kalman smoother's answer). `sigma_d, tau, kappa` maximise the marginal
  likelihood plus a log-normal hyperprior (`HYPER_PRIOR_LOGSD = 0.7`), by L-BFGS-B on
  logs with bounds [0.005, 3]. The walk step q is fixed (`Q_FIXED`: race 0.06,
  qualifying 0.07, % per round); `Q_FIXED = None` fits it as well. Fewer than 4
  observations: no fit. `TEAM_ROUND_NOISE = False` drops u (the model before
  October 2026).

| Hyperprior centre (`HYPER_PRIOR`) | q (% per round) | sigma_d (%) | tau (%) | kappa (%) |
|---|---|---|---|---|
| race | 0.15 (fixed at 0.06) | 0.20 | 0.30 | 0.25 |
| qualifying | 0.10 (fixed at 0.07) | 0.15 | 0.15 | 0.15 |

**Why u and a fixed q** (October 2026). Without u every circuit-specific swing of a
car (shared by both drivers, gone by the next round) is read as a step of the random
walk: the fitted q came out around 0.37% per round in 2026 and the latest car state
followed the last race, which made Red Bull the fastest car on one strong round.
Walk-forward check (fit through round r − 1, predict each driver's observed pace at
round r; mean over rounds, then over the 15 seasons 2012–2026):

| Variant | Gaussian log-loss | Spearman | MSE (%²) |
|---|---|---|---|
| race, before (fitted q, no u) | 0.828 | 0.765 | 0.328 |
| race, with u, fitted q | 0.782 | 0.776 | 0.301 |
| race, with u, q = 0.05 | 0.772 | 0.779 | 0.295 |
| race, with u, q = 0.07 | 0.772 | 0.780 | 0.295 |
| qualifying, before | 0.705 | 0.789 | 0.232 |
| qualifying, with u, q = 0.07 | 0.685 | 0.796 | 0.222 |

u lowered the log-loss in every one of the 15 seasons; q between 0.05 and 0.07 was
best and flat. With both, 2026 through round 15 ranks Ferrari, Mercedes, McLaren,
then Red Bull.

`season_effects(year, upto_round)` returns `car`, `driver`, `quali_car`,
`quali_driver`, `params` and `reasons`. The build computes it for every season
from 1994 (`build_season`).

---

## 4. Qualifying model: `models/qualifying.py`

**Purpose.** The pre-qualifying grid forecast for a round, from the qualifying
decomposition fitted through the previous round.

```
pace_i = car_t + drv_i + eps_i
car_t ~ N(car_{t,R'}, se² + q² (R − R') + kappa²),   drv_i ~ N(drv_hat, se_i²),   eps_i ~ N(0, tau²)
```

- Team-mates share one car draw per simulation.
- A driver without an effect gets `N(0, sigma_d²)` (0.15 if the fit has none); a
  team without one `N(0, 1²)` (`NEW_TEAM_SD`). Missing tau → 0.15, missing q → 0.1.
- At round 1, or when the season has no qualifying effects yet, the previous
  season's final states are carried with extra winter variance `WINTER_CAR_SD² =
  1.0²` per car and `WINTER_DRIVER_SD² = 0.1²` per driver.
- No circuit-type adjustment (the store has no lap length).
- **Practice** (October 2026, `practice_shift`): when the weekend's sessions before qualifying are on disk
  (OpenF1 Practice 1-3 and Sprint Qualifying, 2023 on), each driver's mean moves toward his practice one-lap
  pace `x_i` (`models/practice.py`: best lap as a % gap to the session's best, within 107%, field-centred,
  sessions weighted FP1 0.5, FP2 1, FP3 1.5, SQ 3): `mean_i = (1 − w) mean_i + w (x_i + offset)`, the offset
  re-centring x on the model's mean over the same drivers; variances unchanged; needs at least half the field.
  `w = PRACTICE_SHORT_W = 0.5` (fitted file key `qualifying.PRACTICE_SHORT_W`). A strict walk-forward pick on pole
  log-loss (trained on 2023, expanding) is 0.25 in each season, pole log-loss 2024–2026 1.824 → 1.628; 0.5 is
  best over all 2023–2026 pole data (1.611 against 1.616) and better for the winner, 2024–2026 pole 1.584 and
  winner before qualifying 1.711 → 1.640 through the grid distribution. Only sessions that start before Grand
  Prix qualifying count (2023 sprint weekends held it on Friday, before the shootout and the sprint). `quali_model(..., use_practice=False)` gives
  the pre-weekend forecast; `meta.practice` says what was used. Long-run (race-simulation) practice pace is
  computed by `practice.long_runs` but not used: at every weight tried it made the winner forecast worse
  (docs/research/f1_edge.md).

`quali_model(year, round, n_sims=20000, seed=11)` → per driver `mu_gap_pct`,
`sd`, `p_pole`, `grid_dist` (P(P1)...P(Pn)), `exp_grid`. The race simulator calls
it with 4,000 simulations.

---

## 5. Circuit profiles: `models/circuits.py`

**Purpose.** Per-circuit parameters for the simulator, learned from every race
since 1996 (`FIRST_YEAR`) and shrunk toward a global profile by sample size.
`circuit_profile(circuit_id, before=(year, round))` uses only races strictly
before the cutoff. Per-race records are cached in
`data/f1/cache/circuit_records.json` (`RECORDS_VERSION = 6`).

Weights: `w = 0.5^((Y − y) / 4)` (`HALF_LIFE_YEARS = 4`), Y the cutoff season.
Basic estimator `(sum w x + k g) / (sum w + k)`.

| Quantity | Global prior (`PRIOR`) | Shrinkage |
|---|---|---|
| race laps | 57 | none: the winner's laps at the latest full-distance race there (a race under 90% of the median of the last three is skipped) |
| pit loss | 22.0 s | `K_PIT = 2` races |
| SC hazard per lap | 0.011 | `K_LAPS = 150` laps of exposure |
| VSC hazard per lap | 0.006 | 150 laps |
| pass probability per opportunity | 0.18 | `K_PASS = 40` opportunities |
| mean pace delta of an opportunity | 0.6 s | 40 |
| typical stops per finisher | 1.6 | `K_STOPS = 2`, clipped to [1, 3] |
| wet probability | 0.12 | `K_WET = 2` |
| mechanical / incident DNF per starter | 0.040 / 0.035 | 40 starts globally; circuit multipliers `(obs + 5)/(exp + 5)` |
| lap-1 incident per starter | 0.012 | pooled 50 starts; per grid slot `K_LAP1_SLOT = 20` |
| mechanical share of unknown retirements | 0.53 | 20 retirements |
| SC share of neutralisations | 0.65 | 5 events |
| first-lap position change by slot | mean 0, sd 1.2 + 0.05 × slot | `K_SLOT = 30` starts; circuit sd scale `K_LAP1_SD = 3` |

Details:

- **Length**: `length_km = 305 / laps` (260.3 at Monaco); sprint laps
  `ceil(100 / length_km)`.
- **Reference lap** (`ref_lap_s`, `reference_lap`): the median green lap (median over
  laps after lap 1 of the field-median lap time) of the circuit's latest race with lap
  times; with none, the median over the latest season's races; else 90 s
  (`REF_LAP_DEFAULT`). Monaco 78.9 s, Spa 107.9 s, Monza 83.7 s, Bahrain 98.6 s
  before 2026 round 10. Records carry it from `RECORDS_VERSION = 6`.
- **Pit loss**: per stop `(in-lap + out-lap) − 2 × ref`, ref the driver's median
  green lap in laps l−4..l+5; losses outside 8–45 s dropped; race value the
  median. Before 2011 stops are detected on green laps where `lap_l + lap_{l+1} −
  2 ref > 12 s`. OpenF1 pit-lane times are kept as `pit_lane_s`.
- **SC/VSC**: from 2023, OpenF1 race-control deployments (a red flag counts as
  half an SC event); before, laps whose field median exceeds `NEUTRAL_FACTOR =
  1.20` × the race's median green lap, each run after lap 1 one event, split by the
  OpenF1-era SC share (all SC before 2015). `p_sc_race = 1 − exp(−rate × laps)`.
- **Overtaking**: an opportunity is a car directly behind another at the end of
  lap k − 1, within 1.5 s, at least 0.3 s faster on its previous three laps' median,
  both laps green. Success = ahead at the end of lap k.
  `overtake_threshold_s = d_bar − 0.25 × logit(pass_prob)`, clipped to
  [0.2, 2.5]; `overtake_difficulty = clip(1 − pass_prob / (2 g), 0.02, 0.98)`.
- **Classification** (`status_kind`): numeric `position_text` = finished
  (including "Retired" rows classified on distance); W/F or a did-not-start status
  = dns; D/E = dsq; otherwise a DNF split by keyword into `dnf_incident`,
  `dnf_mech` and `dnf_unknown`.
- **Wet**: any OpenF1 rainfall sample during the race (2023 on). Note that
  `analytics/context.wet()` uses a stricter definition for the wet-pace metric (at
  least 10% of in-race samples with rainfall, or a quarter of drivers on
  intermediates or wets).

---

## 6. Race simulator: `models/race_sim.py`

A vectorised lap-by-lap Monte Carlo of n races at once (`simulate_race(inp, n=20000,
seed)`), about 2.5 s for 20,000 runs of 22 cars over 57 laps.

### 6.1 Inputs: `race_inputs(year, round, before_quali, session="race", use_a=True)`

Built only from data strictly before the race, plus the race's own grid when
`before_quali` is False. The entry list is the round's qualifying or results
rows, or for a future round the latest completed round's results. The circuit
profile is cut off at the race; a circuit with no history takes its laps from the
schedule.

**Results-only pace estimator** (`results_strength`, `_fallback_pace`). Every
race, qualifying and sprint result of the current and two previous seasons
becomes a normal score `z = Phi^-1((rank − 0.5) / N)` (races and sprints: rank
among classified finishers, N = starters; qualifying: position, N = entries),
weighted

```
w = KIND_W[kind] · SEASON_W[seasons back] · 0.5^(races_ago / 6)
KIND_W = {race 1.0, quali 0.8, sprint 0.5}
SEASON_W = {0: 1.0, 1: 0.35, 2: 0.12};  after a reset (REG_RESET = {2014, 2017, 2022, 2026}): {1: 0.08, 2: 0.03}
z_team = (sum_team w z + 1 · 0.5) / (sum_team w + 1)       race and sprint observations; 0.5 = NEW_ENTRY_Z
z_d    = (sum w z + 2 · z_team) / (sum w + 2)               K_TEAM = 2
mu_d   = 0.90 · z_d % of lap     PACE_PER_Z_PCT = 0.90 (walk-forward, 2014-2026; was 0.40 s ≈ 0.444%)
sd_d   = 0.90 · 0.7 / sqrt(sum w + 2)
```

Every pace is in % of lap until the inputs are assembled and is then converted to
s/lap with the circuit's reference lap (section 5). The simulator's time constants
(day sds, lap noise, fuel, default degradation, fastest-lap noise) are stated for a
90 s lap (`REF_LAP_S`) and scale with `ref / 90`; the base lap is the reference lap.

**Blend with the decomposition** (`_a_pace`): when `season_effects` is importable
and the round is not the first, the latest car effect plus the driver effect
through the latest completed round, in % of lap, se `sqrt(se_car² + se_drv²)`, blended

```
mu = w_A A_PACE_SCALE mu_A + (1 − w_A) mu_results,   sd² = w_A sd_A² + (1 − w_A) sd_results²,   w_A = n / (n + 40)
```

with n the rounds with observed race pace (`A_BLEND_K = 40`, walk-forward; it was 4)
and `A_PACE_SCALE = 1`. Used only if it covers at least 80% of the field; uncovered
drivers get the slowest covered pace plus 0.35%, sd 0.45%. `A_CARRY_ROUNDS` (0, off)
would let round 1 use last season's final effects; an early scan (counting them as 2 rounds) gained about 0.005 nats, too little to keep without re-testing under the final constants.

The code is split into `race_components` (everything that does not depend on the
tunable constants: entry, circuit profile, reference lap, raw results observations,
decomposition pace, grid or grid distribution) and `inputs_from_components`; the
tuner caches the first. Fitted constants are read at import from
`oddsmarkets/f1/models/fitted/race_params.json` (`PACE_PER_Z_PCT = 0.9`,
`A_BLEND_K = 40`, `PRE_GRID = "quali_model"`); `set_params` overrides them.

**This round's qualifying pace** (October 2026). After qualifying (`race_components` with the grid known, Grand
Prix only), `round_quali_pace` takes the round's Q1–Q3 times through `decomposition.quali_pace` (% of lap,
field-centred) and the pace becomes

```
mu_d = (1 − w) mu_d + w (q_d + offset),   sd_d = QUALI_PACE_SD_MULT · sd_d,   w = QUALI_PACE_W
```

the offset re-centring q on mu over the same drivers. `QUALI_PACE_W = 0.4`, `QUALI_PACE_SD_MULT = 0.5` (fitted
file), chosen on 2014–2022 from a grid of w 0.25–0.75 and sd multipliers 0.35–1.0 (3,000 simulations a race):
winner log-loss after qualifying 2014–2022 1.341 → 1.279; 2023–2026, not used for the choice, 1.198 → 1.106
(3,000 simulations, after the laps fix of section 5). The win temperature fitted on 2014–2022 is then 1.007; over
2014–2026 it is 1.17, so the remaining timidity sits in 2023–2026. Before October 2026 the post-qualifying
forecast used the grid slot only, and Polymarket's winner prices were 0.16–0.21 nats a race sharper than it
(docs/research/f1_edge.md).

**Grid.** After qualifying, the actual grid (pit-lane starters last). Before, each
driver's slot is drawn from `qualifying.quali_model`'s `grid_dist` with uniform
jitter and ranked (`PRE_GRID = "quali_model"`); `"results"` uses `z_q + 0.55 eps`
(`QUALI_NOISE_Z`) ranked, `"blend"` mixes the two draws' ranks with weight
`PRE_GRID_MIX`. The quali model was best over 2014–2026 at 2,000 simulations.

**Retirement hazard** (`_dnf_hazards`), excluding lap-1 retirements:

```
p_m = (sum w mech + 8 g_m) / (sum w starts + 8) × circuit mech multiplier        per team,   K_MECH = 8
p_i = (sum w inc + 12 g_i) / (sum w starts + 12) × circuit incident multiplier   per driver, K_INC = 12
h   = −ln(1 − min(0.6, p_m + p_i)) / laps
```

`g_i` is the global incident rate minus the mean lap-1 incident rate, floored at
0.005; unknown statuses split by the mechanical share.

### 6.2 Simulation steps

| Step | Rule (constants in `race_sim.py`) |
|---|---|
| race-day pace | `x_d = mu_d + sd_d e1 + 0.16 e2(team) + 0.05 e3` (`DAY_TEAM_SD`, `DAY_DRIVER_SD`, × ref/90; the driver day sd was 0.10 until 21 October 2026, fitted file) |
| lap 1 | `score = slot + m[slot] + 0.4 s[slot] k_c e + B·Exp(8) − 1.0 (x_d − median x)`, B = 1 with p 0.02 (`LAP1_SD_MULT`, `LAP1_BAD_P`, `LAP1_BAD_SCALE`; 0.10 until 21 October 2026, fitted file), ranked; cars 0.65 s apart (`LAP1_SPACING`); lap-1 retirement with the slot's incident probability, capped at 0.5 |
| lap time | `x_d + deg · age + 0.06 (L − lap) + 0.35 e` (× ref/90) + the reference lap (`DEG_DEFAULT = 0.06`, `FUEL_PER_LAP = 0.06`, `LAP_SD = 0.35`) |
| strategy | the race's stops `k_race = 1 + Binomial(2, (m − 1)/2)` drawn once per simulation; each car k_race ± 1 with p 0.1 (`STOP_DEV_P`), clipped to [1, 3]; stop j at `L j/(k+1) + N(0, 0.07 L)`; cost `pit_loss + N(0, 0.6)`, slow stop +U(4, 8) s with p 0.03; under SC 0.5 × pit loss, under VSC 0.65 ×; planned stops within 6 laps of a neutralisation brought forward (`PIT_WINDOW`); sprints no stops |
| overtaking | front to back; a car finishing the lap within 0.4 s (`HOLD_GAP`) of the nearest non-pitting car ahead must pass: `P = sigmoid((dpace − thr) / 0.25)`, dpace without lap noise; success puts it 0.1 s ahead (`PASS_MARGIN`), failure 0.4 s behind; no passing under SC/VSC; only the nearest car ahead is checked |
| SC / VSC | per green lap SC with `sc_rate` (×3 on lap 1, `LAP1_SC_MULT`) for 3–5 laps, else VSC with `vsc_rate` for 2–3 laps; an SC resets gaps to 0.8 s per position; neutralised laps take 1.4 × (SC) or 1.3 × (VSC) the reference lap |
| retirements | retirement lap drawn once as `1 + Geometric(1 − e^−h)`; classified with at least `ceil(0.9 L)` laps (`CLASSIFIED_SHARE`) |
| wet | all sims when `wet`, else each with the circuit's `p_wet`: day sd ×1.6, lap noise ×2, SC/VSC ×2.5, DNF hazard ×1.8, lap-1 spread ×1.3 (`WET`) |
| classification | running cars by total time, then retired cars by laps completed |
| points | the season's table to classified cars; the fastest lap to the best `x_d + N(0, 0.3)` among running cars, with the bonus point only for a classified top-10 finisher in seasons that had it |

**Why lap 1 and strategy changed** (October 2026, the cause of the underconfident
favourites; checked against the data, not tuned on log-loss):

- *Strategy.* Drawing each car's number of stops independently made the simulated
  winner and runner-up differ in stops in 58% of races; in 2011–2025 they differed in
  19%, and 72.5% of finishers ran the race's modal count. A favourite on an extra stop
  loses 7–30 s, so the old draw turned clear favourites into coin flips. With one
  strategy per race and `STOP_DEV_P = 0.1`, the pair differs in about 19%.
- *Lap 1.* The circuit profile's per-slot sd is the sd of observed lap-1 moves, tail
  included, and ranking every car's noisy score moves a car by its neighbours' noise
  as well as its own: the pole-sitter led after lap 1 in 34% of simulations against
  72% of races (2014–2025). The core-plus-tail form was fitted to the observed share of
  each slot (1–10) keeping its place, losing three or more and gaining two or more.
- *Checked and left alone:* SC/VSC probability (2023 on: predicted 53% / 32% of races,
  observed 52% / 32%), the DNF hazard (halving it worsened DNF log-loss), and the
  pit-under-SC window (6 laps: 32% of cars pit under a simulated SC, 34% in the
  2023–2025 OpenF1 pit records, with the same spread across safety cars).

`points_system(year)`: race points 25-18-15-12-10-8-6-4-2-1 from 2010,
10-8-6-5-4-3-2-1 2003–09, 10-6-4-3-2-1 1991–2002, 9-6-4-3-2-1 before (a
simplification); sprint 3-2-1 in 2021, 8-7-6-5-4-3-2-1 from 2022; fastest-lap point
2019–2024 by rule, overridden by `fastest_lap_point_in_data(year)` when the
season's results decide it (2025 removed it).

Outputs per driver: `p_win, p_podium, p_points, p_dnf, exp_pos, exp_points,
pos_dist`; per team `exp_points, p_double_points`; per race `p_sc, p_vsc, p_wet`.

---

### 6.3 Post-qualifying win temperature and the 21 October 2026 constants

The model-improvement program of October 2026 (docs/research/f1_edge.md, "Model-improvement program, Oct 2026")
changed three things, all chosen without the 2023–2026 test races:

- `DAY_DRIVER_SD` 0.10 → 0.05 and `LAP1_BAD_P` 0.10 → 0.02 (fitted file). Chosen on 2014–2022 winner log-loss after
  qualifying among 21 configurations (day sds, pace spread and sd multipliers, lap-1 tail and core, overtaking
  threshold; 3,000 simulations, common random numbers): 2014–2022 1.2790 → 1.2732. On 2023–2026 (87 races, sealed):
  1.1083 → 1.0827, paired difference −0.0256 [−0.0346, −0.0155]; podium log-loss −0.0017 per driver-race. Before
  qualifying the same constants give −0.0082 [−0.0167, +0.0012] (not significant). The lower lap-1 tail also fits
  the data better: the old constants let the pole-sitter lead after lap 1 in 56% of simulations against 72% of
  races (2014–2025).
- `WIN_TEMP_POST` (fitted file, `scripts/f1_tune.py wintemp`): for every Grand Prix from 2014, the temperature T
  minimising the winner log-loss of p^T over all earlier races (walk-forward; 1.0 for the first 20), plus "latest"
  over every race for rounds after the fit. `race_sim.temper_win` applies it to the post-qualifying win
  probabilities only (`forecasts.forecast(..., "post")`, `backtest` `model_post`), capped at the podium probability;
  positions, podium, points and the championship stay the simulator's own. Refit with every backtest run.
  It is a lagging correction: on 2014–2022, where the raw simulator was calibrated, the walk-forward temperature
  costs +0.0073 [+0.0025, +0.0123] a race; over all 269 races it is level. It is kept because 2023 on is timid.
- Together, against the 2 October production model on 2023–2026: winner log-loss after qualifying −0.0417
  [−0.0584, −0.0227], Brier −0.0178 [−0.0261, −0.0089], podium −0.0017 [−0.0027, −0.0007]; calibration slope of
  the win probabilities 1.74 → 1.56 (intercept 0.93 → 0.67), ECE 0.0206 → 0.0174. The temperature alone on top of
  the new constants gains −0.0161 [−0.0256, −0.0058].

Not changed (tested): wider pace spread (helps 2023–2026, hurts 2014–2022: an era effect a fixed constant cannot
pick up honestly), smaller pace sd, harder overtaking (worse everywhere), a market-informed prior from earlier
races' prices (no gain), a rolling 44-race temperature (−0.055 [−0.130, +0.033], too noisy).

## 7. Championship simulator: `models/championship.py`

`simulate_championship(year, n=20000, seed)`: current points summed from the
store's results and sprint rows as awarded; every round without results simulated
(a sprint first where the round has a sprint session and no sprint results), using
the actual grid where qualifying (or the sprint grid) is in the store.

Season-level correlation per simulation s:

```
offset_{s,d,r} = sd_{d,r} z_{s,d} + F_{s,team,r} + G_{s,d,r}
z ~ N(0, 1) once per season;   F_r = F_{r−1} + N(0, 0.06) (TEAM_FORM_STEP);   G step 0.03 (DRIVER_FORM_STEP)
```

Each race is then simulated with `draw_param=False` (no fresh parameter draw).

- **Countback**: points, then GP wins, seconds, ... (sprints do not count), as one
  integer key `(2 × points) << (places × bits) | counts`: drivers 10 places × 5
  bits, constructors 8 places × 6 bits. Identical keys split at random.
- **Magic numbers** (no simulation): R = the most points anyone can still score
  (per GP the winner's points plus the fastest-lap point where awarded; per sprint
  the winner's; constructors the top two places). `magic_d = max over rivals of
  (P_r + R) − P_d + 1`; clinched when ≤ 0; eliminated when `P_d + R` < the leader's
  points; `can_clinch_alone` when magic ≤ R.
- **Conditionals**: for the leader, per remaining GP, `p_win_round`,
  `p_title_if_win`, `p_title_if_not_win`; for the next round, the same for every
  contender with `p_title ≥ 0.005`.
- Outputs: `p_title`, expected points, points quantiles (5, 25, 50, 75, 95),
  position distribution, expected position, per-round expected points.

The build runs it with `--sims` (default 20,000) and `seed=year` for the current
season only, and not once the season is finished (`season.finished`).

---

## 8. Elo: `models/elo.py`

Three ratings, updated once per Grand Prix in calendar order from 1950:

- **Field Elo** on the finishing order: driver plus car.
- **Teammate Elo** on head-to-heads with team-mates only: the cleaner driver
  signal and the basis of the all-time table.
- **Qualifying Elo** on qualifying positions (the grid before qualifying
  classifications exist, pit-lane starts dropped).

```
E_ij = 1 / (1 + 10^((R_j − R_i)/400))
dR_i = K/(n − 1) · sum_{j≠i} w_ij (S_ij − E_ij),   w_ij = min(w_i, w_j); two non-classified drivers skipped
```

| Constant | Value |
|---|---|
| `K_FIELD`, `K_TEAMMATE`, `K_QUALI` | 32, 24, 32 |
| `INITIAL` | 1500 (drivers already racing in the first season on disk) |
| `ROOKIE_OFFSET` | a debutant starts at the mean of the rated drivers in that race minus 100 |
| `REGRESS` | 0.15 toward 1500 before each season |
| `PEAK_MIN_RACES` | 20 starts before a peak counts |
| `ALL_TIME_MIN_RACES` | 50 starts for the all-time table |
| `AMBIGUOUS_WEIGHT` | 0.5 |

Retirement classes (`status_class`): finished (numeric `position_text`,
"Finished", "Lapped", "+n Laps") weight 1 at their position; driver-caused
(accident, collision, spun, crash) 1, behind the classified; mechanical (78
keywords in `_MECHANICAL`) 0; ambiguous ("Retired" and anything unrecognised) 0.5, behind the
classified; excluded (did not start/qualify, withdrew, disqualified, injury...) not
rated. Teammate pairs count when both are classified, or one is classified and
the other retired for a driver-caused reason. Sprints are not rated; the
Indianapolis 500 is skipped; a driver with two cars in one race is rated on the
better entry. Cached in `data/f1/cache/elo.json` keyed on every store's mtime and
size. `ratings_before(history, year, round)` gives the walk-forward ratings.

Because Jolpica's statuses from 2023 are a bare "Retired", every modern retirement
is ambiguous and costs half a crash.

---

## 9. Plackett-Luce: `oddsmarkets/common/ranking.py`

A finishing order as successive draws without replacement, winner ∝ `exp(theta)`.
`fit_strengths(orderings, fields, weights, ridge=0.1)` maximises the weighted
log-likelihood minus `(ridge/2) sum theta²` by L-BFGS-B on the analytic gradient
(at most 500 iterations), centred to mean 0; drivers in the field but not the
order stay in every denominator. `pl_probabilities` gives exact `p_win`
(softmax) and Gumbel-sampled top-k and expected position. Same likelihood as
`scripts/fit_ballon_dor.py`, which does not import it. In F1 it is a backtest
baseline only.

---

## 10. Car/driver split of points

Two implementations exist; the site shows the second.

- **`decomposition.car_driver_split(year, n_sims=4000, seed=7)`**: per team, four
  worlds with common random numbers ((car, drivers) each on or set to the average,
  every other team unchanged); car contribution = mean of the two marginal gains of
  switching the car on, drivers likewise; `car_share = |car| / (|car| + |drivers|)`.
  The build does not call it.
- **`analytics/teams.car_driver_split(year, effects, n_sims, seed=7)`**, used by
  `build_season` with `n_sims` 2,000 for the full season and 500 for light seasons
  (`cfg["split_sims"]`, `cfg["split_sims_light"]`): at every finished round each
  car's score is `car_{t,r} + drv_i + N(0, tau²)` (race effects, qualifying effects
  if there is no race pace), finishing orders are simulated and scored with the
  season's points table (`decomposition._points_table`: the most common points at
  each position in the season's results). The players of a team are its car and
  each of its drivers that round; `v(S)` is the team's expected points with the
  effects in S switched on; each player's Shapley value is
  `phi_j = sum over S not containing j of |S|! (k − |S| − 1)! / k! (v(S + j) − v(S))`.
  A team with more than five drivers in one round is skipped for that round.
  Values are summed over rounds; `car_share = |car| / (|car| + sum |drivers|)`.
  `points` is the team's actual race plus sprint points.

---

## 10a. Driver value, the driver-swap simulator and team needs: `analytics/value.py` (added 15 October 2026)

**Driver value** (no positions in F1), from the season's decomposition (section 3), percent of a lap with the sign
turned so that positive is faster: *pace above team-mate* = −drv (race; qualifying from the qualifying fit), with its
standard error (about 0.15% after a full season, as large as most effects); *pace above the field* = −(car's latest
race-pace state + drv); *trend* = pace above team-mate against last season's (both seasons with five or more races);
percentiles of pace above team-mate among drivers with five or more races (`MIN_RACES`). **Constructors** by −(the car's
latest race-pace state), with the mean of the observed rounds, the latest qualifying state and the change over the
last five rounds. Because drv is identified only within a team and shrunk toward 0, a driver beside a weak team-mate
looks better than he is; the page says so.

**Driver swaps** (`swap_table`, `swap_events`): "X into Y's car" swaps X with W, one of Y's drivers, in every remaining
event's race inputs (the championship's `_events`): X gets the seat's pace plus the driver difference,

```
mu_X' = mu_W + (drv_X − drv_W) · ref_lap / 100        mu_W' = mu_X + (drv_W − drv_X) · ref_lap / 100
```

the seat's grid (or pre-qualifying grid distribution and results-only qualifying strength), the car's mechanical
retirement probability with X's own incident probability (`meta["dnf_split"]`; hazard −ln(1 − min(0.6, p_mech + p_inc)) /
laps, the sprint distance for a sprint), the seat's stop plan and degradation where set, and the team label, so the
team's form walk F and the constructors' points follow the car. Points already scored stay where they were scored. The
seat carries the pace (the race inputs' blend is mostly the results-based estimate of that seat), so a swap moves the
drivers' points far more than the teams' (in the synthetic test season the fastest driver into the slowest car: about
±37 points for the drivers, under 1 for the teams). Every pair of current drivers on different teams (220 in 2026) is
simulated with `--swap-sims` runs (1,000) and the season's seed, the same seed as a baseline run of the unchanged
inputs (common random numbers), and the change is stored; the page adds it to the published 20,000-run championship.
220 pairs take about 3.3 minutes (each championship run costs about 0.9 s whatever n, the race simulator's lap loop
dominating); the table is cached under `<cache>/swaps/` on the race inputs' numbers, the points so far, the driver
effects, n and the seed, and recomputed only when one changes. 2026 check (published championship through round 17):
Verstappen into Russell's Mercedes seat: Verstappen +25.2 expected points, Russell −22.2, Mercedes +29.2, Red Bull −29.2.

**Strengths and needs** (`needs_payload`): the team catalogue's percentiles on car race and qualifying pace,
development through the season, mechanical reliability, tyre management, pit stops, strategy, straight-line speed and
cornering, plus the drivers by the mean team-mate Elo of the team's drivers (section 8: chained across career
team-mates, the one driver measure here comparable across cars), graded A from the 80th percentile, B 60th, C 40th,
D 20th, F below; the top three (60+) and bottom three (40 or less); "balance" when qualifying and race percentiles
differ by 25 or more. A driver weakness gets the five swaps with the most expected constructors' points from the swap
table; a car or operations weakness gets a note (no market for car performance; no price for an upgrade).

## 10b. Fantasy: our points table, projections, value and the backtest: `analytics/fantasy.py` (added 16 October 2026)

docs/VALUE_SECTIONS.md section 5. **Our own table**, in the usual shape of F1 fantasy games, computed from Jolpica results
and OpenF1 records. **Nothing from the official F1 Fantasy game is used** (prices, ownership, picks, scores):
formula1.com's legal notices (https://www.formula1.com/en/information/legal-notices.7egvZU48hzrypubGBNcQKt) say "The
material and content provided on the Site is for your personal, non-commercial use only" and ask users not to
"distribute copy extract or commercially exploit such material or content"; fantasy.formula1.com (including
`/en/terms` and `/en/game-rules`) is a JavaScript app whose text could not be read without running it, so its own
terms could not be checked and nothing is fetched from it. Value is therefore measured against our own form line.

| Part | Item | Points |
|---|---|---|
| Qualifying | P1 ... P10 | 10, 9 ... 1 (P11 or lower 0); no time set −5 |
| Grand Prix | P1 ... P10 | 25, 18, 15, 12, 10, 8, 6, 4, 2, 1 |
| Grand Prix | places gained / lost v the grid slot | +1 / −1 each (classified finishers; pit-lane start = last slot) |
| Grand Prix | fastest lap | +10 |
| Grand Prix | overtakes | +1 each: OpenF1 passes, pit-stop / safety-car / about-to-retire changes removed (`context.overtakes`), capped at 20 a race (2023 on) |
| Grand Prix | not classified / disqualified | −20 (no other race points) |
| Sprint | P1 ... P8; places; fastest lap; retirement | 8 ... 1; ±1 each; +5; −10 |
| Constructor | both drivers | every driver item |
| Constructor | qualifying progression (best tier) | both Q3 +10, one Q3 +5, both Q2 +3, one Q2 +1, neither −1 (Q2 = top 10 + (n − 9) // 2 of n, or a Q2 time) |
| Constructor | team's fastest stationary stop (GP) | < 2.0 s +20, < 2.2 s +10, < 2.5 s +5, < 3.0 s +2; the race's fastest +5 |

Left out: driver of the day (a fan vote), sprint overtakes (not filtered), sprint qualifying, overtakes before 2023
(OpenF1 starts then: those seasons are scored "core" = everything but overtakes), pit bands where OpenF1 has no
stationary times (late 2024, all of 2025 and 2026 rounds 1-4, 7 and 10 have them), and game mechanics (streaks,
team-mate bonuses, chips, transfers, budgets). The overtakes cap: the feed logged 87 passes for Russell at Bahrain
2025 (18 per driver that race).

**Projections.** The race simulation (section 6) per simulated weekend, from the same inputs as the forecasts, with two
additions to `simulate_race`'s samples (the grid slots and the fastest-lap car, drawn after everything else when the
season has no fastest-lap point, so published numbers are unchanged). Before qualifying the slot is drawn from the
qualifying model and doubles as the qualifying position (no grid penalties); once qualifying or the sprint has run
their actual points replace the simulated ones. The sprint uses the race's inputs at the sprint distance with the same
seed as its Grand Prix (common random numbers: same pace draws, same drawn grid). Overtakes, per simulated race:

```
lambda = max(0.2, b0 + b1·gained + b2·lost + b3·finished) · f_circuit · f_driver
f_circuit = (sum of the circuit's per-race means + 1.5 m) / ((races there + 1.5) m)      f_driver = (overtakes + 15 m) / (expected + 15 m)
```

b by least squares on every earlier OpenF1 driver-race (counts capped at 20; m = mean per driver-race; at least three
races); for round 18 of 2026: b = (2.63, 0.385, 0.112, 1.24), m = 4.46 over 86 races. Season-to-season correlation of
a driver's overtakes per race is 0.05-0.36 (2023-2026), hence the heavy driver shrinkage. Pit points: the team's mean
band points and share of the race's fastest stop over earlier races with stationary times (this season weight 1,
last 0.35), shrunk toward the field with 3 races. **Rest of season**: every remaining round in one run of 4,000 with
the championship's season-level correlation (section 7: z, the team walk F with step 0.06 s/lap and the driver walk G
0.03), so the season total's 10-90% range includes a car's season drifting. Expected points per remaining round per
driver and constructor feed the schedule table.

**Value, tiers and picks.** Form line (our price proxy) = (n × season-to-date points per weekend + 3 × last season's) /
(n + 3). Value = projection − form line (next weekend; per weekend over the rest of the season). Tiers: optimal 1-D
breaks (Fisher-Jenks, least within-tier squared error), five for drivers, four for constructors. Picks: top five and
a boost pick by projection; value, differentials (projection rank at least two above the form-line rank, form rank 7+),
risers (car's race pace up 0.04%+ of a lap over five rounds, underlying pace ranking two or more places above form, or
12+ championship points below the race forecasts' expectation, with positive rest-of-season value) and fades (rest-of-
season value below −1) are taken only from the top 60% of projections, so a backmarker whose form line was dragged
down by retirements (Stroll's −7.3 a weekend in 2026) is not sold as value. Reasons are generated from the numbers
(front-row and Q3 shares, car trend, retirement and fastest-lap shares, value, luck, ceiling).

**Backtest** (`backtest`, `python -m oddsmarkets.f1.analytics.fantasy backtest --from 2012 --to 2026 --sims 2000`; about
2 minutes): every Grand Prix weekend with results, projected before qualifying with data strictly before it (the
walk-forward race components pickled by `scripts/f1_tune.py prep`, built live for rounds it lacks: 2026 rounds 16-17),
2,000 simulations each, scored with the same table. Baselines: season-to-date average, previous weekend, last season's
average (each falling back to the previous season's mean per driver-weekend). Spearman is per weekend, averaged.
Results (16 October 2026; 308 weekends, 2012 to 2026 round 17):

| Group | Our projection | Season-to-date avg | Previous weekend | Last season avg |
|---|---|---|---|---|
| Drivers, core (2012-2026; 6,330 driver-weekends): MAE | **8.96** | 9.67 | 12.28 | 10.04 |
| Spearman | **0.544** | 0.505 | 0.374 | 0.417 |
| Top-5 overlap | **0.706** | 0.680 | 0.615 | 0.618 |
| Points of the top pick | **28.7** | 28.7 | 23.4 | 27.4 |
| Drivers, full (2024-2026, overtakes; 1,299): MAE | **9.27** | 10.08 | 12.85 | 10.77 |
| Spearman | **0.580** | 0.550 | 0.430 | 0.447 |
| Constructors, core (3,190): MAE | **13.73** | 14.49 | 18.69 | 16.08 |
| Spearman | **0.688** | 0.665 | 0.553 | 0.602 |
| Constructors, full (2024-2026; 657): MAE | **14.67** | 15.93 | 20.00 | 19.17 |

The driver MAE beats the season-to-date average in every one of the 15 seasons (e.g. 2024 7.38 v 7.97, 2025 8.56 v
9.74, 2026 9.71 v 10.27); constructors lose narrowly in 2019 (13.19 v 13.08) and 2022 (14.90 v 14.88). Bias is under
0.4 points. Half ours / half season average ("blend") is worse than ours alone (8.96 → 9.15). The 10-90% interval
holds 88% of actual core totals (83% full): weekend scores are discrete (many drivers score exactly 0 or −20) and the
interval is closed, so coverage overshoots 80%. Pit points have no skill: MAE 2.53 against 2.53 for the team's
season-to-date average (346 constructor-races with stationary times).

## 11. Walk-forward forecasts: `analytics/forecasts.py`

`forecast(year, round, kind, n=3000)` for kind `pre` (before qualifying), `post`
(with the actual grid; `None` until qualifying is on disk) or `sprint` (sprint
weekends; the sprint grid once known). Seeds are fixed per round and kind
(`year × 1000 + round × 10 + {pre 1, post 2, sprint 3}`), so a rebuild with the
same data reproduces the same numbers. Cached in
`data/f1/cache/forecasts/<year>_<round>_<kind>.json`, keyed by a SHA-1 of
`VERSION = "fc-1"`, the simulation count, the results/qualifying/sprint rows and
lap-time presence of every earlier round this season and the two before, this
round's entry list (and qualifying for `post`, sprint grid for `sprint`), the
circuit profile as of the race, and the list of session files on disk.

The build (`season_forecasts`) runs all three kinds for every round of the full
season: `--race-sims` (default 3,000) per finished round, `--sims` (default
20,000) for the next round. "Points v expected" and several awards use
`race_forecast_for_points`: post-qualifying when present, else pre.

---

## 12. Backtest: `models/backtest.py`

### 12.1 Method

`backtest(seasons=2014..2026, n_sims=4000, seed=0)` (or `python -m
oddsmarkets.f1.models.backtest --from 2014 --to 2026 --sims 4000`): every Grand Prix
with results is predicted with data strictly before it; a past season with missing
results is skipped and listed; the current season is used to date. Four binary
events per driver: win, podium, points (classified in the top 10), DNF; non-starters
dropped. Each race is seeded `seed + 1000 × year + round`. Races are processed one at
a time (inputs and simulations freed, `gc.collect()` per race), and `memory_mb`
records the process's resident memory: 100 MB at the start, 314 MB peak, flat from
2016 on, over 267 races.

| Model | Timing | Definition |
|---|---|---|
| `model_pre` / `model_post` | before / after qualifying | `simulate_race` with the decomposition blend |
| `model_pre_results_only` | before | `simulate_race` with the results-only estimator |
| `grid_order` | after | `sigmoid(a + b × slot)` per event, fitted on previous seasons (ridge 1e-3), rescaled so the field sums to 1 / 3 / 10 |
| `previous_results` | before | event frequency over the last 5 starts, shrunk to the base rate with 2 pseudo-starts |
| `elo` | before | field Elo as Plackett-Luce strengths `theta = elo × ln 10 / 400` |
| `plackett_luce` | before | `fit_strengths` on the last three seasons' orders (weights 1, 0.35, 0.12) |

Scores: binary log-loss (p clipped to [1e-4, 1 − 1e-4]), Brier, the multiclass
winner log-loss `−mean(ln p_winner)` with win probabilities renormalised,
reliability in 10 equal-width bins, and `win_temperature`: the exponent T minimising
the winner log-loss of p^T renormalised (T > 1: favourites win more often than
forecast). Written to `data/f1/cache/backtest.json`, which the build turns into
`calibration.json` (CI keeps the committed copy). Not run by the build or CI; about
12 minutes locally.

**Tuning** (`scripts/f1_tune.py`): `prep` pickles `race_components` for every race
2012–2026 (`data/f1/cache/tune/`); `grid` simulates each configuration of constants for
every race with common random numbers; `select` picks, for each season Y from 2014, the
configuration best on the seasons before Y. Only the constants without a direct data
check were tuned this way: `PACE_PER_Z_PCT`, `A_BLEND_K`, `PRE_GRID` (the walk-forward
pick after qualifying was `PACE_PER_Z_PCT = 0.9, A_BLEND_K = 40` in every season).

### 12.2 Results (October 2026)

**Run of 21 October 2026** (driver day sd 0.05, lap-1 tail 2%, walk-forward post-qualifying win temperature; 269
races 2014–2026 round 17, 4,000 simulations, 1,131 s, 310 MB peak): `model_post` winner log-loss 1.2153 (2014–2022
1.2831, 2023–2026 1.0725; without the temperature 1.2155), T 1.12, win / podium / points / DNF log-loss 0.0963 /
0.2059 / 0.4669 / 0.4113; `model_pre` 1.4504 (T 1.02); `model_pre_results_only` 1.4839; `grid_order` 1.5041.
Section 6.3 has the paired comparisons on the 2023–2026 test races.

**Run of 2 October 2026** (after the edge research: this round's qualifying pace after qualifying, practice in
the qualifying model, the shortened-race laps fix; 267 races, 4,000 simulations, 1,279 s, 357 MB peak):

| Model | Winner LL 2014–26 | T | Win LL | Podium LL | Points LL | DNF LL |
|---|---|---|---|---|---|---|
| `model_post` | **1.224** | 1.17 | 0.097 | 0.206 | 0.467 | 0.412 |
| `model_pre` | **1.444** | 1.05 | 0.111 | 0.232 | 0.497 | 0.412 |
| `model_pre_results_only` | 1.474 | 0.97 | 0.113 | 0.238 | 0.503 | 0.412 |
| `grid_order` | 1.509 | | 0.114 | 0.240 | 0.508 | 0.413 |

`model_pre` uses practice where the sessions are on disk (2023 on). The run of 1 October below is kept for the
record.

The run of 1 October 2026: 267 races (2014–2025 complete, 2026 through round 15),
4,000 simulations per race, 694 s. Seasons before 2023 use Jolpica laps for the
decomposition; 2023 on also use OpenF1 (stints, intervals, race control).

| Model | Winner LL 2014–26 | 2014–22 | 2023–26 | T | Win LL | Podium LL | Points LL | DNF LL |
|---|---|---|---|---|---|---|---|---|
| `model_post` | **1.332** | 1.394 | 1.197 | 1.09 | 0.104 | 0.212 | 0.471 | 0.412 |
| `grid_order` | 1.509 | 1.538 | 1.449 | 0.93 | 0.114 | 0.240 | 0.508 | 0.413 |
| `model_pre` | **1.465** | 1.467 | 1.460 | 1.04 | 0.113 | 0.235 | 0.500 | 0.412 |
| `model_pre_results_only` | 1.477 | 1.486 | 1.455 | 0.97 | 0.113 | 0.238 | 0.503 | 0.412 |
| `plackett_luce` | 2.028 | | | 1.74 | 0.144 | 0.306 | 0.559 | 0.418 |
| `previous_results` | 1.969 | | | 0.98 | 0.139 | 0.281 | 0.554 | 0.463 |
| `elo` | 2.105 | | | 2.51 | 0.149 | 0.305 | 0.552 | 0.418 |

Before the re-tune, on the same 267 races and data (the code at commit 32cd578):
`model_post` 1.505, `model_pre` 1.611, `model_pre_results_only` 1.639, `grid_order`
1.519. (The earlier published run, 85 races 2023–2026 before the Jolpica backfill:
1.284 / 1.501 / 1.484 / 1.502; on the backfilled data the same code scores 1.397 after
qualifying on those seasons.)

Win reliability after qualifying (mean forecast → observed, n): 0.30–0.40 bin
0.349 → 0.407 (123), 0.40–0.50 0.443 → 0.417 (96), 0.50–0.60 0.544 → 0.627 (75),
0.60–0.70 0.641 → 0.773 (22), 0.70–0.80 0.739 → 0.900 (10). Before the re-tune the
50–60% bin won 84.6% of the time (13 forecasts). Some timidity remains at the top
(T = 1.09 after qualifying); no temperature is applied, since the remaining gap is
within a few forecasts in the upper bins and a temperature would break the
simulator's joint distributions (positions, points, championship).

What it says:

- After qualifying the simulator beats grid order by 0.18 nats on the winner over
  2014–2026 and on every binary event except DNF (equal).
- Before qualifying the decomposition blend now beats its results-only variant over
  2014–2026 (1.465 against 1.477) and over 2014–2022; over 2023–2026 alone the two are
  level (1.460 against 1.455).
- Elo and Plackett-Luce remain far behind.

## 13. Markets: `sources/markets.py`, `oddsmarkets/common/`

- **Price** = midpoint of a live two-sided quote, accepted only when `0 < bid ≤ ask
  < 1` and `ask − bid ≤ 0.12` (football's `_mid`, `MAX_SPREAD`); a last trade is
  never a price.
- **Consensus**: per runner, the mean of the sources' mids, excluding eliminated
  runners; then multiplicative de-vig `p_i = m_i / sum_j m_j` (`devig` on
  `1/m`).
- **Thin-market rule** (`assemble`): published only when at least `max(4, half
  the field)` runners are accounted for and the implied total is within
  `MIN_TOTAL, MAX_TOTAL = 0.8, 1.3`. Accounted for = a two-sided quote, an
  eliminated runner (Kalshi result "no"; a Polymarket runner market closed and
  settled No), or a floor runner (no bid, ask ≤ `FLOOR_ASK = 0.02`), which gets
  probability 0 and is never used as a price. A settled market (a "yes") is not
  published.
- **Race winner**: matched to the round by date within `DATE_WINDOW_DAYS = 3`;
  Polymarket slugs with constructor, sprint, pole or practice excluded.
- **Head-to-heads**: Kalshi pairs de-vigged as `m_a / (m_a + m_b)` (one side
  quoted: its mid or one minus it); Polymarket first-outcome mid; both sources
  averaged. The model's side is `_p_ahead` in `analytics/season.py`: P(a ahead of
  b) from the two position distributions treated as independent, ties split.
- **Names**: driver aliases (`DRIVER_ALIASES`: "Jr." → sainz, "Kimi" →
  antonelli, ...), then the three-letter code, then `best_match` over full names,
  then over unique family names (floor 0.8); constructors through
  `CONSTRUCTOR_ALIASES`, then the id, then `best_match` with "F1 team" words
  stripped. `best_match` floors at 0.72 and refuses a runner-up within 0.02.
  Unmatched labels are reported, never guessed.
- **Edge** = model / market − 1 (relative).

---

## 14. Analytics derived from the models

The catalogues are definitions rather than models; their full formulas are in
the module docstrings, which are the reference.

- **Driver catalogue** (`analytics/drivers.py`, 85 metrics plus `races`, in eight
  groups): Results (17: wins, rates, finishes, laps led, race head-to-head,
  fastest laps, Elo), Qualifying (13: poles, Q3 rate, gaps to pole and team-mate,
  quali pace and driver effect, grid drop), Race pace (13: corrected pace and
  ranks, team-mate delta, driver effect, consistency, traffic cost, wet pace rank,
  sector strength), Racecraft (10: positions gained, lap-1 and late gain,
  overtakes made/suffered, pass difficulty, overtakes per pace, penalties), Tyres
  (8: degradation per compound, tyre management index, stint length v field,
  stops, pit-lane time), Reliability (8), Telemetry style (7: braking-point
  earliness, minimum corner speed delta, full throttle, braking and coasting
  shares, speed trap), Points (10: expected points and points v expected,
  points lost in DNFs, sprint points).
- **Team catalogue** (`analytics/teams.py`, 41 metrics in seven groups): Results,
  Car pace (the decomposition's car effect, rank, trend, latest), Profile (top
  speed, corner speed, straight-line bias), Tyres and pit crew (stationary times
  1.5–30 s kept, pit-lane times 8–60 s), Strategy, Reliability, Drivers (car
  share from section 10).
- **Percentiles** (`analytics/__init__.percentiles`): `100 × (worse + 0.5 ties) /
  (n − 1)`, direction-aware, 50 for a lone entry; field and team-mate.
- **Race context** (`analytics/context.py`): the lap table (OpenF1 lap end times
  from 2023, Jolpica positions before), passes (OpenF1 overtakes with pit-stop
  changes, neutralised laps and cars retiring within two laps removed;
  `derived_passes` from lap positions for any season), corrected lap scatter
  (residuals after the race fit's fuel coefficient and the driver's degradation,
  at least 8 laps), the wet flag.
- **Awards** (`analytics/awards.py`): driver of the day (points minus forecast
  expected points), best drive from the back (gain weighted `0.5 + car_rank /
  n_cars`), best strategy (places gained through stops against the race's norm, at
  most `MAX_STRATEGY_STOPS = 4`), fastest stop, overtake of the race (largest pace
  deficit), unluckiest, smoothest (lowest lap scatter with at least 60% of the
  winner's laps), team of the weekend.
- **Expected v actual** (`analytics/races.py`): `pctile_of_actual = 100 × (P(pos >
  actual) + 0.5 P(pos = actual))` under the forecast.

---

## 15. Telemetry processing: `oddsmarkets/f1/telemetry.py`

For each lap window `[t_start, t_start + lap_ms]` with at least 20 car samples:

- **Distance** integrated from speed, `d += v dt`. The reference lap is the
  session's fastest timed lap with telemetry; its distance is the lap length.
  Other laps are rescaled to it; laps below 0.8 × or above 1.25 × it are skipped.
- **Corners** on the reference lap: speed minima with prominence ≥ 25 km/h
  (`CORNER_PROMINENCE`; rise to the lower of the highest speeds within 600 m on
  each side), at least 150 m apart (`CORNER_GAP_M`; a slower minimum within 150 m
  replaces the previous corner). Each lap's corner minimum is the lowest speed
  within ±80 m of the reference apex (`APEX_WINDOW_M`).
- **Braking point**: the last off-to-on brake transition within 400 m before the
  apex (`BRAKE_LOOKBACK_M`), in metres before it.
- **Per-lap summary**: top and mean speed, full throttle (≥ 98) %, braking (> 0) %,
  coasting (< 2, no brake) %, gear changes, DRS open seconds (codes 10, 12, 14).
- **Trace**: each driver's fastest valid lap resampled every 10 m (`STEP_M`):
  speed, throttle, brake, gear, rpm, DRS, and x/y from the first location sample
  at or after each point's interpolated time.

The telemetry-style metrics compare a driver's median per corner with the field
median in the same session (`analytics/drivers._telemetry_style`).

---

## 16. Known limitations

- **2026 regulation reset.** Earlier form says less; the results-only estimator
  uses the reset season weights (0.08, 0.03) and round 1 of the qualifying model
  adds winter variance. Early-season forecasts are wide.
- **No compounds before 2023**; no pit-stop table before 2011 (stops inferred from
  slow laps); no lap length anywhere (inferred from the race distance).
- **Retirement reasons** are a bare "Retired" from 2023: the mechanical/incident
  split falls back to the global share and Elo treats them at half weight.
- **Reference lap** is the circuit's latest race's median green lap, so a circuit
  whose layout changed since its last race uses the old lap until it is raced.
- **Overtaking** checks only the nearest car ahead, so a much faster car can clear
  two cars in a lap.
- **Favourites timid after qualifying in 2023–2026.** The raw simulator's win temperature there is about 1.6 (1.0 on
  2014–2022): pole-sitters won 61% of 2023–2026 races against 41% forecast. Since 21 October 2026 a walk-forward
  temperature sharpens the published post-qualifying win probabilities (section 6.3); it recovers part of it
  (calibration slope 1.74 → 1.56 on 2023–2026), not all. Earlier note:
  section 12.2).
- **Practice long runs are not used**: without fuel loads they made the winner forecast worse.
- **Pre-1991 points** are simplified to 9-6-4-3-2-1 in the simulator (which only
  ever simulates the current season); standings do apply the historical
  dropped-score rules (`DROP_RULES` in `analytics/season.py`).
- **Telemetry at ~3.7 Hz** limits braking-point precision.
- **Driver value is within-team**: the decomposition identifies a driver only against his team-mate, so values across
  teams rest on the shrinkage prior; the swap simulator adds the driver difference to the seat's pace, it does not
  re-estimate the driver. Contracts and availability are not modelled.

---

## 17. Where the code and other texts disagree

Found while writing this document; the code is taken as correct in every case.

| Topic | The code | The other text |
|---|---|---|
| Car/driver split on the site | `analytics/teams.car_driver_split`: Shapley over the car and each driver, 2,000 simulations (500 for light seasons), car share = abs(car) / (abs(car) + sum of abs(driver)) | Methodology (`docs.js`, "Car versus driver share of points") describes `decomposition.car_driver_split`: four worlds, 4,000 simulations, car against the drivers as one player. The build never calls that function. |
| Dropped scores | `analytics/season.standings` applies `DROP_RULES` up to 1990 | Methodology, Limitations: "dropped-score rules are not modelled". True of the simulator only. |
| Telemetry x/y | first location sample at or after the point's time (`np.searchsorted`) | `telemetry.py` docstring: "nearest sample". Methodology agrees with the code. |
| Decomposition window in the blend | effects through the latest completed round before the race | `race_sim.py` docstring: "through the previous round". Methodology agrees with the code. |
| Magic number's R | one R for every driver (the most anyone can score) | `championship.py` docstring: `R_d` per driver. Methodology agrees with the code. |
| Driver metric count | 85 metrics plus `races` (`drivers.METRICS`) | `PAYLOADS.md`: "~70 metrics". The `drivers.py` docstring says ~85. |
| Raw telemetry storage | local `data/f1/telemetry/` and the Actions cache | `sources/openf1.py` docstring and `.gitignore` comment: "and release archives". No release archive exists. |
| OpenF1 pacing | `Client(interval=0.35)`: up to ~170 calls a minute, kept under the limit by latency and 429 back-off | the workflow comment and the site's methodology describe a 30-a-minute limit. |
