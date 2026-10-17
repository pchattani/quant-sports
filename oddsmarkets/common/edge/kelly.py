"""
Stake sizing: Kelly (single, mutually exclusive, simultaneous), flat and proportional-to-edge, with caps.

Closed forms
    kelly_binary(p, o)      f* = (p*o - 1) / (o - 1)                         (one bet, decimal price o)
    kelly_exclusive(p, o)   Smoczynski & Tomkins (2010): bets on mutually exclusive outcomes of one market.
                            Order by p_i*o_i; the optimal set S is the prefix with p_i*o_i > R(S),
                            R(S) = (1 - sum_S p) / (1 - sum_S 1/o); f_i = p_i - R(S)/o_i for i in S.

Numerical
    simultaneous_kelly(p, o, groups)   maximise E[log(1 + sum_i f_i r_i)] over all bets on a slate, where
                            `groups` labels mutually exclusive sets (one market of one event) and different
                            groups are independent. Outcome scenarios are enumerated exactly when the joint
                            space is small, otherwise sampled (fixed seed); the all-lose scenario is always
                            included with its exact probability, so the log barrier keeps wealth positive.
                            L-BFGS-B with analytic gradient, bounds 0 <= f_i <= 1.

Correlated selections that are not mutually exclusive (a moneyline and a total on the same game, two futures on
one team) have no joint distribution in the edge files; the optimiser treats them as independent and the
`max_group` cap on `corr_group` bounds the combined exposure instead.

`size_slate` turns a slate of candidate bets (decision-time columns only) into bankroll fractions:
    full-Kelly vector -> * kelly_fraction -> per-bet cap -> per-corr_group cap -> per-league cap -> per-slate cap
    (each cap scales the offending set down pro rata). Drawdown throttling, liquidity (max_stake_hint) and the
    cash constraint are applied by the backtest engine, which knows the bankroll.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def kelly_binary(p, price):
    p = np.asarray(p, dtype=float)
    o = np.asarray(price, dtype=float)
    return np.clip((p * o - 1.0) / (o - 1.0), 0.0, None)


def kelly_exclusive(p, price) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    o = np.asarray(price, dtype=float)
    n = len(p)
    f = np.zeros(n)
    order = np.argsort(-(p * o))
    R = 1.0
    S: list[int] = []
    sp = sq = 0.0
    for k in order:
        if p[k] * o[k] <= R:
            break
        sp2, sq2 = sp + p[k], sq + 1.0 / o[k]
        if sq2 >= 1.0:
            # betting every outcome of an underround book: R would be undefined; stop at the current set
            S.append(k)
            sp, sq = sp2, sq2
            R = 0.0
            break
        S.append(k)
        sp, sq = sp2, sq2
        R = (1.0 - sp) / (1.0 - sq)
    for k in S:
        f[k] = max(p[k] - R / o[k], 0.0)
    return f


def expected_log_growth(f, p, price, groups=None, **kw) -> float:
    R, w = _scenarios(np.asarray(p, float), np.asarray(price, float),
                      np.arange(len(p)) if groups is None else np.asarray(groups), **kw)
    return float(w @ np.log1p(R @ np.asarray(f, float)))


def _scenarios(p: np.ndarray, o: np.ndarray, groups: np.ndarray, max_enum: int = 4096, n_samples: int = 3000,
               seed: int = 12345) -> tuple[np.ndarray, np.ndarray]:
    """Return (R, w): R[s, i] net return of a unit on bet i in scenario s, w[s] scenario probability."""
    labels, gidx = np.unique(groups, return_inverse=True)
    G = len(labels)
    members = [np.flatnonzero(gidx == g) for g in range(G)]
    # outcome k of group g: k < len(members[g]) means that member wins; k == len: none of the bet selections wins
    probs = []
    for m in members:
        pg = p[m]
        rest = max(1.0 - pg.sum(), 0.0)
        pr = np.append(pg, rest)
        probs.append(pr / pr.sum())
    sizes = [len(pr) for pr in probs]
    total = float(np.prod(np.array(sizes, dtype=float)))
    n = len(p)
    if total <= max_enum:
        grids = np.array(np.meshgrid(*[np.arange(s) for s in sizes], indexing="ij")).reshape(G, -1).T
        w = np.ones(len(grids))
        for g in range(G):
            w *= probs[g][grids[:, g]]
        out = grids
    else:
        rng = np.random.default_rng(seed)
        out = np.empty((n_samples, G), dtype=np.int64)
        for g in range(G):
            out[:, g] = rng.choice(sizes[g], size=n_samples, p=probs[g])
        w = np.full(n_samples, 1.0 / n_samples)
        # exact all-lose scenario appended (weight = its probability), samples reweighted to the remainder
        p_lose = float(np.prod([pr[-1] for pr in probs]))
        out = np.vstack([out, [s - 1 for s in sizes]])
        w = np.append(w * (1.0 - p_lose), p_lose)
    R = np.full((len(out), n), -1.0)
    for g in range(G):
        for j, i in enumerate(members[g]):
            R[out[:, g] == j, i] = o[i] - 1.0
    keep = w > 0
    return R[keep], w[keep]


def simultaneous_kelly(p, price, groups=None, max_enum: int = 4096, n_samples: int = 3000, seed: int = 12345,
                       max_total: float = 0.999) -> np.ndarray:
    p = np.asarray(p, dtype=float)
    o = np.asarray(price, dtype=float)
    n = len(p)
    if n == 0:
        return np.zeros(0)
    groups = np.arange(n) if groups is None else np.asarray(groups)
    pos = p * o > 1.0
    f = np.zeros(n)
    if not pos.any():
        return f
    idx = np.flatnonzero(pos)
    R, w = _scenarios(p[idx], o[idx], groups[idx], max_enum, n_samples, seed)

    # start: per-group exclusive Kelly, scaled so the worst case keeps wealth positive
    x0 = np.zeros(len(idx))
    gi = groups[idx]
    for g in np.unique(gi):
        m = gi == g
        x0[m] = kelly_exclusive(p[idx][m], o[idx][m])
    worst = x0.sum()
    if worst >= 0.5:
        x0 *= 0.5 / worst
    f[idx] = scenario_kelly(R, w, x0, upper=max_total)
    return f


def scenario_kelly(R: np.ndarray, w: np.ndarray, x0: np.ndarray | None = None, upper: float = 0.999) -> np.ndarray:
    """
    Maximise sum_s w_s log(1 + R[s] . x) over 0 <= x_i <= upper, where R[s, i] is the net return of a unit stake on
    bet i in joint scenario s (any dependence: exclusive sets, shared drivers, copulas). `simultaneous_kelly` is the
    special case whose scenarios come from independent exclusive groups; fund/portfolio adds costs, book levels and
    linear limits on top of the same objective. L-BFGS-B with the analytic gradient; falls back to x0 if the solver
    does not improve on it.
    """
    R = np.asarray(R, float)
    w = np.asarray(w, float)
    n = R.shape[1]
    x0 = np.zeros(n) if x0 is None else np.asarray(x0, float)

    def obj(x):
        wealth = 1.0 + R @ x
        if np.any(wealth <= 1e-12):
            return 1e10, np.zeros_like(x)
        v = -(w @ np.log(wealth))
        g = -(R.T @ (w / wealth))
        return v, g

    res = minimize(obj, x0, jac=True, method="L-BFGS-B", bounds=[(0.0, upper)] * n,
                   options={"maxiter": 500, "ftol": 1e-13, "gtol": 1e-10})
    x = np.clip(res.x, 0.0, None)
    if not np.isfinite(obj(x)[0]) or obj(x)[0] > obj(x0)[0]:
        x = x0
    return x


# ----------------------------------------------------------------------------------------------- policy


@dataclass
class SizingConfig:
    method: str = "kelly"            # kelly | flat | prop_edge
    kelly_fraction: float = 0.25
    simultaneous: bool = True        # False: independent per-group Kelly, then caps
    min_edge: float = 0.02
    min_prob: float = 0.02
    max_price: float = 51.0
    use_shrunk: bool = True          # size on q (walk-forward shrunk) rather than raw model_p
    max_bet: float = 0.03            # of bankroll
    max_group: float = 0.05          # per corr_group (same event / same team futures)
    max_league: float = 0.12         # per league within one slate
    max_slate: float = 0.25          # all bets on one slate
    flat_stake: float = 0.01         # of INITIAL bankroll (no compounding)
    prop_scale: float = 0.25         # prop_edge: fraction = prop_scale * edge
    min_frac: float = 0.0002         # dust: smaller stakes are not placed
    dd_start: float = 0.15           # drawdown throttle: full size above, linear down to dd_floor_mult at dd_full
    dd_full: float = 0.40
    dd_floor_mult: float = 0.25
    use_caps: bool = True
    n_samples: int = 2000
    max_enum: int = 4096
    extra: dict = field(default_factory=dict)

    def label(self) -> str:
        if self.method == "kelly":
            s = f"kelly x{self.kelly_fraction:g}" + ("" if self.simultaneous else " (indep)")
        elif self.method == "flat":
            s = f"flat {self.flat_stake:.1%}"
        else:
            s = f"prop-edge x{self.prop_scale:g}"
        s += "" if self.use_shrunk else ", raw model"
        return s + ("" if self.use_caps else ", no caps")


def candidates(view: pd.DataFrame, cfg: SizingConfig) -> pd.Series:
    """Rows that pass the bet filters (decision-time information only)."""
    pcol = "q" if cfg.use_shrunk else "model_p"
    e = view[pcol] * view["price_dec"] - 1.0
    return (e >= cfg.min_edge) & (view[pcol] >= cfg.min_prob) & (view["price_dec"] <= cfg.max_price)


def _cap_sets(f: np.ndarray, keys: np.ndarray, cap: float) -> np.ndarray:
    if len(f) == 0:
        return f
    codes, inv = np.unique(keys, return_inverse=True)
    tot = np.bincount(inv, weights=f, minlength=len(codes))
    scale = np.where(tot > cap, cap / np.where(tot > 0, tot, 1.0), 1.0)
    return f * scale[inv]


def drawdown_multiplier(dd: float, cfg: SizingConfig) -> float:
    if dd <= cfg.dd_start:
        return 1.0
    if dd >= cfg.dd_full:
        return cfg.dd_floor_mult
    t = (dd - cfg.dd_start) / (cfg.dd_full - cfg.dd_start)
    return 1.0 - t * (1.0 - cfg.dd_floor_mult)


def full_kelly(view: pd.DataFrame, cfg: SizingConfig) -> np.ndarray:
    """Full-Kelly fractions for a slate (independent of bankroll, so cacheable across fractions and caps)."""
    pcol = "q" if cfg.use_shrunk else "model_p"
    p = view[pcol].to_numpy(float)
    o = view["price_dec"].to_numpy(float)
    groups = view["excl_key"].to_numpy()
    if cfg.simultaneous:
        return simultaneous_kelly(p, o, groups, max_enum=cfg.max_enum, n_samples=cfg.n_samples)
    f = np.zeros(len(p))
    for g in np.unique(groups):
        m = groups == g
        f[m] = kelly_exclusive(p[m], o[m])
    return f


def size_slate(view: pd.DataFrame, cfg: SizingConfig, bankroll_frac_flat: float = 1.0, full=None) -> np.ndarray:
    """
    Bankroll fractions for one slate's candidate bets. `view` holds decision-time columns only plus q / excl_key.
    `bankroll_frac_flat` = initial bankroll / current bankroll, so flat stakes stay a fixed currency amount.
    """
    n = len(view)
    if n == 0:
        return np.zeros(0)
    pcol = "q" if cfg.use_shrunk else "model_p"
    p = view[pcol].to_numpy(float)
    o = view["price_dec"].to_numpy(float)
    edge = p * o - 1.0
    if cfg.method == "flat":
        f = np.full(n, cfg.flat_stake * bankroll_frac_flat)
    elif cfg.method == "prop_edge":
        f = np.clip(cfg.prop_scale * edge, 0.0, None)
    elif cfg.method == "kelly":
        f = (full_kelly(view, cfg) if full is None else np.asarray(full, float)) * cfg.kelly_fraction
    else:
        raise ValueError(f"unknown sizing method {cfg.method!r}")
    if cfg.use_caps:
        f = np.minimum(f, cfg.max_bet)
        f = _cap_sets(f, view["corr_group"].astype(str).to_numpy(), cfg.max_group)
        f = _cap_sets(f, view["league"].astype(str).to_numpy(), cfg.max_league)
        tot = f.sum()
        if tot > cfg.max_slate:
            f = f * (cfg.max_slate / tot)
    else:
        tot = f.sum()
        if tot > 0.95:  # without caps still never stake the whole bankroll on one slate
            f = f * (0.95 / tot)
    f[f < cfg.min_frac] = 0.0
    return f
