# The Quant Hardwood: payload and front-end contract

Everything `scripts/build_hardwood.py` writes under `docs/hardwood/data/` and the site reads.
Field names are a contract between the Python builder (D) and the front-end builders (E, F).
Probabilities 4 dp, ratings 2 dp, rates 3 dp. Ids are ESPN ids (strings). A payload that
cannot be built is written as `{"ok": false, "reason": "..."}` rather than omitted.
League `L` is `nba` or `wnba`; season `S` is the ESPN year (NBA 2026-27 = 2027).

## Site-wide

`data/index.json`
```
{"updated_at",
 "leagues": {L: {"name","current_season": S,"seasons":[S...],"phase":"preseason|regular|playin|playoffs|offseason",
                 "today": [GAME_CARD], "next_games": [GAME_CARD] (next 3 days), "last_games": [GAME_CARD] (last 2 days),
                 "teams": {tid: {"name","abbr","short","colour","alt_colour","conference","division"}},
                 "champions": [[season, tid|name]] (1947→ for nba, 1997→ wnba, from history)}}}
```
GAME_CARD = `{"id","season","date","status","stype","home","away","hs","as","period","clock",
 "model": {"p_home","margin","total","av"?}, "market": {"p_home","spread_home","total","sources":[...]} | null,
 "wp_home": live model WP | null, "espn_wp": | null, "series": {...} | null}`

GAME_CARD notes: `period` = periods played (final) or the current period (live), `clock` "m:ss" (live only); `model` is the
pregame model (ratings fitted on games before the game day for played games); `market` is the prediction-market price where
fetched, else the DraftKings moneyline (de-vigged) or spread. `model.av` = [home, away] (NBA informed model only): each
team's availability term in points of its own margin (expected rotation against what its rating reflects; injury-report
Outs applied for upcoming games). The game payload's `pregame.model.detail` carries the same split as `injury_home` and
`injury_away` (both in points of home margin).

`data/glossary.json`  `{"groups":[{"name","entries":[{key,label,desc,fmt,lower,scope,kind:"player|team|lineup"}]}],"model":[{key,label,group,desc}]}`
`data/<L>/calibration.json` the backtest (`models/backtest.py`: metrics, metrics_vs_market, margin_rmse, per_season, season_sim, params_by_season,
 carryover, summary) + `{"updated_at","ok"}`, plus `"winprob"`: `winprob.calibration` on the latest season with play-by-play (ours against ESPN:
 {"n","ours":{"brier","logloss","table":[{"lo","hi","n","p_mean","y_mean"}]},"espn":{...},"ours_on_espn_rows","mean_abs_diff","n_espn","season"})
 and `"shots"`: {"season","by_zone": {zone: {"n","fg","p_mean","pts","xpts","brier","diff","z"}},"by_type": {...}}. Kept from the committed copy
 when CI has no backtest cache (the winprob and shots blocks are refreshed when their inputs are on the machine).
`data/<L>/history.json`  `{"seasons": [{"season","champion","runner_up","champion_name","mvp","finals_mvp"|null,"best_record":[tid,w,l]}],
 "champions": [[season, tid]], "first_season": S, "elo_all_time":[{"team","name","peak","season"}], "team_names": {tid: name}}`.
 Champions come from the season stores only (1997 on, as far as the backfill has reached); there is no pre-1997 source, so pages
 say "from <first_season>". index.json `champions` is the same list.

## Per league and season `data/<L>/<S>/`

`season.json`
```
{"ok","league","season","updated_at","phase","format": {conferences, divisions: {conf: [div]}, games, playin: bool, series: [..], rounds: [..],
           seeding: "conference"|"league", playoff_teams, verified},
 "teams": {tid: {"name","abbr","short","colour","alt_colour","conference","division"}},
 "standings": {conf: [{"team","w","l","pct","gb","conf_w","conf_l","div_w","div_l","home":[w,l],"away":[w,l],"l10":[w,l],"streak","pd","seed","division"}]},
 "sim": {"n_sims", "teams": {tid: season_sim.simulate team output (exp_w, w_p05, w_p95, seed_dist, p_playoffs, p_playin, p_top6, p_conf, p_title,
          p_reach{round:p}, win_dist, magic{target:n}, tragic, clinched, eliminated, next{game,date,opp,home,p_win,if_win{...},if_loss{...}},
          p_lottery_pick, current{...}, rating, rating_se)}, "notes", "remaining_games", "runtime_s", "hca", "sigma_noise"} | null
          (null: a light season or a finished season; the teams sit under "teams", never at the top level),
 "bracket": season_sim bracket | null, "postseason": {"series": [{"teams","stype","round","games":[...],"wins":{tid:n},"summary"}]} | null,
 "ratings": {tid: {"off","def","net","pace","se_net","games","rank"}}, "hca", "league_ortg", "league_pace",
 "rating_paths": {tid: [{"date","game","net","se"}]},
 "elo": {tid: elo}, "power": [[tid, net, rank_change_7d]],
 "schedule_difficulty": {tid: {"played","remaining","n_played","n_remaining"}},
 "leaders": {stat: [[pid, value]...10]}  # pts, reb, ast, stl, blk, 3pm per game; hpm; ts (qualified players only)
}
```
Win totals live in `markets.json` only (one source of truth), not in season.json. `sim.teams[tid].next.if_win` / `if_loss` are
interventional (the result forced, the rating draws held at their prior), so one regular-season game moves them by a few points.

`schedule.json`: `{"ok","league","season","updated_at","games": [GAME_CARD]}`, every game of the season in date order (league members
only: no "TBD" slots, no exhibition guests).

`games/<id>.json`: the game centre
```
{"ok","id","league","season","date","status","stype","home","away","hs","as","line":{...},"series",
 "venue","attendance",
 "periods","neutral","teams": {tid: team info},"has_pbp": bool,"updated_at",
 "pregame": {"model": game.predict output, "market": {"p_home","spread_home","total","sources","basis"}|null,
             "injuries": {tid:[{"player","name","status","detail","impact"}]}, "elo_p_home"},
 "box": {tid: {"players":[{"id","name","pos","starter","min","pts","fgm","fga","tpm","tpa","ftm","fta","oreb","dreb","reb","ast","stl","blk","tov","pf","pm","ts","usg","game_score","wpa","pox"}],
               "team": {...ESPN team line, pts, poss, pace, ortg, ff_efg, ff_tov, ff_orb, ff_ftr}, "dnp": [{"id","name","reason"}]}},
 "four_factors": {tid: {"efg","tov","orb","ftr"}},
 "flow": [[t, margin_home]],                        # one point per scoring play
 "wp": {"model": [[t, p_home]], "espn": [[t, p_home]]} | null,
 "shots": {"cols": ["t","team","player","x","y","value","made","xpts","zone","type","assisted"], "rows": [...]} | null,
 "shot_quality": {tid: {"xpts","pts","pox","xefg"}} | null,
 "lineups": {tid: [{"players":[5],"sec","poss","pts_for","pts_against","net"}]} | null,
 "rotation": {tid: {pid: [[t0,t1]...]}} | null,
 "plays": [{"t","period","clock","team","text","score","wpa","dwp_home","wp","li","players":[...],"credit":[...]}] | null,   # top-leverage 60 plus all scoring in the 4th/OT
 "awards": {"player_of_game": AW, "biggest_swing": AW, "shot_maker": AW, "unluckiest": AW, "stopper": AW, "excitement": number, "comeback": number}
}
```
AW = `{"player","team","value","label","why"}` (any AW may be null; "unluckiest" has player null). Box-only seasons (no pbp):
flow/wp/shots/lineups/rotation/plays null; a pbp-era game whose raw play-by-play is not on the building machine keeps shots,
lineups and rotation (from the derived inputs) with flow/wp/plays null.
Units: box `min` is decimal minutes (34.5); `t` is elapsed game seconds; `wp` points are [t, P(home wins)] with 3 dp; a play's `wpa`
is the change in the **acting team's** win probability (a 0-1 fraction; the home team's when the play has no team), `dwp_home` the
change in the home team's, `wp` the home WP after the play, `credit` each listed player's share in his own team's terms (aligned
with `players`). Box `wpa` is the player's game WPA (own team's terms) and `pox` his points over xPTS.

`teams.json`: `{"metrics":[METRIC], "teams": {tid: {"name","values":{key:v},"pct":{key:0-100},"rank":{key:n},"log":[{"game","date","opp","home","res","pts","opp_pts","ortg","drtg","pace","net_rating_after","p_win"}],
 "roster":[{"id","name","pos","min","gp","hpm","o","d"}], "lineups":[{"players":[5],"poss","net","ortg","drtg","shrunk_net"}],
 "rotation": {"games":[gid...], "players":[pid...], "minutes":[[...]]},
 "on_off": {pid: {"on_net","off_net","diff","poss_on"}},
 "shot_profile": {"for": ZONES, "against": ZONES}, "injuries":[...], "odds": {"p_playoffs","p_title",...,"market":{...}}}}}`
ZONES = `{zone: {"freq","fg","pps","league_pps","n"}}` with zone in rim | paint | mid | corner3 | ab3 | heave.
teams.json also carries per team `"short","abbr","colour","conference","division"`, `"pairs"` and `"trios"` (2- and 3-man units, same
fields as lineups plus `hpm_sum`), `"rating_path"`, and roster rows carry `"mpg"`. `log[].net_rating_after` is the model's (Kalman) net
after that game; `log[].p_win` the pregame model's probability that this team wins (ratings fitted on games before the game day).
Team log and records are regular-season games only.

`players.json`: the season catalogue (one row per player with ≥1 game)
```
{"metrics":[METRIC], "pools": {"G","F","C"}, "min_floor": minutes for qualification,
 "players": {pid: {"name","team","pos","pool","age","gp","min","qualified","values":{key:v},"pct":{key},"pct_pool":{key},"rank":{key}}}}
```
METRIC = `{"key","label","group","fmt":"int|1|2|3|pct|prob|pm|sec","lower":bool,"scope":"all|pbp","desc"}` (125 player, 75 team).
Values with fmt "pct" are **0-1 fractions** (0.573 = 57.3 %), "prob" likewise (4 dp). `pools` is `{"G"|"F"|"C": {"label","n"}}` (n =
qualified players); also `"groups"`, `"n_qualified"`, `"league_ts"`, `"has_pbp"`. `pct` (league) and `pct_pool` place every player
against the qualified players (100 = best, direction-aware); `rank` is set for qualified players only. Season stats are regular-season
only (the NBA Cup final does not count). `age` is null where ESPN gives no date of birth.
Role peer groups (22 Oct 2026, docs/_design/metrics/basketball.json): each row also carries `"role"` G | W | B (guards, wings,
bigs; `value.classify_roles`, the same rule and values as value.json) and `"pct_role": {key: 0-100}` against the qualified
players of that role for `players.ROLE_PCT_KEYS` (the spec's headline and secondary metrics); the catalogue adds
`"roles": {"G"|"W"|"B": {"label","n"}}` and `"role_rule": {"threshold","features"}`.

`players/<pid>.json` (per league, not per season: `data/<L>/players/<pid>.json`)
```
{"id","name","pos","pool","dob","league","updated_at",
 "seasons":[{"season","team","gp","min","pts","reb","ast","ts","hpm","o","d","rapm"|null,"box_impact","wpa"|null,"qualified"}],
 "current": {"season","team","log":[{"game","date","opp","home","min","pts","reb","ast","stl","blk","tov","fgm","fga","tpm","tpa","ftm","fta","pm","game_score","wpa"}],
             "shots": {"grid": {"cols":["x","y","n","fg","pps","share","lg_fg","lg_pps","fg_diff","pps_diff"],"rows":[...]} (hex cells, r = 1.5 ft),
                       "zones": ZONES, "types": {type:{"n","fg","pps"}}, "n"} | null,
             "on_off": {"on_net","off_net","diff","on_ortg","on_drtg","off_ortg","off_drtg","poss_on","poss_off"} | null,
             "lineups": [{"players","poss","net","ortg","drtg","shrunk_net","sec"}...top 5], "clutch": {"min","pts","ts","net","wpa","poss"} | null,
             "projection": impact.projections row, "hpm": {"t","o","d","se","se_o","se_d","box_o","box_d","w_rapm_o","w_rapm_d"}, "rapm": {...},
             "awards": {award: p}} | null (null for players not in a season built in full on this machine),
 "similar": [{"id","name","season","distance"}], "career_awards": [[season, award]]}
```

`awards.json`: `{"ok","league","season","updated_at","keys": [award...], "labels": {award: label},
 award: {"model": {pid: p}, "p_top3": {pid: P(top 3 finish)}, "market": TITLE|null, "features": {pid: {...}}, "eligible": {pid: bool},
         "fit": {"features": [...], "weights": [...], "n_seasons", "fitted": bool, "top1"}}}` for mvp, roy, dpoy, sixth, mip and (NBA only)
 clutch; iterate `keys`. `sixth` is the Sixth Man (NBA) / Sixth Player (WNBA) award everywhere (the model's internal name is 6moy).
 `fit` is the conditional-logit fit on past winners (`fitted` false = hand-set default weights; `top1` = share of training seasons whose
 winner had the highest score). Once an award is announced, `award.winner` = `{"names": [...], "ids": [pid|null...]}` (from
 `models/award_winners.py`; ids by folded name among the season's players, null when the store cannot resolve the name).
`markets.json`: `{"ok","league","season","updated_at","fetched": bool, "futures": markets.futures(...) | null,
 "model": {"champion": {tid: p}, "conference": {tid: p}, "playoffs": {tid: p}},
 "games": {gid: {"season","home","away","date","model": {"p_home","margin","total","spread_fair"},"market": {...}|null,"edge"}},
 "win_totals": {tid: {"line","p_over_model","p_over_market","ladder"}} | null}` (games: the next 3 days)
`lab.json`: column-oriented, `{"fields":["id","name","team","season","pool","gp","min", ...metric keys], "metrics":[METRIC], "rows":[[...]], "years":[S...]}` (seasons with box data; pbp metrics null before ~2017).
`shots_league.json`: `{"ok","league","season","updated_at","n_shots",
 "grid": {"cols": ["x","y","n","fg","pps","xpps","share"], "rows": [[...]]}  (hexagons of circumradius 1.5 ft; x, y = cell centre in feet, rim at 0,0),
 "grid_square": the same on 2-ft squares, "grid_kind": {...}, "zones": ZONES, "types": {type: {"n","fg","pps"}},
 "calibration": {zone: {"n","fg","p_mean","pts","xpts","brier","diff","z"}}, "calibration_type": {shot_type: {...}},
 "curve": [{"dist_ft","zone","value","p","xpts"}], "model": {"version","n","fg","pps","loglik"}}`; `{"ok": false}` for box-only seasons.
`manifest.json` (per season, build bookkeeping: input signatures and game-page signatures) and `pbp_summary.json.gz` (per-game
play-by-play summaries the catalogues are built from, kept so CI need not re-parse raw files it does not have): not for the front end.

## Value, needs and trade (`analytics/value.py`, 15 Oct 2026; models in docs/basketball/MODELS.md section 14)

`value.json` (every season with a catalogue; rewritten only when the content changes):
```
{"ok","league","season","updated_at","phase","version",
 "currency": {"unit":"WAR","points_per_win","replacement":-2.0,"pace","game_minutes","games"},
 "roles": {"G":"Guards","W":"Wings","B":"Bigs"}, "role_rule": {"threshold","features":[...]},
 "cols": ["id","name","team","pos","role","age","gp","min","hpm","o","d","se","par","war","par_g","pct","pct_role","q",
          "prev_war","d_hpm","why"],
 "rows": [[...]] (WAR descending; q 1/0 = qualified; why = [[skill, league percentile]] up to 3),
 "best": {"G"|"W"|"B": [pid x10]} (qualified only), "n_qualified", "min_floor", "note"}
```
`needs/<tid>.json` (current season):
```
{"ok","league","season","team","updated_at","phase","basis":"projection",
 "grades": [{"key": G|W|B|off|def|start|bench, "label","value" (projected WAR, full season),"pct","grade" A-F,"rank","n"}],
 "strengths": [{"key","label","grade","pct","relative","evidence"}] x3 (relative: below the median),
 "weaknesses": [{... (relative: above the median), "targets": [{"id","name","team","role","age","mpg","rate","gain" (per 100 at the weak spot),
                 "gain_net","wins","d_playoffs","d_title","seller_cost","displaces":[[pid,min]],"hints":[str],
                 "attainable": bool,"war_rest"}]}] x3,
 "depth": [{"id","name","role","pos","age","mpg","rate","o","d","basis"}], "fill","games","games_left",
 "free_agents","note"}
```
`trade.json` (current season):
```
{"ok","league","season","updated_at","phase","version",
 "params": {"league","G","cap","max_min","extra","repl","pace","ppw"}, "games", "roles", "adjacent": {role: [neighbours]},
 "players": {"cols": ["id","name","team","pos","role","age","mpg","rate","o","d","next","basis","inj"], "rows"},
 "teams": {tid: {"rating","se","w","l","left","exp_w","p_playoffs","p_top6","p_conf","p_title","p_top4","conference"}},
 "curves": {"shifts":[-6,-3,-1.5,0,1.5,3,6],"keys":[...],"n_sims","teams": {tid: {key: [value at each shift]}}} | null,
 "sim": {"n_sims","remaining_games"} | null, "note"}
```
`basis`: b = this season and last, p = last season's projection only, c = this season only (pulled towards replacement),
r = no data (replacement). `inj`: "status (detail)" from the team's injury list or null. The page adds
curve(shift) − curve(0) to the baseline; `curves` null in the offseason.

## Valuation, moves and fantasy (`analytics/valuation.py`, `moves.py`, `fantasy.py`, 16 Oct 2026; models in docs/basketball/MODELS.md section 15)

Written for each league's current season by `build_hardwood.py layers_current` (each step isolated; `{"ok": false,
"reason"}` on failure). Sizes on 16 Oct 2026: NBA 2027 valuation 85 KB, transactions 52 KB, deals 86 KB, fantasy 118 KB;
WNBA 2026 31 / 16 / 6 / 40 KB. Inputs: `data/<L>/bio.json` (scripts/bb_bio.py; committed), the transactions cache
`<cache>/transactions/<L>_<year>.json` (ESPN, refreshed by the build at most every 3 h), `data/<L>/fantasy_backtest.json`
(scripts/bb_fantasy_backtest.py; committed).

`data/<L>/bio.json` (input, never fetched by the build):
```
{"_meta": {"source","updated_at","players","with_dob","with_draft","drafts_checked": {year: day}},
 "_drafts": {"YYYY": [[overall, round, pick, team_id, athlete_id, name, traded]]},
 pid: {"dob": "YYYY-MM-DD"|null, "draft": [year, round, pick, team_id]|null, "debut": year|null, "checked": day}}
```

`valuation.json` (valuation v2: four season slots, discounted 0.9):
```
{"ok","league","season","updated_at","phase","version": 1,
 "cols": ["id","name","team","pos","role","age","basis","rate","sd","mpg","avail","inj","g0","w0","w1","w2","w3",
          "v","p10","p50","p90","surv","vorp","pct","rank"], "rows": [[...]],
 "slots": ["rest of 2027","2028","2029","2030"],
 "constants": {discount, slots, replacement, avail_k, n_sims, aging_min, surv_min, surv_next_min, info_min, rotation,
               pace, points_per_win, game_minutes, games},
 "fit": {"aging": [[age, change]], "aging_info": {n_pairs, mean_change}, "aging_handset": [[age, change]],
         "spread": {s1, s2, tau, n1, n2}, "surv": [b0..b4], "surv_info": {n, rate, logloss, logloss_base}, "avail", "min_cv",
         "seasons", "rows_with_age", "rows"},
 "survival_curve": [[age, p]], "positions": {G|W|B: {repl, n, slots, top10, scarcity}}, "note"}
```
`rate` rest-of-season HPM; `sd` the persistent rate error used in the band; `w0..w3` mean-path WAR per slot (future
slots floored at zero, survival applied); `v` the discounted sum; `p10/p50/p90` the Monte Carlo band; `surv` the chance he
is still playing in the last slot; `vorp` the same value measured from his position's replacement level.

`transactions.json` (last 365 days):
```
{"ok","league","season","updated_at","since","until","types": {code: label},
 "cols": ["date","team","types","text","players","deal"], "rows": [[day, team_id, [type codes], ESPN text, [pids], deal id|null]],
 "unmatched": [names], "source"}
```
Type codes: trade, sign, release, claim, contract, injury, assign, discipline, staff, other.

`deals.json` (every trade of the window, rated):
```
{"ok","league","season","updated_at","version","window": [since, until],
 "deals": [{"id","date","season","teams": [tids],"rows": [{"team","date","text"}],"zero": [notes valued at zero],
            "sides": [{"team","in": [ITEM],"out": [ITEM],"v_in","v_out","share","grade","r_in","r_out","now_in","now_out",
                       "share_now","grade_now"}], "total","total_now","winner","winner_now"}],
 "teams": {tid: {"n","net_time","net_now","net_real","in_time","out_time","best": [deal id, net],"worst": [...]}},
 "pick_curve": {"picks": [[overall, WAR]], "raw": [[overall, mean, drafts]], "rounds": {round: mean}, "n_drafts","years","seasons"},
 "n_rows","unmatched","constants": {discount, slots, grade_cuts, minor, deal_days, prior_shrink_min}, "note"}
ITEM player: {"k":"p","id","name","age","rate","mpg","v","p10","p90","real","gp","rem","now","still"}
ITEM pick:   {"k":"pick","label","v","now","swap"}
```
`v` value at the time (no hindsight), `real` realised since for the new team, `rem` today's projection of the rest of the
window while he is still there (`still` 1), `now` = real + rem. Grades: A ≥ 0.65 share, B ≥ 0.55, C ≥ 0.45, D ≥ 0.35, F;
"minor" when the deal moved under 0.5 WAR.

`fantasy.json`:
```
{"ok","league","season","target","updated_at","phase","version","season_over","started",
 "cols": ["id","name","team","pos","role","age","inj","ret","mpg","mpg_now","last_mpg","avail","left","xgp","rank9","rankp",
          "rank_pre","pg","ros","weeks","luck"],
 "pg_cols": ["min","pts","reb","ast","stl","blk","tpm","tpa","fgm","fga","ftm","fta","tov","dd","td"],
 "tot_cols": ["pts","reb","ast","stl","blk","tpm","fgm","fga","ftm","fta","tov","dd","td"],
 "week_cols": ["g","xgp", ...tot_cols], "luck_cols": ["luck","pps_luck","tp_luck","ft_luck","fg3","fg3_exp"],
 "rows": [[..., pg [per game], ros [rest-of-season totals], weeks [[week 1], [week 2]], luck [..]|null]],
 "weeks": [[monday, sunday] x 4], "teams": {tid: {"left","weeks": [[games, b2b, light, opp_pts] x 4]}},
 "team_week_cols", "cats", "cat_labels", "presets": {key: {"label","w": {stat: points}}},
 "picks": {core|points|breakouts|buy_low|sell_high|adds|drops|streamers|punt_fg|punt_ft|punt_tov: [[pid, reason]]},
 "rest": {"min": {rest: ratio}, "play": {rest: ratio}, "seasons"}, "opp": {tid: {stat: factor, fg_pct, ft_pct}},
 "league_pace", "constants", "backtest": {summary, updated_at, seasons, checkpoints, n} | null, "note"}
```
`season_over`: the current season has no games left, so projections are for the next season (`target`). The page computes
9-category z-scores (with punts), points for any weights, tiers and position VORP from `pg` / `ros` / `weeks`.

`data/<L>/fantasy_backtest.json`: `{"ok","league","updated_at","seasons","checkpoints","n","summary": {next_week |
next_week_total | ros: {ours | season_to_date | last_season: {"mae","spearman","n"}}},"by_season": {S: {summary, cats,
checkpoints}},"scoring","constants","seconds"}`.

Front end: `#/<L>/moves` (moves.js: trade ratings, feed, pick values; `?tab=`, `basis=`, `team=`, `type=`), `#/<L>/fantasy`
(fantasy.js; `?fmt=`, `hz=`, `punt=`), the "Valuation over four seasons" card on `#/<L>/value` (value.js), the team page's
"Ledger" card (teams.js via `HW.movesLedger`).

## Front-end contract (`docs/hardwood/`)

Static, no build step, Plotly 2.27 (cdn.plot.ly), dark theme, same design system as the football and F1 sites
(`assets/base.css` is copied by the build from `docs/site/assets/style.css`; page styles in `assets/hardwood.css` and `assets/pages.css`).
Copy the F1 shell (`docs/paddock/assets/js/core.js`) as `window.HW` with the same helper API (load, loadAll, route, esc, num, pct,
signed, fmtDate, fmtTime, card, tableHTML, sortable, pctPill, statTile, plot, layout, …) adapted: `teamColour(L, tid)`,
`teamLink(L, tid)`, `playerLink(L, pid)`, `gameLink(L, gid)`, `HW.state {league, season, route, params}`.

Routes (hash): `#/` hub (league from state, default nba), `#/<L>` league hub, `#/<L>/season/<S>`, `#/<L>/game/<gid>`,
`#/<L>/team/<tid>`, `#/<L>/player/<pid>`, `#/<L>/players`, `#/<L>/teams`, `#/<L>/leaders`, `#/<L>/awards`,
`#/<L>/playoffs`, `#/<L>/lab`, `#/<L>/compare/players/<a>/<b>`, `#/<L>/compare/teams/<a>/<b>`, `#/<L>/markets`,
`#/<L>/calibration`, `#/glossary`, `#/methodology`, `#/disclaimer`.

Header: name "The Quant Hardwood", tagline "Odds, models and analytics for the NBA and WNBA", search (teams + players of the
league), league switch (NBA | WNBA), season picker, nav (Hub, Season, Games, Teams, Players, Value, Trade, Moves, Fantasy, Leaders, Awards, Playoffs, Lab,
Compare, Markets, Calibration, Glossary, Methodology), a sister-sites group linking
https://pchattani.github.io/the-quant-footballer/ and https://pchattani.github.io/the-quant-paddock/. Footer and first-visit
notice as on the paddock (localStorage key `qh-notice-v1`); disclaimer: not affiliated with the NBA, WNBA, any team, player,
ESPN or a bookmaker; no logos.

Court drawing: shot charts are drawn in feet with the rim at (0, 0), x −25..25 across, y up the floor; draw the court (paint
16 ft wide NBA / 16 WNBA, restricted area 4 ft, free-throw circle 6 ft, 3-pt arc 23.75 ft NBA / 22.15 ft WNBA with 22 ft
corners, baseline at y = −5.25) with Plotly shapes in `HW.charts.court(league)`.
