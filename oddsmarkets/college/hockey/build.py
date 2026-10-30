"""
College hockey payloads for The Quant Campus (`mch` men, `wch` women): the same contract as basketball
(oddsmarkets/college/PAYLOADS.md) where the shapes carry over, plus hockey's own (box scores, the NPI / PairWise
table, the NCAA regionals). Called by scripts/build_campus.py like the other levels:

    build_level(level, out_dir, seasons, current, sims=, markets=)   per-level files: calibration, history, markets,
                                                                     careers (players/<pid>.json)
    build(level, season, out_dir, full=, sims=)                       per-season files: season, schedule, bracket,
                                                                     teams (+ team pages), players, value, moves,
                                                                     lab_players, lab_teams, performers, games/<gid>

Inputs are the private season stores (hockey/data.py, data/college/stores/<L>/<S>.json.gz). College Hockey News
data sits under each store's `chn` block and is used only while sources/chn.py `enabled()`: switched off, every
CHN-derived payload (players, value, moves, lab_players, box scores, shot and power-play numbers) is written as
{"ok": false, "reason": "..."} and the rest (results, ratings, NPI, simulations, brackets) is built from ESPN.

Models: hockey/model.py (game model, walk-forward), npi.py (NPI / PairWise replica), sim.py (season simulation),
players.py (GAR). Sealed test seasons 2025 and 2026 (2024-25, 2025-26): nothing is tuned on them.
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import pickle
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .. import packing as PK
from .. import store as cc_store
from ..sources import chn
from . import data as D
from . import model as M
from . import npi as N
from . import players as P
from . import sim as SIM

logger = logging.getLogger(__name__)

FORMAT = 1
NAME = {"mch": "Men's College Hockey", "wch": "Women's College Hockey"}
SHORT = {"mch": "MCH", "wch": "WCH"}
SEALED = (2025, 2026)
DEV_FROM = 2007


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def r1(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 1)


def r2(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 2)


def r3(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 3)


def r4(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), 4)


def write(p: Path, obj: Any) -> int:
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)
    return p.stat().st_size


def fail(reason: str, **kw) -> dict:
    return {"ok": False, "reason": reason, **kw}


def current_season(level: str, today: date | None = None) -> int:
    """The season shown by default: the one in progress, from 1 May the coming one (as basketball)."""
    d = today or date.today()
    return d.year + 1 if d.month >= 5 else d.year


def chn_on(st: dict | None) -> bool:
    return bool(chn.enabled() and st and st.get("chn"))


# ── colours: the school's colours from the other Campus levels (same ESPN school id), else a small table ─────

HOCKEY_COLOURS = {  # schools with no FBS / D-I basketball team in the Campus stores: name -> (colour, alt)
    "RIT": ("#f76902", "#000000"), "Bentley": ("#1c3f94", "#a2aaad"), "Clarkson": ("#004e42", "#ffd200"),
    "Union": ("#822433", "#000000"), "Rensselaer": ("#d6001c", "#000000"), "RPI": ("#d6001c", "#000000"),
    "St. Lawrence": ("#8b0000", "#5f3a1f"), "Colorado College": ("#000000", "#c99700"), "Minnesota Duluth": ("#7a0019", "#ffcc33"),
    "Minnesota-Duluth": ("#7a0019", "#ffcc33"), "Michigan Tech": ("#000000", "#ffcd00"), "Ferris State": ("#bc0022", "#ffc72c"),
    "Lake Superior State": ("#003f87", "#ffc72c"), "Lake Superior": ("#003f87", "#ffc72c"), "Bemidji State": ("#006241", "#000000"),
    "Augustana": ("#002f6c", "#fdb827"), "Augustana University (SD)": ("#002f6c", "#fdb827"), "Mercyhurst": ("#00543c", "#1c4b9a"),
    "Alaska": ("#236192", "#ffcd00"), "Alaska Anchorage": ("#00583d", "#ffc425"), "Alaska-Anchorage": ("#00583d", "#ffc425"),
    "Franklin Pierce": ("#cc0000", "#000000"), "Saint Anselm": ("#003da5", "#ffffff"), "St. Anselm": ("#003da5", "#ffffff"),
    "Saint Michael's": ("#a6192e", "#002d72"), "Post University": ("#1d4289", "#c8102e"), "Post": ("#1d4289", "#c8102e"),
    "Assumption": ("#002d72", "#ffffff"), "Assumption College": ("#002d72", "#ffffff"), "Plattsburgh": ("#cc0033", "#ffffff"),
    "Maryville": ("#d50032", "#000000"), "Maryville (Mo)": ("#d50032", "#000000"), "Lindenwood": ("#000000", "#b5a36a"),
    "Long Island University": ("#00539b", "#ffc72c"), "Stonehill": ("#2f2a72", "#ffffff"), "St. Thomas": ("#510c76", "#a7a8aa"),
    "St. Thomas - Minnesota": ("#510c76", "#a7a8aa"), "Omaha": ("#d71920", "#000000"), "St. Cloud State": ("#c8102e", "#000000"),
    "Northern Michigan": ("#00563f", "#ffc72c"), "Minnesota State": ("#582c83", "#ffc72c"), "Bowling Green": ("#4f2c1d", "#fe5000"),
    "Western Michigan": ("#6c4023", "#b5a167"), "Holy Cross": ("#602d89", "#ffffff"), "Canisius": ("#0e2756", "#fdb913"),
    "Niagara": ("#582c83", "#ffffff"), "Robert Morris": ("#14234b", "#a6192e"), "Sacred Heart": ("#ce1141", "#636466"),
    "American International": ("#000000", "#ffc72c"), "Quinnipiac": ("#0c2340", "#ffb81c"), "Merrimack": ("#003768", "#ffc72c"),
}


def colour_map() -> dict[str, tuple]:
    """{espn school id: (colour, alt)} from the Campus basketball and football stores (latest season of each)."""
    out: dict[str, tuple] = {}
    root = cc_store.paths()["stores"]
    for lv in ("mbb", "wbb", "cfb"):
        d = root / lv
        if not d.exists():
            continue
        files = sorted(d.glob("*.json.gz"), key=lambda p: p.name)[-2:]
        for p in files:
            try:
                with gzip.open(p, "rt", encoding="utf-8") as fh:
                    st = json.load(fh)
            except (OSError, ValueError):
                continue
            for t, v in (st.get("teams") or {}).items():
                if v.get("colour") and t not in out:
                    out[t] = (v.get("colour"), v.get("alt_colour"))
    return out


# ── context: stores, walk-forward predictions, end-of-season fits ──────────────────────────────────────────

_CTX: dict[str, dict] = {}


def cache_dir() -> Path:
    return cc_store.paths()["cache"] / "hockey"


def load_stores(level: str) -> dict[int, dict]:
    out = {}
    for s in D.seasons_on_disk(level):
        st = D.load_store(level, s)
        if st:
            if not chn.enabled():
                st.pop("chn", None)
                for g in st.get("games") or []:
                    g.pop("chn", None)
            out[s] = st
    return out


def params(level: str) -> dict:
    """The game model's parameters, chosen on the dev seasons (scripts/cc_hockey_tune.py writes them)."""
    p = dict(M.DEFAULTS)
    f = Path(__file__).with_name("fitted") / f"{level}_params.json"
    if not f.exists():                       # a level not tuned yet borrows the other level's settings
        f = Path(__file__).with_name("fitted") / "mch_params.json"
    if f.exists():
        try:
            p.update(json.loads(f.read_text(encoding="utf-8")).get("params") or {})
        except (OSError, ValueError):
            pass
    return p


def context(level: str, refresh: bool = False) -> dict:
    if level in _CTX and not refresh:
        return _CTX[level]
    stores = load_stores(level)
    p = params(level)
    key = json.dumps({"p": p, "s": {s: [len(st["games"]), st.get("built_at")] for s, st in stores.items()}, "v": 3},
                     sort_keys=True)
    cp = cache_dir() / f"{level}_wf.pkl"
    preds = ends = None
    if cp.exists():
        try:
            with open(cp, "rb") as fh:
                c = pickle.load(fh)
            if c.get("key") == key:
                preds, ends = c["preds"], c["ends"]
        except Exception:  # noqa: BLE001
            preds = None
    if preds is None:
        preds, ends = M.walk_forward(sorted(stores), stores, p)
        cp.parent.mkdir(parents=True, exist_ok=True)
        with open(cp, "wb") as fh:
            pickle.dump({"key": key, "preds": preds, "ends": ends}, fh)
    by_id = {pr["id"]: pr for pr in preds}
    ctx = {"level": level, "stores": stores, "p": p, "preds": preds, "pred": by_id, "ends": ends, "bundles": {},
           "colours": colour_map()}
    _CTX[level] = ctx
    return ctx


# ── cards ──────────────────────────────────────────────────────────────────────────────────────────────────

def pregame(ctx: dict, s: int, g: dict) -> dict | None:
    """Our pregame forecast: the walk-forward prediction for a played game (ratings from games before its day), the
    latest ratings for a game still to play."""
    pr = ctx["pred"].get(g["id"])
    if pr is None:
        f = season_fit(ctx, s)
        if f is None or g.get("stype") == "exh":
            return None
        lh, la = f.means(g["home"], g["away"], bool(g.get("neutral")))
        o = M.outcome(lh, la, ctx["p"], post=M.postseason(g), season=s, ties_allowed=not M.postseason(g))
        pr = {"lh": lh, "la": la, **o}
    return {"p_home": r4(pr["p_home"]), "p_tie": r4(pr["p_tie"]), "p_away": r4(pr["p_away"]),
            "margin": r2(pr["lh"] - pr["la"]), "total": r2(pr["lh"] + pr["la"]), "xg_home": r2(pr["lh"]),
            "xg_away": r2(pr["la"])}


def card(ctx: dict, s: int, g: dict, compact: bool = False) -> dict:
    mdl = pregame(ctx, s, g)
    res = None
    if g.get("status") == "post" and g.get("res") in ("W", "L", "T") and mdl:
        pick = max((("W", mdl["p_home"]), ("T", mdl["p_tie"] or 0), ("L", mdl["p_away"])), key=lambda x: x[1])[0]
        fav = "W" if mdl["p_home"] >= mdl["p_away"] else "L"
        res = {"model_correct": None if g["res"] == "T" else (g["res"] == fav), "pick": pick}
    c = {"id": str(g["id"]), "season": s, "date": g.get("date"), "status": g.get("status"), "stype": g.get("stype"),
         "round": g.get("round"), "region": g.get("region"), "note": g.get("note"), "home": g["home"], "away": g["away"],
         "hs": g.get("hs"), "as": g.get("as"), "hr": g.get("hr"), "ar": g.get("ar"), "hseed": g.get("hseed"),
         "aseed": g.get("aseed"), "neutral": bool(g.get("neutral")), "conf_game": bool(g.get("conf_game")),
         "ot": g.get("ot") or None, "so": True if g.get("so") else None, "res": g.get("res"),
         "model": mdl if not compact else ({"p_home": mdl["p_home"], "p_tie": mdl["p_tie"], "p_away": mdl["p_away"]} if mdl else None),
         "result": res, "tba": True if (g.get("tba") and g.get("status") == "pre") else None}
    mk = (ctx.get("game_mk") or {}).get(g["id"]) if g.get("status") == "pre" and not compact else None
    if mk and mk.get("p_home") is not None:
        c["market"] = {"p_home": mk["p_home"], "source": "kalshi"}
    if not compact and g.get("status") == "in":
        c["period"] = None
    return slim(c)


def slim(c: dict) -> dict:
    return {k: v for k, v in c.items() if v is not None and not (v is False and k in ("neutral", "conf_game"))}


# ── season bundle ──────────────────────────────────────────────────────────────────────────────────────────

def season_fit(ctx: dict, s: int) -> M.Fit | None:
    b = ctx["bundles"].setdefault(s, {})
    if "fit" in b:
        return b["fit"]
    f = ctx["ends"].get(s)
    if f is None and s in ctx["stores"]:
        prev = ctx["ends"].get(s - 1)
        st = ctx["stores"][s]
        d1 = {t for t, v in st["teams"].items() if v.get("d1")}
        f = M.season_ratings(s, st["games"], d1, M.end_prior(prev, ctx["p"]["carry"]), ctx["p"])
    b["fit"] = f
    return f


def team_rec(ctx: dict, st: dict, t: str) -> dict:
    v = st["teams"].get(t) or {}
    col = ctx["colours"].get(str(v.get("espn_id") or t)) or HOCKEY_COLOURS.get(v.get("short") or "") or \
        HOCKEY_COLOURS.get(v.get("name") or "") or (None, None)
    name = v.get("name") or t
    short = v.get("short") or name
    abbr = v.get("abbr") or re.sub(r"[^A-Z]", "", short.upper())[:4] or short[:3].upper()
    return {"name": name, "short": short, "abbr": abbr, "colour": col[0], "alt_colour": col[1], "alt": col[1],
            "conference": v.get("conf"), "member": bool(v.get("d1"))}


def standings(ctx: dict, s: int) -> dict:
    """{cid: [row]}: W-L-T overall (NCAA record: shootouts are ties), conference record and points (3-2-1-0 from
    2021-22: 3 a regulation win, 2 an overtime or shootout win, 1 an overtime or shootout loss; 2-1-0 before),
    home / away / neutral, goals, streak, our rating rank, the poll rank."""
    st = ctx["stores"][s]
    teams = st["teams"]
    pts3 = s >= 2022
    rec = defaultdict(lambda: {"w": 0, "l": 0, "t": 0, "otw": 0, "otl": 0, "conf_w": 0, "conf_l": 0, "conf_t": 0, "conf_pts": 0,
                               "conf_gp": 0, "home": [0, 0, 0], "away": [0, 0, 0], "neutral": [0, 0, 0], "gf": 0, "ga": 0, "seq": []})
    for g in sorted((g for g in st["games"] if g.get("status") == "post" and g.get("res") in ("W", "L", "T")
                     and g.get("stype") != "exh"), key=lambda g: g["date"]):
        if g.get("stype") == "ncaa":
            pass
        for side, mine, theirs in (("home", g["hs"], g["as"]), ("away", g["as"], g["hs"])):
            t = g[side]
            if not (teams.get(t) or {}).get("d1"):
                continue
            r = rec[t]
            res = g["res"] if side == "home" else {"W": "L", "L": "W", "T": "T"}[g["res"]]
            ot = (g.get("ot") or 0) > 0 and res != "T"
            r[{"W": "w", "L": "l", "T": "t"}[res]] += 1
            if ot:
                r["otw" if res == "W" else "otl"] += 1
            v = "neutral" if g.get("neutral") else side
            r[v][{"W": 0, "L": 1, "T": 2}[res]] += 1
            r["gf"] += mine or 0
            r["ga"] += theirs or 0
            r["seq"].append(res)
            if g.get("conf_game") and g.get("stype") == "reg":
                r["conf_gp"] += 1
                r[{"W": "conf_w", "L": "conf_l", "T": "conf_t"}[res]] += 1
                if res == "W":
                    r["conf_pts"] += (2 if ot else 3) if pts3 else 2
                elif res == "L":
                    r["conf_pts"] += (1 if ot else 0) if pts3 else 0
                else:
                    r["conf_pts"] += (1.5 if pts3 else 1)
    f = season_fit(ctx, s)
    rank = rating_ranks(ctx, s)
    polls = latest_poll(st)
    out = defaultdict(list)
    for t, v in teams.items():
        if not v.get("d1"):
            continue
        r = rec[t]
        seq = r["seq"]
        streak = None
        if seq:
            k = 1
            while k < len(seq) and seq[-k - 1] == seq[-1]:
                k += 1
            streak = f"{seq[-1]}{k}"
        out[v.get("conf") or "ind"].append({"team": t, "w": r["w"], "l": r["l"], "t": r["t"], "otw": r["otw"], "otl": r["otl"],
                                            "conf_w": r["conf_w"], "conf_l": r["conf_l"], "conf_t": r["conf_t"],
                                            "conf_pts": r["conf_pts"], "conf_gp": r["conf_gp"],
                                            "home": r["home"], "away": r["away"], "neutral": r["neutral"],
                                            "gf": r["gf"], "ga": r["ga"], "streak": streak, "rank": polls.get(t),
                                            "rating_rank": rank.get(t), "conf_rank": None})
    for c, rows in out.items():
        rows.sort(key=lambda r: (-(r["conf_pts"] / max(r["conf_gp"], 1)) if c != "ind" else 0, -r["conf_pts"],
                                 -((r["w"] + 0.5 * r["t"]) / max(r["w"] + r["l"] + r["t"], 1)), r["rating_rank"] or 999))
        for i, r in enumerate(rows):
            r["conf_rank"] = i + 1
    return dict(out)


def latest_poll(st: dict) -> dict[str, int]:
    us = st.get("uscho") or {}
    if us:
        return {r["team"]: r["rank"] for r in us[sorted(us)[-1]]}
    pol = st.get("polls") or {}
    if not pol:
        return {}
    last = pol[sorted(pol)[-1]]
    for p in last:
        if "USCHO" in str(p.get("name") or "") or True:
            return {str(x["team"]): x["rank"] for x in p.get("ranks") or [] if x.get("rank")}
    return {}


def rating_ranks(ctx: dict, s: int) -> dict[str, int]:
    f = season_fit(ctx, s)
    st = ctx["stores"][s]
    if f is None:
        return {}
    d1 = [t for t, v in st["teams"].items() if v.get("d1")]
    order = sorted(d1, key=lambda t: -f.net(t))
    return {t: i + 1 for i, t in enumerate(order)}


def ratings(ctx: dict, s: int) -> dict:
    """RATING (hockey): rating (goals per game better than an average D-I team, neutral ice), off (goals scored above
    average), def (goals prevented below average; higher is better), se, rank, games, sos, sos_rank, luck (points
    share above expectation), plus CHN's shots and special teams where present."""
    st = ctx["stores"][s]
    f = season_fit(ctx, s)
    if f is None:
        return {}
    base = math.exp(f.mu)
    d1 = [t for t, v in st["teams"].items() if v.get("d1")]
    gp = Counter()
    opp_sum = defaultdict(float)
    exp_pts = defaultdict(float)
    act_pts = defaultdict(float)
    for g in st["games"]:
        if g.get("status") != "post" or g.get("res") not in ("W", "L", "T") or g.get("stype") == "exh":
            continue
        pr = ctx["pred"].get(g["id"])
        for side, o in (("home", "away"), ("away", "home")):
            t = g[side]
            gp[t] += 1
            opp_sum[t] += f.net(g[o])
            if pr:
                ph = pr["p_home"] if side == "home" else pr["p_away"]
                exp_pts[t] += ph + 0.5 * pr["p_tie"]
                res = g["res"] if side == "home" else {"W": "L", "L": "W", "T": "T"}[g["res"]]
                act_pts[t] += 1.0 if res == "W" else 0.5 if res == "T" else 0.0
    rk = rating_ranks(ctx, s)
    sos = {t: opp_sum[t] / gp[t] for t in d1 if gp[t]}
    sos_order = sorted(sos, key=lambda t: -sos[t])
    sos_rank = {t: i + 1 for i, t in enumerate(sos_order)}
    sh = special_teams(st)
    out = {}
    for t in d1:
        a, d = f.rating(t)
        n = gp[t]
        se = 0.55 / math.sqrt(max(n, 1) + 6)
        out[t] = {"rating": r2(f.net(t)), "off": r2(base * (math.exp(a) - 1)), "def": r2(base * (1 - math.exp(-d))),
                  "att": r3(a), "dfn": r3(d), "se": r2(se), "rank": rk.get(t), "games": n,
                  "sos": r2(sos.get(t)), "sos_rank": sos_rank.get(t),
                  "luck": r3((act_pts[t] - exp_pts[t]) / n) if n else None, **(sh.get(t) or {})}
    return out


def special_teams(st: dict) -> dict[str, dict]:
    """Shots for / against per game, shot share, PP% and PK%, PIM per game, shooting and save percentages, from
    CHN's game-by-game lines (CHN on only)."""
    if not chn_on(st):
        return {}
    acc = defaultdict(lambda: defaultdict(float))
    for g in st["games"]:
        cb = g.get("chn") or {}
        if g.get("status") != "post" or not cb.get("sh") or g.get("stype") == "exh":
            continue
        sh, pp = cb.get("sh") or [None, None], cb.get("pp") or [[None, None], [None, None]]
        if None in sh:
            continue
        for k, t in enumerate((g["home"], g["away"])):
            o = 1 - k
            a = acc[t]
            a["n"] += 1
            a["sf"] += sh[k]
            a["sa"] += sh[o]
            gf = g["hs"] if k == 0 else g["as"]
            ga = g["as"] if k == 0 else g["hs"]
            a["gf"] += gf or 0
            a["ga"] += ga or 0
            if pp[k][0] is not None and pp[k][1] is not None:
                a["ppg"] += pp[k][0]
                a["ppo"] += pp[k][1]
            if pp[o][0] is not None and pp[o][1] is not None:
                a["ppga"] += pp[o][0]
                a["tsh"] += pp[o][1]
            pim = (cb.get("pim") or [None, None])[k]
            if pim is not None:
                a["pim"] += pim
                a["pim_n"] += 1
            xg = cb.get("xg")
            if xg and xg[k] is not None and xg[o] is not None:
                a["xgf"] += xg[k]
                a["xga"] += xg[o]
                a["xg_n"] += 1
    out = {}
    for t, a in acc.items():
        n = a["n"]
        if n < 1:
            continue
        d = {"sf_pg": r2(a["sf"] / n), "sa_pg": r2(a["sa"] / n), "shot_share": r4(a["sf"] / max(a["sf"] + a["sa"], 1)),
             "sh_pct": r4(a["gf"] / max(a["sf"], 1)), "sv_pct": r4(1 - a["ga"] / max(a["sa"], 1)),
             "pdo": r3(a["gf"] / max(a["sf"], 1) + 1 - a["ga"] / max(a["sa"], 1))}
        if a["ppo"]:
            d["pp_pct"] = r4(a["ppg"] / a["ppo"])
            d["ppo_pg"] = r2(a["ppo"] / n)
        if a["tsh"]:
            d["pk_pct"] = r4(1 - a["ppga"] / a["tsh"])
            d["tsh_pg"] = r2(a["tsh"] / n)
        if a["pim_n"]:
            d["pim_pg"] = r2(a["pim"] / a["pim_n"])
        if a["xg_n"] >= 3:
            d["chn_xgf_pg"] = r2(a["xgf"] / a["xg_n"])
            d["chn_xga_pg"] = r2(a["xga"] / a["xg_n"])
            d["chn_xg_share"] = r4(a["xgf"] / max(a["xgf"] + a["xga"], 1e-9))
        out[t] = d
    return out


def rating_paths(ctx: dict, s: int) -> dict[str, list]:
    """Weekly net rating per team from the walk-forward fits (the rating each Monday, from games before it)."""
    st = ctx["stores"][s]
    d1 = {t for t, v in st["teams"].items() if v.get("d1")}
    games = [g for g in st["games"] if g.get("status") == "post" and g.get("stype") != "exh"]
    if len(games) < 30:
        return {}
    days = sorted({M.game_day(g) for g in games})
    d0 = days[0]
    end = days[-1] + 1                                   # the day after the last game played
    mondays = [m for m in range(d0 + 6, end, 7)] + [end]
    prior = M.end_prior(ctx["ends"].get(s - 1), ctx["p"]["carry"])
    rows = []
    for g in games:
        rh, ra = M.regulation_goals(g)
        if rh is not None:
            rows.append((M.game_day(g), g["home"], g["away"], bool(g.get("neutral")), rh, ra))
    rows.sort()
    out = defaultdict(list)
    f = None
    for m in mondays:
        sub = [r for r in rows if r[0] < m]
        f = M.fit(sub, m, prior, ctx["p"], d1, init=f, iters=5 if f is not None else 8)
        ds = date.fromordinal(m).isoformat()
        for t in d1:
            out[t].append([ds, r2(f.net(t))])
    return dict(out)


def bundle(ctx: dict, s: int) -> dict:
    b = ctx["bundles"].setdefault(s, {})
    if b.get("done"):
        return b
    b["standings"] = standings(ctx, s)
    b["ratings"] = ratings(ctx, s)
    b["rows"] = P.season_rows(ctx["stores"][s]) if chn_on(ctx["stores"][s]) else {}
    b["done"] = True
    return b


# ── selection numbers ──────────────────────────────────────────────────────────────────────────────────────

def selection(ctx: dict, s: int) -> dict:
    """Our NPI (2025-26 on) or PairWise (RPI and comparisons) on the games played before the NCAA tournament."""
    b = ctx["bundles"].setdefault(s, {})
    if "selection" not in b:
        b["selection"] = _selection(ctx, s)
    return b["selection"]


def _selection(ctx: dict, s: int) -> dict:
    st = ctx["stores"][s]
    d1 = {t for t, v in st["teams"].items() if v.get("d1")}
    first_ncaa = min((g["date"][:10] for g in st["games"] if g.get("stype") == "ncaa"), default=None)
    games = [g for g in st["games"] if not first_ncaa or g["date"][:10] < first_ncaa]
    if s >= 2026:
        v = N.npi(games, d1, s, level=ctx["level"])
        rows = sorted(({"team": t, "npi": x["npi"], "rank": x["rank"], "wwp": x["wwp"], "w": x["w"], "l": x["l"], "t": x["t"]}
                       for t, x in v.items()), key=lambda r: r["rank"])
        return {"kind": "npi", "label": "NPI", "rows": rows, "through": first_ncaa}
    r = N.rpi(games, d1, s)
    pw = N.pairwise(games, d1, s, r=r)
    rows = sorted(({"team": t, "pwr": x["pwr"], "pcw": x["pcw"], "rpi": x["rpi"], "rank": x["rank"], "w": x["w"],
                    "l": x["l"], "t": x["t"]} for t, x in pw.items()), key=lambda r: r["rank"])
    return {"kind": "pairwise", "label": "PairWise", "rows": rows, "through": first_ncaa}


# ── NCAA tournament: the actual bracket from the season's games ────────────────────────────────────────────

def reached(act: dict, level: str) -> dict[str, str]:
    """The furthest NCAA round each team reached: Field (lost its first game), QF (men: lost the regional final;
    women: lost the quarterfinal), F4, Final, Champion."""
    out = {t: "Field" for t in act["teams"]}
    for g in act["games"]:
        rd = g.get("round") or ""
        for t in (g["home"], g["away"]):
            if rd in ("Regional final", "Quarterfinal"):
                out[t] = max(out[t], "QF", key=ROUND_ORDER.get)
            elif rd == "Frozen Four":
                out[t] = max(out[t], "F4", key=ROUND_ORDER.get)
            elif rd == "Final":
                out[t] = max(out[t], "Final", key=ROUND_ORDER.get)
    if act.get("champion"):
        out[act["champion"]] = "Champion"
    return out


ROUND_ORDER = {"Field": 0, "QF": 1, "F4": 2, "Final": 3, "Champion": 4}


def actual_ncaa(ctx: dict, s: int) -> dict | None:
    st = ctx["stores"][s]
    games = [g for g in st["games"] if g.get("stype") == "ncaa"]
    if not games:
        return None
    level = ctx["level"]
    teams = set()
    for g in games:
        teams.update((g["home"], g["away"]))
    out = {"games": sorted(games, key=lambda g: g["date"]), "teams": sorted(teams)}
    fin = [g for g in games if (g.get("round") or "") == "Final" and g.get("status") == "post"]
    if fin:
        g = fin[-1]
        w = g["home"] if (g.get("hs") or 0) > (g.get("as") or 0) else g["away"]
        out["champion"] = w
        out["runner_up"] = g["away"] if w == g["home"] else g["home"]
        out["final"] = g
    ff = [g for g in games if (g.get("round") or "") == "Frozen Four"]
    out["frozen_four"] = sorted({t for g in ff for t in (g["home"], g["away"])})
    if level == "mch":
        regs = defaultdict(list)
        for g in games:
            if g.get("region"):
                regs[g["region"]].append(g)
        out["regions"] = {k: sorted(v, key=lambda g: g["date"]) for k, v in regs.items()}
    return out


# ── payload builders: season ───────────────────────────────────────────────────────────────────────────────

def phase(ctx: dict, s: int) -> str:
    st = ctx["stores"][s]
    if s < current_season(ctx["level"]):
        return "offseason"
    gs = [g for g in st["games"] if g.get("stype") != "exh"]
    if not any(g.get("status") in ("post", "in") for g in gs):
        return "preseason"
    nc = [g for g in gs if g.get("stype") == "ncaa"]
    if nc and any(g.get("status") in ("post", "in") for g in nc):
        fin = [g for g in nc if (g.get("round") or "") == "Final" and g.get("status") == "post"]
        return "offseason" if fin else "ncaa"
    if any(g.get("stype") == "conf" and g.get("status") in ("post", "in") for g in gs):
        return "conf_tourneys"
    return "regular"


def season_sim(ctx: dict, s: int, sims: int) -> dict | None:
    """The simulation for the current season (from today); for a finished season the actual results with our
    pre-tournament chances through the actual bracket."""
    b = bundle(ctx, s)
    if "sim" in b:
        return b["sim"]
    st = ctx["stores"][s]
    level = ctx["level"]
    out = None
    f = season_fit(ctx, s)
    if f is None:
        b["sim"] = None
        return None
    if s >= current_season(level) and phase(ctx, s) not in ("offseason",):
        cx = SIM.Ctx(st, f, ctx["p"], s)
        res = SIM.simulate(cx, level, n=max(1000, sims), seed=s)
        out = {"kind": "full", "teams": res["teams"], "n": res["n_sims"], "format": res["format"],
               "selection": res["selection"],
               "notes": ["Season simulation from today's ratings, with the uncertainty in each rating carried into every run.",
                         "Conference tournaments are generic and approximate: every member, single elimination seeded by the "
                         "simulated standings, the higher seed at home until the semifinals (real formats differ by conference "
                         "and are not in a free feed).",
                         ("Selection by our replica of the NPI (it matches the published NPI); " if s >= 2026 else
                          "Selection by the RPI as a proxy for the PairWise; ") +
                         "regional hosts and the committee's swaps to avoid first-round conference games are not modelled."]}
    else:
        act = actual_ncaa(ctx, s)
        pre = pre_tournament_odds(ctx, s, act) if act else {}
        tm = {}
        stand = b["standings"]
        champs = conf_champions(ctx, s)
        reg = {c: rows[0]["team"] for c, rows in stand.items() if rows and c != "ind" and rows[0]["conf_gp"]}
        for c, rows in stand.items():
            for r in rows:
                t = r["team"]
                inn = act and t in act["teams"]
                o = pre.get(t) or {}
                tm[t] = {"exp_w": r["w"], "exp_l": r["l"], "exp_t": r["t"], "p_conf_reg": 1.0 if reg.get(c) == t else 0.0,
                         "p_conf_tourney": 1.0 if champs.get(c) == t else 0.0, "p_ncaa": 1.0 if inn else 0.0,
                         "p_qf": o.get("p_qf", 0.0), "p_f4": o.get("p_f4", 0.0), "p_final": o.get("p_final", 0.0),
                         "p_title": o.get("p_title", 0.0), "pre_tournament": bool(o)}
        out = {"kind": "final", "teams": tm, "n": 20000 if pre else 0, "format": SIM.field_format(level, s),
               "notes": ["Finished season: records, conference titles and the NCAA field are as played; the tournament "
                         "chances are ours before it started (ratings from games before the first NCAA game), through the "
                         "actual bracket."] if pre else ["Finished season: results as played."]}
    b["sim"] = out
    return out


def conf_champions(ctx: dict, s: int) -> dict[str, str]:
    """{conf: tournament champion} from the last conference-tournament final of each conference."""
    st = ctx["stores"][s]
    by = defaultdict(list)
    for g in st["games"]:
        if g.get("stype") != "conf" or g.get("status") != "post" or g.get("res") not in ("W", "L"):
            continue
        c = st["teams"].get(g["home"], {}).get("conf")
        if c and c == st["teams"].get(g["away"], {}).get("conf"):
            by[c].append(g)
    out = {}
    for c, gs in by.items():
        last = max(gs, key=lambda g: g["date"])
        out[c] = last["home"] if last["res"] == "W" else last["away"]
    return out


def ncaa_seeding(ctx: dict, s: int, act: dict) -> dict:
    """Regions with seeds from the actual NCAA games: men, the regional semifinal pairs (1 v 4, 2 v 3) ordered by
    our pre-tournament selection ranking within the region; women, the overall seed order by that ranking (the
    first-round and quarterfinal pairings fix the bands)."""
    sel = selection(ctx, s)
    order = [r["team"] for r in sel["rows"]]
    rk = {t: i for i, t in enumerate(order)}
    level = ctx["level"]
    if level == "mch":
        regs = {}
        for name, gs in (act.get("regions") or {}).items():
            ts = sorted({t for g in gs for t in (g["home"], g["away"])}, key=lambda t: rk.get(t, 999))
            if len(ts) == 4:
                semis = [g for g in gs if (g.get("round") or "") == "Regional semifinal"]
                top = ts[0]
                opp = next((g["away"] if g["home"] == top else g["home"] for g in semis if top in (g["home"], g["away"])), ts[3])
                rest = [t for t in ts if t not in (top, opp)]
                regs[name] = [(1, top), (2, rest[0]), (3, rest[1]), (4, opp)]
        # Frozen Four pairs: the regions whose winners met
        ff = [g for g in act["games"] if (g.get("round") or "") == "Frozen Four"]
        names = list(regs)
        reg_of = {t: n for n, v in regs.items() for _, t in v}
        if len(ff) == 2 and len(names) == 4:
            a = [reg_of.get(ff[0]["home"]), reg_of.get(ff[0]["away"])]
            bb = [reg_of.get(ff[1]["home"]), reg_of.get(ff[1]["away"])]
            if None not in a + bb:
                names = [a[0], bb[0], bb[1], a[1]]
        return {"regions": {n: regs[n] for n in names if n in regs}}
    ts = sorted(act["teams"], key=lambda t: rk.get(t, 999))
    return {"seeds": ts}


def pre_tournament_odds(ctx: dict, s: int, act: dict) -> dict:
    """Our chances before the NCAA tournament (ratings fitted on games before its first day) through the actual bracket."""
    st = ctx["stores"][s]
    level = ctx["level"]
    first = min(g["date"][:10] for g in act["games"])
    d1 = {t for t, v in st["teams"].items() if v.get("d1")}
    prior = M.end_prior(ctx["ends"].get(s - 1), ctx["p"]["carry"])
    f = M.season_ratings(s, st["games"], d1, prior, ctx["p"], through_day=date.fromisoformat(first).toordinal())
    cx = SIM.Ctx(st, f, ctx["p"], s)
    seeding = ncaa_seeding(ctx, s, act)
    fmt = SIM.field_format(level, s)
    if level == "mch":
        regs = seeding.get("regions") or {}
        if len(regs) != 4:
            return {}
        return SIM.bracket_odds(cx, level, regs, n=20000, seed=s)
    seeds = seeding.get("seeds") or []
    if len(seeds) != fmt["field"]:
        return {}
    return SIM.bracket_odds(cx, level, {"seeds": seeds}, n=20000, seed=s)


def season_payload(ctx: dict, s: int, sims: int) -> dict:
    lv = ctx["level"]
    st = ctx["stores"][s]
    b = bundle(ctx, s)
    confs = {}
    for c, v in st["conferences"].items():
        ts = sorted(t for t, x in st["teams"].items() if x.get("d1") and x.get("conf") == c)
        if ts:
            confs[c] = {"name": v.get("name"), "short": v.get("short"), "teams": ts}
    used = {g[k] for g in st["games"] for k in ("home", "away")}
    teams = {t: team_rec(ctx, st, t) for t, v in st["teams"].items() if v.get("d1") or t in used}
    R = b["ratings"]
    power = sorted(({"rank": v["rank"], "team": t, "rating": v["rating"]} for t, v in R.items() if v.get("rank")),
                   key=lambda r: r["rank"])
    paths = rating_paths(ctx, s)
    prev = {}
    for t, pth in paths.items():
        if len(pth) >= 2:
            prev[t] = pth[-2][1]
    if prev:
        order = sorted(prev, key=lambda t: -(prev[t] or -99))
        prk = {t: i + 1 for i, t in enumerate(order)}
        for r in power:
            r["prev_rank"] = prk.get(r["team"])
    sim = season_sim(ctx, s, sims)
    sel = selection(ctx, s)
    leaders = {}
    rows = b["rows"]
    if rows:
        gmax = max((r["gp"] for r in rows.values()), default=1)
        sk = [r for r in rows.values() if r["pos"] != "G" and P.qualified(r, gmax)]
        gk = [r for r in rows.values() if r["pos"] == "G" and P.qualified(r, gmax)]
        for k in ("pts", "g", "a", "gar", "pts_pg"):
            leaders[k] = [[r["id"], r["team"], r.get(k)] for r in sorted(sk, key=lambda r: -(r.get(k) or 0))[:10]]
        leaders["sv_pct"] = [[r["id"], r["team"], r.get("sv_pct")] for r in sorted(gk, key=lambda r: -(r.get("sv_pct") or 0))[:10]]
        leaders["gsaa"] = [[r["id"], r["team"], r.get("gsaa")] for r in sorted(gk, key=lambda r: -(r.get("gsaa") or 0))[:10]]
    polls = {}
    pol = st.get("polls") or {}
    if pol:
        last_key = sorted(pol)[-1]
        prev_key = sorted(pol)[-2] if len(pol) > 1 else None
        for p in pol[last_key]:
            nm = str(p.get("name") or "poll")
            prevmap = {}
            if prev_key:
                for pp in pol[prev_key]:
                    if pp.get("name") == p.get("name"):
                        prevmap = {x["team"]: x["rank"] for x in pp.get("ranks") or []}
            polls["uscho" if "USCHO" in nm else re.sub(r"[^a-z]+", "_", nm.lower())] = [
                {"rank": x["rank"], "team": x["team"], "points": x.get("points"), "first": x.get("fpv"),
                 "prev": x.get("prev") or prevmap.get(x["team"]), "record": x.get("record")} for x in p.get("ranks") or []]
        polls["as_of"] = last_key
    us = st.get("uscho") or {}
    if us:                                   # USCHO's own pages (sources/uscho.py): every week, history included
        last = sorted(us)[-1]
        polls = {"uscho": [{"rank": r["rank"], "team": r["team"], "points": r.get("points"), "first": r.get("first"),
                            "prev": r.get("prev"), "record": r.get("record")} for r in us[last]],
                 "as_of": last, "source": "USCHO"}
    f = season_fit(ctx, s)
    return {"ok": True, "level": lv, "season": s, "updated_at": now_iso(), "phase": phase(ctx, s), "week": None,
            "fmt": FORMAT, "sport": "hockey", "chn": chn_on(st),
            "format": {"ncaa": SIM.field_format(lv, s)},
            "conferences": confs, "teams": teams, "standings": b["standings"], "ratings": R, "rating_paths": paths,
            "polls": polls, "power": power,
            "sim": {"n_sims": sim["n"], "kind": sim["kind"], "teams": sim["teams"], "notes": sim["notes"],
                    "selection": sim.get("selection")} if sim else None,
            "selection": {k: sel[k] for k in ("kind", "label", "through")} | {"rows": sel["rows"]},
            "leaders": leaders,
            "model": {"hfa_goals": r2(math.exp(f.mu) * (math.exp(f.hfa) - 1)) if f else None,
                      "goals_pg": r2(math.exp(f.mu)) if f else None, "games": f.n if f else 0}}


def schedule_payload(ctx: dict, s: int) -> dict:
    st = ctx["stores"][s]
    arch = s < current_season(ctx["level"])
    cards = [card(ctx, s, g, compact=arch) for g in st["games"] if g.get("stype") != "exh" or not arch]
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(), "games": PK.pack(cards),
            "compact": arch}


ROUNDS = {"mch": ["Field", "QF", "F4", "Final", "Champion"], "wch": ["Field", "QF", "F4", "Final", "Champion"]}


def bracket_payload(ctx: dict, s: int, sims: int) -> dict:
    lv = ctx["level"]
    st = ctx["stores"][s]
    sim = season_sim(ctx, s, sims)
    act = actual_ncaa(ctx, s)
    fmt = SIM.field_format(lv, s)
    sel = selection(ctx, s)
    odds = {}
    for t, v in ((sim or {}).get("teams") or {}).items():
        if (v.get("p_ncaa") or 0) <= 0:
            continue
        odds[t] = {"p_round": {"Field": v.get("p_ncaa"), "QF": v.get("p_qf"), "F4": v.get("p_f4"), "Final": v.get("p_final"),
                               "Champion": v.get("p_title")}, "seed_mean": v.get("seed_mean"), "seed_dist": v.get("seed_dist"),
                   "p_auto": v.get("p_auto"), "p_at_large": v.get("p_at_large")}
    actual = None
    if act:
        seeding = ncaa_seeding(ctx, s, act)
        reach = reached(act, lv)
        seed_of, reg_of = {}, {}
        for n_, v in (seeding.get("regions") or {}).items():
            for sd, t in v:
                seed_of[t], reg_of[t] = sd, n_
        for i, t in enumerate(seeding.get("seeds") or []):
            seed_of[t] = i + 1
        for t in act["teams"]:
            o = odds.setdefault(t, {"p_round": {}})
            o["seed"] = seed_of.get(t)
            o["region"] = reg_of.get(t)
            o["reached"] = reach.get(t)
        actual = {"games": [card(ctx, s, g) for g in act["games"]], "champion": act.get("champion"),
                  "runner_up": act.get("runner_up"), "frozen_four": act.get("frozen_four")}
        if lv == "mch":
            actual["regions"] = {n: [{"seed": sd, "team": t} for sd, t in v] for n, v in (seeding.get("regions") or {}).items()}
        else:
            actual["seeds"] = [{"seed": i + 1, "team": t} for i, t in enumerate(seeding.get("seeds") or [])]
    projected = None
    if sim and sim["kind"] == "full":
        # the modal field: the most likely teams by P(field), ordered by mean seed
        cand = sorted(((t, v) for t, v in sim["teams"].items() if (v.get("p_ncaa") or 0) > 0),
                      key=lambda kv: -(kv[1].get("p_ncaa") or 0))[: fmt["field"]]
        cand.sort(key=lambda kv: kv[1].get("seed_mean") or 99)
        field = [t for t, _ in cand]
        if lv == "mch" and len(field) == 16:
            conf_of = {t: st["teams"][t].get("conf") for t in field}
            br = N.seed_bracket(field, conf_of, regions=["Region 1", "Region 2", "Region 3", "Region 4"])
            projected = {"regions": {n: [{"seed": sd, "team": t, "p": sim["teams"][t].get("p_ncaa")} for sd, t in v]
                                     for n, v in br["regions"].items()},
                         "note": "Projected: the sixteen likeliest teams in the field, ordered by their average simulated seed "
                                 "and placed in bands of four (regional sites and hosts not placed)."}
        elif len(field) == fmt["field"]:
            projected = {"seeds": [{"seed": i + 1, "team": t, "p": sim["teams"][t].get("p_ncaa")} for i, t in enumerate(field)],
                         "note": "Projected: the likeliest field, ordered by average simulated seed."}
        bub = sorted(((t, v) for t, v in sim["teams"].items() if 0.03 < (v.get("p_ncaa") or 0) < 0.97),
                     key=lambda kv: -(kv[1].get("p_ncaa") or 0))
        projected = projected or {}
        projected["bubble"] = [{"team": t, "p": r4(v.get("p_ncaa")), "p_auto": r4(v.get("p_auto")),
                                "sel_rank": v.get("sel_rank_mean")} for t, v in bub[:24]]
    ct = conf_tourney_payload(ctx, s, sim)
    return {"ok": True, "season": s, "level": lv, "updated_at": now_iso(), "field": fmt["field"], "format": fmt,
            "rounds": ROUNDS[lv], "actual": actual, "projected": projected, "odds": odds,
            "selection": {"kind": sel["kind"], "label": sel["label"], "through": sel["through"], "rows": sel["rows"][:40]},
            "conf_tourneys": ct, "notes": (sim or {}).get("notes") or []}


def conf_tourney_payload(ctx: dict, s: int, sim: dict | None) -> dict:
    st = ctx["stores"][s]
    out = {}
    by = defaultdict(list)
    for g in st["games"]:
        if g.get("stype") == "conf":
            c = st["teams"].get(g["home"], {}).get("conf")
            by[c].append(g)
    for c in st["conferences"]:
        if c in ("ind",):
            continue
        rows = []
        for t, v in ((sim or {}).get("teams") or {}).items():
            if st["teams"].get(t, {}).get("conf") == c:
                rows.append({"team": t, "p_win": v.get("p_conf_tourney"), "p_reg": v.get("p_conf_reg")})
        rows.sort(key=lambda r: -(r["p_win"] or 0))
        gs = sorted(by.get(c, []), key=lambda g: g["date"])
        if rows or gs:
            out[c] = {"teams": rows, "approximate": True, "games": [card(ctx, s, g) for g in gs]}
    return out


def team_metrics() -> list[tuple]:
    return [("rating", "Rating", "Our ratings", "signed2", False, "Goals per game better than an average D-I team on neutral ice (our team rating model)"),
            ("off", "Offence", "Our ratings", "signed2", False, "Goals scored per game above an average team, against average defences"),
            ("def", "Defence", "Our ratings", "signed2", False, "Goals prevented per game below an average team, against average attacks (higher is better)"),
            ("sos", "Schedule", "Our ratings", "signed2", False, "Average rating of the opponents played"),
            ("gf_pg", "Goals for", "Results", "2", False, "Goals scored per game"),
            ("ga_pg", "Goals against", "Results", "2", True, "Goals allowed per game"),
            ("wpct", "Points %", "Results", "pct", False, "Share of the available points: a win 1, a tie a half"),
            ("sf_pg", "Shots for", "Shots", "1", False, "Shots on goal per game (CHN)"),
            ("sa_pg", "Shots against", "Shots", "1", True, "Shots on goal allowed per game (CHN)"),
            ("shot_share", "Shot share", "Shots", "pct", False, "Share of the game's shots on goal taken by the team (CHN)"),
            ("sh_pct", "Shooting %", "Shots", "pct", False, "Goals per shot on goal"),
            ("sv_pct", "Save %", "Shots", "pct", False, "Saves per shot on goal faced"),
            ("pdo", "PDO", "Shots", "3", False, "Shooting % plus save %: far above 1.000 is usually luck that fades"),
            ("pp_pct", "Power play", "Special teams", "pct", False, "Power-play goals per opportunity (CHN)"),
            ("pk_pct", "Penalty kill", "Special teams", "pct", False, "Penalties killed off per time shorthanded (CHN)"),
            ("ppo_pg", "PP chances", "Special teams", "2", False, "Power plays drawn per game"),
            ("tsh_pg", "Times shorthanded", "Special teams", "2", True, "Penalties taken that gave the opponent a power play, per game"),
            ("pim_pg", "PIM", "Special teams", "1", True, "Penalty minutes per game"),
            ("chn_xg_share", "CHN xG share", "Shots", "pct", False, "College Hockey News's own expected-goals share (theirs, not ours; men's recent seasons)"),
            ("luck", "Luck", "Results", "signed3", False, "Points per game above what our pregame chances expected")]


def team_values(ctx: dict, s: int) -> dict[str, dict]:
    b = bundle(ctx, s)
    out = {}
    stand = {r["team"]: r for rows in b["standings"].values() for r in rows}
    for t, rt in b["ratings"].items():
        r = stand.get(t) or {}
        gp = (r.get("w") or 0) + (r.get("l") or 0) + (r.get("t") or 0)
        v = {"rating": rt.get("rating"), "off": rt.get("off"), "def": rt.get("def"), "sos": rt.get("sos"), "luck": rt.get("luck"),
             "gf_pg": r3(r.get("gf", 0) / gp) if gp else None, "ga_pg": r3(r.get("ga", 0) / gp) if gp else None,
             "wpct": r4((r.get("w", 0) + 0.5 * r.get("t", 0)) / gp) if gp else None}
        for k in ("sf_pg", "sa_pg", "shot_share", "sh_pct", "sv_pct", "pdo", "pp_pct", "pk_pct", "ppo_pg", "tsh_pg", "pim_pg",
                  "chn_xg_share"):
            if rt.get(k) is not None:
                v[k] = rt[k]
        out[t] = v
    return out


def _pcts(vals: dict[str, dict], metrics: list[tuple]) -> dict[str, dict]:
    out = defaultdict(dict)
    for k, _l, _g, _f, lower, _d in metrics:
        xs = {t: v.get(k) for t, v in vals.items() if isinstance(v.get(k), (int, float))}
        if len(xs) < 8:
            continue
        arr = np.array(sorted(xs.values()))
        n = len(arr)
        for t, x in xs.items():
            p = 100.0 * np.searchsorted(arr, x, side="right") / n
            out[t][k] = round(100.0 - p + 100.0 / n if lower else p, 1)
    return out


def _metric(k, label, group, fmt, lower, desc):
    return {"key": k, "label": label, "group": group, "fmt": fmt, "lower": lower, "desc": desc}


def teams_payload(ctx: dict, s: int) -> dict:
    st = ctx["stores"][s]
    b = bundle(ctx, s)
    vals = team_values(ctx, s)
    mets = team_metrics()
    pct = _pcts(vals, mets)
    stand = {r["team"]: r for rows in b["standings"].values() for r in rows}
    out = {}
    for t, v in vals.items():
        r = stand.get(t) or {}
        out[t] = {"name": st["teams"][t].get("short"), "conference": st["teams"][t].get("conf"), "w": r.get("w"), "l": r.get("l"),
                  "t": r.get("t"), "rating_rank": b["ratings"][t].get("rank"),
                  "values": {k: x for k, x in v.items() if x is not None}, "pct": pct.get(t, {})}
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(),
            "metrics": [_metric(*m) for m in mets], "teams": out}


# ── players ────────────────────────────────────────────────────────────────────────────────────────────────

SKATER_METRICS = [
    ("gar", "GAR", "Our value", "1", False, "Goals above replacement: our value model (goals created, a damped on-ice +/- share, penalties, faceoffs)"),
    ("gar_pg", "GAR / game", "Our value", "3", False, "Goals above replacement per game"),
    ("war", "WAR", "Our value", "2", False, "Wins above replacement: GAR / 6"),
    ("gar_off", "Offence GAR", "Our value", "1", False, "Goals created above replacement"),
    ("gp", "GP", "Scoring", "int", False, "Games played"),
    ("g", "G", "Scoring", "int", False, "Goals"), ("a", "A", "Scoring", "int", False, "Assists"),
    ("pts", "PTS", "Scoring", "int", False, "Points"),
    ("pts_pg", "PTS / game", "Scoring", "2", False, "Points per game"), ("g_pg", "G / game", "Scoring", "2", False, "Goals per game"),
    ("a_pg", "A / game", "Scoring", "2", False, "Assists per game"),
    ("p1_pg", "Primary pts / game", "Scoring", "2", False, "Goals and first assists per game (box scores, 2025 on)"),
    ("a1", "First assists", "Scoring", "int", False, "Primary assists (box scores, 2025 on)"),
    ("ppg", "PP goals", "Scoring", "int", False, "Power-play goals"), ("shg", "SH goals", "Scoring", "int", False, "Shorthanded goals"),
    ("gwg", "GWG", "Scoring", "int", False, "Game-winning goals"),
    ("pt_share", "Share of team goals", "Scoring", "pct", False, "Points as a share of the team's goals"),
    ("sh", "Shots", "Shooting", "int", False, "Shots on goal"), ("sh_pg", "Shots / game", "Shooting", "2", False, "Shots on goal per game"),
    ("sh_pct", "Shooting %", "Shooting", "pct", False, "Goals per shot on goal"),
    ("tsa_pg", "Attempts / game", "Shooting", "2", False, "Shot attempts per game: on goal, missed or blocked (CHN, men from 2013-14)"),
    ("ev_tsa_pg", "EV attempts / game", "Shooting", "2", False, "Even-strength shot attempts per game"),
    ("on_net", "On net", "Shooting", "pct", False, "Share of attempts that reach the goalie"),
    ("toi_pg", "TOI", "Usage", "1", False, "Minutes a game (men's box scores, 2025 on)"),
    ("p60", "PTS / 60", "Usage", "2", False, "Points per 60 minutes on ice (men, 2025 on)"),
    ("g60", "G / 60", "Usage", "2", False, "Goals per 60 minutes on ice"),
    ("sh60", "Shots / 60", "Usage", "2", False, "Shots on goal per 60 minutes on ice"),
    ("pm", "+/-", "On ice", "signed1", False, "Plus-minus: even-strength and shorthanded goals for minus against while on the ice"),
    ("pm_rel", "+/- v team", "On ice", "signed1", False, "+/- relative to the team's goal difference for the player's games"),
    ("blk_pg", "Blocks / game", "Defence", "2", False, "Opponent shots blocked per game (men from 2013-14)"),
    ("fo_pct", "Faceoff %", "Faceoffs", "pct", False, "Faceoffs won (centres)"), ("fo_n", "Faceoffs", "Faceoffs", "int", False, "Faceoffs taken"),
    ("pim", "PIM", "Discipline", "int", True, "Penalty minutes"), ("pim_pg", "PIM / game", "Discipline", "2", True, "Penalty minutes per game"),
]
GOALIE_METRICS = [
    ("gar", "GAR", "Our value", "1", False, "Goals above replacement: goals saved above average (shrunk) plus the replacement margin"),
    ("gar_pg", "GAR / game", "Our value", "3", False, "Goals above replacement per game"),
    ("war", "WAR", "Our value", "2", False, "Wins above replacement"),
    ("gsaa", "GSAA", "Goaltending", "signed1", False, "Goals saved above an average goalie on the shots faced"),
    ("sv_pct", "SV%", "Goaltending", "3", False, "Save percentage"), ("gaa", "GAA", "Goaltending", "2", True, "Goals against per 60 minutes"),
    ("sv_above", "SV% above avg", "Goaltending", "signed3", False, "Save percentage above the league's"),
    ("sa60", "Shots faced / 60", "Workload", "1", False, "Shots on goal faced per 60 minutes"),
    ("sa", "Shots faced", "Workload", "int", False, "Shots on goal faced"), ("min", "Minutes", "Workload", "int", False, "Minutes played"),
    ("gp", "GP", "Workload", "int", False, "Games played"), ("so", "Shutouts", "Goaltending", "int", False, "Shutouts"),
]
PCT_KEYS = {
    "S": [("gar_pg", False), ("pts_pg", False), ("g_pg", False), ("a_pg", False), ("sh_pg", False), ("sh_pct", False),
          ("p1_pg", False), ("toi_pg", False), ("p60", False), ("pm_rel", False), ("tsa_pg", False), ("pim_pg", True),
          ("gar", False), ("pts", False), ("g", False), ("a", False), ("blk_pg", False), ("fo_pct", False), ("war", False),
          ("g60", False), ("sh60", False), ("ev_tsa_pg", False), ("on_net", False), ("pt_share", False), ("gar_off", False)],
    "G": [("gar", False), ("gar_pg", False), ("gsaa", False), ("sv_pct", False), ("gaa", True), ("sa60", False), ("war", False),
          ("sv_above", False)],
}
PCT_KEYS["F"] = PCT_KEYS["S"]
PCT_KEYS["D"] = PCT_KEYS["S"]


def all_metrics() -> list[tuple]:
    seen, out = set(), []
    for m in SKATER_METRICS + GOALIE_METRICS:
        if m[0] not in seen:
            seen.add(m[0])
            out.append(m)
    return out


def player_rows(ctx: dict, s: int) -> dict:
    b = bundle(ctx, s)
    rows = b["rows"]
    if rows and "pct_done" not in b:
        gmax = max(r["gp"] for r in rows.values())
        P.percentiles(rows, PCT_KEYS, gmax)
        for r in rows.values():
            if r["pos"] == "G":
                r["pct"] = dict(r.get("pct_pos") or {})
            r["qualified"] = P.qualified(r, gmax)
        b["pct_done"] = True
        b["gmax"] = gmax
    return rows


def players_payload(ctx: dict, s: int) -> dict:
    st = ctx["stores"][s]
    if not chn_on(st):
        return fail("player numbers come from College Hockey News, not available for this season" if chn.enabled()
                    else "player numbers come from College Hockey News, which is switched off", season=s)
    rows = player_rows(ctx, s)
    if not rows:
        return fail("no player lines for this season yet", season=s)
    arch = s < current_season(ctx["level"])
    out = {}
    keys = [m[0] for m in all_metrics()]
    for pid, r in rows.items():
        if arch and not r["qualified"]:
            continue
        out[pid] = {"name": r["name"], "team": r["team"], "pos": r["pos"], "class": r.get("class"), "gp": r["gp"],
                    "qualified": r["qualified"], "values": {k: r[k] for k in keys if isinstance(r.get(k), (int, float))},
                    "pct": r.get("pct") or {}, "pct_pos": r.get("pct_pos") or {}}
    posn = Counter(v["pos"] for v in out.values())
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(),
            "metrics": [_metric(*m) for m in all_metrics()],
            "positions": {"F": {"label": "Forwards", "n": posn.get("F", 0)}, "D": {"label": "Defence", "n": posn.get("D", 0)},
                          "G": {"label": "Goalies", "n": posn.get("G", 0)}},
            "min_floor": {"gp": max(5, int(0.4 * max(r["gp"] for r in rows.values())))},
            "players": PK.pack_keyed(out), "compact": arch, "source": chn.CREDIT}


def value_row(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "team": r["team"], "pos": r["pos"], "class": r.get("class"), "gp": r["gp"],
            "value": r2(r.get("gar")), "value_pg": r3(r.get("gar_pg")), "war": r2(r.get("war")),
            "pctl": (r.get("pct_pos") or {}).get("gar"), "why": P.why(r)}


def value_payload(ctx: dict, s: int) -> dict:
    st = ctx["stores"][s]
    if not chn_on(st):
        return fail("player value comes from College Hockey News lines, not available", season=s)
    rows = player_rows(ctx, s)
    if not rows:
        return fail("no player lines for this season yet", season=s)
    lst = sorted((r for r in rows.values() if r.get("gar") is not None), key=lambda r: -r["gar"])
    return {"ok": True, "level": ctx["level"], "season": s, "updated_at": now_iso(), "basis": "season",
            "currency": {"key": "value", "label": "Goals above replacement",
                         "desc": "Our value model: goals created above a replacement-level player of the same position "
                                 "(Hockey-Reference's goals-created split of the team's goals), a damped share of +/- relative "
                                 "to the team, penalties and faceoffs; goalies: goals saved above average, shrunk toward "
                                 "average on few shots. Six goals are about one win."},
            "leaders": [value_row(r) for r in lst[:200]],
            "by_position": {pos: [value_row(r) for r in lst if r["pos"] == pos][:10] for pos in ("F", "D", "G")}}


def moves_list(ctx: dict, s: int) -> list[dict]:
    """Transfers into season s, from the CHN player id (a player keeps it across schools) on a different Division I
    team than in s - 1, plus the roster's "last team" where it names a D-I school (incoming players with no line yet)."""
    b = ctx["bundles"].setdefault(s, {})
    if "moves" in b:
        return b["moves"]
    out = []
    st = ctx["stores"].get(s)
    prev_st = ctx["stores"].get(s - 1)
    if st and prev_st and chn_on(st) and chn_on(prev_st):
        cur_rows = player_rows(ctx, s)
        prev_rows = player_rows(ctx, s - 1)
        cur_team = {pid: p["team"] for pid, p in (st["chn"].get("players") or {}).items()}
        cur_team.update({pid: p["team"] for pid, p in (st["chn"].get("goalies") or {}).items()})
        for pid, t in cur_team.items():
            pr = prev_rows.get(pid)
            if not pr or pr["team"] == t:
                continue
            cr = cur_rows.get(pid) or {}
            out.append({"player": pid, "name": pr["name"], "pos": pr["pos"], "from": pr["team"], "to": t,
                        "value_before": r2(pr.get("gar")), "value_after": r2(cr.get("gar")) if cr else None,
                        "class": cr.get("class") or pr.get("class"), "gp_before": pr["gp"], "gp_after": cr.get("gp")})
        out.sort(key=lambda m: -(m["value_before"] or -99))
    b["moves"] = out
    return out


def moves_payload(ctx: dict, s: int) -> dict:
    st = ctx["stores"].get(s)
    if not chn_on(st):
        return fail("transfers are read from College Hockey News player ids, not available", season=s)
    mv = moves_list(ctx, s)
    if not ctx["stores"].get(s - 1) or not chn_on(ctx["stores"].get(s - 1)):
        return fail("no previous season with player lines to compare", season=s)
    by = defaultdict(lambda: {"in": [], "out": [], "net_value": 0.0})
    for m in mv:
        by[m["to"]]["in"].append(m["player"])
        by[m["from"]]["out"].append(m["player"])
        by[m["to"]]["net_value"] += m["value_before"] or 0
        by[m["from"]]["net_value"] -= m["value_before"] or 0
    for v in by.values():
        v["net_value"] = r2(v["net_value"])
    d1 = {t for t, v in st["teams"].items() if v.get("d1")}
    return {"ok": True, "season": s, "updated_at": now_iso(),
            "note": "Inferred: the same College Hockey News player id on a different Division I team from one season to the "
                    "next (the transfer portal itself is not public data). value_before = last season's goals above replacement.",
            "moves": mv, "by_team": {t: v for t, v in by.items() if t in d1}, "best": mv[:25],
            "summary": {"n": len(mv), "with_value_after": sum(1 for m in mv if m["value_after"] is not None),
                        "teams_in": sum(1 for t, v in by.items() if v["in"])}}


def lab_payloads(ctx: dict, s: int, sdir: Path) -> int:
    n = 0
    st = ctx["stores"][s]
    tv = team_values(ctx, s)
    mets = team_metrics()
    fields = ["id", "name", "conference"] + [m[0] for m in mets]
    rows = [[t, st["teams"][t].get("short"), st["teams"][t].get("conf")] + [tv[t].get(m[0]) for m in mets] for t in tv]
    n += write(sdir / "lab_teams.json", {"ok": True, "season": s, "kind": "team", "fields": fields,
                                         "metrics": [_metric(*m) for m in mets], "rows": rows})
    if not chn_on(st):
        n += write(sdir / "lab_players.json", fail("player numbers come from College Hockey News, not available", season=s))
        return n
    pr = player_rows(ctx, s)
    if not pr:
        n += write(sdir / "lab_players.json", fail("no player lines for this season yet", season=s))
        return n
    arch = s < current_season(ctx["level"])
    keys = [m[0] for m in all_metrics()]
    pf = ["id", "name", "team", "pos", "class", "gp"] + [k for k in keys if k != "gp"] + ["qualified", "age", "hometown"]
    prow = []
    for pid, r in pr.items():
        if arch and not r["qualified"]:
            continue
        bio = r.get("bio") or {}
        age = None
        if bio.get("dob"):
            try:
                dob = date.fromisoformat(bio["dob"])
                ref = date(s - 1, 10, 1)
                age = round((ref - dob).days / 365.25, 1)
            except ValueError:
                age = None
        prow.append([pid, r["name"], r["team"], r["pos"], r.get("class"), r["gp"]] +
                    [r.get(k) for k in keys if k != "gp"] + [r["qualified"], age, bio.get("hometown")])
    n += write(sdir / "lab_players.json", {"ok": True, "season": s, "kind": "player", "fields": pf,
                                           "metrics": [_metric(*m) for m in all_metrics()], "rows": prow,
                                           "source": chn.CREDIT})
    return n


# ── team pages ─────────────────────────────────────────────────────────────────────────────────────────────

UNITS = [("F", "Forwards", "gar", "Goals above replacement of the forwards"),
         ("D", "Defence", "gar", "Goals above replacement of the defencemen"),
         ("G", "Goaltending", "gar", "Goals above replacement in net"),
         ("off", "Attack", "off", "Goals scored above average (our rating)"),
         ("def", "Keeping goals out", "def", "Goals prevented below average (our rating)"),
         ("pp", "Power play", "pp_pct", "Power-play conversion"), ("pk", "Penalty kill", "pk_pct", "Penalty-kill rate"),
         ("shots", "Shot share", "shot_share", "Share of the shots on goal")]


def team_units(ctx: dict, s: int) -> dict[str, list]:
    b = bundle(ctx, s)
    rows = player_rows(ctx, s)
    tv = team_values(ctx, s)
    by_team = defaultdict(lambda: defaultdict(float))
    for r in rows.values():
        if r.get("gar") is not None:
            by_team[r["team"]][r["pos"]] += r["gar"]
    raw = {}
    for t in tv:
        u = {"F": by_team[t].get("F") if rows else None, "D": by_team[t].get("D") if rows else None,
             "G": by_team[t].get("G") if rows else None, "off": tv[t].get("off"), "def": tv[t].get("def"),
             "pp": tv[t].get("pp_pct"), "pk": tv[t].get("pk_pct"), "shots": tv[t].get("shot_share")}
        raw[t] = u
    out = defaultdict(list)
    for key, label, _m, desc in UNITS:
        xs = {t: u[key] for t, u in raw.items() if isinstance(u.get(key), (int, float))}
        if len(xs) < 8:
            continue
        arr = np.array(sorted(xs.values()))
        for t, x in xs.items():
            p = int(round(100.0 * np.searchsorted(arr, x, side="right") / len(arr)))
            grade = "A" if p >= 85 else "B" if p >= 65 else "C" if p >= 35 else "D" if p >= 15 else "F"
            fmt_v = f"{x:.1%}" if key in ("pp", "pk", "shots") else f"{x:+.2f}"
            out[t].append({"unit": label, "key": key, "grade": grade, "pctl": p, "value": r3(x),
                           "evidence": f"{desc}: {fmt_v}"})
    return dict(out)


def team_pages(ctx: dict, s: int, sdir: Path, sims: int) -> int:
    lv = ctx["level"]
    st = ctx["stores"][s]
    b = bundle(ctx, s)
    sim = season_sim(ctx, s, sims)
    rows = player_rows(ctx, s)
    by_team = defaultdict(list)
    for r in rows.values():
        by_team[r["team"]].append(r)
    units = team_units(ctx, s)
    mv = moves_list(ctx, s) if chn_on(st) else []
    mv_in, mv_out = defaultdict(list), defaultdict(list)
    for m in mv:
        mv_in[m["to"]].append(m)
        mv_out[m["from"]].append(m)
    tv = team_values(ctx, s)
    mets = team_metrics()
    pct = _pcts(tv, mets)
    ranks = {}
    for k, _l, _g, _f, lower, _d in mets:
        xs = sorted(((v.get(k), t) for t, v in tv.items() if isinstance(v.get(k), (int, float))), reverse=not lower)
        ranks[k] = {t: i + 1 for i, (_, t) in enumerate(xs)}
    arch = s < current_season(lv)
    by_t_games = defaultdict(list)
    for g in st["games"]:
        by_t_games[g["home"]].append(g)
        by_t_games[g["away"]].append(g)
    paths = rating_paths(ctx, s) if not arch else {}
    stand = {r["team"]: r for rws in b["standings"].values() for r in rws}
    rosters = ((st.get("chn") or {}).get("rosters") or {}) if chn_on(st) else {}
    n = 0
    for t, rt in b["ratings"].items():
        try:
            us = units.get(t, [])
            strengths = sorted(us, key=lambda u: -u["pctl"])[:3]
            sk = {u["key"] for u in strengths}
            needs = sorted((u for u in us if u["key"] not in sk), key=lambda u: u["pctl"])[:3]
            roster = []
            for r in sorted(by_team.get(t, []), key=lambda r: -(r.get("gar") or -99))[:14 if arch else 99]:
                row = {"id": r["id"], "name": r["name"], "pos": r["pos"], "class": r.get("class"), "gp": r["gp"],
                       "value": r2(r.get("gar")), "value_pg": r3(r.get("gar_pg")), "g": r.get("g"), "a": r.get("a"),
                       "pts": r.get("pts"), "pm": r.get("pm"), "toi": r.get("toi_pg"), "sv_pct": r.get("sv_pct"),
                       "gsaa": r.get("gsaa"), "num": (r.get("bio") or {}).get("num")}
                roster.append({k: v for k, v in row.items() if v is not None})
            stats = {}
            for k, *_r in mets:
                v = tv.get(t, {}).get(k)
                if v is not None:
                    stats[k] = {"v": v, "pct": pct.get(t, {}).get(k), "rank": ranks[k].get(t)}
            r0 = stand.get(t) or {}
            bio = []
            if not arch:
                for x in rosters.get(t, []) or []:
                    bio.append({k: x.get(k) for k in ("num", "name", "cls", "pos", "ht_in", "wt", "hometown", "last_team", "draft")})
            tops = top_performers(rows, t)
            page = {"ok": True, "id": t, "level": lv, "season": s, "team": team_rec(ctx, st, t),
                    "record": {k: r0.get(k) for k in ("w", "l", "t", "otw", "otl", "conf_w", "conf_l", "conf_t", "conf_pts", "home",
                                                      "away", "neutral", "streak", "gf", "ga", "conf_rank")},
                    "rating": rt, "rating_path": paths.get(t, []), "rank_history": rank_history(st, paths, t),
                    "schedule": None if arch else PK.pack(card(ctx, s, g) for g in sorted(by_t_games.get(t, []), key=lambda g: g["date"])),
                    "stats": stats, "roster": PK.pack(roster), "roster_basis": "season", "bio": bio if bio else None,
                    "units": us, "strengths": strengths, "needs": needs,
                    "moves": {"in": mv_in.get(t, []), "out": mv_out.get(t, [])},
                    "odds": (sim or {}).get("teams", {}).get(t) if sim else None, "suggestions": [],
                    "top_performers": tops}
            if arch:
                page.pop("schedule")
                page.pop("rating_path")
            write(sdir / "teams" / f"{t}.json", {k: v for k, v in page.items() if v is not None})
            n += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("team page %s", t)
            write(sdir / "teams" / f"{t}.json", fail(f"team page failed: {exc}"))
    return n


def rank_history(st: dict, paths: dict, t: str) -> list:
    """[[poll date, USCHO rank | None, our rank]] for each USCHO poll of the season (our rank from the weekly
    ratings path on or before the poll's date)."""
    us = st.get("uscho") or {}
    if not us or not paths:
        return []
    out = []
    for d in sorted(us):
        ours = {}
        for tt, p in paths.items():
            v = [x[1] for x in p if x[0] <= d and x[1] is not None]
            if v:
                ours[tt] = v[-1]
        if t not in ours:
            continue
        order = sorted(ours, key=lambda k: -ours[k])
        pr = next((r["rank"] for r in us[d] if r["team"] == t), None)
        out.append([d, pr, order.index(t) + 1])
    return out


def top_performers(rows: dict, t: str) -> dict | None:
    mine = [r for r in rows.values() if r["team"] == t and r.get("qualified")]
    if not mine:
        return None
    n_by = Counter(r["pos"] for r in rows.values() if r.get("qualified"))
    overall = sorted(mine, key=lambda r: -(r.get("gar") or -99))[:5]
    by_pos = []
    for pos in ("F", "D", "G"):
        c = [r for r in mine if r["pos"] == pos]
        if c:
            r = max(c, key=lambda r: r.get("gar") or -99)
            by_pos.append(r)
    order = {}
    for pos in ("F", "D", "G"):
        ps = sorted((x for x in rows.values() if x["pos"] == pos and x.get("qualified")), key=lambda x: -(x.get("gar") or -99))
        order.update({x["id"]: i + 1 for i, x in enumerate(ps)})
    row = lambda r: {"id": r["id"], "name": r["name"], "pos": r["pos"], "key": "gar", "v": r.get("gar"),
                     "pct": (r.get("pct_pos") or {}).get("gar"), "n": n_by.get(r["pos"]), "gp": r["gp"], "rank": order.get(r["id"])}
    return {"key": "gar", "label": "Goals above replacement", "ours": True, "pool": "Division I",
            "overall": [row(r) for r in overall], "by_pos": [row(r) for r in by_pos]}


# ── game pages ─────────────────────────────────────────────────────────────────────────────────────────────

def game_page(ctx: dict, s: int, g: dict) -> dict:
    st = ctx["stores"][s]
    c = card(ctx, s, g)
    teams = {t: team_rec(ctx, st, t) for t in (g["home"], g["away"])}
    page = {"ok": True, "level": ctx["level"], **c, "teams": teams,
            "venue": {"name": g.get("venue")} if g.get("venue") else None, "attendance": g.get("att"),
            "pregame": {"model": c.get("model")}}
    cb = g.get("chn") or {}
    box = ((st.get("chn") or {}).get("boxes") or {}).get(g["id"]) if chn_on(st) else None
    if chn_on(st) and cb:
        ts = {}
        for k, t in enumerate((g["home"], g["away"])):
            d = {}
            if cb.get("sh"):
                d["sog"] = cb["sh"][k]
            if cb.get("shp"):
                d["sog_per"] = cb["shp"][k]
            if cb.get("per"):
                d["goals_per"] = cb["per"][k]
            if cb.get("pp"):
                d["ppg"], d["ppo"] = cb["pp"][k]
            if cb.get("pim"):
                d["pim"] = cb["pim"][k]
            if cb.get("xg"):
                d["chn_xg"] = cb["xg"][k]
            ts[t] = d
        page["team_stats"] = ts
        page["chn_type"] = cb.get("type")
    if box:
        if box.get("team"):
            for t, d in box["team"].items():
                tsd = page.setdefault("team_stats", {}).setdefault(t, {})
                if d.get("fow") is not None:
                    tsd["fow"], tsd["fol"] = d.get("fow"), d.get("fol")
                if d.get("xg") is not None:
                    tsd["chn_xg"] = d["xg"]
                if d.get("pim") is not None:
                    tsd["pim"] = d["pim"]
                if d.get("shots"):
                    tsd["sog_per"] = d["shots"][:-1]
                    tsd["sog"] = d["shots"][-1]
                if d.get("periods"):
                    tsd["goals_per"] = d["periods"]
        page["box"] = {"cols": ((st["chn"].get("box_cols")) or {}), "skaters": box.get("skaters"), "goalies": box.get("goalies"),
                       "goals": box.get("goals"), "pens": box.get("pens"), "lines": box.get("lines") or None,
                       "labels": box.get("labels"), "refs": box.get("refs"), "type": box.get("type")}
        if not page.get("attendance") and box.get("att"):
            page["attendance"] = box["att"]
        if not page.get("venue") and box.get("venue"):
            page["venue"] = {"name": box["venue"]}
        page["flow"] = goal_flow(g, box)
        page["leaders"] = box_leaders(g, box)
        mt = ((st.get("chn") or {}).get("metrics") or {}).get(g["id"])
        if mt:
            page["attempts"] = {"cols": ["kind", "pid", "team", "name"] + D.METRIC_KEYS["skaters"], "gcols":
                                ["kind", "pid", "team", "name"] + D.METRIC_KEYS["goalies"], "rows": mt}
    page["source"] = chn.CREDIT if (chn_on(st) and (cb or box)) else "ESPN"
    return page


def goal_flow(g: dict, box: dict) -> list:
    """[[minute, home lead]] stepping at each goal (empty-net goals included)."""
    out = [[0, 0]]
    lead = 0
    for x in sorted(box.get("goals") or [], key=lambda x: ((x[0] or 0), (x[1] or 0))):
        per, t, team = x[0], x[1], x[2]
        if per is None or t is None or per > 10:
            continue
        minute = (per - 1) * 20 + t / 60.0 if per <= 3 else 60 + (per - 4) * 5 + t / 60.0
        lead += 1 if team == g["home"] else -1
        out.append([round(minute, 2), lead])
    end = 60 + 5 * max(0, (g.get("ot") or 0)) if g.get("ot") else 60
    out.append([end, lead])
    return out


def box_leaders(g: dict, box: dict) -> dict:
    out = {}
    for t in (g["home"], g["away"]):
        sk = [r for r in box.get("skaters") or [] if r[1] == t]
        sk.sort(key=lambda r: (-((r[3] or 0) + (r[4] or 0)), -(r[3] or 0), -(r[6] or 0)))
        rows = []
        for r in sk[:3]:
            if (r[3] or 0) + (r[4] or 0) == 0:
                continue
            rows.append({"id": r[0], "name": r[2], "line": f"{r[3] or 0} G, {r[4] or 0} A" + (f", {r[6]} SOG" if r[6] else "")})
        gk = [r for r in box.get("goalies") or [] if r[1] == t and not r[6]]
        for r in gk[:1]:
            sv, ga = r[3] or 0, r[4] or 0
            rows.append({"id": r[0], "name": r[2], "line": f"{sv} saves on {sv + ga}" + (f" ({sv / (sv + ga):.3f})" if sv + ga else "")})
        out[t] = rows
    return out


def game_pages(ctx: dict, s: int, sdir: Path) -> int:
    st = ctx["stores"][s]
    cur = s >= current_season(ctx["level"])
    n = 0
    for g in st["games"]:
        if g.get("stype") == "exh":
            continue
        if not cur and g.get("stype") not in ("ncaa", "conf"):
            continue
        try:
            n += 1 if write(sdir / "games" / f"{g['id']}.json", game_page(ctx, s, g)) else 0
        except Exception as exc:  # noqa: BLE001
            write(sdir / "games" / f"{g['id']}.json", fail(f"game page failed: {exc}"))
    return n


PERF_FMT = {"gar": "+1", "gar_pg": "+2", "pts_pg": "2", "g_pg": "2", "sh_pg": "1", "pm_rel": "+1", "blk_pg": "2", "sv_pct": "3",
            "gsaa": "+1", "gaa": "2", "p1_pg": "2", "toi_pg": "1"}


def performers_payload(ctx: dict, s: int) -> dict:
    """Top and bottom players on each position's headline numbers, in the shared performers shape
    (oddsmarkets/common/performers.py: views [{key, label, n, peer, metrics [{key, label, unit, dir, fmt, tip, ours,
    top [[pid, name, team, value, pct]], bottom}]}]): the overview's "Who's hot" and Home's leader strips read it."""
    rows = player_rows(ctx, s)
    if not rows:
        return fail("no player lines", season=s)
    lab = {m[0]: (m[1], m[5]) for m in all_metrics()}
    views = []
    for key, pos, label, peer, keys in (("hk_f", ("F",), "Forwards", "forwards", ["gar_pg", "pts_pg", "p1_pg", "sh_pg", "g_pg"]),
                                        ("hk_d", ("D",), "Defence", "defencemen", ["gar_pg", "pts_pg", "pm_rel", "blk_pg"]),
                                        ("hk_g", ("G",), "Goalies", "goalies", ["gsaa", "sv_pct", "gar", "gaa"]),
                                        ("hk_all", ("F", "D"), "Every skater", "skaters", ["gar", "gar_pg", "pts"])):
        q = [r for r in rows.values() if r["pos"] in pos and r.get("qualified")]
        mets = []
        for k in keys:
            low = k in ("gaa",)
            vals = [r for r in q if isinstance(r.get(k), (int, float))]
            if len(vals) < 5:
                continue
            vals.sort(key=lambda r: r[k], reverse=not low)
            n = len(vals)
            pc = lambda i: round(100.0 * (n - i - 0.5) / n, 1)
            mets.append({"key": k, "label": lab.get(k, (k, ""))[0], "unit": "", "dir": "lower" if low else "higher",
                         "fmt": PERF_FMT.get(k, "2"), "tip": lab.get(k, ("", ""))[1], "ours": k in ("gar", "gar_pg", "war"),
                         "top": [[r["id"], r["name"], r["team"], r[k], pc(i)] for i, r in enumerate(vals[:5])],
                         "bottom": [[r["id"], r["name"], r["team"], r[k], pc(n - 3 + i)] for i, r in enumerate(vals[-3:])]})
        if mets:
            views.append({"key": key, "label": label, "n": len(q), "peer": peer, "metrics": mets})
    return {"ok": True, "season": s, "level": ctx["level"], "updated_at": now_iso(), "views": views}


# ── per season ─────────────────────────────────────────────────────────────────────────────────────────────

def build(level: str, season: int, out_dir: Path | str, stores: Any = None, *, full: bool = True, sims: int = 4000,
          markets: bool = True) -> dict:
    ctx = context(level)
    s = int(season)
    if s not in ctx["stores"]:
        return fail(f"no {level} store for {s}")
    sdir = Path(out_dir) / level / str(s)
    sdir.mkdir(parents=True, exist_ok=True)
    rep = {}

    def step(name, fn):
        try:
            rep[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s %s %s", level, s, name)
            write(sdir / f"{name}.json", fail(f"{type(exc).__name__}: {exc}", season=s))
            rep[name] = f"failed: {exc}"

    sims = max(1000, min(int(sims or 4000), 6000))
    if markets and s >= current_season(level) and "game_mk" not in ctx:
        try:
            from . import markets as HM
            ctx["game_mk"] = HM.game_markets(level, ctx["stores"][s])
        except Exception:  # noqa: BLE001
            ctx["game_mk"] = {}
    step("season", lambda: write(sdir / "season.json", season_payload(ctx, s, sims)))
    step("schedule", lambda: write(sdir / "schedule.json", schedule_payload(ctx, s)))
    step("bracket", lambda: write(sdir / "bracket.json", bracket_payload(ctx, s, sims)))
    step("teams", lambda: write(sdir / "teams.json", teams_payload(ctx, s)))
    step("team_pages", lambda: team_pages(ctx, s, sdir, sims))
    step("players", lambda: write(sdir / "players.json", players_payload(ctx, s)))
    step("value", lambda: write(sdir / "value.json", value_payload(ctx, s)))
    step("moves", lambda: write(sdir / "moves.json", moves_payload(ctx, s)))
    step("lab", lambda: lab_payloads(ctx, s, sdir))
    step("performers", lambda: write(sdir / "performers.json", performers_payload(ctx, s)))
    step("fantasy", lambda: write(sdir / "fantasy.json", fail("no fantasy game for college hockey", season=s)))
    if full or s >= current_season(level) - 1:
        step("games", lambda: game_pages(ctx, s, sdir))
    return {"ok": True, **{k: v for k, v in rep.items()}}


def migrate(level: str, out_dir: Path | str, season: int) -> int:
    return 0


# ── per level ──────────────────────────────────────────────────────────────────────────────────────────────

def calibration_payload(ctx: dict) -> dict:
    preds = ctx["preds"]
    seasons = sorted({p["season"] for p in preds})
    # a season is scored only when the season before it is on file (the baseline's base rates); the development
    # seasons are those before the sealed ones (the current season is scored live, in neither group)
    dev = [s for s in seasons if s < min(SEALED) and s >= DEV_FROM and s - 1 in seasons]
    test = [s for s in seasons if s in SEALED]
    per = []
    for s in seasons:
        if s < DEV_FROM or s - 1 not in seasons:
            continue
        e = M.evaluate(preds, [s], rate_seasons=[s - 1])
        if e.get("n"):
            per.append({"season": s, "n": e["n"], "model": {"logloss": e["logloss"], "brier": e["brier_home"], "acc": e["acc"]},
                        "base": {"logloss": e["logloss_base"]}, "diff": e["diff"], "ci95": e["ci95"],
                        "tie_rate": e["tie_rate"], "tie_pred": e["tie_pred"], "sealed": s in SEALED})
    ed = M.evaluate(preds, dev, rate_seasons=[s - 1 for s in dev]) if dev else {}
    et = M.evaluate(preds, test, rate_seasons=[s - 1 for s in test]) if test else {}
    promoted = bool(et.get("n")) and et["ci95"][1] < 0
    return {"ok": True, "level": ctx["level"], "updated_at": now_iso(), "seasons": seasons,
            "n_games": sum(r["n"] for r in per),
            "summary": {"model": {"logloss": et.get("logloss"), "brier": et.get("brier_home"), "acc": et.get("acc"), "n": et.get("n")},
                        "base": {"logloss": et.get("logloss_base")}, "diff": et.get("diff"), "ci95": et.get("ci95"),
                        "dev": {k: ed.get(k) for k in ("n", "logloss", "logloss_base", "diff", "ci95", "acc", "brier_home")},
                        "test_seasons": test, "dev_seasons": [min(dev), max(dev)] if dev else None, "promoted": promoted},
            "per_season": per, "calibration": et.get("calibration") or ed.get("calibration") or [],
            "params": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in ctx["p"].items()},
            "validation": validation_block(ctx),
            "notes": ["Log-loss on the three outcomes of the NCAA record (win, tie, loss; shootouts are ties), every game "
                      "between two Division I teams, each predicted from games before its day.",
                      "Baseline: the previous season's share of home wins, ties and away wins (neutral ice split evenly).",
                      f"Sealed test seasons {', '.join(str(s) for s in test)}: parameters were chosen on {min(dev) if dev else '-'}-"
                      f"{max(dev) if dev else '-'} only."]}


def validation_block(ctx: dict) -> dict | None:
    p = cache_dir() / f"{ctx['level']}_selection_validation.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    return None


def history_payload(ctx: dict) -> dict:
    champs, ff, conf_ch, best = [], {}, {}, []
    calls = []
    for s, st in sorted(ctx["stores"].items()):
        if s >= current_season(ctx["level"]) and phase(ctx, s) != "offseason":
            continue
        act = actual_ncaa(ctx, s)
        if act and act.get("champion"):
            fin = act["final"]
            sc = f"{max(fin['hs'], fin['as'])}-{min(fin['hs'], fin['as'])}" + (" (OT)" if (fin.get("ot") or 0) > 0 else "")
            champs.append({"season": s, "team": act["champion"], "runner_up": act.get("runner_up"), "score": sc,
                           "gid": fin["id"]})
            ff[str(s)] = act.get("frozen_four") or []
            try:
                pre = pre_tournament_odds(ctx, s, act)
            except Exception:  # noqa: BLE001
                pre = {}
            if pre:
                fav = max(pre, key=lambda t: pre[t].get("p_title") or 0)
                calls.append({"season": s, "champion": act["champion"], "p_champion": r4((pre.get(act["champion"]) or {}).get("p_title")),
                              "favourite": fav, "p_favourite": r4(pre[fav].get("p_title")), "hit": fav == act["champion"],
                              "ff_expected": r2(sum((pre.get(t) or {}).get("p_f4", 0) for t in act.get("frozen_four") or [])),
                              "ff": act.get("frozen_four")})
        cc = conf_champions(ctx, s)
        if cc:
            conf_ch[str(s)] = cc
        f = ctx["ends"].get(s)
        if f is not None:
            stand = standings(ctx, s)
            recs = {r["team"]: f"{r['w']}-{r['l']}-{r['t']}" for rows in stand.values() for r in rows}
            for t in recs:
                best.append({"season": s, "team": t, "rating": r2(f.net(t)), "record": recs[t],
                             "name": st["teams"][t].get("short")})
    best.sort(key=lambda r: -(r["rating"] or -9))
    teams = {}
    for s, st in ctx["stores"].items():
        for t, v in st["teams"].items():
            if v.get("d1"):
                teams[t] = team_rec(ctx, st, t)
    return {"ok": True, "level": ctx["level"], "updated_at": now_iso(), "champions": champs, "frozen_fours": ff,
            "conference_champions": conf_ch, "best_teams": best[:25], "calls": calls, "teams": teams,
            "first_season": min(ctx["stores"]) if ctx["stores"] else None,
            "notes": ["NCAA tournament results from ESPN's scoreboards (2005-06 on) and College Hockey News."]}


def markets_payload(ctx: dict, season: int, markets: bool) -> dict:
    """Kalshi's men's national-champion book (hockey/markets.py), a quiet reference beside our title chances; the
    per-game markets ride on the schedule's cards. Polymarket lists no college hockey."""
    out = {"ok": True, "level": ctx["level"], "season": season, "updated_at": now_iso(), "fetched": False, "futures": None,
           "model": {}, "games": {}}
    if not markets or season not in ctx["stores"]:
        return out
    try:
        from . import markets as HM
        t = HM.title_market(ctx["level"], season, ctx["stores"][season])
    except Exception:  # noqa: BLE001
        t = None
    out["fetched"] = True
    if t:
        out["futures"] = {"champion": t}
    sim = season_sim(ctx, season, 2000) or {}
    out["model"] = {"champion": {k: v.get("p_title") for k, v in (sim.get("teams") or {}).items() if v.get("p_title")}}
    return out


def career_files(ctx: dict, out: Path, current: int) -> int:
    """players/<pid>.json for every player with a CHN line in the last two seasons: season-by-season numbers (every
    season of the store), this season's game log from box scores, moves, and the progression series."""
    if not chn.enabled():
        return 0
    seasons = sorted(ctx["stores"])
    rows_by = {s: player_rows(ctx, s) for s in seasons if chn_on(ctx["stores"][s])}
    recent = set()
    for s in (current, current - 1):
        recent |= set(rows_by.get(s, {}))
    logs = P.box_lines(ctx["stores"][current]) if current in ctx["stores"] and chn_on(ctx["stores"][current]) else {}
    glogs = P.goalie_logs(ctx["stores"][current]) if current in ctx["stores"] and chn_on(ctx["stores"][current]) else {}
    pdir = out / ctx["level"] / "players"
    pdir.mkdir(parents=True, exist_ok=True)
    keep = set()
    n = 0
    keys = [m[0] for m in all_metrics()]
    for pid in recent:
        hist = []
        last = None
        for s in seasons:
            r = rows_by.get(s, {}).get(pid)
            if not r:
                continue
            last = r
            row = {"season": s, "team": r["team"], "pos": r["pos"], "class": r.get("class"), "gp": r["gp"],
                   **{k: r.get(k) for k in keys if isinstance(r.get(k), (int, float)) and k != "gp"},
                   "value": r2(r.get("gar")), "value_pg": r3(r.get("gar_pg")), "pctl": (r.get("pct_pos") or {}).get("gar"),
                   "pct": r.get("pct_pos") or {}}
            hist.append(row)
        if not last:
            continue
        cur_r = rows_by.get(current, {}).get(pid)
        cur = None
        if cur_r:
            lg = logs.get(pid, {}).get("log") if cur_r["pos"] != "G" else glogs.get(pid)
            cur = {"season": current, "team": cur_r["team"], "value": value_row(cur_r),
                   "log": PK.pack([dict(zip(["game", "date", "opp", "home", "res", "g", "a", "pts", "pm", "sh", "toi", "pim"], x))
                                   for x in (lg or [])]) if cur_r["pos"] != "G" else
                   PK.pack([dict(zip(["game", "date", "opp", "home", "sv", "ga", "sec"], x)) for x in (lg or [])])}
        bio = last.get("bio") or {}
        moves = []
        for a, b2 in zip(hist, hist[1:]):
            if a["team"] != b2["team"]:
                moves.append({"season": b2["season"], "from": a["team"], "to": b2["team"], "value_before": a.get("value"),
                              "value_after": b2.get("value")})
        page = {"ok": True, "id": pid, "name": last["name"], "pos": last["pos"], "level": ctx["level"], "updated_at": now_iso(),
                "class": last.get("class"), "height_in": bio.get("ht_in"), "weight_lb": bio.get("wt"),
                "hometown": bio.get("hometown"), "dob": bio.get("dob"), "draft": bio.get("draft"), "last_team": bio.get("last_team"),
                "seasons": hist, "current": cur, "moves": moves, "source": chn.CREDIT}
        write(pdir / f"{pid}.json", page)
        keep.add(f"{pid}.json")
        n += 1
    for p in pdir.glob("*.json"):
        if p.name not in keep:
            try:
                p.unlink()
            except OSError:
                pass
    return n


def build_level(level: str, out_dir: Path | str, seasons: Iterable[int] | None = None, current: int | None = None, *,
                sims: int = 4000, markets: bool = True, per_season: bool = True) -> dict:
    ctx = context(level)
    out = Path(out_dir)
    cur = current or current_season(level)
    rep = {}
    ldir = out / level
    ldir.mkdir(parents=True, exist_ok=True)
    for name, fn in (("calibration", lambda: write(ldir / "calibration.json", calibration_payload(ctx))),
                     ("history", lambda: write(ldir / "history.json", history_payload(ctx))),
                     ("markets", lambda: write(ldir / "markets.json", markets_payload(ctx, cur, markets))),
                     ("careers", lambda: career_files(ctx, out, cur))):
        try:
            rep[name] = fn()
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s %s", level, name)
            rep[name] = f"failed: {exc}"
            if name != "careers":
                write(ldir / f"{name}.json", fail(f"{type(exc).__name__}: {exc}"))
    if per_season:
        for s in sorted(seasons or ctx["stores"], reverse=True):
            rep[s] = build(level, s, out, sims=sims, markets=markets)
    return rep
