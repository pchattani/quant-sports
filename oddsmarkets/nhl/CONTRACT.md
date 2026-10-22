# The Quant Rink: data and model contract

NHL only. Seasons labelled by the NHL id `20262027` (also usable as the end year 2027 in display). Ids: games = NHL gameId
(e.g. 2026020009: season + type 01 pre / 02 regular / 03 playoffs + number); players = NHL playerId; teams = tri-codes per season
(relocations: ATL→WPG 2011, ARI→UTA 2024; Seattle 2021 expansion; Vegas 2017). Regular season is 84 games per team from 2026-27
(82 before; 48 in 2012-13; 56 in 2020-21; 2019-20 paused). Points: W 2, OTL/SOL 1; standings tiebreakers per the NHL rule (regulation
wins first, verified and cited in canon). Dependencies: numpy, scipy, pandas, requests, pyarrow, lightgbm. No network in tests.
Roots: `RINK_DATA` (default `docs/rink/data`), `RINK_RAW` (default `data/nhl`), `RINK_CACHE` (default `data/nhl/cache`).
**No agent runs git write commands. Bounded memory** (one season at a time; no recursive closures holding arrays).

## 1. Data (builder A)
Sources (no keys; the NHL APIs have no CORS → fetched in CI only):
- `api-web.nhle.com/v1`: /schedule/{date}, /club-schedule-season/{team}/{season}, /standings/{date}, /roster/{team}/{season},
  /player/{id}/landing, /gamecenter/{id}/play-by-play, /boxscore, /landing, /right-rail, /partner-game/US/now (DraftKings),
  /edge/... (skater/goalie/team detail; 2021-22→). "now/current" URLs redirect (307) — call dated forms.
- `api.nhle.com/stats/rest/en`: shiftcharts?cayenneExp=gameId=X (2010-11→), skater/goalie/team summary and realtime reports
  (limit=-1), season list.
- MoneyPuck shot files (benchmark only; non-commercial with credit "Data from MoneyPuck.com"; file downloads only, ≤ nightly).
- ESPN NHL scoreboard/summary (pickcenter DraftKings ml/puck line/total with open/close; plays with coordinates; onIce) and core odds
  (books 2019-20→; open/close blocks 2022-23→, `canon.ESPN_OPEN_CLOSE_FROM`).
Raw (git-ignored): `<raw>/pbp/<season>/<gameId>.json.gz`, `<raw>/shifts/<season>/<gameId>.json.gz`, `<raw>/edge/<season>/...`,
`<raw>/moneypuck/...`.
Derived compact tables per season (git-ignored, rebuildable): `<raw>/derived/<season>/events.parquet` — one row per event:
game_id, period, sec (elapsed game seconds), type, team, x, y (normalised so the attacking team shoots at +x), zone, shot_type,
shooter, goalie, assist1/2, strength (from situationCode: skaters home/away, goalie in net), score_home/away, home/away on-ice
skaters (6 slots each from shifts) and goalies; `stints.parquet` (on-ice segments with skaters/goalies, start/end sec, strength,
events for/against: shots, unblocked attempts, goals, xG (filled by builder B)).
Stores (committed for completed seasons): `docs/rink/data/<season>/store.json` — teams, games
`{game_id, date, start, type, home, away, hs, as, status, period, ot, so, venue, lines: {ml, puck_line, total, open, close, books}|null,
goalies: {home, away}, attendance}`, standings snapshot, players (names, pos, shoots, dob, height, weight, number).
`sources/{_client,nhl,stats,edge,moneypuck,espn}.py`; `canon.py` (teams by season, divisions/conferences by season, formats,
tiebreakers, arenas with coordinates); `scripts/nhl_fetch.py`.

### 1a. As built (builder A, 1 Oct 2026)
Modules: `canon.py`, `store.py`, `derive.py` (added: pbp + shifts -> events / stints / check), `sources/{_client,nhl,stats,
edge,moneypuck,espn}.py`, `scripts/nhl_fetch.py`, `scripts/nhl_backfill.ps1`. Tests `tests/nhl/test_data.py` (recorded fixtures).
- Raw (git-ignored): `<raw>/pbp|shifts|box/<S>/<gameId>.json.gz`, `<raw>/edge/<S>/{skater,goalie,team}/<id>_<gameType>.json.gz`,
  `<raw>/stats/<S>/<report>_<gameType>.json.gz` (skater/goalie/team summary, skater/team realtime), `<raw>/moneypuck/shots_<S>.parquet`
  (slim; `nhl_game_id` added; join to events on (game_id, sec, shooter) = (nhl_game_id, time, shooterPlayerId):
  `moneypuck.join_events`; MoneyPuck `id` is NOT the eventId; its xCordAdjusted folds every shot to +x), `<raw>/derived/<S>/
  onice_check.json`, `<cache>/stats_seasons.json`.
- events.parquet columns: game_id, season, gtype, event_id, sort, period, ptype (REG/OT/SO), t (s into period), sec (elapsed;
  RS shootout = 3900), type (api-web typeDescKey), team, is_home, x_raw, y_raw, x, y, zone (O/N/D for `team`, from x, blue lines
  +-25), zone_raw, shot_type, shooter, goalie, assist1, assist2, player1, player2 (faceoff winner/loser, hitter/hittee, blocker,
  penalised/drawn, giver/taker), reason, pen_type, pen_desc, pen_min, sit, home_sk, away_sk, home_gin, away_gin, strength ("5v4",
  event team first), state (EV/PP/SH/EN/PS, event team), score_home, score_away (BEFORE the event), penalty_shot, home_s1..home_s6,
  home_g, away_s1..away_s6, away_g, n_home_sk, n_away_sk, onice_ok, onice_strict, stint. `team` of every shot type (blocked
  included) is the SHOOTING team (from the shooter's roster spot), so blocked shots count as attempts for the shooter's side.
- Direction: per period, majority vote of unblocked shots beyond +-25 ft; fallback homeTeamDefendingSide (absent before ~2019-20)
  then alternation. Verified: normalised zone == NHL zoneCode on 100% of 2026-27 unblocked shots; inferred side ==
  homeTeamDefendingSide on every period where published.
- On ice: start < t <= end within the event's period; faceoff / period-start use start <= t < end. onice_ok also accepts the
  "just after" set for penalty / stoppage / delayed-penalty (their situationCode often already shows the post-call state);
  onice_strict does not. Shootouts and penalty shots get no check. Games without shift charts (2009-10; rare gaps) have NA slots
  and no stints. Where stats REST answers empty (e.g. 2024021235-1291), shifts are rebuilt from the NHL HTML TOI reports
  (`stats.shifts_from_toi_html`; raw file carries "source": "html"; meta.shifts[gid] = {"html": true}).
- `store.save_owned` replaces the in-memory game / meta dicts with the merged copy: never hold a game or meta dict across a
  save (re-read `s["games"][gid]`).
- stints.parquet: game_id, season, gtype, stint, period, start, end (game s), t0, t1, dur, home_s1..6, home_g, away_s1..6, away_g,
  n_home_sk, n_away_sk, home_gin, away_gin, strength / state (home view, from shift counts), bad (counts outside 3..6 or 2 goalies),
  score_home, score_away (at start), start_zone (home view O/N/D of a faceoff at the first second, F = on the fly),
  {home,away}_{sog,fenwick,corsi,goals,pen}, xg_home / xg_away (NaN, builder B fills). events.stint links the two.
- GAME (store.json) extra fields: season, neutral, venue_tz, series {round, series, game} (playoffs), espn_id. `goalies` =
  {home|away: {starter, used: [pid], decision}}. `lines` = {src, ml: [home, away], puck_line: {home, price: [h, a]} | null,
  total: {line, over, under} | null, open / close: {ml, puck_line, total} | null, consensus {ml, total, n_books}, books: [{id, name,
  ml, puck_line, total, open?, close?, suspect?}], v}. Books with in-play "current" numbers (moneyline overround outside
  1.00-1.15 or a total >= 1 goal off the median) are `suspect` and never the main line. Upcoming games: ESPN pickcenter
  (DraftKings, open/close), else NHL partner odds (`partner-game/US/now`: the one "now" URL, it has no dated form).
  `attendance` from ESPN scoreboards (2019-20 ->).
  `probables` (from 22 Oct 2026; ESPN scoreboard, recorded before the start only) = {home|away: {id (NHL pid when the
  name maps, else null), espn, name, status "projected"|"confirmed", since, confirmed_at, log: [[at, id or name,
  status]] (one entry per change, last 12)}, at (last read)}.
- store.json top level: season, updated_at, teams (canon.teams: abbr -> {name, id, conference, division, colour, alt, franchise}),
  games, standings {date, season, rows: [{team, conference, division, gp, w, l, otl, pts, pct, rw, row, gf, ga, sow, sol, streak,
  l10, seq {league, conference, division, wildcard}, clinch}]} (last regular-season day for past seasons), players {pid: {name,
  first, last, pos, shoots, dob, height (in), weight (lb), number, team, country}}, meta (fetch marks, season_dates, derived
  summary, edge marks, espn_days / espn_odds, moneypuck marker).
- canon: `teams(S)`, `team_ids(S)`, `abbr_from_id`, `code_in_season` (WPG<-ATL 2011, ARI<-PHX 2014, UTA<-ARI 2024; Utah id 59 then
  68), `abbr_from_espn`, `formats(S)` (games, ot, playoff kind), `decode_situation`, `strength_state`, `ARENAS` / `arena_for_game` /
  `home_arena` / `haversine_km`, tiebreak: `TIEBREAK_STEPS` by era (2019-: gp, rw, row, w, h2h, diff, gf; 2010-18: gp, row, h2h,
  diff; -2009: gp, w, h2h, diff), quoted text `tiebreak_steps(S)`, `head_to_head` (odd games excluded), `order_tied`, `rank`,
  `records_from_games`, `playoff_seeds`. Divisions / club sets verified against /v1/standings for every season 2009-10 -> 2026-27
  (`nhl_fetch.py --check-canon`).

## 2. Models (`oddsmarkets/nhl/models/`)
Common: pure functions + cached `for_season(season)`; committed fits in `models/fitted/` used when the cache is cold (CI); `_io.py`
created by builder B.
Builder B: `xg.py` (unblocked-attempt xG: distance, angle, shot type, rebound, rush, time since last event, previous event type and
location, strength, score state, arena adjustment; cross-fitted by season; benchmark v MoneyPuck xGoal), `shooting.py` (goals above
xG, shrunk), `goalies.py` (GSAx by danger and shot type), `onice.py` (5v5/PP/PK on-ice rates per 60, score/venue adjusted),
`rapm.py` (ridge on stints, separate offence/defence, with zone-start and score controls; multi-season priors), `value.py`
("Rink value": RAPM + box prior → goals/wins above replacement; goalies separately), `lines.py` (forward lines and D pairs), `stabilise.py`.
Builder C: `team_strength.py` (score/venue-adjusted xG and shot rates by strength, special teams, goalie component with starter as
input, schedule effects), `game.py` (goal model: bivariate Poisson with a common-shock term θ ≥ 0 for minutes 0-57, then a late-game Markov
chain (tied-game slowdown, goalie pull and empty net); as built θ is fitted on the grid and has landed on 0, i.e. independent
Poisson; outputs win, puck line, total, P(OT), shootout), `live.py`, `season_sim.py` (84 games, points system, tiebreakers,
divisional + wild-card playoffs, best-of-7 bracket, Presidents' Trophy, lottery, point totals v Kalshi KXNHLSEASONPTS, magic
numbers, interventional next-game odds), `awards.py` (Hart, Vezina, Norris, Calder, Ross, Richard, Selke; verified winners table),
`backtest.py` (v ESPN closing lines 2019-20→; Elo and xG baselines 2010→), `sources/markets.py` (Kalshi KXNHLGAME, KXNHLSPREAD,
KXNHLTOTAL, KXNHL-27, KXNHLEAST/WEST, division series, KXNHLPLAYOFF, KXNHLPRES, KXNHLSEASONPTS, awards; Polymarket tag nhl and
games via series_id=10346).

### Value layer additions (16 Oct 2026)
`analytics/gamelog.py` (per player-game logs: boxscores + player-game table + shot table, cached per season),
`analytics/valuation.py` (valuation v2: multi-season WAR with ageing, survival, availability, uncertainty band, positional
replacement; the as-of-a-date valuation for trade ratings), `analytics/moves.py` (ESPN transactions parsed into clauses,
names matched, deals grouped and graded; the pick-value curve), `analytics/fantasy.py` (fantasy projections and the
walk-forward backtest), `sources/moves.py` (ESPN transactions and injuries, records.nhl.com drafts, NHL player search,
player landings), `scripts/nhl_fantasy_backtest.py`. Payloads valuation.json, transactions.json, deals.json, fantasy.json,
fantasy_backtest.json (PAYLOADS.md "As built"); pages `#/value?tab=val`, `#/moves`, `#/fantasy`, the team page's Ledger.
