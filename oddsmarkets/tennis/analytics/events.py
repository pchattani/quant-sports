"""
Tournament payloads: data/<T>/<year>/events.json (the calendar), data/<T>/events/<event_id>.json (the
tournament page) and data/<T>/history.json (champions by event).

Draw: the store's DRAW (WTA API: seeds and entries; ATP and Slams: reconstructed from results), or one
rebuilt from a finished knockout's results (tournament_sim.bracket_from_results). Each main-draw match card
carries "node" = [round index, node index] in the bracket (round 0 = the first round of `rounds`; node k of
round r covers first-round slots k * 2^(r+1) ... (k+1) * 2^(r+1) - 1, 0-based).

Draw difficulty: with Elo at the event's start (surface blend, B's p_win), the classic bracket recursion
gives every player's chance of reaching each round; a player's opponent in round r comes from the sibling
block with probability proportional to its players' chance of reaching r. exp_opp_elo is the mean over
rounds (first round to the final) of the expected opponent's surface-blended Elo; rank 1 = hardest path.
A qualifier not yet known counts at the field's 25th-percentile rating.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import numpy as np

from oddsmarkets.tennis import analytics as an
from oddsmarkets.tennis.analytics import matches as MT

logger = logging.getLogger(__name__)
KO = ("R128", "R64", "R32", "R16", "QF", "SF", "F")


def event_matches(td: an.TourData, eid: str, year: int) -> list[dict]:
    return [m for m in td.matches(year).values() if m.get("event") == eid]


def runner_up(ev: dict, ms: list[dict]) -> str | None:
    f = [m for m in ms if m.get("round") == "F" and m.get("winner") and m.get("status") in an.FINISHED]
    if not f:
        return None
    m = f[0]
    return m["p2"] if str(m["p1"]) == str(m["winner"]) else m["p1"]


def events_year(td: an.TourData, year: int, pages: set[str] | None = None) -> dict:
    """data/<T>/<year>/events.json: {"ok","tour","year","updated_at","events": {event_id: {name, tid, level, surface, indoor, start, end, status, champion,
    runner_up, draw_size, city, country, n_matches, page}}} in date order ("page": an event page exists)."""
    by: dict[str, list[dict]] = defaultdict(list)
    for m in td.matches(year).values():
        by[m.get("event")].append(m)
    out = {}
    for eid, ev in sorted(td.events(year).items(), key=lambda kv: (str(kv[1].get("start") or ""), kv[0])):
        ms = by.get(eid) or []
        out[eid] = {"name": ev.get("name"), "tid": ev.get("tid"), "level": ev.get("level"), "surface": ev.get("surface"),
                    "indoor": bool(ev.get("indoor")), "start": ev.get("start"), "end": ev.get("end"), "status": ev.get("status"),
                    "champion": ev.get("champion"), "runner_up": runner_up(ev, ms), "draw_size": ev.get("draw_size"),
                    "city": ev.get("city"), "country": ev.get("country"), "n_matches": sum(1 for m in ms if m.get("round") not in ("Q1", "Q2", "Q3")),
                    "page": bool(pages and eid in pages)}
    return {"ok": True, "tour": td.tour, "year": int(year), "updated_at": an.now(), "events": out}


def favourites(td: an.TourData) -> dict:
    """data/<T>/favourites.json (round 9, the Draws calendar's cards): for every tour-level event of every year on file,
    our top-rated entrant going in: the entrant with the highest surface-blended Elo (w_surf x surface + (1 - w_surf) x
    overall) before their first match of the event, read from the Elo history's pre-match ratings, so nothing from the
    event itself (or later) enters. {"ok", "tour", "events": {event_id: [pid, blended Elo, entrants rated]}}."""
    w = float(td.elo_params().get("w_surf", 0.5))
    out: dict[str, list] = {}
    for y in td.years:
        by: dict[str, list[dict]] = defaultdict(list)
        for m in td.matches(y).values():
            by[m.get("event")].append(m)
        for eid, ev in td.events(y).items():
            if str(ev.get("level")) not in an.TOUR_LEVELS:
                continue
            ms = sorted(by.get(eid) or [], key=lambda m: (str(m.get("date") or ""), an.ROUND_ORDER.get(m.get("round"), 5)))
            first: dict[str, float] = {}
            for m in ms:
                g = td.elo_row(m.get("id"))
                if g is None:
                    continue
                for pid, ai, si in ((str(g[2]), 8, 9), (str(g[3]), 10, 11)):
                    if pid not in first and g[ai] is not None and g[si] is not None:
                        first[pid] = w * float(g[si]) + (1 - w) * float(g[ai])
            main = {str(p) for m in ms if m.get("round") not in ("Q1", "Q2", "Q3") for p in (m.get("p1"), m.get("p2")) if p}
            cand = {p: v for p, v in first.items() if p in main}
            if len(cand) < 4:
                continue
            fav = max(cand, key=lambda p: cand[p])
            out[eid] = [fav, round(cand[fav], 1), len(cand)]
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "w_surf": w, "events": out}


def history(td: an.TourData) -> dict:
    """{"events": {tid: {"name","level","surface","champions": [[year, pid, runner_up]]}}} for tour-level events."""
    out: dict[str, dict] = {}
    for y in td.years:
        by: dict[str, list[dict]] = defaultdict(list)
        for m in td.matches(y).values():
            if m.get("round") == "F":
                by[m.get("event")].append(m)
        for eid, ev in td.events(y).items():
            if str(ev.get("level")) not in an.TOUR_LEVELS:
                continue
            tid = ev.get("tid") or eid.rsplit("-", 1)[0]
            rec = out.setdefault(tid, {"name": ev.get("name"), "level": ev.get("level"), "surface": ev.get("surface"), "champions": []})
            rec.update({"name": ev.get("name") or rec["name"], "level": ev.get("level") or rec["level"],
                        "surface": ev.get("surface") or rec["surface"]})
            if ev.get("champion"):
                rec["champions"].append([int(y), ev["champion"], runner_up(ev, by.get(eid) or [])])
    for rec in out.values():
        rec["champions"].sort(key=lambda r: -r[0])
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "events": dict(sorted(out.items()))}


# ---------------------------------------------------------------------------------------------- the draw

def draw_of(ev: dict, ms: list[dict]) -> dict | None:
    from oddsmarkets.tennis.models import tournament_sim as TS
    d = ev.get("draw")
    if d and d.get("slots"):
        return d
    try:
        return TS.bracket_from_results(ms)
    except Exception:  # noqa: BLE001
        return None


def bracket(d: dict | None) -> tuple[list, int, list[str]]:
    """(leaves, size, round names) of a DRAW."""
    from oddsmarkets.tennis.models import _points
    from oddsmarkets.tennis.models import tournament_sim as TS
    if not d:
        return [], 0, []
    leaves, _, size = TS.draw_leaves(d)
    return leaves, size, _points.round_names(size)


def nodes(ms: list[dict], leaves: list, rounds: list[str]) -> dict[str, list[int]]:
    pos = {p: i for i, p in enumerate(leaves) if p and not str(p).startswith("tbd:")}
    out = {}
    for m in ms:
        r = m.get("round")
        if r not in rounds:
            continue
        ri = rounds.index(r)
        i = pos.get(m.get("p1"))
        j = pos.get(m.get("p2"))
        k = i if i is not None else j
        if k is None:
            continue
        out[m["id"]] = [ri, k >> (ri + 1)]
    return out


def draw_difficulty(td: an.TourData, ev: dict, leaves: list) -> dict[str, dict]:
    from oddsmarkets.tennis.models import elo as E
    S = len(leaves)
    if S < 4:
        return {}
    start = an.day(ev.get("start")) or td.today
    rt = td.elo_at(min(start, td.today + timedelta(days=1)))
    prm = td.elo_params()
    surf = ev.get("surface") if ev.get("surface") in an.SURFACES else "hard"
    bo = int(ev.get("best_of") or 3)
    w = float(prm.get("w_surf", 0.5))
    real = [p for p in leaves if p and not str(p).startswith("tbd:")]
    if len(real) < 4:
        return {}
    def blend(p):
        r = rt.get(p)
        return None if not r else w * r[surf] + (1 - w) * r["all"]
    bl = {p: blend(p) for p in real}
    known = sorted(v for v in bl.values() if v is not None)
    q25 = known[len(known) // 4] if known else 1500.0
    rating = np.array([np.nan if not p else (q25 if (str(p).startswith("tbd:") or bl.get(p) is None) else bl[p])
                       for p in leaves])
    present = np.isfinite(rating)
    rec = {p: (rt.get(p) or {}) for p in real}
    P = np.zeros((S, S))
    for i in range(S):
        if not present[i]:
            continue
        for j in range(S):
            if i != j and present[j]:
                pi, pj = leaves[i], leaves[j]
                if str(pi).startswith("tbd:") or str(pj).startswith("tbd:") or not rec.get(pi) or not rec.get(pj):
                    P[i, j] = 1.0 / (1.0 + 10 ** (-(rating[i] - rating[j]) / 400.0))
                else:
                    P[i, j] = float(E.p_win(rec[pi], rec[pj], surf, bo, prm))
    R = int(np.log2(S))
    reach = present.astype(float)
    opp_e = np.zeros(S)
    opp_n = np.zeros(S)
    for r in range(R):
        blk = 2 ** r
        nxt = reach.copy()
        for i in range(S):
            if reach[i] <= 0:
                continue
            sib0 = ((i // blk) ^ 1) * blk
            sib = range(sib0, sib0 + blk)
            wsum = sum(reach[j] for j in sib)
            if wsum <= 0:
                continue                                          # a bye
            opp_e[i] += sum(reach[j] * rating[j] for j in sib) / wsum
            opp_n[i] += 1
            nxt[i] = reach[i] * sum(reach[j] * P[i, j] for j in sib) / wsum   # the sibling block has one survivor
        reach = nxt
    out = {}
    for i, p in enumerate(leaves):
        if p and not str(p).startswith("tbd:") and opp_n[i] > 0:
            out[p] = opp_e[i] / opp_n[i]
    order = sorted(out, key=lambda p: -out[p])
    return {p: {"exp_opp_elo": round(out[p], 1), "rank": k + 1} for k, p in enumerate(order)}


# ---------------------------------------------------------------------------------------------- the page

def event_awards(td: an.TourData, ms: list[dict], preds: dict) -> dict:
    fin = [m for m in ms if m.get("status") in an.PLAYED and m.get("winner") and m.get("round") not in ("Q1", "Q2", "Q3")]
    if not fin:
        return {}
    woe: dict[str, float] = defaultdict(float)
    games: dict[str, list] = defaultdict(lambda: [0, 0, 0])
    tbw: dict[str, list] = defaultdict(lambda: [0, 0])
    for m in fin:
        p = (preds.get(m["id"]) or {}).get("p1_win")
        if p is None:
            p = td.elo_pre(m)
        w = m["winner"]
        l_ = m["p2"] if str(m["p1"]) == str(w) else m["p1"]
        if p is not None:
            pw = p if str(m["p1"]) == str(w) else 1 - p
            woe[w] += 1 - pw
            woe[l_] -= 1 - pw
        for a, b in an.set_pairs(m):
            g1, g2 = (a, b) if str(m["p1"]) == str(w) else (b, a)
            games[w][0] += g1
            games[w][1] += g2
            games[l_][0] += g2
            games[l_][1] += g1
            if {a, b} == {7, 6}:
                tw = m["p1"] if a > b else m["p2"]
                tl = m["p2"] if a > b else m["p1"]
                tbw[tw][0] += 1
                tbw[tl][1] += 1
        games[w][2] += 1
    out = {}
    if woe:
        p = max(woe, key=lambda k: woe[k])
        out["player"] = {"pid": p, "wins_over_exp": round(woe[p], 2)}
    dom = {p: g[0] / (g[0] + g[1]) for p, g in games.items() if g[2] >= 2 and g[0] + g[1] > 0}
    if dom:
        p = max(dom, key=lambda k: dom[k])
        out["dominant"] = {"pid": p, "games_share": round(dom[p], 3), "wins": games[p][2]}
    if tbw:
        p = max(tbw, key=lambda k: (tbw[k][0] - tbw[k][1], tbw[k][0]))
        if tbw[p][0] > 0:
            out["clutch"] = {"pid": p, "tb_w": tbw[p][0], "tb_l": tbw[p][1]}
    return out


def upsets(ms: list[dict], preds: dict, td: an.TourData, cut: float = 0.4, top: int = 10) -> list[dict]:
    out = []
    for m in ms:
        if m.get("status") not in an.PLAYED or not m.get("winner") or m.get("round") in ("Q1", "Q2", "Q3"):
            continue
        p = (preds.get(m["id"]) or {}).get("p1_win")
        basis = "model"
        if p is None:
            p, basis = td.elo_pre(m), "elo"
        if p is None:
            continue
        pw = p if str(m["p1"]) == str(m["winner"]) else 1 - p
        if pw < cut:
            l_ = m["p2"] if str(m["p1"]) == str(m["winner"]) else m["p1"]
            out.append({"match": m["id"], "round": m.get("round"), "winner": m["winner"], "loser": l_, "p": an.prob(pw),
                        "score": an.score_text(m, flip=str(m["p1"]) != str(m["winner"])), "basis": basis})
    return sorted(out, key=lambda r: r["p"])[:top]


def _sim_out(sim: dict | None) -> dict | None:
    if not sim or not sim.get("ok") or not sim.get("players"):
        return None
    pl = {}
    for p, r in sim["players"].items():
        x = {k: an.prob(r.get(k)) for k in ("p_title", "p_final", "p_sf", "p_qf")}
        x["reach"] = {k: an.prob(v) for k, v in (r.get("reach") or {}).items()}
        x["exp_points"] = an.rnd(r.get("exp_points"), 1)
        if r.get("next"):
            x["next"] = r["next"]
        for k in ("group", "p_group_top2"):
            if k in r:
                x[k] = r[k]
        pl[p] = x
    return {"players": dict(sorted(pl.items(), key=lambda kv: -(kv[1]["p_title"] or 0))), "n_sims": sim.get("n_sims"),
            "format": sim.get("format"), "matches": sim.get("matches") or {}, "rounds": sim.get("rounds")}


# ---------------------------------------------------------------------------------------------- before the first ball

PRE_VERSION = 1
PRE_SIMS = 4000
QROUNDS = ("Q1", "Q2", "Q3")


def pre_event_day(ev: dict, ms: list[dict]) -> date | None:
    """The day the event began: its start date, or its first match (qualifying included) if that came earlier. The
    pre-event chances use only matches dated before this day."""
    s = an.day(ev.get("start"))
    days = [d for d in (an.day(m.get("date")) for m in ms) if d is not None and (s is None or abs((d - s).days) <= 60)]
    cand = [d for d in days + [s] if d is not None]
    return min(cand) if cand else None


def pre_event_contexts(td: an.TourData, wants: dict[date, set[str]]) -> dict[date, Any]:
    """{day: predict.Context as it stood before that day} for the players in wants[day], from data dated before the day
    only, with every term of the live blend, as the tournament backtest's "pre" checkpoint builds it
    (models/backtest.py tournaments): Elo and the game-share Elo before the day, the serve/return fit at the month
    checkpoint (through the last day of the month before, as finished matches are priced), the market-rating and
    schedule states before the first match on or after the day (one pass each for all the days), and future rounds on
    an assumed schedule. A day whose serve/return checkpoint is beyond this run's refit
    budget maps to None (a later, warmer run fills it)."""
    from oddsmarkets.tennis.models import _io
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import predict as P
    from oddsmarkets.tennis.models import serve_return as SR
    blend = P.blend_params(td.tour)
    by_ord = {d.toordinal(): ps for d, ps in wants.items()}
    msnap, mprm = {}, None
    if blend.get("w_mr"):
        from oddsmarkets.tennis.models import mrating as MRt
        mprm = MRt.params(td.tour)
        msnap = MRt.snapshots(MRt.prepare(sorted(td.rated_matches(), key=_io.match_key), max_margin=mprm["max_margin"]),
                              mprm, by_ord)
    xsnap = {}
    if blend.get("w_x"):
        from oddsmarkets.tennis.models import sched as SC
        xsnap = SC.snapshots(td.all_matches(), td.elo, by_ord)
    out: dict = {}
    for d in sorted(wants):
        # the serve/return fit at the month checkpoint, as a finished match's pre-match chance uses (matches.predictions):
        # fitted through the last day of the month before, so nothing from the event enters and the fit is cached
        day_before = MT.checkpoint(d) - timedelta(days=1)
        sr = td.sr_fit(day_before)
        if sr is None and day_before.isoformat() in td.sr_skipped:
            out[d] = None
            continue
        gr = gp = None
        if blend.get("w_gelo"):
            gr, gp = td.gelo_at(d), td.gelo.get("params")
        out[d] = P.Context(td.tour, d, elo_ratings=td.elo_at(d), elo_params=td.elo_params(), elo_mod=E, sr_model=sr,
                           sr_mod=SR if sr else None, gelo_ratings=gr, gelo_params=gp,
                           mr_states=(msnap.get(d.toordinal()) or {}) if mprm else None, mr_params=mprm,
                           sched=(xsnap.get(d.toordinal()) or {}) if blend.get("w_x") else None, assumed=True)
    return out


def pre_event_draw(d: dict, ms: list[dict]) -> tuple[dict, dict[str, str]]:
    """The draw as it stood before the first ball: a slot whose player came through qualifying here (or whose entry is
    Q / LL) is an unknown qualifier ("tbd:<slot>"). -> (draw, {pid: "tbd:<slot>"})."""
    qual = {str(p) for m in ms if m.get("round") in QROUNDS for p in (m.get("p1"), m.get("p2")) if p}
    slots, tbd = [], {}
    for s in d.get("slots") or []:
        s = list(s) + [None] * max(0, 4 - len(s))
        pid, entry = s[1], s[3]
        if (pid and str(pid) in qual) or entry in ("Q", "LL"):
            if pid:
                tbd[str(pid)] = f"tbd:{s[0]}"
            slots.append([s[0], None, None, "Q"])
        else:
            slots.append(s[:4])
    return {"size": d.get("size"), "slots": slots}, tbd


def _pre_setup(td: an.TourData, ev: dict, ms: list[dict], n: int) -> tuple | None:
    """(day, event for the simulation, {pid: "tbd:<slot>"}, cache path, cache key) or None when there is nothing to
    simulate (not begun, no draw)."""
    from oddsmarkets.tennis.models import _io
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import gelo as G
    from oddsmarkets.tennis.models import mrating as MRt
    from oddsmarkets.tennis.models import predict as P
    from oddsmarkets.tennis.models import sched as SC
    from oddsmarkets.tennis.models import serve_return as SR
    from oddsmarkets.tennis.models import tournament_sim as TS
    when = pre_event_day(ev, ms)
    if when is None or when > td.today:
        return None
    d = draw_of(ev, ms)
    if not d or not d.get("slots"):
        return None
    draw, tbd = pre_event_draw(d, ms)
    if sum(1 for s in draw["slots"] if s[1]) < 2:
        return None
    ev2 = dict(ev, tour=td.tour, draw=draw)
    if TS.is_round_robin(ev, ms):
        ev2["groups"] = TS._groups(ev, ms)          # the groups are set before a ball; no result is used
    key = an.digest(PRE_VERSION, E.VERSION, SR.VERSION, P.VERSION, G.VERSION, MRt.VERSION, SC.VERSION,
                    _io.fits_signature(td.tour), when.isoformat(), n, draw, ev2.get("groups"))
    path = _io.cache_root() / "ace_pre_event" / f"{td.tour}-{an.fname(str(ev.get('id')))}.json"
    return when, ev2, tbd, path, key


def pre_events(td: an.TourData, year: int, n: int = PRE_SIMS) -> dict[str, dict]:
    """{event_id: pre-event chances} for the year's tour-level events that have begun: our title chances before the
    first ball, walk-forward (round 10, 13 Nov 2026). The tournament simulation runs over the draw as it stood
    (qualifiers unknown), with no result fixed and the model as it stood the day before (pre_event_contexts). Kept on
    the event page once play begins, as a match page keeps its pre-match chance.

    Each: {"asof": the day the event began (only matches dated before it enter), "n_sims", "title": {pid | "tbd:<slot>":
    p}, "final": {...}, "qualifier": {pid: "tbd:<slot>"} (a player who came through qualifying holds that slot's
    chance)}. Cached per event under ACE_CACHE (ace_pre_event/<tour>-<event_id>.json), keyed on the code and fit
    versions, the day, the draw and the groups: computed once, then fixed while the event plays out. An event whose
    model checkpoint is not ready is left out and not cached (a later run fills it). Memoised on `td` per year."""
    from oddsmarkets.tennis.models import _io
    from oddsmarkets.tennis.models import tournament_sim as TS
    memo = td.__dict__.setdefault("_pre_events", {})
    if year in memo:
        return memo[year]
    by: dict[str, list[dict]] = defaultdict(list)
    for m in td.matches(year).values():
        by[m.get("event")].append(m)
    out: dict[str, dict] = {}
    todo: list = []
    for eid, ev in td.events(year).items():
        if str(ev.get("level")) not in an.TOUR_LEVELS:
            continue
        ms = by.get(eid) or []
        if not (str(ev.get("status")) in ("live", "done") or any(m.get("status") in an.FINISHED or m.get("status") == "live" for m in ms)):
            continue
        try:
            st = _pre_setup(td, dict(ev, id=eid), ms, n)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s pre-event setup failed: %s", td.tour, eid, exc)
            continue
        if st is None:
            continue
        when, ev2, tbd, path, key = st
        hit = _io.read_json(path)
        res = hit.get("result") if isinstance(hit, dict) and hit.get("key") == key else None
        if res:
            out[eid] = dict(res, qualifier=tbd) if tbd else dict(res)
        else:
            todo.append((eid, when, ev2, tbd, path, key))
    if todo:
        wants: dict[date, set[str]] = defaultdict(set)
        for _, when, ev2, _, _, _ in todo:
            wants[when].update(str(s[1]) for s in (ev2.get("draw") or {}).get("slots") or [] if s[1])
        try:
            ctxs = pre_event_contexts(td, wants)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s pre-event contexts failed: %s", td.tour, year, exc)
            ctxs = {}
        for eid, when, ev2, tbd, path, key in todo:
            ctx = ctxs.get(when)
            if ctx is None:
                continue
            try:
                sim = TS.simulate(ev2, n=n, matches=[], tour=td.tour, ctx=ctx, conditional=False)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s %s pre-event simulation failed: %s", td.tour, eid, exc)
                continue
            if not sim.get("ok", True) or not sim.get("players"):
                continue
            pl = sim["players"]
            res = {"asof": when.isoformat(), "n_sims": n,
                   "title": {p: an.prob(r.get("p_title")) for p, r in pl.items() if (r.get("p_title") or 0) > 0},
                   "final": {p: an.prob(r.get("p_final")) for p, r in pl.items() if (r.get("p_final") or 0) > 0}}
            _io.write_json(path, {"key": key, "result": res})
            out[eid] = dict(res, qualifier=tbd) if tbd else dict(res)
        logger.info("%s %s pre-event chances: %d computed, %d from cache", td.tour, year, sum(1 for t in todo if t[0] in out),
                    len(out) - sum(1 for t in todo if t[0] in out))
    memo[year] = out
    return out


def simulate(td: an.TourData, ev: dict, ms: list[dict], n: int, ctx=None) -> dict | None:
    from oddsmarkets.tennis.models import tournament_sim as TS
    try:
        r = TS.simulate(dict(ev, tour=td.tour), n=n, matches=ms, tour=td.tour, ctx=ctx or td.today_context())
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s %s simulation failed: %s", td.tour, ev.get("id"), exc)
        return None
    return r if r.get("ok", True) and r.get("players") else None


def build_event(td: an.TourData, eid: str, year: int, preds: dict | None = None, sim: dict | None = None,
                market: dict | None = None, hist: dict | None = None, markets_m: dict | None = None) -> dict:
    ev = dict(td.events(year).get(eid) or {}, id=eid)
    ms = event_matches(td, eid, year)
    preds = preds or {}
    d = draw_of(ev, ms)
    leaves, size, rounds = bracket(d)
    if any(m.get("round") == "RR" for m in ms) or str(ev.get("level")) == "finals":
        rounds = ["RR", "SF", "F"]
    main = [m for m in ms if m.get("round") not in ("Q1", "Q2", "Q3")]
    nd = nodes(main, leaves, rounds) if leaves else {}
    cards = {}
    for m in sorted(main, key=lambda m: (an.ROUND_ORDER.get(m.get("round"), 5), str(m.get("date") or ""))):
        c = MT.card(td, m, preds.get(m["id"]), (markets_m or {}).get(m["id"]))
        if m["id"] in nd:
            c["node"] = nd[m["id"]]
        # the rankings the two held going in (the result row's), so a played match never shows today's ranking
        if m.get("status") != "upcoming" and (m.get("rank1") or m.get("rank2")):
            c["rk"] = [m.get("rank1"), m.get("rank2")]
        cards[m["id"]] = c
    qual = [MT.card(td, m, preds.get(m["id"]), light=True) for m in ms if m.get("round") in ("Q1", "Q2", "Q3")]
    results = [cards[m["id"]] for m in sorted(main, key=lambda m: (str(m.get("date") or ""), an.ROUND_ORDER.get(m.get("round"), 5)),
                                               reverse=True) if m.get("status") in an.FINISHED]
    tid = ev.get("tid") or eid.rsplit("-", 1)[0]
    hrec = ((hist or {}).get("events") or {}).get(tid) or {}
    slots = [list(s) for s in (d or {}).get("slots") or []]
    meta = {k: ev.get(k) for k in ("name", "tid", "year", "level", "surface", "indoor", "start", "end", "status", "champion",
                                   "draw_size", "best_of", "city", "country")}
    meta.update(id=eid, runner_up=runner_up(ev, ms), round_now=round_now(main))
    # our title chances before the first ball, kept once play begins (this season's events; see pre_event)
    pre = None
    if int(year) == int(td.current):
        try:
            pre = pre_events(td, int(year)).get(eid)
        except Exception as exc:  # noqa: BLE001 - the page stands without it
            logger.warning("%s %s pre-event chances failed: %s", td.tour, eid, exc)
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "event": meta,
            "draw": {"rounds": rounds, "size": size, "slots": slots, "source": (d or {}).get("source") or ("results" if d else None),
                     "complete": (d or {}).get("complete"), "matches": cards},
            "sim": _sim_out(sim), "pre": pre, "market": market, "results": results, "qualifying": qual,
            "upsets": upsets(ms, preds, td), "draw_difficulty": draw_difficulty(td, ev, leaves) if leaves else {},
            "awards": event_awards(td, ms, preds), "history": hrec.get("champions") or [],
            "names": {p: td.short(p) for p in {x for m in ms for x in (m.get("p1"), m.get("p2")) if x}}}


def round_now(ms: list[dict]) -> str | None:
    """The earliest round with an unfinished match, else the last round played."""
    open_ = [m.get("round") for m in ms if m.get("status") in ("live", "upcoming") and m.get("round") in an.ROUND_ORDER]
    if open_:
        return min(open_, key=lambda r: an.ROUND_ORDER[r])
    done = [m.get("round") for m in ms if m.get("round") in an.ROUND_ORDER]
    return max(done, key=lambda r: an.ROUND_ORDER[r]) if done else None
