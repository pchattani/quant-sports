"""
Shared plumbing for builder B's tennis models (elo, serve_return, bt): data and cache roots
(env `ACE_DATA`, default docs/ace/data; env `ACE_CACHE`, default data/tennis/cache), the committed
fits folder (models/fitted), a loader of MATCH rows from docs/ace/data/<tour>/<year>/store.json,
surface/level folding, and a JSON cache keyed on the input files' sizes and modification times.
Nothing here raises on missing or unreadable files.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
FITTED = Path(__file__).resolve().parent / "fitted"

TOURS = ("atp", "wta")
SURFACES = ("hard", "clay", "grass")            # carpet folds into hard (indoor flag kept separately)
LEVELS = ("slam", "finals", "m1000", "500", "250", "other", "ch", "q")
TOUR_LEVELS = ("slam", "finals", "m1000", "500", "250", "other")
ROUND_ORDER = {"Q1": 0, "Q2": 1, "Q3": 2, "R128": 3, "R64": 4, "R32": 5, "R16": 6, "RR": 7, "QF": 8, "SF": 9,
               "BR": 10, "F": 11}
RATED_STATUS = ("done", "ret", "def")


def tour_key(tour: Any) -> str:
    return "wta" if str(tour or "").lower() == "wta" else "atp"


def data_root() -> Path:
    return Path(os.environ.get("ACE_DATA") or (ROOT / "docs" / "ace" / "data"))


def cache_root() -> Path:
    return Path(os.environ.get("ACE_CACHE") or (ROOT / "data" / "tennis" / "cache"))


def store_path(tour: str, year: int) -> Path:
    return data_root() / tour_key(tour) / str(int(year)) / "store.json"


def years_on_disk(tour: str) -> list[int]:
    root = data_root() / tour_key(tour)
    try:
        return sorted(int(d.name) for d in root.iterdir() if d.name.isdigit() and (d / "store.json").exists())
    except OSError:
        return []


def load_store(tour: str, year: int) -> dict | None:
    try:
        return json.loads(store_path(tour, year).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def signature(tour: str, years: Iterable[int] | None = None) -> list:
    """[[year, size, mtime_ns]] of the stores read: the cache key."""
    out = []
    for y in (years_on_disk(tour) if years is None else years):
        try:
            st = store_path(tour, y).stat()
            out.append([int(y), st.st_size, st.st_mtime_ns])
        except OSError:
            out.append([int(y), None, None])
    return out


def day(d: Any) -> date | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def fold_surface(s: Any) -> str:
    s = str(s or "").lower()
    return s if s in ("clay", "grass") else "hard"


def fold_level(lv: Any) -> str:
    lv = str(lv or "").lower()
    return lv if lv in LEVELS else "250"


def match_key(m: dict) -> tuple:
    return (str(m.get("date") or "")[:10], ROUND_ORDER.get(str(m.get("round") or ""), 5), str(m.get("id") or ""))


def load_matches(tour: str, years: Iterable[int] | None = None, through: Any = None,
                 statuses: Iterable[str] | None = RATED_STATUS) -> list[dict]:
    """MATCH rows of `tour` from the stores on disk (all years by default), dated (a missing date takes
    the event's start), filtered to `statuses` (None keeps every status) and to date <= `through`,
    sorted by (date, round, id)."""
    t = tour_key(tour)
    th = day(through) if through is not None else None
    keep = set(statuses) if statuses is not None else None
    out: list[dict] = []
    for y in (years_on_disk(t) if years is None else years):
        st = load_store(t, y)
        if not st:
            continue
        events = st.get("events") or {}
        for mid, m in (st.get("matches") or {}).items():
            if not isinstance(m, dict):
                continue
            if keep is not None and m.get("status") not in keep:
                continue
            ev_start = (events.get(m.get("event")) or {}).get("start")
            d = m.get("date") or ev_start
            dd = day(d)
            if dd is None or abs(dd.year - int(y)) > 1:      # a garbled date: fall back to the event's start
                d = ev_start if (day(ev_start) and abs(day(ev_start).year - int(y)) <= 1) else None
            if not d:
                continue
            if th is not None and day(d) is not None and day(d) > th:
                continue
            if not m.get("id"):
                m = dict(m, id=mid)
            if m.get("date") != d:
                m = dict(m, date=str(d)[:10])
            out.append(m)
    out.sort(key=match_key)
    return out


def file_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
        h.update(b"|")
    return h.hexdigest()


FIT_FILES = ("predict", "serve_return", "elo_params")


def fits_signature(tour: str) -> str:
    """A digest of the tour's committed fits (models/fitted/{predict,serve_return,elo_params}_<tour>.json),
    parsed, so line endings do not matter: page signatures include it, and a refit rebuilds finished pages."""
    t = tour_key(tour)
    h = hashlib.sha1()
    for name in FIT_FILES:
        h.update(json.dumps(read_json(FITTED / f"{name}_{t}.json"), sort_keys=True, separators=(",", ":")).encode())
        h.update(b"|")
    return h.hexdigest()[:20]


def read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj: Any, indent: int | None = None, nd: int = 6) -> bool:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(clean(obj, nd), indent=indent, separators=None if indent else (",", ":")),
                       encoding="utf-8")
        tmp.replace(path)
        return True
    except (OSError, TypeError, ValueError):
        return False


def cached(kind: str, name: str, key: str, build: Callable[[], Any], use_cache: bool = True) -> Any:
    """JSON cache under cache_root()/kind/name.json, invalidated by `key`. Never raises on IO."""
    path = cache_root() / kind / f"{name}.json"
    if use_cache:
        c = read_json(path)
        if isinstance(c, dict) and c.get("key") == key:
            return c.get("result")
    out = build()
    if use_cache:
        write_json(path, {"key": key, "result": out})
    return out


def clean(x: Any, nd: int = 6) -> Any:
    """JSON-safe copy: numpy scalars to Python, floats rounded, non-finite to None, tuple keys to "g1-g2"."""
    if isinstance(x, dict):
        return {(f"{k[0]}-{k[1]}" if isinstance(k, tuple) else k): clean(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v, nd) for v in x]
    if isinstance(x, np.ndarray):
        return clean(x.tolist(), nd)
    if isinstance(x, (bool, np.bool_)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        v = float(x)
        return round(v, nd) if math.isfinite(v) else None
    return x
