"""
One paced HTTP client for every Quant Rink source (NHL api-web and stats REST, NHL EDGE, MoneyPuck shot files,
ESPN site and core APIs), mirroring nfl/sources/_client.py.

`get` / `get_text` / `get_bytes` space requests per host (`interval`, or `intervals` by host suffix) and, when
`min_gap` is set, across all hosts (so one process never exceeds 1 / min_gap requests a second in total); retry
with back-off on network errors, 429 and 5xx (honouring Retry-After); count calls against a `budget`; and never
raise on a bad answer: they log and return None. A 404 is an answer, not a failure (EDGE has no page for a
player without tracked games; ESPN has no odds for some events): it returns None and counts in `missing`.
Running out of budget raises `BudgetExhausted`, so a backfill stops cleanly and resumes next time.

NHL "now" / "current" URLs answer 307 to a dated form; callers use dated URLs, and redirects are followed in
any case. `download` streams a body to a file (MoneyPuck season shot files are ~20 MB zipped).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from oddsmarkets.common.mojibake import repair as _repair_mojibake

logger = logging.getLogger(__name__)

UA = "The Quant Rink (pchattani.github.io/the-quant-rink; NHL analytics, non-commercial)"
TIMEOUT = 120


class BudgetExhausted(RuntimeError):
    pass


class Client:
    def __init__(self, budget: int = 2000, interval: float = 0.25, retries: int = 4, name: str = "rink",
                 headers: dict | None = None, intervals: dict[str, float] | None = None, min_gap: float = 0.0):
        self.budget, self.interval, self.retries, self.name = int(budget), float(interval), int(retries), name
        self.min_gap = float(min_gap)
        self.headers = {"User-Agent": UA, "Accept": "application/json, */*"}
        self.headers.update(headers or {})
        self.intervals = dict(intervals or {})
        self.used, self.failures, self.missing, self.seconds, self.bytes = 0, 0, 0, 0.0, 0
        self._last: dict[str, float] = {}
        self._last_any = 0.0
        self.by_host: dict[str, int] = {}
        self.secs_by_host: dict[str, float] = {}
        self.session = requests.Session()

    def _gap(self, host: str) -> float:
        for k, v in self.intervals.items():
            if host.endswith(k):
                return float(v)
        return self.interval

    def _request(self, url: str, params: dict | None = None, method: str = "GET", stream: bool = False,
                 ok_status: tuple = (200,)) -> requests.Response | None:
        host = urlparse(url).netloc
        for attempt in range(self.retries):
            if self.used >= self.budget:
                raise BudgetExhausted(f"{self.name} budget of {self.budget} calls spent")
            now = time.monotonic()
            wait = max(self._last.get(host, 0.0) + self._gap(host) - now, self._last_any + self.min_gap - now)
            if wait > 0:
                time.sleep(wait)
            t0 = time.monotonic()
            self._last_any = t0
            self.used += 1
            self.by_host[host] = self.by_host.get(host, 0) + 1
            try:
                r = self.session.request(method, url, params=params, headers=self.headers, timeout=TIMEOUT,
                                         stream=stream, allow_redirects=True)
            except requests.RequestException as exc:
                self._done(host, t0)
                logger.warning("%s %s %s %s: %s (attempt %d)", self.name, method, url, params or "", exc, attempt + 1)
                time.sleep(5 * (attempt + 1))
                continue
            self._done(host, t0)
            if r.status_code == 429 or r.status_code >= 500:
                try:
                    back = int(r.headers.get("Retry-After") or 0)
                except ValueError:
                    back = 0
                back = back or 10 * (attempt + 1)
                logger.warning("%s %s answered %s; sleeping %ds", self.name, url, r.status_code, back)
                r.close()
                time.sleep(min(back, 120))
                continue
            if r.status_code == 404:
                self.missing += 1
                r.close()
                return None
            if r.status_code not in ok_status:
                logger.warning("%s %s %s %s answered %s", self.name, method, url, params or "", r.status_code)
                self.failures += 1
                r.close()
                return None
            return r
        self.failures += 1
        return None

    def _done(self, host: str, t0: float) -> None:
        dt = time.monotonic() - t0
        self.seconds += dt
        self.secs_by_host[host] = self.secs_by_host.get(host, 0.0) + dt
        self._last[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None):
        """Parsed JSON (dict or list), or None."""
        r = self._request(url, params)
        if r is None:
            return None
        self.bytes += len(r.content)
        try:
            # the NHL stats API serves double-encoded names itself ("MontrÃ©al" in 2025-26 shiftcharts, checked
            # 2026-10-25 against the raw bytes): the safe round trip repairs them and leaves correct text alone
            return _repair_mojibake(r.json())[0]
        except ValueError:
            logger.warning("%s %s %s answered non-JSON", self.name, url, params or "")
            self.failures += 1
            return None

    def get_text(self, url: str, params: dict | None = None) -> str | None:
        r = self._request(url, params)
        if r is None:
            return None
        self.bytes += len(r.content)
        return r.content.decode("utf-8-sig", errors="replace")

    def get_bytes(self, url: str, params: dict | None = None) -> bytes | None:
        r = self._request(url, params)
        if r is None:
            return None
        self.bytes += len(r.content)
        return r.content

    def head(self, url: str) -> dict | None:
        """Final headers after redirects (lower-cased keys), or None."""
        r = self._request(url, method="HEAD")
        if r is None:
            return None
        return {k.lower(): v for k, v in r.headers.items()}

    def download(self, url: str, dest: Path, chunk: int = 1 << 20) -> dict | None:
        """Stream `url` into `dest` (via a .part file). Returns the final headers, or None."""
        r = self._request(url, stream=True)
        if r is None:
            return None
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        n = 0
        t0 = time.monotonic()
        try:
            with open(part, "wb") as fh:
                for block in r.iter_content(chunk):
                    if block:
                        fh.write(block)
                        n += len(block)
        except requests.RequestException as exc:
            logger.warning("%s download %s broke after %d bytes: %s", self.name, url, n, exc)
            self.failures += 1
            part.unlink(missing_ok=True)
            return None
        finally:
            r.close()
            host = urlparse(url).netloc
            self.secs_by_host[host] = self.secs_by_host.get(host, 0.0) + (time.monotonic() - t0)
            self.seconds += time.monotonic() - t0
        expect = r.headers.get("Content-Length")
        if expect and expect.isdigit() and int(expect) != n:
            logger.warning("%s download %s: %d bytes, expected %s", self.name, url, n, expect)
            self.failures += 1
            part.unlink(missing_ok=True)
            return None
        part.replace(dest)
        self.bytes += n
        return {**{k.lower(): v for k, v in r.headers.items()}, "bytes": n}

    def report(self) -> str:
        hosts = ", ".join(f"{k} {v} ({self.secs_by_host.get(k, 0):.0f} s)" for k, v in sorted(self.by_host.items()))
        return (f"{self.used} calls ({hosts}); {self.failures} failures; {self.missing} not found; "
                f"{self.bytes / 1e6:.1f} MB; {self.seconds:.0f} s on the network")
