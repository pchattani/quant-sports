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
  - `howSure`: big numbers over the "we said / it happened" bars;
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
