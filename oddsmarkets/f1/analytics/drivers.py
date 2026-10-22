"""
The driver catalogue: ~85 metrics per driver per season in eight groups (Results,
Qualifying, Race pace, Racecraft, Tyres, Reliability, Telemetry style, Points), with
field percentiles, team-mate percentiles and a per-race log (`drivers.json`).

Two passes:

1. `collect(year, forecasts)` walks every round with results and builds one record per
   (driver, round) from the season store, the OpenF1 session records and the model outputs
   (`context.RaceCtx`). Forecasts (`{round: {"pre": SIM, "post": SIM}}`) are optional; the
   expected-points metrics are None without them.
2. `aggregate(records, ...)` turns each driver's records into season values (formulas below),
   then `percentiles` ranks every metric across the field (100 = best, direction-aware: a
   metric with `lower` = True ranks the smallest value best) and within the team-mates the
   driver shared a car with.

Definitions (per race unless stated; season value = mean over the races where the input exists)
------------------------------------------------------------------------------------------------
* Starts exclude did-not-start entries. Classified = numeric position_text.
* grid slot: `grid`, with a pit-lane start (grid 0) counted as the last slot (number of starters).
* positions gained = grid slot - finishing position (classified finishes only).
* lap-1 gain = grid slot - running position at the end of lap 1; late gain = positions gained - lap-1 gain.
* quali gap to pole (%) = 100 * (t_seg(i) / t_seg(pole) - 1) in the deepest segment the driver set a
  time in (Q3 > Q2 > Q1; pre-2006 the single session); season value is the median.
* quali gap to team-mate (ms, %) = t_seg(i) - t_seg(mate) in the deepest segment both set a time;
  season value is the median over races (negative = faster than the team-mate).
* head-to-heads: share of races ahead of the team-mate (qualifying position; corrected race pace;
  race finish when at least one of the two is classified).
* quali pace: decomposition.quali_pace (segment-adjusted % gap to the field mean, negative = faster);
  quali pace rank = rank of that value in the session.
* race pace: laptime.race_pace pace (s/lap vs the field mean, negative = faster), pct = pace /
  reference lap * 100; rank within the race; season rank = rank of the season mean among drivers
  with at least a third of the most races with a pace.
* race pace delta to team-mate = pace(i) - mean pace(team-mates in that race).
* consistency = sd of the corrected clean-lap residuals (context.lap_scatter), in s.
* overtakes made / suffered: OpenF1 on-track passes (pit-stop position changes removed), per race;
  net = made - suffered.
* pass difficulty = mean over passes made of the pace deficit, deficit = pace(by) - pace(on) in
  s/lap from that race's corrected pace (positive = the overtaker was the slower car on the day).
* overtakes per pace = (overtakes made per race) / (0.25 + max(0, mean pace advantage over the cars
  passed)), advantage = pace(on) - pace(by) s/lap: passes per race per quarter-second-plus-advantage.
* penalties: race-control penalty notices naming the driver's car (race and sprint).
* degradation per compound: race_pace deg (s/lap per lap of tyre age), season mean.
* tyre management index = -1000 * mean over (race, compound) of (deg_i,c - field median deg_c), in ms
  per lap per lap of age: positive = the driver's tyres fell away slower than the field's.
* stint length v field = mean over stints of (laps in the stint - field median for that compound in
  that race); a final stint cut short by a retirement is excluded.
* sector strength = share of the driver's personal-best sectors (S1-S3, per race and qualifying
  session) that were the session's best; sector rank = mean rank of those personal bests.
* speed trap: the driver's top speed-trap reading per session (race and qualifying), its rank in the
  session; season values are means.
* telemetry style (race and qualifying sessions with processed telemetry): brake-point earliness =
  mean over corners of (driver's median braking-point distance before the apex - field median), m
  (positive = brakes earlier); minimum corner speed delta = mean over corners of (driver's median
  minimum speed - field median), km/h; full throttle, braking and coasting = the driver's median share
  of lap time, %.
* wet pace rank: mean race-pace rank in races flagged wet (context.wet).
* expected points = the walk-forward forecast's exp_points (post-qualifying, else pre-qualifying);
  points v expected = sum over races of (points - exp_points); the "pre" variant uses the
  pre-qualifying forecast (credits qualifying too).
* points lost in DNFs = sum of forecast exp_points over races the driver started and did not finish.
* DNF causes from `status`: driver-caused (accident, collision, spun off...), mechanical (engine,
  gearbox...), unknown (Jolpica's bare "Retired", which is all recent seasons publish).
"""
from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from typing import Any

from oddsmarkets.f1 import canon
from oddsmarkets.f1.analytics import (driver_name, fnum, inum, mean, median, percentiles, rnd as _r, share, started,
                                      status_kind)
from oddsmarkets.f1.analytics import context

logger = logging.getLogger(__name__)

COMPOUNDS = ("SOFT", "MEDIUM", "HARD")


def _m(key, label, group, fmt, lower=False, scope="results"):
    return {"key": key, "label": label, "group": group, "fmt": fmt, "lower": lower, "scope": scope}


GROUPS = ["Results", "Qualifying", "Race pace", "Racecraft", "Tyres", "Reliability", "Telemetry style", "Points"]

METRICS: list[dict] = [
    # Results
    _m("races", "Races", "Results", "int"),
    _m("wins", "Wins", "Results", "int"),
    _m("podiums", "Podiums", "Results", "int"),
    _m("win_rate", "Win rate", "Results", "prob"),
    _m("podium_rate", "Podium rate", "Results", "prob"),
    _m("top5_rate", "Top-5 rate", "Results", "prob"),
    _m("avg_finish", "Average finish", "Results", "1", True),
    _m("median_finish", "Median finish", "Results", "1", True),
    _m("best_finish", "Best finish", "Results", "int", True),
    _m("avg_grid", "Average grid", "Results", "1", True),
    _m("laps_led", "Laps led", "Results", "int", False, "laps"),
    _m("laps_led_share", "Share of laps led", "Results", "prob", False, "laps"),
    _m("race_h2h", "Race head-to-head v team-mate", "Results", "prob"),
    _m("fastest_laps", "Fastest laps", "Results", "int", False, "fastest"),
    _m("avg_fastest_rank", "Average fastest-lap rank", "Results", "1", True, "fastest"),
    _m("elo", "Field Elo (season end)", "Results", "0"),
    _m("elo_teammate", "Team-mate Elo (season end)", "Results", "0"),
    # Qualifying
    _m("poles", "Poles", "Qualifying", "int", False, "qualifying"),
    _m("front_row_rate", "Front-row rate", "Qualifying", "prob", False, "qualifying"),
    _m("q3_rate", "Q3 rate", "Qualifying", "prob", False, "segments"),
    _m("q1_exit_rate", "Q1 exit rate", "Qualifying", "prob", True, "segments"),
    _m("avg_quali", "Average qualifying position", "Qualifying", "1", True, "qualifying"),
    _m("quali_gap_pole_pct", "Gap to pole (%)", "Qualifying", "3", True, "qualifying"),
    _m("quali_gap_tm_ms", "Gap to team-mate (ms)", "Qualifying", "gap", True, "qualifying"),
    _m("quali_gap_tm_pct", "Gap to team-mate (%)", "Qualifying", "3", True, "qualifying"),
    _m("quali_h2h", "Qualifying head-to-head v team-mate", "Qualifying", "prob", False, "qualifying"),
    _m("quali_pace", "Qualifying pace (% v field)", "Qualifying", "3", True, "qualifying"),
    _m("quali_pace_rank", "Qualifying pace rank", "Qualifying", "1", True, "qualifying"),
    _m("quali_driver_effect", "Qualifying driver effect (%)", "Qualifying", "3", True, "model"),
    _m("grid_drop", "Grid drop (penalties)", "Qualifying", "2", True, "qualifying"),
    # Race pace
    _m("race_pace", "Race pace (s/lap v field)", "Race pace", "3", True, "laps"),
    _m("race_pace_pct", "Race pace (% v field)", "Race pace", "3", True, "laps"),
    _m("race_pace_rank", "Race pace rank (mean)", "Race pace", "1", True, "laps"),
    _m("race_pace_season_rank", "Season race-pace rank", "Race pace", "int", True, "laps"),
    _m("race_pace_best_rank", "Best race-pace rank", "Race pace", "int", True, "laps"),
    _m("race_pace_tm_delta", "Race pace v team-mate (s/lap)", "Race pace", "3", True, "laps"),
    _m("race_pace_h2h", "Race pace head-to-head v team-mate", "Race pace", "prob", False, "laps"),
    _m("driver_effect", "Race driver effect (%)", "Race pace", "3", True, "model"),
    _m("consistency", "Lap-time scatter (s)", "Race pace", "3", True, "laps"),
    _m("traffic_cost", "Time lost in traffic (s/race)", "Race pace", "2", True, "openf1"),
    _m("wet_pace_rank", "Wet-race pace rank", "Race pace", "1", True, "openf1"),
    _m("sector_best_share", "Sector strength (share of PB sectors that were session-best)", "Race pace", "prob", False, "openf1"),
    _m("sector_rank", "Personal-best sector rank", "Race pace", "1", True, "openf1"),
    # Racecraft
    _m("pos_gained", "Positions gained", "Racecraft", "2"),
    _m("lap1_gain", "Lap-1 gain", "Racecraft", "2", False, "laps"),
    _m("late_gain", "Gain after lap 1", "Racecraft", "2", False, "laps"),
    _m("overtakes_made", "Overtakes made per race", "Racecraft", "2", False, "openf1"),
    _m("overtakes_suffered", "Overtakes suffered per race", "Racecraft", "2", True, "openf1"),
    _m("net_overtakes", "Net overtakes per race", "Racecraft", "2", False, "openf1"),
    _m("pass_difficulty", "Pass difficulty (s/lap)", "Racecraft", "3", False, "openf1"),
    _m("overtakes_per_pace", "Overtakes per unit pace deficit", "Racecraft", "2", False, "openf1"),
    _m("penalties", "Penalties", "Racecraft", "int", True, "openf1"),
    _m("penalties_per_race", "Penalties per race", "Racecraft", "2", True, "openf1"),
    # Tyres
    _m("deg_soft", "Degradation: soft (s/lap/lap)", "Tyres", "3", True, "openf1"),
    _m("deg_medium", "Degradation: medium (s/lap/lap)", "Tyres", "3", True, "openf1"),
    _m("deg_hard", "Degradation: hard (s/lap/lap)", "Tyres", "3", True, "openf1"),
    _m("tyre_mgmt", "Tyre management index", "Tyres", "1", False, "laps"),
    _m("stint_v_field", "Stint length v field (laps)", "Tyres", "1", False, "pit"),
    _m("avg_stint", "Average stint (laps)", "Tyres", "1", False, "pit"),
    _m("stops_per_race", "Stops per race", "Tyres", "2", True, "pit"),
    _m("pit_lane_ms", "Pit-lane time (median)", "Tyres", "ms", True, "pit"),
    # Reliability
    _m("finish_rate", "Finish rate", "Reliability", "prob"),
    _m("dnf_rate", "DNF rate", "Reliability", "prob", True),
    _m("dnf_driver", "DNFs: driver-caused", "Reliability", "int", True),
    _m("dnf_mech", "DNFs: mechanical", "Reliability", "int", True),
    _m("dnf_unknown", "DNFs: cause not published", "Reliability", "int", True),
    _m("dns", "Did not start", "Reliability", "int", True),
    _m("laps_share", "Share of race laps completed", "Reliability", "prob"),
    _m("points_lost_dnf", "Expected points lost in DNFs", "Reliability", "1", True, "model"),
    # Telemetry style
    _m("brake_earliness", "Braking-point earliness v field (m)", "Telemetry style", "1", True, "telemetry"),
    _m("corner_speed_delta", "Minimum corner speed v field (km/h)", "Telemetry style", "1", False, "telemetry"),
    _m("full_throttle", "Full throttle (% of lap)", "Telemetry style", "pct", False, "telemetry"),
    _m("braking_share", "Braking (% of lap)", "Telemetry style", "pct", True, "telemetry"),
    _m("coasting", "Coasting (% of lap)", "Telemetry style", "pct", True, "telemetry"),
    _m("speed_trap_kph", "Speed trap (km/h)", "Telemetry style", "1", False, "openf1"),
    _m("speed_trap_rank", "Speed-trap rank", "Telemetry style", "1", True, "openf1"),
    # Points
    _m("points", "Points", "Points", "1"),
    _m("points_per_race", "Points per race", "Points", "2"),
    _m("points_rate", "Points-finish rate", "Points", "prob"),
    _m("team_points_share", "Share of team points", "Points", "prob"),
    _m("champ_pos", "Championship position", "Points", "int", True),
    _m("exp_points", "Expected points", "Points", "1", False, "model"),
    _m("points_v_expected", "Points v expected", "Points", "signed", False, "model"),
    _m("points_v_expected_pre", "Points v expected (pre-qualifying)", "Points", "signed", False, "model"),
    _m("sprint_points", "Sprint points", "Points", "1", False, "sprint"),
    _m("sprint_gain", "Sprint positions gained", "Points", "2", False, "sprint"),
]
METRIC_KEYS = [m["key"] for m in METRICS]


# ============================================================================== per-race records

def _sector_stats(rec: dict | None, ids: dict[str, str], race: bool) -> tuple[dict, dict, dict]:
    """(best_share, mean sector rank, (top speed, rank)) per driver for one OpenF1 session."""
    if not rec or not rec.get("laps"):
        return {}, {}, {}
    pb: dict[str, list] = {}
    trap: dict[str, float] = {}
    for num, rows in rec["laps"].items():
        d = ids.get(str(num))
        if not d:
            continue
        best = [None, None, None]
        for r in rows or []:
            if not r or len(r) < 9:
                continue
            if race and (r[9] if len(r) > 9 else 0):
                continue
            for k in range(3):
                v = inum(r[3 + k])
                if v and v > 0 and (best[k] is None or v < best[k]):
                    best[k] = v
            st = fnum(r[8])
            if st and 150 < st < 400:
                trap[d] = max(trap.get(d, 0.0), st)
        pb[d] = best
    best_share, rank = {}, {}
    sess_best = [min((b[k] for b in pb.values() if b[k]), default=None) for k in range(3)]
    for d, b in pb.items():
        have = [k for k in range(3) if b[k]]
        if not have:
            continue
        best_share[d] = sum(1 for k in have if b[k] == sess_best[k]) / len(have)
        ranks = []
        for k in have:
            ranks.append(1 + sum(1 for o in pb.values() if o[k] and o[k] < b[k]))
        rank[d] = sum(ranks) / len(ranks)
    order = sorted(trap, key=lambda d: -trap[d])
    traps = {d: (trap[d], k) for k, d in enumerate(order, 1)}
    return best_share, rank, traps


def _telemetry_style(tele: dict | None, ids: dict[str, str]) -> dict[str, dict]:
    """{driver: {brake_earliness, corner_speed_delta, full_throttle, braking_share, coasting}} for one session."""
    if not tele:
        return {}
    out: dict[str, dict] = defaultdict(dict)

    def per_corner(block: dict) -> dict[str, list]:
        res = {}
        for num, laps in (block or {}).items():
            d = ids.get(str(num))
            if not d:
                continue
            cols: dict[int, list] = defaultdict(list)
            for vals in (laps or {}).values():
                for k, v in enumerate(vals or []):
                    if fnum(v) is not None:
                        cols[k].append(float(v))
            res[d] = [median(cols[k]) if cols.get(k) else None for k in range(max(cols) + 1)] if cols else []
        return res

    for key, name in (("brake_points", "brake_earliness"), ("corner_min", "corner_speed_delta")):
        pc = per_corner(tele.get(key))
        if len(pc) < 5:                                          # a field median needs a field
            continue
        nc = max(len(v) for v in pc.values())
        field = [median(v[k] for v in pc.values() if k < len(v)) for k in range(nc)]
        for d, v in pc.items():
            deltas = [v[k] - field[k] for k in range(len(v)) if v[k] is not None and field[k] is not None]
            if deltas:
                out[d][name] = sum(deltas) / len(deltas)
    for num, rows in (tele.get("laps") or {}).items():
        d = ids.get(str(num))
        if not d or not rows:
            continue
        out[d]["full_throttle"] = median(r[3] for r in rows if len(r) > 5)
        out[d]["braking_share"] = median(r[4] for r in rows if len(r) > 5)
        out[d]["coasting"] = median(r[5] for r in rows if len(r) > 5)
    return dict(out)


def race_records(year: int, rnd: int, fc: dict | None = None) -> dict[str, dict]:
    """{driver: record} for one finished round (see module docstring for the fields' definitions)."""
    ctx = context.get(year, rnd)
    if not ctx.done:
        return {}
    fc = fc or {}
    res = {r["driver"]: r for r in ctx.results}
    team = {d: r.get("constructor") for d, r in res.items()}
    mates = defaultdict(list)
    for d, t in team.items():
        for o, t2 in team.items():
            if o != d and t2 == t:
                mates[d].append(o)
    grid = ctx.grid_slots()
    fin = ctx.finish()
    n_laps = max((inum(r.get("laps")) or 0 for r in ctx.results), default=0)

    # qualifying
    from oddsmarkets.f1.models.decomposition import quali_pace
    qrows = {r["driver"]: r for r in ctx.qualifying}
    qp = quali_pace(ctx.qualifying) if ctx.qualifying else {}
    qp_rank = {d: k for k, d in enumerate(sorted(qp, key=lambda d: qp[d]["pace"]), 1)}
    pole = next((r["driver"] for r in ctx.qualifying if inum(r.get("position")) == 1), None)
    era_segments = any(r.get("q2") or r.get("q3") for r in ctx.qualifying)

    # race pace
    pace = ctx.pace()
    pdv = pace.get("drivers") or {}
    ref = fnum(pace.get("ref_lap_s"))
    prank = ctx.pace_rank()
    scatter = ctx.lap_scatter()
    field_deg: dict[str, float] = {}
    for c in {c for v in pdv.values() for c in (v.get("deg") or {})}:
        field_deg[c] = median((v.get("deg") or {}).get(c) for v in pdv.values())

    # OpenF1 extras
    have_of = ctx.session("race") is not None
    ovt = ctx.overtakes() if have_of else []
    pens = ctx.penalties() if have_of else {}
    wet = ctx.wet()
    sectors = {}
    for kind in ("race", "quali"):
        rec = ctx.session(kind)
        if rec:
            sectors[kind] = _sector_stats(rec, ctx.ids(kind), kind == "race")
    tele = {}
    for kind in ("race", "quali"):
        t = ctx.telemetry(kind)
        if t:
            tele[kind] = _telemetry_style(t, ctx.ids(kind))

    # stints and stops
    stints = ctx.stints()
    ins = ctx.in_laps()
    have_pits = bool(ins) or bool(ctx.race.get("pitstops")) or bool(stints and have_of)
    comp_len: dict[str, list[int]] = defaultdict(list)
    for d, ss in stints.items():
        for k, s in enumerate(ss):
            if s.get("from") and s.get("to"):
                if k == len(ss) - 1 and d not in fin:
                    continue
                comp_len[s.get("compound") or "UNKNOWN"].append(s["to"] - s["from"] + 1)
    comp_med = {c: median(v) for c, v in comp_len.items()}
    lane = defaultdict(list)
    for p in ctx.pits():
        if p.get("lane_ms") and 8000 < p["lane_ms"] < 60000:
            lane[p["driver"]].append(p["lane_ms"])

    laps = ctx.laps()
    pre = (fc.get("pre") or {}).get("drivers") or {}
    post = (fc.get("post") or {}).get("drivers") or {}
    exp_src = post or pre
    spr = {r["driver"]: r for r in ctx.sprint}

    out: dict[str, dict] = {}
    for d, row in res.items():
        k = status_kind(row)
        st = k != "dns"
        rec: dict[str, Any] = {"round": rnd, "name": ctx.race.get("name"), "team": team.get(d), "started": st, "kind": k,
                               "status": row.get("status"), "pos": inum(row.get("position")), "classified": k == "finished",
                               "points": fnum(row.get("points")) or 0.0, "grid": grid.get(d), "grid_raw": inum(row.get("grid")),
                               "laps": inum(row.get("laps")) or 0, "race_laps": n_laps, "fastest_rank": inum(row.get("fastest_rank")),
                               "mates": mates.get(d, [])}
        if d in fin and grid.get(d):
            rec["pos_gained"] = grid[d] - fin[d]
        p1 = ctx.pos_at(d, 1) if st else None
        if p1 is not None and grid.get(d):
            rec["lap1_gain"] = grid[d] - p1
        posl = laps["positions"].get(d) or []
        if posl:
            rec["laps_led"] = sum(1 for p in posl if p == 1)
        # qualifying
        q = qrows.get(d)
        if q:
            rec["quali_pos"] = inum(q.get("position"))
            seg, t = ctx.quali_deepest(d)
            rec["q_seg"] = seg
            if era_segments:
                rec["q3"] = bool(inum(q.get("q3")))
                rec["q1_exit"] = not inum(q.get("q2")) and not inum(q.get("q3"))
            if seg and t and pole:
                tp = ctx.quali_time(pole, seg)
                if tp:
                    rec["quali_gap_pole_pct"] = 100.0 * (t / tp - 1.0)
            gaps_ms, gaps_pct = [], []
            for o in mates.get(d, []):
                for sg in ("q3", "q2", "q1"):
                    a, b = ctx.quali_time(d, sg), ctx.quali_time(o, sg)
                    if a and b:
                        gaps_ms.append(a - b)
                        gaps_pct.append(100.0 * (a / b - 1.0))
                        break
            if gaps_ms:
                rec["quali_gap_tm_ms"] = mean(gaps_ms)
                rec["quali_gap_tm_pct"] = mean(gaps_pct)
            h = [1.0 if (inum(q.get("position")) or 99) < (inum((qrows.get(o) or {}).get("position")) or 99) else 0.0
                 for o in mates.get(d, []) if o in qrows]
            if h:
                rec["quali_h2h"] = h
            if d in qp:
                rec["quali_pace"] = qp[d]["pace"]
                rec["quali_pace_rank"] = qp_rank[d]
            if rec["grid_raw"] and rec.get("quali_pos"):
                rec["grid_drop"] = rec["grid_raw"] - rec["quali_pos"]
        # race head-to-head
        hh = []
        for o in mates.get(d, []):
            a, b = res[d], res[o]
            if status_kind(b) == "dns" or not st:
                continue
            ca, cb = d in fin, o in fin
            if ca and cb:
                hh.append(1.0 if fin[d] < fin[o] else 0.0)
            elif ca != cb:
                hh.append(1.0 if ca else 0.0)
        if hh:
            rec["race_h2h"] = hh
        # pace
        pv = pdv.get(d)
        if pv:
            rec["pace"] = pv.get("pace")
            rec["pace_pct"] = 100.0 * pv["pace"] / ref if ref else pv.get("pace_pct")
            rec["pace_rank"] = prank.get(d)
            rec["deg"] = pv.get("deg") or {}
            rec["traffic_cost"] = pv.get("traffic_cost") if have_of else None
            mp = [pdv[o]["pace"] for o in mates.get(d, []) if o in pdv]
            if mp:
                rec["pace_tm_delta"] = pv["pace"] - sum(mp) / len(mp)
                rec["pace_h2h"] = [1.0 if pv["pace"] < x else 0.0 for x in mp]
            devs = [(v - field_deg[c]) for c, v in (pv.get("deg") or {}).items() if field_deg.get(c) is not None]
            if devs:
                rec["deg_dev"] = sum(devs) / len(devs)
            if wet:
                rec["wet_pace_rank"] = prank.get(d)
        if d in scatter:
            rec["scatter"] = scatter[d]
        # OpenF1 racecraft
        if have_of and st:
            made = [o for o in ovt if o["by"] == d]
            suff = [o for o in ovt if o["on"] == d]
            rec["ovt_made"], rec["ovt_suffered"] = len(made), len(suff)
            defs = [pdv[o["by"]]["pace"] - pdv[o["on"]]["pace"] for o in made if o["by"] in pdv and o["on"] in pdv]
            rec["pass_deficits"] = defs
            rec["penalties"] = pens.get(d, 0)
        # tyres and stops
        ss = stints.get(d) or []
        if ss and have_pits:
            lens = []
            for kk, s in enumerate(ss):
                if s.get("from") and s.get("to") and not (kk == len(ss) - 1 and d not in fin):
                    L = s["to"] - s["from"] + 1
                    med = comp_med.get(s.get("compound") or "UNKNOWN")
                    lens.append((L, L - med if med is not None else None))
            if lens:
                rec["stint_lens"] = [x[0] for x in lens]
                rec["stint_dev"] = [x[1] for x in lens if x[1] is not None]
        if have_pits and st:
            rec["stops"] = len(ins.get(d, ()))
        if lane.get(d):
            rec["lane_ms"] = lane[d]
        # sectors / traps / telemetry
        for kind, (bs, rk, tr) in sectors.items():
            if d in bs:
                rec.setdefault("sector_best", []).append(bs[d])
                rec.setdefault("sector_rank", []).append(rk[d])
            if d in tr:
                rec.setdefault("trap_kph", []).append(tr[d][0])
                rec.setdefault("trap_rank", []).append(tr[d][1])
        for kind, ts in tele.items():
            for key, v in (ts.get(d) or {}).items():
                if v is not None:
                    rec.setdefault("tele_" + key, []).append(v)
        # forecasts
        if d in exp_src:
            rec["exp_points"] = exp_src[d].get("exp_points")
        if d in pre:
            rec["exp_points_pre"] = pre[d].get("exp_points")
        # sprint
        s = spr.get(d)
        if s:
            rec["sprint_points"] = fnum(s.get("points")) or 0.0
            if status_kind(s) == "finished" and (inum(s.get("grid")) or 0) > 0 and inum(s.get("position")):
                rec["sprint_gain"] = inum(s["grid"]) - inum(s["position"])
        out[d] = rec
    return out


def collect(year: int, forecasts: dict[int, dict] | None = None, rounds: list[int] | None = None) -> dict[str, dict[int, dict]]:
    """{driver: {round: record}} for every finished round of the season (one bad round is skipped, logged)."""
    out: dict[str, dict[int, dict]] = defaultdict(dict)
    for r in rounds if rounds is not None else canon.completed_rounds(year):
        try:
            for d, rec in race_records(year, r, (forecasts or {}).get(r)).items():
                out[d][r] = rec
        except Exception as exc:
            logger.warning("driver records %s/%s failed: %s", year, r, exc)
    return dict(out)


# ============================================================================== season aggregation

def main_team(recs: dict[int, dict]) -> str | None:
    c = Counter(r.get("team") for r in recs.values() if r.get("team"))
    if not c:
        return None
    top = max(c.values())
    for r in sorted(recs, reverse=True):
        if c.get(recs[r].get("team")) == top:
            return recs[r]["team"]
    return None


def _flat(recs, key):
    out = []
    for r in recs:
        v = r.get(key)
        if isinstance(v, list):
            out.extend(x for x in v if fnum(x) is not None)
        elif fnum(v) is not None:
            out.append(v)
    return out


def season_values(recs: dict[int, dict], team_points: dict[str, float] | None = None) -> dict[str, Any]:
    """Season values of every catalogue metric for one driver (None where the inputs are missing)."""
    rs = [recs[k] for k in sorted(recs)]
    st = [r for r in rs if r["started"]]
    n = len(st)
    cl = [r for r in st if r["classified"]]
    pos = [r["pos"] for r in cl if r.get("pos")]
    v: dict[str, Any] = {k: None for k in METRIC_KEYS}
    v["races"] = n
    if n:
        wins = sum(1 for p in pos if p == 1)
        pods = sum(1 for p in pos if p <= 3)
        v.update(wins=wins, podiums=pods, win_rate=wins / n, podium_rate=pods / n, top5_rate=sum(1 for p in pos if p <= 5) / n)
        v["avg_finish"], v["median_finish"] = mean(pos), median(pos)
        v["best_finish"] = min(pos) if pos else None
        v["avg_grid"] = mean(r.get("grid") for r in st)
        led = [r["laps_led"] for r in st if "laps_led" in r]
        if led:
            v["laps_led"] = sum(led)
            raced = sum(r["laps"] for r in st if "laps_led" in r)
            v["laps_led_share"] = share(sum(led), raced)
        h = _flat(st, "race_h2h")
        v["race_h2h"] = mean(h)
        fr = [r["fastest_rank"] for r in st if r.get("fastest_rank")]
        if fr:
            v["fastest_laps"] = sum(1 for x in fr if x == 1)
            v["avg_fastest_rank"] = mean(fr)
    # qualifying
    q = [r for r in rs if r.get("quali_pos")]
    if q:
        v["poles"] = sum(1 for r in q if r["quali_pos"] == 1)
        v["front_row_rate"] = sum(1 for r in q if r["quali_pos"] <= 2) / len(q)
        v["avg_quali"] = mean(r["quali_pos"] for r in q)
        seg = [r for r in q if "q3" in r]
        if seg:
            v["q3_rate"] = sum(1 for r in seg if r["q3"]) / len(seg)
            v["q1_exit_rate"] = sum(1 for r in seg if r["q1_exit"]) / len(seg)
        v["quali_gap_pole_pct"] = median(_flat(q, "quali_gap_pole_pct"))
        v["quali_gap_tm_ms"] = median(_flat(q, "quali_gap_tm_ms"))
        v["quali_gap_tm_pct"] = median(_flat(q, "quali_gap_tm_pct"))
        v["quali_h2h"] = mean(_flat(q, "quali_h2h"))
        v["quali_pace"] = mean(_flat(q, "quali_pace"))
        v["quali_pace_rank"] = mean(_flat(q, "quali_pace_rank"))
        v["grid_drop"] = mean(_flat(q, "grid_drop"))
    # race pace
    pr = [r for r in st if r.get("pace") is not None]
    if pr:
        v["race_pace"] = mean(r["pace"] for r in pr)
        v["race_pace_pct"] = mean(_flat(pr, "pace_pct"))
        v["race_pace_rank"] = mean(_flat(pr, "pace_rank"))
        v["race_pace_best_rank"] = min(_flat(pr, "pace_rank") or [None]) if _flat(pr, "pace_rank") else None
        v["race_pace_tm_delta"] = mean(_flat(pr, "pace_tm_delta"))
        v["race_pace_h2h"] = mean(_flat(pr, "pace_h2h"))
        v["traffic_cost"] = mean(_flat(pr, "traffic_cost"))
        v["wet_pace_rank"] = mean(_flat(pr, "wet_pace_rank"))
        for c in COMPOUNDS:
            v[f"deg_{c.lower()}"] = mean((r.get("deg") or {}).get(c) for r in pr)
        dd = _flat(pr, "deg_dev")
        v["tyre_mgmt"] = -1000.0 * mean(dd) if dd else None
    v["consistency"] = mean(_flat(st, "scatter"))
    v["sector_best_share"] = mean(_flat(rs, "sector_best"))
    v["sector_rank"] = mean(_flat(rs, "sector_rank"))
    # racecraft
    v["pos_gained"] = mean(_flat(st, "pos_gained"))
    v["lap1_gain"] = mean(_flat(st, "lap1_gain"))
    late = [r["pos_gained"] - r["lap1_gain"] for r in st if r.get("pos_gained") is not None and r.get("lap1_gain") is not None]
    v["late_gain"] = mean(late)
    of = [r for r in st if "ovt_made" in r]
    if of:
        made = sum(r["ovt_made"] for r in of) / len(of)
        suff = sum(r["ovt_suffered"] for r in of) / len(of)
        v.update(overtakes_made=made, overtakes_suffered=suff, net_overtakes=made - suff)
        defs = _flat(of, "pass_deficits")
        v["pass_difficulty"] = mean(defs)
        adv = max(0.0, -(mean(defs) or 0.0)) if defs else 0.0
        v["overtakes_per_pace"] = made / (0.25 + adv)
        v["penalties"] = sum(r.get("penalties", 0) for r in of)
        v["penalties_per_race"] = v["penalties"] / len(of)
    sl = _flat(st, "stint_lens")
    if sl:
        v["avg_stint"] = mean(sl)
        v["stint_v_field"] = mean(_flat(st, "stint_dev"))
    stops = [r["stops"] for r in st if "stops" in r]
    v["stops_per_race"] = mean(stops)
    v["pit_lane_ms"] = median(_flat(st, "lane_ms"))
    # reliability
    if n:
        dnf = [r for r in st if not r["classified"]]
        v["finish_rate"] = len(cl) / n
        v["dnf_rate"] = len(dnf) / n
        v["dnf_driver"] = sum(1 for r in dnf if r["kind"] == "dnf_incident")
        v["dnf_mech"] = sum(1 for r in dnf if r["kind"] == "dnf_mech")
        v["dnf_unknown"] = sum(1 for r in dnf if r["kind"] in ("dnf_unknown", "dsq"))
        tot = sum(r["race_laps"] for r in st)
        v["laps_share"] = share(sum(min(r["laps"], r["race_laps"]) for r in st), tot)
        lost = [r.get("exp_points") for r in dnf if r.get("exp_points") is not None]
        if any(r.get("exp_points") is not None for r in st):
            v["points_lost_dnf"] = sum(lost)
    v["dns"] = sum(1 for r in rs if not r["started"])
    # telemetry style
    for key in ("brake_earliness", "corner_speed_delta", "full_throttle", "braking_share", "coasting"):
        v[key] = mean(_flat(rs, "tele_" + key))
    v["speed_trap_kph"] = mean(_flat(rs, "trap_kph"))
    v["speed_trap_rank"] = mean(_flat(rs, "trap_rank"))
    # points
    pts = sum(r["points"] for r in rs) + sum(r.get("sprint_points", 0.0) for r in rs)
    v["points"] = pts
    v["points_per_race"] = pts / n if n else None
    v["points_rate"] = sum(1 for r in st if r["points"] > 0) / n if n else None
    t = main_team(recs)
    if team_points and t and team_points.get(t):
        v["team_points_share"] = sum(r["points"] + r.get("sprint_points", 0.0) for r in rs if r.get("team") == t) / team_points[t]
    ex = [r for r in st if r.get("exp_points") is not None]
    if ex:
        v["exp_points"] = sum(r["exp_points"] for r in ex)
        v["points_v_expected"] = sum(r["points"] - r["exp_points"] for r in ex)
    exp = [r for r in st if r.get("exp_points_pre") is not None]
    if exp:
        v["points_v_expected_pre"] = sum(r["points"] - r["exp_points_pre"] for r in exp)
    sp = [r for r in rs if "sprint_points" in r]
    if sp:
        v["sprint_points"] = sum(r["sprint_points"] for r in sp)
        v["sprint_gain"] = mean(_flat(sp, "sprint_gain"))
    return v


def _log_row(rec: dict) -> dict:
    return {"round": rec["round"], "name": rec.get("name"), "grid": rec.get("grid_raw"), "pos": rec.get("pos"), "status": rec.get("status"),
            "points": _r(rec.get("points", 0.0) + rec.get("sprint_points", 0.0), 1), "race_points": _r(rec.get("points"), 1),
            "quali_pos": rec.get("quali_pos"), "pace": _r(rec.get("pace"), 3), "pace_rank": rec.get("pace_rank"),
            "pos_gained": rec.get("pos_gained"), "lap1_gain": rec.get("lap1_gain"), "overtakes": rec.get("ovt_made"),
            "pit_stops": rec.get("stops"), "deg": {c: _r(x, 4) for c, x in (rec.get("deg") or {}).items()} or None,
            "team": rec.get("team"), "exp_points": _r(rec.get("exp_points"), 2)}


def _round_value(key: str, v: Any) -> Any:
    if v is None:
        return None
    fmt = next((m["fmt"] for m in METRICS if m["key"] == key), "2")
    if fmt == "int":
        return int(round(v))
    if fmt == "prob":
        return round(float(v), 4)
    if fmt == "ms":
        return int(round(v))
    if fmt in ("3", "gap"):
        return round(float(v), 3) if fmt == "3" else int(round(v))
    return round(float(v), 3)


# Peer group (docs/METRICS_SPEC.md, Formula 1 "Drivers"): race drivers with the minimum starts. The payload `pct` ranks every
# entrant (one-race stand-ins included); `pct_peer` ranks only the qualifying drivers, with the same formula.
PEER_MIN_FULL = 8


def peer_floor(year: int) -> int:
    """Minimum starts for the season's peer group: 8 in a finished season of 16+ rounds; otherwise (an unfinished
    season, or a short one) max(3, min(8, ceil(0.35 x rounds completed)))."""
    done = len(canon.completed_rounds(year))
    total = len(canon.rounds(year))
    if total and done == total and done >= 16:
        return PEER_MIN_FULL
    return max(3, min(PEER_MIN_FULL, math.ceil(0.35 * done)))


PEER_RULE = ("Race drivers with at least `peer_floor` starts: 8 in a finished season of 16+ rounds, else max(3, min(8, "
             "ceil(0.35 x rounds completed))); drivers below it get no peer percentile and are nobody's similar driver.")

# Similar drivers (the spec's recipe): the eight headline metrics, z-scored within each season among its qualifying
# drivers, weighted by season-to-season r floored at 0.2; weighted Euclidean distance; the 5 nearest driver-seasons from
# 1996 on, the driver's own seasons excluded. A feature missing for either driver-season (a pointless team has no
# share of team points) is dropped and the weights renormalised, if at least 6 of the 8 remain.
SIMILAR_W = {"driver_effect": 0.41, "quali_driver_effect": 0.36, "race_h2h": 0.38, "team_points_share": 0.34, "race_pace": 0.73,
             "points_per_race": 0.74, "elo_teammate": 0.84, "lap1_gain": 0.32}
SIMILAR_FROM = 1996
SIMILAR_K = 5
SIMILAR_MIN_FEATURES = 6


def add_similar(catalogues: dict[int, dict], k: int = SIMILAR_K) -> list[int]:
    """Add "similar" [{driver, year, name, team, d}] to every qualifying driver of every catalogue from SIMILAR_FROM on (in
    place) and "similar_method" to each catalogue; returns the years changed. A catalogue without `qualified` flags (built
    before them) uses races >= peer_floor(year)."""
    rows: list[tuple[int, str, dict]] = []
    for y in sorted(catalogues):
        cat = catalogues[y] or {}
        if y < SIMILAR_FROM or not cat.get("drivers"):
            continue
        fl = cat.get("peer_floor") or peer_floor(y)
        D = cat["drivers"]
        q = [d for d, e in D.items() if (e.get("qualified") if "qualified" in e else (e.get("races") or 0) >= fl)]
        stats = {}
        for f in SIMILAR_W:
            xs = [x for x in (fnum((D[d].get("values") or {}).get(f)) for d in q) if x is not None]
            if len(xs) >= 3:
                m = sum(xs) / len(xs)
                sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) or 1.0
                stats[f] = (m, sd)
        for d in q:
            v = D[d].get("values") or {}
            z = {}
            for f, (m, sd) in stats.items():
                x = fnum(v.get(f))
                if x is not None:
                    z[f] = (x - m) / sd
            if len(z) >= SIMILAR_MIN_FEATURES:
                rows.append((y, d, z))
    changed = set()
    for y, d, za in rows:
        best = []
        for y2, d2, zb in rows:
            if d2 == d:
                continue
            fs = [f for f in za if f in zb]
            if len(fs) < SIMILAR_MIN_FEATURES:
                continue
            w = sum(SIMILAR_W[f] for f in fs)
            best.append((math.sqrt(sum(SIMILAR_W[f] * (za[f] - zb[f]) ** 2 for f in fs) / w), y2, d2))
        best.sort()
        out = []
        for dist, y2, d2 in best[:k]:
            e = catalogues[y2]["drivers"][d2]
            out.append({"driver": d2, "year": y2, "name": e.get("name"), "team": e.get("team"), "d": round(dist, 3)})
        catalogues[y]["drivers"][d]["similar"] = out
        changed.add(y)
    for y in changed:
        catalogues[y]["similar_method"] = (
            "The 5 nearest driver-seasons from 1996 on (the driver's own seasons excluded) by weighted Euclidean distance on "
            "the eight headline metrics (race and qualifying driver ratings, race head-to-head, share of team points, race "
            "pace, points per race, team-mate Elo, lap-1 gain), each z-scored within its season among the qualifying "
            "drivers and weighted by its season-to-season reliability (floored at 0.2); a feature missing for either "
            "season is dropped (at least 6 of 8 must remain). d is in standard deviations.")
    return sorted(changed)


def build(year: int, records: dict[str, dict[int, dict]] | None = None, forecasts: dict[int, dict] | None = None,
          effects: dict | None = None, elo: dict | None = None, standings: list[dict] | None = None) -> dict:
    """drivers.json for a season (PAYLOADS: metrics, drivers{name, team, races, values, pct, pct_teammate, log})."""
    from oddsmarkets.f1.analytics.glossary import DRIVER_DEFINITIONS
    store = canon.season(year)
    if records is None:
        records = collect(year, forecasts)
    team_points: dict[str, float] = defaultdict(float)
    for recs in records.values():
        for r in recs.values():
            if r.get("team"):
                team_points[r["team"]] += r["points"] + r.get("sprint_points", 0.0)
    champ = {row["driver"]: row["pos"] for row in standings or []}
    eff = effects or {}
    values: dict[str, dict] = {}
    for d, recs in records.items():
        v = season_values(recs, team_points)
        v["driver_effect"] = ((eff.get("driver") or {}).get(d) or {}).get("effect")
        v["quali_driver_effect"] = ((eff.get("quali_driver") or {}).get(d) or {}).get("effect")
        v["champ_pos"] = champ.get(d)
        e = (elo or {}).get(d) or {}
        v["elo"], v["elo_teammate"] = e.get("elo"), e.get("elo_teammate")
        values[d] = v
    # season race-pace rank among drivers with enough paced races
    paced = {d: sum(1 for r in records[d].values() if r.get("pace") is not None) for d in values}
    need = max(paced.values(), default=0) / 3.0
    elig = {d: values[d]["race_pace"] for d in values if values[d]["race_pace"] is not None and paced[d] >= need and paced[d] > 0}
    for k, d in enumerate(sorted(elig, key=lambda d: elig[d]), 1):
        values[d]["race_pace_season_rank"] = k
    # percentiles
    field_pct: dict[str, dict[str, int]] = defaultdict(dict)
    for m in METRICS:
        if m["key"] in ("races",):
            continue
        p = percentiles({d: v[m["key"]] for d, v in values.items()}, m["lower"])
        for d, x in p.items():
            field_pct[d][m["key"]] = x
    floor = peer_floor(year)
    qual = {d for d, v in values.items() if (v.get("races") or 0) >= floor}
    peer_pct: dict[str, dict[str, int]] = defaultdict(dict)
    for m in METRICS:
        if m["key"] in ("races",):
            continue
        p = percentiles({d: values[d][m["key"]] for d in qual}, m["lower"])
        for d, x in p.items():
            peer_pct[d][m["key"]] = x
    main = {d: main_team(records[d]) for d in values}
    tm_pct: dict[str, dict[str, int]] = defaultdict(dict)
    for t in set(main.values()):
        group = [d for d in values if main[d] == t]
        if len(group) < 2:
            continue
        for m in METRICS:
            if m["key"] in ("races",):
                continue
            p = percentiles({d: values[d][m["key"]] for d in group}, m["lower"])
            for d, x in p.items():
                tm_pct[d][m["key"]] = x
    out_drivers = {}
    for d, v in values.items():
        out_drivers[d] = {"name": driver_name(store, d), "code": ((store.get("drivers") or {}).get(d) or {}).get("code"),
                          "team": main[d], "teams": sorted({r.get("team") for r in records[d].values() if r.get("team")}),
                          "races": v["races"],
                          "values": {k: _round_value(k, x) for k, x in v.items()},
                          "pct": dict(field_pct.get(d, {})), "pct_teammate": dict(tm_pct.get(d, {})),
                          "qualified": d in qual, "pct_peer": dict(peer_pct.get(d, {})),
                          "log": [_log_row(records[d][r]) for r in sorted(records[d])]}
    metrics = [{**m, "desc": DRIVER_DEFINITIONS.get(m["key"], "")} for m in METRICS]
    return {"ok": True, "year": year, "metrics": metrics, "groups": GROUPS, "drivers": out_drivers,
            "peer_floor": floor, "peer_rule": PEER_RULE, "peer_count": len(qual),
            "rounds": sorted({r for recs in records.values() for r in recs})}
