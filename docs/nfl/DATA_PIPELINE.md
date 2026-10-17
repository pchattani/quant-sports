# Data pipeline: extraction and storage (NFL)

How The Quant Gridiron gets its data: the nflverse release mirror and why it is the only
play-level source, ESPN for lines by book and live state, the prediction markets, what each
season holds, identity, the scripts, the store format and the merge rules, what is
committed and what travels with the site, the scheduled job and the backfill. Models are in
[MODELS.md](MODELS.md); the payloads built from the stores are in
[DASHBOARD.md](DASHBOARD.md).

Contents

1. Overview and data flow
2. Sources
3. Coverage by season
4. Identity: `canon.py` and the crosswalks
5. The scripts
6. Formats
7. Merge rules: `store.py`
8. What is committed, what travels with the site, and the caches
9. Scheduling: `.github/workflows/update_gridiron.yml`
10. The backfill
11. Failure modes
12. Known gaps and sharp edges
13. Operator quick reference

---

## 1. Overview and data flow

```
 github.com/nflverse/nflverse-data/releases          site.api.espn.com            sports.core.api.espn.com
 <release>/timestamp.txt, <release>/<file>.parquet    scoreboard, summary          events/<id>/competitions/<id>/odds
        │  (redirect to release-assets.githubusercontent.com)  │                              │
 sources/nflverse.py (timestamp gate, schema check)   sources/espn.py (compact live record, lines by book)
        │                                                      │
        ▼                                                      ▼
 data/nfl/raw/<release>/<file>.parquet + _manifest.json   data/nfl/cache/espn/{summary,odds}/<season>/<game_id>.json[.gz]
        │                                                      │
        ▼               scripts/nfl_fetch.py (per season, newest first;      │
        │               phases releases → schedule → plays → espn → live)    │
        ├──► schedules (games.parquet) → nflverse.compact_game ──► store.merge_game ◄──┘ (lines, live block)
        │                                        │
        │                                        ▼
        │                      docs/gridiron/data/<season>/store.json   (store.save_owned: lock + per-phase fields)
        ▼
 pbp + ftn_charting + pbp_participation ──► data/nfl/derived/<season>/plays.parquet
        │
        ▼
 models (EP, WP, fourth downs, ..., team strength, game, simulations) ──► scripts/build_gridiron.py ──► docs/gridiron/data/** payloads
                                                            ▲
                                                            └── Kalshi, Polymarket (sources/markets.py, at build time)
```

Raw downloads live under `data/nfl/` (git-ignored; env `GRIDIRON_RAW`): `raw/<release>/`
(the mirror, each release with a `_manifest.json`), `derived/<season>/plays.parquet` and
`cache/` (env `GRIDIRON_CACHE`). The data root is `docs/gridiron/data` unless
`GRIDIRON_DATA` points elsewhere.

---

## 2. Sources

### 2.1 The client: `sources/_client.py`

Every source goes through one `Client`: requests spaced per host (`interval`, or
`intervals` keyed by host suffix), up to 4 attempts, a 120 s timeout, a call `budget` per
run. After a network error it sleeps 5 s × the attempt; after HTTP 429 or a 5xx it honours
`Retry-After`, else 10 s × the attempt, at most 120 s. Any other status, or a non-JSON
answer to `get`, is logged, counted in `failures` and returned as `None`: **the client
never raises on a bad answer**. Running out of budget raises `BudgetExhausted`, which
`nfl_fetch` catches to stop cleanly; the next run resumes. `head` returns the final
headers after redirects (GitHub release assets redirect to
`release-assets.githubusercontent.com`, whose ETag, Last-Modified and Content-Length
identify a file version), and `download` streams a body to a `.part` file, checks it
against Content-Length and only then renames it. The user agent is `The Quant Gridiron
(pchattani.github.io/the-quant-gridiron; NFL analytics, non-commercial)`. `report()` gives
calls and seconds per host, failures and megabytes, and `nfl_fetch` logs it at the end of
every run.

`nfl_fetch` makes one client with `--budget` (default 20,000), 0.5 s by default, 0.2 s for
`github.com` and `githubusercontent.com`, and `--espn-interval` (default 1.0 s,
`espn.INTERVAL`) for `espn.com`.

### 2.2 nflverse: `sources/nflverse.py`

The backbone. Release assets download from
`https://github.com/nflverse/nflverse-data/releases/download/<release>/<file>` (not
API-rate-limited). Column names are kept exactly as nflverse publishes them.

| Release | File | Seasons | Used for |
|---|---|---|---|
| `pbp` | `play_by_play_<S>` | 1999→ | every play model and catalogue (372 columns) |
| `schedules` | `games` | all, one file | the stores: results, closing lines, venue, weather, referee, QBs, coaches, ESPN ids (the `pfr` game-id column is dropped from the mirror) |
| `nextgen_stats` | `ngs_{passing,rushing,receiving}` | 2016→, one file per kind | time to throw, separation, cushion, NGS RYOE (season rows, week 0, and weekly rows) |
| `ftn_charting` | `ftn_charting_<S>` | 2022→ | the FTN tiers; play action, RPO, motion, blitzers, drops, interception-worthy throws |
| `pbp_participation` | `pbp_participation_<S>` | 2016–2025 | formation, personnel, box, coverage, pressure, the players on the field; on-field snap counts (`models/_cdata.onfield`) for roster continuity and the edge research's injury feature |
| `depth_charts` | `depth_charts_<S>` | 2001→ | names and positions, the award models; the value pages' QB succession and line starters (latest snapshot) |
| `injuries` | `injuries_<S>` | 2009→ | the game pages' injury lists |
| `rosters`, `weekly_rosters` | `roster_<S>`, `roster_weekly_<S>` | 1999→, 2002→ | positions, the crosswalk fallback; the value pages' current teams and statuses (latest week); each club's opening roster for roster continuity (`_cdata.roster_at_start`). `pfr_id` dropped from the mirror |
| `players` | `players` | one file | the id crosswalk (gsis, ESPN, PFF, OTC, ...); names, birth dates, colleges; draft slots from 2008 only. `pfr_id` and the pre-2008 draft fields are blanked in the mirror (`nflverse.scrub_file`) |
| `espn_data` | `qbr_{season,week}_level` | 2006→ | QBR |
| `stats_player`, `stats_team` | `stats_*_week_<S>` | 1999→ | weekly statistics |
| `contracts` (optional) | `historical_contracts` | one file | OverTheCap contracts and cap hits. Not part of "all": fetched only by name (`nfl_fetch.py --releases contracts`) and published only with `build_gridiron.py --contracts` / `GRIDIRON_CONTRACTS=1`, because OverTheCap's terms do not allow its data on a website without consent (`analytics/contracts.py`) |

**The timestamp gate** (`fetch_file`). Every release carries `timestamp.txt` ("2026-10-01
12:24:05 EDT"), rewritten whenever any of its files changes. Per release and run:

1. read `timestamp.txt` once (cached for the process);
2. a file on disk whose manifest entry carries that timestamp is current: no request;
3. otherwise HEAD the asset: an unchanged ETag (or size and Last-Modified) only refreshes
   the manifest;
4. otherwise download (streamed through `.new` and `.part`), check the Parquet schema
   against the release's required columns (`REQUIRED`), and only then replace the file.

A corrupt or incomplete download never replaces a good file: an unreadable Parquet, a
missing required column or a short body is discarded and the copy on disk kept. A quiet
hour therefore costs one `timestamp.txt` per release and nothing else.

**Schedules → GAME** (`compact_game`): nflverse's `spread_line` is positive when the home
team is favoured, so `spread_home = −spread_line` (the home handicap); kickoff is
`gameday` + `gametime` read as US Eastern and stored as ISO UTC (13:00 when the time is
missing); `status` is `final` when both scores exist, else `scheduled`; stadium
coordinates, altitude and time zone come from `canon.stadium`.

**The derived play table** (`build_plays`): the `PLAY_COLUMNS` subset of play-by-play
(164 columns once joined), FTN charting as `ftn_<col>` (left join on game and play id, from
2022) and participation as `part_<col>` (2016–2025), written as zstd Parquet to
`data/nfl/derived/<season>/plays.parquet`; rebuilt when any input is newer.

### 2.3 ESPN: `sources/espn.py`

The public JSON (no key, CORS `*`), paced at one request a second:

- `site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates=<S>&seasontype=<2|3>&week=<n>`:
  one week (playoffs: week 1 WC, 2 DIV, 3 CON, 5 SB; 4 is the Pro Bowl).
- `…/summary?event=<id>`: drives and plays (start and end down, distance, yards to the end
  zone, scores), ESPN's win probability per play, the pickcenter (DraftKings spread, total
  and moneyline with open and close), the predictor (FPI, not always present), injuries,
  officials, weather, status. `compact_summary` turns it into the contract's compact live
  record (`{espn_id, game_id, status, period, clock, possession, down, distance,
  yardline_100, home_score, away_score, drives, plays [[seq, qtr, clock_s, team, down,
  dist, yl100, type, text, home_score, away_score, wp_home]], wp_home, odds, predictor,
  injuries}`).
- `sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/<id>/competitions/<id>/odds`:
  one item per provider. 2016–2019 offshore and Nevada books (5Dimes, Bovada, Westgate,
  "Opening"), 2019–2024 US books (DraftKings, Caesars, MGM, SugarHouse, ESPN BET),
  2026 DraftKings only. `spread` is the home handicap, signed (verified on 2016, 2019, 2023
  and 2026 events against the moneyline favourite). `initialSpread`/`initialOverUnder`
  (2016–2018) and `open`/`close` blocks (2023 on) give opening and closing lines;
  otherwise `current`, read after the game, is the close.

`compact_lines` keeps every book (`books`), drops in-play rows ("… Live Odds") and the
price-less providers (consensus, teamrankings, numberfire, accuscore, ...), and flags a
book `suspect` when, with three or more books, its spread is more than 3.5 points or its
total more than 5 from the median, or its moneyline favourite disagrees with its spread
favourite at 2.5 points or more. The main book is the first non-suspect one in `PREFERRED`
order (DraftKings first, then ESPN BET, Caesars, MGM, ...); `open`, `close` (with `src`)
and `consensus` (medians, `n_books`) are derived from it and the pool.

**Mapping events to games** (`map_game_id`): the schedules' `espn` column first; then
season, week and teams (`nflverse_id`, trying both orders for neutral sites); then the two
teams and the nearest kickoff within 36 hours.

### 2.4 Prediction markets: `sources/markets.py`

Kalshi (`KXSB` Super Bowl, `KXNFLAFCCHAMP`/`KXNFLNFCCHAMP`, the eight `KXNFL<DIVISION>`
series, `KXNFL1SEED`, `KXNFLPLAYOFF`, `KXNFLWINS` win-total ladders, `KXNFLMVP`,
`KXNFLOPOTY`, `KXNFLDPOTY`, `KXNFLOROTY` and the rest when they list, `KXNFLGAME`,
`KXNFLSPREAD`, `KXNFLTOTAL`, `KXNFLTEAMTOTAL`) and Polymarket (tag `nfl` futures, the fixed
division and postseason slugs, and games via `series_id=12185`), fetched at build time in
CI (never in the browser) and mapped to nflverse abbreviations (`CODE_ALIASES`: JAC→JAX,
LAR→LA, ...) and player names. The price rules are in [MODELS.md](MODELS.md) section 14.

### 2.5 What is not used, and why

- **Pro Football Reference**, directly or through nflverse: its terms forbid scraping and building websites or tools
  on its data. Section 14 lists the nflverse releases and columns this rules out.
- **The NFL's own Next Gen Stats API**: not public; NGS arrives through nflverse.
- **Sofascore**: blocks datacenter addresses (the football site's daily problem,
  `docs/RUNBOOK.md`); nothing here needs it.
- **Player tracking data** (positions and speeds): not public in-season; the models use
  play-by-play, charting and participation only.

---

## 3. Coverage by season

Read with `python scripts/nfl_fetch.py --report --from 1999 --to 2026` on 1 October 2026.
"Lines" counts final games with nflverse's closing spread (S), total (T) and moneyline
(ML); "ESPN" final games with ESPN books, an opening line and a closing line; FTN and
participation count matched plays.

| Season | Games (final) | Plays | FTN | Participation | Lines S / T / ML | ESPN books / open / close |
|---|---|---|---|---|---|---|
| 1999–2001 | 259 | 44,969–46,136 | 0 | 0 | 259 / 259 / 0 | 0 |
| 2002–2005 | 267 | 46,705–47,355 | 0 | 0 | 267 / 267 / 0 | 0 |
| 2006 | 267 | 46,299 | 0 | 0 | 267 / 267 / 220 | 0 |
| 2007–2009 | 267 | 45,917–46,519 | 0 | 0 | 267 / 267 / 194–266 | 0 |
| 2010–2015 | 267 | 46,892–48,158 | 0 | 0 | 267 / 267 / 267 | 0 |
| 2016 | 267 | 47,651 | 0 | 47,651 | 267 / 267 / 267 | 0 |
| 2017–2019 | 267 | 47,109–47,260 | 0 | 47,109–47,260 | 267 / 267 / 266–267 | 265–267 / 0 / 265–267 |
| 2020 | 269 | 47,705 | 0 | 47,704 | 269 / 269 / 269 | 269 / 0 / 269 |
| 2021 | 285 | 49,922 | 0 | 49,922 | 285 / 285 / 285 | 285 / 0 / 285 |
| 2022 | 284 | 49,434 | 41,643 | 49,434 | 284 / 284 / 284 | 284 / 0 / 284 |
| 2023 | 285 | 49,665 | 48,225 | 46,168 | 285 / 285 / 285 | 285 / 128 / 285 |
| 2024–2025 | 285 | 48,771–49,492 | 47,316–48,031 | 45,184–45,919 | 285 / 285 / 285 | 284–285 / 284–285 / 284–285 |
| 2026 (to 1 Oct) | 272 (48) | 8,311 | 8,065 | 0 | 48 / 48 / 48 | 48 / 48 / 48 |

Notes: the ML column is the nflverse schedules' moneyline (none before 2006; 2008 has 194
of 267). Every game of every season has an ESPN id. NGS rows (passing / rushing /
receiving) run about 575–620 / 580–650 / 1,400–1,600 a season from 2016, season rows
(week 0) and weekly rows together; 2026 has 135 / 141 / 323 after three weeks. The
crosswalk (`players`) holds 24,838 gsis ids, 16,569 with an ESPN id (its PFR ids are no
longer kept).

---

## 4. Identity: `canon.py` and the crosswalks

### 4.1 Teams

A team is the nflverse abbreviation it used that season; `canon.FRANCHISES` keeps each
franchise's history (first season, abbreviation, full name) and `RELOCATIONS` maps the
three moves in the data window: STL→LA from 2016, SD→LAC from 2017, OAK→LV from 2020
(Washington's three names keep `WAS`). `franchise(team)` gives the current key of any
abbreviation (nflverse or ESPN), `abbr(team, season)` the one used that season. ESPN's
numeric team ids (all 32 verified on the 2026 week-4 scoreboard) and ESPN abbreviations
(`LAR`, `WSH`, `JAC`) map through `ESPN_TEAM_ID` and `ESPN_ABBR`. Divisions: the
six-division, 31-team alignment for 1999–2001 and the eight-division alignment from 2002
(`alignment`).

### 4.2 Formats

`canon.formats(season)`: 16 games and 17 weeks to 2020, 17 games and 18 weeks from 2021;
6 playoff clubs a conference with two byes to 2019, 7 with one bye from 2020; reseeding
every round; nflverse numbers the playoff weeks on from the regular season (WC = last
regular week + 1, ..., SB = + 4).

### 4.3 Stadiums

`canon.STADIUMS`: 67 nflverse `stadium_id`s with name, city, country, latitude and
longitude, altitude (metres), roof type (outdoors, dome, retractable) and IANA time zone,
hand-entered and checked against the schedules (every id used 1999–2026 present; every
regular home ground within 80 km of its club's city; roof types agree with nflverse's
per-game roof). Surface is per game, from the schedules.

### 4.4 Players and games

Players are gsis ids throughout (play-by-play's `passer_player_id`, ... columns); names,
positions, birth dates, college and draft (2008 onward only) come from the `players` crosswalk, with the
season rosters as the fallback (`analytics/people.py`). Games are nflverse `game_id`s;
ESPN events map to them as in section 2.3.

### 4.5 The tiebreaking procedure

`canon.DIVISION_TWO`, `DIVISION_THREE`, `WILDCARD_TWO` and `WILDCARD_THREE` hold the
NFL's published steps, each with the NFL's wording, from
https://www.nfl.com/standings/tie-breaking-procedures (read 1 October 2026; the
operations.nfl.com page answers 404); `TIEBREAK_NOTES` the notes and
`TIEBREAK_INTERPRETATION` the six readings where the text is silent (ties count half;
strength of victory and schedule count every game; competition ranking for points ranks;
an empty category is 0.5; net touchdowns need touchdown counts, else the step passes to
the coin; the coin is a seeded draw). `oddsmarkets/nfl/tiebreak.py` (`Table`) applies them.

---

## 5. The scripts

### 5.1 `scripts/nfl_fetch.py`: sources into the mirror and the stores

```
python scripts/nfl_fetch.py --from 1999 --to 2026                       # releases + stores + plays
python scripts/nfl_fetch.py --from 2017 --to 2026 --phases espn --espn --log logs/nfl_backfill_espn.log
python scripts/nfl_fetch.py --refresh-current --espn                    # the scheduled job (with --budget 1500)
python scripts/nfl_fetch.py --report --from 1999 --to 2026
```

| Flag | Meaning |
|---|---|
| `--from`, `--to` | seasons (default: the current season); processed **newest first** |
| `--phases` | any of `releases,schedule,plays,espn,live` (default `releases,schedule,plays`) |
| `--releases` | comma list of releases, `all` (default) or `none` |
| `--espn` | add the `espn` phase (and `live` with `--refresh-current`) |
| `--espn-from` | first season for ESPN odds (default 2017, `canon.ESPN_ODDS_FROM`) |
| `--espn-interval` | seconds between ESPN calls (default 1.0) |
| `--budget` | calls per run (default 20,000) |
| `--refresh-current` | scheduled mode: the current season only (and the season-less files) |
| `--force-plays` | rebuild the derived play table even when it is newer than its inputs |
| `--log` | also log to a file |
| `--report` | print the coverage of the stores and the mirror on disk and exit |

The phases, per season:

- **releases**: every file of every selected release for the season (and the season-less
  files once) through the timestamp gate (`schedules`, `players`, `rosters` and
  `weekly_rosters` are scrubbed of their PFR columns as each file lands).
- **schedule**: `games.parquet` is fetched once if missing; every row of the season becomes
  a GAME (`compact_game`) merged into the store; games nflverse dropped (a rescheduled id)
  are deleted; `teams` = `canon.teams(season)` plus each club's most-used home stadium, its
  latest head coach and its regular-season record, points for and against;
  `meta.complete_through`, `meta.sources.schedules` (the release timestamp) and
  `meta.format` are set.
- **plays**: the derived play table, when an input is newer.
- **espn** (seasons from `--espn-from`): one core odds call per final game, read once after
  the game (re-read when the earlier read was before kickoff + 3 h); with
  `--refresh-current`, also games kicking off from 4 hours ago to 7 days ahead, re-read
  when older than 1 hour within 36 hours of kickoff, else 12 hours. The raw answer is
  saved gzipped under `cache/espn/odds/<S>/<game_id>.json.gz`; `compact_lines` writes the
  ESPN half of `lines` (`open`, `close`, `books`, `consensus`, `espn_src`). The store is
  saved every 50 calls.
- **live** (current season, with `--espn --refresh-current`): the scoreboard of every week
  with a kickoff within two days of now (statuses, and any ESPN id the schedules lacked),
  then the summary of every game in play, kicking off within 24 hours, or final within 36
  hours without a final summary. The compact live record goes to
  `cache/espn/summary/<S>/<game_id>.json`; a small `live` block (status, detail, period,
  clock, possession, down, distance, yardline_100, scores, `wp_home`, the DraftKings `dk`
  open and close, `at`) goes onto the GAME, with its status and score when live or final.

Each phase saves through `store.save_owned` (section 7), and the run logs the client's
report at the end.

### 5.2 `scripts/nfl_fit.py`: the committed fits

Runs builder B's exporters in order (`ep, wp, kicking, completion, yac, ryoe, pressure,
player_value, fourth_down, qb, stabilise`; each module's `export_fits(seasons)` writes its
LightGBM boosters as `<name>_<key>.txt.gz` and the rest as `<name>.json` under
`models/fitted/`) and builder C's `fit_c.fit_all(committed=True)` (team-strength
carry-over, the walk-forward game fit, the drive model, the award models, the
season-simulation constants, then the backtest that writes `calibration.json`). Every step
is isolated. `--only b|c`, `--models ep wp ...`, `--through <S>` (default the last
completed season), `--first` (default 1999). See [MODELS.md](MODELS.md) and
[RUNBOOK.md](RUNBOOK.md) section 4.

### 5.3 `scripts/nfl_hydrate.py`: the current season from the live site (CI)

```
python scripts/nfl_hydrate.py                    # the current season
python scripts/nfl_hydrate.py --season 2026 --base https://example.org/data
```

Fetches `https://pchattani.github.io/the-quant-gridiron/data/<S>/store.json` and keeps it
when it is newer than the checkout's (by `updated_at`), writing atomically. A 404 (the
first deploy, or a season not yet published) is not an error; a non-JSON answer is ignored.
Play-by-play is not hydrated: CI restores the mirror from the Actions cache and the
timestamp-gated fetch tops it up.

---

## 6. Formats

### 6.1 Season store: `docs/gridiron/data/<season>/store.json`

```
{"season", "updated_at",
 "teams": {abbr: {"abbr","franchise","name","conf","div","espn_id","city","lat","lon",
                  "stadium","stadium_name","coach","record": [w,l,t],"pf","pa"}},
 "games": {game_id: GAME},
 "meta":  {"fetched", "complete_through" (last week with every game final), "espn_odds" {game_id: {at, books, items}},
           "sources": {"schedules": {timestamp, at}}, "format" (canon.formats), "live_at"}}
```

A GAME:

```
{"game_id", "season", "week", "gtype": REG|WC|DIV|CON|SB, "date", "weekday", "kickoff" (ISO UTC),
 "home", "away", "hs", "as", "status": scheduled|live|final|postponed, "neutral",
 "stadium", "stadium_name", "roof", "surface", "lat", "lon", "altitude_m", "tz", "temp", "wind", "referee",
 "home_qb", "away_qb", "home_qb_name", "away_qb_name", "home_coach", "away_coach", "home_rest", "away_rest",
 "lines": {"spread_home", "total", "ml_home", "ml_away", "spread_price": [h, a], "total_price": [o, u], "src": "nflverse",
           "open", "close" ({spread_home, total, ml_home, ml_away, spread_price, total_price, src}),
           "books": [{id, name, spread_home, total, ml_home, ml_away, spread_price, total_price, open, close, suspect}],
           "consensus": {spread_home, total, ml_home, ml_away, n_books}, "espn_src"} | null,
 "espn_id", "gsis", "old_game_id", "overtime", "div_game",          (no "pfr_id": dropped 16 Oct 2026, store.scrub)
 "live": {status, detail, period, clock, possession, down, distance, yardline_100, home_score, away_score,
          wp_home, dk: {open, close, spread_home, total, ml_home, ml_away}, at} (current season)}
```

`spread_home` is the home team's line, negative when the home team is favoured. Games are
saved sorted by kickoff. Store sizes: about 240 KB a season to 2016; 0.5–1.3 MB from 2017
(the ESPN books; 2023, with the most books listed, is the largest at 1.3 MB).

### 6.2 Release manifest: `data/nfl/raw/<release>/_manifest.json`

`{"release", "timestamp", "files": {file: {"etag", "last_modified", "size", "timestamp",
"at", "rows", "columns", "bytes", "checked_at"}}}`: the gate's memory.

### 6.3 Compact live record: `data/nfl/cache/espn/summary/<S>/<game_id>.json`

As in section 2.3. The game pages read it for games the play-by-play does not yet cover
(ESPN's plays and win probability, `wp.source` "espn").

### 6.4 Derived plays: `data/nfl/derived/<S>/plays.parquet`

`nflverse.PLAY_COLUMNS` (the play-by-play columns the models need, as published) +
`ftn_<col>` (`FTN_COLUMNS`) + `part_<col>` (`PART_COLUMNS`). About 5 MB a season to 2005,
7 MB to 2015 and 8.2–8.7 MB from 2016 (with participation).

---

## 7. Merge rules: `store.py`

**Insert or update** (`merge_game`): a new record never lets a thinner one wipe richer
fields: `lines`, `espn_id`, `referee`, `temp`, `wind`, `home_qb`, `away_qb` and `live` are
kept when the new value is empty; nflverse's line keys update in place inside `lines`
while ESPN's are kept; a schedule rescan that says `scheduled` for a game ESPN already
has as live or final keeps the live status and scores.

**Concurrent writers** (`save_owned(store, phases)`): under a lock file beside the store
(`store.json.lock`; waits up to 300 s, breaks a lock older than 600 s), the store is
re-read from disk and only the fields the given phases own are merged in:

| Phase | GAME fields | `meta` keys | top-level |
|---|---|---|---|
| schedule | the whole GAME except ESPN's half of `lines` (and the live block) | `complete_through`, `sources`, `fetched`, `coverage` | `teams` |
| espn | `lines`: `open`, `close`, `books`, `consensus`, `espn_src` | `espn_odds`, `espn_scan` | – |
| live | `live`, and `status`, `hs`, `as` when live or final | `live_at` | – |

So the paced ESPN odds backfill and a schedules rebuild can run on the same season at
once. The in-memory store is replaced with the merged result after each save.

`complete_through` is the last week through which every game is final.

---

## 8. What is committed, what travels with the site, and the caches

| What | Where | In git | On the public site | In the Actions cache |
|---|---|---|---|---|
| Completed seasons' stores | `docs/gridiron/data/<S>/store.json` | yes (1999–2025) | yes | – |
| Current season's store | same | **no** | yes (hydrated back each run) | – |
| Calibration | `docs/gridiron/data/calibration.json` | yes | yes | – |
| Fitted models | `oddsmarkets/nfl/models/fitted/` (30 files) | yes | – | – |
| Payloads and manifests | everything else under `docs/gridiron/data/` | no | yes (restored with `--ignore-existing`) | – |
| The nflverse mirror and derived plays | `data/nfl/{raw,derived}/` | no | no | yes (`gridiron-raw-<season>-<run_id>`; restored by season prefix) |
| Model and analytics caches, ESPN records | `data/nfl/cache/` | no | no | yes (`gridiron-cache-<run_id>`) |
| ESPN transactions (16 Oct 2026) | `data/nfl/cache/espn/transactions/<year>.json` | no | no (parsed into `<S>/transactions.json`, `ledgers/`) | with the cache |
| Fantasy frames (16 Oct 2026) | `data/nfl/cache/analytics/fantasy/{pw,tw}_<S>_<sig>.parquet` | no | no | with the cache |
| Fantasy fit and backtest | `oddsmarkets/nfl/models/fitted/fantasy.json` | yes | summarised in `fantasy_backtest.json` | – |

The `.gitignore` block: `docs/gridiron/data/**` ignored, then `*/`, `*/store.json` and
`calibration.json` un-ignored. Because the store pattern matches the current season too,
commit stores by explicit path.

In CI, `nfl_fetch --refresh-current` mirrors only the current season's release files and
the season-less ones, so the play models' **fits** for every earlier season come from
`models/fitted/` whenever the cache is cold (`_io.get_fit`: the cached fit when its version
matches, else the committed one), and past seasons' payloads come from the previous deploy:
a past season with no play-by-play on the machine is skipped ("play-by-play not on this
machine; payloads kept").

---

## 9. Scheduling: `.github/workflows/update_gridiron.yml` ("Gridiron Hourly Update")

`cron: '52 * * * *'` and `cron: '7,22,37 * * * *'`, plus `workflow_dispatch`;
`concurrency: gridiron-build` (not cancelled in progress); 55-minute job;
`permissions: contents: read`. The local hourly Windows task
(`scripts/refresh_sofascore_all.ps1`) also dispatches it, because GitHub drops many
scheduled runs (RUNBOOK section 1).

| Step | Timeout | On failure |
|---|---|---|
| Game-window check: a dispatched run or the `:52` run always continues; a `:07/:22/:37` run reads the deployed `index.json` and continues only if a game in `games` or `live` is live, or kicks off between 30 minutes from now and 4 h 30 ago (no index: wait for the hourly run) | – | the rest is skipped |
| Checkout, Python 3.11, `pip install uv`, `uv sync` | – | job fails |
| Season: `canon.current_season()` | – | job fails |
| Restore `data/nfl/raw` and `data/nfl/derived` (key `gridiron-raw-<season>-<run_id>`, restore prefix `gridiron-raw-<season>-`) | – | cold mirror |
| Restore `data/nfl/cache` (key `gridiron-cache-<run_id>`, prefix `gridiron-cache-`) | – | cold caches (committed fits used) |
| Clone the public repo with the deploy key; `rsync -a --ignore-existing /tmp/prev/data/ docs/gridiron/data/` | 10 min | continue (cold build) |
| `nfl_hydrate.py` | 5 min | continue |
| `nfl_fetch.py --refresh-current --espn --budget 1500` | 15 min | continue |
| `build_gridiron.py --game-page-seasons 2` | 30 min | job fails |
| Prune `docs/gridiron/data/<S>/games/` for seasons ≤ current − 2 | – | job fails |
| Deploy: clone the public repo, `rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/gridiron/ /tmp/site/`, commit "Site update <UTC stamp>" (only when something changed), push | – | job fails |

The restore step uses `--ignore-existing`, so the checkout's committed inputs (completed
stores, `calibration.json`) win over the deployed copies; the hydrate step then replaces the
current season's store with the deployed one when it is newer. A typical hourly run calls
github.com for about fifteen `timestamp.txt` files (plus a HEAD and a download for each file
whose release moved), ESPN for a week's scoreboard, the odds of upcoming games and the
summaries of games in play, and the markets once at build time.

---

## 10. The backfill

Run once on the owner's machine on 1 October 2026 (local times in the logs are US Eastern):

```
python scripts/nfl_fetch.py --from 1999 --to 2026 --log logs/nfl_backfill_nflverse.log
python scripts/nfl_fetch.py --from 2017 --to 2026 --phases espn --espn --log logs/nfl_backfill_espn.log
python scripts/nfl_fit.py
```

The nflverse pass (1 October 2026, before PFR's releases were dropped) mirrored 15 releases (`{'pbp': 28, 'schedules': 1, 'nextgen_stats': 3,
'ftn_charting': 5, 'pbp_participation': 10, 'pfr_advstats': 40, 'snap_counts': 15,
'depth_charts': 26, 'injuries': 18, 'rosters': 28, 'weekly_rosters': 25, 'players': 1,
'espn_data': 2, 'stats_player': 28, 'stats_team': 28}` files) in 531 calls, 608 MB and 193 s,
and built the 28 stores and play tables (about 0.6 s a season). The ESPN pass made 2,542
core odds calls for 2026 back to 2017 (about 1.1 s a call, 0 failures, 2,765 s); one 503 was
retried.

The backfill is resumable and idempotent: the timestamp gate skips current files, the
schedule phase rebuilds the store from the schedules, and the ESPN phase reads a final
game's odds once (`meta.espn_odds`).

---

## 11. Failure modes

| Symptom | Cause | Effect |
|---|---|---|
| `timestamp.txt` unreadable | GitHub hiccup | every file is HEADed instead (more calls, same result) |
| `unreadable Parquet` / `missing required columns ...; discarded` | a broken download or a schema change upstream | the copy on disk is kept; a schema change needs `REQUIRED` and the loaders updated |
| `download ... expected N` | a truncated body | discarded; retried next run |
| ESPN 5xx / timeouts | ESPN | that call is skipped; live state stale until the next run |
| a game without ESPN lines | no ESPN id, or the odds endpoint empty | nflverse's closing line still prices the backtest; the page shows no books |
| `BudgetExhausted` in the log | the run's budget spent | stops cleanly; the next run continues |
| `TimeoutError: lock ... held too long` | another writer kept the store lock past 300 s | the phase's save fails; re-run (a lock older than 600 s is broken) |
| the hydrate 404s | first deploy, or a new season | the checkout's store (or none) is used; CI rebuilds the season's store from the schedules on the next fetch |

---

## 12. Known gaps and sharp edges

1. **Participation is published only after each season** (2016–2025 on disk); in-season
   models run without it.
2. **Moneylines start in 2006** (and 2006 and 2008 are incomplete), so the moneyline
   comparison starts there; spreads and totals go back to 1999.
3. **ESPN books start in 2017** (`ESPN_ODDS_FROM`); opening lines exist from 2023
   (128 games of 2023, all from 2024). `sources/espn.py`'s docstring says the core odds
   history runs "2016->"; the fetcher starts at 2017.
4. **The current season's store exists only on the deployed site.** If the public repo is
   lost, the next fetch rebuilds the store from the schedules (results, lines), but the
   ESPN books of past weeks and the live blocks are re-read only for games CI still touches;
   recover with a local `nfl_fetch.py --from <S> --to <S> --phases espn --espn`.
5. **Neutral-site games** can appear in nflverse with the teams in either order; the ESPN
   mapping tries both.
6. **Stadiums, divisions and formats are hand-entered** in `canon.py` (checked against the
   schedules on 1 October 2026); a new stadium id needs an entry or its games lose
   coordinates, altitude and time zone.
7. **NGS rows are only for players who qualify** in nflverse's file (weekly and season).

---

## 13. Operator quick reference

```bash
# Current season, as CI does it
python scripts/nfl_hydrate.py
python scripts/nfl_fetch.py --refresh-current --espn --budget 1500

# One past season again (the gate skips current files; --force-plays rebuilds the play table)
python scripts/nfl_fetch.py --from 2024 --to 2024 --force-plays

# ESPN books for a season
python scripts/nfl_fetch.py --from 2025 --to 2025 --phases espn --espn

# Coverage of the stores and the mirror on disk
python scripts/nfl_fetch.py --report --from 1999 --to 2026

# Backfill progress (UTF-8 logs)
Get-Content logs\nfl_backfill_espn.log -Tail 20
```


## 14. Sources added 16 October 2026 (valuation, transactions, fantasy)

- **ESPN transactions** — `site.api.espn.com/apis/site/v2/sports/football/nfl/transactions?season=<calendar year>&limit=1000&page=<p>`
  (`sources/espn.transactions`): free-text club notes, one call per 1,000; the build fetches the current and previous
  calendar years at most every six hours (a week for the previous year). The same public ESPN site data the site already
  uses for live scores, credited on the page.
- **nflverse players release, draft fields** — the draft-pick value curve uses `draft_year`, `draft_round`, `draft_pick` for
  2008 onward only: nflverse-players takes those from the NFL's draft API (`nflapi_draft_report`); earlier years are scraped
  from Pro Football Reference and are not used.
- **nflverse weekly player and team stats, injuries, weekly rosters** (already mirrored) feed the fantasy frames; play-level
  usage comes from the play-by-play.
- **Left out for terms**: nflverse `trades` (Lee Sharpe's table, "via PFR"), `draft_picks` ("courtesy of PFR") and
  `snap_counts` ("provided by Pro Football Reference") — sports-reference.com/data_use: "you should not create websites or
  tools based on data you scrape from Sports Reference"; OverTheCap contracts (as before); fantasy-platform ADP, ownership
  and salaries.

### 14.1 Pro Football Reference: resolved 16 October 2026

Flagged above: `snap_counts` and `pfr_advstats` were mirrored and `snap_counts` was read by `models/team_strength.py`
(roster continuity) and `edge/features.py` (the injury feature); pre-2008 draft slots in the players release are
scraped from PFR. Resolved by removing every PFR-origin input:

- **Not fetched** (`sources/nflverse.LEFT_OUT`; `fetch_file` raises): `snap_counts`, `pfr_advstats`, `trades`,
  `draft_picks`, `combine`. The local mirrors `data/nfl/raw/snap_counts` and `data/nfl/raw/pfr_advstats` were
  deleted, with the edge caches built from them (`wf_cont.parquet`, `preds_inj.pkl`, `preds_mr_inj_pace.pkl`).
- **Scrubbed from permitted releases** as each file lands and once over the existing mirror (`scrub_file`): the
  schedules' `pfr` game id, `pfr_id` in `players`, `rosters` and `weekly_rosters`, and the players release's
  `draft_year/round/pick/team` before 2008 (from 2008 they come from the NFL's draft API). `people.py` also drops any
  draft before 2008, so player pages show a draft only from 2008 (and no longer say "Undrafted" when the draft is
  unknown).
- **Stores**: GAME records no longer carry `pfr_id` (`compact_game`); `store.load`/`save` strip it, and the 28 season
  stores were rewritten without it (nothing else changed).
- **Replacements**: on-field snaps are counted from the play-by-play participation (`_cdata.onfield`: NGS to 2022,
  FTN from 2023; 2016–2025, published after each season). Roster continuity = share of last season's participation
  snaps played by players on each club's first regular-season weekly roster of this season (`_cdata.roster_at_start`;
  seasons from 2017; correlation with the snap-count version 0.91–0.98 a season, 2017–2026). The injury feature
  weights by the same participation shares (2016–2025; 0 for other seasons, including the current one).
- **Effect**: none on any published number. The continuity coefficient is 0 in the committed fit, so team strength,
  the game model and everything downstream are unchanged (checked: identical preseason priors with and without
  continuity); the injury feature is used only by edge experiments, not by the promoted market blend. MODELS.md
  section 19 and docs/research/nfl_edge.md section 3 have the experiment numbers before and after.
