# Architecture: The Quant Ace

This is the top-level map of the tennis side of the `oddsmarkets` repository and the
site it publishes, **The Quant Ace** (<https://pchattani.github.io/the-quant-ace/>),
which covers ATP and WTA singles. Start here if you are new to the tennis code. Four
sibling documents cover the detail, and this one links to them rather than repeating
them:

| Document | Covers |
|---|---|
| [DATA_PIPELINE.md](DATA_PIPELINE.md) | the four sources, identity resolution, the stores, the registry and style tables, the hourly job, the backfill |
| [MODELS.md](MODELS.md) | Elo, the serve/return model, the match chain, the blend, live win probability, the simulators, markets, the backtest |
| [DASHBOARD.md](DASHBOARD.md) | the static front-end, every payload, the build |
| [RUNBOOK.md](RUNBOOK.md) | operations, deploy, refits, troubleshooting |

`HANDOFF.md` at the repository root holds the open tennis tasks alongside the
football, F1 and basketball ones.

---

## 1. What the site is

The Quant Ace is a static ATP and WTA singles analytics site rebuilt every hour by
GitHub Actions. Both tours share one code path; a tour is `"atp"` or `"wta"`
everywhere, a season is a calendar year, a player id (`pid`) is an ESPN athlete id or
`x:<slug>`, and an event id is `<tid>-<year>` (`wimbledon-2026`;
`oddsmarkets/tennis/canon.py`). Every result starts from tennis-data.co.uk, ESPN's
public scoreboards and (WTA only) the WTA's own API; style profiles come from the
Match Charting Project; prices come from Kalshi and Polymarket and, after the fact,
from the closing odds in tennis-data's workbooks.

The depth of each year is set by what the sources hold (the exact state on disk is
in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 3):

| Tier | ATP | WTA | What it enables |
|---|---|---|---|
| Results and set scores (tennis-data) | 2000 | 2007 | Elo, the serve/return model, catalogues, history |
| Closing odds (tennis-data) | 2001 (none in 2000) | 2007 | the market comparison in the backtest; closing prices on match pages |
| Pinnacle closing odds | 2004–2008, 2010 on (none in 2009; 2026 thin) | 2007–2008, 2010 on (none in 2009; 2026 thin) | the "v Pinnacle" scores |
| ESPN scoreboards (tiebreak points, live state) | 2007 (the 2004–2006 season scoreboards answer empty) | 2007 | tiebreak points in the likelihood, live win probability, current draws |
| Qualifying matches (ESPN, WTA) | 2022 | 2016 | ratings only (qualifying is never priced or scored) |
| Real point-level statistics (WTA API) | none | 2016 | the WTA point layer, real serve/return metrics, the validation |
| Draws with seeds and entry types | none (reconstructed from results) | 2016 (WTA API; Slams reconstructed) | tournament pages, draw simulation |
| Match Charting Project | charted matches 1960–2026 | 1979–2026 | style profiles (career, charted matches only) |

Two facts that the code does not show shape everything:

- **There is no point-level ATP data.** Jeff Sackmann's `tennis_atp` and
  `tennis_wta` repositories (the usual source of per-match serve statistics) were
  taken down and answered 404 on 1 October 2026; atptour.com and Sofascore block
  scripted access. So serve and return strength is **inferred from set scores**
  (an exact set-score likelihood, with the hold/break mirror ambiguity resolved;
  [MODELS.md](MODELS.md) section 3), and the only real point-level statistics are
  the WTA API's, from 2016.
- **ESPN has no ATP draw endpoint.** ATP brackets (and the Slams' on both tours) are
  rebuilt from the matches played, without seeds or entry types; paths beyond the
  first round are approximate until the next round is set.

What the site offers (the navigation in `docs/ace/index.html`; a tour switch
ATP | WTA and a year picker sit above it):

- **Hub**: the tours' tournaments in play with their favourites, at-a-glance tiles,
  live, today's, the next two days' and recent matches with the model against the
  market and live win probability, the biggest model–market gaps, Elo top 10 by
  surface and the race to the Finals.
- **Calendar**: every event of the year by month, with level, surface, draw size,
  status and champion.
- **Tournament pages** (`#/<T>/event/<event_id>`): an interactive bracket with each
  player's path odds, title odds against the market, results, upsets, draw
  difficulty, awards and past champions.
- **Match centre** (`#/<T>/match/<mid>`): model against the market and the closing
  odds, the Elo-only and serve/return-only probabilities, set-score, total-games and
  handicap distributions, the serve/return matchup, head to head, game-by-game win
  probability with swings, excitement and comeback, real WTA statistics where they
  exist and awards.
- **Rankings** (official with movement, Elo, Race, points to defend), **Race**
  (Finals qualification and year-end No. 1 against the markets, rank distributions),
  **Elo** (current by surface, all-time peaks, lines).
- **Players** (a catalogue of 138 metrics a year with tour and surface percentiles)
  and **player pages** (career, Elo and serve/return paths, results with pre-match
  probabilities, splits, clutch, charting style, head to head, points to defend).
- **H2H**, **Lab** (any two metrics against each other) and **Compare**.
- **Markets**: match prices and futures, model against the de-vigged market.
- **Calibration**: the walk-forward backtest against Elo, a ranking baseline and the
  closing odds, the score-distribution checks, tournament-odds calibration and (WTA)
  the inferred-v-real validation.
- **Glossary** and **Methodology**: every metric and model term, and a long
  methodology document (which has fallen behind the code in places;
  [MODELS.md](MODELS.md) section 14).

### What is on disk today

As of this writing (1 October 2026, about 17:40 UTC, read from the files):

- **ATP**: stores for 2000 to 2026, 2,600–3,000 tour-level main-draw matches a year
  (1,298 in 2020), 2,249 so far in 2026; registry of 2,047 players with 2 redirects.
- **WTA**: stores for 2007 to 2026, about 2,500 tour-level main-draw matches a year
  plus qualifying and WTA 125 from 2016; 2,202 matches with real statistics in 2026;
  registry of 2,526 players with 226 redirects.
- **Committed to git** (`854419c`): every completed year's `store.json` (ATP
  2000–2025, WTA 2007–2025), each tour's `registry.json`, `style.json` and
  `calibration.json`, and `oddsmarkets/tennis/models/fitted/` (Elo constants,
  serve/return constants and a frozen fit, blend weights, for both tours). The current
  year (2026) lives on the deployed site.
- **Raw downloads** under `data/tennis/` (git-ignored): tennis-data workbooks
  (`td/<tour>/<year>.xls[x]`), raw WTA API answers (`wta/<year>/<gid>/`), the
  charting CSVs (`charting/`) and model caches (`cache/`).
- **The public site** was first deployed on 1 October 2026 by hand from a local
  build (the local `docs/ace/data/` is about 340 MB); the hourly workflow has
  deployed since (the live `index.json` said `2026-10-01T17:36:43Z` at the time of
  writing).

---

## 2. History in brief

All on 1 October 2026 (times UTC, from `git log`):

| Time | Milestone |
|---|---|
| 14:54 | "Tennis (The Quant Ace): data layer, models, analytics, site and pipeline" (`f8dd603`): `canon.py`, `store.py`, the four sources and markets, every model under `models/`, `analytics/`, `scripts/{tn_fetch,tn_charting,tn_fit,tn_hydrate,build_ace}.py`, the site shell and its seventeen JS modules, `update_ace.yml`, `setup_public_site.py --site ace`, `openpyxl` and `xlrd` added to `pyproject.toml`. |
| 15:48 | "backtest memory fix, season-sim entries, market names; ATP pages drop WTA-only metrics" (`79c62e9`): the reference-cycle leak in `match_chain` fixed ([MODELS.md](MODELS.md) section 12), chunked backtest, `_tn_backtest_c.py`, the ATP blend from the 2010–2026 backtest. |
| 16:23 | "WTA Elo and serve/return refits on the full history; ATP draw limitation documented" (`9d58ffb`). |
| 17:09 | "WTA predict blend from the 2010-2026 walk-forward backtest (w_elo 0.704, w_sr 0.298)" (`e3071b8`). |
| 17:36 | "commit the completed seasons' inputs (ATP 2000-2025, WTA 2007-2025)" (`854419c`). |

The ATP backfill (2000–2026) ran first, in under a minute of network time
(`logs/tn_backfill_atp.log`: 24 ESPN calls, 2 tennis-data calls); the WTA backfill
took about three hours, almost all of it 20,635 WTA API calls for per-match
statistics (`logs/tn_backfill_wta.log`), followed by a tennis-data re-merge and the
WTA charting table (`logs/tn_after_backfill_wta.ps1`).

`oddsmarkets/tennis/CONTRACT.md` records how the work was split while it was built:
builder A owned the data layer (`canon.py`, `store.py`, `sources/` except markets,
the registry and style tables), builder B the ratings (`elo.py`, `serve_return.py`,
`bt.py`, `_io.py`), builder C the chain and everything priced through it
(`match_chain.py`, `predict.py`, `live.py`, `tournament_sim.py`, `season_sim.py`,
`backtest.py`, `sources/markets.py`), builder D the payload build (`analytics/`,
`scripts/build_ace.py`) and builders E and F the front-end (`PAYLOADS.md`). The names
survive in docstrings ("builder B's Elo").

---

## 3. System overview

```
 GitHub Actions (pchattani/oddsmarkets, private)                 Owner's machine
 ───────────────────────────────────────────────                 ───────────────
 .github/workflows/update_ace.yml  "Ace Hourly Update"            scripts/tn_fetch.py (backfill, per tour,
 cron '27 * * * *', 55-minute job, concurrency ace-build            newest year first)
 permissions: contents read (commits nothing)                     scripts/tn_charting.py (style tables)
                                                                  scripts/tn_fit.py (constants, backtest)
   1. checkout, Python 3.11, uv sync                              completed years committed by hand
   2. restore data/tennis/cache (Actions cache, model caches)     the first deploy (1 Oct 2026) pushed by hand
   3. clone the public repo; rsync --ignore-existing its data/
      into docs/ace/data/ (previous payloads and manifests)
   4. tn_hydrate.py: current year's store.json, registry.json,
      style.json from the live site (kept only when newer)
   5. tn_fetch.py --tour atp --refresh-current --budget 300      ≤ 15 min
        ▲ site.api.espn.com (day scoreboards, rankings)
        ▲ www.tennis-data.co.uk (current workbook, conditional GET)
   6. tn_fetch.py --tour wta --refresh-current --budget 400      ≤ 15 min
        ▲ ESPN, api.wtatennis.com (calendar, matches, draws, stats, ranking), tennis-data
   7. build_ace.py --match-page-years 2                           ≤ 30 min
        ▲ Kalshi, Polymarket (match prices, futures)
   8. prune matches/ older than the previous year
   9. rsync --delete docs/ace/ ──► deploy key (ACE_DEPLOY_KEY)
                                         │
                                         ▼
                        ┌───────────────────────────────────────┐
                        │ pchattani/the-quant-ace (public;      │
                        │ named by the ACE_REPO variable)       │
                        └──────────────────┬────────────────────┘
                                           ▼
                GitHub Pages: https://pchattani.github.io/the-quant-ace/
```

Why it is shaped this way, and where it differs from the sister sites:

- **Three free sources, each for what only it has.** tennis-data.co.uk has every
  tour-level result since 2000 (ATP) and 2007 (WTA) with closing odds but no
  tiebreak points, seeds or live state; ESPN has live state, tiebreak points and
  qualifying but no statistics, no server and no ATP bracket; the WTA API has draws
  and per-match statistics, for the WTA only and not at the Slams. All three answer
  GitHub's runners, so CI fetches for itself (no local scheduled task, as on the
  F1 and basketball sites). Why nothing else: [DATA_PIPELINE.md](DATA_PIPELINE.md)
  section 2.6.
- **CI commits nothing.** As on the basketball site, `permissions: contents: read`.
  The current year's store, the registry and the style tables are taken from the
  deployed site at the start of each run (step 4), updated and deployed again, so the
  public site is the store of record for the current year.
- **Completed years are committed by hand**, once, after the season
  (`.gitignore` un-ignores `docs/ace/data/*/*/store.json` and the per-tour
  `registry.json`, `style.json` and `calibration.json`).
- **The fitted constants are committed.** `oddsmarkets/tennis/models/fitted/` holds
  the Elo constants, the serve/return constants (and a frozen fit), and the blend
  weights; CI never tunes or backtests. The serve/return fits themselves are cheap
  and are redone in CI from the stores (cached in `data/tennis/cache`, carried by the
  Actions cache).
- **Match pages are pruned.** A match page is about 4–5 KB, about 10 MB a tour and
  year; the public site keeps them for the current and the previous year.
- **Private engine, public site**, as for the other three sites: `docs/ace/` is
  rsynced (`--delete`, excluding `raw/` and `*.tmp`) into `pchattani/the-quant-ace`.
  Without `ACE_REPO` and `ACE_DEPLOY_KEY` the workflow builds and exits with "build
  only, no deploy".

---

## 4. Repository map

Only the tennis parts; [the football ARCHITECTURE.md](../ARCHITECTURE.md) maps the
rest.

```
oddsmarkets/tennis/
├── CONTRACT.md                 data and model interfaces (the builders' contract)
├── PAYLOADS.md                 every payload under docs/ace/data/ and the front-end contract
├── canon.py                    tours, levels, surfaces, rounds; tournament ids, levels, draw sizes, best-of and
│                               deciding-set rules by event and year; ranking-points tables; name folding and
│                               "Surname I." parsing; Registry (the identity table)
├── store.py                    year stores: load (redirects applied) / save (atomic) / event_for / merge_record /
│                               finalize_events / reconstruct_draw / fill_from_history
├── overrides.json              hard identity cases per tour (names, ESPN profiles with the wrong name, merges)
├── sources/
│   ├── _client.py              paced client (0.5 s, 4 attempts, budget, never raises; BudgetExhausted)
│   ├── tennisdata.py           link page with the hidden prefix, yearly workbooks, rows → source records
│   ├── espn.py                 day and season scoreboards, rankings → source records
│   ├── wta.py                  calendar, matches, per-match stats, draws, ranking (raw answers cached)
│   ├── charting.py             Match Charting Project files, shot-code parser, per-player style tables
│   └── markets.py              Kalshi and Polymarket match prices and futures → pids and store matches
├── models/
│   ├── _io.py                  data and cache roots, MATCH loader, folding, JSON cache keyed on inputs
│   ├── _points.py              ranking points by level and round for the simulators (canon first)
│   ├── elo.py                  surface Elo, fitted constants (fitted/elo_params_<tour>.json)
│   ├── serve_return.py         exact set-score likelihood, penalised serve/return fit, WTA point layer,
│   │                           validation against real stats, tuning, export
│   ├── bt.py                   time-decayed Bradley-Terry (a cross-check; not used by the build)
│   ├── match_chain.py          exact point → game → tiebreak → set → match chain, LiveTable, dispersion mixture
│   ├── predict.py              Elo + serve/return blend priced through the chain (fitted/predict_<tour>.json)
│   ├── live.py                 game-by-game win-probability path, leverage, excitement, comeback
│   ├── tournament_sim.py       knockout and round-robin Monte Carlo with results fixed
│   ├── season_sim.py           rest-of-season simulation: Race, Finals qualification, year-end No. 1
│   ├── backtest.py             walk-forward backtest, distribution checks, tournament checkpoints, validation
│   ├── synthetic.py            point-by-point synthetic matches with planted strengths (tests)
│   └── fitted/                 committed constants and fits (both tours)
└── analytics/
    ├── __init__.py             roots, rounding, percentiles, TourData (memoised stores, Elo, serve/return fits,
    │                           prediction contexts), head to head
    ├── players.py              catalogue (138 metrics), careers, Elo and rank paths, h2h lists
    ├── events.py               calendar, tournament pages, draw difficulty, upsets, awards, history
    ├── matches.py              match cards, the match centre, the schedule, predictions at month checkpoints
    ├── rankings.py             official, Elo, Race, points to defend; elo.json
    ├── race.py                 race.json from the season simulation and the markets
    ├── site.py                 players_index, lab, markets.json, model.json, the index entry
    ├── value.py                the Value section: model rating, breakout model (walk-forward), luck, market v model
    └── glossary.py             glossary.json
oddsmarkets/common/             sport-neutral helpers shared with the other sites (de-vig, prediction-market
                                quotes, Plackett-Luce / Bradley-Terry)
scripts/
├── tn_fetch.py                 ESPN, WTA API, tennis-data → stores; resumable; --refresh-current, --report
├── tn_charting.py              Match Charting Project → docs/ace/data/<tour>/style.json
├── tn_fit.py                   Elo and serve/return constants; --backtest for the blend and calibration.json
├── tn_hydrate.py               CI: current year's store, registry and style table from the live site
├── tn_bio.py                   dates of birth (ESPN core athlete API) → docs/ace/data/<tour>/bio.json
├── _tn_backtest_c.py           a temporary driver for the backtest (builder C)
├── build_ace.py                every payload under docs/ace/data/
└── setup_public_site.py        one-time public repo, deploy key, secret, variable, Pages (--site ace)
tests/tennis/                   pytest, offline: 156 test functions in 8 files, recorded fixtures in fixtures/
docs/
├── ace/                        The Quant Ace: index.html, assets/{base.css, ace.css, pages.css, pages-f.css, js/},
│                               data/ (stores, registries, style tables, payloads)
└── tennis/                     these documents (not published)
.github/workflows/update_ace.yml   hourly (:27) hydrate, fetch, build, prune, deploy
data/tennis/                    git-ignored: td/ (workbooks), wta/ (raw API answers), charting/ (CSVs), cache/
logs/                           git-ignored: tn_backfill_<tour>.log, tn_fetch_<tour>.log, tn_charting_<tour>.log
```

---

## 5. Key design decisions

**One store per tour and year is the single source of truth.** Everything the
sources hold about a year's events, players and matches is merged into
`docs/ace/data/<tour>/<year>/store.json`, one MATCH per real match whichever sources
saw it (tennis-data owns the result, ranks and odds; ESPN and the WTA add tiebreak
points, times and live state; the WTA owns statistics and duration). Fetchers write
it; the build only reads it. See [DATA_PIPELINE.md](DATA_PIPELINE.md) section 6.

**One identity registry per tour.** `docs/ace/data/<tour>/registry.json` links
tennis-data's "Sinner J.", ESPN athletes, WTA ids and charting names to one pid
(ESPN id when known, else `x:<slug>`; an `x:` player later linked to ESPN is
renamed and redirected). Every store is loaded through the registry's redirects.
Resolution runs per year in a fixed order (ESPN, WTA, tennis-data against the
event's full-name field, charting) so abbreviated names meet full names first.

**Serve and return are inferred from scores, and the inference is exact.** There is
no point-level ATP data; the serve/return model scores every observed set exactly
(a dynamic programme over games and tiebreak points, the first server mixed out),
fits hold strengths by penalised likelihood, and resolves the likelihood's mirror
mode. On the WTA, real statistics add binomial terms and calibrate the displayed
numbers. See [MODELS.md](MODELS.md) section 3.

**Everything is priced through one exact chain.** The match price blends Elo and the
serve/return chain on the log-odds scale, then moves the serve-point edge until the
chain reproduces the blend, so set scores, total games, handicaps, tiebreaks, live
probabilities and draw simulations all agree with the headline number.

**Walk-forward where it matters.** A finished match's pre-match line on its page uses
the Elo just before the match and the serve/return fit through the day before its
month began (`analytics/matches.checkpoint`). The backtest refits serve/return every
30 days, fits the blend for year Y on earlier years only, and runs Elo sequentially
(its constants, fitted on 2005–2019, are the in-sample part, and the backtest says
so).

**The models degrade instead of failing.** Elo falls back to `DEFAULT_PARAMS`, the
blend to `DEFAULT_BLEND`, the serve level to `BASE_SPW` when no serve/return model is
available, the build's serve/return fit to the committed one; every build step is
wrapped (`Build.step`), and a payload that cannot be built is written as
`{"ok": false, "reason": ...}`.

**Full and light years, and manifests.** The current year is built in full
(predictions with distributions, tournament simulations, the season simulation,
markets, the index entry); every other year light, and skipped when its inputs'
signature is unchanged. Each tour's `manifest.json` holds payload hashes (an
unchanged payload is not rewritten) and match-page signatures.

**Payloads are JSON; the front-end is hand-written static JS.** No template engine,
no bundler: `index.html` and seventeen scripts under `assets/js/` are shipped
verbatim; Plotly 2.27 loads from cdn.plot.ly. The look is the sister sites':
`assets/base.css` is copied from `docs/site/assets/style.css` on every build.

**The metric catalogue drives the front-end.** `METRICS` in `analytics/players.py`
is emitted with the payloads, with each metric's label, group, format, direction,
scope (`all`, `wta_stats`, `charted`) and description; the player pages, the lab and
compare render from it, and `glossary.json` covers every key (a test checks it).

**Caches are keyed on inputs.** Elo, the serve/return fits (per season end, per month
checkpoint, per backtest refit), the WTA validation and the backtest are cached under
`data/tennis/cache/` (env `ACE_CACHE`), keyed on the matches they saw plus a version
string, so a new result in the current year does not refit past years.

**Licences are carried with the data.** The Match Charting Project is CC BY-NC-SA
4.0: `style.json` carries the licence, attribution and source in `_meta`, the derived
style tables are shared alike, the raw files are never committed, and the disclaimer
and footer credit it and tennis-data.co.uk.

---

## 6. Tech stack

| Layer | What |
|---|---|
| Language | Python ≥ 3.11; CI uses 3.11 |
| Environment | uv (`pyproject.toml`, `uv.lock`), shared with the other sites; `openpyxl` (2013+ workbooks) and `xlrd` (2000–2012 `.xls`) added for tennis |
| Numerics | numpy, scipy (L-BFGS-B, Nelder-Mead, sparse matrices), pandas (workbook reading) |
| HTTP | `requests` through `sources/_client.py`; the shared prediction-market client for Kalshi and Polymarket; `urllib` in `tn_hydrate.py` |
| Tests | pytest, `tests/tennis/` (offline; recorded ESPN, WTA, tennis-data and charting fixtures, synthetic matches) |
| Browser | seventeen plain scripts (no bundler), Plotly 2.27 from cdn.plot.ly |
| CI / hosting | GitHub Actions (`update_ace.yml`), an Actions cache for model caches, GitHub Pages from the public repo |

---

## 7. Getting started

From the repository root:

```bash
uv sync --group dev

# Tennis tests: offline
uv run --group dev pytest tests/tennis

# Build every payload from the stores on disk
uv run python scripts/build_ace.py                                   # current year full, the rest light
uv run python scripts/build_ace.py --quick --no-market --no-light    # fast local check
uv run python scripts/build_ace.py --tours wta --years 2026          # one tour
```

A fresh clone has every completed year's store, both registries and style tables and
both `calibration.json` (committed 1 October 2026) but not the current year's store.
To work on the current year without fetching, `python scripts/tn_hydrate.py` copies
it (with the registry and style tables) from the live site. Preview:

```bash
cd docs/ace
python -m http.server 8898          # then open http://localhost:8898
```

A cold build refits Elo and the serve/return model per year from the stores (the
first full build takes a while; later builds hit `data/tennis/cache/`). The
Calibration page reads the committed `calibration.json`; rebuild it with
`python scripts/tn_fit.py --tours atp --no-elo --no-sr --backtest`
([RUNBOOK.md](RUNBOOK.md) section 4).

Do not run a second `tn_fetch.py` for a tour whose backfill is running: both write
the same store and registry files.

---

## 8. Conventions

- **Under `docs/ace/data/`, only completed years' `store.json` and each tour's
  `registry.json`, `style.json` and `calibration.json` are committed**
  (`.gitignore`). Everything else is build output. The `.gitignore` pattern also
  un-ignores the current year's store, so add stores explicitly by path.
- **Years are calendar years**, tours are lower case, ids are strings. Player ids
  are ESPN ids or `x:<slug>`; file names replace `:` with `_`
  (`players/x_alena-kovackova.json`) because `x:` would name an NTFS alternate data
  stream on Windows.
- **Matches are oriented winner-first** once finished (`p1` = winner, sets from p1's
  view); the backtest orients each match at random by a hash of its id.
- **Surfaces** `hard`, `clay`, `grass`, `carpet` in the stores; the models fold
  carpet into hard and keep `indoor` as a separate flag.
- **Levels** `slam`, `finals`, `m1000`, `500`, `250`, `other` are tour level;
  `ch` (Challenger, WTA 125) and `q` (qualifying) feed the ratings only.
- **Numbers are rounded at the payload boundary** (`PAYLOADS.md`): probabilities 4
  decimals, ratings 1, rates 3; fmt "pct" values are 0–1 fractions. NaN and infinity
  become `null` (`_clean` in `build_ace.py`).
- **Commits go on `main`.** CI never pushes to this repository.
- **Person pronouns.** Some docstrings say "his" or "her"; new text should say
  "they".

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **store** | `docs/ace/data/<tour>/<year>/store.json`: one tour-year's players, events and matches, merged from the sources. |
| **MATCH** | One singles match in a store (`store.build_match`); fields in [DATA_PIPELINE.md](DATA_PIPELINE.md) section 6.1. |
| **source match record (SMR)** | What a source parser hands to `tn_fetch` (`canon.SMR_DOC`): sides "a"/"b" with names and source ids, before identity resolution. |
| **registry** | `docs/ace/data/<tour>/registry.json`: every player's names, aliases, ESPN and WTA ids, and the redirects of renamed pids. |
| **pid** | A canonical player id: ESPN athlete id, else `x:<slug>`. |
| **tid / event id** | A canonical tournament slug (`indian-wells`) / `<tid>-<year>`. |
| **DRAW** | An event's round-1 bracket `[[slot, pid, seed, entry]]`, `source` "wta" (the WTA's draw) or "reconstructed" (rebuilt from results). |
| **style table** | `docs/ace/data/<tour>/style.json`: per-player Match Charting Project profiles (CC BY-NC-SA 4.0). |
| **hold / chain-scale hold** | P(server holds). The chain-scale hold is the one whose i.i.d. point chain reproduces scorelines (used for pricing); the displayed hold adds the WTA's calibration offset `k_hold`. |
| **s, r** | A player's serve and return strength on the hold model's logit scale (plus per-surface deviations). |
| **mirror mode** | The second maximum of the score-only likelihood, (−μ, r, s); the fit keeps μ > 0. |
| **k_hold, k_spw** | The WTA point layer's two tour-level offsets linking chain-scale holds to real holds and serve points won. |
| **the chain** | `models/match_chain.py`: the exact point → game → tiebreak → set → match Markov chain. |
| **blend** | logit p = w_elo · logit(Elo p) + w_sr · logit(serve/return p) (`models/predict.py`). |
| **σ (dispersion)** | The standard deviation of a per-match serve-point edge averaged over for distributions (0.04 fitted). |
| **checkpoint** | The first of a finished match's month: its pre-match serve/return fit runs through the day before. |
| **full / light year** | Built with predictions, simulations, markets and the index entry (the current year), or without them. |
| **manifest** | `data/<T>/manifest.json`: payload hashes, match-page signatures and light-year signatures. |
| **hydrate** | CI's copy of the current year's store, registry and style table from the live site (`tn_hydrate.py`). |
| **thin market** | A field market with too few runners accounted for or an implied total outside 0.8–1.3; not published. |
| **Builders A–F** | The work packages in `CONTRACT.md` and `PAYLOADS.md`. |
