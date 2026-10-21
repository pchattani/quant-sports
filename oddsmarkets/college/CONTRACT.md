# The Quant Campus: data and model contract

College sports on the family's design kit: **NCAA FBS football (`cfb`)**, **Division I men's basketball (`mbb`)**
and **Division I women's basketball (`wbb`)**. Every builder codes to these shapes; the payloads the site reads are
in `PAYLOADS.md`. Written 19 Oct 2026 before the build started; each section ends with an **As built** note that its
builder fills in.

Conventions (`oddsmarkets/college/canon.py`): seasons are ESPN's `season.year` (cfb = the year the season starts,
2026 = the 2026 season whose CFP final is in January 2027; basketball = the year it ends, 2026-27 = 2027). All ids
are ESPN ids as strings. Times are UTC ISO strings (`2026-10-18T19:30:00Z`). Probabilities 4 dp, ratings 2 dp.

Rules for every builder:
- No new dependencies: numpy, scipy, pandas, requests (lightgbm exists but prefer closed forms). No network in tests
  (`tests/college/`, fixtures under `tests/college/fixtures/`). Tests run with `uv run --frozen pytest tests/college -q`.
- **CPU: at most 4 cores for the whole machine**, shared by every builder and the backfill. Set
  `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1` for anything heavy, no multiprocessing pools wider
  than 2, vectorise with numpy instead. Network-bound fetchers are fine to run concurrently.
- **Data terms (the user's standing rule):** a source whose terms forbid reuse is left out and the page says so.
  No Sports-Reference, KenPom, Barttorvik, 247Sports, On3, Rivals, Massey or NCAA.com scraping. ESPN public JSON (as
  every sister site), Kalshi and Polymarket public APIs are fine. The College Football Data API (CFBD) needs a free
  key: the code is ready for one (`CFBD_API_KEY`), but none is configured and none may be added.
- No git write commands; the lead commits. Do not touch other sites' code (football, nfl, baseball, tennis, hockey,
  f1, basketball packages and their scripts): import from them freely, never edit them.
- Front end: no `?.` or `??`; parse every JS file with esprima
  (`uv run --quiet --with esprima --no-project python -c "import esprima,sys; esprima.parseScript(open(sys.argv[1],encoding='utf-8').read())" FILE`).

Ownership:

| Area | Builder | Files |
|---|---|---|
| Data: ESPN source, stores, fetch/backfill, rankings, rosters, odds, markets, CFBD stub | **A** | `oddsmarkets/college/canon.py` (extends), `sources/espn.py`, `sources/markets.py`, `sources/cfbd.py`, `store.py`, `scripts/cc_fetch.py`, `scripts/cc_hydrate.py`, `tests/college/test_data_*.py` |
| Football models and payloads | **B** | `oddsmarkets/college/football/**`, `scripts/cc_build_cfb.py` (optional CLI), `tests/college/test_cfb_*.py` |
| Basketball models and payloads (both levels) | **C** | `oddsmarkets/college/hoops/**`, `tests/college/test_hoops_*.py` |
| Site, build orchestrator, kit, home page | **D** | `docs/campus/**`, `scripts/build_campus.py`, `oddsmarkets/college/site.py` (site-wide payloads), `docs/_design/*` (college entry only), `scripts/build_home.py` (college only), `tests/college/test_site_*.py` |
| Contract, CI/pipeline, integration | lead | `CONTRACT.md`, `PAYLOADS.md`, `scripts/gen_ci_workflows.py`, `scripts/ci_site.py`, `scripts/local_sites.py`, `scripts/export_public.py`, `scripts/push_seed.py` |

## 0. Where things live

| What | Path | In git? | On CI |
|---|---|---|---|
| Season stores (inputs) | `data/college/stores/<L>/<S>.json.gz` | no | Actions cache (content key) + `seed-campus` branch |
| CFB plays (inputs) | `data/college/cfb/plays/<S>.json.gz` | no | same |
| Basketball play-by-play (raw, compact) | `data/college/pbp/<L>/<S>/<gid>.json.gz` | no | current season only (cache); past game pages are restored from the deployed site |
| Rosters, rankings, misc fetch state | inside the stores (`players`, `rankings`, `meta`) | no | with the stores |
| Model caches | `data/college/cache/` (env `CAMPUS_CACHE`) | no | Actions cache, daily key |
| Payloads (site) | `docs/campus/data/` (env `CAMPUS_DATA`) | no (build output) | built every run, deployed |
| Site code | `docs/campus/index.html`, `docs/campus/assets/**` | yes | |

Roots are overridable for tests: `CAMPUS_STORES` (default `data/college/stores`), `CAMPUS_RAW` (default `data/college`),
`CAMPUS_CACHE`, `CAMPUS_DATA`. `oddsmarkets/college/store.py` exposes `paths()` returning them.

Stores are gzipped JSON (`gzip.open(..., "wt", encoding="utf-8")`, compact separators); write atomically
(temp file + `os.replace`).

## 1. Sources and stores (builder A)

### 1.1 ESPN (`oddsmarkets/college/sources/espn.py`)
Same client discipline as `oddsmarkets/basketball/sources/espn.py` (copy the `Client`, do not import Hardwood's
headers): paced GET (`interval`, default 0.5 s), retry with back-off on 429/5xx, `budget` with `BudgetExhausted`,
never raises on a bad game. User-Agent names The Quant Campus.

Endpoints (probed 19 Oct 2026; base `https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}`):
- scoreboard: basketball `?dates=YYYYMMDD&groups=50&limit=500` (one day; competitors carry `statistics`: fgm/fga,
  3pm/3pa, ftm/fta, rebounds, assists, points, `curatedRank`, `records`, team `conferenceId`; postseason events carry
  `notes[].headline` such as "Men's Basketball Championship - South Region - 2nd Round" and `tournamentId`);
  football `?dates=<YEAR>&seasontype=2|3&week=N&groups=80&limit=500` (weeks from `leagues[0].calendar`; bowls and
  CFP are seasontype 3 with headlines such as "College Football Playoff First Round ...", "... Bowl").
- summary `?event=ID`: box (basketball keys: minutes, points, FG, 3PT, FT, rebounds, assists, turnovers, steals,
  blocks, OREB, DREB, fouls — no plus-minus), `plays` + `winprobability` (basketball, recent seasons), football
  `drives.previous[].plays` (down, distance, yardLine, yardsToEndzone, statYardage, type, text, scoring, start/end),
  `winprobability`, `pickcenter` (older seasons: consensus/numberfire/teamrankings), `predictor`, `injuries`.
- core odds `https://sports.core.api.espn.com/v2/sports/{sport}/leagues/{league}/events/{id}/competitions/{id}/odds`:
  recent seasons one sportsbook (ESPN BET) with `open`/`close`/`current` blocks; around 2013-2016 several books
  (5Dimes, BetOnline, Bovada ...) with a single line; none before (2005 probes: 0 items). **This is the closing line
  the backtests use** (the `close` block, else the book's single `spread`/`overUnder`; prefer ESPN BET / DraftKings,
  else the median of books). Measure coverage per season and record it.
- rankings (AP, Coaches, CFP; weekly history), teams by group, conferences, standings
  (`https://site.api.espn.com/apis/v2/sports/{sport}/{league}/standings?season=Y&group=..` or core equivalents),
  rosters (`teams/ID/roster`, with `experience` = class year; probe `?season=Y` for history), injuries where present.

Required functions (others as needed): `Client`, `BudgetExhausted`, `scoreboard_day(c, level, yyyymmdd)`,
`scoreboard_week(c, season, seasontype, week)` (cfb), `calendar(c, level, season)`, `summary(c, level, gid)`,
`core_odds(c, level, gid)`, `rankings(c, level, season)` (all weeks), `teams(c, level, season=None)`,
`conferences(c, level, season)`, `roster(c, level, tid, season=None)`, `injuries(c, level)`; parsers
`compact_event(level, ev)`, `compact_game(level, raw_summary)`, `parse_odds(raw_core)`, `compact_plays_cfb(raw)`,
`compact_pbp_bb(raw)`.

### 1.2 Store (`oddsmarkets/college/store.py`): `data/college/stores/<L>/<S>.json.gz`
```
{"level","season","updated_at",
 "conferences": {cid: {"name","short","abbr","fbs"|"d1": bool,"divisions": {did: name}}},   # divisions: {} when none that season
 "teams": {tid: {"name","short","abbr","location","nickname","colour":"#rrggbb"|null,"alt_colour","conference": cid|null,
                 "member": bool,              # FBS (cfb) / Division I (mbb, wbb) member that season
                 "division": did|null,        # (A) the season's division where the conference had divisions
                 "venue": {"name","city","state"}|null}},   # (A) team venue: null (ESPN gives only an id); game venues are in GAME
 "players": {pid: {"name","short","pos","jersey","class": "FR|SO|JR|SR|GR"|null,"height_in","weight_lb",
                   "hometown"|null,"teams":[tid...]}},        # from box scores and rosters
 "rosters": {tid: [pid...]} ,                                 # the roster as fetched (current season: as of fetch)
 "games": {gid: GAME},
 "rankings": {"ap": {week: [[rank, tid, points, first_votes]]}, "coaches": {...}, "cfp": {...},
              "cfp_seeds": {week: [[seed, tid, 0, 0]]}},                 # (A) cfb 2024 on: ESPN's "CFP Seedings" ranking
              # week labels: regular-season weeks as ESPN numbers them ("1".."16"), "pre" (preseason poll),
              # "final" (last postseason poll), "post<N>" (other postseason polls); points null for the CFP
 "meta": {"fetched": {gid: iso}, "odds": {gid: iso}, "calendar": [...], "complete_through": "YYYY-MM-DD",
          "odds_coverage": {"games","with_close","with_any"}, "version",
          # (A) fetch state: "scanned" {day|"<stype>-<week>": iso}, "standings_at", "rankings_at", "rosters_at",
          # "rosters_full", "rosters_hist_at", "odds_none" (iso: a 40-game sample had no lines; season skipped),
          # "injuries" {tid: [[pid, status, detail, date]]} (current season, today's list), "injuries_at"
          }}
```
GAME (both sports):
```
{"id","date","status":"pre|in|post|postponed|canceled","stype","round": str|null,"region": str|null,"note": headline|null,
 "week": int|null (cfb), "neutral": bool, "conf_game": bool, "home","away","hs","as","periods",
 "line": {"home":[...],"away":[...]}, "ranks": {"home": int|null,"away": int|null},      # AP rank (curatedRank) at game time
                                          # (A) football postseason: ESPN shows the CFP ranking here; NCAA tournament games: null
 "seeds": {"home": int|null,"away": int|null} | null,                                    # tournament seeds when known
                                          # (A) ncaa: ESPN's curatedRank in tournament games IS the seed (2002 on);
                                          # cfp: ESPN CFP seedings (2024 on), else the last CFP ranking's top 4
 "team_stats": {tid: {...}},              # from the scoreboard; basketball keys fgm fga tpm tpa ftm fta reb ast pts
 "box": {} | BOX,                         # from the summary (see below); {} until fetched
 "odds": {"provider","spread_home","total","ml_home","ml_away","open_spread_home","open_total","n_books","source": "core|pickcenter|scoreboard",
          "has_close_block": bool} | null,  # (A) provider "median" = median of the books (2013-2016 era); has_close_block = the
                                            # numbers are the book's explicit close (DraftKings era), else its last line
 "injuries": {tid: [[pid, status, detail]]},   # (A) only on games fetched before they finished (summary injuries = today's)
 "predictor": {"home": p} | null,         # ESPN matchup predictor, only as fetched before the game
 "venue": {"name","city","state"}|null, "attendance": int|null, "has_pbp": bool, "summary": bool}
```
`spread_home` is the home team's line (negative = home favoured), always. `stype`/`round`/`region` come from
`canon.classify(level, season_type, headline)` (A writes it): football rounds "First Round", "Quarterfinal",
"Semifinal", "National Championship" for `cfp`; basketball `ncaa` rounds "First Four", "Round of 64", "Round of 32",
"Sweet 16", "Elite 8", "Final Four", "National Championship"; region names as ESPN gives them.

Basketball BOX: `{tid: {"players": [[pid, starter, sec, pts, fgm, fga, tpm, tpa, ftm, fta, oreb, dreb, ast, stl, blk, tov, pf]],
"dnp": [[pid, reason]], "team": {"fgm","fga","tpm","tpa","ftm","fta","oreb","dreb","ast","stl","blk","tov","team_tov","pf",
"pts_paint","pts_fastbreak","pts_off_tov","largest_lead"}}}` (`BOX_COLS` in `store.py`; the Hardwood rules for team
sums and turnovers apply).

Football BOX: `{tid: {"team": {"first_downs","total_yards","pass_yards","rush_yards","rush_att","pass_att","pass_cmp",
"turnovers","fumbles_lost","ints_thrown","penalties","penalty_yards","third_conv","third_att","fourth_conv","fourth_att",
"possession_s"}, "players": {category: {"cols": [...], "rows": [[pid, ...]]}}}}` with categories passing, rushing,
receiving, fumbles, defensive, interceptions, kickReturns, puntReturns, kicking, punting (cols = ESPN keys,
normalised to snake_case; numbers parsed, "C/ATT" split into cmp and att, "FG" into fgm and fga).

CFB plays `data/college/cfb/plays/<S>.json.gz`:
`{"season","cols": [...],"types": {type_id: text},"games": {gid: {"drives": [[idx, team, period, clock_s, start_yte, n_plays, yards, result, is_score]], "plays": [[...cols]]}}}`
with cols `seq, drive, period, clock_s, offense, defense, type_id, down, distance, yte, yards, end_down, end_distance,
end_yte, scoring, home_score, away_score, turnover, penalty, wp_home, text` (`yte` = yards to the end zone at the snap;
`wp_home` = ESPN's win probability after the play where given, else null). Kickoffs, punts, penalties, timeouts and
period ends are kept (the EP model needs them); `text` kept (player attribution parses it).

Basketball pbp `data/college/pbp/<L>/<S>/<gid>.json.gz`: Hardwood's `compact_pbp` row format (CONTRACT section 1 of
oddsmarkets/basketball) with college halves (20-minute halves men; women four 10-minute quarters since 2016,
two halves before; overtime 5 minutes): `canon.period_len(level, period, season)` and `canon.game_t(...)`.

### 1.3 Fetch (`scripts/cc_fetch.py`)
`--level cfb|mbb|wbb --seasons ... | --refresh-current --budget N --interval 0.5 --phases scoreboard,summary,odds,rankings,rosters,injuries --backfill`.
Resumable (meta.fetched / meta.odds), newest season first, saves every few hundred calls. `--refresh-current` = the
current season's recent and coming days (scores, summaries of games finished since the last run, odds of games in
the next 7 days and close-of-game refetch of finished ones, rankings, injuries, rosters weekly) within the budget.
`scripts/cc_hydrate.py`: CI hydrate (nothing to do if the cache restored the stores; otherwise report).

### 1.4 Markets (`oddsmarkets/college/sources/markets.py`)
On `oddsmarkets/basketball/sources/markets.py`: Kalshi and Polymarket college markets — national champion (CFP,
NCAA men's and women's), conference champions, Heisman if listed, March Madness (champion, Final Four, region winners),
per-game moneylines — mapped to ESPN team ids. `futures(level, season) -> {"champion": TITLE, "conference": {cid: TITLE},
"playoff": {"probs": {tid: p}}, "final_four": ..., "heisman": TITLE|None, ...}` and `game_prices(level, date)`.
TITLE = Hardwood's (`probs`, `sources`, `by_source`, `available`, `implied_total`). Unreachable = `None`, never raise.

### 1.5 CFBD (`oddsmarkets/college/sources/cfbd.py`)
A client that does nothing without `CFBD_API_KEY` (returns `None` and logs once). Documented in its docstring: what
each endpoint would add (recruiting/talent composites, returning production, transfer portal entries, historical
lines with opening and closing from several books back to 2013, advanced box/PPA, weather), the terms to check for
each before use (247Sports recruiting data in particular), and where the models would plug it in.

### As built (builder A, 19 Oct 2026)

Files: `canon.py` (adds `classify`, `ncaa_rounds`, `ncaa_regions`, `fix_cfb_postseason`, `BCS_TITLE_GAMES`,
`period_len/period_start/game_t/reg_periods`, `pool`, `class_year`), `store.py` (`paths`, `load/save` atomic gz,
`BOX_COLS` 17 columns, `TEAM_BOX_KEYS`, `FB_TEAM_KEYS`, `PLAY_COLS`, `DRIVE_COLS`, `PBP_COLS`, merge helpers,
`coverage`), `sources/espn.py`, `sources/markets.py`, `sources/cfbd.py`, `scripts/cc_fetch.py` (`--backfill`,
`--refresh-current`, `--phases`, `--coverage`), `scripts/cc_hydrate.py`; tests `tests/college/test_data_*.py`
(35 tests, fixtures trimmed from real answers). Fields added to 1.2 are marked "(A)" above.

**Stores hold:** every game ESPN lists at groups=80 (FBS games, FCS opponents included, `member` false) or groups=50
(D-I games, non-D-I opponents included) for cfb 2001-2026 and mbb/wbb 2002-2027 (2027 = the 2026-27 schedule as
published); per-season conferences and membership from ESPN standings (realignment correct per season; divisions);
AP and Coaches weekly polls for every season (cfb 2001 on, basketball 2002 on), CFP weekly rankings 2014 on and
ESPN's CFP seedings 2024 on; current rosters (class, height, weight, hometown, position; ESPN's roster endpoint needs
`limit=500` or it stops at 100 players); summaries, box scores, plays / pbp and odds filling in by the backfill.

**What ESPN lacks or gets wrong (handled):**
- `curatedRank` in NCAA tournament games is the SEED (men 2002 on; women 2003 on, not 2002); in football postseason
  games it is the CFP ranking. Men's 2002-2010 opening-round games and a few early games lack tournament tags (stype
  `post`); `canon.ncaa_rounds` sets rounds from the bracket (ESPN's "1st Round" meant the First Four in 2011-2015).
- Women's headlines before 2022 name first-weekend host sites as regions: `canon.ncaa_regions` maps them to the four
  regionals. 2024 on the women's regions are "Regional 1..4".
- 4-team CFP semifinals 2014-2023 are often labelled only as the bowl: `fix_cfb_postseason` marks the finalists'
  previous games (seeds = the last weekly CFP top four); BCS title games 2001-2005 by finalist pair; 2001-2002 have no
  headlines at all (conference title games inferred: December, neutral, same conference).
- Team `conferenceId` on scoreboards is often today's conference (Utah/TCU listed in the Big 12 in 2005): standings
  decide membership; `conf_game` is recomputed from the season's membership.
- No historical rosters on the site endpoint (`?season=Y` answers empty): past rosters come as athlete ids from the
  core season roster (backfill step 6); class year for a past season needs one core call per athlete
  (`espn.athlete_season`, not run by default).
- Injuries: the college football feed holds stale 2020 items (dropped, > 60 days); basketball's is empty in October.
- Odds: no lines anywhere before cfb 2012 / mbb 2013 / wbb 2020. cfb 2012-2013 and mbb 2013 only "consensus"
  (used, provider "consensus"); 2014-2016 five to nine offshore books, one line each (median used); 2017-2023 several
  US books (Caesars, DraftKings id 40, MGM, Unibet...), mostly without close blocks (median of the last lines);
  ESPN BET (id 58) with open/close 2023-2025, DraftKings (id 100) with open/close 2026; "... - Live Odds" items are
  in-game and ignored. Women's lines are partial even now (about a third of games in 2026, sampled).
  Sign check v results: cfb 2025 corr(spread_home, margin) = -0.73, mean(margin + spread) = +0.9.

**First season with lines (core odds, 12-game samples per season):** cfb 2012 (consensus; books from 2014);
mbb 2013 (consensus; books 2014); wbb 2020-2021 (a few games), regular from 2023.

**Coverage at the time of writing** (`python scripts/cc_fetch.py --level L --coverage` prints the live table):
scoreboards complete for every season of all three levels (cfb 700-950 games a season; basketball 4,800-6,400);
polls every season; CFP rankings 2014-2025; NCAA seeds in 63-67 games every season but wbb 2002 and 2020 (no
tournament); summaries + plays + odds done for cfb 2026 (510 finished games) and 2025 (934 games, 932 with plays,
924 with a close), basketball 2026 in progress. The backfill continues detached (`data/college/backfill_start.ps1`;
order in `cc_fetch.py` docstring): cfb about 15 minutes a season (all seasons by about 21:00 on 19 Oct), mbb about
40 minutes a season for 2026-2022, then older odds and summaries (about 20 hours in all), wbb similar.

## 2. Football models (builder B): `oddsmarkets/college/football/`

Reuse the NFL site's model designs (`oddsmarkets/nfl/models/`: ep.py, wp.py, team_strength.py, game.py,
season_sim.py, backtest.py, player_value.py; `oddsmarkets/nfl/analytics/*` for payload shapes) — import helpers where
they are sport-neutral, re-implement where college differs. Required:
- **EP / EPA / success rate** from ESPN plays (fitted on college plays, all seasons with plays; garbage time flagged by
  win probability or score margin and excluded from team ratings).
- **Team ratings**: opponent-adjusted offense/defense EPA per play and success rate (ridge on play-level or game-level
  data with home-field), a points-based rating (opponent-adjusted margin, recency-weighted, garbage-time-capped), and a
  predictive blend (weights fitted walk-forward). Preseason prior = last season's rating regressed toward the
  conference mean; returning production computed from our own box data is allowed (label it, and keep it out of the
  backtest unless it is computed from information available before week 1). Non-FBS opponents: individually rated with
  a strong shrink toward an FCS prior.
- **Game model**: `predict(home, away, date, ctx) -> {"p_home","margin","sd","total","spread_fair","detail"}` (neutral
  sites, rest, travel distance if cheap). **Walk-forward backtest v closing lines** (ESPN core odds): margin MAE/RMSE
  v the close's, ATS hit rate of the model's side v the close, Brier/log loss v the moneyline-implied (de-vigged) where
  present, per season, calibration table; also v ESPN's predictor where stored. Report honestly; no fitting on the
  test season.
- **Season sim** (`n` default 20,000, numpy): remaining regular season, conference standings (tiebreakers:
  head-to-head, then rating as the documented proxy), conference championship games (top two by conference record
  unless the conference has divisions that season), **CFP**: 12 teams, the five highest-ranked conference champions plus
  the seven highest-ranked others, seeded 1-12 straight by ranking (2025 rules; keep a per-season format table:
  4-team 2014-2023, 12-team with byes for the top four conference champions in 2024, straight seeding from 2025; flag
  2026 as "2025 rules assumed" until verified), first round on campus (5v12, 6v11, 7v10, 8v9), byes for 1-4,
  quarterfinals and semifinals neutral, final neutral. **Committee-ranking proxy**: fitted on ESPN's historical CFP
  rankings (2014-2025: final and weekly) from resume features (wins, losses, strength of schedule, our rating, record
  v ranked teams, conference champion) — out-of-sample accuracy reported (Spearman, top-12 overlap). Bowl eligibility
  (6 wins, 5-7 rules ignored), conference title odds, national title odds.
- **Players**: value currency **EPA above replacement** for QB (dropbacks + rushes), RB, WR/TE (targets parsed from play
  text matched to box names), defense and specialists from box stats (documented weights); positions from rosters.
  **Transfers**: inferred moves (same athlete id, different team from one season to the next; with value before and
  after); labelled "inferred from box scores and rosters; not the official portal". **Fantasy**: PPR / half / standard
  projections for QB/RB/WR/TE/K for the coming week (usage share x opponent), with a walk-forward backtest v naive.
- Payload writer: `oddsmarkets/college/football/build.py: build(season, out_dir, stores, *, full: bool, sims: int, markets: bool) -> dict`
  (writes the cfb payloads of PAYLOADS.md for one season; returns a summary); `build_level(out_dir, seasons, current)`
  for the per-level files (calibration, history, players careers, markets).

### As built (builder B, 21 Oct 2026)

Files: `football/data.py` (frames, md5-keyed caches, `UNRELIABLE_LINES`), `ep.py`, `ratings.py`, `game.py`, `backtest.py`
(pipeline + calibration), `committee.py`, `sim.py`, `players.py`, `fantasy.py`, `build.py`, `synthetic.py` (test world);
tests `tests/college/test_cfb_models.py`, `test_cfb_players.py` (27 tests). Methodology and every validation number:
`docs/campus/MODELS_CFB.md` (rendered on the Model page); `calibration.json` carries them for the front end.

- **Signatures** as above; `build(..., current=None)` and `build_level(..., markets=True, careers=True, sims=20000)` add
  keywords (the orchestrator filters kwargs). `build_level` runs first and computes what later season builds reuse
  (pipeline, committee fit, the current season's sim and fantasy projections, player validation) in one in-process
  context; `reset()` clears it. Current season = `canon.current_season("cfb")`, overridable by env `CAMPUS_CFB_CURRENT`.
- **Caches** `data/college/cache/cfb/*.pkl.gz` keyed by md5 of versions, parameters and input contents (store results
  and lines, plays-file bytes), never paths: `ep_fit` (12 fits, ~12 min cold), `plays_epa_<S>`, `pipeline` (~2-4 min
  cold), `committee`, `players_<S>`, `fantasy_bt_<S>`. A full cold build is about 45 minutes on one core; warm, the
  per-season builds are 30-150 s and the current season (20,000 sims, ~890 game pages) about 2-10 minutes.
- **Data findings** (for A / the lead): ESPN's 2012 "consensus" spreads fail the sign check (corr with margin 0.01 v
  -0.70..-0.75 every other season) and are excluded everywhere (cards show no market or cover for 2012); 2001-2004
  plays have no yard line (no EP/EPA before 2005); 2002 has plays for only 31 games; 2001-2003 stores have no players
  (box ids without names); ESPN play types 51 ("Pass", 2005-07) and 6 ("Pass Interception", 2008-14) are passes;
  past-season rosters mix seasons (150-190 athletes per team 2019-25), so no returning-production prior; no stored
  `predictor` on finished games, so the ESPN comparison uses the win-probability feed's value after the opening
  kickoff (2016 on); 2026 bowl games are placeholders (no teams yet), so `cfp.bowls.games` is empty until matchups
  are announced.
- **Payload additions** (no PAYLOADS field renamed): `calibration.json` adds `by_phase` (weeks 1-2 ... postseason, FBS v
  FBS, v non-FBS), `sim_detail`, `committee`, `format_table`, `players` (attribution, stability, team check), `ep`,
  `blend`, `params`; `summary.espn_predictor` holds the ESPN metrics at the top level plus `model`, `per_season`,
  `on_moneyline_games`; `value.json` adds `validation`; `fantasy.json` backtest adds `per_season[].tuning_season` and
  `seasons`; SIMTEAM adds `p_top12`, `p_auto`, `seed_mean`, `rank_mean`; `cfp.json` format adds `table`.
- **Headline validation**: v ESPN closing lines 2013-2026, 11,561 games: margin MAE 12.87 model v 12.33 close, ATS of
  the model's side 49.7% ± 0.5, Brier on moneyline games 0.1854 v 0.1786; committee proxy (leave one season out,
  2014-2025) Spearman 0.933, top-12 overlap 90.3%; CFP-field sim backtest 54 of 64 places; fantasy MAE 5.01 v naive 5.13.
- **Unverified**: the 2026 CFP format (2025 rules assumed, flagged in `format.cfp.verified=false` and the note).

## 3. Basketball models (builder C): `oddsmarkets/college/hoops/`, both levels

Reuse Hardwood (`oddsmarkets/basketball/models/ratings.py`, `game.py`, `season_sim.py`, `backtest.py`,
`analytics/value.py`, `fantasy.py`) — import where sport-neutral. Required:
- **Ratings**: opponent-adjusted offensive/defensive efficiency per 100 possessions and tempo (ridge, recency
  weighting, home court; possessions from the summary box, or FGA - OREB + TOV + 0.475 FTA; where only the scoreboard
  line exists, FGA + 0.475 FTA with a fitted season-level correction), Kalman paths; non-D1 opponents pooled with a low
  prior; preseason prior from last season regressed (returning minutes from our own box data allowed, as in 2).
- **Game model** and **walk-forward backtest v closing lines** (as in 2; plus totals v the closing total).
- **Season sim**: regular season, **conference tournaments** (per-conference formats are not in any free feed:
  generic single elimination seeded by conference record with byes to the bracket size; documented as approximate;
  actual brackets from ESPN events once scheduled), automatic bids, **selection and seeding proxy** (at-large and seed
  models fitted on past fields 2002-2026 from ESPN tournament games: the seeds are in the events; men 68 teams from
  2011, 65 2002-2010; women 68 from 2022, 64 before; First Four), **bracket sim** (S-curve regions, First Four, P(reach
  each round), upset odds per first-round line), NIT/WBIT optional. Out-of-sample selection/seed accuracy reported.
- **Players**: a box-score value (team-constrained: player shares sum to the team's opponent-adjusted margin; public
  formulas such as individual offensive rating/usage, documented), **value above replacement** per game and season,
  positions G/F/C; inferred transfers (as in 2); fantasy points projections (points leagues and 9-category ranks) with a
  walk-forward backtest v naive.
- Payload writer: `oddsmarkets/college/hoops/build.py: build(level, season, out_dir, stores, *, full, sims, markets) -> dict`
  and `build_level(level, out_dir, seasons, current)`.

### As built (builder C, 21 Oct 2026)

Files: `oddsmarkets/college/hoops/` `data.py` (season tables, possessions, `box_ok`, `clean_odds`, neutral
inference, content-keyed JSON caches), `ratings.py` (ridge efficiency + tempo, walk-forward refit every game day,
Kalman paths, carryover), `model.py` (level state, roster-turnover prior, game model), `backtest.py`, `elo.py`,
`tourney.py` (actual field, resume, selection / seed proxy, S-curve, vectorised bracket sim), `ncaa.py`
(pre-tournament fits, leave-one-season-out, tournament backtest), `sim.py` (season + generic conference tournaments +
selection + bracket), `players.py` (value, positions, transfers, units, suggestions, fantasy), `build.py` (payloads;
`python -m oddsmarkets.college.hoops.build --levels mbb,wbb`); tests `tests/college/test_hoops_*.py` +
`hoops_synth.py`. Methodology and every validation number: `docs/campus/MODELS_HOOPS.md`.

- `build(level, season, out_dir, stores, *, full, sims, markets)` writes every per-season payload for every season;
  `full` gates only the game pages (current season's finished / live games, previous season's postseason incl.
  conference tournaments; stale pages are pruned). Seasons before the previous one are "archive" seasons written
  compactly (PAYLOADS.md basketball note). `build_level(..., per_season=True)` writes calibration, history,
  markets and careers (D-I players with a game in the last two box-score seasons; stale careers pruned).
- Store facts that shaped the code: box shells exist for every game but older ones are empty or partial (men
  2002-2004 none; women 2004-2013 partial, 2014-2016 about a quarter); about 12% of men's 2018-2023 boxes miss a
  player line; ESPN BET 2023 men's lines carry the price (-110) in the spread / total fields for 304 games (dropped);
  ESPN's historical season rosters list later teams (not used for past membership); ESPN's predictor is not stored
  for any finished game (comparison null).
- Caches: `data/college/cache/hoops/{fits,walk}/` keyed on store content (sha1 of the bytes) and model versions,
  no paths. A full both-level build takes about 25 minutes on one core per level (walks 3-5 minutes per level when
  the stores change).
- Payload sizes (21 Oct 2026 build): mbb 243 MB, wbb 204 MB (budget 250 each). `write` retries `os.replace` on a
  Windows sharing lock (a reader holding a payload made one build fail once).
- `markets.json`: when `sources/markets.py` flags the pooled champion book thin (men, 21 Oct: Polymarket's overround
  gives an implied total of 1.40), the payload fills `champion.probs` from Kalshi alone, normalised, and says so in
  `champion.fallback` (builder A may want to revisit the thin rule for college futures).

## 4. Site and build (builder D)

`scripts/build_campus.py [--levels ...] [--seasons ...] [--sims N] [--no-market] [--quick] [--game-page-seasons N]`:
copies the kit (`scripts/design_kit.copy_kit(DOCS / "campus")`), calls `football.build.build/build_level` and
`hoops.build.build/build_level` per level with every step isolated (a failure is logged and written as
`{"ok": false, "reason"}`), then the site-wide payloads (`oddsmarkets/college/site.py`: index.json, glossary.json,
search.json) and a size report (fails loudly over the budget in PAYLOADS.md). Front end per PAYLOADS.md.

### As built (builder D, 19 Oct 2026)

- `scripts/build_campus.py`: kit copy; per level `build_level(...)` (C's called with `per_season=False`; kwargs are
  filtered to each builder's signature) then `build(...)` per season, newest first; `full=True` only for the newest
  `--game-page-seasons` (default 2); every step isolated (traceback logged, missing payloads written `{"ok": false,
  "reason"}`, never overwriting); `site.build_all`; size report by folder, exit 1 over 800 MB. `--site-only` rebuilds
  just index/glossary/search. `--quick` = current + previous season, 2,000 sims, no markets.
- `oddsmarkets/college/site.py`: index.json (`next_games` falls back to the next 40 games within 3 weeks when the
  next 3 days are empty, i.e. preseason; `teams` = members plus any team a listed game or table uses), glossary.json
  (site terms + the payloads' METRIC descriptions, namespaced `L:key` on a clash), search.json (member teams; players
  with a career file, names from the last two catalogues or the career file).
- Kit: `QK.ALL_SPORTS` holds every site; the college entry has `pending: true`; `QK.SPORTS` (switcher, footer, home
  tiles) drops pending sites except on their own pages (`<html data-sport>`) and in local preview. Launch = delete the
  flag (and add "college" to `LAUNCHED` in `scripts/build_home.py`).
- Front end tolerates: box rows as arrays or objects (`player_id` or `id`), football box `cols` that include
  `id`/`name`, wp/flow times in seconds or minutes, First Four entries as arrays or objects, `top12_overlap` as a share
  or a count, `format.cfp.note`.

## 5. Pipeline (lead)
`campus.yml` from `scripts/gen_ci_workflows.py` (not launched: manual dispatch only until the user approves), the
`ci_site.py` context, guard (stores of every past season present, backtest caches present), prune and seed entries,
`push_seed.py --site campus`, the PC fallback entry in `local_sites.py` (not in its hourly cycle until launch), the
public-export allowlist.
