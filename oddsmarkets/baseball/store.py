"""
Season stores and data paths for The Quant Bullpen (CONTRACT.md section 1), mirroring basketball/store.py.

    docs/bullpen/data/<level>/<season>/store.json     committed for completed seasons
    docs/bullpen/data/people.json                     identity crosswalk (Chadwick register, ODC-BY)
    data/baseball/statcast/<level>/<season>.parquet   pitch table (git-ignored)
    data/baseball/statcast/<level>/<season>.parts/    per-day Parquet parts the season file is compacted from
    data/baseball/statcast/<level>/<season>.manifest.json
    data/baseball/retro/pa/<season>.parquet           Retrosheet events (git-ignored)
    data/baseball/retro/games/<season>.parquet        Retrosheet game logs
    data/baseball/cache/...                           raw downloads (zips, leaderboards, feeds)

Roots: BULLPEN_DATA (default docs/bullpen/data), BULLPEN_RAW (default data/baseball), BULLPEN_CACHE
(default data/baseball/cache).

store.json = {"level","season","updated_at","teams","venues","players","games","meta"}; GAME records are
built by sources/statsapi.compact_game and merged with `merge_game`, which never lets a thinner record
wipe richer fields (lines, lineups, abs, weather).
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]


def data_root() -> Path:
    return Path(os.environ.get("BULLPEN_DATA") or (ROOT / "docs" / "bullpen" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("BULLPEN_RAW") or (ROOT / "data" / "baseball"))


def cache_root() -> Path:
    return Path(os.environ.get("BULLPEN_CACHE") or (raw_root() / "cache"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── paths ───────────────────────────────────────────────────────────────────

def season_dir(level: str, season: int) -> Path:
    return data_root() / str(level) / str(int(season))


def season_path(level: str, season: int) -> Path:
    return season_dir(level, season) / "store.json"


def people_path() -> Path:
    return data_root() / "people.json"


def calibration_path(level: str) -> Path:
    return data_root() / str(level) / "calibration.json"


def statcast_path(level: str, season: int) -> Path:
    return raw_root() / "statcast" / str(level) / f"{int(season)}.parquet"


def statcast_parts_dir(level: str, season: int) -> Path:
    return raw_root() / "statcast" / str(level) / f"{int(season)}.parts"


def statcast_manifest_path(level: str, season: int) -> Path:
    return raw_root() / "statcast" / str(level) / f"{int(season)}.manifest.json"


def retro_pa_path(season: int) -> Path:
    return raw_root() / "retro" / "pa" / f"{int(season)}.parquet"


def retro_games_path(season: int) -> Path:
    return raw_root() / "retro" / "games" / f"{int(season)}.parquet"


def feed_path(level: str, season: int, gpk: str) -> Path:
    return cache_root() / "feeds" / str(level) / str(int(season)) / f"{gpk}.json.gz"


# ── JSON helpers ────────────────────────────────────────────────────────────

def write_json(p: Path, obj: Any, indent: int | None = None) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
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
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
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

def new_store(level: str, season: int) -> dict[str, Any]:
    return {"level": str(level), "season": int(season), "updated_at": None, "teams": {}, "venues": {}, "players": {},
            "umpires": {},
            "games": {}, "meta": {"days": {}, "fetched": {}, "complete_through": None}}


def load(level: str, season: int) -> dict[str, Any]:
    s = read_json(season_path(level, season))
    if not isinstance(s, dict):
        return new_store(level, season)
    for k, v in new_store(level, season).items():
        s.setdefault(k, v)
    for k, v in new_store(level, season)["meta"].items():
        s["meta"].setdefault(k, v)
    return s


def save(store: dict[str, Any]) -> Path:
    store["updated_at"] = now()
    store["games"] = dict(sorted(store["games"].items(), key=lambda kv: (kv[1].get("start") or kv[1].get("date") or "", kv[0])))
    return write_json(season_path(store["level"], store["season"]), store)


class Lock:
    """A lock file beside a store (several backfill processes write the same season: Savant marks
    has_statcast, ESPN adds lines). Stale locks (older than `stale` seconds) are broken."""

    def __init__(self, path: Path, wait: float = 300.0, stale: float = 600.0):
        self.path, self.wait, self.stale = Path(str(path) + ".lock"), wait, stale

    def __enter__(self):
        import time
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


# Fields of a GAME / meta / top-level keys each fetch phase owns (save_owned merges only these into the
# copy on disk, so concurrent processes running different phases never undo each other's work).
OWNED_GAME = {"statcast": ("has_statcast",), "games": ("abs", "mound_visits", "lineups"), "espn": ("espn", "lines"),
              "people": ()}
OWNED_META = {"schedule": ("weeks", "teams_at", "complete_through", "standings", "rosters", "rosters_at"),
              "statcast": (), "games": ("feed",), "espn": ("espn_days", "espn_odds"), "people": ("crosswalk",)}
OWNED_TOP = {"schedule": ("teams", "venues"), "people": ("players", "umpires")}


def save_owned(store: dict[str, Any], phases: Iterable[str]) -> Path:
    """Lock, re-read the store from disk, merge in what `phases` own from the in-memory store, write, and
    refresh the in-memory store with the merged result."""
    phases = set(phases)
    path = season_path(store["level"], store["season"])
    with Lock(path):
        disk = load(store["level"], store["season"])
        for gpk, g in store["games"].items():
            d = disk["games"].get(gpk)
            if d is None:
                if "schedule" in phases:
                    disk["games"][gpk] = g
                continue
            if "schedule" in phases:
                for k, v in g.items():
                    if k in _OWNED_ANY and k not in _SCHEDULE_TOO:
                        continue
                    if k in _KEEP_IF_EMPTY and not v and d.get(k):
                        continue
                    d[k] = v
            for p in phases:
                for f in OWNED_GAME.get(p, ()):
                    if f in g and (g[f] or not d.get(f)):
                        d[f] = g[f]
        for p in phases:
            for k in OWNED_META.get(p, ()):
                if k in store["meta"]:
                    disk["meta"][k] = store["meta"][k]
            for k in OWNED_TOP.get(p, ()):
                disk.setdefault(k, {}).update(store.get(k) or {})
        out = save(disk)
    store.clear()
    store.update(disk)
    return out


_OWNED_ANY = {f for fs in OWNED_GAME.values() for f in fs}
_SCHEDULE_TOO = {"lineups"}          # the schedule's starting nine; the feed only fills games without one


def seasons_on_disk(level: str) -> list[int]:
    d = data_root() / str(level)
    if not d.exists():
        return []
    return sorted(int(x.name) for x in d.iterdir() if x.is_dir() and x.name.isdigit() and (x / "store.json").exists())


_KEEP_IF_EMPTY = ("lines", "lineups", "abs", "weather", "umpire_hp", "venue", "series", "innings", "decisions", "espn",
                  "probables")


def merge_game(store: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a GAME, keeping richer fields the new record lacks (a schedule rescan never wipes
    lines or ABS counts fetched separately; has_statcast only ever turns on)."""
    gpk = str(game["gpk"])
    old = store["games"].get(gpk)
    if not old:
        store["games"][gpk] = game
        return game
    new = dict(old)
    for k, v in game.items():
        if k in _KEEP_IF_EMPTY and not v and old.get(k):
            continue
        if k == "probables" and isinstance(v, dict) and isinstance(old.get(k), dict):
            v = {side: v.get(side) or old[k].get(side) for side in ("home", "away")}
        if k == "has_statcast" and not v and old.get(k):
            continue
        new[k] = v
    store["games"][gpk] = new
    return new


def mark(store: dict[str, Any], gpk: str, what: str = "fetched") -> None:
    store["meta"].setdefault(what, {})[str(gpk)] = now()


def fetched(store: dict[str, Any], gpk: str, what: str = "fetched") -> bool:
    return str(gpk) in (store["meta"].get(what) or {})


def complete_through(store: dict[str, Any]) -> str | None:
    """The last date through which every game is final (or postponed/cancelled)."""
    last = None
    for g in sorted(store["games"].values(), key=lambda g: g.get("date") or ""):
        if g.get("status") in ("postponed", "cancelled"):
            continue
        if g.get("status") == "final":
            last = g.get("date")
        else:
            break
    return last
