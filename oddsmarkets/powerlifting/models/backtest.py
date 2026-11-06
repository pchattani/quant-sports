"""Sealed-year tests. TRAIN through 2019, VALID 2020-2022 (choices), TEST 2023-2025 (scored once, reported).

Totals: RMSE / MAE of expected DOTS against actual DOTS for lifters with at least one earlier scored meet, against
simple baselines (the last meet, the decayed-mean rating alone). Comparisons are paired: the mean gain in squared
error per lifter-meet with a 95% interval clustered by meet (lifters in one meet share a day, a platform and judges).

Podium: P(top three in the flight) from the simulation against simpler rules, scored by Brier and log loss on flights
of four or more, with the same clustered paired interval. The promotion rule: a component goes live only when the
interval on the sealed test excludes zero in its favour, with no loss of calibration.
"""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from . import ratings as R

TRAIN_END = "2019-12-31"
VALID_END = "2022-12-31"
TEST_END = "2025-12-31"
WINDOWS = {"train": ("1990-01-01", TRAIN_END), "valid": (TRAIN_END, VALID_END), "test": (VALID_END, TEST_END)}
GRID = [R.Params(half_life=h, k0=k) for h in (90.0, 180.0, 365.0, 730.0) for k in (0.02, 0.1, 0.5, 1.5, 4.0)]


def _f(x):
    return None if x is None or not np.isfinite(x) else float(x)


def window(df: pd.DataFrame, name: str, col: str = "date") -> pd.DataFrame:
    a, b = WINDOWS[name]
    return df[(df[col] > a) & (df[col] <= b)]


def errors(actual, pred) -> dict:
    a, p = np.asarray(actual, dtype=float), np.asarray(pred, dtype=float)
    ok = np.isfinite(a) & np.isfinite(p)
    if ok.sum() < 3:
        return {"n": int(ok.sum()), "rmse": None, "mae": None, "bias": None, "r": None}
    e = a[ok] - p[ok]
    return {"n": int(ok.sum()), "rmse": _f(np.sqrt(np.mean(e ** 2))), "mae": _f(np.mean(np.abs(e))),
            "bias": _f(np.mean(e)), "r": _f(np.corrcoef(a[ok], p[ok])[0, 1])}


def paired(loss_base, loss_new, cluster) -> dict:
    """Mean of (base - new) per row with a 95% interval clustered by `cluster`; > 0 means the new one is better."""
    d = pd.DataFrame({"d": np.asarray(loss_base, float) - np.asarray(loss_new, float), "c": np.asarray(cluster)})
    d = d[np.isfinite(d["d"])]
    n = len(d)
    if n < 30:
        return {"n": n, "diff": None, "lo": None, "hi": None, "better": False}
    mean = float(d["d"].mean())
    agg = d.groupby("c")["d"].agg(["sum", "size"])
    u = agg["sum"] - agg["size"] * mean
    se = float(np.sqrt((u ** 2).sum()) / n)
    lo, hi = mean - 1.96 * se, mean + 1.96 * se
    return {"n": n, "clusters": int(len(agg)), "diff": _f(mean), "lo": _f(lo), "hi": _f(hi), "better": bool(lo > 0)}


def score(walked: pd.DataFrame, start: str, end: str) -> dict:
    """The decayed-mean rating alone as a forecast (kept for the tuning grid)."""
    d = walked[(walked["date"] > start) & (walked["date"] <= end) & (walked["n"] > 0)]
    return errors(d["dots"], d["pre"])


def tune(rows: pd.DataFrame, grid: list[R.Params] = GRID) -> pd.DataFrame:
    """One row per (half_life, k0): the rating alone as a forecast. Chosen on training RMSE (then validation)."""
    m0 = R.stream_means(rows, TRAIN_END)
    recs = []
    for p in grid:
        w, _ = R.walk(rows, p, m0=m0)
        s = {k: score(w, *WINDOWS[k]) for k in WINDOWS}
        recs.append({"half_life": p.half_life, "k0": p.k0, "train_rmse": s["train"]["rmse"], "valid_rmse": s["valid"]["rmse"],
                     "test_rmse": s["test"]["rmse"], "test_n": s["test"]["n"]})
    return pd.DataFrame(recs).sort_values(["train_rmse", "valid_rmse"]).reset_index(drop=True)


def brier_logloss(p, y) -> tuple[np.ndarray, np.ndarray]:
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    y = np.asarray(y, float)
    return (p - y) ** 2, -(y * np.log(p) + (1 - y) * np.log(1 - p))


def reliability(p, y, bins=(0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001)) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum() >= 50:
            out.append({"lo": round(lo, 2), "hi": round(min(hi, 1.0), 2), "n": int(m.sum()), "pred": round(float(p[m].mean()), 4),
                        "actual": round(float(y[m].mean()), 4)})
    return out


def params_json(p: R.Params) -> dict:
    return asdict(p)
