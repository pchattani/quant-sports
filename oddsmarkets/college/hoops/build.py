"""
Basketball payload writer for The Quant Campus (PAYLOADS.md, CONTRACT.md section 3), both levels (`mbb`, `wbb`).

    build(level, season, out_dir, stores=None, *, full=True, sims=10000, markets=True) -> summary dict
        writes out_dir/<L>/<S>/: season.json, schedule.json, bracket.json, teams.json, teams/<tid>.json,
        players.json, value.json, moves.json, fantasy.json, lab_players.json, lab_teams.json and games/<gid>.json
        (finished and live games of the current season; the previous season's postseason: NCAA, NIT, WBIT, other
        postseason and conference tournament games). `full=False` skips the game pages only (scripts/build_campus.py
        passes full=True for the newest --game-page-seasons); past seasons are written compactly (`is_archive`), and
        lists are column-packed (FORMAT, oddsmarkets/college/packing.py).
    migrate(level, out_dir, season) -> files rewritten: upgrades a season folder written in an older FORMAT.
    build_level(level, out_dir, seasons, current, *, sims=10000, markets=True, full=True) -> summary dict
        writes out_dir/<L>/: calibration.json, history.json, markets.json, players/<pid>.json (players with a game in
        the last two seasons that have box scores), then calls build() for each season.

`out_dir` is the data root (docs/campus/data, env CAMPUS_DATA). `stores` is accepted for the contract's signature
and ignored: stores are read through oddsmarkets.college.store (read only). Every payload is isolated: a failure is
written as {"ok": false, "reason"}. Models are in model.py / ratings.py / ncaa.py / sim.py / players.py; the
methodology and validation are in docs/campus/MODELS_HOOPS.md.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import traceback
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import norm

from oddsmarkets.college import canon
from oddsmarkets.college import progression as PROG
from oddsmarkets.college.store import jersey_number
from oddsmarkets.college import informed as INF
from oddsmarkets.college import packing as PK
from oddsmarkets.college import store as ST
from oddsmarkets.college.hoops import backtest as BT
from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import market_informed as HMI
from oddsmarkets.college.hoops import model as M
from oddsmarkets.college.hoops import ncaa as N
from oddsmarkets.college.hoops import players as PL
from oddsmarkets.college.hoops import ratings as R
from oddsmarkets.college.hoops import sim as SM
from oddsmarkets.college.hoops import tourney as TT

logger = logging.getLogger(__name__)
VERSION = 1
# Payload format (season.json "fmt"): 2 = packed lists (oddsmarkets/college/packing.py) in schedule.json, players.json,
# team pages, careers and game pages; archive team pages without a schedule. migrate() upgrades older season folders
# (scripts/build_campus.py runs it on the seasons CI restores from the live site instead of rebuilding).
FORMAT = 2
REGION_NAMES = {"mbb": ["East", "West", "South", "Midwest"], "wbb": ["Regional 1", "Regional 2", "Regional 3", "Regional 4"]}
POST_PAGES = ("ncaa", "nit", "wbit", "post", "conf")
SPREAD_SD = {"mbb": 10.5, "wbb": 11.0}


# ── small helpers ───────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def r2(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 2)


def r1(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 1)


def r3(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 3)


def r4(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 4)


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    return o


def write(p: Path, obj: Any) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(_clean(obj), fh, ensure_ascii=False, separators=(",", ":"))
    for k in range(8):                                 # Windows: a reader holding the file blocks the replace briefly
        try:
            os.replace(tmp, p)
            break
        except PermissionError:
            if k == 7:
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            time.sleep(0.25 * (k + 1))
    return p.stat().st_size


def fail(reason: str, **kw) -> dict:
    return {"ok": False, "reason": reason, **kw}


def american_p(ml_h, ml_a) -> float | None:
    def p(a):
        try:
            a = float(a)
        except (TypeError, ValueError):
            return None
        if a == 0:
            return None
        return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)
    a, b = p(ml_h), p(ml_a)
    if a is None or b is None:
        return None
    return a / (a + b)


def team_rec(st: dict, tid: str) -> dict:
    t = (st.get("teams") or {}).get(tid) or {}
    return {"name": t.get("name"), "short": t.get("short"), "abbr": t.get("abbr"), "colour": t.get("colour"),
            "alt_colour": t.get("alt_colour"), "alt": t.get("alt_colour"), "conference": t.get("conference"),
            "member": bool(t.get("member"))}


# ── level context (cached per process) ──────────────────────────────────────

_CTX: dict[str, dict] = {}


def context(level: str, refresh: bool = False) -> dict:
    lv = D.level_of(level)
    ss = D.seasons(lv)
    sig = D.content_sig(lv, ss)
    c = _CTX.get(lv)
    if c and c["sig"] == sig and not refresh:
        return c
    t0 = time.perf_counter()
    state = M.level_state(lv, ss)
    pre = {}
    for s in ss:
        try:
            pre[s] = N.pretourney(state, s)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s pretourney failed: %s", lv, s, exc)
            pre[s] = None
    pre = {s: p for s, p in pre.items() if p}
    rows = N.selection_rows(state, pre)
    loso = N.selection_loso(rows) if len(rows) >= 2 else None
    sel_all = N.fit_on(rows, list(rows)) if rows else None
    c = {"level": lv, "sig": sig, "seasons": ss, "state": state, "pre": pre, "sel_rows": rows, "loso": loso,
         "sel_all": sel_all, "bundles": {}, "players": {}, "brows": {}, "tbt": None, "bt": None}
    _CTX[lv] = c
    logger.info("%s context in %.1fs", lv, time.perf_counter() - t0)
    return c


def current_season(level: str) -> int:
    return canon.current_season(level)


def season_fit(ctx: dict, s: int) -> dict:
    b = ctx["bundles"].setdefault(s, {})
    if "fit" not in b:
        b["fit"] = M.current_fit(ctx["state"], s)
    return b["fit"]


def box_rows(ctx: dict, s: int) -> dict:
    if s not in ctx["brows"]:
        ctx["brows"][s] = PL.box_rows(ctx["level"], s)
    return ctx["brows"][s]


def player_rows(ctx: dict, s: int) -> dict:
    """season_players for season s (team ratings = the season fit), {} rows when the season has no box scores."""
    if s in ctx["players"]:
        return ctx["players"][s]
    if s not in ctx["state"]["tabs"]:
        ctx["players"][s] = {"rows": {}, "params": None}
        return ctx["players"][s]
    tab = ctx["state"]["tabs"][s]
    br = box_rows(ctx, s)
    if not len(br["pid"]):
        ctx["players"][s] = {"rows": {}, "params": None}
        return ctx["players"][s]
    f = season_fit(ctx, s)
    ratings = {t: {"rating": float(f["net"][i]), "tempo": float(f["tempo"][i])} for i, t in enumerate(tab["teams"])}
    ctx["players"][s] = PL.season_players(ctx["level"], s, ratings, br)
    return ctx["players"][s]


# ── cards ───────────────────────────────────────────────────────────────────

def _gindex(tab: dict) -> dict[str, int]:
    if "_gi" not in tab:
        tab["_gi"] = {g: i for i, g in enumerate(tab["g"]["gid"])}
        tab["_pi"] = {g: i for i, g in enumerate(tab["pend"]["gid"])}
    return tab["_gi"]


def game_model(ctx: dict, s: int, g: dict) -> dict | None:
    """Pregame model for a game: walk-forward prediction for finished games, current ratings for the rest."""
    st8 = ctx["state"]
    tab = st8["tabs"].get(s)
    if not tab:
        return None
    gi = _gindex(tab)
    gid = str(g["id"])
    if gid in gi:
        k = gi[gid]
        pr = st8["preds"][s]
        if not np.isfinite(pr["mu"][k]):
            return None
        return {"p_home": r4(pr["p"][k]), "margin": r1(pr["mu"][k]), "total": r1(pr["total"][k]), "sd": r1(pr["sd"][k])}
    idx = tab["idx"]
    h, a = str(g.get("home")), str(g.get("away"))
    hi = idx.get(h, idx[D.ND1] if h else None)
    ai = idx.get(a, idx[D.ND1] if a else None)
    if hi is None or ai is None or hi == ai:
        return None
    f = season_fit(ctx, s)
    prm = st8["params"].get(s) or st8["params"]["latest"]
    neutral = bool(g.get("neutral"))
    p = M.predict_one(f, hi, ai, neutral, prm, se=f.get("se"))
    return {"p_home": r4(p["p_home"]), "margin": r1(p["margin"]), "total": r1(p["total"]), "sd": r1(p["sd"])}


def informed(ctx: dict, s: int) -> dict[str, dict]:
    """The market-informed model (hoops/market_informed.py) for season s: {gid: ...}; {} without a committed fit for
    the season, or on failure (the published model is unaffected)."""
    cache = ctx.setdefault("informed", {})
    if s not in cache:
        try:
            cache[s] = HMI.predict(ctx["state"], ctx["level"], s, season_fit(ctx, s)) if s in ctx["state"]["tabs"] else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s market-informed model failed for %s: %s", ctx["level"], s, exc)
            cache[s] = {}
    return cache[s]


def informed_block(inf: dict | None) -> dict | None:
    if not inf:
        return None
    return {"p_home": r4(inf["p_home"]), "margin": r1(inf["margin"]), "base_p": r4(inf["base_p"]),
            "base_margin": r1(inf["base_margin"]), "mk_spread": r1(-inf["mk"]) if np.isfinite(inf["mk"]) else None,
            "rd": r1(inf["rd"]) if np.isfinite(inf["rd"]) else None, "status": inf.get("status") or "trial"}


def game_market(level: str, g: dict) -> dict | None:
    o = D.clean_odds(level, g.get("odds"))
    sp, tot = o["spread"], o["total"]
    ph = american_p(o["ml_home"], o["ml_away"])
    if ph is None and sp is not None:
        ph = float(norm.cdf(-float(sp) / SPREAD_SD[level]))
    if ph is None and sp is None and tot is None:
        return None
    src = "espn_close" if g.get("status") == "post" else "espn"
    return {"p_home": r4(ph), "spread_home": sp, "total": tot, "source": src}


COMPACT_KEYS = ("id", "season", "date", "status", "stype", "round", "region", "home", "away", "hs", "as", "hr", "ar",
                "hseed", "aseed", "neutral", "conf_game", "model", "market", "result")


def slim(c: dict, compact: bool = False) -> dict:
    """A CARD without its null-valued keys and false `neutral` / `conf_game` (PAYLOADS: a missing CARD key reads as
    null, i.e. false for the flags); `compact` keeps only the
    fields a list needs (archive seasons: schedule and team pages), model.p_home and market.spread_home."""
    out = {}
    for k, v in c.items():
        if v is None or (compact and k not in COMPACT_KEYS) or (v is False and k in ("neutral", "conf_game")):
            continue
        if isinstance(v, dict):
            v = {a: b for a, b in v.items() if b is not None}
            if compact and k == "model":
                v = {a: b for a, b in v.items() if a == "p_home"}
            elif compact and k == "market":
                v = {a: b for a, b in v.items() if a == "spread_home"}
                if not v:
                    continue
        out[k] = v
    return out


def card(ctx: dict, s: int, g: dict) -> dict:
    sd = g.get("seeds") or {}
    rk = g.get("ranks") or {}
    mdl = game_model(ctx, s, g)
    mk = game_market(ctx["level"], g)
    res = None
    if g.get("status") == "post" and g.get("hs") is not None and g.get("as") is not None:
        margin = float(g["hs"]) - float(g["as"])
        cover = None
        if mk and mk.get("spread_home") is not None:
            c = margin + float(mk["spread_home"])
            cover = "home" if c > 0 else ("away" if c < 0 else "push")
        mc = None
        if mdl and mdl.get("p_home") is not None:
            mc = (mdl["p_home"] > 0.5) == (margin > 0)
        res = {"cover": cover, "model_correct": mc}
    live = g.get("status") == "in"
    return {"id": str(g["id"]), "season": s, "date": g.get("date"), "status": g.get("status"), "stype": g.get("stype"),
            "round": g.get("round"), "region": g.get("region"), "note": g.get("note"), "week": None,
            "home": str(g.get("home")), "away": str(g.get("away")), "hs": g.get("hs"), "as": g.get("as"),
            "hr": rk.get("home"), "ar": rk.get("away"), "hseed": sd.get("home"), "aseed": sd.get("away"),
            "neutral": bool(g.get("neutral")), "conf_game": bool(g.get("conf_game")),
            "period": g.get("periods") if live else None, "clock": g.get("clock") if live else None,
            "model": {k: mdl[k] for k in ("p_home", "margin", "total")} if mdl else None, "market": mk, "result": res,
            "tba": True if canon.time_tba(g) else None}           # start time not set yet (shown as TBA)


def is_archive(level: str, s: int) -> bool:
    """Past seasons (every season before the current one: from 1 May the site's current season is the coming one) are
    written compactly (size budget, PAYLOADS.md): compact CARDs in schedules, team pages without a schedule (the page
    reads schedule.json), qualified players only in the player catalogue and lab, the top 12 of each team roster, no
    suggestions. The previous season's postseason game pages are still written (game_pages)."""
    return s < current_season(level)


def archive(ctx: dict, s: int) -> bool:
    return is_archive(ctx["level"], s)


# ── season bundle ───────────────────────────────────────────────────────────

def _week_of(day: int, d0: int) -> int:
    return (day - d0) // 7 + 1


def bundle(ctx: dict, s: int) -> dict:
    """Everything the per-season payloads share (cached)."""
    b = ctx["bundles"].setdefault(s, {})
    if b.get("done"):
        return b
    lv = ctx["level"]
    st8 = ctx["state"]
    tab = st8["tabs"][s]
    st = D.load(lv, s)
    f = season_fit(ctx, s)
    G = tab["g"]
    T = tab["T"]
    teams = tab["teams"]
    mem = tab["member"]
    prm = st8["params"].get(s) or st8["params"]["latest"]
    # ranks
    order = np.argsort(-np.where(mem, f["net"], -1e9))
    rank = np.empty(T, int)
    rank[order] = np.arange(1, T + 1)
    # sos and luck from played games
    gp = np.bincount(np.concatenate([G["h"], G["a"]]), minlength=T).astype(float)
    sos = (np.bincount(G["h"], weights=f["net"][G["a"]], minlength=T) + np.bincount(G["a"], weights=f["net"][G["h"]], minlength=T)) / np.maximum(gp, 1)
    so = np.argsort(-np.where(mem, sos, -1e9))
    sos_rank = np.empty(T, int)
    sos_rank[so] = np.arange(1, T + 1)
    pace = f["tempo"][G["h"]] + f["tempo"][G["a"]] - f["league_pace"]
    mu = prm["s"] * (f["net"][G["h"]] - f["net"][G["a"]]) * pace / 100.0 + prm["hca"] * (~G["neutral"])
    pw = norm.cdf(mu / prm["s0"])
    hw = (G["hs"] > G["as"]).astype(float)
    exp_w = np.bincount(G["h"], weights=pw, minlength=T) + np.bincount(G["a"], weights=1 - pw, minlength=T)
    act_w = np.bincount(G["h"], weights=hw, minlength=T) + np.bincount(G["a"], weights=1 - hw, minlength=T)
    luck = (act_w - exp_w) / np.maximum(gp, 1)
    ratings = {}
    for i, t in enumerate(teams):
        if not mem[i]:
            continue
        ratings[t] = {"rating": r2(f["net"][i]), "off": r2(f["off"][i]), "def": r2(f["def"][i]), "tempo": r2(f["tempo"][i]),
                      "se": r2((f.get("se") if f.get("se") is not None else np.full(T, 5.0))[i]), "rank": int(rank[i]),
                      "games": int(gp[i]), "sos": r2(sos[i]), "sos_rank": int(sos_rank[i]), "luck": r3(luck[i])}
    # Kalman paths (weekly)
    d0 = int(G["day"].min()) if len(G["day"]) else None
    paths = {}
    if len(G["day"]) >= 50:
        pr = st8["priors"][s]
        kp = R.paths(tab, {"net": np.asarray(pr["off"]) - np.asarray(pr["def"]), "se": pr["se"]}, hca=f["hca"])
        days = np.array(kp["days"])
        wk = (days - d0) // 7
        last_of_week = {}
        for k, w in enumerate(wk):
            last_of_week[int(w)] = k
        for i, t in enumerate(teams):
            if mem[i]:
                paths[t] = [[D.day_str(int(days[k])), r2(kp["net"][k, i])] for w, k in sorted(last_of_week.items())]
    # model ranks by week (walk snaps) for rank history and power prev
    snaps = st8["walks"][s]["snaps"]
    snap_rank = []
    for d, nets in snaps:
        nets = np.array(nets)
        o2 = np.argsort(-np.where(mem, nets, -1e9))
        rk2 = np.empty(T, int)
        rk2[o2] = np.arange(1, T + 1)
        snap_rank.append((d, rk2))
    b.update({"st": st, "tab": tab, "fit": f, "rank": rank, "ratings": ratings, "paths": paths, "snap_rank": snap_rank,
              "d0": d0, "prm": prm, "sos": sos})
    b["standings"] = standings(ctx, s, b)
    b["team_stats"] = team_stats(lv, st, tab)
    b["done"] = True
    return b


def _ap_latest(st: dict, kind: str = "ap") -> tuple[list, list]:
    polls = (st.get("rankings") or {}).get(kind) or {}
    num = sorted((k for k in polls if str(k).isdigit()), key=int)
    keys = (["pre"] if "pre" in polls else []) + num + (["final"] if "final" in polls else [])
    if not keys:
        return [], []
    cur = polls[keys[-1]]
    prev = polls[keys[-2]] if len(keys) > 1 else []
    return cur, prev


def polls_payload(st: dict) -> dict:
    out = {}
    for kind in ("ap", "coaches"):
        cur, prev = _ap_latest(st, kind)
        pr = {str(r[1]): r[0] for r in prev}
        out[kind] = [{"rank": r[0], "team": str(r[1]), "points": r[2] if len(r) > 2 else None,
                      "first": r[3] if len(r) > 3 else None, "prev": pr.get(str(r[1]))} for r in cur]
    return out


def standings(ctx: dict, s: int, b: dict) -> dict:
    st, tab = b["st"], b["tab"]
    teams = st.get("teams") or {}
    rec = defaultdict(lambda: {"w": 0, "l": 0, "conf_w": 0, "conf_l": 0, "home": [0, 0], "away": [0, 0], "neutral": [0, 0],
                               "pf": 0, "pa": 0, "seq": []})
    games = sorted((g for g in (st.get("games") or {}).values() if g.get("status") == "post" and g.get("hs") is not None
                    and g.get("stype") in D.COUNTED), key=lambda g: g.get("date") or "")
    for g in games:
        h, a = str(g["home"]), str(g["away"])
        hw = g["hs"] > g["as"]
        for t, w, pf, pa, side in ((h, hw, g["hs"], g["as"], "home"), (a, not hw, g["as"], g["hs"], "away")):
            if not (teams.get(t) or {}).get("member"):
                continue
            r = rec[t]
            r["w" if w else "l"] += 1
            v = "neutral" if g.get("neutral") else side
            r[v][0 if w else 1] += 1
            r["pf"] += pf
            r["pa"] += pa
            r["seq"].append("W" if w else "L")
            if g.get("conf_game") and g.get("stype") == "reg":
                r["conf_w" if w else "conf_l"] += 1
    ap, _ = _ap_latest(st)
    apr = {str(x[1]): x[0] for x in ap}
    out = defaultdict(list)
    for t, v in teams.items():
        if not v.get("member"):
            continue
        r = rec[t]
        seq = r["seq"]
        streak = None
        if seq:
            k = 1
            while k < len(seq) and seq[-k - 1] == seq[-1]:
                k += 1
            streak = f"{seq[-1]}{k}"
        rt = b["ratings"].get(t) or {}
        out[v.get("conference") or "none"].append({"team": t, "w": r["w"], "l": r["l"], "conf_w": r["conf_w"], "conf_l": r["conf_l"],
                                                    "home": r["home"], "away": r["away"], "neutral": r["neutral"], "streak": streak,
                                                    "pf": r["pf"], "pa": r["pa"], "rank": apr.get(t), "rating_rank": rt.get("rank"),
                                                    "conf_rank": None})
    for c, rows in out.items():
        rows.sort(key=lambda r: (-(r["conf_w"] / max(r["conf_w"] + r["conf_l"], 1)), -r["conf_w"],
                                 -(r["w"] / max(r["w"] + r["l"], 1)), r["rating_rank"] or 999))
        for i, r in enumerate(rows):
            r["conf_rank"] = i + 1
    return dict(out)


def team_stats(level: str, st: dict, tab: dict) -> dict[str, dict]:
    """Season team shooting and four-factor style stats from box scores (else the scoreboard line)."""
    acc = defaultdict(lambda: defaultdict(float))
    for g in (st.get("games") or {}).values():
        if g.get("status") != "post" or g.get("stype") not in D.COUNTED:
            continue
        b = g.get("box") or {}
        if len(b) == 2 and not D.box_ok(g, rel=0.1):
            b = {}                                     # partial box (older women's games): the scoreboard line
        ts = g.get("team_stats") or {}
        sides = list(b) if len(b) == 2 else (list(ts) if len(ts) == 2 else [])
        if len(sides) != 2:
            continue
        for t in sides:
            o = sides[1] if t == sides[0] else sides[0]
            if len(b) == 2:
                me, op = b[t].get("team") or {}, b[o].get("team") or {}
                a = acc[t]
                a["box"] += 1
                for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "oreb", "dreb", "ast", "tov", "stl", "blk"):
                    a[k] += float(me.get(k) or 0)
                    a["o_" + k] += float(op.get(k) or 0)
            else:
                me, op = ts.get(t) or {}, ts.get(o) or {}
                if "fga" not in me or "fga" not in op:
                    continue
                a = acc[t]
                a["sb"] += 1
                for k in ("fgm", "fga", "tpm", "tpa", "ftm", "fta", "ast"):
                    a[k] += float(me.get(k) or 0)
                    a["o_" + k] += float(op.get(k) or 0)
    out = {}
    for t, a in acc.items():
        if a["fga"] <= 0:
            continue
        d = {"efg": (a["fgm"] + 0.5 * a["tpm"]) / a["fga"], "opp_efg": (a["o_fgm"] + 0.5 * a["o_tpm"]) / max(a["o_fga"], 1),
             "ftr": a["fta"] / a["fga"], "tpar": a["tpa"] / a["fga"], "tp_pct": a["tpm"] / max(a["tpa"], 1),
             "ft_pct": a["ftm"] / max(a["fta"], 1), "ast_rate": a["ast"] / max(a["fgm"], 1), "opp_ftr": a["o_fta"] / max(a["o_fga"], 1)}
        if a["box"] >= 5 and a["box"] >= a["sb"]:
            poss = a["fga"] - a["oreb"] + a["tov"] + 0.475 * a["fta"]
            d["tov_rate"] = a["tov"] / max(poss, 1)
            d["orb_rate"] = a["oreb"] / max(a["oreb"] + a["o_dreb"], 1)
            d["drb_rate"] = a["dreb"] / max(a["dreb"] + a["o_oreb"], 1)
            opp_poss = a["o_fga"] - a["o_oreb"] + a["o_tov"] + 0.475 * a["o_fta"]
            d["opp_tov_rate"] = a["o_tov"] / max(opp_poss, 1)
            d["stl_rate"] = a["stl"] / max(opp_poss, 1)
            d["blk_rate"] = a["blk"] / max(a["o_fga"] - a["o_tpa"], 1)
        out[t] = d
    return out


# ── sim ─────────────────────────────────────────────────────────────────────

def phase(level: str, s: int, st: dict) -> str:
    cur = current_season(level)
    if s < cur:
        return "offseason"
    gs = list((st.get("games") or {}).values())
    if not any(g.get("status") in ("post", "in") for g in gs if g.get("stype") in D.COUNTED):
        return "preseason"
    if any(g.get("stype") == "ncaa" and g.get("status") in ("post", "in") for g in gs):
        done = all(g.get("status") == "post" for g in gs if g.get("stype") == "ncaa")
        return "offseason" if done and sum(1 for g in gs if g.get("stype") == "ncaa") >= 60 else "ncaa"
    if any(g.get("stype") == "conf" and g.get("status") in ("post", "in") and (g.get("date") or "")[5:7] == "03" for g in gs):
        return "conf_tourneys"
    return "regular"


def season_sim(ctx: dict, s: int, sims: int) -> dict | None:
    """{"kind": "full"|"bracket"|"projected", "teams": {tid: SIMTEAM}, ...} cached in the bundle."""
    b = bundle(ctx, s)
    if "sim" in b:
        return b["sim"]
    lv = ctx["level"]
    tab = b["tab"]
    teams = tab["teams"]
    pre = ctx["pre"].get(s)
    st = b["st"]
    out = None
    complete = False
    if pre:
        regs_chk, _ = N.actual_regions(pre["af"], tab["idx"])
        complete = len(regs_chk) == 4 and all(len(r) >= 14 for r in regs_chk)
    if pre and complete:
        res = SM.bracket_from_actual(ctx["state"], s, pre, n=max(2000, sims))
        reach = res["reach"]
        af = pre["af"]
        tm = {}
        crec = TT.conf_records(st)
        champs = TT.conf_champions(st, af["first_day"])
        reg_champ = _reg_champs(st, b["standings"])
        for i, t in enumerate(teams):
            if not tab["member"][i]:
                continue
            a = af["teams"].get(t)
            stand = _row_of(b["standings"], t) or {}
            c = (st.get("teams") or {}).get(t, {}).get("conference")
            sd = a.get("seed") if a else None
            tm[t] = {"exp_w": stand.get("w"), "exp_l": stand.get("l"), "exp_conf_w": stand.get("conf_w"),
                     "exp_conf_l": stand.get("conf_l"), "p_conf_reg": 1.0 if reg_champ.get(c) == t else 0.0,
                     "p_conf_tourney": 1.0 if champs.get(c) == t else 0.0, "p_ncaa": 1.0 if a else 0.0,
                     "p_auto": 1.0 if a and a.get("auto") else 0.0, "p_at_large": 1.0 if a and not a.get("auto") else 0.0,
                     "seed_mean": sd, "seed_dist": {str(sd): 1.0} if sd else {},
                     "p_round": {k: r4(reach[i, j + 1]) for j, k in enumerate(["r32", "s16", "e8", "f4", "final", "title"])} if a else None,
                     "p_title": r4(reach[i, 6]) if a else 0.0}
        out = {"kind": "bracket", "teams": tm, "reach": reach, "seeds_of": res["seeds_of"], "regs": res["regs"],
               "n": max(2000, sims), "notes": ["Finished season: the NCAA tournament chances are pre-tournament (ratings fitted on "
                                                "games before the First Four), simulated on the actual bracket; records and "
                                                "bids are actual."]}
    elif ctx["sel_all"] is not None and (s == current_season(lv) or s == 2020):
        f = b["fit"]
        as_of = None
        res = SM.simulate(ctx["state"], s, f, n=sims, sel_model=ctx["sel_all"], as_of_day=as_of)
        tm = {}
        for i, t in enumerate(teams):
            if not tab["member"][i]:
                continue
            sd = res["seed_dist"][i]
            tm[t] = {"exp_w": r1(res["exp_w"][i]), "exp_l": r1(res["exp_l"][i]), "exp_conf_w": r1(res["exp_cw"][i]),
                     "exp_conf_l": r1(res["exp_cl"][i]), "p_conf_reg": r4(res["p_conf_reg"][i]), "p_conf_tourney": r4(res["p_conf_t"][i]),
                     "p_ncaa": r4(res["p_ncaa"][i]), "p_auto": r4(res["p_auto"][i]), "p_at_large": r4(res["p_at_large"][i]),
                     "seed_mean": r2(res["seed_mean"][i]),
                     "seed_dist": {str(k): r4(sd[k]) for k in range(1, 17) if sd[k] >= 0.0005},
                     "p_round": {k: r4(res["reach"][i, j + 1]) for j, k in enumerate(["r32", "s16", "e8", "f4", "final", "title"])},
                     "p_title": r4(res["reach"][i, 6])}
            if "n_rem" in res:
                tm[t]["n_rem"] = int(res["n_rem"][i])
                tm[t]["sos_rem"] = r2(res["sos_rem"][i]) if np.isfinite(res["sos_rem"][i]) else None
        notes = ["Season simulation from today's ratings (preseason: the prior from last season's ratings, regressed).",
                 "Conference tournaments are generic and approximate: every member, single elimination, seeded by the simulated "
                 "standings, neutral floors (actual formats are not in a free feed).",
                 "Selection and seeding by our proxy (fitted on past fields); conference-separation and geography rules are not "
                 "modelled."]
        if s == 2020:
            notes.insert(0, "2020: no NCAA tournament was played (COVID-19); the field and chances are hypothetical.")
        out = {"kind": "full" if s != 2020 else "projected", "teams": tm, "res": res, "n": sims, "notes": notes}
    b["sim"] = out
    return out


def _row_of(stand: dict, t: str) -> dict | None:
    for rows in stand.values():
        for r in rows:
            if r["team"] == t:
                return r
    return None


def _reg_champs(st: dict, stand: dict) -> dict[str, str]:
    out = {}
    for c, rows in stand.items():
        if rows and (rows[0]["conf_w"] + rows[0]["conf_l"]) > 0:
            out[c] = rows[0]["team"]
    return out


# ── payload builders ────────────────────────────────────────────────────────

def season_payload(ctx: dict, s: int, sims: int) -> dict:
    lv = ctx["level"]
    b = bundle(ctx, s)
    st, tab = b["st"], b["tab"]
    confs = {}
    for c, v in (st.get("conferences") or {}).items():
        ts = [t for t, x in (st.get("teams") or {}).items() if x.get("member") and x.get("conference") == c]
        if ts:
            confs[c] = {"name": v.get("name"), "short": v.get("short"), "teams": sorted(ts)}
    used = set()
    for g in (st.get("games") or {}).values():
        used.add(str(g.get("home")))
        used.add(str(g.get("away")))
    teams = {t: team_rec(st, t) for t, v in (st.get("teams") or {}).items() if v.get("member") or t in used}
    rk = b["rank"]
    prev = {}
    sr = b["snap_rank"]
    if len(sr) >= 2:
        prev_rk = sr[-2][1] if s == current_season(lv) else sr[-1][1]
        prev = {t: int(prev_rk[i]) for i, t in enumerate(tab["teams"]) if tab["member"][i]}
    power = sorted(({"rank": v["rank"], "team": t, "rating": v["rating"], "prev_rank": prev.get(t)} for t, v in b["ratings"].items()),
                   key=lambda r: r["rank"])
    sim = season_sim(ctx, s, sims)
    fmt = TT.field_format(lv, s)
    pr = player_rows(ctx, s)["rows"]
    leaders = {}
    if pr:
        gmax = max(x["gp"] for x in pr.values())
        qual = [r for r in pr.values() if r["gp"] >= max(5, 0.4 * gmax)]
        for k, f_ in (("pts", lambda r: r["tot"]["pts"] / r["gp"]), ("reb", lambda r: (r["tot"]["oreb"] + r["tot"]["dreb"]) / r["gp"]),
                      ("ast", lambda r: r["tot"]["ast"] / r["gp"]), ("stl", lambda r: r["tot"]["stl"] / r["gp"]),
                      ("blk", lambda r: r["tot"]["blk"] / r["gp"]), ("value", lambda r: r["value"]),
                      ("value_pg", lambda r: r["value_pg"])):
            top = sorted(qual, key=lambda r: -f_(r))[:10]
            leaders[k] = [[r["id"], r["team"], r1(f_(r))] for r in top]
    return {"ok": True, "level": lv, "season": s, "updated_at": now_iso(), "phase": phase(lv, s, st), "week": None,
            "format": {"ncaa": {"field": fmt["field"], "at_large": None if not ctx["pre"].get(s) else ctx["pre"][s]["af"]["n_at_large"],
                                "first_four": fmt["first_four"], "verified": s < current_season(lv) or s <= 2026}},
            "conferences": confs, "teams": teams, "standings": b["standings"], "ratings": b["ratings"],
            "rating_paths": b["paths"], "polls": polls_payload(st), "power": power,
            "sim": {"n_sims": sim["n"], "teams": sim["teams"], "notes": sim["notes"]} if sim else None,
            "leaders": leaders, "fmt": FORMAT, "model": {"hca_pts": r2(b["fit"]["hca_pts"]), "league_ortg": r2(b["fit"]["L"]),
                                          "league_pace": r2(b["fit"]["league_pace"]), "games": int(b["fit"]["n"])}}


def schedule_payload(ctx: dict, s: int) -> dict:
    b = bundle(ctx, s)
    st = b["st"]
    teams = st.get("teams") or {}
    cards = []
    for g in sorted((st.get("games") or {}).values(), key=lambda g: (g.get("date") or "", str(g["id"]))):
        if not ((teams.get(str(g.get("home"))) or {}).get("member") or (teams.get(str(g.get("away"))) or {}).get("member")):
            continue
        cards.append(slim(card(ctx, s, g), compact=archive(ctx, s)))
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(), "games": PK.pack(cards),
            "compact": archive(ctx, s)}


def _regions_payload(regs: list[dict], names: list[str], teams: list[str], p_of: dict | None = None) -> dict:
    out = {}
    for k, reg in enumerate(regs):
        rows = []
        for sd in sorted(reg):
            for t in reg[sd]:
                row = {"seed": int(sd), "team": teams[t]}
                if p_of is not None:
                    row["p"] = r4(p_of.get(teams[t]))
                rows.append(row)
        out[names[k] if k < len(names) else f"Region {k + 1}"] = rows
    return out


_SITE_PATTERNS = (re.compile(r"regional\s+(\d)\s+in\s+([A-Za-z .'-]+?)\s*(?:-|$)", re.IGNORECASE),        # 2024-: Regional 1 in Albany
                  re.compile(r"-\s*([A-Za-z .'-]+?)\s+regional\s+(\d)\b", re.IGNORECASE))                  # 2023: Greenville Regional 1


def region_sites(ncaa: list[dict], names: list[str]) -> dict[str, str]:
    """{region: host city} for the bracket's region headings. Numbered women's regions (2023 on) take the city from
    ESPN's headline ("Regional 1 in Albany", "Greenville Regional 1"); a region already named for its host city
    (women 2005-2022, when the NCAA named regionals that way, after canon.ncaa_regions has moved first-weekend sites
    to their regional) is its own site; compass regions (East, Midwest, ...) have none."""
    out: dict[str, str] = {}
    for g in ncaa:
        reg, note = g.get("region"), str(g.get("note") or "")
        if not reg or reg in out or g.get("round") not in ("Sweet 16", "Elite 8"):
            continue
        for k, pat in enumerate(_SITE_PATTERNS):
            m = pat.search(note)
            if m:
                num, city = (m.group(1), m.group(2)) if k == 0 else (m.group(2), m.group(1))
                if reg == f"Regional {num}":
                    out[reg] = city.strip().title()
                break
    compass = {"East", "West", "South", "Midwest", "Mideast", "Southeast", "Southwest"}
    for n in names:
        if n not in out and n not in compass and not re.match(r"^Regional \d$", str(n)):
            out[n] = n
    return out


def bracket_payload(ctx: dict, s: int, sims: int) -> dict:
    lv = ctx["level"]
    b = bundle(ctx, s)
    st, tab = b["st"], b["tab"]
    teams = tab["teams"]
    sim = season_sim(ctx, s, sims)
    pre = ctx["pre"].get(s)
    fmt = TT.field_format(lv, s)
    sf = ctx["loso"]
    base = {"ok": True, "season": s, "updated_at": now_iso(), "field": fmt["field"],
            "format": {"field": fmt["field"], "first_four": fmt["first_four"], "verified": fmt["verified"],
                       "conf_tourneys": "generic single elimination (approximate)"},
            "rounds": TT.ROUND_KEYS,
            "selection_fit": {"n_seasons": sf["n_seasons"], "at_large_acc": sf["at_large_acc"], "seed_mae": sf["seed_mae"],
                              "seed_exact": sf["seed_exact"], "seed_within1": sf["seed_within1"], "features": sf["features"]} if sf else None}
    if pre and sim and sim["kind"] == "bracket":
        af = pre["af"]
        regs = sim["regs"]
        ncaa = sorted((g for g in (st.get("games") or {}).values() if g.get("stype") == "ncaa"), key=lambda g: g.get("date") or "")
        actual = {"regions": _regions_payload(regs, af["regions"], teams), "games": [slim(card(ctx, s, g)) for g in ncaa],
                  "first_four": af["first_four"], "champion": af["champion"], "sites": region_sites(ncaa, af["regions"])}
        reach = sim["reach"]
        odds = {}
        for t, v in af["teams"].items():
            i = tab["idx"].get(t)
            if i is None:
                continue
            odds[t] = {"p_round": {k: r4(reach[i, j]) for j, k in enumerate(TT.ROUND_KEYS)}, "seed": v.get("seed"),
                       "region": v.get("region"), "reached": v.get("reached")}
        # proxy as of Selection Sunday, fitted on the other seasons
        proj, bo = None, []
        r_ = ctx["sel_rows"].get(s)
        if r_ is not None:
            model = N.fit_on(ctx["sel_rows"], [q for q in ctx["sel_rows"] if q != s])
            pr = N.predict_season(model, r_)
            bo, proj = _bracketology(ctx, s, r_, pr, af)
        ups = []
        for g in ncaa:
            if g.get("round") != "Round of 64" or g.get("status") != "post":
                continue
            sd = g.get("seeds") or {}
            if not sd.get("home") or not sd.get("away") or sd["home"] == sd["away"]:
                continue
            fav, dog = (("home", "away") if sd["home"] < sd["away"] else ("away", "home"))
            i, j = tab["idx"].get(str(g[fav])), tab["idx"].get(str(g[dog]))
            if i is None or j is None:
                continue
            f = pre["fit"]
            pace = f["tempo"][i] + f["tempo"][j] - f["league_pace"]
            pfav = float(norm.cdf(b["prm"]["s"] * (f["net"][i] - f["net"][j]) * pace / 100 / b["prm"]["s0"]))
            mk = game_market(lv, g)
            mp = None
            if mk and mk.get("p_home") is not None:
                mp = 1 - mk["p_home"] if fav == "home" else mk["p_home"]
            won = (g["hs"] > g["as"]) == (fav == "home")
            ups.append({"round": "R64", "fav": str(g[fav]), "dog": str(g[dog]), "seed_fav": sd[fav], "seed_dog": sd[dog],
                        "p_upset": r4(1 - pfav), "market_p": r4(mp), "upset": not won, "gid": str(g["id"])})
        ups.sort(key=lambda u: -(u["p_upset"] or 0))
        return {**base, "actual": actual, "bracketology": bo, "projected": proj, "odds": odds, "upsets": ups,
                "conf_tourneys": conf_tourneys_actual(ctx, s, b)}
    if sim and sim["kind"] in ("full", "projected"):
        res = sim["res"]
        mem_idx = np.where(tab["member"])[0]
        p_ncaa = res["p_ncaa"]
        conf_of = tab["conf"]
        bo = []
        for i in mem_idx[np.argsort(-p_ncaa[mem_idx])][:80]:
            sd = res["seed_dist"][i]
            stand = _row_of(b["standings"], teams[i]) or {}
            bo.append({"team": teams[i], "seed_mean": r2(res["seed_mean"][i]), "seed_mode": int(np.argmax(sd[1:]) + 1) if sd[1:].sum() > 0 else None,
                       "p_ncaa": r4(p_ncaa[i]), "p_auto": r4(res["p_auto"][i]), "p_at_large": r4(res["p_at_large"][i]),
                       "conf": conf_of[i], "record": f"{stand.get('w', 0)}-{stand.get('l', 0)}" if stand else None,
                       "exp_record": f"{res['exp_w'][i]:.1f}-{res['exp_l'][i]:.1f}", "rating_rank": int(b["rank"][i])})
        proj = _projected_field(ctx, s, b, res)
        odds = {}
        for i in mem_idx:
            if res["p_ncaa"][i] < 0.001:
                continue
            odds[teams[i]] = {"p_round": {k: r4(res["reach"][i, j]) for j, k in enumerate(TT.ROUND_KEYS)},
                              "seed": proj["seed_of"].get(teams[i]), "region": proj["region_of"].get(teams[i]),
                              "p_ncaa": r4(res["p_ncaa"][i])}
        ups = _projected_upsets(ctx, s, b, proj)
        ct = {}
        for c, members in sorted(res["groups"].items()):
            pw = res["conf_win"].get(c)
            if pw is None:
                continue
            rows_ = sorted(({"team": teams[i], "seed": None, "p_win": r4(pw[i]), "p_reg": r4(res["p_conf_reg"][i])} for i in members),
                           key=lambda r: -(r["p_win"] or 0))
            for k, r in enumerate(sorted(rows_, key=lambda r: -(r["p_reg"] or 0))):
                r["seed"] = k + 1
            gms = [slim(card(ctx, s, g)) for g in (st.get("games") or {}).values() if g.get("stype") == "conf" and
                   (st.get("teams") or {}).get(str(g.get("home")), {}).get("conference") == c and (g.get("date") or "")[5:7] in ("02", "03")]
            ct[c] = {"teams": rows_, "approximate": True, "games": sorted(gms, key=lambda x: x["date"] or "")}
        return {**base, "actual": None, "bracketology": bo,
                "projected": {"regions": proj["regions"], "first_four": proj["first_four"], "last_in": proj["last_in"],
                              "first_out": proj["first_out"]},
                "odds": odds, "upsets": ups, "conf_tourneys": ct, "notes": sim["notes"]}
    return {**base, "actual": None, "bracketology": [], "projected": None, "odds": {}, "upsets": [], "conf_tourneys": {},
            "notes": ["No NCAA tournament data for this season."]}


def _bracketology(ctx, s, r_, pr, af) -> tuple[list, dict]:
    tab = ctx["state"]["tabs"][s]
    teams = tab["teams"]
    idx = r_["idx"]
    sel = pr["sel"]
    p_at = 1 / (1 + np.exp(-sel))
    fld = pr["field"]
    seed_of = {int(t): sd for t, sd in fld["seed"].items()}
    rows = []
    order = np.argsort(-np.where(r_["auto"], 99.0, sel))[:80]
    b = bundle(ctx, s)
    for k in order:
        t = teams[idx[k]]
        stand = _row_of(b["standings"], t) or {}
        rows.append({"team": t, "seed_mean": seed_of.get(int(k)), "seed_mode": seed_of.get(int(k)),
                     "p_ncaa": 1.0 if r_["auto"][k] else r4(p_at[k]), "p_auto": 1.0 if r_["auto"][k] else 0.0,
                     "p_at_large": 0.0 if r_["auto"][k] else r4(p_at[k]), "conf": tab["conf"][idx[k]],
                     "record": f"{stand.get('w', 0)}-{stand.get('l', 0)}", "rating_rank": int(b["rank"][idx[k]]),
                     "actual_seed": (af["teams"].get(t) or {}).get("seed"), "in_field": t in af["teams"]})
    regs = TT.regions_from_entries([[int(idx[x]) for x in e] for e in fld["entries"]])
    proj = {"regions": _regions_payload(regs, REGION_NAMES[ctx["level"]], teams),
            "first_four": [[teams[idx[a]], teams[idx[b_]]] for a, b_ in fld["ff_pairs"]],
            "last_in": [teams[idx[x]] for x in fld["last_in"]], "first_out": [teams[idx[x]] for x in fld["first_out"]],
            "note": "Our selection and seeding proxy as of Selection Sunday, fitted on the other seasons (leave-one-season-out)."}
    return rows, proj


def _projected_field(ctx, s, b, res) -> dict:
    """The modal projection from the sim: autos = each conference's likeliest champion, at-large = the highest
    at-large probabilities, ordered by mean seed; S-curve regions."""
    tab = b["tab"]
    teams = tab["teams"]
    lv = ctx["level"]
    fmt = TT.field_format(lv, s)
    mem_idx = np.where(tab["member"])[0]
    autos = set()
    for c, members in res["groups"].items():
        pw = res["conf_win"].get(c)
        if pw is not None:
            autos.add(int(members[int(np.argmax(pw[members]))]))
    au = np.array([i in autos for i in mem_idx])
    sel = np.log(np.maximum(res["p_at_large"][mem_idx], 1e-6) / np.maximum(1 - res["p_at_large"][mem_idx], 1e-6))
    sm = np.where(np.isfinite(res["seed_mean"][mem_idx]), res["seed_mean"][mem_idx], 30.0)
    fld = TT.build_field(mem_idx, au, sel, sm, fmt["field"], fmt["first_four"])
    regs = TT.regions_from_entries(fld["entries"])
    names = REGION_NAMES[lv]
    p_of = {teams[i]: float(res["p_ncaa"][i]) for i in mem_idx}
    seed_of, region_of = {}, {}
    for k, reg in enumerate(regs):
        for sd, e in reg.items():
            for t in e:
                seed_of[teams[t]] = int(sd)
                region_of[teams[t]] = names[k]
    return {"regions": _regions_payload(regs, names, teams, p_of), "first_four": [[teams[a], teams[b_]] for a, b_ in fld["ff_pairs"]],
            "last_in": [teams[x] for x in fld["last_in"]], "first_out": [teams[x] for x in fld["first_out"]],
            "seed_of": seed_of, "region_of": region_of, "regs": regs}


def _projected_upsets(ctx, s, b, proj) -> list[dict]:
    f, prm, tab = b["fit"], b["prm"], b["tab"]
    out = []
    for reg in proj["regs"]:
        for hi_seed in range(1, 9):
            lo_seed = 17 - hi_seed
            a, c = reg.get(hi_seed), reg.get(lo_seed)
            if not a or not c or len(a) != 1:
                continue
            i = a[0]
            ps = []
            for j in c:
                pace = f["tempo"][i] + f["tempo"][j] - f["league_pace"]
                ps.append(float(norm.cdf(prm["s"] * (f["net"][i] - f["net"][j]) * pace / 100 / math.sqrt(prm["s0"] ** 2 + prm["s1"] * (f["se"][i] ** 2 + f["se"][j] ** 2) * (pace / 100) ** 2))))
            out.append({"round": "R64", "fav": tab["teams"][i], "dog": tab["teams"][c[0]] if len(c) == 1 else None,
                        "dogs": [tab["teams"][j] for j in c], "seed_fav": hi_seed, "seed_dog": lo_seed,
                        "p_upset": r4(1 - float(np.mean(ps))), "market_p": None})
    out.sort(key=lambda u: -(u["p_upset"] or 0))
    return out


def conf_tourneys_actual(ctx, s, b) -> dict:
    st = b["st"]
    teams = st.get("teams") or {}
    out = {}
    pre = ctx["pre"].get(s)
    before = pre["af"]["first_day"] if pre else f"{s}-03-25"
    champs = TT.conf_champions(st, before)
    gms = defaultdict(list)
    for g in (st.get("games") or {}).values():
        if g.get("stype") != "conf" or (g.get("date") or "")[5:7] not in ("02", "03"):
            continue
        c = (teams.get(str(g.get("home"))) or {}).get("conference")
        if c and c == (teams.get(str(g.get("away"))) or {}).get("conference"):
            gms[c].append(g)
    for c, rows in b["standings"].items():
        if c == "none":
            continue
        ch = champs.get(c) if gms.get(c) else None
        out[c] = {"teams": [{"team": r["team"], "seed": r["conf_rank"], "p_win": 1.0 if r["team"] == ch else 0.0} for r in rows],
                  "approximate": False, "champion": ch,
                  "games": [slim(card(ctx, s, g)) for g in sorted(gms.get(c, []), key=lambda g: g.get("date") or "")]}
    return out


# ── teams ───────────────────────────────────────────────────────────────────

TEAM_METRICS = [("rating", "Rating", "Ratings", "signed2", False, "Adjusted efficiency margin per 100 possessions v an average D-I team"),
                ("off", "Offense", "Ratings", "1", False, "Adjusted points scored per 100 possessions"),
                ("def", "Defense", "Ratings", "1", True, "Adjusted points allowed per 100 possessions"),
                ("tempo", "Tempo", "Ratings", "1", False, "Adjusted possessions per 40 minutes"),
                ("sos", "SOS", "Ratings", "signed2", False, "Mean rating of opponents played"),
                ("luck", "Luck", "Ratings", "signed2", False, "Wins above expectation per game (actual - model)"),
                ("wpct", "Win %", "Record", "3", False, "Winning percentage"),
                ("efg", "eFG%", "Shooting", "3", False, "Effective field-goal percentage"),
                ("opp_efg", "Opp eFG%", "Defense", "3", True, "Opponents' effective field-goal percentage"),
                ("tpar", "3PA rate", "Shooting", "3", False, "Three-point attempts per field-goal attempt"),
                ("tp_pct", "3P%", "Shooting", "3", False, "Three-point percentage"),
                ("ft_pct", "FT%", "Shooting", "3", False, "Free-throw percentage"),
                ("ftr", "FT rate", "Shooting", "3", False, "Free-throw attempts per field-goal attempt"),
                ("ast_rate", "Assist rate", "Ball", "3", False, "Assists per made field goal"),
                ("tov_rate", "TO rate", "Ball", "3", True, "Turnovers per possession (box scores)"),
                ("orb_rate", "OReb%", "Rebounding", "3", False, "Offensive rebound percentage (box scores)"),
                ("drb_rate", "DReb%", "Rebounding", "3", False, "Defensive rebound percentage (box scores)"),
                ("opp_tov_rate", "Forced TO rate", "Defense", "3", False, "Opponent turnovers per possession (box scores)"),
                ("blk_rate", "Block rate", "Defense", "3", False, "Blocks per opponent two-point attempt (box scores)"),
                # already in `values`; listed so the catalogue labels them (the defensive four factors: metrics spec)
                ("opp_ftr", "Opp FT rate", "Defense", "3", True, "Opponents' free-throw attempts per field-goal attempt"),
                ("stl_rate", "Steal rate", "Defense", "3", False, "Steals per opponent possession (box scores)")]


def _metric(k, label, group, fmt, lower, desc):
    return {"key": k, "label": label, "group": group, "fmt": fmt, "lower": lower, "desc": desc}


def team_values(ctx, s) -> dict[str, dict]:
    b = bundle(ctx, s)
    out = {}
    for t, rt in b["ratings"].items():
        stand = _row_of(b["standings"], t) or {}
        v = {"rating": rt["rating"], "off": rt["off"], "def": rt["def"], "tempo": rt["tempo"], "sos": rt["sos"], "luck": rt["luck"],
             "wpct": (stand.get("w", 0) / max(stand.get("w", 0) + stand.get("l", 0), 1)) if stand else None}
        for k, x in (b["team_stats"].get(t) or {}).items():
            v[k] = x
        out[t] = v
    return out


def _pcts(vals: dict[str, dict], keys: list[tuple]) -> dict[str, dict]:
    out = defaultdict(dict)
    for k, *_rest in keys:
        lower = _rest[3]
        xs = {t: v.get(k) for t, v in vals.items() if v.get(k) is not None}
        if len(xs) < 10:
            continue
        arr = np.array(sorted(xs.values()))
        n = len(arr)
        for t, x in xs.items():
            p = 100.0 * np.searchsorted(arr, x, side="right") / n
            out[t][k] = round(100.0 - p + 100.0 / n if lower else p, 1)
    return out


def teams_payload(ctx, s) -> dict:
    b = bundle(ctx, s)
    st = b["st"]
    vals = team_values(ctx, s)
    pct = _pcts(vals, TEAM_METRICS)
    out = {}
    for t, v in vals.items():
        stand = _row_of(b["standings"], t) or {}
        out[t] = {"name": (st.get("teams") or {}).get(t, {}).get("short"), "conference": (st.get("teams") or {}).get(t, {}).get("conference"),
                  "w": stand.get("w"), "l": stand.get("l"), "rating_rank": b["ratings"][t]["rank"],
                  "values": {k: (r3(x) if isinstance(x, float) else x) for k, x in v.items()}, "pct": pct.get(t, {})}
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(),
            "metrics": [_metric(*m) for m in TEAM_METRICS], "teams": out}


def roster_rows(ctx, s) -> tuple[dict, dict, str]:
    """(rows by pid for the season's player value, team map, basis): this season's box scores, else last season's
    values for players on this season's rosters (preseason)."""
    pr = player_rows(ctx, s)
    if pr["rows"]:
        return pr["rows"], {p: r["team"] for p, r in pr["rows"].items()}, "season"
    prev = player_rows(ctx, s - 1)["rows"] if (s - 1) in ctx["state"]["tabs"] else {}
    st = D.load(ctx["level"], s)
    tm = PL.current_team_map(st, None)
    rows = {}
    for p, t in tm.items():
        r = prev.get(p)
        if r:
            rows[p] = {**r, "team": t, "prev_team": r["team"]}
    return rows, tm, "last_season"


def team_pages(ctx, s, sdir: Path, sims: int) -> int:
    lv = ctx["level"]
    b = bundle(ctx, s)
    st, tab = b["st"], b["tab"]
    sim = season_sim(ctx, s, sims)
    rows, tmap, basis = roster_rows(ctx, s)
    by_team = defaultdict(list)
    for r in rows.values():
        by_team[r["team"]].append(r)
    unit_map = PL.units(lv, rows, {t: {**(b["team_stats"].get(t) or {}), "off": (b["ratings"].get(t) or {}).get("off"),
                                       "def": (b["ratings"].get(t) or {}).get("def")} for t in b["ratings"]})
    moves = moves_list(ctx, s)
    mv_in, mv_out = defaultdict(list), defaultdict(list)
    for m in moves:
        mv_in[m["to"]].append(m)
        mv_out[m["from"]].append(m)
    vals = team_values(ctx, s)
    pct = _pcts(vals, TEAM_METRICS)
    ranks = {}
    for k, *_r in TEAM_METRICS:
        lower = _r[3]
        xs = sorted((v.get(k), t) for t, v in vals.items() if v.get(k) is not None)
        if lower:
            ordered = [t for _, t in xs]
        else:
            ordered = [t for _, t in xs[::-1]]
        ranks[k] = {t: i + 1 for i, t in enumerate(ordered)}
    games = sorted((g for g in (st.get("games") or {}).values() if g.get("stype") in D.COUNTED or g.get("status") == "pre"),
                   key=lambda g: g.get("date") or "")
    by_t_games = defaultdict(list)
    for g in games:
        by_t_games[str(g.get("home"))].append(g)
        by_t_games[str(g.get("away"))].append(g)
    ap_weeks = (st.get("rankings") or {}).get("ap") or {}
    n = 0
    tdir = sdir / "teams"
    for t, rt in b["ratings"].items():
        try:
            i = tab["idx"][t]
            rh = []
            num = sorted((k for k in ap_weeks if str(k).isdigit()), key=int)
            for k, (d, rk2) in enumerate(b["snap_rank"]):
                wk = str(k + 1)
                apr = None
                if wk in ap_weeks:
                    apr = next((x[0] for x in ap_weeks[wk] if str(x[1]) == t), None)
                rh.append([k + 1, apr, int(rk2[i])])
            us = unit_map.get(t, [])
            pos_units = [u for u in us]
            # top and bottom units without overlap (preseason has only the G/F/C and offense/defense units)
            ns = min(3, len(pos_units) // 2)
            strengths = sorted(pos_units, key=lambda u: -u["pctl"])[:ns]
            sk = {u["key"] for u in strengths}
            needs = sorted((u for u in pos_units if u["key"] not in sk), key=lambda u: u["pctl"])[:3]
            roster = []
            for r in sorted(by_team.get(t, []), key=lambda r: -r["min"])[:12 if archive(ctx, s) else 99]:
                pg = PL.per_game_line(r)
                row = {"id": r["id"], "name": r["name"], "pos": r["pos"], "class": r.get("class"), "gp": r["gp"],
                       "value": r2(r["value"]), "value_pg": r2(r["value_pg"]), "min": pg["min"], "pts": pg["pts"],
                       "reb": pg["reb"], "ast": pg["ast"], "r": r2(r["r"]),
                       "basis": basis, "prev_team": r.get("prev_team")}
                roster.append({k: v for k, v in row.items() if v is not None})
            if basis == "last_season":
                for p, tt in tmap.items():
                    if tt == t and p not in rows:
                        pi = (st.get("players") or {}).get(p) or {}
                        roster.append({"id": p, "name": pi.get("name"), "pos": PL.position(lv, pi), "class": pi.get("class"),
                                       "gp": 0, "value": None, "value_pg": None, "basis": "new"})
            # suggestions only where they can still matter (current and previous season): size budget
            sugg = [] if archive(ctx, s) else PL.suggestions(t, [u for u in needs], rows, by_team.get(t, []))
            stats = {}
            for k, *_r in TEAM_METRICS:
                v = vals.get(t, {}).get(k)
                if v is not None:
                    stats[k] = {"v": r3(v), "pct": pct.get(t, {}).get(k), "rank": ranks[k].get(t)}
            stand = _row_of(b["standings"], t) or {}
            page = {"ok": True, "id": t, "level": lv, "season": s, "team": team_rec(st, t),
                    "record": {k: stand.get(k) for k in ("w", "l", "conf_w", "conf_l", "home", "away", "neutral", "streak", "pf", "pa", "conf_rank")},
                    "rating": rt, "rating_path": b["paths"].get(t, []), "rank_history": rh,
                    "schedule": None if archive(ctx, s) else PK.pack(slim(card(ctx, s, g)) for g in by_t_games.get(t, [])),
                    "stats": stats, "roster": PK.pack(roster),
                    "roster_basis": basis, "units": us, "strengths": strengths, "needs": needs,
                    "moves": {"in": mv_in.get(t, []), "out": mv_out.get(t, [])},
                    "odds": (sim or {}).get("teams", {}).get(t) if sim else None, "suggestions": sugg,
                    "suggestions_note": "Model suggestions based on on-field box-score value only; not considering eligibility, "
                                        "the transfer portal's actual entries, NIL, fit or availability."}
            if archive(ctx, s):
                page.pop("rating_path")                # the page falls back to season.json rating_paths (size budget)
                page.pop("schedule")                   # and to schedule.json for the team's games
            write(tdir / f"{t}.json", page)
            n += 1
        except Exception as exc:  # noqa: BLE001
            write(tdir / f"{t}.json", fail(f"team page failed: {exc}"))
    return n


# ── players ─────────────────────────────────────────────────────────────────

PLAYER_METRICS = [("value", "Value", "Value", "1", False, "Points above replacement over the season (team-constrained box value)"),
                  ("value_pg", "Value / game", "Value", "2", False, "Points above replacement per game"),
                  ("r", "Rating /100", "Value", "signed1", False, "Box rating: points per 100 possessions above an average D-I player"),
                  ("min", "MIN", "Box", "1", False, "Minutes per game"), ("pts", "PTS", "Box", "1", False, "Points per game"),
                  ("reb", "REB", "Box", "1", False, "Rebounds per game"), ("ast", "AST", "Box", "1", False, "Assists per game"),
                  ("stl", "STL", "Box", "1", False, "Steals per game"), ("blk", "BLK", "Box", "1", False, "Blocks per game"),
                  ("tov", "TOV", "Box", "1", True, "Turnovers per game"), ("fg_pct", "FG%", "Shooting", "3", False, "Field-goal percentage"),
                  ("tp_pct", "3P%", "Shooting", "3", False, "Three-point percentage"), ("ft_pct", "FT%", "Shooting", "3", False, "Free-throw percentage"),
                  ("ts", "TS%", "Shooting", "3", False, "True shooting: PTS / (2 (FGA + 0.475 FTA))"),
                  ("usg", "USG%", "Usage", "1", False, "Share of team possessions used on the floor"),
                  ("ortg", "Pts/100 used", "Usage", "1", False, "Points per 100 possessions used (FGA + 0.475 FTA + TOV)"),
                  # rates (docs/_design/metrics/college.json): per 100 possessions on the floor, shares as 0-1 fractions
                  ("pts100", "PTS/100", "Rates", "1", False, "Points per 100 team possessions on the floor"),
                  ("ts_add", "Scoring added /100", "Rates", "signed2", False,
                   "Points per 100 possessions gained by shooting above the D-I true-shooting rate on the player's volume"),
                  ("efg", "eFG%", "Shooting", "pct", False, "Effective field-goal percentage (a three counts 1.5 field goals)"),
                  ("tpar", "3PA rate", "Shooting", "pct", False, "Three-point attempts per field-goal attempt (style)"),
                  ("ftr", "FT rate", "Shooting", "3", False, "Free-throw attempts per field-goal attempt"),
                  ("fta100", "FTA/100", "Rates", "1", False, "Free-throw attempts per 100 possessions on the floor"),
                  ("ast_pct", "AST%", "Rates", "pct", False, "Share of team-mates' baskets assisted while on the floor"),
                  ("tov_pct", "TOV%", "Rates", "pct", True, "Turnovers per possession used (FGA + 0.475 FTA + TOV)"),
                  ("ast_tov", "AST/TOV", "Rates", "2", False, "Assists per turnover"),
                  ("orb_pct", "OREB%", "Rates", "pct", False, "Share of available offensive rebounds grabbed while on the floor"),
                  ("drb_pct", "DREB%", "Rates", "pct", False, "Share of available defensive rebounds grabbed while on the floor"),
                  ("trb_pct", "REB%", "Rates", "pct", False, "Share of all available rebounds grabbed while on the floor"),
                  ("stl_pct", "STL%", "Rates", "pct", False, "Steals per opponent possession while on the floor"),
                  ("blk_pct", "BLK%", "Rates", "pct", False, "Share of opponent two-point attempts blocked while on the floor"),
                  ("pf100", "PF/100", "Rates", "1", True, "Personal fouls per 100 possessions on the floor")]
# percentiles within the role use rates only (counting stats per game mix in minutes)
ROLE_PCT_KEYS = ["r", "value_pg", "fg_pct", "tp_pct", "ft_pct", "ts", "usg", "ortg"] + list(PL.RATE_KEYS)


def player_line(r: dict) -> dict:
    pg = PL.per_game_line(r)
    return {**pg, "value": r2(r["value"]), "value_pg": r2(r["value_pg"]), "r": r2(r["r"])}


def season_percentiles(ctx, s) -> dict | None:
    """A season's player percentiles as the catalogue places them, whether or not the season is an archive one (whose
    players.json leaves them out): {"rows", "lines", "floor", "qual", "role_of", "role_thr", "pcts", "pcts_pos",
    "pcts_role"} (each pcts {pid: {metric: 0-100}}), or None when the season has no rows."""
    pr = player_rows(ctx, s)
    rows = pr["rows"]
    if not rows:
        return None
    maxgp = max(r["gp"] for r in rows.values())
    floor = {"gp": max(5, int(0.4 * maxgp)), "mpg": 10.0}
    lines = {p: player_line(r) for p, r in rows.items()}
    qual = {p for p, r in rows.items() if r["gp"] >= floor["gp"] and r["min"] / max(r["gp"], 1) >= floor["mpg"]}
    role_of, role_thr = PL.classify_roles(rows, qual)
    pcts, pcts_pos, pcts_role = defaultdict(dict), defaultdict(dict), defaultdict(dict)

    def _rank(sub, k, lower, dest):
        if len(sub) < 10:
            return
        arr = np.array(sorted(sub.values()))
        for p, x in sub.items():
            q = 100.0 * np.searchsorted(arr, x, side="right") / len(arr)
            dest[p][k] = round(100 - q + 100 / len(arr) if lower else q, 1)
    for k, *_r in PLAYER_METRICS:
        lower = _r[3]
        xs = {p: lines[p][k] for p in qual if lines[p].get(k) is not None}
        if len(xs) < 10:
            continue
        _rank(xs, k, lower, pcts)
        for pos in ("G", "F", "C"):
            _rank({p: x for p, x in xs.items() if rows[p]["pos"] == pos}, k, lower, pcts_pos)
        if k in ROLE_PCT_KEYS:                         # within the role (guards / wings / bigs): the spec's peer group
            for role in ("G", "W", "B"):
                _rank({p: x for p, x in xs.items() if role_of.get(p) == role}, k, lower, pcts_role)
    return {"rows": rows, "lines": lines, "floor": floor, "qual": qual, "role_of": role_of, "role_thr": role_thr,
            "pcts": pcts, "pcts_pos": pcts_pos, "pcts_role": pcts_role}


def players_payload(ctx, s) -> dict:
    sp = season_percentiles(ctx, s)
    if sp is None:
        return fail("no usable ESPN box scores for this season (none before men 2005 / women 2014; or not played yet)", season=s)
    pr = player_rows(ctx, s)
    rows, lines, floor, qual = sp["rows"], sp["lines"], sp["floor"], sp["qual"]
    role_of, role_thr = sp["role_of"], sp["role_thr"]
    pcts, pcts_pos, pcts_role = sp["pcts"], sp["pcts_pos"], sp["pcts_role"]
    out = {}
    old = archive(ctx, s)                              # archive seasons: qualified players only (size budget)
    for p, r in rows.items():
        if r["gp"] < 5 or (old and p not in qual):
            continue
        out[p] = {"name": r["name"], "team": r["team"], "pos": r["pos"], "role": role_of.get(p), "class": r.get("class"), "gp": r["gp"],
                  "qualified": p in qual, "values": {k: lines[p].get(k) for k, *_ in PLAYER_METRICS if lines[p].get(k) is not None},
                  "pct": {} if old else pcts.get(p, {}), "pct_pos": {} if old else pcts_pos.get(p, {}),
                  "pct_role": {} if old else pcts_role.get(p, {})}
    posn = Counter(v["pos"] for v in out.values())
    rolen = Counter(v["role"] for v in out.values())
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(),
            "metrics": [_metric(*m) for m in PLAYER_METRICS],
            "positions": {"G": {"label": "Guards", "n": posn.get("G", 0)}, "F": {"label": "Forwards", "n": posn.get("F", 0)},
                          "C": {"label": "Centers", "n": posn.get("C", 0)}},
            "roles": {k: {"label": PL.ROLE_LABEL[k], "n": rolen.get(k, 0)} for k in ("G", "W", "B")},
            "role_rule": {"threshold": role_thr, "rule": "G = listed G; B = listed C, or a listed F (150+ minutes) whose "
                          "z(REB/100) + z(BLK/100) - z(3PA rate) - z(AST/100) is above the midpoint of the guards' and centres' means; "
                          "other F = W"},
            "min_floor": floor, "params": pr["params"], "players": PK.pack_keyed(out), "compact": old}


def value_row(r: dict, params: dict | None) -> dict:
    return {"id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"], "class": r.get("class"), "gp": r["gp"],
            "value": r2(r["value"]), "value_pg": r2(r["value_pg"]), "pctl": r.get("pctl"),
            "why": PL.why(r, params) if params else ""}


def value_payload(ctx, s) -> dict:
    rows, tmap, basis = roster_rows(ctx, s)
    if not rows:
        return fail("no usable ESPN box scores for this season or the last", season=s)
    params = player_rows(ctx, s if basis == "season" else s - 1)["params"]
    lst = sorted(rows.values(), key=lambda r: -r["value"])
    desc = ("Team-constrained box value: Hollinger game score per 40 minutes scaled so a team's players sum to its adjusted "
            "efficiency margin; points above a replacement-level D-I player over the possessions played.")
    if basis == "last_season":
        desc += f" Preseason: {s - 1} values of players on {s} rosters (transfers on their new teams)."
    byp = {pos: [value_row(r, params) for r in lst if r["pos"] == pos][:10] for pos in ("G", "F", "C")}
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(), "basis": basis,
            "currency": {"key": "value", "label": "Points above replacement", "desc": desc},
            "params": params, "leaders": [value_row(r, params) for r in lst[:200]], "by_position": byp}


def moves_list(ctx, s) -> list[dict]:
    b = ctx["bundles"].setdefault(s, {})
    if "moves" in b:
        return b["moves"]
    prev = player_rows(ctx, s - 1)["rows"] if (s - 1) in ctx["state"]["tabs"] else {}
    cur = player_rows(ctx, s)["rows"]
    st = D.load(ctx["level"], s)
    tm = PL.current_team_map(st, cur)
    mv = PL.inferred_moves(prev, tm, cur, st.get("players") or {}) if prev else []
    b["moves"] = mv
    return mv


def moves_payload(ctx, s) -> dict:
    mv = moves_list(ctx, s)
    by = defaultdict(lambda: {"in": [], "out": [], "net_value": 0.0})
    for m in mv:
        by[m["to"]]["in"].append(m["player"])
        by[m["from"]]["out"].append(m["player"])
        by[m["to"]]["net_value"] += m["value_before"] or 0
        by[m["from"]]["net_value"] -= m["value_before"] or 0
    for v in by.values():
        v["net_value"] = r2(v["net_value"])
    st = D.load(ctx["level"], s)
    member = {t for t, v in (st.get("teams") or {}).items() if v.get("member")}
    return {"ok": True, "season": s, "updated_at": now_iso(),
            "note": "Inferred from box scores and rosters (same ESPN athlete id on a different team from one season to the "
                    "next); not the official transfer portal. value_before = last season's points above replacement.",
            "moves": mv, "by_team": {t: v for t, v in by.items() if t in member}, "best": mv[:25],
            "summary": {"n": len(mv), "with_value_after": sum(1 for m in mv if m["value_after"] is not None),
                        "teams_in": sum(1 for t, v in by.items() if v["in"])}}


def fantasy_payload(ctx, s) -> dict:
    lv = ctx["level"]
    cur = player_rows(ctx, s)
    rows, tmap, basis = roster_rows(ctx, s)
    if not rows:
        return fail("no usable ESPN box scores for this season or the last", season=s)
    br = box_rows(ctx, s if basis == "season" else s - 1)
    bt = PL.fantasy_backtest(br)
    lines = {}
    for p, r in rows.items():
        t = r["tot"]
        gp = max(r["gp"], 1)
        L = {"pts": t["pts"] / gp, "reb": (t["oreb"] + t["dreb"]) / gp, "ast": t["ast"] / gp, "stl": t["stl"] / gp,
             "blk": t["blk"] / gp, "tpm": t["tpm"] / gp, "tov": t["tov"] / gp, "fgm": t["fgm"] / gp, "fga": t["fga"] / gp,
             "ftm": t["ftm"] / gp, "fta": t["fta"] / gp}
        L["fp"] = sum(PL.FANTASY_W[k] * L[k] for k in PL.FANTASY_W)
        if r["gp"] >= 5:
            lines[p] = L
    nine = PL.nine_cat(lines)
    st = D.load(lv, s)
    # games in the next 7 days per team (current season)
    upcoming = Counter()
    today = date.today()
    for g in (st.get("games") or {}).values():
        if g.get("status") == "pre":
            d = D.local_day(g.get("date"))
            if d and 0 <= (d - today).days < 7:
                upcoming[str(g["home"])] += 1
                upcoming[str(g["away"])] += 1
    period = "next 7 days" if s == current_season(lv) and sum(upcoming.values()) else (
        f"Preseason: per game, from {s - 1}" if basis == "last_season" else "Season per-game averages")
    proj = []
    for p, L in sorted(lines.items(), key=lambda kv: -kv[1]["fp"])[:400]:
        r = rows[p]
        ng = upcoming.get(r["team"], 0) if period == "next 7 days" else 1
        sd = 0.45 * L["fp"]
        proj.append({"id": p, "name": r["name"], "team": r["team"], "pos": r["pos"], "opp": None, "games": ng,
                     "proj": r1(L["fp"] * ng), "proj_lo": r1(max(0.0, (L["fp"] - sd) * ng)), "proj_hi": r1((L["fp"] + sd) * ng),
                     "per_game": r1(L["fp"]), "tier": None})
    vals = [x["proj"] for x in proj]
    for i, x in enumerate(proj):
        x["tier"] = 1 + i // 25
    nine_rows = sorted(({"id": p, "name": rows[p]["name"], "team": rows[p]["team"], "pos": rows[p]["pos"], "z": v["z"], "rank": v["rank"]}
                        for p, v in nine.items()), key=lambda r: r["rank"])[:300]
    return {"ok": True, "season": s, "updated_at": now_iso(),
            "scoring": {"points": PL.FANTASY_W, "nine_cat": PL.CATS9, "label": "Points: PTS 1, REB 1.2, AST 1.5, STL 3, BLK 3, TO -1 (ours)"},
            "period": period, "basis": basis, "projections": proj,
            "rankings": {"points": [{"id": x["id"], "rank": i + 1, "per_game": x["per_game"]} for i, x in enumerate(proj[:300])],
                         "nine_cat": nine_rows},
            "start_sit": [], "sleepers": _sleepers(rows, lines),
            "backtest": {k: bt.get(k) for k in ("n", "mae", "mae_naive", "rank_corr", "rank_corr_naive")} | {"season": s if basis == "season" else s - 1}}


def _sleepers(rows, lines) -> list[dict]:
    """Players with high per-minute fantasy production on limited minutes (minutes may grow)."""
    out = []
    for p, L in lines.items():
        r = rows[p]
        mpg = r["min"] / max(r["gp"], 1)
        if 10 <= mpg <= 22 and r["gp"] >= 8:
            out.append({"id": p, "name": r["name"], "team": r["team"], "pos": r["pos"], "mpg": r1(mpg),
                        "fp_per40": r1(40 * L["fp"] / mpg)})
    out.sort(key=lambda x: -x["fp_per40"])
    return out[:25]


def lab_payloads(ctx, s, sdir: Path) -> int:
    n = 0
    tv = team_values(ctx, s)
    b = bundle(ctx, s)
    st = b["st"]
    fields = ["id", "name", "conference"] + [m[0] for m in TEAM_METRICS]
    rows = [[t, (st.get("teams") or {}).get(t, {}).get("short"), (st.get("teams") or {}).get(t, {}).get("conference")]
            + [r3(v.get(k)) if isinstance(v.get(k), float) else v.get(k) for k, *_ in TEAM_METRICS] for t, v in tv.items()]
    n += write(sdir / "lab_teams.json", {"ok": True, "season": s, "kind": "team", "fields": fields,
                                         "metrics": [_metric(*m) for m in TEAM_METRICS], "rows": rows})
    pr = player_rows(ctx, s)["rows"]
    if pr:
        pf = ["id", "name", "team", "pos", "class", "gp"] + [m[0] for m in PLAYER_METRICS]
        prow = []
        old = archive(ctx, s)                         # archive seasons: qualified players only (size budget)
        gmax = max(r["gp"] for r in pr.values())
        for p, r in pr.items():
            if r["gp"] < 5 or (old and (r["gp"] < max(5, int(0.4 * gmax)) or r["min"] / max(r["gp"], 1) < 15.0)):
                continue
            L = player_line(r)
            prow.append([p, r["name"], r["team"], r["pos"], r.get("class"), r["gp"]] + [L.get(k) for k, *_ in PLAYER_METRICS])
        n += write(sdir / "lab_players.json", {"ok": True, "season": s, "kind": "player", "fields": pf,
                                               "metrics": [_metric(*m) for m in PLAYER_METRICS], "rows": prow})
    else:
        n += write(sdir / "lab_players.json", fail("no usable ESPN box scores for this season (none before men 2005 / women 2014; or not played yet)", season=s))
    return n


# ── game pages ──────────────────────────────────────────────────────────────

def wp_model(margin: float, t: float, reg_s: float, mu: float, sd: float, ot_len: float = 300.0) -> float:
    """In-game P(home wins): the remaining margin ~ N(mu * f, sd^2 * f), f = share of regulation left (overtime: of an
    overtime period, scaled by its length)."""
    if t < reg_s:
        f = (reg_s - t) / reg_s
    else:
        left = ot_len - ((t - reg_s) % ot_len)
        f = left / reg_s
    if f <= 1e-6:
        return 1.0 if margin > 0 else (0.0 if margin < 0 else 0.5)
    return float(norm.cdf((margin + mu * f) / (sd * math.sqrt(f))))


def thin_wp(series: list, eps: float = 0.01, cap: int = 300) -> list:
    """A step series [[t, p]] without the points that move less than `eps` from the last one kept (first and last
    always kept), at most `cap` points: ESPN's per-play curve drawn as the comparison line (size budget)."""
    if len(series) <= 2:
        return series
    out = [series[0]]
    for x in series[1:-1]:
        if x[1] is not None and out[-1][1] is not None and abs(x[1] - out[-1][1]) < eps:
            continue
        out.append(x)
    out.append(series[-1])
    if len(out) > cap:
        step = len(out) // cap + 1
        out = out[:-1:step] + [out[-1]]
    return out


def game_page(ctx: dict, s: int, g: dict) -> dict:
    lv = ctx["level"]
    st = D.load(lv, s)
    c = card(ctx, s, g)
    mdl = game_model(ctx, s, g)
    teams = {t: team_rec(st, t) for t in (str(g.get("home")), str(g.get("away")))}
    players = st.get("players") or {}
    box = {}
    leaders = {}
    for t, v in (g.get("box") or {}).items():
        rows = []
        for row in v.get("players") or []:
            o = {k: row[i] for i, k in enumerate(ST.BOX_COLS)}
            o["name"] = (players.get(str(row[0])) or {}).get("name")
            o["min"] = round((row[2] or 0) / 60.0, 1)
            rows.append(o)
        # box rows as arrays in store.BOX_COLS order with a names map, DNP rows as [id, name, reason] (size budget;
        # the front end reads either form)
        box[t] = {"players": [list(row[:len(ST.BOX_COLS)]) for row in v.get("players") or []],
                  "names": {str(r["player_id"]): r["name"] for r in rows if r.get("name")}, "team": v.get("team"),
                  "dnp": [[d[0], (players.get(str(d[0])) or {}).get("name"), d[1] if len(d) > 1 else None]
                          for d in v.get("dnp") or []]}
        top = sorted(rows, key=lambda r: -((r.get("pts") or 0) + 1.2 * ((r.get("oreb") or 0) + (r.get("dreb") or 0)) + 1.5 * (r.get("ast") or 0)))[:3]
        leaders[t] = [{"id": str(r["player_id"]), "name": r["name"],
                       "line": f"{r.get('pts') or 0} pts, {(r.get('oreb') or 0) + (r.get('dreb') or 0)} reb, {r.get('ast') or 0} ast"} for r in top]
    flow, wp, plays = None, None, None
    pbp = ST.load_pbp(lv, s, str(g["id"])) if g.get("has_pbp") or ST.has_pbp_file(lv, s, str(g["id"])) else None
    if pbp and pbp.get("plays"):
        reg_s = 2400.0
        mu = (mdl or {}).get("margin") or 0.0
        sd = (mdl or {}).get("sd") or M.DEFAULTS[lv]["s0"]
        espn_wp = pbp.get("wp") or {}
        flow, wm, we, cand = [], [], [], []
        last_m = None
        prev_p = wp_model(0.0, 0.0, reg_s, mu, sd)
        wm.append([0, r4(prev_p)])
        for row in pbp["plays"]:
            try:
                per, clk = int(row[1]), float(row[2] or 0)
                t = canon.game_t(lv, per, clk, s)
                hs_, as_ = float(row[11] or 0), float(row[12] or 0)
            except (TypeError, ValueError, IndexError):
                continue
            m = hs_ - as_
            if m != last_m:
                flow.append([round(t), int(m)])
                p = wp_model(m, t, reg_s, mu, sd)
                wm.append([round(t), r4(p)])
                if row[10]:
                    team = str(row[4]) if row[4] is not None else None
                    cand.append({"t": round(t), "period": per, "clock": clk, "team": team, "text": row[13], "wpa": r4(p - prev_p)})
                prev_p = p
                last_m = m
            ew = espn_wp.get(str(row[0]))
            if ew is not None:
                we.append([round(t), r3(ew)])
        we = thin_wp(we)
        flow = flow or None
        wp = {"model": wm, "espn": we or []}
        plays = sorted(cand, key=lambda x: -abs(x["wpa"] or 0))[:10]
        for x in plays:
            if isinstance(x.get("text"), str) and len(x["text"]) > 140:
                x["text"] = x["text"][:139].rstrip() + "…"
    o = g.get("odds") or {}
    if mdl is not None:
        ib = informed_block(informed(ctx, s).get(str(g["id"])))
        if ib:
            mdl = {**mdl, "trial": ib}           # shown beside the published model, not used for it
    el = None
    tab = ctx["state"]["tabs"].get(s)
    if tab is not None:
        gi = _gindex(tab)
        if str(g["id"]) in gi:
            el = r4(ctx["state"]["elo"][s]["p_home"][gi[str(g["id"])]])
    pred = (g.get("predictor") or {}).get("home")
    return {"ok": True, "id": str(g["id"]), "level": lv, "season": s, **{k: v for k, v in c.items() if k not in ("id", "season")},
            "teams": teams, "venue": g.get("venue"), "attendance": g.get("attendance"),
            "pregame": {"model": mdl, "market": {**(game_market(lv, g) or {}), "ml_home": o.get("ml_home"), "ml_away": o.get("ml_away"),
                                                 "open_spread_home": o.get("open_spread_home"), "provider": o.get("provider")} if o else None,
                        "espn_predictor": pred, "elo_p_home": el},
            "box": box, "team_stats": {} if box and all(v.get("team") for v in box.values()) else (g.get("team_stats") or {}),
            "flow": flow, "wp": wp, "plays": plays, "leaders": leaders}


def game_pages(ctx, s, sdir: Path) -> int:
    lv = ctx["level"]
    cur = current_season(lv)
    st = D.load(lv, s)
    teams = st.get("teams") or {}
    n = 0
    written = set()
    for g in (st.get("games") or {}).values():
        if s == cur:
            want = g.get("status") in ("post", "in")
        elif s == cur - 1:
            want = g.get("status") == "post" and g.get("stype") in POST_PAGES
        else:
            want = False
        if not want:
            continue
        if not ((teams.get(str(g.get("home"))) or {}).get("member") or (teams.get(str(g.get("away"))) or {}).get("member")):
            continue
        try:
            write(sdir / "games" / f"{g['id']}.json", game_page(ctx, s, g))
        except Exception as exc:  # noqa: BLE001
            write(sdir / "games" / f"{g['id']}.json", fail(f"game page failed: {exc}"))
        written.add(f"{g['id']}.json")
        n += 1
    gdir = sdir / "games"
    if gdir.is_dir():                                  # pages no longer in scope (size budget)
        for p in gdir.glob("*.json"):
            if p.name not in written:
                try:
                    p.unlink()
                except OSError:
                    pass
    return n


# ── format migration (seasons restored from the live site) ─────────────────

def _read(p: Path) -> Any:
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def migrate(level: str, out_dir: Path | str, season: int) -> int:
    """Upgrade an already written season folder to FORMAT in place, without the models: pack schedule.json,
    players.json and the team pages' lists, drop archive team pages' schedules (and rating paths). CI rebuilds only the
    newest seasons and restores the rest from the live site, so scripts/build_campus.py calls this on the others.
    Returns the number of files rewritten (0 when the folder is already current or has no readable season.json)."""
    lv = D.level_of(level)
    s = int(season)
    sdir = Path(out_dir) / lv / str(s)
    sea = _read(sdir / "season.json")
    if not isinstance(sea, dict) or sea.get("ok") is False or int(sea.get("fmt") or 1) >= FORMAT:
        return 0
    old = is_archive(lv, s)
    n = 0
    sch = _read(sdir / "schedule.json")
    if isinstance(sch, dict) and isinstance(sch.get("games"), list):
        sch["games"] = PK.pack(sch["games"])
        write(sdir / "schedule.json", sch)
        n += 1
    pl = _read(sdir / "players.json")
    if isinstance(pl, dict) and isinstance(pl.get("players"), dict) and not PK.is_packed(pl["players"]):
        pl["players"] = PK.pack_keyed(pl["players"])
        write(sdir / "players.json", pl)
        n += 1
    for f in sorted((sdir / "teams").glob("*.json")):
        d = _read(f)
        if not isinstance(d, dict) or d.get("ok") is False:
            continue
        if old:
            d.pop("schedule", None)
            d.pop("rating_path", None)
        elif isinstance(d.get("schedule"), list):
            d["schedule"] = PK.pack(d["schedule"])
        if isinstance(d.get("roster"), list):
            d["roster"] = PK.pack(d["roster"])
        write(f, d)
        n += 1
    n += bracket_sites(sdir)
    sea["fmt"] = FORMAT
    write(sdir / "season.json", sea)
    return n + 1


def bracket_sites(sdir: Path) -> int:
    """Add `actual.sites` (region_sites, from the bracket's own game notes) to a bracket.json written before it
    existed; 1 when the file was rewritten."""
    br = _read(sdir / "bracket.json")
    act = (br or {}).get("actual") if isinstance(br, dict) else None
    if not isinstance(act, dict) or "sites" in act or not act.get("regions"):
        return 0
    act["sites"] = region_sites(PK.unpack(act.get("games") or []), list(act["regions"]))
    write(sdir / "bracket.json", br)
    return 1


# ── public: build one season ────────────────────────────────────────────────

def build(level: str, season: int, out_dir: Path | str, stores: Any = None, *, full: bool = True, sims: int = 10000,
          markets: bool = True) -> dict:
    """Write the per-season payloads of `level` and `season` under out_dir/<L>/<S>/ (module docstring)."""
    lv = D.level_of(level)
    s = int(season)
    sdir = Path(out_dir) / lv / str(s)
    sdir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    summary = {"level": lv, "season": s, "ok": True, "files": {}, "errors": {}}
    try:
        ctx = context(lv)
        if s not in ctx["state"]["tabs"]:
            raise ValueError(f"no store for {lv} {s}")
    except Exception as exc:  # noqa: BLE001
        for f in ("season", "schedule", "bracket"):
            write(sdir / f"{f}.json", fail(f"model state failed: {exc}"))
        return {**summary, "ok": False, "reason": str(exc)}

    def step(name, fn):
        try:
            obj = fn()
            summary["files"][name] = write(sdir / f"{name}.json", obj)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s %s failed: %s", lv, s, name, exc)
            summary["errors"][name] = f"{type(exc).__name__}: {exc}"
            summary["files"][name] = write(sdir / f"{name}.json", fail(f"{type(exc).__name__}: {exc}"))
            logger.debug(traceback.format_exc())
    step("season", lambda: season_payload(ctx, s, sims))
    step("schedule", lambda: schedule_payload(ctx, s))
    step("bracket", lambda: bracket_payload(ctx, s, sims))
    # catalogues and team pages for every season; `full` (build_campus: the newest --game-page-seasons) gates only the
    # game pages, which game_pages() further limits to the current season and the previous season's postseason
    if True:
        step("teams", lambda: teams_payload(ctx, s))
        step("players", lambda: players_payload(ctx, s))
        step("value", lambda: value_payload(ctx, s))
        step("moves", lambda: moves_payload(ctx, s))
        step("fantasy", lambda: fantasy_payload(ctx, s))
        try:
            lab_payloads(ctx, s, sdir)
        except Exception as exc:  # noqa: BLE001
            summary["errors"]["lab"] = str(exc)
            write(sdir / "lab_teams.json", fail(str(exc)))
            write(sdir / "lab_players.json", fail(str(exc)))
        try:
            summary["team_pages"] = team_pages(ctx, s, sdir, sims)
        except Exception as exc:  # noqa: BLE001
            summary["errors"]["teams_pages"] = str(exc)
        if full:
            try:
                summary["game_pages"] = game_pages(ctx, s, sdir)
            except Exception as exc:  # noqa: BLE001
                summary["errors"]["game_pages"] = str(exc)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    summary["ok"] = not summary["errors"]
    return summary


# ── public: per-level files ─────────────────────────────────────────────────

def calibration_payload(ctx: dict) -> dict:
    st8 = ctx["state"]
    lv = ctx["level"]
    done = [s for s in st8["seasons"] if s < current_season(lv)]
    body = BT.summarize(st8, done)
    if ctx.get("tbt") is None:
        ctx["tbt"] = N.tourney_backtest(st8, ctx["pre"], n=4000)
    tb = ctx["tbt"]
    loso = ctx["loso"]
    kp = st8["k_poss"]
    notes = [
        "Walk-forward: every game is predicted from ratings fitted on earlier days only (with the preseason prior from the "
        "previous season), and the game-model parameters for a season come from earlier seasons only.",
        "Closing lines: ESPN's core API (consensus 2013, offshore books 2014-2016 as a median, US books later, DraftKings / "
        "ESPN BET closes recently); coverage grows as the summaries/lines backfill lands, so v-close numbers cover only "
        "games with a stored line.",
        f"Possessions: box scores where present, else the scoreboard estimate x {kp['pooled']:.3f} (fitted ratio; MAE "
        f"{kp.get('mae_ratio')} possessions v {kp.get('mae_const')} for a constant).",
        "Neutral sites: ESPN's flag from 2008 (men) / 2011 (women); earlier seasons infer it from the venue v the home "
        "team's usual venue (women before 2011 have no venues: tournament games only).",
        "Selection proxy accuracy is leave-one-season-out; the tournament forecasts use the actual bracket with "
        "pre-tournament ratings; the seed baseline is fitted on earlier seasons only."]
    notes.append("Lines are sanity-checked: ESPN's core API put the -110 quote in the spread and total "
                 "fields of about 300 men's 2023 games; those lines are dropped, as are totals outside a plausible range.")
    notes.append("by_line splits the v-close numbers by line type: an explicit closing line (the book's close block, ESPN BET "
                 "2023-2025, DraftKings 2026) or the last listed line / median of books (earlier seasons), which may be "
                 "earlier than the true close and so easier to beat.")
    notes.append("ESPN's matchup predictor is stored only for games fetched before tip-off; none of the backfilled seasons "
                 "have it, so there is no comparison yet (espn_predictor null).")
    if lv == "wbb":
        notes.append("Women's closing lines are sparse before 2023 and partial since (about a third of games).")
    body["sim"] = {"tournament": tb["summary"], "tournament_per_season": tb["per_season"],
                   "selection": {k: v for k, v in (loso or {}).items()} if loso else None}
    body["params"] = {"game": {k: r4(v) if isinstance(v, float) else v for k, v in st8["params"]["latest"].items()},
                      "ratings": {"half_life_days": R.HALF_LIFE[lv], "ridge_games": R.RIDGE[lv], "q_per_day": R.Q_PER_DAY[lv]},
                      "carryover": st8["coef"][max(st8["seasons"])],
                      "roster": (st8.get("roster_fit") or {}).get(max(st8["seasons"])),
                      "possessions": {k: v for k, v in kp.items() if k != "n"}}
    body["informed"] = INF.summary(lv)
    # the kit's "How sure are we?" block (QK.calib.find reads metrics.model): the walk-forward bins and scores above
    from oddsmarkets.common import calibration as CB
    sm = (body.get("summary") or {}).get("model") or {}
    blk = CB.from_table(body.get("calibration") or [], sm.get("n"), sm.get("brier"), sm.get("logloss"))
    if blk:
        body["metrics"] = {"model": blk}
    return {"ok": True, "level": lv, "updated_at": now_iso(), **body, "notes": notes}


def history_payload(ctx: dict) -> dict:
    lv = ctx["level"]
    champs = []
    confc = {}
    best = []
    for s in ctx["seasons"]:
        st = D.load(lv, s)
        pre = ctx["pre"].get(s)
        if pre:
            af = pre["af"]
            gs = TT.ncaa_games(st)
            fin = gs[-1] if gs else None
            if fin and af["champion"]:
                ru = str(fin["away"] if str(fin["home"]) == af["champion"] else fin["home"])
                champs.append({"season": s, "team": af["champion"], "runner_up": ru,
                               "score": f"{max(fin['hs'], fin['as'])}-{min(fin['hs'], fin['as'])}"})
            confc[str(s)] = TT.conf_champions(st, af["first_day"])
        tab = ctx["state"]["tabs"][s]
        e = ctx["state"]["ends"].get(s)
        if e and s < current_season(lv):
            for t, v in e["teams"].items():
                if t != D.ND1 and v["games"] >= 20:
                    best.append((v["net"], s, t))
    best.sort(reverse=True)
    rows = []
    for net, s, t in best[:25]:
        st = D.load(lv, s)
        w = l = 0
        for g in (st.get("games") or {}).values():
            if g.get("status") == "post" and g.get("hs") is not None and t in (str(g["home"]), str(g["away"])) and g.get("stype") in D.COUNTED:
                won = (g["hs"] > g["as"]) == (str(g["home"]) == t)
                w += won
                l += not won
        rows.append({"season": s, "team": t, "name": (st.get("teams") or {}).get(t, {}).get("short"), "rating": r2(net), "record": f"{w}-{l}"})
    return {"ok": True, "level": lv, "updated_at": now_iso(), "champions": champs, "conference_champions": confc,
            "best_teams": rows, "first_season": min(ctx["seasons"]),
            "note": "best_teams: season-end ratings (no recency weighting) including the postseason."}


def markets_payload(ctx: dict, season: int, markets: bool, sims: int) -> dict:
    lv = ctx["level"]
    fut = None
    if markets:
        try:
            from oddsmarkets.college.sources import markets as MK
            fut = MK.futures(lv, season)
        except Exception as exc:  # noqa: BLE001
            logger.info("futures failed: %s", exc)
            fut = None
        # each venue's book is judged on its own (sources/markets.py assemble): an overround Polymarket book no longer
        # sinks a complete Kalshi one, so the champion line needs no Kalshi-only fallback here
    sim = season_sim(ctx, season, sims)
    model = {"champion": {}, "conference": {}, "ncaa": {}}
    if sim:
        for t, v in sim["teams"].items():
            if (v.get("p_title") or 0) > 0:
                model["champion"][t] = v["p_title"]
            if (v.get("p_ncaa") or 0) > 0:
                model["ncaa"][t] = v["p_ncaa"]
        st = D.load(lv, season)
        for t, v in sim["teams"].items():
            c = (st.get("teams") or {}).get(t, {}).get("conference")
            if c and (v.get("p_conf_tourney") or 0) > 0:
                model["conference"].setdefault(c, {})[t] = v["p_conf_tourney"]
    games = {}
    if markets:
        try:
            from oddsmarkets.college.sources import markets as MK
            prices = MK.game_prices(lv)
            st = D.load(lv, season)
            for gid, pr in prices.items():
                g = (st.get("games") or {}).get(gid)
                if not g:
                    continue
                m = game_model(ctx, season, g)
                edge = r4(m["p_home"] - pr["p_home"]) if m and pr.get("p_home") is not None else None
                games[gid] = {"home": pr["home"], "away": pr["away"], "date": g.get("date"), "model": m,
                              "market": {"p_home": pr.get("p_home"), "basis": pr.get("basis"), "spread_home": pr.get("spread_home"),
                                         "total": pr.get("total")}, "edge": edge}
        except Exception as exc:  # noqa: BLE001
            logger.info("game prices failed: %s", exc)
    return {"ok": True, "level": lv, "season": season, "updated_at": now_iso(), "fetched": bool(markets and fut),
            "futures": fut, "model": model, "games": games}


ROLE_GROUP = {"G": "guards", "W": "wings", "B": "bigs"}


def qualified_roles(ctx: dict, s: int) -> tuple[dict, set, dict]:
    """(lines {pid: player_line}, qualified pids, role {pid: G|W|B}) of a season, as players_payload defines them."""
    rows = player_rows(ctx, s)["rows"]
    if not rows:
        return {}, set(), {}
    maxgp = max(r["gp"] for r in rows.values())
    floor = {"gp": max(5, int(0.4 * maxgp)), "mpg": 10.0}
    qual = {p for p, r in rows.items() if r["gp"] >= floor["gp"] and r["min"] / max(r["gp"], 1) >= floor["mpg"]}
    role_of, _thr = PL.classify_roles(rows, qual)
    return {p: player_line(rows[p]) for p in qual}, qual, role_of


def similar_players(ctx: dict, seasons: list[int], current: int, k: int | None = None) -> dict[str, list]:
    """{pid: [{"id","name","team","season","distance"}]} for players qualified in one of the last two seasons (their
    latest): the nearest qualified player-seasons of the same role over the last ten seasons, the spec's weighted
    distance, other players only."""
    from oddsmarkets.common import similar as SIM
    lv = ctx["level"]
    pool = [s for s in seasons if current - 9 <= s <= current]
    by_role: dict[str, list] = defaultdict(list)
    for s in pool:
        lines, qual, role_of = qualified_roles(ctx, s)
        rows = player_rows(ctx, s)["rows"]
        for p in qual:
            r = role_of.get(p)
            if r in ROLE_GROUP:
                by_role[r].append((s, p, rows[p]["name"], rows[p]["team"], lines[p]))
    out: dict[str, list] = {}
    for role, items in by_role.items():
        cfg = SIM.group_config("college", f"{lv}_{ROLE_GROUP[role]}")
        if not cfg or len(items) < 6:
            continue
        feats = cfg["features"]
        M = SIM.matrix([it[4] for it in items], feats, get=lambda r, f: r.get(f))
        seas = np.array([it[0] for it in items])
        Z = SIM.zscore(M, seas.tolist())
        w = np.array([cfg["weights"][f] for f in feats])
        pids = np.array([str(it[1]) for it in items], dtype=object)
        latest: dict[str, int] = {}
        for i, (s_, p_) in enumerate(zip(seas, pids)):
            if s_ >= pool[-1] - 1 and (p_ not in latest or s_ > seas[latest[p_]]):
                latest[p_] = i
        for p_, i in latest.items():
            nb = SIM.nearest(Z, i, w, k or cfg["k"], allowed=pids != p_)
            out[p_] = [{"id": pids[j], "name": items[j][2], "team": items[j][3], "season": int(seas[j]), "distance": r3(d)}
                       for j, d in nb]
    return out


def prev_ring(cur_sp: dict | None, prev_sp: dict | None, pid: str, season: int) -> dict:
    """Last season's role percentiles for a current block (kit v3 rail rings, 23 Oct 2026): {"prev_pct_pos" (last
    season's pct_role: the spec's guards / wings / bigs), "prev_peer" {"season", "role", "pos", "gp", "qualified"}}
    when the player was qualified last season in the role this season's catalogue gives, else {}. cur_sp / prev_sp:
    season_percentiles() of this season and last (past seasons' players.json carry no percentiles, so they are
    placed here as the catalogue would)."""
    if not cur_sp or not prev_sp:
        return {}
    role = cur_sp["role_of"].get(pid)
    pc = prev_sp["pcts_role"].get(pid)
    if not role or pid not in prev_sp["qual"] or prev_sp["role_of"].get(pid) != role or not pc:
        return {}
    r = prev_sp["rows"].get(pid) or {}
    return {"prev_pct_pos": dict(pc), "prev_peer": {"season": season, "role": role, "pos": r.get("pos"), "gp": r.get("gp"), "qualified": True}}


def career_files(ctx: dict, out: Path, current: int) -> int:
    lv = ctx["level"]
    with_box = [s for s in ctx["seasons"] if s <= current and len(box_rows(ctx, s)["pid"])]
    if not with_box:
        return 0
    recent = with_box[-2:]
    wanted = set()
    for s in recent:
        wanted |= set(player_rows(ctx, s)["rows"])
    rows_by = {s: player_rows(ctx, s)["rows"] for s in with_box}
    moves_by = {s: moves_list(ctx, s) for s in with_box}
    mv_of = defaultdict(list)
    for s, mv in moves_by.items():
        for m in mv:
            mv_of[m["player"]].append({"season": s, "from": m["from"], "to": m["to"], "value_before": m["value_before"],
                                       "value_after": m["value_after"]})
    # similar players (docs/METRICS_SPEC.md): the role group's features and year-to-year weights from
    # docs/_design/metrics/college.json, z within role and season over qualified players, weighted Euclidean
    # (common.similar), k = 5, qualified player-seasons of the last ten seasons, never the player herself / himself
    sim_of = similar_players(ctx, with_box, current)
    n = 0
    pdir = out / lv / "players"
    stores = {s: D.load(lv, s) for s in with_box}
    sps: dict[int, dict | None] = {}

    def sp_of(season: int) -> dict | None:             # a season's percentiles (season_percentiles), once
        if season not in sps:
            sps[season] = season_percentiles(ctx, season) if season in ctx["seasons"] else None
        return sps[season]
    pidx: dict[int, dict[str, list[int]]] = {}
    for s in recent:
        acc_ = defaultdict(list)
        for k, q in enumerate(box_rows(ctx, s)["pid"]):
            acc_[q].append(k)
        pidx[s] = acc_
    # Progression (oddsmarkets/college/progression.py): dv / dp / pg on every season with box scores, within the role
    # (guards, wings, bigs) among the season's qualified players (the catalogue's floor), and progression_ref.json
    prog_rows, prog_block = {}, None
    try:
        recs = {}
        for s in with_box:
            sp = sp_of(s)
            if not sp:
                continue
            recs[s] = [{"pid": q, "kind": sp["role_of"].get(q), "q": q in sp["qual"], "values": sp["lines"].get(q) or {},
                        "pct": sp["pcts_role"].get(q) or None}
                       for q in sp["rows"]]
        prog_rows, ref, prog_block = PROG.build(lv, recs)
        write(out / lv / PROG.PROG_FILE, ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s progression failed: %s", lv, exc)
    written = set()
    for p in wanted:
        try:
            seasons_rows = []
            info = {}
            for s in with_box:
                r = rows_by[s].get(p)
                if not r:
                    continue
                L = player_line(r)
                seasons_rows.append({"season": s, "team": r["team"], "gp": r["gp"], **{k: L[k] for k in
                                     ("min", "pts", "reb", "ast", "stl", "blk", "tov", "fg_pct", "tp_pct", "ft_pct", "ts", "usg", "ortg")},
                                     "value": L["value"], "value_pg": L["value_pg"], "pctl": r.get("pctl"), "r": L["r"]})
                info = (stores[s].get("players") or {}).get(p) or info
            if not seasons_rows:
                continue
            PROG.merge({}, seasons_rows, prog_rows.get(str(p)), None)
            ls = seasons_rows[-1]["season"]
            r = rows_by[ls][p]
            br = box_rows(ctx, ls)
            log = []
            stl = stores[ls].get("games") or {}
            for k in pidx[ls].get(p, []):
                x = br["X"][k]
                g = stl.get(br["gid"][k]) or {}
                mine = g.get("hs") if br["home"][k] else g.get("as")
                theirs = g.get("as") if br["home"][k] else g.get("hs")
                res = None if mine is None or theirs is None else f"{'W' if mine > theirs else 'L'} {mine}-{theirs}"
                log.append({"game": br["gid"][k], "date": D.day_str(int(br["day"][k])), "opp": br["opp"][k], "home": bool(br["home"][k]),
                            "res": res, "min": round(x[0] / 60, 1), "pts": int(x[1]), "reb": int(x[8] + x[9]), "ast": int(x[10]),
                            "stl": int(x[11]), "blk": int(x[12]), "tov": int(x[13]), "fgm": int(x[2]), "fga": int(x[3]),
                            "tpm": int(x[4]), "tpa": int(x[5]), "ftm": int(x[6]), "fta": int(x[7])})
            log.sort(key=lambda z: z["date"])
            similar = sim_of.get(p, [])
            page = {"ok": True, "id": p, "name": r["name"], "pos": r["pos"], "level": lv, "updated_at": now_iso(),
                    "class": info.get("class"), "height_in": info.get("height_in"), "weight_lb": info.get("weight_lb"),
                    "hometown": info.get("hometown"), "number": jersey_number(info.get("jersey")), "seasons": PK.pack(seasons_rows),
                    "current": {"season": ls, "team": r["team"], "log": PK.pack(log), "value": value_row(r, player_rows(ctx, ls)["params"]),
                                "fantasy": None, **prev_ring(sp_of(ls), sp_of(ls - 1), p, ls - 1)},
                    "moves": mv_of.get(p, []), "similar": similar}
            if prog_block and prog_rows.get(str(p)):
                page["prog"] = prog_block
            write(pdir / f"{p}.json", page)
            written.add(f"{p}.json")
            n += 1
        except Exception as exc:  # noqa: BLE001
            write(pdir / f"{p}.json", fail(f"career page failed: {exc}"))
            written.add(f"{p}.json")
    for f in pdir.glob("*.json"):                      # careers no longer in scope (size budget)
        if f.name not in written:
            try:
                f.unlink()
            except OSError:
                pass
    return n


def build_level(level: str, out_dir: Path | str, seasons: Iterable[int] | None = None, current: int | None = None, *,
                sims: int = 10000, markets: bool = True, full: bool = True, per_season: bool = True) -> dict:
    """Per-level files, then (per_season=True) build() for each season (module docstring)."""
    lv = D.level_of(level)
    out = Path(out_dir)
    ldir = out / lv
    ldir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    summary = {"level": lv, "ok": True, "files": {}, "errors": {}, "seasons": {}}
    cur = int(current or current_season(lv))
    try:
        ctx = context(lv)
    except Exception as exc:  # noqa: BLE001
        for f in ("calibration", "history", "markets"):
            write(ldir / f"{f}.json", fail(f"model state failed: {exc}"))
        return {**summary, "ok": False, "reason": str(exc)}
    ss = sorted(int(s) for s in (seasons if seasons is not None else ctx["seasons"]))

    def step(name, fn):
        try:
            summary["files"][name] = write(ldir / f"{name}.json", fn())
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s %s failed: %s", lv, name, exc)
            summary["errors"][name] = f"{type(exc).__name__}: {exc}"
            summary["files"][name] = write(ldir / f"{name}.json", fail(f"{type(exc).__name__}: {exc}"))
    step("calibration", lambda: calibration_payload(ctx))
    step("history", lambda: history_payload(ctx))
    step("markets", lambda: markets_payload(ctx, cur, markets, sims))
    if full:
        try:
            summary["careers"] = career_files(ctx, out, cur)
        except Exception as exc:  # noqa: BLE001
            summary["errors"]["careers"] = str(exc)
    if per_season:
        for s in ss:
            summary["seasons"][s] = build(lv, s, out, full=full, sims=sims, markets=markets)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    summary["ok"] = not summary["errors"] and all(v.get("ok") for v in summary["seasons"].values())
    return summary


def main(argv: list[str] | None = None) -> int:
    """python -m oddsmarkets.college.hoops.build [--levels mbb,wbb] [--seasons 2026,2027] [--sims N] [--no-market]
    [--quick] [--out DIR]: build the basketball payloads (the site orchestrator is scripts/build_campus.py)."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="mbb,wbb")
    ap.add_argument("--seasons", default=None)
    ap.add_argument("--sims", type=int, default=10000)
    ap.add_argument("--no-market", action="store_true")
    ap.add_argument("--quick", action="store_true", help="season, schedule and bracket only; no careers")
    ap.add_argument("--out", default=str(ST.paths()["data"]))
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    rc = 0
    for lv in a.levels.split(","):
        ss = [int(x) for x in a.seasons.split(",")] if a.seasons else None
        res = build_level(lv, a.out, ss, sims=a.sims, markets=not a.no_market, full=not a.quick)
        bad = {s: v.get("errors") for s, v in res["seasons"].items() if v.get("errors")}
        logger.info("%s done in %ss: level errors %s, season errors %s", lv, res.get("seconds"), res.get("errors"), bad)
        rc = rc or (0 if res.get("ok") else 1)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
