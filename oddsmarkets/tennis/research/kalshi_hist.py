"""
Kalshi tennis match-market history for the earlier-decision-time test (docs/research/tennis_edge.md).

* `index(series)`: every settled market of a series, from the live API (settled after Kalshi's historical
  cutoff) and the historical API (before it), paged by cursor; cached as one JSON per series.
* `candles(market)`: hourly candlesticks (yes bid/ask OHLC, traded price, volume) over the market's life,
  one JSON per ticker under data/edge/cache/kalshi/ (fetched once; a settled market never changes).

Polite: one request at a time, at most ~4 per second, exponential back-off on 429. Public endpoints, no key.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from oddsmarkets.tennis.models import _io

API = "https://api.elections.kalshi.com/trade-api/v2"
CACHE = _io.ROOT / "data" / "edge" / "cache" / "kalshi"
SERIES = ("KXATPMATCH", "KXWTAMATCH", "KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH")
MIN_INTERVAL = 0.25
_last = [0.0]
_sess = requests.Session()
_sess.headers["User-Agent"] = "oddsmarkets-research/1.0 (personal research; cached)"


def _get(path: str, params: dict | None = None, tries: int = 8):
    wait = 2.0
    for _ in range(tries):
        dt = time.time() - _last[0]
        if dt < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - dt)
        _last[0] = time.time()
        try:
            r = _sess.get(f"{API}{path}", params=params, timeout=30)
        except requests.RequestException:
            time.sleep(wait)
            wait = min(wait * 2, 60)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(wait)
            wait = min(wait * 2, 60)
            continue
        return None
    return None


def _ts(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


KEEP = ("ticker", "event_ticker", "title", "open_time", "close_time", "occurrence_datetime", "expected_expiration_time",
        "settlement_ts", "result", "volume_fp", "rules_primary", "custom_strike", "no_sub_title", "status")


def index(series: str, refresh: bool = False) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / f"index_{series}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    out: dict = {}
    for path, extra in (("/markets", {"status": "settled"}), ("/historical/markets", {})):
        cur = None
        while True:
            prm = {"series_ticker": series, "limit": 1000, **extra}
            if cur:
                prm["cursor"] = cur
            d = _get(path, prm) or {}
            for m in d.get("markets") or []:
                out[m["ticker"]] = {k: m.get(k) for k in KEEP} | {"_hist": path.startswith("/historical")}
            cur = d.get("cursor")
            if not cur or not d.get("markets"):
                break
    rows = sorted(out.values(), key=lambda m: m.get("open_time") or "")
    p.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def candles(m: dict, series: str) -> list | None:
    d = CACHE / "candles"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{m['ticker']}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    a = _ts(m.get("open_time"))
    b = _ts(m.get("close_time")) or _ts(m.get("settlement_ts"))
    if not a or not b:
        return None
    prm = {"start_ts": a - 3600, "end_ts": b + 3600, "period_interval": 60}
    path = (f"/historical/markets/{m['ticker']}/candlesticks" if m.get("_hist")
            else f"/series/{series}/markets/{m['ticker']}/candlesticks")
    r = _get(path, prm)
    if r is None and not m.get("_hist"):
        r = _get(f"/historical/markets/{m['ticker']}/candlesticks", prm)
    if r is None:
        return None
    cs = r.get("candlesticks") or []
    p.write_text(json.dumps(cs), encoding="utf-8")
    return cs


def run(series_list=SERIES, candle_series=("KXATPMATCH", "KXWTAMATCH"), seed: int = 7):
    """Index every series, then fetch candles for one market per event, the ATP and WTA events interleaved in a
    fixed random order (so a partial run is a uniform sample of both tours)."""
    import random
    todo = []
    for s in series_list:
        rows = index(s)
        print(s, "markets", len(rows), flush=True)
        if s not in candle_series:
            continue
        seen = set()
        for m in rows:
            ev = m.get("event_ticker")
            if ev in seen or m.get("result") not in ("yes", "no"):
                continue
            seen.add(ev)
            todo.append((m, s))
    random.Random(seed).shuffle(todo)
    for n, (m, s) in enumerate(todo, 1):
        candles(m, s)
        if n % 250 == 0:
            print("candles", n, "of", len(todo), flush=True)
    print("done", len(todo), flush=True)


if __name__ == "__main__":
    run(tuple(sys.argv[1:]) or SERIES)
