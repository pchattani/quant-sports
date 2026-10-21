"""
Model-improvement program, October 2026 (docs/research/basketball_edge.md, section "Model-improvement program").

Question: which game model should the site publish? Candidates are scored against the production model (M0:
ratings + home + schedule context, the roster prior on) on the outcome, walk-forward, with the 2 October split:

  tuning seasons  NBA 2014-2023, WNBA 2018-2023 (the seasons with closing lines; choices are made here only)
  test seasons    2024-2026 in both leagues (ESPN open AND close prices; Kalshi from April 2025)

Every fit is walk-forward by season (fit on seasons < s, predict s); within a season inputs use games of US days
<= D - 1 (decision: 08:00 US Eastern on game day). Scores: log-loss and Brier of P(home wins) on the outcome,
paired differences with day-clustered 95 % bootstrap intervals, calibration (logistic slope / intercept of the
outcome on logit p).

Candidates (margin means; p = Phi(mu / sd), sd = the walk-forward residual sd of the margin):
  M0    production game model (experiments.py)
  M1    M0 + availability (last game's participation x last season's player values)
  MK    market ratings from past closing lines (half-life, ridge chosen on the tuning seasons)
  C     close predictor (experiments.py): the close regressed on MK + M1 terms, p at the market sigma
  S     outcome stack: margin ~ MK + rating + availability + schedule context, fitted to OUTCOMES
  SE    S with an early-season interaction (MK and rating weights move with games played)
  K     Kalman margin-of-victory ratings (team strength a random walk; capped margins), as a feature in S
  +cal  any of the above with a walk-forward Platt step (logit p -> a + b logit p, fitted on earlier seasons)
"""
from __future__ import annotations

import json
import logging
import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from oddsmarkets.basketball.research import evaluate as V
from oddsmarkets.basketball.research import experiments as X
from oddsmarkets.basketball.research import market_ratings as MR
from oddsmarkets.basketball.research import markets as M

logger = logging.getLogger(__name__)

TUNE_EVAL = {"nba": (2014, 2023), "wnba": (2018, 2023)}
MK_TRAIN_FROM = {"nba": 2013, "wnba": 2017}
TEST = (2024, 2025, 2026)
MK_HL, MK_RIDGE = 20.0, 1.0            # chosen on the tuning seasons by outcome log-loss (grid 5-40 d x 0.5-3)
CTX = ["b2b", "rest", "travel_1000km", "tz", "altitude", "hca"]
EPS = 1e-4


# ── extra predictors ─────────────────────────────────────────────────────────

def kalman_mov(df: pd.DataFrame, q: float = 0.02, carry: float = 0.6, cap: float = 20.0, r: float = 150.0,
               p0: float = 16.0, hca: float = 2.5, lag: int = 1) -> pd.Series:
    """Kalman filter on team margin ratings (points a game): state x_t ~ random walk with variance q per day per
    team; each game observes clip(margin, -cap, cap) = x_home - x_away + hca [not neutral] + e, var(e) = r.
    Updates day by day; a game on day D sees the state through D - lag. Season start: carry x last season's final
    state (centred), variance p0. Returns kal_mu (home margin mean) by row index."""
    d = df.sort_values(["season", "day", "event_id"])
    out = pd.Series(np.nan, index=df.index)
    last: dict[str, float] = {}
    for s, g in d.groupby("season", sort=True):
        teams = sorted(set(g.home) | set(g.away))
        ix = {t: i for i, t in enumerate(teams)}
        n = len(teams)
        x = np.array([carry * last.get(t, 0.0) for t in teams])
        x = x - x.mean()
        P = np.eye(n) * p0
        days = sorted(g.day.unique())
        by_day = {D: gg for D, gg in g.groupby("day")}
        prev_day = None
        pending: list = []
        for D in days:
            cut = D - timedelta(days=lag)
            # apply every game of days <= cut not yet applied, in day order
            while pending and pending[0][0] <= cut:
                dd, gg = pending.pop(0)
                if prev_day is not None:
                    P = P + np.eye(n) * q * max(0, (dd - prev_day).days)
                prev_day = dd
                for _, rr in gg.iterrows():
                    h, a = ix[rr.home], ix[rr.away]
                    hv = np.zeros(n)
                    hv[h], hv[a] = 1.0, -1.0
                    y = float(np.clip(rr.margin, -cap, cap)) - (0.0 if rr.neutral else hca)
                    S = hv @ P @ hv + r
                    K = P @ hv / S
                    x = x + K * (y - hv @ x)
                    P = P - np.outer(K, hv @ P)
            gg = by_day[D]
            for k, rr in gg.iterrows():
                out[k] = x[ix[rr.home]] - x[ix[rr.away]] + (0.0 if rr.neutral else hca)
            pending.append((D, gg))
        while pending:                                  # the season's last days, for next season's carry
            dd, gg = pending.pop(0)
            for _, rr in gg.iterrows():
                h, a = ix[rr.home], ix[rr.away]
                hv = np.zeros(n)
                hv[h], hv[a] = 1.0, -1.0
                y = float(np.clip(rr.margin, -cap, cap)) - (0.0 if rr.neutral else hca)
                S = hv @ P @ hv + r
                K = P @ hv / S
                x = x + K * (y - hv @ x)
                P = P - np.outer(K, hv @ P)
        last = {t: float(x[i] - x.mean()) for t, i in ix.items()}
    return out


def add_mk(p: pd.DataFrame, df: pd.DataFrame, hl: float, ridge: float, carry: float = 0.6, name: str = "mk_mu") -> pd.DataFrame:
    mk = MR.fit(X._close_cols(df), half_life=hl, ridge=ridge, carry=carry, lag=1).set_index("event_id")
    p = p.copy()
    p[name] = p.event_id.map(mk.mk_mu)
    p[name.replace("_mu", "_tot")] = p.event_id.map(mk.mk_tot)
    p[name.replace("_mu", "_n")] = p.event_id.map(mk.mk_n)
    return p


def wf_margin(p: pd.DataFrame, feats: list[str], name: str, train_from: int | None = None, need: str | None = None,
              target: str = "margin", intercept: bool = False) -> pd.DataFrame:
    """Walk-forward ridge of `target` on `feats` -> columns name_mu, name_sd (rows lacking `need` stay NaN)."""
    p = p.copy()
    have = p.dropna(subset=[need]) if need else p
    seasons = sorted(have.season.unique())
    w = V.walk_forward(have, feats, target, seasons, intercept=intercept, train_from=train_from)
    p[f"{name}_mu"] = np.nan
    p[f"{name}_sd"] = np.nan
    if len(w):
        p.loc[w.index, f"{name}_mu"] = w["pred"]
        p.loc[w.index, f"{name}_sd"] = w["sigma"]
        p.attrs.setdefault("coef", {})[name] = {int(s): c for s, c in w.groupby("season")["coef"].first().items()}
    return p


def prob(p: pd.DataFrame, name: str, sd: float | str | None = None) -> np.ndarray:
    mu = p[f"{name}_mu"].to_numpy(float)
    s = p[f"{name}_sd"].to_numpy(float) if sd is None else (p[sd].to_numpy(float) if isinstance(sd, str) else np.full(len(p), float(sd)))
    return norm.cdf(mu / s)


def logit(x):
    x = np.clip(np.asarray(x, float), EPS, 1 - EPS)
    return np.log(x / (1 - x))


def logistic_fit(z: np.ndarray, y: np.ndarray, l2: float = 1e-6) -> np.ndarray:
    """(a, b) of P(y=1) = sigmoid(a + b z) by Newton steps."""
    Xm = np.column_stack([np.ones(len(z)), z])
    th = np.array([0.0, 1.0])
    for _ in range(50):
        eta = Xm @ th
        pr = 1 / (1 + np.exp(-eta))
        g = Xm.T @ (y - pr) - l2 * th
        H = (Xm * (pr * (1 - pr))[:, None]).T @ Xm + l2 * np.eye(2)
        step = np.linalg.solve(H, g)
        th = th + step
        if np.max(np.abs(step)) < 1e-9:
            break
    return th


def platt_wf(p: pd.DataFrame, col: str, min_train: int = 500, train_from: int | None = None) -> np.ndarray:
    """Walk-forward Platt step on probability column `col`: for season s, (a, b) fitted on seasons < s."""
    out = np.full(len(p), np.nan)
    y = (p.margin > 0).astype(float).to_numpy()
    z = logit(p[col].to_numpy(float))
    ok = np.isfinite(p[col].to_numpy(float))
    seas = p.season.to_numpy()
    for s in sorted(np.unique(seas)):
        tr = ok & (seas < s) & ((seas >= train_from) if train_from else True)
        te = ok & (seas == s)
        if tr.sum() < min_train or not te.any():
            out[te] = p[col].to_numpy(float)[te]
            continue
        a, b = logistic_fit(z[tr], y[tr])
        out[te] = 1 / (1 + np.exp(-(a + b * z[te])))
    return out


def probit_fit(mu: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(c0, sd) maximising sum log Phi(+-(mu + c0) / sd): the margin-scale calibration P(home) = Phi((mu + c0) / sd)."""
    from scipy.optimize import minimize
    mu, y = np.asarray(mu, float), np.asarray(y, float)

    def nll(th):
        z = (mu + th[0]) / math.exp(th[1])
        return -np.sum(y * norm.logcdf(z) + (1 - y) * norm.logcdf(-z))
    r = minimize(nll, np.array([0.0, math.log(12.0)]), method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 2000})
    return float(r.x[0]), float(math.exp(r.x[1]))


def probit_wf(p: pd.DataFrame, mu_col: str, train_from: int | None = None, min_train: int = 500) -> tuple[np.ndarray, dict]:
    """Walk-forward probit calibration of a margin mean: for season s, (c0, sd) fitted on seasons < s."""
    out = np.full(len(p), np.nan)
    mu = p[mu_col].to_numpy(float)
    y = (p.margin > 0).astype(float).to_numpy()
    seas = p.season.to_numpy()
    ok = np.isfinite(mu)
    fits = {}
    for s in sorted(np.unique(seas)):
        tr = ok & (seas < s) & ((seas >= train_from) if train_from else True)
        te = ok & (seas == s)
        if tr.sum() < min_train or not te.any():
            continue
        c0, sd = probit_fit(mu[tr], y[tr])
        fits[int(s)] = (c0, sd)
        out[te] = norm.cdf((mu[te] + c0) / sd)
    return out, fits


def calib(pv, y) -> dict:
    a, b = logistic_fit(logit(pv), np.asarray(y, float))
    pv = np.asarray(pv, float)
    bins = np.clip((pv * 10).astype(int), 0, 9)
    ece = sum(abs(pv[bins == k].mean() - np.asarray(y)[bins == k].mean()) * (bins == k).sum() for k in range(10) if (bins == k).any()) / len(pv)
    return {"slope": float(b), "intercept": float(a), "ece": float(ece)}


# ── the candidate table ──────────────────────────────────────────────────────

def candidates(league: str, roster: bool = True, mk_hl: float = MK_HL, mk_ridge: float = MK_RIDGE,
               kalman: dict | None = None) -> pd.DataFrame:
    df = X.table(league, 1, roster=roster)
    sig_m, sig_t = X.sigmas(df, league)
    p = X.build_predictions(df, league, 1)
    p = add_mk(p.drop(columns=["mk_mu", "mk_tot"]), df, mk_hl, mk_ridge)
    p = M.add_market_means(p, sig_m, sig_t)
    p["sig_m"], p["sig_t"] = sig_m, sig_t
    p["y"] = (p.margin > 0).astype(float)
    p["y_sp"] = -X._close_cols(p)["cl_sp"]
    p["early_w"] = np.exp(-np.minimum(p.gp_h, p.gp_a) / 10.0)
    p["mk_early"] = p["mk_mu"] * p["early_w"]
    p["rating_early"] = p["rating"] * p["early_w"]
    p["kal_mu"] = kalman_mov(p, **(kalman or {}))
    if "dSact_rapm_h" in p:                                       # ORACLE lineup strength (upper bound only)
        k = p["pace_g"] / 100.0
        p["x_dSact"] = (0.5 * (p.dSact_rapm_h - p.dSact_rapm_a) + 0.5 * (p.dSact_box_h - p.dSact_box_a)) * k
    tf = MK_TRAIN_FROM[league]
    p = wf_margin(p, X.V.MARGIN_BASE, "m0")                       # production structure (== mu0)
    p = wf_margin(p, X.M1_FEATS, "m1")
    p = wf_margin(p, ["mk_mu", "hca"], "mko", train_from=tf, need="mk_mu")      # (not "mk": mk_mu is the feature)
    p = wf_margin(p, X.C_SP_FEATS, "c", need="mk_mu", target="y_sp", intercept=True)
    p["c_sd"] = sig_m
    p = wf_margin(p, ["mk_mu", "rating"] + CTX, "s0", train_from=tf, need="mk_mu")
    p = wf_margin(p, ["mk_mu", "rating", "x_dSl"] + CTX, "s", train_from=tf, need="mk_mu")
    p = wf_margin(p, ["mk_mu", "rating", "x_dSl", "mk_early", "rating_early"] + CTX, "se", train_from=tf, need="mk_mu")
    p = wf_margin(p, ["mk_mu", "rating", "kal_mu", "x_dSl"] + CTX, "sk", train_from=tf, need="mk_mu")
    p = wf_margin(p, ["rating", "kal_mu", "x_dSl"] + CTX, "k1")
    # totals: the close-total predictor (CT, fitted to closing totals) and the production structure (TP)
    p["cl_tot"] = X._close_cols(p)["cl_tot"]
    p = wf_margin(p, X.C_TOT_FEATS, "ct", need="mk_tot", target="cl_tot", intercept=True)
    p = wf_margin(p, ["base_total", "x_post"], "tp", target="total_pts", intercept=True)
    if "x_dSact" in p:
        p["x_dSact"] = p["x_dSact"].fillna(p["x_dSl"])
        p = wf_margin(p, ["mk_mu", "rating", "x_dSl", "x_dSact"] + CTX, "so", train_from=tf, need="mk_mu")
        p = wf_margin(p, X.M1_FEATS + ["x_dSact"], "mo")
    return p


PROB_COLS = {"M0": ("m0", None), "M1": ("m1", None), "MK": ("mko", None), "C": ("c", "c_sd"), "S0": ("s0", None),
             "S": ("s", None), "SE": ("se", None), "SK": ("sk", None), "K1": ("k1", None),
             "SO_oracle": ("so", None), "MO_oracle": ("mo", None)}


def add_probs(p: pd.DataFrame, league: str) -> pd.DataFrame:
    p = p.copy()
    for k, (nm, sd) in PROB_COLS.items():
        if f"{nm}_mu" in p:
            p[f"p_{k}"] = prob(p, nm, sd)
    # fall back to M1 where a market-informed model has no market input (no past closes)
    for k in ("MK", "C", "S0", "S", "SE", "SK", "SO_oracle"):
        if f"p_{k}" not in p:
            continue
        p[f"p_{k}"] = p[f"p_{k}"].where(p[f"p_{k}"].notna(), p["p_M1"])
    tf = MK_TRAIN_FROM[league]
    for k in ("M0", "M1", "S", "SE", "SK", "C"):
        p[f"p_{k}+cal"] = platt_wf(p, f"p_{k}", train_from=tf if k not in ("M0", "M1") else None)
    for k, col in (("C", "c_mu"), ("S", "s_mu")):
        v, fits = probit_wf(p, col, train_from=tf)
        p[f"p_{k}+pcal"] = np.where(np.isfinite(v), v, p[f"p_{k}"])
        p.attrs.setdefault("probit", {})[k] = fits
        if k == "C":
            # the informed model as production publishes it: margin c_mu + c0, sd; total CT with its outcome sd
            c0 = p.season.map({s_: f[0] for s_, f in fits.items()})
            sd = p.season.map({s_: f[1] for s_, f in fits.items()})
            p["inf_mu"], p["inf_sd"] = p["c_mu"] + c0, sd
    p["inf_tot"] = p["ct_mu"]
    tsd = {}
    for s_ in sorted(p.season.unique()):
        e = p[(p.season < s_) & p.ct_mu.notna() & p.mk_tot.notna()]
        e = e[e.season >= tf]
        tsd[s_] = float(np.sqrt(np.mean((e.total_pts - e.ct_mu) ** 2))) if len(e) > 300 else np.nan
    p["inf_tsd"] = p.season.map(tsd)
    p["p_close"] = p["close_p_ml"]
    p["p_open"] = p["open_p_ml"]
    p["p_close_sp"] = norm.cdf(-X._close_cols(p)["cl_sp"].to_numpy(float) / p["sig_m"].to_numpy(float))
    return p


def compare(p: pd.DataFrame, cols: list[str], base: str, seasons, need: list[str] | None = None,
            cluster: str = "day") -> list[dict]:
    """Log-loss / Brier of each column on the games of `seasons` that have every column in `need`, with the paired
    difference against `base` (negative = better) and a cluster bootstrap CI."""
    x = p[p.season.isin(list(seasons))].dropna(subset=list(set(cols + [base] + (need or []))))
    if x.empty:
        return []
    y = x.y.to_numpy()
    g = (x.day.astype(str) if cluster == "day" else pd.to_datetime(x.day).dt.strftime("%G-%V")).to_numpy()
    out = []
    for c in cols:
        v = x[c].to_numpy(float)
        d = V.paired_ll_diff(v, x[base].to_numpy(float), y, g)
        bd = V.boot_ci((v - y) ** 2 - (x[base].to_numpy(float) - y) ** 2, g)
        out.append({"forecast": c, "n": int(len(x)), "logloss": V.logloss(v, y), "brier": V.brier(v, y),
                    f"ll_minus_{base}": d[0], "ll_lo": d[1], "ll_hi": d[2], f"brier_minus_{base}": bd[0],
                    "br_lo": bd[1], "br_hi": bd[2], **calib(v, y)})
    return out


# ── the production fit (models/informed.py; written by scripts/bb_fit.py) ─────

PROD_NAMES = {"mk_mu": "mk_mu", "rating": "rating", "x_dSl": "x_av", "x_tot_dS": "x_tot_av"}


def _ridge_coef(tr: pd.DataFrame, feats: list[str], target: str) -> tuple[dict, float]:
    X_ = tr[feats].fillna(0).to_numpy(float)
    y = tr[target].to_numpy(float)
    b = V.ridge(X_, y, intercept=True)
    res = y - np.column_stack([np.ones(len(X_)), X_]) @ b
    names = ["const"] + [PROD_NAMES.get(f, f) for f in feats]
    return {k: round(float(v), 6) for k, v in zip(names, b)}, float(np.sqrt(np.mean(res ** 2)))


def _apply(d: pd.DataFrame, coef: dict, feats: list[str]) -> np.ndarray:
    return coef["const"] + sum(coef[PROD_NAMES.get(f, f)] * d[f].fillna(0).to_numpy(float) for f in feats)


def final_fit(league: str, p: pd.DataFrame | None = None, through: int | None = None) -> dict:
    """The informed model's fit for models/fitted/informed_<L>.json: the close predictor (spread and total) on every
    season with closing lines and market ratings, the probit calibration (c0, sd) on its out-of-sample predictions,
    and the walk-forward path ("wf": per season s, the same fit using seasons < s only) that models/backtest.py
    scores so the calibration page stays out of sample."""
    from oddsmarkets.basketball.models import informed as INF
    p = p if p is not None else add_probs(candidates(league), league)
    p = p.copy()
    p["cl_tot"] = X._close_cols(p)["cl_tot"]
    sp_feats, tot_feats = list(X.C_SP_FEATS), list(X.C_TOT_FEATS)
    last = int(through or p.season.max())
    seasons = sorted(int(s) for s in p.season.unique())
    sp_ok = p.y_sp.notna() & p.mk_mu.notna()
    tot_ok = p.cl_tot.notna() & p.mk_tot.notna()
    tf = MK_TRAIN_FROM[league]
    wf: dict[int, dict] = {}
    mu_wf = pd.Series(np.nan, index=p.index)
    for s in seasons + [last + 1]:
        tr = p[sp_ok & (p.season < s)]
        if len(tr) < 300:
            continue
        cs, _ = _ridge_coef(tr, sp_feats, "y_sp")
        te = p.season == s
        if te.any():
            mu_wf[te & p.mk_mu.notna()] = _apply(p[te & p.mk_mu.notna()], cs, sp_feats)
        prev = p[(p.season < s) & (p.season >= tf) & mu_wf.notna()]
        if len(prev) < 500:
            continue
        c0, sd = probit_fit(mu_wf[prev.index].to_numpy(float), prev.y.to_numpy(float))
        trt = p[tot_ok & (p.season < s)]
        ct, st_ = _ridge_coef(trt, tot_feats, "cl_tot") if len(trt) >= 300 else (None, None)
        wf[int(s)] = {"spread": cs, "cal_c0": round(c0, 4), "cal_sd": round(sd, 4), "total": ct,
                      "n_spread": int(len(tr)), "n_cal": int(len(prev)), "n_total": int(len(trt))}
    prod = wf.get(last + 1)
    if not prod:
        return {}
    # residual sd of the outcome total around the out-of-sample total prediction (for over/under probabilities)
    tot_res = []
    for s, f in wf.items():
        te = p[(p.season == s) & p.mk_tot.notna()]
        if f.get("total") and len(te):
            tot_res.append(te.total_pts.to_numpy(float) - _apply(te, f["total"], tot_feats))
    sig_t = float(np.sqrt(np.mean(np.concatenate(tot_res) ** 2))) if tot_res else None
    return {"version": INF.VERSION, "league": league, "fitted_on": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d"),
            "through_season": last, "mk": {"half_life": MK_HL, "ridge": MK_RIDGE, "carry": 0.6},
            "spread": prod["spread"], "cal_c0": prod["cal_c0"], "cal_sd": prod["cal_sd"], "total": prod["total"],
            "sigma_total": round(sig_t, 4) if sig_t else None, "n_spread": prod["n_spread"], "n_total": prod["n_total"],
            "n_cal": prod["n_cal"], "wf": {str(s): f for s, f in wf.items() if s <= last}}


# ── the experiment log (scripts/bb_edge.py improve -> data/edge/basketball_experiments.json) ─────

LOG_COLS = ["p_M0", "p_M1", "p_MK", "p_C", "p_C+cal", "p_C+pcal", "p_S0", "p_S", "p_S+pcal", "p_SE", "p_SK", "p_K1",
            "p_M0+cal", "p_M1+cal", "p_SO_oracle", "p_MO_oracle"]


def mk_grid(league: str, p: pd.DataFrame, df: pd.DataFrame) -> list[dict]:
    """Outcome log-loss of S and C on the tuning seasons for market-rating half-life x ridge x carry."""
    a, b = TUNE_EVAL[league]
    tf = MK_TRAIN_FROM[league]
    out = []
    grid = [(hl, r, 0.6) for hl in (5, 10, 20, 40) for r in (0.5, 1, 3)] + [(10, 1, 0.3), (10, 1, 0.9), (20, 1, 0.3), (20, 1, 0.9)]
    for hl, r, c in grid:
        q = add_mk(p.drop(columns=["mk_mu", "mk_tot", "mk_n"]), df, hl, r, carry=c)
        q = wf_margin(q, ["mk_mu", "rating", "x_dSl"] + CTX, "s", train_from=tf, need="mk_mu")
        q = wf_margin(q, X.C_SP_FEATS, "c", need="mk_mu", target="y_sp", intercept=True)
        m = q.season.between(a, b) & q.s_mu.notna() & q.c_mu.notna()
        y = q.y[m].to_numpy()
        out.append({"half_life": hl, "ridge": r, "carry": c, "n": int(m.sum()), "ll_S": V.logloss(prob(q[m], "s"), y),
                    "ll_C": V.logloss(prob(q[m], "c", float(q.sig_m.iloc[0])), y),
                    "rmse_mk_vs_close": float(np.sqrt(np.mean((q.mk_mu[m] - q.y_sp[m]) ** 2)))})
    return out


def gbm_residual(league: str, p: pd.DataFrame) -> list[dict]:
    """LightGBM on the residual of S (walk-forward by season, 1 thread); scored on the tuning seasons."""
    import lightgbm as lgb
    feats = ["s_mu", "dis", "gp_h", "gp_a", "se_h", "se_a", "prior_share_h", "prior_share_a", "rest_h", "rest_a", "b2b_h",
             "b2b_a", "mk_n", "post", "pace_g", "x_dSl", "month", "mk_tot"]
    q = p.copy()
    q["dis"], q["month"] = q.mk_mu - q.rating, pd.to_datetime(q.day).dt.month
    q["post"] = (q.stype == "post").astype(float)
    q["res"] = q.margin - q.s_mu
    q["g_mu"] = np.nan
    prm = dict(objective="regression", learning_rate=0.02, num_leaves=8, min_data_in_leaf=100, bagging_fraction=0.8,
               bagging_freq=1, feature_fraction=0.8, lambda_l2=10, num_threads=1, verbose=-1, seed=1)
    for s in sorted(q.dropna(subset=["s_mu"]).season.unique()):
        tr, te = q[(q.season < s) & q.s_mu.notna()], q[(q.season == s) & q.s_mu.notna()]
        if len(tr) < 2000 or te.empty:
            continue
        m = lgb.train(prm, lgb.Dataset(tr[feats].astype(float), tr.res.astype(float)), num_boost_round=200)
        q.loc[te.index, "g_mu"] = te.s_mu + m.predict(te[feats].astype(float))
    sd = {s: float(np.sqrt(np.mean((g.margin - g.g_mu) ** 2))) for s, g in q.dropna(subset=["g_mu"]).groupby("season")}
    q["g_sd"] = q.season.map({s: np.mean([v for k, v in sd.items() if k < s]) if any(k < s for k in sd) else np.nan for s in q.season.unique()})
    q["p_G"] = prob(q, "g")
    a, b = TUNE_EVAL[league]
    return compare(q, ["p_S", "p_G"], "p_S", range(a, b + 1), need=["p_G"])


def totals_table(p: pd.DataFrame, seasons, need: list[str]) -> list[dict]:
    x = p[p.season.isin(list(seasons))].dropna(subset=need)
    g = x.day.astype(str).to_numpy()
    out = []
    for c in ["tp_mu", "mut", "ct_mu", "mk_tot", "cl_tot"]:
        pred = x[c].fillna(x["tp_mu"]) if c == "ct_mu" else x[c]
        e, eb = (x.total_pts - pred).to_numpy(), (x.total_pts - x["tp_mu"]).to_numpy()
        d = V.boot_ci(e ** 2 - eb ** 2, g)
        out.append({"pred": c, "n": int(len(x)), "rmse": float(np.sqrt(np.mean(e ** 2))), "bias": float(np.mean(e)),
                    "mse_minus_production": d[0], "lo": d[1], "hi": d[2]})
    return out


def experiment_log(leagues=("nba", "wnba")) -> dict:
    """Every experiment of the October 2026 program, tuning and test, into data/edge/basketball_experiments.json
    under "model_program_2026_10" (the 2 October entries are kept)."""
    from oddsmarkets.basketball.research import kalshi as K
    from oddsmarkets.basketball.research import output as O
    res: dict = {"split": {"tune": TUNE_EVAL, "test": TEST, "mk_train_from": MK_TRAIN_FROM},
                 "chosen": "C+pcal (close predictor, probit calibration); NBA promoted, WNBA not (test CI includes 0)"}
    for lg in leagues:
        df = X.table(lg, 1, roster=True)
        p = add_probs(candidates(lg), lg)
        a, b = TUNE_EVAL[lg]
        cols = [c for c in LOG_COLS if c in p]
        r = {"tune": compare(p, cols + ["p_close_sp"], "p_M0", range(a, b + 1), need=["p_close_sp"]),
             "test": compare(p, cols + ["p_close", "p_open"], "p_M0", TEST, need=["p_close", "p_open"]),
             "test_week_clusters": compare(p, ["p_M0", "p_C+pcal", "p_close", "p_open"], "p_M0", TEST,
                                           need=["p_close", "p_open"], cluster="week"),
             "test_vs_close": compare(p, ["p_M0", "p_C+pcal"], "p_close", TEST, need=["p_close", "p_open"]),
             "test_vs_open": compare(p, ["p_M0", "p_C+pcal"], "p_open", TEST, need=["p_close", "p_open"]),
             "test_all_games": compare(p, ["p_M0", "p_C+pcal"], "p_M0", TEST),
             "test_by_season": {int(s): compare(p, ["p_M0", "p_C+pcal", "p_close"], "p_M0", [s], need=["p_close", "p_open"])
                                for s in TEST},
             "totals_tune": totals_table(p, range(a, b + 1), ["cl_tot", "mk_tot"]),
             "totals_test": totals_table(p, TEST, ["cl_tot", "mk_tot", "close_mu_tot"]),
             "mk_grid": mk_grid(lg, p, df),
             "probit_fits": {k: {int(s): list(v) for s, v in f.items()} for k, f in p.attrs.get("probit", {}).items()}}
        if lg == "nba":
            q = p.copy()
            r["gbm_residual_tune"] = gbm_residual(lg, q)
        t = p[p.season.isin(TEST)].copy()
        t["day"] = pd.to_datetime(t["day"]).dt.date
        k = K.load(lg, t, O._abbr(lg, t.season.unique()))
        if not k.empty:
            k = k.dropna(subset=["dec_ask_h", "dec_bid_h"])
            k["p_kalshi"] = (k.dec_ask_h + k.dec_bid_h) / 2
            q = p.merge(k[["event_id", "p_kalshi", "close_mid_h"]], on="event_id", how="inner")
            q["p_kalshi_close"] = q["close_mid_h"]
            r["test_vs_kalshi_0800"] = compare(q, ["p_M0", "p_C+pcal", "p_open", "p_close", "p_kalshi_close"], "p_kalshi",
                                               TEST, need=["p_kalshi"])
        res[lg] = r
        logger.info("%s experiment log done", lg)
    path = X.OUT / "basketball_experiments.json"
    try:
        allres = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        allres = {}
    allres["model_program_2026_10"] = res
    path.write_text(json.dumps(allres, default=X._js, indent=1), "utf-8")
    return res
