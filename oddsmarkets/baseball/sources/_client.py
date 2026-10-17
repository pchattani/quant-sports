"""
One paced HTTP client for every baseball source (Baseball Savant, MLB Stats API, Retrosheet, Chadwick,
Lahman, ESPN), mirroring tennis/sources/_client.py.

`Client.get` / `get_text` / `get_bytes` space requests (`interval` seconds apart), retry with back-off on
network errors, 429 and 5xx (honouring Retry-After), count calls against a `budget` and never raise on a
bad answer: they log and return None. Running out of budget raises `BudgetExhausted`, so a backfill stops
cleanly and resumes next time.

`used`, `failures` and `seconds` (time spent waiting on the network) size the backfills; `by_host` counts
calls per host so one run can report calls per source. `interval` can be set per host (`intervals`), so a
single client paces Savant at 3 s and ESPN at 1 s.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

UA = "The Quant Bullpen (pchattani.github.io/the-quant-bullpen; baseball analytics, non-commercial)"
TIMEOUT = 120


class BudgetExhausted(RuntimeError):
    pass


class Client:
    def __init__(self, budget: int = 2000, interval: float = 0.5, retries: int = 4, name: str = "baseball",
                 headers: dict | None = None, intervals: dict[str, float] | None = None):
        self.budget, self.interval, self.retries, self.name = int(budget), float(interval), int(retries), name
        self.headers = {"User-Agent": UA, "Accept": "application/json, text/csv, */*"}
        self.headers.update(headers or {})
        self.intervals = dict(intervals or {})
        self.used, self.failures, self.seconds = 0, 0, 0.0
        self._last: dict[str, float] = {}
        self.by_host: dict[str, int] = {}
        self.secs_by_host: dict[str, float] = {}

    def _gap(self, host: str) -> float:
        for k, v in self.intervals.items():
            if host.endswith(k):
                return float(v)
        return self.interval

    def _request(self, url: str, params: dict | None = None, headers: dict | None = None,
                 ok_status: tuple = (200,)) -> requests.Response | None:
        host = urlparse(url).netloc
        for attempt in range(self.retries):
            if self.used >= self.budget:
                raise BudgetExhausted(f"{self.name} budget of {self.budget} calls spent")
            wait = self._last.get(host, 0.0) + self._gap(host) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            t0 = time.monotonic()
            self.used += 1
            self.by_host[host] = self.by_host.get(host, 0) + 1
            try:
                r = requests.get(url, params=params, headers={**self.headers, **(headers or {})}, timeout=TIMEOUT)
            except requests.RequestException as exc:
                dt = time.monotonic() - t0
                self.seconds += dt
                self.secs_by_host[host] = self.secs_by_host.get(host, 0.0) + dt
                self._last[host] = time.monotonic()
                logger.warning("%s %s %s: %s (attempt %d)", self.name, url, params or "", exc, attempt + 1)
                time.sleep(5 * (attempt + 1))
                continue
            dt = time.monotonic() - t0
            self.seconds += dt
            self.secs_by_host[host] = self.secs_by_host.get(host, 0.0) + dt
            # Pace from the end of the answer: a slow Savant query (8 s) is followed by a real pause.
            self._last[host] = time.monotonic()
            if r.status_code == 429 or r.status_code >= 500:
                try:
                    back = int(r.headers.get("Retry-After") or 0)
                except ValueError:
                    back = 0
                back = back or 10 * (attempt + 1)
                logger.warning("%s %s answered %s; sleeping %ds", self.name, url, r.status_code, back)
                time.sleep(min(back, 120))
                continue
            if r.status_code not in ok_status:
                logger.warning("%s %s %s answered %s", self.name, url, params or "", r.status_code)
                self.failures += 1
                return None
            return r
        self.failures += 1
        return None

    def get(self, url: str, params: dict | None = None):
        """Parsed JSON (dict or list), or None."""
        r = self._request(url, params)
        if r is None:
            return None
        try:
            return r.json()
        except ValueError:
            logger.warning("%s %s %s answered non-JSON", self.name, url, params or "")
            self.failures += 1
            return None

    def get_text(self, url: str, params: dict | None = None) -> str | None:
        """Body as text (UTF-8, a leading byte-order mark dropped), or None."""
        r = self._request(url, params)
        if r is None:
            return None
        return r.content.decode("utf-8-sig", errors="replace")

    def get_bytes(self, url: str, params: dict | None = None) -> bytes | None:
        r = self._request(url, params)
        return None if r is None else r.content

    def report(self) -> str:
        hosts = ", ".join(f"{k} {v} ({self.secs_by_host.get(k, 0):.0f} s)" for k, v in sorted(self.by_host.items()))
        return f"{self.used} calls ({hosts}); {self.failures} failures; {self.seconds:.0f} s on the network"
