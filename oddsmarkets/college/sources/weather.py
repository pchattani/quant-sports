"""
Game-time weather for college football (round 4 research; docs/research/college_edge.md, data_sources.md).

Three steps, each cached under data/college/weather/ (git-ignored; backfilled once, then only new games):

1. Venues: ESPN's public football scoreboards (one call per week, the Campus client paced at 1 s) give each game's
   venue id, city, state and ESPN's `indoor` flag, which the season stores do not keep.
2. Coordinates: Open-Meteo's geocoding API (GeoNames data, CC BY 4.0) for the venue's city and state; city level is
   close enough for weather (a stadium sits within a few km of its city's point).
3. Weather: Open-Meteo's historical weather API (ERA5 / ERA5-Land reanalysis, CC BY 4.0, "Weather data by
   Open-Meteo.com"), hourly temperature, precipitation, wind speed and gusts at 10 m, relative humidity; one call per
   venue and window of at most 14 days (a call of at most 14 days and 10 variables counts as one API call under the
   free tier's limits: under 10,000 a day, 5,000 an hour, 600 a minute), paced at 1 s.

Reanalysis weather is what happened, not what was forecast before kickoff: in the backtest it is an upper bound for
the value of a weather forecast (the oracle test of the round-3 rules), never evidence for a model on its own.

    uv run python -m oddsmarkets.college.sources.weather venues --from 2013 --to 2026
    uv run python -m oddsmarkets.college.sources.weather geocode
    uv run python -m oddsmarkets.college.sources.weather weather
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

from oddsmarkets.college import store

logger = logging.getLogger(__name__)
GEO = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
PREVIOUS = "https://previous-runs-api.open-meteo.com/v1/forecast"
HEADERS = {"User-Agent": "The Quant Campus (pchattani.github.io/the-quant-campus; research use)"}
HOURLY = ["temperature_2m", "precipitation", "wind_speed_10m", "wind_gusts_10m", "relative_humidity_2m"]
GAME_HOURS = 4                      # kickoff hour and the three after it
STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
          "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
          "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
          "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
          "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
          "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
          "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
          "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
          "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
          "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia", "PR": "Puerto Rico"}


def wdir() -> Path:
    d = store.paths()["raw"] / "weather"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p: Path, obj) -> None:
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


class Paced:
    """A paced GET (at least `interval` s between calls) with a few retries; stops on 429 rather than pushing on."""

    def __init__(self, interval: float = 1.0):
        self.interval, self.last, self.used = interval, 0.0, 0

    def get(self, url: str, params: dict) -> dict | None:
        for k in range(3):
            wait = self.interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.used += 1
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=60)
            except requests.RequestException as e:
                logger.warning("weather GET failed (%s), retry %d", e, k)
                time.sleep(5 * (k + 1))
                continue
            if r.status_code == 429:
                raise RuntimeError(f"rate limited by {url}: {r.text[:200]}")
            if r.status_code >= 500:
                time.sleep(10 * (k + 1))
                continue
            if r.status_code != 200:
                logger.warning("weather GET %s -> %s %s", url, r.status_code, r.text[:200])
                return None
            return r.json()
        return None


# ── 1. venues from ESPN scoreboards ─────────────────────────────────────────

def fetch_venues(first: int, last: int) -> dict:
    from oddsmarkets.college.sources import espn
    p = wdir() / "venues_cfb.json"
    cur = _read(p, {"games": {}, "venues": {}, "weeks_done": []})
    done = set(cur.get("weeks_done") or [])
    c = espn.Client(budget=2000, interval=1.0)
    for season in range(int(first), int(last) + 1):
        cal = espn.football_calendar(espn.scoreboard_week(c, season, 2, 1))
        weeks = sorted({(int(r[0]), int(r[1])) for r in cal if r and str(r[0]).isdigit()}) or \
            [(2, w) for w in range(1, 17)] + [(3, 1)]
        for stype, wk in weeks:
            tag = f"{season}-{stype}-{wk}"
            if tag in done:
                continue
            raw = espn.scoreboard_week(c, season, stype, wk)
            for ev in (raw or {}).get("events") or []:
                comp = (ev.get("competitions") or [{}])[0]
                v = comp.get("venue") or {}
                if not v.get("id"):
                    continue
                a = v.get("address") or {}
                cur["venues"][str(v["id"])] = {"name": v.get("fullName"), "city": a.get("city"), "state": a.get("state"),
                                               "country": a.get("country"), "indoor": bool(v.get("indoor"))}
                cur["games"][str(ev.get("id"))] = {"vid": str(v["id"]), "date": ev.get("date")}
            if raw is not None:
                done.add(tag)
            cur["weeks_done"] = sorted(done)
        _write(p, cur)
        logger.info("venues: season %d done (%d games, %d venues, %d calls)", season, len(cur["games"]),
                    len(cur["venues"]), c.used if hasattr(c, "used") else -1)
    return cur


# ── 2. coordinates ──────────────────────────────────────────────────────────

def geocode(interval: float = 1.0) -> dict:
    v = _read(wdir() / "venues_cfb.json", {}).get("venues") or {}
    p = wdir() / "geo.json"
    geo = _read(p, {})
    pc = Paced(interval)
    for vid, r in sorted(v.items()):
        key = f"{r.get('city')}|{r.get('state')}|{r.get('country')}"
        if key in geo or not r.get("city"):
            continue
        params = {"name": r["city"], "count": 10, "language": "en", "format": "json"}
        us = (r.get("country") in (None, "USA", "US", "United States")) and (r.get("state") in STATES or r.get("state") is None)
        if us:
            params["countryCode"] = "US"
        res = (pc.get(GEO, params) or {}).get("results") or []
        pick = None
        sname = STATES.get(str(r.get("state") or ""))
        for x in res:
            if sname and x.get("admin1") == sname:
                pick = x
                break
        if pick is None and res and not sname:
            pick = res[0]
        geo[key] = {"lat": pick["latitude"], "lon": pick["longitude"], "elev": pick.get("elevation"),
                    "name": pick.get("name"), "admin1": pick.get("admin1")} if pick else None
        _write(p, geo)
    logger.info("geocode: %d keys, %d calls", len(geo), pc.used)
    return geo


def venue_coords() -> dict[str, dict]:
    v = _read(wdir() / "venues_cfb.json", {}).get("venues") or {}
    geo = _read(wdir() / "geo.json", {})
    out = {}
    for vid, r in v.items():
        g = geo.get(f"{r.get('city')}|{r.get('state')}|{r.get('country')}")
        if g:
            out[vid] = {**r, **g}
    return out


# ── 3. weather ──────────────────────────────────────────────────────────────

def _kick(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(iso)).astimezone(UTC)
    except (TypeError, ValueError):
        return None


def windows(dates: list[date], span: int = 14) -> list[tuple[date, date]]:
    """Cover sorted dates with windows of at most `span` days."""
    out: list[tuple[date, date]] = []
    for d in sorted(set(dates)):
        if out and (d - out[-1][0]).days < span:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def fetch_weather(seasons: tuple[int, int] | None = None, interval: float = 1.0, max_calls: int = 4500,
                  kind: str = "era5") -> dict:
    """Hourly weather for every outdoor game with venue coordinates; returns {gid: features}. Stops after
    `max_calls` calls (the free tier allows 5,000 an hour); run again to continue.
    kind "era5": realised (reanalysis) weather, game_weather.json; kind "fc1": the forecast issued about 24 h before
    each hour (previous-runs archive, `_previous_day1`; wind and precipitation from February 2024),
    game_forecast.json."""
    vg = _read(wdir() / "venues_cfb.json", {}).get("games") or {}
    coords = venue_coords()
    p = wdir() / ("game_weather.json" if kind == "era5" else "game_forecast.json")
    url = ARCHIVE if kind == "era5" else PREVIOUS
    hourly = HOURLY if kind == "era5" else [h + "_previous_day1" for h in HOURLY]
    have = _read(p, {})
    by_v: dict[str, list[tuple[str, datetime]]] = {}
    for gid, r in vg.items():
        k = _kick(r.get("date"))
        if k is None or gid in have:
            continue
        if seasons and not (seasons[0] <= (k - timedelta(days=60)).year <= seasons[1]):
            continue
        c = coords.get(r["vid"])
        if not c:
            continue
        if c.get("indoor"):
            have[gid] = {"indoor": True}
            continue
        if kind == "era5" and k > datetime.now(UTC) - timedelta(days=6):   # the archive lags about 5 days
            continue
        if kind != "era5" and (k < datetime(2024, 2, 1, tzinfo=UTC) or k > datetime.now(UTC)):
            continue
        by_v.setdefault(r["vid"], []).append((gid, k))
    pc = Paced(interval)
    try:
        for vid, games in sorted(by_v.items()):
            c = coords[vid]
            for a, b in windows([k.date() for _, k in games]):
                if pc.used >= max_calls:
                    raise StopIteration
                d = pc.get(url, {"latitude": c["lat"], "longitude": c["lon"], "start_date": a.isoformat(),
                                     "end_date": (b + timedelta(days=1)).isoformat(), "hourly": ",".join(hourly),
                                     "timezone": "GMT", "wind_speed_unit": "mph", "temperature_unit": "fahrenheit",
                                     "precipitation_unit": "mm"})
                if not d:
                    continue
                hz = d.get("hourly") or {}
                times = hz.get("time") or []
                ix = {t: i for i, t in enumerate(times)}
                for gid, k in games:
                    if not (a <= k.date() <= b):
                        continue
                    h0 = k.replace(minute=0, second=0, microsecond=0)
                    if k.minute >= 30:
                        h0 += timedelta(hours=1)
                    idx = [ix.get((h0 + timedelta(hours=j)).strftime("%Y-%m-%dT%H:%M")) for j in range(GAME_HOURS)]
                    idx = [i for i in idx if i is not None]
                    if not idx:
                        continue

                    def vals(name, hz=hz, idx=idx):
                        arr = hz.get(name) or []
                        return [arr[i] for i in idx if i < len(arr) and arr[i] is not None]
                    t, pr, w, gu, rh = (vals(n) for n in hourly)
                    have[gid] = {"indoor": False, "temp_f": round(t[0], 1) if t else None,
                                 "precip_mm": round(sum(pr), 2) if pr else None,
                                 "wind_mph": round(sum(w) / len(w), 1) if w else None,
                                 "gust_mph": round(max(gu), 1) if gu else None,
                                 "rh": round(rh[0], 0) if rh else None, "lat": c["lat"], "lon": c["lon"]}
            _write(p, have)
    except StopIteration:
        logger.info("weather: call cap %d reached; run again to continue", max_calls)
    _write(p, have)
    logger.info("weather: %d games, %d calls", len(have), pc.used)
    return have


def game_weather() -> dict[str, dict]:
    return _read(wdir() / "game_weather.json", {})


def game_forecast() -> dict[str, dict]:
    return _read(wdir() / "game_forecast.json", {})


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["venues", "geocode", "weather", "forecast"])
    ap.add_argument("--from", dest="first", type=int, default=2013)
    ap.add_argument("--to", dest="last", type=int, default=2026)
    ap.add_argument("--max-calls", type=int, default=4500)
    a = ap.parse_args(argv)
    if a.cmd == "venues":
        fetch_venues(a.first, a.last)
    elif a.cmd == "geocode":
        geocode()
    elif a.cmd == "weather":
        fetch_weather((a.first, a.last), max_calls=a.max_calls)
    else:
        fetch_weather((a.first, a.last), max_calls=a.max_calls, kind="fc1")


if __name__ == "__main__":
    main()

