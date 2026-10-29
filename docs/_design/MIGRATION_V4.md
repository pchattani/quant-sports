# Moving a site to kit v4 "Broadcast" (dark only)

This guide is for the phase-C agents, one site each. Before starting:
1. Read `STYLE_GUIDE.md` (identity, type, colour and the team-colour rules, copy).
2. Open `docs/_design/showcase.html` (serve `docs/`, open `/_design/showcase.html`). The "Broadcast" block at the top
   shows every new piece.
3. Copy the pattern from the reference pages:

| Page | Reference |
|---|---|
| Home | `docs/home/index.html`, `assets/home.js`, `assets/home.css` (builder fields in `scripts/build_home.py`: team `full`, `alt`) |
| Sport overview | `docs/rink/assets/js/rk-overview.js` |
| Game page | `docs/rink/assets/js/rk-games.js` (`hero`: `QK.previewCard` with raw kit colours, `alt`, `full`) |
| Player page | `docs/rink/assets/js/rk-player.js` |
| Compare page | `docs/rink/assets/js/rk-compare.js` |
| Site CSS | `docs/rink/assets/rink-qk.css` §7 and the faux-bold fixes at the end |

The concept the user picked is `<scratchpad>/concepts/broadcast/` (`index.html`, `player.html`, and the
`broadcast-*-theme-dark-*.png` screenshots). Match it. The user's decision is **dark only**: no light theme, no
toggle, and check with `--themes dark`.

## What changes automatically (no code)

Copying the kit (`python scripts/design_kit.py docs/<site>`) makes every page on every site read Broadcast. It went
live on all nine sites with ec8ad0f1. The same APIs now draw:
- **Shell:** the black top bar, "THE QUANT <SITE>" with the volt mark, condensed sport tabs with a volt underline, and
  the section nav on `--block-2`. `QK.shell()` injects Bebas Neue, Barlow and Barlow Condensed if the page links the
  v3 faces.
- **Type everywhere:** `.qk h1–h3`, card titles, section titles, empty states and the legacy `.card-header` become
  all-caps Bebas. Labels, tags, buttons, chips, tabs, table heads and axis labels become Barlow Condensed capitals.
  Body text becomes Barlow.
- **Shape:** every radius is 0 (`--r-pill` too), and soft shadows are gone. Cards are charcoal with a 5 px top rule.
- **Ticker:** chances appear in volt.
- **Section heads:** the kicker is the volt tag on a black parallelogram.
- **Game cards:** the 8 px team-colour stripe, square monograms, Bebas scores and chances, and the foot "Our chance ·
  why". The bar under the rows has gone, because the stripe carries the split (pass `bar: true` to keep it).
- **Chance bars:** the title-race bars are team-colour blocks with the name inside.
- **Stat tiles:** black blocks, with the percentile chip ("97th pctl") under the number.
- **The percentile card / rail:** LED meters with the ▼ for last season and the percentile in a box.
- **Player header:** the full-bleed team-colour diagonal hero with an outlined number; `stats` render as the black
  strip under it.
- **Compare:** two players become the tale of the tape; three get the square table with entity blocks.
- **The Matchday modules:**
  - greeting: the broadcast lower third;
  - `featureCard` and `previewCard`: the diagonal split hero;
  - `hotRow`: the black power list with outlined ranks;
  - `statOfDay`: the volt slab;
  - `newHere`, `shortVersion` and `note`: explain strips;
  - `howSure`: big numbers over the calibration line chart (the dashed diagonal "spot on"; restored 24 Oct);
  - `scorebug`: black, the clock on red.
- **Charts:** solid grids, condensed labels, square bars, black tooltips with a volt edge, and calibration as bars.
- **Specificity guards** stop v3-era site CSS from turning text dark-on-dark: filled selected tabs, link colours on
  blocks, and `.num { text-align: right }` on the big numbers.

The checker after the copy was clean on every site's overview and one player page (17 pages × 1440 and 375). The
contrast audit was clean on the Rink, Ace, Bullpen, Campus, Footballer and Hardwood pages it covered.

## What each page type must add

### 1. The head of every page

Link the v4 fonts (this avoids a late swap), set the meta, and use the volt favicon:
```html
<html lang="en-GB" data-sport="hockey" data-theme="dark">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="#000000">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%23000000'/%3E%3Cpath d='M11 6h14l-6 20H5z' fill='%23d4ff3a'/%3E%3C/svg%3E">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700;800&family=Barlow:wght@400;500;600;700&family=Bebas+Neue&display=swap">
```
Remove the Fraunces / DM Sans link. Still linking it today: `site`, `paddock`, `hardwood`, `ace`, `bullpen`,
`gridiron`, `campus` (`index.html`).

### 2. Overview (as `rk-overview.js`)

- **Opening.** Keep `QK.greeting({ date, title, lede, ctas, side: QK.featureCard(bestGame, { scribble }) })`. It now
  draws the lower third with the split hero under it. Give the teams `full` (the full name, for the city line) and
  `alt` (the second kit colour, for clashes). Or put `QK.splitHero(g, { tag })` first on its own, as the Home does.
- **The black stat strip:** `QK.stats([...])`, or `QK.statStrip(list)` for full bleed.
- **What to watch:** `QK.watchGrid(games, { limit: 6 })` or `QK.gameCard(g, { why: true })` in a `.qk-watch` grid.
  Title it "N games. Our calls.", with the kicker "What to watch tonight".
- **Who's hot:**
  ```js
  QK.band(
    QK.sectionHead({ kicker: 'Who’s hot', title }) +
    QK.hotRow([{ kicker, title, name, value, next, expl, href }])
  )
  ```
  Use the top name on your leader boards.
- **How sure and who's for real** go side by side in a `.qk-g75` grid:
  - left: "We say it. Then we check it.", via `QK.howSure(el, { calibration: <calibration.json>, league, subject })`;
  - right: "Who's for real?", via `QKC.quadrant(el, { points: [{ x, y, label, name, color, href, sub }], xName,
    yName, refX, refY })`. Use the sport's process-against-results pair (shown in the table below).
- **"What's that number?":** `QK.newHere({ items })`, with the third item linking your Model page.
- **Title race:** `QK.sectionHead({ kicker: 'Title race', title: 'Who lifts the Cup?' })` +
  `QK.chances(rows, { key: false })`. Give each row `color` (the team kit) and `mark` (`{ abbr, colour }`). Our
  chance only.

| Sport | x (chances) | y (results) |
|---|---|---|
| Hockey | 5v5 xGF% | points % |
| Football | xG share | points per game |
| NBA / WNBA | net rating | win % |
| NFL | EPA / play margin | win % |
| MLB | run differential per game or xwOBA gap | win % |
| College | rating | win % |

### 3. Game page (as `rk-games.js` `hero`)

- Pass the teams' **raw** kit colour, `alt` and `full` to `QK.previewCard(G, { kicker: '<League> · <venue>', nick,
  factors, noteExtra, market })`. `QK.color.blockPair` makes the blocks (white type at 4.6:1 or better) and resolves
  clashes. Keep your lifted chart pair for charts only.
- The market may sit only here, as `market: { p, label: 'Market (<source>)' }` (a black line under the hero).
- A team "tale of the tape" is `QK.matchupBar({ left, right, rows, colors })`, which now draws as the tape.
- Put your forecast table beside the hero (`.rk-gtop`).

### 4. Player page (as `rk-player.js`)

1. **Crumb**, then `QK.playerHeader({ name, number, pos, kicker, team: { name, abbr, colour, alt, href }, meta,
   tags, strip: [five statTile objects with pctl], short })`. The hero is full bleed. `strip` is the black strip of
   five numbers; `short` is "The short version" as the explain strip.
2. **A `.qk-g75` grid.**
   - Left: `QK.pctRail(...)`, its rows with `prev` (last season's percentile, the ▼, from `prev_pct_pos`), then
     `QK.explain('<b>How sure are we?</b> ' + sample + settle line + ▼ sentence)`.
   - Right: the **tale of the tape** against the closest match. Title it "<Surname> or <Surname>?" with
     `QK.sectionHead({ kicker: 'Tale of the tape' })`. Add chips (`.qk-chips` of `qk-chip` buttons) to switch between
     the closest matches, plus a link opening all three in Compare. Draw it with `QK.compareView({ entities: [two,
     each with colour, alt, short, sub], groups })` and put `QK.verdicts` under it.
3. **A `.qk-g2` grid.**
   - Left: what to watch tonight, `QK.previewCard(g, { layout: 'bug', factors, nick })` (the scoreboard bug and the
     match-up).
   - Right: the last game. Title it with the score ("COL 5, PIT 2"). Show the box score by period (goals, shots,
     expected goals) and the race chart (expected goals, or the sport's equivalent: win probability, points) from the
     game file.
4. **The game log:** "Every game this season", a `qk-table` with the best night as `tr.hl`.
5. **Game by game** and **Their type**, then the existing sections.

### 5. Compare page

Two players are the tape automatically. Remove copy that mentions the delta column, or pass `layout: 'table'` to keep
it. Give entities `colour`, `alt` and `short`. Title the page as a question ("MacKinnon or McDavid?").

### 6. Model page

Put `QK.howSure(el, { calibration, league, span, subject })` at the top. The market column may stay as a named
reference.

### 7. Leaders, teams, standings

Nothing is required. Optionally put a `QK.band(... QK.hotRow(...))` strip at the top of a leaders page.

## Sport rules (team colours, STYLE_GUIDE §3)

- **F1 (Paddock).** A driver takes the constructor colour (`teams[].colour` in `index.json`) as `team.colour`, on the
  hero and in `QK.chances` rows. Team-mates share it: `blockPair` gives the second driver slate with the constructor
  colour as the rule, automatically. Use the car number as `number` for the outlined number.
- **Tennis (Ace).** There are no teams, so pass no colour. The player we favour is cobalt and the other slate (the
  tennis rule, automatic). The player hero is cobalt. No nation colours.
- **Football (Footballer).** Use club colours where the data has `colour`, else the same cobalt v slate rule.
  Payload follow-up for the football data agent: add `colour` and `alt` per club to `clubs_index.json`. For example,
  take the dominant non-white colour of each local crest at build time; that needs no new fetch, since the crests are
  already in `assets/crests/`. Then the 69 competitions get team-colour heroes and bars.
- **College (Campus).** Programme colours come from the data (`colour`), and `alt` where present.

## Site code that must change (found in the v4 sweep)

**Faux bold.** Bebas has one weight, so `font-weight: 600–900` with `var(--font-display)` draws a faux bold. Set
400. Rink fixed this at the end of `rink-qk.css`. Sites with display-face rules to check:
- `site/assets/app/*.css`
- `paddock/assets/app/paddock.css`
- `hardwood/assets/*.css`
- `gridiron/assets/app/gridiron.css`
- `campus/assets/campus.css`
- `ace/assets/ace-qk.css`
- `bullpen/assets/bullpen-qk.css`

Also drop any `font-style: italic` on display text, and `font-variation-settings`.

**Hard-coded radii** in legacy CSS: square them (`border-radius: 0`) where they draw cards, pills or bars. The largest
counts are in `bullpen/assets/legacy.css`, `ace/assets/legacy.css`, `*/assets/base.css` and `pages-f.css`.

**Site-built kit markup.** Rebuild it with the kit builders so the v4 pieces appear:
- **Ace `core.js`** builds its own `.qk-gc` rows. Use `QK.gameCard` (players as `away` / `home`, `players: true`), or
  add the stripe and the `.qk-gc-ft` foot.
- **`.qk-feature-*` "last time out" cards** in Ace `players.js`, Gridiron `player.js`, Hardwood `hw-player.js` and
  Campus `cc-players.js`: replace them with the last-game box score, as `rk-player.js` does.
- **Paddock** `overview.js`, `drivers.js` and `race.js` use the `.qk-feature-*` classes for their own hero. Move to
  `QK.splitHero` (driver v driver for a head-to-head), or `QK.band` + `QK.hotRow` for the grid.

**v3 selected-tab rules** (`.bp-page a.qk-tab[aria-selected]`, `.ta-page a.qk-tab[aria-selected]`) are overridden
by a kit guard. Delete them.

**Paddock contrast.** The contrast audit flagged text dimmed with `opacity`:
- the race-day date and time lines ("Fri 23 Oct", "13:30", at 3.6:1);
- the coral disclaimer link on `--s-4` (4.1:1).

Use `--ink-3` without opacity, and `--signal` for links.

**Copy:** "Six games we'd pick" becomes "Six games. Our calls."; "How sure are we?" titles become "We say it. Then we
check it."; "Results v process" becomes "Who's for real?" / "Results v chances".

## Checks (every changed page)

1. Run `python scripts/design_kit.py docs/<site>` after any kit change. Never edit `assets/qk/`.
2. Run `esprima` on every changed JS file (no `?.`, no `??`):
   `uv run --no-project --with esprima python <scratchpad>/jscheck.py <files>`.
3. Run the checker, dark only, at 1440 and 375, with `--banned`. Wait 6 s for async fills:
   ```sh
   uv run --no-project --with playwright python <scratchpad>/v2check.py <out> "<site>/#/" ... \
     --themes dark --banned --shots --full --wait 6000
   ```
   It must report no overflow, no console errors, no untitled value axis, and no banned words outside `.qk-legal`.
4. Run the contrast audit (text AA against the real background, alpha-blended, white on team blocks included) at both
   widths, and fix any failure:
   ```sh
   uv run --no-project --with playwright python <scratchpad>/bc_contrast.py "<site>/#/..." --width 375
   ```
5. Payload budgets must stay unchanged. The only new reads on the Rink pages are files the site already has
   (`season.json`, a game file).

## Payload follow-ups (for the data agents, not phase C)

- **Club colours for football** (above).
- **`full` and `alt` for every team** in each site's `index.json` teams map. Rink and Gridiron have both; Bullpen
  has full names but no `alt`; check the others. The hero prints the city from `full` and uses `alt` on a clash.
- **Last game in the player file.** A `current.last_game` block with the linescore and the race would let player
  pages skip the game-file load.

## Progression (round 6, 28 Oct 2026)

The user: "it's hard to visualize player progression year to year. Build a view that allows us to look at player
progression year by year and compare players year by year on deep metrics. Make it deep. Make it for all where we have
history." The kit module is `progression.js` (in `KIT_FILES`, so `design_kit.py` copies it to `assets/qk/`); the
builder side is `oddsmarkets/common/progression.py`. Reference sites: Rink, Hardwood and Bullpen.

### Data (builders, fields only)

Use `oddsmarkets.common.progression.Builder` in the careers step. For every player-season row, call
`h = pb.add(season, kind, group_id, values, qualified, pct=site_pct)` and merge `h` into the season row after
`pb.finish()`:

| Field | Where | What |
|---|---|---|
| `prog` | `players/<pid>.json` top level | `{"v": 1, "keys": {"<kind>": [ids]}}`: the deep set per kind. Build it with `deep_keys(sport, [group ids], have)`: the spec groups' headline metrics, then the secondary ones, only ids the data carries |
| `seasons[i].dv` | each season row | the values, aligned to `prog.keys[kind]` (null where missing; 4 significant figures) |
| `seasons[i].dp` | qualified rows only | the percentiles 0-100 against that season's qualified peers of the group (the site's own percentile when passed, so the card and the progression agree) |
| `seasons[i].pg` | each season row | the spec group the row is placed in |
| `progression_ref.json` | one per sport or league (`data/progression_ref.json`, Hardwood `data/<league>/progression_ref.json`) | `pb.reference(labels, lengths)`: season x group x metric -> `[p10, p25, p50, p75, p90]` and `n` (qualified peers); `len` = games in the season. About 50-150 KB |

Arrays keep the player files small (a deep set of ~40 metrics adds ~350 bytes a season). Run the careers step on every
season on disk so every season with history gets the fields. Mark short seasons only where the data shows it (a games
count against the season's length, an injury field): the adapter passes `short: { kind: 'injury' | 'short', tag, text }`.

### Front end

Load the module after `quant-charts.js`: `<script src="assets/qk/progression.js"></script>`. The site adapter turns
a player file into the kit shapes (in `progression.js`'s header):

```js
P = { id, name, short, seasons: [{ key, x /* 2015 */, label /* '2015-16' */, age, team: { abbr, name, colour },
      teams, group, n, nMax, nUnit, small /* under the floor */, partial /* the season in progress: out of the jumps,
      the peak and the trend, tagged SO FAR */, short /* { kind, tag, text } | null */,
      values: { id: v }, pct: { id: p } }] }
M = { id, label, unit, dir, fmt, ours: { name } | null, tip, head }   // from QK.spec: cat.metric(id) + cat.ours(id)
ref = QK.prog.ref(progressionRefJson);  // ref(group, seasonKey, id) -> { q: [5], n }
```

| Piece | Call | Use |
|---|---|---|
| Career chart | `QKC.progression(el, { player: P, metrics: [M], mode: 'value' \| 'pct', x: 'season' \| 'age', ref: (S, id) => ref(S.group, S.key, id), peerName: 'forwards' })` and `QK.progressionKey({ name, peerName, pctLine: true })` under it | one metric: the value line, the peer median (dashed) and the middle half (25th-75th) of each season's qualified peers, the percentile on a right axis; several metrics: percentiles. Dot size = sample, hollow = under the floor, team changes as dashed verticals ("→ NYR" in the team colour), short seasons tagged under the dot |
| Percentile heatmap | `QK.progressionGrid({ player: P, metrics: [M], groups: [{ label, ids }], peerName, dropEmpty })` (rows with no value in any season are dropped unless `dropEmpty: false`) | metrics down the side, seasons across (team and age under each), the percentile on the kit scale in each cell, value and sample in the tooltip, our-model rows tagged "Ours"; scrolls inside its card at 375 px |
| Jumps and drops | `QK.progressionDeltas({ player: P, metrics: [M], limit: 4, peerName })` | the biggest changes between consecutive seasons, in percentile points, with the values |
| Career arc | `var a = QK.careerArc({ player: P, metrics: headline [M], all: deep [M], key: M (WAR / GAR), peerName })` -> `a.html` (black tiles: peak season, age at peak, the last three seasons' trend, the best key value) and `a.text` ("The short version": put it in `QK.explain(a.text, { title: 'The short version.' })`) | the top of the Progression tab |
| Compare | `QK.compareProgression(el, { players: [P] (2-4), metrics: [M], cat, metric, x: 'season' \| 'age' \| 'year', y: 'value' \| 'pct', ref: (P, S, id) => ..., peerName: P => ..., onState: s => (update the hash), suggest: [{ name, href }], cyNote })` | controls (metric select with "Our models" / "Box score" optgroups, by season / by age / career year, value / percentile), the chart (the peer band by season when everyone shares a group), the key, and the season-by-season table with each player's best season marked BEST |

Ages: compute every season's age the same way (from the date of birth on one fixed date), never a mix of a
catalogue's age and a computed one: two seasons at one age keep only the later one.

Pages:
- **Player page:** a "Progression" tab (`#/player/<id>?view=progression`): the career arc and the short version, the
  chart with a metric picker (the deep set, ours first) and by season / by age, the heatmap of the position's headline
  and secondary metrics, the jumps and drops, and a link "Compare progression" to the compare page with the closest
  matches.
- **Compare progression:** `#/compare/progression/<id>/<id>[/<id>/<id>]?m=<metric>&x=season|age|year&y=value|pct`,
  linked from the player page and from Compare.
- Copy: neutral (no pronouns: the surname or "the player"), no betting words, every axis titled.

Checks as above: esprima, the checker (dark, 1440 and 375, `--banned`), the contrast audit. The showcase has a
"Progression" block on sample data (`showcase.html#progression`).

## Scouting Room and Teams page (round 8, 28 Oct 2026)

The user: "Consolidate the Players page with the lab and rename the lab... clean graphics and tables on players that are
meaningful to the sport, positions etc... Do not lose the depth of metrics. The Teams page also looks mediocre... find a
better way to display along with a lot more information comparing teams." The Bullpen is the pilot and the reference:
`docs/bullpen/assets/js/bp-scout.js` (the room), `bp-teams.js` (the Teams page), `lab.js` (`BP.lab.mount`: the Lab as the
room's Chart view), `core.js` (routes, redirects, the nav switch). The kit pieces are in `scout.js` (STYLE_GUIDE §5).

### Rollout, per site

1. **Nav.** `QK.sections(sport, { scout: true })`; add a `scout` route; map the old Players and Lab routes into it with
   their parameters (the Bullpen's `redirectOf` in `core.js`); move Compare and Prospects under the Scouting Room and
   parks / venues / referees under Teams.
2. **Load** `<script src="assets/qk/scout.js" defer></script>` after `quant-charts.js`.
3. **The room** (`#/<L>/scout`): one control bar (`QK.within` + `QK.scoutBar`: season, the minimum sample from the spec
   floor, team, age band, hand or foot where the payload has it, search); "Top of the position" (`QK.hotRow`, five of the
   view's metrics, one per family); view tabs Board | Chart | Leaders (`?view=`); the profile drawer (`?p=`) and the
   compare tray (`?cmp=`). Everything in the address.
4. **Payload.** The room reads one column-oriented file of every player and every metric (the site's `lab.json`), with
   `age` and `hand` per row (the Bullpen added `age`, `hand`, `chances`, `called`: +6.6%). Never the 5-10 MB catalogues.
5. **Teams** (`#/<L>/teams`): power board, team profile grid, style map (presets per sport, the corners named), strengths
   and weaknesses, head to head (`QK.tape` with `gap: true`), and "Through the season" only where the game log or a race
   log already carries it.

### Round 10: the Board's "Bloomberg view" (28 Oct 2026)

`QK.board` draws a quiet table: plain numbers, a thin percentile bar under each, colour only for the top and bottom 10%,
one-line heads from the spec's `short` (every metric in `docs/_design/metrics/<sport>.json` has one; `design_kit.py`
appends it and the short unit to each labels row as `[7]`, `[8]`; `cat.short(id)`, `cat.unitShort(id)`), and a card list on
phones. A site passes `summary` (its value metric, also the default sort), `abbr` (heads for payload keys the spec lacks:
`{ id: 'Short' | ['Short', 'unit'] }`), optionally `family` (the 8-column cap keeps one metric per family first), reads its
column set back with `QK.board.pick(sets, SC.cols, 'view')` (so "Position view (all N)" survives a redraw) and marks the room
`<div class="sc qk-room">` (on phones the tabs come straight after the controls, then "Top of the ..." as small cards). The
heat grid is unchanged.

### What changes per sport

| Site | Groups (Broad / Position) | Rating parts on the power board | Style-map presets |
|---|---|---|---|
| Footballer | outfield / goalkeepers; GK, CB, FB, DM, CM, AM, W, ST | attack (xG for) / defence (xG against) | xG for v against, press v possession, set pieces v open play |
| Hardwood / Campus basketball | all players; guards, wings, bigs | offence / defence net rating | pace v efficiency, three-point rate v rim rate, rebounding v turnovers |
| Rink | skaters / goalies; C, W, D, G | 5v5 offence / defence, special teams | xGF% v points%, PP v PK, shot quality v volume |
| Gridiron / Campus football | offence / defence / specialists; QB ... K | offence / defence / special teams EPA | pass v rush EPA, early-down success v explosiveness |
| Paddock | drivers (one group) | qualifying / race pace | qualifying v race delta, tyre degradation v pace |
| Ace | ATP / WTA by surface | serve / return | serve points won v return points won (no teams page: tennis has no clubs) |

