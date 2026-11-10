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


MERGE_REPORT: dict = {}
_EXTRA: dict = {}


def bios() -> dict:
    """The ESPN core-API bios (scripts/scrum_bios.py): {athlete_id: {dob, ht_cm, wt_kg, pos, born, city}}."""
    p = side_dir() / "bios.json.gz"
    k = ("bios", str(p))
    if k not in _EXTRA:
        try:
            _EXTRA[k] = (read_gz(p) or {}).get("athletes") or {} if p.exists() else {}
        except (OSError, ValueError):
            _EXTRA[k] = {}
    return _EXTRA[k]


def load_all(scope: str, upto: int | None = None, tests_only: bool = True, with_bios: bool = True,
             with_wiki: bool = True, with_sofa: bool = True) -> tuple[list[dict], dict]:
    """Every match of a scope (sorted by date) and the merged athlete table. For the international scopes,
    tests_only drops tour matches against club and provincial sides (a Lions tour's midweek games) and shows each
    nation under one name (nations.canonical). with_bios fills a player's missing bio fields from the core-API
    bios store (a field the match summaries gave wins). with_wiki adds the Wikipedia-only tests (every test before
    ESPN's coverage, the small nations) and the referee and attendance of ESPN's tests (wiki.merge; off with
    SOURCE_WIKIPEDIA_RUGBY_ENABLED=0). with_sofa then merges the Sofascore side store (sofa.merge: statistics for
    tests ESPN carries without them, and the tests only Sofascore has; off with SOURCE_SOFASCORE_RUGBY_ENABLED=0)."""
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
    if with_bios:
        for k, b in bios().items():
            cur = athletes.get(k)
            if cur is not None:
                for kk, vv in b.items():
                    if vv and not cur.get(kk):
                        cur[kk] = vv
    matches.sort(key=lambda m: (m.get("date") or "", m.get("id")))
    if with_wiki and tests_only and scope in ("men", "women"):
        from . import wiki
        matches, rep = wiki.merge(scope, matches)
        if with_sofa:
            from . import sofa
            matches, srep = sofa.merge(scope, matches, athletes)
            rep = dict(rep, sofascore=srep)
        if upto is not None:
            matches = [m for m in matches if int(str(m.get("date") or "0")[:4] or 0) <= upto]
        MERGE_REPORT[scope] = rep
    if tests_only:
        attach_elevation(matches)
    return matches, athletes


def save(scope: str, year: int, matches: list[dict], athletes: dict) -> Path:
    return write_gz(store_path(scope, year), {"v": VERSION, "scope": scope, "year": int(year), "built": now(),
                                               "matches": matches, "athletes": athletes})


def stores_extra(name: str, key: str = "matches") -> dict:
    """A side store keyed by match or venue (weather.json.gz -> "matches", venues.json.gz -> "venues"); {} when
    missing or unreadable. Cached per process."""
    p = side_dir() / f"{name}.json.gz"
    k = (name, key, str(p))
    if k not in _EXTRA:
        try:
            _EXTRA[k] = (read_gz(p) or {}).get(key) or {} if p.exists() else {}
        except (OSError, ValueError):
            _EXTRA[k] = {}
    return _EXTRA[k]


def attach_elevation(matches: list[dict]) -> int:
    """Each match's venue elevation (m) from the venues store (scripts/scrum_weather.py, Open-Meteo) as
    match["venue"]["elev"]; static, so no look-ahead. Nothing when SOURCE_OPENMETEO_RUGBY_ENABLED=0."""
    import os
    if (os.environ.get("SOURCE_OPENMETEO_RUGBY_ENABLED") or "1").strip().lower() in ("0", "false", "no", "off", ""):
        return 0
    vs = stores_extra("venues", "venues")
    n = 0
    for m in matches:
        v = m.get("venue")
        if not isinstance(v, dict):
            continue
        rec = vs.get(f"{(v.get('name') or '').strip()}|{(v.get('city') or '').strip()}")
        e = (rec or {}).get("elev")
        if isinstance(e, (int, float)):
            v["elev"] = round(float(e))
            n += 1
    return n


def side_dir() -> Path:
    """The second-wave side stores (2 Nov 2026): bios.json.gz (ESPN core-API bios), venues.json.gz and
    weather.json.gz (Open-Meteo), wiki/<scope>.json.gz (Wikipedia). Fetched on the PC only; they reach CI in the
    stores snapshot (scripts/push_stores.py, ci_site.py FEEDS) and the seed branch. Private, never published."""
    return paths()["stores"] / "side"
