# The Quant Campus: payload and front-end contract

Everything `scripts/build_campus.py` writes under `docs/campus/data/` (env `CAMPUS_DATA`) and the site reads.
Field names are a contract between the payload writers (B: football, C: basketball, D: site-wide) and the front
end (D). Probabilities 4 dp, ratings 2 dp, rates 3 dp, ids are ESPN ids (strings). A payload that cannot be built
is written as `{"ok": false, "reason": "..."}`, never omitted. `L` = `cfb | mbb | wbb`; `S` = season (canon.py).
Every payload carries `"ok": true, "level", "season" (where per season), "updated_at"`.

**Size budget** (GitHub Pages 1 GB per site; this one is kept under 800 MB): game pages only for the current season
(every game involving an FBS / D-I team) and the previous season's postseason; career files only for players with a
game in the last two seasons; everything else per season. `build_campus.py` prints a size report and exits non-zero
over 800 MB.

## Shared shapes

TEAM (index.json, season.json): `{"name","short","abbr","colour","alt_colour","conference": cid,"member": bool}`
(no logos anywhere: ESPN logos are not ours to use; the kit's monogram marks stand in).

CARD (a game in any list):
```
{"id","season","date","status":"pre|in|post|postponed|canceled","stype","round","region","note","week",
 "home","away","hs","as","hr","ar" (AP ranks or null),"hseed","aseed","neutral","conf_game",
 "period","clock" (live only),
 "model": {"p_home","margin","total"} | null,
 "market": {"p_home","spread_home","total","source"} | null,     # source: kalshi|polymarket|espn_close|espn
 "result": {"cover": "home|away|push"|null, "model_correct": bool|null} | null}   # finals only
```
`model` is pregame (ratings fitted on games before the game day for played games).
(C, basketball) To keep the size budget, basketball CARDs omit keys whose value is null and `neutral` / `conf_game`
when false (read a missing key as null / false);
seasons older than the previous one ("archive" seasons) carry compact CARDs in `schedule.json` (flag `"compact": true`)
(`id, season, date, status, stype, round, region, home, away, hs, as, hr, ar, hseed, aseed, neutral, conf_game`,
`model.p_home`, `market.spread_home`, `result`) and on team pages (the same without `season`, `hr`, `ar`, `result`:
the page's season applies); their `players.json` holds qualified players only (without `pct` / `pct_pos`),
`lab_players.json` qualified players with 15+ minutes a game, team pages the top 12 of the roster by minutes, no
`suggestions` and no `rating_path` (read `season.json` `rating_paths`).
Basketball player payloads are Division I players only (non-D-I opponents' box rows are dropped).

METRIC: `{"key","label","group","fmt":"int|1|2|3|pct|prob|signed1|signed2","lower": bool,"desc"}`.

## Site-wide (builder D: `oddsmarkets/college/site.py`)

`data/index.json`
```
{"ok","updated_at",
 "levels": {L: {"name","short","sport":"football|basketball","current_season": S,"seasons":[S...],"phase",
                "week": int|null (cfb), "headline": str,           # one line: e.g. "Week 8 · CFP odds after Saturday"
                "today":[CARD],"next_games":[CARD] (next 3 days, at most 40, ranked/close first),"last_games":[CARD] (last 2 days, at most 40),
                "top25": [{"rank","team","prev","record"}] (latest AP poll) | [],
                "model_top": [{"rank","team","rating"}] (our top 25),
                "title_odds": [{"team","p","market"}] (top 12),
                "conferences": {cid: {"name","short"}},
                "teams": {tid: TEAM},
                "champions": [[season, tid]]}}}
```
phase: cfb `preseason|regular|conf_champ|bowls|playoff|offseason`; basketball `preseason|regular|conf_tourneys|ncaa|offseason`.

`data/glossary.json` `{"groups":[{"name","entries":[{"key","label","desc"}]}]}`.
`data/search.json` `[{"t","s","href","sport":"college","w"}]` (teams of every level, players with a career file;
`href` = `#/<L>/team/<tid>` or `#/<L>/player/<pid>`).

## Per level `data/<L>/` (builders B and C)

`calibration.json` (walk-forward backtest)
```
{"ok","level","updated_at","seasons":[S...],"n_games",
 "summary": {"model": {"brier","logloss","acc","mae","rmse","n"}, "elo": {...}, "close": {...same, on games with a close},
             "vs_close": {"n","mae_model","mae_close","ats_hit","ats_n","ats_se","total_mae_model","total_mae_close","total_n"},
             "espn_predictor": {...} | null},
 "per_season": [{"season","n","n_close","model": {...},"close": {...},"ats_hit"}],
 "calibration": [{"lo","hi","n","p_mean","y_mean"}],
 "by_spread": [{"lo","hi","n","mae_model","mae_close","ats_hit"}],
 "sim": {...season-sim backtest where built: e.g. CFP field hit rate, NCAA seed MAE, title Brier} | null,
 "notes": [str]}
```
`history.json` `{"ok","level","champions": [{"season","team","runner_up","score"}], "conference_champions": {S: {cid: tid}},
 "best_teams": [{"season","team","rating","record"}] (top 25 ratings all-time), "first_season"}`.
`markets.json` `{"ok","level","season","updated_at","fetched": bool,"futures": markets.futures(...)|null,
 "model": {"champion": {tid: p}, "conference": {cid: {tid: p}}, "playoff"|"ncaa": {tid: p}},
 "games": {gid: {"home","away","date","model":{...},"market":{...}|null,"edge"}}}`.
`players/<pid>.json` (career)
```
{"ok","id","name","pos","level","updated_at","class","height_in","weight_lb","hometown",
 "seasons": [{"season","team","gp", ...sport stats..., "value","value_pg","pctl"}],
 "current": {"season","team","log":[{"game","date","opp","home","res", ...stats...}], "value": VALUE_ROW,
             "fantasy": {...} | null} | null,
 "moves": [{"season","from","to","value_before","value_after"}], "similar": [{"id","name","season","distance"}]}
```
Football seasons rows: `pos`, passing (cmp, att, yds, td, int), rushing (car, yds, td), receiving (rec, tgt, yds, td),
defense (tkl, tfl, sacks, int, pd), `epa` (total), `epa_play`; basketball: `min, pts, reb, ast, stl, blk, tov, fg_pct,
tp_pct, ft_pct, ts, usg, ortg` per game plus `value`.

## Per level and season `data/<L>/<S>/`

`season.json`
```
{"ok","level","season","updated_at","phase","week",
 "format": {...football: conferences with divisions?, cfp: {"teams","auto_bids","byes","rule","verified": bool};
            basketball: ncaa: {"field","at_large","first_four","verified": bool}},
 "conferences": {cid: {"name","short","teams":[tid...]}},
 "teams": {tid: TEAM},
 "standings": {cid: [{"team","w","l","conf_w","conf_l","home":[w,l],"away":[w,l],"neutral":[w,l],"streak","pf","pa",
                      "rank" (AP),"rating_rank","conf_rank"}]},
 "ratings": {tid: RATING},
 "rating_paths": {tid: [[date, rating]]}  (member teams only; weekly for basketball),
 "polls": {"ap": [{"rank","team","points","first","prev"}], "coaches": [...], "cfp": [...] (cfb)} ,
 "power": [{"rank","team","rating","prev_rank"}],
 "sim": {"n_sims","teams": {tid: SIMTEAM}, "notes": [str]} | null,
 "leaders": {stat: [[pid, tid, value]...10]}}
```
RATING (football): `{"rating","off","def","se","rank","games","epa_off","epa_def","sr_off","sr_def","pts_rating","sos","sos_rank"}`
(`rating` = expected margin v an average FBS team on a neutral field, points; `off/def` points per game components).
RATING (basketball): `{"rating","off","def","tempo","se","rank","games","sos","sos_rank","luck"}` (`rating` = adjusted
efficiency margin per 100 possessions; `off`/`def` adjusted points per 100; `tempo` possessions per 40 minutes).
SIMTEAM (football): `{"exp_w","exp_l","w_dist":[...],"p_bowl","p_conf_game","p_conf","p_cfp","p_bye","p_round":{"qf","sf","final","title"},"seed_dist":{seed:p},"p_title","next":{"game","opp","p_win"}|null}`.
SIMTEAM (basketball): `{"exp_w","exp_l","exp_conf_w","exp_conf_l","p_conf_reg","p_conf_tourney","p_ncaa","p_auto","p_at_large","seed_mean","seed_dist":{seed:p},"p_round":{"r32","s16","e8","f4","final","title"},"p_title"}`.

`schedule.json` `{"ok","level","season","updated_at","games":[CARD]}` (every game with a member team, date order).

`cfp.json` (cfb)
```
{"ok","season","updated_at","format": {...},"actual": {"rankings": [...], "bracket": BRACKET}|null,
 "committee_proxy": [{"rank","team","score","p_top12","p_in","p_bye","record","sos_rank","conf_champ_p"}] (top 30),
 "projected_bracket": BRACKET (the modal field and seeding),
 "odds": {tid: {"p_in","p_bye","p_qf","p_sf","p_final","p_title","seed_dist"}},
 "conf_title_games": {cid: [{"team","p_appear","p_win"}]},
 "bowls": {"eligible": {tid: p}, "games": [CARD] (announced bowls)},
 "proxy_fit": {"n_seasons","spearman","top12_overlap","features","weights"}}
```
BRACKET (cfb): `{"seeds": [{"seed","team","auto": bool}], "games": [{"round","slot","home","away","p_home","winner"|null,"gid"|null}]}`.

`bracket.json` (mbb, wbb)
```
{"ok","season","updated_at","field": n,"format": {...},
 "actual": {"regions": {name: [{"seed","team"}]}, "games": [CARD], "first_four": [...]} | null,
 "bracketology": [{"team","seed_mean","seed_mode","p_ncaa","p_auto","p_at_large","conf","record","rating_rank"}] (top 80),
 "projected": {"regions": {name: [{"seed","team","p"}]}, "first_four": [[tid, tid]], "last_in": [tid], "first_out": [tid]},
 "rounds": ["R64","R32","S16","E8","F4","Final","Champion"],
 "odds": {tid: {"p_round": {round: p}, "seed": int|null, "region": str|null}},
 "upsets": [{"round","fav","dog","seed_fav","seed_dog","p_upset","market_p"|null}],
 "conf_tourneys": {cid: {"teams":[{"team","seed","p_win"}],"approximate": bool,"games":[CARD]}},
 "selection_fit": {"n_seasons","at_large_acc","seed_mae","features"}}
```
For a finished season `actual` is filled and `odds` are our pre-tournament probabilities (with results).

`teams.json` (catalogue): `{"ok","metrics":[METRIC],"teams": {tid: {"name","conference","w","l","rating_rank","values":{key:v},"pct":{key:0-100}}}}`.

`teams/<tid>.json` (team page)
```
{"ok","id","level","season","team": TEAM,"record": {...},"rating": RATING,"rating_path": [[date, rating]],
 "rank_history": [[week, ap_rank|null, model_rank]],
 "schedule": [CARD],
 "stats": {key: {"v","pct","rank"}},
 "roster": [{"id","name","pos","class","gp","value","value_pg", ...key stats}],
 "units": [{"unit","grade","pctl","value","evidence"}],          # strengths and needs (football units QB, RB, WR/TE, OL proxy, DL/edge, LB, DB, ST; basketball G/F/C and offense/defense facets)
 "strengths": [UNIT x3], "needs": [UNIT x3],
 "moves": {"in": [MOVE], "out": [MOVE]},                         # inferred transfers into/out of the team for this season
 "odds": SIMTEAM | null,
 "suggestions": [{"need","candidates":[{"id","name","team","value","gain"}]}]}   # portal-style candidates, labelled as model suggestions
```

`players.json` (catalogue): `{"ok","metrics":[METRIC],"positions": {pos: {"label","n"}},"min_floor": {...},
 "players": {pid: {"name","team","pos","class","gp","qualified","values":{key:v},"pct":{key},"pct_pos":{key}}}}`.

`value.json`: `{"ok","currency": {"key","label","desc"},"leaders": [VALUE_ROW] (top 200),"by_position": {pos: [VALUE_ROW] (top 10)}}`
VALUE_ROW `{"id","name","team","pos","class","gp","value","value_pg","pctl","why": str}`.

`moves.json`: `{"ok","season","note","moves": [MOVE],"by_team": {tid: {"in","out","net_value"}},"best": [MOVE],"summary": {...}}`
MOVE `{"player","name","pos","from","to","value_before","value_after"|null,"class","grade"|null}`.

`fantasy.json`: `{"ok","season","scoring": {...},"period": str ("Week 9" / "next 7 days"),"projections": [{"id","name","team","pos","opp","proj","proj_lo","proj_hi","tier"}],
 "rankings": {fmt: [...]},"start_sit": [...],"sleepers": [...],"backtest": {"n","mae","mae_naive","rank_corr","rank_corr_naive"}}`.

`lab.json`: column-oriented `{"ok","fields":[...],"metrics":[METRIC],"rows":[[...]],"kind":"player|team"}` (two files:
`lab_players.json`, `lab_teams.json`).

`games/<gid>.json` (game centre)
```
{"ok","id","level","season", ...CARD fields..., "teams": {tid: TEAM}, "venue","attendance",
 "pregame": {"model": predict output, "market": {...}|null, "espn_predictor": p|null, "elo_p_home"},
 "box": {...as stored, with names: football categories; basketball players rows as objects},
 "team_stats": {tid: {...}},
 "flow": [[t, margin_home]] | null, "wp": {"model": [[t, p]], "espn": [[t, p]]} | null,
 "drives" (cfb): [{"team","period","start","plays","yards","result","epa"}] | null,
 "epa" (cfb): {tid: {"epa_play","sr","pass_epa","rush_epa","explosive"}} | null,
 "plays": top-leverage plays [{"t","period","clock","team","text","wpa"}] | null,
 "leaders": {tid: [{"id","name","line"}]}}
```

## Front end (`docs/campus/`)

Kit-native like Hardwood's `hw-*` sections and Gridiron: `index.html` (data-sport `college`), `assets/qk/` (copied by
the build), `assets/campus.css`, `assets/js/*.js` with a small router `window.CC`. Hash routes, level first:
`#/` (level from state, default by phase: whichever level is in season, cfb in the autumn), `#/<L>`, `#/<L>/games`,
`#/<L>/game/<gid>`, `#/<L>/standings` (tabs: Conferences, Polls, Playoff (cfb) / Bracket (mbb, wbb), Bowls (cfb) /
Conference tournaments), `#/<L>/teams`, `#/<L>/team/<tid>`, `#/<L>/players`, `#/<L>/player/<pid>`, `#/<L>/value`
(Value, By position, Transfers), `#/<L>/fantasy`, `#/<L>/lab`, `#/<L>/model` (Methodology, Calibration, Glossary,
Terms); `?season=S` or `/<S>` suffix for past seasons. Shell: `QK.shell({sport: 'college', sections:
QK.sections('college')...})` with the nine-section IA (Overview · Games · Standings · Teams · Players · Value & Moves ·
Fantasy · Lab · Model), level switch CFB / MBB / WBB (a `QK.seg` in `ctx`, with the season picker), mobile-clean at
375 px, both themes. Disclaimer: unofficial, not affiliated with the NCAA, the CFP, any conference, school, ESPN or a
bookmaker; no logos.
