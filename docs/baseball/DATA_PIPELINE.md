# Data pipeline: extraction and storage (baseball)

How The Quant Bullpen gets its data: Baseball Savant and its silent row cap, the MLB Stats
API, ESPN's lines, Retrosheet, the Chadwick register and Lahman, the prediction markets,
what each season holds, identity, the scripts, the store and pitch-table formats and the
merge rules, what is committed and what travels with the site, the hourly job and the
backfill. Models are in [MODELS.md](MODELS.md); the payloads built from the stores are in
[DASHBOARD.md](DASHBOARD.md).

Contents

1. Overview and data flow
2. Sources
3. Coverage by season
4. Identity: `canon.py`, the Chadwick register and the matching rules
5. The scripts
6. Formats
7. Merge rules: `store.py`
8. What is committed, what travels with the site, and the caches
9. Scheduling: `.github/workflows/update_bullpen.yml`
10. The backfill
11. Failure modes
12. Known gaps and sharp edges
13. Operator quick reference
14. NPB (the npb level): sources and terms, pages, identity, stores, schedule and backfill

---

## 1. Overview and data flow

```
 statsapi.mlb.com              baseballsavant.mlb.com          site.api / sports.core.api.espn.com
 schedule (week windows),      statcast_search/csv (one day     scoreboard (a day), core odds (a game),
 feed/live, teams, venues,     a request; the 25,000-row cap    summary (ESPN WP)
 people, standings, rosters    re-split), leaderboards                 │
        │                             │                                │
 sources/statsapi.py           sources/savant.py               sources/espn.py
        │                             │                                │
        └──────────────┬──────────────┴────────────────┬───────────────┘
                       ▼                               ▼
      scripts/mlb_fetch.py (per level, per season newest first;
      phases schedule → statcast → games → espn → people), store.save_owned per phase
                       │                               │
                       ▼                               ▼
 docs/bullpen/data/<L>/<S>/store.json      data/baseball/statcast/<L>/<S>.parquet (+ .parts/, .manifest.json)
                       │
 www.retrosheet.org ──► scripts/mlb_retro.py ──► data/baseball/retro/{pa,games}/<S>.parquet, validation.json
 Chadwick register (GitHub raw) ──► sources/chadwick.py ──► docs/bullpen/data/people.json
 Lahman (sabr.box.com) ──► sources/lahman.py (cross-check, fielding proxy)
                       │
                       ▼
 models (pitch, batted-ball, value, prediction) ──► scripts/build_bullpen.py ──► docs/bullpen/data/** payloads
                                                            ▲
                                                            └── Kalshi, Polymarket (sources/markets.py, at build time)
```

Raw downloads live under `data/baseball/` (git-ignored; env `BULLPEN_RAW`):
`statcast/<level>/` (pitch tables), `retro/` (events, game logs, validation) and `cache/`
(env `BULLPEN_CACHE`: feeds, leaderboards, zips, Chadwick and Lahman files, ESPN WP, model
and analytics caches). The data root is `docs/bullpen/data` unless `BULLPEN_DATA` points
elsewhere.

---

## 2. Sources

### 2.1 The client: `sources/_client.py`

Every source goes through one `Client`: requests spaced per host (`interval`, or `intervals`
keyed by host suffix), up to 4 attempts, a 120 s timeout, a call `budget` per run. After a
network error it sleeps 5 s × the attempt; after HTTP 429 or a 5xx it honours
`Retry-After`, else 10 s × the attempt, at most 120 s. Any other status, or a non-JSON
answer to `get`, is logged, counted in `failures` and returned as `None`: **the client never
raises on a bad answer**. Running out of budget raises `BudgetExhausted`, which the scripts
catch to stop cleanly; the next run resumes. The user agent is `The Quant Bullpen
(pchattani.github.io/the-quant-bullpen; baseball analytics, non-commercial)`. `report()`
gives calls and seconds per host and failures.

`mlb_fetch` makes one client with `--budget` (default 5,000) and `--interval` 0.5 s for the
Stats API, `--savant-interval` 3.0 s for `baseballsavant.mlb.com`, `--espn-interval` 1.0 s
for `espn.com` and 0.2 s for `githubusercontent.com`. `mlb_retro` paces `retrosheet.org` at
1 s and `sabr.box.com` at 1 s.

### 2.2 Baseball Savant: `sources/savant.py`

The backbone: every pitch, with Savant's column names kept as they are.

```
https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&player_type=pitcher
    &hfGT=R|F|D|L|W|C|&game_date_gt=YYYY-MM-DD&game_date_lt=YYYY-MM-DD        (both bounds inclusive)
Triple-A: the same plus minors=true&hfLevel=AAA|      (without hfLevel the minors search adds Single-A Florida State League parks)
hfTeam=XXX|  filters the pitching team
```

119 columns (a BOM on the first); one MLB day is about 4,700 rows, 3 MB and 7–8 s; one
Triple-A day about 4,600 rows. Regular season and every postseason round come in one search
(`canon.SAVANT_GT` = `R|F|D|L|W|C|`; `C` is the Triple-A National Championship game).

- **The cap.** A search silently returns at most **25,000 rows** (the newest). Any answer
  with exactly `CAP` rows is re-requested as two halves of the date range, and a capped
  single day is split by pitching team; capped requests are recorded in the manifest
  (`capped`). The backfill so far met none (0 capped requests in every season).
- **Typing** (`typed`): categorical strings as pandas category, floats float32, ids and
  counts int32 (nullable Int32 for the on-base, fielder, zone and score columns), `game_date`
  a timestamp, `des` a string; columns a season lacks are present as nulls.
- **Storage**: one Parquet part per day under `statcast/<L>/<S>.parts/`, compacted at the end
  of a season's pass into `statcast/<L>/<S>.parquet` by streaming the parts (one row group a
  day, bounded memory); `<S>.manifest.json` records each day's rows, games and fetch time,
  the capped requests, the rows and the columns with data.
- **Settled days**: a day is settled once it was fetched after noon UTC of the following day;
  unsettled days are fetched again. With `--refresh-current`, yesterday and today are always
  re-pulled.
- **Leaderboards** (validation references only; `--leaderboards`, cached under
  `cache/savant/leaderboards/`): bat tracking, arm strength, sprint speed, outs above
  average, catcher framing, pitch arsenal stats, swing/take, expected statistics. xwOBA+
  reads sprint speed from here; the fielding and framing checks read OAA and framing.

Pitches are never published raw.

### 2.3 The MLB Stats API: `sources/statsapi.py`

`statsapi.mlb.com` (no key, CORS `*`), sportId 1 (MLB) and 11 (Triple-A):

| Endpoint | Used for |
|---|---|
| `/api/v1/schedule?sportId=&startDate=&endDate=&hydrate=probablePitcher,linescore,team,weather,officials,venue,lineups,decisions` | GAME records (about 1 MB a week): probables, linescore, weather `{condition, temp, wind}`, the home-plate umpire, the starting nine, decisions, series fields |
| `/api/v1.1/game/{pk}/feed/live[?fields=...]` | about 830 KB in full; `fields` trims it to about 10 KB: ABS challenges `{usedSuccessful, usedFailed, remaining}` (2026), mound visits, the batting order |
| `/api/v1/teams?sportId=&season=&hydrate=venue` | names, abbreviations, league, division, venue by season (Triple-A teams with their parent club) |
| `/api/v1/venues?venueIds=&hydrate=location,fieldInfo` | latitude and longitude, elevation (ft), azimuth, roof, turf, capacity, fence distances |
| `/api/v1/people?personIds=a,b,...` | name, bats, throws, position, birth date, debut (150 a call) |
| `/api/v1/standings?leagueId=103,104&season=` (Triple-A 117, 112) | records, division and wild-card ranks, games back, run totals, clinched |
| `/api/v1/teams/{id}/roster?rosterType=40Man|injured&season=` | 40-man rosters and injured lists |
| `/api/v1/transactions?startDate=&endDate=&sportId=` | the last two weeks' transactions (cache) |

Raw feeds are never re-hosted (MLBAM terms); only compact GAME records go into the stores.
Status ranks final > live > suspended > pre > postponed / cancelled
(`STATUS_RANK`). Postseason placeholder teams ("NL Higher Seed", "ATL/PHI") carry
`"placeholder": true`.

### 2.4 ESPN: `sources/espn.py`

The public JSON (no key, CORS `*`), paced at one request a second:

- `site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=YYYYMMDD`: one call
  per game day; maps ESPN events to gamePks by the two teams (ESPN id → MLBAM id) and the
  nearest UTC start within 30 hours (`match_events`; doubleheaders resolve by start time;
  ESPN dates are UTC, so an 8 pm ET game is the next day).
- `sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/events/<id>/competitions/<id>/odds`:
  one item per provider (about 7 KB): 2015–2019 offshore books (5Dimes, Bovada, Pinnacle,
  ...), 2020–2024 US books (Caesars, DraftKings, FanDuel, MGM, ...), 2026 DraftKings only;
  consensus, teamrankings and numberfire rows carry no prices. `homeTeamOdds` /
  `awayTeamOdds` `open` / `close` hold the opening and closing moneyline and run line (2023
  on); `item.open` / `close` the total.
- `…/summary?event=<id>`: the pickcenter and ESPN's win probability (about 1 MB; read only
  for current-season games final within 36 hours, cached under `cache/espn_wp/<S>/`).

`compact_lines` keeps every book and picks the main one in `PREFERRED` order (DraftKings
first, then FanDuel, MGM, ...). **The run-line sign** follows the moneyline favourite:
items carry `spread` unsigned (1.5); the side comes from `pointSpread` when given and
non-zero, else the favourite lays the runs (ESPN's own signs are flipped in many pre-2026
payloads).

### 2.5 Retrosheet: `sources/retrosheet.py`

```
https://www.retrosheet.org/events/<YYYY>eve.zip     regular season (team .EVA/.EVN, deduced .EDA/.EDN, rosters .ROS)
https://www.retrosheet.org/events/<YYYY>post.zip    postseason (.EVE per series)
https://www.retrosheet.org/gamelogs/gl<YYYY>.zip    one line per game, 161 fields
```

Event files exist from **1908** (1901–1907 have box-score files only, which are not read, so
those seasons have game logs but no events); game logs from 1871 (read from 1901). Our own
parser (no Chadwick binaries) replays the `id / version / info / start / sub / play / data /
com / radj / badj / padj / ladj / presadj` records into one row per event: every plate
appearance (`pa` = True) and every running event between them (stolen bases, caught
stealing, pickoffs, wild pitches, passed balls, balks, defensive indifference, other
advances; `pa` = False), with the base-out state before and after and the runs that scored,
so run totals reconcile with the game logs. The 2020-on automatic runner is read from the
`radj` records. Each season is validated against its game log, game by game (runs and hits
per team), and with `--lahman` against Lahman's team totals.

**Required notice** (shown verbatim wherever the data appears; `retrosheet.NOTICE`): "The
information used here was obtained free of charge from and is copyrighted by Retrosheet.
Interested parties may contact Retrosheet at "www.retrosheet.org"."

### 2.6 The Chadwick register and Lahman: `sources/chadwick.py`, `sources/lahman.py`

- **Chadwick** (`github.com/chadwickbureau/register`, `data/people-0.csv` … `people-f.csv`,
  about 4 MB each, updated monthly; ODC-BY 1.0, credited with `chadwick.ATTRIBUTION`): the
  sixteen shards are cached under `cache/chadwick/` and refreshed after 30 days, and
  `build` writes `docs/bullpen/data/people.json` (MLBAM id → name, Retrosheet,
  Baseball-Reference and FanGraphs ids, birth date, first and last MLB seasons; people
  known only to Retrosheet as `r:<retroid>`). The full rows with an MLBAM id (minor leaguers
  too) stay in `cache/chadwick/mlbam.json`.
- **Lahman** (SABR, season totals 1871–2025, CC BY-SA 3.0): the comma-delimited release's
  `Teams`, `People`, `Batting`, `Pitching` and `Fielding` files, from the SABR Box shared
  folder, cached under `cache/lahman/`; used only to cross-check Retrosheet's totals and for
  the historical fielding proxy.

### 2.7 Prediction markets: `sources/markets.py`

Kalshi (one event per season: `KXMLB` World Series, `KXMLBAL` / `KXMLBNL` pennants,
`KXMLB{AL,NL}MVP`, `KXMLB{AL,NL}CY`, `KXMLB{AL,NL}ROTY`, `KXMLBSERIES` series winners,
`KXMLBGAME`, `KXMLBTOTAL`, `KXMLBSPREAD`) and Polymarket (tag `mlb`: champion, pennants,
awards, "advance to" markets, series, games with moneyline, spreads, totals and first-five
markets), fetched at build time in CI (never in the browser) and mapped to MLBAM team ids by
code (`CODE_ALIASES`) and players by the store's or the crosswalk's names. The price rules
are in [MODELS.md](MODELS.md) section 19.

### 2.8 What is not used

- **Baseball-Reference and FanGraphs** pages are not fetched; only their ids are carried
  (from the Chadwick register).
- **Third-party Statcast wrappers** (such as pybaseball) are not used: Savant's search is
  called directly, with the cap handled in `savant.py`.
- **Raw Stats API feeds** are read but never stored in full outside the git-ignored cache.
- **Sofascore** (the football site's source) is not needed.

---

## 3. Coverage by season

Read with `python scripts/mlb_fetch.py --level mlb --report --from 2015 --to 2026` (and `--level aaa
--from 2023 --to 2026`) and from the stores on 2 October 2026, after the Savant and ESPN backfills
finished. "Lines" counts final games with ESPN lines; "Close" those with a closing moneyline
(`store_lines(g, "close")`). Every final game has a Statcast record (no Savant day hit the
25,000-row cap).

| Season | Games (final, postseason) | Pitches | Days | Columns with data | Lines | Close | Players |
|---|---|---|---|---|---|---|---|
| 2015 | 2,466 (2,443, 36) | 712,844 | 201 | 102 | 2,399 | 2,396 | 1,349 |
| 2016 | 2,465 (2,451, 35) | 726,023 | 203 | 103 | 2,402 | 2,332 | 1,353 |
| 2017 | 2,468 (2,443, 38) | 735,954 | 204 | 102 | 2,409 | 2,380 | 1,358 |
| 2018 | 2,465 (2,432, 33) | 734,567 | 206 | 102 | 2,337 | 2,214 | 1,378 |
| 2019 | 2,467 (2,450, 37) | 746,272 | 210 | 102 | 2,447 | 2,433 | 1,410 |
| 2020 | 953 (902, 53) | 280,398 | 90 | 103 | 901 | 898 | 1,290 |
| 2021 | 2,467 (2,428, 37) | 723,172 | 206 | 103 | 2,422 | 2,422 | 1,506 |
| 2022 | 2,470 (2,452, 39) | 721,984 | 200 | 103 | 2,452 | 2,452 | 1,500 |
| 2023 | 2,471 (2,458, 41) | 732,562 | 205 | 111 | 2,458 | 2,458 | 1,454 |
| 2024 | 2,473 (2,461, 43) | 724,190 | 208 | 111 | 2,452 | 2,448 | 1,453 |
| 2025 | 2,477 (2,470, 47) | 726,773 | 210 | 111 | 2,464 | 2,464 | 1,470 |
| 2026 (to 1 Oct) | 2,460 (2,427, 8) | 719,119 | 186 | 111 | 2,426 | 2,426 | 1,471 |
| Triple-A 2023 | 2,255 (2,194, 5) | 693,119 | 154 | 103 | – | – | 2,095 |
| Triple-A 2024 | 2,255 (2,226, 5) | 676,925 | 157 | 103 | – | – | 2,032 |
| Triple-A 2025 | 2,255 (2,219, 5) | 672,738 | 155 | 103 | – | – | 2,085 |
| Triple-A 2026 | 2,256 (2,224, 6) | 673,502 | 155 | 103 | – | – | 2,092 |

Lines are thinnest in 2018 (95 final games without an ESPN line, 218 without a closing
moneyline) and 2016 (119 without a close); ESPN has no Triple-A lines. Triple-A's unplayed
games are postponements and cancellations (29–61 a season); Triple-A has no bat tracking.

Notes: every final game has lineups; ABS challenge counts exist for 2,400 of 2026's games
(the feeds are read for finals from 2026 in MLB, 2024 in Triple-A). Columns with data rise
from 102 to 111 as Savant added fields (arm angle, bat tracking). Retrosheet:
125 seasons of game logs (1901–2025) and 118 of events (1908–2025); 2025 has 193,036 events
(186,562 plate appearances) in 2,477 games, and every season's runs and hits match its game
logs exactly (`data/baseball/retro/validation.json`). `people.json` holds 26,021 people,
1,177 of them Retrosheet-only.

---

## 4. Identity: `canon.py`, the Chadwick register and the matching rules

### 4.1 Teams

Teams are keyed by MLBAM team id (a string). `canon.TEAMS` holds, for each of the 30
franchises, its abbreviation by season (Stats API / Savant), ESPN id, colour, names by
season (full, short, city) and Retrosheet and Baseball-Reference codes by season:
Indians → Guardians (2022), Oakland Athletics → Athletics in Sacramento (2025, `ATH`),
Florida → Miami Marlins (2012), Expos → Nationals (2005), Devil Rays → Rays (2008); Houston
moved NL → AL in 2013 and Milwaukee AL → NL in 1998. Verified on 1 October 2026 against the
Stats API's 2015 and 2026 team lists, ESPN's team list and the 2025 Retrosheet event files.
Triple-A teams are read per season from the Stats API, not hard-coded. `tid_from_abbr`,
`tid_from_espn`, `tid_from_retro` map the other codes.

### 4.2 Players

A player is the MLBAM id (`pid`). `people.json` links it to Retrosheet, Baseball-Reference
and FanGraphs ids (the Chadwick register); Retrosheet-era players without an MLBAM id keep
`r:<retroid>`. The stores' `players` are filled from `/people` for everyone in a lineup, a
probable, a decision or the season's pitch table, and enriched with the crosswalk
(`chadwick.enrich_players`); the store's `meta.crosswalk` counts them (2026: 1,471 players,
all in the register, 1,216 with a Retrosheet id, since Retrosheet's 2026 files are not out).

### 4.3 Games and events

Games are gamePks. ESPN events map as in section 2.4; Retrosheet game ids map through the
teams' Retrosheet codes and dates.

### 4.4 Rules and tables

`canon.GAME_TYPES` (R, F Wild Card, D Division Series, L LCS, W World Series, S spring,
E exhibition, A All-Star); `SEASON_TYPES` = R + F, D, L, W, C (C: the Triple-A National Championship, one game after the two league finals, which the Stats API types W); `POSITIONS`; `LEAGUES`
(AL 103, NL 104, International League 117, Pacific Coast League 112); `DIVISIONS`;
`STATCAST_FROM` (MLB 2015, Triple-A 2023); `RETRO_ABS_RUNNER_FROM` 2020 (the automatic
runner in regular-season extra innings).

---

## 5. The scripts

### 5.1 `scripts/mlb_fetch.py`: sources into the stores and pitch tables

```
python scripts/mlb_fetch.py --level mlb --from 2026 --to 2026 --budget 20000
python scripts/mlb_fetch.py --level mlb --from 2015 --to 2025 --phases statcast --log logs/mlb_backfill_savant.log
python scripts/mlb_fetch.py --level aaa --from 2023 --to 2026 --phases schedule,statcast
python scripts/mlb_fetch.py --level mlb --refresh-current --budget 900        # the scheduled job
python scripts/mlb_fetch.py --level mlb --report --from 2015 --to 2026
```

| Flag | Meaning |
|---|---|
| `--level` | `mlb` (default) or `aaa` |
| `--from`, `--to` | seasons (default: the current season); processed **newest first** |
| `--phases` | any of `schedule,statcast,games,espn,people` (default all) |
| `--budget` | calls per run (default 5,000) |
| `--interval`, `--savant-interval`, `--espn-interval` | seconds between Stats API (0.5), Savant (3.0) and ESPN (1.0) calls |
| `--chunk-days` | days per Savant request (default 1) |
| `--refresh-current` | scheduled mode: the current season only |
| `--leaderboards` | also cache Savant's leaderboards for each season (MLB, 2015 on) |
| `--log` | also log to a file |
| `--report` | print the coverage of the stores and pitch tables on disk and exit |

The phases, per season:

- **schedule**: the Stats API schedule in 7-day windows (newest first, about 35 calls a
  season); a week is rescanned until it has been read two days after its last date, and with
  `--refresh-current` every week from three days ago to a week ahead is re-read; the season's
  teams once (weekly for the current season, or while fewer than 30 MLB / 28 Triple-A are
  known) and any venue not yet known. With `--refresh-current` it then reads the standings,
  the 40-man rosters and injured lists (every 20 hours) and the last 14 days' transactions.
- **statcast** (seasons from `STATCAST_FROM`): every day with a final or live game whose
  Savant day is not settled (with `--refresh-current`, yesterday and today always), newest
  first, one request a day; parts written per day; compaction at the end; `has_statcast`
  marked on the games that have pitches.
- **games**: the live feed for final games from the ABS season on (MLB 2026, Triple-A 2024)
  or without a lineup (trimmed with `fields`), and, with `--refresh-current`, the full feed of
  live games (gzipped under `cache/feeds/`) and a re-read of finals within 36 hours whose feed
  was read less than 5 hours after the start; ABS counts, mound visits and the batting order
  go onto the GAME. Saved every 200 feeds.
- **espn** (MLB only): one scoreboard per game day to map events (re-read for days within two
  days of today in refresh mode, or while a game is unmatched); one odds call per final game
  never read or read before start + 2 hours (the closing line), and in refresh mode for games
  starting from 6 hours ago to 36 hours ahead; ESPN's win probability for current-season
  finals within 36 hours. Saved every 200 calls.
- **people**: the Chadwick register rebuilt when `people.json` is older than 30 days; every
  player in lineups, probables, decisions and the pitch table fetched from `/people` (new
  ones, and in refresh mode those without a position); home-plate umpires' names; the
  crosswalk enrichment.

Each phase saves through `store.save_owned` (section 7).

### 5.2 `scripts/mlb_retro.py`: Retrosheet

```
python scripts/mlb_retro.py --from 1901 --to 2025 --log logs/mlb_backfill_retro.log
python scripts/mlb_retro.py --from 2025 --to 2025 --refresh --lahman
```

Newest first: the game log (1901 on) to `retro/games/<S>.parquet` and, from 1908, the regular
and postseason event files parsed to `retro/pa/<S>.parquet`; validation into
`retro/validation.json`. Seasons already parsed are skipped unless `--refresh`;
`--redownload` fetches the zips again; `--lahman` adds the Lahman cross-check; `--budget`
default 1,000.

### 5.3 `scripts/mlb_fit.py`: the committed fits

Fits what CI cannot fit and writes it to `oddsmarkets/baseball/models/fitted/`:

| Group | Writes | From |
|---|---|---|
| `b` | `stuff_<L>.json.gz`, `location_<L>.json.gz`, `pitching_<L>.json.gz`, `swing_<L>.json.gz` | `pitching.export_fits(level, season, with_swing=True)`: the four seasons before and through `--season` |
| `c` | `re24_<L>.json`, `re24_retro.json`, `xwoba_<L>.txt.gz` + `.json`, `catchprob_<L>.txt.gz` + `.json`, `framing_<L>.json`, `parks_<L>.json`, `stabilise_<L>.json`, `war_constants.json` | `fit_c.export_fits` (Retrosheet fits for MLB unless `--no-retro`) |
| `d` | `transitions_<L>.json` | `game_sim.fit_and_save` on the last three pitch seasons on disk |
| `proj` | `proj_agg_{h,p}_<L>_<S>.parquet` | `analytics.fallbacks.export_aggregates` for the last `--proj-seasons` (default 3) seasons |

Every step is isolated; `--levels mlb aaa`, `--only b c d proj`, `--season <S>` (default the
latest pitch table on disk). See [MODELS.md](MODELS.md) and [RUNBOOK.md](RUNBOOK.md)
section 4.

### 5.4 `scripts/mlb_hydrate.py`: the current season from the live site (CI)

```
python scripts/mlb_hydrate.py                         # both levels, their current season
python scripts/mlb_hydrate.py --levels mlb --base https://example.org/data
```

Fetches `https://pchattani.github.io/the-quant-bullpen/data/<L>/<S>/store.json` per level and
keeps it when it is newer than the checkout's (by `updated_at`). A 404 (the first deploy, or a
level with no season yet) is not an error; a non-JSON answer is ignored. The pitch tables are
not hydrated: CI restores the current season's Parquet from the Actions cache and
`mlb_fetch --refresh-current` tops it up.

### 5.5 `scripts/mlb_backfill.ps1`: the historical backfill

Starts detached, hidden PowerShell processes (section 10).

---

## 6. Formats

### 6.1 Season store: `docs/bullpen/data/<L>/<S>/store.json`

```
{"level", "season", "updated_at",
 "teams":   {tid: {"name","abbr","short","league","division","venue","colour",("parent","city" for AAA),("placeholder")}},
 "venues":  {vid: {"name","city","state","lat","lon","elev_ft","roof","turf","azimuth","capacity",
                   "dims": {"lf","lcf","cf","rcf","rf"}, "walls": {...}|null}},
 "players": {pid: {"name","short","bats","throws","pos","dob","debut","retro","bbref","fg"}},
 "umpires": {pid: {"name"}},
 "games":   {gpk: GAME},
 "meta":    {"weeks", "teams_at", "complete_through" (last date with every game final), "standings", "rosters",
             "rosters_at", "feed", "espn_days", "espn_odds", "crosswalk", ...}}
```

A GAME:

```
{"gpk", "date" (official local date), "start" (UTC ISO), "gtype": R|F|D|L|W|C|S|E, "gnum", "series": {"desc","game","of"}|null,
 "home", "away", "hs", "as", "status": pre|live|final|postponed|cancelled|suspended, "venue",
 "weather": {"temp","wind","cond"}|null, "umpire_hp", "probables": {"home","away"}, "lineups": {tid: [pid…]}|null,
 "innings": [[away, home], ...], "decisions": {"w","l","s"}, "scheduled_innings",
 "lines": {"src", "ml": [home, away], "rl": {"home": point, "price": [home, away]}, "total": {"line","over","under"},
           "open", "close" (same shape, 2023 on), "books": [{"id","name","ml","rl","total"}], "consensus"} | null,
 "espn", "abs": {"home"|"away": {"won","lost","left"}} | null, "mound_visits": {"home","away"}, "has_statcast"}
```

Store sizes: 0.9 MB (2020) to 7.4 MB (2022) a season; 3.5 MB for 2026.

### 6.2 Pitch table: `data/baseball/statcast/<L>/<S>.parquet`

Savant's columns as they are (`savant.COLUMNS`; the contract lists them: ids, count, release,
spin, movement, plate location, the nine-parameter trajectory, batted-ball columns, Savant's
expected stats, run and win expectancy changes, fielders and alignment, the umpire, bat
tracking). `savant.load_season(level, season, columns=None, filters=None)` is the reader.
About 90–97 MB a full season (33 MB for 2020). The manifest beside it: `{"days": {date: {"rows","games","at"}},
"capped": [[lo, hi, team, rows]], "rows", "columns_present", "compacted_at"}`.

### 6.3 Retrosheet tables

`retro/pa/<S>.parquet`: one row per event (CONTRACT.md section 1 lists every column: game,
date, game type, teams, park, inning, half, sequence, batting team, outs and bases before,
runners, scores before, count and pitches, the raw play string, the event code, `pa`, `ab`,
hit, error, runs and outs on the play, outs and bases after, batter, pitcher, hands, fielder,
hit location, batted-ball type, sacrifices). `retro/games/<S>.parquet`: game logs with a
matching game id. `retro/validation.json`: per season, game-log and event counts, unparsed
plays, runs and hits matches and the Lahman comparison.

### 6.4 Crosswalk: `docs/bullpen/data/people.json`

`{pid: {"name","retro","bbref","fg","birth","debut","last"}}` (birth `YYYY-MM-DD` or a year;
debut and last are MLB seasons). 3.4 MB.

---

## 7. Merge rules: `store.py`

**Insert or update** (`merge_game`): a thinner record never wipes richer fields: `lines`,
`lineups`, `abs`, `weather`, `umpire_hp`, `venue`, `series`, `innings`, `decisions`,
`espn` and `probables` are kept when the new value is empty; probables merge side by side;
`has_statcast` only ever turns on.

**Concurrent writers** (`save_owned(store, phases)`): under a lock file beside the store,
the store is re-read from disk and only what the given phases own is merged in:

| Phase | GAME fields | `meta` keys | top-level |
|---|---|---|---|
| schedule | every field except the ones other phases own (it may also set `lineups`, the schedule's starting nine) | `weeks`, `teams_at`, `complete_through`, `standings`, `rosters`, `rosters_at` | `teams`, `venues` |
| statcast | `has_statcast` | – | – |
| games | `abs`, `mound_visits`, `lineups` | `feed` | – |
| espn | `espn`, `lines` | `espn_days`, `espn_odds` | – |
| people | – | `crosswalk` | `players`, `umpires` |

So the Savant and ESPN backfill processes run on the same seasons at once
(`mlb_backfill.ps1 -Which all`). The in-memory store is replaced with the merged result after
each save. `complete_through` is the last date through which every game is final (postponed
and cancelled games skipped).

---

## 8. What is committed, what travels with the site, and the caches

| What | Where | In git | On the public site | In the Actions cache |
|---|---|---|---|---|
| Completed seasons' stores | `docs/bullpen/data/<L>/<S>/store.json` | to be committed by hand (none yet: 2017–2025 untracked on 1 October 2026) | yes | – |
| Current season's stores | same | **no** | yes (hydrated back each run) | – |
| Crosswalk | `docs/bullpen/data/people.json` | yes | yes | – |
| Calibration | `docs/bullpen/data/<L>/calibration.json` | yes (MLB) | yes | – |
| Fitted models and projection aggregates | `oddsmarkets/baseball/models/fitted/` (21 files) | yes | – | – |
| Payloads and manifests | everything else under `docs/bullpen/data/` | no | yes (restored with `--ignore-existing`) | – |
| The current season's pitch tables | `data/baseball/statcast/{mlb,aaa}/<S>.{parquet,manifest.json,parts}` | no | no | yes (`bullpen-statcast-<year>-<run_id>`) |
| Earlier pitch tables, Retrosheet | `data/baseball/{statcast,retro}/` | no | no | no |
| Model and analytics caches, feeds, leaderboards | `data/baseball/cache/` | no | no | yes (`bullpen-cache-<run_id>`) |

The `.gitignore` block: `docs/bullpen/data/**` ignored, then `*/`, `*/*/`, `*/*/store.json`,
`people.json` and `*/calibration.json` un-ignored. Because the store pattern matches the
current season too, commit stores by explicit path.

CI has neither the earlier pitch tables nor Retrosheet, so: the pitch and batted-ball models
read `models/fitted/`; projections read the exported aggregates (`analytics/fallbacks.py`);
past seasons are skipped ("pitch table not on this machine; payloads kept") and their
payloads, the careers' Retrosheet blocks and `history.json` come from the previous deploy
("no Retrosheet tables on this machine; history.json kept"); the xwOBA+ check (it needs two
pitch seasons) keeps the committed `calibration.json` block, while the current season's
fielding and framing checks are merged into it each run.

---

## 9. Scheduling: `.github/workflows/update_bullpen.yml` ("Bullpen Hourly Update")

`cron: '7 * * * *'` plus `workflow_dispatch`; `concurrency: bullpen-build` (not cancelled in
progress); 55-minute job; `permissions: contents: read`. The local hourly Windows task
(`scripts/refresh_sofascore_all.ps1`) also dispatches it each hour, because GitHub drops many
scheduled runs (RUNBOOK section 1). There is no game-window gate: the site moves hourly.

| Step | Timeout | On failure |
|---|---|---|
| Checkout, Python 3.11, `pip install uv`, `uv sync` | – | job fails |
| Season: `date -u +%Y` | – | job fails |
| Restore the current season's pitch tables, both levels (key `bullpen-statcast-<year>-<run_id>`, prefix `bullpen-statcast-<year>-`) | – | cold: `mlb_fetch` re-pulls the season within its budget |
| Restore `data/baseball/cache` (key `bullpen-cache-<run_id>`, prefix `bullpen-cache-`) | – | cold caches (committed fits used) |
| Clone the public repo with the deploy key; `rsync -a --ignore-existing /tmp/prev/data/ docs/bullpen/data/` | 10 min | continue (cold build) |
| `mlb_hydrate.py` (both levels) | 5 min | continue |
| `mlb_fetch.py --level mlb --refresh-current --budget 900` | 15 min | continue |
| `mlb_fetch.py --level aaa --refresh-current --budget 300` | 8 min | continue |
| `build_bullpen.py --game-page-seasons 2` | 30 min | job fails |
| Prune `docs/bullpen/data/{mlb,aaa}/<S>/games/` for seasons ≤ this year − 2 | – | job fails |
| Deploy: clone the public repo, `rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/bullpen/ /tmp/site/`, commit "Site update <UTC stamp>" (only when something changed), push | – | job fails |

The restore step uses `--ignore-existing`, so the checkout's committed inputs win over the
deployed copies; the hydrate step then replaces each level's current store with the deployed
one when it is newer. A typical hourly MLB run reads about two schedule weeks, the standings,
the transactions (and the rosters once a day), two Savant days (each about 8 s), the feeds of
live and just-finished games, ESPN's scoreboards for four or five days and the odds of the
day's games.

**A cold pitch-table cache is expensive**: a full MLB season is about 205 Savant requests at
3 s pacing plus 7–10 s a request, more than the fetch step's 15 minutes, so a cold CI run
fetches the newest days first and finishes the season over several runs (completed days are
kept as parts).

---

## 10. The backfill

`scripts/mlb_backfill.ps1` starts detached, hidden PowerShell processes, newest season first;
each step is resumable (re-running the script picks up where the logs stop):

```
powershell -File scripts/mlb_backfill.ps1 -Which savant   # Savant MLB 2025→2015, then Triple-A 2026→2023
powershell -File scripts/mlb_backfill.ps1 -Which espn     # ESPN lines 2025→2015 (≤ 1 request a second)
powershell -File scripts/mlb_backfill.ps1 -Which retro    # Retrosheet 2025→1901 (+ Lahman cross-check)
powershell -File scripts/mlb_backfill.ps1 -Which all      # -From 2015 -To 2025 by default
```

| Step | Commands (with the venv's Python) | Log |
|---|---|---|
| savant | `mlb_fetch.py --level mlb --from 2015 --to 2025 --phases schedule,statcast,games,people --budget 200000 --leaderboards`, then `mlb_fetch.py --level aaa --from 2023 --to 2026 --phases schedule,statcast,people --budget 200000` | `logs/mlb_backfill_savant_mlb.log`, `logs/mlb_backfill_savant_aaa.log` |
| espn | `mlb_fetch.py --level mlb --from 2015 --to 2025 --phases schedule,espn --espn-interval 1.0 --budget 200000` | `logs/mlb_backfill_espn.log` |
| retro | `mlb_retro.py --from 1901 --to 2025 --lahman --budget 2000` | `logs/mlb_backfill_retro.log` |

The stores are written with the lock and per-phase ownership, so the Savant and ESPN
processes run on the same seasons at once.

Progress on 1 October 2026 (UTC): Retrosheet finished in 885 s (367 calls: 361 to
retrosheet.org, 6 to sabr.box.com; 0 unparsed plays). Savant MLB started at 17:06 and takes
about 35 minutes and 260 calls a season (2025 to 2017 done by 22:18; 2016 and 2015 to go,
then Triple-A 2026→2023). ESPN started at 18:28 and takes about 50 minutes and 2,670 calls
a season (2025 to 2022 done; 2021 running; then 2020→2015). The 2026 season had been
fetched separately (`logs/mlb_2026_smoke.log`: 5,257 calls, 6,763 s).

---

## 11. Failure modes

| Symptom | Cause | Effect |
|---|---|---|
| `Savant request failed; will retry next run` | Savant 5xx or timeout | that day stays unsettled and is fetched next run |
| an answer of exactly 25,000 rows | the cap | re-split automatically (halves, then by team); logged in `capped` |
| Savant columns missing for a season | the season predates them | present as nulls; `columns_present` in the manifest says which |
| Stats API 5xx | Stats API | that window or feed is skipped; the next run re-reads it |
| ESPN event unmatched | no start within 30 hours, or a postponement | the game has no lines; days read after they settled are not re-read |
| `BudgetExhausted` in the log | the run's budget spent (a cold Savant season) | stops cleanly; the next run continues |
| a Retrosheet season with `unparsed` plays or runs not matching | a play string the parser does not know | listed in `validation.json`; extend the parser in `retrosheet.py` |
| the hydrate 404s | first deploy, a new season, or a level with no season yet | the checkout's store (or none) is used; the fetch rebuilds the store from the schedule |

---

## 12. Known gaps and sharp edges

1. **No season store is committed yet.** The backfill was still writing 2016 and 2015 (and
   the ESPN lines for 2021→2015) at the time of writing; until the stores are committed, a
   fresh clone has none and CI relies on the deployed copies for past seasons.
2. **Triple-A has no history here yet**: its Savant backfill (2023–2026) runs last; CI
   fetches only the current Triple-A season.
3. **Closing lines** exist from 2023 (21 games of 2023, nearly every game from 2024); before
   that the backtest uses the last pre-game line read after the game.
4. **The current season's stores exist only on the deployed site.** If the public repo is
   lost, the next fetch rebuilds the schedule, but lines of past days are re-read only for
   games the refresh window touches; recover with a local `mlb_fetch.py --from <S> --to <S>`.
5. **Retrosheet's current season** arrives in the winter; history after the last Retrosheet
   year comes from the Statcast PA table.
6. **Retrosheet 1901–1907** have game logs only: no events, so no player seasons before 1908.
7. **ABS challenges** come from the feeds' counts and Savant's play descriptions on the last
   pitch of a plate appearance; challenges earlier in a plate appearance are not seen.

---

## 13. Operator quick reference

```bash
# Current season, as CI does it
python scripts/mlb_hydrate.py
python scripts/mlb_fetch.py --level mlb --refresh-current --budget 900
python scripts/mlb_fetch.py --level aaa --refresh-current --budget 300

# One past season again (settled days, read feeds and closing lines are skipped)
python scripts/mlb_fetch.py --level mlb --from 2024 --to 2024

# Coverage of the stores and pitch tables on disk
python scripts/mlb_fetch.py --level mlb --report --from 2015 --to 2026

# Retrosheet for one season again
python scripts/mlb_retro.py --from 2025 --to 2025 --refresh --lahman

# Backfill progress (UTF-8 logs)
Get-Content logs\mlb_backfill_savant_mlb.log -Tail 20
```

---

## 14. NPB (the npb level)

Added 13 October 2026. Code: `oddsmarkets/baseball/npb/` (`source.py` client and parsers, `store.py`, `markets.py`),
`scripts/npb_fetch.py`, `scripts/npb_backfill.ps1`.

### 14.1 Sources checked, and their terms

| Source | What it has for NPB | Used? | Terms and notes (checked 13 October 2026) |
|---|---|---|---|
| **npb.jp** (the official site, its Baseball Information System pages) | day pages and box scores 2005 on (the BIS layout to 2025, the `/scores/` layout with every plate appearance in 2026); the month schedules with start times and probable starters (2016 on); yearly league pages 1936 on (standings, team batting and pitching, awards, qualified leaders; 1950 on used); Japan Series results 1950 on; every club's roster by year with NPB ids (1936 on; 1950 on used); every player's profile and year-by-year record; the clubs' individual batting and pitching (2005 on; English 2008 on) | **yes, the only game source** | no robots.txt (404); no terms-of-use page; the footer reads "Copyright (C) 1996-2026 Nippon Professional Baseball Organization. All Rights Reserved. 掲載の情報、画像、映像等の二次利用および無断転載を固く禁じます" (secondary use and unauthorised reproduction prohibited). Handling: one request at a time, 1.2 s apart (1.5 s in the backfill), an identifying User-Agent, every page cached and never re-fetched once its season is over; the site shows only facts in its own layout beside derived numbers, credits NPB, never shows NPB's pages, logos, images or text; the stores are not deployed. A residual risk the owner accepts or not (RUNBOOK section 12, "If NPB objects"). |
| MLB Stats API | `sports` lists NPB as sportId 31 ("jml") and `teams?sportId=31` nine NPB clubs, but `schedule?sportId=31` returns no games for any season | no | — |
| ESPN | no NPB league among its baseball leagues | no | — |
| Sofascore | NPB events with scores | no | blocks datacenter addresses and answers bursts with an IP-wide 403 for hours; the football site's hourly fetch depends on it, so NPB stays off it |
| Kalshi | `KXNPBGAME` (a market per club per game, 27 March 2026 on: 894 events by 12 October), `KXNPB` (Japan Series champion), also `KXNPBSPREAD`, `KXNPBTOTAL`, `KXNPBRFI` | yes: game and champion prices | public read API, no key; candles cached under `data/baseball/cache/kalshi_npb/`; markets settled before Kalshi's historical cutoff need one candle request each |
| Polymarket | no NPB markets found | no | — |
| Baseball-Reference | NPB register pages | **no** | its terms forbid scraping |
| Wikipedia | season articles | no | npb.jp has the same facts from 1950 at the source |
| Farm leagues (Eastern / Western) | box scores and standings on npb.jp | no | another ~1,300 box scores a season; not cheap enough for this pass |
| npb.jp play-by-play (15 October 2026) | every plate appearance 2016 on (count before the last pitch, base-out state, result with the fielder) and pitch counts per pitcher | **yes** (the NPB lab, section 14.2) | same handling as every npb.jp page; only derived statistics are published |
| Pitch-by-pitch feeds on other Japanese sites (portal live pages, club sites, commercial data firms) | pitch type, velocity and location | no | not npb.jp; the level uses npb.jp alone for NPB facts, so no Statcast-like pitch metrics exist for NPB on this site |

### 14.2 Pages, parsers and costs

| Phase | Pages | Parser (`npb/source.py`) | Requests |
|---|---|---|---|
| history | `/bis/yearly/{centralleague,pacificleague}_<S>.html`, `/bis/scores/nipponseries/yearlyresults<decade>.html` | `parse_yearly`, `parse_js_results` | 154 + 8 |
| rosters | `/bis/players/all/index.html` -> `/bis/players/search/yearly/<S>/<club>/`; `/bis/teams/rst_<code>.html` (current) | `parse_roster_index`, `parse_roster_search`, `parse_current_roster` | ~930 + 12 |
| days | `/bis/<S>/calendar/index_<MM>.html` (to 2025; the month schedule in 2026), `/bis/<S>/games/gm<YYYYMMDD>.html` | `parse_calendar`, `parse_day` (both layouts) | ~200 a season |
| boxes | `/bis/<S>/games/s<id>.html` (2005-25), `/scores/<S>/<MMDD>/<h>-<a>-<NN>/box.html` (2026) | `parse_box` (both layouts) | ~870 a season |
| schedule | `/games/<S>/schedule_<MM>_detail.html` | `parse_schedule_month` | 9 a season |
| stats | `/bis/<S>/stats/idb1_<code>.html`, `idp1_<code>.html`, and `/bis/eng/<S>/...` | `parse_team_stats` | 48 a season |
| players | `/bis/players/<id>.html` | `parse_player` (profile, kana reading, career rows) | ~9,000 |
| pbp (15 October 2026) | `/scores/<S>/<MMDD>/<h>-<a>-<NN>/playbyplay.html` (2016 on; `<h>`, `<a>` the season's BIS codes, `<NN>` the meeting number), and the same folder's `box.html` for complete games and the current season | `npb/pbp.py`: `parse_playbyplay`, `parse_box_pitches`, `fill_starters` | ~880 a season (one a game) |

Pages are cached gzipped under `data/baseball/npb/html/<path>.gz` (git-ignored; about 6 KB a box score, 9 KB a
play-by-play page). A day page of the last three days is re-read after 30 minutes; everything older is read once. A 404 is
cached as an empty page.

**What the game pages hold (checked 15 October 2026).** Every game since 2016 has a `/scores/` folder with `index.html`,
`box.html`, `playbyplay.html` and `roster.html`; 2005-2015 games have only the BIS box score (the `/scores/` URLs of 2010,
2014 and 2015 games answer 404). The play-by-play lists each plate appearance's outs and runners before it, the batter with
his NPB id, the count before the last pitch ("2-1より", balls-strikes) and the result in words with the fielder
("センターフライ", "レフト前ヒット", "左中間ツーベース", "空振り三振"), the starting pitchers (2026 layout) and every pitching
change, and the steals, caught stealing and pickoffs between plate appearances; `box.html` adds each pitcher's pitch count.
npb.jp has **no pitch-level data**: no pitch types (球種), velocities (球速), spin or locations, and no pitch-by-pitch
results; the "一球速報" feeds that other Japanese sites show are not on npb.jp and are not used. A hit's trajectory is not
recorded either: an out says ground ball, fly, liner or pop-up; a hit says only how deep it went (infield, in front of an
outfielder, down a line, a gap, over an outfielder). The parsed rows go to `data/baseball/npb/pbp/<S>.json.gz` (git-ignored;
about 0.8 MB a season; CONTRACT.md section 3), rebuilt offline from the page cache with `npb_fetch.py --phases pbp --reparse`.

### 14.3 Identity

Clubs: `npb/canon.py` (ids `91001`-`91017`, BIS letter codes by season: `yb` -> `db` for the BayStars in 2012, `bs`
-> `b` for Orix; Japanese names in every form the pages print, matched by ordered fragments). Players: `n<NPB id>`
from the rosters; the clubs' stat pages carry no ids, so each row is matched to the season's roster by its Japanese
name (`nx<hash>` when no roster has it, e.g. a player released mid-season in the current year); English names come from
the English stat pages, matched row to row on the stat line (2008 on), else the reading romanised (`romanise_name`).
Box scores print surnames (with given-name characters only where club-mates share one): `build.short_map` matches
them to roster names by surname and given-name prefix. Games: `YYYYMMDD-<home code>-<away code>`, the same before and
after the game; `bis` (2005-25) or `scores` (2026) keeps NPB's own reference.

### 14.4 Stores

`docs/bullpen/data/npb/<S>/store.json` (season), `docs/bullpen/data/npb/stores/{history,rosters,people,model_params}.json`.
Formats in `oddsmarkets/baseball/CONTRACT.md` section 3. Writers lock (`store.Lock`) and merge game by game, so the
hourly refresh and the backfill can run together; a thinner record (a day page) never wipes a box score. None of the
stores is deployed (`local_sites.prune_bullpen`); completed seasons' stores and the `stores/` files are un-ignored so
they can be committed by path.

### 14.5 Schedule and backfill

Hourly in season via `scripts/local_sites.py` (site "bullpen", step "Fetch NPB": `npb_fetch.py --refresh-current
--budget 400`, 8-minute timeout; it exits at once from December to February). The backfill is
`powershell -File scripts/npb_backfill.ps1` (history and rosters 1950 on, days and stats 2026 -> 2005, box scores 2026
-> 2005, then players; 1.5 s apart; `logs/npb_backfill.log`; resumable). Coverage: `python scripts/npb_fetch.py
--report --from 2005 --to 2026`.

### 14.6 Coverage (13 October 2026, 18:30 UTC, backfill still running)

| Data | Seasons | Notes |
|---|---|---|
| Standings, team batting and pitching, awards, qualified leaders | 1950-2026 (154 league-seasons) | every club name mapped to its franchise |
| Japan Series results | 1950-2025 (76 series) | 2026 from the box scores when played |
| Club rosters by year (NPB ids) | 1950-2026 | 77 seasons |
| Game results (day pages) | 2005-2026: 19,142 final games | 18,285 priced by the backtest (2006 on); every season's W-L-T rebuilt from the games equals NPB's official standings (`npb_fetch.py --report`) |
| Box scores | 2026 (863); 2005-2025 being fetched | ~19,000 pages, newest first |
| Club stat pages (batting and pitching by player) | 2005-2026, English names 2008-2026 | 2026: 743 batters, 385 pitchers, one stat-page name without a roster id |
| Player career pages | queued after the box scores | ~9,000 players rostered since 1950 |
| Kalshi | 2026: 894 game events (885 matched to games), the champion market | candles cached |
| Play-by-play (15 October 2026, 18:20) | 2018-2026: every final regular-season game (7,584 games, 570,694 plate appearances); 2016-2017 being read (due about 19:40) | pitch counts: 2026 only (box scores of 2016-2025 read for complete games); none exist before 2016; [MODELS.md](MODELS.md) section 24.4 |

## 15. Transactions, official stat lines and minor-league lines (MLB Stats API; added 16 October 2026)

`analytics/mlbapi.py` caches, under `<cache>/statsapi/` (git-ignored, never deployed):

| Input | Endpoint | Calls | Kept |
|---|---|---|---|
| transactions, October 2014 on | `/api/v1/transactions?startDate&endDate&sportId=1` (one call a month; 400-1,500 records) | 145 for the backfill; the current month refreshed when older than 3 hours (one call an hourly build) | a month fetched 10+ days after it ended is final |
| official season lines, 2015 on | `/api/v1/stats?stats=season&group=hitting|pitching&playerPool=ALL&sportId=` (MLB 1; Triple-A 11, Double-A 12, High-A 13, Single-A 14) | 24 for MLB, 96 for the minors | final once fetched after 15 November; the current season refreshed every 6 hours |
| weekly lines, 2022 on | `stats=byDateRange` Monday to Sunday | about 280 | final three days after the week |
| people the crosswalk lacks (trade pieces' birth dates) | `/api/v1/people` (150 ids a call) | 23 | kept |

Backfill: `python -m oddsmarkets.baseball.analytics.mlbapi --from 2015 --to 2026 --weekly-from 2022` (445 calls, 264 s on the
network, 16 October 2026); the minor-league season lines took 96 calls (40 s). The hourly build then needs one or two calls.

**Terms.** statsapi.mlb.com is MLB Advanced Media's; its notice (gdx.mlb.com/components/copyright.txt) permits individual,
non-commercial, non-bulk use. The site is non-commercial, the calls are paced (0.4 s apart, an identifying User-Agent), past
months and seasons are fetched once, and only facts (dates, clubs, players, the kind of move, counting stats inside our own
tables) and our own numbers are published, never MLBAM's descriptions or raw responses. **Left out for terms:** contracts and
salaries (Spotrac, Cot's Contracts, Baseball-Reference and FanGraphs forbid scraping or reuse; no free source with acceptable
terms has them), fantasy ADP, ownership and platform rankings (ESPN, Yahoo, NFBC, FantasyPros terms), prospect rankings and
scouting grades (MLB Pipeline's editorial content, FanGraphs, Baseball America).
