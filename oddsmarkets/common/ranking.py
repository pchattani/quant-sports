"""
Plackett-Luce ranking model.

A finishing order is read as successive draws without replacement: the winner is
drawn from the whole field with probability proportional to exp(theta_i), second
from those left, and so on. For an observed (possibly partial, top-k) order
o_1..o_k from a field F,

    P(o | theta) = prod_{s=1..k} exp(theta_{o_s}) / sum_{j in R_s} exp(theta_j),
    R_s = F minus {o_1..o_{s-1}}

Competitors in F but not in the observed order are known only to finish behind
o_k (they stay in every denominator). The fit maximises the penalised log-likelihood

    L(theta) = sum_orders w_o * log P(o | theta)  -  (ridge / 2) * sum_i theta_i^2

with L-BFGS (scipy) on the analytic gradient

    dL/dtheta_i = sum_o w_o sum_s [ 1(i = o_s) - 1(i in R_s) * exp(theta_i) / sum_{j in R_s} exp(theta_j) ] - ridge * theta_i

The ridge is a Gaussian prior theta_i ~ N(0, 1/ridge): it makes the problem
identifiable (L is invariant to adding a constant to every theta) and keeps a
competitor who always wins or always loses at a finite strength. Because the
likelihood gradient sums to zero over items, the optimum has mean(theta) = 0.

Probabilities: P(win) is exact, softmax(theta). Top-k and expected position are
estimated by sampling orders with the Gumbel trick (argsort of theta_i + G_i,
G_i ~ Gumbel(0, 1) i.i.d. is an exact Plackett-Luce draw).
"""
from __future__ import annotations

import math
from typing import Hashable, Iterable, Sequence

import numpy as np

DEFAULT_RIDGE = 0.1


def _index(orderings: Sequence[Sequence[Hashable]], fields: Sequence[Iterable[Hashable]] | None) -> tuple[list, list[np.ndarray], list[int]]:
    items: dict[Hashable, int] = {}

    def ix(x):
        if x not in items:
            items[x] = len(items)
        return items[x]

    arrays, ks = [], []
    for n, order in enumerate(orderings):
        seen: list[int] = []
        for x in order:
            i = ix(x)
            if i not in seen:
                seen.append(i)
        k = len(seen)
        if fields is not None and n < len(fields) and fields[n] is not None:
            for x in fields[n]:
                i = ix(x)
                if i not in seen:
                    seen.append(i)
        arrays.append(np.asarray(seen, dtype=int))
        ks.append(k)
    return list(items), arrays, ks


def _loglik_grad(theta: np.ndarray, arrays: list[np.ndarray], ks: list[int], weights: np.ndarray) -> tuple[float, np.ndarray]:
    ll = 0.0
    grad = np.zeros_like(theta)
    for idx, k, w in zip(arrays, ks, weights):
        m = len(idx)
        stages = min(k, m - 1)                    # the last remaining competitor carries no information
        if stages <= 0 or w == 0:
            continue
        t = theta[idx]
        top = t.max()
        e = np.exp(t - top)
        suffix = np.cumsum(e[::-1])[::-1]         # S_s = sum_{j >= s} e_j
        ll += w * float(np.sum(t[:stages] - top - np.log(suffix[:stages])))
        inv = np.cumsum(1.0 / suffix[:stages])    # sum_{s <= t} 1 / S_s
        pos = np.minimum(np.arange(m), stages - 1)
        g = -e * inv[pos]
        g[:stages] += 1.0
        np.add.at(grad, idx, w * g)
    return ll, grad


def loglik(strengths: dict, orderings: Sequence[Sequence[Hashable]], fields=None, weights=None) -> float:
    """Plackett-Luce log-likelihood of `orderings` under log-strengths `strengths` (unknown items get 0)."""
    items, arrays, ks = _index(orderings, fields)
    theta = np.array([float(strengths.get(x, 0.0)) for x in items])
    w = np.ones(len(arrays)) if weights is None else np.asarray(weights, dtype=float)
    return _loglik_grad(theta, arrays, ks, w)[0]


def fit_strengths(
    orderings: Sequence[Sequence[Hashable]],
    fields: Sequence[Iterable[Hashable]] | None = None,
    weights: Sequence[float] | None = None,
    ridge: float = DEFAULT_RIDGE,
    maxiter: int = 500,
) -> dict:
    """
    Fit Plackett-Luce log-strengths theta (mean zero) from observed orders.

    `orderings` lists each observed order, best first; `fields[n]` (optional) is the
    full set of competitors in contest n, those missing from the order having finished
    behind it; `weights[n]` (optional) down-weights old contests. Returns {item: theta}.
    Never raises on empty input (returns {}).
    """
    if not orderings:
        return {}
    items, arrays, ks = _index(orderings, fields)
    if not items:
        return {}
    w = np.ones(len(arrays)) if weights is None else np.asarray(list(weights), dtype=float)
    ridge = max(float(ridge), 1e-9)

    def objective(x):
        ll, g = _loglik_grad(x, arrays, ks, w)
        return -(ll - 0.5 * ridge * float(x @ x)), -(g - ridge * x)

    from scipy.optimize import minimize

    res = minimize(objective, np.zeros(len(items)), jac=True, method="L-BFGS-B", options={"maxiter": maxiter})
    theta = res.x - res.x.mean()
    return {x: float(v) for x, v in zip(items, theta)}


fit_plackett_luce = fit_strengths


def _theta(strengths: dict, log: bool) -> tuple[list, np.ndarray]:
    items = list(strengths)
    vals = np.array([float(strengths[x]) for x in items], dtype=float)
    if not log:
        vals = np.log(np.clip(vals, 1e-300, None))
    vals = np.where(np.isfinite(vals), vals, -1e9)
    return items, vals


def sample_orders(strengths: dict, n: int = 20000, seed: int | None = 0, log: bool = True) -> tuple[list, np.ndarray]:
    """
    Draw `n` complete Plackett-Luce orders. Returns (items, orders) where orders is an
    (n, m) int array of indices into `items`, best first. `strengths` are log-strengths
    theta (or positive weights with log=False).
    """
    items, theta = _theta(strengths, log)
    if not items or n <= 0:
        return items, np.zeros((0, len(items)), dtype=int)
    rng = np.random.default_rng(seed)
    g = rng.gumbel(size=(int(n), len(items)))
    return items, np.argsort(-(theta[None, :] + g), axis=1)


def pl_probabilities(strengths: dict, top_k: Iterable[int] = (3,), n: int = 20000, seed: int | None = 0, log: bool = True) -> dict:
    """
    {item: {"p_win", "p_top<k>" for each k, "exp_pos"}}. p_win is exact (softmax);
    p_top<k> and exp_pos come from `n` sampled orders. Each p_top<k> column sums to k
    (to min(k, field size)), p_win sums to 1.
    """
    items, theta = _theta(strengths, log)
    if not items:
        return {}
    e = np.exp(theta - theta.max())
    win = e / e.sum()
    _, orders = sample_orders(strengths, n=n, seed=seed, log=log)
    m = len(items)
    rank = np.empty_like(orders)
    rows = np.arange(orders.shape[0])[:, None]
    rank[rows, orders] = np.arange(m)[None, :]          # rank[s, i] = position of item i in draw s (0-based)
    out = {}
    for i, x in enumerate(items):
        rec = {"p_win": float(win[i])}
        for k in top_k:
            rec[f"p_top{int(k)}"] = float(np.mean(rank[:, i] < int(k)))
        rec["exp_pos"] = float(rank[:, i].mean() + 1.0)
        out[x] = rec
    return out


def win_probability(theta_a: float, theta_b: float) -> float:
    """P(a ahead of b) between two competitors alone: 1 / (1 + exp(theta_b - theta_a))."""
    return 1.0 / (1.0 + math.exp(theta_b - theta_a))
