"""
Fitting and walk-forward evaluation for The Quant Scrum (docs/scrum/MODELS.md).

Years. Calendar years. The development years (DEV, 2004-2018) choose every parameter; the sealed test years (TEST,
2019 to the last finished match) are scored once with those parameters. 1995-2003 is burn-in only (no score).
Matches: men's tests with a result (draws included), both sides known. Every forecast is made before the match from
results already played (the model state is updated after the forecast), so nothing leaks forward.

The ladder, each rung promoted only if it beats the rung below on the sealed test years (paired 95% interval of the
per-match log-loss difference excludes zero, calibration no worse):
  wr     our World Rugby rankings replica (rankings.py), its points gap (with World Rugby's own 3-point home
         allowance before July 2026) mapped to a chance by a logistic fitted on the development years, draws at the
         development years' rate
  elo    our single margin rating (ratings.py, split=False) with home advantage
  unc    + uncertainty (Glicko-style): the margin spread widens for a side with few tests rated and for tests between
         lesser sides (by the weaker side's tier), and a new side's rating learns faster
  ctx    + travel (distance and time zones) and rest
  split  attack and defence ratings (gives the expected total as well as the margin)
  hybrid (post hoc, reported as such) the best rung, with the chance of any test involving a tier-three side taken
         from the World Rugby rebuild: the development years hold 10 such tests, so our rating has no settings
         chosen for them; decided after the test years showed the gap, so its test score is not a sealed result
The try model (tries ~ Poisson(t0 + t1 x expected points)) is scored against a constant-rate Poisson the same way.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, replace

from . import nations, rankings
from .ratings import Model, Params, brier, logloss, ncdf, outcome

DEV = (2004, 2018)
TEST_FROM = 2019
BURN_FROM = 1995


def eligible(matches: list[dict]) -> list[dict]:
    out = []
    for m in matches:
        if m.get("status") != "final" or m.get("hs") is None or m.get("as") is None:
            continue
        if not (m.get("home") or {}).get("id") or not (m.get("away") or {}).get("id"):
            continue
        if m["hs"] == 0 and m["as"] == 0:
            continue                        # a 0-0 in this feed is an unplayed or abandoned fixture
        out.append(m)
    out.sort(key=lambda m: (m.get("date") or "", m["id"]))
    return out


def year(m: dict) -> int:
    return int(str(m.get("date") or "0000")[:4])


# ── our model, walked forward ──────────────────────────────────────────────────────────────────────────────

def walk(matches: list[dict], p: Params, keep_from: int = DEV[0], hook=None, wr_fit: dict | None = None) -> list[dict]:
    """Forecast every match before updating; returns rows for matches from `keep_from` on."""
    mdl = Model(p)
    mdl.wr_fit = wr_fit
    rows = []
    for m in matches:
        y = year(m)
        mdl.new_year(y)
        e = mdl.expect(m)
        if y >= keep_from:
            rows.append({"id": m["id"], "y": y, "date": m["date"], "p": (e["p_home"], e["p_draw"], e["p_away"]),
                         "o": outcome(m), "margin": e["margin"], "total": e["total"], "exp_h": e["exp_h"],
                         "exp_a": e["exp_a"], "hs": m["hs"], "as": m["as"], "home": m["home"]["id"], "away": m["away"]["id"]})
        if hook:
            hook(mdl, m, e)
        mdl.update(m, e)
    return rows


def score(rows: list[dict], lo: int, hi: int) -> dict:
    r = [x for x in rows if lo <= x["y"] <= hi]
    if not r:
        return {"n": 0}
    ll = sum(logloss(x["p"], x["o"]) for x in r) / len(r)
    br = sum(brier(x["p"], x["o"]) for x in r) / len(r)
    mae = sum(abs((x["hs"] - x["as"]) - x["margin"]) for x in r if "margin" in x) / len(r) if "margin" in r[0] else None
    return {"n": len(r), "logloss": round(ll, 5), "brier": round(br, 5), "mae_margin": None if mae is None else round(mae, 3)}


def tune(matches: list[dict], base: Params, grid: dict, rounds: int = 2) -> tuple[Params, float]:
    """Coordinate descent on the development years' log-loss."""
    best = base
    best_ll = score(walk(matches, best), *DEV)["logloss"]
    for _ in range(rounds):
        for k, vals in grid.items():
            for v in vals:
                cand = replace(best, **{k: v})
                ll = score(walk(matches, cand), *DEV)["logloss"]
                if ll < best_ll - 1e-6:
                    best, best_ll = cand, ll
    return best, best_ll


GRID_ELO = {"H": [2.0, 3.0, 4.0, 5.0, 6.0, 7.0], "k": [0.06, 0.08, 0.10, 0.12, 0.15, 0.18, 0.22],
            "k_new": [0.2, 0.3, 0.4, 0.5], "cap": [20.0, 25.0, 30.0, 40.0, 60.0], "revert": [0.0, 0.1, 0.2, 0.3],
            "s0": [9.0, 10.0, 11.0, 12.0, 13.0, 14.0], "s1": [0.0, 0.05, 0.1, 0.15, 0.2, 0.25]}
GRID_UNC = {"s_n": [0.0, 10.0, 20.0, 30.0, 40.0, 60.0, 80.0], "s_tier": [0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0], "k_new": [0.2, 0.3, 0.4, 0.5, 0.7], "n_new": [4, 8, 12, 20]}
GRID_CTX = {"c_km": [0.0, 0.5, 1.0, 1.5, 2.0, 3.0], "c_tz": [0.0, 0.1, 0.2, 0.3, 0.5], "c_rest": [0.0, 0.25, 0.5, 1.0]}


# ── the World Rugby replica as a forecaster ────────────────────────────────────────────────────────────────

def replica(matches: list[dict], seed: dict | None = None) -> tuple[rankings.Ranker, list[dict]]:
    """Roll the replica through every match; rows carry the pre-match gap (home allowance as World Rugby applied it)."""
    def default(team, when):
        return {1: 78.0, 2: 66.0, 3: 52.0}[nations.tier(NAMES.get(team, ""))]
    rk = rankings.Ranker(seed=seed or {}, default=default)
    rows = []
    for m in matches:
        h, a = m["home"]["id"], m["away"]["id"]
        NAMES[h], NAMES[a] = m["home"]["name"], m["away"]["name"]
        if nations.invitational(m["home"]["name"]) or nations.invitational(m["away"]["name"]):
            continue                      # Lions and invitational sides: outside the rankings
        ra, rb = rk.get(h, m["date"]), rk.get(a, m["date"])
        home_bonus = rankings.HOME_BONUS if (not m.get("neutral") and str(m["date"])[:10] < rankings.HOME_BONUS_ENDS) else 0.0
        rows.append({"id": m["id"], "y": year(m), "gap": ra + home_bonus - rb, "o": outcome(m), "date": m["date"],
                     "hs": m["hs"], "as": m["as"], "home": h, "away": a, "ra": ra, "rb": rb})
        rk.update(h, a, m["hs"], m["as"], m["date"], neutral=bool(m.get("neutral")),
                  world_cup=bool(m.get("comp") == "rwc"))
    return rk, rows


NAMES: dict[str, str] = {}


def fit_wr(rows: list[dict]) -> dict:
    """Logistic P(home win | no draw) = 1 / (1 + exp(-(a + b gap))) and a constant draw rate, on the development years."""
    dev = [r for r in rows if DEV[0] <= r["y"] <= DEV[1]]
    d = sum(1 for r in dev if r["o"] == 1) / max(1, len(dev))
    a, b = 0.0, 0.2
    for _ in range(200):                     # Newton on the decisive matches
        ga = gb = haa = hab = hbb = 0.0
        for r in dev:
            if r["o"] == 1:
                continue
            y = 1.0 if r["o"] == 0 else 0.0
            z = a + b * r["gap"]
            p = 1.0 / (1.0 + math.exp(-z))
            ga += y - p
            gb += (y - p) * r["gap"]
            w = p * (1 - p)
            haa += w
            hab += w * r["gap"]
            hbb += w * r["gap"] ** 2
        det = haa * hbb - hab * hab
        if det <= 0:
            break
        da = (hbb * ga - hab * gb) / det
        db = (-hab * ga + haa * gb) / det
        a, b = a + da, b + db
        if abs(da) < 1e-9 and abs(db) < 1e-9:
            break
    return {"a": a, "b": b, "draw": d}


def wr_probs(gap: float, f: dict) -> tuple[float, float, float]:
    p = 1.0 / (1.0 + math.exp(-(f["a"] + f["b"] * gap)))
    d = f["draw"]
    return (1 - d) * p, d, (1 - d) * (1 - p)


# ── comparisons ────────────────────────────────────────────────────────────────────────────────────────────

def paired(a: list[dict], b: list[dict], lo: int, hi: int) -> dict:
    """Mean per-match log-loss of b minus a (negative = b better) with a normal 95% interval, on matches both scored."""
    pa = {r["id"]: r for r in a if lo <= r["y"] <= hi}
    d = [logloss(r["p"], r["o"]) - logloss(pa[r["id"]]["p"], pa[r["id"]]["o"]) for r in b if r["id"] in pa and lo <= r["y"] <= hi]
    if not d:
        return {"n": 0}
    n = len(d)
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / max(1, n - 1))
    se = sd / math.sqrt(n)
    return {"n": n, "diff": round(mu, 5), "lo": round(mu - 1.96 * se, 5), "hi": round(mu + 1.96 * se, 5),
            "better": (mu + 1.96 * se) < 0}


def calibration(rows: list[dict], lo: int, hi: int, nb: int = 10) -> dict:
    """Home-win chance against the home-win rate, in ten buckets; ECE (weighted mean absolute gap)."""
    r = [x for x in rows if lo <= x["y"] <= hi]
    bins = []
    ece = 0.0
    for i in range(nb):
        a, b = i / nb, (i + 1) / nb
        sel = [x for x in r if a <= x["p"][0] < b or (i == nb - 1 and x["p"][0] == 1.0)]
        if not sel:
            continue
        mp = sum(x["p"][0] for x in sel) / len(sel)
        fr = sum(1 for x in sel if x["o"] == 0) / len(sel)
        bins.append({"lo": round(a, 2), "hi": round(b, 2), "n": len(sel), "mean_p": round(mp, 4), "freq": round(fr, 4)})
        ece += len(sel) * abs(mp - fr)
    return {"bins": bins, "ece": round(ece / max(1, len(r)), 4), "n": len(r)}


# ── the try model ──────────────────────────────────────────────────────────────────────────────────────────

def poisson_ll(k: int, lam: float) -> float:
    lam = max(lam, 1e-6)
    return -(k * math.log(lam) - lam - math.lgamma(k + 1))


def fit_tries(rows: list[dict], matches_by_id: dict) -> dict:
    """tries = Poisson(t0 + t1 x expected points), least squares on the development years; and the conditional
    tries-given-points line the simulator uses (tries ~ c0 + c1 x points)."""
    xs, ys, ps = [], [], []
    for r in rows:
        if not (DEV[0] <= r["y"] <= DEV[1]):
            continue
        m = matches_by_id.get(r["id"])
        th, ta = (m.get("hstat") or {}).get("tries"), (m.get("astat") or {}).get("tries")
        if th is None or ta is None:
            continue
        xs += [r["exp_h"], r["exp_a"]]
        ys += [th, ta]
        ps += [r["hs"], r["as"]]

    def ls(x, y):
        n = len(x)
        if n < 10:
            return 0.0, 0.13
        mx, my = sum(x) / n, sum(y) / n
        sxx = sum((a - mx) ** 2 for a in x)
        sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
        b1 = sxy / sxx if sxx else 0.0
        return my - b1 * mx, b1
    t0, t1 = ls(xs, ys)
    c0, c1 = ls(ps, ys)
    mean = sum(ys) / max(1, len(ys))
    return {"t0": round(t0, 4), "t1": round(t1, 4), "c0": round(c0, 4), "c1": round(c1, 4), "mean": round(mean, 4), "n": len(ys)}


def score_tries(rows: list[dict], matches_by_id: dict, f: dict, lo: int, hi: int) -> dict:
    d, nb = [], 0
    for r in rows:
        if not (lo <= r["y"] <= hi):
            continue
        m = matches_by_id.get(r["id"])
        th, ta = (m.get("hstat") or {}).get("tries"), (m.get("astat") or {}).get("tries")
        if th is None or ta is None:
            continue
        for k, e in ((th, r["exp_h"]), (ta, r["exp_a"])):
            ours = poisson_ll(k, f["t0"] + f["t1"] * e)
            base = poisson_ll(k, f["mean"])
            d.append(ours - base)
            nb += 1
    if not d:
        return {"n": 0}
    n = len(d)
    mu = sum(d) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in d) / max(1, n - 1))
    se = sd / math.sqrt(n)
    return {"n": n, "diff": round(mu, 5), "lo": round(mu - 1.96 * se, 5), "hi": round(mu + 1.96 * se, 5), "better": mu + 1.96 * se < 0}


def total_sd(rows: list[dict], lo: int, hi: int) -> float:
    r = [x for x in rows if lo <= x["y"] <= hi]
    if not r:
        return 13.0
    return math.sqrt(sum(((x["hs"] + x["as"]) - x["total"]) ** 2 for x in r) / len(r))


# ── the value model: margin on process-stat differences (ridge) ────────────────────────────────────────────

# Quality, not volume: carries, passes, rucks, kicks and knock-ons track how much of the ball a side had (and a side
# ahead kicks more), so they would credit game state rather than skill; they are left out of the value model.
VALUE_TEAM = {"m": "metres", "cb": "breaks", "db": "beaten", "off": "offloads", "tk": "tackles", "mt": "missed",
              "toc": "to_conc", "pc": "pens", "yc": "yc", "rc": "rc", "lo": "lineouts_won"}


def fit_value(matches: list[dict], lam: float = 50.0) -> dict:
    """Ridge regression (standardised, no intercept: home minus away) of the margin on the process-stat differences,
    on the development years where the team stats exist (ESPN's team stats start around 2010, so in practice
    2010-2018). Returns weights in points per unit of each stat, and the out-of-sample R^2 on the test years."""
    keys = list(VALUE_TEAM)

    def rows(lo, hi):
        X, y = [], []
        for m in matches:
            yy = year(m)
            if not (lo <= yy <= hi):
                continue
            hs_, as_ = m.get("hstat") or {}, m.get("astat") or {}
            if not hs_ or not as_ or any(hs_.get(VALUE_TEAM[k]) is None or as_.get(VALUE_TEAM[k]) is None for k in keys):
                continue
            X.append([float(hs_[VALUE_TEAM[k]]) - float(as_[VALUE_TEAM[k]]) for k in keys])
            y.append(float(m["hs"] - m["as"]))
        return X, y
    X, y = rows(*DEV)
    n = len(X)
    if n < 50:
        return {"ok": False, "n": n}
    p = len(keys)
    sd = [math.sqrt(sum(r[j] ** 2 for r in X) / n) or 1.0 for j in range(p)]
    Z = [[r[j] / sd[j] for j in range(p)] for r in X]
    A = [[sum(Z[i][a] * Z[i][b] for i in range(n)) + (lam if a == b else 0.0) for b in range(p)] for a in range(p)]
    v = [sum(Z[i][a] * y[i] for i in range(n)) for a in range(p)]
    beta = _solve(A, v)
    w = {k: beta[j] / sd[j] for j, k in enumerate(keys)}
    Xt, yt = rows(TEST_FROM, 2100)

    def r2(X_, y_):
        if not X_:
            return None
        pred = [sum(w[k] * r[j] for j, k in enumerate(keys)) for r in X_]
        ss = sum((a - b) ** 2 for a, b in zip(y_, pred))
        st = sum(a ** 2 for a in y_)
        return round(1 - ss / st, 4) if st else None
    return {"ok": True, "n": n, "n_test": len(Xt), "weights": {k: round(v_, 5) for k, v_ in w.items()},
            "r2_dev": r2(X, y), "r2_test": r2(Xt, yt), "lambda": lam}


def _solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[piv] = M[piv], M[c]
        if abs(M[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] if abs(M[i][i]) > 1e-12 else 0.0 for i in range(n)]


def as_dict(p: Params) -> dict:
    d = asdict(p)
    d.pop("tiers", None)
    return d
