"""
Surface Elo for ATP and WTA singles (FiveThirtyEight / Tennis Abstract recipe, every constant fitted).

Each player carries an overall rating and one per surface (hard, clay, grass; carpet folds into hard).
For a match on surface S between i and j:

    m_i  = w * R_i,S + (1 - w) * R_i,all                                   surface blend
    P(i) = 1 / (1 + 10 ** (-f * (m_i - m_j) / 400)),  f = 1 (best of 3), f = f5 (best of 5)
    K(n) = a / (n + b) ** c                                                n = matches already rated
    R_i,all <- R_i,all + K(n_i,all) * g * (S_i - E_all),  E_all = P with w = 0 (same for j, and for the
    surface rating with E_S = P with w = 1 and n_i,S); g = 1 for completed matches, g = ret_k for
    retirements and defaults (ret_k fitted in [0, 1]); walkovers are never rated.

Inactivity: before a match, a player idle for gap > idle_days days is pulled toward the mean,
R <- 1500 + (R - 1500) * rho ** ((gap - idle_days) / 365) (all four ratings).
Entry: a player's first rating (all surfaces) is c0 - c1 * ln(rank) from the ranking carried on the
MATCH row, or `unranked` without one.

Constants are fitted per tour by minimising the walk-forward log-loss (the pre-match probability of
the actual winner) on completed tour-level matches dated 2005-2019 (ratings run from the first year on
disk), then frozen in models/fitted/elo_params_<tour>.json. Qualifying and Challenger / WTA 125 matches
feed the ratings but not the loss.

`history(tour)` -> {"cols", "rows", "params", "init", ...} cached under <ACE_CACHE>/elo/ keyed on the
stores' sizes and mtimes; `ratings_at(hist, date)` -> {pid: {"all","hard","clay","grass","n","last"}};
`p_win(r1, r2, surface, best_of, params)`.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date
from typing import Any, Iterable

import numpy as np

from oddsmarkets.tennis.models import _io

logger = logging.getLogger(__name__)
VERSION = 1
MEAN = 1500.0
SURF = {"hard": 1, "clay": 2, "grass": 3}
COLS = ["id", "date", "p1", "p2", "surface", "best_of", "level", "status", "all1", "srf1", "all2", "srf2", "p1_pre",
        "all1_post", "srf1_post", "all2_post", "srf2_post", "n1", "n2"]

DEFAULT_PARAMS = {"k_a": 250.0, "k_b": 5.0, "k_c": 0.4, "w_surf": 0.5, "bo5": 1.1, "idle_days": 60.0, "rho": 0.8,
                  "init_c0": 1900.0, "init_c1": 70.0, "unranked": 1400.0, "ret_k": 0.5}
BOUNDS = {"k_a": (20.0, 2000.0), "k_b": (0.5, 100.0), "k_c": (0.05, 1.0), "w_surf": (0.0, 1.0), "bo5": (0.8, 1.6),
          "idle_days": (60.0, 60.0), "rho": (0.2, 1.0), "init_c0": (1500.0, 2400.0), "init_c1": (0.0, 200.0),
          "unranked": (1000.0, 1800.0), "ret_k": (0.0, 1.0)}
FIT_KEYS = ["k_a", "k_b", "k_c", "w_surf", "bo5", "rho", "init_c0", "init_c1", "unranked", "ret_k"]
LOSS_YEARS = (2005, 2019)


def params(tour: str) -> dict:
    """Frozen constants of `tour` (models/fitted/elo_params_<tour>.json), DEFAULT_PARAMS when absent."""
    p = dict(DEFAULT_PARAMS)
    f = _io.read_json(_io.FITTED / f"elo_params_{_io.tour_key(tour)}.json")
    if isinstance(f, dict) and isinstance(f.get("params"), dict):
        p.update({k: float(v) for k, v in f["params"].items() if k in DEFAULT_PARAMS})
    return p


def expected(d: float, f: float = 1.0) -> float:
    return 1.0 / (1.0 + 10.0 ** (-f * d / 400.0))


def p_win(r1: dict | float, r2: dict | float, surface: str = "hard", best_of: int = 3, params: dict | None = None) -> float:
    """P(player 1 beats player 2) from rating records ({"all", <surface>}) or plain numbers."""
    p = params or DEFAULT_PARAMS
    s = _io.fold_surface(surface)

    def m(r):
        if isinstance(r, dict):
            a = float(r.get("all", MEAN))
            return p["w_surf"] * float(r.get(s, a)) + (1 - p["w_surf"]) * a
        return float(r)

    return expected(m(r1) - m(r2), p["bo5"] if int(best_of or 3) == 5 else 1.0)


def _init(rank: Any, p: dict) -> float:
    try:
        rk = int(rank)
    except (TypeError, ValueError):
        rk = 0
    if rk > 0:
        return p["init_c0"] - p["init_c1"] * math.log(rk)
    return p["unranked"]


def _compact(matches: Iterable[dict], loss_years: tuple[int, int] = LOSS_YEARS) -> list[tuple]:
    out = []
    for m in matches:
        st = m.get("status")
        if st not in _io.RATED_STATUS:
            continue
        p1, p2 = m.get("p1"), m.get("p2")
        d = _io.day(m.get("date"))
        if not p1 or not p2 or p1 == p2 or d is None:
            continue
        lv = _io.fold_level(m.get("level"))
        in_loss = (st == "done" and lv in _io.TOUR_LEVELS and loss_years[0] <= d.year <= loss_years[1])
        out.append((d.toordinal(), p1, p2, SURF[_io.fold_surface(m.get("surface"))],
                    5 if int(m.get("best_of") or 3) == 5 else 3, m.get("rank1"), m.get("rank2"), st, in_loss,
                    m.get("id"), d, lv))
    out.sort(key=lambda r: r[0])
    return out


def _run(rows: list[tuple], p: dict, record: bool = False):
    """Run Elo over compact rows. Returns (loss sum, n in loss) or, with record, (rows_out, state, init)."""
    ka, kb, kc = p["k_a"], p["k_b"], p["k_c"]
    w, f5 = p["w_surf"], p["bo5"]
    idle, rho = p["idle_days"], p["rho"]
    retk = p["ret_k"]
    R: dict[str, list] = {}
    init: dict[str, float] = {}
    loss = 0.0
    nl = 0
    out = []
    lrho = math.log(max(rho, 1e-9)) / 365.0
    for r in rows:
        dd, a, b, s, bo, rk1, rk2, st, inl = r[:9]
        g = 1.0 if st == "done" else retk
        recs = []
        for pid, rk in ((a, rk1), (b, rk2)):
            x = R.get(pid)
            if x is None:
                v = _init(rk, p)
                init[pid] = v
                x = R[pid] = [v, v, v, v, 0, 0, 0, 0, dd]
            else:
                gap = dd - x[8]
                if gap > idle and rho < 1.0:
                    fct = math.exp(lrho * (gap - idle))
                    for k in range(4):
                        x[k] = MEAN + (x[k] - MEAN) * fct
            recs.append(x)
        x1, x2 = recs
        fct = f5 if bo == 5 else 1.0
        m1 = w * x1[s] + (1 - w) * x1[0]
        m2 = w * x2[s] + (1 - w) * x2[0]
        pp = 1.0 / (1.0 + 10.0 ** (-fct * (m1 - m2) / 400.0))
        if inl:
            loss -= math.log(max(pp, 1e-12))
            nl += 1
        pre = (x1[0], x1[s], x2[0], x2[s]) if record else None
        if g > 0:
            ea = 1.0 / (1.0 + 10.0 ** (-fct * (x1[0] - x2[0]) / 400.0))
            es = 1.0 / (1.0 + 10.0 ** (-fct * (x1[s] - x2[s]) / 400.0))
            x1[0] += g * ka / (x1[4] + kb) ** kc * (1 - ea)
            x2[0] -= g * ka / (x2[4] + kb) ** kc * (1 - ea)
            x1[s] += g * ka / (x1[4 + s] + kb) ** kc * (1 - es)
            x2[s] -= g * ka / (x2[4 + s] + kb) ** kc * (1 - es)
            x1[4] += 1; x2[4] += 1; x1[4 + s] += 1; x2[4 + s] += 1
        x1[8] = dd
        x2[8] = dd
        if record:
            out.append([r[9], r[10].isoformat(), a, b, ("hard", "clay", "grass")[s - 1], bo, r[11], st,
                        round(pre[0], 2), round(pre[1], 2), round(pre[2], 2), round(pre[3], 2), round(pp, 5),
                        round(x1[0], 2), round(x1[s], 2), round(x2[0], 2), round(x2[s], 2), x1[4], x2[4]])
    if record:
        return out, R, init
    return loss, nl


def compute(matches: Iterable[dict], prm: dict | None = None) -> dict:
    """Elo history over MATCH rows (any order): {"cols", "rows", "params", "init", "current"}."""
    p = dict(DEFAULT_PARAMS)
    p.update(prm or {})
    rows, R, init = _run(_compact(matches), p, record=True)
    cur = {pid: {"all": round(x[0], 2), "hard": round(x[1], 2), "clay": round(x[2], 2), "grass": round(x[3], 2),
                 "n": x[4], "last": date.fromordinal(x[8]).isoformat()} for pid, x in R.items()}
    return {"version": VERSION, "cols": COLS, "rows": rows, "params": p, "init": {k: round(v, 2) for k, v in init.items()},
            "current": cur}


def history(tour: str, use_cache: bool = True, prm: dict | None = None, matches: list[dict] | None = None) -> dict:
    """Elo for every rated match of `tour` on disk with the tour's frozen constants (see module docstring)."""
    t = _io.tour_key(tour)
    p = params(t)
    p.update(prm or {})
    if matches is not None:
        return compute(matches, p)
    key = _io.file_key(VERSION, _io.signature(t), p)
    return _io.cached("elo", t, key, lambda: dict(compute(_io.load_matches(t), p), tour=t), use_cache)


def ratings_at(hist: dict, when: Any, decay: bool = True) -> dict[str, dict]:
    """Each player's ratings before day `when` (latest post-match values; surfaces never played keep the
    entry rating), with the inactivity pull applied for the layoff up to `when` when `decay`."""
    d = _io.day(when)
    ds = d.isoformat() if d else "9999-12-31"
    p = hist.get("params") or DEFAULT_PARAMS
    init = hist.get("init") or {}
    out: dict[str, dict] = {}
    for g in hist.get("rows") or []:
        if g[1] >= ds:
            break
        for pid, ai, si, n in ((g[2], 13, 14, g[17]), (g[3], 15, 16, g[18])):
            rec = out.get(pid)
            if rec is None:
                v = float(init.get(pid, MEAN))
                rec = out[pid] = {"all": v, "hard": v, "clay": v, "grass": v, "n": 0, "last": g[1]}
            rec["all"] = g[ai]
            rec[g[4]] = g[si]
            rec["n"] = n
            rec["last"] = g[1]
    if decay and d is not None and float(p.get("rho", 1.0)) < 1.0:
        idle, rho = float(p["idle_days"]), float(p["rho"])
        for rec in out.values():
            gap = (d - _io.day(rec["last"])).days
            if gap > idle:
                f = rho ** ((gap - idle) / 365.0)
                for k in ("all", "hard", "clay", "grass"):
                    rec[k] = MEAN + (rec[k] - MEAN) * f
    return out


def pre_match(hist: dict) -> dict[str, float]:
    """{match_id: Elo P(p1 wins)} for every rated match."""
    return {g[0]: g[12] for g in hist.get("rows") or []}


def loss(matches_or_rows, prm: dict) -> tuple[float, int]:
    rows = matches_or_rows if (matches_or_rows and isinstance(matches_or_rows[0], tuple)) else _compact(matches_or_rows)
    p = dict(DEFAULT_PARAMS)
    p.update(prm)
    return _run(rows, p)


def fit_params(matches: list[dict], start: dict | None = None, maxfev: int = 800, log=None,
               loss_years: tuple[int, int] = LOSS_YEARS) -> dict:
    """Minimise the mean walk-forward log-loss over FIT_KEYS (Nelder-Mead on a box-clipped vector).
    Returns {"params", "logloss", "n", "default_logloss", "evals", "secs"}."""
    from scipy.optimize import minimize

    t0 = time.time()
    rows = _compact(matches, tuple(loss_years))
    p0 = dict(DEFAULT_PARAMS)
    p0.update(start or {})
    scale = np.array([BOUNDS[k][1] - BOUNDS[k][0] for k in FIT_KEYS])
    lo = np.array([BOUNDS[k][0] for k in FIT_KEYS])
    hi = np.array([BOUNDS[k][1] for k in FIT_KEYS])
    x0 = (np.array([p0[k] for k in FIT_KEYS]) - lo) / scale
    best = {"f": math.inf}
    ev = [0]

    def unpack(x):
        v = lo + np.clip(x, 0, 1) * scale
        q = dict(p0)
        q.update({k: float(val) for k, val in zip(FIT_KEYS, v)})
        return q

    def obj(x):
        q = unpack(x)
        l, n = _run(rows, q)
        f = l / max(n, 1) + 10.0 * float(np.sum(np.clip(-x, 0, None) + np.clip(x - 1, 0, None)))
        ev[0] += 1
        if f < best["f"]:
            best.update(f=f, q=q)
            if log and ev[0] % 50 == 0:
                log(ev[0], f)
        return f

    d0, n0 = _run(rows, dict(DEFAULT_PARAMS))
    res = minimize(obj, x0, method="Nelder-Mead", options={"maxfev": maxfev, "xatol": 1e-3, "fatol": 1e-6,
                                                           "adaptive": True})
    q = best.get("q") or unpack(res.x)
    l, n = _run(rows, q)
    return {"params": {k: round(v, 5) for k, v in q.items()}, "logloss": l / max(n, 1), "n": n,
            "default_logloss": d0 / max(n0, 1), "evals": ev[0], "secs": round(time.time() - t0, 1),
            "loss_years": list(loss_years)}


def export_fits(tour: str, maxfev: int = 800, loss_years: tuple[int, int] = LOSS_YEARS) -> str:
    """Fit the constants on the stores on disk (loss on `loss_years`) and write
    models/fitted/elo_params_<tour>.json."""
    t = _io.tour_key(tour)
    ms = _io.load_matches(t, through=f"{loss_years[1]}-12-31")
    res = fit_params(ms, start=params(t), maxfev=maxfev, loss_years=tuple(loss_years))
    path = _io.FITTED / f"elo_params_{t}.json"
    _io.write_json(path, {"version": VERSION, "tour": t, **res}, indent=1)
    return str(path)
