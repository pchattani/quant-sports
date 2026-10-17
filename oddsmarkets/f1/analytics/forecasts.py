"""
Walk-forward race forecasts for the race centre and for "points v expected".

For every round the forecast is what the model would have said at the time:

    pre     before qualifying: race_inputs(year, round, before_quali=True), so pace uses
            only results / lap times strictly before the round and the grid is sampled from
            the pre-qualifying model (qualifying.quali_model through the previous round);
    post    after qualifying: the same pace with the round's actual grid
            (race_inputs(..., before_quali=False)); None until qualifying is on disk;
    sprint  the sprint (sprint weekends only), with the sprint grid once the sprint has run
            or its grid is known, else a sampled grid.

and `simulate_race(inputs, n, seed)` plays it out n times (3,000 for finished races by
default; the build uses its --sims for the next race). Seeds are fixed per (year, round,
kind), so a rebuild with the same data reproduces the same numbers.

Cache: data/f1/cache/forecasts/<year>_<round>_<kind>.json, keyed by a hash of everything
the forecast can see: results, qualifying and sprint rows (and whether lap times exist) of
every round of the season and the two before it strictly before this round (plus this
round's qualifying for `post`, its sprint grid for `sprint`), the OpenF1 session files on
disk for the season, the circuit and its profile as of the race (circuits.circuit_profile with
before=(year, round)), the simulation count and a model version. A forecast is
recomputed only when one of those changes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from oddsmarkets.f1 import canon
from oddsmarkets.f1 import store as _store
from oddsmarkets.f1.analytics import data_root, rnd as _r

logger = logging.getLogger(__name__)

VERSION = "fc-3"   # fc-3 (Oct 2026): qualifying pace after qualifying, practice in the qualifying model
CACHE = _store.ROOT / "data" / "f1" / "cache" / "forecasts"
_DIGESTS: dict[int, tuple[float, dict[int, str]]] = {}


def _round_digests(year: int) -> dict[int, str]:
    """{round: sha1 of its results / qualifying / sprint rows and lap-time presence} for a season (cached by mtime)."""
    p = _store.season_path(year)
    try:
        mt = p.stat().st_mtime
    except OSError:
        return {}
    hit = _DIGESTS.get(year)
    if hit and hit[0] == mt and hit[1] is not None:
        return hit[1]
    out = {}
    for k, race in (canon.season(year).get("races") or {}).items():
        if not str(k).isdigit():
            continue
        blob = json.dumps([race.get("results"), race.get("qualifying"), race.get("sprint"), bool(race.get("laps")),
                           (race.get("circuit") or {}).get("id")], sort_keys=True, default=str)
        out[int(k)] = hashlib.sha1(blob.encode()).hexdigest()
    _DIGESTS[year] = (mt, out)
    return out


def signature(year: int, rnd: int, kind: str, n: int) -> str:
    h = hashlib.sha1(f"{VERSION}|{year}|{rnd}|{kind}|{n}".encode())
    for y in (year - 2, year - 1, year):
        dg = _round_digests(y)
        for r in sorted(dg):
            if y == year and r >= rnd:
                continue
            h.update(f"{y}:{r}:{dg[r]}".encode())
    race = canon.race(year, rnd)
    h.update(json.dumps([(race.get("circuit") or {}).get("id"), [r.get("driver") for r in race.get("qualifying") or race.get("results") or []]],
                        default=str).encode())
    if kind == "post":
        h.update(json.dumps([(r.get("driver"), r.get("position")) for r in race.get("qualifying") or []] +
                            [(r.get("driver"), r.get("grid")) for r in race.get("results") or []], default=str).encode())
    if kind == "sprint":
        h.update(json.dumps([(r.get("driver"), r.get("grid")) for r in race.get("sprint") or []], default=str).encode())
    try:                                                         # the circuit parameters the simulator will use
        from oddsmarkets.f1.models.circuits import circuit_profile
        prof = circuit_profile((race.get("circuit") or {}).get("id"), before=(year, rnd))
        h.update(json.dumps(prof, sort_keys=True, default=str).encode())
    except Exception:                                            # pragma: no cover - defensive
        pass
    try:
        files = sorted(f.name for f in (data_root() / str(year) / "sessions").glob("*.json"))
    except OSError:
        files = []
    h.update("|".join(files).encode())
    return h.hexdigest()


def compact(sim: dict) -> dict:
    """The race-centre SIM shape: drivers {p_win, p_podium, p_points, p_dnf, exp_pos, exp_points, pos_dist}, teams, p_sc."""
    drivers = {}
    for d, v in (sim.get("drivers") or {}).items():
        drivers[d] = {"p_win": _r(v.get("p_win"), 4), "p_podium": _r(v.get("p_podium"), 4), "p_points": _r(v.get("p_points"), 4),
                      "p_dnf": _r(v.get("p_dnf"), 4), "exp_pos": _r(v.get("exp_pos"), 3), "exp_points": _r(v.get("exp_points"), 3),
                      "pos_dist": [round(float(x), 4) for x in v.get("pos_dist") or []]}
    teams = {t: {"exp_points": _r(v.get("exp_points"), 3), "p_double_points": _r(v.get("p_double_points"), 4)}
             for t, v in (sim.get("teams") or {}).items()}
    return {"drivers": drivers, "teams": teams, "p_sc": _r(sim.get("p_sc"), 4), "p_vsc": _r(sim.get("p_vsc"), 4),
            "p_wet": _r(sim.get("p_wet"), 4), "n": sim.get("n"), "laps": sim.get("laps"), "session": sim.get("session"),
            "source": sim.get("source")}


def is_sprint_weekend(year: int, rnd: int) -> bool:
    race = canon.race(year, rnd)
    return bool(race.get("sprint") or (race.get("sessions") or {}).get("sprint"))


def forecast(year: int, rnd: int, kind: str = "pre", n: int = 3000, use_cache: bool = True) -> dict | None:
    """Walk-forward SIM for (year, round) and kind 'pre' | 'post' | 'sprint' (see module docstring).

    None when the forecast does not apply (no qualifying yet for 'post', not a sprint weekend for
    'sprint', no entry list) or the model fails; never raises.
    """
    year, rnd = int(year), int(rnd)
    race = canon.race(year, rnd)
    if not race:
        return None
    if kind == "post" and not (race.get("qualifying") or race.get("results")):
        return None
    if kind == "sprint" and not is_sprint_weekend(year, rnd):
        return None
    try:
        sig = signature(year, rnd, kind, n)
    except Exception as exc:                                     # pragma: no cover - defensive
        logger.info("forecast signature %s/%s failed: %s", year, rnd, exc)
        sig = None
    path = CACHE / f"{year}_{rnd}_{kind}.json"
    if use_cache and sig and path.exists():
        try:
            c = json.loads(path.read_text(encoding="utf-8"))
            if c.get("sig") == sig:
                return c["result"]
        except (OSError, ValueError, KeyError):
            pass
    try:
        from oddsmarkets.f1.models import race_sim as rs
        if kind == "sprint":
            inp = rs.race_inputs(year, rnd, before_quali=not race.get("sprint"), session="sprint")
        else:
            inp = rs.race_inputs(year, rnd, before_quali=(kind == "pre"))
        if not inp.drivers:
            return None
        seed = year * 1000 + rnd * 10 + {"pre": 1, "post": 2, "sprint": 3}.get(kind, 0)
        sim = rs.simulate_race(inp, n=n, seed=seed, sprint=(kind == "sprint"))
        out = compact(sim)
        out["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as exc:
        logger.warning("forecast %s/%s %s failed: %s", year, rnd, kind, exc)
        return None
    if sig:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"sig": sig, "result": out}, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
    return out


def race_forecast_for_points(year: int, rnd: int, n: int = 3000) -> dict | None:
    """The forecast "points v expected" is measured against: post-qualifying when qualifying exists, else pre."""
    return forecast(year, rnd, "post", n) or forecast(year, rnd, "pre", n)
