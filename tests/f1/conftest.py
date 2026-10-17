"""Synthetic Paddock data for the analytics and build tests: season stores (and one OpenF1 race
session) written into a temporary data root, with every model cache redirected, restored after."""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

import pytest

YEAR = 2031
N_DRIVERS = 10
LAPS = 20
POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
SESSION_KEY = 9001


def drv(i: int) -> str:
    return f"drv{i}"


def team(i: int) -> str:
    return f"team{i // 2}"


def number(i: int) -> int:
    return 10 + i


def _race(year: int, r: int, rng: random.Random, retire: dict[str, tuple[int, str]], pit_lane: set[str], sprint: bool) -> dict:
    """One finished round: qualifying, results, laps, positions, pit stops (drv0 fastest ... drv9 slowest)."""
    d0 = date(year, 3, 1) + timedelta(days=7 * (r - 1))
    q = []
    for i in range(N_DRIVERS):
        base = 90000 + 150 * i + rng.randint(-60, 60)
        q.append((base, i))
    q.sort()
    qual = []
    for pos, (t, i) in enumerate(q, 1):
        qual.append({"driver": drv(i), "constructor": team(i), "number": number(i), "position": pos,
                     "q1": t + 400, "q2": t + 200 if pos <= 15 else None, "q3": t if pos <= 10 else None})
    grid = {row["driver"]: (0 if row["driver"] in pit_lane else row["position"]) for row in qual}
    laps, cum = {}, {}
    for i in range(N_DRIVERS):
        d = drv(i)
        n = retire[d][0] if d in retire else LAPS
        lst, acc, c = [], (grid[d] or N_DRIVERS) * 300.0, []
        for L in range(1, n + 1):
            ms = 92000 + 150 * i + 30 * ((L - 1) % 10) + rng.randint(-150, 150) + (6000 if L == 1 else 0)
            if L == 10:
                ms += 20000
            if L == 11:
                ms += 3000
            lst.append(ms)
            acc += ms
            c.append(acc)
        laps[d], cum[d] = lst, c
    finishers = sorted((cum[d][-1], d) for d in laps if d not in retire)
    order = [d for _, d in finishers] + sorted((d for d in retire), key=lambda d: -retire[d][0])
    positions = {d: [] for d in laps}
    for L in range(LAPS):
        lap = sorted((c[L], d) for d, c in cum.items() if L < len(c))
        for k, (_t, d) in enumerate(lap, 1):
            positions[d].append(k)
    results = []
    fastest = sorted((min(laps[d][1:]), d) for d in laps if len(laps[d]) > 1)
    frank = {d: k for k, (_t, d) in enumerate(fastest, 1)}
    for pos, d in enumerate(order, 1):
        i = int(d[3:])
        ret = d in retire
        results.append({"driver": d, "constructor": team(i), "number": number(i), "grid": grid[d], "position": pos,
                        "position_text": "R" if ret else str(pos), "points": 0.0 if ret or pos > 10 else float(POINTS[pos - 1]),
                        "laps": len(laps[d]), "status": retire[d][1] if ret else "Finished",
                        "time_ms": None if ret else int(round(cum[d][-1] - (grid[d] or N_DRIVERS) * 300.0)),
                        "fastest_rank": frank.get(d), "fastest_lap": 5, "fastest_ms": min(laps[d][1:]) if len(laps[d]) > 1 else None})
    pit = [{"driver": d, "stop": 1, "lap": 10, "duration_ms": 22000 + 100 * int(d[3:])} for d in laps if len(laps[d]) >= 10]
    sessions = {"quali": f"{(d0 - timedelta(days=1)).isoformat()}T14:00:00Z"}
    race = {"name": f"Test Grand Prix {r}", "date": d0.isoformat(), "time": "13:00:00Z",
            "circuit": {"id": f"circ{r % 3}", "name": f"Circuit {r % 3}", "locality": "Town", "country": "Land", "lat": 0.0, "long": 0.0},
            "sessions": sessions, "results": results, "qualifying": qual, "laps": laps, "positions": positions, "pitstops": pit}
    if sprint:
        sessions["sprint"] = f"{(d0 - timedelta(days=1)).isoformat()}T10:00:00Z"
        race["sprint"] = [{"driver": d, "constructor": team(int(d[3:])), "number": number(int(d[3:])), "grid": k + 2 if k < 9 else 1,
                           "position": k + 1, "position_text": str(k + 1), "points": float(max(0, 8 - k)), "laps": 8,
                           "status": "Finished", "time_ms": 700000 + k * 1000} for k, d in enumerate(order)]
    return race


def make_store(year: int, done: int, total: int, seed: int = 0, sprint_round: int | None = 2) -> dict:
    rng = random.Random(seed + year)
    races = {}
    retire_by_round = {2: {drv(3): (12, "Engine")}, 3: {drv(5): (5, "Collision")}}
    for r in range(1, total + 1):
        if r <= done:
            races[str(r)] = _race(year, r, rng, retire_by_round.get(r, {}), {drv(9)} if r == 1 else set(), r == sprint_round)
        else:
            d0 = date(year, 3, 1) + timedelta(days=7 * (r - 1))
            races[str(r)] = {"name": f"Test Grand Prix {r}", "date": d0.isoformat(), "time": "13:00:00Z",
                             "circuit": {"id": f"circ{r % 3}", "name": f"Circuit {r % 3}", "locality": "Town", "country": "Land"},
                             "sessions": {"quali": f"{(d0 - timedelta(days=1)).isoformat()}T14:00:00Z"}}
    return {"season": year, "races": races,
            "drivers": {drv(i): {"code": f"D{i:02d}", "number": number(i), "given": "Driver", "family": f"Number{i}", "dob": "2000-01-01",
                                 "nationality": "Testish"} for i in range(N_DRIVERS)},
            "constructors": {f"team{j}": {"name": f"Team {j}", "nationality": "Nowhere"} for j in range(N_DRIVERS // 2)},
            "meta": {"fetched": {}, "updated_at": None}}


def make_session(store: dict, rnd: int = 1) -> dict:
    """An OpenF1-style race record for `rnd`, built from the store's lap times, with planted passes,
    a safety car (laps 15-16), a penalty for car 12 and pit rows."""
    race = store["races"][str(rnd)]
    laps, starts = {}, {}
    for d, lst in race["laps"].items():
        i = int(d[3:])
        t = 1000 * i
        rows = []
        for L, ms in enumerate(lst, 1):
            rows.append([L, t, ms, ms // 3, ms // 3, ms - 2 * (ms // 3), 280, 290, 300 + (9 - i), 1 if L == 11 else 0])
            starts[(d, L)] = t
            t += ms
        laps[str(number(i))] = rows
    def t_of(d, L, frac=0.5):
        return int(starts[(d, L)] + frac * race["laps"][d][L - 1])
    over = [
        [t_of("drv1", 5), number(1), number(0), 1],     # valid pass
        [t_of("drv1", 7), number(1), number(2), 2],     # valid pass
        [t_of("drv3", 15), number(3), number(2), 3],    # under the safety car: dropped
        [t_of("drv6", 10), number(6), number(4), 5],    # on a car on its in-lap: dropped
    ]
    d_start = f"{race['date']}T13:00:00+00:00"
    return {"session": {"session_key": SESSION_KEY, "meeting_key": 1, "session_name": "Race", "session_type": "Race", "date_start": d_start,
                        "date_end": None, "circuit_short_name": "Test", "country_name": "Land", "year": store["season"]},
            "drivers": {str(number(i)): {"name_acronym": f"D{i:02d}", "full_name": f"Driver Number{i}", "team_name": f"Team {i // 2}",
                                         "team_colour": f"{(i // 2) * 30 + 10:02X}{(i // 2) * 20 + 30:02X}AA", "last_name": f"Number{i}"}
                        for i in range(N_DRIVERS)},
            "laps": laps, "lap_end": {}, "stints": [[number(i), s, a, b, c, 0] for i in range(N_DRIVERS)
                                                    for s, a, b, c in ((1, 1, 10, "MEDIUM"), (2, 11, LAPS, "HARD"))],
            "pit": [[number(i), 10, 0, 21000 + 100 * i, 2300 + 100 * i] for i in range(N_DRIVERS)],
            "race_control": [[t_of("drv0", 15, 0.1), 15, "SafetyCar", None, None, None, None, "SAFETY CAR DEPLOYED"],
                             [t_of("drv0", 16, 0.1), 16, "SafetyCar", None, None, None, None, "SAFETY CAR IN THIS LAP"],
                             [t_of("drv0", 8), 8, "Other", None, None, None, number(2),
                              f"FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR {number(2)} (D02) - CAUSING A COLLISION"],
                             [t_of("drv0", 9), 9, "Other", None, None, None, number(2), f"PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR {number(2)}"],
                             [t_of("drv0", 20), 20, "Flag", "CHEQUERED", "Track", None, None, "CHEQUERED FLAG"]],
            "weather": [[1000 * k, 25.0, 40.0, 50, 0, 1.0, 90, 1000] for k in range(10)],
            "overtakes": over, "result": [], "grid": [], "positions": {}}


@pytest.fixture
def paddock_data(tmp_path, monkeypatch):
    """A temporary data root with seasons YEAR-1 (complete) and YEAR (3 of 5 rounds done, one OpenF1
    race session), caches redirected; yields (data_root, cache_root)."""
    from oddsmarkets.f1 import analytics as an
    from oddsmarkets.f1 import store as st
    from oddsmarkets.f1.analytics import forecasts as fc
    from oddsmarkets.f1.models import backtest as bt
    from oddsmarkets.f1.models import circuits as circ
    from oddsmarkets.f1.models import elo
    from oddsmarkets.f1.models import laptime as lt
    from oddsmarkets.f1.sources import openf1 as of
    for mod, attr in ((st, "DATA"), (of, "SITE_DATA"), (circ, "CACHE"), (circ, "RECORDS_PATH"), (lt, "CACHE"), (elo, "CACHE"),
                      (bt, "OUT"), (fc, "CACHE"), (an, "_ROOT_SET")):
        monkeypatch.setattr(mod, attr, getattr(mod, attr))
    data, cache = tmp_path / "data", tmp_path / "cache"
    for y, done, total in ((YEAR - 1, 4, 4), (YEAR, 3, 5)):
        s = make_store(y, done, total)
        p = data / str(y) / "store.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(s), encoding="utf-8")
    cur = json.loads((data / str(YEAR) / "store.json").read_text(encoding="utf-8"))
    sp = data / str(YEAR) / "sessions" / f"{SESSION_KEY}.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(make_session(cur, 1)), encoding="utf-8")
    an.set_data_root(data)
    an.set_cache_root(cache)
    yield data, cache
    an._clear_caches()


def payload_keys() -> dict[str, set[str]]:
    """Top-level keys PAYLOADS.md promises for each payload."""
    return {
        "index.json": {"updated_at", "current_season", "seasons", "next", "last", "drivers", "teams", "seasons_meta"},
        "glossary.json": {"groups", "model"},
        "calibration.json": {"updated_at"},
        "markets.json": {"updated_at", "drivers_title", "constructors_title", "next_race", "h2h"},
        "elo.json": {"all_time", "current"},
        "lab.json": {"fields", "metrics", "rows", "windows"},
        "season.json": {"ok", "year", "updated_at", "rounds_total", "rounds_done", "calendar", "standings", "progression", "championship",
                        "car_pace", "driver_effects", "car_driver_split", "elo", "teams"},
        "drivers.json": {"metrics", "drivers"},
        "teams.json": {"metrics", "teams"},
        "race": {"ok", "year", "round", "name", "date", "circuit", "status", "forecast", "sprint_forecast", "results", "qualifying", "sprint",
                 "laps", "stints", "pits", "control", "weather", "overtakes", "pace", "expected_v_actual", "awards", "sessions", "telemetry"},
        "career": {"name", "dob", "nationality", "seasons", "elo", "teammates", "totals"},
    }
