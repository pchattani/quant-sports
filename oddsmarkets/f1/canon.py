"""
Identity for the F1 models: car numbers -> Jolpica driverIds, drivers -> constructorIds,
and OpenF1 session records -> rounds of the season store.

Everything downstream keys drivers by Jolpica `driverId` and teams by `constructorId`
(see CONTRACT.md). Numbers are resolved per season from the store's `results` and
`qualifying` rows, and, where a round is known, per round first:

* a number can change hands across seasons (e.g. #1 is the champion's; retired numbers
  are reissued), so maps are never shared between seasons;
* within a season a substitute races under his own number, and the store's per-round
  rows say who drove; if two drivers ever share a number in one season (a reissued
  number, or a data error), the round-level map disambiguates and the season map
  keeps the driver who used it most.

OpenF1 session records carry the car number and a three-letter acronym; they are
mapped to a round by date (the race whose date is 0-4 days after the session) and to
drivers by number, falling back to the acronym/surname when the number is unknown.

Nothing here raises on missing data: lookups return None or empty dicts.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from oddsmarkets.f1 import store as _store_mod
from oddsmarkets.f1.sources import openf1 as _openf1

_STORES: dict[int, tuple[float, dict]] = {}
_SESS_INDEX: dict[int, tuple[tuple, list[dict]]] = {}
_SESS_RECS: dict[str, tuple[float, dict]] = {}
_HEADERS: dict[str, tuple[float, dict]] = {}


# ---------------------------------------------------------------- store access

def season(year: int) -> dict[str, Any]:
    """The season store, cached by file mtime (the backfill rewrites it atomically)."""
    p = _store_mod.season_path(int(year))
    try:
        mt = p.stat().st_mtime
    except OSError:
        mt = -1.0
    hit = _STORES.get(int(year))
    if hit and hit[0] == mt:
        return hit[1]
    s = _store_mod.load(int(year))
    _STORES[int(year)] = (mt, s)
    return s


def race(year: int, rnd: int) -> dict[str, Any]:
    return (season(year).get("races") or {}).get(str(rnd)) or {}


def rounds(year: int) -> list[int]:
    return sorted(int(k) for k in (season(year).get("races") or {}))


def completed_rounds(year: int) -> list[int]:
    """Rounds with race results on disk."""
    return [r for r in rounds(year) if race(year, r).get("results")]


def _rows(r: dict) -> list[dict]:
    return list(r.get("results") or []) + list(r.get("qualifying") or []) + list(r.get("sprint") or [])


# ---------------------------------------------------------------- numbers

def number_map(year: int, rnd: int | None = None) -> dict[int, str]:
    """{car number: driverId} for a season (or a single round when `rnd` is given).

    Season-level: each number goes to the driver who carried it in most rows; this
    resolves the rare same-season reuse in favour of the regular driver, while the
    round-level map (used whenever the round is known) is always exact.
    """
    races = season(year).get("races") or {}
    keys = [str(rnd)] if rnd is not None else list(races)
    votes: dict[int, Counter] = {}
    for k in keys:
        for row in _rows(races.get(k) or {}):
            n, d = row.get("number"), row.get("driver")
            if n is None or not d:
                continue
            try:
                votes.setdefault(int(n), Counter())[d] += 1
            except (TypeError, ValueError):
                continue
    out = {n: c.most_common(1)[0][0] for n, c in votes.items()}
    if rnd is None:
        # drivers{} carries a permanent number; use it only for numbers no row claims.
        for d, info in (season(year).get("drivers") or {}).items():
            n = (info or {}).get("number")
            try:
                if n is not None and int(n) not in out:
                    out[int(n)] = d
            except (TypeError, ValueError):
                pass
    return out


def number_collisions(year: int) -> dict[int, list[str]]:
    """Numbers carried by more than one driver within the season (data check)."""
    seen: dict[int, set] = {}
    for r in (season(year).get("races") or {}).values():
        for row in _rows(r):
            try:
                seen.setdefault(int(row["number"]), set()).add(row["driver"])
            except (KeyError, TypeError, ValueError):
                continue
    return {n: sorted(ds) for n, ds in seen.items() if len(ds) > 1}


def driver_for_number(year: int, number: Any, rnd: int | None = None) -> str | None:
    """driverId for a car number in a season; exact per round when `rnd` is given."""
    try:
        n = int(number)
    except (TypeError, ValueError):
        return None
    if rnd is not None:
        d = number_map(year, rnd).get(n)
        if d:
            return d
    return number_map(year).get(n)


def team_for(year: int, rnd: int, driver_id: str) -> str | None:
    """constructorId the driver drove for in that round; nearest round otherwise
    (previous rounds first, then later ones), None if he never appears that season."""
    def look(r: dict) -> str | None:
        for row in _rows(r):
            if row.get("driver") == driver_id and row.get("constructor"):
                return row["constructor"]
        return None

    t = look(race(year, rnd))
    if t:
        return t
    rs = rounds(year)
    for r in sorted((x for x in rs if x < int(rnd)), reverse=True) + sorted(x for x in rs if x > int(rnd)):
        t = look(race(year, r))
        if t:
            return t
    return None


def lineup(year: int, rnd: int) -> dict[str, str]:
    """{driverId: constructorId} for a round: its qualifying/results entries if present,
    otherwise the most recent earlier round's lineup."""
    r = race(year, rnd)
    out = {row["driver"]: row["constructor"] for row in _rows(r) if row.get("driver") and row.get("constructor")}
    if out:
        return out
    for prev in sorted((x for x in rounds(year) if x < int(rnd)), reverse=True):
        r = race(year, prev)
        out = {row["driver"]: row["constructor"] for row in _rows(r) if row.get("driver") and row.get("constructor")}
        if out:
            return out
    return {}


# ---------------------------------------------------------------- OpenF1 sessions

def _date(s: Any) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(s)[:10])
        except ValueError:
            return None


def load_session(path: Path | str) -> dict | None:
    """An OpenF1 session record from disk (cached by mtime); None if unreadable."""
    p = Path(path)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    hit = _SESS_RECS.get(str(p))
    if hit and hit[0] == mt:
        return hit[1]
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if len(_SESS_RECS) > 64:
        _SESS_RECS.clear()
    _SESS_RECS[str(p)] = (mt, rec)
    return rec


def round_for_date(year: int, d: date | None) -> int | None:
    """The round whose race date is 0-4 days on or after `d`."""
    if d is None:
        return None
    best = None
    for rk, r in (season(year).get("races") or {}).items():
        rd = _date(r.get("date"))
        if rd is None:
            continue
        gap = (rd - d).days
        if 0 <= gap <= 4 and (best is None or gap < best[0]):
            best = (gap, int(rk))
    return best[1] if best else None


def session_index(year: int) -> list[dict]:
    """[{key, path, name, type, date, round}] for the OpenF1 sessions on disk for a season."""
    folder = _openf1.SITE_DATA / str(year) / "sessions"
    try:
        files = sorted(folder.glob("*.json"))
        sig = tuple((f.name, f.stat().st_mtime) for f in files)
    except OSError:
        return []
    sp = _store_mod.season_path(int(year))
    sig = sig + ((sp.stat().st_mtime if sp.exists() else 0),)
    hit = _SESS_INDEX.get(int(year))
    if hit and hit[0] == sig:
        return hit[1]
    out = []
    for f, mt in zip(files, (x[1] for x in sig)):
        h = _HEADERS.get(str(f))
        if not h or h[0] != mt:
            rec = load_session(f)
            if not rec:
                continue
            h = (mt, rec.get("session") or {})
            _HEADERS[str(f)] = h
        s = h[1]
        d = _date(s.get("date_start"))
        out.append({"key": s.get("session_key"), "path": str(f), "name": s.get("session_name"), "type": s.get("session_type"),
                    "date": d.isoformat() if d else None, "meeting": s.get("meeting_key"), "round": round_for_date(year, d)})
    _SESS_INDEX[int(year)] = (sig, out)
    return out


def find_session(year: int, rnd: int, name: str = "Race") -> dict | None:
    """The OpenF1 record of a round's session by name ("Race", "Qualifying", "Sprint", ...)."""
    for e in session_index(year):
        if e["round"] == int(rnd) and str(e["name"]).lower() == name.lower():
            return load_session(e["path"])
    return None


def session_round(year: int, rec: dict) -> int | None:
    return round_for_date(year, _date((rec.get("session") or {}).get("date_start")))


def session_driver_ids(year: int, rec: dict, rnd: int | None = None) -> dict[str, str]:
    """{str(car number): driverId} for an OpenF1 session record.

    By number within the round (then the season); a number the store does not know is
    matched on the three-letter acronym, then the surname, against the season's drivers.
    """
    if rnd is None:
        rnd = session_round(year, rec)
    drivers = season(year).get("drivers") or {}
    by_code = {str((v or {}).get("code") or "").upper(): k for k, v in drivers.items() if (v or {}).get("code")}
    by_family = {str((v or {}).get("family") or "").lower(): k for k, v in drivers.items() if (v or {}).get("family")}
    numbers = set((rec.get("drivers") or {}).keys()) | set((rec.get("laps") or {}).keys())
    out: dict[str, str] = {}
    for n in numbers:
        d = driver_for_number(year, n, rnd)
        info = (rec.get("drivers") or {}).get(str(n)) or {}
        if d is None:
            d = by_code.get(str(info.get("name_acronym") or "").upper()) or by_family.get(str(info.get("last_name") or "").lower())
        if d:
            out[str(n)] = d
    return out


def rekey(year: int, rec: dict, data: dict, rnd: int | None = None) -> dict[str, Any]:
    """Convert one of a session record's per-number dicts (laps, lap_end, positions,
    drivers) to driverId keys; numbers that cannot be resolved are dropped."""
    ids = session_driver_ids(year, rec, rnd)
    return {ids[str(n)]: v for n, v in (data or {}).items() if str(n) in ids}
