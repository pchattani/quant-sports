# Models: technical reference (NFL)

Every model behind The Quant Gridiron, read from `oddsmarkets/nfl/models/` and the
committed fits in `oddsmarkets/nfl/models/fitted/`. Data and identity are in
[DATA_PIPELINE.md](DATA_PIPELINE.md); how the results reach the pages is in
[DASHBOARD.md](DASHBOARD.md). Section 17 lists where the code, the site's Methodology
(`docs/gridiron/assets/js/docs.js`) and the contracts disagreed, and how each was resolved on
1 October 2026.

Contents

1. Overview
2. Expected points: `ep.py`
3. Win probability: `wp.py`
4. Fourth downs and two-point tries: `fourth_down.py`
5. Completion probability, CPOE and expected YAC: `completion.py`, `yac.py`
6. Rushing yards over expected: `ryoe.py`
7. Kicking and punting: `kicking.py`
8. Pressure, player value, the QB composite and value above replacement: `pressure.py`, `player_value.py`, `qb.py`,
   `analytics/value.py`
9. Stabilisation: `stabilise.py`
10. Team strength: `team_strength.py`
11. The game model and the drive simulation: `game.py`, `drive_sim.py`
12. Live win probability: `live.py`
13. Season and playoff simulation: `season_sim.py`, `tiebreak.py` (13.1 the trade simulator's sensitivity curves)
14. Awards and markets: `awards.py`, `sources/markets.py`
15. Backtest and validation: `backtest.py` and the EP/WP validations
16. Known limitations
17. Where the code and other texts disagree
18. Valuation v2, transactions and trade ratings, fantasy
19. Pro Football Reference data removed (16 October 2026)

---

## 1. Overview

### 1.1 How the models feed each other

```
 play-by-play (one season at a time, _io.plays) ──► ep.py ──► EPA (ours) ─────────────────────────────┐
        │                                     └──► wp.py ──► WP (ours) ──► fourth_down.py (go/punt/FG WP, grades)
        │                                                        ▲         kicking.py (FG p, punts) ──┘
        ├──► completion.py (cp, CPOE, CROE)   yac.py (xYAC, YACOE)   ryoe.py (RYOE)
        ├──► pressure.py, player_value.py (raw / adjusted / RAPM), stabilise.py ──► qb.py (composite)
        │
        └──► _cdata.unit_rows (game × offence × passer) ──► team_strength.py (weekly ridge, priors, QB term)
                                                                │ net ratings, unit edges
                                                                ▼
                    game.py: μ margin, μ total, discrete margin with key numbers ──► drive_sim.py (shape, team totals)
                         │                         │                                    │
                    live.py (WP from ESPN state)   season_sim.py (20,000 runs, tiebreakers, playoffs, draft)
                                                   awards.py ──► markets comparison ◄── sources/markets.py
                         │
                    backtest.py (walk-forward 2006 →, season checkpoints) ──► calibration.json
```

### 1.2 Model inventory

| Model | File | Fitted where | Used for |
|---|---|---|---|
| Expected points | `ep.py` (`ep-1`) | `fitted/ep.json` + `ep_main.txt.gz`; cross-fitted by season | EPA on every page, value, team units |
| Win probability | `wp.py` (`wp-3`) | `fitted/wp.json` + `wp_main.txt.gz` | game pages, fourth downs, live WP |
| Fourth downs | `fourth_down.py` (`4th-2`) | `fitted/fourth_down.json` + conversion and go boosters | grades, coaches, two-point calls |
| Completion | `completion.py` (`cp-3`) | `fitted/completion.json` + four tier boosters | CPOE, CROE |
| Expected YAC | `yac.py` (`xyac-1`) | `fitted/yac.json` + four tier boosters | YACOE |
| RYOE | `ryoe.py` (`ryoe-1`) | `fitted/ryoe.json` + four tier boosters | RYOE |
| Kicking | `kicking.py` (`kick-3`) | `fitted/kicking.json` | FG make probability, FGOE, punts, fourth downs |
| Pressure | `pressure.py` (`press-1`) | – (per season) | sack and pressure rates, SROE |
| Player value | `player_value.py` (`pv-2`) | – (per season) | Gridiron Value |
| QB composite | `qb.py` (`qb-1`) | `fitted/qb.json` | the composite and its forecast |
| Stabilisation | `stabilise.py` (`nflstab-1`) | `fitted/stabilise.json` | shrinkage constants, glossary |
| Team strength | `team_strength.py` | `fitted/team_strength_params.json` | ratings, the game model, the season simulation |
| Market ratings | `market_ratings.py` | – (refitted every week from earlier closing lines) | the game model's `mr` / `mrt` terms |
| Game model | `game.py` | `fitted/game_params.json` | every game price |
| Drive simulation | `drive_sim.py` | `fitted/drive_model.json` | score shape, team totals, cover / over |
| Live WP | `live.py` | – (B's WP fit) | live cards and game pages |
| Season simulation | `season_sim.py` | `fitted/season_sim_params.json` | season.json, playoffs, draft order |
| Sensitivity curves | `season_sim.sensitivity` | – (per build, cached on the simulation's inputs) | trade.json, needs/<abbr>.json |
| Value above replacement | `analytics/value.py` | – (per season) | value.json, needs/<abbr>.json, trade.json |
| Awards | `awards.py` | `fitted/awards_fit.json` | award races |
| Backtest | `backtest.py` | – | `calibration.json` |

Every model exposes a cached `for_season(season)`; the build calls it through
`analytics/adapters.py`, which isolates failures. Fits are versioned: a cached fit whose
version or input key no longer matches is ignored, and the committed fit stands in when
the cache is cold (CI).

---

## 2. Expected points: `ep.py`

For every scrimmage snap (downs 1–4; play types pass, run, punt, field goal, no play,
kneel, spike) the label is the **next score in the same half** (overtime is its own half),
from the offence's point of view, in seven classes:

```
TD +7   FG +3   safety +2   no score 0   opp safety −2   opp FG −3   opp TD −7
EP = Σ_c p_c · v_c
```

(a touchdown is valued at 7: the try is a separate play). The scoring team is `td_team` on
a touchdown, the kicking side on a made field goal and the defence on a safety.

**Model**: LightGBM multiclass (learning rate 0.1, 63 leaves, at least 400 plays a leaf,
L2 5.0, up to 600 rounds) on down, distance, goal to go, yard line, seconds left in the
half, the half, score differential, both teams' timeouts, home, roof and era (season).
**Cross-fitted by season**: seasons are dealt round-robin into 5 folds; every play is
predicted by a model that never saw its season, with early stopping on a 10% game holdout
of the training seasons. The production model is refitted on every completed season at
the folds' mean best iteration (59 in the committed fit, on 1,078,934 plays 1999–2025) and
applied to the current season. Importance: seconds left in the half 0.43, yard line 0.26,
score differential 0.11.

**EPA** (`epa_ours`): EP after the play (the next scrimmage play's EP, sign-flipped on a
change of possession; the points on a scoring play; 0 at the end of a half) minus EP before.

**Validation** against nflfastR's published class probabilities (`td_prob` ...) and `ep`
on the same plays (committed `calibration.json`, `ep.validation`):

| Plays | Ours: log-loss | nflfastR: log-loss | Ours: EP calibration (weighted MAE) | nflfastR |
|---|---|---|---|---|
| all, 1999–2025 (1,078,932) | **1.2517** | 1.2898 | 0.016 | 0.062 |
| 1999–2019 (nflfastR in sample) | 1.2604 | 1.2948 | 0.017 | 0.082 |
| 2020–2025 | 1.2225 | 1.2730 | 0.024 | 0.022 |

Ours has the lower next-score log-loss in **every season from 1999 to 2025** (by 0.013 in
1999 to 0.059 in 2025); the correlation of the two EPs is 0.966. nflfastR over-predicts
field goals (0.267 against an observed 0.258) and under-predicts the opponent's scores.
nflfastR's model was fitted on 1999–2019, so its numbers there are in sample, which
flatters it.

---

## 3. Win probability: `wp.py`

Label: the team in possession won (ties left out of fitting and scoring). Features per
play: score differential, seconds left in the game and the half, the half (overtime the
third), down, distance, yard line, both teams' timeouts, home, the pre-game spread from the
offence's side (`pos_spread`), era, and three derived terms with e = elapsed share of
regulation and u = 1 − e:

```
spread_time = spread · exp(−4e)        diff_time = score_diff · exp(4e)
bm_z = (score_diff + spread · u) / (13.5 · √(u + 0.005))           BM_SIGMA = 13.5 points
```

`bm_z` (added in `wp-2`) is the Brownian-motion view of a game and carries the spread's
information in the scale the trees need; it is by far the most important feature (0.89)
and cut the gap to nflfastR's `vegas_wp` in the first quarter. LightGBM binary (learning
rate 0.08, 63 leaves, 300 a leaf, L2 5.0, up to 800 rounds; 81 in the committed fit),
**monotone** increasing in score differential, the spread terms, `bm_z` and the offence's
timeouts, decreasing in yard line and the defence's timeouts; cross-fitted by season like
EP.

**Not a feature since `wp-3`: the second-half kickoff.** In the data it carries selection,
not only the extra possession (in a tied first half, the side that kicked off to open the
game has the ball only after a stop, and won 60% of such pick'em games 2010–2025 against
48%), so the model learnt about 3.7 WP points from it, up to 8 in counterfactual fourth-down
states, which inflated the value of keeping the ball. Dropping it cost little log-loss. It
is still computed (`receive_2h_ko`) for the payloads.

`state_wp(fit, states)` is the vectorised WP of counterfactual states the fourth-down model
and live WP use.

**Validation** (committed `calibration.json`, `wp.validation`, 1,076,150 plays):

| Plays | Ours | nflfastR `wp` (no spread) | nflfastR `vegas_wp` (spread) |
|---|---|---|---|
| all: log-loss / Brier | 0.4515 / 0.1500 | 0.4814 / 0.1622 | **0.4471** / 0.1485 |
| 1999–2019 | 0.4501 | 0.4789 | 0.4454 |
| 2020–2025 | 0.4560 | 0.4899 | 0.4527 |
| quarter 1 / 2 / 3 / 4 / OT | 0.586 / 0.514 / 0.422 / 0.298 / 0.587 | 0.644 / 0.552 / 0.444 / 0.303 / 0.612 | 0.580 / 0.509 / 0.418 / 0.294 / 0.612 |

Ours beats the plain `wp` clearly and in every season, and **slightly trails `vegas_wp`**
(by 0.004 overall; ours is ahead in overtime and in four seasons: 2000–2002 and 2022). Its
calibration error (ECE 0.0019) is below both of nflfastR's (0.0034).

---

## 4. Fourth downs and two-point tries: `fourth_down.py`

For a fourth down at yard line y, distance t, score s and time left, each option's WP is
computed with `wp.state_wp`, from the side with the ball (score, home, spread, timeouts and
the second-half kickoff swap when the opponent has it):

- **Go**: P(convert) from the conversion model; the yards gained come from the empirical
  distribution of third- and fourth-down gains in the same distance bucket (1, 2, 3–4,
  5–7, 8–10, 11–15, 16+; five quantile points 0.1–0.9 for a conversion, the yards beyond
  the line to gain, and five for a failure). A conversion is a first down at y − g (a
  touchdown when g ≥ y: + 6 + P(PAT), opponent receives); a failure gives the opponent the
  ball at 100 − (y − g).
- **Field goal** (distance y + 17, offered up to 66 yards): P(make) from `kicking.py` for
  this kicker, era, weather, roof and altitude; a make is + 3 and the opponent receives; a
  miss gives the ball at the spot of the kick (y + 7, at least the 20).
- **Punt**: the receiving team's spot from the punt model (five quantile points) and the
  return-touchdown rate.

Clock: 6 s for a go, 8 s for a punt, 5 s for a field goal. Kickoffs land at the season's
median drive start after a kickoff, as yards to go (`ko_yl` in the committed fit: 72–76
to 2010, 80 in 2011–2015, 75 in 2016–2023, 70 in 2024, 69 in 2025; for a season without a
fitted value the default is 75 before 2024, 70 in 2024 and 65 from 2025).

**Conversion model**: LightGBM binary on every third- and fourth-down run or pass
(converted = reached the line to gain or scored, without a turnover; 206,068 plays) on
distance, yard line, goal to go, fourth down, era, roof and the two teams' strength: the
offence's and the opponent defence's pre-game EPA per play (each game's EPA decayed 0.97
per game, carried across seasons at 0.4, shrunk with 300 pseudo-plays); monotone in
distance and both strengths; learning rate 0.05, 15 leaves, 300 a leaf, L2 10; 123 rounds
in the committed fit. Calibration on actual fourth-down attempts (15,514): log-loss 0.640
against 0.693 for the base rate, ECE 0.012; by distance it is within 2 points except 11+
yards (predicted 0.160, observed 0.206).

**Recommendation and grades**: the recommended option is the highest WP; WP lost =
WP(best) − WP(chosen) (0 when the choice was the recommendation); the module's own coach
tables (not published) count a "should go" when going beats the alternative by more than 1
point (`RECOMMEND_MARGIN` 0.01). The payload grades A ≤ 0.5 pp, B ≤ 1.5, C ≤ 3, D ≤ 6, F
beyond (`analytics/games.grade`); the pages turn the letter into a label (A and B a right
call, C a close call, D and F a mistake; `GI.gradeOf`) and, only when no letter is present,
apply the same cut-offs to WP lost (≤ 1.5 / ≤ 3 / above 3 points; section 17, item 10). Overtime fourth downs are
listed but not graded (the WP model has few overtime states and does not know the overtime
rules).

**Two-point tries**: WP(kick) = P(PAT)·WP(+1) + (1 − P(PAT))·WP(+0) and WP(go) =
P(2pt)·WP(+2) + (1 − P(2pt))·WP(+0), each with the opponent receiving; P(PAT) is the
season's league rate (fitted per season, 0.93–0.96 since the 2015 rule change; 0.94 from
2015 and 0.99 before by default), P(2pt)
the pooled league rate shrunk to 0.48 (0.474 on 2,503 attempts). A difference under 0.5 WP
points (`TRY_MARGIN`) is a toss-up: no recommendation, no WP lost.

**Aggressiveness**: `fourth_down.py` also fits a LightGBM model of the go decision (yard
line, distance, score, time, era; `fourth_down_go.txt.gz`). The coaches page's **GOE** is
computed in `analytics/fourth.py` from a separate per-season logistic regression of going
for it on log distance, yard line and its square, score difference, game seconds, win
probability and trailing in the fourth quarter (go rate minus the expected rate, per 100
fourth downs); coach rates leave out the last two minutes of each half and win
probabilities below 5% or above 95%.

---

## 5. Completion probability, CPOE and expected YAC: `completion.py`, `yac.py`

### 5.1 Completion probability

Rows: every targeted pass (a receiver, air yards known; not a sack, spike or try); label:
completed. Air yards exist from 2006 but in 2006–2008 only on completions (99.8% of
"aimed" passes complete), so **cp starts in 2009** (`CP_FIRST`). LightGBM binary (learning
rate 0.06, 31 leaves, 300 a leaf, L2 5, monotone decreasing in air yards) in four feature
tiers, each fitted on the seasons its data covers and cross-fitted by season; every pass is
scored by the richest tier its season has:

| Tier | Seasons | Features |
|---|---|---|
| base | 2009→ | air yards, yard line, room (yard line − air yards), distance, down, goal to go, seconds left in the half, score, pass location, QB hit, shotgun, no huddle, roof, wind, era |
| participation | 2016–2025 | + pressure, time to throw, pass rushers, box, coverage shell, man/zone |
| FTN | 2022→ | + blitzers, pass rushers, box, out of pocket, play action, screen |
| FTN + participation | 2022–2025 | both |

Pressure, blitz and coverage are inputs, so CPOE credits a QB for completing under pressure
(sack and pressure rates are measured separately in `pressure.py`). Each season's
predictions are **recentred** by one logit shift so the league's mean cp equals its
completion rate (shifts −0.098 to +0.073), so CPOE is measured against that season's
league; for the season in progress the shift uses the passes so far. Drops (FTN) are not
inputs; `cpoe_drop_adj` removes dropped passes from both sides. Receivers get catch rate
over expected (CROE).

Validation (308,842 passes 2009–2025): log-loss 0.5763 against nflverse's `cp` 0.5814
(nflfastR's cp was trained on earlier seasons, so in sample there); QB-season CPOE
correlates 0.975 with nflverse's (590 QB-seasons) and 0.817 with NGS's completion
percentage above expectation (344; nflverse's 0.813).

### 5.2 Expected YAC

Rows: completions with YAC recorded; target YAC clipped to [−10, room]. LightGBM regression
(the conditional mean; same settings) in tiers like completion: base (1999→: air yards,
room, yard line, distance, down, past the sticks, location, time, score, shotgun, QB hit,
roof, era), participation (+ box, rushers, coverage, man/zone), FTN (+ screen, play action,
motion, contested), both. YACOE = YAC − xYAC. Validation (222,014 completions): RMSE 6.509
against nflverse's `xyac_mean_yardage` 6.526, MAE 4.11 against 4.16; receiver-season YACOE
correlates 0.978 with nflverse's and 0.730 with NGS's YAC above expectation (921; nflverse
0.717).

---

## 6. Rushing yards over expected: `ryoe.py`

Rows: designed runs (play type run, not a scramble, kneel or try); target rushing yards
clipped to [−15, yard line]. LightGBM regression in tiers: base (1999→: yard line,
distance, down, goal to go, time, score, run location and gap, shotgun, no huddle, roof,
era), participation (+ box, RB/TE/WR counts, formation), FTN (+ box, backfield, motion, RPO,
sneak), both; monotone decreasing in box count. Team and defence quality are deliberately
not inputs, so RYOE credits the runner and his blocking together; NGS's tracking-based
RYOE also sees the defenders. Validation (363,288 runs): RMSE 6.160 against 6.265 for the
mean; rusher-season RYOE per carry correlates 0.838 with NGS's (471 rusher-seasons; yards
per carry 0.819).

---

## 7. Kicking and punting: `kicking.py`

**Field goals**: every attempt from 15 to 75 yards (a block is a miss); logistic regression
(Newton, ridge 0.001) with x = (distance − 40)/10:

```
logit p = β · [1, x, (x+1)+, x+, (x−1)+, era, era·x, wind10·outdoors, wind10·x·outdoors,
               cold·outdoors, indoor, altitude ≥ 3,000 ft, altitude·x]
era = (season − 2010)/10,  wind10 = wind/10 mph,  cold = max(0, 50 − temp)/10
```

(a piecewise-linear logit with knots at 30, 40 and 50 yards, so it extrapolates linearly).
Each kicker's skill is a random effect b_k ~ N(0, τ²), the posterior mode given the fixed
part, with τ² by the method of moments over kickers with 20+ attempts (τ = 0.172 in the
committed fit on 27,759 attempts, 202 kickers; log-loss 0.392). FG over expected = makes −
Σp (p for a league kicker in the same conditions); points over expected = 3·FGOE + extra
points over the season's league PAT rate.

**Punts**: the receiving team's spot as its yards to go (100 − yard line + distance −
return; 80, its own 20, on a touchback), as empirical quantiles 0.1–0.9 per yard line of
the punt from punts within ±2 yards (widened until 60 punts), and the return-TD rate
(TDs + 0.5)/(punts + 100). Punter value = expected spot − actual spot.

---

## 8. Pressure, player value and the QB composite

### 8.1 Pressure: `pressure.py`

Per dropback: sacks and QB hits (all seasons), pressure (participation, 2016–2025), out of
pocket and blitz (FTN, 2022→), pass rushers, time to throw. Expected sack rate = the
league rate in the same down × distance bucket (0–3, 3–6, 6–10, 10+) × field zone cell
that season; SROE = actual − expected. Individuals: sacks (half sacks 0.5), hits, and with
participation the dropbacks a defender was on the field for. FTN's `is_qb_fault_sack` gives
the share of sacks charted as the QB's fault.

### 8.2 Gridiron Value: `player_value.py`

1. **Raw credit** (conventional, not additive across roles): the passer gets the whole EPA
   of his dropbacks; a receiver the whole EPA of his targets, split into air EPA and YAC
   EPA; a rusher his designed runs. A pass's EPA therefore appears under both passer and
   receiver.
2. **Adjusted value** (per season): ridge regression of play EPA on role indicators
   (passer on dropbacks, receiver on targets, rusher on designed runs) plus the defence (a
   team indicator), with unpenalised pass and run intercepts; penalties in pseudo-plays:
   passer 200, receiver 60, rusher 120, defence 600. Value = coefficient × plays (EPA above
   an average player in that role).
3. **On-field RAPM** (2016–2025, participation): ridge of play EPA on the eleven offensive
   players and the defence team, penalty 1,500. It is the only measure that reaches
   offensive linemen, but they play together almost every snap, so their coefficients are
   near-collinear and heavily shrunk: team blocking credit, not individual grades. Not
   available in-season.

EPA is nflverse's by default (`epa_source="nflverse"`) or ours.

### 8.3 QB composite: `qb.py`

Components per QB-season: EPA per dropback (nflverse), CPOE (ours), sack rate, and the
turnover-worthy rate (FTN interception-worthy throws from 2022, else the interception
rate, whose k is about twice twp's). Each is shrunk to a prior with its stabilisation k,
posterior = (n·x + k·prior)/(n + k); the prior is the QB's own history (weight 0.6^lag ×
volume), itself shrunk to the league. The composite is the regression of next season's EPA
per dropback (QBs with 200+ dropbacks both seasons) on this season's standardised
posteriors; `pct` is its percentile among qualified QBs, and the catalogue shows it as
100 + 10 z (`composite_epa` keeps the forecast). Committed fit (663 season pairs
1999–2025): weights EPA/dropback 0.0546, CPOE 0.0045, sack rate −0.0039, turnover-worthy
rate +0.0009, intercept 0.0506; the composite correlates 0.464 with next season's EPA per
dropback against 0.447 for raw EPA per dropback. Without the model the catalogue blends the
shrunk components 0.55 / 0.2 / 0.1 / 0.15 (`analytics/players._fallback_composite`).

---

### 8.4 Value above replacement, team needs and trades: `analytics/value.py` (added 15 October 2026)

One currency for the value page, the team pages' strengths and needs and the trade simulator: **points (EPA) above a
replacement-level player at the same position** (GVAR).

- **QB, RB, WR, TE**: GVAR = Σ over the player's roles (passer, receiver, rusher) of (adjusted rate − replacement rate of
  his position in that role) × plays in the role, the rates being 8.2's ridge coefficients. The replacement rate is the
  20th percentile (`REPL_Q`) of the role's rates among the position's players with at least max(30, 10 per team game)
  dropbacks, max(10, 2 per team game) targets or max(15, 3 per team game) carries (`ROLE_FLOOR`); a position with fewer
  than five such players takes the league-wide rate for the role. Receivers' ridge coefficients are not centred (in 2026
  through week 6 they sum to +332 EPA against +17 for passers: targeted passes are better than the sacks and throwaways in
  the intercept), which is why the comparison is with replacement and not with zero. Without the player-value model the
  raw credit per opportunity, shrunk with 100 pseudo-opportunities, stands in.
- **K**: points over expected (7) per attempt shrunk with k = 60 attempts, minus the 20th-percentile qualified kicker,
  times attempts. **P**: punting EPA over the league's EPA-weighted mean punt, shrunk with k = 60 punts, the same way.
- **Defenders** (EDGE, DL, LB, CB, S): Splash EPA per game (the catalogue's `def_value`) shrunk with 6 games toward the
  position's qualified mean, minus its 20th percentile, times games. Edge and interior roles come from the latest weekly
  roster's NGS position, else PFF's position in the nflverse player table, else the crosswalk's NGS position, else the
  depth chart (3-4 outside linebackers are edge rushers), else the listed position (DE edge, DT/NT interior, OLB
  linebacker, DB cornerback). Credited plays only, never scaled: across 640 team-seasons (2006–2025) team splash EPA per
  game tracks opponent-adjusted defensive EPA per game with slope 1.29 and r 0.71, but that slope carries the coverage
  that creates the splash plays. The offensive check: team Gridiron Value per game against opponent-adjusted offensive EPA
  per game, slope 1.10, r 0.95.
- **OL**: not valued individually (8.2: RAPM is collinear across the five linemen); teams are graded on pass protection.

**Teams (the starters model)**: a position's value is the sum of the best per-game GVARs, each floored at 0 (a replacement
player is always available), over its starters (QB 1, RB 2, WR 3, TE 2, EDGE 2, DL 2, LB 2, CB 3, S 2, K 1, P 1) among the
players on the latest weekly roster who are active or inactive (injured reserve and the practice squad are out). The QB
is the team-strength model's QB term instead: NP × the starter's EPA-per-dropback value (10), so a QB change moves a team
exactly as the season simulation's starting-QB override does. Players carry the per-game value they have shown; an
early version spread each player's per-play rate over the volume of the slot he took, and a backup running back with a
few big plays came out as a 2.7-points-a-game upgrade, so that was dropped.

**Grades** (team pages): units (the QB term; pass and rush offence and defence as opponent-adjusted EPA per play; pass
protection and pass rush as pressure rates, or sacks per dropback in-season, when participation data are not yet out;
special teams) and positions, as percentiles among the 32 teams: A from 80, B 60, C 40, D 20, F below. Strengths: the top
three at 60 or more; weaknesses: the bottom three at 40 or less.

**Ways to improve**: for each weak position (a weak unit maps to its positions: pass offence QB/WR/TE, rush offence RB,
pass defence CB/S/EDGE, rush defence DL/LB, pass rush EDGE/DL, special teams K/P; pass protection has none), every player
on another roster is scored by what he adds (he replaces the weakest starter if he is better; a QB only if his value beats
the starter's): gain = k_resp × Δ position value, with k_resp = s + b_mr × 0.77 (11.1; 0.847 with the committed fit), the
margin's response to a rating change once the market ratings carry it. The top five, with the change in expected wins
and playoff odds from the team's sensitivity curve (13.1), what the player's own team loses (its next man up), and hints:
the seller under 10% to make the playoffs; a cost to the seller under half the gain (depth); age 31 or more; a contract
year only when contracts are enabled. Unsigned candidates: players the latest weekly roster lists as released, or with
no roster entry while the nflverse player table says released (not retired), valued on this season or last.

**Trade simulator** (client-side, `trade.js`): the same starters model on both rosters after the move, the QB rule above,
Δ = k_resp × (Σ Δ position values + NP × ΔQB), and each team's odds read off its own curve at Δ. Verdict: "wins now" for
+0.15 expected wins or +2 points of playoff odds, "weakens now" for the same falls; three or more years younger on
average is flagged as a possible long-term gain, not quantified (no ageing model).

**Contracts** (`analytics/contracts.py`): nflverse's `contracts` release is OverTheCap's data; OverTheCap's terms and
conditions (read 15 October 2026) forbid its data being "used by or provided to any websites ... for the purpose of
providing comprehensive information on professional football contracts, rosters, or player valuations unless contracted
by OTC". Cap hits, contract years and the cap check are built only behind `--contracts` / `GRIDIRON_CONTRACTS=1` and are
off; the pages say so.

## 9. Stabilisation: `stabilise.py`

For each metric and each sample size n on a grid (10, 20, 30, 40, 50, 75, 100, 125, 150,
200, 250, 300, 400, 500), take every player (or team) with at least 2n events in the
season, split the first 2n into odd and even halves and correlate the half means (needs 20
players). Under Spearman–Brown, r(n) = n/(n + k), k = n(1 − r)/r and n₀.₇ = 7k/3. k is
fitted per season by least squares over the grid (weighted by players) and pooled as a
players-weighted geometric mean. k is the shrinkage constant the other models use.

| Metric (unit) | k | n₀.₇ | Seasons |
|---|---|---|---|
| EPA per dropback (dropback) | 179.7 | 419 | 27 |
| CPOE, ours (aimed pass) | 264.4 | 617 | 17 |
| Sack rate (dropback) | 144.7 | 338 | 27 |
| Interception rate / turnover-worthy rate (attempt) | 550.1 / 420.9 | 1,284 / 982 | 27 / 4 |
| RYOE per carry / rushing success (carry) | 201.9 / 127.1 | 471 / 297 | 27 |
| CROE / EPA per target (target) | 183.4 / 105.5 | 428 / 246 | 17 / 27 |
| YACOE (reception) | 78.2 | 182 | 20 |
| Team offensive / defensive EPA per play (play) | 272.4 / 541.4 | 636 / 1,263 | 27 |
| FG over expected (attempt) | 60.9 | 142 | 16 |

Metrics without a fit take `DEFAULT_K` (e.g. EPA per dropback 300, CPOE 350).

---

## 10. Team strength: `team_strength.py`

Opponent-adjusted unit ratings, refitted before every week. One weighted ridge per unit
and target (EPA per play and success rate), on `_cdata.unit_rows` (one row per game ×
offence × passer):

```
pass (dropbacks):   y_gtq = μ + hfa·h_g + PT_t + QB_q + PD_o + ε
rush (designed):    y_gt  = μ + hfa·h_g + RO_t + RD_o + ε
special teams:      s_gt  = ST_t − ST_o + ε                      (net ST EPA per game, points)
minimise Σ w_i (y_i − x_i b)² + Σ λ_j (b_j − m_j)²,   w = plays · 0.5^(age in weeks / half-life)
```

h = +½ at home, −½ away, 0 neutral; offence terms are EPA per play gained above the
league, defence terms (PD, RD) EPA per play allowed above the league (positive = worse);
μ and hfa carry λ = 10⁻⁶. λ is the prior's weight in plays. **Priors** for season S come
from the end-of-season fit of S − 1, mapped across relocations:
m_unit = c_unit · b_unit(S − 1) (the continuity term k_unit is set to 0; continuity, when used, is the share of
S − 1's scrimmage snaps, counted from the play participation, played by players on each club's opening S roster:
`_cdata.onfield`, `_cdata.roster_at_start`; nflverse snap counts are Pro Football Reference's and not used); QBs carry c_qb
per idle season, and a QB never seen starts at `qb_new` EPA per dropback. Posterior sd of b
= s_play · √diag((X′WX + Λ)⁻¹).

| Constant | Default | Committed (`team_strength_params.json`) |
|---|---|---|
| half-life | 30 weeks | 30 weeks |
| λ: pass team, QB, pass defence, rush offence, rush defence, ST | 500, 350, 450, 450, 550, 6 | same |
| carry: pass team, QB, pass defence, rush offence, rush defence, ST | 0.575, 0.95, 0.50, 0.60, 0.505, 0.45 | 0.571, 0.95, 0.541, 0.644, 0.574, 0.459 |
| `qb_new` | −0.02 | −0.02 |
| NP, NR (dropbacks, designed runs per team game) | 35, 26 | 35, 26 |

The defaults were chosen by walk-forward game log-loss 2006–2025 over a grid (half-life
6–1,000 weeks, λ ×0.5–×2, QB λ ×0.3–×3, QB carry 0.7–1.0, new-QB prior −0.10–0); the unit
carry-overs are fitted by `fit_carryover` (regression of end-of-season ratings on the
previous season's; the QB carry stays the tuned constant).

**Net rating** (points per game against an average team on a neutral field):
net_t = NP·(PT_t + QB_starter(t) − PD_t) + NR·(RO_t − RD_t) + ST_t. A starting-QB change
(injury report, depth chart or the GAME's listed starter) moves net through QB_q.

---

## 11. The game model and the drive simulation: `game.py`, `drive_sim.py`

### 11.1 Margin

```
μ = s·(net_h − net_a) + b_sr·(sr_h − sr_a)
  + (HFA + trend·(season − 2015)/10 + HFA_season)·[not neutral] + b_div·[not neutral]·[division game]
  + b_rest·(clip(rest_h, 4, 14) − clip(rest_a, 4, 14))/7 + b_bye·(bye_h − bye_a) + b_short·(short_h − short_a)
  + b_travel·(km_a − km_h)/1000 + b_tz·(tz_a − tz_h) + b_mr·mr
```

**Market ratings** (`mr`, added 2 October 2026; `models/market_ratings.py`, `game.attach_market`): before each
week, a weighted ridge of every earlier **played** game's closing line (nflverse) on home field and one term per
team, weights 0.5^(age in weeks / 2), pulled toward 0.8 × the team's final rating of the previous season with weight
0.3 games; each past game's starting quarterbacks are taken out first (0.77 × NP × (QB_h − QB_a), the QB values of
section 10), and the game being priced adds its own QBs back. So mr is "the line the market's own recent opinion
implies, with this game's quarterbacks". It is a market-blend input: it carries what earlier prices knew (injuries,
depth, money) and the EPA ratings miss, and it is never the price of the game itself. The constants were chosen on
2006–2016 (RMSE against the close 2.54 points with the listed QBs, 2.78 with the expected ones; the model alone 3.1);
the edge research (`docs/research/nfl_edge.md`) found it the one clear out-of-sample gain: 2017–2026 moneyline
log-loss −0.0063 (95% CI −0.0098 to −0.0029), ATS −0.0058, totals −0.0038. Totals get the same from closing totals
(`mrt` = market total rating − base). `predict_frame` attaches it from the season's games on disk, or from
`market_games` (the season simulation passes its games cut at the simulation date, so only results before then
enter); a frame without it (a hypothetical matchup) falls back to 0.77 × net difference + 2 × home field.

sr is a success-rate composite NP(SR_PO − SR_PD) + NR(SR_RO − SR_RD); short is a short week
(≤ 5 days); travel the distance from the home stadium to the venue; tz the hours between
home time zone and the venue's. HFA_season is one coefficient per season, ridge-penalised
towards 0 (`LAM_HFA` 40), so a season with few games leans on the trend. All coefficients
are fitted by `fit_from_rows` (ridge, penalty 1) on **walk-forward rows** (ratings fitted
from games strictly before each week); σ is the residual sd.

**Distribution**: the margin is discrete on −80…80 with key numbers,
p(m) ∝ [Φ((m + ½ − μ)/σ) − Φ((m − ½ − μ)/σ)] · k(|m|), with k(|m|) for |m| ≤ 30 fitted by
`fit_keys` as the ratio of observed to Normal-expected frequency (k(0) = 0.078, so a tie is
about 13 times rarer than a normal puts on [−½, ½]; k(3) = 2.78, k(7) = 1.81, k(10) = 1.22,
k(14) = 1.42). P(home) = P(m > 0), P(tie) = P(m = 0); in the playoffs a tie is impossible
(p_home += p_tie/2).

### 11.2 Total

```
total = base_s + t_c + t_off·O + b_wind·max(wind − 8, 0)·outdoor + b_cold·max(45 − temp, 0)·outdoor + b_dome·[dome or closed]
        + b_mrt·(market total rating − base_s)
O = NP·(PO_h + PD_a + PO_a + PD_h) + NR·(RO_h + RD_a + RO_a + RD_h)
```

base_s is the exponentially weighted mean total of earlier games (half-life 256 games);
total ~ Normal(total, σ_total); team points = (total ± margin)/2. Missing wind is read as
5 mph and missing temperature as 60 °F.

**Markets through the same machinery**: `spread_to_p(line)` turns a market margin into
P(home) through the discrete distribution with σ_market; `ml_to_p` de-vigs American
moneylines multiplicatively.

| Parameter | Code default | Committed fit (`game_params.json`, 5,145 walk-forward rows from 2006; refit 2 Oct 2026) |
|---|---|---|
| s (net rating) | 0.9 | 0.250 (0.774 before the market term) |
| b_mr (market ratings) | 0 | 0.775 |
| b_sr | 0 | 0.276 |
| HFA, trend per decade | 1.9, −0.7 | 0.942, 0.053 (the market term carries most of home field) |
| division, rest, bye, short week | −0.4, 0.3, 0.5, −0.3 | −0.965, 1.351, 0.159, −0.070 |
| travel (per 1,000 km), time zones | 0.15, 0.2 | 0.171, −0.355 |
| σ, σ_market | 13.2, 13.0 | 13.261, 13.179 |
| t_off, wind, cold, dome, b_mrt, t_c | 1.0, −0.35, −0.05, 1.0, 0, 0 | 0.303, −0.338, −0.027, 1.347, 0.497, −0.630 |
| σ_total, t_base | 13.3, 44 | 13.462, 44 |

`game.params()` reads the cache, else the committed fit, else the defaults; the site runs on
the committed fit. The backtest refits these per season (`params_by_season` in
`calibration.json`; the 2026 refit on 6,848 rows is s 0.286, b_mr 0.78). Season home-field
terms in the backtest run from 0.29 (2020) and 0.51 (2019) to 3.28 (2011); 2026 so far
1.06.

### 11.3 Drive simulation

For score shapes, team totals and cover / over probabilities: a drive-level Monte Carlo.
Drive outcomes TD, FG, PUNT (reference), TO, DOWNS, MISS, HALF, SAFETY, OPPTD by a
multinomial logit, logit_k = a_k + b_k·s + c_k·s² + d_k·x, s = (start − 70)/20, x the
offence's expected EPA per play edge from the walk-forward ratings (maximum likelihood,
L-BFGS, ridge 10⁻³; committed fit on 124,260 drives). Each half has N drives (normal,
10.56 ± 2.12 in the committed fit), alternating possession; the next start is drawn from
the empirical starts after each kind of result. Points: TD 6 + try (PAT by era, or a
two-point attempt 10% of the time at 0.48), FG 3, SAFETY 2 to the defence, OPPTD 7 to the
defence. Overtime by season and game type: regular season sudden death to 2011, modified
sudden death 2012–2024 (10-minute periods from 2017), both teams possess from 2025;
playoffs sudden death to 2009, modified 2010–2021, both possess from 2022, played to a
winner. `calibrate` shifts each side's x (two secant iterations) so simulated mean points
equal the game model's team points: the drive simulation supplies the shape, the game
model the means. The build runs 10,000 simulations per priced game (2,000 with `--quick`).

---

## 12. Live win probability: `live.py`

Primary: builder B's WP model (`wp.state_wp` on its current fit) fed ESPN's live state,
with our pre-game expected margin as the possession team's spread, so pre-game strength
fades with the clock as that model learned. Fallback (no fit, or a state the model cannot
take):

```
WP_home = Φ((D + E + μ·f) / (σ·√f + 0.5)),   f = seconds left / 3600 (overtime 600/3600)
E = clip(6.3 − 0.07·yardline_100 − 0.35·(down − 1) − 0.03·(distance − 10), −1, 6), signed to the home side
```

D = home minus away score, μ the pre-game margin, σ the game model's margin sd; at zero time
a non-tied game is decided. `wp_series` scores every play of the ESPN record for the game
centre's chart (ours against ESPN's).

---

## 13. Season and playoff simulation: `season_sim.py`, `tiebreak.py`

20,000 simulations of the rest of the season (chunks of 4,000):

```
margin = μ_g + (x_s,h,w − x_s,a,w) + σ_n·ε,   x_s,t,w = z_s,t + Σ_{k≤w} u_s,t,k
z ~ N(0, (se_scale·se_t)²),   u ~ N(0, DRIFT²),   DRIFT = 0.35 points a week
σ_n = √max(σ² − mean rating variance of a game, (0.85σ)²)
```

μ_g from `game.predict_frame` (ratings with each side's QB, home field by season, rest,
travel, time zones); se_t from team strength; `se_scale` 0.75 in the committed
`season_sim_params.json` (chosen on the backtest's season log-loss: 0.3289 at 0.5, 0.3285
at 0.75, 0.3295 at 1.0). A regular-season game is a tie with probability P_TIE (0.35%
before 2017, 0.5% 2017–2024, 0.4% from 2025), otherwise the margin's sign decides; scores
are integers (margin at least 1, total of the right parity), so every tiebreak quantity is
exact.

**Tiebreakers**: exactly `canon.DIVISION_TWO / DIVISION_THREE / WILDCARD_TWO /
WILDCARD_THREE` with the semantics of `tiebreak.Table` (one club advances per application;
the rest restart at step 1; two-club remainders restart in the two-club format; a Wild Card
group from one division uses the division procedure; division winners are seeded by the
Wild Card procedure). `FastTable` evaluates team-level steps once per chunk and group steps
per tie; a simulation whose seeds are decided by percentages alone never enters the
per-tie code. Net touchdowns are not simulated (that step passes to the coin).
`RESTART_THREE = True` applies the published rule "if three clubs remain tied after a
fourth is eliminated, restart at step 1 of the three-club format (Wild Card: step 2)";
`tiebreak.Table` (the "if the season ended today" seeding) continues with the next step
instead, so the two can order a rare three-club tie differently.

**Playoffs**: seeds 1–4 division winners, 5–7 Wild Cards (5–6 before 2020); byes 1 (2
before 2020); Wild Card seed b+1 v the lowest, ...; reseeding (the best remaining seed hosts
the worst); conference finals at the better seed; Super Bowl neutral; P(home) = Φ((x_h − x_a
+ HFA)/σ_n) with end-of-season strengths; played games fixed.

**Draft order**: non-playoff clubs by win percentage (worst first), then strength of
schedule (lower first), then a random draw; playoff clubs by round of elimination, within a
round by percentage then SOS. Trades and forfeits are not modelled.

**Next-game odds** are interventional: each simulation is weighted by 1/P(result | draws).
**Magic numbers** are deterministic: division and No. 1 seed magic_i = k-th largest (W_j +
R_j − W_i + 1) over rivals, tragic likewise (wins only, ties ignored, tiebreaks assumed
lost); the playoff berth uses sufficient conditions (clinched when the division is clinched
or at most 3 conference rivals can still reach i's wins; eliminated when the division is
lost and at least 7 rivals are out of reach above).

---

### 13.1 Sensitivity curves (the trade simulator): `season_sim.sensitivity` (added 15 October 2026)

`prepare(season, state)` holds everything `simulate` computes before its first random draw (state, ratings, each
remaining game's mean margin and total); `simulate` accepts `shift` ({team: points per game} added to the team's
strength in every remaining game and in the playoffs), `z_scale` and `record` (the team's per-simulation rating draw and
outcomes). With none of them set the output is unchanged (checked: identical odds to the previous code at the same seed).

For each team, one run of 2,000 simulations (`--quick`: 300) in which only that team's rating error z is drawn from
N(0, (3·se)²); every simulation is weighted by N(z; Δ, se²) / N(z; 0, (3·se)²), which turns the run into the outcomes
with the team's true strength shifted by Δ, for Δ on the grid −10, −8, −6, −4, −3, −2, −1, 0, 1, 2, 3, 4, 6, 8, 10
points a game. Keys: playoffs, division, bye, conference, Super Bowl, mean wins, mean draft slot. The weighted means are
made non-decreasing in Δ (isotonic regression weighted by the effective sample size, 491–955 of 2,000 across the teams and shifts in 2026) and
anchored at 0 to the published 20,000-run odds (probabilities move by the curve's change in log-odds, clipped at 10⁻⁴;
wins and the draft slot by its change in level). 32 teams take about 35 s; the result is cached on the simulation's
inputs (ratings, rating errors, game means, results so far, the published odds, n) and recomputed when one changes.

Checked on 15 October 2026 against direct runs with the shift applied (20,000 runs each; KC, NYJ, DET, CLE at ±3 and ±6):
mean absolute differences playoffs 0.8 points (largest 4.1, NYJ +6), division 0.9 (3.4), Super Bowl 0.3 (0.9), mean
wins 0.04 (0.15), mean draft slot 0.16 (0.48). A starting-QB override through the simulation (the depth chart's backup
for the starter at KC, BUF, SF) against the curve at k_resp × NP × ΔQB: mean wins within 0.08 and playoff odds within
2.6 points; Super Bowl odds read 0.6–1.3 points higher off the curve because the simulation's playoff games apply the full
rating change where the curve applies the game model's 0.85.

## 14. Awards and markets: `awards.py`, `sources/markets.py`

### 14.1 Awards

MVP, OPOY, DPOY, OROY, DROY, CPOY and Coach of the Year by a conditional logit per award,
P(i) = exp(β·z_i)/Σ_j exp(β·z_j), z standardised within the season's candidate pool, β by
maximum likelihood with ridge 0.3 on the AP winners 2006–2025 (`award_winners.py`, verified
1 October 2026 against the Wikipedia award pages; the 2025 winners cross-checked on ESPN).
Per player-season value = passing EPA + rushing EPA + receiving EPA / 2 (builder B's value
when it exists); def_score = sacks + 1.5 INT + FF + 0.5 TFL + 0.3 PD + 0.25 QB hits. In
season, counting stats are projected to a full season, team win % uses the simulation's
expected wins and the logits are tempered by (0.35 + 0.65 × share of the season played).

| Award | Features (committed β) | Seasons | Winner ranked first |
|---|---|---|---|
| MVP | value 1.55, passing EPA 0.18, team win % 0.48, No. 1 seed 0.41, QB −0.42 | 20 | 12 |
| OPOY | value 1.33, scrimmage yards 2.13, TDs 0.61, team win % 0.88, QB 0.09 | 20 | 12 |
| DPOY | sacks 0.60, INT 1.49, FF 0.73, TFL 0.81, PD 0.21, QB hits 0.51, tackles 0.09, team defence 1.05 | 19 | 9 |
| OROY | value 0.63, scrimmage yards 1.45, TDs 0.79, team win % 0.08, QB 1.32 | 20 | 14 |
| DROY | sacks 0.97, INT 0.24, TFL 1.03, PD 0.97, tackles 1.05, FF −0.09 | 20 | 10 |
| CPOY | value −0.23, value change 0.79, games missed last season 0.87, QB 0.56, value two seasons ago 0.32 | 16 | 2 |
| COTY | team win % 0.74, change in win % 1.61, wins over expectation 0.74, No. 1 seed −0.05 | 20 | 10 |

### 14.2 Markets

- **Prices**: the midpoint (bid + ask)/2 of a live two-sided quote, 0 < bid ≤ ask < 1 and
  spread ≤ 0.12 (the Hardwood's rules, `basketball/sources/markets.py`); a last trade is
  never a price. Team field markets (Super Bowl, conferences, divisions, No. 1 seeds) are
  pooled across sources and published only when at least max(4, half the field) runners are
  accounted for and the implied total is within 0.8–1.3, then de-vigged multiplicatively.
  Award fields (40–80 runners) are de-vigged per source (`assemble_field`: total 0.8–1.3, or
  up to 1.6 with 20+ runners quoted) and averaged. Two-way markets (games) are de-vigged
  across their two sides; binary per-team markets ("make the playoffs") are averaged.
  Win-total ladders ("N+ wins") are read per team.
- **Games**: Kalshi's two sides, Polymarket's moneyline (slug
  `nfl-<away>-<home>-YYYY-MM-DD`), spreads and totals; a game's market probability is the
  mean of the prediction markets, else the de-vigged closing moneyline.
- **Edges** are model − market in probability (awards: model/market − 1).

On the 1 October 2026 build (`2026/markets.json`, 21:18 UTC), the season simulation's
futures against the de-vigged markets correlated: Super Bowl 0.89 (32 teams), make the
playoffs 0.95 (32), AFC champion 0.97, NFC champion 0.83, No. 1 seed 0.97 (AFC) and 0.94
(NFC) (16 each), divisions 0.82–1.00 (four teams each). Win totals agree less: the model's
P(over) at each market line correlates 0.52 with the market's (64 team-source pairs).
These are a snapshot; they move every build.

---

## 15. Backtest and validation: `backtest.py`

### 15.1 Method

- **Games**: every regular-season and playoff game with a result from 2006 (5,479 in the
  committed run; 14 ties left out of win-probability scoring). Ratings by
  `game.walk_forward` (team strength refitted before every week from that season's earlier
  games, the preseason prior chained from 1999); coefficients refitted before every week on
  all earlier walk-forward rows (key numbers once per season).
- **Forecasters**: `model` (the game model); `model_ratings_only` (rating difference and a
  constant home field); `elo` (NFL Elo as FiveThirtyEight published it: K = 20, home 48 Elo
  points, margin multiplier ln(|m| + 1) · 2.2/(0.001·ΔElo + 2.2), a third of the way back to
  1505 between seasons); `market_ml` (the nflverse closing moneyline, 2006 on, de-vigged);
  `market_spread` (the closing spread through the same margin distribution with σ_market
  fitted on earlier games); `book:<name>` (ESPN closing lines by book, 2017 on).
- **Scores**: log-loss (p clipped to [10⁻⁴, 1 − 10⁻⁴]), Brier, 10-bin reliability; every
  forecaster also on the games with a closing moneyline (`metrics_vs_market`); margin RMSE.
  Against the spread: P(home covers the closing spread) from the margin distribution (push
  removed), scored against covers (pushes excluded), with the record of the model's side
  when P ≥ 0.55; totals likewise.
- **Season odds**: at checkpoints before weeks 1, 5, 10 and 14 of each completed season,
  2,000 simulations with ratings and coefficients fitted strictly before; scored against
  playoffs, division, bye (No. 1 seed), conference champion and Super Bowl.

Run by `scripts/nfl_fit.py --only c` (`fit_c.fit_all`); the committed run took 101 s and
was written at 21:18 UTC on 1 October 2026.

### 15.2 Results (committed `calibration.json`)

**Win probability, 2006–2026**

| Forecaster | All games: n, log-loss, Brier | Games with a closing moneyline: n, log-loss |
|---|---|---|
| model | 5,466, **0.6204**, 0.2160 | 5,331, 0.6194 |
| ratings only | 5,466, 0.6268, 0.2190 | – |
| Elo | 5,466, 0.6302, 0.2203 | – |
| closing moneyline | 5,331, **0.6099**, 0.2113 | 5,331, 0.6099 |
| closing spread | 5,466, 0.6118, 0.2120 | – |

(Run of 2 October 2026 with the market term; before it the model was 0.6267 / 0.6257, beat Elo in 13 seasons and
the moneyline in 3.) The model beats Elo by about 0.010 overall and in 19 of the 21 seasons, and **trails the
closing line by about 0.010** (it beats the moneyline in 4 seasons: 2006, 2015, 2018 and the games of 2026 so far).
Margin RMSE: model 13.34 against the closing line's 13.18. Every ESPN book with 500+ games still beats the model on
the same games (DraftKings 0.596 v 0.631; Unibet 0.610 v 0.622; Westgate 0.612 v 0.623).

**Against the spread and totals** (no edge, as expected): ATS log-loss 0.7013 against
ln 2 = 0.6931 (5,341 games); the model's side at P ≥ 0.55 won 52.1% of 2,746. Totals
0.7007 (5,401); the side at P ≥ 0.55 won 52.3% of 3,062; total RMSE 13.48 against the
closing total's 13.35. Prices that could actually be bet (CLV at the opener, Kalshi, futures):
`docs/research/nfl_edge.md`.

**Season odds** (20 seasons × 4 checkpoints × 32 teams = 2,560 rows per target):

| Target | Base rate | Log-loss (all checkpoints) | Week 1 / 5 / 10 / 14 |
|---|---|---|---|
| playoffs | 0.394 | 0.427 (0.428 before the market term) | 0.591 / … / 0.280 (weeks 1 / 14) |
| division | 0.250 | 0.346 (0.348) | 0.483 / … / 0.230 |
| bye (No. 1 seed) | 0.106 | 0.191 (0.193) | 0.281 / … / 0.110 |
| conference champion | 0.063 | 0.171 (0.171) | 0.208 / … / 0.149 |
| Super Bowl | 0.031 | 0.114 (0.116) | 0.125 / … / 0.107 |

**EP and WP** against nflfastR: sections 2 and 3. **Fourth-down conversion**: section 4.

---

## 16. Known limitations

1. **The closing line beats the model**, as it should: about 0.010 in log-loss over
   2006–2026 (0.016 before the market term). The market knows injuries, inactives, weather and money that the model reads
   late or not at all.
2. **Participation is post-season only**: the current season's completion, YAC and RYOE run
   on the base and FTN tiers, and there is no on-field value in-season.
3. **No individual coverage data**; defenders are rated on credited plays; offensive
   linemen only through RAPM (team blocking credit) and team units.
4. **RYOE cannot see defenders**; NGS's tracking RYOE can.
5. **nflfastR comparisons on 1999–2019 flatter nflfastR** (in sample there).
6. **Fourth downs**: the conversion model under-predicts long conversions (11+ yards: 0.160
   predicted, 0.206 observed); overtime decisions are not graded; the WP model knows little
   about overtime.
7. **Simulations** model no injuries, trades or suspensions beyond the current starting QB;
   strength follows a random walk; net touchdowns go to the coin.
8. **Hand-entered tables** (stadiums, alignments, formats, the tiebreak procedure, the award
   winners) are checked but static.
9. **Small samples**: most rates need hundreds of plays (section 9).
10. **Value and trades** (8.4, 13.1): defenders are valued on credited plays only; offensive linemen not at all;
    players carry the per-game value they have shown, so a backup who would start elsewhere is undervalued; each team's
    odds come from its own curve, so a trade between rivals does not re-simulate their interaction; there is no ageing
    model and no salary-cap check (OverTheCap's terms).

---

## 17. Where the code and other texts disagree (resolved)

Found on 1 October 2026 while writing these documents and **resolved the same day**: the code
was taken as the source of truth except in item 10, where the front end was brought into line
with the payload. Items 1–10 were the site's Methodology (`docs/gridiron/assets/js/docs.js`)
against the code; 11–16 docstrings, logs and contracts. Each item says what was wrong and what
now holds.

### 17.1 The Methodology against the code

1. **Win probability inputs** (resolved): the Methodology listed the second-half kickoff as an
   input; `wp-3` dropped it (`wp.FEATURES`). The page now lists the inputs `wp.FEATURES` holds
   (adding the era) and says why the kickoff term was dropped and that it is still computed
   for the payloads. The fourth-down section no longer lists it among the swapped state.
2. **Team strength weights** (resolved): the page said a 10-week half-life; it now says 30
   weeks (`half_life_weeks`, defaults and committed fit).
3. **Team strength priors** (resolved): the page quoted carry-overs of 0.45/0.75/0.35/0.45/
   0.35/0.35 and a new-QB prior of −0.06. It now quotes the committed fit the site runs on
   (`team_strength_params.json`: 0.571, 0.95, 0.541, 0.644, 0.574, 0.459), the code's defaults
   (0.575, 0.95, 0.50, 0.60, 0.505, 0.45) and the new-QB prior −0.02.
4. **Game model coefficients** (resolved): the page quoted the code defaults and said they ran
   "until the walk-forward fit is published". No payload carries the committed fit (the
   calibration's `params_by_season` are the backtest's walk-forward refits, e.g. s 0.791 on
   6,848 rows for 2026, not the file the site loads), so the page quotes
   `fitted/game_params.json` (5,144 rows, 2006–2026): s 0.774, b_sr 0.494, HFA 2.70, trend
   −0.44, the 2026 season term −0.68, division −1.02, rest 1.32, bye 0.055, short week +0.66,
   travel 0.142, time zones −0.357, σ 13.38, σ_market 13.18, key multipliers k(3) 2.78,
   k(7) 1.81, k(0) 0.078; total t_off 0.511, wind −0.343, cold −0.038, indoor 1.83, constant
   −1.82, σ 13.51. It now describes the success-rate term (the unit ridge on success rate,
   as successful plays per game) and the division term's [not neutral] factor. The Limitations
   bullet says the coefficients are the committed fit.
5. **Gridiron Value** (resolved): the 65% / 25% air/YAC split is gone. The page (and the
   glossary's `gv_term`) now says raw credit gives the whole EPA to passer and receiver alike
   (`player_value.raw_attribution`, not additive), the air/YAC split is shown for receivers
   only, and the per-season ridge (penalties 200/60/120/600) does the sharing out.
6. **Next Gen Stats** (resolved): the data section and the Limitations now say NGS comes as
   weekly and season rows, and that game pages use the weekly rows (`ctx.ngs_weekly`: time to
   throw, separation, NGS RYOE).
7. **Stadiums** (resolved): "about 60" is now 67 (`canon.STADIUMS`).
8. **Drives per half** (resolved): now 10.56 ± 2.12 from `fitted/drive_model.json`.
9. **Drive simulation size** (resolved): the page now says 10,000 drive simulations per game in
   the pricing window, 2,000 in a quick build (`build_gridiron.price_window`), and that past
   games carry the analytic margin and total distributions.
10. **Fourth-down grades** (resolved; decision): the payload's letter (`analytics/games.
    GRADE_CUTS`: A ≤ 0.5 pp, B ≤ 1.5, C ≤ 3, D ≤ 6, F beyond) is kept as the grade of record,
    since every published game page and `fourth_downs.json` carry it and `PAYLOADS.md`
    documents it. The three labels are a grouping of the letters: A and B "Right call" (≤ 1.5
    pp lost), C "Close call" (> 1.5 to ≤ 3), D and F "Mistake" (> 3). `GI.gradeOf` (`core.js`)
    already mapped the letters that way; its numeric fallback (used only without a letter) and
    `fourth.js`'s own fallback moved from < 1 / < 3 to ≤ 1.5 / ≤ 3, inclusive like the cuts.
    The Methodology (fourth-down section, "How the pages compute", glossary `fourth_grade`), the
    fourth-down page's "How the grades work" and the game page legend now state the letters and
    the 1.5 / 3 cut-offs. The Methodology's "should go … by more than 1 point" sentence
    described `fourth_down._grades`, which is not published; it now says the coaches' "went
    when the model said go" uses the recommendation (the highest-WP option).

### 17.2 Docstrings and contracts

11. **`sources/espn.py`** (resolved): the docstring now says the core odds history is fetched
    from 2017 (`canon.ESPN_ODDS_FROM`, `nfl_fetch.py --espn-from`); the endpoint also answers
    for 2016 events, which the provider notes still record.
12. **`fourth_down.py`** (resolved): the docstring now says its LightGBM go model (`exp_go`)
    feeds only its own coach and team tables, which the build does not publish
    (`adapters.fourth_tables` has no caller), and that the published GOE (`fourth_downs.json`
    `go_exp`, `coaches.json` `goe`) comes from the per-season logistic regression in
    `analytics/fourth.go_model`. The Methodology says the same and names `analytics/fourth.py`.
13. **`kicking.py`**: unchanged (outside this pass); the punt result is the receiving team's
    yards to go (80 on a touchback), as the Methodology states.
14. **`nfl_fit_c.log`**: unchanged; the Methodology now quotes the committed
    `game_params.json`, not the log.
15. **`CONTRACT.md`**: unchanged; `PAYLOADS.md`'s "As built" section and the code are
    authoritative.
16. **The season-futures figure**: unchanged (not on the site); section 14.2 has the figures.

Also fixed on 1 October 2026: the build wrote a career file for play-by-play's placeholder
player id "0" (a pooled 1999–2000 "defender"). `careers.real_pid` now excludes placeholder ids
("0", "00-0000000", blanks) from `players/<pid>.json` and `players_index.json`, and the build
drops them from the carried-over index (`tests/nfl/test_analytics_d.py::
test_careers_skip_placeholder_ids`). The next build that writes careers drops the id from
`players_index.json` (checked on a scratch copy: 7,471 entries to 7,470). The build never
deletes files, so the committed `docs/gridiron/data/players/0.json` stays (and is mirrored to
the public site) until it is removed by hand; nothing links to it once the index entry is
gone. The 1999 and 2000 season catalogues still list the id until the defensive aggregation
drops it.


## 18. Valuation v2, transactions and trade ratings, fantasy (added 16 October 2026)

Spec: docs/VALUE_SECTIONS.md §4–5. Code: `analytics/valuation.py`, `analytics/transactions.py`, `sources/espn.transactions`,
`analytics/fantasy.py` (frames, scoring, play-level tables), `analytics/fantasy_model.py` (model, backtest, payload),
`scripts/nfl_fantasy_fit.py`; fitted constants in `models/fitted/fantasy.json`. Payloads in PAYLOADS.md "As built:
valuation v2 …".

### 18.1 Valuation v2 (`valuation.py`)
Fitted on our own value tables (`data/<S>/value.json`, 1999–2025; 35,349 player-seasons). Per position the season-to-season
regression next = a + b·x + c₁A + c₂A² (A = age − 27; players with 4+ games in both seasons, weighted by the smaller
sample) gives the shrinkage constant k = g(1 − b)/b at the median sample and the ageing delta. Fitted 16 Oct 2026:

| Pos | b | k (games) | residual SD (pts/g) | n pairs |
|---|---|---|---|---|
| QB | 0.52 | 13.1 | 2.54 | 923 |
| RB | 0.43 | 17.2 | 0.78 | 2,302 |
| WR | 0.51 | 13.3 | 0.89 | 2,943 |
| TE | 0.58 | 9.3 | 0.59 | 1,555 |
| EDGE | 0.47 | 14.8 | 0.43 | 2,563 |
| DL | 0.50 | 13.0 | 0.31 | 2,845 |
| LB | 0.29 | 33.9 | 0.40 | 2,592 |
| CB | 0.25 | 39.3 | 0.45 | 2,679 |
| S | 0.25 | 43.1 | 0.44 | 2,141 |
| K | 0.09 | 155 | 0.15 | 767 |
| P | 0.24 | 49.6 | 0.40 | 457 |

Ageing (expected change in points a game per year, an average player): RB +0.11 at 22, −0.07 at 26, −0.20 at 30; WR +0.09,
−0.05, −0.16; QB +0.17, +0.02, −0.09; edge rushers +0.03, 0.00, −0.04. Availability: share of players with 4+ games who play
the next season, and their games share, by position, age band (≤24, 24–27, 27–30, 30–33, 33–36, 36+) and level (above or
below the position median), blended with the player's own games / club games over this season and last (shrunk with 8
games toward 0.9). QBs with a team-strength QB value use np × (qb_val − qb_new) as the level, carried toward an average QB
at the model's 0.95 a season. Value = Σ 0.9ᵏ max(0, level_k) E[games_k] over the rest of this season and three more; band
from 400 random-walk draws (σ₁ then the drift √(σ₂² − σ₁²)). Wins per point of season margin 0.0280 (2002–2025 team
seasons). Scarcity index (next season, top five v the (32 × starters)-th level, relative to the average position): QB 5.4,
WR 1.2, TE 0.8, RB 0.6, EDGE 0.4, DL 0.2, LB 0.2, CB 0.1, S 0.1.

Draft-pick curve: 3,171 picks of the 2008–2022 drafts (slots from the nflverse players release, NFL draft API; offensive
linemen and long snappers excluded), realised value over the first four seasons discounted 10% a season, fitted
c + a e^(−b(p−1)) on 8-pick bin means: a 45.9, b 0.0255, c 3.65 (pick 1 49.6 points, pick 32 24.5, pick 64 12.9; round
means 35.4, 17.7, 9.9, 6.4, 4.9, 4.2, 3.9).

### 18.2 Transactions and trade ratings (`transactions.py`)
Source: ESPN `site.api…/nfl/transactions?season=<calendar year>` (about 2,800 notes in 2025, 1,850 to mid-October 2026),
the public site data the site already uses, credited. Parsing, merging and the rating rules are in the module docstring and
the methodology. On the window 15 Oct 2025 – 15 Oct 2026: 47 trades rated (both clubs' notes merged for most), 4,389 feed
clauses (signings 1,196, practice-squad moves 1,112, releases 850, reserve 738, activations 244, claims 89, trade clauses 77,
extensions 74). Left out for terms: nflverse `trades` and `draft_picks` (Pro Football Reference) and contracts (OverTheCap).
Known weaknesses: values at the time ignore in-season form before a mid-season trade; QBs at the time are valued on GVAR
history (the QB model's past values are not stored); defenders' values are a floor; picks cannot be tied to the player drafted.

### 18.3 Fantasy (`fantasy.py`, `fantasy_model.py`)
Model in the `fantasy.py` docstring and the methodology. Tuning (2014–2018, PPR MAE of the pool) over half-life {3, 6} weeks,
opponent exponent {0.3, 0.7} and prior weight {2, 4} games chose 6 / 0.3 / 2 (MAE 4.933; the grid's worst 4.993) — the
chosen half-life and prior weight are at the grid's edges. Constants refitted on 2014–2025: team offensive TDs = −0.51 +
0.129 × implied points; kicker points = 4.04 + 0.166 × implied; points-allowed SD 9.33; script slopes per point of expected
margin −0.03 targets, +0.15 carries; questionable skill players recorded a stat 56% of the time, doubtful 0.6%; fumbles
lost 0.95% of touches. Floor/ceiling SD = c0 + c1 × projection: QB 12.1 + 0.06p, RB 6.5 + 0.08p, WR 6.3 + 0.11p, TE 5.7 +
0.10p; the 10th–90th band held 84.5% of actual scores of players who played (target 80%).

Walk-forward backtest 2019–2025 (every week from the games before it; 34,479 player-weeks in the pool; actual 0 when a player
did not play), PPR:

| Pos | n | MAE model | MAE season-to-date | MAE last season | ρ model | ρ s-t-d | ρ last | ρ played: model / s-t-d | MAE played: model / s-t-d |
|---|---|---|---|---|---|---|---|---|---|
| QB | 4,853 | **4.74** | 8.29 | 9.58 | **0.716** | 0.432 | 0.257 | **0.385** / 0.310 | **6.36** / 6.64 |
| RB | 9,748 | **4.61** | 6.25 | 7.03 | **0.728** | 0.448 | 0.320 | **0.554** / 0.530 | **5.55** / 5.62 |
| WR | 14,654 | **4.67** | 6.35 | 6.90 | **0.670** | 0.408 | 0.317 | **0.483** / 0.461 | **5.62** / 5.79 |
| TE | 5,224 | **3.92** | 5.42 | 5.73 | **0.656** | 0.336 | 0.241 | **0.444** / 0.380 | **4.71** / 4.95 |
| All | 34,479 | **4.55** | 6.45 | 7.15 | | | | | **5.56** / 5.72 |

Half-PPR all 4.09 v 5.82 v 6.43; standard 3.67 v 5.24 v 5.76. Most of the all-player gap is availability (injury report,
injured reserve, starting QB); among players who played the model still wins every position, by 0.07–0.29 points and
0.02–0.08 in rank correlation. The model wins every season 2019–2025 at every position (PPR MAE). Kickers: MAE 3.61 v 3.90
(season-to-date) v 3.74 (last season), ρ 0.14 v 0.08; D/ST: 4.18 v 4.64 v 4.47, ρ 0.28 v 0.11 — weekly kicker and defence
scoring is mostly noise, and the page says so.

Not used, for terms: nflverse snap counts (Pro Football Reference), fantasy-platform ADP / ownership / salaries. Not
available: routes (no in-season source).

## 19. Pro Football Reference data removed (16 October 2026)

Sports Reference's data-use policy says no websites or tools should be built on data scraped from its sites, so every
PFR-origin input is gone (details in DATA_PIPELINE.md 14.1): nflverse `snap_counts` and `pfr_advstats` (no longer
fetched, mirrors deleted; `trades`, `draft_picks` and `combine` were never used), the schedules' PFR game id, PFR ids in
the crosswalk and rosters, and the players release's draft slots before 2008 (player pages show a draft only from 2008).

Where snap counts were used, on-field snaps are now counted from the play participation (`_cdata.onfield`; NGS to 2022,
FTN from 2023; 2016–2025):

- **Team strength (section 10)**: roster continuity = the share of last season's participation snaps played by players on
  each club's first regular-season weekly roster (`_cdata.roster_at_start`), seasons from 2017 (the snap-count version
  covered 2013 on and judged "on the team" by any snap the whole new season, a look-ahead). Correlation with the old
  values 0.91–0.98 a season, 2017–2026. k is 0 in the committed fit, so nothing published moves: the 2026 ratings and
  preseason priors with and without continuity differ by exactly 0.0 (every unit, every team), and the game model,
  season simulation, backtest (`calibration.json`: all-game log-loss 0.6204) and every `fitted/` file stand as they
  are. Nothing in `fitted/` was fitted on snap counts (the carry-over regression uses end-of-season ratings only), so no
  refit was needed.
- **Edge research** (not in production; the promoted blend is `mr`): `inj` (injury report weighted by snap share) paired
  against `base`, moneyline 2017–2026, −0.0008 [−0.0017, +0.0003] with PFR snap counts and −0.0007 [−0.0016, +0.0002]
  with participation shares; its 2006–2016 tuning window loses the 2012–2015 feature values (+0.0139 → +0.0121 against
  the market, now close to `base`'s +0.0120). `cont` (k = 0.5) paired against `base`: +0.0001 [−0.0001, +0.0004] (no
  gain, as before). `mr_inj` 2017–2026 moneyline +0.0129 against the market before and after. Neither feature is promoted.
- **Valuation**: the draft-pick curve already used 2008 onward only; unchanged.

