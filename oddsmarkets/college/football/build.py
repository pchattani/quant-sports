"""
Payload writer for college football (PAYLOADS.md, level `cfb`).

    build(season, out_dir, stores=None, *, full=True, sims=20000, markets=True) -> summary dict
        data/cfb/<S>/: season.json, schedule.json, cfp.json, teams.json, teams/<tid>.json, players.json,
        value.json, moves.json, fantasy.json, lab_players.json, lab_teams.json, games/<gid>.json
        (game pages: every game of the current season with an FBS team, and the previous season's postseason)
    build_level(out_dir, seasons, current, *, markets=True, careers=True) -> summary dict
        data/cfb/: calibration.json, history.json, markets.json, players/<pid>.json (careers of players with a
        game in the last two seasons)

`out_dir` is the site's data root (docs/campus/data, env CAMPUS_DATA); a path already ending in `cfb` is used
as the level directory. Every payload that cannot be built is written as {"ok": false, "reason"}.
`stores` is accepted for the orchestrator's signature; the stores are read through `store.load` (read-only).
"""
from __future__ import annotations

import json
import logging
import math
import os
import traceback
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from oddsmarkets.college import canon, store
from oddsmarkets.college import informed as INF

from . import (
    backtest,
    committee,
    data,
    ep,
    fantasy,
    game,
    market_informed,
    players,
    ratings,
    sim,
)

logger = logging.getLogger(__name__)
LEVEL = "cfb"
_CTX: dict[str, Any] = {}


# ── io helpers ──────────────────────────────────────────────────────────────

def _py(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _py(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_py(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _py(o.tolist())
    if o is pd.NaT:
        return None
    return o


def write(p: Path, obj: Any) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    s = json.dumps(_py(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(s, encoding="utf-8")
    os.replace(tmp, p)
    return len(s)


def level_dir(out_dir) -> Path:
    p = Path(out_dir) if out_dir else store.paths()["data"]
    return p if p.name == LEVEL else p / LEVEL


def r2(x, nd=2):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return round(f, nd) if math.isfinite(f) else None


def safe(name: str, fn: Callable, path: Path, sizes: dict) -> Any:
    try:
        obj = fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("cfb payload %s failed: %s", name, exc)
        logger.debug(traceback.format_exc())
        obj = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    sizes[name] = write(path, obj)
    return obj


# ── shared context ──────────────────────────────────────────────────────────

def context(current: int | None = None, use_cache: bool = True) -> dict:
    current = int(current or os.environ.get("CAMPUS_CFB_CURRENT") or canon.current_season(LEVEL))
    if _CTX.get("current") == current and _CTX.get("stores") == str(store.paths()["stores"]):
        return _CTX                       # one consistent snapshot of the inputs per process
    pipe = backtest.pipeline(current, use_cache=use_cache)
    if _CTX.get("key") == (pipe["key"], current):
        return _CTX
    _CTX.clear()
    comm = committee.fit_and_validate(pipe, use_cache=use_cache)
    _CTX.update({"key": (pipe["key"], current), "pipe": pipe, "comm": comm, "current": current, "seasons": {},
                 "stores": str(store.paths()["stores"]),
                 "values": {}, "sims": {}})
    return _CTX


def informed(ctx: dict, season: int) -> dict[str, dict]:
    """The market-informed model's predictions for `season` ({gid: ...}; market_informed.predict), {} when no fit is
    committed for it (past seasons keep the base model) or it fails (the base model still publishes)."""
    cache = ctx.setdefault("informed", {})
    if season not in cache:
        try:
            cache[season] = market_informed.predict(ctx["pipe"], season)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cfb market-informed model failed for %s: %s", season, exc)
            cache[season] = {}
    return cache[season]


def informed_block(inf: dict | None) -> dict | None:
    """The game page's view of the informed model: the published line and what moved it."""
    if not inf:
        return None
    return {"p_home": r2(inf["p_home"], 4), "margin": r2(inf["margin"]), "base_p": r2(inf["base_p"], 4),
            "base_margin": r2(inf["base_margin"]), "mk_spread": r2(-inf["mk"], 1) if np.isfinite(inf["mk"]) else None,
            "rd": r2(inf["rd"]) if np.isfinite(inf["rd"]) else None, "early": bool(inf["early"])}


def ep_fit(ctx: dict) -> dict:
    if "ep_fit" not in ctx:
        ctx["ep_fit"] = ep.fit(ctx["current"])
    return ctx["ep_fit"]


def pos_map(ctx: dict) -> dict:
    if "pos_map" not in ctx:
        ss = [s for s in data.seasons_available() if s >= ctx["current"] - 6]
        ctx["pos_map"] = players.position_map(ss)
    return ctx["pos_map"]


def season_players(ctx: dict, season: int) -> dict:
    """{"box","plays","attr","value"} for a season (cached on disk by inputs)."""
    if season in ctx["values"]:
        return ctx["values"][season]
    st = data.load_store(season)
    key = f"{players.__name__}|v7|{season}|{data.results_key(season, st)}|{data.file_md5(store.plays_path(season))}|{ep_fit(ctx).get('key')}"
    import hashlib
    k = hashlib.md5(key.encode()).hexdigest()[:16]
    c = data.cache_get(f"players_{season}", k)
    if c is None:
        box = players.box_frame(season, st)
        pl = ep.season_epa(season, ep_fit(ctx)) if season in data.plays_seasons() else pd.DataFrame()
        attr = players.attribute(pl, box, st.get("players") or {}) if len(pl) else pl
        credit = players.play_credit(attr) if len(attr) else pd.DataFrame(columns=["gid", "pid"])
        c = {"box": box, "attr_cols": attr.loc[attr["scrim"].astype(bool), ["gid", "row", "kind", "passer_id", "target_id", "rusher_id"]]
             if len(attr) else None,
             "credit": credit}
        data.cache_put(f"players_{season}", k, c)
    val = players.season_value(season, c["box"], c["credit"], pos_map(ctx), st) if len(c["box"]) else pd.DataFrame()
    if len(val):
        pl_ = st.get("players") or {}
        val["name"] = val["pid"].map(lambda p: (pl_.get(p) or {}).get("name"))
        val["class"] = val["pid"].map(lambda p: (pl_.get(p) or {}).get("class"))
    out = {"box": c["box"], "credit": c["credit"], "value": val, "attr_cols": c.get("attr_cols")}
    ctx["values"][season] = out
    return out


# ── season state ────────────────────────────────────────────────────────────

def team_obj(t: str, tm: dict) -> dict:
    v = tm.get(t) or {}
    return {"name": v.get("name"), "short": v.get("short") or v.get("location"), "abbr": v.get("abbr"),
            "colour": v.get("colour"), "alt_colour": v.get("alt_colour"), "alt": v.get("alt_colour"),
            "conference": v.get("conference"), "member": bool(v.get("member"))}


def season_state(ctx: dict, season: int) -> dict:
    """Ratings (RATING), power, paths, preds and frames of a season (memoised)."""
    if season in ctx["seasons"]:
        return ctx["seasons"][season]
    pipe = ctx["pipe"]
    st = data.load_store(season)
    gf = data.games_frame(season, st)
    tm = st.get("teams") or {}
    mem = [t for t, v in tm.items() if v.get("member")]
    power, pts, b_home = sim.power_table(season, pipe)
    fin = pipe["final"].get(season) or {}
    P = pipe["preds"]
    preds = P[P["season"] == season].set_index("gid") if len(P) else pd.DataFrame()
    # off/def points components rescaled to the blend rating
    po, pdd = fin.get("pts", {}).get("off", {}), fin.get("pts", {}).get("def", {})
    mo = float(np.mean([po[t] for t in mem if t in po])) if mem else 0.0
    md = float(np.mean([pdd[t] for t in mem if t in pdd])) if mem else 0.0
    games_played: dict[str, int] = {}
    opp_list: dict[str, list[str]] = {}
    for h, a, f in zip(gf["home"], gf["away"], gf["final"]):
        if f:
            games_played[h] = games_played.get(h, 0) + 1
            games_played[a] = games_played.get(a, 0) + 1
            opp_list.setdefault(h, []).append(a)
            opp_list.setdefault(a, []).append(h)
    R: dict[str, dict] = {}
    epa, sr = fin.get("epa"), fin.get("sr")
    b = pipe["blends"].get(season) or {}
    coef_pts = ((b.get("full") or b.get("pts") or {"coef": [0, 1]})["coef"])[1]
    for t in power:
        o = po.get(t, 0.0) - mo
        d = pdd.get(t, 0.0) - md
        adj = (power[t] - (o + d)) / 2.0
        se = (fin.get("pts", {}).get("se") or {}).get(t)
        R[t] = {"rating": r2(power[t]), "off": r2(o + adj), "def": r2(d + adj), "se": r2(se * coef_pts if se else None),
                "games": games_played.get(t, 0), "pts_rating": r2(pts.get(t)),
                "epa_off": r2(epa["mu"] + epa["off"][t], 3) if epa and t in epa["off"] else None,
                "epa_def": r2(epa["mu"] - epa["def"][t], 3) if epa and t in epa["def"] else None,
                "sr_off": r2(sr["mu"] + sr["off"][t], 3) if sr and t in sr["off"] else None,
                "sr_def": r2(sr["mu"] - sr["def"][t], 3) if sr and t in sr["def"] else None}
    for t in R:
        ops = opp_list.get(t) or []
        R[t]["sos"] = r2(np.mean([power.get(o, -20.0) for o in ops])) if ops else None
    fbs_order = sorted([t for t in mem if t in R], key=lambda t: -(R[t]["rating"] or -99))
    for i, t in enumerate(fbs_order):
        R[t]["rank"] = i + 1
    sos_order = sorted([t for t in fbs_order if R[t]["sos"] is not None], key=lambda t: -R[t]["sos"])
    for i, t in enumerate(sos_order):
        R[t]["sos_rank"] = i + 1
    paths = rating_paths(pipe, season, st, mem)
    out = {"st": st, "gf": gf, "tm": tm, "mem": mem, "power": power, "pts": pts, "b_home": b_home, "ratings": R,
           "preds": preds, "paths": paths, "fbs_order": fbs_order}
    ctx["seasons"][season] = out
    return out


def _power_of(u_pts, u_epa, u_sr, teams, b) -> dict[str, float]:
    pts = committee._net(u_pts, teams)
    full = b.get("full")
    if full and u_epa is not None and u_sr is not None:
        c = full["coef"]
        e, s = committee._net(u_epa, teams), committee._net(u_sr, teams)
        return {t: c[1] * pts[t] + c[2] * e.get(t, 0) + c[3] * s.get(t, 0) for t in pts}
    c = (b.get("pts") or {"coef": [0, 1]})["coef"]
    return {t: c[1] * pts[t] for t in pts}


def rating_paths(pipe: dict, season: int, st: dict, mem: list[str]) -> dict[str, list]:
    """Weekly [day, rating] per member team: the walk-forward rating at each calendar week's start (games before it),
    up to today, then the current (all games) rating."""
    snaps = pipe["snapshots"].get(season) or {}
    teams = pipe["teams"].get(season) or []
    b = pipe["blends"].get(season) or {}
    today = date.today().isoformat()
    ws = sorted(w for w in set(data.week_starts(st).values()) if w <= today)
    days = sorted(snaps)
    picks = []
    for w in ws:
        d = next((x for x in days if x >= w), None)
        if d and d not in picks and d <= today:
            picks.append(d)
    out: dict[str, list] = {t: [] for t in mem}
    for d in picks:
        u = snaps[d]
        pw = _power_of(u.get("pts"), u.get("epa"), u.get("sr"), teams, b)
        m = float(np.mean([pw[t] for t in mem if t in pw])) if mem else 0.0
        for t in mem:
            if t in pw:
                out[t].append([d, r2(pw[t] - m)])
    fin = pipe["final"].get(season) or {}
    if fin.get("pts"):
        pw = _power_of(fin.get("pts"), fin.get("epa"), fin.get("sr"), teams, b)
        m = float(np.mean([pw[t] for t in mem if t in pw])) if mem else 0.0
        gf = data.games_frame(season, st)
        last = str(gf[gf["final"]]["day"].max()) if gf["final"].any() else today
        stamp = min(today, last) if last else today
        for t in mem:
            if t in pw and (not out[t] or out[t][-1][0] < stamp):
                out[t].append([stamp, r2(pw[t] - m)])
    return out


def phase_of(season: int, gf: pd.DataFrame, current: int) -> tuple[str, int | None]:
    if season < current:
        return "offseason", None
    if not len(gf):
        return "preseason", None
    fin = gf["final"]
    today = date.today().isoformat()
    if not fin.any():
        return "preseason", 1
    rem = gf[~fin]
    wk = None
    st = data.load_store(season)
    for k, start in sorted(data.week_starts(st).items(), key=lambda kv: kv[1]):
        if start <= today:
            wk = int(k)
    if not len(rem):
        return "offseason", wk
    if (rem["stype"] == "reg").any():
        return "regular", wk
    if (rem["stype"] == "conf").any():
        return "conf_champ", wk
    if (rem["stype"] == "cfp").any() and not (rem["stype"] == "bowl").any():
        return "playoff", wk
    return "bowls", wk


# ── cards ───────────────────────────────────────────────────────────────────

def clean_odds(o: dict | None) -> dict:
    """The stored line with implausible numbers dropped (see data.games_frame)."""
    o = dict(o or {})
    t, sp = o.get("total"), o.get("spread_home")
    if t is not None and not (20 <= float(t) <= 110):
        o["total"] = None
    if sp is not None and abs(float(sp)) > 75:
        o["spread_home"] = None
    for k in ("ml_home", "ml_away"):
        if o.get(k) is not None and abs(float(o[k])) < 100:
            o[k] = None
    return o


def market_of(g: dict, live_prices: dict | None, sd: float, season: int | None = None) -> dict | None:
    gid = str(g.get("id"))
    if season is not None and int(season) in data.UNRELIABLE_LINES:
        return None
    if live_prices and gid in live_prices and live_prices[gid].get("p_home") is not None:
        lp = live_prices[gid]
        src = (lp.get("sources") or [{}])[0].get("source")
        source = {"kalshi": "kalshi", "polymarket": "polymarket"}.get(src, "espn")
        if lp.get("basis") == "prediction_markets":
            srcs = sorted({x["source"] for x in lp["sources"] if x["source"] in ("kalshi", "polymarket")})
            source = srcs[0] if len(srcs) == 1 else "kalshi"
        return {"p_home": lp["p_home"], "spread_home": lp.get("spread_home"), "total": lp.get("total"), "source": source}
    o = clean_odds(g.get("odds"))
    if o.get("spread_home") is None and o.get("ml_home") is None:
        return None
    p = data.devig(o.get("ml_home"), o.get("ml_away"))
    if p is None and o.get("spread_home") is not None:
        p = float(norm.cdf(-float(o["spread_home"]) / sd))
    return {"p_home": r2(p, 4), "spread_home": o.get("spread_home"), "total": o.get("total"),
            "source": "espn_close" if g.get("status") == "post" else "espn"}


def card(g: dict, season: int, pred: pd.Series | None, live_prices: dict | None = None, sd: float = 15.5,
         inf: dict | None = None) -> dict:
    hs, as_ = g.get("hs"), g.get("as")
    model = None
    if pred is not None and np.isfinite(pred.get("p_home", np.nan)):
        model = {"p_home": r2(pred["p_home"], 4), "margin": r2(pred["margin"]), "total": r2(pred["total"], 1)}
        if inf:      # the published (market-informed) model; `base` = the ratings model it was stacked on
            model.update({"p_home": r2(inf["p_home"], 4), "margin": r2(inf["margin"]),
                          "base": {"p_home": r2(inf["base_p"], 4), "margin": r2(inf["base_margin"])}})
    mk = market_of(g, live_prices, sd, season)
    res = None
    if g.get("status") == "post" and hs is not None and as_ is not None:
        cover = None
        sp = clean_odds(g.get("odds")).get("spread_home") if int(season) not in data.UNRELIABLE_LINES else None
        if sp is not None:
            v = (hs - as_) + float(sp)
            cover = "home" if v > 0 else ("away" if v < 0 else "push")
        mc = None
        if model and hs != as_:
            mc = bool((model["p_home"] > 0.5) == (hs > as_))
        res = {"cover": cover, "model_correct": mc}
    sd_ = g.get("seeds") or {}
    return {"id": str(g["id"]), "season": season, "date": g.get("date"), "status": g.get("status"), "stype": g.get("stype"),
            "round": g.get("round"), "region": g.get("region"), "note": g.get("note"), "week": g.get("week"),
            "home": str(g.get("home")), "away": str(g.get("away")), "hs": hs, "as": as_,
            "hr": (g.get("ranks") or {}).get("home"), "ar": (g.get("ranks") or {}).get("away"),
            "hseed": sd_.get("home"), "aseed": sd_.get("away"), "neutral": bool(g.get("neutral")),
            "conf_game": bool(g.get("conf_game")), "period": g.get("periods") if g.get("status") == "in" else None,
            "clock": None, "model": model, "market": mk, "result": res,
            **({"tba": True} if canon.time_tba(g) else {})}           # start time not set yet (shown as TBA)


def season_cards(ctx: dict, season: int, live_prices: dict | None = None) -> list[dict]:
    S = season_state(ctx, season)
    st, preds = S["st"], S["preds"]
    sd = ((ctx["pipe"]["blends"].get(season) or {}).get("sd") or {}).get("mid", 15.5)
    tm = S["tm"]
    inf = informed(ctx, season)
    out = []
    for gid, g in sorted((st.get("games") or {}).items(), key=lambda kv: (kv[1].get("date") or "", kv[0])):
        h, a = str(g.get("home")), str(g.get("away"))
        if not ((tm.get(h) or {}).get("member") or (tm.get(a) or {}).get("member")):
            continue
        if not (data.real_team(h) and data.real_team(a)) and g.get("stype") == "reg":
            continue
        pr = preds.loc[gid] if len(preds) and gid in preds.index else None
        out.append(card(g, season, pr, live_prices, sd, inf.get(str(gid))))
    return out


# ── season.json ─────────────────────────────────────────────────────────────

def standings(S: dict) -> dict:
    if "_standings" in S:
        return S["_standings"]
    S["_standings"] = _standings(S)
    return S["_standings"]


def _standings(S: dict) -> dict:
    st, gf, tm, R = S["st"], S["gf"], S["tm"], S["ratings"]
    rec: dict[str, dict] = {t: {"team": t, "w": 0, "l": 0, "conf_w": 0, "conf_l": 0, "home": [0, 0], "away": [0, 0],
                                 "neutral": [0, 0], "streak": "", "pf": 0, "pa": 0, "_res": []} for t in S["mem"]}
    g2 = gf[gf["final"]]
    # conference record = regular-season conference games only: the championship game (stype "conf") counts in the
    # overall record but not in conf_w / conf_l, as the conferences and ESPN's standings count it
    sty = g2["stype"] if "stype" in g2 else ["reg"] * len(g2)
    for h, a, hs, as_, neu, cg, sy in zip(g2["home"], g2["away"], g2["hs"], g2["as"], g2["neutral"], g2["conf_game"], sty):
        for t, o, pf, pa, side in ((h, a, hs, as_, "home"), (a, h, as_, hs, "away")):
            if t not in rec:
                continue
            x = rec[t]
            won = pf > pa
            x["w" if won else "l"] += 1
            k = "neutral" if neu else side
            x[k][0 if won else 1] += 1
            x["pf"] += int(pf)
            x["pa"] += int(pa)
            x["_res"].append("W" if won else "L")
            if cg and sy == "reg" and tm.get(t, {}).get("conference") == tm.get(o, {}).get("conference"):
                x["conf_w" if won else "conf_l"] += 1
    ap = latest_poll(st, "ap")
    apr = {r["team"]: r["rank"] for r in ap}
    out: dict[str, list] = {}
    for t, x in rec.items():
        res = x.pop("_res")
        if res:
            n = 1
            while n < len(res) and res[-n - 1] == res[-1]:
                n += 1
            x["streak"] = f"{res[-1]}{n}"
        x["rank"] = apr.get(t)
        x["rating_rank"] = (R.get(t) or {}).get("rank")
        c = (tm.get(t) or {}).get("conference") or "18"
        out.setdefault(c, []).append(x)
    for c, rows in out.items():
        rows.sort(key=lambda x: (-(x["conf_w"] / max(x["conf_w"] + x["conf_l"], 1)), -x["conf_w"],
                                 -(x["w"] / max(x["w"] + x["l"], 1)), x["rating_rank"] or 999))
        for i, x in enumerate(rows):
            x["conf_rank"] = i + 1
    return out


def latest_poll(st: dict, kind: str) -> list[dict]:
    rk = (st.get("rankings") or {}).get(kind) or {}
    if not rk:
        return []
    def order(w):
        return (2, 0) if w == "final" else ((0, int(w)) if w.isdigit() else ((-1, 0) if w == "pre" else (1, int(w[4:]) if w[4:].isdigit() else 0)))
    weeks = sorted(rk, key=order)
    cur, prev = weeks[-1], (weeks[-2] if len(weeks) > 1 else None)
    pr = {str(r[1]): r[0] for r in (rk.get(prev) or [])} if prev else {}
    return [{"rank": r[0], "team": str(r[1]), "points": r[2] if kind != "cfp" else None,
             "first": r[3] if len(r) > 3 and kind != "cfp" else None, "prev": pr.get(str(r[1])), "week": cur}
            for r in sorted(rk[cur], key=lambda r: r[0])]


def leaders(val: pd.DataFrame) -> dict:
    if val is None or not len(val):
        return {}
    out = {}
    for k in ("value", "pass_yds", "pass_td", "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "tkl", "sacks", "def_int", "tfl"):
        x = val.sort_values(k, ascending=False).head(10)
        out[k] = [[r["pid"], r["team"], r2(r[k], 1)] for r in x.to_dict("records") if r[k] > 0]
    return out


def season_payload(ctx: dict, season: int, simres: dict | None, cards: list[dict]) -> dict:
    S = season_state(ctx, season)
    st, tm = S["st"], S["tm"]
    phase, week = phase_of(season, S["gf"], ctx["current"])
    confs = {}
    for c, v in (st.get("conferences") or {}).items():
        ts = sorted(t for t in S["mem"] if (tm.get(t) or {}).get("conference") == c)
        if ts:
            confs[c] = {"name": v.get("name"), "short": v.get("short"), "teams": ts,
                        "divisions": v.get("divisions") or {}}
    teams = {t: team_obj(t, tm) for t in tm if (tm.get(t) or {}).get("member")}
    used = {c["home"] for c in cards} | {c["away"] for c in cards}
    for t in used:
        if t not in teams and t in tm:
            teams[t] = team_obj(t, tm)
    prev_rank = {}
    paths = S["paths"]
    for t, p in paths.items():
        if len(p) >= 2:
            prev_rank[t] = p[-2][1]
    pr_order = sorted([t for t in prev_rank], key=lambda t: -(prev_rank[t] or -99))
    prk = {t: i + 1 for i, t in enumerate(pr_order)}
    power = [{"rank": S["ratings"][t]["rank"], "team": t, "rating": S["ratings"][t]["rating"], "prev_rank": prk.get(t)}
             for t in S["fbs_order"]]
    sp = season_players(ctx, season)
    ccg = sim.ccg_conferences(st, S["gf"])
    fmt = {"conferences_with_divisions": sorted(c for c, v in confs.items() if v["divisions"]),
           "championship_games": sorted(ccg), "cfp": sim.cfp_format(season)}
    out = {"ok": True, "level": LEVEL, "season": season, "updated_at": data.now_iso(), "phase": phase, "week": week,
           "format": fmt, "conferences": confs, "teams": teams, "standings": standings(S),
           "ratings": {t: S["ratings"][t] for t in S["mem"] if t in S["ratings"]},
           "rating_paths": {t: p for t, p in paths.items() if p},
           "polls": {k: latest_poll(st, k) for k in ("ap", "coaches", "cfp")}, "power": power,
           "sim": None, "leaders": leaders(sp["value"][sp["value"]["team"].isin(S["mem"])] if len(sp["value"]) else None)}
    if simres:
        out["sim"] = {"n_sims": simres["n_sims"], "teams": simres["teams"], "notes": simres["notes"],
                      "as_of": data.now_iso()}
    return out


# ── cfp.json ────────────────────────────────────────────────────────────────

def actual_bracket(season: int, st: dict, cards_by_id: dict) -> dict | None:
    games = [g for g in (st.get("games") or {}).values() if g.get("stype") == "cfp"]
    if not games:
        return None
    af = sim.actual_field(season, st)
    seeds = af["seeds"]
    rows = []
    for g in sorted(games, key=lambda g: g.get("date") or ""):
        h, a = str(g.get("home")), str(g.get("away"))
        win = None
        if g.get("status") == "post" and g.get("hs") is not None:
            win = h if g["hs"] > g["as"] else a
        c = cards_by_id.get(str(g["id"])) or {}
        rows.append({"round": g.get("round"), "slot": None, "home": h if data.real_team(h) else None,
                     "away": a if data.real_team(a) else None, "p_home": (c.get("model") or {}).get("p_home"),
                     "winner": win, "gid": str(g["id"])})
    return {"seeds": [{"seed": s, "team": t, "auto": None} for t, s in sorted(seeds.items(), key=lambda kv: kv[1])],
            "games": rows}


def projected_bracket(simres: dict, S: dict, fmt: dict, b: dict) -> dict | None:
    n = fmt["teams"]
    if n not in (4, 12):
        return None
    T = simres["teams"]
    field = sorted(T, key=lambda t: -T[t]["p_cfp"])[:n]
    field.sort(key=lambda t: (T[t]["seed_mean"] if T[t]["seed_mean"] is not None else 99))
    seeds = [{"seed": i + 1, "team": t, "auto": bool(T[t].get("p_auto", 0) > 0.5 * max(T[t]["p_cfp"], 1e-9))}
             for i, t in enumerate(field)]
    pw, hb, sd = simres["power"], simres["b_home"], simres["sd"]

    def ph(h, a, home):
        return r2(norm.cdf(((hb if home else 0.0) + pw.get(h, 0) - pw.get(a, 0)) / sd), 4)
    by = {s["seed"]: s["team"] for s in seeds}
    games = []
    if n == 12:
        for slot, (x, y) in enumerate(((5, 12), (6, 11), (7, 10), (8, 9))):
            games.append({"round": "First Round", "slot": slot + 1, "home": by[x], "away": by[y], "p_home": ph(by[x], by[y], True),
                          "winner": None, "gid": None})
        for slot, k in enumerate((1, 2, 3, 4)):
            games.append({"round": "Quarterfinal", "slot": slot + 1, "home": by[k], "away": None, "p_home": None,
                          "winner": None, "gid": None})
    else:
        for slot, (x, y) in enumerate(((1, 4), (2, 3))):
            games.append({"round": "Semifinal", "slot": slot + 1, "home": by[x], "away": by[y], "p_home": ph(by[x], by[y], False),
                          "winner": None, "gid": None})
    return {"seeds": seeds, "games": games}


def bracket_odds(season: int, ctx: dict, seeds: dict[str, int], n: int = 20000) -> dict:
    """Pre-playoff title odds for a finished season's actual field (ratings as of the first CFP game)."""
    pipe = ctx["pipe"]
    st = data.load_store(season)
    cfp_days = [data.us_day(g.get("date")) for g in (st.get("games") or {}).values() if g.get("stype") == "cfp"]
    as_of = min(d for d in cfp_days if d)
    power, _, hb = sim.power_table(season, pipe, as_of)
    sd = ((pipe["blends"].get(season) or {}).get("sd") or {}).get("post", 15.5)
    rng = np.random.default_rng(season)
    by = {s: t for t, s in seeds.items()}
    k = len(by)
    out = {t: {"p_in": 1.0, "p_bye": 1.0 if (k == 12 and s <= 4) else 0.0, "p_qf": 0.0, "p_sf": 0.0, "p_final": 0.0,
               "p_title": 0.0, "seed_dist": {str(s): 1.0}} for t, s in seeds.items()}
    if k not in (4, 12):
        return out
    teams = list(seeds)
    ix = {t: i for i, t in enumerate(teams)}
    pw = np.array([power.get(t, 0.0) for t in teams])
    shift = rng.standard_normal((n, len(teams))) * 3.5

    def play(a, b_, home):
        m = (hb if home else 0.0) + pw[a] - pw[b_] + shift[np.arange(n), a] - shift[np.arange(n), b_]
        return np.where(m + np.sqrt(max(sd ** 2 - 2 * 3.5 ** 2, 100)) * rng.standard_normal(n) > 0, a, b_)
    S = {s: np.full(n, ix[t]) for s, t in by.items()}
    cnt = {r: np.zeros(len(teams)) for r in ("qf", "sf", "final", "title")}
    if k == 12:
        r1 = {5: play(S[5], S[12], True), 6: play(S[6], S[11], True), 7: play(S[7], S[10], True), 8: play(S[8], S[9], True)}
        for s in (1, 2, 3, 4):
            cnt["qf"][S[s][0]] += n
        for w in r1.values():
            np.add.at(cnt["qf"], w, 1)
        q = {1: play(S[1], r1[8], False), 2: play(S[2], r1[7], False), 3: play(S[3], r1[6], False), 4: play(S[4], r1[5], False)}
        for w in q.values():
            np.add.at(cnt["sf"], w, 1)
        f1, f2 = play(q[1], q[4], False), play(q[2], q[3], False)
    else:
        for s in (1, 2, 3, 4):
            cnt["sf"][S[s][0]] += n
        f1, f2 = play(S[1], S[4], False), play(S[2], S[3], False)
    np.add.at(cnt["final"], f1, 1)
    np.add.at(cnt["final"], f2, 1)
    np.add.at(cnt["title"], play(f1, f2, False), 1)
    for t, i in ix.items():
        out[t].update({"p_qf": r2(cnt["qf"][i] / n, 4) if k == 12 else 0.0, "p_sf": r2(cnt["sf"][i] / n, 4),
                       "p_final": r2(cnt["final"][i] / n, 4), "p_title": r2(cnt["title"][i] / n, 4)})
    return out


def cfp_payload(ctx: dict, season: int, simres: dict | None, cards: list[dict]) -> dict:
    S = season_state(ctx, season)
    st, gf = S["st"], S["gf"]
    fmt = sim.cfp_format(season)
    fmt["table"] = sim.format_table(list(range(2014, max(season, ctx["current"]) + 1)))
    cbi = {c["id"]: c for c in cards}
    comm = ctx["comm"]
    cfp_rank = latest_poll(st, "cfp")
    br = actual_bracket(season, st, cbi)
    actual = {"rankings": cfp_rank, "bracket": br} if (cfp_rank or br) else None
    # committee proxy: current resume scored by the fitted model
    rating = {t: S["pts"].get(t, 0.0) for t in S["pts"]}
    cutoff = None
    post_days = sorted(d for d in gf.loc[gf["stype"].isin(["bowl", "cfp"]), "day"].dropna())
    if post_days:                     # a season with a postseason: the resume as of selection (before the bowls)
        cutoff = post_days[0]
        u = committee.snapshot_at(ctx["pipe"]["snapshots"].get(season) or {}, None, cutoff)
        if u is not None:
            rating = committee._net(u, ctx["pipe"]["teams"].get(season) or [])
        if not gf[(gf["day"] < cutoff) & gf["final"]].shape[0]:
            cutoff = None
    X = committee.resume(season, st, gf, rating, cutoff)
    proxy = []
    if len(X) and season >= committee.FIRST:
        X["score"] = committee.score(comm["model"], X)
        X = X.sort_values("score", ascending=False).head(30)
        T = (simres or {}).get("teams") or {}
        for i, r in enumerate(X.to_dict("records")):
            t = r["team"]
            proxy.append({"rank": i + 1, "team": t, "score": r2(r["score"], 3), "p_top12": (T.get(t) or {}).get("p_top12"),
                          "p_in": (T.get(t) or {}).get("p_cfp"), "p_bye": (T.get(t) or {}).get("p_bye"),
                          "record": f"{int(r['wins'])}-{int(r['losses'])}", "sos_rank": (S["ratings"].get(t) or {}).get("sos_rank"),
                          "conf_champ_p": (T.get(t) or {}).get("p_conf")})
    odds = {}
    if simres:
        for t, v in simres["teams"].items():
            if v["p_cfp"] > 0 or v["p_title"] > 0:
                odds[t] = {"p_in": v["p_cfp"], "p_bye": v["p_bye"], "p_qf": v["p_round"]["qf"], "p_sf": v["p_round"]["sf"],
                           "p_final": v["p_round"]["final"], "p_title": v["p_title"], "seed_dist": v["seed_dist"]}
    elif br and fmt["teams"] in (4, 12):
        af = sim.actual_field(season, st)
        if len(af["seeds"]) == fmt["teams"]:
            odds = bracket_odds(season, ctx, af["seeds"])
    proj = projected_bracket(simres, S, fmt, ctx["pipe"]["blends"].get(season) or {}) if simres else (br if br else None)
    ctg = {}
    if simres:
        for c, rows in simres["conf"].items():
            ctg[c] = [r for r in rows if r["p_appear"] > 0.001 or r["p_win"] > 0.001][:8]
    elig = {}
    if simres:
        elig = {t: v["p_bowl"] for t, v in simres["teams"].items()}
    else:
        for x in standings(S).values():
            for r in x:
                elig[r["team"]] = 1.0 if r["w"] >= 6 else 0.0
    bowls = [c for c in cards if c["stype"] == "bowl"]
    return {"ok": True, "season": season, "updated_at": data.now_iso(), "format": fmt, "actual": actual,
            "committee_proxy": proxy, "projected_bracket": proj, "odds": odds, "conf_title_games": ctg,
            "bowls": {"eligible": elig, "games": bowls},
            "proxy_fit": {"n_seasons": comm["n_seasons"], "spearman": comm["spearman"], "top12_overlap": comm["top12_overlap"],
                          "top4_overlap": comm["top4_overlap"], "ap_reference": {"spearman": comm["ap_spearman"],
                                                                                 "top12_overlap": comm["ap_top12_overlap"],
                                                                                 "top4_overlap": comm["ap_top4_overlap"]},
                          "features": comm["features"], "weights": comm["weights"],
                          "note": "Leave-one-season-out on each season's selection-day ranking; the AP poll of the same week "
                                  "is shown for reference (it is published alongside, not before, the committee's)."}}


# ── teams ───────────────────────────────────────────────────────────────────

TEAM_METRICS = [
    ("rating", "Rating", "Model", "signed1", False, "Expected margin v an average FBS team, neutral field"),
    ("off", "Offense", "Model", "signed1", False, "Points per game added on offense v average"),
    ("def", "Defense", "Model", "signed1", False, "Points per game prevented on defense v average"),
    ("epa_off", "Off EPA/play", "Efficiency", "3", False, "Opponent-adjusted offensive EPA per play (non-garbage)"),
    ("epa_def", "Def EPA/play", "Efficiency", "3", True, "Opponent-adjusted EPA per play allowed"),
    ("sr_off", "Off success", "Efficiency", "pct", False, "Opponent-adjusted offensive success rate"),
    ("sr_def", "Def success", "Efficiency", "pct", True, "Opponent-adjusted success rate allowed"),
    ("sos", "SOS", "Model", "signed1", False, "Mean rating of opponents played"),
    ("ppg", "Points/game", "Results", "1", False, "Points scored per game"),
    ("papg", "Allowed/game", "Results", "1", True, "Points allowed per game"),
    ("ypp", "Yards/play", "Box", "2", False, "Total yards per offensive play"),
    ("ypp_allowed", "Yards/play allowed", "Box", "2", True, "Yards per play allowed"),
    ("to_margin", "Turnover margin", "Box", "signed1", False, "Takeaways minus giveaways per game"),
    ("third_pct", "3rd-down %", "Box", "pct", False, "Third-down conversion rate"),
    ("pass_epa", "Pass EPA/play", "Efficiency", "3", False, "Raw EPA per dropback"),
    ("rush_epa", "Rush EPA/play", "Efficiency", "3", False, "Raw EPA per rush"),
    ("explosive", "Explosive rate", "Efficiency", "pct", False, "Rushes of 15+ and passes of 20+ yards per play"),
    ("off_pass_epa", "Adj pass EPA", "Efficiency", "3", False, "Opponent-adjusted EPA per dropback on offense (non-garbage)"),
    ("def_pass_epa", "Adj pass EPA allowed", "Efficiency", "3", True, "Opponent-adjusted EPA per dropback allowed"),
    ("off_rush_epa", "Adj rush EPA", "Efficiency", "3", False, "Opponent-adjusted EPA per rush on offense (non-garbage)"),
    ("def_rush_epa", "Adj rush EPA allowed", "Efficiency", "3", True, "Opponent-adjusted EPA per rush allowed"),
]


def metric_list(rows) -> list[dict]:
    return [{"key": k, "label": l, "group": g, "fmt": f, "lower": lo, "desc": d} for k, l, g, f, lo, d in rows]


def team_stats(ctx: dict, season: int) -> dict[str, dict]:
    S = season_state(ctx, season)
    st = S["st"]
    out: dict[str, dict] = {t: {} for t in S["mem"]}
    acc: dict[str, dict] = {t: {"pf": 0, "pa": 0, "g": 0, "yds": 0, "plays": 0, "ydsa": 0, "playsa": 0, "tk": 0, "gv": 0,
                                "c3": 0, "a3": 0} for t in S["mem"]}
    for gid, g in (st.get("games") or {}).items():
        if g.get("status") != "post":
            continue
        h, a = str(g.get("home")), str(g.get("away"))
        box = g.get("box") or {}
        for t, o, pf, pa in ((h, a, g.get("hs"), g.get("as")), (a, h, g.get("as"), g.get("hs"))):
            if t not in acc or pf is None:
                continue
            x = acc[t]
            x["pf"] += pf
            x["pa"] += pa
            x["g"] += 1
            bt, bo = (box.get(t) or {}).get("team") or {}, (box.get(o) or {}).get("team") or {}
            if bt:
                x["yds"] += bt.get("total_yards") or 0
                x["plays"] += (bt.get("rush_att") or 0) + (bt.get("pass_att") or 0)
                x["gv"] += bt.get("turnovers") or 0
                x["c3"] += bt.get("third_conv") or 0
                x["a3"] += bt.get("third_att") or 0
            if bo:
                x["ydsa"] += bo.get("total_yards") or 0
                x["playsa"] += (bo.get("rush_att") or 0) + (bo.get("pass_att") or 0)
                x["tk"] += bo.get("turnovers") or 0
    pl_stats = ctx.get("tgs", {}).get(season)
    if pl_stats is None:
        ts, _f = backtest.team_stats(ctx["current"], [season])
        pl_stats = ts.get(season)
        ctx.setdefault("tgs", {})[season] = pl_stats
    raw = {}
    if pl_stats is not None and len(pl_stats):
        for t, g in pl_stats.groupby("team"):
            w = g["n"].clip(lower=1)
            raw[t] = {"pass_epa": float(np.average(g["pass_epa"], weights=g["n_pass"].clip(lower=1))),
                      "rush_epa": float(np.average(g["rush_epa"], weights=g["n_rush"].clip(lower=1))),
                      "explosive": float(np.average(g["expl"], weights=w))}
    # opponent-adjusted pass and rush EPA per play, offence and defence (the EPA ridge split by play type)
    fits = {}
    for c, nc in (("pass_epa", "n_pass"), ("rush_epa", "n_rush")):
        try:
            fits[c] = ratings.split_adjusted(season, S["gf"], st, pl_stats, c, nc) if pl_stats is not None else None
        except Exception as exc:                                     # noqa: BLE001
            logger.warning("cfb %s adjusted %s: %s", season, c, exc)
            fits[c] = None
    adj_keys = {"off_pass_epa": (fits["pass_epa"], "off"), "def_pass_epa": (fits["pass_epa"], "def"),
                "off_rush_epa": (fits["rush_epa"], "off"), "def_rush_epa": (fits["rush_epa"], "def")}
    for t in S["mem"]:
        x, R = acc[t], S["ratings"].get(t) or {}
        g = max(x["g"], 1)
        v = {k: R.get(k) for k in ("rating", "off", "def", "epa_off", "epa_def", "sr_off", "sr_def", "sos")}
        v.update({"ppg": r2(x["pf"] / g, 1), "papg": r2(x["pa"] / g, 1),
                  "ypp": r2(x["yds"] / x["plays"], 2) if x["plays"] else None,
                  "ypp_allowed": r2(x["ydsa"] / x["playsa"], 2) if x["playsa"] else None,
                  "to_margin": r2((x["tk"] - x["gv"]) / g, 2) if x["plays"] else None,
                  "third_pct": r2(x["c3"] / x["a3"], 3) if x["a3"] else None})
        v.update({k: r2(raw.get(t, {}).get(k), 3) for k in ("pass_epa", "rush_epa", "explosive")})
        for k, (fit, side) in adj_keys.items():
            v[k] = r2((fit or {}).get(side, {}).get(t), 3) if fit else None
        out[t] = v
    return out


def pct_rank(values: dict[str, Any], lower: bool) -> tuple[dict, dict]:
    ok = {t: v for t, v in values.items() if isinstance(v, (int, float)) and v is not None}
    if not ok:
        return {}, {}
    s = pd.Series(ok)
    pct = (s.rank(pct=True, ascending=not lower) * 100).round(0)
    rk = s.rank(ascending=lower, method="min")
    return pct.to_dict(), rk.to_dict()


def teams_payload(ctx: dict, season: int, tstats: dict) -> dict:
    S = season_state(ctx, season)
    stand = {r["team"]: r for rows in standings(S).values() for r in rows}
    pcts = {}
    for k, *_rest in TEAM_METRICS:
        lower = _rest[3]
        pcts[k] = pct_rank({t: tstats[t].get(k) for t in tstats}, lower)[0]
    out = {}
    for t, v in tstats.items():
        out[t] = {"name": S["tm"][t].get("name"), "conference": S["tm"][t].get("conference"),
                  "w": stand.get(t, {}).get("w", 0), "l": stand.get(t, {}).get("l", 0),
                  "rating_rank": (S["ratings"].get(t) or {}).get("rank"), "values": v,
                  "pct": {k: pcts[k].get(t) for k in pcts if pcts[k].get(t) is not None}}
    return {"ok": True, "level": LEVEL, "season": season, "updated_at": data.now_iso(), "metrics": metric_list(TEAM_METRICS),
            "teams": out}


def move_rows(ctx: dict, season: int) -> list[dict]:
    if season - 1 not in data.seasons_available():
        return []
    prev = season_players(ctx, season - 1)["value"]
    cur = season_players(ctx, season)["value"]
    if prev is None or not len(prev):
        return []
    st = data.load_store(season)
    mv = players.moves(prev, cur, st)
    pst = data.load_store(season - 1)
    names = {**{p: v.get("name") for p, v in (pst.get("players") or {}).items()},
             **{p: v.get("name") for p, v in (st.get("players") or {}).items()}}
    cls = {p: v.get("class") for p, v in (st.get("players") or {}).items()}
    pct = prev.set_index("pid")["pctl"].to_dict()
    tm = st.get("teams") or {}
    out = []
    for m in mv:
        if not (tm.get(m["to"]) or {}).get("member") and not (data.load_store(season - 1).get("teams", {}).get(m["from"]) or {}).get("member"):
            continue
        out.append({"player": m["player"], "name": names.get(m["player"]), "pos": m["pos"], "from": m["from"], "to": m["to"],
                    "value_before": m["value_before"], "value_after": m["value_after"], "class": cls.get(m["player"]),
                    "grade": players.grade(pct.get(m["player"], 50.0)), "gp_after": m["gp_after"]})
    return out


def team_page(ctx: dict, season: int, t: str, cards: list[dict], tstats: dict, units: dict, mv: list[dict],
              simres: dict | None, val: pd.DataFrame, light: bool = False) -> dict:
    S = season_state(ctx, season)
    st, tm = S["st"], S["tm"]
    stand = {r["team"]: r for rows in standings(S).values() for r in rows}
    rec = stand.get(t, {})
    sched = [c for c in cards if t in (c["home"], c["away"])]
    stats = {}
    cache = S.setdefault("_pct", {})
    for k, *_rest in TEAM_METRICS:
        lower = _rest[3]
        if k not in cache:
            cache[k] = pct_rank({x: tstats[x].get(k) for x in tstats}, lower)
        p, rk = cache[k]
        if tstats.get(t, {}).get(k) is not None:
            stats[k] = {"v": tstats[t][k], "pct": p.get(t), "rank": int(rk[t]) if t in rk else None}
    roster = []
    v = val[val["team"] == t] if len(val) else val
    seen = set()
    for r in (v.sort_values("value", ascending=False).head(30 if light else 200).to_dict("records") if len(v) else []):
        seen.add(r["pid"])
        roster.append({"id": r["pid"], "name": r.get("name"), "pos": r["pos"], "class": r.get("class"), "gp": int(r["gp"]),
                       "value": r2(r["value"]), "value_pg": r2(r["value_pg"]), "epa": r2(r["epa"], 1),
                       "pass_yds": int(r["pass_yds"]), "rush_yds": int(r["rush_yds"]), "rec_yds": int(r["rec_yds"]),
                       "tkl": int(r["tkl"]), "sacks": r2(r["sacks"], 1)})
    for pid in ((st.get("rosters") or {}).get(t) or []) if not light else []:
        if pid in seen:
            continue
        p = (st.get("players") or {}).get(pid) or {}
        roster.append({"id": pid, "name": p.get("name"), "pos": canon.pool(LEVEL, p.get("pos")) or p.get("pos"),
                       "class": p.get("class"), "gp": 0, "value": None, "value_pg": None})
    u = units.get(t) or []
    graded = [x for x in u if x["unit"] != "OL" or x.get("value") is not None]
    strengths = sorted(graded, key=lambda x: -x["pctl"])[:3]
    needs = sorted(graded, key=lambda x: x["pctl"])[:3]
    sug = players.suggestions(t, needs, val, n=3 if light else 5) if len(val) else []
    ap_hist = []
    rk = (st.get("rankings") or {}).get("ap") or {}
    path = S["paths"].get(t) or []
    allp = S["paths"]
    days = [d for d, _ in path]
    ws = data.week_starts(st)
    for w in sorted([w for w in rk if w.isdigit()], key=int):
        r = next((x[0] for x in rk[w] if str(x[1]) == t), None)
        d = ws.get(w)
        mr = None
        if d:
            dd = next((x for x in days if x >= d), None)
            if dd:
                mrc = S.setdefault("_mrank", {})
                if dd not in mrc:
                    vals = {x: next((pv for pd_, pv in allp[x] if pd_ == dd), None) for x in S["mem"] if allp.get(x)}
                    order = sorted((x for x in vals if vals[x] is not None), key=lambda x: -vals[x])
                    mrc[dd] = {x: i + 1 for i, x in enumerate(order)}
                mr = mrc[dd].get(t)
        ap_hist.append([int(w), r, mr])
    return {"ok": True, "id": t, "level": LEVEL, "season": season, "team": team_obj(t, tm),
            "record": {k: rec.get(k) for k in ("w", "l", "conf_w", "conf_l", "home", "away", "neutral", "streak", "pf", "pa", "conf_rank")},
            "rating": S["ratings"].get(t), "rating_path": path, "rank_history": ap_hist, "schedule": sched, "stats": stats,
            "roster": roster, "units": u, "strengths": strengths, "needs": needs,
            "moves": {"in": [m for m in mv if m["to"] == t], "out": [m for m in mv if m["from"] == t]},
            "odds": (simres or {}).get("teams", {}).get(t), "suggestions": sug,
            "suggestions_note": "Model suggestions from on-field value only: not considering eligibility, the transfer "
                                "window, NIL, scheme fit or availability."}


# ── players ─────────────────────────────────────────────────────────────────

PLAYER_METRICS = [
    ("value", "Value", "Value", "1", False, "Points above a replacement-level player (EPA for skill positions, box points for defence and specialists)"),
    ("value_pg", "Value/game", "Value", "2", False, "Value per game played"),
    ("epa", "EPA", "Efficiency", "1", False, "Total EPA credited (dropbacks, rushes, targets)"),
    ("epa_play", "EPA/play", "Efficiency", "3", False, "EPA per credited play at the player's position"),
    ("pass_yds", "Pass yds", "Passing", "int", False, "Passing yards"),
    ("pass_td", "Pass TD", "Passing", "int", False, "Passing touchdowns"),
    ("pass_int", "INT", "Passing", "int", True, "Interceptions thrown"),
    ("rush_car", "Carries", "Rushing", "int", False, "Rushing attempts"),
    ("rush_yds", "Rush yds", "Rushing", "int", False, "Rushing yards"),
    ("rush_td", "Rush TD", "Rushing", "int", False, "Rushing touchdowns"),
    ("rec", "Rec", "Receiving", "int", False, "Receptions"),
    ("tgt", "Targets", "Receiving", "int", False, "Targets parsed from the play text"),
    ("rec_yds", "Rec yds", "Receiving", "int", False, "Receiving yards"),
    ("rec_td", "Rec TD", "Receiving", "int", False, "Receiving touchdowns"),
    ("tkl", "Tackles", "Defense", "int", False, "Total tackles"),
    ("tfl", "TFL", "Defense", "1", False, "Tackles for loss"),
    ("sacks", "Sacks", "Defense", "1", False, "Sacks"),
    ("pd", "PD", "Defense", "int", False, "Passes defended"),
    ("def_int", "INT", "Defense", "int", False, "Interceptions"),
    ("fgm", "FGM", "Kicking", "int", False, "Field goals made"),
    ("fga", "FGA", "Kicking", "int", False, "Field goals attempted"),
    # rates (docs/_design/metrics/college.json); percentiles within the position need `qualified_rate` volume
    ("db", "Dropbacks", "Passing", "int", False, "Dropbacks credited from the play-by-play (garbage time excluded)"),
    ("epa_db", "EPA/dropback", "Passing", "3", False, "Expected points added per dropback, sacks and interceptions included"),
    ("sr_db", "Dropback success", "Passing", "pct", False, "Share of dropbacks that gain expected points"),
    ("cmp_pct", "Comp%", "Passing", "pct", False, "Completions per pass attempt"),
    ("ypa", "Yds/att", "Passing", "2", False, "Passing yards per attempt"),
    ("td_rate", "TD rate", "Passing", "pct", False, "Touchdown passes per attempt"),
    ("int_rate", "INT rate", "Passing", "pct", True, "Interceptions per pass attempt"),
    ("rush_pg", "Runs/game", "Rushing", "2", False, "Designed runs and scrambles per game (style)"),
    ("epa_rush", "EPA/carry", "Rushing", "3", False, "Expected points added per carry"),
    ("sr_rush", "Rush success", "Rushing", "pct", False, "Share of carries that gain expected points"),
    ("ypc", "Yds/carry", "Rushing", "2", False, "Rushing yards per carry"),
    ("rush_share", "Rush share", "Rushing", "pct", False, "Share of the team's carries in the player's games"),
    ("tgt_share", "Target share", "Receiving", "pct", False, "Share of the team's targets thrown to the player in the player's games"),
    ("epa_tgt", "EPA/target", "Receiving", "3", False, "Expected points added per target"),
    ("sr_tgt", "Target success", "Receiving", "pct", False, "Share of targets that gain expected points"),
    ("yptpa", "Yds/team att", "Receiving", "2", False, "Receiving yards per team pass attempt in the player's games"),
    ("ypr", "Yds/rec", "Receiving", "2", False, "Receiving yards per reception"),
    ("tkl_pg", "Tackles/game", "Defense", "2", False, "Total tackles per game"),
    ("tfl_pg", "TFL/game", "Defense", "2", False, "Tackles for loss per game"),
    ("sacks_pg", "Sacks/game", "Defense", "2", False, "Sacks per game"),
    ("hurries_pg", "Hurries/game", "Defense", "2", False, "Quarterback hurries per game"),
    ("pd_pg", "PD/game", "Defense", "2", False, "Passes defended per game"),
    ("def_int_pg", "INT/game", "Defense", "3", False, "Interceptions per game"),
    ("havoc_pg", "Havoc/game", "Defense", "2", False, "Tackles for loss, passes defended, interceptions and hurries per game"),
    ("fg_pct", "FG%", "Kicking", "pct", False, "Field goals made per attempt"),
    ("xp_pct", "XP%", "Kicking", "pct", False, "Extra points made per attempt"),
    ("gross", "Gross avg", "Punting", "1", False, "Average punt distance"),
    ("in20_rate", "Inside 20", "Punting", "pct", False, "Share of punts downed inside the 20"),
    ("tb_rate", "Touchback rate", "Punting", "pct", True, "Touchbacks per punt"),
    # play-credit rates (per-play yards and flags from the play-by-play, garbage time excluded)
    ("sack_rate", "Sack rate", "Passing", "pct", True, "Sacks per dropback: the most quarterback-driven part of protection"),
    ("expl_pass", "Explosive passes", "Passing", "pct", False, "Completions of 20+ yards per dropback"),
    ("ypd", "Yds/dropback", "Passing", "2", False, "Yards per dropback after sack losses"),
    ("qb_rush_epa", "QB rush EPA", "Rushing", "3", False, "Expected points added per quarterback run (designed runs and scrambles)"),
    ("expl_rush", "Explosive runs", "Rushing", "pct", False, "Share of carries gaining 10+ yards"),
    ("stuff_rate", "Stuff rate", "Rushing", "pct", True, "Share of carries stopped for no gain or a loss"),
    ("ypt", "Yds/target", "Receiving", "2", False, "Receiving yards per target"),
    ("catch_rate", "Catch rate", "Receiving", "pct", False, "Catches per target"),
    ("expl_tgt", "Explosive targets", "Receiving", "pct", False, "Targets that gain 20+ yards"),
    ("fga_pg", "FGA/game", "Kicking", "2", False, "Field-goal attempts per game (how much the coach uses the kicker)"),
    ("fg_long", "Long FG", "Kicking", "int", False, "Longest made field goal of the season"),
]
RATE_KEYS = sorted({k for ks in players.RATE_FIELDS.values() for k in ks})
_DP = {"epa_play": 3, "epa_db": 3, "epa_rush": 3, "epa_tgt": 3, "sr_db": 3, "sr_rush": 3, "sr_tgt": 3, "cmp_pct": 3, "td_rate": 3,
       "int_rate": 3, "rush_share": 3, "tgt_share": 3, "def_int_pg": 3, "fg_pct": 3, "xp_pct": 3, "in20_rate": 3, "tb_rate": 3,
       "ypa": 2, "ypc": 2, "yptpa": 2, "ypr": 2, "rush_pg": 2, "tkl_pg": 2, "tfl_pg": 2, "sacks_pg": 2, "hurries_pg": 2,
       "pd_pg": 2, "havoc_pg": 2, "sack_rate": 3, "expl_pass": 3, "ypd": 2, "qb_rush_epa": 3, "expl_rush": 3, "stuff_rate": 3,
       "ypt": 2, "catch_rate": 3, "expl_tgt": 3, "fga_pg": 2, "fg_long": 0}


def _round(k, x):
    return r2(x, _DP.get(k, 1)) if isinstance(x, float) or k in _DP else x
POS_KEYS = {"QB": ["value", "value_pg", "epa", "epa_play", "pass_yds", "pass_td", "pass_int", "rush_car", "rush_yds", "rush_td"],
            "RB": ["value", "value_pg", "epa", "epa_play", "rush_car", "rush_yds", "rush_td", "rec", "tgt", "rec_yds", "rec_td"],
            "WR": ["value", "value_pg", "epa", "epa_play", "rec", "tgt", "rec_yds", "rec_td", "rush_yds"],
            "TE": ["value", "value_pg", "epa", "epa_play", "rec", "tgt", "rec_yds", "rec_td"],
            "DL": ["value", "value_pg", "tkl", "tfl", "sacks", "pd", "def_int"], "LB": ["value", "value_pg", "tkl", "tfl", "sacks", "pd", "def_int"],
            "DB": ["value", "value_pg", "tkl", "tfl", "sacks", "pd", "def_int"], "K": ["value", "value_pg", "fgm", "fga"],
            "P": ["value", "value_pg"], "OL": ["value"]}
POS_KEYS_BOX = {p: list(ks) for p, ks in POS_KEYS.items()}       # the season totals (careers' similar players)
for _p, _ks in players.RATE_FIELDS.items():
    POS_KEYS[_p] = POS_KEYS[_p] + [k for k in _ks if k not in POS_KEYS[_p]]
MIN_FLOOR = {"QB": 5, "RB": 4, "WR": 4, "TE": 4, "DL": 4, "LB": 4, "DB": 4, "K": 4, "P": 4, "OL": 4}


def _catalogue(val: pd.DataFrame, mem: list[str], light: bool) -> pd.DataFrame:
    """Players listed in the catalogues: FBS teams, 2+ games (seasons before last: 3+ games, top 1,500 by |value|)."""
    if not len(val):
        return val
    v = val[val["team"].isin(mem) & (val["gp"] >= (3 if light else 2))]
    if light:
        v = v.reindex(v["value"].abs().sort_values(ascending=False).index).head(1500)
    return v.copy()


def players_payload(season: int, val: pd.DataFrame, mem: list[str], light: bool = False) -> dict:
    v = _catalogue(val, mem, light)
    out = {}
    pos_n = {}
    if len(v):
        v["_qr"] = [players.rate_qualified(r) for r in v.to_dict("records")]
        cols = {}
        for k, *_r in PLAYER_METRICS:
            if k in RATE_KEYS:
                # rates: percentile within the position among players with the volume for it (qualified_rate),
                # oriented so that 100 = best (lower-is-better rates reversed); no pooled `pct`
                lower = _r[3]
                q = v[v["_qr"]]
                pp = q.groupby("pos")[k].rank(pct=True, ascending=not lower) * 100
                cols[f"_p_{k}"] = pd.Series(np.nan, index=v.index)
                cols[f"_pp_{k}"] = pp.reindex(v.index).round(0)
                continue
            # box counts: 100 = best too (pass_int was ranked ascending, so the most interceptions read 99th)
            lower = _r[3]
            cols[f"_p_{k}"] = (v[k].rank(pct=True, ascending=not lower) * 100).round(0)
            cols[f"_pp_{k}"] = (v.groupby("pos")[k].rank(pct=True, ascending=not lower) * 100).round(0)
        v = pd.concat([v, pd.DataFrame(cols, index=v.index)], axis=1)
        for r in v.to_dict("records"):
            keys = POS_KEYS.get(r["pos"], ["value"])
            vals = {k: _round(k, r[k]) for k in keys}
            out[r["pid"]] = {"name": r.get("name"), "team": r["team"], "pos": r["pos"], "class": r.get("class"), "gp": int(r["gp"]),
                             "qualified": bool(r["gp"] >= MIN_FLOOR.get(r["pos"], 4)), "qualified_rate": bool(r["_qr"]), "values": vals,
                             "pct": {k: r[f"_p_{k}"] for k in keys if pd.notna(r[f"_p_{k}"])},
                             "pct_pos": {k: r[f"_pp_{k}"] for k in keys if pd.notna(r[f"_pp_{k}"])}}
            pos_n[r["pos"]] = pos_n.get(r["pos"], 0) + 1
    return {"ok": True, "level": LEVEL, "season": season, "updated_at": data.now_iso(), "metrics": metric_list(PLAYER_METRICS),
            "positions": {p: {"label": players.POS_LABEL.get(p, p), "n": n} for p, n in pos_n.items()},
            "min_floor": {"games": MIN_FLOOR, "rate": {p: {"field": c, "per_team_game": x} for p, (c, x) in players.RATE_MIN.items()}},
            "players": out}


def value_row(r: dict) -> dict:
    return {"id": r["pid"], "name": r.get("name"), "team": r["team"], "pos": r["pos"], "class": r.get("class"), "gp": int(r["gp"]),
            "value": r2(r["value"]), "value_pg": r2(r["value_pg"]), "pctl": r2(r["pctl"], 1), "why": r.get("why")}


def value_payload(season: int, val: pd.DataFrame, mem: list[str], repl: dict, validation: dict | None = None) -> dict:
    v = val[val["team"].isin(mem)] if len(val) else val
    leaders_ = [value_row(r) for r in v.sort_values("value", ascending=False).head(200).to_dict("records")] if len(v) else []
    byp = {}
    for p in players.POS_ORDER:
        x = v[(v["pos"] == p) & (v["gp"] >= 2)] if len(v) else v
        if len(x):
            byp[p] = [value_row(r) for r in x.sort_values("value", ascending=False).head(10).to_dict("records")]
    return {"ok": True, "level": LEVEL, "season": season, "updated_at": data.now_iso(),
            "currency": {"key": "value", "label": "Points above replacement",
                         "desc": "Skill positions: EPA credited from the play-by-play (dropbacks and rushes for QBs, rushes and "
                                 "targets for backs and receivers, garbage time excluded) above the EPA a replacement-level "
                                 "player (the non-starters at the position) produces on the same plays. Defence and "
                                 "specialists: box-score points with documented weights above the non-starters' rate per game. "
                                 "Values are comparable within a position, less so across positions.",
                         "replacement": repl},
            "leaders": leaders_, "by_position": byp, "validation": validation}


def moves_payload(season: int, mv: list[dict]) -> dict:
    by = {}
    for m in mv:
        for side, k in (("in", m["to"]), ("out", m["from"])):
            b = by.setdefault(k, {"in": [], "out": [], "net_value": 0.0})
            b[side].append(m["player"])
            val = m["value_after"] if side == "in" else m["value_before"]
            if val is not None:
                b["net_value"] = r2(b["net_value"] + (val if side == "in" else -val))
    best = sorted(mv, key=lambda m: -(m["value_after"] if m["value_after"] is not None else m["value_before"] * 0.5))[:30]
    with_after = [m for m in mv if m["value_after"] is not None]
    return {"ok": True, "season": season, "updated_at": data.now_iso(),
            "note": "Inferred from box scores and rosters (the same athlete id on a different team from one season to the "
                    "next); not the official transfer portal. Value before = last season's value at the old team; value "
                    "after = this season's value so far.",
            "moves": mv, "by_team": by, "best": best,
            "summary": {"n": len(mv), "n_played": len(with_after),
                        "mean_before": r2(np.mean([m["value_before"] for m in mv]) if mv else None),
                        "mean_after": r2(np.mean([m["value_after"] for m in with_after]) if with_after else None)}}


# ── fantasy ─────────────────────────────────────────────────────────────────

def implied_points(preds: pd.DataFrame) -> dict:
    out = {}
    if preds is None or not len(preds):
        return out
    for gid, r in preds.iterrows():
        if not np.isfinite(r.get("total", np.nan)) or not np.isfinite(r.get("margin", np.nan)):
            continue
        out[(gid, r["home"])] = (r["total"] + r["margin"]) / 2
        out[(gid, r["away"])] = (r["total"] - r["margin"]) / 2
    return out


def fantasy_backtest_season(ctx: dict, season: int, pm: dict) -> dict | None:
    """Walk-forward PPR backtest of one season (cached by the season's results and the projection parameters)."""
    import hashlib
    st = data.load_store(season)
    k = hashlib.md5(f"fan2|{season}|{data.results_key(season, st)}|{sorted(fantasy.TUNE.items())}|{ctx['pipe']['key']}".encode()).hexdigest()[:16]
    c = data.cache_get(f"fantasy_bt_{season}", k)
    if c is not None:
        return c
    sp = season_players(ctx, season)
    b = sp["box"]
    if not len(b):
        return None
    pm = dict(pm)
    if len(sp["value"]):
        pm.update(dict(zip(sp["value"]["pid"], sp["value"]["pos"])))
    gp = fantasy.game_points(b, pm)
    r = fantasy.backtest({season: gp}, {season: implied_points(season_state(ctx, season)["preds"])}, "ppr")
    data.cache_put(f"fantasy_bt_{season}", k, r)
    return r


def fantasy_payload(ctx: dict, season: int) -> dict:
    S = season_state(ctx, season)
    sp = season_players(ctx, season)
    pm = dict(pos_map(ctx))
    val = sp["value"]
    if len(val):
        pm.update(dict(zip(val["pid"], val["pos"])))
    gp = fantasy.game_points(sp["box"], pm)
    per = []
    window = [s for s in range(season - 5, season + 1) if s in data.seasons_available()] if season == ctx["current"] else [season]
    for s in window:
        r = fantasy_backtest_season(ctx, s, pm if s == season else pos_map(ctx))
        if r and r.get("n"):
            per.append(r)
    oos = [r for r in per if r["per_season"][0]["season"] not in fantasy.TUNED_ON] or per
    n = sum(r["n"] for r in oos)
    if n:
        bt = {"n": n, "format": "ppr",
              "mae": round(sum(r["mae"] * r["n"] for r in oos) / n, 3), "mae_naive": round(sum(r["mae_naive"] * r["n"] for r in oos) / n, 3),
              "rank_corr": round(float(np.nanmean([r["rank_corr"] for r in oos if r.get("rank_corr") is not None])), 4),
              "rank_corr_naive": round(float(np.nanmean([r["rank_corr_naive"] for r in oos if r.get("rank_corr_naive") is not None])), 4),
              "per_season": [{"season": r["per_season"][0]["season"], "n": r["n"], "mae": r["mae"], "mae_naive": r["mae_naive"],
                              "rank_corr": r["rank_corr"], "rank_corr_naive": r["rank_corr_naive"],
                              "tuning_season": r["per_season"][0]["season"] in fantasy.TUNED_ON} for r in per],
              "seasons": sorted(r["per_season"][0]["season"] for r in oos),
              "method": per[0]["method"] + "; pooled numbers exclude the season the projection parameters were chosen on",
              "tuned_on": ", ".join(str(x) for x in fantasy.TUNED_ON) + " (projection parameters)"}
    else:
        bt = {"n": 0, "mae": None, "mae_naive": None, "rank_corr": None, "rank_corr_naive": None}
    names = {p: (S["st"].get("players") or {}).get(p, {}).get("name") for p in gp["pid"].unique()} if len(gp) else {}
    proj_rows, period = [], None
    if season == ctx["current"] and len(gp):
        today = date.today().isoformat()
        up = S["gf"][(~S["gf"]["final"]) & (S["gf"]["day"] >= today)]
        if len(up):
            wk = up.sort_values("date").iloc[0]["week"]
            up = up[up["week"] == wk] if wk is not None else up[up["day"] <= (date.today() + timedelta(days=7)).isoformat()]
            period = f"Week {int(wk)}" if wk is not None and np.isfinite(wk) else "next 7 days"
            main = gp.groupby(["pid", "team"]).size().reset_index(name="n").sort_values("n").drop_duplicates("pid", keep="last")
            tgt = []
            for r in up.itertuples(index=False):
                for team, opp in ((r.home, r.away), (r.away, r.home)):
                    for pid in main[main["team"] == team]["pid"]:
                        tgt.append({"pid": pid, "team": team, "opp": opp, "pos": pm.get(pid), "gid": r.gid})
            tg = pd.DataFrame(tgt)
            tg = tg[tg["pos"].isin(fantasy.FPOS)] if len(tg) else tg
            res = {}
            for f in fantasy.SCORING:
                res[f] = fantasy.project_rows(gp, tg, f, implied_points(S["preds"])) if len(tg) else pd.DataFrame()
            if len(tg):
                pr = res["ppr"].copy()
                pr["tier"] = fantasy.tiers(pr)
                pr = pr[pr["n"] >= 1]
                for r in pr.sort_values("proj", ascending=False).to_dict("records"):
                    proj_rows.append({"id": r["pid"], "name": names.get(r["pid"]), "team": r["team"], "pos": r["pos"], "opp": r["opp"],
                                      "gid": r["gid"], "proj": r2(r["proj"], 1), "proj_lo": r2(max(r["proj"] - r["sd"], 0), 1),
                                      "proj_hi": r2(r["proj"] + r["sd"], 1), "tier": int(r["tier"]), "opp_factor": r2(r["opp_f"], 2)})
                rankings = {}
                for f, df in res.items():
                    d2 = df[df["n"] >= 1].sort_values("proj", ascending=False)
                    rankings[f] = [{"id": r["pid"], "name": names.get(r["pid"]), "team": r["team"], "pos": r["pos"], "proj": r2(r["proj"], 1)}
                                   for r in d2.head(150).to_dict("records")]
            else:
                rankings = {}
        else:
            rankings = {}
    else:
        rankings = {}
    start_sit, sleepers = [], []
    if proj_rows:
        P = pd.DataFrame(proj_rows)
        for pos in ("QB", "RB", "WR", "TE"):
            x = P[P["pos"] == pos].reset_index(drop=True)
            x["rk"] = np.arange(1, len(x) + 1)
            good = x[(x["opp_factor"] >= 1.15) & (x["rk"].between(8, 40))].head(3)
            bad = x[(x["opp_factor"] <= 0.85) & (x["rk"] <= 20)].head(3)
            start_sit += [{"id": r["id"], "name": r["name"], "pos": pos, "call": "start", "why": f"opponent allows {r['opp_factor']:.2f}x the average to {pos}s"} for r in good.to_dict("records")]
            start_sit += [{"id": r["id"], "name": r["name"], "pos": pos, "call": "sit", "why": f"opponent allows {r['opp_factor']:.2f}x the average to {pos}s"} for r in bad.to_dict("records")]
        last2 = gp.sort_values("date").groupby("pid").tail(2).groupby("pid")["fp_ppr"].mean()
        avg = gp.groupby("pid")["fp_ppr"].mean()
        rise = (last2 - avg).dropna()
        for r in P.itertuples(index=False):
            if r.pos in ("RB", "WR", "TE") and rise.get(r.id, 0) > 4 and (P.index[P["id"] == r.id][0] > 40):
                sleepers.append({"id": r.id, "name": r.name, "pos": r.pos, "team": r.team, "proj": r.proj,
                                 "why": f"last two games {last2.get(r.id, 0):.1f} PPR v {avg.get(r.id, 0):.1f} season average"})
        sleepers = sleepers[:15]
    if season == ctx["current"]:
        ctx["fantasy_proj"] = {r["id"]: {"period": period, "opp": r["opp"], "gid": r["gid"], "proj_ppr": r["proj"],
                                         "proj_lo": r["proj_lo"], "proj_hi": r["proj_hi"], "tier": r["tier"]} for r in proj_rows}
    return {"ok": True, "season": season, "updated_at": data.now_iso(),
            "scoring": {"formats": ["ppr", "half", "std"], "rules": fantasy.SCORING_DOC}, "period": period or "Season",
            "projections": proj_rows[:400], "rankings": rankings, "start_sit": start_sit, "sleepers": sleepers, "backtest": bt}


# ── labs ────────────────────────────────────────────────────────────────────

def lab_players(season: int, val: pd.DataFrame, mem: list[str], light: bool = False) -> dict:
    keys = [k for k, *_ in PLAYER_METRICS]
    fields = ["id", "name", "team", "pos", "class", "gp"] + keys
    v = _catalogue(val, mem, light)
    rows = []
    for r in (v.to_dict("records") if len(v) else []):
        rows.append([r["pid"], r.get("name"), r["team"], r["pos"], r.get("class"), int(r["gp"])] +
                    [r2(r[k], _DP.get(k, 1)) for k in keys])
    return {"ok": True, "kind": "player", "season": season, "fields": fields, "metrics": metric_list(PLAYER_METRICS), "rows": rows}


def lab_teams(season: int, tstats: dict, S: dict) -> dict:
    keys = [k for k, *_ in TEAM_METRICS]
    fields = ["id", "name", "conference", "w", "l"] + keys
    stand = {r["team"]: r for rows in standings(S).values() for r in rows}
    rows = [[t, S["tm"][t].get("short") or S["tm"][t].get("name"), S["tm"][t].get("conference"), stand.get(t, {}).get("w", 0),
             stand.get(t, {}).get("l", 0)] + [v.get(k) for k in keys] for t, v in tstats.items()]
    return {"ok": True, "kind": "team", "season": season, "fields": fields, "metrics": metric_list(TEAM_METRICS), "rows": rows}


# ── game pages ──────────────────────────────────────────────────────────────

def _t(period, clock):
    try:
        p, c = int(period), float(clock)
    except (TypeError, ValueError):
        return None
    if p > 4:
        return 3600 + (p - 5) * 60
    return (p - 1) * 900 + (900 - c)


def wp_model(margin_home: float, t: float, pregame_margin: float, sd: float = 15.5, ep_pos: float = 0.0) -> float:
    """In-game win probability (closed form): remaining-time-weighted pregame margin plus the current margin and the
    possession's expected points, over sd x sqrt(remaining fraction)."""
    rem = max(3600.0 - t, 1.0) / 3600.0
    mu = margin_home + ep_pos + pregame_margin * rem
    return float(norm.cdf(mu / (sd * math.sqrt(rem) + 0.5)))


# rows that are not plays (timeouts, end of a period): kept in the WP series, never listed as a play
_ADMIN = ("timeout", "end of ", "end quarter", "end half", "end game", "start of ", "official timeout")


def _despike(w: np.ndarray, pts: np.ndarray, jump: float = 0.10, back: float = 0.03) -> np.ndarray:
    """ESPN's feed carries isolated bad WP values (a penalty row or a mis-clocked snap jumps 0.2 and the next row
    returns to where it was). A non-scoring row that moves >= `jump` and is undone to within `back` by the next
    row takes the previous row's value."""
    w = w.copy()
    for i in range(1, len(w) - 1):
        a, b = w[i] - w[i - 1], w[i + 1] - w[i]
        if pts[i] <= 0 and abs(a) >= jump and abs(b) >= jump and a * b < 0 and abs(w[i + 1] - w[i - 1]) <= back:
            w[i] = w[i - 1]
    return w


def play_wpa(wp_espn: np.ndarray, pts: np.ndarray, wp_pre: np.ndarray, final: float | None = None) -> np.ndarray:
    """Home win probability added by each row (feed order, which is ESPN's sequence; clocks are sometimes wrong,
    so rows are never re-sorted by time).

    ESPN's `wp_home` (0-1) is the home WP *after* the play: when a game has it on most rows, a row's WPA is its value
    less the previous row's (missing values carry the last known WP forward, isolated spikes are removed; the first
    row's baseline is its own value, so the pregame-to-ESPN gap is not credited to the opening kickoff, unless that
    row scored, when our pregame WP is the baseline). Otherwise `wp_pre` (our model's WP *before* each play) is used:
    a row's WPA is the next row's pre-play WP less its own, and the last row's is the result (`final`, 1/0/0.5) less
    its own."""
    n = len(pts)
    if not n:
        return np.zeros(0)
    e = np.asarray(wp_espn, float)
    pts = np.nan_to_num(np.asarray(pts, float))
    wp_pre = np.asarray(wp_pre, float)
    if np.isfinite(e).mean() > 0.5:
        w = pd.Series(e).ffill().bfill().to_numpy(float)
        w = _despike(w, pts)
        base = w[0] if pts[0] <= 0 else wp_pre[0]
        return np.diff(np.concatenate([[base], w]))
    end = wp_pre[-1] if final is None else float(final)
    return np.diff(np.concatenate([wp_pre, [end]]))


def top_plays(x: pd.DataFrame, wpa: np.ndarray, k: int = 10) -> list[dict]:
    """The k rows with the largest |WPA| (admin rows excluded), largest first, in the payload's play shape."""
    if not len(x):
        return []
    y = x.assign(wpa=np.asarray(wpa, float))
    txt = y["text"].fillna("").astype(str).str.strip().str.lower()
    ok = (txt != "") & ~txt.str.startswith(_ADMIN) & np.isfinite(y["wpa"].to_numpy(float))
    y = y[ok.to_numpy()]
    y = y.assign(aw=y["wpa"].abs()).sort_values("aw", ascending=False, kind="stable").head(k)

    def clock(c):
        try:
            c = float(c)
        except (TypeError, ValueError):
            return None
        return f"{int(c // 60)}:{int(c % 60):02d}" if np.isfinite(c) else None

    out = []
    for r in y.to_dict("records"):
        t = r.get("t")
        out.append({"t": int(t) if t is not None and np.isfinite(float(t)) else None,
                    "period": int(r["period"]) if np.isfinite(float(r["period"])) else None,
                    "clock": clock(r.get("clock_s")), "team": r.get("offense"), "text": str(r.get("text") or "")[:200],
                    "wpa": r2(r["wpa"], 3)})
    return out


def game_page(ctx: dict, season: int, g: dict, cardd: dict, pl: pd.DataFrame | None, tgs: pd.DataFrame | None,
              names: dict, plays_raw: dict | None) -> dict:
    S = season_state(ctx, season)
    tm = S["tm"]
    gid = str(g["id"])
    h, a = str(g["home"]), str(g["away"])
    pred = S["preds"].loc[gid] if len(S["preds"]) and gid in S["preds"].index else None
    b = ctx["pipe"]["blends"].get(season) or {}
    pg_model = None
    if pred is not None and np.isfinite(pred.get("margin", np.nan)):
        pg_model = {"p_home": r2(pred["p_home"], 4), "margin": r2(pred["margin"]), "sd": r2(pred["sd"]), "total": r2(pred["total"], 1),
                    "spread_fair": r2(pred["spread_fair"], 1),
                    "detail": {"d_pts": r2(pred.get("d_pts")), "d_epa": r2(pred.get("d_epa"), 4), "d_sr": r2(pred.get("d_sr"), 4),
                               "model": "full" if (b.get("full") and np.isfinite(pred.get("d_epa", np.nan))) else "points"}}
        inf = informed(ctx, season).get(gid)
        if inf:
            fit = market_informed.fitted() or {}
            ph = game.phase(g.get("week"), g.get("stype") or "reg")
            pg_model.update({"p_home": r2(inf["p_home"], 4), "margin": r2(inf["margin"]), "spread_fair": r2(-inf["margin"], 1),
                             "sd": r2(((fit.get("cal") or {}).get("sd") or {}).get(ph, pred["sd"])),
                             "informed": informed_block(inf)})
    out = dict(cardd)
    out.update({"ok": True, "level": LEVEL, "teams": {t: team_obj(t, tm) for t in (h, a)}, "venue": g.get("venue"),
                "attendance": g.get("attendance"),
                "pregame": {"model": pg_model, "market": cardd.get("market"), "espn_predictor": (g.get("predictor") or {}).get("home"),
                            "elo_p_home": r2(pred.get("elo_p_home"), 4) if pred is not None else None},
                "box": None, "team_stats": g.get("team_stats") or {}, "flow": None, "wp": None, "drives": None, "epa": None,
                "plays": None, "leaders": {}})
    box = g.get("box") or {}
    if box:
        nb = {}
        for tid, bb in box.items():
            cats = {}
            for cat, blk in ((bb or {}).get("players") or {}).items():
                cats[cat] = {"cols": ["id", "name"] + list(blk.get("cols") or []),
                             "rows": [[r[0], names.get(str(r[0]))] + list(r[1:]) for r in blk.get("rows") or []]}
            nb[tid] = {"team": (bb or {}).get("team"), "players": cats}
        out["box"] = nb
        out["team_stats"] = {tid: (bb or {}).get("team") for tid, bb in box.items()}
        lead = {}
        for tid, bb in box.items():
            rows = []
            P = (bb or {}).get("players") or {}
            for cat, fmt_ in (("passing", lambda r, c: f"{r[c.index('cmp') + 1]}/{r[c.index('att') + 1]}, {r[c.index('passing_yards') + 1]} yds, {r[c.index('passing_touchdowns') + 1]} TD, {r[c.index('interceptions') + 1]} INT"),
                              ("rushing", lambda r, c: f"{r[c.index('rushing_attempts') + 1]} car, {r[c.index('rushing_yards') + 1]} yds, {r[c.index('rushing_touchdowns') + 1]} TD"),
                              ("receiving", lambda r, c: f"{r[c.index('receptions') + 1]} rec, {r[c.index('receiving_yards') + 1]} yds, {r[c.index('receiving_touchdowns') + 1]} TD"),
                              ("defensive", lambda r, c: f"{r[c.index('total_tackles') + 1]} tkl, {r[c.index('sacks') + 1]} sacks")):
                blk = P.get(cat) or {}
                c = blk.get("cols") or []
                rr = blk.get("rows") or []
                if rr:
                    try:
                        top = rr[0]
                        rows.append({"id": str(top[0]), "name": names.get(str(top[0])), "cat": cat, "line": fmt_(top, c)})
                    except (ValueError, IndexError):
                        pass
            lead[tid] = rows
        out["leaders"] = lead
    if pl is not None and len(pl):
        x = pl[pl["gid"] == gid]
        if len(x):
            x = x.copy()
            x["t"] = [_t(p, c) for p, c in zip(x["period"], x["clock_s"])]
            hp = np.where((x["scorer"] == h), x["pts"], 0.0)
            ap = np.where((x["scorer"] != h) & (x["pts"] > 0), x["pts"], 0.0)
            margin = np.cumsum(hp) - np.cumsum(ap)
            flow = [[int(t), int(m)] for t, m in zip(x["t"], margin) if t is not None]
            if g.get("hs") is not None and flow:
                flow.append([max(3600, flow[-1][0]), int(g["hs"] - g["as"])])
            out["flow"] = flow[::3] + ([flow[-1]] if flow else [])
            pm = float(pg_model["margin"]) if pg_model else 0.0
            sd = float(pg_model["sd"]) if pg_model else 15.5
            ep_h = np.where(x["offense"] == h, x["ep"].fillna(0), -x["ep"].fillna(0))
            mpre = margin - hp + ap
            wpm = [wp_model(m, t, pm, sd, e) for m, t, e in zip(mpre, x["t"], ep_h) if t is not None]
            ts = [t for t in x["t"] if t is not None]
            espn = [[int(t), r2(w, 3)] for t, w in zip(x["t"], x["wp_home"]) if t is not None and np.isfinite(w)]
            out["wp"] = {"model": [[int(t), r2(w, 3)] for t, w in list(zip(ts, wpm))[::3]], "espn": espn[::3] if espn else []}
            # leverage plays: the top 10 by |home WPA| (ESPN's WP where the game has it, else ours), largest first
            wpre = np.array([wp_model(m, t or 0, pm, sd, e) for m, t, e in zip(mpre, x["t"], ep_h)])
            fin = None
            if g.get("status") == "post" and g.get("hs") is not None and g.get("as") is not None:
                fin = 1.0 if g["hs"] > g["as"] else (0.0 if g["hs"] < g["as"] else 0.5)
            out["plays"] = top_plays(x, play_wpa(x["wp_home"].to_numpy(float), x["pts"].to_numpy(float), wpre, fin), 10)
            ep_by_drive = x.groupby("drive")["epa"].sum().to_dict() if "drive" in x else {}
            gp_ = (plays_raw or {}).get("games", {}).get(gid) or {}
            dr = []
            for d in gp_.get("drives") or []:
                idx, team, period, clock, syte, n, yds, result, is_score = (list(d) + [None] * 9)[:9]
                dr.append({"team": str(team), "period": period, "start": syte, "plays": n, "yards": yds, "result": result,
                           "epa": r2(ep_by_drive.get(idx), 2)})
            out["drives"] = dr or None
    if tgs is not None and len(tgs):
        y = tgs[tgs["gid"] == gid]
        if len(y):
            out["epa"] = {r["team"]: {"epa_play": r2(r["epa"], 3), "sr": r2(r["sr"], 3), "pass_epa": r2(r["pass_epa"], 3),
                                      "rush_epa": r2(r["rush_epa"], 3), "explosive": r2(r["expl"], 3), "plays": int(r["n"])}
                          for r in y.to_dict("records")}
    return out


# ── markets ─────────────────────────────────────────────────────────────────

def live_prices(season: int) -> dict:
    try:
        from oddsmarkets.college.sources import markets as mk
        pev = mk._poly_events(LEVEL)
        out = {}
        for k in (0, 3, 6):
            out.update(mk.game_prices(LEVEL, date.today() + timedelta(days=k), poly_events=pev) or {})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("cfb live prices unavailable: %s", exc)
        return {}


# ── build (one season) ──────────────────────────────────────────────────────

def build(season: int, out_dir=None, stores=None, *, full: bool = True, sims: int = 20000, markets: bool = True,
          current: int | None = None) -> dict:
    season = int(season)
    t0 = datetime.now()
    ctx = context(current)
    base = level_dir(out_dir) / str(season)
    base.mkdir(parents=True, exist_ok=True)
    sizes: dict[str, int] = {}
    cur = ctx["current"]
    S = season_state(ctx, season)
    lp = live_prices(season) if (markets and season == cur) else {}
    cards = season_cards(ctx, season, lp)
    simres = None
    if season == cur and sims and S["gf"]["final"].any():
        try:
            simres = sim.simulate(season, ctx["pipe"], ctx["comm"], n=int(sims))
            ctx["sims"][season] = simres
        except Exception as exc:  # noqa: BLE001
            logger.warning("cfb sim failed: %s", exc)
    sp = season_players(ctx, season)
    val = sp["value"]
    mem = S["mem"]
    light = season < cur - 1
    safe("season", lambda: season_payload(ctx, season, simres, cards), base / "season.json", sizes)
    safe("schedule", lambda: {"ok": True, "level": LEVEL, "season": season, "updated_at": data.now_iso(), "games": cards},
         base / "schedule.json", sizes)
    safe("cfp", lambda: cfp_payload(ctx, season, simres, cards), base / "cfp.json", sizes)
    tst = {}
    try:
        tst = team_stats(ctx, season)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cfb team stats failed: %s", exc)
    safe("teams", lambda: teams_payload(ctx, season, tst), base / "teams.json", sizes)
    try:
        units = players.team_units(val, ctx.get("tgs", {}).get(season), mem) if len(val) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("cfb units failed: %s", exc)
        units = {}
    try:
        mv = move_rows(ctx, season)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cfb moves failed: %s", exc)
        mv = []
    tdir = base / "teams"
    n_team = 0
    for t in mem:
        safe(f"team:{t}", lambda t=t: team_page(ctx, season, t, cards, tst, units, mv, simres, val, light), tdir / f"{t}.json", sizes)
        n_team += 1
    safe("players", lambda: players_payload(season, val, mem, light), base / "players.json", sizes)
    safe("value", lambda: value_payload(season, val, mem, val.attrs.get("replacement", {}) if len(val) else {},
                                        ctx.get("player_validation")),
         base / "value.json", sizes)
    safe("moves", lambda: moves_payload(season, mv), base / "moves.json", sizes)
    safe("fantasy", lambda: fantasy_payload(ctx, season), base / "fantasy.json", sizes)
    safe("lab_players", lambda: lab_players(season, val, mem, light), base / "lab_players.json", sizes)
    safe("lab_teams", lambda: lab_teams(season, tst, S), base / "lab_teams.json", sizes)
    n_games = 0
    if full and season in (cur, cur - 1):
        gdir = base / "games"
        st = S["st"]
        pl = ep.season_epa(season, ep_fit(ctx)) if season in data.plays_seasons() else None
        tgs = ctx.get("tgs", {}).get(season)
        raw = data.load_plays_raw(season) if season in data.plays_seasons() else None
        names = {p: v.get("name") for p, v in (st.get("players") or {}).items()}
        cbi = {c["id"]: c for c in cards}
        keep = set()
        for gid, g in (st.get("games") or {}).items():
            if gid not in cbi:
                continue
            if season == cur - 1 and g.get("stype") not in ("bowl", "cfp"):
                continue
            keep.add(f"{gid}.json")
            safe(f"game:{gid}", lambda g=g, gid=gid: game_page(ctx, season, g, cbi[gid], pl, tgs, names, raw),
                 gdir / f"{gid}.json", sizes)
            n_games += 1
        if gdir.exists():
            for p in gdir.glob("*.json"):
                if p.name not in keep:
                    p.unlink()
    elif (base / "games").exists() and season not in (cur, cur - 1):
        for p in (base / "games").glob("*.json"):      # game pages only for the current and previous season
            p.unlink()
    total = sum(v for k, v in sizes.items())
    return {"ok": True, "level": LEVEL, "season": season, "bytes": total, "files": len(sizes), "teams": n_team,
            "games": n_games, "sim": bool(simres), "seconds": round((datetime.now() - t0).total_seconds(), 1)}


# ── build_level ─────────────────────────────────────────────────────────────

def history_payload(ctx: dict, seasons: list[int]) -> dict:
    champs, conf_ch, best = [], {}, []
    for s in sorted(seasons):
        st = data.load_store(s)
        tm = st.get("teams") or {}
        f = next((g for g in (st.get("games") or {}).values() if g.get("stype") == "cfp" and g.get("round") == "National Championship"
                  and g.get("status") == "post" and g.get("hs") is not None), None)
        if f:
            w, l_ = (f["home"], f["away"]) if f["hs"] > f["as"] else (f["away"], f["home"])
            champs.append({"season": s, "team": str(w), "runner_up": str(l_), "score": f"{max(f['hs'], f['as'])}-{min(f['hs'], f['as'])}",
                           "gid": str(f["id"])})
        cc = {}
        for g in (st.get("games") or {}).values():
            if g.get("stype") == "conf" and g.get("status") == "post" and g.get("hs") is not None and data.real_team(g.get("home")):
                w = str(g["home"] if g["hs"] > g["as"] else g["away"])
                c = (tm.get(w) or {}).get("conference")
                if c:
                    cc[c] = w
        if cc:
            conf_ch[str(s)] = cc
        if s in ctx["pipe"]["final"] and s < ctx["current"]:
            pw, _, _ = sim.power_table(s, ctx["pipe"])
            gf = data.games_frame(s, st)
            for t in [t for t, v in tm.items() if v.get("member") and t in pw]:
                best.append((pw[t], s, t, gf))
    best.sort(key=lambda x: -x[0])
    rows = []
    for v, s, t, gf in best[:25]:
        g = gf[gf["final"] & ((gf["home"] == t) | (gf["away"] == t))]
        w = int(((g["home"] == t) & (g["hs"] > g["as"])).sum() + ((g["away"] == t) & (g["as"] > g["hs"])).sum())
        rows.append({"season": s, "team": t, "rating": r2(v), "record": f"{w}-{len(g) - w}",
                     "name": (data.load_store(s).get("teams") or {}).get(t, {}).get("name")})
    return {"ok": True, "level": LEVEL, "updated_at": data.now_iso(), "champions": champs, "conference_champions": conf_ch,
            "best_teams": rows, "first_season": min(seasons) if seasons else None,
            "notes": ["Champions: the CFP national championship (2014 on) and the BCS title game (2001-2013) as ESPN labels them.",
                      "Best teams: our final ratings (end of season, all games), points v an average FBS team."]}


def calibration_payload(ctx: dict) -> dict:
    pipe = ctx["pipe"]
    cal = backtest.calibration(pipe)
    if not cal.get("ok"):
        return cal
    # the kit's "How sure are we?" block (QK.calib.find reads metrics.model): the walk-forward bins and scores above
    from oddsmarkets.common import calibration as CB
    sm = (cal.get("summary") or {}).get("model") or {}
    blk = CB.from_table(cal.get("calibration") or [], sm.get("n"), sm.get("brier"), sm.get("logloss"))
    if blk:
        cal["metrics"] = {"model": blk}
    try:
        sb = sim.backtest(pipe, ctx["comm"], n=4000)
        cal["sim_detail"] = sb.pop("per_season", [])
        cal["sim"] = sb
    except Exception as exc:  # noqa: BLE001
        cal["sim"] = {"ok": False, "reason": str(exc)}
    comm = ctx["comm"]
    cal["committee"] = {k: comm[k] for k in ("n_seasons", "spearman", "top12_overlap", "top4_overlap", "ap_spearman",
                                              "ap_top12_overlap", "ap_top4_overlap", "features", "weights", "per_season")}
    cal["format_table"] = sim.format_table(list(range(2014, ctx["current"] + 1)))
    cal["players"] = ctx.get("player_validation")
    cal["informed"] = INF.summary(LEVEL)
    return cal


def markets_payload(ctx: dict, season: int, markets: bool) -> dict:
    fut = None
    if markets:
        try:
            from oddsmarkets.college.sources import markets as mk
            fut = mk.futures(LEVEL, season)
        except Exception as exc:  # noqa: BLE001
            logger.info("cfb futures unavailable: %s", exc)
    simres = ctx["sims"].get(season)
    model = {"champion": {}, "conference": {}, "playoff": {}}
    if simres:
        model["champion"] = {t: v["p_title"] for t, v in simres["teams"].items() if v["p_title"] > 0}
        model["playoff"] = {t: v["p_cfp"] for t, v in simres["teams"].items() if v["p_cfp"] > 0}
        model["conference"] = {c: {r["team"]: r["p_win"] for r in rows if r["p_win"] > 0} for c, rows in simres["conf"].items()}
    games = {}
    if season == ctx["current"]:
        S = season_state(ctx, season)
        lp = live_prices(season) if markets else {}
        today = date.today().isoformat()
        horizon = (date.today() + timedelta(days=7)).isoformat()
        for gid, g in (S["st"].get("games") or {}).items():
            d = data.us_day(g.get("date"))
            if g.get("status") != "pre" or not d or not (today <= d <= horizon) or not (data.real_team(g.get("home")) and data.real_team(g.get("away"))):
                continue
            pr = S["preds"].loc[gid] if gid in S["preds"].index else None
            if pr is None or not np.isfinite(pr["p_home"]):
                continue
            mo = {"p_home": r2(pr["p_home"], 4), "margin": r2(pr["margin"]), "total": r2(pr["total"], 1)}
            inf = informed(ctx, season).get(str(gid))
            if inf:
                mo.update({"p_home": r2(inf["p_home"], 4), "margin": r2(inf["margin"])})
            mk_ = market_of(g, lp, 15.5)
            games[gid] = {"home": str(g["home"]), "away": str(g["away"]), "date": g.get("date"), "model": mo, "market": mk_,
                          "edge": r2(mo["p_home"] - mk_["p_home"], 4) if mk_ and mk_.get("p_home") is not None else None}
    return {"ok": True, "level": LEVEL, "season": season, "updated_at": data.now_iso(), "fetched": bool(fut and not fut.get("error")),
            "futures": fut, "model": model, "games": games}


SIM_GROUP = {"QB": "cfb_qb", "RB": "cfb_rb", "WR": "cfb_wr", "TE": "cfb_te", "DL": "cfb_dl", "LB": "cfb_lb", "DB": "cfb_db",
             "K": "cfb_k", "P": "cfb_p"}


def similar_players(vals: dict[int, pd.DataFrame], current: int, k: int | None = None) -> dict[str, list]:
    """{pid: [{"id","name","team","season","distance"}]} for players rate-qualified in the current or last season (their
    latest such season): the spec's weighted nearest player-seasons of the same position among rate-qualified rows of
    the seasons in `vals`, other players only."""
    from oddsmarkets.common import similar as SIM
    out: dict[str, list] = {}
    for pos, gid in SIM_GROUP.items():
        cfg = SIM.group_config("college", gid)
        if not cfg:
            continue
        feats = cfg["features"]
        parts = []
        for s, v in vals.items():
            if s > current or s < current - 9 or not len(v):
                continue
            x = v[v["pos"] == pos]
            if not len(x):
                continue
            x = x[[players.rate_qualified(r) for r in x.to_dict("records")]]
            if len(x):
                parts.append(x.assign(_season=s))
        if not parts:
            continue
        X = pd.concat(parts, ignore_index=True)
        if len(X) < 6:
            continue
        M = np.column_stack([pd.to_numeric(X[f], errors="coerce").to_numpy(float) if f in X else np.full(len(X), np.nan)
                             for f in feats])
        M[~np.isfinite(M)] = np.nan
        Z = SIM.zscore(M, X["_season"].tolist())
        w = np.array([cfg["weights"][f] for f in feats])
        pids = X["pid"].astype(str).to_numpy()
        seas = X["_season"].to_numpy(int)
        latest: dict[str, int] = {}
        for i, (pid_, s_) in enumerate(zip(pids, seas)):
            if s_ >= current - 1 and (pid_ not in latest or s_ > seas[latest[pid_]]):
                latest[pid_] = i
        names, teams = X["name"].tolist(), X["team"].tolist()
        for pid_, i in latest.items():
            nb = SIM.nearest(Z, i, w, k or cfg["k"], allowed=pids != pid_)
            out[pid_] = [{"id": pids[j], "name": names[j], "team": teams[j], "season": int(seas[j]), "distance": r2(d, 2)}
                         for j, d in nb]
    return out


def prev_ring(prev_cat: Any, pid: str, pos: str | None, season: int) -> dict:
    """Last season's position percentiles for a current block (kit v3 rail rings, 23 Oct 2026): {"prev_pct_pos" (last
    season's pct_pos, the same shape), "prev_peer" {"season", "pos", "gp", "qualified"}} when the player was qualified
    at the same position last season, else {}. prev_cat: last season's players.json (packed or not)."""
    from oddsmarkets.college import packing as PK
    P = (PK.unpack(prev_cat) or {}).get("players") if isinstance(prev_cat, dict) else None
    r = (P or {}).get(str(pid)) if isinstance(P, dict) else None
    if not r or r.get("qualified") is False or not pos or r.get("pos") != pos or not r.get("pct_pos"):
        return {}
    return {"prev_pct_pos": r["pct_pos"], "prev_peer": {"season": season, "pos": r.get("pos"), "gp": r.get("gp"),
                                                         "qualified": r.get("qualified") is not False}}


def career_files(ctx: dict, out: Path, current: int, sizes: dict) -> int:
    seasons = [s for s in data.seasons_available() if current - 6 <= s <= current]
    vals = {}
    for s in seasons:
        try:
            v = season_players(ctx, s)["value"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("cfb players %s failed: %s", s, exc)
            continue
        if len(v):
            vals[s] = v
    recent = set()
    for s in (current - 1, current):
        if s in vals:
            recent |= set(vals[s]["pid"])
    if not recent:
        return 0
    cur_box = season_players(ctx, current)["box"] if current in vals else pd.DataFrame()
    stores = {s: data.load_store(s) for s in vals}
    by_pid: dict[str, list] = {}
    for s, v in vals.items():
        for r in v[v["pid"].isin(recent)].to_dict("records"):
            by_pid.setdefault(r["pid"], []).append((s, r))
    logs = {}
    if len(cur_box):
        cb = cur_box[cur_box["pid"].isin(recent)].sort_values("date")
        gm = stores[current].get("games") or {}
        for r in cb.to_dict("records"):
            g = gm.get(r["gid"]) or {}
            mine = g.get("hs") if r["home"] else g.get("as")
            theirs = g.get("as") if r["home"] else g.get("hs")
            res = None if mine is None else (("W" if mine > theirs else "L") + f" {mine}-{theirs}")
            logs.setdefault(r["pid"], []).append({"game": r["gid"], "date": r["date"], "opp": r["opp"], "home": bool(r["home"]), "res": res,
                                                  **{k: (r2(r[k], 1) if isinstance(r[k], float) and r[k] != int(r[k]) else int(r[k]))
                                                     for k in ("pass_cmp", "pass_att", "pass_yds", "pass_td", "pass_int", "rush_car",
                                                               "rush_yds", "rush_td", "rec", "rec_yds", "rec_td", "tkl", "sacks", "def_int") if r[k]}})
    mv_all = {}
    for s in seasons:
        if s - 1 in vals and s in vals:
            for m in players.moves(vals[s - 1], vals[s], stores[s]):
                mv_all.setdefault(m["player"], []).append({"season": s, "from": m["from"], "to": m["to"],
                                                           "value_before": m["value_before"], "value_after": m["value_after"]})
    # similar players (docs/METRICS_SPEC.md): the position group's features and year-to-year weights from
    # docs/_design/metrics/college.json, z within position and season over rate-qualified player-seasons, weighted
    # Euclidean (common.similar), k = 5, from the seasons loaded here (the last seven), never the player himself
    sim_map = similar_players(vals, current)
    pc_path = out / str(current - 1) / "players.json"
    prev_cat = json.loads(pc_path.read_text(encoding="utf-8")) if pc_path.exists() else None
    pdir = out / "players"
    n = 0
    keep = set()
    for pid, rows in by_pid.items():
        rows.sort(key=lambda x: x[0])
        info = {}
        for s in sorted(stores, reverse=True):
            p = (stores[s].get("players") or {}).get(pid)
            if p:
                for k in ("name", "pos", "class", "height_in", "weight_lb", "hometown"):
                    if info.get(k) is None and p.get(k) is not None:
                        info[k] = p.get(k)
        last = rows[-1][1]
        seasons_rows = []
        for s, r in rows:
            seasons_rows.append({"season": s, "team": r["team"], "gp": int(r["gp"]), "pos": r["pos"],
                                 "cmp": int(r["pass_cmp"]), "att": int(r["pass_att"]), "pass_yds": int(r["pass_yds"]),
                                 "pass_td": int(r["pass_td"]), "int": int(r["pass_int"]), "car": int(r["rush_car"]),
                                 "rush_yds": int(r["rush_yds"]), "rush_td": int(r["rush_td"]), "rec": int(r["rec"]),
                                 "tgt": int(r["tgt"]), "rec_yds": int(r["rec_yds"]), "rec_td": int(r["rec_td"]),
                                 "tkl": int(r["tkl"]), "tfl": r2(r["tfl"], 1), "sacks": r2(r["sacks"], 1),
                                 "def_int": int(r["def_int"]), "pd": int(r["pd"]), "epa": r2(r["epa"], 1),
                                 "epa_play": r2(r["epa_play"], 3), "value": r2(r["value"]), "value_pg": r2(r["value_pg"]),
                                 "pctl": r2(r["pctl"], 1)})
        current_block = None
        if rows[-1][0] == current:
            current_block = {"season": current, "team": last["team"], "log": logs.get(pid, []), "value": value_row(last),
                             "fantasy": (ctx.get("fantasy_proj") or {}).get(pid)}
            current_block.update(prev_ring(prev_cat, pid, last["pos"], current - 1))
        obj = {"ok": True, "id": pid, "name": info.get("name") or last.get("name"), "pos": last["pos"], "level": LEVEL,
               "updated_at": data.now_iso(), "class": info.get("class"), "height_in": info.get("height_in"),
               "weight_lb": info.get("weight_lb"), "hometown": info.get("hometown"), "seasons": seasons_rows,
               "current": current_block, "moves": mv_all.get(pid, []), "similar": sim_map.get(pid, [])}
        sizes[f"player:{pid}"] = write(pdir / f"{pid}.json", obj)
        keep.add(f"{pid}.json")
        n += 1
    if pdir.exists():
        for p in pdir.glob("*.json"):
            if p.name not in keep:
                p.unlink()
    return n


def player_validation(ctx: dict, current: int) -> dict:
    ss = [s for s in data.seasons_available() if current - 6 <= s <= current]
    vals, attr, toff = {}, {}, {}
    for s in ss:
        sp = season_players(ctx, s)
        if len(sp["value"]):
            vals[s] = sp["value"]
        attr[s] = sp.get("attr_cols")
        toff[s] = {t: r.get("epa_off") for t, r in season_state(ctx, s)["ratings"].items()}
    return players.validate(vals, attr, toff)


def build_level(out_dir=None, seasons: list[int] | None = None, current: int | None = None, *, markets: bool = True,
                careers: bool = True, sims: int = 20000) -> dict:
    t0 = datetime.now()
    ctx = context(current)
    cur = ctx["current"]
    out = level_dir(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    seasons = sorted(seasons or data.seasons_available())
    sizes: dict[str, int] = {}
    if cur not in ctx["sims"] and sims:
        try:
            S = season_state(ctx, cur)
            if S["gf"]["final"].any():
                ctx["sims"][cur] = sim.simulate(cur, ctx["pipe"], ctx["comm"], n=int(sims))
        except Exception as exc:  # noqa: BLE001
            logger.warning("cfb sim failed: %s", exc)
    try:
        ctx["player_validation"] = player_validation(ctx, cur)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cfb player validation failed: %s", exc)
    safe("calibration", lambda: calibration_payload(ctx), out / "calibration.json", sizes)
    safe("history", lambda: history_payload(ctx, seasons), out / "history.json", sizes)
    safe("markets", lambda: markets_payload(ctx, cur, markets), out / "markets.json", sizes)
    n_players = 0
    if careers and "fantasy_proj" not in ctx:
        try:                              # the current block of each career file carries this week's projection
            fantasy_payload(ctx, cur)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cfb fantasy projections for careers failed: %s", exc)
    if careers:
        try:
            n_players = career_files(ctx, out, cur, sizes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cfb careers failed: %s", exc)
            logger.debug(traceback.format_exc())
    return {"ok": True, "level": LEVEL, "bytes": sum(sizes.values()), "files": len(sizes), "players": n_players,
            "seconds": round((datetime.now() - t0).total_seconds(), 1)}


def reset() -> None:
    """Forget the in-process context (tests, or a long-running process after the stores changed)."""
    _CTX.clear()
    data.clear_memo()
