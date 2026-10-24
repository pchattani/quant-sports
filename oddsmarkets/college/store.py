"""
Season stores for The Quant Campus (CONTRACT.md sections 0 and 1.2): one gzipped JSON per level and season,
the single source of truth every model reads.

    data/college/stores/<L>/<S>.json.gz            STORE (teams, conferences, players, rosters, games, rankings, meta)
    data/college/cfb/plays/<S>.json.gz             football plays of a season (compact rows, `PLAY_COLS`)
    data/college/pbp/<L>/<S>/<gid>.json.gz         basketball play-by-play of one game (Hardwood's compact rows)

Roots: CAMPUS_STORES (default data/college/stores), CAMPUS_RAW (default data/college: cfb plays, pbp),
CAMPUS_CACHE (data/college/cache), CAMPUS_DATA (docs/campus/data); `paths()` returns them.

Every write is atomic (temp file + os.replace), gzip text with compact separators, so a reader never sees a
half-written store while the backfill runs.
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

# Basketball BOX player row (CONTRACT.md 1.2; no plus-minus in college box scores)
BOX_COLS = ["player_id", "starter", "sec", "pts", "fgm", "fga", "tpm", "tpa", "ftm", "fta",
            "oreb", "dreb", "ast", "stl", "blk", "tov", "pf"]
TEAM_BOX_KEYS = ["fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "team_tov", "pf",
                 "pts_paint", "pts_fastbreak", "pts_off_tov", "largest_lead"]
# Football team box keys
FB_TEAM_KEYS = ["first_downs", "total_yards", "pass_yards", "rush_yards", "rush_att", "pass_att", "pass_cmp", "turnovers",
                "fumbles_lost", "ints_thrown", "penalties", "penalty_yards", "third_conv", "third_att", "fourth_conv",
                "fourth_att", "possession_s"]
# CFB play row and drive row (data/college/cfb/plays/<S>.json.gz)
PLAY_COLS = ["seq", "drive", "period", "clock_s", "offense", "defense", "type_id", "down", "distance", "yte", "yards",
             "end_down", "end_distance", "end_yte", "scoring", "home_score", "away_score", "turnover", "penalty",
             "wp_home", "text"]
DRIVE_COLS = ["idx", "team", "period", "clock_s", "start_yte", "n_plays", "yards", "result", "is_score"]
# Basketball pbp row (Hardwood's compact_pbp)
PBP_COLS = ["seq", "period", "clock_s", "type_id", "team_id", "participants", "x", "y", "score_value", "shooting",
            "scoring", "home_score", "away_score", "text", "points_attempted"]


def paths() -> dict[str, Path]:
    """{"stores", "raw", "cache", "data"} roots, overridable by CAMPUS_STORES / CAMPUS_RAW / CAMPUS_CACHE / CAMPUS_DATA."""
    return {"stores": Path(os.environ.get("CAMPUS_STORES") or (ROOT / "data" / "college" / "stores")),
            "raw": Path(os.environ.get("CAMPUS_RAW") or (ROOT / "data" / "college")),
            "cache": Path(os.environ.get("CAMPUS_CACHE") or (ROOT / "data" / "college" / "cache")),
            "data": Path(os.environ.get("CAMPUS_DATA") or (ROOT / "docs" / "campus" / "data"))}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_path(level: str, season: int) -> Path:
    return paths()["stores"] / str(level) / f"{int(season)}.json.gz"


def plays_path(season: int) -> Path:
    return paths()["raw"] / "cfb" / "plays" / f"{int(season)}.json.gz"


def pbp_path(level: str, season: int, gid: str) -> Path:
    return paths()["raw"] / "pbp" / str(level) / str(int(season)) / f"{gid}.json.gz"


# ── gz json io ──────────────────────────────────────────────────────────────

def write_gz(p: Path, obj: Any, level: int = 6) -> Path:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=level) as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    for i in range(5):
        try:
            os.replace(tmp, p)
            break
        except PermissionError:           # Windows: a reader holds the file open for a moment
            import time
            time.sleep(0.5 * (i + 1))
    else:
        os.replace(tmp, p)
    return p


def read_gz(p: Path) -> Any:
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError, EOFError):
        return None


# ── season store ────────────────────────────────────────────────────────────

def new_store(level: str, season: int) -> dict[str, Any]:
    return {"level": str(level), "season": int(season), "updated_at": None, "conferences": {}, "teams": {},
            "players": {}, "rosters": {}, "games": {}, "rankings": {},
            "meta": {"fetched": {}, "odds": {}, "calendar": [], "complete_through": None,
                     "odds_coverage": {"games": 0, "with_close": 0, "with_any": 0}, "version": VERSION}}


def load(level: str, season: int) -> dict[str, Any]:
    """The store of a level and season (an empty one when absent or unreadable)."""
    s = read_gz(store_path(level, season))
    base = new_store(level, season)
    if not isinstance(s, dict):
        return base
    for k, v in base.items():
        s.setdefault(k, v)
    for k, v in base["meta"].items():
        s["meta"].setdefault(k, v)
    return s


def save(store: dict[str, Any]) -> Path:
    store["updated_at"] = now()
    store["games"] = dict(sorted(store["games"].items(), key=lambda kv: (kv[1].get("date") or "", kv[0])))
    store["meta"]["odds_coverage"] = odds_coverage(store)
    store["meta"]["version"] = VERSION
    return write_gz(store_path(store["level"], store["season"]), store)


def seasons_on_disk(level: str) -> list[int]:
    d = paths()["stores"] / str(level)
    if not d.exists():
        return []
    return sorted(int(p.name.split(".")[0]) for p in d.glob("*.json.gz") if p.name.split(".")[0].isdigit())


def odds_coverage(store: dict) -> dict[str, int]:
    gs = [g for g in store.get("games", {}).values() if g.get("status") == "post"]
    with_any = [g for g in gs if g.get("odds")]
    with_close = [g for g in with_any if (g["odds"] or {}).get("spread_home") is not None]
    return {"games": len(gs), "with_close": len(with_close), "with_any": len(with_any)}


def coverage(level: str, season: int, store: dict | None = None) -> dict[str, Any]:
    """What a season's inputs hold (the As-built table): games, finished games, summaries, play-by-play
    (football: games in the plays file; basketball: pbp files), odds with a close, poll weeks, seeded games."""
    s = store if store is not None else load(level, season)
    gs = s.get("games") or {}
    fin = [g for g in gs.values() if g.get("status") == "post"]
    if level == "cfb":
        pl = read_gz(plays_path(season)) if plays_path(season).exists() else None
        n_pbp = len((pl or {}).get("games") or {})
    else:
        d = paths()["raw"] / "pbp" / level / str(int(season))
        n_pbp = sum(1 for _ in d.glob("*.json.gz")) if d.exists() else 0
    cov = odds_coverage(s)
    rk = s.get("rankings") or {}
    return {"level": level, "season": int(season), "games": len(gs), "final": len(fin),
            "summaries": sum(1 for g in fin if g.get("summary")), "pbp": n_pbp,
            "odds_any": cov["with_any"], "odds_close": cov["with_close"],
            "odds_core": sum(1 for g in fin if (g.get("odds") or {}).get("source") == "core"),
            "odds_none_sampled": bool((s.get("meta") or {}).get("odds_none")),
            "rank_weeks": {k: len(v) for k, v in rk.items()},
            "seeded_games": sum(1 for g in gs.values() if any((g.get("seeds") or {}).values())),
            "teams": len(s.get("teams") or {}), "members": sum(1 for t in (s.get("teams") or {}).values() if t.get("member")),
            "conferences": len(s.get("conferences") or {}), "players": len(s.get("players") or {}),
            "rosters": len(s.get("rosters") or {}), "updated_at": s.get("updated_at")}


# ── merge helpers ───────────────────────────────────────────────────────────

_KEEP_IF_NEW_EMPTY = ("box", "line", "team_stats", "injuries")
_KEEP_IF_NEW_NONE = ("odds", "venue", "attendance", "predictor", "seeds", "round", "region", "note", "week")


def merge_game(store: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Insert or update a GAME, keeping richer fields the new record lacks (a scoreboard rescan never wipes a
    fetched box score, a pregame predictor or odds; `summary`/`has_pbp` never go back to False)."""
    gid = str(game["id"])
    old = store["games"].get(gid)
    if not old:
        store["games"][gid] = game
        return game
    new = dict(old)
    for k, v in game.items():
        if k in _KEEP_IF_NEW_EMPTY and not v and old.get(k):
            continue
        if k in _KEEP_IF_NEW_NONE and v is None and old.get(k) is not None:
            continue
        if k in ("has_pbp", "summary") and not v and old.get(k):
            continue
        if k == "ranks" and old.get(k) and not any((v or {}).values()):
            continue
        if k == "odds" and v is not None and old.get(k) and _odds_rank(v) < _odds_rank(old[k]):
            continue                      # never replace a closing line with a weaker source
        new[k] = v
    store["games"][gid] = new
    return new


def _odds_rank(o: dict) -> int:
    src = (o or {}).get("source")
    has_close = (o or {}).get("spread_home") is not None
    return {"core": 3, "pickcenter": 2, "scoreboard": 1}.get(src, 0) * 2 + (1 if has_close else 0)


def merge_team(store: dict[str, Any], tid: str, rec: dict[str, Any], weak: tuple = ()) -> dict[str, Any]:
    """Fill a team record without wiping known fields with None. Keys in `weak` (e.g. a scoreboard's
    conferenceId, which is today's conference, not necessarily the season's) only fill gaps."""
    old = store["teams"].setdefault(str(tid), {"name": None, "short": None, "abbr": None, "location": None,
                                               "nickname": None, "colour": None, "alt_colour": None,
                                               "conference": None, "member": False, "venue": None})
    for k, v in rec.items():
        if v is None or v == "":
            continue
        if k in weak and old.get(k) not in (None, False, ""):
            continue
        old[k] = v
    return old


# plausible bounds for ESPN's roster height (inches) and weight (pounds); ESPN carries typos such as 5 lb or
# 2 lb for real players, which are dropped rather than shown
BODY_BOUNDS = {"height_in": (55, 100), "weight_lb": (90, 450)}


def _body_ok(k: str, v: Any) -> bool:
    lo_hi = BODY_BOUNDS.get(k)
    return lo_hi is None or not isinstance(v, (int, float)) or lo_hi[0] <= v <= lo_hi[1]


def jersey_number(v: Any) -> str | None:
    """The jersey number for a player hero, as ESPN's roster `jersey` gives it ("7", "00"); None unless 1-2 digits."""
    s = str(v).strip() if v is not None else ""
    return s if s.isdigit() and len(s) <= 2 else None


def merge_player(store: dict[str, Any], pid: str, rec: dict[str, Any], tid: str | None = None) -> dict[str, Any]:
    old = store["players"].setdefault(str(pid), {"name": None, "short": None, "pos": None, "jersey": None, "class": None,
                                                 "height_in": None, "weight_lb": None, "hometown": None, "teams": []})
    for k, v in rec.items():
        if k in ("id", "teams") or v is None or v == "" or not _body_ok(k, v):
            continue
        old[k] = v
    for k in BODY_BOUNDS:                 # clear a typo stored before the bounds existed
        if not _body_ok(k, old.get(k)):
            old[k] = None
    for t in ([tid] if tid else []) + list(rec.get("teams") or []):
        if t and str(t) not in old["teams"]:
            old["teams"].append(str(t))
    return old


def mark(store: dict[str, Any], gid: str) -> None:
    store["meta"]["fetched"][str(gid)] = now()


def fetched(store: dict[str, Any], gid: str) -> bool:
    return str(gid) in store["meta"]["fetched"]


def mark_odds(store: dict[str, Any], gid: str) -> None:
    store["meta"]["odds"][str(gid)] = now()


def odds_fetched(store: dict[str, Any], gid: str) -> bool:
    return str(gid) in store["meta"]["odds"]


# ── cfb plays and basketball pbp ────────────────────────────────────────────

def new_plays(season: int) -> dict[str, Any]:
    return {"season": int(season), "cols": list(PLAY_COLS), "drive_cols": list(DRIVE_COLS), "types": {}, "games": {}}


def load_plays(season: int) -> dict[str, Any]:
    d = read_gz(plays_path(season))
    if not isinstance(d, dict):
        return new_plays(season)
    d.setdefault("types", {})
    d.setdefault("games", {})
    return d


def save_plays(plays: dict[str, Any]) -> Path:
    return write_gz(plays_path(plays["season"]), plays)


def save_pbp(level: str, season: int, pbp: dict) -> Path:
    return write_gz(pbp_path(level, season, pbp["id"]), pbp)


def load_pbp(level: str, season: int, gid: str) -> dict | None:
    p = pbp_path(level, season, gid)
    return read_gz(p) if p.exists() else None


def has_pbp_file(level: str, season: int, gid: str) -> bool:
    return pbp_path(level, season, gid).exists()
