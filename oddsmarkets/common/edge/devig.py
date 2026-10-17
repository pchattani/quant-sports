"""
De-vigging: decimal prices -> fair probabilities, one market at a time or vectorised over a frame.

Methods (q_i = 1/o_i, S = sum q_i is the booksum, S - 1 the overround):

    multiplicative   p_i = q_i / S                                   (proportional; the classic default)
    additive         p_i = q_i - (S - 1)/n                           (equal margin per outcome; can go negative)
    power            p_i = q_i^k with k such that sum q_i^k = 1      (puts more margin on longshots)
    shin             Shin (1993) insider-trading model: p_i = (sqrt(z^2 + 4(1-z) q_i^2/S) - z) / (2(1-z)),
                     z solved so that sum p_i = 1                    (more margin on longshots, models
                                                                      favourite-longshot bias explicitly)

`power` is this package's consistent default (`DEFAULT_METHOD`): it always has a solution (including an
underround book, S < 1, where it gives k < 1), it corrects the favourite-longshot bias the way Shin does
(Clarke, Kovalchik & Ingram 2017 find power and Shin the two best of the standard methods), and it is cheap to
solve vectorised. Shin with S <= 1 has no insider fraction to solve for and falls back to multiplicative.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

DEFAULT_METHOD = "power"
METHODS = ("multiplicative", "additive", "power", "shin")


def _q(prices: Sequence[float]) -> np.ndarray:
    o = np.asarray(prices, dtype=float)
    if o.ndim != 1 or len(o) == 0 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        raise ValueError(f"decimal prices must be finite and > 1, got {prices!r}")
    return 1.0 / o


def overround(prices: Sequence[float]) -> float:
    return float(_q(prices).sum() - 1.0)


def multiplicative(prices: Sequence[float]) -> np.ndarray:
    q = _q(prices)
    return q / q.sum()


def additive(prices: Sequence[float]) -> np.ndarray:
    q = _q(prices)
    p = q - (q.sum() - 1.0) / len(q)
    p = np.clip(p, 1e-9, None)
    return p / p.sum()


def power(prices: Sequence[float], tol: float = 1e-12) -> np.ndarray:
    q = _q(prices)
    if abs(q.sum() - 1.0) < tol:
        return q.copy()
    lq = np.log(q)
    k = 1.0
    for _ in range(100):  # Newton on f(k) = sum q^k - 1, f' = sum q^k ln q  (< 0, f convex: monotone convergence)
        qk = np.exp(k * lq)
        f = qk.sum() - 1.0
        if abs(f) < tol:
            break
        k -= f / (qk * lq).sum()
    p = np.exp(k * lq)
    return p / p.sum()


def _shin_p(q: np.ndarray, S: float, z: float) -> np.ndarray:
    return (np.sqrt(z * z + 4.0 * (1.0 - z) * q * q / S) - z) / (2.0 * (1.0 - z))


def shin(prices: Sequence[float]) -> np.ndarray:
    q = _q(prices)
    S = q.sum()
    if S <= 1.0 + 1e-12:
        return q / S
    lo, hi = 0.0, 0.999
    for _ in range(200):  # bisection: sum p(z) decreases in z, sqrt(S) > 1 at z = 0
        mid = 0.5 * (lo + hi)
        if _shin_p(q, S, mid).sum() > 1.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-14:
            break
    p = _shin_p(q, S, 0.5 * (lo + hi))
    return p / p.sum()


def shin_z(prices: Sequence[float]) -> float:
    """Shin's insider fraction z for a market (0 when the book is not overround)."""
    q = _q(prices)
    S = q.sum()
    if S <= 1.0:
        return 0.0
    lo, hi = 0.0, 0.999
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _shin_p(q, S, mid).sum() > 1.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ------------------------------------------------------------------------- light-weight multiplicative helpers
# The sport packages' two-way / row-wise helpers are thin wrappers onto these (fund foundations, 2026-10-02). They do
# no validation (the callers keep their own guards) and propagate NaN, so results are bit-identical to the copies
# they replaced.


def multiplicative_pair(d1, d2):
    """Two decimal prices (scalars or arrays) -> (p1, p2), multiplicative; no validation, NaN propagates."""
    a, b = 1 / d1, 1 / d2
    s = a + b
    return a / s, b / s


def normalise_pair(p1, p2):
    """Two implied probabilities (vig included) -> fair P(first) = p1 / (p1 + p2)."""
    return p1 / (p1 + p2)


def multiplicative_dict(prices: dict) -> dict:
    """{outcome: decimal price} -> {outcome: fair p}; entries that are not numbers > 1 are dropped; {} if none."""
    implied = {}
    for outcome, odds in prices.items():
        try:
            value = float(odds)
        except (TypeError, ValueError):
            continue
        if value > 1.0:
            implied[outcome] = 1.0 / value
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in implied.items()}


def multiplicative_rows(odds, strict: bool = True) -> np.ndarray:
    """Multiplicative de-vig along the last axis. Prices <= 1 or NaN make the row NaN; `strict` also NaNs a row with
    any non-finite price (an infinite price otherwise counts as probability 0)."""
    o = np.asarray(odds, dtype=float)
    inv = 1.0 / np.where(o > 1.0, o, np.nan)
    p = inv / inv.sum(axis=-1, keepdims=True)
    if strict:
        bad = ~np.isfinite(o).all(axis=-1) | (o <= 1.0).any(axis=-1)
        p[bad] = np.nan
    return p


_FUNCS = {"multiplicative": multiplicative, "additive": additive, "power": power, "shin": shin}


def devig(prices: Sequence[float], method: str = DEFAULT_METHOD) -> np.ndarray:
    if method not in _FUNCS:
        raise ValueError(f"unknown de-vig method {method!r}; choose from {METHODS}")
    return _FUNCS[method](prices)


# ----------------------------------------------------------------------------------------------- vectorised


def devig_grouped(prices: np.ndarray, codes: np.ndarray, method: str = DEFAULT_METHOD, iters: int = 60) -> np.ndarray:
    """
    De-vig many markets at once. `prices[i]` is a decimal price, `codes[i]` an integer market id (0..G-1).
    Every group is de-vigged on its own with `method`; the result is aligned with `prices`.
    """
    o = np.asarray(prices, dtype=float)
    c = np.asarray(codes, dtype=np.int64)
    if len(o) == 0:
        return np.zeros(0)
    G = int(c.max()) + 1
    q = 1.0 / o
    S = np.bincount(c, weights=q, minlength=G)
    if method == "multiplicative":
        return q / S[c]
    if method == "additive":
        n = np.bincount(c, minlength=G).astype(float)
        p = np.clip(q - ((S - 1.0) / n)[c], 1e-9, None)
        return p / np.bincount(c, weights=p, minlength=G)[c]
    if method == "power":
        lq = np.log(q)
        k = np.ones(G)
        for _ in range(iters):
            qk = np.exp(k[c] * lq)
            f = np.bincount(c, weights=qk, minlength=G) - 1.0
            fp = np.bincount(c, weights=qk * lq, minlength=G)
            step = np.where(np.abs(fp) > 1e-300, f / np.where(fp == 0, 1.0, fp), 0.0)
            k = np.clip(k - step, 1e-3, 1e3)
            if np.max(np.abs(f)) < 1e-12:
                break
        p = np.exp(k[c] * lq)
        return p / np.bincount(c, weights=p, minlength=G)[c]
    if method == "shin":
        over = S > 1.0 + 1e-12
        lo, hi = np.zeros(G), np.full(G, 0.999)
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            z = mid[c]
            s = np.bincount(c, weights=_shin_p(q, S[c], z), minlength=G)
            up = s > 1.0
            lo = np.where(up, mid, lo)
            hi = np.where(up, hi, mid)
        z = np.where(over, 0.5 * (lo + hi), 0.0)[c]
        p = np.where(over[c], _shin_p(q, S[c], z), q / S[c])
        return p / np.bincount(c, weights=p, minlength=G)[c]
    raise ValueError(f"unknown de-vig method {method!r}; choose from {METHODS}")


# Expected number of selections in a complete market (None: any n >= 2 whose booksum is plausible).
_EXPECTED_N = {"1x2": (3,), "moneyline": (2, 3), "spread": (2,), "total": (2,), "btts": (2,), "draw_no_bet": (2,)}


def market_family(market: str) -> str:
    m = str(market).lower()
    for fam in ("1x2", "moneyline", "spread", "total", "btts", "draw_no_bet"):
        if m == fam or m.startswith(fam + "_") or m.startswith(fam + ":"):
            return fam
    if m.startswith(("handicap", "asian_handicap", "ah", "run_line", "puck_line")):
        return "spread"
    if m.startswith(("over_under", "ou_", "totals")):
        return "total"
    if m.startswith("future"):
        return "future"
    if m.startswith("prop"):
        return "prop"
    return m


def as_key(s: pd.Series) -> pd.Series:
    """String key with missing values spelled out (pandas 3 keeps NaN as NA through astype(str))."""
    return s.astype(object).where(s.notna(), "na").astype(str)


def group_keys(df: pd.DataFrame, with_decision: bool = True) -> pd.Series:
    """
    Key of one mutually exclusive market: event, market, |line| (spread sides may carry opposite signs),
    price source and (optionally) decision time. Selections sharing a key are the outcomes of one market.
    """
    fam = df["market"].map(market_family)
    line = pd.to_numeric(df.get("line"), errors="coerce") if "line" in df else pd.Series(np.nan, index=df.index)
    line = np.where(fam.isin(["spread"]), line.abs(), line)
    parts = [as_key(df["event_id"]), as_key(df["market"]), as_key(pd.Series(line, index=df.index).round(4)),
             as_key(df["price_src"])]
    if with_decision:
        t = pd.to_datetime(df["decision_time"], utc=True)
        parts.append(as_key((t - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta(seconds=1)))
    key = parts[0]
    for p_ in parts[1:]:
        key = key + "|" + p_
    return key


def complete_groups(df: pd.DataFrame, price_col: str, key: pd.Series) -> pd.Series:
    """True for rows whose market group looks complete (right outcome count, plausible booksum, unique selections)."""
    q = 1.0 / pd.to_numeric(df[price_col], errors="coerce")
    g = pd.DataFrame({"k": key.values, "q": q.values, "sel": df["selection"].astype(str).values,
                      "fam": df["market"].map(market_family).values}, index=df.index)
    n = g.groupby("k")["q"].transform("count")
    nsel = g.groupby("k")["sel"].transform("nunique")
    S = g.groupby("k")["q"].transform("sum")
    ok_n = pd.Series(True, index=df.index)
    for fam, ns in _EXPECTED_N.items():
        m = g["fam"] == fam
        ok_n[m] = n[m].isin(ns)
    hi = np.where(g["fam"].isin(["future", "prop"]), 1.8, 1.35)
    return (n >= 2) & (nsel == n) & ok_n & q.notna() & (S >= 0.90) & (S <= hi)


def fair_from_prices(df: pd.DataFrame, price_col: str, key: pd.Series, method: str = DEFAULT_METHOD
                     ) -> tuple[pd.Series, pd.Series]:
    """
    Fair probabilities from `price_col` for complete market groups (NaN elsewhere) and the completeness mask.
    """
    ok = complete_groups(df, price_col, key)
    out = pd.Series(np.nan, index=df.index)
    if ok.any():
        sub = df.loc[ok]
        codes = pd.factorize(key[ok])[0]
        out.loc[ok] = devig_grouped(sub[price_col].to_numpy(float), codes, method)
    return out, ok
