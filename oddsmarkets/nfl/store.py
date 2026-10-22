"""
Season stores and data paths for The Quant Gridiron (CONTRACT.md section 1), mirroring baseball/store.py.

    docs/gridiron/data/<season>/store.json            committed for completed seasons
    docs/gridiron/data/calibration.json               committed
    data/nfl/raw/<release>/<file>.parquet              nflverse release mirror (git-ignored)
    data/nfl/raw/<release>/_manifest.json              timestamp gate: release timestamp + per-file ETag
    data/nfl/derived/<season>/plays.parquet            compact play table (pbp subset + FTN + participation)
    data/nfl/cache/espn/...                            ESPN summaries (compact live records), raw odds

Roots: GRIDIRON_DATA (default docs/gridiron/data), GRIDIRON_RAW (default data/nfl), GRIDIRON_CACHE
(default data/nfl/cache).

store.json = {"season","updated_at","teams","games","meta"}; GAME (CONTRACT.md) records are built by
sources/nflverse.compact_game from the schedules and merged with `merge_game`, which never lets a thinner
record wipe richer fields (ESPN lines, a live state). Concurrent writers (the paced ESPN odds backfill and a
schedules rebuild) go through `save_owned`, which merges only the fields each phase owns under a lock file.
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
    return Path(os.environ.get("GRIDIRON_DATA") or (ROOT / "docs" / "gridiron" / "data"))


def raw_root() -> Path:
    return Path(os.environ.get("GRIDIRON_RAW") or (ROOT / "data" / "nfl"))


def cache_root() -> Path:
    return Path(os.environ.get("GRIDIRON_CACHE") or (raw_root() / "cache"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── paths ───────────────────────────────────────────────────────────────────

def season_dir(season: int) -> Path:
    return data_root() / str(int(season))


def season_path(season: int) -> Path:
    return season_dir(season) / "store.json"


def calibration_path() -> Path:
    return data_root() / "calibration.json"


def release_dir(release: str) -> Path:
    return raw_root() / "raw" / str(release)


def release_path(release: str, filename: str) -> Path:
    return release_dir(release) / filename


def manifest_path(release: str) -> Path:
    return release_dir(release) / "_manifest.json"


def derived_dir(season: int) -> Path:
    return raw_root() / "derived" / str(int(season))


def plays_path(season: int) -> Path:
    return derived_dir(season) / "plays.parquet"


def espn_summary_path(season: int, game_id: str) -> Path:
    return cache_root() / "espn" / "summary" / str(int(season)) / f"{game_id}.json"


def espn_odds_raw_path(season: int, game_id: str) -> Path:
    return cache_root() / "espn" / "odds" / str(int(season)) / f"{game_id}.json.gz"


def espn_summary_keep_path(season: int, game_id: str) -> Path:
    """A final game's compact ESPN record, kept beyond the day's model cache (round 4, 22 Oct 2026): under the raw
    root, which CI saves whenever it changes, so a game that finishes after the day's cache save still has an ESPN
    fallback until nflverse publishes its play-by-play."""
    return raw_root() / "raw" / "espn_summary" / str(int(season)) / f"{game_id}.json.gz"


def read_espn_summary(season: int, game_id: str) -> dict | None:
    """The compact ESPN record of a game: the day's cache, else the kept final copy."""
    rec = read_json(espn_summary_path(season, game_id))
    if rec:
        return rec
    p = espn_summary_keep_path(season, game_id)
    return read_json_gz(p) if p.exists() else None


# ── timestamped injury snapshots (ESPN keeps no history) ────────────────────

INJURY_LOG = "injury_log.json.gz"


def injury_log_path(season: int) -> Path:
    return season_dir(season) / INJURY_LOG


def load_injury_log(season: int) -> dict:
    """{"teams": {abbr: [[fetched_at, [[espn_athlete_id, status, espn_date, type, location, return_date, pos], ...]], ...]},
    "updated_at"}: every change of a team's ESPN injury list, stamped with the first fetch that saw it."""
    p = injury_log_path(season)
    d = read_json_gz(p) if p.exists() else None
    return d if isinstance(d, dict) and isinstance(d.get("teams"), dict) else {"teams": {}, "updated_at": None}


def append_injury_log(log: dict, team: str, at: str, rows: list[list]) -> bool:
    """Append one team's snapshot only when it differs from that team's last one. Returns whether it was appended."""
    snaps = log["teams"].setdefault(str(team), [])
    norm = sorted([str(r[0])] + [None if v is None else str(v) for v in r[1:]] for r in rows)
    if snaps and snaps[-1][1] == norm:
        return False
    snaps.append([at, norm])
    return True


def save_injury_log(season: int, log: dict) -> Path:
    log["updated_at"] = now()
    return write_json_gz(injury_log_path(season), log)


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
    return {"season": int(season), "updated_at": None, "teams": {}, "games": {},
            "meta": {"fetched": {}, "complete_through": None, "espn_odds": {}, "sources": {}}}


# GAME keys no longer stored: `pfr_id` (Pro Football Reference's game id, left out for its terms). Stripped on every
# load and save so an older or hydrated store cannot carry them into a published one.
DROPPED_GAME_KEYS = ("pfr_id",)


def scrub(store: dict[str, Any]) -> dict[str, Any]:
    for g in (store.get("games") or {}).values():
        if isinstance(g, dict):
            for k in DROPPED_GAME_KEYS:
                g.pop(k, None)
    return store


def load(season: int) -> dict[str, Any]:
    s = read_json(season_path(season))
    if not isinstance(s, dict):
        return new_store(season)
    base = new_store(season)
    for k, v in base.items():
        s.setdefault(k, v)
    for k, v in base["meta"].items():
        s["meta"].setdefault(k, v)
    return scrub(s)


def _game_key(kv):
    g = kv[1]
    return (g.get("kickoff") or g.get("date") or "", kv[0])


def save(store: dict[str, Any]) -> Path:
    store["updated_at"] = now()
    scrub(store)
    store["games"] = dict(sorted(store["games"].items(), key=_game_key))
    return write_json(season_path(store["season"]), store)


class Lock:
    """A lock file beside a store (the ESPN odds backfill and a schedules rebuild may write the same season).
    Stale locks (older than `stale` seconds) are broken."""

    def __init__(self, path: Path, wait: float = 300.0, stale: float = 600.0):
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


# Fields each fetch phase owns. `lines` is shared: the schedule phase owns nflverse's closing line keys,
# the espn phase owns ESPN's open/close/books; save_owned merges the two halves.
LINES_SCHEDULE = ("spread_home", "total", "ml_home", "ml_away", "spread_price", "total_price", "src")
LINES_ESPN = ("open", "close", "books", "consensus", "espn_src")
OWNED_GAME = {"schedule": (), "espn": (), "live": ("live",)}
OWNED_META = {"schedule": ("complete_through", "sources", "fetched", "coverage"), "espn": ("espn_odds", "espn_scan"),
              "live": ("live_at",)}
OWNED_TOP = {"schedule": ("teams",)}
_LIVE_STATUS = ("live", "status", "hs", "as")


def save_owned(store: dict[str, Any], phases: Iterable[str]) -> Path:
    """Lock, re-read the store from disk, merge in what `phases` own from the in-memory store, write, and
    refresh the in-memory store with the merged result."""
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
                new = dict(g)
                new["lines"] = _merge_lines(d.get("lines"), g.get("lines"), LINES_SCHEDULE)
                if d.get("live") and "live" not in phases:
                    new["live"] = d["live"]
                    if new.get("status") == "scheduled" and d.get("status") in ("live", "final"):
                        for k in ("status", "hs", "as"):
                            new[k] = d.get(k)
                disk["games"][gid] = d = new
            if "espn" in phases:
                d["lines"] = _merge_lines(d.get("lines"), g.get("lines"), LINES_ESPN)
            if "live" in phases and g.get("live"):
                for k in _LIVE_STATUS:
                    if k in g and (k == "live" or g.get("status") in ("live", "final")):
                        d[k] = g[k]
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


def _merge_lines(disk: dict | None, mem: dict | None, keys: tuple) -> dict | None:
    out = dict(disk or {})
    for k in keys:
        if mem and k in mem and (mem[k] is not None or k not in out):
            out[k] = mem[k]
    return out or None


_KEEP_IF_EMPTY = ("lines", "espn_id", "referee", "temp", "wind", "home_qb", "away_qb", "live")


def merge_game(store: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a GAME, keeping richer fields the new record lacks (a schedule rescan never wipes
    ESPN lines or a live state; nflverse's line keys update in place)."""
    gid = str(game["game_id"])
    old = store["games"].get(gid)
    if not old:
        store["games"][gid] = game
        return game
    new = dict(old)
    for k, v in game.items():
        if k in _KEEP_IF_EMPTY and v in (None, {}, []) and old.get(k) not in (None, {}, []):
            continue
        if k == "lines":
            v = _merge_lines(old.get("lines"), v, LINES_SCHEDULE)
        new[k] = v
    if game.get("status") == "scheduled" and old.get("status") in ("live", "final") and old.get("live"):
        for k in ("status", "hs", "as"):
            new[k] = old.get(k)
    store["games"][gid] = new
    return new


def mark(store: dict[str, Any], key: str, what: str = "fetched") -> None:
    store["meta"].setdefault(what, {})[str(key)] = now()


def complete_through(store: dict[str, Any]) -> int | None:
    """The last week through which every game is final."""
    last = None
    weeks: dict[int, list[str]] = {}
    for g in store["games"].values():
        weeks.setdefault(int(g.get("week") or 0), []).append(g.get("status"))
    for w in sorted(weeks):
        if all(s == "final" for s in weeks[w]):
            last = w
        else:
            break
    return last


def seasons_on_disk() -> list[int]:
    d = data_root()
    if not d.exists():
        return []
    return sorted(int(x.name) for x in d.iterdir() if x.is_dir() and x.name.isdigit() and (x / "store.json").exists())
