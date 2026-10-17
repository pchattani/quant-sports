# The Quant Rink: the website and its build

How the site at https://pchattani.github.io/the-quant-rink/ is put together: the static
front-end under `docs/rink/`, every payload under `docs/rink/data/` and what builds it
(`scripts/build_rink.py` and `oddsmarkets/nhl/analytics/`), local preview, tests and
recipes. The payload contract in full is `oddsmarkets/nhl/PAYLOADS.md` (its "As built"
section); this document follows the code where they differ. Models are in
[MODELS.md](MODELS.md), the stores in [DATA_PIPELINE.md](DATA_PIPELINE.md).

Contents

1. Architecture
2. The front-end
3. Pages
4. The build: `scripts/build_rink.py`
5. Payload reference
6. How degradation shows on the page
7. Local preview
8. Tests
9. Recipes
10. Known gaps

---

## 1. Architecture

```
 docs/rink/data/<S>/store.json, calibration.json                          (inputs)
 data/nhl/derived/<S>/{events,stints}.parquet, data/nhl/{edge,stats}/<S>/**, data/nhl/moneypuck/**
 oddsmarkets/nhl/models/fitted/*                                            (committed fits)
        │
        ▼
 scripts/build_rink.py ── analytics/ (SeasonContext, adapters, tables, box, skaters, goalies, teams, season,
        │                              games, leaders, history, careers, glossary, edge, xgfallback)
        │                 └── models/ (xg, shooting, goalies, onice, rapm, value, lines, stabilise, team_strength,
        │                              game, live, season_sim, awards, backtest)
        │                 └── sources/markets.py (Kalshi, Polymarket; current season only)
        ▼
 docs/rink/data/**.json  (payloads, manifests)        docs/rink/assets/base.css (copied from docs/site)
        │
        ▼
 docs/rink/index.html + assets/js/*.js (hand-written, shipped verbatim) ── fetch('data/…') in the browser
```

No template engine, no bundler, no server: the browser fetches JSON payloads and renders
them with twenty-one plain scripts and Plotly 2.27 (cdn.plot.ly). The shell was copied from
The Quant Gridiron (`window.GI` became `window.RK`; the week picker became a game-day
strip).

---

## 2. The front-end

### 2.1 Files

| File | Role |
|---|---|
| `index.html` | the shell: header (brand "The Quant Rink", tagline "Odds, models and analytics for the NHL", season picker, search, sister-site links to the Footballer, Paddock, Hardwood, Ace, Bullpen and Gridiron), navigation, `<main id="app">`, the disclaimer and terms, the footer with credits, the first-visit notice (localStorage key `qr-notice-v1`), the script tags |
| `assets/base.css` | the sister sites' base stylesheet, copied from `docs/site/assets/style.css` on every build (do not edit here) |
| `assets/rink.css`, `pages.css`, `pages-f.css` | the Rink's own look (ice palette); the page styles |
| `assets/js/core.js` | `window.RK`: state, routing, cached loading, formatting, hockey helpers (periods, clocks, puck lines, strengths), names and links, HTML helpers, Plotly wrappers, the header and search, live refresh |
| `assets/js/charts.js` | `RK.charts`: the rink to scale (boards, lines, creases, circles; half or full), shot maps (xG-sized dots, goals filled), hex and zone heatmaps, the xG race, the WP chart, distributions, the bracket |
| `assets/js/fx.js` | `RK.fx`: helpers for the catalogue pages (adapted from the Gridiron's `GI.fx`) |
| `assets/js/skaters.js` | `RK.fk`, the catalogue kit read lazily by the other catalogue pages; the skater catalogue |
| `hub.js`, `games.js`, `game.js`, `standings.js`, `playoffs.js`, `markets.js`, `goalies.js`, `player.js`, `teams.js`, `team.js`, `lines.js`, `leaders.js`, `history.js`, `lab.js`, `compare.js`, `calibration.js`, `docs.js` | one page each (section 3); `docs.js` has the glossary and the methodology |
| `value.js`, `trade.js` | the Value page and the trade simulator (section 3.11; `RK.tradeModel` exposes the depth chart) |

### 2.2 The `RK` namespace

`core.js` returns one object: `state` (season, date), `route(name, fn)` (each page module
registers itself), the router and `?s=` season links (`sq`, `href`); data: `load(path)` (a
cached `fetch('data/' + path)` resolving to the JSON or `null`; a payload written with
`"ok": false` resolves as written); formatting and probability helpers; names and links
(`playerName`, `playerLink`, `teamName`, `teamColour`, ...); HTML helpers (`tableHTML`,
`sortable`, `pctColor`, ...); `plot`, `layout`, `C` (colours: ice blue `#5cc6f2` for the home
side, coral `#ef6a6e` for the away side; green, amber and red for good, close and bad).

Before a page renders, core loads `players_index.json` (`{pid: [name, team, pos,
first_season, last_season]}`) so names and links work synchronously. Team names and colours
come from `index.json` `teams` (and any payload carrying a `teams` dict), with a built-in
table of the 32 clubs (plus ARI, PHX, ATL) as the fallback.

**Conventions** (core's header): every puck line is the home team's line, negative when the
home side is favoured; `sec` is elapsed game seconds (0 at the opening face-off, 1,200 per
regulation period); `clock` is the time remaining in the period.

### 2.3 Routes

```
#/                                   hub
#/games  #/games/<YYYY-MM-DD>        a day of games (default: today, else the nearest day with games)
#/game/<game_id>                     game centre (the season is the id's first four digits)
#/standings[/<S>]  #/playoffs[/<S>]  standings and playoff race; the bracket (S = 20262027)
#/teams  #/team/<abbr>               teams
#/skaters  #/goalies  #/player/<pid>  #/lines  #/leaders  #/history  #/lab  #/compare[/<a>[/<b>]]
#/value                              player value (?kind=S|G&pos=F|C|L|R|D&team=&min=&q=&n=&s=)
#/trade                              trade simulator (?t=<abbr>,<abbr>[,<abbr>]&m=<pid>-<to abbr>.<pid>-<to abbr>)
#/markets  #/calibration  #/glossary[/<key>]  #/methodology[/<section>]  #/disclaimer
```

The season comes from the route (`#/standings/<S>`, `#/playoffs/<S>`), the game id, else a
`?s=<S>` query (any page; `?s=2026` and `?s=2026-27` are accepted), else `index.json`
`season`; the games page's day from the route, else `?d=`. Links carry `?s=` when the
season shown is not the current one. Pages read further options from the query:
`lines?kind=F|D&team=`, `leaders?p=F|D|A|G&m=`, `lab?kind=S|G|T&pos=F|D&x=&y=`; compare takes
playerIds or `t:<abbr>` for teams.

The navigation (`index.html`): Hub, Games, Standings, Playoffs, Teams, Skaters, Goalies,
Value, Trade, Lines, Leaders, History, Lab, Compare, Markets, Calibration, Glossary, Methodology. Game,
player and team pages are reached through links and the search.

### 2.4 Header, search, disclaimer

The season picker lists `index.json` `seasons`. The search box matches players
(`players_index.json`) and teams. The disclaimer (`#/disclaimer`) covers: no affiliation
with the NHL, the NHLPA, any club, player, ESPN, bookmakers or markets, and no logos; NHL
data shown for informational, non-commercial use; "xG benchmark data from MoneyPuck.com"
credited where shown; ESPN's public odds; Kalshi and Polymarket prices; 18+ where gambling is
discussed. The footer repeats the credits.

---

## 3. Pages

### 3.1 Hub (`#/`, `hub.js`)

A band with today at a glance (games today and live now, the Stanley Cup favourite, the
biggest model–market gap, the next puck drop) and the playoff-odds snapshot by conference;
live games (refreshed every minute while any game is live); today's games as cards, then
the model v market v line table with live win probability (`RK.mvmTable`, shared with the
games and markets pages); the biggest gaps (games and futures); last night's results; the
next day's games; leaders; explore links. Reads `index.json` and `glossary.json`.

### 3.2 Games (`#/games[/<date>]`, `games.js`)

A strip of game days, every game of the day as a card, the model v market v line table and,
once games are final, how the model's favourites, its side of the puck line and its totals
did. Reads `<S>/schedule.json` for the season of the day (a date from September on belongs
to that season), with today's cards from `index.json` when they are fresher.

### 3.3 Game centre (`#/game/<game_id>`, `game.js`)

Header: teams, score, period and clock, live win probability and expected goals, the
linescore by period with shots on goal, venue, the game type (playoff round and game).
Tabs: **Preview** (model v market v line for the win (overtime included), regulation
(three-way), overtime, puck line and total; the projected score, the exact-score grid and
the total-goals distribution; the starting goalies); **Game flow** (the xG race, our win
probability with goals marked, half-rink shot maps with strength and period filters, the
goals and the game's awards); **Lines & TOI** (this game's forward lines and defence pairs
from the shift charts, TOI by strength); **Box score** (skaters with individual xG, hits,
blocks, giveaways, takeaways, faceoffs, TOI by strength and on-ice xGF%; goalies with saves,
xGA and GSAx; team stats). Reads `<S>/games/<game_id>.json`, else the card in
`schedule.json`.

### 3.4 Standings and Playoffs

- **Standings** (`standings.js`): Wild card (each conference's top three per division, the
  two wild cards, the cut line, the chasers), Divisions, League, Playoff odds (playoffs,
  division, Presidents' Trophy, conference, Cup; expected points with the points and seed
  distributions), Ratings (our rating by component with its history) and Lottery. Every
  table carries GP, W, L, OTL, PTS, points %, RW, ROW, GF, GA, xGF%, our rating, the
  simulated odds and the magic or elimination number. Reads `<S>/season.json`.
- **Playoffs** (`playoffs.js`): the bracket (West left, East right, the Final in the middle),
  each series with seeds, the series score and our probability (the market's where known);
  before the playoffs, the projection "if the season ended today"; every team's odds by
  round against the Cup market; the seed distribution. Reads `<S>/season.json` and
  `<S>/markets.json`.

### 3.5 Teams (`teams.js`, `team.js`)

The table of every club's unit ratings (5v5 offence and defence, power play, penalty kill,
goaltending), underlying numbers and odds, with 5v5 offence against defence on a chart. The
team page: record, rating and odds tiles; playoff paths; unit ratings over the season;
special teams; 5v5 shot maps for and against the league; lines and pairs; deployment (ice
time by strength, zone starts); the schedule against the model and the market; the roster's
value. Reads `<S>/teams.json`, `season.json`, `schedule.json`, `lines.json`, `skaters.json`,
`goalies.json`.

### 3.6 Skaters, Goalies and the player page

- **Skaters** (`skaters.js`): the catalogue (138 metrics) with percentiles against the
  qualified league (`pct`) and the position pool (`pct_pos`, forwards or defencemen).
- **Goalies** (`goalies.js`): the catalogue (45 metrics), GSAx by danger for the busiest
  goalies, a heat table by shot type, workload against GSAx per 60.
- **Player page** (`player.js`): skaters get Savant-style percentile sliders, the shot
  heatmap against the league and the shot map, the RAPM quadrant with standard errors,
  on-ice rates by strength, EDGE skating and shot speed, deployment (zone starts, QoC /
  QoT), linemates, the game log, the career, a projection and similar players; goalies get
  percentiles among goalies, GSAx by danger and location, save percentage by shot type
  against expected, workload, the log and the career. Reads `players/<pid>.json`, the
  season's catalogue and `players_index.json`.

### 3.7 Lines, Leaders, History, Lab, Compare

- **Lines** (`lines.js`): every forward line and defence pair with its 5v5 time together and
  xGF%, sorted by the shrunk share, a chart of how far each line moved from raw to shrunk.
  Reads `<S>/lines.json` (else `teams.json` `lines`).
- **Leaders** (`leaders.js`): the top five on the headline metrics for forwards,
  defencemen and goalies, then any catalogue metric with filters. Reads the catalogues,
  `<S>/leaders.json` as the fallback.
- **History** (`history.js`): every Cup champion since 1917–18 (109 rows), titles by
  franchise, the league's scoring environment by season, season leaders. Reads
  `history.json`.
- **Lab** (`lab.js`): any two metrics for skaters, goalies or teams, presets, colour by
  team, position or metric, median quadrants, optional shrinkage towards the on-screen
  median by each metric's k. Reads `<S>/lab.json`.
- **Compare** (`compare.js`): two skaters, two goalies or two teams side by side on the
  catalogue; position-pool percentiles for two players of the same pool.

### 3.8 Markets (`#/markets`, `markets.js`)

The games on the board with our price against the de-vigged market and the line
(moneyline, puck line, total); the futures (Cup, conferences, divisions, playoffs,
Presidents' Trophy, season points totals, awards), each as a chart and a table with model,
market, gap and fair odds. Reads `<S>/markets.json` (current season).

### 3.9 Calibration (`#/calibration`, `calibration.js`)

Our xG against MoneyPuck's on the same shots (log-loss, AUC, Brier, reliability, by season
and strength, with the credit); the game model against the closing lines and against Elo
and the xG baseline; season odds at the checkpoints; stabilisation. "What it shows" is
computed from the numbers, and a gap smaller than the noise is called a tie. Reads
`calibration.json` (and the catalogues for the stabilisation table).

### 3.11 Value, strengths and needs, trade (`value.js`, `team.js`, `trade.js`)

Built 15 October 2026 to `docs/VALUE_SECTIONS.md`; the models are in [MODELS.md](MODELS.md) section 17.

- **Value** (`#/value`): reads `<S>/value.json`. The head card defines GAR and WAR (with the season's goals per win
  and a chip with the team games played); tiles for the most WAR among skaters and goalies and the best centre and
  defenceman; "best at each position" (C, LW, RW, D, G: top ten qualified with WAR, GAR per 60, percentile and the
  two largest parts of GAR); a leaderboard of skaters or goalies filtered by position, team, minimum minutes and the
  qualification floor, with GAR, WAR, GAR per 60, the six parts of GAR (goalies: GSAx), percentiles, ΔGAR per 60 and
  last season's WAR. Filters write the hash with `history.replaceState`.
- **Team page "Strengths and needs"** (`team.js` `drawNeeds`, current season only): reads `<S>/needs/<abbr>.json`:
  grades (C, LW, RW, D, G, 5v5 offence and defence, power play, penalty kill), the three strengths and weaknesses
  with evidence, trade-target cards per weakness (gain in goals a game, points from the curve, playoff and Cup odds,
  hints, an "attainable" badge, a link into the trade simulator), the honest-labelling note.
- **Trade** (`#/trade`): reads `<current S>/trade.json`. Club pickers (two or three), rosters by group (rotation
  first, the rest folded) with tick boxes; per club: the verdict ("wins now / weakens now" by ±1 point from the
  `exp_pts` curve; "long-term gain / cost" by ±2 GAR next season), players in and out, tiles (rating change in goals
  a game and over the games left, points, GAR in − out, next season's GAR), the odds table (playoffs, division,
  conference, Cup, first overall pick), minutes lost to newcomers, next players up, replacement minutes, the
  rotation before and after. State in `?t=&m=`; "Copy link".
- **Tabs** (16 Oct 2026, `valuation.js` `RK.valuation.tabs`): Season value · Valuation (multi-season) · Moves and trade
  grades · Fantasy · Trade simulator, at the top of each of those pages.
- **Valuation (multi-season)** (`#/value?tab=val`, `valuation.js`): reads `<current S>/valuation.json`. Tiles (most
  valuable skater, goalie, 23 or under; scarcest position); a table filtered by players, position, team, injured only,
  sortable by four-season value, VORP, this season or next (rate ± se, minutes, availability, this season, next, four
  seasons with the p10–p90 band, VORP, P(regular) next season / in three, ESPN injury chip); position scarcity table;
  survival and ageing chart; fitted constants. The player page adds a one-line valuation under the projection.
- **Moves** (`#/moves`, `moves.js`): reads `<current S>/transactions.json` and `deals.json`. Tiles; winners and losers
  table and net-value bar chart; best deals; graded trades (club filter, minor deals toggle) as cards with each side's
  assets (at the time, realised since with games, now) and grades at the time → now; all transactions (type filter,
  search; "grade →" jumps to the deal); the pick-value curve (slot means and fit) with round averages. State
  `?team=&type=&minor=1`.
- **Team page "Ledger"** (`team.js` + `RK.moves.ledger`, current season): tiles (trades, net value now, transactions),
  the club's graded deals (its side highlighted), minor deals and every transaction folded.
- **Fantasy** (`#/fantasy`, `fantasy.js`): reads `<current S>/fantasy.json` and `fantasy_backtest.json`. Tiles; our picks;
  scoring (points weights editable and kept in localStorage, or categories by z-score); rankings (position, team, flag,
  injured filters; tier, points a game, rest of season, VOR, weeks 1–2, per-game categories or goalie start share / W /
  GAA / SV% / SO, PP unit, season-start rank, flags); streaming goalies; schedule (games per fantasy week, back-to-backs,
  opponent factor); buy low / sell high; waiver targets and breakouts; "How good are these projections?" (the backtest).
  Tiers and VOR are recomputed in the browser when the weights change.

### 3.10 Glossary and Methodology (`docs.js`)

The glossary reads `glossary.json` (24 metric groups, 16 model and rule entries, the
notices), assembling it from the season's catalogues if it is missing. The methodology is
static text in `METHOD_HTML`, 22 sections, each naming its source files;
[MODELS.md](MODELS.md) section 16 lists where it and the code disagree (open on 1 October
2026).

---

## 4. The build: `scripts/build_rink.py`

```
python scripts/build_rink.py                                    # current season full, the rest light
python scripts/build_rink.py --seasons 20262027 20252026
python scripts/build_rink.py --quick --no-market --no-light      # fast local check
```

| Flag | Default | Meaning |
|---|---|---|
| `--seasons` | the current season | seasons built in full (NHL ids) |
| `--sims` | 20,000 | season simulations |
| `--days-ahead` | 3 | price games starting up to N days ahead |
| `--quick` | – | at most 1,000 season simulations |
| `--no-market` | – | skip Kalshi and Polymarket |
| `--no-light` | – | build only the full seasons |
| `--no-careers` | – | skip `players/<pid>.json` (`players_index.json` is still written, from the stores) |
| `--no-history` | – | skip `history.json` |
| `--no-models` | – | catalogues from events and stints only (no builder B/C models) |
| `--all-games` | – | rebuild every game page of the page seasons |
| `--game-page-seasons` | 2 | game pages for the N most recent seasons (0 = none) |
| `--force` | – | rebuild light seasons even when unchanged |
| `--today` | UTC today | pretend date |
| `--data`, `--raw`, `--cache` | `RINK_DATA`, `RINK_RAW`, `RINK_CACHE` | roots |

Order of work: copy `base.css`; `glossary.json`; then every season on disk (a store under
the data root or derived events under the raw root), newest first (`build_season`):

1. Skip a light season whose manifest signature (`BUILD_VERSION` 2, the store's content
   hash, the events' and stints' sizes and mtimes, the model versions) is unchanged and
   which is not a page season, or a past season whose events are not on this machine but
   whose payloads exist ("events not on this machine; payloads kept").
2. `SeasonContext(season, full, ...)`; the shared tables; `skaters.json`, `goalies.json`.
3. Markets (current season, full): futures and game prices.
4. Prices: for the current season, game-model prices for games not yet final starting from
   yesterday to `--days-ahead` (`price_window`); walk-forward prices for the season's games
   (`adapters.walk_forward`); and the frozen prices from the manifest (each priced game's
   last pre-game price, `"source": "frozen"`).
5. xG by game; `schedule.json` (every GAME_CARD); the season simulation (full, current);
   `teams.json`, `season.json`, `lines.json`, `leaders.json`, `lab.json`; the award model
   (full, current) and `awards.json`; `markets.json` (full, current).
6. Game pages for the page seasons: games whose signature (status, scores, period, clock,
   OT / SO, goalies, lines, attendance, start, the number of events, the model versions,
   the build version and the xG source) changed, every missing page, and every not-final game
   of the current season in the pricing window. A page without the game's events on this
   machine keeps the old page's event-level blocks (`kept_from`) and its pre-game block.
7. The players' current blocks (full seasons), the reduced career rows, the history rows,
   the xG benchmark, the manifest; then `SeasonContext.free()`.

Then, site-wide: `calibration.json` (the backtest's `game_model` and `season_sim` blocks
kept as written by `models/backtest.py`, plus `xg` {season: {validation, benchmark, arena,
model}} merged for the seasons built this run and `xg_credit`); `history.json`; the career
files (rewritten only when their content changed, with the stats REST season reports
filling seasons without a catalogue) and `players_index.json`; and `index.json` (kept, not
overwritten, when the current season was not built). Every step runs inside `Build.step`:
an exception is logged with its traceback and the build goes on; `write_or_fail` writes
`{"ok": false, "reason"}` in place of a payload that could not be built; `Build.write`
scrubs internal builder references from every payload. The log ends with the files written,
the 25 slowest steps and up to 60 errors.

---

## 5. Payload reference

All under `docs/rink/data/`. Payloads carry `"ok": true`, `season` (per season) and
`updated_at`; probabilities 4 dp, rates per 60 2 dp, fractions 0–1. Sizes from the local
build of 1 October 2026 (23:21–23:22 UTC).

| Payload | Built by | Contents | Size and count |
|---|---|---|---|
| `index.json` | `build_rink.index_payload` | season, phase, today / live / recent (two days, ≤ 30) / upcoming (three days, ≤ 40) GAME_CARDs, playoff odds, leaders (top 10 of 7 skater and 3 goalie metrics), gaps (≥ 0.03, top 20), teams, seasons, model versions, `sim_reason` | one, 38 KB |
| `glossary.json` | `glossary.build` | metric groups with stabilisation points and units, model entries, notices | one, 44 KB |
| `calibration.json` | backtest + `build_rink.calibration` | `game_model`, `season_sim`, `xg` by season, `xg_credit` | one, meant to be committed, 19 KB |
| `history.json` | `history.build` | champions since 1917–18, titles, season leaders, league environment by season | one, 31 KB |
| `players_index.json` | `careers.write_careers` | `{pid: [name, team, pos, first, last]}` | one, 136 KB (2,429 players) |
| `players/<pid>.json` | `careers.write_careers` | career rows (with era-adjusted "plus"), current block (log, shot chart, on-ice by strength, RAPM, EDGE, linemates, deployment, projection), similar players | 2,429 files, 8.9 MB |
| `<S>/skaters.json`, `goalies.json` | `skaters.build`, `goalies.build` | the catalogues: metrics, players with values, pct, pct_pos, reference pool and floors, `xg_source`, `model_errors` | 4.1 MB and 0.16 MB a full season |
| `<S>/teams.json` | `teams.build` | units with history and percentiles, rolling 10-game shares, shot maps on the 5 ft grid, lines, deployment, goalies, sim, schedule | 1.4 MB a full season |
| `<S>/season.json` | `season.build` | standings (wild card, divisions), the tiebreak steps, simulation, lottery, bracket, ratings | 130–150 KB |
| `<S>/schedule.json` | `season.schedule` | every GAME_CARD | 0.5–0.95 MB |
| `<S>/games/<game_id>.json` | `games.build_page` | the game centre (card, pregame, linescore, shots, xG race, WP, usage, lines, box, awards) | current and previous season (CI prunes the rest); about 28 KB for a played game (1,394 pages, 39 MB for 2025–26) |
| `<S>/lines.json`, `leaders.json`, `lab.json`, `awards.json` | `leaders` | lines (≥ 20 min) league-wide; top 25 per headline metric; the column-oriented lab; races, winners, boards | 1.1 MB, 34 KB, 0.9 MB, 3 KB a full season |
| `<S>/markets.json` | `season.markets_payload` | futures, points ladders, games, awards, sources, note | current season, 65 KB |
| `<S>/value.json` | `analytics/value.season_value` via `build_rink.value_all` | skaters and goalies with GAR, WAR, parts, percentiles, best by position; rewritten only when the content changes | every season with catalogues, 90–185 KB each, 2.7 MB in all |
| `<S>/trade.json`, `<S>/needs/<abbr>.json` | `analytics/value.build_current` via `build_rink.value_all` | the trade simulator's players, clubs, curves and aging; each club's grades, strengths, weaknesses and targets | current season: 105 KB and 32 × ~13 KB |
| `<S>/manifest.json` | `build_season` | signature, frozen prices, page signatures, model errors, xG source, history rows, timings | one per season, 45–72 KB with page seasons |

`PAYLOADS.md`'s "As built" section gives every field. GAME_CARD: `game_id, date, start,
status, period, clock, home, away, hs, as, ot, so, type, series, goalies, model {p_home,
p_reg_home, p_ot, total, puck_line_home, source "game" | "frozen" | "walk_forward"}, market
{p_home, sources} | null, line {ml_home, ml_away, puck_line, total, src, open, close} | null,
wp_home, xg`.

---

## 6. How degradation shows on the page

| Missing | What the page shows |
|---|---|
| a payload file (404) | `RK.load` resolves `null`; the page shows "… is not available yet" (`RK.notBuilt`) |
| a payload with `"ok": false` | its `reason` |
| a model (`model_errors` in the manifest) | the metrics that need it are null (RAPM, value, adjusted rates, EDGE); the catalogue says which model was not available |
| the xG model for a season | the season-fitted logistic, flagged `xg_source` "fallback" |
| team strength | team units from the season's own counts (`source` "counts") |
| the live model | the Poisson fallback, `wp.source` "poisson" |
| the season simulation | standings and today's seeds by the tiebreak procedure; the odds blocks null with `sim_reason` |
| the award model | the model-free boards, with the reason per award |
| a game's events (not on this machine) | the old page's event-level blocks (`kept_from`) |
| markets (thin, unmatched, or `--no-market`) | the model alone; the card's market falls back to the de-vigged store moneyline |
| a metric's sample floor not reached | the value without a percentile |
| EDGE for a season (before 2021–22) | those panels are omitted |

---

## 7. Local preview

```bash
python scripts/build_rink.py --quick --no-market          # or a full build
cd docs/rink
python -m http.server
# open http://localhost:8000
```

The browser fetches `data/…` relative to the page, so serve `docs/rink/` itself. For the
current season without fetching, run `python scripts/nhl_hydrate.py` first.

---

## 8. Tests

```bash
uv run --group dev pytest tests/nhl        # offline
```

117 tests on 15 October 2026 (105 at `8fb8c3c` plus `test_value.py`'s 12: MODELS.md section 17.6); the list below is
the 1 October inventory (103 test functions then; the extra one over `21cce5e` is `test_live_overtime_elapsed_time`):
`test_data.py` (34: season helpers and situation codes, parsing a modern and a 2010–11 game,
coordinates normalised to attack +x, the direction fallbacks, on-ice against the situation
code and the faceoff rule, shootouts and games without shifts, stints, schedule, standings,
boxscore goalies, shift rows, partner lines, EDGE, ESPN team and event mapping, pickcenter
and core lines (a home underdog), the MoneyPuck slice and join, teams by season, formats,
arenas, the tiebreak procedure (a three-way head-to-head with an odd game, earlier steps,
eras, all tied), records and rank, divisional wild-card seeds, the store's ownership merge,
a season built from raw files, phase writes surviving periodic saves, the HTML TOI
fallback), `test_models_b.py` (17: canonical events, xG calibrated and discriminating and its
planted shape, the arena adjustment removing a planted bias, the MoneyPuck benchmark,
`score_events`, shooting and GSAx recovering planted skill, stint attribution, on-ice rates,
RAPM recovering planted effects and its multi-season prior, Rink value, lines, split-half
k, stabilise export, the committed-fit fallback), `test_models_c.py` (30: planted team
strengths, the goalie as an input, time decay and priors, goals mode, schedule context, line
parsing, the goal model's probabilities, OT and shootout logic, correlation and empty-net
effects, simulation against the analytic distribution, the fit recovering home ice and
back-to-backs, market helpers, live WP and its overtime time, the tiebreak cases, season
simulation sums and seeding, completed-season seeds against canon, bracket pairs and home
ice, the lottery matrix against the published odds, magic numbers worked by hand, the
winners table, the award logit and leader simulation, the backtest on a synthetic league,
Elo, team mapping), `test_analytics_d.py` (16: percentiles and floors, the games floor for
count metrics, game-log results, event normalisation, the tables, a teammate block, the
catalogues, teams and season, the game page and card, the Poisson WP fallback, glossary,
history and careers, the xG fallback, the markets payload), `test_build_rink.py` (6: a whole
build into a temporary data root, an isolated failing step, the index kept when the current
season was not built, an unchanged light season skipped, page seasons and `--all-games`,
`players_index.json` without careers). Fixtures in `tests/nhl/fixtures/` were recorded on 1
October 2026 (`conftest.py` lists them); `tests/nhl/rink_synth.py`, `models/synthetic_b.py`
and `models/synthetic_c.py` write synthetic seasons with planted truth. There is no automated
JS check; before committing a JS change run `node --check docs/rink/assets/js/<file>.js` where
Node is available and load the page locally.

---

## 9. Recipes

### Add a skater or goalie metric

1. Compute it in `analytics/skaters.py` `player_values` (or `goalies.py`) from the season
   tables, and add an `M(key, label, group, fmt, den=..., k=..., desc=...)` entry to the
   catalogue's `METRICS` (the denominator decides its sample floor and unit; the
   stabilisation k its shrinkage: give a `_stab` name when `stabilise.py` fits it).
2. The glossary picks it up (`glossary.build` reads the catalogues' metrics).
3. The catalogue, lab, compare and leaders pick it up from the payload; a player-page panel
   that should feature it needs `player.js`.

### The value section

Constants at the top of `analytics/value.py` (prior weight, shrinkage minutes, budgets and caps, aging shrinkage,
grade cuts, candidate floors) and `season_sim.SENS_SHIFTS` / `SENS_SIMS`. `trade.js` mirrors `apply_moves`, `interp`
and `curve_delta`: change both together and re-run a parity check (random trades through `RK.tradeModel.applyMoves`
in a headless browser against the Python; 15 Oct 2026: 300 trades, largest difference 3e-14). The sensitivity
curves are cached in `data/nhl/cache/analytics/value/sensitivity_<S>.json` on the simulation's inputs.

### Add a page

Write `docs/rink/assets/js/<page>.js` registering `RK.route('<page>', render)`, add a
`<script>` tag to `index.html` (and a nav link if wanted); add the route in `core.js`
(`addRoute`) if it takes ids. Build its payload in `analytics/` and write it from
`build_season` with `b.write_or_fail(...)`; document it in `PAYLOADS.md`.

### Change a model constant

Refit and commit the file in `oddsmarkets/nhl/models/fitted/` (MODELS.md section 14.3;
[RUNBOOK.md](RUNBOOK.md) section 4), not a constant in the code. The model versions enter
every season's signature and every game page's signature; a refit that keeps the version
string does not, so rebuild with `--force` (and `--all-games` for the page seasons). Past
seasons' payloads on the public site change only with a hand deploy (RUNBOOK section 6).
Update the Methodology's figures (`docs.js`) by hand.

---

## 10. Known gaps

1. The Methodology quotes several code defaults where the site runs on committed fits, and
   differs from the code in a few constants ([MODELS.md](MODELS.md) section 16; open).
2. Game pages exist for two seasons on the public site; older games are reachable through
   schedules, catalogues and careers only.
3. The award races are empty until the award model is fitted on the full history
   ([MODELS.md](MODELS.md) section 13.1).
4. The calibration page's backtest covers four goals-only seasons and 127 games with a
   closing line until the refit ([MODELS.md](MODELS.md) section 14).
5. The model-version map in `index.json` shows `None` for `live`, `season_sim` and
   `backtest` (those modules publish no version string), so a change to them does not move
   any signature.
