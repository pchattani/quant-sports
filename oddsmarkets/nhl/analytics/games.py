"""
Game cards (GAME_CARD in PAYLOADS.md) and game centre pages (data/<S>/games/<game_id>.json).

A page carries: the card; the pre-game block (model v market v line: win, regulation, OT, puck line, total, score
distribution; goalie starters); the linescore by period (goals, shots, xG); the shot map (cols period, sec, team,
player, x, y, type, shot_type, xg, goal, strength); the xG race; the win-probability series (builder C's live model,
else this layer's Poisson fallback from the pre-game goal expectations, flagged "source"); shift-based line usage
and TOI by strength; the box with advanced stats (individual xG, shots, hits, blocks, giveaways / takeaways,
faceoffs, TOI by strength, on-ice 5v5 xGF%, CF%) for skaters and goalies (GSAx); and game awards (three stars by
game score, top xG, best line).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl import analytics as an
from oddsmarkets.nhl.analytics import box
from oddsmarkets.nhl.analytics.context import BLOCK, CORSI, FENWICK, GOAL, SHOT

LG_GOALS = 3.05                       # goals per team per game (fallback expectation)
TYPE_CODE = {GOAL: "goal", SHOT: "shot", "MISS": "miss", BLOCK: "block"}


# ---------------------------------------------------------------------------------------------- cards

def american_to_prob(o: Any) -> float | None:
    x = an.fnum(o)
    if x is None or x == 0:
        return None
    if abs(x) < 50:                         # decimal odds
        return 1 / x if x > 1 else None
    return 100 / (x + 100) if x > 0 else -x / (-x + 100)


def line_block(g: dict) -> dict | None:
    """GAME.lines (builder A: {"src", "ml": [home, away], "puck_line": {"home", "price": [h, a]}, "total": {"line", "over",
    "under"}, "open": {...}, "close": {...}, "books": [...]}) -> the card's line block."""
    ln = g.get("lines")
    if not isinstance(ln, dict):
        return None
    ml_h, ml_a, pl, tot = _ml_pl_tot(ln)
    out = {"ml_home": ml_h, "ml_away": ml_a, "puck_line": pl, "total": tot, "src": ln.get("src"),
           "open": _compact_line(ln.get("open")), "close": _compact_line(ln.get("close"))}
    if all(out[k] is None for k in ("ml_home", "ml_away", "puck_line", "total", "open", "close")):
        return None
    return out


def _ml_pl_tot(ln: dict) -> tuple:
    ml = ln.get("ml")
    if isinstance(ml, (list, tuple)) and len(ml) >= 2:
        ml_h, ml_a = ml[0], ml[1]
    elif isinstance(ml, dict):
        ml_h, ml_a = ml.get("home"), ml.get("away")
    else:
        ml_h, ml_a = ln.get("ml_home"), ln.get("ml_away")
    pl = ln.get("puck_line")
    if isinstance(pl, dict):
        pl = pl.get("home") if pl.get("home") is not None else pl.get("line")
    tot = ln.get("total")
    if isinstance(tot, dict):
        tot = tot.get("line") if tot.get("line") is not None else tot.get("total")
    return an.fnum(ml_h), an.fnum(ml_a), an.fnum(pl), an.fnum(tot)


def _compact_line(x: Any) -> dict | None:
    if not isinstance(x, dict):
        return None
    ml_h, ml_a, pl, tot = _ml_pl_tot(x)
    if ml_h is None and ml_a is None and pl is None and tot is None:
        return None
    return {"ml_home": ml_h, "ml_away": ml_a, "puck_line": pl, "total": tot}


def starters(g: dict) -> dict:
    """{"home": pid, "away": pid} from GAME.goalies ({"home": {"starter", "used", "decision"}} or plain ids). Before the
    start, with no starter recorded, the probable starters instead (`probable_goalies`)."""
    gl = g.get("goalies") or {}
    out = {}
    for side in ("home", "away"):
        v = gl.get(side)
        out[side] = an.sid(v.get("starter") or v.get("id")) if isinstance(v, dict) else an.sid(v)
    if not out.get("home") and not out.get("away"):
        pb = probable_goalies(g)
        if pb:
            return {side: pb.get(side) for side in ("home", "away")}
    return out


def probable_goalies(g: dict) -> dict | None:
    """{"home"|"away": {"pid", "name", "status" ("confirmed" | "projected"), "at" (when it was first seen with that
    status), "src": "ESPN"}} from GAME.probables for a game that has not started; None otherwise."""
    pb = g.get("probables")
    if not isinstance(pb, dict) or g.get("status") not in (None, "scheduled"):
        return None
    out = {}
    for side in ("home", "away"):
        r = pb.get(side)
        if not isinstance(r, dict) or not r.get("name"):
            continue
        conf = r.get("status") == "confirmed"
        out[side] = {"pid": an.sid(r.get("id")) if r.get("id") else None, "name": r.get("name"),
                     "status": "confirmed" if conf else "projected",
                     "at": (r.get("confirmed_at") if conf else None) or r.get("since"), "src": "ESPN"}
    return out or None


def market_from_line(line: dict | None) -> dict | None:
    """De-vigged home win probability from the store's moneylines."""
    if not line:
        return None
    ph, pa = american_to_prob(line.get("ml_home")), american_to_prob(line.get("ml_away"))
    if ph is None or pa is None or ph + pa <= 0:
        return None
    return {"p_home": round(ph / (ph + pa), 4), "sources": ["line"]}


def model_block(pr: dict | None) -> dict | None:
    if not pr or pr.get("p_home") is None:
        return None
    return {"p_home": an.rnd(pr.get("p_home"), 4), "p_reg_home": an.rnd(pr.get("p_reg_home"), 4), "p_ot": an.rnd(pr.get("p_ot"), 4),
            "total": an.rnd(pr.get("total") if pr.get("total") is not None else
                            ((pr.get("home_goals") or 0) + (pr.get("away_goals") or 0) if pr.get("home_goals") is not None else None), 2),
            "puck_line_home": an.rnd(pr.get("puck_line_home"), 4), "source": pr.get("source") or "game"}


def card(g: dict, model: dict | None = None, market: dict | None = None, xg: dict | None = None, wp: float | None = None) -> dict:
    line = line_block(g)
    return {"game_id": g.get("game_id"), "date": str(g.get("date") or "")[:10] or None, "start": g.get("start"), "status": g.get("status"),
            "period": g.get("period"), "clock": g.get("clock"), "home": g.get("home"), "away": g.get("away"),
            "hs": an.inum(g.get("hs")), "as": an.inum(g.get("as")), "ot": bool(g.get("ot")), "so": bool(g.get("so")),
            "type": g.get("gtype"), "series": g.get("series"), "goalies": starters(g),
            "model": model_block(model), "market": market or market_from_line(line), "line": line, "wp_home": wp, "xg": xg}


def xg_by_game(ev: pd.DataFrame) -> dict[str, dict]:
    """{game_id: {"home","away"}} all-situation xG (empty-net attempts excluded)."""
    if not len(ev) or "xg" not in ev:
        return {}
    E = ev[ev["type"].isin(FENWICK).to_numpy() & (ev["st"] != "EN").to_numpy()]
    if not len(E):
        return {}
    s = E.groupby(["game_id", "is_home"])["xg"].sum()
    out: dict[str, dict] = {}
    for (gid, ih), v in s.items():
        out.setdefault(gid, {"home": 0.0, "away": 0.0})["home" if ih == 1 else "away"] = round(float(v), 2)
    return out


# ---------------------------------------------------------------------------------------------- win probability

def _pois_cdf_tables(lam: float, n: int = 15) -> np.ndarray:
    k = np.arange(n + 1)
    return np.exp(-lam) * lam ** k / np.array([math.factorial(int(i)) for i in k])


def wp_poisson(diff: int, sec_left: float, lam_h: float, lam_a: float, p_ot_home: float = 0.5) -> float:
    """P(home wins) with a goal difference (home - away) and sec_left regulation seconds: independent Poisson
    goals over the remaining time at the pre-game rates; a tie goes to overtime won by home with p_ot_home."""
    f = max(sec_left, 0.0) / 3600.0
    ph = _pois_cdf_tables(lam_h * f)
    pa = _pois_cdf_tables(lam_a * f)
    M = np.outer(ph, pa)
    i, j = np.indices(M.shape)
    d = diff + i - j
    win = M[d > 0].sum()
    tie = M[d == 0].sum()
    return float(win + tie * p_ot_home)


def wp_series(evg: pd.DataFrame, g: dict, pre: dict | None) -> dict:
    """Fallback WP: at the start, after every goal and at each minute mark (regulation; OT at the pre-game OT edge)."""
    ph = (pre or {}).get("p_home")
    tot = (pre or {}).get("total") or 2 * LG_GOALS
    lam_h = (pre or {}).get("home_goals") or tot / 2
    lam_a = (pre or {}).get("away_goals") or tot / 2
    if ph is not None and (pre or {}).get("home_goals") is None:
        # tilt the split so the start-of-game WP matches the model's
        lo, hi = 0.2, 0.8
        for _ in range(30):
            mid = (lo + hi) / 2
            if wp_poisson(0, 3600, tot * mid, tot * (1 - mid)) < ph:
                lo = mid
            else:
                hi = mid
        lam_h, lam_a = tot * (lo + hi) / 2, tot * (1 - (lo + hi) / 2)
    p_ot = 0.5 + 0.5 * ((lam_h - lam_a) / max(lam_h + lam_a, 1e-6))
    goals = evg[(evg["type"] == GOAL).to_numpy()] if len(evg) else evg
    gl = [(float(r.sec), 1 if r.is_home == 1 else -1) for r in goals.itertuples(index=False)
          if r.sec == r.sec and (int(r.period or 0) < 5 or str(g.get("game_id", ""))[4:6] == "03")]
    times = sorted(set([0.0] + [t for t, _ in gl] + list(np.arange(60, 3600, 60.0))))
    out = []
    for t in times:
        d = sum(s for tt, s in gl if tt <= t)
        if t >= 3600:
            break
        out.append([int(t), round(wp_poisson(d, 3600 - t, lam_h, lam_a, p_ot), 4)])
    if g.get("status") == "final" and g.get("hs") is not None and g.get("as") is not None:
        end = max(3600.0, max((t for t, _ in gl), default=3600.0))
        out.append([int(end), 1.0 if g["hs"] > g["as"] else 0.0])
    return {"source": "poisson", "series": out, "now": out[-1][1] if out else None}


# ---------------------------------------------------------------------------------------------- pages

def page_sig(g: dict, n_events: int, mv: dict, stint_s: int | None = None) -> str:
    keys = {k: g.get(k) for k in ("status", "hs", "as", "period", "clock", "ot", "so", "goalies", "lines", "attendance", "start")}
    if g.get("probables"):                      # only games that have them: other pages keep their signatures
        keys["probables"] = g.get("probables")
    if stint_s is not None:
        # seconds covered by the game's shift charts: the stats REST shift charts often arrive incomplete right after a
        # game and are re-read until they settle, with the same play-by-play; without this the page kept the early
        # build's ice times (Oct 2026 audit: MTL-SJS 20 Oct showed both goalies at 49 min of 62, skaters 246 of 303)
        keys["st"] = int(stint_s)
    keys["n"] = n_events
    keys["mv"] = mv
    return hashlib.sha1(json.dumps(an.clean(keys), sort_keys=True, default=str).encode()).hexdigest()[:16]


def game_score_skater(r: dict) -> float:
    f = lambda k: float(r.get(k) or 0.0)  # noqa: E731
    return (0.75 * f("g") + 0.7 * f("a1") + 0.55 * f("a2") + 0.075 * f("sog") + 0.05 * f("blocks") + 0.15 * f("pen_drawn")
            - 0.15 * f("pen_taken") + 0.01 * f("fow") - 0.01 * f("fol") + 0.05 * f("cf_5v5") - 0.05 * f("ca_5v5")
            + 0.15 * f("gf_5v5") - 0.15 * f("ga_5v5"))


def build_page(ctx, g: dict, evg: pd.DataFrame | None, stg: pd.DataFrame | None, pgg: pd.DataFrame | None, ggg: pd.DataFrame | None,
               card_: dict, pregame: dict | None, old: dict | None, pos: dict) -> dict:
    gid = g["game_id"]
    home, away = g.get("home"), g.get("away")
    out: dict = {"ok": True, "game_id": gid, "season": ctx.season, "updated_at": an.now(), "card": card_,
                 "venue": g.get("venue"), "attendance": g.get("attendance"), "type": g.get("gtype"),
                 "teams": {t: {"abbr": t, "name": ctx.name(t), "colour": (ctx.teams.get(t) or {}).get("colour")} for t in (home, away) if t},
                 "pregame": pregame, "xg_source": ctx.xg_source}
    have_ev = evg is not None and len(evg)
    if not have_ev and old and old.get("ok") and old.get("shots"):
        # never downgrade: keep the event-level blocks of a page built where the events were on disk
        for k in ("linescore", "shots", "xg_race", "wp", "usage", "box", "awards", "lines"):
            if k in old:
                out[k] = old[k]
        out["kept_from"] = old.get("updated_at")
        return out
    if not have_ev:
        out["linescore"] = None
        return out
    names = lambda p: ctx.player_name(an.sid(p)) or an.sid(p)  # noqa: E731
    # linescore
    E = evg
    per = E["period"].fillna(0).astype(int).to_numpy()
    ls = []
    for p_ in sorted(set(per[per > 0])):
        m = per == p_
        row = {"period": int(p_)}
        for side, hv in (("home", 1.0), ("away", 0.0)):
            mm = m & (E["is_home"].to_numpy(float) == hv)
            t = E["type"].to_numpy(object)
            row[f"g_{side}"] = int((mm & (t == GOAL)).sum())
            row[f"s_{side}"] = int((mm & np.isin(t, (GOAL, SHOT))).sum())
            row[f"xg_{side}"] = round(float(np.nansum(np.where(mm & np.isin(t, FENWICK), E["xg"].to_numpy(float), 0.0))), 2)
        ls.append(row)
    out["linescore"] = ls
    # shot map
    S = E[E["type"].isin(CORSI).to_numpy()]
    cols = ["period", "sec", "team", "player", "x", "y", "type", "shot_type", "xg", "goal", "strength"]
    rows = []
    for r in S.itertuples(index=False):
        rows.append([int(r.period) if r.period == r.period else None, int(r.sec) if r.sec == r.sec else None, r.team,
                     an.sid(r.p1), an.rnd(r.x, 1), an.rnd(r.y, 1), TYPE_CODE.get(r.type, r.type),
                     getattr(r, "shot_type", None) if isinstance(getattr(r, "shot_type", None), str) else None,
                     an.rnd(r.xg, 4), 1 if r.type == GOAL else 0, r.state])
    out["shots"] = {"cols": cols, "rows": rows, "players": {an.sid(p): names(p) for p in S["p1"].dropna().unique()}}
    # xG race
    F = E[E["type"].isin(FENWICK).to_numpy()]
    race = [[0, 0.0, 0.0, None]]
    ch = ca = 0.0
    for r in F.itertuples(index=False):
        x = float(r.xg) if r.xg == r.xg else 0.0
        if r.is_home == 1:
            ch += x
        else:
            ca += x
        race.append([int(r.sec) if r.sec == r.sec else None, round(ch, 3), round(ca, 3), (home if r.is_home == 1 else away) if r.type == GOAL else None])
    out["xg_race"] = {"cols": ["sec", "home", "away", "goal"], "rows": race}
    # win probability
    from oddsmarkets.nhl.analytics import adapters
    model_pre = (pregame or {}).get("model") if pregame else None
    wp = adapters.live_wp(ctx, g, E, model_pre)
    if not wp or not wp.get("series"):
        wp = wp_series(E, g, model_pre)
    else:
        wp["source"] = "live"
    out["wp"] = wp
    # usage / TOI by strength and lines (from stints)
    out["usage"] = _usage(pgg, pos, names)
    out["lines"] = _game_lines(E, stg, pos, names, home, away)
    # box
    out["box"] = _box(pgg, ggg, pos, names, home, away)
    out["awards"] = _awards(out["box"], out["lines"])
    return out


def _usage(pgg: pd.DataFrame | None, pos: dict, names) -> dict:
    if pgg is None or not len(pgg):
        return {}
    out = {}
    for t, D in pgg.groupby("team"):
        rows = []
        for r in D.sort_values("toi", ascending=False).to_dict("records"):
            rows.append({"id": an.sid(r["pid"]), "name": names(r["pid"]), "pos": pos.get(r["pid"], "F"),
                         "toi": round(r.get("toi", 0) / 60, 2), "toi_5v5": round(r.get("toi_5v5", 0) / 60, 2),
                         "toi_pp": round(r.get("toi_PP", 0) / 60, 2), "toi_sh": round(r.get("toi_SH", 0) / 60, 2),
                         "shifts": int(r.get("shifts", 0))})
        out[t] = rows
    return out


def _game_lines(E: pd.DataFrame, stg: pd.DataFrame | None, pos: dict, names, home, away) -> dict:
    if stg is None or not len(stg):
        return {}
    C = box.combos(E, stg, pos)
    out = {}
    from oddsmarkets.nhl.analytics.teams import line_row
    nm = {}
    for t in (home, away):
        K = C[C["team"] == t]
        res = {}
        for kind, key, n in (("F", "forwards", 4), ("D", "pairs", 3)):
            rows = []
            for r in K[K["kind"] == kind].sort_values("toi", ascending=False).head(n).itertuples(index=False):
                ids = r.key.split("-")
                for i in ids:
                    nm[i] = names(float(i))
                rows.append(line_row(ids, r, nm))
            res[key] = rows
        out[t] = res
    return out


def _box(pgg: pd.DataFrame | None, ggg: pd.DataFrame | None, pos: dict, names, home, away) -> dict:
    out = {"skaters": {}, "goalies": {}, "skater_cols": ["id", "name", "pos", "g", "a", "p", "sog", "ixg", "icf", "hits", "blocks", "give",
                                                            "take", "fow", "fol", "pim", "toi", "toi_5v5", "toi_pp", "toi_sh", "xgf_pct",
                                                            "cf_pct", "xgf", "xga", "gs"],
           "goalie_cols": ["id", "name", "sa", "ga", "sv_pct", "xga", "gsax", "toi"]}
    if pgg is not None and len(pgg):
        for t, D in pgg.groupby("team"):
            rows = []
            for r in D.to_dict("records"):
                xf, xa = r.get("xgf_5v5", 0.0), r.get("xga_5v5", 0.0)
                cf, ca = r.get("cf_5v5", 0.0), r.get("ca_5v5", 0.0)
                a = r.get("a1", 0.0) + r.get("a2", 0.0)
                rows.append([an.sid(r["pid"]), names(r["pid"]), pos.get(r["pid"], "F"), int(r.get("g", 0)), int(a), int(r.get("g", 0) + a),
                             int(r.get("sog", 0)), round(r.get("ixg", 0.0), 2), int(r.get("icf", 0)), int(r.get("hits", 0)),
                             int(r.get("blocks", 0)), int(r.get("give", 0)), int(r.get("take", 0)), int(r.get("fow", 0)), int(r.get("fol", 0)),
                             int(r.get("pim", 0)), round(r.get("toi", 0) / 60, 2), round(r.get("toi_5v5", 0) / 60, 2),
                             round(r.get("toi_PP", 0) / 60, 2), round(r.get("toi_SH", 0) / 60, 2),
                             round(xf / (xf + xa), 3) if xf + xa else None, round(cf / (cf + ca), 3) if cf + ca else None,
                             round(xf, 2), round(xa, 2), round(game_score_skater(r), 2)])
            rows.sort(key=lambda x: -(x[16] or 0))
            out["skaters"][t] = rows
    if ggg is not None and len(ggg):
        for t, D in ggg.groupby("team"):
            out["goalies"][t] = [[an.sid(r["pid"]), names(r["pid"]), int(r.get("sa", 0)), int(r.get("ga", 0)),
                                  round(1 - r["ga"] / r["sa"], 3) if r.get("sa") else None, round(r.get("xga", 0.0), 2),
                                  round(r.get("xga", 0.0) - r.get("ga", 0.0), 2), round(r.get("toi", 0) / 60, 2)]
                                 for r in D.sort_values("toi", ascending=False).to_dict("records")]
    return out


def _awards(bx: dict, lines: dict) -> dict:
    cand = []
    for t, rows in (bx.get("skaters") or {}).items():
        for r in rows:
            cand.append({"id": r[0], "name": r[1], "team": t, "score": r[-1], "line": f"{r[3]}G {r[4]}A, {r[7]} ixG"})
    for t, rows in (bx.get("goalies") or {}).items():
        for r in rows:
            sv = (r[2] or 0) - (r[3] or 0)
            cand.append({"id": r[0], "name": r[1], "team": t, "score": round(-0.75 * (r[3] or 0) + 0.1 * sv, 2),
                         "line": f"{sv} saves, GSAx {r[6]}"})
    cand.sort(key=lambda x: -(x["score"] or 0))
    top_xg = None
    for t, rows in (bx.get("skaters") or {}).items():
        for r in rows:
            if top_xg is None or (r[7] or 0) > top_xg["ixg"]:
                top_xg = {"id": r[0], "name": r[1], "team": t, "ixg": r[7]}
    best_line = None
    for t, L in (lines or {}).items():
        for ln in (L or {}).get("forwards") or []:
            d = (ln.get("xgf") or 0) - (ln.get("xga") or 0)
            if best_line is None or d > best_line["xg_diff"]:
                best_line = {"team": t, "names": ln.get("names"), "ids": ln.get("ids"), "xg_diff": round(d, 2), "toi": ln.get("toi")}
    return {"stars": cand[:3], "top_xg": top_xg, "best_line": best_line,
            "method": "Game score: 0.75 G + 0.7 A1 + 0.55 A2 + 0.075 SOG + 0.05 BLK + 0.15 PD - 0.15 PT + 0.01 FOW - 0.01 FOL "
                      "+ 0.05 CF - 0.05 CA + 0.15 GF - 0.15 GA (5v5 on-ice terms); goalies -0.75 GA + 0.1 saves."}
