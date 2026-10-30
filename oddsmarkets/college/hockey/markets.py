"""
Prediction markets for college hockey, shown quietly beside our numbers (house rule: our chance leads; the market
is a small grey reference). Surveyed 30 Oct 2026: Kalshi lists men's college hockey only,
  KXNCAAH-<yy>           national champion (58 runners for 2026-27)
  KXNCAAHGAME-<date><codes>  per game, one market per team ("Minnesota Duluth vs Colorado College")
(older series KXNCAAHOCKEY / KXNCAAHOCKEYGAME closed); Polymarket lists none. A college hockey game can end in a
tie, so a team market is that team's chance to win; the two sides are de-vigged together only when they add up to
more than one. Never raises: unreachable or thin returns nothing.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from oddsmarkets.common import prediction_markets as cpm

from . import data as D

logger = logging.getLogger(__name__)

TITLE_SERIES = {"mch": "KXNCAAH"}
GAME_SERIES = {"mch": "KXNCAAHGAME"}
_MON = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _date(ticker: str) -> date | None:
    m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", str(ticker or ""))
    if not m or m.group(2) not in _MON:
        return None
    try:
        return date(2000 + int(m.group(1)), _MON[m.group(2)], int(m.group(3)))
    except ValueError:
        return None


def team_mapper(store: dict):
    keys: dict[str, str] = {}
    for t, v in store["teams"].items():
        if not v.get("d1"):
            continue
        for nm in (v.get("short"), v.get("name"), (v.get("chn_slug") or "").replace("-", " ")):
            if nm:
                keys.setdefault(D.norm_name(nm), t)
                keys.setdefault(D.norm_name(re.sub(r"\bSt\.?$", "State", nm)), t)
    abbr = {str(v.get("abbr") or "").upper(): t for t, v in store["teams"].items() if v.get("d1") and v.get("abbr")}

    def m(label: str | None, code: str | None = None) -> str | None:
        n = D.norm_name(label or "")
        return keys.get(n) or keys.get(n.replace(" st", " state")) or (abbr.get(str(code or "").upper()) if code else None)
    return m


def game_markets(level: str, store: dict) -> dict[str, dict]:
    """{game id: {"p_home", "p_away", "source": "kalshi", "market"}} for games still to play."""
    series = GAME_SERIES.get(level)
    if not series:
        return {}
    try:
        evs = cpm.kalshi_events(series) or []
    except Exception:  # noqa: BLE001
        return {}
    mp = team_mapper(store)
    by_pair: dict[tuple, list] = {}
    for g in store["games"]:
        if g.get("status") != "pre":
            continue
        by_pair.setdefault(frozenset((g["home"], g["away"])), []).append(g)
    out = {}
    for ev in evs:
        ed = _date(ev.get("event_ticker"))
        q = {}
        for mk in ev.get("markets") or []:
            tid = mp(mk.get("yes_sub_title"), str(mk.get("ticker") or "").rsplit("-", 1)[-1])
            p = cpm.kalshi_price(mk)
            if tid and p is not None:
                q[tid] = p
        if len(q) < 1:
            continue
        cands = by_pair.get(frozenset(q)) if len(q) == 2 else None
        if not cands:
            continue
        if ed:
            near = [g for g in cands if abs((date.fromisoformat(g["date"][:10]) - ed).days) <= 1]
            cands = near or cands
        g = cands[0]
        h, a = g["home"], g["away"]
        ph, pa = q.get(h), q.get(a)
        tot = (ph or 0) + (pa or 0)
        if ph is not None and pa is not None and tot > 1:
            ph, pa = ph / tot, pa / tot
        out[g["id"]] = {"p_home": round(ph, 4) if ph is not None else None, "p_away": round(pa, 4) if pa is not None else None,
                        "source": "kalshi", "market": ev.get("event_ticker")}
    return out


def title_market(level: str, season: int, store: dict) -> dict | None:
    """The national-champion book: {"available", "probs" {team: p}, "quoted", "field", "reason"} (de-vigged)."""
    series = TITLE_SERIES.get(level)
    if not series:
        return None
    try:
        evs = cpm.kalshi_events(series, status=None) or []
    except Exception:  # noqa: BLE001
        return None
    ev = next((e for e in evs if str(e.get("event_ticker") or "").endswith(f"-{str(season)[2:]}")), None)
    if not ev:
        return None
    mp = team_mapper(store)
    mid, floor, unmatched = {}, 0, []
    for mk in ev.get("markets") or []:
        tid = mp(mk.get("yes_sub_title"), str(mk.get("ticker") or "").rsplit("-", 1)[-1])
        if not tid:
            unmatched.append(mk.get("yes_sub_title"))
            continue
        p = cpm.kalshi_price(mk)
        if p is not None:
            mid[tid] = p
        else:
            floor += 1
    field = len(ev.get("markets") or [])
    tot = sum(mid.values())
    if len(mid) + floor < max(4, field // 2) or not mid or not (0.8 <= tot <= 1.3):
        return {"available": False, "reason": f"thin: {len(mid)} quoted of {field}, implied total {tot:.2f}",
                "quoted": len(mid), "field": field, "market": ev.get("event_ticker")}
    probs = {t: round(p / tot, 5) for t, p in sorted(mid.items(), key=lambda kv: -kv[1])}
    return {"available": True, "probs": probs, "quoted": len(mid), "field": field, "market": ev.get("event_ticker"),
            "unmatched": unmatched[:20], "source": "kalshi"}
