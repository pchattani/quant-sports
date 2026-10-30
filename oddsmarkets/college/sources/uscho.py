"""
USCHO polls (uscho.com) for The Quant Campus college hockey: the Division I men's and women's polls, every week of
the current season and the final poll of each past season. Everything from USCHO sits behind this module and one
switch, USCHO_ENABLED=0 (the hockey builder then falls back to the current poll ESPN carries).

Approved by the site owner on 30 Oct 2026 under the rule for sources with unclear terms (credited in the
disclaimer and DATA_LICENSES.md; taken down on request). Politeness as for College Hockey News: robots.txt obeyed
(USCHO's allows everything, checked 30 Oct 2026), a User-Agent naming the project, one request at a time at least
3 s apart across processes, back-off on refusals, every page cached (private), never fetched on CI.

The poll pages embed their data as JSON (the page's `data-page` attribute): props.content.data = rows
{rnk, shortname, pts, first_pv, record, prev_rnk, PollDate, season}, props.content.pdate = every poll date
(entries "--- 2026 - 2027 ---" mark the season breaks); /rankings/d-i-<mens|womens>-poll/<YYYY-MM-DD> is one week.
"""
from __future__ import annotations

import gzip
import html as _html
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import chn

logger = logging.getLogger(__name__)

BASE = "https://www.uscho.com"
PATH = {"mch": "/rankings/d-i-mens-poll/", "wch": "/rankings/d-i-womens-poll/"}
CREDIT = "USCHO (uscho.com)"


def enabled() -> bool:
    return os.environ.get("USCHO_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")


def fetch_allowed() -> bool:
    return enabled() and not os.environ.get("CI") and not os.environ.get("GITHUB_ACTIONS")


def raw_root() -> Path:
    return Path(os.environ.get("USCHO_RAW") or (chn.ROOT / "data" / "college" / "uscho"))


def _cache(path: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9.-]+", "_", path.strip("/")) or "index"
    return raw_root() / "raw" / f"{safe}.json.gz"


def _read(path: str) -> dict | None:
    p = _cache(path)
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


class _Pace(chn._GlobalPace):
    def __init__(self, interval: float):
        super().__init__(interval)
        self.dir = raw_root()
        self.lock = self.dir / ".fetch_lock"
        self.stamp = self.dir / ".last_fetch"


_rules = None


def _allowed(path: str) -> bool:
    global _rules
    if _rules is None:
        rec = _read("/robots.txt")
        if rec is None and fetch_allowed():
            r = requests.get(BASE + "/robots.txt", headers={"User-Agent": chn.USER_AGENT}, timeout=30)
            rec = {"status": r.status_code, "html": r.text if r.status_code == 200 else "", "fetched_at": chn._now()}
            _write("/robots.txt", rec)
        _rules = chn.parse_robots((rec or {}).get("html") or "")
    return chn.robots_allows(_rules, path)


def _write(path: str, rec: dict) -> None:
    p = _cache(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rec, fh, separators=(",", ":"))
    os.replace(tmp, p)


def get(path: str, max_age: float | None = None) -> str | None:
    """A page's HTML from the cache, or fetched politely (None when not allowed / unavailable)."""
    if not enabled():
        return None
    rec = _read(path)
    if rec is not None and (max_age is None or chn._age_s(rec) <= max_age):
        return rec.get("html") if rec.get("status") == 200 else None
    if not fetch_allowed() or not _allowed(path):
        return rec.get("html") if rec and rec.get("status") == 200 else None
    for attempt in range(3):
        with _Pace(chn.INTERVAL):
            try:
                r = requests.get(BASE + path, headers={"User-Agent": chn.USER_AGENT}, timeout=40)
                status, text = r.status_code, r.text
            except requests.RequestException:
                status, text = -1, ""
        if status in (200, 404):
            new = {"path": path, "status": status, "fetched_at": chn._now(), "html": text if status == 200 else ""}
            _write(path, new)
            return text if status == 200 else None
        time.sleep(60 * (attempt + 1))
    return rec.get("html") if rec and rec.get("status") == 200 else None


def parse_poll(html_text: str) -> dict | None:
    m = re.search(r'data-page="([^"]+)"', html_text or "")
    if not m:
        return None
    try:
        c = json.loads(_html.unescape(m.group(1)))["props"]["content"]
    except (ValueError, KeyError, TypeError):
        return None
    rows = [{"rank": r.get("rnk"), "name": r.get("shortname"), "points": r.get("pts"), "first": r.get("first_pv"),
             "record": r.get("record"), "prev": r.get("prev_rnk"), "date": r.get("PollDate"), "season": r.get("season")}
            for r in c.get("data") or []]
    dates, pending = [], []
    for d in c.get("pdate") or []:                     # newest first; a "--- 2026 - 2027 ---" marker closes its season
        txt = str(d.get("text") or "")
        if txt.startswith("---"):
            m2 = re.search(r"(\d{4})\s*-\s*(\d{4})", txt)
            for x in pending:
                x["season"] = int(m2.group(2)) if m2 else None
            dates += pending
            pending = []
            continue
        pending.append({"date": d.get("value"), "season": None})
    dates += pending
    return {"title": c.get("title"), "rows": rows, "dates": dates, "others": c.get("other")}


def poll_dates(level: str) -> list[dict]:
    p = parse_poll(get(PATH[level], max_age=6 * 3600) or "")
    return (p or {}).get("dates") or []


def polls_for_season(level: str, season: int, current: bool, budget: int = 40) -> dict[str, list]:
    """{poll date: rows} for a season: every week of the current season; the final poll of a past one."""
    dates = [d for d in poll_dates(level) if d.get("season") == season]
    if not current:
        dates = dates[:1]                                      # newest first: the final poll
    out = {}
    for d in dates[:budget]:
        h = get(f"{PATH[level]}{d['date']}", max_age=None if not current else 7 * 86400)
        p = parse_poll(h or "")
        if p and p["rows"]:
            out[d["date"]] = p["rows"]
    return out


def cached(path: str) -> str | None:
    rec = _read(path)
    return rec.get("html") if rec and rec.get("status") == 200 else None


def poll_dates_cached(level: str) -> list[dict]:
    p = parse_poll(cached(PATH[level]) or "")
    return (p or {}).get("dates") or []
