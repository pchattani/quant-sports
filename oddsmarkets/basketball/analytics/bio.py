"""
Player biographies for The Quant Hardwood: dates of birth and draft slots from ESPN (scripts/bb_bio.py writes
data/<league>/bio.json; the build only reads it).

Only the current season's store records dates of birth (today's rosters), so before this file every earlier
season's catalogue, the roster prior's ageing step and the value layer had no age for a player who has left the
league. `fill_dob` fills a missing date from the file; `age_at` is the age in years on a day; `season_age` the age
on 1 February of the NBA season's end year (mid-season; WNBA: 1 July), the convention of the ageing curves.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from oddsmarkets.basketball import analytics as an


def bio_path(league: str) -> Path:
    return an.data_root() / str(league).lower() / "bio.json"


@lru_cache(maxsize=8)
def _load(path: str, mtime: float) -> dict:
    d = an.read_json(Path(path))
    return d if isinstance(d, dict) else {}


def load(league: str) -> dict:
    """The whole bio file ({} when missing), memoised on its modification time."""
    p = bio_path(league)
    try:
        m = p.stat().st_mtime
    except OSError:
        return {}
    return _load(str(p), m)


def players(league: str) -> dict[str, dict]:
    return {k: v for k, v in load(league).items() if not str(k).startswith("_") and isinstance(v, dict)}


def drafts(league: str) -> dict[int, list[list]]:
    """{year: [[overall, round, pick, team_id, athlete_id, name, traded]]}."""
    out = {}
    for k, v in (load(league).get("_drafts") or {}).items():
        try:
            out[int(k)] = v or []
        except (TypeError, ValueError):
            continue
    return out


def dob(league: str, pid: str) -> str | None:
    return (players(league).get(str(pid)) or {}).get("dob")


def draft_slot(league: str, pid: str) -> list | None:
    """[year, round, pick, team_id] from the athlete record, else from the draft lists."""
    r = (players(league).get(str(pid)) or {}).get("draft")
    if r and r[0]:
        return r
    for y, picks in drafts(league).items():
        for p in picks:
            if str(p[4] or "") == str(pid):
                return [y, p[1], p[0], p[3]]
    return None


def fill_dob(league: str, recs: dict[str, dict]) -> dict[str, dict]:
    """A copy of {pid: record} with a missing "dob" filled from the bio file (records with one are untouched)."""
    bp = players(league)
    if not bp:
        return recs
    out = {}
    for pid, r in (recs or {}).items():
        r = r or {}
        d = (bp.get(str(pid)) or {}).get("dob")
        out[pid] = {**r, "dob": d} if d and not r.get("dob") else r
    return out


def age_at(dob_s: Any, day: Any) -> float | None:
    try:
        d = date.fromisoformat(str(dob_s)[:10])
        a = date.fromisoformat(str(day)[:10])
    except (TypeError, ValueError):
        return None
    return (a - d).days / 365.25


def season_day(league: str, season: int) -> str:
    """Mid-season reference day: 1 February of the end year (NBA), 1 July (WNBA)."""
    return f"{int(season)}-07-01" if str(league).lower() == "wnba" else f"{int(season)}-02-01"


def season_age(league: str, season: int, dob_s: Any) -> float | None:
    return age_at(dob_s, season_day(league, season))
