# The Quant Scrum — data pipeline

International rugby union (men's tests first; the women's World Cup where ESPN has it). Live address once launched:
`https://pchattani.github.io/the-quant-scrum/`. The name lives in one place: `oddsmarkets/rugby/config.py` (`SITE`),
plus the `<title>` and meta tags of `docs/scrum/index.html` and the kit registry entry in `docs/_design/quant.js`.

## Source

**ESPN's public JSON only** (`oddsmarkets/rugby/sources/espn.py`). World Rugby's websites and feeds are out: their
terms limit the content to "own personal non-commercial use". The official rankings are rebuilt from results instead
(`rankings.py`), anchored and checked on published values quoted on Wikipedia (`validate.py`).

| Endpoint | What it gives |
|---|---|
| `site.api.espn.com/apis/site/v2/sports/rugby/<slug>/scoreboard?dates=YYYY&limit=1000` | every event of a calendar year in a competition; about 200 team stats per finished match (possession and territory by half, carries over the gain line, rucks, mauls, scrums and lineouts with steals, penalties by offence, turnovers, kicks, cards); the key moments (tries, conversions, penalty and drop goals, cards, substitutions) with the minute |
| `.../summary?event=ID` | the matchday 23 per side (jersey, position, captain, 26 stats a player), athlete bios (date of birth, height, weight, birth country, position), the running score on each key moment, venue and attendance |

League slugs (`config.COMPS`): Six Nations `180659` (Five Nations before 2000; results from 1995), The Rugby
Championship `244293` (the Tri Nations before 2012), Nations Championship `17567` (2026-), Rugby World Cup `164205`
(1987-; 2027 listed), International Test Match `289234` (the summer and autumn tests: thin before about 2015, none in
2005; 100 games and 65 nations in 2025), Lions tours `268565`, 2020 Tri Nations `19940`, Women's Rugby World Cup
`289237`, Olympic sevens `282` / `283`. No older Tri Nations or Pacific Nations Cup slug exists: the core API's league
list (25 leagues, probed 2 Nov 2026) has none; the Tri Nations results sit under the Rugby Championship slug. No odds
are published for rugby.

Depth: lineups from 1996, player and team statistics from about 2006 (the Six Nations), key moments from about 2006.

Etiquette: User-Agent `TheQuantScrum/1.0 (non-commercial; +https://pchattani.github.io/the-quant-scrum)` with no
e-mail, one call every 2 s, back-off on 429/403/5xx (60 s and up), a call budget per run, and every answer cached.

## The second wave (2 Nov 2026): more sources

The hunt (every candidate, its terms and robots.txt, and the verdict) is in `docs/research/data_sources.md`, "The Quant
Scrum: the rugby sources hunt". In use besides ESPN's site API, each with one module, one private side store under
`data/rugby/stores/side/` and one switch:

| Source | Module / script | Side store | Switch | What it adds |
|---|---|---|---|---|
| ESPN core API athletes | `sources/espn.py` `athlete`, `scripts/scrum_bios.py` | `side/bios.json.gz` | (ESPN) | date of birth, height, weight, birthplace for players the summaries lack (every 2026 Nations Championship player, most tier-two and three players) |
| Wikipedia article pages (CC BY-SA 4.0) | `sources/wikipedia.py`, `sources/wiki_html.py`, `wiki.py`, `scripts/scrum_wiki.py` | `side/wiki/<scope>.json.gz` | `SOURCE_WIKIPEDIA_RUGBY_ENABLED` | every test 1871-1986, the small nations' championships and qualifiers, referees, crowds and kick-off times, current-squad career caps and all-time most-capped tables, the Women's Six Nations and WXV |
| Open-Meteo (CC BY 4.0) | `sources/weather.py`, `scripts/scrum_weather.py` | `side/venues.json.gz`, `side/weather.json.gz` | `SOURCE_OPENMETEO_RUGBY_ENABLED` | venue coordinates and elevation; realised weather over each test since 1940 (ERA5); the forecast for tests in the next 16 days |

**Wikipedia.** Only `/wiki/<title>` article pages are read (robots.txt disallows `/w/` and `/api/`), one request every
2 s or more through `oddsmarkets/common/polite.py` (robots obeyed, a lock shared across processes, back-off, every page
cached gzipped under `data/rugby/wiki/`, git-ignored). The crawl starts from about 30 hub articles (each competition,
the mid-year and end-of-year internationals, the World Cup qualification) and every national team's article, then
every linked page whose title has a year and reads like a season, a tour or a test window, then one more level for
World Cup pools, qualification rounds and the internationals' months. Two page shapes are read:
- `{{rugbybox}}` match boxes (from Parsoid's `data-mw`): date, kick-off time with its UTC offset, both sides (`{{ru}}`
  flag templates; `{{ruA}}` "A" sides, "XV" names, invitational and club sides are dropped), score, venue, crowd,
  referee. Boxes with no score yet keep the referee appointment for an upcoming ESPN fixture.
- the national results lists (New Zealand, South Africa, Australia, Argentina, Japan, Germany, England by decade):
  tables with a date, an opponent and points for and against (our side first).
Home and away: a ground is given to the nation listed at home there in three of four home-and-away boxes (two or more),
else to the nearest nation in our city table; a row played at the away side's ground is turned round, one in a third
country is neutral, a list row with an unknown ground is neutral. Duplicates (the same test on a season page, a tour
page and a list) collapse to one, a box winning over a list row. Before 1891 there was no common points system: those
tests are kept as the result only (`ro`; the models see an 8-0 win or a 3-3 draw; the site shows W-L).

**The merge** (`wiki.merge`, called by `store.load_all`): a Wikipedia test matches an ESPN test when the two sides agree
and the dates are within a day; the score must agree too (otherwise it is counted as a conflict and ESPN's row is kept
untouched). A match gives ESPN's row its referee and crowd; an unmatched test becomes a match row with id `w<hash>`,
`source: "wikipedia"`, the ESPN team id where ESPN knows the side (else `w<CODE>`), no line-ups or statistics. The
report (`store.MERGE_REPORT`, also in `index.json` per scope) counts rows, matches, conflicts and additions.

**Venues and weather.** A venue is placed from our ground and city tables (`nations.place`: a ground name shared by
several grounds, such as "Allianz Stadium" in London, Sydney and Turin, goes by its city; a city shared by two countries,
such as Perth, by the ground's name; the tables win over the venues cache, so a corrected entry re-places a cached venue
and its elevation and weather are fetched again), else Open-Meteo's geocoder on its city (restricted to the venue's or
the home side's country); elevations from Open-Meteo's elevation API (Copernicus DEM). Weather is one
archive call per match day with every venue that day: temperature, humidity and wind over the kick-off hour and the
next two, rain summed over the match. Kick-off times are ESPN's (UTC), Wikipedia's when it gives a UTC offset, else
15:00 local. Realised weather is never a pre-match input; venue elevation is static and is (the altitude rung,
MODELS.md).

**Running.** Backfills (resumable, all cached): `scrum_bios.py`, `scrum_wiki.py --crawl --build`, `scrum_weather.py`.
Hourly on the PC: `scripts/scrum_extra_refresh.py` (its own lock `data/rugby/extra.lock`; bios 30 calls, Wikipedia 40
pages with this and next year's pages re-read daily and national-team articles weekly, Open-Meteo 60 calls), then
`push_stores.py` carries `data/rugby/stores/side` to the stores snapshot; CI's Scrum workflow takes it in its feed step
(`ci_site.py` FEEDS) and the guard refuses to deploy without the side stores. Nothing here is fetched on CI.

**Searched and not found:** officials in ESPN's feeds; 2026 Nations Championship statistics anywhere in ESPN; ESPN feeds
for the women's Six Nations, qualifiers or regional championships (the league ids exist with no events); kick distance
and ruck timing.

**Sofascore (added 10 Nov 2026, approved by the user 2 Nov; unclear terms, credited, switch
`SOURCE_SOFASCORE_RUGBY_ENABLED`):** `scripts/scrum_sofascore.py` on the PC only, run hourly by
`refresh_sofascore_all.ps1` after the side-store refresh. Its own budget: at most 30 calls in any rolling hour (a ledger in
`data/rugby/sofascore_state.json`), one call every 5 s, one host (`api.sofascore.com`, no fail-over), stop at the first
403, no call within 6 hours of any 403 (its own `blocked_at`, the football season tables' `blocked_at`, or a "fetch
failed" line in `scripts/refresh_sofascore.log`), skipped while the shared Sofascore lock (`data/deploy/locks/sofascore.lock`)
is held. Each run: the detail queue (statistics and line-ups, two calls a test) for tests ESPN has without
statistics (the 2026 Nations Championship first), then Sofascore-only tests; then discovery one rung a call through the
endpoints the football fetchers use every hour (the rugby categories once, each international category's tournaments,
each tournament's seasons weekly, every page of each season's finished events from 2024, the current season's first
page again daily). Search and the scheduled-events lists are not used: both answered 403 on 10 Nov 2026 (13:33 and
20:13 UTC) while football's tournament and event calls kept working, and football's search-based discovery has logged
"Discovery incomplete" every hour since 29 Sep; the state records `blocked_path`, and a 403 on the category list is
retried weekly. Only senior 15-a-side union internationals between national sides are kept (league,
sevens, age-grade, A and XV sides filtered out). Store: `data/rugby/stores/side/sofascore.json.gz` (`events`, `detail`,
`days`), carried to CI with the other side stores. Merge (`oddsmarkets/rugby/sofa.py`, inside `store.load_all`): a test
ESPN or Wikipedia has (same day +-1, same sides, same score) gets Sofascore's team statistics when it has none and its
players' statistics in the ESPN line-up's empty slots (by shirt number, surname checked), marked `stat_src`; a test only
Sofascore has is added (`id "s<event>"`, `source: "sofascore"`) only when both Sofascore team ids are proven union sides
(matched an ESPN or Wikipedia test). The statistic-name maps (`TEAM_MAP`, `PLAYER_MAP`) keep unknown items out rather
than zero-filling. `--status` prints the store, queue, ledger and back-off without a call.

## Stores (private)

`scripts/scrum_fetch.py` caches raw answers under `data/rugby/raw` (gzipped; never published) and writes one store per
scope and calendar year, `data/rugby/stores/<scope>/<year>.json.gz` (`store.py` has the row shape). A match listed by
two competitions keeps the more specific one (a Lions test is also an "International Test Match").

    uv run python scripts/scrum_fetch.py --backfill            # every competition and year; resumable (cache-based)
    uv run python scripts/scrum_fetch.py --refresh-current     # hourly: this year's and next year's scoreboards, new summaries
    uv run python scripts/scrum_fetch.py --stores-only         # rebuild every store from the raw cache

The hourly refresh writes only this year's and next year's stores, and keeps anything its raw cache lacks from the
existing store, so a runner with a partial cache never loses a line-up. It skips a summary already folded into a
store. A lock file (`data/rugby/fetch.lock`, broken after 3 hours) keeps two runs apart.

Phase 2 (club rugby: Premiership, Top 14, URC, Super Rugby, Champions Cup): a new scope in `config.SCOPES` with kind
`club`, its slugs in `config.COMPS` (ESPN's core league list has them: 8007, 8005, 8331, 8326, 8329, 8010), the same
store shape, and a scope tab on the site. Nothing else in the store changes; the rating model takes club travel
(cities) instead of nations.

## Models and payloads

1. `scripts/scrum_fit.py` tunes on 2004-2018, scores once on 2019-, applies the promotion rule and writes
   `oddsmarkets/rugby/fitted/params.json` and `report.json` (MODELS.md). Since 13 Nov 2026 it also scores the model in
   use on the same inputs and keeps it unless the re-run's choice clears the same rule against it (`--replace` skips
   the check); the report's `incumbent` block has both (MODELS.md 2b).
2. `scripts/scrum_spec.py` measures each player metric's reliability and writes `docs/_design/metrics/rugby.json`.
3. `scripts/build_scrum.py` (every step guarded, every import that can fail inside its step) copies the kit and
   writes per scope (`oddsmarkets/rugby/pages.py`):

| Payload | What |
|---|---|
| `index.json` | site, scopes (teams with colours, years, competitions, `alias`: a side's dropped second id -> the id kept, `store.unify_ids`), freshness, credit |
| `<S>/overview.json` | digest top lines, featured test, upcoming tests with our chances, power board, who's hot by position, stories, who's for real, title races, champions |
| `<S>/fixtures.json`, `<S>/years/<Y>.json` | upcoming tests with chances; results with our walk-forward pre-match call; the archive |
| `<S>/matches/<id>.json` | the match page: card, halves, forecast and its inputs, team stats, the matchday 23 with minutes, key moments, the World Rugby exchange; once the test has started, `pre` (`pages.GoingIn`): how the sides stood going in, from tests dated before the start only (last five results, head to head, our ratings rank at the start of the day, World Rugby points before the test, the team profile over the two years before) |
| `<S>/ratings.json`, `<S>/rankings.json` | our ratings with history; our World Rugby rebuild (table, week's movement, history, "what each result would do", the replica check) |
| `<S>/comps/<key>.json` | standings with bonus points, simulations (Six Nations 2027, Nations Championship 2026, Rugby World Cup 2027), past winners |
| `<S>/teams.json`, `<S>/teams/<id>.json` | the profile grid; team pages (profile, results, head to head, squad, most capped, rating history) |
| `<S>/players.json`, `<S>/players/<id>.json` | the Scouting Room board (column-oriented); player pages |
| `<S>/model.json`, `<S>/lab.json`, `<S>/records.json` | the ladder, calibration and forecast log; league-wide analytics (with the scoring clock, the age curve, weather and altitude); records (with career caps and tests by decade) |
| `<S>/referees.json` | referee tendencies (tests, penalties and cards a test, the home share of penalties, the home side against our chances) and the next appointments |
| `follow/<S>/<id>.json` | My Teams cards (`follow_build.py`, under 8 KB each) |
| `search.json`, `glossary.json` | search rows; the glossary |

The forecast log (`data/rugby/stores/forecast_log_<S>.json`) records every published forecast up to kick-off and then
freezes it; it travels with the stores.

## Front end

`docs/scrum/index.html` and `assets/js/sc-*.js` on kit v4 (`assets/qk`, copied by `scripts/design_kit.py`). Routes:
`#/<S>` overview, `/fixtures`, `/match/<id>`, `/standings?tab=nc|six|trc|rwc&view=`, `/rankings?tab=wr|ours`,
`/teams`, `/team/<id>`, `/scout?view=board|chart|leaders&grp=all|fwd|back|<group>&min=&team=&tier=&age=&q=&p=&cmp=` (sc-scout.js), `/player/<id>`, `/compare?t=<a>,<b>` and `?p=<a>,<b>[,<c>]` (team v team, player v player), `/progression?t=..&m=rating|wr&r=2000|1987|all&f=win|perf|pf` and `?p=..&m=&x=&y=` (sc-compare.js; team pages carry `years`, form by year with our pre-match expected wins and margin; `progression_ref.json` has each year's qualified-peer quantiles per position group), `/model?tab=method|doing|lab|refs|records|glossary|terms` (`refs&ref=<key>` highlights a referee).

## Running and publishing

- PC: `refresh_sofascore_all.ps1` runs `scrum_fetch.py --refresh-current --budget 200` hourly. `local_sites.py`
  has the site (key `scrum`), in `NOT_LAUNCHED` until the Pages repo exists.
- CI: `public_repo/.github/workflows/scrum.yml` (generated by `scripts/gen_ci_workflows.py`, `launched: False`): raw
  cache `data/rugby/stores` + `data/rugby/raw`, seed branch `seed-scrum` (`scripts/push_seed.py --site scrum`),
  guard (every men's store from 1995, at least 3,000 payloads), build, deploy to `pchattani/the-quant-scrum` when
  `DEPLOY_SCRUM=true`.
- Home: `scripts/build_home.py` `build_rugby` (PENDING until `"rugby"` is in `LAUNCHED`).
