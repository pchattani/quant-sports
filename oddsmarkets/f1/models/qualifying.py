"""
Pre-qualifying forecast for one round, from the qualifying decomposition through the
previous round (no information from the session itself is used).

Model
-----
For driver i in team t at round R, qualifying pace in % of the lap (negative = faster):

    pace_i = car_t + drv_i + eps_i
    car_t  ~ N(car_{t,R'}, se_{t,R'}^2 + q^2 * (R - R') + kappa^2)   (random walk carried forward from the
                                                              last modelled round R' < R, plus this session's
                                                              team-specific swing kappa)
    drv_i  ~ N(drv_i_hat, se_i^2)
    eps_i  ~ N(0, tau^2)                                     (session noise: the residual sd of the fit)

car and drv come from season_effects(year, upto_round=R-1)["quali_car"/"quali_driver"],
with q and tau from the same fit. Team-mates share one car draw per simulation, so
their outcomes are correlated as they should be. A driver without a season effect
(debutant, substitute) gets drv ~ N(0, sigma_d^2); a team without one gets car ~ N(0, 1^2).
Round 1 carries the previous season's final states forward with an extra winter
variance of 1.0^2 (% of lap) on every car and 0.1^2 on every driver.

No circuit-type adjustment: the season store has no lap length, so average lap speed
(the natural way to class circuits) is not available for every season; car effects
are therefore assumed to carry across circuit types, and the random walk's q absorbs
the round-to-round circuit swings.

Practice (October 2026): when the weekend's practice sessions before qualifying are on disk (OpenF1, 2023
on), each driver's mean pace moves toward his practice one-lap pace (``models/practice.py``, best laps of
FP1-FP3 and sprint qualifying, field-centred): mean_i = (1 - w) mean_i + w (x_i + offset), w =
``PRACTICE_SHORT_W`` (fitted file; 0.5: best pole log-loss over all 2023-2026 data, tied with 0.25, and better
for the race winner; a strict walk-forward pick (0.25 each season) gives 2024-2026 pole log-loss 1.824 -> 1.628
against the same model without practice, 0.5 gives 1.584). Variances are unchanged. ``use_practice=False``
gives the pre-weekend forecast.

Monte Carlo: n_sims draws of every pace; the grid is the sorted order (qualifying
classification, before grid penalties). p_pole = P(rank 1); grid_dist[k] = P(rank k+1);
mu_gap_pct = mean gap to the fastest driver in the same draw.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from oddsmarkets.f1 import canon
from oddsmarkets.f1.models.decomposition import fit_effects, quali_observations

WINTER_CAR_SD = 1.0


def season_effects(year: int, upto_round: int | None = None) -> dict[str, Any]:
    """The qualifying half of decomposition.season_effects (same fit, without the race half)."""
    f = fit_effects(quali_observations(year, upto_round), "quali")
    return {"quali_car": f["car"], "quali_driver": f["driver"], "params": {"quali": f["params"]}}
WINTER_DRIVER_SD = 0.1
NEW_TEAM_SD = 1.0
PRACTICE_SHORT_W = 0.0       # set from models/fitted/race_params.json ("qualifying.PRACTICE_SHORT_W")


def _load_fitted() -> None:
    global PRACTICE_SHORT_W
    try:
        import json
        from pathlib import Path
        f = json.loads((Path(__file__).resolve().parent / "fitted" / "race_params.json").read_text(encoding="utf-8"))
        PRACTICE_SHORT_W = float((f.get("params") or {}).get("qualifying.PRACTICE_SHORT_W", PRACTICE_SHORT_W))
    except (OSError, ValueError, TypeError):
        pass


_load_fitted()


def practice_shift(year: int, rnd: int, field: dict[str, str], cars: dict, drivers: dict, driver_sd: float,
                   w: float | None = None) -> tuple[dict, dict | None]:
    """Driver states with means moved toward practice one-lap pace (see the module docstring); returns
    (drivers, info) and leaves them unchanged (info None) without practice data or with w = 0."""
    w = PRACTICE_SHORT_W if w is None else w
    if w <= 0:
        return drivers, None
    try:
        from oddsmarkets.f1.models import practice as _pr
        feats = _pr.practice_features(year, rnd)
    except Exception:                                            # pragma: no cover - defensive
        return drivers, None
    x = {d: float(e["short_pct"]) for d, e in (feats.get("drivers") or {}).items()
         if d in field and e.get("short_pct") is not None and math.isfinite(e["short_pct"])}
    if len(x) < max(5, len(field) // 2):
        return drivers, None
    mu = {d: float(cars.get(field[d], (0.0, NEW_TEAM_SD ** 2))[0]) + float(drivers.get(d, (0.0, driver_sd ** 2))[0]) for d in field}
    new = _pr.blend_pct(mu, x, w)
    out = dict(drivers)
    for d in field:
        m0, v0 = drivers.get(d, (0.0, driver_sd ** 2))
        out[d] = (m0 + new[d] - mu[d], v0)
    return out, {"w": w, "drivers": len(x), "sessions": [s_["name"] for s_ in feats.get("sessions") or []]}


def _states(year: int, rnd: int) -> tuple[dict, dict, dict, int | None, float]:
    """(car {team: (mean, var, last_round)}, driver {d: (mean, var)}, params, last_round, extra car var)."""
    eff = season_effects(year, upto_round=rnd - 1) if rnd > 1 else {"quali_car": {}}
    extra = 0.0
    if not eff.get("quali_car"):
        eff = season_effects(year - 1)
        extra = WINTER_CAR_SD ** 2
        if not eff.get("quali_car"):
            return {}, {}, {}, None, 0.0
        kappa = float((eff["params"].get("quali") or {}).get("kappa") or 0.0)
        cars = {t: (v[-1]["effect"], v[-1]["se"] ** 2 + extra + kappa ** 2, None) for t, v in eff["quali_car"].items() if v}
        drivers = {d: (v["effect"], v["se"] ** 2 + WINTER_DRIVER_SD ** 2) for d, v in eff["quali_driver"].items()}
        return cars, drivers, eff["params"].get("quali") or {}, None, extra
    params = eff["params"].get("quali") or {}
    q = float(params.get("q") or 0.1)
    kappa = float(params.get("kappa") or 0.0)          # this session's team-specific swing (shared by team-mates)
    cars = {}
    for t, v in eff["quali_car"].items():
        if v:
            last = v[-1]
            cars[t] = (last["effect"], last["se"] ** 2 + q ** 2 * max(1, rnd - int(last["round"])) + kappa ** 2, last["round"])
    drivers = {d: (v["effect"], v["se"] ** 2) for d, v in eff["quali_driver"].items()}
    return cars, drivers, params, max(int(v[-1]["round"]) for v in eff["quali_car"].values() if v), extra


def simulate_quali(field: dict[str, str], cars: dict[str, tuple], drivers: dict[str, tuple], tau: float,
                   driver_sd: float = 0.15, n_sims: int = 20000, seed: int = 11) -> dict[str, Any]:
    """Monte Carlo of one qualifying session. field = {driverId: constructorId};
    cars = {team: (mean, var, ...)}, drivers = {driverId: (mean, var)}; values in % of lap."""
    ds = sorted(field)
    n = len(ds)
    if n == 0:
        return {"drivers": {}, "reason": "empty field"}
    rng = np.random.default_rng(seed)
    teams = sorted(set(field.values()))
    tix = {t: k for k, t in enumerate(teams)}
    cm = np.array([cars.get(t, (0.0, NEW_TEAM_SD ** 2))[0] for t in teams])
    cs = np.sqrt([cars.get(t, (0.0, NEW_TEAM_SD ** 2))[1] for t in teams])
    dm = np.array([drivers.get(d, (0.0, driver_sd ** 2))[0] for d in ds])
    dsd = np.sqrt([drivers.get(d, (0.0, driver_sd ** 2))[1] for d in ds])
    car_draw = cm + cs * rng.standard_normal((n_sims, len(teams)))
    pace = car_draw[:, [tix[field[d]] for d in ds]] + dm + dsd * rng.standard_normal((n_sims, n)) + tau * rng.standard_normal((n_sims, n))
    ranks = np.argsort(np.argsort(pace, axis=1), axis=1)
    gaps = pace - pace.min(axis=1, keepdims=True)
    out = {}
    for j, d in enumerate(ds):
        dist = np.bincount(ranks[:, j], minlength=n) / n_sims
        tot_sd = math.sqrt(cs[tix[field[d]]] ** 2 + dsd[j] ** 2 + tau ** 2)
        out[d] = {"mu_gap_pct": round(float(gaps[:, j].mean()), 4), "sd": round(tot_sd, 4),
                  "p_pole": round(float(dist[0]), 5), "grid_dist": [round(float(p), 5) for p in dist],
                  "exp_grid": round(float(ranks[:, j].mean() + 1), 3), "team": field[d],
                  "mu_pace_pct": round(float(cm[tix[field[d]]] + dm[j]), 4)}
    return {"drivers": out}


def quali_model(year: int, round: int, n_sims: int = 20000, seed: int = 11,  # noqa: A002 - contract name
                use_practice: bool = True) -> dict[str, Any]:
    """Pre-qualifying forecast for (year, round): {"drivers": {driverId: {"mu_gap_pct", "sd",
    "p_pole", "grid_dist": [p(P1)..p(Pn)], "exp_grid"}}}. Never raises."""
    rnd = int(round)
    try:
        field = canon.lineup(year, rnd)
        if not field:
            return {"drivers": {}, "reason": "no entry list for this round or earlier rounds"}
        cars, drivers, params, last, extra = _states(year, rnd)
        tau = float(params.get("tau") or 0.15)
        dsd = float(params.get("driver_sd") or 0.15)
        prac = None
        if use_practice:
            drivers, prac = practice_shift(year, rnd, field, cars, drivers, dsd)
        out = simulate_quali(field, cars, drivers, tau, dsd, n_sims, seed)
        out["meta"] = {"effects_through_round": last, "tau": tau, "q": params.get("q"), "winter_carry": extra > 0,
                       "unit": "% of lap time", "practice": prac}
        if not cars:
            out["meta"]["reason"] = "no qualifying effects for this or the previous season: flat prior"
        return out
    except Exception as exc:                                     # pragma: no cover - defensive
        return {"drivers": {}, "reason": f"quali model failed: {exc}"}
