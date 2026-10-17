"""
One paced HTTP client for every tennis source (tennis-data, ESPN, WTA, Match Charting Project).

`Client.get` / `Client.get_bytes` space requests (`interval` seconds apart, 0.5 = 2 a second), retry
with back-off on network errors, 429 and 5xx (honouring Retry-After), count calls against a `budget`
and never raise on a bad answer: they log and return None. Running out of budget raises
`BudgetExhausted`, so a backfill stops cleanly and resumes next time.

`used`, `failures` and `seconds` (time spent waiting on the network) size the backfills; the
per-host counters in `by_host` let one run report calls per source.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

UA = "The Quant Ace (pchattani.github.io/the-quant-ace; tennis analytics, non-commercial)"
TIMEOUT = 60


class BudgetExhausted(RuntimeError):
    pass


class Client:
    def __init__(self, budget: int = 2000, interval: float = 0.5, retries: int = 4, name: str = "tennis",
                 headers: dict | None = None):
        self.budget, self.interval, self.retries, self.name = int(budget), float(interval), int(retries), name
        self.headers = {"User-Agent": UA, "Accept": "application/json, */*"}
        self.headers.update(headers or {})
        self.used, self.failures, self.seconds, self._last = 0, 0, 0.0, 0.0
        self.by_host: dict[str, int] = {}

    def _request(self, url: str, params: dict | None = None, headers: dict | None = None,
                 ok_status: tuple = (200,)) -> requests.Response | None:
        host = urlparse(url).netloc
        for attempt in range(self.retries):
            if self.used >= self.budget:
                raise BudgetExhausted(f"{self.name} budget of {self.budget} calls spent")
            wait = self._last + self.interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = t0 = time.monotonic()
            self.used += 1
            self.by_host[host] = self.by_host.get(host, 0) + 1
            try:
                r = requests.get(url, params=params, headers={**self.headers, **(headers or {})}, timeout=TIMEOUT)
            except requests.RequestException as exc:
                self.seconds += time.monotonic() - t0
                logger.warning("%s %s %s: %s (attempt %d)", self.name, url, params or "", exc, attempt + 1)
                time.sleep(3 * (attempt + 1))
                continue
            self.seconds += time.monotonic() - t0
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
        r = self._request(url, params)
        return None if r is None else r.text

    def get_bytes(self, url: str, if_modified_since: str | None = None) -> tuple[bytes | None, dict]:
        """(content, headers). With `if_modified_since`, a 304 answers (None, headers) with headers["status"] = 304."""
        hdr = {"If-Modified-Since": if_modified_since} if if_modified_since else None
        r = self._request(url, headers=hdr, ok_status=(200, 304))
        if r is None:
            return None, {"status": None}
        h = {k.lower(): v for k, v in r.headers.items()}
        h["status"] = r.status_code
        if r.status_code == 304:
            return None, h
        return r.content, h

    def report(self) -> str:
        hosts = ", ".join(f"{k} {v}" for k, v in sorted(self.by_host.items()))
        return f"{self.used} calls ({hosts}); {self.failures} failures; {self.seconds:.0f} s on the network"
