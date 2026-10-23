# The Quant — kit v3 "Matchday" (dark only)

The spec every sport site follows. It replaces v2 "Signal" (a dark, dense terminal the user found neither different
nor friendly enough). The user chose **Matchday + bits** on 23 Oct 2026, then asked for it **in dark mode only**: no
light theme, no theme toggle. Later that day the user swapped the colours for the Broadcast concept's dark palette
("more fan of what you had in the ESPN one"): near-black, cobalt for ours, volt accents, team colours up front. The
layouts, type and copy stay Matchday. The kit is in this folder; `showcase.html` shows every component on sample data; the
reference pages are the Home page (`docs/home`) and the Rink overview, game, player and compare pages (`docs/rink`).
To move a page over, follow `MIGRATION_V3.md`.

## 1. Identity

**Name.** The Quant. Each site is "The Quant <Site>" (Footballer, Paddock, Hardwood, Ace, Bullpen, Gridiron, Rink,
Campus). The logo is the lower-case word mark "the quant" in Fraunces with a volt dot and a cobalt offset; a site adds
its name in italic in the sport accent ("the quant *rink*").

**What it is.** A fun sports hub for people who like numbers: what to watch tonight, our forecasts, ratings and the
stats behind them, each explained. It is not a betting site. The headline is always our forecast, our rating or a stat.

**Feel.** Bright, roomy and explained. Friendliness comes from the type (Fraunces), the spacing, the round cards and
the copy; energy comes from the Broadcast colours (near-black, cobalt, volt, team colours). It must never slide back
into the dense terminal look.

**What we borrow, and what we do not.**

| Source | We take | We never take |
|---|---|---|
| FiveThirtyEight (the base) | probability storytelling, "chance of" framing, annotated charts, friendly explanations, the "how sure are we" honesty | their fox, typefaces, exact chart styling |
| Baseball Savant (via the Notebook concept) | the percentile slider rail against a peer group, cold-to-hot colour, a hollow ring for last season | their red-blue exact ramp and slider artwork, MLB marks |
| ESPN / broadcast (via the Broadcast concept) | the black score ticker, the live score bug, team colours as accents | the red brand, their logos, the bottom-line crawl |
| Bloomberg | tabular figures and crisp tables where density helps | amber-on-black terminal trade dress |

No league, club, sponsor or publisher logos anywhere. Team marks are our own round monograms on the team colour.

## 2. Type

From Google Fonts only. One link (the kit's `QK.FONTS_URL`; `QK.shell()` adds it when a page has not):
`family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&family=Fraunces:ital,opsz,wght,SOFT,WONK@0,9..144,400..800,0..100,0..1;1,9..144,400..700,0..100,0..1`

| Role | Face | Where | Token |
|---|---|---|---|
| Display | **Fraunces** 600–650, `SOFT 100` | headlines, section titles, card titles, big numbers, chances, scores | `--font-display`, `--fvs-display` |
| Italic display | **Fraunces** italic 400 | asides, chart annotations, the "at" between two teams, stickers | `.qk-aside`, `QKC.annot(T)` |
| UI and numbers | **DM Sans** 400–800 | body, labels, buttons, tables, axis labels | `--font-ui`, `--font-num` (with tabular figures) |

Tabular figures wherever a number can change (`.num`, `.qk-num`, tables). Labels are sentence case, never all caps,
except the broadcast ticker's tiny group labels.

| Token | Size | Use |
|---|---|---|
| `--fs-d1` | clamp(2.4, 5.6vw, 4) rem | the greeting headline |
| page h1 (`.qk-sh.lg`) | clamp(2.1, 4.6vw, 3.4) rem | page titles, player names |
| `--fs-h2` | clamp(1.6, 3.2vw, 2.25) rem | section titles |
| `--fs-d3` | clamp(1.75, 2.8vw, 2.5) rem | stat-tile numbers |
| `--fs-d4` | 1.375 rem | chances on game cards |
| `--fs-lg` … `--fs-2xs` | 19 / 16 / 14 / 13 / 12 px | lede, body, dense body, captions, chips |

## 3. Colour (dark only, Broadcast palette)

There is one theme. The tokens live on `:root` only; `QK.theme.boot()` pins `data-theme="dark"` so a site's old
light-mode CSS never applies, and a stored "light" choice is forgotten. `QK.theme.get()` always returns `'dark'`;
`set()` / `toggle()` keep working for old callers but change nothing.

| Role | Token | Value |
|---|---|---|
| Page | `--bg` | #0a0c10 near-black |
| Card / raised / pressed | `--s-1` / `--s-2` / `--s-3` | #14171d / #1c2028 / #262b35 cool charcoal |
| Cream card (New here, The short version, How sure) | `--s-cream`, `--line-cream` | #181c24 with a faint volt rule |
| Broadcast black (ticker, score bug) | `--s-ink` | #000000 |
| Ink | `--ink-1` / `--ink-2` / `--ink-3` | #f3f5f8 / #c3c9d4 / #939bab |
| Hairlines | `--line-1` / `--line-2` / `--line-3` | cool grey at 8% / 13% / 26% |
| Ours | `--signal` (= `--c-model`, `--brand`) | periwinkle cobalt #7d93ff; text on a cobalt fill is near-black |
| Accent | `--volt` (old name `--sun`), `--sun-soft` | #d4ff3a: kickers (section tags), the stat-of-the-day slab, the compare highlighter, the "i" of a note, "it happened" beside ours (`--c-actual`); text on volt is near-black (`--volt-ink`) |
| Live | `--live` | red-orange #ff4d2e |
| Other accents | `--coral`, `--sky`, `--plum` | red-orange #ff6a4d (asides' arrow, a second series); cyan #5ec8f0; plum |
| Market (reference only) | `--c-market` | quiet cool grey |

**Contrast (WCAG 2.x, measured on `--bg` to `--s-3`).** Text on every surface clears AA: ink-1 13.0–17.9:1, ink-2
8.5–11.8:1, ink-3 5.1–7.0:1 (the floor for text), cobalt 5.1–7.0:1, volt 12.3–16.9:1, coral 5.0–6.9:1, sky
7.4–10.2:1, the live badge's #ff7a5f 5.5–7.6:1. Text on a volt fill is #0a0c10 (16.9:1), on a cobalt fill #0a0c10
(7.0:1). The score bug's clock is white on #c92d17 (5.4:1). Percentile knobs take white or near-black, whichever reads better on
that exact colour (`QK.pctInk`).

**Ours.** Blue (cobalt) means ours: our probability, our rating, the forecast line, the favourite's chance on a card,
primary actions, links. It never marks a team, the market, or good/bad. In copy, say "ours in blue".

**Market.** Never on overview cards, never in a headline stat, never on the home page. It may appear only as a quiet
reference on game detail and the Model page: a grey tick, a hollow ring, a muted column, with its source named.
Game cards default to `market: false`.

**Percentile scale (cold → hot).** Broadcast's ramp brightened for dark: `--pc-0` blue #2f6fe0 → `--pc-25` #7fa6e6
→ `--pc-50` cool grey #a9adb5 → `--pc-75` #f59a72 → `--pc-100` red #d9361d (white ink 4.7:1 at both ends). It steps in lightness, so it reads for red-green colour-blind viewers, and every anchor clears
3:1 as a mark on a card. Use `QK.pctColor(p)` in HTML, `QK.pctHex(p)` in charts, `QK.pctInk(p)` for text on it.

**Team colours** are used prominently, as in Broadcast: monograms, the win-probability bar in the two teams' colours,
the stripe across the top of every game card (split by our chance), title-race bars (`QK.chances` uses a row's
`color` by default), the player tile, lines in a race. `QK.color.team()` lifts a dark kit until it clears 3:1 on the
card; two kits side by side must be distinct (`QK.color.distinct`), else the fallbacks are cobalt v grey (`--wp-a` /
`--wp-b`). Where there is no team colour, use cobalt (tennis players: cobalt v grey; F1 constructors have colours).

**Sport accents** (`--a-<sport>`) are identity marks only: the switcher icon, the sport dot, the site word in the logo.

**Status** colours (`--live`, `--up`, `--down`, `--st-*`) are reserved, always with a word or symbol.

**Chart categorical slots** start with cobalt: `--c-1` cobalt, `--c-2` red-orange, `--c-3` cyan, `--c-4` volt,
`--c-5` plum, `--c-6` leaf, `--c-7` rose, `--c-8` sand (the slots keep their Matchday roles, so maps by slot still
read right). A "we said / it happened" pair is cobalt (`--c-model`) with volt (`--c-actual`).

## 4. Space and shape

Roomy. 4 px grid (`--sp-*`), page max 1240 px, 24 px gutter (16 px on phones), 64 px between sections
(`--sec-gap`, 44 px on phones). Cards: 22 px radius (`--r-card`, 18 px on phones), a hairline ring and a soft lift
shadow, 20–22 px padding. Stat tiles 18 px radius. Buttons, pills, chips, tabs and segmented controls are fully round.
Team marks are circles. Nothing may widen the page at 375 px: wide tables scroll inside their card.

Page rhythm: a greeting or a page head, then stat tiles, then the story (what to watch, the rail, the race), then the
detail (tables, charts). One idea per card; the number before the chart; the chart before the table.

## 5. Components

All builders return HTML strings unless noted. Full signatures are in the comments of `quant.js` / `quant-charts.js`;
`showcase.html` shows each one.

**New in v3 (Matchday)**

| Component | Builder | Where |
|---|---|---|
| "i" explainer note | `QK.note(html)` (`.qk-note`) | under any number that needs a sentence |
| Italic aside | `QK.aside(text)` (`.qk-aside`) | a one-line reason, a note beside a number |
| Highlighter | `QK.mark(text)` (`.qk-mark`, `.qk-hl`) | a key phrase in a headline |
| Greeting hero | `QK.greeting({ date, title, lede, ctas, side })`, `QK.greet()` | Home and every sport overview |
| Feature card | `QK.featureCard(g, { scribble })` | the hero's side: the game to watch, with a sun sticker |
| What to watch | `QK.watchGrid(games, { limit, card })`, `QK.whyLine(g)`, `QK.watchScore(g)` | overviews: six cards with a reason |
| Who's hot | `QK.hotRow(items)` | Home; any site's leaders strip (swipeable on phones); "next best" by `QK.surname` (keeps "Witt Jr.") |
| Stat of the day | `QK.statOfDay(s, { nav })` | Home |
| New here? | `QK.newHere({ items })` | Home and overviews |
| How sure are we? | `QK.howSure(el, { bins / calibration, brier, n, league, span, subject })` (renders), `QK.calib.find(json)`, `QKC.calibration(el, spec)` | Home; every Model page; a teaser on overviews |
| Percentile rail | `QK.pctRail(o)` (= `QK.pctCard`), rows `{ label, sub, pctl, prev, value, tip, early }`, `QK.pctKey()` | player pages |
| The short version | `QK.shortVersion(text)`; `QK.playerHeader({ ..., short })` puts it in the header | player (and team) pages |
| Preview card | `QK.previewCard(g, { kicker, nick, factors, note, noteExtra, market, vs, noun, homeFirst })` | game pages: away "at" home (football: home "v" away; tennis "v"; `noun` "match" / "race" in the note), our chance, factors |
| Score bug | `QK.scorebug(g, { size: 'lg' })` | live games (cards, heroes, game pages) |
| Compare verdicts | `QK.verdicts([{ title, who, text }])` | under a compare table |

**v2 builders, restyled (same API)**

| Component | Builder | v3 notes |
|---|---|---|
| Shell | `QK.shell(opts)` | the word mark, round sport pills (current one in off-white), a round search pill; no theme toggle |
| Section head | `QK.sectionHead({ kicker, title, sub, actions, size: 'lg', tag })` | volt kicker, Fraunces title, no rules |
| Ticker | `QK.ticker(games, o)` into `.qk-ticker` | broadcast black, our chance in blue |
| Game card | `QK.gameCard(g, { sport, market, form, why, bug })` | monograms, Fraunces chances, team bar with a key, the score bug when live, `why` aside; **`market` defaults to false** |
| Win bar | `QK.wpBar(pL, pD, pR, tL, tR, { labels: 'key', keyText })` | rounded segments; `'key'` puts short names at the ends and "chance to win" between |
| Chance bars | `QK.chances(rows, { teamColours })` | bars in team colours when rows carry `color` (`teamColours: false` for ours in blue) |
| Stat tile | `QK.statTile(o)`, `QK.stats(list)` | sentence-case label, percentile pill, Fraunces number |
| Player header | `QK.playerHeader({ name, number, pos, team, kicker, meta, tags, stats, short, face })` | tilted number tile with a volt shadow, chips, the short version |
| Percentile card | `QK.pctCard(o)` | now the rail: explanation line, last-season ring, median tick, key |
| Leaderboard | `QK.leaderboard(el, spec)` | heat pills on the percentile scale |
| Compare | `QK.compareView(o)` | the best value in each row under the volt highlighter; percentile pills |
| Matchup bar, keys, tags | `QK.matchupBar`, `QK.keys`, `QK.tag(text, 'signal' / 'sun')` | rounded |
| v1 (kept) | `QK.kpi`, `QK.matchCard`, `QK.tick`, `QK.mvm`, `QK.table`, `QK.tableHTML`, `QK.pctlBars`, `QK.pctlChip`, `QKC.*` | restyled |

Glossary tooltips stay: any `data-tip`, and every known column abbreviation (`QK.GLOSS`).

`QK.now()` is the page clock; `?asof=<ISO>` pins it to preview an older local snapshot (the live sites never pass it).

## 6. Charts

One library, ECharts 5.5.1. Everything themes from the tokens.

- **Axis titles always** (the standing rule): every value axis says what it measures and its unit. The checker fails
  a page with an untitled value axis.
- **Cool grid**: dashed hairlines in cool grey at 8%, DM Sans labels in `--ink-3`, axis titles in `--ink-2`.
- **Blue (cobalt) for ours**, the first series; volt for what happened beside it; red-orange and cyan for the next
  ones; team colours for teams.
- **Annotations** in italic Fraunces (`QKC.annot(T)`): "dashed line = spot on", "two goals in 29 seconds", the
  forecast chart's event labels, quadrant names. Write on the chart instead of a legend wherever a mark can carry its
  own words.
- **538-style forecast lines** (`QKC.forecast`): end labels, bands, annotations, a "Today" rule, a shaded projection.
- **Calibration** (`QKC.calibration`): our chance against how often it happened, dots sized by count, the dashed
  diagonal, notes on the busiest and the top bucket.
- **Uncertainty is shown, never implied**: ranges, bands, error bars; never invent an interval the payload lacks.
- The market is never a filled bar or a second line: a tick or a hollow ring, and only where §3 allows.
- Rounded tooltips on the raised surface.

## 7. Motion

Subtle: cards rise in once, bars grow once, the live dot pulses, cards lift 2 px on hover. No count-up numbers, no
auto-scrolling ticker. The stat of the day rotates slowly and pauses on hover. `prefers-reduced-motion` turns it off.

## 8. Copy

**Voice.** A friendly analyst at the bar. Plain words first, the number second, the method a tap away. Every number
gets a line on what it means ("70% still misses 3 times in 10"), and how sure we are. Short sentences. British
spelling. Warm, never smug, never hype.

**Patterns.**
- Greeting: "Good evening! Here's what's *worth watching* tonight." (`QK.greeting`).
- What to watch: "Six games we'd pick", each with one line on why ("A coin flip: our closest call on the slate.",
  "The Knicks are clear favourites, but a 31% chance comes off about 1 time in 3.", "Before the start we had the
  Jets at 43%. The score has moved it.").
- Every chance with a "how sure" line: "60% means Colorado loses a game like this about 4 times in 10."
- Player pages open with "The short version": two or three sentences in plain English, including the weak spot.
- Small samples are named: "Eight games is a small sample."

**Words we use:** chance, our chance, forecast, projection, rating, expected, likely range, percentile, peers,
"from 20,000 simulated seasons", "how sure are we".

**Words we do not use** in headlines, KPIs, labels, buttons or chart titles: odds (in our own copy), priced, price(s),
pricing, edge, value bet, gap v market, biggest gap, model v market (as a headline), mispriced, lock, fade, sharp,
line value. Exceptions: proper names (NHL EDGE tracking data), the legal footer and terms, and the Model / accuracy
pages, where a "Market" column may sit beside ours as a named reference. Never say "fair odds"; say "our chance".

**Neutral labels:** no player pronouns in UI copy ("the player", "Among peers", "Their type"). Real names and quoted
text are left as they are.

**Legal terms (one decision for every site, 23 Oct 2026).** Each site's disclaimer and terms panel is the
`<template id="disclaimer-template">`, and its outermost element carries the class `qk-legal`. The panel keeps its
legal substance: information and entertainment only; not betting, financial or professional advice; no bets accepted;
provided "as is"; 18+ and responsible gambling. The checker's `--banned` scan skips `.qk-legal` and nothing else.

## 9. Comparisons (metrics)

Percentiles, leaderboards, compare views and "most similar" lists use the sport's metric set from
`docs/METRICS_SPEC.md` (`docs/_design/metrics/<sport>.json`, copied to `assets/qk/metrics/`): peers are the same
position or role with a sensible sample floor; metrics are stable and predictive. A metric still short of its
stabilisation sample is drawn dashed ("early"). The rail's ring is last season's percentile in the same peer group.

## 10. Accessibility

Text contrast as §3 (AA on every surface). Marks ≥ 3:1. Identity never by colour alone (numbers on bars, letters in
form dots, labels on lines, words on the score bug). Keyboard: skip link, focus rings in sun, arrow-key tabs, sortable
headers as buttons, tooltips on focus. Charts carry `role="img"` and a label. Every page is checked at 1440 and 375 px
(dark only).
