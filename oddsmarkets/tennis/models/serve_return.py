"""
Serve/return strengths inferred from game and set scores (the Quant Ace core model).

1. Exact game, tiebreak and set probabilities
---------------------------------------------
A server who wins each point independently with probability p holds with

    G(p) = p^4 (1 + 4q + 10q^2) + 20 p^3 q^3 * p^2 / (1 - 2pq),     q = 1 - p

(love to 30, then deuce: reach 3-3 in C(6,3)=20 ways, win from deuce p^2 / (p^2 + q^2)).
`game_hold(p)` is G, `point_prob_from_hold(h)` its exact inverse (bisection + Newton, to 1e-15).

Tiebreaks (to 7 or to 10, win by two): the first server serves point 1, then the players alternate
every two points. An exact DP runs over the lattice up to (N-1, N-1); from a tie the next two points
have one serve each, so the pair is won with W = pa (1 - pb), lost with L = (1 - pa) pb, split with
T = 1 - W - L, and the tail is geometric (P(win from tie) = W / (W + L); P(N+k : N+k-2) =
P(tie) T^k-1 W).

Sets: hA = P(player 1 holds), hB = P(player 2 holds); servers alternate by game. The same DP runs over
games up to 5-5; then 7-5 = P(5-5) W, 5-7 = P(5-5) L, 6-6 = P(5-5) T with W = hA (1 - hB) etc., and
6-6 goes to a tiebreak (to 7, or to 10 in a "tb10" deciding set) whose first server is the set's first
server (game 13). Advantage sets ("adv") carry on in pairs: P(n+2 : n) = P(5-5) T^(n-5) W, capped at
`cap` games with the tail mass reported. "tb7@12" (Wimbledon 2019-21) is a tiebreak to 7 at 12-12.
The first game of the next set is served by the player who did not serve first in this one exactly
when the set had an odd number of games (a tiebreak counts as one game), so the first server of every
set follows from the first server of the match and the game counts.

2. Match likelihood of an observed scoreline
--------------------------------------------
The match's first server is unknown: L = 1/2 prod_k P(set k | chain from p1 serving first)
+ 1/2 prod_k P(set k | chain from p2 serving first). A 7-6 set uses the exact tiebreak score when
known (else only who won it), with point probabilities p = G^-1(h). Retirements and defaults keep
only their completed sets; walkovers are excluded; an unparseable set ends a match's usable data.

3. The model
------------
    logit P(i holds v j) = mu + clay/grass + indoor + bo5 + level + (s_i + ds_i,surf) - (r_j + dr_j,surf)

for surface in {hard (carpet folds in), clay, grass}. Fitted by penalised maximum likelihood:

    max  sum_m w_m log L_m  -  lam/2 (|s|^2 + |r|^2)  -  lam_d/2 (|ds|^2 + |dr|^2)  -  lam_b/2 |base|^2
    w_m = 0.5 ** (age_days / half_life_days)        (matches older than `window_days` dropped)

with L-BFGS on the exact gradient (forward-mode derivatives carried through the game, set and
tiebreak DPs, and through G^-1 by dp/dh = 1 / G'(p)), vectorised over all sets of the window.
The penalty makes the additive constants identifiable (s and r centre on zero; the levels and
surfaces are deviations from mu).

Mirror symmetry. With the first server unknown, a scoreline is exactly as likely under holds
(hA, hB) as under (1 - hB, 1 - hA): every game flips from "server won" to "receiver won", which is the
same game sequence with the serving order swapped, and the match likelihood mixes both orders (the
tiebreak winner's odds do not depend on who serves first, so tiebreaks do not break it either; only
exact tiebreak point scores and the stats layer do, weakly and strongly). The score-only likelihood
therefore has two mirror modes, (mu, s, r) and (-mu, r, s) (all baseline terms negate). The fit keeps
the physical one, mu > 0 (tour-average holds above 50%, true of every tour-level season on both tours):
when the optimiser lands in the other mode its exact image is taken and polished.

WTA point layer (`stats=True`): where MATCH.stats exist, each player's serve points won
(fs_won + ss_won of sv_pts) adds a binomial term with p_obs = logistic(logit G^-1(h) + k_spw), and her
service games held (sv_gms - (bp_faced - bp_saved) of sv_gms) a binomial term with
h_obs = logistic(eta + k_hold). The two tour-level link offsets exist because real tennis is not iid.
On the committed WTA validation (validate_stats, 2016-2025) the mean real hold (0.651) sits slightly
ABOVE the iid game formula applied to the mean real SPW (G = 0.648), so the game layer alone is nearly
iid on average; what differs is the hold level that best reproduces scorelines under the iid chain (the
chain-scale hold), which sits below the real holds (fitted k_hold about +0.35, k_spw about +0.16:
scorelines are more lopsided than iid points with the real rates would make them). So
h (the "chain-scale" hold) stays the quantity whose exact chain fits the scores (what match pricing
needs), while the stats sharpen s and r and calibrate the displayed hold/SPW. `stats=False` is the
pure score model used for validation. (Scores and stats are treated as independent evidence, a mild
double count that makes se a little optimistic where stats exist.)

Uncertainty (Laplace): per player an 8x8 block (s, ds_hard, ds_clay, ds_grass, r, dr_...) of the
empirical-Fisher Hessian (sums of w * g g' of each match's score in the player's s and r, by surface;
the s-r cross terms matter because set scores pin s_i + r_i far better than s_i - r_i) plus the ridge,
inverted; se of s_i + ds_i,surf is sqrt(e' H^-1 e). Opponent and baseline covariance is ignored.

Public API used by builder C (stable): `game_hold(p)`, `point_prob_from_hold(h)`, `tiebreak_win`,
`set_score_probs(h1, h2, first_server, rule, p_srv1=None, p_srv2=None)`, `hold_prob(model, server,
returner, surface, level, best_of)` and `match_loglik`.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date, timedelta
from typing import Any, Iterable

import numpy as np
import scipy.sparse as sp
from scipy.optimize import minimize

from oddsmarkets.tennis.models import _io

logger = logging.getLogger(__name__)
VERSION = 2

SURFACES = _io.SURFACES
LEVELS = _io.LEVELS
BASE_NAMES = ["mu", "clay", "grass", "indoor", "bo5"] + [f"lv_{lv}" for lv in LEVELS] + ["k_hold", "k_spw"]
K_HOLD, K_SPW = len(BASE_NAMES) - 2, len(BASE_NAMES) - 1
NB = len(BASE_NAMES)
_EPS = 1e-12

# defaults; tuned values per tour live in models/fitted/serve_return_<tour>.json ("constants")
DEFAULTS = {"half_life_days": 365.0, "ridge": 2.0, "ridge_delta": 8.0, "ridge_base": 1.0, "window_days": 1460,
            "stats_weight": 1.0}


# ---------------------------------------------------------------------------------------------------------
# 1. exact game / tiebreak / set probabilities
# ---------------------------------------------------------------------------------------------------------

def _out(x):
    x = np.asarray(x, float)
    return float(x) if x.ndim == 0 else x


def game_hold(p):
    """P(server holds) when winning each service point with probability p (scalar or array)."""
    p = np.asarray(p, float)
    q = 1.0 - p
    return _out(p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * (p * q) ** 3 * p * p / (1 - 2 * p * q))


def game_hold_dp(p):
    """dG/dp."""
    p = np.asarray(p, float)
    q = 1.0 - p
    a = 1 + 4 * q + 10 * q * q
    dA = 4 * p ** 3 * a + p ** 4 * (-4 - 20 * q)
    B = 20 * (p * q) ** 3
    dB = 60 * (p * q) ** 2 * (q - p)
    d = 1 - 2 * p * q
    C = p * p / d
    dC = (2 * p * d - p * p * (4 * p - 2)) / (d * d)
    return _out(dA + dB * C + B * dC)


def point_prob_from_hold(h):
    """The serve-point win probability p with game_hold(p) = h (exact inverse; scalar or array)."""
    h = np.clip(np.asarray(h, float), 1e-13, 1 - 1e-13)
    lo = np.zeros_like(h)
    hi = np.ones_like(h)
    for _ in range(34):
        mid = 0.5 * (lo + hi)
        low = np.asarray(game_hold(mid)) < h
        lo = np.where(low, mid, lo)
        hi = np.where(low, hi, mid)
    p = 0.5 * (lo + hi)
    for _ in range(3):
        g = np.asarray(game_hold_dp(p))
        p = np.clip(p - (np.asarray(game_hold(p)) - h) / np.maximum(g, 1e-300), 1e-13, 1 - 1e-13)
    return _out(p)


def _tb_a_serves(k: int, a_first: bool) -> bool:
    return (((k + 1) // 2) % 2 == 0) == a_first


def _lattice(xa, xb, to: int, a_serves: list[bool]):
    """Forward-mode DP of a race to `to` (win by two from (to-1, to-1)) where A wins a unit with xa when
    A serves and with 1 - xb when B serves. Returns (termA, termB, tie): termA[j] = (v, d/dxa, d/dxb) of
    ending (to, j), j <= to-2; termB[i] likewise for (i, to); tie = state (to-1, to-1)."""
    one = np.ones_like(xa)
    zero = np.zeros_like(xa)
    V = {(0, 0): (one, zero, zero)}
    termA: list = [None] * (to - 1)
    termB: list = [None] * (to - 1)

    def add(key, val):
        i, j = key
        if i == to:
            termA[j] = val
            return
        if j == to:
            termB[i] = val
            return
        cur = V.get(key)
        V[key] = val if cur is None else (cur[0] + val[0], cur[1] + val[1], cur[2] + val[2])

    for k in range(0, 2 * to - 2):
        srv_a = a_serves[k]
        for i in range(max(0, k - (to - 1)), min(k, to - 1) + 1):
            j = k - i
            st = V.pop((i, j), None)
            if st is None:
                continue
            v, da, db = st
            if srv_a:
                w = xa
                win = (v * w, da * w + v, db * w)
                lose = (v - win[0], da - win[1], db - win[2])
            else:
                w = 1.0 - xb
                win = (v * w, da * w, db * w - v)
                lose = (v - win[0], da - win[1], db - win[2])
            add((i + 1, j), win)
            add((i, j + 1), lose)
    tie = V.pop((to - 1, to - 1))
    return termA, termB, tie


def _pair(xa, xb):
    """W, L, T of a two-unit block (one serve each) with derivatives: ((W, dWa, dWb), (L, ...), (T, ...))."""
    W = (xa * (1 - xb), 1 - xb, -xa)
    L = ((1 - xa) * xb, -xb, 1 - xa)
    T = (1 - W[0] - L[0], 2 * xb - 1, 2 * xa - 1)
    return W, L, T


def tiebreak_win(pa, pb, a_first: bool = True, to: int = 7):
    """P(A wins a tiebreak to `to`), A winning a point on her serve with pa, B on hers with pb."""
    xa = np.atleast_1d(np.asarray(pa, float))
    xb = np.atleast_1d(np.asarray(pb, float))
    termA, _, tie = _lattice(xa, xb, int(to), [_tb_a_serves(k, a_first) for k in range(2 * to)])
    W, L, _ = _pair(xa, xb)
    out = sum(t[0] for t in termA) + tie[0] * W[0] / np.maximum(W[0] + L[0], 1e-300)
    return _out(out if np.ndim(pa) else out[0])


def tiebreak_score_probs(pa, pb, a_first: bool = True, to: int = 7, cap: int = 30) -> dict:
    """{(a, b): p} over tiebreak scores up to `cap` points for the winner (scalars)."""
    xa, xb = np.array([float(pa)]), np.array([float(pb)])
    termA, termB, tie = _lattice(xa, xb, int(to), [_tb_a_serves(k, a_first) for k in range(2 * to)])
    W, L, T = _pair(xa, xb)
    out = {}
    for j in range(to - 1):
        out[(to, j)] = float(termA[j][0][0])
        out[(j, to)] = float(termB[j][0][0])
    reach = float(tie[0][0])
    n = to - 1
    while n + 2 <= cap:
        out[(n + 2, n)] = reach * float(W[0][0])
        out[(n, n + 2)] = reach * float(L[0][0])
        reach *= float(T[0][0])
        n += 1
    return out


def _set_serves(fs1: bool) -> list[bool]:
    return [((k % 2) == 0) == fs1 for k in range(12)]


RULES = ("tb7", "tb10", "adv", "tb7@12")


def set_score_probs(h1, h2, first_server=1, rule: str = "tb7", p_srv1=None, p_srv2=None, cap: int = 20,
                    with_tail: bool = False):
    """
    Exact distribution of one set's score from player 1's view: {(g1, g2): p}.

    h1 = P(player 1 holds serve), h2 = P(player 2 holds); `first_server` 1 or 2 (None averages both);
    `rule` "tb7" (tiebreak to 7 at 6-6, the normal set), "tb10" (to 10 at 6-6, a modern Slam deciding set),
    "adv" (no tiebreak, win by two; scores up to `cap` games for the winner), "tb7@12" (tiebreak to 7 at
    12-12). Tiebreak points use p_srv1 / p_srv2 when given, else point_prob_from_hold(h). The values sum
    to 1 except for an "adv" set's tail beyond `cap`; with_tail=True returns (dist, tail).
    """
    if first_server not in (1, 2):
        a, ta = set_score_probs(h1, h2, 1, rule, p_srv1, p_srv2, cap, True)
        b, tb = set_score_probs(h1, h2, 2, rule, p_srv1, p_srv2, cap, True)
        d = {k: 0.5 * (a.get(k, 0.0) + b.get(k, 0.0)) for k in set(a) | set(b)}
        return (d, 0.5 * (ta + tb)) if with_tail else d
    fs1 = first_server == 1
    xa, xb = np.array([float(h1)]), np.array([float(h2)])
    termA, termB, tie = _lattice(xa, xb, 6, _set_serves(fs1))
    W, L, T = _pair(xa, xb)
    w, l, t = float(W[0][0]), float(L[0][0]), float(T[0][0])
    out = {}
    for j in range(5):
        out[(6, j)] = float(termA[j][0][0])
        out[(j, 6)] = float(termB[j][0][0])
    r55 = float(tie[0][0])
    out[(7, 5)] = r55 * w
    out[(5, 7)] = r55 * l
    tail = 0.0
    rule = rule if rule in RULES else "tb7"
    if rule in ("tb7", "tb10"):
        pa = float(p_srv1) if p_srv1 is not None else point_prob_from_hold(h1)
        pb = float(p_srv2) if p_srv2 is not None else point_prob_from_hold(h2)
        tw = tiebreak_win(pa, pb, fs1, 10 if rule == "tb10" else 7)
        out[(7, 6)] = r55 * t * tw
        out[(6, 7)] = r55 * t * (1 - tw)
    else:
        reach = r55 * t                         # P(6-6)
        if rule == "tb7@12":
            for n in range(6, 12):
                out[(n + 2, n)] = reach * w
                out[(n, n + 2)] = reach * l
                reach *= t
            pa = float(p_srv1) if p_srv1 is not None else point_prob_from_hold(h1)
            pb = float(p_srv2) if p_srv2 is not None else point_prob_from_hold(h2)
            tw = tiebreak_win(pa, pb, fs1, 7)       # game 25 is served by the set's first server
            out[(13, 12)] = reach * tw
            out[(12, 13)] = reach * (1 - tw)
        else:
            n = 6
            while n + 2 <= cap:
                out[(n + 2, n)] = reach * w
                out[(n, n + 2)] = reach * l
                reach *= t
                n += 1
            tail = reach
    return (out, tail) if with_tail else out


# ---------------------------------------------------------------------------------------------------------
# 2. scoreline parsing and the vectorised match likelihood
# ---------------------------------------------------------------------------------------------------------

def _tb_points(w, l, N):
    """(winner points, loser points) of a tiebreak to N when consistent, else None. Either may be None
    (a missing winner total is implied by the loser's)."""
    try:
        w = None if w is None else int(w)
        l = None if l is None else int(l)
    except (TypeError, ValueError):
        return None
    if l is None:
        if w is not None and w > N:
            l = w - 2
        else:
            return None
    if w is None:
        w = max(N, l + 2)
    if (w == N and 0 <= l <= N - 2) or (l >= N - 1 and w == l + 2):
        return w, l
    return None


def parse_sets(sets: Any, best_of: int = 3, rule: str | None = "tb7") -> list[tuple]:
    """Usable sets of a scoreline as codes (kind, t, n, m, N, tbw, tbl, p1won, games), stopping at the
    first set that is not a completed set. kind 0 = 6-x (t: 0..4 p1 6-t, 5..9 p2), 1 = (n+2):n with
    n >= 5, 2 = tiebreak at m-m (to N; tbw/tbl the winner/loser points or -1)."""
    out = []
    bo = 5 if int(best_of or 3) == 5 else 3
    for k, s in enumerate(sets or []):
        try:
            g1, g2 = int(s[0]), int(s[1])
        except (TypeError, ValueError, IndexError):
            break
        tb1 = s[2] if len(s) > 2 else None
        tb2 = s[3] if len(s) > 3 else None
        deciding = k == bo - 1
        hi, lo = max(g1, g2), min(g1, g2)
        p1won = g1 > g2
        if hi == 6 and lo <= 4:
            out.append((0, lo if p1won else 5 + lo, 0, 0, 0, -1, -1, p1won, g1 + g2))
        elif hi - lo == 2 and lo >= 5 and (lo == 5 or deciding):
            out.append((1, 0, lo, 0, 0, -1, -1, p1won, g1 + g2))
        elif hi - lo == 1 and (hi == 7 or (hi == 13 and deciding)):
            m = lo
            N = 10 if (m == 6 and deciding and rule == "tb10") else 7
            pts = _tb_points(*((tb1, tb2) if p1won else (tb2, tb1)), N)
            if pts is None and m == 6 and deciding and N == 7:
                alt = _tb_points(*((tb1, tb2) if p1won else (tb2, tb1)), 10)
                if alt is not None and alt[0] >= 10:
                    N, pts = 10, alt
            w, l = pts if pts is not None else (-1, -1)
            out.append((2, 0, 0, m, N, w, l, p1won, g1 + g2))
        else:
            break
    return out


def _prep_sets(codes_by_match: list[list[tuple]]) -> dict:
    mi, kind, t, n, m, N, tw, tl, won, fsx = ([] for _ in range(10))
    for j, codes in enumerate(codes_by_match):
        cum = 0
        for c in codes:
            mi.append(j)
            kind.append(c[0]); t.append(c[1]); n.append(c[2]); m.append(c[3]); N.append(c[4])
            tw.append(c[5]); tl.append(c[6]); won.append(c[7]); fsx.append(cum % 2 == 0)
            cum += c[8]
    a = lambda x, dt=np.int64: np.asarray(x, dtype=dt)
    return {"mi": a(mi), "kind": a(kind), "t": a(t), "n": a(n), "m": a(m), "N": a(N), "tw": a(tw), "tl": a(tl),
            "won": a(won, bool), "fsx": a(fsx, bool), "n_match": len(codes_by_match)}


def _tb_logp(pa, pb, fs1, N, won, tw, tl):
    """log P of each tiebreak outcome (rows share N) and d/dpa, d/dpb."""
    termA, termB, tie = _lattice(pa, pb, N, [_tb_a_serves(k, fs1) for k in range(2 * N)])
    W, L, T = _pair(pa, pb)
    nr = len(pa)
    v = np.zeros(nr); da = np.zeros(nr); db = np.zeros(nr)
    known = tw >= 0
    # unknown points: win probability
    sA = [sum(x[c] for x in termA) for c in range(3)]
    S = np.maximum(W[0] + L[0], 1e-300)
    f = W[0] / S
    dfa = (W[1] * S - W[0] * (W[1] + L[1])) / (S * S)
    dfb = (W[2] * S - W[0] * (W[2] + L[2])) / (S * S)
    pw = (sA[0] + tie[0] * f, sA[1] + tie[1] * f + tie[0] * dfa, sA[2] + tie[2] * f + tie[0] * dfb)
    u = ~known
    v = np.where(u & won, pw[0], np.where(u, 1 - pw[0], v))
    da = np.where(u & won, pw[1], np.where(u, -pw[1], da))
    db = np.where(u & won, pw[2], np.where(u, -pw[2], db))
    if known.any():
        rows = np.arange(nr)
        short = known & (tw == N)
        if short.any():
            li = np.clip(tl, 0, N - 2)
            stA = [np.stack([x[c] for x in termA]) for c in range(3)]
            stB = [np.stack([x[c] for x in termB]) for c in range(3)]
            for c, arr in enumerate((v, da, db)):
                pick = np.where(won, stA[c][li, rows], stB[c][li, rows])
                arr[short] = pick[short]
        long_ = known & (tw > N)
        if long_.any():
            k = np.maximum(tl - (N - 1), 0).astype(float)
            Tk = T[0] ** k
            dTk = np.where(k > 0, k * T[0] ** np.maximum(k - 1, 0), 0.0)
            F = [np.where(won, W[c], L[c]) for c in range(3)]
            val = tie[0] * Tk * F[0]
            dva = tie[1] * Tk * F[0] + tie[0] * dTk * T[1] * F[0] + tie[0] * Tk * F[1]
            dvb = tie[2] * Tk * F[0] + tie[0] * dTk * T[2] * F[0] + tie[0] * Tk * F[2]
            v[long_] = val[long_]; da[long_] = dva[long_]; db[long_] = dvb[long_]
    v = np.maximum(v, 1e-300)
    return np.log(v), da / v, db / v


def _set_logp(hA, hB, S: dict, fs1: bool, inv_cache: dict):
    """log P of every set row with player 1 serving first in that set iff fs1, and d/dhA, d/dhB."""
    termA, termB, tie = _lattice(hA, hB, 6, _set_serves(fs1))
    W, L, T = _pair(hA, hB)
    nr = len(hA)
    rows = np.arange(nr)
    lp = np.zeros(nr); ga = np.zeros(nr); gb = np.zeros(nr)
    kind = S["kind"]
    k0 = kind == 0
    if k0.any():
        stk = [np.stack([x[c] for x in termA] + [x[c] for x in termB]) for c in range(3)]
        v = np.maximum(stk[0][S["t"], rows], 1e-300)
        lp = np.where(k0, np.log(v), lp)
        ga = np.where(k0, stk[1][S["t"], rows] / v, ga)
        gb = np.where(k0, stk[2][S["t"], rows] / v, gb)
    k12 = ~k0
    if k12.any():
        tv = np.maximum(tie[0], 1e-300)
        Tv = np.maximum(T[0], 1e-300)
        base = np.log(tv)
        ba, bb = tie[1] / tv, tie[2] / tv
        reps = np.where(kind == 1, S["n"] - 5, S["m"] - 5).astype(float)
        base = base + reps * np.log(Tv)
        ba = ba + reps * T[1] / Tv
        bb = bb + reps * T[2] / Tv
        k1 = kind == 1
        F = [np.where(S["won"], W[c], L[c]) for c in range(3)]
        Fv = np.maximum(F[0], 1e-300)
        lp = np.where(k1, base + np.log(Fv), lp)
        ga = np.where(k1, ba + F[1] / Fv, ga)
        gb = np.where(k1, bb + F[2] / Fv, gb)
        k2 = kind == 2
        if k2.any():
            lp = np.where(k2, base, lp)
            ga = np.where(k2, ba, ga)
            gb = np.where(k2, bb, gb)
            pa, dpa, pb, dpb = inv_cache["pa"], inv_cache["dpa"], inv_cache["pb"], inv_cache["dpb"]
            for N in np.unique(S["N"][k2]):
                sel = np.nonzero(k2 & (S["N"] == N))[0]
                l, a, b = _tb_logp(pa[sel], pb[sel], fs1, int(N), S["won"][sel], S["tw"][sel], S["tl"][sel])
                lp[sel] += l
                ga[sel] += a * dpa[sel]
                gb[sel] += b * dpb[sel]
    return lp, ga, gb


def _inv_with_grad(h):
    p = np.asarray(point_prob_from_hold(h), float)
    return p, 1.0 / np.maximum(np.asarray(game_hold_dp(p), float), 1e-12)


def match_loglik_vec(hA, hB, S: dict):
    """Per-match log-likelihood of the parsed scorelines (rows of `S` from _prep_sets) and its
    derivatives wrt each match's hA (player 1's hold probability) and hB."""
    nm = S["n_match"]
    if len(S["mi"]) == 0:
        z = np.zeros(nm)
        return z, z.copy(), z.copy()
    mi = S["mi"]
    a = np.clip(hA[mi], 1e-9, 1 - 1e-9)
    b = np.clip(hB[mi], 1e-9, 1 - 1e-9)
    inv = {}
    k2 = S["kind"] == 2
    pa = np.full(len(a), 0.5); dpa = np.zeros(len(a)); pb = pa.copy(); dpb = dpa.copy()
    if k2.any():
        pa[k2], dpa[k2] = _inv_with_grad(a[k2])
        pb[k2], dpb[k2] = _inv_with_grad(b[k2])
    inv = {"pa": pa, "dpa": dpa, "pb": pb, "dpb": dpb}
    l1, a1, b1 = _set_logp(a, b, S, True, inv)
    l2, a2, b2 = _set_logp(a, b, S, False, inv)
    fsx = S["fsx"]
    lX, aX, bX = np.where(fsx, l1, l2), np.where(fsx, a1, a2), np.where(fsx, b1, b2)
    lY, aY, bY = np.where(fsx, l2, l1), np.where(fsx, a2, a1), np.where(fsx, b2, b1)
    LX = np.bincount(mi, lX, nm)
    LY = np.bincount(mi, lY, nm)
    ll = np.logaddexp(LX, LY) - math.log(2.0)
    pX = np.exp(LX - np.logaddexp(LX, LY))
    w = pX[mi]
    gA = np.bincount(mi, w * aX + (1 - w) * aY, nm)
    gB = np.bincount(mi, w * bX + (1 - w) * bY, nm)
    has = np.bincount(mi, minlength=nm) > 0
    return np.where(has, ll, 0.0), gA, gB


def match_loglik(sets, h1, h2, best_of: int = 3, final_set_rule: str = "tb7") -> float:
    """log P(observed scoreline) for one match given each player's hold probability (scalar API).
    `sets` as in MATCH.sets ([[g1, g2, tb1, tb2], ...] from player 1's view); only completed sets count."""
    S = _prep_sets([parse_sets(sets, best_of, final_set_rule)])
    ll, _, _ = match_loglik_vec(np.array([float(h1)]), np.array([float(h2)]), S)
    return float(ll[0])


# ---------------------------------------------------------------------------------------------------------
# 3. the fit
# ---------------------------------------------------------------------------------------------------------

def _stat_pts(st: Any):
    """(serve points won, serve points, service games held, service games) from a STATS record, -1 for a
    part that is missing or inconsistent; None when neither part is usable."""
    if not isinstance(st, dict):
        return None

    def num(key):
        try:
            v = st.get(key)
            return None if v is None else int(v)
        except (TypeError, ValueError):
            return None

    n, fw, sw_, g, bf, bs = (num(k) for k in ("sv_pts", "fs_won", "ss_won", "sv_gms", "bp_faced", "bp_saved"))
    k = (fw or 0) + (sw_ or 0) if (fw is not None or sw_ is not None) else None
    pts = (k, n) if (n is not None and k is not None and n >= 10 and 0 <= k <= n) else (-1, 0)
    br = (bf - bs) if (bf is not None and bs is not None) else None
    gms = (g - br, g) if (g is not None and br is not None and g >= 1 and 0 <= br <= g) else (-1, 0)
    if pts[0] < 0 and gms[0] < 0:
        return None
    return pts[0], pts[1], gms[0], gms[1]


def _prepare(matches: Iterable[dict], through: date | None, window_days: float | None, with_stats: bool):
    rows = []
    for m in matches:
        if m.get("status") not in _io.RATED_STATUS:
            continue
        p1, p2 = m.get("p1"), m.get("p2")
        d = _io.day(m.get("date"))
        if not p1 or not p2 or p1 == p2 or d is None:
            continue
        if through is not None and d > through:
            continue
        if through is not None and window_days and (through - d).days > window_days:
            continue
        bo = 5 if int(m.get("best_of") or 3) == 5 else 3
        codes = parse_sets(m.get("sets"), bo, m.get("final_set_rule") or "tb7")
        st1 = st2 = None
        if with_stats and isinstance(m.get("stats"), dict):
            st1, st2 = _stat_pts(m["stats"].get("p1")), _stat_pts(m["stats"].get("p2"))
        if not codes and st1 is None and st2 is None:
            continue
        rows.append((m, d, bo, codes, st1, st2))
    return rows


def _base_cols(m: dict, bo: int) -> list[int]:
    cols = [0]
    surf = _io.fold_surface(m.get("surface"))
    if surf == "clay":
        cols.append(1)
    elif surf == "grass":
        cols.append(2)
    if m.get("indoor") or str(m.get("surface") or "").lower() == "carpet":
        cols.append(3)
    if bo == 5:
        cols.append(4)
    cols.append(5 + LEVELS.index(_io.fold_level(m.get("level"))))
    return cols


class _Design:
    """Index maps and sparse designs for one fit window."""

    def __init__(self, rows, through: date | None, half_life: float, pids: list[str] | None = None):
        self.pids = pids or sorted({r[0]["p1"] for r in rows} | {r[0]["p2"] for r in rows})
        self.ix = {p: i for i, p in enumerate(self.pids)}
        P = self.P = len(self.pids)
        self.n_par = NB + 8 * P
        ref = through or max(r[1] for r in rows)
        nm = len(rows)
        self.age = np.array([(ref - r[1]).days for r in rows], float)
        self.w = 0.5 ** (self.age / float(half_life))
        self.i1 = np.array([self.ix[r[0]["p1"]] for r in rows])
        self.i2 = np.array([self.ix[r[0]["p2"]] for r in rows])
        self.surf = np.array([SURFACES.index(_io.fold_surface(r[0].get("surface"))) for r in rows])
        ri, ci, vi = [], [], []
        for j, r in enumerate(rows):
            for c in _base_cols(r[0], r[2]):
                ri.append(j); ci.append(c); vi.append(1.0)
        base = sp.csr_matrix((vi, (ri, ci)), shape=(nm, self.n_par))
        jj = np.arange(nm)

        def player(srv, ret):
            r_ = np.concatenate([jj, jj, jj, jj])
            c_ = np.concatenate([NB + srv, NB + 2 * P + 3 * srv + self.surf,
                                 NB + P + ret, NB + 5 * P + 3 * ret + self.surf])
            v_ = np.concatenate([np.ones(nm), np.ones(nm), -np.ones(nm), -np.ones(nm)])
            return sp.csr_matrix((v_, (r_, c_)), shape=(nm, self.n_par))

        self.XA = (base + player(self.i1, self.i2)).tocsr()
        self.XB = (base + player(self.i2, self.i1)).tocsr()
        self.XAT = self.XA.T.tocsr()
        self.XBT = self.XB.T.tocsr()
        self.S = _prep_sets([r[3] for r in rows])
        k = np.full((nm, 2), -1.0)
        n = np.zeros((nm, 2))
        hk = np.full((nm, 2), -1.0)
        hn = np.zeros((nm, 2))
        for j, r in enumerate(rows):
            for c, st in enumerate((r[4], r[5])):
                if st is not None:
                    k[j, c], n[j, c], hk[j, c], hn[j, c] = st
        self.sk, self.sn, self.hk, self.hn = k, n, hk, hn
        self.has_pts = k >= 0
        self.has_gms = hk >= 0
        self.has_stats = self.has_pts | self.has_gms
        self.has_sets = np.bincount(self.S["mi"], minlength=nm) > 0 if len(self.S["mi"]) else np.zeros(nm, bool)


def _penalty(d: _Design, lam: float, lam_d: float, lam_b: float) -> np.ndarray:
    P = d.P
    pen = np.empty(d.n_par)
    pen[:NB] = lam_b
    pen[0] = 1e-8
    pen[NB:NB + 2 * P] = lam
    pen[NB + 2 * P:] = lam_d
    return pen


def _objective(theta, d: _Design, pen, stats_w: float, want_parts: bool = False):
    eA = d.XA @ theta
    eB = d.XB @ theta
    hA = 1 / (1 + np.exp(-eA))
    hB = 1 / (1 + np.exp(-eB))
    ll, gA, gB = match_loglik_vec(hA, hB, d.S)
    geA = gA * hA * (1 - hA)
    geB = gB * hB * (1 - hB)
    gk_hold = gk_spw = 0.0
    if stats_w > 0 and d.has_stats.any():
        kh, ks = theta[K_HOLD], theta[K_SPW]
        for c, (eta, h, ge) in enumerate(((eA, hA, geA), (eB, hB, geB))):
            sel = d.has_pts[:, c]
            if sel.any():               # serve points won: p_obs = logistic(logit G^-1(h) + k_spw)
                hh = np.clip(h[sel], 1e-9, 1 - 1e-9)
                p, dp = _inv_with_grad(hh)
                p = np.clip(p, 1e-9, 1 - 1e-9)
                po = 1 / (1 + np.exp(-(np.log(p / (1 - p)) + ks)))
                k, n = d.sk[sel, c], d.sn[sel, c]
                ll[sel] += stats_w * (k * np.log(po) + (n - k) * np.log(1 - po))
                res = stats_w * (k - n * po)
                ge[sel] += res / (p * (1 - p)) * dp * hh * (1 - hh)
                gk_spw += float(d.w[sel] @ res)
            sel = d.has_gms[:, c]
            if sel.any():               # service games held: h_obs = logistic(eta + k_hold)
                ho = 1 / (1 + np.exp(-(eta[sel] + kh)))
                ho = np.clip(ho, 1e-12, 1 - 1e-12)
                k, n = d.hk[sel, c], d.hn[sel, c]
                ll[sel] += stats_w * (k * np.log(ho) + (n - k) * np.log(1 - ho))
                res = stats_w * (k - n * ho)
                ge[sel] += res
                gk_hold += float(d.w[sel] @ res)
    f = -float(d.w @ ll) + 0.5 * float(pen @ (theta * theta))
    grad = -(d.XAT @ (d.w * geA) + d.XBT @ (d.w * geB)) + pen * theta
    grad[K_HOLD] -= gk_hold
    grad[K_SPW] -= gk_spw
    if want_parts:
        return f, grad, ll, geA, geB
    return f, grad


def _surface_mu(base: dict, surf: str) -> float:
    return base["mu"] + (base.get("clay", 0.0) if surf == "clay" else base.get("grass", 0.0) if surf == "grass" else 0.0)


def _sig(x):
    return 1.0 / (1.0 + math.exp(-x))


def _spw(h_chain: float, k_spw: float = 0.0) -> float:
    """Serve points won implied by a chain-scale hold probability, with the point-link offset."""
    p = min(max(float(point_prob_from_hold(h_chain)), 1e-12), 1 - 1e-12)
    return _sig(math.log(p / (1 - p)) + k_spw)


def _theta_from_prior(prior: dict | None, d: _Design) -> np.ndarray:
    th = np.zeros(d.n_par)
    if not prior:
        th[0] = 1.0
        return th
    b = prior.get("base") or {}
    for i, nm in enumerate(BASE_NAMES):
        if nm == "mu":
            th[i] = b.get("mu", 1.0)
        elif nm.startswith("lv_"):
            th[i] = (b.get("level") or {}).get(nm[3:], 0.0)
        else:
            th[i] = b.get(nm, 0.0)
    P = d.P
    pl = prior.get("players") or {}
    for p, i in d.ix.items():
        rec = pl.get(p)
        if not rec or "all" not in rec:
            continue
        sv = [rec[sf]["s"] if sf in rec else rec["all"]["s"] for sf in SURFACES]
        rv = [rec[sf]["r"] if sf in rec else rec["all"]["r"] for sf in SURFACES]
        s, r = float(np.mean(sv)), float(np.mean(rv))
        th[NB + i] = s
        th[NB + P + i] = r
        for k in range(3):
            th[NB + 2 * P + 3 * i + k] = sv[k] - s
            th[NB + 5 * P + 3 * i + k] = rv[k] - r
    return th


def _mirror(theta: np.ndarray, P: int) -> np.ndarray:
    """The mirror-mode image of a parameter vector: base -> -base, s <-> r, ds <-> dr."""
    x = theta.copy()
    x[:NB] = -theta[:NB]
    x[NB:NB + P], x[NB + P:NB + 2 * P] = theta[NB + P:NB + 2 * P], theta[NB:NB + P]
    x[NB + 2 * P:NB + 5 * P], x[NB + 5 * P:] = theta[NB + 5 * P:], theta[NB + 2 * P:NB + 5 * P]
    return x


def _ridges(ridge) -> tuple[float, float, float]:
    if isinstance(ridge, dict):
        return (float(ridge.get("s", DEFAULTS["ridge"])), float(ridge.get("delta", DEFAULTS["ridge_delta"])),
                float(ridge.get("base", DEFAULTS["ridge_base"])))
    lam = DEFAULTS["ridge"] if ridge is None else float(ridge)
    return lam, DEFAULTS["ridge_delta"] * lam / DEFAULTS["ridge"], DEFAULTS["ridge_base"]


def fit(matches: Iterable[dict], through: Any = None, half_life_days: float | None = None, ridge: Any = None,
        prior: dict | None = None, stats: bool = False, window_days: float | None = None,
        stats_weight: float | None = None, maxiter: int = 400, tol: float = 1e-6) -> dict:
    """
    Penalised-likelihood serve/return fit on MATCH rows dated <= `through` (default: the latest match).
    `ridge` is a float (lam for s, r; lam_delta scales with it) or {"s", "delta", "base"}; `prior` a
    previous fit used as the warm start; `stats=True` adds the WTA point layer. Returns a JSON-safe model:
    {"version", "through", "constants", "base": {"mu","clay","grass","indoor","bo5","level":{...},"new_s","new_r"},
     "players": {pid: {"all"|surface: {"s","r","se_s","se_r","n","hold","break","spw","rpw"}}},
    hold/break/spw/rpw are against the average tour-level opponent on that surface (base["ref"]),
     "n_matches", "n_sets", "n_stats", "loglik", "fit_s", "converged"}.
    """
    t0 = time.time()
    matches = list(matches)
    th = _io.day(through) if through is not None else None
    if th is None:
        ds = [_io.day(m.get("date")) for m in matches if m.get("status") in _io.RATED_STATUS]
        ds = [x for x in ds if x is not None]
        th = max(ds) if ds else None
    hl = float(half_life_days or DEFAULTS["half_life_days"])
    wd = float(window_days or max(DEFAULTS["window_days"], 4 * hl))
    sw = float(DEFAULTS["stats_weight"] if stats_weight is None else stats_weight) if stats else 0.0
    lam, lam_d, lam_b = _ridges(ridge)
    rows = _prepare(matches, th, wd, stats)
    consts = {"half_life_days": hl, "ridge": lam, "ridge_delta": lam_d, "ridge_base": lam_b, "window_days": wd,
              "stats": bool(stats), "stats_weight": sw}
    if not rows:
        return {"version": VERSION, "through": th.isoformat() if th else None, "constants": consts,
                "base": {"mu": 1.0, "clay": 0.0, "grass": 0.0, "indoor": 0.0, "bo5": 0.0,
                         "level": {lv: 0.0 for lv in LEVELS}, "new_s": 0.0, "new_r": 0.0},
                "players": {}, "n_matches": 0, "n_sets": 0, "n_stats": 0, "loglik": 0.0, "fit_s": 0.0, "iterations": 0,
                "converged": True}
    d = _Design(rows, th, hl)
    pen = _penalty(d, lam, lam_d, lam_b)
    x0 = _theta_from_prior(prior, d)
    opts = {"maxiter": maxiter, "maxcor": 20, "ftol": tol * 1e-3, "gtol": tol}
    res = minimize(_objective, x0, args=(d, pen, sw), jac=True, method="L-BFGS-B", options=opts)
    theta, nit, ok = res.x, int(res.nit), bool(res.success)
    mirrored = False
    if theta[0] < 0:                       # the mirror mode: take its image and polish
        res = minimize(_objective, _mirror(theta, d.P), args=(d, pen, sw), jac=True, method="L-BFGS-B", options=opts)
        theta, nit, ok, mirrored = res.x, nit + int(res.nit), bool(res.success), True
    f, _, ll, geA, geB = _objective(theta, d, pen, sw, want_parts=True)
    model = _assemble(theta, d, pen, geA, geB, rows, consts, th)
    model.update({"n_matches": len(rows), "n_sets": int(len(d.S["mi"])), "n_stats": int(d.has_stats.sum()),
                  "loglik": float(d.w @ ll), "objective": float(f), "fit_s": round(time.time() - t0, 3),
                  "iterations": nit, "converged": ok, "mirrored": mirrored})
    return model


def _assemble(theta, d: _Design, pen, geA, geB, rows, consts, th) -> dict:
    P = d.P
    b = {nm: float(theta[i]) for i, nm in enumerate(BASE_NAMES) if not nm.startswith("lv_")}
    b["level"] = {lv: float(theta[5 + k]) for k, lv in enumerate(LEVELS)}
    s = theta[NB:NB + P]
    r = theta[NB + P:NB + 2 * P]
    ds = theta[NB + 2 * P:NB + 5 * P].reshape(P, 3)
    dr = theta[NB + 5 * P:NB + 8 * P].reshape(P, 3)
    # empirical Fisher per player: an 8x8 block (s, ds_hard, ds_clay, ds_grass, r, dr_hard, dr_clay, dr_grass)
    # built from each match's score (d log L / d s_i, d log L / d r_i) by surface, plus the ridge
    w = d.w
    Iss = np.zeros((P, 3)); Irr = np.zeros((P, 3)); Isr = np.zeros((P, 3))
    for i_, gs, gr in ((d.i1, geA, -geB), (d.i2, geB, -geA)):
        np.add.at(Iss, (i_, d.surf), w * gs * gs)
        np.add.at(Irr, (i_, d.surf), w * gr * gr)
        np.add.at(Isr, (i_, d.surf), w * gs * gr)
    nsurf = np.zeros((P, 3), int)
    np.add.at(nsurf, (d.i1, d.surf), 1)
    np.add.at(nsurf, (d.i2, d.surf), 1)
    lam, lam_d = pen[NB], (pen[NB + 2 * P] if P else 1.0)
    H = np.zeros((P, 8, 8))
    for off, I in ((0, Iss), (4, Irr)):
        H[:, off, off] = I.sum(1) + lam
        for k in range(3):
            H[:, off, off + k + 1] = H[:, off + k + 1, off] = I[:, k]
            H[:, off + k + 1, off + k + 1] = I[:, k] + lam_d
    H[:, 0, 4] = H[:, 4, 0] = Isr.sum(1)
    for k in range(3):
        H[:, 0, 5 + k] = H[:, 5 + k, 0] = Isr[:, k]
        H[:, 1 + k, 4] = H[:, 4, 1 + k] = Isr[:, k]
        H[:, 1 + k, 5 + k] = H[:, 5 + k, 1 + k] = Isr[:, k]
    C = np.linalg.inv(H)
    Cs, Cr = C[:, :4, :4], C[:, 4:, 4:]
    share = np.bincount(d.surf, minlength=3).astype(float)
    share = share / max(share.sum(), 1.0)
    mu_s = {surf: _surface_mu(b, surf) for surf in SURFACES}
    low = np.nonzero(nsurf.sum(1) <= 5)[0]
    b["new_s"] = float(s[low].mean()) if len(low) else 0.0
    b["new_r"] = float(r[low].mean()) if len(low) else 0.0
    b["surface_share"] = {surf: float(share[k]) for k, surf in enumerate(SURFACES)}
    # reference opponent: the average tour-level opponent (appearances in main-draw tour matches) per surface
    tl = np.array([_io.fold_level(r_[0].get("level")) in _io.TOUR_LEVELS for r_ in rows])
    if not tl.any():
        tl = np.ones(len(rows), bool)
    S_ = s[:, None] + ds
    R_ = r[:, None] + dr
    ref = {}
    for key, sel in [("all", tl)] + [(sf, tl & (d.surf == k)) for k, sf in enumerate(SURFACES)]:
        if not sel.any():
            sel = tl
        ii = np.concatenate([d.i1[sel], d.i2[sel]])
        kk = np.concatenate([d.surf[sel], d.surf[sel]])
        ref[key] = (float(S_[ii, kk].mean()), float(R_[ii, kk].mean()))
    b["ref"] = {k: {"s": v[0], "r": v[1]} for k, v in ref.items()}
    kh, kp = float(b.get("k_hold", 0.0)), float(b.get("k_spw", 0.0))
    players = {}
    for p, i in d.ix.items():
        rec = {}
        for k, surf in enumerate(("all",) + SURFACES):
            if surf == "all":                       # the player's own surface mix (tour mix when unseen)
                n = int(nsurf[i].sum())
                pi = nsurf[i] / n if n else share
                e = np.concatenate([[1.0], pi])
                sv, rv = s[i] + float(pi @ ds[i]), r[i] + float(pi @ dr[i])
                vs, vr = e @ Cs[i] @ e, e @ Cr[i] @ e
                mu = float(sum(pi[k_] * mu_s[sf] for k_, sf in enumerate(SURFACES)))
            else:
                j = k - 1
                e = np.zeros(4); e[0] = 1; e[j + 1] = 1
                sv, rv = s[i] + ds[i, j], r[i] + dr[i, j]
                vs, vr = e @ Cs[i] @ e, e @ Cr[i] @ e
                mu = mu_s[surf]
                n = int(nsurf[i, j])
            hc = _sig(mu + sv - ref[surf][1])            # v the average tour-level returner (chain scale)
            bc = 1 - _sig(mu + ref[surf][0] - rv)        # v the average tour-level server (chain scale)
            hold = _sig(mu + sv - ref[surf][1] + kh)     # calibrated to real holds where stats exist
            brk = 1 - _sig(mu + ref[surf][0] - rv + kh)
            rec[surf] = {"s": float(sv), "r": float(rv), "se_s": float(math.sqrt(max(vs, 0))),
                         "se_r": float(math.sqrt(max(vr, 0))), "n": n, "hold": hold, "break": brk,
                         "spw": _spw(hc, kp), "rpw": 1 - _spw(1 - bc, kp), "hold_chain": hc, "break_chain": bc}
        players[p] = rec
    return {"version": VERSION, "through": th.isoformat() if th else None, "constants": consts, "base": b,
            "players": players}


# ---------------------------------------------------------------------------------------------------------
# prediction from a fitted model
# ---------------------------------------------------------------------------------------------------------

def _player_sr(model: dict, pid: str, surface: str) -> tuple[float, float]:
    rec = (model.get("players") or {}).get(pid)
    if not rec:
        b = model.get("base") or {}
        return float(b.get("new_s", 0.0)), float(b.get("new_r", 0.0))
    x = rec.get(surface) or rec.get("all")
    return float(x["s"]), float(x["r"])


def base_logit(model: dict, surface: str, level: str | None = None, best_of: int = 3, indoor: bool = False) -> float:
    b = model.get("base") or {}
    surf = _io.fold_surface(surface)
    eta = float(b.get("mu", 1.0))
    if surf in ("clay", "grass"):
        eta += float(b.get(surf, 0.0))
    if indoor or str(surface or "").lower() == "carpet":
        eta += float(b.get("indoor", 0.0))
    if int(best_of or 3) == 5:
        eta += float(b.get("bo5", 0.0))
    if level is not None:
        eta += float((b.get("level") or {}).get(_io.fold_level(level), 0.0))
    return eta


def hold_prob(model: dict, server: str, returner: str, surface: str = "hard", level: str | None = None,
              best_of: int = 3, indoor: bool = False, calibrated: bool = False) -> float:
    """P(`server` holds against `returner`) under a fitted model; unknown players take the
    new-player averages. `level=None` uses the tour-average level. By default this is the chain-scale
    hold (the value whose iid point/game/set chain reproduces observed scorelines: use it for match
    pricing); calibrated=True adds the real-stats offset k_hold (display; zero without stats)."""
    surf = _io.fold_surface(surface)
    s, _ = _player_sr(model, server, surf)
    _, r = _player_sr(model, returner, surf)
    k = float((model.get("base") or {}).get("k_hold", 0.0)) if calibrated else 0.0
    return _sig(base_logit(model, surface, level, best_of, indoor) + s - r + k)


def serve_point_probs(model: dict, p1: str, p2: str, surface: str = "hard", level: str | None = None,
                      best_of: int = 3, indoor: bool = False) -> tuple[float, float]:
    """(P(p1 wins a point on serve), P(p2 wins a point on serve)) implied by the hold probabilities."""
    h1 = hold_prob(model, p1, p2, surface, level, best_of, indoor)
    h2 = hold_prob(model, p2, p1, surface, level, best_of, indoor)
    return float(point_prob_from_hold(h1)), float(point_prob_from_hold(h2))


def holds_for_matches(model: dict, matches: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    hA = np.array([hold_prob(model, m["p1"], m["p2"], m.get("surface"), m.get("level"), m.get("best_of") or 3,
                             bool(m.get("indoor"))) for m in matches])
    hB = np.array([hold_prob(model, m["p2"], m["p1"], m.get("surface"), m.get("level"), m.get("best_of") or 3,
                             bool(m.get("indoor"))) for m in matches])
    return hA, hB


def score_loglik(model: dict, matches: list[dict]) -> tuple[float, int, int]:
    """(sum of log P(scoreline), matches scored, sets scored) of `matches` under `model` (out of sample)."""
    rows = _prepare(matches, None, None, False)
    rows = [r for r in rows if r[3]]
    if not rows:
        return 0.0, 0, 0
    ms = [r[0] for r in rows]
    hA, hB = holds_for_matches(model, ms)
    S = _prep_sets([r[3] for r in rows])
    ll, _, _ = match_loglik_vec(hA, hB, S)
    return float(ll.sum()), len(rows), int(len(S["mi"]))


def _stats_row(st: dict | None):
    """(serve points won, serve points, games served, breaks) from a STATS record, or None."""
    try:
        n = int(st.get("sv_pts") or 0)
        k = int(st.get("fs_won") or 0) + int(st.get("ss_won") or 0)
        g = int(st.get("sv_gms") or 0)
        br = int(st.get("bp_faced") or 0) - int(st.get("bp_saved") or 0)
    except (TypeError, ValueError, AttributeError):
        return None
    if n < 20 or k > n or g < 3 or br < 0 or br > g:
        return None
    return k, n, g, br


def validate_stats(matches: list[dict], years: Iterable[int] | None = None, min_matches: int = 15, log=None,
                   **fit_kw) -> dict:
    """Score-inferred v real serve stats (the WTA check). For each year Y with stats, fit the score-only
    model and the stats model through 31 Dec Y, then compare on every stats match of Y (in sample) and of
    Y+1 January-June (out of sample): "raw" = score-only chain-scale hold and its iid SPW; "cal" = the
    same with the stats fit's tour offsets k_hold / k_spw (two numbers); "statsfit" = the stats model.
    Match level and player-season level (players with >= `min_matches` stats matches, sums weighted by
    games / points). Returns {"in_sample": {...}, "out_of_sample": {...}, "years", "offsets", ...}."""
    ys = sorted(set(years) if years is not None else {int(m["date"][:4]) for m in matches if m.get("stats")})
    rows = []
    prev = prevs = None
    offsets = {}
    for y in ys:
        th = date(y, 12, 31)
        mdl = fit(matches, th, stats=False, prior=prev, **fit_kw)
        mst = fit(matches, th, stats=True, prior=prevs, **fit_kw)
        prev, prevs = mdl, mst
        kh, kp = mst["base"].get("k_hold", 0.0), mst["base"].get("k_spw", 0.0)
        offsets[y] = {"k_hold": kh, "k_spw": kp, "mu_scores": mdl["base"]["mu"], "mu_stats": mst["base"]["mu"]}
        if log:
            log(y, offsets[y])
        for m in matches:
            ds = str(m.get("date") or "")
            oos = ds[:4] == str(y + 1) and ds[5:7] <= "06"
            if not (ds.startswith(str(y)) or oos) or not m.get("stats") or m.get("status") != "done":
                continue
            args = (m.get("surface"), m.get("level"), m.get("best_of") or 3, bool(m.get("indoor")))
            for who, a_, b_ in (("p1", m["p1"], m["p2"]), ("p2", m["p2"], m["p1"])):
                sr = _stats_row((m["stats"] or {}).get(who) or {})
                if sr is None:
                    continue
                h = hold_prob(mdl, a_, b_, *args)
                hs = hold_prob(mst, a_, b_, *args)
                rows.append((y, a_, h, _spw(h), _sig(math.log(h / (1 - h)) + kh), _spw(h, kp),
                             _sig(math.log(hs / (1 - hs)) + kh), _spw(hs, kp)) + sr + (oos,))
    out = {"years": ys, "offsets": offsets, "n_rows": len(rows)}
    if not rows:
        return out
    A = np.array([r[2:12] for r in rows], float)
    oos = np.array([r[12] for r in rows])
    spw, hold = A[:, 6] / A[:, 7], 1 - A[:, 9] / A[:, 8]
    out.update({"actual_mean_spw": float(spw.mean()), "actual_mean_hold": float(hold.mean()),
                "iid_hold_of_actual_spw": float(np.mean(game_hold(spw)))})

    def cmp(pred, act):
        if len(pred) < 3:
            return None
        return {"corr": float(np.corrcoef(pred, act)[0, 1]), "mae": float(np.mean(np.abs(pred - act))),
                "bias": float(np.mean(pred - act)), "n": int(len(pred))}

    names = ("raw", "cal", "statsfit")
    for lab, sel in (("in_sample", ~oos), ("out_of_sample", oos)):
        if not sel.any():
            continue
        rec = {"match": {}}
        for j, nm in enumerate(names):
            rec["match"][f"hold_{nm}"] = cmp(A[sel, 2 * j], hold[sel])
            rec["match"][f"spw_{nm}"] = cmp(A[sel, 2 * j + 1], spw[sel])
        agg: dict = {}
        for r, s_ in zip(rows, sel):
            if not s_:
                continue
            a = agg.setdefault((r[0], r[1]), np.zeros(11))
            n, g = r[9], r[10]
            a += [1, r[2] * g, r[3] * n, r[4] * g, r[5] * n, r[6] * g, r[7] * n, r[8], n, g - r[11], g]
        P = np.array([a for a in agg.values() if a[0] >= min_matches])
        if len(P):
            ah, asp = P[:, 9] / P[:, 10], P[:, 7] / P[:, 8]
            rec["player_season"] = {"n": int(len(P)), "min_matches": min_matches}
            for j, nm in enumerate(names):
                rec["player_season"][f"hold_{nm}"] = cmp(P[:, 1 + 2 * j] / P[:, 10], ah)
                rec["player_season"][f"spw_{nm}"] = cmp(P[:, 2 + 2 * j] / P[:, 8], asp)
        out[lab] = rec
    return out


# ---------------------------------------------------------------------------------------------------------
# rolling fits, cache, tuning, export
# ---------------------------------------------------------------------------------------------------------

def walk_forward(matches: list[dict], start: Any, end: Any, step_days: int = 7, **kw):
    """Yield (through, model) every `step_days` from `start` to `end`, each fit warm-started from the
    previous one (rolling window of `window_days`)."""
    t = _io.day(start)
    end = _io.day(end)
    prev = kw.pop("prior", None)
    while t <= end:
        mdl = fit(matches, through=t, prior=prev, **kw)
        yield t, mdl
        prev = mdl
        t = t + timedelta(days=int(step_days))


def constants(tour: str) -> dict:
    """Tuned constants for `tour` from models/fitted (DEFAULTS when absent)."""
    c = dict(DEFAULTS)
    f = _io.read_json(_io.FITTED / f"serve_return_{_io.tour_key(tour)}.json")
    if isinstance(f, dict) and isinstance(f.get("constants"), dict):
        c.update({k: v for k, v in f["constants"].items() if k in DEFAULTS})
    return c


def for_tour(tour: str, through: Any = None, stats: bool | None = None, use_cache: bool = True) -> dict:
    """The serve/return model of `tour` fitted on the stores through `through` (default: latest), with
    the tour's tuned constants (stats layer on for the WTA by default). Cached under
    <ACE_CACHE>/serve_return/; falls back to the committed fit when no stores are on disk."""
    t = _io.tour_key(tour)
    st = (t == "wta") if stats is None else bool(stats)
    sig = _io.signature(t)
    if not sig:
        f = _io.read_json(_io.FITTED / f"serve_return_{t}.json")
        return (f or {}).get("model") or fit([], through)
    c = constants(t)
    th = _io.day(through)
    key = _io.file_key(VERSION, sig, str(th), st, c)

    def build():
        ms = _io.load_matches(t, through=th)
        return fit(ms, th, c["half_life_days"], {"s": c["ridge"], "delta": c["ridge_delta"], "base": c["ridge_base"]},
                   stats=st, window_days=c["window_days"], stats_weight=c["stats_weight"])

    return _io.cached("serve_return", f"{t}_{th or 'latest'}_{'st' if st else 'sc'}", key, build, use_cache)


def tune(matches: list[dict], checkpoints: list[Any], horizon_days: int = 182,
         half_lives=(240, 365, 540), ridges=(1.0, 2.0, 4.0), delta_mult=(4.0,), log=None) -> dict:
    """Forward-validation grid: fit at each checkpoint, score the next `horizon_days` of scorelines
    (out-of-sample log-likelihood per set). Returns {"grid": [...], "best": {...}}."""
    grid = []
    for hl in half_lives:
        for lam in ridges:
            for dm in delta_mult:
                tot, nsets, prev = 0.0, 0, None
                t0 = time.time()
                for cp in checkpoints:
                    cpd = _io.day(cp)
                    mdl = fit(matches, cpd, hl, {"s": lam, "delta": lam * dm, "base": 1.0}, prior=prev,
                              window_days=max(4 * hl, 1095))
                    prev = mdl
                    fut = [m for m in matches if cpd < (_io.day(m.get("date")) or cpd) <= cpd + timedelta(days=horizon_days)
                           and str(m.get("level")) not in ("ch", "q")]
                    ll, _, ns = score_loglik(mdl, fut)
                    tot += ll
                    nsets += ns
                row = {"half_life_days": hl, "ridge": lam, "ridge_delta": lam * dm, "ll_per_set": tot / max(nsets, 1),
                       "sets": nsets, "secs": round(time.time() - t0, 1)}
                grid.append(row)
                if log:
                    log(row)
    best = max(grid, key=lambda g: g["ll_per_set"]) if grid else {}
    return {"grid": grid, "best": best}


def export_fits(tour: str, through: Any = None, tuned: dict | None = None, keep_days: int = 730,
                refit_elo: bool = True) -> dict:
    """Write models/fitted/serve_return_<tour>.json: the tuned constants and the latest fit (players
    seen in the last `keep_days`), and (refit_elo) models/fitted/elo_params_<tour>.json via elo.export_fits.
    Returns {"serve_return": path, "elo": path}."""
    from oddsmarkets.tennis.models import elo as _elo

    t = _io.tour_key(tour)
    path = _io.FITTED / f"serve_return_{t}.json"
    old = _io.read_json(path) or {}
    c = constants(t)
    if tuned:
        c.update({k: v for k, v in tuned.items() if k in DEFAULTS})
    ms = _io.load_matches(t, through=through)
    st = t == "wta"
    mdl = fit(ms, through, c["half_life_days"], {"s": c["ridge"], "delta": c["ridge_delta"], "base": c["ridge_base"]},
              stats=st, window_days=c["window_days"], stats_weight=c["stats_weight"])
    th = _io.day(mdl.get("through"))
    if th is not None:
        recent = {m["p1"] for m in ms if (th - _io.day(m["date"])).days <= keep_days} | \
                 {m["p2"] for m in ms if (th - _io.day(m["date"])).days <= keep_days}
        mdl["players"] = {p: v for p, v in mdl["players"].items() if p in recent}
    out = {"version": VERSION, "tour": t, "constants": c, "tuning": (tuned or old.get("tuning")),
           "model": mdl}
    _io.write_json(path, out, nd=4)
    ep = _elo.export_fits(t) if refit_elo else str(_io.FITTED / f"elo_params_{t}.json")
    return {"serve_return": str(path), "elo": ep}
