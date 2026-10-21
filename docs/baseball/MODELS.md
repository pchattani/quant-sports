# Models: technical reference (baseball)

Every model behind The Quant Bullpen, read from `oddsmarkets/baseball/models/` and the
committed fits in `oddsmarkets/baseball/models/fitted/`. Data and identity are in
[DATA_PIPELINE.md](DATA_PIPELINE.md); how the results reach the pages is in
[DASHBOARD.md](DASHBOARD.md). Section 22 lists where the code, the site's Methodology
(`docs/bullpen/assets/js/docs.js`) and the contracts disagreed, and how each was resolved on
1 October 2026.

Contents

1. Overview
2. Pitch physics and the prepared pitch table: `physics.py`, `prep.py`
3. Stuff+, Location+ and Pitching+: `stuff.py`, `location.py`, `pitching.py`
4. Tunneling: `tunneling.py`
5. Swing decisions: `swing.py`
6. Bat tracking: `battrack.py`
7. Fatigue and workload: `fatigue.py`
8. xwOBA+: `xwoba.py`
9. Catch probability and fielding runs: `catchprob.py`
10. Called strikes, framing and umpires: `framing.py`, `umpire.py`
11. Run and win expectancy: `re24.py`
12. Park factors: `parks.py`
13. Bullpen WAR: `war.py`
14. History: `history.py`
15. Stabilisation: `stabilise.py`
16. Projections: `projections.py`
17. The game simulation and live WP: `game_inputs.py`, `game_sim.py`, `live.py`
18. Season and postseason simulation: `season_sim.py`
19. Awards and markets: `awards.py`, `sources/markets.py`
20. Backtest and validation: `backtest.py` and the model checks
21. Known limitations
22. Where the code and other texts disagree
23. NPB models: `npb/models.py`, `npb/backtest.py`
24. NPB play-by-play metrics and expected stats: `npb/pbp.py`, `npb/pbpstats.py`, `npb/lab.py`
25. Player value, strengths and needs, and the trade simulator: `analytics/value.py`, `analytics/trade.py`
26. Valuation v2: `analytics/valuation.py`
27. Transactions and trade ratings: `analytics/moves.py`, `analytics/trade_ratings.py`
28. The fantasy layer: `analytics/fantasy.py`, `analytics/fantasy_build.py`

---

## 1. Overview

### 1.1 How the models feed each other

```
 Statcast pitch table (one season at a time)
   │
   ├──► prep.enrich (physics, outcome flags, families, fastball refs, sequence, rv_dn) ──► cached per season
   │       ├──► stuff.py ──► location.py ──► pitching.py (Stuff+, Location+, Pitching+)
   │       ├──► tunneling.py, swing.py (decision value), battrack.py, fatigue.py
   │
   ├──► _c.pa_table / batted balls ──► xwoba.py (xwOBA+, park-neutral xwoba_n) ──► parks.py (contact factors)
   │                                 └► catchprob.py (fielding runs)     framing.py ──► umpire.py
   │                                 re24.py (RE, linear and wOBA weights, count values, WE, WPA, leverage)
   │                                      │
   │                                      └──► war.py (Bullpen WAR) ──► history.py (1908 →, with Retrosheet)
   │
   └──► _dio.plate_appearances ──► projections.py (components, aging, AAA translations)
                                        │
             game_inputs.py (lineups, starters, bullpen, park, umpire, weather) ──► game_sim.py (20,000 games)
                                        │                                   live.py (Markov WP)
                                        ├──► season_sim.py (season, bracket, series)   awards.py
                                        └──► backtest.py (walk-forward, checks) ──► calibration.json
 Retrosheet PA tables ──► re24.retro_season, war.historical_season, history.py
 stabilise.py: k per metric ──► catalogue shrinkage, WAR's batting regression, projections
```

### 1.2 Model inventory

| Model | File (version) | Fitted where | Used for |
|---|---|---|---|
| Physics | `physics.py` (`physics-2`) | – | VAA, HAA, IVB, HB, decision point, spin axis, spin efficiency |
| Stuff+ | `stuff.py` (`stuff-1`) | `fitted/stuff_mlb.json.gz` (2022–2025) | pitch and pitcher quality |
| Location+ | `location.py` (`location-1`) | `fitted/location_mlb.json.gz` | command, heat maps |
| Pitching+ | `pitching.py` (`pitching-2`) | `fitted/pitching_mlb.json.gz` | overall pitch value |
| Tunneling | `tunneling.py` (`tunnel-2`) | – (per season) | tunnel pairs and index |
| Swing decisions | `swing.py` (`swing-1`) | `fitted/swing_mlb.json.gz` | decision value, swing maps |
| Bat tracking | `battrack.py` (`battrack-2`) | – (per season) | adjusted bat speed, squared-up, swing-path fit |
| Fatigue | `fatigue.py` (`fatigue-1`) | – | velocity and spin signals, times through the order |
| xwOBA+ | `xwoba.py` (`xwoba-3`) | `fitted/xwoba_mlb.{txt.gz,json}` (2026) | expected outcomes, WAR's batting value, parks |
| Catch probability | `catchprob.py` (`catch-2`) | `fitted/catchprob_mlb.{txt.gz,json}` | fielding runs |
| Framing / umpires | `framing.py` (`frame-1`), `umpire.py` (`ump-1`) | `fitted/framing_mlb.json` | framing runs, umpire accuracy, scorecards, ABS |
| Run expectancy | `re24.py` (`re24-1`) | `fitted/re24_mlb.json`, `re24_retro.json` | RE24, linear and wOBA weights, count values, WE, WPA |
| Parks | `parks.py` (`parks-3`) | `fitted/parks_mlb.json` (2024–2026) | park factors, the game model's environment |
| WAR | `war.py` (`war-4`) | `fitted/war_constants.json` | Bullpen WAR |
| History | `history.py` (`hist-2`) | – | careers and all-time boards |
| Stabilisation | `stabilise.py` (`stab-3`) | `fitted/stabilise_mlb.json` | shrinkage, the glossary |
| Projections | `projections.py` (version 1) | `fitted/proj_agg_{h,p}_mlb_<S>.parquet` (aggregates) | game inputs, catalogues, prospects |
| Game simulation | `game_sim.py` (version 1) | `fitted/transitions_mlb.json` (2024–2026) | every game price |
| Market layer | `market_layer.py` (version 1) | `fitted/market_layer_mlb.json` (2016–2026) | the published MLB game prices (from 21 Oct 2026) |
| Live WP | `live.py` | – | live cards, game pages |
| Season simulation | `season_sim.py` | – | season.json, the bracket, series odds |
| Awards | `awards.py` | verified winners table | award races |
| Backtest | `backtest.py` | – | `calibration.json` |

Every model exposes a cached `for_season(level, season)`; the build calls it through
`SeasonContext.model`, which isolates failures. Committed fits stand in when the cache is
empty (CI).

---

## 2. Pitch physics and the prepared pitch table: `physics.py`, `prep.py`

Statcast fits each pitch with constant acceleration from y = 50 ft (catcher's view: x
towards first base, y from the point of the plate towards the mound, z up; feet and
seconds). The CSV has vx0, vy0, vz0, ax, ay, az but not x0, z0, so those are backed out
from the plate location (y = 17/12 ft) or the release point. Times solve the y quadratic,
t(y) = (−vy0 − √(vy0² − 2ay(50 − y)))/ay; gravity 32.174 ft/s².

- **Approach angles** at the front of the plate: VAA = atan(vz/−vy) (negative =
  descending), HAA = atan(vx/−vy).
- **Movement against the release tangent line** (the definition that reproduces Savant's
  columns to about 0.13 in on 2026 pitches; the PITCHf/x 40-ft convention misses Hawk-Eye-era
  values by about 4 in): HB = plate_x − x_line, IVB = ½gT² − (z_line − plate_z). Savant's
  pfx is used when present. `hb_arm` is positive towards the pitcher's arm side.
- **Decision point**: the ball's position 0.167 s before the plate.
- **Spin axis from movement** (Savant's convention); a gap of 20° or more from the measured
  axis flags seam-shifted wake.
- **Spin efficiency**: the Magnus acceleration (non-gravity acceleration less its drag
  component) gives a lift coefficient C_L = |a_M|/(K v²) with K = ρπr²/(2m) (air 0.0745
  lb/ft³, a 9.125-in ball of 5.125 oz); inverting the Sawicki–Hubbard–Stronge lift curve
  gives the transverse spin share. Air is sea-level standard, so thin-air parks read low.
- **Release consistency**: the spread of release side, height, extension and arm angle, and
  the largest gap between two pitch types' mean release points (a tipping indicator).

`prep.enrich` adds, per season (cached as Parquet under `cache/prep/`, `prep-3`): outcome
flags, families (fastballs FF FA SI FT FC; breaking SL ST CU KC SV CS; offspeed CH FS FO SC
KN), the count, platoon, location relative to the batter (`x_away`) and to his zone
(`z_rel`, 0 bottom, 1 top), the pitcher's primary fastball (his most-thrown four-seamer or
sinker, else cutter, else hardest pitch) and each pitch's velocity, IVB and HB differences
from it, sequence features from the previous pitch of the plate appearance (same type,
differences, distances apart at the decision point and at the plate), the pitcher's game
pitch count, and the targets: `rv` = `delta_run_exp` (batting side) and the **denoised**
`rv_dn` = rv + b·(xwOBA − wOBA) on balls in play, b the season's slope of run value on wOBA
value, which removes where a ball in play happened to land.

---

## 3. Stuff+, Location+ and Pitching+: `stuff.py`, `location.py`, `pitching.py`

### 3.1 Stuff+

The expected run value of a pitch from its physics alone (no location, count or batter),
per family. Five LightGBM components per family on competitive, non-bunt pitches:
P(swing), P(whiff | swing), P(foul | contact), P(called strike | take) and E[xwOBA | in play]
(Savant's estimated wOBA), combined as

```
xRV = p_sw [p_wh rv_wh + (1 − p_wh)(p_fo rv_fo + (1 − p_fo)(a + b·xwc))] + (1 − p_sw)[p_cs rv_cs + (1 − p_cs) rv_b]
Stuff+ = 100 + 10 (μ − xRV)/sd_pt
```

rv_wh, rv_fo, rv_cs, rv_b are the training seasons' mean run values of whiffs, fouls,
called strikes and balls; a + b·xwc the least-squares line of in-play run value on xwOBA;
μ the pitch-weighted league mean xRV of the last training season and sd_pt the SD of
pitcher × pitch-type mean xRV (groups of 100+ pitches; 1,956 groups in the committed fit).
**16 features**: velocity, IVB, arm-side HB, spin rate, arm-side spin axis, extension,
release height and side, arm angle, location-adjusted VAA (vaa − slope_family·(plate_z −
z_ref)), the differences from the primary fastball (velocity, IVB, HB), the axis deviation,
platoon and the pitcher's hand. Training: the four seasons before the target season,
350,000 sampled pitches each, one season in memory at a time (31 leaves, learning rate
0.08, 300 a leaf, L2 10, 300 rounds). The committed fit is trained on 2022–2025.

Component validation (builder B's run trained on 2025 and scored on 2026, cached in
`data/baseball/cache/report_b/report_2026.json`): every component beats a velocity-only
model, most for fastball whiffs (log-loss 0.478 against 0.494) and called strikes (0.624
against 0.650).

### 3.2 Location+

A LightGBM regression (31 leaves, learning rate 0.06, 1,000 a leaf, L2 20, 500 rounds; four
seasons × 400,000 pitches) of rv_dn on x_away, z_rel, plate_z, balls, strikes, family,
platoon and hands. The score is count-neutral, loc_rel = loc_xRV − base[count], so a 3-0
pitch is not punished for its count, and scaled as Stuff+. `grid` evaluates the surface on a
13 × 13 batter-relative grid (x_away −1.5 to 1.5 ft, z_rel −0.5 to 1.5) for the heat maps.

### 3.3 Pitching+

One more LightGBM regression of rv_dn on the Stuff+ xRV, loc_rel, the 16 physical features,
the location features and the sequence features (same settings as Location+), count-neutral
and scaled the same way; rolling series use 500-pitch windows. The physical features enter
directly so the model can learn stuff × location interactions (a riding fastball up). The
`pitching.py` docstring records that on 2026, with models fitted on 2025, this lifted the
pitcher-level correlation with run value per pitch from 0.29 (stacking stuff and location
only) to 0.39, against 0.35 for stuff alone; the cached builder-B report holds the "before"
figures (stuff 0.348, location 0.041, stacked 0.287), and the 0.39 is not recorded in a file.

### 3.4 Does Stuff+ predict?

`stuff.pitcher_validity` correlates a pitcher's Stuff+ in one season with his run value per
pitch (pitcher's side) in the next, against his own run value per pitch as the predictor.
In builder B's validation run with the models trained on 2021–2024 (`report_2025.json`):

| Pitchers with … pitches in both seasons | n | Stuff+ → next run value | past run value → next run value | Stuff+ → next denoised RV | past denoised RV → next |
|---|---|---|---|---|---|
| 300+ | 377 | 0.308 | 0.221 | 0.351 | 0.383 |
| 500+ | 314 | 0.353 | 0.230 | 0.422 | 0.421 |
| 1,000+ | 163 | **0.462** | **0.339** | 0.533 | 0.497 |

So Stuff+ predicts next season's run value better than past run value does (0.46 against
0.34 for pitchers with 1,000+ pitches), and about as well as past denoised run value. The run
trained on 2025 alone (`report_2026.json`) gives 0.475 against 0.444 at 1,000+ (n 170).
These reports are in the git-ignored cache; no script in the repository writes them. The
Calibration page's own Stuff+ check measures something else (section 20.3).

---

## 4. Tunneling: `tunneling.py`

For consecutive pitches of a plate appearance: dp = their distance apart at the decision
point, plate = their distance apart at the front of the plate (inches). Pairs that finish
far apart naturally started further apart, so the league curve E[dp | plate] is estimated
from bin means (edges 0, 3, 6, 9, 12, 15, 18, 21, 24, 28, 32, 38, 46, 60, 200 in) and
interpolated:

```
tunnel = E[dp | plate] − dp     (positive: the pair stayed together longer than pairs that split as much usually do)
ratio  = plate / max(dp, 0.5)
Tunnel index = 100 + 10 z over pitcher-pairs with 30+ pairs; a pitcher's index is the pair-weighted mean
```

The whiff effect: whiff rate by tunnel decile and a logistic regression of whiff | swing on
the standardised tunnel, controlling for the second pitch's Stuff+ whiff probability, zone
and family.

---

## 5. Swing decisions: `swing.py`

League LightGBM models on location, count, family, velocity, IVB, arm-side HB, platoon and
hands: p_sw = P(swing) (63 leaves, learning rate 0.08, 300 a leaf, L2 5), rv_sw =
E[rv_dn | swing] and rv_tk = E[rv | take] (31 leaves, 0.06, 1,000, L2 20); four seasons ×
400,000 pitches. A batter's aggression is a ridge-shrunk logit offset (prior sd 0.5). For
each pitch, from the hitter's side:

```
dv = rv_chosen − [p_sw rv_sw + (1 − p_sw) rv_tk]
```

the runs the choice gained over the league-average decision, valued at league-average
outcomes for each choice, so it isolates the decision from the contact that follows. A
hitter's decision value sums dv (and per 100 pitches), split into zone and chase parts that
add to the total; `dv_c` centres it on the season's league so the league sums to zero.
"Should have swung" is the share of takes where rv_sw > rv_tk; "should have taken" the
mirror.

---

## 6. Bat tracking: `battrack.py`

Competitive swings: non-bunt swings at 50+ mph (bat tracking exists from 2023–24; absent
seasons return `{"ok": false}`).

- **Adjusted bat speed and swing length**: a league LightGBM regression on what the pitch
  and count demand (plate speed, location, count, family, platoon); a hitter's adjusted value
  is the league mean plus his summed residuals over (n + 50).
- **Squared up**: exit velocity ≥ 80% of the maximum the collision allowed, max = 1.23·bat
  speed + 0.23·plate speed (Savant's definition); rates per contact and per swing, against a
  league model of P(squared up | pitch and swing).
- **Swing-path fit**: mismatch = attack angle + VAA; mean |mismatch| and the share within 5°.
- **Intercept point**: how far in front of the body contact is made, by family and pitch
  type, against the league.

---

## 7. Fatigue and workload: `fatigue.py`

Descriptive, not medical, on the primary fastball: within-game slopes of velocity, spin,
release height, release side and extension per 100 pitches (demeaned within games, shrunk to
the league slope by empirical Bayes over pitchers with 150+ fastballs); per-game means
against the season baseline, the last three games against it and the trend per 30 days;
times through the order (xwOBA per PA first, second and third-plus time, each shrunk with
100 PA; penalty = third − first); a workload flag when the last three games' fastball is
down 1.0 mph or more or 75 rpm or more, with 5+ games on file.

---

## 8. xwOBA+: `xwoba.py`

Expected wOBA per batted ball, on the wOBA scale (about .320 average; not an index). A
LightGBM multiclass over {out, 1B, 2B, 3B, HR} (classes follow Savant's `woba_value`, so an
error or fielder's choice counts as a single) on:

- exit velocity, launch angle and **hang time** from launch physics (`_c.flight`: drag
  C_D 0.33 and backspin lift up to C_L 0.20, sea-level air);
- the **park**: its five fence distances, mean wall height, elevation and roof from the
  store (the park as a category when the store has no dimensions);
- the batter's **sprint speed** from Savant's leaderboard, on every ball.

**Direction is not used** (`SPRAY_MODE = "park_dims"`): every way of using a ball's own
direction (exact angle, 15° bands, air balls only, the batter's cross-fitted tendency, the
fence distance at the angle) predicted next-period wOBA worse or no better; a ball's landing
angle mostly records placement luck. An outcome-based speed proxy also hurt
(`USE_SPEED_PROXY = False`). Strong regularisation helped: 7 leaves, at least 1,500 balls a
leaf, learning rate 0.06, 250 rounds; three-fold cross-fitting by game.

**Calibration**: the class probabilities are raked (iterative proportional scaling) so each
class's mean probability equals its observed share, which makes league xwOBA on contact equal
league wOBA on contact. Class weights are the season's own means of Savant's `woba_value`
(2026: 0, 0.90, 1.25, 1.60, 2.00); walks and hit-by-pitches enter at their `woba_value` and
strikeouts at 0:

```
xwOBA+ = (Σ_BIP Σ_c p_c w_c + Σ_BB,HBP woba_value) / Σ woba_denom
```

The **park-neutral** variant `xwoba_n` re-predicts every ball with standard fences (330,
375, 400, 375, 330 ft), 8-ft walls, the median elevation and an open roof; WAR's batting
value and the park factors use it.

**Validation** (`predictive_test`): split each season at its median date, fit on the first
half only, and correlate first-half wOBA, Savant's xwOBA and xwOBA+ with second-half wOBA
(hitters with 200+ PA in the first half and 100+ in the second); also each second half with
the next season's first half. Committed `calibration.json` (`checks.xwoba`, every Statcast
season 2015–2026 since the post-backfill build of 2 October 2026; the build used to test only
the last three seasons):

| Split | n | wOBA | Savant xwOBA | xwOBA+ |
|---|---|---|---|---|
| within seasons, pooled (Pearson r / RMSE) | 2,197 | 0.325 / 0.0487 | 0.408 / 0.0460 | **0.416** / 0.0445 |
| across seasons, pooled | 1,776 | 0.350 / 0.0504 | 0.396 / 0.0469 | **0.410** / 0.0467 |
| 2015 H1 → H2 | 199 | 0.293 | 0.391 | 0.393 |
| 2016 H1 → H2 | 192 | 0.278 | 0.341 | 0.338 |
| 2017 H1 → H2 | 208 | 0.367 | 0.365 | 0.418 |
| 2018 H1 → H2 | 211 | 0.409 | 0.493 | 0.518 |
| 2019 H1 → H2 | 201 | 0.376 | 0.444 | 0.474 |
| 2020 H1 → H2 | 0 | – | – | – |
| 2021 H1 → H2 | 188 | 0.347 | 0.483 | 0.486 |
| 2022 H1 → H2 | 202 | 0.425 | 0.414 | 0.411 |
| 2023 H1 → H2 | 203 | 0.297 | 0.438 | 0.425 |
| 2024 H1 → H2 | 198 | 0.247 | 0.408 | 0.402 |
| 2025 H1 → H2 | 199 | 0.382 | 0.471 | 0.476 |
| 2026 H1 → H2 | 196 | 0.139 | 0.237 | 0.225 |
| 2015 H2 → 2016 H1 | 179 | 0.418 | 0.432 | 0.470 |
| 2016 H2 → 2017 H1 | 191 | 0.381 | 0.360 | 0.384 |
| 2017 H2 → 2018 H1 | 194 | 0.379 | 0.446 | 0.458 |
| 2018 H2 → 2019 H1 | 181 | 0.406 | 0.393 | 0.404 |
| 2019 H2 → 2020 H1 | 94 | 0.173 | 0.274 | 0.276 |
| 2020 H2 → 2021 H1 | 0 | – | – | – |
| 2021 H2 → 2022 H1 | 185 | 0.323 | 0.389 | 0.394 |
| 2022 H2 → 2023 H1 | 184 | 0.359 | 0.416 | 0.463 |
| 2023 H2 → 2024 H1 | 188 | 0.321 | 0.426 | 0.412 |
| 2024 H2 → 2025 H1 | 182 | 0.369 | 0.433 | 0.443 |
| 2025 H2 → 2026 H1 | 198 | 0.292 | 0.337 | 0.338 |

(The 60-game 2020 season has no hitter with 200 PA in a half, so its splits are empty.) Pooled
over the twelve seasons xwOBA+ is **slightly ahead of Savant's xwOBA** (r .416 against .408
within seasons, .410 against .396 across), and both are well ahead of past wOBA. Season by
season the gap runs from about .05 in xwOBA+'s favour (2017; 2022 H2 → 2023 H1) to about .014
in Savant's (2023, 2026, 2023 H2 → 2024 H1): xwOBA+ trails in 6 of the 21 non-empty splits.
On the 2024–2026 window alone (the previous committed figures) it was a hair behind within
seasons (.368 against .373). It is a different model of the same thing, at least as good on
this test, not decisively better; the page reports the numbers side by side without a verdict.

---

## 9. Catch probability and fielding runs: `catchprob.py`

For every ball in play that stays in the park, P(out) from where and when it lands and where
the fielders started; the fielder responsible is credited with (out − p) outs and (out − p) ×
the play's run value.

- **Geometry**: landing distance = Statcast's hit distance (else 2.495 ft per hit-coordinate
  unit), direction = spray angle; hang time from the flight model; a grounder's time to the
  infielder's depth at 0.75 × exit velocity. **Start positions** are inferred: the CSV has
  the alignment (infield Standard / Strategic / shift; outfield Standard / Strategic / fourth
  outfielder) but no coordinates, so each position starts at a typical angle and depth for
  the alignment, shaded to the batter's pull side (outfielders at ±28° and 295 ft and 320 ft
  in centre, shaded 3°, 7°, 9° or 12°).
- **Model**: LightGBM binary (250 rounds, three folds by game) on hang time, landing
  distance (air balls), required distance and speed from the **outcome-independent** nearest
  fielder, the radial and lateral components, the wall gap, exit velocity and launch angle,
  gaps to the infielders, depth, the throw to first, batter sprint speed, outs and force;
  calibrated to the season's out rate for air balls and grounders. Fielder identity is never
  a feature.
- **Credit** (Savant's OAA scope: infielders on grounders, outfielders on air balls in the
  outfield): an out goes to the fielder who made it as 1 − p; a ball not turned into an out
  is charged −p × share to every fielder in scope (the share a multinomial model of who
  should have had it), so per-play credits sum to out − p.
- **Runs**: rv_play = the mean linear weight of non-outs in the same (air/ground, 40-ft
  landing band, spray band) cell, shrunk with 20 pseudo-observations, minus lw_out (defaults
  1B 0.47, 2B 0.77, 3B 1.04, HR 1.40, out −0.27).

Validation against Savant's published OAA (fielders with 50+ chances, `checks.oaa`): r =
**0.617** (2016, 237), 0.546 (2017), 0.567 (2018), 0.593 (2019), 0.558 (2020, 223), 0.519
(2021), 0.558 (2022), 0.496 (2023), 0.564 (2024), 0.613 (2025, 256), 0.413 (2026, 272, a
partial season). 2015 has no check: no Savant OAA leaderboard is cached for it. The docstring's 2025 split: outfield 0.65–0.81, 1B/2B/3B
0.65–0.68, SS 0.44: positioning varies most at shortstop and the start positions are
inferred.

---

## 10. Called strikes, framing and umpires: `framing.py`, `umpire.py`

### 10.1 The called-strike model

On one season of called pitches (called strikes, balls, blocked balls; automatic calls,
pitchouts and HBP excluded), a penalised logistic regression by Newton/IRLS on a sparse
design:

```
logit P(strike) = f_side(x, z̃) + count[b-s] + family + hands + c_catcher + u_umpire + p_pitcher + b_batter
z̃ = (plate_z − sz_bot)/(sz_top − sz_bot)        (defaults 1.55 and 3.40 ft when missing)
```

f is a tensor-product hat surface per batter side (knots every 0.15 ft on x ∈ [−1.8, 1.8] and
every 0.1 zone heights on z̃ ∈ [−0.6, 1.6]) with a second-difference penalty 1.0; count,
family (FB, BR, OS, OT) and hands carry ridge 1.0; the random effects have fixed prior sds on
the logit scale (catcher 0.20, umpire 0.15, pitcher 0.12, batter 0.12; ridge 1/sd²), which is
the mixed-model posterior mode given those variance components.

### 10.2 Framing

Strikes added = P(with the catcher) − P(with c = 0) on every called pitch he received;
framing runs = strikes added × the count's strike value (`re24.count_values`); also per 7,000
called pitches. Validation against Savant's framing runs (catchers with 1,000+ called pitches,
`checks.framing`): r = 0.987 (2018), 0.988, 0.971 (2020), 0.977, **0.990** (2022), 0.983,
0.982, **0.988** (2025), 0.931 (2026, a partial season); per-pitch rates 0.82–0.94 over
2015–2026. Savant's leaderboard carries no framing run values before 2018 (all zeros), so
2015–2017 are checked on the per-pitch rate only (0.920, 0.895, 0.944).

### 10.3 Umpires

Per home-plate umpire: **accuracy** against the rulebook zone (|plate_x| ≤ 0.83 ft, sz_bot −
0.12 ≤ plate_z ≤ sz_top + 0.12); **expected accuracy** from the model without his effect (so
hard pitches do not count against him); **consistency** with his own zone (P > 0.5); **zone
size** (strikes above expected per 100 called pitches, and his random effect). Leaderboards
need 500+ called pitches. **Scorecards**: every missed call valued at RV(after a ball) −
RV(after a strike) (count values; for terminal counts the base-out state: ball four forces
runners, strike three adds an out); favour = runs gained by home batters minus away batters.
**ABS challenges (2026)**: parsed from Savant's play descriptions ("… challenged (…), call on
the field was overturned/confirmed") on the PA's last pitch, else the store's per-game
counts; per team, challenger and umpire, with each overturn's run value.

---

## 11. Run and win expectancy: `re24.py`

- **RE(outs, bases)** = the mean runs to the end of the half-inning over PAs in complete
  half-innings (bottom halves of the 9th or later and the last half of a shortened game
  excluded; the Tango convention). Run distributions P(R = k | state) to 14, split by top
  and bottom halves and shrunk to the pooled distribution with 50 pseudo-PAs. Statcast
  seasons use the pitch table; earlier seasons use Retrosheet PAs, from 1908 (no event files are read before 1908).
- **RE24** of a PA = RE(end) − RE(start) + runs scored.
- **Linear weights**: lw_c = mean RE24 of PAs ending in class c (BB, IBB, HBP, 1B, 2B, 3B, HR,
  ROE, K, OUT); **wOBA weights** = (lw_c − lw_out)·s with s chosen so league wOBA = league OBP;
  the wOBA denominator is PA − IBB − SH; runs per win = 9·(runs per inning)·1.5 + 3.
- **Count values**: RV(b-s) = the mean final RE24 of PAs that passed through the count; the
  strike value at a count = RV(after a strike) − RV(after a ball).
- **Win expectancy**: an exact backward recursion over half-innings on the home lead
  (clipped ±30), with the walk-off rule and the 2020-on automatic runner (regular season);
  the tied extra inning's value solves X = Σ_k P_top(k)[S_bot(>k) + P_bot(k) X] in closed form.
- **Leverage**: the expected |ΔWE| over one-PA transitions, divided by its season mean; WPA
  = WE after − WE before for the batting team.

2026 (committed `re24_mlb.json`): RE with nobody out 0.500 (empty) to 2.499 (loaded); wOBA
weights BB .725, HBP .748, 1B .879, 2B 1.228, 3B 1.602, HR 1.972, scale 1.187, league wOBA
.318; runs per win 9.80; the WE model's calibration on 184,288 PAs: log-loss 0.4715, Brier
0.159.

---

## 12. Park factors: `parks.py`

Our own, pooled over three seasons (2024–2026 in the committed fit) and regressed.
**Contact factors** by batter hand and outcome compare what happened with the park-neutral
xwOBA+ expectation of the same batted balls, so they separate the park from the hitters:

```
F_c(park, hand) = (observed_c + K_c) / (expected_c + K_c),   K = 1,000 singles, 300 doubles, 60 triples, 250 home runs
F_wOBA on contact = (Σ wOBA + K) / (Σ xwoba_n + K),           K = 1,500 × mean xwoba_n
F_runs = home/road runs per game, regressed with 160 games;  K and BB factors with 6,000 PA
```

Factors are ratios (1.00 neutral) with an index form ×100. The contact factors are not centred
across parks (2015–2025: geometric means 0.96–0.98 on singles, 1.02–1.16 on triples), so the game model
divides each outcome's factor by its geometric mean over the 30 parks (`game_inputs.park_factors_c`, from 2
October 2026). **Dimensions**: across parks, the
factors regressed on mean fence distance, wall height and elevation. **Weather**: on air balls
(launch angle 15–45°, 90+ mph; domes and closed roofs excluded) the carry residual and the
home-run residual regressed on temperature and the outward wind component ("Out To CF" 1,
"Out To LF/RF" 0.7, in negative, cross 0), park means removed.

---

## 13. Bullpen WAR: `war.py`

**Position players** (Statcast era): RAR = batting + baserunning + fielding (+ framing for
catchers) + positional + league adjustment + replacement; WAR = RAR / RPW.

- **Batting runs are talent**: the park-neutral xwOBA+ regressed with k pseudo-PAs of league
  average (k = xwOBA+'s stabilisation constant, 136 PA in the committed fit; 220 without one),
  (x_reg − lg)/wOBA scale × PA. A results-based version (wOBA, park-adjusted by half the run
  factor) is kept beside it (`war_results`), so the best hitters sit below their results-based
  WAR.
- **Baserunning**: wSB = SB·0.2 + CS·(−(2·runs per out + 0.075)) − lgwSB·opportunities
  (FanGraphs' constants; Statcast steals estimated from runner movement between pitches), plus
  extra bases taken on singles and doubles valued by the RE matrix against the league.
- **Fielding**: catch-probability fielding runs; framing runs for catchers.
- **Positional** per 162 games: C +12.5, 1B −12.5, 2B +2.5, 3B +2.5, SS +7.5, LF −7.5, CF +2.5,
  RF −7.5, DH −17.5, prorated by the share of the team's defensive PAs at each position.
- **League adjustment** per PA so the components sum to zero; **replacement**: 1,000 WAR per
  2,430-game season, 57% to position players and 43% to pitchers, scaled by games.

**Pitchers**, two figures: RA9-based (runs while on the mound, inherited runners not
reassigned, park-adjusted by half the run factor) and expected (xwOBA+ against, regressed);
relievers (starts under half their games) × (1 + gmLI)/2; each version's replacement RA9
solved so pitcher WAR sums to 43%.

**Historical WAR** (Retrosheet): batting from that season's Retrosheet wOBA weights,
baserunning from Retrosheet steals and extra bases, fielding a **proxy** (Lahman range factor
against the position's league rate at 0.75 runs a play, errors likewise, regressed to 25%;
`fielding_source: "proxy"`), positional adjustments from Lahman games, RA9-based pitching.

---

## 14. History: `history.py`

Player seasons from Retrosheet's PA tables (1908–2025) and, after the last Retrosheet year,
the Statcast PA table: counting stats, wOBA with the season's own weights, batting runs,
wRC+ = 100·(wRAA/PA + lgR/PA)/(lgR/PA) and RA9− = 100·RA9/lgRA9 (league = that season; not
park-adjusted), and Bullpen WAR. Careers recompute rates from summed components. Rate boards
need 3,000 PA or 4,500 outs. Ids are MLBAM pids when the crosswalk knows the Retrosheet id,
else `r:<retroid>`. `lahman_check` reports the share of player-seasons whose hits and home runs
equal Lahman's. The committed `mlb/history.json` covers 1908–2026: 17,654 batters and 10,590
pitchers.

---

## 15. Stabilisation: `stabilise.py`

For each metric and each n on a grid from 10 to 2,000 events, players with 2n+ events have
their first 2n split into odd and even halves and correlated (25+ players); r(n) = n/(n + k)
fitted by player-weighted least squares, seasons combined by a player-weighted geometric mean;
n₀.₇ = 7k/3. Committed fit (`stabilise_mlb.json`, refitted after the backfill: the twelve seasons
2015–2026; six for xwOBA+, four for bat speed):

| Metric (unit) | k | n₀.₇ |
|---|---|---|
| Strikeout rate, hitters (PA) | 37.2 | 87 |
| Walk rate, hitters (PA) | 98.6 | 230 |
| xwOBA+ / Savant xwOBA / wOBA (PA) | 135.8 / 120.9 / 369.0 | 317 / 282 / 861 |
| Exit velocity (balls in play) | 34.6 | 81 |
| Chase rate (pitches outside the zone) | 53.5 | 125 |
| Whiff rate (swings) | 38.3 | 90 |
| Bat speed (swings) | 8.0 | 19 |
| Strikeout / walk rate, pitchers (batters faced) | 60.8 / 219.9 | 142 / 513 |

Metrics without a fit take a k from published split-half studies (`DEFAULT_K`: xwOBA 220,
wOBA 330, K 25, BB 50). The same k shrinks every catalogue percentile, WAR's batting value and
the lab.

---

## 16. Projections: `projections.py`

Component projections, each regressed at its own rate, from per-player count aggregates of
the PA table (cached; in CI the exported `proj_agg` files stand in for absent seasons):

```
weighted   X = Σ w_i x_i,  N = Σ w_i n_i         hitters w = 1, .8, .6; pitchers 1, .67, .33 (Marcel 5/4/3, 3/2/1)
talent     r = (X + k m)/(N + k)
next       logit r′ = logit r + aging(age)        (linear components add the delta)
range      sd² = r(1 − r)/(N + k) + r(1 − r)/n_proj;   p10, p90 = r′ ∓ 1.2816 sd
```

k (hitters / pitchers): K 60/70, BB 120/170, HBP 240/640, GB 70/70, xwOBA on contact 50/300,
HR per ball in play 300/1,000 (800 for hitters before 2 October 2026), hits per non-HR ball in play
820/2,000, extra-base hits 600/1,000, triples per XBH 100/300, bat speed 50; the stabilisation fit
overrides K, BB and HBP.

**The league environment** (from 2 October 2026): the projection's own, the same seasons, weights
and level as the players' counts (a rest-of-season projection's target season contributes only its
counts to date); the target m is its league rate (position players'), so a league-average player
projects to exactly its event mix (`attrs["env"]`). Before, m came from "the most recent full
season on disk", which in the walk-forward backtest was the whole target season (a leak of the
league level), and the game model's reference was a different table (section 17.1). The season's
own environment for the game model is separate (`game_env`, section 17.1). **Pitchers batting** (batters
faced at least twice their plate appearances, 50+; two-way players stay hitters) are shrunk to the
pitchers' own batting rates: in 2016 they hit .195 wOBA (Savant scale, league .341) and were
projected at .297, and in National League parks before 2022 they fill the ninth slot.
**Pitchers' targets move by role** (`role_offsets`): share of games started × T(m_starters) +
(1 − share) × T(m_relievers) − T(m_all), T = logit; relievers walk and strike out more and allow
fewer HR per ball in play (2025: BB 9.3% v 7.8%, HR/BIP 4.3% v 4.7%), and they have the smallest
samples, so the all-pitcher target overstated the home runs they allow.

Slow components take a target predicted from fast ones (hitters' HR/BIP from contact quality,
ground balls and bat speed; hits from contact quality, ground balls and sprint speed; pitchers' K
from Stuff+, else fastball velocity; pitchers' HR/BIP from contact quality and ground balls): a
weighted least-squares fit of the **empirical logit** (x + 0.5)/(n + 1) (the logit of a raw rate
sent a player with no home runs to −9.2 and steepened the fit), **centred** so its
sample-weighted mean over every player is the league rate (it was centred in logit space on the
largest samples only). The HR/BIP priors enter at **weight 0.4** (`PRIOR_WEIGHT`): they are fitted
on the same batted balls as the rate they shrink, so at full weight they counted that evidence
twice. The weight that best combines prior and data, estimated each season from the earlier ones
(2017–2026, k = 300), was 0.33–0.49 (0.39 pooled). **Aging**: a quadratic in age − 27 fitted on
consecutive-season changes (100+ events in both, ages 19–41), next-season projections only, and
not for hitters' HR/BIP or pitchers' HR/BIP and walks (`NO_AGING`): those delta-method curves,
fitted on players who survived into the next season, made the projections worse walk-forward
(pitchers' HR/BIP carried a +0.004 bias with the curve, −0.0002 without). **Triple-A translations**: the mean MLB −
AAA difference of players with both in a season (50+ each), defaults hitters K +0.22, BB −0.18,
HR/BIP −0.25 (logit; pitchers the mirror); AAA counts enter at weight 0.6. **Platoon** splits
shrunk to the league ratio with 600 PA per hand. The game model's nine event rates are built
from the components.

Against a Marcel-style baseline (5/4/3 or 3/2/1 weights, 1,200 PA of league average, a simple
age factor; players with 200+ PA or BF; weighted RMSE, `checks.projections`), pooled over
2016–2026 (each season projected from the earlier ones, aging fitted walk-forward; 122–348
hitters and 84–341 pitchers a season), gain = 1 − ours/Marcel:

| | K | BB | HR/BIP | Hits | wOBA |
|---|---|---|---|---|---|
| hitters, pooled | 0.0347 v 0.0357 (+3.0%) | 0.0213 v 0.0213 (−0.1%) | 0.0188 v 0.0191 (**+1.4%**) | 0.0307 v 0.0328 (+6.1%) | 0.0339 v 0.0331 (**−2.4%**) |
| pitchers, pooled | 0.0394 v 0.0411 (+4.3%) | 0.0198 v 0.0198 (+0.3%) | 0.0149 v 0.0155 (+4.1%) | 0.0316 v 0.0323 (+2.2%) | 0.0336 v 0.0356 (+5.8%) |
| hitters, 2026 (333) | +5.4% | +1.5% | +1.5% | +8.5% | −3.4% |
| pitchers, 2026 (323) | +5.9% | +3.5% | +4.1% | +2.1% | +6.4% |

Before the changes of 2 October 2026 (the 05:17 run): hitters' HR/BIP 0.0214 v 0.0191 (−12.5%;
2026 −14.7%), wOBA −6.1%; pitchers' HR/BIP −6.2%, BB −1.3%, wOBA +0.8%.

**Hitters' HR/BIP now beats Marcel** pooled and in 9 of 11 seasons, ties it in 2017 (−0.1%) and
2022 (−0.0%), and leads by up to +5.0% (2024). What fixed it, in the order found (pooled gain
against Marcel, walk-forward): the league environment and pitchers-batting targets (−12.5% →
−8.7%); the prior fitted on the empirical logit and centred in rate space (→ −6% at k = 163–300);
the prior at weight 0.4 with k = 300 and no HR/BIP aging (→ +1.4%). Without the prior at all, at
Marcel's effective k (about 160 BIP a weight-1 season), the projection is Marcel (−0.7% to +0.1%);
a smaller k with the prior at full weight was worse (−13%), because the prior and the rate share
the batted balls. **Triple-A**: re-run without the translated Triple-A counts (same code,
2024–2026), hitters' HR/BIP gains +3.5%, +1.8%, +2.6% against +5.0%, +1.7%, +1.5% with them, so
the Triple-A counts no longer cost home runs on balance (the fitted translation itself is
unchanged). **Hitters' wOBA still trails** Marcel (−2.4% pooled; better in 5 of 11 seasons): it
loses in the seasons when league offence rose (2016 −9.0%, 2017 −13.9%, 2019 −10.8%) and wins
when it fell (2022 +7.8%, 2024 +6.8%), the mark of a projection centred on its three stacked
seasons while Marcel regresses to the latest one; taking the latest season as the next-season
target was tried and left wOBA at −2.7%. Pitchers now beat Marcel on every component but walks
(+0.3%, a tie) and on wOBA in every season.

---

## 17. The game simulation and live WP: `game_inputs.py`, `game_sim.py`, `live.py`

### 17.1 Inputs (`game_inputs.py`)

Every input uses data strictly before the game. **Lineup**: the posted one, else the team's
most recent against a starter of the same hand. **Starter**: the probable, else the most
rested regular (4+ days). **Starter exit inputs**: the mean and sd of his last 10 starts' pitch
counts (default 88 and 12) and his pitches per batter. **Bullpen**: pitchers who appeared in
the last 30 days and started under half their games; unavailable after 30+ pitches yesterday
or pitching on both of the last two days, half-weight after pitching yesterday; the best three
available by projected wOBA allowed are the "hi" tier, the rest "mid"; inside a tier weighted
by availability × recent batters faced (√ of it before 2 October 2026, which gave the rarely used,
weakest arms more of the innings than they get). **Unknown players**: league rates moved to
replacement level (hitter K odds ×1.08, hit odds ×0.94; the mirror for pitchers); a known pitcher
batting without a hitting projection takes the pitchers' batting rates. **League reference** (from
2 October 2026): the season's environment (`projections.game_env`): the previous full season's event
mix with each outcome's rate multiplied by (this season's rate to date / the previous season's rate
over its first equal number of plate appearances)^(n/(n + 5,000)), n the plate appearances to date.
Comparing the same stretch of the calendar cancels the cold April, and the ratio follows a change
in the ball within weeks (2022 from 1 June: home runs .0290 a PA against .0294 for the rest of the
season, where the previous season gave .0327; on a linear-weights proxy over 2016–2026 the error in
each season's rest-of-season run level was a third of that of the previous season plus the season
to date). Every hitter's and pitcher's rates are moved from their projection's own environment into
it by env_game / env (`league_from_projections`; hitters' and pitchers' seasons are weighted
differently), so a league-average hitter against a league-average pitcher returns it. The reference
used to be the season-to-date table (or the previous season before 20,000 PAs) while the
projections were centred on another environment; with the miscalibrated ground-out share (section 16) the odds ratio returned ground
outs 9–15% too often and air outs as much too rarely, and home runs about 10–20% too often (a
107-game sample of the 2025 backtest: simulated home runs .0331 a PA against .0303 actual, ground
outs .250 against .220). **Park**: our per-outcome
factors, centred (section 12). **Umpire**: K and BB odds regressed with 4,000 PA. **Weather**: below.

### 17.2 The plate-appearance Monte Carlo (`game_sim.py`)

20,000 games, vectorised over simulations. Nine outcomes (K, BB, HBP, 1B, 2B, 3B, HR, GO, AO),
combined by the generalised odds ratio:

```
q_i = b_i(t) · p_i(h) / l_i(h, t) × park_i × weather_i × umpire_i × home_i,     P_i = q_i / Σ q
```

Switch hitters bat from the side opposite the pitcher. **Times through the order** multiply
the starter's outcomes (second time: K ×0.95, HR ×1.07; third and later: ×0.90 and ×1.13, the
row normalised over the usual 39/39/22% mix so the starter's average is neutral). **Home
batting** multipliers [0.981, 1.027, 1.00, 1.012, 1.024, 1.024, 1.024, 1.00, 1.00] (K, BB,
HBP, 1B, 2B, 3B, HR, GO, AO) make an average matchup about .53 for the home side (2026's
regular season: .529 over 2,419 games); away batting uses the reciprocals.

**Base-out transitions** come from an empirical table T[event, bases, outs] fitted on Statcast
PAs (`transitions_mlb.json`: 548,808 PAs of 2024–2026), with the documented default rules as a
prior (a single scores a runner from second with p 0.62, 0.80 with two outs; a double play on
a ground out with a runner on first and fewer than two outs with p 0.42; ...); a "running"
transition (steals, caught stealing, wild pitches, pickoffs, balks) is drawn before each PA
from a second table. **The starter** leaves when his pitches reach a limit L ~ N(μ, sd), his
runs allowed reach R ∈ {4: .25, 5: .35, 6: .25, 7: .15}, or, at the start of an inning on his
third time through, with probability 0.35 once within 15 pitches of L. L's mean is μ + 0.266 (μ −
70.5) (`PC_LIMIT`, fitted by `calibrate_pitch_limit` so the realised mean pitch count is μ: the
recent counts already include the early exits the other two rules reproduce; centred on μ the
simulated starts ended about 4% short, 84.5 pitches for μ = 88, and starters faced .567 of the
batters in the 2025 backtest sample against .596 actual; .577 against .582 in 2022 and .632 against
.638 in 2016 after the change). Pitches per PA are 1 +
Poisson(m_e − 1) by outcome (fitted). **The bullpen**'s "hi" tier pitches from the 8th inning
on in games within three runs (and in extras), else "mid". **Game flow**: nine innings, no
bottom half when the home team leads, walk-offs (a non-home-run walk-off counts only the
winning run), the automatic runner in regular-season extra innings from 2020, a coin flip
after the 30th inning.

**Weather** (`weather_mult`): HR odds × exp(a × (temp − 70)) (the deviation capped at ±40 °F),
hits on contact × exp(c × (temp − 70)), HR odds × exp(b × mph × direction) (wind capped at 30
mph; out to centre 1.0, out to left or right 0.8, in negative, across 0), with doubles moved by a
quarter of the wind term and air outs by −5% of it; neutral under a closed roof. From 2 October
2026 a, b and c are **fitted** (`game_inputs.fit_weather`) on the three previous seasons' open-air
regular-season games, within parks: binomial HR per PA with a venue fixed effect + a·dt + b·wind,
and non-HR hits per non-HR ball in play with a venue effect + c·dt (2015: a 0.0129, b 0.0047, c
0.0016; 2015–2017: 0.0095, 0.0055, 0.0016; 2020–2022: 0.0108, 0.0094, 0.0022; 2023–2025, used for
2026: 0.0103, 0.0082, 0.0008). The fixed values before (0.011, 0.018, 0.0015) had a wind term about
twice the fitted one, and a game's multiplier was divided by the league's mean, so a park's usual
climate, already in its park factor, counted twice: in the 2016–2017 backtest the simulated totals
moved 3.9 runs per unit of log HR multiplier against 1.6 for the actual totals and 1.5 for the
closing line (2.4 after the change). The multiplier is now divided by the venue's mean over the
previous season's games (20+ reports; else the league's).

**Outputs**: P(home), the run-line covers (home −1.5 / away +1.5 and the reverse), the totals
distribution and P(over) for half-run lines, the first five innings (home / away / tie, totals,
lines), runs per team, the extra-innings rate. The build prices games from yesterday to 3 days
ahead with 20,000 simulations each (`--game-sims`; 2,000 with `--quick`).

### 17.3 Live win probability (`live.py`)

An exact Markov chain with the pre-game strengths: for each batting team and pitching phase
(starter in / bullpen) the lineup's average outcome vector; the distribution of runs to the end
of a half-inning from each (outs, bases) by value iteration (runs to 25); then a backward
recursion over half-innings on the run differential (±30) with the walk-off rule and the
automatic runner; the PA in progress uses count multipliers (K ×exp(0.60s − 0.32b), BB
×exp(0.78b − 0.60s)). Milliseconds per state. A league-average model with no home advantage is
the reference for archive games (`ours_kind` "league").

### 17.4 The market layer (`market_layer.py`, from 21 October 2026)

The simulation's MLB prices are corrected by what the **closing lines of games already played** say about the
teams, the starters and the parks. The game being priced never sees its own market line, so the published price
can still differ from the market and the site's "edge" column keeps its meaning.

- **Moneyline.** For each finished game with a close and a simulation price, r = logit(de-vigged close) −
  logit(simulation). Each day an exponentially weighted ridge regression on the games of the last 400 days
  (weight e^(−age/60 days), ×0.7 per season back) explains r by a constant, the two teams (home +1, away −1, ridge
  1) and the two starters (ridge 2). Published P(home) = sigmoid(a + b (logit p_sim + r̂)), Platt coefficients
  a = 0.010, b = 0.939 (committed, fitted on 2016–2026).
- **Totals.** The same regression on r_t = closing total + 10 × (fair P(over) − ½) + 0.44 − simulated mean
  (0.44: runs scored above the closing total on average in 2016–2021, because the line is a median and totals skew
  high), with a venue effect, both teams' offence, both teams' run prevention and both starters (ridge 1 each).
  The simulated distribution of total runs is shifted by r̂_t (the published distribution and expected total);
  P(over L) = sigmoid(a + b logit P_shift(over L)) with a = −0.033, b = 0.250, applied in full near the expected
  total (weight exp(−½((L − mean)/2.5)²)) and fading to the shifted distribution further out; whole-run lines
  exclude pushes. The small b says that even after the shift the simulation's game-to-game totals views are
  mostly noise: the published over/under probabilities sit close to one half.
- **Run line.** P(home covers ±1.5) = sigmoid(−0.019 + 0.794 logit P_sim(cover) + 0.925 (logit p_layer −
  logit p_sim)).
- **History in production**: the backtest cache's simulation prices (`data/baseball/cache/backtest`) and the
  build's own ledger of pre-game simulation prices (manifest `sim_prices`, written by `scripts/build_bullpen.py`),
  joined to the store's closing lines (`edge.game_prices`); this season and the last. With fewer than 300 usable
  games the layer is off and the simulation is published as it is. Triple-A has no market lines and no layer. A
  page's payload keeps the simulation's own numbers under `sim` and the layer's inputs under `layer`.
- **Cost**: about 5 seconds per build (two stores, one ridge solve per market); no refit of any player model.
- **Validation** (walk-forward: ratings refitted daily, coefficients monthly, on earlier games only; choices made
  on 2016–2021, tested on 2022–2026; 95% CIs resample dates):

| test seasons 2022–2026 | n | simulation | with the layer | market | layer − simulation | share of the gap closed |
|---|---|---|---|---|---|---|
| moneyline v close | 12,236 | 0.6791 | 0.6772 | 0.6744 | −0.0019 (−0.0030 to −0.0010) | 40% |
| run line v close | 12,061 | 0.6782 | 0.6756 | 0.6737 | −0.0026 (−0.0042 to −0.0011) | 57% |
| over/under v close | 11,895 | 0.6981 | 0.6933 | 0.6920 | −0.0047 (−0.0068 to −0.0027) | 78% |
| moneyline v Kalshi 1 h (2025–26) | 4,545 | 0.6838 | 0.6828 | 0.6805 | −0.0010 (−0.0026 to +0.0005) | 32% |
| moneyline v open (2025–26, rotation-guess starters) | 4,888 | 0.6815 | 0.6811 | 0.6806 | −0.0005 (−0.0020 to +0.0010) | n/s |

  Brier moves the same way (moneyline −0.0009, CI −0.0014 to −0.0005). Calibration: the moneyline's slope of
  results on logit p is 0.92 against the simulation's 0.95 on 2022–2026 (paired difference −0.03, CI −0.07 to
  +0.00; 0.89 without the Platt step, which was added after this was seen); the run line's moves from 0.74 to
  1.04 and the over/under's from 0.24 to 0.34 (ECE 0.042 to 0.012). The layer does not beat any market: the close,
  the open and Kalshi all stay sharper.
- **Tried and not adopted**: ratings from the closes themselves (not the residual over the simulation) stacked
  with the simulation (tune 0.6712 against 0.6704 for the residual version); a flag for starters with fewer
  than three starts in the window; fitting the stack to the close instead of the results (equal); moving the
  simulated totals to the line and reading P(over) off the distribution (0.6948–0.6952 on 2017–2021, worse than
  recalibrating, 0.6925).

---

## 18. Season and postseason simulation: `season_sim.py`

The 12-team format (from 2022): per league three division winners and three wild cards;
Wild Card best of three, all at the higher seed ("HHH"); Division Series best of five, 2-2-1
("HHAAH"); LCS and World Series best of seven, 2-3-2 ("HHAAAHH"); seeds 1–2 have byes, 3 v 6
and 4 v 5; the better seed has home field through the LCS and the better record in the World
Series.

- **Series odds are exact**: f(a, b) = p_g f(a+1, b) + (1 − p_g) f(a, b+1) with the home
  pattern (`series_prob`).
- **Game probabilities**: P[i, j] from the game model (`pair_matrix_sim`, 4,000 simulations a
  pairing with each team's latest lineup, its top four starters averaged and its bullpen) or,
  as the fallback, team ratings: rating = (0.40·run differential + 50·prior)/(games + 50),
  se = 0.40·4.3/√(games + 50) × 0.6, P(home) = σ(r_h − r_a + 0.12) (0.12 logit ≈ a .530 home
  win rate between equal teams).
- **Simulation**: 20,000 runs in chunks of 5,000; each draws team-strength errors (from se in
  the regular season, sd 0.08 logit in the postseason) held for the whole run; played games and
  series are fixed from the store; observed pairings override computed seeds.
- **Regular season**: unplayed games simulated; tiebreakers head-to-head among the tied teams,
  intradivision win %, intraleague win %, then a draw (the "last half of intraleague games"
  rule is not modelled). Outputs: division, wild card, bye, postseason odds, seed distribution,
  mean wins with a 90% range, round odds; magic numbers (division: the largest over rivals of
  W_j + R_j − W_i + 1); next-game odds, interventional (simulations reweighted by 1/P(win) or
  1/P(loss)).

---

## 19. Awards and markets: `awards.py`, `sources/markets.py`

### 19.1 Awards

MVP, Cy Young and Rookie of the Year per league by a conditional logit, P(i) = exp(β·x_i)/Σ_j
exp(β·x_j), features z-scored within the league-season's candidates, β by maximum likelihood
with an L2 pull of 0.5 towards the defaults, fitted on the 2015–2025 winners (66, checked
against Baseball-Reference's award pages on 1 October 2026; `VERIFIED = True`); the defaults
alone with fewer than four league-seasons.

| Award | Features (default β) | Candidates |
|---|---|---|
| MVP | value 2.0, HR 0.6, team win % 0.8, wOBA 0.8 | hitters 300+ PA, pitchers 120+ IP (two-way values summed) |
| Cy Young | value 1.6, K 0.8, IP 0.5, RA9 −0.9 | pitchers 40+ IP |
| ROY | value 2.0, playing time 0.5 | no MLB PA in any earlier season on disk, and 100+ PA or 30+ IP |

Value is Bullpen WAR (pitchers: the mean of the RA9 and expected versions), else a proxy
(hitters (wOBA − lg)/1.20·PA/10 + 2.0·PA/600; pitchers a FIP-based figure with constant 3.10).

### 19.2 Markets

The Hardwood's rules: a price is the midpoint (bid + ask)/2 of a live two-sided quote, 0 <
bid ≤ ask < 1 and spread ≤ 0.12; sources are averaged per runner; a field market (World
Series, pennants, awards) is published only when at least max(4, half the field) runners are
accounted for (quoted, written off by a "no bid, ask ≤ 2c" quote, or settled No) and the
implied total is within 0.8–1.3, then de-vigged multiplicatively; two-way markets (series,
games) use p_A = mid_A/(mid_A + mid_B) when both sides are quoted. A game's market probability
is the mean of the prediction markets (fetched for today and tomorrow), else the de-vigged
DraftKings moneyline from the store (q = 100/(ml + 100) or −ml/(−ml + 100)). Team names are
matched by code tables and fuzzy matching with floors (teams 0.72 with a 0.02 margin, players
0.85), never guessed below them. Edges are model − market.

---

## 20. Backtest and validation: `backtest.py` and the model checks

### 20.1 Method

`run(level, seasons=every pitch season from 2016, n_sims=1000, refit_days=7)`, one season at a
time, month by month:

- **model**: the PA simulation (1,000 simulations a game) with inputs from data strictly before
  the game: rest-of-season projections refitted every 7 days from the season's PAs to date plus
  the previous seasons, the season's environment from the counts to date (section 17.1), the
  usage log to the day before, park factors from the three previous seasons, umpire factors and
  each venue's average weather from the previous season, weather effects fitted on the three
  previous seasons, the base-out, running and pitches-per-outcome tables fitted on the two previous
  seasons (`game_sim.fit_tables`; the committed tables are fitted on 2024–2026 and used to carry
  that base running, the 2023 rule changes' steals among it, into every season), posted lineups,
  probables and scheduled innings (the seven-inning doubleheader games of 2020–2021).
- **ratings**: team ratings only (run differential to date, regressed with 50 games to half last
  season's final rating), home field 0.12 logit.
- **starter_record**: a logistic regression on the log5 of the two teams' regressed win % (40
  games of .500), the starters' regressed RA9 difference (40 IP of league average) and home;
  refitted once 500+ training games exist (fixed starting coefficients before).
- **market**: ESPN's closing line (`lines.close`, else the current line), de-vigged
  multiplicatively; a 50/50 model–market blend is also scored. From 2 October 2026 the line is
  checked against the other books in the record (`backtest._market`): ESPN's lead book sometimes
  holds an **in-game line** (totals of 1.5, 4.5 or 18.5, run lines of ±4.5 or −9.5, empty
  moneylines), while every other book shows the pre-game one; when the lead book's total is
  missing, outside 5–16 or a run or more from the books' median, or its moneyline is empty, every
  field comes from the books (the median de-vigged moneyline, the books at the median total, the
  ±1.5 run line), and ESPN's "Live Odds" book (from 2024) is never used. 829 games were affected
  (2016 111, 2017 109, 2018 194, 2019 246, 2020 89, 2021 60, 2022–2024 20), and the in-game lines had
  flattered the market: 2019's close scored 0.6452 with them and 0.6578 without.
- **Scores**: log-loss (p clipped at 10⁻⁴), Brier, ten-bin reliability; every model also on the
  games with a market line. Totals: P(total > the closing line) against the market's own over
  price (pushes excluded); run line: P(home covers); postseason series at game 1 from the closed
  form.

Output: `docs/bullpen/data/mlb/calibration.json` (`write_calibration`), per-season partials
cached under `cache/backtest/` (`mlb_<S>_n1000_v5.json`) so a run can resume; about 5–6 minutes a
season on the owner's machine. **The committed run covers every season 2016–2026** (25,374 games;
generated 08:34 UTC on 2 October 2026). It replaces the 05:17 UTC run of the same day, which is
quoted below as "before".

### 20.2 Results (committed `calibration.json`, 2016–2026)

From 21 October 2026 the committed file's `games` block scores the **published** model, the simulation with the
market layer (section 17.4), walk-forward over 2016–2026 (`scripts/mlb_market_layer.py`); the simulation alone is
kept under `games.sim`. Pooled: moneyline 0.6746 (simulation 0.6766; on the games with a close 0.6745 against
0.6714), over/under 0.6931 (0.6999; market 0.6923), run line 0.6766 (0.6807; market 0.6754), expected total 9.03
runs against 9.03 actual and within 0.15 in every season. The tables below are the simulation alone (2 October).

Log-loss (Brier) per season. "Model" and "ratings" and "S&R" (starter and record) are over every
scored game; "model v close" and "close" are on the games with a closing moneyline.

| Season | Games | Model | Ratings | S&R | With a close | Model v close | Close | Gap | Blend |
|---|---|---|---|---|---|---|---|---|---|
| 2016 | 2,451 | 0.6775 (0.2423) | 0.6861 | 0.6863 | 2,402 | 0.6773 | **0.6736** (0.2404) | +0.0036 | 0.6744 |
| 2017 | 2,443 | 0.6783 (0.2427) | 0.6825 | 0.6832 | 2,409 | 0.6784 | **0.6749** (0.2410) | +0.0035 | 0.6755 |
| 2018 | 2,432 | 0.6732 (0.2402) | 0.6727 | 0.6778 | 2,336 | 0.6725 | **0.6694** (0.2384) | +0.0031 | 0.6699 |
| 2019 | 2,450 | 0.6668 (0.2371) | 0.6675 | 0.6742 | 2,446 | 0.6668 | **0.6578** (0.2330) | +0.0090 | 0.6607 |
| 2020 | 902 | 0.6750 (0.2411) | 0.6773 | 0.6814 | 899 | 0.6747 | **0.6657** (0.2365) | +0.0090 | 0.6688 |
| 2021 | 2,428 | 0.6752 (0.2412) | 0.6761 | 0.6777 | 2,422 | 0.6751 | **0.6714** (0.2393) | +0.0038 | 0.6721 |
| 2022 | 2,452 | 0.6700 (0.2386) | 0.6740 | 0.6734 | 2,452 | 0.6700 | **0.6654** (0.2363) | +0.0046 | 0.6666 |
| 2023 | 2,458 | 0.6813 (0.2442) | 0.6814 | 0.6834 | 2,458 | 0.6813 | **0.6771** (0.2421) | +0.0043 | 0.6782 |
| 2024 | 2,461 | 0.6788 (0.2430) | 0.6803 | 0.6831 | 2,448 | 0.6791 | **0.6708** (0.2394) | +0.0083 | 0.6738 |
| 2025 | 2,470 | 0.6826 (0.2449) | 0.6808 | 0.6834 | 2,464 | 0.6829 | **0.6765** (0.2419) | +0.0064 | 0.6787 |
| 2026 | 2,427 | 0.6826 (0.2448) | 0.6846 | 0.6836 | 2,426 | 0.6826 | **0.6788** (0.2430) | +0.0037 | 0.6799 |
| **Pooled** | 25,374 | **0.6766** (0.2419) | 0.6786 (0.2428) | 0.6806 (0.2438) | 25,162 | 0.6765 (0.2419) | **0.6714** (0.2394) | +0.0052 | 0.6728 |

Runs, totals and run lines (O/U: P(over the closing total) against the market's own over price;
a coin scores 0.6931):

| Season | Model runs | Actual | Bias (before) | O/U games | Model O/U (before) | Market O/U | Run line model | Run line market |
|---|---|---|---|---|---|---|---|---|
| 2016 | 9.11 | 8.94 | +0.18 (+0.76) | 2,301 | 0.7094 (0.7216) | 0.6921 | 0.6823 | 0.6773 |
| 2017 | 9.25 | 9.28 | −0.03 (+0.53) | 2,301 | 0.7012 (0.7030) | 0.6920 | 0.6855 | 0.6788 |
| 2018 | 8.80 | 8.87 | −0.07 (+0.50) | 2,234 | 0.6997 (0.7062) | 0.6925 | 0.6744 | 0.6720 |
| 2019 | 9.27 | 9.64 | −0.37 (+0.40) | 2,346 | 0.7012 (0.7400) | 0.6946 | 0.6806 | 0.6786 |
| 2020 | 9.63 | 9.25 | +0.38 (+0.56) | 895 | 0.7023 (0.7016) | 0.6903 | 0.6967 | 0.6888 |
| 2021 | 8.89 | 9.06 | −0.17 (+0.30) | 2,310 | 0.6963 (0.7016) | 0.6929 | 0.6792 | 0.6751 |
| 2022 | 8.98 | 8.56 | +0.42 (+0.51) | 2,330 | 0.6995 (0.7012) | 0.6922 | 0.6835 | 0.6775 |
| 2023 | 9.30 | 9.20 | +0.09 (+0.31) | 2,359 | 0.7001 (0.6992) | 0.6929 | 0.6816 | 0.6774 |
| 2024 | 8.80 | 8.79 | +0.01 (+0.25) | 2,436 | 0.6928 (0.7011) | 0.6925 | 0.6845 | 0.6731 |
| 2025 | 8.87 | 8.88 | −0.01 (+0.06) | 2,454 | 0.6975 (0.6975) | 0.6896 | 0.6658 | 0.6631 |
| 2026 | 8.95 | 8.97 | −0.01 (−0.16) | 2,316 | 0.7007 (0.6998) | 0.6928 | 0.6834 | 0.6769 |
| **Pooled** | 9.04 | 9.03 | **+0.02** (+0.35) | 24,282 | **0.6999** (0.7068) | 0.6923 | 0.6807 | **0.6754** |

Before: 9.38 runs a game against 9.03 pooled, high in 10 of 11 seasons; model log-loss 0.6776,
O/U 0.7068 on 24,092 games (the "before" O/U column is on the uncleaned lines). Postseason series
at game 1: 97 series, log-loss 0.6570, Brier 0.2322 (0.6529 before; base rate .577 for the
home-field team).

**What moved the totals** (each step measured on the backtest or a 250-game instrumented sample of
it; section 17 has the mechanics):

1. *The league reference and the projections' environment.* With actual batters and pitchers and
   no environment, the odds-ratio matchups returned 2.5–5% too many home runs and 9–15% too many
   ground outs (and as many too few air outs), because the league reference was a different table
   from the one the projections were centred on, the projections' target leaked the whole target
   season, and the ground-out share was miscalibrated (`gb_out_ratio`). The instrumented 2016
   sample went from 0.89 runs a game high (108 games) to 0.22 high (250 games) on this step.
2. *Pitchers batting* (2016–2021) were projected near the position players (.297 against .195 in
   2016).
3. *Starter innings*: centred on the recent average, the pitch limit ended starts about 4% early;
   the starters' share of batters faced went from .567/.554/.600 to .577/.582/.632 against
   .596/.585/.638 actual (2025, 2022, 2016 samples).
4. *Weather*: the fixed wind term was about twice the fitted one and each park's usual climate
   counted twice; the simulated totals moved 3.9 runs per unit of log HR multiplier against 1.6
   for the actual totals (2.4 after).
5. *The season's environment* (`game_env`), *era-specific base-out tables*, *usage-weighted
   relievers*, *centred park factors* and *scheduled innings*: the 2016–2026 run levels above.
   (Neutral teams with each season's actual outcome rates scored 9.04 runs with the committed
   2024–2026 tables in 2016 against 8.96 with 2016's own, 8.96 actual.)

Reading it honestly:

- **The mean is now unbiased pooled** (+0.02 runs a game) and within 0.2 runs in 8 of 11 seasons.
  The misses left are the run environment moving within a season in ways the previous season's
  calendar does not anticipate: 2019 (−0.37; the livelier ball, −0.6 in April–June), 2020
  (+0.38; 60 games from late July against 2019's juiced year) and 2022 (+0.42, mostly July–October,
  after a 2021 whose second half rose with the June sticky-substance checks). Postseason games
  score fewer runs than the model expects in most seasons (October +0.4 to +1.3 in 2016, 2019,
  2022), a regular-season bullpen model in games where managers shorten the bullpen.
- **Totals are still worse than a coin**: 0.6999 pooled against 0.6931 (and the market's own
  0.6923), below a coin only in 2024 (0.6928). The mean is no longer the problem (the model's
  P(over) averages within 0.03 of the over frequency in 8 of 11 seasons; 2020 and 2022 0.05–0.06 high); its game-to-game
  deviations from the closing total carry almost no information (2016–2017: the actual total's
  residual on the line regresses on the model's deviation from it with slope 0.10; correlation
  0.02), while they spread P(over) with a standard deviation of about 0.08, which costs about
  0.01 nats. Widening the simulated distribution (the totals are under-dispersed: variance 17.5
  against 20.0 around the model's mean in 2016–2017; the PIT histogram is U-shaped) moves the
  score by under 0.002 and was not adopted. Park-level errors remain (with builder C's contact
  factors the model is about 1.3 runs under the line at Coors Field and 0.8 at Chase Field before
  its 2018 humidor, 2016–2017; our own home/road factors fix those two but are noisier elsewhere,
  0.6781 game log-loss against 0.6793 and 0.7085 O/U against 0.7035 in 2017). No post-hoc
  recalibration of P(over) was applied.
- **The closing line still beats the model in every season**, by 0.0052 nats pooled on the
  cleaned lines (0.0031–0.0090 a season); the 50/50 blend never beats the close.
- **Against the simple baselines** the model is ahead pooled (0.6766 against 0.6786 for team
  ratings and 0.6806 for starter and record) and in every season but 2018 (0.6732 against 0.6727)
  and 2025 (0.6826 against 0.6808); 2023 is a near tie (0.6813 against 0.6814).
- **2026** scores 0.6826: the 1 October run (before the refit) scored 0.6823 and the 05:17 refit
  0.6845. The refit's loss came from the refitted stabilisation constants and base-out tables
  (each about 0.0014 when put back one at a time; the base-out tables then included 2026's own
  plate appearances). This run fits the tables on 2024–2025 for 2026 and adds the changes above;
  2026 recovers to within 0.0003 of the pre-refit score, and 2025 moves from 0.6847 to 0.6826.
- **Run line**: 0.6807 against the market's cover prices' **0.6754** (24,983 games; 24,819 with
  market prices), **behind in every season**. The figure published before 2 October 2026 (market
  0.6877, the model "ahead in every season but 2017 and 2020") was an artefact: ESPN's records hold
  the two run-line prices the wrong way round in 4–14% of closing lines (14–20% of the 2024–2026
  opens), and those games' stored home −1.5 price implied 63% where the side covered 33%.
  `markets.run_line_swapped` now exchanges any pair that breaks P(home −1.5) < P(home wins) <
  P(home +1.5) (`store_lines`, so the backtest, the game pages and the edge research all read the
  corrected prices); the market column above is recomputed from the cached model rows
  (`backtest.refresh_market`).

### 20.3 The model checks

- **xwOBA+ against Savant's xwOBA**: section 8 (2015–2026 pooled, r .416 against .408 within seasons).
- **Stuff+ validity** (`checks.stuff`): this season's Stuff+ against next season's K% and RA9
  for pitchers with 300+ BF in both, beside this season's K%, pooled over every pair of
  seasons 2015→2016 to 2025→2026 (1,109 pitcher-seasons): Stuff+ → next K% 0.477 (K% → next
  K% 0.711); Stuff+ → next RA9 −0.242 (K% → next RA9 −0.404). **Past K% is clearly better on
  both.** (The 1 October figure, 224 pitchers before the backfill, was 0.614 against 0.709 and −0.341 against
  −0.344.) The early seasons' Stuff+ comes from models trained on fewer than four earlier
  seasons (2015's on itself), which may lower it; the run-value comparison in section 3.4 is the
  one where Stuff+ leads.
- **Projections** against Marcel: section 16.
- **Framing and fielding** against Savant: sections 9 and 10.2.

---

## 21. Known limitations

1. **The closing line beats the model**, as it should: in every season 2016–2026, by 0.0052
   in log-loss pooled on the cleaned closing lines (0.0031–0.0090 a season), and baseball games
   are close to coin flips, so even good models improve on 50/50 by little. The run-line market beats the model too
   (0.6754 against 0.6807 pooled, every season) once ESPN's swapped run-line prices are put right
   (section 20.2). Against the prices one could have bet, the model shows no edge at the close and no
   robust edge at the open (docs/research/mlb_edge.md). The model is ahead of
   team ratings pooled (0.6766 against 0.6786) and behind them in two seasons (2018, 2025). The market layer (section
   17.4, from 21 October 2026) closes 40% of the moneyline gap on 2022–2026 (0.6772 against the close's 0.6744,
   the simulation 0.6791) and 57% of the run-line gap, but no market is beaten.
2. **Totals**: the mean is unbiased pooled (+0.02 runs a game) but misses by about 0.4 runs in
   seasons whose run environment moved within the year (2019, 2020, 2022), and the over/under
   probabilities still score worse than a coin (0.6999 against 0.6931; the market 0.6923): the
   model's game-to-game deviations from the closing total carry almost no information (section
   20.2). Park extremes (Coors Field, the pre-humidor Chase Field) are under-predicted with the
   contact park factors. The market layer's venue effects take the park extremes from earlier closing totals and
   bring the published over/under to a coin's score (0.6933 on 2022–2026; the market 0.6920). Hitters' wOBA projections trail the Marcel baseline (−2.4%) in seasons
   of rising offence (section 16).
3. **Inferred fielder positions**: OAA agrees with Savant's moderately (r 0.41–0.62 over 2016–2026), least at
   shortstop; framing agrees closely.
4. **Talent, not results, in WAR**: batting value is regressed expected value.
5. **Estimated events**: Statcast steals from runner movement; inherited runners not
   reassigned; no earned runs (RA9, FIP on the RA9 scale).
6. **History**: no play-by-play before 1908; before Statcast, fielding is a range-factor proxy
   that overrates some dead-ball-era fielders.
7. **Recent-season training** (four seasons for the pitch models) may lag rule and equipment
   changes (the 2023 pitch clock and shift limits, the 2026 ABS challenges).
8. **Physics** uses sea-level air for spin and flight; weather effects are simple linear terms.
9. **ABS challenges** before a plate appearance's last pitch are not seen.
10. **Simulations** freeze strength within a run apart from the drawn error, model no injuries
    or trades, and simplify tiebreakers.

---

## 22. Where the code and other texts disagree (resolved)

Found on 1 October 2026 while writing these documents and **resolved the same day** (items 1–11;
12 is a contract note left as is). The code and the committed payloads were taken as the source
of truth. Items 1–6 were the site's Methodology (`docs/bullpen/assets/js/docs.js`) and page
texts against the code and the data; 7–12 docstrings, contracts and quoted figures.

### 22.1 The Methodology against the code

1. **Backtest coverage** (resolved): "Every game from 2016 is priced walk-forward" now reads that
   the code runs from 2016 while the committed `calibration.json` covers 2026 only (2,427
   games), with the 2016–2026 run following the Savant / ESPN backfill; the calibration page
   states the seasons its file holds. `backtest.py`'s docstring says the same. Superseded on 2 October 2026: the committed run now covers 2016–2026 (25,374 games), and
   the Methodology says so.
2. **History span** (resolved): every claim that history starts in 1901 now says 1908 — the
   Methodology overview, Retrosheet and identity paragraphs, historical WAR and the
   Limitations; `history.js` (header, year inputs, the dead-ball era option, the note, all
   driven by `history.json`'s `first` with 1908 as the default); the hub's history tile;
   the docstrings of `history.py`, `war.py` and `re24.py`; and `CONTRACT.md`. Statements that
   Retrosheet game logs start in 1901 are true and stay.
3. **Weather in the game model** (resolved): the page now gives the model as coded: home-run
   odds × e^(0.011·Δt) and singles, doubles and triples × e^(0.0015·Δt), Δt the deviation from
   70 °F capped at ±40 (30–110 °F); wind × e^(0.018·mph·d) on home runs with a quarter of that
   on doubles and −5% of it on air outs, wind capped at 30 mph; neutral under a closed roof.
4. **Pitching+ figure** (resolved): the unrecorded 0.39 (and its 0.29 / 0.35 companions) is
   removed from the Methodology and the `pitching.py` docstring; no Pitching+ validation figure
   is published. Section 3.3 above keeps the history of the claim.
5. **Stuff+ validity** (resolved): the Methodology now states only what the published payload
   supports, with its definition: the calibration page's check (this season's Stuff+ against
   next season's K% and RA9, 300+ batters faced in both, beside this season's K%), where past
   K% leads on K% (0.709 against 0.614) and the two tie on RA9 (−0.344 against −0.341), so
   Stuff+ does not beat past results on that measure. The 0.46 against 0.34 run-value figure
   (1,000+ pitches, git-ignored report, section 3.4) is not on the site. The calibration
   page's reading also now says which predictor leads for RA9.
6. **Framing agreement** (resolved): the Methodology quotes the per-season range, 0.93 (2026,
   partial) to 0.99 (2022) over 2020–2026, not 0.99. The calibration page could not show the
   framing and fielding checks at all (it expected one `r`, the payload holds one entry per
   season); its reading and its "Framing and fielding against Savant" table now render the
   per-season `checks.framing` and `checks.oaa` and state the range.

### 22.2 Docstrings and contracts

7. **`backtest.py`** (resolved): the ratings forecaster and the series mirror now cite
   `season_sim.HFA_LOGIT` = 0.12, noting 0.16 is only `BASE_COEF`'s starting home coefficient.
8. **`game_inputs.py`** (resolved): relievers inside a tier are weighted by availability ×
   √(recent batters faced). (Changed on 2 October 2026 to availability × recent batters faced,
   section 17.1.)
9. **`sources/espn.py`** (resolved): events match the nearest UTC start within 30 hours
   (`match_events`, `max_hours`).
10. **`xwoba.py`** (resolved): the docstring now quotes the committed `checks.xwoba` (2024
    .408 / .400, 2025 .471 / .476, 2026 .237 / .225, 2024 H2→2025 H1 .433 / .439, 2025 H2→2026
    H1 .337 / .338) and the true sample floors (200 PA in the first period, 100 in the next).
11. **`war.py`** (resolved): the historical section is headed "1908 onward".
12. **`CONTRACT.md`**: still says stores are "committed for completed seasons" (none was on
    1 October 2026, while the backfill ran); `PAYLOADS.md` lists the front-end routes as
    planned, and `core.js` registers `#/umpire/<id>`, `#/park/<id>` and the level prefix as
    built.

---

## 23. NPB models: `npb/models.py`, `npb/backtest.py`

Added 13 October 2026. NPB publishes no pitch tracking and no fielding data, so the NPB level has none of sections
2-17's models. Everything here is built from line scores, box scores and season totals; since 15 October 2026 the
plate-appearance play-by-play of 2016 on adds the metrics of section 24.

### 23.1 League constants and linear weights

For each league-season (Central and Pacific apart: the Central's pitchers bat until 2027), BaseRuns is calibrated
to the league's runs by its B multiplier (`calibrate_b`, bisection), and the linear weights are its numerical
derivatives at the league's totals (`linear_weights`: 1B, 2B, 3B, HR, BB, HBP, out, SB, CS). wOBA weights are the
weights less the out's, scaled so the league's wOBA equals its OBP (`woba_weights`). The batting totals leave out
pitchers' batting (a pitcher is a row of the pitching tables whose plate appearances are below half his batters
faced). The FIP constant is set on both the ERA and the run-average scale. Runs per win follow FanGraphs' rule,
9 x (runs per inning) x 1.5 + 3, about 8.3 at NPB's 3.5 runs a game.

### 23.2 Park factors

`park_factors`: for each club, (runs per game in its home games) / (runs per game in its road games) over the
season and the two before, halved toward 1 (half the games are at home) and clipped to 0.83-1.20; clubs with fewer
than 30 home or road games get 1. Regular-season games only, 2005 on.

### 23.3 WAR-lite

`season_war`: position players get batting runs ((wOBA − league wOBA) / scale x PA, plus the park correction
(league R/PA x (1 − park factor) x PA)), base-stealing runs (SB and CS at the linear weights, less the league's rate
per time on first), and a positional adjustment per 162 games (C +12.5, SS +7.5, 2B/3B/CF +2.5, LF/RF −7.5,
1B −12.5, DH −17.5; IF 0 and OF −4.2 when only the group is known) by the position a player started most in the box
scores. Pitchers get (league RA9 − FIP on the RA9 scale, park-adjusted) / 9 x IP. The replacement level is set so
the season's wins above replacement total 12 clubs x scheduled games x (.500 − .294), 57% to position players and
43% to pitchers (one rate per PA and one per inning). No fielding, framing or catcher defence: the name says "lite".

### 23.4 Team ratings

`Ratings`: offence and defence per club on the log scale of runs per nine innings. Expected runs for the home club
are exp(mean + offence(home) − defence(away) + home edge), times (1 + w x share x (starter ratio − 1)) for the away
starter, where the starter ratio is his earned runs per out shrunk with 240 outs of league-average pitching, over
the league's, and share is 0.62; plus 0.04 log runs when a club gains the DH at a Pacific park (minus when it loses
it at a Central one). After each day: offence += eta x (runs − expected), the opponent's defence −= the same, the
league mean += eta_mean x the average surprise; runs in extra-inning games are scaled to nine innings. At a new
season every rating is multiplied by `carry` and starters' records are halved.

### 23.5 The game model with ties

`game_probs`: runs in one half-inning are negative binomial with mean (expected runs)/9 and a size fitted by maximum
likelihood to every half-inning of the 2005-2025 line scores (each with its batting club's season runs per inning
as the mean). Nine half-innings add up to a negative binomial with size 9 x size, so P(home ahead), P(level),
P(away ahead) after nine innings are exact sums over the joint table. Each extra inning is won by the home club,
the away club or neither with the one-inning probabilities, so P(still level after k extra innings) =
P(level after nine) x P(level inning)^k: the limit is 3 extra innings normally, 1 in 2020, 0 in 2021, 3 in the
Climax Series, 6 in Japan Series games 1-7 to 2017 and 3 since 2018, none from game 8; the 2011-12 time limit is an
average of 1.5 extra innings (`GameParams.eff_extras_time_limit`). Walk-offs change the margin, not the winner, so
the win and tie probabilities do not depend on them. `backtest.GameTable` tabulates the model on a grid of expected
runs (1-9, step 0.1) for speed.

### 23.6 Simulations

`build.simulate`: the remaining regular-season games are drawn three ways from the game model; the standings are
ranked by W/(W+L), then the Central's more wins / the Pacific's head to head, then last season's rank (inside
the simulation; the payload's standings apply the full rules, `models.rank`). The Climax Series stages and the
Japan Series are then played game by game (`series_winner` encodes the advantage, the level-wins rule and the early
finish; `simulate_stage` and `simulate_js` are vectorised versions used in the tests), with the parks, the DH and
each game's inning limit. Postseason games already played are kept.

### 23.7 The backtest

`backtest.run` (results in section 23.8): every final game 2006 on (2005 warms the ratings up), priced before the
day from the ratings of earlier days, the starters known (NPB announces them the day before). Parameters chosen on
2006-2015 by grid (eta 0.006-0.016, carry 0.4-0.7, home edge 0.02-0.05, starter weight 0-1), scored out of sample
from 2016. Metrics: three-way log loss and Brier score; a baseline with the home, tie and away rates of earlier
seasons; accuracy of the favourite in decided games; predicted against actual ties by season; the error of the
expected total; calibration of P(home win) by decile; the model against Kalshi's last pre-game mid (2026) on the
binary "the home club wins".

### 23.8 Results (the committed `npb/calibration.json` of 13 October 2026, 18:17 UTC)

Run before the box-score backfill reached the past seasons: results 2005-2026 complete (every season's standings
rebuilt from the games equal NPB's official W-L-T exactly), box scores 2026 only. So the starter term was not
fitted (`sp_weight` 0), and the half-inning size is the default 0.45 (fitted from 2005-2025 line scores once they
are in). `scripts/npb_backfill.ps1`'s run is followed by a detached re-run of `backtest.run()`
(`logs/npb_backtest.log`), which refits both; update this table then.

Chosen on 2006-2015: eta 0.0012, carry 0.9, home edge 0.12 log runs, the 2011-12 time limit as 1.0 extra
inning on average.

| | Games | Log loss (3-way) | Baseline | Brier | Baseline | Favourite right | Ties predicted / actual | Decided games: log loss / baseline |
|---|---|---|---|---|---|---|---|---|
| Train 2006-2015 | 8,803 | 0.7930 | 0.8067 | 0.5184 | 0.5251 | 55.9% | 3.2% / 3.1% | 0.6819 / 0.6882 |
| **Test 2016-2026** | 9,482 | **0.8003** | 0.8166 | 0.5223 | 0.5299 | 55.4% | 3.6% / 3.4% | **0.6838 / 0.6905** |
| Postseason 2016-2026 | 182 | 0.7554 | 0.7925 | 0.5004 | 0.5181 | 58.8% | 2.9% / 2.8% | 0.6692 / 0.6842 |

Three-way skill out of sample: 2.0% of the baseline's log loss; about half of it is the ties (the model knows each
season's inning limit, the baseline only earlier seasons' tie rates: 2021's nine-inning season is 1.0620 against
0.9835), the rest team strength (decided games, 1.0%). Calibration of P(home win) by decile (test): every decile
within 2.8 points, the middle deciles overpredict the home club by 1-3 points (the test seasons' home rate, 52.0%,
is below the training seasons', 53.3%). Expected total: mean absolute error 3.2 runs, bias +0.005 (regular season);
postseason totals run 0.58 below the model.

**Against Kalshi** (2026, 846 games with a pre-game mid, binary "the home club wins"): the model 0.6775, Kalshi
0.6707, their average 0.6725; Brier 0.2422 against 0.2395; mean absolute gap 4.2 points, correlation 0.78. The
market is better, as it is for MLB; the starters (known to the market, not yet to the fitted model) are the
obvious missing input.

| Season | Games | Log loss | Baseline | Decided | Baseline | Ties pred. | Ties |
|---|---|---|---|---|---|---|---|
| 2016 | 878 | 0.7642 | 0.7770 | 0.6785 | 0.6891 | 2.1% | 2.1% |
| 2017 | 880 | 0.7510 | 0.7687 | 0.6723 | 0.6875 | 2.1% | 1.8% |
| 2018 | 877 | 0.7727 | 0.7814 | 0.6904 | 0.6974 | 1.8% | 1.9% |
| 2019 | 876 | 0.7886 | 0.7905 | 0.6892 | 0.6903 | 1.9% | 2.5% |
| 2020 | 726 | 0.8510 | 0.8693 | 0.6736 | 0.6832 | 6.1% | 5.5% |
| 2021 | 874 | 0.9835 | 1.0620 | 0.7005 | 0.6963 | 11.6% | 12.0% |
| 2022 | 877 | 0.7782 | 0.7794 | 0.6936 | 0.6928 | 2.6% | 1.9% |
| 2023 | 877 | 0.7743 | 0.7807 | 0.6841 | 0.6884 | 2.7% | 2.2% |
| 2024 | 878 | 0.8101 | 0.8161 | 0.6858 | 0.6908 | 3.0% | 3.4% |
| 2025 | 876 | 0.7820 | 0.7936 | 0.6773 | 0.6893 | 3.1% | 2.6% |
| 2026 | 863 | 0.7565 | 0.7728 | 0.6760 | 0.6892 | 2.6% | 1.9% |

### 23.9 Known limitations

- No starters in the fitted model until the box-score backfill completes (above); no lineups, injuries or
  bullpen usage at all.
- The season simulation breaks Pacific League ties by last season's rank, not head to head (the standings
  payload applies the full rules).
- WAR-lite has no fielding; positions before 2005 are the profile's group (P, C, IF, OF). The play-by-play (section 24)
  records who fielded every ball but not who stood where on each play, so a fielding component is not attempted.
- The 2011-12 time limit is an average number of extra innings, not a clock.
- Ratings are carried over at 0.9 a season with no roster information (a club that lost its ace starts the
  next season rated as if it had not).

---

## 24. NPB play-by-play metrics and expected stats: `npb/pbp.py`, `npb/pbpstats.py`, `npb/lab.py`

Added 15 October 2026. The data and its limits are in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 14.2: from 2016 every
plate appearance with the base-out state before it, the batter and pitcher, the count before the last pitch and the result
with the fielder; no pitch types, velocities or locations, and no trajectory for hits.

### 24.1 The classifier (`pbpstats.classify`)

Each result text becomes an event (K swinging / looking / bunt, BB, IBB, HBP, interference, 1B, 2B, 3B, HR, SF, SH, out,
reached on error, fielder's choice), a trajectory for batted outs, errors, fielder's choices and bunts (ground ball, line
drive, fly to the outfield, pop-up: a fly or foul fly to an infielder or the catcher, bunt), the fielder (1-9, the two gaps),
and for hits the depth (infield, in front of an outfielder, down a line, a gap, over an outfielder or a ground-rule double,
home run). Rows written "（途中交代）" (a batter replaced during the count) and "（途中終了）" (a game stopped during one) are not
plate appearances.

### 24.2 Runs, RE24 and the season tables (`pbpstats.game_rows`, `re_matrix`, `season_tables`)

In each half-inning the rows (plate appearances and the running events listed between them) are taken in order. Runs in a
row follow from runners in and out: runners before + the batter = runners after + outs made + runs, the "after" state being
the next row's "before" state; the half-inning's last row gets the line score's runs less those already counted (a half
whose conservation fails, about 1% of them, keeps no runs and is left out of RE24). Only the game's last half-inning may end
short of three outs (a walk-off or a called game). The run-expectancy matrix is the season's own: mean runs from each of the
24 states to the end of complete half-innings. RE24 of a plate appearance = RE(after) - RE(before) + runs (RE(after) = 0 at
the end of an inning); a wild pitch or passed ball during a plate appearance is not listed, so its advance is charged to
that plate appearance.

Tables per batter, pitcher and club: the counting events; strikeouts swinging and looking; first-pitch in play (the
plate appearance ended on pitch one with the ball in play), reached two strikes (a two-strike count before the last pitch, or
a strikeout), reached three balls, full count; average and strikeouts in two-strike plate appearances; batted-ball outs by
trajectory and pop-ups per ball in play; pull, centre and opposite by the fielder and the batter's side (a switch hitter's
side is the one opposite the pitcher's hand; hands from the clubs' stat pages); hits by depth; BABIP by field; home runs per
air ball = HR / (HR + fly outs to the outfield + sacrifice flies); ground-ball double plays per opportunity; wOBA (with the
league-season weights of players.json) overall, with runners in scoring position, against left- and right-handers;
times through the order for pitchers (the first, second and third-or-later time a pitcher faced a batter in a game); pitches
per batter faced from the box scores' pitch counts. Cached per season on the play-by-play file.

### 24.3 Expected stats (`pbpstats.fit_expected`, `lab.expected_models`)

xBABIP: weighted least squares (weights the harmonic mean of the two seasons' balls in play; features standardised, a light
ridge) of the **next** season's BABIP on this season's profile: pop-ups per ball in play, the ground-ball and line-drive
shares of batted-ball outs, pull and opposite-field shares, bunts per plate appearance, speed ((SB + CS) / times on first)
and the park's run factor. The next season is the target so the fit keeps what persists; a same-season fit would learn the
mechanical link between a season's hits and its own outs (a batter whose ground balls find holes has fewer ground-ball outs
that season). A second fit of the same form predicts the wOBA value per hit in play. Pitchers get the same pair of fits on
the profile they allow (no speed). Walk-forward: a season's model uses only pairs whose later season is before it; seasons
without enough earlier pairs (40) borrow the first model fitted and are flagged in the payload (`expected.out_of_sample`).
xwOBA = (wBB uBB + wHBP HBP + wHR HR + BIP x xBABIP x expected value per hit) / (AB + BB - IBB + SF + HBP): walks, hit
batters, strikeouts and home runs as they happened (the data hold no contact quality).

Why not "type x direction x park", as Statcast's xBA would: a hit's record says where it went but not how it was hit, and
whether a ball counts as an outfield ball depends on whether it got through, so any per-ball class built from these labels
contains its own outcome. The profile model is the honest version.

### 24.4 Coverage and validation

Coverage on 15 October 2026, 18:20 (the detached crawl, `logs/npb_pbp.log`, was then reading 2017 and 2016, due about
19:40; each hourly build folds a new season in, and `python scripts/npb_fetch.py --report --from 2016 --to 2026` prints the
counts):

| Season | Final regular-season games | With play-by-play | Plate appearances | With pitch counts | Half-innings unreconciled | `nx` ids left (bat / pit) |
|---|---|---|---|---|---|---|
| 2016 | 858 | crawl in progress | | | | 62 / 39 |
| 2017 | 858 | crawl in progress | | | | 65 / 37 |
| 2018 | 858 | 858 | 65,994 | 0 | 137 of 15,368 (0.9%) | 0 / 0 |
| 2019 | 858 | 858 | 65,803 | 0 | 171 of 15,384 (1.1%) | 0 / 0 |
| 2020 | 720 | 720 | 54,367 | 0 | 103 of 12,704 (0.8%) | 1 / 1 |
| 2021 | 858 | 858 | 63,658 | 0 | 112 of 15,072 (0.7%) | 1 / 1 |
| 2022 | 858 | 858 | 64,176 | 0 | 156 of 15,367 (1.0%) | 1 / 1 |
| 2023 | 858 | 858 | 64,261 | 0 | 161 of 15,390 (1.0%) | 1 / 1 |
| 2024 | 858 | 858 | 63,992 | 0 | 142 of 15,425 (0.9%) | 1 / 1 |
| 2025 | 858 | 858 | 64,381 | 1 | 134 of 15,434 (0.9%) | 0 / 0 |
| 2026 | 858 | 858 | 64,062 | 858 | 142 of 15,322 (0.9%) | 1 / 1 |

Every result text of 2018-2026 classifies (no unknown forms); no plate appearance lacks its pitcher (the 2016-2025 pages name
the starter through the first pitching change or, for a complete game, the box score). Pitch counts: the 2026 box scores
were all read; for 2016-2025 only complete games' box scores are read, so pitches per batter faced is published only for 2026
(`npb_fetch.py --phases pbp --pbp-boxes` reads the rest, about 8,800 requests). Before 2016 npb.jp has no plate-appearance
pages (the `/scores/` folders of 2010, 2014 and 2015 games answer 404), so 2005-2015 have the stat pages' metrics only. The
`nx` column: stat-page rows the rosters could not name, before the play-by-play: about 65 hitters and 40 pitchers a season
(mostly foreign players); after it, at most one.

The expected stats, out of sample (the models fitted only on earlier seasons; targets 2020-2025, the season's profile against
the next season's BABIP, players with 60+ balls in play in both; weighted by the harmonic mean of the two):

| | Pairs | corr(xBABIP, next BABIP) | corr(BABIP, next BABIP) | RMSE xBABIP | RMSE BABIP | RMSE league mean |
|---|---|---|---|---|---|---|
| Hitters | 765 | 0.269 | 0.293 | **0.0335** | 0.0419 | 0.0341 |
| Pitchers | 841 | 0.088 | 0.069 | 0.0351 | 0.0477 | **0.0348** |

Read honestly: for hitters, xBABIP from the profile alone predicts next season's BABIP with a smaller error than the player's
own BABIP and slightly better than the league mean, but it does not correlate better than his own BABIP (which carries skill
the profile cannot see: contact quality); for pitchers, as in MLB, BABIP is almost all defence, park and luck, and the profile
adds nothing over the league mean. The hitter fit puts weight on pop-ups (down), bunts and speed. The lab page prints these
numbers beside any expected metric. RE24's run-expectancy matrix for 2026: 0.39 runs with nobody on and no one out, 2.06 with
the bases loaded and no one out, 0.08 with nobody on and two out.

## 25. Player value, strengths and needs, and the trade simulator: `analytics/value.py`, `analytics/trade.py`

Added 15 October 2026 (docs/VALUE_SECTIONS.md sections 1-3). Nothing here re-estimates a player's value: Bullpen WAR
(section 13) for MLB and Triple-A, WAR-lite (section 23.3) for NPB.

### 25.1 Positions and rates

MLB and Triple-A: games at each position from the pitch table's `fielder_2..9` at every plate appearance (the share of a
team's defensive plate appearances a player held the position; a game batted without fielding is a DH game;
`war.defensive_games`), cached per season. NPB: box-score starts by position (2005 on; from 15 October 2026 written into
players.json as `pos_g`, and the play-by-play's printed names place the foreign players the rosters could not name). A player's
WAR is split across positions by his games there. Pitchers: MLB starters and relievers by an estimate of batters faced in each
role (22 a start, 4.3 a relief game); NPB by outs per game (12 or more: a starter). A player traded during a season counts for
his latest club (MLB) or the club where he had more plate appearances or batters faced (NPB). Rates: WAR per 600 PA, per 700
BF.

### 25.2 Projection (`fit_projection`, `project`, `marcel_time`)

Rate(next) = (sum of w_i WAR_i + k x m(nw) / unit) / (sum of w_i n_i + k) x unit, weights 5/4/3 for hitters and 3/2/1 for
pitchers, nw = sum of w_i n_i, and the regression target m(nw) = league rate x nw / (nw + h): a player with little playing
time is pulled toward replacement level rather than toward the average regular (h = 0 is plain Marcel). Plus an age adjustment
c1 (age - 28) + c2 (age - 28)^2 fitted on consecutive seasons' rate changes (players with 150+ in both, weighted by the harmonic
mean). k from {300, 600, 1000, 1500, 2500, 4000, 6000} and h from {0, 500, 2000, 6000} are chosen on target seasons before the
one projected. Next season's WAR = the rate x (0.5 n(S) + 0.1 n(S-1) + 200 PA or 60 BF, scaled to the schedule). Triple-A and
NPB use MLB's aging curve (NPB's pages carry no birth dates; the current rosters do, so only current players are aged).

Validation (walk-forward, players with 200+ PA or 150+ BF in the target season, RMSE of the projected rate against the
season's actual rate, weighted by the target season's sample):

| | Targets | Projection | Last season's rate | League rate | k chosen |
|---|---|---|---|---|---|
| MLB hitters (WAR / 600 PA) | 2018-2026 | **1.42** | 1.79 | 1.73 | 1,500 |
| MLB pitchers (WAR / 700 BF) | 2018-2026 | **2.31** | 3.84 | 2.43 | 2,500 |
| Triple-A hitters | 2026 | **1.20** | 1.68 | 1.26 | 4,000 |
| Triple-A pitchers | 2026 | 2.51 | 4.81 | **2.45** | 2,500 |
| NPB hitters | 2008-2026 | **1.67** | 2.50 | 2.08 | 2,500 |
| NPB pitchers | 2008-2026 | **1.52** | 2.41 | 1.74 | 1,000 |

The playing-time scaling h came out 0 in every fit: in Bullpen WAR and WAR-lite, players with little history who play the
next season perform about at the league rate (Bullpen WAR's batting is already regressed xwOBA+), so the regression target is
the plain league rate and playing time is handled by the depth chart's availability caps (25.4). The MLB aging curve: c1 =
-0.065 and c2 = 0.0024 WAR per 600 PA per year (hitters), -0.052 and -0.0016 per 700 BF (pitchers).

### 25.3 Strengths and needs (`team_needs`)

Each club's WAR at each position against the level's other clubs: percentile and grade (A at the 80th percentile or above,
B 60, C 40, D 20, else F); the three best and three worst. For each weakness, the candidates are players on other clubs with
100+ PA (80+ BF) who played the position (15+ games or 20% of theirs; any hitter at DH), ranked by projected wins over a full
season there minus the incumbent's (the player with the most games there; for the rotation and the bullpen one slot, a
fifth of a club's starters' batters faced or a seventh of its relievers', against the club's fifth starter or seventh
reliever). A hitter's value at a new position swaps his positional adjustment for the new one's. Hints only from the data:
his club missed the postseason (or its postseason odds are under 5% in season), or it has another player at the position
projected at three quarters as much or more. Salaries, contracts and availability: not considered (no legitimate free
source exists; free agents are not identified by our data). NPB's Central League played without the DH in 2026: its clubs'
DH is not graded, and since the league adopts the DH in 2027 it is listed as a need.

### 25.4 The trade simulator (`allocate`, `trade_delta`, `mlb_curves`, `npb_curves`, `interp`)

The depth chart: positions in the order C, SS, CF, 2B, 3B, RF, LF, 1B, DH, SP, RP; each filled by the best available eligible
player by projected full-season value there, up to 80% of the time at catcher and 95% elsewhere, a hitter's time used once
across positions; a starter up to a fifth of the starts, a reliever a seventh of the relief work; every cap scaled by how much
of a season the player can be expected to play (Marcel's playing time against three quarters of a full role, between 25% and
100%, so a call-up with a good small sample never takes over a position); the rest at replacement level (zero wins). The trade's change in wins = after - before, both by the same rule (a trade of nothing changes nothing; tested).
The odds: for each club the season simulation (MLB `season_sim.regular_season`, NPB `npb/build.simulate`) is re-run with that
club's rating moved by shifts worth about -9, -5, -2, 0, +2, +5, +9 wins (common random numbers, the other clubs fixed),
recording expected wins and the postseason, division (NPB: pennant, with the Climax Series as "postseason") and title
probabilities; the page interpolates linearly in expected wins. Horizon: the rest of the regular season while one is under way
(30+ games left for MLB, 12+ for NPB), otherwise next season, this season's schedule replayed with the ratings carried forward:
MLB's by the fitted carry of the simulation's end-of-season ratings (slope of r(S+1) on r(S)) with the residual spread of talent
as each club's uncertainty, NPB's by the game model's own carry (0.9). The change in expected wins over the horizon is the
depth-chart change times the horizon's share of a season.

As built on 15 October 2026 (both levels between seasons, so the horizon is next season): MLB 30 clubs x 6 shifts + the base
at 1,000 simulated seasons each, about 3.5 minutes, each club's curve spanning 17.1-17.8 expected wins; NPB 12 clubs at 2,000
each, about 10-20 seconds, spans of 14.6-15.3 wins. The fitted MLB carry of end-of-season ratings is applied with the residual
spread of talent. A full season at a position: 681 PA in an MLB lineup slot (575 in NPB), 3,742 BF for an MLB rotation and 2,386
for a bullpen (3,064 and 2,261 in NPB).

### 25.5 Known limitations

- Value is this season's WAR (and its projection); in-season injuries, platoons and roles are not modelled in the depth chart.
- A trade between two clubs that play each other also moves each other's odds through their games; the curves hold the
  other clubs fixed.
- NPB WAR-lite has no fielding, so NPB's position grades and candidates rest on batting, base stealing and the positional
  adjustment.
- Salaries, contracts, options and roster limits are not checked.


## 26. Valuation v2: `analytics/valuation.py`

Added 16 October 2026 (docs/VALUE_SECTIONS.md section 4). The currency stays Bullpen WAR; nothing re-estimates a season's WAR.

**Season by season.** Next season's rate is section 25.2's Marcel projection; season t (1-5) ages it by the MLB aging curve
and multiplies by Marcel's playing time (the "naive" path). Each horizon is calibrated on history (`horizon_fit`): the slope,
through the origin, of actual WAR in season B+t on the naive projection made after B (players with 50+ PA or BF in B; a
player who did not play counts 0; 2020 is neither a base nor a target), by kind and age band (<26, 26-29, 30-32, 33+).
Fitted on 2015-2026 (16 October 2026): hitters 26-29 slopes 0.85, 0.71, 0.66, 0.62, 0.57 for t = 1..5; 33+ 0.65, 0.49, 0.37,
0.18, 0.05; pitchers' first-year slopes are above 1 (1.16-1.38: Marcel's 60-BF base under-states a pitcher's next workload).
**Value** = sum of 0.92^(t-1) E[WAR_t] over five seasons: the surplus over a freely available player (WAR is already above
replacement); salaries are not known, so it is not net of pay.

**Uncertainty** (`band_fit`): the 10th and 90th percentiles of actual minus expected WAR by bin of the expectation (<0.5,
0.5-1.5, 1.5-3, 3-5, 5+), for next season and for three seasons together. Out of sample (each base's quantiles from earlier
bases), the 80% band held 79.9% of hitters and 79.8% of pitchers next season (3,161 and 3,806 player-seasons), 78.7% and
78.9% over three seasons.

**Availability** (`il_fit`): injured-list days per season from the transactions (section 27): next season's days on last
season's, the season before's and age (least squares), and the chance of 30+ days (logistic), walk-forward from 2016.
Mean absolute error 33.6 days against 36.5 for the league mean (hitters, 3,695 player-seasons), 46.3 against 50.5
(pitchers, 4,426); Brier 0.188 against 0.200 and 0.217 against 0.227. Scaling Marcel's playing time by the expected days
made next season's PA and BF worse (RMSE 189 against 179 hitters, 187 against 183 pitchers), so availability is shown as
risk and does not enter the projection (`il_in_playing_time` false in the payload).

**Scarcity** (`scarcity`): at each position the projected full-season value (value.value_ft) of the 15th-best regular whose
primary position it is (the 75th and 105th for rotation and bullpen slots); a player's "wins over the median starter" there.
Lines for 2027: C 3.8, CF 3.7, SS 3.4, RF 2.8, 3B 2.6, 2B 2.6, LF 2.6, 1B 2.0, DH 1.4 full-season wins; starters 2.3 a
rotation slot, relievers 0.8 a bullpen slot.

**Prospects** (`prospect_rows`, `prospect_fit`): a minor leaguer's expected MLB WAR over the four seasons after a
minor-league season (discounted; 0 if he never reaches the majors) from the Stats API stat lines of Triple-A, Double-A,
High-A and Single-A (2015 on): his highest level with 100+ PA or BF, his age against the level's mean, his performance
against the level's (OPS for hitters, (K - BB) / BF for pitchers, a z-score shrunk by n / (n + 150)) and the sample. A
log-link regression (Poisson pseudo-likelihood on the positive part, rescaled to the outcome's mean) on the 2015-2022 cohorts
(16,469 hitter and 16,593 pitcher seasons). Fitted to 2019 and scored on 2021-22: hitters rank correlation 0.22 against 0.08
for each level's mean, mean absolute error 0.39 against 0.46; pitchers 0.09 against 0.05, 0.24 against 0.27; the top 5% by
the model went on to 2.1 WAR (hitters) and 1.1 (pitchers) against means of 0.28 and 0.12, while the model expected 1.2 and
0.55: it ranks prospects but under-rates the very best (stat lines only, no scouting grades). A linear fit was tried first
(MAE 0.43 and 0.27, top 1% expected 1.2 against an actual 3.4) and a Statcast Triple-A WAR model on the 2023-25 cohorts
(rank correlation 0.27 hitters, 0.18 pitchers, no gain in error on the 2025 cohort); the log-link model on every level
replaced both.

### 26.1 Known limitations
- No contracts or salaries (no legitimate free source); value is not surplus over pay.
- The horizon calibration is pooled by age band; a player's own durability enters only through his playing time.
- Prospects are valued from stat lines alone.

## 27. Transactions and trade ratings: `analytics/moves.py`, `analytics/trade_ratings.py`, `analytics/moves_build.py`

**Transactions** (MLB Stats API `/transactions`, sportId 1, month by month from October 2014: 176,305 records, 2,530 trades
on 16 October 2026). The type code gives the kind; the description is parsed for the injured list's length (10/15/60; the
"disabled list" before 2019), the retroactive date, the body part (a keyword category), minor-league contracts, and a trade's
extras (cash, players to be named later, bonus pool money, picks, future considerations: what precedes " for " goes to the
club the subject traded to, what follows to the subject). A trade's pieces share an id; three-club deals recorded as one-way
trades of a date with neighbouring ids are merged when every club both sends and receives (4 such deals since 2014).
Injured-list stints: a placement opens one (on its retroactive date), a transfer continues it, an activation, release,
outright, election of free agency or trade closes it, an open stint runs to the end of the regular season; a second
placement within three days of the first is the same stint.

**Value at the time** (`value_at`), for the receiving club, from data before the date only. A major leaguer: section 25.2's
Marcel rate from the seasons before, with the season to date folded in as one more season (its WAR from his wOBA, or wOBA
allowed, before the date: `valuation.proxy_fit`, WAR rate = a + b x wRAA rate fitted on earlier full seasons); the rest of
the season = that rate x his playing-time pace over the club's games left; later seasons = section 26's calibrated path; each
later season x the chance he is still with the club, discounted 8% a year; five seasons in all. A minor leaguer: section
26's prospect model on his latest complete minor-league season before the date (S-1, else S-2). Anyone else: the base rate
of traded players of his age band with no MLB record (2015-22 trades: 0.14 WAR over four seasons at 20 or younger, 0.22 at
21-22, 0.32 at 23-24, 0.25 at 25-26, 0.06 at 27+).

**Retention** (`retention_fit`), standing in for contracts and club control: of traded players who played in the majors in a
later season, the share who did so mainly (half their PA/BF or more) for the acquiring club, by seasons since the MLB debut
(0-2, 3-5, 6+) and in-season or off-season trade, for the next five seasons. 2015-2025 trades: in-season, 6+ years 41%, 34%,
36%, 38%, 31%; 3-5 years 56%, 31%, 14%, 13%, 11%; 0-2 years 67%, 54%, 47%, 29%, 25%. Off-season: 90-91% in the first season
for every group, then 74%, 57%, 50%, 41% (0-2), 57%, 39%, 28%, 15% (3-5), 48%, 41%, 37%, 34% (6+).

**Realised** (`realised`): WAR produced for the club since the trade: the season's WAR split by PA (BF) with the club after
the date, moved by (his wOBA there - his season's wOBA) x the wOBA denominator / 1.24 runs, over 10 runs per win (the parts
of a season add up to it; `valuation.war_part`), plus each later season's WAR with the club. The PA table gives each plate
appearance's batting and fielding club.

**Grades**: net expected value (in - out): A +2 wins or more, B +0.75, C within 0.75, D -0.75, F -2 or worse; the winner has
a net of 0.75 or more; the same for the realised net to date.

**Validation** (`validate`, trades of 2016-2024): the expectation over the rest of the trade's season and the next one
(retention-weighted) against the WAR realised for the club over the same span; the naive forecast is the player's last
season's WAR rate over the same playing time with the same calibration. Players with an MLB projection (1,659): r 0.48
against 0.37, rank r 0.35 against 0.31, MAE 0.73 against 0.87, slope of realised on expected 0.89 (mean expected 0.65,
realised 0.50: the expectation runs high by about a quarter). Each trade's net for its first club (1,825): r 0.37 against
0.29, MAE 0.64 against 0.76.

### 27.1 Known limitations
- Cash, players to be named later, bonus pool money and picks are not valued; a player to be named is a separate trade when
  he is named.
- Retention is a group rate, not the player's contract.
- The in-season proxy uses wOBA only (no fielding or baserunning to date).

## 28. The fantasy layer: `analytics/fantasy.py`, `analytics/fantasy_build.py`

Added 16 October 2026 (docs/VALUE_SECTIONS.md section 5). MLB only.

**Lines.** Rates from section 16's component projections (next season aged; rest of season with the season to date). Around
them, fits on the official season lines (MLB Stats API) of earlier seasons only (`fits_for`):
- hitters: AB = PA x (1 - BB - HBP - sacrifices); R / PA and RBI / PA by least squares on the on-base, isolated-power,
  home-run, single and steal rates, the club's runs per game against the league's and the lineup slot (from the stores'
  lineups); SB = times on first x attempts per time on first x success, each a 5/4/3-weighted rate relative to its season's
  league rate, regressed (k = 60 times on first, 15 attempts) to a prior from sprint speed (exp(0.42 (speed - 27))), times the
  latest league rate; PA next season = least squares on the last two seasons' PA and age (players with 50+ PA; a player who
  does not play counts 0).
- pitchers: outs = BF x (1 - (H + BB + HBP) / BF - e); runs by BaseRuns from the event rates, scaled to the league's runs,
  ER = R x the league's ER / R; W and L per start on outs per start, the club's winning percentage and the ERA against the
  league; relievers per relief game; SV and HLD = the club's projected saves (holds) x his share, carried with the fitted
  persistence (0.67 of a closer's share, 0.58 of a set-up man's carry into the next season; 0.6 of that after a change of
  club); BF next season on the last two seasons' BF, the share of starts and age; starts from his share of batters faced as
  a starter.
- next week (`week_project`): the club's games x the share he started in the last 21 days x PA per start by lineup slot
  (4.75 - 0.105 (slot - 1)); each game against the opposing probable starter's hand (65% platoon rates) and the park's run
  and home-run factors (the season before's parks.json); starters' starts from the probable pitchers.

**Values.** 5x5 (R, HR, RBI, SB, AVG; W, SV, K, ERA, WHIP) for a 12-team mixed league (C, 1B, 2B, 3B, SS, CI, MI, 5 OF, UT;
9 P): z-scores over the draftable pool (168 hitters, 108 pitchers, by iteration), ratio categories as volume-weighted
contributions; minus the replacement level of the best position (slots filled scarcest first); $260 budgets (67% to
hitters). Points: our editable default (hitters R 1, RBI 1, 1B 1, 2B 2, 3B 3, HR 4, BB 1, HBP 1, SB 2, CS -1, K -1; pitchers
an out 1, K 1, H -1, BB -1, HBP -1, ER -2, W 5, L -3, SV 5, HLD 3). Tiers: an optimal 1-D k-means (6 tiers) of the top 60 at
each position. Dynasty: this season's value above replacement x the player's valuation-v2 multiplier (five seasons'
discounted expected WAR over next season's), prospects at the slope of value on expected WAR. Positions: 15 games or 20% of
games at a position last season (value.eligible). Clubs: the transactions of the season and since.

**Backtests** (`backtests`, cached per season; 16 October 2026):

| Season (draft), 2018-2026 without 2020; players who qualified the season before | Ours | Last season |
|---|---|---|
| Hitters (2,239 player-seasons): R / HR / RBI / SB MAE | 19.3 / 6.5 / 19.6 / 4.0 | 21.9 / 7.6 / 22.5 / 4.6 |
| AVG MAE (by AB) | .0205 | .0260 |
| points MAE; rank r of points; rank r of 5x5 value | 87.6; 0.64; 0.63 | 98.9; 0.60; 0.58 |
| Pitchers (2,772): W / SV / K MAE | 2.9 / 2.4 / 36.6 | 3.5 / 2.4 / 40.6 |
| ERA / WHIP MAE (by IP) | 0.87 / 0.145 | 1.14 / 0.185 |
| points MAE; rank r of points; rank r of 5x5 value | 98.4; 0.48; 0.43 | 113.2; 0.46; 0.35 |

Rest of season (from 1 June, 1 July, 1 August, 2022-26) against the season-to-date pace: hitters' points MAE 39.8 against
42.5 (R 8.5 v 9.2, HR 3.2 v 3.5, RBI 8.8 v 9.8, SB 2.5 v 2.4), rank r 0.587 v 0.582; pitchers' 44.4 against 48.9 (W 1.5 v
1.9, SV 1.0 v 1.0, K 14.1 v 14.7), 0.453 v 0.449. Next week (2022-26; 34,566 hitter-weeks, 42,395 pitcher-weeks) against
the season-to-date rate: hitters MAE 6.19 against 6.36, rank r 0.444 against 0.387; pitchers 7.56 against 8.30, 0.353 against
0.323. Matchups (platoon and park) add little: 6.19 against 6.20 without, 0.444 against 0.441. Two-start pitchers scored
19.7 points a week, one-start pitchers 9.2.

**Luck** (`luck_check`): the next season's change against this season's gap between results and expected results. The page's
buy-low and sell-high flags (xwOBA - wOBA of .025 or more; RA9 - xRA9 of 0.6 or more) rest on it; its slope and correlation
are in the backtest payload: 57% of a hitter's wOBA - xwOBA gap closes the next season (slope -0.57, r -0.32,
1,819 player-seasons with 300+ PA both), 53% of a pitcher's RA9 - xRA9 gap (slope -0.53, r -0.29, 740 with 100+ IP).

### 28.1 Known limitations
- No ADP, ownership or platform data (their terms do not allow our use): "rises" and "falls" are against last season, and
  streaming starters are those outside our top 150.
- Playing time regresses hard toward the mean (it minimises error with injuries counted), so regulars' counting stats run
  conservative; ranks are what the backtest scores best.
- Closer roles between seasons come from last season's shares and the moves since; spring roles are not known.
