"""
A fast Dixon-Coles fit for walk-forward research (analytic gradient, warm starts).

Same parameterisation as the production `DixonColesModel`
(oddsmarkets/sports/world_cup/models/dixon_coles.py):

    lam_h = exp(att[h] + def[a] + home_adv),  lam_a = exp(att[a] + def[h])
    goals rows: Poisson x Poisson x tau(rho) (low-score correction)
    ridge * (sum (att - att_prior)^2 + sum (def - def_prior)^2), first team's def fixed at 0

and two extensions used by the experiments, both off by default:

* "rate rows": continuous-Poisson rows on any rate per side (production uses Sofascore
  xG here; the research uses a shots-based proxy or the market-implied goal rates of
  past matches). Unlike production, a match may contribute both its goals and its
  rates, each with its own weight.
* per-team prior means for the ridge (production: 0), used for promoted teams.

With rate rows off, priors at 0 and the same weights, the optimum equals production's
(tested in tests/test_football_research.py); only the optimiser is faster.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import poisson


@dataclass
class FitData:
    hi: np.ndarray            # home team index
    ai: np.ndarray            # away team index
    hg: np.ndarray            # goals (float, NaN = no goals row)
    ag: np.ndarray
    wg: np.ndarray            # weight of the goals likelihood per row
    rh: np.ndarray | None = None   # rate rows (NaN = none)
    ra: np.ndarray | None = None
    wr: np.ndarray | None = None
    hfa: np.ndarray | None = None  # 1.0 if home advantage applies (0 for neutral)


@dataclass
class DCParams:
    teams: list[str]
    att: np.ndarray
    dfn: np.ndarray
    home: float
    rho: float
    index: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.index = {t: i for i, t in enumerate(self.teams)}

    def lambdas(self, home: list[str], away: list[str], neutral: np.ndarray | None = None,
                att_default: float = 0.0, def_default: float = 0.0,
                prior: dict[str, tuple[float, float]] | None = None) -> tuple[np.ndarray, np.ndarray]:
        def get(names, arr, default, k):
            out = np.empty(len(names))
            for j, t in enumerate(names):
                i = self.index.get(t)
                if i is not None:
                    out[j] = arr[i]
                elif prior and t in prior:
                    out[j] = prior[t][k]
                else:
                    out[j] = default
            return out
        ah, dh = get(home, self.att, att_default, 0), get(home, self.dfn, def_default, 1)
        aa, da = get(away, self.att, att_default, 0), get(away, self.dfn, def_default, 1)
        ha = self.home * (1.0 - (neutral.astype(float) if neutral is not None else 0.0))
        return np.exp(ah + da + ha), np.exp(aa + dh)


def _tau(hg, ag, lh, la, rho):
    t = np.ones_like(lh)
    m00 = (hg == 0) & (ag == 0)
    m10 = (hg == 1) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m11 = (hg == 1) & (ag == 1)
    t[m00] = 1 - lh[m00] * la[m00] * rho
    t[m10] = 1 + la[m10] * rho
    t[m01] = 1 + lh[m01] * rho
    t[m11] = 1 - rho
    return t, m00, m10, m01, m11


def fit(data: FitData, n: int, ridge: float, *, att_prior: np.ndarray | None = None,
        def_prior: np.ndarray | None = None, x0: np.ndarray | None = None,
        fit_rho: bool = True, rho_bounds=(-0.99, 0.0), maxiter: int = 500,
        rho_fixed: float | None = None) -> np.ndarray:
    """Return the parameter vector [att(n), def(n), home, rho]. `rho_fixed` holds rho at that value."""
    if rho_fixed is not None:
        fit_rho = False
    hi, ai = data.hi, data.ai
    hfa = data.hfa if data.hfa is not None else np.ones(len(hi))
    g_ok = np.isfinite(data.hg) & np.isfinite(data.ag) & (data.wg > 0)
    hg = np.where(g_ok, data.hg, 0.0)
    ag = np.where(g_ok, data.ag, 0.0)
    wg = np.where(g_ok, data.wg, 0.0)
    if data.rh is not None:
        r_ok = np.isfinite(data.rh) & np.isfinite(data.ra) & (data.wr > 0)
        rh = np.where(r_ok, data.rh, 0.0)
        ra = np.where(r_ok, data.ra, 0.0)
        wr = np.where(r_ok, data.wr, 0.0)
        rconst = float(np.sum(wr * (gammaln(rh + 1) + gammaln(ra + 1))))
    else:
        rh = ra = wr = None
        rconst = 0.0
    gconst = float(np.sum(wg * (gammaln(hg + 1) + gammaln(ag + 1))))
    ap = np.zeros(n) if att_prior is None else att_prior
    dp = np.zeros(n) if def_prior is None else def_prior

    def f(x):
        att, dfn, home, rho = x[:n], x[n:2 * n], x[2 * n], x[2 * n + 1]
        eh = att[hi] + dfn[ai] + home * hfa
        ea = att[ai] + dfn[hi]
        lh, la = np.exp(eh), np.exp(ea)
        tau, m00, m10, m01, m11 = _tau(hg, ag, lh, la, rho)
        tau = np.maximum(tau, 1e-10)
        ll = wg * (hg * eh - lh + ag * ea - la + np.log(tau))
        gh = wg * (hg - lh)
        ga = wg * (ag - la)
        # tau derivatives (w.r.t. eta_h, eta_a, rho)
        grho = np.zeros_like(lh)
        d = -lh * la * rho / tau
        gh = gh + np.where(m00, wg * d, 0.0)
        ga = ga + np.where(m00, wg * d, 0.0)
        grho += np.where(m00, -lh * la / tau, 0.0)
        ga = ga + np.where(m10, wg * la * rho / tau, 0.0)
        grho += np.where(m10, la / tau, 0.0)
        gh = gh + np.where(m01, wg * lh * rho / tau, 0.0)
        grho += np.where(m01, lh / tau, 0.0)
        grho += np.where(m11, -1.0 / tau, 0.0)
        total = ll.sum() - gconst
        if rh is not None:
            total += np.sum(wr * (rh * eh - lh + ra * ea - la)) - rconst
            gh = gh + wr * (rh - lh)
            ga = ga + wr * (ra - la)
        g = np.zeros(2 * n + 2)
        g[:n] = np.bincount(hi, gh, n) + np.bincount(ai, ga, n)
        g[n:2 * n] = np.bincount(ai, gh, n) + np.bincount(hi, ga, n)
        g[2 * n] = np.sum(gh * hfa)
        g[2 * n + 1] = np.sum(wg * grho)
        da, dd = att - ap, dfn - dp
        val = -total + ridge * (da @ da + dd @ dd)
        grad = -g
        grad[:n] += 2 * ridge * da
        grad[n:2 * n] += 2 * ridge * dd
        if not fit_rho:
            grad[2 * n + 1] = 0.0
        return val, grad

    if x0 is None:
        x0 = np.zeros(2 * n + 2)
        x0[:n], x0[n:2 * n] = ap, dp
        x0[2 * n], x0[2 * n + 1] = 0.1, -0.1 if fit_rho else 0.0
    x0 = x0.copy()
    x0[n] = 0.0
    if rho_fixed is not None:
        x0[2 * n + 1] = float(rho_fixed)
    bounds = [(None, None)] * n + [(0.0, 0.0)] + [(None, None)] * (n - 1) + [(None, None)]
    bounds.append(rho_bounds if fit_rho else (x0[2 * n + 1], x0[2 * n + 1]))
    x0[2 * n + 1] = float(np.clip(x0[2 * n + 1], *bounds[-1]))
    res = minimize(f, x0, jac=True, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": maxiter, "ftol": 1e-10, "gtol": 1e-6})
    return res.x


def score_matrix(lh: np.ndarray, la: np.ndarray, rho: float | np.ndarray, max_goals: int = 10) -> np.ndarray:
    """(m, G+1, G+1) Dixon-Coles score matrices, renormalised over the grid."""
    k = np.arange(max_goals + 1)
    ph = poisson.pmf(k[None, :], lh[:, None])
    pa = poisson.pmf(k[None, :], la[:, None])
    M = ph[:, :, None] * pa[:, None, :]
    rho = np.broadcast_to(np.asarray(rho, dtype=float), lh.shape)
    M[:, 0, 0] *= 1 - lh * la * rho
    M[:, 1, 0] *= 1 + la * rho
    M[:, 0, 1] *= 1 + lh * rho
    M[:, 1, 1] *= 1 - rho
    M = np.clip(M, 0, None)
    return M / M.sum(axis=(1, 2), keepdims=True)


def outcome_probs(M: np.ndarray) -> np.ndarray:
    """(m, 3) home/draw/away from score matrices."""
    G = M.shape[1]
    i, j = np.indices((G, G))
    return np.stack([(M * (i > j)).sum((1, 2)), (M * (i == j)).sum((1, 2)), (M * (i < j)).sum((1, 2))], axis=1)


def over_prob(M: np.ndarray, line: float = 2.5) -> np.ndarray:
    G = M.shape[1]
    i, j = np.indices((G, G))
    return (M * ((i + j) > line)).sum((1, 2))


def ah_home_value(M: np.ndarray, line: np.ndarray, price_h: np.ndarray, price_a: np.ndarray):
    """
    Expected return per unit (and win/loss probabilities) of the home and away Asian
    handicap bets at `line` (football-data convention: the home side's handicap, e.g.
    -0.5), handling quarter lines as two half stakes.
    Returns (ev_home, ev_away, p_home_eff, p_away_eff), where p_*_eff is the
    probability-equivalent that makes the bet fair at price p: EV = p_eff*price - 1
    for whole/half lines (pushes removed); for quarter lines it is the stake-averaged one.
    """
    G = M.shape[1]
    i, j = np.indices((G, G))
    gd = (i - j)[None, :, :]

    def settle(l):
        # home result per cell at handicap l: margin = gd + l
        m = gd + l[:, None, None]
        win = (M * (m > 0)).sum((1, 2))
        push = (M * (m == 0)).sum((1, 2))
        lose = 1 - win - push
        return win, push, lose

    q = np.round(line * 4) % 2 == 1  # quarter line
    lo = np.where(q, line - 0.25, line)
    hi_ = np.where(q, line + 0.25, line)
    w1, p1, l1 = settle(lo)
    w2, p2, l2 = settle(hi_)
    ev_h = 0.5 * ((w1 * (price_h - 1) - l1) + (w2 * (price_h - 1) - l2))
    ev_a = 0.5 * ((l1 * (price_a - 1) - w1) + (l2 * (price_a - 1) - w2))
    return ev_h, ev_a


def ah_settle(gd: np.ndarray, line: np.ndarray, side_home: np.ndarray) -> np.ndarray:
    """Realised return per unit staked *before* price: returns (win_frac, push_frac) arrays."""
    q = np.round(line * 4) % 2 == 1
    out_w = np.zeros(len(gd))
    out_p = np.zeros(len(gd))
    for part in (np.where(q, line - 0.25, line), np.where(q, line + 0.25, line)):
        m = gd + part
        m = np.where(side_home, m, -m)
        out_w += 0.5 * (m > 0)
        out_p += 0.5 * (m == 0)
    return out_w, out_p
