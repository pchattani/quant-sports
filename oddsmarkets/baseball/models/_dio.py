"""
Builder D's shared I/O: paths, stores, pitch-table access and plate-appearance extraction.

Everything here is defensive: builder A's `store.py` / builder C's modules are used when they exist,
and a plain reader of the contract's files is the fallback, so the prediction models run on whatever
part of the backfill has landed (newest seasons first) and on synthetic data in tests.

Paths (CONTRACT.md):  data root  $BULLPEN_DATA  (default docs/bullpen/data)
                      raw root   $BULLPEN_RAW   (default data/baseball)
                      cache      $BULLPEN_CACHE (default data/baseball/cache)

Plate appearances from the pitch table
--------------------------------------
A PA is the last pitch of each (game_pk, at_bat_number) with a non-null `events`. Its event class is

    K   strikeout, strikeout_double_play
    BB  walk, intent_walk
    HBP hit_by_pitch
    1B / 2B / 3B / HR
    GO  every other ball in play on the ground (bb_type ground_ball, or bunts), including errors,
        fielder's choices and double plays
    AO  every other ball in play in the air (fly_ball, line_drive, popup), including sac flies
    (catcher_interference and truncated PAs are dropped)

The pre-PA state (outs_when_up, on_1b/2b/3b) is read on the PA's *last* pitch, so steals and wild
pitches during the PA are not part of the PA's transition; they are measured separately as the change
between a PA's first and last pitch ("running" transitions). The post-PA state is the next PA's first
pitch in the same half-inning (3 outs when the half-inning ends). Runs on the play are
post_bat_score - bat_score on the last pitch.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
EVENTS = ("K", "BB", "HBP", "1B", "2B", "3B", "HR", "GO", "AO")
E = {e: i for i, e in enumerate(EVENTS)}
NE = len(EVENTS)

_EV_MAP = {
    "strikeout": "K", "strikeout_double_play": "K",
    "walk": "BB", "intent_walk": "BB", "hit_by_pitch": "HBP",
    "single": "1B", "double": "2B", "triple": "3B", "home_run": "HR",
}
_DROP = {"catcher_interf", "catcher_interference", "truncated_pa", "game_advisory", "ejection", "pickoff_1b", "pickoff_2b",
         "pickoff_3b", "caught_stealing_2b", "caught_stealing_3b", "caught_stealing_home", "stolen_base_2b",
         "stolen_base_3b", "stolen_base_home", "wild_pitch", "passed_ball", "pickoff_caught_stealing_2b",
         "pickoff_caught_stealing_3b", "pickoff_caught_stealing_home", "other_out", "runner_double_play"}


def data_root() -> Path:
    return Path(os.environ.get("BULLPEN_DATA") or ROOT / "docs" / "bullpen" / "data")


def raw_root() -> Path:
    return Path(os.environ.get("BULLPEN_RAW") or ROOT / "data" / "baseball")


def cache_root() -> Path:
    p = Path(os.environ.get("BULLPEN_CACHE") or ROOT / "data" / "baseball" / "cache")
    return p


def fitted_dir() -> Path:
    return Path(__file__).with_name("fitted")


# ── stores ───────────────────────────────────────────────────────────────────

def load_store(level: str, season: int) -> dict:
    """The season store (builder A's `store.load` when present, else the JSON file); {} when absent."""
    try:
        from oddsmarkets.baseball import store as bst  # type: ignore
        fn = getattr(bst, "load", None)
        if fn:
            s = fn(level, int(season))
            if s:
                return s
    except Exception as exc:  # noqa: BLE001
        logger.debug("store.load unavailable: %s", exc)
    p = data_root() / level / str(season) / "store.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.info("bad store %s: %s", p, exc)
    gz = p.with_suffix(".json.gz")
    if gz.exists():
        import gzip
        try:
            return json.loads(gzip.decompress(gz.read_bytes()).decode("utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def store_seasons(level: str = "mlb") -> list[int]:
    d = data_root() / level
    if not d.exists():
        return []
    return sorted(int(p.name) for p in d.iterdir() if p.name.isdigit() and (p / "store.json").exists())


def people() -> dict:
    p = data_root() / "people.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


# ── pitch tables ─────────────────────────────────────────────────────────────

def pitch_path(level: str, season: int) -> Path:
    return raw_root() / "statcast" / level / f"{int(season)}.parquet"


def pitch_seasons(level: str = "mlb") -> list[int]:
    d = raw_root() / "statcast" / level
    if not d.exists():
        return []
    return sorted(int(p.stem) for p in d.glob("*.parquet") if p.stem.isdigit())


PA_COLS = ["game_pk", "game_date", "game_type", "at_bat_number", "pitch_number", "pitcher", "batter", "stand", "p_throws",
           "home_team", "away_team", "inning", "inning_topbot", "outs_when_up", "balls", "strikes", "on_1b", "on_2b",
           "on_3b", "events", "bb_type", "launch_speed", "launch_angle", "estimated_woba_using_speedangle", "woba_value",
           "woba_denom", "babip_value", "iso_value", "bat_score", "post_bat_score", "fld_score", "bat_speed",
           "n_thruorder_pitcher", "pitcher_days_since_prev_game", "umpire", "delta_run_exp", "release_speed",
           "description", "type", "hc_x", "hc_y"]


def read_pitches(level: str, season: int, columns: Iterable[str] | None = None, months: Iterable[int] | None = None) -> pd.DataFrame:
    """Columns of one season's pitch table (missing columns come back null); empty frame when absent."""
    p = pitch_path(level, season)
    cols = list(columns or PA_COLS)
    if not p.exists():
        return pd.DataFrame(columns=cols)
    try:
        import pyarrow.parquet as pq
        have = set(pq.read_schema(p).names)
        use = [c for c in cols if c in have]
        df = pd.read_parquet(p, columns=use)
    except Exception as exc:  # noqa: BLE001
        logger.info("read %s failed: %s", p, exc)
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    if months is not None and len(df):
        d = pd.to_datetime(df["game_date"], errors="coerce")
        df = df[d.dt.month.isin(list(months))]
    return df


def iter_months(level: str, season: int, columns: Iterable[str] | None = None) -> Iterator[tuple[int, pd.DataFrame]]:
    """(month, frame) for each month of a season, so callers hold one month at a time."""
    p = pitch_path(level, season)
    if not p.exists():
        return
    cols = list(columns or PA_COLS)
    try:
        import pyarrow.parquet as pq
        import pyarrow.dataset as ds
        have = set(pq.read_schema(p).names)
        use = [c for c in cols if c in have]
        dset = ds.dataset(p)
        dates = pd.to_datetime(pd.Series(dset.to_table(columns=["game_date"]).column(0).to_pandas()), errors="coerce")
        months = sorted(set(dates.dt.month.dropna().astype(int)))
        del dates
    except Exception as exc:  # noqa: BLE001
        logger.info("iter_months %s failed: %s", p, exc)
        return
    import pyarrow as pa
    import pyarrow.compute as pc
    gd = dset.schema.field("game_date").type
    for m in months:
        lo = pd.Timestamp(season, m, 1)
        hi = lo + pd.offsets.MonthBegin(1)
        try:
            if pa.types.is_date(gd):
                lo_s, hi_s = pa.scalar(lo.date(), type=gd), pa.scalar(hi.date(), type=gd)
            elif pa.types.is_timestamp(gd):
                lo_s, hi_s = pa.scalar(lo.to_pydatetime(), type=gd), pa.scalar(hi.to_pydatetime(), type=gd)
            else:
                lo_s, hi_s = lo.strftime("%Y-%m-%d"), hi.strftime("%Y-%m-%d")
            f = (pc.field("game_date") >= lo_s) & (pc.field("game_date") < hi_s)
            df = dset.to_table(columns=use, filter=f).to_pandas()
        except Exception:  # noqa: BLE001
            df = read_pitches(level, season, cols, months=[m])
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        yield m, df


# ── plate appearances ────────────────────────────────────────────────────────

def _bases(df: pd.DataFrame) -> np.ndarray:
    return (df["on_1b"].notna().to_numpy().astype(np.int8) | (df["on_2b"].notna().to_numpy().astype(np.int8) << 1)
            | (df["on_3b"].notna().to_numpy().astype(np.int8) << 2))


def event_class(events: pd.Series, bb_type: pd.Series) -> np.ndarray:
    """Index into EVENTS per row, -1 for non-PA / dropped events."""
    ev = events.astype("object").fillna("").astype(str).to_numpy()
    bt = bb_type.astype("object").fillna("").astype(str).to_numpy()
    out = np.full(len(ev), -1, dtype=np.int8)
    for name, cls in _EV_MAP.items():
        out[ev == name] = E[cls]
    rest = (out < 0) & (ev != "") & ~np.isin(ev, list(_DROP))
    ground = np.isin(bt, ["ground_ball"]) | (np.char.find(ev.astype(str), "bunt") >= 0)
    out[rest & ground] = E["GO"]
    out[rest & ~ground] = E["AO"]
    return out


def plate_appearances(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per PA: game_pk, game_date, game_type, ab, inning, top, batter, pitcher, stand, p_throws, outs, bases,
    ev (EVENTS index), runs, outs_post, bases_post, balls_first..., pitches, xwoba (estimated or woba_value),
    woba_value, woba_denom, babip_value, iso_value, launch_speed, launch_angle, bat_speed(max in PA), tto, umpire,
    bases_start / outs_start / runs_before (state at the PA's first pitch: running between pitches).
    """
    if df is None or not len(df):
        return pd.DataFrame()
    d = df.sort_values(["game_pk", "at_bat_number", "pitch_number"], kind="stable")
    key = d["game_pk"].astype(np.int64).to_numpy() * 1000 + d["at_bat_number"].astype(np.int64).to_numpy()
    last = np.r_[key[1:] != key[:-1], True]
    first = np.r_[True, key[1:] != key[:-1]]
    npitch = np.diff(np.r_[np.flatnonzero(first), len(key)])
    fst = d.loc[first]
    lst = d.loc[last]
    pa = pd.DataFrame({
        "game_pk": lst["game_pk"].astype(np.int64).to_numpy(),
        "game_date": lst["game_date"].astype(str).str[:10].to_numpy(),
        "game_type": lst["game_type"].astype("object").fillna("R").astype(str).to_numpy(),
        "ab": lst["at_bat_number"].astype(np.int32).to_numpy(),
        "inning": lst["inning"].astype(np.int16).to_numpy(),
        "top": (lst["inning_topbot"].astype(str).str.lower().str.startswith("top")).to_numpy(),
        "batter": lst["batter"].astype("Int64").astype(str).to_numpy(),
        "pitcher": lst["pitcher"].astype("Int64").astype(str).to_numpy(),
        "stand": lst["stand"].astype("object").fillna("R").astype(str).to_numpy(),
        "p_throws": lst["p_throws"].astype("object").fillna("R").astype(str).to_numpy(),
        "outs": lst["outs_when_up"].fillna(0).astype(np.int8).to_numpy(),
        "bases": _bases(lst),
        "outs_start": fst["outs_when_up"].fillna(0).astype(np.int8).to_numpy(),
        "bases_start": _bases(fst),
        "score_start": fst["bat_score"].fillna(0).astype(np.int16).to_numpy(),
        "score_pre": lst["bat_score"].fillna(0).astype(np.int16).to_numpy(),
        "ev": event_class(lst["events"], lst["bb_type"]),
        "runs": (lst["post_bat_score"].fillna(lst["bat_score"]).fillna(0) - lst["bat_score"].fillna(0)).astype(np.int8).to_numpy(),
        "fld_score": lst["fld_score"].fillna(0).astype(np.int16).to_numpy(),
        "pitches": npitch.astype(np.int16),
        "xwoba": pd.to_numeric(lst["estimated_woba_using_speedangle"], errors="coerce").astype(np.float32).to_numpy(),
        "woba_value": pd.to_numeric(lst["woba_value"], errors="coerce").astype(np.float32).to_numpy(),
        "woba_denom": pd.to_numeric(lst["woba_denom"], errors="coerce").astype(np.float32).to_numpy(),
        "babip_value": pd.to_numeric(lst["babip_value"], errors="coerce").astype(np.float32).to_numpy(),
        "iso_value": pd.to_numeric(lst["iso_value"], errors="coerce").astype(np.float32).to_numpy(),
        "launch_speed": pd.to_numeric(lst["launch_speed"], errors="coerce").astype(np.float32).to_numpy(),
        "launch_angle": pd.to_numeric(lst["launch_angle"], errors="coerce").astype(np.float32).to_numpy(),
        "tto": pd.to_numeric(lst["n_thruorder_pitcher"], errors="coerce").fillna(1).astype(np.int8).to_numpy(),
        "umpire": lst["umpire"].astype("object").to_numpy() if "umpire" in lst else None,
        "home_team": lst["home_team"].astype(str).to_numpy(),
        "away_team": lst["away_team"].astype(str).to_numpy(),
    })
    bs = pd.to_numeric(d["bat_speed"], errors="coerce").to_numpy(dtype=float)
    grp = np.cumsum(first) - 1
    mx = np.full(first.sum(), np.nan)
    ok = np.isfinite(bs)
    if ok.any():
        tmp = pd.Series(bs[ok]).groupby(grp[ok]).max()
        mx[tmp.index.to_numpy()] = tmp.to_numpy()
    pa["bat_speed"] = mx.astype(np.float32)
    pa = pa[pa["ev"] >= 0].reset_index(drop=True)
    # post state: next PA in the same half-inning
    half = pa["game_pk"].to_numpy() * 100 + pa["inning"].to_numpy() * 2 + (~pa["top"].to_numpy()).astype(int)
    nxt_same = np.r_[half[1:] == half[:-1], False]
    ob = np.r_[pa["bases_start"].to_numpy()[1:], 0]
    oo = np.r_[pa["outs_start"].to_numpy()[1:], 3]
    pa["bases_post"] = np.where(nxt_same, ob, 0).astype(np.int8)
    pa["outs_post"] = np.where(nxt_same, oo, 3).astype(np.int8)
    return pa


def to_date(x: Any):
    from datetime import date, datetime
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def jdump(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":"), default=_default), encoding="utf-8")
    os.replace(tmp, path)


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


@lru_cache(maxsize=4)
def _try_import(name: str):
    try:
        import importlib
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001
        return None


def sibling(name: str):
    """A sibling builder's module (oddsmarkets.baseball.models.<name>) or None while it does not exist / fails."""
    return _try_import(f"oddsmarkets.baseball.models.{name}")
