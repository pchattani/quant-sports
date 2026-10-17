"""
Baseball Savant: the Statcast pitch table (MLB from 2015, Triple-A from 2023) and the leaderboards used as
validation references.

Search (no key, CORS *), verified 1 Oct 2026:
  https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details&player_type=pitcher
      &hfGT=R|F|D|L|W|&game_date_gt=YYYY-MM-DD&game_date_lt=YYYY-MM-DD      (both bounds inclusive)
  Triple-A: the same URL plus `minors=true&hfLevel=AAA|` (without hfLevel the minors search also returns the
  Single-A Florida State League parks). `hfTeam=XXX|` filters the pitching team.
  119 columns (a BOM on the first); one MLB day ~ 4,700 rows / 3 MB / 7-8 s, one Triple-A day ~ 4,600 rows.

A SILENT 25,000-row cap applies per request (the newest rows are returned): any answer with exactly CAP rows
is re-requested as two halves of the date range, and a single capped day is split by pitching team.

Typing (CONTRACT.md section 1): Savant column names as-is; categorical strings as category, floats float32,
ids and counts int32; game_date a timestamp. Columns a season lacks are present as null. Parquet: one part
per day under <season>.parts/, compacted into <season>.parquet by streaming the parts (bounded memory).
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .. import canon
from .. import store as st
from ._client import BudgetExhausted, Client  # noqa: F401  (re-exported for scripts)

logger = logging.getLogger(__name__)

SEARCH = "https://baseballsavant.mlb.com/statcast_search/csv"
BASE = "https://baseballsavant.mlb.com"
CAP = 25_000
INTERVAL = 3.0                      # seconds between Savant requests

COLUMNS = [
    "pitch_type", "game_date", "release_speed", "release_pos_x", "release_pos_z", "player_name", "batter", "pitcher",
    "events", "description", "spin_dir", "spin_rate_deprecated", "break_angle_deprecated", "break_length_deprecated",
    "zone", "des", "game_type", "stand", "p_throws", "home_team", "away_team", "type", "hit_location", "bb_type",
    "balls", "strikes", "game_year", "pfx_x", "pfx_z", "plate_x", "plate_z", "on_3b", "on_2b", "on_1b", "outs_when_up",
    "inning", "inning_topbot", "hc_x", "hc_y", "tfs_deprecated", "tfs_zulu_deprecated", "umpire", "sv_id", "vx0",
    "vy0", "vz0", "ax", "ay", "az", "sz_top", "sz_bot", "hit_distance_sc", "launch_speed", "launch_angle",
    "effective_speed", "release_spin_rate", "release_extension", "game_pk", "fielder_2", "fielder_3", "fielder_4",
    "fielder_5", "fielder_6", "fielder_7", "fielder_8", "fielder_9", "release_pos_y", "estimated_ba_using_speedangle",
    "estimated_woba_using_speedangle", "woba_value", "woba_denom", "babip_value", "iso_value", "launch_speed_angle",
    "at_bat_number", "pitch_number", "pitch_name", "home_score", "away_score", "bat_score", "fld_score",
    "post_away_score", "post_home_score", "post_bat_score", "post_fld_score", "if_fielding_alignment",
    "of_fielding_alignment", "spin_axis", "delta_home_win_exp", "delta_run_exp", "bat_speed", "swing_length",
    "miss_distance", "estimated_slg_using_speedangle", "delta_pitcher_run_exp", "hyper_speed", "home_score_diff",
    "bat_score_diff", "home_win_exp", "bat_win_exp", "age_pit_legacy", "age_bat_legacy", "age_pit", "age_bat",
    "n_thruorder_pitcher", "n_priorpa_thisgame_player_at_bat", "pitcher_days_since_prev_game",
    "batter_days_since_prev_game", "pitcher_days_until_next_game", "batter_days_until_next_game",
    "api_break_z_with_gravity", "api_break_x_arm", "api_break_x_batter_in", "arm_angle", "attack_angle",
    "attack_direction", "swing_path_tilt", "intercept_ball_minus_batter_pos_x_inches",
    "intercept_ball_minus_batter_pos_y_inches",
]
CATEGORY_COLS = {"pitch_type", "pitch_name", "events", "description", "game_type", "stand", "p_throws", "home_team",
                 "away_team", "type", "bb_type", "inning_topbot", "if_fielding_alignment", "of_fielding_alignment",
                 "player_name", "umpire", "sv_id", "spin_dir", "tfs_deprecated", "tfs_zulu_deprecated"}
STRING_COLS = {"des"}
DATE_COLS = {"game_date"}
# never null in a real pitch row: plain int32 on load
INT_KEY_COLS = ["game_pk", "at_bat_number", "pitch_number", "pitcher", "batter", "inning", "balls", "strikes",
                "outs_when_up", "game_year"]
INT_COLS = set(INT_KEY_COLS) | {
    "fielder_2", "fielder_3", "fielder_4", "fielder_5", "fielder_6", "fielder_7", "fielder_8", "fielder_9",
    "on_1b", "on_2b", "on_3b", "zone", "hit_location", "home_score", "away_score", "bat_score", "fld_score",
    "post_away_score", "post_home_score", "post_bat_score", "post_fld_score", "launch_speed_angle", "woba_denom",
    "babip_value", "iso_value", "home_score_diff", "bat_score_diff", "age_pit_legacy", "age_bat_legacy", "age_pit",
    "age_bat", "n_thruorder_pitcher", "n_priorpa_thisgame_player_at_bat", "pitcher_days_since_prev_game",
    "batter_days_since_prev_game", "pitcher_days_until_next_game", "batter_days_until_next_game"}


def _arrow_type(col: str) -> pa.DataType:
    if col in DATE_COLS:
        return pa.timestamp("s")
    if col in CATEGORY_COLS:
        return pa.dictionary(pa.int32(), pa.string())
    if col in STRING_COLS:
        return pa.string()
    if col in INT_COLS:
        return pa.int32()
    return pa.float32()


SCHEMA = pa.schema([pa.field(c, _arrow_type(c)) for c in COLUMNS])


# ── requests ────────────────────────────────────────────────────────────────

def search_params(level: str, lo: date | str, hi: date | str, team: str | None = None) -> dict:
    p = {"all": "true", "hfGT": canon.SAVANT_GT, "game_date_gt": str(lo), "game_date_lt": str(hi),
         "type": "details", "player_type": "pitcher"}
    if level == "aaa":
        p.update({"minors": "true", "hfLevel": "AAA|"})
    if team:
        p["hfTeam"] = f"{team}|"
    return p


def parse_csv(text: str | None) -> pd.DataFrame | None:
    """Raw search answer -> DataFrame of strings (None when the answer is not a Statcast CSV)."""
    if text is None:
        return None
    t = text.lstrip("﻿")
    if not t.strip():
        return pd.DataFrame(columns=COLUMNS)
    head = t[:200].lstrip()
    if not (head.startswith('"pitch_type"') or head.startswith("pitch_type")):
        logger.warning("savant: answer is not a Statcast CSV: %r", head[:120])
        return None
    try:
        return pd.read_csv(io.StringIO(t), dtype=str, keep_default_na=False, na_values=[""], low_memory=False)
    except (ValueError, pd.errors.ParserError) as exc:
        logger.warning("savant: CSV parse failed: %s", exc)
        return None


def fetch_range(c: Client, level: str, lo: date, hi: date, team: str | None = None, teams: Iterable[str] = (),
                capped: list | None = None) -> list[pd.DataFrame] | None:
    """Every pitch from lo to hi (inclusive) as raw-string frames, re-splitting answers that hit the CAP.
    None when a request failed (the caller retries the day on a later run)."""
    raw = parse_csv(c.get_text(SEARCH, search_params(level, lo, hi, team)))
    if raw is None:
        return None
    if len(raw) < CAP:
        return [raw]
    if capped is not None:
        capped.append([str(lo), str(hi), team, len(raw)])
    logger.info("savant %s %s..%s%s hit the %d-row cap; splitting", level, lo, hi, f" {team}" if team else "", CAP)
    if lo < hi:
        mid = lo + timedelta(days=(hi - lo).days // 2)
        a = fetch_range(c, level, lo, mid, team, teams, capped)
        b = fetch_range(c, level, mid + timedelta(days=1), hi, team, teams, capped)
        return None if a is None or b is None else a + b
    if team is None:
        names = sorted(set(teams) | set(raw["home_team"].dropna()) | set(raw["away_team"].dropna()))
        out: list[pd.DataFrame] = []
        for t in names:
            part = fetch_range(c, level, lo, hi, t, (), capped)
            if part is None:
                return None
            out += part
        return out
    logger.warning("savant %s %s team %s still capped at %d rows; kept as is", level, lo, team, CAP)
    return [raw]


# ── typing ──────────────────────────────────────────────────────────────────

def typed(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw strings -> contract types, every known column present (null where the season lacks it).
    Duplicate pitches (a split that overlapped) are dropped."""
    n = len(raw)
    out: dict[str, pd.Series] = {}
    for col in COLUMNS:
        s = raw[col] if col in raw.columns else pd.Series([None] * n, dtype=object, index=raw.index)
        if col in DATE_COLS:
            out[col] = pd.to_datetime(s, errors="coerce", format="%Y-%m-%d").astype("datetime64[s]")
        elif col in CATEGORY_COLS:
            out[col] = s.astype("string").astype("category")
        elif col in STRING_COLS:
            out[col] = s.astype("string")
        elif col in INT_COLS:
            out[col] = pd.to_numeric(s, errors="coerce").round().astype("Int32")
        else:
            out[col] = pd.to_numeric(s, errors="coerce").astype("float32")
    extra = [c for c in raw.columns if c not in SCHEMA.names]
    for col in extra:                       # new Savant columns: numeric if they parse, else category
        num = pd.to_numeric(raw[col], errors="coerce")
        if num.notna().sum() == raw[col].notna().sum():
            out[col] = num.astype("float32")
        else:
            out[col] = raw[col].astype("string").astype("category")
    df = pd.DataFrame(out, index=raw.index)
    if n:
        df = df.drop_duplicates(subset=["game_pk", "at_bat_number", "pitch_number"], keep="first")
    return df.reset_index(drop=True)


def to_table(df: pd.DataFrame) -> pa.Table:
    """A typed frame as an Arrow table on the fixed schema (extra columns appended)."""
    fields = list(SCHEMA)
    for col in df.columns:
        if col not in SCHEMA.names:
            dt = df[col].dtype
            fields.append(pa.field(col, pa.dictionary(pa.int32(), pa.string()) if isinstance(dt, pd.CategoricalDtype)
                                   else pa.float32()))
    schema = pa.schema(fields)
    arrays = []
    for f in schema:
        s = df[f.name] if f.name in df.columns else pd.Series([None] * len(df))
        if pa.types.is_dictionary(f.type):
            arr = pa.array(s.astype("string").to_numpy(dtype=object, na_value=None), type=pa.string()).dictionary_encode()
            arr = arr.cast(f.type) if arr.type != f.type else arr
        elif pa.types.is_timestamp(f.type):
            arr = pa.array(pd.to_datetime(s).astype("datetime64[s]"), type=f.type, from_pandas=True)
        elif pa.types.is_integer(f.type):
            arr = pa.array(pd.array(s, dtype="Int32"), type=f.type, from_pandas=True)
        elif pa.types.is_string(f.type):
            arr = pa.array(s.astype("string").to_numpy(dtype=object, na_value=None), type=pa.string())
        else:
            arr = pa.array(pd.to_numeric(s, errors="coerce").astype("float32"), type=f.type, from_pandas=True)
        arrays.append(arr)
    return pa.Table.from_arrays(arrays, schema=schema)


# ── season files ────────────────────────────────────────────────────────────

def load_manifest(level: str, season: int) -> dict:
    m = st.read_json(st.statcast_manifest_path(level, season)) or {}
    m.setdefault("level", level)
    m.setdefault("season", int(season))
    m.setdefault("days", {})
    m.setdefault("capped", [])
    return m


def save_manifest(m: dict) -> Path:
    return st.write_json(st.statcast_manifest_path(m["level"], m["season"]), m, indent=1)


def write_day(level: str, season: int, day: str, df: pd.DataFrame) -> Path | None:
    """One day's typed pitches as a Parquet part (an empty day removes any stale part)."""
    p = st.statcast_parts_dir(level, season) / f"{day}.parquet"
    if df is None or not len(df):
        if p.exists():
            p.unlink()
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    pq.write_table(to_table(df), tmp, compression="zstd")
    tmp.replace(p)
    return p


def compact(level: str, season: int) -> dict:
    """Stream every day part (date order) into <season>.parquet, one row group per part, on the union
    schema. Returns {"rows", "days", "columns_present"} (columns with any non-null value)."""
    parts = sorted(st.statcast_parts_dir(level, season).glob("*.parquet"))
    dest = st.statcast_path(level, season)
    if not parts:
        return {"rows": 0, "days": 0, "columns_present": []}
    fields = {f.name: f for f in SCHEMA}
    for p in parts:
        for f in pq.read_schema(p):
            fields.setdefault(f.name, f)
    schema = pa.schema(list(fields.values()))
    present: set[str] = set()
    rows = 0
    tmp = dest.with_name(dest.name + ".tmp")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with pq.ParquetWriter(tmp, schema, compression="zstd") as w:
        for p in parts:
            t = pq.read_table(p)
            for f in schema:
                if f.name not in t.column_names:
                    t = t.append_column(f, pa.nulls(t.num_rows, type=f.type))
            t = t.select(schema.names).cast(schema)
            for name in schema.names:
                if name not in present and t.column(name).null_count < t.num_rows:
                    present.add(name)
            rows += t.num_rows
            w.write_table(t)
            del t
    tmp.replace(dest)
    return {"rows": rows, "days": len(parts), "columns_present": [c for c in schema.names if c in present]}


def load_season(level: str, season: int, columns: list[str] | None = None, filters=None) -> pd.DataFrame:
    """A season's pitches as pandas: categories as category, floats float32, the key ids (game_pk, pitcher,
    batter, at_bat_number, pitch_number, inning, balls, strikes, outs_when_up, game_year) as int32, other
    int columns (runner ids, fielders, scores, zone) as nullable Int32. Pass `columns` to bound memory."""
    p = st.statcast_path(level, season)
    if not p.exists():
        return pd.DataFrame(columns=columns or COLUMNS)
    t = pq.read_table(p, columns=columns, filters=filters)
    df = t.to_pandas(types_mapper={pa.int32(): pd.Int32Dtype()}.get)
    for c in INT_KEY_COLS:
        if c in df.columns and not df[c].isna().any():
            df[c] = df[c].astype(np.int32)
    return df


# ── leaderboards (validation references only) ───────────────────────────────

LEADERBOARDS = {
    "bat-tracking": ("/leaderboard/bat-tracking", lambda y, k: {
        "attackZone": "", "batSide": "", "contactType": "", "count": "", "dateStart": "", "dateEnd": "",
        "gameType": "", "isHardHit": "", "minSwings": "q", "minGroupSwings": "1", "pitchHand": "", "pitchType": "",
        "seasonStart": y, "seasonEnd": y, "team": "", "type": k or "batter"}),
    "arm-strength": ("/leaderboard/arm-strength", lambda y, k: {"type": k or "player", "year": y, "minThrows": "50"}),
    "sprint_speed": ("/leaderboard/sprint_speed", lambda y, k: {"year": y, "position": "", "team": "", "min": "10"}),
    "outs_above_average": ("/leaderboard/outs_above_average", lambda y, k: {
        "type": k or "Fielder", "year": y, "team": "", "range": "year", "min": "q", "pos": "", "roles": "", "viz": "hide"}),
    "catcher-framing": ("/leaderboard/catcher-framing", lambda y, k: {
        "type": k or "catcher", "seasonStart": y, "seasonEnd": y, "team": "", "min": "q"}),
    "pitch-arsenal-stats": ("/leaderboard/pitch-arsenal-stats", lambda y, k: {
        "type": k or "pitcher", "pitchType": "", "year": y, "team": "", "min": "10"}),
    "swing-take": ("/leaderboard/swing-take", lambda y, k: {
        "year": y, "team": "", "leverage": "Neutral", "group": k or "Batter", "type": "All", "sub_type": "null", "min": "q"}),
    "expected_statistics": ("/leaderboard/expected_statistics", lambda y, k: {
        "type": k or "batter", "year": y, "position": "", "team": "", "filterType": "bip", "min": "q"}),
}


def leaderboard_path(name: str, season: int, kind: str | None = None) -> Path:
    return st.cache_root() / "savant" / "leaderboards" / f"{name}_{kind or 'default'}_{int(season)}.csv"


def leaderboard(c: Client | None, name: str, season: int, kind: str | None = None, refresh: bool = False) -> pd.DataFrame | None:
    """A Savant leaderboard as a DataFrame (cached under the cache root; `c=None` reads the cache only)."""
    p = leaderboard_path(name, season, kind)
    if p.exists() and not refresh:
        try:
            return pd.read_csv(p, low_memory=False)
        except (OSError, ValueError, pd.errors.ParserError):
            pass
    if c is None or name not in LEADERBOARDS:
        return None
    path, params = LEADERBOARDS[name]
    q = {k: str(v) for k, v in params(int(season), kind).items()}
    q["csv"] = "true"
    text = c.get_text(BASE + path, q)
    if not text or text.lstrip().startswith("<"):
        logger.warning("savant leaderboard %s %s: no CSV", name, season)
        return None
    try:
        df = pd.read_csv(io.StringIO(text.lstrip("﻿")), low_memory=False)
    except (ValueError, pd.errors.ParserError) as exc:
        logger.warning("savant leaderboard %s %s: %s", name, season, exc)
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.lstrip("﻿"), encoding="utf-8")
    return df


def summary(level: str, season: int) -> dict:
    """Pitches, days and columns present for a season (from the manifest; for the coverage report)."""
    m = load_manifest(level, season)
    return {"rows": sum(int(d.get("rows") or 0) for d in m["days"].values()), "days": len(m["days"]),
            "capped": len(m["capped"]), "columns_present": m.get("columns_present") or []}


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"))
