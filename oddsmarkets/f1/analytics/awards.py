"""
Per-race awards for the race centre (`races/<round>.json` -> "awards").

Every award is {"driver", "value", "label", "why"} (team of the weekend: {"team", "value",
"label", "why"}), or null when the inputs do not exist for that race. Methods:

driver_of_the_day     max over drivers of points - exp_points, exp_points from the walk-forward
                      forecast at lights-out (post-qualifying; pre-qualifying when there is none).
                      Without a forecast: max positions gained (grid slot - finish).
best_drive_from_back  max over classified drivers with a gain of gain * w, gain = grid slot - finish,
                      w = 0.5 + rank_car / n_cars, rank_car the rank of the team's car pace at that
                      round (1 = fastest; decomposition car effect, else the race-pace mean of the
                      team's drivers, else the team's best grid slot). A slower car weighs more: a
                      gain in the slowest car counts about three times one in the fastest.
best_strategy         positions gained through the pit stops against the race's norm:
                      for each stop on in-lap L, change = pos(L - 1) - pos(L + 2) (running positions,
                      positive = gained); the norm m = mean change over every stop in the race;
                      value_i = sum over i's stops of (change - m), for classified drivers with at
                      most 4 stops (more pit visits are repairs or penalties, not a strategy). Undercuts, overcuts and stops under
                      a safety car all show up as stops that cost fewer places than usual. Needs lap
                      positions and stop laps; at least one stop.
fastest_stop          min stationary time (OpenF1 stop_ms); when no stationary times exist, the fastest
                      pit-lane time (OpenF1 lane_ms or Jolpica duration), labelled as such.
overtake_of_race      the pass with the largest pace deficit, deficit = pace(by) - pace(on) in s/lap
                      from the race's corrected pace (positive = the overtaker was slower on the day);
                      OpenF1 passes (2023-), else passes derived from lap positions; lap 1 excluded.
unluckiest            largest points loss from bad luck, over two kinds:
                      (a) a retirement not caused by the driver (mechanical, or cause not published)
                          while running in a points position: loss = points of the position held at
                          the end of the last completed lap (else the forecast's exp_points, else the
                          points of the grid slot when it was a points slot);
                      (b) safety-car timing: a driver who stopped in the 3 laps before a SC / VSC
                          deployment (rivals then stop under it for less): loss = points(position at
                          the end of the lap before his stop) - points(final position), when positive.
smoothest             lowest sd of corrected clean laps (context.lap_scatter) among classified drivers
                      with at least 60% of the winner's laps.
team_of_weekend       max over teams of sum over its drivers of (points - exp_points) (race and sprint
                      points v the race and sprint forecasts where they exist).
"""
from __future__ import annotations

from typing import Any

from oddsmarkets.f1.analytics import context, driver_name, fnum, inum, rnd as _r, status_kind, team_name

MAX_STRATEGY_STOPS = 4          # more visits than this are repairs or penalties, not a strategy
KEYS = ("driver_of_the_day", "best_drive_from_back", "best_strategy", "fastest_stop", "overtake_of_race", "unluckiest", "smoothest",
        "team_of_weekend")


def _pts_table(year: int) -> list[float]:
    try:
        from oddsmarkets.f1.models.race_sim import points_system
        return [float(x) for x in points_system(year)["race"]]
    except Exception:                                            # pragma: no cover - defensive
        return [25, 18, 15, 12, 10, 8, 6, 4, 2, 1]


def _pts(table: list[float], pos: int | None) -> float:
    return table[pos - 1] if pos and 1 <= pos <= len(table) else 0.0


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _aw(driver: str, value: Any, label: str, why: str) -> dict:
    return {"driver": driver, "value": value, "label": label, "why": why}


def strategy_gains(ctx: "context.RaceCtx") -> dict[str, float]:
    """{driver: positions gained through stops v the race norm} (module docstring); {} without lap positions."""
    pos = ctx.laps()["positions"]
    ins = ctx.in_laps()
    if not pos or not ins:
        return {}
    changes: dict[str, list[float]] = {}
    for d, laps in ins.items():
        for L in sorted(laps):
            a, b = ctx.pos_at(d, L - 1), ctx.pos_at(d, L + 2)
            if a is not None and b is not None:
                changes.setdefault(d, []).append(a - b)
    allc = [c for v in changes.values() for c in v]
    if not allc:
        return {}
    m = sum(allc) / len(allc)
    return {d: sum(c - m for c in v) for d, v in changes.items()}


def car_rank(ctx: "context.RaceCtx", effects: dict | None) -> dict[str, int]:
    """{team: rank of its car's pace at this round, 1 = fastest} (see best_drive_from_back)."""
    teams = sorted({r.get("constructor") for r in ctx.starters() if r.get("constructor")})
    score: dict[str, float] = {}
    car = (effects or {}).get("car") or {}
    for t in teams:
        states = [s for s in car.get(t) or [] if s.get("round", 0) <= ctx.round]
        if states:
            score[t] = float(states[-1]["effect"])
    if len(score) < len(teams):
        pd = ctx.pace().get("drivers") or {}
        score = {}
        for t in teams:
            v = [pd[d]["pace"] for d in pd if ctx.team_of(d) == t]
            if v:
                score[t] = sum(v) / len(v)
    if len(score) < len(teams):
        grid = ctx.grid_slots()
        score = {t: min((grid[r["driver"]] for r in ctx.starters() if r.get("constructor") == t and r["driver"] in grid), default=99)
                 for t in teams}
    return {t: k for k, t in enumerate(sorted(score, key=lambda t: score[t]), 1)}


def race_awards(year: int, rnd: int, forecast: dict | None = None, effects: dict | None = None) -> dict:
    """All awards for a finished round (module docstring); every entry null when the race has not run."""
    ctx = context.get(year, rnd)
    out: dict[str, Any] = {k: None for k in KEYS}
    if not ctx.done:
        return out
    st = ctx.store
    nm = lambda d: driver_name(st, d)  # noqa: E731
    table = _pts_table(year)
    fin = ctx.finish()
    grid = ctx.grid_slots()
    res = {r["driver"]: r for r in ctx.results}
    fc = forecast or {}
    post = ((fc.get("post") or {}).get("drivers")) or ((fc.get("pre") or {}).get("drivers")) or {}
    sprint_fc = ((fc.get("sprint") or {}).get("drivers")) or {}
    sprint_pts = {r["driver"]: fnum(r.get("points")) or 0.0 for r in ctx.sprint}
    pd = ctx.pace().get("drivers") or {}

    def safe(fn):
        try:
            return fn()
        except Exception:                                        # an award never takes the page down
            return None

    # driver of the day
    def dotd():
        if post:
            cand = {d: (fnum(res[d].get("points")) or 0.0) - (post[d].get("exp_points") or 0.0) for d in res if d in post}
            if not cand:
                return None
            d = max(cand, key=lambda k: cand[k])
            pts = fnum(res[d].get("points")) or 0.0
            return _aw(d, _r(cand[d], 2), f"{cand[d]:+.1f} pts v expected",
                       f"{nm(d)} scored {pts:g} from P{grid.get(d, '?')} on the grid; the model expected {post[d].get('exp_points', 0):.1f}.")
        gains = {d: grid[d] - fin[d] for d in fin if d in grid}
        if not gains:
            return None
        d = max(gains, key=lambda k: gains[k])
        return _aw(d, gains[d], f"+{gains[d]} places", f"{nm(d)} went from P{grid[d]} to P{fin[d]} (no forecast for this race).")
    out["driver_of_the_day"] = safe(dotd)

    # best drive from the back
    def back():
        ranks = car_rank(ctx, effects)
        n = max(len(ranks), 1)
        best = None
        for d, p in fin.items():
            g = grid.get(d)
            if not g or g - p <= 0:
                continue
            t = res[d].get("constructor")
            w = 0.5 + ranks.get(t, n) / n
            v = (g - p) * w
            if best is None or v > best[0]:
                best = (v, d, g, p, ranks.get(t))
        if not best:
            return None
        v, d, g, p, cr = best
        car = f" in the {_ordinal(cr)}-fastest car" if cr else ""
        return _aw(d, _r(v, 2), f"P{g} to P{p}", f"{nm(d)} gained {g - p} places from P{g}{car}.")
    out["best_drive_from_back"] = safe(back)

    # best strategy
    def strat():
        ins = ctx.in_laps()
        g = {d: v for d, v in strategy_gains(ctx).items() if d in fin and len(ins.get(d, ())) <= MAX_STRATEGY_STOPS}
        if not g:
            return None
        d = max(g, key=lambda k: g[k])
        if g[d] <= 0:
            return None
        n_st = len(ctx.in_laps().get(d, ()))
        return _aw(d, _r(g[d], 2), f"{g[d]:+.1f} places through the stops",
                   f"{nm(d)}'s {n_st}-stop race cost {g[d]:.1f} fewer places in the pit windows than the race's average stop.")
    out["best_strategy"] = safe(strat)

    # fastest stop
    def fstop():
        pits = ctx.pits()
        st_ = [p for p in pits if p.get("stop_ms") and 1500 <= p["stop_ms"] <= 30000]
        if st_:
            p = min(st_, key=lambda p: p["stop_ms"])
            return _aw(p["driver"], p["stop_ms"], f"{p['stop_ms'] / 1000:.1f} s stationary",
                       f"{team_name(st, ctx.team_of(p['driver']))} turned {nm(p['driver'])} round in {p['stop_ms'] / 1000:.1f} s on lap {p['lap']}.")
        ln = [p for p in pits if p.get("lane_ms") and 8000 <= p["lane_ms"] <= 60000]
        if ln:
            p = min(ln, key=lambda p: p["lane_ms"])
            return _aw(p["driver"], p["lane_ms"], f"{p['lane_ms'] / 1000:.1f} s in the pit lane",
                       f"Quickest trip through the pit lane, lap {p['lap']} (no stationary times published).")
        return None
    out["fastest_stop"] = safe(fstop)

    # overtake of the race
    def ovt():
        passes = ctx.overtakes() if ctx.session("race") else ctx.derived_passes()
        best = None
        for o in passes:
            if (o.get("lap") or 0) <= 1 or o["by"] not in pd or o["on"] not in pd:
                continue
            deficit = pd[o["by"]]["pace"] - pd[o["on"]]["pace"]
            if best is None or deficit > best[0]:
                best = (deficit, o)
        if not best:
            return None
        deficit, o = best
        return _aw(o["by"], _r(deficit, 3), f"on {nm(o['on'])}, lap {o['lap']}",
                   f"{nm(o['by'])} passed {nm(o['on'])} for P{o.get('pos') or '?'} on lap {o['lap']} despite being {deficit:+.2f} s/lap "
                   f"{'slower' if deficit > 0 else 'quicker'} on corrected pace.")
    out["overtake_of_race"] = safe(ovt)

    # unluckiest
    def unlucky():
        cands = []
        for d, r in res.items():
            k = status_kind(r)
            if k not in ("dnf_mech", "dnf_unknown"):
                continue
            laps_done = inum(r.get("laps")) or 0
            held = ctx.pos_at(d, laps_done) if laps_done else None
            if held:
                loss = _pts(table, held)
                how = f"while running P{held}: {loss:g} points gone"
            elif d in post:
                loss = post[d].get("exp_points") or 0.0
                how = f"; the forecast had him on {loss:.1f} points"
            else:
                g = grid.get(d)
                loss = _pts(table, g)
                how = f"from P{g} on the grid: {loss:g} points gone"
            if loss > 0:
                cause = "a mechanical failure" if k == "dnf_mech" else "a retirement (cause not published)"
                cands.append((loss, d, f"Out on lap {laps_done + 1} with {cause} {how}.".replace(" ;", ";")))
        wins = [w for w in ctx.neutral_windows() if w["kind"] in ("SC", "VSC")]
        if wins:
            for d, laps in ctx.in_laps().items():
                if d not in fin:
                    continue
                for L in laps:
                    w = next((w for w in wins if 0 < w["from"] - L <= 3), None)
                    if not w:
                        continue
                    before = ctx.pos_at(d, L - 1)
                    if not before:
                        continue
                    loss = _pts(table, before) - _pts(table, fin[d])
                    if loss > 0:
                        cands.append((loss, d, f"Stopped on lap {L}, {w['from'] - L} lap(s) before the {w['kind']}: P{before} before the stop, P{fin[d]} at the flag."))
        if not cands:
            return None
        loss, d, why = max(cands, key=lambda c: c[0])
        return _aw(d, _r(loss, 1), f"{loss:.1f} points lost", why)
    out["unluckiest"] = safe(unlucky)

    # smoothest
    def smooth():
        sc = ctx.lap_scatter()
        lead = max((inum(r.get("laps")) or 0 for r in ctx.results), default=0)
        cand = {d: v for d, v in sc.items() if d in fin and (inum(res[d].get("laps")) or 0) >= 0.6 * lead}
        if not cand:
            return None
        d = min(cand, key=lambda k: cand[k])
        return _aw(d, _r(cand[d], 3), f"{cand[d]:.3f} s lap-time sd", f"{nm(d)}'s corrected clean laps varied by just {cand[d]:.3f} s (1 sd).")
    out["smoothest"] = safe(smooth)

    # team of the weekend
    def team():
        if not post:
            return None
        acc: dict[str, float] = {}
        for d, r in res.items():
            t = r.get("constructor")
            if d in post and t:
                acc[t] = acc.get(t, 0.0) + (fnum(r.get("points")) or 0.0) - (post[d].get("exp_points") or 0.0)
                if d in sprint_fc and d in sprint_pts:
                    acc[t] += sprint_pts[d] - (sprint_fc[d].get("exp_points") or 0.0)
        if not acc:
            return None
        t = max(acc, key=lambda k: acc[k])
        return {"team": t, "value": _r(acc[t], 2), "label": f"{acc[t]:+.1f} pts v expected",
                "why": f"{team_name(st, t)}'s drivers beat the model's expectation by {acc[t]:.1f} points combined."}
    out["team_of_weekend"] = safe(team)
    return out
