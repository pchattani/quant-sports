"""
Synthetic tennis for tests and validation: point-by-point simulation of matches from planted
serve/return strengths, emitted as contract MATCH rows (p1 = winner, sets from p1's view, tiebreak
points, and WTA-style STATS totals).
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from oddsmarkets.tennis.models.serve_return import point_prob_from_hold


def _game(p: float, rng) -> tuple[bool, int, int]:
    """(server won, points won by server, points played)."""
    a = b = 0
    while True:
        if rng.random() < p:
            a += 1
        else:
            b += 1
        if a >= 4 and a - b >= 2:
            return True, a, a + b
        if b >= 4 and b - a >= 2:
            return False, a, a + b


def _tiebreak(pa: float, pb: float, a_first: bool, to: int, rng, acc) -> tuple[bool, int, int]:
    a = b = 0
    k = 0
    while True:
        a_srv = (((k + 1) // 2) % 2 == 0) == a_first
        if a_srv:
            acc[0][1] += 1
            if rng.random() < pa:
                a += 1
                acc[0][0] += 1
            else:
                b += 1
        else:
            acc[1][1] += 1
            if rng.random() < pb:
                b += 1
                acc[1][0] += 1
            else:
                a += 1
        k += 1
        if a >= to and a - b >= 2:
            return True, a, b
        if b >= to and b - a >= 2:
            return False, a, b


def simulate_match(pa: float, pb: float, best_of: int = 3, final_set_rule: str = "tb7", rng=None,
                   a_first: bool | None = None) -> dict:
    """One match between A (serve-point probability pa) and B (pb). Returns {"a_won", "sets"
    (A's view, [g1, g2, tb1, tb2]), "stats": [[pts won on serve, serve pts, service games, breaks] for A, B]}."""
    rng = rng or np.random.default_rng()
    a_srv = bool(rng.random() < 0.5) if a_first is None else bool(a_first)
    need = best_of // 2 + 1
    sa = sb = 0
    sets = []
    acc = [[0, 0, 0, 0], [0, 0, 0, 0]]
    while sa < need and sb < need:
        deciding = sa == need - 1 and sb == need - 1
        rule = final_set_rule if deciding else "tb7"
        ga = gb = 0
        set_first = a_srv
        tb = None
        while True:
            if ga == gb and ((ga == 6 and rule in ("tb7", "tb10")) or (ga == 12 and rule == "tb7@12")):
                to = 10 if rule == "tb10" else 7
                won, x, y = _tiebreak(pa, pb, a_srv, to, rng, acc)
                tb = (x, y)
                if won:
                    ga += 1
                else:
                    gb += 1
                a_srv = not a_srv
                break
            who = 0 if a_srv else 1
            held, w, n = _game(pa if a_srv else pb, rng)
            acc[who][0] += w
            acc[who][1] += n
            acc[who][2] += 1
            if not held:
                acc[who][3] += 1
            if held == a_srv:
                ga += 1
            else:
                gb += 1
            a_srv = not a_srv
            if (ga >= 6 or gb >= 6) and abs(ga - gb) >= 2:
                break
        sets.append([ga, gb, tb[0] if tb else None, tb[1] if tb else None])
        if ga > gb:
            sa += 1
        else:
            sb += 1
        del set_first
    return {"a_won": sa > sb, "sets": sets, "stats": acc}


def make_tour(n_players: int = 60, n_matches: int = 3000, seed: int = 0, start: date = date(2018, 1, 1),
              days: int = 730, mu: float = 1.0, sd_s: float = 0.45, sd_r: float = 0.45, sd_delta: float = 0.0,
              bo5_share: float = 0.0, with_stats: bool = True, surfaces=("hard", "clay", "grass"),
              surface_p=(0.55, 0.3, 0.15)) -> tuple[list[dict], dict]:
    """Planted s, r (and optional per-surface deltas) for `n_players`; `n_matches` simulated matches
    between random pairs. Returns (MATCH rows, truth {"s","r","ds","dr","mu","pids"})."""
    rng = np.random.default_rng(seed)
    pids = [f"x:p{i:03d}" for i in range(n_players)]
    s = rng.normal(0, sd_s, n_players)
    r = rng.normal(0, sd_r, n_players)
    ds = rng.normal(0, sd_delta, (n_players, 3)) if sd_delta > 0 else np.zeros((n_players, 3))
    dr = rng.normal(0, sd_delta, (n_players, 3)) if sd_delta > 0 else np.zeros((n_players, 3))
    out = []
    for k in range(n_matches):
        i, j = rng.choice(n_players, 2, replace=False)
        si = int(rng.choice(len(surfaces), p=surface_p))
        surf = surfaces[si]
        bo = 5 if rng.random() < bo5_share else 3
        hA = 1 / (1 + math.exp(-(mu + s[i] + ds[i, si] - r[j] - dr[j, si])))
        hB = 1 / (1 + math.exp(-(mu + s[j] + ds[j, si] - r[i] - dr[i, si])))
        pa, pb = float(point_prob_from_hold(hA)), float(point_prob_from_hold(hB))
        res = simulate_match(pa, pb, bo, "tb7", rng)
        d = start + timedelta(days=int(k * days / n_matches))
        st = res["stats"]
        if res["a_won"]:
            p1, p2, sets, s1, s2 = pids[i], pids[j], res["sets"], st[0], st[1]
        else:
            p1, p2, s2, s1 = pids[j], pids[i], st[0], st[1]
            sets = [[b, a, tb, ta] for a, b, ta, tb in res["sets"]]

        def stats(x):
            return {"aces": None, "dfs": None, "sv_pts": x[1], "fs_in": None, "fs_won": x[0], "ss_won": 0,
                    "sv_gms": x[2], "bp_saved": 0, "bp_faced": x[3], "rt_pts_won": None, "bp_conv": None,
                    "bp_opps": None, "_breaks": x[3]}

        out.append({"id": f"syn-{k}", "event": f"syn-{d.year}", "date": d.isoformat(), "round": "R32", "best_of": bo,
                    "surface": surf, "indoor": False, "level": "250", "p1": p1, "p2": p2, "winner": p1,
                    "status": "done", "sets": sets, "final_set_rule": "tb7", "rank1": None, "rank2": None,
                    "stats": {"p1": stats(s1), "p2": stats(s2), "by_set": []} if with_stats else None})
    truth = {"s": dict(zip(pids, s)), "r": dict(zip(pids, r)), "ds": dict(zip(pids, ds.tolist())),
             "dr": dict(zip(pids, dr.tolist())), "mu": mu, "pids": pids}
    return out, truth
