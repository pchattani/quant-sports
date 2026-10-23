# The Quant — Design System 2.0 "Signal"

The spec every sport site follows. It replaces the v1 "premium data terminal" look (README.md keeps the kit
reference). The kit itself is in this folder; `showcase.html` shows every component on sample data; the reference
pages are the Home page (`docs/home`) and the Rink overview, game, player and compare pages (`docs/rink`).
To move a page over, follow `MIGRATION_V2.md`.

## 1. Identity

**Name.** The Quant. Each site is "The Quant <Site>" (Footballer, Paddock, Hardwood, Ace, Bullpen, Gridiron, Rink,
Campus). The design language is called *Signal*.

**What it is.** A fun sports hub for people who like numbers: scores, our forecasts, ratings and the stats behind
them. It is not a betting site. The headline is always our forecast, our rating or a stat.

**Voice.** A friendly analyst at the bar: plain words first, the number second, the method a tap away.
Quant-literate (we say expected goals, percentiles, a 90% range) but never smug. Short sentences. British spelling.

**What we borrow, and what we do not.**

| Source | We take | We never take |
|---|---|---|
| Bloomberg | terminal density, the scoreboard ticker, tabular figures, crisp tables, one strong accent on a dark plane, keyboard search (`/`, Ctrl K) | amber-on-black trade dress, their fonts, function-key chrome |
| ESPN | scoreboard energy, big headline numbers, game cards, team colours as accents, a live feel | the red brand, their logos, the bottom-line crawl |
| FiveThirtyEight | probability storytelling: "chance of" framing, forecast lines over time with uncertainty bands, annotations, direct labels, friendly explanations | their fox, typefaces, exact chart styling |
| Baseball Savant | percentile sliders against a peer group, player cards, leaderboards, cold-to-hot colour | their red-blue exact ramp and slider artwork, MLB marks |

No league, club, sponsor or publisher logos anywhere. Team marks are our own monograms on the team colour.

## 2. Type

All from Google Fonts (the only font CDN the sites use).

| Role | Face | Where | Token |
|---|---|---|---|
| Display | **Archivo** 800–900, width 88% (semi-condensed) | headlines, section titles, scores, stat-tile numbers, our chances in lists | `--font-display`, `--stretch-display` |
| UI | **Inter** 400–800 | body, labels, buttons, card titles | `--font-ui` |
| Data | **JetBrains Mono** 500–700 | tables, ticker, axis labels, small numbers in sentences | `--font-num` |

Tabular figures everywhere a number can change (`font-variant-numeric: tabular-nums`; `.num` / `.qk-num`; display
numbers have it built in). Link: `family=Archivo:wdth,wght@62..125,500..900&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700`.
`QK.shell()` adds the Archivo link itself when a page has not, so no page is ever without it.

Scale (rem at 16 px):

| Token | Size | Use |
|---|---|---|
| `--fs-d1` | clamp(2.6, 7vw, 5.25) | the home headline only |
| `--fs-d2` | clamp(1.9, 4.2vw, 3) | page titles (`QK.sectionHead({ size: 'lg', tag: 'h1' })`), scoreboard scores, player names |
| `--fs-d3` | clamp(1.6, 3vw, 2.25) | stat-tile numbers |
| `--fs-d4` | 1.375 | numbers inside cards (game-card scores, chances) |
| `--fs-xl` … `--fs-2xs` | 24 / 18 / 15 / 13 / 12 / 11 px | v1 text scale, unchanged |

Section titles: Archivo 800, `clamp(1.45rem, 3vw, 2rem)`. Kickers: Inter 700, 11 px, caps, 0.08em tracking.

## 3. Colour

Dark first, light chosen (not inverted): each theme has its own steps (`tokens.css`).

**The signal (one signature accent).** Violet `--signal` (#9384ff dark, #5a44e4 light). It means *ours*: our
probability, our rating, the forecast line, the favourite's chance on a card, primary buttons, links, the section
rule. It never marks a team, the market, or good/bad. `--c-model` is the signal.

**Sport accents** (`--a-<sport>`) are identity marks only: the switcher icon, the sport pill, the kicker square, the
sport tile rail. Text beside them stays ink. v2 moved the NFL accent to gold (violet is the signal).

**Market.** `--c-market` is a quiet grey. The market appears as a hollow ring, a thin tick on a bar, or a muted
column — never a filled bar, never a headline, never larger than ours.

**Percentile scale (Savant-like, cold → hot).** `--pc-0` blue → `--pc-25` → `--pc-50` grey → `--pc-75` → `--pc-100`
red, in both themes. 0 = worst in the peer group, 100 = best (lower-is-better metrics are already flipped in the
payloads). Blue–grey–red also steps in lightness, so it reads for red-green colour-blind viewers. Use
`QK.pctColor(p)` (theme-following CSS colour) in HTML and `QK.pctHex(p)` in charts; `QK.pctInk(p)` gives the text ink.

**Team colours** are accents: monograms, the win-probability bar, a band on the player header, lines in a race.
`QK.color.team()` lifts a dark kit until it clears 3:1 on the card. Two kits side by side must be distinct
(`QK.color.distinct`: lightness contrast ≥ 1.6, or ≥ 60° apart in hue and not a red–green pair); otherwise the
second team takes its alternate colour, then the fallbacks.

**Win probability.** Team colours first; fallbacks `--wp-a` (blue, left/away) and `--wp-b` (orange, right/home);
`--wp-draw` grey for a draw. The bar always carries the numbers at its ends.

**Status** colours (`--live`, `--up`, `--down`, `--st-*`) are reserved, always with a word or symbol.

**Categorical chart slots** `--c-1` … `--c-8` are unchanged from v1 (the validated palette) for series that are
neither ours nor a team.

## 4. Space, density, shape

4 px grid (`--sp-*`). Page max 1440 px, 16 px gutter. Cards: 12 px radius, 1 px hairline, 16 px padding; dense tables
5–8 px cell padding. Desktop pages run 12 columns (`.qk-grid` + `.qk-span-*`); at 1100 px spans halve, at 720 px
everything stacks; stat tiles go two a row. Nothing may widen the page at 375 px: wide tables scroll inside their card.

Density rule: one idea per card, the number before the chart, the chart before the table. A page opens with a
section head, a row of stat tiles, then the scoreboard or the hero chart.

## 5. Components (kit v2)

All builders return HTML strings (except `QK.leaderboard` and charts, which render). Full signatures are in the
comments of `quant.js` / `quant-charts.js`; `showcase.html` shows each one.

| Component | Builder | Notes |
|---|---|---|
| Nav (top bar + sport switcher + section nav) | `QK.shell(opts)` | unchanged API; v2 brand mark and type |
| Section head | `QK.sectionHead({ kicker, title, sub, actions, size: 'lg', tag })` | kicker square in the sport accent, signal rule |
| Scoreboard ticker | `QK.ticker(games, { group, max })` into `.qk-ticker` | grouped by sport (or league), live first; our chance before the game |
| Game card | `QK.gameCard(game, { sport, market, form })` | our chance per team (favourite in signal), team-colour win-probability bar, form, record, quiet market ring + tick |
| Win-probability bar | `QK.wpBar(pL, pD, pR, tL, tR, { market, size: 'lg', colors })` | numbers at both ends; market tick two-way only |
| Form | `QK.formDots('WWLDW')` | letters carry the meaning |
| Chance bars (538 probability bars) | `QK.chances(rows, opts)`, `QK.chanceBar(row)`; chart form `QKC.chances(el, spec)` | ours as the bar (team colour or signal), market a grey tick, key underneath |
| Stat tile | `QK.statTile({ label, value, unit, sub, delta, pctl, trend, signal, tip, href })`, `QK.stats([...])` | display number, percentile chip, sparkline |
| Player card header | `QK.playerHeader({ name, number, pos, team, kicker, meta, stats, tags })` | team band, number watermark |
| Percentile card | `QK.pctCard({ peer, sample, groups: [{ label, rows: [{ label, pctl, value, tip, early }] }] })` | peer group and sample always shown; early = dashed knob |
| Leaderboard | `QK.leaderboard(el, { columns: [{ type: 'entity' / 'pctl' / 'bar' / 'spark' }], rowClass, rowHref })` | heat cells on the percentile scale |
| Comparison view | `QK.compareView({ entities, groups: [{ label, rows: [{ label, values, pctls, better, fmt, dfmt }] }] })` | 2–3 players, best value bold, delta for two |
| Matchup bar | `QK.matchupBar({ left, right, rows, colors })` | tale of the tape; the better side solid |
| Forecast over time | `QKC.forecast(el, spec)` | see §6 |
| Distribution | `QKC.distribution(el, { values, marks, xName, yName, lowerBetter })` | histogram on the percentile scale, labelled marks |
| Tags, keys | `QK.tag(text, 'signal')`, `QK.keys([{ name, color, kind }])` | |
| v1 (kept) | `QK.kpi`, `QK.matchCard`, `QK.tick`, `QK.mvm`, `QK.table`, `QK.tableHTML`, `QK.pctlBars`, `QK.pctlChip`, `QKC.*` | restyled to v2; prefer the v2 builders on new work |

Glossary tooltips stay: any `data-tip`, and every known column abbreviation gets one automatically
(`QK.GLOSS`). Every chart axis has a title (§6).

## 6. Charts

One library, ECharts 5.5.1 (jsDelivr). Everything themes from the tokens and repaints on a theme switch.

- **Axis titles always** (the standing rule): every value axis says what it measures and its unit
  (`xName` / `yName` / `valName` / `catName`). The checker fails a page with an untitled value axis.
- **Ours in the signal, the market in grey.** A dumbbell reads "Our model" (solid violet) with "Market" as a hollow
  ring; bar charts take a market *tick*, never a second bar. No "gap" rows.
- **538-style forecast lines** (`QKC.forecast`): chance on a 0–100% axis; one line per team in its colour (ours in
  the signal when it is a single forecast); the line labelled at its end with its last value ("BOS 34%") instead of
  a legend; the uncertainty band (80% or 90% range, say which) in the line colour at 16% opacity; dashed annotation
  rules labelled at the top for what moved it (injury, trade, a goal); a solid "Today" rule; what follows today
  shaded as "Projection".
- **Probability bars**: horizontal, sorted, value at the bar end, our chance only; the scale says when it stops
  short of 100%.
- **Uncertainty is shown, never implied**: ranges (`QKC.range`), bands, error bars, or "± one standard error" in the
  sub-line. Do not invent an interval the payload does not carry.
- **Direct labels instead of legends** wherever a line or mark can carry its own name; otherwise `QK.keys` above the
  chart in the series colours.
- **Distributions** colour bins by the percentile scale and mark the player (signal) and the median (dashed).
- Charts sit with a one-sentence sub-line saying what to read, and the same numbers in a table or list nearby.

## 7. Motion

Subtle and functional: cards rise in once (`.qk-rise`, 420 ms), bars grow from zero once (`qk-grow`), the live dot
pulses, hover lifts colour not position. No count-up numbers, no auto-scrolling ticker, no parallax. The stat-of-
the-day carousel pauses on hover. `prefers-reduced-motion` turns all of it off.

## 8. Copy

**Words we use:** chance, our chance, forecast, projection, rating, expected, likely range, percentile, peers,
"from 20,000 simulated seasons".

**Words we do not use** in headlines, KPIs, labels, buttons or chart titles: priced, price(s), pricing, edge,
value bet, gap v market, biggest gap, model v market (as a headline), mispriced, lock, fade, sharp, line value.
Exceptions: proper names (NHL EDGE tracking data), the legal footer and disclaimer, and the Model / accuracy pages,
where a "Market" column may sit beside ours as a reference with its source named (e.g. "Market (Kalshi /
Polymarket)", "No-vig line"). Never say "fair odds"; say "our chance".

| Not | Say |
|---|---|
| Every game, priced. | Every game, by the numbers. |
| Biggest gap v market −42 pts | Cup favourite COL 17% |
| Model v mkt · Edge +9 pts | Our chance 58% · Market 52% (reference) |
| Every price | Our forecast |
| BOS −1.5 covers 35% | BOS wins by two or more: 35% |
| Over 6.5 45% | 7 or more goals: 45% |
| xGF% 0.698 | 70% of the expected goals at 5v5 went the team's way with this player on the ice |

Explanations are friendly and short: say what the number means, then the method in a tooltip. Say "our" for our
models. Name the peer group and the sample under every percentile. The disclaimer stays in the footer of every site.

Labels are neutral: no player pronouns in UI copy. "Among peers", not "Where he sits"; "Playing style", not "How he
plays"; "the player's team", not "his team". Real names and quoted text are left as they are.

**Legal terms (one decision for every site, 23 Oct 2026).** Each site's disclaimer and terms panel is the
`<template id="disclaimer-template">`, and its outermost element carries the class `qk-legal` (the card itself, or a
`<div class="qk-legal">` wrapper). The panel keeps its legal substance on every site: information and entertainment
only; not betting, financial or professional advice; no bets accepted; provided "as is"; 18+ and responsible
gambling. "Betting" stays in its heading and in the advice disclaimer, because that wording is the protection. The
standard sentence is "Model probabilities carry no margin; they are not offers of any kind, and no bets can be placed
here." The panel does not list "fair odds" (the sites no longer show them), says "market probabilities", not "market
prices", and "closing lines", not "closing prices". The checker's `--banned` scan skips `.qk-legal` and nothing else:
any new legal text goes inside that container, and no other element may carry the class.

## 9. Comparisons (metrics)

Percentiles, leaderboards, compare views and "most similar" lists use the sport's metric set from
`docs/METRICS_SPEC.md` (written by the metrics agent): peers are the same position or role with a sensible sample
floor; metrics are stable (year-to-year reliable) and predictive. The front end defines the set in one place per
sport (Rink: `RK.ui.SK_SET` / `G_SET` in `rk-ui.js`) and the percentile card, compare page and distribution all read
it. A metric still short of its stabilisation sample (`metrics[].stabilises_at`) is drawn dashed.

## 10. Accessibility

Text contrast: ink-1 16.9:1, ink-2 8.4:1, ink-3 4.9:1 (the floor). Marks ≥ 3:1. Identity is never colour alone
(numbers on bars, letters in form dots, labels on lines). Keyboard: skip link, focus rings, arrow-key tabs, sortable
headers as buttons, tooltips on focus. Charts carry `role="img"` and a label. Every page is checked at 1440 and 375 px
in both themes.
