# The Quant — kit v4 "Broadcast" (dark only)

The spec every sport site follows. It replaces v3 "Matchday". On 23 Oct 2026 the user first asked for dark mode only
("I want it in dark mode. I don't want the light stuff"), then chose the Broadcast concept for everything: "Switch
everything to the ESPN style view. I like the best. I know it will take longer but that is the best view you offered
me and it is worth it." There is one theme, dark, and no toggle.

The kit is in this folder. `showcase.html` shows every component on sample data (serve `docs/`, open
`/_design/showcase.html`). The reference pages are:
- the Home page (`docs/home`);
- the Rink overview, game, player and compare pages (`docs/rink/assets/js/rk-*.js`).

To move a page over, follow `MIGRATION_V4.md`.

## 1. Identity

**Name.** The Quant. Each site is "The Quant <Site>": Footballer, Paddock, Hardwood, Ace, Bullpen, Gridiron, Rink or
Campus. The logo is "THE QUANT" in Bebas Neue after a volt parallelogram. A site adds its name in its sport accent
("THE QUANT RINK").

**What it is.** A fun sports hub for people who like numbers: what to watch tonight, our forecasts, ratings and the
stats behind them, each explained. It is not a betting site. The headline is always our forecast, our rating or a
stat.

**Feel.** Broadcast energy, made our own:
- a black score ticker;
- team colours as big blocks, cut on a diagonal;
- giant Bebas numbers;
- all-caps headlines under a volt tag;
- hard edges, with no rounded corners and no soft shadows.

The friendliness comes from the copy: every number gets a plain-English line, and "What's that number?" strips sit
wherever a number needs one.

**What we borrow, and what we do not.**

| Source | We take | We never take |
|---|---|---|
| ESPN / broadcast | the score ticker, the scoreboard bug, team-colour blocks, giant scores, the power list | their red brand, logos, fonts, the bottom-line crawl |
| FiveThirtyEight | probability storytelling, "chance of" framing, annotated charts, the "how sure are we" honesty | their fox, typefaces, exact chart styling |
| Baseball Savant | percentiles against a peer group, cold-to-hot colour, last season marked | their slider artwork, MLB marks |
| Bloomberg | tabular figures and crisp tables where density helps | amber-on-black terminal trade dress |

No league, club, sponsor or publisher logos appear anywhere. Team marks are our own squares on the team colour, with
the abbreviation in Bebas. The only images are the club crests that football already shows.

## 2. Type

All fonts come from Google Fonts, in one link (the kit's `QK.FONTS_URL`; `QK.shell()` adds it when a page has not):
`family=Barlow+Condensed:wght@500;600;700;800&family=Barlow:wght@400;500;600;700&family=Bebas+Neue&display=swap`

| Role | Face | Where | Token |
|---|---|---|---|
| Display | **Bebas Neue** (capitals only) | scores, big numbers, chances, short headlines, card titles, short names | `--font-display`, `.qk-display` |
| Labels | **Barlow Condensed** 700–800, capitals, tracked 0.04–0.1 em | tags, kickers, nav, buttons, chips, table heads, axis labels, **long names** | `--font-cond`, `.qk-cond`, `.qk-long` |
| Body and numbers | **Barlow** 400–700 | body, ledes, notes, table cells (tabular figures) | `--font-ui`, `--font-num` |

**Long names.** Bebas has no lower case and sets long names too wide. A player, club or event name longer than the
slot allows (`QK.longName(name, max)`; the kit uses about 13–16 characters) switches to Barlow Condensed 800 in
capitals. Short names, scores and numbers stay in Bebas.

Tabular figures go wherever a number can change (`.num`, tables).

| Token | Size | Use |
|---|---|---|
| `--fs-h2` | 40–64 px | section titles (all caps, Bebas) |
| `.qk-sh.lg` | 48–96 px | page titles |
| player name | 64–150 px | the player hero (two lines) |
| `--fs-d3` | 38–60 px | stat numbers in the strip |
| `--fs-d4` | 40 px | chances and scores on game cards (the % at half size) |
| `--fs-lg` … `--fs-2xs` | 18 / 16 / 14 / 13 / 12 px | lede, body, dense body, labels, chips |

## 3. Colour (dark only)

The tokens live on `:root` only. `QK.theme.boot()` pins `data-theme="dark"`, so a site's old light CSS never
applies.

| Role | Token | Value |
|---|---|---|
| Page | `--bg` | #0a0c10 near-black |
| Broadcast black | `--block` (`--s-ink`), `--block-2` | #000000; #12151c (ticker, section nav, power-list cards) |
| Card / raised / pressed | `--s-1` / `--s-2` / `--s-3` | #14171d / #1c2028 / #262b35 cool charcoal; every card has a 5 px `--card-rule` (#2a303c) across the top |
| Ink | `--ink-1` / `--ink-2` / `--ink-3` | #f3f5f8 / #c3c9d4 / #939bab; on black blocks `--block-ink-2` #c3c9d4 and `--block-ink-3` #9aa3b2 |
| Ours | `--signal`, `--signal-deep` | cobalt #7d93ff (text, lines, the favourite's chance); #5a69b7 as a block carrying white type |
| Accent | `--volt`, `--volt-ink` | #d4ff3a: section tags, the stat-of-the-day slab, key numbers, the "it happened" series, the explain-strip rule, active nav. Text on volt is near-black |
| Live | `--live`, `--live-clock` | #ff4d2e; the score bug's clock block #c92d17 (white 5.4:1) |
| Neutral side | `--slate` | #3a4150: the side of a two-sided block with no colour, or the loser of a clash |
| LED off | `--seg-off` | #262c38 |
| Market (reference only) | `--c-market` | a quiet cool grey |

**Contrast (WCAG 2.x, measured).** Text clears AA on every surface:

| Text | On | Ratio |
|---|---|---|
| ink-3 | `--s-1` / `--s-3` | 6.4:1 / 5.1:1 |
| block-ink-3 | black / `--block-2` | 8.3:1 / 7.2:1 |
| cobalt | `--s-1` / black | 6.4:1 / 7.5:1 |
| volt | `--s-1` / black | 15.5:1 / 17:1 |
| live | `--s-1` / `--block-2` | 5.4:1 / 5.5:1 |

Text on the scale colours and on team monograms takes white or pure black, whichever is higher (`QK.color.ink`,
`QK.pctInk`). Pure black clears 4.58:1 even at the scale's mid-tones, where near-black only reaches 4.43:1. White
type on a team block is at least 4.6:1 through `QK.color.block` (below).

A contrast audit of rendered pages (text against its real background) is the check, not the token table.

**Ours.** Blue (cobalt) means ours:
- our probability, our rating and the forecast line;
- the favourite's chance on a card;
- primary actions and links.

It never marks a team, the market, or good and bad. In copy, say "ours in blue".

**Market.** Never on overviews or cards, never in a headline stat, never on the Home page. It may appear only as a
quiet reference, with its source named:
- on game detail: a black line under the hero, "Market (source) X% · a reference, not our forecast";
- on the Model page: a muted column.

Game cards default to `market: false`.

**Percentile scale (cold → hot).** It runs `--pc-0` blue #2f6fe0 → #7fa6e6 → `--pc-50` cool grey #a9adb5 → #f59a72
→ `--pc-100` red #d9361d. It steps in lightness, so it reads for red-green colour-blind viewers. Use `QK.pctColor(p)`
in HTML, `QK.pctHex(p)` in charts and `QK.pctInk(p)` for text on it. The LED meters light each segment in the colour
of its own position on the scale, so a 99th-percentile row runs blue to red.

**Team colours: the rules** (`QK.color`).
1. **Blocks** (the hero, the bug, the tape heads, title-race bars, the player hero) use `block(hex)`:
   - the kit is darkened, keeping its hue, until white type clears 4.6:1 (`deep(hex, min)`);
   - **pale kits** (luminance over 0.7: white, silver, cream, pale yellow) become a slate block with a 6 px rule in the
     kit colour along the foot. This is the pale-kit rule;
   - a kit that vanishes into the page (navy, black: under 1.5:1 against `--bg`) keeps its colour and gets that rule
     in the kit lifted to 3:1.
2. **Two sides together** use `blockPair(a, b, { fav })`. Two blocks must differ by 1.4:1 in lightness or 50° in hue
   (grey floor 0.1 saturation; red v green always clashes). A clash gives the second side its alternate colour
   (`team.alt`), else slate with the kit as its rule. **F1 team-mates** share a constructor colour, so the second
   driver falls to slate with the constructor colour as the rule.
3. **No colour at all** follows the tennis rule (one rule for every sport): the side we favour is cobalt and the other
   is slate; with no favourite, left is cobalt and right is slate. We never use a nation's flag colour.
4. **Football clubs** take club colours where the data has them (`colour`, `alt`), else rule 3. The build merges
   three layers: Sofascore's `teamColors`, hand-checked overrides, then the crest's dominant colour
   (`docs/site/UNIFIED_PAYLOADS.md`).
5. **Marks and chart lines** (monograms, stripes, dots, lines) use the kit as it is, lifted to 3:1 on the card
   (`color.team`). A monogram that would vanish into the card gets an inset outline (`markOutline`). Two kits side by
   side must be distinct (`color.distinct`), else cobalt v grey (`--wp-a` / `--wp-b`).

**Sport accents** (`--a-<sport>`) are identity marks only: the site word in the logo, the ticker group icon, the
sport tile's top rule.

**Chart slots** start with cobalt: `--c-1` cobalt, `--c-2` red-orange, `--c-3` cyan, `--c-4` volt and so on. A "we
said / it happened" pair is cobalt (`--c-model`) with volt (`--c-actual`).

## 4. Space and shape

- **Broadcast hard edges.** No radii (`--r-*` are 0, including `--r-pill`) and no soft shadows. Circles are kept only
  for live dots and chart dots.
- **Cards** are charcoal with a 5 px rule across the top. An explained card (`.cream`) has a 6 px volt rule on its
  left instead.
- **Signature blocks** are cut on a diagonal:
  - the hero's two sides (70 px);
  - section tags (10 px);
  - the stat-of-the-day slab (36 px);
  - the first stripe on a game card;
  - title-race bar ends;
  - LED segments (−14°).
- **Grid.** The page is 1320 px wide with a 24 px gutter (16 px on phones) and 56 px between sections (40 on phones).
  Black tiles sit 2 px apart.
- **Full bleed.** `.qk-bleed` blocks run edge to edge (the player hero, the stat strip, the black band). `QK.shell()`
  keeps `--qk-sbw` (the scrollbar width) so 100vw never widens the page.
- **Phones.** Nothing may widen the page at 375 px. Wide tables scroll inside their card, and one-column grids are
  `minmax(0, 1fr)`.

**Page rhythm.**
1. The ticker, then the hero (the game to watch, or the player).
2. The black strip of big numbers.
3. The story: what to watch, the power list, how sure we are, the race.
4. The detail: tables and charts.

Keep the number before the chart and the chart before the table.

## 5. Components

All builders return HTML strings unless noted. Signatures are in `quant.js` / `quant-charts.js`, and
`showcase.html` shows each one.

**New in v4 (Broadcast)**

| Component | Builder | Where |
|---|---|---|
| Diagonal split hero | `QK.splitHero(g, { kicker, tag, chip, nick, sub, homeFirst, noun, note, foot, meters, link, compact, blocks })`; two chances that do not add to 100% (F1: each driver against the field) get two separate meters in the foot, never a split bar | Home, overviews (through `QK.featureCard`), game pages (through `QK.previewCard`) |
| Scoreboard bug | `QK.scorebug(g, { size: 'xl' })` (= `QK.scorebugXL`) | "What to watch tonight" on player and team pages (`QK.previewCard(g, { layout: 'bug' })`) |
| Tale of the tape | `QK.tape({ left, right, rows / groups, wins, colors, fav })` (`fav`: with no colours the favourite is cobalt, as on the hero); `QK.compareView` (two entities) and `QK.matchupBar` draw it | player pages, compare pages, game pages |
| LED meter | `QK.meter(p, { prev, style })`; every `QK.pctlBars` / `QK.pctRail` row | player pages |
| Explain strip | `QK.explain(html, { title })` | "What's that number?", "How sure are we?" under any number |
| Black band | `QK.band(html)` | the power list, any black section |
| Stat strip | `QK.statStrip(list)`; `QK.playerHeader({ strip })` | under a hero |
| Quadrant | `QKC.quadrant(el, { points, xName, yName, refX, refY, corners })` | "Who's for real?" |
| Outlined number, long names | `QK.outlineNum(n)`, `.qk-outline`; `QK.longName(name, max)`, `.qk-long` | jersey numbers, ranks; long names |
| Team-colour rules | `QK.color.deep / block / blockPair / markOutline` | anything drawing a team block |
| Small % | `QK.pctSmall(p)` | Bebas chances with a half-size % sign |

**v1–v3 builders, now in Broadcast (same API)**

| Component | Builder | v4 look |
|---|---|---|
| Shell | `QK.shell(opts)` | black top bar, "THE QUANT" with the volt mark, condensed sport tabs with a volt underline, the section nav on `--block-2` |
| Ticker | `QK.ticker(games, o)` | `--block-2`, condensed, our pre-game chances in volt, the live period in red-orange |
| Section head | `QK.sectionHead(o)` | the kicker as a volt tag on a black parallelogram, the title in all-caps Bebas (40–64 px); on a black band the tag is volt with black type |
| Game card | `QK.gameCard(g, o)` | an 8 px stripe in the two team colours split by our chance; the league and time in condensed caps; 52 × 40 squares; Bebas scores and chances (favourite in blue); the foot "Our chance · why" (live: "Chance to win now · ..."); the bar under the rows only with `bar: true`; `homeFirst: true` lists the home side first (football) |
| Win bar | `QK.wpBar(...)` | square team-colour segments, condensed labels |
| Chance bars | `QK.chances(rows, o)` | the team square, a bar block in the team colour with the name inside in white, our chance in Bebas |
| Stat tile | `QK.statTile`, `QK.stats` | black blocks 2 px apart, the label in condensed caps, the number in Bebas, the percentile as a square "97th pctl" chip under it |
| Player header | `QK.playerHeader(o)` | the full-bleed team-colour block with the alternate colour on a diagonal behind a volt stripe, a huge outlined number, the name on two lines, chips; `strip` adds the black strip, `short` the explain strip |
| Percentile card / rail | `QK.pctCard`, `QK.pctRail`, `QK.pctKey` | LED meters (20 segments, ▼ last season, the percentile in a box on the scale colour, the value right); early metrics get a dashed box |
| Leaderboard | `QK.leaderboard` | square heat cells, condensed heads |
| Compare | `QK.compareView(o)` | two: the tale of the tape (`layout: 'table'` keeps the grid); three: a table with entity blocks and the volt stroke under the best |
| Greeting | `QK.greeting(o)` | a broadcast lower third (volt date tag, the line in Bebas, the lede, buttons), the side full width below |
| Feature card | `QK.featureCard(g, o)` | the diagonal split hero (`scribble` becomes its volt tag) |
| What to watch | `QK.watchGrid` | a grid of the game cards; title it "Six games. Our calls." |
| Who's hot | `QK.hotRow(items, { rank })` | the black power list: outlined rank numbers, the sport in volt, the name in Bebas, the big number, the unit and next best, the line on what it means |
| Stat of the day | `QK.statOfDay` | the volt slab with the big number, cut on a diagonal; the kicker in cobalt |
| New here | `QK.newHere(o)` | the "What's that number?" strip with three numbered points |
| How sure | `QK.howSure(el, o)` | three black big-number blocks (checked, the most common call, the Brier score) over the "we said / it happened" bars (`style: 'dots'` keeps the v3 diagonal) |
| Short version | `QK.shortVersion` | the explain strip |
| Preview card | `QK.previewCard(g, o)` | the split hero (or `layout: 'bug'`), the market line on game detail only, the "How sure" strip, the factors as Bebas numbers with the label between |
| Score bug (compact) | `QK.scorebug(g)` | black, the clock on red, team edges |
| Verdicts | `QK.verdicts` | black blocks with a volt top rule, the title in Bebas |
| Note, aside, mark | `QK.note`, `QK.aside`, `QK.mark` | the explain strip on `--s-2`; ▸ in volt; the key phrase in volt |
| v1 (kept) | `QK.kpi`, `QK.matchCard`, `QK.tick`, `QK.mvm`, `QK.table`, `QK.tableHTML`, `QK.pctlBars`, `QK.pctlChip` | restyled |

Glossary tooltips stay: any `data-tip`, and every known column abbreviation (`QK.GLOSS`). Tooltips are black with a
volt edge.

`QK.now()` is the page clock. `?asof=<ISO>` pins it to preview an older local snapshot; the live sites never pass it.

## 6. Charts

There is one library, ECharts 5.5.1, and everything themes from the tokens.
- **Axis titles always** (the standing rule): every value axis says what it measures and its unit. The checker fails
  a page with an untitled value axis.
- **Grid and type.** Solid cool gridlines (`--grid`), 2 px axis lines where a chart has a baseline (`--axis`), axis
  labels in Barlow Condensed 600 (`--ink-3`) and axis titles in Barlow Condensed 700 (`--ink-2`). Data labels are
  Barlow Condensed; big value labels are Bebas.
- **Colour.** Cobalt for ours, the first series. Volt for what happened beside it. Red-orange and cyan for the next
  series, and team colours for teams. Bars and legend keys are square.
- **Annotations** are Barlow Condensed bold (`QKC.annot(T)`). Quadrant and corner names are cobalt capitals. Write
  on the chart instead of a legend wherever a mark can carry its own words.
- **Calibration** (`QKC.calibration`): per forecast bucket, a cobalt "We said" bar beside a volt "It happened" bar.
- **Quadrant** (`QKC.quadrant`): team-colour dots with their abbreviations, dashed references, and the four corners
  named ("The real deal", "Winning on luck?", "Due a run", "Struggling").
- **538-style forecast lines** (`QKC.forecast`) keep end labels, bands and a "Today" rule.
- **Uncertainty is shown, never implied.** Never invent an interval the payload lacks.
- **The market** is never a filled bar or a second line: only a tick or a hollow ring, and only where §3 allows.
- **Tooltips** are black with a 4 px volt edge.

## 7. Motion

Motion is subtle:
- bars grow once and the live dot pulses;
- a link card's top rule turns volt on hover;
- the stat of the day rotates slowly and pauses on hover.

There are no count-up numbers and no auto-scrolling ticker. `prefers-reduced-motion` turns motion off.

## 8. Copy

**Voice.** A friendly analyst at the bar: plain words first, the number second, the method a tap away.
- Every number gets a line on what it means ("70% still misses 3 times in 10") and on how sure we are.
- Headlines are short and punchy, in capitals by type, not by typing: write them in sentence case and Bebas sets the
  capitals.
- British spelling.

**Times and dates (one convention, 23 Oct 2026).** Every time and date is en-GB, 24-hour, in the viewer's own time
zone: "16:00", "Mon 19 Oct", "Today · 19:30", "Sat 18:30". Never the browser locale's "04:00 PM" or "Mon, Oct 19",
and no zone label: the clock is always the viewer's own. The kit's `QK.fmt.time` / `QK.fmt.date` / `QK.whenShort`
apply it on the hero, the score bug, game cards and the ticker; site code formats through them, never through
`toLocaleString()` with no locale.

**Patterns.**
- **Section titles say the story:** "Six games. Our calls.", "We say it. Then we check it.", "Who lifts the Cup?",
  "Results v chances", "The leaderboard, one sport at a time", "Every game this season".
- **Tags (kickers) say the section:** "What to watch tonight", "Who's hot", "How sure are we?", "Who's for real?",
  "Title race", "Tale of the tape", "Game log", "Last game".
- **Foot of a game card:** "Our chance · A coin flip: our closest call on the slate."
- **Under a live hero:** "What's that number? Our live chance updates with the score and the clock. Before the start
  it was 55% ..."
- **Player pages:** "The short version" (two or three plain sentences, including the weak spot). "How sure are we?"
  names the sample: "Eight games is a small sample."

**Words we use:** chance, our chance, forecast, projection, rating, expected, likely range, percentile, peers,
"from 20,000 simulated seasons", "how sure are we".

**Words we do not use** in headlines, KPIs, labels, buttons or chart titles: odds (in our own copy), priced, price(s),
pricing, edge, value bet, gap v market, biggest gap, model v market (as a headline), mispriced, lock, fade, sharp,
line value. Exceptions are proper names (NHL EDGE tracking data), the legal footer and terms, and the game detail and
Model pages, where a "Market" reference may sit beside ours. Never say "fair odds"; say "our chance".

**Neutral labels:** no player pronouns in UI copy ("the player", "Their type"). Real names and quoted text stay as
they are.

**Legal terms (one decision for every site, 23 Oct 2026).** Each site's disclaimer and terms panel is the
`<template id="disclaimer-template">`, and its outermost element carries the class `qk-legal`. The panel keeps its
legal substance:
- information and entertainment only;
- not betting, financial or professional advice;
- no bets accepted;
- provided "as is";
- 18+ and responsible gambling.

The checker's `--banned` scan skips `.qk-legal` and nothing else.

## 9. Comparisons (metrics)

Percentiles, leaderboards, the tale of the tape and "most similar" lists use the sport's metric set from
`docs/METRICS_SPEC.md` (`docs/_design/metrics/<sport>.json`, copied to `assets/qk/metrics/`):
- peers are the same position or role, with a sensible sample floor;
- metrics are stable and predictive;
- a metric still short of its stabilisation sample has a dashed box ("early");
- the ▼ marks last season's percentile in the same peer group (`prev_pct_pos`).

## 10. Accessibility

- **Contrast** as §3: AA for text on every surface, and white on team blocks at 4.6:1 or better. Marks are 3:1 or
  better.
- **Identity never by colour alone:** numbers beside bars, letters in form squares, abbreviations on dots, words on
  the bug.
- **Keyboard:** a skip link, volt focus rings, arrow-key tabs, sortable headers as buttons, tooltips on focus.
- **Images:** charts and meters carry `role="img"` and a label.
- **Checks:** every page is checked at 1440 and 375 px, dark only, with the checker and the contrast audit.
