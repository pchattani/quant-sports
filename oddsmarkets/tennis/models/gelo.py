"""
Game-share Elo: a margin-of-victory rating from the share of games won (docs/research/tennis_edge.md, E3).

Each player carries an overall rating and one per surface (hard, clay, grass; carpet folds into hard), on the logit
scale of the share of games won. Before a match on surface S between i and j:

    m_i   = w * G_i,S + (1 - w) * G_i,all                     surface blend
    diff  = m_i - m_j                                         the feature the match price uses (predict.py)

After it (completed sets of done, retired and defaulted matches; walkovers and unplayed matches skip):

    share = (games_i + 0.5) / (games + 1)
    g     = (1 for done, 0.5 for ret / def) * min(1, games / 18)
    k     = K * g * (1 + 3 / (1 + min(n_i, n_j) / 20))        faster while either player is new
    G_i,X += 4 k (share - sigmoid(G_i,X - G_j,X)),  G_j,X -= the same,   X in {all, S}

A player's first rating is 0 on all four. A pair where either player has never been rated gets diff = 0 (no
information), exactly as the research features did, so the fitted weight transfers. K and w per tour were chosen on
the dev years 2012-2017 only (grid K in {0.06, 0.12, 0.24} x w in {0.2, 0.4, 0.6}); the test years 2018-2025 gave
-0.0024 (ATP) and -0.0045 (WTA) log-loss against the production blend with 95 % CIs excluding zero.

`history(tour, matches=None)` -> {"cols","rows","params","current"} (rows per rated match with games played: id, date, p1, p2,
surface, pre-match diff, the post-match overall and surface ratings of both, the match counts);
`ratings_at(hist, date)`; `diff(r1, r2, surface, params)`; `pre_match(hist)` -> {match id: diff for p1}.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from oddsmarkets.tennis.models import _io

VERSION = 1
PARAMS = {"atp": {"k": 0.06, "w_surf": 0.4}, "wta": {"k": 0.12, "w_surf": 0.2}}
SURF = {"hard": 1, "clay": 2, "grass": 3}
COLS = ["id", "date", "p1", "p2", "surface", "pre_diff", "all1", "srf1", "all2", "srf2", "n1", "n2"]


def params(tour: str) -> dict:
    return dict(PARAMS[_io.tour_key(tour)])


def _games(sets) -> tuple[int, int]:
    g1 = g2 = 0
    for s in sets or []:
        try:
            a, b = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        g1 += a
        g2 += b
    return g1, g2


def compute(matches: Iterable[dict], prm: dict) -> dict:
    """Run over MATCH rows in the order given (callers pass them sorted by date, round, id)."""
    K, w = float(prm["k"]), float(prm["w_surf"])
    R: dict[str, list] = {}
    rows = []
    for m in matches:
        st = m.get("status")
        if st not in _io.RATED_STATUS:
            continue
        p1, p2 = m.get("p1"), m.get("p2")
        d = _io.day(m.get("date"))
        if not p1 or not p2 or p1 == p2 or d is None:
            continue
        p1, p2 = str(p1), str(p2)
        s = SURF[_io.fold_surface(m.get("surface"))]
        r1, r2 = R.get(p1), R.get(p2)
        pre = (w * r1[s] + (1 - w) * r1[0]) - (w * r2[s] + (1 - w) * r2[0]) if (r1 and r2) else 0.0
        g1, g2 = _games(m.get("sets"))
        gp = g1 + g2
        if gp > 0:
            r1 = R.setdefault(p1, [0.0, 0.0, 0.0, 0.0, 0])
            r2 = R.setdefault(p2, [0.0, 0.0, 0.0, 0.0, 0])
            share = (g1 + 0.5) / (gp + 1.0)
            g = (1.0 if st == "done" else 0.5) * min(1.0, gp / 18.0)
            k = K * g * (1.0 + 3.0 / (1.0 + min(r1[4], r2[4]) / 20.0))
            for x in (0, s):
                e = 1.0 / (1.0 + math.exp(-(r1[x] - r2[x])))
                r1[x] += 4.0 * k * (share - e)
                r2[x] -= 4.0 * k * (share - e)
            r1[4] += 1
            r2[4] += 1
        if gp > 0:
            rows.append([m.get("id"), d.isoformat(), p1, p2, ("hard", "clay", "grass")[s - 1], round(pre, 5),
                         round(r1[0], 5), round(r1[s], 5), round(r2[0], 5), round(r2[s], 5), r1[4], r2[4]])
    cur = {pid: {"all": round(x[0], 5), "hard": round(x[1], 5), "clay": round(x[2], 5), "grass": round(x[3], 5),
                 "n": x[4]} for pid, x in R.items()}
    return {"version": VERSION, "cols": COLS, "rows": rows, "params": dict(prm), "current": cur}


def history(tour: str, matches: list[dict] | None = None, use_cache: bool = True) -> dict:
    t = _io.tour_key(tour)
    p = params(t)
    if matches is not None:
        return compute(matches, p)
    key = _io.file_key(VERSION, _io.signature(t), p)
    return _io.cached("gelo", t, key, lambda: dict(compute(_io.load_matches(t), p), tour=t), use_cache)


def ratings_at(hist: dict, when: Any) -> dict[str, dict]:
    """Each player's game-share ratings before day `when` (no inactivity pull)."""
    d = _io.day(when)
    ds = d.isoformat() if d else "9999-12-31"
    out: dict[str, dict] = {}
    for g in hist.get("rows") or []:
        if g[1] >= ds:
            break
        for pid, ai, si, n in ((g[2], 6, 7, g[10]), (g[3], 8, 9, g[11])):
            rec = out.get(pid)
            if rec is None:
                rec = out[pid] = {"all": 0.0, "hard": 0.0, "clay": 0.0, "grass": 0.0, "n": 0}
            rec["all"] = g[ai]
            rec[g[4]] = g[si]
            rec["n"] = n
    return out


def diff(r1: dict | None, r2: dict | None, surface: str = "hard", prm: dict | None = None) -> float:
    """Blended rating difference of player 1 over player 2; 0 when either has never been rated."""
    if not r1 or not r2:
        return 0.0
    w = float((prm or PARAMS["atp"])["w_surf"])
    s = _io.fold_surface(surface)
    m1 = w * float(r1.get(s, 0.0)) + (1 - w) * float(r1.get("all", 0.0))
    m2 = w * float(r2.get(s, 0.0)) + (1 - w) * float(r2.get("all", 0.0))
    return m1 - m2


def pre_match(hist: dict) -> dict[str, float]:
    """{match id: pre-match diff for the row's p1} (rated matches with games; others price with diff from
    ratings_at)."""
    return {g[0]: g[5] for g in hist.get("rows") or []}
