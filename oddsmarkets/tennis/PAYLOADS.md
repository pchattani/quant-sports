# The Quant Ace: payload and front-end contract

Everything `scripts/build_ace.py` writes under `docs/ace/data/` and the site reads. Field names are a contract between the
Python builder (D) and the front-end builders (E, F). Probabilities 4 dp, ratings 1 dp, rates 3 dp. Player ids `pid` and
event ids `"<tid>-<year>"` per CONTRACT.md. A payload that cannot be built is `{"ok": false, "reason"}`. Tour `T` is `atp`|`wta`.
Fractions (fmt `pct`, `prob`) are 0–1.

## Site-wide
`data/index.json`
```
{"updated_at","tours": {T: {"name","year","years":[...],
   "live": [MATCH_CARD], "today": [MATCH_CARD], "recent": [MATCH_CARD] (last 2 days), "upcoming": [MATCH_CARD] (next 2 days),
   "events_now": [{"event","name","level","surface","round_now","favourite":[pid,p]}],
   "elo_top": {"all"|"hard"|"clay"|"grass": [[pid, elo]] x10}, "race_top": [[pid, p_finals, p_no1]] x10}}}
```
MATCH_CARD = `{"id","event","round","date","status","p1","p2","winner","sets","live",
 "model": {"p1","sets_dist_top":[["2-0",p],...3],"exp_games"}, "market": {"p1","sources":[...]} | null,
 "wp_now": p1 live win prob | null}`
`data/glossary.json` (as in Hardwood). `data/<T>/calibration.json` (backtest; committed). `data/<T>/history.json`
`{"events": {tid: {"name","level","surface","champions": [[year, pid, runner_up]]}}}`.
`data/<T>/players_index.json` `{pid: [name, short, country, latest_rank]}` (search; all players with ≥1 tour match since 2000/2007).

## Per tour
- `data/<T>/rankings.json`: `{"date","official": [[rank,pid,points,move]], "elo": [[rank,pid,elo,surface_elos]], "race": [[pid,points]],
  "to_defend": {pid: [[event,week,points]]}}`
- `data/<T>/race.json` (season simulation): `{"n_sims","finals_qual": {pid: p}, "year_end_no1": {pid: p}, "rank_dist": {pid: [p by rank 1..20]},
  "points": {pid: {"mean","p05","p95"}}, "remaining_events": [...], "market": {"finals_qual": TITLE|null, "year_end_no1": TITLE|null}}`
- `data/<T>/elo.json`: `{"current": {pid: {"all","hard","clay","grass","n","rank"}}, "peaks": {"all"|surface: [[pid, elo, date]] top 50},
  "history": {pid: [[date, all, surface_of_match]]}` (top 100 current players only; others in their career file)
- `data/<T>/players.json` (catalogue for the selected year window): `{"year","metrics":[METRIC],"players": {pid: {"name","country","age","rank",
  "matches","qualified","values":{key:v},"pct":{key},"pct_surface":{surface:{key}},"rank_metric":{key}}}}`
  METRIC = `{"key","label","group","fmt":"int|1|2|3|pct|prob|signed","lower":bool,"scope":"all|wta_stats|charted","desc"}` (138: `analytics/players.py` `METRICS`).
- `data/<T>/players/<pid>.json` (career): `{"id","name","country","hand","dob","height","ranks":[[date,rank]],"elo":[[date,all,hard,clay,grass]],
  "serve_return": [[date, surface, s, r, hold, brk, se_s, se_r]], "seasons": [{"year","w","l","titles","finals","by_surface":{...},"hold","brk","elo_end"}],
  "results": [{"match","date","event","round","surface","opp","won","score","p_pre","market_pre"|null}] (latest 2 years; older by year file on demand not needed),
  "splits": {"surface":{...},"level":{...},"round":{...},"opp_band":{...}}, "clutch": {"tb":{w,l,exp},"deciding":{w,l,exp},"from_set_down":{...}},
  "style": charting profile | null, "h2h": [[opp, w, l, last_date]] (top 30 by matches), "to_defend": [...], "odds": {"finals_qual","year_end_no1"}}`
- `data/<T>/<year>/events.json`: `{event_id: {"name","level","surface","indoor","start","end","status","champion","runner_up","draw_size"}}`
- `data/<T>/<year>/schedule.json`: `{"matches":[MATCH_CARD...]}` (all tour-level matches of the year; cards light).
- `data/<T>/events/<event_id>.json` (tournament page): `{"event", "draw": {"rounds":[...], "slots": [...], "matches": {mid: MATCH_CARD}},
  "sim": {"players": {pid: {"p_title","p_final","p_sf","p_qf","reach":{round:p},"exp_points"}}, "n_sims"} | null,
  "market": TITLE | null, "results": [MATCH_CARD], "upsets": [...], "draw_difficulty": {pid: {"exp_opp_elo","rank"}}, "awards": {...},
  "history": [[year, champion, runner_up]]}`
- `data/<T>/matches/<mid>.json` (match centre; kept for the current and previous year):
```
{"id","event","round","date","surface","best_of","status","p1","p2","winner","sets","duration_min",
 "pre": {"model": predict() incl. dist {"p1_win","sets","games","handicap","p_tiebreak","p_straight"}, "elo": {...}, "sr": {"p_srv":[..],"hold":[..]},
         "market": {"p1","sources"}|null, "closing": {"ps":[..],"avg":[..]}|null, "h2h": {"w","l","last":[...]}},
 "wp": [[game_index, set, games_p1, games_p2, p1_wp]] | null, "swings": [...], "excitement", "comeback",
 "stats": {"p1":STATS,"p2":STATS,"by_set":[...]} | null, "inferred": {"hold":[..],"spw":[..]},
 "charting": {...} | null, "awards": {...}}
```
- `data/<T>/lab.json`: column-oriented `{"fields":["id","name","year","matches", ...metric keys],"metrics":[METRIC],"rows":[[...]],"years":[...]}`.
- `data/<T>/markets.json`: `{"updated_at","matches": {mid: {"model","market","edge","sources"}}, "futures": {"events": {event_id: TITLE},
  "finals_qual": TITLE, "year_end_no1": TITLE, "slams_<next season>": {...}}}` (the key is derived from the season, e.g. `slams_2027` in 2026).

## Front-end contract (`docs/ace/`)
Copy the Hardwood shell (`docs/hardwood/index.html`, `assets/js/{core,charts,fx}.js`, `assets/{hardwood,pages,pages-f}.css`) as
`window.TA`, with a tour switch (ATP | WTA) in place of the league switch and a year picker. Name "The Quant Ace", tagline
"Odds, models and analytics for the ATP and WTA tours". Sister-sites group linking the Footballer, Paddock and Hardwood.
Routes: `#/` hub, `#/<T>`, `#/<T>/event/<event_id>`, `#/<T>/match/<mid>`, `#/<T>/player/<pid>`, `#/<T>/players`, `#/<T>/rankings`,
`#/<T>/race`, `#/<T>/elo`, `#/<T>/h2h/<a>/<b>`, `#/<T>/calendar` (events of the year), `#/<T>/lab`, `#/<T>/compare/<a>/<b>`,
`#/<T>/markets`, `#/<T>/calibration`, `#/<T>/value` (`?v=breakout|luck|over|surface|market|validation`), `#/glossary`,
`#/methodology`, `#/disclaimer`. Disclaimer: no affiliation with the ATP,
WTA, ITF, tournaments, ESPN or bookmakers; no logos; Match Charting Project data CC BY-NC-SA 4.0 (attribution + link), derived
style data shared alike; tennis-data.co.uk credited for results and odds. First-visit notice key `qa-notice-v1`.


## As built (builder D): exact shapes where they differ from or add to the above

Every per-tour payload also carries `"ok": true, "tour", "updated_at"` unless noted; a failed payload is `{"ok": false, "reason"}`.

**File names.** `players/<id>.json` and `matches/<id>.json` use the id with `:` replaced by `_`
(`x:alena-kovackova` → `players/x_alena-kovackova.json`); ids inside payloads keep the colon.

**Which pages exist.** Match pages: tour-level main-draw matches (levels slam, finals, m1000, 500, 250, other; no Q rounds)
of the last `--match-page-years` (2) years. Event pages: tour-level events of the last `--event-page-years` (3) years
(`<year>/events.json` rows say `"page": bool`). Careers: every player with a finished match on disk.

**TITLE** (a market field, `sources/markets.py` `assemble()`): `{"available": bool, "reason": str|null, "probs": {pid: p}
(de-vigged, only when available), "sources": ["kalshi","polymarket"], "by_source": {source: {pid: mid}}, "implied_total",
"overround", "markets": {source: ticker|slug}, "kind", "field", "quoted", "unmatched": [labels], "event"?, "label"?}`.
A thin field is `available: false` with the reason and still lists `by_source` mids. **BINARY** (per-player yes markets:
`finals_qual`, `top10`, `slams_<next season>`): `{"available","probs": {pid: mean mid, not de-vigged},"by_source","implied_total",...}`.

**MATCH_CARD** adds `"n": [short1, short2]`; `market` = `{"p1","sources": [names],"basis"}` | null. Schedule cards are light
(`model` = `{"p1"}`; before the page window the p is Elo's). Cards in an event page's `draw.matches` add
`"node": [round_index, node_index]` (round 0 = `draw.rounds[0]`; node k of round r covers first-round slots
k·2^(r+1) … (k+1)·2^(r+1)−1, 0-based).

**index.json** tour entry adds `"names": {pid: short}`; `race_top` rows are `[pid, p_finals, p_no1, race_points]`;
`events_now` items add `start`, `end`; `favourite` is `[pid, p_title]` | null.

**Wrapped files.** `players_index.json` = `{"ok","tour","updated_at","players": {pid: [name, short, country, latest_rank]}}`;
`<year>/events.json` = `{"ok","tour","year","updated_at","events": {event_id: {name, tid, level, surface, indoor, start, end,
status, champion, runner_up, draw_size, city, country, n_matches, page}}}`; `<year>/schedule.json` = `{..., "matches": [...]}`.

**rankings.json**: `official` rows `[rank, pid, points, move]` (move = previous rank − rank, against `"previous": {"date",
"ranks": {pid: rank}}`, the last snapshot the build saw; null until a new snapshot arrives); `elo` rows
`[rank, pid, elo_all, {"hard","clay","grass"}]` (active: a rated match in the last year, ≥ 10 rated); `race` rows
`[pid, points]`; `to_defend`: `{pid: [[event_id_last_season, drop_date, points]]}` (drop_date = the Monday on or after the
event's end + 364 days; only events still inside the 52 weeks); adds `"source"`, `"notes"`.

**race.json** adds `"race": {pid: {"now","mean","p05","p95"}}`, `"finals_title": {pid: p}`, `"rank_dist_labels"`
(`[1..20, "21+"]`, the 21 entries of each `rank_dist` row), `"simplifications": [str]`, `"basis"`, `"snapshot"`, `"as_of"`;
`points` rows add `"now"`; `remaining_events` are `{"id","name","level","start","surface","method","draw_size"}` (events taken
from last season's calendar carry last season's name and start + 364 days); `market` = `{"finals_qual": BINARY,
"year_end_no1": TITLE, "finals_winner": TITLE, "top10": BINARY}` (each may be null).

**elo.json**: `history` rows are `[date, all, surface]` (surface = the match's surface string), last 5 years, top 100 current
players; adds `"params"` (Elo constants), `"as_of"`, `"history_from"`.

**players.json** (also `data/<T>/<year>/players.json` per year; `data/<T>/players.json` = the current year): top level adds
`"floor"` (matches to be `qualified`, scaled to the share of the season played, min 8) and `"surface_floor"`
(`{"hard":10,"clay":8,"grass":5}`: matches on a surface to enter that surface's reference pool); rows add `"short"` and
`"values_surface": {surface: {key: v}}` (the surface-capable keys only; written for surfaces with at least half the surface
floor, as is `pct_surface`). `rank_metric` = rank among qualified players. 138 metrics (`analytics/players.py` `METRICS`); every METRIC has `desc`.

**lab.json**: `fields` = `["id","name","year","qualified","rank", ...metric keys]` (`matches` once, among the metric keys;
rows with ≥ 10 matches); `"surface": {"fields": ["id","year","surface","matches", ...surface keys], "rows": [...],
"min_matches": 5}` (player-season × surface).

**model.json** (new, per tour): `{"as_of","elo": {"w_surf","bo5","mean","params","version","formula"},"blend": {"w_elo","w_sr",
"sigma","fitted","version","formula"},"serve_return": {"base": {"mu","clay","grass","indoor","bo5","level": {lv: x},"new_s",
"new_r","k_hold","k_spw",...},"through","version","formula"},"final_set_rules": {"default","slams": {tid: rule},"levels": {lv:
rule}},"best_of": {"slam","other"},"base_spw": {surface: p},"chain_rules": [...]}`. Player s / r per surface: the latest
`serve_return` row per surface in the career file; Elo ratings: `elo.json` `current`.

**markets.json**: match rows `{"p1","p2","n","event","round","date","status","model","market","edge","sources","basis"}` for
open tour-level matches within 3 days; `futures` = `{"events": {event_id: TITLE},"finals_qual","year_end_no1","finals_winner",
"top10","slams_<next season>"}`; adds `"model": {"events": {event_id: {pid: p_title}},"finals_qual","year_end_no1","finals_title"}`.

**calibration.json**: builder C's backtest page copy (`backtest.page_copy`; the newer of the committed file and the cache);
`{"ok": false, "reason"}` until the backtest has run. WTA adds `"validation_stats"` = B's `serve_return.validate_stats` on the
completed seasons with WTA stats (`{"in_sample","out_of_sample","years","offsets",...}`). The ATP has no real stats, so no
validation block.

**Match centre** adds `names {pid: name}`, `event_name`, `level`, `indoor`, `final_set_rule`, `ranks [r1, r2]`, `score`,
`live`, `wp_reconstructed`, `style_charted [bool, bool]`, `sources`. `pre.model` = `{"p1_win","p_srv","elo_p","sr_p","blend_w",
"basis","as_of" (the fit's checkpoint date),"version","dist": {"p1_win","sets": {"2-0": p},"games": {n: p},"handicap": {k: p},
"p_tiebreak","p_straight","exp_games","best_of","final_set_rule"}}`; `pre.elo` = `{"p","p1": {"all","surface"},"p2": {...},
"surface"}` (ratings before the match); `pre.sr` = `{"p_srv": [..],"hold": [calibrated],"spw": [calibrated]}`; `pre.h2h` =
`{"w","l","last": [[date, event, round, winner_pid, score from p1's view]]}` (before this match, newest first, 5);
`pre.closing` = `{"ps","avg","max","b365": decimal pairs [p1, p2],"p1": de-vigged Pinnacle (else average)}` | null;
`wp` rows `[game_index, set, games_p1, games_p2, p1_wp]` (game_index 0 = pre-match; the last row of a finished match is 0/1);
`swings` = `[{"i","set","sets","games","kind","winner": 0|1,"delta"}]`; `comeback` = `{"winner": 0|1,"min_p","at","sets","games"}`;
`awards` = `{"upset": {"winner","p"},"comeback": {"winner","min_p","sets","games"},"dominant": {"winner","games_share"},
"tiebreaks": [{"set","winner","p1_exp"}]}` (each key only when it applies); `charting` null (per-match charting is not
published; the career `style` profile is).

**Event page** adds `"qualifying": [cards]`, `"names": {pid: short}`; `event` adds `id`, `runner_up`, `round_now`; `draw` adds
`size`, `source` ("wta" | "reconstructed" | "results"), `complete`; draw slots whose player the source left out (seeds with
a bye) are filled from later-round matches (`filled_from_results` on the store draw). `upsets` =
`[{"match","round","winner","loser","p" (winner's pre-match p),"score","basis": "model"|"elo"}]` (p < 0.4, 10 at most);
`awards` = `{"player": {"pid","wins_over_exp"},"dominant": {"pid","games_share","wins"},"clutch": {"pid","tb_w","tb_l"}}`;
`draw_difficulty` = `{pid: {"exp_opp_elo","rank"}}` (rank 1 = hardest); `sim.players[pid]` may add `"next"` (C's
interventional next-match odds); `sim` adds `"format"`, `"matches"`, `"rounds"`.

**Career file** adds `"short"`, `"results_all": [[date, event, round, surface, opp, won (1|0), score]]` (every finished match
of every level and year, oldest first: the H2H page needs only the two career files), and `"current": {"rank","points","race",
"to_defend","elo": {"all","hard","clay","grass"},"elo_rank","hold","brk","age"}`. `seasons[]` rows are `{"year","w","l","titles",
"finals","by_surface": {surface: [w, l]},"hold","brk","elo_end"}` (tour-level main draw); `results` rows add `level`, `status`;
`clutch.*` = `{"w","l","exp" (expected wins),"exp_pct"}`; `serve_return` rows `[season_end_date, "all"|surface, s, r, hold, brk,
se_s, se_r]`; `elo` rows `[date, all, hard, clay, grass]` (last value per week); `ranks` `[[week_monday|snapshot_date, rank]]`.


### The Value section (`analytics/value.py`, added 15 October 2026)

Written by `build_ace.py` (`value`) for the current year of a full build; read by `docs/ace/assets/js/value.js`
(`#/<T>/value`) and the player page's Value card. Both are `{"ok": false, "reason"}` when the step fails.

`data/<T>/value.json` (about 0.3 MB ATP, 0.36 MB WTA):
```
{"ok","tour","updated_at","as_of" (today),"version","universe": 150,"model_asof" (the quarter whose closed windows trained it),
 "breakout": {"rows": [BREAKOUT] (the official top 150, best predicted 12-month change first),
              "base_rise": {"12m","6m"}, "base_fall": {...}, "features": [{"key","label","desc"}],
              "test": {"12m"|"6m": {"rho": [est, lo, hi], "rho_rank_only", "rho_rank_model", "rho_elo": [..],
                                    "risers": {"hit","base","lift","n","recall"}, "fallers": {...}, "n_obs", "years"}},
              "rise_def": {"log", "places"}, "fall_def"},
 "luck": {"rows": [{"pid", "52w": LUCK, "season": LUCK}] (10+ tour-level matches in the window; most wins above expectation
          first), "params": {"k_games_bo3","k_games_bo5","k_points","bp_save_offset","bp_conv_offset","n_games_fit"},
          "min_matches": 10, "windows": {"52w": [from, to], "season": [from, to]}},
 "value": {"rows": [VALUE] (active players ranked inside 200 or model rank inside 120, by model rank), "offset" (display
           constant), "beta" (d logit P / d(s + r)), "weights": {"w_elo","w_sr","w_gelo"}},
 "market": {"rows": [MARKET] (5+ priced matches), "summary": {"n","ll_model","ll_market","sources": {"ps"|"bfe"|"avg": n},
            "kalshi_n","kalshi_ll_model","kalshi_ll_market","kalshi_cache"}, "window": [from, to]}}
```
BREAKOUT = `{"pid","rank","pts","age","imp" (rank the model implies),"n12","tl12","idle" (days),"d_elo" (6 months),"d_rank"
(log, 6 months),"held" (tour-level points in the ranking),"drop6m","drop12m" (points dropping within the horizon),"luck","draw"
(wins over 12 months),"mk" (market v Elo, Elo points), and per horizon h in 12m / 6m: "y<h>" (predicted log-rank change),
"r<h>","lo<h>","hi<h>" (predicted rank, 10th-90th percentile),"p_rise<h>" (null in the top 10),"p_fall<h>","elo<h>" (predicted
Elo change),"exp_earn<h>" (mean tour-level points earned at the implied rank),"why<h>": [[feature, contribution]]}` (contribution
in log-rank units, negative = towards a better rank; the age terms are grouped as "age").

LUCK = `{"n","w","l","win_pct","n_done","exp_games","close","n_stats","exp_points","conv","draw","sos","free","wo_rec",
"ret_rec","games_share","points_share","total","adj_win_pct", "tb": {"w","l","exp","over"}, "dec": {...}}` plus, where WTA
statistics exist, `"bp_saved","bp_faced","bp_saved_exp","bp_saved_over","bp_conv","bp_opps","bp_conv_exp","bp_conv_over"`.
`total` = close + draw + free (conv is shown but not counted); `sos` is centred on the window's players.

VALUE = `{"pid","rank","pts","R" (model rating),"mrank","imp","gap" (log rank - log implied),"pts_imp","elo","elo_rank","g_rank",
"sr_rank","age","surf": {surface: [rating, rank, rated matches on it in 3 years]}}`.

MARKET = `{"pid","n","w","x_model","x_market","model","market" (mean probabilities),"gap" (Elo points, + = the market rates the
player higher),"ll_model","ll_market","k_n","k_w","k_gap","k_model","k_market"}` (k_ = Kalshi quotes ~4 h before the start).

`data/<T>/value_validation.json` (about 28 KB): `{"ok","tour","updated_at","version","asof","tuned": {"k_shrink","lam","grid",
"dev_rho"},"validation": {"12m"|"6m": {"per_year": {year: BLOCK},"pooled": {"dev"|"test": BLOCK + "years"},"recent":
[{"t","risers": [[pid, rank, pred, actual|null]],"fallers": [...]}]}},"coefficients": {"12m"|"6m": {"rank": [[feature, b]],"elo":
[[feature, b]],"n","resid": {band: [p10,p25,p50,p75,p90]},"base_rise","base_fall"}},"drop_one": {"12m"|"6m": [[feature, d_rho]]},
"earn_bins": {"12m"|"6m": [[implied rank upper bound, mean points, n]]},"age_curve": [[age, n, mean, lo, hi, mean Elo change]],
"luck_evidence": {"pairs","min_matches","years","correlations": [{"key","label","kind" (luck|skill|schedule|structural),"n","r",
"lo","hi"}],"prediction": [{"key" (raw|pythagorean|luck_adjusted|adjusted_minus_raw),"n","r","lo","hi","rmse_wf","n_wf"}]},
"luck_params","panel": {"rows","snapshots","first","last","sr_fits","dropped"},"features","definitions": {...}}`.
BLOCK = `{"n","n_obs","rho": [est, lo, hi],"rho_elo","rho_rank_only","d_rank_only": [..],"rho_rank_model","d_rank_model",
"risers","fallers","brier_rise": [model, base],"brier_fall"}`.

Input added with it: `data/<T>/bio.json` (`scripts/tn_bio.py`, committed like `style.json`): `{"_meta", pid: {"dob","espn","checked"}}`,
dates of birth from ESPN's core athlete API; `TourData.players` fills a missing `dob` from it (so the catalogue's `age` is now
filled for the ATP too).

The cached part (the snapshot panel, the walk-forward validation, the final models) lives in `ACE_CACHE/ace_value/<T>_history.json`,
keyed on the quarter, the completed years' stores, the fits, `bio.json`, the backtest's serve/return fits and this module's
source: it is rebuilt once a quarter (about 1-2 minutes a tour) and whenever the code changes. Kalshi quotes are cached in
`ace_value/<T>_kalshi.json` from the research cache (`data/edge/cache/kalshi`).
