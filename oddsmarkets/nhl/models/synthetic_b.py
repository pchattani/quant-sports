"""
Synthetic NHL seasons for builder B's tests and for development before real data is on disk.

`simulate_season(season, n_games, seed)` plays a small league game by game, shift by shift, and returns
frames shaped like builder A's derived tables (contract section 1): `events` (one row per event: game_id,
event_idx, period, sec, type, team, x, y normalised so the event team attacks +x, zone, shot_type, shooter,
goalie, assist1/2, faceoff winner/loser, penalty committed/drawn, situation_code, score after the event,
home_sk1..6 / away_sk1..6 and goalies) and `stints` (game_id, start, end, on-ice slots), plus a `store`
dict (games with dates, players with positions) and the planted `truth`. `write_season` writes them in
builder A's layout under the raw and data roots.

Planted effects (all recorded in `truth`):
* attempt rate per team-second = BASE_RATE * exp(sum offence of its skaters - sum defence of the opponents'
  + home + score state + zone start (first 20 s after an offensive-zone faceoff)) * strength multiplier;
  player offence/defence are the RAPM targets (log-rate units; ~ xGF/60 after scaling by the base xGF/60);
* goal probability of an unblocked attempt (true coordinates): logit = G0 - G_DIST*(d-10) - G_ANG*angle +
  shot type + rebound + rush + power play + shooter finishing - goalie skill (empty net: EN_P);
  a share of attempts miss the net (more from distance) and BLOCK_SHARE more are blocked;
* rebounds (a second attempt 0.5-3 s after a save) and rush attempts (a neutral-zone takeaway 1-4 s before);
* arena bias: before 2020-21 the scorer in ARENA_BIAS_TEAM's rink records distances x ARENA_BIAS (closer
  than true), the hand-tracking artefact the xG arena adjustment must remove;
* line deployment: the first line takes most offensive-zone starts (so zone starts need a control);
* penalties: committed / drawn by planted propensities; faceoff skill per centre.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

TEAMS = ["BOS", "TOR", "MTL", "NYR", "EDM", "CGY", "VAN", "SEA"]
BASE_RATE = 40.0 / 3600.0          # unblocked attempts per team-second at 5v5
BLOCK_SHARE = 0.32                 # blocked attempts per unblocked attempt
OFF_SD, DEF_SD = 0.09, 0.07
HOME_RATE = 0.04
ZS_BOOST = 0.5                     # extra log-rate in the first ZS_SECONDS after an offensive-zone faceoff
ZS_SECONDS = 20.0
SCORE_RATE = 0.07                  # per goal of deficit (trailing teams shoot more), capped at 3
PP_MULT, PK_MULT = 1.9, 0.45
G0, G_DIST, G_ANG = -1.95, 0.07, 0.012
SHOT_EFF = {"wrist": 0.0, "snap": 0.15, "slap": 0.05, "backhand": -0.25, "tip-in": 0.35, "deflected": 0.3,
            "wrap-around": -0.4}
SHOT_P = {"wrist": 0.5, "snap": 0.15, "slap": 0.12, "backhand": 0.1, "tip-in": 0.08, "deflected": 0.03, "wrap-around": 0.02}
REBOUND_EFF, RUSH_EFF, PP_EFF = 1.1, 0.55, 0.3
REBOUND_P, RUSH_P = 0.10, 0.14
FINISH_SD, SAVE_SD = 0.22, 0.18
EN_P = 0.55
ARENA_BIAS_TEAM = "BOS"
ARENA_BIAS = 0.78
PEN_RATE = 3.3 / 3600.0            # minors per team-second
DAY0 = {20182019: "2018-10-04", 20222023: "2022-10-11", 20252026: "2025-10-07", 20262027: "2026-10-07"}


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def make_league(seed: int = 7, n_teams: int = 8) -> dict:
    """Rosters and planted talents: 12 forwards (4 lines: C, LW, RW), 6 defence, 2 goalies per team. The
    same ids persist across seasons (talents carry with small drift in `simulate_season`)."""
    rng = np.random.default_rng(seed)
    teams = {}
    codes = TEAMS[:n_teams] + [f"T{j:02d}" for j in range(max(0, n_teams - len(TEAMS)))]
    for i, t in enumerate(codes):
        base = 8_470_000 + i * 100
        f = [base + k for k in range(12)]
        d = [base + 20 + k for k in range(6)]
        g = [base + 40, base + 41]
        teams[t] = {"F": f, "D": d, "G": g, "pos": {**{p: ("C" if k % 3 == 0 else ("L" if k % 3 == 1 else "R")) for k, p in enumerate(f)},
                                                    **{p: "D" for p in d}, **{p: "G" for p in g}}}
    truth = {"off": {}, "def": {}, "finish": {}, "save": {}, "pen_take": {}, "pen_draw": {}, "fo": {}, "team": {}}
    for t, r in teams.items():
        for p in r["F"] + r["D"]:
            dsc = 0.7 if p in r["D"] else 1.0
            truth["off"][p] = float(rng.normal(0, OFF_SD * dsc))
            truth["def"][p] = float(rng.normal(0, DEF_SD))
            truth["finish"][p] = float(rng.normal(0, FINISH_SD))
            truth["pen_take"][p] = float(np.exp(rng.normal(0, 0.35)))
            truth["pen_draw"][p] = float(np.exp(rng.normal(0, 0.35)))
        for p in r["F"][::3]:
            truth["fo"][p] = float(rng.normal(0, 0.25))
        for p in r["G"]:
            truth["save"][p] = float(rng.normal(0, SAVE_SD))
    return {"teams": teams, "truth": truth}


def _schedule(rng, teams: list[str], n_games: int, day0: str) -> list[tuple[str, str, str]]:
    out = []
    d = pd.Timestamp(day0)
    pairs = [(h, a) for h in teams for a in teams if h != a]
    k = 0
    while len(out) < n_games:
        order = rng.permutation(len(pairs))
        for j in order:
            if len(out) >= n_games:
                break
            h, a = pairs[j]
            out.append((h, a, (d + pd.Timedelta(days=k // (len(teams) // 2))).strftime("%Y-%m-%d")))
            k += 1
    return out


class _Game:
    """State for one simulated game (plain object; no closures)."""

    def __init__(self):
        self.ev: list[dict] = []
        self.stints: list[list] = []


def _lines(rng, r: dict) -> tuple[list[list[int]], list[list[int]]]:
    f = list(r["F"])
    lines = [f[0:3], f[3:6], f[6:9], f[9:12]]
    # line juggling: occasionally swap wingers between adjacent lines (breaks perfect collinearity)
    for _ in range(2):
        if rng.random() < 0.45:
            a = int(rng.integers(0, 3))
            i, j = int(rng.integers(1, 3)), int(rng.integers(1, 3))
            lines[a][i], lines[a + 1][j] = lines[a + 1][j], lines[a][i]
    d = list(r["D"])
    pairs = [d[0:2], d[2:4], d[4:6]]
    if rng.random() < 0.35:
        i, j = int(rng.integers(0, 2)), int(rng.integers(0, 2))
        pairs[0][i], pairs[1][j] = pairs[1][j], pairs[0][i]
    return lines, pairs


def _shift_changes(rng, n_units: int, weights: list[float], lo: float, hi: float, t0: float, t1: float) -> list[tuple[float, int]]:
    """(time, unit) changes over [t0, t1): units rotate in order with lengths scaled by weights."""
    out, t, u = [], t0, 0
    while t < t1:
        out.append((t, u))
        t += float(rng.uniform(lo, hi)) * weights[u]
        u = (u + 1) % n_units
    return out


def _unit_at(changes: list[tuple[float, int]], t: float) -> int:
    u = changes[0][1]
    for tt, uu in changes:
        if tt <= t:
            u = uu
        else:
            break
    return u


def _xy(rng, dist: float, ang_deg: float) -> tuple[float, float]:
    a = math.radians(ang_deg)
    return 89.0 - dist * math.cos(a), (1 if rng.random() < 0.5 else -1) * dist * math.sin(a)


def simulate_game(rng, league: dict, gid: int, home: str, away: str, season: int, truth: dict) -> _Game:
    T = league["teams"]
    g = _Game()
    sides = {"h": home, "a": away}
    lines = {s: _lines(rng, T[sides[s]]) for s in sides}
    goalie = {s: (T[sides[s]]["G"][0] if rng.random() < 0.7 else T[sides[s]]["G"][1]) for s in sides}
    score = {"h": 0, "a": 0}
    bias_arena = season < 20202021 and home == ARENA_BIAS_TEAM
    idx = [0]

    def_ = truth["def"]
    off = truth["off"]

    def add(**kw):
        kw["event_idx"] = idx[0]
        idx[0] += 1
        g.ev.append(kw)

    # penalties (pre-drawn): (time, side that takes it)
    pens = []
    for s in ("h", "a"):
        n = rng.poisson(PEN_RATE * 3600)
        for t in np.sort(rng.uniform(30, 3550, n)):
            pens.append((float(t), s))
    pens.sort()
    pk_until = {"h": -1.0, "a": -1.0}       # side shorthanded until

    for period in (1, 2, 3, 4):
        t0 = (period - 1) * 1200.0
        t1 = t0 + 1200.0 if period < 4 else t0 + 300.0
        if period == 4:
            if score["h"] != score["a"]:
                break
        add(game_id=gid, period=period, sec=t0, type="period-start", team=None)
        fch = {s: _shift_changes(rng, 4, [1.25, 1.1, 0.9, 0.7], 34, 52, t0, t1) for s in sides}
        dch = {s: _shift_changes(rng, 3, [1.15, 1.0, 0.85], 40, 60, t0, t1) for s in sides}
        pts = sorted({t0, t1, *[t for s in sides for t, _ in fch[s] + dch[s]],
                      *[t for t, _ in pens if t0 < t < t1], *[pk_until[s] for s in sides if t0 < pk_until[s] < t1]})
        pts = [p for p in pts if t0 <= p <= t1]
        if period == 3 and abs(score["h"] - score["a"]) in (1, 2) and 3510 not in pts:
            pts = sorted(set(pts + [3510.0]))
        pen_iter = [p for p in pens if t0 < p[0] < t1]
        k = 0
        while k < len(pts) - 1:
            a, b = pts[k], pts[k + 1]
            k += 1
            if b - a < 0.5:
                continue
            for pt, ps in pen_iter:
                if abs(pt - a) < 1e-9 and pk_until[ps] < a:
                    pk_until[ps] = a + 120.0
                    oth = "a" if ps == "h" else "h"
                    on_s = lines[ps][0][_unit_at(fch[ps], a)] + lines[ps][1][_unit_at(dch[ps], a)]
                    on_o = lines[oth][0][_unit_at(fch[oth], a)] + lines[oth][1][_unit_at(dch[oth], a)]
                    wt = np.array([truth["pen_take"][p] for p in on_s])
                    wd = np.array([truth["pen_draw"][p] for p in on_o])
                    taker = on_s[int(rng.choice(len(on_s), p=wt / wt.sum()))]
                    drawer = on_o[int(rng.choice(len(on_o), p=wd / wd.sum()))]
                    add(game_id=gid, period=period, sec=a, type="penalty", team=sides[ps], committed_by=taker,
                        drawn_by=drawer, penalty_minutes=2, zone="N", x=0.0, y=0.0)
                    if pk_until[ps] < t1 and pk_until[ps] not in pts:
                        pts = sorted(set(pts + [pk_until[ps]]))
            on, gl = {}, {}
            for s in sides:
                fl = lines[s][0][_unit_at(fch[s], a)]
                dp = lines[s][1][_unit_at(dch[s], a)]
                sk = list(fl) + list(dp)
                if period == 4:
                    sk = [fl[0], fl[1], dp[0]]
                elif pk_until[s] > a:
                    sk = [fl[0], fl[1], dp[0], dp[1]]
                gl[s] = goalie[s]
                on[s] = sk
            # empty net in the last 90 s when trailing by 1-2
            if period == 3 and a >= 3510 and abs(score["h"] - score["a"]) in (1, 2):
                trail = "h" if score["h"] < score["a"] else "a"
                gl[trail] = None
                on[trail] = on[trail] + [lines[trail][0][(_unit_at(fch[trail], a) + 1) % 4][0]]
            # faceoff at the stint start (60%), zone from the home view; the first line gets offensive starts
            fo_zone = None
            if a == t0 or rng.random() < 0.22:
                if a == t0:
                    fo_zone = "N"
                else:
                    first_h = on["h"][0] == lines["h"][0][0][0]
                    first_a = on["a"][0] == lines["a"][0][0][0]
                    po = 0.33 + 0.25 * first_h - 0.25 * first_a
                    u = rng.random()
                    fo_zone = "O" if u < po else ("D" if u < po + 0.34 else "N")
                ch, ca = on["h"][0], on["a"][0]
                fh, fa = truth["fo"].get(ch, 0.0), truth["fo"].get(ca, 0.0)
                hw = rng.random() < _sig(fh - fa)
                win_side = "h" if hw else "a"
                zone_w = fo_zone if hw else {"O": "D", "D": "O", "N": "N"}[fo_zone]
                xw = {"O": 69.0, "D": -69.0, "N": 0.0}[zone_w]
                add(game_id=gid, period=period, sec=a, type="faceoff", team=sides[win_side], winner=ch if hw else ca,
                    loser=ca if hw else ch, zone=zone_w, x=xw, y=22.0 if fo_zone != "N" else 0.0)
            g.stints.append([gid, a, b, list(on["h"]), list(on["a"]), gl["h"], gl["a"]])
            # attempts per side
            att = []
            for s in sides:
                o = "a" if s == "h" else "h"
                lr = sum(off[p] for p in on[s]) - sum(def_[p] for p in on[o])
                lr += HOME_RATE if s == "h" else -HOME_RATE
                lr += SCORE_RATE * min(max(score[o] - score[s], -3), 3)
                n_s, n_o = len(on[s]), len(on[o])
                mult = PP_MULT if n_s > n_o and gl[o] is not None else (PK_MULT if n_s < n_o and gl[s] is not None else 1.0)
                if period == 4:
                    mult = 1.5
                rate = BASE_RATE * math.exp(lr) * mult
                n = rng.poisson(rate * (b - a))
                ts = list(rng.uniform(a, b, n))
                if fo_zone is not None:
                    zs_for = fo_zone == ("O" if s == "h" else "D")
                    if zs_for:
                        zl = min(ZS_SECONDS, b - a)
                        n2 = rng.poisson(rate * (math.exp(ZS_BOOST) - 1) * zl)
                        ts += list(rng.uniform(a, a + zl, n2))
                nb = rng.poisson(rate * BLOCK_SHARE * (b - a))
                for t in ts:
                    att.append((float(t), s, "u"))
                for t in rng.uniform(a, b, nb):
                    att.append((float(t), s, "b"))
            att.sort()
            last_t = -10.0
            for t, s, kind in att:
                if t <= last_t + 0.3 or t >= b:
                    continue
                last_t = t
                o = "a" if s == "h" else "h"
                shooter = on[s][int(rng.integers(0, len(on[s])))] if rng.random() < 0.15 else \
                    on[s][min(int(rng.choice(len(on[s]), p=_shoot_w(len(on[s])))), len(on[s]) - 1)]
                is_d = shooter in T[sides[s]]["D"]
                dist = float(np.clip(4 + rng.gamma(2.0, 9.5 if not is_d else 16.0), 3, 95))
                ang = float(np.clip(abs(rng.normal(0, 30)), 0, 85))
                st_ = list(SHOT_P)[int(rng.choice(len(SHOT_P), p=np.array(list(SHOT_P.values()))))]
                rush = rng.random() < RUSH_P
                if rush:
                    tr = max(a + 0.01, t - float(rng.uniform(1.0, 3.8)))
                    add(game_id=gid, period=period, sec=round(tr, 2), type="takeaway", team=sides[s], zone="N",
                        x=float(rng.uniform(-20, 20)), y=float(rng.uniform(-30, 30)), shooter=on[s][0])
                    dist = float(np.clip(dist * 0.9, 3, 95))
                if kind == "b":
                    x, y = _xy(rng, dist, ang)
                    add(game_id=gid, period=period, sec=round(t, 2), type="blocked-shot", team=sides[s], shooter=shooter,
                        x=x, y=y, zone="O", shot_type=st_, blocker=on[o][int(rng.integers(0, len(on[o])))])
                    continue
                chain = [(t, rush, False)]
                while chain:
                    tt, rsh, reb = chain.pop()
                    pp = len(on[s]) > len(on[o]) and gl[o] is not None
                    en = gl[o] is None
                    x, y = _xy(rng, dist, ang)
                    if bias_arena:
                        xr, yr = 89.0 - (89.0 - x) * ARENA_BIAS, y * ARENA_BIAS
                    else:
                        xr, yr = x, y
                    xr, yr = round(xr), round(yr)
                    miss_p = min(0.6, 0.2 + 0.006 * dist)
                    lg = (G0 - G_DIST * (dist - 10) - G_ANG * ang + SHOT_EFF[st_] + REBOUND_EFF * reb + RUSH_EFF * rsh
                          + PP_EFF * pp + truth["finish"].get(shooter, 0.0) - (truth["save"].get(gl[o], 0.0) if gl[o] else 0.0))
                    p_goal = EN_P if en else float(_sig(lg))
                    u = rng.random()
                    if u < p_goal:
                        assists = [p for p in on[s] if p != shooter]
                        rng.shuffle(assists)
                        na = int(rng.choice(3, p=[0.1, 0.3, 0.6]))
                        add(game_id=gid, period=period, sec=round(tt, 2), type="goal", team=sides[s], shooter=shooter,
                            goalie=gl[o], x=xr, y=yr, zone="O", shot_type=st_, assist1=assists[0] if na >= 1 else None,
                            assist2=assists[1] if na >= 2 else None)
                        score[s] += 1
                        if pp and pk_until[o] > tt:
                            pk_until[o] = tt
                        break
                    if u < p_goal + miss_p * (1 - p_goal):
                        add(game_id=gid, period=period, sec=round(tt, 2), type="missed-shot", team=sides[s], shooter=shooter,
                            goalie=gl[o], x=xr, y=yr, zone="O", shot_type=st_)
                        break
                    add(game_id=gid, period=period, sec=round(tt, 2), type="shot-on-goal", team=sides[s], shooter=shooter,
                        goalie=gl[o], x=xr, y=yr, zone="O", shot_type=st_)
                    if not reb and rng.random() < REBOUND_P and tt + 3 < b:
                        t2 = tt + float(rng.uniform(0.5, 2.9))
                        shooter = on[s][int(rng.integers(0, len(on[s])))]
                        dist = float(np.clip(rng.gamma(2.0, 4.0) + 3, 3, 40))
                        ang = float(np.clip(abs(rng.normal(0, 35)), 0, 85))
                        st_ = "wrist" if rng.random() < 0.5 else ("backhand" if rng.random() < 0.5 else "tip-in")
                        chain.append((t2, False, True))
                        last_t = t2
            # filler events (hits, giveaways) so previous-event features see a realistic mix
            for t in rng.uniform(a, b, rng.poisson((b - a) * 50 / 3600)):
                s = "h" if rng.random() < 0.5 else "a"
                ty = "hit" if rng.random() < 0.6 else "giveaway"
                xx = float(rng.uniform(-99, 99))
                add(game_id=gid, period=period, sec=round(float(t), 2), type=ty, team=sides[s],
                    x=xx, y=float(rng.uniform(-40, 40)), zone="O" if xx > 25 else ("D" if xx < -25 else "N"),
                    shooter=on[s][0])
        add(game_id=gid, period=period, sec=t1, type="period-end", team=None)
    if score["h"] == score["a"]:
        # shootout (period 5): three rounds, the winner decided at random; goals do not count in score state
        w = "h" if rng.random() < 0.5 else "a"
        for r in range(3):
            for s in ("a", "h"):
                o = "a" if s == "h" else "h"
                scorer = lines[s][0][0][r % 3]
                typ = "goal" if (s == w and r == 2) else "shot-on-goal"
                add(game_id=gid, period=5, sec=3900.0, type=typ, team=sides[s], shooter=scorer, goalie=goalie[o], x=75.0,
                    y=0.0, zone="O", shot_type="wrist")
    g.final = dict(score)
    return g


def _shoot_w(n: int) -> np.ndarray:
    w = np.array([1.5, 1.4, 1.4, 0.8, 0.8, 1.0, 1.0][:n], float)
    return w / w.sum()


def _situation(nh: int, na: int, gh, ga) -> str:
    return f"{int(ga is not None)}{na}{nh}{int(gh is not None)}"


def simulate_season(season: int = 20222023, n_games: int = 240, seed: int = 11, league: dict | None = None,
                    n_teams: int = 8) -> dict:
    """{"events": DataFrame, "stints": DataFrame, "store": dict, "truth": dict, "league": dict}."""
    league = league or make_league(seed, n_teams)
    rng = np.random.default_rng(seed * 1000 + season % 10000)
    truth = league["truth"]
    teams = list(league["teams"])
    sched = _schedule(rng, teams, n_games, DAY0.get(season, f"{season // 10000}-10-08"))
    ev_rows, st_rows, games = [], [], []
    for k, (h, a, day) in enumerate(sched):
        gid = (season // 10000) * 1_000_000 + 20000 + k + 1
        g = simulate_game(rng, league, gid, h, a, season, truth)
        # on-ice slots and situation per event from the stints
        st = g.stints
        starts = np.array([s[1] for s in st])
        for e in g.ev:
            t = e["sec"]
            if e.get("period", 1) >= 5 or e["type"] in ("period-start", "period-end"):
                j = None
            elif e["type"] in ("faceoff", "penalty"):
                j = int(np.searchsorted(starts, t, side="right") - 1)
            else:
                j = int(np.searchsorted(starts, t, side="left") - 1)
            row = dict(e)
            if j is not None and j >= 0:
                s = st[j]
                for i in range(6):
                    row[f"home_sk{i + 1}"] = s[3][i] if i < len(s[3]) else None
                    row[f"away_sk{i + 1}"] = s[4][i] if i < len(s[4]) else None
                row["home_goalie"], row["away_goalie"] = s[5], s[6]
                row["situation_code"] = _situation(len(s[3]), len(s[4]), s[5], s[6])
            row["home_team"], row["away_team"] = h, a
            ev_rows.append(row)
        for s in st:
            r = {"game_id": s[0], "start": s[1], "end": s[2], "home_goalie": s[5], "away_goalie": s[6]}
            for i in range(6):
                r[f"home_sk{i + 1}"] = s[3][i] if i < len(s[3]) else None
                r[f"away_sk{i + 1}"] = s[4][i] if i < len(s[4]) else None
            st_rows.append(r)
        games.append({"game_id": gid, "date": day, "home": h, "away": a, "hs": g.final["h"], "as": g.final["a"],
                      "type": 2, "status": "final", "venue": f"{h} Arena"})
    ev = pd.DataFrame(ev_rows)
    # score after each event (as the NHL feed reports it)
    gl = (ev["type"] == "goal") & (ev["period"] < 5)
    ev["score_home"] = (gl & (ev["team"] == ev["home_team"])).astype(int).groupby(ev["game_id"]).cumsum()
    ev["score_away"] = (gl & (ev["team"] == ev["away_team"])).astype(int).groupby(ev["game_id"]).cumsum()
    for c in [c for c in ev.columns if c.startswith(("home_sk", "away_sk")) or c in (
            "home_goalie", "away_goalie", "shooter", "goalie", "assist1", "assist2", "winner", "loser", "committed_by",
            "drawn_by", "blocker")]:
        ev[c] = pd.to_numeric(ev[c], errors="coerce").astype("Int64")
    stn = pd.DataFrame(st_rows)
    for c in [c for c in stn.columns if c not in ("game_id", "start", "end")]:
        stn[c] = pd.to_numeric(stn[c], errors="coerce").astype("Int64")
    players = {}
    for t, r in league["teams"].items():
        for p, pos in r["pos"].items():
            players[str(p)] = {"name": f"{t} {pos} {p % 100}", "pos": pos, "team": t, "shoots": "L" if p % 3 else "R"}
    store = {"season": season, "teams": teams, "games": games, "players": players}
    return {"events": ev, "stints": stn, "store": store, "truth": truth, "league": league}


def write_season(sim: dict, season: int, raw_root: Path, data_root: Path) -> None:
    d = Path(raw_root) / "derived" / str(season)
    d.mkdir(parents=True, exist_ok=True)
    sim["events"].to_parquet(d / "events.parquet", index=False)
    sim["stints"].to_parquet(d / "stints.parquet", index=False)
    s = Path(data_root) / str(season)
    s.mkdir(parents=True, exist_ok=True)
    import json
    (s / "store.json").write_text(json.dumps(sim["store"]), encoding="utf-8")


def build(raw_root: Path, data_root: Path, seasons=(20182019, 20222023), n_games: int = 240, seed: int = 11) -> dict:
    """Simulate and write several seasons with one league (talents fixed); returns {season: sim}."""
    league = make_league(seed)
    out = {}
    for s in seasons:
        sim = simulate_season(s, n_games, seed, league)
        write_season(sim, s, raw_root, data_root)
        out[s] = sim
    return out
