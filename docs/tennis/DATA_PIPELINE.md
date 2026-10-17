# Data pipeline: extraction and storage (tennis)

How The Quant Ace gets its data: the four sources and why only these, what each year
holds, how players and events from different sources become one identity, the
scripts, the store format and the merge rules, what is committed and what travels
with the site, the hourly job and the backfill. Models are in [MODELS.md](MODELS.md);
the payloads built from the stores are in [DASHBOARD.md](DASHBOARD.md).

Contents

1. Overview and data flow
2. Sources
3. Coverage by year
4. Identity: `canon.py` and the registry
5. The scripts
6. Formats
7. Merge rules: `store.py`
8. What is committed, what travels with the site, and the caches
9. Scheduling: `.github/workflows/update_ace.yml`
10. The backfill
11. Failure modes
12. Known gaps and sharp edges
13. Operator quick reference

---

## 1. Overview and data flow

```
 tennis-data.co.uk            ESPN site API                 api.wtatennis.com            Match Charting Project
 data.php → prefixed links    scoreboard?dates=YYYY|DAY     calendar, matches, draw,     raw.githubusercontent.com
 <year>[w]/<year>.xls[x]      rankings                      matches/<id>/stats, ranking  charting-{m,w}-*.csv
        │                           │                              │                            │
 sources/tennisdata.py        sources/espn.py               sources/wta.py               sources/charting.py
        │  source match records (canon.SMR_DOC), sides "a"/"b" │                            │
        └───────────────┬───────────┴──────────────────────────┘                            │
                        ▼                                                                   ▼
            scripts/tn_fetch.py  (per tour, per year newest first;                scripts/tn_charting.py
            phases espn → wta → td → rankings)                                             │
              Ingest: canon.Registry resolves each side to a pid                           │
              store.event_for finds/creates the event; store.merge_record merges           │
                        │                                                                   │
                        ▼                                                                   ▼
   docs/ace/data/<tour>/<year>/store.json      docs/ace/data/<tour>/registry.json   docs/ace/data/<tour>/style.json
                        │
                        ▼
   models (Elo, serve/return, chain, simulations) ──► scripts/build_ace.py ──► docs/ace/data/** payloads
```

Raw downloads are cached under `data/tennis/` (git-ignored; env `ACE_RAW`):
`td/<tour>/<year>.xls[x]` with a `.meta.json` beside each, `wta/<year>/<gid>/` (the
matches answer and one stats file per match), `charting/` (the CSVs). The data root
is `docs/ace/data` unless `ACE_DATA` points elsewhere; model caches are under
`data/tennis/cache` (`ACE_CACHE`).

---

## 2. Sources

### 2.1 The client: `sources/_client.py`

Every source goes through one `Client`: requests at least `interval` seconds apart
(0.5 s by default, so two a second), up to 4 attempts, a 60 s timeout, a call
`budget` per run. After a network error it sleeps 3 s × the attempt; after HTTP 429
or a 5xx it honours `Retry-After`, else 10 s × the attempt, at most 120 s. Any other
status, or a non-JSON answer to `get`, is logged, counted in `failures` and returned
as `None`: **the client never raises on a bad answer**. Running out of budget raises
`BudgetExhausted`, which `tn_fetch` catches to stop cleanly; the next run resumes.
The user agent is `The Quant Ace (pchattani.github.io/the-quant-ace; tennis
analytics, non-commercial)`. `report()` gives calls per host, failures and seconds on
the network, and `tn_fetch` logs it at the end of every run.

`tn_fetch` makes three clients: ESPN and WTA with `--budget` and `--interval`, and
tennis-data with a budget of `max(60, min(budget, 200))` and at least 1 s between
calls.

### 2.2 tennis-data.co.uk: `sources/tennisdata.py`

The backbone: every ATP tour-level main-draw singles match from 2000 and every WTA
one from 2007, with round, surface, court (indoor/outdoor), best-of, games per set,
entry ranks and ranking points, the result status (the `Comment` column) and closing
odds. Credited on the site.

- **The hidden prefix.** The yearly workbooks live under a path prefix that the site
  rotates; the links with the prefix are on `data.php` (`alldata.php` lists the same
  files without it). Every run that needs a workbook reads the link page first (one
  call): `links()` tries `data.php`, then `alldata.php`, and keeps the first page
  whose links carry a prefix (`https://host/prefix/2026/2026.xlsx`); the link pattern
  is `[prefix/]YYYY[w]/YYYY.(xlsx|xls|zip)`, a `w` after the year for the WTA.
- **Downloads.** `fetch()` writes `data/tennis/td/<tour>/<year>.<ext>` atomically,
  only when the body starts like a workbook (`PK\x03\x04` or the OLE header), with
  a `.meta.json` (url, Last-Modified, ETag, bytes, fetched). A cached completed year
  is never re-read; the current year is re-requested with `If-Modified-Since`, so an
  unchanged file costs one 304.
- **Formats.** 2013 on are `.xlsx` (openpyxl); 2000–2012 are BIFF `.xls`, which
  need `xlrd` (without it those years are skipped and reported). Both are in
  `pyproject.toml`.
- **Columns** (verified 1 October 2026): ATP `ATP, Location, Tournament, Date,
  Series, Court, Surface, Round, Best of, Winner, Loser, WRank, LRank, WPts, LPts,
  W1..L5, Wsets, Lsets, Comment, B365W/L, PSW/L, MaxW/L, AvgW/L, BFEW/L`; the WTA has
  `WTA` and `Tier` in place of `ATP` and `Series` and only `W1..L3`. Older years
  carry other books (`CB, EX, IW, LB, SB, SJ, UB, GB, B&W, BFD, PSC`), kept in
  `odds.other`. Names are "Surname I." ("Sinner J.", "Fernandez L.A.", "Ugo
  Carabelli C."). **No tiebreak points, no seeds**, and before 2003 `Date` is the
  tournament's start for every match.
- **Odds kept**: `ps` (Pinnacle), `b365`, `avg`, `max`, `bfe`, decimal closing
  prices, only when both sides exist and exceed 1. **2009 has no Pinnacle column on
  either tour** (both stores hold 0 Pinnacle prices for 2009), the ATP has no
  Pinnacle before 2004 and no odds at all in 2000, and **2026's Pinnacle column is
  thin** (71 ATP and 101 WTA matches priced by 1 October).
- **Parsing** (`parse`): rows are grouped into events by the file's tournament
  number, name and location; groups with the same name and location merge when they
  start within 3 days or share no round (the files sometimes split one event, as in
  WTA Charleston 2018 and ATP Montpellier 2020). Levels come from `Series`/`Tier`
  (`canon.level_from_series`, corrected by `canon.fix_level` for the WTA Premier
  Mandatory and Premier 5 events of 2009–2020 and two known mislabels). Round names
  ("1st Round" …) are converted per event: once an event has reached its
  quarter-finals the number of numbered rounds fixes the labels; before that the
  bracket comes from the level and the size of the first round
  (`canon.td_round_labels`). Statuses: Completed → `done`, Retired → `ret`,
  Walkover → `wo`, Disqualified/Def → `def`, Sched → `upcoming`; cancelled rows are
  dropped, and spelling slips in the files ("Rrtired", "Walkoer") are caught. A last
  0-0 set (a retirement before the set began) is dropped. The winner is side "a".

### 2.3 ESPN: `sources/espn.py`

The public site API (no key, CORS `*`):

- `site.api.espn.com/apis/site/v2/sports/tennis/{atp,wta}/scoreboard?dates=YYYYMMDD`:
  every tournament in progress that day with all its matches (finished, live and
  scheduled, qualifying included; future rounds appear with TBD competitors, ids
  −3/−4), grouped by draw (`mens-singles`, `womens-singles`, doubles …). Combined
  events appear in both feeds, so each tour keeps only its own singles grouping.
- `…/scoreboard?dates=YYYY`: the whole season in one answer (about 20 MB; ATP 2025:
  61 tournaments, 3,941 men's singles matches).
- `…/rankings`: the latest official ranking, top 150, with athlete ids, names and
  citizenship.

Linescores are games per set; a set that went to a tiebreak carries the tiebreak
points (kept only on 7-6 sets); a live set at 6-6 carries the running tiebreak score.
**No match statistics, no point-by-point, no server.** Round names ("Round 1",
"Quarterfinal", "Qualifying 1st Round" …) are converted per event from the full list
of the event's rounds (`canon.espn_round_labels`; ESPN lists scheduled rounds too, so
the count is reliable); older Finals scoreboards leave the round-robin rounds
unnamed (taken as RR), and other unnamed rounds in older seasons are duplicate rows
under second athlete ids (dropped). ESPN dates some old matches 1900-01-0x; those
dates are discarded. The event end is ESPN's `endDate` minus 6 hours (it is 03:59Z
the next morning). Cancelled, abandoned and bye statuses are skipped.

**ESPN has no draw endpoint for the ATP**: before the draw is made its slots are
TBD; once it is made, first-round pairings appear by name, but with no seed, no
bracket position and nothing linking a first-round match to its second-round slot.
ATP (and Slam) draws are therefore reconstructed (section 7.4).

The season scoreboards are empty before 2007 (the backfill read 0 records for ATP
2004–2006), so `ESPN_FROM = 2007` and ESPN contributes from 2007: tiebreak points, exact match times, and (from 2022 for the ATP) qualifying.

### 2.4 The WTA API: `sources/wta.py`

`api.wtatennis.com/tennis` (no key; the client sends a `Referer:
https://www.wtatennis.com/` header):

- `/tournaments/?from=&to=&pageSize=100&page=N`: the calendar (ITF events dropped
  by `canon.level_from_wta`), with level, surface, indoor/outdoor, city and singles
  draw size.
- `/tournaments/{gid}/{year}/matches`: every match: `DrawMatchType` S/D,
  `DrawLevelType` M (main) or Q, `MatchID` "LS001" (1 = final, 2–3 semi-finals,
  4–7 quarter-finals …, so the number gives round and bracket position), player ids,
  names, countries, seeds, entry types, set scores, `ScoreTbSet{n}` (the tiebreak
  loser's points), `MatchState` F/P/U, `Winner` codes 2–9 (won, by retirement, by
  walkover, by default), live points and server, `MatchTimeTotal`.
- `/tournaments/{gid}/{year}/matches/{MatchID}/stats`: per-match statistics (set 0 =
  the match, then per set): aces, double faults, first serves in and won, serve
  points won, service games, break points converted and played, from which STATS is
  built (`_stat_side`).
- `/tournaments/{gid}/{year}/draw`: the draw (`LS` main singles), positions, seeds,
  entry types and byes, with names for players not yet linked to their WTA id.
- `/players/ranked?type=rankSingles&metric=SINGLES`: the ranking, paged by 100 (top
  1,000 kept), with dates of birth.

Depth (measured 1 October 2026): match lists exist from **2016** (2015 and earlier
answer empty; some events have gaps, e.g. Miami 2018), and the stats endpoint answers
for those matches. **Grand Slams are not served** (they are ITF events): their women's
matches come from ESPN and tennis-data only, without statistics or a WTA draw. Raw
answers are cached under `data/tennis/wta/<year>/<gid>/`; a finished tournament's
matches and a finished match's stats are read from the cache rather than called again.

### 2.5 The Match Charting Project: `sources/charting.py`

Shot-by-shot records of volunteer-charted matches (Jeff Sackmann and contributors,
Tennis Abstract), from
`raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/master`
(the repository answered 200 on 1 October 2026; Sackmann's results repositories did
not, section 2.7). Files per tour (`m`, `w`): `charting-{m,w}-matches.csv` and
`charting-{m,w}-points-{to-2009,2010s,2020s}.csv` (about 95 MB men, 60 MB women),
downloaded once into `data/tennis/charting/` and never committed.

**Licence: CC BY-NC-SA 4.0** — attribution required, non-commercial use, derived
data shared alike. `charting.LICENSE` (name, URL, attribution, source, the
share-alike note) is written into `style.json`'s `_meta`; the disclaimer and the
footer of the site credit and link the project.

`parse_point` implements the MatchChart 0.3.2 shot-code grammar: the serve
(direction 4 wide / 5 body / 6 T, serve-and-volley `+`, fault letters, ace `*`,
unreturnable `#`), rally shots (letters for groundstrokes, slices, volleys, overheads,
drop shots, lobs, half-volleys, swinging volleys, trick shots; approach, net and
net-cord modifiers; direction; return depth 7/8/9; error types with forced `#` /
unforced `@` / winner `*`) and whole-point codes (S, R, P, Q). `accumulate` and
`summarize` turn points into per-player tables (section 6.4). Charting covers a
selected sample of matches, weighted to big matches and well-known players.

### 2.6 Prediction markets: `sources/markets.py`

Kalshi (`KXATPMATCH`/`KXWTAMATCH` matches, `KXATP`/`KXWTA` tournament winners,
Finals winner and qualification, year-end No. 1, next year's Slams) and Polymarket
(tag `tennis`: match moneylines, tournament winners, year-end No. 1 and top 10,
"Player to Qualify"), fetched at build time in CI (never in the browser) and mapped
to pids and store matches by name. Details in [MODELS.md](MODELS.md) section 9.

### 2.7 What is not used, and why

- **Jeff Sackmann's `tennis_atp` and `tennis_wta` repositories** (match results with
  per-match serve statistics, the usual free source) were taken down: they answered
  404 on 1 October 2026 (checked again while writing this). This is why ATP serve and
  return is inferred from scores.
- **atptour.com** and **Sofascore** block scripted access (Sofascore's 403 challenge
  is the football site's daily problem, `docs/RUNBOOK.md`).
- **The ITF** (Slams' own data) offers no usable public API; the Slams' women's
  matches therefore have no statistics.
- **ESPN** is used, but has no statistics, no server and no ATP draw (above).

---

## 3. Coverage by year

Read from the stores' `meta.sources.coverage` on 1 October 2026. "Main" is
tour-level main draw; "Q" qualifying; "CH" Challenger / WTA 125; "PS" matches with a
Pinnacle price; "TB" matches with tiebreak points; "Stats" matches with WTA
statistics; draws are counted by source.

**ATP**

| Year | Main | Q | Odds | PS | TB | Events | Sources of main-draw matches | Draws |
|---|---|---|---|---|---|---|---|---|
| 2000 | 2,963 | 0 | 0 | 0 | 0 | 69 | td only | reconstructed |
| 2001–2003 | 2,854–2,963 | 0 | 2,534–2,802 | 0 | 0 | 66–69 | td only | reconstructed |
| 2004–2006 | 2,877–2,909 | 0 | 2,806–2,887 | 2,698–2,835 | 0 | 67 | td only (ESPN empty) | reconstructed |
| 2007–2008 | 2,740–2,815 | 0 | 2,679–2,767 | 2,658–2,751 | 971–985 | 66–67 | ESPN + td | reconstructed |
| 2009 | 2,735 | 0 | 2,711 | **0** | 937 | 66 | ESPN + td | reconstructed |
| 2010–2019 | 2,602–2,689 | 0 | 2,599–2,669 | 2,583–2,657 | 919–1,046 | 64–67 | ESPN + td | reconstructed |
| 2020 | 1,298 | 0 | 1,267 | 1,258 | 517 | 33 | ESPN + td | reconstructed |
| 2021 | 2,553 | 0 | 2,488 | 2,482 | 928 | 62 | ESPN + td | reconstructed |
| 2022–2025 | 2,632–2,769 | 1,247–1,342 | 2,628–2,699 | 2,532–2,691 | 1,423–1,586 | 60–68 | ESPN + td | reconstructed |
| 2026 (to 1 Oct) | 2,249 | 1,146 | 2,204 | **71** | 1,349 | 50 | ESPN + td | reconstructed |

**WTA**

| Year | Main | Q | CH | Odds | PS | TB | Stats | Events | Draws (wta / reconstructed) |
|---|---|---|---|---|---|---|---|---|---|
| 2007–2008 | 2,405–2,493 | 0 | 0 | 2,380–2,464 | 2,330–2,413 | 442–470 | 0 | 58–61 | 0 / 57–60 |
| 2009 | 2,434 | 0 | 0 | 2,413 | **0** | 471 | 0 | 55 | 0 / 53 |
| 2010–2015 | 2,433–2,534 | 0 | 0–134 | 2,407–2,517 | 2,395–2,511 | 433–540 | 0 | 57–60 | 0 / 56–58 |
| 2016 | 2,615 | 559 | 247 | 2,517 | 2,511 | 627 | 793 | 69 | 23 / 44 |
| 2017–2019 | 2,475–2,565 | 881–1,047 | 155–420 | 2,468–2,498 | 2,452–2,493 | 765–809 | 1,260–1,459 | 65–70 | 44–49 / 17–24 |
| 2020 | 1,089 | 446 | 220 | 1,054 | 1,049 | 410 | 697 | 27 | 24 / 3 |
| 2021–2025 | 2,506–2,574 | 931–1,849 | 523–1,736 | 2,365–2,505 | 2,351–2,476 | 822–1,308 | 1,784–1,980 | 75–109 | 66–106 / 3–17 |
| 2026 (to 1 Oct) | 2,254 | 1,761 | 1,730 | 2,190 | **101** | 1,190 | 2,202 | 102 | 97 / 5 |

Notes: the WTA's 2010–2013 "CH" rows are events tennis-data does not list that ended
before tennis-data's last date and were graded below tour level (section 5.1, phase
td). Style tables: ATP 1,284,276 charted points in 7,532 matches (1960-05-29 to
2026-05-21), 1,000 players of whom 787 link to the registry; WTA 593,481 points in
4,253 matches (1979-09-28 to 2026-09-09), 737 players, 660 linked.

---

## 4. Identity: `canon.py` and the registry

### 4.1 Players

A player id is the ESPN athlete id when known, else `x:<slug of the name>`
(`Registry._new_pid`). `canon.Registry` (persisted as
`docs/ace/data/<tour>/registry.json`: `players` with name, first, last, short,
country, hand, dob, height, espn, wta, aliases, and `redirects`) resolves every
source name:

- **Full names** (ESPN, WTA, rankings: `Registry.add`): first by ESPN or WTA id, then
  by folded alias (`canon.fold`: accents and punctuation removed, `ø`, `ł`, `ß` …
  transliterated; "Jr" dropped; Chinese order reversed as an alternative), preferring
  a candidate in the event's field, then a unique candidate, then country, then date
  of birth; a different date of birth means a namesake. Then against players known
  only by a tennis-data abbreviation. A player with a second ESPN or WTA id (ESPN and
  the WTA both keep duplicate profiles; Venus Williams has WTA ids 18251 and 230220)
  gets it as `espn_alt`/`wta_alt`. An `x:` player who gains an ESPN id is renamed to
  it (`_promote`) and the old id redirected.
- **"Surname I." names** (tennis-data: `Registry.resolve_abbrev`), in this order:
  `overrides.json` names; the event's full-name field (scored by
  `canon.abbrev_matches`: 3 = surname and every initial, 2 = surname and the first
  initial, less for Chinese order or a dropped second surname); a unique earlier
  alias with the same raw string; the whole tour; the event's only player with that
  surname (sources romanise given names differently: "Dolgopolov O." for Alexandr
  Dolgopolov); a lenient in-field match (a surname token among the player's names and
  the first initial on another: "Vallejo D." for Adolfo Daniel Vallejo). Anything left
  becomes a new `x:` player flagged `_abbrev`, counted as `unresolved` when the event
  had a full-name field, else `td_only` (2000–2006 ATP matches have no ESPN field).
  After each year, `link_abbrev_players` merges `_abbrev` players into a unique
  full-name match.
- **Charting and market names** (`Registry.find`): full name, every first/last split
  ("Felix Auger Aliassime"), a shortened compound surname ("Albert Ramos" for
  Ramos-Vinolas); never creates a player.
- **Same player, two profiles**: when ESPN and the WTA name one player differently
  ("Catherine" / "Caty McNally") and a same-score match ties them, an ESPN-only and a
  WTA-only profile with the same surname and first initial are merged
  (`Ingest._link_identity`, `Registry.merge`; ESPN ids win).

`oddsmarkets/tennis/overrides.json` holds the hard cases per tour: `names` (a raw
name → pid: ATP "Barrios M." → 9923, Marcelo Tomas Barrios Vera; "Miguel L." → 14643,
Luiz Augusto Miguel), `espn_names` (an ESPN athlete whose profile carries the wrong
name: ATP 5029 shows "Yuliya Hatouka" in Rogerio Dutra Silva's matches), `same`
(merges; none yet) and `_why` for each. The WTA has none.

Resolution rates at the end of the backfills (`logs/tn_backfill_*.log`): ATP
tennis-data 143,100 names, 17 unresolved, 782 `td_only` (rate 0.9999); WTA
tennis-data 95,200 names, 41 unresolved (0.9996); ESPN and WTA full names 1.0.

### 4.2 Events

A tournament's canonical id `tid` (`canon.tid_for`) comes from name patterns tried
first (`NAME_TIDS`: the four Slams, the Finals, Cincinnati, Queen's, Canada, the
Olympics, and team events and exhibitions mapped to `skip`: Laver Cup, United Cup,
Hopman, Davis and Billie Jean King / Fed Cup, Six Kings, exhibitions; the Next Gen
Finals are skipped too), then the city (`CITY_ALIASES`: "key biscayne" → miami,
"rosmalen" → s-hertogenbosch …). A second event of the same year with the same tid
becomes `tid-2` (`unique_tid`). The event id is `<tid>-<year>`. `KNOWN_LEVELS` gives
the current calendar's levels for events seen in ESPN or the WTA API before
tennis-data has them; `DRAW96` the 96-player Masters/1000s by year.

`store.event_for` places a source record on an event: by its source id, then by
date overlap (3 days' slack) scored on the tid (3), the city (2), shared name tokens
(up to 2) and a city named inside the other source's name (2), needing 2 and a unique
best. tennis-data events are placed by their matchups instead
(`Ingest.place_td_events`: the share of the event's "Surname I." pairs found as
stored matches of a candidate event within 4 days; at least 30 % and a 20-point lead
over the runner-up), which survives missing cities and sponsor names. Events first
made from ESPN take tennis-data's tid when it joins (`rename_td_events`, except the
Slams, Finals, Olympics and Elite Trophy).

### 4.3 Rules and tables (hand-entered, marked VERIFY)

`canon.py` holds the tables the models use: levels from `Series`/`Tier` and the WTA
API; best-of (men's Slam main draws 5, else 3, unless tennis-data's `Best of` says
otherwise); deciding-set rules by event and year (`final_set_rule`: Australian Open
advantage to 2018 then tb10; Roland Garros advantage to 2021 then tb10; Wimbledon
advantage to 2018, tb7 at 12-12 2019–2021, then tb10; US Open tb7 to 2021 then tb10;
Olympics advantage to 2012 then tb7; everything else tb7; qualifying always tb7);
ranking points per level and round from the 2025 rulebooks (`POINTS`, with 56-draw
1000 and 48-draw 500/250 variants and the Finals' 200 per round-robin win, 400 for
the semi-final, 500 for the final). These tables apply to every year: past seasons'
points are computed with the 2025 tables.

---

## 5. The scripts

### 5.1 `scripts/tn_fetch.py`: sources into the stores

```
python scripts/tn_fetch.py --tour atp --from 2026 --to 2026
python scripts/tn_fetch.py --tour wta --from 2007 --to 2025 --budget 60000 --log logs/tn_backfill_wta.log
python scripts/tn_fetch.py --tour atp --refresh-current --budget 300
python scripts/tn_fetch.py --tour wta --report --from 2016 --to 2026
```

| Flag | Meaning |
|---|---|
| `--tour` | `atp` or `wta` (required) |
| `--from`, `--to` | years (default: the current year); processed **newest first** |
| `--phases` | any of `espn,wta,td,rankings` (default all) |
| `--budget` | calls per source per run (default 3,000) |
| `--interval` | seconds between calls (default 0.5) |
| `--refresh-current` | hourly mode: the current year only, day scoreboards, live WTA events |
| `--espn-from` | first year read from ESPN (default 2007) |
| `--no-stats` | skip the WTA per-match statistics |
| `--force-td` | re-merge tennis-data even when its file is unchanged |
| `--log` | log file (default `logs/tn_fetch_<tour>.log`) |
| `--report` | print the coverage of the stores on disk and exit |

Per year it loads the store through the registry, then runs the phases in this
order, so that tennis-data's abbreviations resolve against full-name fields:

- **espn** (from `ESPN_FROM`): a completed year's season scoreboard once (marked
  `meta.fetched.espn_year`; the current year re-read when older than 6 hours). With
  `--refresh-current`, the current year reads one day scoreboard for each of the six
  days from 3 days ago to 2 days ahead instead (live, upcoming, new draws).
- **wta** (WTA only, from 2015): the calendar (cached in the store for completed
  years), then for each tournament that has started, newest first: its matches
  (1 call), its draw (1 call) and, for every finished main-draw match of a tour-level
  (not WTA 125) event, its statistics (1 call a match; marked fetched only once
  merged, so a budget stop does not lose them). A tournament is marked `complete`
  once nothing in it is live or upcoming; with `--refresh-current`, only those
  within 14 days back and 10 ahead are read, and events that ended in the last two
  days are re-read. A year whose first 6 tour-level tournaments all answer empty is
  marked `empty_year` and skipped (2015).
- **td**: the year's workbook. A completed year merges once (`meta.fetched.td`);
  the current year (and the previous one in January) re-merges whenever the file's
  Last-Modified moves. After merging, events tennis-data does not list that ended
  before its last date, that the WTA calendar did not grade and that are not Slams,
  Finals, Olympics or Elite Trophy are graded `ch` (tennis-data lists every
  tour-level event), and `link_abbrev_players` runs.
- **rankings** (current year): ESPN's top 150 (ATP), then the WTA API's top 1,000
  (WTA; after ESPN's so its ids link), into `store.rankings`.

Then (always, in a `finally`) `fill_from_history` (surface, indoor and level of
ESPN-only events from the same tournament in the last three years),
`finalize_events` (status, champion, reconstructed draws, a past year's never-played
matches dropped), `set_players`, the coverage and identity reports into
`meta.sources`, and atomic saves of the store and the registry.

### 5.2 `scripts/tn_charting.py`: style tables

```
python scripts/tn_charting.py --tour atp
python scripts/tn_charting.py --tour wta --refresh --min-points 200
```

Downloads the tour's four CSVs once (`--refresh` re-downloads; budget 20 calls, 1 s
apart), parses every point and writes `docs/ace/data/<tour>/style.json` (section
6.4). Names are matched with `Registry.find` (no new registry entries); unmatched
charted players (pre-2000 careers, juniors, Challenger players) are keyed
`x:<slug>` with `linked: false`. `--save-registry` writes the charting aliases and
hands into the registry; do not use it while a backfill of the tour runs. Logs to
`logs/tn_charting_<tour>.log`.

### 5.3 `scripts/tn_fit.py`: the committed constants

Fits Elo's constants (`elo.export_fits`, 2005–2019 log-loss) and the serve/return
model (`serve_return.export_fits`), and with `--backtest` runs the walk-forward
backtest, which writes the blend weights (`predict_<tour>.json`) and
`calibration.json`. See [MODELS.md](MODELS.md) and [RUNBOOK.md](RUNBOOK.md)
section 4. `scripts/_tn_backtest_c.py <tour> [first_year]` is builder C's temporary
driver for the backtest alone (3,000 tournament simulations, years to 2026).

### 5.4 `scripts/tn_hydrate.py`: the current year from the live site (CI)

```
python scripts/tn_hydrate.py                       # both tours, the current year
python scripts/tn_hydrate.py --tours wta --base https://example.org/data
```

Fetches, per tour, `https://pchattani.github.io/the-quant-ace/data/<T>/<year>/store.json`,
`<T>/registry.json` and `<T>/style.json`, and keeps the deployed copy when it is newer
than the checkout's (by `updated_at`; style by `_meta.updated_at`). The registry
travels with the store because the identities the hourly fetch resolved are in the
deployed registry, not the checkout's. A 404 is not an error.

### 5.5 `scripts/tn_bio.py`: dates of birth (added 15 October 2026)

```
python scripts/tn_bio.py --tour atp                # players without a date of birth, 5+ rated matches since 2005
python scripts/tn_bio.py --tour wta --dry-run      # count them
```

Neither tennis-data nor ESPN's scoreboards carry a date of birth, and the WTA API has one for only part of the WTA. The
script asks ESPN's core athlete API (`https://sports.core.api.espn.com/v2/sports/tennis/leagues/<T>/athletes/<espn id>`,
field `dateOfBirth`, an ISO timestamp whose date part is the date of birth; `sources/espn.py` `athlete_raw` /
`parse_athlete`) for every player with an ESPN id (the pid when numeric, else the registry's `espn`) and at least
`--min-matches` (5) rated matches since `--since` (2005) who has no date yet, through the paced client (0.5 s, `--budget`
2,500). It writes `docs/ace/data/<T>/bio.json` (section 6.5) every 100 players, so an interrupted run keeps its work; a
player ESPN answered without a date is asked again after `--recheck-days` (180). First run, 15 October 2026: 956 dates for
the 962 ATP players asked and 590 for 605 WTA players (1,567 calls, no failures, about 13 minutes). The build never calls
ESPN for this; `TourData.players` fills a missing `dob` from the file (the age terms of the Value section's breakout model
and the catalogue's `age`, which was empty for the ATP before).

---

## 6. Formats

### 6.1 Year store: `docs/ace/data/<tour>/<year>/store.json`

```
{"tour", "year", "updated_at",
 "players":  {pid: {"name","short","country","hand","dob","height","espn","wta","aliases"}},
 "events":   {event_id: {"tid","name","year","start","end","level","surface","indoor","draw_size","best_of",
                         "city","country","espn","wta","status","champion","draw"}},
 "matches":  {mid: MATCH},
 "rankings": {"date","rows": [[rank, pid, points]],"source": "espn"|"wta"},      latest official snapshot
 "meta":     {"sources": {..., "coverage", "identity"}, "fetched": {...}, "conflicts": [...] (last 200),
              "event_src": {event_id: {"_td","_espn","_wta","_tid_src","_lv_level",...}}}}
```

Private event keys (source ids, which source set a field) are moved into
`meta.event_src` on save and back onto the events on load. Events are saved sorted by
start, matches by (date, event, round depth, id). A MATCH:

```
{"id": "<event_id>-<round>-<pidA>-<pidB>" (pids sorted), "event", "date" (ISO, a time when ESPN/WTA gave one),
 "round": R128|R64|R32|R16|QF|SF|F|RR|Q1|Q2|Q3|BR, "best_of", "surface", "indoor", "level" ("q" for qualifying),
 "p1", "p2" (p1 = winner once finished), "winner", "status": upcoming|live|done|ret|wo|def,
 "sets": [[g1, g2, tb1|null, tb2|null]] (p1's view), "final_set_rule": adv|tb7|tb10,
 "rank1","rank2","pts1","pts2", "odds": {"ps","b365","avg","max","bfe": [o1, o2], "other": {...}} | null,
 "stats": {"p1": STATS, "p2": STATS, "by_set": [{"set","p1","p2"}]} | null,
 "live": {"set","games","points","server"} | null, "sources": ["espn","td","wta"], "duration_min",
 optional "final_set_tb_at": 12 (Wimbledon 2019-21), "seeds": [s1, s2], "entries": [e1, e2]}
STATS = {"aces","dfs","sv_pts","fs_in","fs_won","ss_won","sv_gms","bp_saved","bp_faced","rt_pts_won","bp_conv","bp_opps"}
```

Store sizes: ATP 1.5–2.2 MB a year; WTA 1.4–5.4 MB (larger from 2016 with
qualifying, WTA 125 and statistics).

### 6.2 DRAW

```
{"size", "slots": [[slot, pid|null, seed|null, entry ("Q","WC","LL","PR")|null]],
 "source": "wta" | "reconstructed", "complete": bool, "unmatched": n (wta)}
```

Round-1 bracket order; later rounds are implied. The build adds `filled_from_results`
when it fills empty slots (a seed with a bye the source left out) from later-round
matches (`analytics.complete_draw`).

### 6.3 Registry: `docs/ace/data/<tour>/registry.json`

`{"tour","updated_at","n_players","players": {pid: {"name","first","last","short",
"country","hand","dob","height","espn","wta","aliases",["espn_alt","wta_alt","_abbrev"]}},
"redirects": {old_pid: pid}}`. About 0.4–0.5 MB.

### 6.4 Style table: `docs/ace/data/<tour>/style.json`

```
{"_meta": {licence name/url, attribution, source, derived, tour, updated_at, files, points, unparsed_points,
           matches, matches_listed, dates, players, players_linked, identity, unlinked_examples, metrics_doc},
 pid: {"name","hand","linked","matches","points","points_won",
       "serve": {first_in, first_won, second_won, ace_rate, df_rate, unret_rate, snv_rate, won,
                 direction: {first_deuce|first_ad|second_deuce|second_ad: {wide, body, t, n}}},
       "return": {won, depth: {shallow, mid, deep, n}, fh_share},
       "rally": {mean_len, dist: {"1-3","4-6","7-9","10+"}, won: {...}},
       "shots": {winners_per_pt, ue_per_pt, fh/bh_winners_per_pt, fh/bh_ue_per_pt, induced_fe_per_pt,
                 fh_share, winner_ue_ratio},
       "net": {rate, won, n}, "aggression"}}
```

Rates are per point the player played unless named otherwise; aggression = (winners
+ unforced errors) / shots hit; `unret_rate` = aces + unreturnables + return errors per
service point. Consumers skip keys starting with `_`. About 1.1 MB (ATP), 0.8 MB (WTA).

### 6.5 Dates of birth: `docs/ace/data/<tour>/bio.json`

```
{"_meta": {"source", "updated_at", "players", "with_dob"},
 pid: {"dob": "YYYY-MM-DD" | null, "espn": "<id>", "checked": "YYYY-MM-DD"}}
```

About 60 KB (ATP), 40 KB (WTA). Redirected pids are followed when the file is read.

---

## 7. Merge rules: `store.py`

### 7.1 One match, many sources (`merge_record`, `_merge_match`)

A source record becomes a MATCH (`build_match`: oriented winner-first, deciding-set
rule from `canon.final_set_rule`, qualifying always tb7 and level `q`). It joins an
existing match with the same id, else one with the same event and the same pair of
players: the same round, or the only such match unless one is qualifying and the
other not (a lucky loser can meet the same player twice) or both are finals-week
rounds of a round-robin event. If none is found and the record is finished with sets,
a match of the same event and round with one shared player on the same side and the
same games is taken as the same match (ESPN profile mix-ups), with tennis-data's names
winning; the conflict is logged and a WTA-only/ESPN-only pair is merged (4.1).

Precedence when merging:

- **Status**: final beats live beats upcoming; a newer state takes the result
  fields wholesale (orientation from the new record).
- **Two finished versions**: the same games → tiebreak points filled from whichever
  has them; different games → keep a score consistent with the result
  (`valid_score`), tennis-data's when both are, and log a `sets` conflict.
- **tennis-data** owns ranks and ranking points, the final status (a retirement it
  records wins) and the odds.
- **ESPN / WTA** round labels replace tennis-data's inferred ones.
- **WTA** owns statistics and duration; seeds and entries are taken when missing.
- **Dates**: a timestamped date replaces a plain one only within a year of it.

`meta.conflicts` keeps the last 200 (`sets`, `winner`, `identity`).

### 7.2 Event roll-ups (`finalize_events`)

Each event's status and champion come from its matches (champion = the final's
winner; `done` once champion known, or when the end date has passed with nothing
live or upcoming). For a past year, scheduled-but-never-played matches that ESPN
still lists (cancellations) are dropped.

### 7.3 `fill_from_history`

This week's ESPN-only events have no surface, indoor flag or level until tennis-data
or the WTA describes them; they are copied from the same tid in the previous three
years.

### 7.4 Reconstructed draws (`reconstruct_draw`)

For a knockout without a WTA draw (every ATP event, every Slam), each played match
covers a block of first-round slots: its two players' blocks, each either the
earlier-round match the player came through or the player alone with empty slots
(a bye or a not-yet-known match). Blocks are built from the final when it has been
played, otherwise from the deepest matches; first-round pairings no later round
links are appended in date order. Seeds and entries are `null`; `complete` is true
once the final links the whole bracket. While an ATP event is in its first round,
paths beyond it are therefore approximate (the event page and the methodology say
so). Round-robin events get no draw here.

---

## 8. What is committed, what travels with the site, and the caches

| What | Where | In git | On the public site | In the Actions cache |
|---|---|---|---|---|
| Completed years' stores | `docs/ace/data/<T>/<year>/store.json` | yes (ATP 2000–2025, WTA 2007–2025) | yes | – |
| Current year's store | same | **no** | yes (hydrated back each run) | – |
| Registries, style tables | `docs/ace/data/<T>/{registry,style}.json` | yes (as of 1 Oct) | yes (hydrated back) | – |
| Dates of birth | `docs/ace/data/<T>/bio.json` (`tn_bio.py`) | yes (un-ignored with the others; commit by hand) | yes | – |
| Calibration | `docs/ace/data/<T>/calibration.json` | yes | yes | – |
| Fitted constants | `oddsmarkets/tennis/models/fitted/*.json` | yes | – | – |
| Payloads and manifests | everything else under `docs/ace/data/` | no | yes (restored with `--ignore-existing`) | – |
| Raw downloads | `data/tennis/{td,wta,charting}/` | no | no | no |
| Model caches | `data/tennis/cache/` (Elo, serve/return fits, validation, backtest) | no | no | yes (`ace-cache-<run_id>`) |

The `.gitignore` block: `docs/ace/data/**` ignored, then `*/`, `*/*/`,
`*/*/store.json`, `*/registry.json`, `*/style.json`, `*/calibration.json` and `*/bio.json`
un-ignored. Because the store pattern matches the current year too, commit stores by
explicit path.

CI uses the committed fits as follows: the Elo constants (`elo_params_<tour>.json`),
the serve/return constants (`serve_return_<tour>.json` `constants`) and the blend
(`predict_<tour>.json`) always; the frozen serve/return **model** in
`serve_return_<tour>.json` only when no fit can be made from the stores for a date
within 45 days of today (`TourData.sr_fit`), or when no stores exist at all
(`serve_return.for_tour`). With the committed stores a cold cache refits the current
checkpoint, and past checkpoints only within `ACE_SR_FIT_BUDGET` seconds per run (600 in
the workflow): beyond it a past checkpoint gets no serve/return model that run (never the
frozen one, which saw later matches) and the pages built with it are left unsigned, so
the cache warms over a few runs instead of the build timing out (a full cold refit is
about 50 ATP fits of ~20 s and 40 WTA fits of ~50 s).

The registries and style tables in git are the 1 October snapshot; the hourly job
updates the deployed copies. When committing a completed year, take the registry from
the live site (or hydrate first) so the committed registry matches the committed
stores.

---

## 9. Scheduling: `.github/workflows/update_ace.yml` ("Ace Hourly Update")

`cron: '27 * * * *'` plus `workflow_dispatch`; `concurrency: ace-build`
(not cancelled in progress); 55-minute job; `permissions: contents: read`.

| Step | Timeout | On failure |
|---|---|---|
| Checkout, Python 3.11, `pip install uv`, `uv sync` | – | job fails |
| Restore `data/tennis/cache` (key `ace-cache-<run_id>`, restore prefix `ace-cache-`) | – | cold caches |
| Clone the public repo with the deploy key; `rsync -a --ignore-existing /tmp/prev/data/ docs/ace/data/` | 10 min | continue (cold build) |
| `tn_hydrate.py` | 5 min | continue |
| `tn_fetch.py --tour atp --refresh-current --budget 300 --interval 0.5` | 15 min | continue |
| `tn_fetch.py --tour wta --refresh-current --budget 400 --interval 0.5` | 15 min | continue |
| `build_ace.py --match-page-years 2` | 30 min | job fails |
| Prune `docs/ace/data/<T>/matches/*.json` whose id year ≤ current year − 2 | – | job fails |
| Deploy: clone the public repo, `rsync -a --delete --exclude='.git' --exclude='raw/' --exclude='*.tmp' docs/ace/ /tmp/site/`, commit "Site update <UTC stamp>", push | – | job fails |

The restore step uses `--ignore-existing`, so the checkout's committed inputs win over
the deployed copies of the same files; the hydrate step then replaces the current
year's store, registry and style table with the deployed ones when they are newer.
Typical hourly calls: ESPN 6 day scoreboards and 1 ranking per tour, tennis-data 1
link page plus one conditional GET per tour, the WTA API a calendar page, the live
tournaments' matches and draws and the new finished matches' statistics.

---

## 10. The backfill

Run once per tour on the owner's machine, detached, on 1 October 2026:

```
python scripts/tn_fetch.py --tour atp --from 2000 --to 2026 --log logs/tn_backfill_atp.log
python scripts/tn_fetch.py --tour wta --from 2007 --to 2026 --budget 60000 --log logs/tn_backfill_wta.log
```

The ATP pass took seconds of network time (24 ESPN season scoreboards and 2
tennis-data calls; workbooks were already cached). The WTA pass made 20,635 WTA API
calls (60 failures; 3,368 s on the network; about 3 hours in all), almost all of them
per-match statistics. `logs/tn_after_backfill_wta.ps1` then waited for the backfill's
process, re-merged tennis-data over every WTA year (`--phases td --force-td`, grading
ESPN-only past events below tour level) and rebuilt the WTA style table against the
completed registry.

The backfill is resumable: completed phases are marked in each store's
`meta.fetched` (`espn_year`, `wta_calendar`, `wta_events`, `wta_stats`, `td`,
`td_last_modified`), so a stopped run (budget, crash) continues where it left off.

---

## 11. Failure modes

| Symptom | Cause | Effect |
|---|---|---|
| tennis-data `no download links found` | the link pages changed shape | the current year gets no new results or odds; ESPN still adds matches (without odds or ranks) |
| tennis-data answers a non-workbook | the prefix rotated mid-run, or an error page | the cached file is kept |
| `.xls needs xlrd` | `xlrd` missing | 2000–2012 skipped |
| ESPN 5xx / timeouts | ESPN | that day's scoreboard skipped; live states stale for an hour |
| WTA API empty for a live event | WTA | the event keeps its last state; ESPN still updates scores |
| `BudgetExhausted` in the log | the run's budget spent (WTA statistics after a busy week) | stops cleanly; the next run continues |
| a new `x:` player for a known name | a spelling no rule catches | a duplicate player; add the name to `overrides.json` |
| `sets` / `winner` conflicts in `meta.conflicts` | sources disagree | tennis-data's consistent score kept |
| the hydrate 404s | first deploy, or a new year | the checkout's store (or none) is used; CI fetches the current days only, so a new year starts from what the day scoreboards hold |

---

## 12. Known gaps and sharp edges

1. **No ATP statistics and no ATP draws** (sections 2.3, 2.7). ATP serve/return is
   inferred; ATP draws are reconstructed, without seeds.
2. **ESPN before 2007 is empty**, so 2000–2006 ATP matches have no tiebreak points
   and no full-name field for tennis-data names (782 `td_only` players).
3. **2009 has no Pinnacle on either tour**; 2026's Pinnacle column is thin, so the
   2026 "v Pinnacle" scores rest on 69 ATP and 98 WTA matches.
4. **The current year's store exists only on the deployed site.** If the public repo
   is lost, CI rebuilds the current year from six days of scoreboards; recover it with
   a local `tn_fetch.py --from <year> --to <year>` (full season scoreboard,
   tennis-data, WTA calendar).
5. **The committed registry and style tables age**: the deployed ones are newer.
   Commit them with each completed year (section 8).
6. **Points tables are the 2025 ones for every year** (`canon.POINTS`), and are
   hand-entered (`POINTS_VERIFY = True`), as are `KNOWN_LEVELS`, `DRAW96`,
   `WTA_PREMIER_1000*` and `final_set_rule`.
7. **WTA Slams have no statistics** (ITF events), so the WTA point layer and real
   metrics never cover them.
8. **`ESPN_FROM`** was 2004 although nothing before 2007 arrives; fixed on
   1 October 2026 (2007, in the code and the Methodology).
9. **The charting repository could follow the results repositories offline.** The
   style tables in git and on the site would survive; `tn_charting.py` would then
   fail its downloads and keep the cached CSVs if present.

---

## 13. Operator quick reference

```bash
# Current year, as CI does it (both tours)
python scripts/tn_hydrate.py
python scripts/tn_fetch.py --tour atp --refresh-current --budget 300
python scripts/tn_fetch.py --tour wta --refresh-current --budget 400

# One past year again (completed phases are skipped; --force-td re-merges tennis-data)
python scripts/tn_fetch.py --tour atp --from 2024 --to 2024 --force-td

# Coverage of the stores on disk
python scripts/tn_fetch.py --tour wta --report --from 2016 --to 2026

# Style tables
python scripts/tn_charting.py --tour atp
python scripts/tn_charting.py --tour wta --refresh

# Backfill progress (UTF-8 logs)
Get-Content logs\tn_backfill_wta.log -Tail 20
```
