"""
Driver Elo ratings: field Elo, teammate Elo and qualifying Elo, 1950 onwards.

Three ratings, all on the familiar Elo scale (1500 = average, 400 points = 10:1 odds
in a straight fight), all updated once per Grand Prix in calendar order.

What each one measures
    Field Elo        rates the finishing order against the whole field. In Formula 1
                     the car dominates the order, so field Elo is mostly a rating of
                     driver-plus-car: a midfield driver in a dominant car will out-rate
                     a great driver in a slow one. Read it as "how strong was this
                     entry", not "how good is this driver".
    Teammate Elo     updated only on head-to-heads with the driver's own teammate(s),
                     who had the same car. It is the cleaner driver signal, and the
                     one the all-time table is built on. Its weakness is the opposite:
                     it is only as good as the teammates a driver faced, and ratings
                     flow between teams only as drivers change seats.
    Qualifying Elo   field Elo on qualifying positions (one-lap pace, car included).
                     Qualifying classifications exist from 1994; before that the
                     starting grid (results' `grid`, pit-lane starts dropped) stands in.

Expected score and the multi-competitor update
    E_ij = 1 / (1 + 10^((R_j - R_i) / 400))              P(i ahead of j)
    S_ij = 1 if i finished ahead of j, else 0
    dR_i = K / (n - 1) * sum_{j != i} w_ij * (S_ij - E_ij)

    n is the number of drivers taking part in the update (weight > 0), so a race
    moves a driver by at most K whatever the field size. Updates are zero-sum.
    Pair weight w_ij = min(w_i, w_j); a pair of two non-classified drivers is
    skipped (who crashed on lap 3 and who on lap 30 says little about either).

Constants
    K_FIELD = 32, K_TEAMMATE = 24, K_QUALI = 32
    INITIAL = 1500; ROOKIE_OFFSET = 100 (a debutant starts at the mean of the rated
        drivers in their first race minus 100; drivers already racing in the first
        season on disk start at 1500 since their earlier history is not loaded)
    REGRESS = 0.15 between seasons: R <- 1500 + (1 - 0.15) * (R - 1500), applied
        to every rating before a season's first race
    PEAK_MIN_RACES = 20 (a peak counts only from a driver's 20th start)
    ALL_TIME_MIN_RACES = 50 (career starts to enter the all-time table)

Retirements (classified from `status`; weights w_i)
    classified (numeric position_text, i.e. Finished / +n Laps / Lapped or
        classified despite retiring)                              w = 1.0 at their position
    not classified, driver-caused (Accident, Collision, Spun off,
        Collision damage)                                         w = 1.0, behind all classified
    not classified, mechanical (Engine, Gearbox, Hydraulics,
        Power Unit, Brakes, Suspension, Electrical, ... ~60 reasons)  w = 0 (rating untouched)
    not classified, ambiguous ("Retired", "Not classified",
        "Damage", unknown reasons)                                w = 0.5, behind all classified
    did not start / qualify, withdrew, disqualified, excluded,
        injury or illness                                         w = 0 (not in the update)

    Jolpica stopped publishing retirement reasons in recent seasons (2026 statuses
    are just "Retired"), so modern retirements are all ambiguous and cost half a crash.

Teammate head-to-heads
    Within each constructor's entries in a race, a pair counts only when both drivers
    were classified, or one was classified and the other retired for a driver-caused
    reason (the classified one wins). Mechanical and ambiguous retirements, and DNS,
    produce no head-to-head. dR_i = K_TEAMMATE / (m - 1) * sum_j (S_ij - E_ij) over
    the m drivers of that team in an eligible pair.

Other choices
    Sprint races are not rated. The Indianapolis 500 (a championship round 1950-60
    with an almost entirely separate field) is skipped. A driver with two cars in one
    race (1950s shared drives) is rated on their best-placed entry.

`elo_history()` runs on whatever seasons are on disk (the store is backfilled newest
first), never raises on missing data, and caches to data/f1/cache/elo.json keyed on
the stores' modification times.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.f1 import store as st

logger = logging.getLogger(__name__)

K_FIELD = 32.0
K_TEAMMATE = 24.0
K_QUALI = 32.0
INITIAL = 1500.0
ROOKIE_OFFSET = 100.0
REGRESS = 0.15
PEAK_MIN_RACES = 20
ALL_TIME_MIN_RACES = 50
AMBIGUOUS_WEIGHT = 0.5
VERSION = 1

CACHE = st.ROOT / "data" / "f1" / "cache" / "elo.json"

# ── retirement classes ───────────────────────────────────────────────────────

FINISHED, DRIVER, MECHANICAL, AMBIGUOUS, EXCLUDED = "finished", "driver", "mechanical", "ambiguous", "excluded"
WEIGHTS = {FINISHED: 1.0, DRIVER: 1.0, MECHANICAL: 0.0, AMBIGUOUS: AMBIGUOUS_WEIGHT, EXCLUDED: 0.0}

_EXCLUDED = ("did not start", "did not qualify", "did not prequalify", "withdrew", "disqualified", "excluded",
             "107%", "injur", "illness", "unwell", "physical", "fatal", "safety concerns",
             "not restarted", "underweight")
_DRIVER = ("accident", "collision", "spun off", "spun", "crash")
_MECHANICAL = (
    "engine", "gearbox", "transmission", "clutch", "hydraulic", "electrical", "electronic", "electrics", "brake",
    "suspension", "power unit", "turbo", "fuel", "oil", "water", "overheat", "radiator", "exhaust",
    "differential", "driveshaft", "drive shaft", "halfshaft", "half-shaft", "axle", "wheel", "tyre", "puncture",
    "steering", "throttle", "spark", "ignition", "distributor", "battery", "alternator", "magneto", "injection",
    "pneumatic", "vibration", "mechanical", "technical", "launch control", "chassis", "cooling", "fire",
    "heat shield", "rear wing", "wing", "seat", "handling", "out of fuel", "refuelling", "pit stop", "pitstop",
    "stalled", "air box", "trumpet", "crankshaft", "camshaft", "piston", "con rod", "valve", "cv joint", "belt",
    "track rod", "undertray", "front wing", "body", "fuel pressure", "kers", "mgu", "energy store", "power loss",
    "drivetrain", "gear", "supercharger", "compressor", "lubrication", "hub",
)
_FINISHED_RE = re.compile(r"^(finished|lapped|\+\s*\d+\s*laps?)$")


def status_class(status: Any, position_text: Any = None) -> str:
    """One of finished / driver / mechanical / ambiguous / excluded (see module docstring)."""
    s = str(status or "").strip().lower()
    if s and any(k in s for k in _EXCLUDED):
        return EXCLUDED
    if str(position_text or "").strip().isdigit() or _FINISHED_RE.match(s):
        return FINISHED
    if any(k in s for k in _DRIVER):
        return DRIVER
    if any(k in s for k in _MECHANICAL) or re.search(r"\b(ers|kers|mgu-?[hk]?)\b", s):
        return MECHANICAL
    return AMBIGUOUS


# ── core updates ─────────────────────────────────────────────────────────────

def _expected(ri: float, rj: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rj - ri) / 400.0))


def field_update(order: list[tuple[str, float, bool]], ratings: dict[str, float], k: float) -> dict[str, float]:
    """
    Multi-competitor pairwise Elo step. `order` is [(driver, weight, classified)] best
    first. Returns {driver: dR} for drivers with weight > 0.
    """
    part = [(d, w, c) for d, w, c in order if w > 0]
    n = len(part)
    if n < 2:
        return {}
    keff = k / (n - 1)
    delta = {d: 0.0 for d, _, _ in part}
    for a in range(n):
        da, wa, ca = part[a]
        for b in range(a + 1, n):
            db, wb, cb = part[b]
            if not ca and not cb:
                continue
            w = min(wa, wb)
            e = _expected(ratings[da], ratings[db])
            delta[da] += keff * w * (1.0 - e)
            delta[db] -= keff * w * (1.0 - e)
    return delta


def teammate_update(entries: list[tuple[str, str, int, str]], ratings: dict[str, float], k: float) -> dict[str, float]:
    """
    entries: [(driver, constructor, order_index, class)]. Head-to-heads within each
    constructor only; returns {driver: dR} for drivers in at least one eligible pair.
    """
    by_team: dict[str, list[tuple[str, int, str]]] = {}
    for d, team, idx, cls in entries:
        by_team.setdefault(team, []).append((d, idx, cls))
    delta: dict[str, float] = {}
    for team, rows in by_team.items():
        rows.sort(key=lambda r: r[1])
        pairs = []
        for a in range(len(rows)):
            for b in range(a + 1, len(rows)):
                ca, cb = rows[a][2], rows[b][2]
                if (ca == FINISHED and cb == FINISHED) or (ca == FINISHED and cb == DRIVER):
                    pairs.append((rows[a][0], rows[b][0]))           # first is ahead
                elif ca == DRIVER and cb == FINISHED:                 # not reachable when classified rank first
                    pairs.append((rows[b][0], rows[a][0]))
        involved = {d for p in pairs for d in p}
        m = len(involved)
        if m < 2:
            continue
        keff = k / (m - 1)
        for win, lose in pairs:
            e = _expected(ratings[win], ratings[lose])
            delta[win] = delta.get(win, 0.0) + keff * (1.0 - e)
            delta[lose] = delta.get(lose, 0.0) - keff * (1.0 - e)
    return delta


# ── history ──────────────────────────────────────────────────────────────────

def _signature(years: list[int]) -> dict[str, list[int]]:
    sig = {}
    for y in years:
        p = st.season_path(y)
        try:
            s = p.stat()
            sig[str(y)] = [s.st_mtime_ns, s.st_size]
        except OSError:
            pass
    return sig


def _race_entries(race: dict) -> list[dict]:
    """Deduplicated results (best entry per driver), in finishing order."""
    rows = [r for r in race.get("results") or [] if r.get("driver")]

    def key(r):
        try:
            return int(r.get("position") or 999)
        except (TypeError, ValueError):
            return 999

    rows.sort(key=key)
    seen, out = set(), []
    for r in rows:
        if r["driver"] in seen:
            continue
        seen.add(r["driver"])
        out.append(r)
    return out


def _quali_order(race: dict) -> list[str]:
    q = [r for r in race.get("qualifying") or [] if r.get("driver") and r.get("position")]
    if q:
        q.sort(key=lambda r: int(r["position"]))
        return list(dict.fromkeys(r["driver"] for r in q))
    g = []
    for r in race.get("results") or []:
        try:
            grid = int(r.get("grid") or 0)
        except (TypeError, ValueError):
            grid = 0
        if r.get("driver") and grid > 0:
            g.append((grid, r["driver"]))
    g.sort()
    return list(dict.fromkeys(d for _, d in g))


def _r1(x: float) -> float:
    return round(float(x), 1)


def compute(stores: dict[int, dict]) -> dict:
    """Run all three ratings over `stores` ({year: season store}) in calendar order."""
    years = sorted(y for y, s in stores.items() if any((r.get("results") for r in (s.get("races") or {}).values())))
    names: dict[str, str] = {}
    for y in years:
        for d, info in (stores[y].get("drivers") or {}).items():
            names[d] = f"{info.get('given') or ''} {info.get('family') or ''}".strip() or d

    field: dict[str, float] = {}
    tm: dict[str, float] = {}
    ql: dict[str, float] = {}
    starts: dict[str, int] = {}
    h2h: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    last_seen: dict[str, list] = {}
    peaks: dict[str, dict] = {}
    races_out: list[dict] = []
    first_year = years[0] if years else None
    prev_year = None

    for y in years:
        if prev_year is not None:
            for book in (field, tm, ql):
                for d in book:
                    book[d] = INITIAL + (1.0 - REGRESS) * (book[d] - INITIAL)
        prev_year = y
        races = stores[y].get("races") or {}
        for rnd in sorted(races, key=lambda r: int(r) if str(r).isdigit() else 999):
            race = races[rnd]
            if not race.get("results") or "indianapolis 500" in str(race.get("name") or "").lower():
                continue
            entries = _race_entries(race)
            qorder = _quali_order(race)
            present = list(dict.fromkeys([e["driver"] for e in entries] + qorder))
            # seed new drivers
            for book in (field, tm, ql):
                rated = [book[d] for d in present if d in book]
                base = sum(rated) / len(rated) if rated else INITIAL
                for d in present:
                    if d not in book:
                        book[d] = INITIAL if y == first_year or not rated else base - ROOKIE_OFFSET
            for d in present:
                first_seen.setdefault(d, y)
            pre = {d: (field[d], tm[d], ql[d]) for d in present}

            order, tm_entries, classes = [], [], {}
            for idx, e in enumerate(entries):
                cls = status_class(e.get("status"), e.get("position_text"))
                classes[e["driver"]] = cls
                order.append((e["driver"], WEIGHTS[cls], cls == FINISHED))
                if cls in (FINISHED, DRIVER):
                    tm_entries.append((e["driver"], str(e.get("constructor") or ""), idx, cls))
            # classified drivers first, in position order, then the rest
            order.sort(key=lambda t: 0 if t[2] else 1)
            tm_entries.sort(key=lambda t: (0 if t[3] == FINISHED else 1, t[2]))
            tm_entries = [(d, team, i, cls) for i, (d, team, _, cls) in enumerate(tm_entries)]

            df = field_update(order, field, K_FIELD)
            dt = teammate_update(tm_entries, tm, K_TEAMMATE)
            dq = field_update([(d, 1.0, True) for d in qorder], ql, K_QUALI)
            for d, v in df.items():
                field[d] += v
            for d, v in dt.items():
                tm[d] += v
                h2h[d] = h2h.get(d, 0) + 1
            for d, v in dq.items():
                ql[d] += v

            rec_drivers = {}
            for e in entries:
                d = e["driver"]
                cls = classes[d]
                if cls == EXCLUDED and d not in dq:
                    continue
                if cls != EXCLUDED:
                    starts[d] = starts.get(d, 0) + 1
                last_seen[d] = [y, int(rnd) if str(rnd).isdigit() else rnd]
                rec_drivers[d] = {
                    "constructor": e.get("constructor"), "pos": e.get("position_text"), "class": cls,
                    "elo_pre": _r1(pre[d][0]), "elo_teammate_pre": _r1(pre[d][1]), "elo_quali_pre": _r1(pre[d][2]),
                    "elo": _r1(field[d]), "elo_teammate": _r1(tm[d]), "elo_quali": _r1(ql[d]),
                }
                if starts.get(d, 0) >= PEAK_MIN_RACES:
                    pk = peaks.setdefault(d, {})
                    for key, val in (("elo", field[d]), ("elo_teammate", tm[d]), ("elo_quali", ql[d])):
                        if key not in pk or val > pk[key]["value"]:
                            pk[key] = {"value": _r1(val), "year": y, "round": int(rnd) if str(rnd).isdigit() else rnd}
            races_out.append({"year": y, "round": int(rnd) if str(rnd).isdigit() else rnd, "name": race.get("name"),
                              "date": race.get("date"), "drivers": rec_drivers})

    last_year = years[-1] if years else None
    current = {
        d: {"name": names.get(d, d), "elo": _r1(field[d]), "elo_teammate": _r1(tm[d]), "elo_quali": _r1(ql[d]),
            "starts": starts.get(d, 0), "teammate_h2h": h2h.get(d, 0), "first_year": first_seen.get(d),
            "last": last_seen.get(d), "active": bool(last_seen.get(d) and last_seen[d][0] == last_year)}
        for d in field
    }
    all_time = []
    for d, pk in peaks.items():
        if starts.get(d, 0) < ALL_TIME_MIN_RACES or "elo_teammate" not in pk:
            continue
        all_time.append({"driver": d, "name": names.get(d, d), "peak_teammate": pk["elo_teammate"]["value"],
                         "peak_teammate_at": [pk["elo_teammate"]["year"], pk["elo_teammate"]["round"]],
                         "peak_field": pk.get("elo", {}).get("value"), "peak_quali": pk.get("elo_quali", {}).get("value"),
                         "starts": starts.get(d, 0), "teammate_h2h": h2h.get(d, 0),
                         "first_year": first_seen.get(d), "last_year": (last_seen.get(d) or [None])[0]})
    all_time.sort(key=lambda r: -r["peak_teammate"])
    return {
        "version": VERSION,
        "seasons": years,
        "params": {"K_FIELD": K_FIELD, "K_TEAMMATE": K_TEAMMATE, "K_QUALI": K_QUALI, "INITIAL": INITIAL,
                   "ROOKIE_OFFSET": ROOKIE_OFFSET, "REGRESS": REGRESS, "AMBIGUOUS_WEIGHT": AMBIGUOUS_WEIGHT,
                   "PEAK_MIN_RACES": PEAK_MIN_RACES, "ALL_TIME_MIN_RACES": ALL_TIME_MIN_RACES},
        "races": races_out,
        "current": current,
        "peaks": peaks,
        "all_time": all_time,
    }


def elo_history(seasons: Iterable[int] = range(1950, 2027), stores: dict[int, dict] | None = None,
                use_cache: bool = True) -> dict:
    """
    Field, teammate and qualifying Elo for every driver after every race.

    Returns {"seasons": [years rated], "params": {...},
             "races": [{"year", "round", "name", "date", "drivers": {driverId: {
                 "elo", "elo_teammate", "elo_quali"            (after the race),
                 "elo_pre", "elo_teammate_pre", "elo_quali_pre" (before it: use these for forecasts),
                 "constructor", "pos", "class"}}}],
             "current": {driverId: {"name", "elo", "elo_teammate", "elo_quali", "starts", "teammate_h2h",
                                    "first_year", "last": [year, round], "active"}},
             "peaks": {driverId: {"elo"|"elo_teammate"|"elo_quali": {"value", "year", "round"}}},
             "all_time": [{"driver", "name", "peak_teammate", "peak_teammate_at", "peak_field", "peak_quali",
                           "starts", "teammate_h2h", "first_year", "last_year"}] sorted by peak teammate Elo}

    `stores` ({year: store}) bypasses the disk and the cache (tests). Seasons missing
    from disk are skipped; an empty history returns empty tables.
    """
    if stores is not None:
        return compute(stores)
    years = [int(y) for y in seasons if st.season_path(int(y)).exists()]
    sig = _signature(years)
    if use_cache and CACHE.exists():
        try:
            cached = json.loads(CACHE.read_text(encoding="utf-8"))
            if cached.get("version") == VERSION and cached.get("signature") == sig:
                return cached
        except (OSError, ValueError):
            pass
    loaded = {}
    for y in years:
        try:
            loaded[y] = st.load(y)
        except Exception as exc:  # noqa: BLE001
            logger.info("elo: season %s unreadable: %s", y, exc)
    out = compute(loaded)
    out["signature"] = sig
    if use_cache:
        try:
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(CACHE)
        except OSError as exc:
            logger.info("elo: cache not written: %s", exc)
    return out


def ratings_before(history: dict, year: int, rnd: int) -> dict[str, dict[str, float]]:
    """
    Each driver's latest ratings strictly before (year, rnd), for walk-forward use:
    {driverId: {"elo", "elo_teammate", "elo_quali"}} (post-race values of their last
    race before it; season regression not applied).
    """
    out: dict[str, dict[str, float]] = {}
    for race in history.get("races") or []:
        if (race["year"], race["round"]) >= (year, rnd):
            break
        for d, r in race["drivers"].items():
            out[d] = {"elo": r["elo"], "elo_teammate": r["elo_teammate"], "elo_quali": r["elo_quali"]}
    return out
