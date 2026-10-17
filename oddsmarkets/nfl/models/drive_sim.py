"""
Drive-level Monte Carlo: score distributions, team totals and the margin from unit ratings and field position.

Drive outcome model (fitted by `fit` on play-by-play drives, `_cdata.drive_rows`)
    classes  TD, FG, PUNT (reference), TO (interception / fumble lost), DOWNS, MISS (missed field goal), HALF (clock
             runs out), SAFETY, OPPTD (defensive / return touchdown)
    logit_k = a_k + b_k * s + c_k * s^2 + d_k * x,      s = (start - 70) / 20,  start = yards from the opponent end zone
    x = the offence's expected EPA/play edge in the game: (NP (PO + PD_opp) + NR (RO + RD_opp)) / (NP + NR) from the
        walk-forward ratings (0 when the drives are fitted without ratings).
    Multinomial logit, maximum likelihood (L-BFGS, ridge 1e-3).

Game flow (vectorised over simulations)
    Each half has N drives (N ~ the empirical distribution of drives per half, both teams together), alternating
    possession; the second half starts with the team that did not receive the opening kickoff. The next drive's start
    is drawn from the empirical distribution of starts after the previous drive's result (kickoff after a score or at
    a half; punt; turnover; downs; missed field goal; safety free kick), from the most recent seasons fitted.
    Points: TD = 6 + try (kick made with P_XP by era, 2-point attempt at rate P_2PT with success 0.48); FG 3;
    SAFETY 2 to the defence (which then receives); OPPTD 7 to the defence (which then kicks off: the offence keeps
    the next possession).
    Overtime by season and game type: regular season sudden death to 2011; modified sudden death (a first-possession
    field goal gives the other team a possession) 2012-2024 with 10-minute periods from 2017; from 2025 both teams
    possess. Playoffs: sudden death to 2009, modified 2010-2021, both possess from 2022, and play continues until a
    winner. A regular-season period lasts at most 5 drives (15 minutes) or 4 (10 minutes), then a tie.

Calibration to the game model: `calibrate(pts_h, pts_a, ...)` shifts each side's x so the simulated mean points
equal the game model's team points (two secant iterations on the expected points per drive), so the drive simulation
supplies the shape (key numbers, team totals, correlations) and the game model the means.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _cdata as D

logger = logging.getLogger(__name__)

VERSION = 1
CLASSES = ("TD", "FG", "PUNT", "TO", "DOWNS", "MISS", "HALF", "SAFETY", "OPPTD")
REF = CLASSES.index("PUNT")
NEXT_KEYS = ("KICK", "PUNT", "TO", "DOWNS", "MISS", "SAFETY")      # what the next drive starts after
P_2PT = 0.10
P_2PT_MAKE = 0.48


def p_xp(season: int) -> float:
    return 0.99 if season < 2015 else 0.94


def _next_key(result: str) -> str:
    return {"TD": "KICK", "FG": "KICK", "OPPTD": "KICK", "HALF": "KICK", "PUNT": "PUNT", "TO": "TO", "DOWNS": "DOWNS",
            "MISS": "MISS", "SAFETY": "SAFETY"}.get(result, "KICK")


def _design(start: np.ndarray, x: np.ndarray) -> np.ndarray:
    s = (np.asarray(start, float) - 70.0) / 20.0
    return np.column_stack([np.ones_like(s), s, s * s, np.asarray(x, float)])


def default_model() -> dict:
    """Plausible coefficients (fit on 2022-2025 drives without ratings, rounded) and start distributions."""
    coef = np.zeros((len(CLASSES), 4))
    base = {"TD": (-0.60, -0.95, 0.20, 2.5), "FG": (-0.95, -1.15, -0.10, 1.0), "TO": (-1.25, -0.30, 0.05, -1.5),
            "DOWNS": (-1.85, -0.45, 0.10, -0.8), "MISS": (-2.70, -0.75, -0.30, 0.0), "HALF": (-1.80, -0.40, 0.30, 0.0),
            "SAFETY": (-6.0, 2.5, 0.0, -1.0), "OPPTD": (-3.4, 0.25, 0.0, -1.5)}
    for k, v in base.items():
        coef[CLASSES.index(k)] = v
    starts = {"KICK": (71.6, 8.5), "PUNT": (75.5, 15.0), "TO": (53.0, 24.0), "DOWNS": (62.0, 21.0), "MISS": (62.0, 9.0),
              "SAFETY": (58.0, 18.0)}
    hist = {}
    grid = np.arange(1, 100)
    for k, (m, sd) in starts.items():
        p = np.exp(-0.5 * ((grid - m) / sd) ** 2)
        hist[k] = (p / p.sum()).tolist()
    return {"coef": coef.tolist(), "start_hist": hist, "drives_half": {"mean": 10.7, "sd": 2.1}, "fitted": False}


_MODEL: dict | None = None


def model() -> dict:
    global _MODEL
    if _MODEL is None:
        m = default_model()
        for path in (D.c_cache() / "drive_model.json", D.FITTED / "drive_model.json"):
            c = D.read_json(path)
            if c:
                m.update(c.get("result") or c)
                break
        _MODEL = m
    return _MODEL


def set_model(m: dict | None) -> None:
    global _MODEL
    _MODEL = m


# ── fitting ──────────────────────────────────────────────────────────────────

def fit(drives: pd.DataFrame, x: np.ndarray | None = None, ridge: float = 1e-3, recent: pd.DataFrame | None = None) -> dict:
    """Multinomial logit of drive results on start and x; start histograms from `recent` (default: `drives`)."""
    from scipy.optimize import minimize
    d = drives[drives["result"].isin(CLASSES)]
    y = d["result"].map({k: i for i, k in enumerate(CLASSES)}).to_numpy(int)
    xx = np.zeros(len(d)) if x is None else np.asarray(x, float)[drives["result"].isin(CLASSES).to_numpy()]
    X = _design(d["start"].to_numpy(float), xx)
    K, P = len(CLASSES), X.shape[1]
    free = [k for k in range(K) if k != REF]
    Y = np.zeros((len(y), K))
    Y[np.arange(len(y)), y] = 1.0
    fit_x = x is not None

    def unpack(th):
        B = np.zeros((K, P))
        B[free] = th.reshape(len(free), P)
        if not fit_x:
            B[:, 3] = 0.0
        return B

    def nll(th):
        B = unpack(th)
        Z = X @ B.T
        Z -= Z.max(1, keepdims=True)
        lse = np.log(np.exp(Z).sum(1))
        ll = (Y * Z).sum() - lse.sum()
        Pm = np.exp(Z - lse[:, None])
        G = (Y - Pm).T @ X                       # K x P
        g = -G[free].ravel() + 2 * ridge * th
        if not fit_x:
            g = g.reshape(len(free), P)
            g[:, 3] = 0.0
            g = g.ravel()
        return -ll + ridge * (th ** 2).sum(), g

    th0 = np.zeros(len(free) * P)
    res = minimize(nll, th0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    B = unpack(res.x)
    out = {"coef": B.tolist(), "n": int(len(d)), "nll": float(res.fun) / max(len(d), 1), "fitted": True,
           "uses_x": bool(fit_x)}
    rec = recent if recent is not None else drives
    out.update(_starts(rec))
    return out


def _starts(d: pd.DataFrame) -> dict:
    """Empirical next-drive start histograms and drives per half."""
    d = d.sort_values(["game_id", "fixed_drive"] if "fixed_drive" in d else ["game_id"]).copy()
    if "qtr" in d:
        d["half"] = np.where(d["qtr"] <= 2, 1, np.where(d["qtr"] <= 4, 2, 3))
    else:
        d["half"] = 1
    d["prev"] = d.groupby(["game_id", "half"])["result"].shift(1)
    d["key"] = d["prev"].fillna("HALF").map(_next_key)
    hist = {}
    grid = np.arange(1, 100)
    base = default_model()["start_hist"]
    for k in NEXT_KEYS:
        s = d.loc[d["key"] == k, "start"].to_numpy(float)
        if len(s) >= 40:
            h = np.bincount(np.clip(s.astype(int), 1, 99) - 1, minlength=99).astype(float) + 0.2
            hist[k] = (h / h.sum()).tolist()
        else:
            hist[k] = base[k]
    per = d[d["half"] <= 2].groupby(["game_id", "half"]).size()
    dh = {"mean": float(per.mean()) if len(per) else 10.7, "sd": float(per.std()) if len(per) > 1 else 2.1}
    return {"start_hist": hist, "drives_half": dh}


def save(m: dict, committed: bool = False) -> None:
    obj = {"version": VERSION, "result": m}
    D.write_json(D.c_cache() / "drive_model.json", obj)
    if committed:
        D.write_json(D.FITTED / "drive_model.json", obj)
    set_model(None)


# ── simulation ───────────────────────────────────────────────────────────────

def outcome_probs(start: np.ndarray, x: np.ndarray, m: dict | None = None) -> np.ndarray:
    m = m or model()
    B = np.asarray(m["coef"], float)
    Z = _design(start, x) @ B.T
    Z -= Z.max(1, keepdims=True)
    E = np.exp(Z)
    return E / E.sum(1, keepdims=True)


_PTS = {"TD": 6, "FG": 3, "SAFETY": -2, "OPPTD": -7}


def _try_points(n: int, season: int, rng) -> np.ndarray:
    go2 = rng.random(n) < P_2PT
    made2 = rng.random(n) < P_2PT_MAKE
    xp = rng.random(n) < p_xp(season)
    return np.where(go2, np.where(made2, 2, 0), np.where(xp, 1, 0))


def _ot_rule(season: int, playoff: bool) -> str:
    if playoff:
        return "sudden" if season < 2010 else ("modified" if season < 2022 else "both")
    if season < 2012:
        return "sudden"
    return "modified" if season < 2025 else "both"


def simulate(x_h: float, x_a: float, n: int = 20000, season: int = 2026, playoff: bool = False, seed: int = 0,
             m: dict | None = None, drives_half: int | None = None) -> dict:
    """Scores of n simulated games: {"hs", "as" (int arrays), "ot" (bool array)}."""
    m = m or model()
    rng = np.random.default_rng(seed)
    hist = {k: np.asarray(v, float) for k, v in m["start_hist"].items()}
    cdfs = {k: np.cumsum(v / v.sum()) for k, v in hist.items()}
    key_id = {k: i for i, k in enumerate(NEXT_KEYS)}
    cdf_mat = np.stack([cdfs[k] for k in NEXT_KEYS])
    B = np.asarray(m["coef"], float)
    xs = np.array([x_h, x_a])
    pts = np.zeros((n, 2), int)
    receiver0 = (rng.random(n) < 0.5).astype(int)          # team receiving the opening kickoff (0 home, 1 away)
    dh = m.get("drives_half") or {"mean": 10.7, "sd": 2.1}
    cls_pts = np.array([_PTS.get(c, 0) for c in CLASSES])
    NK = np.array([key_id[_next_key(c)] for c in CLASSES])

    def draw_start(keys: np.ndarray) -> np.ndarray:
        u = rng.random(len(keys))
        return 1 + (cdf_mat[keys] < u[:, None]).sum(1)

    def play_drives(poss: np.ndarray, start: np.ndarray, active: np.ndarray):
        """One drive for the active sims; returns (result class, next key) and updates pts."""
        Z = _design(start, xs[poss]) @ B.T
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(1, keepdims=True)
        u = rng.random(len(poss))
        c = (P.cumsum(1) < u[:, None]).sum(1)
        c = np.minimum(c, len(CLASSES) - 1)
        p = cls_pts[c]
        td = c == CLASSES.index("TD")
        p = np.where(td, p + _try_points(len(c), season, rng), p)
        ar = np.nonzero(active)[0]
        off_pts = np.where(p > 0, p, 0)
        def_pts = np.where(p < 0, -p, 0)
        np.add.at(pts, (ar, poss), off_pts)
        np.add.at(pts, (ar, 1 - poss), def_pts)
        return c

    for half in (0, 1):
        nd = drives_half if drives_half is not None else None
        N = np.full(n, nd) if nd is not None else np.maximum(4, np.rint(rng.normal(dh["mean"], dh["sd"], n))).astype(int)
        poss = receiver0 if half == 0 else 1 - receiver0
        start = draw_start(np.full(n, key_id["KICK"]))
        for k in range(int(N.max())):
            active = N > k
            if not active.any():
                break
            ia = np.nonzero(active)[0]
            c = play_drives(poss[ia], start[ia], active)
            names = np.array(CLASSES)[c]
            nk = np.array([key_id[_next_key(s)] for s in names]) if len(c) < 64 else \
                np.vectorize(lambda s: key_id[_next_key(s)])(names)
            keep = c == CLASSES.index("OPPTD")          # the defence scored and kicks off: offence has it again
            newposs = np.where(keep, poss[ia], 1 - poss[ia])
            poss = poss.copy()
            poss[ia] = newposs
            start = start.copy()
            start[ia] = draw_start(nk)
    ot = pts[:, 0] == pts[:, 1]
    rule = _ot_rule(season, playoff)
    if ot.any():
        idx = np.nonzero(ot)[0]
        max_drives = 99 if playoff else (5 if season < 2017 else 4)
        _overtime(idx, pts, rule, max_drives, xs, B, cdf_mat, key_id, rng, season, playoff)
    return {"hs": pts[:, 0], "as": pts[:, 1], "ot": ot}


def _overtime(idx, pts, rule, max_drives, xs, B, cdf_mat, key_id, rng, season, playoff):
    """Overtime for the tied simulations (loops per drive over the still-tied subset)."""
    n = len(idx)
    poss = (rng.random(n) < 0.5).astype(int)
    first = poss.copy()
    start = 1 + (cdf_mat[np.full(n, key_id["KICK"])] < rng.random(n)[:, None]).sum(1)
    open_ = np.ones(n, bool)
    had = np.zeros((n, 2), bool)
    score = np.zeros((n, 2), int)
    drives = 0
    while open_.any() and drives < max_drives:
        ia = np.nonzero(open_)[0]
        Z = _design(start[ia], xs[poss[ia]]) @ B.T
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(1, keepdims=True)
        c = np.minimum((P.cumsum(1) < rng.random(len(ia))[:, None]).sum(1), len(CLASSES) - 1)
        names = np.array(CLASSES)[c]
        pt = np.array([_PTS.get(s, 0) for s in names])
        pt = np.where(names == "TD", 6 + np.where(rng.random(len(ia)) < p_xp(season), 1, 0), pt)
        p_off = np.where(pt > 0, pt, 0)
        p_def = np.where(pt < 0, -pt, 0)
        score[ia, poss[ia]] += p_off
        score[ia, 1 - poss[ia]] += p_def
        had[ia, poss[ia]] = True
        d = score[ia, 0] - score[ia, 1]
        both = had[ia].all(1)
        if rule == "sudden":
            done = d != 0
        elif rule == "modified":
            # a first-possession TD (or defensive score) ends it; otherwise the first score once both possessed,
            # or any score by the second team, ends it
            first_pos = ~had[ia, 1 - first[ia]]
            td_first = first_pos & ((names == "TD") | (names == "OPPTD") | (names == "SAFETY"))
            done = (d != 0) & (~first_pos | td_first)
        else:   # both teams possess unless the first possession ends in a defensive score
            def_score = (names == "OPPTD") | (names == "SAFETY")
            first_pos = ~had[ia, 1 - first[ia]]
            done = (d != 0) & (both | (first_pos & def_score))
        open_[ia[done]] = False
        keep = names == "OPPTD"
        poss[ia] = np.where(keep, poss[ia], 1 - poss[ia])
        keys = np.array([key_id[_next_key(s)] for s in names])
        start[ia] = 1 + (cdf_mat[keys] < rng.random(len(ia))[:, None]).sum(1)
        drives += 1
        if playoff and drives >= max_drives and open_.any():
            max_drives += 2
    pts[idx] += score


def summarise(res: dict, spread_home: float | None = None, total_line: float | None = None) -> dict:
    hs, as_ = res["hs"], res["as"]
    m = hs - as_
    t = hs + as_
    n = len(m)
    out = {"p_home": float((m > 0).mean()), "p_tie": float((m == 0).mean()), "p_away": float((m < 0).mean()),
           "mean_margin": float(m.mean()), "mean_total": float(t.mean()), "sd_margin": float(m.std()),
           "sd_total": float(t.std()), "pts_h": float(hs.mean()), "pts_a": float(as_.mean()), "p_ot": float(res["ot"].mean()),
           "margin_pmf": {int(k): round(v / n, 5) for k, v in zip(*np.unique(np.clip(m, -40, 40), return_counts=True))},
           "total_q": {q: float(np.quantile(t, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)},
           "team_q": {"home": {q: float(np.quantile(hs, q)) for q in (0.1, 0.5, 0.9)},
                      "away": {q: float(np.quantile(as_, q)) for q in (0.1, 0.5, 0.9)}}}
    if spread_home is not None:
        a = m + float(spread_home)
        out["cover"] = {"home": float((a > 0).mean()), "push": float((a == 0).mean()), "away": float((a < 0).mean())}
    if total_line is not None:
        out["over"] = {"over": float((t > total_line).mean()), "push": float((t == total_line).mean()),
                       "under": float((t < total_line).mean())}
    return out


def expected_points_per_drive(x: float, m: dict | None = None, season: int = 2026) -> float:
    """Expected net points of one drive at the kickoff start distribution (TD worth 6 + expected try)."""
    m = m or model()
    h = np.asarray(m["start_hist"]["KICK"], float)
    h = h / h.sum()
    grid = np.arange(1, 100)
    P = outcome_probs(grid, np.full(99, x), m)
    try_ev = P_2PT * 2 * P_2PT_MAKE + (1 - P_2PT) * p_xp(season)
    val = np.array([_PTS.get(c, 0) + (try_ev if c == "TD" else 0) for c in CLASSES])
    val = np.where(val < 0, 0, val)          # points to the offence only
    return float((h * (P @ val)).sum())


def _solve_x(goal_per_drive: float, m: dict, season: int) -> float:
    lo, hi = -1.5, 1.5
    for _ in range(40):
        mid = (lo + hi) / 2
        if expected_points_per_drive(mid, m, season) < goal_per_drive:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def calibrate(pts_h: float, pts_a: float, season: int = 2026, m: dict | None = None, iters: int = 2,
              n_check: int = 6000) -> tuple[float, float]:
    """x_h, x_a such that the simulated mean points match the targets: start from the kickoff-start expected points
    per drive, then correct the per-drive goal by the ratio of target to simulated points (`iters` rounds)."""
    m = m or model()
    per_team = float((m.get("drives_half") or {}).get("mean", 10.7))      # drives per half (both teams) = per team per game
    goals = [max(pts_h, 1.0) / per_team, max(pts_a, 1.0) / per_team]
    xs = [_solve_x(g, m, season) for g in goals]
    for it in range(iters):
        r = simulate(xs[0], xs[1], n=n_check, season=season, seed=10_000 + it, m=m)
        sim = [float(r["hs"].mean()), float(r["as"].mean())]
        goals = [g * max(t, 1.0) / max(sv, 1.0) for g, t, sv in zip(goals, (pts_h, pts_a), sim)]
        xs = [_solve_x(g, m, season) for g in goals]
    return xs[0], xs[1]


def price(pts_h: float, pts_a: float, season: int = 2026, playoff: bool = False, n: int = 20000, seed: int = 0,
          spread_home: float | None = None, total_line: float | None = None) -> dict:
    """Drive simulation calibrated to the game model's team points."""
    xh, xa = calibrate(pts_h, pts_a, season)
    res = simulate(xh, xa, n=n, season=season, playoff=playoff, seed=seed)
    out = summarise(res, spread_home, total_line)
    out.update({"x_h": xh, "x_a": xa})
    return out
