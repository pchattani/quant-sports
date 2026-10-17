# Architecture: The Quant Rink

This is the top-level map of the NHL side of the `oddsmarkets` repository and the site it
publishes, **The Quant Rink** (<https://pchattani.github.io/the-quant-rink/>). Start here if
you are new to the NHL code. Four sibling documents cover the detail, and this one links to
them rather than repeating them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | NHL api-web, stats REST, EDGE, ESPN, MoneyPuck, the markets, events and stints, the stores, the scheduled job, the backfill |
| [MODELS.md](MODELS.md) | the shot and player models (xG, shooting, goalies, on-ice, RAPM, value, lines, stabilisation), team strength, the game model, live WP, the season simulation, awards, markets, the backtest |
| [DASHBOARD.md](DASHBOARD.md) | the static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | operations, deploy, the backfill, refits, troubleshooting |

`HANDOFF.md` at the repository root holds the open tasks of every site (it had no Rink
entry on 1 October 2026; the Rink's open items are in [MODELS.md](MODELS.md) section 16).

---

## 1. What the site is

The Quant Rink is a static NHL analytics site rebuilt by GitHub Actions every hour, and
every 15 minutes while a game is on. A season is the NHL's id (`20262027`, shown 2026–27;
`canon.current_season`: July to December belongs to the season starting that year, January
to June to the one that started the year before), a game an NHL gameId (`2026020009`: the
start year, the type, 02 regular season or 03 playoffs, and the number), a player an NHL
playerId and a team the tri-code the NHL used that season (ATL → WPG from 2011–12, PHX →
ARI from 2014–15, ARI → UTA from 2024–25; `oddsmarkets/nhl/canon.py`). Everything
play-level comes from the NHL's own public APIs (api-web play-by-play, stats REST shift
charts); lines come from ESPN (core odds by book from 2019–20, with open and close blocks
from 2023–24, and the DraftKings pickcenter for upcoming games); NHL EDGE tracking
aggregates come from api-web from 2021–22; MoneyPuck's shot files are downloaded only to
benchmark our xG; prices from Kalshi and Polymarket.

The depth of each season is set by what the NHL publishes (the state on disk is in
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 3):

| Tier | From | What it enables |
|---|---|---|
| Play-by-play with coordinates (api-web) | 2009–10 (`canon.FIRST_SEASON`) | events, shot maps, xG, shooting, goaltending, the catalogues' individual metrics |
| Shift charts (stats REST) | 2010–11 (`canon.SHIFTS_FROM`; 2009–10 answers empty) | on-ice players, stints, TOI, on-ice rates, RAPM, lines, deployment, Rink value |
| ESPN core odds by book | 2019–20 (`canon.ESPN_ODDS_FROM`) | GAME.lines, the market comparison in the backtest |
| ESPN open and close blocks | 2023–24 (`canon.ESPN_OPEN_CLOSE_FROM`; 2022–23 also has them for 1,288 of 1,400 games) | opening lines on the game pages |
| NHL EDGE (api-web `/edge`) | 2021–22 (`canon.EDGE_FROM`) | skating and shot speed, distance, zone time, goalie shot-location summaries |
| MoneyPuck shot files | 2007–08 (`canon.MONEYPUCK_FROM`) | the xG benchmark only |

Two facts that the code does not show shape everything:

- **The location data changes character in 2020–21.** Shot coordinates before then were
  recorded by each arena's scorers and carry rink biases; the xG model arena-adjusts seasons
  before `_io.TRACKING_FIRST` (20202021) and leaves later ones alone
  ([MODELS.md](MODELS.md) section 2). The committed xG model was fitted on two tracked-era
  seasons only, and on hand-tracked samples MoneyPuck's model is clearly better
  ([MODELS.md](MODELS.md) section 14.2).
- **Hockey is close to a coin flip.** Forecasters differ in the third decimal of log-loss;
  the model's edge over Elo and its gap to the closing line are both small numbers.

What the site offers (the navigation in `docs/rink/index.html`; a season picker sits above
it):

- **Hub**: today at a glance (games today and live now, the Stanley Cup favourite, the
  biggest model–market gap, the next puck drop), the playoff-odds snapshot, live games
  (refreshed every minute), today's games with model against market against line and live
  win probability, the biggest gaps, last night's results, leaders.
- **Games** (`#/games[/<date>]`): a day of games with prices and, once final, how the
  model's favourites, puck-line sides and totals did.
- **Game centre** (`#/game/<game_id>`): pre-game model against market and line (win,
  regulation, overtime, puck line, total, the exact-score grid and the total-goals
  distribution, starting goalies); game flow (the xG race, our win probability, half-rink
  shot maps, game awards); lines and TOI from the shift charts; the box score with
  individual xG, on-ice xGF% and goalie GSAx.
- **Standings** (wild card, divisions, league, playoff odds with points and seed
  distributions, ratings, the draft lottery) and **Playoffs** (the bracket with series
  odds, odds by round against the Cup market).
- **Teams** and **team pages** (unit ratings and their history, special teams, 5v5 shot
  maps for and against the league, lines and pairs, deployment, the schedule against the
  model and the market, the roster's value).
- **Skaters** (138 metrics) and **Goalies** (45 metrics) catalogues with
  stabilisation-aware percentiles, and **player pages** (Savant-style sliders, shot
  heatmap and map, the RAPM quadrant, on-ice rates by strength, EDGE, deployment,
  linemates, game log, career, projection, similar players).
- **Lines** (every forward line and defence pair, raw and shrunk xGF%), **Leaders**,
  **History** (every Cup champion since 1917–18, the scoring environment, season leaders),
  **Lab** (any two metrics), **Compare**.
- **Markets**: games and futures (Cup, conferences, divisions, playoffs, Presidents'
  Trophy, season points ladders, awards), model against the de-vigged market.
- **Calibration**: our xG against MoneyPuck's on the same shots, the game model against
  Elo, an xG baseline and the closing line, season odds, stabilisation.
- **Glossary** and **Methodology**: every metric and model term, and a long methodology
  document ([MODELS.md](MODELS.md) section 16 lists where it and the code disagree).

### What is on disk today

As of this writing (1 October 2026, about 23:20 EDT, 03:20 UTC on 2 October, read from the
files; the logs' times are the machine's local time, EDT):

- **The historical backfill is still running** (two NHL workers started at 17:26 EDT;
  `logs/nhl_backfill_nhl_{a,b}.log`). Complete on disk: 2016–17 to 2025–26 (play-by-play,
  shifts, boxscores and derived tables for every final game), 2026–27 to date (8 final
  games of 1,344 scheduled) and the ESPN lines for 2019–20 to 2025–26. Worker a was in
  2015–16 (play-by-play 500 of 1,291 at 23:18), worker b in 2014–15 (boxscores 500 of
  1,319); 2013–14, 2012–13, 2011–12, 2010–11 and 2009–10 follow. It was expected to finish
  at about 03:15 EDT on 2 October 2026. 2010–11 and 2015–16 each also hold an earlier
  30-game sample with derived events.
- **Stores** under `docs/rink/data/<S>/store.json` for every season the backfill has
  reached (0.6–0.9 MB a season to 2018–19, 2.4–7.0 MB for 2019–20 to 2023–24 with ESPN's
  books, 2.2 MB for 2024–25 and 2025–26, 0.6 MB for 2026–27). The stores of 2009–10 and
  2011–12 to 2013–14 were 1 KB placeholders until the backfill reaches them.
- **The MoneyPuck files** for 2009–10 to 2026–27 under `data/nhl/moneypuck/` (84 MB).
- **Committed to git**: the code (`a70b2fe`, "NHL (The Quant Rink): data, xG/RAPM/value,
  team and season models, analytics, site and pipeline", 119 files, 19:10 EDT; then
  `4c85f34` checkpoint fixes and `21cce5e` the goalie nav) and the nine files of
  `oddsmarkets/nhl/models/fitted/`. **No store and no `calibration.json` is committed
  yet**: `docs/rink/data/` is untracked in its entirety (RUNBOOK section 5). The working
  tree also holds an uncommitted change to `models/live.py`, `analytics/adapters.py` and
  `tests/nhl/test_models_c.py` (overtime elapsed time in the win-probability series).
- **The local build** (`docs/rink/data/`, about 109 MB, built at 23:21–23:22 UTC on
  1 October): 2,429 career files (8.9 MB), game pages for 2025–26 (1,394, 39 MB) and
  2026–27 (1,344, 6.1 MB).
- **The public site**: `pchattani/the-quant-rink` was created with
  `setup_public_site.py --site rink` and the first deploy pushed by hand on 1 October 2026
  (the deploy key file `~/.ssh/oddsmarkets_RINK_DEPLOY_KEY.base64.txt` is
  dated 23:15 EDT); RUNBOOK section 2. The local hourly task has dispatched
  `update_rink.yml` every hour from 20:06 EDT (the 19:04 dispatch answered 404 because the
  workflow was not yet on `main`).

---

## 2. History in brief

All on 1 October 2026 (times EDT, from `git log`, the logs and the files' times):

| Time | Milestone |
|---|---|
| 17:15–17:20 | Smoke run of the current season (`logs/nhl_smoke_20262027.log`): 465 calls, 8 final games with play-by-play, shifts, boxscores and derived tables, 302 EDGE pages, ESPN lines for the 8 games, the first 618 MoneyPuck rows of 2026–27. |
| 17:25–17:26 | MoneyPuck backfill, 2025–26 back to 2009–10: 34 calls to peter-tanner.com, 305 MB, 75 s (`logs/nhl_backfill_moneypuck.log`). |
| 17:26 → | NHL backfill, two workers on alternate seasons, newest first (`scripts/nhl_backfill.ps1 -Which nhl`); 2025–26 and 2024–25 done at 18:44, then about an hour a season per worker. |
| 17:27–17:41 | A first ESPN pass for 2025–26 and 2024–25 (64 and 63 final games with lines). |
| 17:43–17:45 | Builder C's fit (`fit_c.fit_all`): `team_strength_params`, `game_params`, `awards_fit` and `season_sim_params`, then the backtest written to `calibration.json` (21:45 UTC) on the four seasons with stores, rated on goals only. |
| 17:41–20:43 | ESPN backfill, 2025–26 back to 2019–20: 10,370 calls (9,030 core odds), 302.8 MB, 10,891 s, 0 failures (`logs/nhl_backfill_espn.log`). |
| 18:24–18:36 | 2025–26 and 2024–25 derived; the 57 games of 2024–25 whose shift charts answer empty rebuilt from the NHL's HTML time-on-ice reports (`logs/nhl_backfill_html_2024.log`). |
| 18:26–18:49 | Builder B's fits on 2024–25 and 2025–26: `xg.json` and `xg_main.txt.gz` (18:26), `stabilise.json` (18:27), `value.json` (18:33), `rapm_prior.json` (18:49). |
| 19:10 | "NHL (The Quant Rink): data, xG/RAPM/value, team and season models, analytics, site and pipeline" (`a70b2fe`): `canon.py`, `store.py`, `derive.py`, the sources, every model with its committed fits, `analytics/`, `scripts/{nhl_fetch,nhl_fit,nhl_hydrate,build_rink}.py`, `nhl_backfill.ps1`, the site shell and its twenty-one JS modules, `update_rink.yml`, the tests. |
| 19:21–19:22 | The local build (the manifests' `built_at` 23:21 UTC, `index.json` 23:22 UTC), adding the xG validation and benchmark blocks to `calibration.json`. |
| 19:26 | "Rink: checkpoint fixes" (`4c85f34`): market source labels, gap names, distinct team colours, the exact-score grid, a games floor for count percentiles, game-log results. |
| about 23:15 | `setup_public_site.py --site rink`; the first deploy pushed by hand. |
| 23:17 | "Rink: goalie player pages highlight Goalies in the nav" (`21cce5e`). |

`oddsmarkets/nhl/CONTRACT.md` and `PAYLOADS.md` record how the work was split while it
was built: builder A owned the data layer (`canon.py`, `store.py`, `derive.py`, the
sources except markets, `nhl_fetch.py`, `nhl_backfill.ps1`), builder B the shot and player
models (`xg`, `shooting`, `goalies`, `onice`, `rapm`, `value`, `lines`, `stabilise`,
`_io.py`, `_stints.py`, `fit_b.py`), builder C the team and pricing models
(`team_strength`, `game`, `live`, `season_sim`, `awards`, `award_winners`, `backtest`,
`sources/markets.py`, `_cdata.py`, `fit_c.py`), builder D the payload build
(`analytics/`, `scripts/build_rink.py`) and builders E and F the front-end. The names
survive in docstrings and code comments ("builder B's xG"); `an.scrub` removes them from
every published payload.

---

## 3. System overview

```
 GitHub Actions (pchattani/oddsmarkets, private)                    Owner's machine
 ───────────────────────────────────────────────                    ───────────────
 .github/workflows/update_rink.yml  "Rink Hourly Update"            scripts/nhl_backfill.ps1 (nhl, espn, moneypuck workers)
 cron '32 * * * *' (hourly) and '2,17,47 * * * *' (game windows)    fit_b.fit_all, fit_c.fit_all, scripts/nhl_fit.py
 55-minute job, concurrency rink-build, contents: read              completed seasons committed by hand
                                                                    the first deploy pushed by hand
   0. game-window gate (the :02/:17/:47 runs exit unless a game     scripts/refresh_sofascore_all.ps1 (hourly
      is live or starts within 30 min, from the deployed              Windows task): dispatches this workflow
      index.json)
   1. checkout, Python 3.11, uv sync
   2. restore data/nhl/{pbp,shifts,box,edge,stats,derived}/<S>
      (Actions cache) and data/nhl/cache (model caches)
   3. clone the public repo; rsync --ignore-existing its data/
      into docs/rink/data/ (previous payloads and manifests)
   4. nhl_hydrate.py: the current season's store.json from the
      live site (kept only when newer)
   5. nhl_fetch.py --seasons <S> --refresh-current --budget 3000     ≤ 20 min
        ▲ api-web.nhle.com (schedule, play-by-play, boxscores, standings, rosters, EDGE, partner odds)
        ▲ api.nhle.com/stats/rest (shift charts, season reports)   ▲ www.nhl.com (HTML TOI fallback)
        ▲ site.api.espn.com, sports.core.api.espn.com              ▲ peter-tanner.com (MoneyPuck, daily)
        (then the season's events.parquet / stints.parquet are rebuilt)
   6. build_rink.py --game-page-seasons 2                         ≤ 25 min
        ▲ Kalshi, Polymarket (game prices, futures, points ladders, awards)
   7. prune data/<S>/games/ for seasons ≤ current − 2
   8. rsync --delete docs/rink/ ──► deploy key (RINK_DEPLOY_KEY)
                                         │
                                         ▼
                        ┌───────────────────────────────────────┐
                        │ pchattani/the-quant-rink (public;     │
                        │ named by the RINK_REPO variable)      │
                        └──────────────────┬────────────────────┘
                                           ▼
             GitHub Pages: https://pchattani.github.io/the-quant-rink/
```

Why it is shaped this way, and where it differs from the sister sites:

- **The NHL's own APIs answer GitHub's runners.** api-web and stats REST have no key and
  no CORS (so they are fetched in CI, never in the browser) and tolerate a few requests a
  second; ESPN, MoneyPuck and the markets also answer datacenter addresses. So CI fetches
  for itself; the local scheduled task only dispatches the workflow, because GitHub drops
  many scheduled runs. Why nothing else: [DATA_PIPELINE.md](DATA_PIPELINE.md) section 2.8.
- **A game-window cadence.** The `:32` cron always runs; the `:02`, `:17` and `:47` runs
  read the deployed `index.json` and stop at the first step unless a game is live, or one
  in `live`, `today` or `upcoming` starts between 30 minutes from now and 3 h 30 ago. So
  the site moves every 15 minutes during games (most evenings October to June) and hourly
  otherwise.
- **CI commits nothing.** `permissions: contents: read`. The current season's store is
  taken from the deployed site at the start of each run (step 4), updated and deployed
  again, so the public site is the store of record for the current season.
- **Completed seasons are committed by hand**, once, after the Stanley Cup Final
  (`.gitignore` un-ignores `docs/rink/data/*/store.json` and `calibration.json` only).
- **The fitted models are committed.** CI holds only the current season's raw data and
  derived tables (and whatever the Actions cache carries), so every model that trains on
  earlier seasons reads `oddsmarkets/nhl/models/fitted/` when its cache is cold
  (`_io.get_fit`, `game.params`, `team_strength.params`, `season_sim.sim_params`); CI never
  trains or backtests.
- **Game pages are pruned.** A game page carries the shot map, box and line usage (about
  25–28 KB, 35–39 MB a season); the public site keeps them for the current and the previous
  season.
- **Private engine, public site**, as for the other sites: `docs/rink/` is rsynced
  (`--delete`, excluding `raw/` and `*.tmp`) into `pchattani/the-quant-rink`. Without
  `RINK_REPO` and `RINK_DEPLOY_KEY` the workflow builds and exits with "build only, no
  deploy".

---

## 4. Repository map

Only the NHL parts; [the football ARCHITECTURE.md](../ARCHITECTURE.md) maps the rest.

```
oddsmarkets/nhl/
├── CONTRACT.md                 data and model interfaces (the builders' contract; builder A's "As built")
├── PAYLOADS.md                 every payload under docs/rink/data/ and the front-end contract ("As built")
├── canon.py                    seasons and coverage constants, formats, teams and relocations, colours, divisions by era,
│                               ESPN ids, 56 arenas (40 home rinks, 16 neutral sites) and 34 outdoor stadiums, situation
│                               codes, the tiebreak procedure (quoted) and its application (order_tied, rank, playoff_seeds)
├── store.py                    paths, season stores: load / save (atomic), Lock, save_owned (per-phase field ownership),
│                               merge_game, complete_through, seasons_on_disk
├── derive.py                   play-by-play + shift charts → events.parquet, stints.parquet, onice_check.json
├── sources/
│   ├── _client.py              paced client (per-host intervals, a global min gap, 4 attempts, budget, never raises)
│   ├── nhl.py                  api-web: schedule, play-by-play, boxscore, standings, rosters, players, partner odds
│   ├── stats.py                stats REST: shift charts, season reports, season list; the HTML TOI fallback
│   ├── edge.py                 NHL EDGE skater / goalie / team detail
│   ├── moneypuck.py            MoneyPuck season shot files → slim Parquet (benchmark only)
│   ├── espn.py                 scoreboard, summary pickcenter, core odds → GAME.lines (books, open / close), event mapping
│   └── markets.py              Kalshi and Polymarket futures, game prices, points ladders, award fields
├── models/
│   ├── _io.py                  roots, canonical events, LightGBM helpers, cross-fitting, fitted read/write, statistics
│   ├── _stints.py              enriched stints (events attributed, xG, score/venue weights), player-stint and player-game tables
│   ├── xg.py                   expected goals (LightGBM, arena adjustment, Platt, empty-net logistic), MoneyPuck benchmark
│   ├── shooting.py, goalies.py goals above xG (shrunk); GSAx by danger, shot type and situation (shrunk)
│   ├── onice.py, lines.py      on-ice rates by role (raw, adjusted, relative); forward lines and defence pairs (shrunk)
│   ├── rapm.py, value.py       5v5 RAPM (xG, goals, attempts) with multi-season priors; Rink value (GAR, WAR)
│   ├── stabilise.py            split-half stabilisation constants
│   ├── fit_b.py                builder B's fit order (xG → stabilise → RAPM prior → value)
│   ├── _cdata.py               builder C's games frame, schedule context, team-game table
│   ├── team_strength.py        unit ratings (5v5 xG and shots, PP / PK, penalties, goals), finishing, goalies, priors
│   ├── game.py                 bivariate Poisson + late-game chain + OT / SO; walk-forward rows; the fit
│   ├── live.py                 live win probability (Markov chain on the goal difference)
│   ├── season_sim.py           20,000-run season, tiebreakers, playoffs, lottery, magic numbers, next-game odds
│   ├── awards.py, award_winners.py   conditional-logit races, Ross / Richard simulation; verified winners 2009-10 to 2025-26
│   ├── backtest.py, fit_c.py   walk-forward backtest → calibration.json; builder C's fit entry point and report
│   ├── synthetic_b.py, synthetic_c.py   synthetic seasons with planted truth (tests)
│   └── fitted/                 committed fits (9 files)
└── analytics/
    ├── __init__.py             roots, rounding, metric records, percentiles, shrinkage, scrub
    ├── context.py              SeasonContext (store, normalised events and stints with xG, model outputs, phase)
    ├── adapters.py             isolated calls into builders B's and C's models
    ├── tables.py, box.py       per player-game, goalie-game and team-game tables; line combinations; QoC / QoT
    ├── skaters.py, goalies.py  the catalogues
    ├── teams.py, season.py     teams.json; season.json, schedule.json, markets.json
    ├── games.py                game cards and game centre pages
    ├── leaders.py              leaders, lab, lines, awards
    ├── history.py, careers.py  history.json; career files and players_index.json
    ├── glossary.py, edge.py    glossary.json; EDGE readers
    └── xgfallback.py           the season-fitted logistic xG used when the model does not score a season
scripts/
├── nhl_fetch.py                schedule, pbp, shifts, box, edge, espn, moneypuck → stores and raw files; derive; --report, --check-canon
├── nhl_backfill.ps1            detached hidden backfill workers (-Which nhl | espn | moneypuck | all)
├── nhl_fit.py                  builder B's fit_all and builder C's exports (see MODELS.md section 16.2)
├── nhl_hydrate.py              CI: the current season's store from the live site
├── build_rink.py               every payload under docs/rink/data/
├── setup_public_site.py        one-time public repo, deploy key, secret, variable, Pages (--site rink)
└── refresh_sofascore_all.ps1   the local hourly task (dispatches update_rink.yml among others)
tests/nhl/                      pytest, offline: 103 test functions in 5 files (102 at HEAD), recorded fixtures in fixtures/
docs/
├── rink/                       The Quant Rink: index.html, assets/{base.css, rink.css, pages.css, pages-f.css, js/},
│                               data/ (stores, calibration, payloads)
└── nhl/                        these documents (not published)
.github/workflows/update_rink.yml   hourly (:32) and game-window (:02, :17, :47) hydrate, fetch, build, prune, deploy
data/nhl/                       git-ignored: pbp/, shifts/, box/, edge/, stats/, moneypuck/, derived/, cache/
logs/                           git-ignored: nhl_backfill_*.log, nhl_smoke_20262027.log
```

---

## 5. Key design decisions

**One store per season is the single source of truth for games.** The schedule, results,
lines (ESPN's books with open and close, or the DraftKings pickcenter and the NHL partner
odds for upcoming games), goalies, attendance, standings and rosters are merged into
`docs/rink/data/<season>/store.json`. Fetchers write it through `store.save_owned`, which
lets each fetch phase write only the fields it owns; the build only reads it. Play-level
data stays in the raw files and the derived tables, never in the store. See
[DATA_PIPELINE.md](DATA_PIPELINE.md) sections 6 and 7.

**Events and stints are the play-level backbone.** `derive.py` turns each game's
play-by-play and shift charts into one row per event (coordinates normalised so the event
team attacks +x, the players on the ice, the strength and the score before the event) and
one row per stint (a stretch of play with the same players on both sides), and checks the
on-ice counts against the NHL's situation code (99.3–99.8% agreement in 2021–22 to 2025–26;
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 3).

**Our own xG, benchmarked against a published one.** MoneyPuck's xGoal is downloaded only
to score our model on the same shots ([MODELS.md](MODELS.md) section 14.2); nothing on the
site uses MoneyPuck's numbers as a metric.

**Fitted once, read many times.** Every model writes its fit to the cache, and the fit
scripts export the same fits to `models/fitted/` (versioned). The build reads the cache when
the version matches, else the committed fit, so CI never trains on seasons it does not
hold.

**The models degrade instead of failing.** Every model call from the build is isolated
(`analytics/adapters.py`): a model that is missing or raises yields `{"ok": false}`, the
metrics that need it are `null` and the reason is listed in the season manifest's
`model_errors`. When the xG model does not score a season, the build fits a logistic on the
season's own attempts and says so (`xg_source` "fallback"). Every build step is wrapped
(`Build.step`); a payload that cannot be built is written as `{"ok": false, "reason": ...}`;
`index.json` is never overwritten when the current season was not built.

**Full and light seasons, manifests and frozen prices.** The current season is built in
full (season simulation, game prices in the pricing window, markets, award races, the
players' current blocks); every other season light, and skipped when its signature (the
store's content hash, the derived tables' sizes and mtimes, the model versions) is
unchanged. Each season's `manifest.json` also keeps every game's last pre-game price
(`"source": "frozen"`), so a game that has started keeps the price it had.

**A page is never downgraded.** CI holds only the current season's events; a game page
whose events are not on the machine keeps the previous page's event-level blocks
(`kept_from`), and a past season without derived events on the machine keeps its payloads.

**Payloads are JSON; the front-end is hand-written static JS.** No template engine, no
bundler: `index.html` and twenty-one scripts under `assets/js/` are shipped verbatim;
Plotly 2.27 loads from cdn.plot.ly. The shell was copied from The Quant Gridiron
(`window.GI` became `window.RK`); `assets/base.css` is copied from
`docs/site/assets/style.css` on every build.

**The metric catalogue drives the front-end.** `analytics/skaters.py` and `goalies.py` emit
each metric's key, label, group, format, direction, scope, unit and stabilisation point
with the payload; the catalogues, player pages, lab, compare, leaders and glossary render
from it.

**Memory is bounded by design.** One season of events and stints is in memory at a time;
the contract forbids recursive closures holding arrays (the tennis memory incident,
[`docs/tennis/MODELS.md`](../tennis/MODELS.md) section 12); `SeasonContext.free()` releases
each season.

**Licences and credits are carried with the data.** NHL data is shown for informational,
non-commercial use; "xG benchmark data from MoneyPuck.com" is credited wherever MoneyPuck's
numbers appear (MoneyPuck's terms: free for non-commercial use with credit, file downloads
only, at most nightly). The disclaimer, the footer and the glossary carry the notices.

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11; CI uses 3.11 |
| Environment | uv (`pyproject.toml`, `uv.lock`), shared with the other sites |
| Numerics | numpy, scipy (Cholesky, sparse ridge, L-BFGS), pandas, pyarrow (Parquet), LightGBM (xG) |
| HTTP | `requests` through `sources/_client.py`; the shared prediction-market client (`oddsmarkets/common/prediction_markets.py`) and the Hardwood's sport-neutral parsers (`basketball/sources/markets.py`) for Kalshi and Polymarket; `urllib` in `nhl_hydrate.py` and the workflow's gate |
| Tests | pytest, `tests/nhl/` (offline; recorded api-web, stats REST, ESPN, partner and MoneyPuck fixtures, synthetic seasons with planted truth) |
| Browser | twenty-one plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly |
| CI / hosting | GitHub Actions (`update_rink.yml`), Actions caches for the current season's raw data and the model caches, GitHub Pages from the public repo |

---

## 7. Getting started

From the repository root:

```bash
uv sync --group dev

# NHL tests: offline
uv run --group dev pytest tests/nhl

# Build every payload from the stores and the derived tables on disk
uv run python scripts/build_rink.py                                    # current season full, the rest light
uv run python scripts/build_rink.py --quick --no-market --no-light     # fast local check
uv run python scripts/build_rink.py --seasons 20262027 20252026        # two seasons in full
```

A fresh clone has the code and the committed fits, but (until the completed seasons are
committed, RUNBOOK section 5) no store, no `calibration.json` and no raw data. To work on
the current season, `python scripts/nhl_hydrate.py` copies its store from the live site, and
`python scripts/nhl_fetch.py --refresh-current` fetches the current season's raw files and
rebuilds its derived tables. For past seasons, run the backfill
(`powershell -File scripts/nhl_backfill.ps1 -Which all`; [DATA_PIPELINE.md](DATA_PIPELINE.md)
section 10): it is resumable and takes about an hour a season per NHL worker. Preview:

```bash
cd docs/rink
python -m http.server              # then open http://localhost:8000
```

A cold build scores every season with the committed xG model and caches the shot tables
under `data/nhl/cache/`. The Calibration page reads `calibration.json`; it is rewritten by
`fit_c.fit_all()` (the backtest) and topped up by every build with the xG blocks
([RUNBOOK.md](RUNBOOK.md) section 4).

Do not run two `nhl_fetch.py` processes that write the same phase of the same season.
Different phases may run at once (the ESPN backfill beside the NHL workers on the same
season): the store's lock and per-phase ownership keep their writes apart.

---

## 8. Conventions

- **Under `docs/rink/data/`, only completed seasons' `store.json` and `calibration.json` are
  committed** (`.gitignore`). Everything else is build output. The pattern also un-ignores
  the current season's store, so add stores explicitly by path.
- **Seasons are NHL ids** (`20262027`); `--from 2026`, `20262027` and `2026-27` all name the
  same season in `nhl_fetch.py` (`canon.norm_season`); ids are strings in payloads; teams
  are the tri-code of that season (`canon.code_in_season`).
- **The puck line is the home team's line, negative when the home team is favoured**
  (`lines.puck_line.home`; `GAME_CARD.line.puck_line`).
- **Coordinates are feet from centre ice**, normalised so the event team attacks +x; the
  goal line is at x = 89 (`_io.GOAL_X`), the blue lines at ±25.
- **Time**: `sec` is elapsed game seconds (a regular-season shootout sits at 3,900); `t` is
  seconds into the period; `clock` is the time remaining in the period.
- **Numbers are rounded at the payload boundary**: probabilities 4 decimals, rates per 60 2,
  fractions 0–1. NaN and infinity become `null`.
- **Commits go on `main`.** CI never pushes to this repository.
- **Person pronouns.** Several docstrings and the Methodology say "his"; new text should say
  "they".

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **store** | `docs/rink/data/<season>/store.json`: one season's teams, games, standings snapshot, players and fetch marks. |
| **GAME** | One game in a store (`sources/nhl.compact_game`, merged by `store.merge_game`); fields in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 6.1. |
| **events** | `data/nhl/derived/<S>/events.parquet`: one row per play-by-play event with normalised coordinates, strength, score and on-ice players. |
| **stint** | A stretch of play with the same skaters and goalies on both sides (`stints.parquet`); the unit of on-ice rates, lines and RAPM. |
| **on-ice check** | The share of events whose on-ice counts from the shift charts agree with the NHL's situation code (`onice_check.json`). |
| **xG / ixG / GAx** | Expected goals of an unblocked attempt / summed over a player's attempts / goals minus ixG. |
| **GSAx** | Goals saved above expected: xG of the unblocked attempts a goalie faced minus the goals allowed (empty net excluded). |
| **cross-fitted** | Each row predicted by a model that did not see it: by season with three or more seasons, by game with fewer (`_io.fold_ids`). |
| **arena adjustment** | Quantile matching of shot distances in a team's home rink onto its road games, for hand-tracked seasons (before 2020–21). |
| **score and venue adjustment** | 5v5 events weighted 0.5 / (the league's share for a side in that score state at that venue), clipped to [0.7, 1.4]. |
| **RAPM** | Regularised adjusted plus-minus: a ridge on 5v5 stints with an offence and a defence coefficient per skater. |
| **Rink value, GAR, WAR** | Goals and wins above replacement from RAPM with a box prior, special teams, shooting and penalties (goalies: GSAx). |
| **stabilisation point** | The sample at which split-half reliability reaches 0.7, n₀.₇ = 7k/3. |
| **net rating** | A team's goals per game minus goals against per game against a league-average team and goalie. |
| **frozen price** | The last pre-game model price of a game, kept in the season manifest once the game starts. |
| **full / light season** | Built with the simulation, prices, markets and current blocks (the current season), or without them. |
| **manifest** | `data/<S>/manifest.json`: input signature, frozen prices, page signatures, model errors, xG source, timings. |
| **hydrate** | CI's copy of the current season's store from the live site (`nhl_hydrate.py`). |
| **game window** | A live game, or a start within 30 minutes (to 3 h 30 after it), read from the deployed `index.json`. |
| **Builders A–F** | The work packages in `CONTRACT.md` and `PAYLOADS.md`. |
