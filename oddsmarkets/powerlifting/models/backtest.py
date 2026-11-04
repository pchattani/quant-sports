"""Sealed-year test of the DOTS walk. TRAIN through 2019, VALID 2020-2022, TEST 2023-2025."""
from __future__ import annotations

from dataclasses import asdict

import numpy as np
import pandas as pd

from . import ratings as R

TRAIN_END = "2019-12-31"
VALID_END = "2022-12-31"
TEST_END = "2025-12-31"
GRID = [
    R.Params(half_life=h, k0=k) for h in (180.0, 270.0, 365.0, 540.0) for k in (2.0, 4.0, 8.0)
]


def _mean_m0(rows: pd.DataFrame, end: str) -> float:
    d = rows[rows["date"] <= end]
    return float(d["dots"].mean()) if len(d) else 400.0


def score(walked: pd.DataFrame, start: str, end: str) -> dict:
    """RMSE / MAE / r of pre-meet DOTS vs actual, only of lifters who already had a meet (n>0)."""
    d = walked[(walked["date"] > start) & (walked["date"] <= end) & (walked["n"] > 0)]
    if d.empty:
        return {"n": 0, "rmse": None, "mae": None, "r": None}
    resid = d["resid"].to_numpy(dtype=float)
    pre, act = d["pre"].to_numpy(dtype=float), d["dots"].to_numpy(dtype=float)
    def _f(x):
        return None if x is None or not np.isfinite(x) else float(x)
    r = _f(float(np.corrcoef(pre, act)[0, 1])) if len(d) > 2 else None
    return {"n": int(len(d)), "rmse": _f(np.sqrt(np.mean(resid ** 2))), "mae": _f(np.mean(np.abs(resid))), "r": r}


def run(rows: pd.DataFrame, p: R.Params) -> tuple[pd.DataFrame, dict]:
    m0 = _mean_m0(rows, TRAIN_END)
    walked, _ = R.walk(rows, R.Params(half_life=p.half_life, k0=p.k0, m0=m0, min_field=p.min_field))
    return walked, {
        "params": {**asdict(p), "m0": m0},
        "train": score(walked, "1990-01-01", TRAIN_END),
        "valid": score(walked, TRAIN_END, VALID_END),
        "test": score(walked, VALID_END, TEST_END),
    }


def tune(rows: pd.DataFrame, grid: list[R.Params] = GRID) -> pd.DataFrame:
    """One row per (half_life, k0); sort by training RMSE (then validation)."""
    recs = []
    for p in grid:
        _, s = run(rows, p)
        recs.append({"half_life": p.half_life, "k0": p.k0, "m0": s["params"]["m0"],
                     "train_rmse": s["train"]["rmse"], "valid_rmse": s["valid"]["rmse"],
                     "test_rmse": s["test"]["rmse"], "train_r": s["train"]["r"], "valid_r": s["valid"]["r"],
                     "test_r": s["test"]["r"], "test_n": s["test"]["n"]})
    return pd.DataFrame(recs).sort_values(["train_rmse", "valid_rmse"]).reset_index(drop=True)
