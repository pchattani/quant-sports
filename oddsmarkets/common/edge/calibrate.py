"""
Fair probabilities and walk-forward shrinkage of the model toward the market.

`prepare(df)` adds the derived columns every later step uses:
    fair_dec / fair_close     de-vigged with ONE method (default power) wherever the market group is complete;
                              else the file's own fair_p_* column; else 1/price (vig left in, flagged)
    fair_dec_src              "recomputed" | "supplied" | "vig_incl"
    excl_key                  mutually exclusive market group (event, market, |line|, price source, decision time)
    settle_at                 when the result is known (settle_time, else start_time + settle_lag; futures: the
                              last start in that sport-season + settle_lag)
    profit_unit               settlement profit per unit stake at price_dec (pushes / half results handled)
    clv                       fair_close * price_dec - 1: expected return of the bet if the close is the truth
    beat_close                price_dec > price_close (got a better number than the close)
    edge_raw                  model_p * price_dec - 1

`walk_forward_shrink(df)` estimates, on past settled data only, how much of the model-market gap is real:

    logit q = a + b * logit(m) + c * (logit(model) - logit(m))           m = fair_dec

a ridge-penalised logistic regression with prior (a, b, c) = (0, 1, 0), i.e. "the market is right". c is the
blend weight: q's logit is (1-c) parts market and c parts model when a = 0, b = 1. b != 1 or a != 0 lets the fit
also correct a miscalibrated market (favourite-longshot bias). The prior is worth `k_prior` pseudo-bets, so a
short history leaves q at the market (no edge, no bets) and a long one lets the data speak. Fitted hierarchically:
sport level with the market prior, then each market with the sport fit as its prior. Refitted every month on
rows settled before the month starts; applied to the month's decisions. Shrunk probabilities are renormalised
within complete exclusive groups, and `edge = q * price_dec - 1`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .devig import DEFAULT_METHOD, as_key, fair_from_prices, group_keys, market_family
from .schema import settle_profit

EPS = 1e-6
# futures that resolve at season end (when no settle_time is given); other futures (a race winner) settle at
# start_time + settle_lag like any event
SEASON_LONG = ("season|title|champion|outright|league_winner|relegat|top_4|top4|mvp|award|wins|division|playoff|"
               "conference|super_bowl|superbowl|pennant|world_series|finals|make_|promot")
IN_SAMPLE_SPLITS = ("dev", "train", "tune", "tuning", "in_sample", "insample", "fit")
# Price sources that are statistics over books, not a price anyone quoted: never bet in the bankroll simulation
# or the headline tests (they still appear in the by-price-source breakdown). "max" is the best price across books
# after the fact (known to be optimistic: stale outliers), "avg"/"mean"/"median" were never on offer.
AGGREGATE_SRC = r"(?:^|[_-])(?:avg|max|mean|median|consensus|best)(?:[_-]|$)"


def to_seconds(s: pd.Series) -> np.ndarray:
    """UTC datetimes -> float epoch seconds (independent of the pandas datetime resolution)."""
    t = pd.to_datetime(s, utc=True)
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy(float)


def logit(p):
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def expit(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


def prepare(df: pd.DataFrame, method: str = DEFAULT_METHOD, settle_lag_hours: float = 24.0) -> pd.DataFrame:
    d = df.copy()
    d["excl_key"] = group_keys(d, with_decision=True)
    fam = d["market"].map(market_family)
    line = as_key(d["line"].abs().where(fam.eq("spread"), d["line"]).round(4))
    d["outcome_key"] = as_key(d["event_id"]) + "|" + as_key(d["market"]) + "|" + line
    fair, ok = fair_from_prices(d, "price_dec", d["excl_key"], method)
    d["fair_dec"] = fair
    d["fair_dec_src"] = np.where(ok, "recomputed", "")
    sup = ~ok & d["fair_p_decision"].notna()
    d.loc[sup, "fair_dec"] = d.loc[sup, "fair_p_decision"]
    d.loc[sup, "fair_dec_src"] = "supplied"
    rest = d["fair_dec"].isna()
    d.loc[rest, "fair_dec"] = 1.0 / d.loc[rest, "price_dec"]
    d.loc[rest, "fair_dec_src"] = "vig_incl"
    d["group_complete"] = ok.to_numpy()

    if d["price_close"].notna().any():
        has = d["price_close"].notna()
        fc, okc = fair_from_prices(d[has], "price_close", d.loc[has, "excl_key"], method)
        d["fair_close"] = np.nan
        d.loc[has, "fair_close"] = fc
    else:
        d["fair_close"] = np.nan
    d["fair_close"] = d["fair_close"].where(d["fair_close"].notna(), d["fair_p_close"])

    lag = pd.Timedelta(hours=settle_lag_hours)
    settle = d["settle_time"].copy() if "settle_time" in d else pd.Series(pd.NaT, index=d.index)
    settle = pd.to_datetime(settle, utc=True)
    fut = d["market"].map(market_family).eq("future") & d["market"].str.lower().str.contains(SEASON_LONG)
    if fut.any():
        nonfut = d[~fut]
        season_end = (nonfut.groupby(["sport", "season"])["start_time"].max() if len(nonfut)
                      else pd.Series(dtype="datetime64[ns, UTC]"))
        key = list(zip(d.loc[fut, "sport"], d.loc[fut, "season"]))
        ends = pd.Series([season_end.get(k, pd.NaT) for k in key], index=d.index[fut])
        ends = pd.to_datetime(ends, utc=True)
        fallback = d.loc[fut, "start_time"]
        settle.loc[fut] = settle.loc[fut].where(settle.loc[fut].notna(),
                                                ends.where(ends.notna() & (ends > fallback), fallback) + lag)
    settle = settle.where(settle.notna(), d["start_time"] + lag)
    d["settle_at"] = settle

    # fees folded into the price after de-vigging (the market's fair probability does not include our fee)
    d["price_gross"] = d["price_dec"]
    if "fee" in d and pd.to_numeric(d["fee"], errors="coerce").fillna(0).gt(0).any():
        fee = pd.to_numeric(d["fee"], errors="coerce").fillna(0.0).clip(lower=0.0)
        d["price_dec"] = 1.0 / (1.0 / d["price_gross"] + fee)
    d["profit_unit"] = settle_profit(d["outcome"], d["price_dec"])
    d["clv"] = d["fair_close"] * d["price_dec"] - 1.0
    d["beat_close"] = np.where(d["price_close"].notna(), (d["price_gross"] > d["price_close"] + 1e-9).astype(float),
                               np.nan)
    if "line_close" in d:
        # a closing price for a different line is not comparable: no CLV for those rows
        lc = pd.to_numeric(d["line_close"], errors="coerce")
        moved_line = lc.notna() & d["line"].notna() & ((lc - d["line"]).abs() > 1e-9)
        d.loc[moved_line, ["clv", "beat_close"]] = np.nan
        d["line_moved"] = moved_line
    d["edge_raw"] = d["model_p"] * d["price_dec"] - 1.0
    d["lead_h"] = (d["start_time"] - d["decision_time"]).dt.total_seconds() / 3600.0
    # out-of-sample, executable rows: the only ones bet and scored
    in_test = pd.Series(True, index=d.index)
    if "split" in d:
        sp = d["split"].astype(object).where(d["split"].notna(), "").astype(str).str.lower()
        in_test &= ~sp.isin(IN_SAMPLE_SPLITS)
    if "quality_ok" in d:
        in_test &= d["quality_ok"].astype(object).where(d["quality_ok"].notna(), True).astype(bool)
    d["executable"] = ~d["price_src"].str.lower().str.contains(AGGREGATE_SRC, regex=True)
    d["oos"] = in_test
    d["in_test"] = in_test & d["executable"]
    return d


# ------------------------------------------------------------------------------------------- the logistic fit


@dataclass
class BlendFit:
    theta: np.ndarray        # (a, b, c)
    se: np.ndarray
    n: int

    @property
    def weight(self) -> float:
        return float(self.theta[2])


PRIOR = np.array([0.0, 1.0, 0.0])


def prior_precision(X: np.ndarray, k_prior: float | np.ndarray) -> np.ndarray:
    """Diagonal prior precision worth `k_prior` pseudo-observations per coefficient:
    lambda_j = k_prior_j * 0.25 * mean(x_j^2) (the Fisher information of k_prior average rows at p = 1/2)."""
    return np.asarray(k_prior, dtype=float) * 0.25 * np.maximum((np.asarray(X, float) ** 2).mean(axis=0), 1e-4)


def fit_logit_prior(X: np.ndarray, y: np.ndarray, prior: np.ndarray, lam: np.ndarray, w: np.ndarray | None = None,
                    iters: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """
    MAP logistic regression of y on the design X (n x K) under a Gaussian prior N(prior, diag(1/lam)) or, when
    `lam` is a K x K matrix, the prior precision matrix `lam`. Damped Newton-Raphson. Returns (theta, H) where H is
    the posterior precision at the last iterate (its inverse is the Laplace covariance). `fit_blend` is the K = 3
    case [1, logit market, model gap] with the "market is right" prior; fund/alpha uses K = 2 + factors.
    """
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    prior = np.asarray(prior, dtype=float)
    K = X.shape[1]
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    L = np.asarray(lam, dtype=float)
    Lm = L if L.ndim == 2 else np.diag(L)
    th = prior.copy()
    H = np.eye(K)
    for _ in range(iters):
        p = expit(X @ th)
        g = X.T @ (w * (y - p)) - Lm @ (th - prior)
        H = (X * (w * p * (1 - p))[:, None]).T @ X + Lm
        step = np.linalg.solve(H, g)
        # damped step keeps Newton stable on separable / tiny samples
        mx = np.max(np.abs(step))
        if mx > 2.0:
            step *= 2.0 / mx
        th = th + step
        if mx < 1e-9:
            break
    return th, H


def fit_blend(lm: np.ndarray, d: np.ndarray, y: np.ndarray, prior: np.ndarray = PRIOR, k_prior: float = 200.0,
              w: np.ndarray | None = None, iters: int = 50) -> BlendFit:
    """
    Ridge logistic regression of y on [1, lm, d] with a Gaussian prior centred on `prior` worth `k_prior`
    pseudo-observations: lambda_j = k_prior * 0.25 * mean(x_j^2) (the Fisher information of k_prior average rows).
    Newton-Raphson; returns the MAP estimate and its Laplace standard errors. (The K-feature form is
    `fit_logit_prior`.)
    """
    n = len(y)
    prior = np.asarray(prior, dtype=float)
    if n == 0:
        return BlendFit(prior.copy(), np.full(3, np.inf), 0)
    X = np.column_stack([np.ones(n), lm, d])
    th, H = fit_logit_prior(X, y, prior, prior_precision(X, k_prior), w, iters)
    try:
        se = np.sqrt(np.clip(np.diag(np.linalg.inv(H)), 0, None))
    except np.linalg.LinAlgError:
        se = np.full(3, np.nan)
    return BlendFit(th, se, n)


def apply_blend(theta: np.ndarray, m: np.ndarray, model: np.ndarray) -> np.ndarray:
    lm = logit(m)
    return expit(theta[0] + theta[1] * lm + theta[2] * (logit(model) - lm))


def _renorm(d: pd.DataFrame, col: str) -> pd.Series:
    q = d[col].copy()
    ok = d["group_complete"].astype(bool)
    if ok.any():
        s = q[ok].groupby(d.loc[ok, "excl_key"]).transform("sum")
        q.loc[ok] = q[ok] / s
    return q


def walk_forward_shrink(d: pd.DataFrame, k_prior: float = 200.0, min_train: int = 200, freq: str = "MS",
                        level: tuple = ("sport", "market")) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Adds q (shrunk probability), edge (q*price-1), warmup (True where too little history to fit: q = market),
    w_model (blend weight used). Returns (frame, fit history). Uses only rows with settle_at < refit time.
    """
    d = d.reset_index(drop=True)
    hist = []
    binary = d["outcome"].isin([0.0, 1.0]).to_numpy()
    lm_all = logit(d["fair_dec"].to_numpy())
    dd_all = logit(d["model_p"].to_numpy()) - lm_all
    y_all = d["outcome"].to_numpy(float)
    fair = d["fair_dec"].to_numpy(float)
    model = d["model_p"].to_numpy(float)
    dec_s = to_seconds(d["decision_time"])
    set_s = to_seconds(d["settle_at"])
    q = np.full(len(d), np.nan)
    wm = np.full(len(d), np.nan)
    warm = np.ones(len(d), dtype=bool)
    sub_all = d[level[1]].astype(str).to_numpy() if len(level) > 1 else np.full(len(d), "all")
    sports = d["sport"].to_numpy()
    for sport in pd.unique(sports):
        idx = np.flatnonzero(sports == sport)
        dec = dec_s[idx]
        first = pd.Timestamp(dec.min(), unit="s", tz="UTC")
        last = pd.Timestamp(dec.max(), unit="s", tz="UTC")
        starts = pd.date_range(first.normalize().replace(day=1), last, freq=freq)
        bounds = [int(t.timestamp()) for t in starts] + [int(dec.max()) + 1]
        bin_s, settle, sub = binary[idx], set_s[idx], sub_all[idx]
        for t0, t1 in zip(bounds[:-1], bounds[1:]):
            target = (dec >= t0) & (dec < t1)
            if not target.any():
                continue
            month = pd.Timestamp(t0, unit="s", tz="UTC")
            train = bin_s & (settle < t0)
            n_tr = int(train.sum())
            if n_tr < min_train:
                ti = idx[target]
                q[ti] = fair[ti]
                wm[ti] = 0.0
                hist.append({"sport": sport, "segment": "*", "month": month, "n_train": n_tr, "a": 0.0, "b": 1.0,
                             "c": 0.0, "se_c": np.nan, "warmup": True})
                continue
            gi = idx[train]
            fs = fit_blend(lm_all[gi], dd_all[gi], y_all[gi], PRIOR, k_prior)
            hist.append({"sport": sport, "segment": "*", "month": month, "n_train": n_tr, "a": fs.theta[0],
                         "b": fs.theta[1], "c": fs.theta[2], "se_c": fs.se[2], "warmup": False})
            for seg in np.unique(sub[target]):
                tmask = target & (sub == seg)
                gim = idx[train & (sub == seg)]
                fm = fit_blend(lm_all[gim], dd_all[gim], y_all[gim], fs.theta, k_prior) if len(gim) else fs
                ti = idx[tmask]
                q[ti] = apply_blend(fm.theta, fair[ti], model[ti])
                wm[ti] = fm.theta[2]
                warm[ti] = False
                hist.append({"sport": sport, "segment": seg, "month": month, "n_train": len(gim),
                             "a": fm.theta[0], "b": fm.theta[1], "c": fm.theta[2], "se_c": fm.se[2],
                             "warmup": False})
    d["q"] = q
    d["w_model"] = wm
    d["warmup"] = warm
    d["warm_fit"] = warm
    if "in_test" in d:
        d["warmup"] = d["warmup"] | ~d["in_test"].astype(bool)
    d["q"] = _renorm(d, "q")
    d["edge"] = d["q"] * d["price_dec"] - 1.0
    return d, pd.DataFrame(hist)
