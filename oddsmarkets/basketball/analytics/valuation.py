"""
Valuation v2 for The Quant Hardwood: a player's projected value over a four-season window, in wins above
replacement (WAR, analytics/value.py), with ageing, survival, availability, uncertainty and position scarcity
(docs/VALUE_SECTIONS.md section 4; payload valuation.json in PAYLOADS.md "Valuation, moves and fantasy").

Window and discounting
----------------------
Four season slots starting now: the rest of the current season (when games are left) and the following seasons
until four slots are used (in the offseason: the next four seasons). Slot k is discounted DISCOUNT^k (0.9).

    value = sum_k  0.9^k x S_k x A_k x G_k x m x (r_k - R) x pace / G_min / 100 / points per win

r_0     the rest-of-season HPM (value.player_projection: this season blended with last season's projection)
r_k     r_0 plus the fitted ageing steps (below) for each season passed
R       replacement level (-2.0 per 100; value over positional replacement uses the position's own level)
m       minutes a game from the team's depth chart (value.baseline_minutes; capped, five players' worth)
G_k     games in the slot (games left now; a full season after)
A_k     availability: share of team games played over the last two seasons, regressed to the league mean with
        AVAIL_K (40) pseudo-games; slot 0 also takes out games the injury report rules the player out of
S_k     survival: probability he is still playing k seasons on (fitted logistic, below), S_0 = 1
future slots are floored at zero (a player below replacement stops being played); slot 0 is not (he is rostered)

Fits (cached on the completed seasons' value.json and the bio file; data/<L>/<S>/value.json rows, ages from
analytics/bio.py)
--------------------------------------------------------------------------------------------------------
Ageing   delta method on consecutive seasons with AGING_MIN (500) minutes in both: the average change in HPM by
         age, weighted by the harmonic mean of the two seasons' minutes, shrunk towards zero (AGING_SHRINK pseudo-
         weight) and smoothed over neighbouring ages. Not centred: HPM is zero-mean each season, and the average
         continuing player's measured HPM does rise (+0.17 a season), so the raw change is the unbiased forecast.
Survival P(plays SURV_NEXT_MIN (100) minutes next season | played SURV_MIN (200) this season) by logistic
         regression on age, age squared, HPM and log minutes.
Spread   one-season-ahead residual of HPM around the ageing curve (sd s1) and two seasons ahead (s2):
         persistent error var s1^2 - tau^2, yearly drift tau^2 = s2^2 - s1^2 (both from the data, so the band
         is what our own model will measure, not a guess). Scaled up for players with little information.
Bands    p10 / p50 / p90 of a Monte Carlo over the persistent error, the drift, minutes (lognormal, the fitted
         year-to-year minutes spread) and survival (Bernoulli each season); N_SIMS draws, fixed seed.

Position scarcity
-----------------
Replacement level by position group (guards, wings, bigs): the mean projected HPM of the best N_teams players at
that position outside every team's top ROTATION players by depth-chart minutes (the freely available talent).
VORP at position replaces R by that level. The scarcity index is R minus the position's level (positive: the
position's freely available players are worse than the league's, so good players there are scarcer).
"""
from __future__ import annotations

import hashlib
import logging
import math
from typing import Any, Iterable

import numpy as np

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import bio as BIO
from oddsmarkets.basketball.analytics import value as VAL

logger = logging.getLogger(__name__)

VERSION = 1
SLOTS = 4
DISCOUNT = 0.9
AGING_MIN = 500.0
AGING_SHRINK = 10000.0
AGES = (19, 41)
SURV_MIN = 200.0
SURV_NEXT_MIN = 100.0
AVAIL_K = 40.0
AVAIL_MIN = 500.0
INFO_MIN = 1500.0                 # minutes of information at which a player's spread is the fitted one
N_SIMS = 400
ROTATION = {"nba": 9, "wnba": 8}
DEFAULT_FITS = {"aging": None, "surv": [2.4, -0.06, -0.035, 0.32, 0.0], "s1": 2.0, "tau": 0.9, "avail": 0.82, "min_cv": 0.25}
COLS = ["id", "name", "team", "pos", "role", "age", "basis", "rate", "sd", "mpg", "avail", "inj", "g0", "w0", "w1", "w2", "w3",
        "v", "p10", "p50", "p90", "surv", "vorp", "pct", "rank"]


def _f(v: Any) -> float | None:
    return an.fnum(v)


def _r(v: Any, nd: int = 2) -> float | None:
    v = _f(v)
    return None if v is None else round(v, nd)


# ---------------------------------------------------------------------------------------------- history

def season_rows(league: str, seasons: Iterable[int], data=None) -> dict[int, list[dict]]:
    """{season: [{"id","hpm","min","gp","role","se","age","games"}]} from each season's value.json, ages from the bio
    file (age on the season's reference day)."""
    out: dict[int, list[dict]] = {}
    root = data or an.data_root()
    bp = BIO.players(league)
    for s in seasons:
        v = an.read_json(root / league / str(s) / "value.json") or {}
        cols = v.get("cols") or []
        if not cols or not v.get("rows"):
            continue
        games = int(((v.get("currency") or {}).get("games")) or VAL.season_games(league, s))
        rows = []
        for r in v["rows"]:
            x = dict(zip(cols, r))
            h, m = _f(x.get("hpm")), _f(x.get("min")) or 0.0
            if h is None or m <= 0:
                continue
            dob = (bp.get(str(x["id"])) or {}).get("dob")
            age = BIO.season_age(league, s, dob) if dob else _f(x.get("age"))
            rows.append({"id": str(x["id"]), "hpm": h, "min": m, "gp": int(x.get("gp") or 0), "role": x.get("role"),
                         "se": _f(x.get("se")), "age": age, "games": games, "team": x.get("team")})
        out[int(s)] = rows
    return out


def _sig(league: str, seasons: list[int]) -> str:
    # path-independent (relative path, size, content digest), so the cache travels between the PC and CI
    from oddsmarkets.basketball.models import _io as _bio
    h = hashlib.sha1()
    root = an.data_root() / league
    for s in seasons:
        h.update(f"{s}:{_bio.path_sig(root / str(s) / 'value.json')}".encode())
    h.update(f"bio:{_bio.path_sig(BIO.bio_path(league))}".encode())
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------- fits

def aging_curve(rows_by: dict[int, list[dict]]) -> tuple[list[list[float]], dict]:
    """[[age, change in HPM over the next season]] for AGES, and fit facts."""
    S: dict[int, float] = {}
    W: dict[int, float] = {}
    n = 0
    for s in sorted(rows_by):
        nxt = {x["id"]: x for x in rows_by.get(s + 1) or []}
        if not nxt:
            continue
        for x in rows_by[s]:
            y = nxt.get(x["id"])
            if not y or x.get("age") is None or x["min"] < AGING_MIN or y["min"] < AGING_MIN:
                continue
            w = 2.0 / (1.0 / x["min"] + 1.0 / y["min"])
            a = int(round(x["age"]))
            S[a] = S.get(a, 0.0) + w * (y["hpm"] - x["hpm"])
            W[a] = W.get(a, 0.0) + w
            n += 1
    lo, hi = AGES
    if not W:
        return [[a, 0.0] for a in range(lo, hi + 1)], {"n_pairs": 0}
    mean = sum(S.values()) / sum(W.values())
    raw = {a: (S[a] / W[a]) * W[a] / (W[a] + AGING_SHRINK) for a in W}
    out = []
    for a in range(lo, hi + 1):
        num = den = 0.0
        for d, k in ((-1, 0.5), (0, 1.0), (1, 0.5)):
            if a + d in raw:
                num += k * W[a + d] * raw[a + d]
                den += k * W[a + d]
        out.append([a, round(num / den, 4) if den else 0.0])
    return out, {"n_pairs": n, "mean_change": round(mean, 4)}


def aging_delta(curve: list | None, age: float | None) -> float:
    if not curve or age is None or not math.isfinite(age):
        return 0.0
    xs = [c[0] for c in curve]
    ys = [c[1] for c in curve]
    return float(VAL.interp(xs, ys, float(age)) or 0.0)


def _spread(rows_by: dict[int, list[dict]], curve: list) -> dict:
    """Weighted sd of next-season and two-seasons-ahead HPM around the ageing path (players with AGING_MIN minutes)."""
    out = {}
    for lag in (1, 2):
        num = den = 0.0
        n = 0
        for s in sorted(rows_by):
            b = {x["id"]: x for x in rows_by.get(s + lag) or []}
            if not b:
                continue
            for x in rows_by[s]:
                y = b.get(x["id"])
                if not y or x.get("age") is None or x["min"] < AGING_MIN or y["min"] < AGING_MIN:
                    continue
                pred = x["hpm"] + sum(aging_delta(curve, x["age"] + j) for j in range(lag))
                w = 2.0 / (1.0 / x["min"] + 1.0 / y["min"])
                num += w * (y["hpm"] - pred) ** 2
                den += w
                n += 1
        out[lag] = (math.sqrt(num / den) if den else None, n)
    s1, n1 = out[1]
    s2, n2 = out[2]
    if s1 is None:
        return {"s1": DEFAULT_FITS["s1"], "tau": DEFAULT_FITS["tau"], "n1": 0, "n2": 0}
    tau2 = max(0.05, (s2 or s1) ** 2 - s1 ** 2) if s2 is not None else DEFAULT_FITS["tau"] ** 2
    tau2 = min(tau2, 0.8 * s1 ** 2)
    return {"s1": round(s1, 4), "s2": None if s2 is None else round(s2, 4), "tau": round(math.sqrt(tau2), 4), "n1": n1, "n2": n2}


def _logit_fit(X: np.ndarray, y: np.ndarray, w: np.ndarray | None = None, ridge: float = 1e-3, iters: int = 50) -> np.ndarray:
    """Logistic regression by iteratively reweighted least squares (small ridge for stability)."""
    n, k = X.shape
    w = np.ones(n) if w is None else w
    b = np.zeros(k)
    for _ in range(iters):
        z = np.clip(X @ b, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        W_ = w * p * (1 - p)
        H = X.T @ (X * W_[:, None]) + ridge * np.eye(k)
        g = X.T @ (w * (y - p)) - ridge * b
        step = np.linalg.solve(H, g)
        b = b + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b


def surv_features(age: float, hpm: float, minutes: float) -> list[float]:
    a = float(age) - 27.0
    return [1.0, a, a * a / 10.0, float(hpm), math.log(max(minutes, 50.0) / 1000.0)]


def survival_fit(rows_by: dict[int, list[dict]], last_complete: int) -> tuple[list[float], dict]:
    X, y = [], []
    for s in sorted(rows_by):
        if s + 1 > last_complete or not rows_by.get(s + 1):
            continue
        nxt = {x["id"]: x for x in rows_by[s + 1]}
        for x in rows_by[s]:
            if x.get("age") is None or x["min"] < SURV_MIN:
                continue
            X.append(surv_features(x["age"], x["hpm"], x["min"]))
            y.append(1.0 if (nxt.get(x["id"]) or {}).get("min", 0.0) >= SURV_NEXT_MIN else 0.0)
    if len(y) < 200:
        return list(DEFAULT_FITS["surv"]), {"n": len(y)}
    b = _logit_fit(np.array(X), np.array(y))
    p = 1.0 / (1.0 + np.exp(-np.clip(np.array(X) @ b, -30, 30)))
    ll = float(-np.mean(np.array(y) * np.log(p + 1e-12) + (1 - np.array(y)) * np.log(1 - p + 1e-12)))
    base = float(np.mean(y))
    ll0 = float(-(base * math.log(base) + (1 - base) * math.log(1 - base)))
    return [round(float(v), 5) for v in b], {"n": len(y), "rate": round(base, 4), "logloss": round(ll, 4), "logloss_base": round(ll0, 4)}


def p_survive(b: list[float], age: float | None, hpm: Any, minutes: Any) -> Any:
    """Probability of playing next season (scalar or numpy arrays for `hpm` / `minutes`)."""
    a = (27.0 if age is None else float(age)) - 27.0
    lm = np.log(np.maximum(np.asarray(minutes, dtype=float), 50.0) / 1000.0)
    z = b[0] + b[1] * a + b[2] * a * a / 10.0 + b[3] * np.asarray(hpm, dtype=float) + b[4] * lm
    p = 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))
    return float(p) if np.ndim(p) == 0 else p


def availability_mean(rows_by: dict[int, list[dict]]) -> float:
    xs = [min(1.0, x["gp"] / max(1, x["games"])) for rows in rows_by.values() for x in rows if x["min"] >= AVAIL_MIN]
    return float(np.mean(xs)) if xs else DEFAULT_FITS["avail"]


def minutes_cv(rows_by: dict[int, list[dict]]) -> float:
    """Spread of the year-to-year change in minutes a game (log scale) for players with AVAIL_MIN in both."""
    d = []
    for s in sorted(rows_by):
        b = {x["id"]: x for x in rows_by.get(s + 1) or []}
        for x in rows_by[s]:
            y = b.get(x["id"])
            if y and x["min"] >= AVAIL_MIN and y["min"] >= AVAIL_MIN and x["gp"] and y["gp"]:
                d.append(math.log((y["min"] / y["gp"]) / (x["min"] / x["gp"])))
    if len(d) < 50:
        return DEFAULT_FITS["min_cv"]
    return float(min(0.6, max(0.1, np.std(d))))


def fits(league: str, current: int, use_cache: bool = True) -> dict:
    """The ageing curve, survival model, spread, availability mean and minutes spread from every completed season
    before `current` (cached on those seasons' value.json files and the bio file)."""
    seasons = [s for s in an.seasons_on_disk(league) if s < current]
    sig = _sig(league, seasons)
    path = an.cache_root() / "value" / f"valuation_fits_{league}.json"
    if use_cache:
        c = an.read_json(path)
        if isinstance(c, dict) and c.get("key") == [VERSION, sig] and c.get("fits"):
            return c["fits"]
    rows_by = season_rows(league, seasons)
    curve, ainfo = aging_curve(rows_by)
    spread = _spread(rows_by, curve)
    surv, sinfo = survival_fit(rows_by, max(seasons) if seasons else current - 1)
    with_age = sum(1 for rows in rows_by.values() for x in rows if x.get("age") is not None)
    total = sum(len(rows) for rows in rows_by.values())
    out = {"aging": curve, "aging_info": ainfo, "aging_handset": [[a, d] for a, d in _handset()], "spread": spread,
           "surv": surv, "surv_info": sinfo, "avail": round(availability_mean(rows_by), 4), "min_cv": round(minutes_cv(rows_by), 4),
           "seasons": [min(seasons), max(seasons)] if seasons else None, "rows_with_age": with_age, "rows": total}
    try:
        an.write_json(path, {"key": [VERSION, sig], "fits": out})
    except OSError:
        pass
    return out


def _handset() -> list:
    from oddsmarkets.basketball.models.impact import AGE_CURVE
    return list(AGE_CURVE)


# ---------------------------------------------------------------------------------------------- one player

def project(rate: float, sd: float, mpg: float, age: float | None, slots: list[dict], fit: dict, prm: dict, repl: float | None = None,
            n: int = N_SIMS, seed: int = 0, avail: float | None = None) -> dict:
    """Multi-season value of one player. `slots`: [{"games": games in the slot, "avail": availability override}] (slot 0
    first); `repl`: the replacement level to measure from (default the league's). Returns the mean path
    ("war": [per slot]), the discounted total ("v"), its p10 / p50 / p90 and survival to the last slot."""
    R = prm["repl"] if repl is None else repl
    conv = prm["pace"] / prm["G"] / 100.0 / prm["ppw"]
    k_n = len(slots)
    tau = float((fit.get("spread") or {}).get("tau") or DEFAULT_FITS["tau"])
    curve = fit.get("aging")
    surv_b = fit.get("surv") or DEFAULT_FITS["surv"]
    cv = float(fit.get("min_cv") or DEFAULT_FITS["min_cv"])
    av = avail if avail is not None else float(fit.get("avail") or DEFAULT_FITS["avail"])
    # mean path
    steps = [aging_delta(curve, (age + j) if age is not None else None) for j in range(k_n)]
    rates = [rate + sum(steps[:k]) for k in range(k_n)]
    war, surv = [], []
    S = 1.0
    for k in range(k_n):
        a_k = slots[k].get("avail", av)
        g_k = float(slots[k]["games"])
        base = (rates[k] - R) * mpg * g_k * a_k * conv
        war.append(S * (base if k == 0 else max(0.0, base)))
        surv.append(S)
        S *= p_survive(surv_b, (age + k) if age is not None else None, rates[k], mpg * (g_k * a_k if g_k else 70.0))
    disc = [DISCOUNT ** k for k in range(k_n)]
    v_mean = sum(d * w for d, w in zip(disc, war))
    # Monte Carlo band
    rng = np.random.default_rng(seed)
    e0 = rng.normal(0.0, max(0.0, float(sd)), n)
    tot = np.zeros(n)
    alive = np.ones(n, dtype=bool)
    drift = np.zeros(n)
    for k in range(k_n):
        if k > 0:
            drift = drift + rng.normal(0.0, tau, n)
        r_k = rates[k] + e0 + drift
        if k > 0:
            mm = mpg * np.exp(rng.normal(-0.5 * cv * cv, cv, n))
        else:
            mm = np.full(n, float(mpg))
        a_k = slots[k].get("avail", av)
        g_k = float(slots[k]["games"])
        base = (r_k - R) * mm * g_k * a_k * conv
        if k > 0:
            base = np.maximum(0.0, base)
        tot += disc[k] * np.where(alive, base, 0.0)
        if k + 1 < k_n:
            p_k = p_survive(surv_b, (age + k) if age is not None else None, r_k, mm * (g_k * a_k if g_k else 70.0))
            alive = alive & (rng.random(n) < p_k)
    q = np.percentile(tot, [10, 50, 90])
    return {"rates": rates, "war": war, "surv": surv + [S], "v": v_mean, "p10": float(q[0]), "p50": float(q[1]), "p90": float(q[2])}


def player_sd(fit: dict, cur_min: float, prev_min: float, basis: str | None) -> float:
    """Persistent rate error for one player: sqrt(s1^2 - tau^2) at INFO_MIN minutes of information, scaled by
    sqrt(INFO_MIN / information) (information = this season's minutes + 0.7 x last season's, at least 250)."""
    sp = fit.get("spread") or {}
    s1 = float(sp.get("s1") or DEFAULT_FITS["s1"])
    tau = float(sp.get("tau") or DEFAULT_FITS["tau"])
    base = math.sqrt(max(0.25, s1 ** 2 - tau ** 2))
    info = max(250.0, float(cur_min or 0.0) + 0.7 * float(prev_min or 0.0))
    sd = base * math.sqrt(max(1.0, INFO_MIN / info))
    return min(sd, 3.0 * base) if basis != "r" else 3.0 * base


# ---------------------------------------------------------------------------------------------- positions

def positional_replacement(lists: dict[str, list[dict]], minutes: dict[str, dict[str, float]], league: str) -> dict:
    """{role: {"repl", "n", "top10"}}: the mean rate of the best N_teams players at the role outside every team's
    top ROTATION players by depth-chart minutes; "top10" the role's ten best rates among rotation players."""
    rot_n = ROTATION.get(league, 9)
    rotation = set()
    mins_of: dict[str, float] = {}
    for t, ps in lists.items():
        m = minutes.get(t) or {}
        order = sorted(ps, key=lambda p: (-m.get(p["id"], 0.0), str(p["id"])))
        for i, p in enumerate(order):
            mins_of[p["id"]] = float(m.get(p["id"], 0.0))
            if i < rot_n and m.get(p["id"], 0.0) >= 1.0:
                rotation.add(p["id"])
    n_teams = max(1, len(lists))
    everyone = [p for ps in lists.values() for p in ps]
    out = {}
    for role in VAL.ROLES:
        # the position's next tier of playing time: its players ranked by depth-chart minutes, after as many as the
        # league's rotations hold at that position, the next N_teams (ranked by minutes, not by rate, so noisy
        # small-sample rates do not select themselves)
        grp = sorted([p for p in everyone if (p.get("role") or "W") == role], key=lambda p: (-mins_of.get(p["id"], 0.0), str(p["id"])))
        slots = sum(1 for p in grp if p["id"] in rotation)
        cand = [p for p in grp[slots: slots + n_teams] if p.get("basis") != "r"]
        rot = sorted([float(p["rate"]) for p in grp if p["id"] in rotation], reverse=True)
        repl = float(np.mean([float(p["rate"]) for p in cand])) if len(cand) >= 3 else VAL.REPLACEMENT
        out[role] = {"repl": round(repl, 3), "n": len(cand), "slots": slots, "top10": round(float(np.mean(rot[:10])), 3) if rot else None,
                     "scarcity": round(VAL.REPLACEMENT - repl, 3)}
    return out


# ---------------------------------------------------------------------------------------------- the payload

def injury_games(status: str | None, detail: str | None, team_dates: list[str], today: str) -> int:
    """Games the injury report rules a player out of: until the return date when ESPN gives one, else 10 for "Out",
    1 for day-to-day / questionable."""
    s = str(status or "").lower()
    if not s:
        return 0
    import re
    m = re.search(r"return (\d{4}-\d{2}-\d{2})", str(detail or ""))
    if m:
        return sum(1 for d in team_dates if today <= d < m.group(1))
    if s.startswith("out"):
        return 10
    return 1


def build(ctx, cat: dict | None, prev_cat: dict | None, proj: dict[str, dict], prm: dict, games_left: dict[str, int],
          injuries: dict[str, list] | None = None, fit: dict | None = None, updated_at: str | None = None) -> dict:
    """valuation.json for the current season. `proj`: value.projections; `injuries`: {pid: [status, detail]}."""
    league, season = ctx.league, ctx.season
    fit = fit or fits(league, season)
    lists = VAL.team_lists(proj)
    minutes = {t: VAL.baseline_minutes(ps, prm) for t, ps in lists.items()}
    pos = positional_replacement(lists, minutes, league)
    full = VAL.season_games(league, season)
    P = ((cat or {}).get("players")) or {}
    PP = ((prev_cat or {}).get("players")) or {}
    team_dates: dict[str, list[str]] = {}
    for g in (ctx.games or {}).values():
        if g.get("status") != "post" and g.get("stype") in ("reg", None):
            d = str(g.get("date") or "")[:10]
            for t in (g.get("home"), g.get("away")):
                team_dates.setdefault(str(t), []).append(d)
    today = str(ctx.today)
    bio_p = BIO.players(league)
    team_gp = team_games_played(ctx.games)
    prev_full = VAL.season_games(league, season - 1)
    rows = []
    for t, ps in lists.items():
        left = int(games_left.get(t, full) or 0)
        for p in ps:
            pid = p["id"]
            mpg = float(minutes[t].get(pid, 0.0))
            cur, prv = P.get(pid) or {}, PP.get(pid) or {}
            gp = int(cur.get("gp") or 0) + int(prv.get("gp") or 0)
            team_g = (prev_full if prv.get("gp") else 0) + (max(int(cur.get("gp") or 0), team_gp.get(str(cur.get("team")), 0)) if cur.get("gp") else 0)
            avail = availability(gp, team_g, fit)
            inj = (injuries or {}).get(pid)
            miss = injury_games(inj[0], inj[1], sorted(team_dates.get(t) or []), today) if inj else 0
            slots = []
            if left > 0:
                g0 = max(0, left - miss)
                slots.append({"games": left, "avail": avail * (g0 / left) if left else avail})
            while len(slots) < SLOTS:
                slots.append({"games": full, "avail": avail})
            age = p.get("age")
            if age is None and (bio_p.get(pid) or {}).get("dob"):
                age = BIO.age_at(bio_p[pid]["dob"], today)
            sd = player_sd(fit, _f(cur.get("min")) or 0.0, _f(prv.get("min")) or 0.0, p.get("basis"))
            seed = int(hashlib.sha1(f"{league}{season}{pid}".encode()).hexdigest()[:8], 16)
            res = project(float(p["rate"]), sd, mpg, age, slots, fit, prm, seed=seed)
            role = p.get("role") or "W"
            res_pos = project(float(p["rate"]), sd, mpg, age, slots, fit, prm, repl=(pos.get(role) or {}).get("repl"), n=60, seed=seed)
            w = res["war"] + [None] * (SLOTS - len(res["war"]))
            rows.append({"id": pid, "name": p.get("name"), "team": t, "pos": p.get("pos"), "role": role, "age": age, "basis": p.get("basis"),
                         "rate": p["rate"], "sd": sd, "mpg": mpg, "avail": avail, "inj": (inj[0] if inj else None), "g0": left if left > 0 else 0,
                         "w0": w[0], "w1": w[1], "w2": w[2], "w3": w[3], "v": res["v"], "p10": res["p10"], "p50": res["p50"], "p90": res["p90"],
                         "surv": res["surv"][-2] if len(res["surv"]) >= 2 else None, "vorp": res_pos["v"]})
    ref = sorted(r["v"] for r in rows if r["mpg"] >= 10)
    rows.sort(key=lambda r: -r["v"])
    for i, r in enumerate(rows):
        r["pct"] = VAL.place(ref, r["v"]) if len(ref) >= 2 else None
        r["rank"] = i + 1
    nd = {"age": 1, "rate": 2, "sd": 2, "mpg": 1, "avail": 3, "w0": 2, "w1": 2, "w2": 2, "w3": 2, "v": 2, "p10": 2, "p50": 2, "p90": 2,
          "surv": 3, "vorp": 2}
    out_rows = [[(_r(r[c], nd[c]) if c in nd else r[c]) for c in COLS] for r in rows]
    slot_labels = []
    s0 = season
    if any(int(games_left.get(t, 0) or 0) > 0 for t in lists):
        slot_labels.append(f"rest of {s0}")
        nxt = s0 + 1
    else:
        nxt = s0 + 1
    while len(slot_labels) < SLOTS:
        slot_labels.append(str(nxt))
        nxt += 1
    return {"ok": True, "league": league, "season": int(season), "updated_at": updated_at or an.now(), "phase": ctx.phase,
            "version": VERSION, "cols": COLS, "rows": out_rows, "slots": slot_labels,
            "constants": {"discount": DISCOUNT, "slots": SLOTS, "replacement": VAL.REPLACEMENT, "avail_k": AVAIL_K, "n_sims": N_SIMS,
                          "aging_min": AGING_MIN, "surv_min": SURV_MIN, "surv_next_min": SURV_NEXT_MIN, "info_min": INFO_MIN,
                          "rotation": ROTATION.get(league), "pace": round(prm["pace"], 2), "points_per_win": round(prm["ppw"], 2),
                          "game_minutes": prm["G"], "games": full},
            "fit": {k: fit.get(k) for k in ("aging", "aging_info", "aging_handset", "spread", "surv", "surv_info", "avail", "min_cv",
                                              "seasons", "rows_with_age", "rows")},
            "survival_curve": [[a, round(p_survive(fit.get("surv") or DEFAULT_FITS["surv"], a, h, 2000.0), 3)] for a in range(20, 39)
                               for h in (0.0,)],
            "positions": pos,
            "note": "On-field value only (HPM wins above replacement); no salaries or contracts (no free, legitimate salary source)."}


def team_games_played(games: dict | None) -> dict[str, int]:
    """{team: regular-season games played} from a season's games."""
    n: dict[str, int] = {}
    for g in (games or {}).values():
        if g.get("status") == "post" and g.get("stype") == "reg":
            for t in (g.get("home"), g.get("away")):
                n[str(t)] = n.get(str(t), 0) + 1
    return n


def availability(gp: int, team_games: int, fit: dict) -> float:
    """Share of team games played, regressed to the league mean with AVAIL_K pseudo-games."""
    mu = float(fit.get("avail") or DEFAULT_FITS["avail"])
    return float((gp + AVAIL_K * mu) / (max(team_games, gp) + AVAIL_K))


# ---------------------------------------------------------------------------------------------- value at a date

def value_at(rate: float, sd: float, mpg: float, age: float | None, games_left: int, full: int, avail: float, fit: dict, prm: dict,
             slots_total: int = SLOTS, seed: int = 0, n: int = 200) -> dict:
    """Valuation of one player at a past date (trade ratings): `games_left` in that season, then full seasons."""
    slots = []
    if games_left > 0:
        slots.append({"games": games_left, "avail": avail})
    while len(slots) < slots_total:
        slots.append({"games": full, "avail": avail})
    return project(rate, sd, mpg, age, slots, fit, prm, n=n, seed=seed)
