"""
The fantasy layer's engine (docs/VALUE_SECTIONS.md section 5; MODELS.md section 28): projected fantasy lines for MLB
players, rotisserie (5x5) and points values, and the helpers the walk-forward backtests share (analytics/fantasy_build.py
writes the payloads and runs the backtests).

Lines. Rates come from the component projections (models/projections.py: K, BB, HBP, singles, doubles, triples, home runs
and outs per plate appearance or batter faced, each regressed at its own rate; next season aged, rest of season from the
season to date). Around them, models fitted on the official season lines (MLB Stats API) of earlier seasons only:
  hitters  AB = PA x (1 - BB - HBP - sacrifices); AVG = H / AB.
           R / PA and RBI / PA: least squares on the on-base, isolated-power, home-run, single and steal rates, the
           club's runs per game against the league's and the lineup slot (`fit_context`).
           SB: attempts per time on first (singles, walks, hit by pitch) and success, each a weighted three-season rate
           (5/4/3) relative to its season's league rate, regressed (k = 60 times on first, 15 attempts) to a prior
           from sprint speed, times the latest season's league rates (the 2023 rules raised them).
           PA next season: least squares on the last two seasons' PA, age and the projected wOBA (`fit_time`),
           checked against Marcel's playing time.
  pitchers outs = BF x (1 - (H + BB + HBP) / BF - e), e the league's reached-on-error rate; IP = outs / 3.
           Runs: BaseRuns from the event rates, scaled so the league's BaseRuns equal its runs; ER = R x the league's
           ER / R. ERA = 9 ER / IP; WHIP = (H + BB) / IP.
           W and L per start from outs per start, the club's winning percentage and the pitcher's ERA against the
           league; relievers' W and L per relief game from the club's winning percentage (`fit_context`).
           SV and HLD: the club's projected saves (holds) times the pitcher's share of them, the share carried with
           the year-to-year persistence fitted on history (`fit_roles`).
           BF next season: least squares on the last two seasons' BF, the share of starts and age; starts = BF x
           his share of batters faced as a starter / batters faced per start.

Values. 5x5 (R, HR, RBI, SB, AVG; W, SV, K, ERA, WHIP) for a 12-team mixed league (C, 1B, 2B, 3B, SS, CI, MI, 5 OF, UT;
9 P): z-scores over the draftable pool (168 hitters, 108 pitchers, found by iteration), AVG, ERA and WHIP as volume-
weighted contributions (hits above the pool's average on his at-bats, earned runs and baserunners saved on his innings),
less the replacement level of his best position; dollars on a $260 budget. Points: our editable default scheme (POINTS).
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

import numpy as np

from oddsmarkets.baseball import analytics as an

EV = ("K", "BB", "HBP", "1B", "2B", "3B", "HR", "GO", "AO")
HIT_CATS = ("r", "hr", "rbi", "sb", "avg")
PIT_CATS = ("w", "sv", "so", "era", "whip")
TEAMS = 12
ROSTER = {"C": 1, "1B": 1, "2B": 1, "3B": 1, "SS": 1, "CI": 1, "MI": 1, "OF": 5, "UT": 1}
N_HIT = TEAMS * sum(ROSTER.values())
N_PIT = TEAMS * 9
BUDGET = 260
# the default points scheme (editable on the page)
POINTS = {"H": {"r": 1, "rbi": 1, "b1": 1, "d": 2, "t": 3, "hr": 4, "bb": 1, "hbp": 1, "sb": 2, "cs": -1, "so": -1},
          "P": {"outs": 1, "so": 1, "h": -1, "bb": -1, "hbp": -1, "er": -2, "w": 5, "l": -3, "sv": 5, "hld": 3}}
SPRINT_REF = 27.0


# ── official lines ──────────────────────────────────────────────────────────

def h_rates(x: dict) -> dict | None:
    """Per-PA rates of an official hitting line."""
    pa = float(x.get("pa") or 0)
    if pa <= 0:
        return None
    h, d, t, hr = (float(x.get(k) or 0) for k in ("h", "d", "t", "hr"))
    b1 = h - d - t - hr
    bb, hbp = float(x.get("bb") or 0), float(x.get("hbp") or 0)
    return {"obp": (h + bb + hbp) / pa, "iso": (d + 2 * t + 3 * hr) / pa, "hr": hr / pa, "b1": b1 / pa, "sb": float(x.get("sb") or 0) / pa,
            "r": float(x.get("r") or 0) / pa, "rbi": float(x.get("rbi") or 0) / pa, "opp": (b1 + bb + hbp) / pa}


def proj_h_feats(r9) -> dict:
    """The same rates from a projected event vector (per PA)."""
    r = dict(zip(EV, [float(v) for v in r9]))
    return {"obp": r["BB"] + r["HBP"] + r["1B"] + r["2B"] + r["3B"] + r["HR"], "iso": r["2B"] + 2 * r["3B"] + 3 * r["HR"], "hr": r["HR"],
            "b1": r["1B"], "opp": r["1B"] + r["BB"] + r["HBP"]}


def league(lines_h: dict, lines_p: dict) -> dict:
    """League constants of a season from its official lines."""
    H = defaultdict(float)
    for x in (lines_h or {}).values():
        for k in ("pa", "ab", "r", "h", "d", "t", "hr", "rbi", "sb", "cs", "bb", "hbp", "sf", "sh", "so", "g"):
            H[k] += float(x.get(k) or 0)
    P = defaultdict(float)
    for x in (lines_p or {}).values():
        for k in ("outs", "bf", "h", "r", "er", "hr", "bb", "hbp", "so", "w", "sv", "hld", "gs", "g", "l"):
            P[k] += float(x.get(k) or 0)
    pa = max(H["pa"], 1.0)
    b1 = H["h"] - H["d"] - H["t"] - H["hr"]
    opp = b1 + H["bb"] + H["hbp"]
    tb = H["h"] + H["d"] + 2 * H["t"] + 3 * H["hr"]
    br = baseruns(H["h"], H["hr"], H["bb"] + H["hbp"], tb, H["ab"] - H["h"] + H["sf"] + H["sh"])
    bf = max(P["bf"], 1.0)
    e = 1.0 - P["outs"] / bf - (P["h"] + P["bb"] + P["hbp"]) / bf
    return {"sfsh": (H["sf"] + H["sh"]) / pa, "att": (H["sb"] + H["cs"]) / max(opp, 1.0), "succ": H["sb"] / max(H["sb"] + H["cs"], 1.0),
            "r_pa": H["r"] / pa, "rg": H["r"] / max(P["gs"], 1.0), "br_mult": (H["r"] / br) if br > 0 else 1.0,
            "er_r": P["er"] / max(P["r"], 1.0), "e": max(min(e, 0.04), -0.02), "era": 27.0 * P["er"] / max(P["outs"], 1.0),
            "whip": 3.0 * (P["h"] + P["bb"]) / max(P["outs"], 1.0), "avg": H["h"] / max(H["ab"], 1.0), "sv_team": P["sv"] / 30.0,
            "hld_team": P["hld"] / 30.0, "woba": None}


def baseruns(h: float, hr: float, walks: float, tb: float, outs: float) -> float:
    a = h + walks - hr
    b = (1.4 * tb - 0.6 * h - 3.0 * hr + 0.1 * walks) * 1.02
    return (a * b / (b + outs) if b + outs > 0 else 0.0) + hr


# ── store context: lineup slots, club runs and records ─────────────────────

def store_context(store: dict, lo: str | None = None, hi: str | None = None) -> dict:
    """{"slot": {pid: [sum of slots, starts]}, "starts": {pid: starts}, "team": {tid: {"g", "r", "w"}}, "player_team": {pid: tid}}
    from the regular-season games dated lo..hi (inclusive bounds, either open)."""
    slot: dict[str, list] = defaultdict(lambda: [0.0, 0])
    team: dict[str, dict] = defaultdict(lambda: {"g": 0, "r": 0, "w": 0})
    pteam: dict[str, tuple] = {}
    for g in (store.get("games") or {}).values():
        if g.get("gtype") != "R" or g.get("status") != "final":
            continue
        d = str(g.get("date"))[:10]
        if (lo and d < lo) or (hi and d > hi):
            continue
        hs, as_ = g.get("hs"), g.get("as")
        for side, tid, rs, ra in (("home", g.get("home"), hs, as_), ("away", g.get("away"), as_, hs)):
            if tid is None or rs is None or ra is None:
                continue
            t = team[tid]
            t["g"] += 1
            t["r"] += rs
            t["w"] += int(rs > ra)
        for tid, lu in (g.get("lineups") or {}).items():
            for i, pid in enumerate((lu or [])[:9]):
                if pid:
                    c = slot[str(pid)]
                    c[0] += i + 1
                    c[1] += 1
                    if str(pid) not in pteam or pteam[str(pid)][0] <= d:
                        pteam[str(pid)] = (d, str(tid))
    return {"slot": {k: v for k, v in slot.items()}, "team": dict(team), "player_team": {k: v[1] for k, v in pteam.items()}}


def mean_slot(ctx: dict, pid: str, k: float = 20.0) -> float:
    s = (ctx.get("slot") or {}).get(pid)
    if not s:
        return 6.0
    return (s[0] + k * 5.5) / (s[1] + k)


def team_rg(ctx: dict, tid: str | None, lg_rg: float, k: float = 81.0) -> float:
    t = (ctx.get("team") or {}).get(tid) if tid else None
    if not t or not t["g"]:
        return lg_rg
    return (t["r"] + k * lg_rg) / (t["g"] + k)


def team_wpct(ctx: dict, tid: str | None, k: float = 81.0) -> float:
    t = (ctx.get("team") or {}).get(tid) if tid else None
    if not t or not t["g"]:
        return 0.5
    return (t["w"] + k * 0.5) / (t["g"] + k)


# ── fits on official lines ──────────────────────────────────────────────────

def _ols(X, y, w=None, ridge: float = 1e-6):
    X, y = np.asarray(X, float), np.asarray(y, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    sw = np.sqrt(w)
    A = X * sw[:, None]
    coef = np.linalg.solve(A.T @ A + ridge * np.eye(X.shape[1]), A.T @ (y * sw))
    return coef


def r_feats(f: dict, sb: float, rg_rel: float, slot: float) -> list[float]:
    return [1.0, f["obp"], f["iso"], sb, rg_rel, slot - 5.0]


def rbi_feats(f: dict, rg_rel: float, slot: float) -> list[float]:
    return [1.0, f["hr"], f["iso"], f["b1"], rg_rel, slot - 5.0]


def fit_context(seasons: Iterable[int], lines: dict, ctxs: dict, leagues: dict) -> dict:
    """R, RBI per PA (hitters, 150+ PA) and W, L per start (starters, 10+ starts and 70% of games started) and per relief
    game (relievers) on the given seasons' official lines."""
    XR, yR, XB, yB, w = [], [], [], [], []
    XW, yW, yL, ww = [], [], [], []
    XRP, yWr, yLr, wr = [], [], [], []
    for s in seasons:
        lh, lp = (lines.get(s) or {}).get("hitting") or {}, (lines.get(s) or {}).get("pitching") or {}
        cx, lg = ctxs.get(s) or {}, leagues.get(s) or {}
        lg_rg = lg.get("rg") or 4.5
        for pid, x in lh.items():
            if (x.get("pa") or 0) < 150:
                continue
            f = h_rates(x)
            tid = x.get("team") or cx.get("player_team", {}).get(pid)
            rg_rel = team_rg(cx, tid, lg_rg, 0.0) - lg_rg
            sl = mean_slot(cx, pid)
            XR.append(r_feats(f, f["sb"], rg_rel, sl))
            yR.append(f["r"])
            XB.append(rbi_feats(f, rg_rel, sl))
            yB.append(f["rbi"])
            w.append(float(x["pa"]))
        for pid, x in lp.items():
            g, gs, outs = float(x.get("g") or 0), float(x.get("gs") or 0), float(x.get("outs") or 0)
            tid = x.get("team")
            wp = team_wpct(cx, tid, 0.0) - 0.5
            era_rel = 27.0 * float(x.get("er") or 0) / max(outs, 1.0) - (lg.get("era") or 4.2)
            if gs >= 10 and gs >= 0.7 * g:
                XW.append([1.0, outs / gs, wp, max(min(era_rel, 4.0), -4.0)])
                yW.append(float(x.get("w") or 0) / gs)
                yL.append(float(x.get("l") or 0) / gs)
                ww.append(gs)
            elif gs <= 0.1 * g and g >= 20:
                rg_ = g - gs
                XRP.append([1.0, wp, outs / max(g, 1.0)])
                yWr.append(float(x.get("w") or 0) / rg_)
                yLr.append(float(x.get("l") or 0) / rg_)
                wr.append(rg_)
    out = {}
    if len(yR) >= 100:
        out["r"] = [float(c) for c in _ols(XR, yR, w)]
        out["rbi"] = [float(c) for c in _ols(XB, yB, w)]
    if len(yW) >= 50:
        out["w_sp"] = [float(c) for c in _ols(XW, yW, ww)]
        out["l_sp"] = [float(c) for c in _ols(XW, yL, ww)]
    if len(yWr) >= 50:
        out["w_rp"] = [float(c) for c in _ols(XRP, yWr, wr)]
        out["l_rp"] = [float(c) for c in _ols(XRP, yLr, wr)]
    return out


def _avail(seasons, lines, group):
    return [s for s in seasons if (lines.get(s) or {}).get(group)]


def fit_time(seasons: list[int], lines: dict, woba_proj: dict | None = None) -> dict:
    """Playing time next season. Hitters: PA(S+1) on [1, PA(S), PA(S-1), age - 28, (age - 28)^2] (players with 50+ PA in S;
    a player with no line in S+1 counts 0). Pitchers: BF(S+1) on [1, BF(S), BF(S-1), share of starts, age - 28]."""
    Xh, yh, Xp, yp = [], [], [], []
    for s in seasons:
        a, b0, nx = (lines.get(s) or {}), (lines.get(s - 1) or {}), (lines.get(s + 1) or {})
        if not nx or s + 1 == 2020 or s == 2020:
            continue
        for pid, x in (a.get("hitting") or {}).items():
            if (x.get("pa") or 0) < 50:
                continue
            prev = ((b0.get("hitting") or {}).get(pid) or {}).get("pa") or 0
            age = float(x.get("age") or 28) - 28.0
            Xh.append([1.0, float(x["pa"]), float(prev), age, age * age])
            yh.append(float(((nx.get("hitting") or {}).get(pid) or {}).get("pa") or 0))
        for pid, x in (a.get("pitching") or {}).items():
            if (x.get("bf") or 0) < 40:
                continue
            prev = ((b0.get("pitching") or {}).get(pid) or {}).get("bf") or 0
            age = float(x.get("age") or 28) - 28.0
            share = float(x.get("gs") or 0) / max(float(x.get("g") or 1), 1.0)
            Xp.append([1.0, float(x["bf"]), float(prev), share, age])
            yp.append(float(((nx.get("pitching") or {}).get(pid) or {}).get("bf") or 0))
    out = {}
    if len(yh) >= 200:
        out["H"] = [float(c) for c in _ols(Xh, yh)]
    if len(yp) >= 200:
        out["P"] = [float(c) for c in _ols(Xp, yp)]
    return out


def fit_roles(seasons: list[int], lines: dict) -> dict:
    """Persistence of the saves and holds roles: the share of the club's saves (holds) in S+1 on the share in S, through
    the origin, over pitchers with a 10%+ share in S who pitched in S+1."""
    acc = {"sv": [0.0, 0.0, 0], "hld": [0.0, 0.0, 0]}
    for s in seasons:
        a, nx = (lines.get(s) or {}).get("pitching") or {}, (lines.get(s + 1) or {}).get("pitching") or {}
        if not a or not nx or 2020 in (s, s + 1):
            continue
        for key in ("sv", "hld"):
            tot_a = defaultdict(float)
            tot_n = defaultdict(float)
            for x in a.values():
                if x.get("team"):
                    tot_a[x["team"]] += float(x.get(key) or 0)
            for x in nx.values():
                if x.get("team"):
                    tot_n[x["team"]] += float(x.get(key) or 0)
            mean_n = (sum(tot_n.values()) / max(len(tot_n), 1)) or 1.0
            for pid, x in a.items():
                t = x.get("team")
                if not t or not tot_a.get(t):
                    continue
                sh = float(x.get(key) or 0) / tot_a[t]
                if sh < 0.1 or pid not in nx:
                    continue
                y = nx[pid]
                sh2 = float(y.get(key) or 0) / (tot_n.get(y.get("team")) or mean_n)
                c = acc[key]
                c[0] += sh * sh2
                c[1] += sh * sh
                c[2] += 1
    return {k: (round(v[0] / v[1], 4) if v[1] > 0 else 0.6) for k, v in acc.items()} | {"n": {k: v[2] for k, v in acc.items()}}


# ── steals ──────────────────────────────────────────────────────────────────

def sb_rates(pid: str, seasons: list[int], lines: dict, leagues: dict, sprint: float | None, target_lg: dict,
             k_att: float = 60.0, k_succ: float = 15.0) -> tuple[float, float]:
    """(attempts per time on first, success rate) for the target season."""
    w = (5.0, 4.0, 3.0)
    num_a = den_a = num_s = den_s = 0.0
    for i, s in enumerate(sorted(seasons, reverse=True)[:3]):
        x = ((lines.get(s) or {}).get("hitting") or {}).get(pid)
        lg = leagues.get(s) or {}
        if not x or not lg.get("att"):
            continue
        f = h_rates(x)
        if not f:
            continue
        opp = f["opp"] * float(x["pa"])
        att = float(x.get("sb") or 0) + float(x.get("cs") or 0)
        num_a += w[i] * att / lg["att"]
        den_a += w[i] * opp
        num_s += w[i] * float(x.get("sb") or 0)
        den_s += w[i] * att
    prior = 1.0 if sprint is None else max(0.15, math.exp(0.42 * (float(sprint) - SPRINT_REF)))
    rel = (num_a + k_att * prior) / (den_a + k_att)
    succ = (num_s + k_succ * target_lg.get("succ", 0.78)) / (den_s + k_succ)
    return rel * target_lg.get("att", 0.08), succ


# ── lines ───────────────────────────────────────────────────────────────────

def hitter_line(r9, pa: float, lg: dict, fit: dict, sb_att: float, sb_succ: float, rg_rel: float, slot: float) -> dict:
    r = dict(zip(EV, [float(v) for v in r9]))
    f = proj_h_feats(r9)
    sb_pa = f["opp"] * sb_att * sb_succ
    cs_pa = f["opp"] * sb_att * (1 - sb_succ)
    rc = fit.get("r") or [0, 0.35, 0.2, 0.5, 0.01, -0.002]
    bc = fit.get("rbi") or [0, 1.5, 0.15, 0.1, 0.01, -0.002]
    r_pa = max(float(np.dot(rc, r_feats(f, sb_pa, rg_rel, slot))), 0.0)
    rbi_pa = max(float(np.dot(bc, rbi_feats(f, rg_rel, slot))), 0.0)
    ab = pa * max(1.0 - r["BB"] - r["HBP"] - lg.get("sfsh", 0.009), 0.5)
    h = pa * (r["1B"] + r["2B"] + r["3B"] + r["HR"])
    return {"pa": pa, "ab": ab, "h": h, "b1": pa * r["1B"], "d": pa * r["2B"], "t": pa * r["3B"], "hr": pa * r["HR"], "bb": pa * r["BB"],
            "hbp": pa * r["HBP"], "so": pa * r["K"], "r": pa * r_pa, "rbi": pa * rbi_pa, "sb": pa * sb_pa, "cs": pa * cs_pa,
            "avg": h / ab if ab > 0 else 0.0}


def pitcher_line(r9, bf: float, gs: float, g: float, lg: dict, fit: dict, wpct: float, sv_share: float, hld_share: float,
                 team_sv: float, team_hld: float) -> dict:
    r = dict(zip(EV, [float(v) for v in r9]))
    h_bf = r["1B"] + r["2B"] + r["3B"] + r["HR"]
    outs_bf = max(1.0 - h_bf - r["BB"] - r["HBP"] - lg.get("e", 0.01), 0.4)
    outs = bf * outs_bf
    tb_bf = r["1B"] + 2 * r["2B"] + 3 * r["3B"] + 4 * r["HR"]
    runs = baseruns(bf * h_bf, bf * r["HR"], bf * (r["BB"] + r["HBP"]), bf * tb_bf, outs) * lg.get("br_mult", 1.0)
    er = runs * lg.get("er_r", 0.92)
    ip = outs / 3.0
    era = 9.0 * er / ip if ip > 0 else 0.0
    whip = bf * (h_bf + r["BB"]) / ip if ip > 0 else 0.0
    era_rel = max(min(era - lg.get("era", 4.2), 4.0), -4.0)
    wp = wpct - 0.5
    w = l = 0.0
    if gs > 0:
        x = [1.0, _outs_per_start(outs, gs, g), wp, era_rel]
        w += gs * max(float(np.dot(fit.get("w_sp") or [0.0, 0.016, 0.5, -0.02], x)), 0.0)
        l += gs * max(float(np.dot(fit.get("l_sp") or [0.3, -0.005, -0.5, 0.03], x)), 0.0)
    relief = max(g - gs, 0.0)
    if relief > 0:
        x = [1.0, wp, outs / max(g, 1.0)]
        w += relief * max(float(np.dot(fit.get("w_rp") or [0.06, 0.1, 0.0], x)), 0.0)
        l += relief * max(float(np.dot(fit.get("l_rp") or [0.06, -0.1, 0.0], x)), 0.0)
    return {"bf": bf, "outs": outs, "ip": ip, "gs": gs, "g": g, "h": bf * h_bf, "hr": bf * r["HR"], "bb": bf * r["BB"], "hbp": bf * r["HBP"],
            "so": bf * r["K"], "er": er, "era": era, "whip": whip, "w": w, "l": l, "sv": team_sv * sv_share, "hld": team_hld * hld_share}


def _outs_per_start(outs: float, gs: float, g: float) -> float:
    """Outs per start when a pitcher both starts and relieves: relief outs at about 3.3 a game."""
    relief = max(g - gs, 0.0) * 3.3
    return max(outs - relief, 0.0) / max(gs, 1e-9)


def points(line: dict, kind: str, scheme: dict | None = None) -> float:
    sc = (scheme or POINTS)[kind]
    return float(sum(v * float(line.get(k) or 0.0) for k, v in sc.items()))


def actual_line(x: dict, kind: str) -> dict:
    """An official line in the projection's keys (b1, ip, era, whip, avg)."""
    if kind == "H":
        y = {k: float(x.get(k) or 0) for k in ("pa", "ab", "h", "d", "t", "hr", "bb", "hbp", "so", "r", "rbi", "sb", "cs")}
        y["b1"] = y["h"] - y["d"] - y["t"] - y["hr"]
        y["avg"] = y["h"] / y["ab"] if y["ab"] > 0 else 0.0
        return y
    y = {k: float(x.get(k) or 0) for k in ("bf", "outs", "gs", "g", "h", "hr", "bb", "hbp", "so", "er", "w", "l", "sv", "hld")}
    y["ip"] = y["outs"] / 3.0
    y["era"] = 9.0 * y["er"] / y["ip"] if y["ip"] > 0 else 0.0
    y["whip"] = (y["h"] + y["bb"]) / y["ip"] if y["ip"] > 0 else 0.0
    return y


# ── values ──────────────────────────────────────────────────────────────────

def _contrib(lines: dict[str, dict], kind: str, pool_avg: dict) -> dict[str, dict]:
    """Per player the category numbers the z-scores use (ratio categories as volume-weighted contributions)."""
    out = {}
    for pid, x in lines.items():
        if kind == "H":
            out[pid] = {"r": x["r"], "hr": x["hr"], "rbi": x["rbi"], "sb": x["sb"], "avg": x["h"] - pool_avg["avg"] * x["ab"]}
        else:
            out[pid] = {"w": x["w"], "sv": x["sv"], "so": x["so"], "era": (pool_avg["era"] * x["ip"] - 9.0 * x["er"]) / 9.0,
                        "whip": pool_avg["whip"] * x["ip"] - (x["h"] + x["bb"])}
    return out


def zvalues(lines: dict[str, dict], kind: str, n_pool: int, iters: int = 3) -> tuple[dict[str, dict], dict]:
    """{pid: {"z": {cat: z}, "total"}} over a pool of the n_pool best by total z (found by iteration), and the pool's
    means and standard deviations."""
    cats = HIT_CATS if kind == "H" else PIT_CATS
    pids = list(lines)
    if not pids:
        return {}, {}
    vol = "ab" if kind == "H" else "ip"
    pool = sorted(pids, key=lambda p: -lines[p].get(vol, 0.0))[:n_pool]
    stats: dict = {}
    res: dict = {}
    for _ in range(iters):
        if kind == "H":
            ab = sum(lines[p]["ab"] for p in pool)
            pool_avg = {"avg": sum(lines[p]["h"] for p in pool) / max(ab, 1.0)}
        else:
            ip = sum(lines[p]["ip"] for p in pool)
            pool_avg = {"era": 9.0 * sum(lines[p]["er"] for p in pool) / max(ip, 1.0),
                        "whip": sum(lines[p]["h"] + lines[p]["bb"] for p in pool) / max(ip, 1.0)}
        C = _contrib(lines, kind, pool_avg)
        stats = {"pool": pool_avg}
        for c in cats:
            v = np.array([C[p][c] for p in pool])
            stats[c] = (float(v.mean()), float(v.std()) or 1.0)
        res = {}
        for p in pids:
            z = {c: (C[p][c] - stats[c][0]) / stats[c][1] for c in cats}
            res[p] = {"z": z, "total": float(sum(z.values()))}
        pool = sorted(pids, key=lambda p: -res[p]["total"])[:n_pool]
    return res, stats


def eligible_slots(pos: list[str], kind: str) -> list[str]:
    if kind == "P":
        return ["P"]
    out = []
    for p in pos:
        q = "OF" if p in ("LF", "CF", "RF") else p
        if q in ("C", "1B", "2B", "3B", "SS", "OF") and q not in out:
            out.append(q)
    if "1B" in out or "3B" in out:
        out.append("CI")
    if "2B" in out or "SS" in out:
        out.append("MI")
    out.append("UT")
    return out


def replacement(values: dict[str, float], elig: dict[str, list[str]]) -> tuple[dict[str, float], set]:
    """Fill a 12-team league's hitting slots greedily, scarcest first, by value; replacement level at each slot is the
    best player left eligible there. Returns ({slot: level}, drafted pids)."""
    order = ["C", "SS", "2B", "3B", "1B", "OF", "MI", "CI", "UT"]
    ranked = sorted(values, key=lambda p: -values[p])
    taken: set = set()
    level = {}
    for slot in order:
        need = TEAMS * ROSTER[slot]
        got = [p for p in ranked if p not in taken and slot in elig.get(p, [])][:need]
        taken.update(got)
        rest = [p for p in ranked if p not in taken and slot in elig.get(p, [])]
        level[slot] = values[rest[0]] if rest else (values[got[-1]] if got else 0.0)
    return level, taken


def dollars(var: dict[str, float], n_slots: int, budget_share: float) -> dict[str, float]:
    """$1 for every rostered player and the rest of the league's budget share in proportion to value above replacement."""
    pos = {p: v for p, v in var.items() if v > 0}
    top = sorted(pos, key=lambda p: -pos[p])[:n_slots]
    tot = sum(pos[p] for p in top) or 1.0
    pool = TEAMS * BUDGET * budget_share - n_slots
    return {p: (1.0 + pool * var[p] / tot) if p in top else min(1.0, 1.0 + var[p]) for p in var}


def tiers(vals: list[float], k: int = 6) -> list[int]:
    """Optimal 1-D k-means of values sorted descending (dynamic programme on squared deviations): tier numbers from 1."""
    n = len(vals)
    if n == 0:
        return []
    k = max(1, min(k, n))
    x = np.array(vals, float)
    cs, cs2 = np.concatenate([[0], np.cumsum(x)]), np.concatenate([[0], np.cumsum(x * x)])

    def cost(i, j):
        m = j - i
        s = cs[j] - cs[i]
        return (cs2[j] - cs2[i]) - s * s / m
    D = np.full((k + 1, n + 1), np.inf)
    B = np.zeros((k + 1, n + 1), dtype=int)
    D[0][0] = 0.0
    for kk in range(1, k + 1):
        for j in range(kk, n + 1):
            best, arg = np.inf, kk - 1
            for i in range(kk - 1, j):
                c = D[kk - 1][i] + cost(i, j)
                if c < best:
                    best, arg = c, i
            D[kk][j], B[kk][j] = best, arg
    out = [0] * n
    j = n
    for kk in range(k, 0, -1):
        i = B[kk][j]
        for t in range(i, j):
            out[t] = kk
        j = i
    return out


def spearman(a, b) -> float | None:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or np.std(a) == 0 or np.std(b) == 0:
        return None
    from scipy.stats import rankdata
    return float(np.corrcoef(rankdata(a), rankdata(b))[0, 1])
