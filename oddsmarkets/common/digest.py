"""The digest: "This week in <sport>" on every sport overview and "Today / This week" on the Home page. The one
implementation of these numbers, so the Home page and the overviews always agree. The game a page leads with is
the other shared module, oddsmarkets/common/featured.py (significance, rank_featured, when_label).

No look-ahead. Every piece reads only what was known at the time: a finished game's chance is the one published
BEFORE its start (the frozen walk-forward prices the sites already show on finished games), and the chance log is
a snapshot taken at each build, never a rebuilt or revised number. A caller passes only sports whose finished-game
chances are frozen that way.

The game dict is featured.py's (the Home page's normalised game, build_home.game); the fields read here are
    id, sport, league, note, start (ISO, UTC), status ("pre" | "live" | "final" | "off"), home, away (anything: an
    abbreviation, an id, a name, or a team dict with abbr / id / name), hs, as (scores), p_home, p_draw (optional,
    football), p_away (optional: 1 - p_home - p_draw), event (True for a race: skipped), and winner (optional:
    "home" | "away" | "draw", for sports whose score does not say, such as tennis sets).

    record(games, now)            our favourites this week: won against expected, with a per-sport split
    upset(games, now)             the winner we gave the lowest pre-game chance this week
    hot(games, now)               the side with the best week (most wins, then win share, then margin)
    roll_log(prev, now, chances)  the per-build chance snapshot carried forward (one a day, the last `keep` days)
    movers(log, chances, now)     the biggest risers and fallers in a chance since about a week ago
    swing(series, now)            the single biggest move in a title / playoff chance series over the week
    log_series(log, ...)          a chance log as swing() series
    window(now, days)             the ISO bounds of "this week"

A site payload stays small: a handful of keys, ids and rounded numbers. The front end words them.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

WEEK = 7


def _dt(x) -> datetime | None:
    """ISO 8601 / date / datetime -> aware UTC datetime (a bare date is midnight UTC); None when unreadable."""
    if x is None:
        return None
    if isinstance(x, datetime):
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    if isinstance(x, date):
        return datetime(x.year, x.month, x.day, tzinfo=timezone.utc)
    s = str(x).strip()
    if not s:
        return None
    try:
        if len(s) == 10:
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _now(now) -> datetime:
    return _dt(now) or datetime.now(timezone.utc)


def side_key(v):
    """A hashable key for a side: the value itself, or a team dict's abbr / id / name."""
    if isinstance(v, dict):
        for k in ("abbr", "id", "key", "name"):
            if v.get(k) is not None:
                return v[k]
        return None
    return v


def window(now, days: int = WEEK) -> tuple[str, str]:
    """(start, end) ISO strings of the `days` before `now`."""
    n = _now(now)
    return (n - timedelta(days=days)).isoformat().replace("+00:00", "Z"), n.isoformat().replace("+00:00", "Z")


def chances(g: dict) -> tuple[float, float, float] | None:
    """(home, away, draw) pre-game chances, or None without a usable p_home."""
    ph = _num(g.get("p_home"))
    if ph is None:
        return None
    pd = _num(g.get("p_draw")) or 0.0
    pa = _num(g.get("p_away"))
    if pa is None:
        pa = max(0.0, 1.0 - ph - pd)
    return ph, pa, pd


def result(g: dict) -> str | None:
    """'home' | 'away' | 'draw' for a finished game, else None. A level score counts as a draw only where a draw
    was possible (we gave it a chance); a tie elsewhere (an NFL tie) has no result here and is skipped."""
    if g.get("status") != "final" or g.get("event"):
        return None
    w = g.get("winner")
    if w in ("home", "away", "draw"):
        return w
    hs, as_ = _num(g.get("hs")), _num(g.get("as"))
    if hs is None or as_ is None:
        return None
    if hs == as_:
        c = chances(g)
        return "draw" if c and c[2] > 0 else None
    return "home" if hs > as_ else "away"


def week_finals(games: Iterable[dict], now, days: int = WEEK) -> list[dict]:
    """Finished games that started in the `days` before `now`, with a pre-game chance and a result."""
    n = _now(now)
    lo = n - timedelta(days=days)
    out = []
    for g in games or []:
        t = _dt(g.get("start"))
        if t is None or not (lo <= t <= n) or result(g) is None or chances(g) is None:
            continue
        out.append(g)
    return out


def record(games: Iterable[dict], now, days: int = WEEK, min_n: int = 3) -> dict | None:
    """Our favourites this week: {"n", "won", "expected", "expected_rate", "draws", "upsets", "from", "to", "by"}.

    The favourite is the side we gave the higher pre-game chance; a game we had dead level is left out. `won` counts
    favourites that won outright; `expected` is the sum of their chances (the wins a calibrated forecaster expects)
    and `expected_rate` its mean. A draw (football) is a favourite not winning and is counted in `draws`. `by` splits
    it by sport ({sport, n, won, expected}) for the Home page. None under `min_n` games."""
    fin = week_finals(games, now, days)
    tot = {"n": 0, "won": 0, "exp": 0.0, "draws": 0, "upsets": 0}
    by: dict = {}
    for g in fin:
        ph, pa, _ = chances(g)
        if abs(ph - pa) < 1e-9:
            continue
        fav = "home" if ph > pa else "away"
        r = result(g)
        b = by.setdefault(g.get("sport"), {"sport": g.get("sport"), "n": 0, "won": 0, "exp": 0.0})
        for t in (tot, b):
            t["n"] += 1
            t["exp"] += max(ph, pa)
            t["won"] += 1 if r == fav else 0
        if r == "draw":
            tot["draws"] += 1
        elif r != fav:
            tot["upsets"] += 1
    n = tot["n"]
    if n < min_n:
        return None
    lo, hi = window(now, days)
    return {"n": n, "won": tot["won"], "expected": round(tot["exp"], 1), "expected_rate": round(tot["exp"] / n, 4),
            "draws": tot["draws"], "upsets": tot["upsets"], "from": lo[:10], "to": hi[:10],
            "by": [{"sport": b["sport"], "n": b["n"], "won": b["won"], "expected": round(b["exp"], 1)}
                   for b in sorted(by.values(), key=lambda b: (-b["n"], str(b["sport"])))]}


def upset(games: Iterable[dict], now, days: int = WEEK, below: float = 0.4, full: bool = False) -> dict | None:
    """The winner we rated least likely this week (at `below` or less): {"id", "start", "side", "winner", "loser",
    "p", "hs", "as"} (plus "sport", "league", "note" when the game has them; `full` adds the game itself as "game"),
    or None. A draw is a surprise, not an upset winner."""
    best = None
    for g in week_finals(games, now, days):
        r = result(g)
        if r not in ("home", "away"):
            continue
        ph, pa, _ = chances(g)
        p = ph if r == "home" else pa
        if p <= below and (best is None or p < best[0]):
            best = (p, g, r)
    if not best:
        return None
    p, g, r = best
    out = {"id": g.get("id"), "start": g.get("start"), "side": r, "winner": g.get(r), "loser": g.get("away" if r == "home" else "home"),
           "p": round(p, 3), "hs": g.get("hs"), "as": g.get("as")}
    for k in ("sport", "league", "note"):
        if g.get(k):
            out[k] = g[k]
    if full:
        out["game"] = g
    return out


def hot(games: Iterable[dict], now, days: int = WEEK, min_games: int = 2) -> dict | None:
    """The side with the best week: most wins, then the best win share, then the biggest margin.
    {"key", "w", "l", "d", "gp", "margin"} (margin: points / goals / runs for minus against), or None."""
    tab: dict = {}
    for g in week_finals(games, now, days):
        r = result(g)
        hs, as_ = _num(g.get("hs")), _num(g.get("as"))
        for side in ("home", "away"):
            k = side_key(g.get(side))
            if k is None:
                continue
            t = tab.setdefault(k, {"key": k, "w": 0, "l": 0, "d": 0, "gp": 0, "margin": 0.0})
            t["gp"] += 1
            if r == side:
                t["w"] += 1
            elif r == "draw":
                t["d"] += 1
            else:
                t["l"] += 1
            if hs is not None and as_ is not None:
                t["margin"] += (hs - as_) if side == "home" else (as_ - hs)
    rows = [t for t in tab.values() if t["gp"] >= min_games and t["w"] > 0]
    if not rows:
        return None
    rows.sort(key=lambda t: (-t["w"], -(t["w"] + 0.5 * t["d"]) / t["gp"], -t["margin"], str(t["key"])))
    t = dict(rows[0])
    t["margin"] = round(t["margin"], 1)
    return t


def roll_log(prev: dict | None, now, current: dict, keep: int = 10, digits: int = 4) -> dict:
    """The chance log: {"YYYY-MM-DD": {key: p}}, one snapshot per UTC day (a later build the same day replaces it), the
    last `keep` days. `current` is this build's {key: p}; an empty current leaves the log as it was."""
    log = {d: v for d, v in ((prev or {}).items()) if isinstance(v, dict) and len(str(d)) == 10}
    day = _now(now).date().isoformat()
    cur = {str(k): round(float(v), digits) for k, v in (current or {}).items() if _num(v) is not None}
    if cur:
        log[day] = cur
    return {d: log[d] for d in sorted(log)[-keep:]}


def movers(log: dict | None, current: dict, now, days: int = WEEK, k: int = 2, min_move: float = 0.02,
           min_days: int = 1) -> dict | None:
    """The biggest risers and fallers in a chance since the snapshot nearest `days` ago (never one newer than
    `min_days`): {"since": "YYYY-MM-DD", "days", "up": [{"key", "p", "d"}], "down": [...]}; moves under `min_move`
    are left out. None without an old enough snapshot or any move that size."""
    n = _now(now).date()
    target = n - timedelta(days=days)
    old = [d for d in (log or {}) if len(str(d)) == 10 and date.fromisoformat(d) <= n - timedelta(days=min_days)]
    if not old:
        return None
    since = min(old, key=lambda d: (abs((date.fromisoformat(d) - target).days), d))
    base = log[since]
    rows = []
    for key, p in (current or {}).items():
        p, b = _num(p), _num(base.get(str(key)))
        if p is None or b is None:
            continue
        rows.append({"key": key, "p": round(p, 4), "d": round(p - b, 4)})
    up = sorted([r for r in rows if r["d"] >= min_move], key=lambda r: -r["d"])[:k]
    down = sorted([r for r in rows if r["d"] <= -min_move], key=lambda r: r["d"])[:k]
    if not up and not down:
        return None
    return {"since": since, "days": (n - date.fromisoformat(since)).days, "up": up, "down": down}


def swing(series: Iterable[dict] | None, now, days: int = WEEK, min_move: float = 0.03) -> dict | None:
    """The largest move in a title / playoff chance over the last `days` days.

    series: [{"name", "league", "kind": "title" | "playoff", "points": [[iso_ts, p], ...], "href", "sport"}]. The
    move runs from the first point at or after now - days to the latest point at or before now (`since` says when
    it starts). {"name", "league", "kind", "from", "to", "delta", "since", "href", "sport"} or None."""
    n = _now(now)
    lo = n - timedelta(days=days)
    best = None
    for s in series or []:
        pts = []
        for ts, p in s.get("points") or []:
            d, p = _dt(ts), _num(p)
            if d is not None and p is not None and d <= n:
                pts.append((d, p))
        if len(pts) < 2:
            continue
        pts.sort()
        inside = [x for x in pts if x[0] >= lo]
        if not inside or inside[0] == pts[-1]:
            continue
        first, last = inside[0], pts[-1]
        delta = last[1] - first[1]
        if abs(delta) >= min_move and (best is None or abs(delta) > abs(best["delta"])):
            best = {"name": s.get("name"), "league": s.get("league"), "kind": s.get("kind") or "title",
                    "from": round(first[1], 4), "to": round(last[1], 4), "delta": round(delta, 4),
                    "since": first[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "href": s.get("href"), "sport": s.get("sport")}
    return best


def log_series(log: dict | None, kind: str = "title", names: dict | None = None, **extra) -> list[dict]:
    """A chance log ({day: {key: p}}) as swing() series, one per key: {"name", "kind", "points", ...extra}."""
    keys: dict = {}
    for d in sorted(log or {}):
        for k, p in (log[d] or {}).items():
            keys.setdefault(k, []).append([d + "T12:00:00Z", p])
    return [dict(extra, key=k, name=(names or {}).get(k, k), kind=kind, points=pts) for k, pts in keys.items()]
