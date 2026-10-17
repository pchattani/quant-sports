"""
Exact Markov chain for a tennis singles match: point -> game -> tiebreak -> set -> match.

Inputs are the two serve-point win probabilities: `p1` = P(player 1 wins a point on his serve),
`p2` = P(player 2 wins a point on her serve). Points are independent and identically distributed
within a player's service games (the standard i.i.d. model; Newton & Keller 2005, Barnett & Clarke).
Every function takes scalars or numpy arrays (one entry per match) and is exact, not simulated.

Game (server wins a point with p, q = 1 - p)
    P(hold) = p^4 (1 + 4q + 10q^2) + 20 p^3 q^3 * p^2 / (1 - 2pq)          p = 0.6 -> 0.7357
    from any point score: backward recursion on 0..3 x 0..3 with deuce D = p^2 / (p^2 + q^2).

Tiebreak (first to `to` points, win by two; 7, or 10 for a match tiebreak)
    Point k (0-based) is served by the tiebreak's first server when ((k + 1) // 2) is even, so service
    alternates after the first point and then every two points. From any tie at to-1 or beyond, the
    next two points are served one each, so P(win from tie) = x / (x + y) with x = p1 (1 - p2),
    y = (1 - p1) p2.

Set (games alternate serve; `first_server` 0 = player 1 serves the set's first game, 1 = player 2)
    rule "tb7"  : a tiebreak to 7 at 6-6 (every non-deciding set; the deciding set before the Slam changes)
    rule "tb10" : a tiebreak to 10 at 6-6 (deciding sets at the Slams from 2022)
    rule "tb12" : a tiebreak to 7 at 12-12 (Wimbledon deciding sets 2019-2021)
    rule "adv"  : no tiebreak, play on until two games clear
A set that went to a tiebreak is scored 7-6 (13-12 for "tb12") and counts 13 (25) games. Advantage
sets are followed exactly up to CAP-CAP games; from that tie the rest of the set is collapsed onto
(CAP+2)-CAP / CAP-(CAP+2) with the exact win probability, so P(win) is exact and only the total-games
tail beyond 2*CAP games is approximate.

Match (best of 3 or 5; the deciding set uses `final_set_rule`, earlier sets "tb7")
    The first server of each set is the player due to serve the next game, i.e. it changes when the
    previous set had an odd number of games (a tiebreak counts as one game). Before the match the
    first server is unknown and both orders are averaged (the coin toss), unless `first_server` is
    given. The forward pass carries, for each (sets won, next first server) state, the full
    distributions of total games and of the game margin, and the mass of paths without a tiebreak.

Live states: `state` = {"sets": [s1, s2], "games": [g1, g2], "points": [a, b] | None, "server": 0|1|None,
"played": [[g1, g2], ...] | None}. Points are player 1's and player 2's points in the current game
(0, 1, 2, 3, 4... or "0", "15", "30", "40", "AD"), or the tiebreak points when the games are at the
tiebreak score. `server` is who serves the current game (unknown -> both averaged). With "played"
(completed sets' games) the total-games and handicap distributions include the games already played;
without it they cover the current and future sets only.

`LiveTable` gives the same win probability by backward recursion in O(1) per state, for win-probability
paths (live.py); it agrees with `match(..., state=...)` exactly.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

CAP = 30                                       # advantage-set games followed exactly per player
RULES = {"tb7": (6, 7), "tb10": (6, 10), "tb12": (12, 7), "tb7@12": (12, 7), "adv": (None, None)}
POINT_LABELS = {"0": 0, "00": 0, "love": 0, "15": 1, "30": 2, "40": 3, "a": 4, "ad": 4, "adv": 4, "an": 4}


def _arr(x) -> np.ndarray:
    return np.atleast_1d(np.asarray(x, float))


def _rule(rule: str | None) -> tuple:
    return RULES.get(str(rule or "tb7").lower(), RULES["tb7"])


def parse_points(points) -> tuple[int, int] | None:
    """(a, b) point counts from numbers or tennis labels ("15", "40", "AD"); None when absent."""
    if points is None:
        return None
    try:
        a, b = points
    except (TypeError, ValueError):
        return None

    def one(x):
        if x is None:
            return 0
        if isinstance(x, (int, np.integer)):
            return int(x)
        s = str(x).strip().lower()
        if s in POINT_LABELS:
            return POINT_LABELS[s]
        try:
            return int(float(s))
        except ValueError:
            return 0
    a, b = one(a), one(b)
    # "40-AD" style labels: AD = 4 against 40 = 3 is already right; "AD" against 40 normalises below
    return a, b


# ── game ─────────────────────────────────────────────────────────────────────

def game_win(p):
    """P(the server holds) for serve-point probability p (closed form)."""
    p = np.asarray(p, float)
    q = 1.0 - p
    return p ** 4 * (1 + 4 * q + 10 * q ** 2) + 20 * p ** 3 * q ** 3 * p ** 2 / (1 - 2 * p * q)


def game_from(p, a: int = 0, b: int = 0):
    """P(the server wins the game) from the server's `a` points and the returner's `b` points."""
    p = np.asarray(p, float)
    q = 1.0 - p
    D = p * p / (p * p + q * q)
    one, zero = np.ones_like(p), np.zeros_like(p)
    a, b = int(a), int(b)
    if a >= 3 and b >= 3:
        if a == b:
            return D
        if a == b + 1:
            return p + q * D
        if b == a + 1:
            return p * D
        return one if a > b else zero
    if a >= 4:
        return one
    if b >= 4:
        return zero
    V: dict = {}
    for i in range(3, -1, -1):
        for j in range(3, -1, -1):
            if i == 3 and j == 3:
                V[(i, j)] = D
                continue
            w = one if i + 1 >= 4 else V[(i + 1, j)]
            l = zero if j + 1 >= 4 else V[(i, j + 1)]
            V[(i, j)] = p * w + q * l
    return V[(a, b)]


def _game_p1(pA, pB, server: int, points):
    """P(player 1 wins the current game) given the server and (player 1, player 2) points."""
    a, b = points or (0, 0)
    if server == 0:
        return game_from(pA, a, b) if (a or b) else game_win(pA)
    return 1.0 - (game_from(pB, b, a) if (a or b) else game_win(pB))


# ── tiebreak ─────────────────────────────────────────────────────────────────

def tiebreak_win(p1, p2, to: int = 7, first_server: int = 0, points=(0, 0)):
    """P(player 1 wins a tiebreak to `to` (win by two) from (player 1, player 2) points."""
    pA, pB = np.broadcast_arrays(np.asarray(p1, float), np.asarray(p2, float))
    x, y = pA * (1 - pB), (1 - pA) * pB
    T = x / np.maximum(x + y, 1e-300)
    fs = int(first_server)
    a0, b0 = points or (0, 0)
    a0, b0 = int(a0), int(b0)

    def pw(k):
        srv = fs if ((k + 1) // 2) % 2 == 0 else 1 - fs
        return pA if srv == 0 else 1.0 - pB

    def closed(i, j):
        """Value at a terminal or extended (both >= to - 1) score, else None."""
        if i >= to and i - j >= 2:
            return np.ones_like(pA)
        if j >= to and j - i >= 2:
            return np.zeros_like(pA)
        if i >= to - 1 and j >= to - 1:
            if i == j:
                return T
            q = pw(i + j)
            return q + (1 - q) * T if i == j + 1 else q * T
        return None

    c = closed(a0, b0)
    if c is not None:
        return c
    # iterative backward pass over the lattice below (to - 1, to - 1); no recursive closure (no reference cycle)
    V: dict = {}
    for i in range(to, a0 - 1, -1):
        for j in range(to, b0 - 1, -1):
            c = closed(i, j)
            if c is not None:
                V[(i, j)] = c
                continue
            q = pw(i + j)
            V[(i, j)] = q * V[(i + 1, j)] + (1 - q) * V[(i, j + 1)]
    return V[(a0, b0)]


# ── set ──────────────────────────────────────────────────────────────────────

def _terminal(g1: int, g2: int, tb_at) -> bool:
    hi, lo = max(g1, g2), min(g1, g2)
    if hi >= 6 and hi - lo >= 2:
        return True
    return tb_at is not None and hi == tb_at + 1 and lo == tb_at


def is_tiebreak_score(g1: int, g2: int, rule: str = "tb7") -> bool:
    tb_at, _ = _rule(rule)
    return tb_at is not None and max(g1, g2) == tb_at + 1 and min(g1, g2) == tb_at


def set_dist(p1, p2, first_server: int = 0, rule: str = "tb7", start=(0, 0), points=None, cap: int = CAP) -> dict:
    """
    {(g1, g2): P} over final set scores (player 1's games first), exact. `first_server` serves the
    set's first game (0 = player 1); with `start` the set is already at that games score (the server of
    game g1+g2 follows from `first_server`) and `points` is the current game's (or tiebreak's) score.
    Values are arrays when p1/p2 are arrays.
    """
    pA, pB = np.broadcast_arrays(_arr(p1), _arr(p2))
    hA, hB = game_win(pA), game_win(pB)
    tb_at, tb_to = _rule(rule)
    fs = int(first_server)
    g0 = (int(start[0]), int(start[1]))
    cap = max(int(cap), max(g0) + 1)
    pts = parse_points(points)
    out: dict = {}
    mass = {g0: np.ones_like(pA)}
    t = g0[0] + g0[1]
    while mass:
        cur = [k for k in mass if k[0] + k[1] == t]
        for k in cur:
            m = mass.pop(k)
            g1, g2 = k
            if _terminal(g1, g2, tb_at):
                out[k] = out.get(k, 0.0) + m
                continue
            srv = fs if (g1 + g2) % 2 == 0 else 1 - fs
            here = pts if k == g0 else None
            if tb_at is not None and g1 == g2 == tb_at:
                w = tiebreak_win(pA, pB, tb_to, srv, here or (0, 0))
                out[(g1 + 1, g2)] = out.get((g1 + 1, g2), 0.0) + m * w
                out[(g1, g2 + 1)] = out.get((g1, g2 + 1), 0.0) + m * (1 - w)
                continue
            if tb_at is None and g1 == g2 and g1 >= cap and not here:
                x, y = hA * (1 - hB), (1 - hA) * hB
                w = x / np.maximum(x + y, 1e-300)
                out[(g1 + 2, g2)] = out.get((g1 + 2, g2), 0.0) + m * w
                out[(g1, g2 + 2)] = out.get((g1, g2 + 2), 0.0) + m * (1 - w)
                continue
            w = _game_p1(pA, pB, srv, here) if here else (hA if srv == 0 else 1.0 - hB)
            mass[(g1 + 1, g2)] = mass.get((g1 + 1, g2), 0.0) + m * w
            mass[(g1, g2 + 1)] = mass.get((g1, g2 + 1), 0.0) + m * (1 - w)
        t += 1
    return out


def set_win(p1, p2, first_server: int = 0, rule: str = "tb7"):
    """P(player 1 wins the set), an array (one entry per match)."""
    d = set_dist(p1, p2, first_server, rule)
    return sum((v for k, v in d.items() if k[0] > k[1]), np.zeros_like(_arr(p1)))


# ── match (forward, full distributions) ─────────────────────────────────────

def _shift_add(dst: np.ndarray, src: np.ndarray, k: int, q: np.ndarray) -> None:
    W = dst.shape[1]
    if k >= 0:
        if k < W:
            dst[:, k:] += src[:, :W - k] * q[:, None]
    else:
        if -k < W:
            dst[:, :W + k] += src[:, -k:] * q[:, None]


def _played(state: dict) -> tuple[int, int, bool]:
    G = D = 0
    tb = False
    for s in (state.get("played") or []):
        try:
            a, b = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            continue
        G += a + b
        D += a - b
        tb = tb or (max(a, b) == 7 and min(a, b) == 6) or (len(s) > 2 and s[2] is not None)
    return G, D, tb


def match_batch(p1, p2, best_of: int = 3, final_set_rule: str = "tb7", state: dict | None = None,
                first_server: int | None = None, cap: int = CAP) -> dict:
    """
    Arrays, one entry per match: {"p1_win","p2_win","sets": {"s1-s2": arr},"games": (B, W) P(total = n),
    "handicap": (B, 2H+1) P(g1 - g2 = k - H) with "handicap_offset" H,"p_tiebreak","p_straight",
    "exp_games"}.
    """
    pA, pB = np.broadcast_arrays(_arr(p1), _arr(p2))
    pA, pB = np.clip(pA.astype(float), 1e-6, 1 - 1e-6), np.clip(pB.astype(float), 1e-6, 1 - 1e-6)
    B = len(pA)
    best_of = 5 if int(best_of) == 5 else 3
    need = best_of // 2 + 1
    dec_rule = str(final_set_rule or "tb7").lower()
    if dec_rule not in RULES:
        dec_rule = "tb7"
    st = dict(state or {})
    sets0 = st.get("sets") or [0, 0]
    s1_0, s2_0 = int(sets0[0]), int(sets0[1])
    games0 = st.get("games") or [0, 0]
    g1_0, g2_0 = int(games0[0]), int(games0[1])
    pts0 = parse_points(st.get("points"))
    G0, D0, tb0 = _played(st)
    capx = max(cap, g1_0 + 1, g2_0 + 1)
    WT = G0 + 13 * (best_of - 1) + 2 * capx + 6
    H = abs(D0) + 7 * (best_of - 1) + capx + 4
    WD = 2 * H + 1
    rule_of = lambda typ: dec_rule if typ == "dec" else "tb7"  # noqa: E731
    sd = {}

    def dist(typ, b):
        if (typ, b) not in sd:
            sd[(typ, b)] = set_dist(pA, pB, b, rule_of(typ), cap=cap)
        return sd[(typ, b)]

    T: dict = {}
    Dd: dict = {}
    N: dict = {}

    def add(key, t_src, d_src, n_src, q, dg, dd, tb_score):
        if key not in T:
            T[key] = np.zeros((B, WT))
            Dd[key] = np.zeros((B, WD))
            N[key] = np.zeros(B)
        _shift_add(T[key], t_src, dg, q)
        _shift_add(Dd[key], d_src, dd, q)
        if not tb_score:
            N[key] += n_src * q

    def nxt(s1, s2, a, c, b):
        return (s1 + (a > c), s2 + (c > a), b if (a + c) % 2 == 0 else 1 - b)

    fresh = (s1_0, s2_0, g1_0, g2_0) == (0, 0, 0, 0) and not pts0 and state is None
    if fresh or (g1_0, g2_0) == (0, 0) and not pts0:
        # at the start of a set: the next set's first server is the given / unknown server
        srv = st.get("server", first_server) if state is not None else first_server
        servers = [(int(srv), 1.0)] if srv in (0, 1) else [(0, 0.5), (1, 0.5)]
        for b, w in servers:
            key = (s1_0, s2_0, b)
            T.setdefault(key, np.zeros((B, WT)))
            Dd.setdefault(key, np.zeros((B, WD)))
            N.setdefault(key, np.zeros(B))
            T[key][:, G0] += w
            Dd[key][:, H + D0] += w
            if not tb0:
                N[key] += w
    else:
        srv = st.get("server")
        servers = [(int(srv), 1.0)] if srv in (0, 1) else [(0, 0.5), (1, 0.5)]
        typ = "dec" if (s1_0 == s2_0 == need - 1) else "reg"
        rule = rule_of(typ)
        t0 = np.zeros((B, WT))
        t0[:, G0] = 1.0
        d0 = np.zeros((B, WD))
        d0[:, H + D0] = 1.0
        n0 = np.zeros(B) if tb0 else np.ones(B)
        for S, w in servers:
            b_eq = S if (g1_0 + g2_0) % 2 == 0 else 1 - S
            cur = set_dist(pA, pB, b_eq, rule, start=(g1_0, g2_0), points=pts0, cap=cap)
            for (a, c), q in cur.items():
                add(nxt(s1_0, s2_0, a, c, b_eq), t0, d0, n0, q * w, a + c, a - c, is_tiebreak_score(a, c, rule))
    # propagate set by set
    for tot in range(s1_0 + s2_0, 2 * need - 1):
        for s1 in range(need):
            s2 = tot - s1
            if s2 < 0 or s2 >= need:
                continue
            for b in (0, 1):
                key = (s1, s2, b)
                if key not in T:
                    continue
                t, d, n = T.pop(key), Dd.pop(key), N.pop(key)
                typ = "dec" if s1 == s2 == need - 1 else "reg"
                rule = rule_of(typ)
                for (a, c), q in dist(typ, b).items():
                    add(nxt(s1, s2, a, c, b), t, d, n, q, a + c, a - c, is_tiebreak_score(a, c, rule))
    sets: dict = {}
    games = np.zeros((B, WT))
    hcap = np.zeros((B, WD))
    no_tb = np.zeros(B)
    for (s1, s2, b), t in T.items():
        if s1 < need and s2 < need:
            continue
        lab = f"{s1}-{s2}"
        sets[lab] = sets.get(lab, 0.0) + t.sum(1)
        games += t
        hcap += Dd[(s1, s2, b)]
        no_tb += N[(s1, s2, b)]
    order = sorted(sets, key=lambda s: (-int(s.split("-")[0]), int(s.split("-")[1])))
    sets = {k: sets[k] for k in order}
    p1w = sum((v for k, v in sets.items() if int(k.split("-")[0]) == need), np.zeros(B))
    straight = sum((v for k, v in sets.items() if min(int(x) for x in k.split("-")) == 0), np.zeros(B))
    n_axis = np.arange(WT)
    return {"p1_win": p1w, "p2_win": 1.0 - p1w, "sets": sets, "games": games, "handicap": hcap,
            "handicap_offset": H, "p_tiebreak": 1.0 - no_tb, "p_straight": straight,
            "exp_games": games @ n_axis, "best_of": best_of, "final_set_rule": dec_rule}


def _to_scalar_dist(arr1d: np.ndarray, offset: int = 0, floor: float = 1e-9) -> dict:
    return {int(i - offset): float(v) for i, v in enumerate(arr1d) if v > floor}


def match(p1, p2, best_of: int = 3, final_set_rule: str = "tb7", state: dict | None = None,
          first_server: int | None = None, cap: int = CAP) -> dict:
    """
    {"p1_win","p2_win","sets": {"2-0": p, ...},"games": {n: p},"handicap": {g1 - g2: p},"p_tiebreak",
    "p_straight","exp_games"} for scalar inputs (the contract's shape; "handicap" is player 1's game margin);
    arrays (as match_batch) when p1/p2 are arrays.
    """
    scalar = np.ndim(p1) == 0 and np.ndim(p2) == 0
    r = match_batch(p1, p2, best_of, final_set_rule, state, first_server, cap)
    if not scalar:
        return r
    return {"p1_win": float(r["p1_win"][0]), "p2_win": float(r["p2_win"][0]),
            "sets": {k: float(v[0]) for k, v in r["sets"].items()},
            "games": _to_scalar_dist(r["games"][0]), "handicap": _to_scalar_dist(r["handicap"][0], r["handicap_offset"]),
            "p_tiebreak": float(r["p_tiebreak"][0]), "p_straight": float(r["p_straight"][0]),
            "exp_games": float(r["exp_games"][0]), "best_of": r["best_of"], "final_set_rule": r["final_set_rule"]}


def over_prob(dist: dict, line: float) -> float:
    """P(total > line) from a {n: p} games distribution (or P(margin > line) from a handicap one)."""
    return float(sum(p for n, p in dist.items() if n > line))


def p_win_from_dist(d: dict) -> float:
    return float(d.get("p1_win", 0.0))


# ── match-level dispersion (mixture over a random serve-point edge) ─────────
#
# Points are not i.i.d. across a whole match: a player's level on the day varies, so real matches are more
# lopsided at set level (more straight sets, fewer games) than one fixed pair (p1, p2) implies. The mixture
# draws a per-match edge e ~ N(0, sigma^2) on the point scale, (p1 + e, p2 - e), and averages the exact chain
# over Gauss-Hermite nodes; `solve_shift(..., sigma=)` re-centres it so P(win) still equals the target.
# sigma is fitted per tour in the backtest (set-score log-likelihood) and stored with the blend.

def _gh(nodes: int):
    z, w = np.polynomial.hermite_e.hermegauss(int(nodes))
    return z, w / w.sum()


def _expand(pA, pB, sigma: float, nodes: int):
    z, w = _gh(nodes)
    A = np.clip(pA[:, None] + sigma * z[None, :], 0.01, 0.99).ravel()
    Bv = np.clip(pB[:, None] - sigma * z[None, :], 0.01, 0.99).ravel()
    return A, Bv, w


def match_mix(p1, p2, best_of: int = 3, final_set_rule: str = "tb7", sigma: float = 0.0, nodes: int = 7,
              state: dict | None = None) -> dict:
    """match_batch averaged over a per-match edge e ~ N(0, sigma^2) (arrays in and out, same keys)."""
    pA, pB = np.broadcast_arrays(_arr(p1), _arr(p2))
    if not sigma or sigma <= 0:
        return match_batch(pA, pB, best_of, final_set_rule, state)
    B = len(pA)
    A, Bv, w = _expand(pA.astype(float), pB.astype(float), float(sigma), nodes)
    K = len(w)
    r = match_batch(A, Bv, best_of, final_set_rule, state)

    def red(x):
        x = np.asarray(x)
        return np.tensordot(x.reshape((B, K) + x.shape[1:]), w, axes=([1], [0]))
    out = dict(r)
    for k in ("p1_win", "p2_win", "p_tiebreak", "p_straight", "exp_games"):
        out[k] = red(r[k])
    out["games"] = np.einsum("bk...,k->b...", r["games"].reshape(B, K, -1), w)
    out["handicap"] = np.einsum("bk...,k->b...", r["handicap"].reshape(B, K, -1), w)
    out["sets"] = {k: red(v) for k, v in r["sets"].items()}
    out["sigma"] = float(sigma)
    return out


def match_win_prob_mix(p1, p2, best_of: int = 3, final_set_rule: str = "tb7", sigma: float = 0.0, nodes: int = 7):
    pA, pB = np.broadcast_arrays(_arr(p1), _arr(p2))
    if not sigma or sigma <= 0:
        return match_win_prob(pA, pB, best_of, final_set_rule)
    A, Bv, w = _expand(pA.astype(float), pB.astype(float), float(sigma), nodes)
    return match_win_prob(A, Bv, best_of, final_set_rule).reshape(len(pA), len(w)) @ w


def solve_shift(target, pA, pB, best_of: int = 3, final_set_rule: str = "tb7", iters: int = 40, sigma: float = 0.0):
    """
    delta (array) such that match(pA + delta, pB - delta)["p1_win"] = target: moves a win probability
    into the serve-point edge while keeping pA + pB (the matchup's serve dominance). Bisection, vectorised.
    With sigma > 0 the target is matched by the dispersion mixture (match_mix).
    """
    tgt = np.clip(_arr(target), 1e-6, 1 - 1e-6)
    pA, pB = np.broadcast_arrays(_arr(pA), _arr(pB))
    lo = np.maximum(-pA + 0.02, pB - 0.98) - 0.0
    hi = np.minimum(0.98 - pA, pB - 0.02)
    lo, hi = np.minimum(lo, 0.0), np.maximum(hi, 0.0)
    for _ in range(iters):
        mid = (lo + hi) / 2
        pw = match_win_prob_mix(pA + mid, pB - mid, best_of, final_set_rule, sigma)
        up = pw < tgt
        lo = np.where(up, mid, lo)
        hi = np.where(up, hi, mid)
    return (lo + hi) / 2


# ── fast win probability (no distributions) and the live table ─────────────

class _SetClasses:
    """
    (g1, g2, points) -> (B, 4) [win&even, win&odd, lose&even, lose&odd] of the set's final score total parity,
    for a set whose first game is served by `b`. A class (not a recursive closure) so that discarded tables
    are freed by refcounting: a self-referencing closure holding numpy arrays is a cycle that leaked memory.
    """

    def __init__(self, pA, pB, b: int, rule: str, cap: int = CAP):
        self.pA, self.pB, self.b = pA, pB, int(b)
        self.hA, self.hB = game_win(pA), game_win(pB)
        self.tb_at, self.tb_to = _rule(rule)
        x, y = self.hA * (1 - self.hB), (1 - self.hA) * self.hB
        self.Tadv = x / np.maximum(x + y, 1e-300)
        self.B = len(pA)
        self.memo: dict = {}

    def onehot(self, win, parity):
        o = np.zeros((self.B, 4))
        o[:, (0 if win else 2) + parity] = 1.0
        return o

    def __call__(self, g1, g2, pts=None):
        key = (g1, g2)
        if pts is None and key in self.memo:
            return self.memo[key]
        tb_at, b = self.tb_at, self.b
        if _terminal(g1, g2, tb_at):
            r = self.onehot(g1 > g2, (g1 + g2) % 2)
        else:
            srv = b if (g1 + g2) % 2 == 0 else 1 - b
            if tb_at is not None and g1 == g2 == tb_at:
                w = tiebreak_win(self.pA, self.pB, self.tb_to, srv, pts or (0, 0))
                par = (2 * tb_at + 1) % 2
                r = w[:, None] * self.onehot(True, par) + (1 - w)[:, None] * self.onehot(False, par)
            elif tb_at is None and g1 == g2 and g1 >= 5 and not pts:
                r = self.Tadv[:, None] * self.onehot(True, 0) + (1 - self.Tadv)[:, None] * self.onehot(False, 0)
            else:
                w = _game_p1(self.pA, self.pB, srv, pts) if pts else (self.hA if srv == 0 else 1.0 - self.hB)
                r = w[:, None] * self(g1 + 1, g2) + (1 - w)[:, None] * self(g1, g2 + 1)
        if pts is None:
            self.memo[key] = r
        return r


def _classes_set(pA, pB, b: int, rule: str, cap: int = CAP) -> _SetClasses:
    return _SetClasses(pA, pB, b, rule, cap)


class LiveTable:
    """
    P(player 1 wins) from any score by backward recursion, vectorised over matches.
    `p(sets, games, server, points)` with server 0/1 (None averages both).
    """

    def __init__(self, p1, p2, best_of: int = 3, final_set_rule: str = "tb7", cap: int = CAP):
        pA, pB = np.broadcast_arrays(_arr(p1), _arr(p2))
        self.pA = np.clip(pA.astype(float), 1e-6, 1 - 1e-6)
        self.pB = np.clip(pB.astype(float), 1e-6, 1 - 1e-6)
        self.best_of = 5 if int(best_of) == 5 else 3
        self.need = self.best_of // 2 + 1
        self.dec_rule = final_set_rule if final_set_rule in RULES else "tb7"
        self.cls = {(typ, b): _classes_set(self.pA, self.pB, b, self.dec_rule if typ == "dec" else "tb7", cap)
                    for typ in ("reg", "dec") for b in (0, 1)}
        need = self.need
        B = len(self.pA)
        M: dict = {}
        for s1 in range(need, -1, -1):
            for s2 in range(need, -1, -1):
                for b in (0, 1):
                    if s1 == need and s2 < need:
                        M[(s1, s2, b)] = np.ones(B)
                    elif s2 == need and s1 < need:
                        M[(s1, s2, b)] = np.zeros(B)
                    elif s1 < need and s2 < need:
                        c = self.cls[(self._typ(s1, s2), b)](0, 0)
                        M[(s1, s2, b)] = self._combine(c, s1, s2, b, M)
        self.M = M

    def _typ(self, s1, s2):
        return "dec" if s1 == s2 == self.need - 1 else "reg"

    @staticmethod
    def _combine(c, s1, s2, b, M):
        return (c[:, 0] * M[(s1 + 1, s2, b)] + c[:, 1] * M[(s1 + 1, s2, 1 - b)]
                + c[:, 2] * M[(s1, s2 + 1, b)] + c[:, 3] * M[(s1, s2 + 1, 1 - b)])

    def p(self, sets=(0, 0), games=(0, 0), server: int | None = None, points=None) -> np.ndarray:
        s1, s2 = int(sets[0]), int(sets[1])
        if s1 >= self.need:
            return np.ones(len(self.pA))
        if s2 >= self.need:
            return np.zeros(len(self.pA))
        g1, g2 = int(games[0]), int(games[1])
        pts = parse_points(points)
        if pts == (0, 0):
            pts = None
        if server not in (0, 1):
            return 0.5 * (self.p(sets, games, 0, points) + self.p(sets, games, 1, points))
        b = server if (g1 + g2) % 2 == 0 else 1 - server
        c = self.cls[(self._typ(s1, s2), b)](g1, g2, pts)
        return self._combine(c, s1, s2, b, self.M)

    def p_pre(self) -> np.ndarray:
        return 0.5 * (self.M[(0, 0, 0)] + self.M[(0, 0, 1)])


def match_win_prob(p1, p2, best_of: int = 3, final_set_rule: str = "tb7"):
    """P(player 1 wins) before the match (first server averaged), arrays in and out; fast path."""
    return LiveTable(p1, p2, best_of, final_set_rule).p_pre()


@lru_cache(maxsize=4096)
def _cached_scalar(p1: float, p2: float, best_of: int, rule: str) -> float:
    return float(match_win_prob(p1, p2, best_of, rule)[0])


def win_prob(p1: float, p2: float, best_of: int = 3, final_set_rule: str = "tb7") -> float:
    """Scalar, cached P(player 1 wins) for serve-point probabilities rounded to 1e-5."""
    return _cached_scalar(round(float(p1), 5), round(float(p2), 5), 5 if int(best_of) == 5 else 3,
                          str(final_set_rule or "tb7"))
