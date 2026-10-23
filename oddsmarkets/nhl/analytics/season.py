"""
season.json, schedule.json and markets.json.

season.json: standings (league, conference, division, wild card) with GP, W, L, OTL, PTS, P%, RW, ROW, GF, GA, xGF%
and our rating; the simulation per team (p_playoffs, p_div, p_pres, p_conf, p_cup, points distribution, seed
distribution, magic / elimination numbers); lottery odds; the bracket with series odds (the simulation's, or the
actual playoff series from the store); team ratings by component with history; the tiebreak procedure (canon).

Records are builder A's canon.records_from_games on the store's final regular-season games (the store's standings
snapshot fills streak / last-10 / clinch codes when present); ordering is canon.rank (the NHL tiebreak procedure of
the season).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import games as GM
from oddsmarkets.nhl.analytics.context import SeasonContext


def _canon():
    try:
        from oddsmarkets.nhl import canon
        return canon
    except Exception:                                            # noqa: BLE001
        return None


def records(ctx: SeasonContext) -> dict[str, dict]:
    C = _canon()
    gl = [{**g, "type": 2} for g in ctx.games.values() if g.get("gtype") == "REG" and g.get("status") == "final"
          and g.get("hs") is not None and g.get("as") is not None]
    if C is not None:
        rec = C.records_from_games(gl)
    else:
        rec = {}
        for g in gl:
            for side, gf, ga in (("home", g["hs"], g["as"]), ("away", g["as"], g["hs"])):
                t = rec.setdefault(g[side], {"gp": 0, "w": 0, "l": 0, "otl": 0, "pts": 0, "rw": 0, "row": 0, "gf": 0, "ga": 0})
                t["gp"] += 1
                t["gf"] += int(gf)
                t["ga"] += int(ga)
                if gf > ga:
                    t["w"] += 1
                    t["pts"] += 2
                    t["row"] += 0 if g.get("so") else 1
                    t["rw"] += 0 if (g.get("so") or g.get("ot")) else 1
                elif g.get("ot") or g.get("so"):
                    t["otl"] += 1
                    t["pts"] += 1
                else:
                    t["l"] += 1
    for t in ctx.teams:
        rec.setdefault(t, {"gp": 0, "w": 0, "l": 0, "otl": 0, "pts": 0, "rw": 0, "row": 0, "gf": 0, "ga": 0})
    return rec


def _rank(ctx, clubs: list[str], rec: dict) -> list[str]:
    C = _canon()
    gl = [{**g, "type": 2} for g in ctx.games.values() if g.get("gtype") == "REG" and g.get("status") == "final" and g.get("hs") is not None]
    if C is not None:
        try:
            return C.rank(clubs, rec, gl, ctx.season)
        except Exception:                                        # noqa: BLE001
            pass
    return sorted(clubs, key=lambda t: (-rec[t]["pts"], rec[t]["gp"], -rec[t]["rw"], -rec[t]["row"], -rec[t]["w"],
                                        -(rec[t]["gf"] - rec[t]["ga"]), -rec[t]["gf"]))


def standings(ctx: SeasonContext, teams_payload: dict | None, sim: dict | None) -> dict:
    rec = records(ctx)
    snap = ctx.store.get("standings") if isinstance(ctx.store.get("standings"), dict) else None
    snap_rows = {r.get("team"): r for r in (snap or {}).get("rows") or []}
    tp = (teams_payload or {}).get("teams") or {}
    sim_t = (sim or {}).get("teams") or {} if (sim or {}).get("ok") else {}
    order = _rank(ctx, list(ctx.teams), rec)
    rows = []
    for i, t in enumerate(order):
        r = dict(rec[t])
        info = ctx.teams.get(t) or {}
        u = (tp.get(t) or {}).get("units") or {}
        s = snap_rows.get(t) or {}
        rows.append({"team": t, "name": info.get("name"), "division": info.get("division"), "conference": info.get("conference"),
                     "gp": r["gp"], "w": r["w"], "l": r["l"], "otl": r["otl"], "pts": r["pts"],
                     "p_pct": an.rnd(r["pts"] / (2 * r["gp"]), 3) if r["gp"] else None, "rw": r["rw"], "row": r["row"],
                     "gf": r["gf"], "ga": r["ga"], "diff": r["gf"] - r["ga"], "xgf_pct": u.get("xgf_pct5"), "rating": u.get("rating"),
                     "streak": s.get("streak"), "l10": s.get("l10"), "clinch": s.get("clinch"), "league_rank": i + 1,
                     "p_playoffs": an.rnd((sim_t.get(t) or {}).get("p_playoffs"), 4), "p_cup": an.rnd((sim_t.get(t) or {}).get("p_cup"), 4),
                     "mean_pts": an.rnd((sim_t.get(t) or {}).get("mean_pts"), 1)})
    by = {r["team"]: r for r in rows}
    confs: dict[str, dict] = {}
    for r in rows:
        c = r.get("conference") or "League"
        confs.setdefault(c, {}).setdefault(r.get("division") or "-", []).append(r["team"])
    divisions = []
    wild = {}
    C = _canon()
    fmt = None
    try:
        fmt = C.formats(ctx.season)["playoff"]["kind"] if C is not None else None
    except Exception:                                            # noqa: BLE001
        fmt = None
    for c, divs in confs.items():
        tops = set()
        for d, ts in divs.items():
            o = _rank(ctx, ts, rec)
            divisions.append({"conference": c, "division": d, "teams": o})
            if fmt in (None, "divisional_wildcard"):
                tops |= set(o[:3])
        conf_order = _rank(ctx, [t for ts in divs.values() for t in ts], rec)
        wc = [t for t in conf_order if t not in tops]
        wild[c] = {"leaders": [t for t in conf_order if t in tops], "wild_card": wc[:2] if fmt in (None, "divisional_wildcard") else [],
                   "chasers": wc[2:] if fmt in (None, "divisional_wildcard") else wc, "order": conf_order}
    for i, t in enumerate(_rank(ctx, list(ctx.teams), rec)):
        by[t]["league_rank"] = i + 1
    return {"rows": rows, "divisions": divisions, "wild_card": wild, "format": fmt,
            "cols": ["team", "gp", "w", "l", "otl", "pts", "p_pct", "rw", "row", "gf", "ga", "diff", "xgf_pct", "rating"],
            "snapshot_date": (snap or {}).get("date"),
            "tiebreak": _tiebreak(ctx)}


def _tiebreak(ctx) -> dict | None:
    C = _canon()
    if C is None:
        return None
    try:
        return {"steps": [[k, txt] for k, txt in C.tiebreak_steps(ctx.season)], "source": getattr(C, "TIEBREAK_SOURCE", None)}
    except Exception:                                            # noqa: BLE001
        return None


def series_from_store(ctx: SeasonContext) -> list[dict]:
    """Actual playoff series from the store's playoff games: round, teams, wins, games, winner."""
    ser: dict[tuple, dict] = {}
    for gid, g in sorted(ctx.games.items()):
        if g.get("gtype") != "PO":
            continue
        s = g.get("series") or {}
        rnd = an.inum(s.get("round")) or (int(gid[7]) if len(gid) >= 10 else None)
        num = an.inum(s.get("series")) or (int(gid[8]) if len(gid) >= 10 else None)
        if rnd is None:
            continue
        key = (rnd, num)
        e = ser.setdefault(key, {"round": rnd, "series": num, "teams": sorted([g.get("home"), g.get("away")]), "wins": {}, "games": []})
        e["games"].append(gid)
        if g.get("status") == "final" and g.get("hs") is not None:
            w = g["home"] if g["hs"] > g["as"] else g["away"]
            e["wins"][w] = e["wins"].get(w, 0) + 1
    out = []
    for (rnd, num), e in sorted(ser.items()):
        top = max(e["wins"].values()) if e["wins"] else 0
        e["winner"] = next((t for t, w in e["wins"].items() if w >= 4), None) if top >= 4 else None
        out.append(e)
    return out


def champion(ctx: SeasonContext) -> str | None:
    ss = series_from_store(ctx)
    if not ss:
        return None
    last = max(s["round"] for s in ss)
    fin = [s for s in ss if s["round"] == last]
    return fin[0].get("winner") if len(fin) == 1 and last >= 4 else None


def bracket(ctx: SeasonContext, sim: dict | None, stand: dict) -> dict:
    actual = series_from_store(ctx)
    simb = (sim or {}).get("bracket") if (sim or {}).get("ok") else None
    seeds = {}
    for c, w in (stand.get("wild_card") or {}).items():
        seeds[c] = {"leaders": w.get("leaders"), "wild_card": w.get("wild_card")}
    return {"series": actual, "sim": simb, "seeds_now": seeds, "champion": champion(ctx)}


def build(ctx: SeasonContext, teams_payload: dict | None, sim: dict | None) -> dict:
    stand = standings(ctx, teams_payload, sim)
    sim_ok = bool((sim or {}).get("ok"))
    odds = {}
    if sim_ok:
        for t, r in (sim.get("teams") or {}).items():
            odds[t] = {k: (an.rnd(v, 4) if isinstance(v, float) else v) for k, v in r.items()}
    tp = (teams_payload or {}).get("teams") or {}
    ratings = {t: {"units": (v or {}).get("units"), "history": (v or {}).get("history"), "rolling": (v or {}).get("rolling")} for t, v in tp.items()}
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "phase": ctx.phase, "team_games": ctx.team_games(),
            "season_games": ctx.season_games(), "standings": stand, "sim": {"ok": sim_ok, "reason": None if sim_ok else (sim or {}).get("reason"),
                                                                          "n": (sim or {}).get("n"), "version": (sim or {}).get("version"),
                                                                          "teams": odds, "extra": (sim or {}).get("extra")},
            "lottery": (sim or {}).get("lottery") if sim_ok else None, "bracket": bracket(ctx, sim, stand), "ratings": ratings,
            "teams": {t: {k: v.get(k) for k in ("name", "division", "conference", "colour", "alt")} for t, v in ctx.teams.items()}}


def schedule(ctx: SeasonContext, prices: dict, frozen: dict, wf: dict, markets: dict | None, xg: dict) -> dict:
    mk = (markets or {}).get("games") or {}
    cards = []
    for gid, g in sorted(ctx.games.items(), key=lambda kv: (str(kv[1].get("date")), str(kv[1].get("start") or ""), kv[0])):
        if g.get("gtype") not in ("REG", "PO"):
            continue
        pr = prices.get(gid) or frozen.get(gid) or wf.get(gid)
        m = mk.get(gid)
        market = None
        if isinstance(m, dict) and m.get("p_home") is not None:
            market = {"p_home": an.rnd(m.get("p_home"), 4), "sources": m.get("sources") if isinstance(m.get("sources"), list) else
                      [s.get("source") if isinstance(s, dict) else s for s in (m.get("sources") or [])]}
        wp = None
        if g.get("status") == "live":
            from oddsmarkets.nhl.analytics import adapters
            wp = adapters.live_now(ctx, g, pr)
        cards.append(GM.card(g, pr, market, xg.get(gid), wp))
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "games": cards}


def _probs(x: Any) -> dict[str, dict]:
    """{team: {"p", "sources"}} from builder C's TITLE / BINARY ({"probs": {team: p}, "by_source", ...}), a dict of
    TITLEs (conference / division) merged, or a plain {team: p}."""
    if not isinstance(x, dict):
        return {}
    if isinstance(x.get("probs"), dict):
        srcs = sorted((x.get("by_source") or {}).keys()) or x.get("sources") or x.get("used")
        return {str(t): {"p": an.fnum(p), "sources": srcs} for t, p in x["probs"].items() if an.fnum(p) is not None}
    if x and all(isinstance(v, dict) and ("probs" in v or "available" in v) for v in x.values()):
        out: dict[str, dict] = {}
        for v in x.values():
            out.update(_probs(v))
        return out
    return {str(t): {"p": an.fnum(p), "sources": None} for t, p in x.items() if an.fnum(p) is not None}


FUTURES = (("cup", "p_cup", ("champion", "cup")), ("conference", "p_conf", ("conference",)), ("division", "p_div", ("division",)),
           ("presidents", "p_pres", ("presidents",)), ("playoffs", "p_playoffs", ("playoffs",)))


def markets_payload(ctx: SeasonContext, sim: dict | None, awards: dict | None, cards: list[dict], markets: dict | None) -> dict:
    """Model v market: futures (Cup, conference, division, Presidents' Trophy, playoffs), season point totals (Kalshi
    KXNHLSEASONPTS / Polymarket ladders v the simulation's points distribution), today's and upcoming games, awards."""
    from datetime import date
    mk = markets or {}
    fut = mk.get("futures") if isinstance(mk.get("futures"), dict) else {}
    sim_t = (sim or {}).get("teams") or {} if (sim or {}).get("ok") else {}
    fut_rows = {}
    for key, sk, names in FUTURES:
        m = next((_probs(fut.get(n)) for n in names if fut.get(n)), {})
        rows = []
        for t in sorted(ctx.teams):
            model = (sim_t.get(t) or {}).get(sk)
            mv = m.get(t)
            if model is None and mv is None:
                continue
            p_mk = mv.get("p") if mv else None
            rows.append({"team": t, "model": an.rnd(model, 4), "market": an.rnd(p_mk, 4), "sources": mv.get("sources") if mv else None,
                         "edge": an.rnd(model - p_mk, 4) if model is not None and p_mk is not None else None})
        rows.sort(key=lambda r: -(r["model"] if r["model"] is not None else (r["market"] or 0)))
        fut_rows[key] = rows
    games = []
    t0 = ctx.today - timedelta(days=1)
    t1 = ctx.today + timedelta(days=4)
    for c in cards:
        try:
            d = date.fromisoformat(str(c.get("date"))[:10])
        except ValueError:
            continue
        if not (t0 <= d <= t1) or c.get("status") == "final":
            continue
        pm = (c.get("model") or {}).get("p_home")
        pk = (c.get("market") or {}).get("p_home") if c.get("market") else None
        detail = ((mk.get("games") or {}).get(c.get("game_id")) or {})
        games.append({**{k: c.get(k) for k in ("game_id", "date", "start", "home", "away", "status")}, "model": c.get("model"),
                      "market": c.get("market"), "line": c.get("line"),
                      "detail": {k: detail.get(k) for k in ("spread", "total", "ot", "book", "basis")} if detail else None,
                      "edge_home": an.rnd(pm - pk, 4) if pm is not None and pk is not None else None})
    aw = awards.get("markets") if awards and isinstance(awards.get("markets"), dict) else None
    if aw is None and isinstance(mk.get("awards"), dict):
        aw = {k: {"available": v.get("available"), "probs": v.get("probs"), "reason": v.get("reason"), "sources": v.get("sources")}
              for k, v in mk["awards"].items() if isinstance(v, dict)}
    return {"ok": True, "season": ctx.season, "updated_at": an.now(), "futures": fut_rows, "points": _points(mk.get("points") or fut.get("points"), sim_t),
            "games": games, "awards": aw, "sources": ["Kalshi", "Polymarket"], "generated_at": fut.get("generated_at"),
            "note": "Market probabilities (reference) are the midpoints of live two-sided quotes with the margin removed; the difference is model minus market."}


def _points(pts: Any, sim_t: dict) -> list[dict] | None:
    """Season point totals: P(points >= N) from the market ladders against the simulation's."""
    if not isinstance(pts, dict) or not pts:
        return None
    out = []
    for t, v in sorted(pts.items()):
        if not isinstance(v, dict):
            continue
        s = sim_t.get(t) or {}
        ge = s.get("p_points_ge") or {}
        dist = s.get("points_dist")
        for src in ("kalshi", "polymarket"):
            lad = (v.get(src) or {}).get("ladder") if isinstance(v.get(src), dict) else None
            if not isinstance(lad, dict):
                continue
            for n, p in sorted(lad.items(), key=lambda kv: float(kv[0])):
                nn = an.fnum(n)
                p_md = an.fnum(ge.get(int(nn)) if int(nn) in ge else ge.get(str(int(nn)))) if ge else None
                if p_md is None and dist is not None and nn is not None:
                    p_md = _p_over(dist, nn - 0.5)
                out.append({"team": t, "source": src, "points": int(nn) if nn is not None else None, "market": an.rnd(p, 4),
                            "model": an.rnd(p_md, 4), "edge": an.rnd(p_md - an.fnum(p), 4) if p_md is not None and an.fnum(p) is not None else None})
    return out


def _p_over(dist: Any, thr: float) -> float | None:
    """P(points > thr) from a points distribution: {"lo": a, "p": [...]} or {points: p}."""
    if isinstance(dist, dict) and "p" in dist and "lo" in dist:
        lo = int(dist["lo"])
        return float(sum(p for i, p in enumerate(dist["p"]) if lo + i > thr))
    if isinstance(dist, dict):
        try:
            return float(sum(float(p) for k, p in dist.items() if float(k) > thr))
        except (TypeError, ValueError):
            return None
    return None
