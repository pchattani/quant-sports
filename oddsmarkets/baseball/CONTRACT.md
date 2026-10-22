# The Quant Bullpen: data and model contract

Levels: `"mlb"` and `"aaa"`. Seasons are calendar years. Ids: players `pid` = MLBAM id as string (`key_mlbam`);
Retrosheet-only players `"r:<retroid>"`; teams = MLBAM team id; games `gpk` = MLBAM gamePk. Dependencies: numpy, scipy,
pandas, requests, pyarrow, lightgbm. No network in tests. Data root env `BULLPEN_DATA` (default `docs/bullpen/data`),
raw root `BULLPEN_RAW` (default `data/baseball`), cache `BULLPEN_CACHE` (default `data/baseball/cache`).

## 1. Data (builder A)

### Pitch table (Parquet, git-ignored): `<raw>/statcast/<level>/<season>.parquet`
Savant CSV column names kept as-is (game_pk, game_date, game_type, at_bat_number, pitch_number, pitcher, batter, stand,
p_throws, home_team, away_team, inning, inning_topbot, outs_when_up, balls, strikes, on_1b/2b/3b, pitch_type, pitch_name,
release_speed, effective_speed, release_spin_rate, spin_axis, release_extension, release_pos_x/y/z, arm_angle, pfx_x, pfx_z,
plate_x, plate_z, sz_top, sz_bot, zone, vx0, vy0, vz0, ax, ay, az, api_break_z_with_gravity, api_break_x_arm,
api_break_x_batter_in, description, type, events, bb_type, launch_speed, launch_angle, hit_distance_sc, hc_x, hc_y,
launch_speed_angle, estimated_ba_using_speedangle, estimated_woba_using_speedangle, estimated_slg_using_speedangle,
woba_value, woba_denom, babip_value, iso_value, delta_run_exp, delta_pitcher_run_exp, delta_home_win_exp, home_win_exp,
bat_score, fld_score, post_bat_score, fielder_2..fielder_9, if_fielding_alignment, of_fielding_alignment, umpire,
bat_speed, swing_length, attack_angle, attack_direction, swing_path_tilt, intercept_ball_minus_batter_pos_x_inches,
intercept_ball_minus_batter_pos_y_inches, hyper_speed, n_thruorder_pitcher, pitcher_days_since_prev_game, …).
Types: categorical strings as pandas category, floats float32, ids int32. Missing columns for early seasons are present as null.
Plus `<raw>/statcast/<level>/<season>.manifest.json` {days fetched, rows per day, capped days re-split}.

### Stores (committed for completed seasons): `docs/bullpen/data/<level>/<season>/store.json`
```
{"level","season","updated_at",
 "teams": {tid: {"name","abbr","short","league":"AL|NL","division","venue": vid,"colour"}},
 "venues": {vid: {"name","city","lat","lon","elev_ft","roof","dims": {"lf","lcf","cf","rcf","rf"},"walls": {...}|null}},
 "players": {pid: {"name","short","bats","throws","pos","dob","debut","retro","bbref","fg"}},
 "games": {gpk: GAME},
 "meta": {...}}
```
GAME = `{"gpk","date","gtype":"R|F|D|L|W|C|S|E","series": {"desc","game","of"}|null,"home","away","hs","as","status","venue",
"weather": {"temp","wind","cond"}|null,"umpire_hp": pid|null,"probables": {"home","away"},"lineups": {tid: [pid…]}|null,
"innings","lines": {"ml":[home,away],"rl":{...},"total":{...},"open":{...},"close":{...},"books":[...]}|null,
"abs": {"home":{...},"away":{...}}|null,"has_statcast": bool}`

Pre-game timestamps (from 22 October 2026, written by `store.merge_game` while a game is still "pre"; hourly
resolution): `"lineups_at": {tid: ISO time the current posted lineup was first seen}` and
`"probables_log": [[ISO time, home pid, away pid], ...]` (one row per change of the listed probables). Past games have
neither; their earliest archived pre-game lineups and probables come from the timecoded live feed
(scripts/mlb_lineup_snapshots.py, cache only).

### Retrosheet (git-ignored raw; compact PA table): `<raw>/retro/pa/<season>.parquet`
one row per event — plate appearances (`pa` = True) and the running events between them (`pa` = False: sb, cs, po,
poe, wp, pb, bk, di, oa, foul_err), so runs reconcile with the game logs: game_id, date, season, gtype (R|F|D|L|W),
home, away (Retrosheet team codes; `canon.tid_from_retro`), park, inning, half (0 top, 1 bottom), seq, bat_team, outs_pre,
bases_pre (bitmask 1 = first, 2 = second, 4 = third), run1_pre/run2_pre/run3_pre (runner ids), away_score_pre,
home_score_pre, balls, strikes, pitches, event_tx (raw play string), event_cd (out, k, bb, ibb, hbp, int, e, fc, 1b, 2b,
3b, hr, plus the running codes), pa, ab, hit (0-4), err, runs_on_play, outs_on_play, outs_post, bases_post (0 once
three are out), batter, pitcher (retro ids), bat_hand, pit_hand (switch hitters resolved against the pitcher), fielded_by,
hit_loc, bb_type (G|L|F|P|BG|BP...), sh, sf. Event files exist 1908-2025 (1901-1907 have box scores only, so game logs
but no events); regular season and postseason in one file per season. Plus `<raw>/retro/games/<season>.parquet` (game
logs 1901->, with a matching game_id) and `<raw>/retro/validation.json` (runs and hits per team v the game logs).
`retrosheet.NOTICE` holds the required notice text.

### Crosswalk: `docs/bullpen/data/people.json` (committed) — `{pid: {"name","retro","bbref","fg","birth","debut","last"}}`
from the Chadwick register (ODC-BY; attribution string `chadwick.ATTRIBUTION`).

### Sources (`oddsmarkets/baseball/sources/`): `savant.py` (day-chunked CSV, 25,000-row re-split, leaderboards),
`statsapi.py` (schedule, live feed, standings, rosters, IL, transactions, people, weather, umpires, ABS),
`retrosheet.py` (download + parser), `chadwick.py`, `lahman.py`, `espn.py` (lines incl. open/close, ESPN WP),
`markets.py` (builder D). Each is a paced client that never raises.

### Implementation notes (builder A, 1 Oct 2026)
- Pitch table: Triple-A is the same search with `minors=true&hfLevel=AAA|` (2023->). One Parquet part per day in
  `<raw>/statcast/<level>/<season>.parts/`, compacted (streamed, one row group per day) into `<season>.parquet`.
  `savant.load_season(level, season, columns=None, filters=None)` is the reader: game_date datetime64; game_pk,
  at_bat_number, pitch_number, pitcher, batter, inning, balls, strikes, outs_when_up, game_year int32; the other id/count
  columns (on_1b/2b/3b, fielder_2..9, zone, scores, ...) nullable Int32; `des` string. Manifest:
  {"days": {date: {"rows","games","at"}}, "capped": [[lo, hi, team, rows]], "rows", "columns_present", "compacted_at"}.
  `savant.leaderboard(client|None, name, season)` reads the cached validation leaderboards.
- GAME extra keys: "start" (UTC ISO), "gnum", "scheduled_innings", "decisions" {"w","l","s"}, "espn" (event id),
  "mound_visits" {"home","away"}. "date" is the official (local) date; "status" pre|live|final|postponed|cancelled|suspended;
  "innings" [[away, home], ...]; "abs" {"home"|"away": {"won","lost","left"}}; "lines" {"src","ml":[home,away],
  "rl":{"home": point, "price":[home,away]},"total":{"line","over","under"},"open","close" (same shape, 2023->),
  "books":[{"id","name","ml","rl","total"}],"consensus"}; the run-line sign follows the moneyline favourite (ESPN's own
  signs are flipped in many pre-2026 payloads). Postseason placeholder teams ("NL Higher Seed") carry "placeholder": true.
- Store extras: top-level "umpires" {pid: {"name"}}; venue "state","azimuth","turf","capacity"; AAA teams "parent","city";
  meta "standings" {tid: {"w","l","div_rank","lg_rank","wc_rank","gb","wc_gb","rs","ra","clinched"}} and "rosters"
  {tid: {"40man": [pid], "injured": [[pid, status, note]]}} (current season), "crosswalk" counts.
- people.json "birth" is YYYY-MM-DD (or a year), "debut"/"last" are first/last MLB seasons (years).
- Concurrent writers use `store.save_owned(store, phases)` (lock file + merge of the fields each phase owns).

## 2. Models (`oddsmarkets/baseball/models/`)
Common: pure functions on DataFrames + cached `for_season(level, season)`; committed fits in `models/fitted/` (versioned)
used when the cache is empty (CI). Memory: process pitch tables by season/chunk; never hold all seasons at once.

Builder B (pitch): `physics.py` (trajectory from 9 params → VAA, HAA, IVB, HB, decision-point positions, spin efficiency
proxy), `stuff.py`, `location.py`, `pitching.py` (stuff+location+sequence, scaled 100 = league average),
`tunneling.py`, `swing.py` (swing probability, swing/take run values, decision value), `battrack.py` (adjusted bat speed,
squared-up v expected, swing-path fit).

Builder C (batted ball and value): `xwoba.py` (xwOBA+ with spray, park, sprint speed; also Savant comparison),
`catchprob.py` (catch probability, fielding runs), `framing.py` (called-strike model, framing runs) and `umpire.py`
(accuracy, consistency, scorecards, ABS), `re24.py` (run and win expectancy, linear weights, wOBA weights by season,
1908→ from Retrosheet play-by-play), `parks.py`, `war.py` (Bullpen WAR, historical via Retrosheet), `history.py`.

Builder D (prediction): `projections.py` (component projections, aging, AAA translations), `game_sim.py` (PA Monte Carlo
→ win, run line, total, F5), `live.py`, `season_sim.py` (regular season + postseason bracket), `awards.py`,
`backtest.py` (v ESPN closing lines; xwOBA+ v Savant xwOBA predictive test; stuff validity; projection error),
`sources/markets.py` (Kalshi KXMLB*, Polymarket tag mlb).

## 3. NPB (level `npb`, added 13 October 2026)

`oddsmarkets/baseball/npb/` is self-contained and shares only `store.Lock`, `store.read_json/write_json`, `sources/_client.py`
and `analytics` helpers with the MLB code. Ids: teams `91001`-`91017` (`npb/canon.py`), players `n<NPB id>`, games
`YYYYMMDD-<home code>-<away code>`. Stores (`npb/store.py`): `docs/bullpen/data/npb/<S>/store.json` = `{"level": "npb",
"season", "updated_at", "teams" {tid: canon.team_record}, "games" {gpk: GAME}, "stats" {"bat", "pit": {pid or pid@tid: row}},
"names_en" {pid: "Surname, Given"}, "meta" {days, boxes, stats_at, js_dates, kalshi_futures}}`; GAME = `{gpk, date, gtype
"R"|"C1"|"C2"|"J", league "CL"|"PL"|null, interleague, home, away, home_code, away_code, hs, as, status
"pre"|"live"|"final"|"postponed"|"cancelled", venue (Japanese), start "HH:MM" (Japan), meeting, series {key, league, game},
bis (2005-25 box id) | scores (/scores/ path, 2026 on), innings [[away, home]], rhe, decisions {w, l, s}, hr, att, dur, box
{bat, pit: {away, home: rows}}, box_final, probables, kalshi {home, away, at, ticker}}`. `stores/history.json` = `{"yearly" {S:
{CL, PL: source.parse_yearly}}, "js" {S: source.parse_js_results row}}`; `stores/rosters.json` = `{S: {tid: [[pid, jp, jp
with space, debut, ...]]}}`; `stores/people.json` = `{pid: source.parse_player}`; `stores/model_params.json` = the backtest's
chosen parameters. Writers lock and merge (`npb/store.save`, `update_json`). No network in tests (recorded pages in
`tests/baseball/fixtures/npb/`).

### Play-by-play store (added 15 October 2026): `data/baseball/npb/pbp/<S>.json.gz` (git-ignored, 2016 on)

`{gpk: {"v": PARSE_VERSION, "pa": [[inning, half (0 top, 1 bottom), outs, bases (bit mask 1/2/4), batter pid, pitcher pid,
balls, strikes (the count before the last pitch), result text]], "ev": [[inning, half, outs, bases, runner pid, text, index of
the plate appearance it follows]], "np": {pid: pitches}, "names": {pid: name as printed}}}`, written by
`scripts/npb_fetch.py --phases pbp` (`npb/pbp.py`: `parse_playbyplay`, `parse_box_pitches`, `fill_starters`), rebuilt
offline from the page cache with `--reparse`. Read by `npb/lab.season_tables` (cached under
`<cache>/npb/pbp_tables_<S>_<key>.pkl`) and by `npb/build.season_players` (the play-by-play's printed names give the NPB id of
stat-page rows the rosters cannot name).

## 4. Value and trade (added 15 October 2026)

`analytics/value.py` (rows, positions, projections, the value payload, team needs), `analytics/trade.py` (the depth-chart
allocation, rosters, sensitivity curves), `analytics/value_build.py` (MLB and Triple-A; called by `build_bullpen.build_level`),
`npb/valuebuild.py` (NPB; called by `npb/build.build_level`, also writes the NPB lab). A value ROW is `{pid, name, team, kind
"H"|"P", pos (primary: C..DH, SP, RP), pos_g {pos: games (hitters) | share (pitchers)}, g, n (PA or BF), war, rate (per 600 PA /
700 BF), pos_runs, comps [[label, value]], stat {label: value}, age}`. Caches under `<cache>/value/`: `posgames_<L>_<S>_<key>.json`
(position games from the pitch table's fielders), `rows_<L>_<S>_<key>.json`, `proj_<L>_<key>.json` (k, aging), `aging_mlb.json`
(the MLB aging curve that Triple-A and NPB reuse), `curves_<L>_<S>.json` (sensitivity curves: reused while their inputs are
unchanged and for up to six hours after they change).

## 5. Valuation v2, transactions, trade ratings, fantasy (added 16 October 2026)

`analytics/mlbapi.py` (cached Stats API inputs: transactions by month, official season and weekly stat lines for MLB and the
minor-league levels aaa/aa/hia/a, people the crosswalk lacks; `BULLPEN_OFFLINE` or `--no-statsapi` reads the cache only),
`analytics/moves.py` (parsing, injured-list stints, trades), `analytics/valuation.py` (horizons, bands, availability,
scarcity, prospects, club splits), `analytics/trade_ratings.py` (value at a date, realised, retention, base rates, grades,
validation), `analytics/moves_build.py` (the shared context and the moves/trades payloads), `analytics/fantasy.py` (lines,
values) and `analytics/fantasy_build.py` (projections, backtests, payloads). Caches: `<cache>/statsapi/` (tx/<L>/<YYYY-MM>.json,
lines/<L>/season_<group>_<S>.json and range_<group>_<from>_<to>.json, people.json), `<cache>/value/stints_<L>_<S>_<mtime>.parquet`
(PA and wOBA by player, club and date), `<cache>/value/trade_validation.json`, `<cache>/fantasy/` (rest-of-season
projections by date, backtests by season). Build flags: `--no-moves`, `--no-fantasy`, `--no-statsapi`.
