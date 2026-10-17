"""
Telemetry processing: per-lap summaries for every lap, and distance-based traces
for each driver's fastest lap, from the raw OpenF1 car data and location.

Raw data (sources/openf1.py) arrives at ~3.7 Hz for car data and ~3.7 Hz for
position, timestamped in ms from the session start. For each lap window
[t_start, t_start + lap_ms] of the session record:

  distance   integrated from speed: d += v · dt (v in m/s); the lap's distance is
             rescaled so every lap of a driver ends at the session's median lap
             length, which keeps different laps comparable point by point.
  summary    top speed, mean speed, full throttle (throttle ≥ 98) as a share of
             lap time, braking (brake > 0) share, coasting (throttle < 2, no brake)
             share, gear changes, DRS open seconds (DRS codes 10, 12, 14 = open),
             and the minimum speed at each corner.
  corners    found once per session on the reference lap (the fastest lap of the
             session): local minima of speed with a prominence of at least 25 km/h,
             at least 150 m apart, numbered in order along the lap. Each lap's
             corner minimum is the lowest speed within ±80 m of the reference apex.
  braking    for each corner, the distance before the apex at which the braking
             zone into it began (the last off-to-on brake transition within 400 m) — "braking point".
  trace      the fastest lap of each driver resampled every 10 m: speed, throttle,
             brake, gear, rpm, DRS, and x/y from the location feed (nearest sample).

Output (committed, read by the site): docs/paddock/data/<year>/telemetry/<session_key>.json
  {"session_key", "ref": {"driver", "lap", "length_m", "corners": [{"n", "d", "v"}]},
   "laps": {driver: [[lap, top, mean, full_throttle, braking, coasting, gear_changes, drs_s], ...]},
   "corner_min": {driver: {lap: [v per corner]}}, "brake_points": {driver: {lap: [m before apex per corner]}},
   "fastest": {driver: {"lap", "ms", "d": step, "speed": [...], "throttle": [...], "brake": [...], "gear": [...],
                        "rpm": [...], "drs": [...], "x": [...], "y": [...]}}}
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from oddsmarkets.f1.sources import openf1 as of

logger = logging.getLogger(__name__)

STEP_M = 10
DRS_OPEN = {10, 12, 14}
CORNER_PROMINENCE = 25.0
CORNER_GAP_M = 150.0
APEX_WINDOW_M = 80.0
BRAKE_LOOKBACK_M = 400.0
MIN_AVG_SPEED = 25.0         # m/s: a reference lap must integrate to at least this average speed (90 km/h)


def out_path(year: int, key: int) -> Path:
    return of.SITE_DATA / str(year) / "telemetry" / f"{key}.json"


def _arr(car: dict, k: str) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in car.get(k) or []], dtype=float)


def lap_slice(car: dict, t0: int, t1: int) -> dict[str, np.ndarray] | None:
    t = np.array(car["t"], dtype=float)
    m = (t >= t0) & (t <= t1)
    if m.sum() < 20:
        return None
    out = {"t": t[m]}
    for k in ("speed", "rpm", "gear", "throttle", "brake", "drs"):
        out[k] = _arr(car, k)[m]
    v = np.nan_to_num(out["speed"]) / 3.6
    dt = np.diff(out["t"], prepend=out["t"][0]) / 1000.0
    out["d"] = np.cumsum(v * dt)
    return out


def summarise(s: dict[str, np.ndarray]) -> list[float]:
    dt = np.diff(s["t"], prepend=s["t"][0]) / 1000.0
    total = float(dt.sum()) or 1.0
    thr, brk = np.nan_to_num(s["throttle"]), np.nan_to_num(s["brake"])
    gears = np.nan_to_num(s["gear"])
    drs = np.nan_to_num(s["drs"]).astype(int)
    return [
        round(float(np.nanmax(s["speed"])), 1), round(float(np.nanmean(s["speed"])), 1),
        round(100 * float(dt[thr >= 98].sum()) / total, 1), round(100 * float(dt[brk > 0].sum()) / total, 1),
        round(100 * float(dt[(thr < 2) & (brk <= 0)].sum()) / total, 1),
        int(np.count_nonzero(np.diff(gears) != 0)), round(float(dt[np.isin(drs, list(DRS_OPEN))].sum()), 1),
    ]


def find_corners(d: np.ndarray, v: np.ndarray) -> list[dict]:
    """Speed minima with enough prominence, in order along the lap."""
    v = np.nan_to_num(v, nan=np.nanmax(v) if np.isfinite(v).any() else 0.0)
    corners = []
    n = len(v)
    i = 1
    while i < n - 1:
        if v[i] <= v[i - 1] and v[i] < v[i + 1]:
            # prominence: rise to the higher of the nearest peaks on either side within 600 m
            lo, hi = i, i
            while lo > 0 and d[i] - d[lo] < 600:
                lo -= 1
            while hi < n - 1 and d[hi] - d[i] < 600:
                hi += 1
            prom = min(v[lo:i + 1].max(), v[i:hi + 1].max()) - v[i]
            if prom >= CORNER_PROMINENCE and (not corners or d[i] - corners[-1]["d"] >= CORNER_GAP_M):
                corners.append({"d": float(d[i]), "v": float(v[i])})
            elif prom >= CORNER_PROMINENCE and corners and v[i] < corners[-1]["v"]:
                corners[-1] = {"d": float(d[i]), "v": float(v[i])}
        i += 1
    for k, c in enumerate(corners, start=1):
        c["n"] = k
        c["d"], c["v"] = round(c["d"]), round(c["v"], 1)
    return corners


def corner_values(s: dict[str, np.ndarray], scale: float, corners: list[dict]) -> tuple[list, list]:
    d = s["d"] * scale
    v = np.nan_to_num(s["speed"], nan=999.0)
    brk = np.nan_to_num(s["brake"])
    mins, brakes = [], []
    for c in corners:
        w = (d >= c["d"] - APEX_WINDOW_M) & (d <= c["d"] + APEX_WINDOW_M)
        mins.append(round(float(v[w].min()), 1) if w.any() else None)
        # The start of the braking zone that leads into this apex: the last
        # off-to-on brake transition before the apex, within the look-back.
        a = np.where((d >= c["d"] - BRAKE_LOOKBACK_M) & (d <= c["d"]))[0]
        start = None
        for j in a[::-1]:
            if j > 0 and brk[j] > 0 and brk[j - 1] <= 0:
                start = j
                break
        brakes.append(round(float(c["d"] - d[start])) if start is not None else None)
    return mins, brakes


def trace(s: dict[str, np.ndarray], scale: float, length: float, loc: dict | None) -> dict:
    d = s["d"] * scale
    grid = np.arange(0, length, STEP_M)
    out: dict[str, Any] = {"d": STEP_M}
    for k in ("speed", "throttle", "brake", "gear", "rpm", "drs"):
        y = np.nan_to_num(s[k])
        out[k] = np.round(np.interp(grid, d, y)).astype(int).tolist() if k != "drs" else np.interp(grid, d, y, left=0, right=0).round().astype(int).tolist()
    if loc and loc.get("t"):
        lt = np.array(loc["t"], dtype=float)
        lx, ly = np.array(loc["x"], dtype=float), np.array(loc["y"], dtype=float)
        tq = np.interp(grid, d, s["t"])
        idx = np.clip(np.searchsorted(lt, tq), 0, len(lt) - 1)
        out["x"], out["y"] = lx[idx].round().astype(int).tolist(), ly[idx].round().astype(int).tolist()
    return out


def process_session(year: int, key: int) -> dict | None:
    """Summaries for every lap of every driver with telemetry on disk; None if the session record or telemetry is missing."""
    p = of.session_path(year, key)
    if not p.exists():
        return None
    rec = json.loads(p.read_text(encoding="utf-8"))
    laps = rec.get("laps") or {}
    tele: dict[str, dict] = {}
    for dn in laps:
        t = of.load_telemetry(year, key, int(dn))
        if t and t.get("car", {}).get("t"):
            tele[dn] = t
    if not tele:
        return None
    # Reference lap: the fastest timed lap whose telemetry covers it (a lap whose car data is missing or frozen
    # integrates to no distance and is passed over: 2025 session 9870's fastest lap did).
    cands = sorted(((r[2], dn, r[0], r[1]) for dn, rows in laps.items() if dn in tele
                    for r in rows if r[1] is not None and r[2]), key=lambda c: c[0])
    best = ref_s = None
    for ms, dn, lap, t0 in cands[:50]:
        sl = lap_slice(tele[dn]["car"], t0, t0 + ms)
        if sl is not None and float(sl["d"][-1]) > MIN_AVG_SPEED * ms / 1000.0:
            best, ref_s = (dn, lap, ms, t0), sl
            break
    if best is None:
        return None
    length = float(ref_s["d"][-1])
    corners = find_corners(ref_s["d"], ref_s["speed"])
    out: dict[str, Any] = {"session_key": key, "ref": {"driver": best[0], "lap": best[1], "length_m": round(length), "corners": corners},
                           "laps": {}, "corner_min": {}, "brake_points": {}, "fastest": {}}
    for dn, rows in laps.items():
        if dn not in tele:
            continue
        car, fastest = tele[dn]["car"], None
        for r in rows:
            lap, t_start, ms = r[0], r[1], r[2]
            if t_start is None or not ms:
                continue
            s = lap_slice(car, t_start, t_start + ms)
            if s is None or not s["d"][-1] > 0 or s["d"][-1] < 0.8 * length or s["d"][-1] > 1.25 * length:
                continue                  # partial or pit-lane-distorted lap
            scale = length / float(s["d"][-1])
            out["laps"].setdefault(dn, []).append([lap] + summarise(s))
            mins, brakes = corner_values(s, scale, corners)
            out["corner_min"].setdefault(dn, {})[str(lap)] = mins
            out["brake_points"].setdefault(dn, {})[str(lap)] = brakes
            if fastest is None or ms < fastest[1]:
                fastest = (lap, ms, s, scale)
        if fastest:
            tr = trace(fastest[2], fastest[3], length, tele[dn].get("loc"))
            tr.update({"lap": fastest[0], "ms": fastest[1]})
            out["fastest"][dn] = tr
    return out


def write_session(year: int, key: int) -> Path | None:
    out = process_session(year, key)
    if out is None:
        return None
    p = out_path(year, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return p
