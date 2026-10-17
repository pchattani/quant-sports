"""
Simulation primitives shared across competitions.

These are the pieces of a vectorized season simulator that do not depend on the
competition's shape: turning a model's score matrix into something cheap to sample
from, the probability that one side survives a single-leg knockout tie, and ranking
a (n_sims, n_teams) table by an ordered list of tiebreak keys.

Everything above this level — what the table means, who qualifies for what, how a
bracket is drawn — belongs to the competition package. The Argentine simulator
predates this module and still carries private copies of the first two; they can be
pointed here when it is next touched.
"""
from __future__ import annotations

import math
from typing import Callable

import numpy as np


class ScoreSampler:
    """
    Cached cumulative score distributions per ordered pairing.

    The same pairing is sampled once per simulation, and the model call is far more
    expensive than the sampling, so each (home, away, neutral) triple is asked of the
    model exactly once.
    """

    def __init__(self, model, teams: list[str], max_goals: int = 8) -> None:
        self.model = model
        self.teams = teams
        self.max_goals = max_goals
        self._cdf: dict[tuple[int, int, bool], np.ndarray] = {}

    @property
    def k(self) -> int:
        return self.max_goals + 1

    def cdf(self, home: int, away: int, neutral: bool = False) -> np.ndarray:
        key = (home, away, neutral)
        cached = self._cdf.get(key)
        if cached is not None:
            return cached
        probs = self.model.predict(
            self.teams[home], self.teams[away], neutral=neutral, max_goals=self.max_goals,
        )
        matrix = np.maximum(np.asarray(probs.score_matrix, dtype=np.float64), 0.0)
        total = matrix.sum()
        if total <= 0 or not np.isfinite(total):
            # Degenerate fit: independent Poisson at a league-average rate.
            lam = 1.2
            pmf = np.exp(-lam) * lam ** np.arange(self.k) / np.array(
                [float(math.factorial(i)) for i in range(self.k)]
            )
            matrix = np.outer(pmf, pmf)
            total = matrix.sum()
        cdf = np.cumsum((matrix / total).ravel())
        cdf[-1] = 1.0
        self._cdf[key] = cdf
        return cdf

    def sample(self, home: int, away: int, rng: np.random.Generator, n: int,
               neutral: bool = False) -> tuple[np.ndarray, np.ndarray]:
        """(home_goals, away_goals) for `n` simulations of one fixture."""
        cdf = self.cdf(home, away, neutral)
        idx = np.searchsorted(cdf, rng.random(n), side="right")
        np.clip(idx, 0, cdf.size - 1, out=idx)
        hg, ag = np.divmod(idx, self.k)
        return hg.astype(np.int32), ag.astype(np.int32)


def advance_matrix(model, teams: list[str], extra_time_weight: float = 0.5,
                   max_goals: int = 8) -> np.ndarray:
    """
    P(home side advances) for every ordered pairing in a single-leg tie.

    A drawn tie goes to extra time and then a shootout. Extra time favours the
    stronger side, so the drawn mass is split between a strength-weighted phase and
    an even shootout rather than being handed to a coin flip.
    """
    n = len(teams)
    out = np.full((n, n), 0.5, dtype=np.float64)
    for h in range(n):
        for a in range(n):
            if h == a:
                continue
            probs = model.predict(teams[h], teams[a], neutral=False, max_goals=max_goals)
            hw, dr, aw = probs.home_win, probs.draw, probs.away_win
            decisive = hw + aw
            share = (hw / decisive) if decisive > 0 else 0.5
            out[h, a] = hw + dr * (extra_time_weight * share + (1.0 - extra_time_weight) * 0.5)
    return out


def _goal_difference_pmf(matrix: np.ndarray) -> np.ndarray:
    """PMF of (home goals - away goals) from a score matrix, indexed from -k+1 to k-1."""
    k = matrix.shape[0]
    out = np.zeros(2 * k - 1)
    for i in range(k):
        for j in range(k):
            out[i - j + k - 1] += matrix[i, j]
    return out


def two_leg_advance_matrix(model, teams: list[str], extra_time_weight: float = 0.5,
                           max_goals: int = 8) -> np.ndarray:
    """
    P(a advances) for every ordered pairing (a, b) of a two-legged tie in which
    **b hosts the second leg** — the convention for a seeded tie, where the better
    seed plays the return at home. Index as out[a, b].

    Aggregate goals decide it (no away-goals rule, as in UEFA since 2021 and
    CONMEBOL since 2022). A level aggregate goes to extra time and a shootout,
    split as for a single-leg tie: the stronger side's share of decisive results
    weighted by `extra_time_weight`, the rest a coin flip.
    """
    n = len(teams)
    k = max_goals + 1
    out = np.full((n, n), 0.5, dtype=np.float64)
    pmf_cache: dict[tuple[int, int], np.ndarray] = {}

    def gd_pmf(home: int, away: int) -> np.ndarray:
        key = (home, away)
        if key not in pmf_cache:
            probs = model.predict(teams[home], teams[away], neutral=False, max_goals=max_goals)
            m = np.maximum(np.asarray(probs.score_matrix, dtype=np.float64), 0.0)
            m = m / m.sum() if m.sum() > 0 else np.full((k, k), 1.0 / (k * k))
            pmf_cache[key] = _goal_difference_pmf(m)
        return pmf_cache[key]

    for a in range(n):
        for b in range(n):
            if a == b:
                continue
            leg1 = gd_pmf(a, b)             # a at home: +ve favours a
            leg2 = gd_pmf(b, a)[::-1]       # b at home, flipped so +ve favours a
            total = np.convolve(leg1, leg2)  # aggregate GD for a, centred at index 2k-2
            centre = 2 * k - 2
            p_win = total[centre + 1:].sum()
            p_level = total[centre]
            p_lose = total[:centre].sum()
            decisive = p_win + p_lose
            share = (p_win / decisive) if decisive > 0 else 0.5
            out[a, b] = p_win + p_level * (extra_time_weight * share + (1.0 - extra_time_weight) * 0.5)
    return out


class PairSampler:
    """
    Score sampling for fixtures whose teams differ per simulation.

    `ScoreSampler` serves fixtures fixed across simulations. Split-season groups
    and knockout legs are drawn per simulation, so the cumulative distributions
    are gathered per row: cdf_all[home_idx, away_idx] -> (S, k*k), inverted with
    one comparison per row rather than a searchsorted.
    """

    def __init__(self, sampler: ScoreSampler) -> None:
        self.sampler = sampler
        self.k = sampler.k
        n = len(sampler.teams)
        self._all: np.ndarray | None = None
        self._n = n

    def _table(self) -> np.ndarray:
        if self._all is None:
            n, kk = self._n, self.k * self.k
            table = np.zeros((n, n, kk))
            for h in range(n):
                for a in range(n):
                    if h != a:
                        table[h, a] = self.sampler.cdf(h, a, neutral=False)
                    else:
                        table[h, a] = np.linspace(1.0 / kk, 1.0, kk)
            self._all = table
        return self._all

    def sample(self, home: np.ndarray, away: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
        """(home_goals, away_goals) per simulation for per-simulation pairings."""
        cdf = self._table()[home, away]                       # (S, k*k)
        idx = (rng.random(home.shape[0])[:, None] > cdf).sum(axis=1)
        np.clip(idx, 0, cdf.shape[1] - 1, out=idx)
        hg, ag = np.divmod(idx, self.k)
        return hg.astype(np.int32), ag.astype(np.int32)


def rank_table(keys: list[np.ndarray], rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """
    Rank a (S, T) table by ordered tiebreak keys, most important first.

    Returns (order, rank): `order[s, i]` is the team index in position i (0 = first),
    `rank[s, t]` is team t's position. Remaining ties are broken by random jitter —
    the honest representation of a drawn lot, and one that does not hand a
    systematic edge to clubs early in the alphabet.
    """
    S, T = keys[0].shape
    jitter = rng.random((S, T))
    # lexsort sorts by the last key first, ascending; we want descending on every
    # key with the most important applied last.
    order = np.lexsort(tuple([jitter] + list(reversed(keys))), axis=-1)[:, ::-1]
    rank = np.empty_like(order)
    np.put_along_axis(rank, order, np.broadcast_to(np.arange(T), order.shape), axis=-1)
    return order, rank


def count_positions(order: np.ndarray, n_teams: int) -> np.ndarray:
    """(n_teams, n_positions) counts of how often each team finished in each slot."""
    S, P = order.shape
    counts = np.zeros((n_teams, P), dtype=np.int64)
    np.add.at(counts, (order, np.broadcast_to(np.arange(P), order.shape)), 1)
    return counts


def ensure_callable(fn: Callable | None, default: Callable) -> Callable:
    return fn if fn is not None else default
