"""
Tournament simulation: each round's score of each player is round(-rating + sd * z), z standard normal, so a player
rated +2 averages two strokes a round better than an average field. After `cut_round` rounds the `cut_count` lowest
and ties play on (no cut when cut_round is 0 or the field is not over cut_count). The lowest total wins; a tie for
first is settled at random (a playoff between equals). A top-k finish counts ties (rank = 1 + players strictly ahead),
as Kalshi's top-10 markets do.
"""
from __future__ import annotations

import numpy as np

TOPS = (5, 10, 20)


def simulate(ratings: np.ndarray, sd: np.ndarray | float, rounds: int = 4, cut_round: int = 2, cut_count: int = 65,
             n: int = 20000, seed: int = 0, chunk: int = 5000) -> dict[str, np.ndarray]:
    """Per player (in input order): win, top5, top10, top20, make_cut and mean finish rank."""
    r = np.asarray(ratings, dtype=float)
    P = len(r)
    s = np.broadcast_to(np.asarray(sd, dtype=float), (P,))
    rng = np.random.default_rng(seed)
    out = {k: np.zeros(P) for k in ("win", "make_cut", "rank", *(f"top{t}" for t in TOPS))}
    cut_on = bool(cut_round) and 0 < cut_round < rounds and P > cut_count
    done = 0
    while done < n:
        m = min(chunk, n - done)
        sc = np.rint(-r[None, :, None] + s[None, :, None] * rng.standard_normal((m, P, rounds)))
        tot = sc.sum(axis=2)
        alive = np.ones((m, P), dtype=bool)
        if cut_on:
            early = sc[:, :, :cut_round].sum(axis=2)
            line = np.partition(early, cut_count - 1, axis=1)[:, cut_count - 1]
            alive = early <= line[:, None]
            tot = np.where(alive, tot, np.inf)
        best = tot.min(axis=1, keepdims=True)
        lead = tot == best
        pick = np.where(lead, rng.random((m, P)), -1.0)
        win = pick == pick.max(axis=1, keepdims=True)
        # players strictly ahead, every simulation at once: rows offset so one sorted array holds them all
        fin = np.where(alive, tot, 1e6) + (np.arange(m) * 1e7)[:, None]
        flat = np.sort(fin, axis=None)
        ahead = np.searchsorted(flat, fin.ravel(), side="left").reshape(m, P) - (np.arange(m) * P)[:, None]
        rank = np.where(alive, ahead + 1, P)
        out["win"] += win.sum(axis=0)
        out["make_cut"] += alive.sum(axis=0)
        out["rank"] += rank.sum(axis=0)
        for t in TOPS:
            out[f"top{t}"] += ((rank <= t) & alive).sum(axis=0)
        done += m
    return {k: v / n for k, v in out.items()}


def simulate_live(ratings: np.ndarray, sd: float, base: np.ndarray, to_cut: np.ndarray, after_cut: np.ndarray,
                  playing: np.ndarray, cut_count: int = 0, field_par: float = 0.0, n: int = 20000, seed: int = 0,
                  chunk: int = 5000) -> dict[str, np.ndarray]:
    """An event under way, from each player's score so far.

    base: strokes to par so far (holes played); to_cut / after_cut: rounds still to play before and after the cut, in
    eighteenths (a player thru 9 of round 2 has 0.5 to the cut); playing: False for a player who missed the cut or
    withdrew; cut_count 0 when the cut is made or there is none; field_par: the event's average field round to par so
    far. The rest of a player's event is normal with mean (field_par - rating) and sd * sqrt(rounds) per piece,
    totals rounded to whole strokes."""
    r = np.asarray(ratings, dtype=float)
    P = len(r)
    b, f1, f2 = (np.asarray(x, dtype=float) for x in (base, to_cut, after_cut))
    on = np.asarray(playing, dtype=bool)
    rng = np.random.default_rng(seed)
    out = {k: np.zeros(P) for k in ("win", "make_cut", "rank", *(f"top{t}" for t in TOPS))}
    cut_on = cut_count > 0 and on.sum() > cut_count
    done = 0
    while done < n:
        m = min(chunk, n - done)
        z = rng.standard_normal((2, m, P))
        early = b + (field_par - r) * f1 + sd * np.sqrt(f1) * z[0]
        alive = np.broadcast_to(on, (m, P)).copy()
        if cut_on:
            e = np.rint(np.where(on, early, np.inf))
            line = np.partition(e, cut_count - 1, axis=1)[:, cut_count - 1]
            alive &= e <= line[:, None]
        tot = np.rint(early + (field_par - r) * f2 + sd * np.sqrt(f2) * z[1])
        tot = np.where(alive, tot, np.inf)
        best = tot.min(axis=1, keepdims=True)
        lead = tot == best
        pick = np.where(lead, rng.random((m, P)), -1.0)
        win = pick == pick.max(axis=1, keepdims=True)
        fin = np.where(alive, tot, 1e6) + (np.arange(m) * 1e7)[:, None]
        flat = np.sort(fin, axis=None)
        ahead = np.searchsorted(flat, fin.ravel(), side="left").reshape(m, P) - (np.arange(m) * P)[:, None]
        rank = np.where(alive, ahead + 1, P)
        out["win"] += win.sum(axis=0)
        out["make_cut"] += alive.sum(axis=0)
        out["rank"] += rank.sum(axis=0)
        for t in TOPS:
            out[f"top{t}"] += ((rank <= t) & alive).sum(axis=0)
        done += m
    return {k: v / n for k, v in out.items()}
