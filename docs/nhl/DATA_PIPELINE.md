# Data pipeline: extraction and storage (NHL)

How The Quant Rink gets its data: the NHL's api-web and stats REST APIs, NHL EDGE, ESPN for
lines by book, the MoneyPuck benchmark files and the prediction markets, and why nothing
else; how play-by-play and shift charts become events and stints; what each season holds;
identity; the scripts; the store format and the merge rules; what is committed and what
travels with the site; the scheduled job and the backfill. Models are in
[MODELS.md](MODELS.md); the payloads built from the stores are in
[DASHBOARD.md](DASHBOARD.md).

Contents

1. Overview and data flow
2. Sources
3. Coverage by season
4. Identity: `canon.py`
5. The scripts
6. Formats
7. Merge rules: `store.py`
8. What is committed, what travels with the site, and the caches
9. Scheduling: `.github/workflows/update_rink.yml`
10. The backfill
11. Failure modes
12. Known gaps and sharp edges
13. Operator quick reference

---

## 1. Overview and data flow

```
 api-web.nhle.com/v1                    api.nhle.com/stats/rest/en          site.api.espn.com / sports.core.api.espn.com
 schedule, play-by-play, boxscore,      shiftcharts, skater / goalie /       scoreboard, summary (pickcenter), core odds
 standings, roster, edge/*,             team reports, season                 │
 partner-game/US/now                    │   (www.nhl.com HTML TOI reports    │          peter-tanner.com/moneypuck
        │                               │    when a shift chart is empty)    │          shots_<YYYY>.zip
 sources/nhl.py, sources/edge.py        sources/stats.py                     sources/espn.py    sources/moneypuck.py
        │                               │                                    │                  │
        ▼                               ▼                                    ▼                  ▼
 data/nhl/{pbp,box,edge}/<S>/...        data/nhl/{shifts,stats}/<S>/...      data/nhl/cache/... data/nhl/moneypuck/shots_<S>.parquet
        │       scripts/nhl_fetch.py (per season, newest first; phases schedule → pbp → shifts → box → derive → edge → espn → moneypuck)
        ├──► schedule weeks → nhl.compact_game ──► store.merge_game ◄── ESPN lines, attendance, espn_id; boxscore goalies
        │                                  │
        │                                  ▼
        │                docs/rink/data/<season>/store.json   (store.save_owned: lock + per-phase fields)
        ▼
 derive.build_season: play-by-play + shift charts ──► data/nhl/derived/<S>/{events.parquet, stints.parquet, onice_check.json}
        │
        ▼
 models (xG, shooting, goalies, on-ice, RAPM, value, lines, team strength, game, simulations) ──► scripts/build_rink.py ──► docs/rink/data/** payloads
                                                            ▲
                                                            └── Kalshi, Polymarket (sources/markets.py, at build time)
```

Raw downloads live under `data/nhl/` (git-ignored; env `RINK_RAW`): `pbp/`, `shifts/`,
`box/`, `edge/`, `stats/`, `moneypuck/`, `derived/` and `cache/` (env `RINK_CACHE`). The
data root is `docs/rink/data` unless `RINK_DATA` points elsewhere (`store.py`,
`models/_io.py`, `models/_cdata.py` and `analytics/__init__.py` all read the same three
variables).

---

## 2. Sources

### 2.1 The client: `sources/_client.py`

Every source goes through one `Client`: requests spaced per host (`interval`, or `intervals`
keyed by host suffix) and, when `min_gap` is set, across all hosts (one process never exceeds
1 / `min_gap` requests a second); up to 4 attempts; a 120 s timeout; a call `budget` per run.
After a network error it sleeps 5 s × the attempt; after HTTP 429 or a 5xx it honours
`Retry-After`, else 10 s × the attempt, at most 120 s. **A 404 is an answer, not a failure**
(EDGE has no page for a player without tracked games; ESPN has no odds for some events): it
returns `None` and counts in `missing`. Any other status, or a non-JSON answer to `get`, is
logged, counted in `failures` and returned as `None`: **the client never raises on a bad
answer**. Running out of budget raises `BudgetExhausted`, which `nhl_fetch` catches to stop
cleanly; the next run resumes. `head` returns the final headers after redirects (the NHL's
"now" and "current" URLs answer 307 to a dated form; only dated forms are called, except
`partner-game/US/now`, which has none), and `download` streams to a `.part` file checked
against Content-Length. The user agent is `The Quant Rink (pchattani.github.io/the-quant-rink;
NHL analytics, non-commercial)`. `report()` gives calls and seconds per host, failures, not
found and megabytes, and `nhl_fetch` logs it at the end of every run.

`nhl_fetch` makes one client with `--budget` (default 5,000), `--interval` (default 0.25 s,
`nhl.INTERVAL`) per NHL host, `--min-gap` (default 0.25 s: four requests a second in total),
`--espn-interval` (default 1.0 s, `espn.INTERVAL`) for `espn.com` and 2.0 s for
`peter-tanner.com`.

### 2.2 NHL api-web: `sources/nhl.py`

`https://api-web.nhle.com/v1`, no key, no CORS (fetched in CI or locally only); "3–5
requests a second are tolerated" (the module's docstring; endpoints verified 1 October 2026):

| Endpoint | Used for |
|---|---|
| `/schedule/{YYYY-MM-DD}` | a game week (7 days from the date): id, type, UTC start, venue, neutral site, state, schedule state, teams, scores, last period type |
| `/gamecenter/{id}/play-by-play` | every event (eventId, sortOrder, period, time in period, `situationCode`, `homeTeamDefendingSide` (absent before about 2019–20), `typeDescKey`, details with coordinates, zone, shot type, player ids, `eventOwnerTeamId`) and `rosterSpots` |
| `/gamecenter/{id}/boxscore` | goalies (starter flag, TOI, decision) |
| `/standings/{YYYY-MM-DD}` | one row per club: conference / division / wild-card sequences, GP, W, L, OTL, points, RW, ROW, GF, GA, streak, last ten, clinch code |
| `/roster/{team}/{season}` | forwards, defencemen, goalies (birth date, height, weight, shoots / catches, number, country) |
| `/player/{id}/landing` | bio and season totals |
| `/partner-game/US/now` | DraftKings moneyline (2- and 3-way), puck line and total for today's games |

Game states: FUT / PRE → `scheduled`, LIVE / CRIT → `live`, FINAL / OFF → `final`;
`gameScheduleState` PPD → `postponed`, CNCL → `cancelled`. Only regular-season and playoff
games are kept (`canon.KEEP_TYPES` = (2, 3)).

**Schedule → GAME** (`compact_game`): the local game date from `gameDate`, else the UTC
start shifted by the venue's offset; scores and period only when live or final; `ot` / `so`
from `gameOutcome.lastPeriodType`; a playoff game's `series` {round, series, game} from its
id (`...03RSG`).

**Goalies**: from the boxscore (`goalies_from_box`: the flagged starter, else the goalie
with most TOI; every goalie with TOI; the W or L decision), else from the play-by-play
(`goalies_from_pbp`: the first `goalieInNetId` seen against each side).

**Partner odds** (`partner_lines`): `MONEY_LINE_2_WAY`, `PUCK_LINE` (with the home line's
sign) and `OVER_UNDER` per side, as a lines record with `src` "NHL partner (DraftKings)".

### 2.3 NHL stats REST: `sources/stats.py`

`https://api.nhle.com/stats/rest/en`:

- `shiftcharts?cayenneExp=gameId=X`: one row per shift (typeCode 517: playerId, teamId,
  period, start and end "mm:ss" in the period, duration) plus goal markers (typeCode 505,
  dropped). From 2010–11; 2009–10 games answer `total 0`. `compact_shifts` keeps
  {pid, team_id, team, period, start, end} (a shift without an end takes start + duration).
- `skater/summary`, `skater/realtime`, `goalie/summary`, `team/summary`, `team/realtime`
  (`?limit=-1&cayenneExp=seasonId=S and gameTypeId=T`): one row per player or team per
  season; the awards' player seasons, careers back to a player's debut, the NHL's own PP% /
  PK%, the EDGE job list.
- `season`: every season's start, regular-season end and end dates, games and total
  regular-season games (cached a day in `data/nhl/cache/stats_seasons.json`).

**The HTML fallback.** Some games' shift charts answer empty (57 games of 2024–25,
2024021235 to 2024021291, empty on 1 October 2026). For a settled game with an empty
answer, `nhl_fetch.html_shifts` reads the NHL's HTML time-on-ice reports
(`https://www.nhl.com/scores/htmlreports/<S>/T{H|V}<gameId[4:]>.HTM`, home and visitors),
maps each player block ("4 BYRAM, BOWEN") to a playerId by team and sweater number through
the play-by-play roster spots, and writes a shiftcharts-shaped answer with `"source":
"html"` (`meta.shifts[gid] = {"html": true}`). All 57 games of 2024–25 were rebuilt this way
with 0 unmatched players (850–899 rows each; `logs/nhl_backfill_html_2024.log`).

### 2.4 NHL EDGE: `sources/edge.py`

`https://api-web.nhle.com/v1/edge/{skater,goalie,team}-detail/{id}/{S}/{T}` (T = 2 regular
season, 3 playoffs), from 2021–22 (2020–21 and earlier answer 404, as does a player with no
tracked games): skater top shot speed, skating speed (maximum, bursts over 20 mph),
distance, zone time (offensive / neutral / defensive, all and even strength) with the NHL's
percentiles; goalie statistics and shot-location summaries; team speed, shot speed,
distance and zone time. These are **season aggregates**, not per-play tracking: EDGE never
enters the play-level models. `summary(kind, raw)` gives the compact record the catalogues
read.

### 2.5 ESPN: `sources/espn.py`

The public JSON (no key, CORS `*`), paced at one request a second:

- `site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD`: the events
  of a US day (ESPN team ids, UTC start, status, scores, attendance).
- `…/summary?event=<id>`: the pickcenter (DraftKings moneyline, puck line and total with
  `open` and `close` blocks), plays with coordinates, gameInfo (attendance).
- `sports.core.api.espn.com/v2/sports/hockey/leagues/nhl/events/<id>/competitions/<id>/odds`:
  one item per provider. 2019–20 offshore and international books (Bet365, BetStars,
  Betradar, Caesars, ...); 2023–24 on US books with open and close blocks (Caesars, BetMGM,
  ESPN BET, DraftKings, ...). `spread` is the **home** puck line, signed (verified on
  2019-10-15 MIN@TOR, 2023-10-20 CGY@CBJ and 2026-09-30 PIT@PHI).

`compact_lines` keeps every book (`books`), drops in-play rows ("… Live Odds") and the
price-less providers (`NO_PRICE`: consensus, teamrankings, numberfire and two others), and
flags a book `suspect` when its moneyline overround is outside 1.00–1.15, its total is a
goal or more from the median (three or more books), or its moneyline favourite does not lay
the 1.5 goals. The main book is the first sound one in `PREFERRED` order (provider "100",
DraftKings, first); `open`, `close` and `consensus` (median moneylines and total,
`n_books`) are derived from it and the pool. `LINES_VERSION` = 2 (in-play books flagged and
never chosen); `espn_phase` re-picks the main line of records stored by an earlier version
from their books, without network (`reselect`).

**Mapping events to games** (`match_events`): ESPN team id (or abbreviation) → the NHL
code of the season (`canon.abbr_from_espn`), then the nearest UTC start within 30 hours
for the same home and away teams, each game used once.

### 2.6 MoneyPuck: `sources/moneypuck.py`

`https://peter-tanner.com/moneypuck/downloads/shots_{YYYY}.zip` (linked from
moneypuck.com/data.htm; YYYY = the season's start year, 2007 on; about 18–20 MB zipped,
about 120,000 rows): **benchmark only**, "xG benchmark data from MoneyPuck.com", free for
non-commercial use with credit, file downloads at most nightly, never scraped. Each season
is converted to `data/nhl/moneypuck/shots_<S>.parquet` with the `KEEP` columns and
`nhl_game_id` = start year × 10⁶ + MoneyPuck's `game_id`; the zip is discarded. The file's
Last-Modified and Content-Length are kept (`meta.moneypuck`), so a completed season is
never downloaded twice and the current season at most once in 20 hours. MoneyPuck's `id` is
not the api-web eventId, and its `xCordAdjusted` folds every shot to +x, so it is not a
direction check. Join: (game, elapsed second, shooter) (`join_events`; 99.8% of 2026–27's
first 618 rows match, all with the same event type); the benchmark itself matches on game,
period, second and shooter ([MODELS.md](MODELS.md) section 2.6).

### 2.7 Prediction markets: `sources/markets.py`

Kalshi (`KXNHL-27` Stanley Cup, `KXNHLEAST` / `KXNHLWEST`, the four division series,
`KXNHLPLAYOFF`, `KXNHLPRES`, `KXNHLSEASONPTS` points ladders per team, `KXNHLHART`,
`KXNHLNORRIS` and the other awards when they list, `KXNHLGAME`, `KXNHLSPREAD`,
`KXNHLTOTAL`, `KXNHLOT`; event suffix = the season's end year) and Polymarket (tag `nhl`
futures, points ladders, award fields, and games via `series_id=10346`, slug
`nhl-<a>-<b>-YYYY-MM-DD`), fetched at build time in CI (never in the browser) and mapped to
NHL codes (`CODE_ALIASES`: LA → LAK, SJ → SJS, NJ → NJD, TB → TBL, LAS → VGK, ...) and
player names. Surveyed 1 October 2026 (fixture `tests/nhl/fixtures/markets_c.json`). The
price rules are in [MODELS.md](MODELS.md) section 13.2.

### 2.8 What is not used, and why

- **MoneyPuck's numbers as metrics**: its terms allow non-commercial use with credit; the
  site uses its xGoal only as a benchmark on the Calibration page.
- **Natural Stat Trick, Evolving-Hockey and similar**: derived data behind their own terms;
  everything here is computed from the NHL's own feeds.
- **Per-play tracking (puck and player positions)**: not public; NHL EDGE publishes season
  aggregates only.
- **Sofascore**: blocks datacenter addresses (the football site's daily problem,
  `docs/RUNBOOK.md`); nothing here needs it.
- **CapFriendly, PuckPedia, Spotrac** (contracts, cap hits, cap space): their terms do not
  allow our reuse, so the valuation, trade grades and trade simulator never use salaries
  and the pages say "not contracts or the cap".
- **Fantasy platforms' ownership, ADP, rankings and prices** (ESPN, Yahoo, Sleeper,
  Fantrax, ...): their terms do not allow our reuse; the Fantasy page's "add / drop" are
  defined from our own projections.
- **ESPN injury comments**: the injuries feed carries a news provider's text; only the status,
  its date, the injury type and the return date are kept.

### 2.9 Transactions, injuries, drafts and player search: `sources/moves.py` (16 Oct 2026)

Raw caches under `<raw>/moves/` (git-ignored, like the rest of `data/nhl/`):

- **ESPN transactions** `site.api.espn.com/apis/site/v2/sports/hockey/nhl/transactions?season=
  <calendar year>&limit=200&page=<n>` → `espn_tx_<year>.json` {year, rows [[date, ESPN team id,
  abbreviation, description]], complete, page_count, fetched_at}. Free text, one row per club per
  day (each side of a trade is its own row), newest first; about 1,850 rows a calendar year. A past
  year is fetched in full once (2025: 10 pages; 2026 so far 7); the hourly build refreshes the
  current year's first two pages (`refresh`: 2 calls) and skips silently offline. NHL api-web has
  no transactions endpoint (`/v1/transactions` answers 404, checked 16 Oct 2026).
- **ESPN injuries** `.../hockey/nhl/injuries` → `espn_injuries.json` {fetched_at, rows [[ESPN team
  id, club, name, status, date, type, return date]]}, refreshed at most hourly (1 call); matched
  to NHL ids by normalised name and club (2026-10-16: 89 of 131).
- **Draft** `records.nhl.com/site/api/draft?cayenneExp=draftYear=<Y>` → `draft/draft_<Y>.json`
  {cols [year, overall, round, in_round, pid, name, team, dob, pos], rows}; one call a year, cached
  for good once the draft is done (2005–2026 on file).
- **Player search** `search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=10&q=<name>` (the
  NHL's own search, the same public NHL data as api-web) → `search.json`, only for names in trades
  that the players index, the stores and the draft records do not know; at most 20 calls a run, a
  miss asked again after 7 days. Accepted only on an exact normalised name (the clubs break ties).
- **Player landing** `api-web.nhle.com/v1/player/<id>/landing` → `landings.json` (birth date,
  position, draft details) for missing birth dates; cached.

Pacing: ESPN and records.nhl.com 0.5 s, api-web 0.25 s (`sources/_client.py`, 2 retries).

**Game logs** (`analytics/gamelog.py`): per season under `<cache>/analytics/gamelog/`: boxscore rows
(`box_<S>_sk|gk.parquet`, each boxscore read once, kept with its file size and mtime) and the joined
logs `log_<S>_{sk,gk,tg}.parquet` keyed on the boxscores, the player-game and shot-table cache keys,
the schedule's model probabilities and the store's results (content, not mtime). About 13 s a past
season once; the current season 1–2 s an hour.

---

## 3. Coverage by season

Read with `python scripts/nhl_fetch.py --report --from 2009 --to 2026` at about 23:20 EDT on
1 October 2026, **mid-backfill**: 2009–10 and 2011–12 to 2013–14 had not been reached, 2014–15
had play-by-play and shifts but no derived tables yet, 2015–16 was in progress, and 2010–11
and 2015–16 carry only a 30-game derived sample. "On-ice" is the share of checked events
whose counts from the shift charts agree with the situation code; "lines" counts final
games with ESPN lines (open / close in brackets).

| Season | Games final (regular + playoffs) | Events | Shots (with x/y) | Stints | On-ice agreement (games < 98%) | EDGE pages | Lines (open/close) | MoneyPuck rows |
|---|---|---|---|---|---|---|---|---|
| 2009–10 | not reached | – | – | – | – | – | – | 110,895 |
| 2010–11 | 1,230 + 89 | 10,130 (30 games) | 3,533 | 8,795 | 0.9924 (2) | – | 0 | 111,405 |
| 2011–12 to 2013–14 | not reached | – | – | – | – | – | – | 108,753; 66,087; 110,682 |
| 2014–15 | 1,230 + 89 | not derived yet | – | – | – | – | 0 | 109,627 |
| 2015–16 | 1,230 + 91 | 10,418 (30 games) | 3,551 | 9,301 | 0.9970 (0) | – | 0 | 109,461 |
| 2016–17 | 1,230 + 87 | 413,339 | 149,661 (149,657) | 363,258 | 0.9942 (32) | – | 0 | 110,953 |
| 2017–18 | 1,271 + 84 | 434,744 | 160,727 (160,718) | 362,883 | 0.9961 (18) | – | 0 | 119,715 |
| 2018–19 | 1,271 + 87 | 433,203 | 157,478 (157,474) | 363,152 | 0.9949 (25) | – | 0 | 117,622 |
| 2019–20 | 1,082 + 130 | 382,738 | 139,200 (139,199) | 329,096 | **0.9556 (200)** | – | 1,211 / 1,212 (0) | 104,172 |
| 2020–21 | 868 + 84 | 287,926 | 104,316 | 260,125 | 0.9868 (134) | – | 951 / 952 (0) | 78,611 |
| 2021–22 | 1,312 + 89 | 436,795 | 160,574 | 454,593 | 0.9931 (48) | 1,536 | 1,401 (0) | 121,471 |
| 2022–23 | 1,312 + 88 | 440,786 | 164,416 | 560,226 | 0.9948 (16) | 1,468 | 1,400 (1,288) | 122,026 |
| 2023–24 | 1,312 + 88 | 445,452 | 171,256 | 558,319 | 0.9969 (16) | 1,436 | 1,398 / 1,400 (1,398) | 122,472 |
| 2024–25 | 1,312 + 86 | 451,857 | 167,558 | 562,766 | 0.9962 (42) | 1,428 | 1,398 (1,398) | 119,870 |
| 2025–26 | 1,312 + 82 | 443,569 | 163,818 | 556,340 | 0.9975 (7) | 1,458 | 1,394 (1,394) | 119,271 |
| 2026–27 (to 1 Oct) | 8 of 1,344 scheduled | 2,551 | 858 | 3,329 | 0.9965 (0) | 302 | 8 (8) | 618 |

Notes: the strict check (the event rule only, no "just after the call" allowance) runs about
0.4–0.6 points lower (2025–26: 0.9930 against 0.9975). The disagreements are mostly stoppages, period ends,
shots and penalties at a change (2025–26: 373 stoppages, 204 period ends, 145 shots on goal,
82 penalties of 1,108). In 2016–17 to 2018–19 the published defending side is absent
(`side_checked` 0), so the direction is the shot-majority vote alone; in 2019–20 the vote and
the published side disagreed in 30 periods, in 2020–21 in 11, and in none from 2021–22. The
normalised zone agrees with the NHL's zone code on 99.5% of unblocked shots (2025–26:
119,545 of 120,154). Attendance comes from ESPN's scoreboards (2019–20 on; 381 of 952 games
in 2020–21). The report counts only shift charts read from stats REST, so it shows 1,341
for 2024–25; the other 57 came from the HTML reports.

---

## 4. Identity: `canon.py`

### 4.1 Teams and seasons

A team is the tri-code the NHL published for that season, with the NHL team id (stats REST
`/team`, verified 1 October 2026): ATL (11) → WPG (52) from 2011–12; PHX (27) → ARI (53)
from 2014–15 (a rename); ARI (53) → UTA (59) from 2024–25 (the NHL lists Utah as a new
franchise that took over the Coyotes' hockey assets; its id became 68 as the Utah Mammoth
from 2025–26, `UTA_MAMMOTH_FROM`); VGK (54) from 2017–18; SEA (55) from 2021–22.
`code_in_season(abbr, season)` gives a club's code in a season; `FRANCHISE` maps the
lineage to today's club (ATL → WPG, PHX and ARI → UTA) for the model priors. ESPN's team
ids and abbreviations (LA, NJ, SJ, TB, UTAH; Arizona id 24, Utah 129764) map through
`ESPN_ID` and `ESPN_ABBR`. `COLOURS` holds each club's primary and secondary colour.

Divisions by era (`_SIX`, `_FOUR`, `_COVID`, `_NOW`): six divisions to 2012–13; four
(Atlantic, Metropolitan, Central, Pacific) 2013–14 to 2019–20 (VGK in the Pacific from
2017–18); four realigned COVID divisions without conferences in 2020–21 (North, East,
Central, West); from 2021–22 Seattle in the Pacific and Arizona (Utah) in the Central.
`nhl_fetch.py --check-canon` compares them with `/v1/standings` at the end of each season
(the docstring says every season 2009–10 to 2025–26 was verified; `CONTRACT.md` says to
2026–27).

### 4.2 Formats

`canon.formats(season)`: 30 clubs to 2016–17, 31 to 2020–21, 32 from 2021–22; 82 games, 48 in
2012–13, 56 in 2020–21, 84 from 2026–27 (2019–20 paused at 68–71 games); points W 2, OTL and
SOL 1; regular-season overtime five minutes (4-on-4 to 2014–15, 3-on-3 from 2015–16) then a
shootout; playoff overtime 20-minute 5-on-5 periods. Playoffs: 16 teams, best of seven;
`conference` (8 a conference, division winners seeded 1–3, re-seeded) to 2012–13,
`divisional_wildcard` (top three of each division and two wild cards a conference, fixed
bracket) from 2013–14, `return_to_play` in 2019–20 (24 teams), `division_2021` in 2020–21.

### 4.3 Arenas

`canon.ARENAS`: 56 arenas (40 home rinks over the window and 16 neutral sites: Global
Series and other one-offs) with name, city, latitude and longitude, IANA time zone, the
home club and the seasons used, and each arena's sponsor names over the window as aliases;
`STADIUMS`: 34 outdoor stadiums matched by name only. `arena_for_game(venue, home, season)`
resolves a game's venue name, falling back to the home club's arena of that season
(`home_arena`; the Islanders' 2015–16 to 2019–20 home is Barclays). Travel uses
`haversine_km`.

### 4.4 Players and games

Players are NHL playerIds; names, positions, shooting hand, birth date, height (inches),
weight (pounds), number and country come from the rosters, topped up from the play-by-play
roster spots. Games are NHL gameIds; ESPN events map to them as in section 2.5.

### 4.5 Situation codes and strength

`decode_situation("1551")` → away goalie in net, away skaters, home skaters, home goalie in
net (so "1451" is a home power play, "0651" an empty away net with six skaters).
`strength_state` gives EV, PP or SH from a team's view, EN when the opponent's net is empty
and PS for a penalty shot or shootout (1v0).

### 4.6 The tiebreaking procedure

`canon.TIEBREAK_STEPS` holds the NHL's steps by era with the NHL's wording (`_STEP_TEXT`),
from NHL.com's "Tie-Breaking Procedure"
(https://www.nhl.com/info/standings-info/tie-breaking-procedure, read 1 October 2026) and,
for earlier eras, the NHL's announcement of the regulation-wins change: from 2019–20 games
played (points percentage), RW, ROW, W, head-to-head (the odd game excluded; percentage of
available points among three or more), goal differential, goals for; 2010–11 to 2018–19 games
played, ROW, head-to-head, goal differential; before, wins first. `TIEBREAK_NOTES` record the
readings: shootout goals count in GF / GA; steps run in order and each still-tied subgroup
carries on from the next step (no restart clause); every step exhausted → abbreviation
order, traced as "unresolved" (the NHL draws lots). `order_tied`, `rank`,
`records_from_games`, `head_to_head` and `playoff_seeds` apply them; the season simulation
uses the same steps ([MODELS.md](MODELS.md) section 12).

---

## 5. The scripts

### 5.1 `scripts/nhl_fetch.py`: sources into the raw files and the stores

```
python scripts/nhl_fetch.py --from 2026 --to 2026 --budget 20000
python scripts/nhl_fetch.py --from 2009 --to 2025 --phases schedule,pbp,shifts,box,edge --min-gap 0.25 --log logs/nhl_backfill_nhl.log
python scripts/nhl_fetch.py --from 2019 --to 2025 --phases schedule,espn --espn-interval 1.0 --log logs/nhl_backfill_espn.log
python scripts/nhl_fetch.py --refresh-current --budget 3000
python scripts/nhl_fetch.py --report --from 2009 --to 2026
python scripts/nhl_fetch.py --check-canon --from 2009 --to 2026
```

| Flag | Meaning |
|---|---|
| `--from`, `--to` | seasons (2009, 20092010 or 2009-10; default the current season); processed **newest first** |
| `--seasons` | an explicit comma list, processed in the order given (overrides `--from` / `--to`) |
| `--phases` | any of `schedule,pbp,shifts,box,edge,espn,moneypuck` (default all seven) |
| `--budget` | calls per run (default 5,000) |
| `--interval` | seconds between calls to one NHL host (default 0.25) |
| `--min-gap` | seconds between any two calls (default 0.25) |
| `--espn-interval` | seconds between ESPN calls (default 1.0) |
| `--max-games` | cap games per phase per season (smoke runs) |
| `--refresh-current` | scheduled mode: the current season only |
| `--no-derive` / `--derive-only` | skip the derived tables / rebuild them without fetching |
| `--report` | print the coverage of the stores and raw files on disk and exit (no network) |
| `--check-canon` | compare `canon`'s clubs and divisions (and games per team) with `/v1/standings` and the season list |
| `--log` | also log to a file (UTF-8) |

Seasons before 2009–10 are dropped unless the phases include `moneypuck`. Within a season,
games are processed newest first. The phases:

- **schedule**: `/schedule/<date>` week by week over the season's window (the stats REST
  season dates; about 40 calls). A week is rescanned until it has been read more than two
  days after its last date; with `--refresh-current`, weeks from three days ago to a week
  ahead are always rescanned. `teams` = `canon.teams(season)`; `meta.complete_through`; a
  standings snapshot (today in the current season, else the last regular-season day); the
  rosters of every club (32 calls; weekly in the current season) → `players`.
- **pbp**: the play-by-play of every final regular-season and playoff game whose file is
  missing (with `--refresh-current`, also games of the last three days read before they
  settled: a file is settled when fetched after noon UTC of the day after the game) →
  `pbp/<S>/<gameId>.json.gz`; players from the roster spots; starters from the
  play-by-play when a game has no boxscore goalies.
- **shifts** (2010–11 on): the shift charts → `shifts/<S>/<gameId>.json.gz`; an empty answer
  for a settled game tries the HTML reports (section 2.3); an empty answer is retried until
  settled.
- **box**: boxscores → `box/<S>/...` and GAME.goalies; a repair pass refills goalies from
  boxscores on disk; the five stats REST reports for the regular season and the playoffs
  (`stats/<S>/<report>_<T>.json.gz`; in the current season at most once in 20 hours).
- **derive**: after pbp or shifts, when anything new arrived or the events file is missing,
  `derive.build_season` rebuilds `events.parquet`, `stints.parquet` and `onice_check.json`
  and a summary goes to `meta.derived`.
- **edge** (2021–22 on): team-detail of every club (and playoffs for playoff teams),
  skater-detail and goalie-detail of every player in the season reports →
  `edge/<S>/{skater,goalie,team}/<id>_<T>.json.gz`; a 404 is remembered as `"none"`.
  Completed seasons once; the current season weekly.
- **espn** (2019–20 on): one scoreboard per game day (re-read until the day is settled;
  with `--refresh-current`, the last two days always) maps events to games (`espn_id`,
  `attendance`); one core odds call per final game (once: `meta.espn_odds[gid].final`) gives
  GAME.lines, keeping an opening line seen earlier; with `--refresh-current`, games up to two
  days ahead read the summary pickcenter, and `partner-game/US/now` fills scheduled games
  that still have no lines.
- **moneypuck**: the season's shot file (section 2.6).

Each phase saves through `store.save_owned` (section 7), every 100 games or calls within a
long phase (`SAVE_EVERY`), and the run logs the client's report at the end.

### 5.2 `scripts/nhl_backfill.ps1`: the detached backfill workers

Starts hidden PowerShell processes, each running `nhl_fetch.py` with the repository's
`.venv\Scripts\python.exe`; every step is resumable, so re-running the script picks up where
the raw files and stores stop. Parameters `-Which nhl|espn|moneypuck|all` (default `all`),
`-From` (default 2009), `-To` (default 2025):

| `-Which` | Workers |
|---|---|
| `nhl` | two workers on alternate seasons, newest first (a: 2025, 2023, ...; b: 2024, 2022, ...): `--seasons <list> --phases schedule,pbp,shifts,box,edge --min-gap 0.6 --interval 0.6 --budget 400000`, logs `logs/nhl_backfill_nhl_a.log` and `_b.log` |
| `espn` | one worker, `--from max(From, 2019) --to To --phases schedule,espn --espn-interval 1.0 --interval 1.5 --min-gap 1.0 --budget 200000`, log `logs/nhl_backfill_espn.log` |
| `moneypuck` | one worker, `--from From --to To --phases moneypuck --min-gap 2.0 --budget 200`, log `logs/nhl_backfill_moneypuck.log` |
| `all` | all four processes |

Pacing: each NHL worker keeps at least 0.6 s between any two of its calls and the ESPN
worker's NHL schedule calls are at least 1.5 s apart, so the NHL hosts see at most about four
requests a second in total. The script prints each worker's PID.

### 5.3 `scripts/nhl_fit.py`: the committed fits

Fits on every season on disk with derived events from `--first` (default 20092010) through
`--through` (default the last completed season, `prev_season(current_season())`). Builder B:
`fit_b.fit_all(seasons, export=True)` (xG, stabilisation, the RAPM prior, the value model;
[MODELS.md](MODELS.md) section 1.2), or with `--models` each module's `export_fits`. Builder
C: for each of `team_strength, game, live, season_sim, awards, backtest`, the module's
`export_fits`, `fit_and_save` or `export`, else `fit_params` + `save_params(committed=True)`.
**None of the C modules has any of those functions, so the C half reports every step as
skipped** ("no export function"); builder C's fits and the backtest are made by
`fit_c.fit_all()` ([MODELS.md](MODELS.md) section 16.2, item 14; [RUNBOOK.md](RUNBOOK.md)
section 4). `--only b|c`, `--models ...`, `--raw`, `--cache`. It prints a JSON report and
exits 1 if any step failed.

### 5.4 `scripts/nhl_hydrate.py`: the current season from the live site (CI)

```
python scripts/nhl_hydrate.py                         # the current season
python scripts/nhl_hydrate.py --season 20262027 --base https://example.org/data
```

Fetches `https://pchattani.github.io/the-quant-rink/data/<S>/store.json` and keeps it when it
is newer than the checkout's (by `updated_at`), writing atomically. A 404 (the first deploy,
or a season not yet published) is not an error; a non-JSON answer is ignored. Raw files and
derived tables are not hydrated: CI restores the current season's from the Actions cache
and the fetch tops them up.

---

## 6. Formats

### 6.1 Season store: `docs/rink/data/<season>/store.json`

```
{"season", "updated_at",
 "teams": {abbr: {"abbr","name","id","conference","division","colour","alt","franchise"}},
 "games": {game_id: GAME},
 "standings": {"date","at","season","rows": [{team, conference, division, gp, w, l, otl, pts, pct, rw, row, gf, ga,
               sow, sol, ties, streak, l10 [w, l, otl], seq {league, conference, division, wildcard}, clinch}]},
 "players": {pid: {"name","first","last","pos","shoots","dob","height","weight","number","team","country"}},
 "meta": {"weeks", "complete_through" (last date with every game final), "season_dates", "rosters_at",
          "pbp", "shifts", "box", "reports", "derived" (the season's derive summary), "edge",
          "espn_days", "espn_odds", "moneypuck" {last_modified, length, rows, at}, "fetched", "sources"}}
```

A GAME:

```
{"game_id", "season", "date" (local), "start" (ISO UTC), "type" (2 | 3), "home", "away", "hs", "as",
 "status": scheduled|live|final|postponed|cancelled, "period", "ot", "so", "venue", "neutral", "venue_tz",
 "series": {round, series, game} (playoffs),
 "goalies": {"home"|"away": {"starter", "used": [pid], "decision"}},
 "lines": {"src", "ml": [home, away], "puck_line": {"home", "price": [h, a]} | null,
           "total": {"line", "over", "under"} | null, "open" / "close": {ml, puck_line, total} | null,
           "consensus": {ml, total, n_books} | null, "books": [{id, name, ml, puck_line, total, open?, close?, suspect?}] | null,
           "v"} | null,
 "attendance", "espn_id"}
```

`puck_line.home` is the home team's line, negative when the home side is favoured. Games are
saved sorted by start. Store sizes: 0.6–0.9 MB a season to 2018–19, 2.4–7.0 MB for 2019–20 to
2023–24 (the books; 2023–24 the largest), 2.2 MB for 2024–25 and 2025–26.

### 6.2 Events: `data/nhl/derived/<S>/events.parquet`

One row per play-by-play event (shootout attempts included, never given on-ice players):
`game_id, season, gtype, event_id, sort, period, ptype (REG/OT/SO), t (s into the period), sec
(elapsed; a regular-season shootout at 3900), type (typeDescKey), team, is_home, x_raw, y_raw,
x, y (normalised: the event team attacks +x), zone (O/N/D for the event team, blue lines ±25),
zone_raw, shot_type, shooter, goalie, assist1, assist2, player1, player2 (faceoff winner /
loser, hitter / hittee, blocker, penalised / drawn by, giver / taker), reason, pen_type,
pen_desc, pen_min, sit, home_sk, away_sk, home_gin, away_gin, strength ("5v4", event team
first), state (EV/PP/SH/EN/PS), score_home, score_away (before the event), penalty_shot,
home_s1..home_s6, home_g, away_s1..away_s6, away_g, n_home_sk, n_away_sk, onice_ok,
onice_strict, stint`. `team` of every shot type, blocked shots included, is the **shooting**
team (from the shooter's roster spot).

**Direction**: per period, the home team's attacking direction is the majority sign of x
over unblocked shots more than 25 ft from centre; a period without such shots falls back to
`homeTeamDefendingSide` ("right" = home defends +x), then to the opposite of the previous
period. **On ice** at second t: a shift with start < t ≤ end (players leaving at a stoppage
were on for the event); faceoffs and period starts take start ≤ t < end. `onice_ok` also
accepts the players just after the call for penalties, stoppages and delayed penalties
(their published situation code often already shows the post-call state); `onice_strict`
does not. Games without shift charts (2009–10, rare gaps) have NA slots and no stints.

### 6.3 Stints: `data/nhl/derived/<S>/stints.parquet`

Each period is cut at every shift start and end; consecutive pieces with the same skaters
and goalies on both sides are merged. Columns: `game_id, season, gtype, stint, period, start,
end (game seconds), t0, t1, dur, home_s1..6, home_g, away_s1..6, away_g, n_home_sk, n_away_sk,
home_gin, away_gin, strength, state (home view, from shift counts), bad (counts outside 3..6
or two goalies), score_home, score_away (at the start), start_zone (home view O/N/D of a
faceoff at the first second, F = on the fly), {home,away}_{sog,fenwick,corsi,goals,pen}`,
and `xg_home` / `xg_away` left empty for builder B (filled in the enriched stints,
[MODELS.md](MODELS.md) section 4). `events.stint` links the two.

### 6.4 The on-ice check: `data/nhl/derived/<S>/onice_check.json`

Per season: games, events, stints, games with shifts, shots (with x/y), checked, ok, rate,
rate_strict, the games below 98% with their first mismatches, side and zone checks, mismatch
types, errors and games without shifts. A summary is copied into `meta.derived`.

---

## 7. Merge rules: `store.py`

**Insert or update** (`merge_game`): a new record never lets a thinner one wipe richer
fields: `lines`, `goalies`, `attendance`, `espn_id`, `venue`, `start`, `hs` and `as` are
kept when the new value is empty; a final game never goes back to scheduled or live (its
status, scores, period, `ot` and `so` are kept).

**Concurrent writers** (`save_owned(store, phases)`): under a lock file beside the store
(`store.json.lock`; a waiter gives up after 900 s, a lock older than 120 s is broken; a save
takes about a second), the store is re-read from disk and only the fields the given phases
own are merged in:

| Phase | GAME fields | `meta` keys | top level |
|---|---|---|---|
| schedule | the whole GAME except the fields other phases own (empty values never replace full ones) | `weeks`, `complete_through`, `sources`, `season_dates`, `rosters_at` | `teams`, `players`; `standings` |
| pbp | `goalies` (only for a game without a boxscore) | `pbp` | `players` |
| shifts | – | `shifts` | – |
| box | `goalies` | `box`, `reports` | `players` |
| espn | `lines`, `espn_id`, `attendance` | `espn_days`, `espn_odds`, `espn_summary` | – |
| edge | – | `edge` | – |
| moneypuck | – | `moneypuck` | – |
| derive | – | `derived` | – |

So the two NHL workers and the ESPN worker can share seasons. The in-memory store is
**replaced** with the merged result after each save: code must never hold a game or meta
dict across a save (re-read `s["games"][gid]`; `CONTRACT.md` 1a).

`complete_through` is the last date through which every game is final (postponed and
cancelled games skipped).

---

## 8. What is committed, what travels with the site, and the caches

| What | Where | In git | On the public site | In the Actions cache |
|---|---|---|---|---|
| Completed seasons' stores | `docs/rink/data/<S>/store.json` | meant to be, by hand; **none yet on 1 October 2026** | yes | – |
| Current season's store | same | **no** | yes (hydrated back each run) | – |
| Calibration | `docs/rink/data/calibration.json` | meant to be; **not yet** | yes | – |
| Fitted models | `oddsmarkets/nhl/models/fitted/` (9 files) | yes | – | – |
| Payloads and manifests | everything else under `docs/rink/data/` | no | yes (restored with `--ignore-existing`) | – |
| Raw files and derived tables, current season | `data/nhl/{pbp,shifts,box,edge,stats,derived}/<S>` | no | no | yes (`rink-raw-<S>-<run_id>`; restored by the `rink-raw-<S>-` prefix) |
| Model and analytics caches, ESPN records, the season list | `data/nhl/cache/` | no | no | yes (`rink-cache-<run_id>`) |
| MoneyPuck files | `data/nhl/moneypuck/` | no | no | no (CI re-downloads the current season's at most daily) |

The `.gitignore` block: `docs/rink/data/**` ignored, then `*/`, `*/store.json` and
`calibration.json` un-ignored. Because the store pattern matches the current season too,
commit stores by explicit path.

In CI the current season is the only one with raw data and derived tables, so the shot and
player models' **fits** for every earlier season come from `models/fitted/` whenever the
cache is cold (`_io.get_fit`: the cached fit when its version matches, else the committed
one), and past seasons' payloads come from the previous deploy: a past season without
derived events on the machine is skipped ("events not on this machine; payloads kept").

---

## 9. Scheduling: `.github/workflows/update_rink.yml` ("Rink Hourly Update")

`cron: '32 * * * *'` and `cron: '2,17,47 * * * *'`, plus `workflow_dispatch`;
`concurrency: rink-build` (not cancelled in progress); 55-minute job;
`permissions: contents: read`. The local hourly Windows task
(`scripts/refresh_sofascore_all.ps1`) also dispatches it, because GitHub drops many
scheduled runs (RUNBOOK section 1).

| Step | Timeout | On failure |
|---|---|---|
| Game-window check: a dispatched run or the `:32` run always continues; a `:02/:17/:47` run reads the deployed `index.json` and continues only if a game in `live`, `today` or `upcoming` is live, or not final and starting between 30 minutes from now and 3 h 30 ago (no index: wait for the hourly run) | – | the rest is skipped |
| Checkout, Python 3.11, `pip install uv`, `uv sync` | – | job fails |
| Season: `canon.current_season()` | – | job fails |
| Restore `data/nhl/{pbp,shifts,box,edge,stats,derived}/<S>` (key `rink-raw-<S>-<run_id>`, restore prefix `rink-raw-<S>-`) | – | cold: the fetch re-pulls the current season |
| Restore `data/nhl/cache` (key `rink-cache-<run_id>`, prefix `rink-cache-`) | – | cold caches (committed fits used) |
| Clone the public repo with the deploy key; `rsync -a --ignore-existing /tmp/prev/data/ docs/rink/data/` | 10 min | continue (cold build) |
| `nhl_hydrate.py` | 5 min | continue |
| `nhl_fetch.py --seasons <S> --refresh-current --budget 3000` | 20 min | continue |
| `build_rink.py --game-page-seasons 2` | 25 min | job fails |
| Prune `docs/rink/data/<S>/games/` for seasons ≤ current − 2 (8-digit ids ≤ `(start year − 2) × 10001 + 1`) | – | job fails |
| Deploy: clone the public repo, `rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/rink/ /tmp/site/`, commit "Site update <UTC stamp>" (only when something changed), push | – | job fails |

The restore step uses `--ignore-existing`, so the checkout's committed inputs win over the
deployed copies; the hydrate step then replaces the current season's store with the deployed
one when it is newer. A typical hourly run calls api-web for a few schedule weeks, the
standings and any new final games' play-by-play and boxscores, stats REST for their shift
charts (and the season reports at most every 20 hours), ESPN for two days of scoreboards,
the odds of newly final games and the pickcenters of games up to two days ahead, the partner
odds once, MoneyPuck at most daily, and the markets once at build time.

---

## 10. The backfill

Started on the owner's machine on 1 October 2026 (times EDT, the logs' local time):

```
powershell -File scripts/nhl_backfill.ps1 -Which all          # or nhl / espn / moneypuck
```

- **MoneyPuck** (17:25–17:26): 2025–26 back to 2009–10, 34 calls, 305.4 MB, 75 s, 0 failures.
- **ESPN** (17:41–20:43, after a first pass for 2025–26 and 2024–25 at 17:27–17:41): 2025–26
  back to 2019–20, 10,370 calls (api-web 282, ESPN site 1,058, ESPN core 9,030), 302.8 MB,
  10,891 s, 0 failures; final games with lines 1,394 / 1,394 (2025–26), 1,398 / 1,398,
  1,398 / 1,400, 1,400 / 1,400, 1,401 / 1,401, 951 / 952 and 1,211 / 1,212 (2019–20).
- **NHL** (from 17:26, two workers): a season takes 2,866–5,749 calls and 40–80 minutes per
  worker (2025–26: 4,411 calls, 3,732 s; 2023–24: 5,646 calls, 4,753 s; 2020–21: 2,866
  calls, 2,363 s), the derived tables 148–309 s of that. 2016–17 to 2025–26 were complete by
  23:11; worker a was then in 2015–16, worker b in 2014–15, with 2013–14 to 2009–10 to
  follow. Expected to finish at about 03:15 EDT on 2 October 2026.
- **The HTML fallback** for 2024–25 (18:26–18:36): 57 games rebuilt from the TOI reports
  (171 calls: 114 to www.nhl.com, 57 to stats REST; 588 s with the season's derived tables).

The backfill is resumable and idempotent: a game's raw file is fetched once, the derived
tables are rebuilt only when something new arrived, the ESPN phase reads a final game's odds
once (`meta.espn_odds`), and MoneyPuck files are kept by Last-Modified. Check progress with
the logs (`Get-Content logs\nhl_backfill_nhl_a.log -Tail 20`) and coverage with
`python scripts/nhl_fetch.py --report --from 2009 --to 2026`. When it finishes, refit the
models on the full history ([RUNBOOK.md](RUNBOOK.md) section 4).

---

## 11. Failure modes

| Symptom | Cause | Effect |
|---|---|---|
| `<S> shifts: ... N empty` | stats REST answered an empty chart | retried until the game settles, then the HTML reports; a game without either has NA on-ice slots and no stints |
| `derive <gid> failed: ...` | one game's play-by-play or shifts did not parse | that game is left out of the season's tables (`errors` in the check); the rest are built |
| on-ice agreement well below 0.99 for a season | shift charts and situation codes disagree (2019–20: 0.9556, 200 games below 98%) | on-ice rates, stints and RAPM for those games carry the error; see section 12 |
| ESPN 5xx / timeouts | ESPN | that call is skipped; the next run retries |
| `unmatched events` in the ESPN log | an ESPN event without an NHL game for the same teams within 30 h (2021–22: 65, 2020–21: 56, mostly neutral or postponed games) | no `espn_id` or lines for it |
| `BudgetExhausted` in the log | the run's budget spent | stops cleanly; the next run continues |
| `TimeoutError: lock ... held too long` | another writer kept the store lock past 900 s | the phase's save fails; re-run (a lock older than 120 s is broken) |
| the hydrate logs "no deployed store (first run?)" | first deploy, or a new season | the checkout's store (or none) is used; CI rebuilds the season's store from the schedule on the next fetch |
| a MoneyPuck download fails | peter-tanner.com | the previous Parquet is kept; the benchmark uses it |

---

## 12. Known gaps and sharp edges

1. **The historical backfill was still running** when the committed fits and
   `calibration.json` were made (section 10; [MODELS.md](MODELS.md) section 14.3).
2. **Shift charts start in 2010–11**; 2009–10 has events but no stints, so no TOI, on-ice
   rates, RAPM, lines or value.
3. **2019–20's on-ice agreement is 0.9556** (200 games below 98%), against 0.987–0.998 in
   every other full season on disk; its stints and on-ice numbers are the least reliable.
4. **The published defending side is absent before about 2019–20**, so the direction rests
   on the shot-majority vote; it disagreed with the published side in 30 periods of 2019–20
   and 11 of 2020–21, none from 2021–22.
5. **ESPN's open and close blocks** exist for 1,288 games of 2022–23 as well as from 2023–24,
   though `canon.ESPN_OPEN_CLOSE_FROM` says 2023–24; before that `current` (read after the
   game) is the close.
6. **The current season's store exists only on the deployed site.** If the public repo is
   lost, the next fetch rebuilds the store from the schedule, but the ESPN pickcenter
   opening lines of past games are not re-read; recover with a local
   `nhl_fetch.py --seasons <S> --phases espn`.
7. **The coverage report undercounts shifts rebuilt from the HTML reports** (it counts only
   plain marks in `meta.shifts`).
8. **Arenas, divisions and formats are hand-entered** in `canon.py` (checked against the
   NHL's standings with `--check-canon`); a new venue name needs an alias or its games fall
   back to the home rink.
9. **`canon.current_season` turns over on 1 July**, but `_cdata.season_of_date`,
   `sources/markets.season_for` and the analytics layer's fallback turn over on 1 August
   ([MODELS.md](MODELS.md) section 16.2).

---

## 13. Operator quick reference

```bash
# Current season, as CI does it
python scripts/nhl_hydrate.py
python scripts/nhl_fetch.py --refresh-current --budget 3000

# One past season again (raw files on disk are kept; the derived tables rebuild when something new arrives)
python scripts/nhl_fetch.py --seasons 20242025 --phases schedule,pbp,shifts,box
python scripts/nhl_fetch.py --seasons 20242025 --derive-only

# ESPN lines for a season
python scripts/nhl_fetch.py --seasons 20222023 --phases schedule,espn

# Coverage of the stores and raw files on disk
python scripts/nhl_fetch.py --report --from 2009 --to 2026

# Canon against the NHL's standings
python scripts/nhl_fetch.py --check-canon --from 2009 --to 2026

# Backfill progress (UTF-8 logs)
Get-Content logs\nhl_backfill_nhl_a.log -Tail 20
Get-Content logs\nhl_backfill_nhl_b.log -Tail 20
```
