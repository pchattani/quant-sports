# Architecture: The Quant Footballer

This is the top-level map of the `oddsmarkets` repository and the site it
publishes, **The Quant Footballer**
(<https://pchattani.github.io/the-quant-footballer/>). Start here if you are new to
the repo. Four sibling documents and one payload contract cover the detail, and this one links to them
rather than repeating them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Sofascore extraction, the stores, discovery, call budgets, the scheduled task |
| [MODELS.md](MODELS.md) | Dixon-Coles, Elo, the ensemble, the league/cup/Liga simulators, the pooled and international fits, player analytics |
| [DASHBOARD.md](DASHBOARD.md) | The static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | Operations, deploy, troubleshooting |
| [site/UNIFIED_PAYLOADS.md](site/UNIFIED_PAYLOADS.md) | The contract of the unified payloads: people, clubs, seasons |

`README.md` (repository root) is the long-form reference, `ROADMAP.md` records
what each format took and what is still open, and `HANDOFF.md` holds the tasks in
flight.

---

## 1. What the project is

The Quant Footballer is a static football analytics site rebuilt every hour. It
covers **69 competitions** in one registry:

| Group | Count | Where it is configured |
|---|---|---|
| Leagues | 12 | `LEAGUES` in `oddsmarkets/football/competitions/league/config.py`: Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, Eredivisie, Liga Portugal, Brasileirão, MLS, Saudi Pro League, Liga MX, Belgian Pro League |
| Argentine Liga Profesional | 1 | its own package, `oddsmarkets/football/competitions/liga/` (slug `liga-argentina`) |
| Continental and world cups (family `cup`) | 11 | `CUPS` in `oddsmarkets/football/competitions/cup/config.py`: Champions, Europa and Conference League; Libertadores, Sudamericana; AFC Champions League Elite; CAF Champions League; CONCACAF Champions Cup; Leagues Cup; Club World Cup; FIFA Intercontinental Cup |
| National cups (family `domestic`) | 14 | same file: FA Cup, EFL Cup, Copa del Rey, Coppa Italia, DFB-Pokal, Coupe de France, KNVB Beker, Taça de Portugal, Taça da Liga, Belgian Cup, Copa do Brasil, Copa Argentina, King's Cup, US Open Cup |
| Super cups (family `super`) | 15 | same file: UEFA Super Cup, Recopa Sudamericana, Campeones Cup and twelve domestic ones |
| National-team competitions (family `international`) | 16 | same file (`INTERNATIONALS`): World Cup, Euro, Copa América, Nations League, Euro qualifiers, World Cup qualifying in all five confederations, AFCON and its qualifiers, Asian Cup, Gold Cup, CONCACAF Nations League, friendlies |

(12 + 1 + 11 + 14 + 15 + 16 = 69; counted from `LEAGUES` and `CUPS` grouped by
`family`.)

What the site offers:

- **Scores and fixtures** across every competition on one scoreboard, with the
  model's win/draw/loss line, expected goals, most likely score and **fair
  decimal odds** (no margin) for every match still to play.
- **Model probabilities** per competition: Monte Carlo title, berth,
  relegation and bracket probabilities for leagues and club cups.
- **Club, player and match analytics at "Baseball Savant" depth**: the full
  Sofascore per-match stat set (~70 keys per player), percentile rankings
  against positional peers, radars, match logs, shot maps, xG races, momentum,
  lineups and the team-stat sheet.
- **Cross-competition comparison**: every club on one pooled strength scale with
  a hypothetical-match pricer, global leaderboards with league-adjusted rates,
  two-player and two-club comparisons, careers from the archive, every player's
  season across league, cups and national team on one table.
- **National teams** on their own scale (`#/nations`) with a pricer.
- **One record per person and per club** across every store (appearances,
  seasons by competition, current club from the fetched squads, archive
  career), and per competition a season list and a page per past season, from
  the unified build (section 3).

### Which competitions have data today

A competition has data when its store exists. As of this writing (29 September
2026) that is **23 of the 69**:

- 22 stores under `docs/site/data/<slug>/store.json`: the 12 leagues, the three
  UEFA cups, Libertadores, Sudamericana, AFC Champions League Elite, CAF
  Champions League, CONCACAF Champions Cup, the Intercontinental Cup, and the
  World Cup (seeded from the archived 2026 site by
  `scripts/seed_world_cup_store.py`, not fetched).
- The Argentine store, which lives at `docs/liga/data/liga_store.json` for
  historical reasons.

The other **46** (Leagues Cup, Club World Cup, all 14 national cups, all 15
super cups, and 15 of the 16 national-team competitions) are in the registry but
wait on **discovery**: the hourly task resolves six Sofascore ids per run into
`oddsmarkets/football/competitions/league/data/seasons.json`, and the next run's
fetch creates their stores. The picker lists them as "(soon)" until then. The
archive store (`docs/site/data/archive/store.json`), which careers and past
seasons read, does not exist yet either. Both are held up by Sofascore's 403
challenge; see `HANDOFF.md` Tasks 0 and 4.

Update, 2 October 2026: discovery has since resolved all 69 (`HANDOFF.md` Task
4). The five World Cup qualifiers and the Asian Cup had resolved to the wrong
Sofascore tournaments and were pinned to the right ones, their stores emptied
to refill. Two further stores now fill hourly: current squads
(`docs/site/data/squads/store.json`) and past results
(`docs/site/data/past/store.json`); see `HANDOFF.md` Task 27.

---

## 2. History in brief

The repository began as something else, and its name still says so.

| Date | Milestone (from `git log`) |
|---|---|
| Feb 2026 | Initial commits: a prediction-market arbitrage screener (`oddsmarkets/fetchers/`, `screener/`, `pipeline.py`). Dormant since. |
| 6 Jun 2026 | "Add World Cup 2026 quantitative trading platform": the Dixon-Coles, Elo and ensemble models and the tournament simulator under `oddsmarkets/sports/world_cup/`. |
| 24 Jun 2026 | The **World Cup 2026 site** on GitHub Pages (`docs/wc/`, `scripts/build_site_wc.py`, `.github/workflows/update_wc.yml`), updated hourly through the tournament; Sofascore live player data added 6 July. |
| 18 Aug 2026 | World Cup over; its hourly schedule disabled and the site archived. Same day: the `oddsmarkets/football/` package and the **Argentine Liga Profesional site** (`docs/liga/`, Spanish-language, `update_liga.yml`). |
| 20 Sep 2026 | The **combined site**: ten leagues plus Argentina in one shell (`docs/site/`, `build_site_all.py`). |
| 22–23 Sep 2026 | Per-league model tuning with a pooled all-league fit; Liga MX, the Belgian split; the UEFA, CONMEBOL and Intercontinental cups. The Liga-only workflow taken off its schedule. |
| 28 Sep 2026 | The **analytics layer** ("Football Analytics Hub"): scoreboard, fixtures with fair odds, club, player and match pages; AFC, CAF and CONCACAF cups. |
| 29 Sep 2026 | The **cross-competition layer**: clubs on one scale, global leaders, compare, careers. |
| 29 Sep 2026 | **Internationals, national cups and super cups**: 47 competitions join the registry. |
| 29 Sep 2026 | The site renamed **The Quant Footballer**. |
| 2 Oct 2026 | The **unified payloads** (people, clubs, seasons), current squads and past results; the World Cup qualifiers and Asian Cup re-pinned. |

Between the feature commits, the history is dominated by hourly "Sofascore store
refresh (local scheduled task)" commits, which are the data pipeline at work
(section 3).

---

## 3. System overview

```
 Owner's Windows machine (residential IP)          GitHub
 ─────────────────────────────────────────         ──────────────────────────────────────────────

 Task Scheduler: "Sofascore Refresh (all)", hourly
   scripts/refresh_sofascore_all.ps1
     1. git pull --rebase (current branch, main)
     2. fetch_sofascore_liga.py      --budget 100
     3. discover_sofascore_leagues.py --missing --limit 6
     4. fetch_sofascore_leagues.py   --all --refresh-detail --budget 150
     5. fetch_sofascore_squads.py    --budget 20
     6. fetch_sofascore_history.py   --budget 60  (up to 20 on past results)
     7. ONE commit of every changed store.json          ┌──────────────────────────────────┐
        + seasons.json, git push ──────────────────────►│ pchattani/oddsmarkets  (private) │
                                                        │  engine + stores                 │
   Sofascore API ◄── curl_cffi (Chrome fingerprint)     └──────────────┬───────────────────┘
   (blocks datacenter IPs)                                             │ cron '17 * * * *'
                                                                       ▼
                                             .github/workflows/update_site.yml
                                               uv sync
                                               hydrate: take the public site's copy of a
                                                 store if it is more complete
                                               build_site_all.py  (JSON payloads only;
                                                 calls Polymarket, Kalshi, The Odds API
                                                 if keyed; build_unified() last)
                                               rsync docs/site/ ──► deploy key (SITE_DEPLOY_KEY)
                                                                       │
                                                                       ▼
                                                        ┌──────────────────────────────────────┐
                                                        │ pchattani/the-quant-footballer       │
                                                        │ (public; target named by the         │
                                                        │  SITE_REPO Actions variable)         │
                                                        └──────────────┬───────────────────────┘
                                                                       ▼
                                          GitHub Pages: https://pchattani.github.io/the-quant-footballer/
```

Why it is shaped this way:

- **The fetch runs at home.** Sofascore blocks datacenter IPs, so GitHub Actions
  cannot reach it. The scheduled task on a residential connection is the only
  place data enters the system. It is **one** task committing **once** per run:
  two tasks would race on `pull --rebase`/`push` and one would silently lose its
  update. It commits to whatever branch is checked out.
- **CI never fetches Sofascore.** It builds from the committed stores alone, every
  time. This is the normal path, not a fallback. The only network calls in the
  build are Polymarket and Kalshi (match and title markets, no key) and The Odds
  API (bookmaker rows, only when `ODDS_API_KEY` is set), and all degrade to the
  previous payload or to nothing.
- **The unified layer is built last.** After the per-competition and site-wide
  steps, `build_unified()` in `scripts/build_site_all.py` runs
  `analytics/unified.py` (class `Unified`) over every store (competition stores,
  Argentina, the archive, squads and past results) and writes one file per
  person (`people/<pid>.json`), per club and national team (`clubs/<tid>.json`),
  their indexes, and per competition `seasons.json` and
  `s/<sid>/season.json` for past seasons. The contract is
  [site/UNIFIED_PAYLOADS.md](site/UNIFIED_PAYLOADS.md). The older
  `history/`, `careers/`, `season_index.json` and `search.json` are still built
  as front-end fallbacks.
- **Private engine, public site.** GitHub Pages is free only for public
  repositories. The engine, tuning scripts and history stay in the private
  `pchattani/oddsmarkets`; the workflow rsyncs `docs/site/` into the public repo,
  whose root it becomes. So the separation is "private-ish": the stores are
  published along with the site, because the next CI run hydrates from the
  public copy when it is more complete than the committed one (compared on match
  count, then detail coverage). They sit in the public repo as data; the page
  never loads them.
- Without `SITE_REPO`/`SITE_DEPLOY_KEY` set, the workflow builds and exits
  cleanly without deploying. The job timeout is 30 minutes.

Details: [DATA_PIPELINE.md](DATA_PIPELINE.md) for the task and the fetchers,
[RUNBOOK.md](RUNBOOK.md) for deploy setup and failure modes.

---

## 4. Repository map

```
oddsmarkets/                        the Python package (installed by uv; hatchling build)
├── football/                       everything the site runs on
│   ├── sources/
│   │   ├── sofascore.py            all Sofascore access: season events, standings, match detail,
│   │   │                           history endpoints, team squads (team_players), past seasons'
│   │   │                           results (past_season_events); CallBudget and the 403 circuit breaker
│   │   ├── prediction_markets.py   match and title prices from Polymarket and Kalshi (no key)
│   │   └── teams.py                cross-provider team-name normalisation, one registry per competition
│   ├── competitions/
│   │   ├── league/                 the 12 leagues: config.py (LeagueConfig, bands, tiebreaks, MLS
│   │   │   │                       playoffs, Liguilla, Belgian split), season_state.py, store.py,
│   │   │   │                       simulator.py (vectorised Monte Carlo)
│   │   │   └── data/               seasons.json (discovered Sofascore ids, teams; committed),
│   │   │                           model_params.json (tuner output)
│   │   ├── cup/                    the 56 cup-shaped competitions: config.py (CupConfig, CUPS,
│   │   │                           CUP_FAMILIES, six kinds), season_state.py, store.py, simulator.py
│   │   └── liga/                   the Argentine Liga Profesional: zones, fixed bracket, Tabla Anual,
│   │                               promedios; its own simulator, strength.py; markets.py re-exports core
│   ├── core/
│   │   ├── __init__.py             re-exports DixonColesModel, EloRatings, EnsembleModel, GoldenBootModel
│   │   ├── simulation.py           shared simulator primitives: score sampling, (two-legged) advance
│   │   │                           matrices, pair sampler, vectorised table ranking
│   │   └── markets.py              de-vigging and model edge against market odds
│   └── analytics/
│       ├── players.py              per-player aggregates, per-90s, percentiles, match logs; METRICS
│       ├── teams.py                team match statistics; TEAM_METRICS
│       ├── matches.py              per-match detail pages
│       ├── pool.py                 the pooled fit read back: club strength, scoring factors, bridges
│       ├── archive.py              past seasons and careers from the archive store
│       ├── unified.py              class Unified: people, clubs and seasons across every store
│       │                           (docs/site/UNIFIED_PAYLOADS.md)
│       ├── value.py                player value: line-up roles from formations, the walk-forward
│       │                           goals-added model, replacement levels (docs/MODELS.md 11b)
│       ├── value_payloads.py       data/value/: leaderboards, club strengths and needs, targets,
│       │                           fair value index
│       ├── sensitivity.py          per-club sensitivity curves for the transfer simulator
│       └── confederations.py       national team → confederation
├── sports/world_cup/               the original World Cup 2026 code, still load-bearing
│   ├── models/                     dixon_coles.py, elo.py, ensemble.py, player_goals.py, features.py:
│   │                               the models every competition uses (via football/core)
│   ├── trading/                    simulator.py (the World Cup tournament simulator), tournament_state.py,
│   │                               the_odds_api.py (still used by the hub's market tab), betfair, signals
│   ├── data/                       historical and live World Cup data loaders, match_xg.csv, player_stats.csv
│   └── matchup_analyzer.py
├── pipeline.py                     orchestrator of the dormant arb screener (fetchers → DuckDB → screener)
├── config.py                       pydantic-settings for the screener (DuckDB path, thresholds, .env)
├── fetchers/, screener/, normalizer/, db/, topics.py   the dormant arb screener
scripts/
├── fetch / discover (local only; need a residential IP)
│   ├── discover_sofascore_leagues.py   Sofascore ids, teams, last season's table → seasons.json
│   ├── fetch_sofascore_leagues.py      incremental store refresh for every league and cup
│   ├── fetch_sofascore_history.py      the archive: past seasons, careers and past results, budgeted
│   ├── fetch_sofascore_squads.py       current squads of the followed clubs → squads/store.json, budgeted
│   ├── discover_sofascore_liga.py, fetch_sofascore_liga.py   the Argentine equivalents
│   ├── fetch_crests.py                 club crests into docs/site/assets/crests/
│   ├── refresh_sofascore_all.ps1       the hourly scheduled task
│   └── refresh_sofascore_local.ps1     the retired World-Cup-only task
├── build
│   ├── build_site_all.py               the hub: every competition, hub.json, search.json, indexes,
│   │                                   and last build_unified() (people, clubs, seasons)
│   ├── build_site_global.py            the layer above (pool, global players, careers);
│   │                                   called by build_site_all.py
│   ├── build_site_liga.py              the Argentine payloads (standalone site and inside the hub)
│   └── build_site_wc.py                the archived World Cup site
├── tune / backfill / fit
│   ├── tune_league_models.py           per-league vs global vs pooled constants → model_params.json
│   ├── tune_liga_model.py, backfill_liga_history.py
│   └── build_historical_data.py, build_xg_data.py, build_player_data.py   World Cup training data
├── sample stores (offline builds and tests)
│   ├── make_league_sample_store.py, make_liga_sample_store.py
│   └── seed_world_cup_store.py         the World Cup store from the archived docs/wc data
├── legacy dashboards
│   ├── dashboard.py                    Streamlit arb-screener dashboard (no runtime: Streamlit removed)
│   ├── wc_app.py, wc_dashboard.py      Dash World Cup matchup dashboards
│   └── run_screener.py, fetch_market_odds.py, fetch_sofascore.py   screener / World Cup era
tests/                              pytest, 23 files, 356 tests (football, top level of tests/) (see section 7)
docs/
├── site/                           The Quant Footballer: index.html, assets/{style.css, js/, crests/},
│                                   data/<slug>/store.json, data/{archive,squads,past}/store.json
│                                   (committed) and build outputs (ignored); UNIFIED_PAYLOADS.md
├── liga/                           the standalone Spanish Argentine site; data/liga_store.json is
│                                   the Argentine store
├── wc/                             the archived World Cup 2026 site (payloads committed)
└── ARCHITECTURE.md, DATA_PIPELINE.md, MODELS.md, DASHBOARD.md, RUNBOOK.md
.github/workflows/
├── update_site.yml                 hourly (:17) build + deploy of docs/site/
├── update_liga.yml                 manual only; superseded by update_site.yml
└── update_wc.yml                   manual only; World Cup over
data/                               git-ignored local data: screener DuckDB and parquet exports,
                                    historical_matches.csv, raw_intl_results.csv
logs/                               git-ignored screener logs
start.bat                           launches the dormant screener; broken (references a deleted script)
pyproject.toml, uv.lock             dependencies (uv)
README.md, ROADMAP.md, HANDOFF.md
```

---

## 5. Key design decisions

**One store per competition is the single source of truth.** Everything Sofascore
told us about a competition lives in its `store.json`: matches, standings, lineups,
per-match detail. Fetchers only ever write stores; the build only ever reads them.
Any payload can be regenerated from the stores with no network, which is what
lets CI build without Sofascore and lets the public copy of a store rehydrate a
stale private one. See [DATA_PIPELINE.md](DATA_PIPELINE.md).

**Payloads are JSON only; the front-end is hand-written static JS.** There is no
template engine and no JS build step. The Python build emits JSON under
`docs/site/data/`; `index.html`, `assets/style.css` and `assets/js/{core,charts,tabs,pages,global}.js`
are committed and shipped verbatim, with Plotly loaded from its CDN. Payloads load lazily
per competition and per tab, and match pages and player logs are sharded
(`matches/<id>.json`, `players/<club>.json`) so pages load little and deploy
diffs stay small. See [DASHBOARD.md](DASHBOARD.md).

**Every competition degrades independently.** A missing or empty store lists the
competition with `ok: false` instead of dropping it; a failure mid-build is logged
and skipped; a cup before its main phase builds as fixtures only; a dead upstream
keeps the previous payload and paints a staleness banner. One bad competition
never stops the other 68.

**One call budget per run.** Sofascore answers an IP-wide 403 "challenge" after
bursts well under a thousand calls an hour. Each fetcher spends a single
`sofascore.CallBudget` (five calls per match of detail) round-robin across
competitions, paced at about a call a second, and stops at the first 403
(`sofascore.is_blocked()`). The hourly budgets are 150 detail calls for leagues and
cups, 100 for Argentina, 60 for the archive (of which up to 20 for past results),
20 for squads, and about 25 for discovery, plus the unbudgeted fixture pages.
Out-of-season competitions go dormant
and refresh their fixture lists once a day.

**One pooled fit across leagues, with cups as bridges.** Where the tuner chooses
it, a single Dixon-Coles model is fitted over every league at once, team names
prefixed by league slug, and each league reads it through `LeagueView`. Cup
matches (continental, national and super cups) join that fit with each club under
its own league's prefix, which is what puts clubs from different leagues on one
scale. Within a continental block the cups connect clubs weekly; between blocks
only the Intercontinental Cup and the Club World Cup do, so cross-block rankings
lean on the ridge prior and the site says so. See [MODELS.md](MODELS.md).

**National teams are fitted apart.** Every national-team match goes into its own
Dixon-Coles fit with an Elo beside it (`fit_international` in `build_site_all.py`),
friendlies at half weight and tournament matches marked neutral. The club pool and
the international fit never meet.

**National-team competitions are not simulated.** Their groups and knockout
ladders are shown as played, with the international fit's line on each fixture
and a banner that says so. Leagues and club cups are simulated (100,000 runs by
default, `--sims` to override).

**The models are shared and must stay World-Cup-compatible.** The Dixon-Coles,
Elo and ensemble classes in `oddsmarkets/sports/world_cup/models/` serve every
competition through `oddsmarkets/football/core`. Changes must be additive with
defaults that preserve World Cup behaviour; `tests/test_model_golden.py` enforces it.

**The metric catalogue drives the front-end.** `METRICS` (`analytics/players.py`)
and `TEAM_METRICS` (`analytics/teams.py`) are emitted with the payloads, and the
leaderboards, percentile bars, sliders and match logs render from them. Adding a
metric in Python adds it to the site with no JS change. Likewise
`competitions.json` carries each competition's tabs and family, so a new
competition needs no front-end work.

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11 (`requires-python`); CI uses 3.11 |
| Environment | [uv](https://docs.astral.sh/uv/) (`pyproject.toml`, `uv.lock`); hatchling as build backend |
| Numerics | numpy, pandas, scipy (L-BFGS-B for the Dixon-Coles fit) |
| HTTP | curl_cffi impersonating Chrome for Sofascore (resolved transitively through `datafc` in `uv.lock`; no fetcher uses datafc itself any more); requests for the prediction markets (Polymarket, Kalshi); aiohttp for the older code |
| Tests | pytest (dev dependency group) |
| Browser | five hand-written plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly for charts |
| CI / hosting | GitHub Actions (`update_site.yml`), GitHub Pages from the public repo |
| Legacy only | Dash, dash-bootstrap-components, duckdb, pydantic-settings, apscheduler, rapidfuzz, rich, betfairlightweight: the screener and the World Cup dashboards |

---

## 7. Getting started

From the repository root on Windows:

```bash
uv sync --group dev                      # creates .venv with the dev group (pytest)

# Tests: 356 football tests, about 3 minutes
.venv/Scripts/python -m pytest tests
```

`tests/test_model_golden.py::test_ensemble_golden_predictions` currently fails
by about 1e-3. The cause is date drift: the fit's time decay is measured from
today against a fixed ridge penalty, so the golden values age. Freezing the
reference date fixes it; `HANDOFF.md` Task 7 and `docs/MODELS.md` explain.

Build the site from the committed stores (no network needed except the optional
market calls):

```bash
uv run python scripts/build_site_all.py                         # everything, about 20 minutes
uv run python scripts/build_site_all.py --only premier-league   # one competition (repeatable)
uv run python scripts/build_site_all.py --sims 20000 --no-market   # faster local iteration
```

Built payloads are git-ignored, so a fresh clone shows nothing until it has been
built once. Preview locally:

```bash
cd docs/site
python -m http.server 8899               # then open http://localhost:8899
```

Do **not** run the fetch or discovery scripts casually: they spend the shared
Sofascore allowance and can trigger the challenge for the whole IP, including the
scheduled task. [RUNBOOK.md](RUNBOOK.md) says when and how.

---

## 8. Conventions

- **Under `docs/site/data/` only `store.json` files are committed.** Everything else
  there is a build output; committing it would dirty the tree after every local
  build and break the scheduled task's `pull --rebase`. `.gitignore` enforces this.
- **`.gitignore` has a bare `data/`, which matches at any depth.** A new package
  data directory needs an explicit un-ignore or its files never reach CI.
- **`.ps1` files are ASCII-only.** Windows PowerShell 5.1 reads a BOM-less file in
  the ANSI code page, so an em dash or accented letter corrupts the script.
  `refresh_sofascore_all.ps1` is clean; the retired `refresh_sofascore_local.ps1`
  still carries three non-ASCII bytes. Also: never redirect native stderr (`2>&1`)
  in those scripts.
- **Commits go on `main`.** The scheduled task commits to the checked-out branch,
  so leave the working copy on `main`.
- **Model changes are additive** with World-Cup-preserving defaults (section 5).
- Build outputs carry no timestamps in match and player shards, so an unchanged
  rebuild is byte-identical and the deploy diff is only what changed.

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **store** | A competition's committed raw data, `docs/site/data/<slug>/store.json` (Argentina: `docs/liga/data/liga_store.json`; the archive: `docs/site/data/archive/store.json`; current squads: `squads/store.json`; past results: `past/store.json`). Written only by fetchers, read only by the build. |
| **person / pid** | One Sofascore player id; `people/<pid>.json` is that person's unified record across every store. |
| **current club** | The club a person plays for now: the fetched squad, else a profile newer than the last appearance, else the latest club appearance if that club has no fetched squad (`UNIFIED_PAYLOADS.md` 2.3). |
| **last edition** | A competition whose newest season on Sofascore is finished and whose next edition is not listed yet; the payload `<slug>/seasons.json` and `competitions.json`'s `current_season` mark it `status: last_edition`, with the winner. |
| **payload** | A JSON file the build writes for the front-end (`fixtures.json`, `players_live.json`, `hub.json`, `pool.json`, ...). Git-ignored, regenerated hourly by CI. |
| **slug** | A competition's kebab-case id (`premier-league`, `wc-qual-caf`): the key in `LEAGUES`/`CUPS`/`seasons.json`, the data directory name, and the route prefix `#/<slug>/<tab>`. |
| **family** | The picker group of a cup-shaped competition, from `CUP_FAMILIES`: `cup` (continental and world), `domestic` (national cups), `super`, `international` (national teams). Leagues have no family field and group as leagues. |
| **kind** | In `competitions.json`, the page shape: `league`, `conference` (MLS), `playoff` (Liga MX), `liga` (Argentina) or `cup`. A cup also has a `cup_kind`, the bracket format: `swiss`, `groups`, `regional_swiss`, `knockout`, `fixed` or `international`. |
| **pool** | The pooled Dixon-Coles fit over every league (team names prefixed `<slug>:`) plus the cup matches; `pool.json` is its read-back. |
| **bridge** | A cup match between clubs of different leagues or continental blocks; bridges are what identify the pooled scale. Between blocks only the Intercontinental Cup and the Club World Cup provide them. |
| **scoring factor** | Per league, `exp(mean pool defence − mean league defence)`: the multiplier that puts a player's attacking rates on the pool's footing for league-adjusted leaderboards. |
| **dormant** | A competition with no fixture within 7 days either side of today whose fixtures were refreshed in the last 24 hours; its fixture list is then refreshed daily, not hourly (`--refresh-dormant` forces it). |
| **challenge** | Sofascore's IP-wide 403 response after a burst of calls, lasting hours; the fetchers stop at the first one. |
| **detail** | Per-match data beyond the score: lineups with player metadata and stat lines, the team-stat sheet, shots, momentum, incidents (five calls per match). Old- and full-format detail coexist; `--refresh-detail` upgrades old matches a few per run. |
| **followed club** | A club of one of the 12 followed leagues. National and super cups use `detail_scope="followed"`, fetching detail only for ties involving such a club. |
