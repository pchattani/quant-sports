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
   `oddsmarkets/rugby/fitted/params.json` and `report.json` (MODELS.md).
2. `scripts/scrum_spec.py` measures each player metric's reliability and writes `docs/_design/metrics/rugby.json`.
3. `scripts/build_scrum.py` (every step guarded, every import that can fail inside its step) copies the kit and
   writes per scope (`oddsmarkets/rugby/pages.py`):

| Payload | What |
|---|---|
| `index.json` | site, scopes (teams with colours, years, competitions), freshness, credit |
| `<S>/overview.json` | digest top lines, featured test, upcoming tests with our chances, power board, who's hot by position, stories, who's for real, title races, champions |
| `<S>/fixtures.json`, `<S>/years/<Y>.json` | upcoming tests with chances; results with our walk-forward pre-match call; the archive |
| `<S>/matches/<id>.json` | the match page: card, halves, forecast and its inputs, team stats, the matchday 23 with minutes, key moments, the World Rugby exchange |
| `<S>/ratings.json`, `<S>/rankings.json` | our ratings with history; our World Rugby rebuild (table, week's movement, history, "what each result would do", the replica check) |
| `<S>/comps/<key>.json` | standings with bonus points, simulations (Six Nations 2027, Nations Championship 2026, Rugby World Cup 2027), past winners |
| `<S>/teams.json`, `<S>/teams/<id>.json` | the profile grid; team pages (profile, results, head to head, squad, most capped, rating history) |
| `<S>/players.json`, `<S>/players/<id>.json` | the Scouting Room board (column-oriented); player pages |
| `<S>/model.json`, `<S>/lab.json`, `<S>/records.json` | the ladder, calibration and forecast log; league-wide analytics; records |
| `follow/<S>/<id>.json` | My Teams cards (`follow_build.py`, under 8 KB each) |
| `search.json`, `glossary.json` | search rows; the glossary |

The forecast log (`data/rugby/stores/forecast_log_<S>.json`) records every published forecast up to kick-off and then
freezes it; it travels with the stores.

## Front end

`docs/scrum/index.html` and `assets/js/sc-*.js` on kit v4 (`assets/qk`, copied by `scripts/design_kit.py`). Routes:
`#/<S>` overview, `/fixtures`, `/match/<id>`, `/standings?tab=nc|six|trc|rwc&view=`, `/rankings?tab=wr|ours`,
`/teams`, `/team/<id>`, `/scout?view=board|chart|leaders&grp=all|fwd|back|<group>&min=&team=&tier=&age=&q=&p=&cmp=` (sc-scout.js), `/player/<id>`, `/model?tab=method|doing|lab|records|glossary|terms`.

## Running and publishing

- PC: `refresh_sofascore_all.ps1` runs `scrum_fetch.py --refresh-current --budget 200` hourly. `local_sites.py`
  has the site (key `scrum`), in `NOT_LAUNCHED` until the Pages repo exists.
- CI: `public_repo/.github/workflows/scrum.yml` (generated by `scripts/gen_ci_workflows.py`, `launched: False`): raw
  cache `data/rugby/stores` + `data/rugby/raw`, seed branch `seed-scrum` (`scripts/push_seed.py --site scrum`),
  guard (every men's store from 1995, at least 3,000 payloads), build, deploy to `pchattani/the-quant-scrum` when
  `DEPLOY_SCRUM=true`.
- Home: `scripts/build_home.py` `build_rugby` (PENDING until `"rugby"` is in `LAUNCHED`).
