"""Similar players, one recipe for every site (docs/METRICS_SPEC.md, "Similar players").

    features  the peer group's similarity features (docs/_design/metrics/<sport>.json groups[].similar.features)
    z         each feature z-scored within the pool the caller passes (group and season, over qualified players)
    weights   the feature's year-to-year r, floored at 0.2 (the spec's weight_values / weights, else the metric's yoy_r)
    distance  weighted Euclidean over the features both rows have, divided by the weight used:
              d = sqrt(sum_f w_f (z_a,f - z_b,f)^2 / sum_f w_f)   (an RMS z gap: 0 = identical, about 1.4 = two random rows)
    k         5 (the group's k)

The builders call `group_config` for the features and weights, `zscore` on the pool and `nearest` per row, so every
payload's neighbours come from the same code. `similarity(d)` turns a distance into the 0-100 score the older list
payloads carried in their last column (100 = identical; 100 exp(-d)).
"""
from __future__ import annotations

import functools
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

SPEC_DIR = Path(__file__).resolve().parents[2] / "docs" / "_design" / "metrics"
W_FLOOR = 0.2
K_DEFAULT = 5


@functools.lru_cache(maxsize=None)
def spec(sport: str) -> dict:
    """docs/_design/metrics/<sport>.json, or {} when it is missing or broken (the builders then use their fallback)."""
    try:
        return json.loads((SPEC_DIR / f"{sport}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _weight(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return W_FLOOR
    return max(W_FLOOR, x) if math.isfinite(x) else W_FLOOR


def group_config(sport: str, group_id: str, fallback: dict | None = None) -> dict | None:
    """{"features": [...], "weights": {f: w}, "k": k} for one spec group, weights floored at 0.2.

    Weights come from the group's `similar.weight_values`, else `similar.weights` when it is a dict, else the metric's
    own `yoy_r` in the group's metric list, else the floor. `fallback` ({"features", "weights", "k"}) is used when the
    spec file or group is missing, so a build never depends on the docs folder being present."""
    g = next((x for x in spec(sport).get("groups") or [] if x.get("id") == group_id), None)
    sim = (g or {}).get("similar") or {}
    feats = list(sim.get("features") or [])
    if not feats:
        if not fallback:
            return None
        return {"features": list(fallback["features"]),
                "weights": {f: _weight((fallback.get("weights") or {}).get(f)) for f in fallback["features"]},
                "k": int(fallback.get("k") or K_DEFAULT)}
    wv = sim.get("weight_values")
    if not isinstance(wv, dict):
        wv = sim.get("weights") if isinstance(sim.get("weights"), dict) else {}
    yoy = {m.get("id"): m.get("yoy_r") for m in (g or {}).get("metrics") or []}
    w = {f: _weight(wv[f] if f in wv else yoy.get(f)) for f in feats}
    return {"features": feats, "weights": w, "k": int(sim.get("k") or K_DEFAULT)}


def matrix(rows: Sequence[dict], features: Sequence[str], get=None) -> np.ndarray:
    """(n, f) float matrix of the rows' feature values, NaN where missing or not a finite number."""
    get = get or (lambda r, f: (r.get("values") or {}).get(f))
    out = np.full((len(rows), len(features)), np.nan)
    for i, r in enumerate(rows):
        for j, f in enumerate(features):
            v = get(r, f)
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(x):
                out[i, j] = x
    return out


def zscore(X: np.ndarray, groups: Iterable | None = None) -> np.ndarray:
    """Column z-scores ignoring NaN, within each value of `groups` (e.g. season) when given. A column with no spread
    in a group gets z 0 where present (it then says nothing about the distance)."""
    X = np.asarray(X, float)
    Z = np.full_like(X, np.nan)
    keys = np.zeros(len(X), dtype=object) if groups is None else np.asarray(list(groups), dtype=object)
    for g in dict.fromkeys(keys.tolist()):
        m = keys == g
        sub = X[m]
        with np.errstate(invalid="ignore"):
            n = np.sum(np.isfinite(sub), axis=0)
            mu = np.where(n > 0, np.nansum(sub, axis=0) / np.maximum(n, 1), 0.0)
            var = np.where(n > 1, np.nansum((sub - mu) ** 2, axis=0) / np.maximum(n - 1, 1), 0.0)
        sd = np.sqrt(var)
        safe = np.where(sd > 0, sd, 1.0)
        z = (sub - mu) / safe
        z = np.where(sd > 0, z, np.where(np.isfinite(sub), 0.0, np.nan))
        Z[m] = z
    return Z


def distances(Z: np.ndarray, i: int, w: np.ndarray, min_weight: float = 0.5) -> np.ndarray:
    """Weighted RMS z distance from row i to every row over the features both have (inf where they share less than
    `min_weight` of the total weight, or for row i itself)."""
    Z = np.asarray(Z, float)
    w = np.asarray(w, float)
    a = Z[i]
    both = np.isfinite(Z) & np.isfinite(a)
    wb = np.where(both, w, 0.0)
    num = np.sum(wb * np.where(both, (np.nan_to_num(Z) - np.nan_to_num(a)) ** 2, 0.0), axis=1)
    den = wb.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = np.sqrt(num / den)
    d[den < min_weight * w.sum()] = np.inf
    d[~np.isfinite(d)] = np.inf
    d[i] = np.inf
    return d


def nearest(Z: np.ndarray, i: int, w: np.ndarray, k: int = K_DEFAULT, allowed: np.ndarray | None = None,
            min_weight: float = 0.5) -> list[tuple[int, float]]:
    """The k nearest rows to row i as [(index, distance)], nearest first; `allowed` masks the candidates."""
    d = distances(Z, i, w, min_weight)
    if allowed is not None:
        d = np.where(np.asarray(allowed, bool), d, np.inf)
    n = int(np.isfinite(d).sum())
    if n == 0:
        return []
    k = min(k, n)
    idx = np.argpartition(d, k - 1)[:k] if k < len(d) else np.arange(len(d))
    idx = idx[np.argsort(d[idx], kind="stable")]
    return [(int(j), float(d[j])) for j in idx if np.isfinite(d[j])]


def similarity(d: float) -> float:
    """0-100 score from a distance: 100 exp(-d) (identical 100, a typical close neighbour 70-85, a random row ~25)."""
    return round(100.0 * math.exp(-d), 1) if math.isfinite(d) else 0.0
