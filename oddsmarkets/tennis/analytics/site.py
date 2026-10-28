"""
Tour-wide payloads: data/<T>/players_index.json, data/<T>/lab.json, data/<T>/markets.json and the tour's
entry in data/index.json (PAYLOADS.md).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from oddsmarkets.tennis import analytics as an
from oddsmarkets.tennis.analytics import matches as MT

logger = logging.getLogger(__name__)
LAB_MIN_MATCHES = 10
LAB_MIN_SURFACE = 5
EDGE_HIDE_LEVELS = ("q",)


def players_index(td: an.TourData) -> dict:
    """{pid: [name, short, country, latest_rank]} for every player with a tour-level match on disk."""
    seen: dict[str, tuple] = {}
    for y in td.years:
        for m in td.matches(y).values():
            if not an.is_tour_level(m):
                continue
            d = str(m.get("date") or "")
            for p, rk in ((m.get("p1"), m.get("rank1")), (m.get("p2"), m.get("rank2"))):
                if not p:
                    continue
                old = seen.get(p)
                if old is None or d >= old[0]:
                    seen[p] = (d, an.inum(rk) if rk else (old[1] if old else None))
    rk = {r[1]: int(r[0]) for r in (td.store(td.current).get("rankings") or {}).get("rows") or []}
    out = {}
    for p in sorted(seen):
        info = td.players.get(p) or {}
        out[p] = [td.name(p), td.short(p), info.get("country"), rk.get(p, seen[p][1])]
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "players": out}


def lab(td: an.TourData, catalogues: dict[int, dict]) -> dict:
    """Column-oriented player-seasons (at least LAB_MIN_MATCHES matches) with the official "rank" column and the
    catalogue's "age" (at the season's end) and the player's "hand" (R / L, the registry's; the Scouting Room's age and
    plays filters, round 9), plus a compact "surface" block:
    player-season x surface rows (at least LAB_MIN_SURFACE matches on it) over the surface-capable metrics only
    (players.SURFACE_KEYS, "matches" first)."""
    from oddsmarkets.tennis.analytics.players import METRICS, SURFACE_KEYS, tour_metrics
    keys = [m["key"] for m in METRICS]
    fields = ["id", "name", "year", "qualified", "rank", "age", "hand"] + keys
    skeys = ["matches"] + [k for k in SURFACE_KEYS if k != "matches"]
    sfields = ["id", "year", "surface"] + skeys
    rows, srows, years = [], [], []
    for y in sorted(catalogues):
        cat = catalogues[y] or {}
        pl = cat.get("players") or {}
        if not pl:
            continue
        years.append(int(y))
        for pid, r in pl.items():
            v = r.get("values") or {}
            if (r.get("matches") or 0) >= LAB_MIN_MATCHES:
                rows.append([pid, r.get("name"), int(y), bool(r.get("qualified")), v.get("rank"), r.get("age"),
                             (td.players.get(pid) or {}).get("hand")] + [v.get(k) for k in keys])
            for srf, sv in (r.get("values_surface") or {}).items():
                if (sv.get("matches") or 0) >= LAB_MIN_SURFACE:
                    srows.append([pid, int(y), srf] + [sv.get(k) for k in skeys])
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "fields": fields, "metrics": tour_metrics(td.tour), "rows": rows, "years": years,
            "min_matches": LAB_MIN_MATCHES, "surface": {"fields": sfields, "rows": srows, "min_matches": LAB_MIN_SURFACE}}


def model_payload(td: an.TourData) -> dict:
    """data/<T>/model.json: the constants a browser needs to price any pairing the way predict() does."""
    from oddsmarkets.tennis import canon
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import gelo as G
    from oddsmarkets.tennis.models import match_chain as mc
    from oddsmarkets.tennis.models import predict as P
    from oddsmarkets.tennis.models import serve_return as SR
    prm = td.elo_params() or {}
    bl = P.blend_params(td.tour)
    mkt = None
    if bl.get("w_mr"):
        # the match price adds the market rating (models/mrating.py), which this payload does not carry per player:
        # the browser formula below keeps the fundamental blend (fitted without it), and "market" documents the rest
        from oddsmarkets.tennis.models import _io
        from oddsmarkets.tennis.models import mrating as MRt
        fund = (_io.read_json(_io.FITTED / f"predict_{td.tour}.json") or {}).get("fundamental") or {}
        mkt = {"w_elo": bl.get("w_elo"), "w_sr": bl.get("w_sr"), "w_gelo": bl.get("w_gelo"), "w_mr": bl.get("w_mr"),
               "params": MRt.params(td.tour), "version": MRt.VERSION,
               "formula": "the site's match forecasts: logit p = w_elo logit(elo_p) + w_sr logit(sr_p) + w_gelo (m1 - m2) + "
                          "w_mr s_b (M1 - M2), M = the market rating (R + D_surface; a Kalman filter on earlier "
                          "matches' closing lines (margin removed) and results), s_b = params.s5 for best of five, else 1"}
        from oddsmarkets.tennis.models import sched as SC
        if SC.on(td.tour) and bl.get("w_x"):
            # the schedule and form terms (models/sched.py) are part of the price on this tour
            mkt["w_x"] = {k: round(float(v), 5) for k, v in bl["w_x"].items()}
            mkt["sched_version"] = SC.VERSION
            mkt["formula"] += (" + sum_k w_x[k] (x1_k - x2_k), x = [rest: log days since the last match (1-60), m30: "
                               "matches in the last 30 days (difference clipped to +-15, / 5), pts: log ranking points, "
                               "form: decayed mean of result - Elo expectation (half-life 8 matches, x 5), ret: retired "
                               "in the last match, h2h: (wins - losses) / (meetings + 3)]")
        if fund.get("w_elo") is not None:
            bl = dict(bl, w_elo=fund["w_elo"], w_sr=fund["w_sr"], w_gelo=fund.get("w_gelo", bl.get("w_gelo")))
    sr = td.sr_fit(td.today - timedelta(days=1)) or {}
    base = dict(sr.get("base") or {})
    rules = {}
    for tid in ("australian-open", "roland-garros", "wimbledon", "us-open"):
        r, at = canon.final_set_rule(td.tour, tid, td.today.year)
        rules[tid] = "tb12" if (r == "tb7" and at == 12) else r
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "as_of": td.today.isoformat(),
            "elo": {"w_surf": prm.get("w_surf"), "bo5": prm.get("bo5"), "mean": E.MEAN, "params": prm, "version": E.VERSION,
                    "formula": "m = w_surf * R_surface + (1 - w_surf) * R_all; P(1) = 1 / (1 + 10^(-f (m1 - m2) / 400)), "
                               "f = bo5 for best of five, else 1 (ratings: elo.json current)"},
            "blend": {"w_elo": bl.get("w_elo"), "w_sr": bl.get("w_sr"), "w_gelo": bl.get("w_gelo") or 0.0,
                      "gelo_w_surf": G.params(td.tour)["w_surf"], "sigma": bl.get("sigma"), "fitted": bl.get("fitted"),
                      "version": bl.get("version"),
                      "formula": "logit p = w_elo logit(elo_p) + w_sr logit(sr_p) + w_gelo (m1 - m2), m = gelo_w_surf G_surface "
                                 "+ (1 - gelo_w_surf) G_all from the game-share Elo (elo.json current 'g': all, hard, clay, "
                                 "grass; 0 when either is missing); sr_p = chain(p_srv1, p_srv2); the serve-point "
                                 "pair is then shifted (p1 + d, p2 - d) until the chain returns p" +
                                 ("; these are the fundamental weights (fitted without the market rating): the match "
                                  "pages' forecasts add it ('market')" if mkt else "")},
            **({"market": mkt} if mkt else {}),
            "serve_return": {"base": base, "through": sr.get("through"), "version": sr.get("version") or SR.VERSION,
                             "formula": "logit hold(i v j) = mu + clay|grass + indoor + bo5 + level[lv] + (s_i + ds_i,surface) - "
                                        "(r_j + dr_j,surface); unknown players s = new_s, r = new_r; p_srv = inverse of "
                                        "G(p) = p^4 (1 + 4q + 10q^2) + 20 p^3 q^3 p^2 / (1 - 2pq); displayed hold adds k_hold, "
                                        "displayed SPW = sigmoid(logit p + k_spw). Player s, r per surface: the latest "
                                        "'serve_return' row per surface in the career file."},
            "final_set_rules": {"default": "tb7", "slams": rules,
                                "levels": {lv: ("tb10" if lv == "slam" else "tb7") for lv in an.TOUR_LEVELS}},
            "best_of": {"slam": 5 if td.tour == "atp" else 3, "other": 3},
            "base_spw": P.BASE_SPW.get(td.tour), "chain_rules": list(mc.RULES)}


def _title(t: dict | None) -> dict | None:
    if not isinstance(t, dict):
        return None
    keep = ("available", "reason", "probs", "sources", "by_source", "implied_total", "overround", "markets", "kind", "field",
            "quoted", "unmatched", "event", "label")
    return {k: t.get(k) for k in keep if k in t}


def markets_payload(td: an.TourData, prices: dict | None, futures: dict | None, preds: dict, sims: dict[str, dict],
                    race_sim: dict | None, horizon_days: int = 3) -> dict:
    ms = {}
    for y in {td.current}:
        for mid, m in td.matches(y).items():
            if m.get("status") not in ("upcoming", "live") or not an.is_tour_level(m):
                continue
            d = an.day(m.get("date"))
            if d is not None and (d > td.today + timedelta(days=horizon_days) or d < td.today - timedelta(days=1)):
                continue
            pr = preds.get(mid)
            mk = (prices or {}).get(mid)
            p = (pr or {}).get("p1_win")
            q = (mk or {}).get("p1")
            ms[mid] = {"p1": m.get("p1"), "p2": m.get("p2"), "n": [td.short(m.get("p1")), td.short(m.get("p2"))],
                       "event": m.get("event"), "round": m.get("round"), "date": m.get("date"), "status": m.get("status"),
                       "model": an.prob(p), "market": an.prob(q), "edge": an.prob(p - q) if p is not None and q is not None else None,
                       "sources": (mk or {}).get("sources") or [], "basis": (mk or {}).get("basis")}
    fut = futures or {}
    ev_titles = {}
    for key, t in (fut.get("tournaments") or {}).items():
        eid = (t or {}).get("event") or key
        ev_titles[eid] = _title(t)
    model = {"events": {eid: {p: an.prob(r.get("p_title")) for p, r in ((s or {}).get("players") or {}).items() if r.get("p_title")}
                        for eid, s in sims.items()},
             "finals_qual": {p: an.prob(v) for p, v in ((race_sim or {}).get("finals_qual") or {}).items()},
             "year_end_no1": {p: an.prob(v) for p, v in ((race_sim or {}).get("year_end_no1") or {}).items()},
             "finals_title": {p: an.prob(v) for p, v in ((race_sim or {}).get("finals_title") or {}).items()}}
    return {"ok": True, "tour": td.tour, "updated_at": an.now(), "matches": ms,
            "futures": {"events": ev_titles, "finals_qual": _title(fut.get("finals_qual")), "year_end_no1": _title(fut.get("year_end_no1")),
                        "finals_winner": _title(fut.get("finals_winner")), "top10": _title(fut.get("top10")),
                        f"slams_{td.current + 1}": _title(fut.get("slam_next_year"))},
            "model": model, "error": fut.get("error"), "generated_at": fut.get("generated_at")}


def index_entry(td: an.TourData, preds: dict, prices: dict | None, sims: dict[str, dict], race_sim: dict | None,
                race_rows: list | None) -> dict:
    """The tour's entry in data/index.json."""
    cur = td.matches(td.current)
    today = td.today
    lists: dict[str, list] = {"live": [], "today": [], "recent": [], "upcoming": []}
    for m in sorted(cur.values(), key=lambda m: (str(m.get("date") or ""), an.ROUND_ORDER.get(m.get("round"), 5))):
        if not an.is_tour_level(m):
            continue
        d = an.day(m.get("date"))
        if d is None:
            continue
        st = m.get("status")
        key = None
        if st == "live":
            key = "live"
        elif d == today:
            key = "today"
        elif st in an.FINISHED and today - timedelta(days=2) <= d < today:
            key = "recent"
        elif st == "upcoming" and today < d <= today + timedelta(days=2):
            key = "upcoming"
        if key is None:
            continue
        pr = preds.get(m["id"])
        lists[key].append(MT.card(td, m, pr, (prices or {}).get(m["id"]), wp_now=MT.wp_now(m, pr) if st == "live" else None))
    lists["recent"] = lists["recent"][::-1][:60]
    evs = []
    for eid, ev in td.events(td.current).items():
        if ev.get("status") != "live" or str(ev.get("level")) not in an.TOUR_LEVELS:
            continue
        from oddsmarkets.tennis.analytics.events import round_now
        ms = [m for m in cur.values() if m.get("event") == eid and m.get("round") not in ("Q1", "Q2", "Q3")]
        sp = (sims.get(eid) or {}).get("players") or {}
        fav = max(sp.items(), key=lambda kv: kv[1].get("p_title") or 0) if sp else None
        evs.append({"event": eid, "name": ev.get("name"), "level": ev.get("level"), "surface": ev.get("surface"),
                    "start": ev.get("start"), "end": ev.get("end"), "round_now": round_now(ms),
                    "favourite": [fav[0], an.prob(fav[1].get("p_title"))] if fav else None})
    lvl = {"slam": 0, "finals": 1, "m1000": 2, "500": 3, "250": 4, "other": 5}
    evs.sort(key=lambda e: (lvl.get(str(e["level"]), 9), str(e.get("start"))))
    from oddsmarkets.tennis.analytics.rankings import active_elo
    act = active_elo(td, today + timedelta(days=1))
    elo_top = {k: [[p, round(act[p][k], 1)] for p in sorted(act, key=lambda p: -act[p][k])[:10]] for k in ("all",) + an.SURFACES}
    fq = (race_sim or {}).get("finals_qual") or {}
    no1 = (race_sim or {}).get("year_end_no1") or {}
    rr = {p: v for p, v in (race_rows or [])}
    order = sorted(set(fq) | set(list(rr)[:20]), key=lambda p: (-(fq.get(p) or 0), -(rr.get(p) or 0)))[:10]
    return {"name": an.TOUR_NAMES.get(td.tour, td.tour.upper()), "year": td.current, "years": td.years, **lists,
            "events_now": evs, "elo_top": elo_top, "race_top": [[p, an.prob(fq.get(p, 0.0)), an.prob(no1.get(p, 0.0)), rr.get(p)]
                                                                 for p in order],
            "names": {p: td.short(p) for p in set(order) | {x[0] for v in elo_top.values() for x in v}
                      | {e["favourite"][0] for e in evs if e.get("favourite")}}}


# ─────────────────────────────────────────────── "This week in tennis" (the overview's digest)
FEATURED_MIN = 40.0        # a tennis hero needs more than the Home page's 30: a 250 quarter-final at a sane hour is
                           # about 32, so only a Slam, Finals or 1000 match, a 500 from the quarters, or a 250 final leads


def _start(c: dict) -> tuple[str | None, bool]:
    """(ISO UTC start, tba) from a card's date: "2026-10-17T04:00" is UTC; a bare date has no time (tba)."""
    d = str(c.get("date") or "")
    if len(d) == 16:
        return d + ":00Z", bool(c.get("tba"))
    if len(d) == 10:
        return d, True
    return (d or None), bool(c.get("tba"))


def digest_games(cards: list[dict], events: dict, tour: str) -> list[dict]:
    """Match cards (MT.card) as the shared game dict (oddsmarkets/common/featured.py, digest.py): p1 is "home" and its
    chance p_home; the winner set from the card (the score is sets, so it says who won only with a retirement read
    right); the event's level as sig.comp and the round as sig.round. Walkovers are left out (no match was played)."""
    out = []
    for c in cards or []:
        st = str(c.get("status") or "")
        if st == "wo" or not c.get("p1") or not c.get("p2"):
            continue
        status = "final" if st in an.FINISHED else "live" if st == "live" else "pre"
        start, tba = _start(c)
        ev = (events or {}).get(c.get("event")) or {}
        sets = c.get("sets") or []
        hs = sum(1 for s in sets if s and s[0] is not None and s[1] is not None and s[0] > s[1]) if status != "pre" else None
        as_ = sum(1 for s in sets if s and s[0] is not None and s[1] is not None and s[1] > s[0]) if status != "pre" else None
        w = c.get("winner")
        g = {"sport": "tennis", "league": f"{tour.upper()} · {ev.get('name') or c.get('event')}", "id": c.get("id"), "start": start,
             "status": status, "home": c.get("p1"), "away": c.get("p2"), "hs": hs, "as": as_, "p_home": (c.get("model") or {}).get("p1"),
             "wp_home": c.get("wp_now") if status == "live" else None, "note": c.get("round"),
             "winner": "home" if w and w == c.get("p1") else "away" if w and w == c.get("p2") else None,
             "sig": {"comp": ev.get("level") or ("challenger" if "challenger" in str(c.get("event") or "") else "other"), "round": c.get("round")}}
        if tba:
            g["tba"] = True
        out.append(g)
    return out


def digest(tour: str, cards: list[dict], events: dict, race_sim: dict | None, prev_log: dict | None, now) -> tuple[dict, dict]:
    """The tour's index.json "digest" and the chance log to write back (data/<T>/chance_log.json).

    record / upset / hot (the player with the most wins this week) from finished matches' pre-match chances, which
    are walk-forward (matches.predictions: the Elo from just before the match and the serve/return fit through the
    day before its month began), so no look-ahead; movers in the race to the Finals and the year-end No. 1 from the
    log of each build's season simulation; the stage (the tournaments in play, the next big one, the Finals); and
    the featured match on the shared significance rule, a TBA (date-only) match never featured since its hour is
    unknown."""
    from oddsmarkets.common import digest as DG
    from oddsmarkets.common import featured as FT
    games = digest_games(cards, events, tour)
    out: dict = {"asof": now.strftime("%Y-%m-%dT%H:%MZ")}
    rec = DG.record(games, now)
    if rec:
        rec.pop("by", None)
        out["record"] = rec
    up = DG.upset(games, now)
    if up:
        out["upset"] = {k: up[k] for k in ("id", "start", "side", "winner", "loser", "p", "hs", "as", "league") if k in up}
    h = DG.hot(games, now)
    if h:
        out["hot"] = h
    log = {}
    for m in ("finals_qual", "year_end_no1"):
        cur = {p: v for p, v in ((race_sim or {}).get(m) or {}).items() if isinstance(v, (int, float)) and v >= 0.005}
        log[m] = DG.roll_log((prev_log or {}).get(m), now, cur)
    best = None
    for m in ("finals_qual", "year_end_no1"):
        cur = (race_sim or {}).get(m) or {}
        mv = DG.movers(log[m], {p: v for p, v in cur.items() if isinstance(v, (int, float))}, now)
        if mv:
            top = max(abs(r["d"]) for r in mv["up"] + mv["down"])
            if best is None or top > best[0]:
                best = (top, dict(mv, metric=m))
    if best:
        out["movers"] = best[1]
    today = now.date()
    lvl = {"slam": 0, "finals": 1, "m1000": 2, "500": 3, "250": 4, "other": 5}
    evs = [(eid, e) for eid, e in (events or {}).items() if str(e.get("level")) in an.TOUR_LEVELS]
    live = sorted([(eid, e) for eid, e in evs if e.get("status") == "live" or (str(e.get("start")) <= today.isoformat() <= str(e.get("end")) and e.get("status") != "done")],
                  key=lambda x: (lvl.get(str(x[1].get("level")), 9), str(x[1].get("start"))))
    later = sorted([(eid, e) for eid, e in evs if str(e.get("start") or "") > today.isoformat()], key=lambda x: str(x[1].get("start")))
    ev_ = lambda eid, e: {"id": eid, "name": e.get("name"), "level": e.get("level"), "surface": e.get("surface"), "start": e.get("start"), "end": e.get("end")}
    big_next = next(((eid, e) for eid, e in later if str(e.get("level")) in ("slam", "finals", "m1000")), None)
    finals = next(((eid, e) for eid, e in evs if e.get("level") == "finals"), None)
    out["stage"] = {"now": [ev_(*x) for x in live[:3]], "next": ev_(*later[0]) if later else None, "next_big": ev_(*big_next) if big_next else None,
                    "finals": ev_(*finals) if finals else None, "done": sum(1 for _, e in evs if e.get("status") == "done"), "total": len(evs)}
    cand = [g for g in games if not g.get("tba")]
    r = FT.rank_featured(cand, now, min_score=FEATURED_MIN)
    row = lambda x: {"id": x["key"].split(":", 1)[1], "score": x["score"], "why": x.get("reasons") or []}
    wk = r.get("week")
    out["featured"] = {"today": [row(x) for x in r["today"]], "week": row(wk) if wk and wk.get("week_score", 0) >= FEATURED_MIN - 10 else None}
    return out, log
