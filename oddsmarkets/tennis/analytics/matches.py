"""
Match cards, the match centre (data/<T>/matches/<mid>.json) and the season schedule (data/<T>/<year>/schedule.json).

Pre-match prediction of a match (C's predict_many: Elo blended with the serve/return model, priced through
the exact chain): for a finished match, B's walk-forward Elo probability from just before it and the
serve/return model fitted through the day before the first of its month (monthly checkpoints, so a match
never sees itself or anything after its month began); for a live or upcoming match, today's ratings and fit.

The win-probability path (C's live.path) uses the prediction's serve-point pair; for a finished match the
game order within sets is reconstructed (the path says so) unless the source gives it.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from oddsmarkets.tennis import analytics as an

logger = logging.getLogger(__name__)
VERSION = 1
UPSET_P = 0.35
COMEBACK_P = 0.25
DOMINANT_SHARE = 0.70


def event_year(eid: Any, default: int) -> int:
    tail = str(eid or "").rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else default


def checkpoint(d: date) -> date:
    return d.replace(day=1)


def predictions(td: an.TourData, matches: list[dict], with_dist: bool = False) -> dict[str, dict]:
    """{mid: predict row} (C's contract) for MATCH rows, finished ones at their month checkpoint with exact
    pre-match Elo, the others with today's context."""
    from oddsmarkets.tennis.models import predict as P
    groups: dict[date, list[dict]] = defaultdict(list)
    for m in matches:
        if not m.get("p1") or not m.get("p2"):
            continue
        d = an.day(m.get("date"))
        if m.get("status") in an.FINISHED and d is not None and d <= td.today:
            groups[checkpoint(d)].append(m)
        else:
            groups[td.today].append(m)
    out: dict[str, dict] = {}
    for cp, ms in sorted(groups.items()):
        exact = {}
        exact_g = {}
        exact_m = {}
        use_g = hasattr(td, "gelo_pre") and bool(P.blend_params(getattr(td, "tour", "atp")).get("w_gelo"))
        use_m = hasattr(td, "mr_pre") and bool(P.blend_params(getattr(td, "tour", "atp")).get("w_mr"))
        if cp != td.today:
            for m in ms:
                e = td.elo_pre(m)
                if e is not None:
                    exact[(m["p1"], m["p2"])] = e
                g = td.gelo_pre(m) if use_g else None
                if g is not None:
                    exact_g[(m["p1"], m["p2"])] = g
        if use_m:                       # finished: exact pre-match values; today: current states (rank prior if new)
            for m in ms:
                v = td.mr_pre(m)
                if v is not None:
                    exact_m[(m["p1"], m["p2"])] = v
        kw = {}
        if exact_g:
            kw["exact_gelo"] = exact_g
        if exact_m:
            kw["exact_mr"] = exact_m
        ctx = td.context(cp, exact_elo=exact or None, **kw)
        rows = [{"p1": m["p1"], "p2": m["p2"], "surface": m.get("surface") or "hard", "best_of": int(m.get("best_of") or 3),
                 "level": m.get("level") or "250", "indoor": bool(m.get("indoor")), "final_set_rule": an.chain_rule(m),
                 "date": m.get("date"),
                 "tid": (m.get("event") or "").rsplit("-", 1)[0]} for m in ms]
        try:
            res = P.predict_many(ctx, rows, with_dist=with_dist)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s predictions at %s failed: %s", td.tour, cp, exc)
            continue
        standin = (cp - timedelta(days=1)).isoformat() in td.sr_skipped
        for m, r in zip(ms, res):
            r["_ctx_date"] = cp.isoformat()
            if standin:
                r["_sr_skipped"] = True                # no serve/return fit this run (refit budget): page left unsigned
            out[m["id"]] = r
    return out


def _dist_top(pred: dict | None) -> list | None:
    d = (pred or {}).get("dist")
    if not d:
        return None
    s = sorted((d.get("sets") or {}).items(), key=lambda kv: -kv[1])[:3]
    return [[k, an.prob(v)] for k, v in s]


def card(td: an.TourData, m: dict, pred: dict | None = None, market: dict | None = None, wp_now: float | None = None,
         light: bool = False) -> dict:
    """MATCH_CARD (PAYLOADS.md), plus "n": [short names]."""
    p = (pred or {}).get("p1_win")
    if p is None and light:
        p = td.elo_pre(m)
    model = {"p1": an.prob(p)} if light else {"p1": an.prob(p), "sets_dist_top": _dist_top(pred),
                                               "exp_games": an.rnd(((pred or {}).get("dist") or {}).get("exp_games"), 1)}
    mk = None
    if market and market.get("p1") is not None:
        mk = {"p1": an.prob(market["p1"]), "sources": [s.get("source") for s in market.get("sources") or []] or
              ([market.get("basis")] if market.get("basis") else []), "basis": market.get("basis")}
    return {"id": m["id"], "event": m.get("event"), "round": m.get("round"), "date": m.get("date"), "status": m.get("status"),
            "p1": m.get("p1"), "p2": m.get("p2"), "n": [td.short(m.get("p1")), td.short(m.get("p2"))], "winner": m.get("winner"),
            "sets": m.get("sets") or [], "live": m.get("live"), "model": model, "market": mk, "wp_now": an.prob(wp_now)}


def wp_path(m: dict, pred: dict | None) -> dict | None:
    from oddsmarkets.tennis.models import live as LV
    if not pred or not pred.get("p_srv"):
        return None
    if not (m.get("sets") or m.get("live")):
        return None
    try:
        return LV.path(m, tuple(pred["p_srv"]))
    except Exception as exc:  # noqa: BLE001
        logger.debug("wp path %s failed: %s", m.get("id"), exc)
        return None


def wp_now(m: dict, pred: dict | None) -> float | None:
    if m.get("status") != "live":
        return None
    pth = wp_path(m, pred)
    if not pth or not pth.get("steps"):
        return None
    return pth["steps"][-1].get("p1")


def _dist_out(d: dict | None) -> dict | None:
    if not d:
        return None
    games = {str(k): an.prob(v) for k, v in (d.get("games") or {}).items() if v and v >= 5e-5}
    hcp = {str(k): an.prob(v) for k, v in (d.get("handicap") or {}).items() if v and v >= 5e-5}
    return {"p1_win": an.prob(d.get("p1_win")), "sets": {k: an.prob(v) for k, v in (d.get("sets") or {}).items()},
            "games": games, "handicap": hcp, "p_tiebreak": an.prob(d.get("p_tiebreak")), "p_straight": an.prob(d.get("p_straight")),
            "exp_games": an.rnd(d.get("exp_games"), 2), "best_of": d.get("best_of"), "final_set_rule": d.get("final_set_rule")}


def build_match(td: an.TourData, m: dict, pred: dict | None, market: dict | None = None, event: dict | None = None) -> dict:
    """data/<T>/matches/<mid>.json."""
    from oddsmarkets.tennis.models import serve_return as SR
    ev = event or td.events(event_year(m.get("event"), td.current)).get(m.get("event")) or {}
    p1, p2 = m.get("p1"), m.get("p2")
    surf = m.get("surface") or ev.get("surface") or "hard"
    # Elo before the match
    g = td.elo_row(m["id"])
    when = an.day(m.get("date")) or td.today
    if g is not None:
        a1, s1, a2, s2 = (g[8], g[9], g[10], g[11]) if str(g[2]) == str(p1) else (g[10], g[11], g[8], g[9])
        elo = {"p": an.prob(td.elo_pre(m)), "p1": {"all": an.rnd(a1, 1), "surface": an.rnd(s1, 1)},
               "p2": {"all": an.rnd(a2, 1), "surface": an.rnd(s2, 1)}, "surface": surf}
    else:
        r = td.elo_at(min(when, td.today))
        x1, x2 = r.get(p1) or {}, r.get(p2) or {}
        sk = surf if surf in an.SURFACES else "hard"
        elo = {"p": an.prob((pred or {}).get("elo_p")), "p1": {"all": an.rnd(x1.get("all"), 1), "surface": an.rnd(x1.get(sk), 1)},
               "p2": {"all": an.rnd(x2.get("all"), 1), "surface": an.rnd(x2.get(sk), 1)}, "surface": surf}
    # serve / return at the prediction's checkpoint
    cp = an.day((pred or {}).get("_ctx_date")) or td.today
    sr = td.sr_fit(cp - timedelta(days=1))
    holds = spw = None
    if sr:
        try:
            args = (surf, m.get("level"), int(m.get("best_of") or 3), bool(m.get("indoor")))
            hc = [SR.hold_prob(sr, p1, p2, *args, calibrated=True), SR.hold_prob(sr, p2, p1, *args, calibrated=True)]
            ch = [SR.hold_prob(sr, p1, p2, *args), SR.hold_prob(sr, p2, p1, *args)]
            k_spw = float((sr.get("base") or {}).get("k_spw", 0.0))
            f = getattr(SR, "_spw", None)
            holds = [an.rnd(x, 3) for x in hc]
            spw = [an.rnd(f(x, k_spw), 3) for x in ch] if f else None
        except Exception:  # noqa: BLE001
            pass
    odds = m.get("odds") or {}
    closing = None
    if odds.get("ps") or odds.get("avg"):
        closing = {"ps": odds.get("ps"), "avg": odds.get("avg"), "max": odds.get("max"), "b365": odds.get("b365"),
                   "p1": an.prob(an.devig2(odds.get("ps")) or an.devig2(odds.get("avg")))}
    mk = None
    if market and market.get("p1") is not None:
        mk = {"p1": an.prob(market["p1"]), "sources": market.get("sources") or [], "basis": market.get("basis"),
              "bookmakers": market.get("bookmakers")}
    pre = {"model": None, "elo": elo, "sr": {"p_srv": [an.rnd(x, 4) for x in ((pred or {}).get("p_srv_sr") or (pred or {}).get("p_srv") or [])] or None,
                                              "hold": holds, "spw": spw},
           "market": mk, "closing": closing, "h2h": an.h2h(td, p1, p2, before=str(m.get("date") or td.today.isoformat()))}
    if pred:
        pre["model"] = {"p1_win": an.prob(pred.get("p1_win")), "p_srv": [an.rnd(x, 4) for x in pred.get("p_srv") or []],
                        "elo_p": an.prob(pred.get("elo_p")), "sr_p": an.prob(pred.get("sr_p")), "blend_w": pred.get("blend_w"),
                        "basis": pred.get("basis"), "as_of": pred.get("_ctx_date"), "version": pred.get("version"),
                        "dist": _dist_out(pred.get("dist"))}
    pth = wp_path(m, pred)
    wp = None
    if pth:
        wp = [[s["i"], s.get("set"), (s.get("games") or [None, None])[0], (s.get("games") or [None, None])[1], an.prob(s.get("p1"))]
              for s in pth.get("steps") or []]
    awards = match_awards(m, pred, pth)
    st = m.get("stats") if isinstance(m.get("stats"), dict) else None
    return {"ok": True, "tour": td.tour, "id": m["id"], "event": m.get("event"), "event_name": ev.get("name"), "level": m.get("level"),
            "round": m.get("round"), "date": m.get("date"), "surface": surf, "indoor": bool(m.get("indoor")),
            "best_of": int(m.get("best_of") or 3), "final_set_rule": an.chain_rule(m), "status": m.get("status"),
            "p1": p1, "p2": p2, "names": {p1: td.name(p1), p2: td.name(p2)}, "ranks": [m.get("rank1"), m.get("rank2")],
            "winner": m.get("winner"), "sets": m.get("sets") or [], "score": an.score_text(m), "live": m.get("live"),
            "duration_min": m.get("duration_min"), "pre": pre, "wp": wp,
            "wp_reconstructed": (pth or {}).get("reconstructed"),
            "swings": (pth or {}).get("swings") or [], "excitement": an.rnd((pth or {}).get("excitement"), 3),
            "comeback": (pth or {}).get("comeback"), "stats": st, "inferred": {"hold": holds, "spw": spw},
            "charting": None, "style_charted": [p1 in td.style, p2 in td.style], "awards": awards,
            "sources": m.get("sources") or [], "updated_at": an.now()}


def match_awards(m: dict, pred: dict | None, pth: dict | None) -> dict:
    out: dict[str, Any] = {}
    w = an.winner_side(m)
    if w is None or m.get("status") not in an.FINISHED:
        return out
    pw = (pred or {}).get("p1_win")
    if pw is not None:
        pwin = pw if w == 0 else 1 - pw
        if pwin < UPSET_P:
            out["upset"] = {"winner": m.get("winner"), "p": an.prob(pwin)}
    cb = (pth or {}).get("comeback")
    if cb and cb.get("min_p") is not None and cb["min_p"] < COMEBACK_P:
        out["comeback"] = {"winner": m.get("winner"), "min_p": an.prob(cb["min_p"]), "sets": cb.get("sets"), "games": cb.get("games")}
    sets = an.set_pairs(m)
    if sets and m.get("status") == "done":
        gw = sum(a for a, b in sets)
        gl = sum(b for a, b in sets)
        share = gw / (gw + gl) if gw + gl else None
        if share is not None and share >= DOMINANT_SHARE:
            out["dominant"] = {"winner": m.get("winner"), "games_share": an.rnd(share, 3)}
    tbs = []
    ps = (pred or {}).get("p_srv")
    if ps:
        from oddsmarkets.tennis.models import match_chain as mc
        bo = int(m.get("best_of") or 3)
        for k, (a, b) in enumerate(sets):
            if {a, b} == {7, 6} or {a, b} == {13, 12}:
                to = 10 if (k == bo - 1 and an.chain_rule(m) == "tb10") else 7
                e = 0.5 * (float(mc.tiebreak_win(ps[0], ps[1], to, 0)) + float(mc.tiebreak_win(ps[0], ps[1], to, 1)))
                tbs.append({"set": k + 1, "winner": m.get("p1") if a > b else m.get("p2"), "p1_exp": an.prob(e)})
    if tbs:
        out["tiebreaks"] = tbs
    return out


def page_sig(m: dict, tour: str) -> str:
    """A match page's inputs: the model code versions, the committed fits (predict_, serve_return_ and
    elo_params_<tour>.json, so a refit rebuilds finished pages) and the match row's own fields."""
    from oddsmarkets.tennis.models import _io
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import predict as P
    from oddsmarkets.tennis.models import serve_return as SR
    return an.digest(VERSION, P.VERSION, SR.VERSION, E.VERSION, _io.fits_signature(tour),
                     m.get("status"), m.get("winner"), m.get("sets"), m.get("date"), bool(m.get("stats")),
                     bool(m.get("odds")), m.get("p1"), m.get("p2"), bool(m.get("indoor")))


def schedule(td: an.TourData, year: int, preds: dict | None = None, markets: dict | None = None) -> dict:
    ms = [m for m in td.matches(year).values() if an.is_tour_level(m)]
    ms.sort(key=lambda m: (str(m.get("date") or ""), m.get("event") or "", an.ROUND_ORDER.get(m.get("round"), 5), m["id"]))
    preds = preds or {}
    cards = [card(td, m, preds.get(m["id"]), (markets or {}).get(m["id"]), light=True) for m in ms]
    return {"ok": True, "tour": td.tour, "year": int(year), "updated_at": an.now(), "matches": cards}
