# The Quant Gridiron: data and model contract

NFL only. Seasons are the year the season starts (2026 = 2026 season incl. its Jan/Feb 2027 playoffs). Ids: games =
nflverse `game_id` ("2026_04_PIT_CLE"); players = gsis_id ("00-0036355"); teams = nflverse abbreviations (current
abbreviation per season; relocations mapped in canon). Dependencies: numpy, scipy, pandas, requests, pyarrow, lightgbm.
No network in tests. Roots: `GRIDIRON_DATA` (default `docs/gridiron/data`), `GRIDIRON_RAW` (default `data/nfl`),
`GRIDIRON_CACHE` (default `data/nfl/cache`). **No agent runs git write commands.** Bounded memory: one season of plays at a
time; no recursive closures holding arrays.

## 1. Data (builder A)
- Raw (git-ignored): `<raw>/raw/<release>/<file>.parquet` mirrored from nflverse-data releases with `timestamp.txt` gating:
  pbp (`play_by_play_<season>`), schedules (`games`), nextgen_stats (`ngs_<passing|rushing|receiving>`), ftn_charting,
  pbp_participation (2016–2025), depth_charts, injuries, rosters/weekly_rosters, players, espn_data,
  stats_player/stats_team. Column names kept as nflverse publishes them. Pro Football Reference's releases (snap_counts,
  pfr_advstats, trades, draft_picks, combine) are never fetched (`nflverse.LEFT_OUT`); PFR columns in the others (`pfr`,
  `pfr_id`, pre-2008 draft fields) are scrubbed as each file lands (`nflverse.scrub_file`).
- `oddsmarkets/nfl/sources/nflverse.py`: `fetch(release, season=None, force=False) -> Path|None`, `load_pbp(season, columns=None)`,
  `load_schedules()`, `load(release, season)`.
- `oddsmarkets/nfl/sources/espn.py`: scoreboard(date|week), summary(event) → compact live record
  `{"espn_id","game_id","status","period","clock","possession","down","distance","yardline_100","home_score","away_score",
  "drives":[...],"plays":[[seq, qtr, clock_s, team, down, dist, yl100, type, text, home_score, away_score, wp_home]],
  "odds":{"provider","spread_home","total","ml_home","ml_away","open":{...},"close":{...}},"predictor":{...},"injuries":{...}}`;
  core odds history by book (2017→); `map_game_id(espn_event) -> game_id`.
- `canon.py`: teams by season (STL→LAR 2016, SD→LAC 2017, OAK→LV 2020), divisions/conferences, stadiums (roof, surface, lat/lon,
  altitude), formats (16 games to 2020, 17 from 2021; playoff teams 12 to 2019, 14 from 2020; byes), and the verified NFL
  tiebreaker procedure (division, wild card; source cited) as data the season sim can apply.
- Stores (committed for completed seasons): `docs/gridiron/data/<season>/store.json`
  `{"season","updated_at","teams":{abbr:{...}},"games":{game_id: GAME},"meta":{...}}`;
  GAME = `{"game_id","season","week","gtype":"REG|WC|DIV|CON|SB","date","kickoff","home","away","hs","as","status","stadium","roof",
  "surface","temp","wind","referee","home_qb","away_qb","home_coach","away_coach","lines":{"spread_home","total","ml_home","ml_away",
  "open":{...},"close":{...},"books":[...]},"espn_id","overtime","div_game"}`.
- Derived compact tables (git-ignored, rebuilt from raw): `<raw>/derived/<season>/plays.parquet` (subset of pbp columns needed by
  models + FTN/participation joins).
- As built (builder A): `spread_home` is the home handicap (negative = home favoured; nflverse `spread_line` negated). `lines`
  also carries `spread_price`/`total_price` ([home, away] / [over, under]), `src` ("nflverse": the schedules' closing line,
  1999->, moneylines 2006->), and from ESPN (2017->) `open`/`close` (`{spread_home,total,ml_home,ml_away,spread_price,
  total_price,src}`), `books` (per book; `suspect: true` for in-play/stale rows), `consensus` (median of books), `espn_src`.
  GAME extras: `neutral`, `kickoff` (ISO UTC), `lat`,`lon`,`altitude_m`,`tz` (stadium), `home_qb_name`/`away_qb_name`,
  `home_rest`/`away_rest`, `gsis`, `old_game_id` (no `pfr_id` since 16 Oct 2026); `live` (current season, from ESPN: status, period, clock,
  possession, down, distance, yardline_100, scores, wp_home, `dk` open/close) with the full compact live record in
  `<cache>/espn/summary/<season>/<game_id>.json`. Store `teams[abbr]` = canon team + `stadium`, `coach`, `record` [W,L,T], `pf`,
  `pa`. Derived plays: pbp columns as published, FTN as `ftn_<col>`, participation as `part_<col>`
  (`nflverse.PLAY_COLUMNS`, `load_plays(season, columns)`).
- Tiebreakers: `oddsmarkets/nfl/tiebreak.py` `Table(games, season, tds=None, rng=None)` with `division_order(div)`,
  `order(clubs, "div"|"wc")`, `seed_conference(conf)` / `seeds()` (`{"seeds","division_winners","wild_cards","byes","order"}`);
  steps and quoted text in `canon.DIVISION_TWO/THREE`, `WILDCARD_TWO/THREE`, `TIEBREAK_NOTES`, `TIEBREAK_INTERPRETATION`.

## 2. Models (`oddsmarkets/nfl/models/`)
Common: pure functions on DataFrames + cached `for_season(season)`; committed fits in `models/fitted/` (versioned) used when the
cache is cold (CI). `_io.py` (builder B creates; others import): roots, loaders, cache, fitted fallback.

Builder B (play level): `ep.py`, `wp.py` (our own; compare with nflfastR's ep/wp columns), `fourth_down.py` (go/punt/FG WP
and decision grades; also 2-pt), `completion.py` (cp/CPOE), `yac.py` (xYAC), `ryoe.py`, `pressure.py`, `player_value.py`
(EPA attribution, opponent/supporting-cast adjusted; RAPM-style on 2016–2025 participation), `qb.py`, `kicking.py` (FG make prob,
kicker value), `stabilise.py`.

Builder C (teams and pricing): `team_strength.py` (opponent-adjusted unit ratings, time decay, priors, QB component),
`game.py` (margin/total → win, spread, total; HFA by season, rest, travel, tz, weather, injuries/QB), `drive_sim.py`
(score distributions), `live.py`, `season_sim.py` (18 weeks, tiebreakers from canon, 7-team playoffs with bye and reseeding,
division/playoff/bye/SB odds, magic numbers, draft order), `awards.py` (verified winners table), `backtest.py` (2006→ v closing
spread/moneyline; ESPN books 2017→; EP/WP v nflfastR), `sources/markets.py` (Kalshi KXNFL*/KXSB*/divisions/awards/props,
Polymarket tag nfl + games via series_id=12185).
