# Architecture: The Quant Bullpen

This is the top-level map of the baseball side of the `oddsmarkets` repository and the site
it publishes, **The Quant Bullpen** (<https://pchattani.github.io/the-quant-bullpen/>),
which covers MLB and Triple-A. Start here if you are new to the baseball code. Four sibling
documents cover the detail, and this one links to them rather than repeating them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Savant, the Stats API, ESPN, Retrosheet, Chadwick, Lahman, the stores, the pitch tables, the hourly job, the backfill |
| [MODELS.md](MODELS.md) | the pitch models, xwOBA+, fielding, framing, umpires, run expectancy, parks, WAR, projections, the simulations, markets, the backtest |
| [DASHBOARD.md](DASHBOARD.md) | the static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | operations, deploy, refits, the backfill, troubleshooting |

`HANDOFF.md` at the repository root holds the open tasks of every site.

---

## 1. What the site is

The Quant Bullpen is a static MLB and Triple-A analytics site rebuilt every hour by GitHub
Actions. Both levels share one code path; a level is `"mlb"` or `"aaa"` everywhere, a
season is a calendar year (`canon.current_season`; the season window runs 10 March to 10
November), a player id (`pid`) is an MLBAM id as a string (`"r:<retroid>"` for players
known only to Retrosheet), a team an MLBAM team id and a game an MLBAM gamePk
(`oddsmarkets/baseball/canon.py`). Every pitch comes from Baseball Savant's Statcast search;
schedules, live games, rosters and venues from the MLB Stats API; lines from ESPN (several
books, opening and closing from 2023); history from Retrosheet; identities from the Chadwick
register; prices from Kalshi and Polymarket.

The depth of each season is set by what the sources hold (the exact state on disk is in
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 3):

| Tier | MLB | Triple-A | What it enables |
|---|---|---|---|
| Retrosheet game logs | 1901 | – | team runs and hits, validation |
| Retrosheet play-by-play (every PA and running event) | 1908–2025 | – | run expectancy and linear weights by season, history, historical WAR |
| Statcast pitch table (119 columns) | 2015 | 2023 | every pitch model, xwOBA+, catalogues, the game model |
| Bat tracking (bat speed, swing length, attack angle) | 2023–24 | per Savant | adjusted bat speed, squared-up, swing-path fit |
| ESPN lines (several books) | 2015 (offshore books to 2019, US books 2020–24, DraftKings alone in 2026); opening and closing lines from 2023 | none | the backtest's closing line, DraftKings lines on cards |
| ABS challenges (live feed) | 2026 | 2024 | umpire and challenge analytics |

Two facts that the code does not show shape everything:

- **Savant silently caps a search at 25,000 rows** (the newest are returned), so the fetcher
  asks for one day at a time, re-requests an exactly-capped answer in halves, and splits a
  capped single day by pitching team. A full MLB season is about 205 requests and 35
  minutes at the 3-second pacing ([DATA_PIPELINE.md](DATA_PIPELINE.md) section 2.2).
- **CI holds only the current season's pitch table** (about 95 MB in the Actions cache).
  Every model that trains on earlier seasons reads `oddsmarkets/baseball/models/fitted/`
  in CI, projections read exported per-season count aggregates, and past seasons'
  payloads come from the previous deploy.

What the site offers (the navigation in `docs/bullpen/index.html`; a level switch MLB | AAA
and a season picker sit above it):

- **Hub**: the season, the postseason bracket with series odds against the market, live,
  today's, upcoming and recent games with model against market against the DraftKings line
  and live win probability, the biggest gaps, leaders, World Series odds.
- **Games** (`#/<L>/games[/<date>]`) and the **game centre** (`#/<L>/game/<gpk>`): pre-game
  model against market against DraftKings (win, run line, total, first five, the runs
  distribution), lineups with matchup projections, weather, park, umpire; live and after:
  win probability (ours against ESPN's) with the top WPA plays, spray chart, pitch-by-pitch
  with the strike zone, box score with expected stats, the umpire scorecard and ABS
  challenges, each pitcher's arsenal against his season norm.
- **Standings** (W-L, Pythagorean and rating-expected records, simulated odds, magic
  numbers) and **Postseason** (the bracket, series odds, path odds).
- **Hitters** (175 metrics) and **Pitchers** (150 metrics plus arsenals) catalogues with
  percentiles against the level and the position or role, and **player pages** (percentile
  sliders, spray chart, zones, swing decisions, bat tracking, arsenal, movement, release,
  tunnels, fatigue, rolling form, splits, Statcast and Retrosheet careers, projections).
- **Teams** (78 metrics, ratings, roster, bullpen availability, alignment, park, schedule
  against the model), **Leaders**, **Umpires**, **Parks**, **Prospects** (Triple-A with MLB
  translations), **History** (1908 on, era-adjusted), **Awards**, **Lab**, **Compare**.
- **Markets**: games, series and futures (World Series, pennants, awards), model against
  the de-vigged market.
- **Calibration**: the walk-forward game backtest against ESPN's closing lines and the
  model checks (xwOBA+ against Savant's xwOBA, Stuff+ validity, projections against a
  Marcel-style baseline, framing and fielding against Savant).
- **Glossary** and **Methodology**: every metric and model term, and a long methodology
  document ([MODELS.md](MODELS.md) section 22 lists where it and the code disagreed, resolved
  on 1 October 2026).

### What is on disk today

As of 2 October 2026, about 05:00 UTC, after the backfill (read from the files):

- **MLB stores** for 2015 to 2026: 2,465–2,477 games a season (953 in 2020); 2026 holds
  2,460 games, 2,427 final, and is in the postseason. **Triple-A stores** for 2023 to 2026
  (2,255–2,256 games, 2,194–2,226 final; every season complete).
- **Statcast pitch tables** (`data/baseball/statcast/`, git-ignored): MLB 2015–2026 (2.0 GB,
  280,398 pitches in 2020 to 746,272 in 2019; 2026 has 719,119) and Triple-A 2023–2026
  (592 MB, 672,738–693,119 a season).
- **ESPN lines**: every MLB season 2015–2026, 2,337–2,464 final games a season with lines
  (DATA_PIPELINE.md section 3); none for Triple-A.
- **Retrosheet** (`data/baseball/retro/`, 192 MB): game logs 1901–2025 and parsed events
  1908–2025 (118 seasons), every season's runs and hits matching its game logs exactly.
- **Committed to git** (`400b4e4`, `1c2e8f4`): `docs/bullpen/data/people.json` (the Chadwick
  crosswalk), `docs/bullpen/data/mlb/calibration.json` and the 21 files of
  `oddsmarkets/baseball/models/fitted/`. **No season store is committed yet**: the completed
  seasons' stores (MLB 2015–2025, Triple-A 2023–2025) await the commit of RUNBOOK.md
  section 6.
- **The local build** (`docs/bullpen/data/`, about 1.05 GB): 6,126 career files (82 MB),
  game pages for MLB 2025 and 2026 (172 and 173 MB) and Triple-A 2025 and 2026 (156 and
  159 MB); everything else about 390 MB. That is above GitHub Pages' 1 GB published-site
  limit, so a hand deploy of the whole tree needs fewer game-page seasons (section 7 of the
  runbook prunes older seasons only).
- **The public site**: the deploy model (a public repo `pchattani/the-quant-bullpen` set up
  by `setup_public_site.py --site bullpen`, a first deploy pushed by hand, then CI) is in
  [RUNBOOK.md](RUNBOOK.md) section 2. The set-up ran and the first deploy was pushed by
  hand on 1 October 2026; https://pchattani.github.io/the-quant-bullpen/ is live, and the
  local hourly task dispatches `update_bullpen.yml` (`scripts/refresh_sofascore.log`).

### NPB (the third level, 13 October 2026)

Nippon Professional Baseball is the level `npb`, built by its own package `oddsmarkets/baseball/npb/` from the
official NPB site (npb.jp) and Kalshi's NPB markets, with its own pages (`assets/js/npb.js`). No pitch tracking or
fielding data exist for NPB, so the level is results, line scores, box scores, season and career statistics, team ratings
and a three-way (home, tie, away) game model; the Statcast pages are MLB and Triple-A only. Since 15 October 2026 npb.jp's
plate-appearance play-by-play (2016 on) feeds an NPB lab and compare (`npb/pbp.py`, `npb/pbpstats.py`, `npb/lab.py`;
[MODELS.md](MODELS.md) section 24), and every level has a Value page, team strengths and needs and (MLB, NPB) a trade
simulator (`analytics/value.py`, `analytics/trade.py`, `assets/js/value.js`; [MODELS.md](MODELS.md) section 25).

| Tier | NPB | What it enables |
|---|---|---|
| Yearly league pages (standings, team totals, awards, qualified leaders) | 1950 on (the two-league era) | History, champions by year |
| Japan Series results | 1950 on | History |
| Club rosters by year with NPB ids, player career pages | 1950 on | careers, all-time leaders, names |
| Day pages and box scores (line score, batting and pitching lines, decisions, home runs) | 2005 on (per-plate-appearance results from 2026) | games, ratings, the backtest, positions for WAR-lite |
| Club stat pages (batting and pitching by club), English names | 2005 on (English 2008 on) | players.json, WAR-lite |
| Kalshi game and champion prices | 2026 | the market comparison |

It is fetched by `scripts/npb_fetch.py` (hourly in season through `scripts/local_sites.py`, the backfill through
`scripts/npb_backfill.ps1`) and built by `scripts/build_bullpen.py` with the other levels. Its stores are kept off the
public site. Details: [DATA_PIPELINE.md](DATA_PIPELINE.md) section 14, [MODELS.md](MODELS.md) section 23,
[DASHBOARD.md](DASHBOARD.md) section 11, [RUNBOOK.md](RUNBOOK.md) section 12.

---

## 2. History in brief

All on 1 October 2026 (times UTC, from `git log` and the logs, whose own timestamps are US
Eastern):

| Time | Milestone |
|---|---|
| 16:33–18:26 | The 2026 smoke run (`logs/mlb_2026_smoke.log`): schedule, 186 days of Statcast, feeds, ESPN lines and people for the current season; 5,257 calls, 0 failures, 6,763 s. |
| 16:40–16:55 | Retrosheet backfill, 2025 back to 1901 with the Lahman cross-check (`logs/mlb_backfill_retro.log`): 367 calls, 885 s. |
| from 17:06 | Savant backfill, MLB 2025 back to 2015 (`logs/mlb_backfill_savant_mlb.log`), about 35 minutes and 260 calls a season; at 2016 at the time of writing. |
| from 18:28 | ESPN lines backfill, 2025 back to 2015 (`logs/mlb_backfill_espn.log`), about 2,670 calls and 50 minutes a season; at 2021 at the time of writing. |
| 19:01 | The 2026 game backtest written to `calibration.json` (2,427 games, 856 s). |
| 17:43–19:59 | The committed fits (`mlb_fit.py`, file times): the game simulation's transition tables (17:43); RE24, framing, catch probability, xwOBA+, parks, stabilisation, WAR constants (19:18–19:21); the pitch models fitted on 2022–2025 (19:39); the projection aggregates (19:59). |
| 20:39 | "Baseball (The Quant Bullpen): data, pitch models, value, prediction, analytics, site and pipeline" (`400b4e4`): `canon.py`, `store.py`, the seven sources, every model under `models/` with its committed fits, `analytics/`, `scripts/{mlb_fetch,mlb_retro,mlb_fit,mlb_hydrate,build_bullpen}.py`, `scripts/mlb_backfill.ps1`, the site shell and its twenty-three JS modules, `update_bullpen.yml`, `people.json` and `calibration.json`. |
| 20:44 | "Bullpen: score postseason batted balls with the committed xwOBA+ model; correct the spray wording" (`1c2e8f4`). |

`oddsmarkets/baseball/CONTRACT.md` and `PAYLOADS.md` record how the work was split while it
was built: builder A owned the data layer (`canon.py`, `store.py`, the sources except
markets), builder B the pitch models (`physics`, `stuff`, `location`, `pitching`,
`tunneling`, `swing`, `battrack`, `fatigue`, `prep`, `_io.py`), builder C the batted-ball and
value models (`xwoba`, `catchprob`, `framing`, `umpire`, `re24`, `parks`, `war`, `history`,
`stabilise`, `_c.py`), builder D the prediction models (`projections`, `game_inputs`,
`game_sim`, `live`, `season_sim`, `awards`, `backtest`, `sources/markets.py`, `_dio.py`),
builder E the payload build (`analytics/`, `scripts/build_bullpen.py`) and builders F and G
the front-end. The names survive in docstrings ("builder D's backtest").

---

## 3. System overview

```
 GitHub Actions (pchattani/oddsmarkets, private)                    Owner's machine
 ───────────────────────────────────────────────                    ───────────────
 .github/workflows/update_bullpen.yml  "Bullpen Hourly Update"       scripts/mlb_backfill.ps1 (detached: Savant MLB
 cron '7 * * * *', 55-minute job, concurrency bullpen-build            2025→2015 then AAA 2023→2026; ESPN lines
 permissions: contents read (commits nothing)                          2025→2015; Retrosheet 2025→1901)
                                                                     scripts/mlb_fit.py (committed fits)
   1. checkout, Python 3.11, uv sync                                 models/backtest.py (calibration.json)
   2. restore the current season's pitch tables (mlb, aaa) and       completed seasons committed by hand
      data/baseball/cache (Actions caches)                           the first deploy pushed by hand
   3. clone the public repo; rsync --ignore-existing its data/       scripts/refresh_sofascore_all.ps1 (hourly
      into docs/bullpen/data/ (previous payloads and manifests)        Windows task): dispatches this workflow
   4. mlb_hydrate.py: each level's current store.json from the
      live site (kept only when newer)
   5. mlb_fetch.py --level mlb --refresh-current --budget 900   ≤ 15 min
        ▲ statsapi.mlb.com (schedule, feeds, standings, rosters, transactions)
        ▲ baseballsavant.mlb.com (yesterday and today)
        ▲ site.api.espn.com, sports.core.api.espn.com (lines, ESPN WP)
   6. mlb_fetch.py --level aaa --refresh-current --budget 300   ≤ 8 min
   7. build_bullpen.py --game-page-seasons 2                    ≤ 30 min
        ▲ Kalshi, Polymarket (game and series prices, futures)
   8. prune <L>/<S>/games/ for seasons ≤ this year − 2
   9. rsync --delete docs/bullpen/ ──► deploy key (BULLPEN_DEPLOY_KEY)
                                         │
                                         ▼
                        ┌───────────────────────────────────────┐
                        │ pchattani/the-quant-bullpen (public;  │
                        │ named by the BULLPEN_REPO variable)   │
                        └──────────────────┬────────────────────┘
                                           ▼
              GitHub Pages: https://pchattani.github.io/the-quant-bullpen/
```

Why it is shaped this way, and where it differs from the sister sites:

- **Free sources that answer GitHub's runners.** Savant, the Stats API and ESPN all serve
  datacenter addresses, so CI fetches for itself; the local scheduled task only dispatches
  the workflow, because GitHub drops many scheduled runs. Why nothing else:
  [DATA_PIPELINE.md](DATA_PIPELINE.md) section 2.8.
- **CI commits nothing.** `permissions: contents: read`. Each level's current store is
  taken from the deployed site at the start of each run (step 4), updated and deployed
  again, so the public site is the store of record for the current season.
- **Completed seasons are committed by hand**, once, after the World Series (`.gitignore`
  un-ignores `docs/bullpen/data/*/*/store.json`, `people.json` and each level's
  `calibration.json`).
- **The fitted models are committed**, and CI never retrains the large ones: the pitch
  models, xwOBA+, catch probability, framing, parks, RE24, stabilisation, WAR constants,
  the game simulation's transition tables and the projection aggregates all come from
  `models/fitted/` when the cache is cold.
- **Game pages are pruned.** A game page carries pitch-by-pitch (50–70 KB, 150–190 MB a
  season); the public site keeps them for the current and the previous season.
- **Private engine, public site**, as for the other sites: `docs/bullpen/` is rsynced
  (`--delete`, excluding `raw/` and `*.tmp`) into `pchattani/the-quant-bullpen`. Without
  `BULLPEN_REPO` and `BULLPEN_DEPLOY_KEY` the workflow builds and exits with "build only, no
  deploy".

---

## 4. Repository map

Only the baseball parts; [the football ARCHITECTURE.md](../ARCHITECTURE.md) maps the rest.

```
oddsmarkets/baseball/
├── CONTRACT.md                 data and model interfaces (the builders' contract)
├── PAYLOADS.md                 every payload under docs/bullpen/data/ and the front-end contract ("As built")
├── canon.py                    levels, game types, positions, the 30 franchises by season (MLBAM, Savant, ESPN, Retrosheet,
│                               Baseball-Reference codes; names, leagues, divisions), game status
├── store.py                    stores and paths: load / save (atomic), Lock, save_owned (per-phase field ownership),
│                               merge_game, complete_through, seasons_on_disk
├── sources/
│   ├── _client.py              paced client (per-host intervals, 4 attempts, budget, never raises)
│   ├── savant.py               day-chunked Statcast search with the cap re-split, typing, Parquet parts, leaderboards
│   ├── statsapi.py             schedule, feeds, teams, venues, people, standings, rosters, transactions, ABS
│   ├── espn.py                 scoreboard, core odds → lines by book, run-line sign, ESPN WP, event matching
│   ├── retrosheet.py           event files, game logs, our own event-file parser, the notice
│   ├── chadwick.py, lahman.py  the identity register (people.json); the Lahman cross-check
│   └── markets.py              Kalshi and Polymarket: World Series, pennants, awards, series, games
├── models/
│   ├── _io.py, prep.py         builder B: roots, outcome classes, families; the enriched pitch table per season
│   ├── physics.py              trajectory, VAA/HAA, IVB/HB, decision point, spin axis, seam-shifted wake, spin efficiency
│   ├── stuff.py, location.py, pitching.py   Stuff+, Location+, Pitching+ (LightGBM, 100 = league average)
│   ├── tunneling.py, swing.py, battrack.py, fatigue.py   tunnels, swing decisions, bat tracking, fatigue signals
│   ├── _c.py                   builder C: loaders, PA table, batted-ball geometry, launch physics, penalised logistic
│   ├── xwoba.py, catchprob.py  xwOBA+; catch probability and fielding runs
│   ├── framing.py, umpire.py   called-strike model and framing; umpire accuracy, scorecards, ABS
│   ├── re24.py, parks.py       run and win expectancy, linear and wOBA weights (Statcast and Retrosheet); park factors
│   ├── war.py, history.py, stabilise.py   Bullpen WAR (Statcast and historical); careers 1908→; stabilisation
│   ├── fit_c.py                builder C's exports
│   ├── _dio.py                 builder D: paths, stores, PA extraction
│   ├── projections.py          component projections, aging, Triple-A translations
│   ├── game_inputs.py, game_sim.py, live.py   game specs; the PA Monte Carlo; live WP Markov chain
│   ├── season_sim.py, awards.py, backtest.py  season and postseason; award races; walk-forward backtest and checks
│   ├── synthetic.py, synthetic_c.py, synthetic_d.py   synthetic pitch tables and seasons with planted truth (tests)
│   └── fitted/                 committed fits (21 files)
└── analytics/
    ├── __init__.py, context.py, catalog.py, fallbacks.py   roots and helpers; SeasonContext; catalogue plumbing;
    │                           the CI fallbacks (projection aggregates)
    ├── pitchagg.py             one pass over a season's pitches: PA table, counting tables
    ├── hitters.py, pitchers.py, fielders.py, teams.py   the catalogues
    ├── season.py, games.py     season.json, the bracket, markets, schedule, index entries; cards and game pages
    ├── umpires.py, parks.py, leaders.py, awards.py, prospects.py   the per-season pages' payloads
    ├── history.py, careers.py, glossary.py   history.json, career files, glossary.json
    ├── value.py, trade.py, value_build.py   player value, best by position, strengths and needs; the trade simulator's
    │                           depth charts and sensitivity curves; the build step (MLB, Triple-A)
scripts/
├── mlb_fetch.py                schedule, statcast, games, espn, people → stores and pitch tables; --refresh-current, --report
├── mlb_retro.py                Retrosheet events and game logs, validation, Lahman cross-check
├── mlb_fit.py                  the committed fits (builders B, C, D and the projection aggregates)
├── mlb_hydrate.py              CI: each level's current store from the live site
├── mlb_backfill.ps1            the detached historical backfill (Savant, ESPN, Retrosheet)
├── npb_fetch.py                npb.jp (and Kalshi) into the NPB stores; --refresh-current (hourly), --backfill, --report
├── npb_backfill.ps1            the detached NPB backfill (logs/npb_backfill.log)
├── build_bullpen.py            every payload under docs/bullpen/data/
├── setup_public_site.py        one-time public repo, deploy key, secret, variable, Pages (--site bullpen)
└── refresh_sofascore_all.ps1   the local hourly task (dispatches update_bullpen.yml among others)
├── npb/                        Nippon Professional Baseball (level npb): canon.py (franchises, rules by season), html.py (a small
│                               HTML tree), source.py (the npb.jp client and parsers), store.py, models.py (linear weights, WAR-lite,
│                               ratings, the three-way game model, the simulations), backtest.py, build.py, markets.py (Kalshi),
│                               pbp.py, pbpstats.py, lab.py (play-by-play 2016 on: parsers, RE24, season tables, expected stats,
│                               the lab payload), valuebuild.py (the NPB lab, value and trade files)
tests/baseball/                 pytest, offline: recorded fixtures in fixtures/ (fixtures/npb/: recorded npb.jp pages); test_npb.py,
                                test_npb_pbp.py, test_value_trade.py
docs/
├── bullpen/                    The Quant Bullpen: index.html, assets/{base.css, bullpen.css, pages.css, pages-g.css, js/},
│                               data/ (stores, people.json, calibration, payloads)
└── baseball/                   these documents (not published)
.github/workflows/update_bullpen.yml   hourly (:07) hydrate, fetch, build, prune, deploy
data/baseball/                  git-ignored: statcast/<L>/ (pitch tables), retro/ (events, game logs), cache/
logs/                           git-ignored: mlb_backfill_*.log, mlb_2026_smoke.log
```

---

## 5. Key design decisions

**One store per level and season for games, one Parquet table for pitches.** The schedule,
results, linescores, lineups, probables, decisions, weather, umpires, venues, lines, ABS
counts, rosters and standings are merged into `docs/bullpen/data/<L>/<S>/store.json`;
every pitch lives in `data/baseball/statcast/<L>/<S>.parquet` (Savant's column names, typed),
never in the store. Fetchers write both (the store through `store.save_owned`, which lets
each fetch phase write only the fields it owns, so the Savant and ESPN backfills can run on
the same season at once); the build only reads them. See
[DATA_PIPELINE.md](DATA_PIPELINE.md) sections 6 and 7.

**Our own models beside the published ones.** xwOBA+ sits next to Savant's xwOBA, our
fielding runs next to Savant's OAA, our framing next to Savant's framing runs, and the
Calibration page reports the comparisons side by side without a verdict field. Labels are
neutral ("xwOBA+ (ours)", "xwOBA (Savant)").

**Walk-forward where it matters.** The game backtest prices every game with projections
refitted every 7 days from games strictly before it, usage to the day before and park
factors from earlier seasons; the pitch models train on the four seasons before the
target season; xwOBA+ and catch probability are cross-fitted by game.

**Fitted once, read many times.** The pitch models train on 350,000–400,000 sampled
pitches from each of four seasons, one season in memory at a time; `mlb_fit.py` exports
them to `models/fitted/` and CI reads those. `analytics/fallbacks.py` wraps the projections
so a season whose pitch table is absent reads the exported count aggregates.

**The models degrade instead of failing.** Every model call from the build is isolated
(`SeasonContext.model`): a model that is missing or raises yields `{"ok": false, "reason"}`,
the metrics that need it are `null`, and the catalogue's `model_errors` says why. Every
build step is wrapped (`Build.step`); a payload that cannot be built is written as
`{"ok": false, "reason": ...}`; a partial run never removes a level's entry from
`index.json`.

**Full and light seasons, manifests and frozen prices.** The current season is built in
full (season simulation, game prices in the pricing window, markets, award races,
projections, the players' current blocks); every other season light, and skipped when its
signature (the store's content hash, the pitch table's size and mtime, the model versions)
is unchanged, or when its pitch table is not on the machine but its payloads exist. Each
season's `manifest.json` keeps every game's last pre-game price, so a page that has gone
live keeps the price it had.

**Payloads are JSON; the front-end is hand-written static JS.** No template engine, no
bundler: `index.html` and twenty-three scripts under `assets/js/` are shipped verbatim;
Plotly 2.27 loads from cdn.plot.ly. The shell was copied from The Quant Ace (`window.TA`
became `window.BP`, the tour switch a level switch); `assets/base.css` is copied from
`docs/site/assets/style.css` on every build.

**The metric catalogue drives the front-end.** Each catalogue emits its metrics with key,
label, group, format, direction, scope, unit and stabilisation point; the catalogue pages,
player pages, lab, compare, leaders and glossary render from it, and percentiles are placed
on values shrunk by each metric's stabilisation constant.

**Memory is bounded by design.** One season of pitches at a time, column subsets, chunked
aggregation, game pages built in batches of 150 games with pitches pushed down to Parquet;
no recursive closures holding arrays (the tennis memory incident,
[`docs/tennis/MODELS.md`](../tennis/MODELS.md) section 12).

**Licences and notices are carried with the data.** The Retrosheet notice is shown
verbatim wherever its data appears (`retrosheet.NOTICE`, in every history payload's
`meta`); the Chadwick register is ODC-BY (attribution string `chadwick.ATTRIBUTION`); the
Lahman database CC BY-SA; MLBAM data is shown for non-commercial, informational use; raw
Statcast and Stats API feeds are never re-hosted.

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11; CI uses 3.11 |
| Environment | uv (`pyproject.toml`, `uv.lock`), shared with the other sites |
| Numerics | numpy, scipy, pandas, pyarrow (Parquet, streamed compaction), LightGBM (the pitch, batted-ball and fielding models) |
| HTTP | `requests` through `sources/_client.py`; the shared prediction-market client for Kalshi and Polymarket; `urllib` in `mlb_hydrate.py` |
| Tests | pytest, `tests/baseball/` (offline; recorded Savant, Stats API, ESPN, Retrosheet, Chadwick and market fixtures; synthetic pitch tables and seasons) |
| Browser | twenty-three plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly |
| CI / hosting | GitHub Actions (`update_bullpen.yml`), Actions caches for the current pitch tables and model caches, GitHub Pages from the public repo |
| Local | PowerShell 5.1 for `mlb_backfill.ps1` (detached hidden processes) |

---

## 7. Getting started

From the repository root:

```bash
uv sync --group dev

# Baseball tests: offline
uv run --group dev pytest tests/baseball

# Build every payload from the stores and pitch tables on disk
uv run python scripts/build_bullpen.py                                    # each level: current full, the rest light
uv run python scripts/build_bullpen.py --quick --no-market --no-light     # fast local check
uv run python scripts/build_bullpen.py --levels mlb --seasons 2026 2025
```

A fresh clone has `people.json`, `calibration.json` and the committed fits, but no season
store (none was committed as of 2 October 2026) and no pitch tables. To work on the current season,
`python scripts/mlb_hydrate.py` copies each level's current store from the live site and
`python scripts/mlb_fetch.py --level mlb --from 2026 --to 2026` fetches its pitches (about
35 minutes at Savant's pacing). The full history is the backfill
([RUNBOOK.md](RUNBOOK.md) section 5). Preview:

```bash
cd docs/bullpen
python -m http.server 8897          # then open http://localhost:8897
```

A cold build scores every pitch of every season with the pitch models (cached under
`data/baseball/cache/` afterwards; the first full build takes a while). The Calibration
page reads `docs/bullpen/data/mlb/calibration.json`; rebuild its games block with the
backtest ([RUNBOOK.md](RUNBOOK.md) section 4).

Do not run two `mlb_fetch.py` processes on the same phase of the same season. Different
phases may run at once (the Savant and ESPN backfills do): the store's lock and per-phase
ownership keep their writes apart.

---

## 8. Conventions

- **Under `docs/bullpen/data/`, only completed seasons' `store.json`, `people.json` and each
  level's `calibration.json` are committed** (`.gitignore`). Everything else is build
  output. The pattern also un-ignores the current season's store, so add stores
  explicitly by path. As of 1 October 2026 no store is committed yet.
- **Seasons are calendar years**, levels are lower case, ids are strings. Retrosheet-only
  players are `r:<retroid>`.
- **HB is arm-side positive for both hands** everywhere in the payloads; IVB in inches;
  coordinates in the catcher's view.
- **No earned runs exist in the pitch data**: `r` and `ra9` are all runs scored while the
  pitcher was on the mound; FIP is on the RA9 scale.
- **Numbers are rounded at the payload boundary**: probabilities 4 decimals, rates 3,
  "plus" scores integers (100 = average), "war" 1; fmt "pct" values are 0–1 fractions.
- **Commits go on `main`.** CI never pushes to this repository.
- **Person pronouns.** Some docstrings say "his"; new text should say "they".

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **store** | `docs/bullpen/data/<L>/<S>/store.json`: one level-season's teams, venues, players, umpires and games. |
| **GAME** | One game in a store (`statsapi.compact_game`, merged by `store.merge_game`); fields in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 6.1. |
| **pitch table** | `data/baseball/statcast/<L>/<S>.parquet`: every Statcast pitch of a level-season, Savant's column names. |
| **gpk / pid / tid / vid** | MLBAM gamePk / player id / team id / venue id, as strings. |
| **the cap** | Savant's silent 25,000-row limit per search. |
| **PA table** | One row per plate appearance, from the pitch table (`_c.pa_table`, `_dio.plate_appearances`) or from Retrosheet (`retro/pa/<S>.parquet`). |
| **rv / rv_dn** | A pitch's `delta_run_exp` (batting side) / the same with in-play luck removed. |
| **Stuff+ / Location+ / Pitching+** | Pitch scores, 100 = the league-average pitch, 10 = one SD of pitcher-pitch-type quality. |
| **xwOBA+** | Our expected wOBA on the wOBA scale (not an index); `xwoba_n` its park-neutral version. |
| **decision value (dv)** | Runs a hitter's swing or take gained over the league-average decision on that pitch. |
| **Bullpen WAR** | Our WAR; position players' batting from regressed park-neutral xwOBA+ (talent), with a results-based figure beside it. |
| **k / n₀.₇** | A metric's stabilisation constant and the sample at which split-half reliability reaches 0.7 (7k/3). |
| **full / light season** | Built with the simulation, prices, markets, projections and current blocks (the current season), or without them. |
| **frozen price** | The last pre-game model price of a game, kept in the season manifest once it starts. |
| **manifest** | `data/<L>/<S>/manifest.json`: input signature, frozen prices, page signatures, model errors, timings. |
| **hydrate** | CI's copy of each level's current store from the live site (`mlb_hydrate.py`). |
| **Builders A–G** | The work packages in `CONTRACT.md` and `PAYLOADS.md`. |
