# The Quant Paddock: the website and its build

This document covers the site at https://pchattani.github.io/the-quant-paddock/:
how the front-end is put together, every page and the payloads it reads, the build
that writes them, and how to add to it. `oddsmarkets/f1/PAYLOADS.md` is the
field-level contract between the Python builders and the JS; this document does
not repeat every field.

| Section | Covers |
|---|---|
| 1 | architecture |
| 2 | the front-end: files, the `PD` namespace, routes, loading, search |
| 3 | pages |
| 4 | the build: `scripts/build_paddock.py` |
| 5 | payload reference |
| 6 | how degradation shows on the page |
| 7 | local preview |
| 8 | tests and the JS syntax check |
| 9 | recipes: a metric, a page, a payload |
| 10 | known gaps |

---

## 1. Architecture

```
docs/paddock/                         rsynced verbatim to pchattani/the-quant-paddock
├── index.html                        the shell: header, nav, season picker, search, <main id="app">,
│                                     disclaimer template, footer, first-visit notice, script tags
├── .nojekyll                         stops Pages' Jekyll from hiding files
├── assets/
│   ├── base.css                      copied from docs/site/assets/style.css by every build (do not edit)
│   ├── paddock.css, pages.css        F1 styles
│   └── js/                           14 hand-written modules (section 2.1)
└── data/
    ├── <year>/store.json             committed inputs (never read by the page)
    ├── <year>/sessions/<key>.json    committed inputs (the telemetry lab reads lap start times from them)
    ├── <year>/telemetry/<key>.json   committed telemetry summaries
    └── everything else               payloads written by build_paddock.py (git-ignored)
```

The page is a static shell over JSON payloads. There is no template engine and no
JS build step; Plotly 2.27 loads from `cdn.plot.ly`. The design system is the
football site's: `base.css` is that site's stylesheet, so a change to football's
style changes the Paddock's on the next build.

---

## 2. The front-end

### 2.1 Files

Script order is fixed in `index.html`: `core.js`, `charts.js`, then the page
modules, then `docs.js`.

| File | Role | Routes |
|---|---|---|
| `core.js` | `window.PD`: state, routing, cached loading, formatters, tables, plots, colours, links, search, the season picker, the meta line | — |
| `charts.js` | `PD.charts`: `positionChart`, `gapChart`, `lapTimeViolin`, `stintChart`, `trackMap`, `telemetryOverlay`, `heatTable` | — |
| `hub.js` | the hub | `#/` |
| `season.js` | the season page | `#/season/<y>` |
| `race.js` | races list, race centre, qualifying | `#/races/<y>`, `#/race/<y>/<r>`, `#/race/<y>/<r>/quali` |
| `drivers.js` | drivers index and driver page; also defines `PD.pg`, helpers shared by the other page modules | `#/drivers`, `#/driver/<id>` |
| `teams.js` | teams index and team page | `#/teams`, `#/team/<id>` |
| `circuits.js` | circuits index and circuit page | `#/circuits`, `#/circuit/<id>` |
| `lab.js` | the driver lab | `#/lab` |
| `compare.js` | compare two drivers or two teams | `#/compare`, `#/compare/drivers/<a>/<b>`, `#/compare/teams/<a>/<b>` |
| `markets.js` | model against the markets | `#/markets` |
| `calibration.js` | the backtest | `#/calibration` |
| `telemetry.js` | the telemetry lab | `#/race/<y>/<r>/telemetry` |
| `value.js` | driver value and constructors by car pace | `#/value`, `#/value/<y>` |
| `swap.js` | the driver-swap simulator | `#/swap` (`?x=<driverId>&w=<driverId>`) |
| `fantasy.js` | fantasy projections, picks and backtest | `#/fantasy` |
| `docs.js` | glossary and methodology | `#/glossary`, `#/glossary/<key>`, `#/glossary/g:<group>`, `#/methodology`, `#/methodology/<section>` |
| `index.html` (inline) | the disclaimer route and the first-visit notice | `#/disclaimer` |

### 2.2 The `PD` namespace

`core.js` defines `window.PD`, and every page module registers itself with
`PD.route(name, renderFn)` and never edits `core.js`. A render function is called
as `fn(el, params, state)`: `el` is a fresh `<div>` inside `<main id="app">`,
detached when the viewer navigates away (async code checks `el.isConnected`);
`params` holds the named segments (`year, round, id, a, b, kind, rest, query`).
`PD.route` accepts a route name, an alias or the pattern itself.

Helpers used across modules (the list in `PAYLOADS.md` is the contract): `esc`,
`num`, `pct`, `signed`, `fmtMs` (1:23.456), `fmtGap` (+0.123), `fmtDate`,
`fmtStamp`, `card`, `tableHTML`, `sortable`, `pctPill`, `statTile`, `plot`,
`layout`, `PALETTE`, `teamColour`, `driverLink`, `teamLink`, `circuitLink`,
`raceLink`, `compoundColour`, `load`, `loadAll`, `ok`, `reason`, `cached`,
`index`, `currentSeason`.

### 2.3 Routes

From the header of `core.js`:

```
#/                              hub
#/season/<y>                    season          (#/season -> current season)
#/races/<y>                     races           (#/races  -> current season)
#/race/<y>/<r>                  race
#/race/<y>/<r>/quali            quali
#/race/<y>/<r>/telemetry        telemetry
#/driver/<id>  #/team/<id>  #/circuit/<id>
#/drivers  #/teams  #/circuits
#/lab
#/compare/drivers/<a>/<b>       compare-drivers (falls back to 'compare')
#/compare/teams/<a>/<b>         compare-teams   (falls back to 'compare')
#/compare
#/markets #/calibration #/glossary #/methodology #/disclaimer
#/value  #/value/<y>  #/swap?x=<driverId>&w=<driverId>  #/fantasy
```

Extra trailing segments land in `params.rest`; a `?a=1&b=2` suffix in
`params.query`.

### 2.4 Loading and caching

`PD.load(path)` fetches `data/<path>` with `cache: 'no-cache'`, keeps the result in
an in-memory map for the session, de-duplicates concurrent requests and resolves
to the JSON, or `null` when the file is missing or broken. Every loaded payload
also passes through `learn`, which harvests driver, team and circuit names and
colours for links and search. `PD.ok(payload)` is false for `null` and for `{"ok": false}`
payloads, and `PD.reason(payload)` returns the reason for the "not built" message.
Payloads are fetched per page: the hub reads four files, a race page one or two.

### 2.5 Header: season picker, nav, meta line

- The **season picker** lists `index.json`'s `seasons` (2026 down to 1950).
  Changing it moves the Season and Races links to that year and navigates there.
- The **nav** is static in `index.html`; `markNav` highlights the current entry.
- The **meta line** shows the page's own note and "Updated <time>" from
  `index.json`'s `updated_at`.
- A link to The Quant Footballer sits in the header and the footer.

### 2.6 Search

The search box builds its index on first use from `elo.json` (every driver in the
all-time table), `circuits.json`, the selected and current seasons'
`season.json` (races) and the names `core.js` has harvested from every payload
loaded so far (`learn`), then matches every typed word
against accent-folded labels, grouped as Drivers, Teams, Circuits and Races.

### 2.7 Disclaimer and first-visit notice

The disclaimer text is a `<template>` in `index.html` (last updated 30 September
2026), rendered by an inline `PD.route('disclaimer', ...)`. A first-visit notice
is shown until dismissed; the dismissal is remembered in `localStorage` under
`qp-notice-v1`. The site sets no cookies and runs no analytics.

---

## 3. Pages

Every section of every page degrades to a muted line when its data is missing.

### 3.1 Hub (`#/`, `hub.js`)

Reads `index.json`, `<year>/season.json`, `<year>/races/<next>.json`,
`markets.json`. A header band with the next race, a live countdown to its next
session and the weekend schedule in the viewer's local time, and the last winner;
the next race's forecast; title odds against the market; standings with points
sparklines; the championship chart; car pace at the latest round; quick links.

### 3.2 Season (`#/season/<y>`, `season.js`)

Reads `<y>/season.json`. Standings for drivers and constructors with the title
simulation (P(title), expected points, the p05–p95 band, magic numbers, clinched
and eliminated chips); a finishing-position heatmap; points progression; car pace
by race as a heat table and lines; driver race and qualifying effects; the
car/driver split; Elo; the calendar with winners, poles and the forecast
favourite. A finished season shows final standings without the simulation.

### 3.3 Races (`#/races/<y>`, `#/race/<y>/<r>`, `#/race/<y>/<r>/quali`, `race.js`)

Reads `<y>/season.json` and `<y>/races/<r>.json`.

- **Upcoming race**: the pre-qualifying forecast, the post-qualifying one once
  qualifying is in, the sprint forecast on sprint weekends; position
  distributions; P(safety car).
- **Finished race**: the eight awards, results, forecast against result
  (`expected_v_actual`), lap-by-lap positions, gaps to the leader, lap-time
  distributions beside corrected pace, tyre strategy, pit stops, race control,
  weather, overtakes, degradation by compound.
- **Qualifying**: the classification with gaps to pole and to the team-mate.

No stints, overtakes or race control before 2023; no laps before 1996.

### 3.4 Telemetry lab (`#/race/<y>/<r>/telemetry`, `telemetry.js`)

Two drivers, one lap each, on a shared distance axis: cumulative time delta,
speed, throttle, brake, gear, RPM and DRS; a track map coloured by the driver who
took less time over each 50 m segment; a corners table (minimum speed and braking
point); per-lap summaries. Fastest laps come from `<y>/telemetry/<key>.json`
(10 m spacing). Any other lap is fetched live from
`https://api.openf1.org/v1/car_data` for the lap's window (session `date_start` +
the lap's `t_start_ms` from `<y>/sessions/<key>.json`), integrated and rescaled as
`oddsmarkets/f1/telemetry.py` does. The race payload's `telemetry` flags say
whether summaries exist for the race and qualifying sessions.

### 3.5 Drivers (`#/drivers`, `#/driver/<id>`, `drivers.js`)

Reads `<y>/drivers.json`, `<y>/season.json`, `drivers/<id>.json` (career) and,
lazily, race files for the expected-points chart. The catalogue with field and
team-mate percentiles, a radar, the race log, Elo and the career.

### 3.6 Teams (`#/teams`, `#/team/<id>`, `teams.js`)

Reads `<y>/teams.json`, `<y>/season.json`, `<y>/drivers.json`, `markets.json` and
`<y>/needs.json`. The team catalogue, car pace by round with standard errors, the
car/driver split, pit crew (median and best stationary time, share under 2.5 s),
constructors' standing and title simulation, and **strengths and needs** (current
season, hidden otherwise): the graded areas against the field (A–F by percentile), the
top three strengths and weaknesses, ways to improve (driver swaps for a driver weakness,
a note for a car or operations one), the qualifying-v-race balance and the five swaps
that add the most expected constructors' points, each with a link into the swap
simulator.

### 3.6a Value (`#/value`, `value.js`) and Swap (`#/swap`, `swap.js`) (added 15 October 2026)

- **Value**: the best ten drivers by pace above team-mate and by pace above the field;
  every driver's pace above team-mate (race and qualifying, ± standard error),
  percentile, pace above the field, trend v last season, points, expected points and
  title odds; constructors ranked by the car's latest race-pace state with the season
  mean, qualifying car and the last five rounds' change. Any season from 1994. Reads
  `<y>/value.json`.
- **Swap**: pick a driver, a car and the seat he takes; the two drivers' expected points,
  title odds and final position and the two constructors' expected points and title
  odds, now and with the swap (published championship + the simulated change), the pace
  context, and a share link. Current unfinished season. Reads `<y>/swap.json` and
  `<y>/value.json`.

### 3.6b Fantasy (`#/fantasy`, `fantasy.js`) (added 16 October 2026)

Our own fantasy-style table (MODELS.md section 10b), current season. A label up top says it is not the official game
and that its prices and ownership are not used (terms). Tiles: next weekend, top projection, best value, backtest MAE
and rank correlation against the season-to-date average. **Our suggested picks**: top five, boost, value,
differentials, risers / buy low, form flatters / sell high, constructors and constructor value, each with up to three
generated reasons. **Drivers** table with a toggle: next weekend (tier, projection, a floor-ceiling bar on a shared
scale, Q3 / front-row / retirement / fastest-lap shares, form line, value) or rest of season (total, range, rounds,
per weekend, value per weekend, season so far). Charts: where the points come from (stacked expected points by item,
negatives left), projection v form line (above the diagonal = value). **Constructors** (drivers, qualifying bonus,
pit points, rest of season, value). **The schedule ahead**: expected points per remaining round (drivers or
constructors), green above the round's median. **Season so far**: actual points per weekend, last ten rounds.
**Backtest**: a generated reading, MAE / bias / rank correlation / top-5 overlap / top-pick points / interval coverage
per method for drivers and constructors (core and full scoring), by season, and the 10-weekend rolling MAE against
the season average. **Our scoring table** and what is left out and why. Reads `<y>/fantasy.json` and
`fantasy_backtest.json` (falls back to the summary inside `fantasy.json`).

### 3.7 Circuits (`#/circuits`, `#/circuit/<id>`, `circuits.js`)

Reads `circuits.json` (every circuit since 1950), season files for the rounds held
there, race files and a telemetry summary for the track map. The learned profile,
the winners and poles of every Grand Prix there, and records (most wins, poles,
team wins, the lap record from 2004, the share won from pole).

### 3.8 Lab (`#/lab`, `lab.js`)

Reads `lab.json` (one row per driver-season from 2018). Any two driver metrics
against each other for one season or all; presets; marker size and colour by any
metric, team or season; median quadrants; the ten drivers with the largest sum of
standard scores labelled; optional shrinkage toward the group median with 3 races
of prior, `(races × value + 3 × median) / (races + 3)`.

### 3.9 Compare (`#/compare/...`, `compare.js`)

Two drivers or two teams: identity cards, a verdict (which side wins more
percentile metrics, the three largest gaps each way), a radar, the full catalogue
with gap bars, shared races, Elo histories, careers. Drivers from different
seasons are each ranked against their own season's field.

### 3.10 Markets (`#/markets`, `markets.js`)

Reads `markets.json`, falling back to `season.json` and the next race file for the
model side. Drivers' and constructors' titles (price, model, edge, sources,
eliminated runners), the next race winner, open head-to-heads. When a market is
thin, its reason is shown.

### 3.11 Calibration (`#/calibration`, `calibration.js`)

Reads `calibration.json`. Log-loss and Brier for win, podium, points and DNF by
model, the winner log-loss, reliability diagrams with ±2 binomial standard errors
`sqrt(p(1 − p)/n)`, the probability each model gave the actual winner, and a
plain-words reading generated from the numbers. Shows "not built" when the payload
has `ok: false` or no `metrics`.

### 3.12 Glossary and Methodology (`docs.js`)

The glossary reads `glossary.json` and falls back to the current season's driver
and team catalogues. The methodology is static text in `docs.js` (`METHOD_HTML`,
plus `VALUE_HTML`, `FANTASY_HTML` and `SITE_HTML` on what the browser computes), split into sections by
`<section id>`. Its constants were read from the Python; keep it in step when a
model changes ([MODELS.md](MODELS.md) section 17 lists where it has drifted).

---

## 4. The build: `scripts/build_paddock.py`

```
python scripts/build_paddock.py                                    # current season full + every season light
python scripts/build_paddock.py --seasons 2026 2025 --sims 20000
python scripts/build_paddock.py --quick --no-market --no-light     # fast local check
```

| Flag | Default | Meaning |
|---|---|---|
| `--seasons Y ...` | the current season | seasons built in full |
| `--sims` | 20,000 | championship and next-race simulations |
| `--race-sims` | 3,000 | per walk-forward forecast of a finished round |
| `--no-market` | off | skip Kalshi and Polymarket |
| `--no-light` | off | build only the `--seasons` |
| `--quick` | off | at most 400 / 150 simulations, 150 / 100 for the split |
| `--data` | `PADDOCK_DATA` or `docs/paddock/data` | data root (stores in, payloads out) |
| `--cache` | `PADDOCK_CACHE` or `data/f1/cache` | model cache root |
| `--no-careers` | off | skip `drivers/<id>.json` |
| `--swap-sims` | 1,000 | championship simulations per driver swap (`--quick`: 150) |

The current season is the newest season on disk with a calendar
(`current_season`). Order of work:

1. copy `docs/site/assets/style.css` to `docs/paddock/assets/base.css`;
   write `glossary.json`;
2. Elo history over every season on disk; standings, "finished" flags and
   `circuits.build_all` for every season;
3. per season, full ones first (`build_season`): standings, team colours, the
   decomposition (`season_effects`, 1994 on), and for a full season the
   walk-forward forecasts for every round; driver records; `drivers.json`; the
   car/driver split; `teams.json`; for an unfinished full season the championship
   simulation; `season.json`; the value pages (`value_pages`: `value.json` from 1994; for
   the unfinished full season the swap table, every pair of current drivers on different
   teams through the championship simulation, cached under `<cache>/swaps/` on its inputs,
   about 3.3 minutes when it has to run, then `swap.json` and `needs.json`); for the current season
   the fantasy pages (`fantasy_pages`: the fantasy backtest brought up to date, about 5 s when cached,
   the next-weekend and rest-of-season projection, about 12 s, then `fantasy.json`); `races/<r>.json`
   for every round; `circuits.json`; the decomposition of a season is computed once and
   shared with the next season's trend;
4. site-wide: `index.json`, `elo.json`, `lab.json` (reusing `drivers.json` on disk
   for seasons from 2018 not rebuilt this run), `circuits.json`,
   `calibration.json` (from `data/f1/cache/backtest.json`), `fantasy_backtest.json` (this run's
   fantasy backtest, else the cached run, else the published copy), `markets.json`,
   `drivers/<id>.json` careers.

Every step goes through `Build.step`: a failure is logged with its traceback and
the build continues; `write_or_fail` writes `{"ok": false, "reason": "<name> could
not be built (see the build log)"}` in place of a payload that failed. Writes are
atomic (`.tmp` then rename). The log ends with the file count, megabytes, seconds
and step errors. Exit code 1 only when no season store exists.

---

## 5. Payload reference

All paths under `docs/paddock/data/`. Field lists: `oddsmarkets/f1/PAYLOADS.md`.

| Payload | Built by | Read by |
|---|---|---|
| `index.json` | `analytics/season.index` | every page (`core.js`): seasons, next and last race, current drivers and teams, colours, season meta |
| `glossary.json` | `analytics/glossary.build_glossary` | glossary, metric descriptions |
| `elo.json` | `analytics/season.elo_payload` | search, drivers, compare |
| `lab.json` | `analytics/season.lab_payload` | lab |
| `circuits.json` | `analytics/circuits.build_all` | circuits, search |
| `calibration.json` | `build_paddock.calibration` from `data/f1/cache/backtest.json` | calibration |
| `markets.json` | `analytics/season.markets_payload` | markets, hub, teams |
| `drivers/<id>.json` | `analytics/season.careers` | driver page, compare |
| `<y>/season.json` | `analytics/season.build_season` | season, hub, races list, search, teams, drivers |
| `<y>/drivers.json` | `analytics/drivers.build` | drivers, compare, teams, glossary fallback |
| `<y>/teams.json` | `analytics/teams.build` | teams, compare |
| `<y>/value.json` | `analytics/value.value_payload` | value, swap (pace context) |
| `<y>/swap.json` | `analytics/value.swap_payload` | swap |
| `<y>/needs.json` | `analytics/value.needs_payload` | team page (strengths and needs) |
| `<y>/fantasy.json` | `analytics/fantasy.fantasy_payload` | fantasy (current season) |
| `fantasy_backtest.json` | `analytics/fantasy.backtest_payload` | fantasy (backtest card) |
| `<y>/races/<r>.json` | `analytics/races.build_race` | race centre, quali, hub (next race), circuits, telemetry lab |
| `<y>/circuits.json` | `analytics/circuits.build_season` | the season's circuits |
| `<y>/telemetry/<key>.json` | `scripts/f1_telemetry.py` (not the build) | telemetry lab, circuit track maps |
| `<y>/sessions/<key>.json` | `scripts/f1_openf1.py` (not the build) | telemetry lab (lap windows) |

Rounding at the boundary: probabilities 4 decimals, seconds 3, milliseconds
integers; NaN and infinity become `null`.

---

## 6. How degradation shows on the page

| Situation | What the page shows |
|---|---|
| A payload failed to build | its `ok: false` reason in a "not built" card |
| A season before 1996 | results and qualifying; lap sections muted |
| A season before 2023 | no stints, compounds, overtakes, race control or telemetry |
| A finished season | final standings, no simulation |
| No qualifying yet | pre-qualifying forecast only |
| A thin market | "not published" with the thin-market reason |
| No telemetry summary for a session | the telemetry lab's stored traces missing; live laps still fetchable from OpenF1 |
| `calibration.json` without metrics | "not built" |

---

## 7. Local preview

```
uv run python scripts/build_paddock.py --quick --no-market
cd docs/paddock
python -m http.server 8898
# open http://127.0.0.1:8898
```

Payloads are git-ignored, so a fresh clone needs one build. The telemetry lab's
live laps need internet access to `api.openf1.org`; Plotly needs `cdn.plot.ly`.

---

## 8. Tests and the JS syntax check

`tests/f1/` (92 tests, offline, synthetic stores):

| File | Tests | Covers |
|---|---|---|
| `test_pace.py` | 14 | lap-time model and its exclusions (pit, VSC, red flag, unclosed SC windows, refuelling era), decomposition, qualifying pace and model, `canon` number reuse and re-keying |
| `test_sim.py` | 20 | race simulator, points systems, fastest-lap detection, championship end-games, countback, magic numbers, status kinds, circuit-profile shrinkage, results-only inputs |
| `test_ratings_markets.py` | 14 | Elo, Plackett-Luce, name mapping, title, race-winner and head-to-head markets, the thin-market rule, football re-exports |
| `test_analytics.py` | 17 | percentiles, the catalogue, team-mate gaps, overtake filtering, awards, strategy gains, dropped scores, standings countback, race payloads, the red-flag/chequered-flag regex |
| `test_build_paddock.py` | 2 | a quick end-to-end build into a temporary data root (value.json, swap.json, needs.json included); a failing step stays isolated |
| `test_value.py` | 4 | the seat swap of the race inputs (pace, team, grid, retirement split, sprint distance, team-mates untouched), the value page's signs, floors and ranking, grades and swap ranking, the swap table on the synthetic season and its cache |

```
uv run --group dev pytest tests/f1
```

There is no JS test suite. To check a module parses:

```
uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/paddock/assets/js/race.js',encoding='utf-8').read())"
```

---

## 9. Recipes

### Add a driver metric

1. Compute it per race in `analytics/drivers.race_records` (or from existing
   fields) and aggregate it in `season_values`.
2. Add an entry to `METRICS` in `analytics/drivers.py` with `key`, `label`,
   `group` (one of the eight `GROUPS`), `fmt`, `lower` and `scope`.
3. Add its plain-English definition to `analytics/glossary.py`.
4. Rebuild. The driver page, compare, the lab (from 2018) and the glossary pick
   it up with no JS change.

Team metrics are the same in `analytics/teams.py`.

### Add a page

1. Write `docs/paddock/assets/js/<page>.js` as an IIFE over `window.PD` that calls
   `PD.route('<name>', render)`; use a known route name, or pass a pattern to
   create one.
2. Add its `<script>` tag to `index.html` after `charts.js` and before `docs.js`,
   and a nav link if it is top-level.
3. If it needs a new payload, add a builder in `oddsmarkets/f1/analytics/`, a
   `write_or_fail` call in `build_paddock.py`, and document the shape in
   `PAYLOADS.md`.

### Change a model constant

Change it in the Python, then update the matching paragraph in `docs.js`
(`METHOD_HTML`) and [MODELS.md](MODELS.md). Forecast caches key on their inputs
and version strings (`VERSION` in `forecasts.py`, `MODEL_VERSION` in
`laptime.py`, `RECORDS_VERSION` in `circuits.py`, `VERSION` in `elo.py`); bump
the relevant one when the change does not alter the inputs, or delete
`data/f1/cache/`.

---

## 10. Known gaps

- The Calibration page depends on `data/f1/cache/backtest.json`, which only
  exists where the backtest has been run; CI does not run it or cache it.
- The Methodology's car/driver section describes the function the build does not
  use ([MODELS.md](MODELS.md) section 17).
- Telemetry summaries exist only for sessions whose raw telemetry has been
  fetched; at the time of writing one is committed.
- The site has no live timing: it changes after sessions end.
- (Fixed 15 October 2026.) `docs.js` had a line break inside the `METHOD_HTML` string literal since 1 October,
  so the browser rejected the file and the Glossary and Methodology pages did not render; the esprima check above
  catches it.
- Driver value is measured within a team (MODELS.md section 10a); driver contracts are not available, and a swap is
  a what-if.
