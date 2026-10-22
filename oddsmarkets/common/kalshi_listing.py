"""
Incremental refresh of Kalshi's settled listings (cursor pages), shared by the sports' Kalshi history fetchers.

Listings: GET /markets?status=settled, GET /historical/markets and GET /events?status=settled, each paged by an
opaque cursor. Kalshi serves them newest first (checked 21 Oct 2026 on the cached KXNFLGAME pages: the first page
opens with the latest game, the cursor encodes the last row's time and ticker). So new settlements land on the
first page, and a market that crosses the historical cutoff lands on the first page of /historical/markets.

A fetcher that cached the listing once and never re-read it never saw a new game (the NFL fetcher cached every
settled page for good; the football one cached the whole listing for good). `refresh` instead walks from the
newest page and stops at the first page whose rows are all already known and closed more than `grow_days` ago:
that page and everything older can no longer change, and the previous snapshot supplies it. Only the newest pages,
and the pages holding games that closed in the last `grow_days` days (late settlements, corrections), are fetched
again. A snapshot that never finished a full walk (an interrupted first fetch, or a failure mid-refresh) is walked
in full on its next refresh.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable

GROW_DAYS = 14.0
TIME_FIELDS = ("settlement_ts", "close_time", "expected_expiration_time", "occurrence_datetime")


def _ts(v: Any) -> float | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def row_time(row: dict) -> float | None:
    """The latest of a market's settlement / close / expiry times (an event: over its nested markets)."""
    ts = [_ts(row.get(f)) for f in TIME_FIELDS]
    for m in row.get("markets") or []:
        if isinstance(m, dict):
            ts += [_ts(m.get(f)) for f in TIME_FIELDS]
    ts = [t for t in ts if t is not None]
    return max(ts) if ts else None


def row_id(row: dict) -> str | None:
    """Markets by ticker, events (no ticker) by event ticker."""
    return row.get("ticker") or row.get("event_ticker")


def refresh(fetch_page: Callable[[str | None], dict | None], key: str, known: Iterable[dict] | None = None,
            complete: bool = False, *, grow_days: float = GROW_DAYS, now: datetime | None = None,
            max_pages: int = 500, ident: Callable[[dict], Any] = row_id) -> tuple[list[dict], bool, int]:
    """
    Refresh a newest-first cursor listing against a previous snapshot `known` (rows, newest first).

    `fetch_page(cursor)` returns one page's JSON body (None on failure); `key` is the list's field ("markets",
    "events"). The walk stops at the end of the listing, or (when `complete`, i.e. the snapshot once held the whole
    listing) at the first page whose rows are all in the snapshot and whose newest close is more than `grow_days`
    before `now` (a row without any time counts as old once known: Kalshi returns pre-cutoff events without their
    markets). Returns (rows newest first: the fetched rows, then the snapshot's rows not fetched again; complete;
    pages fetched). Fetched rows replace their snapshot copies.
    """
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    cutoff = now_ts - grow_days * 86400.0
    prev = [r for r in (known or []) if ident(r) is not None]
    seen_before = {ident(r) for r in prev}
    fresh: dict[Any, dict] = {}
    cursor: str | None = None
    pages = 0
    ok = False
    while pages < max_pages:
        body = fetch_page(cursor)
        if body is None:
            break
        pages += 1
        rows = [r for r in (body.get(key) or []) if isinstance(r, dict) and ident(r) is not None]
        settled_long_ago = all((row_time(r) is None or row_time(r) < cutoff) for r in rows)
        stable = bool(rows) and settled_long_ago and all(ident(r) in seen_before for r in rows)
        for r in rows:
            fresh.setdefault(ident(r), r)
        cursor = body.get("cursor") or None
        if not cursor or not rows:
            ok = True                       # the end of the listing: the walk saw all of it
            break
        if stable and complete:
            ok = True                       # older pages are unchanged since the snapshot
            break
    rows_out = list(fresh.values()) + [r for r in prev if ident(r) not in fresh]
    return rows_out, ok, pages
