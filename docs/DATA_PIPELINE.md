# Data pipeline: extraction and storage

This document covers how football data gets into this repository, where it is
stored and how it reaches the public site, **The Quant Footballer**
(`docs/site/`, published through GitHub Pages). It is written for an engineer who
will run and extend the pipeline, and for the repo owner. Every endpoint,
budget, default and path below was checked against the code as of 2026-09-29;
the squads fetcher, the past-results phase and the re-pinned competitions were
added on 2026-10-02. File references are relative to the repository root.

Contents

1. [Overview and data flow](#1-overview-and-data-flow)
2. [Sources](#2-sources)
3. [The Sofascore 403 challenge and the rules that follow from it](#3-the-sofascore-403-challenge)
4. [Competition registry](#4-competition-registry)
5. [Discovery](#5-discovery)
6. [Fetchers](#6-fetchers)
7. [Store format](#7-store-format)
8. [Scheduling: local task and CI](#8-scheduling)
9. [Failure modes and how each degrades](#9-failure-modes)
10. [Known gaps and sharp edges](#10-known-gaps-and-sharp-edges)
11. [Free alternative sources (not implemented)](#11-free-alternative-sources-not-implemented)
12. [Operator quick reference](#12-operator-quick-reference)

---

## 1. Overview and data flow

Almost all match data comes from **Sofascore's unofficial JSON API**. Sofascore
blocks datacenter IPs, so GitHub Actions cannot fetch from it. Fetching therefore
runs only on the owner's Windows machine, through an hourly scheduled task. That
task writes JSON "stores" into the repo and pushes them. An hourly GitHub Actions
workflow then builds the site payloads from those stores and deploys `docs/site/`
to the public site repository.

```
                        OWNER'S WINDOWS MACHINE (residential IP)
                        scheduled task "Sofascore Refresh (all)", hourly
                        scripts/refresh_sofascore_all.ps1
 ┌────────────────────┐
 │ Sofascore API      │  curl_cffi, impersonate="chrome"
 │ api.sofascore.com  │  failover: api.sofavpn.com
 └─────────┬──────────┘
           │
           ├─► scripts/fetch_sofascore_liga.py ──────► docs/liga/data/liga_store.json
           │     (reads liga/data/seasons.json)
           │
           ├─► scripts/discover_sofascore_leagues.py ─► oddsmarkets/football/competitions/
           │     --missing --limit 6                      league/data/seasons.json
           │
           ├─► scripts/fetch_sofascore_leagues.py ───► docs/site/data/<slug>/store.json
           │     --all --refresh-detail --budget 150      (12 leagues + 56 cups/national teams)
           │
           ├─► scripts/fetch_sofascore_squads.py ────► docs/site/data/squads/store.json
           │     --budget 20                              (current squads, departures)
           │
           └─► scripts/fetch_sofascore_history.py ───► docs/site/data/archive/store.json
                 --budget 60                              (past seasons, player careers)
                 (up to 20 of the 60) ──────────────► docs/site/data/past/store.json
                                                          (past seasons' results)

           git add <stores> + seasons.json ; one commit ; git push (current branch)
                                   │
                                   ▼
                        PRIVATE REPO (this one) on GitHub
                                   │
                                   ▼  .github/workflows/update_site.yml, hourly at :17
                        1. hydrate: for each store, keep the public copy if it is
                           more complete (match count, then lineup count) and its
                           season is one of seasons.json's; squads and past: the
                           newer copy
                        2. scripts/build_site_all.py
                             reads stores + seasons.json + model_params.json
                             + The Odds API (ODDS_API_KEY, optional)
                             + Polymarket and Kalshi (match and title markets, no key)
                             + committed crests docs/site/assets/crests/<team_id>.png
                           writes docs/site/data/**: competitions.json, hub.json,
                             search.json, season_index.json, nations.json, pool.json,
                             players_global.json, careers/, history/, and per
                             competition <slug>/{fixtures,table,probs,bracket,strength,
                             teams,players_live,player_leaders,shots,team_stats,
                             matches,meta,history,market_odds,club_matches}.json,
                             matches/<id>.json, players/<club>.json; then the
                             unified layer: people/<pid>.json, people_index.json,
                             clubs/<tid>.json, clubs_index.json,
                             <slug>/seasons.json, <slug>/s/<sid>/season.json
                        3. rsync docs/site/ → public site repo (SITE_REPO), commit, push
                                   │
                                   ▼
                        PUBLIC SITE REPO → GitHub Pages
                        (index.html + assets/ + data/, stores included as data)
```

The key design points:

- **Stores are the only committed fetched data.** Everything else under
  `docs/site/data/` is a build output that CI regenerates (see `.gitignore`).
- **One call budget per run** caps Sofascore detail calls. A circuit breaker
  stops a run at the first HTTP 403.
- **Every network failure degrades to last-good data.** A fetcher leaves a store
  untouched when nothing arrives, and the build marks competitions stale rather
  than failing.

---

## 2. Sources

### 2.1 Sofascore (primary): `oddsmarkets/football/sources/sofascore.py`

Transport: `get_json(path, timeout=20, quiet=False)` makes a `curl_cffi.requests.get`
with `impersonate="chrome"` (a browser TLS fingerprint) against
`https://{host}/api/v1{path}`. It tries each host in `HOSTS` in order:

| Constant | Value |
|---|---|
| `HOSTS` | `["api.sofascore.com", "api.sofavpn.com"]` |
| `PAGE_PAUSE_S` | `0.5` s between season-event pages |
| `DETAIL_CALLS` | `5` calls per match of detail |
| `DETAIL_PAUSE_S` | `0.25` s after each budgeted call |
| `STATUS_FINISHED` / `STATUS_LIVE` | `"finished"` / `"inprogress"` |

`get_json` never raises. It returns the parsed JSON on HTTP 200 and `None` when
every host fails. One logical call can therefore make **two** HTTP requests when
the first host fails.

A second route, `call(fn, **kwargs)`, wraps the `datafc` library with the source
keys `["sofascore", "sofavpn"]`. Only the legacy World Cup fetcher still uses
datafc. The Argentine fetcher dropped it because datafc's client fingerprint
started drawing 403s when the direct route did not.

#### Endpoints used

All paths are relative to `https://{host}/api/v1`.

| Function | Path | Used by | Budgeted? |
|---|---|---|---|
| `list_seasons(tid)` | `/unique-tournament/{tid}/seasons` | discovery, history | history only (charged by hand) |
| `season_events(tid, sid)` | `/unique-tournament/{tid}/season/{sid}/events/last/{page}` then `/events/next/{page}` | leagues/cups fetcher, Liga fetcher | no |
| `standings_blocks(tid, sid)` | `/unique-tournament/{tid}/season/{sid}/standings/total` | discovery, history | history only |
| `probe(tid, sid)` | `/unique-tournament/{tid}/season/{sid}/events/last/0` | every fetcher, before anything else | no |
| `search_tournament(q, hint, budget=None)` | `/search/all?q={q}&page=0` | discovery (`resolve_id`) | only if a budget is passed (discovery passes none) |
| `fetch_match_detail(...)`: lineups | `/event/{id}/lineups` | detail | yes |
| ↳ team statistics | `/event/{id}/statistics` | detail | yes |
| ↳ shot map | `/event/{id}/shotmap` | detail | yes |
| ↳ momentum | `/event/{id}/graph` | detail | yes |
| ↳ incidents | `/event/{id}/incidents` | detail | yes |
| `past_season_events(tid, sid, budget, start_page=0)` | `/unique-tournament/{tid}/season/{sid}/events/last/{page}` | history (past results) | yes, one call per page of 30 matches |
| `team_players(team_id, budget=None)` | `/team/{id}/players` | squads | yes |
| `player_details(pid)` | `/player/{pid}` | history, squads (departures) | yes |
| `player_seasons(pid)` | `/player/{pid}/statistics/seasons` | history | yes |
| `player_season_stats(pid, tid, sid)` | `/player/{pid}/unique-tournament/{tid}/season/{sid}/statistics/overall` | history | yes |
| `top_players(tid, sid)` | `/unique-tournament/{tid}/season/{sid}/top-players/overall` | history | yes |
| `search_player(name)` | `/search/all?q={name}&page=0` | history | yes |
| (crests, separate script) | `/team/{team_id}/image` on `api.sofascore.app`, then `api.sofascore.com` | `scripts/fetch_crests.py` | no |

`season_events` pages `last` from page 0 until `hasNextPage` is false, then does
the same for `next`. It stops early on the first page that fails and returns what
arrived. A 404 on `next/0` is normal for a finished season and is logged
quietly. Events are de-duplicated by id, because a live match can appear on both
the last page of `last` and the first page of `next`. Each season costs **at
least two calls** (`last/0` and `next/0`).

#### `CallBudget` and `BudgetExhausted`

```python
budget = sofascore.CallBudget(150)   # .limit, .used, .left
budget.take(n=1) -> bool             # False (and nothing taken) if it would exceed the limit
```

`fetch_match_detail` and `_budgeted` call `budget.take()` before each request.
When `take()` fails they raise `BudgetExhausted(path)`. A match that runs out
mid-way keeps whatever arrived. The fetchers only start a match when
`budget.left >= DETAIL_CALLS`, so in practice matches are not split. **Only
detail, archive and player calls are charged.** Fixture pages, probes, discovery
searches and standings are not charged (see §10).

`fetch_match_detail(store, gid, meta, canon, budget=None) -> bool` fetches in this
order: lineups, statistics, shotmap, graph, incidents. It returns `True` only if
the lineups arrived **and** contained at least one player with kept stats. If the
lineups are missing it returns `False` without making the other four calls. A
match without lineups counts as a failure. That rule exists because a broken
detail fetch once reported hundreds of "successes" and stored nothing.

#### `LAST_STATUS` and `is_blocked()`: the circuit breaker

`get_json` records the HTTP status of each attempt in the module-global
`LAST_STATUS`. On a transport exception it sets `None`. `is_blocked()` returns
`LAST_STATUS == 403`. Every fetcher checks it:

- after the initial `probe` (the run exits 1 if it is blocked),
- before each competition in phase one of the leagues fetcher,
- after every detail match, and in the archive loops before each item.

Because `LAST_STATUS` holds the status of the **last host tried**, a 403 from
`api.sofascore.com` followed by a transport error on `api.sofavpn.com` leaves
`LAST_STATUS = None`. The breaker does not trip in that case. The second guard,
`MAX_CONSECUTIVE_FAILURES = 3` (three matches in a row with no lineups), catches it.

#### `event_record`: one Sofascore event as a store record

```python
event_record(event, canon, season_id, canon2=None, round_slugs=None, international=False)
    -> (str(event_id), record) | None
```

- **Names.** Leagues canonicalise both sides with `canon(name)` (the league's
  registry). Club cups pass `canon2 = normalize_cup_name`, which canonicalises
  each club through the registry of its own country (`team.country.alpha3`).
  National-team competitions use their config's `registry`, which is
  `"international"`. The function returns `None` if the id or either name is
  missing.
- **Knockout round.** `playoff_round(slug, name, extra)` maps
  `roundInfo.slug` / `roundInfo.name` onto a short key through `PLAYOFF_SLUGS`
  (24 entries: `r16`, `qf`, `sf`, `po`, `wc`, `r1`, `csf`, `cf`, `final`) merged
  with the per-competition `round_slugs` from the config. Separators are
  normalised (`[\s_/]+` → `-`). It tries an exact match first, then the longest
  needle, matching whole hyphen-separated tokens only, so `round-12` is not
  `round-1`. `round_slugs` override the shared map. For example, domestic cups
  send `round-of-32` to `r32`, where the shared map sends it to the UEFA
  play-off `po`.
- **Group.** The group is parsed from the `tournament.name` label.
  `group ([a-z]?\d{1,2}|[a-z])` handles "Group A", "Group 1" and the Nations
  League's "Group A1". "League A, Group 2" becomes `A2`. Otherwise
  `(east|west|north|south|central) region` handles the AFC's regional leagues,
  producing `East` / `West`.
- **Stage.** Evaluated in this order:

  | Condition | `stage` |
  |---|---|
  | `international` and a knockout round was found | `playoff` |
  | `international` (anything else, including "qualifying" labels) | `league` |
  | label contains `qualif` without `knockout`, or `playoff round` without `knockout`/`mls` | `qualifying` |
  | `championship round`, `conference league playoffs`, `relegation round` (the Belgian split) | `split` (with `split_group` = `top` / `europe` / `relegation`) |
  | `relegation/promotion` or `europa playoffs` | `other` |
  | knockout round, `roundInfo.cupRoundType`, or label contains `playoff` / `play in` / `play-in` / `knockout` | `playoff` |
  | otherwise | `league` |

  The MLS playoffs have no `roundInfo` at all. The label ("MLS, Playoffs") is the
  only marker, which is why the label checks exist.
- **Round.** The knockout key if there is one, otherwise `roundInfo.round`,
  otherwise `roundInfo.name`.
- **Winners.** `winner` is set only for a drawn `playoff` match with
  `winnerCode` 1 or 2 (settled on penalties). `agg_winner` comes from
  `aggregatedWinnerCode` on the second leg of a two-legged tie.
- **Shoot-outs.** Sofascore's display score excludes a penalty shoot-out, so
  since 2 October 2026 the shoot-out is kept beside it as `pens: [home, away]`.
  Result strings on the site read "D 2-2, lost 2-4 pens".
- **Other fields.** `home_id`/`away_id` (used for crests), `home_country`/
  `away_country` (alpha-3, which let cup entrants find their league), and `leg`,
  which is always `null` in the current code (the expression is
  `cupRoundType and None`).

The fetcher applies two more rules afterwards (§6.1): a knockout cup never
records `league` play, and a partial response never erases a stored date.

#### `search_tournament(query, country_hint=None, budget=None)`

This function calls `/search/all` and keeps results of type `uniqueTournament`
whose folded name contains the query or is contained in it. Folding means ASCII,
lower case, with non-alphanumerics turned into spaces. Each hit is scored:

- +2 when the folded `country_hint` is in the category name,
- +1 for an exact name match,
- −5 for `women`, `u17`, `u19`, `u20`, `u21` or `u23`, and (since 2 October
  2026) `conifa`, `futsal`, `beach`, `youth` or `olympic`.

It returns `{id, name, category}` for the best hit when its score is ≥ 0,
otherwise `None`. **Check its log line on every new competition.** A wrong
tournament, such as a "Serie C" or a women's edition, is fixed by pinning
`sofascore_id` in the config. The five World Cup qualifiers had all resolved to
the Conifa World Cup qualifiers (tournament 28716) before the penalty was added;
they are now pinned (§4.2).

#### `KEEP_STATS`

`KEEP_STATS` lists the 72 per-player match statistics kept from the roughly 70
that lineups expose. They cover minutes, scoring and creation, passing and
carrying, defending and duels, goalkeeping, physical output, and `rating`.
Sofascore's composite "value" indices are dropped. Every competition uses the
same list, so readers and the front-end share one shape. The legacy World Cup
fetcher has its own 26-key list.

### 2.2 Name registries and canonicalisation: `oddsmarkets/football/sources/teams.py`

Every provider spells clubs differently, and a join on mismatched names fails
silently: the team simply drops out. The registries are flat alias → canonical
dicts, kept in separate namespaces so that club and national-team aliases never
collide.

| Registry key (`REGISTRIES`) | Used for |
|---|---|
| `international` | national teams (and cups with `family="international"`) |
| `liga_argentina` | Liga Profesional (and Copa Argentina / Supercopa Argentina entrants via country) |
| `premier_league`, `la_liga`, `serie_a`, `bundesliga`, `ligue_1`, `eredivisie`, `primeira_liga`, `brasileirao`, `mls`, `saudi_pro_league`, `liga_mx`, `belgian_pro_league` | one per league; `LeagueConfig.registry` defaults to the slug with `-`→`_` |

- `normalize_team_name(name, registry="international")` tries an exact alias
  match first, then an accent-, punctuation- and case-folded key (`&` → "and").
  Canonical names always resolve to themselves. Unknown names come back
  **unchanged**, never raising. Fold tables are cached by registry *name*, never
  by dict identity.
- `normalize_cup_name(name, country_alpha3)` looks the country up in
  `COUNTRY_REGISTRY` and canonicalises through that league's registry. Clubs
  from unlisted countries keep Sofascore's spelling. The table includes both
  ISO and FIFA codes: `ENG`, `ESP`, `ITA`, `GER`/`DEU`, `FRA`, `NED`/`NLD`,
  `POR`/`PRT`, `BRA`, `USA`/`CAN` (MLS), `SAU`/`KSA`, `ARG`, `MEX`, `BEL`. The
  effect is that "Liverpool FC" in the Champions League is the same "Liverpool"
  as in the Premier League store.
- `cup/config.py` has a parallel `COUNTRY_LEAGUE` table (alpha-3 → league
  slug). The pooled model uses it to put a cup entrant into its league.

**To add a club spelling**, add an alias to the right registry and let the next
fixture refresh rename it. Renames propagate into stored detail (§9).

### 2.3 Prediction markets: `oddsmarkets/football/sources/prediction_markets.py`

- Polymarket's Gamma API (`https://gamma-api.polymarket.com`) and Kalshi
  (`https://api.elections.kalshi.com/trade-api/v2`), both public and read
  without a key, through `requests`.
- Used at **build time** by `fetch_markets_safe` in `scripts/build_site_all.py`
  for the Market tabs: match lines from each fixture's win/draw/win markets and
  title markets from Kalshi's champion series and Polymarket's champion event.
  `MARKETS` maps each competition to its series. `HANDOFF.md` Task 2 has the
  acceptance rules.
- Any failure leaves `market_odds.json` at the previous payload. This runs fine
  from CI. `scripts/build_site_all.py --no-market` skips it.

### 2.4 The Odds API (bookmaker h2h odds)

- The client is `oddsmarkets/sports/world_cup/trading/the_odds_api.py`
  (`TheOddsAPIFetcher`, base `https://api.the-odds-api.com/v4`). The call is
  `GET /sports/{sport}/odds?regions=eu,uk&markets=h2h&oddsFormat=decimal`, and
  only bookmakers in `CANADIAN_BOOKMAKERS` are kept.
- It is called at **build time** by `fetch_markets_safe` in
  `scripts/build_site_all.py` (per league/cup with an `odds_api_sport` key) and
  in `scripts/build_site_liga.py` (`ODDS_API_SPORT =
  "soccer_argentina_primera_division"` in `liga/config.py`).
- It needs `ODDS_API_KEY`, passed to the build step from Actions secrets in
  `update_site.yml`. If the key is missing it silently skips. On failure,
  `market_odds.json` keeps the previous payload with `ok: false`.
- Note: `scripts/fetch_market_odds.py` is **not** The Odds API. It is the
  legacy World Cup script that pulls Polymarket (events `30615`, `414457`,
  `413862`) and Kalshi (`api.elections.kalshi.com/trade-api/v2`, series
  `KXMENWORLDCUP`, `KXWCROUND`, `KXWCGOALLEADER`) for `scripts/build_site_wc.py`.

### 2.5 football-data.org (legacy, World Cup only)

- The client is `oddsmarkets/sports/world_cup/data/live_data.py`:
  `https://api.football-data.org/v4/competitions/WC/{matches,standings,scorers}?season=2026`,
  free tier 10 requests/minute, with API-Football
  (`v3.football.api-sports.io`) as fallback.
- It is used only by `scripts/build_site_wc.py` with `FD_API_KEY`. The World
  Cup is over and `update_wc.yml` is manual-only.
- The current hub does not use football-data.org.

### 2.6 Crests: `scripts/fetch_crests.py`

- It collects `home_id`/`away_id` from every store in `LEAGUES + CUPS` plus
  `docs/liga/data/liga_store.json`, current season only.
- It downloads `/api/v1/team/{id}/image` from `api.sofascore.app`, falling back
  to `api.sofascore.com` (curl_cffi, `impersonate="chrome"`), into
  `docs/site/assets/crests/{team_id}.png`, pausing `PAUSE_S = 0.3` s between
  downloads.
- Existing files are skipped unless `--refresh` is passed. Crests are committed
  because a plain client gets a 403, so hot-linking is impossible.
- It is **run by hand**, not by the scheduled task, and it has **no call budget
  and no 403 breaker**. Run it only when the IP is healthy and few crests are
  missing. There are 516 crests at the time of writing.
- The build's `crest_path()` emits `assets/crests/{id}.png` only if the file
  exists.

---

## 3. The Sofascore 403 challenge

What is known, from operating history (`HANDOFF.md`, fetcher docstrings):

- **It is IP-wide.** Once challenged, Sofascore answers HTTP 403 to every
  endpoint from that IP. The probe, fixtures, detail and search all fail.
- **Bursts trigger it.** It happened once after about 3,000 calls in one
  sitting. It happened again on 2026-09-29, from about 03:30 UTC, after fewer
  than 1,000 calls in an hour: the new cups' fetch and the first budgeted hourly
  run landed in the same hour.
- **It lasts on the order of 13 hours** and has cleared on its own. If it has
  not cleared after a day, a new IP (router restart) has also cleared it.
- **Datacenter IPs are blocked outright.** GitHub Actions runners cannot reach
  Sofascore at all, which is why fetching runs only on the owner's Windows
  machine and CI only builds.
- **Every call made while challenged is wasted** and may prolong the block.

### Rules that follow

1. **Never run a manual backfill on top of the hourly task.** Either disable the
   scheduled task first or space backfills hours apart. The task and a backfill
   in the same hour is exactly how the 2026-09-29 challenge started.
2. **Budget every run.** The hourly defaults are 100 (Liga) + 150 (leagues/cups)
   + 60 (archive, of which up to 20 for past results) + 20 (squads) budgeted
   calls, plus about 25 for discovery and the unbudgeted fixture pages.
   Per-script budgets:

   | Script | Budget default | `--backfill` | Hourly task passes | Unit |
   |---|---|---|---|---|
   | `fetch_sofascore_leagues.py` | `DEFAULT_BUDGET = 150` | `BACKFILL_BUDGET = 1000` | `--budget 150` | detail calls (5/match → 30 matches) |
   | `fetch_sofascore_liga.py` | `DEFAULT_BUDGET = 100` | `BACKFILL_BUDGET = 1000` | `--budget 100` | detail calls (5/match → 20 matches) |
   | `fetch_sofascore_history.py` | `DEFAULT_BUDGET = 60`; `--past-budget` 20 of it | n/a | `--budget 60` | any archive call; past results one call per page |
   | `fetch_sofascore_squads.py` | `DEFAULT_BUDGET = 20` | n/a | `--budget 20` | one call per squad; up to 8 profile lookups |
   | `discover_sofascore_leagues.py` | none | n/a | `--missing --limit 6` | 6 competitions (~2–4 calls each) |
   | `fetch_crests.py` | none | n/a | not run | one call per missing crest |
   | `fetch_sofascore.py` (legacy WC) | `max_new=40` matches | `1000` | not run | datafc calls |

3. **Stop at the first 403.** Every fetcher probes first and exits 1 on a 403.
   Mid-run, `is_blocked()` or three consecutive detail failures
   (`MAX_CONSECUTIVE_FAILURES = 3`) stop the run.
4. **Pace.** 0.5 s between event pages, 0.25 s after each detail call, and 1.0 s
   between matches (`DETAIL_PAUSE_S = 1.0` in the fetchers) or between archive
   items (`PAUSE_S = 1.0`).
5. **Check before a backfill.** Use
   `python scripts/fetch_sofascore_leagues.py --probe`, which costs one call. It
   exits 0 if reachable and 1 otherwise.

---

## 4. Competition registry

There are 69 competitions: 12 plain leagues (`LEAGUES`), 56 cups and
national-team competitions (`CUPS`), and the Argentine Liga Profesional, which
has its own package.

### 4.1 `oddsmarkets/football/competitions/league/config.py`: `LeagueConfig`

These fields matter to the pipeline:

- `slug`, `sofascore_id`, and `alt_sofascore_id` (a second unique-tournament;
  Liga MX's Clausura beside its Apertura).
- `registry` (defaults to the slug with underscores) and `odds_api_sport`.
- `conferences` (MLS). Discovery fills membership from standings blocks.
- `n_teams`, used to sanity-check discovery.

The rest (bands, playoff, split, tiebreak, simulation) is model configuration.
Every league has a **fixed** Sofascore id.

| League | Slug | Country | Sofascore id | Registry |
|---|---|---|---|---|
| Premier League | `premier-league` | England | 17 | `premier_league` |
| LaLiga | `la-liga` | Spain | 8 | `la_liga` |
| Serie A | `serie-a` | Italy | 23 | `serie_a` |
| Bundesliga | `bundesliga` | Germany | 35 | `bundesliga` |
| Ligue 1 | `ligue-1` | France | 34 | `ligue_1` |
| Eredivisie | `eredivisie` | Netherlands | 37 | `eredivisie` |
| Liga Portugal | `primeira-liga` | Portugal | 238 | `primeira_liga` |
| Brasileirão Série A | `brasileirao` | Brazil | 325 | `brasileirao` |
| Major League Soccer | `mls` | USA / Canada | 242 | `mls` |
| Saudi Pro League | `saudi-pro-league` | Saudi Arabia | 955 | `saudi_pro_league` |
| Liga MX | `liga-mx` | Mexico | 11621 (+ alt 11620) | `liga_mx` |
| Belgian Pro League | `belgian-pro-league` | Belgium | 38 | `belgian_pro_league` |

### 4.2 `oddsmarkets/football/competitions/cup/config.py`: `CupConfig`

These fields matter to the pipeline:

| Field | Meaning |
|---|---|
| `kind` | `swiss`, `groups`, `regional_swiss`, `knockout`, `fixed`, or `international`. For `knockout`, a fixture the event parser calls `league` becomes `playoff` if its round is in the bracket's `rounds`, otherwise `qualifying`. |
| `family` | `cup` (continental/world), `domestic` (national cup), `super` (super cup) or `international` (national teams). Labels come from `CUP_FAMILIES`. `international` switches `registry` to `"international"` and turns on the international stage rules in `event_record`. |
| `sofascore_id` | Fixed id, or `0` to resolve by search. |
| `search` + `country_hint` | Discovery searches `search` and prefers the unique tournament whose category matches `country_hint`. |
| `detail_scope` | `"all"` (default) or `"followed"`. With `"followed"`, per-match detail is fetched only when a side is a club of a followed league (see `followed_clubs`, §6.1). Every `_domestic(...)` cup uses `"followed"`: all national cups, all super cups, **and Leagues Cup**. |
| `round_slugs` | Per-competition overrides of `PLAYOFF_SLUGS`. Domestic cups use `_DOMESTIC_SLUGS` (`round-of-64`/`1-32`→`r64`, `round-of-32`/`1-16`→`r32`, `1st-round`…`6th-round` and `first-round`…`sixth-round`→`r1`…`r6`). National teams use `_INTL_SLUGS` (`round-of-32`→`r32`, `round-of-64`→`r64`, the third-place variants→`3rd`). |
| `neutral_venues` | Every match is at a neutral venue. This is a model input, applied at build time; it is not stored per match (§7). |
| `friendly` | Friendlies count for half in the international fit. |
| `odds_api_sport` | The Odds API key, when one exists (UCL, UEL, Libertadores). |

All cups and national-team competitions, by family. "Fixed" ids are in the
config. "Search" ids are resolved by discovery and stored in `seasons.json`.

**Continental and world (`family="cup"`)**

| Competition | Slug | Kind | Sofascore id |
|---|---|---|---|
| UEFA Champions League | `champions-league` | swiss | fixed 7 |
| UEFA Europa League | `europa-league` | swiss | fixed 679 |
| UEFA Conference League | `conference-league` | swiss | fixed 17015 |
| CONMEBOL Libertadores | `libertadores` | groups | fixed 384 |
| CONMEBOL Sudamericana | `sudamericana` | groups | fixed 480 |
| AFC Champions League Elite | `afc-champions-league` | regional_swiss | fixed 463 |
| CAF Champions League | `caf-champions-league` | groups | fixed 1054 |
| CONCACAF Champions Cup | `concacaf-champions-cup` | knockout | fixed 498 |
| Leagues Cup | `leagues-cup` | knockout | search "Leagues Cup" / hint "USA" (detail: followed) |
| FIFA Club World Cup | `club-world-cup` | groups | fixed 357 (neutral venues) |
| FIFA Intercontinental Cup | `intercontinental-cup` | fixed | fixed 23674 |

**National cups (`family="domestic"`; all knockout, detail: followed, domestic round slugs)**

| Competition | Slug | Sofascore id |
|---|---|---|
| FA Cup | `fa-cup` | search "FA Cup" / England |
| EFL Cup | `efl-cup` | search "EFL Cup" / England |
| Copa del Rey | `copa-del-rey` | search "Copa del Rey" / Spain |
| Coppa Italia | `coppa-italia` | search "Coppa Italia" / Italy |
| DFB-Pokal | `dfb-pokal` | search "DFB Pokal" / Germany |
| Coupe de France | `coupe-de-france` | search "Coupe de France" / France |
| KNVB Beker | `knvb-beker` | search "KNVB Beker" / Netherlands |
| Taça de Portugal | `taca-de-portugal` | search "Taca de Portugal" / Portugal |
| Taça da Liga | `taca-da-liga` | search "Taca da Liga" / Portugal |
| Belgian Cup | `belgian-cup` | search "Belgian Cup" / Belgium |
| Copa do Brasil | `copa-do-brasil` | search "Copa do Brasil" / Brazil |
| Copa Argentina | `copa-argentina` | search "Copa Argentina" / Argentina |
| Saudi King's Cup | `kings-cup` | search "King Cup" / Saudi Arabia |
| U.S. Open Cup | `us-open-cup` | search "US Open Cup" / USA |

**Super cups (`family="super"`; all knockout, detail: followed, domestic round slugs)**

| Competition | Slug | Sofascore id |
|---|---|---|
| UEFA Super Cup | `uefa-super-cup` | fixed 465 |
| CONMEBOL Recopa | `recopa-sudamericana` | search "Recopa Sudamericana" / South America |
| Campeones Cup | `campeones-cup` | search "Campeones Cup" / USA |
| FA Community Shield | `community-shield` | search "Community Shield" / England |
| Supercopa de España | `supercopa-espana` | search "Supercopa" / Spain |
| Supercoppa Italiana | `supercoppa-italiana` | search "Supercoppa Italiana" / Italy |
| DFL-Supercup | `dfl-supercup` | search "DFL-Supercup" / Germany |
| Trophée des Champions | `trophee-des-champions` | search "Trophee des Champions" / France |
| Johan Cruijff Schaal | `johan-cruijff-schaal` | search "Johan Cruijff Schaal" / Netherlands |
| Supertaça Cândido de Oliveira | `supertaca-portugal` | search "Supertaca" / Portugal |
| Belgian Super Cup | `belgian-super-cup` | search "Belgian Super Cup" / Belgium |
| Supercopa do Brasil | `supercopa-do-brasil` | search "Supercopa do Brasil" / Brazil |
| Supercopa Argentina | `supercopa-argentina` | search "Supercopa Argentina" / Argentina |
| Saudi Super Cup | `saudi-super-cup` | search "Saudi Super Cup" / Saudi Arabia |
| Campeón de Campeones | `campeon-de-campeones` | search "Campeon de Campeones" / Mexico |

**National teams (`family="international"`, `kind="international"`; not simulated, full detail, international round slugs)**

| Competition | Slug | Sofascore id | Notes |
|---|---|---|---|
| FIFA World Cup | `world-cup` | fixed 16 | neutral venues |
| UEFA European Championship | `euro` | fixed 1 | neutral venues |
| CONMEBOL Copa América | `copa-america` | fixed 133 | neutral venues |
| UEFA Nations League | `nations-league` | search "UEFA Nations League" / Europe | |
| European Championship Qualification | `euro-qualifiers` | search "European Championship Qualification" / Europe | |
| World Cup Qualification, UEFA | `wc-qual-uefa` | fixed 11 | pinned 2 Oct 2026 (search had found Conifa, 28716) |
| World Cup Qualification, CONMEBOL | `wc-qual-conmebol` | fixed 295 | pinned 2 Oct 2026 |
| World Cup Qualification, CONCACAF | `wc-qual-concacaf` | fixed 14 | pinned 2 Oct 2026 |
| World Cup Qualification, CAF | `wc-qual-caf` | fixed 13 | pinned 2 Oct 2026 |
| World Cup Qualification, AFC | `wc-qual-afc` | fixed 308 | pinned 2 Oct 2026 |
| Africa Cup of Nations | `afcon` | fixed 270 | neutral venues |
| Africa Cup of Nations Qualification | `afcon-qualifiers` | search "Africa Cup of Nations Qualification" / Africa | |
| AFC Asian Cup | `asian-cup` | fixed 246 | neutral venues; was 247 (Bulgaria's Parva Liga) until 2 Oct 2026 |
| CONCACAF Gold Cup | `gold-cup` | fixed 140 | neutral venues |
| CONCACAF Nations League | `concacaf-nations-league` | search "CONCACAF Nations League" / North & Central America | |
| International Friendlies | `friendlies` | search "Int. Friendly Games" / World | `friendly=True` |

**State on 2026-09-29.** `seasons.json` (discovered `2026-09-29T02:46:08Z`)
holds 21 entries: the 12 leagues plus the 9 original fixed-id cups (UCL, UEL,
UECL, Libertadores, Sudamericana, AFC, CAF, CONCACAF Champions Cup,
Intercontinental). The other 47 registry entries are not yet discovered because
the challenge started first. The World Cup has a seeded store (§6.5) but no
`seasons.json` entry.

**State on 2026-10-02.** All 69 are discovered. The five World Cup qualifiers
and the Asian Cup were re-pinned (verified against Sofascore that day): each
qualifier has its 2026-cycle edition as the live season, finished, so it shows
as its last edition; the Asian Cup has the 2027 edition live and 2023 as the
previous one. Their stores and archive seasons were emptied to refill. Several
competitions' newest edition on Sofascore is a finished one because the next is
not listed yet: Euro 2024, Copa América 2024, Euro qualifiers 2024, Gold Cup
2025, AFCON 2025, Coupe de France 25/26, Supercoppa Italiana 2025 and Saudi
Super Cup 2025. These show as `status: last_edition` in the unified payloads.

### 4.3 `oddsmarkets/football/competitions/liga/config.py`: Argentina

- `SOFASCORE_TOURNAMENT_ID = 155`. `SOFASCORE_COPA_LIGA_TOURNAMENT_ID = 13475`
  is kept only so it is not confused with the league.
- `ZONES = ("A", "B")`, `TORNEOS = ("apertura", "clausura")`, and
  `ODDS_API_SPORT = "soccer_argentina_primera_division"`.
- Season ids and zone membership come from
  `oddsmarkets/football/competitions/liga/data/seasons.json`, written by
  `scripts/discover_sofascore_liga.py` (§5.2). Since 2026 one season id (87913,
  "Primera LPF 2026") serves both torneos.

---

## 5. Discovery

Discovery turns the registry into concrete Sofascore season ids. Its output is
committed static configuration, because CI cannot regenerate it.

### 5.1 `scripts/discover_sofascore_leagues.py`

Output: `oddsmarkets/football/competitions/league/data/seasons.json`

```json
{
  "discovered_at": "2026-09-29T02:46:08Z",
  "leagues": {
    "<slug>": {
      "tournament_id": 17,
      "seasons": [{"season_id": 96668, "name": "Premier League 26/27", "year": "26/27", "tournament_id": 17}, ...],
      "teams": ["Arsenal", ...],
      "conferences": {"Eastern": [...], "Western": [...]},
      "previous_rank": {"Liverpool": 1, ...},
      "bands_seen": ["Champions League", ...],
      "family": "cup"
    }
  }
}
```

`bands_seen` appears for leagues only and `family` for cups only. `seasons[0]`
is the season being simulated. The ones after it are training history. The 21
entries in the committed file predate two fields the code now writes: their
season records have no per-season `tournament_id` (the fetcher falls back to
`cfg.sofascore_id`), and the cup entries have no `family`. A rediscovery adds
both.

| Function / constant | Behaviour |
|---|---|
| `KEEP_SEASONS = 2` | Newest season plus one of history. |
| `resolve_id(cfg)` | `cfg.sofascore_id` if non-zero. Otherwise `search_tournament(cfg.search, cfg.country_hint)`; logs the resolved id, name and category, or an error and `None`. |
| `list_seasons` | `/unique-tournament/{tid}/seasons`, newest first. |
| `discover_league(cfg)` | Seasons, then standings of the current season (overall block → `teams`, conference blocks → `conferences`, `promotion` texts → `bands_seen`), then standings of the previous season → `previous_rank` (seeds Elo). For Liga MX with `alt_sofascore_id`, the current season is the newer of the two tournaments' newest seasons. Team names are canonicalised through the league registry. |
| `discover_cup(cfg)` | Seasons. For `fixed`, `knockout` and `international` kinds it stops there (no standings call). `groups` reads group blocks into `conferences` keyed by the last letter of the block name. Other kinds take the largest block as `teams`. Cup team names stay **raw** Sofascore spellings. |

Flags:

| Flag | Effect |
|---|---|
| (none) | Discover every competition and **rewrite the file from scratch** (existing entries are not merged in). |
| `--league SLUG` (repeatable) | Only these; merges into the existing file. |
| `--missing` | Only slugs not already in `seasons.json`; merges. |
| `--limit N` | Stop after N competitions (so discovery spreads across runs); merges. |
| `--verify` | Print the JSON, do not write. |

The script stops before the next competition when `is_blocked()`. It exits 1 if
every requested competition failed, or with `--verify` if any failed. Without
`--verify` it writes whatever succeeded and exits 1 if anything failed. That is
why the hourly task logs "Discovery incomplete (continuing)" and carries on.

Cost per competition: fixed-id knockout, fixed or international competitions
take 1 call (seasons). Search-resolved ones add 1 search. League-phase cups add
1 standings call. Leagues take 3 (seasons + two standings), and Liga MX takes 4.
These calls are **not** charged to any budget.

### 5.2 `scripts/discover_sofascore_liga.py`

Output: `oddsmarkets/football/competitions/liga/data/seasons.json` with
`tournament_id`, `discovered_at`, `seasons` (per year:
`{year, apertura: <sid>, clausura: <sid>, names: {...}}`, newest first) and
`zones[year][torneo][zone] = [teams]`.

- The script has its own `_get` with the same host failover, but it does **not**
  update `LAST_STATUS`, so it has no 403 breaker.
- Season names containing "Apertura" or "Clausura" classify directly. The newest
  `_PROBE_NEWEST = 3` unnamed seasons are probed through standings, because from
  2026 one season id serves both torneos and only the standings block labels
  ("…, Clausura, Group A") say so.
- Zones are read for the newest year only. Aggregate blocks ("Anual",
  "Promedios") are skipped.
- Flags: `--verify` (print only), `--tournament-id` (default 155), and
  `--years Y …` (restrict).
- It runs **by hand at a season rollover**, not from the scheduled task.

---

## 6. Fetchers

### 6.1 `scripts/fetch_sofascore_leagues.py`: leagues, cups, national teams

One process serves every entry in `COMPETITIONS = {**LEAGUES, **CUPS}`. The
season-events endpoint is format-agnostic: MLS has no rounds at all, and the
same code handles it. Stores are written to `docs/site/data/<slug>/store.json`.

**Startup**

1. Load `seasons.json`. If it is missing the script exits 1 with a message to
   run discovery.
2. `--probe`: probe the first entry and exit 0/1.
3. Build `CallBudget(--budget, or 1000 with --backfill, or 150)`.
4. Probe the first requested competition that has a `seasons.json` entry. On a
   403, exit 1 with "nothing fetched this run". On any other failure, warn and
   carry on.

**Phase one: fixtures for every competition** (unbudgeted)

For each slug:

- Stop (count a failure) if `is_blocked()`, if the slug is unknown, or if it has
  no `seasons.json` entry.
- Load the store with `liga.store.load_store`, which never raises. If
  `meta.synthetic` is set, discard the store and start from `new_store()`.
- **Dormancy.** Unless `--refresh-dormant` is passed, `is_dormant(store)` skips
  the fixture refresh entirely. A store is dormant when it has matches, a
  parseable `meta.fixtures_refreshed_at` less than
  `DORMANT_REFRESH_HOURS = 24` hours old, no live match, and no match dated
  within `DORMANT_DAYS = 7` days either side of today. (Caveat in §10.)
- `refresh_fixtures(store, cfg, entry)`: for every season in
  `entry["seasons"]` (tournament id from the season, falling back to the
  config), call `season_events` and then `event_record` for each event.
  - Club cups pass `canon2=normalize_cup_name`. National teams pass
    `international=True`. Every competition passes its `round_slugs`.
  - A **knockout cup never records league play.** A `league` stage becomes
    `playoff` if the round is in `cfg.rounds`, otherwise `qualifying`.
  - A missing `date` keeps the previously stored date.
  - **Renames propagate.** If `home`/`away` differ from the stored record, the
    old name is rewritten to the new one in that match's `lineups[*].t`,
    `shots[*].team` and `incidents[*].team`.
  - A season returning no events is skipped with "keeping stored fixtures". If
    no season returned anything, `ok=False` and the store is left untouched.
  - On success it sets `store["conferences"]` from the seasons entry and
    `meta = {league, season_id (seasons[0]), season_name,
    fixtures_refreshed_at}`, merged over the existing meta.
- `detail_queue(store, refresh, followed)` selects matches that are
  `status == "finished"`, in `meta.season_id` (current season only), and not
  `stage` `qualifying` or `other`. For `detail_scope="followed"` competitions, a
  side must be in `followed_clubs()`. The queue is: matches with no lineups
  (newest first), then, with `--refresh-detail`, matches with lineups but no
  `team_stats` entry, i.e. old thin format (newest first).
- `followed_clubs(seasons)` is the union of every league's `teams` in
  `seasons.json` and every home/away name in the current season of each league
  store.

**Phase two: detail, round-robin under one budget**

- While any competition has a queue and `budget.left >= 5`: take one match from
  each active competition in turn and call `fetch_match_detail`.
- On `BudgetExhausted`, stop.
- Stop all detail on `is_blocked()` or after `MAX_CONSECUTIVE_FAILURES = 3`
  consecutive failed matches across competitions.
- Sleep `DETAIL_PAUSE_S = 1.0` s between matches.
- The log line `detail calls used: X of Y` reports the spend.

**Phase three: save only what changed**

- `store_signature(store)` (in `league/store.py`) is the tuple: match count;
  finished `(gid, hs, as, winner)`; every `(gid, date, is_finished)`; lineup
  count; team_stats count; `meta.season_id`.
- If the signature is unchanged and the file exists, the store is **not
  rewritten**, unless `--force` is passed. A live score ticking over does not
  produce a commit.
- `save_store` stamps `meta.updated_at` and writes compact UTF-8 JSON
  (`ensure_ascii=False`).
- Exit code is 0 if at least one competition succeeded (`failures < len(slugs)`),
  else 1.

Flags:

| Flag | Default | Effect |
|---|---|---|
| `--all` | off | Every competition in the registry (also the behaviour when no `--league` is given). |
| `--league SLUG` | — | Repeatable; restrict to these slugs. |
| `--budget N` | 150 | Detail calls this run may make (5 per match). |
| `--backfill` | off | Default budget becomes 1000 (ignored if `--budget` is given). |
| `--refresh-detail` | off | Also queue old thin-format matches (lineups but no `team_stats`) behind the missing ones. |
| `--refresh-dormant` | off | Refetch fixtures of dormant competitions too. |
| `--force` | off | Rewrite stores even when the signature is unchanged. |
| `--probe` | off | Connectivity check only (one call). |

### 6.2 `scripts/fetch_sofascore_liga.py`: Argentina

- **Store:** `docs/liga/data/liga_store.json`.
- **Seasons:** `oddsmarkets/football/competitions/liga/data/seasons.json`. A
  missing file means exit 1 with a message.
- **Budget:** `DEFAULT_BUDGET = 100`, `BACKFILL_BUDGET = 1000`,
  `DETAIL_PAUSE_S = 1.0`, `MAX_CONSECUTIVE_FAILURES = 3`.
  `max_new = budget.limit // 5`, so 20 matches by default.
- **Flow.**
  1. Probe; exit 1 on a 403.
  2. Load the store. A `synthetic` store is discarded and replaced by
     `EMPTY_STORE`.
  3. Write `zones` for the current year from `seasons.json`.
  4. Fetch each distinct season id once (`season_events(155, sid)`). Each
     match's torneo is read from its own `tournament.name` label
     (`torneo_of_label`).
  5. Rewrite every match record.
  6. Queue finished matches without lineups, then (with `--refresh-detail`)
     matches without `team_stats`, newest first, capped at `max_new`.
  7. Fetch detail through the shared `sofascore.fetch_match_detail`.
- **Differences from the league fetcher.**
  - It keeps its own `PLAYOFF_SLUGS` and `playoff_round`: substring match, only
    `r16`/`qf`/`sf`/`final`.
  - It has no dormancy logic and no signature check: the store is saved on every
    successful run.
  - Its match record shape differs (§7.2).
  - `status` is stored as Sofascore's raw `status.type`; readers accept
    `FINISHED_STATUSES = {"ended", "afterpenalties", "afterextratime", "ap",
    "aet", "finished"}`.
- **Flags:** `--budget N`, `--backfill`, `--refresh-detail`, `--probe`.
- **Exit:** 1 if no matches were fetched (store untouched), else 0.

### 6.3 `scripts/fetch_sofascore_history.py`: the archive

- **Store:** `docs/site/data/archive/store.json`. The loader and readers are in
  `oddsmarkets/football/analytics/archive.py`. The shape is
  `{seasons, players, season_lists, meta}`.
- **Second store:** `docs/site/data/past/store.json` (past results, below).
- **Budget:** `DEFAULT_BUDGET = 60`. Every call is charged, except the initial
  probe. `--past-budget N` (default `DEFAULT_PAST_BUDGET = 20`, 0 to skip) is
  the share of it past results may spend.
- **Constants:** `SEASONS_BACK = 8`, `SEASONS_PER_PLAYER = 12`,
  `PROFILED_PER_COMPETITION = 25`, `PAST_SEASONS_BACK = 6`, `PAUSE_S = 1.0`,
  `MAX_CONSECUTIVE_FAILURES = 3`.
- **Competitions:** every `seasons.json` entry plus the Argentine league
  (tournament 155, its current year's Apertura and Clausura counting as the
  store's seasons; `with_liga()`).

Three queues are spent in order. Each run does what the budget allows and the
next run resumes.

1. **Past seasons** (skipped with `--players-only`).
   - For each competition: if the tournament's season list is not
     cached in `season_lists`, fetch it (1 call) and immediately fetch up to 8
     past seasons.
   - Otherwise fetch past seasons not yet in `archive.seasons[slug]`. Each costs
     2 calls: `standings_blocks` and `top_players`. Standings rows record
     `team_id`.
   - The loop stops when `budget.left < 2`, when blocked, or after 3
     consecutive misses.
2. **Past results** (skipped with `--players-only` or `--past-budget 0`).
   - `past_queue()` lists up to 6 seasons older than the ones each store keeps
     (from the cached season list; club friendlies skipped), not yet
     `complete`, newest first across competitions (every competition's last
     season before its store's, then the one before), leagues before cups at
     each depth. A season no longer in the tournament's list (a competition
     re-resolved to another tournament) is dropped.
   - `fetch_past_season()` calls `sofascore.past_season_events()`: the
     `events/last` pages from the season's `next_page`, one call per page of
     30 matches, under a budget of `min(--past-budget, budget left)`. Each event
     goes through `event_record` with the competition's own name rules and is
     stored as results only (`PAST_KEYS`: `home, away, home_id, away_id, hs,
     as, date, round, stage, group, winner, agg_winner, status, split_group,
     pens`; no detail). A season the budget cut
     short resumes at its page next run.
   - About 350 seasons are queued, roughly 2,800 calls: about six days at 20 an
     hour.
3. **Player careers** (skipped with `--seasons-only`).
   - `profiled_players()` returns the top 25 qualified players by rating from
     each `docs/site/data/*/players_live.json`, de-duplicated by id.
   - For each incomplete player: `player_details`, then `player_seasons`
     (filtered to `allowed_tournaments()`, meaning every registry id, Liga MX's
     alt id, `{16, 1, 133, 357}` and 155, newest 12), then one
     `player_season_stats` per season.
   - A season with no statistics is stored with `empty: True` so it is not
     re-asked.
   - `complete` is set when every listed season is in.

The archive and the past-results store are each saved only if something
changed. The script exits 1 only if `seasons.json` is missing or the probe hits
a 403. Otherwise it exits 0.

### 6.3a `scripts/fetch_sofascore_squads.py`: current squads

- **Store:** `docs/site/data/squads/store.json` (§7.3a). The build reads it as
  the authority on who plays where.
- **Clubs** (`candidate_clubs()`): every club of the current season of the 12
  followed leagues and Argentina (priority 0), and of the continental and world
  club cups (family `cup`, priority 1); about 620. National teams have no fixed
  squad and are left to their latest call-ups.
- **Rotation** (`due_clubs()`): clubs never fetched first, by priority (leagues
  before cups); then any club whose squad is older than `REFRESH_DAYS = 3`, or
  one day (`WINDOW_REFRESH_DAYS`) inside a transfer window
  (`TRANSFER_WINDOWS`: 1 January to 10 February, 10 June to 5 September),
  oldest first. One call per club, `sofascore.team_players()` on
  `/team/{id}/players`.
- **Departures:** a player in the club's previous squad, or who appeared for it
  in the last `RECENT_DAYS = 365` and has not been seen at another followed club
  since, but is missing from the new squad, joins `pending`. Up to
  `DEPARTURE_LOOKUPS = 8` a run are looked up with `/player/{id}` and their new
  club recorded under `people`. The queue is capped at `MAX_PENDING = 400`.
- **Budget:** `DEFAULT_BUDGET = 20`; `PAUSE_S = 1.0`,
  `MAX_CONSECUTIVE_FAILURES = 3`; stops at the first 403.
- **Flags:** `--budget N`; `--team TID` (repeatable) fetches those clubs now,
  ignoring the rotation.
- The first pass over about 620 clubs takes a day and a half at 20 an hour.

### 6.4 `scripts/fetch_sofascore.py`: legacy World Cup (datafc)

- Tournament `16`, season `58210`, via datafc `match_data` /
  `season_rounds_data` with slugged knockout rounds, and datafc's `lineups_data`,
  `shots_data`, `momentum_data`, `incidents_data` for detail.
- Store: `docs/wc/data/players_live_store.json` in the old thin format. The
  record has only `home, away, round, status, hs, as`; there are no dates, and
  shots have fields remapped from datafc.
- Flags: `--probe`, `--backfill` (max_new 1000; default 40). There is no budget.
- It was driven by `scripts/refresh_sofascore_local.ps1` (the old "WC2026
  Sofascore Refresh" task, which pulls and pushes `main` by name) and read by
  `scripts/build_site_wc.py`. The World Cup is over, so do not re-enable it. The
  hub's World Cup comes from the seeded store below and, once discovered, from
  the main fetcher.

### 6.5 `scripts/seed_world_cup_store.py`

A one-off bridge. It builds `docs/site/data/world-cup/store.json` from the
archived World Cup site's `docs/wc/data/players_live_store.json` and
`groups.json`:

- It maps the old numeric knockout rounds (`6→r32`, `5→r16`, `27→qf`, `28→sf`,
  `29→final`, `50→3rd`) and approximates dates as one per round.
- It sets `group` from group membership, `neutral: true`, `season_id: null`,
  and `meta.seeded_from = "docs/wc"` with `dates_approximate: true`.
- It refuses to run if the store already has `meta.season_id`, meaning a real
  fetch has happened.

After `world-cup` is discovered, the fetcher replaces the fixtures by event id.
The detail carries over and is upgraded to the full format by
`--refresh-detail`.

### 6.6 Sample-store generators (development only)

`scripts/make_league_sample_store.py` and `scripts/make_liga_sample_store.py`
write synthetic stores marked `meta.synthetic = true`. The build shows a sample
banner, and both fetchers discard a synthetic store rather than merging real
matches into invented ones.

---

## 7. Store format

### 7.1 League, cup and national-team stores: `docs/site/data/<slug>/store.json`

Top-level keys (`sofascore.new_store()` plus what `load_store` and the fetcher
add):

```text
matches        {event_id: MatchRecord}
lineups        {event_id: {player_id: LineupEntry}}
shots          {event_id: [Shot]}
momentum       {event_id: [{minute, value}]}
incidents      {event_id: [Incident]}
players        {player_id: PlayerMeta}             # once per store, not per match
team_stats     {event_id: {home: {...}, away: {...}}}
lineup_extras  {event_id: {formation: {home, away}, missing: {home: [...], away: [...]}}}
conferences    {name: [teams]}                     # from seasons.json (MLS conferences, cup groups)
zones          {}                                  # added by the shared loader; used by Argentina only
meta           {league, season_id, season_name, fixtures_refreshed_at, updated_at, [synthetic], [seeded_from, dates_approximate]}
```

**MatchRecord** (from `event_record`, keyed by Sofascore event id as a string):

| Key | Type | Notes |
|---|---|---|
| `home`, `away` | str | Canonical names (registry / country registry / international). |
| `round` | int \| str \| null | League round number, knockout key (`r16`, `qf`, `po`, `r32`, `3rd`, …), or the round name. |
| `status` | str | Sofascore `status.type`, lower-cased: `finished`, `inprogress`, `notstarted`, `postponed`, `canceled`, … |
| `hs`, `as` | int \| null | `homeScore.display` / `awayScore.display`. |
| `date` | ISO-8601 UTC | From `startTimestamp`; the previous value is kept if missing. |
| `stage` | str | `league`, `playoff`, `qualifying`, `split`, `other`. |
| `winner` | str \| null | Drawn playoff match settled on penalties. |
| `season_id` | int | Sofascore season id. Only `meta.season_id` is the live season; others are training history. |
| `home_id`, `away_id` | int | Sofascore team ids (crests, club pages). |
| `home_country`, `away_country` | str \| null | Alpha-3. |
| `group` | str \| null | `A`, `1`, `A1`, `East`, … |
| `split_group` | str \| null | Belgian split: `top`, `europe`, `relegation`. |
| `agg_winner` | str \| null | Two-legged tie winner on aggregate (second leg). |
| `leg` | null | Always null in the current code. |
| `neutral` | bool | **Only present in the seeded World Cup store.** Otherwise neutrality comes from config (`neutral_venues`, `neutral_rounds`, `final_at_neutral_venue`) at build time; `cup/store.py` reads `raw.get("neutral")` and defaults to false. |

**LineupEntry** (`parse_lineups`; players with no kept stats, i.e. unused
substitutes, are omitted):

| Key | Meaning |
|---|---|
| `n` | Player name. |
| `t` | Team (canonical name of the side). |
| `s` | `{stat: number}` restricted to `KEEP_STATS`; ints stay ints, floats rounded to 4 dp. |
| `p` | Position (`G`, `D`, `M`, `F`). |
| `no` | Shirt number (string). |
| `sub` | `true` if he started on the bench. |
| `cap` | `true` if captain. |

**PlayerMeta** (`players[pid]`): `n` (name), `sn` (short name), `pos`, `slug`,
`dob` (Unix seconds), `h` (height, cm), `c` (country alpha-3), `no` (jersey
number).

**Shot** (`parse_shotmap`):

- Always present: `player_id`, `player_name`, `team`, `is_home`, `x`, `y`, `xg`,
  `xgot`, `shot_type`, `body_part`, `situation`, `time`.
- Optional: `added_time`, `goal_mouth`, `gm_y`, `gm_z`, `goalkeeper`.
- `x` is the distance from the goal line being attacked (0 at the line) and `y`
  runs across the pitch, both in percent of the pitch.

**Incident** (`parse_incidents`; `period` and `injuryTime` are dropped):

- Always present: `incident_type`, `incident_class`, `time`, `added_time`,
  `is_home`, `team`, plus `player_name`/`player_id` when there is a player.
- Substitution adds `player_in`, `player_out` and optionally `injury`.
- Goal adds `home_score`, `away_score` and optionally `assist`.
- Card adds `reason`. VAR adds `confirmed`.

**team_stats**: whole-match (`period == "ALL"`) values keyed by Sofascore's stat
`key`, for example `ballPossession`, `expectedGoals` and `totalShotsOnGoal`. For
ratio stats the denominator is stored as `<key>_total`.

**momentum**: `[{minute, value}]` from `graphPoints`. A positive value means
home pressure.

#### Thin versus full detail

| | Thin (old) | Full (current) |
|---|---|---|
| Written by | datafc-era fetchers (and the seeded World Cup store) | `sofascore.fetch_match_detail` |
| `lineups[gid][pid]` | `{n, t, s}` with a short stat list (~12–26 keys) | `{n, t, s, p, no, sub, cap}` with the 72-key list |
| `team_stats[gid]` | absent | present |
| `players`, `lineup_extras` | absent | present |
| Shots | datafc columns | includes `player_id`, goal-mouth, goalkeeper |

A match counts as thin when `gid in lineups and gid not in team_stats`. Both
fetchers queue such matches **behind** matches with no detail when
`--refresh-detail` is set, so stores upgrade a few matches per run. Example, the
Premier League store on 2026-09-29: 50 matches with lineups, 5 in the full
format, with an average of 27 stat keys per player (full) against 12.6 (thin).
The hourly task always passes `--refresh-detail`.

### 7.2 The Argentine store: `docs/liga/data/liga_store.json`

It has the same top-level keys (`EMPTY_STORE` in `liga/store.py` adds `zones`).
Its match record is different:

`{home, away, round, status (raw), hs, as, date, torneo ("apertura"|"clausura"),
season_id, zone ("A"|"B"|null for interzone), home_id, away_id}`

`zones` is `{torneo: {zone: [teams]}}`. The detail keys are identical to §7.1.

### 7.3 The archive store: `docs/site/data/archive/store.json`

```text
seasons[slug][season_id] = {name, year, tournament_id, standings: [{group, team, team_id, position, points, matches, promotion}],
                            top_players: {category: [{id, name, position, team, value, appearances}]}, fetched_at}
players[pid]             = {why, details: {...player_details}, season_list: [{tid, tname, sid, sname, year}],
                            seasons: [{tid, tname, sid, sname, year, stats, team, [empty]}], complete, fetched_at}
season_lists[tid]        = [{season_id, name, year}]
meta                     = {updated_at}
```

The file does not exist yet: the first archive run hit the 2026-09-29 challenge.
`team_id` in standings rows was added on 2026-10-02; older rows lack it.

### 7.3a The squads store: `docs/site/data/squads/store.json`

```text
teams[tid]   = {name, fetched_at, players: [PlayerMeta-shaped rows, plus the contract end]}
people[pid]  = {team_id, team, fetched_at}     # a departed player's new club, from /player/{id}
pending      = [pid]                           # departures still to look up (at most 400)
meta         = {updated_at}
```

### 7.3b The past-results store: `docs/site/data/past/store.json`

```text
seasons[slug][season_id] = {name, year, tournament_id, matches: {event_id: results-only MatchRecord},
                            complete, next_page, fetched_at}
meta                     = {updated_at}
```

`complete` is false while pages remain; `next_page` is where the next run
resumes.

### 7.4 Where stores live, and what is committed

| Store | Path | Committed by the hourly task |
|---|---|---|
| Each league/cup/national team | `docs/site/data/<slug>/store.json` | yes (glob `docs\site\data\*\store.json`) |
| Archive | `docs/site/data/archive/store.json` | yes (same glob) |
| Current squads | `docs/site/data/squads/store.json` | yes (same glob) |
| Past results | `docs/site/data/past/store.json` | yes (same glob) |
| Argentina | `docs/liga/data/liga_store.json` | yes |
| League/cup season ids | `oddsmarkets/football/competitions/league/data/seasons.json` | yes |
| Argentine season ids and zones | `oddsmarkets/football/competitions/liga/data/seasons.json` | no (commit by hand after discovery) |
| Legacy World Cup | `docs/wc/data/players_live_store.json` | no (legacy task) |
| Probability snapshots (build output) | `docs/site/data/<slug>/history_store.json` | no; travels via the public repo and is hydrated back |

`.gitignore` ignores `data/` at any depth and re-includes only specific
directories. Under `docs/site/data/` it ignores everything
(`docs/site/data/**`) and re-includes only `docs/site/data/*/` and
`docs/site/data/*/store.json`. **Only `store.json` files are committed there.**
Every other file in that tree is a CI build output.

### 7.5 Readers

| Module | Functions |
|---|---|
| `oddsmarkets/football/competitions/liga/store.py` | `load_store` (never raises; fills missing keys from `EMPTY_STORE`), `save_store` (stamps `meta.updated_at`), `store_age_hours` (from `meta.updated_at`), `iter_matches`, `zones_from_store`, `torneo_from_store`, `season_state_from_store`, `team_xg_map`, `training_frame`, `aggregate_players`, `shots_by_player`, `match_details`, `player_match_logs`, `team_match_stats`, `empirical_calibration`. The match-level readers are shared by every competition (called with a registry). |
| `oddsmarkets/football/competitions/league/store.py` | Re-exports `load_store`, `save_store`, `store_age_hours`, `empirical_calibration`; plus `iter_matches(store, cfg, …)`, `current_season_id`, `conferences_from_store`, `league_state_from_store`, `team_ids_from_store`, `playoff_results`, `training_frame(store, cfg)`, `team_xg_map`, `aggregate_players`, `shots_by_player`, `match_details`, `player_match_logs`, `team_match_stats`, `store_signature`, `last_finished_date`. |
| `oddsmarkets/football/competitions/cup/store.py` | `iter_matches(store, season_id=None)`, `tie_results`, `cup_state_from_store`, `training_frame(store)` (every finished match, all stages and seasons, with countries and `neutral`, for the pooled fit), `international_training_frame(store, neutral, weight)` (adds `neutral` and `weight` columns), plus the shared analytics wrappers with no registry. |
| `oddsmarkets/football/analytics/archive.py` | `load_archive`, `save_archive`, the career and past-season readers. |
| `oddsmarkets/football/analytics/unified.py` | `Unified`: reads every store above (competitions, Argentina, archive, squads, past results) into the people, clubs and seasons payloads; contract in `docs/site/UNIFIED_PAYLOADS.md`. |

---

## 8. Scheduling

### 8.1 Local: `scripts/refresh_sofascore_all.ps1`

This is registered as the Windows scheduled task **"Sofascore Refresh (all)"**,
repeating hourly. The registration commands are in the script header. It is
**one task for everything on purpose**: two tasks racing `pull --rebase` /
`push` against the same repo would silently drop updates. The file is **ASCII
only**, because Windows PowerShell 5.1 misreads UTF-8 without a BOM. It also
must **not** redirect native stderr (`2>&1`), because Python logs INFO to stderr
and PS 5.1 turns the redirect into a terminating error. The log is
`scripts/refresh_sofascore.log` (git-ignored via `scripts/*.log`).

Steps, in order:

| # | Step | Command | On failure |
|---|---|---|---|
| 1 | Resolve the current branch | `git rev-parse --abbrev-ref HEAD` | detached HEAD → log "not on a branch", exit 1 |
| 2 | Autostash if dirty | `git stash push --quiet -m "refresh_sofascore_all autostash"` (tracked files only; `--untracked-files=no` is used for the dirtiness check) | — |
| 3 | Pull | `git pull --rebase --quiet origin <branch>` then `git stash pop` | log "git pull failed", exit 1 |
| 4 | Argentina | `fetch_sofascore_liga.py --refresh-detail --budget 100` | log, continue |
| 5 | Discovery | `discover_sofascore_leagues.py --missing --limit 6` | log "Discovery incomplete", continue |
| 6 | Leagues, cups, national teams | `fetch_sofascore_leagues.py --all --refresh-detail --budget 150` | log, continue |
| 7 | Current squads | `fetch_sofascore_squads.py --budget 20` | log "Squads fetch failed", continue |
| 8 | Archive and past results | `fetch_sofascore_history.py --budget 60` | log, continue |
| 9 | Nothing succeeded | — | log "no stores refreshed - nothing to commit", exit 1 |
| 10 | Stage | `docs/liga/data/liga_store.json` (if step 4 ok), every `docs\site\data\*\store.json` (if step 6, 7 or 8 ok; this includes `squads/` and `past/`), and always `oddsmarkets/football/competitions/league/data/seasons.json` | — |
| 11 | Commit and push once | `git commit -m "Sofascore store refresh (local scheduled task)"`, `git push origin <branch>` | log "git push failed", exit 1 |

The task works on whichever branch is checked out. It pulls, commits and pushes
that branch. The site workflow builds from the default branch, so **stores
pushed to a feature branch do not reach the site** until merged.

### 8.2 CI: `.github/workflows/update_site.yml` ("Combined Site Hourly Update")

It is triggered by cron `17 * * * *` (hourly at :17) and `workflow_dispatch`.
It runs on `ubuntu-latest` with Python 3.11 and `uv sync`, has
`permissions: contents: read`, and never writes back to this repo.

1. **Hydrate.** This step is skipped if the `SITE_REPO` variable is unset. For
   every slug in `seasons.json` plus `liga-argentina`, it
   fetches `https://raw.githubusercontent.com/<SITE_REPO>/main/data/<slug>/store.json`
   and replaces the repo copy if `(len(matches), len(lineups))` is larger when
   compared as a tuple: match count first, then detail coverage. Since
   2 October 2026 it first refuses a public store whose `meta.season_id` is not
   one of `seasons.json`'s seasons for that slug (`same_seasons`), so a store
   from before a competition was re-resolved (the World Cup qualifiers, the
   Asian Cup) cannot come back however many matches it has. It also
   hydrates `data/<slug>/history_store.json` (probability snapshots) when the
   public copy has more snapshots.
   - `squads` and `past` are in the loop too: the public copy replaces the repo
     copy when its `meta.updated_at` is newer.
   - The Argentine store (`docs/liga/data/liga_store.json`) is **not** hydrated
     from the public site; only its history is.
   - The archive is not in the loop (it is not in `seasons.json`), so the repo
     copy is always used.
2. **Build.** `uv run python scripts/build_site_all.py --sims 30000` with
   `ODDS_API_KEY` from secrets. The last build step, `build_unified()`, writes
   the people, clubs and seasons payloads. `build_site_all.py` flags: `--sims N`, `--no-market`,
   `--only SLUG` (repeatable), `--skip-liga`, `--seed`.
3. **Deploy.** This needs `SITE_REPO` and `SITE_DEPLOY_KEY` (base64 SSH key);
   without them the job builds and exits cleanly. It clones the public repo,
   `rsync -av --delete --exclude='.git' docs/site/ /tmp/site/`, and commits
   "Site update <UTC timestamp>" as `github-actions[bot]`. Stores ship with the
   site so the next run can hydrate from them. They are data files, not part of
   the page.

### 8.3 Legacy workflows

| Workflow | Status | What it did |
|---|---|---|
| `.github/workflows/update_liga.yml` | `workflow_dispatch` only; superseded by `update_site.yml` | Hydrated `liga_store.json` / `history_store.json` from `LIGA_SITE_REPO`, ran `build_site_liga.py`, and deployed `docs/liga/`. It never deployed successfully (`LIGA_DEPLOY_KEY` is invalid). |
| `.github/workflows/update_wc.yml` | `workflow_dispatch` only; the World Cup is over | Hydrated `players_live_store.json` from `pchattani/wc2026` (by lineup count), built `build_site_wc.py` with `FD_API_KEY`, and deployed `docs/wc/`. |

---

## 9. Failure modes

| Failure | Detection | How it degrades |
|---|---|---|
| **IP challenged (403)** | `probe` → `is_blocked()` | The fetcher exits 1 after one call ("nothing fetched this run"). Mid-run, it stops before the next competition or after the current match. Stores already modified in memory are still saved in phase three when their signature changed. The task commits nothing if every step failed. The site keeps serving the last build; after 24 h without a store rewrite, a competition shows as stale (`store_fresh: false`, `STALE_AFTER_HOURS = 24` in `build_site_all.py`). |
| **Host down or transport error** | `get_json` returns `None` | Failover to `api.sofavpn.com`. The call is counted as a miss. Three consecutive detail misses stop detail for the run. |
| **Partial fixture response** | `season_events` stops at the first failed page | Returns what arrived. Fixtures already in the store are kept (records are upserted by id, never deleted). A missing `date` keeps the stored date. A season with zero events is skipped ("keeping stored fixtures"). If no season arrived, the store is left untouched. |
| **Partial detail** | `fetch_match_detail` | No lineups means failure, and nothing is written for that match, so it stays queued. Lineups present but statistics/shots/graph/incidents missing means the match is stored without them. If `team_stats` is missing, the match remains "thin" and is retried under `--refresh-detail`. |
| **Budget runs out** | `budget.left < 5` / `BudgetExhausted` | Detail stops. The queue resumes next run, newest first. |
| **Club renamed** (registry change, fixed country code) | `refresh_fixtures` sees `prev.home != record.home` | The rename is applied to that match's `lineups[*].t`, `shots[*].team` and `incidents[*].team`, so players and shots follow the club into the table. The rename only happens for matches whose fixtures are refetched, i.e. the `seasons.json` seasons of non-dormant competitions. |
| **Unknown spelling** | none (silent) | `normalize_team_name` returns the name unchanged. The club appears under Sofascore's spelling, and a join against another source (odds, league registry) misses. Fix it by adding an alias. |
| **Synthetic sample store** | `meta.synthetic` | Both fetchers discard it and start fresh. The build labels a synthetic store as sample data until then. |
| **Competition with no store** | `load_store` returns no matches | The build emits `{ok: false, reason: "no store yet"}` for leagues, cups (except `fixed`) and Argentina. The picker in `docs/site/assets/js/core.js` shows it disabled as "(soon)". Any other `ok: false` reason shows "(unavailable)". |
| **Competition not in `seasons.json`** | fetcher logs "not in seasons.json" | Counted as a failure for that slug; the rest proceed. The hourly discovery step adds six missing entries per run. |
| **Search resolves the wrong tournament** | discovery log line "resolved to …" | Silent wrong data. Pin `sofascore_id` in `cup/config.py`, rerun `discover_sofascore_leagues.py --league <slug>`, and empty the slug's store and archive seasons so they refill. The CI hydrate step will not bring back a public store whose season is not in the new `seasons.json` entry; past results drop seasons not in the new tournament's list. |
| **Squads stale or not yet fetched** | `squads/store.json` `teams[tid].fetched_at` | The build falls back for that club (`UNIFIED_PAYLOADS.md` 2.3): a profile newer than the last appearance, else the latest club appearance. |
| **Only live scores changed** | `store_signature` unchanged | Not rewritten and not committed. |
| **Build error in one competition** | exception in `build_league` / `build_cup` / `build_liga` | Logged. That competition gets `ok: false` with the error as the reason; the others build. |
| **The Odds API / Polymarket / Kalshi down, or no key** | `None` from the safe wrappers | `market_odds.json` keeps the previous payload with `ok: false`. |
| **Public copy more complete than the repo copy** | hydrate step | CI builds from the public copy, which protects against a local store that regressed. |
| **Push rejected** (race) | exit code | Logged "git push failed", exit 1. The next run pulls with rebase and retries. |

---

## 9a. The calendar window backfill

`detail_queue` also queues **last season's** finished matches dated within
`WINDOW_DAYS` (365) of today that have no detail, newest first, after everything
the current season wants (and after `--refresh-detail` upgrades), under the same
hourly budget. They feed the Player lab's "last 12 months" and "calendar year"
views. As of 30 September 2026 that is roughly 4,000 matches across the
competitions with stores, about 20,000 calls, so at 150 calls an hour shared with
the current season the window fills over about a week once the Sofascore
challenge clears. Season pages never count this detail: `build_site_all.py`
aggregates players, match logs, shot lists and team sheets from
`_season_view(store)`, the store restricted to the current season's matches.

## 9b. Two things a refresh taught (30 September 2026)

- **Sofascore shows a voided or awarded match with a negative "score"** (a
  Coupe de France walkover came back as −2/−4). `event_record` now stores such a
  score as none, `Match.is_finished` needs a real scoreline, and the Dixon-Coles
  fit drops negative rows and raises rather than fit if its likelihood is not
  finite. Before those guards, one such row froze the pooled optimiser at its
  starting point and every club in every pooled league came out average.
- **Sofascore's search spans every sport.** "King Cup" found the Billie Jean
  King Cup (tennis) and "Copa do Brasil" a volleyball cup, and both were
  fetched and pooled. `search_tournament` now keeps football only and marks
  down women's and youth editions; those two cups carry pinned ids (2058, 373).

## 9c. Argentina's halves (2 October 2026)

Since 2026 one Sofascore season id serves both torneos (§4.3). The hub's
Argentine pages (players, logs, team stats, shots, fixtures, leaders) are built
on the current torneo only (Clausura 2026), through `_torneo_view()` in
`scripts/build_site_all.py`, not on the whole calendar year. The Apertura is a
past season in the unified payloads, with season id `"2026-apertura"`.

## 10. Known gaps and sharp edges

These come from reading the code. Items 1 and 2 were fixed on 2026-09-29;
the rest are open.

1. **Fixed: dormancy lapsed a day after the last real change.**
   `fixtures_refreshed_at` is not part of `store_signature`, so a quiet store
   was never rewritten and its stamp never reached disk. The fetcher now saves
   an unchanged store once every `HEARTBEAT_HOURS` (20) via `needs_heartbeat`,
   which keeps the stamp inside `DORMANT_REFRESH_HOURS` (24). Dormant
   competitions are never re-saved; the cost is one small commit per quiet
   competition per day.
2. **Fixed: the stale flag on quiet stores.** The same daily save refreshes
   `meta.updated_at`, so a competition checked hourly but without new results
   stays inside the build's 24-hour staleness window.
3. **Fixture pages are unbudgeted.** Each season costs at least 2 calls
   (`last/0`, `next/0`) plus one per extra page. With `KEEP_SEASONS = 2` that
   is at least 4 calls per competition per run, before detail. With all 68
   registry entries discovered, that is at least ~270 unbudgeted calls an hour
   unless dormancy works (item 1). The same applies to discovery (search,
   seasons, standings) and to the probes. `CallBudget` covers detail, archive,
   past-results, squad and player calls only.
4. **Failover doubles HTTP requests.** A failing call hits both hosts, and the
   403 breaker reads only the last host's status (§2.1).
5. **`fetch_crests.py` and `discover_sofascore_liga.py` have no budget and no
   403 breaker.** Run them only by hand on a healthy IP.
6. **The autostash comment overstates it.** `refresh_sofascore_all.ps1` says it
   stashes "only what is not a store", but `git stash push` stashes all tracked
   changes, stores included, and pops them back before the fetch.
7. **Branch coupling.** The task pushes whatever branch is checked out, while
   `update_site.yml` checks out the default branch. Leaving a feature branch
   checked out on the owner's machine keeps fresh stores off the site.
8. **The Argentine store is not hydrated in CI**, unlike the others.

---

## 11. Free alternative sources (not implemented)

**None of these is wired into the pipeline.** They were considered as
supplements or fallbacks, mainly to reduce dependence on one unofficial API that
blocks bursts and datacenter IPs.

| Source | What it would add |
|---|---|
| football-data.org (free tier) | Official fixtures, results and standings for about a dozen top competitions via an API key that works from CI. It would make a Sofascore-independent fixture fallback. No player detail or xG. Already used for the legacy World Cup (§2.5). |
| ESPN public endpoints (`site.api.espn.com`) | Unauthenticated scoreboards, fixtures and basic box scores across many leagues. A cheap cross-check for results and kickoff times that may work from CI. |
| Understat | Shot-level xG and per-player xG/xA for the big-five leagues plus the RPL, back to 2014. It would give an independent xG model and long history for training. |
| FotMob (unofficial JSON) | Lineups, player ratings, shot maps and xG across many leagues. A detail fallback similar to Sofascore, with similar unofficial-API risk. |
| FBref | Season-level advanced player and team stats (Opta-derived) and long histories, via scraping. Rate-limited, and some advanced tables have been removed. |
| StatsBomb open data | Free event-level data (World Cups, Euros, some league seasons, women's competitions). Useful for model research and validating shot-map and xG handling, not for live data. |
| ClubElo | Daily Elo ratings for European clubs back decades, via a simple CSV API. Priors and a cross-check for the club strength scale. |
| eloratings.net | World Football Elo for national teams. Priors for the international fit and a benchmark for `nations.json`. |
| football-data.co.uk | Historical results with closing bookmaker odds (CSV) for many European leagues. A market baseline to calibrate and backtest the model's fair odds. |
| API-Football (free tier) | Fixtures, lineups, events and statistics under a small daily request quota with a key. A CI-friendly but quota-limited detail fallback; there is already a client in `live_data.py`. |

---

## 12. Operator quick reference

Check whether Sofascore answers this IP (one call):

```
.venv\Scripts\python scripts\fetch_sofascore_leagues.py --probe
```

Read the task log:

```
Get-Content scripts\refresh_sofascore.log -Tail 30
```

Before any manual run, disable the scheduled task:

```
Disable-ScheduledTask -TaskName "Sofascore Refresh (all)"
```

A one-sitting fill after a challenge clears (space runs hours apart; re-enable
the task afterwards):

```
.venv\Scripts\python scripts\discover_sofascore_leagues.py --missing
.venv\Scripts\python scripts\fetch_sofascore_leagues.py --all --refresh-detail --budget 600
.venv\Scripts\python scripts\fetch_crests.py
```

Then commit `oddsmarkets/football/competitions/league/data/seasons.json` and
`docs/site/data/*/store.json`.

One club's squad now (a call per club):

```
.venv\Scripts\python scripts\fetch_sofascore_squads.py --team <tid>
```

Add a competition:

1. Add a `LeagueConfig` to `LEAGUES` or a `CupConfig` to `CUPS`. Use a fixed
   `sofascore_id` or `search` + `country_hint`; set `family`, `kind`,
   `round_slugs` and `detail_scope`.
2. Add a name registry if it is a new country's league, and map the country in
   `COUNTRY_REGISTRY` and `COUNTRY_LEAGUE`.
3. `discover_sofascore_leagues.py --league <slug>` (or let `--missing` pick it
   up hourly), and check the resolved id in the log.
4. Let the hourly task fetch it. Until its store exists the site lists it as
   "(soon)".

Season rollover:

- Rerun `discover_sofascore_leagues.py --league <slug>` for the competition, or
  run it without flags to rewrite the whole file.
- For Argentina, run `discover_sofascore_liga.py --verify`, check the ids, then
  run it without `--verify` and commit.
- Re-verify the bands and formats in the configs.
