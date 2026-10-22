"""
Season stores for The Quant Hardwood: one JSON per league and season, the single
source of truth the build reads (mirroring the F1 and football stores).

    docs/hardwood/data/<league>/<season>/store.json
    {"league", "season", "updated_at",
     "teams":   {team_id: {name, abbr, location, colour, alt_colour, conference, division}},
     "players": {player_id: {name, short, pos, pool, jersey, dob, teams: [team_id...]}},
     "games":   {game_id: GAME},           # see sources/espn.compact_game and CONTRACT.md
     "meta":    {"fetched": {game_id: iso}, "complete_through": "YYYY-MM-DD", "calendar": [...]}}

Raw play-by-play (git-ignored) lives beside the repo's data root:

    data/basketball/pbp/<league>/<season>/<game_id>.json.gz      (sources/espn.compact_pbp)

The data root can be redirected with HARDWOOD_DATA and the play-by-play root with HARDWOOD_PBP.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# Fixed column order of a GAME box-score player row (CONTRACT.md section 1).
BOX_COLS = ["player_id", "starter", "sec", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta",
            "oreb", "dreb", "ast", "stl", "blk", "tov", "pf", "pm"]
TEAM_BOX_KEYS = ["fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "team_tov", "pf",
                 "pts_paint", "pts_fastbreak", "pts_off_tov", "largest_lead", "lead_changes"]


def data_root() -> Path:
    return Path(os.environ.get("HARDWOOD_DATA") or (ROOT / "docs" / "hardwood" / "data"))


def pbp_root() -> Path:
    return Path(os.environ.get("HARDWOOD_PBP") or (ROOT / "data" / "basketball" / "pbp"))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def season_dir(league: str, season: int) -> Path:
    return data_root() / str(league) / str(int(season))


def season_path(league: str, season: int) -> Path:
    return season_dir(league, season) / "store.json"


def pbp_path(league: str, season: int, game_id: str) -> Path:
    return pbp_root() / str(league) / str(int(season)) / f"{game_id}.json.gz"


def new_store(league: str, season: int) -> dict[str, Any]:
    return {"league": str(league), "season": int(season), "updated_at": None, "teams": {}, "players": {}, "games": {},
            "meta": {"fetched": {}, "complete_through": None}}


def load(league: str, season: int) -> dict[str, Any]:
    p = season_path(league, season)
    if p.exists():
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
            for k, v in new_store(league, season).items():
                s.setdefault(k, v)
            s["meta"].setdefault("fetched", {})
            s["meta"].setdefault("complete_through", None)
            return s
        except (OSError, ValueError):
            pass
    return new_store(league, season)


def _write_json(p: Path, obj: Any) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)
    return p


def save(store: dict[str, Any]) -> Path:
    store["updated_at"] = now()
    # Games in date order make diffs and reads stable.
    store["games"] = dict(sorted(store["games"].items(), key=lambda kv: (kv[1].get("date") or "", kv[0])))
    return _write_json(season_path(store["league"], store["season"]), store)


def save_table(league: str, season: int, name: str, obj: Any) -> Path:
    return _write_json(season_dir(league, season) / name, obj)


def save_table_gz(league: str, season: int, name: str, obj: Any) -> Path:
    """`<name>.gz` beside the plain table (completed seasons commit only the gzipped shots/stints)."""
    p = season_dir(league, season) / f"{name}.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(p)
    return p


def table_path(league: str, season: int, name: str) -> Path:
    """The file holding table `name`: `<name>.gz` when present and not older than the plain file, else `name`."""
    p = season_dir(league, season) / name
    gz = p.with_name(p.name + ".gz")
    try:
        g = gz.stat().st_mtime_ns
    except OSError:
        return p
    try:
        return gz if g >= p.stat().st_mtime_ns else p
    except OSError:
        return gz


def load_table(league: str, season: int, name: str) -> Any:
    """A season table (shots.json, stints.json, recon.json, ...), read from `<name>.gz` when that is
    present and not older than the plain file."""
    p = table_path(league, season, name)
    try:
        if p.name.endswith(".gz"):
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, EOFError):
        return None


def save_pbp(league: str, season: int, pbp: dict) -> Path:
    p = pbp_path(league, season, pbp["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(pbp, fh, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(p)
    return p


def load_pbp(league: str, season: int, game_id: str) -> dict | None:
    p = pbp_path(league, season, game_id)
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, EOFError):
        return None


def seasons_on_disk(league: str) -> list[int]:
    d = data_root() / str(league)
    if not d.exists():
        return []
    return sorted(int(x.name) for x in d.iterdir() if x.is_dir() and x.name.isdigit() and (x / "store.json").exists())


INJURY_LOG = "injury_log.json"


def load_injury_log(league: str, season: int) -> dict[str, list]:
    """{game_id: [[fetched_at, {team_id: [[player_id, status, espn_date]]}], ...]}: timestamped snapshots of ESPN's
    injury list for upcoming games (`append_injury_log`); {} when none."""
    return load_table(league, season, INJURY_LOG) or {}


def append_injury_log(log: dict[str, list], game_id: str, at: str, rows: dict[str, list]) -> bool:
    """Append one snapshot for a game not yet started, only when it differs from the game's last one (so the log
    holds every change, each stamped with the first fetch that saw it). Returns whether it was appended."""
    snaps = log.setdefault(str(game_id), [])
    norm = {str(t): sorted([str(r[0]), r[1], r[2]] for r in v) for t, v in sorted(rows.items())}
    if snaps and snaps[-1][1] == norm:
        return False
    snaps.append([at, norm])
    return True


def save_injury_log(league: str, season: int, log: dict[str, list]) -> Path:
    return save_table_gz(league, season, INJURY_LOG, log)


def merge_game(store: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a GAME, keeping richer fields the new record lacks (a scoreboard
    skeleton never wipes a fetched box score; injuries survive the post-game refetch)."""
    gid = str(game["id"])
    old = store["games"].get(gid)
    if not old:
        store["games"][gid] = game
        return game
    new = dict(old)
    for k, v in game.items():
        if k in ("box", "injuries", "line") and not v and old.get(k):
            continue
        if k in ("odds", "venue", "series", "attendance", "predictor") and v is None and old.get(k) is not None:
            continue
        if k == "has_pbp" and not v and old.get(k):
            continue
        if k == "stype" and v == "reg" and old.get(k) in ("cup", "playin", "post"):
            continue                      # a scoreboard rescan without notes keeps the summary's label
        new[k] = v
    store["games"][gid] = new
    return new


def mark(store: dict[str, Any], game_id: str) -> None:
    store["meta"]["fetched"][str(game_id)] = now()


def fetched(store: dict[str, Any], game_id: str) -> bool:
    return str(game_id) in store["meta"]["fetched"]
