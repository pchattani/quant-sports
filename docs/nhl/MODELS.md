# Models: technical reference (NHL)

Every model behind The Quant Rink, read from `oddsmarkets/nhl/models/` and the committed
fits in `oddsmarkets/nhl/models/fitted/`. Data and identity are in
[DATA_PIPELINE.md](DATA_PIPELINE.md); how the results reach the pages is in
[DASHBOARD.md](DASHBOARD.md). Section 16 lists where the code, the committed fits, the
site's Methodology (`docs/rink/assets/js/docs.js`), the glossary, the docstrings, the
scripts and the contracts disagree; those items are **open**.

**Every figure here is as of 1 October 2026.** The committed fits were made while the
historical backfill was running: builder B's on 2024–25 and 2025–26, builder C's and the
backtest on the four seasons whose stores were then on disk, all rated on goals alone. They
are to be refitted on the full history once the backfill finishes (expected about 03:15 EDT
on 2 October 2026); the procedure is in section 14.3. **The refit ran on 2 October 2026 (committed in `8fb8c3c`);
its validation, written to `docs/rink/data/calibration.json` at 10:11 UTC that day, is in section 14.4** (added
15 October 2026), which supersedes the 1 October figures in sections 2.4 and 14.2. Section 17 covers the player
value, team needs and trade simulator layer built on 15 October 2026.

Contents

1. Overview
2. Expected goals: `xg.py`
3. Shooting and goaltending: `shooting.py`, `goalies.py`
4. Enriched stints and on-ice rates: `_stints.py`, `onice.py`
5. RAPM: `rapm.py`
6. Rink value: `value.py`
7. Lines and pairs: `lines.py`
8. Stabilisation and percentiles: `stabilise.py`, `analytics/`
9. Team strength: `team_strength.py`, `_cdata.py`
10. The game model: `game.py`
11. Live win probability: `live.py`
12. Season and playoff simulation: `season_sim.py`
13. Awards and markets: `awards.py`, `sources/markets.py`
14. Backtest and validation: `backtest.py` and the xG benchmark
15. Known limitations
16. Where the code and other texts disagree (open)
17. Player value, team needs and the trade simulator: `analytics/value.py`

---

## 1. Overview

### 1.1 How the models feed each other

```
 events.parquet (one season at a time, _io.events) ──► xg.py ──► xG per unblocked attempt ──► shooting.py (GAx, shrunk)
        │                                                   │                               goalies.py (GSAx, shrunk)
        │                                                   ▼
        └── stints.parquet ──► _stints.py (events attributed, xG, score/venue weights) ──► onice.py (rates by role)
                                        │                                                   lines.py (trios, pairs)
                                        ├──► rapm.py (5v5 ridge: xG, goals, attempts; prior = 0.7 × last season)
                                        │          └──► value.py (box prior → RAPM refit → GAR, WAR)
                                        └──► stabilise.py (split-half k) ──► shrinkage everywhere

 _cdata.team_games (team-game rows: 5v5 xG, PP / PK, goals, starters) ──► team_strength.py (weekly ridge, priors)
                                                                              │ expected goals per side, net rating
                                                                              ▼
           game.py: μ_h, μ_a → bivariate Poisson (0–57 min) → late-game chain (57–60) → OT / SO
                │                         │
           live.py (Markov chain)    season_sim.py (20,000 runs, tiebreakers, playoffs, lottery)
                                     awards.py ──► markets comparison ◄── sources/markets.py
                │
           backtest.py (walk-forward, Elo, xG baseline, closing line) ──► calibration.json
```

### 1.2 Model inventory

| Model | File (version) | Fitted where | Used for |
|---|---|---|---|
| Expected goals | `xg.py` (`nhlxg-2`) | `fitted/xg.json` + `xg_main.txt.gz` (2024–25, 2025–26) | every xG on the site, GSAx, GAx, on-ice xG, RAPM |
| Shooting | `shooting.py` (`nhlshoot-1`) | – (per season; k from stabilise) | GAx, shooting talent |
| Goaltending | `goalies.py` (`nhlgoal-1`) | – (per season) | GSAx by danger, shot type, situation |
| Enriched stints | `_stints.py` (`nhlstints-2`) | – (per season) | on-ice rates, lines, RAPM, value |
| On-ice rates | `onice.py` (`nhlonice-1`) | – | catalogues, player pages |
| RAPM | `rapm.py` (`nhlrapm-2`) | `fitted/rapm_prior.json` (2025–26 estimates as the next prior) | RAPM, value |
| Rink value | `value.py` (`nhlvalue-1`) | `fitted/value.json` (box prior, Pythagorean exponent) | GAR, WAR |
| Lines | `lines.py` (`nhllines-1`) | – | lines.json, team pages |
| Stabilisation | `stabilise.py` (`nhlstab-1`) | `fitted/stabilise.json` | shrinkage constants, percentiles, glossary |
| Team strength | `team_strength.py` (1) | `fitted/team_strength_params.json` | ratings, the game model, the season simulation |
| Game model | `game.py` (1) | `fitted/game_params.json` | every game price |
| Live WP | `live.py` | – (the game model's parameters) | live cards and game pages |
| Season simulation | `season_sim.py` | `fitted/season_sim_params.json` | season.json, playoffs, lottery |
| Awards | `awards.py` (1) | `fitted/awards_fit.json` (not fitted; section 13.1) | award races |
| Backtest | `backtest.py` | – | `calibration.json` |

Every model exposes a cached `for_season(season)`; the build calls it through
`analytics/adapters.py`, which isolates failures. Fits are versioned: a cached fit whose
version or input key no longer matches is ignored, and the committed fit stands in when the
cache is cold (CI). Builder B's order is `fit_b.fit_all`: xG → stabilisation (needs xG) →
the RAPM prior → the value model's box prior and Pythagorean exponent.

---

## 2. Expected goals: `xg.py`

### 2.1 Rows and features

Rows: every unblocked attempt (goal, shot on goal, missed shot) with coordinates, outside
the shootout and penalty shots (fewer than three skaters on the ice in total). Label: goal.
Features, all in the shooting team's frame (attacking +x towards the net at (89, 0)):

| Feature | Definition |
|---|---|
| `distance`, `angle`, `x`, `abs_y` | from the (arena-adjusted) location; angle in degrees off the goal-line normal, above 90 behind the net |
| `shot_type_code` | categorical (wrist, snap, slap, backhand, tip-in, deflected, wrap-around, poke, bat, between-legs, cradle) |
| `rebound`, `rebound_angle` | the previous event an attempt by the same team within 3 s (`REBOUND_S`), and the angle change on it |
| `rush` | the previous event in the neutral or defensive zone within 4 s (`RUSH_S`) |
| `dt_prev`, `dist_prev`, `speed_prev`, `prev_type_code`, `prev_x` | seconds and feet since the previous event, its speed, type and x |
| `sk_for`, `sk_against`, `empty_net` | skaters each side; no goalie in the defending net |
| `score_state`, `is_home`, `period`, `sec` | the shooter's lead clipped to ±3; home; period (capped at 4); game seconds |
| `hand_y` | y for a left shot, −y for a right shot (positive = the off wing), NaN when the hand is unknown |

### 2.2 The arena adjustment

Scorer-recorded coordinates before 2020–21 (`_io.TRACKING_FIRST` = 20202021) carry
rink-specific biases. Per arena and season (`arena_maps`), the distances of all attempts in
a team's home games are mapped through their empirical CDF onto the quantiles (1st to 99th,
`ARENA_Q`) of the distances in the same team's road games (its shots and its opponents',
recorded by other rinks' scorers); two passes (`ARENA_PASSES`), so the reference rinks are
themselves adjusted; arenas with at least 300 attempts both ways (`ARENA_MIN_SHOTS`);
neutral sites are left alone. The angle is kept and (x, y) recomputed at the new distance.
Seasons from 2020–21 are not adjusted, but the bias table (median home over road distance)
is reported for every season. In the committed fit (both seasons tracked, `applied` false)
the mean |log ratio| was 0.022 (2024–25) and 0.019 (2025–26), the extremes Edmonton 0.950
and Utah 1.071 (2025–26).

### 2.3 The model

LightGBM binary (`PARAMS`: learning rate 0.04, 31 leaves, at least 300 rows a leaf, L2 10,
feature fraction 0.85, `max_cat_to_onehot` 16, `cat_smooth` 20; up to 1,500 rounds) on the
non-empty-net attempts, **cross-fitted** (`_io.fold_ids`: by season with three or more
seasons, five folds dealt round-robin; **by game with fewer**, five folds by a hash of the
game id), each fold early-stopped (30 rounds) on a 10% game holdout of its training rows;
then **Platt** recalibration (a + b · logit p) on the pooled out-of-fold predictions.
**Empty-net attempts** get their own small ridge logistic (intercept, distance, angle;
ridge 5, the intercept 0.05) shrunk to a prior centre (1.2, −0.02, −0.01), cross-fitted the
same way: boosted trees see too few of them. The production model is refitted on every
season at the folds' mean best iteration. `event_xg(season)` returns the out-of-fold xG for
a season in the fit (`xg_oof/<S>.parquet`, keyed to the fit) and the production model's
otherwise. Danger bands: low < 0.08 ≤ medium < 0.20 ≤ high (`DANGER`, MoneyPuck's bands).

**Committed fit** (`fitted/xg.json`, 18:26 EDT 1 October 2026): seasons 2024–25 and
2025–26, so **cross-fitted by game within those two seasons**; 239,243 attempts, 16,994
goals; five folds of about 170,300–170,800 training rows, best iterations 216–287, mean 236;
Platt (a, b) = (0.0238, 1.0127); empty-net logistic (2.797, −0.0219, −0.0302). Gain
importance: distance 0.365, |y| 0.130, seconds since the previous event 0.088, shot type
0.080, angle 0.057, speed from the previous event 0.052, x 0.043, `hand_y` 0.032.

### 2.4 Validation (out of fold, committed fit)

| Attempts | n | Log-loss (base rate) | AUC | Brier | ECE |
|---|---|---|---|---|---|
| all | 239,243 | **0.2135** (0.2563) | 0.7945 | 0.0583 | 0.0009 |
| 2024–25 | 119,924 | 0.2097 (0.2544) | 0.8010 | 0.0572 | – |
| 2025–26 | 119,319 | 0.2173 (0.2582) | 0.7879 | 0.0593 | – |
| 5v5 | 188,313 | 0.1913 (0.2261) | 0.7948 | 0.0511 | 0.0008 |
| power play | 38,585 | 0.2925 (0.3183) | 0.7020 | 0.0819 | 0.0053 |
| short-handed | 5,221 | 0.2011 (0.2574) | 0.8429 | 0.0585 | 0.0109 |
| empty net | 2,070 | 0.5943 (0.6902) | 0.7408 | 0.2052 | 0.0291 |

Predicted goals 16,993.8 against 16,994 observed; the ten-bin calibration is within 0.007
in every bin. Before Platt the log-loss was 0.21349 (17,045.8 predicted goals).

### 2.5 The fallback (`analytics/xgfallback.py`)

When the model does not score a season (cold cache and no committed fit, a model error, a
season outside its coverage), the build fits a ridge-penalised logistic regression (λ 5) on
the season's own unblocked attempts: distance (linear, log, squared), angle, distance ×
angle, shot type, rebound, rush, strength (PP, SH, EV, empty net); the payloads say
`xg_source` "fallback" (else "model", or "table" when the events carry B's column).

### 2.6 The MoneyPuck benchmark (`benchmark_moneypuck`)

MoneyPuck's xGoal on the same shots, matched on (game, period, rounded second, shooter)
with duplicates on that key dropped from both sides; at least 100 matched shots. Reported
per season: log-loss, AUC and Brier for both on the matched shots (and without empty nets),
the shot-level correlation, label agreement, and team-season and player-season (shooters
with 50+ matched attempts) correlations of summed xG with each other and with goals.
MoneyPuck's model was trained on earlier seasons, so on those its numbers are in sample.
Results: section 14.2.

---

## 3. Shooting and goaltending: `shooting.py`, `goalies.py`

### 3.1 Shooting

On a manned net (empty-net attempts carry no finishing signal), per shooter and season:
unblocked attempts, shots on goal, goals, ixG, GAx = goals − ixG, and

```
talent = GAx / (attempts + k)          GAx_shrunk = attempts × talent = GAx × attempts / (attempts + k)
```

with k the stabilisation constant of "finishing" (goals − xG per unblocked attempt), so
talent is the posterior mean under a normal prior on finishing. Also sh% (goals per shot on
goal) raw and shrunk by `sh_pct`'s k, xsh% (ixG per attempt), fsh% (goals per attempt) and
the 5v5 / power-play split of GAx. Committed k: finishing **783.6 attempts** (n₀.₇ 1,828),
shooting % 80.9 shots (section 8).

### 3.2 Goaltending

Every unblocked attempt on a manned net is charged to the goalie in it (`goalie` on the
event, else the defending side's goalie slot). Per goalie and season:

```
GSAx = xGA − GA      GSAx/100 = 100 · GSAx / fa      GSAx/60 per 60 minutes in net (from the stints)
xSv% = 1 − xG on shots on goal / shots on goal       dSv% = Sv% − xSv%
talent = GSAx / (fa + k),  GSAx_shrunk = fa · talent        (k: stabilise "gsax100", attempts faced)
```

GSAx is split by danger band (low, medium, high), by shot type (wrist, snap, slap,
backhand, tip-in, deflected, wrap-around, other) and by rebound and rush; the bands and the
types partition the attempts, so each set of components sums to GSAx exactly. Committed k
for GSAx per attempt: **2,980.5 attempts faced** (n₀.₇ 6,954).

---

## 4. Enriched stints and on-ice rates: `_stints.py`, `onice.py`

### 4.1 Enriched stints

Builder A's stints with the season's events attributed to them: a faceoff to the stint that
starts at its second (start ≤ t < end), every other event to the stint whose players were on
the ice (start < t ≤ end: a goal at a change belongs to the players coming off). Per stint
and side: `cf`, `ff`, `sf`, `gf` and `xg` (summed xG of the unblocked attempts); the strength
from the home view (`5v5`, `pp_h`, `pp_a`, `ev_other` for 4v4 and 3v3, `en` when a net is
empty); the faceoff zone at its start (O, D, N; F on the fly); the score before it; both
teams' back-to-back flags.

**Score and venue adjustment** (McCurdy-style, `adjust_weights`): at 5v5 an event by a side
leading by d (clipped to ±3) at venue v gets weight 0.5 / s(d, v), with s the league's share
of that metric taken by such sides that season (goals take the xG weights), clipped to
[0.7, 1.4] (`ADJ_CLIP`); the `*_adj` columns.

`player_long` stacks the stints into one row per player-stint from the player's side (role
`5v5`, `pp`, `pk`, `ev_other`, `en_for`, `en_against`); `player_games` gives one row per
player-game (TOI by strength, goals and assists by strength, individual xG and attempts,
hits, blocks, penalties taken and drawn, faceoffs, on-ice 5v5 counts).

### 4.2 On-ice rates

For every skater and role (5v5; pp: his side has more skaters with both nets manned; pk the
reverse): TOI and the on-ice counts for and against (CF/CA, FF/FA, SF/SA, GF/GA, xGF/xGA) as
per-60 rates and shares (CF%, FF%, xGF%, GF%), raw and adjusted. **Relative to team** (5v5):
off-ice = the team's 5v5 totals minus the player's on-ice totals; rel per 60 = on − off,
rel % = on% − off%; a traded player's values are TOI-weighted across his teams.
**Deployment**: OZ start % = offensive-zone faceoff starts / (offensive + defensive) over the
stints he started.

---

## 5. RAPM: `rapm.py`

Each 5v5 stint (both nets manned, five skaters a side, at least one second, `MIN_DUR`)
gives two observations, one per attacking side, weighted by its duration in minutes:

```
y = 3600 · metric_for / duration
  = μ + Σ_attackers O_i − Σ_defenders D_j + h · home_attack + z_O·OZ + z_D·DZ + z_N·NZ start
    + Σ_s c_s · [attacking lead = s]  (s ∈ −2 or worse, −1, +1, +2 or better; tied baseline)
    + b_a · attacker on a back-to-back + b_d · defender on a back-to-back + ε
```

O_i is the xGF/60 a skater adds to his side, D_j the xGA/60 he takes off the opponent
(positive = good defence); net = O + D. Ridge (Bayesian) least squares: O_i, D_i ~
N(m_i, σ²/λ) with m = `PRIOR_CARRY` 0.7 × last season's estimate (sequential fits from the
earliest season on disk, at most `MAX_SEASONS_BACK` 6 back; the first season of a chain
centres on the committed prior when it is the season after it, else on zero; a new player
on zero); the 11 controls nearly unpenalised (`CTRL_RIDGE` 10⁻³). λ from `RIDGE_GRID`
(60, 125, 250, 500, 1,000, 2,000, 4,000, 8,000, 16,000) by five-fold cross-validation over
games (weighted squared error per minute); with fewer than 150 games (`MIN_GAMES_CV`, a
season's first weeks) λ is the last completed season's (`committed_ridge`, default 1,000).
The normal equations (2P + 12 columns) are solved by Cholesky; the posterior covariance
σ²(X′WX + Λ)⁻¹ gives the standard errors of O, D and net (with the O–D covariance). Three
targets: **xG** (the headline), **goals** (with the defending goalie as an extra
defence-only column, so skaters are not charged for goaltending) and **shot attempts**.

**Committed prior** (`fitted/rapm_prior.json`, 18:49 EDT): the 2025–26 estimates (940
skaters) as the 2026–27 centres, with the chosen λ: xG 1,000, goals 4,000 (98 goalies),
attempts 1,000.

---

## 6. Rink value: `value.py`

**Skaters.**

1. **Box prior**: a TOI-weighted ridge (λ 5, `BOX_RIDGE`), pooled over every season on disk
   with stints, of 5v5 xG RAPM offence and defence on standardised individual rates: 5v5
   ixG, attempts, primary and secondary assists per 60, minors drawn and taken per 60, net
   faceoff wins per 60, hits and blocks per 60 (all situations) and a defenceman flag (each
   rate regressed to its position group's mean with 100 pseudo-minutes; players with 150+
   5v5 minutes; weights capped at 1,200). Its residual variance τ² (weighted residual
   variance minus the mean RAPM se², floored at 0.0025) is the prior's variance.
2. **Combination**: the season's 5v5 xG RAPM is refitted with each skater's ridge centre at
   his box prediction (λ again by cross-validation), so a player sits on his box profile
   until his minutes move him.
3. **Components** (goals above average): EV offence = O × 5v5 TOI / 60; EV defence = D × 5v5
   TOI / 60; PP = share × (on-ice PP xGF/60 − league) × PP TOI / 60 / 5; PK = share × (league
   − on-ice PK xGA/60) × PK TOI / 60 / 4, share = TOI / (TOI + 150 min); shooting = GAx
   shrunk; penalties = (minors drawn − taken) × goals per minor (league net PP goals per 60
   × 2 / 60). GAA = the sum. Faceoffs enter only through the box prior.
4. **Replacement**: per position group, the TOI-weighted GAA per 60 of players outside each
   team's top 13 forwards and 7 defencemen by TOI (the bottom 10% when there are none); GAR
   = GAA − replacement rate × TOI / 60.
5. **Wins**: WAR = GAR / goals per win, goals per win = 4g / x (the derivative of the
   Pythagorean expectation at g goals per team-game; x fitted on every team-season on disk,
   2.0 without enough).

**Goalies**: GAR = GSAx − replacement GSAx per attempt × attempts faced (replacement:
goalies outside the top two per team by attempts faced, else the bottom quarter); WAR = GAR /
goals per win.

**Committed fit** (`fitted/value.json`, 18:33 EDT): box prior on 1,555 player-seasons
(seasons listed 2010–11, 2015–16, 2024–25, 2025–26 and 2026–27: the first two were 30-game
samples and the last 8 games), R² 0.592 for offence and 0.075 for defence, τ² 0.0025 on both
(the floor); Pythagorean x 2.01.

---

## 7. Lines and pairs: `lines.py`

From the enriched 5v5 stints, each side's skaters are split by position group (store
positions; F unless D): a side with exactly three forwards and two defencemen contributes
its trio and its pair. Per team and unit: TOI together, on-ice xGF / xGA (and CF / CA,
GF / GA), raw shares and

```
xGF%_shrunk = (xGF + m · p_team) / (xGF + xGA + m)
```

with p_team the team's 5v5 xGF% and m the pseudo-xG of the `xgf_pct` stabilisation
constant (k in seconds × the league's 5v5 xG rate per second, both sides): a unit stays near
its team's share until its own sample of chances is comparable with m. Units with fewer than
20 minutes together (`MIN_TOI`) are left out.

---

## 8. Stabilisation and percentiles: `stabilise.py`, `analytics/`

Every metric is a ratio of sums over an entity's units, with a sample in its own denominator
(events, or TOI in seconds for per-60 rates and on-ice shares). For each n on a grid (25 to
3,000 events; 20 to 800 minutes) every entity with at least 2n keeps its first 2n in game
order, deals the units alternately into two halves, and the half values are correlated
across entities (at least 20). Under Spearman–Brown, r(n) = n/(n + k) and n₀.₇ = 7k/3; k is
fitted by weighted least squares per season and pooled as an entity-weighted geometric mean.
`shrink_k` returns the fitted k, else `DEFAULT_K`, else 200.

Committed fit (`fitted/stabilise.json`, two seasons; time constants in minutes):

| Metric (unit) | k | n₀.₇ | Default k |
|---|---|---|---|
| Finishing, goals − xG per attempt (attempts) | 783.6 | 1,828 | 1,500 |
| Shot quality, xG per attempt (attempts) | 8.4 | 19.5 | 60 |
| Shooting % (shots) | 80.9 | 189 | 375 |
| Save % (attempts faced) | 9,261 | 21,610 | 2,000 |
| High-danger save % (attempts faced) | 3,158 | 7,370 | 1,500 |
| GSAx per attempt (attempts faced) | 2,980.5 | 6,954 | 1,200 |
| Faceoff % (faceoffs) | 87.1 | 203 | 140 |
| Points / 60, all situations (minutes) | 174.4 | 407 | 400 |
| Goals / 60 (minutes) | 249.5 | 582 | 600 |
| 5v5 points / 60 (minutes) | 356.8 | 833 | 500 |
| ixG / 60, 5v5 (minutes) | 61.2 | 143 | 250 |
| CF / 60, CA / 60 (minutes) | 127.8, 287.1 | 298, 670 | 400, 400 |
| xGF / 60, xGA / 60 (minutes) | 189.3, 559.9 | 442, 1,307 | 500, 500 |
| CF%, xGF%, GF% (minutes) | 178.8, 405.2, 2,106 | 417, 946, 4,915 | 400, 500, 1,500 |
| Hits / 60, blocks / 60 (minutes) | 14.3, 104.1 | 33, 243 | 150, 200 |
| Penalties drawn, taken / 60 (minutes) | 400.8, 528.3 | 935, 1,233 | 600, 600 |

**Percentiles** (`analytics.add_percentiles`): a player's value is shrunk towards the
qualified pool's mean, (n·v + k·m)/(n + k), and placed against the pool, pct = 100 (W + T/2)
/ (n − 1), reversed where lower is better (100 = best); displayed values are never shrunk.
**Qualified**: skaters with 250 minutes at 5v5 per 82 team games, prorated (`QUAL_5V5_MIN`;
696 skaters in 2025–26); goalies a quarter of the team's minutes. **Floors** before a metric
gets a percentile: 50 minutes at 5v5, 100 minutes overall, 20 shots or attempts, 50
faceoffs, 20 PP or PK minutes; goalies 100 attempts faced; metrics with no denominator
(counts, GSAx, RAPM, value) need 5 games (goalies 3). `pct_pos` compares forwards with
forwards and defencemen with defencemen. **Projections** regress per-game rates towards the
position group's mean with 30 games of prior for points and 45 for goals, and 5v5 xGF%
towards 50% by its constant.

---

## 9. Team strength: `team_strength.py`, `_cdata.py`

**The team-game table** (`_cdata.team_games`): two rows per played game from the side's
view: goals (regulation and OT, no shootout), 5v5 TOI, score- and venue-adjusted 5v5 xG for
and against, 5v5 unblocked attempts, PP TOI / xGF / GF, PK TOI / xGA / GA, all non-empty-net
xG and goals against, empty-net goals and the starter. xG is the events' own column when
builder B has filled it, else the analytics layer's fallback. **Without derived data the
table is goals-only** (`src` "store"): every xG and TOI column is NaN and team strength falls
back to a goals model.

**Units**, one weighted ridge each (`ridge_two_way`, μ nearly free):

```
5v5 xG       xGF60_{g,t}  = μ_ev + O_t + D_o + e     (O created above the league; D allowed above the league, + = worse)
5v5 shots    FF60_{g,t}   = μ_ff + SO_t + SD_o + e
power play   PPxG60_{g,t} = μ_pp + PP_t + PK_o + e
penalties    PPmin_{g,t}  = μ_pen + DR_t + TK_o + e
goals        GF_{g,t}     = μ_g + A_t + G_o + e       (the goals-only model, used alone when there is no event data)
minimise Σ w_i (y_i − x_i b)² + Σ λ_j (b_j − m_j)²,   w = minutes (games for penalties and goals) × 0.5^(age in days / H)
```

**Finishing and goaltending** are decayed sums shrunk towards the prior: conv = Σ GA / Σ xGA
over the league (the xG model's calibration); fin_t = (Σ GF − conv Σ xGF + k_fin m_t) /
(Σ xGF + k_fin) / conv; a goalie's val = (Σ GA − conv Σ xGA + k_g m_q) / (Σ xGA + k_g) /
conv over the games he started (goals allowed per expected goal above the league, negative
= better; builder B's GSAx stands in when it publishes a season table). In goals mode a
goalie's value is its prior.

**Expected goals for a game** (`expected_goals`; regulation, no empty-net goals):

```
PPmin_h = clip(μ_pen + DR_h + TK_a, 1, 12),   EVmin = 60 − PPmin_h − PPmin_a
xG_h    = EVmin/60 · (μ_ev + O_h + D_a) + PPmin_h/60 · (μ_pp + PP_h + PK_a) + PPmin_a/60 · μ_sh
G_h     = conv · xG_h · (1 + fin_h) · (1 + val_{starter a})
goals mode: G_h = max(μ_g + A_h + G_a, 0.5) · (1 + val_{starter a})
```

The starter is an input (`goalie_h` / `goalie_a`), by default the team's most frequent
starter in its last ten games. Net rating = goals for minus against per game against a
league-average team and goalie.

**Priors** for season S: m = carry × the S − 1 end-of-season value, franchise-mapped (ATL →
WPG, PHX / ARI → UTA); goalies carry carry_goalie^(idle seasons) × their latest value, new
goalies start at `goalie_new`. `fit_carryover` fits each carry as the no-intercept slope of
a franchise's end value on the previous season's (franchises with 30+ games both seasons;
needs 40 pairs a unit, goalies 30 pairs with 60+ xGA).

| Constant | Code default | Committed (`team_strength_params.json`, 17:43 EDT) |
|---|---|---|
| half-life H | 300 days | 300 days |
| λ: 5v5 xG, 5v5 shots, PP, penalties, goals | 1,500 min, 900 min, 260 min, 30 games, 45 games | same |
| k_fin, k_goalie (expected goals) | 160, 110 | same |
| carry: ev_off, ev_def, ff_off, ff_def, pp, pk, draw, take, g_att, g_def, fin, goalie | 0.6, 0.6, 0.65, 0.65, 0.45, 0.4, 0.5, 0.5, 0.75, 0.75, 0.35, 0.7 | same |
| goalie_new | +0.03 | same |
| league before fitting: 5v5 xG/60, FF/60, PP xG/60, PP min, SH goals/60, conv, goals/game | 2.45, 42, 6.6, 4.6, 0.75, 1.0, 2.95 | same |

The committed file equals the defaults: the 1 October fit had only one pair of consecutive
seasons (2024–25 and 2025–26, at most 32 franchise pairs), short of the 40 `fit_carryover`
needs, and no event data. **Schedule features** (fitted in the game model, defined here):
back-to-back, rest days capped at 3, travel km / 1,000 from the previous venue and the
absolute time-zone change, each home minus away (`schedule_features`; `_cdata.add_context`
caps rest at 7 and gives a season opener 7).

---

## 10. The game model: `game.py`

### 10.1 Means

```
log μ_h = b0 + b_xg · log G^xg_h + b_g · log G^g_h + home · [not neutral] + ½ s · f
log μ_a = b0 + b_xg · log G^xg_a + b_g · log G^g_a                       − ½ s · f
```

G^xg is team strength's expected goals (with the **opposing starter's** goaltending), G^g
the goals-only ratings (a second opinion), f the schedule features home minus away, s their
coefficients; μ is a side's regulation goals before the empty-net chain. `fit_means`: a
Poisson GLM on the regulation goals of played walk-forward rows (ridge 2 on all but the
intercept).

### 10.2 Regulation, overtime and the shootout

Minutes 0–57: bivariate Poisson, X = U + W, Y = V + W, U ~ P(μ′_h − λ3), V ~ P(μ′_a − λ3),
W ~ P(λ3), μ′ = μ · 57/60, λ3 = θ · min(μ′_h, μ′_a). Minutes 57–60: a Markov chain on the
score in 10-second steps (at most one goal a step; scores tracked to 12): tied → both rates
× tie_k (teams play for the point); trailing by one with ≤ pull1 minutes left, or by two
with ≤ pull2, → the trailing side's goalie is pulled (its rate × k_pull, the leader adds r_en
goals a minute). Overtime (regular season, tied after regulation): five minutes, 3-on-3 from
2015–16 and 4-on-4 before (`ot_era`), P(goal) = 1 − exp(−5 k_ot (μ_h + μ_a)/60), the scorer
home with probability μ_h/(μ_h + μ_a); otherwise a shootout won by the home side with
probability so_home. Playoffs: sudden-death 5-on-5 at μ_h/(μ_h + μ_a). The NHL credits the
shootout winner with one goal, so the final score is the regulation score + 1 for the
winner of any game past regulation: an overtime game never covers −1.5, and totals are
settled on that score.

`fit_shape`: θ, tie_k, r_en and k_pull by coordinate-wise grid maximum likelihood of the
regulation score (two rounds; grids θ 0–0.25, tie_k 0.4–1.1, r_en 0.12–0.35, k_pull 1.5–3.5;
at most 6,000 games), b0 re-centred so the mean regulation total matches. `fit_ot`: k_ot per
era from the share of regular-season overtimes decided before a shootout; so_home = (home
shootout wins + 150) / (shootouts + 300).

Outputs (`outcome_probs`, `predict`): P(home), P(regulation win / loss), P(OT), P(home in
OT or SO), P(SO), the puck line P(final margin ≥ 2) each way, the totals pmf of the final
score, expected goals, the fair total (the half-goal line nearest an even over / under), the
7 × 7 final-score matrix. Market helpers: `ml_to_p` (multiplicative de-vig of American
moneylines), `two_way`.

### 10.3 Parameters

| Parameter | Code default | Committed fit (`game_params.json`, 17:44 EDT; 5,279 walk-forward rows, 2010–11 to 2025–26) |
|---|---|---|
| b0, b_xg, b_g | 0, 1, 0 | 0.090, 0.346, 0.473 |
| home (log scale) | 0.045 | 0.064 |
| back-to-back, rest, travel, time zones | −0.06, +0.01, −0.01, −0.01 | −0.071, +0.020, −0.015, +0.018 |
| θ (correlation) | 0.08 | **0.0** (the grid's lower edge) |
| tie_k | 0.85 | **0.4** (the grid's lower edge) |
| k_pull, r_en, pull1, pull2 | 2.2, 0.22, 2, 3 | 2.5, 0.17, 2, 3 |
| k_ot 3-on-3, 4-on-4 | 1.85, 1.2 | 2.339, 1.566 |
| so_home | 0.5 | 0.488 |

`game.params()` reads the cache, else the committed fit, else the defaults; the site runs on
the committed fit. The 5,279 rows came from four seasons (2010–11, 2015–16, 2024–25,
2025–26) **rated on goals alone** (no derived events were on disk for them at 17:44; G^xg and
G^g were then both goals-model expectations), so b_xg and b_g split one signal and the fit
says nothing yet about the xG composition. Mean log-likelihood of the regulation score
−3.729 per game.

---

## 11. Live win probability: `live.py`

The rest of regulation is a Markov chain on the goal difference d (home minus away, −10..10)
in 10-second steps, with the game model's pre-game regulation means as the base rates, so
pre-game strength fades exactly as the clock runs down. Rates are μ/60 a minute × a
strength multiplier for the penalty time left: 5v4 or 4v3, the power-play side × 2.4
(`K_PP`) and the short-handed side × 0.3 (`K_SH`); 5v3, × 4.0 and × 0.2; 4v4 or 3v3, both ×
1.15. The late-game rules are the game model's (tie_k, pull1 / pull2, k_pull, r_en, from the
committed parameters), and an empty net reported now is honoured for the next minute
whatever the clock. At the end of regulation d > 0 is a home win, d < 0 an away win and d =
0 goes to the game model's overtime and shootout (playoffs: sudden death); in overtime the
remaining overtime time is used, in a shootout so_home. When only a pre-game P(home) is
known, symmetric means are solved for at a total near 6 goals (`means_from_p`).

`from_events` scores the state after every goal, penalty and faceoff of a game's events for
the game centre's chart. The working tree on 1 October 2026 carries an uncommitted change
(with `analytics/adapters.live_wp` and a test in `tests/nhl/test_models_c.py`): each state
keeps its own elapsed seconds, regular-season overtime runs 3,600 → 3,900 and playoff
overtime 20 minutes a period. Without the model the page falls back to
`analytics/games.wp_series`: independent Poisson goals over the remaining time at the
pre-game rates (`source` "poisson"; league goals 3.05 a game when no prices exist).

---

## 12. Season and playoff simulation: `season_sim.py`

20,000 simulations of the rest of the regular season (the build's `--sims`), vectorised in
chunks of 1,000 (`CHUNK`):

```
μ_h,s = μ_h,g · exp(+(x_s,h − x_s,a)/(2Ḡ)),   μ_a,s = μ_a,g · exp(−(x_s,h − x_s,a)/(2Ḡ))
x_s,t = z_s,t + Σ_{k ≤ w(g)} u_s,t,k,   z ~ N(0, (se_scale · se_t)²),   u ~ N(0, drift²) weekly
```

μ_g are the game model's regulation means (ratings with each team's usual starter, home
ice, rest, back-to-backs, travel, time zones), Ḡ the league goals per team-game, se_t team
strength's net-rating standard error. Scores come from `game.simulate_scores` (the same
bivariate-Poisson and empty-net process with six late sub-steps, then 3-on-3 overtime and the
shootout), so W, RW, ROW, points (2-1-0), GF / GA (the shootout winner credited a goal) and
head-to-head points are exact per simulation. Committed `season_sim_params.json`:
**se_scale 1.0, drift 0.035** goals a game a week; the scan on the backtest's mean log-loss
(playoffs, division, Cup) gave 0.3608 at 0.5, 0.3595 at 0.75 and 0.3555 at 1.0, so the
chosen value is the grid's upper edge.

**Tiebreakers**: `canon.TIEBREAK_STEPS` with the semantics of `canon.order_tied`; steps 1–4
(games played, RW, ROW, W) as one lexicographic key, then head-to-head (the odd game
excluded), goal differential and goals for on each still-tied group, a random draw last
(simulations only). 2010–11 to 2018–19: points, games played, ROW, head-to-head, goal
differential. The current standings are `canon.rank` itself.

**Playoffs**: from 2013–14 (not 2019–20, 2020–21) the top three of each division and two
wild cards a conference; the division winner with the better record plays the second wild
card; winners advance within the division bracket, then the conference final and the Cup
Final; home ice in every series to the better regular-season record. 2010–11 to 2012–13:
division winners seeded 1–3, five more by points, re-seeded each round. 2020–21: the
divisional format. Series best of seven, 2-2-1-1-1 (`PATTERN` "HHAAHAH"), the home side of
each game winning with probability logistic(logit P0[h, a] + k_po (x_h − x_a)), P0 the game
model's playoff win probability at the base ratings (clipped to 0.02–0.98) and k_po its
numerical slope in goals per game. Played playoff games are fixed; a series in progress
continues.

**Draft lottery** (the current format, verified 1 October 2026 from the 2026 NHL entry draft
page on Wikipedia and Yahoo Sports): the 16 non-playoff clubs in reverse order, first-draw
odds 18.5, 13.5, 11.5, 9.5, 8.5, 7.5, 6.5, 6.0, 5.0, 3.5, 3.0, 2.5, 2.0, 1.5, 0.5, 0.5%; two
draws; a club may move up at most ten places (a winner that cannot reach the pick moves up
ten and the pick goes to the best-placed remaining club); `lottery_matrix` enumerates both
draws exactly. The twice-in-five-years limit is not modelled.

**Magic numbers** (deterministic, points, tiebreaks assumed lost): magic_i = k-th largest
(P_j + 2R_j − P_i + 1) over rivals, tragic likewise; division k = 1, Presidents' Trophy
k = 1 (league); the playoff berth by sufficient conditions (clinched with a top-three
division place or at most four conference rivals able to reach the club; eliminated when
top three is lost and eight conference rivals are out of reach above). **Next-game odds**
are interventional (each simulation weighted by 1 / P(result | its strength draws)).
**Points ladder**: P(points ≥ N) for N = 50, 55, ..., 130 (`PTS_LADDER`) against Kalshi's
`KXNHLSEASONPTS` and Polymarket's ladders.

---

## 13. Awards and markets: `awards.py`, `sources/markets.py`

### 13.1 Awards

The Hart, Vezina, Norris, Calder and Selke by a **conditional logit** per award, P(i) =
exp(x_i b) / Σ_j exp(x_j b), features z-scored within the season's candidates, b by
ridge-penalised maximum likelihood (ridge 0.1) on the verified winners
(`award_winners.py`, 2009–10 to 2025–26, verified 1 October 2026 against the Wikipedia
trophy pages). Candidates and features: Hart, top 30 skaters by points + top 5 goalies by
GSAx (points, goals, team points %, value, a goalie's GSAx z); Vezina, goalies with 40% of
the team's games, top 20 by GSAx (GSAx, share of games, team points %, save %); Norris, top
25 defencemen by points (points, value, TOI, plus-minus); Calder, top 25 rookie skaters + top
5 rookie goalies (no earlier season of more than 25 games, age ≤ 26 on 15 September; points,
goals, defenceman, GSAx); Selke, top 50 forwards by points with 40% of games (defensive
value, plus-minus, points, centre). In season, counting features are projected to the end of
the season and utilities multiplied by (0.5 + 0.5 × share of the season played). The Art
Ross and Rocket Richard are simulated: the top 40 by projected total, remaining points
(goals) Poisson(rate × games left × 0.93), the rate shrunk to last season's with 20 games'
weight (0.55 points / 0.22 goals a game without last season); 20,000 draws; Ross ties to
more goals, Richard ties shared.

**Committed state**: `fitted/awards_fit.json` has **no fitted award** (`ok` false for all
five; the player seasons existed for 2 seasons, 15 missing). The 1 October build therefore
publishes no logit races ("award model not fitted") and no Ross / Richard race ("fewer than
20 games played and no previous-season rates on disk"); the awards page shows the
model-free boards (Hart GAR, Vezina GSAx, Norris defencemen's GAR, Calder rookie points,
Ross, Richard, Selke forwards' RAPM defence).

### 13.2 Markets

- **Prices**: the midpoint of a live two-sided quote, 0 < bid ≤ ask < 1 and ask − bid ≤
  0.12 (the Hardwood's rules, `basketball/sources/markets.py`); a last trade is never a
  price. Team field markets (Cup, conferences, divisions, Presidents' Trophy) are pooled
  across sources and published only when at least max(4, half the field) runners are
  accounted for and the implied total is within 0.8–1.3, then de-vigged multiplicatively.
  Award fields are de-vigged per source (implied total 0.8–1.3, or up to 1.6 with 20+
  quoted runners) and averaged. Two-way game markets are de-vigged across their two sides;
  Kalshi's spread, total and overtime ladders are published as quoted mids.
- **Games**: a card's `market` is the Kalshi / Polymarket probability when quoted, else the
  de-vigged store moneyline (sources ["line"]).
- **Edges** are model − market in probability; `index.json` lists gaps of 0.03 or more.

On the 1 October 2026 build (`20262027/markets.json`) every futures block had all 32 teams
(Cup, conference, division, Presidents' Trophy, playoffs), 252 points-ladder rows and 35
games, from Kalshi and Polymarket. These move every build.

---

## 14. Backtest and validation: `backtest.py` and the xG benchmark

### 14.1 Method

- **Games**: every regular-season and playoff game with a result in the seasons given
  (`fit_c.fit_all`: stores with at least 100 played games). Ratings by `game.walk_forward`
  (team strength refitted in 7-day blocks from that season's earlier games, the preseason
  prior chained from the season before the first). Coefficients for season S: `fit_means` on
  the walk-forward rows of seasons before S, the distribution shape refitted every third
  season (`_season_params`); with fewer than 600 earlier rows, `game.params()`.
- **Forecasters**: `model`; `xg_baseline` (logistic(a + b(xev_h − xev_a)) on 5v5 xG
  ratings, refitted each season on earlier ones; the goals-model net rating where a season
  has no xG); `elo` (FiveThirtyEight-style NHL Elo: K = 6, home ice 50, margin multiplier
  0.6686 ln(margin) + 0.8048 times 2.05/(0.001 ΔElo_winner + 2.05), playoff differences ×
  1.25, a third of the way back to 1505 between seasons, franchise-mapped, shootouts a
  one-goal margin); `market` (the store's closing, else current, moneyline, de-vigged).
- **Scores**: log-loss (p clipped to [10⁻⁴, 1 − 10⁻⁴]), Brier, 10-bin reliability; every
  forecaster also on the games with a closing line (`metrics_vs_market`); P(OT), P(home
  regulation win), the puck line (margin ≥ 2), totals against the closing total (pushes
  dropped) beside the market's own de-vigged over price, total RMSE.
- **Season odds**: checkpoints at each season's first regular-season game and after 60 and
  120 days, for completed wild-card-format seasons (not 2019–20 or 2020–21), with ratings
  and coefficients fitted strictly before; scored for the playoffs, division, Presidents'
  Trophy, conference champion and Cup.

### 14.2 Results as of 1 October 2026 (provisional; superseded by section 14.4)

**Expected goals against MoneyPuck on matched shots** (`calibration.json` `xg`, written by
the 1 October build):

| Season | Matched shots | Log-loss ours / MoneyPuck | AUC ours / MoneyPuck | Brier ours / MoneyPuck | Without empty nets (log-loss) |
|---|---|---|---|---|---|
| 2024–25 | 119,120 | **0.2099** / 0.2178 | **0.801** / 0.780 | 0.0573 / 0.0587 | 0.2067 / 0.2128 |
| 2025–26 | 118,438 | **0.2178** / 0.2223 | **0.789** / 0.778 | 0.0595 / 0.0602 | 0.2145 / 0.2167 |
| 2026–27 (to 1 Oct) | 617 | 0.2387 / 0.2368 | 0.765 / 0.772 | 0.0653 / 0.0650 | 0.2368 / 0.2351 |
| 2010–11 (30-game sample) | 2,488 | 0.2303 / **0.1926** | 0.720 / **0.835** | 0.0611 / 0.0524 | 0.2286 / 0.1915 |
| 2015–16 (30-game sample) | 2,468 | 0.2206 / **0.1842** | 0.720 / **0.829** | 0.0568 / 0.0490 | 0.2175 / 0.1813 |

**The caveat matters.** On 2024–25 and 2025–26 ours is **cross-fitted within the season on
only two seasons** (by game: every shot scored by a model that did not see its game, but
did see the rest of its season), while MoneyPuck's model was trained on earlier seasons,
so for MoneyPuck these are genuinely out-of-sample seasons. On 2026–27 both are out of
sample and the 617 shots are **about a tie** (ours 0.0019 worse in log-loss, a difference
far inside the noise of 617 shots). On the hand-tracked-era samples, where our production
model (fitted on two tracked seasons) is applied with the arena adjustment to scorer-recorded
coordinates, **MoneyPuck is clearly better**. Label agreement is 1.0 in every season. At the
team-season level summed xG correlates 0.974 (2024–25) and 0.988 (2025–26) with MoneyPuck's,
and with goals 0.890 against MoneyPuck's 0.862 (2024–25) and 0.946 against 0.943 (2025–26);
at the player-season level (629 and 649 shooters with 50+ matched attempts) 0.984 and 0.989
with MoneyPuck's, and with goals 0.939 against 0.921 and 0.939 against 0.928. The shot-level
correlation of the two xGs is 0.62–0.63 in the full seasons (0.94 on the 617 shots of
2026–27).

**Win probability** (`calibration.json` `game_model`, generated 21:45 UTC, 17:45 EDT, on
2010–11, 2015–16, 2024–25 and 2025–26, the history **rated on goals only**):

| Forecaster | All games: n, log-loss, Brier | Games with a closing line: n, log-loss |
|---|---|---|
| model | 5,432, **0.6842**, 0.2456 | 127, 0.6896 |
| Elo | 5,432, 0.6880, 0.2474 | 127, 0.6957 |
| xG baseline (goals net rating here) | 5,432, 0.6920, 0.2494 | 127, 0.6955 |
| closing moneyline | 127, **0.6510**, 0.2295 | 127, 0.6510 |

By season the model beat Elo in all four (2010–11 0.6861 v 0.6898; 2015–16 0.6863 v 0.6905;
2024–25 0.6792 v 0.6803; 2025–26 0.6854 v 0.6916). On the 127 games with a closing line
(63 of 2024–25 and 64 of 2025–26: the ESPN backfill had only then reached them) **the model
trails the market** by 0.039. Home teams won 53.3% of games; the model's mean P(home) was
0.536.

Regulation and totals: P(OT) log-loss 0.5406 (base rate 0.231, mean prediction 0.231);
P(home regulation win) 0.6724 (0.419 v 0.420); the home puck line 0.6138 (base 0.311, mean
0.302); totals on the 127 games 0.7059 against the market's own over price 0.6978; total
RMSE 2.278 against the closing total's 2.227.

**Season odds** (`season_sim`, **500 simulations** a checkpoint, 2015–16 and 2024–25 × three
checkpoints × 30–32 teams = 186 rows a target):

| Target | Base rate | Log-loss (all) | Day 0 / 60 / 120 |
|---|---|---|---|
| playoffs | 0.516 | 0.4993 | 0.6833 / 0.5113 / 0.3033 |
| division | 0.129 | 0.2804 | 0.3800 / 0.2847 / 0.1765 |
| Presidents' Trophy | 0.032 | 0.0906 | 0.1447 / 0.0846 / 0.0424 |
| conference champion | 0.065 | 0.2274 | 0.2282 / 0.2396 / 0.2146 |
| Cup | 0.032 | 0.1372 | 0.1307 / 0.1429 / 0.1379 |

These are small samples (two seasons) on goals-only ratings.

### 14.3 The refit after the backfill

The figures above will move once the full history is on disk. After the backfill finishes
(expected about 03:15 EDT on 2 October 2026; check `logs/nhl_backfill_nhl_{a,b}.log` and
`python scripts/nhl_fetch.py --report --from 2009 --to 2026`), on the owner's machine, from
the repository root:

1. **Builder B**: `python -m oddsmarkets.nhl.models.fit_b` (xG, stabilisation, the RAPM
   prior, the value model; exports to `models/fitted/`). With no arguments it fits **every
   season with derived events, the current one included**; to fit completed seasons only,
   pass 8-digit ids (`python -m oddsmarkets.nhl.models.fit_b 20092010 20102011 ... 20252026`;
   a 4-digit argument is read as the season's **end** year, section 16.2). With three or more
   seasons the xG model is cross-fitted by season and the arena adjustment applies to
   2009–10 to 2019–20.
2. **Builder C and the backtest**: `python -c "from oddsmarkets.nhl.models import fit_c;
   print(fit_c.fit_all())"` (team-strength carry-over, walk-forward rows, the game model,
   the award models, the se_scale scan, the backtest; writes `team_strength_params.json`,
   `game_params.json`, `awards_fit.json`, `season_sim_params.json` and
   `docs/rink/data/calibration.json`'s `game_model` and `season_sim`). Seasons are the
   stores with 100+ played games; `last=` stops at a season.
3. **`python scripts/nhl_fit.py`** refits builder B on the completed seasons
   (`--through`, default the last completed season) and exports; its builder C half does
   nothing today (section 16.2). It is the safe way to repeat step 1 with the current season
   excluded.
4. **Rebuild**: `python scripts/build_rink.py --force` (with the deployed payloads restored
   under the local ones; RUNBOOK section 6), which refreshes the xG benchmark blocks of
   `calibration.json`; then commit the fitted files and `calibration.json`, update this
   section and the Methodology (`docs.js`), and hand-deploy past seasons (RUNBOOK sections 5
   and 6).

### 14.4 Results after the full-history refit (2 October 2026)

From `docs/rink/data/calibration.json` (`game_model.generated_at` 2026-10-02T10:11:25Z; the committed fits it
reports under `fitted`). Read on 15 October 2026.

**Expected goals.** The committed model is fitted on 17 seasons (2009–10 to 2025–26), **cross-fitted by season** (each
season scored by a model that never saw it): 1,863,253 unblocked attempts, log-loss 0.2101 against a base rate of
0.2467, AUC 0.782, Brier 0.0565, predicted goals 125,513 against 125,502; mean best iteration 674, Platt (0.0262,
1.0119). Gain importance: distance 0.416, |y| 0.143, shot type 0.081, rebound angle 0.060, seconds since the previous
event 0.050. Against MoneyPuck's xGoal on the same matched shots:

| Season | Matched shots | Log-loss ours / MoneyPuck | AUC ours / MoneyPuck | Team-season r with goals, ours / MoneyPuck |
|---|---|---|---|---|
| 2009–10 | 109,874 | 0.2071 / **0.1945** | 0.778 / **0.808** | **0.894** / 0.870 |
| 2012–13 | 65,797 | 0.2016 / **0.1900** | 0.786 / **0.814** | **0.858** / 0.844 |
| 2015–16 | 109,085 | 0.2001 / **0.1891** | 0.791 / **0.817** | **0.869** / 0.858 |
| 2018–19 | 117,055 | 0.2111 / **0.2042** | 0.782 / **0.797** | **0.855** / 0.828 |
| 2021–22 | 120,853 | 0.2192 / **0.2109** | 0.779 / **0.798** | **0.905** / 0.904 |
| 2023–24 | 121,938 | 0.2165 / **0.2138** | 0.782 / **0.791** | 0.938 / **0.944** |
| 2024–25 | 119,120 | 0.2186 / **0.2178** | 0.774 / **0.780** | **0.883** / 0.862 |
| 2025–26 | 118,438 | 0.2254 / **0.2223** | 0.764 / **0.778** | 0.942 / **0.943** |
| 2026–27 (to 15 Oct) | 8,651 | 0.2372 / **0.2262** | 0.748 / **0.785** | 0.711 / 0.707 |

(every season is in the file; the others follow the same pattern). **MoneyPuck's xG is better shot by shot in every
season**, by 0.001–0.013 in log-loss and 0.006–0.03 in AUC; on 2026–27, out of sample for both, the gap is 0.011 on
8,651 shots. MoneyPuck's model was trained on the earlier seasons, so those seasons are in sample for it and out of
sample for ours; 2026–27 is the fair comparison and it favours MoneyPuck. Summed to team-seasons, our xG correlates
with goals at least as well as MoneyPuck's in 12 of 17 seasons. The launch reading (section 14.2: ours ahead on
2024–25 and 2025–26) came from within-season cross-fitting on two seasons and does not survive the refit.

**Win probability.** Walk-forward, 2009–10 (warm-up) to 2025–26:

| Forecaster | All games: n, log-loss, Brier | Games with a closing line (2019–20 on): n, log-loss |
|---|---|---|
| model | 21,910, **0.6728**, 0.2401 | 9,153, 0.6673 |
| xG baseline | 21,910, 0.6746, 0.2409 | 9,153, 0.6702 |
| Elo | 21,910, 0.6755, 0.2414 | 9,153, 0.6711 |
| closing moneyline | 9,153, 0.6612, 0.2345 | 9,153, **0.6612** |

The model beats Elo in 14 of 17 seasons (not 2009–10, the warm-up; 2010–11, by 0.0002; 2012–13, the lockout season)
and trails the closing line in 6 of the 7 seasons with lines (2019–20 is level: 0.6794 against 0.6796); overall it
trails the line by 0.006 on 9,153 games. Home teams won 54.1 %, the model's mean P(home) 0.545. Regulation and
totals: P(overtime) log-loss 0.5410 (base 0.231, mean prediction 0.234); P(home regulation win) 0.6667; the home puck
line 0.6096 (base 0.314, mean 0.308); the model's over on 8,941 games with a closing total 0.6068, the market's own
over price 0.6867 on 8,581 (the model 0.6169 on the same games); total-goals RMSE 2.316 (the market line's figure
in the file, 44.4, is not a plausible RMSE: open item 23).

**Season odds** (1,000 simulations a checkpoint; checkpoints at day 0, 60 and 120 of the completed wild-card-format
seasons; 1,026 team-checkpoints): playoffs log-loss 0.421 (base rate 0.515; day 0 / 60 / 120: 0.581 / 0.396 /
0.285), division 0.265 (base 0.129), Presidents' Trophy 0.091 (0.032), conference champion 0.199 (0.064), Cup 0.119
(0.032). The se_scale scan now picks 0.75 from 0.5–1.5 (log-loss 0.3024), inside its grid.

**Fitted state** (`fitted`): team-strength carry-overs fitted (5v5 offence 0.724, defence 0.744, power play 0.718,
penalty kill 0.556, finishing 0.439, goalies 0.574: no longer the defaults); game model on 21,225 rows: b_xg 0.408,
b_g 0.602, home 0.081, back-to-back −0.073, θ 0.0 and tie_k 0.1 (both still at the lower edges of their grids,
item 17), k_pull 2.0, r_en 0.12, k_ot 2.366 / 1.302, so_home 0.496; Rink value's box prior on 11,466 player-seasons
(2010–11 to 2025–26), R² 0.560 offence and 0.063 defence, Pythagorean x 2.1; award logits fitted for all five
trophies (Hart top-1 9 of 17 seasons, Vezina 11 of 17, Norris 6 of 17, Calder 11 of 16, Selke 0 of 13).

**Totals in this section were wrong** (corrected in section 14.5): the 0.6068 / 0.6169 against 0.6867 and the RMSE
44.4 came from a line-parsing bug, not from the model.

### 14.5 Model-improvement program (21 October 2026)

Full write-up, experiment log and edge backtest: `docs/research/nhl_edge.md` (code `scripts/nhl_edge.py`). Split
fixed before reading any test number: warm-up 2019–20, dev 2020–21 to 2022–23, sealed test 2023–24 to 2025–26
(4,190 games with a closing line); CIs are paired, bootstrapped by game day.

**Totals fix (items 23 and the 14.4 totals).** On 2 October some 2022–23 ESPN captures carried a price (−110) in the
total-line field; `_cdata.line_fields` was fixed on 3 October (a total outside 3–12 falls back to the main line) but
`calibration.json` was not regenerated, so the site published a model that "beat" the market on totals by 0.07
log-loss and a market RMSE of 44.4. `calibration.json`'s `game_model` block was regenerated on 21 October with the
current code and the committed fits (`backtest.write_calibration` now keeps the season-odds block on a games-only
refresh; season odds unchanged). Moneyline and puck-line numbers are unchanged. Corrected totals, 2019–20 to 2025–26:

| | n | log-loss | Brier | mean P(over) / base rate |
|---|---|---|---|---|
| model, P(over the closing total) | 8,932 | 0.6938 | 0.2503 | 0.478 / 0.501 |
| market's de-vigged over price | 8,574 | **0.6912** | 0.2490 | 0.502 / 0.501 |
| model on the same 8,574 games | 8,574 | 0.6939 | 0.2504 | |
| total goals RMSE: model's expected total / the closing line | 8,932 | 2.318 / 2.332 | | |

The market's over price is better than the model's; the model's P(over) is also over-dispersed (calibration slope
0.29 on the test seasons) and leans to the under.

**Before (production) against the prices, test seasons.** Moneyline: 0.6703 against the close's 0.6645 (+0.0058
[+0.0030, +0.0086]; Brier +0.0027 [+0.0014, +0.0041]); at 08:00 ET with the expected starter, 0.6707 against ESPN's
open 0.6675 (+0.0032 [+0.0008, +0.0055]) and, on 1,475 games of 2025–26, 0.6847 against Kalshi's mid 0.6795
(+0.0052 [+0.0006, +0.0097]). Calibration intercept / slope −0.040 / 1.135. Puck line against the market +0.0049
[+0.0017, +0.0083]; totals +0.0031 [+0.0005, +0.0056].

**What was tried, and why nothing was promoted.** Team ratings implied by past closing lines (ridge on the de-vigged
closing logit, half-life 60 days), net or not of the starting goalie; walk-forward Platt scaling and logistic stacks
with Elo; the skaters who dressed (known at puck drop: the share of a team's usual ice time missing, and the change in
TOI-weighted points and on-ice xG rates); offset stacks that keep the model's own calibration; for the puck line and
totals, Platt scaling, the stacked moneyline and past closing totals as team pace ratings. Every variant helped on the
dev seasons (up to −0.0072 log-loss) and none on the test seasons: the best, model + lineup + market ratings with the
model's logit as an offset, is −0.0010 [−0.0036, +0.0016] (calibration +0.013 / 1.003), closing 17% of the gap to the
close, not significantly. The dev seasons were unusual (COVID absences, a no-fans 2020–21; the model's calibration
slope 1.6 there against 1.13 on the test seasons), and the free stacks learnt that era and were over-confident on the
test seasons (slopes 0.76–0.82). The site's game model is therefore unchanged.

**Item 17 resolved (no change).** The regulation-score likelihood is flat in tie_k from 0.1 to 0.4 (0.0006 a game on
4,000 games); 0.2–0.4 reproduce the observed regulation-tie rate (22.7%); 0.1 is the noise of `fit_shape`'s 4,000-game
subsample, not a boundary. θ = 0 is the bivariate Poisson's own boundary (it cannot correlate negatively); θ = 0.04 is
worse by 0.0009 a game.

**Edge backtest** (`scripts/edge_backtest.py`, quarter-Kelly, shrinkage on): no edge; every market loses to the
closing line (all markets CLV −2.80% [−4.53, −1.91], ROI −6.67% [−13.91, −1.12], 439 bets; the moneyline has 19 bets
because the fitted weight on the model is negative).

### 14.6 Round 3: starting goalies and totals (22 October 2026)

Write-up: `docs/research/nhl_edge.md`, "Round 3" (code `scripts/nhl_edge_r3.py`; sources `docs/research/data_sources.md`).

- **Probable starters, captured from now on.** ESPN's scoreboard lists each team's probable starting goalie
  ("Expected", then "Confirmed"); `nhl_fetch.py`'s ESPN phase keeps every pre-game read in `GAME.probables` (goalie,
  NHL id when the name maps, first seen, first confirmed, each change with its time). No historical timestamped source
  exists (NHL api-web has no starter before puck drop; Daily Faceoff and NHL.com forbid scraping; ESPN rewrites the
  field after the game). Upcoming games are now priced with the listed starter (`adapters._starter`), and the game page
  shows it and its effect against each team's usual starter (`pregame.model.goalie_effect`). On 256 archived pre-game
  scoreboards ESPN's "Expected" starter was right 78% of the time and "Confirmed" 98%, against 61% for the previous
  default (the most frequent recent starter).
- **Goalie terms: nothing promoted.** A walk-forward starter model (mixture or its pick) changes test log-loss by
  -0.0002 / +0.0000; even the actual starters, known at 08:00, gain only -0.0001 [-0.0006, +0.0004]: the gap to the
  close is not the starter as this model values goalies.
- **Totals: nothing promoted.** Fitted on the final totals, the score model needs no extra game-level variance
  (sigma -> 0) and a 4-11% narrower spread of expected totals; that improves P(over) on the test seasons by -0.0005
  [-0.0011, +0.0001], slope 0.29 -> 0.32: not significant. The P(over) slope problem comes from the closing line
  holding information the model lacks, not from the score distribution.

---

## 15. Known limitations

(Item 1 below describes the state before the refit; see section 14.4 for the refitted numbers.)

1. **The fits are provisional** (1 October 2026): two tracked seasons for xG, goals-only
   ratings for the game model, an unfitted award model, default team-strength carry-overs;
   section 14.3.
2. **The closing line is sharper than the model**, as it should be: it knows confirmed
   starting goalies, injuries and money. Starters are an input, often confirmed only on the
   morning of a game.
3. **Hockey is close to a coin flip**: forecasters differ in the third decimal of log-loss;
   one or two seasons of comparison cannot separate them reliably.
4. **Hand-tracked locations** before 2020–21 are arena-adjusted by quantile matching, which
   removes systematic distance bias, not individual errors; on those seasons MoneyPuck's
   model is clearly better than ours as fitted on 1 October.
5. **Shift data starts in 2010–11**, and 2019–20's shift charts agree with the situation
   codes on only 95.6% of events.
6. **Goaltending and finishing are noisy**: one season of GSAx or GAx is mostly noise and is
   shrunk before ranking (k in the thousands of attempts for save % and GSAx).
7. **RAPM** separates teammates only as far as coaches mix them; read it with its standard
   error.
8. **Scorer-recorded events** (hits, giveaways, takeaways, blocks) vary by arena and are not
   adjusted.
9. **Simulations** hold team strength to a random walk and use each team's usual starter;
   no injuries, trades or call-ups beyond what the ratings show.
10. **Hand-entered tables** (arenas, divisions, formats, the tiebreak procedure, lottery odds,
    award winners, the Cup champions before 2009–10) are checked but static.

---

## 16. Where the code and other texts disagree (open)

Found on 1 October 2026 while writing these documents. **None of these has been changed**:
these documents were written without editing the code or the site. Items 1–11 are the
site's Methodology (`docs/rink/assets/js/docs.js`) and glossary against the code and the
committed fits; 12–22 are docstrings, scripts, contracts and state. Each item says what
the text says, what the code holds, and a suggested resolution.

### 16.1 The Methodology and glossary against the code

1. **Team-strength half-life.** The Methodology says "half-life H = 110 days"; the code's
   default and the committed fit are **300 days** (`team_strength.DEFAULTS`,
   `team_strength_params.json`). Suggested: quote 300 days.
2. **Team-strength carry-over for goals.** The Methodology lists "goals 0.5"; the code and
   the committed file carry `g_att` and `g_def` at **0.75**. The other carry-overs (5v5 0.6,
   shots 0.65, PP 0.45, PK 0.4, penalties 0.5, finishing 0.35, goalies 0.7) match.
3. **Game-model constants.** The Methodology states the late-game rules as fact with the
   code defaults ("tied, both rates × 0.85", goalie pulled "× 2.2, the leader adds 0.22",
   k_ot "1.85 at 3-on-3 and 1.2 at 4-on-4", shootout "won by the home side half the time")
   and gives the defaults "before the walk-forward fit". The site runs on the committed fit:
   tie_k 0.4, k_pull 2.5, r_en 0.17, k_ot 2.339 / 1.566, so_home 0.488, θ 0.0, home 0.064,
   b_xg 0.346, b_g 0.473, schedule −0.071 / +0.020 / −0.015 / +0.018 (section 10.3). The live
   section repeats "tied: both × 0.85" (live WP uses the committed 0.4). Suggested: quote the
   committed fit after the refit, as the Gridiron's Methodology now does.
4. **xG cross-fitting.** The Methodology and the glossary say the model is "cross-fitted by
   season (five folds: each season predicted by a model that never saw it)" and "no shot is
   scored by a model that saw it". With fewer than three seasons `_io.fold_ids` folds by
   game, and the committed fit has two seasons: each shot's own game is held out, the rest
   of its season is not. Suggested: state the rule (by season with three or more seasons, by
   game otherwise) and which applies to the committed fit; after the refit on the full
   history the by-season description becomes true.
5. **xG features.** The Methodology's feature list omits `hand_y` (the shooter's
   handedness × y; 3.2% of the gain) and the separate empty-net logistic. The glossary lists
   "an arena adjustment for scorer bias" without saying it applies only before 2020–21.
6. **Stabilisation constants quoted as defaults.** The shooting section says finishing's k
   "is in the thousands of attempts (the default before fitting is 1,500)"; the committed fit
   is **783.6** attempts (n₀.₇ 1,828). The stabilisation section's list (finishing 1,500,
   shooting % 375, save % 2,000, GSAx per attempt 1,200, faceoff % 140, points / 60 400
   minutes, xGF% 500, GF% 1,500) is labelled "defaults before a fit", but the site's
   percentiles and shrinkage use the committed values (80.9, 9,261, 2,980.5, 87.1, 174 min,
   405 min, 2,106 min; section 8). Suggested: quote the committed table (it moves at the
   refit).
7. **Catalogue sizes.** The Methodology says skaters and goalies are rated on "about 120
   and 40 metrics" (the `skaters.py` docstring "~120"); the payloads carry **138** skater and
   **45** goalie metrics.
8. **The backtest's market window.** The Methodology, the calibration page's header
   comment (`calibration.js`: "ESPN's DraftKings and other books, 2023–24 on"),
   `backtest.py`'s docstring and `CONTRACT.md` say the closing moneyline is used from
   2023–24. `_cdata.line_fields` reads the close block, **else the current line**, which the
   ESPN fetch reads after the game, so every game with ESPN lines from **2019–20** counts.
   On 1 October only 127 games had lines at fit time; after the refit the market comparison
   will span 2019–20 to 2025–26 (9,153 games with lines on disk). Suggested: say "ESPN's closing line
   (2019–20 on; opening and closing blocks from 2023–24)".
9. **Season-odds sample.** The Methodology and `backtest.py` say "1,000 simulations each"
   and "completed seasons 2013–14 to 2025–26"; the committed `calibration.json` has
   `n_sims` **500** and two seasons (2015–16, 2024–25), because only those stores were on
   disk. `fit_c.fit_all` passes 1,000 to the backtest (its se_scale scan uses 500), so the
   refit should restore 1,000; check `n_sims` afterwards.
10. **Award races.** The Methodology describes the conditional logit trained on 2009–10 to
    2025–26 as running; `awards_fit.json` has no fitted award and the build publishes no
    race (section 13.1). It does say "until the model answers, the awards page ranks each
    trophy's usual criteria", which is what the site shows. The glossary's value entry lists
    faceoffs as a component; `value.py` uses them only through the box prior.
11. **Tracking era.** The Methodology and the Limitations say "from 2020–21 the NHL's puck
    and player tracking records locations" (`_io.TRACKING_FIRST` = 20202021), while
    `canon.EDGE_FROM` is 2021–22 and EDGE answers 404 for 2020–21. Which season first has
    tracked shot locations decides whether 2020–21 is arena-adjusted; worth confirming
    before the refit.

### 16.2 Docstrings, scripts, contracts and state

12. **Season-id helpers disagree on a 4-digit year.** `_io.sid(2026)` → 20252026 (an **end**
    year), while `canon.norm_season(2026)`, `_cdata.sid(2026)` and `nhl_fetch.py --from 2026`
    give 20262027 (a **start** year). `python -m oddsmarkets.nhl.models.fit_b 2025` therefore
    fits 2024–25. Suggested: one convention (start year, as everywhere else), or reject
    4-digit input in `_io.sid`.
13. **Season turnover date.** `canon.current_season` turns over on 1 July; `_cdata.
    season_of_date`, `sources/markets.season_for` and the analytics layer's fallback
    (`analytics.current_season`, whose docstring says "from August") turn over on 1 August.
    In July the markets module would ask for the previous season's events.
14. **`scripts/nhl_fit.py`'s builder C half is a no-op.** Its docstring says builder C's
    models are exported through `export_fits` or `fit_and_save` / `fit_params` +
    `save_params(committed=True)`; none of `team_strength`, `game`, `live`, `season_sim`,
    `awards`, `backtest` has `export_fits`, `fit_and_save`, `export` or `fit_params` (only
    `game.save_params`), so every C step is reported as skipped. Builder C's committed fits
    and the backtest come from `fit_c.fit_all()` alone. Suggested: have `nhl_fit.py` call
    `fit_c.fit_all(committed=True, last=through)` for `--only c`.
15. **`fit_b` run as a module includes the current season.** `fit_b.fit_all(None)` uses
    every season with derived events (`_io.season_range`), the current one included;
    `nhl_fit.py` stops at the last completed season. `value.json` lists 2026–27 among its
    seasons for the same reason (`value.box_model` pools every season with stints).
16. **First backtest season in sample.** `backtest._season_params` prices a season with fewer
    than 600 earlier walk-forward rows with `game.params()`, which inside `fit_c.fit_all` is
    the just-saved fit on **all** seasons, including the one being scored. On 1 October that
    was 2010–11 (1,319 games, log-loss 0.6861). Suggested: use `game.DEFAULTS` there.
17. **Grid edges.** The committed game fit put θ (0.0) and tie_k (0.4) on the lower edges of
    their grids, and the se_scale scan chose its upper edge (1.0); widen the grids at the
    refit if they stay there. *Resolved 21 October 2026 (section 14.5): the grid was widened to 0.1 and tie_k still
    lands there, but the likelihood is flat from 0.1 to 0.4 and the pick is subsample noise; θ = 0 is the model's own
    boundary. No change.*
18. **Team-strength carry-overs not fitted.** `fit_carryover` needs 40 franchise pairs a
    unit; with one pair of consecutive seasons the committed file equals the defaults
    (section 9). The full history fixes this.
19. **`CONTRACT.md` and canon.** `CONTRACT.md` describes the game model as "bivariate /
    negative-binomial or Poisson with correlation" (it is bivariate Poisson with a late-game
    chain, and the fitted correlation is 0); it says divisions were verified to 2026–27 where
    canon's docstring says 2025–26; `canon.ESPN_OPEN_CLOSE_FROM` is 2023–24 while 1,288 games
    of 2022–23 carry open and close blocks.
20. **Committed data.** `.gitignore` and `update_rink.yml` say completed seasons' stores and
    `calibration.json` are committed by hand; on 1 October none was (`docs/rink/data/` is
    wholly untracked). Commit them after the backfill and the refit (RUNBOOK section 5).
21. **Coverage report.** `nhl_fetch.report` counts shifts by plain marks only and misses the
    57 games of 2024–25 rebuilt from the HTML reports (it shows 1,341 of 1,398).
22. **Uncommitted working-tree change.** `models/live.py`, `analytics/adapters.py` and
    `tests/nhl/test_models_c.py` (the overtime elapsed time of the win-probability series,
    section 11) were modified but not committed at the time of writing.

### 16.3 Found on 15 October 2026

23. **Total-goals RMSE of the market line.** `calibration.json` `game_model.total_rmse.line` is 44.38 on 8,941 games
    (the model's 2.316): not a plausible RMSE of a closing total; probably a unit or matching problem in
    `backtest.py`'s totals block. Not investigated. *Resolved 21 October 2026 (section 14.5): a line-parsing bug
    (prices read as total lines in some 2022-23 ESPN captures), fixed in code on 3 October; `calibration.json`
    regenerated. The closing total's RMSE is 2.332, the model's 2.318.*
24. **Launch xG claim.** The memory note and section 14.2's reading that our xG beats MoneyPuck held only for the
    two-season, within-season cross-fit; after the refit MoneyPuck is ahead in every season (section 14.4).

---

## 17. Player value, team needs and the trade simulator: `analytics/value.py`

Built 15 October 2026 to the shared spec (`docs/VALUE_SECTIONS.md`); pages in [DASHBOARD.md](DASHBOARD.md) section 3.11,
payloads in `oddsmarkets/nhl/PAYLOADS.md` "As built".

### 17.1 Currency and leaderboard (`season_value`)

Rink value (section 6) as is: GAR and WAR from the catalogues (`skaters.json`, `goalies.json`), the rate GAR per 60,
the six parts of a skater's GAR, goalies ranked separately. Percentiles of WAR against the season's qualified players
(the catalogues' `qualified`: skaters 250 5v5 minutes per 82 team games, prorated; goalies a quarter of the team's
minutes), and within the position (C, LW, RW, D, G; 3+ qualified). Trend: ΔGAR per 60 against last season and last
season's WAR. Goals per win shown on the page = GAR / WAR read back over players with |WAR| ≥ 0.5 (20 needed; else
last season's): 5.86 for 2025–26. Best at each position: the top ten qualified by WAR with the two largest parts of
GAR (goalies: GSAx and save %). 2025–26: MacKinnon 3.28 WAR, McDavid 3.14 (C); Hagel 2.59 (LW); Caufield 2.62 (RW);
Hughes 2.86, Hutson 2.70 (D); Logan Thompson 8.14 (G).

### 17.2 Rest-of-season projection (`player_projection`, `projections`)

```
rate = (GAR_this + 0.7 × GAR_last) / (TOI_this + 0.7 × TOI_last + K) × 60      K = 300 min skaters, 1,500 goalies
parts of GAR likewise;  0.7 = the RAPM prior's carry;  K = replacement-level minutes (GAR 0)
skater minutes a game = (TOI_this + 10 × TOI_last / GP_last) / (GP_this + 10)
goalie minutes a game = 60 × (share_this × team GP + share_last × 10) / (team GP + 10),  share = his minutes / team minutes
next season = rate + aging(age)
```

Rosters: the store's players (their `team` is today's). 2026–27 (15 Oct): 809 rostered players.

**Aging** (`aging_curve`): the delta method on every pair of consecutive seasons on disk (current season excluded):
players with 400+ minutes in both (goalies 1,000+), weight = the harmonic mean of the two seasons' minutes, the
weighted mean change in GAR per 60 at each age (age in the first season, rounded), minus the all-ages mean change,
shrunk by W / (W + 20,000) (goalies 300,000), then a 1-2-1 weighted smoothing over neighbouring ages. Skaters:
+0.035 a 60 at 20, +0.014 at 23, 0.000 at 26, −0.007 at 29, −0.006 at 32, −0.018 at 35. Goalies: within ±0.025.

### 17.3 Depth chart (`baseline_minutes`, `team_value`, `apply_moves`)

Budgets per team game: forwards = the league's forward minutes per team game in last season's catalogue (181.0 for
2025–26), defence likewise (116.7), goalies 60; caps per player 22 (F), 26 (D), 60 (G). Baseline: projected minutes
handed out most first within each group; shortfall at replacement (GAR 0). Team value = Σ rate × minutes / 60 (goals
a game above replacement; also by part of GAR). A trade: outgoing minutes open at the position; incoming players
(best rate first) take their minutes from open minutes at their position, then the lowest-rated minutes there (the
group's replacement fill counts as a 0 there), then the neighbours (C ↔ LW ↔ RW; D and G none), never from a player
rated at or above them; a goalie takes max(his minutes, the minutes of every goalie he outrates + open + fill), so a
better goalie starts. Leftover open minutes go to the best remaining players at the position, each at most
`EXTRA` more (4 minutes for forwards, 5 for defence, all 60 for a backup goalie) and up to the cap, then the
neighbours, then replacement. The same algorithm is `docs/rink/assets/js/trade.js` `applyMoves`: 300 random trades
on the 15 Oct payloads agree to 3e-14.

### 17.4 Grades, strengths and needs

Per club: C, LW, RW, D, G, and the 5v5 offence, 5v5 defence, power-play and penalty-kill parts of GAR, each as
projected GAR over a full season, placed against the 32 clubs (A ≥ 80th percentile, B ≥ 60, C ≥ 40, D ≥ 20, F
below); three strengths and three weaknesses with evidence (flagged `relative` when a strength is below the median or a
weakness above it). Targets: players on other clubs with 8+ projected minutes
(defence and goalies 10+) and a value basis, at that position (a unit: any skater, ranked by that part), added with
nobody going back; ranked by the gain (> 0.002 goals a game); the top five plus up to three more marked attainable;
points from the club's `exp_pts` sensitivity curve, Δ playoff and Cup odds, and goals over the games left. Hints:
seller below 15 % to make the playoffs; seller's Δ from losing him above −0.5 × his gain (depth); one of the seller's
two most valuable (rate × minutes); age 32+ with the aging step (when it is at least 0.005 a 60). No salaries (no
free legitimate source: not CapFriendly, PuckPedia or Spotrac): the cap is not checked; free agents are not identified.

### 17.5 Sensitivity curves (`season_sim.sensitivity`, `value.sensitivity_curves`)

`simulate(..., state={"shift": {abbr: d}})` adds d (goals a game, net) to that club's season-level draw z, which
scales its remaining games' goal rates by exp(±(d)/(2 Ḡ)) and moves its playoff series through k_po. `sensitivity`
runs the season at `SENS_SHIFTS` = (−0.75, −0.4, −0.15, 0, +0.15, +0.4, +0.75) for each club alone, `SENS_SIMS` =
1,000 runs a point, seed = season mod 100000 + 1 (common random numbers), sharing the state, game means, playoff
matrix and current order through `state["_cache"]`; outputs exp_pts, p_playoffs, p_div, p_conf, p_cup, p_first,
p_top2, made monotone outward from 0 and cached under `cache/analytics/value/` on the simulation's inputs (reused for up
to `SENS_TTL_HOURS` = 6 when only results or ratings have moved). About 1.1 s
a run: 3.7 minutes for 32 clubs on a cache miss (the Rink build was 12–13 minutes; limit 40). Example (15 Oct 2026):
a first run on a ±0.5 grid gave Colorado +0.1 goals a game → 110.6 to 112.7 expected points and San Jose +0.1 → playoffs 8.8 % to 11.7 %.

### 17.6 Tests

`tests/nhl/test_value.py` (12): season value, percentiles, floors and best by position; goals per win; the aging curve
recovering a planted decline; the projection's pooling, shrinkage and minutes (skaters and goalies); group budgets
and caps; centre swaps and displacement; defence never displacing forwards, wings covering centres; a better goalie
taking the starts; next player up and replacement; grades and targets with hints; interpolation and monotone curves;
the simulation's shift and sensitivity on a synthetic league.

## 18. Valuation v2 (multi-season): `analytics/valuation.py`

Built 16 October 2026 to `docs/VALUE_SECTIONS.md` section 4; payload `data/<S>/valuation.json` (PAYLOADS.md "As built"),
page `#/value?tab=val` (`valuation.js`), a line on the player page.

```
V = Σ_{k=0..3} 0.9^k × S_k × r_k × m × a × n_k / 60 / gpw          (WAR; k = 0 the rest of this season)
r_0 = value.py rest-of-season GAR per 60;  r_k = r_{k-1} + aging(age + k - 1)
m   = projected minutes a game (goalies: share of team goalie minutes × 60, so a = 1)
a   = (GP_this + GP_last + GP_2ago + 30 × A0) / (team games of the seasons he appeared in + 30),  A0 = 0.786
      this season × (games left − games an injury costs) / games left
n_k = games left this season, then canon.games_per_team (84)
S_k = Π_j s(age + j, r_j, m),  s = logistic(1, (age−27)/5, ((age−27)/5)², 4r (goalies r), m/20 (goalies m/60))
```

Fits (cached on the value payloads, `<cache>/analytics/valuation/fits.json`; numbers from 2010–11 to 2025–26):

| | skaters | goalies |
|---|---|---|
| noise σ² (per 60 minutes) | 0.0723 | 2.374 |
| true spread τ² | 0.0188 | 0.0078 |
| drift δ² a season | 0.0198 | 0.135 |
| half-signal minutes 60σ²/τ² | 231 | 18,211 |
| season pairs | 9,421 | 913 |
| minutes CV (log change, regulars) | 0.356 | 0.442 |
| survival base / log-loss (v base) | 83.5 % / 0.367 (0.449) | 83.1 % / 0.365 (0.455) |
| mean share of team games (regulars) | 0.786 | 0.442 |

σ² and δ² from WLS of E[(r₂ − r₁ − aging)²] = σ²(60/T₁ + 60/T₂) + δ² on 15 quantile bins of pairs with 100+ minutes
(goalies 300+); τ² = the minute-weighted covariance of r₁ and r₂ for 400+ minutes in both (goalies 1,000+). Survival
regulars: GP ≥ 25 % of team games (goalies 12 %); coefficients (skaters) −1.742, −0.267, −0.206, 0.814, 4.614. Observed v
fitted survival by age (skaters): 0.90 / 0.87 at 20, 0.85 / 0.86 at 27, 0.81 / 0.80 at 32, 0.67 / 0.68 at 36, 0.53 / 0.60 at 38.
The goalie drift is larger than the goalie talent spread: year-to-year changes in goalie GAR are mostly not explained by
the minutes (team defence, shot quality xG misses), so goalie bands are wide.

Band: 400 Monte Carlo careers (seed 20261016, common across players): r_0 ~ N(r_0, se²), se² = 1/(1/τ² + T_eff/(60σ²)),
T_eff = this season's minutes + 0.7 × last season's; each later season adds aging + N(0, δ²); log(m a) a random walk with
step MIN_CV (this season's scaled by √(share of the season left)); survival draws. p10 / p50 / p90 of the discounted total;
the point value is the analytic expectation.

Positional replacement (pooled 2023–24 to 2025–26): top N by TOI per position = the position's share of the top 13 F /
7 D / 2 G per team. Replacement GAR per 60: C +0.007, LW +0.004, RW +0.032, D −0.001, G +0.011; starters C 0.136, LW 0.146,
RW 0.146, D 0.083, G 0.323; scarcity (gap / skater gap 0.111): LW 1.28, C 1.17, RW 1.03, D 0.76. Injury: ESPN status and
return date (games before the return); no date: day-to-day 1, out 3, IR 7, LTIR 25, suspension 2. 2026–27 (16 Oct): 819
rostered players; 89 of 131 ESPN injury rows matched (the rest are minor-league or non-roster players). Top: MacKinnon 7.6
WAR, Hutson 7.2, McDavid 7.0 (skaters); goalies run higher on Rink value's goalie WAR (Logan Thompson 15.9).

**As of a date** (`AsOf`, for the trade ratings): rates from the value payloads of seasons completed before the date only
(the date's valuation season = the season starting that autumn from 1 July), aged one season; minutes and availability
from the game logs before the date blended with the last completed season (10 games); team games left after the date
from the season's store. Model parameters (ageing, survival, reliability) are fitted on all completed seasons (a stated
exception). Tests: `tests/nhl/test_valuation_fantasy.py`, `tests/nhl/test_moves.py::test_at_the_time_value_has_no_hindsight`.

## 19. Transactions, deals, trade grades and the pick-value curve: `analytics/moves.py`

Source and parsing in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 2.9; payloads `transactions.json`, `deals.json`;
page `#/moves` and the team page's Ledger (`moves.js`).

- **Clauses**: sentence split (protecting "St.", "N.Y.", "No.", initials, "Jr."); types trade, signing, claim, waivers,
  release, recall/assignment, injured reserve, other. 16 Oct 2026 (12 months): 2,437 clauses: 1,199 recall/assignment,
  615 injured reserve, 261 signings, 154 trade sentences, 150 waivers, 15 claims, 4 releases, 39 other.
- **Names**: 3,023 names in clauses, 2,920 matched (103 unmatched, none in trades: minor-league players with no NHL record;
  never guessed). Trades: 164 of 164 players matched (those the local lists miss through the NHL's player search).
- **Deals**: 154 trade sentences → 96 deals (74 graded, 22 minor); linking within 1 day when the clubs name each other or a
  player crosses, never merging a group with a club on two different days (the same rule as the Hardwood).
- **Values** (WAR, discounted 0.9 a season to the trade season): at the time (AsOf + `project`), realised (season GAR/60 ×
  TOI for the new club after the date / gpw, regular season), now (realised + valuation v2's remaining in-window seasons
  while still with the club); each asset max(0, ·). Grades on share × sides / 2: A ≥ .65, B ≥ .55, C ≥ .45, D ≥ .35, F;
  minor < 0.25 WAR in total. League table 16 Oct 2026 (net now): MIN +5.1, TOR +3.4, NJD +3.2 … CGY −3.6, VAN −4.8, COL −4.8.
- **Pick-value curve**: drafts 2010–2019 (records.nhl.com, 2,126 picks), v = Σ_{k<7} 0.9^k max(0, WAR_k) × 82/team games;
  slot means → PAVA (non-increasing) → v(p) = a (p + b)^−c by weighted least squares: a 8.223, b 0.453, c 0.710; R² 0.735 on
  slot means, 0.978 on 16-pick bins. v(1) 6.31, v(16) 1.13, v(32) 0.70, v(64) 0.43, v(128) 0.26. Round averages (fitted /
  observed / share with any WAR): 1st 1.56 / 1.59 / 88 %, 2nd 0.53 / 0.56 / 58 %, 3rd 0.37 / 0.39 / 36 %, 4th 0.29 / 0.24 /
  31 %, 5th 0.24 / 0.21 / 23 %, 6th 0.21 / 0.13 / 20 %, 7th 0.19 / 0.09 / 16 % (the fit is generous to the last rounds,
  where the power law flattens; documented, not tuned). A future pick: the round's average × 0.9^(draft year − trade
  season start year); a known slot ("No. 23") uses v(slot); a prospect with no NHL games: v(his draft slot).
- **Limits**: a pick's value counts seven seasons after the draft, a player's four from the trade, so picks are favoured
  against young players with long careers; conditional picks at face value; retained salary and the cap are not modelled.

## 20. Fantasy: `analytics/fantasy.py`, `analytics/gamelog.py`

Payloads `fantasy.json`, `fantasy_backtest.json`; page `#/fantasy` (`fantasy.js`). The model is in the module docstring and
the Methodology; constants: HL_TOI 10 games, HL_RATE 40, goalie talent HL 80 with 150 pseudo-xG, start share HL 10 club
games, finishing prior 40 xG, rate priors 300 (ES ixG, on-ice), 60 (PP ixG, PP assists), 200 (SOG, hits, blocks) minutes,
assist share 15 goals, club factors 10 pseudo-games (HL 20, last season at half weight), decision share 0.97, back-to-back
ratio fitted (0.55 on 2024–25 to 2026–27). Default points (ours): G 2, A 1.5, +/- 0.5, PPP 0.5, SOG 0.3, HIT 0.2, BLK 0.4;
W 4, GA −1, SV 0.2, SO 3. Game logs: boxscores (official G, A, +/-, PIM, hits, blocks, SOG, PPG, TOI; goalie SA, SV, GA,
decision, starter) joined to the models' player-game table (TOI by strength, PP points, ixG, on-ice 5v5) and the shot table
(ixG on the PP and at even strength; goalie xG faced), cached per season on content signatures (box files parsed once).

**Backtest** (2021–22 to 2025–26, 127 weekly checkpoints; MAE per player-game in default points, Spearman averaged over
checkpoints; best in bold):

| | MAE ours | to date | last season | ρ ours | to date | last season |
|---|---|---|---|---|---|---|
| Skaters, next week | **0.828** | 0.856 | 0.860 | **0.497** | 0.463 | 0.437 |
| Skaters, rest of season | **0.352** | 0.452 | 0.423 | **0.775** | 0.711 | 0.674 |
| Goalies, next week (per club game) | **1.509** | 1.534 | 1.592 | **0.403** | 0.389 | 0.311 |
| Goalies, rest of season | **0.764** | 0.860 | 0.886 | 0.601 | **0.611** | 0.502 |

Skater categories, rest of season (MAE ours / to date / last; ρ ours / to date / last): G 0.065 / 0.095 / 0.079, ρ 0.758 /
0.629 / 0.666; A 0.104 / 0.132 / 0.112, ρ 0.698 / 0.607 / 0.624; +/- 0.187 / 0.279 / 0.233, ρ 0.326 / 0.263 / 0.239; PPP
0.050 / 0.062 / 0.056, ρ 0.808 / 0.735 / 0.719; SOG 0.290 / 0.366 / 0.354, ρ 0.840 / 0.789 / 0.775; HIT 0.343 / 0.356 /
0.357, ρ 0.829 / 0.829 / 0.805 (a tie with season to date on rank); BLK 0.178 / 0.243 / 0.213, ρ 0.855 / 0.805 / 0.812.
By season the rest-of-season skater MAE is 0.340–0.372 (baselines 0.409–0.464). Where a baseline wins (goalie rest-of-season
rank correlation; hits ranks) the page shows it. The xG model was fitted on all seasons (cross-fitted by season), a small
leak the backtest does not remove. Recompute with `scripts/nhl_fantasy_backtest.py` (about 4 minutes on 2 cores); the
hourly build only copies the cache (flagged "stale" when the inputs moved since).

Tests: `tests/nhl/test_moves.py` (30) and `tests/nhl/test_valuation_fantasy.py` (9).
