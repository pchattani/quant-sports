"""
The trade simulator (docs/VALUE_SECTIONS.md section 3) for MLB and NPB: the precomputed payloads the browser reads.

    <L>/<S>/trade.json         the clubs, the units, the horizon, and every club's sensitivity curve
    <L>/<S>/value/<tid>.json   "roster": each player's projected value at every position he can play (value.py
                               writes the rest of the file: grades, strengths, needs)

The browser (assets/js/value.js) moves players between clubs and re-runs, for each club, the same depth-chart
allocation as `allocate` below: positions are filled in order of scarcity (C, SS, CF, 2B, 3B, RF, LF, 1B, DH, then
the rotation and the bullpen), each by the best available eligible player by projected full-season value at that
position, a hitter up to 80% of a position's time at catcher and 95% elsewhere (rest days), a starter up to a fifth of
the starts, a reliever up to a seventh of the relief work, each scaled by how much of a season the player can be
expected to play (Marcel's playing time against three quarters of a full role, 25%-100%); a player's time is used once
across positions; time no one on the roster can fill goes to a replacement-level player (zero by definition of WAR). The change in a club's wins is
the allocation after the trade minus the allocation before it (both by the same rule, so a trade of nothing changes
nothing), and "who he displaces" is every player whose time went down.

Odds come from the season simulation, not guesswork: for each club the simulation is re-run with that club's
rating moved by a series of shifts (common random numbers, the other clubs fixed), recording its expected wins and
its postseason, division (NPB: pennant) and title probabilities; the browser interpolates linearly in expected wins
(`interp`). The horizon is the rest of the regular season while one is being played, otherwise the next season
(this season's schedule replayed with every rating carried forward: MLB by the fitted year-to-year carry of the
season simulation's ratings, NPB by the game model's own carry).

Salary and roster legality are not checked: no legitimate free source of MLB or NPB salaries exists (the payload
and the page say so).
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import date
from typing import Any

import numpy as np

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import value as V

log = logging.getLogger(__name__)
VERSION = "trade-1"
ORDER = ("C", "SS", "CF", "2B", "3B", "RF", "LF", "1B", "DH", "SP", "RP")
CAP = {"C": 0.80, "SP": 0.20, "RP": 1.0 / 7.0}
CAP_DEFAULT = 0.95
SHIFT_WINS = (-9.0, -5.0, -2.0, 0.0, 2.0, 5.0, 9.0)
NOT_CHECKED = "Salaries, contracts and roster rules are not checked: no legitimate free source of MLB or NPB salaries exists."


# ── the depth-chart allocation (mirrored in value.js) ───────────────────────

def allocate(players: list[dict], positions: tuple = ORDER, dh: bool = True) -> dict:
    """players: [{"pid", "ft": {pos: projected wins over a full season there}, "avail": hitter's share of a season he
    can play (default 1), "avail_sp" / "avail_rp": the same for a pitcher's role}] (a position absent from ft is one the
    player cannot play). Returns {"share": {pid: {pos: share}}, "wins": total, "repl": {pos: unfilled share}}."""
    avail = {p["pid"]: float(p.get("avail", 1.0)) for p in players}
    share: dict[str, dict] = defaultdict(dict)
    wins = 0.0
    repl = {}
    for pos in positions:
        if pos == "DH" and not dh:
            continue
        cap = CAP.get(pos, CAP_DEFAULT)
        cands = sorted((p for p in players if pos in (p.get("ft") or {}) and p["ft"][pos] is not None),
                       key=lambda p: (-p["ft"][pos], str(p["pid"])))
        left = 1.0
        for p in cands:
            if left <= 1e-9:
                break
            pid = p["pid"]
            # pitchers' time is per role; a hitter's availability is shared across positions
            take = min(cap * float(p.get("avail_" + pos.lower(), 1.0)), left) if pos in ("SP", "RP") else min(cap, left, avail[pid])
            if take <= 1e-9:
                continue
            if pos not in ("SP", "RP"):
                avail[pid] -= take
            share[pid][pos] = share[pid].get(pos, 0.0) + take
            wins += take * p["ft"][pos]
            left -= take
        repl[pos] = max(left, 0.0)
    return {"share": {k: dict(v) for k, v in share.items()}, "wins": wins, "repl": repl}


def trade_delta(roster: list[dict], out_ids: set, incoming: list[dict], dh: bool = True) -> dict:
    """The club's change in wins when out_ids leave and `incoming` arrive; who lost time."""
    before = allocate(roster, dh=dh)
    after_roster = [p for p in roster if p["pid"] not in out_ids] + incoming
    after = allocate(after_roster, dh=dh)
    def seasons(sh: dict) -> float:                 # a hitter's position share; a fifth of the starts or a seventh of the relief work
        return sum(v / (CAP[k] if k in ("SP", "RP") else 1.0) for k, v in sh.items())
    displaced = []
    for pid, sh in before["share"].items():
        if pid in out_ids:
            continue
        lost = seasons(sh) - seasons(after["share"].get(pid) or {})
        if lost > 0.01:
            displaced.append([pid, round(lost, 3)])
    return {"before": before["wins"], "after": after["wins"], "delta": after["wins"] - before["wins"], "displaced": displaced,
            "after_share": after["share"]}


def interp(curve: dict, exp_w: float, key: str) -> float | None:
    """Linear interpolation of curve[key] at expected wins exp_w (clamped to the curve's ends); the curve's points are
    the shifts' expected wins, increasing."""
    xs, ys = curve.get("exp_w") or [], curve.get(key) or []
    if not xs or len(xs) != len(ys):
        return None
    pts = sorted(zip(xs, ys))
    if exp_w <= pts[0][0]:
        return pts[0][1]
    if exp_w >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= exp_w <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (exp_w - x0) / (x1 - x0)
    return pts[-1][1]


# ── rosters ─────────────────────────────────────────────────────────────────

def units(rows: list[dict], n_teams: int, team_games: int, sched: int) -> dict:
    """Full-season units for a club: a lineup slot's plate appearances, the rotation's and the bullpen's batters
    faced (this season's league totals per club, scaled to the schedule)."""
    tg = max(team_games, 1)
    pa = sum((r.get("n") or 0) for r in rows if r["kind"] == "H")
    sp = sum((r.get("n") or 0) * (r.get("pos_g") or {}).get("SP", 0.0) for r in rows if r["kind"] == "P")
    rp = sum((r.get("n") or 0) * (r.get("pos_g") or {}).get("RP", 0.0) for r in rows if r["kind"] == "P")
    k = sched / tg / max(n_teams, 1)
    return {"pa": round(pa * k / 9.0, 1) or 650.0, "sp": round(sp * k, 1) or 4000.0, "rp": round(rp * k, 1) or 2200.0}


def roster_rows(team: str, rows: list[dict], proj: dict, slot: dict, rpw: float, curve: list[float], level: str,
                hist: dict | None = None) -> list[dict]:
    """The club's players for the simulator: ft (projected full-season wins at each position he can play), the
    season's WAR and sample, next season's projected WAR (rate x Marcel playing time) and three seasons' (with
    aging)."""
    out = []
    for r in rows:
        if r.get("team") != team or r.get("war") is None:
            continue
        p = (proj.get(r["kind"]) or {}).get(r["pid"]) or {}
        rate = p.get("rate") if p.get("rate") is not None else r.get("rate")
        ft = {}
        elig = V.eligible(r, min_share=0.1, min_games=5) if r["kind"] == "H" else ["SP", "RP"]
        for pos in elig + (["DH"] if r["kind"] == "H" else []):
            v = V.value_ft(r, pos, rate, slot, rpw)
            if v is not None:
                ft[pos] = round(v, 2)
        if r["kind"] == "P":                       # a starter can relieve; a reliever starts only if he has
            if r.get("pos") == "RP" and (r.get("pos_g") or {}).get("SP", 0) < 0.15:
                ft.pop("SP", None)
        h = (hist or {}).get(r["kind"] + ":" + r["pid"]) or {}
        unit = V.UNIT[r["kind"]]
        pt = V.marcel_time(h, max(h) if h else 0, r["kind"], level) if h else (r.get("n") or 0)
        # how much of a season he can be expected to play (Marcel's playing time against three quarters of a full role):
        # a part-timer or a call-up never takes over a position on his projected rate alone
        avail = {}
        if r["kind"] == "H":
            avail["avail"] = round(min(1.0, max(0.25, pt / (0.75 * slot["pa"]))), 3)
        else:
            avail["avail_sp"] = round(min(1.0, max(0.25, pt / (0.75 * slot["sp"] / 5.0))), 3)
            avail["avail_rp"] = round(min(1.0, max(0.25, pt / (0.75 * slot["rp"] / 7.0))), 3)
        age = p.get("age") if p.get("age") is not None else r.get("age")
        w1 = rate * pt / unit if rate is not None else None
        w3 = None
        if rate is not None:
            rr, tot = rate, 0.0
            for y in range(3):
                if y:
                    rr += V.age_delta(curve, (age + y - 1) if age is not None else None)
                tot += rr * pt / unit
            w3 = tot
        out.append({"pid": r["pid"], "name": r.get("name"), "kind": r["kind"], "pos": r.get("pos"), "ft": ft, "war": an.rnd(r.get("war"), 1),
                    "n": r.get("n"), "rate": an.rnd(rate, 2), "proj": an.rnd(w1, 1), "proj3": an.rnd(w3, 1), "age": an.rnd(age, 1), **avail})
    return out


# ── sensitivity curves: MLB ─────────────────────────────────────────────────

def mlb_carry(level: str = "mlb") -> dict:
    """Year-to-year carry of the season simulation's end-of-season ratings (regressed run differential): slope of
    r(S+1) on r(S) through the origin, and the residual spread of talent (the ratings' own noise removed)."""
    from oddsmarkets.baseball.models import season_sim as SS
    seasons = an.seasons_on_disk(level)
    rs: dict[int, dict] = {}
    for s in seasons:
        st = an.load_store(level, s)
        if not st or SS.phase(st) == "preseason":
            continue
        try:
            rs[s] = {t: v["r"] for t, v in SS.team_ratings(st).items() if v.get("g")}
        except Exception:                           # noqa: BLE001
            continue
    x, y = [], []
    for s in rs:
        if s + 1 in rs and s + 1 != max(rs) or (s + 1 in rs and SS.phase(an.load_store(level, s + 1)) != "regular"):
            for t, r0 in rs[s].items():
                if t in rs[s + 1]:
                    x.append(r0)
                    y.append(rs[s + 1][t])
    if len(x) < 30:
        return {"carry": 0.5, "sd": 0.12, "n": len(x)}
    x, y = np.array(x), np.array(y)
    carry = float((x * y).sum() / (x * x).sum())
    resid = y - carry * x
    noise = SS.RATING_PER_RUN * SS.RD_SD / math.sqrt(162 + SS.RATING_G0) * 0.6
    sd = float(math.sqrt(max(resid.var() - noise ** 2, 0.03 ** 2)))
    return {"carry": round(carry, 4), "sd": round(sd, 4), "n": len(x), "seasons": sorted(rs)}


def mlb_curves(store: dict, season: int, n: int = 1000, seed: int = 11, carry: dict | None = None) -> dict:
    """Sensitivity curves for every MLB club: {"horizon", "base": {tid: {...}}, "curves": {tid: {...}}}."""
    from oddsmarkets.baseball.models import season_sim as SS
    ph = SS.phase(store)
    reg = SS.regular_games(store)
    left = [g for g in reg if not SS.is_final(g) and str(g.get("status") or "").lower() not in ("postponed", "cancelled", "canceled")]
    horizon = "rest" if ph == "regular" and len(left) >= 30 else "next"
    ratings = SS.team_ratings(store)
    if horizon == "next":
        c = carry or {"carry": 0.5, "sd": 0.12}
        sim_store = {"teams": store.get("teams"), "level": store.get("level"), "games": {}}
        for g in reg:
            x = dict(g)
            x.update(status="Scheduled", hs=None, **{"as": None})
            sim_store["games"][str(g.get("gpk"))] = x
        base_r = {t: {"r": c["carry"] * v["r"], "se": c["sd"]} for t, v in ratings.items()}
        games_left = len(reg)
    else:
        sim_store = store
        base_r = {t: dict(v) for t, v in ratings.items()}
        games_left = len(left)
    teams = SS.real_teams(store)
    per_team_games = 2.0 * games_left / max(len(teams), 1)
    out = {"horizon": horizon, "games_per_club": round(per_team_games, 1), "curves": {}, "sims": n,
           "keys": {"p_post": "Postseason", "p_div": "Division", "p_title": "World Series"}}

    def run(r):
        res = SS.regular_season(sim_store, n=n, seed=seed, ratings=r)
        return res["teams"]
    base = run(base_r)
    for t in teams:
        pts = []
        for w in SHIFT_WINS:
            if w == 0:
                res_t = base[t]
            else:
                d = 4.0 * w / max(per_team_games, 1.0)
                r = {k: dict(v) for k, v in base_r.items()}
                r[t]["r"] = r[t]["r"] + d
                res_t = run(r)[t]
            pts.append((float(res_t["exp_w"]), float(res_t["p_postseason"]), float(res_t["p_division"]), float(res_t["p_ws"])))
        pts.sort()
        out["curves"][t] = {"exp_w": [round(p[0], 2) for p in pts], "p_post": [round(p[1], 4) for p in pts],
                            "p_div": [round(p[2], 4) for p in pts], "p_title": [round(p[3], 4) for p in pts]}
    out["base"] = {t: {"exp_w": round(float(base[t]["exp_w"]), 2), "p_post": round(float(base[t]["p_postseason"]), 4),
                       "p_div": round(float(base[t]["p_division"]), 4), "p_title": round(float(base[t]["p_ws"]), 4)} for t in teams}
    return out


# ── sensitivity curves: NPB ─────────────────────────────────────────────────

def npb_curves(st: dict, tab: dict, br: dict, R, table, n: int = 600, seed: int = 11, today: date | None = None) -> dict:
    """Sensitivity curves for every NPB club from npb/build.simulate (regular season, Climax Series, Japan Series)."""
    from oddsmarkets.baseball.npb import build as NB, canon
    s = st["season"]
    games = list(st["games"].values())
    td = (today or canon.today_jst()).isoformat()
    left = [g for g in games if g.get("gtype") == "R" and g.get("status") in ("pre", "live") and g["date"] >= td]
    horizon = "rest" if len(left) >= 12 else "next"
    R2 = copy.deepcopy(R)
    if horizon == "next":
        for d in (R2.off, R2.dfn):
            for k in d:
                d[k] *= R2.p.carry
        sim_st = {"season": s, "games": {}}
        for g in games:
            if g.get("gtype") != "R" or g.get("status") not in ("final",):
                continue
            x = {k: g.get(k) for k in ("gpk", "date", "home", "away", "gtype", "league")}
            x["status"] = "pre"
            sim_st["games"][x["gpk"]] = x
        tab0 = {lg: [dict(r, w=0, l=0) for r in rows] for lg, rows in tab.items()}
        br0: dict = {}
        sim_today = date(s, 1, 1)
        n_left = sum(1 for g in sim_st["games"].values())
    else:
        sim_st, tab0, br0, sim_today = st, tab, br, today
        n_left = len(left)
    teams = canon.teams_in(s)
    per_team = 2.0 * n_left / max(len(teams), 1)

    class Shifted(NB.Pricer):
        def __init__(self, Rr, tbl, season, team=None, delta=0.0):
            super().__init__(Rr, tbl, season)
            self.team, self.delta = team, delta

        def __call__(self, home, away, gtype, game_no=None, sp_home=None, sp_away=None):
            if self.team is None or self.delta == 0:
                return super().__call__(home, away, gtype, game_no, sp_home, sp_away)
            key = (home, away, gtype, game_no if gtype == "J" and game_no and game_no >= 8 else None, sp_home, sp_away)
            if key in self.memo:
                return self.memo[key]
            from oddsmarkets.baseball.npb import models as M
            mx, ext = M.extras_for(self.s, gtype, game_no, self.table.p)
            dh = canon.dh(canon.team_league(home), self.s)
            mu = list(self.R.expected(home, away, self.s, dh_home=dh, sp_home=sp_home, sp_away=sp_away))
            f = math.exp(self.delta / 2.0)
            if home == self.team:
                mu = [mu[0] * f, mu[1] / f]
            elif away == self.team:
                mu = [mu[0] / f, mu[1] * f]
            p = self.table.probs(mu[0], mu[1], mx, ext)
            self.memo[key] = (p, tuple(mu))
            return self.memo[key]

    def run(team=None, delta=0.0):
        return NB.simulate(sim_st, tab0, br0, Shifted(R2, table, s, team, delta), n, seed=seed, today=sim_today)["teams"]
    base = run()
    out = {"horizon": horizon, "games_per_club": round(per_team, 1), "curves": {}, "sims": n,
           "keys": {"p_post": "Climax Series (top three)", "p_div": "Pennant", "p_title": "Japan Series champion"}}
    for t in teams:
        pts = []
        for w in SHIFT_WINS:
            # about 0.22 log runs of net rating per 10% of winning percentage in NPB's run environment
            d = 2.2 * (w / max(per_team, 1.0))
            res = base[t] if w == 0 else run(t, d)[t]
            pts.append((float(res["exp_w"]), float(res["p_cs"]), float(res["p_pennant"]), float(res["p_champion"])))
        pts.sort()
        out["curves"][t] = {"exp_w": [round(p[0], 2) for p in pts], "p_post": [round(p[1], 4) for p in pts],
                            "p_div": [round(p[2], 4) for p in pts], "p_title": [round(p[3], 4) for p in pts]}
    out["base"] = {t: {"exp_w": round(float(base[t]["exp_w"]), 2), "p_post": round(float(base[t]["p_cs"]), 4),
                       "p_div": round(float(base[t]["p_pennant"]), 4), "p_title": round(float(base[t]["p_champion"]), 4)} for t in teams}
    return out


def trade_index(level: str, season: int, teams: dict, curves: dict, unit: dict, rpw: float, dh: dict) -> dict:
    """<L>/<S>/trade.json."""
    return {"ok": True, "level": level, "season": season, "updated_at": an.now(), "teams": teams, "horizon": curves.get("horizon"),
            "games_per_club": curves.get("games_per_club"), "keys": curves.get("keys"), "curves": curves.get("curves"), "base": curves.get("base"),
            "sims": curves.get("sims"), "units": unit, "rpw": round(rpw, 2), "dh": dh, "order": list(ORDER),
            "caps": {"C": CAP["C"], "SP": CAP["SP"], "RP": round(CAP["RP"], 4), "other": CAP_DEFAULT},
            "not_checked": NOT_CHECKED, "version": VERSION,
            "notes": ["Chances: each club's season simulation re-run at seven rating shifts (common random numbers, the other clubs fixed); "
                      "the page interpolates in expected wins.",
                      "Depth charts: positions filled by the best available eligible player by projected value (the same rule before and after).",
                      "A trade between two clubs that play each other also moves each other's chances through head-to-head games; the curves hold "
                      "the other clubs fixed, so that effect is left out."]}
