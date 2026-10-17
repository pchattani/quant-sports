# The Quant Rink: payload and front-end contract

Everything `scripts/build_rink.py` writes under `docs/rink/data/` and the site reads. Contract between builder D and the
front-end builders E and F. Probabilities 4 dp; rates per 60 2 dp. Ids: NHL gameId, playerId, team tri-codes; season `S` =
`20262027`. Unbuildable payloads are `{"ok": false, "reason"}`; document deviations under "As built" at the end. Fractions 0–1.
Spread convention: puck line is the home team's line (−1.5 means home favoured).

## Site-wide
- `data/index.json`: `{"updated_at","season","phase","today":[GAME_CARD],"live":[GAME_CARD],"recent":[GAME_CARD],"upcoming":[GAME_CARD],
  "playoff_odds":{team:{"p_playoffs","p_div","p_pres","p_cup"}},"leaders":{metric:[[pid,value]]},"gaps":[...],"teams":{abbr:{"name","colour","alt","division","conference"}}}`
  GAME_CARD = `{"game_id","date","start","status","period","clock","home","away","hs","as","goalies":{"home","away"},
   "model":{"p_home","p_reg_home","p_ot","total","puck_line_home"},"market":{"p_home","sources"}|null,"line":{"ml_home","ml_away","puck_line","total","open","close"}|null,"wp_home":live|null,"xg":{"home","away"}|null}`
- `data/players_index.json` `{pid:[name, team, pos, first_season, last_season]}`; `data/glossary.json`; `data/calibration.json`;
  `data/history.json` (champions 1917→, season leaders).

## Per season — `data/<S>/`
- `season.json`: standings (division/conference/wild card; GP, W, L, OTL, PTS, P%, RW, ROW, GF, GA, xGF%, our rating), sim odds per team
  (p_playoffs, p_div, p_pres, p_conf, p_cup, points distribution, seed distribution, magic/elim), lottery odds, bracket with odds,
  team ratings by component with history.
- `schedule.json` `{"games":[GAME_CARD]}`.
- `games/<game_id>.json` (current and previous season): pre-game model v market v line (win, regulation, OT, puck line, total, score
  distribution), goalie starters; live/final: linescore by period, shot map (cols: period, sec, team, player, x, y, type, shot_type,
  xg, goal, strength), xG race chart data, win probability (ours), shift-based line usage and TOI, box with advanced stats
  (individual xG, shots, hits, blocks, giveaways/takeaways, faceoffs, TOI by strength, on-ice xGF%), game awards.
- `teams.json`: unit ratings (5v5 offence/defence, PP, PK, goaltending) with history, shot maps for/against (hex/zone grids),
  line combinations (forward lines, D pairs with TOI and on-ice xGF%), deployment, schedule v model.
- `skaters.json` / `goalies.json`: catalogues `{"metrics":[METRIC],"players":{pid:{"name","team","pos","age","gp","toi","qualified",
  "values":{key},"pct":{key},"pct_pos":{key}}}}`, METRIC = `{key,label,group,fmt,lower,scope,desc,stabilises_at}`.
- `lines.json`, `leaders.json`, `lab.json` (column-oriented per kind), `awards.json`, `markets.json`.

## Per player — `data/players/<pid>.json` (career 2009-10→ with season totals back to their debut from stats REST)
`{"id","name","pos","shoots","dob","height","weight","seasons":[...],"current":{"log":[...],"shots":{grid + points},"onice":{...},
 "rapm":{...},"edge":{...},"linemates":[...],"deployment":{...},"projection":{...}},"similar":[...]}`

## Front-end contract (`docs/rink/`)
Copy the Gridiron shell (`docs/gridiron/index.html`, `assets/js/{core,charts,fx}.js`, css) as `window.RK`: season picker, search,
nav (Hub, Games, Standings, Playoffs, Teams, Skaters, Goalies, Lines, Leaders, History, Lab, Compare, Markets, Calibration,
Glossary, Methodology). Name "The Quant Rink", tagline "Odds, models and analytics for the NHL". Sister group: Footballer, Paddock,
Hardwood, Ace, Bullpen, Gridiron. Charts: half-rink shot map (200×85 ft rink, attacking right; xG-sized dots, goals filled),
xG race chart, WP chart, shot heatmaps (hex/zone, v league), on-ice impact (RAPM offence × defence), linemate network/table,
Savant-style percentile sliders. Routes: `#/`, `#/games[/<date>]`, `#/game/<id>`, `#/standings[/<S>]`, `#/playoffs[/<S>]`, `#/value` (`?tab=val`: multi-season valuation), `#/trade`, `#/moves`, `#/fantasy`,
`#/teams`, `#/team/<abbr>`, `#/skaters`, `#/goalies`, `#/player/<pid>`, `#/lines`, `#/leaders`, `#/history`, `#/lab`,
`#/compare/<a>/<b>`, `#/markets`, `#/calibration`, `#/glossary`, `#/methodology`, `#/disclaimer`.
Disclaimer: no affiliation with the NHL, NHLPA, teams, players, ESPN or bookmakers; no logos; NHL data shown for informational,
non-commercial use; "xG benchmark data from MoneyPuck.com" credited where shown; 18+ where gambling is discussed. First-visit notice
key `qr-notice-v1`.

## As built (builder D, `scripts/build_rink.py`, `oddsmarkets/nhl/analytics/`)
Names above are kept; additions and the exact shapes the front end reads:
- **GAME_CARD** also carries `ot`, `so`, `type` ("REG"/"PO"), `series` (playoff {round, series, game}). `goalies` = starter
  pids (strings). `model` = {p_home, p_reg_home, p_ot, total, puck_line_home, source: "game" (live pricing) | "frozen" (last
  pre-game price) | "walk_forward" (builder C's weekly-refitted ratings, completed games)}. `line` = {ml_home, ml_away,
  puck_line (home), total, src, open, close} with open/close {ml_home, ml_away, puck_line, total} | null. `market` is
  {p_home, sources} from Kalshi/Polymarket when quoted, else de-vigged from the store's moneylines with sources ["line"].
  `wp_home` set for live games (builder C's live model on the store's period/clock/score). `xg` all situations, empty net out.
- **index.json** also: `ok`, `seasons`, `models` (versions), `sim_reason`. `leaders` keys are `s_<metric>` (skaters) and
  `g_<metric>` (goalies) → [[pid, value]] (top 10). `gaps` = [{kind: "game"|"cup"|"conference"|"division"|"presidents"|
  "playoffs", game_id?|team?, model, market, edge}] with |edge| ≥ 0.03, largest first.
- **games/<id>.json**: {card, pregame, venue, attendance, type, teams {abbr: {abbr, name, colour}}, xg_source, linescore
  [{period, g_home, s_home, xg_home, g_away, s_away, xg_away}], shots {cols, rows, players {pid: name}} (type ∈ goal | shot |
  miss | block; xg null on blocks; strength = event team's "5v5"/"5v4"/"EN"...), xg_race {cols [sec, home, away, goal], rows}
  (goal = scoring team or null), wp {source "live" | "poisson", series [[sec, p_home]], now}, usage {team: [{id, name, pos,
  toi, toi_5v5, toi_pp, toi_sh, shifts}]} (minutes), lines {team: {forwards [LINE], pairs [LINE]}} (this game's 5v5 units),
  box {skater_cols, goalie_cols, skaters {team: [rows]}, goalies {team: [rows]}}, awards {stars [{id, name, team, score,
  line}], top_xg, best_line, method}, kept_from (when event blocks were kept from an earlier build)}.
  `pregame` = {model, source, market, market_detail (Kalshi/Polymarket spread/total/OT ladders), line, goalies,
  priced_at}; `model` = {p_home, p_reg_home, p_reg_away, p_ot, p_so, p_ot_home, puck_line_home (P(home -1.5 covers)),
  puck_line_away, total (expected), fair_total, p_over, total_line, home_goals, away_goals, total_dist [P(total = 0..15)],
  score_dist {rows "home goals 0-6", cols "away goals 0-6", p 7x7 final-score matrix}, goalies, source}. Walk-forward and
  frozen prices carry the same keys minus score_dist when it was not computed.
- **LINE** = {ids [pid], names, toi (min), games, xgf, xga, xgf_pct, cf_pct, gf, ga, xgf60, xga60} (+ team in lines.json).
- **skaters.json / goalies.json**: METRIC also has `unit` (the stabilises_at unit: "5v5 minutes", "minutes", "shots",
  "unblocked attempts", "faceoffs", "unblocked attempts faced", "games"). Player rows also `teams`, `group` (F/D/G); goalies
  `catches`. `pct_pos` is v forwards or defencemen. A percentile needs the metric's floor (`reference.floors[den]`); metrics with no denominator (counts, GSAx, RAPM, value) need `floors.gp` games, so they are absent early in the season. Top level also `kind`, `team_games`, `reference` {n, min_toi5 | min_toi,
  floors}, `xg_source` ("model" builder B | "table" | "fallback" this layer's logistic), `coverage`, `model_errors`.
  Values of metrics whose model is missing are null (RAPM, value, adjusted rates, EDGE). Formats: `toi_min` = minutes
  (1 dp; TOI / GP, 5v5 TOI, PP / PK TOI per game, QoC / QoT, goalie TOI), `toi` = seconds (not used in catalogues), `p60` per
  60, `pct` fraction 0-1, `goals` 2 dp, `int`, `1`/`2`/`3` decimals, `mph`, `ft`, `sec`. RAPM: rapm_off, rapm_def (both
  "higher is better": defence = xGA/60 prevented), rapm_net, rapm_off_se, rapm_def_se, rapm_net_se (posterior SEs, no
  percentile), rapm_cf, rapm_ca (higher better), rapm_pp, rapm_pk (null until modelled).
- **teams.json**: {teams {abbr: {abbr, name, division, conference, colour, alt, record, units {off5, def5 (xGA/60), pp, pk,
  goalie (GSAx/60), pp_pct, pk_pct, pp_source ("nhl" = stats REST team summary, "events" = PP goals per minor drawn), gf_g, ga_g, xgf_g, xga_g, xgf_pct5, cf_pct5, gp, rating, source "team_strength"|"counts", model {C's
  components}, pct {unit: league percentile, 100 = best}}, history (C's, when given), rolling [[game_no, date, xgf_pct5,
  gf_pct, cf_pct5]] (10-game), shot_map {for, against: {att, xg, g, att60, xg60, att60_rel, xg60_rel, zones {crease, slot,
  high_slot, circles, point, perimeter, behind_net: {att, xg, g}}}, toi5}, lines {forwards, pairs}, deployment [{id, name,
  pos, gp, toi_gp, toi5_gp, toi_pp_gp, toi_sh_gp, ozs_pct, qoc_toi, xgf_pct, p, gar, rapm_net}], goalies [{id, name, gp,
  gsax, sv_pct, gs}], sim, schedule [{game_id, date, opp, home, status, gf, ga, result, p_win, p_market, xgf, xga}]}},
  grid {x0 25, dx 5, nx 14, y0 -42.5, dy 5, ny 17} (5v5 unblocked attempts; arrays row-major, index iy*nx + ix; attacking
  right, the net at x = 89), zones, league_map {att60, xg60}}.
- **season.json**: standings {rows [{team, name, division, conference, gp, w, l, otl, pts, p_pct, rw, row, gf, ga, diff,
  xgf_pct, rating, streak, l10, clinch, league_rank, p_playoffs, p_cup, mean_pts}], divisions [{conference, division,
  teams}], wild_card {conf: {leaders, wild_card, chasers, order}}, format, cols, tiebreak {steps [[key, text]], source}};
  sim {ok, reason, n, version, teams {abbr: {p_playoffs, p_div, p_pres, p_conf, p_cup, p_wildcard, p_top3, mean_pts,
  exp_pts (= mean_pts), pts_p05/p50/p95, points_dist {pts: p}, p_points_ge {N: p}, div_rank_dist, p_reach {round: p}, magic, tragic, clinched,
  eliminated, next_game {game_id, date, opp, home, p_win, if_win, if_loss}, lottery, rating}}}; lottery {odds, sources,
  table (by slot), teams {abbr: {p_first, p_top2, p_top3, pick_dist}}}; bracket {series [actual: {round, series, teams,
  wins, games, winner}], sim (C's {format, rounds, matchups {round: [{home_ice, other, p, p_home_ice_wins}]}}),
  seeds_now, champion}; ratings {abbr: {units, history, rolling}}; teams.
- **leaders.json**: {cols [id, value, name, team], skaters {key: {label, fmt, lower, rows}}, goalies {...}, teams {key:
  [[abbr, value]]}}. Counting stats rank everyone; rates the qualified pool.
- **lab.json** (column-major: data[key][i] belongs to ids[i]): {skaters / goalies: {cols, ids, name, team, pos, qualified,
  age, data {key: [...]}, labels {key: [label, fmt, lower, group]}}, teams {cols, ids, data}, lines_forwards / lines_pairs
  {cols, ids ("p1-p2-p3"), team, names, data}}.
- **lines.json**: {forwards [LINE], pairs [LINE], min_toi (20 min), model (builder B's lines with xgf_pct_shrunk)}.
- **awards.json**: {awards [{key, name, desc}], races {award: [{id, name, p}]} | null, basis {award: "clogit" |
  "simulation"}, reasons {award: why no race}, winners {award: [{name, team, value}]} (verified table; Richard can list two), boards {award: [[id, name, team, value]]} (Hart: GAR, Vezina: GSAx, Norris: D GAR, Calder: rookie points, Ross,
  Richard, Selke: forward RAPM defence), board_cols}.
- **markets.json**: {futures {cup | conference | division | presidents | playoffs: [{team, model, market, sources, edge}]},
  points [{team, source, points (N), market P(pts ≥ N), model, edge}], games [{game_id, date, start, home, away, status,
  model, market, line, detail, edge_home}], awards (C's fields {kind: {available, probs, reason, sources}}), sources, note}.
- **history.json**: {champions [{season, label, champion, finalist, note, source "table"|"store", champion_abbr?}] from
  1917-18, titles [[club, n]], season_leaders {season: {key: {label, id, name, team, value}}}, league [{season, label, games,
  goals_pg (per team-game, shootout winners out), shots_pg, xg_pg, sv_pct, sh_pct, pp_pct, pk_pct, pen_pg, ot_share,
  so_share, home_win, source}] (seasons on disk; league_cols lists them), seasons (stats REST list)}.
- **players/<pid>.json**: also `number`, `kind` ("skater"/"goalie"), `updated_at`; seasons [{season, team, teams, pos, age,
  qualified, values, plus (100 + 10 z in the season's qualified pool at the position), source ("stats" for stats-REST-only
  rows)}]; current {season, kind, log {cols, rows}, shots {grid, att, xg, g, points [[x, y, xg, goal]] (≤ 400), point_cols}
  (goalies: shots faced, `faced: true`), onice {5v5 values (toi5, cf60, ca60, cf_pct, xgf60, xga60, xgf_pct, gf60, ga60,
  gf_pct, on_sh_pct, on_sv_pct, pdo, rel and adjusted) + pct + by_strength {"5v5" | "pp" | "pk": {toi (min), cf60, ca60, ff60,
  fa60, sf60, sa60, gf60, ga60, xgf60, xga60, cf_pct, xgf_pct, gf_pct}}}, rapm {rapm_* incl. _se + pct}, deployment,
  projection, edge, linemates [[pid, name, toi_min]] (shared 5v5 time), pct; goalies `goalie` (catalogue values)};
  similar [[pid, name, team, distance]]. Shot grid arrays (`att`, `xg`, `g`) use the teams.json grid (row-major,
  iy * nx + ix); `points` are the last 400 unblocked attempts [x, y, xg, goal]. seasons[].values / plus are nested dicts
  keyed by metric.
- **players_index.json** is written even with --no-careers (from the stores' players).
- **value.json** (every season with catalogues, 15 Oct 2026; rewritten only when its content changes): {ok, season,
  updated_at, phase, version, currency {unit "WAR", goals_per_win, replacement 0}, team_games, roles {C, L, R, D, G},
  cols [id, name, team, pos (C/L/R/D/G), kind (S/G), age, gp, toi (min), toi_gp, gar, war, rate (GAR per 60), pct,
  pct_pos, q (1/0), prev_war, d_rate, ev_off, ev_def, pp, pk, shooting, pen, gsax, why], rows (WAR descending), best
  {pos: [pid x10]} (qualified), n_qualified {S, G}, note}. `why`: skaters [[part, GAR]] x2, goalies [["GSAx", v],
  ["save %", v]].
- **needs/<abbr>.json** (current season): {ok, season, team, updated_at, phase, basis "projection", grades [{key (C, L,
  R, D, G, ev_off, ev_def, pp, pk), label, value (projected GAR, full season), pct, grade A-F, rank, n}], strengths
  [{key, label, grade, pct, relative (below the median), evidence}] x3, weaknesses [... + targets [{id, name, team, pos, age, mpg, rate, gain (goals a
  game at the weak spot), gain_net, gain_season, pts, d_playoffs, d_cup, seller_cost, displaces [[pid, min]], hints,
  attainable}]] x3, depth [{id, name, pos, age, mpg, rate, basis}], games, games_left, free_agents, note}.
- **trade.json** (current season): {ok, season, updated_at, phase, version, params {budget {F, D, G}, cap {F, D, G},
  extra {F, D, G}, repl 0}, games, roles, group {pos: F/D/G}, adjacent {pos: [neighbours]}, components [six parts], players {cols [id,
  name, team, pos, age, mpg, rate, next, basis, ev_off, ev_def, pp, pk, shooting, pen], rows}, teams {abbr: {rating,
  se, gp, pts, left, exp_pts, p_playoffs, p_div, p_conf, p_cup, p_first, p_top2, conference}}, curves {shifts, keys,
  n_sims, teams {abbr: {key: [value at each shift]}}} | null, sim {n_sims, remaining_games} | null, aging {S, G:
  [[age, change in GAR per 60]]}, note}. `basis`: b both seasons, c this season only, p last season only, r none
  (replacement). The page adds curve(shift) − curve(0) to the 20,000-run baseline.
- **calibration.json**: the backtest blocks (game_model, season_sim, written by the models' backtest) passed through, plus
  xg {season: {validation, benchmark (v MoneyPuck xGoal), arena, model}} and xg_credit; {ok: false, reason} before either.
- Published text carries no internal builder references (scrubbed at write time).
- **valuation.json** (current season, 16 Oct 2026; analytics/valuation.py; ~106 KB, 819 rows): {ok, season, updated_at, phase,
  version, currency {unit "WAR", goals_per_win}, constants {discount 0.9, horizon 3, draws 400, avail_pseudo 30, avail_mean
  {S, G}, regular {S 0.25, G 0.12}, games [this season, +1, +2, +3], injury_games, shrink_minutes, prev_weight}, fits
  {reliability {S, G: {sigma2, delta2, tau2, k_rel, n_pairs}}, minutes {S, G: {cv, mean, n}}, survival {S, G: {coef, features,
  n, base, logloss, logloss_base}}, survival_by_age {S, G: [[age, n, observed, fitted]]}, positional {positions {C, L, R, D, G:
  {repl, starter, gap, scarcity, n_top}}, seasons, gap_skaters}, completed}, curves {aging {S, G: [[age, Δ GAR/60]]}, survival
  {S, G: [[age, P(regular next season)]]}}, cols [id, name, team, pos (C/L/R/D/G), age, rate (GAR/60), se, mpg, avail, games
  (left this season), now (WAR rest of season), next (WAR next season), total (4-season discounted WAR), p10, p90, vorp, s1, s3
  (P(regular) next season / in three), inj [status, return date, games missed] | null, basis], rows (total descending),
  injuries {source, fetched_at, rows, matched}, note}.
- **transactions.json** (current season; analytics/moves.py; ~320 KB, ~2,400 clauses over 12 months): {ok, season, updated_at,
  phase, version, source, window {from, to}, note, types {trade, signing, claim, waivers, release, recall, ir, other: label},
  cols [date, team, type, text (one sentence of ESPN's description), players [[pid | null, name]], deal (deal id | null)], rows
  (newest first), counts {type: n}, names {named, matched}, unmatched [[name, team, date, type, how]] (≤ 400), n_unmatched}.
- **deals.json** (current season; ~112 KB, 96 deals): {ok, season, updated_at, phase, version, source, window, note, constants
  {discount, minor_war 0.25, grades [[cut, letter]], deal_days 1, horizon 3}, deals [{id ("<date>-<club>-<club>"), date,
  teams, minor, winner_at, winner_now, total_at, total_now, sides {abbr: {at, real, now, sent_at, sent_now, share_at,
  share_now, grade_at, grade_now, net_at, net_now}}, assets [{k "player" | "pick" | "fc" | "cash", from, to; players: pid, name,
  pos, at, real, now, gp (games for the new club since), rights?, note?, gone? (no longer with that club), match? (how the name
  was matched when not exact); picks: year, round, overall | null, cond, at, now, yr_inferred?}], text [[abbr, sentence]]}]
  (newest first), teams {abbr: {deals, in_at, out_at, in_now, out_now, won, lost, net_at, net_now}}, best [deal ids x10],
  pick_curve {ok, a, b, c, max_overall, points [[overall, value]] x224, round_avg {1..7}, round_empirical {round: [mean, n,
  share with WAR > 0]}, r2_slots, r2_bins, n_picks, drafts, seasons 7, discount}, pick_raw [[overall, mean, n]], n {deals,
  graded, players, players_matched, picks}}. All values WAR discounted to the trade's season.
- **fantasy.json** (current season; analytics/fantasy.py; ~305 KB, ~810 rows): {ok, season, updated_at, phase, version, asof,
  points {g, a, pm, ppp, sog, hit, blk, w, ga, sv, so} (our default weights), labels, cats {S, G}, weeks [[from, to]] x4
  (Monday-Sunday; the first from today), roster {C 2, L 2, R 2, D 4, UTIL 1, G 2, BN 4}, n_teams 12, replacement {pos: points},
  top_n 150, b2b_ratio, cols [id, name, team, pos, age, kind (S/G), rank, tier, pre_rank, ros, pts_pg, vor, z, left,
  inj_games, gp, toi, toi_es, toi_pp, pp_unit, share, starts, gaa, svp, flags [add | drop | buy | sell | breakout], inj
  [status, return] | null, pg_<cat> x11 (per game; goalies per start), ros_<cat> x11, w1..w4 (skaters [games, points],
  goalies [club games, starts, points]), act_pg, regress, luck, pdo [pdo, on SH%, on SV%] | null, toi5, toi_prev, pp5,
  pp_prev], rows (rank order), goalie_next {pid: [[date, opp, P(start), P(club wins), points]] x7}, teams {abbr: {left, weeks
  [[games, back-to-backs, mean opponent goals-against factor]] x4, def_g, off_g}}, picks [{kind, id, name, team, pos, why}],
  backtest {seasons, checkpoints, pts {S_week, S_ros, G_week, G_ros: {model, std, last: [mae, spearman]}}} | null,
  constants, note}.
- **fantasy_backtest.json** (site-wide; ~6 KB; computed by scripts/nhl_fantasy_backtest.py and cached; the hourly build only
  copies the cache): {ok, version, updated_at, seasons, checkpoints, step_days 7, cols [kind, horizon, cat, who (model | std |
  last), mae, spearman, games], rows, season_cols, by_season, baselines {std, last}, units, points, seconds, stale?}.
