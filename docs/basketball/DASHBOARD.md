# The Quant Hardwood: the website and its build

This document covers the site at https://pchattani.github.io/the-quant-hardwood/:
how the front-end is put together, every page and the payloads it reads, the build
that writes them, and how to add to it. `oddsmarkets/basketball/PAYLOADS.md` is the
field-level contract between the Python builder and the JS; this document does not
repeat every field, and notes where `PAYLOADS.md` and the code differ.

| Section | Covers |
|---|---|
| 1 | architecture |
| 2 | the front-end: files, the `HW` namespace, routes, loading, header and search |
| 3 | pages |
| 4 | the build: `scripts/build_hardwood.py` |
| 5 | payload reference |
| 6 | how degradation shows on the page |
| 7 | local preview |
| 8 | tests and the JS syntax check |
| 9 | recipes: a metric, a page, a model constant |
| 10 | known gaps |

---

## 1. Architecture

```
docs/hardwood/                        rsynced to pchattani/the-quant-hardwood (minus plain shots/stints.json)
├── index.html                        the shell: header (league switch, season picker, nav, search, sister
│                                     sites), <main id="app">, footer, first-visit notice, disclaimer route
├── .nojekyll                         stops Pages' Jekyll from hiding files
├── assets/
│   ├── base.css                      copied by every build from docs/site/assets/style.css (football's look)
│   ├── hardwood.css, pages.css,      basketball and page styles
│   │   pages-f.css
│   └── js/                           sixteen modules, no bundler (section 2.1)
└── data/
    ├── index.json, glossary.json     site-wide
    └── <L>/                          nba | wnba
        ├── history.json, lab.json, markets.json, calibration.json (committed)
        ├── players/<pid>.json        career files (NBA 1,167 and WNBA 974 locally on 1 Oct 2026)
        └── <S>/                      per season
            ├── store.json, recon.json, shots.json.gz, stints.json.gz      inputs (section 8 of DATA_PIPELINE)
            ├── season.json, schedule.json, teams.json, players.json,
            │   awards.json, shots_league.json                             payloads
            ├── games/<gid>.json                                           game pages (three latest seasons)
            └── manifest.json, pbp_summary.json.gz                         build bookkeeping
```

Everything under `data/` except the inputs is written by `scripts/build_hardwood.py`.
The page is a static shell: every module fetches JSON from `data/` and renders into
`<main id="app">`. There is no server and no build step for the front-end. Plotly 2.27
loads from cdn.plot.ly. No browser code calls ESPN, Kalshi or Polymarket; every price
is fetched at build time.

---

## 2. The front-end

### 2.1 Files

| File | Lines | Job |
|---|---|---|
| `core.js` | 1,055 | namespace `window.HW`, state, routing, cached loading, formatting, names and colours, game cards, HTML helpers, header, search, meta line |
| `charts.js` | 540 | `HW.charts`: the court drawn in feet (`court(L)`), shot charts, flow and win-probability charts, reliability diagrams |
| `fx.js` | 447 | `HW.fx`: shared helpers for the catalogue pages (rows from payloads, metric formatting, zone labels, hex grids) |
| `hub.js` | 225 | `#/` and `#/<L>` |
| `season.js` | 292 | `#/<L>/season/<S>` |
| `game.js` | 400 | `#/<L>/game/<gid>` and `#/<L>/games[/<date>]` |
| `playoffs.js` | 145 | `#/<L>/playoffs` |
| `markets.js` | 178 | `#/<L>/markets` |
| `players.js` | 330 | `#/<L>/players`, `#/<L>/player/<pid>` |
| `teams.js` | 259 | `#/<L>/teams`, `#/<L>/team/<tid>` |
| `leaders.js` | 119 | `#/<L>/leaders` |
| `awards.js` | 121 | `#/<L>/awards` |
| `lab.js` | 254 | `#/<L>/lab` |
| `compare.js` | 293 | `#/<L>/compare[/players|teams/<a>/<b>]` |
| `calibration.js` | 181 | `#/<L>/calibration` |
| `docs.js` | 181 | `#/glossary`, `#/methodology` (the Methodology text is one long string, about 99 KB) |
| `value.js` | 190 | `#/<L>/value` (player value, best by position, leaderboard, valuation over four seasons) |
| `moves.js` | 230 | `#/<L>/moves` (trade ratings, transactions feed, pick values) and `HW.movesLedger` (team page) |
| `fantasy.js` | 320 | `#/<L>/fantasy` (projections, 9-category and points, punts, tiers, VORP, schedule, luck, picks, backtest) |
| `trade.js` | 303 | `#/<L>/trade` (the trade simulator; `HW.tradeModel` exposes its depth chart) |

`index.html` loads them in the order above (core, charts, fx, then the pages) and
registers `#/disclaimer` inline.

### 2.2 The `HW` namespace

`core.js` exposes one object (its `return {...}` at the end lists everything):

- **state and routing**: `state {league, season, route, params}`, `route(name, fn)`,
  `go`, `onLeave`, `interval` (cleared on navigation), `switchLeague`, `setSeason`,
  `setMeta`;
- **data**: `load(path)` (fetch once per page life, `cache: 'no-cache'`, `null` on a
  missing payload), `loadAll`, `ok(d)` (`d.ok !== false`), `reason(d)`, `path(file, L,
  S)` → `L/S/file`, `loadSeason`, `lpath`, `index()`, `currentSeason(L)`, `seasons(L)`,
  `phase(L)`;
- **formatting**: `num`, `pct`, `signed`, `pp`, `fmtSec`, `fmtMin`, `fmtDate`,
  `fmtTime`, `countdown`, `fmtSpread`, `american`, `decimal`, ...;
- **names, colours, links**: `teamName`, `teamColour(L, tid)`, `teamLink(L, tid)`,
  `playerLink(L, pid)`, `gameLink(L, gid)`, `href`, ... (when the first argument is not
  a league, the current league is used);
- **games**: `gameState`, `periodLabel`, `statusChip`, `stypeLabel`, `gameCard`,
  `simTeams`, `titleProbs`;
- **HTML**: `card`, `muted`, `chip`, `notBuilt`, `tableHTML`, `sortable`, `pctPill`,
  `statTile`, `probCell`, `edgeHTML`, `toggles`, `pageHead`;
- **charts**: `plot`, `layout`, `PALETTE`, `C` (colours), `DARK_LAYOUT`, `PLOTLY_CONF`;
  `charts` is filled by `charts.js`.

Every payload the loader reads also teaches `HW.NAMES` the teams and players it
mentions (`learn`), which feeds search and links.

### 2.3 Routes

```
#/                              hub (league = last viewed, localStorage "qh-league", default nba)
#/<L>                           hub
#/<L>/season/<S>                season          (#/<L>/season -> current season)
#/<L>/games[/<YYYY-MM-DD>]      games           (a date list; ?s=S for another season)
#/<L>/game/<gid>                game centre
#/<L>/team/<tid>  #/<L>/player/<pid>
#/<L>/players  teams  leaders  awards  playoffs  lab  markets  calibration
#/<L>/value                     player value (?pos=G|W|B&team=&min=&q=0|1&n=)
#/<L>/trade                     trade simulator (?t=<tid>,<tid>[,<tid>]&m=<pid>-<to tid>.<pid>-<to tid>)
#/<L>/moves                     transactions and trade ratings (?tab=ratings|feed|picks&basis=now|time&team=&type=)
#/<L>/fantasy                   fantasy (?fmt=9cat|standard|simple|daily|custom&hz=pg|ros|w0|w1&punt=fg,ft,...)
#/<L>/compare                   compare (pickers)
#/<L>/compare/players/<a>/<b>   compare-players (falls back to 'compare')
#/<L>/compare/teams/<a>/<b>     compare-teams   (falls back to 'compare')
#/glossary  #/methodology  #/disclaimer   (global; a league prefix is accepted and kept)
```

The season comes from the route, else a `?s=<S>` query, else the league's current
season (`index.json`). Links carry `?s=` when the season shown is not the current one.
Aliases: `home`, `index`, `league` → hub; `schedule`, `scores` → games; `bracket` →
playoffs; `docs` → methodology.

### 2.4 Header, search, disclaimer

The header carries the name "The Quant Hardwood" and the tagline "Odds, models and
analytics for the NBA and WNBA", the league switch, the season picker, the nav (Hub,
Season, Games, Teams, Players, Value, Trade, Moves, Fantasy, Leaders, Awards, Playoffs, Lab, Compare, Markets,
Calibration, Glossary, Methodology), the meta line ("Updated" from `index.json`) and
links to the two sister sites (`FOOTBALL_URL`, `PADDOCK_URL` in `core.js`). Search
covers the current league's teams and players that the loaded payloads have named.
The first-visit notice is stored under `localStorage` key `qh-notice-v1`; the footer
and `#/disclaimer` say the site is not affiliated with the NBA, the WNBA, any team or
player, ESPN or a bookmaker, uses no logos, and offers no bets.

---

## 3. Pages

### 3.1 Hub (`#/`, `#/<L>`, `hub.js`)

Reads `index.json`, `<L>/<S>/season.json`, `markets.json`, `awards.json`. A band with
the league, season and phase, a countdown to the next tip-off (ticking every second)
or the number of games live, KPI tiles (title favourite, best team by net rating, MVP
favourite); today's and live games with model against market (moneyline, spread,
total) and live win probability, else the next games, then recent results; key
upcoming games (ranked by how much each result moves playoff or title odds, from
`sim.teams[tid].next.if_win` / `if_loss`); title odds against the market; power
ratings; the award race; a standings snapshot.

### 3.2 Season (`#/<L>/season/<S>`, `season.js`)

Reads `season.json`, `markets.json`, `history.json`. A champion banner for finished
seasons; standings per conference (or the league) with projected wins, playoff /
play-in / title odds and magic numbers; the seed-distribution heatmap; team ratings
(offence, defence, net ± se, pace, Elo); Kalman rating paths with a ± 1 se band for a
picked team; win totals (the simulated distribution against the Kalshi line; edges
hidden while `phase == "preseason"`); schedule difficulty; statistical leaders.

### 3.3 Games and the game centre (`#/<L>/games`, `#/<L>/game/<gid>`, `game.js`)

The games list reads `schedule.json` by date. The game centre reads
`<L>/<S>/games/<gid>.json`: the head (teams, score, status, line score, series, venue);
pregame (the model against the market: win %, spread, total; Elo; the margin broken into
rating, home court, rest, travel, time zones, altitude and injuries; the injury report
with each player's impact); the six game awards; the box score with advanced columns
(TS%, usage, Game Score, WPA, points over xPTS); four factors; the margin flow; win
probability (ours and ESPN's, top plays marked); shot charts per team (make/miss,
xPTS, hexes against the league, zones); lineups; the rotation chart; the play list of
the top-leverage plays and every 4th-quarter and overtime scoring play with WPA.

### 3.4 Playoffs (`#/<L>/playoffs`, `playoffs.js`)

Per round, the most likely match-ups (projected) or the actual series once set, each
with the chance it happens and the home-court team's series win probability; series
scores from the game cards when the playoffs are live; `p_reach` per team for every
round and the title; a champion banner for finished seasons.

### 3.5 Players (`#/<L>/players`, `#/<L>/player/<pid>`, `players.js`)

The catalogue reads `players.json`: every player with a game, filterable by pool, team
and qualification, with league and pool percentiles. The player page reads
`<L>/players/<pid>.json` (career by season, the current season's game log, shot chart
on 1.5 ft hexes against the league, zones and types, on/off, top lineups, clutch,
projection, HPM with its RAPM and box parts and the weight on RAPM, award odds,
similar players, career awards), plus `teams.json` and `awards.json`. The `current`
block exists only for players in a season built in full on the building machine.

### 3.6 Teams (`#/<L>/teams`, `#/<L>/team/<tid>`, `teams.js`)

Reads `teams.json`, `season.json`, `players.json`: the 76-metric catalogue with
percentiles and ranks, the game log (regular season) with the Kalman net after each
game and the pregame model probability, roster with HPM, 5-man lineups with shrunk net
and 2- and 3-man units, the rotation matrix, on/off, shot profiles for and against
(the defensive map mirrored so red is always good for the team shown), injuries and
season odds against the market.

### 3.7 Leaders, Awards, Lab, Compare

- **Leaders** (`leaders.js`): `season.json` leaders (pts, reb, ast, stl, blk, 3pm per
  game; HPM; TS among qualified players) and a ranked table of any catalogue metric with
  games and minutes floors and a per-game / per-36 / per-100 / total switch.
- **Awards** (`awards.js`): `awards.json` keys in order: the model's P(win) and P(top 3),
  the market's de-vigged price matched by player id or folded name, the edge, the
  features behind each candidate, eligibility under the NBA's 65-game rule, and the fit
  (`fitted`, `n_seasons`, `top1`). Where the award has been announced, `winner`
  (`{"names", "ids"}`, from `models/award_winners.py`, ids resolved by folded name in
  the season's players) is shown on the race button, above the chart with the model's
  probability for the winner, and as a "winner" tag in the candidates table.
- **Lab** (`lab.js`): `lab.json` (column-oriented, every season with box data); any two
  metrics for one season or a window, filtered by pool and minutes, presets, size by
  minutes, colour by team, pool, season or a metric, quadrant medians, labelled
  outliers, and optional shrinkage of rates to the pool median with a 300-minute prior.
- **Compare** (`compare.js`): two players (verdict strip by percentiles, radar, the full
  catalogue, shot charts side by side, career HPM, head to head) or two teams (the same
  plus rating paths, four factors, shot profiles at both ends, lineups and the season
  series).

### 3.8 Markets (`#/<L>/markets`, `markets.js`)

Reads `markets.json`, `season.json`, `awards.json` and the games list: futures
(champion, conference titles, awards, win totals, playoffs and play-in yes/no) model
against market with edges; the next three days' games (model win %, spread, total
against the market and its basis); a note on de-vigging, thin and one-sided markets and
what an edge means. Win-total edges are hidden while `phase == "preseason"`.

### 3.9 Calibration (`#/<L>/calibration`, `calibration.js`)

Reads `<L>/calibration.json`: coverage, a plain-words reading generated from the numbers,
the scores (log-loss, Brier, margin RMSE; all games and the games with a market line;
"skill v base rate" = 1 − log-loss / H, H the log-loss of always forecasting the home win
rate), reliability diagrams with ± 2 binomial se, the season simulation's calibration,
the parameters by season, live win probability against ESPN's, and the shot model by
zone (`shots.by_zone`).

### 3.11 Value, strengths and needs, trade (`value.js`, `teams.js`, `trade.js`)

Built 15 October 2026 to `docs/VALUE_SECTIONS.md`; the models are in [MODELS.md](MODELS.md) section 14.

- **Value** (`#/<L>/value`, `value.js`): reads `<L>/<S>/value.json`; when the season has no regular-season game yet
  (NBA 2026-27 preseason) it shows the previous season with a note. A head card defines WAR (with the season's
  points per win and pace); tiles for the most WAR and the best guard, wing and big; "best at each position" (top ten
  qualified per group with WAR, HPM, percentile and a "why" line: O/D split and the box skills at the 80th
  percentile or better); a leaderboard filtered by position group, team, minimum minutes and the qualification
  floor, sortable, with WAR, PAR per game, HPM, O, D, percentiles, ΔHPM and last season's WAR; an HPM-against-minutes
  scatter. Filters write the hash with `history.replaceState`.
- **Team page "Strengths and needs"** (`teams.js` `drawNeeds`, current season only): reads `<L>/<S>/needs/<tid>.json`:
  the grade table (area, letter, projected WAR, rank, percentile), the three strengths and weaknesses with evidence,
  and for each weakness the trade targets as cards (gain, wins, playoff and title odds change, hints, an
  "attainable" badge, a "Try in the trade simulator" link that opens `#/<L>/trade?t=<tid>,<seller>&m=<pid>-<tid>`),
  then the honest-labelling note (no salaries, cap not checked, free agents not identified).
- **Trade** (`#/<L>/trade`, `trade.js`): reads `<L>/<current S>/trade.json` (always the current season). Team pickers
  (two, or three with "Add a third team"), each roster (rotation first, the rest folded) with a tick box (a "to"
  select with three teams); per team: the verdict line ("wins now / weakens now / about even now" by ±0.5 wins over
  the rest of the season, or title odds once the regular season is over; "long-term gain / cost" by ±0.5 WAR next
  season), players in and out, tiles (rating change with offence and defence, wins from the `exp_w` curve,
  WAR in − out over the games left, next season's WAR), the odds table (now, after, change: playoffs, top six,
  Finals, title, top-four pick), who loses minutes to the newcomers, the next players up, replacement minutes, and
  the rotation before and after. State lives in `?t=&m=` (written with `history.replaceState`; "Copy link" copies
  it). Without a simulation it shows wins over a full season and no odds.

### 3.10 Glossary and Methodology (`docs.js`)

The glossary reads `glossary.json` (`analytics/glossary.py`; a test checks every catalogue
key has an entry) and falls back to the catalogues' own metric lists. The Methodology is
static text whose constants were read from the code; [MODELS.md](MODELS.md) section 13
lists where it has fallen behind.

---

## 4. The build: `scripts/build_hardwood.py`

```
python scripts/build_hardwood.py                                   # every league: current full, the rest light
python scripts/build_hardwood.py --leagues wnba --seasons 2026
python scripts/build_hardwood.py --leagues nba --seasons 2027 2026 --sims 20000
python scripts/build_hardwood.py --quick --no-market --no-light    # fast local check
```

| Flag | Default | Effect |
|---|---|---|
| `--leagues` | both | |
| `--seasons` | each league's current season | seasons built in full |
| `--sims` | 20,000 | season simulations (`--quick`: at most 400) |
| `--no-market` | off | skip Kalshi and Polymarket |
| `--no-light` | off | build only the full seasons |
| `--no-careers` | off | skip `players/<pid>.json` |
| `--games-recent` | 3 | in a full season, also rebuild game pages within N days of today |
| `--all-games` | off | rebuild every game page |
| `--game-page-seasons` | 0 (every season) | game pages only for each league's N most recent seasons on disk; CI passes 3 |
| `--force` | off | rebuild light seasons whose inputs are unchanged |
| `--no-light-awards` | off | skip `awards.json` for light seasons |
| `--today` | UTC today | |
| `--data`, `--cache`, `--pbp` | `HARDWOOD_DATA`, `HARDWOOD_CACHE`, `HARDWOOD_PBP` | roots |

**Order**: copy `base.css`; `glossary.json`; per league: the Elo history; each season in
date order (full or light, `build_season`); then `history.json`, `lab.json`,
`calibration.json`, `markets.json` (current season only) and the career files; finally
`index.json` (a league whose current season was not built this run keeps its previous
entry). Every step runs in `Build.step`: an exception is logged with its traceback and
recorded, and `write_or_fail` writes `{"ok": false, "reason": "<step> could not be built
(see the build log)"}` in place of the payload. The log ends with the 15 slowest steps
and the errors.

**One season** (`build_season`, through `analytics/context.SeasonContext`, which loads
each input and model lazily and leaves any piece that fails empty):

1. **Skip test** (light seasons): when the manifest's `sig` equals the current one and
   `players.json` exists, the season is skipped. `season_sig` = the build version, the
   SHA-1 of `store.json`, `shots.json` and `stints.json` (read through the `.gz` when
   that is the newer file) and the number of raw play-by-play files for the season.
   Because the raw-file count is part of it, a season built on a machine with raw files
   is rebuilt once on a machine without them (CI), and is then skipped again.
2. **The play-by-play pass** (`analytics/pbpx.season_pass`): when raw files exist, every
   final game is parsed and scored for WPA once, the per-game summaries are cached in
   `pbp_summary.json.gz` (keyed on the fetch stamp and the WP model), and the game pages
   that are due are written from the parse. Without raw files the cached summaries are
   reused, so CI keeps the play-by-play catalogue metrics of past seasons.
3. **The other game pages**: a page is due when its signature changed (`page_sig`: build
   version, `winprob.MODEL_VERSION`, `pbpx.VERSION`, the game's fetch stamp, status,
   score, whether it has a box, whether its raw file is here), when the file is missing,
   or, in a full season, for unplayed games within `--games-recent` days and games that
   finished in the last day. A page with play-by-play blocks is never replaced by one
   built without the raw file. Pages are written only for seasons within
   `--game-page-seasons`.
4. `players.json`, `teams.json`, `season.json` (with the simulation in a full season
   not in the offseason), `schedule.json`, `awards.json`, `shots_league.json`; in a full
   season, ratings fitted through seven days ago for the power-ranking change, and the
   players' `current` blocks.
5. `manifest.json`: `sig`, `built_at`, `full`, `games` (page signatures), `phase`.

The season's phase (`season_phase`): `preseason` (no counted game played), `regular`
(regular-season or Cup games pending), `playin`, `playoffs`, `offseason`; pending
games more than three days in the past are ignored as stale. The simulation is skipped
in the offseason and for light seasons.

---

## 5. Payload reference

Field-level detail is in `PAYLOADS.md`; what builds each file:

| Payload | Built by | Notes |
|---|---|---|
| `index.json` | `analytics/season.league_index` | per league: name, current season, seasons, phase, today / next 3 days / last 2 days game cards, teams, champions |
| `glossary.json` | `analytics/glossary.build_glossary` | |
| `<L>/history.json` | `analytics/season.history` | champions, runners-up, MVP, best record, all-time Elo peaks; from the stores, so champions exist only where a postseason is final in the store (WNBA from 2003 on 1 Oct 2026), while `first_season` is the first store on disk |
| `<L>/lab.json` | `analytics/season.lab_payload` | players with at least `LAB_MIN_SHARE = 0.5` of the minutes floor |
| `<L>/markets.json` | `analytics/season.markets_payload` | current season only |
| `<L>/calibration.json` | `analytics/season.calibration` | the cached backtest, else the committed copy; plus `winprob` and `shots` blocks |
| `<L>/players/<pid>.json` | `build_hardwood.careers`, `analytics/players` | `current` kept from the file on disk when this run did not build it |
| `<L>/<S>/season.json` | `analytics/season.build_season` | `sim` null for light or offseason seasons |
| `<L>/<S>/schedule.json` | `build_hardwood.schedule_payload` | every game as a GAME_CARD |
| `<L>/<S>/games/<gid>.json` | `analytics/games.build_game` | pregame, box, flow, wp, shots, lineups, rotation, plays, awards |
| `<L>/<S>/teams.json` | `analytics/teams.build` | 76 metrics |
| `<L>/<S>/players.json` | `analytics/players.build` | 125 metrics; `min_floor = MIN_FLOOR_SHARE (0.2) ×` the season's most minutes |
| `<L>/<S>/awards.json` | `analytics/awards.build` | `keys` lists the awards; `sixth` is the model's `6moy`; `<award>.winner` once announced |
| `<L>/<S>/shots_league.json` | `build_hardwood.shots_league` | `{"ok": false}` for seasons without shots |
| `<L>/<S>/value.json` | `analytics/value.season_value` via `build_hardwood.value_seasons` | every season with a catalogue; rewritten only when its content (not `updated_at`) changes (`Build.write_if_changed`); 25–90 KB a season, about 3.2 MB for both leagues |
| `<L>/<S>/trade.json` | `analytics/value.build_current` via `build_hardwood.value_current` | current season only; NBA 72 KB, WNBA 29 KB |
| `<L>/<S>/needs/<tid>.json` | the same | current season only, one per team, about 10 KB each |
| `<L>/<S>/manifest.json`, `pbp_summary.json.gz` | the build | bookkeeping, not read by the front-end |

Conventions (`PAYLOADS.md`): probabilities 4 decimals, ratings 2, rates 3; fmt "pct" and
"prob" values are 0–1 fractions; `t` is elapsed game seconds; box `min` is decimal
minutes; a play's `wpa` is the acting team's change in win probability, `dwp_home` the
home team's.

Game awards (`analytics/games.py`): player of the game (max Game Score + 20 × WPA),
biggest swing (largest |change in home WP|), shot maker (max points over xPTS, 5+
shots), unluckiest (the team whose margin fell furthest below its expected margin from
xPTS and made free throws), stopper (max defensive WPA), plus excitement and comeback.
Constants: `MAX_PLAYS = 60`, `MAX_WP_POINTS = 400`, `WP_STEP = 0.004`, `MAX_UNITS = 12`.

---

## 6. How degradation shows on the page

| Situation | What the page shows |
|---|---|
| A payload is `{"ok": false, "reason"}` | a muted card with the reason (`HW.notBuilt`) |
| A payload file is missing | "not built yet" |
| A box-only game (no play-by-play) | flow, win probability, shots, lineups, rotation and plays are absent; the box and pregame remain |
| A play-by-play game whose raw file was not on the building machine | shots, lineups and rotation (from the derived tables) without flow, win probability and plays |
| A game older than each league's three latest seasons | no game page (pruned); the game stays in schedules, logs and catalogues |
| A light season | no simulation: standings without odds; awards and catalogues still built |
| Catalogue metrics with scope "pbp" in a season without play-by-play | null, shown as "—" with no percentile |
| `players/<pid>.json` with `current: null` | career only |
| Preseason | win-total edges hidden on Season and Markets |
| A thin or settled market | the market column says why ("thin: ...", "settled: ...") |

---

## 7. Local preview

```bash
uv run python scripts/build_hardwood.py --quick --no-market       # or a full build
cd docs/hardwood
python -m http.server 8897
# open http://127.0.0.1:8897
```

Use a port no other site preview uses (the F1 runbook uses 8898, football 8899). The
browser caches nothing across reloads (`cache: 'no-cache'`), but each payload is loaded
once per page life.

---

## 8. Tests and the JS syntax check

```bash
uv run --group dev pytest tests/basketball
```

164 tests (15 Oct 2026; 148 before the value section) in the files below, offline: `test_data.py` (ESPN parsing on recorded
fixtures, the store, the play-by-play reconstruction), `test_models_b.py` (ratings,
game model, season simulation, Elo, backtest on synthetic stores), `test_models_c.py`
(xPTS, RAPM, HPM, win probability, WPA identities, awards), `test_markets_b.py`
(markets on canned payloads, never raising without network), `test_analytics_d.py`
(percentiles, phases, lineups and on/off, catalogues, the season payload, glossary
coverage, the game centre from recorded play-by-play, WPA team sums, the `.gz` loaders,
the ESPN predictor), `test_build_hardwood.py` (a build into a temporary data root,
step isolation, light seasons skipped when unchanged, game pages never downgraded), `test_value.py`
(player value, position groups, the depth chart, grades, trade targets, sensitivity curves; MODELS.md section 14.7).

The JS has no test suite. A syntax check per module:

```bash
uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/hardwood/assets/js/core.js',encoding='utf-8').read())"
```

---

## 9. Recipes

### Add a player or team metric

1. Compute it in `analytics/players.py` (or `teams.py`) and add a `metric(key, label,
   group, fmt, lower, scope, desc)` entry to `METRICS`; scope "pbp" if it needs
   play-by-play.
2. Add a glossary entry in `analytics/glossary.py` (`PLAYER` or `TEAM`); the test fails
   without it.
3. Rebuild with `--force` so light seasons pick it up. The catalogue pages, leaders, the
   lab and compare render it from `METRICS` with no JS change.

### The value section

- Constants live at the top of `analytics/value.py` (replacement, prior minutes, the minutes cap, grade cuts,
  candidate floors) and `season_sim.SENS_SHIFTS` / `SENS_SIMS`. `trade.js` mirrors `apply_moves`, `interp` and
  `curve_delta` line for line: change both together and re-run a parity check (random trades through
  `HW.tradeModel.applyMoves` in a headless browser against the Python; 15 Oct 2026: 300 trades, largest difference 3e-14).
- The sensitivity curves are cached in `data/basketball/cache/value/sensitivity_<L>_<S>.json` on the simulation's
  inputs; bump `value.VERSION` to force a recompute.

### Add a page

1. A new `assets/js/<name>.js` that calls `HW.route('<name>', fn)`; add its `<script>` tag
   to `index.html` after `fx.js`.
2. If the route has a new shape, add it to `ROUTES` in `core.js` (`addRoute`), and a nav
   link with `data-nav` in `index.html` and `NAV_OF` / `TITLES` in `core.js`.
3. Document its payload in `PAYLOADS.md`.

### Change a model constant

Change it in the model file; bump the model's version string (`MODEL_VERSION` in
`shots.py`, `impact.py`, `winprob.py`, `awards.py`; `VERSION` in `ratings.py`,
`game.py`, `elo.py`) so the caches refit; a change to how win probability or WPA is
computed must bump `winprob.MODEL_VERSION` or `pbpx.VERSION` so game pages rebuild.
Update the Methodology (`docs.js`) and [MODELS.md](MODELS.md).

---

## 10. Known gaps

- **Preseason win-total edges are hidden**: the preseason prior is last season only; the
  roster-aware prior is built but off, because it widened the gap to the Kalshi win totals
  (HANDOFF Task 18, [MODELS.md](MODELS.md) section 2.2).
- **Ages** exist only for players on a current roster; retired players' are null.
- **The Methodology has fallen behind the code** in several places ([MODELS.md](MODELS.md)
  section 13).
- **Live games update hourly**, with the workflow; nothing on the site polls ESPN.
