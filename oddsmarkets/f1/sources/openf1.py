"""
OpenF1 (https://api.openf1.org/v1/): timing, strategy, race control, weather and
car telemetry for every session since 2023. No key for historical data; CORS is
open, so the site's browser can also read telemetry directly.

Everything is fetched per session and stored compactly:

  docs/paddock/data/<year>/sessions/<session_key>.json   (committed, read by the build and the site)
    session, drivers, laps (per driver: [lap, t_start, ms, s1, s2, s3, i1, i2, st, pit_out]),
    lap_end (per driver: gap to leader and interval at each lap's end), stints, pit,
    race_control, weather, overtakes, result, grid, positions (changes)

  data/f1/telemetry/<year>/<session_key>/<driver>.json.gz  (local and release archive, not in git)
    car: column arrays t (ms from session start), speed, rpm, gear, throttle, brake, drs
    loc: column arrays t, x, y, z

Times inside a session are milliseconds from the session's `date_start`.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from bisect import bisect_right
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.openf1.org/v1"
HEADERS = {"User-Agent": "The Quant Paddock (pchattani.github.io/the-quant-paddock)"}
TIMEOUT = 60
ROOT = Path(__file__).resolve().parents[3]
SITE_DATA = ROOT / "docs" / "paddock" / "data"
TELEMETRY = ROOT / "data" / "f1" / "telemetry"


class Client:
    """Paced GET with retries; `budget` caps calls per run. OpenF1 documents 30 requests a minute for the free tier,
    so calls are spaced 2.1 s apart (about 28 a minute); 0.35 s (about 170 a minute) was over it."""

    def __init__(self, budget: int = 2000, interval: float = 2.1):
        self.budget, self.interval, self.used, self._last = budget, interval, 0, 0.0

    def get(self, endpoint: str, **params) -> list[dict] | None:
        if self.used >= self.budget:
            raise RuntimeError(f"OpenF1 budget of {self.budget} calls spent")
        for attempt in range(5):
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.used += 1
            try:
                r = requests.get(f"{BASE}/{endpoint}", params=params, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException as exc:
                logger.warning("openf1 %s: %s (attempt %d)", endpoint, exc, attempt + 1)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After") or 20 * (attempt + 1)))
                continue
            if r.status_code == 404:
                return []                       # OpenF1 answers 404 "No results found" for an empty query
            if r.status_code != 200:
                logger.warning("openf1 %s answered %s", endpoint, r.status_code)
                time.sleep(5 * (attempt + 1))
                continue
            data = r.json()
            return data if isinstance(data, list) else []
        return None


def _ts(s: Any) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _ms(v: Any) -> int | None:
    try:
        return None if v is None else int(round(float(v) * 1000))
    except (TypeError, ValueError):
        return None


def _rel(t0: float, s: Any) -> int | None:
    t = _ts(s)
    return None if t is None else int(round((t - t0) * 1000))


def session_path(year: int, key: int) -> Path:
    return SITE_DATA / str(year) / "sessions" / f"{key}.json"


def telemetry_path(year: int, key: int, driver: int) -> Path:
    return TELEMETRY / str(year) / str(key) / f"{driver}.json.gz"


def sessions(c: Client, year: int) -> list[dict]:
    return c.get("sessions", year=year) or []


def fetch_session(c: Client, sess: dict) -> dict:
    """The compact session record (everything but telemetry)."""
    key = sess["session_key"]
    t0 = _ts(sess.get("date_start")) or 0.0
    out: dict[str, Any] = {
        "session": {k: sess.get(k) for k in ("session_key", "meeting_key", "session_name", "session_type", "date_start", "date_end",
                                            "circuit_key", "circuit_short_name", "country_name", "location", "year")},
        "drivers": {}, "laps": {}, "lap_end": {}, "stints": [], "pit": [], "race_control": [], "weather": [], "overtakes": [],
        "result": [], "grid": [], "positions": {}, "fetched_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for d in c.get("drivers", session_key=key) or []:
        out["drivers"][str(d["driver_number"])] = {k: d.get(k) for k in ("broadcast_name", "full_name", "name_acronym", "first_name", "last_name",
                                                                         "team_name", "team_colour", "country_code")}
    laps_raw = c.get("laps", session_key=key) or []
    ends: dict[str, list[tuple[int, int]]] = {}
    for l in laps_raw:
        dn = str(l["driver_number"])
        start = _rel(t0, l.get("date_start"))
        dur = _ms(l.get("lap_duration"))
        out["laps"].setdefault(dn, []).append([l.get("lap_number"), start, dur, _ms(l.get("duration_sector_1")), _ms(l.get("duration_sector_2")),
                                               _ms(l.get("duration_sector_3")), l.get("i1_speed"), l.get("i2_speed"), l.get("st_speed"),
                                               1 if l.get("is_pit_out_lap") else 0])
        if start is not None and dur is not None:
            ends.setdefault(dn, []).append((l.get("lap_number"), start + dur))
    for dn in out["laps"]:
        out["laps"][dn].sort(key=lambda r: r[0] or 0)
    for s in c.get("stints", session_key=key) or []:
        out["stints"].append([s.get("driver_number"), s.get("stint_number"), s.get("lap_start"), s.get("lap_end"), s.get("compound"), s.get("tyre_age_at_start")])
    for p in c.get("pit", session_key=key) or []:
        out["pit"].append([p.get("driver_number"), p.get("lap_number"), _rel(t0, p.get("date")), _ms(p.get("lane_duration") or p.get("pit_duration")), _ms(p.get("stop_duration"))])
    for r in c.get("race_control", session_key=key) or []:
        out["race_control"].append([_rel(t0, r.get("date")), r.get("lap_number"), r.get("category"), r.get("flag"), r.get("scope"), r.get("sector"),
                                    r.get("driver_number"), r.get("message")])
    for w in c.get("weather", session_key=key) or []:
        out["weather"].append([_rel(t0, w.get("date")), w.get("air_temperature"), w.get("track_temperature"), w.get("humidity"), w.get("rainfall"),
                               w.get("wind_speed"), w.get("wind_direction"), w.get("pressure")])
    if sess.get("session_type") in ("Race", "Qualifying") or "Sprint" in str(sess.get("session_name")):
        for o in c.get("overtakes", session_key=key) or []:
            out["overtakes"].append([_rel(t0, o.get("date")), o.get("overtaking_driver_number"), o.get("overtaken_driver_number"), o.get("position")])
        for r in c.get("session_result", session_key=key) or []:
            out["result"].append({k: r.get(k) for k in ("position", "driver_number", "number_of_laps", "points", "dnf", "dns", "dsq", "duration", "gap_to_leader")})
        for g in c.get("starting_grid", session_key=key) or []:
            out["grid"].append([g.get("position"), g.get("driver_number"), _ms(g.get("lap_duration"))])
        for p in c.get("position", session_key=key) or []:
            out["positions"].setdefault(str(p["driver_number"]), []).append([_rel(t0, p.get("date")), p.get("position")])
        if sess.get("session_type") == "Race" and ends:
            iv = c.get("intervals", session_key=key) or []
            by: dict[str, list[tuple[int, Any, Any]]] = {}
            for x in iv:
                t = _rel(t0, x.get("date"))
                if t is not None:
                    by.setdefault(str(x["driver_number"]), []).append((t, x.get("gap_to_leader"), x.get("interval")))
            for dn, rows in by.items():
                rows.sort(key=lambda r: r[0])
                ts = [r[0] for r in rows]
                lst = []
                for lap, end in sorted(ends.get(dn, []), key=lambda e: e[0] or 0):
                    i = bisect_right(ts, end) - 1
                    lst.append([lap, rows[i][1], rows[i][2]] if i >= 0 else [lap, None, None])
                out["lap_end"][dn] = lst
    return out


def save_session(year: int, rec: dict) -> Path:
    p = session_path(year, rec["session"]["session_key"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return p


def fetch_telemetry(c: Client, year: int, sess: dict, driver: int) -> Path | None:
    """Raw car data and location for one driver in one session, column-packed and gzipped."""
    key = sess["session_key"]
    t0 = _ts(sess.get("date_start")) or 0.0
    car = c.get("car_data", session_key=key, driver_number=driver)
    loc = c.get("location", session_key=key, driver_number=driver)
    if car is None or loc is None:
        return None
    pack = {"car": {k: [] for k in ("t", "speed", "rpm", "gear", "throttle", "brake", "drs")}, "loc": {k: [] for k in ("t", "x", "y", "z")}}
    # The feed runs all day; keep the session (5 minutes either side).
    span = ((_ts(sess.get("date_end")) or t0) - t0) * 1000
    lo, hi = -300_000, span + 300_000
    car = [r for r in car if (t := _rel(t0, r.get("date"))) is not None and lo <= t <= hi]
    loc = [r for r in loc if (t := _rel(t0, r.get("date"))) is not None and lo <= t <= hi]
    for r in car:
        pack["car"]["t"].append(_rel(t0, r.get("date")))
        for k, src in (("speed", "speed"), ("rpm", "rpm"), ("gear", "n_gear"), ("throttle", "throttle"), ("brake", "brake"), ("drs", "drs")):
            pack["car"][k].append(r.get(src))
    for r in loc:
        pack["loc"]["t"].append(_rel(t0, r.get("date")))
        for k in ("x", "y", "z"):
            pack["loc"][k].append(r.get(k))
    p = telemetry_path(year, key, driver)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(pack, fh, separators=(",", ":"))
    return p


def load_telemetry(year: int, key: int, driver: int) -> dict | None:
    p = telemetry_path(year, key, driver)
    if not p.exists():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        return json.load(fh)
