"""
Race lap-time model: corrected race pace per driver for one Grand Prix.

Model (one race, clean laps only)
---------------------------------
For driver i (team t) on lap L, running compound c on tyres of age a:

    lap_{i,L} = team_t + dev_i                              (car + driver: "pace")
              + fuel * F_{i,L}                              (fuel load)
              + off_c + (g_c + tdeg_{t,c} + ddeg_{i,c}) * a  (tyre: compound offset + linear degradation)
              + e2 * P2(u_L) + e3 * P3(u_L)                 (track evolution, non-linear part)
              + k * traffic_{i,L}                           (dirty air, 2023-)
              + eps_{i,L}

* F is laps of fuel on board: laps remaining (N - L) since 2010, and laps to the
  driver's next stop (or the flag) in the 1994-2009 refuelling era.
* u_L maps lap 1..N onto [-1, 1]; P2, P3 are Legendre polynomials. The *linear* part
  of track evolution is not separable from fuel burn (both are linear in L), so the
  fuel coefficient reports the net linear lap trend: fuel burn plus linear rubbering-in.
  In the refuelling era fuel is not linear in L, so a linear P1(u) evolution term is added.
* Tyre age a is OpenF1's tyre_age_at_start + laps into the stint (2023-); before
  that it is laps since the last pit stop, on one "UNKNOWN" compound (new tyres assumed).
* traffic_{i,L} = max(0, 1 - interval/1.5 s) using the interval to the car ahead at the
  start of the lap (OpenF1 `lap_end` of lap L-1): 0 when clear, 1 when right behind.
  k is the full cost of sitting on a gearbox; traffic_cost = k * sum of traffic over
  the driver's clean laps.
* Fuel has a weak prior N(0.06, 0.05^2) s/lap (about 1.7 kg/lap at 0.035 s/kg); within a
  stint fuel burn and tyre wear are both linear in the lap, so fuel is identified only by
  the level change at pit stops and varied stop laps, and the prior steadies it when those
  are few.
* Team intercepts are free; dev_i (driver relative to team), tdeg (team relative to the
  compound slope) and ddeg (driver relative to team) are ridge-shrunk with prior sds
  0.5 s, 0.03 s/lap and 0.02 s/lap, and the track-evolution terms with 0.5 s. A driver
  with few laps is therefore pulled to his team-mate/compound mean.

Clean laps: lap 1, pit in- and out-laps (Jolpica pit stops, OpenF1 pit table, pit_out
flags, stint boundaries; with no pit data at all, pre-2011, a green lap > 110% of the
driver's median is taken as a stop), laps overlapping a Safety Car / VSC / red flag window
(OpenF1 race control, 2023-; a window never closed by a message ends at the leader's first
green lap), any lap whose field-median time is more than 7% above the race's
median (neutralisation detector used in every season; covers pre-2023), the lap after a
neutralised block (restart), and laps outside [93%, 110%] of the median clean lap are
removed. The rest are fitted by ridge-regularised weighted least squares with Huber IRLS
weights (k = 1.345 robust sd), so remaining outliers are down-weighted rather than trusted.

Output: pace_i = (team_t + dev_i) - mean over drivers, in seconds per lap (negative =
faster), with se from the posterior covariance sigma^2 (X'WX + Lambda)^-1, inflated by
(1 + rho)/(1 - rho) for the lag-1 autocorrelation rho of a driver's residuals.
"""
from __future__ import annotations

import re

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import scipy.linalg

from oddsmarkets.f1 import canon
from oddsmarkets.f1.store import ROOT

MODEL_VERSION = "laptime-2"
CACHE = ROOT / "data" / "f1" / "cache" / "pace"

NEUTRAL_FIELD_RATIO = 1.07      # field-median lap > 107% of race median => neutralised lap
CLEAN_BAND = (0.93, 1.10)       # hard outlier band around the median clean lap
TRAFFIC_WINDOW_S = 1.5          # car ahead within 1.5 s costs time
HUBER_K = 1.345
PRIOR_SD = {"team": 100.0, "dev": 0.5, "fuel": 0.05, "off": 10.0, "deg": 1.0, "tdeg": 0.03, "ddeg": 0.02,
            "traffic": 10.0, "evo": 0.5}
# Ridge priors are centred on zero except fuel: ~1.7 kg/lap at ~0.035 s/kg gives ~0.06 s per
# lap of fuel. With prior sd 0.05 it only matters when stints cannot separate fuel from wear.
PRIOR_MEAN = {"fuel": 0.06}
UNKNOWN = "UNKNOWN"


def _empty(reason: str) -> dict[str, Any]:
    return {"drivers": {}, "fuel_coef": None, "excluded": {}, "reason": reason}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


# ===================================================================== assembly

def _neutral_windows(rc: list, ref_ms: float) -> tuple[list[tuple[float, float, Any]], set[int]]:
    """Time windows (start ms, end ms, start lap) and leader laps under SC / VSC / red flag.

    SC: "SAFETY CAR DEPLOYED" .. "SAFETY CAR IN THIS LAP" (+1.5 laps); VSC: "VSC DEPLOYED" ..
    "VSC ENDING" (+20 s); red flag: flag RED / "RED FLAG" / "SESSION ABORTED" .. "SESSION
    STARTED" / track GREEN (+1 lap). A window never closed by a message ends at +inf and is
    resolved by the caller from the lap times (the first green lap after it).
    """
    wins: list[tuple[float, float, Any]] = []
    laps: set[int] = set()
    open_: dict[str, tuple[Any, Any]] = {}

    def close(kind: str, t: Any, lap: Any, pad: float) -> None:
        t0, l0 = open_.pop(kind)
        if t0 is not None and t is not None:
            wins.append((float(t0), float(t) + pad, l0))
        if l0 is not None and lap is not None:
            laps.update(range(int(l0), int(lap) + 1))

    rows = sorted((r for r in rc or [] if isinstance(r, (list, tuple)) and len(r) >= 8),
                  key=lambda r: (r[0] is None, r[0] or 0))
    for t, lap, cat, flag, scope, _sector, _dn, msg in (r[:8] for r in rows):
        m = str(msg or "").upper()
        fl = str(flag or "").upper()
        if cat == "SafetyCar" or ("SAFETY CAR" in m and cat != "Other"):
            kind = "vsc" if ("VSC" in m or "VIRTUAL" in m) else "sc"
            if "DEPLOYED" in m and kind not in open_:
                open_[kind] = (t, lap)
            elif kind in open_ and ("ENDING" in m or "IN THIS LAP" in m or "ENDED" in m):
                close(kind, t, lap, 20_000 if kind == "vsc" else 1.5 * ref_ms)
        red_on = fl == "RED" or re.search(r"(?<![A-Z])RED FLAG", m) is not None or (cat == "SessionStatus" and ("ABORTED" in m or "SUSPENDED" in m))
        if red_on and "red" not in open_:
            open_["red"] = (t, lap)
        elif "red" in open_ and ((fl == "GREEN" and str(scope or "").lower() == "track")
                                 or (cat == "SessionStatus" and ("STARTED" in m or "RESUMED" in m))):
            close("red", t, lap, ref_ms)
    for kind in list(open_):
        t0, l0 = open_.pop(kind)
        if t0 is not None:
            wins.append((float(t0), float("inf"), l0))
    return wins, laps


def assemble(race: dict, sess: dict | None = None, ids: dict[str, str] | None = None, team: dict[str, str] | None = None,
             year: int | None = None) -> tuple[list[dict], dict]:
    """Lap rows for one race with exclusion reasons, from the season-store race entry
    and (2023-) its OpenF1 race session record. `ids` maps OpenF1 car numbers to driverIds.

    Each row: driver, team, lap, lap_s, t0 (ms or None), compound, age, fuel, interval, excl.
    """
    info: dict[str, Any] = {}
    race = race or {}
    team = dict(team or {})
    for row in race.get("results") or []:
        team.setdefault(row.get("driver"), row.get("constructor"))
    ids = ids or {}
    refuel = year is not None and 1994 <= int(year) <= 2009

    of_laps = (sess or {}).get("laps") or {}
    use_of = bool(of_laps) and sum(1 for n in of_laps if str(n) in ids) >= max(3, len(of_laps) // 2)
    info["source"] = "openf1" if use_of else "jolpica"

    # raw laps: {driver: {lap: (lap_s, t0)}}
    raw: dict[str, dict[int, tuple[float | None, float | None]]] = defaultdict(dict)
    pit_out: dict[str, set[int]] = defaultdict(set)
    if use_of:
        for num, lst in of_laps.items():
            d = ids.get(str(num))
            if not d:
                continue
            for e in lst or []:
                if not e or e[0] is None:
                    continue
                ms = _f(e[2]) if len(e) > 2 else None
                raw[d][int(e[0])] = (ms / 1000 if ms else None, _f(e[1]))
                if len(e) > 9 and e[9]:
                    pit_out[d].add(int(e[0]))
    else:
        for d, lst in (race.get("laps") or {}).items():
            for i, ms in enumerate(lst or []):
                v = _f(ms)
                raw[d][i + 1] = (v / 1000 if v else None, None)
    if not raw:
        return [], {**info, "reason": "no lap times on disk"}

    n_laps = max(max(v) for v in raw.values())
    for row in race.get("results") or []:
        try:
            n_laps = max(n_laps, int(row.get("laps") or 0))
        except (TypeError, ValueError):
            pass

    # pit stops -> in-laps per driver
    in_laps: dict[str, set[int]] = defaultdict(set)
    for p in race.get("pitstops") or []:
        try:
            in_laps[p["driver"]].add(int(p["lap"]))
        except (KeyError, TypeError, ValueError):
            pass
    stints: dict[str, list[tuple[int, int | None, str, int]]] = defaultdict(list)
    if sess:
        for p in sess.get("pit") or []:
            d = ids.get(str(p[0]))
            if d and p[1] is not None:
                in_laps[d].add(int(p[1]))
        for d, laps in pit_out.items():
            in_laps[d].update(l - 1 for l in laps if l > 1)
        for s in sess.get("stints") or []:
            d = ids.get(str(s[0]))
            if not d or s[2] is None:
                continue
            comp = str(s[4] or UNKNOWN).upper()
            if comp in ("NONE", "", "TEST_UNKNOWN"):
                comp = UNKNOWN
            stints[d].append((int(s[2]), None if s[3] is None else int(s[3]), comp, int(s[5] or 0)))
            if (s[1] or 1) > 1 and int(s[2]) > 1:
                in_laps[d].add(int(s[2]) - 1)
    have_pits = any(in_laps.values())

    # neutralised laps: race control windows (OpenF1) and the field-median rule
    vals = [v[0] for laps in raw.values() for l, v in laps.items() if v[0] and l > 1]
    ref = float(np.median(vals)) if vals else 90.0
    wins, rc_laps = _neutral_windows((sess or {}).get("race_control") or [], ref * 1000) if sess else ([], set())
    by_lap: dict[int, list[float]] = defaultdict(list)
    for laps in raw.values():
        for l, v in laps.items():
            if v[0]:
                by_lap[l].append(v[0])
    meds = {l: float(np.median(x)) for l, x in by_lap.items() if len(x) >= 3 and l > 1}
    race_med = float(np.median(list(meds.values()))) if meds else ref
    neutral = {l for l, m in meds.items() if m > NEUTRAL_FIELD_RATIO * race_med}
    restart = {l + 1 for l in neutral if l + 1 not in neutral}
    # a window race control never closed ends when the leader starts the first green lap after it
    lead_t0: dict[int, float] = {}
    for laps in raw.values():
        for l, v in laps.items():
            if v[1] is not None:
                lead_t0[l] = min(lead_t0.get(l, float("inf")), v[1])
    resolved = []
    for w0, w1, l0 in wins:
        if math.isinf(w1):
            start = int(l0) if l0 is not None else min((l for l, t in lead_t0.items() if t >= w0), default=n_laps)
            green = next((l for l in range(start + 1, n_laps + 1) if l not in neutral and l in lead_t0), None)
            w1 = lead_t0[green] if green is not None else w0 + 5 * ref * 1000
            info.setdefault("unclosed_windows", 0)
            info["unclosed_windows"] += 1
        resolved.append((w0, w1))
    wins = resolved
    info["neutral_laps"] = sorted(neutral | ({l for l in rc_laps} if not wins else set()))

    # without any pit information (pre-2011), treat isolated slow green laps as stops
    if not have_pits:
        for d, laps in raw.items():
            own = [v[0] for l, v in laps.items() if v[0] and l > 1 and l not in neutral]
            if len(own) < 5:
                continue
            m = float(np.median(own))
            for l, v in laps.items():
                if v[0] and l > 1 and l not in neutral and l - 1 not in in_laps[d] and v[0] > 1.10 * m:
                    in_laps[d].add(l)
        info["pits_inferred"] = True

    ends: dict[str, dict[int, float | None]] = {}
    if sess and use_of:
        for num, lst in (sess.get("lap_end") or {}).items():
            d = ids.get(str(num))
            if d:
                ends[d] = {int(e[0]): _f(e[2]) for e in lst or [] if e and e[0] is not None and len(e) > 2}

    rows: list[dict] = []
    for d, laps in raw.items():
        ins = sorted(in_laps.get(d, ()))
        sts = sorted(stints.get(d, []))
        for l in sorted(laps):
            lap_s, t0 = laps[l]
            comp, age = UNKNOWN, None
            for (a, b, c, age0) in sts:
                if a <= l and (b is None or l <= b):
                    comp, age = c, age0 + (l - a)
            if age is None:
                last_in = max((x for x in ins if x < l), default=0)
                age = l - (last_in + 1)
            nxt = min((x for x in ins if x >= l), default=n_laps)
            fuel = (nxt - l) if refuel else (n_laps - l)
            interval = ends.get(d, {}).get(l - 1)
            excl = None
            if not lap_s:
                excl = "missing"
            elif l == 1:
                excl = "lap1"
            elif l in in_laps.get(d, ()) or (l - 1) in in_laps.get(d, ()) or l in pit_out.get(d, ()):
                excl = "pit"
            elif l in neutral or l in restart or (
                    t0 is not None and any(t0 < w1 and t0 + lap_s * 1000 > w0 for w0, w1 in wins)) or (
                    t0 is None and not wins and l in rc_laps):
                excl = "neutralised"
            rows.append({"driver": d, "team": team.get(d) or f"_{d}", "lap": l, "lap_s": lap_s, "t0": t0, "compound": comp,
                         "age": max(0, int(age)), "fuel": float(max(0, fuel)), "interval": interval, "excl": excl})

    clean = [r["lap_s"] for r in rows if r["excl"] is None]
    if clean:
        m = float(np.median(clean))
        for r in rows:
            if r["excl"] is None and not (CLEAN_BAND[0] * m <= r["lap_s"] <= CLEAN_BAND[1] * m):
                r["excl"] = "outlier"
    info["n_laps"] = n_laps
    info["refuel"] = refuel
    info["traffic"] = bool(sess and sess.get("lap_end")) and use_of
    return rows, info


# ===================================================================== fit

def _legendre(u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return 0.5 * (3 * u ** 2 - 1), 0.5 * (5 * u ** 3 - 3 * u)


def fit_race(rows: list[dict], n_laps: int | None = None, traffic: bool = False, refuel: bool = False,
             iters: int = 15) -> dict[str, Any]:
    """Fit the lap-time model to assembled rows (see module docstring); pure function."""
    excluded: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.get("excl"):
            excluded[r["excl"]] += 1
    use = [r for r in rows if not r.get("excl") and r.get("lap_s")]
    if len(use) < 10:
        out = _empty("fewer than 10 clean laps")
        out["excluded"] = dict(excluded)
        return out
    drivers = sorted({r["driver"] for r in use})
    teams = sorted({r["team"] for r in use})
    comps_count: dict[str, int] = defaultdict(int)
    for r in use:
        comps_count[r["compound"]] += 1
    comps = sorted(comps_count, key=lambda c: -comps_count[c])
    di = {d: i for i, d in enumerate(drivers)}
    ti = {t: i for i, t in enumerate(teams)}
    ci = {c: i for i, c in enumerate(comps)}
    team_of = {r["driver"]: r["team"] for r in use}
    n_laps = n_laps or max(r["lap"] for r in rows)

    y = np.array([r["lap_s"] for r in use], float)
    n = len(y)
    lapn = np.array([r["lap"] for r in use], float)
    u = 2 * (lapn - 1) / max(1, n_laps - 1) - 1
    age = np.array([r["age"] for r in use], float)
    fuel = np.array([r["fuel"] for r in use], float)
    tr = np.zeros(n)
    if traffic:
        for k, r in enumerate(use):
            iv = r.get("interval")
            if iv is not None and 0 < iv < TRAFFIC_WINDOW_S:
                tr[k] = 1 - iv / TRAFFIC_WINDOW_S
    has_traffic = traffic and tr.sum() > 0

    cols: list[tuple[str, Any, np.ndarray]] = []    # (kind, key, column)
    for t in teams:
        cols.append(("team", t, np.array([1.0 if r["team"] == t else 0.0 for r in use])))
    for d in drivers:
        cols.append(("dev", d, np.array([1.0 if r["driver"] == d else 0.0 for r in use])))
    cols.append(("fuel", None, fuel))
    for c in comps[1:]:
        cols.append(("off", c, np.array([1.0 if r["compound"] == c else 0.0 for r in use])))
    for c in comps:
        cols.append(("deg", c, np.array([a if r["compound"] == c else 0.0 for r, a in zip(use, age)])))
    tc_pairs = sorted({(r["team"], r["compound"]) for r in use})
    for (t, c) in tc_pairs:
        cols.append(("tdeg", (t, c), np.array([a if (r["team"], r["compound"]) == (t, c) else 0.0 for r, a in zip(use, age)])))
    dc_pairs = sorted({(r["driver"], r["compound"]) for r in use})
    for (d, c) in dc_pairs:
        cols.append(("ddeg", (d, c), np.array([a if (r["driver"], r["compound"]) == (d, c) else 0.0 for r, a in zip(use, age)])))
    if has_traffic:
        cols.append(("traffic", None, tr))
    p2, p3 = _legendre(u)
    cols.append(("evo", 2, p2))
    cols.append(("evo", 3, p3))
    if refuel:
        cols.append(("evo", 1, u))
    X = np.column_stack([c[2] for c in cols])
    prior_sd = np.array([PRIOR_SD[c[0]] for c in cols])
    prior_mu = np.array([PRIOR_MEAN.get(c[0], 0.0) for c in cols])
    idx = {(c[0], c[1]): j for j, c in enumerate(cols)}

    w = np.ones(n)
    sigma = 0.5
    for _ in range(iters):
        lam = sigma ** 2 / prior_sd ** 2
        A = X.T @ (X * w[:, None]) + np.diag(lam)
        beta = scipy.linalg.solve(A, X.T @ (w * y) + lam * prior_mu, assume_a="pos")
        res = y - X @ beta
        mad = float(np.median(np.abs(res - np.median(res)))) * 1.4826
        sigma_new = max(mad, 0.02)
        z = np.abs(res) / sigma_new
        w_new = np.where(z <= HUBER_K, 1.0, HUBER_K / np.maximum(z, 1e-12))
        done = np.allclose(w_new, w, atol=1e-4) and abs(sigma_new - sigma) < 1e-4
        w, sigma = w_new, sigma_new
        if done:
            break
    lam = sigma ** 2 / prior_sd ** 2
    A = X.T @ (X * w[:, None]) + np.diag(lam)
    beta = scipy.linalg.solve(A, X.T @ (w * y) + lam * prior_mu, assume_a="pos")
    res = y - X @ beta
    sig2 = float(np.sum(w * res ** 2) / max(1.0, np.sum(w) - min(len(beta), np.sum(w) - 1)))
    cov = sig2 * np.linalg.inv(A)

    # lag-1 autocorrelation of a driver's consecutive clean-lap residuals
    pairs = []
    order = sorted(range(n), key=lambda k: (use[k]["driver"], use[k]["lap"]))
    for a_, b_ in zip(order, order[1:]):
        if use[a_]["driver"] == use[b_]["driver"] and use[b_]["lap"] == use[a_]["lap"] + 1:
            pairs.append((res[a_], res[b_]))
    rho = 0.0
    if len(pairs) > 10:
        pa = np.array(pairs)
        if pa[:, 0].std() > 0 and pa[:, 1].std() > 0:
            rho = float(np.clip(np.corrcoef(pa[:, 0], pa[:, 1])[0, 1], 0.0, 0.6))
    cov *= (1 + rho) / (1 - rho)

    # pace contrasts: (team + dev) - mean over drivers
    D = len(drivers)
    L = np.zeros((D, len(beta)))
    for d in drivers:
        L[di[d], idx[("team", team_of[d])]] = 1.0
        L[di[d], idx[("dev", d)]] = 1.0
    raw_pace = L @ beta
    C = np.eye(D) - 1.0 / D
    pace = C @ raw_pace
    pace_cov = C @ L @ cov @ L.T @ C.T
    k_tr = float(beta[idx[("traffic", None)]]) if has_traffic else None
    ref_lap = float(np.median(y))

    out_d: dict[str, Any] = {}
    for d in drivers:
        mask = np.array([r["driver"] == d for r in use])
        deg = {}
        for c in sorted({r["compound"] for r in use if r["driver"] == d}):
            v = beta[idx[("deg", c)]] + beta[idx[("tdeg", (team_of[d], c))]] + beta[idx[("ddeg", (d, c))]]
            deg[c] = round(float(v), 4)
        out_d[d] = {"pace": round(float(pace[di[d]]), 4), "se": round(float(math.sqrt(max(pace_cov[di[d], di[d]], 0.0))), 4),
                    "laps": int(mask.sum()), "deg": deg,
                    "traffic_cost": round(float(k_tr * tr[mask].sum()), 3) if has_traffic else 0.0,
                    "pace_pct": round(float(100 * pace[di[d]] / ref_lap), 4), "team": team_of[d]}
    excluded["downweighted"] = int(np.sum(w < 0.5))
    return {
        "drivers": out_d,
        "fuel_coef": round(float(beta[idx[("fuel", None)]]), 4),
        "fuel_unit": "s per lap of fuel on board (net of linear track evolution)",
        "excluded": dict(excluded),
        "traffic_coef": round(k_tr, 4) if k_tr is not None else None,
        "compound_offset": {c: (0.0 if c == comps[0] else round(float(beta[idx[("off", c)]]), 4)) for c in comps},
        "compound_deg": {c: round(float(beta[idx[("deg", c)]]), 4) for c in comps},
        "track_evo": {"p2": round(float(beta[idx[("evo", 2)]]), 4), "p3": round(float(beta[idx[("evo", 3)]]), 4)},
        "sigma": round(math.sqrt(sig2), 4), "rho": round(rho, 3), "ref_lap_s": round(ref_lap, 3),
        "n_clean": n, "n_laps": int(n_laps),
    }


# ===================================================================== public entry

def _inputs(year: int, rnd: int) -> tuple[dict, dict | None, dict[str, str]]:
    race = canon.race(year, rnd)
    sess = canon.find_session(year, rnd, "Race") if int(year) >= 2023 else None
    ids = canon.session_driver_ids(year, sess, rnd) if sess else {}
    return race, sess, ids


def _key(year: int, rnd: int, race: dict, sess: dict | None) -> str:
    h = hashlib.sha1()
    h.update(f"{MODEL_VERSION}|{year}|{rnd}|".encode())
    sub = {k: race.get(k) for k in ("results", "pitstops", "laps")}
    h.update(json.dumps(sub, sort_keys=True, separators=(",", ":")).encode())
    if sess:
        sub2 = {k: sess.get(k) for k in ("laps", "lap_end", "stints", "pit", "race_control", "drivers")}
        h.update(json.dumps(sub2, sort_keys=True, separators=(",", ":"), default=str).encode())
    return h.hexdigest()


def race_pace(year: int, rnd: int, use_cache: bool = True) -> dict[str, Any]:
    """Corrected race pace for one Grand Prix (contract shape; see module docstring).

    Uses OpenF1 laps/stints/pit/race control/intervals when the race session is on disk
    (2023-), else the season store's Jolpica laps and pit stops. Never raises: returns
    {"drivers": {}, ..., "reason": ...} when there is nothing to fit. Results are cached
    in data/f1/cache/pace/<year>_<round>.json under a hash of the inputs.
    """
    try:
        race, sess, ids = _inputs(year, rnd)
    except Exception as exc:                                          # pragma: no cover - defensive
        return _empty(f"could not read inputs: {exc}")
    if not race:
        return _empty("round not in season store")
    if not race.get("laps") and not (sess and sess.get("laps")):
        return _empty("no lap times on disk (Jolpica laps not yet backfilled, no OpenF1 race session)")
    key = _key(year, rnd, race, sess)
    path = CACHE / f"{year}_{rnd}.json"
    if use_cache and path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("key") == key:
                return c["result"]
        except (OSError, ValueError, KeyError):
            pass
    team = {}
    for d in set(ids.values()) | set(race.get("laps") or {}):
        t = canon.team_for(year, rnd, d)
        if t:
            team[d] = t
    try:
        rows, info = assemble(race, sess, ids, team, year)
        if not rows:
            out = _empty(info.get("reason", "no laps"))
        else:
            out = fit_race(rows, info.get("n_laps"), traffic=info.get("traffic", False), refuel=info.get("refuel", False))
        out["source"] = info.get("source")
        out["neutral_laps"] = info.get("neutral_laps", [])
    except Exception as exc:                                          # pragma: no cover - defensive
        return _empty(f"fit failed: {exc}")
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"key": key, "result": out}, separators=(",", ":")), encoding="utf-8")
    except OSError:
        pass
    return out
