"""
Kalshi game-winner history (scripts/bb_kalshi_history.py) joined to the stores.

One market (one side) per game is fetched; the other side trades at 1 - bid / 1 - ask. Per game:
  dec_*   prices at the decision time (the hourly candle ending at or before it): yes ask / bid for the fetched side
  close_* the last candle ending at or before tip-off (mid = de-vigged fair probability, spread noted)
Taker fee (Kalshi general schedule): 0.07 * p * (1 - p) per contract (bulk order), added to the ask.
`hours_before` moves the decision to a fixed time before tip-off instead of the table's decision_time.
Matching: the event ticker's date (US day) and the two team codes (CODE_ALIASES -> ESPN abbreviations).
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from oddsmarkets.basketball.models import _io
from oddsmarkets.common.fees import kalshi_fee_per_contract
from oddsmarkets.basketball.sources.markets import CODE_ALIASES

SERIES = {"nba": "KXNBAGAME", "wnba": "KXWNBAGAME"}
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def fee(p: float) -> float:
    """Taker fee per contract for a bulk order (Kalshi rounds the ORDER's fee up to the cent, so per contract
    it is 0.07 p (1 - p) plus at most a cent spread over the order). Delegates to common/fees.py."""
    return kalshi_fee_per_contract(p)


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _at(candles: list[dict], ts: float) -> dict | None:
    best = None
    for c in candles:
        if c.get("end_period_ts", 0) <= ts:
            bid = _f((c.get("yes_bid") or {}).get("close"))
            ask = _f((c.get("yes_ask") or {}).get("close"))
            if bid is not None and ask is not None and 0 < bid <= ask < 1:
                best = {"bid": bid, "ask": ask, "ts": c["end_period_ts"], "vol": _f(c.get("volume")) or 0.0,
                        "oi": _f(c.get("open_interest")) or 0.0}
    return best


def load(league: str, games: pd.DataFrame, abbr: dict[int, dict[str, str]], hours_before: float | None = None) -> pd.DataFrame:
    """games: the experiment table (event_id, season, day, home, away, start_time, decision_time, margin).
    abbr: {season: {team_id: ESPN abbreviation}}. Returns one row per matched game."""
    series = SERIES[league]
    root = _io.cache_root() / "kalshi" / series
    try:
        markets = json.loads((root / "markets.json").read_text("utf-8"))
    except (OSError, ValueError):
        return pd.DataFrame()
    alias = CODE_ALIASES[league]
    idx = {}
    for _, g in games.iterrows():
        ab = abbr.get(int(g.season)) or {}
        idx[(g.day, ab.get(g.home), ab.get(g.away))] = g
    rows = []
    seen = set()
    for m in sorted(markets, key=lambda m: m["ticker"]):
        ev = m["event_ticker"]
        if ev in seen:
            continue
        p = root / "candles" / f"{m['ticker']}.json"
        if not p.exists():
            continue
        mt = re.match(r"^[A-Z]+-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$", ev)
        if not mt:
            continue
        yy, mon, dd, codes = mt.groups()
        side = m["ticker"].rsplit("-", 1)[-1]
        other = codes[: len(codes) - len(side)] if codes.endswith(side) else codes[len(side):] if codes.startswith(side) else None
        if not other:
            continue
        day = datetime(2000 + int(yy), MONTHS[mon], int(dd)).date()
        s_ab, o_ab = alias.get(side, side), alias.get(other, other)
        g = idx.get((day, s_ab, o_ab))
        side_is_home = True
        if g is None:
            g = idx.get((day, o_ab, s_ab))
            side_is_home = False
        if g is None:
            continue
        seen.add(ev)
        candles = json.loads(p.read_text("utf-8"))
        st = datetime.fromisoformat(str(g.start_time).replace("Z", "+00:00")).timestamp()
        dt = st - hours_before * 3600 if hours_before is not None else pd.Timestamp(g.decision_time).timestamp()
        dq, cq = _at(candles, dt), _at(candles, st)
        if cq is None:
            continue
        # express everything for the HOME side
        def home(q):
            if q is None:
                return None
            if side_is_home:
                return q
            return {**q, "bid": 1 - q["ask"], "ask": 1 - q["bid"]}
        dh, ch = home(dq), home(cq)
        rows.append({"event_id": g.event_id, "ticker": m["ticker"], "side_is_home": side_is_home,
                     "dec_bid_h": dh["bid"] if dh else None, "dec_ask_h": dh["ask"] if dh else None,
                     "dec_ts": dh["ts"] if dh else None, "dec_oi": dh["oi"] if dh else None,
                     "close_bid_h": ch["bid"], "close_ask_h": ch["ask"], "close_mid_h": (ch["bid"] + ch["ask"]) / 2,
                     "close_oi": ch["oi"], "volume": _f(m.get("volume_fp")), "result_home": None})
    return pd.DataFrame(rows)


def selections(k: pd.DataFrame, t: pd.DataFrame, p_col: str) -> pd.DataFrame:
    """Kalshi moneyline selections at the decision time: buy the home yes at ask (+fee) or the away side at
    1 - bid (+fee). fair_p_decision = mid at decision; fair_p_close = mid at the last pre-game candle."""
    x = k.merge(t, on="event_id", how="inner")
    x = x.dropna(subset=["dec_bid_h", "dec_ask_h"])
    rows = []
    for _, r in x.iterrows():
        y = 1.0 if r.margin > 0 else 0.0
        mid = (r.dec_bid_h + r.dec_ask_h) / 2
        for side, cost, pm, fd, fc, out in (("home", r.dec_ask_h, r[p_col], mid, r.close_mid_h, y),
                                            ("away", 1 - r.dec_bid_h, 1 - r[p_col], 1 - mid, 1 - r.close_mid_h, 1 - y)):
            c = cost + fee(cost)
            if not (0 < c < 1):
                continue
            rows.append({"event_id": r.event_id, "league": r.league, "season": int(r.season), "start_time": r.start_time,
                         "decision_time": r.decision_time, "day": r.day, "stype": r.stype, "gp": int(r.gp_h + r.gp_a),
                         "market": "moneyline", "selection": side, "line": None, "model_p": float(pm), "model_push": 0.0,
                         "price_dec": 1 / c, "price_src": "kalshi_ask", "fair_p_decision": fd, "fair_p_close": fc,
                         "close_push": 0.0, "outcome": out, "max_stake_hint": r.dec_oi, "spread_cents": (r.dec_ask_h - r.dec_bid_h) * 100})
    s = pd.DataFrame(rows)
    if s.empty:
        return s
    s["model_ev"] = s.model_p * (s.price_dec - 1) - (1 - s.model_p)
    s["clv"] = s.fair_p_close * (s.price_dec - 1) - (1 - s.fair_p_close)
    s["profit"] = np.where(s.outcome == 1.0, s.price_dec - 1, -1.0)
    return s
