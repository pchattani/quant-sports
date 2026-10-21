"""
Market layer (MLB): the plate-appearance simulation corrected by what past closing lines say about the teams,
starters and parks. Added 21 October 2026 (docs/research/mlb_edge.md, "Model-improvement program, Oct 2026").

Only prices of games already played enter; the game being priced never sees its own market line.

Moneyline. For every finished game with a closing moneyline and a simulation price, r = logit(close) - logit(sim)
(how far the market sat from our simulation). An exponentially weighted ridge regression, refitted on the day,
explains r by an intercept, the two teams (home +1, away -1) and the two starters (home +1, away -1):
weights exp(-age / 60 days), x0.7 per season back, games of the last 400 days, ridge 1 per team and 2 per
starter. The published probability is Platt(logit(sim) + predicted r) with the committed Platt coefficients.

Totals. The same regression on r_t = (closing total + 10 x (fair P(over) - 0.5) + 0.44) - the simulation's mean
(0.44: runs scored above the closing total on average, 2016-2021, since the line is a median), with a
venue effect, both teams' offence, both teams' run prevention and both starters (ridge 1 each). The simulation's
distribution of total runs is shifted by the predicted r_t (the published distribution and expected total);
P(over L) = sigmoid(a + b logit P_shift(over L)) near the expected total (weight exp(-((L - mean) / 2.5)^2 / 2),
the shifted distribution further out), published for half-run and whole-run lines (pushes excluded).

Run line. P(home covers +-1.5) = sigmoid(a + b logit P_sim(cover) + c (logit p_layer - logit p_sim)).

Committed coefficients: fitted/market_layer_mlb.json (`fit_coefficients`, written by scripts/mlb_market_layer.py).
Walk-forward research version of the whole layer: `walk_forward` (monthly refits of the coefficients on earlier
games only, ratings refitted daily on earlier games only).

History in production: the walk-forward backtest's cached simulation prices (data/baseball/cache/backtest) and
the pre-game simulation prices the site build records in each season's manifest ("sim_prices"), joined to the
store's closing lines (`edge.game_prices`). Below MIN_ROWS usable games the layer is off and the simulation is
published as it is.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _dio

logger = logging.getLogger(__name__)

VERSION = 1
MIN_ROWS = 300
K_RUN = 10.0            # runs per unit of (fair P(over) - 0.5) at the closing total
MEAN_OFFSET = 0.44      # runs scored above that line on average (2016-2021: the line is a median, totals skew right)
CFG_ML = {"tau": 60.0, "carry": 0.7, "window": 400, "lam": {"team": 1.0, "sp": 2.0}}
CFG_TOT = {"tau": 60.0, "carry": 0.7, "window": 400, "lam": {"off": 1.0, "def": 1.0, "venue": 1.0, "sp": 1.0}}
TOT_BAND = 2.5          # runs: where the totals recalibration applies in full
FIT_PATH = Path(__file__).resolve().parent / "fitted" / "market_layer_mlb.json"
EPS = 1e-4


def logit(p):
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z):
    return 1 / (1 + np.exp(-np.asarray(z, float)))


def _ok(k) -> bool:
    return k is not None and str(k) not in ("None", "nan", "")


# ── designs ──────────────────────────────────────────────────────────────────

def ml_terms(home, away, sp_h, sp_a) -> list[tuple[str, Any, float]]:
    return [("team", str(home), 1.0), ("team", str(away), -1.0), ("sp", sp_h, 1.0), ("sp", sp_a, -1.0)]


def tot_terms(home, away, sp_h, sp_a, venue) -> list[tuple[str, Any, float]]:
    return [("off", str(home), 1.0), ("off", str(away), 1.0), ("def", str(home), 1.0), ("def", str(away), 1.0),
            ("venue", venue, 1.0), ("sp", sp_h, 1.0), ("sp", sp_a, 1.0)]


def _row_terms(d: pd.DataFrame, kind: str, sp_cols=("sp_home", "sp_away")) -> list[list]:
    h, a = d["home"].astype(str).tolist(), d["away"].astype(str).tolist()
    sh, sa = d[sp_cols[0]].tolist(), d[sp_cols[1]].tolist()
    if kind == "ml":
        return [ml_terms(*x) for x in zip(h, a, sh, sa)]
    v = d["venue"].tolist()
    return [tot_terms(*x) for x in zip(h, a, sh, sa, v)]


# ── the weighted ridge ───────────────────────────────────────────────────────

def _ordinal(x) -> int:
    return date.fromisoformat(str(x)[:10]).toordinal()


def _solve(terms: list[list], z: np.ndarray, w: np.ndarray, lam: dict) -> dict:
    """Weighted ridge with an (almost) free intercept: {"_": intercept, (block, key): coef}."""
    cols: dict = {}
    for ts in terms:
        for b, k, _ in ts:
            if _ok(k):
                cols.setdefault((b, str(k)), len(cols) + 1)
    p = len(cols) + 1
    A = np.zeros((p, p))
    rhs = np.zeros(p)
    for ts, zi, wi in zip(terms, z, w):
        idx = [0] + [cols[(b, str(k))] for b, k, _ in ts if _ok(k)]
        val = np.array([1.0] + [c for b, k, c in ts if _ok(k)])
        A[np.ix_(idx, idx)] += wi * np.outer(val, val)
        rhs[idx] += wi * zi * val
    pen = np.zeros(p)
    pen[0] = 1e-3
    for (b, k), j in cols.items():
        pen[j] = lam.get(b, 1.0)
    coef = np.linalg.solve(A + np.diag(pen), rhs)
    out = {"_": float(coef[0])}
    for key, j in cols.items():
        out[key] = float(coef[j])
    return out


def fit_ratings(hist: pd.DataFrame, target: str, kind: str, as_of: Any, cfg: dict) -> dict | None:
    """Ratings fitted on the rows of `hist` dated before `as_of` (ISO date) inside the window; None below MIN_ROWS."""
    d0 = _ordinal(as_of)
    h = hist[np.isfinite(hist[target].to_numpy(float))]
    day = np.array([_ordinal(x) for x in h["date"]])
    m = (day < d0) & (day >= d0 - cfg["window"])
    if m.sum() < MIN_ROWS:
        return None
    h = h[m]
    season = int(str(as_of)[:4])
    w = np.exp(-(d0 - day[m]) / cfg["tau"]) * cfg["carry"] ** (season - h["season"].to_numpy())
    return _solve(_row_terms(h, kind), h[target].to_numpy(float), w, cfg["lam"]) | {"n": int(m.sum())}


def predict(coef: dict | None, terms: list) -> float | None:
    if not coef:
        return None
    return coef["_"] + sum(c * coef.get((b, str(k)), 0.0) for b, k, c in terms if _ok(k))


def rolling(df: pd.DataFrame, target: str, kind: str, cfg: dict, sp_pred=("sp_home", "sp_away")) -> np.ndarray:
    """Walk-forward predictions for every row: ratings refitted each day on earlier rows only (research and the
    backtest). `sp_pred` names the starters a row is predicted with (e.g. a rotation guess)."""
    import scipy.sparse as sp
    d = df.reset_index(drop=True)
    day = np.array([_ordinal(x) for x in d["date"]])
    seas = d["season"].to_numpy()
    z = d[target].to_numpy(float)
    tt, tp = _row_terms(d, kind), _row_terms(d, kind, sp_pred)
    cols: dict = {}
    for terms in (tt, tp):
        for ts in terms:
            for b, k, _ in ts:
                if _ok(k):
                    cols.setdefault((b, str(k)), len(cols) + 1)

    def mk(terms):
        rr, cc, vv = list(range(len(d))), [0] * len(d), [1.0] * len(d)
        for i, ts in enumerate(terms):
            for b, k, c in ts:
                if _ok(k):
                    rr.append(i)
                    cc.append(cols[(b, str(k))])
                    vv.append(c)
        return sp.csr_matrix((vv, (rr, cc)), shape=(len(d), len(cols) + 1))
    X, XP = mk(tt), mk(tp)
    pen = np.zeros(X.shape[1])
    pen[0] = 1e-3
    for (b, k), j in cols.items():
        pen[j] = cfg["lam"].get(b, 1.0)
    pred = np.full(len(d), np.nan)
    coef = None
    for dd in np.unique(day):
        test = np.where(day == dd)[0]
        tr = np.where((day < dd) & (day >= dd - cfg["window"]) & np.isfinite(z))[0]
        if len(tr) >= MIN_ROWS:
            w = np.exp(-(dd - day[tr]) / cfg["tau"]) * cfg["carry"] ** (seas[test[0]] - seas[tr])
            Xt = X[tr]
            used = np.unique(np.r_[0, Xt.indices])
            Xu = Xt[:, used]
            A = (Xu.T @ Xu.multiply(w[:, None])).toarray() + np.diag(pen[used])
            coef = np.zeros(X.shape[1])
            coef[used] = np.linalg.solve(A, Xu.T @ (w * z[tr]))
        else:
            coef = None
        if coef is not None:
            pred[test] = XP[test] @ coef
    return pred


# ── turning ratings into published numbers ───────────────────────────────────

def ml_prob(p_sim: float, r: float | None, platt: list[float] | None) -> float:
    z = float(logit(p_sim)) + (r or 0.0)
    if platt:
        z = platt[0] + platt[1] * z
    return float(sigmoid(z))


def shift_dist(dist, delta: float) -> np.ndarray:
    """A distribution of totals 0..n-1 moved by `delta` runs (linear interpolation of the CDF; mass kept)."""
    d = np.asarray(dist, float)
    x = np.arange(len(d))
    c = np.interp(x, x + delta, np.cumsum(d), left=0.0, right=1.0)
    out = np.diff(np.concatenate([[0.0], c]))
    out[-1] += 1.0 - c[-1]
    out = np.clip(out, 0.0, None)
    return out / max(out.sum(), 1e-12)


def p_over_dist(d: np.ndarray, line: float) -> float | None:
    """P(total > line | not a push)."""
    k = np.arange(len(d))
    over, under = d[k > line].sum(), d[k < line].sum()
    return float(over / (over + under)) if over + under > 0 else None


def totals_curve(dist, r_t: float | None, recal: list[float] | None) -> tuple[np.ndarray, float]:
    """(published distribution of totals, its mean): the simulation's distribution shifted by r_t, with its tail
    probabilities recalibrated near the expected total (TOT_BAND) and the distribution rebuilt from them."""
    d = shift_dist(dist, r_t or 0.0)
    mu = float(np.arange(len(d)) @ d)
    if not recal:
        return d, mu
    n = len(d)
    tail = np.cumsum(d[::-1])[::-1]             # tail[k] = P(T >= k)
    new = tail.copy()
    for k in range(1, n):
        ps = float(tail[k])                      # P(T > k - 0.5)
        if not (0.0 < ps < 1.0):
            continue
        w = math.exp(-0.5 * ((k - 0.5 - mu) / TOT_BAND) ** 2)
        pr = float(sigmoid(recal[0] + recal[1] * float(logit(ps))))
        new[k] = w * pr + (1 - w) * ps
    new[0] = 1.0
    new = np.minimum.accumulate(new)            # tail probabilities must not rise
    out = np.clip(new - np.r_[new[1:], 0.0], 0.0, None)
    out = out / max(out.sum(), 1e-12)
    return out, float(np.arange(n) @ out)


def runline_prob(p_cover_sim: float, p_sim: float, p_layer: float, coef: list[float] | None) -> float:
    if not coef:
        return float(p_cover_sim)
    z = coef[0] + coef[1] * float(logit(p_cover_sim)) + coef[2] * (float(logit(p_layer)) - float(logit(p_sim)))
    return float(sigmoid(z))


# ── history (production) ─────────────────────────────────────────────────────

def _fair(a, b) -> float:
    from oddsmarkets.baseball.models import edge as E
    f = E.devig2(a, b)
    return f[0] if f else float("nan")


def sim_prices(level: str, season: int) -> dict[str, dict]:
    """{gpk: {"p", "t"}}: the simulation's pre-game prices of a season's games: the walk-forward backtest cache
    (variant "post", newest file wins) and the site build's ledger (manifest "sim_prices"), the ledger first."""
    out: dict[str, dict] = {}
    try:
        files = sorted((_dio.cache_root() / "backtest").glob(f"{level}_{season}_n*_v*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        files = []
    for p in files:
        if p.stem.endswith(("_open", "_open_rot")):
            continue
        try:
            res = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        for r in res.get("games") or []:
            if r.get("model") is not None:
                out[str(r["gpk"])] = {"p": float(r["model"]), "t": r.get("model_total")}
    mp = _dio.data_root() / level / str(season) / "manifest.json"
    try:
        led = (json.loads(mp.read_text(encoding="utf-8")).get("sim_prices") or {}) if mp.exists() else {}
    except Exception:  # noqa: BLE001
        led = {}
    for gpk, v in led.items():
        if isinstance(v, dict) and v.get("p") is not None:
            out[str(gpk)] = {"p": float(v["p"]), "t": v.get("t")}
    return out


def history(level: str, season: int, store: dict | None = None, seasons_back: int = 1) -> pd.DataFrame:
    """Finished games of `season` and the season before with a closing line and a simulation price:
    columns date, season, home, away, sp_home, sp_away, venue, z_c, r_c, r_t."""
    from oddsmarkets.baseball.models import edge as E
    rows = []
    for s in range(season - seasons_back, season + 1):
        st = store if (s == season and store is not None) else _dio.load_store(level, s)
        sims = sim_prices(level, s)
        for gpk, g in ((st or {}).get("games") or {}).items():
            if str(g.get("status")) != "final" or str(gpk) not in sims:
                continue
            pr = E.game_prices(g)
            c = (pr or {}).get("close") or {}
            ph = _fair(c.get("ml_h"), c.get("ml_a"))
            po = _fair(c.get("over"), c.get("under"))
            sim = sims[str(gpk)]
            prob = g.get("probables") or {}
            zc = float(logit(ph)) if np.isfinite(ph) else np.nan
            zt = (c["tot"] + (po - 0.5) * K_RUN + MEAN_OFFSET) if (c.get("tot") is not None and np.isfinite(po)) else np.nan
            rows.append({"gpk": str(gpk), "date": str(g.get("date"))[:10], "season": s, "home": str(g.get("home")),
                         "away": str(g.get("away")), "sp_home": prob.get("home"), "sp_away": prob.get("away"),
                         "venue": str(g.get("venue") or ""), "z_c": zc,
                         "r_c": zc - float(logit(sim["p"])),
                         "r_t": (zt - float(sim["t"])) if (sim.get("t") is not None and np.isfinite(zt)) else np.nan})
    return pd.DataFrame(rows)


def load_fit(path: Path | None = None) -> dict | None:
    p = path or FIT_PATH
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


class Layer:
    """The market layer as of one date (ratings fitted on games before it)."""

    def __init__(self, ml: dict | None, tot: dict | None, fit: dict | None, as_of: str):
        self.ml, self.tot, self.fit, self.as_of = ml, tot, fit or {}, as_of

    def apply(self, summary: dict, game: dict) -> dict:
        """The simulation's payload summary with the layer applied (the simulation's own numbers kept under "sim")."""
        if not summary or summary.get("p_home") is None or (self.ml is None and self.tot is None):
            return summary
        out = dict(summary)
        prob = game.get("probables") or {}
        h, a = str(game.get("home")), str(game.get("away"))
        sh, sa = prob.get("home"), prob.get("away")
        p_sim = float(summary["p_home"])
        out["sim"] = {"p_home": summary.get("p_home"), "runline": summary.get("runline"),
                      "total": (summary.get("runs") or {}).get("total")}
        info: dict = {"version": VERSION, "as_of": self.as_of}
        p_new = p_sim
        if self.ml is not None:
            r = predict(self.ml, ml_terms(h, a, sh, sa))
            p_new = ml_prob(p_sim, r, self.fit.get("platt"))
            out["p_home"] = round(p_new, 5)
            out["p_away"] = round(1 - p_new, 5)
            info["r_ml"] = round(float(r), 4)
            rl = dict(summary.get("runline") or {})
            coef = self.fit.get("runline")
            for key, opp in (("home_-1.5", "away_+1.5"), ("home_+1.5", "away_-1.5")):
                if rl.get(key) is not None and 0 < rl[key] < 1:
                    v = runline_prob(rl[key], p_sim, p_new, coef)
                    rl[key], rl[opp] = round(v, 5), round(1 - v, 5)
            out["runline"] = rl
        if self.tot is not None and summary.get("total_dist"):
            rt = predict(self.tot, tot_terms(h, a, sh, sa, str(game.get("venue") or "")))
            dist = shift_dist(summary["total_dist"], rt or 0.0)
            mu = float(np.arange(len(dist)) @ dist)
            curve, _ = totals_curve(summary["total_dist"], rt, self.fit.get("tot_recal"))
            # the chart keeps the simulated shape (moved by r_tot); P(over L) comes from the recalibrated curve, on
            # half-run lines and (pushes excluded) whole-run lines
            out["total_dist"] = [round(float(x), 5) for x in dist]
            out["over"] = {f"{L:.1f}": round(float(p_over_dist(curve, L)), 5) for L in np.arange(3.0, 16.0, 0.5)
                           if p_over_dist(curve, L) is not None}
            runs = dict(summary.get("runs") or {})
            if runs.get("total") is not None:
                dm = mu - float(runs["total"])
                runs.update(total=round(mu, 4), home=round(float(runs.get("home", 0)) + dm / 2, 4),
                            away=round(float(runs.get("away", 0)) + dm / 2, 4))
            out["runs"] = runs
            cdf = np.cumsum(dist)
            out["total_median"] = float(np.searchsorted(cdf, 0.5))
            info["r_tot"] = round(float(rt), 3)
        out["layer"] = info
        return out


def build(level: str, season: int, store: dict | None = None, as_of: Any = None) -> Layer | None:
    """The layer for pricing `season`'s games on `as_of` (today), MLB only; None when there is too little history."""
    if level != "mlb":
        return None
    as_of = str(as_of or date.today())[:10]
    try:
        hist = history(level, season, store)
    except Exception as exc:  # noqa: BLE001
        logger.info("market layer history failed: %s", exc)
        return None
    if not len(hist):
        return None
    ml = fit_ratings(hist, "r_c", "ml", as_of, CFG_ML)
    tot = fit_ratings(hist, "r_t", "tot", as_of, CFG_TOT)
    if ml is None and tot is None:
        return None
    return Layer(ml, tot, load_fit(), as_of)


# ── research: the walk-forward layer and the committed coefficients ──────────

def _wf_logistic(df: pd.DataFrame, fit_cols: list[str], target: str, apply_cols: list[str] | None = None,
                 min_train: int = 1500) -> np.ndarray:
    """Monthly expanding-window logistic regression fitted on earlier rows only."""
    from oddsmarkets.baseball.models import edge as E
    apply_cols = apply_cols or fit_cols
    per = df["date"].str[:7].to_numpy()
    Xf = np.c_[np.ones(len(df)), df[fit_cols].to_numpy(float)]
    Xa = np.c_[np.ones(len(df)), df[apply_cols].to_numpy(float)]
    y = df[target].to_numpy(float)
    okf, oka = np.isfinite(Xf).all(1), np.isfinite(Xa).all(1)
    pred = np.full(len(df), np.nan)
    for k in dict.fromkeys(per):
        tr = (per < k) & okf & np.isfinite(y)
        if tr.sum() >= min_train:
            b = E.fit_logistic(Xf[tr], y[tr], l2=1.0)
            t = (per == k) & oka
            pred[t] = sigmoid(Xa[t] @ b)
    return pred


def frame_targets(df: pd.DataFrame) -> pd.DataFrame:
    """Targets on a games frame (scripts/mlb_edge.assemble): close logit, residuals against the simulation."""
    d = df.sort_values(["date", "gpk"]).reset_index(drop=True).copy()
    d["z_c"] = np.where(np.isfinite(d["c_fair_h"]), logit(d["c_fair_h"].to_numpy()), np.nan)
    d["lm"] = logit(d["model"].to_numpy())
    d["r_c"] = d["z_c"] - d["lm"]
    d["r_t"] = d["c_tot"] + (d["c_fair_over"] - 0.5) * K_RUN + MEAN_OFFSET - d["model_total"]
    for c in ("sp_home", "sp_away", "rot_sp_h", "rot_sp_a"):
        if c in d:
            d[c] = d[c].astype(object).where(d[c].notna(), None)
    return d


def walk_forward(df: pd.DataFrame) -> pd.DataFrame:
    """
    The layer walk-forward on a games frame: ratings refitted daily and the Platt / totals / run-line coefficients
    refitted monthly, on earlier games only. Adds: mrr, mrr_rot, mrt, mrt_rot, p_layer (published moneyline at the
    close decision), p_layer_rot (open decision, rotation-guess starters and the open_rot simulation),
    po_layer (P(over the closing total)), po_layer_o (P(over the opening total)), p_rl_layer, p_rl_layer_o.
    """
    from oddsmarkets.baseball.models import edge as E
    d = frame_targets(df)
    d["mrr"] = rolling(d, "r_c", "ml", CFG_ML)
    d["mrt"] = rolling(d, "r_t", "tot", CFG_TOT)
    if "rot_sp_h" in d:
        d["mrr_rot"] = rolling(d, "r_c", "ml", CFG_ML, sp_pred=("rot_sp_h", "rot_sp_a"))
        d["mrt_rot"] = rolling(d, "r_t", "tot", CFG_TOT, sp_pred=("rot_sp_h", "rot_sp_a"))
    # moneyline: Platt on logit(sim) + r, refitted monthly
    d["z_layer_raw"] = d["lm"] + d["mrr"]
    d["p_layer_raw"] = sigmoid(d["z_layer_raw"])
    d["p_layer"] = _wf_logistic(d, ["z_layer_raw"], "y")
    d["p_layer"] = d["p_layer"].fillna(d["p_layer_raw"]).fillna(d["model"])
    if "model_rot" in d:
        d["z_layer_rot_raw"] = logit(d["model_rot"].to_numpy()) + d["mrr_rot"]
        d["p_layer_rot"] = _wf_logistic(d, ["z_layer_raw"], "y", ["z_layer_rot_raw"])
    # totals at the closing total: P_shift(over) and its monthly recalibration
    tot = d["total"].to_numpy(float)

    def shifted(dist_col, line_col, r_col):
        out = np.full(len(d), np.nan)
        for i, (dist, L, r) in enumerate(zip(d[dist_col], d[line_col], d[r_col])):
            if dist is not None and np.isfinite(L) and np.isfinite(r):
                out[i] = p_over_dist(shift_dist(dist, r), L)
        return out
    d["y_over"] = np.where(tot == d["c_tot"].to_numpy(float), np.nan, (tot > d["c_tot"].to_numpy(float)).astype(float))
    d["po_shift"] = shifted("total_dist", "c_tot", "mrt")
    d["lpo_shift"] = logit(np.clip(d["po_shift"].to_numpy(), 1e-3, 1 - 1e-3))
    d.loc[~np.isfinite(d["po_shift"]), "lpo_shift"] = np.nan
    # the monthly recalibration coefficients, then the published curve evaluated at the closing total
    d["po_layer"] = _published_over(d, "total_dist", "c_tot", "mrt", "lpo_shift", "y_over")
    if "total_dist_open" in d and "mrt_rot" in d:
        d["po_layer_o"] = _published_over(d, "total_dist_open", "o_tot", "mrt_rot", "lpo_shift", "y_over")
    # run line
    mg = d["margin"].to_numpy(float)
    for tag, dist_col, line_col, psim, pnew in (("c", "margin_dist", "c_rl", "model", "p_layer"),
                                                 ("o", "margin_dist_open", "o_rl", "model_rot", "p_layer_rot")):
        if dist_col not in d or pnew not in d:
            continue
        rl = d[line_col].to_numpy(float)
        d[f"y_rl_{tag}"] = np.where(mg + rl == 0, np.nan, ((mg + rl) > 0).astype(float))
        d[f"p_rl_sim_{tag}"] = [E.p_cover(m, L) if (m is not None and np.isfinite(L)) else np.nan for m, L in zip(d[dist_col], rl)]
        d[f"lrl_{tag}"] = logit(np.clip(d[f"p_rl_sim_{tag}"].to_numpy(float), 1e-3, 1 - 1e-3))
        d[f"dl_{tag}"] = logit(d[pnew].to_numpy()) - logit(d[psim].to_numpy())
    d["p_rl_layer"] = _wf_logistic(d, ["lrl_c", "dl_c"], "y_rl_c")
    if "lrl_o" in d:
        d["p_rl_layer_o"] = _wf_logistic(d, ["lrl_c", "dl_c"], "y_rl_c", ["lrl_o", "dl_o"])
    return d


def _published_over(d: pd.DataFrame, dist_col: str, line_col: str, r_col: str, fit_col: str, y_col: str) -> np.ndarray:
    """P(over the line) from the published totals curve, with recalibration coefficients refitted monthly on earlier
    games' (logit P_shift(over the closing total), result)."""
    from oddsmarkets.baseball.models import edge as E
    per = d["date"].str[:7].to_numpy()
    X = np.c_[np.ones(len(d)), d[fit_col].to_numpy(float)]
    y = d[y_col].to_numpy(float)
    ok = np.isfinite(X).all(1) & np.isfinite(y)
    out = np.full(len(d), np.nan)
    for k in dict.fromkeys(per):
        tr = (per < k) & ok
        coef = list(E.fit_logistic(X[tr], y[tr], l2=1.0)) if tr.sum() >= 1500 else None
        for i in np.where(per == k)[0]:
            dist, L, r = d[dist_col].iat[i], d[line_col].iat[i], d[r_col].iat[i]
            if dist is None or not np.isfinite(L) or not np.isfinite(r):
                continue
            curve, _ = totals_curve(dist, r, coef)
            out[i] = p_over_dist(curve, L)
    return out


def fit_coefficients(d: pd.DataFrame) -> dict:
    """The committed coefficients, fitted on every row of a walk_forward frame."""
    from oddsmarkets.baseball.models import edge as E

    def fit(cols, target):
        X = np.c_[np.ones(len(d)), d[cols].to_numpy(float)]
        y = d[target].to_numpy(float)
        ok = np.isfinite(X).all(1) & np.isfinite(y)
        return [round(float(b), 5) for b in E.fit_logistic(X[ok], y[ok], l2=1.0)], int(ok.sum())
    platt, n1 = fit(["z_layer_raw"], "y")
    recal, n2 = fit(["lpo_shift"], "y_over")
    rl, n3 = fit(["lrl_c", "dl_c"], "y_rl_c")
    return {"version": VERSION, "platt": platt, "tot_recal": recal, "runline": rl,
            "n": {"moneyline": n1, "totals": n2, "runline": n3},
            "seasons": [int(d["season"].min()), int(d["season"].max())], "cfg_ml": CFG_ML, "cfg_tot": CFG_TOT, "k_run": K_RUN,
            "mean_offset": MEAN_OFFSET}
