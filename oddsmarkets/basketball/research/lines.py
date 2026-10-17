"""
Betting lines per game from the cache written by scripts/bb_odds_history.py (ESPN core odds, every book).

`game_lines(league, season)` -> {event_id: {"open": BLOCK|None, "close": BLOCK|None, "src": str|None,
                                           "books": {name: BLOCK}}}
BLOCK = {"ml_h","ml_a","sp_h","spo_h","spo_a","tot","over","under"} (American odds; sp_h the home spread line,
negative = home favoured; tot the total line).

Open / close: the first book among PRIMARY that carries both an `open` and a `close` block (ESPN BET 2023-25,
DraftKings 2026). Seasons without open blocks (NBA <= 2023, WNBA <= 2023) get `close` from a single book's
snapshot (DraftKings, else consensus, else Caesars): ESPN shows a finished game's last pre-game numbers, so it
is treated as the close, never as a price available at an earlier decision time.

De-vig (`devig2`): multiplicative (normalised implied probabilities); `fair` returns both sides.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from oddsmarkets.basketball.models import _io
from oddsmarkets.common.edge import devig as _dv

PRIMARY = ("100", "58")                     # DraftKings (2026 on), ESPN BET (2023-25)
SNAPSHOT = ("40", "100", "1004", "58", "31", "38", "45", "47", "1001", "37", "36", "25")   # DK, consensus, Caesars ...


def cache_dir() -> Path:
    return _io.cache_root() / "odds"


def am_to_dec(a: float | None) -> float | None:
    if a is None or not math.isfinite(a) or a == 0 or -100 < a < 100:
        return None
    return 1 + (a / 100.0 if a > 0 else 100.0 / -a)


def devig2(a: float | None, b: float | None) -> tuple[float, float] | None:
    """Multiplicative de-vig of a two-way market given American odds; None when either is missing or absurd."""
    da, db = am_to_dec(a), am_to_dec(b)
    if da is None or db is None:
        return None
    ia, ib = 1 / da, 1 / db
    s = ia + ib
    if not (0.98 <= s <= 1.15):
        return None
    return _dv.multiplicative_pair(da, db)          # common/edge/devig.py


def _ok_block(b: dict | None, league: str) -> dict | None:
    if not b:
        return None
    out = dict(b)
    lo, hi = (180.0, 280.0) if league == "nba" else (130.0, 200.0)
    if out.get("tot") is not None and not (lo <= out["tot"] <= hi):
        out["tot"] = out["over"] = out["under"] = None
    if out.get("sp_h") is not None and abs(out["sp_h"]) > 30:
        out["sp_h"] = out["spo_h"] = out["spo_a"] = None
    if devig2(out.get("ml_h"), out.get("ml_a")) is None:
        out["ml_h"] = out["ml_a"] = None
    for k in ("spo_h", "spo_a", "over", "under"):
        v = out.get(k)
        if v is not None and not ((v <= -100 or v >= 100) and abs(v) <= 400):
            out[k] = None
    return out if any(out.get(k) is not None for k in ("ml_h", "sp_h", "tot")) else None


def _snap(b: dict) -> dict:
    return {"ml_h": b.get("ml_h"), "ml_a": b.get("ml_a"), "sp_h": b.get("spread"), "spo_h": b.get("spo_h"),
            "spo_a": b.get("spo_a"), "tot": b.get("total"), "over": b.get("over"), "under": b.get("under")}


def parse_game(books: list[dict] | None, league: str) -> dict:
    out: dict[str, Any] = {"open": None, "close": None, "src": None, "books": {}}
    if not books:
        return out
    books = [b for b in books if not b.get("live")]
    by_id = {b["id"]: b for b in books}
    for b in books:
        snap = _ok_block(_snap(b), league)
        if snap:
            out["books"][b.get("name") or b["id"]] = snap
    for pid in PRIMARY:
        b = by_id.get(pid)
        if b and b.get("open") and b.get("close"):
            o, c = _ok_block(b["open"], league), _ok_block(b["close"], league)
            if o and c:
                out.update({"open": o, "close": c, "src": {"100": "espn_dk", "58": "espn_espnbet"}[pid]})
                return out
    for pid in SNAPSHOT:
        b = by_id.get(pid)
        if b:
            blk = _ok_block(b.get("close") or _snap(b), league)
            if blk:
                out.update({"close": blk, "src": f"espn_snap_{pid}"})
                return out
    return out


def game_lines(league: str, season: int) -> dict[str, dict]:
    p = cache_dir() / f"{league}_{season}.json"
    try:
        raw = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {gid: parse_game(books, league) for gid, books in raw.items()}
