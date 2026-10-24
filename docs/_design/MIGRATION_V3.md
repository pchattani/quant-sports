> **Superseded by `MIGRATION_V4.md` (kit v4 "Broadcast", 23 Oct 2026).** Kept as history; follow v4.

# Moving a site to kit v3 "Matchday" (dark only)

For the phase-B agents, one site each. Read `STYLE_GUIDE.md` first (identity, colour, type, copy), open
`docs/_design/showcase.html` (serve `docs/`, open `/_design/showcase.html`) to see every component, and copy the
pattern from the reference pages:

| Page | Reference |
|---|---|
| Home | `docs/home/index.html`, `assets/home.js`, `assets/home.css` (builder fields: `scripts/build_home.py`) |
| Sport overview | `docs/rink/assets/js/rk-overview.js` (`render`: greeting, tiles, what to watch, How sure teaser + New here) |
| Game page | `docs/rink/assets/js/rk-games.js` (`hero` → `QK.previewCard`; the forecast table beside it) |
| Player page | `docs/rink/assets/js/rk-player.js` (crumb, header with the short version, tiles, rail with rings, How sure, game by game, their type, compare, next and last game) |
| Compare page | `docs/rink/assets/js/rk-compare.js` (question title, highlighter, verdicts) |
| Shared site helpers | `docs/rink/assets/js/rk-ui.js` (`U.SUB` rail lines, `U.ARCHETYPE`, `U.gc(c, o, rows, why)`, `U.game` live fields) and `assets/rink-qk.css` §5 |

**The user's decision: dark only.** There is no light theme and no theme toggle. Do not add light-mode CSS, do not
add a toggle, and run the checker with `--themes dark` only.

## What changes automatically (no code)

Copying the kit (`python scripts/design_kit.py docs/<site>`) is enough for every page on every site to look Matchday:

- **Tokens:** the Broadcast palette (23 Oct, later): near-black planes, cool charcoal cards, white and cool-grey
  ink, cobalt for ours, volt for kickers, the highlighter and key numbers, red-orange live, the dark percentile ramp,
  22 px card radii, roomy spacing (1240 px page, 64 px between sections). The legacy variables each site maps onto
  kit tokens (`rink-qk.css` §1, `hardwood-qk.css`, ...) follow.
- **Fonts:** `QK.shell()` injects Fraunces + DM Sans when the page links the v2 faces; every kit class uses them.
- **Theme:** `QK.theme` is dark only. `boot()` pins `data-theme="dark"`, so old `[data-theme="light"]` and
  `prefers-color-scheme: light` rules in site CSS never apply; the toggle button is gone from the shell.
- **Every v1 / v2 builder** renders in the v3 look with the same API: shell (word mark, round pills), section heads
  (coral kicker, Fraunces title), black ticker, stat tiles, game cards (monograms, Fraunces chances, team bar with a
  key, the score bug when live), chance bars (team colours, else ours in blue), the percentile card (now the rail), compare (highlighter),
  leaderboards, tables, tabs, chips, buttons, notes, tooltips, charts (cool dashed grid, DM Sans labels, cobalt first
  series, italic annotations).
- **Game cards default to `market: false`.** The market disappears from every overview card without a code change.
  Only pass `market: true` on game detail or the Model page, never on an overview.

Check with the checker after the copy: nothing should break (no overflow, no console errors, no untitled axes).

## What each page type should add

1. **Head of every page.** Link the fonts (avoids a late swap) and set the dark meta:
   ```html
   <html lang="en-GB" data-sport="hockey" data-theme="dark">
   <meta name="color-scheme" content="dark"><meta name="theme-color" content="#17140f">
   <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&family=Fraunces:ital,opsz,wght,SOFT,WONK@0,9..144,400..800,0..100,0..1;1,9..144,400..700,0..100,0..1&display=swap">
   ```
   Drop the Archivo / Inter / JetBrains Mono link and any inline theme-boot script that sets `light`. Favicon: the sun
   dot (see `docs/home/index.html`).
2. **Overview.** Replace the page head with `QK.greeting({ date: '<League> · <season> · <phase>', title: QK.greet() +
   '! Here’s what’s ' + QK.mark('worth watching') + ' in the <league> tonight.', lede, ctas, side:
   QK.featureCard(bestGame, { scribble }) })`. Then the stat tiles; then **What to watch**: game cards with
   `why: true` (`QK.watchGrid(games, { limit: 6 })` or `QK.gameCard(g, { why: true })` in your own grid); then
   **New here?** (`QK.newHere()`, the third item linking your Model page) beside a **How sure are we?** teaser read
   from your `data/calibration.json` with `QK.calib.find` (rk-overview.js shows it). Title races: `QK.chances(rows,
   { key: false })` with no market on the overview.
3. **Game page.** Hero → `QK.previewCard(g, { kicker: '<League> · <venue>', nick, colors, factors, noteExtra,
   market })`: away "at" home with records (and form if you have it), the score bug when live, our chance for the
   favourite as a big blue number with a sentence, the bar, a "How sure are we?" note (add overtime / draws / expected
   total in `noteExtra`) and the match-up factors (better side in blue). The market may sit here as `market: { p,
   label: 'Market (<source>)' }`, a quiet line. Put your forecast table beside the hero (rk-games.js `.rk-gtop`).
4. **Player page.** As rk-player.js:
   - a crumb (`Sport › Team › Name`);
   - `QK.playerHeader({ name, number, pos, kicker: '<season> · N games in', team, meta: [chips], short })` with
     **The short version** (two or three plain-English sentences from this season's percentiles: the headline line,
     what the player is top-10% at, the weak spot, "early days" under 15 games);
   - five `QK.stats` tiles with percentile chips;
   - the **rail**, `QK.pctRail({ kicker: 'How they stack up', peer, sample, groups, ringLabel })`, rows with `sub` (a
     plain line, see `U.SUB`) and `prev` (last season's percentile in the same peer group: the hollow ring);
   - beside it a cream **How sure are we?** card (when the metrics settle at this player's playing time, from the
     spec's stabilisation samples), **game by game** (a titled chart; annotate the best game with `QKC.annot`) and
     **Their type** (plays most like, most time with);
   - a **compare** of the player and the two closest matches (`QK.compareView` + `QK.verdicts`);
   - the next game (`QK.previewCard`) and the last one; then the old sections under "More on the player".
5. **Compare page.** Title as a question ("MacKinnon, McDavid or Kucherov?"), `QK.compareView` (the highlighter is
   automatic), `QK.verdicts` from the metric where each player leads the others by the most (`U.ARCHETYPE` names it).
6. **Model page.** Add **How sure are we?** at the top: `QK.howSure(el, { calibration: <your calibration.json>, league,
   span, subject: 'the home team' })`. The market column may stay here as a named reference.
7. **Leaders / teams / standings.** Nothing required; optionally a `QK.hotRow` strip at the top of a leaders page.

## Copy voice (apply as you go)

- Friendly analyst: plain words, then the number, then the method in a tooltip or a note.
- Every chance gets a "how sure" line: "60% means Colorado loses a game like this about 4 times in 10."
- Coral kickers say what the section is ("What to watch tonight", "How they stack up", "Last time out"); Fraunces
  titles say the story ("Six games we'd pick", "Percentiles: how the player ranks").
- Neutral labels: no player pronouns ("the player", "Their type").
- No betting words in headlines, KPIs, labels, buttons or chart titles (STYLE_GUIDE §8). Not "violet" any more: the
  favourite is "in blue".
- **Colours (Broadcast palette, 23 Oct).** Use tokens only: no hard-coded Matchday values (#3cc9b4, #17140f,
  #211d17, #2c271f, #f3ece0, #ffc94d) in site CSS or JS. Copy says "ours in blue", never "teal"; text on a volt or
  cobalt fill is near-black. Game cards carry a team-colour stripe and title races use team colours by default.

| v2 | v3 |
|---|---|
| "Every NHL game, by the numbers." page head | the greeting: "Good evening! Here's what's worth watching in the NHL tonight." |
| "Scoreboard / Tonight" + "the favourite in violet. A grey tick marks the market" | "What to watch tonight / 9 games on the slate" + "Our chance for each side, with a line on why it's worth your time." |
| Cup chances with a market tick on the overview | our chance only (`key: false`) |
| "Percentile rankings" | kicker "How they stack up", title "Percentiles: how the player ranks" |
| "Model prices the listed starters" | "The model uses the listed starters" |

## Checks (every changed page)

1. `python scripts/design_kit.py docs/<site>` after any kit change (never edit `assets/qk/`).
2. `esprima` on every changed JS file (no `?.`, no `??`):
   `uv run --no-project --with esprima python <scratchpad>/jscheck.py <files>`.
3. The checker, dark only, 1440 and 375, with `--banned`:
   `uv run --no-project --with playwright python <scratchpad>/v2check.py <out> "<site>/#/" ... --themes dark --banned --shots --full`.
   No overflow, no console errors, no untitled value axis, no banned words outside `.qk-legal`.
4. Payload budgets unchanged (no new data files; the rail's ring reads last season's existing catalogue lazily).

## Site CSS that can fight the kit

- Hard-coded fonts (`font-family: Inter`, `JetBrains Mono`, `Archivo`) in a site's own CSS: switch to
  `var(--font-ui)` / `var(--font-display)` / `var(--font-num)`.
- Hard-coded colours (`#fff`, `#000`, blues and violets) in site CSS: use tokens.
- `text-transform: uppercase` labels in legacy CSS: v3 labels are sentence case.
- Small radii (4–8 px) on legacy `.card` classes: map them to `var(--r-card)` (rink-qk.css §2 already does).
- Any chart colour taken as `T.cat[0]` now draws teal: fine for a main series; for a second team use a team colour.

## Payload follow-ups (for the data agents, not phase B)

- **Last-season percentiles in the player file.** The rail's rings load `<last season>/skaters.json` (4 MB on Rink)
  when the rail scrolls into view. Writing `current.prev_pct_pos` (last season's position-pool percentiles and games)
  into `players/<pid>.json` would let pages skip that load. Same for the other sites.
- **Calibration.json for every site.** Home reads Rink, Hardwood (NBA), Gridiron and Bullpen (`calibration_summary`
  in `scripts/build_home.py`). Footballer, Ace and Campus have none yet; Paddock's is per event (win / podium), shown
  on its own Model page with `subject: 'the driver'`.
- **Form strings.** `QK.previewCard` and `QK.gameCard` show the last five results when `team.form` is set ("WWLOW").
