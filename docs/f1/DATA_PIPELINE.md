# Data pipeline: extraction and storage (F1)

This document covers how Formula 1 data enters the repository, where it is
stored, and how it stays current. It is written for whoever maintains the
fetchers or needs to read the stores. Every constant below was read from the code
and names its file; where a docstring and the code differ, the code is followed
and the difference is noted.

| Section | Covers |
|---|---|
| 1 | overview and data flow |
| 2 | the sources: Jolpica, OpenF1, the prediction markets |
| 3 | coverage by year |
| 4 | the fetch scripts |
| 5 | the store formats: season store, session record, raw telemetry, telemetry summary |
| 6 | identity: `canon.py` |
| 7 | what is committed, and the model caches |
| 8 | scheduling: the hourly workflow |
| 9 | the one-off backfills |
| 10 | failure modes |
| 11 | known gaps and sharp edges |
| 12 | operator quick reference |

---

## 1. Overview and data flow

```
 Jolpica (api.jolpi.ca/ergast/f1)          OpenF1 (api.openf1.org/v1)               Kalshi, Polymarket
   calendar, results, qualifying,            sessions, drivers, laps, stints, pit,    title, race winner,
   sprints, pit stops, laps, positions       race_control, weather, overtakes,        head-to-head prices
         │                                   session_result, starting_grid,                 │
         │ scripts/f1_fetch.py               position, intervals, car_data, location        │
         │ (sources/jolpica.py, Pacer)             │ scripts/f1_openf1.py                    │ build time only
         ▼                                         │ (sources/openf1.py, Client)              │ (sources/markets.py)
 docs/paddock/data/<year>/store.json ◄──┐          ├──────────────► docs/paddock/data/<year>/sessions/<key>.json
   (committed)                          │          └─ --telemetry ► data/f1/telemetry/<year>/<key>/<driver>.json.gz
                                        │                              (git-ignored; Actions cache in CI)
                                        │                                       │ scripts/f1_telemetry.py
                                        │                                       ▼ (oddsmarkets/f1/telemetry.py)
                                        │                     docs/paddock/data/<year>/telemetry/<key>.json (committed)
                                        │
                   canon.py: car numbers → driverIds, sessions → rounds
                                        │
                                        ▼
                         scripts/build_paddock.py ──► payloads under docs/paddock/data/ (git-ignored)
```

Two rules hold throughout:

- **Fetchers write, the build reads.** `scripts/f1_fetch.py`, `scripts/f1_openf1.py`
  and `scripts/f1_telemetry.py` are the only writers of the committed data.
  `scripts/build_paddock.py` never calls Jolpica or OpenF1; its only network calls
  are the market prices for `markets.json` (skipped with `--no-market`).
- **Every fetcher is resumable.** Each skips what is already on disk and can be
  stopped at any point; the stores are written atomically (`store.save` writes a
  `.tmp` file and renames it).

---

## 2. Sources

### 2.1 Jolpica: `oddsmarkets/f1/sources/jolpica.py`

Jolpica is the community successor to the Ergast F1 API. It needs no key.

| Constant | Value | Where |
|---|---|---|
| Base URL | `https://api.jolpi.ca/ergast/f1` | `BASE` |
| User-Agent | `The Quant Paddock (pchattani.github.io/the-quant-paddock)` | `HEADERS` |
| Timeout | 30 s | `TIMEOUT` |
| Spacing between calls | 7.3 s by default | `Pacer(interval=7.3)` |
| Calls per run | 450 by default | `Pacer(budget=450)` |
| Rows per page | 100 | `paged(limit=100)` |

**Limits.** Jolpica allows about 4 requests a second in a burst and 500 an hour
sustained, enforced per IP address with HTTP 429. The default spacing of 7.3 s is
493 calls an hour, just under the hourly cap.

**`Pacer.get`.** Every call goes through one pacer, which sleeps until
`interval` seconds have passed since the previous call, counts the call against
the budget and raises `BudgetExhausted` once the budget is spent. Each call is
tried up to 5 times:

| Answer | What happens |
|---|---|
| 200 | returns `MRData` |
| 404 | returns `None` (no data) |
| 429 | sleeps `Retry-After`, or 60 s × attempt when the header is missing, and retries |
| other status | logs, sleeps 5 s × attempt, retries |
| network error | logs, sleeps 10 s × attempt, retries |

After 5 failed attempts it returns `None`. Retries count against the budget.

**`paged(pacer, path, table, key)`** walks `offset` in steps of `limit` until the
reported `total` is reached, yielding each item of `MRData[table][key]`.

**Endpoints used** (all by `scripts/f1_fetch.py`):

| Path | Phase | Calls |
|---|---|---|
| `<year>.json?limit=100` | schedule | 1 a season |
| `<year>/results.json` | results | paged |
| `<year>/qualifying.json` | results | paged |
| `<year>/sprint.json` (2021 on) | results | paged |
| `<year>/<round>/pitstops.json` (2011 on) | pitstops | paged, usually 1 a race |
| `<year>/<round>/laps.json` (1996 on) | laps | paged, about 10–15 a race |

**Parsers.** They flatten Ergast's nested JSON into records keyed by Jolpica ids:

- `to_ms("1:23.456")` and `to_ms("83.456")` both give `83456`; anything
  unparseable gives `None`.
- `race_rec`: `name, date, time, circuit{id, name, locality, country, lat, long},
  sessions{fp1, fp2, fp3, quali, sprint, sprint_quali}` (ISO strings;
  `SprintShootout` maps to `sprint_quali`). The race's own start is `date` +
  `time`, not a `sessions` entry.
- `result_rec`: `driver, constructor, number, grid, position, position_text,
  points, laps, status, time_ms, fastest_rank, fastest_lap, fastest_ms`. Used for
  races and sprints.
- `quali_rec`: `driver, constructor, number, position, q1, q2, q3` (ms).
- `driver_rec`: `code, number (permanentNumber), given, family, dob, nationality`.
- `constructor_rec`: `name, nationality`.

### 2.2 OpenF1: `oddsmarkets/f1/sources/openf1.py`

OpenF1 provides timing, strategy, race control, weather and car telemetry for
every session since 2023. Historical data needs no key, and it sends permissive
CORS headers, so the site's telemetry lab also fetches raw laps from the browser.

| Constant | Value | Where |
|---|---|---|
| Base URL | `https://api.openf1.org/v1` | `BASE` |
| Timeout | 60 s | `TIMEOUT` |
| Spacing between calls | 0.35 s | `Client(interval=0.35)` |
| Calls per run | 2,000 in the class; the scripts pass their own (`f1_openf1.py` default 100,000; the workflow 3,000) | `Client(budget=...)` |
| Session records | `docs/paddock/data/<year>/sessions/<session_key>.json` | `session_path` |
| Raw telemetry | `data/f1/telemetry/<year>/<session_key>/<driver>.json.gz` | `telemetry_path` |

**Limits.** OpenF1 allows 30 requests a minute. The client's 0.35 s spacing does
not enforce that by itself (it would allow about 170 a minute); in practice each
call takes long enough that the backfill has run at about 25 calls a minute
(2,349 calls between 21:26 and 22:58 on 30 September in `logs/f1_openf1.log`),
and a 429 is handled by waiting `Retry-After`, or 20 s × attempt. A 404 means "No
results found" and is returned as an empty list. Other failures retry up to 5
times (5 s × attempt) and then return `None`. Exceeding the budget raises
`RuntimeError`.

**Endpoints used by `fetch_session(client, sess)`**, per session:

| Endpoint | Stored as | Sessions |
|---|---|---|
| `sessions?year=Y` | the list the scripts iterate | — |
| `drivers` | `drivers` | all |
| `laps` | `laps` (and lap end times for `lap_end`) | all |
| `stints` | `stints` | all |
| `pit` | `pit` | all |
| `race_control` | `race_control` | all |
| `weather` | `weather` | all |
| `overtakes` | `overtakes` | Race, Qualifying, any session named "Sprint…" |
| `session_result` | `result` | same |
| `starting_grid` | `grid` | same |
| `position` | `positions` | same |
| `intervals` | `lap_end` | Race only, and only when lap end times exist |

**`fetch_telemetry(client, year, sess, driver)`** makes two calls per driver
(`car_data` and `location`), keeps the samples from 5 minutes before the session's
`date_start` to 5 minutes after its `date_end` (the feed runs all day), and writes
them gzipped as column arrays. `load_telemetry` reads them back.

### 2.3 Prediction markets: `oddsmarkets/f1/sources/markets.py`

Kalshi and Polymarket prices are fetched at build time for `markets.json` only and
never stored. Kalshi series `KXF1` (drivers' champion), `KXF1CONSTRUCTORS`,
`KXF1RACE` (race winner) and `KXF1H2H`; Polymarket events under the tag `f1`,
title slugs `{year}-f1-drivers-champion` / `f1-drivers-champion` and
`f1-constructors-champion` / `{year}-f1-constructors-champion`. The pricing rules
(two-sided midpoints, consensus, de-vig, the thin-market rule, name mapping) are
in [MODELS.md](MODELS.md) section 13. The module docstring also lists the many F1
series that exist but are not used (podium, top 5/10, pole, fastest lap, sprint
and others).

---

## 3. Coverage by year

| Data | From | Source and notes |
|---|---|---|
| Race results | 1950 | Jolpica |
| Qualifying classification | about 1994; Q1/Q2/Q3 times from 2006 | Jolpica (`CONTRACT.md`) |
| Lap times and lap-end positions | 1996 | Jolpica (`LAPS_FROM = 1996`, `f1_fetch.py`) |
| Pit stops | 2011 | Jolpica (`PITSTOPS_FROM = 2011`, `f1_fetch.py`) |
| Sprint results | 2021 | Jolpica |
| Fastest-lap ranks | 2004 | Jolpica (the lap-record table on circuit pages starts here) |
| Sessions: sectors, speed traps, stints and compounds, pit-lane and stationary times, race control, weather, overtakes, intervals | 2023 | OpenF1 |
| Car telemetry and location | 2023 | OpenF1 |

So results reach back to 1950, lap-level analysis to 1996, and the deep
analytics (stints, sectors, overtakes, telemetry) to 2023. The glossary carries
this as each metric's `scope` (`oddsmarkets/f1/analytics/glossary.py`): results,
qualifying, segments, fastest, laps, pit, sprint, openf1, telemetry, model.

Jolpica stopped publishing detailed retirement reasons from 2023: in the stores,
2023–2026 retirements are a bare "Retired" (49 to 64 rows a season) beside
"Finished" and "Lapped", where 2021–2022 still carried "Collision", "Engine" and
so on. The models treat a bare "Retired" as ambiguous (see
[MODELS.md](MODELS.md)).

---

## 4. Fetch scripts

### 4.1 `scripts/f1_fetch.py`: Jolpica into the season stores

Fills the stores in four phases. Each phase runs over every season in the range,
newest first, and skips what is already stored (`store.has(store, round, what)`
against `meta.fetched`):

| Phase | What | Skips |
|---|---|---|
| `schedule` | the calendar, 1 call a season; merges `race_rec` into each round | a past season already marked |
| `results` | race results, qualifying and (2021 on) sprint results, paged; also fills `drivers` and `constructors` | a season whose finished rounds all have results |
| `pitstops` | 2011 on, per round with results | rounds already marked |
| `laps` | 1996 on, per round with results: `laps{driver: [ms per lap]}` and `positions{driver: [position per lap]}` | rounds already marked; a race with no laps at Jolpica is marked so it is not asked again |

A race counts as finished 4 hours after its scheduled start (`_finished`). The
pitstops and laps phases save the store after every round, so a stopped run loses
at most one round.

| Flag | Default | Meaning |
|---|---|---|
| `--from`, `--to` | 1950, the current UTC year | seasons, processed newest first |
| `--phases` | `schedule,results,pitstops,laps` | any subset |
| `--budget` | 450 | Jolpica calls in this run |
| `--interval` | 7.3 | seconds between calls |
| `--refresh-current` | off | only the current season, all four phases, re-fetching every finished round |

The docstring puts the full history at about 7,000 calls, roughly 14 hours at the
default pacing.

```
python scripts/f1_fetch.py --from 1950 --to 2026 --budget 10000      # the full backfill
python scripts/f1_fetch.py --phases results,laps --from 2023 --budget 400
python scripts/f1_fetch.py --refresh-current --budget 120             # what the workflow runs (with --interval 1.0)
```

`--refresh-current` re-fetches pit stops and laps for **every** finished round of
the current season on each run, from round 1 upward, not only the latest round.
With the workflow's budget of 120 calls the laps phase runs out of budget after
the first several rounds (about 10–15 calls a race), so later rounds' Jolpica laps
are never reached by CI. For 2023 onward this costs little, because the models and
the race centre take laps from the OpenF1 session records when they exist; it is
listed in `HANDOFF.md`.

### 4.2 `scripts/f1_openf1.py`: OpenF1 session records and telemetry

For each season in the range, newest first, lists the sessions and walks them
newest first. A session is fetched once it has ended plus a settling margin of
1,800 s (`_ended`), and fetched again on every run while it is younger than
`--refresh-hours`, so late corrections land. With `--telemetry`, each driver's raw
telemetry is fetched for every session whose record exists, skipping files already
on disk unless the session is still young.

| Flag | Default | Meaning |
|---|---|---|
| `--from`, `--to` | 2023, the current UTC year | seasons |
| `--telemetry` | off | also fetch raw `car_data` and `location` per driver |
| `--budget` | 100,000 | OpenF1 calls in this run |
| `--refresh-hours` | 48 | re-fetch sessions that ended less than this long ago |
| `--types` | all | comma-separated `session_type` filter, e.g. `Race,Qualifying` |

A session record costs 6 calls for a practice session (drivers, laps, stints,
pit, race control, weather), 10 for qualifying and sprint sessions (plus
overtakes, result, grid, positions) and 11 for a race (plus intervals), on top of
one `sessions` call per season. Telemetry costs 2 calls per driver. Without
`--types`, practice sessions are fetched too, including their telemetry.

### 4.3 `scripts/f1_telemetry.py`: raw telemetry into summaries

For each season (default 2023 to the current year), for every session folder under
`data/f1/telemetry/<year>/`, runs `oddsmarkets.f1.telemetry.write_session` when the
summary is missing or older than the newest raw file (`--force` reprocesses
everything). A failing session is logged and skipped. It prints a line per season
with the counts processed and up to date. The processing itself is described in
[MODELS.md](MODELS.md) section 15.

---

## 5. Store formats

### 5.1 Season store: `docs/paddock/data/<year>/store.json`

`oddsmarkets/f1/store.py`; `CONTRACT.md` is the reference for field meanings.

```
{
  "season": 2026,
  "races": {"<round>": {
      "name", "date", "time",
      "circuit": {"id", "name", "locality", "country", "lat", "long"},
      "sessions": {"fp1", "fp2", "fp3", "quali", "sprint_quali", "sprint": ISO},
      "results":    [result_rec ...],
      "qualifying": [quali_rec ...],
      "sprint":     [result_rec ...],
      "pitstops":   [{"driver", "stop", "lap", "duration_ms"}],
      "laps":       {driverId: [ms per lap, null where missing]},
      "positions":  {driverId: [position at the end of each lap]}
  }},
  "drivers":      {driverId: {"code", "number", "given", "family", "dob", "nationality"}},
  "constructors": {constructorId: {"name", "nationality"}},
  "meta": {"fetched": {"<round>": {"results": ts, "qualifying": ts, "pitstops": ts, "laps": ts},
                       "_": {"schedule": ts}},
           "updated_at": ts}
}
```

Conventions (`CONTRACT.md`): `grid == 0` is a pit-lane start; `status`
distinguishes "Finished", "+1 Lap" and retirements; "Disqualified" is not
classified; points include fastest-lap and sprint points as awarded that year.
Lap times are kept as one list per driver so 1996–2026 fits in tens of megabytes
(store docstring). `store.load(year)` returns an empty store for a missing or
unreadable file and fills any missing top-level keys.

### 5.2 OpenF1 session record: `docs/paddock/data/<year>/sessions/<session_key>.json`

Every time inside a session is milliseconds from the session's `date_start`.

```
{
  "session":  {"session_key", "meeting_key", "session_name", "session_type", "date_start", "date_end",
               "circuit_key", "circuit_short_name", "country_name", "location", "year"},
  "drivers":  {"<number>": {"broadcast_name", "full_name", "name_acronym", "first_name", "last_name",
                            "team_name", "team_colour", "country_code"}},
  "laps":     {"<number>": [[lap, t_start_ms, lap_ms, s1_ms, s2_ms, s3_ms, i1_kph, i2_kph, speedtrap_kph, pit_out], ...]},
  "lap_end":  {"<number>": [[lap, gap_to_leader, interval], ...]},     race only; the last interval sample at or
                                                                       before the lap's end; may be "+1 LAP" strings
  "stints":   [[driver_number, stint, lap_start, lap_end, compound, tyre_age_at_start]],
  "pit":      [[driver_number, lap, t_ms, lane_ms, stop_ms]],          lane_ms from lane_duration, else pit_duration
  "race_control": [[t_ms, lap, category, flag, scope, sector, driver_number, message]],
  "weather":  [[t_ms, air_c, track_c, humidity, rainfall, wind_speed, wind_dir, pressure]],
  "overtakes":[[t_ms, overtaking_number, overtaken_number, position]],     race, qualifying, sprint
  "result":   [{"position", "driver_number", "number_of_laps", "points", "dnf", "dns", "dsq", "duration", "gap_to_leader"}],
  "grid":     [[position, driver_number, lap_ms]],
  "positions":{"<number>": [[t_ms, position], ...]},                     at each position change
  "fetched_at": ISO
}
```

Records are keyed by car number; `canon.py` maps them to driverIds (section 6).

### 5.3 Raw telemetry: `data/f1/telemetry/<year>/<session_key>/<driver>.json.gz`

```
{"car": {"t": [...], "speed": [...], "rpm": [...], "gear": [...], "throttle": [...], "brake": [...], "drs": [...]},
 "loc": {"t": [...], "x": [...], "y": [...], "z": [...]}}
```

Column arrays, `t` in ms from the session start, about 3.7 samples a second.
Git-ignored. Locally the files stay where the backfill wrote them; in CI they live
in the Actions cache (section 8). The docstring of `sources/openf1.py` and the F1
block of `.gitignore` also mention "release archives"; no workflow creates one.

### 5.4 Telemetry summary: `docs/paddock/data/<year>/telemetry/<session_key>.json`

Written by `oddsmarkets/f1/telemetry.py` and committed. Drivers are keyed by car
number (as strings), as in the session record.

```
{"session_key",
 "ref": {"driver", "lap", "length_m", "corners": [{"n", "d", "v"}]},
 "laps": {"<number>": [[lap, top_kph, mean_kph, full_throttle_pct, braking_pct, coasting_pct, gear_changes, drs_open_s], ...]},
 "corner_min":   {"<number>": {"<lap>": [min speed per corner]}},
 "brake_points": {"<number>": {"<lap>": [metres before the apex per corner]}},
 "fastest": {"<number>": {"lap", "ms", "d": 10, "speed", "throttle", "brake", "gear", "rpm", "drs", "x", "y"}}}
```

---

## 6. Identity: `oddsmarkets/f1/canon.py`

Everything downstream keys drivers by Jolpica `driverId` and teams by
`constructorId`. `canon.py` is the only place numbers and sessions are resolved.
Nothing in it raises on missing data.

- **Stores are cached by file modification time** (`canon.season(year)`), so a
  backfill rewriting a store is picked up without a restart.
- **`number_map(year, round=None)`**: from the `number` field of the round's (or
  the season's) results, qualifying and sprint rows, each number goes to the
  driver who carried it in the most rows. At season level, a permanent number from
  the season's `drivers` block fills only numbers no row claims. Numbers are
  never shared across seasons (No. 1 belongs to the champion, retired numbers are
  reissued). `number_collisions(year)` lists numbers two drivers used in one
  season, as a data check.
- **`driver_for_number(year, number, round)`** tries the round's map first (exact,
  so a substitute resolves correctly), then the season's.
- **`team_for(year, round, driver)`**: the constructor on the driver's row in that
  round; otherwise the nearest round, earlier rounds first.
- **`lineup(year, round)`**: `{driverId: constructorId}` from the round's rows, or
  the most recent earlier round's for a round not yet run.
- **`session_index(year)`** lists the session files on disk with their round:
  `round_for_date` assigns a session to the round whose race date is 0 to 4 days
  on or after the session's date, the closest winning. `find_session(year, round,
  "Race")` returns a round's record by session name.
- **`session_driver_ids(year, record, round)`** maps each car number in a record by
  number within the round, then the season; an unknown number by the OpenF1
  `name_acronym` against the season's driver codes, then by `last_name` against
  family names. `rekey` converts a record's per-number dict to driverIds and drops
  numbers it cannot resolve.

The circuit model (`models/circuits.py`) matches OpenF1 race and sprint sessions
to races by date with offsets of 0, −1, +1 and −2 days instead, through its own
`match_session`.

---

## 7. What is committed, and the model caches

`.gitignore` (the F1 block at its end):

```
!docs/paddock/data/
docs/paddock/data/**
!docs/paddock/data/*/
!docs/paddock/data/*/store.json
!docs/paddock/data/*/sessions/
!docs/paddock/data/*/sessions/**
!docs/paddock/data/*/telemetry/
!docs/paddock/data/*/telemetry/**
```

So under `docs/paddock/data/` only the season stores, the session records and the
telemetry summaries are committed. Every other file there (`index.json`,
`<year>/season.json`, `races/`, `drivers/`, ...) is build output, regenerated by
CI every hour. `docs/paddock/assets/base.css` is committed and also overwritten by
each build from `docs/site/assets/style.css`.

The root `data/` is ignored, which covers:

| Path | Written by | Keyed on |
|---|---|---|
| `data/f1/telemetry/` | `f1_openf1.py --telemetry` | — (raw data) |
| `data/f1/cache/pace/<year>_<round>.json` | `laptime.race_pace` | SHA-1 of the model version and the race's store rows and session record |
| `data/f1/cache/circuit_records.json` | `circuits.all_records` | per-season fingerprint of store and session files; `RECORDS_VERSION = 5` |
| `data/f1/cache/elo.json` | `elo.elo_history` | modification time and size of every store; `VERSION = 1` |
| `data/f1/cache/forecasts/<year>_<round>_<kind>.json` | `analytics/forecasts.forecast` | SHA-1 of everything the forecast can see (see [MODELS.md](MODELS.md) section 11) |
| `data/f1/cache/backtest.json` | `models/backtest.backtest()` | not keyed: written when the backtest is run |
| `data/f1/cache/swaps/swaps_<year>_<key>.json` | `analytics/value.swap_table` | the remaining events' race inputs, points so far, driver effects, n, seed |
| `data/f1/cache/fantasy/actuals_<year>.json` | `analytics/fantasy.season_actuals` | the season's round digests (results, qualifying, sprint rows) and OpenF1 session file names; `VERSION` |
| `data/f1/cache/fantasy/backtest_preds.json` | `analytics/fantasy.backtest` | per weekend: `VERSION`, sims, the race components' source (tune pickle size and time, or the forecast signature), the fitted race constants, the overtake and pit models |
| `data/f1/cache/fantasy/backtest.json` | `fantasy` CLI and `update_backtest` | not keyed: the last run (its seasons and sims are what the hourly build extends) |
| `data/f1/cache/tune/<year>_<round>.pkl` | `scripts/f1_tune.py prep` | not keyed: walk-forward race components, read by the fantasy backtest |

`PADDOCK_DATA` (or `--data`) points the stores and payloads at another directory,
and `PADDOCK_CACHE` (or `--cache`) the model caches; the tests use both.

---

## 8. Scheduling: `.github/workflows/update_paddock.yml` ("Paddock Hourly Update")

| Setting | Value |
|---|---|
| Triggers | `cron: '37 * * * *'` and `workflow_dispatch` |
| Runner | `ubuntu-latest`, Python 3.11, `pip install uv`, `uv sync` |
| Job timeout | 55 minutes |
| Concurrency | group `paddock-build`, `cancel-in-progress: false` (a run waits for the previous one) |
| Permissions | `contents: write` (to commit the stores back) |

Steps in order:

1. **Restore raw telemetry**: `actions/cache@v4` on `data/f1/telemetry`, key
   `f1-telemetry-${{ github.run_id }}`, restore key `f1-telemetry-`. Each run
   restores the newest cache and saves a new one at the end.
2. **Fetch new rounds (Jolpica)**: `f1_fetch.py --refresh-current --budget 120
   --interval 1.0`, `continue-on-error`, 8-minute timeout. One call a second
   stays under the 4-a-second burst limit, and 120 calls under the 500-an-hour
   cap. The runner's IP is not the owner's, so it does not compete with a home
   backfill.
3. **Fetch new sessions and telemetry (OpenF1)**: `f1_openf1.py --from $YEAR --to
   $YEAR --telemetry --budget 3000`, `continue-on-error`, 25-minute timeout. At 30
   requests a minute a cold telemetry cache (2 calls per driver per session, every
   session of the season) takes several runs to fill; the cache carries what was
   fetched to the next run. The timeout keeps the build and deploy inside the
   job's limit.
4. **Summarise telemetry**: `f1_telemetry.py` for the current year,
   `continue-on-error`.
5. **Build**: `build_paddock.py` with its defaults (current season full, 20,000
   championship and next-race simulations, every other season light, markets
   fetched).
6. **Commit changed stores**: `git add docs/paddock/data/*/store.json
   docs/paddock/data/*/sessions docs/paddock/data/*/telemetry`; if anything is
   staged, commits "Paddock store refresh (CI)" as `github-actions[bot]` and tries
   `pull --rebase` + `push origin HEAD:main` up to three times, 10 s apart. A
   rejected push is logged; the next run retries.
7. **Deploy**: when `PADDOCK_REPO` and `PADDOCK_DEPLOY_KEY` are set, decodes the
   key, clones the public repo, `rsync -a --delete --exclude='.git' docs/paddock/
   /tmp/site/`, commits "Site update <timestamp>" when anything changed, pushes.
   Otherwise logs "build only, no deploy".

Only `data/f1/telemetry` is cached between runs. `data/f1/cache/` is not, so every
run recomputes the pace fits, circuit records, Elo history and walk-forward
forecasts from scratch, and finds no `backtest.json` (see section 11).

The site's data therefore changes after each session ends: OpenF1 sessions become
eligible 30 minutes after they end, and Jolpica rounds as soon as Jolpica publishes
them. Nothing updates during a session.

---

## 9. The one-off backfills

The history was filled from the owner's machine with two detached processes
started on 30 September 2026:

| Backfill | Command (as the running process shows it) | Log |
|---|---|---|
| Jolpica, every season | `python scripts/f1_fetch.py --from 1950 --to 2026 --budget 12000` (all four phases, default 7.3 s pacing) | `logs/f1_backfill.log` (stdout in `logs/f1_backfill.out`) |
| OpenF1, 2023 on | `python scripts/f1_openf1.py --from 2023 --to 2026`, intended with `--telemetry` | `logs/f1_openf1.log` (stdout in `logs/f1_openf1.out`) |

Progress when this was written (about 23:00 local time, 30 September):

- Jolpica had finished the schedule and results phases for every season
  (results 1950 done at 552 calls) and was in the pitstops phase at 2017 (761
  calls used), about 490 calls an hour. The laps phase, the longest (about 10–15
  calls per race for every race since 1996), had not started. The modified stores
  (2015–2019 so far) are not yet committed.
- OpenF1 was working back through 2024 (Silverstone) at 2,349 calls, about 25 a
  minute, writing session records; 32 new 2024 session files were not yet
  committed. The backfill is one PowerShell command that runs two passes in turn:
  `f1_openf1.py --from 2023 --to 2026` (session records, the pass that was running),
  then the same with `--telemetry` (raw car data and location for every driver in
  every session, about 17,600 calls, roughly 11 hours at OpenF1's 30 a minute).
  Afterwards run `python scripts/f1_telemetry.py --from 2023 --to 2026` to write the
  summaries.

Both scripts can be stopped and restarted at any point; they skip what is on
disk. When they finish, commit the stores and session files on `main` (pull
first: CI commits the current season's store and sessions every hour, so the
2026 files may conflict; see [RUNBOOK.md](RUNBOOK.md) section 5). The raw
telemetry stays local; the summaries from `f1_telemetry.py --from 2023` are what
gets committed.

Never run a second Jolpica caller from the same machine while the backfill runs:
the limit is per IP, and both would slow to the 429 back-off.

---

## 10. Failure modes

| What fails | Effect | Recovery |
|---|---|---|
| Jolpica 429 | the pacer sleeps `Retry-After` (or 60 s × attempt) and retries; the call counts against the budget | none needed; keep to one caller per IP |
| Jolpica down or slow in CI | the fetch step fails or times out at 8 minutes; `continue-on-error` lets the build run on the committed stores | the next hour retries |
| OpenF1 429 | sleeps `Retry-After` (or 20 s × attempt) | none needed |
| OpenF1 slow in CI | the step stops at 25 minutes; whatever telemetry was fetched is saved in the cache | the next run continues |
| Budget exhausted | `BudgetExhausted` (Jolpica) or `RuntimeError` (OpenF1) ends the script cleanly after saving | run again |
| A session not yet in OpenF1 | not eligible until 30 minutes after it ends; re-fetched for 48 hours | wait |
| An unresolvable car number | `canon.rekey` drops it; that driver is missing from session-derived metrics for that race | check `canon.number_collisions(year)` and the store's `number` fields |
| Push of the stores rejected three times | logged; the deploy still runs | the next run commits again |
| A build step raises | logged with its traceback; the payload is written as `{"ok": false, "reason"}` | read the build log |

---

## 11. Known gaps and sharp edges

- **`--refresh-current` re-fetches every finished round** each hour, so with a
  120-call budget the laps phase never reaches the later rounds (section 4.1).
- **The OpenF1 client is not paced to 30 a minute.** Its 0.35 s spacing relies on
  response latency and the 429 back-off to stay under the limit.
- **Model caches are not carried between CI runs**, so the hourly build recomputes
  them and CI never has `data/f1/cache/backtest.json`. The backtest is run
  locally; `docs/paddock/data/calibration.json` is committed, and a build without
  the backtest cache keeps that committed copy instead of writing "not built".
  After a local re-run, rebuild and commit `calibration.json`.
- **The workflow and the backfill both write 2026 files.** CI commits the current
  season's store and session records hourly; the local backfill writes the same
  files, so a manual commit of backfilled data needs a pull and, for 2026, a
  choice of version.
- **Jolpica retirement reasons** are a bare "Retired" from 2023, which weakens
  the mechanical/incident split.
- **No lap length.** Jolpica has none, so circuit length is inferred from the race
  distance (`length_km = 305 / laps`).
- **Telemetry is ~3.7 Hz**, which limits braking-point precision to tens of metres.

---

## 12. Operator quick reference

```
# Current season, as CI does it
python scripts/f1_fetch.py --refresh-current --budget 120 --interval 1.0
python scripts/f1_openf1.py --from 2026 --to 2026 --telemetry --budget 3000
python scripts/f1_telemetry.py --from 2026 --to 2026

# One season's results again
python scripts/f1_fetch.py --phases schedule,results --from 2025 --to 2025 --budget 60

# OpenF1 race and qualifying records only, no telemetry
python scripts/f1_openf1.py --from 2023 --to 2026 --types Race,Qualifying

# Summaries for every season with raw telemetry
python scripts/f1_telemetry.py --from 2023 --to 2026

# Backfill progress
tail -f logs/f1_backfill.log logs/f1_openf1.log
```
