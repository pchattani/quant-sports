"""
Shared plumbing for The Quant Gridiron models (builder B creates; builders C and D import).

* Roots: `GRIDIRON_DATA` (default docs/gridiron/data), `GRIDIRON_RAW` (default data/nfl) and
  `GRIDIRON_CACHE` (default data/nfl/cache); committed fits in models/fitted/ (`FITTED`).
* Loaders read builder A's nflverse mirror (`<raw>/raw/<release>/<file>.parquet`) through
  `sources/nflverse.py` when it is importable and otherwise straight from disk, one season at a time and
  only the requested columns (missing columns come back as nulls, so callers can rely on them).
  `load_pbp`, `load_participation` (2016-2025), `load_ftn` (2022->), `load_ngs(kind)`, `load_schedules`.
* `plays(season)`: the compact model table for one season (the pbp columns the play models need, plus the
  participation and FTN joins), cached as Parquet under the cache root and keyed on the source files.
* JSON cache (`cached`), JSON/gzip writers, `clean`, fitted read/write (`read_fit`, `write_fit`,
  `write_booster`, `read_booster`), LightGBM helpers that keep a booster JSON-safe (its text dump) with a
  bounded in-process cache, logistic / ridge helpers, shrinkage.

Memory: one season of plays is read per call; fits concatenate compact float32 feature tables only. No
closures hold arrays (module-level functions throughout).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FITTED = Path(__file__).resolve().with_name("fitted")

FIRST_SEASON = 1999
PARTICIPATION_SEASONS = (2016, 2025)    # nflverse pbp_participation: published after each season
FTN_FIRST = 2022
NGS_FIRST = 2016

# pbp columns the play models read (a superset; absent columns come back null)
PBP_COLUMNS = [
    "game_id", "play_id", "season", "week", "season_type", "home_team", "away_team", "posteam", "defteam",
    "posteam_type", "qtr", "down", "ydstogo", "goal_to_go", "yardline_100", "half_seconds_remaining",
    "game_seconds_remaining", "quarter_seconds_remaining", "score_differential", "posteam_score", "defteam_score",
    "posteam_timeouts_remaining", "defteam_timeouts_remaining", "home_opening_kickoff", "roof", "surface", "temp",
    "wind", "play_type", "pass_attempt", "rush_attempt", "complete_pass", "incomplete_pass", "sack", "interception",
    "fumble_lost", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike", "qb_hit", "shotgun", "no_huddle",
    "pass_location", "pass_length", "air_yards", "yards_after_catch", "rushing_yards", "yards_gained",
    "run_location", "run_gap", "first_down", "third_down_converted", "fourth_down_converted",
    "fourth_down_failed", "touchdown", "td_team", "safety", "field_goal_result", "kick_distance",
    "extra_point_result", "two_point_attempt", "two_point_conv_result", "punt_blocked", "touchback",
    "return_yards", "penalty", "epa", "ep", "wp", "vegas_wp", "def_wp", "home_wp", "wpa", "cp", "cpoe",
    "xyac_mean_yardage", "xyac_epa", "air_epa", "yac_epa", "no_score_prob", "opp_fg_prob", "opp_safety_prob",
    "opp_td_prob", "fg_prob", "safety_prob", "td_prob", "spread_line", "total_line", "result",
    "passer_player_id", "passer_player_name", "receiver_player_id", "receiver_player_name", "rusher_player_id",
    "rusher_player_name", "kicker_player_id", "kicker_player_name", "punter_player_id", "punter_player_name",
    "sack_player_id", "half_sack_1_player_id", "half_sack_2_player_id", "qb_hit_1_player_id",
    "qb_hit_2_player_id", "home_coach", "away_coach", "stadium_id", "game_stadium", "drive", "fixed_drive",
    "success", "xpass", "pass_oe",
]
PARTICIPATION_COLUMNS = ["nflverse_game_id", "play_id", "offense_formation", "offense_personnel", "defenders_in_box",
                         "defense_personnel", "number_of_pass_rushers", "offense_players", "defense_players",
                         "time_to_throw", "was_pressure", "defense_man_zone_type", "defense_coverage_type"]
FTN_COLUMNS = ["nflverse_game_id", "nflverse_play_id", "n_offense_backfield", "n_defense_box", "is_no_huddle",
               "is_motion", "is_play_action", "is_screen_pass", "is_rpo", "is_qb_out_of_pocket",
               "is_interception_worthy", "is_throw_away", "is_catchable_ball", "is_contested_ball", "is_drop",
               "is_qb_sneak", "n_blitzers", "n_pass_rushers", "is_qb_fault_sack"]

ROOF_CODE = {"outdoors": 0, "open": 1, "closed": 2, "dome": 3}
LOC_CODE = {"left": 0, "middle": 1, "right": 2}
GAP_CODE = {"end": 0, "tackle": 1, "guard": 2}         # run_gap; middle runs have no gap (coded 3)
COVERAGE_CODE = {"COVER_0": 0, "COVER_1": 1, "COVER_2": 2, "2_MAN": 3, "COVER_3": 4, "COVER_4": 5, "COVER_6": 6,
                 "COVER_9": 7, "PREVENT": 8, "BLOWN": 9, "SCREEN": 10}
MANZONE_CODE = {"MAN_COVERAGE": 0, "ZONE_COVERAGE": 1}
# stadium altitude (ft) where it matters for kicking; canon (builder A) is preferred when importable
ALTITUDE_FT = {"DEN": 5280.0}


# ----------------------------------------------------------------------------- roots

def data_root() -> Path:
    return Path(os.environ.get("GRIDIRON_DATA") or (ROOT / "docs" / "gridiron" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("GRIDIRON_RAW") or (ROOT / "data" / "nfl"))


def cache_root() -> Path:
    return Path(os.environ.get("GRIDIRON_CACHE") or (raw_root() / "cache"))


def release_dir(release: str) -> Path:
    return raw_root() / "raw" / release


def _nflverse():
    """Builder A's loader module, or None (tests and a partial checkout read straight from disk)."""
    if os.environ.get("GRIDIRON_NO_SOURCES"):
        return None
    try:
        from oddsmarkets.nfl.sources import nflverse  # type: ignore
        return nflverse
    except Exception:  # noqa: BLE001
        return None


def release_path(release: str, season: int | None = None, kind: str | None = None) -> Path | None:
    """The Parquet file for a release (and season / kind) under the raw root, by nflverse's asset names."""
    d = release_dir(release)
    if not d.exists():
        return None
    names = []
    if release == "pbp" and season is not None:
        names = [f"play_by_play_{season}.parquet"]
    elif release == "pbp_participation" and season is not None:
        names = [f"pbp_participation_{season}.parquet"]
    elif release == "ftn_charting" and season is not None:
        names = [f"ftn_charting_{season}.parquet"]
    elif release == "nextgen_stats" and kind:
        names = [f"ngs_{kind}.parquet"] + ([f"ngs_{season}_{kind}.parquet"] if season else [])
    elif release == "schedules":
        names = ["games.parquet"]
    for n in names:
        if (d / n).exists():
            return d / n
    pat = f"*{season}*.parquet" if season is not None else "*.parquet"
    hits = sorted(p for p in d.rglob(pat) if (kind is None or kind in p.name))
    return hits[0] if hits else None


def pbp_seasons() -> list[int]:
    d = release_dir("pbp")
    if not d.exists():
        return []
    out = set()
    for p in d.rglob("*.parquet"):
        digits = "".join(ch for ch in p.stem if ch.isdigit())
        if len(digits) >= 4 and digits[-4:].isdigit():
            y = int(digits[-4:])
            if 1990 < y < 2100:
                out.add(y)
    return sorted(out)


def parquet_columns(path: Path) -> list[str]:
    try:
        import pyarrow.parquet as pq
        return list(pq.read_schema(path).names)
    except Exception:  # noqa: BLE001
        return []


def read_parquet(path: Path | None, columns: Iterable[str] | None = None) -> pd.DataFrame:
    """Only `columns` (all when None); missing ones come back null; categoricals as object."""
    cols = list(dict.fromkeys(columns)) if columns is not None else None
    if path is None or not Path(path).exists():
        return pd.DataFrame(columns=cols or [])
    have = parquet_columns(Path(path))
    want = [c for c in cols if c in have] if cols is not None else None
    try:
        df = pd.read_parquet(path, columns=want)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=cols or [])
    return _normalise(df, cols)


def _normalise(df: pd.DataFrame, cols: list[str] | None) -> pd.DataFrame:
    for c in df.columns:
        dt = df[c].dtype
        if isinstance(dt, pd.CategoricalDtype) or (dt != object and pd.api.types.is_string_dtype(dt)):
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    if cols is not None:
        for c in cols:
            if c not in df:
                df[c] = np.nan
        df = df[cols]
    return df


def load_pbp(season: int, columns: Iterable[str] | None = None) -> pd.DataFrame:
    cols = list(dict.fromkeys(columns)) if columns is not None else None
    src = _nflverse()
    if src is not None and hasattr(src, "load_pbp"):
        try:
            df = src.load_pbp(int(season), columns=[c for c in cols] if cols else None)
            if df is not None and len(df):
                return _normalise(df, cols)
        except TypeError:
            pass
        except Exception:  # noqa: BLE001
            pass
    return read_parquet(release_path("pbp", int(season)), cols)


def _load_release(release: str, season: int | None, columns: Iterable[str] | None, kind: str | None = None) -> pd.DataFrame:
    cols = list(dict.fromkeys(columns)) if columns is not None else None
    src = _nflverse()
    if src is not None and hasattr(src, "load"):
        try:
            df = src.load(release, season, kind=kind, columns=cols)
            if df is not None and len(df):
                return _normalise(df, cols)
        except Exception:  # noqa: BLE001
            pass
    return read_parquet(release_path(release, season, kind), cols)


def load_participation(season: int, columns: Iterable[str] | None = None) -> pd.DataFrame:
    if not (PARTICIPATION_SEASONS[0] <= int(season) <= PARTICIPATION_SEASONS[1]):
        return pd.DataFrame(columns=list(columns or PARTICIPATION_COLUMNS))
    return _load_release("pbp_participation", int(season), columns or PARTICIPATION_COLUMNS)


def load_ftn(season: int, columns: Iterable[str] | None = None) -> pd.DataFrame:
    if int(season) < FTN_FIRST:
        return pd.DataFrame(columns=list(columns or FTN_COLUMNS))
    return _load_release("ftn_charting", int(season), columns or FTN_COLUMNS)


def load_ngs(kind: str, season: int | None = None) -> pd.DataFrame:
    """Next Gen Stats (`passing`, `rushing`, `receiving`); all seasons, filtered to `season` when given."""
    src = _nflverse()
    df = None
    if src is not None and hasattr(src, "load"):
        try:
            df = src.load("nextgen_stats", season, kind=kind)
        except Exception:  # noqa: BLE001
            df = None
    if df is None or not len(df):
        df = read_parquet(release_path("nextgen_stats", season, kind))
    df = _normalise(df, None)
    if season is not None and "season" in df and len(df):
        df = df[pd.to_numeric(df["season"], errors="coerce") == int(season)]
    return df


_PLAYERS: dict = {}


def players() -> pd.DataFrame:
    """gsis_id -> display_name, position, position_group (nflverse `players`), cached in-process."""
    if "df" not in _PLAYERS:
        df = _load_release("players", None, ["gsis_id", "display_name", "position", "position_group"])
        _PLAYERS["df"] = df.drop_duplicates("gsis_id").set_index("gsis_id") if len(df) and "gsis_id" in df else             pd.DataFrame(columns=["display_name", "position", "position_group"])
    return _PLAYERS["df"]


def load_schedules() -> pd.DataFrame:
    src = _nflverse()
    if src is not None and hasattr(src, "load_schedules"):
        try:
            df = src.load_schedules()
            if df is not None and len(df):
                return _normalise(df, None)
        except Exception:  # noqa: BLE001
            pass
    return read_parquet(release_path("schedules"))


def source_files(season: int) -> list[Path]:
    out = []
    for rel in ("pbp", "pbp_participation", "ftn_charting"):
        p = release_path(rel, season)
        if p is not None:
            out.append(p)
    return out


# ----------------------------------------------------------------------------- the compact play table

def _flag(s: pd.Series) -> np.ndarray:
    """0/1/nan from booleans, 'TRUE'/'FALSE' strings or numbers."""
    if s.dtype == bool:
        return s.astype(float).to_numpy()
    x = pd.to_numeric(s, errors="coerce")
    if x.notna().any() or s.isna().all():
        return x.astype(float).to_numpy()
    t = s.astype(str).str.lower()
    return np.where(t.isin(["true", "1", "yes"]), 1.0, np.where(t.isin(["false", "0", "no"]), 0.0, np.nan))


def _add_cols(df: pd.DataFrame, cols: dict) -> pd.DataFrame:
    """Add constant columns in one concat (avoids a fragmented frame)."""
    new = {k: v for k, v in cols.items() if k not in df.columns}
    if not new:
        return df
    add = pd.DataFrame({k: pd.Series([v] * len(df), index=df.index, dtype=object if v is None else float)
                        for k, v in new.items()})
    return pd.concat([df, add], axis=1)


def attach_participation(df: pd.DataFrame, part: pd.DataFrame) -> pd.DataFrame:
    """Left-join participation (box, rushers, pressure, coverage, on-field players) on (game_id, play_id)."""
    names = {"defenders_in_box": "p_box", "number_of_pass_rushers": "p_rushers", "was_pressure": "p_pressure",
             "time_to_throw": "p_ttt", "defense_coverage_type": "p_coverage", "defense_man_zone_type": "p_manzone",
             "offense_players": "p_off_players", "defense_players": "p_def_players",
             "offense_personnel": "p_off_personnel", "offense_formation": "p_formation"}
    obj = ("p_off_players", "p_def_players", "p_coverage", "p_manzone", "p_off_personnel", "p_formation")
    df = _add_cols(df, {v: (None if v in obj else np.nan) for v in names.values()})
    if part is None or not len(part) or "play_id" not in part:
        return df
    p = part.rename(columns={"nflverse_game_id": "game_id"})
    p = p[[c for c in ["game_id", "play_id", *names] if c in p]].drop_duplicates(["game_id", "play_id"])
    p["play_id"] = pd.to_numeric(p["play_id"], errors="coerce")
    p = p.rename(columns=names)
    df = df.drop(columns=[c for c in names.values() if c in p.columns])
    df = df.merge(p, on=["game_id", "play_id"], how="left")
    for c in ("p_box", "p_rushers", "p_ttt"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["p_pressure"] = _flag(df["p_pressure"]) if "p_pressure" in df else np.nan
    return df


def attach_ftn(df: pd.DataFrame, ftn: pd.DataFrame) -> pd.DataFrame:
    names = {"n_defense_box": "f_box", "n_blitzers": "f_blitzers", "n_pass_rushers": "f_rushers",
             "is_drop": "f_drop", "is_interception_worthy": "f_int_worthy", "is_qb_out_of_pocket": "f_oop",
             "is_play_action": "f_pa", "is_screen_pass": "f_screen", "is_throw_away": "f_throwaway",
             "is_catchable_ball": "f_catchable", "is_contested_ball": "f_contested", "is_motion": "f_motion",
             "is_rpo": "f_rpo", "is_qb_sneak": "f_sneak", "n_offense_backfield": "f_backfield",
             "is_qb_fault_sack": "f_qb_fault_sack"}
    df = _add_cols(df, {v: np.nan for v in names.values()})
    if ftn is None or not len(ftn) or "nflverse_play_id" not in ftn:
        return df
    f = ftn.rename(columns={"nflverse_game_id": "game_id", "nflverse_play_id": "play_id"})
    f = f[[c for c in ["game_id", "play_id", *names] if c in f]].drop_duplicates(["game_id", "play_id"])
    f["play_id"] = pd.to_numeric(f["play_id"], errors="coerce")
    f = f.rename(columns=names)
    df = df.drop(columns=[c for c in names.values() if c in f.columns])
    df = df.merge(f, on=["game_id", "play_id"], how="left")
    for c in names.values():
        df[c] = _flag(df[c]) if df[c].dtype == object else pd.to_numeric(df[c], errors="coerce")
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Numeric types and derived codes shared by every model (in place on a copy of the pbp subset)."""
    df = df.copy()
    num = ["play_id", "season", "week", "qtr", "down", "ydstogo", "goal_to_go", "yardline_100", "half_seconds_remaining",
           "game_seconds_remaining", "score_differential", "posteam_timeouts_remaining", "defteam_timeouts_remaining",
           "home_opening_kickoff", "temp", "wind", "pass_attempt", "rush_attempt", "complete_pass", "incomplete_pass",
           "sack", "interception", "fumble_lost", "qb_dropback", "qb_scramble", "qb_kneel", "qb_spike", "qb_hit",
           "shotgun", "no_huddle", "air_yards", "yards_after_catch", "rushing_yards", "yards_gained", "first_down",
           "third_down_converted", "fourth_down_converted", "fourth_down_failed", "touchdown", "safety",
           "kick_distance", "two_point_attempt", "punt_blocked", "touchback", "return_yards", "penalty", "epa", "ep",
           "wp", "vegas_wp", "cp", "cpoe", "xyac_mean_yardage", "air_epa", "yac_epa", "spread_line", "result",
           "no_score_prob", "opp_fg_prob", "opp_safety_prob", "opp_td_prob", "fg_prob", "safety_prob", "td_prob",
           "success", "xpass", "posteam_score", "defteam_score"]
    for c in num:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("posteam", "defteam", "home_team", "away_team", "play_type", "roof", "pass_location", "run_location",
              "run_gap", "td_team", "field_goal_result", "two_point_conv_result", "extra_point_result", "game_id"):
        if c in df:
            df[c] = df[c].astype(object).where(df[c].notna(), None)
    df["home"] = (df["posteam"].astype(str) == df["home_team"].astype(str)).astype(float)
    df.loc[df["posteam"].isna(), "home"] = np.nan
    df["roof_code"] = df["roof"].map(ROOF_CODE).astype(float) if "roof" in df else np.nan
    df["indoor"] = (df["roof_code"] >= 2).astype(float)
    df["loc_code"] = df["pass_location"].map(LOC_CODE).astype(float) if "pass_location" in df else np.nan
    df["run_loc_code"] = df["run_location"].map(LOC_CODE).astype(float) if "run_location" in df else np.nan
    if "run_gap" in df:
        g = df["run_gap"].map(GAP_CODE).astype(float)
        df["gap_code"] = np.where(df["run_loc_code"] == 1, 3.0, g)
    # the posteam's pregame expected margin (spread_line is the home side's expected margin)
    sp = df["spread_line"] if "spread_line" in df else pd.Series(np.nan, index=df.index)
    df["pos_spread"] = np.where(df["home"] == 1, sp, -sp)
    alt = pd.Series(np.nan, index=df.index)
    if "stadium_id" in df:
        alt = df["stadium_id"].map(altitude_by_stadium())
    if "home_team" in df:
        alt = alt.fillna(df["home_team"].map(ALTITUDE_FT))
    df["altitude"] = alt.fillna(0.0).astype(float)
    return df.copy()


_ALT_CACHE: dict = {}


def altitude_by_stadium() -> dict:
    """nflverse stadium_id -> altitude in feet, from canon (builder A) when importable."""
    if "m" in _ALT_CACHE:
        return _ALT_CACHE["m"]
    out = {}
    try:
        from oddsmarkets.nfl import canon  # type: ignore
        for sid in getattr(canon, "STADIUMS", {}) or {}:
            st = canon.stadium(sid) or {}
            a = st.get("altitude_m")
            if a is not None:
                out[sid] = float(a) * 3.28084
    except Exception:  # noqa: BLE001
        pass
    _ALT_CACHE["m"] = out
    return out


def plays(season: int, use_cache: bool = True) -> pd.DataFrame:
    """The compact model table for one season (pbp subset + participation + FTN joins, prepared)."""
    srcs = source_files(season)
    pbp_path = release_path("pbp", season)
    if pbp_path is None:
        src = _nflverse()
        if src is None:
            return pd.DataFrame()
    key = file_key(*srcs, "plays-3")
    path = cache_root() / "plays" / f"{int(season)}.parquet"
    meta = cache_root() / "plays" / f"{int(season)}.key"
    if use_cache and path.exists() and meta.exists():
        try:
            if meta.read_text().strip() == key:
                return pd.read_parquet(path)
        except OSError:
            pass
    df = load_pbp(season, PBP_COLUMNS)
    if df is None or not len(df):
        return pd.DataFrame()
    df = prepare(df.copy())
    df = attach_participation(df, load_participation(season))
    df = attach_ftn(df, load_ftn(season))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        for c in out.columns:
            if out[c].dtype == float:
                out[c] = out[c].astype("float32")
        out.to_parquet(path, index=False)
        meta.write_text(key)
    except Exception:  # noqa: BLE001
        pass
    return df


def season_range(seasons: Iterable[int] | None = None) -> list[int]:
    return sorted(int(s) for s in (seasons if seasons is not None else pbp_seasons()))


def stack(seasons: Iterable[int], fn: Callable[[pd.DataFrame], pd.DataFrame], columns: list[str] | None = None,
          loader: Callable[[int], pd.DataFrame] | None = None) -> pd.DataFrame:
    """Concatenate fn(plays(season)) over seasons, one season in memory at a time; float columns as float32."""
    parts = []
    load = loader or plays
    for s in seasons:
        d = load(int(s))
        if d is None or not len(d):
            continue
        x = fn(d)
        del d
        if x is None or not len(x):
            continue
        if columns:
            x = x[[c for c in columns if c in x]]
        for c in x.columns:
            if x[c].dtype == np.float64:
                x[c] = x[c].astype("float32")
        parts.append(x)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=columns or [])


# ----------------------------------------------------------------------------- JSON / cache

def resolve(path: Path) -> Path:
    p = Path(path)
    gz = p.with_name(p.name + ".gz")
    if gz.exists() and (not p.exists() or gz.stat().st_mtime_ns >= p.stat().st_mtime_ns):
        return gz
    return p


def read_json(path: Path) -> Any:
    p = resolve(path)
    try:
        if p.name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def _json_default(o: Any) -> Any:
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def clean(x: Any, nd: int = 4) -> Any:
    """Round floats, map non-finite to None, recurse into dicts/lists (for payloads)."""
    if isinstance(x, dict):
        return {str(k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    if isinstance(x, np.ndarray):
        return [clean(v, nd) for v in x.tolist()]
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, nd) if math.isfinite(v) else None
    return x


def write_json(path: Path, obj: Any, gz: bool = False, nd: int | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(clean(obj, nd) if nd else clean(obj, 8), separators=(",", ":"), default=_json_default)
    if gz or p.name.endswith(".gz"):
        p = p if p.name.endswith(".gz") else p.with_name(p.name + ".gz")
        with gzip.open(p, "wt", encoding="utf-8", compresslevel=9) as fh:
            fh.write(txt)
    else:
        p.write_text(txt, encoding="utf-8")
    return p


def file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            try:
                st = p.stat()
                h.update(f"{p}|{st.st_size}|{st.st_mtime_ns}".encode())
            except OSError:
                h.update(f"{p}|missing".encode())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"|")
    return h.hexdigest()


def cached(kind: str, name: str, key: str, build: Callable[[], Any], use_cache: bool = True, gz: bool = False) -> Any:
    """JSON cache under cache_root()/kind/name.json[.gz], invalidated by `key`. Never raises on IO."""
    path = cache_root() / kind / (f"{name}.json.gz" if gz else f"{name}.json")
    if use_cache and resolve(path).exists():
        c = read_json(path)
        if isinstance(c, dict) and c.get("key") == key:
            return c.get("result")
    out = build()
    try:
        write_json(path, {"key": key, "result": out}, gz=gz)
    except (OSError, TypeError, ValueError):
        pass
    return out


def cached_frame(kind: str, name: str, key: str, build: Callable[[], pd.DataFrame], use_cache: bool = True) -> pd.DataFrame:
    """Parquet cache for per-season derived play tables (predictions), invalidated by `key`."""
    d = cache_root() / kind
    path, meta = d / f"{name}.parquet", d / f"{name}.key"
    if use_cache and path.exists() and meta.exists():
        try:
            if meta.read_text().strip() == key:
                return pd.read_parquet(path)
        except (OSError, ValueError):
            pass
    out = build()
    try:
        d.mkdir(parents=True, exist_ok=True)
        out.to_parquet(path, index=False)
        meta.write_text(key)
    except Exception:  # noqa: BLE001
        pass
    return out


def write_fit(name: str, obj: Any, gz: bool = False) -> Path:
    FITTED.mkdir(parents=True, exist_ok=True)
    return write_json(FITTED / f"{name}.json", obj, gz=gz, nd=6)


def read_fit(name: str) -> Any:
    return read_json(FITTED / f"{name}.json")


def load_fitted(name: str, version: str) -> dict | None:
    m = read_fit(name)
    if isinstance(m, dict) and m.get("version") == version and m.get("ok", True):
        return m
    return None


def write_booster(name: str, model_str: str) -> str:
    """A booster's text dump to models/fitted/<name>.txt.gz; returns the file name (for the JSON fit)."""
    FITTED.mkdir(parents=True, exist_ok=True)
    p = FITTED / f"{name}.txt.gz"
    with gzip.open(p, "wt", encoding="utf-8", compresslevel=9) as fh:
        fh.write(model_str)
    return p.name


def read_booster(fname: str) -> str | None:
    p = FITTED / fname
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


# ----------------------------------------------------------------------------- LightGBM

_BOOSTERS: dict[str, Any] = {}


def threads(n_rows: int = 10**6) -> int:
    env = os.environ.get("GRIDIRON_THREADS")
    if env:
        return int(env)
    return 2 if n_rows < 100_000 else min(16, max(1, (os.cpu_count() or 4) - 4))


def lgb_train(X: pd.DataFrame, y: np.ndarray, objective: str, params: dict | None = None, X_val=None, y_val=None,
              rounds: int = 400, early: int = 30, weight: np.ndarray | None = None,
              monotone: dict | None = None) -> tuple[Any, dict]:
    """Train a LightGBM booster; returns (booster, {"best_iter", "val_metric"}). Deterministic."""
    import lightgbm as lgb
    p = {"objective": objective, "learning_rate": 0.08, "num_leaves": 31, "min_data_in_leaf": 200,
         "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 5.0, "verbose": -1,
         "seed": 7, "deterministic": True, "force_col_wise": True, "num_threads": threads(len(X))}
    if params:
        p.update(params)
    if monotone:
        p["monotone_constraints"] = [int(monotone.get(c, 0)) for c in X.columns]
        p.setdefault("monotone_constraints_method", "advanced")
    ds = lgb.Dataset(X, label=np.asarray(y, float), weight=weight, free_raw_data=True)
    valid, cbs = [], []
    if X_val is not None and len(X_val):
        valid = [lgb.Dataset(X_val, label=np.asarray(y_val, float), reference=ds)]
        cbs = [lgb.early_stopping(early, verbose=False)]
    bst = lgb.train(p, ds, num_boost_round=rounds, valid_sets=valid or None, callbacks=cbs or None)
    info = {"best_iter": int(bst.best_iteration or bst.current_iteration())}
    if valid:
        bs = bst.best_score.get("valid_0") or {}
        info["val_metric"] = {k: float(v) for k, v in bs.items()}
    return bst, info


def booster_dump(bst) -> str:
    return bst.model_to_string(num_iteration=bst.best_iteration or -1)


def booster(model_str: str):
    """A Booster from its text dump, cached in-process by hash (bounded)."""
    import lightgbm as lgb
    h = hashlib.sha1(model_str.encode()).hexdigest()
    b = _BOOSTERS.get(h)
    if b is None:
        b = lgb.Booster(model_str=model_str)
        if len(_BOOSTERS) > 32:
            _BOOSTERS.clear()
        _BOOSTERS[h] = b
    return b


def lgb_predict(model_str: str, X: pd.DataFrame, chunk: int = 400_000) -> np.ndarray:
    b = booster(model_str)
    if len(X) == 0:
        return np.zeros((0,))
    nt = threads(len(X))
    out = [b.predict(X.iloc[i:i + chunk], num_threads=nt) for i in range(0, len(X), chunk)]
    return np.concatenate(out).astype(float)


def importances(model_str: str, features: list[str]) -> dict:
    b = booster(model_str)
    g = b.feature_importance(importance_type="gain").astype(float)
    tot = g.sum() or 1.0
    names = b.feature_name() or features
    return {n: round(float(v / tot), 4) for n, v in sorted(zip(names, g), key=lambda t: -t[1])}


def season_folds(seasons: Iterable[int], k: int = 5) -> list[list[int]]:
    """Seasons dealt round-robin into k folds (cross-fitting by season: each season is predicted by a
    model that never saw it)."""
    s = sorted(set(int(x) for x in seasons))
    k = max(1, min(k, len(s)))
    return [s[i::k] for i in range(k)]


# ----------------------------------------------------------------------------- statistics

def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))) if len(y) else float("nan")


def mlog_loss(y: np.ndarray, P: np.ndarray) -> float:
    """Multiclass log-loss of integer labels y against probability rows P."""
    y = np.asarray(y, int)
    P = np.clip(np.asarray(P, float), 1e-9, 1.0)
    P = P / P.sum(axis=1, keepdims=True)
    return float(-np.mean(np.log(P[np.arange(len(y)), y]))) if len(y) else float("nan")


def brier(y: np.ndarray, p: np.ndarray) -> float:
    y = np.asarray(y, float)
    return float(np.mean((np.asarray(p, float) - y) ** 2)) if len(y) else float("nan")


def calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> dict:
    """Equal-width bins: [[p_mid, mean_pred, mean_obs, n], ...] plus ECE (count-weighted |pred - obs|)."""
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    b = np.clip((p * bins).astype(int), 0, bins - 1)
    rows, ece = [], 0.0
    for i in range(bins):
        m = b == i
        n = int(m.sum())
        if not n:
            continue
        mp, mo = float(p[m].mean()), float(y[m].mean())
        rows.append([round((i + 0.5) / bins, 3), round(mp, 4), round(mo, 4), n])
        ece += n * abs(mp - mo)
    return {"bins": rows, "ece": round(ece / max(len(y), 1), 5), "n": int(len(y))}


def pearson(a, b) -> float | None:
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 3:
        return None
    a, b = a[ok], b[ok]
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def shrink(total: float, n: float, k: float, prior: float = 0.0) -> float:
    return float((total + k * prior) / (n + k)) if (n + k) > 0 else float(prior)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -35, 35)))


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))


def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float | np.ndarray = 1e-4, iters: int = 50,
              weight: np.ndarray | None = None, offset: np.ndarray | None = None) -> dict:
    """Dense logistic regression by Newton-Raphson (intercept is the caller's column). `ridge` may be a
    vector (per-coefficient penalty, 0 for unpenalised). Returns {"beta", "se"}."""
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    w = np.ones(len(y)) if weight is None else np.asarray(weight, float)
    off = np.zeros(len(y)) if offset is None else np.asarray(offset, float)
    R = np.diag(np.broadcast_to(np.asarray(ridge, float), (X.shape[1],)))
    b = np.zeros(X.shape[1])
    H = np.eye(X.shape[1])
    for _ in range(iters):
        mu = sigmoid(X @ b + off)
        g = X.T @ (w * (y - mu)) - R @ b
        H = X.T @ (X * (w * mu * (1 - mu))[:, None]) + R + 1e-10 * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-9:
            break
    try:
        cov = np.linalg.inv(H)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(X.shape[1], np.nan)
    return {"beta": b, "se": se}


def ridge_sparse(X, y: np.ndarray, lam: float, weight: np.ndarray | None = None, unpenalised: int = 0) -> np.ndarray:
    """Ridge on a scipy.sparse design: minimise sum w (y - X b)^2 + lam |b[unpenalised:]|^2, by LSQR on the
    augmented system (the first `unpenalised` columns carry a tiny penalty only)."""
    import scipy.sparse as sp
    from scipy.sparse.linalg import lsqr
    X = sp.csr_matrix(X)
    y = np.asarray(y, float)
    if weight is not None:
        sw = np.sqrt(np.asarray(weight, float))
        X = sp.diags(sw) @ X
        y = y * sw
    p = X.shape[1]
    pen = np.full(p, math.sqrt(lam))
    pen[:unpenalised] = 1e-4
    A = sp.vstack([X, sp.diags(pen)]).tocsr()
    rhs = np.concatenate([y, np.zeros(p)])
    return lsqr(A, rhs, atol=1e-10, btol=1e-10, iter_lim=5000)[0]


def zscore(x, mu=None, sd=None) -> np.ndarray:
    x = np.asarray(x, float)
    mu = np.nanmean(x) if mu is None else mu
    sd = np.nanstd(x) if sd is None else sd
    return (x - mu) / (sd if sd and sd > 0 else 1.0)


# ----------------------------------------------------------------------------- fits: cache, export, cross-fitting

def store_fit(name: str, fit: dict) -> None:
    """A full fit (booster dumps inline under fit["models"]) to the cache (gzip JSON)."""
    try:
        write_json(cache_root() / "fits" / f"{name}.json", fit, gz=True, nd=8)
    except (OSError, TypeError, ValueError):
        pass


def get_fit(name: str, version: str) -> dict | None:
    """The cached fit when its version matches, else the committed one in models/fitted/ (boosters re-read
    from their .txt.gz files), else None."""
    c = read_json(cache_root() / "fits" / f"{name}.json")
    if isinstance(c, dict) and c.get("version") == version and c.get("ok", True):
        return c
    f = load_fitted(name, version)
    if f is None:
        return None
    files = f.get("model_files") or {}
    if files:
        models = {}
        for k, fn in files.items():
            s = read_booster(fn)
            if s is None:
                return None
            models[k] = s
        f = {**f, "models": models}
    return f


def export_fit(name: str, fit: dict) -> Path:
    """Commit a fit to models/fitted/: boosters as <name>_<key>.txt.gz, the rest as <name>.json."""
    out = {k: v for k, v in fit.items() if k != "models"}
    files = {}
    for k, s in (fit.get("models") or {}).items():
        files[k] = write_booster(f"{name}_{k}", s)
    if files:
        out["model_files"] = files
    return write_fit(name, out)


def fold_ids(seasons: np.ndarray, games: np.ndarray, k: int = 5) -> np.ndarray:
    """Fold per row: by season when there are >= 3 seasons (cross-fitting by season), else by game."""
    us = np.unique(seasons)
    if len(us) >= 3:
        folds = season_folds(us, k)
        m = {s: i for i, f in enumerate(folds) for s in f}
        return np.array([m[s] for s in seasons], dtype=int)
    codes = pd.factorize(pd.Series(games).astype(str))[0]
    return (codes * 2654435761 % 2**32) % k


def _valid_mask(games: np.ndarray, frac: float = 0.1) -> np.ndarray:
    codes = pd.factorize(pd.Series(games).astype(str))[0]
    return ((codes * 40503 + 17) % 1000) < frac * 1000


def crossfit(X: pd.DataFrame, y: np.ndarray, folds: np.ndarray, games: np.ndarray, objective: str,
             params: dict | None = None, rounds: int = 500, weight: np.ndarray | None = None,
             monotone: dict | None = None, n_class: int = 0) -> tuple[np.ndarray, list[dict]]:
    """Out-of-fold predictions: each fold is predicted by a model trained on the other folds (early stopping
    on a 10% game holdout of the training folds). Returns (oof, infos)."""
    n = len(X)
    oof = np.full((n, n_class), np.nan) if n_class else np.full(n, np.nan)
    infos = []
    vm = _valid_mask(games)
    for f in np.unique(folds):
        te = folds == f
        tr = ~te & ~vm
        va = ~te & vm
        if tr.sum() < 50 or te.sum() == 0:
            continue
        w = weight[tr] if weight is not None else None
        bst, info = lgb_train(X[tr], y[tr], objective, params, X[va], y[va], rounds=rounds, weight=w, monotone=monotone)
        pr = bst.predict(X[te], num_iteration=bst.best_iteration or None, num_threads=threads(int(te.sum())))
        oof[te] = pr
        info["fold"] = int(f)
        info["n_train"] = int(tr.sum())
        infos.append(info)
        del bst
    return oof, infos


def fit_full(X: pd.DataFrame, y: np.ndarray, objective: str, params: dict | None = None, rounds: int = 300,
             weight: np.ndarray | None = None, monotone: dict | None = None) -> tuple[str, dict]:
    """One booster on everything for `rounds` iterations (the cross-fit's mean best iteration). Returns
    (model text dump, info)."""
    bst, info = lgb_train(X, y, objective, params, rounds=max(10, int(rounds)), weight=weight, monotone=monotone)
    s = booster_dump(bst)
    del bst
    return s, info


def predict_model(model_str: str, X: pd.DataFrame) -> np.ndarray:
    return lgb_predict(model_str, X)


# ----------------------------------------------------------------------------- tiered play-value models

def tier_index(seasons: np.ndarray, tiers: list[dict], fitted: set | None = None) -> np.ndarray:
    """Per row, the index of the richest tier (last in the list) whose season range covers the row and that
    was fitted; tier 0 (all seasons) is the fallback."""
    s = np.asarray(seasons, float)
    out = np.zeros(len(s), dtype=int)
    for i, t in enumerate(tiers):
        if fitted is not None and t["name"] not in fitted:
            continue
        lo, hi = t.get("lo") or 0, t.get("hi") or 9999
        out = np.where((s >= lo) & (s <= hi), i, out)
    return out


def fit_tiers(t: pd.DataFrame, tiers: list[dict], objective: str, params: dict, k: int = 5, rounds: int = 600,
              monotone: dict | None = None, min_rows: int = 2000) -> tuple[dict, np.ndarray]:
    """Cross-fit and refit one LightGBM model per feature tier (each on the seasons its data covers).
    Each row's out-of-fold prediction comes from its richest tier. t needs "y", "season", "game_id"."""
    y = t["y"].to_numpy(float)
    seasons = t["season"].to_numpy(float)
    games = t["game_id"].to_numpy()
    oofs, info, models = {}, [], {}
    for tier in tiers:
        lo, hi = tier.get("lo") or 0, tier.get("hi") or 9999
        m = (seasons >= lo) & (seasons <= hi) & np.isfinite(y)
        if m.sum() < min_rows:
            continue
        X = t.loc[m, tier["features"]]
        folds = fold_ids(seasons[m].astype(int), games[m], k)
        mono = {c: v for c, v in (monotone or {}).items() if c in tier["features"]}
        oof, infos = crossfit(X, y[m], folds, games[m], objective, params, rounds=rounds, monotone=mono)
        best = int(np.mean([i["best_iter"] for i in infos])) if infos else 200
        model, _ = fit_full(X, y[m], objective, params, rounds=best, monotone=mono)
        full = np.full(len(t), np.nan)
        full[m] = oof
        oofs[tier["name"]] = full
        models[tier["name"]] = model
        info.append({"name": tier["name"], "lo": lo, "hi": hi, "features": tier["features"], "n": int(m.sum()),
                     "best_iter": best, "importance": importances(model, tier["features"])})
        del X
    ti = tier_index(seasons, tiers, set(models))
    out = np.full(len(t), np.nan)
    for i, tier in enumerate(tiers):
        if tier["name"] in oofs:
            sel = ti == i
            out[sel] = oofs[tier["name"]][sel]
    return {"tiers": info, "models": models}, out


def predict_tiers(fit: dict, t: pd.DataFrame, tiers: list[dict]) -> np.ndarray:
    have = set((fit.get("models") or {}).keys())
    ti = tier_index(t["season"].to_numpy(float), tiers, have)
    out = np.full(len(t), np.nan)
    for i, tier in enumerate(tiers):
        sel = ti == i
        if sel.any() and tier["name"] in have:
            out[sel] = lgb_predict(fit["models"][tier["name"]], t.loc[sel, tier["features"]])
    return out


def oof_store(name: str, season: int, frame: pd.DataFrame) -> None:
    p = cache_root() / f"{name}_oof" / f"{int(season)}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(p, index=False)


def oof_load(name: str, season: int) -> pd.DataFrame | None:
    p = cache_root() / f"{name}_oof" / f"{int(season)}.parquet"
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:  # noqa: BLE001
        return None


def personnel_counts(s: pd.Series) -> pd.DataFrame:
    """'1 RB, 2 TE, 2 WR' -> n_rb, n_te, n_wr (NaN when missing)."""
    txt = s.astype(object).where(s.notna(), "").astype(str)
    out = {}
    for pos in ("RB", "TE", "WR"):
        out[f"n_{pos.lower()}"] = pd.to_numeric(txt.str.extract(rf"(\d+)\s*{pos}")[0], errors="coerce").to_numpy(float)
    return pd.DataFrame(out, index=s.index)
