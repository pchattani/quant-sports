"""
Closed Polymarket football match markets and their hourly price history (no key).

Each fixture is an event in the league's sports series with three yes/no markets
(home win, draw, away win). `endDate` is the scheduled kickoff. The CLOB
`prices-history` endpoint returns an hourly *last/mid* price ("p"), not the bid and
ask, so a bet price derived from it needs an assumed half-spread (see the edge script).

Cache (git-ignored): data/football/odds/polymarket/
    events/<sport>.json           closed events of the series (markets trimmed)
    history/<event_id>.json       {token_id: [[t, p], ...]} for the 4 days before kickoff
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from oddsmarkets.football.sources.prediction_markets import GAMMA, MARKETS

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "football" / "odds" / "polymarket"
CLOB = "https://clob.polymarket.com"
HEADERS = {"User-Agent": "The Quant Footballer research (+https://pchattani.github.io/the-quant-footballer/)"}
PAUSE_S = 0.6


class RateLimited(RuntimeError):
    pass


def _get(url: str, params: dict | None = None, tries: int = 5):
    for k in range(tries):
        time.sleep(PAUSE_S * (1 + 3 * k))
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
        except requests.RequestException as exc:  # pragma: no cover - network
            logger.warning("polymarket %s: %s", url, exc)
            continue
        if r.status_code == 429:
            time.sleep(10 * (k + 1))
            continue
        if r.status_code != 200:
            logger.warning("polymarket %s -> HTTP %s", url, r.status_code)
            return None
        return r.json()
    raise RateLimited(url)


def series_ids() -> dict[str, str]:
    d = _get(f"{GAMMA}/sports") or []
    return {x["sport"]: str(x["series"]) for x in d if x.get("sport") and x.get("series")}


def closed_events(sport: str, series_id: str, refresh: bool = False) -> list[dict]:
    p = CACHE / "events" / f"{sport}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    out, off = [], 0
    while True:
        d = _get(f"{GAMMA}/events", {"series_id": series_id, "closed": "true", "limit": 500, "offset": off})
        if not d:
            break
        for e in d:
            ms = [{"question": m.get("question"), "tokens": m.get("clobTokenIds"), "outcomePrices": m.get("outcomePrices"),
                   "volume": m.get("volume"), "groupItemTitle": m.get("groupItemTitle")} for m in e.get("markets", [])]
            out.append({"id": e.get("id"), "title": e.get("title"), "endDate": e.get("endDate"), "markets": ms})
        off += len(d)  # the API caps a page at 100 whatever the limit
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out), encoding="utf-8")
    return out


def event_history(e: dict) -> dict:
    p = CACHE / "history" / f"{e['id']}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    end = int(datetime.fromisoformat(e["endDate"].replace("Z", "+00:00")).timestamp())
    out = {}
    for m in e["markets"]:
        toks = json.loads(m["tokens"]) if isinstance(m["tokens"], str) else (m["tokens"] or [])
        if not toks:
            continue
        d = _get(f"{CLOB}/prices-history", {"market": toks[0], "startTs": end - 4 * 86400, "endTs": end + 3600, "fidelity": 60})
        out[toks[0]] = [[h["t"], h["p"]] for h in ((d or {}).get("history") or [])]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out), encoding="utf-8")
    return out


def download(slugs: list[str]) -> pd.DataFrame:
    sids = series_ids()
    rows = []
    for slug in slugs:
        sport = MARKETS.get(slug, (None,))[0]
        if not sport or sport not in sids:
            continue
        evs = [e for e in closed_events(sport, sids[sport]) if len(e["markets"]) == 3 and e.get("endDate")]
        logger.info("polymarket %s: %d closed 3-way events", sport, len(evs))
        for e in evs:
            try:
                h = event_history(e)
            except RateLimited:
                logger.warning("polymarket: rate limited; stopping (re-run resumes)")
                return pd.DataFrame(rows)
            for m in e["markets"]:
                toks = json.loads(m["tokens"]) if isinstance(m["tokens"], str) else (m["tokens"] or [])
                if not toks:
                    continue
                prices = json.loads(m["outcomePrices"]) if isinstance(m["outcomePrices"], str) else m["outcomePrices"]
                won = prices and float(prices[0]) > 0.5
                for t, pr in h.get(toks[0], []):
                    rows.append({"league": slug, "event": e["id"], "title": e["title"], "kickoff": e["endDate"],
                                 "question": m["question"], "won": bool(won), "ts": t, "p": pr})
    return pd.DataFrame(rows)


if __name__ == "__main__":  # pragma: no cover
    import sys
    logging.basicConfig(level=logging.INFO)
    df = download(sys.argv[1:])
    out = CACHE / "history_long.parquet"
    df.to_parquet(out)
    print(len(df), "rows ->", out)
