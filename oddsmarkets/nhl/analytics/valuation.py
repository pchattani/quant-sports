"""
Valuation v2 for The Quant Rink (`data/<S>/valuation.json`, the "Valuation (multi-season)" tab of #/value) and the
as-of-a-date valuation the trade ratings use (analytics/moves.py). Shared spec: docs/VALUE_SECTIONS.md section 4.

Currency: WAR (Rink value GAR / goals per win, models/value.py). A player's value is his projected on-field value over
the rest of the current season and the next three seasons, discounted by DISCOUNT = 0.9 a season:

    V = sum_k 0.9^k x S_k x r_k x m_k x a x n_k / 60 / gpw          k = 0 (rest of this season), 1, 2, 3

  r_k  GAR per 60: r_0 = the rest-of-season rate (value.py player_projection: this season's and last season's GAR at
       0.7, minute-weighted, with 300 minutes (goalies 1,500) of replacement-level play); r_k = r_{k-1} + aging(age +
       k - 1), the delta-method ageing curve (value.py aging_curve).
  m_k  projected minutes a game when he plays (value.py: blended with last season's at 10 games; goalies 60 x his
       share of the team's goalie minutes).
  a    availability (skaters; a goalie's m is already his share of the team's minutes), the expected share of team games he plays: (GP this season + GP last + GP two seasons ago +
       AVAIL_PSEUDO x A0) / (team games of the seasons he appeared in + AVAIL_PSEUDO), A0 the league's mean share of
       regulars (fitted); for the rest of this season x (games left - games an injury rules him out) / games left
       (ESPN injury status and return date; no date: day-to-day 1 game, out 3, injured reserve 7, long-term 25).
  n_k  team games: the games left this season; then canon.games_per_team (84 from 2026-27).
  S_k  survival: P(still an NHL regular k seasons ahead) = prod_j s(age + j); s is a logistic regression, fitted on
       every pair of consecutive completed seasons, of "regular next season" (GP >= 25 % of team games; goalies 12 %)
       on age, age^2, the shrunk GAR per 60 and minutes a game, among that season's regulars. S_0 = 1.

Uncertainty (p10-p90 of V, Monte Carlo with N_DRAWS = 400 common draws, seed fixed):
  rate:   r_0 ~ N(r_0, se^2), se^2 = 1 / (1 / tau^2 + T_eff / (60 sigma^2)), T_eff = this season's minutes + 0.7 x last
          season's; sigma^2 (noise per 60 minutes) and delta^2 (true year-to-year drift) from the consecutive-season
          pairs, E[(r2 - r1 - aging)^2] = sigma^2 (60/T1 + 60/T2) + delta^2 (weighted least squares on binned pairs);
          tau^2 (spread of true rates) = cov(r1, r2) on pairs with 400+ minutes in both. Reliability at T minutes =
          tau^2 / (tau^2 + 60 sigma^2 / T).
  drift:  r_k = r_{k-1} + aging + N(0, delta^2) (a random walk, so the spread grows with k).
  minutes: log(m_k a) is a random walk with step sd MIN_CV (the sd of the log change in minutes per team game
          between consecutive seasons among regulars, fitted); this season's step scaled by sqrt(share of the season
          left).
  survival: a regular stays one more season with probability s(age + j) (draws of who drops out).
The point value is the analytic expectation (independent parts); the band comes from the draws.

Position scarcity: replacement level at C, LW, RW, D and G = the TOI-weighted GAR per 60 of players at that position
outside the league's top N_p by TOI, N_p = the position's share of the top 13 forwards / 7 defence / 2 goalies per
team (pooled over the last three completed seasons). Value over positional replacement (VORP) replaces r_k by
r_k - repl_p. Scarcity index = (TOI-weighted GAR per 60 of the position's top N_p - repl_p) / the same gap for all
skaters (> 1: good players at that position are harder to replace).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import date, datetime, timezone
from typing import Any, Iterable

import numpy as np

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import value as VAL

logger = logging.getLogger(__name__)

VERSION = 1
DISCOUNT = 0.9
HORIZON = 3                       # seasons after the current one
N_DRAWS = 400
SEED = 20261016
AVAIL_PSEUDO = 30.0               # pseudo-games at the league's mean share of regulars
REGULAR = {"S": 0.25, "G": 0.12}  # GP >= this share of team games = an NHL regular
REL_MIN = {"S": 100.0, "G": 300.0}
TAU_MIN = {"S": 400.0, "G": 1000.0}
INJ_GAMES = {"day-to-day": 1, "out": 3, "injured reserve": 7, "long-term injured reserve": 25, "suspension": 2}
POS_SLOTS = {"F": 13, "D": 7, "G": 2}
ROLES = ("C", "L", "R", "D", "G")
POS_ONE = {"C": "C", "L": "LW", "R": "RW", "D": "D", "G": "G"}


def _f(v: Any) -> float | None:
    return an.fnum(v)


def _r(v: Any, nd: int = 2) -> float | None:
    v = _f(v)
    return None if v is None or not math.isfinite(v) else round(v, nd)


# ---------------------------------------------------------------------------------------------- inputs

def value_rows(data_root=None, seasons: Iterable[int] | None = None) -> dict[int, dict]:
    """{season: {"rows": [dict], "team_games": n, "gpw": goals per win, "n_teams"}} from data/<S>/value.json."""
    root = data_root or an.data_root()
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 8):
        s = int(d.name)
        if seasons is not None and s not in set(seasons):
            continue
        v = an.read_json(d / "value.json")
        if not v or not v.get("ok") or not v.get("rows"):
            continue
        cols = v["cols"]
        rows = [dict(zip(cols, r)) for r in v["rows"]]
        out[s] = {"rows": rows, "team_games": int(v.get("team_games") or 0) or 82,
                  "gpw": _f((v.get("currency") or {}).get("goals_per_win")), "n_teams": len({r.get("team") for r in rows if r.get("team")})}
    return out


def _sig(vr: dict[int, dict]) -> str:
    src = [(s, len(x["rows"]), x["team_games"], round(sum(float(r.get("gar") or 0) for r in x["rows"]), 3)) for s, x in sorted(vr.items())]
    return hashlib.sha1(json.dumps([VERSION, src]).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------- fits

def reliability(vr: dict[int, dict], completed: list[int], curves: dict | None = None) -> dict:
    """{kind: {"sigma2","delta2","tau2","k_rel","n_pairs"}}: noise per 60 minutes, true year-to-year drift, spread of
    true rates and the minutes at which the rate's reliability is one half."""
    out = {}
    for kind in ("S", "G"):
        X, Y, W = [], [], []
        a1, a2, ww = [], [], []
        for s in completed:
            nxt = an.season_id(an.start_year(s) + 1)
            if nxt not in vr or nxt not in completed:
                continue
            b = {r["id"]: r for r in vr[nxt]["rows"] if r.get("kind") == kind}
            for r in vr[s]["rows"]:
                if r.get("kind") != kind:
                    continue
                q = b.get(r["id"])
                if not q:
                    continue
                t1, t2 = _f(r.get("toi")) or 0.0, _f(q.get("toi")) or 0.0
                r1, r2 = _f(r.get("rate")), _f(q.get("rate"))
                if r1 is None or r2 is None or t1 < REL_MIN[kind] or t2 < REL_MIN[kind]:
                    continue
                ag = VAL.aging_delta((curves or {}).get(kind), _f(r.get("age")))
                X.append(60.0 / t1 + 60.0 / t2)
                Y.append((r2 - r1 - ag) ** 2)
                W.append(1.0)
                if t1 >= TAU_MIN[kind] and t2 >= TAU_MIN[kind]:
                    a1.append(r1)
                    a2.append(r2)
                    ww.append(2.0 / (1.0 / t1 + 1.0 / t2))
        if len(X) < 50:
            out[kind] = {"sigma2": 0.5 if kind == "S" else 2.0, "delta2": 0.005, "tau2": 0.02, "k_rel": None, "n_pairs": len(X)}
            continue
        X, Y = np.asarray(X), np.asarray(Y)
        qs = np.quantile(X, np.linspace(0, 1, 16))
        bx, by, bn = [], [], []
        for lo, hi in zip(qs[:-1], qs[1:]):
            m = (X >= lo) & (X <= hi)
            if m.sum() >= 10:
                bx.append(X[m].mean())
                by.append(Y[m].mean())
                bn.append(m.sum())
        bx, by, bn = np.asarray(bx), np.asarray(by), np.asarray(bn, float)
        A = np.vstack([bx, np.ones_like(bx)]).T
        sw = np.sqrt(bn)
        coef = np.linalg.lstsq(A * sw[:, None], by * sw, rcond=None)[0]
        sigma2 = max(float(coef[0]), 1e-6)
        delta2 = max(float(coef[1]), 0.0)
        tau2 = None
        if len(a1) >= 30:
            a1, a2, ww = np.asarray(a1), np.asarray(a2), np.asarray(ww)
            m1, m2 = np.average(a1, weights=ww), np.average(a2, weights=ww)
            tau2 = float(np.average((a1 - m1) * (a2 - m2), weights=ww))
        tau2 = max(tau2 or 0.0, 1e-4)
        out[kind] = {"sigma2": round(sigma2, 5), "delta2": round(delta2, 6), "tau2": round(tau2, 6),
                     "k_rel": round(60.0 * sigma2 / tau2, 0), "n_pairs": int(len(X)),
                     "bins": [[round(float(x), 4), round(float(y), 5), int(n)] for x, y, n in zip(bx, by, bn)]}
    return out


def _regular(r: dict, tg: float, kind: str) -> bool:
    return (an.inum(r.get("gp")) or 0) >= REGULAR[kind] * max(tg, 1)


def _shrunk(r: dict, kind: str) -> float:
    gar, toi = _f(r.get("gar")) or 0.0, _f(r.get("toi")) or 0.0
    return gar / (toi + VAL.SHRINK_MIN[kind]) * 60.0


SURV_FEATURES = ("age", "age2", "rate", "mpg")


def _surv_x(age: float, rate: float, mpg: float, kind: str) -> list[float]:
    a = (age - 27.0) / 5.0
    m = mpg / (20.0 if kind == "S" else 60.0)
    return [1.0, a, a * a, rate * (4.0 if kind == "S" else 1.0), m]


def _logit_fit(X: np.ndarray, y: np.ndarray, lam: float = 1.0, iters: int = 50) -> np.ndarray:
    b = np.zeros(X.shape[1])
    P = np.eye(X.shape[1]) * lam
    P[0, 0] = 0.0
    for _ in range(iters):
        z = X @ b
        p = 1.0 / (1.0 + np.exp(-z))
        w = np.clip(p * (1 - p), 1e-6, None)
        H = X.T @ (X * w[:, None]) + P
        g = X.T @ (y - p) - P @ b
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def survival_fit(vr: dict[int, dict], completed: list[int]) -> dict:
    """{kind: {"coef": [...], "n", "base", "by_age": [[age, n, observed, fitted]]}}: P(regular next season | regular
    this season, age, shrunk GAR per 60, minutes a game)."""
    out = {}
    for kind in ("S", "G"):
        X, y, ages = [], [], []
        for s in completed:
            nxt = an.season_id(an.start_year(s) + 1)
            if nxt not in vr or nxt not in completed:
                continue
            tg, tg2 = vr[s]["team_games"], vr[nxt]["team_games"]
            b = {r["id"]: r for r in vr[nxt]["rows"] if r.get("kind") == kind}
            for r in vr[s]["rows"]:
                if r.get("kind") != kind or not _regular(r, tg, kind) or _f(r.get("age")) is None:
                    continue
                gp = an.inum(r.get("gp")) or 1
                q = b.get(r["id"])
                X.append(_surv_x(float(r["age"]), _shrunk(r, kind), (_f(r.get("toi")) or 0.0) / gp, kind))
                y.append(1.0 if q is not None and _regular(q, tg2, kind) else 0.0)
                ages.append(int(round(float(r["age"]))))
        if len(y) < 100:
            out[kind] = {"coef": None, "n": len(y)}
            continue
        X, y = np.asarray(X), np.asarray(y)
        b = _logit_fit(X, y)
        p = 1 / (1 + np.exp(-(X @ b)))
        by_age = []
        ages = np.asarray(ages)
        for a in range(18, 43):
            m = ages == a
            if m.sum() >= 5:
                by_age.append([a, int(m.sum()), round(float(y[m].mean()), 3), round(float(p[m].mean()), 3)])
        ll = float(np.mean(y * np.log(np.clip(p, 1e-9, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-9, 1))))
        base = float(y.mean())
        ll0 = base * math.log(base) + (1 - base) * math.log(1 - base)
        out[kind] = {"coef": [round(float(c), 5) for c in b], "features": list(SURV_FEATURES), "n": int(len(y)),
                     "base": round(base, 4), "logloss": round(-ll, 4), "logloss_base": round(-ll0, 4), "by_age": by_age}
    return out


def survival_p(fit: dict | None, age: float | None, rate: float, mpg: float, kind: str) -> float:
    c = (fit or {}).get("coef")
    if not c or age is None:
        return float((fit or {}).get("base") or 0.8)
    z = float(np.dot(c, _surv_x(float(age), float(rate), float(mpg), kind)))
    return 1.0 / (1.0 + math.exp(-z))


def minutes_cv(vr: dict[int, dict], completed: list[int]) -> dict:
    """{kind: sd of log(minutes per team game next season / this season) among regulars who stay regulars}."""
    out = {}
    for kind in ("S", "G"):
        d = []
        for s in completed:
            nxt = an.season_id(an.start_year(s) + 1)
            if nxt not in vr or nxt not in completed:
                continue
            tg, tg2 = vr[s]["team_games"], vr[nxt]["team_games"]
            b = {r["id"]: r for r in vr[nxt]["rows"] if r.get("kind") == kind}
            for r in vr[s]["rows"]:
                q = b.get(r["id"])
                if r.get("kind") != kind or not q or not _regular(r, tg, kind) or not _regular(q, tg2, kind):
                    continue
                m1, m2 = (_f(r.get("toi")) or 0) / tg, (_f(q.get("toi")) or 0) / tg2
                if m1 > 0 and m2 > 0:
                    d.append(math.log(m2 / m1))
        if len(d) < 30:
            out[kind] = {"cv": 0.25, "n": len(d)}
            continue
        a = np.asarray(d)
        lo, hi = np.quantile(a, [0.01, 0.99])
        a = a[(a >= lo) & (a <= hi)]
        out[kind] = {"cv": round(float(a.std()), 4), "mean": round(float(a.mean()), 4), "n": int(len(d))}
    return out


def avail_mean(vr: dict[int, dict], completed: list[int]) -> dict:
    """{kind: the league's mean share of team games played by its regulars}."""
    out = {}
    for kind in ("S", "G"):
        num = den = 0.0
        for s in completed[-5:]:
            tg = vr[s]["team_games"]
            for r in vr[s]["rows"]:
                if r.get("kind") == kind and _regular(r, tg, kind):
                    num += an.inum(r.get("gp")) or 0
                    den += tg
        out[kind] = round(num / den, 4) if den else (0.85 if kind == "S" else 0.5)
    return out


def positional(vr: dict[int, dict], completed: list[int]) -> dict:
    """Replacement level (GAR per 60) and scarcity index by position, pooled over the last three completed seasons."""
    use = completed[-3:]
    acc = {p: {"top_g": 0.0, "top_t": 0.0, "rep_g": 0.0, "rep_t": 0.0, "n_top": 0} for p in ROLES}
    all_top = {"g": 0.0, "t": 0.0}
    all_rep = {"g": 0.0, "t": 0.0}
    for s in use:
        rows = vr[s]["rows"]
        nt = max(vr[s]["n_teams"], 1)
        for grp, roles in (("F", ("C", "L", "R")), ("D", ("D",)), ("G", ("G",))):
            pool = sorted([r for r in rows if r.get("pos") in roles and (_f(r.get("toi")) or 0) > 0], key=lambda r: -(_f(r.get("toi")) or 0))
            top = pool[:POS_SLOTS[grp] * nt]
            for p in roles:
                n_p = sum(1 for r in top if r.get("pos") == p)
                at = [r for r in pool if r.get("pos") == p]
                for i, r in enumerate(at):
                    t, g = _f(r.get("toi")) or 0.0, _f(r.get("gar")) or 0.0
                    if i < n_p:
                        acc[p]["top_g"] += g
                        acc[p]["top_t"] += t
                        if p != "G":
                            all_top["g"] += g
                            all_top["t"] += t
                    elif t >= 20:
                        acc[p]["rep_g"] += g
                        acc[p]["rep_t"] += t
                        if p != "G":
                            all_rep["g"] += g
                            all_rep["t"] += t
                acc[p]["n_top"] += n_p
    gap_all = (all_top["g"] / max(all_top["t"], 1e-9) - all_rep["g"] / max(all_rep["t"], 1e-9)) * 60.0
    out = {}
    for p in ROLES:
        a = acc[p]
        top = a["top_g"] / max(a["top_t"], 1e-9) * 60.0
        rep = a["rep_g"] / max(a["rep_t"], 1e-9) * 60.0 if a["rep_t"] > 0 else 0.0
        out[p] = {"repl": round(rep, 4), "starter": round(top, 4), "gap": round(top - rep, 4),
                  "scarcity": round((top - rep) / gap_all, 3) if gap_all > 0 and p != "G" else None,
                  "n_top": int(round(a["n_top"] / max(len(use), 1)))}
    if gap_all > 0 and out["G"]["gap"] is not None:
        out["G"]["scarcity"] = None
    return {"positions": out, "seasons": use, "gap_skaters": round(gap_all, 4)}


def fits(vr: dict[int, dict], completed: list[int], curves: dict | None) -> dict:
    """Every fitted piece, cached on the value payloads' signature (never recomputed hourly unless they change)."""
    key = hashlib.sha1(json.dumps([_sig({s: vr[s] for s in completed if s in vr}), curves], default=str).encode()).hexdigest()[:16]
    p = an.an_cache() / "valuation" / "fits.json"
    c = an.read_json(p) if p.exists() else None
    if isinstance(c, dict) and c.get("key") == key:
        return c["fits"]
    f = {"reliability": reliability(vr, completed, curves), "survival": survival_fit(vr, completed),
         "minutes": minutes_cv(vr, completed), "avail": avail_mean(vr, completed), "positional": positional(vr, completed),
         "aging": curves, "completed": completed}
    try:
        an.write_json(p, {"key": key, "fits": f})
    except OSError:
        pass
    return f


# ---------------------------------------------------------------------------------------------- the projector

def rate_se(t_eff: float, rel: dict) -> float:
    tau2, sigma2 = float(rel.get("tau2") or 0.02), float(rel.get("sigma2") or 0.5)
    return math.sqrt(1.0 / (1.0 / tau2 + max(t_eff, 0.0) / (60.0 * sigma2)))


def availability(gp_tg: list[tuple[float, float]], a0: float, pseudo: float = AVAIL_PSEUDO) -> float:
    """(sum GP + pseudo x a0) / (sum team games + pseudo) over the seasons he appeared in."""
    num = sum(g for g, t in gp_tg if g > 0 and t > 0)
    den = sum(min(t, max(t, g)) for g, t in gp_tg if g > 0 and t > 0)
    return float(min(1.0, (num + pseudo * a0) / (den + pseudo)))


def injury_games(status: str | None, ret: str | None, team_dates: list[str], today: date) -> int:
    """Team games the injury is expected to cost from today: games before the return date when ESPN gives one,
    else INJ_GAMES by status."""
    s = str(status or "").strip().lower()
    if not s or s in ("active", "probable"):
        return 0
    if ret:
        try:
            rd = date.fromisoformat(str(ret)[:10])
            return int(sum(1 for d in team_dates if today.isoformat() <= d < rd.isoformat()))
        except ValueError:
            pass
    for k, n in INJ_GAMES.items():
        if s.startswith(k) or k in s:
            if k == "injured reserve" and "long" in s:
                continue
            return n
    return 0


def project(players: list[dict], f: dict, n_draws: int = N_DRAWS, seed: int = SEED, discount: float = DISCOUNT) -> list[dict]:
    """players: [{"id","kind" (S/G),"pos","age","rate","mpg","avail","t_eff","games": [n_0..n_K],"gpw","frac0" (share
    of a season left), "repl" (positional replacement, optional), "inj_games0"}] -> each with "ev" (expected WAR by season),
    "vorp_ev", "total", "vorp", "p10", "p50", "p90", "surv" (S_1..S_K), "se"."""
    if not players:
        return []
    rel = f.get("reliability") or {}
    curves = f.get("aging") or {}
    surv = f.get("survival") or {}
    mins = f.get("minutes") or {}
    K = max(len(p["games"]) for p in players)
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal((n_draws, K))          # rate (k=0) and drift (k>=1)
    E = rng.standard_normal((n_draws, K))          # minutes
    U = rng.random((n_draws, K))                   # survival
    out = []
    for p in players:
        kind = p["kind"]
        rr = rel.get(kind) or {}
        se = rate_se(float(p.get("t_eff") or 0.0), rr)
        delta = math.sqrt(float(rr.get("delta2") or 0.0))
        cv = float((mins.get(kind) or {}).get("cv") or 0.25)
        age = _f(p.get("age"))
        gpw = float(p.get("gpw") or 6.0)
        games = list(p["games"]) + [0] * (K - len(p["games"]))
        m0 = float(p.get("mpg") or 0.0) * float(p.get("avail") if p.get("avail") is not None else 1.0)
        # expected rate path and survival
        rates, S = [float(p.get("rate") or 0.0)], [1.0]
        for k in range(1, K):
            a_prev = None if age is None else age + k - 1
            rates.append(rates[-1] + VAL.aging_delta(curves.get(kind), a_prev))
            s_k = survival_p(surv.get(kind), a_prev, rates[-2], float(p.get("mpg") or 0.0), kind)
            S.append(S[-1] * s_k)
        repl = float(p.get("repl") or 0.0)
        w = [discount ** k for k in range(K)]
        g0 = games[0]
        inj = min(float(p.get("inj_games0") or 0.0), g0)
        mult0 = (g0 - inj) / g0 if g0 > 0 else 0.0
        ev = [S[k] * rates[k] * m0 * (mult0 if k == 0 else 1.0) * games[k] / 60.0 / gpw for k in range(K)]
        ev_v = [S[k] * (rates[k] - repl) * m0 * (mult0 if k == 0 else 1.0) * games[k] / 60.0 / gpw for k in range(K)]
        # draws
        frac0 = float(p.get("frac0") if p.get("frac0") is not None else 1.0)
        cv0 = cv * math.sqrt(max(min(frac0, 1.0), 0.0))
        t = rates[0] + se * Z[:, 0]
        L = math.log(max(m0, 1e-9)) + cv0 * E[:, 0] - cv0 * cv0 / 2.0
        alive = np.ones(n_draws)
        tot = w[0] * t * np.exp(L) * mult0 * g0 / 60.0 / gpw if m0 > 0 else np.zeros(n_draws)
        for k in range(1, K):
            t = t + (rates[k] - rates[k - 1]) + delta * Z[:, k]
            L = L + cv * E[:, k] - cv * cv / 2.0
            s_k = S[k] / S[k - 1] if S[k - 1] > 0 else 0.0
            alive = alive * (U[:, k] < s_k)
            if m0 > 0:
                tot = tot + w[k] * alive * t * np.exp(L) * games[k] / 60.0 / gpw
        q10, q50, q90 = (float(x) for x in np.quantile(tot, [0.1, 0.5, 0.9]))
        out.append({**p, "se": se, "rates": rates, "surv": S[1:], "ev": ev, "vorp_ev": ev_v,
                    "total": float(sum(wk * e for wk, e in zip(w, ev))), "vorp": float(sum(wk * e for wk, e in zip(w, ev_v))),
                    "p10": q10, "p50": q50, "p90": q90})
    return out


# ---------------------------------------------------------------------------------------------- current season

def _cat_players(c: dict | None) -> dict:
    return ((c or {}).get("players")) or {}


def team_schedule(store: dict, today: date) -> dict[str, list[str]]:
    """{team: [dates of regular-season games not yet final, from today]}."""
    out: dict[str, list[str]] = {}
    gs = (store or {}).get("games") or {}
    for g in (gs.values() if isinstance(gs, dict) else gs):
        gid = str(g.get("game_id") or "")
        if gid[4:6] != "02" or str(g.get("status") or "").lower() in ("final", "off", "official"):
            continue
        d = str(g.get("date") or "")[:10]
        if d < today.isoformat():
            continue
        for t in (g.get("home"), g.get("away")):
            if t:
                out.setdefault(t, []).append(d)
    return {t: sorted(v) for t, v in out.items()}


def injuries_by_pid(rows: list[list], store_players: dict, teams_espn: dict | None = None) -> dict[str, dict]:
    """Match ESPN injury rows ([espn team id, club, name, status, date, type, return]) to NHL ids by normalised name
    (and the club when two players share a name)."""
    from oddsmarkets.nhl import canon
    from oddsmarkets.nhl.analytics import moves as MV
    idx: dict[str, list[tuple[str, str]]] = {}
    for pid, p in store_players.items():
        nm = p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x)
        idx.setdefault(MV.norm_name(nm), []).append((str(pid), p.get("team")))
    out = {}
    for r in rows or []:
        team = canon.abbr_from_espn(r[0]) if r and r[0] else None
        cands = idx.get(MV.norm_name(r[2])) or []
        if len(cands) > 1:
            cands = [c for c in cands if c[1] == team] or cands[:0]
        if len(cands) == 1:
            out[cands[0][0]] = {"status": r[3], "date": r[4], "type": r[5], "ret": r[6] if len(r) > 6 else None}
    return out


def current_payload(season: int, store: dict, sk: dict | None, gk: dict | None, prev_sk: dict | None, prev_gk: dict | None,
                    prev2: tuple[dict | None, dict | None], f: dict, gpw: float, today: date, injuries: dict[str, dict] | None = None,
                    phase: str | None = None) -> dict:
    """valuation.json for every player on a current roster ("_ev": {pid: expected WAR by season} for the trade ratings;
    the builder removes it before writing)."""
    teams = {p.get("team") for p in ((store or {}).get("players") or {}).values() if isinstance(p, dict) and p.get("team")}
    proj = VAL.projections(season, store, teams, sk, gk, prev_sk, prev_gk, f.get("aging"))
    cur = {**_cat_players(sk), **_cat_players(gk)}
    prv = {**_cat_players(prev_sk), **_cat_players(prev_gk)}
    pr2 = {**_cat_players(prev2[0]), **_cat_players(prev2[1])}
    tg_cur = max(VAL.team_games_played(store).values() or [0]) if store else 0
    tg_cur_t = VAL.team_games_played(store)
    tg_prev = int(_f((prev_sk or {}).get("team_games")) or 82)
    tg_prev2 = int(_f((prev2[0] or {}).get("team_games")) or 82)
    sched = team_schedule(store, today)
    n_season = an.inum(None) or 0
    from oddsmarkets.nhl import canon
    n_season = canon.games_per_team(season)
    future = [canon.games_per_team(an.season_id(an.start_year(season) + k)) for k in range(1, HORIZON + 1)]
    pos_fit = (f.get("positional") or {}).get("positions") or {}
    a0 = f.get("avail") or {}
    players = []
    for pid, p in proj.items():
        kind = "G" if p["pos"] == "G" else "S"
        c, q, q2 = cur.get(pid) or {}, prv.get(pid) or {}, pr2.get(pid) or {}
        t_eff = (_f(c.get("toi")) or 0.0) + VAL.PREV_WEIGHT * (_f(q.get("toi")) or 0.0)
        gp_tg = [(float(an.inum(c.get("gp")) or 0), float(tg_cur_t.get(p["team"], tg_cur) or 0)),
                 (float(an.inum(q.get("gp")) or 0), float(tg_prev)), (float(an.inum(q2.get("gp")) or 0), float(tg_prev2))]
        av = availability(gp_tg, float(a0.get(kind) or 0.85)) if kind == "S" else 1.0   # a goalie's minutes are already a share of team minutes
        dates = sched.get(p["team"]) or []
        g0 = len(dates)
        inj = (injuries or {}).get(pid)
        ig = injury_games(inj.get("status"), inj.get("ret"), dates, today) if inj else 0
        players.append({"id": pid, "name": p["name"], "team": p["team"], "pos": p["pos"], "kind": kind, "age": p.get("age"),
                        "rate": p["rate"], "mpg": p["mpg"], "avail": av, "t_eff": t_eff, "games": [g0] + future, "gpw": gpw,
                        "frac0": g0 / max(n_season, 1), "repl": (pos_fit.get(p["pos"]) or {}).get("repl", 0.0), "inj_games0": ig,
                        "inj": inj, "basis": p.get("basis")})
    res = project(players, f)
    cols = ["id", "name", "team", "pos", "age", "rate", "se", "mpg", "avail", "games", "now", "next", "total", "p10", "p90", "vorp",
            "s1", "s3", "inj", "basis"]
    rows = []
    for r in sorted(res, key=lambda r: -r["total"]):
        inj = r.get("inj") or None
        rows.append([r["id"], r["name"], r["team"], r["pos"], _r(r.get("age"), 1), _r(r["rate"], 3), _r(r["se"], 3), _r(r["mpg"], 1),
                     _r(r["avail"], 3), r["games"][0], _r(r["ev"][0], 2), _r(r["ev"][1] if len(r["ev"]) > 1 else None, 2), _r(r["total"], 2),
                     _r(r["p10"], 2), _r(r["p90"], 2), _r(r["vorp"], 2), _r(r["surv"][0] if r["surv"] else None, 3),
                     _r(r["surv"][-1] if r["surv"] else None, 3),
                     [inj.get("status"), inj.get("ret") or None, r["inj_games0"]] if inj else None, r.get("basis")])
    rel = f.get("reliability") or {}
    surv = f.get("survival") or {}
    curves_s = {}
    for kind, (rate, mpg) in (("S", (0.0, 16.0)), ("G", (0.0, 40.0))):
        curves_s[kind] = [[a, round(survival_p(surv.get(kind), a, rate, mpg, kind), 3)] for a in range(19, 41)]
    return {"ok": True, "season": int(season), "updated_at": an.now(), "phase": phase, "version": VERSION,
            "currency": {"unit": "WAR", "goals_per_win": _r(gpw, 2)},
            "constants": {"discount": DISCOUNT, "horizon": HORIZON, "draws": N_DRAWS, "avail_pseudo": AVAIL_PSEUDO,
                          "avail_mean": a0, "regular": REGULAR, "games": [n_season] + future, "injury_games": INJ_GAMES,
                          "shrink_minutes": VAL.SHRINK_MIN, "prev_weight": VAL.PREV_WEIGHT},
            "fits": {"reliability": {k: {kk: vv for kk, vv in v.items() if kk != "bins"} for k, v in rel.items()},
                     "minutes": f.get("minutes"), "survival": {k: {kk: vv for kk, vv in v.items() if kk != "by_age"} for k, v in surv.items()},
                     "survival_by_age": {k: v.get("by_age") for k, v in surv.items()}, "positional": f.get("positional"),
                     "completed": f.get("completed")},
            "curves": {"aging": f.get("aging"), "survival": curves_s},
            "cols": cols, "rows": rows, "_ev": {r["id"]: {"ev": r["ev"], "total": r["total"]} for r in res},
            "note": "Projected on-field value (Rink value, WAR) over the rest of this season and the next three, discounted "
                    "0.9 a season, with survival, availability and ageing. Not contracts or the salary cap (no salary source)."}


# ---------------------------------------------------------------------------------------------- as of a date (trade ratings)

def season_of(d: date) -> int:
    """The valuation season of a date: from 1 July the season that starts that autumn."""
    return an.season_id(d.year if d.month >= 7 else d.year - 1)


class AsOf:
    """Valuation of any player as of a date with no hindsight: GAR rates from the seasons completed before the date only,
    minutes a game and availability from games before the date (gamelog), team games left after the date from the
    season's store. Model parameters (ageing, survival, reliability) are the ones fitted on all completed seasons."""

    def __init__(self, vr: dict[int, dict], f: dict, logs: dict, stores: dict[int, dict], today: date):
        self.vr, self.f, self.today = vr, f, today
        self.by = {s: {r["id"]: r for r in x["rows"]} for s, x in vr.items()}
        self.logs = logs
        self.stores = stores
        sk, gk = logs.get("sk"), logs.get("gk")
        self.sk = sk if sk is not None and len(sk) else None
        self.gk = gk if gk is not None and len(gk) else None
        self._sched: dict[int, dict[str, list[str]]] = {}

    def _completed_before(self, d: date) -> list[int]:
        """Seasons before the date's valuation season (from 1 July the season just ended counts as completed)."""
        return sorted(s for s in self.vr if s < season_of(d))

    def team_dates(self, season: int) -> dict[str, list[str]]:
        if season not in self._sched:
            st = self.stores.get(season) or {}
            out: dict[str, list[str]] = {}
            gs = st.get("games") or {}
            for g in (gs.values() if isinstance(gs, dict) else gs):
                gid = str(g.get("game_id") or "")
                if gid[4:6] != "02":
                    continue
                for t in (g.get("home"), g.get("away")):
                    if t:
                        out.setdefault(t, []).append(str(g.get("date") or "")[:10])
            self._sched[season] = {t: sorted(v) for t, v in out.items()}
        return self._sched[season]

    def player(self, pid: str, team: str, d: date, pos_hint: str | None = None, dob: str | None = None) -> dict | None:
        """Inputs of `project` for player `pid` joining `team` on date d (None without any NHL data before d)."""
        from oddsmarkets.nhl import canon
        s0 = season_of(d)
        done = self._completed_before(d)
        rows = [(s, self.by[s].get(pid)) for s in reversed(done) if self.by[s].get(pid)]
        last_c = done[-1] if done else None
        c = self.by.get(last_c, {}).get(pid) if last_c else None
        p = self.by.get(done[-2], {}).get(pid) if len(done) >= 2 else None
        kind = "G" if (pos_hint == "G" or (rows and rows[0][1].get("kind") == "G")) else "S"
        ds = d.isoformat()
        log = None
        if kind == "S" and self.sk is not None:
            log = self.sk[(self.sk["pid"] == int(pid)) & (self.sk["season"] == s0) & (self.sk["date"] < ds) & (self.sk["gt"] == "R")]
        elif kind == "G" and self.gk is not None:
            log = self.gk[(self.gk["pid"] == int(pid)) & (self.gk["season"] == s0) & (self.gk["date"] < ds) & (self.gk["gt"] == "R")]
        gp_now = int(len(log)) if log is not None else 0
        if not rows and gp_now == 0:
            return None
        cg = _f((c or {}).get("gar"))
        ct = _f((c or {}).get("toi")) or 0.0
        pg = _f((p or {}).get("gar"))
        pt = _f((p or {}).get("toi")) or 0.0
        num = den = 0.0
        if cg is not None and ct > 0:
            num += cg
            den += ct
        if pg is not None and pt > 0:
            num += VAL.PREV_WEIGHT * pg
            den += VAL.PREV_WEIGHT * pt
        rate = num / (den + VAL.SHRINK_MIN[kind]) * 60.0 if den > 0 else 0.0
        age_c = _f((c or {}).get("age"))
        age = None
        if dob:
            age = an.age_on(dob, s0)
        elif age_c is not None:
            age = age_c + 1.0
        if c is not None and age_c is not None:
            rate += VAL.aging_delta((self.f.get("aging") or {}).get(kind), age_c)
        # minutes a game: games before the date this season, blended with the last completed season (10 games)
        dates_all = self.team_dates(s0)
        tg_before = {t: sum(1 for x in v if x < ds) for t, v in dates_all.items()}
        if kind == "S":
            toi_now = float(log["toi"].sum()) if log is not None and len(log) else 0.0
            cgp = int(an.inum((c or {}).get("gp")) or 0)
            if cgp > 0 and ct > 0:
                mpg = (toi_now + VAL.TOI_PRIOR_GAMES * ct / cgp) / (gp_now + VAL.TOI_PRIOR_GAMES)
            else:
                mpg = toi_now / gp_now if gp_now else 0.0
        else:
            toi_now = float(log["toi"].sum()) if log is not None and len(log) else 0.0
            team_before = max(tg_before.values() or [0]) if gp_now else 0
            tg_c = self.vr.get(last_c, {}).get("team_games", 82) if last_c else 82
            cs = toi_now / (team_before * 60.0) if team_before > 0 else None
            ps = ct / (tg_c * 60.0) if ct > 0 else None
            if cs is not None and ps is not None:
                share = (cs * team_before + ps * VAL.TOI_PRIOR_GAMES) / (team_before + VAL.TOI_PRIOR_GAMES)
            else:
                share = cs if cs is not None else ps if ps is not None else 0.0
            mpg = min(1.0, share) * 60.0
        gp_tg = [(float(gp_now), float(max(tg_before.values() or [0])))]
        for s in reversed(done[-2:]):
            r = self.by[s].get(pid)
            gp_tg.append((float(an.inum((r or {}).get("gp")) or 0), float(self.vr[s]["team_games"])))
        av = availability(gp_tg, float((self.f.get("avail") or {}).get(kind) or 0.85)) if kind == "S" else 1.0
        left = sum(1 for x in dates_all.get(team, []) if x >= ds)
        n_season = canon.games_per_team(s0)
        future = [canon.games_per_team(an.season_id(an.start_year(s0) + k)) for k in range(1, HORIZON + 1)]
        gpw = self.vr.get(last_c, {}).get("gpw") if last_c else None
        role = VAL.role_of(pos_hint or (rows[0][1].get("pos") if rows else None)) if kind == "S" else "G"
        return {"id": pid, "kind": kind, "pos": role, "age": age, "rate": rate, "mpg": mpg, "avail": av,
                "t_eff": ct + VAL.PREV_WEIGHT * pt, "games": [left] + future, "gpw": gpw or 6.0, "frac0": left / max(n_season, 1),
                "season": s0, "basis": "b" if cg is not None and pg is not None else "c" if cg is not None else "p" if pg is not None else "r"}
