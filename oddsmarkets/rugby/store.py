"""
Season stores for The Quant Scrum: one gzipped JSON per scope and calendar year, the single source every model and
payload reads.

    data/rugby/stores/<scope>/<year>.json.gz   {"v", "scope", "year", "built", "matches": [...], "athletes": {...}}
    data/rugby/raw/sb/<slug>/<year>.json.gz     ESPN scoreboards as fetched (local cache, never published)
    data/rugby/raw/summary/<nn>/<id>.json.gz    ESPN summaries as fetched (local cache, never published)

A match row (sources/espn.parse_event, then the summary's lineups merged in):
    id, comp, slug, season, date (ISO UTC), status (pre | live | final | off), neutral, venue {name, city, country},
    home / away {id, name, abbr, colour, alt}, hs, as, hh / ah (half scores), hstat / astat (team stats, espn.TEAM_KEYS),
    events [[minute, type, side, athlete_id, name, home_score, away_score]], lh / la (matchday 23:
    [athlete_id, jersey, pos, starter, captain, stats]), attendance
Athletes: {id: {name, short, dob, ht_cm, wt_kg, pos, born}}.

Roots: RUGBY_STORES (default data/rugby/stores), RUGBY_RAW (data/rugby/raw), SCRUM_DATA (docs/scrum/data). The stores
reach CI through the Actions cache and the private stores repo (seed-scrum branch, scripts/push_seed.py); they are
never part of the public build. Writes are atomic.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VERSION = 1


def paths() -> dict[str, Path]:
    return {"stores": Path(os.environ.get("RUGBY_STORES") or (ROOT / "data" / "rugby" / "stores")),
            "raw": Path(os.environ.get("RUGBY_RAW") or (ROOT / "data" / "rugby" / "raw")),
            "cache": Path(os.environ.get("RUGBY_CACHE") or (ROOT / "data" / "rugby" / "cache")),
            "data": Path(os.environ.get("SCRUM_DATA") or (ROOT / "docs" / "scrum" / "data"))}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_path(scope: str, year: int) -> Path:
    return paths()["stores"] / str(scope) / f"{int(year)}.json.gz"


def write_gz(p: Path, obj: Any) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)
    return p


def read_gz(p: Path) -> Any:
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def years(scope: str) -> list[int]:
    d = paths()["stores"] / scope
    if not d.is_dir():
        return []
    return sorted(int(p.name.split(".")[0]) for p in d.glob("*.json.gz") if p.name.split(".")[0].isdigit())


def load(scope: str, year: int) -> dict | None:
    p = store_path(scope, year)
    if not p.exists():
        return None
    try:
        return read_gz(p)
    except (OSError, ValueError):
        return None


def load_all(scope: str, upto: int | None = None, tests_only: bool = True) -> tuple[list[dict], dict]:
    """Every match of a scope (sorted by date) and the merged athlete table. For the international scopes,
    tests_only drops tour matches against club and provincial sides (a Lions tour's midweek games) and shows each
    nation under one name (nations.canonical)."""
    from . import nations
    matches, athletes = [], {}
    for y in years(scope):
        if upto is not None and y > upto:
            continue
        s = load(scope, y) or {}
        for m in s.get("matches") or []:
            if tests_only and scope in ("men", "women"):
                h, a = (m.get("home") or {}).get("name"), (m.get("away") or {}).get("name")
                if not nations.is_side(h) or not nations.is_side(a):
                    continue
                m["home"]["name"], m["away"]["name"] = nations.canonical(h), nations.canonical(a)
            matches.append(m)
        for k, v in (s.get("athletes") or {}).items():
            cur = athletes.get(k)
            athletes[k] = v if cur is None else {**cur, **{kk: vv for kk, vv in v.items() if vv}}
    matches.sort(key=lambda m: (m.get("date") or "", m.get("id")))
    return matches, athletes


def save(scope: str, year: int, matches: list[dict], athletes: dict) -> Path:
    return write_gz(store_path(scope, year), {"v": VERSION, "scope": scope, "year": int(year), "built": now(),
                                               "matches": matches, "athletes": athletes})
