"""
Market rating: each player's strength as the betting market priced it, learnt from the de-vigged closing prices of
matches already played (docs/research/tennis_edge.md, "Model-improvement program, Oct 2026").

A Kalman filter on the logit scale. Player i carries an overall rating R_i (variance P_i) and an offset per surface
D_i,S (variance Q_i,S; hard, clay, grass; carpet folds into hard). For a match on surface S, best of b:

    d     = (R_i + D_i,S) - (R_j + D_j,S)                     the market-rating difference (logit, best of 3)
    p     = sigmoid(s_b * d),  s_b = 1 for best of 3, `s5` for best of 5
    V     = P_i + Q_i,S + P_j + Q_j,S

After the match, two updates, in order:

1. the closing price (when the match has one that passes a sanity check): z = logit(p_close) / s_b, de-vigged by
   the power method from the first book present in `books`; e = z - d; every state moves by its variance over
   (V + r_obs) times e (signs by side) and its variance shrinks the Kalman way;
2. the result (done, retired at half weight; walkovers never): an approximate Bayesian logistic step on the
   difference, shift = k_res * V s_b (y - p) / (1 + V s_b^2 p (1 - p)), shared by variance; the variances shrink by
   the matching information. k_res = 1 is the plain Laplace update; it is tuned (the close already contains most
   of what the result says about the player).

Between matches every variance grows by q per day idle (capped at its prior), the surface offsets by q_s. A new
player starts at R = -c1 (ln rank - ln 100) (the MATCH row's rank, `unranked` when missing), P = p0, offsets 0 with
variance ps0. Matches without a closing price (qualifying, Challengers / WTA 125, matches tennis-data does not
price) still move the ratings through the result step, which is where most newcomers are first seen.

`prepare(matches)` reduces MATCH rows (sorted by date, round, id) to compact tuples; `run(prepared, prm)` returns
{"pre": {id: (d, V)}, "current": {pid: [R, P, D_h, D_c, D_g, Q_h, Q_c, Q_g, last day, n market obs, n results]}};
`history(tour)` caches both per tour; `diff(r1, r2, surface)` prices a pair from current states.
Everything a match sees comes from matches strictly before it in that order (its own close is used only after it).
"""
from __future__ import annotations

import math
from typing import Any, Iterable

from oddsmarkets.tennis.models import _io

VERSION = 1
BOOKS = ("ps", "bfe", "avg", "b365", "max")
SURF = {"hard": 0, "clay": 1, "grass": 2}
# chosen on the dev years 2012-2017 only (coordinate search; docs/research/tennis_edge.md, Oct 2026 section);
# `BOOKS` is the order in which a match's closing price is taken
PARAMS = {
    "atp": {"q": 0.001, "r_obs": 0.3, "k_res": 1.25, "p0": 4.0, "ps0": 0.2, "q_s": 0.00003, "c1": 1.0,
            "unranked": 400.0, "s5": 1.4, "max_margin": 0.12},
    "wta": {"q": 0.002, "r_obs": 0.5, "k_res": 0.8, "p0": 1.5, "ps0": 0.05, "q_s": 0.001, "c1": 1.2,
            "unranked": 800.0, "s5": 1.0, "max_margin": 0.12},
}
DEFAULTS = PARAMS["atp"]


def params(tour: str) -> dict:
    return dict(PARAMS[_io.tour_key(tour)])


def _power_p1(a: float, b: float) -> float:
    """P(first) from a two-way decimal pair, power de-vig ((1/a)^k + (1/b)^k = 1)."""
    ia, ib = 1.0 / a, 1.0 / b
    lo, hi = 0.3, 3.0
    for _ in range(40):
        k = 0.5 * (lo + hi)
        if ia ** k + ib ** k > 1.0:
            lo = k
        else:
            hi = k
    return ia ** (0.5 * (lo + hi))


def close_p1(odds: dict | None, books: Iterable[str] = BOOKS, max_margin: float = 0.12) -> float | None:
    """De-vigged closing P(p1) from the first sane book in `books` (margin in [0, max_margin])."""
    for k in books:
        o = (odds or {}).get(k)
        try:
            a, b = float(o[0]), float(o[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (a > 1.0 and b > 1.0 and math.isfinite(a) and math.isfinite(b)):
            continue
        ov = 1.0 / a + 1.0 / b
        if not (1.0 <= ov <= 1.0 + max_margin):
            continue
        return _power_p1(a, b)
    return None


def _rank(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v >= 1 else None


def prepare(matches: Iterable[dict], books: Iterable[str] = BOOKS, max_margin: float = 0.12) -> list[tuple]:
    """(id, day ordinal, p1, p2, surface index, best of 5, status code, y for p1, close P(p1) or None, rank1, rank2)
    for every MATCH row with two players and a date; status code 1 done, 2 ret/def, 0 anything else (no result step:
    walkovers, upcoming, live)."""
    books = tuple(books)
    out = []
    for m in matches:
        p1, p2 = m.get("p1"), m.get("p2")
        d = _io.day(m.get("date"))
        if not p1 or not p2 or p1 == p2 or d is None:
            continue
        p1, p2 = str(p1), str(p2)
        st = m.get("status")
        code = 1 if st == "done" else (2 if st in ("ret", "def") else 0)
        w = str(m.get("winner") or "")
        if code and w not in (p1, p2):
            code = 0
        y = 1.0 if w == p1 else 0.0
        cp = close_p1(m.get("odds"), books, max_margin) if code or st == "wo" else None
        if st == "wo":
            cp = None
        out.append((m.get("id"), d.toordinal(), p1, p2, SURF[_io.fold_surface(m.get("surface"))],
                    int(m.get("best_of") or 3) == 5, code, y, cp, _rank(m.get("rank1")), _rank(m.get("rank2"))))
    return out


def _new(prm: dict, rank: float | None, day: int) -> list:
    r = rank if rank is not None else prm["unranked"]
    R = -prm["c1"] * (math.log(r) - math.log(100.0))
    s0 = prm["ps0"]
    return [R, prm["p0"], 0.0, 0.0, 0.0, s0, s0, s0, day, 0, 0]


def _age(x: list, day: int, prm: dict) -> None:
    gap = day - x[8]
    if gap > 0:
        x[1] = min(prm["p0"], x[1] + prm["q"] * gap)
        for k in (5, 6, 7):
            x[k] = min(prm["ps0"], x[k] + prm["q_s"] * gap)
        x[8] = day


def run(prep: list[tuple], prm: dict, day_lag: bool = True) -> dict:
    """Every match of a day is priced from the states at the end of the day before (`day_lag`, the default): the
    WTA stores hold some matches twice on one date under two events (a WTA 125 row and a tour-level row, or two
    seasons' stores across New Year), and a strictly sequential pass let the twin's result into the price (WTA test years:
    0.556 log-loss on the 4 % of matches with a same-day earlier match, against Pinnacle's 0.608). False is the plain
    sequential pass (date, round, id)."""
    S: dict[str, list] = {}
    pre: dict = {}
    buf: list = []
    if not day_lag:
        _step(prep, S, prm, pre, buf)
        return {"pre": pre, "current": S}
    i, n = 0, len(prep)
    while i < n:
        j = i
        while j < n and prep[j][1] == prep[i][1]:
            j += 1
        day = prep[i][1]
        for rec in prep[i:j]:                     # price the whole day first, then apply its updates in order
            for pid, rk in ((rec[2], rec[9]), (rec[3], rec[10])):
                if pid not in S:
                    S[pid] = _new(prm, rk, day)
                _age(S[pid], day, prm)
            a, b = S[rec[2]], S[rec[3]]
            ds, vs = 2 + rec[4], 5 + rec[4]
            pre[rec[0]] = ((a[0] + a[ds]) - (b[0] + b[ds]), a[1] + a[vs] + b[1] + b[vs])
        _step(prep[i:j], S, prm, {}, buf)
        i = j
    return {"pre": pre, "current": S}


def _obs(a: list, b: list, si: int, s: float, cp: float, r_obs: float) -> None:
    """Kalman update of both players' overall and surface states on the de-vigged close P(a) = cp."""
    ds, vs = 2 + si, 5 + si
    d = (a[0] + a[ds]) - (b[0] + b[ds])
    Sv = a[1] + a[vs] + b[1] + b[vs] + r_obs
    e = math.log(cp / (1.0 - cp)) / s - d
    for x, sg in ((a, 1.0), (b, -1.0)):
        g1, g2 = x[1] / Sv, x[vs] / Sv
        x[0] += sg * g1 * e
        x[ds] += sg * g2 * e
        x[1] -= x[1] * g1
        x[vs] -= x[vs] * g2
        x[9] += 1


def _step(prep: list[tuple], S: dict, prm: dict, pre: dict, buf: list | None = None) -> None:
    r_obs = float(prm["r_obs"])
    k_res = float(prm["k_res"])
    s5 = float(prm["s5"])
    lag = int(prm.get("obs_lag") or 0)          # research only: closes become known `lag` days after the match
    if buf is None:
        buf = []
    for (mid, day, p1, p2, si, bo5, code, y, cp, rk1, rk2) in prep:
        if buf and buf[0][0] <= day:
            keep = []
            for it in buf:
                if it[0] <= day:
                    _obs(S[it[1]], S[it[2]], it[3], it[4], it[5], r_obs)
                else:
                    keep.append(it)
            buf[:] = keep
        a = S.get(p1)
        if a is None:
            a = S[p1] = _new(prm, rk1, day)
        b = S.get(p2)
        if b is None:
            b = S[p2] = _new(prm, rk2, day)
        _age(a, day, prm)
        _age(b, day, prm)
        ds = 2 + si
        vs = 5 + si
        pre[mid] = ((a[0] + a[ds]) - (b[0] + b[ds]), a[1] + a[vs] + b[1] + b[vs])
        s = s5 if bo5 else 1.0
        if cp is not None and 0.0 < cp < 1.0:
            if lag > 0:
                buf.append((day + lag, p1, p2, si, s, cp))
            else:
                _obs(a, b, si, s, cp, r_obs)
        if code and k_res > 0:
            d = (a[0] + a[ds]) - (b[0] + b[ds])
            V = a[1] + a[vs] + b[1] + b[vs]
            wgt = 1.0 if code == 1 else 0.5
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, s * d))))
            info = s * s * p * (1.0 - p)
            den = 1.0 + V * info
            shift = wgt * k_res * s * (y - p) / den          # per unit variance
            shrink = wgt * k_res * info / den
            for x, sg in ((a, 1.0), (b, -1.0)):
                x[0] += sg * x[1] * shift
                x[ds] += sg * x[vs] * shift
                x[1] *= max(0.05, 1.0 - x[1] * shrink)          # floor: k_res > 1 must not flip a variance's sign
                x[vs] *= max(0.05, 1.0 - x[vs] * shrink)
                x[10] += 1


def scale(best_of: Any, prm: dict | None = None) -> float:
    return float((prm or DEFAULTS)["s5"]) if int(best_of or 3) == 5 else 1.0


def p_win(d: float, best_of: int = 3, prm: dict | None = None) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, scale(best_of, prm) * d))))


def history(tour: str, matches: list[dict] | None = None, use_cache: bool = True, prm: dict | None = None) -> dict:
    """{"version","params","pre": {match id: [d for the row's p1, V]}, "current": {pid: state}} over the MATCH rows
    given (sorted here by date, round, id), else every row on disk (all statuses)."""
    t = _io.tour_key(tour)
    p = dict(prm or params(t))

    def go(ms):
        r = run(prepare(sorted(ms, key=_io.match_key), max_margin=p["max_margin"]), p)
        return {"version": VERSION, "params": p, "tour": t,
                "pre": {k: [round(v[0], 6), round(v[1], 6)] for k, v in r["pre"].items()},
                "current": {k: [round(float(x), 6) for x in v] for k, v in r["current"].items()}}

    if matches is not None:
        return go(matches)
    key = _io.file_key(VERSION, _io.signature(t), p)
    return _io.cached("mrating", t, key, lambda: go(_io.load_matches(t, statuses=None)), use_cache)


def pre_match(hist: dict) -> dict[str, float]:
    """{match id: pre-match market-rating difference d for the row's p1 (best-of-3 logit scale)}."""
    return {k: float(v[0]) for k, v in (hist.get("pre") or {}).items()}


def prior(prm: dict | None = None, rank: float | None = None) -> list:
    """The state of a player never seen (rank prior; `unranked` without a rank)."""
    return _new(prm or DEFAULTS, rank, 0)


def rating(state: list | None, surface: str = "hard", prm: dict | None = None) -> float:
    x = state or prior(prm)
    return float(x[0]) + float(x[2 + SURF[_io.fold_surface(surface)]])


def diff(s1: list | None, s2: list | None, surface: str = "hard", prm: dict | None = None) -> float:
    """Market-rating difference d of player 1 over player 2 (best-of-3 logit scale) from their states; a player
    never seen takes the unranked prior, as the sequential pass would at a first match without a rank."""
    return rating(s1, surface, prm) - rating(s2, surface, prm)


def snapshots(prep: list[tuple], prm: dict, wants: dict[int, set]) -> dict[int, dict[str, list]]:
    """{day ordinal: {pid: state}} for the players in wants[day], taken before the first match on or after that day
    (one pass; players not yet seen are left out)."""
    S: dict[str, list] = {}
    out: dict[int, dict[str, list]] = {}
    i, n = 0, len(prep)
    for W in sorted(wants):
        j = i
        while j < n and prep[j][1] < W:
            j += 1
        if j > i:
            _step(prep[i:j], S, prm, {}, [])
        i = j
        out[W] = {p: list(S[p]) for p in wants[W] if p in S}
    return out
