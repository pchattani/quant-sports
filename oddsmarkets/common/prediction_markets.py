"""
Kalshi and Polymarket, sport-neutral.

Re-exports the football module's primitives unchanged
(`oddsmarkets.football.sources.prediction_markets`):

    _get(url, params)        GET -> JSON, or None on any failure (never raises)
    _mid(bid, ask)           midpoint of a live two-sided quote: (bid + ask) / 2 when
                             0 < bid <= ask < 1 and ask - bid <= MAX_SPREAD (0.12); else None.
                             A last trade is never used as a price.
    fold(name)               accent-folded, lower-cased tokens without club-form words
    name_score, best_match   token-subset (0.93) or difflib ratio; best_match refuses
                             ties (runner-up within 0.02) and scores below `floor` (0.72)

and adds helpers that take a Kalshi series ticker or a Polymarket slug / query /
tag, so other sports do not depend on football's competition table.
"""
from __future__ import annotations

import json
from typing import Any

from oddsmarkets.football.sources.prediction_markets import (  # noqa: F401
    ALIASES,
    GAMMA,
    HEADERS,
    KALSHI,
    MAX_SPREAD,
    TIMEOUT,
    _f,
    _get,
    _kalshi_price,
    _mid,
    _odds,
    _parse_time,
    _poly_price,
    best_match,
    fold,
    name_score,
)


def kalshi_price(m: dict) -> float | None:
    """Midpoint of a Kalshi market's live yes bid/ask (dollars), or None."""
    return _kalshi_price(m or {})


def poly_price(m: dict) -> float | None:
    """Midpoint of a Polymarket market's best bid/ask (first outcome), or None."""
    return _poly_price(m or {})


def kalshi_events(series_ticker: str, status: str | None = "open", limit: int = 200, max_pages: int = 5) -> list[dict]:
    """Events (with nested markets) of one Kalshi series; [] when unreachable."""
    out: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params: dict[str, Any] = {"series_ticker": series_ticker, "with_nested_markets": "true", "limit": limit}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        page = _get(f"{KALSHI}/events", params) or {}
        out.extend(page.get("events") or [])
        cursor = page.get("cursor")
        if not cursor or not page.get("events"):
            break
    return out


def polymarket_event(slug: str) -> dict | None:
    """One Polymarket event by slug (with its markets), or None."""
    rows = _get(f"{GAMMA}/events", {"slug": slug})
    if isinstance(rows, list) and rows:
        return rows[0]
    return None


def polymarket_search(query: str, active_only: bool = True, limit: int = 20) -> list[dict]:
    """Events from Polymarket's public search; [] when unreachable."""
    params: dict[str, Any] = {"q": query, "limit_per_type": limit}
    if active_only:
        params["events_status"] = "active"
    found = _get(f"{GAMMA}/public-search", params) or {}
    return list(found.get("events") or []) if isinstance(found, dict) else []


def polymarket_tag_events(tag_slug: str, closed: bool | None = False, limit: int = 200) -> list[dict]:
    """Events carrying a Polymarket tag (e.g. "f1"), newest end date first; [] when unreachable."""
    params: dict[str, Any] = {"tag_slug": tag_slug, "limit": limit, "order": "endDate", "ascending": "false"}
    if closed is not None:
        params["closed"] = "true" if closed else "false"
    rows = _get(f"{GAMMA}/events", params)
    return rows if isinstance(rows, list) else []


def poly_resolved(m: dict) -> float | None:
    """
    1.0 / 0.0 when a Polymarket market is closed and settled on its first outcome
    (outcomePrices ["1","0"] / ["0","1"]); None while it trades. Polymarket closes a
    title runner's market once that runner is mathematically eliminated.
    """
    if not m or not m.get("closed"):
        return None
    prices = m.get("outcomePrices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except ValueError:
            return None
    try:
        first = float(prices[0])
    except (TypeError, ValueError, IndexError):
        return None
    if first in (0.0, 1.0):
        return first
    return None
