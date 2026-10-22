"""
Schedule and form terms of the match price (docs/research/tennis_edge.md sections 10.3 R4 and 11): six antisymmetric
features of a pairing, the exact definitions of research/features.py and research/experiment.design, computed in one
sequential pass over the MATCH rows on disk (every level and status, Challengers included when present):

    rest   log(days since the last match, clipped to 1..60; 60 without one): player 1 minus player 2
    m30    matches played in the 30 days before (walkovers not counted), difference clipped to +-15, / 5
    pts    log ranking points (the row's points; for a match not yet played, the player's latest points on an
           earlier row, else the store's ranking; 1 when unknown), difference
    form   an exponentially decayed mean of (result - Elo expectation), half-life 8 matches, difference x 5
    ret    1 when the player retired or was defaulted in the last match, difference
    h2h    (wins of 1 over 2 - wins of 2 over 1) / (total + 3), earlier meetings at any level, walkovers not counted

The price adds sum_k w_k x_k to the blend's logit (predict.py, weights "w_x" in models/fitted/predict_<tour>.json).
`history(tour, matches)` -> {"pre": {match id: [x for the row's p1]}, "current": {pid: state}, "h2h": {...}}.

Matches not yet played. `pair(state1, state2, h2h, day)` gives the exact features of a pairing on a known day.
The simulators price future rounds whose day is unknown with `assumed=True`: both players have played every
earlier round of the event, so rest and the retirement flag are taken as equal (difference 0) and the 30-day count,
points, form and head to head are the values at the start of the event. Section 11 measures what that costs on
the test years.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Iterable

from oddsmarkets.tennis.models import _io

VERSION = 1
FEATS = ("rest", "m30", "pts", "form", "ret", "h2h")
FORM_HL = 8.0
# switched on per tour by the promotion rule (tennis_edge.md section 11): the backtest fits "w_x" only when on
ON = {"atp": True, "wta": False}


def on(tour: str) -> bool:
    return bool(ON.get(_io.tour_key(tour)))


def _pts(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def _new() -> list:
    # [last day | None, last event, last retired flag, form num, form den, last points, recent days (list)]
    return [None, None, 0, 0.0, 0.0, None, []]


def features(s1: list | None, s2: list | None, h12: int, h21: int, day: int | None, pts1: Any = None,
             pts2: Any = None, assumed: bool = False) -> list[float]:
    """The six features for player 1 v player 2 on `day` (ordinal) from their states before the match."""
    s1 = s1 or _new()
    s2 = s2 or _new()
    if assumed or day is None:
        rest = 0.0
        ret = 0.0
    else:
        d1 = (day - s1[0]) if s1[0] is not None else 60
        d2 = (day - s2[0]) if s2[0] is not None else 60
        rest = math.log(min(60, max(1, d1))) - math.log(min(60, max(1, d2)))
        ret = float(s1[2]) - float(s2[2])
    ref = day if day is not None else max([x for x in (s1[0], s2[0]) if x is not None] or [0])
    n1 = sum(1 for x in s1[6] if x >= ref - 30)
    n2 = sum(1 for x in s2[6] if x >= ref - 30)
    m30 = max(-15.0, min(15.0, float(n1 - n2))) / 5.0
    p1 = _pts(pts1) or _pts(s1[5]) or 1.0
    p2 = _pts(pts2) or _pts(s2[5]) or 1.0
    pts = math.log(p1) - math.log(p2)
    f1 = s1[3] / (s1[4] + 1.0)
    f2 = s2[3] / (s2[4] + 1.0)
    form = (f1 - f2) * 5.0
    h2h = (h12 - h21) / (h12 + h21 + 3.0)
    return [rest, m30, pts, form, ret, h2h]


def run(matches: list[dict], elo_pre: dict[str, float], snap_days: dict[int, set] | None = None) -> dict:
    """One pass in (date, round, id) order: the pre-match features of every row, the final states, the head-to-head
    tallies, and optional snapshots {day: {pid: state}} taken before the first match on or after each day."""
    S: dict[str, list] = {}
    H: dict[tuple, int] = {}
    pre: dict[str, list] = {}
    snaps: dict[int, dict] = {}
    want = sorted(snap_days or {})
    wi = 0
    lam = 0.5 ** (1.0 / FORM_HL)
    for m in matches:
        p1, p2 = m.get("p1"), m.get("p2")
        d = _io.day(m.get("date"))
        if not p1 or not p2 or d is None:
            continue
        p1, p2 = str(p1), str(p2)
        o = d.toordinal()
        while wi < len(want) and want[wi] <= o:
            snaps[want[wi]] = _snap(S, H, snap_days[want[wi]])
            wi += 1
        a = S.setdefault(p1, _new())
        b = S.setdefault(p2, _new())
        for x in (a, b):
            while x[6] and x[6][0] < o - 30:
                x[6].pop(0)
        pre[str(m.get("id"))] = [round(v, 6) for v in features(a, b, H.get((p1, p2), 0), H.get((p2, p1), 0), o,
                                                               m.get("pts1"), m.get("pts2"))]
        st = m.get("status")
        if st in ("upcoming", "live", None):
            continue
        win = str(m.get("winner") or "")
        for x, pt in ((a, m.get("pts1")), (b, m.get("pts2"))):
            if _pts(pt):
                x[5] = float(pt)
        if st == "wo":
            continue
        for x, pid in ((a, p1), (b, p2)):
            x[6].append(o)
            x[0], x[1] = o, m.get("event")
            x[2] = int(st in ("ret", "def") and pid != win)
        if win not in (p1, p2):
            continue
        loser = p2 if win == p1 else p1
        H[(win, loser)] = H.get((win, loser), 0) + 1
        pe = elo_pre.get(str(m.get("id")))
        if pe is not None:
            for x, res, ex in ((a, float(win == p1), pe), (b, float(win == p2), 1.0 - pe)):
                x[3] = lam * x[3] + (res - ex)
                x[4] = lam * x[4] + 1.0
    while wi < len(want):
        snaps[want[wi]] = _snap(S, H, snap_days[want[wi]])
        wi += 1
    return {"pre": pre, "current": S, "h2h": H, "snaps": snaps}


def _copy(x: list) -> list:
    return x[:6] + [list(x[6])]


def _snap(S: dict, H: dict, pids: set) -> dict:
    """{"current": states of `pids`, "h2h": their tallies against each other} (the shape Context.x_vec reads)."""
    ps = [p for p in pids if p in S]
    h = {}
    for a in ps:
        for b in ps:
            n = H.get((a, b))
            if n:
                h[f"{a}|{b}"] = n
    return {"current": {p: _copy(S[p]) for p in ps}, "h2h": h}


def snapshots(matches: list[dict], elo_hist: dict | None, wants: dict[int, set]) -> dict[int, dict]:
    """{day ordinal: {"current", "h2h"}} for the players in wants[day], before the first match on or after that day
    (one pass; the backtest's tournament checkpoints)."""
    from oddsmarkets.tennis.models import elo as E
    ep = E.pre_match(elo_hist) if elo_hist else {}
    return run(sorted(matches, key=_io.match_key), ep, wants)["snaps"]


def history(tour: str, matches: list[dict] | None = None, elo_pre: dict | None = None, use_cache: bool = True) -> dict:
    """{"version", "pre", "current", "h2h": {"a|b": wins}} over the MATCH rows given (sorted here), else every row on
    disk; `elo_pre` = elo.pre_match of the same rows (computed when absent)."""
    t = _io.tour_key(tour)

    def go(ms):
        ms = sorted(ms, key=_io.match_key)
        ep = elo_pre
        if ep is None:
            from oddsmarkets.tennis.models import elo as E
            ep = E.pre_match(E.history(t, matches=[m for m in ms if m.get("status") in _io.RATED_STATUS]))
        r = run(ms, ep)
        return {"version": VERSION, "tour": t, "pre": r["pre"], "current": r["current"],
                "h2h": {f"{a}|{b}": n for (a, b), n in r["h2h"].items()}}

    if matches is not None:
        return go(matches)
    key = _io.file_key(VERSION, _io.signature(t))
    return _io.cached("sched", t, key, lambda: go(_io.load_matches(t, statuses=None)), use_cache)


def h2h_counts(hist: dict, p1: str, p2: str) -> tuple[int, int]:
    h = hist.get("h2h") or {}
    return int(h.get(f"{p1}|{p2}", 0)), int(h.get(f"{p2}|{p1}", 0))


def dot(x: Iterable[float], w: dict | None) -> float:
    """sum_k w_k x_k with the weights {"rest": .., ...} (0 without weights)."""
    if not w:
        return 0.0
    return float(sum(float(w.get(k) or 0.0) * float(v) for k, v in zip(FEATS, x)))
