"""
How a club's season odds move with its strength: per-club sensitivity curves.

The transfer simulator (`#/transfer`) asks "if this club were this much stronger
for the rest of the season, what would its title, European and relegation odds
be?". Guessing that in the browser would be wrong, so the build re-runs the
competition's own season simulator with one club's rating shifted, at a few
shifts, and publishes the curve; the page interpolates.

A shift `delta` is in log goal-rate units, split evenly between attack and
defence: the club's expected goals are multiplied by exp(delta / 2) and its
opponents' by exp(-delta / 2) in every remaining match. On the score matrix that
is an exponential tilt, M'[i, j] ∝ M[i, j] · a^i · b^j (exact for independent
Poisson goals, a close approximation for the Dixon-Coles and Elo blend), so no
model refit is needed and every other pairing keeps its prediction exactly.

Common random numbers: every run uses the same seed, so the difference between a
shifted run and the unshifted one is far less noisy than either run's level. The
page therefore applies differences, base + (curve(delta) - curve(0)), to the
probabilities published by the main 30,000-run simulation.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import replace
from typing import Any, Callable

import numpy as np

from oddsmarkets.sports.world_cup.models.dixon_coles import MatchProbabilities

logger = logging.getLogger(__name__)

# Log goal-rate shifts. 0.15 is about a quarter of a goal of expected goal
# difference per match for a mid-table side (lambda ~1.4 each way).
SHIFTS = (-0.3, -0.15, 0.0, 0.15, 0.3)
SENS_SIMS = 2000


def _wdl(m: np.ndarray) -> tuple[float, float, float]:
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def tilt_matrix(matrix: np.ndarray, home_factor: float, away_factor: float) -> np.ndarray:
    """Score matrix with the home side's goals tilted by `home_factor` and the away side's by `away_factor`."""
    m = np.maximum(np.asarray(matrix, dtype=np.float64), 0.0)
    k = m.shape[0]
    i = np.arange(k, dtype=np.float64)
    out = m * np.outer(home_factor ** i, away_factor ** i)
    s = out.sum()
    return out / s if s > 0 and np.isfinite(s) else m


class CachedModel:
    """Memoises a model's predictions so repeated simulator runs never call the model twice."""

    def __init__(self, model) -> None:
        self.model = model
        self.cache: dict[tuple, Any] = {}

    def predict(self, home: str, away: str, neutral: bool = False, max_goals: int = 8, **kw):
        key = (home, away, bool(neutral), max_goals)
        hit = self.cache.get(key)
        if hit is None:
            hit = self.cache[key] = self.model.predict(home, away, neutral=neutral, max_goals=max_goals, **kw)
        return hit


class TiltedModel:
    """One club made stronger (delta > 0) or weaker (delta < 0) in every match it plays."""

    def __init__(self, base: CachedModel, team: str, delta: float) -> None:
        self.base = base
        self.team = team
        self.delta = float(delta)
        self.up = math.exp(self.delta / 2.0)
        self.down = math.exp(-self.delta / 2.0)

    def predict(self, home: str, away: str, neutral: bool = False, max_goals: int = 8, **kw):
        p = self.base.predict(home, away, neutral=neutral, max_goals=max_goals, **kw)
        if self.delta == 0.0 or self.team not in (home, away):
            return p
        hf, af = (self.up, self.down) if home == self.team else (self.down, self.up)
        m0 = np.asarray(p.score_matrix, dtype=np.float64)
        m1 = tilt_matrix(m0, hf, af)
        w0, w1 = _wdl(m0 / m0.sum() if m0.sum() > 0 else m0), _wdl(m1)
        # The ensemble's H/D/A differ slightly from its matrix's (MODELS.md 4.3): move them by the matrix's change.
        hw = min(max(p.home_win + (w1[0] - w0[0]), 0.0), 1.0)
        dr = min(max(p.draw + (w1[1] - w0[1]), 0.0), 1.0)
        aw = min(max(p.away_win + (w1[2] - w0[2]), 0.0), 1.0)
        tot = hw + dr + aw or 1.0
        return MatchProbabilities(home_win=hw / tot, draw=dr / tot, away_win=aw / tot,
                                  lambda_home=p.lambda_home * hf, lambda_away=p.lambda_away * af, score_matrix=m1)


def gd_per_delta(base: CachedModel, team: str, fixtures: list[tuple[str, str, bool]], eps: float = 0.02) -> float | None:
    """Expected goal difference per match gained per unit of shift, over the club's remaining fixtures."""
    tilted = TiltedModel(base, team, eps)
    diffs = []
    for home, away, neutral in fixtures:
        if team not in (home, away):
            continue
        m0 = np.asarray(base.predict(home, away, neutral=neutral).score_matrix, dtype=np.float64)
        m0 = m0 / m0.sum() if m0.sum() > 0 else m0
        m1 = np.asarray(tilted.predict(home, away, neutral=neutral).score_matrix, dtype=np.float64)
        k = m0.shape[0]
        gd = np.subtract.outer(np.arange(k), np.arange(k)).astype(np.float64)
        sign = 1.0 if home == team else -1.0
        diffs.append(sign * float(((m1 - m0) * gd).sum()) / eps)
    return round(float(np.mean(diffs)), 4) if diffs else None


def run_sensitivity(teams: list[str], run_once: Callable[[Any], dict[str, dict[str, float]]], base: CachedModel,
                    shifts: tuple[float, ...] = SHIFTS, budget_s: float | None = None) -> dict[str, dict[str, list[float]]]:
    """
    `run_once(model)` runs the season simulator with `model` and returns
    {team: {metric: value}}. Returns {team: {metric: [value at each shift]}}.
    The unshifted run is shared by every club. A time budget stops early (the
    clubs not reached are left out, never half-filled).
    """
    t0 = time.perf_counter()
    sim_log = logging.getLogger("oddsmarkets.football.competitions")
    level = sim_log.level
    sim_log.setLevel(logging.WARNING)
    try:
        zero = run_once(base)
        out: dict[str, dict[str, list[float]]] = {}
        for team in teams:
            if budget_s is not None and time.perf_counter() - t0 > budget_s:
                logger.warning("sensitivity: time budget reached after %d of %d clubs", len(out), len(teams))
                break
            curve: dict[str, list[float]] = {}
            for d in shifts:
                res = zero if d == 0.0 else run_once(TiltedModel(base, team, d))
                for metric, v in (res.get(team) or {}).items():
                    curve.setdefault(metric, []).append(round(float(v), 4))
            if curve and all(len(v) == len(shifts) for v in curve.values()):
                out[team] = curve
        return out
    finally:
        sim_log.setLevel(level)


def league_metrics(results, cfg) -> dict[str, dict[str, float]]:
    """The per-club numbers the transfer simulator reads from a LeagueResults."""
    out: dict[str, dict[str, float]] = {}
    for t in results.teams:
        row = {"exp_pts": results.expected_points.get(t, 0.0), "p_title": results.p_title.get(t, 0.0)}
        for band in cfg.bands:
            row["band:" + band.key] = results.p_in_band(band.key, t)
        if results.p_playoffs:
            row["p_playoffs"] = results.p_playoffs.get(t, 0.0)
        if results.p_cup:
            row["p_cup"] = results.p_cup.get(t, 0.0)
        out[t] = row
    return out


def league_sensitivity(model, state, cfg, n_sims: int = SENS_SIMS, seed: int = 20261015,
                       shifts: tuple[float, ...] = SHIFTS, budget_s: float | None = 120.0) -> dict:
    """Sensitivity curves for every club of a league (LeagueSimulator)."""
    from oddsmarkets.football.competitions.league.simulator import LeagueSimulator

    t0 = time.perf_counter()
    small = replace(cfg, n_sims=n_sims, sim_chunk=n_sims)
    base = CachedModel(model)

    def run_once(m):
        res = LeagueSimulator(m, state, cfg=small, n_sims=n_sims, seed=seed, chunk=n_sims).run()
        return league_metrics(res, small)

    teams = list(state.teams)
    curves = run_sensitivity(teams, run_once, base, shifts, budget_s)
    fixtures = [(m.home_team, m.away_team, False) for m in state.remaining if not getattr(m, "is_playoff", False)]
    bands = [{"key": "band:" + b.key, "label": b.label, "kind": b.kind} for b in cfg.bands]
    payload = {
        "shifts": list(shifts), "n_sims": n_sims, "seed": seed, "remaining": len(fixtures),
        "metrics": ["exp_pts", "p_title"] + [b["key"] for b in bands] +
                   (["p_playoffs"] if any("p_playoffs" in c for c in curves.values()) else []) +
                   (["p_cup"] if any("p_cup" in c for c in curves.values()) else []),
        "bands": bands,
        "teams": {t: {"gd_per_delta": gd_per_delta(base, t, fixtures),
                      "remaining": sum(1 for h, a, _ in fixtures if t in (h, a)), **c} for t, c in curves.items()},
        "runtime_s": round(time.perf_counter() - t0, 1),
    }
    return payload


def liga_sensitivity(model, state, cfg, n_sims: int = SENS_SIMS, seed: int = 20261015,
                     shifts: tuple[float, ...] = SHIFTS, budget_s: float | None = 120.0) -> dict:
    """Sensitivity curves for the Argentine Liga Profesional (LigaSimulator)."""
    from oddsmarkets.football.competitions.liga.simulator import LigaSimulator

    t0 = time.perf_counter()
    small = replace(cfg, n_sims=n_sims, sim_chunk=n_sims)
    base = CachedModel(model)

    def run_once(m):
        r = LigaSimulator(m, state, cfg=small, n_sims=n_sims, seed=seed, chunk=n_sims).run()
        return {t: {"exp_pts": r.expected_points.get(t, 0.0), "p_title": r.p_title.get(t, 0.0),
                    "band:libertadores": r.p_libertadores.get(t, 0.0), "band:sudamericana": r.p_sudamericana.get(t, 0.0),
                    "band:relegation": r.p_relegation_any.get(t, 0.0)} for t in r.teams}

    teams = list(state.teams)
    curves = run_sensitivity(teams, run_once, base, shifts, budget_s)
    torneo = state.live_torneo() if hasattr(state, "live_torneo") else None
    fixtures = [(m.home_team, m.away_team, False) for m in (getattr(torneo, "remaining", None) or []) if not m.is_playoff]
    torneo = getattr(torneo, "key", None)
    bands = [{"key": "band:libertadores", "label": "Copa Libertadores", "kind": "up"},
             {"key": "band:sudamericana", "label": "Copa Sudamericana", "kind": "up"},
             {"key": "band:relegation", "label": "Relegation", "kind": "down"}]
    return {
        "shifts": list(shifts), "n_sims": n_sims, "seed": seed, "remaining": len(fixtures), "torneo": torneo,
        "metrics": ["exp_pts", "p_title"] + [b["key"] for b in bands], "bands": bands,
        "teams": {t: {"gd_per_delta": gd_per_delta(base, t, fixtures),
                      "remaining": sum(1 for h, a, _ in fixtures if t in (h, a)), **c} for t, c in curves.items()},
        "runtime_s": round(time.perf_counter() - t0, 1),
    }
