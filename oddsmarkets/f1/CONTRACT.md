# F1 models: the interface contract

Shared by everyone building `oddsmarkets/f1/`. Python 3.11, numpy/pandas/scipy
available (see pyproject.toml). Run Python with the project's virtual environment (`uv run python`).
Tests go in `tests/f1/`, offline (no network), with small synthetic fixtures.

## Data you read (never write these from model code)

**Season store** — `oddsmarkets.f1.store.load(year)` → dict (see `oddsmarkets/f1/store.py`):
- `races[str(round)]`: `name, date, time, circuit{id,name,locality,country,lat,long}, sessions{fp1,quali,sprint,...: iso}`,
  `results[]` (`driver, constructor, number, grid, position, position_text, points, laps, status, time_ms, fastest_rank, fastest_lap, fastest_ms`),
  `qualifying[]` (`driver, constructor, number, position, q1, q2, q3` in ms), `sprint[]` (as results), `pitstops[]` (`driver, stop, lap, duration_ms`),
  `laps{driverId: [ms per lap, None if missing]}`, `positions{driverId: [position per lap]}`.
- `drivers{driverId: {code, number, given, family, dob, nationality}}`, `constructors{constructorId: {name, nationality}}`.
- Coverage: results 1950→, qualifying ~1994→ (q1/q2/q3 from 2006), sprint 2021→, pit stops 2011→, laps 1996→. Being backfilled now
  (newest seasons first); 2026 results and qualifying are complete through round 15.
- `grid == 0` means pit-lane start. `status` distinguishes "Finished", "+1 Lap", and retirements ("Engine", "Collision", "Accident"...).
  Treat "Disqualified" as not classified. Points include fastest-lap and sprint points as awarded that year.

**OpenF1 session record** (2023→) — `json.load(open(oddsmarkets.f1.sources.openf1.session_path(year, session_key)))`:
- `session{session_key, meeting_key, session_name, session_type ("Race"/"Qualifying"/"Practice"), date_start, date_end, circuit_short_name, country_name, year}`
- `drivers{str(number): {name_acronym, full_name, team_name, team_colour, ...}}`
- `laps{str(number): [[lap, t_start_ms, lap_ms, s1_ms, s2_ms, s3_ms, i1_kph, i2_kph, speedtrap_kph, pit_out(0/1)], ...]}` (times from session start)
- `lap_end{str(number): [[lap, gap_to_leader, interval], ...]}` (race only; gaps in seconds, may be strings like "+1 LAP")
- `stints[[driver_number, stint, lap_start, lap_end, compound, tyre_age_at_start]]`
- `pit[[driver_number, lap, t_ms, lane_ms, stop_ms]]`
- `race_control[[t_ms, lap, category, flag, scope, sector, driver_number, message]]` (SC: category "SafetyCar"; VSC in message; flags "YELLOW", "RED", "GREEN", "CHEQUERED"...)
- `weather[[t_ms, air_c, track_c, humidity, rainfall(0/1), wind_speed, wind_dir, pressure]]`
- `overtakes[[t_ms, overtaking_number, overtaken_number, position]]`, `result[{position, driver_number, dnf, dns, dsq, ...}]`, `positions{number: [[t_ms, pos]]}`
- The list of sessions on disk: `docs/paddock/data/<year>/sessions/*.json`.

**Telemetry** (2023→): `oddsmarkets.f1.sources.openf1.load_telemetry(year, session_key, driver_number)` →
`{"car": {t, speed, rpm, gear, throttle, brake, drs}, "loc": {t, x, y, z}}` column arrays, t in ms from session start.

**Network:** do not call Jolpica (a detached backfill is using the IP's 500/hour). Do not call OpenF1 from tests.

## Identity

`oddsmarkets/f1/canon.py` (Builder A owns it): `driver_for_number(year, number) -> driverId | None` built from the season
store's results/qualifying `number` field (per season; a number can change hands across seasons); `team_for(year, round, driverId) -> constructorId`.
Everything downstream keys drivers by Jolpica `driverId` and teams by `constructorId`.

## Model outputs (the contract between builders)

**Builder A — pace** (`models/laptime.py`, `models/decomposition.py`, `models/qualifying.py`):
- `race_pace(year, round) -> dict` → `{"drivers": {driverId: {"pace": s_per_lap_vs_field (negative = faster), "se": float, "laps": n_clean,
   "deg": {compound: s_per_lap_per_lap_of_age}, "traffic_cost": s}}, "fuel_coef": s_per_kg_or_lap, "excluded": {...counts}}`
  (2018→ from Jolpica laps, richer with OpenF1 stints/compounds/pit-out flags 2023→; from 1996 a coarser version without compounds).
- `season_effects(year, upto_round=None) -> dict` → `{"car": {constructorId: [{"round", "effect", "se"}]}, "driver": {driverId: {"effect", "se", "races"}},
   "quali_car": {...same shape}, "quali_driver": {...}}`: car = team pace by race (random walk), driver = within-team effect shrunk to 0.
- `quali_model(year, round, n_sims=20000) -> dict` → `{"drivers": {driverId: {"mu_gap_pct", "sd", "p_pole", "grid_dist": [p(P1)...p(P22)]}}}`
  using effects through the previous round (pre-qualifying forecast).

**Builder B — simulation** (`models/race_sim.py`, `models/championship.py`, `models/backtest.py`):
- Inputs through a dataclass `RaceInputs(year, round, drivers: list[driverId], team: dict, pace_mu: dict, pace_sd: dict, grid: dict|None,
   dnf_hazard: dict (per lap), circuit: dict(overtake_difficulty, sc_rate_per_lap, pit_loss_s, laps, typical_stops), wet: bool)`.
  `race_inputs(year, round, before_quali: bool) -> RaceInputs` assembles them from A's outputs when available and falls back to a
  results-only estimator (recent finishing positions → pace) so B can be built and tested before A lands.
- `simulate_race(inp, n=20000, seed) -> dict` → `{"drivers": {driverId: {"p_win","p_podium","p_points","p_dnf","exp_pos","exp_points","pos_dist":[...] }},
   "teams": {constructorId: {"exp_points","p_double_points"}}, "p_sc": float}`.
- `simulate_championship(year, n=20000, seed) -> dict` → drivers' and constructors' title probabilities, final position distributions,
   expected points, points quantiles, per-remaining-round expected points.
- `backtest(seasons=[2023,2024,2025,2026]) -> dict`: walk-forward (each race predicted with data strictly before it) log-loss and Brier for
   win/podium/points/DNF, reliability bins, against baselines `grid_order` (post-quali), `previous_results` (pre-quali), Elo-only (from C).

**Builder C — ratings and markets** (`models/elo.py`, `oddsmarkets/common/ranking.py`, `oddsmarkets/common/markets.py`,
`oddsmarkets/common/prediction_markets.py`, `oddsmarkets/f1/sources/markets.py`):
- `elo_history(seasons=range(1950, 2027)) -> dict` → per race per driver `{"elo", "elo_teammate"}`, current ratings, peaks; field Elo on finishing order
  (multi-competitor pairwise update), teammate Elo on head-to-heads only. Also qualifying Elo.
- `ranking.py`: Plackett-Luce fit/sample (lift the fit from `scripts/fit_ballon_dor.py`) used as B's cross-check.
- `common/markets.py` and `common/prediction_markets.py`: re-export the football implementations (`oddsmarkets/football/core/markets.py`,
  `oddsmarkets/football/sources/prediction_markets.py`) without changing football behaviour; sport-neutral helpers (`_mid`, `fold`, `best_match`,
  Kalshi/Polymarket event fetchers taking a series/slug) importable from `oddsmarkets.common`.
- `f1/sources/markets.py`: `title_prices(kind="drivers"|"constructors")`, `race_winner_prices(year, round)`, `h2h_prices()` from Kalshi
  (`KXF1` and any F1 race/constructor series you find) and Polymarket (`2026-f1-drivers-champion`, race-winner events), mapped to driverId/
  constructorId with `best_match`; two-sided midpoint only; thin-market rule as football.
