"""
Pre-game availability from Kalshi's player-points markets (round 3, 22 October 2026; docs/research/basketball_edge.md,
section "Availability from Kalshi player props").

ESPN keeps no injury-report history, and the official NBA / WNBA injury reports and the archived ESPN / CBS injury
pages are closed by their terms (docs/research/data_sources.md). Kalshi's player-points ladders (KXNBAPTS from
late November 2025, KXWNBAPTS from August 2026) are public, timestamped and allowed. Kalshi lists a ladder for most
of each team's leading scorers about a day before tip-off and rarely lists a player already ruled out, so "is there a
market for this player at the decision time, and is it still bid" is an honest, timestamped availability signal.
Pre-registered test (NBA 2026 from 1 Feb): no gain (-0.0001 [-0.0035, +0.0039]); not promoted.

Inputs (scripts/bb_kalshi_history.py --series KXNBAPTS KXWNBAPTS --props, cached under
data/basketball/cache/kalshi/<series>/): the listing (markets.json: ticker, event, title, open_time, close_time,
floor_strike) and hourly candles of the lowest strike of each player in each game (candles/<event>.json).

`game_listings(league, season)` -> per game and team, each listed player's ESPN id, listing time and candles;
`state_at(rows, T)` -> per player at the decision time T: listed (open_time <= T), the yes bid / ask of the last
candle ending at or before T, quoted (an ask below 1). research/props_eval.py builds the per-player table, the
P(plays) rule (`overrides`; its rates are estimated on the development slice only) and the scores.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.sources.markets import CODE_ALIASES

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "basketball" / "cache" / "kalshi"
SERIES = {"nba": "KXNBAPTS", "wnba": "KXWNBAPTS"}
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


def _ts(s) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _title_name(title) -> str:
    """'Draymond Green: 10+ points' or 'Julius Randle records 15+ points' -> the player's name."""
    s = str(title or "")
    s = re.split(r":| records ", s, maxsplit=1)[0]
    return s.strip()


def listing(league: str) -> dict[str, list[dict]]:
    """{event_ticker: [lowest-strike market per player: {ticker, name, team_code, open_ts, close_ts}]}."""
    p = CACHE / SERIES[league] / "markets.json"
    if not p.exists():
        return {}
    low: dict[tuple[str, str], dict] = {}
    for m in json.loads(p.read_text()):
        ev, tk = m["event_ticker"], m["ticker"]
        code = tk[len(ev) + 1:].rsplit("-", 1)[0]
        k = (ev, code)
        if k not in low or float(m.get("floor_strike") or 1e9) < float(low[k].get("floor_strike") or 1e9):
            low[k] = m
    out: dict[str, list[dict]] = defaultdict(list)
    for (ev, code), m in low.items():
        out[ev].append({"ticker": m["ticker"], "name": _title_name(m.get("title")), "code": code,
                        "open_ts": _ts(m.get("open_time")), "close_ts": _ts(m.get("close_time"))})
    return dict(out)


def candles(league: str, event: str) -> dict[str, list[dict]]:
    p = CACHE / SERIES[league] / "candles" / f"{event}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def quote_at(cs: list[dict], ts: float) -> dict | None:
    """The last hourly candle ending at or before ts: {"bid", "ask", "end"} (None when there is none)."""
    best = None
    for c in cs:
        e = c.get("end_period_ts") or 0
        if e <= ts and (best is None or e > best["end"]):
            best = {"bid": _f((c.get("yes_bid") or {}).get("close")), "ask": _f((c.get("yes_ask") or {}).get("close")),
                    "end": e}
    return best


def _event_key(league: str, ev: str) -> tuple | None:
    m = re.match(rf"{SERIES[league]}-(\d\d)([A-Z]{{3}})(\d\d)([A-Z]+)$", ev)
    if not m:
        return None
    yy, mon, dd, codes = m.groups()
    return datetime(2000 + int(yy), MONTHS[mon], int(dd)).date(), codes


def match_events(league: str, store: dict, events: dict) -> dict[str, tuple[str, dict]]:
    """{event_ticker: (game_id, {kalshi team code: team_id})} for the store's games."""
    alias = CODE_ALIASES[league]
    abbr = {t: str(v.get("abbr") or "").upper() for t, v in (store.get("teams") or {}).items()}
    by_pair: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for gid, g in (store.get("games") or {}).items():
        if g.get("stype") not in G.COUNTED:
            continue
        d = G.local_day(g)
        by_pair[(abbr.get(str(g["away"])), abbr.get(str(g["home"])))].append((d, gid, g))
    out = {}
    for ev in events:
        k = _event_key(league, ev)
        if not k:
            continue
        day, codes = k
        for i in range(2, len(codes) - 1):
            a, h = codes[:i], codes[i:]
            for d, gid, g in by_pair.get((alias.get(a, a), alias.get(h, h)), []):
                if d is not None and abs((d - day).days) <= 1:
                    out[ev] = (gid, {a: str(g["away"]), h: str(g["home"])})
    return out


def _team_of_market(m: dict, codes: dict[str, str]) -> str | None:
    for c, t in sorted(codes.items(), key=lambda kv: -len(kv[0])):
        if m["code"].startswith(c):
            return t
    return None


def game_listings(league: str, season: int, store: dict | None = None) -> dict[str, dict[str, list[dict]]]:
    """{game_id: {team_id: [{"pid", "name", "open_ts", "candles"}]}} for the season's games with a Kalshi event;
    pid is the ESPN player id matched by name within the team (None when no match)."""
    st = store if store is not None else (G.load_store(league, season) or {})
    evs = listing(league)
    matched = match_events(league, st, evs)
    names: dict[str, dict[str, str]] = defaultdict(dict)                 # team -> folded name -> pid
    for pid, p in (st.get("players") or {}).items():
        for t in p.get("teams") or []:
            names[str(t)][fold(p.get("name") or "")] = str(pid)
    by_name_any = {fold(p.get("name") or ""): str(pid) for pid, p in (st.get("players") or {}).items()}
    out: dict[str, dict[str, list[dict]]] = {}
    for ev, (gid, codes) in matched.items():
        cs = candles(league, ev)
        rec: dict[str, list[dict]] = defaultdict(list)
        for m in evs[ev]:
            t = _team_of_market(m, codes)
            if t is None:
                continue
            f = fold(m["name"])
            pid = names[t].get(f) or by_name_any.get(f)
            rec[t].append({"pid": pid, "name": m["name"], "open_ts": m["open_ts"], "candles": cs.get(m["ticker"]),
                           "ticker": m["ticker"]})
        out[gid] = dict(rec)
    return out


def tip_ts(g: dict) -> float | None:
    return _ts(g.get("date"))


def decision_ts(g: dict, kind: str = "tip-1h") -> float | None:
    """T: one hour before tip-off ("tip-1h") or 08:00 US Eastern on the game's US day ("08et"; EST/EDT by month,
    the same rule as the research tables)."""
    t = tip_ts(g)
    if t is None:
        return None
    if kind == "tip-1h":
        return t - 3600
    d = G.local_day(g)
    off = 4 if 3 <= d.month <= 10 else 5
    return datetime(d.year, d.month, d.day, 8 + off, tzinfo=timezone.utc).timestamp()


def state_at(rows: list[dict], T: float) -> dict[str, dict]:
    """{pid: {"listed", "quoted", "ask", "bid"}} for the team's markets at T."""
    out = {}
    for r in rows:
        if not r.get("pid"):
            continue
        listed = r["open_ts"] is not None and r["open_ts"] <= T
        q = quote_at(r.get("candles") or [], T) if listed else None
        ask = q["ask"] if q else None
        out[r["pid"]] = {"listed": listed, "ask": ask, "bid": q["bid"] if q else None,
                         "quoted": bool(listed and ask is not None and ask < 0.995)}
    return out
