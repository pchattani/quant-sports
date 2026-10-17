# Architecture: The Quant Gridiron

This is the top-level map of the NFL side of the `oddsmarkets` repository and the site it
publishes, **The Quant Gridiron** (<https://pchattani.github.io/the-quant-gridiron/>).
Start here if you are new to the NFL code. Four sibling documents cover the detail, and
this one links to them rather than repeating them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | the nflverse mirror, ESPN, the markets, the stores, the derived play table, the scheduled job, the backfill |
| [MODELS.md](MODELS.md) | the play models (EP, WP, fourth downs, completion, YAC, RYOE, kicking, value), team strength, the game model, the simulations, markets, the backtest |
| [DASHBOARD.md](DASHBOARD.md) | the static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | operations, deploy, refits, troubleshooting |

`HANDOFF.md` at the repository root holds the open tasks of every site.

---

## 1. What the site is

The Quant Gridiron is a static NFL analytics site rebuilt by GitHub Actions every hour,
and every 15 minutes while a game is on. A season is the year it starts (2026 includes
the January and February 2027 playoffs; `canon.current_season`: March to February is one
season), a game is an nflverse `game_id` (`2026_04_PIT_CLE`), a player a gsis id
(`00-0036355`) and a team the nflverse abbreviation it used that season (`LA` for the Rams
from 2016, `STL` before; `oddsmarkets/nfl/canon.py`). Everything play-level comes from
the nflverse data releases on GitHub; lines come from nflverse's schedules (closing spread
and total from 1999, moneylines from 2006) and ESPN's odds endpoint (every book, open and
close, from 2017); live state comes from ESPN; prices from Kalshi and Polymarket.

The depth of each season is set by what nflverse publishes (the exact state on disk is in
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 3):

| Tier | From | What it enables |
|---|---|---|
| Play-by-play (372 columns, nflfastR's EP/WP/CPOE/xYAC kept for comparison) | 1999 | every play model, catalogues, team units, history |
| Schedules: closing spread and total | 1999 | the game model's market comparison, ATS records |
| Schedules: closing moneylines | 2006 (partial in 2006 and 2008) | the backtest against the moneyline (2006 on) |
| Our completion model (air yards on every pass) | 2009 | CPOE, CROE |
| Next Gen Stats (season and weekly rows), participation (formation, personnel, box, coverage, pressure) | 2016 (participation 2016–2025 only, published after each season) | tracking measures, the participation tiers of the play models, on-field RAPM |
| ESPN core odds by book | 2017 (opening lines from 2023) | per-book closing lines, the "v book" scores |
| FTN charting (play action, RPO, motion, blitzers, drops, interception-worthy throws) | 2022 | the FTN tiers of the play models, tendencies, turnover-worthy rate |

Two facts that the code does not show shape everything:

- **Participation is never available in-season.** nflverse publishes `pbp_participation`
  after each season (2016–2025 on disk), so the current season's completion, YAC and RYOE
  run on the base and FTN tiers, and the on-field (RAPM-style) value and the pressure
  inputs are missing until the season is over ([MODELS.md](MODELS.md) section 16).
- **Nothing tracks individual coverage.** Defenders are rated only on what play-by-play
  credits them with (sacks, hits, tackles, takeaways, passes defensed).

What the site offers (the navigation in `docs/gridiron/index.html`; a season picker and
a week picker sit above it):

- **Hub**: the week at a glance, live games (refreshed every minute), this week's games
  with model against market against the line and live win probability, the biggest
  model–market gaps, playoff odds, leaders and last week's results.
- **Week** (`#/week/<S>/<w>`): every game of a week with prices, key matchups and, once
  final, how the model's favourites and its sides against the line did.
- **Game centre** (`#/game/<game_id>`): pre-game model against market and line (win,
  spread, total, the margin and total distributions with the key numbers), injuries and
  QBs, weather, unit matchups; live and after: win probability by play (ours against
  nflfastR's and ESPN's) with every fourth down marked by its grade, the drive chart, the
  play table with EPA and WPA, the box score with advanced and NGS columns, key plays,
  awards.
- **Standings** (divisions, conference seeding, ratings, win totals, draft order) and
  **Playoffs** (the bracket with odds, seed distributions, round odds against the market).
- **Teams** and **team pages** (unit ratings week by week, tendencies, pace, fourth-down
  aggressiveness, schedule against the model, QB situation, roster value).
- **Players** (a catalogue by position group with stabilisation-aware percentiles) and
  **player pages** (Savant-style sliders, game log, career from 1999, NGS and FTN panels,
  pass grids, RYOE by game, similar players).
- **Fourth downs** (every fourth down graded) and **Coaches** (go rate over expected,
  agreement with the model, WP given up).
- **Leaders**, **History** (1999 on, raw and era-adjusted), **Lab** (any two metrics),
  **Compare**.
- **Markets**: games and futures (Super Bowl, conferences, divisions, playoffs, No. 1
  seeds, win totals, awards), model against the de-vigged market.
- **Calibration**: the walk-forward game backtest against Elo and the closing lines, ATS
  and totals, season odds, and our EP and WP against nflfastR's.
- **Glossary** and **Methodology**: every metric and model term, and a long methodology
  document (it quotes the committed fits; [MODELS.md](MODELS.md) section 17 records what was
  corrected on 1 October 2026).

### What is on disk today

As of this writing (1 October 2026, about 22:10 UTC, read from the files):

- **Stores** for 1999 to 2026: 259 games a season (1999–2001), 267 (2002–2019), 269
  (2020), 284–285 (2021–2025); 2026 holds 272 scheduled games, 48 final (weeks 1–3
  complete, `complete_through` 3; the index says week 4, phase `regular`).
- **Committed to git** (`290dbff`): every completed season's `store.json` (1999–2025),
  `docs/gridiron/data/calibration.json` and the 30 files of
  `oddsmarkets/nfl/models/fitted/` (JSON parameters and gzipped LightGBM boosters). The
  current season (2026) lives on the deployed site.
- **The nflverse mirror** under `data/nfl/raw/` (git-ignored; 582 MB, 15 releases), the
  derived play tables under `data/nfl/derived/<season>/plays.parquet` (186 MB) and the
  caches under `data/nfl/cache/` (273 MB: model outputs, ESPN raw odds and live records).
- **The local build** (`docs/gridiron/data/`, about 134 MB): 7,471 career files (31 MB),
  game pages for 2025 (285, 18 MB) and 2026 (272); the last full local build wrote 1,436
  files in 379 s with 0 step errors (`logs/build_gridiron_run4.log`).
- **The public site**: the deploy model (a public repo `pchattani/the-quant-gridiron`
  set up by `setup_public_site.py --site gridiron`, a first deploy pushed by hand, then
  CI) is in [RUNBOOK.md](RUNBOOK.md) section 2. At the time of writing no
  `oddsmarkets_GRIDIRON_DEPLOY_KEY.base64.txt` existed under `~/.ssh/`, so the
  set-up had not yet been run from this machine; the local hourly task dispatched
  `update_gridiron.yml` successfully from 22:04 UTC (`scripts/refresh_sofascore.log`; the
  21:04 dispatch answered 404 because the workflow was not yet on `main`).

---

## 2. History in brief

All on 1 October 2026 (times UTC, from `git log` and the logs):

| Time | Milestone |
|---|---|
| 20:22–20:26 | nflverse backfill, 1999–2026: 531 calls to github.com, 608 MB, 193 s (`logs/nfl_backfill_nflverse.log`); 28 season stores and derived play tables built. |
| 20:27–21:12 | ESPN odds backfill, 2026 back to 2017: 2,542 core odds calls, 0 failures, 2,765 s (`logs/nfl_backfill_espn.log`). |
| 21:04–21:05 | Builder C's fit (`nfl_fit.py --only c`): team-strength carry-over, the walk-forward game fit (65 s), the backtest (`logs/nfl_fit_c.log`). |
| 21:18 | `calibration.json` written by the backtest (5,479 games 2006–2026, 101 s). |
| 20:39–21:25 | Four full local builds (`logs/build_gridiron_run1..4.log`), 0 step errors each. |
| 21:31 | "NFL (The Quant Gridiron): data, play models, team and season models, analytics, site and pipeline" (`290dbff`): `canon.py`, `store.py`, `tiebreak.py`, the sources, every model under `models/` with its committed fits, `analytics/`, `scripts/{nfl_fetch,nfl_fit,nfl_hydrate,build_gridiron}.py`, the site shell and its twenty-one JS modules, `update_gridiron.yml`, the completed seasons' stores and `calibration.json`. |
| 21:32 | "Gridiron: show the stadium name on game pages" (`bca7904`). |

`oddsmarkets/nfl/CONTRACT.md` and `PAYLOADS.md` record how the work was split while it
was built: builder A owned the data layer (`canon.py`, `store.py`, `tiebreak.py`, the
nflverse and ESPN sources), builder B the play-level models (`ep`, `wp`, `fourth_down`,
`completion`, `yac`, `ryoe`, `pressure`, `player_value`, `qb`, `kicking`, `stabilise`,
`_io.py`), builder C the team and pricing models (`team_strength`, `game`, `drive_sim`,
`live`, `season_sim`, `awards`, `backtest`, `sources/markets.py`, `_cdata.py`), builder D
the payload build (`analytics/`, `scripts/build_gridiron.py`) and builders E and F the
front-end. The names survive in docstrings and code comments ("builder C's backtest").

---

## 3. System overview

```
 GitHub Actions (pchattani/oddsmarkets, private)                    Owner's machine
 ───────────────────────────────────────────────                    ───────────────
 .github/workflows/update_gridiron.yml  "Gridiron Hourly Update"     scripts/nfl_fetch.py (backfill 1999→, ESPN odds 2017→)
 cron '52 * * * *' (hourly) and '7,22,37 * * * *' (game windows)     scripts/nfl_fit.py (committed fits, backtest)
 55-minute job, concurrency gridiron-build, contents: read           completed seasons committed by hand
                                                                     the first deploy pushed by hand
   0. game-window gate (the :07/:22/:37 runs exit unless a game      scripts/refresh_sofascore_all.ps1 (hourly
      is live or kicks off within 30 min, from the deployed            Windows task): dispatches this workflow
      index.json)
   1. checkout, Python 3.11, uv sync
   2. restore data/nfl/{raw,derived} (Actions cache, per season)
      and data/nfl/cache (model caches)
   3. clone the public repo; rsync --ignore-existing its data/
      into docs/gridiron/data/ (previous payloads and manifests)
   4. nfl_hydrate.py: the current season's store.json from the
      live site (kept only when newer)
   5. nfl_fetch.py --refresh-current --espn --budget 1500        ≤ 15 min
        ▲ github.com/nflverse/nflverse-data (timestamp-gated)
        ▲ site.api.espn.com, sports.core.api.espn.com (odds, live)
   6. build_gridiron.py --game-page-seasons 2                    ≤ 30 min
        ▲ Kalshi, Polymarket (game prices, futures)
   7. prune data/<S>/games/ for seasons ≤ current − 2
   8. rsync --delete docs/gridiron/ ──► deploy key (GRIDIRON_DEPLOY_KEY)
                                         │
                                         ▼
                        ┌───────────────────────────────────────┐
                        │ pchattani/the-quant-gridiron (public; │
                        │ named by the GRIDIRON_REPO variable)  │
                        └──────────────────┬────────────────────┘
                                           ▼
             GitHub Pages: https://pchattani.github.io/the-quant-gridiron/
```

Why it is shaped this way, and where it differs from the sister sites:

- **One free source for everything play-level.** nflverse republishes the NFL's
  play-by-play with nflfastR's columns, the schedules with closing lines, NGS, FTN
  charting and participation as Parquet release assets on GitHub, which answer GitHub's
  runners and are not API-rate-limited. ESPN supplies what nflverse lacks (lines by book,
  live state). So CI fetches for itself; the local scheduled task only dispatches the
  workflow, because GitHub drops many scheduled runs. Why nothing else:
  [DATA_PIPELINE.md](DATA_PIPELINE.md) section 2.5.
- **A game-window cadence.** The `:52` cron always runs; the `:07`, `:22` and `:37` runs
  read the deployed `index.json` and stop at the first step unless a game is live or
  kicks off within 30 minutes (and up to 4 h 30 after kickoff). So the site moves every
  15 minutes during games and hourly otherwise.
- **CI commits nothing.** `permissions: contents: read`. The current season's store is
  taken from the deployed site at the start of each run (step 4), updated and deployed
  again, so the public site is the store of record for the current season.
- **Completed seasons are committed by hand**, once, after the Super Bowl (`.gitignore`
  un-ignores `docs/gridiron/data/*/store.json` and `calibration.json` only).
- **The fitted models are committed.** CI holds only the current season's play-by-play
  (and whatever the Actions cache carries), so every model that trains on earlier seasons
  reads `oddsmarkets/nfl/models/fitted/` when its cache is cold; CI never trains or
  backtests (`nfl_fit.py` runs on the owner's machine).
- **Game pages are pruned.** A game page carries the full play table (about 50–65 KB,
  15–18 MB a season); the public site keeps them for the current and the previous season.
- **Private engine, public site**, as for the other sites: `docs/gridiron/` is rsynced
  (`--delete`, excluding `raw/` and `*.tmp`) into `pchattani/the-quant-gridiron`. Without
  `GRIDIRON_REPO` and `GRIDIRON_DEPLOY_KEY` the workflow builds and exits with "build only,
  no deploy".

---

## 4. Repository map

Only the NFL parts; [the football ARCHITECTURE.md](../ARCHITECTURE.md) maps the rest.

```
oddsmarkets/nfl/
├── CONTRACT.md                 data and model interfaces (the builders' contract)
├── PAYLOADS.md                 every payload under docs/gridiron/data/ and the front-end contract ("As built")
├── canon.py                    seasons and coverage constants, formats by season, franchises and relocations, ESPN team
│                               ids, division alignments (1999-2001 and 2002 on), ~60 stadiums, the tiebreak procedure as data
├── store.py                    season stores: paths, load / save (atomic), Lock, save_owned (per-phase field ownership),
│                               merge_game, complete_through, seasons_on_disk
├── tiebreak.py                 Table: division order, Wild Card order, conference seeding with the NFL's procedure
├── sources/
│   ├── _client.py              paced client (per-host intervals, 4 attempts, budget, never raises; head, download)
│   ├── nflverse.py             release mirror with the timestamp gate, schema checks, schedules → GAME, the derived plays
│   ├── espn.py                 scoreboard, summary → compact live record, core odds → lines by book, game-id mapping
│   └── markets.py              Kalshi and Polymarket futures, game prices, win-total ladders, award fields
├── models/
│   ├── _io.py                  roots, loaders, plays(season) cache, JSON cache, fitted read/write, LightGBM helpers
│   ├── ep.py, wp.py            expected points, win probability (LightGBM, cross-fitted by season)
│   ├── fourth_down.py          go / punt / FG win probability, conversion model, grades, two-point tries, GOE model
│   ├── completion.py, yac.py, ryoe.py    cp / CPOE / CROE, xYAC / YACOE, RYOE (feature tiers)
│   ├── kicking.py              FG make probability with kicker random effects, PAT rate, punt model, punter value
│   ├── pressure.py             sacks, hits, pressure; SROE; pass-rush rates
│   ├── player_value.py         raw EPA credit, opponent/cast-adjusted ridge value, on-field RAPM (2016-2025)
│   ├── qb.py, stabilise.py     QB composite; split-half stabilisation constants
│   ├── fit_b.py                builder B's fit order
│   ├── _cdata.py               builder C's games frame, unit table, drive table
│   ├── team_strength.py        opponent-adjusted unit ratings with a QB component, priors, carry-over
│   ├── game.py                 margin and total model, key-number distribution, market conversions, walk-forward
│   ├── drive_sim.py            drive-level Monte Carlo (score shape, team totals, overtime rules by era)
│   ├── live.py                 live WP from ESPN's state (B's WP model, a closed-form fallback)
│   ├── season_sim.py           20,000-run season and playoffs with FastTable tiebreakers, draft order, magic numbers
│   ├── awards.py, award_winners.py   conditional-logit award races; verified AP winners 2006-2025
│   ├── backtest.py, fit_c.py   walk-forward backtest → calibration.json; builder C's fit entry point
│   ├── synthetic_b.py, synthetic_c.py   synthetic seasons with planted truth (tests)
│   └── fitted/                 committed fits (30 files)
└── analytics/
    ├── __init__.py             roots, rounding, JSON helpers, season lists
    ├── context.py              SeasonContext (store, plays with FTN/participation and our model columns, model outputs)
    ├── adapters.py             isolated calls into builders B's and C's models
    ├── players.py              the catalogue by position group, QB composite scaling
    ├── teams.py, teamsref.py   team units, tendencies, pace; team reference fallback
    ├── season.py               season.json, schedule, weeks, markets payload, gaps
    ├── games.py                game cards, game centre pages, grades, injuries
    ├── fourth.py               fourth_downs.json, coaches.json, referees.json
    ├── leaders.py              leaders, lab, awards, glossary
    ├── history.py, careers.py, people.py   history.json, career files, the player crosswalk
scripts/
├── nfl_fetch.py                releases, schedule → stores, derived plays, ESPN odds and live; --refresh-current, --report
├── nfl_fit.py                  builder B's exports and builder C's fit_all (committed fits, backtest)
├── nfl_hydrate.py              CI: the current season's store from the live site
├── build_gridiron.py           every payload under docs/gridiron/data/
├── setup_public_site.py        one-time public repo, deploy key, secret, variable, Pages (--site gridiron)
└── refresh_sofascore_all.ps1   the local hourly task (dispatches update_gridiron.yml among others)
tests/nfl/                      pytest, offline: 84 test functions in 5 files, recorded fixtures in fixtures/
docs/
├── gridiron/                   The Quant Gridiron: index.html, assets/{base.css, gridiron.css, pages.css, pages-f.css, js/},
│                               data/ (stores, calibration, payloads)
└── nfl/                        these documents (not published)
.github/workflows/update_gridiron.yml   hourly (:52) and game-window (:07, :22, :37) hydrate, fetch, build, prune, deploy
data/nfl/                       git-ignored: raw/ (nflverse mirror), derived/ (play tables), cache/
logs/                           git-ignored: nfl_backfill_*.log, nfl_fit_c.log, build_gridiron_run*.log
```

---

## 5. Key design decisions

**One store per season is the single source of truth for games.** The schedule, results,
lines (nflverse's closing line and ESPN's books), venue, weather, officials, starting QBs,
coaches and the live state of every game are merged into
`docs/gridiron/data/<season>/store.json`. Fetchers write it, through `store.save_owned`,
which lets each fetch phase write only the fields it owns; the build only reads it.
Play-level data stays in the nflverse mirror and the derived play table, never in the
store. See [DATA_PIPELINE.md](DATA_PIPELINE.md) section 6.

**Our own models, compared with the published ones.** nflfastR's EP, WP, CPOE and xYAC
come with the play-by-play; the site fits its own (cross-fitted by season, so every play
is scored by a model that never saw its season) and publishes both on the Calibration page
and the game pages. EPA on the site is ours wherever our EP scored the season.

**Walk-forward where it matters.** The game model's backtest refits team strength before
every week from that season's earlier games and the game coefficients on earlier rows
only; the season-odds checks simulate from checkpoints with ratings fitted strictly before
them. The play models are cross-fitted by season rather than walk-forward (they describe
plays, not forecasts).

**Fitted once, read many times.** Every model writes its fit to the cache, and
`nfl_fit.py` exports the same fits to `models/fitted/` (versioned). The build reads the
cache when the version matches, else the committed fit (`_io.get_fit`, `game.params`,
`team_strength.params`), so CI never trains on seasons it does not hold.

**The models degrade instead of failing.** Every model call from the build is isolated
(`analytics/adapters.py`): a model that is missing or raises yields `{"ok": false}`, the
metrics that need it are `null` and the reason is listed in the season manifest's
`model_errors`. Every build step is wrapped (`Build.step`); a payload that cannot be built
is written as `{"ok": false, "reason": ...}`; `index.json` is never overwritten when the
current season was not built.

**Full and light seasons, manifests and frozen prices.** The current season is built in
full (season simulation, game prices in the pricing window, markets, award races, the
players' current blocks); every other season light, and skipped when its signature (the
store's content hash, the release files' sizes and mtimes, the model versions and fit
keys) is unchanged. Each season's `manifest.json` also keeps every game's last pre-game
price (`"source": "frozen"`), so a game that has kicked off keeps the price it had.

**A page is never downgraded.** CI holds only the current season's play-by-play; a game
page whose plays are not on the machine keeps the previous page's play-level blocks, and
a past season without play-by-play on the machine keeps its payloads.

**Payloads are JSON; the front-end is hand-written static JS.** No template engine, no
bundler: `index.html` and twenty-one scripts under `assets/js/` are shipped verbatim;
Plotly 2.27 loads from cdn.plot.ly. The shell was copied from The Quant Bullpen
(`window.BP` became `window.GI`); `assets/base.css` is copied from
`docs/site/assets/style.css` on every build.

**The metric catalogue drives the front-end.** `analytics/players.py` emits each metric's
key, label, group, format, direction, scope (position groups), unit and stabilisation
point with the payload; the catalogue, player pages, lab, compare, leaders and glossary
render from it.

**Memory is bounded by design.** One season of plays is in memory at a time; the
contract forbids recursive closures holding arrays (the tennis memory incident,
[`docs/tennis/MODELS.md`](../tennis/MODELS.md) section 12); `SeasonContext.free()`
releases each season.

**Licences are carried with the data.** nflverse data is CC BY 4.0 (credited), FTN
charting CC BY-SA 4.0 (derived charting data shared alike), NGS is redistributed NFL data
shown for informational, non-commercial use; the disclaimer, footer and glossary carry the
notices.

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11; CI uses 3.11 |
| Environment | uv (`pyproject.toml`, `uv.lock`), shared with the other sites |
| Numerics | numpy, scipy (L-BFGS, Cholesky, sparse ridge), pandas, pyarrow (Parquet), LightGBM (the play models) |
| HTTP | `requests` through `sources/_client.py`; the shared prediction-market client (`oddsmarkets/common/prediction_markets.py`) for Kalshi and Polymarket; `urllib` in `nfl_hydrate.py` and the workflow's gate |
| Tests | pytest, `tests/nfl/` (offline; recorded nflverse Parquet slices, ESPN and market fixtures, synthetic seasons) |
| Browser | twenty-one plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly |
| CI / hosting | GitHub Actions (`update_gridiron.yml`), Actions caches for the mirror and model caches, GitHub Pages from the public repo |

---

## 7. Getting started

From the repository root:

```bash
uv sync --group dev

# NFL tests: offline
uv run --group dev pytest tests/nfl

# Build every payload from the stores and the mirror on disk
uv run python scripts/build_gridiron.py                                    # current season full, the rest light
uv run python scripts/build_gridiron.py --quick --no-market --no-light     # fast local check
uv run python scripts/build_gridiron.py --seasons 2026 2025                # two seasons in full
```

A fresh clone has every completed season's store, `calibration.json` and the committed
fits, but not the current season's store and no play-by-play. To work on the current
season, `python scripts/nfl_hydrate.py` copies its store from the live site, and
`python scripts/nfl_fetch.py --refresh-current --espn` fetches the current season's
releases (and the season-less ones). For past seasons' catalogues, fetch the mirror:
`python scripts/nfl_fetch.py --from 1999 --to 2026` (about 600 MB, a few minutes;
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 10). Preview:

```bash
cd docs/gridiron
python -m http.server 8899          # then open http://localhost:8899
```

A cold build scores every season with the play models (cached under `data/nfl/cache/`
afterwards). The Calibration page reads the committed `calibration.json`; rebuild it with
`python scripts/nfl_fit.py --only c` ([RUNBOOK.md](RUNBOOK.md) section 4).

Do not run two `nfl_fetch.py` processes that write the same phase of the same season.
Different phases may run at once (the ESPN odds backfill beside a schedule rebuild): the
store's lock and per-phase ownership keep their writes apart.

---

## 8. Conventions

- **Under `docs/gridiron/data/`, only completed seasons' `store.json` and
  `calibration.json` are committed** (`.gitignore`). Everything else is build output. The
  pattern also un-ignores the current season's store, so add stores explicitly by path.
- **Seasons are the year the season starts**; ids are strings; teams are the abbreviation
  of that season (STL→LA 2016, SD→LAC 2017, OAK→LV 2020; `canon.RELOCATIONS`).
- **Spreads are the home team's betting line, negative when the home team is favoured**
  (`lines.spread_home` = −nflverse `spread_line`); `model.spread = −model.margin`, where
  `margin` is the expected home-minus-away points.
- **Field position is `yardline_100`**, the distance to the opponent's goal line.
- **Numbers are rounded at the payload boundary**: probabilities 4 decimals, EPA 3;
  fmt "pct" values are 0–1 fractions. NaN and infinity become `null`.
- **Commits go on `main`.** CI never pushes to this repository.
- **Person pronouns.** Some docstrings say "his"; new text should say "they".

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **store** | `docs/gridiron/data/<season>/store.json`: one season's teams and games, merged from the sources. |
| **GAME** | One game in a store (`nflverse.compact_game`, merged by `store.merge_game`); fields in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 6.1. |
| **release** | An nflverse-data GitHub release (`pbp`, `schedules`, `nextgen_stats`, ...); its files are mirrored under `data/nfl/raw/<release>/`. |
| **timestamp gate** | A release's `timestamp.txt` is read once per run; a file whose manifest entry carries that timestamp is not requested again. |
| **derived plays** | `data/nfl/derived/<season>/plays.parquet`: the play-by-play columns the models use with FTN (`ftn_*`) and participation (`part_*`) joined. |
| **EP / EPA** | Expected points of the next score in the half / the change across a play; ours unless a column says nflfastR. |
| **WP / WPA** | Win probability of the team in possession (home WP on pages) / its change across a play. |
| **cross-fitted** | Seasons dealt into five folds; every play is scored by a model trained without its season. |
| **tier** | A feature set of the completion, YAC and RYOE models (base, participation, FTN, FTN + participation); each play uses the richest its season has. |
| **net rating** | A team's points per game against an average team on a neutral field, from the unit ratings and the starting QB. |
| **frozen price** | The last pre-game model price of a game, kept in the season manifest once the game starts. |
| **full / light season** | Built with the simulation, prices, markets and current blocks (the current season), or without them. |
| **manifest** | `data/<S>/manifest.json`: input signature, frozen prices, page signatures, model errors, timings. |
| **hydrate** | CI's copy of the current season's store from the live site (`nfl_hydrate.py`). |
| **game window** | A live game, or a kickoff within 30 minutes (to 4 h 30 after it), read from the deployed `index.json`. |
| **GOE** | Go rate over expected: a coach's fourth-down go rate minus a league model's expected rate in the same situations. |
| **Builders A–F** | The work packages in `CONTRACT.md` and `PAYLOADS.md`. |
