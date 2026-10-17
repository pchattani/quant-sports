# Architecture: The Quant Hardwood

This is the top-level map of the basketball side of the `oddsmarkets` repository and
the site it publishes, **The Quant Hardwood**
(<https://pchattani.github.io/the-quant-hardwood/>), which covers the NBA and the
WNBA. Start here if you are new to the basketball code. Four sibling documents cover
the detail, and this one links to them rather than repeating them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | ESPN extraction, the stores, play-by-play reconstruction, the derived tables, the hourly job, the backfill |
| [MODELS.md](MODELS.md) | ratings, the game model, the season simulation, Elo, xPTS, RAPM and HPM, win probability and WPA, awards, markets, the backtest |
| [DASHBOARD.md](DASHBOARD.md) | the static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | operations, deploy, troubleshooting |

`HANDOFF.md` at the repository root holds the open basketball tasks alongside the
football and F1 ones.

---

## 1. What the site is

The Quant Hardwood is a static NBA and WNBA analytics site rebuilt every hour by
GitHub Actions. Both leagues share one code path; a league is `"nba"` or `"wnba"`
everywhere, and a season is labelled by the year it ends in (ESPN's `season.year`:
the NBA's 2026-27 season is `2027`, the WNBA's 2026 season is `2026`;
`oddsmarkets/basketball/canon.py`). Every number starts from ESPN's public JSON
APIs; prediction-market prices come from Kalshi and Polymarket.

The depth of each season is set by what ESPN holds (the exact state on disk is in
[DATA_PIPELINE.md](DATA_PIPELINE.md) section 3):

| Tier | NBA | WNBA | What it enables |
|---|---|---|---|
| Schedules and scores | 1997 | 1997 (but see below) | standings, Elo, team ratings, the game model, history |
| Box scores | 1997 | 2002 in practice | player catalogues, box impact, the backtest |
| Plus-minus in the box | about 2007 | about 2007 | on/off from the box |
| Play-by-play | 2002 (585 games), 2003 on | 2002 | possessions, lineups and stints, RAPM, WPA, clutch |
| Play-by-play the parser reads cleanly | 2007 on (2004–2005 reconcile poorly) | 2009 for lineups, 2020 for shots | shot charts, xPTS, reliable possessions |
| DraftKings line in the stores | 2017–2023 and 2026 | 2026 games | the market comparison in the backtest |

What the site offers (the navigation in `docs/hardwood/index.html`; a league switch
NBA | WNBA and a season picker sit above it):

- **Hub**: the league's phase, a countdown to the next tip-off or the games live,
  KPI tiles (title favourite, best team, MVP favourite), today's games with the
  model against the market and live win probability, key upcoming games, title
  odds against the market, power ratings, the award race and a standings snapshot.
- **Season**: standings per conference with projected wins, playoff, play-in and
  title odds and magic numbers; the seed-distribution heatmap; team ratings with
  standard errors; Kalman rating paths; win totals against the market; schedule
  difficulty; leaders.
- **Games**: a date list and a game centre per game: pregame model against the
  market with the margin broken into its parts, injuries, the box score with
  advanced columns, four factors, the margin flow, win probability (ours and
  ESPN's), shot charts with xPTS, lineups, the rotation, the top-leverage plays
  with WPA and six game awards.
- **Teams** and **Players**: catalogues of 76 team metrics and 125 player metrics a
  season with league and position-pool percentiles; team pages with the game log,
  roster, lineups (5-, 3- and 2-man), the rotation matrix, on/off and shot
  profiles; player pages with the career, game log, shot chart, on/off, lineups,
  clutch, projection, award odds and similar players.
- **Leaders**, **Awards** (MVP, ROY, DPOY, Sixth Man / Sixth Player, MIP and the
  NBA's Clutch Player against the markets), **Playoffs** (the projected or actual
  bracket and each team's chance of reaching every round).
- **Lab**: any two player metrics against each other, one season or a window.
- **Compare**: two players or two teams side by side.
- **Markets**: futures, win totals and the next three days' games, model against
  the de-vigged market.
- **Calibration**: the walk-forward backtest against Elo and the DraftKings line,
  the season simulation's calibration, and live win probability against ESPN's.
- **Glossary** and **Methodology**: every metric and model term, and a long
  methodology document whose constants were read from the code.

### What is on disk today

As of this writing (1 October 2026, after the backfill, read from the files):

- **WNBA**: stores for 1997 to 2026, all fetched by the backfill. 2026 holds 377
  games, 357 final, every final game with play-by-play; the phase is "playoffs".
  Derived inputs (`shots.json`, `stints.json`, `recon.json`) exist for every season
  with play-by-play.
- **NBA**: stores for 1997 to 2027, all fetched by the backfill, derived from 2002.
  2027 holds 1,273 scheduled games (phase "preseason").
- **Committed to git**: every completed season's `store.json`, `recon.json`,
  `shots.json.gz` and `stints.json.gz` (NBA 1997–2026, WNBA 1997–2025), both
  `calibration.json` files and `oddsmarkets/basketball/models/fitted/`. The current
  seasons (NBA 2027, WNBA 2026) live on the deployed site.
- **Raw play-by-play** under `data/basketball/pbp/` for NBA 2002 to 2026 and WNBA
  2002 to 2026 (git-ignored).
- **The public site** was first deployed on 1 October 2026 by hand from a local
  build (408 MB); the hourly workflow has deployed since.

---

## 2. History in brief

| Date | Milestone (from `git log`) |
|---|---|
| 1 Oct 2026, 00:56 | "Basketball (The Quant Hardwood), steps 1-2: ESPN data layer and models" (`dcc39d5`): `sources/espn.py`, `store.py`, `canon.py`, `pbp.py`, `sources/markets.py`, every model under `models/`, the fetch and derive scripts and the tests. |
| 1 Oct 2026, 03:17 | "steps 3-5: analytics, site and pipeline" (`e4ada1e`): `analytics/`, `scripts/build_hardwood.py`, `bb_pack.py`, `bb_hydrate.py`, the site shell and its sixteen JS modules, `.github/workflows/update_hardwood.yml`. |
| 1 Oct 2026, 03:22 | "a run without the current season keeps that league's index entry" (`99f2f33`). |
| 1 Oct 2026, 07:17 | "hide preseason win-total edges; link all three sister sites" (`50203f7`). |

The full backfill of both leagues was started detached at about 00:49 UTC the same
day. `oddsmarkets/basketball/CONTRACT.md` records how the work was split while it
was built: builder A owned the sources, stores and play-by-play reconstruction
(`sources/espn.py`, `store.py`, `canon.py`, `pbp.py`, `scripts/bb_derive.py`),
builder B the team side (`ratings.py`, `game.py`, `season_sim.py`, `config.py`,
`elo.py`, `backtest.py`, `sources/markets.py`), builder C the player side
(`shots.py`, `impact.py`, `winprob.py`, `awards.py`), builder D the payload build
(`analytics/`, `scripts/build_hardwood.py`) and builders E and F the front-end
(`PAYLOADS.md`). The names survive in docstrings ("builder B's preseason prior").

---

## 3. System overview

```
 GitHub Actions (pchattani/oddsmarkets, private)                 Owner's machine
 ───────────────────────────────────────────────                 ───────────────
 .github/workflows/update_hardwood.yml                            scripts/bb_fetch.py (backfill, detached,
 cron '47 * * * *', 55-minute job, concurrency hardwood-build       both leagues, newest season first)
 permissions: contents read (commits nothing)                     scripts/bb_derive.py, bb_pack.py
                                                                  completed seasons' inputs committed by hand
   1. checkout, Python 3.11, uv sync                              the first deploy (1 Oct 2026, 408 MB)
   2. restore data/basketball/pbp   (Actions cache, raw pbp)         pushed by hand
   3. restore data/basketball/cache (Actions cache, model caches)
   4. clone the public repo; rsync --ignore-existing its data/
      into docs/hardwood/data/  (previous payloads, manifests,
      every season's stores and derived .gz files)
   5. bb_hydrate.py: current season's store.json, recon.json,
      shots.json.gz, stints.json.gz from the live site
      (kept only when newer than the checkout's)
   6. leagues in season? (season window -14 / +7 days)
   7. bb_fetch.py --refresh-current per league     ≤ 15 min each
        ▲ site.api.espn.com  (no key; CORS *; 0.5 s spacing)
   8. bb_derive.py per league in season            ≤ 10 min
   9. build_hardwood.py --game-page-seasons 3      ≤ 30 min
        ▲ Kalshi, Polymarket (markets.json, game prices)
  10. prune games/ older than each league's three latest seasons
  11. rsync --delete docs/hardwood/ (minus plain shots.json /
      stints.json) ──► deploy key (HARDWOOD_DEPLOY_KEY)
                                         │
                                         ▼
                        ┌───────────────────────────────────────┐
                        │ pchattani/the-quant-hardwood (public; │
                        │ named by the HARDWOOD_REPO variable)  │
                        └──────────────────┬────────────────────┘
                                           ▼
                GitHub Pages: https://pchattani.github.io/the-quant-hardwood/
```

Why it is shaped this way, and where it differs from the football and F1 sites:

- **Only ESPN.** ESPN's site API needs no key, answers with `Access-Control-Allow-
  Origin: *` and answers GitHub's runners, one scoreboard day per call.
  `cdn.nba.com` and `stats.nba.com` are blocked by Akamai both from the owner's
  machine and from CI, and Basketball-Reference's terms forbid scraping. Kalshi
  has no CORS for other sites, so prices are fetched in CI at build time, never in
  the browser.
- **CI fetches its own data**, as on the F1 site: there is no local scheduled task.
- **CI commits nothing.** Unlike the F1 workflow, this one has
  `permissions: contents: read`. The current season's inputs never enter git: each
  run starts from the previous deploy (step 4) and the live site's copy of the
  current season (step 5), adds what ESPN has new, and deploys. The deployed site
  is therefore also the store of record for the current season.
- **Completed seasons are committed by hand**, once, after the season ends:
  `store.json`, `recon.json`, `shots.json.gz` and `stints.json.gz` per season
  (`.gitignore`, `scripts/bb_pack.py`).
- **Raw play-by-play never enters git.** It sits in `data/basketball/pbp/` and
  travels between CI runs in the Actions cache (key `hardwood-pbp-<run_id>`,
  restored by the prefix `hardwood-pbp-`). CI fetches only the current season, so
  only the current season's raw files are in CI; everything a past season's pages
  need from play-by-play is in the derived tables and the deployed pages.
- **Game pages are pruned.** A game page is about 50 KB, about 70 MB per NBA season;
  the public site keeps them for each league's three most recent seasons. Older
  games stay in schedules, logs and catalogues.
- **Private engine, public site**, as for football and F1: `docs/hardwood/` is
  rsynced (`--delete`) into `pchattani/the-quant-hardwood`. Without
  `HARDWOOD_REPO` and `HARDWOOD_DEPLOY_KEY` the workflow builds and exits with
  "build only, no deploy".

---

## 4. Repository map

Only the basketball parts; [the football ARCHITECTURE.md](../ARCHITECTURE.md) maps
the rest.

```
oddsmarkets/basketball/
├── CONTRACT.md                 data and model interfaces (the builders' contract)
├── PAYLOADS.md                 every payload under docs/hardwood/data/ and the front-end contract
├── canon.py                    leagues, seasons, period clock, three-point line, position pools,
│                               season types (stype), season windows, franchise moves
├── store.py                    season stores and derived tables: load / save (atomic) / merge_game /
│                               load_table (.gz aware) / raw play-by-play; HARDWOOD_DATA, HARDWOOD_PBP
├── pbp.py                      play-by-play → typed events, lineups, possessions, stints, shots,
│                               reconciliation against the box score
├── sources/
│   ├── espn.py                 Client (0.5 s, 4 retries, budget), scoreboard / summary / teams /
│   │                           roster / injuries / standings / season dates; compact_game, compact_pbp
│   └── markets.py              Kalshi and Polymarket futures, win totals and game prices → ESPN ids
├── models/
│   ├── _io.py                  data and cache roots, table helpers, penalised logistic fit, cache keys
│   ├── _games.py               finished-game rows, possessions, US calendar day (UTC − 6 h)
│   ├── config.py               SeasonFormat per league and season; arenas; GAME_DEFAULTS; ELO_DEFAULTS
│   ├── ratings.py              offence / defence / net / pace ridge fit, Kalman paths, preseason prior
│   ├── game.py                 pregame margin model, schedule context, injuries, fit_params
│   ├── season_sim.py           20,000-run season, tiebreaks, play-in, playoffs, lottery, magic numbers
│   ├── elo.py                  game Elo from the first season on disk
│   ├── backtest.py             walk-forward game and season-simulation scoring
│   ├── shots.py                xPTS logistic model, shot-making, diet, grids, calibration
│   ├── impact.py               RAPM, box impact, HPM, projections, roster impact
│   ├── winprob.py              live win probability, WPA, leverage, excitement, calibration vs ESPN
│   ├── awards.py               conditional-logit award races projected to season end
│   ├── award_winners.py        past winners (training labels), verified 1 Oct 2026
│   └── synthetic.py            synthetic stores with planted truth (tests)
└── analytics/
    ├── __init__.py             roots, rounding, percentiles, member teams, placeholder teams
    ├── context.py              SeasonContext: one league-season's inputs and models, loaded lazily
    ├── pbpx.py                 one pass over a season's raw play-by-play (summaries, WPA, game pages)
    ├── games.py                the game centre and game cards; game awards; injury inputs
    ├── season.py               season.json, history, lab, markets, calibration, index entry
    ├── teams.py                teams.json (76 metrics), team logs, lineups, on/off, shot profiles
    ├── players.py              players.json (125 metrics), career files, shot grids, similar players
    ├── lineups.py              stint tables, lineup units with shrunk net, on/off
    ├── awards.py               awards.json, career awards
    └── glossary.py             glossary.json
oddsmarkets/common/             sport-neutral helpers shared with football and F1 (de-vig, quotes, names,
                                Plackett-Luce)
scripts/
├── bb_fetch.py                 ESPN → stores and raw play-by-play; resumable; --refresh-current, --rosters
├── bb_derive.py                raw play-by-play → shots.json, stints.json, recon.json (+ .gz)
├── bb_pack.py                  gzip completed seasons' derived tables for committing
├── bb_hydrate.py               CI: the current season's inputs from the live site
├── build_hardwood.py           every payload under docs/hardwood/data/
└── setup_public_site.py        one-time public repo, deploy key, secret, variable, Pages (--site hardwood)
tests/basketball/               pytest, offline: 111 test functions in 6 files, ESPN fixtures in fixtures/
docs/
├── hardwood/                   The Quant Hardwood: index.html, assets/{base.css, hardwood.css, pages.css,
│                               pages-f.css, js/}, data/ (stores, derived inputs, payloads)
└── basketball/                 these documents (not published)
.github/workflows/update_hardwood.yml   hourly (:47) fetch, derive, build, prune, deploy
data/basketball/                git-ignored: pbp/ (raw play-by-play, gzipped) and cache/ (model caches)
logs/                           git-ignored: bb_backfill_nba.log, bb_backfill_wnba.log
```

---

## 5. Key design decisions

**One store per league and season is the single source of truth.** Everything ESPN
holds about a season's teams, players and games lives in
`docs/hardwood/data/<league>/<season>/store.json`. Fetchers write it; the build
only reads it. See [DATA_PIPELINE.md](DATA_PIPELINE.md) section 5.

**ESPN ids are the identity.** Teams, players and games are keyed by ESPN ids as
strings. ESPN keeps one id per franchise through moves and renames (Seattle and
Oklahoma City are id 25 throughout), and each season store records the names of its
own time (`canon.FRANCHISE_MOVES` documents the moves for display).

**Play-by-play is reconstructed, then frozen into derived tables.** ESPN's
play-by-play has no lineups, no possession markers and no shot distance or zone.
`pbp.py` rebuilds all three and checks each game against its box score; the
results are written per season as `shots.json`, `stints.json` and `recon.json`
(`scripts/bb_derive.py`). The models read the derived tables, not the raw files,
so a machine without raw play-by-play (CI for past seasons) still has every input.

**Walk-forward where it matters.** A finished game's pregame line on its page is
what the model said before tip-off (ratings fitted on games before the game day,
`analytics/games.model_line`). The backtest refits ratings weekly from earlier games
and fits the game-model coefficients on earlier seasons only. The win-probability
model for a season is fitted on up to three earlier seasons. The shot model and the
box-impact model are in-sample by design (they measure players against their own
league; [MODELS.md](MODELS.md) section 12).

**The models degrade instead of failing.** Every model has defaults for when history
is short (`config.GAME_DEFAULTS`, `ratings.DEFAULT_B`, `awards.DEFAULT_WEIGHTS`) and
returns `{"ok": false, "reason": ...}` rather than raising. In the build every step
is wrapped (`Build.step` in `scripts/build_hardwood.py`), and a payload that cannot
be built is written as `{"ok": false, "reason": ...}`.

**Full and light seasons, and manifests.** Each league's current season is built in
full (the season simulation, markets, award races, the players' "current" blocks);
every other season light. Each season writes a `manifest.json` of input signatures
and game-page signatures, so an unchanged light season and an unchanged game page
are skipped. A game page built with raw play-by-play is never overwritten by one
built without it.

**Payloads are JSON; the front-end is hand-written static JS.** No template engine,
no bundler. `index.html` and sixteen scripts under `assets/js/` are shipped verbatim;
Plotly 2.27 loads from cdn.plot.ly. The look is the football and F1 sites':
`assets/base.css` is copied from `docs/site/assets/style.css` on every build.

**The metric catalogue drives the front-end.** `METRICS` in
`analytics/players.py` and `analytics/teams.py` are emitted with the payloads, with
each metric's label, group, format, direction, scope ("all" or "pbp") and
description; the player and team pages, the leaders, the lab and compare render
from them, and `glossary.json` covers every key.

**Caches are keyed on inputs.** Ratings, the game parameters, Elo, xPTS, RAPM and
box impact, win probability, awards and the backtest are cached under
`data/basketball/cache/` (env `HARDWOOD_CACHE`), each keyed on the sizes and
modification times or hashes of what it reads plus a model version string. CI
carries the cache between runs (`hardwood-cache-` prefix).

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11; CI uses 3.11 |
| Environment | uv (`pyproject.toml`, `uv.lock`), shared with football and F1 |
| Numerics | numpy, scipy (sparse `lsqr`, Cholesky, L-BFGS, `norm`), pandas; no new dependencies (`CONTRACT.md`) |
| HTTP | `requests` for ESPN; the shared prediction-market client for Kalshi and Polymarket; `urllib` in `bb_hydrate.py` |
| Tests | pytest, `tests/basketball/` (offline; ESPN fixtures and synthetic stores) |
| Browser | sixteen plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly |
| CI / hosting | GitHub Actions (`update_hardwood.yml`), Actions caches for raw play-by-play and model caches, GitHub Pages from the public repo |

---

## 7. Getting started

From the repository root:

```bash
uv sync --group dev

# Basketball tests: offline
uv run --group dev pytest tests/basketball

# Build every payload from the stores on disk
uv run python scripts/build_hardwood.py                                   # current season full, the rest light
uv run python scripts/build_hardwood.py --quick --no-market --no-light    # fast local check
uv run python scripts/build_hardwood.py --leagues wnba --seasons 2026     # one league, one season in full
```

A fresh clone has every completed season's stores and derived inputs (committed 1
October 2026) but not the current seasons'. To work on the current season without
fetching,
`python scripts/bb_hydrate.py` copies it from the live site. Preview:

```bash
cd docs/hardwood
python -m http.server 8897          # then open http://localhost:8897
```

The Calibration page reads `data/basketball/cache/backtest_<league>.json`; build it
with
`uv run python -c "from oddsmarkets.basketball.models.backtest import backtest; backtest('wnba')"`
(see [RUNBOOK.md](RUNBOOK.md) section 4).

ESPN states no rate limit, but do not run a second fetcher for a league whose
backfill is running: both write the same store file.

---

## 8. Conventions

- **Under `docs/hardwood/data/`, only completed seasons' `store.json`,
  `recon.json`, `shots.json.gz` and `stints.json.gz`, and each league's
  `calibration.json`, are committed** (`.gitignore`). The plain `shots.json` and
  `stints.json` are never committed; everything else is build output.
- **Seasons are the year they end in**, leagues are lower case, ids are strings.
- **Time.** `clock_s` is seconds left in the period; `t` is elapsed game seconds
  (`canon.game_t`). NBA periods are 720 s, WNBA 600 s from 2006 (two 1,200 s halves
  1997–2005), every overtime 300 s. A game's calendar day is its UTC tip-off minus
  6 hours (`models/_games.local_day`).
- **Numbers are rounded at the payload boundary** (`PAYLOADS.md`): probabilities 4
  decimals, ratings 2, rates 3; fmt "pct" values are 0–1 fractions. NaN and infinity
  become `null` (`_clean` in `build_hardwood.py`).
- **Ratings are per 100 possessions**, possessions = FGA − OREB + TOV + 0.44 FTA
  averaged over both teams. A positive defensive impact (D) is good defence; team
  `def` is points allowed (lower is better).
- **Commits go on `main`.** CI never pushes to this repository.
- **Person pronouns.** Some code comments and docstrings say "his"; new text
  should say "they".

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **season store** | `docs/hardwood/data/<league>/<season>/store.json`: one league-season's teams, players and games (box, odds, injuries, series) from ESPN. |
| **GAME** | One game record in a store (`espn.compact_game`); fields in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 5.1. |
| **stype** | Season type: `pre`, `reg`, `playin`, `post`, `cup` (a Cup final, which does not count in the standings) or `allstar` (never stored). |
| **raw play-by-play** | `data/basketball/pbp/<league>/<season>/<id>.json.gz` (`espn.compact_pbp`). Never committed. |
| **derived tables** | `shots.json`, `stints.json` (and their `.gz`) and `recon.json` per season, from `scripts/bb_derive.py`. |
| **stint** | A stretch of one period with the same ten players on the floor. |
| **possession** | Rebuilt by `pbp.py`; ends on a made basket, defensive rebound, turnover, made last free throw or the period's end. |
| **reconciliation** | Stint minutes against box minutes (pass at 60 s), points from events against the final score. |
| **xPTS** | Expected points of a field-goal attempt from the shot model (`models/shots.py`). |
| **RAPM / box impact / HPM** | Ridge plus-minus from stints; its box-score prediction; their precision-weighted blend (Hardwood Plus-Minus), points per 100 possessions. |
| **WPA** | Win probability added, each team's players summing to that team's change in win probability. |
| **full / light season** | Built with the simulation, markets, award races and current-player blocks (the current season), or without them. |
| **manifest** | `manifest.json` per season: input signatures and game-page signatures, so unchanged work is skipped. |
| **hydrate** | CI's copy of the current season's inputs from the live site (`bb_hydrate.py`). |
| **phase** | `preseason`, `regular`, `playin`, `playoffs` or `offseason`, from the games' types and statuses (`analytics/context.season_phase`). |
| **thin market** | A field market with too few runners accounted for or an implied total outside 0.8–1.3; not published. |
| **Builders A–F** | The work packages in `CONTRACT.md` and `PAYLOADS.md`. |
