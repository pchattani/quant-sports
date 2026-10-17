"""
Rankings payloads: data/<T>/rankings.json (official, Elo, race, points to defend) and data/<T>/elo.json.

Points per event come from C's `season_sim.event_points` (canon's tables through `_points`): a loser keeps the
points of the round she lost in (a bye followed by a loss earns first-round points), the champion "W", the
Finals pay per round-robin win, semi-final and final win. Only tour-level events with ranking points
(Slams, the Finals, Masters / 1000s, 500s, 250s) are counted; qualifying, Challenger / WTA 125 points and the
best-of-N rule are not modelled (the official column is the tours' own).

Race: points from this season's counted events, finished or in progress (a player still alive has the
points of the rounds she has already lost nothing in: none yet).
Points to defend: last season's counted events whose 52 weeks have not run out on `today`; each drops on
the Monday after its end date plus 52 weeks: [[event, week, points]].
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from oddsmarkets.tennis import analytics as an

logger = logging.getLogger(__name__)
ACTIVE_DAYS = 365
MIN_ELO_N = 10


def event_points(td: an.TourData, year: int, eids: list[str] | None = None) -> dict[str, dict[str, float]]:
    """{event_id: {pid: points}} for the season's counted events."""
    from oddsmarkets.tennis.models import season_sim as SS
    by_ev: dict[str, list[dict]] = defaultdict(list)
    for m in td.matches(year).values():
        by_ev[m.get("event")].append(m)
    out = {}
    for eid, ev in td.events(year).items():
        if str(ev.get("level")) not in an.POINT_LEVELS or (eids is not None and eid not in eids):
            continue
        ms = by_ev.get(eid) or []
        if not ms:
            continue
        pts, _, _ = SS.event_points(dict(ev, id=eid, year=int(year)), ms, td.tour)
        out[eid] = {p: float(v) for p, v in pts.items() if p and v}
    return out


def drop_week(end: Any) -> str | None:
    """The Monday on or after end + 364 days, iso."""
    d = an.day(end)
    if d is None:
        return None
    x = d + timedelta(days=364)
    return (x + timedelta(days=(7 - x.weekday()) % 7)).isoformat()


def to_defend(td: an.TourData, today: date | None = None, prev_points: dict | None = None) -> dict[str, list]:
    """{pid: [[event, week, points]]} for last season's counted events still inside the 52 weeks on `today`."""
    today = today or td.today
    y = today.year - 1
    if y not in td.years:
        return {}
    pts = prev_points if prev_points is not None else event_points(td, y)
    out: dict[str, list] = defaultdict(list)
    for eid, row in pts.items():
        ev = td.events(y).get(eid) or {}
        wk = drop_week(ev.get("end") or ev.get("start"))
        if wk is None or wk < today.isoformat():
            continue
        for p, v in row.items():
            out[p].append([eid, wk, round(v)])
    return {p: sorted(v, key=lambda r: r[1]) for p, v in out.items()}


def race(td: an.TourData, year: int, cur_points: dict | None = None) -> list[list]:
    pts = cur_points if cur_points is not None else event_points(td, year)
    tot: dict[str, float] = defaultdict(float)
    for row in pts.values():
        for p, v in row.items():
            tot[p] += v
    return [[p, round(v)] for p, v in sorted(tot.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0]


def active_elo(td: an.TourData, when: date) -> dict[str, dict]:
    """Ratings at `when` of players with a rated match in the last year and at least MIN_ELO_N rated matches."""
    r = td.elo_at(when)
    return {p: x for p, x in r.items() if x.get("last") and (when - an.day(x["last"])).days <= ACTIVE_DAYS
            and (x.get("n") or 0) >= MIN_ELO_N}


def build_rankings(td: an.TourData, prev_payload: dict | None = None, defend: dict | None = None,
                   race_rows: list | None = None) -> dict:
    s = td.store(td.current)
    rk = s.get("rankings") or {}
    rows = [r for r in rk.get("rows") or [] if r and r[1]]
    date_ = rk.get("date")
    prev = prev_payload or {}
    if prev.get("date") and prev.get("date") != date_:
        previous = {"date": prev.get("date"), "ranks": {r[1]: r[0] for r in prev.get("official") or []}}
    else:
        previous = prev.get("previous") or {}
    pr = previous.get("ranks") or {}
    official = [[int(r[0]), r[1], an.inum(r[2]) if len(r) > 2 else None,
                 (pr[r[1]] - int(r[0])) if r[1] in pr else None] for r in rows]
    when = td.today + timedelta(days=1)
    act = active_elo(td, when)
    order = sorted(act, key=lambda p: -act[p]["all"])[:200]
    elo_rows = [[i + 1, p, round(act[p]["all"], 1), {k: round(act[p][k], 1) for k in an.SURFACES}] for i, p in enumerate(order)]
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "date": date_, "source": rk.get("source"),
            "official": official, "elo": elo_rows, "race": race_rows if race_rows is not None else race(td, td.current),
            "to_defend": defend if defend is not None else to_defend(td), "previous": previous,
            "notes": ["Race and points to defend count Slams, the Finals, Masters / 1000s, 500s and 250s only "
                      "(no qualifying, Challenger / WTA 125 points, no best-of-N rule)."]}


def build_elo(td: an.TourData, history_top: int = 100, history_years: int = 5) -> dict:
    when = td.today + timedelta(days=1)
    act = active_elo(td, when)
    order = sorted(act, key=lambda p: -act[p]["all"])
    rank = {p: i + 1 for i, p in enumerate(order)}
    current = {p: {"all": round(act[p]["all"], 1), "hard": round(act[p]["hard"], 1), "clay": round(act[p]["clay"], 1),
                   "grass": round(act[p]["grass"], 1), "n": act[p].get("n"), "rank": rank[p]} for p in order}
    # game-share Elo [all, hard, clay, grass] (the blend's third term; the H2H page prices with it)
    try:
        gr = td.gelo_at(when)
        for p in order:
            g = gr.get(p)
            if g:
                current[p]["g"] = [round(float(g[k]), 4) for k in ("all", "hard", "clay", "grass")]
    except Exception:  # noqa: BLE001
        pass
    # all-time peaks: each player's best rating (post-match) on each scale, with at least 20 rated matches
    best: dict[str, dict[str, tuple]] = {k: {} for k in ("all", "hard", "clay", "grass")}
    for g in td.elo.get("rows") or []:
        for pid, ai, si, n in ((g[2], 13, 14, g[17]), (g[3], 15, 16, g[18])):
            if (n or 0) < 20:
                continue
            a = an.fnum(g[ai])
            if a is not None and a > best["all"].get(pid, (-1e9,))[0]:
                best["all"][pid] = (a, g[1][:10])
            sv = an.fnum(g[si])
            srf = g[4] if g[4] in best else "hard"
            if sv is not None and sv > best[srf].get(pid, (-1e9,))[0]:
                best[srf][pid] = (sv, g[1][:10])
    peaks = {k: [[p, round(v[0], 1), v[1]] for p, v in sorted(d.items(), key=lambda kv: -kv[1][0])[:50]] for k, d in best.items()}
    top = set(order[:history_top])
    lo = f"{td.today.year - history_years}-01-01"
    hist: dict[str, list] = defaultdict(list)
    for g in td.elo.get("rows") or []:
        if g[1] < lo:
            continue
        for pid, ai in ((g[2], 13), (g[3], 15)):
            if pid in top:
                hist[pid].append([g[1][:10], round(float(g[ai]), 1), g[4]])
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "as_of": td.today.isoformat(), "current": current,
            "peaks": peaks, "history": dict(hist), "history_from": lo,
            "params": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (td.elo_params() or {}).items()}}
