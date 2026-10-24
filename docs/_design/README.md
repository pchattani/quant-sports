# The Quant design system (kit v4 "Broadcast", dark only, Oct 2026)

> v4 replaced v3 "Matchday" on 23 Oct 2026, when the user picked the Broadcast concept for everything: Bebas Neue,
> Barlow and Barlow Condensed; black blocks, team colours as diagonal blocks, volt tags, hard edges; dark only. The
> spec is `STYLE_GUIDE.md`, the move guide `MIGRATION_V4.md` (`MIGRATION_V3.md` and `MIGRATION_V2.md` are history);
> `showcase.html` shows every component. The rest of this file is the older kit reference and still holds for the
> v1/v2 APIs, which are unchanged.

One look for every sports site: Bloomberg density, ESPN scoreboard energy, 538 probability stories and Savant
percentile cards, in a look of our own. Dark first with a light mode, our numbers in one signature violet, the market
a quiet grey reference. Framework-free: four static files and one CDN chart library.

**v2 docs:** `STYLE_GUIDE.md` (the spec: identity, type, colour, components, charts, motion, copy),
`MIGRATION_V2.md` (moving a page to v2, old → new map, copy changes), `showcase.html` (every v2 component on sample
data; not shipped). The reference pages are `docs/home` and the Rink overview, game, player and compare pages.
Everything below is the v1 reference, still valid: every v1 call works and renders in the v2 look.

Living style guide: `docs/_design/index.html` (serve `docs/` and open `/_design/`; add `?theme=light`
or `?theme=dark` to force a theme). Every component on that page is the real kit.

| File | What it is |
|---|---|
| `tokens.css` | Design tokens: colour (dark + light), sport accents, chart palette, type scale, spacing, radii, shadows, motion |
| `quant.css` | Base styles and every component, all prefixed `qk-` so the kit can sit beside a site's old CSS during migration |
| `quant.js` | `window.QK`: shell (top bar, sport switcher, section nav, search, footer), theme, tables, tabs, chips, match cards, ticker, team marks, colour/contrast, sparklines, formatting, fetch |
| `quant-charts.js` | `window.QKC`: the chart kit on Apache ECharts 5.5.1 |
| `plotly-ec.js` | optional: `window.Plotly` (newPlot, react, purge, relayout, `plotly_click`) drawn by ECharts on the tokens, for views still written against Plotly. Load it after `quant-charts.js`, or inject it on first use (Hardwood, Rink); no site loads the Plotly CDN any more |
| `league.js` | `window.QKL`: the league pages' module for the US sports (Rink, Hardwood, Gridiron, Bullpen): how the race is shaping up (chances over time from the race log, movers with reasons, magic numbers, schedule left, the games that matter), the team card (chips and percentile meters, expandable under a standings row) and the shape of the league (offence v defence, record v the numbers, tiers), drawn from `season.json["league"]` (`oddsmarkets/common/league.py`). Load it after `quant-charts.js` |
| `index.html`, `guide.js` | The v1 style guide (not copied into sites) |
| `showcase.html`, `showcase.js` | The v2 showcase (not copied into sites) |
| `STYLE_GUIDE.md`, `MIGRATION_V2.md` | The v2 spec and the migration guide |

## Adopting the kit in a site

### 1. The build copies the kit
Each site's build copies the kit files (`KIT_FILES` in `scripts/design_kit.py`) into `docs/<site>/assets/qk/`, exactly as it copies `base.css` today:

```python
from design_kit import copy_kit          # scripts/design_kit.py
copy_kit(DOCS / "rink")                  # -> docs/rink/assets/qk/{tokens.css, quant.css, quant.js, quant-charts.js, plotly-ec.js, league.js}
```

`scripts/build_home.py` already does this for `docs/home/`. Never edit the copies; edit `docs/_design/` and rebuild.

### 2. The HTML shell

```html
<!doctype html>
<html lang="en" data-sport="hockey">             <!-- football | f1 | basketball | tennis | baseball | nfl | hockey | college -->
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark light">
  <title>The Quant Rink</title>
  <!-- no flash of the wrong theme: the viewer's pinned choice applies before CSS paints -->
  <script>try{var t=localStorage.getItem('qk-theme');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}</script>
  <link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..900&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap">
  <link rel="stylesheet" href="assets/qk/tokens.css">
  <link rel="stylesheet" href="assets/qk/quant.css">
  <link rel="stylesheet" href="assets/rink.css">  <!-- site-specific layout only, written against the tokens -->
</head>
<body class="qk">
  <div id="qk-shell"></div>
  <main id="main" class="qk-page"> … </main>
  <div id="qk-footer"></div>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js" defer></script>
  <script src="assets/qk/quant.js" defer></script>
  <script src="assets/qk/quant-charts.js" defer></script>
  <script src="assets/js/core.js" defer></script>  <!-- the site's router, unchanged -->
</body>
</html>
```

### 3. The JS API

```js
var shell = QK.shell({
  sport: 'hockey',                        // sets the accent, marks the switcher
  section: 'overview',                    // one of QK.SECTIONS keys
  sections: QK.sections('hockey'),        // the nine-section IA; override hrefs to match the site's routes:
  // sections: QK.sections('hockey').map(function (s) { s.href = '#/' + (s.key === 'overview' ? '' : s.key); return s; }),
  ctx: '<select class="qk-select">…seasons…</select>',   // optional, right of the section nav
  search: { load: function () { return Promise.resolve(rows); } }  // rows: [{ sport, t, s, href }]
});
shell.setSection('teams');               // call from the router on every route change
shell.setLive({ hockey: true });         // live dot on the switcher
```

The section links scroll inside their own row (`.qk-secnav-links`); `ctx` sits to their right on desktop and on a
second row of its own at 720 px and below, so a league or season switch is reachable on a phone without scrolling
the nav sideways. Nothing in the shell (switcher, section nav, context) can widen the page: at 375 px
`body.scrollWidth` equals the viewport. Search rows may carry a weight `w` (higher first) that ranks matches which
start equally well, e.g. a star before a namesake in the reserves.

Information architecture (REDESIGN.md), same order everywhere: Overview · Fixtures · Standings · Teams ·
Players · Value & Moves · Fantasy · Lab · Model. `QK.sections()` relabels per sport (F1: Races / Constructors /
Drivers; tennis: Draws / Rankings, no Teams; US sports: Games) but never reorders. Pass an override map as the
second argument to relabel or hide (`null`) a section.

Components (HTML classes + helpers):

| Component | Use |
|---|---|
| App shell | `QK.shell()` — sticky top bar (brand, 7-sport switcher with live dots, search on `/` or Ctrl K, theme toggle), sticky section nav, skip link, footer |
| Layout | `.qk-page`, `.qk-grid` + `.qk-span-{3..12}` (collapses at 1100/720 px), `.qk-auto` (`--min`), `.qk-section`, `.qk-section-head`, `.qk-hscroll` |
| Card | `.qk-card` (`.is-link`, `.accent-top`) with `.qk-card-head/-title/-sub/-body/-foot` |
| KPI tile, sparkline tile | `QK.kpi({label, value, sub, delta, spark, text, tip, accent, cls, html})` — `html: true` takes value and sub as HTML (links, marks); values wrap and step down on phones, never ellipsis; `QK.spark(values, opts)` (inline SVG) |
| Table | `QK.table(el, {columns, rows, sort, rank, dense, maxHeight})` — sticky header, sortable buttons with `aria-sort`, pinned first column (`sticky: true`), percentile chips (`pctl: 'key'`); a column with `raw: true` / `year: true` / `fmt: 'raw'` (or a key like `year`, `season`) prints 2026, not 2,026 |
| Static table | `QK.tableHTML(cols, rows, {cls, id, maxHeight, sticky, caption})` returns kit table HTML (cells `{v, html, cls, align, title}`; `v` sorts); `QK.sortable(el)` wires header sorting and `data-href` row links on every such table under `el` |
| Percentiles | `QK.pctlChip(p)`, `QK.pctlBars([{label, pctl, value}])` |
| Tabs / segmented / chips | `QK.tabs(root, cb)` (arrow keys), `QK.seg(root, cb)`, `QK.chips(root, cb, multi)` |
| Inputs | `.qk-select`, `.qk-input`, `.qk-btn` (`.primary`) |
| Match / game card | `QK.matchCard(game)` — status, teams, model probability, probability bar, model-v-market strip and "Edge" badge (pre-game only) |
| Score ticker | `.qk-ticker` filled with `QK.tick(game)` |
| Team / player header | `.qk-hero` with `--tc` (team colour), `.qk-hero-stats`, `.qk-avatar`, `QK.teamMark(team, 'lg')` |
| Badges | `.qk-badge` (`.live`, `.final`, `.accent`, `.edge`), `.qk-sportpill` |
| Loading / empty | `QK.skeleton('lines'|'card'|'chart', n)`, `QK.empty(title, text)` |
| Tooltips | any element with `data-tip="…"` (hover and keyboard focus); `.qk-note` for inline notes |

The game shape every card, ticker and adapter shares:

```js
{ sport, league, id, start /* ISO UTC */, status: 'pre' | 'live' | 'final',
  home: { name, abbr, colour, logo, href }, away: { … }, hs, as,
  p_home, p_draw, p_away, market_home, note, period, clock, href }
```

### 4. Charts

One library: **Apache ECharts 5.5.1** from jsDelivr. Why ECharts over the Plotly the sites use now:
it is about a third of Plotly's size (1.0 MB v 3.5 MB minified), renders on canvas so dense pages stay smooth on
phones, has first-class touch tooltips, end labels, label de-overlap, heatmaps, visual maps and custom series
(the dumbbell), and it can be themed completely from our tokens at render time. Plotly can be themed too, but its
chrome (mode bar, hover boxes, legends) is what made the sites look dated, and its bundle is the heaviest asset on
every page.

```js
QKC.line(el, { x, xType: 'category' | 'value' | 'time', series: [{ name, data, color, dash, area,
  band: { lo, hi }, err | lo + hi }], bands, yFmt, ref: { y } | { x }, yInverse, endLabels, xTicks, yTicks });
QKC.bar(el, { cats, series: [{ name, data, lo, hi /* whiskers */, market /* tick */ }], horizontal, labels, fmt,
  colors, legendItems: [{ name, color }], hrefs, diverging, stack, valTicks });
QKC.dumbbell(el, { rows: [{ label, a, b, href }], aName: 'Model', bName: 'Market' });   // model v market
QKC.range(el, { rows: [{ label, lo, hi, mid, href }], loName, hiName, midName, fmt });   // floor to ceiling
QKC.butterfly(el, { cats, left: { name, data, color }, right: { name, data, color }, fmt });
QKC.scatter(el, { points: [{ x, y, name, color, label, href }], refX, refY, quadrants, labelTop,
  yInverse, xInverse, diagonal: true | { label }, legendItems });
QKC.heatmap(el, { x, y, data: [[xi, yi, v]], diverging, mid, labelMin, labelIf });     // label ink by contrast
QKC.winProb(el, { t, p, home, away, events: [{ t, p, label }], periods, tMin, tMax, interval, tFmt, tLabel,
  step, compare: { name, t, p }, xType: 'value' | 'time' });                           // numeric x axis
QKC.shotMap(el, { surface: 'pitch' | 'rink' | 'court' | 'field', shots: [{ x, y, v, made, name }], sizeScale });
QKC.mount(el, function (T) { return echartsOption; });   // anything else, built from tokens T
```

Custom tick labels: `QKC.axis(T, { ticks: { values, labels } })` puts labels at exactly those values, and
`QKC.mount` widens the grid for them (ECharts' containLabel measures only the default ticks). Legends always
show the colour the marks use: series carry their colour, and per-bar or per-point colours get legend entries
through `legendItems` (or `QKC.legendSeries(T, items)` in a hand-built option). Never pair a line series with a
piecewise `visualMap` — ECharts 5.5.1 throws a "coord" error on some data; colour by side with area fills
(`areaStyle.origin`) or two series, as `winProb` does.

Surfaces are SVG in real units (pitch 105 × 68 m; rink 200 × 85 ft centred; half court 50 × 47 ft with the
basket at 0,0; field in feet from home plate) drawn behind a scatter on the same axes. Every chart repaints
when the theme changes, resizes with its container, honours reduced motion, links points with `href`
on click, and shows a message (not a blank box) if the CDN fails. Views still written against Plotly load the
kit module `assets/qk/plotly-ec.js`, which draws `Plotly.newPlot(el, traces, layout)` with ECharts on the same
tokens, so no page needs the Plotly bundle; migrate them to QKC chart by chart.

## Design decisions

- **Dark first, light selected, not inverted.** Each theme has its own surface, ink and chart steps. The
  page follows the OS until the viewer clicks the toggle, which is then remembered (`localStorage['qk-theme']`).
- **Sites not launched yet.** An entry in `QK.ALL_SPORTS` with `pending: true` (The Quant Campus, Oct 2026) is left out
  of `QK.SPORTS` (switcher, footer, home tiles) except on its own pages (`data-sport` set on `<html>`) and in local
  preview (`QK.localBase()`); `QK.sport(key)` still finds it. Launching = removing the flag.
- **v2: the signal + one identity accent per sport.** The signal violet (`--signal`; `--brand` points at it) marks The Quant and *ours* (forecasts, primary actions). v1 used amber here. The rest of this bullet is v1: each site sets `data-sport`
  and its accent (`--a-<sport>`) colours the nav underline, section rules and tiles. Accents mark identity
  only; text beside them stays ink.
- **Chart colour by job.** Categorical slots in a fixed order (the validated reference palette); slot 1
  (blue) is always the model and slot 2 (orange) the market, on every site. Sequential is one hue; diverging
  is red / grey / blue. Status colours are reserved and always carry a label.
- **Team colours, contrast-checked.** `QK.color.team(hex)` raises lightness in HSL (hue kept, so a navy
  becomes a brighter blue, not grey) until a kit colour reaches 3:1 on the card; `QK.color.ink(bg)` picks
  white or black text for monograms. Where two kits are too alike the bar falls back to blue v orange.
- **Numbers in mono.** Inter for words; JetBrains Mono with tabular figures for scores, odds, tables and axes.
- **v1: model v market everywhere** (v2: ours first, the market a quiet grey ring or tick; no gap or edge labels). A shared strip (blue dot model, orange dot market, the gap between) on game
  cards and a dumbbell chart for lists. Shown before games only: a live market has moved with the score and
  the pre-game model has not.

## Accessibility

Text contrast (dark card): primary 16.9:1, secondary 8.4:1, muted 4.9:1 — muted is the floor for text. Marks
reach 3:1. Identity is never colour alone (legends, end labels, abbreviations on marks). Keyboard: skip link,
visible focus rings, arrow-key tabs, sortable headers are buttons, search palette with arrows/Enter/Esc.
`prefers-reduced-motion` stops pulses, shimmer, lifts and chart animation. Charts carry `role="img"` and a label
and sit beside a table or list with the same numbers. Forced colours and print fall back cleanly. Layouts are
checked at 375 px (no horizontal page scroll; wide tables scroll inside their card).

## Rules shared with the sites

No `?.` or `??` (older browsers); parse every file with esprima before shipping
(`uv run --quiet --with esprima --no-project python -c "import esprima; esprima.parseScript(open('docs/_design/quant.js',encoding='utf-8').read())"`).
Storage access is wrapped so private mode never breaks a page.

## The home page (`docs/home/`)

`python scripts/build_home.py` reads the local sport data trees (`docs/site/data`, `docs/paddock/data`, …),
writes `docs/home/data/home.json` (~85 KB: games, futures, leaders, chart series, stats of
the day, per-sport tiles) and `docs/home/data/search.json` (~4,400 teams, players, drivers and competitions,
loaded only when search opens), and copies the kit. A missing or broken sport is skipped and logged. Links point
at the public GitHub Pages sites; `--links local` points them at `../site/`, `../paddock/` … for preview.

Live scores: the page itself polls each sport's published `index.json` (football: `hub.json`) once a minute while
one of its games is live or about to start. GitHub Pages sends `Access-Control-Allow-Origin: *` (checked
17 Oct 2026 on all seven sites), so no proxy or per-sport `home.json` is needed. If a fetch fails the page keeps
the built snapshot. `QK.HOME_URL` is https://pchattani.github.io/the-quant/: the Pages repo pchattani/the-quant,
deployed by the `home.yml` workflow of the public build repo pchattani/quant-sports (docs/HOSTING_MIGRATION.md).
