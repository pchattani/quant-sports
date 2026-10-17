# Architecture: The Quant Paddock

This is the top-level map of the Formula 1 side of the `oddsmarkets` repository
and the site it publishes, **The Quant Paddock**
(<https://pchattani.github.io/the-quant-paddock/>). Start here if you are new to
the F1 code. Four sibling documents cover the detail, and this one links to them
rather than repeating them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | Jolpica and OpenF1 extraction, the stores, telemetry, the hourly job, the backfills |
| [MODELS.md](MODELS.md) | pace, decomposition, qualifying, circuits, the race and championship simulators, Elo, the backtest, markets |
| [DASHBOARD.md](DASHBOARD.md) | the static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | operations, deploy, troubleshooting |

`HANDOFF.md` at the repository root holds the open F1 tasks alongside the
football ones.

---

## 1. What the site is

The Quant Paddock is a static Formula 1 analytics site rebuilt every hour by
GitHub Actions. It covers every World Championship season from 1950 to the
current one, with the depth of each season set by what the data sources hold:

| Tier | From | What it enables | Source |
|---|---|---|---|
| Results | 1950 | calendars, results, standings (with the historical dropped-score rules), Elo, careers, circuit history | Jolpica |
| Qualifying classification | about 1994 (Q1/Q2/Q3 times from 2006) | qualifying Elo, qualifying pace, the qualifying decomposition | Jolpica |
| Lap times and lap-end positions | 1996 | corrected race pace, the car/driver decomposition, circuit profiles, lap charts, derived passes | Jolpica |
| Pit stops | 2011 | pit loss, stop counts, strategy | Jolpica |
| Sprints | 2021 | sprint results and forecasts | Jolpica |
| Deep analytics | 2023 | stints and tyre compounds, sector times, speed traps, race control, weather, on-track overtakes, car telemetry | OpenF1 |

What the site offers (the navigation in `docs/paddock/index.html`):

- **Hub**: the next race with a countdown and the weekend schedule in the
  viewer's local time, its forecast, title odds against the market, standings,
  the championship chart and car pace at the latest round.
- **Season**: standings with the championship simulation (P(title), expected
  points, a 5th–95th percentile band, magic numbers, clinched and eliminated
  flags), a finishing-position heatmap, points progression, car pace by race,
  driver effects, the car/driver split of each team's points, Elo and the
  calendar.
- **Races**: for an upcoming race, the pre-qualifying and post-qualifying
  forecasts (and the sprint forecast on sprint weekends) from a lap-by-lap Monte
  Carlo; for a finished race, awards, results against the forecast, lap-by-lap
  positions and gaps, lap-time distributions beside corrected pace, tyre
  strategy, pit stops, race control, weather, overtakes and degradation. A
  qualifying page and a telemetry lab hang off each race.
- **Drivers** and **Teams**: catalogues of about 85 driver metrics and 40 team
  metrics per season, with field and team-mate percentiles, race logs, Elo and
  career pages.
- **Circuits**: a learned profile per circuit (pit loss, safety-car hazard,
  overtaking difficulty, typical stops, retirement rates), the winners and poles
  of every Grand Prix held there, and records.
- **Lab**: any two driver metrics against each other, one season or every season
  since 2018.
- **Compare**: two drivers or two teams side by side.
- **Markets**: the championship and next-race simulations against de-vigged
  Kalshi and Polymarket prices, and open head-to-heads.
- **Calibration**: the walk-forward backtest of the race simulator against
  simple baselines.
- **Glossary** and **Methodology**: every metric and model term, and a long
  methodology document whose constants were read from the code.

### What is on disk today

As of this writing (30 September 2026):

- 77 season stores, `docs/paddock/data/1950/store.json` to `2026/store.json`, all
  committed. The 2026 store holds results and qualifying through round 15.
- 254 OpenF1 session records committed under `docs/paddock/data/<year>/sessions/`
  (2024: 40, 2025: 123, 2026: 91), with more arriving from the backfill and not
  yet committed.
- One telemetry summary committed (`docs/paddock/data/2026/telemetry/11377.json`).
- Two one-off backfills running detached on the owner's machine: Jolpica
  (`scripts/f1_fetch.py`, log `logs/f1_backfill.log`) and OpenF1
  (`scripts/f1_openf1.py`, log `logs/f1_openf1.log`; a records pass, then a
  `--telemetry` pass, run in turn by one PowerShell command). Until they finish, seasons before 2024 have results but
  not yet the lap-level depth their tier allows.
  [DATA_PIPELINE.md](DATA_PIPELINE.md) section 9 tracks them.

---

## 2. History in brief

| Date | Milestone (from `git log`) |
|---|---|
| 30 Sep 2026, 21:57 | "F1 (The Quant Paddock), steps 1-2: data layer, models and backtest" (`eb5a88b`): the Jolpica and OpenF1 clients, the season store, `canon.py`, the lap-time, decomposition, qualifying, circuit, race, championship and Elo models, the markets source and the backtest. |
| 30 Sep 2026, 22:50 | "steps 3-5: analytics, site and pipeline" (`6efb08f`): the analytics layer, `scripts/build_paddock.py`, the site shell and its fourteen JS modules, `.github/workflows/update_paddock.yml`. |
| 30 Sep 2026, 22:56 | "Paddock workflow: cap the fetch steps so the build and deploy always run" (`a401e6a`): the 8- and 25-minute step timeouts. |

`oddsmarkets/f1/CONTRACT.md` records how the work was split while it was built:
Builder A owned the pace models (`laptime.py`, `decomposition.py`,
`qualifying.py`) and `canon.py`, Builder B the simulation (`race_sim.py`,
`championship.py`, `backtest.py`), Builder C the ratings and markets (`elo.py`,
`oddsmarkets/common/`, `sources/markets.py`). The names survive in code
comments ("A's season effects") and in the optional-import structure of
`race_sim.py`, which still runs if Builder A's modules are missing.

---

## 3. System overview

```
 GitHub Actions (pchattani/oddsmarkets, private)            Owner's machine (one-off)
 ───────────────────────────────────────────────            ─────────────────────────
 .github/workflows/update_paddock.yml                        scripts/f1_fetch.py
 cron '37 * * * *', 55-minute job, concurrency                 (Jolpica, all seasons, detached)
 group paddock-build                                         scripts/f1_openf1.py --telemetry
                                                               (OpenF1 2023-, detached)
   1. checkout, Python 3.11, uv sync                          commit stores + sessions by hand
   2. restore data/f1/telemetry from the Actions cache        when they finish
   3. f1_fetch.py --refresh-current     (Jolpica, ≤ 8 min)
        ▲ api.jolpi.ca  ~4 req/s burst, 500/hour per IP
   4. f1_openf1.py --telemetry, this year (OpenF1, ≤ 25 min)
        ▲ api.openf1.org  30 req/min, no key
   5. f1_telemetry.py  (raw telemetry → per-session summaries)
   6. build_paddock.py (payloads; Kalshi and Polymarket for markets.json)
   7. commit docs/paddock/data/*/{store.json,sessions,telemetry}
      back to main ("Paddock store refresh (CI)")
   8. rsync docs/paddock/ ──► deploy key (PADDOCK_DEPLOY_KEY)
                                         │
                                         ▼
                        ┌───────────────────────────────────────┐
                        │ pchattani/the-quant-paddock (public;  │
                        │ named by the PADDOCK_REPO variable)   │
                        └──────────────────┬────────────────────┘
                                           ▼
                  GitHub Pages: https://pchattani.github.io/the-quant-paddock/
```

Why it is shaped this way, and where it differs from the football site:

- **CI fetches its own data.** Jolpica and OpenF1 answer datacenter addresses,
  unlike Sofascore, so there is no local scheduled task. Each hourly run fetches
  the current season's new rounds and sessions, builds and deploys. The fetch
  steps are `continue-on-error: true` with their own timeouts (8 and 25 minutes,
  `update_paddock.yml`), so a slow or failing source never stops the build and
  deploy.
- **The workflow commits back.** The stores, session records and telemetry
  summaries it changed are committed to `main` of the private repo (three
  `pull --rebase`/`push` attempts), so the next run starts from them. Football
  never does this; its stores arrive from the owner's machine.
- **Raw telemetry never enters git.** It sits in `data/f1/telemetry/`
  (git-ignored) and travels between CI runs in the Actions cache (key
  `f1-telemetry-<run_id>`, restored by the prefix `f1-telemetry-`). OpenF1
  allows 30 requests a minute, so a cold cache fills over several runs.
- **The backfill runs at home, once.** The full history is about 7,000 Jolpica
  calls, roughly 14 hours at the 500-an-hour limit (docstring of
  `scripts/f1_fetch.py`), far beyond one CI run. It was started detached on the
  owner's machine; its results are committed by hand.
- **Private engine, public site**, as for football: `docs/paddock/` is rsynced
  (`--delete`) into `pchattani/the-quant-paddock`, whose root it becomes. The
  stores and session records travel with it as data.
- Without `PADDOCK_REPO` and `PADDOCK_DEPLOY_KEY` the workflow builds, commits
  and exits with "build only, no deploy".

---

## 4. Repository map

Only the F1 parts; [the football ARCHITECTURE.md](../ARCHITECTURE.md) maps the rest.

```
oddsmarkets/
├── f1/
│   ├── CONTRACT.md               data and model interfaces (the builders' contract)
│   ├── PAYLOADS.md               every payload under docs/paddock/data/ and the front-end contract
│   ├── store.py                  season stores: load / save (atomic) / mark / has; DATA = docs/paddock/data
│   ├── canon.py                  identity: car number → driverId per season and round, driver → team,
│   │                             OpenF1 session → round, session record re-keying
│   ├── telemetry.py              raw car data → per-lap summaries, corners, braking points, 10 m traces
│   ├── sources/
│   │   ├── jolpica.py            Pacer (7.3 s, 450-call budget, 429 back-off), paging, parsers
│   │   ├── openf1.py             Client (0.35 s, retries), compact session record, raw telemetry
│   │   └── markets.py            Kalshi and Polymarket F1 prices → driverId / constructorId
│   ├── models/
│   │   ├── laptime.py            corrected race pace per Grand Prix (ridge WLS, Huber IRLS)
│   │   ├── decomposition.py      car random walk + driver effect per season (race and qualifying);
│   │   │                         a four-world car/driver points split
│   │   ├── qualifying.py         pre-qualifying grid forecast
│   │   ├── circuits.py           circuit profiles learned from history, shrunk to the global profile
│   │   ├── race_sim.py           RaceInputs, the results-only estimator, the lap-by-lap Monte Carlo
│   │   ├── championship.py       remaining rounds with correlated season draws, countback, magic numbers
│   │   ├── elo.py                field, teammate and qualifying Elo from 1950
│   │   └── backtest.py           walk-forward backtest against baselines
│   └── analytics/
│       ├── __init__.py           data root (PADDOCK_DATA), cache root (PADDOCK_CACHE), percentiles, helpers
│       ├── context.py            RaceCtx: one race's lap table, passes, lap scatter, wet flag
│       ├── forecasts.py          walk-forward pre / post / sprint forecasts, cached by input hash
│       ├── drivers.py            driver catalogue (METRICS, 86 entries including "races")
│       ├── teams.py              team catalogue (METRICS, 41) and the Shapley car/driver split the site shows
│       ├── races.py              the race centre payload
│       ├── awards.py             eight per-race awards
│       ├── season.py             standings, progression, calendar, colours, index, careers, Elo, lab, markets
│       ├── circuits.py           circuit pages: profile, history, records
│       └── glossary.py           glossary.json
├── common/                       sport-neutral helpers shared with football
│   ├── markets.py                re-exports football's devig / edge / consensus; adds consensus_field
│   ├── prediction_markets.py     re-exports football's Kalshi / Polymarket primitives; series/slug fetchers
│   └── ranking.py                Plackett-Luce fit, probabilities, Gumbel sampling
scripts/
├── f1_fetch.py                   Jolpica: schedule, results, pitstops, laps; resumable; --refresh-current
├── f1_openf1.py                  OpenF1 session records, --telemetry for raw car data
├── f1_telemetry.py               raw telemetry → docs/paddock/data/<year>/telemetry/<key>.json
├── build_paddock.py              every payload under docs/paddock/data/
└── setup_public_site.py          one-time public repo, deploy key, secret, variable, Pages (--site paddock)
tests/f1/                         pytest, offline: 67 tests in 5 files (analytics, build, pace, ratings/markets, sim)
docs/
├── paddock/                      The Quant Paddock: index.html, assets/{base.css, paddock.css, pages.css, js/},
│                                 data/<year>/{store.json, sessions/, telemetry/} (committed) and build outputs (ignored)
└── f1/                           these documents (not published)
.github/workflows/update_paddock.yml   hourly (:37) fetch, build, commit, deploy
data/f1/                          git-ignored: telemetry/ (raw, gzipped) and cache/ (model caches)
logs/                             git-ignored: f1_backfill.log, f1_openf1.log
```

---

## 5. Key design decisions

**One store per season is the single source of truth.** Everything Jolpica holds
about a season lives in `docs/paddock/data/<year>/store.json`: calendar, results,
qualifying, sprints, pit stops, lap times and lap-end positions. OpenF1's richer
per-session data sits beside it as one compact record per session in
`sessions/<session_key>.json`. Fetchers only write these; the build only reads
them. See [DATA_PIPELINE.md](DATA_PIPELINE.md).

**Jolpica ids are the identity.** Drivers are keyed by Jolpica `driverId`, teams by
`constructorId`, circuits by `circuitId` everywhere downstream. OpenF1 keys by car
number, which can change hands between seasons, so `canon.py` resolves numbers
per season and per round from the store's own rows.

**Walk-forward everywhere.** Every forecast on the site, including the ones shown
on finished races, is what the model would have said at the time: race inputs,
circuit profiles and decomposition fits are all cut off strictly before the race
(`race_sim.race_inputs`, `circuits.circuit_profile(before=...)`). The backtest and
the "points v expected" metrics depend on this.

**The models degrade instead of failing.** `race_sim.py` imports the pace models
optionally; without them, or without lap data, it falls back to a results-only
estimator. Every model returns empty results with a `reason` rather than raising.
In the build, every step is wrapped (`Build.step` in `scripts/build_paddock.py`):
a failure is logged with its traceback, and a payload that cannot be built is
written as `{"ok": false, "reason": ...}` instead of being omitted.

**Full and light seasons.** The current season is built in full: walk-forward
forecasts for every round (pre-qualifying, post-qualifying and sprint), the
championship simulation, expected-points metrics. Every other season on disk is
built light: the same payloads from results, laps and the pace models, without
forecasts or a championship simulation.

**Payloads are JSON; the front-end is hand-written static JS.** No template engine,
no bundler. `index.html` and `assets/js/*.js` are committed and shipped verbatim;
Plotly 2.27 loads from cdn.plot.ly. The look is the football site's:
`assets/base.css` is copied from `docs/site/assets/style.css` on every build, and
F1-specific styles live in `paddock.css` and `pages.css`.

**The metric catalogue drives the front-end.** `METRICS` in
`oddsmarkets/f1/analytics/drivers.py` and `teams.py` are emitted with the
payloads, with each metric's label, group, format, direction, description and
scope; the driver and team pages, the lab and compare render from them.

**Shared code stays football-safe.** `oddsmarkets/common/` re-exports the football
implementations of de-vigging, quote midpoints and name matching unchanged, so F1
can use them without football's behaviour drifting, and adds sport-neutral
helpers next to them.

**Caches are keyed on inputs.** Pace fits, circuit records, Elo, forecasts and the
backtest are cached under `data/f1/cache/`, each keyed on a hash or the
modification times of what it reads, so a rebuild recomputes only what changed.
The cache is git-ignored and is not carried between CI runs (see
[RUNBOOK.md](RUNBOOK.md) section 7 and `HANDOFF.md`).

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11; CI uses 3.11 |
| Environment | uv (`pyproject.toml`, `uv.lock`), shared with football |
| Numerics | numpy, scipy (L-BFGS-B, `scipy.linalg`, `norm.ppf`) |
| HTTP | `requests` for Jolpica and OpenF1; football's prediction-market client for Kalshi and Polymarket |
| Tests | pytest, `tests/f1/` (offline, synthetic fixtures; `conftest.py`) |
| Browser | fourteen plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly; the telemetry lab calls OpenF1 directly |
| CI / hosting | GitHub Actions (`update_paddock.yml`), Actions cache for raw telemetry, GitHub Pages from the public repo |

---

## 7. Getting started

From the repository root:

```bash
uv sync --group dev

# F1 tests: 67 tests, offline
uv run --group dev pytest tests/f1

# Build every payload from the committed stores
uv run python scripts/build_paddock.py                            # current season full, every other season light
uv run python scripts/build_paddock.py --quick --no-market --no-light   # fast local check
```

Built payloads are git-ignored, so a fresh clone shows nothing until it has been
built once. Preview:

```bash
cd docs/paddock
python -m http.server 8898          # then open http://localhost:8898
```

The Calibration page needs a backtest in `data/f1/cache/backtest.json`; build it
once with
`uv run python -c "from oddsmarkets.f1.models.backtest import backtest; backtest()"`
(see [RUNBOOK.md](RUNBOOK.md) section 4).

Do **not** run the fetch scripts casually while a backfill is running: Jolpica's
limit is per IP, and a second caller pushes both into HTTP 429.

---

## 8. Conventions

- **Under `docs/paddock/data/` only `*/store.json`, `*/sessions/**` and
  `*/telemetry/**` are committed** (`.gitignore`). Everything else there is build
  output that CI regenerates hourly.
- **`.gitignore` has a bare `data/`, which matches at any depth.** The F1 entries
  un-ignore exactly the three committed kinds of file above; `data/f1/` at the
  root stays ignored.
- **Numbers are rounded at the payload boundary** (`PAYLOADS.md`): probabilities 4
  decimals, seconds 3, milliseconds integers. NaN and infinity become `null`
  (`_clean` in `build_paddock.py`).
- **Units.** Race pace is seconds per lap against the field mean; decomposition
  effects and qualifying pace are percent of lap time; both are negative for
  faster. Times in the stores are integer milliseconds.
- **Commits go on `main`.** The workflow pushes to `main`; pull before committing
  backfilled stores.
- **Person pronouns.** Some code comments and docstrings say "his"; new text
  should say "they".

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **season store** | `docs/paddock/data/<year>/store.json`: one season's calendar, results, qualifying, sprints, pit stops, laps and positions from Jolpica. |
| **session record** | `docs/paddock/data/<year>/sessions/<session_key>.json`: one OpenF1 session in compact form (laps with sectors, stints, pits, race control, weather, overtakes, positions). |
| **raw telemetry** | `data/f1/telemetry/<year>/<key>/<driver>.json.gz`: OpenF1 car data and location for one driver in one session. Never committed. |
| **telemetry summary** | `docs/paddock/data/<year>/telemetry/<key>.json`: per-lap summaries, corners, braking points and fastest-lap traces built from raw telemetry. |
| **payload** | A JSON file the build writes for the front-end (`index.json`, `season.json`, `races/<r>.json`, ...). Git-ignored. |
| **round** | A Grand Prix weekend's number in the season; stores key races by `str(round)`. |
| **pace** | Corrected race pace from the lap-time model: seconds per lap against the field mean, negative = faster. |
| **car effect / driver effect** | The decomposition's split of pace: a per-constructor random walk by round and a per-driver season constant, in percent of lap. |
| **pre / post / sprint** | The three walk-forward forecasts of a round: before qualifying, after it (with the actual grid), and the sprint. |
| **full / light season** | Built with forecasts and the championship simulation (the current season by default), or without them (every other season). |
| **neutralised lap** | A lap under a safety car, VSC or red flag, from race control (2023-) or the field-median rule. Excluded from pace fits and pass detection. |
| **opportunity** | In the circuit model, a car within 1.5 s of the car ahead and at least 0.3 s a lap faster over its last three laps; a pass is its success. |
| **magic number** | Points a driver or team still needs to be sure of the title regardless of rivals' results. |
| **thin market** | A field market with too few runners accounted for or an implied total outside 0.8–1.3; not published. |
| **Builder A / B / C** | The three work packages in `CONTRACT.md`: pace, simulation, ratings and markets. |
