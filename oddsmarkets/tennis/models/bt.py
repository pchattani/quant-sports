"""
Time-decayed Bradley-Terry baseline (the calibration page's simple cross-check).

Each completed match is a two-item Plackett-Luce order [winner, loser] (Bradley-Terry for pairs) fitted
with `oddsmarkets.common.ranking.fit_strengths`: P(i beats j) = 1 / (1 + exp(theta_j - theta_i)),
weights w = 0.5 ** (age_days / half_life_days), ridge prior theta ~ N(0, 1/ridge). Optional surface
filter; retirements and walkovers are excluded. Unknown players take the mean of players with few matches.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from oddsmarkets.common.ranking import fit_strengths
from oddsmarkets.tennis.models import _io

VERSION = 1
DEFAULTS = {"half_life_days": 365.0, "ridge": 0.5, "window_days": 1460}


def fit(matches: Iterable[dict], through: Any = None, half_life_days: float | None = None, ridge: float | None = None,
        surface: str | None = None, window_days: float | None = None) -> dict:
    """{"version", "through", "players": {pid: {"theta", "n"}}, "new", "constants"}."""
    hl = float(half_life_days or DEFAULTS["half_life_days"])
    lam = float(DEFAULTS["ridge"] if ridge is None else ridge)
    wd = float(window_days or max(DEFAULTS["window_days"], 4 * hl))
    rows = []
    for m in matches:
        if m.get("status") != "done" or not m.get("p1") or not m.get("p2") or m["p1"] == m["p2"]:
            continue
        d = _io.day(m.get("date"))
        if d is None:
            continue
        if surface and _io.fold_surface(m.get("surface")) != _io.fold_surface(surface):
            continue
        rows.append((d, m["p1"], m["p2"]))
    th = _io.day(through) if through is not None else (max(r[0] for r in rows) if rows else None)
    rows = [r for r in rows if th is not None and r[0] <= th and (th - r[0]).days <= wd]
    consts = {"half_life_days": hl, "ridge": lam, "window_days": wd, "surface": surface}
    if not rows:
        return {"version": VERSION, "through": th.isoformat() if th else None, "players": {}, "new": 0.0,
                "constants": consts}
    orders = [[w, l] for _, w, l in rows]
    weights = [0.5 ** ((th - d).days / hl) for d, _, _ in rows]
    theta = fit_strengths(orders, weights=weights, ridge=lam)
    n: dict[str, int] = {}
    for _, w, l in rows:
        n[w] = n.get(w, 0) + 1
        n[l] = n.get(l, 0) + 1
    few = [theta[p] for p, k in n.items() if k <= 5]
    return {"version": VERSION, "through": th.isoformat(), "constants": consts,
            "new": float(sum(few) / len(few)) if few else 0.0,
            "players": {p: {"theta": float(v), "n": n.get(p, 0)} for p, v in theta.items()}}


def p_win(model: dict, p1: str, p2: str) -> float:
    pl = model.get("players") or {}
    new = float(model.get("new", 0.0))
    a = (pl.get(p1) or {}).get("theta", new)
    b = (pl.get(p2) or {}).get("theta", new)
    return 1.0 / (1.0 + math.exp(b - a))


def for_tour(tour: str, through: Any = None, use_cache: bool = True) -> dict:
    t = _io.tour_key(tour)
    th = _io.day(through)
    key = _io.file_key(VERSION, _io.signature(t), str(th), DEFAULTS)
    return _io.cached("bt", f"{t}_{th or 'latest'}", key, lambda: fit(_io.load_matches(t, through=th), th), use_cache)
