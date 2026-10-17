# The Quant Bullpen: the website and its build

How the site at https://pchattani.github.io/the-quant-bullpen/ is put together: the static
front-end under `docs/bullpen/`, every payload under `docs/bullpen/data/` and what builds it
(`scripts/build_bullpen.py` and `oddsmarkets/baseball/analytics/`), local preview, tests and
recipes. The payload contract in full is `oddsmarkets/baseball/PAYLOADS.md` (its "As built"
section); this document follows the code where they differ. Models are in
[MODELS.md](MODELS.md), the stores in [DATA_PIPELINE.md](DATA_PIPELINE.md).

Contents

1. Architecture
2. The front-end
3. Pages
4. The build: `scripts/build_bullpen.py`
5. Payload reference
6. How degradation shows on the page
7. Local preview
8. Tests
9. Recipes
10. Known gaps
11. The NPB level
12. Value, strengths and needs, and the trade simulator

---

## 1. Architecture

```
 docs/bullpen/data/<L>/<S>/store.json, people.json, <L>/calibration.json           (inputs)
 data/baseball/statcast/<L>/<S>.parquet, data/baseball/retro/**, data/baseball/cache/**
 oddsmarkets/baseball/models/fitted/*                                              (committed fits)
        │
        ▼
 scripts/build_bullpen.py ── analytics/ (SeasonContext, pitchagg, hitters, pitchers, fielders, teams, season,
        │                                 games, umpires, parks, leaders, awards, prospects, history, careers,
        │                                 glossary, fallbacks)
        │                     └── models/ (physics … projections, game_sim, live, season_sim, awards, backtest)
        │                     └── sources/markets.py (Kalshi, Polymarket; MLB, current season only)
        ▼
 docs/bullpen/data/**.json  (payloads, manifests)        docs/bullpen/assets/base.css (copied from docs/site)
        │
        ▼
 docs/bullpen/index.html + assets/js/*.js (hand-written, shipped verbatim) ── fetch('data/…') in the browser
```

No template engine, no bundler, no server: the browser fetches JSON payloads and renders them
with twenty-three plain scripts and Plotly 2.27 (cdn.plot.ly). The shell was copied from The
Quant Ace (`window.TA` became `window.BP`, the tour switch the level switch MLB | AAA).

---

## 2. The front-end

### 2.1 Files

| File | Role |
|---|---|
| `index.html` | the shell: header (brand "The Quant Bullpen", level switch, season picker, search, sister-site links), navigation, `<main id="app">`, the disclaimer and terms, the footer with credits and the Retrosheet notice, the first-visit notice (localStorage key `qb-notice-v1`), the script tags |
| `assets/base.css` | the sister sites' base stylesheet, copied from `docs/site/assets/style.css` on every build (do not edit here) |
| `assets/bullpen.css`, `pages.css`, `pages-g.css` | the Bullpen's own look; the page styles |
| `assets/js/core.js` | `window.BP`: state (level, season), routing, cached loading, formatting, baseball helpers, names and links, HTML helpers, Plotly wrappers, the header and search |
| `assets/js/charts.js` | `BP.charts`: the strike zone (catcher's view, plate 17 in, the batters' zone), the spray chart on park dimensions, the movement plot (IVB × arm-side HB, arm-angle line), zone heat maps, win-probability charts, percentile sliders, the bracket |
| `assets/js/fx.js` | `BP.fx`: helpers for the catalogue pages (adapted from the Ace's `TA.fx`) |
| `assets/js/hitters.js` | `BP.gk`, the catalogue kit read lazily by the other catalogue pages; the hitters catalogue |
| `hub.js`, `games.js`, `game.js`, `standings.js`, `postseason.js`, `markets.js`, `pitchers.js`, `player.js`, `teams.js`, `leaders.js`, `umpires.js`, `parks.js`, `prospects.js`, `history.js`, `awards.js`, `lab.js`, `compare.js`, `calibration.js`, `docs.js` | one page each (section 3); `docs.js` has the glossary and the methodology |
| `value.js` (15 October 2026) | the Value page, the trade simulator and the team pages' "Strengths and needs" (`BP.valueTeam`), every level (section 12); styles in `assets/value.css` |

### 2.2 The `BP` namespace

`core.js` returns one object: `state` (level, season), `route(name, fn)`, `go`, `parseHash`;
data: `load(path)` (a cached `fetch('data/' + path, {cache: 'no-cache'})` resolving to the JSON
or `null`; a payload written with `"ok": false` resolves as written), level- and season-aware
paths; formatting; baseball helpers (counts, innings, pitch types and colours, game status,
lines); names and links (`playerName`, `playerLink`, `playerHref(pid, opts)`,
`teamLink(tid, opts)`, `gameHref(gpk, L, S)`: helpers take the level last and optionally);
HTML helpers (`tableHTML`, `sortable`, `pctPill`, `statTile`, `probCell`, `edgeHTML`); `plot`,
`layout`, `C` (colours: clay `#d9804e` for the home side, blue for the away side).

Before a page renders, core loads `players_index.json` (`{pid: [name, team, pos, bats, throws,
[levels]]}`) so names and links work synchronously. Team names come from `index.json` `teams`
(and any payload carrying a `teams` dict), with a built-in MLB table as the fallback.

### 2.3 Routes

```
#/  #/<L>                          hub (level = last viewed, default mlb)
#/<L>/games[/<date>]               games of a day (YYYY-MM-DD)
#/<L>/game/<gpk>                   game centre
#/<L>/standings                    standings
#/<L>/hitters  #/<L>/pitchers      catalogues
#/<L>/hitter/<pid>  #/<L>/pitcher/<pid>  #/player/<pid>   player pages (two-way players get both tabs)
#/<L>/teams  #/<L>/team/<tid>      teams
#/<L>/leaders  #/<L>/lab           leaderboards, lab
#/<L>/value  #/<L>/trade           player value and the best at each position; the trade simulator (MLB, NPB)
#/postseason  #/markets  #/umpires  #/umpire/<id>  #/parks  #/park/<vid>  #/prospects
#/history  #/awards  #/compare[/<a>[/<b>]]  #/calibration  #/glossary[/<key>]  #/methodology  #/disclaimer
```

L is `mlb` or `aaa` and may prefix any route. The season comes from a `?s=<YYYY>` query (any
page), else the level's current season (`index.json` `levels[L].season`, else `season`); links
carry `?s=` when the season shown is not the current one. Pages read further options from the
query: `leaders?k=hitter|pitcher|pitch&m=&pt=`, `lab?kind=&x=&y=`; compare takes MLBAM ids or
`t<tid>` for teams.

The navigation (`index.html`): Hub, Games, Standings, Postseason, Hitters, Pitchers, Teams,
Leaders, Umpires, Parks, Prospects, History, Awards, Lab, Compare, Value, Trade, Markets, Calibration,
Glossary, Methodology.

### 2.4 Header, search, disclaimer

The level switch keeps the page and swaps the level; the season picker lists the level's
seasons. The search box matches players (`players_index.json`) and teams. The disclaimer
(`#/disclaimer`) covers: no affiliation with MLB, MLBAM, any club, player, ESPN, sportsbooks
or markets, and no logos; the Retrosheet notice verbatim; the Chadwick register's ODC-BY
attribution; Lahman CC BY-SA; MLBAM data shown for non-commercial, informational use; rights
holders and corrections; privacy (no cookies, no analytics; localStorage only for the notice
and the last level; Plotly from cdn.plot.ly); 18+ where gambling is discussed.

---

## 3. Pages

### 3.1 Hub (`#/`, `#/<L>`, `hub.js`)

A band with the level, season, phase (and postseason round) and at a glance (World Series
favourite, games today, live games, the biggest gap); the postseason bracket with series odds
against the market once it is set; games live, today, in the next days and recent, each with
the model against the market against the DraftKings line and live win probability; the
biggest gaps (games, series, futures); leaders; World Series odds; explore links. Reads
`index.json`, `<L>/<S>/markets.json` and `glossary.json`.

### 3.2 Games and the game centre (`games.js`, `game.js`)

**Games**: a date picker and the day's games as cards or a table (model · market · line ·
result · whether the favourite won), with a one-line summary of the day. Reads
`<L>/<S>/schedule.json` (and `index.json` for today). **Game centre**: header (teams, score,
status, series, park, umpire; live state with the count, bases, outs and batter; win
probability; the linescore); tabs **Preview** (model v market v DraftKings for win, run line,
total and first five, the total-runs distribution, starters, lineups with matchup projections,
weather, park and umpire), **Game** (win probability, ours against ESPN's, with the top WPA
plays; the spray chart with xwOBA+ against Savant's xwOBA and the batted-ball table),
**Pitches** (pitch-by-pitch with filters and the strike zone coloured by type, result,
Stuff+ or xwOBA+), **Box score** (with expected stats), **Umpire** (scorecard: missed calls,
run cost, favoured team; ABS challenges), **Arsenals** (each pitcher's pitches that day
against his season norm). Reads `<L>/<S>/games/<gpk>.json`, falling back to the card in
`schedule.json` or `index.json`.

### 3.3 Standings and postseason (`standings.js`, `postseason.js`)

**Standings**: divisions (W-L, GB, runs, run differential, Pythagorean and rating-expected
records, playoff, division, bye and World Series odds, magic numbers), the wild-card race with
the cut line, ratings (offence, run prevention, pitching in runs per game; luck). Reads
`<L>/<S>/season.json`, or computes a table from `schedule.json` when it is not built.
**Postseason**: the bracket with series wins and odds against the market, every series with
its games and next game, path odds against the World Series market with what the next game
is worth. Reads `season.json` `postseason` (else `index.json`), `markets.json`,
`schedule.json`.

### 3.4 Catalogues and player pages (`hitters.js`, `pitchers.js`, `player.js`)

The **hitters** (175 metrics) and **pitchers** (150 metrics, a starter / reliever filter)
catalogues with percentiles against the reference pool (`pct`) and the position group or role
(`pct_role`). The **player page**: hitters get Savant-style sliders over the catalogue, tiles
(xwOBA+ against Savant's xwOBA, Bullpen WAR, decision value, adjusted bat speed), the spray
chart, zone heat maps by pitch type and count, the swing-decision map, bat speed and swing
path, rolling xwOBA+ against wOBA, splits, the career (Statcast and Retrosheet-era seasons),
projections with ranges, similar players; pitchers the arsenal table, the movement plot, the
release point and extension consistency, tunneling pairs, usage by count and hand, velocity and
spin trends with fatigue signals, zone heat maps, times through the order, the career and
projections. Reads `players/<pid>.json`, `<L>/<S>/hitters.json` / `pitchers.json`,
`<L>/<S>/parks.json`.

### 3.5 Teams, leaders, umpires, parks, prospects, history, awards

- **Teams** (`teams.js`): the catalogue (78 metrics) and the team page: record and ratings,
  playoff odds, percentile sliders, roster value, the projected lineup and rotation, bullpen
  availability (recent pitch counts and rest), defensive alignment tendencies, the home park's
  factors, the schedule log against the game model.
- **Leaders** (`leaders.js`): any catalogue metric, or any per-pitch arsenal metric for one
  pitch type, with a sample floor, qualified only, a team filter and the league's distribution.
- **Umpires** (`umpires.js`): accuracy, expected accuracy, consistency, zone size, run impact,
  favoured side, per-game scorecards, ABS challenges.
- **Parks** (`parks.js`): contact factors by hand and outcome, runs, K and BB factors,
  dimensions and walls, weather effects on carry and home runs (100 = neutral).
- **Prospects** (`prospects.js`, Triple-A): the Triple-A line, MLB-equivalent rates and the
  call-up preview.
- **History** (`history.js`): all-time leaderboards, era-adjusted (wRC+, RA9−), with the
  Retrosheet notice; the league environment by season.
- **Awards** (`awards.js`): MVP, Cy Young and Rookie of the Year per league, model against the
  markets, with the features the model weighs.

### 3.6 Lab and Compare (`lab.js`, `compare.js`)

**Lab**: any two metrics for hitters or pitchers, presets (stuff against results, bat speed
against xwOBA+, decision value against chase rate, VAA against whiff rate, xwOBA+ against
Savant's xwOBA, framing against pop time), colour by team, position or metric, quadrants,
labelled corners, optional shrinkage towards the on-screen median by each metric's k.
**Compare**: two hitters, two pitchers or two teams side by side.

### 3.7 Markets (`#/markets`, `markets.js`)

Game prices (model against the de-vigged Kalshi / Polymarket price and the DraftKings line,
largest gap first), series prices, futures (World Series, pennants, awards) with fair odds,
and a "how to read it" panel. Reads `mlb/<S>/markets.json`, `season.json`, `awards.json` and
the cards in `index.json`.

### 3.8 Calibration (`#/calibration`, `calibration.js`)

The walk-forward game backtest against ESPN's closing lines (log-loss, Brier and reliability
for the game model, team ratings, starter and record and the de-vigged closing moneyline;
totals and run lines against the market's own prices; postseason series), then the model
checks: xwOBA+ against Savant's xwOBA, Stuff+ validity, projections against a Marcel-style
baseline, framing and fielding against Savant. "What it shows" is written from the numbers.
Reads `<L>/calibration.json`.

### 3.9 Glossary and Methodology (`docs.js`)

The glossary reads `glossary.json` (every catalogue metric of hitters, pitchers, fielders,
teams and umpires with its stabilisation point and unit, the model entries, the rules and the
notices). The methodology is static text in `METHOD_HTML`, 27 sections, each naming its
source files; [MODELS.md](MODELS.md) section 22 lists where it and the code disagreed
(resolved on 1 October 2026).

---

## 4. The build: `scripts/build_bullpen.py`

```
python scripts/build_bullpen.py                                    # every level: current full, the rest light
python scripts/build_bullpen.py --levels mlb --seasons 2026 2025
python scripts/build_bullpen.py --quick --no-market --no-light      # fast local check
```

| Flag | Default | Meaning |
|---|---|---|
| `--levels` | mlb aaa | levels to build |
| `--seasons` | each level's current season | seasons built in full |
| `--sims` | 20,000 | season simulations |
| `--game-sims` | 20,000 | simulations per game price |
| `--days-ahead` | 3 | price games up to N days ahead |
| `--quick` | – | at most 1,000 season and 2,000 game simulations |
| `--no-market` | – | skip Kalshi and Polymarket |
| `--no-light` | – | build only the full seasons |
| `--no-careers` | – | skip `players/<pid>.json` |
| `--no-history` | – | skip `history.json` and the Retrosheet-era career rows |
| `--no-models` | – | catalogues from the pitch tables only (no builder B/C/D models) |
| `--light-awards` | – | also build `awards.json` for light seasons |
| `--all-games` | – | rebuild every game page of the page seasons |
| `--game-page-seasons` | 2 | game pages for each level's N most recent seasons |
| `--force` | – | rebuild light seasons even when unchanged |
| `--today` | UTC today | pretend date |
| `--data`, `--raw`, `--cache` | `BULLPEN_DATA`, `BULLPEN_RAW`, `BULLPEN_CACHE` | roots |

Order of work: install the CI fallbacks (`analytics/fallbacks.install`); copy `base.css`;
`glossary.json`; then per level, MLB first (`build_level`), every season on disk newest first
(`build_season`):

1. Skip a light season whose manifest signature (store content hash, pitch-table size and
   mtime, model versions) is unchanged (and which is not a page season), or a past season
   whose pitch table is not on this machine but whose catalogues exist ("payloads kept").
2. `SeasonContext(level, season, full, ...)`; `hitters.json`, `pitchers.json`, `fielders.json`.
3. The season simulation (MLB, full); markets (MLB, full, current).
4. Prices for the current season's games not yet final from yesterday to `--days-ahead`
   (`price_window`: the game simulation's summary, the model block, the market row); frozen
   prices from the manifest; walk-forward backtest prices for games before the first build.
5. `schedule.json`, `teams.json`, `season.json`, `umpires.json`, `parks.json`, `leaders.json`,
   `lab.json`, `awards.json` (MLB; full seasons or `--light-awards`), `prospects.json`
   (Triple-A, with MLB's projections and catalogues).
6. Game pages for the page seasons (unless the season's pitch table is absent and its pages
   exist): games whose signature (status, score, lines, lineups, pitches in the table, model
   versions) changed, every missing page, and every not-final game of the current season in
   the pricing window; built in batches of 150 games whose pitches are read together.
7. `markets.json` (MLB, full, current), the players' current blocks, the manifest.

Then per level the calibration merges: the xwOBA+ predictive test for the last three pitch
seasons (MLB, needs two; cached on the Parquet files' signatures) into `checks.xwoba`, the
fielding and framing validations of the seasons built into `checks.oaa` and `checks.framing`,
and a placeholder `{"ok": false}` when no `calibration.json` exists. Site-wide: the MLB
`history.json` from the Retrosheet tables (kept as it is when they are not on the machine), the
career files with their Retrosheet-era rows and `players_index.json`, and `index.json` (a level
whose current season was not built keeps its previous entry). Every step runs inside
`Build.step`; `write_or_fail` writes `{"ok": false, "reason"}` in place of a payload that
could not be built. The log ends with the files written, the 25 slowest steps and up to 60
errors.

---

## 5. Payload reference

All under `docs/bullpen/data/`. Payloads carry `"ok": true`, `level`, `season` and
`updated_at`; catalogues also `phase`, `team_games` and `model_errors`. Probabilities 4 dp,
rates 3, "plus" scores integers, fractions 0–1. Sizes from the local build of 1 October 2026
(MLB 2026).

| Payload | Built by | Contents | Size and count |
|---|---|---|---|
| `index.json` | `build_bullpen.index_payload` | season, phase, today / recent / upcoming cards, the postseason, leaders, teams, `levels` | one, 20 KB |
| `glossary.json` | `glossary.build` | metric groups by kind with units and stabilisation points, model entries, notices | one, 95 KB |
| `people.json` | `chadwick.build` (fetch) | the crosswalk | one, committed, 3.4 MB |
| `players_index.json` | `careers.write_careers` | `{pid: [name, team, pos, bats, throws, [levels]]}` | one, 174 KB |
| `players/<pid>.json` | `careers.write_careers` | career (all levels), Retrosheet history, current block, similar players | 3,282 files, 59 MB |
| `<L>/history.json` | `history.build` | all-time boards 1908 on, era table, the Retrosheet notice | MLB, 75 KB |
| `<L>/calibration.json` | backtest + the build's check merges | `games`, `checks` | MLB, committed, 15 KB |
| `<L>/<S>/hitters.json`, `pitchers.json` | `hitters.build`, `pitchers.build` | the catalogues (175 / 150 metrics), arsenals, reference pool, floors | 4.7 MB / 6.9 MB |
| `<L>/<S>/fielders.json` | `fielders.build` | fielding and framing with Savant comparisons, validation | 0.4 MB |
| `<L>/<S>/teams.json` | `teams.build` | 78 metrics, game log, roster, bullpen, defence, park | 0.6 MB |
| `<L>/<S>/season.json` | `season.build` | standings with simulation odds, ratings, the postseason, next games | 23 KB (postseason) |
| `<L>/<S>/schedule.json` | `build_bullpen.schedule` | every GAME_CARD | 1.1 MB |
| `<L>/<S>/games/<gpk>.json` | `games.build_page` | the game centre (card, teams, weather, venue with factors, umpire, pregame, lineups, pitches, wp, umpire scorecard, ABS, box, arsenal, WPA leaders) | two most recent seasons (CI prunes the rest); about 70 KB, 2,400–2,500 a season |
| `<L>/<S>/umpires.json`, `parks.json` | `umpires.build`, `parks.build` | umpire tables and scorecards; park factors and effects | 243 KB, 22 KB |
| `<L>/<S>/leaders.json`, `lab.json` | `leaders.build`, `leaders.lab` | top 25 per metric, best pitches; column-oriented rows (50+ PA / BF) | 0.37 MB, 1.0 MB |
| `<L>/<S>/awards.json` | `awards.build` | the six races with model, market and features | MLB, 25 KB |
| `<L>/<S>/prospects.json` | `prospects.build` | Triple-A players with translations and projections | AAA only |
| `<L>/<S>/markets.json` | `season.markets_payload` | champion, pennants, awards, advance, series, games | MLB, current season, 39 KB |
| `<L>/<S>/manifest.json` | `build_season` | signature, frozen prices, page signatures, model errors, timings | one per season, 70 KB |

`PAYLOADS.md`'s "As built" section gives every field (note there: HB is arm-side positive for
both hands; `call` is the pitch result and `desc` the play text on a PA's last pitch; ESPN's
WP x is the 0–1 fraction of its play list, ours a PA index).

---

## 6. How degradation shows on the page

| Missing | What the page shows |
|---|---|
| a payload file (404) | `BP.load` resolves `null`; the page says it is not built yet |
| a payload with `"ok": false` | its `reason` |
| a model (`model_errors` in a catalogue) | the columns that need it are empty and the page says which model was not available |
| `calibration.json` before a backtest | `{"ok": false, "reason": "no backtest yet: run builder D's backtest (models/backtest.py) to write it"}` |
| `season.json` | standings computed from `schedule.json` |
| a game page | the card from `schedule.json` or `index.json` |
| a game's pitches (not on the machine) | an existing page keeps its pitch-level blocks; the frozen pre-game price is carried into the live and final page |
| markets (thin, unmatched, or `--no-market`) | the model alone; the de-vigged DraftKings line from the store as the market |
| bat tracking (seasons before 2023–24) | the section is omitted |

---

## 7. Local preview

```bash
python scripts/build_bullpen.py --quick --no-market          # or a full build
cd docs/bullpen
python -m http.server 8897
# open http://127.0.0.1:8897
```

The browser fetches `data/…` relative to the page, so serve `docs/bullpen/` itself. For the
current season without fetching, run `python scripts/mlb_hydrate.py` first (the pitch-level
blocks need the pitch table).

---

## 8. Tests

```bash
uv run --group dev pytest tests/baseball      # 247 tests, about 3 minutes, offline (15 October 2026)
```

`test_data.py` (29 functions: Savant's cap re-splitting, failed and HTML answers, the Triple-A
search, typing and Parquet round trips, duplicate pitches from overlapping splits, Stats API
GAME records and feeds, merges, canon, the Retrosheet parser against synthetic and real games
reconciled with the game logs, the notice, the crosswalk, ESPN mapping, doubleheaders, 2019 and
2026 lines and run-line signs, the store's ownership merge), `test_models_b.py` (13: physics
against planted movement and numerical integration, the axis convention and seam-shifted wake,
release consistency, Stuff+, Location+, Pitching+, swing, tunneling, bat tracking, fatigue,
booster round trips, missing columns), `test_models_c.py` (20: RE24 against simulator truth and
a hand-computed matrix, linear weights, win expectancy, xwOBA+ (park and spray, calibration,
the predictive test, classes), catch probability, framing, umpires, ABS, parks, WAR, steals,
Retrosheet history, stabilisation), `test_models_d.py` (18: series closed form and simulation,
postseason and regular-season simulations, tiebreaks, extra innings, the PA simulation against
planted run environments and independent games, live Markov against simulation, projections,
aging and translations, the backtest, awards, markets from fixtures), `test_analytics_e.py` (9:
percentiles, catalogues, isolated model failures, game pages, the history notice, the
glossary), `test_build_bullpen.py` (6: a whole build, a failing step, partial runs keeping the
index entry, a past season kept without its pitch table, the hydrate keeping the newer store,
the public site entry), `test_npb.py` (the NPB level), `test_npb_pbp.py` (44, 15 October 2026: the play-by-play and
box-score parsers on recorded 2016 and 2026 pages, the result classifier, runs reconciled with the line score, RE24 and
the season tables, outs on a play, the nx-id remap, the expected-stats fit on a planted relation, xwOBA, the lab payload)
and `test_value_trade.py` (27: grade cuts, percentiles, WAR split by position games, strengths, weaknesses and candidate
ranking with the feasibility hints, sample floors, the Central League DH, the value payload's floors and best-by-position,
Marcel weights and the walk-forward projection fit, the aging curve, the depth-chart allocation's caps, availability and
replacement fill, the trade delta and displacement, curve interpolation, and the MLB sensitivity curves from the season
simulation on a synthetic league) and `test_moves_fantasy.py` (35, 16 October 2026: the Stats API transactions and stat
lines on planted answers, the offline cache, transaction parsing, trade grouping and three-club merges, injured-list stints
and days, the WAR split by club and date, aging paths, bands, scarcity, the log-link fit, prospect rows, trade grades,
timing, value at a date with retention, base rates, realised value, a rated trade, fantasy lines, z-values, replacement,
dollars, tiers, points, steals and current clubs). JS: no Node on the owner's machine; parse every edited file with esprima
(`uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/bullpen/assets/js/value.js', encoding='utf-8').read())"`),
which also rejects `?.` and `??`, and load the page locally.

---

## 9. Recipes

### Add a player metric

1. Compute it in `analytics/hitters.py` or `pitchers.py` (from the season's pitch pass,
   `pitchagg`, or a model output through `SeasonContext.model`) and add its METRIC (key,
   label, group, fmt, lower, scope, unit, desc); give it a sample floor and a stabilisation k
   (from `stabilise.py`, or a published value).
2. The glossary reads the catalogue's metrics (`glossary.build`); check the entry.
3. The catalogue, lab, compare, leaders and glossary pick it up from the payload; a
   player-page panel that should feature it needs `player.js`.

### Add a page

Write `docs/bullpen/assets/js/<page>.js` registering `BP.route('<page>', render)`, add a
`<script>` tag to `index.html` (and a nav link if wanted); add the route in `core.js`
(`addRoute`) if it takes ids. Build its payload in `analytics/` and write it from
`build_season` with `b.write_or_fail(...)`; document it in `PAYLOADS.md`.

### Change a model constant

Refit and commit the file in `oddsmarkets/baseball/models/fitted/` (`mlb_fit.py`;
[RUNBOOK.md](RUNBOOK.md) section 4), not a constant in the code; bump the module's
`MODEL_VERSION` if the change is structural (the versions enter every season's and every game
page's signature). The next build rebuilds the light seasons and page seasons on a machine that
has their pitch tables; past seasons on the public site change only with a hand deploy (RUNBOOK
section 7). Update the Methodology's figures (`docs.js`) by hand.

---

## 10. Known gaps

1. (Resolved 1 October 2026.) The Methodology claimed a 2016-on backtest and history from
   1901; it now says the committed backtest is 2026 only (2016–2026 follows the backfill) and
   history starts in 1908 ([MODELS.md](MODELS.md) section 22).
2. Game pages exist for two seasons on the public site; older games are reachable through
   schedules, team logs and careers only.
3. No Triple-A season is on the owner's machine yet; the Triple-A pages exist only for what CI
   fetches (the current season).
4. `linescore_totals` counts Statcast `field_error` events only, a lower bound on errors.

---

## 11. The NPB level (`npb.js`, `npb.css`; added 13 October 2026)

The level switch has a third button, **NPB**. While the level is npb, `core.js` hands every route name to the page
registered for it with `BP.routeNpb(name, fn)` in `assets/js/npb.js` (`handlerFor`); routes the level does not have
(Umpires, Parks, Prospects, Awards, Markets: all built on Statcast) go to a short note, and their nav links are hidden
by `body.lv-npb` rules in `assets/npb.css` (a new stylesheet; `assets/base.css` is untouched). Since 15 October 2026 the Lab
and Compare (`lab.js`, `compare.js`, reading `npb/<S>/lab.json`) and Value and Trade (`value.js`) register their own npb
handlers (section 12).
The Glossary, Methodology and Disclaimer stay shared (an "NPB (Japan)" glossary group and a Methodology section
"Nippon Professional Baseball" in `docs.js`; an NPB paragraph in the disclaimer).

| Route | Page | Reads |
|---|---|---|
| `#/npb` | hub: the season band (champion or favourite, pennant winners, games today), the Climax Series and Japan Series bracket with each stage's odds, championship odds against Kalshi, today / coming up / recent games, mini standings, leaders | `index.json` `levels.npb`, `npb/<S>/season.json` |
| `#/npb/standings` | Central and Pacific: G, W, L, T, PCT (W/(W+L)), GB, RS, RA, diff, Pythagorean, home, road, interleague, streak, rating, top-three and title odds; head-to-head matrices; the tiebreakers and the season's rules | `season.json` |
| `#/postseason` | the bracket (seeds, stages with the advantage shown as +1 or +2, game chips linking to game pages), odds, the postseason games, the format | `season.json`, `schedule.json` |
| `#/npb/games[/<date>]` | a day's cards with day navigation | `schedule.json` |
| `#/npb/game/<gpk>` | line score (ties and extra innings), the model's away / tie / home with Kalshi, expected runs and the runs distribution chart, over 7.5 / 8.5, decisions and home runs, both box scores (2026 on with every plate appearance's result) | `npb/<S>/games/<gpk>.json` (falls back to the card) |
| `#/npb/hitters`, `#/npb/pitchers` | season tables (league and minimum toggles), the league constants | `players.json` |
| `#/npb/player/<pid>` (also `hitter/`, `pitcher/`) | Japanese name and reading, profile, this season's WAR-lite, wRC+, ERA/FIP, career batting and pitching by season | `npb/careers/<NN>.json`, `players.json` |
| `#/npb/teams`, `#/npb/team/<tid>` | clubs; a club's record, rating through the season (chart), leading players, every game with the model's pre-game chance, its names over time | `teams.json`, `season.json` |
| `#/npb/leaders` | league leaders (qualified: 3.1 PA or 1 IP per club game) | `players.json`, `season.json` |
| `#/history` | champions by year since 1950 (Japan Series, pennants, Climax Series, MVPs), titles by club, every franchise's names, all-time leaders, any season's standings and awards | `npb/history.json` |
| `#/calibration` | the walk-forward backtest: three-way log loss and Brier against the baseline, by season (ties predicted against actual, extra-inning limit), calibration chart, against Kalshi, parameters | `npb/calibration.json` |
| `#/npb/lab` | the MLB lab over NPB's metrics: hitters, pitchers and clubs, any two metrics, presets (xwOBA against wOBA, pull against home runs per air ball, FIP against ERA, the first and third times through the order, defensive efficiency against runs allowed, ...); play-by-play metrics from 2016 | `npb/<S>/lab.json` |
| `#/compare` (level npb) | two hitters, two pitchers or two clubs side by side; percentiles computed in the browser from the lab file among players above its floors (200 PA, 150 BF) | `npb/<S>/lab.json` |
| `#/npb/value`, `#/npb/trade`, the team page's strengths and needs | section 12 | `npb/<S>/value.json`, `value/<tid>.json`, `trade.json` |

Search: `core.js` adds NPB players from `npb/names.json` (English and Japanese names) and NPB clubs (with their
Japanese names) to the search box. Phone width: every grid collapses to one column under 640 px and tables scroll
inside `.table-wrap`; checked at 375 px. The build is `oddsmarkets/baseball/npb/build.py`, called by
`build_bullpen.py` (`--levels npb` alone takes seconds); payloads in `oddsmarkets/baseball/PAYLOADS.md`, "NPB".


---

## 12. Value, strengths and needs, and the trade simulator (`value.js`, `value.css`; added 15 October 2026)

Every level (MLB, Triple-A, NPB); the trade simulator for MLB and NPB (Triple-A's trade page points to MLB's). Models in
[MODELS.md](MODELS.md) section 25, payloads in `PAYLOADS.md` "Value and trade".

| Route | Page | Reads |
|---|---|---|
| `#/<L>/value` | the leaderboard (WAR, the rate per 600 PA / 700 BF, the percentile, last season and the change, next season's projection, "why": the components) with filters for hitters or pitchers, club, position (eligible positions count), minimum sample and a name search; the best ten at each position (C 1B 2B 3B SS LF CF RF DH SP RP); the projection's out-of-sample check | `<L>/<S>/value.json` |
| `#/<L>/trade?a=<tid>&b=<tid>&ao=<pid,..>&bo=<pid,..>` | two clubs and the players each sends (checkbox rosters); per club the verdict, value in and out, next season, the depth-chart change in wins and runs, who loses time, what is left at replacement level, the postseason / division / title odds before and after (interpolated on the club's sensitivity curve), the moved players' age and next one and three seasons, the depth chart after; "Copy link" keeps the state in the hash | `<L>/<S>/trade.json`, `<L>/<S>/value/<tid>.json` (both clubs) |
| team pages (`teams.js` `#tm-value`, `npb.js` `#npb-value`) | "Strengths and needs": the three strongest and weakest positions with the evidence, every position's grade, WAR there, rank and percentile; "Ways to improve": the best five candidates on other clubs for each weakness with age, WAR, projected value there, gain and feasibility hints, and a link into the trade simulator; current season only | `<L>/<S>/value/<tid>.json` |

`value.js` mirrors `analytics/trade.allocate` (`BP.valueAllocate`) and `trade.interp` (`BP.valueInterp`); the Python versions
are the tested ones (`tests/baseball/test_value_trade.py`). Phone width: the rosters, the two clubs' results and the
strengths/needs columns collapse to one column under 640 px and tables scroll inside `.table-wrap`; checked at 375 px with
headless Chrome (no horizontal overflow, no console errors).

The build: `build_bullpen.build_level` calls `analytics/value_build.build_level` for MLB and Triple-A after the seasons
(`--no-value` skips it); `npb/build.build_level` calls `npb/valuebuild.build_all` (the lab, then the value files). The
sensitivity curves cost about 3.5 minutes for MLB (30 clubs x 6 shifts + the base, 1,000 seasons each) and about 20 seconds
for NPB (2,000 seasons each); they are cached and recomputed at most every six hours while their inputs change.

---

## 13. Moves and fantasy (`moves.js`, `fantasy.js`; valuation v2 in `value.js`; added 16 October 2026)

MLB only (the nav links point at `#/mlb/moves` and `#/mlb/fantasy`; the routes are added in `core.js`). Models in MODELS.md
sections 26-28, payloads in PAYLOADS.md "Valuation v2, transactions, trade ratings and fantasy".

| Route | Page | Reads |
|---|---|---|
| `#/mlb/value` (and `#/aaa/value`) | a "Valuation: the next five seasons" card under the leaderboard with the same filters: next season's and three seasons' expected WAR with 80% bands, the five-season value, wins over the median starter at his position, injured-list days and risk, the bands' coverage and the scarcity lines; Triple-A: "Prospect value" (the minor-league model) | `<L>/<S>/value.json` |
| `#/mlb/moves?tab=trades|clubs|feed|il|method&team=<tid>&kind=<kind>` | Trades: each trade of the last twelve months with each club's grade, net, value in and out, realised since and every piece (valued by the MLB projection, the prospect model or the base rate); biggest or newest first. Clubs: winners and losers and the counts of every kind of move. Feed: every move with club, kind and name filters. Injured list: who is on it now. Method: the validation, retention, the prospect model, base rates, sources and terms | `mlb/moves.json`, `mlb/trades.json` |
| MLB team pages (`teams.js` `#tm-moves`) | "Moves": the club's twelve-month trade record and its last trades and moves | the same |
| `#/mlb/fantasy?tab=rank|dyn|picks|closers|steals|week|bt|scoring&fmt=5x5|pts&kind=all|H|P&pos=` | Rankings (5x5 dollars and value, or points under the scoring kept in the browser, localStorage key `qb-fantasy-points-v1`), tiers, last season's rank, reasons; Dynasty (five-season values and prospects); Our picks (sleepers, fades, young risers, luck carry-over); Closers by club; Steals and untapped speed; This week (in season: two-start and streaming starters, hitters' week); Backtest; Scoring | `mlb/fantasy.json`, `mlb/fantasy_backtest.json` |

Phone width: every table scrolls inside `.table-wrap`, the trade cards' clubs collapse to one column under 640 px; checked at
375 and 1280 px with headless Chrome (no horizontal overflow, no console errors) on every tab, `#/mlb/value`, `#/aaa/value` and
team pages. JS parsed with esprima; no `?.` or `??`.
