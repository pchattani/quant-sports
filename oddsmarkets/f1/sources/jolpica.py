"""
Jolpica, the community successor to the Ergast F1 API (https://api.jolpi.ca/ergast/f1/).

No key. Limits: 4 requests a second in a burst, 500 an hour sustained, enforced
per IP with HTTP 429. Every call here goes through one `Pacer`, which spaces
requests to stay under the hourly cap (7.3 s apart by default) and backs off on
429. Pages are 100 rows at most; `paged()` walks `offset` until `total` is met.

The parsers turn Ergast's nested JSON into flat records keyed by Jolpica ids
(`driverId`, `constructorId`, `circuitId`), with times in milliseconds.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)

BASE = "https://api.jolpi.ca/ergast/f1"
HEADERS = {"User-Agent": "The Quant Paddock (pchattani.github.io/the-quant-paddock)"}
TIMEOUT = 30


class BudgetExhausted(RuntimeError):
    pass


class Pacer:
    """Spaces calls `interval` seconds apart, counts them against `budget`, backs off on 429."""

    def __init__(self, budget: int = 450, interval: float = 7.3):
        self.budget, self.interval, self.used, self._last = budget, interval, 0, 0.0

    def get(self, path: str, params: dict | None = None) -> dict | None:
        if self.used >= self.budget:
            raise BudgetExhausted(f"Jolpica budget of {self.budget} calls spent")
        for attempt in range(5):
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.used += 1
            try:
                r = requests.get(f"{BASE}/{path}", params=params, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException as exc:
                logger.warning("jolpica %s: %s (attempt %d)", path, exc, attempt + 1)
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 429:
                back = int(r.headers.get("Retry-After") or 60 * (attempt + 1))
                logger.warning("jolpica 429 on %s; sleeping %ds", path, back)
                time.sleep(back)
                continue
            if r.status_code == 404:
                return None
            if r.status_code != 200:
                logger.warning("jolpica %s answered %s", path, r.status_code)
                time.sleep(5 * (attempt + 1))
                continue
            return r.json().get("MRData")
        return None


def paged(pacer: Pacer, path: str, table: str, key: str, limit: int = 100) -> Iterator[dict]:
    """Every item of MRData[table][key] across pages (each page a list of races or standings lists)."""
    offset, total = 0, None
    while total is None or offset < total:
        d = pacer.get(path, {"limit": limit, "offset": offset})
        if not d:
            return
        total = int(d.get("total") or 0)
        for item in (d.get(table) or {}).get(key) or []:
            yield item
        offset += limit


# ── parsing ─────────────────────────────────────────────────────────────────

_TIME = re.compile(r"^(?:(\d+):)?(\d+(?:\.\d+)?)$")


def to_ms(t: Any) -> int | None:
    """'1:23.456' or '83.456' as milliseconds; None for missing or unparseable."""
    if t is None or t == "":
        return None
    m = _TIME.match(str(t).strip())
    if not m:
        return None
    return int(round((int(m.group(1) or 0) * 60 + float(m.group(2))) * 1000))


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def driver_rec(d: dict) -> dict:
    return {"code": d.get("code"), "number": _int(d.get("permanentNumber")), "given": d.get("givenName"),
            "family": d.get("familyName"), "dob": d.get("dateOfBirth"), "nationality": d.get("nationality")}


def constructor_rec(c: dict) -> dict:
    return {"name": c.get("name"), "nationality": c.get("nationality")}


def race_rec(r: dict) -> dict:
    c = r.get("Circuit") or {}
    loc = c.get("Location") or {}
    sessions = {}
    for key, name in (("FirstPractice", "fp1"), ("SecondPractice", "fp2"), ("ThirdPractice", "fp3"),
                      ("Qualifying", "quali"), ("Sprint", "sprint"), ("SprintQualifying", "sprint_quali"), ("SprintShootout", "sprint_quali")):
        s = r.get(key)
        if s:
            sessions[name] = (s.get("date") or "") + ("T" + s["time"] if s.get("time") else "")
    return {
        "name": r.get("raceName"), "date": r.get("date"), "time": r.get("time"),
        "circuit": {"id": c.get("circuitId"), "name": c.get("circuitName"), "locality": loc.get("locality"),
                    "country": loc.get("country"), "lat": _float(loc.get("lat")), "long": _float(loc.get("long"))},
        "sessions": sessions,
    }


def result_rec(x: dict) -> dict:
    fl = x.get("FastestLap") or {}
    return {
        "driver": (x.get("Driver") or {}).get("driverId"), "constructor": (x.get("Constructor") or {}).get("constructorId"),
        "number": _int(x.get("number")), "grid": _int(x.get("grid")), "position": _int(x.get("position")),
        "position_text": x.get("positionText"), "points": _float(x.get("points")), "laps": _int(x.get("laps")),
        "status": x.get("status"), "time_ms": _int((x.get("Time") or {}).get("millis")),
        "fastest_rank": _int(fl.get("rank")), "fastest_lap": _int(fl.get("lap")), "fastest_ms": to_ms((fl.get("Time") or {}).get("time")),
    }


def quali_rec(x: dict) -> dict:
    return {"driver": (x.get("Driver") or {}).get("driverId"), "constructor": (x.get("Constructor") or {}).get("constructorId"),
            "number": _int(x.get("number")), "position": _int(x.get("position")),
            "q1": to_ms(x.get("Q1")), "q2": to_ms(x.get("Q2")), "q3": to_ms(x.get("Q3"))}
