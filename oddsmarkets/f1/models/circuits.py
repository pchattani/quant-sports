"""
Circuit parameters learned from history, shrunk toward the global mean by sample size.

Sources
-------
* Jolpica season stores (1996->): results (laps, grid, status), pit stops (2011->), lap times and
  lap-end positions (1996->).
* OpenF1 race sessions (2023->): pit-lane times, race control (SC / VSC / red flag), weather (rain),
  on-track overtakes, lap times with pit-out flags. When the season store has no lap times for a race
  (the Jolpica lap backfill has not reached it), the OpenF1 record also supplies the lap matrix,
  lap-end running order (order of completing each lap), pit laps (pit rows and pit-out flags), and
  from them the overtaking opportunities, neutralised-lap runs, stops per finisher and first-lap
  deltas (`_openf1_fill`), keyed by car number and matched to results through `number`.

Per race we extract a record (cached in ``data/f1/cache/circuit_records.json``, rebuilt per season when a
store or session file changes); ``circuit_profile(circuit_id, before=(year, round))`` aggregates the records
strictly before the cutoff, so the backtest never sees the race it predicts.

Recency weighting
-----------------
Every race record gets weight ``w = 0.5 ** ((Y - y) / HALF_LIFE_YEARS)`` where ``Y`` is the cutoff season and
``y`` the record's season (HALF_LIFE_YEARS = 4). All sums below are w-weighted, so "n" is an effective count.

Estimators (circuit value c, global value g, shrinkage constant k)
-----------------------------------------------------------------
* Laps: the most recent full race distance at the circuit (winner's laps; a race under 90% of the median of the
  circuit's last three is skipped as shortened); else 57. Lap length is not in the data:
  ``length_km = 305 / laps`` (the FIA minimum race distance; Monaco 260.3 km). Sprint laps =
  ``ceil(100 / length_km)``.
* Pit loss (s): per stop ``loss = (in_lap + out_lap) - 2 * ref`` where ``ref`` is the driver's median green lap
  in laps l-4..l+5 excluding the in/out laps (stops with loss outside 8..45 s are dropped: SC-affected);
  the race value is the median over stops. Before 2011 (no pit stop table) pit laps are detected as
  ``lap_l + lap_{l+1} - 2 * ref > 12 s`` on a green lap. OpenF1 pit lane time is kept as ``pit_lane_s``
  and used as the race value when no lap times exist. Circuit estimate:
  ``(sum w*x + k*g) / (sum w + k)`` with k = 2 races; global prior 22.0 s.
* SC / VSC hazard per lap (Gamma-Poisson): ``rate = (events_w + K_LAPS * g) / (exposure_laps_w + K_LAPS)``,
  K_LAPS = 150 laps. Events from OpenF1 race control ("SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR DEPLOYED",
  red flags) 2023->; before 2023 neutralised laps are detected statistically: a lap whose field-median lap
  time exceeds 1.20 x the race's median green lap is neutralised; each run of consecutive neutralised laps
  after lap 1 is one event, split SC:VSC by the OpenF1-era share (default 0.65:0.35; all SC before 2015).
  Global priors: SC 0.011, VSC 0.006 per lap.
* Overtaking: an *opportunity* is a car directly behind another at the end of lap k-1, within 1.5 s, whose
  median of its previous 3 laps is >= 0.3 s faster, both green (no pit in/out lap, lap not neutralised).
  Success = it is ahead at the end of lap k. ``pass_prob = (succ_w + 40 * g) / (opp_w + 40)``, global prior
  0.18. The race simulator passes with ``P = sigmoid((delta - thr) / OVERTAKE_SCALE)``, OVERTAKE_SCALE =
  0.25 s, and the threshold is calibrated so that a typical opportunity (mean pace delta ``d_bar``, prior
  0.6 s) passes at the observed rate: ``thr = d_bar - 0.25 * logit(pass_prob)``.
  ``overtake_difficulty = clip(1 - pass_prob / (2 * g), 0.02, 0.98)`` (0.5 = an average circuit).
  On-track position swaps per green car-lap (pairs swapping order with neither car pitting) and OpenF1
  overtakes per car-lap are reported as ``passes_per_car_lap``.
* Typical stop count: mean stops per classified finisher; ``(sum w*x + 2 * 1.6) / (sum w + 2)``.
* First lap: delta = position at end of lap 1 - grid slot. Global mean and sd per grid slot (1..26),
  each slot shrunk toward the pooled value with k = 30 starts; a circuit multiplier on the sd
  ``(sum w*sd_c + 3) / (sum w + 3)`` (relative to global). Priors: mean 0, sd = 1.2 + 0.05 * slot.
* Classification: a row with a numeric ``position_text`` is classified (including "Retired" rows classified on
  distance); otherwise W/F/"Did not start" = did not start, D/E = disqualified, the rest are DNFs.
* DNF (per starter per race): statuses split into mechanical (engine, gearbox, hydraulics...), incident
  (accident, collision, spun off, damage, puncture...) and unknown ("Retired"); unknown is split by the
  global mechanical share. Global rates are the recency-weighted mean over all races; circuit multipliers
  ``m = (obs_w + 5) / (exp_w + 5)`` with ``exp_w`` the global-era rate times the circuit's starters, so a
  circuit needs several excess retirements before it departs from 1. Lap-1 incident probability by grid
  slot (retired with 0 laps completed) is ``(k_g + 20 * p) / (n_g + 20)`` around the pooled rate p.
  Priors: mechanical 0.040, incident 0.035 per race, lap-1 incident 0.012 per starter.
* Wet probability: OpenF1 rainfall during the race; ``(wet_w + 2 * 0.12) / (n_w + 2)``.
"""
from __future__ import annotations

import json
import logging
import math
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from oddsmarkets.f1 import store as _store

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "data" / "f1" / "cache"
RECORDS_PATH = CACHE / "circuit_records.json"
RECORDS_VERSION = 6
FIRST_YEAR = 1996

HALF_LIFE_YEARS = 4.0
MAX_SLOTS = 26

# priors (used when no history at all)
PRIOR = {
    "laps": 57, "pit_loss_s": 22.0, "sc_rate_per_lap": 0.011, "vsc_rate_per_lap": 0.006, "pass_prob": 0.18,
    "pass_delta_s": 0.6, "typical_stops": 1.6, "dnf_mech_per_race": 0.040, "dnf_incident_per_race": 0.035,
    "lap1_incident": 0.012, "p_wet": 0.12, "mech_share": 0.53, "sc_share": 0.65,
}
K_PIT, K_LAPS, K_PASS, K_STOPS, K_LAP1_SD, K_DNF, K_LAP1_SLOT, K_SLOT, K_WET = 2.0, 150.0, 40.0, 2.0, 3.0, 5.0, 20.0, 30.0, 2.0
OVERTAKE_SCALE = 0.25
NEUTRAL_FACTOR = 1.20

INCIDENT_WORDS = ("accident", "collision", "spun", "damage", "debris", "puncture", "crash", "contact", "fatal", "injur", "tyre", "wheel nut",
                  "safety", "retired - incident")
MECH_WORDS = ("engine", "gearbox", "hydraul", "brake", "electr", "power", "suspension", "transmission", "clutch", "oil", "water", "fuel",
              "overheat", "exhaust", "turbo", "ers", "battery", "driveshaft", "drivetrain", "mechanical", "throttle", "steering", "radiator",
              "differential", "pneumatic", "vibration", "cooling", "technical", "halfshaft", "spark", "wheel", "axle", "launch", "pressure",
              "out of fuel", "mgu", "energy", "chassis", "undertray", "seat", "rear wing", "front wing", "physical", "illness")
NOT_STARTED = ("did not start", "withdrew", "not qualified", "did not qualify", "did not prequalify", "107%", "excluded", "dns")


# ----------------------------------------------------------------------------------------------- store access

@lru_cache(maxsize=64)
def _load_cached(year: int, mtime: float) -> dict:
    return _store.load(year)


def load_store(year: int) -> dict:
    """Season store, cached by file mtime (cheap to call repeatedly)."""
    p = _store.season_path(year)
    try:
        m = p.stat().st_mtime
    except OSError:
        return _store.new_store(year)
    return _load_cached(year, m)


def store_years() -> list[int]:
    try:
        return sorted(int(p.name) for p in _store.DATA.iterdir() if p.is_dir() and p.name.isdigit())
    except OSError:
        return []


def race_key(year: int, rnd: int | str) -> tuple[int, int]:
    return int(year), int(rnd)


# ----------------------------------------------------------------------------------------------- classification

def status_kind(row: dict) -> str:
    """'finished' | 'dnf_mech' | 'dnf_incident' | 'dnf_unknown' | 'dsq' | 'dns'."""
    st = str(row.get("status") or "").strip().lower()
    pt = str(row.get("position_text") or "").strip().upper()
    if pt.isdigit():
        return "finished"                        # classified (incl. "Retired" but classified on distance)
    if any(w in st for w in NOT_STARTED) or pt in ("W", "F"):
        return "dns"
    if "disqualif" in st or pt in ("D", "E"):
        return "dsq"
    if not pt and (st in ("finished", "lapped") or st.startswith("+")):
        return "finished"
    if any(w in st for w in INCIDENT_WORDS):
        return "dnf_incident"
    if any(w in st for w in MECH_WORDS):
        return "dnf_mech"
    return "dnf_unknown"


def is_classified(row: dict) -> bool:
    return status_kind(row) == "finished"


# ----------------------------------------------------------------------------------------------- OpenF1 sessions

def _session_index(year: int) -> dict[str, dict]:
    """{'<date>|Race' or '<date>|Sprint': path} for the year's OpenF1 race/sprint sessions."""
    d = _store.DATA / str(year) / "sessions"
    out: dict[str, dict] = {}
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        s = rec.get("session") or {}
        name = str(s.get("session_name") or "")
        if name not in ("Race", "Sprint"):
            continue
        date = str(s.get("date_start") or "")[:10]
        if date:
            out[f"{date}|{name}"] = {"path": str(p), "rec": rec}
    return out


def match_session(index: dict, date: str | None, name: str = "Race") -> dict | None:
    if not date:
        return None
    from datetime import date as _d, timedelta
    try:
        d0 = _d.fromisoformat(date[:10])
    except ValueError:
        return None
    for off in (0, -1, 1, -2):
        k = f"{(d0 + timedelta(days=off)).isoformat()}|{name}"
        if k in index:
            return index[k]["rec"]
    return None


def _openf1_events(rec: dict) -> dict:
    sc = vsc = red = 0
    sc_laps: set[int] = set()
    for row in rec.get("race_control") or []:
        try:
            _, lap, cat, flag, *_rest = row
            msg = str(row[7] or "").upper()
        except (ValueError, IndexError):
            continue
        if "VIRTUAL SAFETY CAR DEPLOYED" in msg:
            vsc += 1
        elif "SAFETY CAR DEPLOYED" in msg:
            sc += 1
        if str(flag or "").upper() == "RED":
            red += 1
        if lap is not None and ("SAFETY CAR" in msg and "DEPLOYED" in msg):
            sc_laps.add(int(lap))
    rain = any((w[4] or 0) > 0 for w in rec.get("weather") or [] if len(w) > 4 and w[4] is not None)
    lanes = [p[3] / 1000.0 for p in rec.get("pit") or [] if len(p) > 3 and p[3] and 10000 < p[3] < 60000]
    return {"sc": sc, "vsc": vsc, "red": red, "wet": bool(rain), "lanes": lanes, "overtakes": len(rec.get("overtakes") or []),
            "laps_by_num": {k: {int(r[0]): r[2] for r in v if r and r[0] is not None} for k, v in (rec.get("laps") or {}).items()},
            "pit_laps": [(str(p[0]), int(p[1])) for p in rec.get("pit") or [] if p and p[0] is not None and p[1] is not None]}


def _openf1_matrix(rec: dict) -> tuple[list[str], np.ndarray, dict[str, list], set[tuple[str, int]]]:
    """Lap-time matrix (s), lap-end positions and pit laps from an OpenF1 race record, keyed by car number.

    Lap ends: the next lap's start when known, else start + lap time; the order of completing lap L is the
    running order at the end of lap L. Pit laps: OpenF1 pit rows (in-lap) and pit-out flags (lap - 1).
    """
    laps = rec.get("laps") or {}
    ids = sorted(str(k) for k in laps)
    L = 0
    ends: dict[str, dict[int, float]] = {}
    times: dict[str, dict[int, float]] = {}
    pit_set: set[tuple[str, int]] = set()
    for dn in ids:
        rows = [r for r in laps.get(dn) or [] if r and r[0] is not None]
        st = {int(r[0]): r[1] for r in rows}
        times[dn] = {int(r[0]): r[2] for r in rows if r[2]}
        e = {}
        for lap, s in st.items():
            if st.get(lap + 1) is not None:
                e[lap] = st[lap + 1]
            elif s is not None and times[dn].get(lap):
                e[lap] = s + times[dn][lap]
        ends[dn] = e
        L = max([L] + list(st))
        for r in rows:
            if len(r) > 9 and r[9] and int(r[0]) > 1:
                pit_set.add((dn, int(r[0]) - 1))
    for p in rec.get("pit") or []:
        if p and p[0] is not None and p[1] is not None:
            pit_set.add((str(p[0]), int(p[1])))
    M = np.full((len(ids), L), np.nan)
    for i, dn in enumerate(ids):
        for lap, ms in times[dn].items():
            if 0 < lap <= L and ms > 0:
                M[i, lap - 1] = ms / 1000.0
    positions: dict[str, list] = {dn: [None] * L for dn in ids}
    for lap in range(1, L + 1):
        order = sorted((e[lap], dn) for dn, e in ends.items() if lap in e)
        for k, (_t, dn) in enumerate(order, 1):
            positions[dn][lap - 1] = k
    return ids, M, positions, pit_set


def _openf1_fill(rec: dict, o: dict, results: list[dict], finishers: set[str]) -> None:
    """When the season store has no lap times, take overtaking opportunities, neutralised-lap runs, stop
    counts and first-lap deltas from the OpenF1 race record (keyed by car number, matched to results by
    the results' `number`)."""
    ids, M, positions, pit_set = _openf1_matrix(o)
    if not M.size:
        return
    neut, _ref = _neutralised(M)
    if np.isfinite(_ref) and "ref_lap_s" not in rec:
        rec["ref_lap_s"] = round(float(_ref), 3)
    ot = _overtakes(M, ids, positions, neut, pit_set)
    rec.update({f"ot_{k}": v for k, v in ot.items()})
    rec.setdefault("neutral_events", _runs(neut[1:]) if neut.size > 1 else 0)
    num_of = {r.get("driver"): str(r.get("number")) for r in results if r.get("number") is not None}
    if "stops_mean" not in rec and finishers:
        cnt: dict[str, int] = {}
        for dn, _lap in pit_set:
            cnt[dn] = cnt.get(dn, 0) + 1
        vals = [cnt.get(num_of.get(d), 0) for d in finishers if num_of.get(d) in positions]
        if vals:
            rec["stops_mean"] = float(np.mean(vals))
    if "lap1_deltas" not in rec:
        deltas: dict[str, list[int]] = {}
        for r in results:
            g = int(r.get("grid") or 0)
            pl = positions.get(num_of.get(r.get("driver"), "")) or []
            if 0 < g <= MAX_SLOTS and pl and pl[0]:
                deltas.setdefault(str(g), []).append(int(pl[0]) - g)
        if deltas:
            rec["lap1_deltas"] = deltas


# ----------------------------------------------------------------------------------------------- per-race extraction

def _lap_matrix(laps: dict[str, list]) -> tuple[list[str], np.ndarray]:
    ids = sorted(laps)
    L = max((len(v) for v in laps.values()), default=0)
    M = np.full((len(ids), L), np.nan)
    for i, d in enumerate(ids):
        for j, v in enumerate(laps[d] or []):
            if v is not None and v > 0:
                M[i, j] = v / 1000.0
    return ids, M


def _neutralised(M: np.ndarray) -> tuple[np.ndarray, float]:
    """Boolean per lap (index 0 = lap 1) and the race's median green lap (s)."""
    if M.size == 0:
        return np.zeros(0, bool), float("nan")
    with np.errstate(all="ignore"):
        med = np.nanmedian(M, axis=0)
    ref = float(np.nanmedian(med[1:])) if med.size > 1 and np.isfinite(med[1:]).any() else float("nan")
    neut = np.zeros(med.size, bool)
    if np.isfinite(ref):
        neut = np.nan_to_num(med, nan=0.0) > NEUTRAL_FACTOR * ref
        neut[0] = False
    return neut, ref


def _runs(mask: np.ndarray) -> int:
    n, prev = 0, False
    for v in mask:
        if v and not prev:
            n += 1
        prev = bool(v)
    return n


def _pit_losses(M: np.ndarray, ids: list[str], neut: np.ndarray, stops: list[tuple[str, int]]) -> list[float]:
    idx = {d: i for i, d in enumerate(ids)}
    out = []
    L = M.shape[1] if M.ndim == 2 else 0
    for d, lap in stops:
        i = idx.get(d)
        if i is None or lap < 2 or lap >= L:
            continue
        inl, outl = M[i, lap - 1], M[i, lap]
        win = [j for j in range(max(1, lap - 5), min(L, lap + 5)) if j not in (lap - 1, lap) and not neut[j]]
        ref = np.nanmedian(M[i, win]) if win else np.nan
        if not (np.isfinite(inl) and np.isfinite(outl) and np.isfinite(ref)) or neut[lap - 1] or neut[lap]:
            continue
        loss = inl + outl - 2 * ref
        if 8.0 <= loss <= 45.0:
            out.append(float(loss))
    return out


def _detect_stops(M: np.ndarray, ids: list[str], neut: np.ndarray) -> list[tuple[str, int]]:
    out = []
    for i, d in enumerate(ids):
        row = M[i]
        if not np.isfinite(row).any():
            continue
        ref = np.nanmedian(row[1:]) if row.size > 1 else np.nan
        for j in range(1, row.size - 1):
            if neut[j] or neut[j + 1] or not np.isfinite(row[j]) or not np.isfinite(row[j + 1]):
                continue
            if row[j] + row[j + 1] - 2 * ref > 12.0 and row[j] - ref > 3.0:
                out.append((d, j + 1))
    return out


def _overtakes(M: np.ndarray, ids: list[str], positions: dict, neut: np.ndarray, pit_set: set[tuple[str, int]]) -> dict:
    """Opportunity/success counts and the mean pace delta of opportunities, plus pairwise green swaps."""
    D = len(ids)
    if D == 0 or not positions:
        return {"opp": 0, "succ": 0, "delta_sum": 0.0, "swaps": 0, "car_laps": 0}
    L = M.shape[1]
    P = np.full((D, L), np.nan)
    for i, d in enumerate(ids):
        for j, v in enumerate((positions.get(d) or [])[:L]):
            if v:
                P[i, j] = v
    cum = np.nancumsum(np.where(np.isfinite(M), M, 0.0), axis=1)
    pitted = np.zeros((D, L + 1), bool)
    for i, d in enumerate(ids):
        for lap in range(1, L + 1):
            if (d, lap) in pit_set:
                pitted[i, lap - 1] = True
                if lap < L:
                    pitted[i, lap] = True
    opp = succ = swaps = car_laps = 0
    dsum = 0.0
    for k in range(2, L):                       # lap index k (0-based) compares end of lap k-1 -> k
        if neut[k] or neut[k - 1]:
            continue
        prev, cur = P[:, k - 1], P[:, k]
        ok = np.isfinite(prev) & np.isfinite(cur) & ~pitted[:, k] & ~pitted[:, k - 1] & np.isfinite(M[:, k])
        car_laps += int(ok.sum())
        idx = np.where(ok)[0]
        if idx.size < 2:
            continue
        a = idx[:, None]
        b = idx[None, :]
        swaps += int(((prev[a] > prev[b]) & (cur[a] < cur[b])).sum())
        by_pos = {int(prev[i]): i for i in idx}
        for p, i in by_pos.items():
            j = by_pos.get(p - 1)                # car directly ahead
            if j is None:
                continue
            gap = cum[i, k - 1] - cum[j, k - 1]
            if not (0 < gap < 1.5) or k < 4:
                continue
            ri, rj = np.nanmedian(M[i, k - 3:k]), np.nanmedian(M[j, k - 3:k])
            if not (np.isfinite(ri) and np.isfinite(rj)):
                continue
            delta = rj - ri
            if delta >= 0.3:
                opp += 1
                dsum += float(delta)
                if cur[i] < cur[j]:
                    succ += 1
    return {"opp": opp, "succ": succ, "delta_sum": dsum, "swaps": swaps, "car_laps": car_laps}


def race_record(year: int, rnd: str, race: dict, sess_index: dict | None = None) -> dict | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return _race_record(year, rnd, race, sess_index)


def _race_record(year: int, rnd: str, race: dict, sess_index: dict | None = None) -> dict | None:
    results = race.get("results") or []
    if not results:
        return None
    circ = (race.get("circuit") or {}).get("id")
    kinds = [status_kind(r) for r in results]
    starters = [r for r, k in zip(results, kinds) if k != "dns"]
    laps_race = max((int(r.get("laps") or 0) for r in results), default=0)
    rec: dict[str, Any] = {"year": int(year), "round": int(rnd), "circuit": circ, "laps": laps_race or None, "starters": len(starters),
                           "mech": 0, "incident": 0, "unknown": 0, "lap1_by_slot": {}, "starts_by_slot": {}}
    for r, k in zip(results, kinds):
        if k == "dns":
            continue
        if k == "dnf_mech":
            rec["mech"] += 1
        elif k == "dnf_incident":
            rec["incident"] += 1
        elif k == "dnf_unknown":
            rec["unknown"] += 1
        g = int(r.get("grid") or 0)
        g = g if 0 < g <= MAX_SLOTS else MAX_SLOTS
        rec["starts_by_slot"][str(g)] = rec["starts_by_slot"].get(str(g), 0) + 1
        if k.startswith("dnf") and int(r.get("laps") or 0) == 0:
            rec["lap1_by_slot"][str(g)] = rec["lap1_by_slot"].get(str(g), 0) + 1
    # stops per classified finisher
    pits = race.get("pitstops") or []
    finishers = {r["driver"] for r, k in zip(results, kinds) if k == "finished"}
    if pits:
        cnt: dict[str, int] = {}
        for p in pits:
            cnt[p.get("driver")] = cnt.get(p.get("driver"), 0) + 1
        if finishers:
            rec["stops_mean"] = float(np.mean([cnt.get(d, 0) for d in finishers]))
    laps = race.get("laps") or {}
    positions = race.get("positions") or {}
    ids, M = _lap_matrix(laps) if laps else ([], np.zeros((0, 0)))
    neut, ref = _neutralised(M)
    if M.size and np.isfinite(ref):
        rec["ref_lap_s"] = round(float(ref), 3)
    if M.size:
        stops = [(p.get("driver"), int(p.get("lap") or 0)) for p in pits] if pits else _detect_stops(M, ids, neut)
        losses = _pit_losses(M, ids, neut, stops)
        if losses:
            rec["pit_loss"] = float(np.median(losses))
        if "stops_mean" not in rec and not pits and finishers:
            c: dict[str, int] = {}
            for d, _ in stops:
                c[d] = c.get(d, 0) + 1
            rec["stops_mean"] = float(np.mean([c.get(d, 0) for d in finishers]))
        rec["neutral_events"] = _runs(neut[1:]) if neut.size > 1 else 0
        rec["green_exposure"] = int(max(0, M.shape[1] - 1))
        ot = _overtakes(M, ids, positions, neut, set(stops))
        rec.update({f"ot_{k}": v for k, v in ot.items()})
    # first-lap deltas from lap-1 positions
    deltas: dict[str, list[int]] = {}
    for r in results:
        g = int(r.get("grid") or 0)
        pl = positions.get(r.get("driver")) or []
        if 0 < g <= MAX_SLOTS and pl and pl[0]:
            deltas.setdefault(str(g), []).append(int(pl[0]) - g)
    if deltas:
        rec["lap1_deltas"] = deltas
    # OpenF1 overlay
    if sess_index is not None:
        o = match_session(sess_index, race.get("date"), "Race")
        if o:
            ev = _openf1_events(o)
            rec.update({"of_sc": ev["sc"], "of_vsc": ev["vsc"], "of_red": ev["red"], "wet": ev["wet"], "of_overtakes": ev["overtakes"]})
            if not M.size:
                _openf1_fill(rec, o, results, finishers)
            if ev["lanes"]:
                rec["pit_lane_s"] = float(np.median(ev["lanes"]))
            if "pit_loss" not in rec:
                lbn = ev["laps_by_num"]
                if lbn:
                    num_ids = sorted(lbn)
                    L = max((max(v) for v in lbn.values() if v), default=0)
                    MM = np.full((len(num_ids), L), np.nan)
                    for i, dn in enumerate(num_ids):
                        for lap, ms in lbn[dn].items():
                            if ms and 0 < lap <= L:
                                MM[i, lap - 1] = ms / 1000.0
                    nn, _ = _neutralised(MM)
                    losses = _pit_losses(MM, num_ids, nn, ev["pit_laps"])
                    if losses:
                        rec["pit_loss"] = float(np.median(losses))
                    if "neutral_events" not in rec:
                        rec["green_exposure"] = int(max(0, L - 1))
                elif rec.get("pit_lane_s"):
                    rec["pit_loss"] = rec["pit_lane_s"]
            if not rec.get("green_exposure") and rec.get("laps"):
                rec["green_exposure"] = int(rec["laps"]) - 1
    return rec


# ----------------------------------------------------------------------------------------------- cache

def _fingerprint(year: int) -> str:
    parts = []
    p = _store.season_path(year)
    try:
        parts.append(f"{p.stat().st_mtime:.0f}")
    except OSError:
        parts.append("-")
    d = _store.DATA / str(year) / "sessions"
    try:
        files = list(d.glob("*.json")) if d.exists() else []
        parts.append(f"{len(files)}:{max((f.stat().st_mtime for f in files), default=0):.0f}")
    except OSError:
        parts.append("-")
    return f"v{RECORDS_VERSION}|" + "|".join(parts)


_RECORDS_MEM: dict[str, Any] | None = None


def all_records(refresh: bool = False) -> list[dict]:
    """Every race record on disk (recomputing only seasons whose files changed)."""
    global _RECORDS_MEM
    cache = _RECORDS_MEM
    if cache is None:
        cache = {}
        try:
            cache = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    changed = False
    out: list[dict] = []
    for y in store_years():
        if y < FIRST_YEAR:
            continue
        fp = _fingerprint(y)
        ent = cache.get(str(y))
        if refresh or not ent or ent.get("fp") != fp:
            try:
                st = load_store(y)
                idx = _session_index(y) if y >= 2023 else None
                recs = []
                for rnd, race in (st.get("races") or {}).items():
                    try:
                        r = race_record(y, rnd, race, idx)
                    except Exception as exc:          # never let one bad race break the profile
                        logger.warning("circuit record %s/%s failed: %s", y, rnd, exc)
                        r = None
                    if r:
                        recs.append(r)
            except Exception as exc:
                logger.warning("circuit records %s failed: %s", y, exc)
                recs = []
            ent = {"fp": fp, "records": recs}
            cache[str(y)] = ent
            changed = True
        out.extend(ent.get("records") or [])
    _RECORDS_MEM = cache
    if changed:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = RECORDS_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
            tmp.replace(RECORDS_PATH)
        except OSError:
            pass
    return out


# ----------------------------------------------------------------------------------------------- aggregation

def _before(rec: dict, before: tuple[int, int] | None) -> bool:
    return before is None or (rec["year"], rec["round"]) < (int(before[0]), int(before[1]))


def _shrunk_mean(xs: list[tuple[float, float]], prior: float, k: float) -> tuple[float, float]:
    sw = sum(w for _, w in xs)
    return (sum(w * x for x, w in xs) + k * prior) / (sw + k), sw


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def global_profile(before: tuple[int, int] | None = None, records: list[dict] | None = None) -> dict:
    """Recency-weighted global means over all races strictly before ``before``."""
    recs = [r for r in (records if records is not None else all_records()) if _before(r, before)]
    Y = int(before[0]) if before else max((r["year"] for r in recs), default=2026)
    return _aggregate(recs, Y, None)


def _w(rec: dict, Y: int) -> float:
    return 0.5 ** (max(0, Y - rec["year"]) / HALF_LIFE_YEARS)


def _aggregate(recs: list[dict], Y: int, g: dict | None) -> dict:
    """g None -> global profile (priors = PRIOR); else circuit profile shrunk to g."""
    P = PRIOR if g is None else g
    out: dict[str, Any] = {}
    ws = [(_w(r, Y), r) for r in recs]
    # pit loss
    out["pit_loss_s"], out["n_pit"] = _shrunk_mean([(r["pit_loss"], w) for w, r in ws if r.get("pit_loss")], P["pit_loss_s"], K_PIT)
    lanes = [(r["pit_lane_s"], w) for w, r in ws if r.get("pit_lane_s")]
    out["pit_lane_s"] = round(_shrunk_mean(lanes, P.get("pit_lane_s") or P["pit_loss_s"], K_PIT)[0], 2) if lanes else (P.get("pit_lane_s") if g else None)
    # SC / VSC hazards
    sc_share = P["sc_share"]
    if g is None:
        of = [(w, r) for w, r in ws if "of_sc" in r]
        tot = sum(w * (r["of_sc"] + r["of_vsc"]) for w, r in of)
        if tot > 0:
            sc_share = (sum(w * r["of_sc"] for w, r in of) + 5 * PRIOR["sc_share"]) / (tot + 5)
    out["sc_share"] = sc_share
    sc_ev = vsc_ev = expo = 0.0
    for w, r in ws:
        e = r.get("green_exposure")
        if not e:
            continue
        if "of_sc" in r:
            sc_ev += w * (r["of_sc"] + r.get("of_red", 0) * 0.5)
            vsc_ev += w * r["of_vsc"]
        elif "neutral_events" in r:
            n = r["neutral_events"]
            share = 1.0 if r["year"] < 2015 else sc_share
            sc_ev += w * n * share
            vsc_ev += w * n * (1 - share) if r["year"] >= 2015 else 0.0
        else:
            continue
        expo += w * e
    out["sc_rate_per_lap"] = (sc_ev + K_LAPS * P["sc_rate_per_lap"]) / (expo + K_LAPS)
    out["vsc_rate_per_lap"] = (vsc_ev + K_LAPS * P["vsc_rate_per_lap"]) / (expo + K_LAPS)
    out["n_sc_laps"] = expo
    # overtaking
    opp = sum(w * r.get("ot_opp", 0) for w, r in ws)
    succ = sum(w * r.get("ot_succ", 0) for w, r in ws)
    dsum = sum(w * r.get("ot_delta_sum", 0.0) for w, r in ws)
    out["pass_prob"] = (succ + K_PASS * P["pass_prob"]) / (opp + K_PASS)
    out["pass_delta_s"] = (dsum + K_PASS * P["pass_delta_s"]) / (opp + K_PASS)
    out["n_pass_opps"] = opp
    swaps = sum(w * r.get("ot_swaps", 0) for w, r in ws)
    cl = sum(w * r.get("ot_car_laps", 0) for w, r in ws)
    of_ot = sum(w * r.get("of_overtakes", 0) for w, r in ws if "of_overtakes" in r)
    of_cl = sum(w * (r.get("starters", 20) * (r.get("laps") or 0)) for w, r in ws if "of_overtakes" in r)
    num, den = swaps + of_ot, cl + of_cl
    pp_prior = P.get("passes_per_car_lap", 0.05)
    out["passes_per_car_lap"] = (num + 2000 * pp_prior) / (den + 2000)
    # stops
    out["typical_stops"], out["n_stops"] = _shrunk_mean([(r["stops_mean"], w) for w, r in ws if r.get("stops_mean") is not None],
                                                       P["typical_stops"], K_STOPS)
    # wet
    wr = [(1.0 if r["wet"] else 0.0, w) for w, r in ws if "wet" in r]
    out["p_wet"] = _shrunk_mean(wr, P["p_wet"], K_WET)[0]
    # DNF
    starts = sum(w * r.get("starters", 0) for w, r in ws)
    mech = sum(w * r.get("mech", 0) for w, r in ws)
    inc = sum(w * r.get("incident", 0) for w, r in ws)
    unk = sum(w * r.get("unknown", 0) for w, r in ws)
    if g is None:
        share = (mech + 20 * PRIOR["mech_share"]) / (mech + inc + 20)
        out["mech_share"] = share
        out["dnf_mech_per_race"] = (mech + unk * share + 40 * PRIOR["dnf_mech_per_race"]) / (starts + 40) if starts else PRIOR["dnf_mech_per_race"]
        out["dnf_incident_per_race"] = (inc + unk * (1 - share) + 40 * PRIOR["dnf_incident_per_race"]) / (starts + 40) if starts else PRIOR["dnf_incident_per_race"]
        out["mech_mult"] = out["incident_mult"] = 1.0
    else:
        share = g["mech_share"]
        out["mech_share"] = share
        exp_m, exp_i = starts * g["dnf_mech_per_race"], starts * g["dnf_incident_per_race"]
        out["mech_mult"] = (mech + unk * share + K_DNF) / (exp_m + K_DNF)
        out["incident_mult"] = (inc + unk * (1 - share) + K_DNF) / (exp_i + K_DNF)
        out["dnf_mech_per_race"] = g["dnf_mech_per_race"] * out["mech_mult"]
        out["dnf_incident_per_race"] = g["dnf_incident_per_race"] * out["incident_mult"]
    out["n_starts"] = starts
    # lap-1 incident by slot and first-lap deltas
    l1 = np.zeros(MAX_SLOTS + 1)
    st = np.zeros(MAX_SLOTS + 1)
    for w, r in ws:
        for s, c in (r.get("lap1_by_slot") or {}).items():
            l1[int(s)] += w * c
        for s, c in (r.get("starts_by_slot") or {}).items():
            st[int(s)] += w * c
    if g is None:
        pooled = (l1.sum() + 50 * PRIOR["lap1_incident"]) / (st.sum() + 50)
        out["lap1_incident"] = pooled
        out["lap1_incident_by_grid"] = [round(float((l1[s] + K_LAP1_SLOT * pooled) / (st[s] + K_LAP1_SLOT)), 5) for s in range(1, MAX_SLOTS + 1)]
        sums = {s: [0.0, 0.0, 0.0] for s in range(1, MAX_SLOTS + 1)}
        for w, r in ws:
            for s, ds in (r.get("lap1_deltas") or {}).items():
                a = sums[int(s)]
                for dlt in ds:
                    a[0] += w
                    a[1] += w * dlt
                    a[2] += w * dlt * dlt
        tw = sum(a[0] for a in sums.values())
        pooled_var = (sum(a[2] for a in sums.values()) / tw) if tw else None
        means, sds = [], []
        for s in range(1, MAX_SLOTS + 1):
            a = sums[s]
            prior_sd = 1.2 + 0.05 * s
            m = (a[1] + K_SLOT * 0.0) / (a[0] + K_SLOT)
            var = (a[2] + K_SLOT * prior_sd ** 2) / (a[0] + K_SLOT) - m * m
            means.append(round(float(m), 3))
            sds.append(round(float(math.sqrt(max(var, 0.25))), 3))
        out["lap1_mean_by_grid"], out["lap1_sd_by_grid"] = means, sds
        out["lap1_sd_scale"] = 1.0
        out["n_lap1"] = tw
        out["_pooled_lap1_var"] = pooled_var
    else:
        # circuit multipliers on the global lap-1 numbers
        exp_l1 = sum(st[s] * g["lap1_incident_by_grid"][s - 1] for s in range(1, MAX_SLOTS + 1))
        m1 = (l1.sum() + K_DNF) / (exp_l1 + K_DNF)
        out["lap1_incident_mult"] = m1
        out["lap1_incident_by_grid"] = [round(float(v * m1), 5) for v in g["lap1_incident_by_grid"]]
        out["lap1_mean_by_grid"] = g["lap1_mean_by_grid"]
        ratios = []
        for w, r in ws:
            num_, den_ = 0.0, 0.0
            for s, ds in (r.get("lap1_deltas") or {}).items():
                gs = g["lap1_sd_by_grid"][int(s) - 1]
                num_ += sum(dl * dl for dl in ds)
                den_ += len(ds) * gs * gs
            if den_ > 0:
                ratios.append((math.sqrt(num_ / den_), w))
        out["lap1_sd_scale"] = _shrunk_mean(ratios, 1.0, K_LAP1_SD)[0]
        out["lap1_sd_by_grid"] = [round(float(v * out["lap1_sd_scale"]), 3) for v in g["lap1_sd_by_grid"]]
    out["n_races"] = len(recs)
    return out


def _finish(p: dict, g: dict, laps: int | None, circuit_id: str | None) -> dict:
    laps = int(laps or PRIOR["laps"])
    length = (260.3 if circuit_id == "monaco" else 305.0) / laps
    pp = float(p["pass_prob"])
    thr = float(p["pass_delta_s"]) - OVERTAKE_SCALE * _logit(pp)
    out = {
        "circuit_id": circuit_id, "laps": laps, "length_km": round(length, 3), "distance_km": round(length * laps, 1),
        "sprint_laps": int(math.ceil(100.0 / length)),
        "pit_loss_s": round(float(p["pit_loss_s"]), 2), "pit_lane_s": p.get("pit_lane_s"),
        "sc_rate_per_lap": round(float(p["sc_rate_per_lap"]), 5), "vsc_rate_per_lap": round(float(p["vsc_rate_per_lap"]), 5),
        "p_sc_race": round(1 - math.exp(-p["sc_rate_per_lap"] * laps), 3), "p_vsc_race": round(1 - math.exp(-p["vsc_rate_per_lap"] * laps), 3),
        "pass_prob": round(pp, 4), "overtake_difficulty": round(min(0.98, max(0.02, 1 - pp / (2 * g["pass_prob"]))), 3),
        "overtake_threshold_s": round(min(2.5, max(0.2, thr)), 3), "overtake_scale_s": OVERTAKE_SCALE,
        "passes_per_car_lap": round(float(p["passes_per_car_lap"]), 4),
        "typical_stops": round(float(min(3.0, max(1.0, p["typical_stops"]))), 3), "p_wet": round(float(p["p_wet"]), 3),
        "dnf_mech_per_race": round(float(p["dnf_mech_per_race"]), 4), "dnf_incident_per_race": round(float(p["dnf_incident_per_race"]), 4),
        "mech_share": round(float(p["mech_share"]), 3),
        "lap1_incident_by_grid": p["lap1_incident_by_grid"], "lap1_mean_by_grid": p["lap1_mean_by_grid"], "lap1_sd_by_grid": p["lap1_sd_by_grid"],
        "lap1_sd_scale": round(float(p.get("lap1_sd_scale", 1.0)), 3),
        "samples": {"races": p.get("n_races", 0), "pit": round(p.get("n_pit", 0), 2), "sc_laps": round(p.get("n_sc_laps", 0), 1),
                    "pass_opps": round(p.get("n_pass_opps", 0), 1), "stops": round(p.get("n_stops", 0), 2), "starts": round(p.get("n_starts", 0), 1)},
    }
    return out


_PROFILE_CACHE: dict[tuple, dict] = {}
REF_LAP_DEFAULT = 90.0      # s; used only when no race on disk has lap times


def reference_lap(mine: list[dict], prior: list[dict]) -> tuple[float, str]:
    """The circuit's reference lap (s): its latest race's median green lap; with no lap times there, the
    median over the latest season's races anywhere (the era's typical lap); else REF_LAP_DEFAULT."""
    for r in sorted(mine, key=lambda r: (r["year"], r["round"]), reverse=True):
        if r.get("ref_lap_s"):
            return float(r["ref_lap_s"]), "circuit"
    withref = [r for r in prior if r.get("ref_lap_s")]
    if withref:
        y = max(r["year"] for r in withref)
        return float(np.median([r["ref_lap_s"] for r in withref if r["year"] == y])), "season median"
    return REF_LAP_DEFAULT, "default"



def circuit_profile(circuit_id: str | None, before: tuple[int, int] | None = None, records: list[dict] | None = None) -> dict:
    """Circuit parameters (shrunk to the global profile) using only races strictly before ``before``.

    Never raises: with no history it returns the global priors.
    """
    try:
        recs = records if records is not None else all_records()
        key = (circuit_id, tuple(before) if before else None, id(records) if records is not None else len(recs))
        if key in _PROFILE_CACHE:
            return dict(_PROFILE_CACHE[key])
        prior = [r for r in recs if _before(r, before)]
        Y = int(before[0]) if before else max((r["year"] for r in prior), default=2026)
        g = _aggregate(prior, Y, None)
        mine = [r for r in prior if r.get("circuit") == circuit_id]
        p = _aggregate(mine, Y, g) if circuit_id else g
        laps = None
        ran = [r for r in sorted(mine, key=lambda r: (r["year"], r["round"]), reverse=True) if r.get("laps")]
        if ran:
            # the latest race run to (nearly) full distance: a race stopped short (Spa 2021: 1 lap behind the safety
            # car, Suzuka 2022: 28 of 53, Monaco 2022: 64 of 78 on the time limit) would otherwise set next year's
            # distance. "Full" = at least 90% of the median of the last three races (a median, not a maximum: the
            # 2020 Sakhir outer loop shares Bahrain's circuit id at 87 laps).
            med = float(np.median([r["laps"] for r in ran[:3]]))
            laps = next((r["laps"] for r in ran if r["laps"] >= 0.9 * med), ran[0]["laps"])
        out = _finish(p, g, laps, circuit_id)
        out["ref_lap_s"], out["ref_lap_source"] = reference_lap(mine, prior)
        out["global"] = {k: round(float(g[k]), 5) for k in ("pit_loss_s", "sc_rate_per_lap", "vsc_rate_per_lap", "pass_prob", "typical_stops",
                                                            "dnf_mech_per_race", "dnf_incident_per_race", "p_wet")}
        _PROFILE_CACHE[key] = out
        return dict(out)
    except Exception as exc:                       # pragma: no cover - defensive
        logger.warning("circuit_profile(%s) fell back to priors: %s", circuit_id, exc)
        g = _aggregate([], 2026, None)
        out = _finish(g, g, None, circuit_id)
        out["ref_lap_s"], out["ref_lap_source"] = REF_LAP_DEFAULT, "default"
        return out


def scheduled_laps(year: int, rnd: int) -> int | None:
    """Race laps from the store when the race has run (winner's laps)."""
    race = (load_store(year).get("races") or {}).get(str(rnd)) or {}
    return max((int(r.get("laps") or 0) for r in race.get("results") or []), default=0) or None
