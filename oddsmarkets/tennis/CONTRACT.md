# The Quant Ace: data and model contract

Every builder codes to these shapes. Tours are `"atp"` and `"wta"`; singles only. Years are
calendar years. Player ids `pid` are canonical strings from `canon.py` (ESPN athlete id when known,
else `"x:<slug>"`), tournament ids `tid` are canonical slugs (`"wimbledon"`, `"indian-wells"`, …),
an event is `"<tid>-<year>"`. Surfaces: `hard`, `clay`, `grass`, `carpet`; `indoor` is a separate flag.
Levels: `slam`, `finals`, `m1000` (ATP Masters / WTA 1000), `500`, `250`, `other` (Olympics, United Cup,
Davis/BJK Cup), `ch` (Challenger / WTA 125, ratings only), `q` (qualifying, ratings only).
Numpy/scipy/pandas/requests only, plus `openpyxl` (added to pyproject) for tennis-data xlsx and `xlrd`
(added by builder A) for tennis-data's 2000-2012 `.xls` workbooks.
No network in tests.

## 1. Data (builder A)

`oddsmarkets/tennis/store.py`: `docs/ace/data/<tour>/<year>/store.json`
```
{"tour","year","updated_at",
 "players": {pid: {"name","short","country","hand"|null,"dob"|null,"height"|null,"espn":id|null,"wta":id|null,"aliases":[...]}},
 "events": {event_id: {"tid","name","year","start","end","level","surface","indoor","draw_size","best_of","city","country",
                       "espn":id|null,"wta":id|null,"status":"upcoming|live|done","champion":pid|null,"draw": DRAW|null}},
 "matches": {mid: MATCH},
 "rankings": {"date": iso, "rows": [[rank, pid, points]], "source": "espn|wta"},   # latest official snapshot
 "meta": {"sources": {...}, "fetched": {...}}}
```
MATCH (one per singles match, the union of sources; `mid` = `"<event_id>-<round>-<pidA>-<pidB>"` with pids sorted):
```
{"id","event","date": iso|null,"round":"R128|R64|R32|R16|QF|SF|F|RR|Q1|Q2|Q3|BR","best_of":3|5,"surface","indoor","level",
 "p1": pid,"p2": pid,                 # p1 = winner once finished; for upcoming, ESPN/draw order
 "winner": pid|null,"status":"upcoming|live|done|ret|wo|def",
 "sets": [[g1, g2, tb1|null, tb2|null]],   # games per set from p1's view; tb points for 7-6 sets when known
 "final_set_rule": "adv|tb7|tb10",          # how a deciding set ends (by event/year rules)
 "rank1","rank2","pts1","pts2",
 "odds": {"ps":[o1,o2],"b365":[..],"avg":[..],"max":[..],"bfe":[..]} | null,     # decimal, closing (tennis-data)
 "stats": {"p1": STATS, "p2": STATS, "by_set": [...]} | null,                     # WTA API only
 "live": {"set","games":[g1,g2],"points":[..]|null,"server":pid|null} | null,
 "sources": ["td","espn","wta"], "duration_min": int|null}
```
Optional MATCH keys (builder A): `"final_set_tb_at": 12` when the deciding-set tiebreak is not at 6-6 (Wimbledon
2019-2021: tb7 at 12-12; absent otherwise); `"seeds": [s1, s2]` and `"entries": [e1, e2]` ("Q","WC","LL","PR") when a
source gives them (WTA API).
STATS = `{"aces","dfs","sv_pts","fs_in","fs_won","ss_won","sv_gms","bp_saved","bp_faced","rt_pts_won","bp_conv","bp_opps"}` (null when absent).
DRAW = `{"size","slots":[[slot, pid|null, seed|null, entry("Q","WC","LL","PR")|null]]}` — round-1 bracket order; later rounds implied.
DRAW also carries `"source": "wta"` (the WTA draw endpoint: seeds and entry types) or `"reconstructed"` (ATP and
Slams: rebuilt from played matches, seeds/entries null) and `"complete"` (false while unplayed rounds leave
first-round blocks unlinked; such blocks are appended in date order).

Sources (`oddsmarkets/tennis/sources/`): `tennisdata.py` (prefix from alldata.php, yearly xlsx → MATCH rows with odds),
`espn.py` (scoreboard by day/year, rankings; live state), `wta.py` (calendar, draws, matches, per-match stats, rankings),
`charting.py` (Match Charting Project → per-point records → per-player style tables), each a paced client that never raises.
`canon.py`: identity resolution across sources (name folding, initials "Sinner J.", within-event matching first), tournament
table (tid, level, surface, indoor, points tables per level and round, best-of and final-set rules by year), `overrides.json`.

Charting outputs (committed): `docs/ace/data/<tour>/style.json` → `{pid: {"matches","points", metrics...}}` plus one
`"_meta"` key (licence CC BY-NC-SA 4.0, attribution, source, counts); consumers skip keys starting with `_`.
Identity registry (committed, builder A): `docs/ace/data/<tour>/registry.json` → `{"players": {pid: {...,"aliases"}},
"redirects": {old_pid: pid}}`; `store.load(tour, year, canon.Registry.load(tour))` applies the redirects.

## 2. Models (builders B and C): `oddsmarkets/tennis/models/`

Common: pure functions on in-memory inputs + cached `for_tour(tour, through=None)`; caches under `data/tennis/cache/`
(env `ACE_CACHE`); data root env `ACE_DATA` (default `docs/ace/data`); committed fits in `models/fitted/` used when the
cache is empty (CI). Every fitted object carries `version`.

Builder B
- `elo.py`: `history(tour) -> rows`, `ratings_at(hist, date) -> {pid: {"all","hard","clay","grass","n"}}`,
  `p_win(r1, r2, surface, best_of, params)`; K(n) decay, surface blend weight, best-of-5 scaling, inactivity decay — all in `params`, fitted.
- `serve_return.py`:
  `set_score_probs(h1, h2, first_server, rule, p_srv1=None, p_srv2=None) -> {(g1,g2): p}` (exact DP; with tiebreak);
  `fit(matches, through, half_life_days, ridge, prior=None) -> {"players": {pid: {surface: {"s","r","se_s","se_r","n"}}}, "base": {...}, "version"}`;
  `hold_prob(model, server, returner, surface, level, best_of) -> h`; `point_prob_from_hold(h) -> p` (inverse of the game formula);
  WTA point layer: `fit(..., stats=True)` adds binomial terms for serve/return points won.
  Also: `game_hold(p)` (the game formula), `serve_point_probs(model, p1, p2, surface, level, best_of) -> (p1_srv, p2_srv)`,
  `for_tour(tour, through=None)` (cached fit with the tour's tuned constants; committed `fitted/serve_return_<tour>.json` when
  no stores), `export_fits(tour)` (writes `fitted/serve_return_<tour>.json`; `elo.export_fits` writes `fitted/elo_params_<tour>.json`).
  Player records carry `"all"` plus each surface; hold/break/spw/rpw there are v the average tour-level opponent.
- `bt.py`: time-decayed Bradley-Terry via `oddsmarkets/common/ranking.py`.

Builder C
- `match_chain.py`: exact Markov chain. `game_win(p)`, `tiebreak_win(p1, p2, to=7)`, `set_dist(p1, p2, first_server, rule)`,
  `match(p1, p2, best_of, final_set_rule, state=None) -> {"p1_win","sets": {"2-0":p,...},"games": {n: p},"handicap": {k: p},"p_tiebreak","p_straight"}`;
  `state` = current score for live win probability: `{"sets":[s1,s2],"games":[g1,g2],"points":[a,b]|None,"server":0|1|None,"played":[[g1,g2],...]|None}`
  (0 = p1); rules also "tb12" (= "tb7@12", Wimbledon 2019-21); `handicap` key = p1 games minus p2 games. `LiveTable(p1, p2, best_of, rule).p(sets, games, server, points)`.
- `predict.py`: `predict(tour, p1, p2, surface, best_of, date, level) -> {"p1_win", "p_srv": [p1,p2], "elo_p", "sr_p", "blend_w", "dist": match(...)}` (blend fitted);
  `context(tour, date)`, `predict_many(ctx, rows)`, `prob_matrix(ctx, pids, surface, best_of, level, rule)`; weights in `models/fitted/predict_<tour>.json`.
- `live.py`: win-probability path per game from the live/finished score; leverage; excitement; comeback.
  `path(match, p_srv, sequence=None) / for_match(match, ctx=None, tour=None) -> {"steps": [{"i","set","sets","games","server","kind","winner","p1","delta","leverage"}], "p_pre","excitement","comeback","swings","set_path","reconstructed"}`.
- `tournament_sim.py`: `simulate(event, n=20000, matches=None, tour=None, ctx=None) -> {"players": {pid: {"p_title","p_final","p_sf","p_qf","reach": {round: p},"exp_points","next"}}, "matches": {...}}`
  (`matches` = the event's MATCH rows, results fixed; `next` = interventional next-match odds `{"p_win","opponents","if_win","if_loss"}`; Finals: `format` "round_robin", `event["groups"]` optional).
- `season_sim.py`: rest-of-season simulation → `{"year_end_no1": {pid: p}, "finals_qual": {pid: p}, "rank_dist": {pid: [...]}, "points": {pid: {"mean","p05","p95"}}}`
  via `for_tour(tour, as_of=None, n=10000)` (also "race", "finals_title", "events", "simplifications", "basis").
- `backtest.py`: walk-forward 2010→ per tour; log-loss/Brier v Pinnacle closing (`odds.ps`, de-vigged), avg odds, rank and Elo baselines;
  set-score and total-games calibration; tournament checkpoints; validation of inferred hold/SPW v WTA real stats.

## 3. Markets (builder C): `oddsmarkets/tennis/sources/markets.py`
On the `basketball/sources/markets.py` template with `common.prediction_markets`: Kalshi `KXATPMATCH`/`KXWTAMATCH` (match),
`KXATP`/`KXWTA` (tournament winners), `KXATP1RANK`/`KXWTA1RANK`, Finals qualification; Polymarket tag `tennis` (match winners,
tournament winners, "Player to Qualify", year-end No. 1/top 10). `match_prices(tour, date) -> {mid: {"p1","sources","bookmakers","basis"}}`,
`futures(tour) -> {"tournaments": {event_id: TITLE}, "finals_winner", "year_end_no1": TITLE, "finals_qual"/"top10"/"slam_next_year": BINARY}`
(BINARY = per-player yes prices `{"probs": {pid: p}, "implied_total", ...}`, not de-vigged).
