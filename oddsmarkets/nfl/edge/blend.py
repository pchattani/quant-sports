"""
Market-blend models (EDGE_PROTOCOL 2.3: a price may be an input, judged only against later prices or outcomes).

residual_close   at the close: logit p = logit(p_market) + b * (logit(p_model) - logit(p_market)), b refitted every
                 season on earlier seasons (ridge-free logistic, one parameter + intercept). b > 0 out of sample
                 means the model adds to the closing price; b ~ 0 means it does not. Judged on outcomes.

move_model       at the open: the predicted close line  C^ = open + b * (model line - open), and the same for totals.
                 b is learnt where history is long: on 2006 -> seasons before the test season, with a PSEUDO-open
                 (the market-implied line from earlier closes, mratings.py; QB-adjusted) standing in for the opener,
                 i.e. regress (close - pseudo open) on (model - pseudo open). Applied to the real ESPN opener, the
                 model's probability for any selection is the market distribution centred on C^ (sd sigma_m, key
                 numbers), and a bet is placed only when that beats the opening price. Judged on CLV.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import expit, logit

from oddsmarkets.nfl.edge import market as MK
from oddsmarkets.nfl.models import game as GM

EPS = 1e-4


def _logit(p):
    return logit(np.clip(np.asarray(p, float), EPS, 1 - EPS))


def _fit_logistic(x, off, y, iters=50):
    """y ~ Bernoulli(expit(off + a + b x)); Newton steps."""
    a, b = 0.0, 0.0
    for _ in range(iters):
        z = off + a + b * x
        p = expit(z)
        w = p * (1 - p)
        g = np.array([np.sum(y - p), np.sum((y - p) * x)])
        H = np.array([[np.sum(w), np.sum(w * x)], [np.sum(w * x), np.sum(w * x * x)]]) + np.eye(2) * 1e-6
        step = np.linalg.solve(H, g)
        a, b = a + step[0], b + step[1]
        if np.abs(step).max() < 1e-8:
            break
    return a, b


def residual_close(p_model, p_mkt, y, seasons, first_test: int = 2010) -> pd.DataFrame:
    """Walk-forward residual blend. Returns per-row p_blend (NaN before first_test) and the season's (a, b)."""
    p_model, p_mkt, y, seasons = (np.asarray(v, float) for v in (p_model, p_mkt, y, seasons))
    ok = np.isfinite(p_model) & np.isfinite(p_mkt) & np.isfinite(y)
    x = _logit(p_model) - _logit(p_mkt)
    off = _logit(p_mkt)
    out = np.full(len(y), np.nan)
    coefs = {}
    for s in sorted(set(seasons[ok].astype(int))):
        if s < first_test:
            continue
        tr = ok & (seasons < s)
        te = ok & (seasons == s)
        a, b = _fit_logistic(x[tr], off[tr], y[tr])
        coefs[s] = (a, b)
        out[te] = expit(off[te] + a + b * x[te])
    return pd.DataFrame({"p_blend": out}), coefs


def move_beta(model_line, pseudo_open, close_line, seasons, test_season: int, first: int = 2006) -> float:
    """OLS slope (no intercept) of (close - pseudo_open) on (model - pseudo_open) over seasons [first, test_season)."""
    m = np.isfinite(model_line) & np.isfinite(pseudo_open) & np.isfinite(close_line) & (seasons >= first) & (seasons < test_season)
    x = (model_line - pseudo_open)[m]
    y = (close_line - pseudo_open)[m]
    return float(x @ y / max(x @ x, 1e-9))


def probs_from_line(mu_hat, sigma_m: float, kk: np.ndarray, spread_home, playoff=None):
    """(P(home win, tie half), P(home covers spread_home | no push), P(push)) when the margin ~ market dist at mu_hat."""
    mu_hat = np.asarray(mu_hat, float)
    ph = np.full(len(mu_hat), np.nan)
    pc = np.full(len(mu_hat), np.nan)
    pp = np.full(len(mu_hat), np.nan)
    sp = np.asarray(spread_home, float)
    po = np.zeros(len(mu_hat), bool) if playoff is None else np.asarray(playoff, bool)
    for i in range(len(mu_hat)):
        if not np.isfinite(mu_hat[i]):
            continue
        row = GM.margin_pmf(np.array([mu_hat[i]]), sigma_m, kk)
        w = row[0, GM.SUPPORT > 0].sum()
        t = row[0, GM.SUPPORT == 0].sum()
        ph[i] = w + t / 2.0
        if np.isfinite(sp[i]):
            a, b = MK.cover_home(row, np.array([sp[i]]))
            pc[i], pp[i] = a[0], b[0]
    return ph, pc, pp


def over_from_total(mu_t_hat, sigma_t: float, tk, line):
    mu_t_hat, line = np.asarray(mu_t_hat, float), np.asarray(line, float)
    po = np.full(len(line), np.nan)
    pp = np.full(len(line), np.nan)
    for i in range(len(line)):
        if np.isfinite(mu_t_hat[i]) and np.isfinite(line[i]):
            a, b = MK.over_prob(MK.total_pmf(np.array([mu_t_hat[i]]), sigma_t, tk), np.array([line[i]]))
            po[i], pp[i] = a[0], b[0]
    return po, pp
