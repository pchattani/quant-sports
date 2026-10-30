"""
A polite, cached, switchable HTTP client for sources whose terms are unclear (the user's rule of 30 Oct 2026: "For
all with unclear terms assume I am ok with it and add. Then just add it in disclaimers. If we need to take it down,
we will.").

Every such source gets one module that builds a `Source` here, one environment switch and one private raw cache:

    SOURCE_<NAME>_ENABLED=0   -> `enabled()` is False: no fetch, no parse, and the builders drop every payload
                                 derived from the source, so the sites render as if it never existed.

Politeness is enforced here, never by callers:
- robots.txt is read (cached a day) and obeyed for `User-agent: *` (wildcards, `$` anchors, longest match wins), and
  its Crawl-Delay is honoured when it is longer than the source's own interval;
- a real User-Agent naming the project;
- one request at a time across every process on this PC for that source (a lock directory) and at least `interval`
  seconds between requests (a shared timestamp file);
- back-off on 403 / 429 / 5xx (Retry-After honoured) and `Blocked` after repeated refusals, so a job stops;
- every response cached (gzip, under data/, which git ignores) so nothing is fetched twice;
- local fetch only: `fetch_allowed()` is False on CI.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
USER_AGENT = "TheQuantSports/1.0 (non-commercial sports analytics; +https://pchattani.github.io/the-quant-sports)"


class Blocked(RuntimeError):
    """The site refused us repeatedly (403/429/5xx): stop the job."""


class Disallowed(RuntimeError):
    """robots.txt disallows this path."""


class BudgetExhausted(RuntimeError):
    pass


def flag_on(name: str, default: bool = True) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "")


def on_ci() -> bool:
    return bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


# ── robots ─────────────────────────────────────────────────────────────────────────────────────────────────

def parse_robots(text: str, agent: str = "*") -> tuple[list[tuple[str, bool]], float | None]:
    """(rules, crawl_delay) of the group that applies to `agent` (here '*')."""
    groups: list[tuple[list[str], list[tuple[str, bool]], float | None]] = []
    agents: list[str] = []
    rules: list[tuple[str, bool]] = []
    delay: float | None = None
    last_agent = False
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            if not last_agent and (agents or rules or delay is not None):
                groups.append((agents, rules, delay))
                agents, rules, delay = [], [], None
            agents.append(v.lower())
            last_agent = True
            continue
        last_agent = False
        if k in ("allow", "disallow"):
            if v:
                rules.append((v if v.startswith(("/", "*")) else "/" + v, k == "allow"))
        elif k == "crawl-delay":
            try:
                delay = float(v)
            except ValueError:
                pass
    if agents or rules or delay is not None:
        groups.append((agents, rules, delay))
    out: list[tuple[str, bool]] = []
    cd: float | None = None
    for ags, rs, d in groups:
        if agent.lower() in ags:
            out.extend(rs)
            cd = d if d is not None else cd
    return out, cd


def _pat_re(p: str) -> re.Pattern:
    anchored = p.endswith("$")
    body = p[:-1] if anchored else p
    return re.compile("^" + "".join(".*" if ch == "*" else re.escape(ch) for ch in body) + ("$" if anchored else ""))


def robots_allows(rules: list[tuple[str, bool]], path: str) -> bool:
    """Longest matching rule wins; ties go to Allow. No match -> allowed."""
    best_len, best_allow = -1, True
    for pat, allow in rules:
        if _pat_re(pat).match(path):
            if len(pat) > best_len or (len(pat) == best_len and allow):
                best_len, best_allow = len(pat), allow
    return best_allow


# ── source ─────────────────────────────────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_s(rec: dict) -> float:
    try:
        t = datetime.strptime(rec["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except (KeyError, ValueError, TypeError):
        return 1e12


@dataclass
class Source:
    """One unclear-terms source: its base URL, switch, raw cache and pacing."""
    name: str                      # short id, e.g. "umpscorecards"
    base: str                      # "https://umpscorecards.com"
    flag: str                      # "SOURCE_UMPSCORECARDS_ENABLED"
    raw_dir: Path                  # private cache root (under data/, git-ignored)
    interval: float = 3.0
    credit: str = ""
    robots: bool = True            # False only for hosts with no robots.txt (e.g. an archive's API)
    timeout: float = 60.0

    def enabled(self) -> bool:
        return flag_on(self.flag)

    def fetch_allowed(self) -> bool:
        return self.enabled() and not on_ci()

    # cache
    def cache_path(self, path: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9.,=-]+", "_", path.strip("/"))[:140] or "index"
        h = hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]
        return self.raw_dir / "raw" / f"{safe}.{h}.json.gz"

    def read_cached(self, path: str) -> dict | None:
        cp = self.cache_path(path)
        if not cp.exists():
            return None
        try:
            with gzip.open(cp, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError, EOFError):
            return None

    def write_cached(self, path: str, rec: dict) -> None:
        cp = self.cache_path(path)
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_name(cp.name + f".{os.getpid()}.tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
            json.dump(rec, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, cp)

    def client(self, budget: int | None = None, offline: bool = False) -> "Client":
        return Client(self, budget=budget, offline=offline or not self.fetch_allowed())


@dataclass
class Client:
    src: Source
    budget: int | None = None
    offline: bool = False
    used: int = 0
    failures: int = 0
    _rules: Any = field(default=None, repr=False)
    _delay: float | None = field(default=None, repr=False)
    _session: Any = field(default=None, repr=False)

    def _robots(self) -> list[tuple[str, bool]]:
        if not self.src.robots:
            return []
        if self._rules is None:
            rec = self.src.read_cached("/robots.txt")
            if (rec is None or _age_s(rec) > 86400) and not self.offline:
                rec = self._fetch("/robots.txt", check=False) or rec
            status = (rec or {}).get("status")
            text = (rec or {}).get("text") or ""
            if status in (404, 410) or (status == 200 and "<html" in text[:500].lower()):
                text = ""                                    # no robots.txt (or an app page): no rules
            elif status != 200:
                raise Blocked(f"{self.src.name}: robots.txt unavailable; refusing to crawl blind")
            self._rules, self._delay = parse_robots(text)
        return self._rules

    def allowed(self, path: str) -> bool:
        return robots_allows(self._robots(), path)

    def get(self, path: str, max_age: float | None = None) -> str | None:
        """Text of `path` (site-relative). Cached responses are returned without a request unless older than
        `max_age` seconds. None for a 404, a disallowed path offline, or the switch off."""
        if not self.src.enabled():
            return None
        rec = self.src.read_cached(path)
        if rec is not None and (max_age is None or _age_s(rec) <= max_age):
            return rec.get("text") if rec.get("status") == 200 else None
        if self.offline:
            return rec.get("text") if rec and rec.get("status") == 200 else None
        if not self.allowed(path):
            raise Disallowed(f"{self.src.name}: robots.txt disallows {path}")
        new = self._fetch(path)
        if new is None:
            return rec.get("text") if rec and rec.get("status") == 200 else None
        return new.get("text") if new.get("status") == 200 else None

    def _fetch(self, path: str, check: bool = True) -> dict | None:
        import requests
        if self.budget is not None and self.used >= self.budget:
            raise BudgetExhausted(f"{self.src.name} budget {self.budget} used")
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/csv,*/*;q=0.8"})
        interval = max(self.src.interval, self._delay or 0.0)
        delay = 60.0
        for _ in range(4):
            with _Pace(self.src.raw_dir, interval):
                self.used += 1
                try:
                    r = self._session.get(self.src.base + path, timeout=self.src.timeout)
                    status, text, ra = r.status_code, r.text, r.headers.get("Retry-After")
                except requests.RequestException as e:
                    status, text, ra = -1, "", None
                    logger.warning("%s %s: %s", self.src.name, path, e)
            if status == 200 or status in (404, 410):
                self.failures = 0
                rec = {"path": path, "status": status, "fetched_at": _now(), "text": text if status == 200 else ""}
                self.src.write_cached(path, rec)
                return rec
            self.failures += 1
            if self.failures >= 5:
                raise Blocked(f"{self.src.name} refused {self.failures} times in a row (last {status} on {path})")
            wait = delay
            if ra and str(ra).isdigit():
                wait = max(wait, float(ra))
            if status == 403:
                wait = max(wait, 300.0)
            logger.warning("%s %s -> %s; backing off %.0f s", self.src.name, path, status, wait)
            time.sleep(wait)
            delay *= 2
        return None


class _Pace:
    """mkdir lock + last-request timestamp per source, shared by every process on the PC."""

    def __init__(self, root: Path, interval: float):
        self.interval = interval
        root.mkdir(parents=True, exist_ok=True)
        self.lock = root / ".fetch_lock"
        self.stamp = root / ".last_fetch"

    def _last(self) -> float:
        try:
            return float(self.stamp.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def __enter__(self):
        t0 = time.time()
        while True:
            wait = self._last() + self.interval - time.time()
            if wait > 0:
                time.sleep(wait + random.uniform(0, 0.5))
                continue
            try:
                self.lock.mkdir()
            except FileExistsError:
                try:
                    if time.time() - self.lock.stat().st_mtime > 300:
                        self.lock.rmdir()
                        continue
                except OSError:
                    pass
                if time.time() - t0 > 1800:
                    raise Blocked("fetch lock held for 30 minutes")
                time.sleep(random.uniform(0.2, 0.8))
                continue
            if self._last() + self.interval > time.time():
                self.lock.rmdir()
                continue
            return self

    def __exit__(self, *exc):
        try:
            self.stamp.write_text(f"{time.time():.3f}")
        finally:
            try:
                self.lock.rmdir()
            except OSError:
                pass
        return False
