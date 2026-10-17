"""
The race centre payload, `data/<year>/races/<round>.json` (PAYLOADS.md), for finished and upcoming
rounds of any season.

Sources: the season store (results, qualifying, sprint, Jolpica laps/positions/pit stops), the
OpenF1 session records mapped to driverIds with `canon` (laps, stints, pit, race control, weather,
overtakes; 2023-), `laptime.race_pace`, the walk-forward forecasts (`forecasts.forecast`) and the
awards. Seasons without lap data get results/qualifying and empty lap sections.

Derived fields
--------------
* results.gap_ms = time_ms - the winner's time_ms (classified on the lead lap; None otherwise).
* qualifying.gap_ms_to_pole = the driver's time minus the pole-sitter's in the deepest segment the
  driver set a time in; teammate_gap_ms = the same against the team-mate in the deepest segment
  both set a time in (negative = faster).
* expected_v_actual (finished rounds with a forecast): exp_pos from the post-qualifying forecast
  (pre-qualifying when there is none), actual = classification position, and
  pctile_of_actual = 100 * (P(pos > actual) + 0.5 * P(pos = actual)) under the forecast's
  position distribution: 100 = better than every simulated outcome, 50 = as expected.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from oddsmarkets.f1.analytics import context, fnum, inum, rnd as _r, status_kind
from oddsmarkets.f1.analytics.awards import KEYS as AWARD_KEYS
from oddsmarkets.f1.analytics.awards import race_awards


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _result_rows(rows: list[dict]) -> list[dict]:
    win = next((inum(r.get("time_ms")) for r in rows if inum(r.get("position")) == 1), None)
    out = []
    for r in sorted(rows, key=lambda r: inum(r.get("position")) or 99):
        t = inum(r.get("time_ms"))
        out.append({"pos": inum(r.get("position")), "pos_text": r.get("position_text"), "driver": r.get("driver"),
                    "team": r.get("constructor"), "number": inum(r.get("number")), "grid": inum(r.get("grid")), "status": r.get("status"),
                    "classified": status_kind(r) == "finished", "points": fnum(r.get("points")), "laps": inum(r.get("laps")),
                    "time_ms": t, "gap_ms": (t - win) if (t is not None and win is not None) else None,
                    "fastest_ms": inum(r.get("fastest_ms")), "fastest_rank": inum(r.get("fastest_rank")),
                    "fastest_lap": inum(r.get("fastest_lap"))})
    return out


def _quali_rows(ctx: "context.RaceCtx") -> list[dict]:
    pole = next((r["driver"] for r in ctx.qualifying if inum(r.get("position")) == 1), None)
    team = {r["driver"]: r.get("constructor") for r in ctx.qualifying}
    out = []
    for r in ctx.quali_rows():
        d = r["driver"]
        seg, t = ctx.quali_deepest(d)
        gp = None
        if seg and t and pole:
            tp = ctx.quali_time(pole, seg)
            gp = (t - tp) if tp else None
        tg = None
        for o, to in team.items():
            if o == d or to != team.get(d):
                continue
            for sg in ("q3", "q2", "q1"):
                a, b = ctx.quali_time(d, sg), ctx.quali_time(o, sg)
                if a and b:
                    tg = a - b
                    break
            if tg is not None:
                break
        out.append({"pos": inum(r.get("position")), "driver": d, "team": r.get("constructor"), "number": inum(r.get("number")),
                    "q1": inum(r.get("q1")), "q2": inum(r.get("q2")), "q3": inum(r.get("q3")), "best_seg": seg,
                    "gap_ms_to_pole": gp, "teammate_gap_ms": tg})
    return out


def expected_v_actual(results: list[dict], sim: dict | None) -> dict[str, dict]:
    """{driver: {"exp_pos", "actual", "pctile_of_actual"}} (module docstring); {} without a forecast."""
    sd = (sim or {}).get("drivers") or {}
    out = {}
    for r in results:
        d = r.get("driver")
        a = inum(r.get("position"))
        if d not in sd or not a or status_kind(r) == "dns":
            continue
        dist = sd[d].get("pos_dist") or []
        if not dist:
            continue
        i = min(a, len(dist)) - 1
        tot = sum(dist) or 1.0
        p_worse = sum(dist[i + 1:]) / tot
        p_eq = dist[i] / tot
        out[d] = {"exp_pos": _r(sd[d].get("exp_pos"), 2), "actual": a, "pctile_of_actual": round(100.0 * (p_worse + 0.5 * p_eq), 1),
                  "exp_points": _r(sd[d].get("exp_points"), 2), "points": fnum(r.get("points"))}
    return out


def _pace_block(pace: dict) -> dict:
    drivers = {d: {"pace": _r(v.get("pace"), 3), "se": _r(v.get("se"), 3), "laps": v.get("laps"),
                   "deg": {c: _r(x, 4) for c, x in (v.get("deg") or {}).items()}, "traffic_cost": _r(v.get("traffic_cost"), 3),
                   "pace_pct": _r(v.get("pace_pct"), 3)}
               for d, v in (pace.get("drivers") or {}).items()}
    return {"drivers": drivers, "fuel_coef": _r(pace.get("fuel_coef"), 4), "ref_lap_s": _r(pace.get("ref_lap_s"), 3),
            "source": pace.get("source"), "reason": pace.get("reason")}


def build_race(year: int, rnd: int, forecasts: dict | None = None, effects: dict | None = None) -> dict:
    """races/<round>.json for (year, round). `forecasts` = {"pre", "post", "sprint"} SIMs (any may be None)."""
    ctx = context.get(year, rnd)
    race = ctx.race
    if not race:
        return {"ok": False, "reason": "round not in the season store", "year": year, "round": rnd}
    c = race.get("circuit") or {}
    fc = forecasts or {}
    done = ctx.done
    out: dict[str, Any] = {
        "ok": True, "year": year, "round": rnd, "name": race.get("name"), "date": race.get("date"), "time": race.get("time"),
        "circuit": {"id": c.get("id"), "name": c.get("name"), "country": c.get("country"), "locality": c.get("locality"),
                    "lat": c.get("lat"), "long": c.get("long")},
        "status": "done" if done else "upcoming", "schedule": race.get("sessions") or {},
        "forecast": {"pre_quali": fc.get("pre"), "post_quali": fc.get("post"),
                     "generated_at": next((f.get("generated_at") for f in (fc.get("post"), fc.get("pre")) if f), None)},
        "sprint_forecast": fc.get("sprint"),
        "results": _result_rows(ctx.results),
        "qualifying": _quali_rows(ctx),
        "sprint": _result_rows(ctx.sprint) if ctx.sprint else None,
    }
    if done:
        lt = ctx.laps()
        out["laps"] = {"n": lt["n"], "positions": lt["positions"], "gaps": lt["gaps"], "times": lt["times"], "source": lt.get("source")}
        out["stints"] = ctx.stints()
        out["pits"] = ctx.pits()
        out["control"] = ctx.control()
        out["weather"] = ctx.weather()
        out["wet"] = ctx.wet()
        out["overtakes"] = [{"lap": o["lap"], "by": o["by"], "on": o["on"], "pos": o["pos"]} for o in ctx.overtakes()]
        out["pace"] = _pace_block(ctx.pace())
        out["expected_v_actual"] = expected_v_actual(ctx.results, fc.get("post") or fc.get("pre"))
        out["awards"] = race_awards(year, rnd, fc, effects)
    else:
        out.update({"laps": {"n": 0, "positions": {}, "gaps": {}, "times": {}, "source": None}, "stints": {}, "pits": [], "control": [],
                    "weather": [], "wet": None, "overtakes": [], "pace": {"drivers": {}, "fuel_coef": None},
                    "expected_v_actual": {}, "awards": {k: None for k in AWARD_KEYS}})
    keys = ctx.session_keys()
    out["sessions"] = {k: keys.get(k) for k in ("race", "quali", "sprint", "sprint_quali", "fp1", "fp2", "fp3")}
    out["telemetry"] = {"race": ctx.has_telemetry("race"), "quali": ctx.has_telemetry("quali")}
    out["updated_at"] = _now()
    return out
