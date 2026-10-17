# The Quant Ace: the website and its build

How the site at https://pchattani.github.io/the-quant-ace/ is put together: the static
front-end under `docs/ace/`, every payload under `docs/ace/data/` and what builds it
(`scripts/build_ace.py` and `oddsmarkets/tennis/analytics/`), local preview, tests and
recipes. The payload contract in full is `oddsmarkets/tennis/PAYLOADS.md`; this
document follows the code where they differ. Models are in [MODELS.md](MODELS.md),
the stores in [DATA_PIPELINE.md](DATA_PIPELINE.md).

Contents

1. Architecture
2. The front-end
3. Pages
4. The build: `scripts/build_ace.py`
5. Payload reference
6. How degradation shows on the page
7. Local preview
8. Tests
9. Recipes
10. Known gaps

---

## 1. Architecture

```
 docs/ace/data/<T>/<year>/store.json, registry.json, style.json, calibration.json   (inputs)
 oddsmarkets/tennis/models/fitted/*.json                                             (constants)
        │
        ▼
 scripts/build_ace.py ── analytics/ (TourData, players, events, matches, rankings, race, site, glossary)
        │                     └── models/ (elo, serve_return, predict, match_chain, live, tournament_sim, season_sim)
        │                     └── sources/markets.py (Kalshi, Polymarket; current year only)
        ▼
 docs/ace/data/**.json  (payloads, manifests)        docs/ace/assets/base.css (copied from docs/site)
        │
        ▼
 docs/ace/index.html + assets/js/*.js (hand-written, shipped verbatim) ── fetch('data/…') in the browser
```

No template engine, no bundler, no server: the browser fetches JSON payloads and
renders them with eighteen plain scripts and Plotly 2.27 (cdn.plot.ly). The shell
was copied from The Quant Hardwood (`window.HW` became `window.TA`, the league switch a
tour switch ATP | WTA).

---

## 2. The front-end

### 2.1 Files

| File | Role |
|---|---|
| `index.html` | the shell: header (brand, tour switch, year picker, search, sister-site links to the Footballer, Paddock and Hardwood), navigation, `<main id="app">`, the disclaimer and terms, the footer with credits, the first-visit notice (localStorage key `qa-notice-v1`), the script tags |
| `assets/base.css` | the sister sites' base stylesheet, copied from `docs/site/assets/style.css` on every build (do not edit here) |
| `assets/ace.css`, `pages.css`, `pages-f.css` | the Ace's own look; the page styles (from the Hardwood) |
| `assets/js/core.js` | `window.TA`: state, routing, cached loading, formatting, tennis helpers (surfaces, levels, rounds, scores, match cards), names and links, HTML helpers, Plotly wrappers, the header and search |
| `assets/js/charts.js` | `TA.charts`: the interactive bracket, path odds, the win-probability chart, set-score and games distributions, Elo lines, radar, heat tables, probability bars |
| `assets/js/fx.js` | `TA.fx`: shared helpers for the catalogue pages (adapted from the Hardwood's `HW.fx`) |
| `assets/js/players.js` | `TA.fk`, the catalogue kit read lazily by elo, h2h, lab, compare, calibration and docs; the catalogue and player pages |
| `hub.js`, `calendar.js`, `event.js`, `match.js`, `rankings.js`, `race.js`, `elo.js`, `h2h.js`, `lab.js`, `compare.js`, `markets.js`, `calibration.js`, `value.js`, `docs.js` | one page each (section 3); `docs.js` has the glossary and the methodology; `value.js` also draws the player page's Value card (`TA.value.card`) |

### 2.2 The `TA` namespace

`core.js` returns one object: `state` (tour, year), `route(name, fn)` (each page module
registers itself), `go`, `parseHash`, `switchTour`, `setYear`; data: `load(path)` (a
cached `fetch('data/' + path, {cache: 'no-cache'})` resolving to the JSON or `null`;
a payload written with `"ok": false` resolves as written, test with `TA.ok(d)`),
`loadAll`, `tpath('rankings.json')` → `atp/rankings.json`, `ypath('events.json')` →
`atp/2026/events.json`, `eventPath`, `matchPath`, `playerPath`; formatting (`pct`,
`signed`, `fmtDate`, `fmtScore` …); tennis helpers; `playerName`, `playerLink`,
`eventName`, `eventLink`, `matchLink`, `h2hHref`, `compareHref`, `href`; HTML helpers
(`tableHTML`, `sortable`, `pctPill`, `statTile`, `probCell`, `edgeHTML`); `plot`,
`layout`, `C` (colours: ace yellow `#d9f24f` for player 1, blue for player 2, a
colour per surface).

Before a page renders, core loads `<T>/players_index.json` (names for every pid) and
`<T>/<Y>/events.json` (event names) so names and links work synchronously. The tour is
remembered in localStorage (`qa-tour`).

### 2.3 Routes

```
#/                              hub (tour = last viewed, localStorage "qa-tour", default atp)
#/<T>                           hub
#/<T>/event/<event_id>          tournament page (event_id = "<tid>-<year>"; ?p=<pid> preselects a player)
#/<T>/match/<mid>               match centre
#/<T>/player/<pid>              player page
#/<T>/players  rankings  race  elo  calendar  lab  markets  calibration  value
#/<T>/h2h[/<a>[/<b>]]           head to head (pickers without both ids)
#/<T>/compare[/<a>[/<b>]]       compare players
#/glossary[/<key>]  #/methodology[/<section>]  #/disclaimer   (global; a tour prefix is accepted)
```

The year comes from a `?y=<YYYY>` query, else the year inside an event or match id,
else the tour's current year (`index.json` `tours[T].year`); links carry `?y=` when the
year shown is not the current one. Pages read further options from the query:
`rankings?v=official|elo|race|defend`, `lab?x=<key>&y=<key>`, `elo?p=pid,pid`,
`value?v=breakout|luck|over|surface|market|validation` (with `h=12m|6m`, `w=52w|season`, `s=hard|clay|grass`).

The navigation (`index.html`): Hub, Calendar, Rankings, Race, Elo, Players, Value, H2H,
Lab, Compare, Markets, Calibration, Glossary, Methodology. Event, match, player and H2H
pages are reached through links and the search.

### 2.4 Header, search, disclaimer

The tour switch keeps the page and swaps the tour; the year picker lists the tour's
years (`index.json` `tours[T].years`). The search box matches players
(`players_index.json`) and events. The disclaimer (`#/disclaimer`) covers: no
affiliation with the ATP, WTA, ITF, tournaments, players, ESPN, data providers,
bookmakers or markets, and no logos; data sources and licences (tennis-data.co.uk
credited for results and closing odds, ESPN, the WTA, the Match Charting Project under
CC BY-NC-SA 4.0 with attribution and a link, the derived style data shared alike);
rights holders and corrections; privacy (no cookies, no analytics; localStorage only
for the notice and the last tour; Plotly from cdn.plot.ly). The footer repeats the
credits.

---

## 3. Pages

### 3.1 Hub (`#/`, `#/<T>`, `hub.js`)

The tour and year, tournaments in play with their favourites (`events_now`), at a
glance (No. 1, Elo No. 1, Finals favourite, matches live), the match lists (live,
today, next two days, recent) with the model against the market and live win
probability, the biggest model–market gaps (matches and futures), Elo top 10 with a
surface toggle, the race to the Finals with qualification and year-end No. 1 odds.
Reads `index.json`, `<T>/markets.json`, `<T>/race.json`, `<T>/<Y>/events.json`.

### 3.2 Calendar (`#/<T>/calendar`, `calendar.js`)

Every event of the year by month (dates, level, surface, place, draw size, status,
champion, runner-up); events in play highlighted, the next marked; filters by level
(tour level, Slams and 1000s, or with Challengers / WTA 125s) and surface. Reads
`<T>/<Y>/events.json`.

### 3.3 Tournament page (`#/<T>/event/<event_id>`, `event.js`)

Level, surface, dates, draw size, status or champion; the interactive bracket
(`TA.charts.bracket`: click a player to light their path; the panel gives the
probability of reaching each round and the likeliest opponents there; on phones a
round picker); title odds against the de-vigged market with round-reached odds and
expected points; results by round; qualifying; upsets; draw difficulty; awards; past
champions. The draw's subtitle names its source: the WTA draw "with seeds and entry
types", or "rebuilt from the matches played; seeds not shown" with the note that ESPN
gives no bracket order or seeds, so later-round paths are approximate until the next
round is set. Reads `<T>/events/<event_id>.json` and `<T>/history.json`.

### 3.4 Match centre (`#/<T>/match/<mid>`, `match.js`)

The score by set (tiebreaks in superscript) and status; before the match: the model
against the market and the closing odds (Pinnacle and average, de-vigged), the
Elo-only and serve/return-only probabilities and the blend weight, set-score,
total-games and handicap distributions, the serve/return matchup (calibrated hold and
serve points won), head to head; live and after: win probability game by game with set
boundaries and the biggest swings, excitement and comeback (flagged "reconstructed"
when the game order was inferred), a statistics comparison (real WTA statistics where
they exist, otherwise the inferred numbers, labelled), awards. Reads
`<T>/matches/<mid>.json`; falls back to the match card in `index.json` or the event
payload when no match page exists (older years, qualifying).

### 3.5 Rankings, Race, Elo

- **Rankings** (`rankings.js`): official (with movement against the previous snapshot,
  the Elo rank beside it, Race position and points to defend), Elo (with surface
  ratings), Race (with the Finals cut), points to defend (a week-by-week heat grid).
  Reads `<T>/rankings.json`, `<T>/race.json`.
- **Race** (`race.js`): Finals qualification (model against Kalshi and Polymarket yes
  prices, race points, the gap to eighth), year-end No. 1 (model against the de-vigged
  market), rank distributions (ranks 1–20 and 21+), projected year-end race points
  (mean and 5th–95th percentile), the events left in the simulation. Reads
  `<T>/race.json`, `<T>/rankings.json`, `<T>/markets.json`.
- **Elo** (`elo.js`): current ratings by surface, all-time peaks (since 2000 ATP, 2007
  WTA), Elo lines for chosen players. Reads `<T>/elo.json` and career files for players
  outside its top 100.

### 3.6 Players (`#/<T>/players`, `#/<T>/player/<pid>`, `players.js`)

The **catalogue**: 138 metrics in groups (Results, Ranking, Form, Serve and Return
inferred, Serve and Return from WTA stats, Clutch, Efficiency, Style from charting),
with tour percentiles and surface-pool percentiles; WTA-only metrics are dropped on the
ATP pages (`players.tour_metrics`). The **player page**: identity and current block
(rank, points, Race, to defend, Elo and Elo rank, hold, break, age), Finals and
year-end No. 1 odds, the Elo path by surface, the serve/return path with standard
errors, seasons, the results log with pre-match model and market probabilities
(cumulative wins over expected), splits by surface, level, round and opponent band,
clutch, the charting style profile against tour medians (with the licence), head to
head, points to defend. Reads `<T>/players.json`, `<T>/players/<pid>.json`,
`<T>/players_index.json`, `<T>/elo.json`, `<T>/rankings.json`, `<T>/race.json`,
`<T>/<Y>/events.json`, `<T>/style.json`.

### 3.7 H2H, Lab, Compare

- **H2H** (`h2h.js`): the history with a surface split, the model's matchup odds on
  every surface with set-score distributions (**computed in the browser**: Elo on the
  surface-blended ratings, the chain fed with each player's hold against this
  opponent recovered from the published hold and break, the logit blend with
  `calibration.json`'s `blend_all_years`, the serve-point shift), where the rivalry ran
  against the ratings, the serve/return matchup. Its hard-coded constants are partly
  stale for the WTA ([MODELS.md](MODELS.md) section 14.2). Full history on demand from
  `<T>/<Y>/schedule.json` and `events.json`.
- **Lab** (`lab.js`): any two catalogue metrics for a year or a rolling window, an
  optional surface filter, presets, colour by country, year, surface or metric,
  quadrant medians, labelled outliers, optional shrinkage towards the on-screen
  median with a 15-match prior. Reads `<T>/lab.json`.
- **Compare** (`compare.js`): identity cards, a verdict strip (metrics won on
  percentile, the biggest gaps each way, tour or one surface's pool), a radar, the full
  table, Elo and serve/return paths overlaid, charting styles side by side, the head to
  head tally.

### 3.8 Markets (`#/<T>/markets`, `markets.js`)

Match prices (open and live tour-level matches within 3 days with a market price, the
model against the de-vigged market, sorted by the gap) and futures (tournament
winners against the draw simulation, Finals qualification and year-end No. 1 against
the season simulation, next year's Slams when quoted), with a "how to read it" panel.
Reads `<T>/markets.json`, `<T>/race.json`, `index.json` and the events with a winner
market.

### 3.9 Calibration (`#/<T>/calibration`, `calibration.js`)

Coverage, a plain-words reading written from the numbers, the score table (all
matches, Pinnacle and average subsets, by year and level), reliability diagrams with
±2 standard-error bands, set-score, straight-sets, tiebreak and total-games
calibration, live probability at set boundaries, tournament-odds calibration, the blend
weights by year and (WTA) both validations of the inferred hold and serve points won.
Reads `<T>/calibration.json`.

### 3.11 Value (`#/<T>/value`, `value.js`; added 15 October 2026)

Six views (`?v=`), all from `<T>/value.json` and `<T>/value_validation.json` (`analytics/value.py`; [MODELS.md](MODELS.md)
section 15):

- **Breakouts** (`breakout`, `h=12m|6m`): the test-years record in four tiles, the 20 likeliest breakouts (outside the top 10)
  and regressions with age, rank, the rank the model implies, the predicted rank and its 10th-90th percentile range, the
  probability, the points to defend against the points players at that level earn, and the reasons as chips (▲ towards a better
  rank); the age curve; the points calendar (points to defend against the expected points, log-log); the whole top 150, sortable.
  On phones the reasons move under the name.
- **Luck** (`luck`, `w=52w|season`): the evidence in four tiles (season-to-season correlation of luck and of win %, next-season
  win % from the luck-adjusted and raw win %), the luckiest and unluckiest eight, and every player with 10+ matches: W-L, the
  Pythagorean expected wins, close-match luck, tiebreaks and deciding sets against the chain, draw luck, free wins, the total,
  the luck-adjusted win %, (WTA) break points saved and converted over expected and the points-to-games conversion, and the
  strength of schedule; the evidence chart (correlations with CIs, luck against skill).
- **Ranking v model** (`over`): official rank against the rank the model implies (log-log scatter, labelled outliers), the 15
  most underrated and overrated inside the top 200, and the model ranking with points held, points at the implied rank and the
  ranks of the three components.
- **Surfaces** (`surface`, `s=`): the best 30 on the surface, the specialists and the weakest (surface rating minus overall).
- **Market v model** (`market`): the "market is the better forecaster" note first, the 52-week scoreboard (log-loss of the
  close and of Kalshi against the model), the players the market rates higher and lower, every player (8+ priced matches).
- **Validation** (`validation`, `h=`): pooled test and dev tiles, the year-by-year chart and table with the baselines and hit
  rates, coefficients and the drop-one table, the luck evidence, the age curve, and the last four scored snapshots' lists with
  what happened.

The player page shows a **Value card** under the headline tiles (12-month forecast and range with the probabilities, luck over
52 weeks with its parts, ranking against the model, market against the model, the forecast's drivers), linking to each view.

### 3.10 Glossary and Methodology (`docs.js`)

The glossary reads `glossary.json` (every catalogue metric, the Value section's entries in five "Value: ..." groups, and the
model terms; filterable by text and source). The methodology is static text in `METHOD_HTML`, 17
sections (the Value section is `#/methodology/m-value`), each naming its source file; it has fallen behind the code in places
([MODELS.md](MODELS.md) section 14.1).

---

## 4. The build: `scripts/build_ace.py`

```
python scripts/build_ace.py                                    # both tours: current year full, the rest light
python scripts/build_ace.py --tours atp wta --years 2026 2025
python scripts/build_ace.py --quick --no-market --no-light     # fast local check
```

| Flag | Default | Meaning |
|---|---|---|
| `--tours` | atp wta | tours to build |
| `--years` | the current year | years built in full |
| `--sims` | 20,000 | tournament simulations per live or upcoming event |
| `--season-sims` | 10,000 | season simulations |
| `--quick` | – | at most 1,000 / 500 simulations |
| `--no-market` | – | skip Kalshi and Polymarket |
| `--no-light` | – | build only the full years |
| `--no-careers` | – | skip `players/<pid>.json` |
| `--match-page-years` | 2 | match pages for the N most recent years (0 = all) |
| `--event-page-years` | 3 | event pages for the N most recent years (0 = all) |
| `--all-matches` | – | rebuild every match page in the window |
| `--no-validate` | – | skip the WTA `validate_stats` (slow when its cache is cold) |
| `--force` | – | rebuild light years even when unchanged |
| `--today` | UTC today | pretend date |
| `--data`, `--cache` | `ACE_DATA`, `ACE_CACHE` | roots |

Order of work: copy `base.css`; `glossary.json`; the Polymarket tennis events (once);
then per tour (`build_tour`):

1. `TourData(tour, today)` (memoised stores with redirects, Elo, serve/return fits,
   contexts); the Elo history.
2. Markets (current year, full builds): match prices for the current store and
   futures.
3. Predictions without distributions for every tour-level match of the match-page
   years (finished matches at their month checkpoint), then with distributions for the
   current year's live, upcoming and ±2-day matches.
4. Tournament simulations for the current year's live and upcoming tour-level events;
   the season simulation.
5. Event points, points to defend and the Race; `rankings.json`, `race.json`,
   `elo.json` (current year).
6. `history.json`; per-year entries (`players.season_entries`); then per year (full and
   light): `<year>/players.json` (and `players.json` for the current year),
   `<year>/events.json`, `<year>/schedule.json` and the event pages of the
   event-page years. A light year whose signature (the store sizes and mtimes of the
   year and the one before, the model versions, the style table size) is unchanged in
   the manifest is skipped.
7. Match pages: tour-level matches of the match-page years whose signature changed, or
   that are live or upcoming, in chunks of 400 with full predictions.
8. `players_index.json`, `lab.json`; `markets.json` and `model.json` (current year);
   `calibration.json` (the newer of the committed file and the cached backtest's page
   copy, plus the WTA's `validation_stats`, cached); `value.json` and `value_validation.json`
   (current year; the snapshot panel and walk-forward validation are cached per quarter under
   `ACE_CACHE/ace_value`, about 1-2 minutes a tour when rebuilt, a few seconds otherwise); careers
   for every player with a finished match; the index entry.

Then `index.json` (a tour whose current year was not built keeps its previous entry)
and the manifests. Every step runs inside `Build.step`: an exception is logged with its
traceback and the build continues; `write_or_fail` writes `{"ok": false, "reason"}` in
place of a payload that could not be built. `write_if_changed` skips a payload whose
hash (less `updated_at`) matches the manifest and whose file exists. The log ends with
the files written, the unchanged count, the 25 slowest steps and up to 50 errors.

---

## 5. Payload reference

All under `docs/ace/data/`. Per-tour payloads carry `"ok": true, "tour",
"updated_at"`; probabilities 4 dp, ratings 1, rates 3; fractions 0–1.

| Payload | Built by | Contents | Size and count |
|---|---|---|---|
| `index.json` | `site.index_entry` | per tour: name, year, years, live / today / recent / upcoming MATCH_CARDs, events now with favourite, Elo top 10 by surface, Race top 10 `[pid, p_finals, p_no1, race_points]`, short names | one |
| `glossary.json` | `glossary.build_glossary` | groups of metric entries and model terms | one |
| `<T>/players_index.json` | `site.players_index` | `{pid: [name, short, country, latest_rank]}` | one per tour |
| `<T>/rankings.json` | `rankings.build_rankings` | official `[rank, pid, points, move]`, previous snapshot, Elo `[rank, pid, elo, {surfaces}]` (active players), Race, points to defend | one |
| `<T>/race.json` | `race.build` | season simulation outputs, remaining events, market (`finals_qual`, `year_end_no1`, `finals_winner`, `top10`) | one |
| `<T>/elo.json` | `rankings.build_elo` | current ratings, peaks (top 50 per surface), history of the top 100 (5 years), params | one |
| `<T>/players.json`, `<T>/<Y>/players.json` | `players.build` | the catalogue: metrics, floor, surface floors, players with values, percentiles, surface values and ranks | one per tour-year |
| `<T>/players/<pid>.json` | `players.career_payload` | career: ranks, Elo path, serve/return path, seasons, results (two years), `results_all` (every match), splits, clutch, style, h2h, to defend, odds, current block | about 1,700 ATP, 1,400 WTA |
| `<T>/<Y>/events.json` | `events.events_year` | the calendar, with `page: bool` | one per tour-year |
| `<T>/<Y>/schedule.json` | `matches.schedule` | every tour-level match of the year as a light card | one per tour-year |
| `<T>/events/<event_id>.json` | `events.build_event` | event, draw (rounds, slots, matches with nodes), simulation, market, results, qualifying, upsets, draw difficulty, awards, history | tour-level events of three years |
| `<T>/matches/<mid>.json` | `matches.build_match` | the match centre (`pre` model, Elo, serve/return, market, closing, h2h; `wp` path; swings; stats; inferred; awards) | current and previous year, about 4,900 ATP and 5,000 WTA locally; 4–5 KB each |
| `<T>/history.json` | `events.history` | champions by tid | one |
| `<T>/lab.json` | `site.lab` | column-oriented player-seasons (10+ matches) and a surface block (5+) | one |
| `<T>/markets.json` | `site.markets_payload` | match rows with model, market, edge; futures; the model's side | one |
| `<T>/model.json` | `site.model_payload` | Elo, blend and serve/return constants, deciding-set rules, best-of, base serve rates | one (not read by any page) |
| `<T>/calibration.json` | `backtest.page_copy` + `validate_stats` | committed | one |
| `<T>/value.json` | `value.build_value` | breakout forecasts (top 150), luck (52 weeks, season), ranking and surfaces v the model rating, market v model | one, ~0.3 MB |
| `<T>/value_validation.json` | `value.validation_payload` | walk-forward scores by year, baselines, coefficients, drop-one, age curve, luck evidence | one, ~28 KB |
| `<T>/bio.json` | `scripts/tn_bio.py` (input, committed) | dates of birth from ESPN's core athlete API | one, ~60 KB |
| `<T>/manifest.json` | `Build.save_manifests` | payload hashes, match-page signatures, light-year signatures | one |

`PAYLOADS.md`'s "As built" section gives every field. File names replace `:` with `_`
(`players/x_alena-kovackova.json`); ids inside payloads keep the colon.

---

## 6. How degradation shows on the page

| Missing | What the page shows |
|---|---|
| a payload file (404) | `TA.load` resolves `null`; the page shows "not built yet" (`TA.notBuilt`) |
| a payload with `"ok": false` | its `reason` |
| `calibration.json` before a backtest | `{"ok": false, "reason": "the walk-forward backtest has not been run yet (scripts/tn_fit.py --backtest)"}` |
| a match page (older years, qualifying) | the match card from `index.json`, the schedule or the event payload |
| markets (thin, unmatched, or `--no-market`) | the model alone; thin fields say why |
| a WTA draw (ATP, Slams) | the reconstructed bracket and its note |
| real statistics (ATP, WTA before 2016, Slams) | the inferred numbers, labelled |
| a charting profile | the style section is omitted |

---

## 7. Local preview

```bash
python scripts/build_ace.py --quick --no-market          # or a full build
cd docs/ace
python -m http.server 8898
# open http://127.0.0.1:8898
```

The browser fetches `data/…` relative to the page, so serve `docs/ace/` itself. For
the current year without fetching, run `python scripts/tn_hydrate.py` first.

---

## 8. Tests

```bash
uv run --group dev pytest tests/tennis        # 156 test functions, 197 tests, about 3-5 minutes, offline
```

`test_data.py` (34 functions: parsers on recorded ESPN, WTA and tennis-data fixtures,
names, events, merges, draws), `test_models_b.py` (31: Elo, the exact likelihoods,
recovery of planted strengths, the mirror mode, the point layer), `test_models_c.py`
(38: the chain against brute force, live tables, the dispersion mixture, the
simulators, markets, the memory regression test), `test_analytics_d.py` (11: payload
shapes, percentiles, the glossary covering every metric, match and event pages,
careers, draws, the model payload), `test_value.py` (19: the Value section's
metrics on hand-made and synthetic data, walk-forward without look-ahead, features that never see the snapshot day or later,
the points calendar, the payloads, the glossary and the page's references), `test_build_ace.py` (4: a whole build into a
temporary data root, skipping unchanged payloads, an isolated failing step, a partial
run keeping the index entry), `test_gelo.py` (6) and `test_ace_fixes.py` (13). There is no automated JS check besides
`test_value.py`'s look at `value.js`; before committing a JS change parse it with esprima (RUNBOOK section 4) or
run `node --check docs/ace/assets/js/<file>.js` where Node is available, and load
the page locally.

---

## 9. Recipes

### Add a player metric

1. Compute it in `analytics/players.values_from` (from the season's entries and the
   serve/return record) and add a `metric(key, label, group, fmt, lower, scope, desc)`
   to `METRICS`; add it to `SHRINK` if it is a rate with a sample size, and to the
   surface keys if it makes sense per surface.
2. Add a definition to `analytics/glossary.DESC` (the test fails without one).
3. The catalogue, lab, compare and glossary pick it up from the payload; a player-page
   section that should feature it needs `players.js`.

### Add a page

Write `docs/ace/assets/js/<page>.js` registering `TA.route('<page>', render)`, add a
`<script>` tag to `index.html` (and a nav link if wanted); add the route in `core.js`
(`addRoute`) if it takes ids. Build its payload in `analytics/` and write it from
`build_tour` with `b.write_or_fail(..., tour=tour)`; document it in `PAYLOADS.md`.

### Change a model constant

Refit and commit the file in `oddsmarkets/tennis/models/fitted/` (`tn_fit.py`;
[RUNBOOK.md](RUNBOOK.md) section 4), not a constant in the code. Then rebuild with
`--force --all-matches` so light years and finished match pages pick it up, and update
the Methodology's figures (`docs.js`) and the h2h constants (`h2h.js`) by hand.

---

## 10. Known gaps

1. The Methodology and the head-to-head page carry stale WTA constants and an old ATP
   blend ([MODELS.md](MODELS.md) section 14).
2. `model.json` is built but unused; the head-to-head page should read its constants
   from it.
3. Event pages exist for three years and match pages for two; older events and matches
   are reachable only through schedules, careers and history.
4. Finished match pages are not rebuilt when the fits change (the signature does not
   include them); use `--all-matches` after a refit.
5. ATP brackets are reconstructed without seeds.
