"""
Player-movement probabilities: the shared engine behind the "chance of moving", team "Outlook" and "Targets" blocks of
The Quant Bullpen, Hardwood, Rink and Gridiron (docs/research/moves_model.md; the brief: who leaves, who arrives, and
which players on other teams a team would realistically go after).

A sport supplies a *panel*: one row per rostered player at a snapshot date inside season S (the same point of the
season every year, so the training rows look like the row being predicted), with numeric features and the labels

    y_dl     1 when the player is traded away (MLB: a trade; the box-score sports: a move straight to another team, i.e.
             a trade or a waiver claim) between the snapshot and the trade deadline
    y_next   1 when he is no longer with the team at the start of the next season
    y_type   the kind of that departure (0 trade, 1 release or waiver, 2 free agency / other), -1 when unknown

and, for the team blocks, the arrivals (players who were on another club at the snapshot and join the team inside the
horizon).

Models (all fitted walk-forward: a season is predicted only from seasons whose labels were settled before its
snapshot):
  * departure        ridge logistic regression on standardised features (some entered squared);
  * departure type   multinomial logit among the leavers (the type split; base shares when it does not beat them);
  * arrivals         Poisson regression per team x position (need, team strength and trajectory, past turnover, the
                     expected departures at the position from the departure model), P(adds >= 1) = 1 - exp(-lambda);
  * destination      conditional logit: given that a player moves, which team gets him (need at his position, the
                     upgrade he would be there, contending teams and older players, rebuilding teams and younger ones).
                     A target's chance of joining team T = P(he moves) x P(T | he moves).

Validation (pre-registered in docs/research/moves_model.md before the sealed seasons were scored): log-loss and Brier
against the training base rate with a 95% CI from a bootstrap over team-seasons (paired), calibration by decile and a
calibration slope / calibration-in-the-large, and top-k precision of the target lists against the need x value ranking
and against chance. Promotion: the CI on the log-loss gain excludes zero and the model is calibrated (CAL_RULE).

Nothing here reads a sport's files: numpy, scipy and pandas only.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize

VERSION = "movement-1"
EPS = 1e-6
L2_GRID = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
N_BOOT = 2000
# calibration rule (pre-registered): slope of the logistic recalibration within [0.8, 1.25] and calibration-in-the-large
# (observed minus predicted rate) within 10% of the base rate or 1 percentage point, whichever is larger
CAL_SLOPE = (0.8, 1.25)
CAL_LARGE_REL, CAL_LARGE_ABS = 0.10, 0.01
TYPES = ("trade", "release", "other")


# ---------------------------------------------------------------------------------------------- design matrix

@dataclass
class Design:
    feats: list[str]
    quad: list[str] = field(default_factory=list)
    mu: dict = field(default_factory=dict)
    sd: dict = field(default_factory=dict)
    fill: dict = field(default_factory=dict)

    def names(self) -> list[str]:
        return list(self.feats) + [f + "^2" for f in self.quad]

    def fit(self, df: pd.DataFrame) -> "Design":
        for f in self.feats:
            x = pd.to_numeric(df[f], errors="coerce").astype(float)
            m = float(x.mean()) if x.notna().any() else 0.0
            self.fill[f] = m
            x = x.fillna(m)
            self.mu[f] = float(x.mean())
            s = float(x.std())
            self.sd[f] = s if s > 1e-9 else 1.0
        for f in self.quad:
            z = (pd.to_numeric(df[f], errors="coerce").astype(float).fillna(self.fill[f]) - self.mu[f]) / self.sd[f]
            q = z * z
            self.mu[f + "^2"] = float(q.mean())
            s = float(q.std())
            self.sd[f + "^2"] = s if s > 1e-9 else 1.0
        return self

    def X(self, df: pd.DataFrame) -> np.ndarray:
        cols = []
        for f in self.feats:
            x = pd.to_numeric(df[f], errors="coerce").astype(float).fillna(self.fill[f]).to_numpy()
            cols.append((x - self.mu[f]) / self.sd[f])
        for f in self.quad:
            x = pd.to_numeric(df[f], errors="coerce").astype(float).fillna(self.fill[f]).to_numpy()
            z = (x - self.mu[f]) / self.sd[f]
            cols.append((z * z - self.mu[f + "^2"]) / self.sd[f + "^2"])
        return np.column_stack(cols) if cols else np.zeros((len(df), 0))

    def to_json(self) -> dict:
        return {"feats": self.feats, "quad": self.quad, "mu": self.mu, "sd": self.sd, "fill": self.fill}


def _add1(X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X])


# ---------------------------------------------------------------------------------------------- fits

def fit_logit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, w: np.ndarray | None = None) -> np.ndarray:
    """Ridge logistic regression (intercept not penalised); returns [b0, b...]. l2 is per row-average scale x n."""
    A = _add1(X)
    y = np.asarray(y, dtype=float)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    pen = np.ones(A.shape[1]) * l2
    pen[0] = 0.0
    p0 = min(max(float(np.average(y, weights=w)), 1e-4), 1 - 1e-4)
    b0 = np.zeros(A.shape[1])
    b0[0] = math.log(p0 / (1 - p0))

    def f(b):
        z = A @ b
        ll = np.sum(w * (y * z - np.logaddexp(0.0, z)))
        p = 1.0 / (1.0 + np.exp(-z))
        g = A.T @ (w * (y - p))
        return -ll + 0.5 * np.sum(pen * b * b), -g + pen * b

    r = minimize(f, b0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return r.x


def pred_logit(b: np.ndarray, X: np.ndarray) -> np.ndarray:
    z = _add1(X) @ b
    return np.clip(1.0 / (1.0 + np.exp(-z)), EPS, 1 - EPS)


def fit_mnl(X: np.ndarray, y: np.ndarray, K: int, l2: float = 1.0) -> np.ndarray:
    """Multinomial logit with class 0 as reference: returns B of shape (p+1, K-1)."""
    A = _add1(X)
    n, p = A.shape
    Y = np.zeros((n, K))
    Y[np.arange(n), np.asarray(y, dtype=int)] = 1.0
    pen = np.ones((p, K - 1)) * l2
    pen[0, :] = 0.0
    freq = np.clip(Y.mean(axis=0), 1e-4, None)
    B0 = np.zeros((p, K - 1))
    B0[0, :] = np.log(freq[1:] / freq[0])

    def f(bflat):
        B = bflat.reshape(p, K - 1)
        Z = np.column_stack([np.zeros(n), A @ B])
        lse = np.logaddexp.reduce(Z, axis=1)
        ll = np.sum(np.sum(Y * Z, axis=1) - lse)
        P = np.exp(Z - lse[:, None])
        G = A.T @ (Y[:, 1:] - P[:, 1:])
        return -ll + 0.5 * np.sum(pen * B * B), (-G + pen * B).ravel()

    r = minimize(f, B0.ravel(), jac=True, method="L-BFGS-B", options={"maxiter": 800})
    return r.x.reshape(p, K - 1)


def pred_mnl(B: np.ndarray, X: np.ndarray) -> np.ndarray:
    A = _add1(X)
    Z = np.column_stack([np.zeros(len(A)), A @ B])
    Z -= Z.max(axis=1, keepdims=True)
    P = np.exp(Z)
    P /= P.sum(axis=1, keepdims=True)
    return np.clip(P, EPS, 1.0)


def fit_poisson(X: np.ndarray, y: np.ndarray, l2: float = 1.0) -> np.ndarray:
    A = _add1(X)
    y = np.asarray(y, dtype=float)
    pen = np.ones(A.shape[1]) * l2
    pen[0] = 0.0
    b0 = np.zeros(A.shape[1])
    b0[0] = math.log(max(float(y.mean()), 1e-3))

    def f(b):
        z = np.clip(A @ b, -20, 20)
        mu = np.exp(z)
        ll = np.sum(y * z - mu)
        g = A.T @ (y - mu)
        return -ll + 0.5 * np.sum(pen * b * b), -g + pen * b

    r = minimize(f, b0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return r.x


def pred_poisson(b: np.ndarray, X: np.ndarray) -> np.ndarray:
    return np.exp(np.clip(_add1(X) @ b, -20, 20))


def fit_clogit(Xs: list[np.ndarray], chosen: list[int], l2: float = 1.0) -> np.ndarray:
    """Conditional logit: Xs[i] is the (alternatives x p) matrix of choice set i, chosen[i] the row picked."""
    p = Xs[0].shape[1]
    A = np.vstack(Xs)
    sizes = np.array([len(x) for x in Xs])
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    grp = np.repeat(np.arange(len(Xs)), sizes)
    pick = starts + np.asarray(chosen)

    def f(b):
        z = A @ b
        gmax = np.full(len(Xs), -np.inf)
        np.maximum.at(gmax, grp, z)
        e = np.exp(z - gmax[grp])
        den = np.bincount(grp, weights=e, minlength=len(Xs))
        lse = np.log(den) + gmax
        ll = np.sum(z[pick] - lse)
        P = e / den[grp]
        G = A[pick].sum(axis=0) - (A * P[:, None]).sum(axis=0)
        return -ll + 0.5 * l2 * np.sum(b * b), -G + l2 * b

    r = minimize(f, np.zeros(p), jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return r.x


def pred_clogit(b: np.ndarray, X: np.ndarray) -> np.ndarray:
    z = X @ b
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


# ---------------------------------------------------------------------------------------------- metrics

def logloss_rows(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def boot_ci(diff_sum: np.ndarray, cnt: np.ndarray, n_boot: int = N_BOOT, seed: int = 7) -> tuple[float, float, float]:
    """Mean of a per-row quantity from per-cluster sums and counts, and its 95% CI by resampling clusters."""
    rng = np.random.default_rng(seed)
    k = len(cnt)
    est = float(diff_sum.sum() / max(cnt.sum(), 1))
    if k < 2:
        return est, float("nan"), float("nan")
    idx = rng.integers(0, k, size=(n_boot, k))
    bs = diff_sum[idx].sum(axis=1) / np.maximum(cnt[idx].sum(axis=1), 1)
    return est, float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def _cluster_sums(values: np.ndarray, clusters: Sequence) -> tuple[np.ndarray, np.ndarray]:
    codes, uniq = pd.factorize(pd.Series(list(clusters)))
    s = np.bincount(codes, weights=values)
    c = np.bincount(codes)
    return s, c


def calib_table(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[list]:
    """[[mean predicted, observed rate, n]] by decile of the prediction (equal counts)."""
    order = np.argsort(p, kind="stable")
    out = []
    for chunk in np.array_split(order, bins):
        if len(chunk):
            out.append([round(float(p[chunk].mean()), 4), round(float(y[chunk].mean()), 4), int(len(chunk))])
    return out


def calib_slope(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """(intercept, slope) of the logistic recalibration y ~ a + b logit(p)."""
    z = np.log(np.clip(p, EPS, 1 - EPS) / np.clip(1 - p, EPS, 1))
    b = fit_logit(z[:, None], y, l2=0.0)
    return float(b[0]), float(b[1])


def binary_metrics(y, p, p0, clusters, n_boot: int = N_BOOT) -> dict:
    """Model v base-rate log-loss and Brier with clustered bootstrap CIs on the paired gains, calibration."""
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    p0 = np.asarray(p0, dtype=float)
    ll_m, ll_b = logloss_rows(y, p), logloss_rows(y, p0)
    br_m, br_b = (p - y) ** 2, (p0 - y) ** 2
    s_ll, c = _cluster_sums(ll_b - ll_m, clusters)
    s_br, _ = _cluster_sums(br_b - br_m, clusters)
    g_ll = boot_ci(s_ll, c, n_boot)
    g_br = boot_ci(s_br, c, n_boot, seed=11)
    a, b = calib_slope(y, p)
    obs, pred = float(y.mean()), float(p.mean())
    # bootstrap of calibration-in-the-large
    s_cl, _ = _cluster_sums(y - p, clusters)
    cil = boot_ci(s_cl, c, n_boot, seed=13)
    tol = max(CAL_LARGE_ABS, CAL_LARGE_REL * obs)
    calibrated = (CAL_SLOPE[0] <= b <= CAL_SLOPE[1]) and abs(obs - pred) <= tol
    passed = bool(g_ll[1] > 0) and calibrated
    return {"n": int(len(y)), "clusters": int(len(c)), "rate": round(obs, 4), "mean_p": round(pred, 4),
            "logloss": round(float(ll_m.mean()), 5), "logloss_base": round(float(ll_b.mean()), 5),
            "ll_gain": [round(g_ll[0], 5), round(g_ll[1], 5), round(g_ll[2], 5)],
            "ll_gain_pct": round(100 * g_ll[0] / max(float(ll_b.mean()), 1e-9), 2),
            "brier": round(float(br_m.mean()), 5), "brier_base": round(float(br_b.mean()), 5),
            "brier_gain": [round(g_br[0], 5), round(g_br[1], 5), round(g_br[2], 5)],
            "cal_slope": round(b, 3), "cal_intercept": round(a, 3), "cal_large": [round(cil[0], 4), round(cil[1], 4), round(cil[2], 4)],
            "cal_tol": round(tol, 4), "calibrated": bool(calibrated), "deciles": calib_table(y, p), "passed": passed}


def multi_metrics(y: np.ndarray, P: np.ndarray, P0: np.ndarray, clusters, n_boot: int = N_BOOT) -> dict:
    """Multinomial log-loss of P v the base shares P0 (rows: classes), paired clustered CI; per-class calibration."""
    y = np.asarray(y, dtype=int)
    idx = np.arange(len(y))
    ll_m = -np.log(np.clip(P[idx, y], EPS, 1))
    ll_b = -np.log(np.clip(P0[idx, y], EPS, 1))
    s, c = _cluster_sums(ll_b - ll_m, clusters)
    g = boot_ci(s, c, n_boot)
    per = []
    for k in range(P.shape[1]):
        yk = (y == k).astype(float)
        per.append({"rate": round(float(yk.mean()), 4), "mean_p": round(float(P[:, k].mean()), 4),
                    "slope": round(calib_slope(yk, P[:, k])[1], 3) if 0 < yk.sum() < len(yk) else None})
    return {"n": int(len(y)), "logloss": round(float(ll_m.mean()), 5), "logloss_base": round(float(ll_b.mean()), 5),
            "ll_gain": [round(g[0], 5), round(g[1], 5), round(g[2], 5)], "classes": per, "passed": bool(g[1] > 0)}


# ---------------------------------------------------------------------------------------------- walk-forward

def _season_rows(df: pd.DataFrame, seasons: Iterable[int]) -> pd.DataFrame:
    return df[df["season"].isin(list(seasons))]


def wf_binary(panel: pd.DataFrame, label: str, feats: list[str], quad: list[str], eval_seasons: list[int],
              l2: float, min_train: int = 2, gap: int = 0) -> pd.DataFrame:
    """Walk-forward predictions for eval_seasons: season s is fitted on every labelled season before s. Returns the eval
    rows with columns p (model) and p0 (training base rate)."""
    out = []
    for s in eval_seasons:
        tr = panel[(panel["season"] < s - gap) & panel[label].notna()]
        te = panel[(panel["season"] == s) & panel[label].notna()]
        if tr["season"].nunique() < min_train or not len(te):
            continue
        d = Design(list(feats), list(quad)).fit(tr)
        b = fit_logit(d.X(tr), tr[label].to_numpy(dtype=float), l2)
        r = te.copy()
        r["p"] = pred_logit(b, d.X(te))
        r["p0"] = float(tr[label].mean())
        out.append(r)
    return pd.concat(out) if out else pd.DataFrame()


def choose_l2(panel: pd.DataFrame, label: str, feats: list[str], quad: list[str], dev: list[int], grid=L2_GRID,
              gap: int = 0) -> tuple[float, dict]:
    res = {}
    for l2 in grid:
        r = wf_binary(panel, label, feats, quad, dev, l2, gap=gap)
        res[l2] = float(logloss_rows(r[label].to_numpy(float), r["p"].to_numpy()).mean()) if len(r) else float("inf")
    best = min(res, key=res.get)
    return best, {str(k): round(v, 5) for k, v in res.items()}


def evaluate_binary(panel: pd.DataFrame, label: str, feats: list[str], quad: list[str], dev: list[int], test: list[int],
                    cluster_cols=("season", "tid"), gap: int = 0) -> dict:
    l2, grid = choose_l2(panel, label, feats, quad, dev, gap=gap)
    out = {"label": label, "l2": l2, "l2_dev": grid, "dev": dev, "test": test, "gap": gap}
    for name, ss in (("dev_eval", dev), ("test_eval", test)):
        r = wf_binary(panel, label, feats, quad, ss, l2, gap=gap)
        if not len(r):
            out[name] = None
            continue
        cl = r[list(cluster_cols)].astype(str).agg("|".join, axis=1).to_numpy()
        m = binary_metrics(r[label].to_numpy(float), r["p"].to_numpy(), r["p0"].to_numpy(), cl)
        m["by_season"] = {str(s): {"n": int((r["season"] == s).sum()), "rate": round(float(r.loc[r["season"] == s, label].mean()), 4),
                                   "ll_gain": round(float((logloss_rows(r.loc[r["season"] == s, label].to_numpy(float), r.loc[r["season"] == s, "p0"].to_numpy())
                                                           - logloss_rows(r.loc[r["season"] == s, label].to_numpy(float), r.loc[r["season"] == s, "p"].to_numpy())).mean()), 5)}
                          for s in sorted(r["season"].unique())}
        out[name] = m
    return out


def fit_final_binary(panel: pd.DataFrame, label: str, feats: list[str], quad: list[str], l2: float, upto: int) -> tuple[Design, np.ndarray, float]:
    tr = panel[(panel["season"] <= upto) & panel[label].notna()]
    d = Design(list(feats), list(quad)).fit(tr)
    b = fit_logit(d.X(tr), tr[label].to_numpy(dtype=float), l2)
    return d, b, float(tr[label].mean())


def coef_table(d: Design, b: np.ndarray) -> list[list]:
    """[[feature, coefficient per SD]] sorted by size (the intercept left out)."""
    return sorted([[n, round(float(c), 3)] for n, c in zip(d.names(), b[1:])], key=lambda r: -abs(r[1]))


# ---------------------------------------------------------------------------------------------- departure type

def wf_type(panel: pd.DataFrame, feats: list[str], quad: list[str], eval_seasons: list[int], l2: float, K: int = 3,
            gap: int = 0) -> pd.DataFrame:
    """Among leavers with a known type: multinomial predictions (P0 = training shares) for eval seasons."""
    lv = panel[(panel["y_next"] == 1) & (panel["y_type"] >= 0)]
    out = []
    for s in eval_seasons:
        tr, te = lv[lv["season"] < s - gap], lv[lv["season"] == s]
        if tr["season"].nunique() < 2 or not len(te) or tr["y_type"].nunique() < K:
            continue
        d = Design(list(feats), list(quad)).fit(tr)
        B = fit_mnl(d.X(tr), tr["y_type"].to_numpy(int), K, l2)
        P = pred_mnl(B, d.X(te))
        sh = np.bincount(tr["y_type"].to_numpy(int), minlength=K) / len(tr)
        r = te.copy()
        for k in range(K):
            r[f"q{k}"] = P[:, k]
            r[f"q0{k}"] = sh[k]
        out.append(r)
    return pd.concat(out) if out else pd.DataFrame()


def evaluate_type(panel: pd.DataFrame, feats: list[str], quad: list[str], dev: list[int], test: list[int], K: int = 3,
                  gap: int = 0) -> dict:
    best, grid = None, {}
    for l2 in L2_GRID:
        r = wf_type(panel, feats, quad, dev, l2, K, gap)
        if not len(r):
            continue
        P = r[[f"q{k}" for k in range(K)]].to_numpy()
        ll = float(-np.log(np.clip(P[np.arange(len(r)), r["y_type"].to_numpy(int)], EPS, 1)).mean())
        grid[str(l2)] = round(ll, 5)
        if best is None or ll < grid[str(best)]:
            best = l2
    out = {"l2": best, "l2_dev": grid}
    if best is None:
        return {**out, "test_eval": None, "dev_eval": None}
    for name, ss in (("dev_eval", dev), ("test_eval", test)):
        r = wf_type(panel, feats, quad, ss, best, K, gap)
        if not len(r):
            out[name] = None
            continue
        cl = r[["season", "tid"]].astype(str).agg("|".join, axis=1).to_numpy()
        out[name] = multi_metrics(r["y_type"].to_numpy(int), r[[f"q{k}" for k in range(K)]].to_numpy(),
                                  r[[f"q0{k}" for k in range(K)]].to_numpy(), cl)
    return out


def fit_final_type(panel: pd.DataFrame, feats: list[str], quad: list[str], l2: float, upto: int, K: int = 3):
    lv = panel[(panel["y_next"] == 1) & (panel["y_type"] >= 0) & (panel["season"] <= upto)]
    d = Design(list(feats), list(quad)).fit(lv)
    B = fit_mnl(d.X(lv), lv["y_type"].to_numpy(int), K, l2)
    sh = np.bincount(lv["y_type"].to_numpy(int), minlength=K) / max(len(lv), 1)
    return d, B, sh


# ---------------------------------------------------------------------------------------------- arrivals by position

def wf_poisson(rows: pd.DataFrame, feats: list[str], eval_seasons: list[int], l2: float, gap: int = 0) -> pd.DataFrame:
    """rows: one per (season, tid, pos) with y (arrivals); base = the training mean at that position."""
    out = []
    pos_d = pd.get_dummies(rows["pos"], prefix="pos", dtype=float)
    R = pd.concat([rows, pos_d], axis=1)
    fx = list(feats) + list(pos_d.columns[1:])
    for s in eval_seasons:
        tr, te = R[R["season"] < s - gap], R[R["season"] == s]
        if tr["season"].nunique() < 2 or not len(te):
            continue
        d = Design(fx).fit(tr)
        b = fit_poisson(d.X(tr), tr["y"].to_numpy(float), l2)
        r = te.copy()
        r["lam"] = pred_poisson(b, d.X(te))
        base = tr.groupby("pos")["y"].mean()
        r["lam0"] = r["pos"].map(base).fillna(float(tr["y"].mean())).to_numpy()
        out.append(r)
    return pd.concat(out) if out else pd.DataFrame()


def evaluate_arrivals(rows: pd.DataFrame, feats: list[str], dev: list[int], test: list[int], gap: int = 0) -> dict:
    grid, best = {}, None
    for l2 in L2_GRID:
        r = wf_poisson(rows, feats, dev, l2, gap)
        if not len(r):
            continue
        y1 = (r["y"] > 0).to_numpy(float)
        ll = float(logloss_rows(y1, 1 - np.exp(-r["lam"].to_numpy())).mean())
        grid[str(l2)] = round(ll, 5)
        if best is None or ll < grid[str(best)]:
            best = l2
    out = {"l2": best, "l2_dev": grid}
    for name, ss in (("dev_eval", dev), ("test_eval", test)):
        r = wf_poisson(rows, feats, ss, best, gap) if best is not None else pd.DataFrame()
        if not len(r):
            out[name] = None
            continue
        y1 = (r["y"] > 0).to_numpy(float)
        cl = r[["season", "tid"]].astype(str).agg("|".join, axis=1).to_numpy()
        m = binary_metrics(y1, 1 - np.exp(-r["lam"].to_numpy()), 1 - np.exp(-r["lam0"].to_numpy()), cl)
        lam, lam0, y = np.maximum(r["lam"].to_numpy(), 1e-6), np.maximum(r["lam0"].to_numpy(), 1e-6), r["y"].to_numpy(float)
        dev_m = 2 * np.sum(np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / lam), 0) - (y - lam))
        dev_b = 2 * np.sum(np.where(y > 0, y * np.log(np.maximum(y, 1e-9) / lam0), 0) - (y - lam0))
        m["poisson_deviance"] = [round(float(dev_m / len(y)), 4), round(float(dev_b / len(y)), 4)]
        m["arrivals_per_team"] = round(float(r.groupby(["season", "tid"])["y"].sum().mean()), 2)
        m["pred_per_team"] = round(float(r.groupby(["season", "tid"])["lam"].sum().mean()), 2)
        out[name] = m
    return out


def fit_final_poisson(rows: pd.DataFrame, feats: list[str], l2: float, upto: int):
    pos_d = pd.get_dummies(rows["pos"], prefix="pos", dtype=float)
    R = pd.concat([rows, pos_d], axis=1)
    fx = list(feats) + list(pos_d.columns[1:])
    tr = R[R["season"] <= upto]
    d = Design(fx).fit(tr)
    b = fit_poisson(d.X(tr), tr["y"].to_numpy(float), l2)
    return d, b, list(pos_d.columns)


def predict_poisson_rows(d: Design, b: np.ndarray, pos_cols: list[str], rows: pd.DataFrame) -> np.ndarray:
    R = rows.copy()
    for c in pos_cols:
        R[c] = (("pos_" + R["pos"].astype(str)) == c).astype(float)
    return pred_poisson(b, d.X(R))


# ---------------------------------------------------------------------------------------------- targets

def topk_eval(groups: list[dict], k: int = 10, n_boot: int = N_BOOT) -> dict:
    """groups: [{"key", "hits": {cand ids that arrived}, "rankings": {name: [cand ids, best first]}, "pool": n}] for
    team-seasons with at least one arrival in the pool. Precision@k per ranking, the share of team-seasons with a hit in
    the top k, the chance expectation, and paired CIs of each ranking against the first ("model") one."""
    names = list(groups[0]["rankings"]) if groups else []
    prec = {n: [] for n in names}
    hit = {n: [] for n in names}
    chance = []
    for g in groups:
        H = g["hits"]
        for n in names:
            top = g["rankings"][n][:k]
            h = sum(1 for c in top if c in H)
            prec[n].append(h / k)
            hit[n].append(1.0 if h else 0.0)
        chance.append(min(len(H), g["pool"]) / max(g["pool"], 1))
    out = {"k": k, "team_seasons": len(groups), "chance_precision": round(float(np.mean(chance)), 4) if chance else None}
    if not groups:
        return out
    rng = np.random.default_rng(5)
    n = len(groups)
    idx = rng.integers(0, n, size=(n_boot, n))
    ref = np.asarray(prec[names[0]])
    for nm in names:
        a = np.asarray(prec[nm])
        out[nm] = {"precision": round(float(a.mean()), 4), "hit_rate": round(float(np.mean(hit[nm])), 4)}
        if nm != names[0]:
            d = ref - a
            bs = d[idx].mean(axis=1)
            out[nm]["model_minus_this"] = [round(float(d.mean()), 4), round(float(np.percentile(bs, 2.5)), 4),
                                           round(float(np.percentile(bs, 97.5)), 4)]
    c = ref - np.asarray(chance)
    bs = c[idx].mean(axis=1)
    out["model_minus_chance"] = [round(float(c.mean()), 4), round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
    return out


def r4(x: Any) -> Any:
    try:
        return None if x is None or not np.isfinite(x) else round(float(x), 4)
    except TypeError:
        return None


# ---------------------------------------------------------------------------------------------- the sport pipeline
#
# A sport adapter builds the panel (one DataFrame, columns below) and a Config; everything after that is shared:
# validation (research), the final fits on every labelled season, the team blocks and the payload.
#
# Panel columns: season, pid, tid, pos, age, yrs (years in the league; may be NaN), vnow (value now in the sport's
# currency, used for need, upgrade and targets), team_wp, team_traj, team_turn, the feature columns named in the Config,
# labels y_next (0/1/NaN), y_type (index into Config.types, -1 unknown), y_dl (0/1/NaN), dest (club joined by next
# season, None), dest_dl (club joined before the deadline, None).

@dataclass
class Config:
    level: str
    version: str
    feats: list
    quad: list
    dl_feats: list
    type_feats: list
    arr_feats: list
    types: tuple
    type_label: dict
    dev: list
    test: list
    slots: dict = field(default_factory=dict)
    contend: float = 0.53
    rebuild: float = 0.46
    unit: str = "WAR"
    age_pivot: float = 29.0
    why: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    yrs_phrase: str = "{n} seasons in the league"
    walk_from: int | None = None              # years in the league from which a target reads "at or near free agency"
    k: int = 10
    deadline_label: str = "traded"            # "traded" (typed history) or "traded or claimed" (box-score history)
    # In season, the previous season's "left by next season" label is only settled once the current season is over
    # (a player who opens elsewhere in December, or never plays): fit on seasons < s - 1 then, and live on seasons up
    # to two back. After the season every label of the previous season is settled at the snapshot (gap 0).
    inseason_gap: int = 1
    # the horizon of the team blocks (outlook, targets): None = before the deadline in season and by next season after
    # it; "next" = by next season always (the NFL, where in-season moves are rare)
    team_horizon: str | None = None


def gap_of(cfg: "Config", phase: str) -> int:
    return int(cfg.inseason_gap) if phase == "inseason" else 0


def dest_col_of(cfg: "Config", phase: str) -> str:
    return "dest" if (cfg.team_horizon == "next" or (cfg.team_horizon is None and phase == "offseason")) else "dest_dl"


def team_pos_table(df: pd.DataFrame, slots: dict) -> pd.DataFrame:
    """Per season, club and position: the incumbent's value (the slot-th best player there, e.g. the fifth starter;
    else the best), the club's strength there (the sum of its top slots), its percentile among clubs, need = 1 - it,
    and the expected departures there (the sum of the players' P(leave))."""
    out = []
    has_p = "p_next" in df.columns
    for (s, t, pos), g in df.groupby(["season", "tid", "pos"]):
        k = int(slots.get(pos, 1))
        vs = sorted(pd.to_numeric(g["vnow"], errors="coerce").fillna(0.0).tolist(), reverse=True)
        inc = vs[k - 1] if len(vs) >= k else 0.0
        out.append({"season": s, "tid": t, "pos": pos, "incumbent": inc, "strength": sum(vs[:k]), "n_pos": len(vs),
                    "exp_out": float(g["p_next"].sum()) if has_p else np.nan})
    tp = pd.DataFrame(out)
    if not len(tp):
        return tp
    tp["pct"] = tp.groupby(["season", "pos"])["strength"].rank(pct=True)
    tp["need"] = 1.0 - tp["pct"]
    return tp


def fill_grid(tp: pd.DataFrame, df: pd.DataFrame, positions: list[str]) -> pd.DataFrame:
    """Every club x position each season (a position with nobody on it is a full need)."""
    have = {(r.season, r.tid, r.pos) for r in tp.itertuples()}
    add = []
    for s, g in df.groupby("season"):
        for t in sorted(g["tid"].unique()):
            for pos in positions:
                if (s, t, pos) not in have:
                    add.append({"season": s, "tid": t, "pos": pos, "incumbent": 0.0, "strength": 0.0, "n_pos": 0, "exp_out": 0.0,
                                "pct": 0.0, "need": 1.0})
    return pd.concat([tp, pd.DataFrame(add)], ignore_index=True) if add else tp


def arrivals_rows(df: pd.DataFrame, tp: pd.DataFrame, dest_col: str) -> pd.DataFrame:
    """Per season x club x position: y = arrivals there (players on another club at the snapshot who joined), with the
    club's features."""
    arr = df[df[dest_col].notna()].groupby(["season", dest_col, "pos"]).size()
    team = df.groupby(["season", "tid"]).agg(team_wp=("team_wp", "first"), team_traj=("team_traj", "first"),
                                             team_turn=("team_turn", "first")).reset_index()
    R = tp.merge(team, on=["season", "tid"], how="left")
    R["y"] = [int(arr.get((s, t, p), 0)) for s, t, p in zip(R["season"], R["tid"], R["pos"])]
    # last season's arrivals there and the league's mean at the position (settled before the snapshot; used when a
    # sport's Config lists them)
    own = {(s, t, p): y for s, t, p, y in zip(R["season"], R["tid"], R["pos"], R["y"])}
    lg = R.groupby(["season", "pos"])["y"].mean().to_dict()
    R["arr_prev"] = [own.get((s - 1, t, p), np.nan) for s, t, p in zip(R["season"], R["tid"], R["pos"])]
    R["lg_prev"] = [lg.get((s - 1, p), np.nan) for s, p in zip(R["season"], R["pos"])]
    return R


DEST_FEATS = ["gain", "need", "wp_x_age", "wp_x_v", "turn", "exp_out_pos", "same_league"]


def _num(v, default):
    try:
        f = float(v)
        return default if f != f else f
    except (TypeError, ValueError):
        return default


def pair_features(c: Any, clubs: list[str], tpi: dict, team: dict, league: dict, age_pivot: float = 29.0) -> np.ndarray:
    """(clubs x DEST_FEATS) for candidate c (a panel row): his upgrade over the club's incumbent at his position, the
    club's need there, the club's strength x his age and x his value, the club's turnover, its expected departures at
    the position, same league/conference."""
    rows = []
    v = _num(c.vnow, 0.0)
    age = _num(c.age, age_pivot)
    for t in clubs:
        x = tpi.get((t, c.pos)) or {"incumbent": 0.0, "need": 1.0, "exp_out": 0.0}
        tm = team.get(t) or {}
        wp = _num(tm.get("team_wp"), 0.5) - 0.5
        rows.append([max(0.0, v - _num(x["incumbent"], 0.0)), _num(x["need"], 1.0), wp * (age - age_pivot) / 4.0, wp * v,
                     _num(tm.get("team_turn"), 0.3), _num(x["exp_out"], 0.0),
                     1.0 if league.get(t) and league.get(t) == league.get(c.tid) else 0.0])
    return np.asarray(rows, dtype=float)


def season_ctx(df_s: pd.DataFrame, tp_s: pd.DataFrame):
    tpi = {(r.tid, r.pos): {"incumbent": r.incumbent, "need": r.need, "exp_out": r.exp_out} for r in tp_s.itertuples()}
    team = df_s.groupby("tid").agg(team_wp=("team_wp", "first"), team_turn=("team_turn", "first")).to_dict("index")
    clubs = sorted(df_s["tid"].unique())
    return tpi, team, clubs


def fit_dest(df: pd.DataFrame, tp: pd.DataFrame, league: dict, seasons: list[int], dest_col: str, age_pivot: float = 29.0,
             l2: float = 1.0) -> dict | None:
    """Conditional logit of the destination club among the movers of `seasons` (choice set: every other club)."""
    Xs, ch = [], []
    for s in seasons:
        ds = df[df["season"] == s]
        tpi, team, clubs = season_ctx(ds, tp[tp["season"] == s])
        mv = ds[ds[dest_col].notna() & ds[dest_col].isin(clubs)]
        for c in mv.itertuples():
            alts = [t for t in clubs if t != c.tid]
            if getattr(c, dest_col) not in alts:
                continue
            Xs.append(pair_features(c, alts, tpi, team, league, age_pivot))
            ch.append(alts.index(getattr(c, dest_col)))
    if len(Xs) < 30:
        return None
    A = np.vstack(Xs)
    mu, sd = A.mean(axis=0), A.std(axis=0)
    sd[sd < 1e-9] = 1.0
    b = fit_clogit([(X - mu) / sd for X in Xs], ch, l2)
    return {"mu": mu, "sd": sd, "b": b, "n": len(Xs)}


def rank_targets(df_s: pd.DataFrame, tp_s: pd.DataFrame, league: dict, dfit: dict | None, age_pivot: float = 29.0,
                 pool_min: float = 0.0) -> dict:
    """{club: {"model": [(pid, P(joins), gain, P(club | moves), P(moves))] best first, "need_value": [pid] by upgrade,
    "avail": [pid] by upgrade x P(moves), "pool": n}} for one season. Candidates: players on other clubs with value above
    pool_min who would upgrade the club's incumbent at their position."""
    tpi, team, clubs = season_ctx(df_s, tp_s)
    out = {t: {"model": [], "need_value": [], "avail": []} for t in clubs}
    cands = df_s[pd.to_numeric(df_s["vnow"], errors="coerce").fillna(0) > pool_min]
    for c in cands.itertuples():
        alts = [t for t in clubs if t != c.tid]
        X = pair_features(c, alts, tpi, team, league, age_pivot)
        pdest = pred_clogit(dfit["b"], (X - dfit["mu"]) / dfit["sd"]) if dfit else np.full(len(alts), 1.0 / max(len(alts), 1))
        pl = _num(getattr(c, "p_next", None), 0.3)
        for j, t in enumerate(alts):
            if X[j, 0] <= 0:
                continue
            out[t]["model"].append((c.pid, pl * pdest[j], X[j, 0], pdest[j], pl))
    for t in clubs:
        L = out[t]["model"]
        out[t]["pool"] = len(L)
        out[t]["need_value"] = [r[0] for r in sorted(L, key=lambda r: -r[2])]
        out[t]["avail"] = [r[0] for r in sorted(L, key=lambda r: -(r[2] * r[4]))]
        out[t]["model"] = sorted(L, key=lambda r: -r[1])
    return out


def oof_next(df: pd.DataFrame, cfg: Config, l2: float, gap: int = 0) -> pd.Series:
    """P(leaves by next season) for every labelled row: walk-forward from the first dev season; earlier seasons from a fit
    on themselves (only ever a training input of the destination and arrival models, never scored)."""
    first = cfg.dev[0]
    p = pd.Series(np.nan, index=df.index)
    lab = sorted(df.loc[df["y_next"].notna(), "season"].unique())
    r = wf_binary(df, "y_next", cfg.feats, cfg.quad, [s for s in lab if s >= first], l2, gap=gap)
    if len(r):
        p.loc[r.index] = r["p"]
    early = df[(df["season"] < first) & df["y_next"].notna()]
    if len(early) and early["y_next"].nunique() > 1:
        d = Design(list(cfg.feats), list(cfg.quad)).fit(early)
        b = fit_logit(d.X(early), early["y_next"].to_numpy(float), l2)
        p.loc[early.index] = pred_logit(b, d.X(early))
    return p


def research(df: pd.DataFrame, cfg: Config, league: dict, phase: str, dev: list[int] | None = None,
             test: list[int] | None = None) -> dict:
    """The pre-registered validation of every block on the dev seasons (choices) and the sealed seasons."""
    import time as _t
    t0 = _t.perf_counter()
    dev = cfg.dev if dev is None else dev
    test = cfg.test if test is None else test
    df = df.copy()
    out: dict[str, Any] = {"version": cfg.version, "engine": VERSION, "phase": phase, "dev": dev, "test": test, "n_rows": int(len(df))}
    gap = gap_of(cfg, phase)
    out["gap"] = gap
    out["next"] = evaluate_binary(df, "y_next", cfg.feats, cfg.quad, dev, test, gap=gap)
    out["deadline"] = evaluate_binary(df, "y_dl", cfg.dl_feats, cfg.quad, dev, test, gap=gap)
    out["type"] = evaluate_type(df, cfg.type_feats, [], dev, test, K=len(cfg.types), gap=gap)
    df["p_next"] = oof_next(df, cfg, out["next"]["l2"], gap)
    dest_col = dest_col_of(cfg, phase)
    lab = df[df["season"] <= max(test or dev)]
    tp = fill_grid(team_pos_table(lab, cfg.slots), lab, sorted(df["pos"].dropna().unique()))
    out["arrivals"] = evaluate_arrivals(arrivals_rows(lab, tp, dest_col), cfg.arr_feats, dev, test, gap)
    groups: dict[str, list] = {"dev_eval": [], "test_eval": []}
    seasons = sorted(lab["season"].unique())
    for name, ss in (("dev_eval", dev), ("test_eval", test)):
        for s in ss:
            fit = fit_dest(lab, tp, league, [q for q in seasons if q < s - gap], dest_col, cfg.age_pivot)
            ds = lab[lab["season"] == s]
            ranks = rank_targets(ds, tp[tp["season"] == s], league, fit, cfg.age_pivot)
            for t, r in ranks.items():
                if r["pool"] < cfg.k:
                    continue
                pool = {z[0] for z in r["model"]}
                hits = set(ds.loc[ds[dest_col] == t, "pid"]) & pool
                groups[name].append({"key": f"{s}|{t}", "hits": hits, "pool": r["pool"],
                                     "rankings": {"model": [z[0] for z in r["model"]], "need_value": r["need_value"], "avail": r["avail"]}})
    out["targets"] = {name: topk_eval(g, cfg.k) for name, g in groups.items()}
    out["targets"]["k"] = cfg.k
    out["seconds"] = round(_t.perf_counter() - t0, 1)
    return json.loads(json.dumps(out, default=_jsonable))


def _jsonable(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    return str(o)


def published(res: dict) -> dict:
    pub = {k: bool(((res.get(k) or {}).get("test_eval") or {}).get("passed")) for k in ("next", "deadline", "type", "arrivals")}
    tt = (res.get("targets") or {}).get("test_eval") or {}
    m = tt.get("model") or {}
    pub["targets"] = bool(m and (m.get("precision") or 0) > 0
                          and ((tt.get("need_value") or {}).get("model_minus_this") or [0, 0])[1] > 0
                          and (tt.get("model_minus_chance") or [0, 0])[1] > 0)
    return pub


def reason(e: dict | None) -> str:
    e = e or {}
    g = e.get("ll_gain") or [0, 0, 0]
    if not e:
        return "Not published: too few labelled seasons to test it."
    if g[1] <= 0:
        return (f"Not published: on the sealed seasons the model did not beat the base rate with confidence (log-loss gain "
                f"{g[0]:.4f}, 95% CI {g[1]:.4f} to {g[2]:.4f}). The league base rate is shown instead.")
    return (f"Not published: on the sealed seasons the model beat the base rate (log-loss gain {g[0]:.4f}, 95% CI {g[1]:.4f} to "
            f"{g[2]:.4f}) but missed the calibration rule: it predicted {e.get('mean_p', 0) * 100:.1f}% and {e.get('rate', 0) * 100:.1f}% "
            f"happened (tolerance {e.get('cal_tol', 0) * 100:.1f} points; slope {e.get('cal_slope')}). The league base rate is shown instead.")


def why_words(cfg: Config, d: Design, b: np.ndarray, X: np.ndarray, rows: pd.DataFrame, top: int = 2) -> list[str]:
    """The features pushing each row's departure chance up the most, in words (Config.why: {feature: (high, low)})."""
    names = d.names()
    C = X * b[1:]
    out = []
    for row, xr, rec in zip(C, X, rows.to_dict("records")):
        words: list[str] = []
        for j in np.argsort(-row):
            if row[j] <= 0.05 or len(words) >= top:
                break
            nm = names[j]
            age, yrs = rec.get("age"), rec.get("yrs")
            if nm in ("age", "age^2") and age is not None and age == age:
                phrase = f"age {int(age)}"
            elif nm in ("yrs", "yrs^2", "fa_elig") and yrs is not None and yrs == yrs and xr[j] > 0:
                phrase = cfg.yrs_phrase.format(n=int(yrs))
            else:
                w = cfg.why.get(nm, (None, None))
                phrase = w[0] if xr[j] > 0 else w[1]
            if phrase and phrase not in words:
                words.append(phrase)
        out.append(", ".join(words))
    return out


def status_of(cfg: Config, wp: float) -> str:
    return "contending" if wp >= cfg.contend else ("rebuilding" if wp <= cfg.rebuild else "in the middle")


def _rr(x, nd=3):
    try:
        return None if x is None or x != x else round(float(x), nd)
    except (TypeError, ValueError):
        return None


def summary(ev: dict | None) -> dict | None:
    if not ev:
        return None
    keep = ("n", "clusters", "rate", "mean_p", "logloss", "logloss_base", "ll_gain", "ll_gain_pct", "brier", "brier_base", "brier_gain",
            "cal_slope", "cal_large", "cal_tol", "calibrated", "deciles", "passed", "poisson_deviance", "arrivals_per_team",
            "pred_per_team", "classes", "by_season")
    return {k: v for k, v in ev.items() if k in keep}


def predict_current(df: pd.DataFrame, cfg: Config, league: dict, res: dict, phase: str, cur: int) -> dict:
    """Final fits on every labelled season; predictions for the current season's rows."""
    df = df.copy()
    gap = gap_of(cfg, phase)
    lab_last = min(int(df.loc[df["y_next"].notna(), "season"].max()), cur - 1 - gap)
    dl_rows = df.loc[df["y_dl"].notna(), "season"]
    dl_last = min(int(dl_rows.max()), cur - 1 - gap) if len(dl_rows) else lab_last
    now = df[df["season"] == cur].copy()
    d, b, base_next = fit_final_binary(df, "y_next", cfg.feats, cfg.quad, res["next"]["l2"], lab_last)
    Xn = d.X(now)
    now["p_next"] = pred_logit(b, Xn)
    now["why"] = why_words(cfg, d, b, Xn, now)
    dd, bd, base_dl = fit_final_binary(df, "y_dl", cfg.dl_feats, cfg.quad, res["deadline"]["l2"], dl_last)
    now["p_dl"] = pred_logit(bd, dd.X(now))
    K = len(cfg.types)
    tl2 = (res.get("type") or {}).get("l2") or 3.0
    lv = df[(df["y_next"] == 1) & (df["y_type"] >= 0) & (df["season"] <= lab_last)]
    if len(lv) and lv["y_type"].nunique() == K:
        dt, Bt, shares = fit_final_type(df, cfg.type_feats, [], tl2, lab_last, K)
        type_ok = bool(((res.get("type") or {}).get("test_eval") or {}).get("passed"))
        Q = pred_mnl(Bt, dt.X(now)) if type_ok else np.tile(shares, (len(now), 1))
    else:
        shares = np.bincount(lv["y_type"].to_numpy(int), minlength=K) / max(len(lv), 1) if len(lv) else np.full(K, 1.0 / K)
        Q = np.tile(shares, (len(now), 1))
    for k, nm in enumerate(cfg.types):
        now["p_" + nm] = now["p_next"].to_numpy() * Q[:, k]
    df["p_next"] = oof_next(df, cfg, res["next"]["l2"], gap)
    df.loc[now.index, "p_next"] = now["p_next"]
    dest_col = dest_col_of(cfg, phase)
    tp = fill_grid(team_pos_table(df, cfg.slots), df, sorted(df["pos"].dropna().unique()))
    R_all = arrivals_rows(df, tp, dest_col)           # the current season's rows carry last season's arrivals too
    R = R_all[R_all["season"] <= lab_last]
    da, ba, pos_cols = fit_final_poisson(R, cfg.arr_feats, (res.get("arrivals") or {}).get("l2") or 1.0, lab_last)
    Rn = R_all[R_all["season"] == cur].copy()
    Rn["lam"] = predict_poisson_rows(da, ba, pos_cols, Rn)
    seasons = [s for s in sorted(df["season"].unique()) if s <= lab_last]
    fit = fit_dest(df[df["season"] <= lab_last], tp, league, seasons, dest_col, cfg.age_pivot)
    ranks = rank_targets(now, tp[tp["season"] == cur], league, fit, cfg.age_pivot)
    base_arr = {str(pos): [_rr(float((g["y"] > 0).mean())), _rr(float(g["y"].mean()), 2)] for pos, g in R.groupby("pos")}
    return {"now": now, "tp": tp[tp["season"] == cur], "arr": Rn, "ranks": ranks, "base_next": base_next, "base_dl": base_dl,
            "base_arrivals": base_arr,
            "shares": shares, "coef_next": coef_table(d, b), "coef_dl": coef_table(dd, bd), "dest": fit, "lab_last": lab_last}


def payload(df: pd.DataFrame, cfg: Config, league: dict, res: dict, phase: str, cur: int, names: dict, snapshot: str,
            horizons: dict, extra: dict | None = None, n_targets: int = 10, target_bits=None) -> dict:
    """The movement payload (PAYLOADS.md "Movement"): every rostered player's chances, each club's outlook and targets,
    the validation and what was not published and why. Blocks that failed the pre-registered rule carry None / []."""
    P = predict_current(df, cfg, league, res, phase, cur)
    now = P["now"]
    pub = published(res)
    players = []
    for r in now.sort_values(["tid", "p_next"], ascending=[True, False]).itertuples():
        yrs = int(r.yrs) if r.yrs is not None and r.yrs == r.yrs else None
        players.append([r.pid, names.get(r.pid), r.tid, r.pos, _rr(r.age, 1), yrs, _rr(r.vnow, 2),
                        _rr(r.p_next) if pub["next"] else None,
                        *[(_rr(getattr(r, "p_" + t)) if pub["next"] else None) for t in cfg.types],
                        _rr(r.p_dl) if pub["deadline"] else None, r.why if pub["next"] else ""])
    teams = {}
    for t, g in now.groupby("tid"):
        wp = float(g["team_wp"].iloc[0])
        arr = P["arr"][P["arr"]["tid"] == t].sort_values("lam", ascending=False)
        outlook = [[a.pos, _rr(1 - math.exp(-a.lam)), _rr(a.lam, 2), _rr(a.need, 2), _rr(a.exp_out, 2), int(a.n_pos)] for a in arr.itertuples()]
        tg = []
        for pid, score, gain, pdest, pl in (P["ranks"].get(t) or {}).get("model", [])[:n_targets]:
            c = now[now["pid"] == pid].iloc[0]
            bits = [f"+{gain:.1f} {cfg.unit} over your {c['pos']} slot"]
            if _num(c["team_wp"], 0.5) <= cfg.rebuild:
                bits.append("his team is rebuilding")
            if cfg.walk_from is not None and c["yrs"] is not None and c["yrs"] == c["yrs"] and c["yrs"] >= cfg.walk_from:
                bits.append("at or near free agency")
            if target_bits is not None:
                bits.extend(target_bits(c) or [])
            bits.append(f"{round(pl * 100)}% chance he moves")
            tg.append([pid, names.get(pid), c["tid"], c["pos"], _rr(c["age"], 1), _rr(c["vnow"], 2), _rr(gain, 2), _rr(pl), _rr(score, 4),
                       "; ".join(bits)])
        teams[t] = {"wp": _rr(wp), "status": status_of(cfg, wp), "traj": _rr(float(g["team_traj"].iloc[0])),
                    "exp_departures": _rr(float(g["p_next"].sum()), 1) if pub["next"] else None,
                    "exp_arrivals": _rr(float(arr["lam"].sum()), 1) if pub["arrivals"] else None,
                    "outlook": outlook if pub["arrivals"] else [],
                    "targets": tg if pub["targets"] else []}
    val = {k: {"test": summary((res.get(k) or {}).get("test_eval")), "dev": summary((res.get(k) or {}).get("dev_eval")),
               "l2": (res.get(k) or {}).get("l2")} for k in ("next", "deadline", "type", "arrivals")}
    val["targets"] = {"k": (res.get("targets") or {}).get("k"), "test": (res.get("targets") or {}).get("test_eval"),
                      "dev": (res.get("targets") or {}).get("dev_eval")}
    reasons = {k: reason((res.get(k) or {}).get("test_eval")) for k in ("next", "deadline", "arrivals") if not pub[k]}
    if not pub["type"]:
        reasons["type"] = "The type split did not beat the training shares on the sealed seasons: the shares are shown."
    if not pub["targets"]:
        reasons["targets"] = "The target ranking did not beat both the need x value ranking and chance on the sealed seasons."
    out = {"ok": True, "level": cfg.level, "season": cur, "version": cfg.version, "engine": VERSION, "phase": phase, "snapshot": snapshot,
           "horizons": horizons, "deadline_label": cfg.deadline_label, "unit": cfg.unit,
           "team_horizon": "next" if dest_col_of(cfg, phase) == "dest" else "deadline",
           "types": list(cfg.types), "type_labels": cfg.type_label, "published": pub, "reasons": reasons,
           "base_rates": {"next": _rr(P["base_next"]), "deadline": _rr(P["base_dl"]),
                          "types": {t: _rr(v) for t, v in zip(cfg.types, P["shares"])}},
           "base_arrivals": P["base_arrivals"], "base_arrivals_fields": ["p_add", "mean_arrivals"],
           "player_fields": ["pid", "name", "team", "pos", "age", "yrs", "value", "p_next"] + ["p_" + t for t in cfg.types] + ["p_dl", "why"],
           "players": players,
           "team_fields": {"outlook": ["pos", "p_add", "exp_arrivals", "need", "exp_departures", "players"],
                           "targets": ["pid", "name", "team", "pos", "age", "value", "gain", "p_move", "p_join", "why"]},
           "teams": teams, "status_cuts": {"contending": cfg.contend, "rebuilding": cfg.rebuild},
           "drivers": {"next": P["coef_next"][:12], "deadline": P["coef_dl"][:12]},
           "validation": val, "split": {"dev": res.get("dev"), "test": res.get("test")}, "notes": cfg.notes}
    if extra:
        out.update(extra)
    return out


def research_cached(df: pd.DataFrame, cfg: Config, league: dict, phase: str, key_parts: list, path, max_age_days: float = 7.0,
                    read_json=None, write_json=None) -> dict:
    """research() cached at `path` on key_parts (the sport's phase bucket, seasons, ...) and the versions, for a week."""
    from datetime import datetime, timezone
    import json as _json
    from pathlib import Path as _P
    key = _json.dumps([cfg.version, VERSION, phase, cfg.dev, cfg.test] + list(key_parts), default=str)
    p = _P(path)
    got = None
    if p.exists():
        try:
            got = _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            got = None
    if got and got.get("key") == key:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(got["at"])).total_seconds() / 86400
        except (KeyError, ValueError):
            age = 99.0
        if age <= max_age_days:
            return got["res"]
    res = research(df, cfg, league, phase)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps({"key": key, "at": datetime.now(timezone.utc).isoformat(), "res": res}), encoding="utf-8")
    return res
