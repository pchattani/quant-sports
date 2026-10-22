"""
nflverse-data release mirror (https://github.com/nflverse/nflverse-data/releases), timestamp-gated.

Assets download from https://github.com/nflverse/nflverse-data/releases/download/<tag>/<file> (a redirect to
release-assets.githubusercontent.com; not API-rate-limited). Every release carries `timestamp.txt` ("2026-10-01
12:24:05 EDT"), rewritten whenever any of its files changes. The gate, per release and run:

  1. read timestamp.txt once (cached for the process);
  2. a file on disk whose manifest entry carries that timestamp is current: no further request;
  3. otherwise HEAD the asset: an unchanged ETag (or size + Last-Modified) only refreshes the manifest;
  4. otherwise download (streamed, via .part), check the Parquet schema, then replace the file.

Releases (verified 1 Oct 2026; column names kept as nflverse publishes them):

  pbp                play_by_play_<season>          1999->   372 columns (EPA, WP, CPOE, xYAC, ids)
  schedules          games                          all      lines 1999->, moneylines 2006->, espn ids
  nextgen_stats      ngs_<passing|rushing|receiving>  2016-> (one file, all seasons)  NGS: non-commercial
  ftn_charting       ftn_charting_<season>          2022->   CC-BY-SA, "FTN Data via nflverse"
  pbp_participation  pbp_participation_<season>     2016-2025 (after each season)
  depth_charts       depth_charts_<season>          2001->
  injuries           injuries_<season>              2009->
  rosters            roster_<season>                1920-> (we keep 1999->)
  weekly_rosters     roster_weekly_<season>         2002->
  players            players                        all      id crosswalk (gsis, espn, ...); draft fields used from 2008 only
  espn_data          qbr_<season|week>_level        2006->
  stats_player       stats_player_week_<season>     1999->
  stats_team         stats_team_week_<season>       1999->
  contracts          historical_contracts           all      OverTheCap contracts (optional: not in "all"; see below)
  officials          officials                      2015->   game officials by position (optional: research only, fetched by name)

Licence: nflverse data CC-BY 4.0; FTN charting CC-BY-SA 4.0; NGS redistributed NFL data (credit, non-commercial).
The contracts release is OverTheCap's data, whose terms do not allow republishing it on a website without OTC's consent:
it is fetched only when asked for by name (`nfl_fetch.py --releases contracts`) and published only behind
GRIDIRON_CONTRACTS=1 (analytics/contracts.py).

Left out for Pro Football Reference's terms (sports-reference.com/data_use: "you should not create websites or tools
based on data you scrape from Sports Reference"): `snap_counts` ("provided by Pro Football Reference"), `pfr_advstats`,
`trades`, `draft_picks`, `combine`, and from other releases the PFR-scraped parts: the players release's draft fields
before 2008 (people.py drops them) and the schedules' `pfr` game id (not stored). `LEFT_OUT` lists them; none is
fetchable. On-field snap shares come from the play-by-play participation instead (models/_cdata.onfield).
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .. import canon
from .. import store as st
from ._client import BudgetExhausted, Client  # noqa: F401

logger = logging.getLogger(__name__)

BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# release -> (file template, first season or None for season-less files, last season or None, kinds)
RELEASES: dict[str, dict] = {
    "pbp": {"tpl": "play_by_play_{season}", "from": 1999},
    "schedules": {"tpl": "games", "from": None},
    "nextgen_stats": {"tpl": "ngs_{kind}", "from": None, "kinds": ("passing", "rushing", "receiving")},
    "ftn_charting": {"tpl": "ftn_charting_{season}", "from": canon.FTN_FROM},
    "pbp_participation": {"tpl": "pbp_participation_{season}", "from": canon.PARTICIPATION[0], "to": canon.PARTICIPATION[1]},
    "depth_charts": {"tpl": "depth_charts_{season}", "from": 2001},
    "injuries": {"tpl": "injuries_{season}", "from": 2009},
    "rosters": {"tpl": "roster_{season}", "from": canon.FIRST_SEASON},
    "weekly_rosters": {"tpl": "roster_weekly_{season}", "from": 2002},
    "players": {"tpl": "players", "from": None},
    "espn_data": {"tpl": "qbr_{kind}_level", "from": None, "kinds": ("season", "week")},
    "stats_player": {"tpl": "stats_player_week_{season}", "from": canon.FIRST_SEASON},
    "stats_team": {"tpl": "stats_team_week_{season}", "from": canon.FIRST_SEASON},
    "contracts": {"tpl": "historical_contracts", "from": None, "optional": True},
    "officials": {"tpl": "officials", "from": None, "optional": True},      # research only (nfl_edge.md section 11)
}

# nflverse releases left out for their source's terms (module docstring); never fetched.
LEFT_OUT: dict[str, str] = {
    "snap_counts": "Pro Football Reference",
    "pfr_advstats": "Pro Football Reference",
    "trades": "Pro Football Reference",
    "draft_picks": "Pro Football Reference",
    "combine": "Pro Football Reference",
}

# Columns a file must carry to replace the copy on disk (schema check).
REQUIRED: dict[str, tuple] = {
    "pbp": ("play_id", "game_id", "season", "week", "posteam", "defteam", "down", "ydstogo", "yardline_100",
            "game_seconds_remaining", "play_type", "epa", "wp", "desc"),
    "schedules": ("game_id", "season", "game_type", "week", "gameday", "home_team", "away_team", "home_score",
                  "away_score", "spread_line", "total_line", "espn", "stadium_id", "roof", "surface"),
    "nextgen_stats": ("season", "season_type", "week", "player_gsis_id", "team_abbr"),
    "ftn_charting": ("nflverse_game_id", "nflverse_play_id", "season", "week"),
    "pbp_participation": ("nflverse_game_id", "play_id"),
    "depth_charts": (),
    "injuries": ("season", "week", "team", "gsis_id"),
    "rosters": ("season", "team", "gsis_id"),
    "weekly_rosters": ("season", "week", "team", "gsis_id"),
    "players": ("gsis_id",),
    "espn_data": ("season",),
    "stats_player": ("season", "week", "player_id"),
    "stats_team": ("season", "week", "team"),
    "contracts": ("gsis_id", "is_active", "season_history"),
}

_TIMESTAMPS: dict[str, str | None] = {}
_CLIENT: Client | None = None


def client() -> Client:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Client(budget=10_000, interval=0.2, name="nflverse")
    return _CLIENT


def filename(release: str, season: int | None = None, kind: str | None = None) -> str:
    spec = RELEASES[release]
    if spec.get("kinds") and kind is None and "{kind}" in spec["tpl"]:
        kind = spec["kinds"][0]
    return spec["tpl"].format(season=season, kind=kind) + ".parquet"


def seasons(release: str, through: int | None = None) -> list[int | None]:
    spec = RELEASES[release]
    if spec["from"] is None:
        return [None]
    hi = min(spec.get("to") or 9999, through or canon.current_season())
    return list(range(spec["from"], hi + 1))


def files_for(release: str, season: int | None) -> list[str]:
    """Every file of a release for one season (season-less releases: every file)."""
    spec = RELEASES[release]
    kinds = spec.get("kinds") or (None,)
    if spec["from"] is None:
        return [filename(release, None, k) for k in kinds]
    out = [filename(release, season, k) for k in kinds]
    return out


def url(release: str, fname: str) -> str:
    return f"{BASE}/{release}/{fname}"


# ── timestamp gate ──────────────────────────────────────────────────────────

def release_timestamp(release: str, c: Client | None = None, refresh: bool = False) -> str | None:
    if refresh or release not in _TIMESTAMPS:
        txt = (c or client()).get_text(url(release, "timestamp.txt"))
        _TIMESTAMPS[release] = txt.strip() if txt else None
    return _TIMESTAMPS[release]


def load_manifest(release: str) -> dict:
    m = st.read_json(st.manifest_path(release)) or {}
    m.setdefault("release", release)
    m.setdefault("timestamp", None)
    m.setdefault("files", {})
    return m


def save_manifest(release: str, m: dict) -> None:
    st.write_json(st.manifest_path(release), m, indent=1)


def _version(h: dict | None) -> dict:
    h = h or {}
    return {"etag": h.get("etag"), "last_modified": h.get("last-modified"),
            "size": int(h["content-length"]) if str(h.get("content-length") or "").isdigit() else h.get("bytes")}


def _same(a: dict, b: dict) -> bool:
    if a.get("etag") and b.get("etag"):
        return a["etag"] == b["etag"]
    return bool(a.get("size")) and a.get("size") == b.get("size") and a.get("last_modified") == b.get("last_modified")


def check_schema(release: str, path: Path) -> list[str]:
    """Required columns missing from a downloaded file ([] when it is fine). Raises on an unreadable file."""
    names = set(pq.read_schema(path).names)
    return [c for c in REQUIRED.get(release, ()) if c not in names]


# PFR-origin columns inside otherwise permitted releases, removed from the mirror as each file lands (`scrub_file`):
# Pro Football Reference ids, and the players release's draft fields before DRAFT_API_FROM (scraped from PFR).
SCRUB_COLS: dict[str, tuple] = {"schedules": ("pfr",), "players": ("pfr_id",), "rosters": ("pfr_id",),
                                "weekly_rosters": ("pfr_id",)}
DRAFT_API_FROM = 2008
DRAFT_COLS = ("draft_year", "draft_round", "draft_pick", "draft_team")


def scrub_frame(release: str, df: pd.DataFrame) -> pd.DataFrame:
    """The frame without its PFR-origin columns (SCRUB_COLS); for `players`, draft fields blanked before 2008."""
    drop = [c for c in SCRUB_COLS.get(release, ()) if c in df.columns]
    if drop:
        df = df.drop(columns=drop)
    if release == "players" and "draft_year" in df.columns:
        old = pd.to_numeric(df["draft_year"], errors="coerce") < DRAFT_API_FROM
        if old.any():
            df = df.copy()
            for c in DRAFT_COLS:
                if c in df.columns:
                    df[c] = df[c].where(~old, None)
    return df


def scrub_file(release: str, p: Path) -> bool:
    """Rewrite a mirrored Parquet file without its PFR-origin data (scrub_frame); True when it changed."""
    if release not in SCRUB_COLS or not Path(p).exists():
        return False
    names = set(pq.read_schema(p).names)
    needs = any(c in names for c in SCRUB_COLS[release])
    if not needs and release == "players" and "draft_year" in names:
        dy = pd.to_numeric(pd.read_parquet(p, columns=["draft_year"])["draft_year"], errors="coerce")
        needs = bool((dy < DRAFT_API_FROM).any())
    if not needs:
        return False
    df = scrub_frame(release, pd.read_parquet(p))
    tmp = Path(str(p) + ".scrub")
    df.to_parquet(tmp, index=False)
    tmp.replace(p)
    return True


def fetch_file(release: str, fname: str, force: bool = False, c: Client | None = None) -> Path | None:
    """Mirror one asset of a release through the timestamp gate. Returns the local path (None if the
    asset is unavailable and nothing is on disk)."""
    if release in LEFT_OUT:
        raise ValueError(f"nflverse {release} is {LEFT_OUT[release]}'s data and is left out for its terms")
    c = c or client()
    dest = st.release_path(release, fname)
    m = load_manifest(release)
    ent = m["files"].get(fname) or {}
    ts = release_timestamp(release, c)
    if not force and dest.exists() and ent and ts and ent.get("timestamp") == ts:
        return dest
    head = None if force else c.head(url(release, fname))
    if head is None and not force:
        if dest.exists():
            return dest
        # unknown (missing asset or network): try the download anyway
    ver = _version(head) if head else {}
    if not force and dest.exists() and ent and ver and _same(ent, ver):
        ent.update(timestamp=ts, checked_at=st.now())
        m["files"][fname] = ent
        m["timestamp"] = ts
        save_manifest(release, m)
        return dest
    tmp = dest.with_name(dest.name + ".new")
    dest.parent.mkdir(parents=True, exist_ok=True)
    got = c.download(url(release, fname), tmp)
    if got is None:
        logger.warning("nflverse %s/%s: download failed%s", release, fname, "; keeping the copy on disk" if dest.exists() else "")
        return dest if dest.exists() else None
    try:
        missing = check_schema(release, tmp)
    except Exception as exc:  # noqa: BLE001 - a corrupt download must never replace a good file
        logger.warning("nflverse %s/%s: unreadable Parquet (%s); discarded", release, fname, exc)
        tmp.unlink(missing_ok=True)
        return dest if dest.exists() else None
    if missing:
        logger.warning("nflverse %s/%s: missing required columns %s; discarded", release, fname, missing)
        tmp.unlink(missing_ok=True)
        return dest if dest.exists() else None
    scrub_file(release, tmp)
    tmp.replace(dest)
    meta = pq.read_metadata(dest)
    m["files"][fname] = {**_version(got), "timestamp": ts, "at": st.now(), "rows": meta.num_rows,
                         "columns": meta.num_columns, "bytes": dest.stat().st_size, "checked_at": st.now()}
    m["timestamp"] = ts
    save_manifest(release, m)
    logger.info("nflverse %s/%s: %d rows, %d columns, %.1f MB", release, fname, meta.num_rows, meta.num_columns,
                dest.stat().st_size / 1e6)
    return dest


def fetch(release: str, season: int | None = None, force: bool = False, kind: str | None = None,
          c: Client | None = None) -> Path | None:
    """CONTRACT: mirror the release's file for a season (or the season-less file). For releases with
    several kinds (NGS, QBR) `kind` picks one; `fetch_all` takes every file."""
    if release not in RELEASES:
        raise KeyError(release)
    return fetch_file(release, filename(release, season, kind), force=force, c=c)


def fetch_all(release: str, season: int | None = None, force: bool = False, c: Client | None = None) -> list[Path]:
    out = []
    names = files_for(release, season)
    spec = RELEASES[release]
    if spec["from"] is not None and spec.get("extra") and season == canon.current_season():
        names += [x + ".parquet" for x in spec["extra"]]
    for fname in names:
        p = fetch_file(release, fname, force=force, c=c)
        if p is not None:
            out.append(p)
    return out


# ── loaders ─────────────────────────────────────────────────────────────────

def path(release: str, season: int | None = None, kind: str | None = None) -> Path:
    return st.release_path(release, filename(release, season, kind))


def load(release: str, season: int | None = None, kind: str | None = None, columns: list[str] | None = None) -> pd.DataFrame | None:
    """A mirrored file as a DataFrame (None when not on disk). Season-less releases filtered to `season`
    when given and a season column exists."""
    p = path(release, season if RELEASES[release]["from"] is not None else None, kind)
    if not p.exists():
        return None
    cols = None
    if columns is not None:
        names = set(pq.read_schema(p).names)
        cols = [c for c in columns if c in names]
    df = pd.read_parquet(p, columns=cols)
    if RELEASES[release]["from"] is None and season is not None and "season" in df.columns:
        df = df[df["season"] == int(season)].reset_index(drop=True)
    return df


def load_pbp(season: int, columns: list[str] | None = None) -> pd.DataFrame | None:
    return load("pbp", season, columns=columns)


def load_schedules() -> pd.DataFrame | None:
    return load("schedules")


# ── schedules -> GAME ───────────────────────────────────────────────────────

def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _str(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


def kickoff_utc(gameday: str | None, gametime: str | None) -> str | None:
    """nflverse gameday + gametime (US Eastern) -> ISO UTC."""
    if not gameday:
        return None
    from datetime import datetime
    from zoneinfo import ZoneInfo
    hhmm = gametime or "13:00"
    try:
        dt = datetime.strptime(f"{gameday} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York"))
    except ValueError:
        return None
    return dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_game(r: dict) -> dict:
    """A schedules row (dict) -> GAME (CONTRACT.md). Lines: nflverse's spread_line is positive when the
    home team is favoured, so spread_home = -spread_line (the home handicap, negative when favoured)."""
    hs, as_ = _num(r.get("home_score")), _num(r.get("away_score"))
    spread_line = _num(r.get("spread_line"))
    lines = None
    if spread_line is not None or _num(r.get("total_line")) is not None or _num(r.get("home_moneyline")) is not None:
        lines = {"spread_home": -spread_line if spread_line is not None else None,
                 "total": _num(r.get("total_line")),
                 "ml_home": _num(r.get("home_moneyline")), "ml_away": _num(r.get("away_moneyline")),
                 "spread_price": [_num(r.get("home_spread_odds")), _num(r.get("away_spread_odds"))],
                 "total_price": [_num(r.get("over_odds")), _num(r.get("under_odds"))],
                 "src": "nflverse"}
        if lines["spread_home"] == 0:
            lines["spread_home"] = 0.0
    sid = _str(r.get("stadium_id"))
    sd = canon.stadium(sid) or {}
    season = int(r["season"])
    return {
        "game_id": str(r["game_id"]), "season": season, "week": int(r["week"]), "gtype": str(r["game_type"]),
        "date": _str(r.get("gameday")), "weekday": _str(r.get("weekday")),
        "kickoff": kickoff_utc(_str(r.get("gameday")), _str(r.get("gametime"))),
        "home": str(r["home_team"]), "away": str(r["away_team"]), "hs": hs, "as": as_,
        "status": "final" if hs is not None and as_ is not None else "scheduled",
        "neutral": _str(r.get("location")) == "Neutral",
        "stadium": sid, "stadium_name": _str(r.get("stadium")),
        "roof": _str(r.get("roof")), "surface": _str(r.get("surface")),
        "lat": sd.get("lat"), "lon": sd.get("lon"), "altitude_m": sd.get("altitude_m"), "tz": sd.get("tz"),
        "temp": _num(r.get("temp")), "wind": _num(r.get("wind")), "referee": _str(r.get("referee")),
        "home_qb": _str(r.get("home_qb_id")), "away_qb": _str(r.get("away_qb_id")),
        "home_qb_name": _str(r.get("home_qb_name")), "away_qb_name": _str(r.get("away_qb_name")),
        "home_coach": _str(r.get("home_coach")), "away_coach": _str(r.get("away_coach")),
        "home_rest": _num(r.get("home_rest")), "away_rest": _num(r.get("away_rest")),
        "lines": lines, "espn_id": _str(r.get("espn")), "gsis": _num(r.get("gsis")),
        "old_game_id": _str(r.get("old_game_id")),
        "overtime": bool(_num(r.get("overtime"))) if _num(r.get("overtime")) is not None else None,
        "div_game": bool(_num(r.get("div_game"))),
    }


def games_for_season(sched: pd.DataFrame, season: int) -> list[dict]:
    sub = sched[sched["season"] == int(season)]
    return [compact_game(r) for r in sub.to_dict("records")]


# ── derived plays table ─────────────────────────────────────────────────────

PLAY_COLUMNS = [
    "game_id", "play_id", "season", "week", "season_type", "game_date", "home_team", "away_team", "posteam",
    "defteam", "posteam_type", "qtr", "down", "ydstogo", "yardline_100", "goal_to_go", "game_seconds_remaining",
    "half_seconds_remaining", "quarter_seconds_remaining", "game_half", "drive", "fixed_drive", "fixed_drive_result",
    "series", "series_success", "order_sequence", "time", "play_type", "play_type_nfl", "desc", "yards_gained",
    "shotgun", "no_huddle", "qb_dropback", "qb_kneel", "qb_spike", "qb_scramble", "pass_length", "pass_location",
    "air_yards", "yards_after_catch", "run_location", "run_gap", "field_goal_result", "kick_distance",
    "extra_point_result", "two_point_conv_result", "two_point_attempt", "extra_point_attempt", "field_goal_attempt",
    "punt_attempt", "kickoff_attempt", "punt_blocked", "touchback", "posteam_timeouts_remaining",
    "defteam_timeouts_remaining", "home_timeouts_remaining", "away_timeouts_remaining", "timeout", "timeout_team",
    "posteam_score", "defteam_score", "score_differential", "posteam_score_post", "defteam_score_post",
    "total_home_score", "total_away_score", "ep", "epa", "wp", "def_wp", "home_wp", "wpa", "vegas_wp",
    "vegas_home_wp", "vegas_wpa", "air_epa", "yac_epa", "comp_air_epa", "comp_yac_epa", "qb_epa", "cp", "cpoe",
    "xyac_epa", "xyac_mean_yardage", "xyac_success", "xyac_fd", "xpass", "pass_oe", "success", "first_down",
    "first_down_rush", "first_down_pass", "first_down_penalty", "third_down_converted", "third_down_failed",
    "fourth_down_converted", "fourth_down_failed", "rush_attempt", "pass_attempt", "complete_pass",
    "incomplete_pass", "interception", "sack", "qb_hit", "fumble", "fumble_lost", "touchdown", "pass_touchdown",
    "rush_touchdown", "return_touchdown", "td_team", "safety", "penalty", "penalty_team", "penalty_yards",
    "penalty_type", "pass", "rush", "special", "play", "aborted_play", "play_deleted",
    "passer_player_id", "receiver_player_id", "rusher_player_id", "passer_id", "rusher_id", "receiver_id",
    "kicker_player_id", "punter_player_id", "interception_player_id", "sack_player_id", "half_sack_1_player_id",
    "half_sack_2_player_id", "qb_hit_1_player_id", "qb_hit_2_player_id", "pass_defense_1_player_id",
    "solo_tackle_1_player_id", "assist_tackle_1_player_id", "tackle_for_loss_1_player_id",
    "forced_fumble_player_1_player_id", "kickoff_returner_player_id", "punt_returner_player_id", "return_yards",
    "passing_yards", "receiving_yards", "rushing_yards", "roof", "surface", "temp", "wind", "stadium_id",
    "spread_line", "total_line", "result", "total", "home_coach", "away_coach", "home_opening_kickoff",
    "drive_start_yard_line", "drive_end_transition", "drive_play_count", "drive_time_of_possession",
]

FTN_COLUMNS = ["starting_hash", "qb_location", "n_offense_backfield", "n_defense_box", "is_no_huddle", "is_motion",
               "is_play_action", "is_screen_pass", "is_rpo", "is_trick_play", "is_qb_out_of_pocket",
               "is_interception_worthy", "is_throw_away", "read_thrown", "is_catchable_ball", "is_contested_ball",
               "is_created_reception", "is_drop", "is_qb_sneak", "n_blitzers", "n_pass_rushers", "is_qb_fault_sack"]

PART_COLUMNS = ["offense_formation", "offense_personnel", "defenders_in_box", "defense_personnel",
                "number_of_pass_rushers", "ngs_air_yards", "time_to_throw", "was_pressure", "route",
                "defense_man_zone_type", "defense_coverage_type", "offense_players", "defense_players",
                "n_offense", "n_defense"]


def build_plays(season: int, pbp: pd.DataFrame | None = None, ftn: pd.DataFrame | None = None,
                part: pd.DataFrame | None = None, write: bool = True) -> dict:
    """The compact play table for a season: PLAY_COLUMNS of pbp, FTN charting as ftn_* and participation
    as part_* (left joins on game and play id). One season in memory at a time."""
    if pbp is None:
        pbp = load_pbp(season, PLAY_COLUMNS)
    if pbp is None:
        return {"season": season, "plays": 0}
    df = pbp[[c for c in PLAY_COLUMNS if c in pbp.columns]].copy()
    del pbp
    info = {"season": int(season), "plays": int(len(df)), "games": int(df["game_id"].nunique())}
    if ftn is None and int(season) >= canon.FTN_FROM:
        ftn = load("ftn_charting", season, columns=["nflverse_game_id", "nflverse_play_id"] + FTN_COLUMNS)
    if ftn is not None and len(ftn):
        f = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
        f = f[["game_id", "play_id"] + [c for c in FTN_COLUMNS if c in f.columns]]
        f = f.drop_duplicates(["game_id", "play_id"])
        f["play_id"] = pd.to_numeric(f["play_id"], errors="coerce")
        f = f.rename(columns={c: f"ftn_{c}" for c in FTN_COLUMNS})
        df = df.merge(f, on=["game_id", "play_id"], how="left")
        info["ftn_matched"] = int(df["ftn_is_play_action"].notna().sum()) if "ftn_is_play_action" in df else 0
    if part is None and canon.PARTICIPATION[0] <= int(season) <= canon.PARTICIPATION[1]:
        part = load("pbp_participation", season, columns=["nflverse_game_id", "play_id"] + PART_COLUMNS)
    if part is not None and len(part):
        p = part.rename(columns={"nflverse_game_id": "game_id"})
        p = p[["game_id", "play_id"] + [c for c in PART_COLUMNS if c in p.columns]].drop_duplicates(["game_id", "play_id"])
        p["play_id"] = pd.to_numeric(p["play_id"], errors="coerce")
        p = p.rename(columns={c: f"part_{c}" for c in PART_COLUMNS})
        df = df.merge(p, on=["game_id", "play_id"], how="left")
        info["part_matched"] = int(df["part_offense_players"].notna().sum()) if "part_offense_players" in df else 0
    if write:
        out = st.plays_path(season)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".tmp")
        df.to_parquet(tmp, index=False, compression="zstd")
        tmp.replace(out)
        info["bytes"] = out.stat().st_size
    info["columns"] = int(df.shape[1])
    return info


def load_plays(season: int, columns: list[str] | None = None) -> pd.DataFrame | None:
    p = st.plays_path(season)
    if not p.exists():
        return None
    cols = None
    if columns is not None:
        names = set(pq.read_schema(p).names)
        cols = [c for c in columns if c in names]
    return pd.read_parquet(p, columns=cols)
