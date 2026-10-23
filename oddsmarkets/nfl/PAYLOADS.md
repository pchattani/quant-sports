# The Quant Gridiron: payload and front-end contract

Everything `scripts/build_gridiron.py` writes under `docs/gridiron/data/` and the site reads. Contract between the Python
builder (D) and the front-end builders (E, F). Probabilities 4 dp; EPA 3 dp. Ids: `game_id` (nflverse), `pid` (gsis_id),
team abbreviations. Season `S`. A payload that cannot be built is `{"ok": false, "reason"}`. Wrapped shapes are allowed when
documented under "As built" at the end. Fractions are 0–1. Spreads: every spread is the home team's betting line, negative
when the home team is favoured (`line.spread_home`, `market.spread`, `model.spread`); `model.spread = −model.margin`, where
`margin` is the expected home-minus-away points.

## Site-wide
- `data/index.json`: `{"updated_at","season","week","phase":"preseason|regular|playoffs|offseason","games":[GAME_CARD] (this week),
  "live":[GAME_CARD],"recent":[GAME_CARD],"standings_top": {...},"playoff_odds": {team: {"p_playoffs","p_div","p_bye","p_sb"}},
  "leaders": {metric: [[pid, value]] x10},"gaps": [ {"game_id"|"market","model","market","edge"} ],"teams": {abbr: {"name","colour","alt","division","conference"}}}`
  GAME_CARD = `{"game_id","week","gtype","kickoff","home","away","hs","as","status","qtr","clock","possession","down","dist","yl100",
   "model":{"p_home","spread","total"},"market":{"p_home","spread","total","sources"}|null,"line":{"spread_home","total","ml_home","ml_away","open","close"}|null,
   "wp_home": live|null,"qbs":{"home","away"},"weather":{...}|null}`
- `data/players_index.json` `{pid: [name, team, pos, first_season, last_season]}`
- `data/glossary.json`, `data/calibration.json`, `data/history.json` (1999→ leaders, era-adjusted), `data/coaches.json`
  (decision grades by coach and season), `data/referees.json`.

## Per season — `data/<S>/`
- `season.json`: standings by division (W-L-T, PF, PA, point diff, our rating, SOS, remaining SOS), sim odds per team
  (p_playoffs, p_div, p_bye, p_conf, p_sb, seed_dist, win_dist, magic/elim), draft order odds, playoff bracket with odds,
  team ratings by unit with history (week by week).
- `schedule.json`: `{"games":[GAME_CARD]}` all weeks.
- `weeks/<week>.json`: the week's games with model v market v line and key matchups.
- `games/<game_id>.json` (current and previous season): pre-game (model: win, spread, total, score distribution; market; line
  open/close; injuries and QB status; weather; unit matchups), live/final (score by quarter, drives with result and EPA, plays
  `{"cols":[qtr, clock, team, down, dist, yl100, type, desc, epa, wpa, wp_home_ours, wp_home_espn, ep_before, ep_after, players], "rows"}`,
  win-probability chart data, every 4th down with recommendation and WP lost, box score with advanced stats and NGS, key plays, awards).
- `teams.json`: per team unit ratings and history, tendencies (PROE by situation, play action, RPO, motion, personnel, formation,
  pace), 4th-down aggressiveness, schedule v model, QB situation, roster value.
- `players.json`: catalogue by position group (QB, RB, WR, TE, K, P, DEF) `{"metrics":[METRIC],"players":{pid:{"name","team","pos",
  "group","age","games","qualified","values":{key},"pct":{key},"pct_pos":{key}}}}`, METRIC = `{key,label,group,fmt,lower,scope,desc,stabilises_at}`.
- `fourth_downs.json`: every 4th down of the season with situation, choice, recommendation, WP by option, WP lost; coach table.
- `leaders.json`, `lab.json` (column-oriented per position group), `awards.json`, `markets.json` (games, futures: SB, conference,
  divisions, playoffs, 1 seed, win totals, awards with edges).

## Per player — `data/players/<pid>.json` (career 1999→)
`{"id","name","pos","college","draft":{...},"seasons":[{season, team, games, …position stats…, epa, value}],
 "current": {"season","log":[...per game...],"charts":{qb: depth/location grid, receivers: depth profile, rb: RYOE by game},
 "ngs": {...}, "ftn": {...}, "projection": {...}}, "similar": [...]}`

## Front-end contract (`docs/gridiron/`)
Copy the Bullpen shell (`docs/bullpen/index.html`, `assets/js/{core,charts,fx}.js`, css) as `window.GI`: season picker, week
picker, search over players_index.json, nav (Hub, Week, Standings, Playoffs, Teams, Players, Fourth downs, Coaches, Leaders,
History, Lab, Compare, Markets, Calibration, Glossary, Methodology). Name "The Quant Gridiron", tagline "Odds, models and
analytics for the NFL". Sister group: Footballer, Paddock, Hardwood, Ace, Bullpen. Charts: drive chart (field 0–100 with drives
as bars), WP chart (ours v ESPN, 4th-down markers coloured by decision grade), field-position heatmaps, pass depth/location grids,
Savant-style percentile sliders. Routes: `#/`, `#/week/<S>/<w>`, `#/game/<game_id>`, `#/standings/<S>`, `#/playoffs/<S>`,
`#/team/<abbr>`, `#/teams`, `#/player/<pid>`, `#/players`, `#/fourth-downs`, `#/coaches`, `#/coach/<name>`, `#/leaders`,
`#/history`, `#/lab`, `#/compare/<a>/<b>`, `#/markets`, `#/calibration`, `#/glossary`, `#/methodology`, `#/disclaimer`.
Disclaimer: no affiliation with the NFL, teams, players, ESPN or bookmakers; no logos; data from nflverse (CC-BY 4.0) with
credit; "FTN Data via nflverse" (CC-BY-SA 4.0; derived charting data shared alike); NFL Next Gen Stats credited, informational
non-commercial use; 18+ where gambling is discussed. First-visit notice key `qg-notice-v1`.

## As built (builder D, 1 Oct 2026)

Deviations and detail beyond the contract above. Every payload carries `ok`, `season` (per season) and `updated_at`;
a payload that failed is `{"ok": false, "reason", "season"}` in its place.

**Conventions.** Spreads: see the header (home line, negative = home favoured; `model.spread = −margin`). Percentiles
(`pct`, `pct_pos`): 0–100, 100 = best (reversed for `lower` metrics), placed after stabilisation shrinkage; a metric
below its sample floor has no percentile. `stabilises_at` is in the metric's `unit` (dropbacks, att, carries, targets,
rec, fga, punts, games).

**GAME_CARD** adds `overtime`, `div_game`; live cards add `wp_home_espn`, `wp_source`. `model` =
`{p_home, spread, total, margin, home_pts?, away_pts?, source?}` (`source`: absent = the current game model; `"frozen"` =
the last pre-game price kept in the manifest; `"walk_forward"` = builder C's walk-forward price, for games before this
build). `market` = prediction markets only (the Kalshi / Polymarket mean: `{p_home, spread: null, total: null,
sources}`); the bookmaker line is `line` = `{spread_home, total, ml_home, ml_away, open, close, provider}` (open / close as
the store keeps them). `qbs` = `{home: {id, name, status}, away: {...}}`. `weather` = `{temp, wind, roof, surface, desc}`.

**index.json** also has `seasons` (on disk), `models` (model versions and fit keys) and `sim_reason`.
`standings_top` = `{AFC|NFC: [[team, w, l, t, seed], ...x7]}` (today's seeds by the tiebreakers). `leaders` keys are
`<group>_<metric>` (`qb_composite`, `qb_epa_db`, `qb_cpoe`, `rb_rush_epa`, `rb_ryoe`, `wr_rec_epa`, `te_rec_epa`,
`def_sacks`, `k_fg_oe`). `gaps`: game rows `{game_id, model, market, edge}` (probabilities; edge = model − market);
futures rows `{name: "sb: KC", model, market, edge}` (the futures label is `name`; `market` is always a probability).

**games/<game_id>.json** = `{ok, game_id, season, updated_at, card (GAME_CARD), game {stadium (id), stadium_id,
stadium_name, roof, surface, temp, wind, referee, home_coach, away_coach, home_rest, away_rest, div_game, overtime,
espn_id, date, neutral}, pregame, matchups, injuries, espn_predictor, credits, score, drives, plays, wp, fourth_downs,
box, key_plays, awards, source}`.
- `pregame` = `{model: PRICE, source, market, market_detail (C's per-game record: sources, spread / total ladders, book),
  line, priced_at, qbs, weather}`; PRICE = `{p_home, p_tie, spread, margin, total, home_pts, away_pts, sigma, sigma_total,
  net_h?, net_a?, source, dist}`; `dist` = `{margin: {lo, p[]} (P(margin = lo + i), with the key numbers), total: {lo, p[]},
  margin_sd, total_sd, cover {home, push, away} v the line, over {over, push, under}, drive_sim {p_home, p_tie, p_away,
  mean_margin, mean_total, sd_margin, sd_total, pts_h, pts_a, p_ot, margin_pmf {m: p}, total_q {q: pts}, team_q {home|away:
  {q: pts}}, cover, over, n}}`. `drive_sim` is present for games priced this run; past games carry the analytic pmfs.
- `score` = `{home: [points by quarter, OT appended], away: [...]}`.
- `drives` = `{cols: [n, team, qtr, clock, start_yl100, end_yl100, plays, yards, result, epa, top, first_downs, wp_start,
  wp_end], rows}`; the start is the first snap (kickoffs and tries excluded); a touchdown drive ends at 0.
- `plays` = `{cols: the PAYLOADS cols + [play_id, game_seconds, wp_home_nflfastr, success, home_score, away_score], rows}`;
  `epa` / `ep_before` / `ep_after` are ours when builder B's EP scores the season (nflfastR's otherwise); `wpa` likewise.
- `wp` = `{cols: [game_seconds_remaining, wp_home_ours, wp_home_nflfastr, wp_home_espn, play_index], rows}`; for a game known
  only from the ESPN live record: `{cols: [seq, wp_home_ours, wp_home_espn], rows, source}` plus `espn_plays`.
- `fourth_downs` = `[{play_id, qtr, clock, team, dist, yl100, score_diff, choice (go|punt|fg), rec, wp: {go, punt, fg},
  p_convert, wp_lost, grade, result, desc}]`; `grade` from the WP lost against the best option: A <= 0.5 pp, B <= 1.5,
  C <= 3, D <= 6, F beyond (null when builder B's fourth-down model did not score the play).
- `box` = `{home|away: {passing: [{pid, name, cmp, att, yds, td, int, sacks, epa, epa_db, cpoe, adot, ttt}], rushing: [{pid,
  name, car, yds, td, epa, success, ryoe}], receiving: [{pid, name, tgt, rec, yds, td, epa, air, yac, yacoe, sep}], defense:
  [{pid, name, tkl, sacks, int, pd, hits, tfl, ff}], team: {plays, yards, epa, epa_play, success, pass_epa, rush_epa,
  third_down: [conv, att], turnovers, penalties, penalty_yds, proe}}}` (ttt, sep and NGS ryoe from the NGS week rows).
- `key_plays` = the top 8 by |WPA|: `[{play_id, qtr, clock, team, desc, wpa, epa, wp_home_before, wp_home_after}]`;
  `awards` = `{home_ball: {pid, name, epa}, away_ball, play_of_game}`.
- `matchups` = `{home_off|away_off: {pass: {off, off_rank, def, def_rank}, rush: {...}, proe, pace}, rating: {home, away},
  st: {home, away}}` (EPA per play; rank 1 = best). `injuries` = `{home: [{pid, name, pos, status, practice, injury}],
  away, source}` (the nflverse weekly report; ESPN's list for upcoming games).

**season.json** = `{standings: [{division, conference, teams: [ROW]}], sos_units, seeds_today: {AFC|NFC: {seeds,
division_winners, order}}, sim: {ok, n, reason, teams: {abbr: SIM}}, draft: [DRAFT], bracket, ratings: {abbr: {values,
history, source}}, ratings_history_cols: [week, net, off, def], model_errors}`.
ROW = `{team, name, colour, w, l, t, pct, pf, pa, diff, home|away|div|conf: [w, l, t], streak, last5, rating, sos, sos_left,
games_left, sos_pct, seed_today}` plus, when the simulation ran, `{p_playoffs, p_div, p_bye, p_conf, p_sb, p_1seed,
p_wildcard, mean_wins, w_p05, w_p95, p_first_pick, mean_pick, seed_dist[7], win_dist[18], magic, tragic, clinched,
eliminated, next_game, p_reach {DIV, CON, SB}}`. `sos` / `sos_left` = the mean rating (points per game against an average
team) of the opponents played / still to play; `sos_pct` = the opponents' combined win percentage (the NFL's SOS).
`magic`, `tragic`, `clinched`, `eliminated` are builder C's dicts (division, #1 seed, playoffs). `next_game` = `{game_id,
week, opp, home, p_win, if_win: {p_playoffs, p_div, p_bye, p_conf, p_sb}, if_loss}`.
DRAFT = `{team, w, l, t, pct, sos_pct, in_playoffs_today, mean_pick, p_first_pick, p_top5, p_top10, pick_dist, pick_today,
source ("simulation" | "record")}`. `bracket` = `{rounds: [{key (WC|DIV|CON|SB), name, games: [GAME_CARD]}], seeds_today,
sim: {sb_matchups: [{afc, nfc, p}], format}, odds: {abbr: {p_playoffs, p_bye, p_conf, p_sb}}}`.

**teams.json** = `{metrics: [METRIC], teams: {abbr: {abbr, name, short, division, conference, colour, alt, franchise, values,
rank, pct, record, units {source, model (C's units), epa_ppg}, history [[week, net, off, def]], history_cols,
history_source, personnel [{group, share, epa, pass_rate, n}], formation [...], qbs [{pid, name, dropbacks, games, epa_db,
composite, started_last}], roster_value, sim, schedule}}, ratings_source, ratings_units, plays_per_team_game}`. `rank`: 1 =
best; style metrics (scope "style") rank high to low and have no `pct`.

**players.json** = `{metrics, groups: {QB|RB|WR|TE|K|P|DEF: [metric keys]}, players: {pid: {name, team, pos, group, age,
games, qualified, values, pct, pct_pos}}, reference, composite_source, model_metrics, qualification, credits}`. METRIC.scope
lists the groups it applies to ("QB", "RB WR TE", ...); METRIC.group is the metric's category; `unit` is added. WR and TE
share one reference pool (`pct`); `pct_pos` is within WR or TE, and within DL / LB / DB for defence. `composite` is on the
100 + 10 z scale; `composite_epa` is builder B's forecast of EPA per dropback.

**weeks/<w>.json** = `{week, gtypes, games: [GAME_CARD + edges {model_v_market, model_v_line, spread_v_line, total_v_line,
p_home_line} + matchup]}`. **schedule.json** = `{games: [GAME_CARD]}`.

**fourth_downs.json** = `{cols: [game_id, week, gtype, qtr, clock, team, opp, coach, dist, yl100, score_diff, wp, choice,
rec, wp_go, wp_punt, wp_fg, p_convert, wp_lost, go_exp, result, play_id, grade], rows, coaches: [{coach, team, n, go, go_rate,
go_exp, goe, n_rec_go, go_when_rec_go, agree, wp_lost, wp_lost_per}], league, model, model_note}`. GOE = go rate minus a
league logistic model's expected rate in the same situations, fitted per season. **coaches.json** = `{season, current:
[{name, team, n, go_rate, goe, go_when_rec_go, agree, wp_lost}], coaches: {name: {seasons: [...], teams, career, record {w,
l, t, post_w, post_l}}}}`. **referees.json** (site-wide) = `{season, current: [REF], league: {season: penalties_pg},
referees: {name: {seasons: [{season, ...REF}], career}}}`, REF = `{referee, games, penalties_pg, yards_pg, home_share,
vs_league, top_calls [[type, n]], home_record [w, l, t]}`; also per season at `data/<S>/referees.json`.

**leaders.json** = `{cols: [pid, name, team, value], players: {group: {metric: [[pid, name, team, value] x10]}}, teams:
{metric: [[team, value] x32]}, headline, metrics}`. **lab.json** = `{groups: {group: {cols: [pid, name, team, pos, age,
games, qualified, ...keys, ...pct_<key>], rows}}, teams: {cols, rows}, metrics, team_metrics}`.

**awards.json** = `{source ("model" | "ranking"), awards: {mvp|opoy|dpoy|oroy|droy|cpoy|coty: {name, candidates: [{pid,
name, team, pos, p_model, p_market, edge}], winner {name, team, pos} | null}}, share_played?}`. `model`: builder C's award
logit (current season); `ranking`: candidates by our value metrics, no probabilities; winners from C's verified table.

**markets.json** = `{games: [{game_id, week, home, away, kickoff, model, market, line, edge}], futures: {sb, conf_afc,
conf_nfc, seed1_afc, seed1_nfc, div_<afc_east ...>, playoffs: [{team, market, model, edge}]}, win_totals: {abbr: {mean_wins,
win_dist, kalshi|polymarket: {line, p_over, model_over, edge, ladder}}}, awards: {award: [{name, team, model, market,
edge}]}, fetched, futures_error, generated_at, sources, notice}`. Futures and game edges are model − market; the awards
rows are C's compare_markets, whose edge is model / market − 1.

**players/<pid>.json** = `{id, name, pos, group, college, draft {year, round, pick, team} | null (null before the 2008 draft: earlier slots are Pro Football Reference's), dob, height, weight, seasons:
[{season, team, group, games, qualified, age, ...group stats, plus {metric: 100 + 10 z}, epa, value}], current: {season,
log [{game_id, week, team, opp, p_* / r_* / x_* stats}], charts {qb_grid [{depth, loc, att, cmp_pct, epa, td, int}],
depth_profile [{depth, tgt, catch, epa, yds}], ryoe_by_game [[week, ryoe]]}, ngs, ftn, projection (null), values, pct,
pct_pos} | null, similar: [[pid, name, team, similarity]]}`. Files exist for players with a season of volume (QB 20 att,
RB 10 carries, WR 8 / TE 6 targets, K 3 FGA, P 10 punts, DEF 10 tackles) or a current block.

**history.json** = `{seasons, season_cols: [pid, name, season, team, value, plus], season_leaders: {<group>_<metric>: {label,
group, key, rows}}, career_cols: [pid, name, first, last, seasons, total], career_leaders: {...}, league: [{season, games,
ppg, home_win, epa_play, pass_epa, rush_epa, pass_rate, success, go_rate, fg_pct, sack_rate, int_rate, penalties_pg,
adot}], era_note, season_floor, coverage}`. Single-season boards need a full season's volume (`season_floor`).

**calibration.json**: builder C's backtest payload passed through when `models/backtest.py` provides one; until then the
existing file is kept, else `{"ok": false, "reason"}`.

**Per season**: `data/<S>/manifest.json` (input signatures, frozen pre-game prices, page signatures, model errors, timings).

## As built: value, strengths and needs, trade (15 Oct 2026; docs/VALUE_SECTIONS.md)

Built by `analytics/value.py` from the season's catalogue (`players.json`), the player-value model (`player_value`), the
team-strength model (QB values), the latest nflverse weekly roster and depth chart, and the season simulation's
sensitivity curves (`season_sim.sensitivity`, through `adapters.season_sensitivity`, cached on the simulation's inputs
under `<cache>/analytics/sensitivity/`). The currency is **points (EPA) above a replacement-level player at the same
position** (GVAR); see `docs/nfl/MODELS.md` section 8.4.

**`<S>/value.json`** (every season with a catalogue) = `{ok, season, updated_at, version, phase, team_games, current,
basis_season, positions: [QB, RB, WR, TE, EDGE, DL, LB, CB, S, K, P], labels {pos: name}, cols, rows, best {pos: [pid x10]},
why {pos: [component keys]}, replacement {pos: {role | per_fga | per_punt | per_game: rate}, _league: {...}}, repl_q, notes
{currency, ol, defence, trend}, credits}`. `cols` = `[pid, name, team, pos, age, games, opp, gv, gvar, gvar_pg, pct, trend,
q, why]`: `opp` the sample (plays for QB/RB/WR/TE, FGA, punts, games for defenders), `gv` the raw currency (Gridiron Value;
K points over expected; P punting EPA over the league's mean punt; defenders Splash EPA), `gvar` value above replacement,
`gvar_pg` per game, `pct` percentile of `gvar_pg` among qualified players at the position (null below the catalogue's sample
floor), `trend` = this season's `gv` per game minus last season's, `q` 1 = qualified, `why` the position's components in
`why[pos]` order (QB: pass, rush (GVAR by role), epa_db, cpoe, composite; RB: rush, rec, ryoe, ypc; WR/TE: rec, yacoe, croe,
target_share; K: fg_oe, fg_50, fg_pct; P: net, inside20, net_oe; EDGE/DL: sacks, qb_hits, tfl, ff; LB: tfl, sacks, pd, ints;
CB/S: pd, ints, ff, tfl). Rows: players with a value and at least 5 opportunities (defenders 2 games), by `gvar`. `team` is
the current roster team in the current season (null = released), else the last team played for. `basis_season` < `season`
when the season has not started (last season's values on this season's rosters). About 100–150 KB a season.

**`<S>/needs/<abbr>.json`** (current season) = `{ok, season, team, updated_at, basis_season, label, units: [UNIT],
positions: [POS], strengths: [ITEM x<=3], weaknesses: [ITEM x<=3], improve: [IMPROVE], ol {starters [[pid, pos]], note},
k_resp, remaining, contracts {enabled, note}, grades [[cut, letter]]}`. UNIT = `{key (qb | pass_off | rush_off |
protection | pass_def | rush_def | pass_rush | st), label, value, fmt, pct, grade, stat, positions, lower}` (protection and
pass rush fall back to sacks per dropback when the pressure model has no participation data, i.e. in-season). POS = `{pos,
label, value (points a game above replacement among the starters; QB: the model QB term x dropbacks a game), pct, grade,
players [[pid, name, gvar_pg, qbv]], ir [[pid, name]], basis}`. ITEM = `{kind (unit | pos), key, label, pct, grade, value,
fmt, evidence, positions}`. IMPROVE = `{key, label, positions, candidates: [CAND x<=5], unsigned: [CAND x<=3]}` or `{key,
label, candidates: [], unsigned: [], note}` when no position can be traded for (pass protection). CAND = `{pid, name, team,
pos, age, gain_pg (points a game, k_resp x the gain in position value), gain_rest (x games left), d_wins, d_playoffs (from
the team's sensitivity curve), seller_cost_pg, gvar_pg, hints [text], last_season (unsigned), cap_hit?, years_left?}`.
About 9 KB a team.

**`<S>/trade.json`** (current season) = `{ok, season, updated_at, version, phase, basis_season, cols, players, slots {pos:
starters}, positions, labels, qb {abbr: {starter, val, depth [pid]}}, qb_new, np, k_resp, sens {ok, grid [-10..10], keys
[p_playoffs, p_div, p_bye, p_conf, p_sb, mean_wins, mean_pick], teams {abbr: {key: [value per grid point], ess: [...]}}, n,
reason}, baseline {abbr: {p_playoffs, p_div, p_bye, p_conf, p_sb, mean_wins, mean_pick, rating, remaining, record [w, l, t]}},
cap (null unless contracts are enabled: {season_cap, teams {abbr: $M}, credit, note}), contracts {enabled, note}, label}`.
`cols` = `[pid, name, team, pos, age, games, gvar, gvar_pg, qbv, status, cap_hit, years_left]` for every player on a
current roster (ACT, INA, RES) at a modelled position, plus depth-chart QBs without a sample (their model QB value). The
curves are monotone in the shift and equal the published odds at 0. About 125 KB.

Contracts (`analytics/contracts.py`): `cap_hit`, `years_left`, the cap totals and the cap check are filled only with
`build_gridiron.py --contracts` or `GRIDIRON_CONTRACTS=1`, which should not be set until OverTheCap allows its data to be
republished (its terms forbid it on websites without consent; the nflverse `contracts` release is OverTheCap's data). The
release is fetched only by name (`nfl_fetch.py --releases contracts`).


## As built: valuation v2, transactions and trade ratings, fantasy (16 Oct 2026; docs/VALUE_SECTIONS.md §4–5)

Built by `scripts/build_gridiron.py` for the full current season only (`value_pages` → `valuation_payload`,
`transactions_pages`; `fantasy_pages`). `--no-transactions` and `--no-fantasy` skip them; `--no-market` also stops the
ESPN transactions fetch (the cached copy is used).

**`<S>/valuation.json`** (`analytics/valuation.py`) = `{ok, season, updated_at, version "valuation-2", horizon 3, discount 0.9,
k_resp, wins_per_point, np, qb_new, qb_carry, cols, rows, curves {pos: {b, k, sd1, sd2, drift, n, mean, ret [[age lo, age
hi, p_play_next, games_share]], ageing [[age, delta per game]]}}, scarcity {pos: {marginal, top5, starters, spread, index}},
pick_curve {ok, picks [value of overall pick 1..262], rounds {r: mean}, a, b, c, n, drafts [first, last], seasons, discount,
means [[bin centre, mean, n]], note}, seasons [S..S+3], notes {value, qb, salary, availability}, credits}`.
`cols` = `[pid, name, team, pos, age, status, lvl (current level, points a game above replacement), r (shrinkage weight;
null for QB-model levels), proj [level per season S..S+3], games [expected games per season], value (discounted points),
lo, hi (10th/90th percentile), wins, over_ms (next season's level above the position's marginal starter), now_pg (this
season's value per game), src (gvar | qb)]`, every player on a current roster with a value history and unsigned players
with value (status `FA`), sorted by value. About 220 KB.

**`<S>/transactions.json`** (`analytics/transactions.py`) = `{ok, season, updated_at, version, window [from, to], k_resp,
wins_per_point, grades [[cut, letter]], trades [TRADE], table [CLUB], best [[date, team, from, wins_now, grade_now,
wins_at]] x10, worst [...], feed_cols [date, team, type, text, players], feed [[...]] (trades, signings, releases, claims,
extensions; newest 400; players [[pid|null, name, pos, model value now|null]]), counts {type: n}, n_feed, pick_curve {ok,
rounds, n, drafts, note}, notes {source, left_out, method, parse}, credits}`. TRADE = `{date, teams [A, B], winner (abbr |
"even" | null), notes [club notes], sides [{team, gets [ASSET], in_at, in_now, real, exp_so_far, net_at, net_now, wins_at,
wins_now, grade_at, grade_now}]}`; ASSET = `{kind "player", pid, name, pos, at, now, real, exp, games, valued, why,
on_roster}` | `{kind "pick", year, round, overall, conditional, at, now, valued}` | `{kind "considerations"}`. CLUB = `{team,
trades, net_at, net_now, wins_at, wins_now, real, signed, lost, n_signed, n_lost}`. About 130 KB.

**`<S>/ledgers/<abbr>.json`** = `{ok, season, team, updated_at, window, summary CLUB, trades [TRADE], feed_cols [date, type,
text, players], feed [[...]] (every move of the club in the window), credits}`. 10–40 KB a club.

Raw cache: `<cache>/espn/transactions/<year>.json` = `{year, fetched_at, n, rows [{date, text, team, team_name}]}`
(refetched after 6 hours for the current calendar year, a week for the previous one).

**`<S>/fantasy.json`** (`analytics/fantasy_model.build`) = `{ok, season, week (the week to come), last_week, updated_at,
version, cols, rows, k {abbr: TEAMPROJ}, dst {abbr: TEAMPROJ}, sos {abbr: {pos: [rest of season, next four]}}, picks {start,
waiver, buy_low, sell_high, breakout: [{pid, pos, score, why}], dst, k: [{team, proj, opp, why}]}, waiver_n, start_n, sd
{pos: [c0, c1]}, params, backtest (the fitted summary), tune_seasons, scoring, notes {left_out, waiver, injuries}, credits}`.
`cols` = `[pid, name, team, pos, status, inj, opp, home, imp, opp_f, ppr, half, std, floor, ceil (PPR 10th/90th), tgt, rec,
rec_yds, rec_td, car, rush_yds, rush_td, att, pass_yds, pass_td, ints (this week's projected line), ros_ppr, ros_half,
ros_std, ros_g, next4 [[week, opp, ppr]], sos, sos4, g, pts_ppr, pts_half, pts_std, xfp (expected PPR points from usage; null
for QBs), td, xtd, rec_yds_s, xrec_yds_s, rush_yds_s, xrush_yds_s, tgt_sh, tgt_sh3, car_sh, car_sh3, rz_sh, rz_sh3,
air_sh, ppg_last]`. TEAMPROJ = `{weeks [[week, opp, proj]] (next four), ros, next}`. About 200 KB.

**`fantasy_backtest.json`** (site-wide) = `{ok, updated_at, version, fitted_at, tune_seasons, eval_seasons, grid [[HL, ALPHA,
PRIOR_G, MAE]], params, sd, backtest {seasons, formats {ppr|half|std: {QB|RB|WR|TE|ALL: {n, model|season_to_date|last_season:
{mae, mae_played, rho, rho_played, n}}}}, k, dst {n, model|season_to_date|last_season: {mae, rho}}, by_season {S: {pos: {model,
season_to_date, last_season, rho, rho_std}}}, n_weeks, band_coverage}, current {season, weeks, ppr} (this season so far),
credits}`. The fitted part is `oddsmarkets/nfl/models/fitted/fantasy.json` (written by `scripts/nfl_fantasy_fit.py`).
Frames cache: `<cache>/analytics/fantasy/pw_<S>_<sig>.parquet`, `tw_<S>_<sig>.parquet`.

## Movement (`data/<S>/movement.json`, the current season; added 22 October 2026)

Written once a day by `scripts/build_gridiron.py` `movement_page` from `analytics/movement.py` on the shared engine
(`oddsmarkets/common/movement.py` `payload()`); method and validation in `docs/research/moves_model.md` and
`docs/research/moves_gridiron.md`. About 260 KB (2,000 rostered players).

`{ok, level "nfl", season, version, engine, phase "inseason", snapshot (date), horizons {deadline, deadline_estimated,
next, snapshot_week}, deadline_label "traded or claimed", unit "points", team_horizon "next", types [trade, release,
other], type_labels, published {next, deadline, type, arrivals, targets}, reasons {block: text}, base_rates {next,
deadline, types {type: share}}, base_arrivals {pos: [p_add, mean]}, base_arrivals_fields, player_fields, players
[[pid, name, team, pos, age, yrs, value, p_next, p_trade, p_release, p_other, p_dl, why]], team_fields {outlook,
targets}, teams {abbr: {wp, status, traj, exp_departures, exp_arrivals, outlook [[pos, p_add, exp_arrivals, need,
exp_departures, players]], targets [[pid, name, team, pos, age, value, gain, p_move, p_join, why]]}}, status_cuts,
drivers {next, deadline: [[feature, coefficient per SD]]}, validation {next, deadline, type, arrivals: {test, dev, l2},
targets: {k, test, dev}}, split {dev, test}, notes, updated_at}`.

A block that failed its pre-registered test carries `null` probabilities / empty lists and a `reasons` entry; on
22 Oct 2026 `next` and `deadline` are published, the type split shows the base shares, arrivals and targets are
not published. `p_<type>` sum to `p_next`. Positions are the value page's plus OL and LS (never targets: not valued).

## Metrics-spec fields (23 Oct 2026; docs/METRICS_SPEC.md, docs/_design/metrics/nfl.json)

- `players.json` rows: `role` (QB, RB, WR, TE, K, P; defenders EDGE = outside pass rushers, display code "ED", DL =
  interior, LB, CB, S by value.json's `def_position` rule, so the two files agree) and `pct_role` {metric: 0-100} against
  the qualified players of the same role (same shrinkage, floors and direction as `pct`). Catalogue `roles`
  {role: {label, short, group, n, qualified}} and `role_rule`.
- DEF `values`: `sacks_pg`, `tfl_pg`, `tackles_pg`, `pd_pg`, `ints_pg`, `ff_pg` (per game with a credited stat, k 6) and
  `def_snaps` (participation, 2016-2025). DEF `qualified`: half the team's games with a credited stat, plus 300 defensive
  snaps over 17 games where participation exists (the old tackles-equivalent rule qualified 48% of snap-regular interior
  linemen; 2024: DL 48 -> 101, EDGE 66 -> 97).
- K `values.fg_oe_att`: field goals over expected per attempt (the percentile basis; `fg_oe` stays the season total).
- P `values.net_oe`: sign fixed (higher = better; it ran r -0.95 with net average before).
- `players/<pid>.json`: `current.role`, `current.pct_role`, `current.peer` {role, label, short, group, n, minimum,
  spec_group}; `seasons[].role`; `similar` [[pid, name, team, similarity 0-100]] by the spec recipe
  (oddsmarkets/common/similar.py: the role's features with gvar_pg from value.json, z within role and season, weights
  = year-to-year r floored at 0.2, k 5; similarity = 100 exp(-distance)).
