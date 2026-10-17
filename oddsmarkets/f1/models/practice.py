"""
Practice pace: what the Friday/Saturday sessions say before qualifying (OpenF1 session records, 2023 on).

Two measurements per driver, both in % of lap against the field (negative = faster), from the sessions of the
weekend that start before Grand Prix qualifying (by the OpenF1 start times): Practice 1-3 and, on sprint weekends
from 2024, Sprint Qualifying and the Sprint (in 2023 both came after Grand Prix qualifying and are left out).

* ``long_pct``: long-run (race-simulation) pace. In each stint the laps within ``LONG_BAND`` of the stint's
  lower quartile are kept (cool-down and traffic laps drop out), pit-out laps and the stint's last lap
  (in-lap) are removed, and a stint counts with at least ``LONG_MIN_LAPS`` such laps. Per session, a ridge
  least-squares fit ``y = 100 (lap / ref - 1) = a_driver + c_compound + g * tyre_age`` (ref the session's median
  long-run lap) gives each driver's effect ``a``; sessions are combined by laps. Sprint laps count as a long run.
* ``short_pct``: one-lap pace. Each driver's best lap (not a pit-out lap) as a % gap to the session's best,
  centred on the field; sessions combined with weights ``SHORT_W`` (later sessions and sprint qualifying,
  where cars run qualifying trim, weigh more).

``team_long_pct`` / ``team_short_pct`` average the team-mates (fuel and programme noise is shared within a
team less than across teams, and averaging halves the driver noise).

``practice_features(year, round)`` -> ``{"drivers": {driverId: {...}}, "sessions": [...]}``. Never raises;
empty without session records. Nothing here uses a session that starts after Grand Prix qualifying.
"""
from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from oddsmarkets.f1 import canon

logger = logging.getLogger(__name__)

SESSIONS = ("Practice 1", "Practice 2", "Practice 3", "Sprint Qualifying", "Sprint")
LONG_BAND = 1.03
LONG_MIN_LAPS = 5
SHORT_W = {"Practice 1": 0.5, "Practice 2": 1.0, "Practice 3": 1.5, "Sprint Qualifying": 3.0}
LONG_W = {"Practice 1": 0.7, "Practice 2": 1.0, "Practice 3": 0.7, "Sprint": 1.5}
RIDGE = 1e-3


def _laps(rec: dict, ids: dict[str, str]) -> dict[str, list[tuple[int, float, bool]]]:
    """{driverId: [(lap, lap_ms, pit_out)]} with lap times."""
    out: dict[str, list] = {}
    for num, rows in (rec.get("laps") or {}).items():
        d = ids.get(str(num))
        if not d:
            continue
        for r in rows or []:
            if len(r) < 3 or r[2] is None:
                continue
            out.setdefault(d, []).append((int(r[0]), float(r[2]), bool(r[9]) if len(r) > 9 and r[9] else False))
    return out


def _stints(rec: dict, ids: dict[str, str]) -> dict[str, list[tuple[int, int, str, int]]]:
    out: dict[str, list] = {}
    for s in rec.get("stints") or []:
        if len(s) < 6:
            continue
        d = ids.get(str(s[0]))
        if not d or s[2] is None:
            continue
        out.setdefault(d, []).append((int(s[2]), int(s[3] if s[3] is not None else s[2]), str(s[4] or "UNKNOWN").upper(),
                                      int(s[5] or 0)))
    return out


def long_runs(rec: dict, ids: dict[str, str], race: bool = False) -> tuple[dict[str, tuple[float, int]], dict]:
    """Per-driver long-run effect (% of lap, field-centred) and laps used, from one session."""
    laps, stints = _laps(rec, ids), _stints(rec, ids)
    rows = []                                                      # (driver, compound, age, lap_ms)
    for d, ls in laps.items():
        by_lap = {l: (ms, po) for l, ms, po in ls}
        for a, b, comp, age0 in stints.get(d) or [(min(by_lap), max(by_lap), "UNKNOWN", 0)]:
            stint = [(l, by_lap[l][0]) for l in range(a, b + 1) if l in by_lap and not by_lap[l][1] and l != b and l > 1]
            if race:
                stint = [(l, ms) for l, ms in stint]
            if len(stint) < LONG_MIN_LAPS:
                continue
            q25 = float(np.percentile([ms for _, ms in stint], 25))
            keep = [(l, ms) for l, ms in stint if 0.985 * q25 <= ms <= LONG_BAND * q25]
            if len(keep) < LONG_MIN_LAPS:
                continue
            for l, ms in keep:
                rows.append((d, comp, age0 + (l - a), ms))
    if len(rows) < 20:
        return {}, {"n": len(rows)}
    ref = float(np.median([r[3] for r in rows]))
    drivers = sorted({r[0] for r in rows})
    comps = sorted({r[1] for r in rows})
    di = {d: i for i, d in enumerate(drivers)}
    ci = {c: i for i, c in enumerate(comps)}
    nD, nC = len(drivers), len(comps)
    # columns: one per driver, one per compound but the first (the reference), the tyre-age slope
    X = np.zeros((len(rows), nD + nC))
    y = np.zeros(len(rows))
    for k, (d, c, age, ms) in enumerate(rows):
        X[k, di[d]] = 1.0
        if ci[c] > 0:
            X[k, nD + ci[c] - 1] = 1.0
        X[k, nD + nC - 1] = age
        y[k] = 100.0 * (ms / ref - 1.0)
    lam = np.full(nD + nC, RIDGE)
    lam[nD:nD + nC - 1] = 0.5                                      # compound offsets: mild shrinkage
    beta = np.linalg.solve(X.T @ X + np.diag(lam), X.T @ y)
    a = beta[:nD]
    cnt = {d: sum(1 for r in rows if r[0] == d) for d in drivers}
    m = float(np.mean(a))
    out = {d: (float(a[di[d]] - m), cnt[d]) for d in drivers}
    return out, {"n": len(rows), "ref_ms": ref, "deg_pct_per_lap": float(beta[nD + nC - 1]),
                 "compound_pct": {c: (0.0 if ci[c] == 0 else float(beta[nD + ci[c] - 1])) for c in comps}}


def short_runs(rec: dict, ids: dict[str, str]) -> dict[str, float]:
    """Per-driver best lap as % gap to the session best, field-centred (drivers within 107% only)."""
    laps = _laps(rec, ids)
    best = {d: min(ms for _, ms, po in ls if not po) for d, ls in laps.items() if any(not po for _, _, po in ls)}
    if len(best) < 5:
        return {}
    top = min(best.values())
    gaps = {d: 100.0 * (v / top - 1.0) for d, v in best.items() if v <= 1.07 * top}
    if len(gaps) < 5:
        return {}
    m = float(np.mean(list(gaps.values())))
    return {d: g - m for d, g in gaps.items()}


def practice_features(year: int, rnd: int) -> dict[str, Any]:
    """Long- and short-run practice pace for a round, from the sessions before Grand Prix qualifying."""
    try:
        lineup = canon.lineup(year, rnd)
    except Exception:                                              # pragma: no cover - defensive
        lineup = {}
    out: dict[str, Any] = {"drivers": {}, "sessions": []}
    lr_acc: dict[str, list[tuple[float, float]]] = {}
    sr_acc: dict[str, list[tuple[float, float]]] = {}
    try:                                                           # 2023 sprint weekends: GP qualifying on Friday,
        q_rec = canon.find_session(year, rnd, "Qualifying")        # before the sprint shootout and the sprint
    except Exception:                                              # pragma: no cover - defensive
        q_rec = None
    q_start = str((q_rec or {}).get("session", {}).get("date_start") or "")
    for name in SESSIONS:
        try:
            rec = canon.find_session(year, rnd, name)
        except Exception:                                          # pragma: no cover - defensive
            rec = None
        if not rec:
            continue
        start = str((rec.get("session") or {}).get("date_start") or "")
        if q_start and start and start >= q_start:                 # only sessions that start before qualifying
            continue
        ids = canon.session_driver_ids(year, rec, rnd)
        info = {"name": name, "key": (rec.get("session") or {}).get("session_key")}
        if name in LONG_W:
            lr, meta = long_runs(rec, ids, race=(name == "Sprint"))
            info["long_laps"] = meta.get("n", 0)
            for d, (v, n) in lr.items():
                lr_acc.setdefault(d, []).append((v, LONG_W[name] * n))
        if name in SHORT_W:
            sr = short_runs(rec, ids)
            info["short_drivers"] = len(sr)
            for d, v in sr.items():
                sr_acc.setdefault(d, []).append((v, SHORT_W[name]))
        out["sessions"].append(info)
    drv: dict[str, dict] = {}
    for d in set(lr_acc) | set(sr_acc):
        e: dict[str, Any] = {"team": lineup.get(d)}
        if d in lr_acc:
            w = sum(x[1] for x in lr_acc[d])
            e["long_pct"], e["long_laps"] = sum(v * x for v, x in lr_acc[d]) / w, w
        if d in sr_acc:
            w = sum(x[1] for x in sr_acc[d])
            e["short_pct"], e["short_w"] = sum(v * x for v, x in sr_acc[d]) / w, w
        drv[d] = e
    for key in ("long_pct", "short_pct"):
        vals = [e[key] for e in drv.values() if key in e]
        if vals:
            m = float(np.mean(vals))
            for e in drv.values():
                if key in e:
                    e[key] -= m
        teams: dict[str, list[float]] = {}
        for e in drv.values():
            if key in e and e.get("team"):
                teams.setdefault(e["team"], []).append(e[key])
        for e in drv.values():
            t = e.get("team")
            if t in teams:
                e["team_" + key] = float(np.mean(teams[t]))
    out["drivers"] = drv
    return out


def blend_pct(mu: dict[str, float], x: dict[str, float], w: float) -> dict[str, float]:
    """Shift a field-relative pace prior toward a practice measurement: ``(1 - w) mu + w x`` for drivers with x,
    with x re-centred to the mean of mu over the same drivers (both are field-relative, % of lap)."""
    common = [d for d in mu if d in x and x[d] is not None and math.isfinite(x[d])]
    if not common or w == 0:
        return dict(mu)
    off = float(np.mean([mu[d] for d in common])) - float(np.mean([x[d] for d in common]))
    return {d: ((1 - w) * v + w * (x[d] + off)) if d in common else v for d, v in mu.items()}
