"""
Race simulation: a vectorised lap-by-lap Monte Carlo over n simulated races at once.

Inputs (``RaceInputs``)
-----------------------
``pace_mu[d]`` is driver d's expected race pace in seconds per lap relative to the field (negative = faster),
``pace_sd[d]`` its uncertainty, ``grid`` the starting slots (None before qualifying), ``dnf_hazard[d]`` the
per-lap retirement hazard (after lap 1), ``circuit`` the circuit profile from ``circuits.circuit_profile``.

``race_inputs(year, round, before_quali)`` uses only data strictly before the race (plus the race's own grid
post-qualifying). Pace is in % of lap until the inputs are assembled, then converted to s/lap with the circuit's
reference lap (its latest race's median green lap). The results-only estimator below is always computed; when
``decomposition.season_effects`` is importable, its race pace through the latest completed round (latest car
effect + driver effect; ``se = sqrt(se_car^2 + se_drv^2)``) is blended in: ``mu = w * mu_A + (1 - w) * mu_results``,
``sd^2 = w * sd_A^2 + (1 - w) * sd_results^2`` with ``w = n / (n + A_BLEND_K)``, n = rounds with observed race pace.
Before qualifying the grid is sampled from ``qualifying.quali_model``'s grid distribution (``PRE_GRID``).
Constants marked as fitted are read from ``fitted/race_params.json`` (walk-forward, ``scripts/f1_tune.py``).

Results-only pace estimator
---------------------------
Each earlier result becomes a normal score ``z = Phi^-1((rank - 0.5) / N)`` (race: rank among classified
finishers, N = starters; qualifying: position, N = entries; sprint as race). Observation weight
``w = kind * season * 0.5 ** (races_ago / 6)`` with kind = 1.0 race, 0.8 qualifying, 0.5 sprint, and
season = 1 (current), 0.35 (previous), 0.12 (two back) and races_ago counted across seasons; after a regulation reset
(2014, 2017, 2022, 2026) the previous seasons count 0.08 / 0.03. Driver score shrinks to the team's score:
``z_d = (sum w z + 2 * z_team) / (sum w + 2)``, ``z_team = (sum_team w z + 1 * 0.5) / (sum_team w + 1)``
(0.5 = a new team's prior). Pace ``mu_d = PACE_PER_Z_PCT * z_d`` (% of lap),
``sd_d = PACE_PER_Z_PCT * 0.7 / sqrt(sum w + 2)``. The results-only grid uses the same estimator on
qualifying results only, sampled per simulation as ``z_q + 0.55 * eps`` and ranked.
Retirement: mechanical by team ``p_m = (sum w m + 8 g_m) / (sum w starts + 8)``, incident by driver
``p_i = (sum w i + 12 g_i) / (sum w starts + 12)`` (g = era/circuit rates from the circuit profile, unknown
statuses split by the mechanical share, lap-1 retirements excluded), per lap ``h = -ln(1 - p_m - p_i) / laps``.

The simulation (per simulated race, all n at once)
--------------------------------------------------
* Per-race pace ``x_d = mu_d + sd_d * e1 + c_team * e2 + c_drv * e3 (+ season offsets in the championship)``
  with car day-to-day sd c_team = 0.16 s/lap and driver day sd c_drv = 0.10 s/lap.
* Lap 1: ``score = slot + m[slot] + LAP1_SD_MULT * s[slot] * k_c * e + B * Exp(LAP1_BAD_SCALE) - 1.0 * (x_d - median x)``
  ranked to the lap-1 order (m, s = the circuit's first-lap position change mean / sd by grid slot, k_c its sd
  scale, B = 1 with probability LAP1_BAD_P); cars leave the lap 0.65 s apart. Lap-1 retirement with probability ``q[slot]`` (circuit's lap-1 incident rate by slot).
* Lap time ``t = x_d + deg * age + 0.06 * (L - lap) + 0.35 * e`` (s/lap; deg = 0.06 s per lap of tyre age unless A
  supplies one, fuel term 0.06 s per lap of fuel remaining is common to all cars).
* Strategy: the race's stops ``k = 1 + Binomial(2, (m - 1) / 2)`` (mean = the circuit's typical stops m) drawn once
  per simulated race, each car off it by one stop with probability STOP_DEV_P; stop j on lap
  ``L * j / (k + 1) + N(0, 0.07 L)``; cost = pit loss + N(0, 0.6) (+4-8 s slow stop with p = 0.03). Under SC
  the cost is 0.5 x pit loss, under VSC 0.65 x, and planned stops within the next 6 laps are brought forward.
  Sprints: no stops. ``RaceInputs.stops`` can fix a driver's number of stops.
* Overtaking: cars are processed front to back; a car that would finish the lap within 0.4 s of (or ahead of)
  the nearest non-pitting car in front must pass it: ``P(pass) = sigmoid((dpace - thr) / 0.25)`` where dpace is
  the underlying pace difference (no lap noise) and thr the circuit's overtake threshold; a failed pass leaves
  it 0.4 s behind. (Approximation: a car is checked only against the nearest car ahead, so a much faster car
  can clear two cars in one lap.)
* SC / VSC: each green lap starts an SC with probability sc_rate (x3 on lap 1) lasting 3-5 laps, else a VSC with
  probability vsc_rate lasting 2-3 laps. An SC resets the gaps to 0.8 s per position; neither allows passing.
* Retirement after lap 1 with per-lap hazard h_d (the retirement lap is drawn once as ``1 + Geometric(1 - e^-h)``).
  A car is classified if it completed 90 % of the laps; DNF = not classified.
* Wet (all sims if ``wet``, else with probability ``p_wet``): day sd x1.6, lap noise x2, SC/VSC hazard x2.5,
  retirement hazard x1.8, lap-1 spread x1.3.
* Points by the season's table to classified cars; the fastest lap goes to the running car with the best
  ``x_d + N(0, 0.3)`` and earns the bonus point (seasons that had it) only if that car finished in the top 10.

Runtime: 20,000 sims of a 22-car 57-lap race take ~2.5 s (numpy; Python loops only over laps and grid positions).
This is a full lap-by-lap model, not a stint-level approximation.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

from oddsmarkets.f1.models import circuits as _circ

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------------------------- constants
# Every pace quantity is converted between % of lap and s/lap with the circuit's reference lap (the
# circuit profile's ``ref_lap_s``: its latest race's median green lap). Time-based noise constants below are
# stated for a 90 s lap (REF_LAP_S) and scale with the circuit's lap.
REF_LAP_S = 90.0          # default reference lap (s) when a circuit has no lap times; the scale of the s-constants
PACE_PER_Z_PCT = 0.444    # % of lap per normal-score unit (0.40 s at 90 s); refitted, see FITTED_PATH
Z_OBS_SD = 0.7
QUALI_NOISE_Z = 0.55
NEW_ENTRY_Z = 0.5
K_TEAM, K_NEW, K_MECH, K_INC = 2.0, 1.0, 8.0, 12.0
HALF_LIFE_RACES = 6.0
KIND_W = {"race": 1.0, "quali": 0.8, "sprint": 0.5}
REG_RESET = {2014, 2017, 2022, 2026}
SEASON_W = {0: 1.0, 1: 0.35, 2: 0.12}
SEASON_W_RESET = {0: 1.0, 1: 0.08, 2: 0.03}

DAY_TEAM_SD, DAY_DRIVER_SD, LAP_SD = 0.16, 0.10, 0.35
DEG_DEFAULT, FUEL_PER_LAP = 0.06, 0.06
LAP1_PACE_GAIN, LAP1_SPACING = 1.0, 0.65
# Lap 1: a Gaussian core (the circuit profile's per-slot spread x LAP1_SD_MULT) plus a tail: with LAP1_BAD_P a
# car loses Exponential(LAP1_BAD_SCALE) places (a bad start, contact, a trip across the grass). The profile's
# spread is the sd of observed moves, tail included, and ranking every car's noisy score moves a car by its own
# noise and its neighbours', so the plain Gaussian at full spread let the pole-sitter lead after lap 1 in 34%
# of simulations against 72% observed (2014-2025). Fitted to the observed lap-1 moves by grid slot (keep the
# place, lose 3+, gain 2+): core 0.4, tail 10% x 8 places (pole keeps the lead 56%).
LAP1_SD_MULT = 0.4
LAP1_BAD_P, LAP1_BAD_SCALE = 0.10, 8.0
HOLD_GAP, PASS_MARGIN = 0.4, 0.1
SC_GAP, SC_LAPS, VSC_LAPS = 0.8, (3, 5), (2, 3)
# PIT_WINDOW: a planned stop within this many laps is taken under a neutralisation. With the race-level strategy
# below, 6 laps makes 32% of cars pit under a safety car (spread across SCs: sd 0.29) against 34% (sd 0.29)
# in the 2023-2025 OpenF1 race-control and pit records.
SC_PIT_FACTOR, VSC_PIT_FACTOR, PIT_WINDOW = 0.5, 0.65, 6
PIT_SD, SLOW_STOP_P, SLOW_STOP = 0.6, 0.03, (4.0, 8.0)
LAP1_SC_MULT = 3.0
WET = {"day": 1.6, "lap": 2.0, "sc": 2.5, "dnf": 1.8, "lap1": 1.3}
CLASSIFIED_SHARE = 0.9
FL_NOISE = 0.3
SC_RATE_MULT = 1.0        # multiplies the circuit's SC/VSC hazards (tuning)
# Strategy: the race's number of stops is drawn once per simulated race and each car departs from it by one
# stop with this probability. 2011-2025: 72.5% of finishers ran the race's modal count and the winner and
# runner-up differed in 19% of races; independent draws per car (None) made 58% of pairs differ.
STOP_DEV_P: float | None = 0.1
A_PACE_SCALE = 1.0        # multiplies the decomposition's pace deviations before the blend
DNF_MULT = 1.0            # multiplies the retirement hazards (tuning)
A_BLEND_K = 4.0           # decomposition weight = rounds / (rounds + A_BLEND_K)
A_CARRY_ROUNDS = 0.0      # round 1: last season's final decomposition counts as this many rounds (0 = not used)
PRE_GRID = "quali_model"  # pre-qualifying grid: "quali_model" (decomposition), "results" or "blend"
PRE_GRID_MIX = 0.5        # "blend": weight of the quali model's expected slot against the results score
# After qualifying: this round's qualifying pace (decomposition.quali_pace over Q1-Q3, % of lap, field-centred)
# pulls each driver's race pace toward it, mu = (1 - w) mu + w (q + offset), and the pace sd shrinks by
# QUALI_PACE_SD_MULT (the session has told us much of what the prior was unsure about). Walk-forward on
# 2014-2022 (docs/research/f1_edge.md): winner log-loss after qualifying 1.383 -> 1.323 there, 1.199 -> 1.108
# on 2023-2026. 0 switches it off.
QUALI_PACE_W = 0.0
QUALI_PACE_SD_MULT = 1.0
# Post-qualifying win temperature (October 2026, docs/research/f1_edge.md "Model-improvement program"): the
# published post-qualifying win probabilities become p^T renormalised, T > 1 sharpening a timid favourite.
# ``WIN_TEMP_POST`` holds {"YYYY_R": T} with T fitted only on the races before that one (walk-forward, every Grand
# Prix from 2014, scripts/f1_tune.py wintemp) and "latest" (all races to date) for rounds not in the table.
# Empty = off. Only p_win changes: positions, podium, points and the championship are the simulator's own.
WIN_TEMP_POST: dict = {}
# Post-qualifying strength scale (22 October 2026; docs/research/f1_edge.md 9.6; tested and OFF: no pre-registered
# memory rule beat s = 1 on 2014-2022, so the fitted file has no table). After this round's
# qualifying-pace blend, the field-centred pace means of a Grand Prix with its grid known are multiplied by s,
# mu_d = mean + s (mu_d - mean). How strongly pace gaps decide a race differs by season (a dominant car's margin is
# not expressed by rank-based scores), so s is learned walk-forward from earlier races (scripts/f1_tune.py spread):
# ``PACE_SPREAD_POST`` holds {"YYYY_R": s} fitted only on races before that one, plus "latest". Empty = off (s = 1).
# Pace sd, pre-qualifying forecasts and sprints are unchanged; every simulated output follows from the scaled pace.
PACE_SPREAD_POST: dict = {}

# Constants fitted by the walk-forward backtest (scripts/f1_tune.py) override the defaults above.
FITTED_PATH = Path(__file__).resolve().parent / "fitted" / "race_params.json"
FITTED: dict[str, Any] = {}


def _load_fitted() -> None:
    global FITTED
    try:
        FITTED = json.loads(FITTED_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        FITTED = {}
    for k, v in (FITTED.get("params") or {}).items():
        if k in globals() and not callable(globals()[k]):
            globals()[k] = tuple(v) if isinstance(globals()[k], tuple) else v


def set_params(**kw: Any) -> dict[str, Any]:
    """Override module constants (tuning and tests); returns the previous values."""
    old = {}
    for k, v in kw.items():
        if k not in globals():
            raise KeyError(k)
        old[k] = globals()[k]
        globals()[k] = v
    return old


def __getattr__(name: str):                  # PACE_PER_Z (s/lap at the default lap) kept for older callers
    if name == "PACE_PER_Z":
        return PACE_PER_Z_PCT * REF_LAP_S / 100.0
    raise AttributeError(name)

DEFAULT_CIRCUIT = {"laps": 57, "sprint_laps": 19, "pit_loss_s": 22.0, "sc_rate_per_lap": 0.011, "vsc_rate_per_lap": 0.006,
                   "overtake_threshold_s": 0.95, "overtake_scale_s": 0.25, "overtake_difficulty": 0.5, "typical_stops": 1.6, "p_wet": 0.0,
                   "lap1_incident_by_grid": None, "lap1_mean_by_grid": None, "lap1_sd_by_grid": None, "lap1_sd_scale": 1.0}
_load_fitted()


# ----------------------------------------------------------------------------------------------- points

def points_system(year: int) -> dict:
    """The season's points tables (rule-based, then checked against the data where possible)."""
    y = int(year)
    if y >= 2010:
        race = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]
    elif y >= 2003:
        race = [10, 8, 6, 5, 4, 3, 2, 1]
    elif y >= 1991:
        race = [10, 6, 4, 3, 2, 1]
    else:
        race = [9, 6, 4, 3, 2, 1]
    sprint = [3, 2, 1] if y == 2021 else ([8, 7, 6, 5, 4, 3, 2, 1] if y >= 2022 else [])
    fl = 2019 <= y <= 2024
    data_fl = fastest_lap_point_in_data(y)
    if data_fl is not None:
        fl = data_fl
    return {"race": race, "sprint": sprint, "fastest_lap": fl, "fastest_lap_top10": True, "source_fl": "data" if data_fl is not None else "rule"}


def fastest_lap_point_in_data(year: int) -> bool | None:
    """True/False when the season's results show (or rule out) a fastest-lap bonus point; None if undecidable."""
    try:
        st = _circ.load_store(year)
    except Exception:
        return None
    y = int(year)
    table = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1] if y >= 2010 else ([10, 8, 6, 5, 4, 3, 2, 1] if y >= 2003 else [10, 6, 4, 3, 2, 1])
    yes = no = 0
    for race in (st.get("races") or {}).values():
        for r in race.get("results") or []:
            try:
                pos, fr, pts = int(r.get("position") or 0), int(r.get("fastest_rank") or 0), float(r.get("points") or 0)
            except (TypeError, ValueError):
                continue
            if fr != 1 or not (1 <= pos <= 10) or pos > len(table):
                continue
            base = table[pos - 1]
            if abs(pts - base - 1) < 1e-6 or abs(pts - base / 2 - 0.5) < 1e-6:
                yes += 1
            elif abs(pts - base) < 1e-6 or abs(pts - base / 2) < 1e-6 or abs(pts - 2 * base) < 1e-6:
                no += 1
    if yes >= 2 and yes > no:
        return True
    if no >= 3 and yes == 0:
        return False
    return None


# ----------------------------------------------------------------------------------------------- inputs

@dataclass
class RaceInputs:
    year: int
    round: int
    drivers: list[str]
    team: dict[str, str]
    pace_mu: dict[str, float]
    pace_sd: dict[str, float]
    grid: dict[str, int] | None
    dnf_hazard: dict[str, float]
    circuit: dict
    wet: bool = False
    p_wet: float | None = None
    grid_strength: dict[str, float] | None = None     # quali z score (lower = faster), used to sample a grid
    grid_dist: dict[str, list[float]] | None = None   # A's p(P1..Pn) per driver, preferred over grid_strength
    deg: dict[str, float] | None = None               # s per lap of tyre age
    stops: dict[str, int] | None = None               # fixed number of stops per driver (strategy override)
    session: str = "race"
    source: str = "results"
    ref_lap_s: float | None = None                    # circuit reference lap (s); None = the circuit's, else REF_LAP_S
    meta: dict[str, Any] = field(default_factory=dict)


def _opt(modname: str):
    """Import an optional sibling module (another builder's) or return None."""
    try:
        if importlib.util.find_spec(modname) is None:
            return None
        return importlib.import_module(modname)
    except Exception as exc:
        logger.debug("optional module %s unavailable: %s", modname, exc)
        return None


def _optional_fn(name: str, modules: tuple[str, ...]):
    for m in modules:
        mod = _opt(m)
        fn = getattr(mod, name, None) if mod else None
        if callable(fn):
            return fn
    return None


_A_MODULES = ("oddsmarkets.f1.models.decomposition", "oddsmarkets.f1.models.laptime", "oddsmarkets.f1.models.qualifying")


def _ordered_races(upto: tuple[int, int], seasons_back: int = 2) -> list[tuple[int, int, dict]]:
    """(year, round, race) for every race with results strictly before ``upto``, oldest first."""
    y0, r0 = int(upto[0]), int(upto[1])
    out = []
    for y in range(y0 - seasons_back, y0 + 1):
        st = _circ.load_store(y)
        for k, race in (st.get("races") or {}).items():
            try:
                rk = int(k)
            except ValueError:
                continue
            if (y, rk) < (y0, r0) and (race.get("results") or race.get("qualifying")):
                out.append((y, rk, race))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def _z(rank: int, n: int) -> float:
    return float(norm.ppf((rank - 0.5) / max(n, 1)))


def _obs_weight(seasons_back: int, races_ago: int, reset: bool) -> float:
    sw = SEASON_W_RESET if reset else SEASON_W
    return float(sw.get(int(seasons_back), 0.0)) * 0.5 ** (races_ago / HALF_LIFE_RACES)


def results_strength(year: int, rnd: int) -> dict:
    """Normal-score observations for every driver/team from results strictly before (year, rnd).

    ``obs`` rows are ``(driver, team, kind, z, w, seasons_back, races_ago)``; ``w`` uses the current weights and
    ``_fallback_pace`` recomputes it from the last two fields, so re-tuned weights apply to a cached ``obs``.
    """
    races = _ordered_races((year, rnd))
    reset = int(year) in REG_RESET
    n = len(races)
    obs: list[tuple] = []
    starts: dict[str, list] = {}                                  # driver -> [(team, w, kind, lap0)]
    for i, (y, rk, race) in enumerate(races):
        ago = n - 1 - i
        sb = int(year) - y
        w0 = _obs_weight(sb, ago, reset)
        if w0 <= 0:
            continue
        for kind, rows in (("race", race.get("results") or []), ("sprint", race.get("sprint") or [])):
            if not rows:
                continue
            kinds = [_circ.status_kind(r) for r in rows]
            started = [r for r, k in zip(rows, kinds) if k != "dns"]
            fin = sorted((r for r, k in zip(rows, kinds) if k == "finished"), key=lambda r: int(r.get("position") or 99))
            N = len(started)
            for rank, r in enumerate(fin, 1):
                obs.append((r["driver"], r.get("constructor"), kind, _z(rank, N), KIND_W[kind] * w0, sb, ago))
            if kind == "race":
                for r, k in zip(rows, kinds):
                    if k == "dns":
                        continue
                    lap0 = int(r.get("laps") or 0) == 0 and k.startswith("dnf")
                    starts.setdefault(r["driver"], []).append((r.get("constructor"), w0, k, lap0))
        q = race.get("qualifying") or []
        qs = sorted((r for r in q if r.get("position")), key=lambda r: int(r["position"]))
        for r in qs:
            obs.append((r["driver"], r.get("constructor"), "quali", _z(int(r["position"]), len(qs)), KIND_W["quali"] * w0, sb, ago))
    return {"obs": obs, "starts": starts, "n_races": n, "reset": reset}


def _entry(year: int, rnd: int) -> tuple[list[str], dict[str, str]]:
    st = _circ.load_store(year)
    race = (st.get("races") or {}).get(str(rnd)) or {}
    rows = race.get("qualifying") or race.get("results") or []
    if rows:
        drivers = []
        team = {}
        for r in rows:
            if r.get("driver") and r["driver"] not in team:
                drivers.append(r["driver"])
                team[r["driver"]] = r.get("constructor") or r["driver"]
        for r in race.get("results") or []:           # anyone missing from qualifying (e.g. no time set)
            if r.get("driver") and r["driver"] not in team:
                drivers.append(r["driver"])
                team[r["driver"]] = r.get("constructor") or r["driver"]
        return drivers, team
    # future race: the latest completed round's entry
    for y in (year, year - 1):
        s = _circ.load_store(y)
        rk = sorted((int(k) for k, v in (s.get("races") or {}).items() if v.get("results") and (y < year or int(k) < rnd)), reverse=True)
        if rk:
            race = s["races"][str(rk[0])]
            drivers, team = [], {}
            for r in race.get("results") or []:
                if r.get("driver") and r["driver"] not in team:
                    drivers.append(r["driver"])
                    team[r["driver"]] = r.get("constructor") or r["driver"]
            return drivers, team
    return [], {}


def _fallback_pace(year: int, rnd: int, drivers: list[str], team: dict[str, str], rs: dict | None = None) -> dict:
    """Results-only pace in % of lap (``mu_pct``, ``sd_pct``) and the qualifying score ``grid_z``."""
    rs = rs if rs is not None else results_strength(year, rnd)
    reset = bool(rs.get("reset"))
    cur_team_obs: dict[str, list[tuple[float, float]]] = {}
    drv_race: dict[str, list[tuple[float, float]]] = {}
    drv_q: dict[str, list[tuple[float, float]]] = {}
    for row in rs["obs"]:
        d, t, kind, z = row[0], row[1], row[2], row[3]
        w = KIND_W[kind] * _obs_weight(row[5], row[6], reset) if len(row) > 6 else row[4]
        if w <= 0:
            continue
        (drv_q if kind == "quali" else drv_race).setdefault(d, []).append((z, w))
        if kind != "quali":
            cur_team_obs.setdefault(t, []).append((z, w))
    team_z = {}
    for t in set(team.values()):
        xs = cur_team_obs.get(t, [])
        sw = sum(w for _, w in xs)
        team_z[t] = (sum(z * w for z, w in xs) + K_NEW * NEW_ENTRY_Z) / (sw + K_NEW)
    mu, sd, gz = {}, {}, {}
    for d in drivers:
        t = team.get(d)
        # race pace uses race/sprint finishes and qualifying (one-lap pace is informative about race pace)
        xs = drv_race.get(d, []) + drv_q.get(d, [])
        sw = sum(w for _, w in xs)
        z = (sum(z * w for z, w in xs) + K_TEAM * team_z.get(t, NEW_ENTRY_Z)) / (sw + K_TEAM)
        mu[d] = PACE_PER_Z_PCT * z
        sd[d] = PACE_PER_Z_PCT * Z_OBS_SD / math.sqrt(sw + K_TEAM)
        qs = drv_q.get(d, [])
        qw = sum(w for _, w in qs)
        gz[d] = (sum(z * w for z, w in qs) + K_TEAM * z) / (qw + K_TEAM)
    return {"mu_pct": mu, "sd_pct": sd, "grid_z": gz, "rs": rs}


def _dnf_hazards(rs: dict, drivers: list[str], team: dict[str, str], circuit: dict, laps: int) -> tuple[dict, dict]:
    g = circuit.get("global") or {}
    gm = float(g.get("dnf_mech_per_race", circuit.get("dnf_mech_per_race", 0.04)))
    gi_all = float(g.get("dnf_incident_per_race", circuit.get("dnf_incident_per_race", 0.035)))
    l1 = circuit.get("lap1_incident_by_grid") or [0.012]
    gi = max(0.005, gi_all - float(np.mean(l1)))
    share = float(circuit.get("mech_share", 0.53))
    cm = float(circuit.get("dnf_mech_per_race", gm)) / gm if gm else 1.0
    ci = float(circuit.get("dnf_incident_per_race", gi_all)) / gi_all if gi_all else 1.0
    t_starts: dict[str, float] = {}
    t_mech: dict[str, float] = {}
    d_starts: dict[str, float] = {}
    d_inc: dict[str, float] = {}
    for d, rows in rs["starts"].items():
        for t, w, kind, lap0 in rows:
            t_starts[t] = t_starts.get(t, 0) + w
            d_starts[d] = d_starts.get(d, 0) + w
            if lap0:
                continue
            m = 1.0 if kind == "dnf_mech" else (share if kind == "dnf_unknown" else 0.0)
            i = 1.0 if kind == "dnf_incident" else ((1 - share) if kind == "dnf_unknown" else 0.0)
            t_mech[t] = t_mech.get(t, 0) + w * m
            d_inc[d] = d_inc.get(d, 0) + w * i
    haz, split = {}, {}
    for d in drivers:
        t = team.get(d)
        pm = (t_mech.get(t, 0) + K_MECH * gm) / (t_starts.get(t, 0) + K_MECH) * cm
        pi = (d_inc.get(d, 0) + K_INC * gi) / (d_starts.get(d, 0) + K_INC) * ci
        p = min(0.6, pm + pi)
        haz[d] = -math.log(1 - p) / max(laps, 1)
        split[d] = {"mech": round(pm, 4), "incident": round(pi, 4)}
    return haz, split


_A_MEMO: dict[tuple, dict] = {}


def _season_effects_memo(fn, year: int, upto: int | None) -> dict:
    p = _circ._store.season_path(year)
    key = (int(year), upto, p.stat().st_mtime if p.exists() else 0)
    eff = _A_MEMO.get(key)
    if eff is None:
        eff = fn(year, upto_round=upto) if upto is not None else fn(year)
        if len(_A_MEMO) > 64:
            _A_MEMO.clear()
        _A_MEMO[key] = eff
    return eff


def _a_pace(year: int, rnd: int, drivers: list[str], team: dict[str, str], carry_only: bool = False) -> dict | None:
    """The decomposition's race pace in % of lap: the latest car effect plus the driver effect, fitted through the
    latest completed round before ``rnd``; ``se = sqrt(se_car^2 + se_drv^2)``. With ``carry_only``: at round 1
    (no completed round this season) of a season that is not a regulation reset, the previous season's final
    effects (``carry`` True; ``inputs_from_components`` counts them as ``A_CARRY_ROUNDS`` rounds)."""
    fn = _optional_fn("season_effects", _A_MODULES)
    if fn is None:
        return None
    try:
        st = _circ.load_store(year)
        done = [int(k) for k, v in (st.get("races") or {}).items() if str(k).isdigit() and v.get("results") and int(k) < rnd]
        car = drv = {}
        n_rounds = 0.0
        carry = False
        if done and not carry_only:
            eff = _season_effects_memo(fn, year, max(done))      # future rounds share the latest completed round's fit
            car, drv = eff.get("car") or {}, eff.get("driver") or {}
            n_rounds = float(len({int(e.get("round", 0)) for c in car.values() for e in c if e.get("observed", True) and int(e.get("round", 0)) < rnd}))
        if carry_only and not done and int(year) not in REG_RESET:
            eff = _season_effects_memo(fn, year - 1, None)
            car, drv = eff.get("car") or {}, eff.get("driver") or {}
            n_rounds, carry = 0.0, True
        if not car:
            return None
        mu, sd = {}, {}
        for d in drivers:
            c = [e for e in (car.get(team.get(d)) or []) if carry or int(e.get("round", 0)) < rnd]
            if not c:
                continue
            ce = c[-1]
            de = drv.get(d) or {}
            m = float(ce.get("effect", 0.0)) + float(de.get("effect", 0.0))
            s = math.sqrt(float(ce.get("se", 0.2)) ** 2 + float(de.get("se", 0.1)) ** 2)
            if not (math.isfinite(m) and abs(m) < 12 and math.isfinite(s)):
                return None
            mu[d], sd[d] = m, s
        if not mu or len(mu) < 0.8 * len(drivers):
            return None
        worst = max(mu.values()) + 0.35
        for d in drivers:
            mu.setdefault(d, worst)
            sd.setdefault(d, 0.45)
        return {"mu_pct": mu, "sd_pct": sd, "n_rounds": n_rounds, "carry": carry}
    except Exception as exc:
        logger.info("A's season_effects unavailable for %s/%s: %s", year, rnd, exc)
        return None


def _a_grid_dist(year: int, rnd: int, drivers: list[str]) -> dict | None:
    fn = _optional_fn("quali_model", _A_MODULES)
    if fn is None:
        return None
    try:
        q = fn(year, rnd, n_sims=4000) or {}
        out = {d: list(map(float, (q.get("drivers") or {}).get(d, {}).get("grid_dist") or [])) for d in drivers}
        if sum(1 for v in out.values() if v) < 0.8 * len(drivers):
            return None
        return out
    except Exception as exc:
        logger.info("A's quali_model unavailable for %s/%s: %s", year, rnd, exc)
        return None


def actual_grid(year: int, rnd: int, session: str = "race") -> dict[str, int] | None:
    race = (_circ.load_store(year).get("races") or {}).get(str(rnd)) or {}
    rows = race.get("sprint") if session == "sprint" else race.get("results")
    if rows:
        g = {r["driver"]: int(r.get("grid") or 0) for r in rows if _circ.status_kind(r) != "dns"}
        if any(v > 0 for v in g.values()):
            return g
    if session == "race" and race.get("qualifying"):
        return {r["driver"]: int(r.get("position") or 0) for r in race["qualifying"]}
    return None


def round_quali_pace(year: int, rnd: int, drivers: list[str]) -> dict[str, float] | None:
    """This round's qualifying pace per driver (% of lap, field-centred; ``decomposition.quali_pace``), or None."""
    fn = _optional_fn("quali_pace", ("oddsmarkets.f1.models.decomposition",))
    race = (_circ.load_store(year).get("races") or {}).get(str(rnd)) or {}
    if fn is None or not race.get("qualifying"):
        return None
    try:
        qp = fn(race["qualifying"]) or {}
    except Exception as exc:
        logger.info("quali_pace unavailable for %s/%s: %s", year, rnd, exc)
        return None
    out = {d: float(v["pace"]) for d, v in qp.items()
           if d in drivers and v.get("pace") is not None and math.isfinite(float(v["pace"]))}
    return out or None


def _blend_toward(mu: dict[str, float], x: dict[str, float], w: float) -> dict[str, float]:
    """``(1 - w) mu + w (x + off)`` for drivers in x, off re-centring x on mu over those drivers."""
    common = [d for d in mu if d in x]
    if not common or w <= 0:
        return dict(mu)
    off = float(np.mean([mu[d] for d in common])) - float(np.mean([x[d] for d in common]))
    return {d: ((1 - w) * v + w * (x[d] + off)) if d in x else v for d, v in mu.items()}


def race_components(year: int, round: int, before_quali: bool = True, session: str = "race", use_a: bool = True) -> dict:
    """Everything ``race_inputs`` needs that does not depend on the tunable constants (cacheable, picklable):
    entry list, circuit profile and reference lap, raw results observations, the decomposition's pace in % of
    lap, the actual grid (after qualifying) or the qualifying model's grid distribution (before)."""
    year, rnd = int(year), int(round)
    st = _circ.load_store(year)
    race = (st.get("races") or {}).get(str(rnd)) or {}
    cid = (race.get("circuit") or {}).get("id")
    circuit = _circ.circuit_profile(cid, before=(year, rnd))
    if circuit.get("samples", {}).get("races", 0) == 0:
        lp = _circ.scheduled_laps(year, rnd)
        if lp:
            circuit = {**circuit, "laps": lp}
    ref = float(circuit.get("ref_lap_s") or REF_LAP_S)
    drivers, team = _entry(year, rnd)
    rs = results_strength(year, rnd)
    a = _a_pace(year, rnd, drivers, team) if use_a else None
    a_carry = _a_pace(year, rnd, drivers, team, carry_only=True) if (use_a and a is None) else None
    grid = None if before_quali else actual_grid(year, rnd, session)
    if grid is not None:
        grid = {d: grid.get(d, 0) for d in drivers}
    qpace = round_quali_pace(year, rnd, drivers) if (grid is not None and session == "race") else None
    gd = _a_grid_dist(year, rnd, drivers) if (before_quali and use_a and session == "race") else None
    return {"year": year, "round": rnd, "session": session, "before_quali": before_quali, "drivers": drivers, "team": team,
            "circuit": circuit, "ref_lap_s": ref, "rs": rs, "a": a, "a_carry": a_carry, "grid": grid, "grid_dist": gd,
            "quali_pace": qpace,
            "meta": {"circuit_id": cid, "name": race.get("name")}}


def inputs_from_components(comp: dict) -> RaceInputs:
    """``RaceInputs`` from ``race_components`` under the module's current constants.

    Pace: the results-only estimate and the decomposition (when present) in % of lap, blended with weight
    ``w_A = n / (n + A_BLEND_K)`` (n = rounds the decomposition has observed race pace for), then converted to
    s/lap with the circuit's reference lap."""
    year, rnd, session = comp["year"], comp["round"], comp["session"]
    drivers, team, circuit = comp["drivers"], comp["team"], comp["circuit"]
    k = comp["ref_lap_s"] / 100.0
    fb = _fallback_pace(year, rnd, drivers, team, comp["rs"])
    a = comp.get("a")
    if not a and comp.get("a_carry") and A_CARRY_ROUNDS > 0:
        a = {**comp["a_carry"], "n_rounds": float(A_CARRY_ROUNDS)}
    if a and a["n_rounds"] > 0:
        wa = a["n_rounds"] / (a["n_rounds"] + A_BLEND_K) if a["n_rounds"] + A_BLEND_K > 0 else 0.0
        mu_p = {d: wa * A_PACE_SCALE * a["mu_pct"][d] + (1 - wa) * fb["mu_pct"][d] for d in drivers}
        sd_p = {d: math.sqrt(wa * a["sd_pct"][d] ** 2 + (1 - wa) * fb["sd_pct"][d] ** 2) for d in drivers}
        source = f"blend(A:season_effects{' carried' if a.get('carry') else ''} w={wa:.2f}, results)"
    else:
        mu_p, sd_p, source = fb["mu_pct"], fb["sd_pct"], "results"
    if comp.get("grid") and comp.get("quali_pace") and QUALI_PACE_W > 0:
        mu_p = _blend_toward(mu_p, comp["quali_pace"], QUALI_PACE_W)
        sd_p = {d: v * (QUALI_PACE_SD_MULT if d in comp["quali_pace"] else 1.0) for d, v in sd_p.items()}
        source += f"+quali_pace(w={QUALI_PACE_W:g})"
    if comp.get("grid") and session == "race":
        s = pace_spread_post(year, rnd)
        if s != 1.0:
            mu_p = spread_pace(mu_p, s)
            source += f"+spread({s:g})"
    mu = {d: k * v for d, v in mu_p.items()}
    sd = {d: k * v for d, v in sd_p.items()}
    laps = int(circuit.get("sprint_laps") if session == "sprint" else circuit.get("laps") or 57)
    haz, split = _dnf_hazards(comp["rs"], drivers, team, circuit, laps)
    gd = comp.get("grid_dist") if PRE_GRID in ("quali_model", "blend") else None
    return RaceInputs(year=year, round=rnd, drivers=drivers, team=team, pace_mu=mu, pace_sd=sd, grid=comp.get("grid"), dnf_hazard=haz,
                      circuit=circuit, wet=False, p_wet=float(circuit.get("p_wet", 0.0)), grid_strength=fb["grid_z"], grid_dist=gd,
                      session=session, source=source + ("+A:quali_model" if gd else ""), ref_lap_s=comp["ref_lap_s"],
                      meta={**comp.get("meta", {}), "dnf_split": split, "n_prior_races": comp["rs"]["n_races"], "ref_lap_s": comp["ref_lap_s"],
                            "pace_pct": {d: round(v, 4) for d, v in mu_p.items()}})


def race_inputs(year: int, round: int, before_quali: bool = True, session: str = "race", use_a: bool = True) -> RaceInputs:
    """Assemble ``RaceInputs`` from data strictly before the race (plus the grid when ``before_quali`` is False)."""
    return inputs_from_components(race_components(year, round, before_quali, session, use_a))


# ----------------------------------------------------------------------------------------------- simulation

def win_temp_post(year: int, rnd: int) -> float:
    """The post-qualifying win temperature for (year, round): its walk-forward entry in ``WIN_TEMP_POST``, else
    the "latest" fit (a round after the last fit), else 1 (off)."""
    tab = WIN_TEMP_POST or {}
    t = tab.get(f"{int(year)}_{int(rnd)}")
    if t is None:
        t = tab.get("latest", 1.0)
    try:
        t = float(t)
    except (TypeError, ValueError):
        return 1.0
    return t if math.isfinite(t) and 0.2 <= t <= 5.0 else 1.0


def pace_spread_post(year: int, rnd: int) -> float:
    """The post-qualifying strength scale s for (year, round): its walk-forward entry in ``PACE_SPREAD_POST``, else
    the "latest" fit, else 1 (off)."""
    tab = PACE_SPREAD_POST or {}
    s = tab.get(f"{int(year)}_{int(rnd)}")
    if s is None:
        s = tab.get("latest", 1.0)
    try:
        s = float(s)
    except (TypeError, ValueError):
        return 1.0
    return s if math.isfinite(s) and 0.25 <= s <= 5.0 else 1.0


def spread_pace(mu: dict[str, float], s: float) -> dict[str, float]:
    """Scale the field's pace deviations about their mean by s (``mean + s (x - mean)``); s = 1 returns a copy."""
    if not mu or s == 1.0:
        return dict(mu)
    m = float(np.mean(list(mu.values())))
    return {d: m + s * (v - m) for d, v in mu.items()}


def temper_win(drivers: dict[str, dict], T: float) -> dict[str, dict]:
    """Sharpen (T > 1) or flatten the win probabilities of a ``simulate_race`` result in place: p ~ p^T
    renormalised over the field, then capped at the driver's podium probability (a win is a podium). Returns
    the same dict. Nothing else is touched."""
    if not drivers or T == 1.0:
        return drivers
    ds = list(drivers)
    p = np.array([float(drivers[d].get("p_win") or 0.0) for d in ds])
    if p.sum() <= 0:
        return drivers
    q = np.where(p > 0, np.power(np.clip(p, 1e-12, 1.0), T), 0.0)
    q = q / q.sum()
    for d, v in zip(ds, q):
        pod = drivers[d].get("p_podium")
        drivers[d]["p_win"] = float(min(v, pod)) if pod is not None else float(v)
    return drivers


def bunch(T: np.ndarray, running: np.ndarray) -> np.ndarray:
    """Safety-car compression: running cars keep their order, gaps reset to SC_GAP per position."""
    rk = np.argsort(np.argsort(T, axis=1), axis=1)
    lead = np.min(T, axis=1, keepdims=True)
    return np.where(running, lead + rk * SC_GAP, np.inf)


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def _arr(seq, n_slots: int, default: float) -> np.ndarray:
    a = np.full(n_slots + 2, default, float)
    if seq:
        v = np.asarray(seq, float)
        a[1:1 + min(len(v), n_slots)] = v[:n_slots]
        a[1 + len(v):] = v[-1] if len(v) else default
    return a


def _sample_grid(inp: RaceInputs, rng, n: int, pace: np.ndarray, ref: float = REF_LAP_S) -> np.ndarray:
    """(n, D) grid slot (1-based) per driver: the actual grid; else drawn from the qualifying model's grid
    distribution (``PRE_GRID`` "quali_model"), from the results-only qualifying score, or a mix of the two
    draws' ranks ("blend", weight ``PRE_GRID_MIX`` on the quali model)."""
    D = len(inp.drivers)
    if inp.grid:
        g = np.array([int(inp.grid.get(d) or 0) for d in inp.drivers], float)
        g = np.where(g <= 0, 1000 + np.arange(D), g)      # pit-lane starters behind everyone
        order = np.argsort(g, kind="stable")
        slots = np.empty(D, int)
        slots[order] = np.arange(1, D + 1)
        return np.broadcast_to(slots, (n, D)).copy()
    if inp.grid_dist and all(inp.grid_dist.get(d) for d in inp.drivers):
        P = np.zeros((D, D))
        for i, d in enumerate(inp.drivers):
            v = np.asarray(inp.grid_dist[d], float)[:D]
            P[i, :len(v)] = v
        P = np.clip(P, 1e-9, None)
        P /= P.sum(1, keepdims=True)
        cdf = np.cumsum(P, 1)
        u = rng.random((n, D))
        draw = np.empty((n, D))
        for i in range(D):
            draw[:, i] = np.searchsorted(cdf[i], u[:, i])
        score = draw + rng.random((n, D))
        if PRE_GRID == "blend" and inp.grid_strength:
            z = np.array([float(inp.grid_strength.get(d, NEW_ENTRY_Z)) for d in inp.drivers])
            rz = np.argsort(np.argsort(z[None, :] + QUALI_NOISE_Z * rng.standard_normal((n, D)), axis=1), axis=1)
            ra = np.argsort(np.argsort(score, axis=1), axis=1)
            score = PRE_GRID_MIX * ra + (1 - PRE_GRID_MIX) * rz + 0.01 * rng.random((n, D))
    elif inp.grid_strength:
        z = np.array([float(inp.grid_strength.get(d, NEW_ENTRY_Z)) for d in inp.drivers])
        score = z[None, :] + QUALI_NOISE_Z * rng.standard_normal((n, D))
    else:
        score = pace / (PACE_PER_Z_PCT * ref / 100.0) + QUALI_NOISE_Z * rng.standard_normal((n, D))
    return np.argsort(np.argsort(score, axis=1), axis=1) + 1


def simulate_race(inp: RaceInputs, n: int = 20000, seed: int | None = None, *, offsets: np.ndarray | None = None,
                  draw_param: bool = True, return_samples: bool = False, sprint: bool | None = None) -> dict:
    """Monte Carlo of one race; see the module docstring for the equations. Never raises on thin inputs."""
    sprint = (inp.session == "sprint") if sprint is None else sprint
    drivers = list(inp.drivers)
    D = len(drivers)
    if D == 0:
        return {"drivers": {}, "teams": {}, "p_sc": 0.0, "n": 0}
    rng = np.random.default_rng(seed)
    c = {**DEFAULT_CIRCUIT, **{k: v for k, v in (inp.circuit or {}).items() if v is not None}}
    L = int(c["sprint_laps"] if sprint else c["laps"])
    L = max(L, 2)
    ps = points_system(inp.year)
    table = np.array(ps["sprint"] if sprint else ps["race"], float)
    award_fl = bool(ps["fastest_lap"]) and not sprint

    mu = np.array([float(inp.pace_mu.get(d, 0.0)) for d in drivers])
    sdp = np.array([float(inp.pace_sd.get(d, 0.0)) for d in drivers])
    teams = [inp.team.get(d, d) for d in drivers]
    tnames = sorted(set(teams))
    tidx = np.array([tnames.index(t) for t in teams])

    ref = float(inp.ref_lap_s or c.get("ref_lap_s") or REF_LAP_S)
    ts = ref / REF_LAP_S                                   # time-based constants are stated for a 90 s lap
    p_wet = 1.0 if inp.wet else float(inp.p_wet if inp.p_wet is not None else c.get("p_wet", 0.0))
    wet = rng.random(n) < p_wet
    wf = lambda key: np.where(wet, WET[key], 1.0)          # noqa: E731

    pace = np.broadcast_to(mu, (n, D)).copy()
    if draw_param:
        pace += sdp * rng.standard_normal((n, D))
    if offsets is not None:
        pace += offsets
    pace += (ts * DAY_TEAM_SD * rng.standard_normal((n, len(tnames))))[:, tidx] * wf("day")[:, None]
    pace += ts * DAY_DRIVER_SD * rng.standard_normal((n, D)) * wf("day")[:, None]
    deg = np.array([float((inp.deg or {}).get(d, ts * DEG_DEFAULT)) for d in drivers])
    haz = DNF_MULT * np.array([float(inp.dnf_hazard.get(d, 0.001)) for d in drivers])
    # retirement lap after lap 1 drawn once: geometric with the per-lap hazard (x wet factor)
    hz = np.clip(1 - np.exp(-haz[None, :] * wf("dnf")[:, None]), 1e-9, 0.999)
    dnf_lap = 1 + rng.geometric(hz, size=(n, D))

    # ---- grid and lap 1
    slots = _sample_grid(inp, rng, n, pace, ref)
    S = max(D, 26)
    m1 = _arr(c.get("lap1_mean_by_grid"), S, 0.0)
    s1 = _arr(c.get("lap1_sd_by_grid"), S, 0.0)
    if not c.get("lap1_sd_by_grid"):
        s1 = 1.2 + 0.05 * np.arange(S + 2)
    q1 = _arr(c.get("lap1_incident_by_grid"), S, 0.012)
    sl = np.minimum(slots, S + 1)
    score = slots + m1[sl] + s1[sl] * LAP1_SD_MULT * float(c.get("lap1_sd_scale") or 1.0) * wf("lap1")[:, None] * rng.standard_normal((n, D))
    if LAP1_BAD_P > 0:
        score += (rng.random((n, D)) < LAP1_BAD_P) * rng.exponential(LAP1_BAD_SCALE, (n, D)) * wf("lap1")[:, None]
    score -= LAP1_PACE_GAIN * (pace - np.median(pace, axis=1, keepdims=True))
    rank1 = np.argsort(np.argsort(score, axis=1), axis=1)
    T = ref + rank1 * LAP1_SPACING + 0.05 * rng.random((n, D))
    running = np.ones((n, D), bool)
    laps_done = np.full((n, D), L, int)
    out1 = rng.random((n, D)) < np.minimum(0.5, q1[sl] * wf("dnf")[:, None])
    running &= ~out1
    laps_done[out1] = 0
    T[out1] = np.inf

    # ---- strategy
    W = 3
    stops = np.full((n, D, W), 10 ** 6, int)
    if not sprint:
        m = float(min(3.0, max(1.0, c.get("typical_stops", 1.6))))
        if STOP_DEV_P is None:                                  # independent per car (the model before October 2026)
            k = 1 + rng.binomial(2, (m - 1) / 2, size=(n, D))
        else:
            # one strategy for the race (the day's optimum), each car off it by one stop with STOP_DEV_P
            kr = 1 + rng.binomial(2, (m - 1) / 2, size=n)
            off = (rng.random((n, D)) < STOP_DEV_P) * np.where(rng.random((n, D)) < 0.5, -1, 1)
            k = np.clip(kr[:, None] + off, 1, W)
        if inp.stops:
            fixed = np.array([int(inp.stops.get(d, -1)) for d in drivers])
            k = np.where(fixed[None, :] >= 0, np.clip(fixed, 0, W)[None, :], k)
        for j in range(1, W + 1):
            base = L * j / (k + 1) + rng.normal(0, 0.07 * L, size=(n, D))
            lap = np.clip(np.round(base), 2, L - 1).astype(int)
            stops[:, :, j - 1] = np.where(j <= k, lap, 10 ** 6)
        stops.sort(axis=2)
    age = np.zeros((n, D))

    thr = float(c.get("overtake_threshold_s", 0.95))
    scale = float(c.get("overtake_scale_s", 0.25)) or 0.25
    sc_rate = SC_RATE_MULT * float(c.get("sc_rate_per_lap", 0.011))
    vsc_rate = SC_RATE_MULT * float(c.get("vsc_rate_per_lap", 0.006))
    pit_loss = float(c.get("pit_loss_s", 22.0))
    neutral_left = np.zeros(n, int)
    neutral_kind = np.zeros(n, int)                     # 1 SC, 2 VSC
    any_sc = np.zeros(n, bool)
    any_vsc = np.zeros(n, bool)
    rows = np.arange(n)[:, None]

    order = np.argsort(T, axis=1)
    for lap in range(1, L + 1):
        if lap == 1:
            # lap 1 already resolved; it can still bring out a neutralisation for the following laps
            u = rng.random(n)
            new_sc = u < sc_rate * LAP1_SC_MULT * wf("sc")
            new_vsc = ~new_sc & (u < (sc_rate + vsc_rate) * LAP1_SC_MULT * wf("sc"))
        else:
            free_now = neutral_left == 0
            u = rng.random(n)
            new_sc = free_now & (u < sc_rate * wf("sc"))
            new_vsc = free_now & ~new_sc & (u < (sc_rate + vsc_rate) * wf("sc"))
        if lap > 1 or new_sc.any() or new_vsc.any():
            if new_sc.any():
                neutral_left[new_sc] = rng.integers(SC_LAPS[0], SC_LAPS[1] + 1, size=int(new_sc.sum()))
                neutral_kind[new_sc] = 1
                any_sc |= new_sc
                T[new_sc] = bunch(T[new_sc], running[new_sc])
            if new_vsc.any():
                neutral_left[new_vsc] = rng.integers(VSC_LAPS[0], VSC_LAPS[1] + 1, size=int(new_vsc.sum()))
                neutral_kind[new_vsc] = 2
                any_vsc |= new_vsc
        if lap == 1:
            age += 1
            continue
        neutral = neutral_left > 0
        # opportunistic stops under neutralisation
        if not sprint and neutral.any():
            moved = np.zeros((n, D), bool)
            for j in range(W):
                sj = stops[:, :, j]
                cond = neutral[:, None] & (sj >= lap) & (sj <= lap + PIT_WINDOW) & ~moved
                sj[cond] = lap
                moved |= cond
                # keep later stops strictly after this lap
                for jj in range(j + 1, W):
                    sjj = stops[:, :, jj]
                    clash = cond & (sjj <= lap)
                    sjj[clash] = lap + 1 + jj
        pitting = (stops == lap).any(axis=2) & running
        # lap times
        eff = pace + deg * age
        lt = eff + ts * FUEL_PER_LAP * (L - lap) + ts * LAP_SD * wf("lap")[:, None] * rng.standard_normal((n, D))
        lt = np.where(neutral[:, None], 0.0, lt) + ref * np.where(neutral, np.where(neutral_kind == 1, 1.4, 1.3), 1.0)[:, None]
        pf = np.where(neutral_kind == 1, SC_PIT_FACTOR, VSC_PIT_FACTOR)
        Tn = T + lt
        if pitting.any():
            si, di_ = np.nonzero(pitting)
            m_ = si.size
            cost = pit_loss * np.where(neutral[si], pf[si], 1.0) + PIT_SD * rng.standard_normal(m_)
            cost += (rng.random(m_) < SLOW_STOP_P) * rng.uniform(*SLOW_STOP, size=m_)
            Tn[si, di_] += cost
        # retirements
        dnf = running & (dnf_lap == lap)
        running &= ~dnf
        laps_done[dnf] = lap - 1
        Tn[~running] = np.inf
        # overtaking, front to back in the previous lap's order
        # position-major (D, n) contiguous copies for the sequential pass
        Tp = np.ascontiguousarray(Tn[rows, order].T)
        Pp = np.ascontiguousarray(eff[rows, order].T)
        Fp = np.ascontiguousarray((pitting | ~running)[rows, order].T)
        blkT = np.full(n, -np.inf)
        blkP = np.zeros(n)
        U = rng.random((D, n))
        allow = ~neutral
        for i in range(D):
            cur = Tp[i]
            fi = Fp[i]
            inter = ~fi & np.isfinite(blkT) & (cur < blkT + HOLD_GAP)
            if inter.any():
                pp = _sigmoid((blkP - Pp[i] - thr) / scale) * allow
                win = U[i] < pp
                new = np.where(win, np.minimum(cur, blkT - PASS_MARGIN), np.maximum(cur, blkT + HOLD_GAP))
                cur = np.where(inter, new, cur)
                Tp[i] = cur
            upd = ~fi & (cur > blkT)
            blkP = np.where(upd, Pp[i], blkP)
            blkT = np.where(upd, cur, blkT)
        Tn = np.empty_like(Tn)
        Tn[rows, order] = Tp.T
        T = Tn
        age += 1
        age[pitting] = 0
        neutral_left = np.maximum(neutral_left - 1, 0)
        neutral_kind[neutral_left == 0] = 0
        order = np.argsort(T, axis=1)

    # ---- classification
    key = np.where(running, T - T.min(axis=1, keepdims=True, initial=np.inf, where=running), 1e9 + (L - laps_done) * 1e4)
    key = np.where(np.isfinite(key), key, 1e9 + (L - laps_done) * 1e4)
    key = key + 1e-6 * rng.random((n, D))
    fin_order = np.argsort(key, axis=1)
    pos = np.empty((n, D), int)
    pos[rows, fin_order] = np.arange(D)[None, :]
    classified = laps_done >= math.ceil(CLASSIFIED_SHARE * L)
    pts = np.where(classified & (pos < len(table)), table[np.minimum(pos, len(table) - 1)], 0.0)
    fl_bonus = np.zeros((n, D))
    flw = fl_score = None
    if award_fl:
        fl_score = np.where(running, pace + ts * FL_NOISE * rng.standard_normal((n, D)), np.inf)
        flw = np.argmin(fl_score, axis=1)
        ok = (pos[np.arange(n), flw] < 10) & classified[np.arange(n), flw]
        fl_bonus[np.arange(n)[ok], flw[ok]] = 1.0
    pts = pts + fl_bonus

    out_d = {}
    npts = len(table)
    for i, d in enumerate(drivers):
        p = pos[:, i]
        dist = np.bincount(p, minlength=D)[:D] / n
        out_d[d] = {"p_win": float(dist[0]), "p_podium": float(dist[:3].sum()),
                    "p_points": float(np.mean((p < npts) & classified[:, i])), "p_dnf": float(np.mean(~classified[:, i])),
                    "exp_pos": float(p.mean() + 1), "exp_points": float(pts[:, i].mean()), "pos_dist": [round(float(x), 5) for x in dist]}
    out_t = {}
    for ti, t in enumerate(tnames):
        cols = np.where(tidx == ti)[0]
        tp = pts[:, cols].sum(axis=1)
        dbl = np.all(pts[:, cols] > 0, axis=1) if len(cols) >= 2 else np.zeros(n, bool)
        out_t[t] = {"exp_points": float(tp.mean()), "p_double_points": float(dbl.mean())}
    res = {"drivers": out_d, "teams": out_t, "p_sc": float(any_sc.mean()), "p_vsc": float(any_vsc.mean()), "p_wet": float(wet.mean()),
           "n": int(n), "laps": L, "session": "sprint" if sprint else "race", "year": inp.year, "round": inp.round,
           "points_total": float(table.sum() + (1.0 if award_fl else 0.0)), "source": inp.source}
    if return_samples:
        # The fastest-lap car of each simulation (running at the flag; -1 if none), drawn after everything above when
        # the season has no fastest-lap point, so the published numbers do not change; and the grid slots (1-based).
        # Used by the fantasy layer (analytics/fantasy.py).
        if fl_score is None:
            fl_score = np.where(running, pace + ts * FL_NOISE * rng.standard_normal((n, D)), np.inf)
            flw = np.argmin(fl_score, axis=1)
        flw = np.where(np.isfinite(fl_score.min(axis=1)), flw, -1)
        res["_samples"] = {"drivers": drivers, "pos": (pos + 1).astype(np.int16), "points": pts.astype(np.float32),
                           "classified": classified, "teams": teams, "grid": np.asarray(slots, np.int16), "fl": flw.astype(np.int16),
                           "gap_to_winner": np.where(running, T - np.min(np.where(running, T, np.inf), axis=1, keepdims=True), np.nan)}
    return res


def simulate_sprint(inp: RaceInputs, n: int = 20000, seed: int | None = None, **kw) -> dict:
    """Sprint: the circuit's sprint distance (~100 km), no mandatory stop, sprint points table."""
    return simulate_race(inp, n=n, seed=seed, sprint=True, **kw)
