"""
Line arithmetic for CLV: selection probabilities at one line implied by prices at another.

A spread or total moves between the decision and the close, so the closing price of "home -3" says nothing directly
about "home -3.5". The close is turned into a market distribution (margin: the game model's discrete distribution
with key numbers, sd sigma_m; total: integers with total key multipliers, sd sigma_t), centred so that it reproduces
the de-vigged closing probability at the closing line, and that distribution prices the decision's line.
Probabilities of spread / total selections are conditional on no push throughout (a push refunds the stake), so
EV per unit = (1 - P(push)) (p d - 1) and the sign of p d - 1 decides a bet.
"""
from __future__ import annotations

import numpy as np
from scipy.special import ndtr

from oddsmarkets.nfl.models import game as GM

MU_GRID = np.arange(-35.0, 35.0001, 0.05)
TOT_SUPPORT = np.arange(0, 141)
TMU_GRID = np.arange(20.0, 80.0001, 0.05)


def _margin_table(sigma: float, kk: np.ndarray) -> np.ndarray:
    return GM.margin_pmf(MU_GRID, sigma, kk)                      # (len grid, 161)


def cover_home(P: np.ndarray, spread_home: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """P(home covers | no push) and P(push) for each pmf row of P (rows aligned with spread_home)."""
    adj = GM.SUPPORT[None, :] + np.asarray(spread_home, float)[:, None]
    win = (P * (adj > 1e-9)).sum(1)
    push = (P * (np.abs(adj) < 1e-9)).sum(1)
    lose = 1.0 - win - push
    return win / np.maximum(win + lose, 1e-12), push


def total_pmf(mu, sigma: float, tk: np.ndarray | None = None) -> np.ndarray:
    mu = np.atleast_1d(np.asarray(mu, float))[:, None]
    P = ndtr((TOT_SUPPORT[None, :] + 0.5 - mu) / sigma) - ndtr((TOT_SUPPORT[None, :] - 0.5 - mu) / sigma)
    if tk is not None:
        P = P * tk[None, :]
    return P / P.sum(1, keepdims=True)


def over_prob(P: np.ndarray, line: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    adj = TOT_SUPPORT[None, :] - np.asarray(line, float)[:, None]
    win = (P * (adj > 1e-9)).sum(1)
    push = (P * (np.abs(adj) < 1e-9)).sum(1)
    lose = 1.0 - win - push
    return win / np.maximum(win + lose, 1e-12), push


def fit_total_keys(mu: np.ndarray, y: np.ndarray, sigma: float, iters: int = 3) -> np.ndarray:
    """Total key multipliers k(t), t = 0..140, observed / expected (clipped 0.3-3, smoothed outside 20-75)."""
    tk = np.ones(len(TOT_SUPPORT))
    obs = np.bincount(np.clip(np.round(y).astype(int), 0, len(TOT_SUPPORT) - 1), minlength=len(TOT_SUPPORT)).astype(float)
    for _ in range(iters):
        exp = np.zeros(len(TOT_SUPPORT))
        for ch in np.array_split(np.arange(len(mu)), max(1, len(mu) // 3000)):
            exp += total_pmf(mu[ch], sigma, tk).sum(0)
        ratio = np.where(exp > 5, obs / np.maximum(exp, 1e-9), 1.0)
        tk = np.clip(tk * ratio, 0.3, 3.0)
    return tk


class LineMap:
    """Implied probabilities across lines from a market distribution fitted to one (line, probability)."""

    def __init__(self, sigma_m: float, kk: np.ndarray, sigma_t: float, tk: np.ndarray | None):
        self.Pm = _margin_table(sigma_m, kk)
        self.Pt = total_pmf(TMU_GRID, sigma_t, tk)

    def spread_at(self, line_from, p_from, line_to):
        """P(home covers line_to | no push), P(push at line_to) given P(home covers line_from | no push) = p_from."""
        line_from, p_from, line_to = (np.atleast_1d(np.asarray(x, float)) for x in (line_from, p_from, line_to))
        out_p, out_push = np.full(len(line_from), np.nan), np.full(len(line_from), np.nan)
        for i in range(len(line_from)):
            if not (np.isfinite(line_from[i]) and np.isfinite(p_from[i]) and np.isfinite(line_to[i])):
                continue
            c, _ = cover_home(self.Pm, np.full(len(MU_GRID), line_from[i]))      # increasing in mu
            mu = np.interp(p_from[i], c, MU_GRID)
            j = int(np.clip(np.searchsorted(MU_GRID, mu), 1, len(MU_GRID) - 1))
            wgt = (mu - MU_GRID[j - 1]) / (MU_GRID[j] - MU_GRID[j - 1])
            row = (1 - wgt) * self.Pm[j - 1] + wgt * self.Pm[j]
            p, pu = cover_home(row[None, :], np.array([line_to[i]]))
            out_p[i], out_push[i] = p[0], pu[0]
        return out_p, out_push

    def total_at(self, line_from, p_from, line_to):
        line_from, p_from, line_to = (np.atleast_1d(np.asarray(x, float)) for x in (line_from, p_from, line_to))
        out_p, out_push = np.full(len(line_from), np.nan), np.full(len(line_from), np.nan)
        for i in range(len(line_from)):
            if not (np.isfinite(line_from[i]) and np.isfinite(p_from[i]) and np.isfinite(line_to[i])):
                continue
            c, _ = over_prob(self.Pt, np.full(len(TMU_GRID), line_from[i]))
            mu = np.interp(p_from[i], c, TMU_GRID)
            j = int(np.clip(np.searchsorted(TMU_GRID, mu), 1, len(TMU_GRID) - 1))
            wgt = (mu - TMU_GRID[j - 1]) / (TMU_GRID[j] - TMU_GRID[j - 1])
            row = (1 - wgt) * self.Pt[j - 1] + wgt * self.Pt[j]
            p, pu = over_prob(row[None, :], np.array([line_to[i]]))
            out_p[i], out_push[i] = p[0], pu[0]
        return out_p, out_push
