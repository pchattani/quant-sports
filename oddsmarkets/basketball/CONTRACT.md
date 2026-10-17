# The Quant Hardwood: data and model contract

Every builder codes to these shapes. Leagues are `"nba"` and `"wnba"`. A **season**
is labelled by the year it ends in (NBA 2026-27 = `2027`; WNBA 2026 = `2026`), the ESPN
`season.year` convention. All ids are ESPN ids as strings. Times are UTC ISO strings;
game clocks are seconds remaining in the period (`clock_s`), and `t` is elapsed game
seconds (`period_start + period_len - clock_s`; NBA periods 720 s, WNBA 600 s, OT 300 s).

No new dependencies: numpy, scipy, pandas, requests only. No network in tests.

## 1. Sources and stores (builder A)

`oddsmarkets/basketball/sources/espn.py`
- `Client(budget=..., interval=0.5)`: paced GET with retry/back-off, call counter, never raises
  on a bad game (returns None, logs).
- `scoreboard(c, league, yyyymmdd) -> list[dict]` (one day; multi-day ranges return non-JSON).
- `summary(c, league, event_id) -> dict | None` (raw).
- `teams(c, league)`, `roster(c, league, team_id)`, `injuries(c, league)`, `season_dates(c, league, year)`,
  `standings(c, league, season) -> {team_id: {"conference","division"}}` (any season).
- `compact_game(raw) -> dict` (below); `compact_pbp(raw) -> dict | None`; `compact_event(scoreboard_event) -> GAME` skeleton
  (no box); `calendar(raw_scoreboard) -> [YYYYMMDD]` (the season's game days). Running out of budget raises `BudgetExhausted`.

`oddsmarkets/basketball/store.py`: `docs/hardwood/data/<league>/<season>/store.json`
```
{"league","season","updated_at",
 "teams": {team_id: {"name","abbr","location","colour":"#rrggbb","alt_colour","conference","division"}},
 "players": {player_id: {"name","short","pos":"G|F|C|G-F|F-C|...","pool":"G|F|C","jersey","dob"|null,"teams":[team_id...]}},
 "games": {game_id: GAME},
 "meta": {"fetched": {game_id: iso}, "complete_through": "YYYY-MM-DD", "calendar": [YYYYMMDD], "days": {YYYYMMDD: iso}}}
```
GAME (`compact_game`):
```
{"id","date": iso,"status":"pre|in|post|postponed|canceled","stype":"pre|reg|playin|post|cup|allstar",
 "neutral": bool,"home": team_id,"away": team_id,"hs": int|null,"as": int|null,"periods": n,
 "line": {"home": [pts per period], "away": [...]},
 "box": {team_id: {"players": [[player_id, starter(0/1), sec_played, pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf, plus_minus]],
                   "dnp": [[player_id, reason]],
                   "team": {"fgm","fga","tpm","tpa","ftm","fta","oreb","dreb","ast","stl","blk","tov","team_tov","pf","pts_paint","pts_fastbreak","pts_off_tov","largest_lead","lead_changes"}}},
 "odds": {"provider","spread_home": float|null,"total": float|null,"ml_home": int|null,"ml_away": int|null} | null,
 "predictor": {"home": P(home wins)} | null,   # ESPN matchup predictor when the summary has one (kept across refetches)
 "injuries": {team_id: [[player_id, status, detail]]},
 "venue": {"id","name","city","state"} | null, "attendance": int|null,
 "series": {"round","game","summary"} | null, "has_pbp": bool}
```
Box column order above is fixed (`BOX_COLS` constant in `store.py`). `sec_played` comes from whole box minutes
(×60). `plus_minus` is null where ESPN has none (before about 2007). Team line: the counting stats are the
players' sums (ESPN's own team line is column-shifted in 2017-18); `tov` = all turnovers including team
turnovers, `team_tov` = `tov` − Σ player tov; `pts_off_tov` is ESPN's `turnoverPoints` as given; paint/fast-break
null where ESPN writes −1. `injuries` is filled only for games not yet final (ESPN's summary lists today's
injuries, not the game day's). `series` only for playoff games. All-Star games are not stored.

Raw play-by-play (git-ignored): `data/basketball/pbp/<league>/<season>/<game_id>.json.gz`
(`compact_pbp`): `{"id","periods","plays": [[seq, period, clock_s, type_id, team_id|null, [participant ids], x|null, y|null, score_value, shooting(0/1), scoring(0/1), home_score, away_score, text, points_attempted]], "types": {type_id: ESPN type text}, "wp": {seq: home_wp}}`.
Coordinates are ESPN's (half-court, whole feet: x 0..50 with the rim at 25, y along the floor from the
shooting team's basket with the rim centre at y = 0.75); `pbp.py` normalises them. Substitution participants
are [entering, leaving]; assisted makes [shooter, assister]; blocked misses [shooter, blocker]; steals [loser, stealer].

## 2. Possession and lineup reconstruction (builder A): `oddsmarkets/basketball/pbp.py`

- `parse(pbp, game, league=None, season=None) -> GameEvents` (league inferred from the period-1 clock when not given) with `events`
  (typed: shot, ft, reb, tov, foul, sub, timeout, jump, period_start/end, other), `lineups` (the fives on the floor at each event)
  and `possessions`: `[{"team","start_t","end_t","start_kind":"tr|made|dead|oreb|period","pts","end":"made|dreb|tov|ft|period|other","players_off":[5],"players_def":[5]}]`.
  Offensive rebounds continue a possession, so `oreb` is never produced; `end: "other"` is a held-ball jump won by the defence
  (or a data glitch). Technical free throws never change possession; flagrant, clear-path and lone (take-foul) free throws keep the ball.
- `stints(game, events) -> list[STINT]`, STINT = `{"t0","t1","home":[5 ids],"away":[5 ids],"poss_home","poss_away","pts_home","pts_away","fga_h","fga_a","tov_h","tov_a","oreb_h","oreb_a","fta_h","fta_a"}`.
- `shots(game, events) -> list[SHOT]`, SHOT = `[game_id, t, period, team, shooter, x_ft, y_ft, dist_ft, angle_deg, zone, shot_type, value(2|3), made(0/1), assisted(0/1), assister|null, blocked(0/1), putback(0/1), transition(0/1), margin_before, clutch(0/1)]`
  - `x_ft, y_ft`: feet from the basket, x across (−25..25), y along (0 at the rim).
  - zones: `rim` (<4 ft), `paint` (4–14 in lane), `mid` (other 2s), `corner3`, `ab3` (above-break 3), `heave` (>40 ft).
  - shot_type: `dunk|layup|tip|hook|floater|jumper|pullup|stepback|fadeaway|turnaround|other` from ESPN type ids/text.
- `reconcile(game, stints) -> {"max_err_s", "per_player": {pid: err_s}, "ok": bool, "bad_lineup_s"}` vs box minutes (ok = within 60 s);
  `points_check(game, events) -> {"home": [events, box], "away": [...], "ok"}` exact; `derive(pbp, game, league, season)` does all of it for one game.

Derived inputs, committed per season (builder A, `scripts/bb_derive.py`):
- `docs/hardwood/data/<league>/<season>/shots.json`: `{"cols":[...SHOT names], "rows": [[...]]}`
- `docs/hardwood/data/<league>/<season>/stints.json`: `{"cols":[...], "rows": [[game_id, t0, t1, h1..h5, a1..a5, poss_h, poss_a, pts_h, pts_a]]}`
- `docs/hardwood/data/<league>/<season>/recon.json`: `{"version","summary": {...season shares}, "games": {game_id: {"max_err_s","ok","points_ok","pts","poss","three_agree","fixes","stints","sig"}}}`.

## 3. Models (builders B and C): `oddsmarkets/basketball/models/`

Common: each model has a pure function on in-memory inputs (testable on synthetic data) and a
cached loader `for_season(league, season, through=date|None)`; caches under `data/basketball/cache/`
(env `HARDWOOD_CACHE`). Data root env `HARDWOOD_DATA` (default `docs/hardwood/data`).

Builder B
- `ratings.py`: `fit_ratings(games, through, half_life_days, ridge, prior=None) -> {"teams": {tid: {"off","def","net","pace","se_net","games"}}, "hca","league_ortg","league_pace"}`
  (per 100 possessions; possessions from box: FGA − OREB + TOV + 0.44·FTA, averaged both teams).
  `rating_paths(games, ...) -> {tid: [{"date","game","net","se"}]}` (Kalman). `preseason_prior(league, season, roster_impact=None)`.
- `game.py`: `predict(home, away, date, ctx) -> {"p_home","margin","sd","total","spread_fair","detail":{rest,travel,altitude,injury,...}}`; `sigma(league)`.
- `season_sim.py`: `simulate(league, season, n=20000, seed=0, state=None) -> {"teams": {tid: {"exp_w","exp_l","w_p05","w_p95","seed_dist":[...],"p_playoffs","p_playin","p_top6","p_conf","p_title","p_lottery_pick":[...]|null,"magic","eliminated","clinched"}}, "bracket": {...}, "n_sims"}`
  with a `config.py` holding per-league/season format (conferences, divisions, games, play-in, series lengths, tiebreak order, lottery odds table).
  `magic`, `tragic`, `clinched`, `eliminated` are dicts keyed by target (NBA `top6`, `postseason` (top 10), `division`, `top_seed`;
  WNBA `postseason` (top 8), `top_seed`). Each team also carries `conference`, `division`, `current` {w,l,conf_w,conf_l,div_w,div_l,pd,remaining,rank,gb},
  `rating`, `rating_se`, `p_div` (NBA), `p_reach` {round: p}, `win_dist` [P(W = k)], `next` {game,date,opp,home,p_win,if_win,if_loss} | null.
  `p_conf` = reached the Finals (WNBA: a finalist). Standings count stype `reg` only (`cup` is the Cup final, which does not count).
- `elo.py`: game Elo 1997→ with MOV multiplier, HCA, season regression; `history(league)`, `ratings_before(history, date)`.
- `backtest.py`: walk-forward game and season scoring vs Elo, DraftKings spread (`odds.spread_home` → p via `sigma`), ESPN predictor if present.

Builder C
- `shots.py`: `fit_xpts(shots) -> model`; `xpts(model, shots) -> array`; per-player/team shot-making, shot diet, calibration table.
- `impact.py`: `rapm(stints, players=None, ridge=None, prior=None) -> {pid: {"o","d","t","poss","se","se_o","se_d","poss_o","poss_d"}}`
  (`rapm_fit` adds ridge/hca/cv meta; `poss` counts both ends);
  `box_impact_fit(box_rates | [per season], rapm | [per season])` / `box_impact(box_rates, model)`; `hpm(box, rapm, model)`;
  `projections(games, asof, players, hpm_values)`; `roster_impact(team_players, minutes, league)` for B's preseason prior / injuries.
- `winprob.py`: `fit_wp(states) -> model`; `wp(model, state)`; `wpa(game, pbp, model, events=None, league) -> per-play WPA and per-player totals`
  (`pbp` = compact_pbp, `events` = A's `parse` output for exact possession); excitement / comeback indices.
- `awards.py`: race models for MVP, ROY, DPOY, 6MOY, MIP, Clutch -> `races(table, models, team_wins) -> {award: {pid: p}}`;
  `team_wins` = B's season_sim `{tid: {"exp_w","w_p05","w_p95"}}`.

## 4. Markets (builder B): `oddsmarkets/basketball/sources/markets.py`
On the `f1/sources/markets.py` template using `oddsmarkets.common.prediction_markets` and `common.markets.devig`:
`futures(league, season) -> {"champion": TITLE, "conference": {...}, "mvp": TITLE, "roy": ..., "dpoy": ..., "win_totals": {tid: {"line","p_over"}}, ...}`;
`game_prices(league, date) -> {game_id: {"p_home", "sources": [...]}}`. TITLE as in F1 (`available, prices, sources, by_source, eliminated, implied_total`).
As built: TITLE's fair prices are under `probs` (F1's key), `sources` is the list of source names and `by_source` {source: {id: mid}};
futures keys `champion`, `conference` {East, West}, `cup`, `mvp`, `roy`, `dpoy`, `sixth`, `clutch` (TITLE), `playoffs` / `playin`
({"probs": {tid: p}} per-team yes/no, not de-vigged), `win_totals` {tid: {line, p_over, ladder {N: P(W >= N)}, ticker}}.
`game_prices` rows also carry `home`, `away`, `spread_home`, `total`, `basis` (prediction_markets | draftkings_ml | draftkings_spread).
