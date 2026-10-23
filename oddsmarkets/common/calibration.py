"""The "How sure are we?" calibration block the kit reads (docs/_design/quant.js QK.calib.find / QK.howSure):
{"n", "brier", "logloss", "base_rate", "mean_p", "reliability": [{"lo", "hi", "n", "mean_p", "freq"}]} for one binary
event (the home side wins, the first player wins ...), from walk-forward forecasts only. A site's calibration.json
carries it at metrics.model, the first place QK.calib.find looks after game_model.metrics.model.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

EPS = 1e-12


def reliability(p: Iterable[float], y: Iterable[float], bins: int = 10) -> list[dict]:
    """Equal-width forecast buckets over [0, 1] (the last one closed): predicted (mean_p) against observed (freq)."""
    p, y = np.asarray(list(p), float), np.asarray(list(y), float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= 1.0))
        if m.any():
            out.append({"lo": round(float(edges[i]), 2), "hi": round(float(edges[i + 1]), 2), "n": int(m.sum()),
                        "mean_p": round(float(p[m].mean()), 4), "freq": round(float(y[m].mean()), 4)})
    return out


def block(p: Iterable[float], y: Iterable[float], bins: int = 10) -> dict:
    """The block from forecasts p of a binary event and its outcomes y (0 / 1)."""
    p, y = np.asarray(list(p), float), np.asarray(list(y), float)
    ok = np.isfinite(p) & np.isfinite(y)
    p, y = p[ok], y[ok]
    if not len(p):
        return {"n": 0, "reliability": []}
    q = np.clip(p, EPS, 1 - EPS)
    return {"n": int(len(p)), "brier": round(float(np.mean((p - y) ** 2)), 5),
            "logloss": round(float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))), 5),
            "base_rate": round(float(y.mean()), 4), "mean_p": round(float(p.mean()), 4), "reliability": reliability(p, y, bins)}


def from_table(rows: list[dict], n: int | None = None, brier: float | None = None, logloss: float | None = None,
               p_key: str = "p_mean", y_key: str = "y_mean") -> dict | None:
    """The block from an existing bucket table ({lo, hi, n, <p_key>, <y_key>} rows) and its summary scores; base_rate
    and mean_p are the bucket-weighted means. None when the table is empty."""
    rel = [{"lo": r.get("lo"), "hi": r.get("hi"), "n": int(r["n"]), "mean_p": r[p_key], "freq": r[y_key]}
           for r in rows or [] if r.get("n") and r.get(p_key) is not None and r.get(y_key) is not None]
    if not rel:
        return None
    tot = sum(r["n"] for r in rel)
    return {"n": int(n) if n is not None else tot, "brier": brier, "logloss": logloss,
            "base_rate": round(sum(r["freq"] * r["n"] for r in rel) / tot, 4),
            "mean_p": round(sum(r["mean_p"] * r["n"] for r in rel) / tot, 4), "reliability": rel}
