# The Quant Paddock: payload and front-end contract

Everything the build writes under `docs/paddock/data/` and the site reads. Field
names are a contract between the Python builders and the front-end builders.
Numbers are rounded (probabilities 4 dp, seconds 3 dp, ms integers). Drivers are
keyed by Jolpica `driverId`, teams by `constructorId`, circuits by `circuitId`.
A payload that cannot be built is written with `"ok": false, "reason": "..."`
rather than omitted.

## Site-wide

`data/index.json`
```
{"updated_at", "current_season": 2026, "seasons": [2026, 2025, ... 1950],
 "next": {"year", "round", "name", "circuit": {id, name, country}, "sessions": {fp1, quali, sprint_quali, sprint, race: iso}},
 "last": {"year", "round", "name", "winner": driverId, "date"},
 "drivers": {driverId: {"name", "code", "number", "nationality", "team": constructorId|null}},   # current season
 "teams": {constructorId: {"name", "colour": "#RRGGBB"}},                                         # current season; colour from OpenF1 team_colour, else a palette
 "seasons_meta": {year: {"rounds", "completed", "champion": driverId|null, "constructors_champion": constructorId|null}}}
```
`data/glossary.json` — `{"groups": [{"name", "entries": [{"key","label","desc","fmt","lower","scope"}]}], "model": [{"key","label","desc","group"}]}`
`data/calibration.json` — the backtest output (`models/backtest.py`) plus `{"updated_at", "races", "seasons", "skipped"}`.
`data/markets.json` — `{"updated_at", "drivers_title": TITLE, "constructors_title": TITLE, "next_race": {"year","round","prices": {driverId: p}, "model": {driverId: p}, "sources": [...]}, "h2h": [...]}`
  TITLE = `{"available", "prices": {id: p}, "model": {id: p}, "edge": {id: rel}, "sources": [...], "eliminated": [...], "implied_total"}`
`data/elo.json` — `{"all_time": [{"driver","name","peak_teammate","peak_field","peak_quali","races","years":[a,b]}] (top 200), "current": {driverId: {"elo","elo_teammate","elo_quali"}}}`
`data/hall_of_fame.json` — round 9 (`season.hall_payload`, written by the careers step): `{"ok", "min_starts": 8, "rating", "seasons": [{driver, name, year, team, tm_elo, field_elo, gain, starts, wins, pos, points}] (top 100 by team-mate Elo after the season), "climbs": [same rows, top 100 by the season's gain], "hall": [{driver, name, peak_tm, peak_field, titles, wins, starts, years, teams}] (top 100 by peak team-mate Elo, 20+ starts)}`; about 37 KB.

`data/lab.json` — column-oriented like the football lab: `{"fields": [...], "metrics": [{key,label,group,fmt,lower,desc}], "rows": [[...]] , "windows": {"season": year}}`; fields start `driver, name, team, year, races, age` (round 9: `age` = whole years on 1 July of the season, from the store's date of birth, for the Scouting Room's age band; null when unknown)
  one row per driver-season 2018→ (driverId, name, team, year, races, then every catalogue metric value).

## Per season — `data/<year>/`

`season.json`
```
{"ok", "year", "updated_at", "rounds_total", "rounds_done",
 "calendar": [{"round","name","date","circuit": {id,name,country,locality},"sprint": bool,"status": "done"|"next"|"upcoming",
               "winner","pole","fastest","p_win_top": [[driverId, p] x3]}],
 "standings": {"drivers": [{"pos","driver","team","points","wins","podiums","poles"}], "constructors": [{"pos","team","points","wins"}]},
 "progression": {"drivers": {driverId: [cumulative points after each done round]}, "constructors": {teamId: [...]}},
 "championship": {"drivers": {driverId: {"p_title","exp_points","p05","p95","pos_dist":[...],"magic","clinched","eliminated"}},
                  "constructors": {teamId: {...same}}, "conditional": {...}, "n_sims"} | null for a finished season,
 "title_history": [{"after_round","rounds_done","as_of","n_sims","final"?,                 # 22 Oct 2026: one per completed round
                    "drivers": {driverId: {"p_title","exp_points","p05","p25","p50","p75","p95","points"}}, "constructors": {...same}}],
 "car_pace": {"race": {teamId: [{"round","effect","se"}]}, "quali": {teamId: [...]}},          # % of lap vs field, negative = faster
 "driver_effects": {"race": {driverId: {"effect","se","races"}}, "quali": {...}},
 "car_driver_split": {teamId: {"points","car","drivers": {driverId: pts}}},
 "elo": {driverId: {"elo","elo_teammate","elo_quali"}},
 "teams": {teamId: {"name","colour","drivers": [driverId...]}}}
```
`drivers.json` — the driver catalogue for the season
```
{"metrics": [{"key","label","group","fmt","lower","desc","scope"}],      # ~70 metrics, groups: Results, Qualifying, Race pace, Racecraft, Tyres, Reliability, Telemetry style, Points
 "drivers": {driverId: {"name","team","races","values": {key: v}, "pct": {key: 0-100 field percentile, 100 = best}, "pct_teammate": {key: ...},
                        "log": [{"round","name","grid","pos","status","points","quali_pos","pace","pace_rank","pos_gained","lap1_gain","overtakes","pit_stops","deg"}]}}}
```
Added 22 Oct 2026 (docs/METRICS_SPEC.md, Formula 1): top level `"peer_floor"` (starts to join the peer group: 8 in a finished
season of 16+ rounds, else max(3, min(8, ceil(0.35 x rounds completed)))), `"peer_rule"`, `"peer_count"`; drivers add
`"qualified"` (races >= peer_floor) and `"pct_peer"` (the `pct` formula among the qualifying drivers only; empty below the
floor, so one-race stand-ins neither get nor dilute a percentile). From 1996, `"similar": [{"driver","year","name","team","d"}]`
on qualifying drivers (the 5 nearest driver-seasons, own seasons excluded, by the spec's weighted recipe on the eight headline
metrics; `d` in season standard deviations) and top-level `"similar_method"` (the build's post-pass `drivers.add_similar`).
`season.json` `"title_history"`: the championship simulation's snapshot per completed round (the first build after a
round records it; a later one replaces it only with more simulations); points quantiles give the band. Recording started
22 Oct 2026 (after round 17 of 2026): earlier rounds were never stored, and no look-ahead-free backfill exists.
`teams.json` — `{"metrics": [...], "teams": {teamId: {"name","colour","values","pct","pit": {"median_ms","best_ms","p_under_2500","stops"}, "log": [{"round","points","car_pace","quali_pace","dnfs"}]}}}`
`races/<round>.json` — the race centre
```
{"ok","year","round","name","date","circuit": {...},"status": "done"|"upcoming",
 "forecast": {"pre_quali": SIM, "post_quali": SIM|null, "generated_at"},      # SIM = simulate_race output: drivers{id:{p_win,p_podium,p_points,p_dnf,exp_pos,exp_points,pos_dist}}, teams, p_sc
 "sprint_forecast": SIM|null,
 "results": [{"pos","driver","team","grid","status","points","laps","time_ms","gap_ms","fastest_ms","fastest_rank"}],
 "qualifying": [{"pos","driver","team","q1","q2","q3","gap_ms_to_pole","teammate_gap_ms"}],
 "sprint": [...as results] | null,
 "laps": {"n": total, "positions": {driverId: [pos per lap]}, "gaps": {driverId: [gap to leader s per lap]}, "times": {driverId: [ms per lap]}},
 "stints": {driverId: [{"compound","from","to","age_start"}]},                # 2023→; earlier inferred from pit laps with compound null
 "pits": [{"driver","lap","lane_ms","stop_ms"}],
 "control": [{"lap","t_ms","kind": "SC"|"VSC"|"RED"|"FLAG"|"PENALTY"|"OTHER","message"}],
 "weather": [{"t_ms","air","track","rain","wind"}],
 "overtakes": [{"lap","by","on","pos"}],
 "pace": {"drivers": {driverId: {"pace","se","laps","deg": {compound: v},"traffic_cost"}}, "fuel_coef"},   # race_pace output
 "expected_v_actual": {driverId: {"exp_pos","actual","pctile_of_actual"}},
 "awards": {"driver_of_the_day": AW, "best_drive_from_back": AW, "best_strategy": AW, "fastest_stop": AW, "overtake_of_race": AW, "unluckiest": AW, "smoothest": AW, "team_of_weekend": {"team","value","label"}},  # AW = {"driver","value","label","why"}
 "sessions": {"race": session_key|null, "quali": ..., "sprint": ..., "sprint_quali": ..., "fp1": ..., "fp2": ..., "fp3": ...},
 "telemetry": {"race": bool, "quali": bool}}                                   # whether data/<year>/telemetry/<key>.json exists
```
`circuits.json` — `{circuitId: {"name","country","profile": circuit_profile(...) fields, "history": [{"year","winner","pole","team"}], "records": {...}}}` (also written site-wide as `data/circuits.json` covering all circuits).

`data/drivers/<driverId>.json` — career: `{"name","dob","nationality","seasons": [{"year","team","races","wins","podiums","poles","points","pos"}], "elo": [[year, round, elo, elo_teammate]], "teammates": [{"year","teammate","h2h_quali": [a,b], "h2h_race": [a,b]}], "totals": {...}}`

Telemetry (already produced by `oddsmarkets/f1/telemetry.py`): `data/<year>/telemetry/<session_key>.json`.
OpenF1 raw lap telemetry for any lap can be fetched by the browser: `https://api.openf1.org/v1/car_data?session_key=K&driver_number=N&date>=ISO&date<ISO`
(the lap's ISO window comes from `data/<year>/sessions/<key>.json` laps: `date_start` = session `date_start` + `t_start_ms`).

## Front-end contract (`docs/paddock/`)

Static, no build step, Plotly 2.27 from cdnjs/cdn.plot.ly as the football site does, dark theme. The shell builder writes, FIRST:

- `docs/paddock/index.html` with header (name "The Quant Paddock", tagline, search, season picker, nav: Hub, Season, Races, Drivers, Teams, Circuits, Lab, Compare, Markets, Calibration, Glossary, Methodology), a link to the football site, a `<main id="app">` the router renders into, the footer and disclaimer notice like the football site.
- `assets/js/core.js` defining `window.PD` with: `PD.state {year, route, params}`, `PD.load(path)` (cached fetch of `data/...`, returns Promise of JSON or null), `PD.route(name, renderFn)` registration and hash routing (`#/` hub, `#/season/<y>`, `#/race/<y>/<r>`, `#/race/<y>/<r>/quali`, `#/race/<y>/<r>/telemetry`, `#/driver/<id>`, `#/team/<id>`, `#/circuit/<id>`, `#/lab`, `#/compare/drivers/<a>/<b>`, `#/compare/teams/<a>/<b>`, `#/markets`, `#/calibration`, `#/glossary`, `#/methodology`, `#/disclaimer`, `#/drivers`, `#/teams`, `#/circuits`, `#/races/<y>`), and helpers `esc, num, pct, signed, fmtMs (1:23.456), fmtGap (+0.123), fmtDate, card(title, sub, bodyHtml, id), tableHTML(cols, rows, opts), sortable(el), pctPill(p), statTile(label, value, sub), plot(el, traces, layout), layout(extra), PALETTE, teamColour(teamId), driverLink(id), teamLink(id), circuitLink(id), raceLink(y, r), compoundColour(c)`.
- `assets/js/charts.js` with shared chart helpers (`PD.charts.positionChart`, `gapChart`, `lapTimeViolin`, `stintChart`, `trackMap`, `telemetryOverlay`, `heatTable`).
- `assets/base.css` is copied by the build from `docs/site/assets/style.css` (do not edit it); page styles go in `assets/paddock.css`.

Each other page module registers itself with `PD.route(...)` and never edits core.js. Element ids written by a module are literal `id="..."` strings in its own templates.

## As built: value, swaps, strengths and needs (15 Oct 2026; docs/VALUE_SECTIONS.md)

Built by `oddsmarkets/f1/analytics/value.py` through `build_paddock.value_pages`. Pace in % of a lap, POSITIVE = FASTER
(the decomposition's sign turned).

`data/<year>/value.json` (1994 onward, every season with a decomposition) =
`{"ok", "year", "updated_at", "version", "current", "unit", "driver_cols", "drivers", "team_cols", "teams", "best":
{"pace_tm": [driverId x<=10], "pace_field": [...]}, "min_races": 5, "params" (the decomposition's), "notes"}`.
`driver_cols` = `[id, name, team, races, pace_tm, pace_tm_se, quali_tm, quali_tm_se, pace_field, pct, trend, points,
exp_points, p_title, elo_tm]` (pace_tm = −drv, pace_field = −(latest car + drv), pct among drivers with 5+ races, trend
v last season, exp_points / p_title from the championship (current season)); rows sorted by pace_field.
`team_cols` = `[id, name, car, car_se, car_mean, quali_car, trend, rank, points, p_title]` (car = −latest race-pace
state, trend = change over the last five rounds), sorted by car. About 5 KB.

`data/<year>/swap.json` (current unfinished season) = `{"ok", "year", "updated_at", "version", "n", "remaining":
[[round, "race"|"sprint"]], "lineup": {driverId: constructorId}, "names", "drv_effect": {driverId: % (raw sign)},
"cols", "pairs": {"<a>|<b>": [changes]}, "published": {"n", "drivers": {id: [exp_points, p_title, exp_pos,
current_points]}, "constructors": {id: [exp_points, p_title, current_points]}}, "label"}`. A pair key has the two
driverIds sorted; `cols` = `[a_pts, a_title, a_pos, b_pts, b_title, b_pos, ta_pts, ta_title, tb_pts, tb_title]`: the
change in each driver's expected points, title probability and expected final position, and in the constructors'
expected points and title probability, `ta` = a's original team (which gets b), `tb` = b's. The page shows published +
change. About 19 KB.

`data/<year>/needs.json` (current unfinished season) = `{"ok", "year", "updated_at", "version", "label", "grades":
[[cut, letter]], "swaps_n", "teams": {constructorId: {"name", "areas": [AREA], "balance", "strengths": [AREA x<=3],
"weaknesses": [AREA x<=3], "improve": [{"key", "label", "swaps": [SWAP], "note"}], "best_swaps": [SWAP x<=5]}}}`.
AREA = `{key, label, metric, value, pct, grade, stat}` (keys race_pace, quali_pace, development, reliability, tyres,
pit, strategy, straights, corners, drivers). SWAP = `{in, in_name, out, out_name, from, gain_pts, gain_title,
other_change}` (the team's change in expected constructors' points and title probability with `in` replacing `out`;
`other_change` = the selling team's change). About 45 KB.

## As built: fantasy (16 October 2026; docs/VALUE_SECTIONS.md section 5)

Built by `oddsmarkets/f1/analytics/fantasy.py` through `build_paddock.fantasy_pages` (current season) and the site-wide
step. Our own table (MODELS.md section 10b); no official F1 Fantasy data.

`data/<year>/fantasy.json` (current season) = `{"ok", "year", "updated_at", "version", "label", "projection_ok", "reason",
"n", "next": {"round", "name", "sprint", "quali_known", "sprint_known"}, "driver_cols", "drivers", "comp_cols", "comp",
"team_cols", "teams", "schedule", "history", "picks", "models", "backtest", "scoring", "excluded", "k_form", "names"}`.
`driver_cols` = `[id, name, team, next, p10, p90, p_q3, p_front, p_dnf, p_fl, exp_qpos, gain, ros, ros_p10, ros_p90,
ros_per, rounds_left, form, form_n, last, price, value, value_ros, tier, tier_next, pace_field, pace_rank, form_rank,
car_trend, pace_tm, luck]`: next = expected points next weekend, p10 / p90 its floor and ceiling, p_q3 / p_front the
shares of simulations qualifying top ten / top four, gain the expected places gained, ros the rest-of-season total
(ros_per per round entered), form = season-to-date points per weekend (form_n weekends), last = last season's,
price = the form line `(n form + 3 last) / (n + 3)`, value = next − price, value_ros = ros_per − price, tier (rest of
season) and tier_next, pace_field / car_trend / pace_tm from value.json, luck = championship points minus the
forecasts' expectation (drivers.json `points_v_expected`); rows sorted by next. `comp` = `{driverId: [expected points
per comp_cols item, next weekend]}` with comp_cols = `[quali, race_pos, race_gain, race_fl, race_dnf, overtakes,
sprint_pos, sprint_gain, sprint_fl, sprint_dnf]`. `team_cols` = `[id, name, next, p10, p90, drivers, q_bonus, pit, ros,
ros_p10, ros_p90, ros_per, rounds_left, form, form_n, last, price, value, value_ros, tier, car, car_trend]`.
`schedule` = `{"rounds": [[round, name, sprint]], "drivers": {id: [expected per round]}, "teams": {...}}`; `history` =
`{"rounds": [[round, name]], "drivers": {id: [actual points per completed round or null]}, "teams": {...}}` (constructors
with pit points where they exist). `picks` = `{"top": [PICK x5], "boost": PICK, "value", "differentials", "risers",
"fades", "constructors", "constructor_value"}`, PICK = `{id, proj, ros_per, value, why: [text x<=3]}`. `models` =
`{"overtakes": {coef, mean, races} | null, "pit": {races, field} | null}`. `backtest` = the summary below (drivers_core,
drivers_full, teams_core, teams_full per method, pit). `scoring` = `[[part, item, points, note]]`, `excluded` = `[[what,
why]]`. A season with nothing left to simulate has `projection_ok: false`, the history and no picks. About 24 KB.

`data/fantasy_backtest.json` = `{"ok", "updated_at", "version", "seasons", "races", "n_sims", "full_from", "baselines":
{method: description}, "metrics": {group: {method: {n, races, mae, rmse, bias, spearman, top5, top_pick,
coverage_80 (model)}}}, "pit": {"model"|"std": {n, mae, bias}}, "per_season": {year: {group: {method: ...}}},
"per_race_cols": [year, round, mae, mae_std, spearman, spearman_std], "per_race": [[...]], "label"}`; groups
drivers_core, drivers_full (2024 on), teams_core, teams_full; methods model, std, prev, last (+ blend for drivers). About
33 KB.
