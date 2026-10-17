"""
Settled Kalshi football game markets and their hourly price history (no key needed).

Kalshi lists each fixture as an event in a `KX...GAME` series (see
`prediction_markets.MARKETS`) with three binary markets: home club, away club and
"Tie". Markets settled before Kalshi's historical cutoff are served by the
`/historical/...` endpoints, later ones by the live endpoints; field names differ a
little between the two (`yes_ask.close` against `yes_ask.close_dollars`).

Everything is cached under data/football/odds/kalshi/ (git-ignored):
    markets/<SERIES>.json       every settled market of the series (both endpoints)
    candles/<EVENT>.json        hourly candles of the event's markets, open to expiry
A cached event is never re-fetched. Requests go one at a time with a pause.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from oddsmarkets.football.sources.prediction_markets import KALSHI, MARKETS

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "football" / "odds" / "kalshi"
HEADERS = {"User-Agent": "The Quant Footballer research (+https://pchattani.github.io/the-quant-footballer/)"}
PAUSE_S = 1.0
TIMEOUT = 30


def game_series() -> dict[str, str]:
    """competition slug -> Kalshi game series."""
    return {slug: v[1] for slug, v in MARKETS.items() if v[1]}


class RateLimited(RuntimeError):
    pass


def _get(path: str, params: dict | None = None, tries: int = 6) -> dict | None:
    for k in range(tries):
        time.sleep(PAUSE_S * (1 + 3 * k))
        try:
            r = requests.get(f"{KALSHI}{path}", params=params, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:  # pragma: no cover - network
            logger.warning("kalshi %s: %s", path, exc)
            continue
        if r.status_code == 429:
            time.sleep(15 * (k + 1))
            continue
        if r.status_code != 200:
            logger.warning("kalshi %s -> HTTP %s", path, r.status_code)
            return None
        return r.json()
    raise RateLimited(path)


def _list(path: str, series: str) -> list[dict]:
    out, cursor = [], None
    while True:
        params = {"series_ticker": series, "limit": 1000}
        if path == "/markets":
            params["status"] = "settled"
        if cursor:
            params["cursor"] = cursor
        d = _get(path, params)
        if not d:
            break
        out.extend(d.get("markets") or [])
        cursor = d.get("cursor")
        if not cursor or not d.get("markets"):
            break
    return out


def settled_markets(series: str, *, refresh: bool = False) -> list[dict]:
    p = CACHE / "markets" / f"{series}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    hist = _list("/historical/markets", series)
    for m in hist:
        m["_historical"] = True
    live = _list("/markets", series)
    seen = {m["ticker"] for m in hist}
    allm = hist + [m for m in live if m["ticker"] not in seen]
    keep = [{k: v for k, v in m.items() if not k.startswith("rules")} for m in allm]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(keep), encoding="utf-8")
    return keep


def _ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def event_candles(series: str, event: str, markets: list[dict]) -> dict:
    p = CACHE / "candles" / f"{event}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for m in markets:
        start = _ts(m.get("open_time") or m["created_time"])
        end = _ts(m.get("expected_expiration_time") or m["close_time"])
        # Four days before the expected expiry (about kickoff + 3 h) covers every
        # decision time we test (24 h and 1 h before kickoff) and keeps the cache small.
        start = max(start, end - 4 * 86400)
        if m.get("_historical"):
            path = f"/historical/markets/{m['ticker']}/candlesticks"
        else:
            path = f"/series/{series}/markets/{m['ticker']}/candlesticks"
        d = _get(path, {"start_ts": start, "end_ts": end, "period_interval": 60})
        out[m["ticker"]] = [_compact(c) for c in ((d or {}).get("candlesticks") or [])]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out), encoding="utf-8")
    return out


def _compact(c: dict) -> dict:
    """Keep only what the research reads: time, bid/ask close, volume, open interest."""
    return {"end_period_ts": c["end_period_ts"],
            "yes_bid": {"close": _quote(c, "yes_bid")}, "yes_ask": {"close": _quote(c, "yes_ask")},
            "volume": c.get("volume_fp", c.get("volume")), "open_interest": c.get("open_interest_fp", c.get("open_interest"))}


def _f(x) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _quote(c: dict, side: str) -> float | None:
    q = c.get(side) or {}
    return _f(q.get("close_dollars", q.get("close")))


def candle_frame(series: str, slug: str, markets: list[dict], candles: dict) -> pd.DataFrame:
    """Long frame: one row per market per hour with bid/ask close and volume."""
    rows = []
    by_t = {m["ticker"]: m for m in markets}
    for tk, cs in candles.items():
        m = by_t.get(tk)
        if not m:
            continue
        for c in cs:
            rows.append({
                "league": slug, "series": series, "event": m["event_ticker"], "ticker": tk,
                "title": m.get("title"), "side": m.get("yes_sub_title"), "result": m.get("result"),
                "expected_expiration": m.get("expected_expiration_time"),
                "ts": pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC"),
                "bid": _quote(c, "yes_bid"), "ask": _quote(c, "yes_ask"),
                "volume": _f(c.get("volume_fp", c.get("volume"))),
                "oi": _f(c.get("open_interest_fp", c.get("open_interest"))),
            })
    return pd.DataFrame(rows)


def download(slugs: list[str] | None = None, *, max_events: int | None = None) -> pd.DataFrame:
    """Fetch (or reuse) every settled game market and its candles; return the long frame."""
    frames = []
    for slug, series in game_series().items():
        if slugs and slug not in slugs:
            continue
        ms = settled_markets(series)
        events: dict[str, list[dict]] = {}
        for m in ms:
            events.setdefault(m["event_ticker"], []).append(m)
        logger.info("kalshi %s: %d markets, %d events", series, len(ms), len(events))
        for i, (ev, mlist) in enumerate(sorted(events.items())):
            if max_events and i >= max_events:
                break
            try:
                frames.append(candle_frame(series, slug, mlist, event_candles(series, ev, mlist)))
            except RateLimited:
                logger.warning("kalshi: rate limited at %s; stopping (re-run resumes from the cache)", ev)
                return pd.concat([f for f in frames if len(f)], ignore_index=True) if frames else pd.DataFrame()
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


if __name__ == "__main__":  # pragma: no cover
    import sys
    logging.basicConfig(level=logging.INFO)
    df = download(sys.argv[1:] or None)
    out = CACHE / "candles_long.parquet"
    df.to_parquet(out)
    print(len(df), "candle rows ->", out)
