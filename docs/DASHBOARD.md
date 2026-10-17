# The Quant Footballer: the website and its build

The Quant Footballer (previously "Football Analytics Hub") is the public football
site in this repo. It covers 69 competitions (leagues, continental and world cups,
national cups, super cups and national-team competitions) and publishes scores,
fixtures, Monte Carlo season probabilities, fair odds, club, player and match
analytics, and a set of cross-competition pages. It is served from GitHub Pages at
**https://pchattani.github.io/the-quant-footballer/**.

This document is for an engineer changing the front-end or the build, and for the
repo owner. Every route, payload name and field listed here was checked against the
code; file paths are relative to the repo root.

Contents

1. [Architecture](#1-architecture)
2. [The front-end](#2-the-front-end)
3. [Pages and tabs](#3-pages-and-tabs)
4. [The build](#4-the-build)
5. [Payload reference](#5-payload-reference)
6. [How degradation shows on the page](#6-how-degradation-shows-on-the-page)
7. [Local preview and screenshots](#7-local-preview-and-screenshots)
8. [Tests and the JS syntax check](#8-tests-and-the-js-syntax-check)
9. [Recipes: a tab, a metric, a global page](#9-recipes-a-tab-a-metric-a-global-page)
10. [Known gaps](#10-known-gaps)
11. [Legacy sites](#11-legacy-sites)

---

## 1. Architecture

```
Sofascore stores (docs/site/data/<slug>/store.json, docs/liga/data/liga_store.json,
                  docs/site/data/{archive,squads,past}/store.json)
        │   refreshed from a residential connection (scripts/refresh_sofascore_all.ps1)
        ▼
scripts/build_site_all.py ──► scripts/build_site_liga.py   (Argentina, run in-process)
        │                ├──► scripts/build_site_global.py (pool, global players,
        │                │                                  careers)
        │                └──► build_unified() → analytics/unified.py (people, clubs,
        │                                                   seasons; run last)
        ▼
docs/site/data/**.json     (JSON only: no HTML is generated)
        +
docs/site/index.html, docs/site/assets/{style.css, js/*.js, crests/*.png}
        │   (hand-maintained, shipped verbatim)
        ▼
.github/workflows/update_site.yml: hourly build, rsync docs/site/ → the public
Pages repo (vars.SITE_REPO) → https://pchattani.github.io/the-quant-footballer/
```

- **No template engine and no front-end build step.** The build scripts write only
  JSON. `docs/site/` is the web root as-is.
- **Everything is relative.** The page fetches `data/...` and loads `assets/...`
  with relative paths and routes with the URL hash. That is why it works unchanged
  under the `/the-quant-footballer/` sub-path on GitHub Pages and from
  `python -m http.server` locally. Do not introduce paths that start with `/`.
- **Every competition degrades independently.** A missing store, a failed build or
  a missing payload removes one competition or one section, never the site (see
  [section 6](#6-how-degradation-shows-on-the-page)).

---

## 2. The front-end

### 2.1 Files

| File | Role |
|---|---|
| `docs/site/index.html` | The static shell: header (site title, search box, competition picker, global nav), the tab bar `#mainTabs`, `#stale-banners`, and one `div.tab-pane` per tab (`#tab-home`, `#tab-overview`, … `#tab-compare`, `#tab-page`). Loads Plotly 2.27 from `https://cdn.plot.ly/plotly-2.27.0.min.js`, then the five scripts in this order: `core`, `charts`, `tabs`, `pages`, `global`. |
| `docs/site/assets/style.css` | Dark theme. Colours are CSS custom properties on `:root` (`--bg`, `--text`, `--blue`, `--pb-h`/`--pb-d`/`--pb-a` for the home/draw/away bar…); responsive breakpoints are plain `@media (max-width: …)` rules. |
| `docs/site/assets/js/core.js` | Defines `window.FH`: state, formatting helpers, crests and links, table builder, percentile sliders, routing, payload loading and caching, the meta line and banners, search, and `init()`. |
| `docs/site/assets/js/charts.js` | Plotly wrappers: `plot`, `layout`, `pitchShapes`, `renderShotMap`, `renderXgRace`, `renderMomentum`, `renderRadar`, `renderProbBars`. |
| `docs/site/assets/js/tabs.js` | The competition tabs. Registers `RENDERERS` (overview, table, fixtures, zones, bracket, anual, relegation, probs, power, team, players, matches, market, history, methodology) and exports shared pieces (`fixtureRow`, `fixtureDetailRow`, `standingsTable`, `teamHeadline`, `RADAR_OUT`, `RADAR_GK`). |
| `docs/site/assets/js/pages.js` | The hub renderer (`RENDERERS.home`) and the club and player pages (`PAGES.team/player`; the match page moved to `match.js`, with `PAGE_NEEDS`). |
| `docs/site/assets/js/global.js` | The pages above the competitions (`GLOBAL_PAGES.clubs/nations/leaders/compare/career`) and the in-browser Dixon-Coles pricer (`FH.dcMatrix`, `FH.matchCard`). |
| `docs/site/assets/js/match.js` | The match centre (`PAGES.match`, overriding nothing else): summary, expected result, full-pitch shot map with filters, goal-mouth views, xG race, timeline, chance creators, team sheet, drawn formations, player table. Loaded after `global.js`. |
| `docs/site/assets/js/lab.js` | The Player lab (`GLOBAL_PAGES.lab`): scatters of any two metrics by position, within a competition or across all of them, from `players_lab.json`. Loaded last. |
| `docs/site/assets/js/analytics.js` | The per-competition Analytics tab (`RENDERERS.analytics`, registered through a hoisted shim in tabs.js because analytics.js loads later) and the shared XI drawing (`FH.drawXI`, `FH.xiPoints`, `FH.halfPitchVertical`, `FH.ratingColor`). Styles in `analytics.css`. |
| `docs/site/assets/js/docs.js` | The glossary (`GLOBAL_PAGES.glossary`, `FH.glossaryLink`) and the methodology document (`FH.renderMethodologyDoc`, used both by `#/methodology` and by each competition's Methodology tab through `renderMethodology` in tabs.js). Styles in `docs.css`. |
| `docs/site/assets/js/hub.js` | The hub (`RENDERERS.home`; loaded last, replacing the earlier hub in pages.js): header band, scoreboard, competition cards by family, title races, leaders and national-team teasers. Styles in `hub.css`. |
| `docs/site/assets/js/value.js` | Player value (`GLOBAL_PAGES.value`, `#/value`), the transfer simulator (`GLOBAL_PAGES.transfer`, `#/transfer`) and the club page's "Strengths and needs" card (`FH.renderClubNeeds`, called from `people.js`). Loaded last. Styles in `value.css` (football-only; `style.css` is untouched because the sister sites copy it as their base). |
| `docs/site/assets/crests/<team_id>.png` | Club crests, referenced from payloads as `assets/crests/<id>.png` (`crest_path()` in `scripts/build_site_all.py` only emits a path when the file exists). |

### 2.2 The FH namespace and the module split

`core.js` is an IIFE that returns the `FH` object; every other module is
`(function (FH) { ... })(window.FH)`, destructures what it needs from `FH`, and
attaches its own exports. The load order in `index.html` matters because each
module destructures exports of the ones before it (for example `pages.js` takes
`fixtureRow`, `teamHeadline` and `RADAR_OUT` from `tabs.js`). A test asserts the
order (section 8).

What `core.js` exports: `INDEX, CACHE, STATE, DARK_LAYOUT, PLOTLY_CONF, C, PALETTE,
TAB_LABELS, ROUND_LABELS, STAGE_LABELS, FAMILY_LABELS, CORE, NEEDS, FILES, FALLBACK`,
the helpers (`fetchJSON, pct, esc, num, signed, fmtNum, fmtMetric, fmtDate, fmtTime,
fmtStamp, localDay, parseDate, slugify, D, comp, kind, cupKind, crest, teamHref,
teamLink, playerLink, matchHref, makeSortable, tableHTML, setHTML, sortableIn,
wireRowLinks, statTile, formChips, resultClass, riskClass, bandClass, bandColor,
pctColor, pctPill, pctRow, probBar, statusChip, scoreText`), the router and loaders
(`parseHash, navigate, route, ensure, loadShard, loadSite, activateTab, openPage,
updateMeta, tabLabel, showPane`) and four empty registries the other modules fill:
`RENDERERS`, `PAGES`, `PAGE_NEEDS`, `GLOBAL_PAGES`.

Useful accessors: `FH.D()` is the open competition's loaded payloads
(`CACHE[STATE.current].data`), `FH.comp()` its manifest entry, `FH.kind()` its
`kind` and `FH.cupKind()` its `cup_kind`.

Rendering conventions:

- Tables go through `tableHTML(cols, rows, opts)`; each cell carries `data-v` so
  `makeSortable` sorts numerically where it can. `sortableIn(id)` wires a pane's
  table; `wireRowLinks(id)` makes rows with `_href` navigate.
- Charts go through `plot(id, traces, layout(...))`. When Plotly failed to load,
  `plot` writes "The chart library did not load. The tables carry the same data."
  into the chart box instead of throwing.
- Every renderer runs inside `safeRender`, which catches an exception and prepends
  "This section could not be shown: …" to the pane.

### 2.3 Routes

`parseHash()` in `core.js` reads `location.hash`; `route()` runs on load and on
every `hashchange`.

| Route | Opens | Renderer |
|---|---|---|
| `#/` (or empty) | The hub | `RENDERERS.home` (`pages.js`) |
| `#/<slug>/<tab>` | A competition tab; an unknown or missing tab falls back to the competition's first tab | `RENDERERS[<tab>]` (`tabs.js`) |
| `#/<slug>` | The competition's first tab | as above |
| `#/<tab>` | A tab of the competition already open (single segment that is neither a competition nor a global page) | as above |
| `#/<slug>/team/<team-slug>` | Club page | `PAGES.team` (`pages.js`) |
| `#/<slug>/player/<player-id>` | Player page (this competition's season) | `PAGES.player` |
| `#/<slug>/match/<match-id>` | Match page | `PAGES.match` |
| `#/clubs` | Clubs across leagues | `GLOBAL_PAGES.clubs` (`global.js`) |
| `#/nations` | National teams | `GLOBAL_PAGES.nations` |
| `#/leaders` | Global leaders | `GLOBAL_PAGES.leaders` |
| `#/compare` | Compare (empty pickers, examples) | `GLOBAL_PAGES.compare` |
| `#/compare/players/<comp>:<id>/<comp>:<id>` | Two players | `GLOBAL_PAGES.compare` → `comparePlayers` |
| `#/compare/clubs/<comp>:<team-slug>/<comp>:<team-slug>` | Two clubs | `GLOBAL_PAGES.compare` → `compareClubs` |
| `#/player/<player-id>` | Career page (from the archive) | `GLOBAL_PAGES.career` |
| `#/value?v=season&c=<slug>&t=<tier>&club=<tid>&r=<role>&min=<n>&q=<text>` | Player value: leaderboard, best at each position, the method (every filter optional) | `GLOBAL_PAGES.value` (`value.js`) |
| `#/transfer?p=<pid>&to=<tid>&out=<pid,pid>` | The transfer simulator; the state is the link | `GLOBAL_PAGES.transfer` (`value.js`) |

Details:

- Global segments are the keys of `GLOBAL` in `core.js`: `clubs, nations, leaders,
  compare, player, club, disclaimer, lab, glossary, methodology, value, transfer`. A global segment wins only when no competition has
  that slug.
- Club slugs come from `teams.json` (`teams[name].slug`); `findTeamBySlug` in
  `pages.js` also accepts `FH.slugify(name)` and falls back to `probs.json`.
- In compare keys the competition prefix is optional: `comparePlayers` falls back
  to the player id alone, `compareClubs` to the club slug alone.
- Inside a competition the tab bar is `['home'].concat(c.tabs)`; "home" is labelled
  "Hub" and returns to `#/`. On the hub and global pages the tab bar is
  `GLOBAL_TABS`: Hub, Clubs across leagues, National teams, Global leaders,
  Player lab, Player value, Transfers, Compare. The header's `.global-nav` links to the same routes.

### 2.4 Loading and caching

The only payload loaded at start-up is `data/competitions.json` (the manifest); it
fills the picker and the tab lists. Everything else loads when first needed.

| Mechanism | Where | What it does |
|---|---|---|
| `fetchJSON(path, fallback)` | `core.js` | `fetch(path + '?v=' + Date.now())`. The cache-buster means the browser never serves a stale payload after an hourly rebuild; all caching is in memory, per page load. With a `fallback`, a missing payload logs `optional payload missing:` to the console and resolves to the fallback. Without one it rejects. |
| `CORE[kind]` | `core.js` | Payloads loaded when a competition opens (behind the loading overlay on first open): `meta, teams, table, probs` for `league`, `conference`, `playoff`, `cup`; `meta, teams, zones, probs` for `liga`. |
| `NEEDS[tab]` | `core.js` | Payloads a tab needs, loaded on its first visit (`activateTab` → `ensure`). See the payload map below. |
| `FILES[name]` | `core.js` | Payload name → file name under `data/<slug>/`. |
| `FALLBACK[name]` | `core.js` | The value used when that file is missing, so `ensure` never rejects for a competition payload. |
| `ensure(names)` | `core.js` | Loads the named payloads for the open competition into `CACHE[slug].data`, de-duplicating in-flight requests through `CACHE[slug].pending`. |
| `CACHE[slug]` | `core.js` | `{ data, pending, rendered, shards }`. `rendered` is the set of tabs already drawn: a tab renders once per page load and is only shown again on later visits. |
| `loadShard(path, fallback)` | `core.js` | A sharded file under `data/<open slug>/` (`matches/<id>.json`, `players/<club>.json`, `club_matches.json`), cached in `CACHE[slug].shards`. A `null` result is not cached, so it is retried next time. |
| `loadSite(path)` | `core.js` | A site-wide file under `data/` (`pool.json`, `players_global.json`, `nations.json`, `hub.json`, `season_index.json`, and the unified payloads `people/<pid>.json`, `people_index.json`, `clubs/<tid>.json`, `clubs_index.json`), cached for the session in `SITE.data`. Missing files resolve to `null`. |
| `PAGE_NEEDS[page]` | `pages.js` | Competition payloads a page needs before it renders: `team: probs, strength, table, zones, team_stats, fixtures, players_live`; `player: players_live`; `match: fixtures`. |
| Direct `fetchJSON` | `pages.js`, `global.js`, `core.js` | `data/hub.json` (hub; cached in the module variable `HUB`), `data/search.json` (search and the compare pickers), `data/careers/<id>.json`, and in compare `data/<comp>/players/<club>.json` and `data/<comp>/team_stats.json` of another competition. |

The payload map (`NEEDS` in `core.js`):

| Tab | Payloads (`FILES` names) |
|---|---|
| overview | `meta, table, probs, fixtures, players_live, zones, bracket` |
| table | `table` |
| fixtures | `fixtures` |
| zones | `zones` |
| bracket | `bracket` |
| anual | `anual` |
| relegation | `relegation` |
| probs | `probs` |
| power | `strength` |
| team | `probs, strength, relegation, table, zones, team_stats` |
| players | `players_live, player_leaders, shots` |
| matches | `matches` |
| market | `market_odds` |
| history | `history` |
| methodology | `meta, table, bracket` |

Because the lists are shared across kinds, some requests 404 by design (for
example `zones.json` for a normal league, `table.json` for Argentina,
`bracket.json` for a league without a playoff). The fallback absorbs them; the
console shows an `optional payload missing` warning.

### 2.5 The competition picker

`init()` in `core.js` builds `<select id="comp-select">` from the manifest, as
`<optgroup>`s in this order:

| Group | Rule |
|---|---|
| Leagues | `kind !== 'cup'` (so `league`, `conference`, `playoff` and `liga`) |
| Continental & world | `kind === 'cup'` and `family` `cup` (or no family) |
| National cups | `family === 'domestic'` |
| Super cups | `family === 'super'` |
| National teams | `family === 'international'` |

Within a group, competitions keep the manifest order. An entry with `ok: false` is
a disabled option, suffixed "(soon)" when its `reason` is `"no store yet"` and
"(unavailable)" otherwise. The first option, "Hub — all competitions", returns to
`#/`. Choosing a competition navigates to its first tab.

### 2.6 Tabs per competition kind

The tab list comes from the manifest (`tabs`), set by the build from these
constants in `scripts/build_site_all.py`:

| Constant | Used for | Tabs |
|---|---|---|
| `TABS_LEAGUE` | `kind: league` | overview, table, fixtures, probs, power, team, players, matches, market, history, methodology |
| `TABS_PLAYOFF` / `TABS_CONFERENCE` | `kind: playoff` (Liga MX), `conference` (MLS) | as the league, plus `bracket` after `table` |
| `TABS_CUP` | cups with `cup_kind` `swiss`, `groups`, `regional_swiss` | overview, table, bracket, fixtures, probs, power, team, players, matches, market, history, methodology |
| `TABS_KNOCKOUT` | `cup_kind: knockout` | overview, bracket, fixtures, probs, power, team, players, matches, history, methodology |
| `TABS_FIXED` | `cup_kind: fixed` | overview, bracket, fixtures, probs, matches, history, methodology |
| `TABS_PRE` | a cup before its main phase (`phase: "pre"`) | overview, fixtures, matches, methodology |
| `TABS_INTERNATIONAL` | `cup_kind: international` | overview, table, bracket, fixtures, power, team, players, matches, methodology; `build_international` drops `table` when there are no groups or standings and `bracket` when no tie is known |
| `TABS_LIGA` | `kind: liga` (Argentina) | overview, zones, bracket, fixtures, anual, relegation, probs, power, team, players, matches, market, history, methodology |

Labels come from `TAB_LABELS` in `core.js`, overridden per competition by
`tabLabel()`:

| Tab | Condition | Label |
|---|---|---|
| table | `kind: conference` | Conferences |
| table | cup with `cup_kind` `groups` or `international` | Groups |
| table | cup with `cup_kind` `regional_swiss` | Regions |
| table | any other cup | League phase |
| bracket | cup | Knockout |
| bracket | `kind: playoff` | Liguilla |
| bracket | `kind: liga` | Playoffs |
| power | `family: international` | Ratings |
| team | `family: international` | Nations |
| anything else | | `TAB_LABELS` (Overview, Table, Fixtures & Results, Zones, Playoffs, Tabla Anual, Relegation, Probabilities, Power Rankings, Clubs, Players, Matches, Market, History, Methodology) |

### 2.7 The meta line and banners

`updateMeta()` in `core.js` writes the header's `#meta-line` (competition name,
season, played/total matches, simulation count, update time; on the hub, the number
of live competitions) and `#footer-meta`, and fills `#stale-banners`:

| Banner | Condition (in `meta.json` unless stated) |
|---|---|
| "Sample data generated to exercise the site. These are not real results." | `synthetic` |
| "The Sofascore data could not be refreshed (last good data N h ago). Showing the last good data." | `store_fresh === false` (store older than `STALE_AFTER_HOURS` = 24) |
| `phase_note` (or "The main phase has not started.") | `phase === 'pre'` |
| "This edition is complete; the next one is simulated once its draw is known." | `season_stale` and the manifest entry has `complete` |
| "The most recent recorded match is old. The configured season may be out of date." | `season_stale` otherwise (last match older than 30 days for leagues, 60 for cups, 120 for national teams) |
| "The league season is complete; probabilities reflect the final table." | `league_complete` and `kind === 'league'` |
| "National-team competitions are not simulated: tables and the knockout ladder are as played; the line on each fixture comes from the international fit." | `unsimulated` |
| "<name> is not available yet: <reason>." (error style) | manifest `ok: false`, when the competition is opened by URL |
| "Could not load <name>: …" (error style) | a core payload request threw |

### 2.8 Search

The header search box (`initSearch`/`runSearch` in `core.js`) loads
`data/search.json` on first use and matches accent-insensitively after two
characters: up to 3 competitions (from the manifest, by `name` or `short_name`),
6 clubs (`teams[].n`) and 8 players (`players[].n`). Clubs link to
`#/<comp>/team/<slug>`, players to `#/<comp>/player/<id>`. Players are sorted by
minutes in the payload, so the most-played namesake comes first. Escape clears it.

---

## 3. Pages and tabs

Each entry lists what the page shows and the payloads that feed it. Payload names
are the `FILES` names (`data/<slug>/<name>.json`) unless a path is given.

### 3.1 Hub (`#/`)

`renderHome` in `hub.js`; reads `competitions.json` (INDEX), `hub.json`, and
lazily `nations.json`.

- **Header band:** the date, four tiles (matches today, in play, competitions
  live, coming soon), the build time, and an Explore card linking every
  site-wide page (Player lab, Clubs across leagues, National teams, Global
  leaders, Compare, Glossary, Methodology).
- **Scoreboard:** a day strip (the week's days plus "Latest results" and "Next
  up" buckets, live dots) and, for the chosen day, matches grouped by
  competition in two columns: status or kickoff, home, score, away, and the
  model's line for a fixture or xG for a result. Rows open the match centre.
- **Competitions:** family filter chips (All, Leagues, Continental & world,
  National cups, Super cups, National teams) with counts and a search box;
  one card per live competition: country, name, favourite with probability
  bar, season progress bar, leader and top scorer, next fixture, and quick
  links (Table, Fixtures, Analytics, Players, Odds) where the tab exists;
  competitions without a store are listed as chips under "Coming as the data
  arrives".
- **Across the site:** title races still open (favourite below 99.5% and the
  competition not complete), leaders (goals, assists, and rating for players
  with 450+ minutes, a floor the build applies before cutting the list), and
  the six strongest national teams.

### 3.2 Competition tabs (`tabs.js`)

| Tab | What it shows | Payloads |
|---|---|---|
| Overview | KPI tiles (leader or zone/group leaders, title/cup favourite, top scorer, matches played and with full data), latest 8 results, next 8 fixtures with the model bar, "The race" (top 8 by `p_title` or `p_cup`), mini leaderboards (goals, assists, xG, rating) | `meta, table, probs, fixtures, players_live` (+ `zones` for Argentina) |
| Table | Standings with played/W/D/L/GF/GA/GD/Pts, projected points (`exp_pts`), 5th–95th range (`p05`–`p95`), title/winner probability and band probabilities (`bands`), with a band legend. Conferences or groups render one table each (`conferences`, labelled by `group_label`), MLS adds the Supporters' Shield table (`overall`, `overall_label`). Split leagues (Belgium) add a "Top N" column (`p_top_group`). Unsimulated (national-team) tables drop the projection columns. Below: the **finishing-position heatmap** from `p_pos` (`p_final_pos` for a split season) with dashed band cut lines; per-conference panels for conference tables; for group cups and unsimulated competitions a note instead. Then the next 30 unplayed fixtures from `table.fixtures`. | `table` |
| Fixtures & Results | Every match of the season, grouped by local day, filterable by status (upcoming / played / all), stage or round, and club. Unplayed matches carry the full model line: probability bar, fair decimal odds (`fair`, no margin), expected goals (`lh`–`la`), most likely score (`score`, `p_score`), over 2.5 (`o25`), both teams to score (`btts`). Played matches carry xG and a link to the match page when `detail`. | `fixtures` |
| Zones (Argentina) | Zona A and B tables with projected points and top-8 probability (`p_top8`), cut line at `qualifiers_per_zone`, then upcoming zone fixtures | `zones` |
| Bracket / Knockout / Playoffs / Liguilla | Argentina: the Round-of-16 bracket from `seeds` (`label`, `likely`), decided slots from `results`, and a reach table (`reach[team].r16/qf/sf/final`, `p_title`). Every other kind (`renderLadder`): the ties already drawn per round (`known`) with each side's chance of going through and the winner of decided ties (`forced`); seed tables per conference for MLS and Liga MX (`seeds`, `p_playoffs`, `p_cup`); and a reach table per round (`rounds`, `round_labels`, `reach`, `p_cup`). `note` explains the format. | `bracket` |
| Tabla Anual (Argentina) | The annual table with Libertadores/Sudamericana berths (`berths`), champion and berth probabilities, and its position heatmap | `anual` |
| Relegation (Argentina) | Promedio now, projected promedio band (`p05`/`p50`/`p95`), relegation via promedio, via the annual table and overall (`p_promedio`, `p_anual`, `p_any`), and a stacked risk chart | `relegation` |
| Probabilities | One sortable summary row per club. Columns depend on kind: leagues show projected points, title and each band; MLS adds Shield, Playoffs, Conf. title, MLS Cup; cups and Liga MX show bands, reaches final (`p_conference`) and winner (`p_cup`); Argentina shows zone, top 8, champion, anual, Libertadores, Sudamericana, relegation | `probs` |
| Power Rankings / Ratings | Model strength table (`strength_ppg`, `elo`, table position and `rank_delta`, PPG, form chips and `form_ppg`, `xg_diff`, `luck`, `sos_delta`), a luck chart (actual minus xG-expected points), a schedule chart (`sos_played` against `sos_remaining`) and Elo over the season for the top 8 (`elo_history`). The explainer text is `notes` (`notes_en` for Argentina). | `strength` |
| Clubs / Nations | A jump-to select and a card per club: position and points, form, headline probabilities (`teamHeadline()`: title/band/relegation for leagues, MLS Cup/Playoffs/Shield, Champion/Liguilla, Winner/Final for cups, Champion/Top 8/Relegation for Argentina), strength, xG difference per match, luck. Cards link to the club page. | `probs, strength, table, team_stats` (+ `zones`, `relegation`) |
| Players | Leaderboard driven by the metric catalogue (`metrics`): metric, position, club, minimum minutes (defaults to `minutes_floor`) and "qualified only" filters, with the percentile pill (a total uses its `_90` twin's percentile). Top-scorer race (`player_leaders.top_scorer`, rows with a `model` probability). Compare two qualified players on a percentile radar (`RADAR_OUT` or `RADAR_GK`). npxG/90 against xA/90 scatter. Shot map per player. | `players_live, player_leaders, shots` |
| Matches | Played matches (up to 250 shown) filterable by club and "with full match data only" (`detail`), linking to match pages | `matches` |
| Market | Model against de-vigged bookmaker prices per match (`matches.fixtures`: `books`, `model`, `market`, `best_outcome`, `best_edge`, `actionable`) and outrights (`outrights.teams`), with a warning when `field_complete` is false | `market_odds` |
| History | How the headline probabilities moved, one point per hourly run, top 8 clubs of the latest snapshot. Series: Title, the first "up" band and Relegation for leagues; MLS Cup and Supporters' Shield for MLS; Winner (and the first band) for cups; Champion and Liguilla for Liga MX; Clausura champion, Campeón de Liga (Anual) and Relegation for Argentina. Needs two snapshots. | `history` |
| Methodology | Static text in `index.html` plus measured calibration (`meta.calibration`: `draw_rate`, `mean_goals`, `home_win_rate`), the format (conferences/groups, bands, head-to-head note from `table`), the cup or playoff note (`bracket.note`), and the model settings (`meta.model`: `elo_home_advantage`, `dc_weight`, `dc_xi`, `params_method`; `training_matches`, `n_sims`, `detail_matches`, `sheet_matches`) | `meta, table, bracket` |

### 3.2a Analytics tab (`#/<slug>/analytics`)

`renderAnalytics` in `analytics.js`, into `#analytics-root`; needs
`analytics.json` (below), `players_live`, `team_stats`, `strength`, `table`,
`fixtures`. Present for leagues, cups, knockout cups, national-team
competitions and Argentina (not for fixed-tie or pre-phase cups).

| Card | What it shows |
|---|---|
| Team of the week | a round picker (newest first); the XI drawn on a vertical half pitch in the formation the build chose, markers coloured by rating, surname and rating under each, a bench; Player of the week with the build's one-line "why"; award tiles (finisher, creator, the wall, engine, ball winner) and team awards (best xG difference, luckiest, unluckiest, smash-and-grab) with score lines linked to the match centre |
| Best XIs of the season | basis picker (rating, output, defence, form), the pitch, and a table with the basis value, rating, G, A, xG, xA |
| Top and bottom performers | metric picker grouped as the catalogue is; the metric's definition; Top 8 and Bottom 8 among qualified players with value and percentile pill |
| Team rankings and style map | metric picker over the team metrics; a bar chart of every club coloured by percentile beside a ranked table; a heat table of every club against ten headline metrics (xG for and against, possession, field tilt, PPDA, shot quality, big chances, aerial %, pass %, luck) |
| Attack against defence | scatter of xG for against xG against (reversed, so better is up and right), marker size by points, medians, ranks on hover; and points against expected points per club, sorted by luck |
| Form | last six as W/D/L chips with points, xPts, luck and xG difference over the window |

Ids are created inside the module's templates; the round and basis pickers re-render only their card.

### 3.2b Glossary (`#/glossary`, `#/glossary/<key>`) and Methodology (`#/methodology`, `#/methodology/<section>`, `#/<slug>/methodology`)

`docs.js`. The glossary reads `glossary.json`: a live search box, a sticky
group index, one card per group (label, key chip, per-90 / % hints, "lower is
better", scope, definition), then the model terms; a deep link scrolls to and
highlights the entry, and `FH.glossaryLink(key, text)` gives other modules an
anchor. The methodology is one document in thirteen sections with a sticky
table of contents (data; the match model; the pooled scale; national teams;
simulations; power rankings; player analytics; team analytics; the match
centre; markets; player value and transfers; limitations; glossary), every constant taken
from docs/MODELS.md and docs/DATA_PIPELINE.md. A competition's Methodology tab
prepends a "This competition" card from its `meta.json` (parameter set, xi and
its half-life, ridge, dc_weight, Elo settings, calibration, simulations, store
freshness, format and tiebreak rules, the unsimulated flag) and then the same
document.

### 3.3 Club page (`#/<slug>/team/<team-slug>`)

`renderTeamPage` in `pages.js`; needs `PAGE_NEEDS.team`.

- Header with crest, position/points/record chip, form chips, and for a cup club an
  "In its league →" link (`teams[team].league`).
- KPI tiles: the `teamHeadline` probabilities, strength (`strength_ppg`), Elo and
  strength rank, xG for/against per match (`team_stats` season `xg`, `xga`,
  `with_sheet`), luck.
- **Season profile**: percentile sliders against the competition for every
  `team_stats.metrics` entry the club has a `season.pct` for.
- **xG by match** (bars, for and against) and **Form** (five-match rolling points
  per game) from `team_stats.teams[team].matches`.
- **Matches**: first drawn from this competition's `fixtures`; then, when
  `club_matches.json` (loaded with `loadShard`) has more rows for the club, redrawn
  as the **cross-competition list** with a Competition column (league, cups, super
  cups; not national teams). Each row: date, competition, round, opponent,
  venue, result or status, xG, the model bar for unplayed matches, and the link to
  the match page.
- **Squad**: every player of the club from `players_live`, with percentile pills
  (npxG/90, xA/90, pass %, rating; save % and goals prevented/90 for keepers).

The club page also carries, between the season profile and the match list
(`clubAnalyticsHTML` / `renderClubAnalytics` in pages.js, from `analytics.json`
and `players_live.json`): **Where they rank** (every team metric with value,
percentile pill and "#n of N"), a **style radar** on eight axes against the
competition median, **points and expected points by match** with cumulative
luck, the **squad by position** (four sortable tables with position-appropriate
per-90s and percentile pills), the **best XI of the club** drawn with
`FH.drawXI`, **top and bottom at the club** on five metrics, and **set pieces
and discipline** tiles. Each card degrades to one muted line.

### 3.4 Player page (`#/<slug>/player/<id>`)

`renderPlayerPage` in `pages.js`; needs `players_live`.

- Header chips: position label (`players_live.positions`), age, height, country,
  shirt, and the percentile pool (`pool.label`, `pool.n` qualified) or a warning
  that the player is below `minutes_floor`.
- Six KPI tiles (appearances and starts, goals with penalties and xG/npxG or saves
  and save %, assists and xA or goals prevented, shots or conceded, rating and its
  percentile, cards and fouls).
- **Percentile rankings vs the positional pool**: every catalogue metric with
  `pct: true` in the player's scope (`out` or `gk`, plus `all`), grouped by the
  metric's `group`, as sliders; `lower` metrics say "lower is better".
- **Radar** (`RADAR_OUT` or `RADAR_GK` axes from `pct`).
- **Rating by match**, **shot map**, and **evolution charts** (cumulative goals, xG
  and G+A by match; five-match rolling rating) from the club shard
  `players/<club-slug>.json` loaded with `loadShard`, which also feeds the **match
  log** (columns `LOG_COLS_OUT` or `LOG_COLS_GK`, newest first, each row linking to
  the match).
- **All competitions this season** from `data/season_index.json` (`loadSite`):
  one row per competition (`cn`, family chip from `fam`, `t`, `apps`, `min`, `g`,
  `a`, `xg`, `xa`, `sh`, `kp`, `y`, `r`, `rt`) plus a total row with a
  minutes-weighted rating. Other competitions link to the player's page there.
- Links to the career page (`#/player/<id>`), compare, and global leaders.

### 3.5 Match centre (`#/<slug>/match/<id>`)

`renderMatchPage` in `match.js` (registered as `FH.PAGES.match`); needs
`fixtures`, then loads `matches/<id>.json` with `loadShard`. Every section
degrades on its own for matches stored in the older, thinner format (no team
sheet, positions, formation or goal-mouth data).

| Section | What it shows | Data |
|---|---|---|
| Header, model line | score, xG, status; win/draw/loss with fair odds before kick-off | fixture, `model` |
| Summary tiles | xG and non-penalty xG, xG on target, shots and on target, xG per shot, big chances, possession | `shots`, `team_stats` |
| Expected result | every shot replayed 20,000 times as a coin flip at its xG (seeded by match id, so stable): win/draw/loss, the chance of the actual result, a scoreline heatmap with the real score outlined. Rebounds count as separate chances, which the card states | `shots[].xg` |
| xG race | cumulative xG step lines, a dot per shot sized by xG, goals green, half-time marked | `shots` |
| Shot map | one full pitch, home attacking right; size = xG, colour = outcome, ring = team, symbol = body part (▲ header, ■ other); filters for team, situation (open play, set pieces, penalties) and outcome; a running summary of the filtered shots | `shots[].x, y, xg, xgot, shot_type, body_part, situation, goalkeeper` |
| Where the shots went | per team, the goal frame from the shooter's view; size = xGOT. Sofascore's goal-mouth scale puts the posts at y 44.6 and 55.4 and the bar at z 38; higher y is the shooter's left | `shots[].gm_y, gm_z` |
| Timeline, momentum | goals, cards and substitutions by minute and side; Sofascore's pressure index | `incidents`, `momentum` |
| Who made the chances | xG and xA stacked per player, coloured by team | `lineups[].xg, xa, g, a` |
| Team statistics | a derived block first (xG per shot, non-penalty xG, pass accuracy, box-touch share as field tilt, opponent passes per defensive action over the whole pitch, xGOT − xG), then the sheet by phase: attack, possession and passing, duels and defending, goalkeeping, physical | `team_stats` (`<key>_total` for ratio rows) |
| Line-ups | both starting XIs drawn on the pitch from the formation string, coloured by rating; bench, unused and missing players listed | `lineups`, `formation`, `missing` |
| Player statistics | every player who played, sortable, filterable by team: rating, G, A, xG, xA, shots, key passes, big chances, passes, long balls, crosses, touches, progressive carries, dribbles, possession lost, duels, aerials, tackles, interceptions, recoveries, clearances, blocks, fouls, saves, goals prevented, distance, top speed | `lineups[]` short keys (see `LINEUP_KEYS` in `analytics/matches.py`) |

The formation drawing relies on the build keeping starters in Sofascore's
order within each line (Sofascore lists a line from the team's right to its
left): `match_details` sorts starters by line only, never by minutes. When the
formation string does not add up to ten outfielders, the drawing is skipped
and the starters are listed instead.

### 3.5a Player lab (`#/lab`, `#/lab/<comp|all>/<F|M|D|G|O>`)

`renderLab` in `lab.js`, reading `players_lab.json`. Any two catalogue
metrics against each other for one position group (forwards, midfielders,
defenders, goalkeepers, or all outfield players), within one competition or
across every competition.

- **Presets** per position pick pairs that separate styles: for forwards,
  scoring against creating (npxG/90 v xA/90), shot volume against quality,
  chances against finishing, chance quality against placement, dribbling,
  involvement against ball security, output against work off the ball;
  similar sets for midfielders (creation, progression, passing security, ball
  winning, two-way), defenders (possession-adjusted activity v duel success,
  aerials, distribution, ball-playing, box defending, attacking full-backs) and
  goalkeepers (shot stopping, command of the area, distribution). Any metric can
  be chosen for X, Y, marker size and colour.
- **Scope and fairness:** a minutes floor (default 450' globally, 270' within a
  competition); across competitions, attacking rates can be multiplied by the
  pooled model's league scoring factor (the catalogue's adjusted keys plus
  npxG + xA, goals + assists and shots + key passes).
- **Reading it:** dotted lines at the group medians; axes where less is better
  are reversed so better is always up and to the right; the twelve players
  furthest into that corner by summed standard scores are labelled; a search box
  highlights anyone; clicking a dot opens the player. Colour defaults to
  competition globally and to rating within a competition.
- **Ranked table:** the top 60 of the group on the same combined score, with
  each axis's percentile within the group.
- **Views: tournament against calendar.** "This season, per competition"
  reads `players_lab.json` (one line per player per competition). "Last 12
  months" and "Calendar year so far" read `players_lab_365.json` and
  `players_lab_ytd.json`: one line per player across every competition played
  in that window, club and national team, so a player in a league five
  matches old is compared on the same stretch of calendar as one twenty matches
  in. In those views the scope filter is the player's main club competition, the
  club shown is his latest club (never his national team), the table lists the
  minutes in each competition, and league adjustment uses the minutes-weighted
  blend of the competitions he played in. A banner names every competition
  whose match detail does not yet reach back to the window's start.
- **Shrink small samples** (on by default): each rate becomes (minutes × rate +
  450 × group median) / (minutes + 450), so five matches of data move a player
  halfway from the median to his own figure and two thousand minutes leave him
  almost untouched. Hover shows the unshrunk figures; axes say "(shrunk)".
- The URL tracks scope, position and view (`#/lab/<comp|all>/<pos>[/365|/ytd]`), so a view can be shared. Player pages link
  to their competition and position here.
- Sofascore labels positions only G, D, M and F, so wingers usually sit with the
  midfielders and wing-backs with the defenders.

### 3.5b Player value (`#/value`), the transfer simulator (`#/transfer`), strengths and needs

`value.js`; the method is `docs/MODELS.md` 11b and the payloads `docs/site/UNIFIED_PAYLOADS.md` 11.

**`#/value`** reads `value/meta.json` and `value/players.json` (and `value/lines.json` for the
season view). A header card explains the currency and states the current build's walk-forward
validation (value against Sofascore rating and team form) and repeatability; four tiles. The filter
bar: view (last 12 months of club football, or this season by competition), league or competition,
tier (Top five, Other Europe, South America, North America, Asia), club (from the rows the other
filters leave), position (the eight roles, or DF/MF/FW without a start), minimum minutes (900 for 12
months, the competition's floor this season) and a name search; all in the query string. The table
(top 150 by GAR/90, sortable): player, club, league, role badge, age, minutes, GAR/90, GAR, PAR,
percentile pill, projected GAR/90 and fair value index (12 months) or the trend against last season
(season view), the two components that drive the value, and a link to the simulator. **Best at each
position**: eight cards (GK, CB, FB, DM, CM, AM, W, ST), the top eight under the same filters with
value, percentile and the three driving components. **The weights and the checks**: every action's
fitted weight, the validation table and the replacement level per role.

**`#/transfer`** reads `value/players.json`, `clubs_index.json` (the buying-club picker: clubs whose
home league is followed), `value/club/<tid>.json` of the buyer and the seller, each league's
`sensitivity.json`, `probs.json`, `teams.json` and `meta.json`. Two search pickers (player, buying
club), a copy-link button, the player's card (GAR/90, projection, percentile, fair value index,
Sofascore's market value and contract date where held), the verdict per club (strengthens / weakens /
no change now, in goals a match and expected points over the rest of the season; a long-term line
from age; the window status), each club's odds table (now, after, change: title or the league's
headline prize, every band, relegation, expected points) from the sensitivity curves, the affected
units' depth charts (minutes a match before and after), the fair value card, and "players out"
check boxes (`out=`). Clubs outside the followed leagues get values but no odds.

**Strengths and needs** (`FH.renderClubNeeds(el, tid)`, a card near the top of `#/club/<tid>` for
clubs, not national teams; nothing when `value/club/<tid>.json` is missing): the six units with grade,
GAR/90, rank and percentile in the league, the players used and the component that stands out; the
top three strengths and weaknesses in words (marked "relative" when even the weakest units are above
the league median); and for each weakness up to five ranked targets (age, club and league, minutes,
projected GAR/90, gain per 90, points over the rest of the season, fair value index, Sofascore value,
contract and no-club hints, a "Simulate" link). The card states that the suggestions do not consider
wages, fees, contracts, fit or availability.

**Added 16 October 2026** (`docs/MODELS.md` 11c, UNIFIED_PAYLOADS 12). `#/value`: two more columns
in the 12-month view, **Value** (valuation v2 over four seasons, its 10-90% band on hover) and **Fair fee**
(the fee model; the fair value index when the model is not fitted) plus Sofascore's value, and a "Fair
fees and budgets" card with both models' out-of-sample checks and the data coverage. The player card
shows v2 with its band and availability, and the fair fee with its range. `#/transfer` has a sub-nav:
**Simulator** (as before, plus a "Fair fee and budget" card: the fee model evaluated for the chosen buyer
from `meta.fee.model`, the buyer's summer and next-window budgets and whether the fee fits),
**Latest transfers** (`?view=feed`: the feed from `value/transfers.json` with league, type, window and
text filters; fee, fair fee, fee/fair, minutes and GAR/90 since, buyer and seller grades), **Best and
worst deals** (`?view=deals`) and **Windows by league** (`?view=windows`). The club page's strengths and
needs card gained a "Transfer budget and ledger" block (budget tiles, the 12-month market value added,
ins and outs with grades, spend by window marked partial where it relies on player histories) and the
targets' fair fee and budget fit.

### 3.5c Fantasy (`#/fantasy`)

`fantasy.js`; method `docs/MODELS.md` 11d; payloads UNIFIED_PAYLOADS 12.4. Query: `l` league, `v` view,
`p` position, `max` price, `q` name, `fd` (fixtures: `def` for the defence view). A header card with the
league picker, six view chips and four tiles (next gameweek, players, the backtest's rank correlation and
top-20 points against last-five form). Views: **Rankings** (position chips, max price, search; top 120 by
the next-five projection: price, next gameweek, next five, rest of season, tier, expected minutes,
P(goal), clean sheet, season points, form against the underlying numbers); **Next gameweek** (eight
captain cards, the top 30 with points by scoring component); **Fixtures** (each club's next six
gameweeks coloured 1-5, attack or defence view, sorted by total xG or expected clean sheets);
**Picks** (best buys per position, value picks, differentials, transfer out, buy low, sell high);
**Suggested squad** (the MILP's XI by line on a pitch, captain and vice, bench, cost, projections);
**Method and backtest** (the backtest table against three baselines, the scoring, the projection and
the price proxy, and why official FPL data is not used).

### 3.6 Clubs across leagues (`#/clubs`)

`renderClubs` in `global.js`; reads `data/pool.json`.

- **Leagues on one scale**: per league `rank`, `name`, `n_clubs`, `strength`,
  `attack`, `defence`, `factor_att` (the scoring factor used to adjust player
  rates), `best` / `best_rank`, and `connection` (cup matches bridging it into the
  pool; under 20 is flagged "weak"). A note lists `bridges` (matches between
  continental blocks).
- **If they met**: pick any two clubs and a venue; `dcMatrix(home, away, model,
  homeAdv)` computes the Dixon-Coles score matrix in the browser from the clubs'
  `attack`/`defence` and `model.rho`, `model.home_adv`, `model.max_goals`
  (`homeAdv` is 0 at a neutral venue), and `matchCard` shows win/draw/loss with
  fair odds, expected goals, the most likely score, over 2.5 and both to score.
- **Every club**: `clubs[]` filterable by competition and name (`rank`, `team`,
  `comp_name`, `block`, `strength`, `xg_for`, `xg_against`, `attack`, `defence`,
  `elo`, `table_rank`, `form_results`, `luck`); rows with `in_league` link to the
  club page.
- **The strongest 25** bar chart.

### 3.7 National teams (`#/nations`)

`renderNations` in `global.js`; reads `data/nations.json` and `data/hub.json`.

- A table of every national team (`rank`, `team`, `confederation`, `played`,
  `strength`, `attack`, `defence`, `elo`), filterable by confederation and name,
  with `note` above it.
- **If they met**: the same `dcMatrix` pricer over the international fit's
  `model`, neutral venue by default.
- **Next internationals**: unplayed items with `family === 'international'` from
  `hub.json` `upcoming` and `days`, de-duplicated, first 30, with the model bar.
- **The strongest 25** chart.

### 3.8 Global leaders (`#/leaders`)

`renderLeaders` in `global.js`; reads `data/players_global.json` (qualified players
of every competition).

- Metric select from `metrics`; every key in `adjusted_keys` also appears as
  `<key>_adj` "(league-adjusted)". The default is `npxg_90_adj` (`saves_90` for
  keepers).
- Filters: position, competition, minimum minutes (defaults to `minutes_floor`).
- Columns: the value, the raw value before adjustment, the league factor
  (`adj_factor`), and the percentile in the **global** position pool
  (`pct_global`, falling back to the metric's `_90` twin).
- `note` explains the adjustment. Argentina carries no factor (it is fitted
  separately).

### 3.9 Compare (`#/compare/players|clubs/<comp>:<id>/<comp>:<id>`)

`renderCompare` in `global.js`. The pickers (kind toggle, two search boxes with
suggestions, URL state) feed `comparePlayers` or `compareClubs`; async work is
guarded by a render token so a stale pair never paints.

Players: identity cards; a verdict strip (metrics won on the position's
percentile set and the three biggest gaps each way in words); a radar with a
competition / global percentile toggle; the full catalogue table grouped, with
value, percentile pill and a diverging gap bar for each metric, sortable by
group or by size of gap; eight headline per-90s as paired bars; cumulative
goals against xG and rolling rating overlaid; shot maps side by side; the last
five matches each; and every competition this season from `season_index.json`.

Clubs: identity cards (position, points, form, pool rank, strength, Elo,
attack, defence, luck); a hypothetical match priced three ways from
`pool.json` when both are in the pool; a style radar and the full team-metric
table with ranks from `analytics.json`; head-to-head this season with the
model's line on the fixture to come; last six and points against expected
points by round; season probabilities side by side; the top five players by
rating at each club.

### 3.10 Career page (`#/player/<id>`)

`renderCareer` in `global.js`; reads `data/careers/<id>.json`: `details` (name,
team, position, `dob`, height, country, foot, `market_value`), `totals` (`apps`,
`minutes`, `goals`, `assists`, `xg`, `xa`, `ga_90`, `rating`), `seasons` (one row
per season and tournament: `season`/`year`, `tournament`, `team`, `apps`,
`minutes`, `goals`, `assists`, `xg`, `xa`, `ga_90`, `shots_90`, `key_passes_90`,
`rating`) and `complete`. Charts: goals and assists by season, G+A per 90 and
rating by season. Without a file: "No career in the archive for player <id> yet."

The archive currently holds no players (`data/careers/index.json` is empty), so
career pages and the career half of compare show their empty states until
`scripts/fetch_sofascore_history.py` fills `docs/site/data/archive/store.json`.

---

## 4. The build

### 4.1 `scripts/build_site_all.py`

Run: `uv run python scripts/build_site_all.py` (the full run takes about 20
minutes). It writes into `DATA_DIR = docs/site/data`.

CLI flags:

| Flag | Effect |
|---|---|
| `--sims N` | Override the simulation count of every competition (and Argentina's). |
| `--no-market` | Skip The Odds API and the prediction-market (Polymarket, Kalshi) fetches (market payloads are marked `ok: false` or keep the previous run's market). |
| `--seed N` | Seed the simulators. |
| `--only SLUG` | Build only these slugs; repeatable. Competitions not rebuilt keep their manifest entries and feed `hub.json`/`search.json` from their existing payloads. |
| `--skip-liga` | Skip the Argentine build. |
| `--no-sensitivity` | Skip the per-club sensitivity curves (`sensitivity.json`); the transfer simulator then shows values without odds. |
| `--no-value` | Skip the player value layer (`data/value/`) and with it the fantasy layer. |
| `--no-fantasy` | Skip the fantasy layer (`data/fantasy/`). |
| `--no-market-rates` | Fit without the market-implied rates of past matches. |

The exit code is 0 when at least one competition built, 1 otherwise.

What `main()` does, in order:

1. Reads `oddsmarkets/football/competitions/league/data/seasons.json` (per
   competition: `previous_rank`, `conferences`, `teams`).
2. **The pooled fit** (`fit_pooled`): when any league's tuned method in
   `model_params.json` is `pooled` or any cup is being built, one Dixon-Coles fit
   over every league store plus every non-international cup store.
   `pooled_training_frame` prefixes each club with its league slug; cup matches put
   a club under its league's prefix (via `COUNTRY_LEAGUE`) when that league has
   it, which is what connects the leagues into one graph. It records
   `POOL_CONNECTIONS` (cup matches per league) and `POOL_BRIDGES` (matches between
   continental blocks). `LeagueView` and `CupView` present that one fit to each
   competition under plain team names.
3. **Leagues** (`build_league`, one per entry of `LEAGUES`): Elo seeded from last
   season's table, Dixon-Coles (own fit or the pooled view, per
   `model_params_for`), blended in an `EnsembleModel` with the draw rate and goal
   scale measured from the league (`empirical_calibration`); the season simulated
   by `LeagueSimulator` with the golden-boot model; the per-club sensitivity curves
   (`write_sensitivity` → `sensitivity.json`, about 2 × 2,000-run simulations per club and shift,
   4 to 10 seconds a league, never failing the league); then `teams.json`,
   `table.json`, `probs.json`, `bracket.json` (MLS and Liga MX only),
   `strength.json`, `players_live.json`, `player_leaders.json`, `shots.json`,
   `history.json`, `market_odds.json`, the analytics payloads
   (`write_analytics`), and `meta.json`. `kind` is `conference` when the config has
   conferences, `playoff` when it has a playoff, else `league`.
4. **The international fit** (`fit_international`): one Dixon-Coles fit (plus Elo)
   over every national-team store (friendlies at half weight, neutral venues
   marked), used to price national-team fixtures and to write `nations.json`.
5. **Cups** (`build_cup`, every entry of `CUPS`; `fixed` brackets last so they can
   draw on other cups' simulated champions):
   - no store (and not `fixed`) → `ok: false, reason: "no store yet"`;
   - `cup_kind: international` → `build_international`: tables and the knockout
     ladder as played, `probs.json` empty, `strength.json` from the international
     fit, fixtures priced by that fit, `unsimulated: true`, no history or market;
   - no teams in the main phase yet → `build_cup_pre`: fixtures, results, players
     and match pages only, `phase: "pre"`, the note from `PRE_PHASE_NOTES`, tabs
     `TABS_PRE`;
   - otherwise the pooled view (or an own fit) and `CupSimulator`, then
     `teams.json`, `table.json` (`standings` for `swiss`, `conferences` for
     `groups`/`regional_swiss`, empty for knockout and fixed), `bracket.json`,
     `probs.json`, `strength.json`, players, `history.json`, `market_odds.json`,
     analytics and `meta.json`.
6. **Argentina** (`build_liga`): see 4.3.
7. **Site-wide payloads**: `hub.json` (`build_hub`) and `search.json`
   (`build_search`) from this run's entries plus, under `--only`, the previous
   entries re-read from disk.
8. **The layer above the competitions** (inside one `try`, so a failure here never
   blocks the manifest): `build_nations`, `build_season_index`,
   `build_club_matches`, then `scripts/build_site_global.py`: `build_global`
   (`pool.json`, `players_global.json`) and `build_archive_pages` (`careers/`,
   `history/`).
9. **The unified layer** (`build_unified(entries, seasons, archive)`, run as the
   step "people, clubs and seasons" after the site-wide steps): `Unified` in
   `oddsmarkets/football/analytics/unified.py` reads every competition store,
   the Argentine store, the archive, `squads/store.json` and `past/store.json`,
   and writes `people/`, `people_index.json`, `clubs/`, `clubs_index.json`,
   each competition's `seasons.json` and `s/<sid>/season.json` (section 5.1a).
   It also returns the fields the manifest gains (`kind_u`, `scope`,
   `current_season`, `seasons`, `winner`) and the `current` flag for
   `players_live.json` rows. As it loads each store it hands the line-ups to a
   `ValueCollector` (`analytics/value.py`).
9b. **Player value** (`build_value_layer`, its own step: a failure is logged and
   the manifest is still written): fits the value model walk-forward on the
   collected line-ups and writes `value/meta.json`, `players.json`, `lines.json`
   and `value/club/<tid>.json` (about 15 seconds; `docs/MODELS.md` 11b); since 16 October 2026 also
   valuation v2, the fee model, deal grades, ledgers and budgets from `data/transfers/store.json`
   (`analytics/transfers.py`, about 3 seconds) and `value/transfers.json` (MODELS 11c).
9c. **Fantasy** (`build_fantasy_layer`, its own step, `--no-fantasy` skips it): the walk-forward
   backtest, then projections, picks and the MILP squad per followed league into `fantasy/`
   (about 10 seconds; MODELS 11d).
10. **The manifest** `competitions.json`, in the order leagues, Argentina, cups
   (registry order), merging this run's entries over the previous file so `--only`
   never drops a competition.

Every per-competition builder returns an index entry. Keys starting with `_`
(`_fixtures`, `_players`, `_teams`, `_strength`, `_probs`, `_bracket`, `_floor`)
carry in-memory results to steps 7 and 8 and are stripped before the manifest is
written.

`write_analytics(out_dir, store, registry, model, season_filter, players, logs,
by_team, details, neutral_when)` is shared by leagues, cups, national teams and
Argentina. It writes `fixtures.json` (`build_fixtures_json`: every match the
season filter admits, the model line from `predict_fixture` on unplayed matches,
neutral when `neutral_when(raw)` says so), `matches.json` and `matches/<id>.json`
(`write_match_pages`, pruning stale shards and deleting a legacy
`match_detail.json`), `players/<club-slug>.json` (`write_player_shards`, pruned
likewise) and `team_stats.json` (`build_team_stats_json`).

`predict_fixture` returns `{h, d, a, lh, la, o25, btts, score, p_score, fair}`,
with `fair` = `1/p` rounded to two decimals (null below p = 0.005).

### 4.2 The manifest: `competitions.json`

`{"competitions": [...], "updated_at": ...}`. Fields of an entry:

| Field | Meaning |
|---|---|
| `slug`, `name`, `short_name`, `country` | Identity (`country` is the region for cups). |
| `kind` | `league`, `conference` (MLS), `playoff` (Liga MX), `liga` (Argentina), `cup`. |
| `cup_kind` | Cups only: `swiss`, `groups`, `regional_swiss`, `knockout`, `fixed`, `international`. |
| `family`, `family_label` | Cups only: `cup`, `domestic`, `super`, `international` (drives the picker groups and the national-team labels). |
| `tabs` | The tab list (section 2.6). |
| `ok`, `reason` | Whether it built; `reason` is `"no store yet"`, an exception message, the pre-phase note, or `"liga build exited N"`. |
| `phase` | `"pre"` for a cup before its main phase. |
| `unsimulated` | National-team competitions. |
| `complete` | A cup whose favourite has reached probability 1. |
| `season`, `games_played`, `games_total`, `updated_at` | Progress. |
| `synthetic`, `store_fresh`, `season_stale` | Data health (hub chips). |
| `favourite`, `p_favourite`, `favourite_label` | The hub card and the Favourites chart. |
| `leader`, `top_scorer`, `next`, `last` | From `index_extras`: `{team, pts, played}`, `{id, name, team, goals}`, the next fixture `{id, date, home, away, status, model{h,d,a}}`, the last result `{id, date, home, away, hs, as}`. |
| `kind_u`, `scope` | From the unified layer: `league`, `domestic_cup`, `super_cup`, `continental_club` or `international`; `club` or `international`. |
| `current_season`, `seasons`, `winner` | From the unified layer: `{sid, season, era, status}` with `status` `current` or `last_edition`; the season list (as in `<slug>/seasons.json`); the winner of a last edition. Field definitions in `docs/site/UNIFIED_PAYLOADS.md`. |

On 29 September 2026 the manifest lists 69 competitions: 23 with `ok: true`
(one of them, the CAF Champions League, in its pre-phase form) and 46 with
`reason: "no store yet"`.

### 4.3 `scripts/build_site_liga.py`

The original Argentine build. It writes `teams.json`, `zones.json`,
`bracket.json`, `anual.json`, `relegation.json`, `probs.json`, `history.json`,
`strength.json` (with `notes_en`), `players_live.json`, `player_leaders.json`,
`shots.json`, `match_detail.json`, `market_odds.json` and `meta.json` (with
`phase` `apertura`/`clausura`) into its `DATA_DIR`, and keeps the fitted model and
store in the module global `LAST_BUILD`. Its CLI: `--sims`, `--no-market`,
`--seed`. It returns 1 on an empty store or a completed season.

`build_liga` in `build_site_all.py` points the module at
`docs/site/data/liga-argentina/` (overriding `SITE_DIR`, `DATA_DIR`, `STORE_PATH`
= `docs/liga/data/liga_store.json`, `HISTORY_STORE`), calls its `main()` with the
forwarded flags, then re-writes `players_live.json` with the catalogue and
percentiles the site expects, runs `write_analytics` for the season's matches
(which also removes `match_detail.json`), and fills crest paths into `teams.json`.

### 4.4 `scripts/build_site_global.py`

Called from step 8 with the in-memory entries.

- `build_global(data_dir, entries, pooled, connections, bridges)`: `pool.json`
  from `oddsmarkets/football/analytics/pool.py` `build_pool` (or a stub with
  `note: "No pooled fit this run."`), and `players_global.json`: every qualified
  player of every `ok` competition, restricted to `GLOBAL_KEYS`, plus `comp`,
  `comp_name`, `kind`, `team_slug`, `crest`, `pct_comp` (the competition
  percentiles); `adjust_players` multiplies the `ADJUSTED_KEYS` rates by the
  league's `factor_att` into `<key>_adj` and sets `adj_factor`; percentiles are
  recomputed over the whole pool into `pct_global` / `pool_global`, and
  `_write_adjusted_percentiles` adds the `_adj` percentiles.
- `build_archive_pages(data_dir, archive)`: `careers/<id>.json` for every archived
  player, `careers/index.json`, and `history/<slug>.json` (past season tables) for
  every competition with archived seasons.

### 4.5 Deployment

`.github/workflows/update_site.yml` runs hourly at :17. It cannot fetch from
Sofascore (datacenter IPs are blocked), so it hydrates each store and history store
from the public site repo when that copy is more complete, runs
`uv run python scripts/build_site_all.py` (with `ODDS_API_KEY` from secrets), and
rsyncs `docs/site/` into the repo named by `vars.SITE_REPO` using
`SITE_DEPLOY_KEY`. Without those settings it builds and does not deploy. Stores
travel with the site so the next run can hydrate from them; the page never reads
them.

---

## 5. Payload reference

All paths are under `docs/site/data/`. "Producer" is the function that calls
`_write` for the file (in `scripts/build_site_all.py` unless another script is
named).

### 5.1 Site-wide

| Path | Producer | Consumer | Key fields |
|---|---|---|---|
| `glossary.json` | `build_glossary` in `oddsmarkets/football/analytics/glossary.py` (site-wide step) | Glossary; definitions also travel in every `players_live.json` metric as `desc` | `groups[{name, entries[{key,label,desc,fmt,scope,lower,group}]}]`, `model[{key,label,desc,group}]` |
| `players_lab.json` | `build_lab` in `scripts/build_site_global.py` | Player lab | column-oriented: `fields` (identity columns, `comp`, `team_slug`, then metric keys), `rows` (one per player per competition with 90+ minutes), `metrics` (catalogue subset), `comps` (name, kind, family, scoring `factor`), `adjusted_keys`, `min_minutes` |
| `players_lab_365.json`, `players_lab_ytd.json` | `build_lab_windows` in `scripts/build_site_global.py` | Player lab, calendar views | as `players_lab.json`, plus per row `mix` (competitions and minutes) and `factor` (blended scoring factor); `window` {tag, label, start, end}; `comps[slug].first_detail` (earliest match with detail) |
| `competitions.json` | `main` | `init` (picker, tabs), banners, hub cards and Favourites chart, search | `competitions[]` (section 4.2), `updated_at` |
| `hub.json` | `build_hub` | Hub scoreboard and leaders; `#/nations` next internationals | `days{YYYY-MM-DD: [item]}`, `window[lo, hi]`, `today`, `recent[]`, `upcoming[]`, `leaders{goals, assists, rating}`; item: `comp, comp_name, kind, family, id, date, home, away, hs, as, status, stage, round, detail, crests[2], model{h,d,a}?, xg?`; leader row: `id, name, team, comp, comp_name, pos, value` + `xg` / `xa` / `minutes` |
| `search.json` | `build_search` | Header search; compare pickers | `teams[{n, comp, comp_name, slug, crest}]`, `players[{id, n, t, comp, pos, min}]` (sorted by minutes) |
| `season_index.json` | `build_season_index` | Player page, "All competitions this season" | `players{<id>: {n, rows[{comp, cn, kind, fam, t, pos, apps, min, g, a, xg, xa, rt, sh, kp, y, r}]}}` |
| `nations.json` | `build_nations` | `#/nations` | `teams[{team, confederation, played, attack, defence, strength, elo, rank}]`, `model{rho, home_adv, attack_mean, defence_mean, max_goals}`, `calibration`, `note` |
| `pool.json` | `build_global` (`build_site_global.py`) | `#/clubs`, compare clubs | `model{rho, home_adv, attack_mean, defence_mean, max_goals, n_clubs}`, `leagues{<slug>: {name, n_clubs, attack, defence, strength, best, best_rank, factor_att, factor_def, connection, rank, block}}`, `clubs[{team, comp, comp_name, in_league, attack, defence, xg_for, xg_against, strength, p_win_avg, p_draw_avg, elo, table_rank, played, ppg, form_results, xg_diff, luck, team_id, crest, slug, rank, block}]`, `bridges{"A\|B": n}`, `note` (stub only) |
| `players_global.json` | `build_global` (`build_site_global.py`) | `#/leaders`, compare players | `players[]` (`GLOBAL_KEYS` + `comp, comp_name, kind, team_slug, crest, pct_comp, pct_global, pool_global, adj_factor, <key>_adj`), `metrics`, `positions`, `minutes_floor`, `leagues`, `adjusted_keys`, `note` |
| `careers/<id>.json` | `build_archive_pages` (`build_site_global.py`) | `#/player/<id>`; compare players (careers) | `id, details, seasons[], totals, fetched_at, complete` |
| `careers/index.json` | `build_archive_pages` | not read by the front-end | `players[{id, name, team, position, country, seasons, complete, goals, assists}]` |
| `history/<slug>.json` | `build_archive_pages` | front-end fallback for the season list when `<slug>/seasons.json` is missing | `seasons` (past tables and leaders from the archive) |
| `value/meta.json`, `value/players.json`, `value/lines.json` | `build_value_layer` → `analytics/value_payloads.py` | `#/value`, `#/transfer` | UNIFIED_PAYLOADS.md 11.2, 12 |
| `value/transfers.json` | `build_value_layer` → `analytics/transfers.py` | `#/transfer?view=` | UNIFIED_PAYLOADS.md 12.3 |
| `fantasy/meta.json`, `fantasy/<league>.json` | `build_fantasy_layer` → `analytics/fantasy.py` | `#/fantasy` | UNIFIED_PAYLOADS.md 12.4 |
| `value/club/<tid>.json` | the same | club page "Strengths and needs", `#/transfer` | UNIFIED_PAYLOADS.md 11.2 |

`search.json`, `season_index.json`, `careers/` and `history/` are kept as
front-end fallbacks while the pages move to the unified payloads below.

### 5.1a Unified payloads (added 2 October 2026)

Written by `build_unified()` (section 4.1, step 9). The field-level contract is
[`docs/site/UNIFIED_PAYLOADS.md`](site/UNIFIED_PAYLOADS.md); this table only
says what each file is.

| Path | What it holds |
|---|---|
| `people/<pid>.json` | One file per Sofascore player id (about 15,000, ~70 MB): identity, `current_club`, `national_team`, every appearance across every store as compact rows (`apps_fields`, `apps`), per-competition-season rows `seasons` (tagged `kind` `league`, `domestic_cup`, `super_cup`, `continental_club` or `international`, `scope` `club` or `international`, a `current` flag, and the full season `line` above 90 minutes), and the archive career rows. |
| `people_index.json` | One row per person (search and pickers). |
| `clubs/<tid>.json` | One file per Sofascore team id, national teams included (about 2,500, ~12 MB): names per competition, squad, seasons, matches across every store with the fixture's model line, pooled strength. |
| `clubs_index.json` | One row per club or national team. |
| `<slug>/seasons.json` | The competition's season list from the live store, the past-results store and the archive, each with `status` `current` or `last_edition`, and the winner of a last edition. |
| `<slug>/s/<sid>/season.json` | One past season: standings (official from the archive, or computed from past results), fixtures, bracket, players and leaders with team ids. Argentina's Apertura 2026 is `s/2026-apertura/`. |

Fields added to existing payloads: `competitions.json` entries gain `kind_u`,
`scope`, `current_season`, `seasons` and `winner` (section 4.2);
`players_live.json` rows gain `current` (false when the player has left that
club).

### 5.2 Per competition (`data/<slug>/`)

| File (`FILES` name) | Producer | Consumer | Key fields |
|---|---|---|---|
| `analytics.json` | `build_analytics` in `oddsmarkets/football/analytics/insights.py`, written by `write_analytics` | Analytics tab; club page; compare | `rounds[]` newest first (team_of_week with formation and XI, player_of_week with `why`, awards, team_awards), `season_xi{rating,output,defence,form}`, `performers.players{key:{top,bottom}}`, `performers.teams{key:{ranking}}`, `teams{team:{profile{key:{v,pct}}, form[6], rounds[]}}`, `team_metrics[]`, `player_metrics[]`, `minutes_floor` |
| `meta.json` (`meta`) | `build_league`, `build_cup`, `build_cup_pre`, `build_international`; Argentina: `build_site_liga.py` `main` | Core; meta line, banners, overview, methodology | `updated_at, n_sims, runtime_s, season, games_played, games_total, league_complete, store_fresh, synthetic, store_age_hours, season_stale, training_matches, calibration{draw_rate, lam_scale, mean_goals, home_win_rate}, model{elo_home_advantage, elo_k_league, dc_weight, dc_xi, dc_ridge, dc_fitted, params_method}, h2h_tiebreak, source, detail_matches, sheet_matches`; cups add `cup_kind, forced_ties, cup_complete`; pre-phase adds `phase, phase_note`; national teams add `phase, unsimulated`; Argentina has `phase` (`apertura`/`clausura`) and `apertura_champion` and no `season` |
| `teams.json` (`teams`) | the same builders | Core; crests, club slugs, conference, "In its league" link | `teams{<name>: {slug, conference, team_id, crest, league?}}` |
| `table.json` (`table`) | `build_table_json` (leagues), `build_cup`, `build_cup_pre`, `build_international`; none for Argentina | Core; table tab, overview, club cards and page, methodology | `season, bands[{key, label, first, last, kind}], tiebreak, h2h_tiebreak, fixtures[{round, home, away, hg, ag, date, done, stage, id}], games_played, total_games, matches_per_team`; then `standings[]` or `conferences{}` + `overall[]` (+ `overall_label`, `group_label`); `split{top, europe, relegation, halve_points}` with `p_final_pos`, `p_top_group` per row; `unsimulated`. Row: `pos, team, played, w, d, l, gf, ga, gd, pts, exp_pts, p05, p50, p95, p_title, p_pos[], bands{}` |
| `probs.json` (`probs`) | `build_probs_json`, `build_cup`, stubs; Argentina `build_probs_json` | Core; probabilities, overview race, club cards, headline tiles | `teams[{team, conference, exp_pts, p_title, bands{}, p_playoffs?, p_cup?, p_conference?}]` (Argentina: `zone, p_top8, p_anual, p_libertadores, p_sudamericana, p_relegation`), `bands`, `has_playoff` |
| `bracket.json` (`bracket`) | `build_bracket_json` (MLS, Liga MX), `build_cup`, `build_cup_pre`, `build_international`; Argentina `build_bracket_json` | Bracket tab, overview, methodology note | `kind, rounds, round_labels, seeds, known{round: [[a, b]]}, forced{"A v B": winner}, reach{team: {round: p}}, p_playoffs, p_cup, confirmed, format, note`. Argentina: `rounds, round_labels, seeds[{slot, label, pair, likely, confirmed}], results, reach, p_title` |
| `zones.json` (`zones`) | Argentina `build_zones_json` | Core for Argentina; zones tab | `tournament, qualifiers_per_zone, zones{A, B: {standings, fixtures, games_played, total_games}}` |
| `anual.json` (`anual`) | Argentina `build_anual_json` | Tabla Anual tab | `berths{libertadores, sudamericana, note, note_en}, rows[{pos, team, played, pts_now, exp_pts, p_champion, p_libertadores, p_sudamericana, p_pos}]` |
| `relegation.json` (`relegation`) | Argentina `build_relegation_json` | Relegation tab | `rules{places, note, note_en}, rows[{pos, team, promedio_now, p05, p50, p95, p_promedio, p_anual, p_any}]` |
| `strength.json` (`strength`) | `build_strength_json` (leagues, cups, national teams); Argentina `build_strength_json` | Power tab, club cards and page | `form_window, rows[{team, conference, elo, attack, defence, strength_ppg, strength_rank, table_rank, rank_delta, played, points, ppg, form_points, form_ppg, form_gf, form_ga, form_results, xg_for, xg_against, xg_diff, expected_points, luck, sos_played, sos_remaining, sos_delta}], elo_history{team: [{date, elo}]}, notes` (+ `notes_en`) |
| `players_live.json` (`players_live`) | `build_players_json` | Players tab, overview leaders, club squad, player page | `ok, updated_at, checked_at, matches_covered, minutes_floor, metrics[{key, label, group, fmt, scope, pct?, lower?}], positions{G, D, M, F}, players[]`; a player row has identity (`player_id, name, short_name, team, position, is_gk, age, country, height, shirt`), totals, `_90` rates, `pct{metric: 0-100}`, `pool{key, label, n}`, `qualified`, `current` (false when the player has left that club; unified layer). Null values are omitted. |
| `player_leaders.json` (`player_leaders`) | `build_players_json` | Players tab, top-scorer race | `top_scorer[40]`, `live[]`; row `{id, name, team, goals, assists, xg, minutes, model}` |
| `shots.json` (`shots`) | `shots_by_player` via the builders | Players tab shot map | `players{<name>: {team, player_id, shots[{x, y, xg, xgot, type, body, situation, time, match, gid}]}}` |
| `fixtures.json` (`fixtures`) | `build_fixtures_json` via `write_analytics` | Overview, fixtures tab, club page, match page | `matches[{id, date, round, stage, status, home, away, hs, as, detail, xg?, group?, split_group?, torneo?, zone?, winner?, agg_winner?, model?{h, d, a, lh, la, o25, btts, score, p_score, fair[3]}}]`; `status` is `scheduled`, `live`, `finished`, `postponed` or `cancelled` |
| `matches.json` (`matches`) | `write_match_pages` | Matches tab | `matches[{id, date, round, stage, group, home, away, hs, as, xg, detail}]` (played only, newest first), `with_detail` |
| `matches/<id>.json` (shard) | `write_match_pages` | Match page | `id, home, away, hs, as, round, stage, torneo, date, status, group, xg, momentum[{minute, value}], incidents[], shots[], ratings[], lineups{home, away}, formation{home, away}, missing{home, away}, team_stats{home, away}` (the sheet is absent for matches fetched in the older format) |
| `players/<club-slug>.json` (shard) | `write_player_shards` | Player page (log, rating, evolution, shot map); compare evolution | `team, players{<id>: {name, team, pos, matches[{gid, date, round, stage, team, opp, ha, gf, ga, res, pos, start, min, rt, g, a, xg, xa, sh, ..., shots[]}]}}` (newest first) |
| `team_stats.json` (`team_stats`) | `build_team_stats_json` | Club cards and page; compare clubs | `teams{<name>: {season{matches, with_sheet, xg, xga, gf, ga, ..., pct{}}, matches[{gid, date, opp, ha, gf, ga, res, xg, xga, ...}]}}`, `metrics` (`TEAM_METRICS`: `key, label, fmt, lower?`) |
| `club_matches.json` (shard) | `build_club_matches` (league kinds only: `league`, `conference`, `playoff`, `liga`) | Club page cross-competition match list | `clubs{<name>: [{id, date, round, stage, status, home, away, hs, as, xg, detail, comp, cn, model?{h,d,a}}]}` |
| `sensitivity.json` | `write_sensitivity` (leagues, Argentina) | `#/transfer` | UNIFIED_PAYLOADS.md 11.3 |
| `history.json` (`history`) | `build_history_json` (last 60 of the store); Argentina `build_history_json`; pre-phase cups write the existing store's tail, national teams an empty list | History tab | `snapshots[{ts, title, relegation?, band?, band_key?, shield?}]`; Argentina `{ts, title, anual, relegation}` |
| `market_odds.json` (`market_odds`) | `write_market_odds`; Argentina `write_market_odds` | Market tab | `ok, updated_at, checked_at, matches{fixtures[{home, away, books, model{home, draw, away}, market{...}, best_outcome, best_edge, actionable}], min_edge, actionable}, outrights{available, teams[{team, model, market, edge, actionable}], field_complete?}` |

### 5.3 Files in `data/` that the page never reads

| Path | What it is |
|---|---|
| `<slug>/store.json` | The Sofascore store for that competition (build input; deployed so CI can hydrate). |
| `<slug>/history_store.json` | Up to 400 snapshots; the served `history.json` is its tail. |
| `archive/store.json` | The archive (past seasons, careers), input to `build_archive_pages` and the unified layer. |
| `squads/store.json` | Current squads (`scripts/fetch_sofascore_squads.py`), input to the unified layer. |
| `past/store.json` | Past seasons' results (`scripts/fetch_sofascore_history.py`), input to the unified layer. |
| `careers/index.json` | Written by `build_archive_pages`; no page reads it yet. |

---

## 6. How degradation shows on the page

| Situation | Build behaviour | What the visitor sees |
|---|---|---|
| Competition without a store | Entry `ok: false, reason: "no store yet"`; no payloads written | Picker option disabled, "(soon)"; hub card with an "unavailable" chip and the reason; opening `#/<slug>` by URL shows the hub with "<name> is not available yet: no store yet." |
| Competition whose build throws | Logged with the traceback; entry `ok: false, reason: <exception>` | As above, suffixed "(unavailable)" |
| Argentine build fails or its store is missing | `ok: false` with `"no store yet"` or `"liga build exited N"` | As above |
| Cup before its main phase | `build_cup_pre`: `phase: "pre"`, `tabs: TABS_PRE`, empty table/probs/bracket/strength, `n_sims: 0` | Tabs Overview, Fixtures, Matches, Methodology; banner with `phase_note`; hub card chip with the note (or "not started"); the overview race says "No simulation for this competition yet." |
| Stale store (older than 24 h) | `store_fresh: false`, `store_age_hours` | Banner "The Sofascore data could not be refreshed (last good data N h ago). Showing the last good data."; hub card chip "stale" |
| Old season | `season_stale: true` | Banner "The most recent recorded match is old…", or "This edition is complete…" for a completed cup |
| National-team competition | `build_international`, `unsimulated: true` | Banner; tables without projection columns; heatmap replaced by a note; no Probabilities, Market or History tabs; fixtures still carry the international fit's line |
| No market odds (`--no-market`, no `ODDS_API_KEY`, no `odds_api_sport`, or a failed fetch) | `market_odds.json` written with `ok: false` (keeping the previous matches if there were any) | Market tab: "Odds could not be refreshed." and "No match odds available. Set ODDS_API_KEY in the build environment to fill this tab."; outrights: "No outright market available for this competition." Fair odds on the Fixtures tab are unaffected. |
| No pooled fit | `pool.json` stub with `note` | `#/clubs` shows "No pooled fit this run."; compare clubs "(no pooled model this run)"; on global leaders every `adj_factor` is 1, so adjusted rates equal raw ones |
| No international fit | `nations.json` with `teams: []`, `note` | `#/nations` shows the note; national-team fixtures have no model line |
| Empty archive | `careers/` holds only `index.json` | Career page "No career in the archive…"; compare "Neither player is in the archive yet…" |
| Unified payload missing for a person or club | `people/<pid>.json` or `clubs/<tid>.json` not built (unified step failed, or an older deploy) | The page assembles the person from `season_index.json` and the career archive, or the club from one competition's payloads, with a chip "this season and the archive only" / "this season only" |
| Squads not yet fetched for a club | The unified layer falls back to a newer profile, then the latest club appearance (`UNIFIED_PAYLOADS.md` 2.3) | A player who has left a club with no fetched squad can still show there until the squad arrives |
| Site-wide step throws | Caught and logged; `competitions.json` still written | The affected global page shows its empty state |
| Optional payload missing | Front-end `FALLBACK` | That section's "No … yet." message; console warning |
| Plotly CDN blocked | none | "The chart library did not load. The tables carry the same data." in each chart box |
| A renderer throws | `safeRender` | "This section could not be shown: <message>" at the top of the pane |
| Match without a detail shard | Only `detail: false` fixtures lack a shard | Match page header plus "No detailed data for this match yet…" and the model card if unplayed |
| Player below the minutes floor | `qualified: false`, no `pct` | Player page chip "below N minutes: no percentiles yet"; sliders read "not enough minutes" |

---

## 7. Local preview and screenshots

Serve the site root (any static server works; there is nothing to build):

```bash
cd docs/site
python -m http.server 8899
# open http://127.0.0.1:8899
```

Deep links work directly, for example
`http://127.0.0.1:8899/#/premier-league/table`,
`http://127.0.0.1:8899/#/champions-league/bracket`,
`http://127.0.0.1:8899/#/compare/players/premier-league:839956/bundesliga:108579`.

To refresh the data first without the 20-minute full build:

```bash
uv run python scripts/build_site_all.py --sims 20000 --no-market --only premier-league --skip-liga
```

`--only` keeps every other competition's manifest entry and payloads as they are.
Do not run the fetch scripts to refresh stores for a preview (Sofascore budgets and
its 403 challenge; see `HANDOFF.md`).

Headless screenshots with Chrome (Plotly loads from its CDN, so the machine needs
network access). `--virtual-time-budget` lets the page's fetches and renders
finish before the capture:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu --hide-scrollbars `
  --window-size=1440,2400 --virtual-time-budget=20000 `
  --screenshot=C:\tmp\epl-table.png "http://127.0.0.1:8899/#/premier-league/table"
```

Raise the budget for heavy pages (a club page with a cross-competition list,
`#/leaders`, which loads the 6,000-row `players_global.json`). Microsoft Edge
(`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`) takes the same
flags.

---

## 8. Tests and the JS syntax check

```bash
uv run --group dev pytest tests/test_build_site_all.py tests/test_site_global.py tests/test_build_site_liga.py tests/test_international.py
```

| File | Covers |
|---|---|
| `tests/test_build_site_all.py` | An end-to-end build from synthetic stores (`scripts/make_league_sample_store.py`, `scripts/make_liga_sample_store.py`), offline, with `--sims 2000 --no-market --only …` for EPL, MLS, Liga MX, the Belgian Pro League, Argentina, the Champions League, Libertadores, the AFC, CAF and CONCACAF cups, the FA Cup and the World Cup, into a temporary directory. Asserts the manifest, league/MLS/Liga MX/split/cup/regional-swiss/knockout/national-cup/national-team payloads and their probability sums, fixtures with model lines, player percentiles and the catalogue, player and match shards, team stats, `hub.json`, `search.json`, `pool.json`, `players_global.json`, `nations.json`, `season_index.json`, `club_matches.json`, and the degradation paths (missing store, pre-phase cup). **Front-end contract checks** by inspection: every element id the scripts write to exists in `index.html` (or is created by the scripts); the five scripts load in the order `core, charts, tabs, pages, global`; every tab in every `TABS_*` list has a `#tab-<name>` pane and an entry in the `RENDERERS` block of `tabs.js`; the club/player/match pages and the global pages are registered; every payload the build writes is named in the JS (`'<name>.json'`). Also the tuned model parameters and the pooled `LeagueView`. |
| `tests/test_site_global.py` | The layer above the competitions on synthetic inputs: the pooled score matrix, `build_pool` ranks and league factors, careers and archive season tables. |
| `tests/test_value_football.py` | Player value (28 tests, offline): roles from formations, the line-up collector (npxG, possession adjustment, signs), non-negative weights, priors from earlier days only, walk-forward validation on a planted signal, the default-weight fallback, points per goal, continuation and ageing curves, transfer windows, the unit allocation, target ranking (strength, league step, age, own club, two per club), the Poisson tilt and the sensitivity curves on a sample league, the payload shapes, sample floors, unit grades, and person files without `line` or crest paths. |
| `tests/test_transfers_football.py` | Transfers (16 October 2026, offline): the Sofascore transfer parsers and their soft failures, the fetcher's queues and budget split (followed clubs, players, cup reserve, 404 back-off, 403 stop), windows and deal kinds, the line history and availability, valuation v2, the fee model against a baseline on a planted relationship, grades, the budget model. |
| `tests/test_fantasy_football.py` | Fantasy (offline): FPL scoring from match lines, bonus by rating with ties, Poisson expectations, the fixture's effect on a projection, gameweeks (rounds, rescheduled matches, weeks), prices, the squad MILP's rules and the greedy fallback. The end-to-end build test also checks the transfers and fantasy payloads. |
| `tests/test_unified.py` | The unified layer (2 October 2026): registry de-duplication, the current-club rules, squads, season lists and statuses, Argentina's halves, name matching, the squads rotation, and the past-results queue and paging. |
| `tests/test_build_site_liga.py` | The Argentine build offline: meta, probabilities, zones, Tabla Anual, relegation routes, players, top-scorer probabilities, shots, match detail, market degradation, history accumulation, and failing loudly on an empty store. |
| `tests/test_international.py` | The cup registry (national teams, national cups, super cups), round and stage parsing, tournament search, the confederation table, the international training frame, and `build_season_index` / `build_club_matches` from build entries. |

There is no browser test. After any JS change, parse every module:

```bash
uv run --quiet --with esprima --no-project python -c "
import esprima, glob
for f in sorted(glob.glob('docs/site/assets/js/*.js')):
    esprima.parseScript(open(f, encoding='utf-8').read())
    print('ok', f)
"
```

Then load the changed pages in a browser (or take headless screenshots) and check
the console.

---

## 9. Recipes: a tab, a metric, a global page

### Add a competition tab

1. **Payload.** Write it in the builder(s) with `_write(out_dir, "<name>.json",
   payload)` (in `build_league`, `build_cup` or `write_analytics`, depending on
   which competitions need it). Keep it degradable: write an empty shape when
   there is nothing to show.
2. **Manifest.** Add the tab name to the relevant `TABS_*` lists in
   `scripts/build_site_all.py` (the order is the order in the tab bar).
3. **Loading.** In `core.js`: add `<name>: '<name>.json'` to `FILES`, a fallback
   to `FALLBACK`, and `<tab>: ['<name>', ...]` to `NEEDS`. Add a label to
   `TAB_LABELS`, and a case in `tabLabel()` if it varies by kind.
4. **Pane.** Add `<div id="tab-<tab>" class="tab-pane">…</div>` to `index.html`
   with the element ids the renderer writes to.
5. **Renderer.** Write `render<Tab>()` in `tabs.js` reading `FH.D().<name>` and
   register it in the `RENDERERS` object literal at the bottom (the test parses
   that block, so keep the `<tab>: render<Tab>` form).
6. **Tests.** `test_every_manifest_tab_has_a_pane_and_a_renderer`,
   `test_every_element_id_the_script_writes_to_exists` and
   `test_script_lists_every_payload_it_reads` will fail until 3–5 are consistent;
   add payload assertions to `tests/test_build_site_all.py`.

### Add a player metric

The catalogue `METRICS` in `oddsmarkets/football/analytics/players.py` drives the
front-end: it is emitted in `players_live.json` and `players_global.json` as
`metrics`, and the competition and global leaderboard selects and the player
page's percentile sliders are built from it.

1. Compute the value in `aggregate_players` (same file; league, cup and Argentine
   stores all delegate to it). A raw sum starts in `SUM_KEYS`; a per-90 twin comes
   from adding the total to `PER90`.
2. Add a catalogue entry: `{"key", "label", "group", "fmt": "int"|"1"|"2"|"pct",
   "scope": "out"|"gk"|"all"}`, plus `"pct": True` to make it a percentile slider
   (ranked by `add_percentiles` against the positional pool) and `"lower": True`
   when less is better. The entry's `group` decides which optgroup and slider group
   it lands in.
3. To show it on global leaders and compare, add the key to `GLOBAL_KEYS` in
   `scripts/build_site_global.py` (rows are whitelisted); to league-adjust it, add
   it to `ADJUSTED_KEYS` in `oddsmarkets/football/analytics/pool.py`.
4. Radar axes (`RADAR_OUT`, `RADAR_GK` in `tabs.js`), match-log columns
   (`LOG_COLS_OUT`, `LOG_COLS_GK` in `pages.js`), the squad table and the compare
   side-by-side rows are hand-listed; edit them only if the metric belongs there.

Team metrics work the same way through `TEAM_METRICS` in
`oddsmarkets/football/analytics/teams.py` (`key, label, fmt, lower?`), which
drives the club page's season-profile sliders and the compare-clubs table.

### Add a global page

1. Payload: write it in `scripts/build_site_global.py` (or `build_site_all.py`
   step 8) with `_write(data_dir, "<file>.json", ...)`, inside the existing `try`.
2. Route: add `'<segment>': '<name>'` to `GLOBAL` in `core.js`; to put it in the tab
   bar, add `<name>` to `GLOBAL_TABS`, `GLOBAL_ROUTE` and `TAB_LABELS`, and a link
   to `.global-nav` in `index.html`.
3. Pane: add `<div id="tab-<name>" class="tab-pane">` to `index.html` (`openGlobal`
   shows the pane with the page's name; only `career` renders into `#tab-page`).
4. Renderer: write it in `global.js` using `loadSite('<file>.json')`, and register
   it with `Object.assign(FH.GLOBAL_PAGES, { <name>: render<Name> })`. The
   renderer receives the rest of the route after the segment as its argument.
5. Add the pane and renderer to the assertions in
   `test_every_element_id_the_script_writes_to_exists`.

---

## 10. Known gaps

Found while writing this document.

- **Fixed 2026-09-29: player match logs for clubs with accented or punctuated
  names.** The build names club shards with `_slug()` (keeps Unicode letters,
  one dash per other character, no collapsing); the front-end's `slugify` used
  to strip non-ASCII and collapse dashes, so 80 of 603 shards (e.g.
  `bayern-münchen.json`) were never found. `FH.slugify` now mirrors `_slug()`
  exactly, and the player page prefers the club's `teams.json` slug. Keep the
  two functions in step if either changes.
- **`careers/index.json` is written but not read.** `history/<slug>.json` is
  read only as the fallback for a missing `<slug>/seasons.json`.
- **The career page's compare link** uses the first competition in the manifest as
  the prefix; `comparePlayers` then falls back to the id alone, so it works only
  when the player is in `players_global.json`.
- **Shared `NEEDS` lists request payloads some kinds never have** (section 2.4),
  which shows as 404s and console warnings.

---

## 11. Legacy sites

| Site | Path | Status |
|---|---|---|
| Argentine Liga Profesional | `docs/liga/` (`index.html`, `assets/app.js`, `assets/style.css`, `data/`) | The original single-competition site, in Spanish (`lang="es"`; Bootstrap 5.3 and Plotly 2.27 from CDNs). Built by `scripts/build_site_liga.py` into `docs/liga/data/` when run standalone. Its workflow, `.github/workflows/update_liga.yml`, is superseded by `update_site.yml`: the schedule is off and it runs only by hand (its deploy key has never worked). Its store `docs/liga/data/liga_store.json` is still the input for The Quant Footballer's Argentina pages. |
| World Cup 2026 | `docs/wc/` (`index.html`, `assets/app.js`, `assets/style.css`, `data/`) | Archived; its workflow (`.github/workflows/update_wc.yml`) is manual-only, with the schedule removed. |

Neither shares code with `docs/site/`; changes to The Quant Footballer's front-end
never need to touch them.
