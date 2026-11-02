"""
The Quant Scrum's payloads (docs/scrum/data; the shapes are in docs/scrum/DATA_PIPELINE.md, "Payloads").

    build_scope(scope, data_dir, sims) writes, for one scope (men | women):
      <S>/overview.json   the landing page: digest top lines, the featured test, upcoming tests, power board, stories
      <S>/fixtures.json   upcoming tests with our chances, recent results with our pre-match call
      <S>/years/<Y>.json  every match of a year (the results archive)
      <S>/ratings.json    our ratings, ranks, movement and a monthly history per team
      <S>/rankings.json   our World Rugby rankings replica: the table, movement, history, "what each result would do"
      <S>/comps/<key>.json  standings with bonus points, simulations, past winners
      <S>/teams/<id>.json   a team page; <S>/teams.json the Teams page (power board, profile grid, style map)
      <S>/players/<id>.json a player page; <S>/players.json the Scouting Room's board (one row per player)
      <S>/matches/<id>.json a match page
      <S>/model.json      how it works, how we're doing (the ladder, calibration, the forecast log), the lab
      <S>/records.json    history and records
    and the follow cards (follow_build.py).

No look-ahead: the walk-forward forecasts on finished matches are made before each match from results already
played; upcoming forecasts use every result to date; the forecast log freezes the last forecast published before a
kick-off and never rewrites it.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import colours, comps, config, models, nations, players as PL, rankings, store, validate
from .ratings import Model, Params

log = logging.getLogger("scrum.build")
FITTED = Path(__file__).resolve().parent / "fitted"
UPCOMING_DAYS = 120
RECENT_RESULTS = 160


# ── io ──────────────────────────────────────────────────────────────────────────────────────────────────────

def write(p: Path, obj) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    return len(text)


def r1(x, d=1):
    return None if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))) else round(float(x), d)


def now_utc() -> datetime:
    s = os.environ.get("SCRUM_NOW")
    if s:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def load_params(scope: str) -> dict:
    sfx = "" if scope == "men" else f"_{scope}"
    p = FITTED / f"params{sfx}.json"
    if not p.exists():
        p = FITTED / "params.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_report(scope: str) -> dict:
    sfx = "" if scope == "men" else f"_{scope}"
    p = FITTED / f"report{sfx}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def mk_params(d: dict | None) -> Params:
    p = Params()
    for k, v in (d or {}).items():
        if hasattr(p, k):
            setattr(p, k, v)
    return p


# ── the state of a scope ───────────────────────────────────────────────────────────────────────────────────

class Scope:
    def __init__(self, scope: str, now: datetime):
        self.scope, self.now = scope, now
        self.today = now.date().isoformat()
        raw, self.athletes = store.load_all(scope)
        self.all = [m for m in raw if m.get("home", {}).get("id") and m.get("away", {}).get("id")]
        self.finals = models.eligible(self.all)
        fin_ids = {m["id"] for m in self.finals}
        self.upcoming = sorted([m for m in self.all if m["status"] == "pre" and m["id"] not in fin_ids and
                                str(m.get("date") or "") >= (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M")],
                               key=lambda m: m["date"])
        self.live = [m for m in self.all if m["status"] == "live"]
        self.by_id = {m["id"]: m for m in self.all}
        self.fit = load_params(scope)
        self.report = load_report(scope)
        self.p = mk_params(self.fit.get("params"))
        self.pt = mk_params(self.fit.get("total_params") or self.fit.get("params"))
        self.pt.split = True
        self.teams = self._teams()

    def _teams(self) -> dict:
        out = {}
        for m in self.all:
            for s in ("home", "away"):
                t = m[s]
                cur = out.get(t["id"]) or {}
                n = nations.lookup(t["name"])
                prim, alt = colours.kit(t["name"], t.get("colour"), t.get("alt"))
                out[t["id"]] = {"name": t["name"], "abbr": (n["code"] if n else None) or t.get("abbr") or t["name"][:3].upper(),
                                "code": n["code"] if n else None, "tier": n["tier"] if n else 3,
                                "colour": prim or cur.get("colour"), "alt": alt or cur.get("alt")}
        return out

    def name(self, tid: str) -> str:
        return (self.teams.get(tid) or {}).get("name") or str(tid)


def card(S: Scope, m: dict, fc: dict | None = None) -> dict:
    """The match shape every list uses (front end: SC.game)."""
    c = {"id": m["id"], "date": m["date"], "comp": m.get("comp"), "status": m["status"], "home": m["home"]["id"],
         "away": m["away"]["id"]}
    if m.get("neutral"):
        c["neutral"] = 1
    v = m.get("venue") or {}
    if v.get("name"):
        c["venue"] = v["name"] + (", " + v["city"] if v.get("city") else "")
    if m.get("note"):
        c["note"] = m["note"]
    if m.get("hs") is not None and m["status"] in ("final", "live"):
        c["hs"], c["as"] = m["hs"], m["as"]
    if fc:
        c["p"] = [r1(fc["p_home"], 4), r1(fc["p_draw"], 4), r1(fc["p_away"], 4)]
        c["m"] = r1(fc["margin"])
        if fc.get("total") is not None:
            c["t"] = r1(fc["total"])
    return c


# ── the walk: forecasts on every finished match, the final state, rating histories ─────────────────────────

def walk(S: Scope) -> dict:
    mdl, tot = Model(S.p), Model(S.pt)
    mdl.wr_fit = S.fit.get("wr_logistic")
    fc, hist = {}, defaultdict(list)
    for m in S.finals:
        y = int(m["date"][:4])
        mdl.new_year(y)
        tot.new_year(y)
        e = mdl.expect(m)
        et = tot.expect(m)
        mg = e["margin"]
        total = et["total"]
        fc[m["id"]] = {"p_home": e["p_home"], "p_draw": e["p_draw"], "p_away": e["p_away"], "margin": mg, "total": total,
                       "exp_h": (total + mg) / 2, "exp_a": (total - mg) / 2, "edge": e["edge"],
                       "r_h": mdl.rating(m["home"]["id"]), "r_a": mdl.rating(m["away"]["id"]), "ctx": e["ctx"], "sd": e.get("sd")}
        mdl.update(m, e)
        tot.update(m, et)
        for t in (m["home"]["id"], m["away"]["id"]):
            hist[t].append((m["date"][:10], round(mdl.rating(t), 2)))
    y = S.now.year
    mdl.new_year(y) if mdl.year is not None and y > mdl.year else None
    tot.new_year(y) if tot.year is not None and y > tot.year else None
    up = {}
    for m in S.upcoming + S.live:
        e = mdl.expect(m)
        et = tot.expect(m)
        up[m["id"]] = {"p_home": e["p_home"], "p_draw": e["p_draw"], "p_away": e["p_away"], "margin": e["margin"],
                       "total": et["total"], "exp_h": (et["total"] + e["margin"]) / 2, "exp_a": (et["total"] - e["margin"]) / 2,
                       "edge": e["edge"], "ctx": e["ctx"], "r_h": mdl.rating(m["home"]["id"]), "r_a": mdl.rating(m["away"]["id"])}
    return {"model": mdl, "total": tot, "fc": fc, "up": up, "hist": hist}


def form_of(S: Scope, tid: str, upto: str | None = None, n: int = 5) -> str:
    out = []
    for m in reversed(S.finals):
        if upto and m["date"] >= upto:
            continue
        if tid in (m["home"]["id"], m["away"]["id"]):
            us = m["hs"] if m["home"]["id"] == tid else m["as"]
            th = m["as"] if m["home"]["id"] == tid else m["hs"]
            out.append("W" if us > th else ("D" if us == th else "L"))
            if len(out) >= n:
                break
    return "".join(reversed(out))


def team_results(S: Scope, tid: str) -> list[dict]:
    return [m for m in S.finals if tid in (m["home"]["id"], m["away"]["id"])]


# ── the World Rugby replica ────────────────────────────────────────────────────────────────────────────────

def replica(S: Scope) -> dict:
    """Burn-in replica (from 1995, tier priors) and the live table (anchored on the published 28 Sep 2026 table)."""
    rk, _rows = models.replica(S.finals)
    check = validate.replica_check(rk, S.finals) if S.scope == "men" else {}
    anchor = validate.anchor_seed(S.finals) if S.scope == "men" else {}
    live = rankings.Ranker()
    if anchor:
        burn_at = validate.points_at(rk.history, validate.PUBLISHED_DATE)
        floor = min(anchor.values())
        for t, v in burn_at.items():
            live.points[t] = anchor.get(t, min(v, floor - 0.01))
            live.played[t] = rk.played.get(t, 0)
            live.last[t] = rk.last.get(t, "")
        for t, v in anchor.items():
            live.points[t] = v
        after = [m for m in S.finals if m["date"][:10] > validate.PUBLISHED_DATE
                 and not nations.invitational(m["home"]["name"]) and not nations.invitational(m["away"]["name"])]
        for m in after:
            live.update(m["home"]["id"], m["away"]["id"], m["hs"], m["as"], m["date"], neutral=bool(m.get("neutral")),
                        world_cup=m.get("comp") in ("rwc", "wrwc"))
        src = "anchored"
    else:
        live = rk
        src = "rebuilt"
    return {"burn": rk, "live": live, "check": check, "source": src}


# ── competition tables and simulations ─────────────────────────────────────────────────────────────────────

def results_of(S: Scope, comp: str, yr: int, teams: list[str] | None = None) -> list[dict]:
    out = []
    for m in S.finals:
        if m.get("comp") != comp or int(m["date"][:4]) != yr:
            continue
        hn, an = S.name(m["home"]["id"]), S.name(m["away"]["id"])
        if teams and (hn not in teams or an not in teams):
            continue
        out.append({"home": hn, "away": an, "hs": m["hs"], "as": m["as"],
                    "ht": (m.get("hstat") or {}).get("tries"), "at": (m.get("astat") or {}).get("tries"), "id": m["id"],
                    "date": m["date"]})
    return out


def ids_by_name(S: Scope) -> dict:
    out = {}
    for tid, t in S.teams.items():
        out.setdefault(t["name"], tid)
    for k, al in validate.ALIASES.items():
        for a in al:
            if a in out and k not in out:
                out[k] = out[a]
    return out


def score_sim(S: Scope, seed: int = 11) -> comps.ScoreSim:
    tr = S.fit.get("tries") or {}
    return comps.ScoreSim(S.p.s0, S.p.s1, float(S.fit.get("sd_total") or 13.0), float(tr.get("c0", 0.0)),
                          float(tr.get("c1", 0.125)), random.Random(seed))


class SimModel:
    """A Model view for the simulators: margin from our promoted model, total from the attack/defence model."""

    def __init__(self, w: dict):
        self.m, self.t = w["model"], w["total"]

    def expect(self, m):
        e, et = self.m.expect(m), self.t.expect(m)
        tot, mg = et["total"], e["margin"]
        return {"exp_h": (tot + mg) / 2, "exp_a": (tot - mg) / 2}


def comp_payloads(S: Scope, w: dict, rep: dict, sims: int) -> dict:
    out = {}
    if S.scope != "men":
        return out
    ids = ids_by_name(S)
    sm = SimModel(w)
    fallback = {S.name(t): p for t, p in rep["live"].points.items()}
    yr = S.now.year
    # Six Nations: the latest edition's table, the next edition's chances
    six_teams = comps.NC_NORTH
    for y in range(yr, 1999, -1):
        last_six = results_of(S, "six", y, six_teams)
        if last_six:
            break
    table6 = comps.table(last_six, six_teams, bonus=y >= 2017, grand_slam=y >= 2017)
    six = {"key": "six", "name": "Six Nations", "season": y, "table": table6, "results": [_res_row(r, S, w) for r in last_six]}
    if all(n in ids for n in six_teams):
        fx = [(d, h, a) for d, h, a in comps.SIX27]
        done = results_of(S, "six", 2027, six_teams)
        rem = [(d, h, a) for d, h, a in fx if not any(r["home"] == h and r["away"] == a for r in done)]
        sim = comps.simulate_league(sm, score_sim(S, 1), six_teams, ids, done, rem, n=sims, grand_slam=True,
                                    triple_crown=True, fallback=fallback)
        six["next"] = {"season": 2027, "sim": sim, "fixtures": [{"date": d, "home": h, "away": a,
                                                                 "p": _p_named(S, w, ids, h, a, d)} for d, h, a in rem]}
    six["winners"] = winners(S, "six", six_teams, bonus_from=2017, grand_slam_from=2017)
    out["six"] = six
    # The Rugby Championship (Tri Nations before 2012)
    trc_y = None
    for y in range(yr, 1995, -1):
        rs = results_of(S, "trc", y)
        if rs:
            trc_y = y
            break
    if trc_y:
        tt = sorted({r["home"] for r in rs} | {r["away"] for r in rs})
        out["trc"] = {"key": "trc", "name": "The Rugby Championship", "season": trc_y, "table": comps.table(rs, tt),
                      "results": [_res_row(r, S, w) for r in rs], "winners": winners(S, "trc", None)}
        rem = [m for m in S.upcoming if m.get("comp") == "trc"]
        if rem:
            out["trc"]["next"] = {"season": int(rem[0]["date"][:4]), "sim": comps.simulate_league(
                sm, score_sim(S, 2), tt, ids, results_of(S, "trc", int(rem[0]["date"][:4])),
                [(m["date"], S.name(m["home"]["id"]), S.name(m["away"]["id"])) for m in rem], n=sims, fallback=fallback)}
    # Nations Championship 2026: both conferences, the finals weekend
    nc_teams = comps.NC_NORTH + comps.NC_SOUTH
    if all(n in ids for n in nc_teams):
        played = results_of(S, "nc", 2026, nc_teams)
        rem = [(m["date"], S.name(m["home"]["id"]), S.name(m["away"]["id"])) for m in S.upcoming
               if m.get("comp") == "nc" and S.name(m["home"]["id"]) in nc_teams and S.name(m["away"]["id"]) in nc_teams]
        tabs = comps.table(played, nc_teams)
        north = comps.rank([dict(x) for x in tabs if x["team"] in comps.NC_NORTH], played)
        south = comps.rank([dict(x) for x in tabs if x["team"] in comps.NC_SOUTH], played)
        sim = comps.simulate_nc(sm, score_sim(S, 3), ids, played, rem, n=sims) if rem or played else None
        out["nc"] = {"key": "nc", "name": "Nations Championship", "season": 2026, "north": north, "south": south,
                     "results": [_res_row(r, S, w) for r in played], "sim": sim,
                     "fixtures": [{"date": d, "home": h, "away": a, "p": _p_named(S, w, ids, h, a, d)} for d, h, a in sorted(rem)],
                     "finals": [{"place": 2 * i + 1, "label": lab, "date": d} for i, (lab, d) in enumerate(NC26_FINALS)]}
    # Rugby World Cup 2027
    rwc_teams = [t for ts in comps.RWC27_POOLS.values() for t in ts]
    if sum(1 for n in rwc_teams if n in ids) >= 20:
        played = [r for r in results_of(S, "rwc", 2027)]
        sim = comps.simulate_rwc27(sm, score_sim(S, 4), ids, played, fallback, n=max(2000, sims // 2))
        out["rwc"] = {"key": "rwc", "name": "Rugby World Cup", "season": 2027, "pools": comps.RWC27_POOLS, "sim": sim,
                      "host": comps.RWC27_HOST, "r16": {str(k): v for k, v in comps.RWC27_R16.items()},
                      "qf": {str(k): v for k, v in comps.RWC27_QF.items()}, "sf": {str(k): v for k, v in comps.RWC27_SF.items()},
                      "thirds": comps.RWC27_THIRDS, "winners": rwc_winners(S),
                      "pool_tables": {p: comps.table(played, ts, tiebreak="rwc") for p, ts in comps.RWC27_POOLS.items()}}
    return out


# the finals weekend of the 2026 Nations Championship (Wikipedia, "2026 Nations Championship", read 2 Nov 2026)
NC26_FINALS = [("The final (N1 v S1)", "2026-11-29T16:40Z"), ("Third place (N2 v S2)", "2026-11-28T16:40Z"),
               ("Fifth place (N3 v S3)", "2026-11-27T20:10Z"), ("Seventh place (N4 v S4)", "2026-11-29T13:10Z"),
               ("Ninth place (N5 v S5)", "2026-11-28T13:10Z"), ("Eleventh place (N6 v S6)", "2026-11-27T16:40Z")]


def _p_named(S: Scope, w: dict, ids: dict, h: str, a: str, d: str) -> list | None:
    if h not in ids or a not in ids:
        return None
    e = w["model"].expect({"home": {"id": ids[h], "name": h}, "away": {"id": ids[a], "name": a}, "date": d,
                           "neutral": False, "venue": {}})
    return [r1(e["p_home"], 4), r1(e["p_draw"], 4), r1(e["p_away"], 4), r1(e["margin"])]


def _res_row(r: dict, S: Scope, w: dict) -> dict:
    f = w["fc"].get(r["id"]) or {}
    return {"id": r["id"], "date": r["date"][:10], "home": r["home"], "away": r["away"], "hs": r["hs"], "as": r["as"],
            "ht": r.get("ht"), "at": r.get("at"), "p": r1(f.get("p_home"), 3) if f else None}


def winners(S: Scope, comp: str, teams: list[str] | None, bonus_from: int = 0, grand_slam_from: int = 9999) -> list[dict]:
    out = []
    yrs = sorted({int(m["date"][:4]) for m in S.finals if m.get("comp") == comp})
    for y in yrs:
        rs = results_of(S, comp, y, teams)
        if len(rs) < 6:
            continue
        tt = teams or sorted({r["home"] for r in rs} | {r["away"] for r in rs})
        tab = comps.table(rs, tt, bonus=(comp != "six" or y >= bonus_from), grand_slam=y >= grand_slam_from)
        top = tab[0]
        out.append({"season": y, "team": top["team"], "pts": top["pts"], "w": top["w"], "p": top["p"],
                    "slam": top["w"] == len(tt) - 1 and comp == "six", "n": len(rs),
                    "complete": len(rs) == len(tt) * (len(tt) - 1) // (1 if comp == "trc" and len(tt) <= 4 else 2)})
    return out


def rwc_winners(S: Scope) -> list[dict]:
    """World Cup finals in the data: the last match of each edition (its latest date) is the final."""
    out = []
    for y in sorted({int(m["date"][:4]) for m in S.finals if m.get("comp") == "rwc"}):
        ms = [m for m in S.finals if m.get("comp") == "rwc" and int(m["date"][:4]) == y]
        if len(ms) < 20:
            continue
        f = max(ms, key=lambda m: m["date"])
        hw = f["hs"] > f["as"]
        out.append({"season": y, "team": S.name(f["home" if hw else "away"]["id"]),
                    "runner_up": S.name(f["away" if hw else "home"]["id"]), "score": [max(f["hs"], f["as"]), min(f["hs"], f["as"])],
                    "id": f["id"], "n": len(ms)})
    return out
