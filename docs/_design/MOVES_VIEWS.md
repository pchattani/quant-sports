# Who moves next: view spec for the phase-2 redesign

Four views per sport, from the moves payloads: a roster column "chance of leaving", a team **Outlook** card, a
ranked **Targets** table and a player-page **Movement** card. Each sport's moves agent appends its own section
below (football and college by the football/college moves agent; NBA, NFL, MLB and NHL by the US-sports moves
agent). Append; never rewrite another sport's section.

**Shared rules for every sport**
- Kit: the committed kit is v1.1 (`git log -- docs/_design`: no v2 commit yet on 23 October 2026). Build on its
  components (`QK.table` / `QK.sortable`, `QK.probBar`, `QK.kpi`, `QK.pctlChip`, `QK.chips`, `QK.tabs`, `QK.empty`;
  `QKC.bar`) and switch to the v2 equivalents when the design lead commits them. Never edit a site's kit copy.
- Wording: fun and quant-literate. "Chance of moving", "If he moves", "Likely landing spots", "Expected arrivals",
  "Who they could sign". No betting language (no odds, price, edge, value bet, line).
- Honesty labels are part of the design, not footnotes: where a number is a **base rate** (not a validated
  player-level forecast) the view says so in the header's info tip and with a small "base rate" chip; where it is
  inferred (college) it says "inferred, not the official portal".
- Probabilities as whole percentages ("23%"), under 1% as "<1%"; a bar's fill is the probability on a 0-100% scale,
  never rescaled per table. Stacked type splits always in the same colour order with a legend.
- Every chart axis has a title (standing rule). ES5 only in the front end (no `?.`, no `??`).
- Phone (375 px): tables keep the name and the chance columns and hide the rest behind the row's expand.

---

## Football (The Quant Footballer)

Payloads (contract: `docs/site/UNIFIED_PAYLOADS.md` section 15): `data/value/moves.json` (one row per player,
`fields`/`rows`, plus `meta`) and `movement` in `data/value/club/<tid>.json`. Units are the Sofascore letters:
`G` Goalkeeper, `D` Defence, `M` Midfield, `F` Attack (`meta.units`). The horizon is `meta.horizon` (e.g. "Winter
2026/27"); show it in every view's title ("Chance of moving this winter").

**What is a model and what is a base rate** (from `meta.validation`, show in the info tips):
- `p` (chance of leaving) is a **base rate**: last same-kind window's rate for players like him (his league and role
  band, or his region's on-loan rate). Chip: "base rate". Tip: "How often players like him (same league, same role
  share) left in Winter 2025/26. Our player-level model is being forward-tested this winter; it did not beat this
  base rate on last summer's window."
- `types` and `dests` (how and where, if he moves) and the targets' ranking are **models that passed** their
  held-out test (Summer 2026). Tip: the numbers in `meta.validation.type`, `.dest`, `.targets`.
- `expected_in` / `p_add` (arrivals) are **base rates** (the league's clubs' arrivals last winter).

### 1. Roster column "Chance of moving" (club page squad table; also the Players section)

- Join `moves.json` rows to the squad by `id`. Column header "Chance of moving" with the horizon in its tip.
- Cell: `QK.probBar`-style horizontal bar (0-100%) with the percentage, the bar split into the five types in
  proportion `p x types[k]` (Transfer, Free transfer, Loan out, Loan ends, Released; `meta.type_labels`), a small
  "on loan" chip when `loan` = 1, and the role band as a muted suffix ("rotation").
- Sort by `p` descending by default; the club file's `movement.roster` ([pid, p, most likely type]) is the same list,
  already sorted, for pages that do not load `moves.json`.
- A player missing from `moves.json` (no club appearance in 180 days) shows "-" with the tip "not enough recent
  minutes for an estimate".

### 2. Team "Outlook" card (club page, in Value & Moves beside Strengths and needs)

- Title: "Outlook: Winter 2026/27". Two KPIs (`QK.kpi`): "Expected departures" = `out_total`, "Expected arrivals" =
  `in_total`, each with the "base rate" chip.
- A four-row grid by unit (Goalkeeper, Defence, Midfield, Attack): expected out (`expected_out[u]`), expected in
  (`expected_in[u]`), and "Chance of adding" (`p_add[u]`) as a bar. Highlight the unit with the largest
  `expected_out - expected_in` as "Biggest gap"; and, from the existing club file, mark the units that are also in
  `weaknesses` (value needs) with a "need" chip, so the card reads "needs" = weak units plus expected gaps.
- Optional chart: `QKC.butterfly` or a diverging `QKC.bar` per unit (out to the left, in to the right); x axis title
  "Players (expected)", y axis "Unit".

### 3. "Targets" table (club page, Value & Moves; the transfer simulator can reuse it)

- Title "Who they could sign"; sub "Ranked by chance of joining: availability x fit x plausibility". From
  `movement.targets` (10 rows, best first; only players who would improve the unit are listed).
- Columns: rank; player (link to `#/player/<id>`), age, unit; club and league (`club`, `league`); **Chance of joining**
  (`p_join`, as a percentage with one decimal under 10%: these are small numbers, say so in the tip: "the chance he
  joins this club this window; 1-3% is a strong target"); **Availability** (`p_move` bar, base-rate chip); **Fit**
  (`q_gap` signed, "+0.25 rating vs your midfield", and `need` as "x0.8 of a starter expected to leave");
  **Plausibility** (`plaus`: "3.1x an average club" for his likely destinations); fair fee and budget fit (`fee`,
  `afford`: "fits", "stretch", "beyond", as the existing targets); and **Why** (`why`, one line, wraps on phone).
- Info tip with the validation: "Tested on last summer's window: 0.28% of the clubs' top-10 names were signed by
  that club, 7x the rate for the most available players alone (0.04%), level with same-league players first
  (0.24%)." Keep it modest: targets are a shortlist, not a prediction of the signing.

### 4. Player page "Movement" card

- Title "Movement: Winter 2026/27". Big number: "Chance of moving" `p` with the base-rate chip and the basis in
  words (`basis`: "players like him in <league>, <band>" / "players on loan in <region>" / "players in <region>").
- "If he moves": two small stacked bars, how (`types`) and where (`dests`: Same league, Stronger league, Weaker
  league, Outside our leagues; `meta.dest_labels`), with the model tip.
- "Likely landing spots" (optional, when the page also loads the club files of his league): the clubs whose
  `movement.targets` list him, with their `p_join`.
- Facts beside it, never mixed into the number: his contract end from Sofascore where `players.json` `until` has it
  ("contract ends Jun 2027 (Sofascore)"), his recent loans.

### Model page text

Render `moves.json` `meta.method` verbatim under a "Who moves next" heading, then a small table of
`meta.validation` (leave, type, destination, arrivals, targets: model v base, CI, passed). It says, as the brief
requires, that there is no contract data and why.

---

## College (The Quant Campus: CFB, MBB, WBB)

Payloads (contract: `oddsmarkets/college/PAYLOADS.md`, "movement.json"): `data/<L>/<S>/movement.json` for the current
season (`players` is a packed list: expand with `CC.unpack` as every Campus payload) and `movement` on the current
season's team pages (`teams/<tid>.json`). The horizon is "before the <next> season" (`meta.next_season`): show it in
every title ("Chance of leaving before 2027"). Every view carries the label **"Inferred from box scores, not the
official transfer portal"** (a chip plus the info tip with `meta.method`).

**What is a model and what is a base rate** (from `meta.validation`):
- `p`, `p_transfer`, `p_gone` are a **model that passed** its held-out test on all three levels (tip: the log-loss and
  CI in `meta.validation.leave`).
- `expected_in` / `p_add` are a **base rate** (last offseason's inferred transfers in per team): "base rate" chip.
- Targets exist for MBB and WBB only (`movement.targets` is null for CFB: the CFB destination model did not pass).
  For CFB, hide the Targets table and show one line: "Targets: not shown for football: our destination model did not
  beat a simple ranking on held-out seasons."
- When `movement.json` has `ok: false` (basketball until about mid-December 2026: `reason` says why), every view
  shows `QK.empty` with the reason, e.g. "Forecasts start when the 2026-27 season has a quarter of its box scores."

### 1. Roster column "Chance of leaving" (team page roster; Players catalogue)

- Join `movement.json` players to the roster by `id` (or use `movement.roster` [pid, p, p_transfer] on the team page).
- Cell: a 0-100% bar for `p`, split into two segments: "Transfer" (`p_transfer`) and "No line next season" (`p_gone`;
  tip: "graduation, the pros, a lower division, injury or not playing"). Percentage label = `p`.
- Suffixes: `class` when present (this season's ESPN roster class, a fact), "transferred in" when `new_in` = 1.
- Football: offensive linemen have no box-score line, so no estimate: "-" with the tip "no box-score line (offensive
  line)". Football positions in this file are box-inferred (WR includes tight ends); show the roster position from the
  team page where it exists and fall back to `pos`.

### 2. Team "Outlook" card (team page, Value & Moves)

- Title "Outlook: before 2027". KPIs: "Expected departures" `out_total`, "Expected transfers out" (sum of
  `expected_transfers_out`), "Expected transfers in" (sum of `expected_in`, "base rate" chip).
- A grid by position (`meta.positions`: CFB QB, RB, WR, DL, LB, DB, K; basketball G, F, C): expected out (with the
  transfer part), expected in, "Chance of adding" (`p_add`) as a bar. Mark the position with the largest
  `expected_out - expected_in` "Biggest gap"; mark the existing `needs` units from the same page with a "need" chip.
- Optional chart: a diverging `QKC.bar` by position (departures left, arrivals right), x axis "Players (expected)",
  y axis "Position".

### 3. "Targets" table (MBB and WBB team pages, Value & Moves)

- Title "Who they could land"; sub "Likely transfers ranked by chance of joining: availability x fit x plausibility".
  From `movement.targets` (10 rows).
- Columns: rank; player (link `#/<L>/player/<id>`), position, current team (`team`); **Chance of joining** (`p_join`,
  one decimal %; tip "the chance he ends up here; around 0.5% is a strong target among ~360 teams"); **Availability**
  (`p_transfer` bar); **Fit** (`pctl`: "84th percentile of guards this season", and the team's expected departures at
  his position from the Outlook card); **Plausibility** (`plaus`: "3.4x an average team"; `margin_step` as "a step up /
  down for him"); **Why** (`why`).
- Tip with the validation: "On the 2023-24 to 2025-26 offseasons, a team's top 10 held its actual incoming transfers 4x
  as often as the most likely transfers alone (0.36% v 0.09% of names, MBB; 0.46% v 0.13%, WBB)."

### 4. Player page "Movement" card

- Title "Movement: before <next season>". Big number `p` ("Chance of leaving"), with the split bar (transfer / no line)
  and one line of context: experience ("3 earlier seasons in our box scores"), `class` if present, "transferred in
  this season" if `new_in`.
- "Teams that fit" (optional, when the page loads the level's team pages): teams whose `movement.targets` list him, with
  their `p_join`.
- The existing career `moves` list (inferred transfers that happened) sits under it as history.

### Model page text

Render `movement.json` `meta.method` under "Who moves next", then a table of `meta.validation` (leave, joint, targets:
model v base, CI, passed) for the level shown.

---

## US sports (The Quant Hardwood, Gridiron, Bullpen, Rink)

One payload shape for all five leagues (engine `oddsmarkets/common/movement.py` `payload()`; method and validation in
`docs/research/moves_model.md`, `moves_hardwood.md`, `moves_gridiron.md`, `moves_rink.md`):

| League | Payload | Phase today | Value unit | Positions |
|---|---|---|---|---|
| NBA | `hardwood/data/nba/movement.json` | season start (`inseason`) | WAR (Hardwood) | G, F, C |
| WNBA | `hardwood/data/wnba/movement.json` | after the season (`offseason`) | WAR (Hardwood) | G, F, C |
| NFL | `gridiron/data/<S>/movement.json` | week 6 (`inseason`) | points above replacement | QB RB WR TE OL EDGE DL LB CB S K P LS |
| MLB | `bullpen/data/mlb/movement.json` | after the season (`offseason`) | WAR (Bullpen) | C 1B 2B 3B SS LF CF RF DH SP RP |
| NHL | `rink/data/<SSSSSSSS>/movement.json` | ~12% into the season (`inseason`) | WAR (Rink) | C LW RW D G |

Keys (never renamed; read by name, not position):
- `players`: rows with `player_fields` = `pid, name, team, pos, age, yrs, value, p_next, p_<type>... , p_dl, why`.
  `p_next` = chance the player is not with this team at `horizons.next`; `p_<type>` (in `types` order, labels in
  `type_labels`) split it and sum to it; `p_dl` = chance he moves before `horizons.deadline`, labelled with
  `deadline_label` ("traded" for MLB, "traded or claimed" elsewhere: the box scores cannot tell the two apart);
  `why` = up to two drivers in words ("age 34, a small role"). A probability is `null` when its block is not
  published.
- `teams[tid]`: `wp`, `status` ("contending" / "in the middle" / "rebuilding", cut-offs in `status_cuts`), `traj`,
  `exp_departures`, `exp_arrivals`, `outlook` rows (`team_fields.outlook`: `pos, p_add, exp_arrivals, need,
  exp_departures, players`), `targets` rows (`team_fields.targets`: `pid, name, team, pos, age, value, gain, p_move,
  p_join, why`). Empty lists / `null` when not published.
- `published` {next, deadline, type, arrivals, targets}, `reasons` {block: one sentence, show it verbatim where the
  block would be}, `base_rates` {next, deadline, types}, `base_arrivals` {pos: [p_add, mean]}, `team_horizon`
  ("deadline" or "next": the horizon of the Outlook and Targets), `horizons` (`deadline`, `deadline_estimated` where
  set, `next`), `validation` (per block `test`/`dev`: n, rate, log-loss and Brier with gains and CIs, calibration
  slope, in-the-large, deciles), `drivers` (the largest standardised coefficients), `notes`, `snapshot`.
- Sport extras: NBA/WNBA `roster_source`, `recent_rates`; NHL `label_check` (in-season moves the games found v ESPN's trade and waiver rows); NFL
  `horizons.snapshot_week`.

**What is published today (22 Oct 2026)** — the views must follow `published`, not this table:

| | Leaves by next season | Before the deadline | Type split | Outlook | Targets |
|---|---|---|---|---|---|
| MLB | model | base rate (calibration miss) | model | model | model |
| NBA | model | model | model | base rate | hidden |
| WNBA | base rate | base rate | base shares | base rate | hidden |
| NFL | model | model | base shares | base rate | hidden |
| NHL | model ("not in the lineup") | base rate | base shares | base rate | hidden |

### 1. Roster column "Chance of moving" (team page roster table; Players catalogue)

- Header "Chance of moving", tip: "by `horizons.next`" plus the first `notes` line. Cell: a 0-100% bar
  (`QK.chanceBar({ label: name, p: p_next })`, kit v2 "Signal") with the percentage, the bar segmented by
  `p_<type>` in the `types` order with a `QK.keys` legend once per table (Trade / Release or waiver / Free agency /
  Other; NFL: In-season move / Released in season / Offseason departure). When `published.type` is false add the
  "base shares" chip to the legend: the split is the league's shares, not the player's.
- A second, narrower column "Deadline" (`p_dl`, label from `deadline_label`: "Traded" or "Traded or claimed") when
  `published.deadline`; otherwise one line above the table: "About `base_rates.deadline` of players are
  traded/claimed before `horizons.deadline`" with the "base rate" chip and `reasons.deadline` in its tip.
- `why` as a muted second line under the name on desktop, inside the row's expand on phone.
- When `published.next` is false (WNBA today), do not show a per-player column: show the league line "About
  `base_rates.next` of rostered players leave by next season (last three seasons: `recent_rates.next`)" with the
  base-rate chip and `reasons.next`.
- Default sort: `p_next` descending. MLB NHL wording: NHL `p_next` reads "Chance he's not in the lineup next season"
  (it includes a season in the minors); MLB and NBA "Chance he's gone by next season".

### 2. Team "Outlook" card (team page, Value & Moves, beside Strengths and needs)

- Title "Outlook: `horizons.next`" (or "to the deadline" when `team_horizon` = "deadline"), with the `status` as a
  chip ("contending", "rebuilding": from our standings, cut-offs in the tip).
- Stat tiles (`QK.stats`): "Expected departures" `exp_departures`, "Expected arrivals"
  `exp_arrivals` (from other teams' rosters; prospects, draft picks and players from outside the league are not
  counted: say so in the tip).
- A position grid from `outlook`: position, "Chance of adding" (`p_add` bar), expected arrivals, expected departures
  there, and `need` as a percentile chip (`QK.pctlChip((1 - need) * 100)`: the team's strength at the position among
  the league). Mark positions that are also in the existing `weaknesses` with a "need" chip.
- When `published.arrivals` is false: the grid shows `base_arrivals[pos][0]` with the "base rate" chip and
  `reasons.arrivals`, and the expected-arrivals tile shows the sum of `base_arrivals[pos][1]` labelled "league
  average".
- Optional chart: a diverging `QKC.bar` per position (departures left, arrivals right); x axis "Players
  (expected)", y axis "Position".

### 3. "Targets" table (team page, Value & Moves; the trade simulator can prefill from it)

- Only when `published.targets` (MLB today). Title "Who they could get"; sub "Ranked by chance of joining: chance he
  moves x chance he lands here; only players who would upgrade your weakest regular at the position".
- Columns: rank; player (link), age, position; team (mark); **Chance of joining** (`p_join`, one decimal: "1.8%";
  tip: "the chance the player joins this team by `horizons.next`; 1-2% is a strong target among 30 teams"); **Availability**
  (`p_move` bar); **Fit** (`gain` signed in `unit`: "+0.7 WAR over your 3B slot"); **Why** (`why`).
- Info tip from `validation.targets.test`: "On 2023-2025, 2.7% of a team's top 10 joined it, against 0.3% for the
  best upgrades alone and 0.8% by chance." Keep it modest: a shortlist, not a prediction of the move.
- Where targets are hidden, show `reasons.targets` in a `QK.empty` and keep the existing "Ways to improve" list as it
  is (it is the need x value ranking).

### 4. Player page "Movement" card

- Title "Movement". `QK.playerHeader` stat or a stat tile: "Chance of moving" `p_next` with the horizon; under it the
  type split as a stacked bar with the legend, and "Before the deadline" `p_dl` when published.
- Context line from the row: age, `yrs` ("8 seasons since his debut" MLB; "8 accrued seasons" NFL; "seasons in the
  league" NBA/NHL), `value`, and `why`.
- "Teams that fit" (optional, MLB): the teams whose `targets` list him, with `p_join`.
- Facts never mixed into the number: his transactions history (existing moves/transactions payloads).

### Model page text

Under "Who moves next": the `notes` verbatim (they include the no-contract-data sentence the brief requires), then a
table from `validation` (block, sealed seasons `split.test`, n, rate, model v base log-loss, gain with CI, Brier gain,
calibration slope, published yes/no with `reasons`) and a decile chart for `next` (`QKC.line` or scatter of
`deciles`: x axis "Predicted chance", y axis "Observed share", the diagonal as reference).

Kit note (US sports): the v2 "Signal" kit is committed (855814be; `docs/_design/MIGRATION_V2.md`), so build these
views with `QK.sectionHead`, `QK.stats`, `QK.chanceBar` / `QK.chances`, `QK.leaderboard`, `QK.keys`, `QK.pctlChip`,
`QK.playerHeader` and `QK.empty`. A payload written before 22 Oct 17:30 may lack `team_horizon` and `base_arrivals`
until its daily refresh: treat a missing `team_horizon` as "deadline" in season and "next" after it.
