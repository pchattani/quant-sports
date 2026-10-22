# Moving a site page to Design System 2.0

For the phase-2 agents. Read `STYLE_GUIDE.md` first (identity, colour, type, copy rules), open
`docs/_design/showcase.html` (serve `docs/`; `?theme=light` / `?theme=dark`) to see every component, and copy the
pattern from the reference pages:

| Page | Reference |
|---|---|
| Home | `docs/home/index.html`, `assets/home.js`, `assets/home.css` |
| Sport overview | `docs/rink/assets/js/rk-overview.js` |
| Game page | `docs/rink/assets/js/rk-games.js` (`hero`, `kpiStrip`, `pregameCard`, `tape`, `summary`) |
| Player page | `docs/rink/assets/js/rk-player.js` |
| Compare page | `docs/rink/assets/js/rk-compare.js` (registered after `rk-sections.js`) |
| Shared site helpers | `docs/rink/assets/js/rk-ui.js`, section "Design System 2.0 helpers"; layout in `assets/rink-qk.css` §4 |

The kit is backward compatible: every v1 call (`QK.kpi`, `QK.matchCard`, `QK.tick`, `QK.mvm`, `QK.table`,
`QK.tableHTML`, `QK.pctlBars`, `QKC.*`) still works and already renders in the v2 look, so a site that has only had
the kit copied is not broken. Migration is about using the v2 builders, the v2 page structure and the v2 copy.

## Step by step

1. **Kit and fonts.** Never edit a site's `assets/qk/`; edit `docs/_design/` and run
   `python scripts/design_kit.py docs/<site>` (each site build does this too). In the page `<head>`, add Archivo to
   the Google Fonts link:
   `family=Archivo:wdth,wght@62..125,500..900&family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700`
   (`QK.shell()` injects it if missing, but the link avoids a late font swap). Update the favicon to the signal
   colours (`fill='%239384ff'`, stroke `%230c0820`) and `theme-color` to `#08090d`. Rewrite the meta description in
   v2 copy (no "odds", "priced", "against the market").
2. **Page head.** Replace the old header with `QK.sectionHead({ kicker: '<League> · <season> · <phase>', title, sub,
   size: 'lg', tag: 'h1', actions })`. Section titles inside the page: `QK.sectionHead({ kicker, title, sub, actions })`
   (a seg control goes in `actions`). Rink wraps this as `RK.ui.head()`.
3. **KPI strip → stat tiles.** `QK.kpi(...)` rows become `QK.stats([{ label, value, unit, sub, pctl, signal, tip,
   href }])`. Put ours first and mark it `signal: true`. Delete every market or gap tile.
4. **Game cards and ticker.** `QK.matchCard(g)` → `QK.gameCard(g, { sport: false })`. Add `home.record` / `away.record`
   ("7-2-0") and `home.form` / `away.form` ("WWLWL", oldest first) when the payload has them (Rink: `RK.ui.gameV2`
   adds records from the standings rows). A grid of cards: `grid-template-columns: repeat(auto-fill, minmax(290px, 1fr))`.
   A site ticker: `el.innerHTML = QK.ticker(games, { group: 'league' })` inside `.qk-ticker`.
5. **Win probability.** Use `QK.wpBar(pAway, pDraw, pHome, away, home, { size: 'lg', market })` in heroes. If the page
   picks a colour pair for its charts (Rink `RK.ui.pair`), pass it as `colors: [ca, ch]` so bar and charts agree.
6. **Futures and title races.** Dumbbells of model v market become chance bars: `QK.chances(rows, { limit, marketName:
   'Market (<source>)' })` (HTML) or `QKC.chances(el, spec)` (chart). Rows: `{ label, p, market, color, href, mark }`.
7. **Player pages.** Hero → `QK.playerHeader({ name, number, pos, team, kicker, meta: [[label, value]], stats, tags })`.
   Percentiles → `QK.pctCard({ peer, sample, groups })`: the peer group is the position group from the payload's
   position-pool percentiles (`pct_pos` / equivalent), the sample line names games, minutes and the floor, and
   `early: true` marks a metric whose sample is short of `stabilises_at`. Add `QKC.distribution` ("Where he sits")
   with the player and the median marked. Rink's `RK.ui.pctGroups`, `sampleOf`, `sampleLine` show how.
8. **Compare.** A compare page puts two or three players side by side with `QK.compareView({ entities, groups })`,
   the same metric set as the player card, peers = shared position group (else say "all skaters" and why), and a
   distribution with each player marked. Keep the old full comparison reachable ("Every metric (classic)").
9. **Leaderboards.** `QK.table` → `QK.leaderboard(el, spec)` with `type: 'entity'` (name, mark, sub-line),
   `type: 'pctl'` (heat cell from a percentile key), `type: 'bar'` (inline bar), `type: 'spark'` (last-N trend),
   `rowHref` for row links, `rowClass` to highlight a row (`is-me`).
10. **Charts.** Title every axis. Ours in the signal (`color: 'model'` on a `QKC.bar` series, `ours: true` on a
    `QKC.forecast` series). Market only as a tick (`market: [...]` on a bar series) or a hollow ring (dumbbell).
    Replace legends with end labels (`QKC.line` and `QKC.forecast` do this) or `QK.keys`. Do not use `T.market` as
    a generic second colour any more (it is grey now): use `T.cat[1]` or a team colour.
11. **Copy pass.** Apply the table below to headlines, KPIs, labels, buttons, chart titles and sub-lines. Leave the
    disclaimer and terms alone. Model / accuracy pages may keep a market column as a named reference.
12. **Check.** `esprima` on every changed JS file (no `?.`, no `??`); the headless checker at 1440 and 375, dark and
    light, on every changed page: no JS or console errors, no horizontal overflow, no untitled chart axis, and no
    betting words in the visible text (the checker's `--banned` list). Payload budgets unchanged.

## Old → new component map

| v1 | v2 | Notes |
|---|---|---|
| `.rk-head` / page `<header>` with `<h1>` | `QK.sectionHead({ size: 'lg', tag: 'h1' })` | |
| `.qk-section-head` + `<h2>` | `QK.sectionHead({ kicker, title, sub, actions })` | the old class still renders |
| `QK.kpi()` row (`.qk-kpis`) | `QK.stats([QK.statTile...])` | percentile chip, trend, `signal` |
| `QK.matchCard(g)` | `QK.gameCard(g)` | matchCard no longer shows an Edge badge in v2 |
| `QK.probBar()` | `QK.wpBar()` | labels at the ends, market tick, `colors` |
| `QK.mvm()` strip | the game card's market ring / the hero's `.qk-mkt` line | mvm still works (ours solid, market hollow) |
| `.qk-ticker` + `QK.tick` per game | `QK.ticker(games, opts)` | grouped, our chance pre-game |
| `QKC.dumbbell` model v market | `QK.chances` / `QKC.chances` | dumbbell is still fine on a Model / accuracy page |
| `.qk-hero` player header | `QK.playerHeader()` | |
| `QK.pctlBars(rows)` in a card | `QK.pctCard({ peer, sample, groups })` | pctlBars itself is v2 (cold→hot, early) |
| `QK.pctlChip(p)` | unchanged API, continuous colour | |
| `QK.table` with `pctl:` column | `QK.leaderboard` with `type: 'pctl'` | |
| radar / "every metric" compare | `QK.compareView()` + `QKC.distribution()` | keep the old view as a tab |
| ad-hoc win-prob or playoff-odds-over-time lines | `QKC.forecast()` | end labels, bands, annotations, today, projection |
| ad-hoc histograms | `QKC.distribution()` | |
| home/away tale of the tape tables | `QK.matchupBar()` | |
| `.qk-badge.edge` | remove (renders as a quiet outline if left) | `.qk-badge.signal` for "ours" |
| `var(--brand)` amber | `var(--signal)` violet (`--brand` now points at it) | |
| `--c-1` / `--c-2` as model / market | `--c-model` (signal) / `--c-market` (grey) | categorical `--c-*` unchanged |

## Copy changes

| Old | New |
|---|---|
| "Every game, priced." / "Week 6, priced." / "World football, priced and measured" | "Every game, by the numbers." / "Week 6, by the numbers." / "World football, by the numbers" |
| "Biggest gap v market" tile | a forecast or stat tile (favourite, top-rated club, leader, best goalie) |
| "Priced games / Priced fixtures" | "Games with our forecast" or drop it |
| "Model v market" (headline or card title) | "Our chance" / "Our forecast"; the market as "Market (reference)" |
| "Model v mkt", "Gap +9 pts", "Edge", "value" (bets) | remove; show "Market 52%" quietly |
| "Model win probability" | "Our win chance" |
| "Every price", "Pre-game prices" | "Our forecast", "Our pre-game forecast" |
| "fair odds", "-150", moneylines, "priced at" | "our chance 60%" (odds formats only on the Model page, if at all) |
| "−1.5 covers 35%", "puck line", "spread covers" | "wins by two or more: 35%", "wins by 4+: 52%" |
| "Over 6.5: 45%", "O/U" | "7 or more goals: 45%", "total goals" |
| "Title odds", "Cup odds" | "Title chances", "Cup chances" |
| "the market (orange)" / "blue dot model" | "violet: ours; grey: the market, for reference" |
| "Kalshi/Polymarket price" | "Kalshi / Polymarket number" or "Market (Kalshi / Polymarket)" |

Keep: proper names (NHL EDGE tracking, "No-vig line" as a named source on Model pages), the disclaimer, the
responsible-gambling links in the terms.

## What phase 2 must know

- **Metric sets.** `docs/METRICS_SPEC.md` (metrics agent) is the source of truth for peer groups, sample floors and
  metric sets. Define the set once per sport in the site's shared helper (Rink: `RK.ui.SK_SET` / `G_SET`) and have
  the percentile card, compare page and distribution read it. Align Rink's set with the spec when it lands.
- **Peer groups in the data.** Rink player files (`players/<pid>.json` → `current.pct`) carry league-wide skater
  percentiles while the old page said "against his position". The v2 player page loads `<S>/skaters.json` for
  `pct_pos` (position pool) and the metric catalogue. Payload follow-up for the data agent: write `pct_pos` (and the
  sample) into the player file so the page can skip the 2.7 MB catalogue.
- **Stale snapshots.** The home page drops games still marked live or upcoming 12 hours after their start (a stale
  local snapshot showed 14 "live" games from 17 Oct on 22 Oct). Sites should apply the same guard to any cached
  live list.
- **Colour pairs.** v2 `QK.color.distinct` replaced the lightness-only clash test: red v blue kits now keep their own
  colours; navy v dark green still falls back. Use `RK.ui.pair`-style helpers and pass `colors` to `QK.wpBar` /
  `QK.matchupBar` so the bar matches the charts.
- **`T.market` is grey now.** Any site chart that used `T.market` (or `--c-2` via the token) as a generic orange series
  must switch to `T.cat[1]`. Rink player charts were switched; grep each site for `T.market`.
- **Kit files are copied, not linked.** After any kit change run `design_kit.py` for all nine sites and run the checker
  on each overview at least.
