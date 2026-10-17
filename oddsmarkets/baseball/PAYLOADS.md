# The Quant Bullpen: payload and front-end contract

Everything `scripts/build_bullpen.py` writes under `docs/bullpen/data/` and the site reads. Contract between the Python
builder (E) and the front-end builders (F, G). Probabilities 4 dp; rates 3 dp; "plus" scores integers (100 = average).
Ids: `pid` MLBAM string, `tid` MLBAM team id, `gpk` gamePk. Level `L` = `mlb` | `aaa`; season `S`. A payload that can't
be built is `{"ok": false, "reason"}`. Wrapped shapes (`{"ok", ..., "<key>": {...}}`) are allowed; document them under
"As built" at the end of this file. Fractions (fmt pct/prob) are 0–1.

## Site-wide
- `data/index.json`: `{"updated_at","season","phase":"preseason|regular|postseason|offseason","today":[GAME_CARD],"recent":[GAME_CARD],
  "upcoming":[GAME_CARD],"postseason": {"round","series":[SERIES]}|null,"leaders": {metric: [[pid, value]] x10},"teams": {tid: {...}},
  "levels": {"mlb": {...}, "aaa": {...}}}`
  GAME_CARD = `{"gpk","date","start","status","gtype","series","home","away","hs","as","inning","probables":{"home","away"},
   "model":{"p_home","total","rl_home"},"market":{"p_home","sources"}|null,"line":{"ml","total","rl"}|null,"wp_home":live|null}`
  SERIES = `{"id","round","teams":[tid,tid],"wins":[a,b],"best_of","p":[pa,pb],"market":[...]|null,"games":[gpk...]}`
- `data/players_index.json` `{pid: [name, team, pos, bats, throws, active_levels]}` (search)
- `data/glossary.json` (groups with key,label,desc,fmt,lower,scope,stabilises_at), `data/methodology` text lives in docs.js.
- `data/people.json` (crosswalk; committed by builder A).

## Per level and season — `data/<L>/<S>/`
- `season.json`: standings by division with W-L, run diff, pythag, expected W-L from our ratings, playoff/division/bye/WS odds
  (sim), magic numbers; team ratings (offence/defence/pitching runs per game); postseason bracket with series odds.
- `schedule.json`: `{"games": [GAME_CARD]}` (whole season).
- `hitters.json` / `pitchers.json`: catalogues `{"metrics":[METRIC], "players": {pid: {"name","team","pos","age","pa"|"bf","qualified",
  "values":{key},"pct":{key},"pct_role":{key}}}}` with METRIC = `{"key","label","group","fmt","lower","scope","desc","stabilises_at"}`;
  pitchers also `"arsenal": {pid: {pitch_type: {...per-pitch metrics...}}}` (or per player file).
- `teams.json`: team catalogue (~80 metrics) + `{"log": [...], "roster": [...], "park": vid}` per team.
- `games/<gpk>.json` (current and previous season): pre-game model v market v ESPN line (win, run line, total, F5 distributions),
  lineups with matchup projections, weather/park/umpire; live/final: linescore, `pitches` (columns: inning, half, ab, pitch_no,
  batter, pitcher, pitch_type, velo, spin, ivb, hb, plate_x, plate_z, sz_top, sz_bot, call, desc, stuff, location, launch_speed,
  launch_angle, xwoba_plus, xwoba_savant, hc_x, hc_y, event, re24, wpa), win-probability series (ours and ESPN's), umpire scorecard
  (missed calls with run-expectancy cost, favoured team), ABS challenges, box score with expected stats, pitcher arsenals v their norm.
- `umpires.json`: per umpire accuracy, consistency, expected v actual, run impact, ABS; `parks.json`: our park factors by
  handedness/batted-ball type, dimensions, weather effects.
- `leaders.json`: top-N per metric (pre-filtered by sample).
- `lab.json`: column-oriented `{"fields","metrics","rows","kinds":["hitter","pitcher"]}` per season window.
- `awards.json`: per award {model: {pid: p}, market, features}.
- `prospects.json` (aaa): AAA players with MLB translations and call-up previews.
- `calibration.json` (per level `data/<L>/calibration.json`): backtest v ESPN closing lines, xwOBA+ v Savant xwOBA predictive test,
  stuff validity, framing/OAA v Savant, projection error, reliability bins.
- `markets.json`: futures (WS, pennants, awards) and game/series prices with edges.

## Per player — `data/players/<pid>.json` (career, all levels)
`{"id","name","bats","throws","pos","dob","debut","ids":{"retro","bbref","fg"},"seasons":[{level,season,team,…traditional…,
 xwoba_plus, xwoba_savant, war, …}], "history": Retrosheet-era seasons (pre-2015) with linear-weights value,
 "current": {"season","hitting": {...}, "pitching": {...}, "spray": grid/points with xwOBA+, "zones": {pitch_type: grid},
 "decisions": swing/take value grid, "battrack": {...}, "arsenal": {...}, "movement": points, "release": {...}, "tunnels": [...],
 "fatigue": {...}, "rolling": [[date, xwoba_plus, woba]], "splits": {...}, "projection": {...}}, "similar": [...]}`

## Front-end contract (`docs/bullpen/`)
Copy the Hardwood/Ace shell (`docs/ace/index.html`, `assets/js/{core,charts,fx}.js`, css) as `window.BP`: level switch
(MLB | AAA), season picker, search, nav (Hub, Games, Standings, Postseason, Hitters, Pitchers, Teams, Leaders, Umpires, Parks,
Prospects, History, Awards, Lab, Compare, Markets, Calibration, Glossary, Methodology). Name "The Quant Bullpen", tagline
"Odds, pitch models and analytics for Major League Baseball" (no comparative claims against other sites or trademarks in the
site copy). Sister group: Footballer, Paddock, Hardwood, Ace. Charts: strike zone (catcher's view, plate 17 in,
sz_top/sz_bot), spray chart (field outline from park dims), movement plot (IVB × HB, arm-angle line), Savant-style percentile
sliders, zone heatmaps. Routes: `#/`, `#/<L>/game/<gpk>`, `#/<L>/games[/<date>]`, `#/<L>/standings`, `#/postseason`,
`#/<L>/hitter/<pid>`, `#/<L>/pitcher/<pid>` (or `#/player/<pid>` with tabs), `#/<L>/hitters`, `#/<L>/pitchers`, `#/<L>/team/<tid>`,
`#/<L>/teams`, `#/<L>/leaders`, `#/umpires`, `#/umpire/<id>`, `#/parks`, `#/park/<vid>`, `#/prospects`, `#/history`, `#/awards`,
`#/<L>/lab`, `#/compare/<a>/<b>`, `#/markets`, `#/calibration`, `#/glossary`, `#/methodology`, `#/disclaimer`.
Disclaimer: no affiliation with MLB, MLBAM, teams, players, ESPN or bookmakers; no logos; Retrosheet notice verbatim
("The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact
Retrosheet at "www.retrosheet.org"."); Chadwick register ODC-BY attribution; Lahman CC BY-SA; MLBAM data shown for non-commercial,
informational use; 18+ where gambling is discussed. First-visit notice key `qb-notice-v1`.

## As built (builder E, 1 Oct 2026)

Writer: `scripts/build_bullpen.py` with `oddsmarkets/baseball/analytics/*`. Every payload is wrapped: `{"ok": true, "level",
"season", "updated_at", ...}`; catalogues also carry `"phase"`, `"team_games"` and `"model_errors"` ({model: reason} for every
builder B/C/D model that was not available, so the page can say why a column is empty). A payload that could not be built is
`{"ok": false, "reason", "level", "season"}`. Values are rounded per `fmt` (pct/prob are fractions; "plus" integers; "war" 1 dp).

### Files (additions and placements)
- Site: `index.json`, `glossary.json`, `players_index.json`, `players/<pid>.json` (careers are site-wide, not per level),
  `assets/base.css` (copy of the football site's style.css).
- Per level: `data/<L>/history.json` (MLB; see below), `data/<L>/calibration.json` (builder D's backtest; E merges `checks.xwoba`,
  `checks.oaa`, `checks.framing`; an `{"ok": false}` placeholder until the first backtest).
- Per level and season: `hitters.json`, `pitchers.json`, **`fielders.json`** (new), `teams.json`, `season.json`, `schedule.json`,
  `umpires.json`, `parks.json`, `leaders.json`, `lab.json` (per season), `awards.json` (MLB), `prospects.json` (AAA),
  `markets.json` (MLB, current season, only when markets were fetched), `games/<gpk>.json` (the two most recent seasons),
  `manifest.json` (build bookkeeping: input signature, frozen pre-game prices, page signatures, model errors, timings).

### Catalogues (hitters / pitchers / fielders)
- METRIC also has `"unit"`: the sample the metric is measured on (`pa`, `bip`, `pitches`, `swings`, `bat_swings`, `oz`, `iz`,
  `pa_l`, `pa_r`, `bf`, `bf_l`, `bf_r`, `chances`, `called`, `fb`/`br`/`os` pitches of that family, `v95`/`v90`/`vlo`,
  `heart`/`shadow`/`chase`/`waste`, `tto3`); `stabilises_at` is in that unit (builder C's n_0.7; fixed published k where C has no fit).
- `players[pid]` = `{"name","team" (tid of his latest team),"team_abbr","pos","age" (on 30 June),"pa"|"bf","qualified","values",
  "pct","pct_role","n": {unit: sample}}`; hitters add `"bats"`, pitchers `"throws","role" ("SP"|"RP"),"primary"` (primary
  fastball type). `pos` = primary position from WAR's games by position (C, 1B, 2B, 3B, SS, LF, CF, RF, DH), else the roster's.
- Percentiles: `pct` against the reference pool (hitters with 2.1 PA per team game, pitchers 1.25 BF per team game), `pct_role`
  against the position group (C, 1B, 2B, 3B, SS, CF, LF/RF, DH) or role (SP/RP), min 5 in the group. A key is absent when the
  player is under the metric's sample floor (`floors`); counting stats (fmt int) have no percentile. The value placed is shrunk
  toward the pool mean with the metric's stabilisation k; displayed values are raw. Payload extras: `"reference": {rule, n,
  min_pa|min_bf, means}`, `"floors"`, `"roles"`.
- Hitters: 175 metrics, pitchers 150 (keys and descriptions in glossary.json). Both WAR flavours: hitters `war` (regressed:
  batting from park-neutral xwOBA+) and `war_results` (results-based batting runs); pitchers `war` (RA9, results) and `war_x`
  (xwOBA+, regressed). Labels are neutral: "xwOBA+ (ours)" next to "xwOBA (Savant)".
- Pitchers: `"arsenal": {pid: {pitch_type: {n, usage, velo, spin, ivb, hb, vaa, haa, ext, rel_z, rel_side, arm_angle, spin_eff,
  axis_meas, axis_move, axis_dev, ssw, plate_speed, spread_in, stuff, location, pitching, xrv100, rv100, whiff, csw, chase, zone,
  xwoba, hard, usage_vl, usage_vr, usage_ahead, usage_behind, usage_two, d_velo, d_ivb, d_hb, stuff_pct, whiff_pct_type}}}`
  (types with 10+ pitches; `d_*` against his primary fastball; `stuff_pct` / `whiff_pct_type` = percentile among the league's
  pitches of the same type with 100+ thrown), `"arsenal_keys"`, `"league_types": {pt: {n, usage, whiff, csw, xwoba, stuff, velo,
  ivb, hb, spin, vaa}}`, `"constants": {lg_ra9, c_fip, lg_hr_fb}`. No earned runs exist in the pitch data: `r` / `ra9` are all runs
  scored while he pitched; FIP is on the RA9 scale.
- **HB is arm-side positive for both hands** everywhere (arsenal, game pitches, movement points); IVB in inches.
- `fielders.json`: `{"metrics","players": {pid: {name, team, pos, values, pct, pct_role, n}}, "validation": {season, oaa: {ok, n,
  min_chances, r_oaa, r_runs}, framing: {ok, n, min_called, r_runs, r_rate}}, "validation_model"}` (our OAA / framing against
  Savant's leaderboards for the same season).

### teams.json
`{"metrics","teams": {tid: {id, name, abbr, short, league, division, colour, venue, values, pct, park (vid),
"log": [[gpk, date, gtype, opp_tid, home 1/0, runs_for, runs_against, "W"|"L"|status, model_p_win, market_p_win]],
"roster": [{pid, name, pos, kind "hitter"|"pitcher"|"40man", pa|ip, war, woba|ra9, xwoba_plus|stuff_plus, injured}],
"bullpen": [{pid, name, throws, available 1|0.5|0, pitches_3d, rest (days), bf_30d}] (current season only, else null),
"defence": {"if": {alignment: share}, "of": {...}, "if_by_stand": {"L"|"R": {...}}, "of_by_stand": {...}}}}, "constants"}`.
Ratings (`values.off_rpg/def_rpg/pit_rpg/rating`) are runs per game above an average team.

### season.json
`{"standings": {division: [{tid, name, abbr, short, league, division, w, l, pct, gb, rs, ra, rd, pythag_w, exp_w, exp_pct, rating,
off, def, pit, seed, div_winner, clinched, streak, last10, + simulation odds: p_division, p_wildcard, p_bye, p_postseason, p_ds,
p_lcs, p_pennant, p_ws, proj_w, w_p05, w_p95, magic, next, seed_dist (regular season) or p_postseason/p_ds/.../p_ws (postseason)}]},
"ratings": {tid: {off, def, pit, total}}, "league_rpg", "sim": {available, basis "game_model"|"ratings", reason, kind
"postseason"|"regular", sims, remaining_games}, "postseason": {round, series: [SERIES], seeds: {AL, NL}, teams: {tid: {seed, league,
p_ds, p_lcs, p_pennant, p_ws, next: {p_win, if_win: {p_ws}, if_loss: {p_ws}}, name}}, matrix: {teams, p}, sims} | null, "next_games"}`.
SERIES also has `round_name`, `p_sim` (simulation: the next game priced with its probables), `p_closed` (closed form on the pair
matrix), `done`, `market_sources`, and
`next: {home, away, p_home, gpk, date, start}`; `teams[0]` holds home field; `p` = `p_sim` for a live series, else `p_closed`.

### schedule.json and GAME_CARD
GAME_CARD as specified plus `"venue"`. `model` may carry `"source": "backtest"` (builder D's walk-forward price for games played
before the first build). `market`: prediction markets `{p_home, sources}` when fetched (today/tomorrow), else the de-vigged
DraftKings line from the store `{p_home, sources: ["draftkings_ml"], total, p_over}` (closing line for final games).

### index.json
`{"ok","updated_at","season","phase","today","recent","upcoming","postseason": {round, series, seeds, teams} | null,
"leaders": {"h_war"|"h_xwoba_plus"|"h_woba"|"h_hr"|"h_dv"|"h_bat_speed_adj"|"h_barrel_pct"|"h_sprint_speed"|"p_war"|"p_stuff_plus"|
"p_pitching_plus"|"p_k_pct"|"p_ra9"|"p_fb_velo"|"p_csw_pct"|"p_tunnel_index": [[pid, value]] x10 (reference pool)},
"teams": {tid: {name, abbr, short, league, division, colour, w, l, rating, p_postseason, p_ws}}, "levels": {L: {season, seasons,
phase, updated_at, teams, games, final, sim, has_pitches, model_errors}}}`. A run that does not build a level's current season
keeps that level's entry (and the hub blocks) from the previous index.

### games/<gpk>.json
Card fields plus: `teams {home, away}` (team_info), `weather`, `venue {id, name, city, roof, elev_ft, dims, azimuth, turf,
factors}` (park factors are **ratios keyed by event**: 1B, 2B, 3B, HR, woba_con, runs, K, BB; 1.00 neutral), `umpire_hp {id, name,
season {called, games, accuracy, x_accuracy, acc_above_x, consistency, zone_per100, runs_per_game}}`, `decisions`, `abs_summary`
(GAME.abs, may be null), `mound_visits`, `linescore` (GAME.innings `[[away, home], ...]`), `linescore_totals {home, away: {r, h, e}}`
(E counts Statcast `field_error` events only: a lower bound), `lines` (GAME.lines), `pregame {model (builder D's summary: p_home,
p_away, runline {home_-1.5, away_+1.5, away_-1.5, home_+1.5}, margin_dist, runs {home, away, total, total_sd}, total_dist,
total_median, over {line: p}, f5 {home, away, tie, total, over, home_-0.5, home_-1.5, away_-1.5}, extra_innings, inputs),
market, store_market, line, priced_at}` (priced every run until first pitch, then frozen on the page), `lineups {home|away:
{source "posted"|"projected", batters: [{slot, pid, name, pos, bats, matchup {woba, k, bb, hr, hand, unknown}}], opp_starter,
opp_starter_name}}`, `has_statcast`, and with pitch data: `pitches {cols, rows}`, `wp {ours: [[pa_index, inning, half, wp_home]]
(+ a final row at 1/0), ours_kind "model" (the game's own pre-game strengths: current season, games in play or just finished) |
"league" (league-average Markov model: the archive), espn: [[x, wp_home]] | null}` (**ESPN's x is the 0-1 fraction of its play
list**; ours is a PA index), `umpire {umpire, name, called, missed, accuracy, home_gain, away_gain, home_favour, favoured (tid or
null), total_impact, calls_cols, calls, season}`, `abs [{inning, half, ab, who, kind, result, batter, pitcher}]`, `box {batting:
{home, away: [{pid, name, pa, ab, h, hr, bb, so, hbp, tb, xwoba_plus, xwoba_savant, woba, ev_max, pitches, wpa}]}, pitching: {home,
away: [{pid, name, ip "6.1", outs, bf, h, r, bb, so, hr, pitches, strikes, whiffs, csw, velo_max, stuff, pitching, xwoba_plus,
xwoba_savant, wpa}]}, totals}` (no earned runs: R is runs while he pitched), `arsenal {pitcher: {pt: {n, velo, velo_max, ivb, hb,
spin, stuff, whiffs, csw, d_velo, d_ivb, d_hb, d_spin, d_stuff}}}` (`d_*` = that day minus his season norm), `wpa_leaders [{ab,
inning, batter, pitcher, wpa}]`. Without pitch data on the machine an existing page keeps its pitch-level blocks.
- Pitch columns: PAYLOADS' list plus `balls, strikes, outs, pitching`. **`call` is the pitch result** (Savant `description`, e.g.
  `called_strike`); **`desc` is the play text, on the last pitch of each PA only**; `event` and `wpa` (ours, batting side) are on
  the last pitch only; `xwoba_plus` on the PA's last pitch when the ball was in play; `re24` is Savant's `delta_run_exp` per pitch;
  `half` 0 = top, 1 = bottom; `stuff`/`location`/`pitching` are builder B's per-pitch scores.

### Other per-season payloads
- `umpires.json`: `{"metrics","umpires": {id: {name, values, pct, qualified, games_list}}, "games_cols": [gpk, date, home, away,
  called, missed, accuracy, x_accuracy, home_favour, favoured, impact], "league", "abs" (builder C's season ABS block), "min_called"}`.
- `parks.json`: `{"parks": {vid: {id, abbr, team, name, city, state, dims, walls, elev_ft, roof, turf, azimuth, capacity, lat, lon,
  factors (ratios), index (x100), by_hand {L, R}, n_bip, season {games, runs, runs_per_game}}}, "years", "dimension_effects",
  "weather_effects", "model_ok"}` (keyed by venue id).
- `leaders.json`: `{"hitters"|"pitchers": {key: [[pid, value, name, tid]] x25}, "teams": {key: [[tid, value]]}, "pitch_types": {pt:
  {stuff|pitching|whiff: [[pid, value, name, tid, n, velo]]}}, "hitters_min_pa", "pitchers_min_bf", "top"}`.
- `lab.json`: `{"fields": ["pid","name","team","pos","n"], "metrics": {"hitter": [METRIC], "pitcher": [METRIC]}, "rows": {"hitter":
  [[pid, name, tid, pos, n, v1, v2, ...]] (values in metrics order), "pitcher": [...]}, "kinds", "presets": [{kind, x, y, label}]}`
  (players with 50+ PA / BF).
- `awards.json`: `{"awards": {al_mvp|nl_mvp|al_cy|nl_cy|al_roy|nl_roy: {label, league, award, model {pid: p}, rows [{pid, name, p,
  value, team, features {feature: raw value}}], market, vs_market, features [names], fit, reason}}, "source", "verified_winners",
  "value_source"}`. Feature values are builder D's raw candidate features (MVP value, hr, team win%, woba; Cy value, k, ip, ra9
  as D defines it; ROY value, pa_ip).
- `markets.json`: `{"champion": {market (TITLE), rows [{id, model, market, edge}]}, "pennant": {AL, NL: same}, "awards": {key: same},
  "advance", "series": [{id, round, teams, wins, next {home, away, p_home, gpk, date, start}, model [pa, pb], market, edge}],
  "games": [{gpk, date, home, away, model, market, basis, sources, total, runline, f5, edge {home, away}}]}`.
- `prospects.json` (AAA): `{"players": {pid: {name, kind, team, parent, pos, age, aaa {...}, aaa_pct, mlb_eq {k_pct, bb_pct, hr_pa,
  xwobacon, gb_pct, woba, k_bb_pct}, n, mlb_proj {woba, rates, components, age} | null, mlb_this_season, rank}}, "ranked": {hitters,
  pitchers}, "translation", "woba_weights", "rules"}`.
- `calibration.json` additions: `checks.xwoba {seasons, labels, within {season: {n, woba|savant_xwoba|xwoba: {r, rmse, rmse_wtd}}},
  across, within_pooled, across_pooled}` (no verdict field: the page shows the numbers side by side), `checks.oaa {season: {...}}`,
  `checks.framing {season: {...}}`, `checks_updated_at`.

### history.json (`data/<L>/history.json`)
`{"meta": {"retrosheet_notice" (verbatim), "attribution": [Chadwick, Lahman]}, "seasons", "first", "last", "leaders": {bat_war,
bat_wraa, bat_hr, bat_h, bat_wrc_plus, pit_war, pit_k, pit_ra9_minus: {cols, rows} (builder C's career columns + "name"),
"all_war": {cols: [pid, name, war, war_bat, war_pit, first, last, pa, ip], rows}}, "era": [[season, pa, runs_per_pa, hr_pa,
k_pct, bb_pct, ra9]], "n_batters", "n_pitchers", "rules", "sources": {retrosheet, statcast}}`. Ids are MLBAM pids wherever
people.json maps the Retrosheet id; pre-MLBAM players keep `r:<retroid>` with their name. History starts in 1908.

### players/<pid>.json and players_index.json
- `players_index.json`: `{pid: [name, team tid, pos, bats, throws, [levels]]}`.
- Career file: as specified; `seasons` rows `{level, season, kind "hitter"|"pitcher", team, pos|role, ...}` with the keys in
  `analytics/careers.py` SEASON_KEYS_H / SEASON_KEYS_P (both WAR flavours); `history: {"batting": [[...]], "pitching": [[...]],
  "cols": {batting: [season, pa, ab, h, b2, b3, hr, bb, k, woba, wrc_plus, wraa, war], pitching: [season, games, outs, bf, runs, k,
  bb, hr, ra9, ra9_minus, war]}}` (Retrosheet-era seasons, before 2015) with `meta.retrosheet_notice`; `similar: [{pid, season, name,
  distance}]`.
- `current`: `{season, level, hitting|pitching: {values, pct, pct_role, n, qualified, pa|bf, team, pos|role, primary, age},
  spray: [[hc_x, hc_y, xwoba (ours, else Savant), ev, la, code 0 out|1 1B|2 2B|3 3B|4 HR|5 ROE]] (last 400), zones: {all|fb|br|os:
  5x5 [[n, swing, whiff, xwoba]]} (rows low -> high, columns catcher's view left -> right, inner 3x3 = the zone in thirds),
  decisions: 5x5 [[dv per 100 pitches, n]], battrack, rolling: [[date, xwoba_plus_100pa, woba_100pa]], arsenal, pitch_zones: {pt:
  5x5 [[n, whiff]]}, movement: [[pt, hb, ivb, velo]] (<= 300), release, tunnels: [{pair, n, dp, plate, tunnel, index, whiff}],
  fatigue, pitching_rolling: [[date, n, stuff, location, pitching, rolling_500]], splits: {batter|pitcher: {home, away, vL, vR:
  {pa, woba, k_pct}, months: {YYYY-MM: {...}}}}, projection: {kind, season, ...builder D's row} | null}`.

### glossary.json
`{"groups": [{"name": "<Kind>: <group>", "entries": [METRIC + unit + kind]}], "model": [{key, label, group, desc}], "notices":
{retrosheet, chadwick, lahman}}`.

## NPB (level `npb`, `oddsmarkets/baseball/npb/build.py`; added 13 October 2026)

Pages: `docs/bullpen/assets/js/npb.js` (registered with `BP.routeNpb`; they take over the route names while the level
is npb). Team ids `91001`-`91017` (numeric strings, our own; `npb/canon.py`), player ids `n<NPB 8-digit id>` (`nx<hash>`
for a stat-page name no roster maps), game ids `YYYYMMDD-<home code>-<away code>` (BIS letter codes; `-2` for a second
meeting on one day).

- `index.json` `levels.npb`: `{season, seasons, phase "preseason"|"regular"|"postseason"|"offseason", updated_at, teams {tid:
  {name, abbr, short, jp, league "CL"|"PL", division, colour, level}}, today, recent, upcoming: [CARD], leaders {bat_war, bat_hr,
  bat_wrc_plus, pit_war, pit_era, pit_so: [[pid, name, tid, value]]}, postseason {bracket, sim}}`.
- CARD: `{gpk, date, start (ISO, +09:00) | null, status, gtype "R"|"C1"|"C2"|"J", league, interleague, home, away, hs, as, venue
  (English, else Japanese), venue_jp, inn, level, series {key, game, desc} | absent, tie, model {p_home, p_tie, p_away, total,
  source "walk-forward"|"ratings"}, market {p_home, p_away, sources ["Kalshi"]}, dec {w, l, s} (names as printed)}`.
- `npb/<S>/season.json`: `{phase, standings {CL, PL: [{tid, rank, g, w, l, t, pct, lpct, gb, rs, ra, pyth, hw, hl, ht, aw, al, at,
  iw, il, it, lw, ll, lt, streak, h2h {tid: [w, l, t]}}]}, bracket {leagues {CL, PL: {seeds [t1, t2, t3], pennant, champion,
  stages [{key, high, low, games, need, adv, results ["W"|"L"|"T" from the higher seed], gpks, winner}]}}, js {cl, pl, results
  (from the Central club), gpks, winner, home_league}}, sim {teams {tid: {p_pennant, p_cs, p_final, p_js, p_champion, exp_w,
  exp_l}}, stages {"<lg>-<key>-<high>-<low>": P(high through)}, n} | null, ratings {tid: {off, def, net, rs9, ra9}} | null,
  ratings_track {tid: [[date, net]]} | null, kalshi_futures {p {tid: mid}, at} | null, teams, rules {max_innings, time_limited,
  schedule, dh {CL, PL}, tiebreakers, js_home_league}}`.
- `npb/<S>/schedule.json`: `{games: [CARD], js_dates}`.
- `npb/<S>/players.json`: `{bat: [{pid, name, jp, team, league, bats, g, pa, ab, r, h, d, t, hr, rbi, sb, cs, sh, sf, bb, ibb, hbp,
  so, gdp, avg, obp, slg, ops, iso, k_pct, bb_pct, woba, wrc_plus, bat_runs, br_runs, pos_runs, war, pos, pos_g {pos: box-score starts} (15 October 2026 on), pitcher}], pit: [{pid,
  name, jp, team, league, throws, g, w, l, sv, hld, cg, sho, bf, outs, h, hr, bb, ibb, hbp, so, wp, bk, r, er, ip, era, whip, k9,
  bb9, fip, ra9, k_pct, bb_pct, era_minus, fip_minus, war, role}], league {CL, PL: {woba_weights, woba_scale, lg_woba, r_pa, ra9,
  era, c_fip, rpw, lw, r_per_game}}, parks {tid: factor}, war_meta {pool, rep_per_pa, rep_per_ip, rpw}}`. A player traded during
  a season has one row per club. From 15 October 2026 a stat-page row the rosters could not name (an `nx` id) takes its NPB id from
  the play-by-play (2016 on) when exactly one player of that club and season has that printed name (`npb/lab.nx_remap`).
- `npb/<S>/teams.json`: `{teams {tid: {name, abbr, short, jp, league, colour, record (a standings row), results [[gpk, date, opp,
  home 1|0, rs, ra, status, gtype, model P(this club wins)]], park_factor, war_bat, war_pit, top_bat, top_pit, names [{from, to,
  name, jp}], rating {off, def, net} (current season)}}}`.
- `npb/<S>/games/<gpk>.json` (current season on the public site): `{card, innings [[away, home]] (null: did not bat), rhe {away,
  home: [R, H, E]}, att, dur (minutes), venue {jp, en}, teams {home, away}, hr [{mark, name, n, inning, runs, pitcher}], decisions
  {w|l|s: {name, pid, side}}, box {away, home: {bat [{name, pid, pos (Japanese marks), ab, r, h, rbi, sb, bb, hbp, so, d, t, hr,
  pa [results, 2026 on]}], pit [{name, pid, dec, outs, bf, np, h, hr, bb, hbp, so, r, er}]}}, model {p_home, p_tie, p_away,
  mu_home, mu_away, total, runs_home, runs_away (0-15), p_over {"5.5".."10.5"}, sp_home, sp_away, source}, kalshi {home, away, at,
  ticker}, rules {max_innings, dh}}`.
- `npb/history.json`: `{seasons [{season, leagues {CL, PL: {standings [{tid, jp, name, w, l, t, pct, gb, rs, ra, hr, era}],
  pennant, awards [{award, award_jp, jp, pid, name, team, value}], cs_winner, stages}}, js {winner, loser, wins, ties, games}}],
  franchises {tid: [{from, to, name, jp}]}, titles {tid: {js, pennants}}, leaders {h|hr|rbi|sb|w|sv|so: {label, rows [[pid,
  name, jp, total, first, last]]}}}` (1950 on).
- `npb/careers/<NN>.json` (NN = the last two digits of the pid): `{players {pid: {name, jp, kana, romanised, pos, bats, throws,
  born, ht, wt, draft, bat [{season, team, team_jp, g, pa, ab, r, h, d, t, hr, rbi, sb, cs, bb, hbp, so, sh, sf, gdp}], pit
  [{season, team, team_jp, g, w, l, sv, hld, outs, bf, h, hr, bb, hbp, so, r, er}]}}}`.
- `npb/names.json`: `{players {pid: [English, Japanese, last club, position, last season]}}` (read by the search box).
- `npb/calibration.json`: `{games {train, test {n, logloss, brier, base_logloss, base_brier, skill_logloss, acc, home_rate,
  tie_rate, tie_pred, total_mae, total_bias}, postseason_test, by_season {S: {... , max_innings}}, calibration [{lo, hi, n, pred,
  actual}], kalshi {n, model_logloss, kalshi_logloss, blend_logloss, model_brier, kalshi_brier, mean_abs_gap, corr, note} | null},
  params {rating, game}, tuning, notes}` (written by `npb/backtest.run`).
- Not deployed: `npb/<S>/store.json`, `npb/stores/*` (inputs; `scripts/local_sites.py` `prune_bullpen`).

## Value and trade (every level; added 15 October 2026)

Built by `analytics/value_build.py` (MLB, Triple-A) and `npb/valuebuild.py` (NPB); pages `assets/js/value.js`
(`#/<L>/value`, `#/<L>/trade`, and `BP.valueTeam` on the team pages). A payload is rewritten only when its content apart from
`updated_at` changed. Sizes from the local builds of 15 October 2026.

- `<L>/<S>/value.json` (every season with catalogues; MLB ~230 KB, NPB ~110 KB): `{ok, level, season, phase, currency "Bullpen
  WAR"|"WAR-lite", units {H: "WAR per 600 PA", P: "WAR per 700 BF"}, floors {H: PA, P: BF} (2.1 PA / 1.25 BF per team game),
  fields ["pid", "name", "team", "kind" "H"|"P", "pos", "elig" [positions], "age", "g", "n", "war", "rate", "pct" (percentile of
  WAR among players above the floor of the same kind; null below it), "war_prev" (last season), "proj" (next season's WAR),
  "why" (the components, text)], rows [[...]] (n >= 10), best {C..RP: [[pid, name, team, war, rate, pct within the position, n,
  age, why, stat line]] (top 10, primary position, half the floor)}, positions, projection {H, P: {k, k_by_target {S: k},
  validation {targets, rmse {projection, last_season, league_rate}, unit, min_n}, aging [c0, c1, c2], aging_source}} (current
  season only), notes}`.
- `<L>/<S>/value/<tid>.json` (current season; MLB ~18 KB each, NPB ~14 KB): `{ok, level, season, tid, team {name, abbr, short,
  league, division, colour}, grades [{pos, war (WAR at the position: each player's WAR split by his games there), pct, grade
  "A".."F" | null, players [[pid, name, share of his games, WAR there, games]], rank, of, incumbent_ft (projected wins over a full
  season there; pitchers: the fifth starter's / seventh reliever's slot), evidence, ungraded (NPB Central League DH, 2026)}],
  strengths [pos x3], weaknesses [pos x3 (+ "DH" for Central League clubs before 2027)], improve {pos: [{pid, name, team, pos,
  age, war, proj_ft, gain (wins over the incumbent), hints [text], n}] (top 5)}, label, free_agents, units {war, gain, slot {pa,
  sp, rp}}, roster (MLB, NPB) [{pid, name, kind, pos, ft {pos: projected wins over a full season there}, war, n, rate, proj (next
  season's WAR), proj3 (three seasons, aged), age}]}`.
- `<L>/<S>/trade.json` (current season, MLB ~15 KB, NPB ~7 KB): `{ok, level, season, teams {tid: {name, abbr, short, league,
  division, colour}}, horizon "rest"|"next", games_per_club, keys {p_post, p_div, p_title: label}, curves {tid: {exp_w [7],
  p_post [7], p_div [7], p_title [7]}} (sorted by expected wins), base {tid: {exp_w, p_post, p_div, p_title}}, sims, units {pa,
  sp, rp}, rpw, dh {tid: bool} (the horizon season's rule), order [positions], caps {C, SP, RP, other}, not_checked, notes}`.
  MLB: postseason / division / World Series; NPB: Climax Series (top three) / pennant / Japan Series champion.

## NPB lab (`npb/<S>/lab.json`, every season 2005 on; added 15 October 2026)

Built by `npb/lab.build` (from `npb/valuebuild.py`); read by `lab.js` and, for compare, `compare.js` (which turns its three kinds
into catalogues with percentiles in the browser). The shape of `analytics/leaders.lab`'s MLB file: `{ok, level "npb", season,
kinds ["hitter", "pitcher", "team"], fields ["pid", "name", "team", "pos", "n"], metrics {kind: [METRIC + "source" "stats"|
"pbp"]}, rows {kind: [[pid, name, team, pos (team rows: league), n (PA / BF / games), ...metric values]]}, presets [{kind, x, y,
label}], floors {hitter: 200, pitcher: 150, team: 1} (compare's percentile pool), n_label {hitter "PA", pitcher "BF", team "G"},
pbp {available, coverage {games_with_pbp, games_final}, re [24 run expectancies: outs x 8 + bases]} , expected {out_of_sample,
borrowed_from, validation {bat, pit: {n, seasons, corr_next {xbabip, babip}, rmse_next {xbabip, babip, league_mean}}}, coef {bat,
pit: {babip, hv: {coef [intercept, 8 features], mean, n}}}, features}, notes}`. Rows: hitters and pitchers with 10+ PA / BF (a
traded player's clubs summed; his club is the one with more), every club. Before 2016 only the stat pages' metrics are present
(`source: "stats"`): ~100 KB a season; with the play-by-play ~220 KB.

## Valuation v2, transactions, trade ratings and fantasy (MLB; added 16 October 2026)

Built by `analytics/value_build.py` (with `moves_build.py`) and `analytics/fantasy_build.py`; pages `value.js`, `moves.js`
(`#/mlb/moves`, and `BP.movesTeam` on MLB team pages), `fantasy.js` (`#/mlb/fantasy`). Models: MODELS.md sections 26-28.
Sizes from the local build of 16 October 2026.

- `mlb/<S>/value.json` (current season; 301 KB, was 207): `fields` gains `e1, lo1, hi1` (expected WAR next season and its 80%
  band), `e3, lo3, hi3` (three seasons), `v5` (five seasons, discounted 8% a year), `il3` [days on the injured list two
  seasons ago, last season, this season], `il_exp`, `il_p30` (next season's expected days, chance of 30+), `pos_line` (the
  median starter's projected full-season wins at his position), `over_line` (his minus that); `valuation {fields, discount,
  horizon, age_bands, horizon_fit {H, P: {band: {slope [5], n [5]}}}, band_fit {H, P: {"1", "3": {bin: [q10, q90, n]}},
  coverage}, il_fit {H, P: {coef, logit, mean, rate30, features, validation}}, positions {pos: {line, n, delta}},
  il_in_playing_time {H, P}, notes}`.
- `aaa/<S>/value.json` (current season; 308 KB): `fields` gains `p_level` (the level of the season's line: aaa, aa, hia, a),
  `p_z` (performance z), `p_value` (expected MLB WAR over four seasons, discounted); `prospects {model {H, P: {coef, scale,
  early_share, features, n, validation, mean, share_1war}}, notes}`.
- `mlb/moves.json` (574 KB): `{ok, level, updated_at, window [from, to], fields ["date", "kind", "pid", "from", "to", "detail"],
  rows [[...]] (newest first; kinds in `kinds`: trade, signing, recall, selected, option, outright, dfa, release, claim,
  free_agency, retired, suspension, purchase, rule5, il_place, il_transfer, il_activate, rehab), names {pid: name}, kinds
  {kind: label}, ledger {tid: {kind (trade_in, trade_out, ...): count}}, il_now [[pid, club, list, start, part, days]],
  il_fields, teams, source, notes}`. Minor-league contracts, assignments and number changes are left out; the API's text is
  never included.
- `mlb/trades.json` (151 KB): `{ok, level, updated_at, window, teams, trades [{id, date, teams, winner, r_winner, clubs {tid:
  {in, out, net, r_in, r_out, r_net, e2_net, grade, r_grade, extras}}, pieces [[pid, name, from, to, type "mlb"|"prospect"|
  "base", kind, age, service "0-2"|"3-5"|"6+"|null, value, rest, next, realised, detail]]}] (newest first), piece_fields,
  table {tid: {n, in, out, net, r_in, r_out, r_net, won, lost}}, grades, validation {span, pieces, nets: {n, r_model,
  r_naive, mae_model, mae_naive, slope, mean_expected, mean_realised, spearman_model, spearman_naive}}, retention {by
  {"<service>|<in|off|any>": [5 shares]}, n}, base_rates {age band: {value, e2, n, share_positive}}, prospect_model, discount,
  source, notes}`.
- `mlb/fantasy.json` (412 KB): `{ok, level, updated_at, season, target, phase, in_season, mode, h_fields, hitters [[...]],
  p_fields, pitchers [[...]], prospects [[pid, name, team, kind, pos, age, level, z, p_value, dyn, dyn_rank]], war_to_value,
  closers {tid: [[pid, sv, hld, era, so, sv_share, hld_share]]}, steals [[pid, sb, att, succ, sprint, pa, sb_last]],
  sb_upside, two_start, streaming [[pid, name, starts, games [[date, opponent, home?]], pts, so, era, w]], week_hitters,
  picks {sleepers, fades, young: [[kind, pid, our rank, last season's rank, reasons]]}, teams, points {H, P: {stat: weight}},
  league {teams, roster, pitchers, budget, replacement}, skills_fields, il_fields, fits, notes}`. Hitter fields: pid, name,
  team, elig (fantasy slots), age, pa, ab, h, b1, d, t, hr, r, rbi, sb, cs, bb, hbp, so, avg, pts, z_r, z_hr, z_rbi, z_sb,
  z_avg, val (z above replacement), usd, rank (overall), pos_rank, tier, dyn, dyn_rank, last [PA, R, HR, RBI, SB, AVG,
  points] (last season's official line), last_rank, skills [xwOBA+, wOBA, Savant xwOBA, barrel%, bat speed, sprint speed,
  K%, BABIP], il [expected days, chance of 30+, days last season, list now, body part], flags [reasons], slot, sb_att,
  sb_succ, sprint. Pitcher fields: pid, name, team, role, age, ip, outs, gs, g, w, l, sv, hld, so, h, bb, hbp, er, era, whip,
  pts, z_w, z_sv, z_so, z_era, z_whip, val, usd, rank, pos_rank, tier, dyn, dyn_rank, last [IP, W, SV, K, ERA, WHIP,
  points], last_rank, skills [Stuff+, Pitching+, RA9, xRA9, FIP, K%, CSW%, BABIP against], il, flags, sv_share, hld_share.
- `mlb/fantasy_backtest.json` (27 KB): `{ok, by_season {season {T: {H, P: {n, <cat>: {model, last}, points {model, last,
  rank_model, rank_last}, value_5x5 {rank_model, rank_last}}}}, ros {T: ...}, week {T: ...}}, summary {season, ros, week},
  luck {H, P: {n, slope, corr, gap}}, version, notes}`.
