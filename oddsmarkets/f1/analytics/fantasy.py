"""
F1 fantasy layer (docs/VALUE_SECTIONS.md section 5): our own fantasy-style points table, projections for the next race
weekend and the rest of the season from the race simulation, value picks against a form line, and a walk-forward,
race-by-race backtest. Payloads: data/<year>/fantasy.json and data/fantasy_backtest.json (PAYLOADS.md "As built").

Scoring: ours, not the official game's
--------------------------------------
A fantasy-style table in the usual shape of F1 fantasy games, computed by us from Jolpica results and OpenF1 records.
No data from the official F1 Fantasy game (fantasy.formula1.com) is used: its prices, ownership, picks and scores are
left out because formula1.com's legal notices make its material "for your personal, non-commercial use only" and ask
users not to "distribute copy extract or commercially exploit" it (the game itself is a JavaScript app whose own terms
could not be read without running it; nothing is fetched from it).

Drivers, per weekend:
* qualifying: P1 10, P2 9 ... P10 1, P11 or lower 0; no time set (in the classification without a Q1/Q2/Q3 time) -5.
* Grand Prix: finishing points P1-P10 25, 18, 15, 12, 10, 8, 6, 4, 2, 1; positions gained or lost against the grid slot
  +1 / -1 per place (classified finishers only; a pit-lane start counts as the last slot); fastest lap +10; not
  classified (retired) -20; disqualified -20 (and nothing else from the race).
* overtakes: +1 per on-track pass in the Grand Prix, from OpenF1's overtakes feed with pit-stop position changes,
  safety-car laps and passes on a car about to retire removed (analytics/context.py), counted up to 20 a race (the
  feed occasionally logs spurious swaps: 87 for one driver at Bahrain 2025). OpenF1 starts in 2023, so earlier
  seasons have no overtakes: they are scored "core" (everything but overtakes) and the backtest reports core
  scoring over every season and full scoring from 2024 (a complete OpenF1 season behind every baseline).
  Sprint overtakes are left out.
* sprint: P1-P8 8, 7 ... 1; positions gained / lost +1 / -1; fastest lap +5; not classified or disqualified -10.
  Sprint qualifying is not scored.
* driver of the day: left out (a fan vote; nothing to model).
Constructors: both drivers' points (every item above) plus
* qualifying progression (the best that applies): both cars in Q3 +10, one in Q3 +5, both in Q2 +3, one in Q2 +1,
  neither -1 (Q2 = the top 15 of 20 cars, 16 of 22, 17 of 24: 10 + (n - 9) // 2, or a Q2 time when the session has
  them);
* pit stops (Grand Prix): the team's fastest stationary time (OpenF1 stop_ms, wheels stopped to moving, 1.5-30 s
  kept) under 2.0 s +20, 2.0-2.19 s +10, 2.2-2.49 s +5, 2.5-2.99 s +2, 3.0 s or slower 0; the race's fastest stop +5.
  OpenF1 publishes stationary times only for some races (late 2024, all of 2025, rounds 1-4, 7 and 10 of 2026), so
  pit points are scored and projected only where they exist and backtested on those races.

Projections
-----------
Every number comes from the race simulation (models/race_sim.py, the same inputs as the race forecasts) played out
per simulated weekend, so a floor and a ceiling (10th / 90th percentiles of the simulated weekend total) come out
with the mean:
* before qualifying the grid is drawn from the qualifying model's grid distribution and the drawn slot doubles as the
  qualifying position (grid penalties are not modelled); once qualifying is in, the actual grid and the actual
  qualifying points are used, and an actual sprint result replaces the sprint's simulation;
* a sprint weekend's sprint uses the same race inputs at the sprint distance (no stops) and the same random numbers
  as its Grand Prix (common random numbers), so a car quick on the simulated Saturday is quick on the Sunday too;
* finishing points, positions gained, retirements and the fastest lap (the running car with the best pace plus
  noise at the flag) come straight from each simulated race;
* overtakes: an expected count per simulated race, ``lambda = max(0.2, b0 + b1 gained + b2 lost + b3 finished) x
  f_circuit x f_driver``, b by least squares on every earlier OpenF1 race (driver-race rows, overtakes capped at 20,
  gained / lost = places against the grid when classified), ``f_circuit = (sum of the circuit's per-race means + 1.5
  m) / ((races there + 1.5) m)`` and ``f_driver = (overtakes + 15 m) / (expected + 15 m)`` (m = the mean per
  driver-race; the shrinkage reflects how little a driver's count carries from season to season: correlation 0.05-0.36
  between consecutive seasons). Needs three earlier OpenF1 races; until then overtakes are not projected;
* pit points (constructors): the team's band points and its share of the race's fastest stop over its earlier races
  with stationary times (this season weight 1, last season 0.35), shrunk toward the field with 3 races of prior;
* the rest of the season runs every remaining round in one simulation with the championship's season-level
  correlation (models/championship.py: the pace estimate's error persists, team and driver form walk round to
  round), so the season total's floor and ceiling are honest about how a car's season can drift.

Value without prices
--------------------
Fantasy prices broadly track recent scoring; the official prices cannot be used, so the form line stands in as our
own price proxy: the driver's season-to-date fantasy points per weekend (our table), blended with last season's
average while the sample is small, ``(n x form + 3 x last) / (n + 3)``. Value = our projection minus the form line
(next weekend, and per weekend over the rest of the season). Differentials: no ownership data, so a differential is
a driver outside the top eight by form line whose projection ranks inside the top ten. Risers / buy-low and fades /
sell-high compare form with the underlying pace (the decomposition's pace above the field and the car's trend over
five rounds, from value.json) and with luck (championship points against the forecasts' expectation).

Backtest
--------
For every Grand Prix weekend with results (2012 onward: the walk-forward race components cached by
scripts/f1_tune.py prep, built live for rounds the cache does not have), the projection made before qualifying
(data strictly before the weekend, practice included as in the qualifying model) is scored against the weekend's
actual fantasy points with the same table. Baselines: the driver's season-to-date average, his previous weekend, last
season's average (each falling back to the previous season's mean per driver-weekend when the driver has no
history). Metrics: mean absolute error, bias, the per-race Spearman rank correlation averaged over races, the overlap
of predicted and actual top fives, the points the top pick scored, and the share of actual totals inside the 10-90%
interval. Results are cached per race under data/f1/cache/fantasy/ (keyed on the race inputs, the fitted constants,
the overtake and pit models and the simulation count).

    python -m oddsmarkets.f1.analytics.fantasy backtest --from 2012 --to 2026 --sims 2000
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from oddsmarkets.f1 import canon
from oddsmarkets.f1.analytics import fnum, inum, status_kind

logger = logging.getLogger(__name__)

VERSION = "f1fantasy-1"
SIMS = 4000                 # rest-of-season projection
BT_SIMS = 2000              # per backtest weekend
FIRST_OPENF1 = 2023         # overtakes and stationary pit times exist from here
FULL_FROM = FIRST_OPENF1 + 1
OVT_CAP = 20
OVT_MIN_RACES = 3
K_CIRCUIT, K_DRIVER = 1.5, 15.0
K_PIT = 3.0
K_FORM = 3.0
PIT_SEASON_W = {0: 1.0, 1: 0.35}

Q_PTS = (10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
Q_NC = -5
RACE_PTS = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
SPRINT_PTS = (8, 7, 6, 5, 4, 3, 2, 1)
GAIN = 1
RACE_FL, SPRINT_FL = 10, 5
RACE_DNF, SPRINT_DNF = -20, -10
OVERTAKE = 1
Q_BONUS = (("both_q3", 10), ("one_q3", 5), ("both_q2", 3), ("one_q2", 1), ("none_q2", -1))
PIT_BANDS = ((2.0, 20), (2.2, 10), (2.5, 5), (3.0, 2))
PIT_FASTEST = 5

DCOMP = ["quali", "race_pos", "race_gain", "race_fl", "race_dnf", "overtakes", "sprint_pos", "sprint_gain", "sprint_fl", "sprint_dnf"]
CORE = [c for c in DCOMP if c != "overtakes"]
TCOMP = ["drivers", "q_bonus", "pit"]

SCORING = [  # the table the page shows: group, item, points, note
    ("Qualifying", "P1, P2 ... P10", "10, 9 ... 1", "P11 or lower 0"),
    ("Qualifying", "No time set", "-5", "classified without a Q1/Q2/Q3 time"),
    ("Grand Prix", "P1 ... P10", "25, 18, 15, 12, 10, 8, 6, 4, 2, 1", "classified finishers"),
    ("Grand Prix", "Positions gained / lost", "+1 / -1 per place", "against the grid slot; classified finishers only; pit-lane start = last slot"),
    ("Grand Prix", "Fastest lap", "+10", ""),
    ("Grand Prix", "Overtakes", "+1 each", "OpenF1 on-track passes (2023 on), pit-stop and safety-car changes removed, up to 20"),
    ("Grand Prix", "Not classified / disqualified", "-20", "no other race points"),
    ("Sprint", "P1 ... P8", "8, 7 ... 1", ""),
    ("Sprint", "Positions gained / lost", "+1 / -1 per place", ""),
    ("Sprint", "Fastest lap", "+5", ""),
    ("Sprint", "Not classified / disqualified", "-10", ""),
    ("Constructor", "Both drivers", "every driver item", "sum of the two drivers"),
    ("Constructor", "Qualifying progression", "both Q3 +10, one Q3 +5, both Q2 +3, one Q2 +1, neither -1", "the best that applies"),
    ("Constructor", "Fastest pit stop of the team", "<2.0 s +20, <2.2 s +10, <2.5 s +5, <3.0 s +2", "stationary time; only races with OpenF1 stationary times"),
    ("Constructor", "Fastest stop of the race", "+5", ""),
]
EXCLUDED = [
    ("Official F1 Fantasy costs, ownership, picks and scores",
     "Not used. formula1.com's legal notices: material on the site is \"for your personal, non-commercial use only\" and users "
     "agree not to \"distribute copy extract or commercially exploit such material or content\". The game at fantasy.formula1.com "
     "is a JavaScript app whose own terms could not be read without running it; nothing is fetched from it."),
    ("Driver of the day", "A fan vote: nothing in our data predicts it."),
    ("Sprint overtakes", "Left out: only the Grand Prix passes are filtered for pit stops and safety cars."),
    ("Overtakes before 2023", "OpenF1 starts in 2023; earlier seasons are scored without them (\"core\")."),
    ("Pit-stop bands where OpenF1 has no stationary times", "Not scored or projected (most of 2023-2024 and much of 2026)."),
    ("Streaks, team-mate bonuses, chips, transfers and budgets", "Game mechanics of particular fantasy games; this table scores the weekend only."),
]
LABEL = ("Our own fantasy-style scoring and projections from our race simulation. Not the official F1 Fantasy game: its "
         "costs, ownership and scores are not used (their terms do not allow it), so 'value' is measured against our own "
         "form line, a cost proxy, not against the game's costs.")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _r(x: Any, nd: int = 2) -> float | None:
    v = fnum(x)
    return None if v is None or not math.isfinite(v) else round(v, nd)


def cache_dir() -> Path:
    from oddsmarkets.f1.analytics import forecasts as fc
    return Path(fc.CACHE).parent / "fantasy"


def tune_dir() -> Path:
    from oddsmarkets.f1.analytics import forecasts as fc
    return Path(fc.CACHE).parent / "tune"


# ---------------------------------------------------------------------------------------------- scoring primitives

def quali_points(pos: Any) -> int:
    p = inum(pos)
    return Q_PTS[p - 1] if p is not None and 1 <= p <= len(Q_PTS) else 0


def finish_points(pos: Any, sprint: bool = False) -> int:
    t = SPRINT_PTS if sprint else RACE_PTS
    p = inum(pos)
    return t[p - 1] if p is not None and 1 <= p <= len(t) else 0


def q2_cut(n: int) -> int:
    """Cars into Q2 for a field of n: 15 of 20, 16 of 22, 17 of 24 (never more than the field)."""
    return min(int(n), 10 + max(0, (int(n) - 9) // 2))


def q_bonus(n_q2: int, n_q3: int) -> int:
    """Constructor qualifying progression: the best tier that applies."""
    if n_q3 >= 2:
        return 10
    if n_q3 == 1:
        return 5
    if n_q2 >= 2:
        return 3
    if n_q2 == 1:
        return 1
    return -1


def pit_points(stop_s: float | None) -> int:
    if stop_s is None:
        return 0
    for cut, pts in PIT_BANDS:
        if stop_s < cut:
            return pts
    return 0


def _table(pts: tuple, size: int) -> np.ndarray:
    t = np.zeros(max(size, len(pts)) + 2)
    t[1:len(pts) + 1] = pts
    return t


def score_session(slot: np.ndarray, pos: np.ndarray, cls: np.ndarray, fl: np.ndarray, sprint: bool = False) -> dict[str, np.ndarray]:
    """Vectorised driver points for one simulated session: arrays (n, D) of 1-based grid slot and finishing position,
    classified flags, and (n,) the fastest-lap car's column (-1 none). Returns the four components."""
    n, D = pos.shape
    t = _table(SPRINT_PTS if sprint else RACE_PTS, D)
    p = np.clip(pos.astype(int), 0, len(t) - 1)
    out = {"pos": np.where(cls, t[p], 0.0),
           "gain": np.where(cls, (slot.astype(float) - pos.astype(float)) * GAIN, 0.0),
           "fl": (np.arange(D)[None, :] == np.asarray(fl)[:, None]) * float(SPRINT_FL if sprint else RACE_FL),
           "dnf": np.where(cls, 0.0, float(SPRINT_DNF if sprint else RACE_DNF))}
    return out


def score_quali(qpos: np.ndarray) -> np.ndarray:
    t = _table(Q_PTS, qpos.shape[-1])
    return t[np.clip(qpos.astype(int), 0, len(t) - 1)]


def expected_from_dist(dist: list[float], table: tuple = RACE_PTS) -> float:
    """Expected points from a finishing-position distribution [P(P1), P(P2), ...]: sum P(pos) x points(pos)."""
    return float(sum(p * (table[i] if i < len(table) else 0) for i, p in enumerate(dist or [])))


# ---------------------------------------------------------------------------------------------- actual points

def _quali_rows(race: dict) -> dict[str, dict]:
    """{driver: {"pos", "pts", "q2", "q3", "team"}} from the qualifying classification."""
    rows = [r for r in race.get("qualifying") or [] if r.get("driver")]
    if not rows:
        return {}
    n = len(rows)
    any_t = any(r.get(k) for r in rows for k in ("q1", "q2", "q3"))
    any_q2 = any(r.get("q2") for r in rows)
    any_q3 = any(r.get("q3") for r in rows)
    out = {}
    for r in rows:
        pos = inum(r.get("position"))
        timed = any(r.get(k) for k in ("q1", "q2", "q3"))
        nc = any_t and not timed
        out[r["driver"]] = {"pos": pos, "pts": Q_NC if nc else quali_points(pos), "team": r.get("constructor"),
                            "q2": bool(r.get("q2")) if any_q2 else (pos is not None and pos <= q2_cut(n)),
                            "q3": bool(r.get("q3")) if any_q3 else (pos is not None and pos <= 10)}
    return out


def _session_rows(rows: list[dict], sprint: bool) -> dict[str, dict]:
    """{driver: {"c": components, "slot", "pos", "cls", "started", "team"}} for a race or sprint classification."""
    rows = [r for r in rows or [] if r.get("driver")]
    started = [r for r in rows if status_kind(r) != "dns"]
    n = len(started)
    pre = "sprint_" if sprint else "race_"
    out = {}
    for r in rows:
        k = status_kind(r)
        d = r["driver"]
        c = {pre + "pos": 0, pre + "gain": 0, pre + "fl": 0, pre + "dnf": 0}
        g = inum(r.get("grid")) or 0
        slot = g if g > 0 else n
        pos = inum(r.get("position"))
        if k == "dns":
            out[d] = {"c": c, "slot": None, "pos": None, "cls": False, "started": False, "team": r.get("constructor")}
            continue
        if k == "finished" and pos:
            c[pre + "pos"] = finish_points(pos, sprint)
            c[pre + "gain"] = (slot - pos) * GAIN
        else:
            c[pre + "dnf"] = SPRINT_DNF if sprint else RACE_DNF
        if inum(r.get("fastest_rank")) == 1 and k != "dsq":
            c[pre + "fl"] = SPRINT_FL if sprint else RACE_FL
        out[d] = {"c": c, "slot": slot, "pos": pos if k == "finished" else None, "cls": k == "finished", "started": True,
                  "team": r.get("constructor")}
    return out


def actual_weekend(year: int, rnd: int, overtakes: bool = True, pits: bool = True) -> dict | None:
    """Actual fantasy points of one weekend (our table): {"year", "round", "circuit", "sprint", "has_ovt", "has_pit",
    "drivers": {d: {"team", "c": {component: pts}, "started", "slot", "pos", "cls", "ovt"}}, "teams": {t: {"drivers",
    "q_bonus", "pit", "best_stop_s", "fastest"}}}. Parts not yet run are simply absent (a weekend in progress has its
    qualifying and sprint); None when nothing has run."""
    race = canon.race(year, rnd)
    if not race:
        return None
    Q = _quali_rows(race)
    R = _session_rows(race.get("results") or [], False)
    S = _session_rows(race.get("sprint") or [], True)
    if not (Q or R or S):
        return None
    drivers: dict[str, dict] = {}
    for d in list(R) + [d for d in Q if d not in R] + [d for d in S if d not in R and d not in Q]:
        c = {k: 0 for k in DCOMP}
        if d in Q:
            c["quali"] = Q[d]["pts"]
        if d in R:
            c.update(R[d]["c"])
        if d in S:
            c.update(S[d]["c"])
        team = (R.get(d) or {}).get("team") or (Q.get(d) or {}).get("team") or (S.get(d) or {}).get("team")
        drivers[d] = {"team": team, "c": c, "started": bool((R.get(d) or {}).get("started")), "slot": (R.get(d) or {}).get("slot"),
                      "pos": (R.get(d) or {}).get("pos"), "cls": bool((R.get(d) or {}).get("cls")), "ovt": None}
    has_ovt = has_pit = False
    best_stop: dict[str, float] = {}
    if (overtakes or pits) and int(year) >= FIRST_OPENF1 and R:
        from oddsmarkets.f1.analytics import context as _ctx
        ctx = _ctx.get(year, rnd)
        if overtakes and ctx.session("race"):
            has_ovt = True
            cnt: dict[str, int] = {}
            for o in ctx.overtakes():
                cnt[o["by"]] = cnt.get(o["by"], 0) + 1
            for d, v in drivers.items():
                if v["started"]:
                    v["ovt"] = cnt.get(d, 0)
                    v["c"]["overtakes"] = min(cnt.get(d, 0), OVT_CAP) * OVERTAKE
        if pits:
            for p in ctx.pits():
                s = p.get("stop_ms")
                t = (drivers.get(p["driver"]) or {}).get("team")
                if s and 1500 <= s <= 30000 and t:
                    best_stop[t] = min(best_stop.get(t, 99.0), s / 1000.0)
            has_pit = bool(best_stop)
    teams: dict[str, dict] = {}
    for d, v in drivers.items():
        if v["team"]:
            teams.setdefault(v["team"], {"drivers": []})["drivers"].append(d)
    fastest = min(best_stop, key=best_stop.get) if best_stop else None
    for t, x in teams.items():
        if Q:
            qs = [Q[d] for d in x["drivers"] if d in Q]
            x["q_bonus"] = q_bonus(sum(1 for q in qs if q["q2"]), sum(1 for q in qs if q["q3"]))
        else:
            x["q_bonus"] = 0
        x["best_stop_s"] = best_stop.get(t)
        x["fastest"] = t == fastest
        x["pit"] = (pit_points(best_stop.get(t)) + (PIT_FASTEST if t == fastest else 0)) if has_pit else None
    circuit = (race.get("circuit") or {}).get("id")
    return {"year": int(year), "round": int(rnd), "circuit": circuit, "sprint": bool(S), "has_quali": bool(Q), "has_race": bool(R),
            "has_ovt": has_ovt, "has_pit": has_pit, "drivers": drivers, "teams": teams}


def driver_total(v: dict, full: bool = True) -> float:
    return float(sum(x for k, x in (v.get("c") or {}).items() if full or k != "overtakes"))


def team_total(aw: dict, t: str, full: bool = True, pit: bool = False) -> float:
    x = aw["teams"][t]
    s = sum(driver_total(aw["drivers"][d], full) for d in x["drivers"]) + x.get("q_bonus", 0)
    if pit and x.get("pit") is not None:
        s += x["pit"]
    return float(s)


def _season_sig(year: int) -> str:
    from oddsmarkets.f1.analytics import data_root
    from oddsmarkets.f1.analytics import forecasts as fc
    h = hashlib.sha1(f"{VERSION}|{year}".encode())
    for r, dg in sorted(fc._round_digests(year).items()):
        h.update(f"{r}:{dg}".encode())
    try:
        h.update("|".join(sorted(f.name for f in (data_root() / str(year) / "sessions").glob("*.json"))).encode())
    except OSError:
        pass
    return h.hexdigest()[:16]


_ACTUALS: dict[int, tuple[str, dict]] = {}


def season_actuals(year: int, use_cache: bool = True) -> dict[int, dict]:
    """{round: actual_weekend} for every round of a season that has run (whole or in part); cached in memory and on disk
    per season on the store's round digests and the OpenF1 session files."""
    year = int(year)
    sig = _season_sig(year)
    hit = _ACTUALS.get(year)
    if hit and hit[0] == sig:
        return hit[1]
    p = cache_dir() / f"actuals_{year}.json"
    if use_cache and p.exists():
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            if c.get("sig") == sig:
                out = {int(k): v for k, v in c["rounds"].items()}
                _ACTUALS[year] = (sig, out)
                return out
        except (OSError, ValueError, KeyError):
            pass
    out = {}
    for r in canon.rounds(year):
        try:
            aw = actual_weekend(year, r)
        except Exception as exc:                                  # noqa: BLE001 - one bad round must not stop a season
            logger.warning("fantasy actuals %s/%s: %s", year, r, exc)
            aw = None
        if aw:
            out[r] = aw
    _ACTUALS[year] = (sig, out)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"sig": sig, "rounds": {str(k): v for k, v in out.items()}}, separators=(",", ":")), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------------------------- overtakes and pit stops

class OvertakeModel:
    """Expected Grand Prix overtakes per driver per simulated race (module docstring)."""

    def __init__(self, coef: tuple[float, float, float, float], mean: float, circuit: dict[str, float], driver: dict[str, float],
                 races: int):
        self.coef, self.mean, self.circuit, self.driver, self.races = tuple(float(c) for c in coef), float(mean), circuit, driver, races

    @staticmethod
    def rows_from(actuals: Iterable[dict]) -> list[tuple]:
        """(race key, circuit, driver, gained, lost, finished, overtakes) for every starter of every race with OpenF1 overtakes."""
        rows = []
        for aw in actuals:
            if not aw or not aw.get("has_ovt"):
                continue
            key = f"{aw['year']}_{aw['round']}"
            for d, v in aw["drivers"].items():
                if not v.get("started") or v.get("ovt") is None:
                    continue
                fin = bool(v.get("cls"))
                diff = (v["slot"] - v["pos"]) if fin and v.get("slot") and v.get("pos") else 0
                rows.append((key, aw.get("circuit"), d, max(diff, 0), max(-diff, 0), int(fin), min(int(v["ovt"]), OVT_CAP)))
        return rows

    @classmethod
    def fit(cls, rows: list[tuple]) -> "OvertakeModel | None":
        races = {r[0] for r in rows}
        if len(races) < OVT_MIN_RACES:
            return None
        X = np.array([[1.0, r[3], r[4], r[5]] for r in rows], float)
        y = np.array([r[6] for r in rows], float)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        m = float(y.mean()) or 1.0
        per_race: dict[str, list[float]] = {}
        circ_of: dict[str, str] = {}
        for r in rows:
            per_race.setdefault(r[0], []).append(r[6])
            circ_of[r[0]] = r[1]
        by_c: dict[str, list[float]] = {}
        for k, v in per_race.items():
            by_c.setdefault(circ_of[k], []).append(float(np.mean(v)))
        fc = {c: (sum(v) + K_CIRCUIT * m) / ((len(v) + K_CIRCUIT) * m) for c, v in by_c.items() if c}
        pred = np.maximum(0.2, X @ coef) * np.array([fc.get(r[1], 1.0) for r in rows])
        obs: dict[str, float] = {}
        exp: dict[str, float] = {}
        for r, p in zip(rows, pred):
            obs[r[2]] = obs.get(r[2], 0.0) + r[6]
            exp[r[2]] = exp.get(r[2], 0.0) + float(p)
        fd = {d: (obs[d] + K_DRIVER * m) / (exp[d] + K_DRIVER * m) for d in obs}
        return cls(tuple(coef), m, fc, fd, len(races))

    def lam(self, drivers: list[str], circuit: str | None, slot: np.ndarray, pos: np.ndarray, cls: np.ndarray) -> np.ndarray:
        diff = np.where(cls, slot.astype(float) - pos.astype(float), 0.0)
        b0, b1, b2, b3 = self.coef
        base = np.maximum(0.2, b0 + b1 * np.maximum(diff, 0) + b2 * np.maximum(-diff, 0) + b3 * cls)
        fd = np.array([self.driver.get(d, 1.0) for d in drivers])
        return base * self.circuit.get(circuit, 1.0) * fd[None, :]

    def digest(self) -> list:
        return [round(c, 4) for c in self.coef] + [round(self.mean, 4), self.races]


class PitModel:
    """Expected pit-stop points per team per Grand Prix (module docstring)."""

    def __init__(self, exp: dict[str, tuple[float, float]], field: float, races: int):
        self.exp, self.field, self.races = exp, field, races

    @classmethod
    def fit(cls, actuals: Iterable[dict], year: int) -> "PitModel | None":
        num: dict[str, float] = {}
        fast: dict[str, float] = {}
        w_t: dict[str, float] = {}
        tot = tot_w = 0.0
        races = 0
        n_teams: list[int] = []
        for aw in actuals:
            if not aw or not aw.get("has_pit"):
                continue
            w = PIT_SEASON_W.get(int(year) - int(aw["year"]), 0.0)
            if w <= 0:
                continue
            races += 1
            n_teams.append(len(aw["teams"]))
            for t, x in aw["teams"].items():
                if x.get("best_stop_s") is None:
                    continue
                pts = pit_points(x["best_stop_s"])
                num[t] = num.get(t, 0.0) + w * pts
                fast[t] = fast.get(t, 0.0) + w * (1.0 if x.get("fastest") else 0.0)
                w_t[t] = w_t.get(t, 0.0) + w
                tot += w * pts
                tot_w += w
        if not races or tot_w <= 0:
            return None
        field = tot / tot_w
        share = 1.0 / max(1.0, float(np.mean(n_teams)))
        exp = {t: ((num[t] + K_PIT * field) / (w_t[t] + K_PIT), (fast[t] + K_PIT * share) / (w_t[t] + K_PIT)) for t in w_t}
        exp["__field__"] = (field, share)
        return cls(exp, field, races)

    def expected(self, team: str) -> float:
        b, f = self.exp.get(team) or self.exp["__field__"]
        return float(b + PIT_FASTEST * f)

    def detail(self, team: str) -> tuple[float, float]:
        return self.exp.get(team) or self.exp["__field__"]

    def digest(self) -> list:
        return [self.races, round(self.field, 4)] + sorted((t, round(a, 4), round(b, 4)) for t, (a, b) in self.exp.items())


# ---------------------------------------------------------------------------------------------- simulated weekends

def _session_samples(inp, n: int, seed: int, sprint: bool, offsets: np.ndarray | None = None) -> dict:
    from oddsmarkets.f1.models import race_sim as rs
    res = rs.simulate_race(inp, n=n, seed=seed, sprint=sprint, return_samples=True, offsets=offsets, draw_param=offsets is None)
    s = res["_samples"]
    return {"drivers": list(s["drivers"]), "slot": s["grid"].astype(int), "pos": s["pos"].astype(int), "cls": s["classified"],
            "fl": s["fl"].astype(int), "team": dict(inp.team)}


def weekend_points(race: dict | None, sprint: dict | None, drivers: list[str], teams: list[str], team_of: dict[str, str],
                   known: dict | None = None, ovt: OvertakeModel | None = None, circuit: str | None = None,
                   pit: PitModel | None = None, n: int | None = None) -> dict:
    """Per simulated weekend points. race / sprint: session samples (``_session_samples``) or None; known: the actual
    parts of a weekend in progress ({"quali": {d: {pos, pts, q2, q3}}, "sprint": {d: {component: pts}}}). Returns
    {"comp": {component: (n, D)}, "total": (n, D), "core": (n, D), "team": (n, T), "team_core": (n, T),
    "q_bonus": (n, T), "pit": (T,), "qpos": (n, D) or None, "race": race samples aligned to drivers}."""
    known = known or {}
    n = n or len((race or sprint or {}).get("pos", [[]]))
    D, T = len(drivers), len(teams)
    di = {d: i for i, d in enumerate(drivers)}
    comp = {k: np.zeros((n, D)) for k in DCOMP}
    qpos = None
    aligned = {}
    for kind, s in (("race", race), ("sprint", sprint)):
        if s is None:
            continue
        cols = np.array([di[d] for d in s["drivers"]])
        sc = score_session(s["slot"], s["pos"], s["cls"], s["fl"], sprint=(kind == "sprint"))
        pre = kind + "_"
        for k, v in sc.items():
            comp[pre + k][:, cols] = v
        if kind == "race":
            slot = np.zeros((n, D), int)
            pos = np.zeros((n, D), int)
            cls = np.zeros((n, D), bool)
            slot[:, cols], pos[:, cols], cls[:, cols] = s["slot"], s["pos"], s["cls"]
            aligned = {"slot": slot, "pos": pos, "cls": cls, "cols": cols}
            qpos = np.full((n, D), 99, int)
            qpos[:, cols] = s["slot"]
            if ovt is not None:
                comp["overtakes"][:, cols] = OVERTAKE * ovt.lam(s["drivers"], circuit, s["slot"], s["pos"], s["cls"])
    # known parts replace the simulated ones
    kq = known.get("quali") or {}
    if kq:
        qpos = np.full((n, D), 99, int)
        for d, q in kq.items():
            if d in di:
                qpos[:, di[d]] = q.get("pos") or 99
                comp["quali"][:, di[d]] = q.get("pts", 0)
    elif qpos is not None:
        comp["quali"] = score_quali(qpos)
    for d, c in (known.get("sprint") or {}).items():
        if d in di:
            for k, v in c.items():
                if k.startswith("sprint_"):
                    comp[k][:, di[d]] = v
    total = sum(comp.values())
    core = total - comp["overtakes"]
    team_tot = np.zeros((n, T))
    team_core = np.zeros((n, T))
    qb = np.zeros((n, T))
    pit_e = np.zeros(T)
    field = len((race or {}).get("drivers") or drivers)
    cut = q2_cut(field)
    for j, t in enumerate(teams):
        cols = [di[d] for d in drivers if team_of.get(d) == t]
        if not cols:
            continue
        team_tot[:, j] = total[:, cols].sum(axis=1)
        team_core[:, j] = core[:, cols].sum(axis=1)
        if kq:
            qs = [kq[d] for d in drivers if team_of.get(d) == t and d in kq]
            qb[:, j] = q_bonus(sum(1 for q in qs if q.get("q2")), sum(1 for q in qs if q.get("q3")))
        elif qpos is not None:
            sub = qpos[:, cols]
            n2, n3 = (sub <= cut).sum(axis=1), (sub <= 10).sum(axis=1)
            qb[:, j] = np.where(n3 >= 2, 10, np.where(n3 == 1, 5, np.where(n2 >= 2, 3, np.where(n2 == 1, 1, -1))))
        if pit is not None and race is not None:
            pit_e[j] = pit.expected(t)
    team_tot += qb + pit_e[None, :]
    team_core += qb
    return {"comp": comp, "total": total, "core": core, "team": team_tot, "team_core": team_core, "q_bonus": qb, "pit": pit_e,
            "qpos": qpos, "race": aligned}


def _q(a: np.ndarray, q: float) -> np.ndarray:
    return np.percentile(a, q, axis=0)


def summarise(wp: dict, drivers: list[str], teams: list[str]) -> dict:
    """Means, floors and ceilings and the per-driver probabilities the page shows."""
    tot, core = wp["total"], wp["core"]
    p10, p50, p90 = _q(tot, 10), _q(tot, 50), _q(tot, 90)
    c10, c90 = _q(core, 10), _q(core, 90)
    qpos = wp.get("qpos")
    rc = wp.get("race") or {}
    out_d = {}
    for i, d in enumerate(drivers):
        x = {"mean": float(tot[:, i].mean()), "core": float(core[:, i].mean()), "p10": float(p10[i]), "p50": float(p50[i]),
             "p90": float(p90[i]), "core_p10": float(c10[i]), "core_p90": float(c90[i]),
             "comp": {k: float(v[:, i].mean()) for k, v in wp["comp"].items()}}
        if qpos is not None:
            x["p_q3"] = float(np.mean(qpos[:, i] <= 10))
            x["p_front"] = float(np.mean(qpos[:, i] <= 4))
            x["exp_qpos"] = float(np.mean(np.minimum(qpos[:, i], 30)))
        if rc:
            x["p_dnf"] = float(np.mean(~rc["cls"][:, i])) if i in set(rc["cols"].tolist()) else None
            x["p_fl"] = float(np.mean(wp["comp"]["race_fl"][:, i] > 0))
            x["p_top10"] = float(np.mean(rc["cls"][:, i] & (rc["pos"][:, i] <= 10)))
        out_d[d] = x
    tt, tc = wp["team"], wp["team_core"]
    t10, t90 = _q(tt, 10), _q(tt, 90)
    out_t = {t: {"mean": float(tt[:, j].mean()), "core": float(tc[:, j].mean()), "p10": float(t10[j]), "p90": float(t90[j]),
                 "q_bonus": float(wp["q_bonus"][:, j].mean()), "pit": float(wp["pit"][j]),
                 "drivers": float((tt[:, j] - wp["q_bonus"][:, j] - wp["pit"][j]).mean())} for j, t in enumerate(teams)}
    return {"drivers": out_d, "teams": out_t}


# ---------------------------------------------------------------------------------------------- inputs

def _comp_source(year: int, rnd: int) -> str:
    """What the pre-qualifying race components of a weekend come from, cheaply (the cache key): the walk-forward cache of
    scripts/f1_tune.py when it has the race, else the forecast signature of the data before it."""
    p = tune_dir() / f"{year}_{rnd}.pkl"
    if p.exists():
        st = p.stat()
        return f"tune:{st.st_size}:{int(st.st_mtime)}"
    from oddsmarkets.f1.analytics import forecasts as fc
    return "live:" + fc.signature(year, rnd, "pre", 0)


def _components(year: int, rnd: int, before_quali: bool = True) -> dict | None:
    """The race components (``race_sim.race_components``): before qualifying from the walk-forward cache of
    scripts/f1_tune.py when it has the race, else built now (data strictly before the race either way)."""
    from oddsmarkets.f1.models import race_sim as rs
    p = tune_dir() / f"{year}_{rnd}.pkl"
    if before_quali and p.exists():
        try:
            with open(p, "rb") as fh:
                return pickle.load(fh)
        except Exception as exc:                                   # noqa: BLE001
            logger.info("tune pickle %s unreadable: %s", p, exc)
    return rs.race_components(year, rnd, before_quali=before_quali, session="race")


def weekend_inputs(comp: dict, sprint: bool, before_quali: bool = True):
    """(race RaceInputs, sprint RaceInputs or None) from race components. The sprint shares the race's inputs at the sprint
    distance; before qualifying both draw their grid from the same qualifying-model distribution."""
    from oddsmarkets.f1.models import race_sim as rs
    c = dict(comp)
    if before_quali:
        c["grid"] = None
        c.pop("grid_actual", None)
    race = rs.inputs_from_components(c)
    spr = None
    if sprint:
        cs = dict(c, session="sprint", quali_pace=None)
        if not before_quali:
            cs["grid"] = None
        spr = rs.inputs_from_components(cs)
    return race, spr


def _params_digest() -> str:
    from oddsmarkets.f1.models import race_sim as rs
    try:
        return hashlib.sha1(rs.FITTED_PATH.read_bytes()).hexdigest()[:12]
    except OSError:
        return "none"


# ---------------------------------------------------------------------------------------------- backtest

def spearman(x: Iterable[float], y: Iterable[float]) -> float | None:
    """Spearman rank correlation with average ranks for ties; None when either side is constant or n < 3."""
    a, b = np.asarray(list(x), float), np.asarray(list(y), float)
    if len(a) < 3 or len(a) != len(b):
        return None

    def rank(v):
        o = np.argsort(v, kind="mergesort")
        r = np.empty(len(v))
        r[o] = np.arange(1, len(v) + 1)
        for u in np.unique(v):
            m = v == u
            if m.sum() > 1:
                r[m] = r[m].mean()
        return r
    ra, rb = rank(a), rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def top_overlap(pred: dict[str, float], actual: dict[str, float], k: int = 5) -> float | None:
    if len(pred) < k:
        return None
    tp = set(sorted(pred, key=lambda d: (-pred[d], d))[:k])
    ta = set(sorted(actual, key=lambda d: (-actual[d], d))[:k])
    return len(tp & ta) / float(k)


def score_method(races: list[tuple[dict[str, float], dict[str, float]]], k: int = 5) -> dict:
    """Metrics of one method over races [(pred {id: pts}, actual {id: pts})] on the ids both have: MAE, RMSE, bias
    (pred - actual), per-race Spearman averaged, top-k overlap, the actual points of the top pick, and the count."""
    err, rho, ovl, top = [], [], [], []
    for item in races:
        pred, act = item[0], item[1]
        ids = [d for d in act if d in pred and pred[d] is not None]
        if not ids:
            continue
        e = [pred[d] - act[d] for d in ids]
        err.extend(e)
        s = spearman([pred[d] for d in ids], [act[d] for d in ids])
        if s is not None:
            rho.append(s)
        o = top_overlap({d: pred[d] for d in ids}, {d: act[d] for d in ids}, k)
        if o is not None:
            ovl.append(o)
        best = max(ids, key=lambda d: (pred[d], d))
        top.append(act[best])
    if not err:
        return {"n": 0}
    e = np.array(err)
    return {"n": int(len(e)), "races": len(races), "mae": round(float(np.abs(e).mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3),
            "bias": round(float(e.mean()), 3), "spearman": round(float(np.mean(rho)), 4) if rho else None,
            "top5": round(float(np.mean(ovl)), 4) if ovl else None, "top_pick": round(float(np.mean(top)), 3) if top else None}


def coverage(rows: list[tuple[float, float, float]]) -> float | None:
    """Share of actual values inside [lo, hi]; rows (lo, hi, actual)."""
    if not rows:
        return None
    return round(float(np.mean([lo <= a <= hi for lo, hi, a in rows])), 4)


class _History:
    """Actual weekend totals per driver / team in order, for the baselines."""

    def __init__(self, actuals: dict[int, dict[int, dict]]):
        self.seq: list[tuple[int, int, dict]] = [(y, r, aw) for y in sorted(actuals) for r, aw in sorted(actuals[y].items()) if aw.get("has_race")]

    def before(self, y: int, r: int) -> list[tuple[int, int, dict]]:
        return [t for t in self.seq if (t[0], t[1]) < (y, r)]

    @staticmethod
    def _vals(aw: dict, full: bool, teams: bool) -> dict[str, float]:
        if teams:
            return {t: team_total(aw, t, full) for t in aw["teams"]}
        return {d: driver_total(v, full) for d, v in aw["drivers"].items() if v.get("started") or v["c"].get("quali")}

    def baselines(self, y: int, r: int, full: bool, teams: bool = False) -> dict[str, dict[str, float]]:
        prior = self.before(y, r)
        this = [aw for (yy, rr, aw) in prior if yy == y]
        last = [aw for (yy, rr, aw) in prior if yy == y - 1]
        acc_this: dict[str, list[float]] = {}
        acc_last: dict[str, list[float]] = {}
        prev: dict[str, float] = {}
        for aw in last:
            for k, v in self._vals(aw, full, teams).items():
                acc_last.setdefault(k, []).append(v)
        for aw in this:
            for k, v in self._vals(aw, full, teams).items():
                acc_this.setdefault(k, []).append(v)
        for (_, _, aw) in prior[-60:]:
            prev.update(self._vals(aw, full, teams))
        allv = [v for vs in acc_last.values() for v in vs] or [v for vs in acc_this.values() for v in vs]
        const = float(np.mean(allv)) if allv else 0.0
        last_avg = {k: float(np.mean(v)) for k, v in acc_last.items()}
        std = {k: float(np.mean(v)) for k, v in acc_this.items()}
        return {"std": std, "last": last_avg, "prev": prev, "const": const}


def _predict_weekend(y: int, r: int, n: int, actuals: dict[int, dict[int, dict]], hist: _History, cache: dict) -> dict | None:
    """The pre-qualifying projection of one finished weekend (cached on its inputs)."""
    race = canon.race(y, r)
    if not race.get("results"):
        return None
    prior = [aw for (_, _, aw) in hist.before(y, r)]
    ovt = OvertakeModel.fit(OvertakeModel.rows_from(prior)) if y >= FIRST_OPENF1 else None
    pit = PitModel.fit(prior, y) if y >= FIRST_OPENF1 else None
    sprint = bool(race.get("sprint"))
    key = hashlib.sha1(json.dumps([VERSION, n, y, r, _comp_source(y, r), sprint, _params_digest(), ovt.digest() if ovt else None,
                                   pit.digest() if pit else None], default=str).encode()).hexdigest()[:16]
    hit = cache.get(f"{y}_{r}")
    if hit and hit.get("key") == key:
        return hit
    comp = _components(y, r, before_quali=True)
    if comp is None or not comp.get("drivers"):
        return None
    rin, sin = weekend_inputs(comp, sprint)
    seed = 1000 * y + r
    rs_ = _session_samples(rin, n, seed, False)
    ss_ = _session_samples(sin, n, seed, True) if sin is not None else None
    drivers = list(dict.fromkeys(list(rin.drivers) + (list(sin.drivers) if sin is not None else [])))
    team_of = {**(sin.team if sin is not None else {}), **rin.team}
    teams = sorted(set(team_of.values()))
    wp = weekend_points(rs_, ss_, drivers, teams, team_of, ovt=ovt, circuit=(race.get("circuit") or {}).get("id"), pit=pit, n=n)
    sm = summarise(wp, drivers, teams)
    rec = {"key": key, "ovt": ovt is not None, "pit": pit is not None, "sprint": sprint,
           "drivers": {d: [round(v["mean"], 3), round(v["core"], 3), round(v["p10"], 2), round(v["p90"], 2), round(v["core_p10"], 2),
                           round(v["core_p90"], 2)] for d, v in sm["drivers"].items()},
           "teams": {t: [round(v["core"], 3), round(v["mean"] - v["pit"], 3), round(v["p10"], 2), round(v["p90"], 2), round(v["pit"], 3)]
                     for t, v in sm["teams"].items()}}
    cache[f"{y}_{r}"] = rec
    return rec


def backtest(seasons: Iterable[int], n: int = BT_SIMS, use_cache: bool = True, refresh_past: bool = True,
             progress: bool = False) -> dict:
    """Walk-forward race-by-race backtest of the weekend projection against actual fantasy points (module docstring).

    ``refresh_past`` False keeps cached weekends of earlier seasons even when their key is stale (the hourly build:
    only the current season is recomputed; the CLI refreshes everything). Never raises on a missing race."""
    t0 = time.perf_counter()
    seasons = sorted({int(s) for s in seasons})
    if not seasons:
        return {"ok": False, "reason": "no seasons"}
    cur = max(seasons)
    cpath = cache_dir() / "backtest_preds.json"
    cache: dict = {}
    if use_cache and cpath.exists():
        try:
            cache = json.loads(cpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    if cache.get("_n") != n:
        cache = {"_n": n}
    actuals = {y: season_actuals(y) for y in range(min(seasons) - 1, cur + 1)}
    hist = _History(actuals)
    per_race = []
    rows: dict[str, list] = {}
    cover: dict[str, list] = {}
    pit_rows: dict[str, list] = {"model": [], "std": []}
    errors = []
    new = 0
    for y in seasons:
        for r in sorted(actuals.get(y) or {}):
            aw = actuals[y][r]
            if not aw.get("has_race"):
                continue
            k = f"{y}_{r}"
            try:
                if not refresh_past and y < cur and k in cache:
                    pred = cache[k]
                else:
                    before = cache.get(k, {}).get("key")
                    pred = _predict_weekend(y, r, n, actuals, hist, cache)
                    if pred and pred.get("key") != before:
                        new += 1
                        if progress:
                            logger.info("fantasy backtest %s: %.0f s", k, time.perf_counter() - t0)
            except Exception as exc:                               # noqa: BLE001 - never let one race stop the run
                errors.append(f"{k}: {exc}")
                logger.warning("fantasy backtest %s failed: %s", k, exc)
                continue
            if not pred:
                continue
            rec = {"y": y, "r": r}
            for full in (False, True):
                if full and not (y >= FULL_FROM and aw.get("has_ovt") and pred.get("ovt")):
                    continue
                tag = "full" if full else "core"
                act = {d: driver_total(v, full) for d, v in aw["drivers"].items() if v.get("started") and d in pred["drivers"]}
                if len(act) < 3:
                    continue
                bl = hist.baselines(y, r, full)
                model = {d: pred["drivers"][d][0 if full else 1] for d in act}
                std = {d: bl["std"].get(d, bl["last"].get(d, bl["const"])) for d in act}
                prev = {d: bl["prev"].get(d, bl["const"]) for d in act}
                last = {d: bl["last"].get(d, bl["const"]) for d in act}
                blend = {d: 0.5 * model[d] + 0.5 * std[d] for d in act}
                for name, P in (("model", model), ("std", std), ("prev", prev), ("last", last), ("blend", blend)):
                    rows.setdefault(f"drivers_{tag}", {}).setdefault(name, []).append((P, act, y))
                lo_i, hi_i = (2, 3) if full else (4, 5)
                cover.setdefault(f"drivers_{tag}", []).extend((pred["drivers"][d][lo_i], pred["drivers"][d][hi_i], act[d]) for d in act)
                # constructors (pit points separately)
                tact = {t: team_total(aw, t, full) for t in aw["teams"] if t in pred["teams"]}
                if len(tact) >= 3:
                    tb = hist.baselines(y, r, full, teams=True)
                    tm = {t: pred["teams"][t][1 if full else 0] for t in tact}
                    ts = {t: tb["std"].get(t, tb["last"].get(t, tb["const"])) for t in tact}
                    tp = {t: tb["prev"].get(t, tb["const"]) for t in tact}
                    tl = {t: tb["last"].get(t, tb["const"]) for t in tact}
                    for name, P in (("model", tm), ("std", ts), ("prev", tp), ("last", tl)):
                        rows.setdefault(f"teams_{tag}", {}).setdefault(name, []).append((P, tact, y))
                if not full:
                    sm = score_method([(model, act)])
                    ss = score_method([(std, act)])
                    rec.update(mae=sm.get("mae"), mae_std=ss.get("mae"), rho=sm.get("spearman"), rho_std=ss.get("spearman"))
            if aw.get("has_pit") and pred.get("pit"):
                prior_pit = [a for (yy, rr, a) in hist.before(y, r) if yy == y and a.get("has_pit")]
                for t, x in aw["teams"].items():
                    if x.get("pit") is None or t not in pred["teams"]:
                        continue
                    pit_rows["model"].append((pred["teams"][t][4], x["pit"]))
                    own = [a["teams"][t]["pit"] for a in prior_pit if t in a["teams"] and a["teams"][t].get("pit") is not None]
                    allp = [a["teams"][u]["pit"] for a in prior_pit for u in a["teams"] if a["teams"][u].get("pit") is not None]
                    pit_rows["std"].append((float(np.mean(own)) if own else (float(np.mean(allp)) if allp else 5.0), x["pit"]))
            per_race.append(rec)
    try:
        cpath.parent.mkdir(parents=True, exist_ok=True)
        tmp = cpath.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
        tmp.replace(cpath)
    except OSError:
        pass
    metrics = {g: {name: score_method(v) for name, v in m.items()} for g, m in rows.items()}
    for g, cv in cover.items():
        metrics[g]["model"]["coverage_80"] = coverage(cv)
    pit_m = {}
    for name, v in pit_rows.items():
        if v:
            e = np.array([p - a for p, a in v])
            pit_m[name] = {"n": len(v), "mae": round(float(np.abs(e).mean()), 3), "bias": round(float(e.mean()), 3)}
    per_season = {}
    for y in seasons:
        ys = {g: {name: score_method([x for x in v if x[2] == y]) for name, v in m.items()} for g, m in rows.items()}
        ys = {g: {name: v for name, v in m.items() if v.get("n")} for g, m in ys.items()}
        ys = {g: m for g, m in ys.items() if m}
        if ys:
            per_season[str(y)] = ys
    return {"ok": True, "version": VERSION, "generated_at": _now(), "n_sims": n, "seasons": seasons, "races": len(per_race),
            "metrics": metrics, "pit": pit_m, "per_season": per_season,
            "per_race": [[x["y"], x["r"], x.get("mae"), x.get("mae_std"), _r(x.get("rho"), 3), _r(x.get("rho_std"), 3)] for x in per_race],
            "new": new, "errors": errors[:30], "runtime_s": round(time.perf_counter() - t0, 1)}



def backtest_summary(bt: dict) -> dict:
    """The compact block the fantasy page shows (the site-wide payload has everything)."""
    if not (bt or {}).get("ok"):
        return {"ok": False, "reason": (bt or {}).get("reason") or "no backtest"}
    keep = ("n", "races", "mae", "rmse", "bias", "spearman", "top5", "top_pick", "coverage_80")
    m = bt.get("metrics") or {}
    out = {"ok": True, "seasons": [min(bt["seasons"]), max(bt["seasons"])], "races": bt.get("races"), "n_sims": bt.get("n_sims"),
           "generated_at": bt.get("generated_at")}
    for g in ("drivers_core", "drivers_full", "teams_core", "teams_full"):
        if g in m:
            out[g] = {name: {k: v.get(k) for k in keep if v.get(k) is not None} for name, v in m[g].items()}
    if bt.get("pit"):
        out["pit"] = bt["pit"]
    return out



BASELINES = {"model": "our projection before qualifying (the race simulation, module docstring)",
             "std": "the driver's (constructor's) season-to-date average weekend points",
             "prev": "the driver's (constructor's) previous weekend's points",
             "last": "the driver's (constructor's) average weekend points last season",
             "blend": "half our projection, half the season-to-date average"}


def update_backtest(current: int, n: int = BT_SIMS) -> dict:
    """The hourly build's backtest: the seasons (and simulation count) of the cached full run (the CLI) plus the current
    season; weekends of earlier seasons come from the per-race cache as they are, only the current season's are
    recomputed when their inputs change. Without a cached run: the current and the previous season only."""
    p = cache_dir() / "backtest.json"
    seasons: list[int] = []
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            seasons = [int(y) for y in old.get("seasons") or []]
            n = int(old.get("n_sims") or n)
        except (OSError, ValueError):
            seasons = []
    if not seasons:
        seasons = [int(current) - 1]
    seasons = sorted(set(seasons) | {int(current)})
    bt = backtest(seasons, n=n, refresh_past=False)
    if bt.get("ok"):
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(bt, separators=(",", ":")), encoding="utf-8")
        except OSError:
            pass
    return bt


def backtest_payload(bt: dict | None) -> dict | None:
    """data/fantasy_backtest.json (PAYLOADS.md "As built")."""
    if not (bt or {}).get("ok"):
        return None
    return {"ok": True, "updated_at": bt.get("generated_at") or _now(), "version": VERSION, "seasons": bt.get("seasons"), "races": bt.get("races"),
            "n_sims": bt.get("n_sims"), "full_from": FULL_FROM, "baselines": BASELINES, "metrics": bt.get("metrics"), "pit": bt.get("pit"),
            "per_season": bt.get("per_season"), "per_race_cols": ["year", "round", "mae", "mae_std", "spearman", "spearman_std"],
            "per_race": bt.get("per_race"), "label": LABEL}

# ---------------------------------------------------------------------------------------------- the current season

def _prior_actuals(year: int, rnd: int, back: int = 3) -> list[dict]:
    out = []
    for y in range(int(year) - back, int(year) + 1):
        for r, aw in sorted(season_actuals(y).items()):
            if (y, r) < (int(year), int(rnd)) and aw.get("has_race"):
                out.append(aw)
    return out


def _known(year: int, rnd: int) -> dict:
    """The actual parts of a weekend in progress: its qualifying and its sprint."""
    race = canon.race(year, rnd)
    k: dict = {}
    q = _quali_rows(race)
    if q:
        k["quali"] = {d: {"pos": v["pos"], "pts": v["pts"], "q2": v["q2"], "q3": v["q3"]} for d, v in q.items()}
    if race.get("sprint"):
        k["sprint"] = {d: v["c"] for d, v in _session_rows(race["sprint"], True).items()}
    return k


def season_projection(year: int, n: int = SIMS, seed: int | None = None) -> dict:
    """Next weekend and rest of season: every remaining round simulated in one run with the championship's season-level
    correlation (module docstring). Never raises; {"ok": False, "reason"} when nothing is left to simulate."""
    from oddsmarkets.f1.models import championship as CH
    t0 = time.perf_counter()
    try:
        st = CH.season_state(year)
        remaining = st["remaining"]
        rounds = list(dict.fromkeys(r for r, _ in remaining))
        if not rounds:
            return {"ok": False, "reason": "no rounds left in the season"}
        nxt = rounds[0]
        prior = _prior_actuals(year, nxt)
        ovt = OvertakeModel.fit(OvertakeModel.rows_from(prior)) if int(year) >= FIRST_OPENF1 else None
        pit = PitModel.fit(prior, year) if int(year) >= FIRST_OPENF1 else None
        events = []
        for rnd in rounds:
            race = canon.race(year, rnd)
            q_done = bool(race.get("qualifying"))
            try:
                from oddsmarkets.f1.models import race_sim as rs
                comp = rs.race_components(year, rnd, before_quali=not q_done, session="race")
            except Exception as exc:                               # noqa: BLE001
                logger.warning("fantasy inputs %s/%s: %s", year, rnd, exc)
                continue
            if not comp or not comp.get("drivers"):
                continue
            rin, sin = weekend_inputs(comp, (rnd, "sprint") in remaining, before_quali=not q_done)
            sprint_wknd = bool((race.get("sessions") or {}).get("sprint") or race.get("sprint"))
            events.append({"round": rnd, "name": race.get("name"), "race": rin, "sprint": sin, "sprint_weekend": sprint_wknd,
                           "known": _known(year, rnd), "circuit": (race.get("circuit") or {}).get("id")})
        if not events:
            return {"ok": False, "reason": "no race inputs for the remaining rounds"}
        drivers = sorted({d for e in events for inp in (e["race"], e["sprint"]) if inp is not None for d in inp.drivers})
        team_last: dict[str, str] = {}
        for e in reversed(events):
            for inp in (e["race"], e["sprint"]):
                if inp is not None:
                    for d, t in inp.team.items():
                        team_last.setdefault(d, t)
        nxt_team = {**(events[0]["sprint"].team if events[0]["sprint"] is not None else {}), **events[0]["race"].team}
        teams = sorted({t for e in events for inp in (e["race"], e["sprint"]) if inp is not None for t in inp.team.values()})
        di, ti = {d: i for i, d in enumerate(drivers)}, {t: j for j, t in enumerate(teams)}
        D, T = len(drivers), len(teams)
        rng = np.random.default_rng(int(year) * 7 + 3 if seed is None else seed)
        z = rng.standard_normal((n, D))
        Fw = np.zeros((n, T))
        Gw = np.zeros((n, D))
        ros = np.zeros((n, D))
        ros_t = np.zeros((n, T))
        sched_d: dict[str, list] = {d: [] for d in drivers}
        sched_t: dict[str, list] = {t: [] for t in teams}
        entered = np.zeros(D)
        entered_t = np.zeros(T)
        nxt_sum = None
        for e in events:
            Fw += CH.TEAM_FORM_STEP * rng.standard_normal((n, T))
            Gw += CH.DRIVER_FORM_STEP * rng.standard_normal((n, D))
            sub = int(rng.integers(0, 2 ** 31 - 1))

            def off(inp):
                cols = np.array([di[d] for d in inp.drivers])
                tcols = np.array([ti[inp.team.get(d, d)] for d in inp.drivers])
                sd = np.array([float(inp.pace_sd.get(d, 0.0)) for d in inp.drivers])
                return sd * z[:, cols] + Fw[:, tcols] + Gw[:, cols]
            rs_ = _session_samples(e["race"], n, sub, False, off(e["race"]))
            ss_ = _session_samples(e["sprint"], n, sub, True, off(e["sprint"])) if e["sprint"] is not None else None
            team_of = {**(e["sprint"].team if e["sprint"] is not None else {}), **e["race"].team}
            wp = weekend_points(rs_, ss_, drivers, teams, team_of, e["known"], ovt, e["circuit"], pit, n)
            ros += wp["total"]
            ros_t += wp["team"]
            here = {d for d in team_of}
            for d in drivers:
                sched_d[d].append(round(float(wp["total"][:, di[d]].mean()), 2) if d in here else None)
                entered[di[d]] += d in here
            for t in teams:
                on = t in set(team_of.values())
                sched_t[t].append(round(float(wp["team"][:, ti[t]].mean()), 2) if on else None)
                entered_t[ti[t]] += on
            if nxt_sum is None:
                nxt_sum = summarise(wp, drivers, teams)
                for d in drivers:
                    if d not in here:
                        nxt_sum["drivers"].pop(d, None)
                for t in teams:
                    if t not in set(team_of.values()):
                        nxt_sum["teams"].pop(t, None)
        r10, r90 = _q(ros, 10), _q(ros, 90)
        t10, t90 = _q(ros_t, 10), _q(ros_t, 90)
        out_d = {d: {"team": nxt_team.get(d) or team_last.get(d), "next": (nxt_sum or {}).get("drivers", {}).get(d),
                     "ros": float(ros[:, i].mean()), "ros_p10": float(r10[i]), "ros_p90": float(r90[i]), "rounds_left": int(entered[i]),
                     "schedule": sched_d[d]} for d, i in di.items()}
        out_t = {t: {"next": (nxt_sum or {}).get("teams", {}).get(t), "ros": float(ros_t[:, j].mean()), "ros_p10": float(t10[j]),
                     "ros_p90": float(t90[j]), "rounds_left": int(entered_t[j]), "schedule": sched_t[t]} for t, j in ti.items()}
        ev0 = events[0]
        return {"ok": True, "year": int(year), "n": int(n), "next": {"round": ev0["round"], "name": ev0["name"], "sprint": ev0["sprint_weekend"],
                                                                     "quali_known": bool(ev0["known"].get("quali")),
                                                                     "sprint_known": bool(ev0["known"].get("sprint"))},
                "rounds": [[e["round"], e["name"], e["sprint_weekend"]] for e in events], "drivers": out_d, "teams": out_t,
                "lineup": nxt_team,
                "models": {"overtakes": ({"coef": [round(c, 3) for c in ovt.coef], "mean": round(ovt.mean, 2), "races": ovt.races}
                                         if ovt else None),
                           "pit": ({"races": pit.races, "field": round(pit.field, 2)} if pit else None)},
                "runtime_s": round(time.perf_counter() - t0, 1)}
    except Exception as exc:                                       # noqa: BLE001
        logger.exception("fantasy season projection failed")
        return {"ok": False, "reason": f"error: {exc}"}


# ---------------------------------------------------------------------------------------------- tiers, value, picks

def tiers(values: dict[str, float], k: int = 5) -> dict[str, int]:
    """Optimal 1-D partition (Fisher-Jenks: least within-tier sum of squares) into at most k tiers; 1 = best."""
    ids = sorted((d for d, v in values.items() if v is not None), key=lambda d: (-values[d], d))
    x = np.array([values[d] for d in ids], float)
    n = len(x)
    if n == 0:
        return {}
    k = max(1, min(k, n))
    c1 = np.concatenate([[0.0], np.cumsum(x)])
    c2 = np.concatenate([[0.0], np.cumsum(x * x)])

    def sse(i, j):                                                 # x[i..j] inclusive
        m = j - i + 1
        s = c1[j + 1] - c1[i]
        return (c2[j + 1] - c2[i]) - s * s / m
    INF = float("inf")
    dp = np.full((k + 1, n), INF)
    back = np.zeros((k + 1, n), int)
    for j in range(n):
        dp[1, j] = sse(0, j)
    for m in range(2, k + 1):
        for j in range(m - 1, n):
            best, arg = INF, m - 1
            for i in range(m - 1, j + 1):
                v = dp[m - 1, i - 1] + sse(i, j)
                if v < best:
                    best, arg = v, i
            dp[m, j], back[m, j] = best, arg
    out = {}
    j, m = n - 1, k
    while m >= 1:
        i = back[m, j] if m > 1 else 0
        for q in range(i, j + 1):
            out[ids[q]] = m
        j, m = i - 1, m - 1
    return out


def form_line(form: list[float], last: float | None) -> float | None:
    """Our price proxy: the season-to-date points per weekend blended with last season's, (n form + 3 last) / (n + 3)."""
    n = len(form)
    f = float(np.mean(form)) if n else None
    if f is None:
        return last
    if last is None:
        return f
    return (n * f + K_FORM * last) / (n + K_FORM)


def rank_of(values: dict[str, float | None], reverse: bool = True) -> dict[str, int]:
    ids = sorted((d for d, v in values.items() if v is not None), key=lambda d: ((-values[d]) if reverse else values[d], d))
    return {d: i + 1 for i, d in enumerate(ids)}


def _pc(p: float | None) -> str:
    return f"{100 * p:.0f}%" if p is not None else "-"


def reasons(row: dict, kind: str, names: dict | None = None) -> list[str]:
    """Short generated reasons for a pick, the most telling first for the kind of pick (top, value, differential,
    riser, fade, boost, team)."""
    names = names or {}
    c = []                                                         # (priority by kind, text)
    nx, p10, p90 = row.get("next"), row.get("p10"), row.get("p90")
    pr = {"top": ("proj", "front", "q3", "trend", "fl", "dnf"), "boost": ("floor", "front", "fl", "dnf"),
          "value": ("value", "value_ros", "proj", "trend", "luck", "q3"), "differential": ("rank", "ceiling", "value", "trend", "gain"),
          "riser": ("trend", "pace", "luck", "value_ros", "value"), "fade": ("value_neg", "luck_neg", "trend", "dnf"),
          "team": ("proj", "qb", "pit", "trend", "dnf"), "team_value": ("value", "value_ros", "proj", "trend")}.get(kind, ("proj",))
    is_team = kind in ("team", "team_value") or "q_bonus" in row
    his = "its" if is_team else "the driver's"
    team = (names.get(row.get("id")) or row.get("name") or "the car") if is_team else (names.get(row.get("team")) or row.get("team") or "the car")
    txt = {}
    if nx is not None:
        txt["proj"] = f"projects {nx:.1f} points next weekend (floor {p10:.0f}, ceiling {p90:.0f})" if p10 is not None else f"projects {nx:.1f} points"
        if p10 is not None:
            txt["floor"] = f"the highest expected score in the field; a floor of {p10:.0f} (10th percentile)"
        if p90 is not None:
            txt["ceiling"] = f"a ceiling of {p90:.0f} points (90th percentile)"
    if row.get("p_front") is not None and row["p_front"] >= 0.2:
        txt["front"] = f"starts from the front two rows in {_pc(row['p_front'])} of simulations"
    if row.get("p_q3") is not None and row["p_q3"] >= 0.3:
        txt["q3"] = f"reaches Q3 in {_pc(row['p_q3'])} of simulations"
    tr = row.get("car_trend")
    if tr is not None and abs(tr) >= 0.04:
        txt["trend"] = f"{team} race pace {'up' if tr > 0 else 'down'} {abs(tr):.2f}% of a lap over the last five rounds"
    if row.get("pace_rank") and row.get("form_rank") and row["form_rank"] - row["pace_rank"] >= 2:
        txt["pace"] = f"underlying pace ranks {row['pace_rank']} on the grid, {his} form only {row['form_rank']}"
    if row.get("p_fl") is not None and row["p_fl"] >= 0.1:
        txt["fl"] = f"takes the fastest lap in {_pc(row['p_fl'])} of simulations"
    if row.get("p_dnf") is not None and row["p_dnf"] >= 0.12:
        txt["dnf"] = f"retires in {_pc(row['p_dnf'])} of simulations"
    v = row.get("value")
    if v is not None and row.get("price") is not None:
        if v >= 1.5:
            txt["value"] = f"{v:+.1f} points against {his} form line of {row['price']:.1f} a weekend"
        if v <= -1.5:
            txt["value_neg"] = f"projects {abs(v):.1f} points below {his} form line of {row['price']:.1f} a weekend"
    vr = row.get("value_ros")
    if vr is not None and row.get("price") is not None and abs(vr) >= 1.0:
        txt["value_ros"] = f"{vr:+.1f} a weekend over the rest of the season against {his} form line"
    lk = row.get("luck")
    if lk is not None:
        if lk <= -12:
            txt["luck"] = f"has scored {abs(lk):.0f} championship points fewer than our race forecasts expected"
        if lk >= 12:
            txt["luck_neg"] = f"has scored {lk:.0f} championship points more than our race forecasts expected"
    if row.get("rank_next") and row.get("price_rank") and row["price_rank"] - row["rank_next"] >= 2:
        txt["rank"] = f"ranks {row['rank_next']} on our projection, only {row['price_rank']} on the form line"
    if row.get("gain") is not None and row["gain"] >= 1.5:
        txt["gain"] = f"gains {row['gain']:.1f} places a race in our simulations"
    if row.get("q_bonus") is not None:
        txt["qb"] = f"qualifying progression worth {row['q_bonus']:+.1f} a weekend"
    if row.get("pit") is not None and row["pit"] > 0:
        txt["pit"] = f"pit stops worth {row['pit']:.1f} a race on its stationary times"
    out = [txt[k] for k in pr if k in txt]
    return out[:3]


def _vrow(value: dict | None) -> tuple[dict, dict]:
    if not value or not value.get("ok", True):
        return {}, {}
    D = {r[0]: dict(zip(value.get("driver_cols") or [], r)) for r in value.get("drivers") or []}
    T = {r[0]: dict(zip(value.get("team_cols") or [], r)) for r in value.get("teams") or []}
    return D, T


DRIVER_COLS = ["id", "name", "team", "next", "p10", "p90", "p_q3", "p_front", "p_dnf", "p_fl", "exp_qpos", "gain", "ros", "ros_p10", "ros_p90",
               "ros_per", "rounds_left", "form", "form_n", "last", "price", "value", "value_ros", "tier", "tier_next", "pace_field", "pace_rank",
               "form_rank", "car_trend", "pace_tm", "luck"]
TEAM_COLS = ["id", "name", "next", "p10", "p90", "drivers", "q_bonus", "pit", "ros", "ros_p10", "ros_p90", "ros_per", "rounds_left", "form", "form_n",
             "last", "price", "value", "value_ros", "tier", "car", "car_trend"]


def fantasy_payload(year: int, proj: dict, actuals: dict[int, dict], last_actuals: dict[int, dict], value: dict | None = None,
                    dcat: dict | None = None, names: dict | None = None, bt: dict | None = None) -> dict:
    """data/<year>/fantasy.json (PAYLOADS.md "As built")."""
    names = names or {}
    tnames = {}
    D_cat = (dcat or {}).get("drivers") or {}
    for d, v in D_cat.items():
        names.setdefault(d, v.get("name") or d)
    vD, vT = _vrow(value)
    for t, v in vT.items():
        tnames[t] = v.get("name") or t
    done = sorted(r for r, aw in actuals.items() if aw.get("has_race"))
    hist_d: dict[str, list] = {}
    hist_t: dict[str, list] = {}
    for i, r in enumerate(done):
        aw = actuals[r]
        for d, v in aw["drivers"].items():
            if v.get("started") or v["c"].get("quali"):
                hist_d.setdefault(d, [None] * len(done))[i] = round(driver_total(v), 1)
        for t in aw["teams"]:
            hist_t.setdefault(t, [None] * len(done))[i] = round(team_total(aw, t, True, pit=True), 1)
    last_d: dict[str, list] = {}
    last_t: dict[str, list] = {}
    for r, aw in last_actuals.items():
        if not aw.get("has_race"):
            continue
        for d, v in aw["drivers"].items():
            if v.get("started"):
                last_d.setdefault(d, []).append(driver_total(v))
        for t in aw["teams"]:
            last_t.setdefault(t, []).append(team_total(aw, t, True, pit=True))
    ok = bool(proj.get("ok"))
    P = proj.get("drivers") or {}
    PT = proj.get("teams") or {}
    rows = {}
    ids = sorted(set(P) | (set(hist_d) if not ok else set()))
    lineup = proj.get("lineup") or {}
    for d in ids:
        p = P.get(d) or {}
        nx = p.get("next") or {}
        form = [x for x in hist_d.get(d, []) if x is not None]
        last = float(np.mean(last_d[d])) if last_d.get(d) else None
        price = form_line(form, last)
        team = p.get("team") or (D_cat.get(d) or {}).get("team")
        vr = vD.get(d) or {}
        trow = vT.get(team) or {}
        rl = p.get("rounds_left") or 0
        ros_per = p["ros"] / rl if rl and p.get("ros") is not None else None
        rows[d] = {"id": d, "name": names.get(d) or vr.get("name") or d, "team": team, "next": nx.get("mean"), "p10": nx.get("p10"),
                   "p90": nx.get("p90"), "p_q3": nx.get("p_q3"), "p_front": nx.get("p_front"), "p_dnf": nx.get("p_dnf"), "p_fl": nx.get("p_fl"),
                   "exp_qpos": nx.get("exp_qpos"), "gain": (nx.get("comp") or {}).get("race_gain"), "ros": p.get("ros"),
                   "ros_p10": p.get("ros_p10"), "ros_p90": p.get("ros_p90"), "ros_per": ros_per, "rounds_left": rl, "form": float(np.mean(form)) if form else None,
                   "form_n": len(form), "last": last, "price": price,
                   "value": (nx["mean"] - price) if nx.get("mean") is not None and price is not None else None,
                   "value_ros": (ros_per - price) if ros_per is not None and price is not None else None,
                   "pace_field": vr.get("pace_field"), "car_trend": trow.get("trend"), "pace_tm": vr.get("pace_tm"),
                   "luck": ((D_cat.get(d) or {}).get("values") or {}).get("points_v_expected"), "comp": nx.get("comp")}
    in_next = [d for d in rows if rows[d]["next"] is not None and (not lineup or d in lineup)]
    tr = tiers({d: rows[d]["ros_per"] for d in in_next})
    trn = tiers({d: rows[d]["next"] for d in in_next})
    pace_rank = rank_of({d: rows[d]["pace_field"] for d in in_next})
    form_rank = rank_of({d: rows[d]["price"] for d in in_next})
    next_rank = rank_of({d: rows[d]["next"] for d in in_next})
    for d, x in rows.items():
        x.update(tier=tr.get(d), tier_next=trn.get(d), pace_rank=pace_rank.get(d), form_rank=form_rank.get(d), rank_next=next_rank.get(d),
                 price_rank=form_rank.get(d))
    trows = {}
    for t in sorted(set(PT) | (set(hist_t) if not ok else set())):
        p = PT.get(t) or {}
        nx = p.get("next") or {}
        form = [x for x in hist_t.get(t, []) if x is not None]
        last = float(np.mean(last_t[t])) if last_t.get(t) else None
        price = form_line(form, last)
        rl = p.get("rounds_left") or 0
        ros_per = p["ros"] / rl if rl and p.get("ros") is not None else None
        vt = vT.get(t) or {}
        trows[t] = {"id": t, "name": tnames.get(t) or t, "next": nx.get("mean"), "p10": nx.get("p10"), "p90": nx.get("p90"),
                    "drivers": nx.get("drivers"), "q_bonus": nx.get("q_bonus"), "pit": nx.get("pit") if (proj.get("models") or {}).get("pit") else None,
                    "ros": p.get("ros"), "ros_p10": p.get("ros_p10"), "ros_p90": p.get("ros_p90"), "ros_per": ros_per, "rounds_left": rl,
                    "form": float(np.mean(form)) if form else None, "form_n": len(form), "last": last, "price": price,
                    "value": (nx["mean"] - price) if nx.get("mean") is not None and price is not None else None,
                    "value_ros": (ros_per - price) if ros_per is not None and price is not None else None,
                    "car": vt.get("car"), "car_trend": vt.get("trend")}
    ttr = tiers({t: trows[t]["ros_per"] for t in trows if trows[t]["next"] is not None}, k=4)
    for t, x in trows.items():
        x["tier"] = ttr.get(t)
    picks = suggest(rows, trows, tnames) if ok else {}
    nd = {"next": 2, "p10": 1, "p90": 1, "p_q3": 3, "p_front": 3, "p_dnf": 3, "p_fl": 3, "exp_qpos": 1, "gain": 2, "ros": 1, "ros_p10": 1,
          "ros_p90": 1, "ros_per": 2, "form": 2, "last": 2, "price": 2, "value": 2, "value_ros": 2, "pace_field": 3, "car_trend": 3, "pace_tm": 3,
          "luck": 1, "drivers": 2, "q_bonus": 2, "pit": 2, "car": 3}

    def pack(r, cols):
        return [(_r(r.get(c), nd[c]) if c in nd else r.get(c)) for c in cols]
    order = sorted(rows, key=lambda d: (-(rows[d]["next"] if rows[d]["next"] is not None else -99), d))
    torder = sorted(trows, key=lambda t: (-(trows[t]["next"] if trows[t]["next"] is not None else -99), t))
    rounds = proj.get("rounds") or []
    return {"ok": True, "year": int(year), "updated_at": _now(), "version": VERSION, "label": LABEL, "projection_ok": ok,
            "reason": None if ok else proj.get("reason"), "n": proj.get("n"), "next": proj.get("next"),
            "driver_cols": DRIVER_COLS, "drivers": [pack(rows[d], DRIVER_COLS) for d in order],
            "comp_cols": DCOMP, "comp": {d: [_r((rows[d].get("comp") or {}).get(k), 2) for k in DCOMP] for d in order if rows[d].get("comp")},
            "team_cols": TEAM_COLS, "teams": [pack(trows[t], TEAM_COLS) for t in torder],
            "schedule": {"rounds": rounds, "drivers": {d: (P.get(d) or {}).get("schedule") for d in order if (P.get(d) or {}).get("schedule")},
                         "teams": {t: (PT.get(t) or {}).get("schedule") for t in torder if (PT.get(t) or {}).get("schedule")}},
            "history": {"rounds": [[r, (canon.race(year, r) or {}).get("name")] for r in done], "drivers": hist_d, "teams": hist_t},
            "picks": picks, "models": proj.get("models"), "backtest": backtest_summary(bt) if bt else None,
            "scoring": [list(x) for x in SCORING], "excluded": [list(x) for x in EXCLUDED], "k_form": K_FORM,
            "names": {"drivers": {d: rows[d]["name"] for d in rows}, "teams": {t: trows[t]["name"] for t in trows}}}


def suggest(rows: dict[str, dict], trows: dict[str, dict], tnames: dict[str, str]) -> dict:
    """Our suggested picks with generated reasons (module docstring: value, differentials, risers and fades)."""
    live = {d: r for d, r in rows.items() if r.get("next") is not None}
    if not live:
        return {}

    def pick(d, kind, src=None):
        r = (src or rows)[d]
        return {"id": d, "proj": _r(r.get("next"), 1), "ros_per": _r(r.get("ros_per"), 1), "value": _r(r.get("value"), 1),
                "why": reasons(r, kind, tnames)}
    by_next = sorted(live, key=lambda d: (-live[d]["next"], d))
    top = by_next[:5]
    boost = by_next[0]
    n_live = len(live)
    scorer = set(by_next[:max(6, int(round(0.6 * n_live)))])     # value picks must be drivers who score: the top 60% by projection

    def v2(d):                                                     # next weekend and rest of season against the form line
        a, b = live[d].get("value"), live[d].get("value_ros")
        xs = [x for x in (a, b) if x is not None]
        return float(np.mean(xs)) if xs else None
    price_top = {d for d, r in live.items() if (r.get("price_rank") or 99) <= 5}
    value = [d for d in sorted(scorer, key=lambda d: (-(v2(d) if v2(d) is not None else -99), d))
             if d not in price_top and (v2(d) or 0) > 0][:4]
    diff = [d for d in sorted(scorer, key=lambda d: (-((live[d].get("price_rank") or 0) - (live[d].get("rank_next") or 99)), d))
            if (live[d].get("price_rank") or 0) > 6 and (live[d].get("price_rank") or 0) - (live[d].get("rank_next") or 99) >= 2][:4]
    if not diff:
        diff = sorted([d for d in scorer if (live[d].get("price_rank") or 0) > 6], key=lambda d: (-(live[d].get("p90") or -99), d))[:3]
    risers = [d for d in sorted(scorer, key=lambda d: (-(live[d].get("value_ros") if live[d].get("value_ros") is not None else -99), d))
              if ((live[d].get("car_trend") or 0) >= 0.04 or (live[d].get("form_rank") or 0) - (live[d].get("pace_rank") or 99) >= 2
                  or (live[d].get("luck") or 0) <= -12) and (live[d].get("value_ros") or 0) > 0][:4]
    fades = [d for d in sorted(scorer, key=lambda d: ((live[d].get("value_ros") if live[d].get("value_ros") is not None else 99), d))
             if (live[d].get("value_ros") or 0) < -1][:4]
    tl = {t: r for t, r in trows.items() if r.get("next") is not None}
    tby = sorted(tl, key=lambda t: (-tl[t]["next"], t))
    tscorer = set(tby[:max(4, int(round(0.6 * len(tby))))])
    tval = [t for t in sorted(tscorer, key=lambda t: (-(tl[t].get("value") if tl[t].get("value") is not None else -99), t))
            if (tl[t].get("value") or 0) > 0][:2]
    return {"top": [pick(d, "top") for d in top], "boost": pick(boost, "boost"), "value": [pick(d, "value") for d in value],
            "differentials": [pick(d, "differential") for d in diff], "risers": [pick(d, "riser") for d in risers],
            "fades": [pick(d, "fade") for d in fades], "constructors": [pick(t, "team", tl) for t in tby[:2]],
            "constructor_value": [pick(t, "team_value", tl) for t in tval]}


# ---------------------------------------------------------------------------------------------- command line

def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="F1 fantasy backtest (writes data/f1/cache/fantasy/backtest_preds.json and backtest.json)")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("backtest")
    b.add_argument("--from", dest="start", type=int, default=2012)
    b.add_argument("--to", dest="end", type=int, default=datetime.now().year)
    b.add_argument("--sims", type=int, default=BT_SIMS)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd != "backtest":
        ap.print_help()
        return 1
    bt = backtest(range(args.start, args.end + 1), n=args.sims, progress=True)
    p = cache_dir() / "backtest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bt, separators=(",", ":")), encoding="utf-8")
    for g, m in (bt.get("metrics") or {}).items():
        print(g)
        for name, v in m.items():
            print(f"  {name:6s} " + " ".join(f"{k}={v.get(k)}" for k in ("n", "mae", "bias", "spearman", "top5", "top_pick", "coverage_80") if k in v))
    print("pit", bt.get("pit"))
    print("races", bt.get("races"), "runtime", bt.get("runtime_s"), "s", "errors", len(bt.get("errors") or []), file=sys.stderr)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
