#!/usr/bin/env python
"""
Fetch ESPN rugby for The Quant Scrum and write the season stores (oddsmarkets/rugby/store.py).

    uv run python scripts/scrum_fetch.py --backfill                 # every competition, every year; resumable
    uv run python scripts/scrum_fetch.py --refresh-current          # hourly: this year's and next year's scoreboards,
                                                                     # summaries of newly finished matches
    uv run python scripts/scrum_fetch.py --stores-only              # rebuild the stores from the raw cache (no network)

Every answer is cached gzipped under data/rugby/raw, so a killed backfill resumes where it stopped. Pacing: one call
every --interval seconds (2 s by default) with back-off on 429/403/5xx; --budget caps network calls per run.
A lock file (data/rugby/fetch.lock, broken after 3 hours) keeps two runs apart.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.rugby import config, store  # noqa: E402
from oddsmarkets.rugby.sources import espn  # noqa: E402

log = logging.getLogger("scrum_fetch")
# a match listed by two competitions keeps the more specific one (a Lions test is also an "International Test")
PRIORITY = {"rwc": 0, "wrwc": 0, "six": 1, "trc": 1, "nc": 1, "tri20": 1, "lions": 2, "oly7m": 1, "oly7w": 1, "test": 9}
LOCK_MAX_AGE_S = 3 * 3600


def _lock(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime < LOCK_MAX_AGE_S:
        return False
    path.write_text(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}", encoding="utf-8")
    return True


_HAVE: dict = {}


def stored_with_summary(scope: str, year: int) -> set:
    """Match ids whose summary is already folded into the store (a runner without the raw summaries need not refetch)."""
    k = (scope, year)
    if k not in _HAVE:
        st = store.load(scope, year) or {}
        _HAVE[k] = {m["id"] for m in st.get("matches") or [] if m.get("lh") or m.get("la") or m.get("events")}
    return _HAVE[k]


def fetch(c: espn.Client, years_by_slug: dict[str, list[int]], refresh_years: set[int], summaries: bool) -> dict:
    stats = {"scoreboards": 0, "events": 0, "summaries_new": 0, "summaries_missing": 0}
    for slug, yrs in years_by_slug.items():
        for y in yrs:
            try:
                d = espn.scoreboard(c, slug, y, refresh=y in refresh_years)
            except espn.BudgetExhausted:
                log.warning("budget spent at %s %s", slug, y)
                return stats
            stats["scoreboards"] += 1
            rows = espn.parse_scoreboard(d, slug)
            stats["events"] += len(rows)
            if rows:
                log.info("%s %s: %d events", config.comp(slug)["key"], y, len(rows))
            if not summaries:
                continue
            have = stored_with_summary(config.comp(slug)["scope"], y)
            for r in rows:
                if r["status"] != "final" or espn.summary_cached(r["id"]) or r["id"] in have:
                    continue
                try:
                    s = espn.summary(c, slug, r["id"])
                except espn.BudgetExhausted:
                    log.warning("budget spent in summaries (%s %s)", slug, y)
                    return stats
                if s is None:
                    stats["summaries_missing"] += 1
                else:
                    stats["summaries_new"] += 1
    return stats


def build_stores(years_by_slug: dict[str, list[int]], only_years: set[int] | None = None) -> dict:
    """Rebuild the scope-year stores from the raw cache (no network). With only_years (the hourly refresh), only those
    years' stores are written, and anything the raw cache lacks (a summary fetched on another machine, a match the
    scoreboard no longer lists) is kept from the existing store, so a runner with a partial raw cache never loses data."""
    import gzip
    import json
    by_id: dict[str, dict] = {}
    raw = espn.raw_root()
    for slug in years_by_slug:
        d = raw / "sb" / slug
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json.gz")):
            try:
                with gzip.open(p, "rt", encoding="utf-8") as fh:
                    sb = json.load(fh)
            except (OSError, ValueError):
                continue
            for r in espn.parse_scoreboard(sb, slug):
                cur = by_id.get(r["id"])
                if cur is None or PRIORITY.get(r["comp"], 5) < PRIORITY.get(cur["comp"], 5) or \
                        (r["status"] == "final" and cur["status"] != "final"):
                    if cur is not None and PRIORITY.get(cur["comp"], 5) < PRIORITY.get(r["comp"], 5):
                        r["comp"], r["slug"] = cur["comp"], cur["slug"]
                    by_id[r["id"]] = r
    out: dict[tuple, dict] = {}
    n_lineups = 0
    for mid, r in by_id.items():
        scope = config.comp(r["slug"])["scope"]
        y = int(str(r.get("date") or "0000")[:4] or 0)
        if not y or (only_years is not None and y not in only_years):
            continue
        b = out.setdefault((scope, y), {"matches": [], "athletes": {}})
        if r["status"] == "final":
            p = raw / "summary" / mid[-2:] / f"{mid}.json.gz"
            if p.exists():
                try:
                    with gzip.open(p, "rt", encoding="utf-8") as fh:
                        sm = espn.parse_summary(json.load(fh))
                except (OSError, ValueError):
                    sm = None
                if sm:
                    if sm["lineups"]["h"] or sm["lineups"]["a"]:
                        r["lh"], r["la"] = sm["lineups"]["h"], sm["lineups"]["a"]
                        n_lineups += 1
                    if sm.get("events"):
                        r["events"] = sm["events"]
                    if sm.get("attendance"):
                        r["attendance"] = sm["attendance"]
                    if sm.get("venue") and not r["venue"].get("country"):
                        r["venue"]["country"] = sm["venue"].get("country") or ""
                    for aid, a in sm["athletes"].items():
                        cur = b["athletes"].get(aid) or {}
                        b["athletes"][aid] = {**cur, **{k: v for k, v in a.items() if v}}
        b["matches"].append(r)
    if only_years is not None:
        for (scope, y), b in out.items():
            old = store.load(scope, y) or {}
            have = {m["id"]: m for m in b["matches"]}
            for om in old.get("matches") or []:
                nm = have.get(om["id"])
                if nm is None:
                    b["matches"].append(om)
                    continue
                for k in ("lh", "la", "events", "attendance"):
                    if k in om and k not in nm:
                        nm[k] = om[k]
            for aid, a in (old.get("athletes") or {}).items():
                b["athletes"][aid] = {**a, **(b["athletes"].get(aid) or {})}
    for (scope, y), b in out.items():
        b["matches"].sort(key=lambda m: (m.get("date") or "", m["id"]))
        store.save(scope, y, b["matches"], b["athletes"])
    return {"stores": len(out), "matches": len(by_id), "with_lineups": n_lineups}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--refresh-current", action="store_true")
    ap.add_argument("--stores-only", action="store_true")
    ap.add_argument("--comps", default="", help="comma list of competition keys or slugs (default: all)")
    ap.add_argument("--from-year", type=int, default=0)
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[scrum_fetch] %(asctime)s %(levelname)s %(message)s")
    this = datetime.now(timezone.utc).year
    wanted = {x.strip() for x in a.comps.split(",") if x.strip()}
    slugs = [s for s, v in config.COMPS.items() if not wanted or s in wanted or v["key"] in wanted]
    if a.backfill or a.stores_only:
        ybs = {s: list(range(max(config.COMPS[s]["first"], a.from_year or 0), this + 2)) for s in slugs}
    else:
        ybs = {s: [y for y in (this, this + 1) if y >= config.COMPS[s]["first"]] for s in slugs}
    lock = store.paths()["raw"].parent / "fetch.lock"
    if not a.stores_only:
        if not _lock(lock):
            log.warning("another scrum_fetch holds %s; exiting", lock)
            return 0
        try:
            c = espn.Client(budget=a.budget, interval=a.interval)
            st = fetch(c, ybs, refresh_years={this, this + 1}, summaries=True)
            log.info("fetch: %s; network calls %d, cache hits %d, failures %d, throttled %d", st, c.used, c.hits,
                     c.failures, c.throttled)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass
    all_ybs = {s: [] for s in config.COMPS}
    only = None if (a.backfill or a.stores_only) else {this, this + 1}
    res = build_stores(all_ybs, only_years=only)
    log.info("stores: %s", res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
