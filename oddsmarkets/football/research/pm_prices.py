"""
Prediction-market prices joined to football-data matches.

Kalshi: the yes-ask close of the last hourly candle ending at or before the decision time,
with a live two-sided quote (bid > 0, ask < 1). The bet price includes Kalshi's taker fee
(0.07 * P * (1 - P) per contract, before rounding): price_dec = 1 / (ask + fee).

Polymarket: the hourly history is a last/mid price only; the bet price assumes a half-cent
half-spread and no fee: price_dec = 1 / (p + 0.005). Treat it as indicative.

Matching: same league, the market's date within a day of the football-data kickoff, both
club names matching (folded, club-form words dropped, token-set ratio >= 80).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from oddsmarkets.football.sources.prediction_markets import ALIASES, fold
from oddsmarkets.common.fees import KALSHI_TAKER_RATE, kalshi_cost, kalshi_decimal  # noqa: F401

KALSHI_FEE = KALSHI_TAKER_RATE      # common/fees.py
POLY_HALF_SPREAD = 0.005


def _norm(s: str) -> str:
    f = fold(s)
    return fold(ALIASES.get(f, f))


def _same(a: str, b: str) -> bool:
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return False
    if x == y or set(x.split()) <= set(y.split()) or set(y.split()) <= set(x.split()):
        return True
    return fuzz.token_set_ratio(x, y) >= 80


def _score(a: str, b: str) -> float:
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return 0.0
    if _same(a, b):
        return 100.0
    return max(fuzz.token_set_ratio(x, y), fuzz.partial_ratio(x, y) * 0.9)


def match_events(ev: pd.DataFrame, fd: pd.DataFrame) -> pd.DataFrame:
    """ev: event, league, day (UTC date), home, away. Returns ev with fd_index (or NaN)."""
    out = ev.copy()
    out["fd_index"] = np.nan
    out["swapped"] = False
    fd = fd.assign(day=fd.start_time.dt.floor("D"))
    by = {k: g for k, g in fd.groupby(["league", "day"])}
    for i, r in out.iterrows():
        for dd in (r.day, r.day - pd.Timedelta(days=1), r.day + pd.Timedelta(days=1)):
            g = by.get((r.league, dd))
            if g is None:
                continue
            sc = np.array([min(_score(r.home, h), _score(r.away, a)) for h, a in zip(g.home, g.away)])
            order = np.argsort(-sc)
            if sc[order[0]] >= 60 and (len(sc) == 1 or sc[order[0]] - sc[order[1]] >= 10):
                out.at[i, "fd_index"] = g.index[order[0]]
                break
        if np.isnan(out.at[i, "fd_index"]):
            pass
    return out


def kalshi_quotes(candles_dir: Path, markets_dir: Path, leagues: dict[str, str]) -> pd.DataFrame:
    """One row per Kalshi market with its hourly candles flattened (league, event, side, ts, bid, ask)."""
    rows = []
    for slug, series in leagues.items():
        mp = markets_dir / f"{series}.json"
        if not mp.exists():
            continue
        ms = json.loads(mp.read_text(encoding="utf-8"))
        by_ev: dict[str, list[dict]] = {}
        for m in ms:
            by_ev.setdefault(m["event_ticker"], []).append(m)
        for evt, mlist in by_ev.items():
            cp = candles_dir / f"{evt}.json"
            if not cp.exists():
                continue
            cs = json.loads(cp.read_text(encoding="utf-8"))
            title = (mlist[0].get("title") or "").replace(" Winner?", "")
            if " vs " not in title:
                continue
            home, away = [t.strip() for t in title.split(" vs ", 1)]
            exp = pd.Timestamp(mlist[0].get("expected_expiration_time") or mlist[0]["close_time"])
            for m in mlist:
                side = m.get("yes_sub_title") or ""
                sel = "draw" if side.lower() in ("tie", "draw") else ("home" if _same(side, home) else "away" if _same(side, away) else None)
                if sel is None:
                    continue
                for c in cs.get(m["ticker"], []):
                    rows.append({"league": slug, "event": evt, "home": home, "away": away, "expected_expiration": exp,
                                 "selection": sel, "result": m.get("result"),
                                 "ts": pd.Timestamp(c["end_period_ts"], unit="s", tz="UTC"),
                                 "bid": c["yes_bid"]["close"], "ask": c["yes_ask"]["close"],
                                 "volume": float(c.get("volume") or 0)})
    return pd.DataFrame(rows)


def quote_at(q: pd.DataFrame, when: pd.Series) -> pd.DataFrame:
    """For each (event, selection), the last candle at or before `when[event]` with a two-sided quote."""
    q = q[(q.bid > 0) & (q.ask < 1) & q.ask.notna()].copy()
    q["when"] = q.event.map(when)
    q = q[q.ts <= q["when"]]
    q = q[q.ts >= q["when"] - pd.Timedelta(hours=6)]  # stale quotes are not prices
    return q.sort_values("ts").groupby(["event", "selection"]).tail(1)


def polymarket_quotes(cache: Path, sports: dict[str, str]) -> pd.DataFrame:
    """Flatten cached Polymarket histories: league, event, home, away, kickoff, selection, ts, p, won."""
    rows = []
    for slug, sport in sports.items():
        ep = cache / "events" / f"{sport}.json"
        if not ep.exists():
            continue
        for e in json.loads(ep.read_text(encoding="utf-8")):
            hp = cache / "history" / f"{e['id']}.json"
            if not hp.exists() or " vs" not in (e.get("title") or ""):
                continue
            home, away = [t.strip(" .") for t in re.split(r"\s+vs\.?\s+", e["title"], maxsplit=1)]
            h = json.loads(hp.read_text(encoding="utf-8"))
            for m in e["markets"]:
                toks = json.loads(m["tokens"]) if isinstance(m["tokens"], str) else (m["tokens"] or [])
                if not toks or toks[0] not in h:
                    continue
                q = (m.get("question") or "").lower()
                if "draw" in q:
                    sel = "draw"
                else:
                    mm = re.match(r"will (.+?) win", q)
                    team = mm.group(1) if mm else ""
                    sel = "home" if _score(team, home) >= _score(team, away) else "away"
                prices = json.loads(m["outcomePrices"]) if isinstance(m.get("outcomePrices"), str) else m.get("outcomePrices")
                won = bool(prices) and float(prices[0]) > 0.5
                for t, pr in h[toks[0]]:
                    rows.append({"league": slug, "event": e["id"], "home": home, "away": away,
                                 "kickoff": pd.Timestamp(e["endDate"]), "selection": sel, "won": won,
                                 "ts": pd.Timestamp(t, unit="s", tz="UTC"), "p": float(pr)})
    return pd.DataFrame(rows)
