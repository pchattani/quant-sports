# Models: technical reference

This document covers every statistical model behind The Quant Footballer (the repo's `oddsmarkets` package and `scripts/`). It is written for whoever maintains or extends the models. Each parameter and formula below was read from the code. Where the code and its own docstrings disagree, this document follows the code and says so.

Paths are relative to the repository root. "The build" means `scripts/build_site_all.py`, which writes the combined site under `docs/site/data/`. The Argentine league is built by `scripts/build_site_liga.py`, which `build_site_all.py` calls. The World Cup site (`docs/wc/`) has its own legacy build, `scripts/build_site_wc.py`.

---

## 1. Overview

### 1.1 How the models feed each other

```
Sofascore stores (docs/site/data/<slug>/store.json, docs/liga/data/liga_store.json)
  |
  | training_frame(): finished matches; goals, plus team xG where lineups exist
  |
  +--> per-league Dixon-Coles fit --------------------+
  |                                                   |
  +--> POOLED Dixon-Coles fit (12 leagues + all       |
  |    non-international cups, clubs "<league>:<club>")|
  |      |-- LeagueView / CupView -------------------->+
  |      +-- pool.json: club strength, league factors  |
  |            +-- players_global.json (*_adj rates)   |
  |                                                    v
  +--> Elo replay (leagues; flat in cups) ----> EnsembleModel (DC blended with Elo,
  |                                             draw_rate / lam_scale from empirical_calibration)
  |                                               |-- predict_fixture -> fixtures.json (H/D/A, fair odds)
  |                                               |-- League/Cup/Liga simulators -> table, probs, bracket, history
  |                                               |      +-- GoldenBootModel -> player_leaders.json
  |                                               |      +-- cup winner distributions -> fixed brackets
  |                                               |-- neutral_strength -> strength.json (power rankings)
  |                                               +-- markets.build_match_markets (The Odds API) -> market_odds.json
  |
  +--> INTERNATIONAL Dixon-Coles fit (national teams only; not simulated)
  |      +-- Ensemble -> fixture lines; nations.json
  |
  +--> player aggregates -> per-90s -> positional percentiles -> players_live.json
         +-- global pool, league-adjusted -> players_global.json
```

### 1.2 Model inventory

| Model | Code | Used by |
|---|---|---|
| Dixon-Coles (DC) | `oddsmarkets/sports/world_cup/models/dixon_coles.py` (re-exported from `oddsmarkets/football/core/__init__.py`) | every competition |
| Elo | `oddsmarkets/sports/world_cup/models/elo.py` | every competition |
| EnsembleModel | `oddsmarkets/sports/world_cup/models/ensemble.py` | every competition |
| Empirical calibration | `empirical_calibration` in `oddsmarkets/football/competitions/liga/store.py` (aliased in `league/store.py`) | leagues, cups, internationals |
| Pooled fit and read-back | `fit_pooled`, `pooled_training_frame`, `LeagueView`, `CupView` in `scripts/build_site_all.py`; `oddsmarkets/football/analytics/pool.py` | pooled leagues, all club cups, pool.json |
| International fit | `fit_international`, `build_nations` in `scripts/build_site_all.py` | national-team competitions, nations.json |
| Simulation primitives | `oddsmarkets/football/core/simulation.py` | all three vectorised simulators |
| League simulator | `oddsmarkets/football/competitions/league/simulator.py` | 12 leagues |
| Liga simulator | `oddsmarkets/football/competitions/liga/simulator.py` | Argentina |
| Cup simulator | `oddsmarkets/football/competitions/cup/simulator.py` | 40 club cups |
| Strength / power rankings | `oddsmarkets/football/competitions/liga/strength.py` | strength.json everywhere |
| Top scorer (Golden Boot) | `oddsmarkets/sports/world_cup/models/player_goals.py` | leagues, Argentina, World Cup |
| Player, team, match analytics | `oddsmarkets/football/analytics/{players,teams,matches}.py` | every competition |
| Market odds | `oddsmarkets/football/core/markets.py`, `oddsmarkets/sports/world_cup/trading/the_odds_api.py`, `scripts/fetch_market_odds.py` | market_odds.json |
| Player value (goals added, GAR, PAR), fair value index | `oddsmarkets/football/analytics/value.py`, `value_payloads.py` | `value/` payloads, club strengths and needs |
| Sensitivity curves | `oddsmarkets/football/analytics/sensitivity.py` | `<league>/sensitivity.json`, the transfer simulator |

The site covers 69 competitions: 12 leagues in `LEAGUES` (`oddsmarkets/football/competitions/league/config.py`), Argentina, and 56 entries in `CUPS` (`oddsmarkets/football/competitions/cup/config.py`). The 56 cup entries are 14 continental/world competitions, 26 national cups and super cups, and 16 national-team competitions.

---

## 2. Match model: Dixon-Coles

**Purpose.** Gives each team an attack and a defence parameter and returns a full score distribution for any fixture.

**Inputs.** A DataFrame with `home_team, away_team, home_goals, away_goals, match_date`. It may also carry `weight` (0 to 1) and `home_xg, away_xg`. Frames are built by `training_frame` in `league/store.py`, `liga/store.py` and `cup/store.py`. Each includes every finished match in the store (all stages; a league store holds the current and previous season). Team xG comes from `team_xg_map` in `liga/store.py`: the sum of the players' Sofascore `expectedGoals` in a match. It exists only for matches with lineups, which the fetchers collect for the current season only.

### 2.1 Parameterisation

```
lam_h = exp(att[home] + def[away] + home_adv)
lam_a = exp(att[away] + def[home])
```

A higher `att` means more goals scored. A higher `def` means more goals conceded, so a good defence has a low `def`. `home_adv` is a single global term, and `neutral=True` at prediction sets it to 0.

The parameter vector is `[att_0..att_{n-1}, def_0..def_{n-1}, home_adv, rho]`, so it has 2n + 2 entries. Teams are sorted alphabetically. The first team's `def` is fixed at 0 through L-BFGS-B bounds (the "anchor"). The ridge penalty also identifies the scale on its own.

### 2.2 Likelihood

Each row gets a time weight:

```
w_i = exp(-xi * days_ago_i) * weight_i        days_ago measured from datetime.now(UTC)
```

**Goals rows** (rows without finite xG on both sides) use the Dixon-Coles likelihood: independent Poisson with the low-score correction.

```
ll_i = log Pois(hg; lam_h) + log Pois(ag; lam_a) + log(max(tau, 1e-10))

tau(0,0) = 1 - lam_h*lam_a*rho
tau(1,0) = 1 + lam_a*rho
tau(0,1) = 1 + lam_h*rho
tau(1,1) = 1 - rho
tau(x,y) = 1 otherwise
```

**xG rows** replace the goals entirely with a continuous Poisson likelihood on the xG values. There is no tau for these rows.

```
ll_i = hx*log(lam_h) - lam_h - lgamma(hx+1) + ax*log(lam_a) - lam_a - lgamma(ax+1)
```

This is a substitution, not a blend. A match with xG contributes only its xG, and a match without xG contributes only its goals. Club xG is used raw (uncalibrated Sofascore sums). The World Cup path is the exception: it rescales xG to goals (section 12.3).

**Objective.**

```
minimise  -sum_i w_i * ll_i  +  ridge * (sum att^2 + sum def^2)
```

The ridge is not scaled by the number of matches and does not apply to `home_adv` or `rho`. Because the time weights shrink as the data ages while the ridge stays fixed, the effective regularisation strengthens with wall-clock time. Section 14 covers the consequence.

**Fitting.** `scipy.optimize.minimize(method="L-BFGS-B")` with numerical gradients (no `jac` is supplied). Options: `maxiter=5000`, `maxfun=max(50000, 200*n_params)`, `ftol=1e-8`. Starting point: all team parameters 0, `home_adv=0.1`, `rho=-0.1`. Bounds: `rho` in [-0.99, 0], `home_adv` free. A non-converged fit logs a warning and is still used.

### 2.3 Prediction

`predict_match(home, away, neutral=True, max_goals=8)` builds a 9x9 matrix: `Pois(i; lam_h) * Pois(j; lam_a) * tau(i, j)`. It clamps negative cells to 0 and renormalises, which discards the mass above 8 goals. Home win, draw and away win are the lower triangle, trace and upper triangle. A team missing from the fit gets `att = def = 0`, the centre of the ridge prior.

### 2.4 Parameters

| Name | Class default | Where overridden |
|---|---|---|
| `xi` (daily decay) | 0.0018 | per league from `model_params.json` (0.001 to 0.008); pooled 0.0035; own-fit cups 0.0035; international 0.002 |
| `ridge` | 1.0 | per league (0.25 to 2.0); pooled 1.0; cups 1.0; international 1.0 |
| `max_goals` | 8 | `LeagueConfig`, `CupConfig`, `LigaConfig` all 8 |
| rho bounds | [-0.99, 0] | fixed |
| minimum rows to fit | 50 (league, cup own fit, Liga, pooled); 30 (international) | build code |

With xi = 0.0035 the half-life is ln 2 / 0.0035, about 198 days. With xi = 0.008 it is about 87 days.

**Caveats.**
- `rho` is identified only by goals rows. When every row carries xG, rho stays at its starting value. The current `nations.json` reports `rho = -0.1` exactly, which fits this pattern.
- The fit has no neutral-venue term. Neutral matches (tournament finals, neutral cup rounds, the international tournaments) are fitted with `home_adv` credited to whichever side the feed lists as home. Neutrality is honoured only at prediction time and in the Elo replay.
- For about 530 clubs the pooled fit has roughly 1,060 parameters. With finite-difference gradients it was the slowest step of the build (about ten minutes on this PC). Since 2 October 2026 the build's fits (pooled, the leagues' own fits and Argentina) pass `analytic_grad=True`, which hands L-BFGS-B the exact gradient of the same objective: the pooled fit takes about a second and lands on the same optimum (parameters within about 1e-4). The class default is still the finite-difference path, so the World Cup build and the golden test are unchanged.

### 2.5 Market-rate rows (since 2 October 2026)

`oddsmarkets/football/sources/market_rates.py` adds one extra training row per finished league match that football-data.co.uk lists with closing prices: the pair of goal rates (home, away) that reproduces the de-vigged closing 1X2 and over/under 2.5 under a Dixon-Coles score model (rho -0.05), carried in the xG columns (so the row uses the continuous-Poisson path) with weight `W_MKT = 3`. The match's own goals or xG row stays as it was. Closing prices are Pinnacle's where the files have them (to January 2026), else the Betfair exchange close, else the market average; the research found average-close rates exactly as useful as Pinnacle's (difference -0.0002 nats, CI -0.0005 to +0.0001).

- Where: `pooled_training_frame` (league parts) and `build_model`'s own fit in `scripts/build_site_all.py`, and the Argentine fit in `scripts/build_site_liga.py`. The rows go to the Dixon-Coles fit only; Elo, `empirical_calibration` and the seeding read the plain one-row-per-match frame.
- Leagues: the twelve with a football-data file (not the Saudi Pro League); fixtures are matched to Sofascore events by day and score (`football_data.map_to_sofascore`).
- No leakage: only closing prices of matches already played enter a fit.
- Why: in the walk-forward backtest (2019/20 onwards, production parameters, all twelve leagues, 30,854 matches) it cut the 1X2 log-loss by 0.0079 (95% CI 0.0065 to 0.0092) and improved every league. See `docs/research/football_edge.md`.
- Data: `data/football/odds/raw/` (git-ignored). The build refreshes the current season's files at most once a day (`market_rates.refresh`, skipped with `--no-market`). Without the files the module adds nothing, so CI or a fresh clone builds exactly the goals/xG model. `--no-market-rates` turns it off.

---

## 3. Elo

**Purpose.** A slow-moving rating that acts as a prior and a fallback for DC, and supplies the `elo` column and trajectory in strength.json.

**Maths** (`EloRatings`):

```
dr  = R_home - R_away + (home_advantage if not neutral else 0)
E_h = 1 / (1 + 10^(-dr/400))
S_h = 1 (win), 0.5 (draw), 0 (loss)
R_home += K * (S_h - E_h);  R_away += K * ((1 - S_h) - (1 - E_h))
```

**Goal difference is ignored.** Only win, draw or loss enters the update, and there is no margin-of-victory multiplier. The update uses the same home-advantage-adjusted expectation that the model predicts, so home wins are not over-rewarded.

**Seeding.** `seed_from_ranking(rank)` sets `R = 1500 + (n_teams - rank) * 15`. Unseeded teams sit at `base = 1500`.

| Parameter | Default | Where set |
|---|---|---|
| `K_WORLD_CUP` | 60 | `elo.py` |
| `K_QUALIFIER` | 40 (also used for an unknown `tournament_type`) | `elo.py` |
| `K_FRIENDLY` | 20 | `elo.py` |
| `K_LEAGUE` | 20 | `elo.py`; per league `k_league` from `model_params.json` (15 to 30) |
| `home_advantage` | 0.0 (Elo points) | leagues: `elo_home_advantage` (30 to 70); cups and internationals: 50.0 |
| seed scale | 15 points per rank | `_rank_to_elo` |

**How each build uses Elo.**
- **Leagues** (`build_model`): seeded from last season's final table in `league/data/seasons.json` (`previous_rank`). Clubs missing from it (promoted clubs) are seeded at rank `n_teams`, the bottom. The whole training frame is then replayed with `tournament_type="league"` and `neutral=False`.
- **Argentina** (`scripts/build_site_liga.py`): seeded from `previous_anual_rank` in `liga/data/season_meta.json`, falling back to the order of the state's team list. Replayed the same way as the leagues.
- **Cups** (`build_cup`): `EloRatings(k_league=20, home_advantage=50.0)` with **no seeding and no updates**, so every club is at 1500. This matters only in the fallback described in section 4.
- **Internationals** (`fit_international`): no seeding. Every national-team match is replayed with K = 20 (`"league"`), HA = 50, and the row's `neutral` flag. Friendlies count in full here; the half weight applies only to DC.
- **World Cup**: see section 12.3.

---

## 4. EnsembleModel

**Purpose.** Blends DC and Elo into one `MatchProbabilities` object: win/draw/loss, lambdas and a score matrix. Every simulator and payload goes through it.

### 4.1 Effective DC weight (`_adaptive_dc_weight`)

```
dc_w = 0                               if DC not fitted, or |rho| >= 0.99
     = max(dc_weight - 0.30, 0.40)     if either team has no attack_ parameter
     = dc_weight                       otherwise
elo_w = 1 - dc_w
```

### 4.2 Elo side

The Elo logistic `p_E = E_h` is treated as P(home win). The rest of the mass is split with the empirical draw rate:

```
elo_home = p_E
elo_draw = (1 - p_E) * draw_rate
elo_away = (1 - p_E) * (1 - draw_rate)
```

An Elo score matrix comes from independent Poisson distributions:

```
lam_h_E = max(p_E * lam_scale, 0.3)
lam_a_E = max((1 - p_E) * lam_scale * a, 0.3)     a = 1 if neutral else away_penalty
```

### 4.3 Blend

```
H = dc_w*H_DC + elo_w*elo_home, and likewise for D and A, then renormalised
score_matrix = normalise(dc_w*M_DC + elo_w*M_Elo)
lambda_home/away = the DC lambdas (the Elo lambdas on the Elo-only path)
```

When `dc_w == 0` (the Elo-only path), W/D/L are read from the Poisson matrix itself, so no outcome can be clamped to zero.

**Inconsistency to know about.** On the blended path, the returned H/D/A (a linear blend using Elo's draw-rate split) differ from the W/D/L implied by the blended `score_matrix` (which uses Elo's Poisson matrix). For example, with dc_w = 0.8 and a fixture from the golden test: H/D/A = 0.708/0.176/0.116, while the matrix gives 0.692/0.204/0.104. The simulators sample from the matrix. `advance_matrix`, `fixtures.json` and `strength.json` read H/D/A. The two views of the same fixture can differ by a few points.

### 4.4 Calibration (`empirical_calibration`)

Measured from the model's own training frame:

```
draw_rate     = share of rows with home_goals == away_goals
mean_goals    = (mean home goals + mean away goals) / 2
lam_scale     = 2 * mean_goals
home_win_rate = share of home wins (reported only)
empty frame   -> {draw_rate 0.25, lam_scale 2.6, mean_goals 1.3, home_win_rate 0.45}
```

Cups with fewer than 30 training rows use the empty-frame defaults.

| Parameter | Class default (WC) | Leagues / Argentina | Cups | International |
|---|---|---|---|---|
| `dc_weight` | 0.70 | tuned (0.65 to 1.0); 0 if DC unfitted | 1.0 (0 if unfitted) | 1.0 |
| `draw_rate` | 0.25 (`WC_DRAW_RATE`) | empirical | empirical if >= 30 rows | empirical |
| `lam_scale` | 2.6 (`WC_LAM_SCALE`) | empirical | empirical if >= 30 rows | empirical |
| `away_penalty` | 0.75 (`WC_AWAY_PENALTY`) | 1.0 | 1.0 | 1.0 |

With `dc_weight = 1.0` (cups, internationals, the pooled leagues), Elo enters only when a team is unknown to DC, and then at weight 0.30. In cups that Elo is flat at 1500 with HA 50, so the fallback blends in a pure home-advantage prior: p_E = 0.571 for the home side.

### 4.5 Fair odds and the fixture line

`predict_fixture` in `scripts/build_site_all.py` produces the model line on each unplayed fixture in `fixtures.json`:

| Field | Definition |
|---|---|
| `h, d, a` | Ensemble H/D/A (section 4.3) |
| `lh, la` | DC lambdas (Elo lambdas on the Elo-only path) |
| `o25` | sum of matrix cells with i + j >= 3 |
| `btts` | sum of matrix cells with i >= 1 and j >= 1 |
| `score, p_score` | argmax cell of the matrix |
| `fair` | `[1/h, 1/d, 1/a]` rounded to 2 dp; `None` when p <= 0.005. No margin. |

A fixture is priced as neutral if the raw match has `neutral` set, or if the competition's `neutral_when` rule matches (cup final or neutral rounds, international tournaments with `neutral_venues`).

---

## 5. Tuning and backtests

### 5.1 `scripts/tune_league_models.py` (all leagues, including Argentina)

**What is tuned:** `xi`, `ridge`, `elo_home_advantage`, `k_league` and `dc_weight`, per league.

**Metric:** walk-forward three-way log-loss on each league's own matches. The Brier score is also reported. Walk-forward means expanding-window folds: `min_train=200` and `folds=6`, with fold step `(n - 200) // 6`. Each fold fits DC and replays Elo on `df.iloc[:s]` and scores `df.iloc[s:e]`. Elo in folds is seeded by points per game over the training window, the closest stand-in for last season's table.

**Staged grid search.** Stage A fits DC alone (xi x ridge at dc_weight 1). Stage B fits Elo alone (HA x K at dc_weight 0). Stage C searches the blend weight. The staging ignores interactions between the stages.

| Grid | Values |
|---|---|
| `xi` | 0.001, 0.002, 0.0035, 0.005, 0.008 |
| `ridge` | 0.25, 0.5, 1.0, 2.0 |
| `elo_home_advantage` | 30, 50, 70, 90, 110 |
| `k_league` | 15, 20, 30 |
| `dc_weight` | 0.5, 0.65, 0.8, 0.9, 1.0 |
| pooled grid | xi in {0.002, 0.0035, 0.005} x ridge in {0.5, 1.0}; other params = global best |

**Candidates per league:**
- `per-league`: the league's own best.
- `global`: one parameter set minimising the match-weighted log-loss across leagues.
- `pooled`: one DC fit over all leagues except Argentina, with prefixed teams and per-league Elo and calibration. This tuning pool contains **leagues only, no cups**, unlike the build's pooled fit. Its walk-forward uses `min_train = 30%` of the pooled frame.
- `default`: `DEFAULTS`.

Where the pooled fit ran, all methods are re-scored on the pooled test rows so they are compared on the same matches.

**Selection.** `global` is the reference. `pooled`, then `per-league`, replaces the current choice only if it beats that choice by `margin = 0.002` log-loss. The winner must also beat the better of two baselines: uniform (ln 3 = 1.0986) and a home-advantage-only prior (H/D/A frequencies over the first 200 rows). Otherwise `method = "default"` with `DEFAULTS`.

**Output.** `oddsmarkets/football/competitions/league/data/model_params.json` (current file tuned 2026-09-22):

| League | Method | xi | ridge | Elo HA | K | dc_weight | log-loss | best baseline | n_eval |
|---|---|---|---|---|---|---|---|---|---|
| premier-league | pooled | 0.0035 | 1.0 | 50 | 30 | 1.0 | 1.05075 | 1.09861 | 230 |
| la-liga | global | 0.002 | 2.0 | 50 | 30 | 1.0 | 0.99241 | 1.04412 | 249 |
| serie-a | per-league | 0.001 | 1.0 | 30 | 15 | 0.65 | 0.97039 | 1.07924 | 230 |
| bundesliga | pooled | 0.0035 | 1.0 | 50 | 30 | 1.0 | 0.98656 | 1.07937 | 144 |
| ligue-1 | pooled | 0.0035 | 1.0 | 50 | 30 | 1.0 | 1.03116 | 1.09861 | 154 |
| eredivisie | per-league | 0.001 | 0.25 | 30 | 15 | 1.0 | 0.99686 | 1.08738 | 184 |
| primeira-liga | pooled | 0.0035 | 1.0 | 50 | 30 | 1.0 | 0.95242 | 1.09688 | 170 |
| brasileirao | global | 0.002 | 2.0 | 50 | 30 | 1.0 | 1.01356 | 1.05355 | 370 |
| mls | pooled | 0.0035 | 1.0 | 50 | 30 | 1.0 | 1.05445 | 1.06665 | 414 |
| saudi-pro-league | pooled | 0.0035 | 1.0 | 50 | 30 | 1.0 | 0.94208 | 1.08036 | 169 |
| liga-argentina | per-league | 0.008 | 2.0 | 70 | 30 | 0.8 | 1.06549 | 1.08061 | 190 |
| liga-mx | per-league | 0.005 | 2.0 | 50 | 15 | 0.8 | 1.04789 | 1.0687 | 216 |
| belgian-pro-league | per-league | 0.001 | 0.25 | 30 | 20 | 0.8 | 0.96908 | 1.06616 | 184 |

The file's `global` set is xi 0.002, ridge 2.0, HA 50, K 30, dc_weight 1.0. Its `pooled` set is xi 0.0035, ridge 1.0, HA 50, K 30, dc_weight 1.0.

**How the build reads it.** `model_params_for(slug)` in `scripts/build_site_all.py` returns `{**DEFAULT_PARAMS, **tuned["params"]}` and the method, or `DEFAULT_PARAMS` with `"default"`. `DEFAULT_PARAMS = {elo_home_advantage 65.0, k_league 20, dc_weight 0.80, ridge 0.5, xi 0.0035}`, the same as the tuner's `DEFAULTS`.

A league whose method is `pooled` uses `LeagueView` over the build's pooled fit, whose xi and ridge come from the file's `pooled` block. If that fit is unavailable, the league falls back to its own fit with the same params and reports `"pooled (fit unavailable; own fit)"`.

`scripts/build_site_liga.py` starts from its own constants (`ELO_HOME_ADVANTAGE 70`, `ELO_K_LEAGUE 20`, `DC_WEIGHT 0.80`, `DC_RIDGE 0.5`, `DC_XI 0.0035`) and overrides them with the `liga-argentina` entry when present. The effective Argentine model is therefore xi 0.008, ridge 2.0, HA 70, K 30, dc_weight 0.8.

### 5.2 `scripts/tune_liga_model.py` (Argentina, older standalone tuner)

- Full grid search: xi {0.0015, 0.0025, 0.0035, 0.0045, 0.006} x dc_weight {0.5, 0.65, 0.8, 0.9} x ridge {0.2, 0.5, 1.0} x HA {0, 30, 50, 70, 90, 110} x `elo_rank_scale` {8, 10, 15}.
- Walk-forward setup: `folds=5`, `min_train=150`. Data comes from `liga/data/history_matches.csv`, or from a store with `--store`.
- Scoring: log-loss (primary) and Brier, against the same two baselines.
- It prints constants to paste into `build_site_liga.py` and writes nothing into the build.
- Elo in folds is seeded alphabetically, which `tune_league_models.py` notes handicaps Elo.
- `elo_rank_scale` has no effect: `evaluate` never passes it, and the build's `ELO_RANK_SCALE = 10.0` is never read (seeding always uses 15 points per rank).

### 5.3 `scripts/backfill_liga_history.py`

This is a local-only Sofascore job, not a model. It writes the inputs the Argentine model cannot derive, into `oddsmarkets/football/competitions/liga/data/`:
- `promedios_history.json`: accumulated points and matches per club for the seasons before the current one, over the `promedio_seasons = 3` window.
- `season_meta.json`: the Apertura champion and the previous Tabla Anual order, which seeds Elo.
- `history_matches.csv`: a multi-season DC training set with per-match xG, capped by `--xg-cap` (default 1200).

Tables are derived from the match dump and checked for points conservation (`check_consistency`), not scraped.

### 5.4 Tests

`tests/test_backfill_and_tuning.py` covers the offline pieces of `backfill_liga_history.py` and `tune_liga_model.py`: points tables, the consistency check, promedio accumulation, the log-loss and Brier edge cases (uniform = ln 3, finite at p = 0), outcome encoding and baselines. `tune_league_models.py` has no direct tests.

---

## 6. The pooled cross-competition fit

**Purpose.**
- One DC surface for every club, so that leagues can be compared.
- The model for every club cup, which needs clubs from several leagues on one scale.
- The scoring factors that put players from different leagues on one footing.

**Inputs** (`pooled_training_frame`):
- Every league in `LEAGUES` (not Argentina), with teams renamed `"<league-slug>:<club>"`.
- Every cup store whose `family != "international"`. A cup entrant is renamed to `"<league>:<club>"` when its country maps through `COUNTRY_LEAGUE` (`cup/config.py`, keyed by ISO alpha-3 and FIFA codes) to a followed league and the club appears in that league's frame. Otherwise it keeps the cup's prefix, `"<cup-slug>:<club>"`.

Cup matches between clubs of different leagues are the only edges connecting the leagues' parameter blocks. Without them the leagues would be separate components, identified only by the ridge.

**Fit** (`fit_pooled`): `DixonColesModel(xi, ridge)` from `model_params.json["pooled"]` (0.0035 / 1.0), falling back to `DEFAULT_PARAMS`. It requires at least 50 rows and runs once per build whenever any cup or pooled league is built. `LeagueView` and `CupView` strip the prefixes so `EnsembleModel` and the strength module read the pooled parameters under plain names.

**Consequences of the prefixing:**
- A club from a league the site does not follow appears once per cup it plays in. Argentine and lower-division clubs are examples: a club can exist as both `libertadores:X` and `copa-argentina:X`, with no shared parameters.
- `COUNTRY_LEAGUE` maps ARG to `liga-argentina`, but Argentina is not in the pooled league set, so Argentine clubs always carry cup prefixes. Argentina's own model is fitted separately (section 8.2).

### 6.1 Read-back: `oddsmarkets/football/analytics/pool.py`

`build_pool` works from the pooled parameters.

```
att_bar, def_bar = mean attack / defence over clubs whose prefix is a league (not cup prefixes)
avg club       = (att_bar, def_bar)

for each club c:
  M = dc_score_matrix(att_c, def_c, att_bar, def_bar, rho, home_adv=0)    neutral venue
  strength  = 3*P(win) + P(draw)          expected points per game vs the pool-average club
  xg_for    = exp(att_c + def_bar)
  xg_against= exp(att_bar + def_c)

for each league L (mean over its clubs):
  factor_att = exp(def_bar - mean_def_L)   scoring-rate multiplier for players (<1 = weaker defences)
  factor_def = exp(att_bar - mean_att_L)
  strength   = mean club strength; rank by it
  connection = number of cup-match appearances by L's clubs
```

`connection` counts every cup appearance, including domestic cups (FA Cup, Copa del Rey and so on) whose matches mostly link a league to itself or to cup-prefixed lower-division clubs. It overstates how well a league is bridged to the others.

**Continental blocks and bridges.** `BLOCKS` maps each league and continental cup to Europe, South America, North America, Asia, Africa or World (Intercontinental Cup, Club World Cup). Clubs under a cup prefix take that cup's block. `block_bridges` counts cup matches whose two clubs sit in different blocks. The latest `pool.json` (2026-09-29) shows:

```
Asia|World 3, North America|South America 1, South America|World 1, Europe|South America 1
```

That is six cross-block matches in total. Within Europe the UEFA competitions connect the leagues every week. Between blocks, the relative level (for example Brasileirão against the Premier League) rests on a handful of Club World Cup and Intercontinental Cup results, time-decayed. The ridge pulls every block toward the same centre, so cross-block league rankings mostly reflect each block's internal spread and the ridge, not measured strength differences. In the current file the Brasileirão ranks 2nd and Liga MX 3rd among the 12 leagues. Treat cross-block rankings and factors as weakly identified. The payload exposes `bridges` so the front-end can say this.

**Outputs.** `docs/site/data/pool.json`, with `model {rho, home_adv, attack_mean, defence_mean, max_goals, n_clubs}`, `leagues`, `clubs` and `bridges`. The current file has 531 clubs, rho -0.0431 and home_adv 0.257. `factor_att` feeds `players_global.json` (section 11.2).

---

## 7. The international fit

**Purpose.** Prices fixtures for, and ranks, national teams. It is separate from the club pool.

**Inputs.** Every store in `INTERNATIONALS` (the 16 cups with `family == "international"`), via `international_training_frame`:
- `weight = 0.5` for `friendly=True` competitions (only `friendlies`), otherwise 1.0.
- `neutral = cfg.neutral_venues`, which is true for the World Cup, Euro, Copa América, AFCON, Asian Cup and Gold Cup.

**Fit** (`fit_international`):
- `DixonColesModel(xi=0.002, ridge=1.0)` on the concatenated frame, with at least 30 rows. The `neutral` column is dropped before fitting, so one `home_adv` serves qualifiers and neutral finals alike, as the payload note says.
- Elo: `EloRatings(k_league=20, home_advantage=50.0)`, unseeded, replayed with each row's neutral flag.
- `EnsembleModel(dc_weight=1.0, empirical draw_rate / lam_scale, away_penalty=1.0)`.

**Use.**
- National-team competitions (`kind="international"`) are **not simulated**. `build_international` writes fixtures with the model line (neutral where `neutral_venues`), tables and the knockout ladder as drawn, players and strength. `n_sims` is 0 and `probs.json` is empty.
- `build_nations` writes `docs/site/data/nations.json`. For each nation, strength = 3·P(win) + P(draw) against the mean nation (mean attack and defence over all fitted nations) at a neutral venue, from `dc_score_matrix`. The file also carries attack, defence, Elo, matches played and confederation (competition hint, else `confederation_of`).

**Caveat: the fit is thin.** The current `nations.json` has 48 nations, 36 of them with fewer than 5 matches in the stores. Its calibration implies about 52 training matches, and rho sits exactly at its starting value of -0.1. Ranks outside the top handful are mostly the ridge prior.

---

## 8. Simulators

### 8.1 Shared primitives: `oddsmarkets/football/core/simulation.py`

- **`ScoreSampler`** caches one flattened score CDF per `(home, away, neutral)`, so the model is called once per pairing. Sampling is `searchsorted(cdf, U)`, then `divmod(idx, 9)` to get (home goals, away goals). A degenerate matrix (sum <= 0 or non-finite) falls back to independent Poisson(1.2).
- **`advance_matrix`**: P(home side advances) in a single-leg tie, predicted with `neutral=False`. A draw goes to extra time and penalties; extra time is weighted by strength and the shootout is a coin flip.

  ```
  A1[h,a] = H + D * (etw * H/(H+A) + (1 - etw) * 0.5)        etw = extra_time_weight = 0.5
  ```

- **Neutral single leg** (cup neutral rounds, the Argentine final): `p = 0.5 * (A1[h,a] + 1 - A1[a,h])`. This symmetrises home advantage rather than calling the model with `neutral=True`.
- **`two_leg_advance_matrix`**: `out[a,b]` is P(a advances) when **b hosts the second leg**. It convolves the goal-difference PMFs of leg 1 (a at home) and leg 2 (b at home, flipped) to get the aggregate GD. There is no away-goals rule. A level aggregate is split exactly as a single-leg draw.
- **`PairSampler`**: for pairings that vary per simulation (the Belgian split). It gathers the CDF rows per simulation.
- **`rank_table`**: lexsort on ordered tiebreak keys, descending, with a final uniform random jitter. This is the drawing of lots, and it avoids an alphabetical bias.

**Simulation counts.** `n_sims = 100_000`, `sim_chunk = 25_000` and `random_seed = 42` in `LeagueConfig`, `CupConfig` and `LigaConfig`. The World Cup uses `N_SIMS = 100_000`. `--sims` and `--seed` override them. The Monte Carlo standard error is at most sqrt(0.25/1e5), about 0.0016.

Points quantiles (`p05/p50/p95`) come only from the first chunk's first 2,000 simulations: the sample is kept while `len(samples) * chunk < 5000`. The same holds for the Argentine promedio quantiles.

### 8.2 League simulator: `oddsmarkets/football/competitions/league/simulator.py`

**Process.**
1. Seed points, GF, GA and wins from finished matches.
2. Sample every remaining non-playoff fixture for all simulations at once.
3. Rank with `cfg.tiebreak`.

**Tiebreaks.**
- `TIEBREAK_GD = (pts, gd, gf)` is the default.
- `TIEBREAK_WINS = (pts, w, gd, gf)` applies to the Brasileirão and MLS.
- Head-to-head is **not simulated**. La Liga and Serie A carry `h2h_tiebreak=True`, but that flag only drives the methodology text; ties are resolved by GD, GF and then lots. The approximation matters only for exact points ties.

**Outputs.**
- `p_position`; `p_title` (1st, or 1st after the split); `expected_points`; points quantiles.
- `p_band`: sums of the position distribution over each `Band` (continental places, relegation, playoffs). These use the conference table for MLS and the post-split table for Belgium.
- `team_goals_mean`, fed to the top-scorer model.

**Belgian split** (`SplitConfig(top=6, europe=6, relegation=6)`, `halve_points=True`):
- After the regular season each simulation splits its own table into groups of 6.
- Carried points are `ceil(points / 2)`. GD and GF carry over unhalved.
- Each group plays a double round-robin sampled per simulation. The three-point win is hard-coded here. The group is then ranked on (pts, gd, gf, lots).
- The champion is first in the championship group, and the bands read the post-split order.
- The split is always simulated from the full regular-season table. The state has no notion of a split already under way.

**MLS playoffs** (`PlayoffConfig(kind="mls")`, per conference):
- Seeds 1 to 7 qualify directly. 8 hosts 9 in a single wildcard match.
- Round One is best-of-three: 1 v wildcard winner, 2 v 7, 3 v 6, 4 v 5, with the higher seed hosting games 1 and 3.

  ```
  p_h = A1[hi,lo], p_a = 1 - A1[lo,hi]
  P(series) = p_h*p_a + p_h*(1-p_a)*p_h + (1-p_h)*p_a*p_h
  ```

- Winners are re-seeded (best v worst). Semi-finals and conference finals are single matches hosted by the better seed.
- MLS Cup is hosted by the finalist with more regular-season points (key pts*1000 + gd + jitter).
- Every tie uses `A1`, including the extra-time split. The config docstring says Round One games go straight to penalties, but the code applies the same extra-time weighting.
- Outputs: `p_playoffs`, `p_reach[round]` for wc, r1, csf, cf, final, and `p_cup`.

**Liga MX Liguilla** (`kind="liguilla"`):
- Play-in: 7 hosts 8 and 9 hosts 10, single leg with `A1`. The 7v8 loser hosts the 9v10 winner for seed 8.
- Quarter-finals are 1v8, 2v7, 3v6 and 4v5. Semi-finals and the final are re-seeded. All three rounds are two-legged, with the higher seed at home in the second leg.
- Two-legged ties use `two_leg_advance_matrix` with `extra_time_weight = 1.0`, so a level aggregate goes entirely by the strength share H/(H+A). The config says a level aggregate favours the *higher seed*; the code approximates that with relative strength, and applies it in the final too.

**Forced results.** Decided playoff ties are forced by club pair (`playoff_results` in `league/store.py`). The rule counts decisive games: one decided game, or `round_one_best_of // 2 + 1 = 2` wins, settles a pair. For the two-legged Liguilla this means a tie with only its first leg played is forced to that leg's winner. A 1-1 split in leg wins stays unforced even when the aggregate is decided.

**Outputs.** In `docs/site/data/<league>/`: `table.json`, `probs.json`, `bracket.json` (MLS, Liga MX), `history.json` (run snapshots) and `meta.json` (params, calibration, method).

### 8.3 Argentine simulator: `oddsmarkets/football/competitions/liga/simulator.py`

The format is in `LigaConfig` (`liga/config.py`, 2026): 30 clubs in zones A and B of 15. Each club plays 16 matches per tournament (14 in its zone plus 2 interzone).

**Process.**
- **Zone phase.** Only the live tournament's remaining fixtures are simulated. Each zone is ranked by (pts, gd, gf, lots), and the top 8 per zone qualify.
- **Playoffs.** Single-leg octavos, cuartos, semis and final on a **fixed tree**, `PLAYOFF_PAIRINGS` (A1-B8, A4-B5, A2-B7, A3-B6, B1-A8, B4-A5, B2-A7, B3-A6), with adjacent slots feeding the next round. The better zone rank hosts; when the zone ranks are equal, the left slot hosts. The final is neutral (`final_at_neutral_venue`). Played ties are forced by `"<round>:<slot>"`, not by pair.
- **Tabla Anual.** Zone-phase points from both tournaments, ranked by (pts, gd, gf, lots). Playoff results are excluded.
- **Continental berths**, computed inside each simulation because they depend on the champion:
  - Libertadores (6 places): the Apertura champion, the Clausura champion and the Copa Argentina winner (`copa_argentina_winner`, `None` until known). The remaining places go down the Tabla Anual.
  - Sudamericana: the next 6 clubs not already qualified.
- **Relegation (2 places):**
  - Promedio = (prior points + Tabla Anual points) / (prior matches + season matches). The prior comes from `promedios_history.json`. The season-matches denominator counts matches played and still to play, and is constant across simulations.
  - The worst promedio goes down. The last club in the Tabla Anual goes down second. If both are the same club, the next-worst promedio goes instead and is counted as a promedio relegation.
- **Outputs:** `p_zone_position`, `p_top8`, `p_reach`, `p_title`, `p_anual_*`, `p_libertadores`, `p_sudamericana`, `p_relegation_{promedio,anual,any}`, and promedio quantiles. These go to `zones.json`, `bracket.json`, `anual.json`, `relegation.json`, `probs.json` and `history.json`, under both `docs/liga/data/` and `docs/site/data/liga-argentina/`.

### 8.4 Cup simulator: `oddsmarkets/football/competitions/cup/simulator.py`

The league or group phase is simulated as in 8.2 with (pts, gd, gf, lots). Brackets are resolved from `A1` (single leg), neutral single leg, and `A2 = two_leg_advance_matrix` (etw 0.5). Decided ties are forced by pair on aggregate, falling back to `agg_winner` or `winner` for a level aggregate. Draws already in the store (`known_pairs`) fix the pairings. Undrawn rounds are drawn at random per simulation.

| `kind` | Competitions | Bracket logic |
|---|---|---|
| `swiss` | Champions League, Europa League, Conference League | 36-club league phase. Places 1 to 8 go to the R16. Places 9 to 24 play a two-legged play-off (9 v 24 ... 16 v 17, the higher finisher at home in the second leg). Seed *k* (1 to 8) meets the winner of the (17−*k*) v (16+*k*) play-off, so seed 1 meets the 16 v 17 winner. Fixed tree [1,8,4,5,2,7,3,6]. Later rounds are two-legged, with the better league-phase seed hosting the second leg. The final is single-leg and neutral. |
| `groups` | Libertadores, Sudamericana, CAF CL, Club World Cup | Top 2 per group. The first KO round pairs group winners (second-leg hosts) with a runner-up from another group, drawn by rejection (up to 20 reshuffles). In the Sudamericana, runners-up first meet the `AVERAGE` outside side ("Outside side (any)", the model's default club) over two legs. |
| `regional_swiss` | AFC Champions League Elite | Two regions of 16. Top 8 per region play a two-legged R16 within the region (1 v 8 ...). The QF pairs West against East at random. `neutral_rounds = (qf, sf, final)` are single legs with no home side. |
| `knockout` | CONCACAF Champions Cup, 26 national cups and super cups | Rounds and legs come from config. Pairs come from the draw where known, else random pairing of survivors, with byes for odd counts. A store left with more than one survivor is settled by neutral coin-flip rounds. |
| `fixed` | Intercontinental Cup | Ties from config. A `"champion:<slug>"` slot is drawn per simulation from that cup's winner distribution (the Libertadores). Cups are built in order with `fixed` last so those distributions exist. All ties are single matches; the final is neutral. |
| `international` | 16 national-team competitions | **Not simulated** (section 7). |

**Outputs.**
- `p_win` (used as `p_title` and `p_cup`), `p_reach[round]`, `p_position` (swiss) or `p_group_position`, bands, expected points and quantiles.
- These go to `table.json`, `bracket.json`, `probs.json` and `history.json` under `docs/site/data/<cup>/`.
- The top-scorer race is not simulated for cups: `build_cup` passes empty boot probabilities.

**Caveat.** The Club World Cup has `neutral_venues=True`, but the simulator ignores that flag. Group matches and the R16 to SF are sampled with home advantage for the listed home side. Only the final is neutral. The field affects only the fixture lines.

---

## 9. Strength and power rankings

`build_team_strength` in `oddsmarkets/football/competitions/liga/strength.py`, wrapped by `build_strength_json` in `scripts/build_site_all.py` (and its counterpart in `build_site_liga.py`):

| Field | Definition |
|---|---|
| `strength_ppg` | mean over every other team in the competition of `3*H + D` from `model.predict(team, opp, neutral=True)` (the full Ensemble). "Average opponent" means the average over this competition's field, not a synthetic club as in pool.json. |
| `strength_rank` | rank by `strength_ppg` |
| `rank_delta` | table position minus strength rank *within the club's zone or conference*. Positive means the club sits below its strength. |
| `attack`, `defence`, `elo` | the model's DC parameters and final Elo |
| `form_*` | last `FORM_WINDOW = 6` finished non-playoff matches: results, points, GF, GA |
| `xg_for/against/diff` | sums of team xG over matches with xG |
| `expected_points` | sum over matches of xPts. xPts treats the two xG totals as independent Poisson means, truncated at 8 goals, and returns `3*P(win) + P(draw)`. |
| `luck` | points minus expected_points (0 when there is no xG) |
| `sos_played`, `sos_remaining`, `sos_delta` | mean `strength_ppg` of opponents already played and still to play; `delta = remaining - played` |
| `elo_history` | Elo replayed from a fresh seed over the **current season's or tournament's** finished matches only. Leagues seed from `previous_rank`; Argentina seeds by the order of its team list, not `previous_anual_rank`. The trajectory's endpoint therefore differs from the `elo` column, which is replayed over the whole training frame. |

In cups `elo` is 1500 for everyone (section 3). The output is `strength.json` per competition.

---

## 10. Top scorer (Golden Boot)

The model is `GoldenBootModel` in `oddsmarkets/sports/world_cup/models/player_goals.py`. It is tested in `tests/test_top_scorer.py`.

**Candidates.** Built by `build_boot_candidates_from` in `build_site_all.py` and `build_boot_candidates` in `build_site_liga.py`:
- Non-goalkeepers only, the top 12 per club by (goals, xG, minutes).
- `hist_goals_90` is this season's goals per 90. Role is FWD if goals/90 >= 0.25, else MID.
- Duplicate names are merged, keeping the higher scorer.

**Goal shares.** Within a team the share vector covers the candidates plus an "other" bucket:

```
w_player = 2.0*cur_goals + 1.2*hist_goals_90 + ROLE_BASE[role]      (floored at 1e-4)
w_other  = 1.5
ROLE_BASE = {FWD 0.40, MID 0.15, DEF 0.05, GK 0.0, "" 0.15}
```

**Batch path.** Used by the vectorised simulators through `accumulate_batch`. Each simulation's remaining team goals (league phase, plus the Belgian split) are split across the team's candidates with one multinomial draw per team. Each player's total is current goals plus simulated goals. The leader wins, with ties broken by assists and then at random. P(top scorer) is wins / n_sims. The model has its own RNG, seeded with `cfg.random_seed`.

The legacy per-match path (`start_sim`, `allocate`, `finalize_sim`) is used by the World Cup simulator, which calls it only from knockout matches.

**Caveat.** Shares are fixed for the rest of the season and heavily weighted by goals already scored (2.0 per goal against 1.5 for all "other" players combined). Injuries, transfers and rotation are not modelled.

**Output.** The `model` column of `player_leaders.json` (`top_scorer`, top 40).

---

## 11. Player, team and match analytics

### 11.1 Players: `oddsmarkets/football/analytics/players.py`

**Aggregation** (`aggregate_players`):
- Sums the per-match Sofascore stats in `SUM_KEYS`, keyed by player id. The club is the team of the latest appearance.
- `rating` is the minutes-weighted mean of match ratings.
- `npg = goals - pens`, where pens are counted from incidents.
- `npxg = max(xg - 0.79*pens, 0)`, with `PEN_XG = 0.79`.
- Goalkeeper `conceded` is the opponent's goals scaled by `min(minutes, 90)/90`. `save_pct = saves / (saves + conceded)`.
- Ratio stats (`sot_pct`, `pass_pct`, `dribble_pct`, `duel_pct` and so on) come from summed numerators and denominators.

**Per-90.** Every key in `PER90` gets `<key>_90 = total / (max(minutes, 1)/90)`.

**Catalogue.** `METRICS` lists 86 entries with `group`, `fmt`, `scope` (`out`, `gk` or `all`), `pct` (a percentile slider) and `lower` (less is better). It is emitted in `players_live.json` so the front-end is data-driven.

**Minutes floor** (`minutes_floor`):

```
floor = max(90, round(0.3 * max minutes in the competition, to 10))      # FLOOR_SHARE, FLOOR_MIN
```

Changed 17 October 2026 (was `max(90, min(270, 0.35 * max minutes))`): the 270-minute cap was a tenth of a
Brazilian or MLS season thirty rounds in and over a third of a European one seven rounds in, so one leaderboard
ranked unlike samples. The floor is now proportional to the games played (`minutes_floor(players, games)` takes
the games when known); about 190 minutes seven rounds in, 810 thirty rounds in, 1,030 at the end of a
38-round league.

**Percentiles** (`add_percentiles`):
- Pools are positional: G (by `is_gk`), D, M or F, else `"out"`. Only players with minutes >= floor are pooled.
- `pct = round(100 * (below + 0.5*ties) / n)`, inverted for `lower` metrics.
- A percentile is skipped when the pool has fewer than 3 values or the metric's scope does not match the pool (`gk` metrics only for G, `out` metrics never for G).
- Writes `pct`, `pool` and `qualified` on each row.

**Outputs.** `players_live.json` (every player, the catalogue and the floor), per-player match-log shards, `shots.json`, and `season_index.json` (every player's line in every competition).


**Derived ("Advanced") metrics**, added to every player line and to the
catalogue, so they get percentiles on player pages and appear in the Player lab:

| Key | Definition | Why |
|---|---|---|
| `npxg_xa_90` | (npxG + xA) per 90 | total expected involvement in goals, penalties excluded |
| `ga_90` | (goals + assists) per 90 | the realised counterpart |
| `finishing` | (npG − npxG) / non-penalty shots | finishing above or below expectation, per shot so volume does not dominate |
| `placement` | (xGOT − xG) / shots | how much a player's shot placement adds to the chance he had (xGOT only counts shots on target) |
| `xa_per_kp` | xA / key passes | the quality of the chances a player creates |
| `shot_creation_90` | (shots + key passes) per 90 | shot-ending and shot-creating volume |
| `prog_actions_90` | (progressive carries + successful dribbles) per 90 | carrying the ball forward |
| `def_actions_90` | (tackles + interceptions + blocks + clearances) per 90 | raw defensive volume |
| `padj_tkl_int_90` | Σ over matches of (tackles + interceptions) × 50 / opponent possession, per 90 | possession-adjusted defending: a side without the ball has more to defend. Opponent possession is clamped to 25–75% and taken from the match's team sheet; matches without a sheet count unadjusted |
| `ball_wins_90` | (tackles won + interceptions + recoveries) per 90 | regaining the ball |
| `duels_90`, `aerials_90` | duels / aerials contested per 90 | volume behind the success rates |
| `loss_per_100` | possession lost per 100 touches (lower is better) | ball security, independent of how often a player is on the ball |


### 11.2 League adjustment: `players_global.json`

`build_global` in `scripts/build_site_global.py`:
1. Collects every qualified player row from every built competition.
2. Multiplies the attacking rates in `ADJUSTED_KEYS` (goals, npg, assists, xg, npxg, xa, xgot, shots, key passes and big chances per 90) by the competition's `factor_att` from pool.json, writing `<key>_adj` and `adj_factor`.
3. Recomputes percentiles against the global positional pools (`pct_global`), plus percentiles of the adjusted rates. Every row is already over its own competition's floor (above), so the pool floor is `FLOOR_MIN` (90).
4. Keeps one window (since 17 October 2026): only competitions whose built edition is that of the season under way in their frame (`in_current_window`: a club edition in its frame's current season, an international competition while it has played in the last 60 days). The Euro 2024 qualifiers, 2026 World Cup qualifying or last season's Coupe de France are left out (`left_out`) instead of ranking as "this season".

Only the 12 pooled leagues have a factor. Cups, national-team competitions and Argentina get 1.0, which means no adjustment. The cross-block caveat in section 6 carries over directly to adjusted rates.

### 11.3 Teams: `oddsmarkets/football/analytics/teams.py`

- `team_match_stats` builds per-match rows from Sofascore team-stat sheets (`STAT_COLUMNS`), with opponent shooting (`xga`, `shots_ag`, `sot_ag`). xG falls back to the lineup-summed xG when a sheet lacks it.
- `season_team_stats` gives means over matches where each value exists, plus derived rates:
  - `xg_diff`
  - `xg_per_shot` = Σxg / Σshots
  - `conv` = Σgf / Σshots
  - `pass_pct`, `aerial_pct`, `ground_pct`
  - `save_pct` = (Σsot_ag − Σga) / Σsot_ag
  - totals
- Within-competition percentiles use the same formula as players, over the `TEAM_METRICS` catalogue.
- Output: `team_stats.json`.

### 11.4 Matches: `oddsmarkets/football/analytics/matches.py`

`match_details` is descriptive, not a model. It returns lineups with each player's line, ratings (top 30), incidents, shots, momentum, formation, missing players, the team-stat sheet, and per-side xG (the sum of player xG). Output: match shards and `matches.json`.

---

## 11a. Team analytics, teams of the week and best XIs

`oddsmarkets/football/analytics/insights.py` builds each competition's
`analytics.json` from the player match logs, the team match rows and the
fixtures; `glossary.py` defines every metric it uses.

**Team metrics** are per-match averages over played matches with a team sheet,
the opponent's figures read from the opponent's row for the same match:
xG for and against and their difference, goals, finishing (goals − xG),
keeping (xG against − goals against), expected points per match, luck (points
− xPts), possession, field tilt (own box touches over both sides' box touches),
PPDA (opponent passes over own tackles + interceptions + fouls, lower is more
pressing), shots for and against, shot quality (xG per shot) for and against,
shots on target %, big chances created and missed, corners, aerial and ground
duel %, passes and pass %, long-ball share, crosses, dribbles, fouls, cards
(yellow + 2 × red), distance, sprints and rating. Percentiles within the
competition are rank-based and direction-aware, so 100 is always best.

**Expected points** for a match come from a Poisson score matrix with means
(xG, xG against), goals capped at 8: xPts = 3·P(win) + P(draw).

**Team of the week:** players with 45+ minutes in that round's matches, ranked
by rating, then goals + assists, then xG + xA; the XI is the best eleven under a
formation: one goalkeeper, then the (D, M, F) shape among 4-3-3, 4-4-2, 3-5-2,
3-4-3, 5-3-2, 5-4-1, 4-5-1 and 3-6-1 that maximises total rating. Player of the
week needs 60+ minutes. Awards: finisher = max goals − xG with a goal; creator =
max xA (key passes as tie-break) with an assist or xA ≥ 0.3; the wall = the
goalkeeper with the most goals prevented over 60+ minutes; engine = most
distance; ball winner = most tackles won + interceptions + recoveries among
outfield players. Team awards: best xG difference, luckiest and unluckiest
(points − xPts), and smash-and-grab (a win with an xG share below 0.4).

**Season XIs** use the same formation optimiser on season lines over the
minutes floor: rating (minutes-weighted), output (npxG + xA per 90; keepers by
goals prevented per 90), defence (possession-adjusted tackles + interceptions
per 90 for defenders and midfielders, defensive actions for forwards, goals
prevented for keepers) and form (mean rating over each player's last five, at
least three played).

**Top and bottom performers** list the best and worst eight qualified players
on seventeen metrics (rating, G+A, npxG+xA, finishing, placement, xA per key
pass, shot creation, progressive actions, PAdj tackles + interceptions, ball
wins, duel %, aerial %, possession lost per 100 touches, pass %, distance, and
for goalkeepers goals prevented per 90 and save %), direction-aware.

---

## 11b. Player value, club strengths and needs, the transfer simulator

Added 15 October 2026 (spec: `docs/VALUE_SECTIONS.md` sections 1-3). Code:
`oddsmarkets/football/analytics/value.py` (the model), `value_payloads.py` (the payloads, the
club grades and targets) and `sensitivity.py` (per-club sensitivity curves). Built by
`build_value_layer` (after the unified step) and `write_sensitivity` (inside each league build)
in `scripts/build_site_all.py`. Payload contract: `docs/site/UNIFIED_PAYLOADS.md` section 11.

### 11b.1 Inputs

`ValueCollector.add_store` reads every store's line-ups as the unified step loads it (no second
pass over the stores). One row per player-match with minutes: the player, match, side, day,
competition, season key, team id, start, minutes, Sofascore's G/D/M/F letter, the role from the
formation, the match rating, and sixteen signed action counts:

| Key | Action | Sign | Notes |
|---|---|---|---|
| `npxg` | non-penalty xG | + | `max(xG − 0.79 × penalties taken, 0)`; penalties from incidents plus `penaltyMiss` |
| `xa`, `kp` | expected assists, key passes | + | |
| `prog`, `drb` | progressive carries, dribbles completed | + | |
| `ohp` | accurate passes in the opposition half | + | |
| `lost` | possession lost | − | |
| `tkw`, `int`, `blk`, `clr`, `rec` | tackles won, interceptions, blocks, clearances, recoveries | + | each × 50 / opponent possession (clamped 25–75%), as `padj_tkl_int_90` |
| `aer` | aerial duels won | + | |
| `err` | errors leading to a shot or goal | − | |
| `gp`, `gkc` | goals prevented; high claims + accurate sweeper actions | + | goalkeepers only |

The match table keeps each side's non-penalty xG (the sum of its players') and goals. On the stores of
15 October 2026: 226,161 rows, 7,281 matches, 5,994 club matches with both line-ups.

**Roles from formations** (`formation_roles`, `assign_roles`). Sofascore lists each line of a starting
XI right to left, defence first (`docs/DASHBOARD.md` 3.5 relies on the same order), so a formation
string assigns the ten outfield starters: a back four is FB CB CB FB, a back three CB×3, a back five
FB CB CB CB FB; the first line of four or more beyond a back three has wing-backs (FB) on its ends,
otherwise wide midfielders (W); a deepest line of one or two in front of the defence is DM, a most
advanced midfield line of one or two is AM and of three W AM W; a front three is W ST W. 96% of
starts get a role. A player's role is the one he starts in most (by minutes, last 12 months, else any
time); without a start it is Sofascore's letter (DF, MF, FW).

### 11b.2 The model

**Box-score weights.** For each club match (both sides with 900+ minutes from 10+ players):

```
npxG_home − npxG_away ≈ h + Σ_k β_k (A_home,k − A_away,k),   β_k ≥ 0
A_side,k = Σ_players (minutes / 90) × prior per-90 rate of action k
prior rate = (player's counts on earlier days + 5 × position mean) / (his earlier minutes / 90 + 5)
```

Prior rates use the player's matches on earlier days only (every club competition), shrunk toward
his letter's mean measured on earlier days only (450 minutes of prior). `fit_weights` is a ridge on
standardised columns with non-negative bounds (`scipy.optimize.lsq_linear`, BVLS); the ridge (1, 10,
100 or 1000) is chosen on the last 20% of the training matches in date order, then refitted on all.

**Second stage.** `stack_weights`: OLS of the xG difference on the box-score index and the line-ups'
prior rating difference (same shrinkage, 450 minutes toward 6.7 by letter), both coefficients
non-negative. The published value of a line is `a × Σ_k β_k x_k + b × (rating − 6.0) × minutes / 90`.

Weights on 15 October 2026 (goals of xG difference per action, after the stage-two scale `a` = 0.70;
the build refits them hourly): npxG 0.225, xA 0.138, key passes 0.072, tackles won 0.036, aerials won
0.029, goals prevented 0.019, dribbles 0.016, interceptions 0.014, progressive carries 0.006, recoveries
0.003, accurate opposition-half passes 0.003, claims and sweeps 0.002, possession lost -0.004; blocks,
clearances and errors 0 (no predictive weight). Rating: 0.141 goals per 90 per rating point.

**Centring and the pooled scale** (`comp_offsets`, `row_shift`). Each competition is centred on its
own minutes-weighted mean gross value per 90 and moved by `offset / 11`, where `offset` is the
competition's strength in goals of expected goal difference per match against the pool-average club:
for a pooled league or a club cup, the minutes-weighted mean of its clubs' `xg_for − xg_against` in
`pool.json` (the club's league entry, else a continental-cup entry; domestic-cup entries are skipped
because they connect to the pool only through their own cup); for Argentina (outside the pool), the
mean over its clubs in continental cups of (pooled rating − own-league xG difference per match);
national-team competitions 0 (not on the club scale). On 15 October 2026: Premier League +0.71,
Bundesliga +0.59, LaLiga +0.37, Ligue 1 +0.29, Serie A +0.16, Brasileirão +0.08, Liga MX +0.08,
Saudi +0.04, MLS +0.03, Belgium −0.05, Argentina −0.12 (12 bridging clubs), Eredivisie −0.15,
Liga Portugal −0.30. The section 6 caveat applies: cross-block offsets are weakly identified.

**Replacement, GAR, PAR.** Replacement level per role = the 20th percentile of regulars' (900+ minutes
of club football in the last 365 days) pooled value per 90 in that role; a coarse role takes the mean of
its fine roles. `GAR/90 = value per 90 − replacement(role)`; `GAR = GAR/90 × minutes / 90`;
`PAR = GAR × xpts_slope(μ)`, the derivative of expected points (two independent Poisson sides at the
league's mean goals per team μ, from `meta.json` calibration) with respect to expected goal
difference: 0.63 (Bundesliga) to 0.76 (Argentina), 0.69 at μ = 1.35. Projected GAR/90 =
`minutes / (minutes + 900) × GAR/90` (900 minutes of replacement-level prior).

**Percentiles.** Last 12 months: among regulars of the same role (the unit when a role has fewer than
ten). This season: within the competition and unit, among lines over the competition's minutes floor.

### 11b.3 Validation (`validate`, `split_half`)

Walk-forward: the club matches in date order, the first 40% burn-in, the rest in five blocks, each
predicted by models fitted on earlier matches only (a block starts on a new day). Out-of-sample R²
against a home-advantage-only model, on 3,479 test matches from 22 February 2026 (15 October build):

| Predictor | xG difference | Goal difference |
|---|---|---|
| Line-ups' prior Sofascore rating | 0.154 | 0.139 |
| Each team's own prior xG difference per match | 0.163 | 0.110 |
| Box-score index alone | 0.186 | 0.127 |
| **Player value (box score + rating)** | **0.216** | **0.166** |

Split-half reliability (odd v even appearances, 2,324 players with 1,800+ minutes): value 0.82,
box-score part 0.88, rating 0.56. Rating alone predicts goal difference better than the box score
alone, which is why it is the model's second input; the combination beats both. The numbers are
recomputed every build (`value/meta.json` `validation`, `reliability`). With fewer than 300 club
matches (offline tests, a fresh clone) the build uses `DEFAULT_BETA` and skips nothing else.

### 11b.4 Fair value index (`fvi_raw`)

Superseded on 16 October 2026 by valuation v2 and the fee model (section 11c), fitted on the fees in Sofascore's transfer data (already the site's source); the index is still computed and shown beside them, and is what the pages fall back to when the fee model cannot be fitted.

```
FVI_raw = Σ_{t=0..3} 0.85^t × alive_t × max(g_t, 0) × (2500 / 90) × ppg_pool
g_0 = projected GAR/90;  g_{t+1} = g_t + slope × Δrating(age + t)
alive_0 = 1;  alive_{t+1} = alive_t × continuation(age + t)
FVI = 100 × FVI_raw / median FVI_raw of top-five-league regulars (1,800+ minutes in 12 months)
```

- `Δrating(age)`: delta method over the archive's careers (consecutive seasons of one tournament with
  900+ minutes each, weighted by the harmonic mean of minutes; 1,580 pairs), smoothed by a weighted
  quadratic in age (`ageing_curve`): +0.09 a year at 18, +0.02 at 24, −0.005 at 27, −0.03 at 30, −0.05 at 36.
- `slope`: the cross-sectional slope of value per 90 on rating among outfield regulars (0.32).
- `continuation(age)` (`continuation_curve`): n(age + 1) / n(age) among this year's regulars, 1 up to
  26, a three-year average after, never rising: 0.94 at 27, 0.82 at 30, 0.66 at 35.

Sofascore's proposed market value (EUR) is shown beside it where the archive's player profiles hold it
(1,183 players), reference only; rank correlation with the index 0.57 over 938 players.

### 11b.5 Strengths and needs (`write_club_needs`, `find_targets`)

For every club of a followed league (the twelve pooled leagues and Argentina; 266 clubs): the current
squad is the unified layer's current club (UNIFIED_PAYLOADS 2.3); each player's minutes this season
(every current competition the club plays) are attributed to units by the line-up role (else his main
role). Unit rate = minutes-weighted projected GAR/90 of the current players used there; fewer than 270
such minutes → the squad's best `round(slots)` at the unit; nobody → replacement (0) and flagged.
`slots` = the unit's minutes per match / 90 this season. Percentile and rank against the league's
clubs; grade A (80+), B (60+), C (40+), D (20+), E. Strengths and weaknesses are the three highest and
lowest units; evidence is the component whose per-90 deviation from the league's unit mean is largest
in the grade's direction.

Targets per weakness: projected GAR/90 minus the weakest of the unit's top `round(slots)` regulars by
minutes, best first, among players with a known age of 31 or under, 900+ minutes in 12 months, at a
club whose pooled strength is at most 0.15 points per game above the buyer's, from a league whose
offset is at most 0.25 goals per match above the buyer's (wages are unknown; a much stronger league
pays more), at most two per club, five per unit; or listed by Sofascore with "No team" (33 or under,
450+ minutes). Points = gain × 0.85 (minutes share) × the league's points per goal × the club's
remaining league matches (and × 38 for a full season). Feasibility hints, only where the data supports
them: a contract ending within 12 months (Sofascore's dates: `until` in the squads store, `contract_until` in
the archive); surplus depth (his club has at least the unit's usual number of starters plus two players
with 450+ minutes in the unit over 12 months); and a selling club with nothing left to play for (title, every
band and relegation below 2% in its simulation).

### 11b.6 Sensitivity curves (`sensitivity.py`)

Per league (and Argentina), after the main simulation: each club's goal rate is multiplied by
`exp(δ/2)` and its opponents' by `exp(−δ/2)` in every remaining match, as an exponential tilt of each
score matrix (`M'[i, j] ∝ M[i, j] a^i b^j`, exact for independent Poisson, close for the Dixon-Coles
and Elo blend; H/D/A move by the matrix's change), for δ ∈ {−0.3, −0.15, 0, 0.15, 0.3}. The
competition's own simulator (`LeagueSimulator`, `LigaSimulator`, with the split, conferences and
play-offs) runs 2,000 times per shift with one seed (common random numbers), predictions memoised
(`CachedModel`). Per club: expected points, title, every band, play-offs and cup where the league has
them (Argentina: champion, Libertadores, Sudamericana, relegation), and `gd_per_delta`, the expected
goal difference per match gained per unit of δ over its remaining fixtures. 4 to 10 seconds a league
(a 90-second budget each). The simulator divides a change in goals per match by `gd_per_delta`,
interpolates linearly (capped at the ends) and applies the difference `curve(δ) − curve(0)` to the
published 30,000-run probabilities.

**The simulator's displacement** (`value.js` `alloc`): a unit's `slots × 90` minutes a match go to its
players best projection first, each player's 85 minutes a match split over the units he played in this season
in proportion to his minutes there (all in his role's unit without any), the rest to replacement (0); a
signing joins his unit with 85 minutes, players out leave theirs; the club's change is the sum over units. Window status is a table of
typical registration periods per league (`WINDOWS` in value.py), labelled approximate.

---

## 11c. Valuation v2, transfers, fair fees, deal grades and budgets

Added 16 October 2026 (spec: `docs/VALUE_SECTIONS.md` section 4). Code:
`oddsmarkets/football/analytics/transfers.py`, called from `build_value` in `value_payloads.py`
(after the players' state, before `players.json` and the club files are written). About 3 seconds a
build. Payloads: `docs/site/UNIFIED_PAYLOADS.md` section 12.

### 11c.1 Data: Sofascore transfers and market values

- **Source and terms.** Sofascore is already the site's only match-data source. Its terms page
  renders in JavaScript and could not be read by a fetch on 16 October 2026; the site keeps to factual
  data, credits Sofascore on every page, paces its calls inside a small hourly budget and never
  republishes raw stores (the deploy prunes every `store.json`). Transfermarkt and other sites whose
  terms forbid reuse are not used.
- **Endpoints** (`sources/sofascore.py`): `/team/{id}/transfers` (`team_transfers`: the club's moves in
  and out over roughly the last nine months), `/player/{id}/transfer-history` (`player_transfer_history`:
  a whole career), both parsed by `parse_transfer` into a compact record: Sofascore's transfer id, the
  player, both clubs' ids and names, the type (1 loan, 2 loan return, 3 permanent), the fee as published
  (EUR unless `cur`), Sofascore's fee text ("59.6M €", "Free", "-") and the date. The squads endpoint
  (`team_players`) now also keeps each player's proposed market value (`mv`).
- **Rotation, inside the existing hourly budget.** A fourth phase of `scripts/fetch_sofascore_history.py`
  (the archive's 60 calls a run, whose other queues had all but emptied) spends what is left (about 55):
  the followed leagues' clubs' transfer lists first (never fetched, then older than 7 days, 2 days in a
  transfer window), then rated players' histories (450+ club minutes in 12 months, most minutes first,
  refreshed after 180 days), keeping a fifth of the rest (at most 5) for the cup clubs (every 30 days).
  A page Sofascore does not have (404) is noted and retried after 14 days; a 403 stops the run. Store:
  `docs/site/data/transfers/store.json`, committed by the hourly task with the other stores.
  Market values ride on the squads rotation (20 calls a run, unchanged).
- **The squads rotation was stuck** from 5 to 15 October: three never-fetched cup clubs without a squad
  page sat at the head of its queue and ended every run (three failures in a row). Fixed: such a club
  is noted under `failed` and skipped for 14 days, and the followed leagues' clubs come before the cups.
- **Coverage on 16 October 2026, 13:00 UTC** (after 13 hourly runs): 12,373 moves (2,193 with a
  published fee, 1,976 free, 1,719 undisclosed, 1,020 promotions from a club's own youth or reserve
  side, 2,742 loans, 2,723 loan returns); all 266 followed clubs' lists; 314 player histories; market
  values for 4,866 players (152 of the 267 followed squads re-fetched with values). Full coverage: the
  remaining ~115 followed squads by about 19:00 UTC on 16 October; the ~6,900 rated players' histories
  at ~45 a run in about six days; the ~360 cup clubs at 5 a run in about three days.

### 11c.2 Deals and windows

`deal_kind`: a permanent move with a fee over 0 is `fee`; with 0 and "Free" `free`; from a side whose
name marks a youth or reserve team (U19/U21/U23, II, B, Castilla, Next Gen, Jong, NXT, ...) `youth`;
otherwise `undisclosed` (also any fee in a currency other than EUR, which is never converted). Type 1
is `loan`, type 2 `loan_end`. Windows are halves of the year: May-October is "Summer YYYY",
November-April "Winter YYYY-1/YY" (northern-hemisphere names; South America's and MLS's windows fall
in the same halves). Undisclosed fees are counted, never summed.

### 11c.3 Valuation v2 (`value_v2`)

The expected points above replacement a player adds over the next four seasons, discounted 15% a year:

```
V2 = E[ sum_t 0.85^t x alive_t x max(rate_t, 0) x 3400 x avail / 90 x ppg_pool ]
rate_0 ~ N(proj, var_within / (90s played + 10))         (the projection's posterior)
rate_t+1 = rate_t + slope x ageing(age + t) + N(0, sigma_age^2)
avail ~ Beta(a x 12, (1 - a) x 12)
```

- `proj`, `slope`, `ageing`, `alive` (continuation) and `ppg_pool` are section 11b's.
- `var_within`: the pooled within-player variance of value per 90 in single matches of 45+ minutes
  (0.032 on 16 October).
- `sigma_age`: the spread of season-to-season rating changes around the ageing curve, less the part two
  seasons' sampling noise explains (a match rating's sd 0.75 over each season's 90s), times `slope`
  (0.032 goals per 90 a year).
- **Availability** `a`: the share of his clubs' minutes he played in the last 12 months. Each club he
  appeared for counts its matches (with line-ups, club competitions) from his first to his last
  appearance there, his latest club up to today, so an injury or a benching counts against him;
  shrunk toward 0.5 by 8 matches. A season is 3,400 minutes.
- 400 draws per player (seeded) give the mean, a 10-90% band and the first season's points.
- **Position scarcity** enters the euro figure through the fee model's position terms (what clubs pay
  for a striker against a full-back of the same value); league strength through both the value's
  league centring (11b) and the fee model's club terms.
- Rank correlation with Sofascore's market value over 3,411 players with 450+ minutes: 0.56 (the 11b
  index: 0.57). Value alone ranks players like the index; the fee model adds what the market prices.

### 11c.4 The fair fee model (`FeeModel`, `validate_fee`)

Ridge regression of log(fee) on standardised features, fitted on every published fee of €100k or
more whose player had 450+ club minutes in our line-ups in the year before the move (701 of 2,193 fees
on 16 October), with his value **as the model saw him the day before** (`snapshot`: the 12 months
before the move, availability at that date, age at that date):

| Feature | Coefficient (standardised, 16 Oct) |
|---|---|
| log(1 + V2 at the time) | +0.16 |
| projected GAR/90 at the time | +0.09 |
| age - 26, (age - 26)^2 | -0.37, -0.05 |
| unit (CB, FB, MID, ATT, ST; GK the base) | +0.10, -0.01, +0.15, +0.17, +0.24 |
| seller's pooled xG difference per match (unknown: -0.6 and a flag) | +0.31 |
| buyer's pooled xG difference per match (unknown: -0.6 and a flag) | +0.57 |
| log(1 + 90s played in the year) | +0.21 |

The ridge (0.3 to 30) is chosen by five-fold cross-validation grouped by player. Out of sample:

| 16 Oct 2026 | Typical error (exp median abs. log error) | Within ±50% | R² (log) | Spearman | Median miss |
|---|---|---|---|---|---|
| **Fee model, 5 folds by player (701 fees)** | **×1.82** | **45%** | **0.58** | **0.76** | **€2.6m** |
| Value and age only | ×2.15 | 36% | 0.29 | 0.54 | €3.2m |
| Median fee by buyer's league tier and position | ×2.40 | 32% | 0.17 | 0.43 | €4.5m |
| **Fee model, the latest 30% of fees (from 12 Aug) from the earlier 70%** | **×1.78** | **47%** | **0.61** | **0.78** | **€2.5m** |
| Baseline, same split | ×2.47 | 31% | 0.19 | 0.47 | €4.3m |

The buyer's strength is the largest term: the same player costs more to a stronger (richer) club.
Every rated player's **fair fee** (`players.json` `fee`, with the middle-half range `feelo`-`feehi`
from the cross-validated residual sd) is the fee to a buyer like his own club. Rank correlation with
Sofascore's market value over 3,411 players: **0.76**. The transfer simulator evaluates the same
coefficients (published in `value/meta.json` `fee.model`) for the chosen buyer. With fewer than 120
usable fees the model is not fitted and the pages keep the fair value index (section 11b.4) and say so.

### 11c.5 Deal grades

Every move of the last 12 months except loan returns and youth promotions, for the buying club and,
for fees and frees, the selling club:

- **Price**: log(fair fee at the time / fee), clipped to ±2 (a free: log((fair + €1m) / €1m), 0 to 2),
  times the evidence behind the fair fee (the player's club minutes before the move / 1,800, at most 1).
  Fair fees of the fitted deals are their cross-validated predictions, so a deal never prices itself.
- **Since the move**: GAR/90 for the new club, shrunk toward the projection at the time by 900 minutes,
  minus that projection, per 0.1 GAR/90, plus 2 x (his share of the club's minutes since - 0.6); weighted
  by minutes since / 1,800 (at most 1). Moves without a value at the time (from a league we do not
  follow) are judged on the minutes since alone once he has 450.
- Buyer score = price + weight x since; seller score = -price (half for a free) - half the buyer's
  "since" (selling a player who then thrives counts against the seller). Letters are quintiles among the
  year's graded deals (2,122 buyer grades, 1,052 seller grades on 16 October); the winner is the side
  ahead by more than 0.3.

### 11c.6 Ledgers and windows

Per followed club (`value/club/<tid>.json` `ledger`): the moves in and out of the last ~13 months with
fee, fair fee, grade and minutes since; the last 12 months' spend, sales, net, fair value in and out
and the market value added ((fair in - fees paid) - (fair out - fees received)), and the signings' and
departures' expected GAR a season (projected GAR/90 x availability x 3,400 / 90); spend and sales by
window (the latest summer and winter windows are complete once the club's list is fetched; older
windows come from players' histories and are marked partial). Per league (`value/transfers.json`
`windows`): spend, sales, net, signings by kind, the five biggest fees, the five best-graded signings
and the top net spenders and sellers per window.

### 11c.7 Budgets (`fit_budgets`)

Ridge on log(1 + gross spend in EUR m) in the latest complete summer window, across the followed clubs
whose recent lists are fetched, from what was known before it: the previous (winter) window's spend and
sales, the league's offset (11b) and the club's pooled xG difference, and the squad's market value
before the window (Sofascore's values, the window's signings taken out and its sales put back) once at
least 60% of the clubs have 60% of their squads valued (not yet on 16 October: switched on
automatically as the squads rotation completes). Out of sample (five folds by club, 266 clubs):
**rank correlation 0.72, R² 0.58 on the log scale, 49.6% of clubs inside their predicted 25-75%
range** (target 50%). Each club gets a summer-window budget (mid, 25-75% and 10-90%) and the next
window's (the model with the latest window's spend and sales scaled to winter as the previous window,
times the winter-to-summer spending ratio across these clubs, 0.19).

**Used by** the club page (budget, squad value, ledger), the targets of section 11b.5 (each target's
fair fee to this buyer, and "fits" within the budget's 25-75% top, "stretch" to its 90th percentile,
"beyond"; a target over 1.5 x the 90th percentile is left out) and the transfer simulator (the fair fee
to the chosen buyer against its budget).

---

## 11d. Fantasy (FPL-style)

Added 16 October 2026 (spec: `docs/VALUE_SECTIONS.md` section 5). Code:
`oddsmarkets/football/analytics/fantasy.py`, `build_fantasy_layer` in `scripts/build_site_all.py`
(after the value layer; `--no-fantasy` skips it). About 10 seconds a build including the backtest.
Payloads: `docs/site/UNIFIED_PAYLOADS.md` section 12.4.

### 11d.1 Scoring

FPL's 2025/26 rules applied by us to Sofascore's match lines (`points_components`): minutes 1 (1-59) or
2 (60+); goals 10/6/5/4 (GK/DEF/MID/FWD); assists 3; clean sheet (60+ minutes, nothing conceded while on
the pitch) 4/4/1/0; -1 per two conceded on the pitch (GK, DEF); 1 per three saves; yellow -1, red -3 (a
second yellow is the red only); own goal -2; penalty missed -2; defensive contribution 2 (DEF: 10+
clearances, blocks, interceptions and tackles; MID/FWD: 12+ including recoveries); bonus 3/2/1 to the
three best Sofascore ratings in the match (ties share), our stand-in for FPL's bonus point system.
Penalty saves are not scored (the incidents do not tell a save from a miss). Positions are Sofascore's
G/D/M/F. **Goals conceded on the pitch** come from the goal incidents' minutes and the running score
(own goals to the right side), the line's minutes and substitution time (`goal_timeline`); without
incidents, the side's goals against x minutes / 90. Collected in the value collector's single pass
(`Rows.F`, `FANTASY_KEYS`).

### 11d.2 Projection

`RateIndex` keeps, for every player, recency-weighted cumulative sums of his club lines, so rates at
any cutoff are a vectorised lookup:

- **Rates per 90** (180-day exponential weighting, 365-day span), shrunk to his position's mean: goals and
  assists are 70% expected (xG including penalties x the data's goals/xG ratio, 0.96; xA x the
  assists/xA ratio, 0.97; both over matches with xG only) and 30% actual (6 90s of prior); saves (4), yellows (8),
  reds (20), own goals and penalty misses (30), bonus (6); the defensive-contribution hit rate per 60+
  appearance (4 appearances of prior).
- **Minutes** at his current club (unified current club): his league minutes against the club's league
  matches since he first played for it, 60-day weighting, shrunk by one weighted match toward his own
  unweighted record at the club over the last 120 days, itself shrunk by three matches toward a
  newcomer's 30 minutes (p60 0.25, p1 0.45): expected minutes, P(60+), P(plays).
- **Fixture**: the match model's expected goals for and against (`fixtures.json` `model.lh`/`la`).
  Goals, assists and bonus (midfielders, forwards) scale with the team's expected goals in the fixture
  over its mean across its remaining fixtures; clean sheet = P(60+) x exp(-xGA); conceded and saves
  from Poisson expectations (E[floor(X/2)], E[floor(X/3)]); a double gameweek adds both fixtures.
- **Calibration**: projections x 0.90, the ratio of actual to projected points over the backtest.
- **Gameweeks** (`gameweeks`): by round where the league numbers them (a fixture more than four days
  from its round's median, or a lone rescheduled match, joins the gameweek it falls in), else by week.

### 11d.3 Backtest (`backtest`)

Every round (match days with no gap of 2+ days) of every followed league with line-ups and 28+ days of
history: each player whose latest club line before the round is with one of its clubs is projected from
earlier matches only, the fixture's expected goals from a walk-forward stand-in (team attack and
defence from recency-weighted non-penalty xG for and against, shrunk by five matches, times the league's
mean home and away goals; past fixtures keep no model line), the calibration factor from earlier rounds
only. Scored against the points his line-ups earned (0 if he did not play). 16 October 2026: 389 rounds,
198,657 player-rounds, mean 1.68 points:

| Projection | MAE | RMSE | Bias | Rank corr. per round | Top-20's actual points | Big-five MAE |
|---|---|---|---|---|---|---|
| **Ours** | **1.497** | **2.346** | +0.03 | **0.540** | **4.35** | **1.544** |
| Last five club matches | 1.519 | 2.503 | -0.05 | 0.523 | 3.80 | 1.555 |
| Season-to-date per club match | 1.631 | 2.524 | +0.18 | 0.486 | 3.75 | 1.643 |
| Last 365 days per club match | 1.637 | 2.618 | +0.17 | 0.483 | 3.68 | 1.652 |

By position the projection's MAE is lower for defenders (1.69 v 1.72), midfielders (1.38 v 1.42) and
forwards (1.35 v 1.37), and higher for goalkeepers (1.72 v 1.62 for last-five form): keeper points
swing on saves and clean sheets the model spreads out. The live projections use the match model's
expected goals, so they should do at least as well as the stand-in.

### 11d.4 Prices, picks and the squad

- **Prices** (`price_proxy`): official FPL prices and ownership are **not used**: the Premier League's
  terms of use allow downloading for private use only and forbid reproducing, re-utilising or
  redistributing its material or building a database from it (checked 16 October 2026). Our price is the
  player's first-season value from 11c.3 (expected points above replacement next season), ranked
  within his league and position and mapped to lo + (hi - lo) x q^1.6: GK £4.0-6.0, DEF £4.0-7.5, MID
  £4.5-13.0, FWD £4.5-14.5. It prices on-field value, not fantasy points, so "best buys" (projection
  above what players at the price usually score, a linear fit per position) are where fantasy scoring
  and value disagree (attacking full-backs, penalty takers, players in good fixture runs).
- **Picks**: captain (top next-gameweek projections, with P(goal) and P(goal or assist)); best buys per
  position; value picks (£6.5 or less, points per pound above £3.5); differentials (projected in the top
  but outside the top 15 at the position by points so far, £7.5 or less: no ownership data, so "what
  most managers already own" is approximated by points so far); transfer out (points per match so far x
  5 well above the next-five projection, £6.0+); buy low / sell high (last five club league matches,
  actual points against the underlying points: goals and assists at xG and xA, clean sheet and conceded
  at the opponent's xG while on the pitch; 4+ points of gap).
- **Tiers** within a position break where the next-five projection drops by more than twice the typical
  gap (at least 0.15).
- **Fixture difficulty**: each club's next six gameweeks with expected goals for and against, rated 1-5
  by quintile of the league's upcoming fixtures.
- **Squad** (`optimise_squad`): 15 players (2/5/5/3), at most 3 a club, £100.0, maximising the XI's
  next-five projection plus 0.1 x the bench's plus the captain's next-gameweek points, with the XI in a
  legal formation (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD); scipy's HiGHS MILP over the best 60 per position
  (20-second limit); a greedy points-per-price fallback without a solver.

---

## 12. Market odds

### 12.1 Club match markets: `oddsmarkets/football/core/markets.py`

- **Source:** The Odds API v4, `TheOddsAPIFetcher.fetch_match_odds` in `oddsmarkets/sports/world_cup/trading/the_odds_api.py`.
  - Request: `/sports/{sport}/odds`, `regions="eu,uk"`, `markets="h2h"`, `oddsFormat="decimal"`.
  - Only bookmakers in `CANADIAN_BOOKMAKERS` are kept.
  - The key is read from the `ODDS_API_KEY` environment variable. Without it, or without a sport key (`odds_api_sport` in config), the build skips the fetch.
- **`devig`:** multiplicative. `p_i = (1/o_i) / Σ_j (1/o_j)`.
- **`overround`:** `Σ 1/o_i - 1`. A negative value means the field is incomplete.
- **`consensus`:** each book is de-vigged, then the median per outcome is taken across books and renormalised.
- **`edge`:** relative, `model / market - 1`. `MIN_EDGE = 0.03` sets `actionable`.
- **`build_outright_markets`:** de-vigs a title market against the simulation's `p_title`. It is flagged `field_complete = overround >= 0`, and a missing market returns `available: false`.
- **Output:** `market_odds.json` per competition.

**Known defect.** `fetch_match_odds` returns a *flat* list, one row per bookmaker outcome (`match_id, outcome, decimal_odds, ...`). `build_match_markets` expects rows grouped as `{home, away, books: {book: {home, draw, away}}}`. Nothing in the build converts one shape into the other, so any row without `home` and `away` is skipped and a live fetch yields zero fixtures. Every `market_odds.json` checked (premier-league, liga-argentina, champions-league) is currently `ok: false` with no fixtures. The de-vig and edge maths are unit-tested in `tests/test_markets.py` with the grouped shape.

### 12.2 World Cup markets: `scripts/fetch_market_odds.py`

This is a separate WC-only script using no API key. It fetches:
- Polymarket winner, reach-final and golden-boot events.
- Kalshi `KXMENWORLDCUP`, `KXWCROUND` and the goal leader.

Winner markets are de-vigged by normalising the matched teams to sum to 1. Reach markets use the bid/ask midpoint without cross-team normalisation, because the sum over teams is about 16 for the R16 by design. Despite the file name, it does not use The Odds API.

### 12.3 World Cup model (legacy path)

`scripts/build_site_wc.py` builds the World Cup model as follows:
- **DC:** `DixonColesModel(ridge=1.0)` with the class default xi = 0.0018. It is trained on `data/historical_matches.csv` (gitignored, so absent in CI) plus live WC matches.
- **xG scaling:**
  - Historical xG is multiplied by goals/xG from `match_xg.csv`, or by 0.839 when that CSV has no goals columns.
  - Live xG is scaled by the tournament's own goals/xG ratio.
- **Elo:** seeded from `FIFA_RANKING_2026` and updated with K = 60 at neutral venues.
- **Ensemble:** `EnsembleModel(dc_weight=0.50)` with the WC defaults (draw_rate 0.25, lam_scale 2.6).
- **Simulator:** `TournamentSimulator` (`oddsmarkets/sports/world_cup/trading/simulator.py`) runs one Python loop per simulation. It applies full head-to-head group tiebreaks and the best-8-thirds allocation. A knockout draw is a 50/50 shootout with no extra-time weighting. `N_SIMS = 100_000`.

---

### 12.4 Prediction markets (the default source)

Since 30 September 2026 the Market tabs read Polymarket and Kalshi through
`oddsmarkets/football/sources/prediction_markets.py`, without a key.

| Step | Rule |
|---|---|
| Price | midpoint of best bid and ask; skipped without a live two-sided quote or with a spread over 0.12 |
| Match line | three yes/no markets per fixture (home, draw, away); each source is a "book" of decimal odds 1/p, de-vigged by `devig`, pooled by `consensus` (median) |
| Matching | market event to our fixture within 36 hours of kickoff whose two clubs both match; names folded (accents, FC/AFC/CF...), token subset or ratio ≥ 0.72, ambiguous ties refused; `ALIASES` for city names (Kalshi's "Eindhoven" is PSV) |
| Title market | Kalshi champion series plus Polymarket's champion event, averaged per club; published only if at least half the field is quoted and the implied total is within 0.8–1.3 |
| Model side | match lines against `model.predict`; title against the simulation's `p_title` (league), `p_cup` (playoff league) or `p_win` (cup) |

The first run showed the model far from the market on several titles (it
rated Manchester City 38% for the 2026-27 Premier League against the market's
18%, and Liverpool 0.4% against 7%), which says more about a model fitted
mostly on five matches of the new season than about the market. Read edges in
September as a diagnostic of the model, not as opportunities.

## 13. Outputs by model

| Model | Payload files (under `docs/site/data/`) |
|---|---|
| Ensemble line | `<slug>/fixtures.json`; hub cards in `hub.json`; `<league>/club_matches.json` |
| League / Liga / Cup simulators | `<slug>/table.json`, `probs.json`, `bracket.json`, `history.json`, `meta.json`; Liga adds `zones.json`, `anual.json`, `relegation.json` |
| Strength | `<slug>/strength.json` |
| Golden Boot | `<slug>/player_leaders.json` |
| Player analytics | `<slug>/players_live.json`, `shots.json`, player shards; `season_index.json`; `players_global.json` |
| Team / match analytics | `<slug>/team_stats.json`, `matches.json`, match shards |
| Pool | `pool.json` |
| International | `nations.json`; international `<slug>/fixtures.json`, `strength.json` |
| Markets | `<slug>/market_odds.json` |
| Player value | `value/meta.json`, `value/players.json`, `value/lines.json`, `value/club/<tid>.json` |
| Sensitivity curves | `<league>/sensitivity.json` |
| Transfers, fair fees, budgets | `value/transfers.json`; `fee`, `v2`, `budgets`, `transfers` in `value/meta.json`; `budget`, `ledger` in `value/club/<tid>.json` |
| Fantasy | `fantasy/meta.json`, `fantasy/<league>.json` |

---

## 14. Known limitations

1. **The fit drifts with the calendar.** DC weights are `exp(-xi * (now - date))`, and the ridge is not rescaled. As the data ages, every weight shrinks by the same factor, so the ridge gains relative strength and the parameters shrink toward zero even with no new matches. The effect is deterministic, not optimiser noise.

   `tests/test_model_golden.py::test_ensemble_golden_predictions` asserts `abs=1e-3`, and its docstring blames the earlier 1e-5 flapping on BLAS or optimiser noise. With "now" frozen, the same fit gives these values:

   | Fit date | home_win |
   |---|---|
   | 2026-08-18 | 0.64585 (the golden value 0.6458) |
   | 2026-09-15 | 0.64504 |
   | 2026-09-29 | 0.64463 |
   | 2026-12-31 | 0.64174 |

   That is about 3e-5 per day. The test fails as of 2026-09-29 (home_win is 1.19e-3 below golden), and it will keep failing at any fixed tolerance. The fix belongs in the test: freeze "now", or give `fit` a reference date. It does not belong in the tolerance.
2. **Cross-continent identification is weak.** Only about 6 cross-block cup matches link the blocks (section 6). Cross-block league ranks and scoring factors, and the adjusted player rates built on them, are mostly prior.
3. **The international fit is thin.** It rests on about 52 matches for 48 nations, with rho stuck at its starting value (section 7). National-team competitions are not simulated.
4. **The Odds API match rows are in the wrong shape** (section 12.1), so a key adds no bookmaker rows; the Market tabs come from the prediction markets (section 12.4).
5. **There is no neutral term in the fit.** Neutral-venue matches train `home_adv` as if the listed home side were at home (section 2).
6. **xG replaces goals, not blends with them.** xG exists only for current-season matches with lineups, and club xG is not calibrated to goals. rho is estimated from goals rows only.
7. **The Ensemble's H/D/A and its score matrix disagree by a few points** on blended fixtures (section 4.3).
8. **Head-to-head tiebreaks are approximated** by GD and GF in the league simulators (La Liga, Serie A), and cups use (pts, gd, gf) in place of their real tiebreak orders.
9. **Liguilla forced results are not aggregate-aware.** A two-legged tie is forced after its first decisive leg, and a level aggregate goes by strength share, not seed (section 8.2).
10. **The tuning pool differs from the deployed pool.** The pooled candidate in `tune_league_models.py` is scored without cups, but the build's pooled fit includes them.
11. **`tune_liga_model.py` has a dead parameter.** Its `elo_rank_scale` grid dimension has no effect, and neither does `ELO_RANK_SCALE` in `build_site_liga.py`.
12. **Cup Elo is flat** (unseeded, never updated), so cup `strength.json` Elo columns read 1500 and unknown-club fallbacks are a pure home-advantage prior.
13. **The Belgian split is always simulated from scratch** off the regular-season table. **Points quantiles** use 2,000 simulations, not the full run.
14. **Player value is a box score plus a rating** (section 11b). What Sofascore does not count (positioning, pressing without a tackle, off-ball runs) is invisible, so defenders and goalkeepers are measured less well than attackers; blocks, clearances and errors carry no predictive weight. Cross-league comparison rests on the pooled offsets (weak across continents, approximate for Argentina), and a transfer moves a player between leagues by those offsets alone. The fair fee (11c) is fitted on Sofascore's published fees, a third of which have a value at the time in our data; budgets do not know wages or owners' money; fantasy prices are our own proxy (no official FPL data) and the bonus is a rating stand-in. The windows are typical dates.
