# Data pipeline: extraction and storage (basketball)

This document covers how NBA and WNBA data enters the repository, where it is
stored, how play-by-play is turned into model inputs, and how it all stays current.
It is written for whoever maintains the fetchers or needs to read the stores. Every
constant below was read from the code and names its file; where a docstring and the
code differ, the code is followed and the difference is noted. Figures about what is
on disk were read from the files on 1 October 2026, after both backfills finished and
the stores were repaired (section 3).

| Section | Covers |
|---|---|
| 1 | overview and data flow |
| 2 | the sources: ESPN, the prediction markets, and what is not used |
| 3 | coverage by season |
| 4 | the scripts: fetch, derive, pack, hydrate |
| 5 | the formats: store, GAME, raw play-by-play, derived tables |
| 6 | play-by-play reconstruction: `pbp.py` |
| 7 | identity and seasons: `canon.py` |
| 8 | what is committed, what travels with the site, the model caches |
| 9 | scheduling: the hourly workflow |
| 10 | the backfill |
| 11 | failure modes |
| 12 | known gaps and sharp edges |
| 13 | operator quick reference |

---

## 1. Overview and data flow

```
 ESPN site API (site.api.espn.com)                           Kalshi, Polymarket
   scoreboard (one day per call), summary (box, plays,         futures, win totals,
   win probability, pickcenter, injuries, header),             game prices
   teams, roster, injuries; v2 standings; core season dates         │
         │                                                          │ build time only
         │ scripts/bb_fetch.py (sources/espn.py, Client)            │ (sources/markets.py)
         ▼                                                          │
 docs/hardwood/data/<L>/<S>/store.json ─────────────┐               │
         │                                          │               │
         └─► data/basketball/pbp/<L>/<S>/<id>.json.gz (raw, git-ignored; Actions cache in CI)
                          │ scripts/bb_derive.py (pbp.py)
                          ▼
         docs/hardwood/data/<L>/<S>/{shots.json, stints.json}(+ .gz), recon.json
                          │
                          ▼
         scripts/build_hardwood.py ──► payloads under docs/hardwood/data/ (git-ignored)
                          │
                          ▼ rsync to the public repo (stores and .gz inputs travel with the site)
         https://pchattani.github.io/the-quant-hardwood/data/... ──► scripts/bb_hydrate.py (next CI run)
```

Three rules hold throughout:

- **Fetchers write the stores, the build reads them.** `scripts/bb_fetch.py` is the
  only writer of `store.json` and the raw play-by-play; `scripts/bb_derive.py` the
  only writer of the derived tables. `scripts/build_hardwood.py` never calls ESPN; its
  only network calls are the market prices (skipped with `--no-market`).
- **Everything is resumable.** The fetcher skips days already scanned and games
  already fetched as final; the deriver re-parses only games whose fetch stamp
  changed. Stores and tables are written to a `.tmp` file and renamed into place
  (`store._write_json`, `store.save_table_gz`).
- **No season input is lost when the raw files are absent.** The deriver keeps the
  rows of games whose raw play-by-play is not on the machine, and the build never
  replaces a game page built with play-by-play by one built without it.

---

## 2. Sources

### 2.1 ESPN: `oddsmarkets/basketball/sources/espn.py`

ESPN's public JSON services need no key and state no rate limit. They answer
GitHub's runners and send `Access-Control-Allow-Origin: *`. League is `nba` or
`wnba` in every path.

| Endpoint | Base | Used for |
|---|---|---|
| `scoreboard?dates=YYYYMMDD&limit=200` | `SITE = https://site.api.espn.com/apis/site/v2/sports/basketball/<league>/` | one day's events (`scoreboard`, `scoreboard_raw`); `leagues[0].calendar` lists the season's game days (`calendar`). One day per call: a multi-day range answers with something that is not JSON. |
| `summary?event=<id>` | `SITE` | one game: `header`, `boxscore`, `plays`, `winprobability`, `pickcenter`, `predictor`, `injuries`, `gameInfo` (`summary`, `compact_game`, `compact_pbp`) |
| `teams?limit=100`, `teams/<id>/roster`, `injuries` | `SITE` | team records, today's rosters (with dates of birth), today's injuries |
| `standings?season=Y&level=3` | `SITE_V2 = https://site.api.espn.com/apis/v2/sports/basketball/<league>/` | conferences and (NBA) divisions of any season (`standings`) |
| `seasons/Y[/types/N]` | `CORE = https://sports.core.api.espn.com/v2/sports/basketball/leagues/<league>/` | start and end dates of a season and of its types 1, 2, 3, 5 (`season_dates`; US dates) |

**The client** (`Client(budget=2000, interval=0.5, retries=4)`):

| Constant | Value | Meaning |
|---|---|---|
| `interval` | 0.5 s (CLI `--interval`; the backfill ran at 0.6) | minimum spacing between calls |
| `retries` | 4 | attempts per call |
| `budget` | 2,000 by default (CLI `--budget`) | calls per run; reaching it raises `BudgetExhausted`, which stops a run cleanly |
| `TIMEOUT` | 30 s | per request |
| `HEADERS` | `User-Agent: The Quant Hardwood (pchattani.github.io/the-quant-hardwood)` | |
| back-off | network error: 3 s × attempt; HTTP 429 or 5xx: `Retry-After` or 10 s × attempt | |
| `MIN_PBP_PLAYS` | 50 | plays other than types 411 / 412 / 402 (period start, period end, game end); fewer means no real play-by-play |
| `NO_COORD` | −1,000,000 | ESPN writes about −2.1e8 for a play without a location; anything below is dropped |

Any other non-200 status, or an answer that is not a JSON object, is logged and
returns `None`; the client never raises on a bad game. `used`, `failures` and
`seconds` are counters the fetch script logs at the end of a run.

**Shapes verified on 1 October 2026** (module docstring; fixtures in
`tests/basketball/fixtures/`): box minutes are whole minutes; before about 2007
`plusMinus` is 0 for everyone (stored as null) and points in the paint are −1
(stored as null); old team box scores put every turnover under `teamTurnovers`, so
the team `tov` is `totalTurnovers` and `team_tov` is that minus the players'
turnovers; summary `injuries` and `standings` describe today, not the game's date.

The module docstring also says "games before about 2017 have no plays"; the backfill
found play-by-play much further back (section 3).

### 2.2 Prediction markets: `oddsmarkets/basketball/sources/markets.py`

Kalshi and Polymarket are read at build time only, in CI and locally, never from the
browser (Kalshi sends no CORS headers for other sites). Polymarket is read through
its gamma API by tag (`nba`, `wnba`); Kalshi by series ticker. The series, the
thin-market rule and the name matching are in [MODELS.md](MODELS.md) section 10.
The DraftKings line comes from ESPN's `pickcenter` and is stored with each game.

### 2.3 What is not used, and why

| Source | Why not |
|---|---|
| `cdn.nba.com`, `stats.nba.com` | blocked by Akamai both from the owner's machine and from GitHub Actions |
| Basketball-Reference | its terms forbid scraping |
| `nba.com`, `wnba.com` | not used for data (the award winners in `models/award_winners.py` were cross-checked against them by hand) |

---

### 2.1b ESPN athletes, drafts and transactions (16 Oct 2026)

| Endpoint | Used for |
|---|---|
| `sports.core.api.espn.com/v2/sports/basketball/leagues/<league>/athletes/<id>` | `dateOfBirth`, `draft {year, round, selection, team}`, `debutYear` (`athlete_raw`, `parse_athlete`; WNBA records carry no draft) |
| `SITE/draft?season=Y` | every pick of a draft with the ESPN athlete id (`athlete.alternativeId`), including picks who never played (`draft_raw`, `parse_draft`); NBA 2003 on, WNBA about 2017 on (earlier years answer 404) |
| `SITE/transactions?season=Y&limit=200&page=N` | the transactions feed, newest first; `season` is the CALENDAR year; free text only, one row per team per day (`transactions_page`, `parse_transactions`) |

`scripts/bb_bio.py` (run by hand; `--league nba|wnba`, `--budget`, `--interval 0.6`, resumable, saves every 100 players)
writes `docs/hardwood/data/<league>/bio.json` (committed). First run 15-16 Oct 2026: NBA 4,426 players asked (4,459 calls,
0 failures, 49 min; 4,025 dates of birth), WNBA 1,668 (1,684 calls, 3 failures, 19 min; 1,189 dates), 24 NBA and 12 WNBA
draft years. A player ESPN answers without a date is re-asked after 120 days; a past draft once. The build never calls it;
new rookies get their date from the rosters phase as before.

Transactions: `analytics/moves.py load_transactions` keeps `<cache>/transactions/<league>_<year>.json` for this calendar
year and last. A past year is fetched once (all pages, about 5 calls); this year's newest page is refreshed by the build at
most every 3 hours (a full refresh daily), skipped with `--no-market`; a failed refresh keeps the cache.

Left out because their terms forbid reuse: Basketball-Reference, Spotrac, HoopsHype (salaries, contracts, cap) and every
fantasy platform's rankings, ownership and ADP. The site therefore checks no cap and has no ownership data (waiver lists use
our own season-start ranks as the proxy).

## 3. Coverage by season

`canon.py` declares `BOX_FROM = {"nba": 1997, "wnba": 1997}` and
`PBP_FROM = {"nba": 2017, "wnba": 2017}`, and its comment says play-by-play with
coordinates starts about 2017. The backfill shows ESPN reaches further back than
that. What the stores and raw files held on 1 October 2026 (`recon.json` summaries,
store statuses, and a sample of raw files):

**NBA** (backfill finished; every final game has a box score):

| Seasons | Games final | With play-by-play | Derived: all players within 60 s / points exact |
|---|---|---|---|
| 2027 | 0 of 1,273 | — | preseason; the scheduled Cup final is already `cup` |
| 2020–2026 | 1,220–1,394 a season | all | 83–99 % / 99.2–99.9 % |
| 2007–2019 | 1,104–1,436 a season | 97–100 % | 72–96 % / 96–99.7 % (2013: 65 % points exact; 2016: 49 %) |
| 2006 | 1,438 | 1,405 | 74 % / 76 % |
| 2004–2005 | 1,384, 1,431 | 1,342, 1,393 | 27–29 % / 75–79 % |
| 2002–2003 | 1,370, 1,389 | 584, 1,132 | 63–67 % / 66–74 % |
| 1997–2001 | 792–1,360 a season | none | box scores only |

Regular-season games per team after the repairs: 82 everywhere except the shortened
seasons (1999: 50, 2012: 66, 2020: 64–75, 2021: 72), 2013 (BOS and IND 81: the
cancelled Boston game) and 2000 (80–82: ESPN has only empty 0-0 placeholders for 23
Chicago games, so those games are missing). Each Cup final (seasons 2024–2026) is one
`cup` game outside the standings.

Raw NBA play-by-play from 2003 carries shot coordinates, but ESPN's
`pointsAttempted` is 0 on every shot in the 2003 sample and present from the 2016
sample on; `pbp.py` then takes the value from the text ("three point").

**Store repairs on 1 October 2026** (after the backfill; scratch scripts, not in the
repository):

- The Cup finals were re-fetched (8 summaries) and relabelled `cup`: NBA 2024
  (401607495), 2025 (401734908), 2026 (401809839); WNBA 2021 (401353913), 2022
  (401430112), 2023 (401507376), 2024 (401677672), 2025 (401736430). Two finals' notes
  were not recognised by `canon.stype` and now are: "NBA In-Season Tournament
  Championship" (2023) and the bare "WNBA Commissioner's Cup" (2021).
- NBA 2000's calendar from ESPN also covered the 1999 season: its 500 games from that
  season (all present in the 1999 store) were removed from the 2000 store.
- 0-0 "final" placeholders (ids 4002xxxxx, Chicago games, empty boxes) were removed:
  50 in 1999, 82 in 2000, 1 in 2002. 59 of the 2000 ones and all of 1999's duplicate a
  real game; 23 in 2000 have no real record at ESPN.
- All-Star and exhibition games stored as `reg` were removed: NBA 1998 (DEF v DEN),
  2002 and 2003 (East v West); WNBA 2002 (East v West), 2004 (WNBA stars v USA), 2023
  (Team Wilson v Team Stewart).
- Two duplicate ids of one game were removed: NBA 2003 400222658 (of 230104006), WNBA
  2011 400182104 (of 310604005).

`bb_fetch._keep_event` now keeps both kinds of stray event out: a scoreboard event
dated outside `canon.season_window` or a final at 0-0 is not stored.

**WNBA** (backfill finished at 02:27 UTC):

| Seasons | Store | Play-by-play | Derived |
|---|---|---|---|
| 1997 | 112 games, all status `pre`, no scores, no box | none | nothing |
| 1998–2001 | games carry scores and box scores, but ESPN's summaries give most of them status `in` (2001: 232 of 307), so only 4–19 a season are final | none | nothing |
| 2002–2008 | final, with box | 95–100 % of games | stints written, but **no game passes the 60 s minutes check** (median largest error 284–404 s), possession counts within 2 in 35–42 % of games, points exact in 68–97 % |
| 2009–2019 | final, with box | 98–100 % | stints: 69–96 % of games within 60 s; points exact mostly 96–99 % (2013: 77 %); **no shot rows** |
| 2020–2026 | final, with box | 100 % | shots and stints: 94–100 % within 60 s, points exact 99.6–100 %, three-point agreement 99.7–99.8 % |

The WNBA "shot coordinates from 2020" boundary comes from the parser, not from ESPN:
the raw files before 2020 do carry coordinates, but their shot plays use a different
family of type ids (for example 20092, 30092, 20558 rather than 92, 95) and
`pointsAttempted` 0, so `pbp._classify` does not recognise them as shots. They fall
through to "other", which is also why possession counts and lineups reconcile poorly
in those seasons. See HANDOFF Task 21.

Because 1997–2001 WNBA games are not final, the models never see them
(`_games.game_row` requires status `post`): WNBA ratings, Elo, catalogues and the
history page effectively start in 2002. WNBA regular-season games per team: the
season's format everywhere from 2002, except 2003 (four teams 33 of 34) and 2004 (six
teams 33 of 34), whose missing games ESPN does not have, and 2018 (LV and WSH 33: the
forfeited game).

**Other era gaps** (`sources/espn.py`, `pbp.py`):

- plus-minus is null before about 2007; points in the paint null where ESPN writes −1;
- in 2017-18 ESPN's team lines are shifted by a column (counting stats are therefore
  summed from the players), and scoring plays can carry `scoreValue` 0 and running
  scores that lag or lead (the parser rebuilds both);
- the DraftKings line is in ESPN's finished-game summaries for NBA 2017–2023 and
  2026 (none for 2024–2025) and WNBA 2026; ESPN's matchup predictor is in no finished
  game's summary, so it is kept only when a pregame fetch caught it (`merge_game`
  never overwrites it with null); on 1 October 2026 no stored game has one.

---

## 4. The scripts

### 4.1 `scripts/bb_fetch.py`: ESPN into the stores

```
python scripts/bb_fetch.py --league nba --from 1997 --to 2027 --budget 60000
python scripts/bb_fetch.py --league wnba --from 2026 --to 2026 --budget 400
python scripts/bb_fetch.py --league nba --refresh-current --budget 300
python scripts/bb_fetch.py --league wnba --rosters
```

Flags: `--league` (required), `--from`, `--to` (default: the current season),
`--phases` (default `schedule,games`), `--budget` (2,000), `--interval` (0.5),
`--refresh-current`, `--rosters`. Seasons run newest first so the current season is
usable first.

**schedule** (per season):

1. If the store has no calendar, or the season is current: one scoreboard on a
   probe day (`_probe_day`: 15 January for the NBA, 15 July for the WNBA) reads the
   season's calendar of game days. If ESPN gives no calendar, the fallback window
   `canon.season_window` is scanned day by day (NBA 25 September of the previous
   year to 31 July, with special windows for 1999, 2012, 2020 and 2021; WNBA 1 April
   to 1 November).
2. One scoreboard per game day not yet scanned (`meta.days`), newest first. For the
   current season in refresh mode (or until `complete_through` is set) the days from
   two days ago to a week ahead are re-scanned. NBA about 230 days a season, WNBA
   about 140.
3. Each event becomes a GAME skeleton (`espn.compact_event`) merged into the store;
   All-Star events (`stype == "allstar"`) are dropped, and so are events dated
   outside `canon.season_window` and finals at 0-0 (`_keep_event`, section 3).
4. A standings call fills conferences and divisions when no team has one, and again
   on Mondays in refresh mode.

**games** (per season), one summary per game that is:

- final and not yet fetched as final with a box score;
- final within the last 48 hours, in refresh mode for the current season, when its
  last fetch is more than 6 hours old (late stat corrections);
- in progress (status `in`) with a tip-off in the past;
- in refresh mode, starting within the next 36 hours (lines, the predictor and
  injuries).

Postponed and canceled games are skipped. Each summary becomes a GAME
(`espn.compact_game`) merged into the store; the team and player records are
updated from it; when it has play-by-play, the compact play-by-play is written to
`data/basketball/pbp/<league>/<season>/<id>.json.gz`. A final game is stamped in
`meta.fetched`. The store is saved every 25 games, with a progress line.
`complete_through` is the last date through which every game is final and fetched.

**rosters** (current season only; implied by `--refresh-current`, forced by
`--rosters`): one roster call per team that has a conference and is not "TBD", at
most every `ROSTER_EVERY_H = 20` hours (`meta.rosters_at`). It fills each player's
date of birth, position, jersey and team list, and records today's roster per team in
`meta.rosters` ({team id: [player ids]}; the preseason prior's roster impact reads it,
[MODELS.md](MODELS.md) section 2.2). ESPN's roster endpoint is today's roster, so this
cannot fill past seasons. Box-score player records carry no date of birth. Run on 1
October 2026: NBA 2027 605 players from 30 teams, WNBA 2026 221 from 15, every one
with a date of birth.

**Cost**: about 1,620 ESPN calls per NBA season (about 230 scoreboards and 1,400
summaries) at 0.6 s; the backfill measured about 0.69 s a game including ESPN's
response time. A WNBA season is about 280–380 calls; the whole WNBA history took
9,697 calls in 5,892 s (0.61 s a call, no failures).

### 4.2 `scripts/bb_derive.py`: raw play-by-play into the model inputs

```
python scripts/bb_derive.py --league wnba --from 2026 --to 2026
python scripts/bb_derive.py --league nba --from 2017 --to 2027 --force
```

For each final game with play-by-play it runs `pbp.derive` (section 6) and writes, per
season, `shots.json` and `stints.json` (plain and gzipped beside each other) and
`recon.json`. `VERSION = 1`.

- A game is re-parsed only when its fetch stamp (`meta.fetched[gid]`, stored as
  `sig` in `recon.json`) or the derivation version changed, or with `--force`.
- A game whose raw file is not on this machine keeps the rows and reconciliation an
  earlier machine derived. So CI, which holds only the current season's raw files,
  never drops history.
- One bad game is logged and recorded as `{"sig", "error"}`; the season goes on.
- A season whose inputs are unchanged is not rewritten.

The season summary in `recon.json` (`_summary`): `games_final`, `games_pbp`,
`derived`, `errors`, `raw_missing`, `share_all_within_60s`, `share_points_exact`,
`share_poss_within_2`, `median_max_err_s`, `p95_max_err_s`, `three_agree_mean`,
`lineup_fixes_mean`.

### 4.3 `scripts/bb_pack.py`: gzip completed seasons for committing

```
python scripts/bb_pack.py                                   # every completed season of both leagues
python scripts/bb_pack.py --league nba --from 2017 --to 2026
python scripts/bb_pack.py --league wnba --seasons 2025 --remove-plain
```

Writes `shots.json.gz` and `stints.json.gz` from the plain tables, verifies each
round-trips before anything is removed, and skips the current season of each league
(`canon.current_season`) unless `--include-current`. A `.gz` already newer than its
plain file is left alone unless `--force`. `bb_derive.py` already writes the `.gz`
files, so this is mainly a check and a way to remove the plain files.

### 4.4 `scripts/bb_hydrate.py`: the current season from the live site (CI)

```
python scripts/bb_hydrate.py                       # both leagues, their current seasons
python scripts/bb_hydrate.py --leagues wnba --base https://example.org/data
```

For each league's current season it fetches
`https://pchattani.github.io/the-quant-hardwood/data/<L>/<S>/store.json` and keeps
it only when its `updated_at` is newer than the checkout's copy; then it fetches
`recon.json`, `shots.json.gz` and `stints.json.gz` (each checked to decompress) and
deletes the plain `shots.json` / `stints.json` so the hydrated `.gz` is read. A 404
(a first deploy, or a league with no season yet) is not an error. It is also the
quickest way to get the current season onto a new machine without calling ESPN.

---

## 5. Formats

### 5.1 Season store: `docs/hardwood/data/<league>/<season>/store.json`

```
{"league", "season", "updated_at",
 "teams":   {team_id: {"name","abbr","location","colour":"#rrggbb","alt_colour","conference","division"}},
 "players": {player_id: {"name","short","pos","pool":"G|F|C","jersey","dob"|null,"teams":[team_id...]}},
 "games":   {game_id: GAME},
 "meta":    {"fetched": {game_id: iso}, "complete_through": "YYYY-MM-DD", "calendar": [YYYYMMDD],
             "days": {YYYYMMDD: iso}, "rosters_at": iso}}
```

`store.save` sorts games by date (stable diffs) and stamps `updated_at`, which is
what `bb_hydrate.py` compares. Paths can be redirected with `HARDWOOD_DATA` (stores
and payloads) and `HARDWOOD_PBP` (raw play-by-play).

**GAME** (`espn.compact_game`; contract in `CONTRACT.md` section 1):

```
{"id", "date": iso (UTC tip-off), "status": "pre|in|post|postponed|canceled",
 "stype": "pre|reg|playin|post|cup", "neutral": bool, "home", "away", "hs", "as", "periods",
 "line": {"home": [pts per period], "away": [...]},
 "box": {team_id: {"players": [[BOX_COLS...]], "dnp": [[player_id, reason]], "team": {TEAM_BOX_KEYS...}}},
 "odds": {"provider","spread_home","total","ml_home","ml_away"} | null,
 "predictor": {"home": P(home wins)} | null,
 "injuries": {team_id: [[player_id, status, detail]]},
 "venue": {"id","name","city","state"} | null, "attendance",
 "series": {"round","game","summary"} | null, "has_pbp": bool}
```

- `BOX_COLS` (`store.py`): `player_id, starter, sec, pts, fgm, fga, tpm, tpa, ftm, fta,
  oreb, dreb, ast, stl, blk, tov, pf, pm`. `sec` is whole box minutes × 60; `pm` is
  null where ESPN has none.
- `TEAM_BOX_KEYS`: the counting stats are the players' sums; `tov` is all turnovers
  including team turnovers, `team_tov = tov − Σ player tov`; `pts_paint`,
  `pts_fastbreak`, `pts_off_tov`, `largest_lead`, `lead_changes` are ESPN's own.
- `odds` is DraftKings from `pickcenter` when listed, else the first provider; the
  home spread is made negative when the home side is the favourite.
- `predictor` is ESPN's `predictor.homeTeam.gameProjection` / 100.
- `injuries` are filled only for games not yet final (the summary lists today's).
- `series` only for playoff games.
- `stype` comes from `canon.stype(season_type, headline)`: ESPN's types 1, 2, 3, 5
  map to `pre`, `reg`, `post`, `playin`; a headline containing "all-star", "rising
  stars" or "celebrity" gives `allstar` (never stored); one containing "cup" and
  "championship" or " final" (not "semifinal") gives `cup`, as do "in-season
  tournament" with "championship" (the 2023 NBA final) and the bare "WNBA
  Commissioner's Cup" (the 2021 final). A summary carries its label in
  `header.gameNote` rather than in competition notes, so `compact_game` reads that
  too (the "gameNote fix"). The backfill ran before that fix; the past Cup finals were
  relabelled afterwards (section 3).

**`store.merge_game`** never lets a poorer record wipe a richer one: an empty `box`,
`injuries` or `line` keeps the old one; a null `odds`, `venue`, `series`,
`attendance` or `predictor` keeps the old one; `has_pbp` never goes from true to
false; and a rescan labelled `reg` does not overwrite `cup`, `playin` or `post`.
Because `cup` does overwrite `reg`, re-fetching a game's summary is enough to
relabel a Cup final.

### 5.2 Raw play-by-play: `data/basketball/pbp/<league>/<season>/<game_id>.json.gz`

```
{"id", "periods",
 "plays": [[seq, period, clock_s, type_id, team_id|null, [participant ids], x|null, y|null,
            score_value, shooting(0/1), scoring(0/1), home_score, away_score, text, points_attempted]],
 "types": {type_id: ESPN type text},
 "wp": {seq: home win probability}}
```

`x`, `y` are kept only on shooting plays with a real location. Participants:
substitutions [entering, leaving]; assisted makes [shooter, assister]; blocked misses
[shooter, blocker]; steals [player who lost the ball, stealer]. `wp` is ESPN's
per-play home win probability, keyed by sequence number. About 441 MB for both
leagues on 1 October 2026 (NBA 2003–2026, WNBA 2002–2026).

### 5.3 Derived tables: `docs/hardwood/data/<league>/<season>/`

| File | Content |
|---|---|
| `shots.json` (+ `.gz`) | `{"cols": SHOT_COLS, "rows": [...]}`, one row per field-goal attempt: `game_id, t, period, team, shooter, x_ft, y_ft, dist_ft, angle_deg, zone, shot_type, value, made, assisted, assister, blocked, putback, transition, margin_before, clutch` |
| `stints.json` (+ `.gz`) | `{"cols": STINT_COLS, "rows": [...]}`: `game_id, t0, t1, h1..h5, a1..a5, poss_h, poss_a, pts_h, pts_a`; stints without five a side are left out |
| `recon.json` | `{"version","league","season","updated_at","summary": {...}, "games": {gid: {"max_err_s","ok","bad_lineup_s","n_err_60","points_ok","pts","poss","three_agree","fixes","stints","sig"}}}` |

Every loader (`store.load_table`, `models/_io.resolve`) reads `<name>.gz` when it
exists and is not older than the plain file, so a checkout with only the `.gz` works.
The plain and gzipped files hold byte-identical JSON, so input signatures computed
on either agree.

---

## 6. Play-by-play reconstruction: `oddsmarkets/basketball/pbp.py`

ESPN's play-by-play has no on-floor lineups, no possession markers and no shot
distance or zone. `pbp.py` rebuilds all three and checks each game against the box
score. `derive(pbp, game, league, season)` does it all for one game.

### 6.1 Events (`parse`, `_classify`)

Each play becomes one of: `sub`, `ft`, `shot`, `reb`, `tov`, `timeout`, `jump`,
`period_start`, `period_end`, `foul`, `other`. Type id first, text second:

| Kind | Rule |
|---|---|
| sub | type 584, or "enters the game for" |
| ft | "free throw" in the text or type text; "n of m"; technical, flagrant, clear-path flags |
| shot | a type id in `SHOT_TYPE_IDS`, or a shooting play with `points_attempted` 2 or 3 |
| reb | types 155 (defensive) / 156 (offensive), or "rebound" |
| tov | "turnover", "traveling", or type 61–91; a steal when the text says so |
| timeout | types 16–20, or "timeout" |
| jump | types 11, 615, or "gains possession" |
| period end / start | types 412, 402 / 411, or "end of" / "start of" |
| foul | "foul" (technical, flagrant, offensive or charge, shooting flags) |

A shot's value is `points_attempted`; when that is missing, 3 if the text says
"three point", else 2. A made shot whose `score_value` is 0 (2017-18 rows) gets its
value. The running score is rebuilt from the events, not taken from the rows. The
league is inferred from the period-1 clock (above 650 s means NBA) when not given.

### 6.2 Lineups (`_lineups`, `_period_five`, `_absentee`)

- Period 1 starts with the box-score starters.
- Each later period's opener is: players whose first appearance is being subbed out;
  then players who act (shot, rebound, turnover, jump, non-technical free throw or
  foul) before any substitution of theirs; topped up from the previous period's
  closing five (leaving out anyone subbed in during the period); then, rarely, the
  team's highest-minute players not known to have come in. If more than five
  qualify, the subbed-out come first and the rest are ranked by how often they act.
- Substitutions are applied in order; changes at a period break are logged at the
  new period's opening clock.
- Repairs ("fixes"): an incoming player already on the floor removes the outgoing
  one; an outgoing player not on the floor removes the most plausible absentee; a
  player who acts while off the floor is put on in place of the most plausible
  absentee. Actions at the same clock as the player's own substitution are ignored.
- The most plausible absentee is the first on-floor player whose next appearance is
  being subbed in; else one who never acts again; else the one who goes longest
  without acting.

### 6.3 Possessions (`_possessions`)

A possession ends `made`, `dreb`, `tov`, `ft` (made last free throw), `period` or
`other` (a held ball won by the defence, or a data glitch). Offensive rebounds
continue it. Each possession records its start kind: `tr` (after a defensive rebound
by a player or a steal), `made`, `dead` or `period`, its times, points and both
fives. Special cases: a made shot followed by a non-technical free throw by the same
team within 0.05 s on the clock is an and-one; technical free throws never change
possession; flagrant, clear-path and lone (1 of 1, not and-one) free throws keep the
ball; a "defensive" rebound by the team already on offence is a dead-ball team
rebound and does not end the possession; a turnover logged after a held ball has
already moved the ball is booked on the possession the held ball ended.

### 6.4 Stints, shots and checks

- **Stints** (`stints`): a stretch of one period with the same ten players. Events go
  to the stint holding them; a possession counts in the stint holding its last event;
  time runs from the stint's first event to the next change (the first stint of a
  period from the period's start, the last to its end).
- **Shots** (`shots`, `shot_geometry`, `zone`, `shot_type`): ESPN coordinates are
  whole feet on a half court, `x` 0..50 with the rim at `RIM_X = 25`, `y` along the
  floor with the rim centre at `RIM_Y = 0.75` (fitted on the "N-foot" distances in the
  text, mean absolute error 0.4 ft). `x_ft = x − 25`, `y_ft = y − 0.75`,
  `dist_ft = hypot`, `angle_deg = atan2(x_ft, y_ft)`. Zones: `heave` (a three from
  over `HEAVE_FT = 40` ft), `corner3` (a three with `y_ft ≤ CORNER_Y_FT = 8.75` and
  `|x_ft| ≥ 20`), `ab3`, `rim` (a two under 4 ft), `paint` (`|x_ft| ≤ 8`,
  `y_ft ≤ 13.75`), `mid`. A shot without coordinates takes its distance from the
  text. Putback: ESPN types 94, 125, 138, 150, or within `PUTBACK_S = 3` s of the same
  team's offensive rebound in the same possession. Transition: the possession started
  `tr` and the shot is within `TRANSITION_S = 6` s. Clutch: the 4th period or later,
  ≤ `CLUTCH_S = 300` s on the clock, margin within `CLUTCH_MARGIN = 5`.
- **Checks** (`reconcile`, `points_check`, `shot_quality`): stint seconds against box
  seconds per player, a game passing when nobody is off by more than
  `RECON_TOL_S = 60` s (box minutes are whole minutes, so 30 s of any error is
  rounding); points from events against the final score, exactly; the share of
  shots whose coordinates fall on the same side of the three-point line as ESPN's
  value (tolerance 0.5 ft).

---

## 7. Identity and seasons: `oddsmarkets/basketball/canon.py`

- `LEAGUES = ("nba", "wnba")`. Seasons are ESPN's `season.year`.
- `current_season(league, today)`: WNBA = this year from April, else last year; NBA =
  next year from September, else this year. (`sources/markets.season_for` turns the
  NBA over in August instead; it matters only for a market fetch in August.)
- The clock: `period_len` 720 s NBA, 600 s WNBA from 2006, 1,200 s WNBA halves
  before 2006, 300 s overtime; `game_t = period_start + period_len − clock_s`.
- Three-point line: NBA 23.75 ft arc, 22 ft corners; WNBA 22.15 / 22 ft from 2013,
  20.5 ft before.
- Position pools (`POOL`, `pool`): G (G, PG, SG), F (F, SF, PF, G-F, F-G, F-C and
  variants), C (C, C-F); wings and stretch bigs are F.
- `FRANCHISE_MOVES` and `team_label`: one ESPN id per franchise through moves; the
  store's own era name wins, the table is the fallback. WNBA expansion: Golden State
  Valkyries (2025), Toronto Tempo and Portland Fire (2026).
- `season_window`: generous fallback windows (above). The workflow also uses it to
  decide whether a league is "in season" (window − 14 days to + 7 days).

---

## 8. What is committed, what travels with the site, and the model caches

`.gitignore` (the basketball block):

```
!docs/hardwood/data/
docs/hardwood/data/**
!docs/hardwood/data/*/
!docs/hardwood/data/*/*/
!docs/hardwood/data/*/*/store.json
!docs/hardwood/data/*/*/recon.json
!docs/hardwood/data/*/*/shots.json.gz
!docs/hardwood/data/*/*/stints.json.gz
!docs/hardwood/data/*/calibration.json
!docs/hardwood/data/*/bio.json
!docs/hardwood/data/*/fantasy_backtest.json
```

The storage rule:

| What | Where it lives |
|---|---|
| Completed seasons' `store.json`, `recon.json`, `shots.json.gz`, `stints.json.gz` | committed to git **by hand**, once, after the season ends |
| The current season's inputs | **never committed**; deployed with the site, hydrated back by CI (`bb_hydrate.py`) |
| `<league>/calibration.json` | committed (the backtest is run locally; CI keeps the committed copy) |
| Plain `shots.json`, `stints.json` | never committed, never deployed |
| Payloads (`index.json`, `season.json`, `games/`, `players/`, ...), `manifest.json`, `pbp_summary.json.gz` | build output; deployed; restored from the previous deploy at the start of each CI run |
| Raw play-by-play | `data/basketball/pbp/` (ignored); the Actions cache in CI |
| Model caches | `data/basketball/cache/` (ignored); the Actions cache in CI |

On 1 October 2026 the completed seasons (NBA 1997–2026, WNBA 1997–2025) were
committed after the backfill and the repairs, with both `calibration.json` files; NBA
2027 and WNBA 2026 (still in its Finals) were not. The first deploy was 408 MB.

Model caches under `data/basketball/cache/` (`HARDWOOD_CACHE`), each a JSON file
`{"key", "result"}` (`_io.cached`) unless noted:

| Path | Written by | Keyed on |
|---|---|---|
| `ratings/<L>_<S>_<through>.json`, `ratings/carryover_<L>.json` | `ratings.for_season`, `fit_carryover` | `VERSION = 2` and the size and mtime of the stores used |
| `game/params_<L>.json` | `game.fit_params` | `VERSION = 3` and every store's size and mtime |
| `elo/<L>.json` | `elo.history` | `VERSION = 1` and every store's size and mtime |
| `shots/<L>_<S>.json` | `shots.for_season` | `xpts-1` and `shots.json` (and the store when `through` is set) |
| `rapm/<L>_<S>.json`, `impact/box_model_<L>.json`, `impact/<L>_<S>_<through>.json` | `impact` | `impact-1` and every season's store, stints and shots |
| `winprob/model_<L>_<S>.json`, `winprob/<L>_<S>_<through>.json` | `winprob.model_for`, `for_season` | `wp-2`, the training seasons and their raw-file counts |
| `awards/<L>_<S>_<through>.json` | `awards.for_season` | `awards-1`, team wins, every store |
| `analytics/<L>_<S>_pbp.json` | `analytics/pbpx` | per-game fetch stamps and the WP model |
| `backtest_<L>.json` | `backtest.backtest()` | not keyed: written when the backtest is run |

Signatures that include file modification times change when a file is copied, so a
fresh checkout or a hydrated file recomputes the caches that read it.

---

## 9. Scheduling: `.github/workflows/update_hardwood.yml` ("Hardwood Hourly Update")

| Setting | Value |
|---|---|
| Triggers | `cron: '47 * * * *'` and `workflow_dispatch` |
| Runner | `ubuntu-latest`, Python 3.11, `pip install uv`, `uv sync` |
| Job timeout | 55 minutes |
| Concurrency | group `hardwood-build`, `cancel-in-progress: false` |
| Permissions | `contents: read` (the job commits nothing to this repository) |

Steps in order:

1. **Restore raw play-by-play**: `actions/cache@v4` on `data/basketball/pbp`, key
   `hardwood-pbp-${{ github.run_id }}`, restore key `hardwood-pbp-`.
2. **Restore model caches**: the same on `data/basketball/cache`, prefix
   `hardwood-cache-`.
3. **Restore the previous deploy's payloads** (`continue-on-error`, 10 minutes):
   clones the public repo with the deploy key and
   `rsync -a --ignore-existing /tmp/prev/data/ docs/hardwood/data/`. Files in the
   checkout win; everything else comes back: payloads, manifests, game pages, and
   every season's stores and `.gz` inputs (the deploy publishes them). Without the
   variable or the secret it logs "cold build".
4. **Hydrate the current season** (`bb_hydrate.py`, `continue-on-error`, 5 minutes).
5. **Leagues in season**: a league is fetched when today is within its
   `season_window` widened by 14 days before and 7 after. The NBA window (25
   September to 31 July) covers almost the whole year; the WNBA's (1 April to 1
   November) about seven months.
6. **Fetch NBA** and **Fetch WNBA**: `bb_fetch.py --league <L> --refresh-current
   --budget 600` (NBA) / `400` (WNBA) `--interval 0.5`, each `continue-on-error` with
   a 15-minute timeout.
7. **Derive** (`continue-on-error`, 10 minutes): `bb_derive.py --league <L>` for each
   league in season (its current season by default).
8. **Build**: `build_hardwood.py --game-page-seasons 3` (30 minutes): each league's
   current season in full with 20,000 simulations and the markets, every other
   season light (skipped when its manifest matches), game pages only for each
   league's three most recent seasons on disk.
9. **Prune old game pages**: deletes `docs/hardwood/data/<L>/<S>/games/` for every
   season `≤ current − 3`.
10. **Deploy**: clones the public repo,
    `rsync -a --delete --exclude='.git' --exclude='shots.json' --exclude='stints.json' docs/hardwood/ /tmp/site/`,
    commits "Site update <timestamp>" when anything changed and pushes. Without
    `HARDWOOD_REPO` and `HARDWOOD_DEPLOY_KEY`: "build only, no deploy".

Data changes after games: a finished game is fetched at the first hourly run after
ESPN marks it final (and refetched for 48 hours for corrections); in-progress games
are refetched every run, so the live cards move hourly, not in real time.

---

## 10. The backfill

Started detached on the owner's machine at about 00:49 UTC on 1 October 2026, both
leagues, newest season first:

| League | Command (as the running process showed it) | Log | Outcome |
|---|---|---|---|
| NBA | `.venv\Scripts\python.exe scripts\bb_fetch.py --league nba --from 1997 --to 2027 --budget 60000 --interval 0.6` | `logs/bb_backfill_nba.log` | finished on 1 October 2026, then `bb_derive.py` for every season (the log ends "done in 257.8 s") |
| WNBA | the same shape for 1997–2026 (its exact flags are not in the log) | `logs/bb_backfill_wnba.log` | finished 02:27 UTC: 9,697 calls in 5,892 s, then `bb_derive.py` for every season |

The logs are PowerShell redirections, written in UTF-16 with PowerShell's
`NativeCommandError` wrapper lines; read them with
`Get-Content logs\bb_backfill_nba.log -Tail 10`, not with `tail` or an editor that
expects UTF-8. The NBA process shows twice in the process list (the venv's
`python.exe` launcher and the interpreter it starts); that is one backfill, not two.

The script resumes where it stopped: kill and restart it freely. The follow-up (repair
the Cup-final labels and stray games, derive, pack, commit the completed seasons, refit
and rebuild) was done on 1 October 2026 (section 3, HANDOFF Task 15).

---

## 11. Failure modes

| What fails | Effect | Recovery |
|---|---|---|
| ESPN 429 or 5xx | the client sleeps `Retry-After` or 10 s × attempt and retries (4 attempts) | none needed |
| ESPN answers non-JSON or 4xx for one game | logged, `None`, counted as a failure; the game stays unfetched and is retried next run | none needed |
| A summary without a header | logged as "has no header", skipped | retried next run |
| Budget exhausted | `BudgetExhausted` ends the run after saving the store | run again |
| ESPN slow in CI | the fetch step stops at 15 minutes; `continue-on-error` lets derive, build and deploy run | the next hour continues |
| One game fails to parse in `bb_derive.py` | recorded as `{"sig","error"}` in `recon.json`; its rows dropped | fix the parser, `--force` the season |
| The live site unreachable in CI | hydrate logs a warning; the run builds from the restored deploy (the same files, from git) | none needed |
| The public repo cannot be cloned | "cold build": every payload is rebuilt (slow; may hit the 30-minute build limit) | check the deploy key |
| A build step raises | logged with its traceback; the payload becomes `{"ok": false, "reason"}` | read the build log |

---

## 12. Known gaps and sharp edges

- **NBA 2000 lacks 23 Chicago games** (ESPN has only 0-0 placeholders for them).
- **WNBA 1997–2001 are not usable** (status `pre` or `in`, section 3).
- **WNBA play-by-play before 2020 yields no shots** and unreliable possessions and
  lineups (different type ids, no `pointsAttempted`); WNBA 2002–2008 stints fail the
  minutes check outright. Those stints still enter RAPM and the pooled box-impact
  fit (HANDOFF Task 21).
- **`canon.PBP_FROM` (2017) and the `espn.py` docstring are out of date** with what
  ESPN serves.
- **Player ages** exist only for players on a current roster (the rosters phase reads
  today's rosters); retired players' ages stay null.
- **CI has only the current season's raw play-by-play.** The win-probability model
  for the current season is meant to be fitted on the three previous seasons' raw
  files; in CI those are absent, so `winprob.model_for` falls back to the current
  season itself (in-sample), and `calibration.json`'s `winprob` block is recomputed
  from it ([MODELS.md](MODELS.md) sections 8.1 and 12, HANDOFF Task 21). This is read from
  the code, not observed in a CI log.
- **The DraftKings line exists only where ESPN's finished-game summary keeps it**: NBA
  2017–2023 and 2026, WNBA 2026, so the backtest's market comparison covers those.
- **Injuries are today's**, so only games not yet final keep them.

---

## 13. Operator quick reference

```
# Current season, as CI does it
python scripts/bb_fetch.py --league nba --refresh-current --budget 600 --interval 0.5
python scripts/bb_fetch.py --league wnba --refresh-current --budget 400 --interval 0.5
python scripts/bb_derive.py --league nba
python scripts/bb_derive.py --league wnba

# The current season from the live site instead of ESPN
python scripts/bb_hydrate.py

# Rosters (dates of birth) for the current season
python scripts/bb_fetch.py --league nba --rosters --phases none --budget 100     # "none" = no schedule or games phase

# One past season's games again (only unfetched games are fetched)
python scripts/bb_fetch.py --league wnba --from 2025 --to 2025 --phases games --budget 500

# Derive every season again
python scripts/bb_derive.py --league wnba --from 2002 --to 2026 --force

# Gzip completed seasons for committing
python scripts/bb_pack.py

# Backfill progress (PowerShell; the logs are UTF-16)
Get-Content logs\bb_backfill_nba.log -Tail 10
```
