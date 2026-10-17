"""
Season stores and data paths for The Quant Rink (CONTRACT.md section 1), mirroring nfl/store.py and baseball/store.py.

    docs/rink/data/<season>/store.json              committed for completed seasons
    docs/rink/data/calibration.json                 committed
    data/nhl/pbp/<season>/<gameId>.json.gz           api-web play-by-play (git-ignored, as every path below)
    data/nhl/shifts/<season>/<gameId>.json.gz        stats REST shift charts
    data/nhl/box/<season>/<gameId>.json.gz           api-web boxscore
    data/nhl/edge/<season>/{skater,goalie,team}/<id>.json.gz
    data/nhl/stats/<season>/<report>.json.gz         stats REST season reports (summary, realtime)
    data/nhl/moneypuck/shots_<season>.parquet        MoneyPuck shot table (benchmark only, slimmed)
    data/nhl/derived/<season>/events.parquet         one row per event, on-ice filled from shifts
    data/nhl/derived/<season>/stints.parquet         on-ice segments with events for / against
    data/nhl/derived/<season>/onice_check.json       per-game on-ice v situationCode agreement
    data/nhl/cache/espn/...                          ESPN scoreboards, summaries, core odds

Roots: RINK_DATA (default docs/rink/data), RINK_RAW (default data/nhl), RINK_CACHE (default data/nhl/cache).

store.json = {"season","updated_at","teams","games","standings","players","meta"}; GAME records
(`sources.nhl.compact_game`) are merged with `merge_game`, which never lets a thinner record wipe richer fields
(lines, goalies, attendance). Concurrent writers (the paced ESPN backfill and the NHL backfill on the same
season) go through `save_owned`, which merges only the fields each phase owns under a lock file.
"""
from __future__ import annotations

import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return Path(os.environ.get("RINK_DATA") or (ROOT / "docs" / "rink" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("RINK_RAW") or (ROOT / "data" / "nhl"))


def cache_root() -> Path:
    return Path(os.environ.get("RINK_CACHE") or (raw_root() / "cache"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── paths ───────────────────────────────────────────────────────────────────

def season_dir(season: int) -> Path:
    return data_root() / str(int(season))


def season_path(season: int) -> Path:
    return season_dir(season) / "store.json"


def calibration_path() -> Path:
    return data_root() / "calibration.json"


def pbp_path(season: int, game_id: int | str) -> Path:
    return raw_root() / "pbp" / str(int(season)) / f"{game_id}.json.gz"


def shifts_path(season: int, game_id: int | str) -> Path:
    return raw_root() / "shifts" / str(int(season)) / f"{game_id}.json.gz"


def box_path(season: int, game_id: int | str) -> Path:
    return raw_root() / "box" / str(int(season)) / f"{game_id}.json.gz"


def edge_path(season: int, kind: str, ident: int | str) -> Path:
    return raw_root() / "edge" / str(int(season)) / kind / f"{ident}.json.gz"


def stats_report_path(season: int, report: str) -> Path:
    return raw_root() / "stats" / str(int(season)) / f"{report}.json.gz"


def moneypuck_path(season: int) -> Path:
    return raw_root() / "moneypuck" / f"shots_{int(season)}.parquet"


def derived_dir(season: int) -> Path:
    return raw_root() / "derived" / str(int(season))


def events_path(season: int) -> Path:
    return derived_dir(season) / "events.parquet"


def stints_path(season: int) -> Path:
    return derived_dir(season) / "stints.parquet"


def onice_check_path(season: int) -> Path:
    return derived_dir(season) / "onice_check.json"


def espn_dir(kind: str, season: int) -> Path:
    return cache_root() / "espn" / kind / str(int(season))


# ── JSON helpers ────────────────────────────────────────────────────────────

def write_json(p: Path, obj: Any, indent: int | None = None) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    if indent:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")
    else:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)
    return p


def read_json(p: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json_gz(p: Path, obj: Any) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(p)
    return p


def read_json_gz(p: Path) -> Any:
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, EOFError):
        return None


# ── season stores ───────────────────────────────────────────────────────────

def new_store(season: int) -> dict[str, Any]:
    return {"season": int(season), "updated_at": None, "teams": {}, "games": {}, "standings": None, "players": {},
            "meta": {"weeks": {}, "complete_through": None, "fetched": {}, "espn_days": {}, "espn_odds": {},
                     "edge": {}, "sources": {}}}


def load(season: int) -> dict[str, Any]:
    s = read_json(season_path(season))
    if not isinstance(s, dict):
        return new_store(season)
    base = new_store(season)
    for k, v in base.items():
        s.setdefault(k, v)
    for k, v in base["meta"].items():
        s["meta"].setdefault(k, v)
    return s


def _game_key(kv):
    g = kv[1]
    return (g.get("start") or g.get("date") or "", kv[0])


def save(store: dict[str, Any]) -> Path:
    store["updated_at"] = now()
    store["games"] = dict(sorted(store["games"].items(), key=_game_key))
    return write_json(season_path(store["season"]), store)


class Lock:
    """A lock file beside a store (the ESPN backfill and the NHL backfill may write the same season). Stale locks
    (older than `stale` seconds; a save takes about a second) are broken well before a waiter gives up."""

    def __init__(self, path: Path, wait: float = 900.0, stale: float = 120.0):
        self.path, self.wait, self.stale = Path(str(path) + ".lock"), wait, stale

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() - t0 > self.wait:
                    raise TimeoutError(f"lock {self.path} held too long")
                time.sleep(0.2)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


# Fields each fetch phase owns. The schedule phase owns the GAME core (and teams, standings, players);
# box owns goalies (pbp fills them only for a game without a boxscore); espn owns lines, espn_id and attendance; pbp / shifts / derive own nothing in the GAME
# (their state lives in meta); edge owns meta.edge.
OWNED_GAME = {"schedule": (), "box": ("goalies",), "espn": ("lines", "espn_id", "attendance"),
              "pbp": ("goalies",), "shifts": (), "edge": (), "moneypuck": ()}
OWNED_META = {"schedule": ("weeks", "complete_through", "sources", "season_dates", "rosters_at"),
              "pbp": ("pbp",), "shifts": ("shifts", "html_retry"), "box": ("box", "reports"),
              "espn": ("espn_days", "espn_odds", "espn_summary"), "edge": ("edge",), "moneypuck": ("moneypuck",),
              "derive": ("derived",)}
OWNED_TOP = {"schedule": ("teams", "players"), "pbp": ("players",), "box": ("players",)}
OWNED_SCALAR = {"schedule": ("standings",)}
_OWNED_ANY = {f for fs in OWNED_GAME.values() for f in fs}


def save_owned(store: dict[str, Any], phases: Iterable[str]) -> Path:
    """Lock, re-read the store from disk, merge in what `phases` own from the in-memory store, write, and refresh
    the in-memory store with the merged result."""
    phases = set(phases)
    path = season_path(store["season"])
    with Lock(path):
        disk = load(store["season"])
        for gid, g in store["games"].items():
            d = disk["games"].get(gid)
            if d is None:
                if "schedule" in phases:
                    disk["games"][gid] = g
                continue
            if "schedule" in phases:
                new = dict(d)
                for k, v in g.items():
                    if k in _OWNED_ANY:
                        continue
                    if k in _KEEP_IF_EMPTY and v in (None, {}, [], "") and d.get(k) not in (None, {}, [], ""):
                        continue
                    new[k] = v
                disk["games"][gid] = d = new
            for p in phases:
                for f in OWNED_GAME.get(p, ()):
                    if f in g and (g[f] not in (None, {}, []) or d.get(f) in (None, {}, [])):
                        d[f] = g[f]
        for p in phases:
            for k in OWNED_META.get(p, ()):
                if k in store["meta"]:
                    disk["meta"][k] = store["meta"][k]
            for k in OWNED_TOP.get(p, ()):
                cur = disk.setdefault(k, {})
                for pid, rec in (store.get(k) or {}).items():
                    cur[pid] = {**(cur.get(pid) or {}), **{a: b for a, b in rec.items() if b is not None}}
            for k in OWNED_SCALAR.get(p, ()):
                if store.get(k) is not None:
                    disk[k] = store[k]
        out = save(disk)
    store.clear()
    store.update(disk)
    return out


_KEEP_IF_EMPTY = ("lines", "goalies", "attendance", "espn_id", "venue", "start", "hs", "as")


def merge_game(store: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a GAME, keeping richer fields the new record lacks (a schedule rescan never wipes ESPN
    lines, goalies or attendance; a final game never goes back to scheduled)."""
    gid = str(game["game_id"])
    old = store["games"].get(gid)
    if not old:
        store["games"][gid] = game
        return game
    new = dict(old)
    for k, v in game.items():
        if k in _KEEP_IF_EMPTY and v in (None, {}, [], "") and old.get(k) not in (None, {}, [], ""):
            continue
        new[k] = v
    if old.get("status") == "final" and game.get("status") in ("scheduled", "live"):
        for k in ("status", "hs", "as", "period", "ot", "so"):
            new[k] = old.get(k)
    store["games"][gid] = new
    return new


def mark(store: dict[str, Any], key: str, what: str = "fetched", value: Any = None) -> None:
    store["meta"].setdefault(what, {})[str(key)] = value if value is not None else now()


def complete_through(store: dict[str, Any]) -> str | None:
    """The last date through which every game is final (or postponed / cancelled)."""
    last = None
    for g in sorted(store["games"].values(), key=lambda g: (g.get("date") or "", g.get("start") or "")):
        if g.get("status") in ("postponed", "cancelled"):
            continue
        if g.get("status") == "final":
            last = g.get("date")
        else:
            break
    return last


def seasons_on_disk() -> list[int]:
    d = data_root()
    if not d.exists():
        return []
    return sorted(int(x.name) for x in d.iterdir() if x.is_dir() and x.name.isdigit() and (x / "store.json").exists())
