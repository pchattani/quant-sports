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
