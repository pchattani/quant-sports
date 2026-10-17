"""
The MLB Stats API inputs of the valuation, transactions and fantasy layers, cached under <cache>/statsapi/ (git-ignored;
never deployed): transactions by month, official season stat lines and stat lines by date range (weeks).

Source and terms: statsapi.mlb.com, already the site's source of schedules, rosters and injured lists. Its notice
(gdx.mlb.com/components/copyright.txt) reserves the data to MLB Advanced Media and permits individual, non-commercial,
non-bulk use; the site is non-commercial, the calls are paced (0.4 s apart, an identifying User-Agent), a closed month or
a past season is fetched once and kept, and the pages show only facts and our own numbers derived from them (dates,
clubs, players, the kind of move, counting stats in our tables), never MLBAM's text or feeds.

    transactions   <cache>/statsapi/tx/<level>/<YYYY-MM>.json   {"fetched_at", "rows": [statsapi.compact_tx]}
                   a month is final once fetched 10+ days after it ended; the current month is refetched when older
                   than `max_age_h` hours (3 by default)
    season lines   <cache>/statsapi/lines/<level>/season_<group>_<S>.json  {"fetched_at", "rows": {pid: line}}
                   final once fetched after 15 November of the season
    range lines    <cache>/statsapi/lines/<level>/range_<group>_<start>_<end>.json (weeks for the fantasy backtests)
    people         <cache>/statsapi/people.json   {pid: person record} for players the crosswalk lacks (trade pieces)

Offline (client None: `--no-statsapi`, or BULLPEN_OFFLINE set, as the tests do): only what is cached is read.

Backfill (one time, about 300 calls):
    python -m oddsmarkets.baseball.analytics.mlbapi --from 2015 --to 2026
"""
from __future__ import annotations

import argparse
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from oddsmarkets.baseball import analytics as an

log = logging.getLogger(__name__)
FINAL_AFTER_DAYS = 10
SEASON_FINAL = (11, 15)


def client(budget: int = 600):
    """A paced Stats API client, or None when BULLPEN_OFFLINE is set (the tests: cache only, no network)."""
    if os.environ.get("BULLPEN_OFFLINE"):
        return None
    from oddsmarkets.baseball.sources._client import Client
    return Client(budget=budget, interval=0.4, name="statsapi")


def root() -> Path:
    return an.cache_root() / "statsapi"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_h(at: str | None) -> float:
    if not at:
        return 1e9
    try:
        t = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return 1e9
    return (_now() - t).total_seconds() / 3600.0


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def months(lo: date, hi: date) -> list[tuple[int, int]]:
    out = []
    y, m = lo.year, lo.month
    while (y, m) <= (hi.year, hi.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ── transactions ────────────────────────────────────────────────────────────

def tx_path(level: str, y: int, m: int) -> Path:
    return root() / "tx" / level / f"{y:04d}-{m:02d}.json"


def tx_month(level: str, y: int, m: int, c=None, max_age_h: float = 3.0, today: date | None = None) -> list[dict] | None:
    """One month's transactions: the cache, refreshed through `c` when it is missing, or not final and stale."""
    p = tx_path(level, y, m)
    got = an.read_json(p)
    today = today or _now().date()
    end = _month_end(y, m)
    if got is not None:
        fetched = str(got.get("fetched_at") or "")[:10]
        final = bool(fetched) and fetched >= (end + timedelta(days=FINAL_AFTER_DAYS)).isoformat()
        if final or c is None or _age_h(got.get("fetched_at")) < max_age_h:
            return got.get("rows") or []
    if c is None or date(y, m, 1) > today:
        return (got or {}).get("rows") if got else None
    from oddsmarkets.baseball.sources import statsapi
    rows = statsapi.transactions_raw(c, date(y, m, 1), min(end, today), level)
    if rows is None:
        return (got or {}).get("rows") if got else None
    an.write_json(p, {"fetched_at": an.now(), "level": level, "month": f"{y:04d}-{m:02d}", "rows": rows})
    return rows


def transactions(level: str, lo: date, hi: date, c=None, max_age_h: float = 3.0, today: date | None = None) -> list[dict]:
    """Every cached (or fetched) transaction dated lo..hi, oldest first."""
    out = []
    for y, m in months(lo, hi):
        rows = tx_month(level, y, m, c, max_age_h, today) or []
        out.extend(r for r in rows if r.get("d") and lo.isoformat() <= r["d"] <= hi.isoformat())
    out.sort(key=lambda r: (r.get("d") or "", r.get("id") or 0))
    return out


# ── stat lines ──────────────────────────────────────────────────────────────

def _lines_path(level: str, name: str) -> Path:
    return root() / "lines" / level / f"{name}.json"


def season_lines(level: str, season: int, group: str, c=None, max_age_h: float = 6.0, today: date | None = None) -> dict | None:
    """{pid: line} for a season (statsapi.stat_lines), cached; a season fetched after 15 November is final."""
    p = _lines_path(level, f"season_{group}_{season}")
    got = an.read_json(p)
    today = today or _now().date()
    if got is not None:
        final = str(got.get("fetched_at") or "")[:10] >= date(season, *SEASON_FINAL).isoformat()
        if final or c is None or _age_h(got.get("fetched_at")) < max_age_h:
            return got.get("rows")
    if c is None or season > today.year:
        return (got or {}).get("rows") if got else None
    from oddsmarkets.baseball.sources import statsapi
    rows = statsapi.stat_lines(c, group, level, season=season)
    if rows is None:
        return (got or {}).get("rows") if got else None
    an.write_json(p, {"fetched_at": an.now(), "level": level, "season": season, "group": group, "rows": rows})
    return rows


def range_lines(level: str, start: date, end: date, group: str, c=None, today: date | None = None) -> dict | None:
    """{pid: line} for start..end (inclusive), cached; final once fetched three days after `end`."""
    p = _lines_path(level, f"range_{group}_{start.isoformat()}_{end.isoformat()}")
    got = an.read_json(p)
    today = today or _now().date()
    if got is not None:
        if str(got.get("fetched_at") or "")[:10] >= (end + timedelta(days=3)).isoformat() or c is None or _age_h(got.get("fetched_at")) < 3:
            return got.get("rows")
    if c is None or start > today:
        return (got or {}).get("rows") if got else None
    from oddsmarkets.baseball.sources import statsapi
    rows = statsapi.stat_lines(c, group, level, season=start.year, start=start, end=min(end, today))
    if rows is None:
        return (got or {}).get("rows") if got else None
    an.write_json(p, {"fetched_at": an.now(), "level": level, "start": start.isoformat(), "end": end.isoformat(), "group": group, "rows": rows})
    return rows


def season_weeks(season: int, store: dict | None = None) -> list[tuple[date, date]]:
    """Monday-to-Sunday weeks covering the regular season (from the store's first and last regular-season games;
    the season window when there is no store)."""
    lo, hi = None, None
    for g in ((store or {}).get("games") or {}).values():
        if g.get("gtype") != "R" or not g.get("date"):
            continue
        d = str(g["date"])[:10]
        lo = d if lo is None or d < lo else lo
        hi = d if hi is None or d > hi else hi
    a = date.fromisoformat(lo) if lo else date(season, 3, 25)
    b = date.fromisoformat(hi) if hi else date(season, 9, 30)
    a = a - timedelta(days=a.weekday())
    out = []
    while a <= b:
        out.append((a, a + timedelta(days=6)))
        a += timedelta(days=7)
    return out


def week_lines(level: str, season: int, group: str, store: dict | None = None, c=None, today: date | None = None) -> dict[str, dict]:
    """{"YYYY-MM-DD" (the Monday): {pid: line}} for every week of the season that is cached (or fetched)."""
    out = {}
    for a, b in season_weeks(season, store):
        r = range_lines(level, a, b, group, c, today)
        if r is not None:
            out[a.isoformat()] = r
    return out


# ── people the crosswalk lacks ──────────────────────────────────────────────

def people(pids: Iterable[str], c=None) -> dict[str, dict]:
    """Person records (name, birth date, position) for MLBAM ids, from people.json, then the cache, then the API."""
    want = {str(p) for p in pids if p and str(p).isdigit()}
    cp = root() / "people.json"
    cache = an.read_json(cp) or {}
    crosswalk = an.load_people()
    out = {}
    for p in want:
        x = crosswalk.get(p) or {}
        if x.get("birth"):
            out[p] = {"name": x.get("name"), "dob": x.get("birth"), "pos": None}
        elif p in cache:
            out[p] = cache[p]
    miss = sorted(want - set(out))
    if miss and c is not None:
        from oddsmarkets.baseball.sources import statsapi
        got = statsapi.people(c, miss)
        for p, r in got.items():
            cache[p] = {"name": r.get("name"), "dob": r.get("dob"), "pos": r.get("pos")}
            out[p] = cache[p]
        for p in miss:                               # unknown ids are remembered so they are not asked for again
            if p not in got:
                cache[p] = {"name": None, "dob": None, "pos": None}
        an.write_json(cp, cache)
    return out


# ── backfill ────────────────────────────────────────────────────────────────

def backfill(level: str, first: int, last: int, weekly_from: int, budget: int = 900, today: date | None = None) -> str:
    """Transactions month by month, season lines (hitting, pitching) and weekly lines from `weekly_from`."""
    today = today or _now().date()
    c = client(budget)
    from oddsmarkets.baseball.sources._client import BudgetExhausted
    try:
        for y, m in months(date(first - 1, 10, 1), today):
            if y > last:
                break
            tx_month(level, y, m, c, today=today)
        for s in range(first, last + 1):
            for g in ("hitting", "pitching"):
                season_lines(level, s, g, c, today=today)
        for s in range(weekly_from, last + 1):
            if s == 2020:
                continue
            st = an.load_store(level, s)
            for g in ("hitting", "pitching"):
                week_lines(level, s, g, st, c, today)
    except BudgetExhausted as exc:
        log.warning("statsapi backfill stopped: %s", exc)
    return c.report()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", default="mlb")
    ap.add_argument("--from", dest="first", type=int, default=2015)
    ap.add_argument("--to", dest="last", type=int, default=_now().year)
    ap.add_argument("--weekly-from", type=int, default=2022)
    ap.add_argument("--budget", type=int, default=900)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(backfill(args.level, args.first, args.last, args.weekly_from, args.budget))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
