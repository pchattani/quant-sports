# Player value, best by position, and team strengths/needs (all sites except The Quant Ace)

Shared spec so the six sites build the same feature the same way. Requested 15 Oct 2026: "build a section that is
about player value and best in each position in all applicable sports (except tennis). In the team page suggest
strongest points and strongest weak points and potential trade or signings to improve."

## 1. A "Value" section on each site (`#/value`, in the nav)
- **One value currency per sport**, from the models we already have, documented on the page and in the
  methodology: football (Sofascore-based player value from minutes, ratings, xG/xA/defensive actions, per 90 and
  totals; if a goals/points-above-replacement can be built from the existing models, prefer it), NBA/WNBA (the
  RAPM/box impact value, wins above replacement), MLB/AAA/NPB (WAR / WAR-lite), NFL (the EPA-based player value,
  QB model), NHL (Rink value GAR/WAR), F1 (driver value: pace above team-mate and above the field from the
  decomposition — no positions; constructors ranked by car pace).
- **Leaderboard**: season value, per-game/per-90/per-60 rate, percentile, trend v last season, filters (league,
  team, position, minimum sample), with sample floors honoured.
- **Best at each position**: the sport's positions (football GK/DF/MF/FW, or finer where data allows; NBA
  guards/wings/bigs or PG–C; MLB/NPB C/1B/2B/3B/SS/LF/CF/RF/DH/SP/RP; NFL QB/RB/WR/TE/OL where data/edge rushers/
  LB/CB/S/K/P as data allows; NHL C/LW/RW/D/G): top 5–10 per position with value, rate, percentile and a short
  "why" (the components that drive the value).

## 2. Team page: "Strengths and needs"
- Grade every position/unit against the league (team value at that position v league distribution → percentile
  and a letter or tier).
- **Top 3 strengths** and **top 3 weaknesses**, each with the evidence (value, percentile, the stat behind it).
- **Ways to improve** for each weakness: ranked candidates from other teams (trade targets) and, where the data
  identifies them, free agents / unsigned players. For each: projected value gain at that position (in the sport's
  currency, and in wins/points where possible), age, contract/salary only where a legitimate data source exists
  (e.g. nflverse contracts for the NFL); a feasibility hint where the data supports one (the other team is out of
  contention, has surplus depth at the position, player in a contract year). Never invent salaries, contracts or
  availability.
- **Honest labelling** on the page: "model suggestions based on on-field value; not considering salary cap,
  contracts, fit or availability unless shown." Off-season and in-season behave the same; transfer windows
  (football) noted when open.

## 3. Trade section with a trade simulator (`#/trade`), and transfers for football
Added 15 Oct 2026: "Add a trade section with a trade simulator to see how the trade stacks up for teams. Same idea
for soccer adapted to transfers and fair value."
- **Trade simulator (NBA/WNBA, MLB/AAA/NPB, NFL, NHL):** pick two (or more) teams and the players moving each
  way; the page shows, per team: value in and out (sport currency), the position-aware net effect (who the incoming
  player displaces on the depth chart; replacement level at each position from that team's own roster), projected
  change in team rating and wins over the rest of the season, and the change in playoff/title odds. Odds must come
  from the season simulation, not guesswork: precompute per team a sensitivity curve (playoff, division/seed and
  title probability v a rating shift, from re-running the season sim at several shifts) so the browser can
  interpolate instantly. Age/term context (value next season from the projection/aging curve) shown where the
  model has it. Salary/cap legality only where a legitimate source exists (NFL: nflverse contracts); otherwise say
  it is not checked. A verdict line per team ("wins now / weakens now / long-term gain") and a share link (state
  in the URL hash).
- **Transfer simulator (football):** pick a player and a buying club (and optionally players out); show the
  player's value to the buyer (position-aware: who he displaces, minutes he would take), the change in the buyer's
  and seller's ratings, title / European places / relegation odds via precomputed sensitivity curves from the
  league simulation, and a **fair transfer fee**: a model of value-to-fee from the player's on-field value, age,
  position and league strength (calibrated on real transfer fees only if a legitimate source with acceptable
  terms exists — otherwise present a value-based "fair value index", clearly labelled, not a euro figure). Show
  Sofascore's market value alongside only if it is already in our stores. Window status (open/closed) noted.
- **F1:** a driver-swap simulator ("put driver X in car Y") using the pace decomposition: change in expected
  points and championship odds for both teams, from the season simulation's sensitivity.
- All simulators are client-side over precomputed compact payloads; every number on them traceable to a model.

## 4. Valuation, market values, transactions and budgets (added 16 Oct 2026)
User: "Improve on the valuation concept and add market values, recent transfers/trades, rating for trades done in
a year and transfers too. Just overall better analytics on trades and transfers. Also incorporate realistic
budgets for team based on previous spend or data for soccer."
- **Valuation v2:** value = projected multi-season surplus (on-field value by season from the projection/ageing
  curves, discounted), position scarcity, injury/availability risk where data exists; uncertainty bands.
- **Market values** only from sources whose terms allow our use (the user's standing rule: if terms forbid
  reuse, leave it out and say so). Football: Sofascore's market value (already our source). Other sports: none
  exist freely — show model value only.
- **Transactions feed:** recent trades/transfers/signings/releases from legitimate sources (Sofascore transfer
  history; MLB Stats API transactions; ESPN transactions endpoints for NBA/WNBA/NFL/NHL; NHL api-web if it has
  them) — verify each source's terms before use.
- **Trade/transfer ratings:** every transaction in the last 12 months graded for each side: value at the time
  (model), value since (realised performance after the move), fee/market value v fair value (football), a grade
  and winner, updated as results come in; league-wide "best/worst deals" tables and per-team ledgers.
- **Football budgets:** each club's realistic transfer budget from its own history (gross and net spend by
  window from transfer fees in the transfer history, league and club strength, recent sales), with a range; used
  by the transfer suggestions and simulator ("can they afford it?" against fair fee / market value).

**As built, football (16 Oct 2026):** `docs/MODELS.md` 11c. Sofascore transfer lists and histories (Transfermarkt
not used: its terms), valuation v2 with a band, a fee model fitted on 701 real fees (out of sample: typical error
x1.82 v x2.40 for a league-and-position median; Spearman 0.76 with Sofascore's market values), deal grades for
both clubs, ledgers, window summaries, budgets (out of sample Spearman 0.72, 49.6% inside the 25-75% range) used
by the club suggestions and the simulator.

## 5. Fantasy layer (added 16 Oct 2026)
User: "build a layer that helps find good players in a league for fantasy with your suggested picks based on
current and past season data or other analytics. Go deep."
- Per sport, a `#/fantasy` section: projections in standard scoring formats (football: an FPL-style points system
  computed by us; NFL: PPR/half/standard; NBA/WNBA: points and 9-category; MLB: 5x5 roto and points; NHL: standard
  points/categories; F1: a fantasy-style driver/constructor points model), built from our models (minutes/usage,
  per-90/per-game rates, matchups/opponent strength, schedule/fixture difficulty, rest, injuries where known).
- Pages: rankings and tiers (draft/season), rest-of-season and next-period (gameweek/week) projections,
  value over replacement by position, schedule/fixture difficulty, start/sit, waiver/transfer targets (risers,
  undervalued, buy-low/sell-high from luck v underlying), sleepers/breakouts, differentials, captain picks
  (football), streaming (MLB pitchers, NHL goalies), and "our suggested picks" with reasons.
- Backtest each projection walk-forward against actual fantasy points (error and rank correlation v naive
  baselines such as last season / season-to-date). Third-party fantasy-game data (official prices, ownership,
  ADP) only if its terms allow our use; otherwise leave it out and say so.

**As built, football (16 Oct 2026):** `docs/MODELS.md` 11d, `#/fantasy` for the 13 followed leagues. Walk-forward
over 389 rounds: MAE 1.50 v 1.52 (last five), RMSE 2.35 v 2.50, within-round rank correlation 0.54 v 0.52, top-20
picks 4.35 v 3.80 points. Official FPL prices/ownership left out (Premier League terms); prices are our proxy.

## 6. Engineering rules
- Build in each site's existing analytics/build layer; reuse its value models; payloads documented in the
  sport's PAYLOADS/CONTRACT "As built"; tests for position grading, candidate ranking and sample floors.
- Front end in each site's style; esprima on edited JS; no `?.`/`??`; no horizontal overflow at 375 px.
- Keep each public site under its size budget (football ~700 MB now, bullpen ~765 MB; Pages cap 1 GB): value
  payloads compact; per-team files rather than one giant file.
- No git write commands by agents; the main session commits. Builds run hourly via `scripts/local_sites.py`.
