"""
Kalshi tennis match markets as an earlier decision time (docs/research/tennis_edge.md, section "Prediction markets").

For every settled KXATPMATCH / KXWTAMATCH event whose candles are cached (kalshi_hist.py), the two Kalshi labels are
mapped to store players (markets.map_player, the site's own matcher) and the event to the store's match (same pair
within 3 days of the ticker date). Decision times, both strictly before the first ball:

* "open": the first hourly candle ending at least 2 h after the market opened with a two-sided quote
  (0 < bid <= ask < 1, spread <= 0.06), and before the cut-off;
* "late": the last candle with such a quote ending before the cut-off.
The cut-off is the earlier of close_time - 6 h (Kalshi closes a match market when the winner is declared, and
almost no match lasts 6 h) and the store's scheduled start - 1 h (ESPN / WTA times; a match is rarely started
earlier than scheduled). Both guards are needed: close_time alone let in-play quotes through for matches
suspended or settled late (seen in the first pass, e.g. a 0.015 quote 9.6 h before the close of a Wimbledon R64
match the books closed at 0.22).

Executable prices at a decision: back player X at the candle's closing yes ask a (decimal 1/a), back the opponent
at the NO ask 1 - bid. Kalshi's taker fee, ceil(0.07 * C * P * (1 - P)) dollars for C contracts at price P, is
carried separately per $1 contract (`fee`), so `price_dec` stays the raw quote as the protocol asks.
The closing reference is tennis-data's de-vigged close: Pinnacle where present (to November 2025), else the
Betfair exchange close, else the market average.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from oddsmarkets.common.fees import KALSHI_TAKER_RATE, kalshi_fee_per_contract
from oddsmarkets.tennis.models import _io
from oddsmarkets.tennis.research.kalshi_hist import CACHE
from oddsmarkets.tennis.sources import markets as MK

SPREAD_MAX = 0.06
FEE_RATE = KALSHI_TAKER_RATE          # common/fees.py


def _ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _quotes(cs: list) -> list[tuple[float, float, float, float]]:
    """[(end_ts, bid, ask, volume)] with a valid two-sided quote at the candle's close."""
    out = []
    for c in cs or []:
        b = _f((c.get("yes_bid") or {}).get("close"))
        a = _f((c.get("yes_ask") or {}).get("close"))
        if b is None or a is None or not (0 < b <= a < 1) or a - b > SPREAD_MAX:
            continue
        out.append((float(c["end_period_ts"]), b, a, _f(c.get("volume")) or 0.0))
    return out


def decisions(m: dict, cs: list, sched: float | None = None) -> dict:
    q = _quotes(cs)
    o, c = _ts(m.get("open_time")), _ts(m.get("close_time"))
    if not q or o is None or c is None:
        return {}
    cut = c - 6 * 3600
    if sched is not None:
        cut = min(cut, sched - 3600)
    out = {}
    early = [x for x in q if o + 7200 <= x[0] <= cut]
    if early:
        out["open"] = early[0]
    late = [x for x in q if x[0] <= cut]
    if late:
        out["late"] = late[-1]
    return out


def _sched(m: dict) -> float | None:
    d = str(m.get("date") or "")
    if "T" not in d:
        return None
    try:
        return datetime.fromisoformat(d[:16]).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _label(m: dict) -> str:
    t = str(m.get("title") or "")
    return t[:-5].strip() if t.endswith(" wins") else (m.get("no_sub_title") or t)


def load(tour: str) -> pd.DataFrame:
    """One row per matched event and decision: {id (store match), date, decision, ts, x_pid, bid, ask, close_ts,
    ticker, volume_total}. x_pid is the player of the market whose candles were fetched (YES = x_pid wins)."""
    t = _io.tour_key(tour)
    series = {"atp": "KXATPMATCH", "wta": "KXWTAMATCH"}[t]
    p = CACHE / f"index_{series}.json"
    if not p.exists():
        return pd.DataFrame()
    idx = json.loads(p.read_text(encoding="utf-8"))
    by_ev: dict = {}
    for m in idx:
        by_ev.setdefault(m["event_ticker"], []).append(m)
    stores: dict = {}

    def store(y):
        if y not in stores:
            stores[y] = _io.load_store(t, y) or {}
        return stores[y]
    rows = []
    for ev, ms in by_ev.items():
        got = [(m, CACHE / "candles" / f"{m['ticker']}.json") for m in ms]
        got = [(m, f) for m, f in got if f.exists()]
        if not got or len(ms) != 2:
            continue
        m, f = got[0]
        ed = MK.kalshi_match_date(ev)
        if ed is None:
            continue
        cands = []
        for y in {ed.year, (ed.year - 1) if ed.month == 1 else ed.year}:
            st = store(y)
            for mm in (st.get("matches") or {}).values():
                d = _io.day(mm.get("date"))
                if d and abs((d - ed).days) <= 3 and mm.get("p1") and mm.get("p2"):
                    cands.append(mm)
        field = sorted({str(x[k]) for x in cands for k in ("p1", "p2")})
        players = {}
        for y in {ed.year, ed.year - 1}:
            players.update(store(y).get("players") or {})
        x = MK.map_player(_label(m), players, field)
        other = next(mm for mm in ms if mm["ticker"] != m["ticker"])
        z = MK.map_player(_label(other), players, field)
        if not x or not z or x == z:
            continue
        hits = [mm for mm in cands if {str(mm["p1"]), str(mm["p2"])} == {x, z}]
        if not hits:
            continue
        hit = min(hits, key=lambda mm: abs((_io.day(mm["date"]) - ed).days))
        cs = json.loads(f.read_text(encoding="utf-8"))
        vol = sum(_f(c.get("volume")) or 0.0 for c in cs)
        for dname, (ts, b, a, v) in decisions(m, cs, _sched(hit)).items():
            rows.append({"id": hit["id"], "date": str(hit["date"])[:10], "decision": dname, "ts": ts, "x_pid": x,
                         "bid": b, "ask": a, "close_ts": _ts(m.get("close_time")), "ticker": m["ticker"],
                         "sched_ts": _sched(hit), "candle_volume": v,
                         "volume_total": vol, "result_x": 1 if m.get("result") == "yes" else 0})
    return pd.DataFrame(rows)


def fee(p) -> np.ndarray:
    return kalshi_fee_per_contract(np.asarray(p, float))
