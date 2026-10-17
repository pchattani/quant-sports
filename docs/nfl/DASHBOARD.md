# The Quant Gridiron: the website and its build

How the site at https://pchattani.github.io/the-quant-gridiron/ is put together: the
static front-end under `docs/gridiron/`, every payload under `docs/gridiron/data/` and what
builds it (`scripts/build_gridiron.py` and `oddsmarkets/nfl/analytics/`), local preview,
tests and recipes. The payload contract in full is `oddsmarkets/nfl/PAYLOADS.md` (its "As
built" section); this document follows the code where they differ. Models are in
[MODELS.md](MODELS.md), the stores in [DATA_PIPELINE.md](DATA_PIPELINE.md).

Contents

1. Architecture
2. The front-end
3. Pages
4. The build: `scripts/build_gridiron.py`
5. Payload reference
6. How degradation shows on the page
7. Local preview
8. Tests
9. Recipes
10. Known gaps

---

## 1. Architecture

```
 docs/gridiron/data/<S>/store.json, calibration.json                (inputs)
 data/nfl/raw/** (nflverse mirror), data/nfl/derived/<S>/plays.parquet, data/nfl/cache/espn/**
 oddsmarkets/nfl/models/fitted/*                                     (committed fits)
        │
        ▼
 scripts/build_gridiron.py ── analytics/ (SeasonContext, adapters, players, teams, season, games, fourth,
        │                                  leaders, history, careers, people)
        │                     └── models/ (ep, wp, fourth_down, completion, yac, ryoe, kicking, pressure,
        │                                  player_value, qb, stabilise, team_strength, game, drive_sim, live,
        │                                  season_sim, awards, backtest)
        │                     └── sources/markets.py (Kalshi, Polymarket; current season only)
        ▼
 docs/gridiron/data/**.json  (payloads, manifests)        docs/gridiron/assets/base.css (copied from docs/site)
        │
        ▼
 docs/gridiron/index.html + assets/js/*.js (hand-written, shipped verbatim) ── fetch('data/…') in the browser
```

No template engine, no bundler, no server: the browser fetches JSON payloads and renders
them with twenty-one plain scripts and Plotly 2.27 (cdn.plot.ly). The shell was copied
from The Quant Bullpen (`window.BP` became `window.GI`; the level switch became season and
week pickers).

---

## 2. The front-end

### 2.1 Files

| File | Role |
|---|---|
| `index.html` | the shell: header (brand "The Quant Gridiron", tagline "Odds, models and analytics for the NFL", season and week pickers, search, sister-site links to the Footballer, Paddock, Hardwood, Ace, Bullpen and Rink), navigation, `<main id="app">`, the disclaimer and terms, the footer with credits, the first-visit notice (localStorage key `qg-notice-v1`), the script tags |
| `assets/base.css` | the sister sites' base stylesheet, copied from `docs/site/assets/style.css` on every build (do not edit here) |
| `assets/gridiron.css`, `pages.css`, `pages-f.css` | the Gridiron's own look (turf and leather palette); the page styles |
| `assets/js/core.js` | `window.GI`: state, routing, cached loading, formatting, football helpers (weeks, downs, clocks, drive results, grades, lines), names and links, HTML helpers, Plotly wrappers, the header and search, live refresh |
| `assets/js/charts.js` | `GI.charts`: the drive chart, the win-probability chart (ours v ESPN, fourth downs marked by grade), field heatmaps, pass depth × location grids, distributions, the bracket |
| `assets/js/fx.js` | `GI.fx`: helpers for the catalogue pages (adapted from the Bullpen's `BP.fx`) |
| `assets/js/players.js` | `GI.fk`, the catalogue kit read lazily by the other catalogue pages; the players catalogue |
| `hub.js`, `week.js`, `game.js`, `standings.js`, `playoffs.js`, `markets.js`, `player.js`, `teams.js`, `team.js`, `fourth.js`, `coaches.js`, `leaders.js`, `history.js`, `lab.js`, `compare.js`, `value.js`, `trade.js`, `calibration.js`, `docs.js` | one page each (section 3); `docs.js` has the glossary and the methodology |

### 2.2 The `GI` namespace

`core.js` returns one object: `state` (season, week), `route(name, fn)` (each page module
registers itself), `go`, `parseHash`, `setSeason`, `setWeek`; data: `load(path)` (a cached
`fetch('data/' + path, {cache: 'no-cache'})` resolving to the JSON or `null`; a payload
written with `"ok": false` resolves as written, test with `GI.ok(d)`), `loadAll`,
`ypath`, `weekPath`, `gamePath`, `playerPath`, `liveRefresh`; formatting (`pct`, `signed`,
`pp`, `fmtDate`, `american`, `devigAm` ...); football helpers (`weekLabel`, `downDist`,
`fieldPos`, `fmtClock`, `driveResult`, `gradeOf`, `homeLine`, `spreadText`, `gameCard`);
names and links (`playerName`, `playerLink`, `teamName`, `teamColour`, `gameLink`,
`coachLink`, `weekLink`); HTML helpers (`tableHTML`, `sortable`, `pctPill`, `statTile`,
`probCell`, `edgeHTML`, `gradePill`); `plot`, `layout`, `C` (colours: leather `#c8834a`
for the home side, blue for the away side, green / amber / red for right call / close call
/ mistake).

Before a page renders, core loads `players_index.json` (`{pid: [name, team, pos, first,
last]}`) so names and links work synchronously. Team names and colours come from
`index.json` `teams`, with a built-in table of the 32 clubs (plus OAK, SD, STL) as the
fallback.

**Spread convention**: every spread is the home team's betting line, negative when the home
team is favoured; a payload that writes the expected home margin instead can say so
(`"spread_convention": "margin"`) and `GI.homeLine` converts it.

### 2.3 Routes

```
#/                                   hub
#/week  #/week/<S>/<w>               a week of games (w = 1..18; playoffs 19..22, or WC|DIV|CON|SB)
#/game/<game_id>                     game centre (the season is the id's prefix)
#/standings[/<S>]  #/playoffs[/<S>]  standings; the playoff picture and bracket
#/teams  #/team/<abbr>               teams
#/players  #/player/<pid>            players (pid = gsis id)
#/fourth-downs  #/coaches  #/coach/<name>  #/leaders  #/history  #/lab  #/compare[/<a>[/<b>]]
#/markets  #/calibration  #/glossary[/<key>]  #/methodology[/<section>]  #/disclaimer
#/value[?pos=&team=&s=]  #/trade[?t=<abbr>,<abbr>[,<abbr>]&m=<pid>:<to>,...]   player value; the trade simulator
```

The season comes from the route (`#/week/<S>/…`, `#/standings/<S>`, `#/playoffs/<S>`),
else a `?s=<YYYY>` query (any page), else `index.json` `season`; the week from the route,
else `?w=`, else `index.json` `week` (current season) or 1. Links carry `?s=` when the
season shown is not the current one. Pages read further options from the query:
`players?g=QB|RB|WR|TE|K|P|DEF`, `leaders?g=&m=`, `lab?g=…|TEAM&x=&y=`; compare takes
gsis ids or `t:<abbr>` for teams.

The navigation (`index.html`): Hub, Week, Standings, Playoffs, Teams, Players, Value, Trade,
Fourth downs, Coaches, Leaders, History, Lab, Compare, Markets, Calibration, Glossary,
Methodology. Game, player, team and coach pages are reached through links and the search.

### 2.4 Header, search, disclaimer

The season picker lists `index.json` `seasons` (1999 on); the week picker the season's
weeks. The search box matches players (`players_index.json`) and teams. The disclaimer
(`#/disclaimer`) covers: no affiliation with the NFL, any club, player, ESPN, bookmakers or
markets, and no logos; data sources and licences (nflverse CC BY 4.0 with credit, FTN Data
via nflverse CC BY-SA 4.0 with derived charting data shared alike, NFL Next Gen Stats
credited for informational non-commercial use, ESPN's public data for personal
non-commercial use, Kalshi and Polymarket prices); rights holders and corrections; privacy
(no cookies, no analytics; localStorage only for the first-visit notice; Plotly from
cdn.plot.ly); 18+ where gambling is discussed. The footer repeats the credits.

---

## 3. Pages

### 3.1 Hub (`#/`, `hub.js`)

A band with the season and week at a glance (games this week and live now, the Super Bowl
favourite, the biggest model–market gap, the next kickoff) and the playoff-odds snapshot;
live games (refreshed every minute while any game is live); this week's games as cards,
then the model v market v line table with live win probability (`GI.mvmTable`, shared with
the week page); the biggest gaps (games and futures); leaders; last week's results;
explore links. Reads `index.json` and `glossary.json` (leader labels).

### 3.2 Week (`#/week/<S>/<w>`, `week.js`)

Every game of the week as a card (grouped by day), the model v market v line table, key
matchups and, once games are final, how the model's favourites and its side against the
line did. Reads `<S>/weeks/<w>.json`, falling back to the week's games in
`<S>/schedule.json`. Refreshes every minute while a game is live.

### 3.3 Game centre (`#/game/<game_id>`, `game.js`)

Header: teams, score, quarter and clock, possession with down, distance and field position
on a field strip, live win probability (ours and ESPN's), the linescore, venue, weather,
officials. Tabs: **Preview** (model v market v line for win, spread and total, the
projected score, margin and total distributions with the key numbers, injuries and QB
status, weather, unit matchups); **Game flow** (the WP chart with every fourth down marked
by its grade, scoring plays and numbered key plays; the drive chart; the fourth-down
decisions; key plays; awards); **Plays** (play-by-play with team, quarter, play-type, EPA
and WPA filters and a search); **Box score** (passing, rushing, receiving, defence, team,
with advanced and NGS columns). Reads `<S>/games/<game_id>.json`; falls back to the card in
`schedule.json` while no page exists.

### 3.4 Standings and Playoffs

- **Standings** (`standings.js`): Divisions (W-L-T, points, differential, our rating,
  strength of schedule played and remaining, simulated playoff, division, bye and Super
  Bowl odds, magic and elimination numbers), Conferences (the seeding race with the cut
  line), Ratings (unit ratings and their week-by-week history), Win totals (simulated win
  distributions), Draft order. Reads `<S>/season.json`.
- **Playoffs** (`playoffs.js`): the 14-team bracket (No. 1 seed's bye; 2v7, 3v6, 4v5;
  reseeding) with each game's model probability and the market where there is one,
  projected from today's seeds before the playoffs; seed distributions and round odds
  against the Super Bowl market. Reads `<S>/season.json` and `<S>/markets.json`.

### 3.5 Teams (`teams.js`, `team.js`)

The table of every club's unit ratings, tendencies, pace, fourth-down aggressiveness and
odds, with offence against defence on a chart. The team page: record, rating and odds
tiles; playoff paths; unit ratings week by week; the profile as percentiles; tendencies
(PROE by situation, play action, RPO, motion, personnel, formation) and pace;
fourth-down aggressiveness with the team's own fourth downs graded; the schedule against
the model and the market; the QB situation; roster value; and **strengths and needs**
(current season): unit and position grades against the league (A–F by percentile), the
top three strengths and weaknesses with the number behind each, and ways to improve each
weak position (trade targets from other rosters and unsigned players, ranked by the points
a game they would add, with the change in wins and playoff odds, what the seller loses,
hints, and a "Simulate" link into the trade simulator), labelled as model suggestions on
on-field value only. Reads `<S>/teams.json`, `season.json`, `fourth_downs.json`,
`schedule.json`, `players.json`, `needs/<abbr>.json`.

### 3.6 Players (`players.js`, `player.js`)

The **catalogue** by position group (QB, RB, WR, TE, K, P, DEF) with percentiles against
the group (`pct`) and the exact position (`pct_pos`; DL / LB / DB within defence). The
**player page**, position-aware: header (team, position, age, college, draft), tiles,
Savant-style percentile sliders, the season game log, the career from 1999 with a
value-by-season chart, NGS and FTN panels, similar players; QBs the pass grid by depth and
location; RBs RYOE (ours against NGS's) by game; receivers the target depth profile; K/P
field goals over expected and punting; defenders what the public data allows. Reads
`players/<pid>.json`, `<S>/players.json`, `players_index.json`.

### 3.7 Fourth downs and coaches (`fourth.js`, `coaches.js`)

Every fourth down of the season graded: situation, choice, recommendation, WP by option,
WP lost; filters by team, week, choice, recommendation and grade; a field map; the coach
aggressiveness table. The coaches page: GOE, go rate when the model said go, agreement,
WP given up, by coach and season; the coach page adds the season-by-season line, the
record and this season's fourth downs. Reads `<S>/fourth_downs.json` and `coaches.json`.
Until the fourth-down model has scored a season, the page shows the decisions with the
league's expected go rate and leaves the grades empty.

### 3.8 Leaders, History, Lab, Compare

- **Leaders** (`leaders.js`): the top five on every group's headline metrics, then any
  catalogue metric with filters. Reads `<S>/players.json`, `<S>/leaders.json`.
- **History** (`history.js`): single-season and career boards since 1999, raw or
  era-adjusted (100 + 10 z within the season's qualified players), and the league
  environment by season. Reads `history.json`.
- **Lab** (`lab.js`): any two metrics for a group or the teams, presets, colour by team,
  position or metric, quadrants, labelled corners, optional shrinkage towards the on-screen
  median by each metric's k. Reads `<S>/lab.json`.
- **Compare** (`compare.js`): two players or two teams side by side on the catalogue.

### 3.8a Value (`#/value`, `value.js`) and Trade (`#/trade`, `trade.js`) (added 15 October 2026)

- **Value**: the currency (points above a replacement-level player at the same position;
  how each position is valued; why linemen are not), the best ten qualified players at each
  of QB, RB, WR, TE, EDGE, DL, LB, CB, S, K and P with the components behind the top three,
  and the leaderboard (season value, per game, percentile of value per game among qualified
  players at the position, trend against last season, the "why") with position, team,
  sort, size, name and qualified-only filters. Any season (`?s=`). Reads `<S>/value.json`.
- **Trade**: two or three teams, the players each sends (and, with three, to whom); per
  team the verdict (wins now / weakens now / little change; younger by three years or more
  flagged as a possible long-term gain), the strength change in points a game, value in
  and out, the effect at each touched position (before, after, who enters and leaves the
  starters; the starting QB through the team-strength QB term), and wins, playoff,
  division, bye, conference and Super Bowl odds and the mean draft slot now and after, read
  off the team's sensitivity curve (held at the edge beyond ±10 points); cap and contracts
  are not checked (OverTheCap's terms; section 10). The state is in the address, with a
  copyable share link. Current season. Reads `<S>/trade.json`.

### 3.9 Markets (`#/markets`, `markets.js`)

The games on the board with our price against the de-vigged market and the line; the
futures (Super Bowl, conferences, divisions, playoffs, No. 1 seeds, win totals, awards),
each as a chart and a table with model, market, gap and fair odds. Reads
`<S>/markets.json` (current season).

### 3.10 Calibration (`#/calibration`, `calibration.js`)

The game model against the closing line, walk-forward 2006 on (log-loss, Brier and
reliability against the de-vigged closing moneyline and the baselines; ATS and totals;
season odds), our EP and WP against nflfastR's, and the fourth-down conversion model. "What
it shows" is computed from the numbers, and a difference smaller than the noise is called a
tie. Reads `calibration.json`.

### 3.10b Transactions (`#/transactions`, `transactions.js`) and fantasy (`#/fantasy`, `fantasy.js`) (16 Oct 2026)

**Transactions**: the last twelve months of ESPN's club transaction notes, parsed (analytics/transactions.py). Tabs:
trade ratings (every trade, each side's assets with value at the time → now, net wins and grades, the winner; the best and
worst deals), winners and losers by club (net trade value at the time and now, realised value received, projected value of
the players signed and released), the feed (filter by club, type, text) and a club ledger (`ledgers/<abbr>.json`: every
move). Reads `<S>/transactions.json`. Address `#/transactions?tab=trades|table|feed|team&team=<abbr>&type=<type>`.

**Fantasy**: PPR / half / standard toggle and eight tabs: our picks (start, waiver targets, buy low, sell high, breakouts,
D/ST and kicker streamers, each with its reason), this week (rankings, tiers, matchup, team total, projection, 10th–90th
band, projected line; K and D/ST), rest of season (points, expected games, value over replacement, schedule, next four),
start/sit (pick two to four players: the chance each scores most, from 4,000 draws on the bands; Start / Flex / Sit by
position), buy & sell (points v expected points, TDs v expected, yards v expected, target share trend), streaming, schedule
strength by team and position, and the backtest (`fantasy_backtest.json`). Address `#/fantasy?f=ppr|half|std&tab=<tab>&pos=<POS>`.

The value page (`value.js`) also shows, for the current season, the projected multi-season value table (valuation v2:
level now, per-game projection by season, expected games, discounted value with its band, wins, v marginal starter),
position scarcity and the draft-pick curve, from `<S>/valuation.json`.

### 3.11 Glossary and Methodology (`docs.js`)

The glossary reads `glossary.json` (every catalogue metric with its stabilisation point,
plus the model terms and the data notices), assembling it from the season's catalogues if
it is missing. The methodology is static text in `METHOD_HTML`, 20 sections, each naming
its source files (two sections added 16 Oct 2026: valuation v2 / transactions, and fantasy); [MODELS.md](MODELS.md) section 17 lists where it and the code disagreed
(resolved on 1 October 2026).

---

## 4. The build: `scripts/build_gridiron.py`

```
python scripts/build_gridiron.py                                 # current season full, the rest light
python scripts/build_gridiron.py --seasons 2026 2025
python scripts/build_gridiron.py --quick --no-market --no-light   # fast local check
```

| Flag | Default | Meaning |
|---|---|---|
| `--seasons` | the current season | seasons built in full |
| `--sims` | 20,000 | season simulations |
| `--days-ahead` | 7 | price games kicking off up to N days ahead |
| `--quick` | – | at most 1,000 season simulations (and 2,000 drive simulations a game) |
| `--no-market` | – | skip Kalshi and Polymarket |
| `--no-light` | – | build only the full seasons |
| `--no-careers` | – | skip `players/<pid>.json` |
| `--no-history` | – | skip `history.json` |
| `--no-models` | – | catalogues from play-by-play only (no builder B/C models) |
| `--all-games` | – | rebuild every game page of the page seasons |
| `--game-page-seasons` | 2 | game pages for the N most recent seasons (0 = none) |
| `--force` | – | rebuild light seasons even when unchanged |
| `--today` | UTC today | pretend date |
| `--contracts` | – | publish cap hits and the cap check from nflverse's OverTheCap contracts (also `GRIDIRON_CONTRACTS=1`); off: OverTheCap's terms do not allow republishing (section 10) |
| `--data`, `--raw`, `--cache` | `GRIDIRON_DATA`, `GRIDIRON_RAW`, `GRIDIRON_CACHE` | roots |

Order of work: copy `base.css`; `glossary.json`; then every season on disk, newest first
(`build_season`):

1. Skip a light season whose manifest signature is unchanged (and which is not a page
   season), or a past season whose play-by-play is not on this machine but whose payloads
   exist ("payloads kept").
2. `SeasonContext(season, full, ...)`; `players.json`.
3. Markets (current season, full): futures and game prices.
4. Prices: for the current season, game-model prices for games not yet final kicking off
   from yesterday to `--days-ahead`, each with its distributions (10,000 drive simulations;
   `price_window`); walk-forward prices for games before this build
   (`adapters.walk_forward_prices`); and the frozen prices from the manifest.
5. `schedule.json` (every GAME_CARD), the season simulation (full, current), `teams.json`,
   `season.json`, `weeks/<w>.json`, `fourth_downs.json`, `referees.json`, `leaders.json`,
   `lab.json`, the value pages (`value_pages`: `value.json` every season; for the full
   current season the sensitivity curves, 2,000 importance-weighted runs a team, 300 with
   `--quick`, cached on the simulation's inputs, then `trade.json` and `needs/<abbr>.json`),
   the award model and `awards.json`, `markets.json` (full, current), the league summary.
6. Game pages for the page seasons: games whose signature (status, score, lines, QBs, plays
   on the table, the ESPN plays, the model versions) changed, every missing page, and every
   not-final game of the current season in the pricing window.
7. The players' current blocks (full seasons), the reduced catalogue rows, the manifest.

Then, site-wide: `coaches.json` and `referees.json` from every season's fourth downs and
referee tables; `history.json`; `calibration.json` (builder C's `game_model` and
`season_sim` sections kept as they are, restored from the cached backtest output when
missing; `ep` and `wp` refreshed from `models/fitted/{ep,wp}.json`'s validation blocks);
the career files (rewritten only when their content changed) and `players_index.json`; and
`index.json` (kept, not overwritten, when the current season was not built). Every step
runs inside `Build.step`: an exception is logged with its traceback and the build goes on;
`write_or_fail` writes `{"ok": false, "reason"}` in place of a payload that could not be
built. The log ends with the files written, the 25 slowest steps and up to 60 errors.

---

## 5. Payload reference

All under `docs/gridiron/data/`. Payloads carry `"ok": true`, `season` (per season) and
`updated_at`; probabilities 4 dp, EPA 3 dp, fractions 0–1. Sizes from the local build of
1 October 2026.

| Payload | Built by | Contents | Size and count |
|---|---|---|---|
| `index.json` | `build_gridiron.index_payload` | season, week, phase, this week's / live / recent GAME_CARDs, standings top (today's seeds), playoff odds, leaders, gaps, teams, seasons, model versions, `sim_reason` | one, 43 KB |
| `glossary.json` | `leaders.glossary` | metric groups with stabilisation points, model terms, rules, notices | one, 30 KB |
| `calibration.json` | backtest + `build_gridiron.calibration` | `game_model`, `season_sim`, `ep`, `wp` | one, committed, 50 KB |
| `history.json` | `history.build` | season and career leaders (raw and era-adjusted), league environment by season | one, 40 KB |
| `coaches.json`, `referees.json` | `fourth.coaches`, `fourth.referees` | fourth-down grades by coach and season; referees by season | one each, 209 KB / 154 KB |
| `players_index.json` | `careers.write_careers` | `{pid: [name, team, pos, first, last]}` | one, 386 KB |
| `players/<pid>.json` | `careers.write_careers` | career from 1999, current block (log, charts, NGS, FTN), similar players | 7,471 files, 31 MB |
| `<S>/players.json` | `players.build` | the catalogue: metrics, groups, players with values, pct, pct_pos | one per season, 0.5–0.8 MB |
| `<S>/teams.json` | `teams.build` | team metrics, units, history, personnel, formation, QBs, roster value, sim, schedule | one per season, ~0.3 MB |
| `<S>/season.json` | `season.build` | standings, SOS, seeds today, simulation, draft, bracket, ratings history | one per season, 50–125 KB |
| `<S>/schedule.json` | `season.schedule` | every GAME_CARD | one per season, 180–285 KB |
| `<S>/weeks/<w>.json` | `season.weeks` | the week's cards with edges and matchups | 18–22 per season |
| `<S>/games/<game_id>.json` | `games.build_page` | the game centre (card, game, pregame, matchups, injuries, ESPN predictor, score, drives, plays, wp, fourth downs, box, key plays, awards) | current and previous season (CI prunes the rest); about 50–65 KB for a played game |
| `<S>/fourth_downs.json` | `fourth.build` | every fourth down (column-oriented) and the coach table | one per season, 100–575 KB |
| `<S>/referees.json`, `leaders.json`, `lab.json`, `awards.json` | `fourth`, `leaders` | as `PAYLOADS.md` | one each per season |
| `<S>/markets.json` | `season.markets_payload` | games, futures, win totals, awards, sources, notice | current season, ~100 KB |
| `<S>/value.json` | `value.value_payload` | value above replacement by player, best ten at each position, replacement levels | every season, 100–150 KB |
| `<S>/trade.json` | `value.trade_payload` | players on current rosters, QB depth, sensitivity curves, published odds | current season, ~125 KB |
| `<S>/needs/<abbr>.json` | `value.needs_payload` | unit and position grades, strengths, weaknesses, ways to improve | current season, 32 files, ~9 KB each |
| `<S>/manifest.json` | `build_season` | signature, frozen prices, page signatures, model errors, timings | one per season |

`PAYLOADS.md`'s "As built" section gives every field.

---

## 6. How degradation shows on the page

| Missing | What the page shows |
|---|---|
| a payload file (404) | `GI.load` resolves `null`; the page shows "not built yet" (`GI.notBuilt`) |
| a payload with `"ok": false` | its `reason` |
| a model (`model_errors` in the manifest) | the metrics that need it are empty; the catalogue says which model was not available |
| the season simulation | standings, today's seeds and the draft order by record; the odds blocks are null with `sim_reason` |
| the fourth-down model for a season | decisions with the league's expected go rate; grades and recommendations empty |
| a game's play-by-play (not yet published) | the ESPN live record's plays and win probability (`wp.source` "espn"); an older page keeps its play-level blocks |
| markets (thin, unmatched, or `--no-market`) | the model alone |
| NGS or FTN for a season | those panels are omitted |

---

## 7. Local preview

```bash
python scripts/build_gridiron.py --quick --no-market          # or a full build
cd docs/gridiron
python -m http.server 8899
# open http://127.0.0.1:8899
```

The browser fetches `data/…` relative to the page, so serve `docs/gridiron/` itself. For the
current season without fetching, run `python scripts/nfl_hydrate.py` first.

---

## 8. Tests

```bash
uv run --group dev pytest tests/nfl        # 113 tests, about 2.5 minutes, offline
```

`test_data.py` (27 functions: the release gate and schema check on recorded Parquet
slices, schedules → GAME, line signs and kickoff times, ESPN lines by book, summaries and
game-id mapping, the store's ownership merge, relocations, formats, stadiums, and fourteen
tiebreaker cases including the actual 2022 and 2025 playoff fields), `test_models_b.py` (19: EP, WP,
fourth downs and two-point tries worked by hand, kicking, completion, YAC, RYOE, value,
pressure, stabilisation and the QB composite on synthetic seasons with planted truth, the
committed-fit fallback with a cold cache), `test_models_c.py` (25: team strength, the game
model and its margin distribution, the drive simulation, the season simulation's
tiebreakers and `FastTable` against `Table`, interventional odds, magic numbers, live WP,
awards, markets from fixtures, Elo, the backtest), `test_value.py` (11: replacement levels
and sample floors, best lists, defensive roles, the starters model and QB rule, candidate
ranking and hints, the season simulation's prepared state, shift and record, the
importance weights against a planted curve, the monotone anchored curves, the curves
against direct shifted runs, the contracts table and its gate), `test_analytics_d.py` (9: percentiles,
the catalogues, teams, fourth downs, leaders, lab and glossary, game pages, an isolated
model failure, careers and history), `test_build_gridiron.py` (4: a whole build into a
temporary data root, including value.json, trade.json and needs/; an isolated failing step,
the index kept when the current season was not built, an unchanged light season skipped).
There is no automated JS check; before committing a JS change parse it with esprima
(`uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/gridiron/assets/js/<file>.js', encoding='utf-8').read())"`;
no `?.` or `??`) and load the page locally at 375 px and desktop width.

---

## 9. Recipes

### Add a player metric

1. Compute it in the right `analytics/players.py` row builder (`qb_rows`, `rush_rows`,
   `rec_rows`, `kick_rows`, `punt_rows`, `def_rows`) and add an `M(key, label, group, fmt,
   scope=..., den=..., k=..., desc=...)` entry to the catalogue's metric list (the unit and
   the stabilisation k decide its shrinkage and floor).
2. Make sure the glossary picks it up (`leaders.glossary` reads the catalogue's metrics).
3. The catalogue, lab, compare, leaders and glossary pick it up from the payload; a
   player-page panel that should feature it needs `player.js`.

### Add a page

Write `docs/gridiron/assets/js/<page>.js` registering `GI.route('<page>', render)`, add a
`<script>` tag to `index.html` (and a nav link if wanted); add the route in `core.js`
(`addRoute`) if it takes ids. Build its payload in `analytics/` and write it from
`build_season` with `b.write_or_fail(...)`; document it in `PAYLOADS.md`.

### Change a model constant

Refit and commit the file in `oddsmarkets/nfl/models/fitted/` (`nfl_fit.py`;
[RUNBOOK.md](RUNBOOK.md) section 4), not a constant in the code. The fit keys enter every
season's signature and every game page's signature, so the next build rebuilds the light
seasons and the page seasons' game pages; past seasons' payloads on the public site change
only with a hand deploy (RUNBOOK section 6). Update the Methodology's figures (`docs.js`)
by hand.

---

## 10. Known gaps

1. (Resolved 1 October 2026.) The Methodology quoted code defaults and old constants where
   the site runs on committed fits; it now quotes the fits ([MODELS.md](MODELS.md) section 17).
2. Game pages exist for two seasons on the public site; older games are reachable through
   schedules, weeks, careers and history only.
3. A placeholder player id `"0"` from early play-by-play's defensive credits got an index
   entry and a career file (`players/0.json`, "0", DEF, 1999–2000). The build no longer writes
   either (`careers.real_pid`, 1 October 2026); the committed `players/0.json` stays until it
   is deleted by hand, and the 1999 and 2000 catalogues still list the id.
4. (Resolved 1 October 2026.) The fourth-down texts said a right call was under 1 point
   while the labels followed the payload's letters; texts, legends and the numeric fallback
   now use the letters' cut-offs, right call ≤ 1.5 points (A–B), close call ≤ 3 (C), mistake
   above 3 (D–F) ([MODELS.md](MODELS.md) section 17, item 10).
5. **Cap and contracts are not shown** (15 October 2026): nflverse's `contracts` release is
   OverTheCap's data, and OverTheCap's terms forbid republishing it on a website without its
   consent. `analytics/contracts.py` and `--contracts` are ready (cap hits, contract years,
   a cap check against the season cap derived from cap numbers and cap percentages) for when
   permission exists; the release is fetched only by name (`nfl_fetch.py --releases
   contracts`).
6. **Value limits**: defenders on credited plays only; offensive linemen not valued
   individually; a backup carries the per-game value he has shown; each team's trade odds
   come from its own sensitivity curve (no re-simulation of the two teams together).
7. (Fixed 15 October 2026.) Catch rate over expected was stored in percentage points when our
   completion model scored the season (`completion.py` reports it ×100) but as a fraction on
   the play-by-play fallback, while the catalogue metric is a fraction (`fmt` "pct"), so the
   players page showed, for example, 1780% for +17.8 points. `adapters.player_tables` now
   scales the model's value to a fraction; the next build rewrites every season's catalogue
   (BUILD_VERSION 2 rebuilds the light seasons once).
