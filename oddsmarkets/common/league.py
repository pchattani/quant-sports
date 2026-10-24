"""The league pages' "how the race is shaping up" and "strengths and weaknesses" block: one implementation for the US
sport sites (Rink, Hardwood, Gridiron, Bullpen), written into each season payload as `season.json["league"]` and drawn
by the kit's league module (docs/_design/league.js, QKL).

What it holds, for the front end to word and draw:
    history   a summary of the race log (data/.../race_log.json): our playoff / division / title chances, one snapshot a
              day since the site began keeping them, and before that snapshots rebuilt from the season simulation run
              as of earlier dates (only the results known on each date; the rebuilt dates are listed)
    movers    the biggest risers and fallers over about a week, each with the reason: the team's own results, its
              rivals' results, the schedule left
    games     the games that matter most for the race in the next seven days: the swing in a team's chance between a
              win and a loss in its next game (the simulation's interventional if_win / if_loss), else the shared
              significance rule's stakes (oddsmarkets/common/featured.py)
    race      per team: the magic / elimination numbers (deterministic, from the simulation module), clinched or out
              in every simulation, the strength of the schedule left from our ratings (and its rank), the next game
    teams     per team: percentiles on the sport's team set (docs/_design/metrics/<sport>.json), plain-English chips
              ("Top-3 defence", "Power play is the weak spot", "Winning close games: luck?"), the tier, the luck line
              (record against the record the scoring deserved), the quadrant point (offence, defence)
    tiers     contenders, playoff-bound, on the bubble, long shots, rebuilding (or the postseason's own tiers)

No look-ahead. The live snapshots are taken at each build and never revised; a rebuilt snapshot for date D comes from
the simulation with `through=D` (results before D only, ratings fitted through D). Everything is stdlib so the four
builders and the tests can call it without a sport.

The race log ({season: {metric: {"YYYY-MM-DD": {key: p}}, "_meta": {"rebuilt": [days], "n": sims}}}) is a persistent
CI log like chance_log.json (scripts/ci_site.py LOGS): each build starts from the previous deploy's copy.
"""
from __future__ import annotations

import math
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable

from oddsmarkets.common import digest as DG

V = 1
META = "_meta"


# ───────────────────────────────────────────────────────────── small helpers
def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _day(x) -> str | None:
    """'YYYY-MM-DD' from a date, datetime or ISO string; None when unreadable."""
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date().isoformat()
    if isinstance(x, date):
        return x.isoformat()
    s = str(x).strip()
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else None


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _r(x, k=3):
    v = _num(x)
    return None if v is None else round(v, k)


def _sig(x, digits: int = 4):
    """A number rounded to about `digits` significant figures (payload size)."""
    v = _num(x)
    if v is None or v == 0:
        return v
    return round(v, max(0, digits - 1 - int(math.floor(math.log10(abs(v))))))


def ordinal(n: int) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


# ───────────────────────────────────────────────────────────── the race log
def race_season(log: dict | None, season) -> dict:
    """The race log of one season ({metric: {day: {key: p}}, "_meta": {...}}), a fresh copy; {} when absent."""
    s = (log or {}).get(str(season)) if isinstance(log, dict) else None
    if not isinstance(s, dict):
        return {}
    out = {m: dict(v) for m, v in s.items() if isinstance(v, dict) and m != META}
    meta = s.get(META) if isinstance(s.get(META), dict) else {}
    out[META] = {"rebuilt": sorted(set(meta.get("rebuilt") or [])), **{k: v for k, v in meta.items() if k != "rebuilt"}}
    return out


def roll_race(seas: dict, day, current: dict, digits: int = 3) -> dict:
    """Add this build's snapshot (current {metric: {key: p}}) for `day` to one season's race log. One snapshot a day
    (a later build the same day replaces it, and replaces a rebuilt snapshot for that day); nothing is trimmed."""
    day = _day(day)
    out = {m: dict(v) for m, v in (seas or {}).items() if m != META}
    meta = dict((seas or {}).get(META) or {})
    reb = set(meta.get("rebuilt") or [])
    wrote = False
    for m, cur in (current or {}).items():
        snap = {str(k): round(float(v), digits) for k, v in (cur or {}).items() if _num(v) is not None}
        if snap and day:
            out.setdefault(m, {})[day] = snap
            wrote = True
    if wrote and day in reb:
        reb.discard(day)
    if wrote and day:
        meta["live_from"] = min([d for d in [meta.get("live_from"), day] if d])
    meta["rebuilt"] = sorted(reb)
    out[META] = meta
    return out


def add_rebuilt(seas: dict, day, chances: dict, n: int | None = None, digits: int = 3) -> dict:
    """A snapshot rebuilt from the simulation as of `day` (through=day: results before that date). It never replaces
    a live snapshot; `day` is listed in _meta.rebuilt."""
    day = _day(day)
    out = {m: dict(v) for m, v in (seas or {}).items() if m != META}
    meta = dict((seas or {}).get(META) or {})
    reb = set(meta.get("rebuilt") or [])
    live = {d for m, v in out.items() for d in v} - reb
    if day is None or day in live:
        return dict(out, **{META: dict(meta, rebuilt=sorted(reb))})
    for m, cur in (chances or {}).items():
        snap = {str(k): round(float(v), digits) for k, v in (cur or {}).items() if _num(v) is not None}
        if snap:
            out.setdefault(m, {})[day] = snap
    reb.add(day)
    meta["rebuilt"] = sorted(reb)
    if n:
        meta["n"] = int(n)
    out[META] = meta
    return out


def rebuild_dates(first_day, live_from, step_days: int, also: Iterable | None = None) -> list[str]:
    """The dates to rebuild before live tracking began: the first game day (the preseason baseline: nothing played),
    then every `step_days`, strictly before `live_from` (the first live snapshot; today when there is none), plus any
    `also` dates in that window (e.g. the NFL's Tuesdays)."""
    f, lf = _day(first_day), _day(live_from)
    if not f or not lf or f >= lf:
        return []
    out, d = [], _d(f)
    end = _d(lf)
    while d < end:
        out.append(d.isoformat())
        d += timedelta(days=max(1, int(step_days)))
    for a in also or []:
        a = _day(a)
        if a and f <= a < lf:
            out.append(a)
    return sorted(set(out))


def backfill(seas: dict, dates: Iterable[str], run_asof: Callable[[str], dict | None], budget_s: float = 90.0,
             n: int | None = None, clock: Callable[[], float] = time.perf_counter) -> tuple[dict, list[str]]:
    """Rebuild the missing `dates` (oldest first) with run_asof(day) -> {metric: {key: p}} | None, inside a time budget
    (a build adds at most about budget_s; the next build carries on). Returns (log, the days rebuilt this call)."""
    have = {d for m, v in (seas or {}).items() if m != META for d in v}
    todo = [d for d in sorted(set(dates or [])) if d not in have]
    t0, done = clock(), []
    for d in todo:
        if done and clock() - t0 > budget_s:
            break
        try:
            ch = run_asof(d)
        except Exception:                      # noqa: BLE001 - a failed date is skipped, the next build retries it
            ch = None
        if ch:
            seas = add_rebuilt(seas, d, ch, n=n)
            done.append(d)
    return seas, done


def history_summary(seas: dict, metrics: Iterable[str]) -> dict:
    """{"first", "last", "days", "live_from", "rebuilt": [days], "n"} for the front end's note ("tracking since ...")."""
    days = sorted({d for m in metrics for d in ((seas or {}).get(m) or {})})
    meta = (seas or {}).get(META) or {}
    reb = sorted(set(meta.get("rebuilt") or []) & set(days))
    live = [d for d in days if d not in reb]
    return {"first": days[0] if days else None, "last": days[-1] if days else None, "days": len(days),
            "live_from": live[0] if live else None, "rebuilt": reb, "n": meta.get("n")}


def merge_race(live: dict | None, new: dict | None) -> tuple[dict, int]:
    """CI repair (scripts/ci_site.py): the build's race log with any day the live copy had and the build lost put
    back; every season kept (a race log is the whole season, never trimmed). Returns (merged, entries restored)."""
    if not isinstance(live, dict) or not live:
        return (new if isinstance(new, dict) else {}), 0
    out = {s: (dict(v) if isinstance(v, dict) else v) for s, v in (new or {}).items()}
    lost = 0
    for s, ms in live.items():
        if not isinstance(ms, dict):
            continue
        cur = out.setdefault(s, {})
        if not isinstance(cur, dict):
            continue
        for m, days in ms.items():
            if not isinstance(days, dict):
                continue
            if m == META:
                mine = dict(cur.get(META) or {})
                reb = set(mine.get("rebuilt") or []) | set(days.get("rebuilt") or [])
                mine["rebuilt"] = sorted(reb)
                for k, v in days.items():
                    mine.setdefault(k, v)
                cur[META] = mine
                continue
            have = dict(cur.get(m) or {})
            miss = [d for d in days if d not in have]
            if miss:
                lost += len(miss)
                have.update({d: days[d] for d in miss})
                cur[m] = {d: have[d] for d in sorted(have)}
    return (out, lost) if lost else ((new if isinstance(new, dict) else {}), 0)


# ───────────────────────────────────────────────────────────── results and records
def norm_results(games: Iterable[dict]) -> list[dict]:
    """Finished games as {"date", "home", "away", "hs", "as", "ot"}: the input every function below reads. A game
    dict may carry `date` or `start`, scores as hs/as (or home_score/away_score), `ot` True for an overtime or
    shootout result (a loser's point in the NHL)."""
    out = []
    for g in games or []:
        hs, as_ = _num(g.get("hs", g.get("home_score"))), _num(g.get("as", g.get("away_score")))
        d = _day(g.get("date") or g.get("start"))
        if hs is None or as_ is None or d is None or g.get("home") is None or g.get("away") is None:
            continue
        out.append({"date": d, "home": str(g["home"]), "away": str(g["away"]), "hs": hs, "as": as_, "ot": bool(g.get("ot"))})
    out.sort(key=lambda x: x["date"])
    return out


def team_window(results: list[dict], team: str, lo: str, hi: str | None = None) -> dict:
    """A team's games with lo <= date < hi (hi None: through the end): {"w", "l", "otl", "t", "n", "games": [{date,
    opp, home, gf, ga, res: 'W'|'L'|'OTL'|'T'}]}."""
    w = l = otl = t = 0
    gs = []
    for g in results:
        if g["date"] < lo or (hi is not None and g["date"] >= hi) or team not in (g["home"], g["away"]):
            continue
        home = g["home"] == team
        gf, ga = (g["hs"], g["as"]) if home else (g["as"], g["hs"])
        if gf > ga:
            res = "W"
            w += 1
        elif gf < ga:
            res = "OTL" if g["ot"] else "L"
            if g["ot"]:
                otl += 1
            else:
                l += 1
        else:
            res = "T"
            t += 1
        gs.append({"date": g["date"], "opp": g["away"] if home else g["home"], "home": home, "gf": gf, "ga": ga, "res": res})
    return {"w": w, "l": l, "otl": otl, "t": t, "n": len(gs), "games": gs}


def record_str(x: dict, otl: bool = False) -> str:
    s = f"{x['w']}-{x['l']}"
    if otl:
        s += f"-{x['otl']}"
    elif x.get("t"):
        s += f"-{x['t']}"
    return s


def _score(gm: dict) -> str:
    a, b = int(round(gm["gf"])), int(round(gm["ga"]))
    return f"{a}-{b}"


# ───────────────────────────────────────────────────────────── movers with reasons
def mover_reasons(team: str, d: float, since: str, today: str, results: list[dict], rivals: Iterable[str],
                  abbr: dict, rating: dict | None = None, sos_rank: dict | None = None, n_teams: int = 0,
                  otl: bool = False, weekly: bool = False) -> list[str]:
    """One or two short reasons for a move of `d` since `since`: the team's results (with the best win or the worst
    loss), its rivals' results when those did more, the schedule left when it is among the hardest or easiest."""
    ab = lambda k: str(abbr.get(k, k))                                    # noqa: E731
    me = team_window(results, team, since)
    why = []
    rate = {k: _num(v) for k, v in (rating or {}).items()}
    if me["n"] == 0:
        why.append("Did not play")
    elif weekly and me["n"] == 1:
        gm = me["games"][0]
        verb = {"W": "Beat", "L": "Lost to", "OTL": "Lost in overtime to", "T": "Tied"}[gm["res"]]
        why.append(f"{verb} {ab(gm['opp'])} {_score(gm)}")
    else:
        rec = record_str(me, otl)
        wins = [g for g in me["games"] if g["res"] == "W"]
        losses = [g for g in me["games"] if g["res"] in ("L", "OTL")]
        if d > 0 and wins:
            best = max(wins, key=lambda g: (rate.get(g["opp"]) if rate.get(g["opp"]) is not None else -99, g["gf"] - g["ga"]))
            tail = f", beat {ab(best['opp'])} {_score(best)}" if me["n"] > 1 else ""
            why.append(f"Went {rec}{tail}")
        elif d < 0 and losses:
            worst = min(losses, key=lambda g: (rate.get(g["opp"]) if rate.get(g["opp"]) is not None else 99, g["gf"] - g["ga"]))
            tail = f", lost to {ab(worst['opp'])} {_score(worst)}" if me["n"] > 1 else ""
            why.append(f"Went {rec}{tail}")
        else:
            why.append(f"Went {rec}")
    # rivals: did they do more of the moving? (their combined record over the same days)
    riv = [r for r in rivals if r != team]
    if riv:
        rw = rl = 0
        for r in riv:
            x = team_window(results, r, since)
            rw += x["w"]
            rl += x["l"] + x["otl"]
        own_share = (me["w"] / me["n"]) if me["n"] else 0.5
        riv_share = rw / (rw + rl) if rw + rl else 0.5
        if rw + rl >= (2 if weekly else 4) and ((d > 0 and riv_share <= 0.4 and own_share <= 0.6) or (d < 0 and riv_share >= 0.6 and own_share >= 0.4)
                                                or me["n"] == 0):
            why.append(f"Rivals went {rw}-{rl}")
    if sos_rank and n_teams and team in sos_rank and len(why) < 2:
        rk = sos_rank[team]
        if rk <= 3 and d < 0:
            why.append("One of the hardest schedules left")
        elif rk >= n_teams - 2 and d > 0:
            why.append("One of the easiest schedules left")
    return why[:2]


def movers(seas: dict, metric: str, current: dict, now, results: list[dict], rivals_of: Callable[[str], Iterable[str]],
           abbr: dict, rating: dict | None = None, sos_rank: dict | None = None, k: int = 3, days: int = 7,
           min_move: float = 0.02, otl: bool = False, weekly: bool = False) -> dict | None:
    """The biggest risers and fallers in `metric` since the snapshot nearest `days` ago (digest.movers on the race
    log), each with its reasons: {"metric", "since", "days", "up": [{"team", "p", "d", "why"}], "down": [...]}."""
    # a weekly sport compares with a snapshot at least six days old, so the window holds a full round of games
    mv = DG.movers((seas or {}).get(metric), current, now, days=days, k=k, min_move=min_move, min_days=6 if weekly else 1)
    if not mv:
        return None
    today = DG._now(now).date().isoformat()
    n_teams = len(current or {})
    for side in ("up", "down"):
        for r in mv[side]:
            r["team"] = str(r.pop("key"))
            r["why"] = mover_reasons(r["team"], r["d"], mv["since"], today, results, rivals_of(r["team"]), abbr, rating,
                                     sos_rank, n_teams, otl=otl, weekly=weekly)
    return dict(mv, metric=metric)


# ───────────────────────────────────────────────────────────── strength of schedule
def schedule_strength(games: Iterable[dict], rating: dict, teams: Iterable[str], hfa: float = 0.0) -> dict:
    """{team: {"avg": mean opponent rating (+hfa for road games, -hfa at home: the edge the venue gives the
    opponent), "n": games, "home": home games}} over `games` ({home, away})."""
    rate = {str(k): _num(v) for k, v in (rating or {}).items()}
    acc = {str(t): [0.0, 0, 0] for t in teams}
    for g in games or []:
        h, a = str(g.get("home")), str(g.get("away"))
        for me, op, home in ((h, a, True), (a, h, False)):
            if me not in acc or rate.get(op) is None:
                continue
            acc[me][0] += rate[op] + (-hfa if home else hfa)
            acc[me][1] += 1
            acc[me][2] += 1 if home else 0
    return {t: {"avg": round(s / n, 3) if n else None, "n": n, "home": hm} for t, (s, n, hm) in acc.items()}


def ranks(values: dict, high_first: bool = True) -> dict:
    """{key: 1-based rank} (ties share the better rank); None values are left out."""
    xs = sorted(((v, k) for k, v in values.items() if _num(v) is not None), key=lambda t: -t[0] if high_first else t[0])
    out, prev, rk = {}, None, 0
    for i, (v, k) in enumerate(xs, 1):
        if prev is None or v != prev:
            rk = i
        out[k] = rk
        prev = v
    return out


def percentiles(values: dict, higher_better: bool = True) -> dict:
    """{key: 0-100} by rank within the group (the best is 100, the worst 0; ties share the mean rank)."""
    xs = [(float(v), k) for k, v in values.items() if _num(v) is not None]
    n = len(xs)
    if n < 2:
        return {k: 50 for _, k in xs}
    xs.sort(key=lambda t: t[0])
    out, i = {}, 0
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1][0] == xs[i][0]:
            j += 1
        p = 100.0 * ((i + j) / 2) / (n - 1)
        for t in range(i, j + 1):
            out[xs[t][1]] = round(p if higher_better else 100 - p)
        i = j + 1
    return out


# ───────────────────────────────────────────────────────────── the games that matter
def matter_games(upcoming: Iterable[dict], nxt: dict, metric: str, now, days: int = 7, limit: int = 6,
                 sig: Callable[[dict], tuple[float, list]] | None = None, min_swing: float = 0.01) -> list[dict]:
    """The next `days` days' games ranked by how much they move the race.

    upcoming: [{"id", "start" (ISO), "home", "away", "p_home"}]; nxt: {team: {"game_id", "p_win", "if_win": {metric: p},
    "if_loss": {...}}} from the season simulation (a team's NEXT game only). A game's swing is the sum over its two
    sides of |if_win - if_loss| (chance points); a game the simulation holds no conditional for is ranked by
    sig(game) -> (stakes points 0-20, reasons) from featured.py, after every game with a measured swing.
    Rows: {"id", "start", "home", "away", "p_home", "swing", "sides": {team: [if_win, if_loss, now]}, "why"}."""
    n = DG._now(now)
    hi = n + timedelta(days=days)
    rows = []
    for g in upcoming or []:
        st = DG._dt(g.get("start") or g.get("date"))
        if st is None or st < n - timedelta(hours=3) or st > hi:
            continue
        gid = str(g.get("id"))
        sides, sw = {}, 0.0
        for t in (str(g.get("home")), str(g.get("away"))):
            x = (nxt or {}).get(t) or {}
            if str(x.get("game_id") or x.get("game") or "") != gid:
                continue
            a, b = _num((x.get("if_win") or {}).get(metric)), _num((x.get("if_loss") or {}).get(metric))
            if a is None or b is None:
                continue
            sides[t] = [round(a, 3), round(b, 3)]
            sw += abs(a - b)
        row = {"id": gid, "start": g.get("start") or g.get("date"), "home": str(g.get("home")), "away": str(g.get("away")),
               "p_home": _r(g.get("p_home"), 3), "swing": round(sw, 3) if sides else None, "sides": sides}
        if not sides and sig is not None:
            pts, why = sig(g)
            row["stakes"] = round(pts, 1)
            row["why"] = why
        rows.append(row)
    measured = sorted([r for r in rows if r["swing"] is not None and r["swing"] >= min_swing], key=lambda r: -r["swing"])
    rest = sorted([r for r in rows if r["swing"] is None and (r.get("stakes") or 0) > 4], key=lambda r: -(r.get("stakes") or 0))
    return (measured + rest)[:limit]


# ───────────────────────────────────────────────────────────── profiles and chips
def profile(values: dict, spec: list[dict], gp: dict | None = None, min_gp: int = 0) -> dict:
    """values {team: {metric: v}}; spec [{"id", "dir": "higher" | "lower", "model": bool}]: {team: {"pct": {id: 0-100},
    "rank": {id: 1..N (1 best)}}}. Below min_gp games only the model's ratings (spec "model": True, which carry the
    preseason prior) get a percentile: a raw rate over a handful of games is noise."""
    teams = list(values)
    early = {t: (gp or {}).get(t) is not None and (gp or {}).get(t) < min_gp for t in teams}
    allearly = bool(teams) and all(early.values())
    out = {t: {"pct": {}, "rank": {}} for t in teams}
    for m in spec:
        mid = m["id"]
        if allearly and not m.get("model"):
            continue
        col = {t: (values.get(t) or {}).get(mid) for t in teams}
        col = {t: v for t, v in col.items() if _num(v) is not None}
        if len(col) < 3:
            continue
        hb = m.get("dir", "higher") != "lower"
        pc = percentiles(col, hb)
        rk = ranks(col, high_first=hb)
        for t in col:
            out[t]["pct"][mid] = pc[t]
            out[t]["rank"][mid] = rk[t]
    return out


def chips(team: str, prof: dict, spec: list[dict], n: int, overall: str | None = None, luck: dict | None = None,
          sos_rank: int | None = None, early: bool = False, limit: int = 4) -> list[list[str]]:
    """Plain-English chips for one team: [[text, tone]] with tone "+" (a strength), "-" (a weakness), "?" (a question),
    "s" (a style, neither better nor worse). Rules, in order of priority:
        top-3 on a dimension            "Top-3 defence"          (rank <= 3 of n; the best two such; else
                                        "Strong defence" for the best dimension at the 75th percentile or higher)
        the weak spot of a decent team  "Power play is the weak spot" (the lowest dimension at or under the 30th
                                        percentile, when the overall rating is at the 40th or better)
        bottom-3 on a dimension         "Bottom-3 offence"       (when no weak-spot chip was given)
        luck                            "Winning close games: luck?" / "Record ahead of the numbers: luck?" /
                                        "Losing close games: bad luck?" / "Record trails the numbers"
        schedule                        "Toughest schedule left" / "Easiest schedule left" (rank 1-2 / last two)
        style                           "Fastest pace" / "Slowest pace" (spec "style": True, "chip" names it)
    spec rows: {"id", "chip": "defence" (the dimension's name in a sentence), "style": bool, "hi"/"lo" (style words)}."""
    p = prof.get(team) or {}
    pct, rk = p.get("pct") or {}, p.get("rank") or {}
    dims = [m for m in spec if m.get("chip") and not m.get("style") and m["id"] in pct]
    out: list[list[str]] = []
    tops = sorted([m for m in dims if rk.get(m["id"], 99) <= 3], key=lambda m: rk[m["id"]])
    for m in tops[:2]:
        out.append([f"Best {m['chip']}" if rk[m["id"]] == 1 else f"Top-3 {m['chip']}", "+"])
    if not tops:
        good = sorted([m for m in dims if pct[m["id"]] >= 75], key=lambda m: -pct[m["id"]])
        for m in good[:1]:
            out.append([f"Strong {m['chip']}", "+"])
    ov = pct.get(overall) if overall else None
    weak = sorted([m for m in dims if pct[m["id"]] <= 30], key=lambda m: pct[m["id"]])
    named = {c[0] for c in out}
    if weak and (ov is None or ov >= 40):
        w = weak[0]
        out.append([f"{w['chip'][0].upper() + w['chip'][1:]} is the weak spot", "-"])
    else:
        bots = sorted([m for m in dims if rk.get(m["id"], 0) >= n - 2], key=lambda m: -rk[m["id"]])
        for m in bots[:1]:
            txt = f"Worst {m['chip']}" if rk[m["id"]] == n else f"Bottom-3 {m['chip']}"
            if txt not in named:
                out.append([txt, "-"])
    lk = luck or {}
    if lk.get("flag") == "lucky":
        out.append(["Winning close games: luck?" if lk.get("close_good") else "Record ahead of the numbers: luck?", "?"])
    elif lk.get("flag") == "unlucky":
        out.append(["Losing close games: bad luck?" if lk.get("close_bad") else "Record trails the numbers", "?"])
    if sos_rank is not None and n:
        if sos_rank <= 2:
            out.append(["Toughest schedule left", "s"])
        elif sos_rank >= n - 1:
            out.append(["Easiest schedule left", "s"])
    for m in spec:
        if m.get("style") and m["id"] in pct and len(out) < limit:
            if rk.get(m["id"]) == 1 and m.get("hi"):
                out.append([m["hi"], "s"])
            elif rk.get(m["id"]) == n and m.get("lo"):
                out.append([m["lo"], "s"])
    if early:
        out = [c for c in out if c[1] != "?"]
    return out[:limit]


# ───────────────────────────────────────────────────────────── luck
def luck(rec: dict, threshold: float, close_min: int = 3) -> dict:
    """rec {team: {"gp", "actual", "expected", "close": [w, l]}} (actual and expected in the same unit: wins, or points
    in the NHL): {team: {"a", "x", "d" (actual - expected), "close": [w, l], "flag": "lucky" | "unlucky" | None,
    "close_good": bool}}. The flag needs |d| >= threshold."""
    out = {}
    for t, r in (rec or {}).items():
        a, x = _num(r.get("actual")), _num(r.get("expected"))
        if a is None or x is None:
            continue
        d = a - x
        cw, cl = (list(r.get("close") or []) + [0, 0])[:2]
        cn = (cw or 0) + (cl or 0)
        flag = "lucky" if d >= threshold else "unlucky" if d <= -threshold else None
        out[str(t)] = {"a": round(a, 1), "x": round(x, 1), "d": round(d, 1), "close": [int(cw or 0), int(cl or 0)], "flag": flag,
                       "close_good": bool(cn >= close_min and cw / cn >= 0.65),
                       "close_bad": bool(cn >= close_min and cw / cn <= 0.35)}
    return out


def pythag(pf: float, pa: float, gp: int, exp: float) -> float | None:
    """Pythagorean win share (pf^e / (pf^e + pa^e)); None without scoring."""
    pf, pa = _num(pf), _num(pa)
    if not gp or pf is None or pa is None or pf + pa <= 0:
        return None
    return pf ** exp / (pf ** exp + pa ** exp)


def close_record(results: list[dict], team: str, margin: float) -> list[int]:
    """[wins, losses] in games decided by `margin` or less (an overtime result counts as close)."""
    w = l = 0
    for g in results:
        if team not in (g["home"], g["away"]):
            continue
        diff = abs(g["hs"] - g["as"])
        if diff == 0 or (diff > margin and not g["ot"]):
            continue
        won = (g["hs"] > g["as"]) == (g["home"] == team)
        w += won
        l += not won
    return [w, l]


# ───────────────────────────────────────────────────────────── tiers
TIER_LABEL = {
    "contend": ("Contenders", "a real title chance"),
    "solid": ("Playoff bound", "in at least 7 seasons in 10"),
    "bubble": ("On the bubble", "in between 1 and 7 seasons in 10"),
    "long": ("Long shots", "in under 1 season in 4"),
    "rebuild": ("Rebuilding", "in under 1 season in 20"),
    "alive": ("Still alive", "in the postseason"),
    "out_po": ("Out in the postseason", "made it, then went out"),
    "missed": ("Missed the postseason", "the regular season ended there"),
    "champion": ("Champions", "won the title"),
}


def tiers(playoff: dict, title: dict, phase: str = "regular", n: int | None = None) -> list[dict]:
    """Tiers by our chances: {"key", "label", "sub", "teams": [keys, best first]}.
    In season: contenders (title >= max(5%, 1.6 / N)), playoff bound (playoffs >= 70%), on the bubble (25-70%), long
    shots (5-25%), rebuilding (< 5%). Once the postseason field is set (every playoff chance 0 or 1): still alive
    (a title chance left), out in the postseason, missed the postseason; a finished season names the champions."""
    keys = sorted(set(playoff or {}) | set(title or {}))
    n = n or len(keys) or 1
    P = {k: _num((playoff or {}).get(k)) for k in keys}
    T = {k: _num((title or {}).get(k)) or 0.0 for k in keys}
    set_ = phase in ("postseason", "complete") or (P and all(v in (0.0, 1.0) for v in P.values() if v is not None))
    groups: dict[str, list] = {}
    for k in keys:
        p, t = P[k], T[k]
        if set_:
            if t >= 0.9999 and phase == "complete":
                g = "champion"
            elif t > 0:
                g = "alive"
            elif (p or 0) >= 0.9999:
                g = "out_po"
            else:
                g = "missed"
        elif t >= max(0.05, 1.6 / n):
            g = "contend"
        elif p is None:
            continue
        elif p >= 0.70:
            g = "solid"
        elif p >= 0.25:
            g = "bubble"
        elif p >= 0.05:
            g = "long"
        else:
            g = "rebuild"
        groups.setdefault(g, []).append(k)
    order = ["champion", "alive", "out_po", "missed"] if set_ else ["contend", "solid", "bubble", "long", "rebuild"]
    out = []
    for g in order:
        if g not in groups:
            continue
        ts = sorted(groups[g], key=lambda k: (-T[k], -(P[k] or 0), k))
        out.append({"key": g, "label": TIER_LABEL[g][0], "sub": TIER_LABEL[g][1], "teams": ts})
    return out


def tier_of(tl: list[dict]) -> dict:
    return {t: x["key"] for x in tl for t in x["teams"]}


# ───────────────────────────────────────────────────────────── the block
def block(*, now, phase: str, metrics: list[dict], current: dict, seas: dict, movers_: dict | None, games: list[dict],
          race: dict, prof: dict, spec: list[dict], chips_: dict, luck_: dict, tiers_: list[dict], quad: dict | None,
          early: bool, min_gp: int | None, gp: dict | None = None, values: dict | None = None,
          notes: dict | None = None) -> dict:
    """season.json["league"] (schema v1). metrics [{"key", "label"}] (the chance metrics in the race log, playoffs
    first); current {metric: {team: p}}; race {team: {...}} (magic numbers, schedule, next game); prof from profile();
    spec the profile metrics [{"id", "label", "dir", "fmt", "unit", "style", "group", "model"}]; quad {"x": id, "y": id,
    "xName", "yName", "flipY": bool} or None."""
    teams = {}
    tof = tier_of(tiers_)
    for t in sorted(set(prof) | set(race) | set(tof)):
        p = prof.get(t) or {}
        teams[t] = {k: v for k, v in {
            "tier": tof.get(t),
            "pct": p.get("pct") or None,
            "vals": {k: _sig(v) for k, v in ((values or {}).get(t) or {}).items() if _num(v) is not None} or None,
            "chips": chips_.get(t) or None,
            "luck": luck_.get(t),
            "gp": (gp or {}).get(t),
        }.items() if v is not None}
    return {
        "v": V, "asof": DG._now(now).date().isoformat(), "phase": phase,
        "metrics": metrics,
        "current": {m["key"]: {str(t): round(float(p), 3) for t, p in ((current or {}).get(m["key"]) or {}).items() if _num(p) is not None}
                    for m in metrics},
        "history": history_summary(seas, [m["key"] for m in metrics]),
        "movers": movers_,
        "games": games,
        "race": race,
        "profile": {"metrics": spec, "min_gp": min_gp, "early": early},
        "teams": teams,
        "tiers": tiers_,
        "quad": quad,
        "notes": notes or {},
    }
