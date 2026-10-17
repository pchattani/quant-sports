"""
Season decomposition of pace into a car effect (per constructor, per round) and a
driver effect (per driver, per season), for race pace and for qualifying pace.

Model
-----
Observation for driver i (driving for team t) at round r, in percent of the lap
(negative = faster than the field average):

    y_{i,r} = car_{t,r} + u_{t,r} + drv_i + e_{i,r},   e_{i,r} ~ N(0, se_{i,r}^2 + tau^2)
    car_{t,r} = car_{t,r'} + eta,              eta ~ N(0, q^2 * (r - r'))   (Gaussian random walk; r' = previous modelled round)
    u_{t,r} ~ N(0, kappa^2)                    (this round only: the car's fit to the circuit, shared by team-mates)
    car_{t,first} ~ N(0, 2^2),   drv_i ~ N(0, sigma_d^2)                     (driver effect shrunk to zero)

* u is what separates a car that suits one circuit from a car that has changed: without it every
  circuit-specific swing is read as a step of the random walk, q comes out large and the latest car state
  follows the last race (2026: Red Bull's one strong race made it the fastest car). With it, the latest
  state is the car's persistent level, which is what the next race can use (walk-forward check: Gaussian
  log-loss of the next round's pace per driver, 2012-2026, in docs/f1/MODELS.md section 3).

* Race y = race_pace(year, round).pace / reference lap * 100, with its se.
* Qualifying y = within-session pace: each driver's Q1/Q2/Q3 times are taken as % gaps
  to that segment's fastest time (track evolution is absorbed by comparing within a
  segment), then gap_{i,s} = a_i + b_s is solved by least squares across segments
  (b = segment offset, Q1 = 0; times > 105% of the segment's best are dropped), and
  a_i is centred on the field mean. se_{i,r} = 0.1% / sqrt(segments run).
* Identification: team-mates share car_{t,r}, so drv_i is the within-team difference;
  a driver who changes team mid-season is linked to both cars through his one drv_i.
  Because drv ~ N(0, sigma_d^2), a pair of team-mates who are equally fast both get
  drv = 0 and the car carries their common level.
* The model is linear-Gaussian, so the joint posterior is computed exactly by
  generalised least squares on the stacked state vector (car states for every
  modelled round plus driver effects) with the random-walk prior as a banded
  precision matrix: this is the Kalman smoother's answer, without a forward/backward pass.
* Hyperparameters (q, sigma_d, tau, kappa) maximise the marginal likelihood of y plus a weak
  log-normal prior centred on (0.15, 0.20, 0.30, 0.25)% for race and (0.10, 0.15, 0.15, 0.15)% for
  qualifying, so a season with two races still gets sensible values.

Never raises: missing data yields empty dicts and a "reason".
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

import numpy as np
from scipy.linalg import solve_triangular
from scipy.optimize import minimize

from oddsmarkets.f1 import canon
from oddsmarkets.f1.models.laptime import race_pace

CAR0_SD = 2.0                  # % of lap: prior sd of a car's first state
QUALI_SEG_CUTOFF = 1.05        # drop segment times > 105% of the segment's best
QUALI_OBS_SD = 0.10            # % : timing/lap noise of one segment's best lap
HYPER_PRIOR = {
    "race": {"q": 0.15, "sd": 0.20, "tau": 0.30, "kappa": 0.25},
    "quali": {"q": 0.10, "sd": 0.15, "tau": 0.15, "kappa": 0.15},
}
TEAM_ROUND_NOISE = True         # the u_{t,r} term (False = the model before October 2026)
# q fixed rather than fitted per season: the marginal-likelihood q tracks within-season wobble and predicts the
# next round worse than a slower walk (walk-forward check, MODELS.md section 3). None = fitted.
Q_FIXED: dict[str, float | None] = {"race": 0.06, "quali": 0.07}
HYPER_PRIOR_LOGSD = 0.7         # width of the log-normal hyperprior
STANDARD_POINTS = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]


# ===================================================================== observations

def quali_pace(qualifying: list[dict]) -> dict[str, dict[str, float]]:
    """{driverId: {"pace": % vs field (negative = faster), "se", "segments"}} for one session."""
    obs = []
    for seg in ("q1", "q2", "q3"):
        times = [(row["driver"], float(row[seg])) for row in qualifying or [] if row.get(seg) and row.get("driver")]
        times = [(d, t) for d, t in times if t > 0]
        if not times:
            continue
        best = min(t for _, t in times)
        for d, t in times:
            if t <= QUALI_SEG_CUTOFF * best:
                obs.append((d, seg, 100.0 * (t / best - 1.0)))
    if not obs:
        return {}
    drivers = sorted({o[0] for o in obs})
    segs = sorted({o[1] for o in obs})
    di = {d: i for i, d in enumerate(drivers)}
    si = {s: j for j, s in enumerate(segs[1:])}
    X = np.zeros((len(obs), len(drivers) + len(segs) - 1))
    y = np.zeros(len(obs))
    for k, (d, s, g) in enumerate(obs):
        X[k, di[d]] = 1.0
        if s in si:
            X[k, len(drivers) + si[s]] = 1.0
        y[k] = g
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    a = beta[: len(drivers)]
    a = a - a.mean()
    nseg = Counter(o[0] for o in obs)
    return {d: {"pace": float(a[di[d]]), "se": QUALI_OBS_SD / math.sqrt(nseg[d]), "segments": nseg[d]} for d in drivers}


def race_observations(year: int, upto_round: int | None = None) -> list[tuple]:
    """[(round, driver, team, y_pct, se_pct)] from race_pace for the season's rounds."""
    obs = []
    for r in canon.completed_rounds(year):
        if upto_round is not None and r > upto_round:
            continue
        rp = race_pace(year, r)
        ref = rp.get("ref_lap_s")
        if not rp.get("drivers") or not ref:
            continue
        for d, v in rp["drivers"].items():
            t = canon.team_for(year, r, d) or v.get("team")
            if t and v.get("se") is not None:
                obs.append((r, d, t, 100.0 * v["pace"] / ref, 100.0 * v["se"] / ref))
    return obs


def quali_observations(year: int, upto_round: int | None = None) -> list[tuple]:
    obs = []
    for r in canon.rounds(year):
        if upto_round is not None and r > upto_round:
            continue
        q = canon.race(year, r).get("qualifying") or []
        for d, v in quali_pace(q).items():
            t = canon.team_for(year, r, d)
            if t:
                obs.append((r, d, t, v["pace"], v["se"]))
    return obs


# ===================================================================== state-space fit

def _design(obs: list[tuple], team_round: bool = False):
    """Design matrix over [car states (team-major, round-minor) | driver effects | team-round terms]."""
    rounds = sorted({o[0] for o in obs})
    teams = sorted({o[2] for o in obs})
    drivers = sorted({o[1] for o in obs})
    K, T, D = len(rounds), len(teams), len(drivers)
    ri = {r: k for k, r in enumerate(rounds)}
    ti = {t: j for j, t in enumerate(teams)}
    di = {d: j for j, d in enumerate(drivers)}
    pairs = sorted({(o[2], o[0]) for o in obs}) if team_round else []
    pi = {pr: j for j, pr in enumerate(pairs)}
    n = len(obs)
    X = np.zeros((n, T * K + D + len(pairs)))
    for m, (r, d, t, _y, _se) in enumerate(obs):
        X[m, ti[t] * K + ri[r]] = 1.0
        X[m, T * K + di[d]] = 1.0
        if team_round:
            X[m, T * K + D + pi[(t, r)]] = 1.0
    y = np.array([o[3] for o in obs], float)
    se = np.array([o[4] for o in obs], float)
    return rounds, teams, drivers, X, y, se


def _prior_precision(rounds: list[int], T: int, D: int, q: float, sd: float, M: int = 0, kappa: float = 1.0) -> np.ndarray:
    K = len(rounds)
    P = np.zeros((T * K + D + M, T * K + D + M))
    for j in range(T):
        b = j * K
        P[b, b] += 1.0 / CAR0_SD ** 2
        for k in range(1, K):
            w = 1.0 / (q ** 2 * max(1, rounds[k] - rounds[k - 1]))
            P[b + k, b + k] += w
            P[b + k - 1, b + k - 1] += w
            P[b + k, b + k - 1] -= w
            P[b + k - 1, b + k] -= w
    P[T * K:T * K + D, T * K:T * K + D] += np.eye(D) / sd ** 2
    if M:
        P[T * K + D:, T * K + D:] += np.eye(M) / kappa ** 2
    return P


def _neg_log_post(theta: np.ndarray, X, y, se, rounds, T, D, prior: dict, M: int = 0) -> float:
    # Marginal likelihood of y ~ N(0, R + X P^-1 X') in precision form (determinant lemma):
    #   log|S| = log|R| + log|Q| - log|P|,  y'S^-1 y = y'R^-1 y - b'Q^-1 b,  Q = P + X'R^-1 X, b = X'R^-1 y.
    # |P| is analytic: each car chain has independent increments, so log|P_team| = -(log V0 + sum log v_k).
    q, sd, tau = np.exp(theta[:3])
    kappa = float(np.exp(theta[3])) if M else 1.0
    P = _prior_precision(rounds, T, D, q, sd, M, kappa)
    r = se ** 2 + tau ** 2
    Q = P + X.T @ (X / r[:, None])
    b = X.T @ (y / r)
    try:
        L = np.linalg.cholesky(Q)
    except np.linalg.LinAlgError:
        return 1e12
    z = solve_triangular(L, b, lower=True)
    steps = [max(1, rounds[k] - rounds[k - 1]) for k in range(1, len(rounds))]
    logdet_p = -T * (math.log(CAR0_SD ** 2) + sum(math.log(q ** 2 * s) for s in steps)) - D * math.log(sd ** 2) - M * math.log(kappa ** 2)
    logdet_s = float(np.sum(np.log(r))) + 2.0 * float(np.sum(np.log(np.diag(L)))) - logdet_p
    quad = float(np.sum(y ** 2 / r)) - float(z @ z)
    ll = -0.5 * quad - 0.5 * logdet_s
    lp = sum(-0.5 * ((th - math.log(prior[k])) / HYPER_PRIOR_LOGSD) ** 2 for th, k in zip(theta, ("q", "sd", "tau", "kappa")))
    return -(ll + lp)


def fit_effects(obs: list[tuple], kind: str = "race", hyper: dict | None = None) -> dict[str, Any]:
    """Posterior car random walk and driver effects from [(round, driver, team, y, se)].

    `hyper` = {"q", "sd", "tau"(, "kappa")} fixes the hyperparameters; otherwise they are fitted
    (marginal likelihood + weak log-normal hyperprior). ``TEAM_ROUND_NOISE`` adds the team-round term u.
    """
    if len(obs) < 4:
        return {"car": {}, "driver": {}, "params": {}, "reason": "fewer than 4 observations"}
    tr = bool(TEAM_ROUND_NOISE)
    rounds, teams, drivers, X, y, se = _design(obs, tr)
    T, D, K = len(teams), len(drivers), len(rounds)
    M = X.shape[1] - T * K - D
    prior = HYPER_PRIOR.get(kind, HYPER_PRIOR["race"])
    kappa = prior["kappa"]
    if hyper is None:
        names = ("q", "sd", "tau", "kappa")[: 4 if M else 3]
        th0 = np.log([prior[k] for k in names])
        bounds = [(math.log(0.005), math.log(2.0))] + [(math.log(0.005), math.log(3.0))] * (len(names) - 1)
        qf = Q_FIXED.get(kind)
        if qf:
            th0[0] = math.log(qf)
            bounds[0] = (math.log(qf), math.log(qf))
        try:
            res = minimize(_neg_log_post, th0, args=(X, y, se, rounds, T, D, prior, M), method="L-BFGS-B", bounds=bounds)
            vals = np.exp(res.x)
            q, sd, tau = vals[:3]
            kappa = float(vals[3]) if M else kappa
        except Exception:                                        # pragma: no cover - defensive
            q, sd, tau = prior["q"], prior["sd"], prior["tau"]
    else:
        q, sd, tau = hyper["q"], hyper["sd"], hyper["tau"]
        kappa = hyper.get("kappa", kappa)
    P = _prior_precision(rounds, T, D, q, sd, M, kappa)
    Rinv = 1.0 / (se ** 2 + tau ** 2)
    Q = P + X.T @ (X * Rinv[:, None])
    cov = np.linalg.inv(Q)
    mean = cov @ (X.T @ (Rinv * y))
    sdv = np.sqrt(np.clip(np.diag(cov), 0, None))
    car: dict[str, list[dict]] = {}
    present = defaultdict(set)
    for (r, _d, t, _y, _s) in obs:
        present[t].add(r)
    for j, t in enumerate(teams):
        car[t] = [{"round": r, "effect": round(float(mean[j * K + k]), 4), "se": round(float(sdv[j * K + k]), 4),
                   "observed": r in present[t]} for k, r in enumerate(rounds)]
    races = Counter(o[1] for o in obs)
    driver = {d: {"effect": round(float(mean[T * K + j]), 4), "se": round(float(sdv[T * K + j]), 4), "races": races[d]}
              for j, d in enumerate(drivers)}
    return {"car": car, "driver": driver,
            "params": {"q": round(float(q), 4), "driver_sd": round(float(sd), 4), "tau": round(float(tau), 4),
                       "kappa": round(float(kappa), 4) if M else None,
                       "rounds": rounds, "unit": "% of lap time vs field (negative = faster)"}}


# ===================================================================== public

def season_effects(year: int, upto_round: int | None = None) -> dict[str, Any]:
    """Car (random walk by round) and driver (season) effects, for race and qualifying pace.

    Returns {"car": {constructorId: [{"round","effect","se","observed"}]}, "driver": {driverId:
    {"effect","se","races"}}, "quali_car": ..., "quali_driver": ..., "params": {"race": .., "quali": ..}}
    in % of lap time vs the field average (negative = faster). Never raises.
    """
    out: dict[str, Any] = {"car": {}, "driver": {}, "quali_car": {}, "quali_driver": {}, "params": {}, "reasons": {}}
    try:
        ro = race_observations(year, upto_round)
    except Exception as exc:                                     # pragma: no cover - defensive
        ro, out["reasons"]["race"] = [], f"race observations failed: {exc}"
    try:
        qo = quali_observations(year, upto_round)
    except Exception as exc:                                     # pragma: no cover - defensive
        qo, out["reasons"]["quali"] = [], f"quali observations failed: {exc}"
    fr = fit_effects(ro, "race")
    fq = fit_effects(qo, "quali")
    out["car"], out["driver"], out["params"]["race"] = fr["car"], fr["driver"], fr["params"]
    out["quali_car"], out["quali_driver"], out["params"]["quali"] = fq["car"], fq["driver"], fq["params"]
    if fr.get("reason"):
        out["reasons"].setdefault("race", fr["reason"] if ro else "no race pace on disk for this season")
    if fq.get("reason"):
        out["reasons"].setdefault("quali", fq["reason"] if qo else "no qualifying times on disk for this season")
    return out


def _points_table(year: int) -> list[float]:
    by_pos: dict[int, Counter] = defaultdict(Counter)
    for r in canon.completed_rounds(year):
        for row in canon.race(year, r).get("results") or []:
            try:
                by_pos[int(row["position"])][float(row.get("points") or 0)] += 1
            except (KeyError, TypeError, ValueError):
                continue
    if not by_pos:
        return [float(x) for x in STANDARD_POINTS]
    n = max(by_pos)
    return [by_pos[p].most_common(1)[0][0] if by_pos.get(p) else 0.0 for p in range(1, n + 1)]


def car_driver_split(year: int, n_sims: int = 4000, seed: int = 7) -> dict[str, Any]:
    """Per team: how much of its points the car explains versus the drivers.

    Method (Shapley decomposition on model-expected points): at every completed round
    each driver's score is car_{t,r} + drv_i (race effects; the car state is taken from
    the nearest modelled round at or before r, qualifying effects if there is no race
    pace), plus N(0, tau^2) race noise; finishing orders are simulated and scored with
    the season's points table. For each team four worlds are simulated with common random
    numbers: (its car, its drivers), (average car, its drivers), (its car, average
    drivers), (average car, average drivers), where "average" = effect 0 and every
    other team is unchanged. Car contribution = mean of the two marginal gains of
    switching the car on; driver contribution likewise; they sum to model points minus
    the average-team baseline. car_share = car / (|car| + |drivers|).
    """
    eff = season_effects(year)
    car, drv, params = eff["car"], eff["driver"], eff["params"].get("race") or {}
    source = "race"
    if not car:
        car, drv, params, source = eff["quali_car"], eff["quali_driver"], eff["params"].get("quali") or {}, "quali"
    if not car:
        return {"teams": {}, "reason": "no effects for this season"}
    tau = float(params.get("tau") or 0.3)
    pts = np.array(_points_table(year), float)
    rng = np.random.default_rng(seed)
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def car_at(t: str, r: int) -> float:
        states = car.get(t) or []
        prev = [s for s in states if s["round"] <= r]
        s = prev[-1] if prev else (states[0] if states else None)
        return float(s["effect"]) if s else 0.0

    for r in canon.completed_rounds(year):
        res = canon.race(year, r).get("results") or []
        lineup = [(row["driver"], row["constructor"]) for row in res if row.get("driver") and row.get("constructor")]
        if len(lineup) < 2:
            continue
        for row in res:
            acc[row["constructor"]]["points"] += float(row.get("points") or 0)
        n = len(lineup)
        c = np.array([car_at(t, r) for _, t in lineup])
        dv = np.array([float((drv.get(d) or {}).get("effect", 0.0)) for d, _ in lineup])
        noise = rng.normal(0.0, tau, size=(n_sims, n))
        table = np.zeros(n)
        table[: min(n, len(pts))] = pts[: min(n, len(pts))]
        for t in sorted({t for _, t in lineup}):
            mine = np.array([tt == t for _, tt in lineup])
            e = {}
            for car_on in (0, 1):
                for drv_on in (0, 1):
                    s = c + dv
                    s[mine] = car_on * c[mine] + drv_on * dv[mine]
                    order = np.argsort(s[None, :] + noise, axis=1)
                    ranks = np.argsort(order, axis=1)
                    e[(car_on, drv_on)] = float(table[ranks][:, mine].sum(axis=1).mean())
            a = acc[t]
            a["model_points"] += e[(1, 1)]
            a["baseline"] += e[(0, 0)]
            a["car"] += 0.5 * ((e[(1, 1)] - e[(0, 1)]) + (e[(1, 0)] - e[(0, 0)]))
            a["drivers"] += 0.5 * ((e[(1, 1)] - e[(1, 0)]) + (e[(0, 1)] - e[(0, 0)]))
    teams = {}
    for t, a in acc.items():
        denom = abs(a["car"]) + abs(a["drivers"])
        teams[t] = {k: round(float(a[k]), 2) for k in ("points", "model_points", "baseline", "car", "drivers")}
        teams[t]["car_share"] = round(float(abs(a["car"]) / denom), 3) if denom > 0 else None
    return {"teams": teams, "source": source, "method": "Shapley on simulated expected points (see docstring)"}
