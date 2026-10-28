"""
Transfers for The Quant Footballer: valuation v2, the fair fee model, deal grades,
club ledgers, window summaries and transfer budgets.

Inputs are the player value model's per-match lines (value.py), the value layer's
per-player state (value_payloads.py) and the transfer store that the hourly task
fills from Sofascore (docs/site/data/transfers/store.json: each followed club's
recent transfers in and out, and rated players' whole transfer histories; fees as
Sofascore publishes them).

Valuation v2 (`value_v2`). A player's value is the expected points above replacement
he adds over the next four seasons, discounted 15% a year:

    sum over t of 0.85^t x alive_t x max(rate_t, 0) x minutes_t / 90 x points per goal

with rate_0 his projected GAR/90 drawn from its posterior (the projection's standard
error from his minutes), rate_t moved each year by the ageing curve plus a random
year-to-year change, minutes_t = 3,400 x his availability (the share of his clubs'
minutes he played in the last 12 months, shrunk, drawn from a Beta), and alive_t the
chance of still being a regular. 400 draws give the mean and a 10-90% band.

Fair fee (`FeeModel`). log(fee) is regressed (ridge, standardised columns) on the value
at the time of each real fee in the store: log(1 + v2), the projected GAR/90, age and
its square, the position unit, the seller's and the buyer's pooled strength (expected
goal difference per match against the pool-average club; unknown clubs imputed with a
flag), and log(1 + 90s played). Position scarcity enters here, as the market prices it
(the unit terms), and so does league strength (the clubs' terms). Validated out of
sample: five folds by player, and the latest 30% of fees predicted from the earlier
70%, against a median-by-league-tier-and-unit baseline; and rank-correlated with
Sofascore's market values. Fitted only with MIN_FEE_FIT fees; otherwise the pages keep
the fair value index and say so.

Deal grades (in `build_transfers`): every transfer, loan and free in the last 12 months, for
both clubs: the fee against the fair fee at the time (cross-fitted, so a deal never
grades itself), weighted by the club minutes behind that fair fee (full from 1,800), and the value delivered since the move (GAR in the minutes played for
the new club against the projection at the time, shrunk by 900 minutes, plus the share
of the minutes he got), weighted in as the minutes accumulate. Letters are quintiles
among the year's graded deals. Ledgers, window summaries and budgets follow.

Everything here is pure computation; it never fetches and never invents a fee: a fee
Sofascore does not publish is "undisclosed" and stays out of the sums and the fit.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import numpy as np

from oddsmarkets.football.analytics import value as V

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────

SEASON_MINUTES = 3400.0          # minutes a club plays in a season (38 league matches and a few cup ties)
AVAIL_PRIOR = 0.5                # availability prior (share of the clubs' minutes) ...
AVAIL_PRIOR_MATCHES = 8.0        # ... worth this many matches
AVAIL_CONCENTRATION = 12.0       # Beta(a x c, (1 - a) x c) for the draws
V2_DRAWS = 400
V2_SEED = 20261016
MIN_FEE_FIT = 120                # fees with a value at the time needed to fit the fee model
FEE_LAMBDAS = (0.3, 1.0, 3.0, 10.0, 30.0)
FREE_REF_EUR = 1_000_000.0       # a free transfer's price score: log((fair + ref) / ref)
GRADE_WINDOW_DAYS = 365
FEED_DAYS = 400                  # the feed keeps this much history (two windows and the one now)
PERF_MINUTES = 1800.0            # the value since the move counts fully after this many minutes
PRICE_MINUTES = 1800.0           # the price part of a grade counts fully with this many club minutes before the move
UNKNOWN_XGD = -0.6               # a club outside the pooled fit: imputed strength (with a flag)
YOUTH_RE = re.compile(r"(\bU\s?\d{2}\b|\bII\b|\bB\b|Atl[eè]tic|Castilla|Next Gen|Reserves?|Youth|Juniors?|Primavera|\bNXT\b|Jong\b|Sub-?\d{2})",
                      re.IGNORECASE)
FEATURES = ("log_v2", "proj", "age", "age2", "u_CB", "u_FB", "u_MID", "u_ATT", "u_ST", "seller_xgd", "seller_unknown",
            "buyer_xgd", "buyer_unknown", "log_n90")


def _r(x, n=3):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, n) if math.isfinite(f) else None


# ── windows and deal kinds ───────────────────────────────────────────────────

def window_of(d: date) -> tuple[str, str]:
    """
    The transfer window a date falls in, by half-year: May-October is the summer window
    ("2026-S", "Summer 2026"); November-April the winter window ("2026-W", "Winter 2025/26",
    November and December counting toward the next year's). Northern-hemisphere names;
    South America's and MLS's windows fall in the same halves.
    """
    if 5 <= d.month <= 10:
        return f"{d.year}-S", f"Summer {d.year}"
    y = d.year + 1 if d.month >= 11 else d.year
    return f"{y}-W", f"Winter {y - 1}/{str(y)[2:]}"


def deal_kind(rec: dict) -> str:
    """fee, free, undisclosed, youth (a promotion from the club's own youth or reserve side), loan, loan_end."""
    k = rec.get("k")
    if k == 1:
        return "loan"
    if k == 2:
        return "loan_end"
    fee = rec.get("fee")
    if rec.get("cur"):
        fee = None                                   # a fee in another currency is not converted
    if fee is not None and fee > 0:
        return "fee"
    if YOUTH_RE.search(str(rec.get("fn") or "")):
        return "youth"
    if str(rec.get("d") or "").strip().lower() == "free":
        return "free"
    return "undisclosed"


def normalise(store: dict, today: date | None = None) -> list[dict]:
    """The store's transfers as dicts with a date, a kind, a window and the fee in EUR (or None)."""
    out = []
    for key, r in (store.get("transfers") or {}).items():
        try:
            d = datetime.fromtimestamp(int(r["ts"]), tz=timezone.utc).date()
            pid = int(r["p"])
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            continue
        if today is not None and d > today:
            continue                                  # announced for a future date
        kind = deal_kind(r)
        wk, wl = window_of(d)
        out.append({"key": key, "pid": pid, "name": r.get("n"), "pos": r.get("ps"), "date": d, "day": d.toordinal(),
                    "from": int(r["f"]) if r.get("f") is not None else None, "from_name": r.get("fn"),
                    "to": int(r["t"]) if r.get("t") is not None else None, "to_name": r.get("tn"),
                    "kind": kind, "fee": float(r["fee"]) if kind == "fee" else (0.0 if kind == "free" else None),
                    "fee_text": r.get("d"), "window": wk, "window_label": wl})
    out.sort(key=lambda t: (t["day"], t["key"]))
    return dedupe(out)


DEDUPE_DAYS = 14


def dedupe(moves: list[dict]) -> list[dict]:
    """
    One row per move. Sofascore can list the same move twice under two ids (an announcement and the registration, a
    day or a week apart): the same player, from the same club to the same club, of the same kind, within 14 days is
    one move. The first is kept (its date is the announcement) and takes a published fee the other carries.
    """
    kept: list[dict] = []
    last: dict[tuple, dict] = {}
    for t in moves:                                   # in date order
        k = (t["pid"], t["from"], t["to"], t["kind"])
        prev = last.get(k)
        if prev is not None and t["day"] - prev["day"] <= DEDUPE_DAYS:
            if prev.get("fee") is None and t.get("fee") is not None:
                prev["fee"], prev["fee_text"] = t["fee"], t.get("fee_text")
            continue
        last[k] = t
        kept.append(t)
    return kept


# ── a player's lines around a date ───────────────────────────────────────────

class History:
    """Per-player club lines in date order, with cumulative minutes and value, for windows around any date."""

    def __init__(self, R: V.Rows, vals: np.ndarray, repl_of_row: np.ndarray) -> None:
        club = V._club_rows(R)
        rows = np.flatnonzero(club)
        order = rows[np.lexsort((R.day[rows], R.pid[rows]))]
        self.pid = R.pid[order]
        self.day = R.day[order]
        self.tid = R.tid[order]
        self.mins = R.mins[order]
        v = vals.sum(axis=1)[order] if len(R) else np.zeros(0)
        self.gar = v - repl_of_row[order] * self.mins / 90.0
        self.cm = np.r_[0.0, np.cumsum(self.mins)]
        self.cg = np.r_[0.0, np.cumsum(self.gar)]
        u, start = np.unique(self.pid, return_index=True)
        self.start = dict(zip(u.tolist(), start.tolist()))
        self.end = dict(zip(u.tolist(), np.r_[start[1:], self.pid.size].tolist()))
        # Each club's match days (club competitions), for availability.
        mm = np.flatnonzero(np.array([R.comp_scope[c] == "club" for c in R.m_comp.tolist()], dtype=bool)) if R.m_day.size else np.zeros(0, dtype=int)
        by_club: dict[int, list[int]] = {}
        for mi in mm.tolist():
            for s in (0, 1):
                by_club.setdefault(int(R.m_tid[mi, s]), []).append(int(R.m_day[mi]))
        self.club_days = {t: np.sort(np.array(d)) for t, d in by_club.items()}

    def span(self, pid: int) -> tuple[int, int]:
        return self.start.get(pid, 0), self.end.get(pid, 0)

    def window(self, pid: int, d0: int, d1: int, tid: int | None = None) -> tuple[float, float, int]:
        """(minutes, GAR, appearances) of `pid` on days d0 <= day < d1, at club `tid` if given."""
        a, b = self.span(pid)
        if a >= b:
            return 0.0, 0.0, 0
        days = self.day[a:b]
        i, j = a + int(np.searchsorted(days, d0, "left")), a + int(np.searchsorted(days, d1, "left"))
        if i >= j:
            return 0.0, 0.0, 0
        if tid is None:
            return float(self.cm[j] - self.cm[i]), float(self.cg[j] - self.cg[i]), j - i
        sel = self.tid[i:j] == tid
        return float(self.mins[i:j][sel].sum()), float(self.gar[i:j][sel].sum()), int(sel.sum())

    def club_matches(self, tid: int, d0: int, d1: int) -> int:
        days = self.club_days.get(int(tid))
        if days is None:
            return 0
        return int(np.searchsorted(days, d1, "left") - np.searchsorted(days, d0, "left"))

    def availability(self, pid: int, d1: int, span_days: int = V.WINDOW_DAYS) -> tuple[float, float, int]:
        """
        (minutes, share of his clubs' minutes, matches he could have played) over [d1 - span, d1):
        each club he appeared for counts its matches from his first to his last appearance
        there, the latest club up to d1 (an injury or a benching counts against him).
        """
        a, b = self.span(pid)
        if a >= b:
            return 0.0, float("nan"), 0
        d0 = d1 - span_days
        days = self.day[a:b]
        i, j = a + int(np.searchsorted(days, d0, "left")), a + int(np.searchsorted(days, d1, "left"))
        if i >= j:
            return 0.0, float("nan"), 0
        mins = float(self.cm[j] - self.cm[i])
        tids, dd = self.tid[i:j], self.day[i:j]
        last_tid = int(tids[-1])
        n = 0
        for t in set(tids.tolist()):
            sel = dd[tids == t]
            hi = d1 if t == last_tid else int(sel.max()) + 1
            n += max(self.club_matches(t, int(sel.min()), hi), int((tids == t).sum()))
        return mins, (mins / (90.0 * n) if n > 0 else float("nan")), n


def shrunk_availability(share: float, n: int) -> float:
    if not (share == share) or n <= 0:
        return AVAIL_PRIOR
    share = min(max(share, 0.0), 1.0)
    return (share * n + AVAIL_PRIOR * AVAIL_PRIOR_MATCHES) / (n + AVAIL_PRIOR_MATCHES)


# ── valuation v2 ─────────────────────────────────────────────────────────────

@dataclass
class V2Params:
    ppg: float                       # points per goal of goal difference (pool)
    slope: float                     # value per 90 per rating point
    curve: dict[int, float]          # age -> rating change a year
    survive: dict[int, float]        # age -> chance of still being a regular a year later
    var_within: float                # within-player variance of value per 90 (one match)
    sigma_age: float                 # sd of a year's true change in value per 90
    years: int = V.FVI_YEARS
    discount: float = V.FVI_DISCOUNT
    draws: int = V2_DRAWS


def value_v2(proj: np.ndarray, n90: np.ndarray, age: np.ndarray, avail: np.ndarray, P: V2Params,
             seed: int = V2_SEED) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Expected points above replacement over `years` seasons, with a 10-90% band, per player.
    Returns (mean, p10, p90, mean points in the first season). Ages may be nan (taken as 26).
    """
    n = proj.size
    if n == 0:
        z = np.zeros(0)
        return z, z, z, z
    rng = np.random.default_rng(seed)
    S = P.draws
    se = np.sqrt(P.var_within / (np.maximum(n90, 0.0) + V.PROJ_MINUTES / 90.0))
    rate = proj[:, None] + se[:, None] * rng.standard_normal((n, S))
    a = np.clip(np.where(np.isfinite(avail), avail, AVAIL_PRIOR), 0.02, 0.98)
    av = rng.beta(a[:, None] * AVAIL_CONCENTRATION, (1 - a[:, None]) * AVAIL_CONCENTRATION, size=(n, S))
    age0 = np.where(np.isfinite(age), age, 26.0)
    total = np.zeros((n, S))
    first = None
    alive = np.ones(n)
    for t in range(P.years):
        pts = (P.discount ** t) * alive[:, None] * np.maximum(rate, 0.0) * (SEASON_MINUTES * av / 90.0) * P.ppg
        total += pts
        if first is None:
            first = pts.mean(axis=1)
        ai = np.clip(np.floor(age0 + t).astype(int), 17, 40)
        drift = np.array([P.curve.get(int(min(x, 38)), 0.0) for x in ai]) * P.slope
        rate = rate + drift[:, None] + P.sigma_age * rng.standard_normal((n, S))
        alive = alive * np.array([P.survive.get(int(x), 0.0) for x in ai])
    return total.mean(axis=1), np.percentile(total, 10, axis=1), np.percentile(total, 90, axis=1), first


def within_variance(R: V.Rows, vals: np.ndarray, rows: np.ndarray, min_minutes: float = 45.0) -> float:
    """Pooled within-player variance of value per 90 in single matches (lines of min_minutes+), weighted by 90s."""
    sel = rows[R.mins[rows] >= min_minutes]
    if sel.size < 200:
        return 0.09
    v90 = vals[sel].sum(axis=1) / R.mins[sel] * 90.0
    w = R.mins[sel] / 90.0
    pid = R.pid[sel]
    u, inv = np.unique(pid, return_inverse=True)
    sw = np.bincount(inv, w)
    mean = np.bincount(inv, w * v90) / np.maximum(sw, 1e-9)
    dev = v90 - mean[inv]
    cnt = np.bincount(inv)
    keep = cnt[inv] >= 5
    if keep.sum() < 100:
        return 0.09
    # Per-match values weigh by their 90s; the variance of one 90 is about the weighted mean square.
    return float(np.sum(w[keep] * dev[keep] ** 2) / np.sum(w[keep]))


def ageing_sigma(pairs: list[tuple[float, float, float]], curve: dict[int, float], slope: float,
                 rating_match_sd: float = 0.75) -> float:
    """
    The sd of a year's true change in value per 90: the spread of season-to-season rating changes
    around the ageing curve, less what two seasons' sampling noise explains, times the value slope.
    """
    if len(pairs) < 50 or slope <= 0:
        return 0.04
    a = np.array([p[0] for p in pairs])
    d = np.array([p[1] for p in pairs])
    w = np.array([p[2] for p in pairs])
    resid = d - np.array([curve.get(int(min(max(x, 17), 38)), 0.0) for x in a])
    var = float(np.average(resid ** 2, weights=w))
    # w is the harmonic mean of the two seasons' minutes: noise of the difference ~ 2 sd^2 x 90 / w.
    noise = float(np.average(2.0 * rating_match_sd ** 2 * 90.0 / np.maximum(w, 90.0), weights=w))
    true = max(var - noise, 0.2 * var)
    return float(math.sqrt(true) * slope)


# ── the fee model ────────────────────────────────────────────────────────────

def features(v2: np.ndarray, proj: np.ndarray, age: np.ndarray, unit: list[str], seller_xgd: np.ndarray,
             buyer_xgd: np.ndarray, n90: np.ndarray) -> np.ndarray:
    """The fee model's design (FEATURES order); unknown club strengths imputed with a flag."""
    n = v2.size
    X = np.zeros((n, len(FEATURES)))
    ag = np.where(np.isfinite(age), age, 26.0) - 26.0
    s_unk, b_unk = ~np.isfinite(seller_xgd), ~np.isfinite(buyer_xgd)
    X[:, 0] = np.log1p(np.maximum(v2, 0.0))
    X[:, 1] = proj
    X[:, 2] = ag
    X[:, 3] = ag ** 2
    for j, u in enumerate(("CB", "FB", "MID", "ATT", "ST")):
        X[:, 4 + j] = np.array([1.0 if x == u else 0.0 for x in unit])
    X[:, 9] = np.where(s_unk, UNKNOWN_XGD, seller_xgd)
    X[:, 10] = s_unk.astype(float)
    X[:, 11] = np.where(b_unk, UNKNOWN_XGD, buyer_xgd)
    X[:, 12] = b_unk.astype(float)
    X[:, 13] = np.log1p(np.maximum(n90, 0.0))
    return X


@dataclass
class FeeModel:
    mean: np.ndarray
    sd: np.ndarray
    coef: np.ndarray
    intercept: float
    lam: float
    sigma: float                     # residual sd of log fee (cross-validated)
    n: int

    def predict_log(self, X: np.ndarray) -> np.ndarray:
        return self.intercept + ((X - self.mean) / self.sd) @ self.coef

    def to_json(self) -> dict:
        return {"features": list(FEATURES), "mean": [_r(x, 5) for x in self.mean], "sd": [_r(x, 5) for x in self.sd],
                "coef": [_r(x, 5) for x in self.coef], "intercept": _r(self.intercept, 5), "lambda": self.lam,
                "sigma": _r(self.sigma, 4), "n": self.n, "unknown_xgd": UNKNOWN_XGD}


def fit_fee(X: np.ndarray, y: np.ndarray, lam: float) -> FeeModel:
    mean = X.mean(axis=0)
    sd = X.std(axis=0)
    sd = np.where(sd > 1e-9, sd, 1.0)
    Z = (X - mean) / sd
    yc = y - y.mean()
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    coef = np.linalg.solve(A, Z.T @ yc)
    resid = y - (y.mean() + Z @ coef)
    return FeeModel(mean=mean, sd=sd, coef=coef, intercept=float(y.mean()), lam=lam,
                    sigma=float(np.sqrt(np.mean(resid ** 2))), n=int(y.size))


def _folds(groups: np.ndarray, k: int, seed: int = 7) -> np.ndarray:
    u = np.unique(groups)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(u.size)
    fold_of = dict(zip(u[perm].tolist(), (np.arange(u.size) % k).tolist()))
    return np.array([fold_of[g] for g in groups.tolist()])


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 10:
        return None
    ra = np.argsort(np.argsort(a[ok])).astype(float)
    rb = np.argsort(np.argsort(b[ok])).astype(float)
    return round(float(np.corrcoef(ra, rb)[0, 1]), 3)


def _err_stats(y: np.ndarray, p: np.ndarray) -> dict:
    e = np.abs(p - y)
    ss = float(np.sum((y - y.mean()) ** 2))
    return {"n": int(y.size), "mdae_log": _r(np.median(e), 3), "error_factor": _r(math.exp(float(np.median(e))), 2),
            "within_50pct": _r(float(np.mean(np.abs(np.exp(p - y) - 1) <= 0.5)), 3),
            "r2_log": _r(1 - float(np.sum((y - p) ** 2)) / ss, 3) if ss > 0 else None,
            "median_abs_eur": _r(float(np.median(np.abs(np.exp(p) - np.exp(y)))), 0), "spearman": spearman(y, p)}


def fee_baseline(train_y: np.ndarray, train_key: list, test_key: list) -> np.ndarray:
    """Median log fee of the training fees with the same key (buyer tier, unit), else the overall median."""
    med = float(np.median(train_y)) if train_y.size else 0.0
    by: dict[Any, list[float]] = {}
    for k, y in zip(train_key, train_y.tolist()):
        by.setdefault(k, []).append(y)
    return np.array([float(np.median(by[k])) if len(by.get(k, ())) >= 3 else med for k in test_key])


def validate_fee(X: np.ndarray, y: np.ndarray, groups: np.ndarray, days: np.ndarray, key: list,
                 k: int = 5) -> tuple[dict, np.ndarray, float]:
    """
    Out-of-sample checks of the fee model: k folds by player (with the ridge chosen inside
    each fold's training part), and a time split (the latest 30% of fees from the earlier 70%),
    each against the median-by-key baseline and a value-and-age-only model. Returns
    (report, cross-fitted log predictions, chosen ridge).
    """
    n = y.size
    folds = _folds(groups, k)
    # The ridge: the one with the lowest cross-validated error over the folds.
    best, best_lam = None, FEE_LAMBDAS[0]
    for lam in FEE_LAMBDAS:
        pred = np.zeros(n)
        for f in range(k):
            tr, te = folds != f, folds == f
            if tr.sum() < 20 or te.sum() == 0:
                continue
            pred[te] = fit_fee(X[tr], y[tr], lam).predict_log(X[te])
        err = float(np.mean((pred - y) ** 2))
        if best is None or err < best:
            best, best_lam = err, lam
    cv = np.zeros(n)
    base = np.zeros(n)
    simple = np.zeros(n)
    cols = [0, 2, 3]                      # value and age only
    for f in range(k):
        tr, te = folds != f, folds == f
        if tr.sum() < 20 or te.sum() == 0:
            continue
        cv[te] = fit_fee(X[tr], y[tr], best_lam).predict_log(X[te])
        simple[te] = fit_fee(X[tr][:, cols], y[tr], best_lam).predict_log(X[te][:, cols])
        base[te] = fee_baseline(y[tr], [key[i] for i in np.flatnonzero(tr)], [key[i] for i in np.flatnonzero(te)])
    report = {"folds": k, "lambda": best_lam, "n": int(n),
              "cv": {"model": _err_stats(y, cv), "value_age_only": _err_stats(y, simple), "baseline_median": _err_stats(y, base)}}
    order = np.argsort(days, kind="stable")
    cut = int(round(0.7 * n))
    if n - cut >= 20 and cut >= 40:
        tr, te = order[:cut], order[cut:]
        p = fit_fee(X[tr], y[tr], best_lam).predict_log(X[te])
        b = fee_baseline(y[tr], [key[i] for i in tr], [key[i] for i in te])
        report["time_split"] = {"train_until": date.fromordinal(int(days[tr].max())).isoformat(),
                                "test_from": date.fromordinal(int(days[te].min())).isoformat(),
                                "model": _err_stats(y[te], p), "baseline_median": _err_stats(y[te], b)}
    return report, cv, best_lam


# ── deals ────────────────────────────────────────────────────────────────────

def grade_letters(scores: np.ndarray) -> list[str]:
    """Quintiles of the scores among the graded deals: A the top fifth, E the bottom fifth."""
    if scores.size == 0:
        return []
    r = np.argsort(np.argsort(scores)) / max(scores.size - 1, 1)
    return ["A" if x >= 0.8 else "B" if x >= 0.6 else "C" if x >= 0.4 else "D" if x >= 0.2 else "E" for x in r]


def perf_score(gar_post: float, min_post: float, proj_pre: float, share_post: float | None) -> tuple[float, float]:
    """
    (score, weight) of the value delivered since a move: the GAR/90 he has produced at the new
    club, shrunk toward the projection at the time by 900 minutes, against that projection
    (0.1 GAR/90 = one unit), plus how much of the minutes he got against a 60% share; the weight
    grows with the minutes played, to 1 at PERF_MINUTES.
    """
    n90 = min_post / 90.0
    k = V.PROJ_MINUTES / 90.0
    realised = (gar_post + proj_pre * k) / (n90 + k)
    s = (realised - proj_pre) / 0.1
    if share_post is not None and share_post == share_post:
        s += 2.0 * (min(share_post, 1.0) - 0.6)
    return float(s), float(min(min_post / PERF_MINUTES, 1.0))


@dataclass
class TransferContext:
    today: date
    hist: History
    people: dict[str, dict]
    role_of: dict[int, str]
    club_xgd: dict[int, float]                 # pooled expected goal difference per match, by club
    club_league: dict[int, str]                # followed clubs' leagues
    club_name: dict[int, str]
    followed: set[int]                         # clubs with a club file
    league_offset: dict[str, float]
    v2p: V2Params
    tiers: dict[str, str] = field(default_factory=dict)


def age_at(dob: str | None, d: date) -> float:
    if not dob:
        return float("nan")
    try:
        born = date.fromisoformat(str(dob)[:10])
    except ValueError:
        return float("nan")
    return (d - born).days / 365.25


def snapshot(T: TransferContext, pid: int, day: int) -> dict:
    """The player as the model saw him the day before `day`: 12 months of club football before it."""
    mins, gar, apps = T.hist.window(pid, day - V.WINDOW_DAYS, day)
    _, share, n_avail = T.hist.availability(pid, day)
    gar90 = gar / (mins / 90.0) if mins > 0 else 0.0
    proj = (mins / (mins + V.PROJ_MINUTES)) * gar90 if mins > 0 else 0.0
    return {"min": mins, "apps": apps, "gar90": gar90, "proj": proj, "avail": shrunk_availability(share, n_avail),
            "n_avail": n_avail}


def build_deals(T: TransferContext, transfers: list[dict]) -> list[dict]:
    """Every transfer with the model's view at the time and since; fees and fair fees added later."""
    out = []
    for t in transfers:
        pid = t["pid"]
        snap = snapshot(T, pid, t["day"])
        ident = T.people.get(str(pid)) or {}
        role = T.role_of.get(pid) or V.LETTER_ROLE.get(t.get("pos") or "", "MF")
        d = dict(t)
        d.update({"role": role, "unit": V.unit_of_role(role), "age": age_at(ident.get("dob"), t["date"]),
                  "pre_min": snap["min"], "pre_gar90": snap["gar90"], "proj_pre": snap["proj"], "avail_pre": snap["avail"],
                  "from_xgd": T.club_xgd.get(t["from"]) if t["from"] is not None else None,
                  "to_xgd": T.club_xgd.get(t["to"]) if t["to"] is not None else None})
        if t["to"] is not None and t["kind"] != "loan_end":
            m_post, g_post, a_post = T.hist.window(pid, t["day"], T.today.toordinal() + 1, tid=t["to"])
            n_club = T.hist.club_matches(t["to"], t["day"], T.today.toordinal() + 1)
            d.update({"post_min": m_post, "post_gar": g_post, "post_apps": a_post,
                      "post_share": (m_post / (90.0 * n_club)) if n_club > 0 else None, "post_club_matches": n_club})
        out.append(d)
    return out


def club_window_sums(deals: list[dict]) -> dict[int, dict[str, dict]]:
    """club -> window -> {spend, income, n_in, n_out, n_fee_in, n_fee_out, undisclosed_in, undisclosed_out}."""
    out: dict[int, dict[str, dict]] = {}

    def acc(tid, w):
        return out.setdefault(tid, {}).setdefault(w, {"spend": 0.0, "income": 0.0, "n_in": 0, "n_out": 0, "n_fee_in": 0,
                                                       "n_fee_out": 0, "undisclosed_in": 0, "undisclosed_out": 0, "loans_in": 0,
                                                       "loans_out": 0, "free_in": 0, "free_out": 0})
    for d in deals:
        if d["kind"] in ("loan_end", "youth"):
            continue
        for tid, side in ((d["to"], "in"), (d["from"], "out")):
            if tid is None:
                continue
            a = acc(tid, d["window"])
            a["n_" + side] += 1
            if d["kind"] == "fee":
                a["spend" if side == "in" else "income"] += d["fee"]
                a["n_fee_" + side] += 1
            elif d["kind"] == "undisclosed":
                a["undisclosed_" + side] += 1
            elif d["kind"] == "loan":
                a["loans_" + side] += 1
            elif d["kind"] == "free":
                a["free_" + side] += 1
    return out


# ── budgets ──────────────────────────────────────────────────────────────────

BUDGET_FEATURES = ("log_mv_pre", "log_prev_spend", "log_prev_income", "league_offset", "club_xgd")


def _m(x: float) -> float:
    return math.log1p(max(float(x or 0.0), 0.0) / 1e6)


def latest_windows(today: date) -> tuple[str, str, str]:
    """
    (the latest complete summer window, the winter window before it, the next window to open
    or the one open now), as window keys. The summer window counts as complete from September.
    """
    m, y = today.month, today.year
    summer_year = y if m >= 9 else y - 1
    nxt = f"{y}-S" if 5 <= m <= 8 else (f"{y + 1}-W" if m >= 9 else f"{y}-W")
    return f"{summer_year}-S", f"{summer_year}-W", nxt


def fit_budgets(sums: dict[int, dict[str, dict]], clubs: list[int], complete: set[int], mv_pre: dict[int, float | None],
                league_of: dict[int, str], offsets: dict[str, float], xgd: dict[int, float], today: date) -> dict:
    """
    Each followed club's transfer budget for a summer window and for the next window, in EUR,
    with a 25-75% range. The model (ridge on log(1 + gross spend in EUR m)) is fitted across the
    clubs whose recent transfer lists are complete, on the latest summer window, from what was
    known before it: the squad's market value before the window (Sofascore's values, the
    window's signings taken out and its sales put back), the previous window's spend and sales,
    the league's strength and the club's. Validated with five folds by club. The next window
    (a winter one) is the model's figure with the latest window's spend and sales as the
    "previous window", scaled by the winter-to-summer ratio of spending across these clubs.
    """
    summer, winter, nxt = latest_windows(today)
    use_mv = sum(1 for c in clubs if mv_pre.get(c)) >= 0.6 * max(len(clubs), 1)
    cols = [i for i, f in enumerate(BUDGET_FEATURES) if use_mv or f != "log_mv_pre"]

    def feats(c: int, prev: dict) -> list[float]:
        lg = league_of.get(c)
        row = [_m(mv_pre.get(c) or 0.0), _m(prev.get("spend", 0.0)), _m(prev.get("income", 0.0)),
               float(offsets.get(lg, 0.0)) if lg else 0.0, float(xgd.get(c, UNKNOWN_XGD))]
        return [row[i] for i in cols]

    def win(c: int, w: str) -> dict:
        return (sums.get(c) or {}).get(w) or {}

    fit_clubs = [c for c in clubs if c in complete]
    report: dict[str, Any] = {"target_window": summer, "previous_window": winter, "next_window": nxt, "n_clubs": len(fit_clubs),
                              "features": [BUDGET_FEATURES[i] for i in cols], "market_values": use_mv}
    out: dict[int, dict] = {}
    if len(fit_clubs) < 30:
        report["ok"] = False
        report["reason"] = f"{len(fit_clubs)} clubs with complete transfer lists (30 needed)"
        return {"report": report, "clubs": out}
    X = np.array([feats(c, win(c, winter)) for c in fit_clubs])
    y = np.array([_m(win(c, summer).get("spend", 0.0)) for c in fit_clubs])
    folds = _folds(np.array(fit_clubs), 5)
    cv = np.zeros(y.size)
    for f in range(5):
        tr, te = folds != f, folds == f
        if te.any() and tr.sum() >= 10:
            cv[te] = fit_fee(X[tr], y[tr], 3.0).predict_log(X[te])
    res = y - cv
    q10, q25, q75, q90 = (float(x) for x in np.percentile(res, [10, 25, 75, 90]))
    model = fit_fee(X, y, 3.0)
    ss = float(np.sum((y - y.mean()) ** 2))
    tot_s = sum(win(c, summer).get("spend", 0.0) for c in fit_clubs)
    tot_w = sum(win(c, winter).get("spend", 0.0) for c in fit_clubs)
    ratio = min(max((tot_w / tot_s) if tot_s > 0 else 0.35, 0.1), 1.0)
    # The P25-P75 range should hold about half the clubs out of sample.
    inside = float(np.mean((res >= q25) & (res <= q75)))
    report.update({"ok": True, "r2_log_cv": _r(1 - float(np.sum(res ** 2)) / ss, 3) if ss > 0 else None,
                   "spearman_cv": spearman(y, cv), "residual_quantiles": [_r(q10, 3), _r(q25, 3), _r(q75, 3), _r(q90, 3)],
                   "inside_25_75_cv": _r(inside, 3), "winter_ratio": _r(ratio, 3),
                   "coef": [_r(x, 4) for x in model.coef], "mean": [_r(x, 4) for x in model.mean],
                   "sd": [_r(x, 4) for x in model.sd], "intercept": _r(model.intercept, 4)})

    def eur(v: float) -> float:
        return round(max(math.expm1(v), 0.0) * 1e6, -4)

    for c in clubs:
        ps = float(model.predict_log(np.array([feats(c, win(c, winter))]))[0])
        last = win(c, summer)
        pn = float(model.predict_log(np.array([feats(c, {"spend": last.get("spend", 0.0) * ratio,
                                                          "income": last.get("income", 0.0) * ratio})]))[0])
        out[c] = {
            "summer": {"mid": eur(ps), "lo": eur(ps + q25), "hi": eur(ps + q75), "lo80": eur(ps + q10), "hi80": eur(ps + q90)},
            "next": {"window": nxt, "mid": round(eur(pn) * ratio, -4), "lo": round(eur(pn + q25) * ratio, -4),
                     "hi": round(eur(pn + q75) * ratio, -4)},
            "complete": c in complete,
        }
    report["n_budgets"] = len(out)
    return {"report": report, "clubs": out}


# ── the build ────────────────────────────────────────────────────────────────

@dataclass
class TransferResult:
    players: dict[int, dict]                   # pid -> {v2, v2lo, v2hi, v2y1, avail, fee, fee_lo, fee_hi}
    clubs: dict[int, dict]                     # followed club -> {budget, ledger}
    meta: dict
    fee_model: FeeModel | None
    feed: dict                                 # the transfers.json payload


def squad_market_values(squads: dict, archive: dict) -> tuple[dict[str, float], dict[int, dict]]:
    """
    (pid -> Sofascore market value in EUR, club -> {mv, n, n_mv}) from the squads store (each
    squad row's `mv`), falling back to the archive's player profiles for a player without one.
    """
    mv: dict[str, float] = {}
    for pid, rec in (archive.get("players") or {}).items():
        det = rec.get("details") or {}
        if det.get("market_value") and (det.get("market_value_currency") or "EUR") == "EUR":
            mv[str(det.get("id") or pid)] = float(det["market_value"])
    per_club: dict[int, dict] = {}
    for tid, rec in (squads.get("teams") or {}).items():
        for p in rec.get("players") or []:
            if p.get("mv") and not p.get("mvc"):
                mv[str(p["id"])] = float(p["mv"])
    for tid, rec in (squads.get("teams") or {}).items():
        tot, n, k = 0.0, 0, 0
        for p in rec.get("players") or []:
            n += 1
            v = mv.get(str(p.get("id")))
            if v:
                tot += v
                k += 1
        try:
            per_club[int(tid)] = {"mv": tot, "n": n, "n_mv": k, "fetched_at": rec.get("fetched_at")}
        except (TypeError, ValueError):
            continue
    return mv, per_club


def _wlabel(w: str) -> str:
    return window_of(date(int(w[:4]), 7 if w.endswith("S") else 1, 1))[1]


def build_transfers(store: dict, *, R: V.Rows, vals: np.ndarray, repl: dict[str, float], role_of: dict[int, str],
                    player_info: dict[int, dict], people: dict[str, dict], squads: dict, archive: dict,
                    club_xgd: dict[int, float], club_league: dict[int, str], club_name: dict[int, str], followed: set[int],
                    offsets: dict[str, float], ppg_pool: float, curve: dict[int, float], slope: float,
                    survive: dict[int, float], pairs: list, today: date, in_window_rows: np.ndarray) -> TransferResult:
    t_start = datetime.now(timezone.utc)
    repl_row = np.array([repl.get(role_of.get(int(p), "MF"), repl.get("MF", 0.0)) for p in R.pid.tolist()]) if len(R) else np.zeros(0)
    hist = History(R, vals, repl_row)
    v2p = V2Params(ppg=ppg_pool, slope=slope, curve=curve, survive=survive,
                   var_within=within_variance(R, vals, np.flatnonzero(in_window_rows)),
                   sigma_age=ageing_sigma(pairs, curve, slope))
    T = TransferContext(today=today, hist=hist, people=people, role_of=role_of, club_xgd=club_xgd, club_league=club_league,
                        club_name=club_name, followed=followed, league_offset=offsets, v2p=v2p)

    # ── valuation v2 for every rated player ─────────────────────────────────
    pids = [p for p, info in player_info.items() if info.get("min", 0) > 0 and info.get("proj") is not None]
    d1 = today.toordinal() + 1
    av = [hist.availability(p, d1) for p in pids]
    avail = np.array([shrunk_availability(s, n) for _, s, n in av])
    proj = np.array([player_info[p]["proj"] for p in pids], dtype=float)
    n90 = np.array([player_info[p]["min"] / 90.0 for p in pids], dtype=float)
    age = np.array([player_info[p]["age"] if player_info[p]["age"] is not None else np.nan for p in pids], dtype=float)
    v2, v2lo, v2hi, v2y1 = value_v2(proj, n90, age, avail, v2p)
    players: dict[int, dict] = {}
    for i, p in enumerate(pids):
        players[p] = {"v2": float(v2[i]), "v2lo": float(v2lo[i]), "v2hi": float(v2hi[i]), "v2y1": float(v2y1[i]), "avail": float(avail[i])}

    # ── transfers and the value at the time ─────────────────────────────────
    all_t = normalise(store, today)
    lo_day = today.toordinal() - FEED_DAYS
    keep = [t for t in all_t if t["day"] >= lo_day or t["kind"] == "fee"]
    deals = build_deals(T, keep)
    if deals:
        pre_v2 = value_v2(np.array([d["proj_pre"] for d in deals], dtype=float), np.array([d["pre_min"] / 90.0 for d in deals], dtype=float),
                          np.array([d["age"] for d in deals], dtype=float), np.array([d["avail_pre"] for d in deals], dtype=float), v2p)[0]
        for d, v in zip(deals, pre_v2.tolist()):
            d["v2_pre"] = v

    # ── the fee model ───────────────────────────────────────────────────────
    def xgd_or_nan(t):
        return club_xgd.get(t) if t is not None and club_xgd.get(t) is not None else np.nan

    def design(ds: list[dict]) -> np.ndarray:
        return features(np.array([d["v2_pre"] for d in ds]), np.array([d["proj_pre"] for d in ds]), np.array([d["age"] for d in ds]),
                        [d["unit"] for d in ds], np.array([xgd_or_nan(d["from"]) for d in ds], dtype=float),
                        np.array([xgd_or_nan(d["to"]) for d in ds], dtype=float), np.array([d["pre_min"] / 90.0 for d in ds]))

    train = [d for d in deals if d["kind"] == "fee" and d["fee"] >= 100_000 and d["pre_min"] >= 450 and d["age"] == d["age"]]
    fee_meta: dict[str, Any] = {"n_fees": sum(1 for d in deals if d["kind"] == "fee"), "n_with_value": len(train), "min_fit": MIN_FEE_FIT}
    model = None
    if len(train) >= MIN_FEE_FIT:
        X = design(train)
        y = np.log(np.array([d["fee"] for d in train]))
        key = [(V.LEAGUE_TIERS.get(club_league.get(d["to"], ""), "other"), d["unit"]) for d in train]
        report, cv, lam = validate_fee(X, y, np.array([d["pid"] for d in train]), np.array([d["day"] for d in train]), key)
        model = fit_fee(X, y, lam)
        model.sigma = float(np.sqrt(np.mean((cv - y) ** 2)))
        for d, p in zip(train, cv.tolist()):
            d["fair_pre_log"] = p
        fee_meta.update({"fitted": True, "validation": report, "model": model.to_json()})
    else:
        fee_meta.update({"fitted": False,
                         "reason": f"{len(train)} fees with a value at the time ({MIN_FEE_FIT} needed); the fair value index stays"})

    if model is not None and deals:
        rest = [d for d in deals if "fair_pre_log" not in d]
        if rest:
            for d, p in zip(rest, model.predict_log(design(rest)).tolist()):
                d["fair_pre_log"] = p
        for d in deals:
            d["fair_pre"] = math.exp(d["fair_pre_log"]) if d["pre_min"] >= 450 else None

    # Every rated player's fair fee now, to a buyer like his own club; the check against Sofascore.
    mv_all, club_mv = squad_market_values(squads, archive)
    if model is not None and pids:
        own = np.array([xgd_or_nan(player_info[p].get("tid")) for p in pids], dtype=float)
        lp = model.predict_log(features(v2, proj, age, [V.unit_of_role(player_info[p]["role"]) for p in pids], own, own, n90))
        z = 0.6745 * model.sigma
        for i, p in enumerate(pids):
            if player_info[p]["min"] >= 450:
                players[p].update({"fee": math.exp(lp[i]), "fee_lo": math.exp(lp[i] - z), "fee_hi": math.exp(lp[i] + z)})
        both = [(players[p]["fee"], mv_all[str(p)]) for p in pids if "fee" in players[p] and mv_all.get(str(p))]
        fee_meta["market_value_check"] = {"n": len(both), "spearman_fair_fee": spearman([a for a, _ in both], [b for _, b in both])}
    both_v2 = [(players[p]["v2"], mv_all[str(p)]) for p in pids if mv_all.get(str(p)) and player_info[p]["min"] >= 450]
    fee_meta["market_value_check_v2"] = {"n": len(both_v2), "spearman_v2": spearman([a for a, _ in both_v2], [b for _, b in both_v2])}

    # ── grades ──────────────────────────────────────────────────────────────
    g_lo = today.toordinal() - GRADE_WINDOW_DAYS
    graded_b, graded_s = [], []
    for d in deals:
        if d["day"] < g_lo or d["kind"] in ("loan_end", "youth"):
            continue
        fair = d.get("fair_pre")
        price = None
        if fair:
            # The fair fee is only as good as the evidence before the move: full weight from PRICE_MINUTES.
            conf = min(d["pre_min"] / PRICE_MINUTES, 1.0)
            if d["kind"] == "fee":
                price = conf * float(np.clip(math.log(fair / d["fee"]), -2.0, 2.0))
            elif d["kind"] == "free":
                price = conf * float(np.clip(math.log((fair + FREE_REF_EUR) / FREE_REF_EUR), 0.0, 2.0))
        perf, w = None, 0.0
        if d.get("post_min") is not None and d["pre_min"] >= 450:
            perf, w = perf_score(d["post_gar"], d["post_min"], d["proj_pre"], d.get("post_share"))
        elif d.get("post_min") is not None and d["post_min"] >= 450:
            # No value before the move (from a league we do not follow): the minutes since, on their own.
            perf, w = perf_score(d["post_gar"], d["post_min"], 0.0, d.get("post_share"))
        d["perf"], d["perf_w"], d["price"] = perf, w, price
        b = None
        if d["to"] is not None:
            if price is not None:
                b = price + (w * perf if perf is not None else 0.0)
            elif perf is not None and w >= 0.25:
                b = w * perf
        sc = None
        if d["from"] is not None and d["kind"] in ("fee", "free") and price is not None:
            sc = -price * (1.0 if d["kind"] == "fee" else 0.5) - (0.5 * w * perf if perf is not None else 0.0)
        d["b_score"], d["s_score"] = b, sc
        if b is not None:
            graded_b.append(d)
        if sc is not None:
            graded_s.append(d)
    for lst, key, gk in ((graded_b, "b_score", "b_grade"), (graded_s, "s_score", "s_grade")):
        for d, g in zip(lst, grade_letters(np.array([d[key] for d in lst]))):
            d[gk] = g
    for d in deals:
        if d.get("b_score") is not None and d.get("s_score") is not None:
            diff = d["b_score"] - d["s_score"]
            d["winner"] = "buyer" if diff > 0.3 else "seller" if diff < -0.3 else "even"

    # ── the feed, best and worst, windows by league ─────────────────────────
    feed_deals = [d for d in deals if d["day"] >= lo_day and ((d["to"] in followed) or (d["from"] in followed))]
    feed_deals.sort(key=lambda d: (-d["day"], -(d["fee"] or 0)))
    f_fields = ["key", "date", "pid", "name", "age", "role", "from", "from_name", "to", "to_name", "kind", "fee", "fee_text", "window",
                "fair", "pre_min", "proj_pre", "post_min", "post_gar90", "post_share", "b_grade", "b_score", "s_grade", "s_score", "winner",
                "from_league", "to_league"]

    def row(d):
        pm = d.get("post_min")
        return [d["key"], d["date"].isoformat(), str(d["pid"]), d["name"], int(d["age"]) if d["age"] == d["age"] else None, d["role"],
                d["from"], d["from_name"], d["to"], d["to_name"], d["kind"], _r(d["fee"], 0), d.get("fee_text"), d["window"],
                _r(d.get("fair_pre"), -4), int(round(d["pre_min"])), _r(d["proj_pre"]), int(round(pm)) if pm is not None else None,
                _r(d["post_gar"] / (pm / 90.0)) if pm else None, _r(d.get("post_share"), 2), d.get("b_grade"), _r(d.get("b_score"), 2),
                d.get("s_grade"), _r(d.get("s_score"), 2), d.get("winner"), club_league.get(d["from"]) if d["from"] is not None else None,
                club_league.get(d["to"]) if d["to"] is not None else None]

    year = [d for d in graded_b if d["kind"] in ("fee", "free") and d["to"] in followed]
    best = [d["key"] for d in sorted(year, key=lambda d: -d["b_score"])[:20]]
    worst = [d["key"] for d in sorted(year, key=lambda d: d["b_score"])[:20]]
    sums = club_window_sums(deals)
    windows_by_league: dict[str, dict[str, dict]] = {}
    for lg in sorted(set(club_league.get(c) for c in followed) - {None}):
        clubs_lg = {c for c in followed if club_league.get(c) == lg}
        wk: dict[str, dict] = {}
        for c in clubs_lg:
            for w, a in (sums.get(c) or {}).items():
                x = wk.setdefault(w, {"spend": 0.0, "income": 0.0, "n_in": 0, "n_fee_in": 0, "undisclosed_in": 0, "loans_in": 0,
                                      "free_in": 0, "_clubs": {}})
                for k_ in ("spend", "income", "n_in", "n_fee_in", "undisclosed_in", "loans_in", "free_in"):
                    x[k_] += a.get(k_, 0)
                x["_clubs"][c] = (a.get("spend", 0.0), a.get("income", 0.0))
        for w, x in wk.items():
            ds = [d for d in deals if d["window"] == w and d["to"] in clubs_lg and d["kind"] in ("fee", "free", "loan")]
            top = sorted([d for d in ds if d["kind"] == "fee"], key=lambda d: -d["fee"])[:5]
            bestv = sorted([d for d in ds if d.get("b_score") is not None], key=lambda d: -d["b_score"])[:5]
            cl = x.pop("_clubs")
            x.update({"net": _r(x["spend"] - x["income"], 0), "spend": _r(x["spend"], 0), "income": _r(x["income"], 0),
                      "top": [d["key"] for d in top], "best": [d["key"] for d in bestv], "label": _wlabel(w),
                      "spenders": [[c, _r(s_, 0), _r(i_, 0)] for c, (s_, i_) in sorted(cl.items(), key=lambda kv: -(kv[1][0] - kv[1][1]))[:3]],
                      "sellers": [[c, _r(s_, 0), _r(i_, 0)] for c, (s_, i_) in sorted(cl.items(), key=lambda kv: -kv[1][1])[:3]]})
        windows_by_league[lg] = wk
    # Deals that best/worst/windows refer to but the feed's filter left out still need a row.
    ref = set(best) | set(worst) | {k_ for wk in windows_by_league.values() for x in wk.values() for k_ in x["top"] + x["best"]}
    have = {d["key"] for d in feed_deals}
    feed_rows = [row(d) for d in feed_deals] + [row(d) for d in deals if d["key"] in ref and d["key"] not in have]

    # ── budgets ─────────────────────────────────────────────────────────────
    complete = {int(t) for t in (store.get("teams") or {}) if str(t).isdigit()}
    summer, winter, nxt = latest_windows(today)
    moved_in: dict[Any, list[int]] = {}
    moved_out: dict[Any, list[int]] = {}
    for d in deals:
        if d["window"] == summer and d["kind"] in ("fee", "free", "loan"):
            moved_in.setdefault(d["to"], []).append(d["pid"])
            moved_out.setdefault(d["from"], []).append(d["pid"])
    mv_pre: dict[int, float | None] = {}
    for c in followed:
        cm = club_mv.get(c)
        if not cm or cm["n"] == 0 or cm["n_mv"] < 0.6 * cm["n"]:
            mv_pre[c] = None
            continue
        squad_ids = {str(p.get("id")) for p in ((squads.get("teams") or {}).get(str(c)) or {}).get("players") or []}
        adj = cm["mv"] - sum(mv_all.get(str(p), 0.0) for p in moved_in.get(c, []) if str(p) in squad_ids) \
            + sum(mv_all.get(str(p), 0.0) for p in moved_out.get(c, []) if str(p) not in squad_ids)
        mv_pre[c] = max(adj, 0.0)
    budgets = fit_budgets(sums, sorted(followed), complete, mv_pre, club_league, offsets, club_xgd, today)

    # ── ledgers ─────────────────────────────────────────────────────────────
    def season_gar(pid: int) -> float:
        info = player_info.get(pid) or {}
        pl = players.get(pid) or {}
        return max(info.get("proj") or 0.0, 0.0) * pl.get("avail", AVAIL_PRIOR) * SEASON_MINUTES / 90.0

    def lrow(d: dict, side: str) -> dict:
        pm = d.get("post_min")
        return {"key": d["key"], "date": d["date"].isoformat(), "pid": str(d["pid"]), "name": d["name"], "role": d["role"],
                "age": int(d["age"]) if d["age"] == d["age"] else None, "club": d["from"] if side == "in" else d["to"],
                "club_name": d["from_name"] if side == "in" else d["to_name"], "kind": d["kind"], "fee": _r(d["fee"], 0),
                "fee_text": d.get("fee_text"), "fair": _r(d.get("fair_pre"), -4),
                "grade": d.get("b_grade") if side == "in" else d.get("s_grade"),
                "post_min": int(round(pm)) if pm is not None else None,
                "post_gar90": _r(d["post_gar"] / (pm / 90.0)) if pm else None, "proj_pre": _r(d["proj_pre"])}

    by_club: dict[int, list[dict]] = {}
    for d in deals:
        if d["day"] < lo_day or d["kind"] == "youth":
            continue
        for c in {d["to"], d["from"]} & followed:
            by_club.setdefault(c, []).append(d)
    clubs: dict[int, dict] = {}
    for c in followed:
        mine = sorted(by_club.get(c, []), key=lambda d: -d["day"])
        last12 = [d for d in mine if d["day"] >= g_lo]
        ins = [d for d in last12 if d["to"] == c]
        outs = [d for d in last12 if d["from"] == c]
        spend = sum(d["fee"] for d in ins if d["kind"] == "fee")
        income = sum(d["fee"] for d in outs if d["kind"] == "fee")
        fair_in = sum(d.get("fair_pre") or 0.0 for d in ins if d["kind"] in ("fee", "free"))
        fair_out = sum(d.get("fair_pre") or 0.0 for d in outs if d["kind"] in ("fee", "free"))
        wins = []
        for w in sorted((sums.get(c) or {}).keys(), reverse=True)[:8]:
            a = sums[c][w]
            wins.append({"window": w, "label": _wlabel(w), "spend": _r(a["spend"], 0), "income": _r(a["income"], 0),
                         "net": _r(a["spend"] - a["income"], 0), "n_in": a["n_in"], "n_out": a["n_out"],
                         "undisclosed": a["undisclosed_in"] + a["undisclosed_out"], "loans_in": a["loans_in"], "free_in": a["free_in"],
                         "complete": c in complete and w in (summer, winter)})
        cmv = club_mv.get(c) or {}
        bud = budgets["clubs"].get(c)
        clubs[c] = {
            "ledger": {"in": [lrow(d, "in") for d in mine if d["to"] == c and d["kind"] != "loan_end"][:40],
                       "out": [lrow(d, "out") for d in mine if d["from"] == c and d["kind"] != "loan_end"][:40],
                       "returns": [lrow(d, "in") for d in mine if d["to"] == c and d["kind"] == "loan_end"][:20],
                       "windows": wins,
                       "last12": {"spend": _r(spend, 0), "income": _r(income, 0), "net": _r(spend - income, 0),
                                  "fair_in": _r(fair_in, -4), "fair_out": _r(fair_out, -4),
                                  "value_added": _r((fair_in - spend) - (fair_out - income), -4) if model is not None else None,
                                  "gar_in": _r(sum(season_gar(d["pid"]) for d in ins if d["kind"] in ("fee", "free", "loan")), 2),
                                  "gar_out": _r(sum(season_gar(d["pid"]) for d in outs if d["kind"] in ("fee", "free", "loan")), 2)},
                       "fetched": ((store.get("teams") or {}).get(str(c)) or {}).get("fetched_at")},
            "budget": ({**(bud or {}), "squad_mv": _r(cmv.get("mv"), -4) if cmv.get("n_mv") else None, "squad_mv_n": cmv.get("n_mv"),
                        "squad_n": cmv.get("n"), "mv_pre": _r(mv_pre.get(c), -4)} if (bud or cmv) else None),
        }

    kinds: dict[str, int] = {}
    for t in all_t:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    coverage = {
        "transfers": len(all_t), "by_kind": kinds,
        "clubs_fetched": len(complete & followed), "clubs_followed": len(followed), "clubs_fetched_all": len(complete),
        "players_fetched": len(store.get("players") or {}),
        "first_date": all_t[0]["date"].isoformat() if all_t else None, "last_date": all_t[-1]["date"].isoformat() if all_t else None,
        "squads_with_mv": sum(1 for c in followed if (club_mv.get(c) or {}).get("n_mv")),
        "players_with_mv": len(mv_all), "store_updated": (store.get("meta") or {}).get("updated_at"),
    }
    meta = {"fee": fee_meta,
            "v2": {"draws": v2p.draws, "years": v2p.years, "discount": v2p.discount, "season_minutes": SEASON_MINUTES,
                   "var_within": _r(v2p.var_within, 4), "sigma_age": _r(v2p.sigma_age, 4), "avail_prior": AVAIL_PRIOR,
                   "avail_prior_matches": AVAIL_PRIOR_MATCHES, "avail_concentration": AVAIL_CONCENTRATION, "ppg": _r(ppg_pool, 4)},
            "budgets": budgets["report"], "coverage": coverage,
            "grades": {"n_buyer": len(graded_b), "n_seller": len(graded_s), "window_days": GRADE_WINDOW_DAYS,
                       "perf_minutes": PERF_MINUTES, "price_minutes": PRICE_MINUTES, "free_ref": FREE_REF_EUR},
            "runtime_s": round((datetime.now(timezone.utc) - t_start).total_seconds(), 1)}
    feed = {"fields": f_fields, "rows": feed_rows, "best": best, "worst": worst, "windows": windows_by_league,
            "coverage": coverage, "fee_fitted": model is not None, "today": today.isoformat(), "next_window": nxt,
            "latest_summer": summer}
    logger.info("transfers: %d stored, %d in the feed, %d fees with a value at the time (model %s), %d buyer grades, budgets %s; %.1fs",
                len(all_t), len(feed_rows), len(train), "fitted" if model else "not fitted", len(graded_b),
                "fitted" if budgets["report"].get("ok") else "not fitted", meta["runtime_s"])
    return TransferResult(players=players, clubs=clubs, meta=meta, fee_model=model, feed=feed)
