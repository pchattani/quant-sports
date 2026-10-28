"""
The game centre (`games/<id>.json`) and the game cards of the hub (`index.json`).

Pregame: the game model (`models/game.py`) with ratings fitted on games strictly before the game
day (so a finished game shows what the model said before tip-off), the rest / travel / altitude
context, and an injury adjustment from the ESPN injury list (players listed "Out", each worth
(HPM - replacement) x expected minutes). In the NBA the market-informed model (`models/informed.py`) replaces it
wherever the season's stored lines allow: market ratings from earlier games' closing lines and expected
availability, with injury-report Outs set to "does not play" inside the availability term; the market (prediction-market moneylines where fetched,
else the DraftKings spread via `game.spread_to_p`); and the Elo probability.

With play-by-play (local raw file): margin flow, our win probability and ESPN's per play, every
shot with xPTS, lineups and the rotation from the reconstructed stints, the top-leverage plays and
every 4th-quarter / overtime scoring play with WPA, and the game awards. Without the raw file but
with the season's derived inputs, shots / lineups / rotation come from shots.json / stints.json and
flow / wp / plays are null; box-only seasons have all of these null.

Game awards
    player of the game   max Game Score + 20 x WPA
    biggest swing        the play with the largest |change in home WP|
    shot maker           max points over xPTS (5+ shots)
    unluckiest           the team whose margin fell furthest below its expected margin
                         (xPTS + made free throws, both sides)
    stopper              max defensive WPA (credit on plays by the other team: blocks, steals, contests)
    excitement           sum of |dWP| over the game;  comeback = the winner's lowest WP
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import lineups as LU
from oddsmarkets.basketball.analytics.context import SeasonContext
from oddsmarkets.basketball.models import _io

logger = logging.getLogger(__name__)
SHOT_OUT_COLS = ["t", "team", "player", "x", "y", "value", "made", "xpts", "zone", "type", "assisted"]
MAX_PLAYS = 60            # top-leverage plays (plus every 4th-quarter / overtime scoring play)
MAX_WP_POINTS = 400
WP_STEP = 0.004           # a WP point is kept when it moved this much since the last kept point
MAX_UNITS = 12            # lineups per team on a game page


def _day(g: dict) -> date | None:
    from oddsmarkets.basketball.models._games import local_day
    return local_day(g)


# ---------------------------------------------------------------------------------------------- pregame

def injury_inputs(ctx: SeasonContext, g: dict) -> tuple[dict, dict]:
    """(model injuries {tid: [{"impact","minutes"}]} for players listed Out, payload {tid: [{"player","status","impact"}]})."""
    model, payload = {}, {}
    gm = _io.game_minutes(ctx.league)
    for tid, lst in (g.get("injuries") or {}).items():
        rows = []
        for r in lst or []:
            pid = str(r[0])
            status = r[1] if len(r) > 1 else None
            h = ctx.hpm.get(pid) or {}
            mins = float(((h.get("proj") or {}).get("min")) or 0.0)
            imp = None
            if h.get("t") is not None:
                imp = (float(h["t"]) + 2.0) * mins / gm
                if str(status or "").lower() == "out":
                    model.setdefault(str(tid), []).append({"impact": float(h["t"]), "minutes": mins})
            rows.append({"player": pid, "name": an.player_name(ctx.store, pid), "status": status,
                         "detail": r[2] if len(r) > 2 else None, "impact": an.rnd(imp, 2)})
        payload[str(tid)] = rows
    return model, payload


def model_line(ctx: SeasonContext, g: dict, use_injuries: bool = True) -> dict | None:
    from oddsmarkets.basketball.models import game as GM
    h, a = str(g.get("home")), str(g.get("away"))
    d = _day(g)
    if d is None:
        return None
    rt = ctx.ratings_before(d) if g.get("status") in ("post", "in") else ctx.ratings
    pre = use_injuries and g.get("status") == "pre"
    inj = injury_inputs(ctx, g)[0] if pre else {}
    c = {"league": ctx.league, "ratings": rt, "schedule": ctx.schedule, "injuries": inj, "params": ctx.params,
         "neutral": bool(g.get("neutral")), "stype": g.get("stype")}
    si = ctx.informed
    if si:
        from oddsmarkets.basketball.models import informed as INF
        outs = {str(t): {str(r[0]) for r in (lst or []) if len(r) > 1 and str(r[1] or "").lower() == "out"}
                for t, lst in (g.get("injuries") or {}).items()} if pre else None
        c["informed"] = INF.inputs_for_game(si, d, h, a, out=outs, upcoming=g.get("status") == "pre")
    p = GM.predict(h, a, d, c)
    return _io.clean(p, 4)


def market_line(ctx: SeasonContext, g: dict) -> dict | None:
    from oddsmarkets.basketball.models import game as GM
    gid = str(g.get("id"))
    gp = (ctx.game_prices or {}).get(gid)
    odds = g.get("odds") or {}
    if gp and gp.get("p_home") is not None:
        return {"p_home": an.rnd(gp["p_home"], 4), "spread_home": gp.get("spread_home", odds.get("spread_home")),
                "total": gp.get("total", odds.get("total")), "sources": [s.get("source") for s in gp.get("sources") or []] or
                [gp.get("basis") or "market"], "basis": gp.get("basis"), "by_source": gp.get("sources")}
    if odds.get("spread_home") is not None or odds.get("ml_home") is not None:
        p = None
        basis = None
        mh, ma = odds.get("ml_home"), odds.get("ml_away")
        if mh is not None and ma is not None:
            ph, pa = _ml(mh), _ml(ma)
            if ph and pa:
                p, basis = ph / (ph + pa), "draftkings_ml"
        if p is None and odds.get("spread_home") is not None:
            p, basis = GM.spread_to_p(odds.get("spread_home"), ctx.league), "draftkings_spread"
        return {"p_home": an.rnd(p, 4), "spread_home": odds.get("spread_home"), "total": odds.get("total"),
                "sources": [odds.get("provider") or "DraftKings"], "basis": basis}
    return None


def _ml(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v == 0:
        return None
    return 100.0 / (v + 100.0) if v > 0 else -v / (-v + 100.0)


def elo_p(ctx: SeasonContext, g: dict) -> float | None:
    from oddsmarkets.basketball.models import elo as E
    row = (ctx.elo_season.get("games") or {}).get(str(g.get("id")))
    if row:
        return an.rnd(row[2], 4)
    cur = (ctx.elo_hist or {}).get("current") or {}
    if not cur:
        return None
    return an.rnd(E.predict(cur, str(g.get("home")), str(g.get("away")), bool(g.get("neutral")), ctx.league)["p_home"], 4)


# ---------------------------------------------------------------------------------------------- box

def box_block(ctx: SeasonContext, g: dict, wpa: dict | None = None, pox: dict | None = None) -> tuple[dict, dict]:
    """(box {tid: {"players", "team"}}, four_factors {tid: {...}})."""
    box = g.get("box") or {}
    h, a = str(g.get("home")), str(g.get("away"))
    out, ff = {}, {}
    team_tot = {}
    for t in (h, a):
        b = box.get(t) or {}
        rows = [dict(zip(_io.BOX_COLS, list(r) + [None] * (len(_io.BOX_COLS) - len(r)))) for r in b.get("players") or []]
        tb = b.get("team") or {}
        tot = {k: float(tb.get(k) if tb.get(k) is not None else sum((r.get(k) or 0) for r in rows))
               for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "stl", "blk", "tov", "pf")}
        tot["sec"] = float(sum((r.get("sec") or 0) for r in rows))
        team_tot[t] = (rows, tot, tb)
    for t, o in ((h, a), (a, h)):
        rows, tot, tb = team_tot[t]
        otot = team_tot[o][1]
        poss_t = tot["fga"] - tot["oreb"] + tot["tov"] + 0.44 * tot["fta"]
        poss_o = otot["fga"] - otot["oreb"] + otot["tov"] + 0.44 * otot["fta"]
        poss = 0.5 * (poss_t + poss_o)
        pts = g.get("hs") if t == h else g.get("as")
        secs = 4 * (600 if ctx.league == "wnba" else 720) + 300 * max(0, int(g.get("periods") or 4) - 4)
        f4 = {"efg": an.rnd(an.div(tot["fgm"] + 0.5 * tot["tpm"], tot["fga"]), 3), "tov": an.rnd(an.div(tot["tov"], poss), 3),
              "orb": an.rnd(an.div(tot["oreb"], tot["oreb"] + otot["dreb"]), 3), "ftr": an.rnd(an.div(tot["ftm"], tot["fga"]), 3)}
        ff[t] = f4
        players = []
        usg_den = tot["fga"] + 0.44 * tot["fta"] + tot["tov"]
        for r in rows:
            sec = float(r.get("sec") or 0)
            pid = str(r["player_id"])
            fga, fta, tov = float(r.get("fga") or 0), float(r.get("fta") or 0), float(r.get("tov") or 0)
            f = sec / max(tot["sec"] / 5.0, 1.0)
            gs = ((r.get("pts") or 0) + 0.4 * (r.get("fgm") or 0) - 0.7 * fga - 0.4 * (fta - (r.get("ftm") or 0)) + 0.7 * (r.get("oreb") or 0)
                  + 0.3 * (r.get("dreb") or 0) + (r.get("stl") or 0) + 0.7 * (r.get("ast") or 0) + 0.7 * (r.get("blk") or 0)
                  - 0.4 * (r.get("pf") or 0) - tov)
            info = ctx.players.get(pid) or {}
            players.append({"id": pid, "name": info.get("name") or pid, "pos": info.get("pos"), "starter": bool(r.get("starter")),
                            "min": round(sec / 60.0, 1), "pts": r.get("pts"), "fgm": r.get("fgm"), "fga": r.get("fga"), "tpm": r.get("tpm"),
                            "tpa": r.get("tpa"), "ftm": r.get("ftm"), "fta": r.get("fta"), "oreb": r.get("oreb"), "dreb": r.get("dreb"),
                            "reb": (r.get("oreb") or 0) + (r.get("dreb") or 0), "ast": r.get("ast"), "stl": r.get("stl"), "blk": r.get("blk"),
                            "tov": r.get("tov"), "pf": r.get("pf"), "pm": r.get("pm"),
                            "ts": an.rnd(an.div(r.get("pts") or 0, 2 * (fga + 0.44 * fta)), 3) if fga + fta > 0 else None,
                            "usg": an.rnd(an.div(fga + 0.44 * fta + tov, f * usg_den), 3) if sec > 0 and usg_den > 0 else None,
                            "game_score": round(gs, 1) if sec > 0 else None,
                            "wpa": an.rnd(((wpa or {}).get(pid) or {}).get("wpa"), 4) if wpa else None,
                            "pox": an.rnd((pox or {}).get(pid), 2) if pox else None})
        team = {k: tb.get(k) for k in tb}
        team.update({**{k: int(v) for k, v in tot.items() if k != "sec"}, "pts": pts, "poss": an.rnd(poss, 1),
                     "pace": an.rnd(poss * (2400 if ctx.league == "wnba" else 2880) / secs, 1),
                     "ortg": an.rnd(an.per100(pts, poss), 1) if pts is not None else None, **{f"ff_{k}": v for k, v in f4.items()}})
        out[t] = {"players": players, "team": team, "dnp": [{"id": str(r[0]), "name": an.player_name(ctx.store, r[0]),
                                                             "reason": r[1] if len(r) > 1 else None}
                                                            for r in (box.get(t) or {}).get("dnp") or []]}
    return out, ff


# ---------------------------------------------------------------------------------------------- play-by-play blocks

def _t(league: str, period: int, clock: float) -> float:
    return float(_io.period_start(league, period) + _io.period_len(league, period) - float(clock or 0))


def flow_series(ge) -> list[list]:
    out = [[0.0, 0]]
    for e in ge.events:
        if e.get("pts") and e.get("team") in (ge.home, ge.away):
            m = (e["hs_before"] - e["as_before"]) + (e["pts"] if e["team"] == ge.home else -e["pts"])
            out.append([round(float(e["t"]), 1), int(m)])
    return out


def wp_series(league: str, wres: dict) -> dict:
    model, espn = [[0, an.rnd(wres.get("wp0"), 3)]], []
    last, last_e = None, None
    plays = wres.get("plays") or []
    for k, p in enumerate(plays):
        t = int(round(_t(league, p["period"], p["clock_s"])))
        w = an.rnd(p["wp"], 3)
        if last is None or abs((w or 0) - last) >= WP_STEP or k == len(plays) - 1:
            model.append([t, w])
            last = w
        e = p.get("espn_wp")
        if e is not None and not (isinstance(e, float) and math.isnan(e)):
            e = an.rnd(e, 3)
            if last_e is None or abs(e - last_e) >= WP_STEP or k == len(plays) - 1:
                espn.append([t, e])
                last_e = e
    if wres.get("home_win") is not None and plays:
        model.append([int(round(_t(league, plays[-1]["period"], 0.0))), float(wres["home_win"])])
    if len(model) > MAX_WP_POINTS:
        step = int(math.ceil(len(model) / MAX_WP_POINTS))
        model = model[::step] + [model[-1]]
    if len(espn) > MAX_WP_POINTS:
        step = int(math.ceil(len(espn) / MAX_WP_POINTS))
        espn = espn[::step] + [espn[-1]]
    return {"model": model, "espn": espn or None}


def shots_block(ctx: SeasonContext, df: pd.DataFrame) -> tuple[dict | None, dict | None, dict]:
    """(shots {"cols","rows"}, shot_quality {tid: {"xpts","pts","pox","xefg","shots"}}, pox by player)."""
    from oddsmarkets.basketball.models import shots as SH
    if df is None or df.empty:
        return None, None, {}
    df = SH.as_shots(df)
    if ctx.xmodel:
        df = SH.with_xpts(df, ctx.xmodel)
    else:
        df["xpts"] = np.nan
        df["pts"] = df["made"] * df["value"]
    rows = []
    for r in df.itertuples(index=False):
        rows.append([an.rnd(r.t, 1), str(r.team), str(r.shooter), an.rnd(r.x_ft, 1), an.rnd(r.y_ft, 1), int(r.value), int(r.made),
                     an.rnd(r.xpts, 3), r.zone, r.shot_type, int(r.assisted)])
    sq = {}
    for t, s in df.groupby("team"):
        xs = float(s["xpts"].sum()) if s["xpts"].notna().any() else None
        sq[str(t)] = {"shots": int(len(s)), "pts": int(s["pts"].sum()), "xpts": an.rnd(xs, 2),
                      "pox": an.rnd(float(s["pts"].sum()) - xs, 2) if xs is not None else None,
                      "xefg": an.rnd(xs / len(s) / 2.0, 3) if xs is not None and len(s) else None}
    pox = {}
    if df["xpts"].notna().any():
        g = df.groupby("shooter")
        for pid, s in g:
            pox[str(pid)] = float(s["pts"].sum() - s["xpts"].sum())
        pox["_n"] = {str(p): int(len(s)) for p, s in g}
    return {"cols": SHOT_OUT_COLS, "rows": rows}, sq, pox


def lineup_block(ts: pd.DataFrame, g: dict) -> tuple[dict | None, dict | None]:
    if ts is None or ts.empty:
        return None, None
    out = {}
    for t in (str(g.get("home")), str(g.get("away"))):
        units = LU.lineup_table(ts, t, 5, None, min_poss=0.0)
        out[t] = [{"players": u["players"], "sec": an.rnd(u["sec"], 0), "poss": an.rnd(u["poss"], 1), "pts_for": int(u["pts_for"]),
                   "pts_against": int(u["pts_against"]), "net": an.rnd(u["net"], 1)} for u in units[:MAX_UNITS]]
    return out, LU.rotation(ts, str(g.get("id")))


def plays_block(league: str, wres: dict, raw: dict, ge) -> list[dict]:
    rows = wres.get("plays") or []
    raw_by_seq = {}
    for p in (raw or {}).get("plays") or []:
        raw_by_seq[p[0]] = p
    reg = 4
    keep = set(sorted(range(len(rows)), key=lambda k: -abs(rows[k]["dwp"]))[:MAX_PLAYS])
    scoring = {k for k, r in enumerate(rows) if int(r["period"]) >= reg and (raw_by_seq.get(r["seq"]) or [None] * 11)[10]}
    out = []
    for k in sorted(keep | scoring):
        r = rows[k]
        rp = raw_by_seq.get(r["seq"]) or []
        score = f"{rp[11]}-{rp[12]}" if len(rp) > 12 and rp[11] is not None else None
        cr = r.get("credit") or {}
        out.append({"t": int(round(_t(league, r["period"], r["clock_s"]))), "period": int(r["period"]), "clock": an.rnd(r["clock_s"], 1),
                    "team": r.get("team"), "text": r.get("text"), "score": score,
                    "wpa": an.rnd(r["dwp"] if (r.get("team") in (None, ge.home)) else -r["dwp"], 4),
                    "dwp_home": an.rnd(r["dwp"], 4), "wp": an.rnd(r["wp"], 3), "li": an.rnd(r.get("li"), 1),
                    "players": list(cr.keys()), "credit": [an.rnd(c, 4) for c in cr.values()]})
    return out


def awards_block(ctx: SeasonContext, g: dict, box: dict, wres: dict | None, pox: dict, sq: dict | None, summ: dict | None) -> dict:
    h, a = str(g.get("home")), str(g.get("away"))
    pl = [(t, p) for t in (h, a) for p in (box.get(t) or {}).get("players") or [] if p.get("min")]
    wpa_p = (wres or {}).get("players") or {}
    out: dict[str, Any] = {"player_of_game": None, "biggest_swing": None, "shot_maker": None, "unluckiest": None, "stopper": None,
                           "excitement": an.rnd((wres or {}).get("excitement"), 3), "comeback": an.rnd((wres or {}).get("comeback"), 4)}
    if pl:
        def score(tp):
            t, p = tp
            return (p.get("game_score") or 0.0) + 20.0 * float((wpa_p.get(p["id"]) or {}).get("wpa") or 0.0)
        t, p = max(pl, key=score)
        w = (wpa_p.get(p["id"]) or {}).get("wpa")
        out["player_of_game"] = {"player": p["id"], "team": t, "value": round(score((t, p)), 1), "label": "Player of the game",
                                 "why": f"{p.get('pts')} pts, {p.get('reb')} reb, {p.get('ast')} ast, Game Score {p.get('game_score')}"
                                        + (f", WPA {w:+.2f}" if w is not None else "")}
    if wres and wres.get("plays"):
        r = max(wres["plays"], key=lambda r: abs(r["dwp"]))
        cr = r.get("credit") or {}
        who = max(cr, key=lambda k: abs(cr[k])) if cr else None
        team_of = {p["id"]: t for t, p in pl}
        out["biggest_swing"] = {"player": who, "team": team_of.get(who) or r.get("team"), "value": an.rnd(abs(r["dwp"]), 4),
                                "label": "Biggest swing", "why": f"{r.get('text')} (home WP {r['wp'] - r['dwp']:.0%} to {r['wp']:.0%})"}
    n = pox.get("_n") or {}
    cands = [(pid, v) for pid, v in pox.items() if pid != "_n" and n.get(pid, 0) >= 5]
    if cands:
        pid, v = max(cands, key=lambda kv: kv[1])
        team_of = {p["id"]: t for t, p in pl}
        out["shot_maker"] = {"player": pid, "team": team_of.get(pid), "value": an.rnd(v, 2), "label": "Shot maker",
                             "why": f"{v:+.1f} points over expected on {n.get(pid)} shots"}
    if sq and all(sq.get(t, {}).get("xpts") is not None for t in (h, a)) and g.get("hs") is not None:
        ft = {t: (box.get(t) or {}).get("team", {}).get("ftm") or 0 for t in (h, a)}
        luck = {}
        for t, o in ((h, a), (a, h)):
            exp = (sq[t]["xpts"] + ft[t]) - (sq[o]["xpts"] + ft[o])
            real = (g["hs"] - g["as"]) * (1 if t == h else -1)
            luck[t] = (real - exp, exp, real)
        t = min(luck, key=lambda k: luck[k][0])
        lv, exp, real = luck[t]
        out["unluckiest"] = {"player": None, "team": t, "value": an.rnd(lv, 2), "label": "Unluckiest",
                             "why": f"expected margin {exp:+.1f} from shot quality, real {real:+d}"}
    dw = ((summ or {}).get("wpa") or {})
    if dw:
        pid = max(dw, key=lambda k: dw[k].get("dwpa") or 0.0)
        v = dw[pid].get("dwpa") or 0.0
        if v > 0:
            out["stopper"] = {"player": pid, "team": dw[pid].get("team"), "value": an.rnd(v, 4), "label": "Stopper",
                              "why": f"defensive WPA {v:+.3f} (blocks, steals and stops credited on the other team's plays)"}
    if out["stopper"] is None and pl:
        t, p = max(pl, key=lambda tp: (tp[1].get("stl") or 0) + (tp[1].get("blk") or 0))
        sb = (p.get("stl") or 0) + (p.get("blk") or 0)
        if sb:
            out["stopper"] = {"player": p["id"], "team": t, "value": sb, "label": "Stopper", "why": f"{p.get('stl')} steals, {p.get('blk')} blocks"}
    return out


# ---------------------------------------------------------------------------------------------- the page

def build_game(ctx: SeasonContext, gid: str, parsed: dict | None = None) -> dict:
    g = (ctx.store.get("games") or {}).get(str(gid))
    if not g:
        return {"ok": False, "reason": f"game {gid} not in the store", "id": str(gid)}
    h, a = str(g.get("home")), str(g.get("away"))
    _inj_model, inj_payload = injury_inputs(ctx, g)
    pregame = {"model": _safe(lambda: model_line(ctx, g)), "market": _safe(lambda: market_line(ctx, g)), "injuries": inj_payload,
               "elo_p_home": _safe(lambda: elo_p(ctx, g))}
    wres = (parsed or {}).get("wpa")
    d = (parsed or {}).get("derive")
    summ = (ctx.pbp_summaries or {}).get(str(gid))
    shots_df = None
    ts = None
    if d is not None:
        shots_df = pd.DataFrame(d["shots"], columns=_io.SHOT_COLS) if d.get("shots") else None
        if d.get("stints"):                                   # pbp.derive gives stints.json rows (STINT_COLS)
            ts = LU.team_stints(LU.stint_frame({"cols": _io.STINT_COLS, "rows": d["stints"]}), ctx.store.get("games") or {})
    else:
        sh = ctx.shots
        if sh is not None and not sh.empty:
            sub = sh[sh["game_id"].astype(str) == str(gid)]
            shots_df = sub[_io.SHOT_COLS] if len(sub) else None
        st = ctx.team_stints
        if st is not None and not st.empty:
            sub = st[st["game_id"].astype(str) == str(gid)]
            ts = sub if len(sub) else None
    shots, sq, pox = _safe(lambda: shots_block(ctx, shots_df), (None, None, {})) or (None, None, {})
    box, ff = box_block(ctx, g, (wres or {}).get("players"), {k: v for k, v in pox.items() if k != "_n"})
    lineups, rot = _safe(lambda: lineup_block(ts, g), (None, None)) or (None, None)
    out = {"ok": True, "id": str(gid), "league": ctx.league, "season": ctx.season, "date": g.get("date"), "status": g.get("status"),
           "stype": g.get("stype"), "home": h, "away": a, "hs": g.get("hs"), "as": g.get("as"), "periods": g.get("periods"),
           "neutral": bool(g.get("neutral")), "line": g.get("line"), "series": _series(ctx, g), "venue": g.get("venue"),
           "attendance": g.get("attendance"),
           "teams": {t: an.team_info(ctx.store, t) for t in (h, a)},
           "pregame": pregame, "box": box if g.get("box") else {}, "four_factors": ff if g.get("box") else {},
           "flow": None, "wp": None, "shots": shots, "shot_quality": sq, "lineups": lineups, "rotation": rot, "plays": None,
           "awards": None, "has_pbp": bool(d is not None)}
    if d is not None:
        ge = d["events"]
        out["flow"] = _safe(lambda: flow_series(ge))
        if wres:
            out["wp"] = _safe(lambda: wp_series(ctx.league, wres))
            out["plays"] = _safe(lambda: plays_block(ctx.league, wres, (parsed or {}).get("raw"), ge))
    if g.get("status") == "post" and g.get("box"):
        out["awards"] = _safe(lambda: awards_block(ctx, g, box, wres, pox, sq, summ))
    out["updated_at"] = an.now()
    return out


def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("game block failed: %s", exc, exc_info=True)
        return default


# ---------------------------------------------------------------------------------------------- cards

def _av_card(m: dict) -> dict:
    """{"av": [home, away]}: the informed model's availability term for each team, in points of that team's OWN
    margin (expected rotation against what its rating already reflects, injury-report Outs applied); {} for the
    base model."""
    det = m.get("detail") or {}
    h, a = det.get("injury_home"), det.get("injury_away")
    if m.get("model") != "informed" or h is None or a is None:
        return {}
    return {"av": [an.rnd(h, 2), an.rnd(-a, 2)]}


def card(ctx: SeasonContext, g: dict, live: dict | None = None) -> dict:
    m = _safe(lambda: model_line(ctx, g)) or {}
    mk = _safe(lambda: market_line(ctx, g))
    line = g.get("line") or {}
    period = len(line.get("home") or []) or None
    return {"id": str(g.get("id")), "season": ctx.season, "date": g.get("date"), "status": g.get("status"), "stype": g.get("stype"), "home": str(g.get("home")),
            "away": str(g.get("away")), "hs": g.get("hs"), "as": g.get("as"), "period": period if g.get("status") == "in" else
            (g.get("periods") if g.get("status") == "post" else None), "clock": (live or {}).get("clock"),
            "model": {"p_home": m.get("p_home"), "margin": an.rnd(m.get("margin"), 2), "total": an.rnd(m.get("total"), 1),
                      **_av_card(m)} if m else None,
            "market": {k: mk.get(k) for k in ("p_home", "spread_home", "total", "sources")} if mk else None,
            "wp_home": (live or {}).get("wp_home"), "espn_wp": (live or {}).get("espn_wp"), "series": _series(ctx, g)}


def _series(ctx: SeasonContext, g: dict) -> dict | None:
    """The game's series block with the round's normalised name (season.series_round: WNBA "Playoff Series" ->
    Semi-finals / WNBA Finals)."""
    from oddsmarkets.basketball.analytics.season import series_round
    return _safe(lambda: series_round(ctx, g), g.get("series"))


def live_state(ctx: SeasonContext, g: dict) -> dict | None:
    """Model and ESPN win probability at the latest play of an in-progress game (needs its raw play-by-play)."""
    from oddsmarkets.basketball import store as bst
    from oddsmarkets.basketball.models import winprob as W
    if g.get("status") != "in" or not ctx.wp_model:
        return None
    raw = bst.load_pbp(ctx.league, ctx.season, str(g.get("id")))
    if not raw:
        return None
    st = W.states_from_pbp(raw, g, None, ctx.league)
    if st.empty:
        return None
    last = st.iloc[-1]
    wp = float(W.wp(ctx.wp_model, st.iloc[[-1]])[0])
    e = last.get("espn_wp")
    m, s = divmod(int(float(last["clock_s"])), 60)
    return {"wp_home": round(wp, 4), "espn_wp": an.rnd(e, 4) if e is not None and e == e else None, "clock": f"{m}:{s:02d}"}


def cards(ctx: SeasonContext, today: date) -> dict:
    """{"today","next_games" (next 3 days),"last_games" (last 2 days)} for the league hub."""
    out = {"today": [], "next_games": [], "last_games": []}
    for gid, g in sorted(ctx.games.items(), key=lambda kv: str(kv[1].get("date") or "")):
        d = _day(g)
        if d is None:
            continue
        live = _safe(lambda: live_state(ctx, g)) if g.get("status") == "in" else None
        if d == today:
            out["today"].append(card(ctx, g, live))
        elif today < d <= today + timedelta(days=3):
            out["next_games"].append(card(ctx, g))
        elif today - timedelta(days=2) <= d < today:
            out["last_games"].append(card(ctx, g))
    return out
