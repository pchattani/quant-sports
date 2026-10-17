# Models: technical reference (basketball)

Every model behind The Quant Hardwood, with its equations and constants as they
stand in the code. Paths are under `oddsmarkets/basketball/` unless given in full.
Each model has a pure function on in-memory inputs (tested on synthetic stores) and a
cached loader `for_season(league, season, ...)` (`CONTRACT.md` section 3). Where the
site's Methodology (`docs/hardwood/assets/js/docs.js`), `CONTRACT.md`, `PAYLOADS.md`
or a docstring differs from the code, the code is taken as correct and the
difference is listed in section 13.

Units: ratings and impact are points per 100 possessions; possessions are
FGA − OREB + TOV + 0.44 FTA (TOV including team turnovers), averaged over the two
teams (`models/_games.team_poss`, `game_row`; an estimate of 20 or fewer is ignored).
Pace is possessions per 48 minutes (NBA) or 40 (WNBA).

---

## 1. Overview

### 1.1 How the models feed each other

```
 store.json (games, box) ─┬─► ratings.py ──► game.py ──► season_sim.py ──► season.json, markets, awards (team wins)
                          │      ▲  preseason prior: last season (roster term built, off)
                          ├─► elo.py (history, baseline)
                          └─► backtest.py (ratings + game + elo + DraftKings + season_sim, walk-forward)

 shots.json ─► shots.py (xPTS) ─┬─► shot charts, shot-making, calibration
                                └─► impact.py box features (rim / three frequency, shrunk pox100)
 stints.json ─► impact.py RAPM ─► box impact (pooled) ─► HPM ─► projections ─► injuries in game.py,
                                                                             award features, lineups
 raw pbp ─► pbp.parse ─► winprob.py (model on 3 earlier seasons) ─► WP, WPA, clutch, excitement ─► awards (clutch)
 Kalshi / Polymarket / DraftKings ─► sources/markets.py ─► markets.json, awards.json, game cards
 HPM + game sigma ─► analytics/value.py ─► value.json (WAR), needs/<tid>.json, trade.json ◄── season_sim.sensitivity
```

### 1.2 Model inventory

| Model | File | Version string | Output |
|---|---|---|---|
| Team ratings | `models/ratings.py` | `VERSION = 2` | off, def, net, pace with se; Kalman paths; preseason prior |
| Game model | `models/game.py` | `VERSION = 4` | margin ~ Normal(mu, sigma): p_home, spread; calibrated total |
| Season format | `models/config.py` | — | `SeasonFormat` per league and season |
| Season simulation | `models/season_sim.py` | — | 20,000 seasons: wins, seeds, playoffs, title, lottery, magic numbers |
| Elo | `models/elo.py` | `VERSION = 1` | pregame P(home) for every rated game |
| Backtest | `models/backtest.py` | — | walk-forward scores against Elo, DraftKings, ESPN |
| Shot model | `models/shots.py` | `xpts-1` | P(make), xPTS, shot-making, grids |
| Player impact | `models/impact.py` | `impact-1` | RAPM, box impact, HPM, projections, roster impact |
| Win probability | `models/winprob.py` | `wp-2` | WP per state, WPA, leverage, excitement, comeback |
| Award races | `models/awards.py` | `awards-1` | P(win), P(top 3) per award |
| Markets | `sources/markets.py` | — | de-vigged futures, win totals, game prices |
| Player value, needs, trades | `analytics/value.py` (+ `season_sim.sensitivity`) | `VERSION = 1` | WAR, position groups, team grades, trade targets, depth chart, sensitivity curves (section 14) |

---

## 2. Team ratings: `models/ratings.py`

### 2.1 Static fit (`fit_ratings`)

Every finished game of stype `reg`, `cup`, `playin` or `post` (`_games.COUNTED`) gives
two observations, one per offence:

```
100 · pts_home / poss = mu + o_home + d_away + (h/2)·[not neutral] + e
100 · pts_away / poss = mu + o_away + d_home − (h/2)·[not neutral] + e
weight  w = 0.5^(age_days / half_life) · poss / mean(poss)
penalty   ridge · Σ_i [(o_i − o_i^prior)² + (d_i − d_i^prior)²] + 0.05² · h²
```

`o_i` is offence above average, `d_i` points allowed above average (lower is better),
`h` home court per 100 possessions on the margin. Solved as one augmented sparse
least-squares problem (`scipy.sparse.linalg.lsqr`). Reported, centred:

```
L = mu + mean(o) + mean(d)                (league ORtg)
off_i = L + o_i − mean(o),  def_i = L + d_i − mean(d),  net_i = off_i − def_i
se_net_i from s² (A'WA + P)⁻¹,  s² the weighted residual variance
hca_pts = h · league_pace / 100
```

Pace is a separate ridge fit, `pace_game = P + p_home + p_away`, reported as
`pace_i = league_pace + p_i − mean(p)`. A finished game without a box score gets the
mean pace of the games that have one (scaled for overtime): its score counts, but it
is left out of the pace fit (`impute_poss`).

| Constant | NBA | WNBA |
|---|---|---|
| `HALF_LIFE` (days) | 75 | 45 |
| `RIDGE` (games-equivalents) | 8 | 6 |
| League ORtg before any fit (`config.GAME_DEFAULTS["ortg"]`) | 114.0 | 104.0 |
| League pace before any fit (`GAME_DEFAULTS["pace"]`) | 99.0 | 80.0 |

### 2.2 Preseason prior (`preseason_prior`, `fit_carryover`, `season_end_ratings`)

Last season's full-season ratings (no decay, ridge 2, at least 30 games) regressed to
the mean:

```
net_prior = b · net_last
off_prior = L + b · (off_last − L),  def_prior = L + b · (def_last − L)
pace_prior = P + b_pace · (pace_last − P),   se_prior = residual sd of the carry-over fit
```

`b` is the slope through the origin of a team's net on its previous season's, over
every consecutive pair of seasons on disk with at least 20 games each; it needs 40
pairs, else `DEFAULT_B = 0.65`, `DEFAULT_SE = {"nba": 4.0, "wnba": 5.0}`, `b_pace =
0.6`. A team new to the league starts at `EXPANSION_NET = −4.0` (offence −2, defence +2)
with se × 1.25. Fitted values in the local cache on 1 October 2026
(`data/basketball/cache/ratings/carryover_<L>.json`): NBA b = 0.5433, se = 4.094,
b_pace = 0.4552 (210 pairs); WNBA b = 0.4685, se = 4.733, b_pace = 0.6543 (295
pairs). The carry-over refits itself whenever the stores change.

The prior can blend in roster impact, `net = (1 − blend)·b·net_last + blend·(impact −
mean impact)`, `blend = 0.5`, se × sqrt(1 − blend/2), split equally between offence
and defence.

**Roster impact** (`roster_prior_impact`, built 1 October 2026, **on since 2 October 2026** for both leagues):
`ratings.for_season` passes it for the current season of the leagues in `ROSTER_PRIOR_LEAGUES = ("nba", "wnba")`
(`roster=False` turns it off for one call). For each team in the
store's `meta.rosters` (today's roster per team, written by the `bb_fetch.py` rosters
phase), each player counts at his projected HPM for the new season (`impact.projections`
"hpm_next": last season's HPM plus the aging step) over his projected minutes, the
minutes handed out to the players with the most first until five players' worth (240
NBA) are used (`_allocate_minutes`), the rest at replacement (`impact.roster_impact`,
−2.0). A player with no minutes last season counts at his values from the season
before (an injured star); rookies count at replacement. The per-player values are
cached on the content of last season's store and stints (`cache/ratings/
roster_values_<L>_<S>.json`), so the hourly build does not refit last season's impact
model (the first WNBA computation took 168 s on 2 October 2026; later calls read the cache).

History of the switch. On 1 October 2026 it was switched off because, against the Kalshi NBA 2026-27 win
totals (4,000 simulations), it widened the gap to the market (mean |P(over) model − market| 18.1 points
against 15.0). That compared one season with a market, not with outcomes. The walk-forward test on outcomes
(`docs/research/basketball_edge.md`, experiment E3; each season's preseason box-score rosters standing in for
`meta.rosters`, carry-over slope fitted on earlier seasons only) favours it:

| RMSE of the prior against the actual season net rating | carry-over only | roster prior (as coded) | seasons better |
|---|---|---|---|
| NBA 2012–2026, 450 team-seasons | 3.745 | **3.599** | 11 of 15 |
| WNBA 2010–2026, 193 team-seasons | 5.204 | **4.894** | 10 of 16 |

and at game level (walk-forward, information through the previous day) it lowers the log-loss of the first
~20 games of each team: NBA −0.0031 [−0.0051, −0.0011], WNBA −0.0042 [−0.0072, −0.0011]. A roster-change form
(`b · net_last + κ · (S_new − S_last)`) did slightly better again in the research code (NBA 3.50) but is not in
production. **The site still hides preseason win-total edges** (`season.js`, `markets.js`); revisit with the
research numbers before showing them.

### 2.3 Rating paths (`rating_paths`)

A Kalman filter on all teams' net ratings jointly, full covariance:

```
state     n_t = n_(t−1) + u,  u ~ N(0, q · min(days since last game day, 60)) per team
observe   100 · margin / poss − h·[not neutral] = n_home − n_away + e,  e ~ N(0, r)
start     n_0 = prior net, Var = prior se²  (5² without a prior)
r = 0.8 · var(100 · margin / poss)  (160 with 30 games or fewer);  h from a no-decay fit with ridge 4
```

`Q_PER_DAY = {"nba": 0.03, "wnba": 0.05}`.

---

## 3. Game model: `models/game.py`

### 3.1 Equation (`predict`)

```
margin ~ Normal(mu, sigma)
mu = s · (net_h − net_a) · pace_g / 100
   + HCA · [not neutral]
   + b_b2b  · (b2b_h − b2b_a)
   + b_rest · (min(rest_h, 3) − min(rest_a, 3))
   + b_trav · (km_h − km_a) / 1000
   + b_tz   · (tz_h − tz_a)
   + b_alt  · [host is DEN / UTAH / UTA and not neutral]       (NBA; the WNBA has no altitude teams)
   + inj_h − inj_a
pace_g = pace_h + pace_a − league_pace
p_home = Φ(mu / sigma),   spread_fair = −mu
pts_h = (off_h + def_a − L) · pace_g/100 + HCA/2 + context/2,   pts_a likewise,  raw = pts_h + pts_a
total = total_a + total_b · raw + total_post · [playoff game]     (shift split equally between pts_h and pts_a)
```

`context` is mu minus the rating and home terms. A team without a rating is average.

**Totals calibration** (`game.fit_total`, model `VERSION = 4`, 2 October 2026): the raw ratings total is biased
in the NBA (walk-forward 2012–2023: 2.2 points low overall, 3.3 high in the playoffs; 2024–2026 playoffs 9.8
high), so `fit_from_rows` regresses the final total on the raw total and a playoff indicator. Out of sample it
lowers the NBA total RMSE from 18.45 to 18.27 (2012–2023) and from 18.65 to 18.56 on 2024–2026 (MSE difference
CI excludes zero); WNBA neutral. `analytics/games.model_line` passes the game's `stype` so playoff games get the
playoff term; `predict` also returns `total_raw`.

**Schedule context** (`Schedule.team_features`): rest = days since the previous
non-preseason, non-All-Star game minus 1 (b2b when 0; a first game counts as 3); travel
= great-circle km between the previous and current arenas (Earth radius 6,371 km);
tz = the difference in the arenas' standard UTC offsets. Travel and tz count only when
rest ≤ 3. Arenas are fixed coordinates by ESPN abbreviation (`config.NBA_ARENAS`,
`WNBA_ARENAS`; Denver 1,609 m, Utah 1,288 m).

**Injuries** (`injury_adjustment`): for each missing player with an impact per 100
and expected minutes,
`inj_team = −Σ (impact − replacement) · min(minutes, G)/G · pace_g/100`, G = 48 (NBA) or
40 (WNBA), `replacement = GAME_DEFAULTS["replacement"] = −2.0`. The build supplies the
list (`analytics/games.injury_inputs`): players listed "Out" on ESPN's injury report,
impact = their HPM total, minutes = their projected minutes. It is applied only to
games not yet played (pregame lines on game pages and in `markets.json`); the season
simulation passes no injuries.

**Spread to probability** (`spread_to_p`): `p = Φ(−spread_home / sigma_market)`.

### 3.2 Fitting (`walk_forward`, `fit_from_rows`, `fit_params`)

For every finished game of every season on disk, ratings are refitted weekly
(`REFIT_DAYS = 7`) from games strictly before the week, with the preseason prior. The
margin is regressed on [rating term, home, b2b, rest, travel, tz, altitude] by ridge
(λ = 1 on every coefficient, no intercept; all-zero columns dropped).
`sigma = sqrt(RSS / (n − k))`; `sigma_market = sqrt(mean((margin + spread_home)²))` over
games with a line (needs 100, else = sigma). Fewer than 200 games: the defaults.

| `config.GAME_DEFAULTS` | NBA | WNBA |
|---|---|---|
| sigma | 12.0 | 12.5 |
| hca | 2.4 | 2.0 |
| b2b | −1.6 | −1.2 |
| rest | 0.4 | 0.3 |
| travel_1000km | −0.25 | −0.2 |
| tz | −0.25 | −0.2 |
| altitude | 1.0 | 0.5 |
| replacement | −2.0 | −2.0 |
| sigma_market | 12.0 | 12.5 |

`scripts/bb_fit.py` (run locally) fits them on every store on disk and commits them to
`oddsmarkets/basketball/models/fitted/game_params_<L>.json`, with the live
win-probability model (`winprob_<L>.json`); `game.params` reads the local cache, then
the committed file, then the defaults, so CI (no history to fit on) publishes the
committed fit. Refitted on 1 October 2026 on the full history:

| Fitted | NBA (1997–2027 stores, 38,000 games) | WNBA (1997–2026 stores, 6,028 games) |
|---|---|---|
| rating_scale | 1.0131 | 1.0005 |
| hca | 2.520 | 2.527 |
| b2b | −1.770 | −0.953 |
| rest | 0.103 | 0.183 |
| travel_1000km | +0.126 | −0.101 |
| tz | −0.314 | −0.089 |
| altitude | +0.953 | 0.5 (column dropped; default kept) |
| sigma | 12.405 | 12.015 |
| sigma_market | 12.682 (15,220 lines) | 12.707 (339 lines) |
| total_a / total_b / total_post (2 Oct 2026) | 7.837 / 0.9723 / −5.770 | −2.333 / 1.0204 / −0.391 |
| sigma_total | 18.18 | 16.72 |

On the full history the NBA altitude term has the expected sign (+0.95 points to a
Denver or Utah host; it was −0.36 on two seasons). Travel stays slightly positive
(+0.13 per 1,000 km more travelled by the home side than by the visitor), which is not
plausible on its own; it is small and shares its signal with the time-zone term
(−0.31 per hour), so the two are best read together. The live win-probability models:
NBA K = 20 on 1,978,778 states, WNBA K = 10 on 336,743.

---

## 4. Season simulation: `models/season_sim.py`

### 4.1 State (`build_state`)

Standings games are stype `reg` (which includes the NBA Cup's group and knockout games;
the Cup final, `cup`, does not count). `playin` and `post` are the postseason; played
ones are fixed and a series in progress continues from its score. A game after the
`through` day or not final is unplayed; "TBD" placeholders are ignored; a postponed game
is dropped when both teams already have a full schedule; once the postseason has begun
any regular-season game still on the books is dropped. Before the NBA Cup knockout
draw, a team short of the format's game count (and no team short by more than 4) gets
filler games against conference rivals that are short too, home side drawn at random.

### 4.2 Simulated games

```
margin(s, g) = mu_g + (x_(s,h,w) − x_(s,a,w)) · P/100 + sigma_n · eps
x_(s,t,w)    = z_(s,t) + Σ_(k≤w) u_(s,t,k),   z ~ N(0, se_t²),  u ~ N(0, drift²)
sigma_n      = sqrt(max(sigma² − mean(2 se²)·(P/100)², (0.85 sigma)²))
```

`mu_g` is `game.predict`'s mean for the fixture (ratings, home court, rest, travel,
altitude). `z` is a season-long draw of each team's rating error (so outcomes are
correlated), `u` a weekly random walk from the first remaining game day. sigma was
fitted on walk-forward residuals that already contain rating error, so the game noise
removes the mean rating variance but never falls below 85 % of sigma.

| Constant | NBA | WNBA |
|---|---|---|
| simulations (`n`, the build's `--sims`) | 20,000 | 20,000 |
| `CHUNK` | 5,000 | 5,000 |
| `DRIFT` (weekly sd, net per 100) | 0.35 | 0.45 |
| rating se when a team has none | 4.0 | 4.0 |

The build seeds the simulation with the season number (`analytics/context.py`).

### 4.3 Tiebreakers and formats (`Ranker`, `config.py`)

Teams are ranked by win % within their seeding group (conference in the NBA, the league
in the WNBA from 2016). Exact ties go through the format's two-team or multi-team list;
each criterion splits the tied teams into classes, a class still tied restarts from the
top, and a tie surviving everything is a random draw. Criteria: `h2h`, `div_winner`,
`div_record`, `conf_record`, `vs_playoff_own`, `vs_playoff_other` (win % against teams at
or above the `eligible_n`-th place), `vs_500`, `h2h_pd`, `pd`.

| List | NBA | WNBA |
|---|---|---|
| two teams | h2h, div_winner, div_record, conf_record, vs_playoff_own, vs_playoff_other, pd | h2h, vs_500, h2h_pd, pd |
| three or more | div_winner, h2h, div_record, conf_record, vs_playoff_own, pd | h2h, vs_500, h2h_pd, pd |

| Current format | NBA 2027 | WNBA 2026 |
|---|---|---|
| teams; games | 30; 82 | 15; 44 |
| seeding | conference (15 each) | league |
| direct places; play-in | 6; seeds 7–10 | 8; none |
| series (best of) | 7, 7, 7, 7 | 3, 5, 7 |
| home patterns | HHAAHAH every round | HAH, HHAAH, HHAAHAH |
| Finals home court | better regular-season record, point differential on a tie | higher seed |
| lottery | `LOTTERY_2019` (140, 140, 140, 125, 105, 90, 75, 60, 45, 30, 20, 15, 10, 5), 4 draws | none |
| Cup | 4 group games; group and knockout count; final does not | Commissioner's Cup final does not count |

Every season from 1997 has a format (`config.fmt`, never raises): NBA 29 teams to 2004;
50 games in 1999, 66 in 2012, 72 in 2020 and 2021 (the bubble noted, not modelled);
play-in from 2021; best-of-5 first round to 2002; 2-3-2 Finals 1985–2013; two divisions
per conference to 2004; `LOTTERY_1995` with 3 draws before 2019; the Cup from 2024. WNBA
team and game counts per season are in `_WNBA_TEAMS` and `_WNBA_GAMES` (2026 verified,
earlier marked unverified); best-of 3, 5, 5 from 2022 to 2024; single-game first two
rounds 2016–2021 (simplified as a bracket); before 2016 four playoff teams per
conference with best-of 3, 3, 5.

### 4.4 Postseason, lottery, outputs

- **NBA play-in**: 7 hosts 8 (winner is the 7th seed), 9 hosts 10 (loser out), loser of
  7v8 hosts winner of 9v10 for the 8th seed.
- **Bracket** 1-8, 4-5, 3-6, 2-7, no reseeding; the higher seed holds home court; each
  game `Φ(((x_A − x_B)·P/100 ± HCA) / sigma_n)` with end-of-season strengths, no rest or
  travel. Once the regular season is over the seeds are fixed, and observed first-round
  pairings override the computed slots.
- **Lottery** (NBA): the 14 non-playoff teams in reverse win % (ties random) take the
  slots; picks 1–4 (1–3 before 2019) drawn in proportion to combinations out of 1,000;
  exact slot-to-pick probabilities enumerated once (`lottery_matrix`); pick trades and
  protections ignored.
- **Outputs** per team: `exp_w`, `exp_l`, `w_p05`, `w_p95`, `win_dist`, `seed_dist`,
  `p_playoffs` (play-in winners included), `p_playin` (7th–10th), `p_top6`, `p_div`
  (NBA), `p_reach` per round, `p_conf` (reached the Finals), `p_title`,
  `p_lottery_pick`, `magic`, `tragic`, `clinched`, `eliminated`, `next` with
  `if_win` / `if_loss`, `current`. The bracket lists the 24 most frequent match-ups per
  round.
- **Conditional on the next game** (`next.if_win`, `if_loss`): interventional; each
  simulation where the team won is weighted by 1 / P(win | that simulation's rating
  draws), so the draws keep their prior distribution and the difference measures the
  game's own effect.
- **Magic and tragic numbers** (exact, not simulated): for "top k of group X",
  `M_ij = W_j + R_j − W_i + 1`; magic = the k-th largest over rivals, clinched at ≤ 0;
  tragic = the k-th smallest `W_i + R_i − W_j + 1`, eliminated at ≤ 0. NBA targets
  `top6`, `postseason` (top 10), `division`, `top_seed`; WNBA `postseason` (top 8),
  `top_seed`.

---

## 5. Elo: `models/elo.py`

FiveThirtyEight's NBA recipe over every season on disk:

```
E_home = 1 / (1 + 10^(−(R_h − R_a + HCA·[not neutral]) / 400))
R_h ← R_h + K · M · (S_home − E_home),  R_a ← R_a − (same)
M = (|MOV| + 3)^0.8 / (7.5 + 0.006 · D),  D = winner's Elo minus loser's (home court included)
between seasons R ← carry · R + (1 − carry) · mean
spread equivalent = −(R_h − R_a + HCA) · pts_per_elo
```

| `config.ELO_DEFAULTS` | NBA | WNBA |
|---|---|---|
| k | 20 | 20 |
| hca (Elo points) | 100 | 90 |
| carry | 0.75 | 0.70 |
| mean | 1505 | 1505 |
| new_team | 1300 | 1350 |
| pts_per_elo | 1/28 | 1/30 |

`reg`, `cup`, `playin` and `post` games are rated. A team's first game is rated at the
mean in the first season on disk, at `new_team` later. The Elo history starts in the
first season with final games on disk (WNBA: 2002 in practice, section 3 of
[DATA_PIPELINE.md](DATA_PIPELINE.md)).

---

## 6. Shot model (xPTS): `models/shots.py`

```
logit P(make) = a + f_dist(dist_ft) + f_angle(|angle_deg|)       piecewise-linear splines
              + zone + shot_type                                one-hot
              + b·[three] + assisted + putback + transition
              + period (1, 2, 3, 4, OT) + clock (end ≤ 4 s left, late ≤ 24 s, normal)
              + margin bucket (≤ −10, −9..−4, −3..3, 4..9, ≥ 10)
              + league (only when a table mixes leagues)
xPTS = P(make) · value
```

| Constant | Value |
|---|---|
| `DIST_KNOTS` (ft) | 0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 23, 24, 25, 26, 28, 30, 34, 40, 50, 94 |
| `ANGLE_KNOTS` (°) | 0, 15, 30, 45, 60, 75, 90, 120, 180 |
| `LAMBDA_SMOOTH` | 30 (second-difference penalty on both splines) |
| `LAMBDA_TINY` | 0.001 (ridge on spline coefficients) |
| `LAMBDA_CAT` | 1.0 (ridge on one-hot and indicators: prior sd 1) |
| `SHRINK_SHOTS` | 250 pseudo-shots at zero for `pox100_shrunk` |
| `GRID_Y_MAX` | 35 ft |

Fitted by Newton/IRLS on a sparse design (`_io.logistic_fit`), one fit per league and
season on that season's `shots.json`. A block is an outcome, not a feature; free throws
are outside the table. The zone and intercept terms are close to unpenalised, so the
fit is calibrated by zone in-sample: xPTS measures shot difficulty against that
season's league, not an out-of-sample forecast. Derived tables: `shot_making`
(pox = points − xPTS, pox100, its binomial se, `pox100_shrunk = 100·pox/(shots + 250)`),
`defense_xpts`, `shot_diet`, `shot_profile` (feeds box impact), `calibration_table` by
zone and type (with `z = (FG% − mean p)·n / sqrt(Σ p(1 − p))`), `league_grid` (hexagons of
circumradius 1.5 ft or 2 ft squares) and `distance_curve`.

Calibration in the committed `calibration.json` (2026 seasons, in-sample by
construction): NBA 248,615 shots, WNBA 48,799; every zone's mean predicted probability
equals its make rate to the fourth decimal (WNBA above-the-break threes: 0.3388
against 0.3388, z = 0.02).

---

## 7. Player impact: `models/impact.py`

### 7.1 RAPM (`rapm_fit`, `_season_rapm`)

Each stint gives two observations, one per offence:

```
y = 100 · pts_off / poss_off − league ORtg  =  Σ_(offence) O_i − Σ_(defence) D_j + hca · s + e
s = +0.5 home offence, −0.5 away;  weight = poss_off;  Var(e) = sigma² / poss_off
prior O_i, D_i ~ N(m_i, sigma²/λ),  hca ~ N(0, sigma²/0.001)
(X'WX + Λ) b = X'Wy + Λ m;   cov = sigma² (X'WX + Λ)⁻¹,  sigma² = wRSS / (n − tr((X'WX + Λ)⁻¹ X'WX))
```

λ from `RIDGE_GRID = [250, 500, 1000, 2000, 3500, 6000, 10000]` by `CV_FOLDS = 5`-fold
cross-validation over whole games (`DEFAULT_RIDGE = 2000` when a single value is
given). The prior centre is 0 in the first season with stints, otherwise the previous
season's estimate × `PRIOR_CARRY = 0.8`, chained up to 12 seasons back. O is offence
added, D points taken off the opponent (positive is good), T = O + D; the se of T
includes the O–D covariance.

### 7.2 Box impact (`box_rates`, `box_impact_fit`, `box_impact`, `box_model`)

Per player and season, regular-season box rates with `on_poss = team_poss · sec /
(team player-seconds / 5)`: per-100 pts, fga, tpa, fta, ast, tov, oreb, dreb, stl, blk,
pf; `ts_add = (TS_shrunk − lg_TS) · 2 · 100 · TSA / on_poss` with `TS_PSEUDO = 50`
attempts at league TS; 3PA and FT rates shrunk with `RATE_PSEUDO_FGA = 20`; usage; pool
dummies (a player with no pool counts as F). `BOX_FEATURES` = pts100, ts_add, tpar,
ftr, ast100, tov100, oreb100, dreb100, stl100, blk100, pf100, usg, pool_G, pool_F;
`SHOT_FEATURES` = rim_freq, three_freq, pox100_shrunk.

A possession-weighted ridge of RAPM O and D on the standardised features, pooled over
every season on disk that has stints, in two variants: "full" (box + shot features)
and "box" (box only, for players or seasons without shots). Weight `min(poss,
BOX_WEIGHT_CAP = 4000)`, ridge `BOX_RIDGE = 5.0` × total weight / 1000, free intercept.
A team adjustment then adds `(team ORtg − league − Σ frac·o) / 5` to each player's O (and
likewise for D) so the minutes-weighted five-man sums match the team. Team ratings use only games with a box
score, and the adjustment is skipped for a team with fewer than `MIN_TEAM_BOX_GAMES = 10` of them (`BOX_VERSION = 2`,
2 October 2026). Before that, NBA 2015-16 Chicago (one game with a box score) got O/D splits of about ±48.
`_io.box_frame` leaves out a side whose players all have 0 seconds (a missing box score: ESPN returns the same zeros
on a refetch; NBA 2013–2018 about 330 team-games a season, mostly CHI and NO; WNBA 2002–2005 most heavily), and takes
the game's possessions from the other side; `analytics/teams._team_frame` blanks that side's counting stats and
imputes its possessions, so team ORtg, DRtg and pace keep every game's points. `tau²` = the
weighted variance of (RAPM − box) minus the mean RAPM se², floored at `TAU2_FLOOR =
0.25`. Because WNBA stints exist from 2002 and pre-2020 WNBA play-by-play reconciles
poorly, the WNBA pool includes noisy early seasons (HANDOFF Task 21).

### 7.3 HPM (`hpm`)

```
HPM_side = (box/tau² + RAPM/se²) / (1/tau² + 1/se²),   se = (1/tau² + 1/se²)^(−1/2),   side = O, D
HPM = HPM_O + HPM_D,   se_HPM = sqrt(se_O² + se_D²)
```

With no RAPM, box impact with se tau (`tau² = 4` if a variant has none). The page shows
`w_rapm_o` / `w_rapm_d`, the weight on RAPM.

### 7.4 Projections and roster impact

`projections`: per-36 rates from games before `asof` weighted `0.5^(k/60)`
(`HALF_LIFE_GAMES = 60`), shrunk to the pool rate with `PRIOR_MINUTES = 250`; expected
minutes weighted `0.5^(k/12)` (`MINUTES_HALF_LIFE = 12`); availability = share of the
team's last 20 games played; `HPM_next = HPM + aging(age)` with `AGE_CURVE` (19: +1.2,
21: +0.9, 23: +0.6, 25: +0.3, 27: 0, 29: −0.25, 31: −0.6, 33: −1.0, 35: −1.4, 38: −2.0;
hand-set). Dates of birth: the rosters phase for the current season, data/<L>/bio.json (scripts/bb_bio.py) for
every other player since 16 Oct 2026 (section 15.1).

`roster_impact(team_players, minutes)`: `net = Σ HPM_p · m_p / G + REPLACEMENT_HPM ·
fill / G`, minutes above 5G scaled down, `fill = max(0, 5G − Σ m)`,
`REPLACEMENT_HPM = −2.0`. Defined and tested; not yet called by the ratings prior
(section 2.2).

---

## 8. Win probability and WPA: `models/winprob.py`

### 8.1 Model

State after each play: margin m (home − away), seconds left τ (regulation left, or left
in the current overtime), possession p (+1 / −1 / 0), pregame expected margin s,
league. T = 2,880 s (NBA) or 2,400 s (WNBA), u = τ/T.

```
logit P(home wins) = [b1 m + b2 m·u + b3 s·u + b4 p + b5 p·u] / sqrt(τ + K)
s = −spread_home (DraftKings via pickcenter); no line: DEFAULT_HCA at home, 0 at a neutral site
```

No intercept (a pick'em at tip-off is exactly 0.5). K from `K_GRID = [2, 5, 10, 20, 40,
80]` by log-likelihood; ridge `RIDGE = 0.001`; `DEFAULT_HCA = {"nba": 2.5, "wnba": 2.0}`.
A finished game is exactly 1 or 0; a tie at τ = 0 goes to overtime. No fouls to give,
bonus or timeouts.

**Possession after a play**: from the parsed possessions (by event index, then time),
else inferred from text. A made basket, turnover or made last free throw hands the ball
over; a missed field goal (missed last free throw) leaves a loose ball worth
`p = side · (2r − 1)` to the shooting side, `r = OREB_FG = 0.27` (`OREB_FT = 0.14`): the
miss carries most of the lost possession, the defensive rebound the rest.

**Training** (`model_for`): every play-by-play state of the `n_seasons = 3` seasons
before the season, labelled with the result, so the season itself is out of sample;
only when no earlier raw play-by-play is on the machine does it fall back to the season
itself. CI holds only the current season's raw files, so in CI the fallback applies
(section 12). Fitted locally on 1 October 2026 for the 2026 seasons: NBA K = 20, β =
(5.303, −1.294, 5.834, 2.835, −0.557) on 1,953,976 states; WNBA K = 10, β = (5.711,
−0.818, 4.648, 3.057, −0.233) on 337,193 states.

### 8.2 WPA (`wpa`, `_credit`)

Per-team accounting: each play's dWP is credited in full to both teams in their own
terms (+dWP to home, −dWP to away), so a team's players sum to that team's own change in
win probability:

```
Σ(team's players' WPA) + unattributed[team] = team's WP(final) − WP(tip-off)
```

Within a team: on the acting team its listed participants share it (the first
`1 − ASSIST_SHARE`, team-mates `ASSIST_SHARE = 0.3`); on the other team a listed player
(blocker, stealer, fouled player) takes `DEF_SHARE = 0.5` and its five on the floor split
the rest, or the five share all of it when nobody is listed; a team with nobody to credit
(no lineup, or the final step to 1 or 0) books it to `unattributed`. `check` in the
output is the largest residual of the identity (about 0).

**Leverage, clutch, excitement, comeback**: `LI = |WP(m+1) − WP(m−1)|/2` at the state
before the play, divided by its mean over the fitting states; leverage-adjusted WPA =
Σ credit / max(LI, 0.1); clutch = 4th period or overtime, ≤ `CLUTCH_S = 300` s, margin
within `CLUTCH_MARGIN = 5`; excitement = Σ|dWP|; comeback = the winner's lowest WP.

### 8.3 Calibration against ESPN (`calibration`)

Both models scored on the same states (Brier, log-loss, 10-bin reliability), from the
committed `calibration.json`, 2026 seasons:

| League | States (with ESPN) | Ours, all states: Brier / log-loss | Ours, ESPN's states | ESPN | Mean abs. difference |
|---|---|---|---|---|---|
| WNBA | 146,348 (142,369) | **0.1400** / 0.4224 | 0.1408 / 0.4246 | 0.1426 / 0.4273 | 3.6 points |
| NBA | 678,461 (675,141) | 0.1498 / 0.4464 | 0.1502 / 0.4477 | **0.1494** / 0.4474 | 4.4 points |

On identical states ours beats ESPN's on the WNBA (Brier 0.1408 against 0.1426) and is
very slightly worse on the NBA (0.1502 against 0.1494). The headline WNBA figure (0.1400
against 0.1426) compares all of our states with ESPN's subset.

---

## 9. Award races: `models/awards.py`, `models/award_winners.py`

```
P(i wins | pool) = exp(θ_i) / Σ_(j in pool) exp(θ_j),   θ_i = Σ_k w_k z_ik
```

z is each feature standardised within the season's pool. Weights fitted on past winners
by maximising Σ log P(winner) − 0.5 · `RIDGE` · |w|² (`RIDGE = 0.5`, L-BFGS); co-winners
weighted 1/k; fewer than three usable past seasons gives `DEFAULT_WEIGHTS`.

| Award | `FEATURES` | `DEFAULT_WEIGHTS` | Pool beyond the floor |
|---|---|---|---|
| mvp | hpm_value, ppg, team_win_pct, hpm_t | 1.6, 0.8, 1.0, 0.4 | — |
| roy | ppg, mpg, hpm_value, team_win_pct | 1.6, 0.6, 0.6, 0.2 | rookies |
| dpoy | hpm_d_value, bpg, spg, dpg, team_def | 1.2, 0.8, 0.4, 0.4, 0.8 | — |
| 6moy (site key `sixth`) | ppg, hpm_value, mpg, team_win_pct | 1.6, 0.6, 0.4, 0.4 | started fewer than half their games |
| mip | d_hpm, d_ppg, d_mpg, ppg | 1.2, 1.2, 0.6, 0.4 | played the previous season |
| clutch (NBA) | clutch_wpa, wpa, team_win_pct | 1.6, 0.4, 0.8 | has clutch play-by-play |

`hpm_value = (HPM_T + 2.0) · minutes / G / 10`, `hpm_d_value = (HPM_D + 1.0) · minutes / G /
10`, `team_def = league ORtg − team DRtg`. Floor: `MIN_GAMES_SHARE = 0.4` of the team's
games and `MIN_MPG = 12`. NBA from 2024 (`RULE_65_FROM`): MVP, DPOY, MIP and Clutch need
`RULE_65_GAMES = 65` qualifying games (20+ minutes, plus at most two of 15–20).

**Rookies**: a player not seen in any earlier season on disk. While fewer than five
earlier seasons are on disk (`n_before < 5`), a newcomer counts only if their date of
birth puts them at 24 or younger. Dates of birth come only from the rosters phase, so
with fewer than five earlier seasons and no rosters the ROY pool is empty (HANDOFF
Task 19).

**Projection** (`race`, `N_SIMS = 5,000`): remaining games ~ Binomial(team games left,
availability clipped to 0.02–1); counting stats at per-game rates; HPM drifts
N(0, `HPM_DRIFT_SD`² = 1.5² × share of season left), defence by half the draw; team wins
from the season simulation as Normal(exp_w, ((w_p95 − w_p05)/3.29)², floor 0.5) or
Binomial without it; features restandardised per simulation; the winner drawn by the
Gumbel-max trick. `p_top3` likewise. Past winners (`award_winners.py`) were verified on
1 October 2026; the WNBA 2026 MVP, DPOY and Sixth Player were not yet announced.

---

## 10. Markets: `sources/markets.py`

| Market | Kalshi | Polymarket (by title) |
|---|---|---|
| Champion | `KXNBA`, `KXWNBA` | "NBA: 2027 Champion", "WNBA: 2026 Champion" |
| Conference (NBA) | `KXNBAEAST`, `KXNBAWEST` | Eastern / Western Conference Champion |
| NBA Cup | `KXNBACUP` | "NBA Cup Winner" |
| MVP, ROY, DPOY | `KXNBAMVP`, `KXNBAROY`, `KXNBADPOY`; `KXWNBAMVP`, `KXWNBAROY`, `KXWNBADPOY` | by title |
| Sixth, Clutch | `KXNBASIXTH`, `KXNBACLUTCH`; `KXWNBA6POY` | by title |
| Playoffs / play-in (NBA, per team yes/no) | `KXNBAPLAYOFF`, `KXNBAPLAYIN` | "Team to Make Playoffs" / "Play-In" |
| Win totals | `KXNBAWINS`, `KXWNBAWINS` (ladders of "N+ wins") | — |
| Games | `KXNBAGAME`, `KXWNBAGAME` | `nba-<a>-<b>-YYYY-MM-DD` moneyline |

- **Price** = midpoint of a live two-sided quote (`0 < bid ≤ ask < 1`, `ask − bid ≤
  0.12`); never a last trade. Sources averaged per runner.
- **Thin-market rule** (`assemble`): published only when at least `max(4, field/2)`
  runners are accounted for (quoted, no bid with ask ≤ `FLOOR_ASK = 0.02`, or settled
  No) and the implied total is within `MIN_TOTAL, MAX_TOTAL = 0.8, 1.3`; then
  multiplicative de-vig. Award fields are the runners the markets list. A settled market
  is reported as settled, not priced. Playoff / play-in yes/no markets are the mean mid,
  not de-vigged.
- **Win totals** (`parse_win_ladder`): the ladder forced non-increasing by a running
  minimum; line = N − 0.5 at the rung nearest 0.5, P(over) its price. The model's P(over)
  comes from the simulation's `win_dist` (`analytics/season.win_totals`).
- **Games** (`game_prices`): matched to the store's games by the team pair within one day
  (US day). Kalshi: `mid_h / (mid_h + mid_a)`; Polymarket: the first outcome's mid;
  DraftKings moneylines converted (`100/(ml+100)` underdog, `−ml/(−ml+100)` favourite) and
  de-vigged; the DraftKings spread through `game.spread_to_p`. `p_home` = the mean of the
  prediction markets, else the moneyline, else the spread; `basis` records which.
- **Names**: Kalshi team codes through `CODE_ALIASES` to ESPN abbreviations, then
  location and nickname matching, then `best_match` (floor 0.72, refuses a runner-up
  within 0.02); players by folded name, then fuzzy (floor 0.85), then a unique family
  name. Unmatched labels are reported.
- **Edges** (`analytics/season.markets_payload`): model `p_home` minus market `p_home` for
  the next three days' games; futures and win totals pair model and market on the page.
  The site hides preseason win-total edges (`season.js`, `markets.js`): the
  roster-aware prior is switched off (it widened the gap to the market) and last
  season alone ignores summer moves (section 2.2).

---

## 11. Backtest: `models/backtest.py`

### 11.1 Method

Every finished `reg`, `cup`, `playin` and `post` game of the chosen seasons:

- **model**: ratings refitted weekly from games strictly before the week, with the
  preseason prior (carry-over fitted on the stores at hand, teams with 10+ games in both
  seasons, 40 pairs); coefficients and sigma fitted on earlier seasons only (defaults for
  the first);
- **model_ratings_only**: the same ratings with home court only;
- **elo**: the pregame Elo probability;
- **market**: the DraftKings spread from pickcenter, `Φ(−spread_home / sigma_m)`, sigma_m
  from earlier seasons; only games with a line (the line ESPN showed when the finished
  game was fetched, treated as the close);
- **espn**: ESPN's pregame predictor where stored.

Scores: log-loss (p clipped to [1e-4, 1 − 1e-4]), Brier, 10-bin reliability, margin
RMSE; every forecast also on the games with a market line. Season simulation: 2,000
simulations at opening day and 25 / 50 / 75 % of the regular season, scored on playoffs
(appeared in a playoff game), finals (appeared in the last playoff game) and title.
Written to `data/basketball/cache/backtest_<league>.json`; the build turns it into
`<league>/calibration.json`.

### 11.2 Results

From the committed `calibration.json` files, generated on 1 October 2026 on the full
history after the backfill (walk-forward over every store on disk; scored seasons as
below):

**NBA, 2017–2026, 12,852 games**

| Forecast | All games: log-loss / Brier | 9,960 games with a line: log-loss / Brier |
|---|---|---|
| model | 0.6235 / 0.2171 | 0.6283 / 0.2191 |
| model_ratings_only | 0.6253 / 0.2179 | 0.6297 / 0.2197 |
| elo | 0.6334 / 0.2211 | 0.6364 / 0.2224 |
| market (DraftKings) | — | **0.6061** / 0.2094 |

Margin RMSE: model 13.65, Elo 13.78; on the games with a line, model 13.51 against the
market's 13.07. Season simulation (1,080 team-checkpoint forecasts): playoffs log-loss
0.381, finals 0.192, title 0.093. Per season the model beats Elo in 9 of 10 (not 2018:
0.6203 against 0.6196) and trails the line in every season with one (2017–2023, 2026).

**WNBA, 2014–2026, 3,097 games**

| Forecast | All games: log-loss / Brier | 339 games with a line: log-loss / Brier |
|---|---|---|
| model | 0.6173 / 0.2145 | 0.5906 / 0.2012 |
| model_ratings_only | 0.6173 / 0.2145 | 0.5930 / 0.2023 |
| elo | 0.6257 / 0.2182 | 0.6119 / 0.2111 |
| market (DraftKings) | — | **0.5773** / 0.1967 |

Margin RMSE: model 12.52, Elo 12.67; on the games with a line, model 12.90 against the
market's 12.71. Season simulation (532 forecasts): playoffs 0.345, finals 0.350, title
0.206.

**Live win probability** (`calibration.json` `winprob`, the current season scored with
the model fitted on the three seasons before it): NBA 2026, 678,461 states, Brier
0.1498 against ESPN's 0.1494 (0.1502 against 0.1494 on the states where ESPN has a
value); WNBA 2026, 146,348 states, 0.1400 against ESPN's 0.1426.

**ESPN's pregame predictor** is in no stored game (ESPN removes it from finished games'
summaries; DATA_PIPELINE section 3), so the backtest has no `espn` row.

What it says:

- The model beats Elo in both leagues (NBA 0.624 against 0.633; WNBA 0.617 against
  0.626) and loses to the DraftKings line wherever there is one (NBA 0.628 against
  0.606 on 9,960 games; WNBA 0.591 against 0.577 on 339).
- In the NBA the schedule-context terms help a little (0.6235 against 0.6253 for ratings
  and home court only). In the WNBA they add nothing on all games (both 0.6173) and a
  little on the games with a line.
- Live win probability is level with ESPN's in the NBA and slightly better in the WNBA.

---

## 12. Known limitations

- **Rebuilt lineups and possessions.** No on-floor lineups or possession markers from
  ESPN; repairs pick the most plausible absentee; whole-minute box minutes hide errors
  under about 30 s; stints without five a side are dropped from RAPM. Before 2020 the WNBA
  play-by-play is not parsed as shots at all, and 2002–2008 WNBA stints fail the minutes
  check ([DATA_PIPELINE.md](DATA_PIPELINE.md) section 3).
- **No tracking data.** xPTS knows location, ESPN's shot type and game context only;
  shot-making includes contest quality; a defence's points over expected is partly luck.
- **In-sample by design.** xPTS is fitted on the season it scores; box impact is pooled
  over every play-by-play season including the current one.
- **The preseason roster term is coarse** (section 2.2): rookies count at replacement level and single-season
  HPM is noisy for some stars (for example Jaylen Brown −0.24, Trae Young −0.11 on 382 minutes in 2025-26);
  preseason win-total edges stay hidden; the season simulation ignores injuries.
- **The game-model parameters are not refitted automatically** (section 3.2):
  `scripts/bb_fit.py` is run by hand and its output committed.
- **The win-probability model in CI** falls back to in-sample fitting on the current
  season (only its raw files are in CI); early in a season with fewer than 100 states it
  cannot fit at all, and game pages built in CI then carry no model WP. The
  `calibration.json` `winprob` block is rebuilt by every build that has raw play-by-play,
  so a CI build can replace the locally computed out-of-sample comparison with an
  in-sample one (read from `analytics/season.calibration` and `winprob.model_for`).
- **Simplified postseason**: end-of-season strengths and home court only; pick trades
  and protections ignored; the NBA Cup knockout is not simulated (its games count as
  regular season; the Cup winner is shown from the markets only); historical formats
  approximate where marked unverified.
- **Awards** see box, impact, WPA and team wins only: no narrative, voter fatigue or
  injury news before it shows in games played; the 65-game projection assumes the
  current qualifying rate; ROY and Sixth Man are left out of the 65-game rule.
- **Hand-set pieces**: the aging curve, the award defaults, the WPA credit shares, the
  loose-ball rebound rates and the replacement level.
- **Elo** knows nothing about rosters.

---

## 13. Where the code and other texts disagree

Found while writing these documents; the code (and the data on disk) is taken as
correct in every case. "Methodology" is the site text in
`docs/hardwood/assets/js/docs.js`.

| Topic | The code / the data | The other text |
|---|---|---|
| Play-by-play coverage | raw play-by-play on disk from NBA 2003 and WNBA 2002 (section 3 of DATA_PIPELINE) | Methodology "Coverage" and "Limitations", `canon.PBP_FROM = 2017` and its comment, the `espn.py` docstring and `glossary.PBP` ("about 2017 on"): play-by-play from about 2017, a single "Start Period" row before |
| WNBA box scores | 1997 has no scores; 1998–2001 mostly status `in`, so unused; usable from 2002 | Methodology: "Box scores start in 1997 for both leagues" |
| WNBA shots | shot rows only from 2020 (older plays use other type ids and no `pointsAttempted`) | Methodology implies shots wherever there is play-by-play |
| The hourly job | `.github/workflows/update_hardwood.yml`, hourly at :47 | Methodology "Fetching": "The scheduled workflow that will run this mode is not in the repository at the time of writing" |
| Reconciliation figures | WNBA 2026 now 357 derived games, 99.72 % within 60 s, points exact 100 % | Methodology: "266 games ... every game within 60 s" (an earlier derive) |
| Injuries in forecasts | the build supplies the list for unplayed games (`analytics/games.injury_inputs`: players listed Out, HPM and projected minutes) | Methodology "Injuries": "the model code does not build the list itself. Whether a published forecast includes injuries depends on the site build" |
| Roster impact in the prior | on for both leagues since 2 October 2026 (`ROSTER_PRIOR_LEAGUES = ("nba", "wnba")`) | consistent: the Methodology was updated the same day |
| Edges | computed by `analytics/season.markets_payload` | consistent since 2 October 2026 (the Methodology said the step was missing) |
| Catalogues and percentiles | `analytics/players.py`, `teams.py` exist; percentiles are mid-rank against qualified players (`analytics._place`), pool percentile needs 3 qualified members, league needs 2 | Methodology "Percentiles and the player and team catalogues": "the catalogue builder ... is not in the repository"; the convention is described as "a plan" |
| Metric counts | 125 player metrics, 76 team metrics | Methodology "about 120 / about 70"; `PAYLOADS.md` "125 player, 75 team"; `analytics/teams.py` docstring "about 70" |
| Calibration page, shot table | `calibration.json` has `shots.by_zone`; `calibration.js` passes `d.shots` (the wrapper with `season`, `n_shots`, `by_zone`, `by_type`, `curve`) to `fx.rowsOf`, which yields no zone rows, so the page says the table is missing | `PAYLOADS.md` documents `"shots": {"season","by_zone",...}` correctly; the front-end reads the wrong level |
| Game-model parameters | read from the local cache (current model version), else the committed `models/fitted/` files | consistent since 2 October 2026 |
| WP training in CI | falls back to the current season itself when earlier raw files are absent, which is always so in CI | Methodology "Training": "The season itself is then out of sample" |
| `impact.py` docstring | box-only seasons "1997-2016" | play-by-play stints exist much earlier; which seasons are box-only depends on what has been derived |
| `CONTRACT.md` GAME `stype` | never stores `allstar` (dropped by the fetcher) | lists `allstar` among the stypes; `PAYLOADS.md` says All-Star games are not stored (correct) |
| `PAYLOADS.md` history | `history.json` champions come from the stores: WNBA champions start in 2003 on disk, while `first_season` is 1997 (the first store), so pages say "from 1997" | "1997→ wnba" |
| Pronouns | — | `impact.py`, `winprob.py`, `awards.py` docstrings, `glossary.py` and the Methodology use "his" for players |
| Aging in the roster prior | `ratings._last_season_values` reads `impact.projections` "hpm_next" for last season, whose ages come from last season's store; only the current season's store has dates of birth (the rosters phase), so for every player hpm_next = HPM (no aging step) | section 2.2 and the Methodology say the prior adds the aging step. Found 15 Oct 2026 while building section 14; not changed (it would move the published ratings). Section 14 inherits it for the rest-of-season prior and applies the aging step only to next season |

Agreement checked and found consistent: the ratings equations and constants, the game
model equation and defaults, the season-simulation noise, tiebreak lists, formats,
lottery tables and Finals home court, Elo, the shot model's constants, RAPM, box impact
and HPM, the WPA per-team accounting and its constants (`DEF_SHARE` 0.5, `ASSIST_SHARE`
0.3, `OREB_FG` 0.27, `OREB_FT` 0.14), the award features and weights, the market rules
and the backtest method.

---

## 14. Player value, team needs and the trade simulator: `analytics/value.py`

Built 15 October 2026 to the shared spec (`docs/VALUE_SECTIONS.md`); pages in [DASHBOARD.md](DASHBOARD.md) section 3.11,
payloads in `PAYLOADS.md` "Value, needs and trade".

### 14.1 Currency: wins above replacement

```
possessions = minutes × league pace / G                      G = 48 (NBA), 40 (WNBA); pace per G minutes (season.json)
PAR = (HPM − REPLACEMENT) × possessions / 100                REPLACEMENT = −2.0 (impact.REPLACEMENT_HPM)
WAR = PAR / ppw,   ppw = sigma × sqrt(2π)                    sigma = game.params(L)["sigma"]
```

The game model's margin is Normal(mu, sigma), so one point of expected margin moves an even game's win probability by
φ(0)/sigma; points per win is its inverse: NBA sigma 12.405 → 31.1 points per win, WNBA 12.015 → 30.1. Rates: HPM
(per 100, above average) and PAR per game played. Percentiles place WAR among the season's qualified players (the
catalogue's `qualified`, minutes ≥ 20 % of the season's most) with the catalogues' mid-rank rule, and within the
position group (needs 3 qualified members); unqualified players are placed but never listed among the best. Trend:
ΔHPM against last season and last season's WAR. Leaders, 2025-26 NBA: Jokic 17.5 WAR (HPM +9.3), Gilgeous-Alexander
17.2, Wembanyama 15.4; WNBA 2026: A'ja Wilson 7.3, Veronica Burton 6.5.

### 14.2 Position groups (`classify_roles`)

ESPN lists only G, F and C (NBA 2026: 341 G, 275 F, 104 C, eight PG/SG/SF), so PG–C cannot be used. Guards = G; bigs
= C plus forwards with 150+ minutes (`ROLE_MIN`) whose box score is closer to the centres':

```
score = z(oreb100 + dreb100) + z(blk100) + z(rim_freq) − z(tpar) − z(ast100)      z over the season's qualified players
big   ⇔ score > (mean score of qualified G + mean score of qualified C) / 2
```

(`rim_freq` is skipped where a season has no shots). NBA 2026: threshold 1.75; 54 of 178 forwards are bigs
(Wembanyama, Gafford, Isaiah Jackson ...), 124 wings. Forwards under 150 minutes are wings.

### 14.3 Rest-of-season projection (`player_projection`, `projections`)

```
rate = (HPM_this × min_this + prior × K) / (min_this + K)     offence and defence likewise
prior = hpm_next of last season (ratings._last_season_values: the roster prior's value), the season before for a
        player who missed last season;   K = PRIOR_MIN = 1,000 minutes
no earlier season: prior = REPLACEMENT with K = PRIOR_MIN_NEW = 250 (impact's PRIOR_MINUTES)
minutes a game = impact.projections "min" (weights 0.5^(k/12) on his recent games)
next season = rate + impact.aging_delta(age)
```

Rosters: the store's `meta.rosters` (ESPN team rosters, refreshed by the fetcher), plus anyone on no roster who
played in the last 30 days (`RECENT_DAYS`), at his latest game's team. Ages from the current store's dates of birth.
NBA 2026-27 preseason: 627 rostered players, 504 with a prior, 123 newcomers at replacement.

### 14.4 Depth chart (`baseline_minutes`, `team_value`, `apply_moves`)

```
baseline: minutes = min(projected minutes, MAX_SHARE × G) handed out most first until 5G (240 / 200) is used
team value = Σ rate × minutes / G + REPLACEMENT × fill / G           fill = 5G − Σ minutes (net points per 100)
```

A trade: the outgoing players' baseline minutes open up at their position group. Incoming players, best rate first,
take their projected minutes (capped at MAX_SHARE × G: 38.4 / 32): first open minutes at their group, then the new
team's lowest-rated minutes at that group (the replacement fill counts as a −2.0 player there), then at the
neighbouring groups (`ADJACENT`: guards → wings → bigs, wings → guards → bigs, bigs → wings → guards), never from a
player rated at or above the newcomer. Open minutes left over go to the best remaining players at that group, each
at most `EXTRA_SHARE` × G more (12 NBA, 10 WNBA: the minutes are spread, not handed to one bench player) and up to
the cap, then the neighbours, then the fill. Δ team value = Δ net rating for the rest of the season. The same
algorithm is implemented in `docs/hardwood/assets/js/trade.js` (`applyMoves`); on 300 random trades over the 15 Oct
2026 payloads the two agree to 3e-14.

### 14.5 Grades, strengths and needs (`grade_teams`, `candidates`, `needs_payloads`)

Per team, from the baseline rotation: guards, wings, bigs, offence (Σ (o − R/2) × minutes), defence, starting five
(the five with the most minutes) and bench, each as projected WAR over a full season
(`× pace / 100 × games / ppw / G`). Percentile against the league's teams (mid-rank); grades A ≥ 80, B ≥ 60, C ≥ 40,
D ≥ 20, F below. Strengths: the three highest percentiles; weaknesses: the three lowest not already strengths; each
flagged `relative` when a strength is below the league median or a weakness above it (an elite team's "weakness").

Targets for a weakness: every player on another team with 10+ projected minutes and a value basis (not a newcomer),
in that group (for offence / defence any group, ranked by the change in that half; starting five: 28+ minutes; bench:
under 24), added to the team's depth chart with nobody going back; ranked by the gain (> 0.05 per 100); the top five
plus up to three more marked attainable. Wins: the team's `exp_w` sensitivity curve at the net gain (else
gain × pace / 100 × games left / ppw); also Δ playoff and title odds. Hints, data only: the seller's playoff
probability below 15 % ("out of contention"); the seller's own Δ from losing him (`apply_moves` with him out) above
−0.5 × his gain ("depth"); one of the seller's two most valuable players (rate − R) × minutes ("franchise"); age 31+
with the aging step; ESPN's injury report. Attainable = (out of contention or depth) and not franchise. No salaries
(no free legitimate source: not Basketball-Reference, HoopsHype or Spotrac): the pages say the cap is not checked.
Free agents are not identified.

### 14.6 Sensitivity curves (`season_sim.sensitivity`, `value.sensitivity_curves`)

`simulate(..., state={"shift": {tid: d}})` adds d to that team's season-level draw z in every simulation, so every
remaining game's margin moves by d × pace / 100 and its playoff strength by d. `sensitivity` runs the full season at
`SENS_SHIFTS` = (−6, −3, −1.5, 0, +1.5, +3, +6) for each team alone, `SENS_SIMS` = 2,000 runs a point, seed =
season + 1 throughout (common random numbers), sharing the setup (state and game means) through `state["_cache"]`;
outputs exp_w, p_playoffs, p_top6, p_conf, p_title and (NBA) p_top4 (the first four of `p_lottery_pick`). Curves
are made monotone outward from 0 (`monotone`; p_top4 decreasing) and cached under `cache/value/` on the simulation's
inputs (ratings, se, W–L, games left); a run on the same teams, grid and stage is reused for up to `SENS_TTL_HOURS` = 6
when only results or ratings have moved, so a day of games costs at most a few re-runs. The page reads curve(d) − curve(0) and adds it to the 20,000-run baseline;
beyond ±6 the edge value. Each team's curve holds the others at their ratings, so the trading teams' head-to-head
effect is ignored. Cost: about 0.32 s a run, 60 s for the NBA's 30 teams on a cache miss on an idle machine (the hourly build was
30–32 minutes before; its limit is 45). The first hourly build with this section (15 Oct 2026, 17:06 UTC) took 40.8
minutes, the value steps 1.3 s of it (a cache hit): the play-by-play pass (1,331 s against 900) and the award races
(966 s against 704) ran slower while other work loaded the machine. Without a simulation (offseason) the trade page uses the linear conversion
over a full season and shows no odds.

Example (NBA 2026-27 preseason, 15 Oct 2026, Lakers): +1.5 per 100 → 40.6 to 44.2 expected wins, playoffs 54.5 %
to 68.2 %.

### 14.7 Tests

`tests/basketball/test_value.py` (16): points per win, the position split, WAR and percentiles and the floor, the
projection blend (prior, newcomer, rookie), baseline minutes and fill, like-for-like swaps, displacement by position
(and never of a better player), next man up and replacement, zero-sum minutes, grades, target ranking and hints,
low-minute and newcomer exclusions, the needs payload, interpolation and monotone curves, and the simulation's shift
and sensitivity on a synthetic store.

---

## 15. Valuation v2, transactions and trade ratings, fantasy: `analytics/valuation.py`, `moves.py`, `fantasy.py` (16 Oct 2026)

Spec: docs/VALUE_SECTIONS.md sections 4–5. Payloads: PAYLOADS.md "Valuation, moves and fantasy". All three are built for
each league's current season by `build_hardwood.py layers_current` after the value step; each is isolated. On-field value
only: no salary or contract source (Spotrac, HoopsHype, Basketball-Reference terms forbid reuse) and no fantasy platform
data (rankings, ownership, ADP).

### 15.1 Ages (`scripts/bb_bio.py`, `analytics/bio.py`)

ESPN's core athlete records and draft lists into `data/<L>/bio.json` (DATA_PIPELINE.md 2.1b). `SeasonContext.players`
and `impact.for_season` fill missing dates of birth from it (the impact cache key and the roster-value cache key,
`roster-values-2`, include the file), so the roster prior now applies the hand-set `AGE_CURVE` step to every player, and
every season's catalogue gets ages when it is next rebuilt. Coverage: all 14,402 NBA player-seasons, 3,565 of 3,678 WNBA.

Check on past seasons (E3 style, scratch script; preseason box-score rosters for `meta.rosters`, cached impact fits, the
production prior 0.5 × b × net_last + 0.5 × (impact − mean) against each season's final net rating):

| | team-seasons | no ages | hand-set step | fitted curve | ΔMSE hand-set [95 %] | ΔMSE fitted [95 %] |
|---|---|---|---|---|---|---|
| NBA 2012–2026 | 450 | 3.030 | **2.971** | 2.987 | −0.353 [−0.742, +0.051] | −0.262 [−0.413, −0.112] |
| WNBA 2010–2026 | 190 | 3.933 | **3.886** | 3.911 | −0.374 [−1.076, +0.329] | −0.176 [−0.378, +0.043] |

On the NBA 2027 preseason the ages alone move the teams' roster impact by sd 1.28 points per 100 (−2.77 to +2.11, mean
0.00). Changing the cache key also replaced a stale cached set of last season's values (the live prior had been reading
values from before later store and model changes); the two together moved team roster impact by sd 3.0 before the mean
is removed. The win-total edges stay hidden (section 2.2).

### 15.2 Valuation v2 (`valuation.py`)

Four season slots from now, discounted `DISCOUNT` = 0.9: `Σ 0.9^k S_k A_k G_k m (r_k − R) pace / G / 100 / ppw`
(module docstring). Fits (`fits`, cached on the completed seasons' value.json and bio.json, `cache/value/
valuation_fits_<L>.json`):

- Ageing: delta method, 500+ minutes in both seasons, harmonic-mean weights, `AGING_SHRINK` = 10,000, smoothed, not centred
  (the minutes-weighted mean change of continuing players is +0.07 NBA, −0.04 WNBA). NBA (7,623 pairs): 19 +0.61, 21 +0.48,
  23 +0.30, 25 +0.14, 27 +0.03, 29 −0.01, 31 −0.20, 33 −0.29, 35 −0.33, 37 −0.53 — flatter than the hand-set curve
  (+1.2 at 19, −1.4 at 35). WNBA (1,208 pairs): 21 +0.35, 23 +0.31, 25 +0.07, 27 −0.07, 29 −0.20, 31 −0.20, 35 −0.31.
- Spread: s1 (next season around the ageing path) NBA 1.50, s2 1.83, τ 1.04; WNBA 1.96, 2.21, 1.03.
- Survival: logistic on [1, a, a²/10, HPM, log(min / 1000)], a = age − 27, outcome 100+ minutes next season given 200+
  this season: NBA 11,332 player-seasons, log-loss 0.328 against 0.433 for the base rate (84.4 %); WNBA 2,609, 0.441
  against 0.504.
- Availability mean (500+ minute players' games share): NBA 0.79, WNBA 0.92; minutes spread (sd of the log change in
  minutes a game): NBA 0.25, WNBA 0.19.

Band: 400-draw Monte Carlo (persistent error √(s1² − τ²) scaled by √(1,500 / information minutes), drift τ a season,
lognormal minutes, Bernoulli survival), fixed seed per player. Positional replacement: the mean rate of each position's
next N_teams players by depth-chart minutes after the league's rotations (top 9 NBA, 8 WNBA a team). Build cost: about 1 s.

### 15.3 Transactions and trade ratings (`moves.py`)

Parsing, deal grouping, the three valuations and grades as in the module docstring. Window: the last 365 days. On
16 Oct 2026: NBA 441 rows (235 signings, 168 releases, 66 trade sentences) into 53 deals; WNBA 123 rows, 3 deals; 56 NBA
and 6 WNBA names unmatched (two-way and G League players with no games in our data). The pick-value curve: NBA drafts
2003–2022 (20), No. 1 3.90 WAR, No. 5 2.67, round 1 mean 1.91, round 2 0.53 (WAR over the first four seasons, each
floored, discounted). Known limits: values at the time use only completed seasons (in-season form before a deadline deal
is ignored, by design: no hindsight); a pick's realised value is not tracked after the draft (it stays at curve value);
multi-team deals whose sides do not name each other are split into pairwise deals; picks in a multi-team sentence with
more than one counterparty are credited to the row's team only. Build cost: about 2 s plus at most one ESPN call.

### 15.4 Fantasy (`fantasy.py`, `research/fantasy_backtest.py`)

Projection as in the module docstring. Fitted rest factors (NBA 2024–2026, rotation players): minutes ratio by days of rest
0 / 1 / 2 / 3+ = 1.011 / 1.005 / 0.996 / 0.988 and chance of playing 0.966 / 0.996 / 1.007 / 1.032 (relative to the
average). `STD_BLEND` = 0.5 × min(1, games / 20) and the availability term were chosen on WNBA 2023–2025 (blend 0 / 0.3 /
0.5 / 0.7: next-week MAE 9.041 / 8.984 / 8.960 / 8.951, rest of season 4.222 / 4.116 / 4.088 / 4.091; availability from
the impact model's last 20 team games against this season's share: weekly total MAE 18.475 against 17.833). The opponent
factors helped slightly (WNBA 2024–25 next-week MAE 9.141 with, 9.180 without); the rate half-life (20 / 40 / 60) and a
100-minute prior barely moved anything.

Walk-forward, standard points (`scripts/bb_fantasy_backtest.py`; NBA 105 checkpoints, 6.6 minutes; WNBA 70, 1.4 minutes):

| | ours | season to date | last season | Spearman (ours / std / last) |
|---|---|---|---|---|
| NBA 2022–26, next 7 days per game (107,931 player-games) | **9.902** | 9.965 | 10.689 | 0.776 / 0.768 / 0.683 |
| NBA, next 7 days total (44,655) | **24.93** | 25.05 | 26.99 | |
| NBA, rest of season per game (39,563) | **4.278** | 4.691 | 5.593 | 0.846 / 0.837 / 0.752 |
| WNBA 2022–26, next 7 days per game (19,559) | **8.917** | 8.956 | 9.692 | 0.758 / 0.751 / 0.658 |
| WNBA, next 7 days total (8,948) | 17.13 | 17.13 | 18.95 | |
| WNBA, rest of season per game (6,856) | **4.017** | 4.269 | 5.417 | 0.857 / 0.849 / 0.747 |

Ours beats both baselines in every NBA season (all out of sample for the choices) on all three horizons, and in every WNBA
season per game and over the rest of the season; the WNBA weekly totals are level (2024 and 2025 slightly worse). Per
category the unblended model line is level with the season-to-date average (NBA 2026 points MAE 4.72 against 4.66, rebounds
1.91 / 1.91), so the gain comes from combining the two. The injury report has no history, so the backtest cannot test the
production availability (two-season share plus the report).

### 15.5 Tests

`tests/basketball/test_layers.py` (26): ages and date filling; the ageing curve, survival fit, discounting, floors and
band order, ageing's effect, positional replacement, availability, injury games; name normalisation and typos, sentence
splitting and types, plural position tags, pick parsing (counts, years, swaps, "20227"), directions and team hints, deal
pairing without day chains, pick de-duplication, the pick curve's monotonicity and pick values, grades, season dates,
no-hindsight value at the time and realised value after the date; game lines, 9-category z-scores and punts, points and
tiers, the schedule's rest days, rest and opponent factors, the backtest's Spearman and blend.
