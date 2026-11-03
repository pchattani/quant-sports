"""
Match weather and venue elevation for The Quant Scrum from Open-Meteo (free API for non-commercial use, data CC BY 4.0,
credit "Weather data by Open-Meteo.com"; terms and the robots.txt reading in docs/research/data_sources.md: the API
hosts answer `Disallow: /`, read across the program as a crawler rule on hosts that only serve the documented API,
flagged to the user; turn the source off with SOURCE_OPENMETEO_RUGBY_ENABLED=0).

    geocoding  geocoding-api.open-meteo.com/v1/search?name=<city>      venue city -> latitude, longitude (GeoNames)
    elevation  api.open-meteo.com/v1/elevation?latitude=..&longitude=..  up to 100 points a call (Copernicus DEM 90 m)
    archive    archive-api.open-meteo.com/v1/archive                     realised hourly weather (ERA5 from 1940): one
                                                                         call per match day with every venue that day
    forecast   api.open-meteo.com/v1/forecast                            the next 16 days, for upcoming tests

Realised weather is known only after the match, so it is never a pre-match model input (no look-ahead): it feeds the
match pages and the Lab. Upcoming tests show the forecast as issued. Calls are paced (`INTERVAL` s), retried with
back-off, counted against a budget and cached gzipped under data/rugby/weather/ (git-ignored); a finished day is
fetched once.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from ...common import polite

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
FLAG = "SOURCE_OPENMETEO_RUGBY_ENABLED"
INTERVAL = 1.5
UA = "TheQuantScrum/1.0 (non-commercial; +https://pchattani.github.io/the-quant-scrum)"
CREDIT = "Weather data by Open-Meteo.com (CC BY 4.0)"
HOURLY = ("temperature_2m", "relative_humidity_2m", "precipitation", "rain", "wind_speed_10m", "wind_gusts_10m")
URL = {"geo": "https://geocoding-api.open-meteo.com/v1/search", "elev": "https://api.open-meteo.com/v1/elevation",
       "archive": "https://archive-api.open-meteo.com/v1/archive", "forecast": "https://api.open-meteo.com/v1/forecast"}


def enabled() -> bool:
    return polite.flag_on(FLAG)


def raw_dir() -> Path:
    return Path(os.environ.get("RUGBY_WEATHER") or (ROOT / "data" / "rugby" / "weather"))


class Budget(RuntimeError):
    pass


class Client:
    def __init__(self, budget: int = 3000, interval: float = INTERVAL, offline: bool = False):
        self.budget, self.interval, self.offline = budget, interval, offline or polite.on_ci() or not enabled()
        self.used = self.hits = self.failures = 0
        self._last = 0.0
        self._s = None

    def _path(self, kind: str, params: dict) -> Path:
        key = json.dumps(params, sort_keys=True)
        return raw_dir() / kind / (hashlib.sha1(key.encode()).hexdigest()[:16] + ".json.gz")

    def get(self, kind: str, params: dict, max_age: float | None = None) -> Any:
        p = self._path(kind, params)
        if p.exists():
            fresh = max_age is None or (time.time() - p.stat().st_mtime) <= max_age
            if fresh or self.offline:
                try:
                    with gzip.open(p, "rt", encoding="utf-8") as fh:
                        self.hits += 1
                        return json.load(fh)
                except (OSError, ValueError):
                    pass
        if self.offline:
            return None
        import requests
        if self._s is None:
            self._s = requests.Session()
            self._s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        for attempt in range(4):
            if self.used >= self.budget:
                raise Budget(f"Open-Meteo budget {self.budget} spent")
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.used += 1
            try:
                r = self._s.get(URL[kind], params=params, timeout=60)
            except requests.RequestException as e:
                log.warning("open-meteo %s: %s", kind, e)
                time.sleep(20 * (attempt + 1))
                continue
            if r.status_code == 200:
                d = r.json()
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                    json.dump(d, fh, separators=(",", ":"))
                os.replace(tmp, p)
                return d
            if r.status_code in (429, 500, 502, 503, 504):
                log.warning("open-meteo %s -> %s; backing off", kind, r.status_code)
                time.sleep(60 * (attempt + 1))
                continue
            self.failures += 1
            log.warning("open-meteo %s -> %s %s", kind, r.status_code, r.text[:200])
            return None
        self.failures += 1
        return None


def geocode(c: Client, city: str, country: str = "") -> dict | None:
    """The best GeoNames match for a venue city: {lat, lon, name, country, elev}; the country, when given, must agree."""
    d = c.get("geo", {"name": city, "count": 10, "language": "en", "format": "json"})
    res = (d or {}).get("results") or []
    if not res:
        return None
    cc = (country or "").lower()
    if cc:
        hit = [r for r in res if cc in str(r.get("country") or "").lower() or str(r.get("country") or "").lower() in cc]
        if hit:
            res = hit
        else:
            return None
    r = max(res, key=lambda r: (r.get("population") or 0))
    return {"lat": round(float(r["latitude"]), 4), "lon": round(float(r["longitude"]), 4), "name": r.get("name"),
            "country": r.get("country"), "elev": r.get("elevation")}


def elevations(c: Client, pts: list[tuple[float, float]]) -> list[float | None]:
    out: list[float | None] = []
    for i in range(0, len(pts), 100):
        chunk = pts[i:i + 100]
        d = c.get("elev", {"latitude": ",".join(f"{a:.4f}" for a, _ in chunk),
                           "longitude": ",".join(f"{b:.4f}" for _, b in chunk)})
        ev = (d or {}).get("elevation") or [None] * len(chunk)
        out += [None if v is None else float(v) for v in ev]
    return out


def archive_day(c: Client, day: str, pts: list[tuple[float, float]]) -> list[dict] | None:
    """Hourly realised weather (UTC) on `day` and the day after (an evening kick-off runs past midnight UTC) at each
    point; one dict per point: {"time": [...], <var>: [...]}."""
    from datetime import date, timedelta
    end = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    d = c.get("archive", {"latitude": ",".join(f"{a:.4f}" for a, _ in pts),
                          "longitude": ",".join(f"{b:.4f}" for _, b in pts), "start_date": day, "end_date": end,
                          "hourly": ",".join(HOURLY), "timezone": "GMT", "wind_speed_unit": "kmh"})
    if d is None:
        return None
    rows = d if isinstance(d, list) else [d]
    return [r.get("hourly") or {} for r in rows]


def forecast(c: Client, lat: float, lon: float, max_age: float = 6 * 3600) -> dict | None:
    d = c.get("forecast", {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "hourly": ",".join(HOURLY),
                           "timezone": "GMT", "forecast_days": 16, "wind_speed_unit": "kmh"}, max_age=max_age)
    return (d or {}).get("hourly")


def window(hourly: dict, kickoff_iso: str, hours: int = 2) -> dict | None:
    """Kick-off hour and the next `hours`: mean temperature (C), humidity (%), wind and gusts (km/h); rain summed over
    the hours ending kick-off + 1 to kick-off + hours + 1 (Open-Meteo's precipitation at hour h is the hour before)."""
    times = hourly.get("time") or []
    k = str(kickoff_iso or "")[:13]
    try:
        i = next(j for j, t in enumerate(times) if t[:13] == k)
    except StopIteration:
        return None

    def vals(var, lo, hi):
        xs = (hourly.get(var) or [])[lo:hi]
        return [float(x) for x in xs if x is not None]
    t = vals("temperature_2m", i, i + hours + 1)
    if not t:
        return None
    rh = vals("relative_humidity_2m", i, i + hours + 1)
    w = vals("wind_speed_10m", i, i + hours + 1)
    g = vals("wind_gusts_10m", i, i + hours + 1)
    pr = vals("precipitation", i + 1, i + hours + 2)
    return {"temp": round(sum(t) / len(t), 1), "rh": round(sum(rh) / len(rh)) if rh else None,
            "wind": round(sum(w) / len(w), 1) if w else None, "gust": round(max(g), 1) if g else None,
            "rain": round(sum(pr), 1) if pr else None}
