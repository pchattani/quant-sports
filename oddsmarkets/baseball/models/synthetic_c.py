"""
Synthetic seasons for builder C's tests: a pitch-by-pitch game simulator that writes Savant-shaped
pitch rows (the contract's column names) plus a store dict, with planted truth:

* called strikes: logit = 9 * signed distance to the rulebook zone (ft) + count shift
  + catcher framing effect (log-odds, `truth["catcher"]`) + umpire zone effect (`truth["umpire"]`);
* batted balls: launch speed / angle / pull angle drawn from batter traits; outcomes from the
  geometry (spray against infielder angles and outfield walls at that spray, launch physics carry
  scaled by park elevation, temperature and wind, hang time against fielder range), so spray and
  park matter beyond exit velocity and launch angle;
* fielder range (`truth["fielder"]`, ft/s for outfielders, degrees for infielders), batter speed
  (`truth["speed"]`, ft/s) which drives infield hits, extra bases taken, triples and steals;
* every plate appearance's start state and the runs scored from it to the end of its half-inning
  (`truth["pa"]`), for the hand-computed RE24 check.
"""
from __future__ import annotations

import datetime as dt
import math
import random

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

ZONE_HALF = 0.83          # half plate + ball radius, ft
EDGE_PAD = 0.12           # ball radius, ft (top / bottom)
WOBA_W = {"BB": 0.69, "HBP": 0.72, "1B": 0.88, "2B": 1.25, "3B": 1.58, "HR": 2.03}
IF_ANGLES = {3: 32.0, 4: 13.0, 6: -13.0, 5: -32.0}      # field spray angle of each infielder (RHB standard)
IF_DEPTH = {3: 105.0, 4: 145.0, 6: 145.0, 5: 115.0}
OF_POS = {7: (-28.0, 295.0), 8: (0.0, 320.0), 9: (28.0, 295.0)}
DIMS_STD = {"lf": 330, "lcf": 375, "cf": 400, "rcf": 375, "rf": 330}
_TAB: dict = {}


def _flight_table():
    if not _TAB:
        ev = np.arange(20, 126, 1.0)
        la = np.arange(-90, 91, 1.0)
        E, L = np.meshgrid(ev, la, indexing="ij")
        r = _c.flight(E.ravel(), L.ravel())
        _TAB["hang"] = r["hang"].reshape(E.shape)
        _TAB["dist"] = r["dist"].reshape(E.shape)
    return _TAB


def _fl(ev: float, la: float) -> tuple[float, float]:
    t = _flight_table()
    i = int(min(max(round(ev) - 20, 0), 105)); j = int(min(max(round(la) + 90, 0), 180))
    return float(t["hang"][i, j]), float(t["dist"][i, j])


def wall_at(dims: dict, spray: float) -> float:
    """Fence distance at a field spray angle (deg, -45 = LF line, +45 = RF line), linear between the five points."""
    xs = [-45.0, -22.5, 0.0, 22.5, 45.0]
    ys = [dims["lf"], dims["lcf"], dims["cf"], dims["rcf"], dims["rf"]]
    return float(np.interp(spray, xs, ys))


def _signed_zone_dist(px: float, pz: float, bot: float, top: float) -> float:
    dx = ZONE_HALF - abs(px)
    dz = min(pz - (bot - EDGE_PAD), (top + EDGE_PAD) - pz)
    if dx >= 0 and dz >= 0:
        return min(dx, dz)
    return -math.hypot(min(dx, 0.0), min(dz, 0.0))


def synth_season(n_teams: int = 10, n_games: int = 400, season: int = 2025, seed: int = 0, level: str = "mlb",
                 framing_sd: float = 0.25, umpire_sd: float = 0.15, n_umpires: int = 16, steal: bool = True,
                 extra_runner: bool = True) -> tuple[pd.DataFrame, dict, dict]:
    """Simulate `n_games` games among `n_teams` teams. Returns (pitches, store, truth)."""
    R = random.Random(seed)
    rng = np.random.default_rng(seed)
    pid = [700000]

    def new_id():
        pid[0] += 1
        return pid[0]

    teams, venues, players = {}, {}, {}
    bat_traits, fld_skill, speed = {}, {}, {}
    catcher_eff, team_def, lineups, catchers, staffs = {}, {}, {}, {}, {}
    for t in range(n_teams):
        tid = 100 + t
        abbr = f"T{t:02d}"
        dims = dict(DIMS_STD)
        walls = {k: 8 for k in DIMS_STD}
        elev = 500
        if t == 0:
            dims = {"lf": 312, "lcf": 360, "cf": 390, "rcf": 362, "rf": 314}
        elif t == 1:
            dims = {"lf": 345, "lcf": 392, "cf": 418, "rcf": 392, "rf": 345}
        elif t == 2:
            elev = 5200
        elif t == 3:
            dims = {"lf": 310, "lcf": 379, "cf": 390, "rcf": 380, "rf": 302}
            walls["lf"] = 37
        vid = 1000 + t
        venues[str(vid)] = {"name": f"Park {t}", "city": "", "lat": 40.0, "lon": -75.0, "elev_ft": elev,
                            "roof": "open", "dims": dims, "walls": walls}
        teams[str(tid)] = {"name": f"Team {t}", "abbr": abbr, "short": abbr, "league": "AL" if t % 2 else "NL",
                           "division": "", "venue": str(vid), "colour": "#000"}
        roster = {}
        for pos in range(3, 10):
            roster[pos] = new_id()
        cs = [new_id(), new_id()]
        dh = new_id()
        catchers[abbr] = cs
        for c in cs:
            catcher_eff[c] = rng.normal(0, framing_sd)
        team_def[abbr] = roster
        lineup = [roster[p] for p in (8, 4, 3, 9, 5, 7, 6)] + [dh, None]   # None = today's catcher
        lineups[abbr] = lineup
        staffs[abbr] = {"sp": [new_id() for _ in range(5)], "rp": [new_id() for _ in range(4)]}
        for pos, p in roster.items():
            fld_skill[p] = (rng.normal(27.0, 1.5) if pos >= 7 else rng.normal(0.0, 2.0))
        hitters = list(roster.values()) + cs + [dh]
        for h in hitters:
            bat_traits[h] = {"ev": rng.normal(88.0, 3.0), "la": rng.normal(12.0, 5.0), "pull": rng.normal(6.0, 6.0),
                             "eye": float(np.clip(rng.normal(0.28, 0.05), 0.12, 0.45)),
                             "contact": float(np.clip(rng.normal(0.78, 0.05), 0.6, 0.92)),
                             "stand": "L" if rng.random() < 0.4 else "R"}
            speed[h] = float(rng.normal(27.0, 1.3))
            players[str(h)] = {"name": f"Player {h}", "short": f"P{h}", "bats": bat_traits[h]["stand"], "throws": "R",
                               "pos": "C" if h in cs else "DH" if h == dh else str([k for k, v in roster.items() if v == h][0]),
                               "dob": None, "debut": None, "retro": None, "bbref": None, "fg": None}
        for p in staffs[abbr]["sp"] + staffs[abbr]["rp"]:
            players[str(p)] = {"name": f"Pitcher {p}", "short": f"P{p}", "bats": "R",
                               "throws": "L" if rng.random() < 0.3 else "R", "pos": "P", "dob": None, "debut": None,
                               "retro": None, "bbref": None, "fg": None}
    # planted extremes so the framing test has clear signal
    allc = [c for cs in catchers.values() for c in cs]
    catcher_eff[allc[0]] = 0.6
    catcher_eff[allc[1]] = -0.6
    umps = [new_id() for _ in range(n_umpires)]
    ump_eff = {u: float(rng.normal(0, umpire_sd)) for u in umps}
    abbrs = [teams[k]["abbr"] for k in sorted(teams)]
    abbr_tid = {teams[k]["abbr"]: k for k in teams}

    rows: list[dict] = []
    truth_pa: list[dict] = []
    sb_log: list[tuple] = []
    games = {}
    d0 = dt.date(season, 3, 28)
    for g in range(n_games):
        hi, ai = R.sample(range(n_teams), 2)
        home, away = abbrs[hi], abbrs[ai]
        gpk = 800000 + g
        date = d0 + dt.timedelta(days=int(g * 182 / max(n_games, 1)))
        venue = teams[abbr_tid[home]]["venue"]
        vinfo = venues[venue]
        temp = float(rng.normal(72, 10))
        wind_mph = int(rng.integers(0, 15))
        wind_dir = R.choice(["Out To CF", "In From CF", "L To R", "R To L", "Calm"])
        if wind_dir == "Calm":
            wind_mph = 0
        wind_out = wind_mph if wind_dir.startswith("Out") else -wind_mph if wind_dir.startswith("In") else 0
        carry = (1 + 0.0018 * (temp - 72)) * (1 + 0.008 * wind_out) * (1 + 0.05 * (vinfo["elev_ft"] > 3000))
        ump = umps[g % n_umpires] if R.random() < 0.9 else R.choice(umps)
        cat = {home: catchers[home][g % 2], away: catchers[away][(g + 1) % 2]}
        sp_ = {home: staffs[home]["sp"][g % 5], away: staffs[away]["sp"][(g + 2) % 5]}
        score = {home: 0, away: 0}
        lpos = {home: 0, away: 0}
        ab_no = 0
        inning = 1
        final = False
        while not final:
            for half in (0, 1):
                bat, fld = (away, home) if half == 0 else (home, away)
                if half == 1 and inning >= 9 and score[home] > score[away]:
                    final = True
                    break
                outs = 0
                bases = [None, None, None]
                if inning >= 10 and extra_runner:
                    bases[1] = lineups[bat][(lpos[bat] - 1) % 9] or cat[bat]
                pitcher = sp_[fld] if inning <= 6 else staffs[fld]["rp"][(inning + g) % 4]
                fielders = {2: cat[fld], **team_def[fld]}
                half_pas = []
                walkoff = False
                while outs < 3:
                    batter = lineups[bat][lpos[bat] % 9] or cat[bat]
                    lpos[bat] += 1
                    ab_no += 1
                    tr = bat_traits[batter]
                    stand = tr["stand"]
                    pa_start = {"outs": outs, "bases": (bases[0] is not None) * 1 + (bases[1] is not None) * 2 + (bases[2] is not None) * 4,
                                "bat_score": score[bat], "hkey": (gpk, inning, half)}
                    half_pas.append(pa_start)
                    balls = strikes = 0
                    pn = 0
                    ev_ = None
                    bip = None
                    runs_pa = 0
                    sz_bot, sz_top = 1.55 + rng.normal(0, 0.05), 3.40 + rng.normal(0, 0.05)
                    while True:
                        pn += 1
                        base_row = {"game_pk": gpk, "game_date": date.isoformat(), "game_type": "R", "at_bat_number": ab_no,
                                    "pitch_number": pn, "pitcher": pitcher, "batter": batter, "stand": stand,
                                    "p_throws": players[str(pitcher)]["throws"], "home_team": home, "away_team": away,
                                    "inning": inning, "inning_topbot": "Top" if half == 0 else "Bot", "outs_when_up": outs,
                                    "balls": balls, "strikes": strikes, "on_1b": bases[0], "on_2b": bases[1], "on_3b": bases[2],
                                    "bat_score": score[bat], "fld_score": score[fld], "umpire": ump, "sz_top": sz_top,
                                    "sz_bot": sz_bot, "if_fielding_alignment": "Standard", "of_fielding_alignment": "Standard",
                                    **{f"fielder_{k}": v for k, v in fielders.items()}}
                        ptype = R.choice(["FF", "FF", "SI", "SL", "CH", "CU"])
                        px, pz = rng.normal(0, 0.85), rng.normal(2.45, 0.85)
                        row = {**base_row, "pitch_type": ptype, "release_speed": 94.0 if ptype in ("FF", "SI") else 85.0,
                               "plate_x": px, "plate_z": pz}
                        if pn == 1 and R.random() < 0.009:
                            row.update(description="hit_by_pitch", type="B", events="hit_by_pitch")
                            ev_ = "HBP"
                        else:
                            sd = _signed_zone_dist(px, pz, sz_bot, sz_top)
                            in_zone = sd >= 0
                            swing_p = (0.66 if in_zone else tr["eye"]) + (0.08 if strikes == 2 else 0.0)
                            if R.random() < swing_p:
                                if R.random() < tr["contact"] * (1.0 if in_zone else 0.75):
                                    if R.random() < 0.45:
                                        row.update(description="foul", type="S")
                                        strikes = min(strikes + 1, 2)
                                    else:
                                        row.update(description="hit_into_play", type="X")
                                        ev_ = "BIP"
                                else:
                                    row.update(description="swinging_strike", type="S")
                                    strikes += 1
                            else:
                                cshift = 0.35 if (balls == 3 and strikes == 0) else -0.45 if (strikes == 2 and balls < 2) else 0.0
                                logit = 9.0 * sd + cshift + catcher_eff[fielders[2]] + ump_eff[ump] - 0.05
                                if R.random() < 1 / (1 + math.exp(-logit)):
                                    row.update(description="called_strike", type="S")
                                    strikes += 1
                                else:
                                    row.update(description="ball", type="B")
                                    balls += 1
                            if strikes >= 3:
                                ev_ = "K"
                                row["events"] = "strikeout"
                            elif balls >= 4:
                                ev_ = "BB"
                                row["events"] = "walk"
                        if ev_ == "BIP":
                            bip = _batted_ball(R, rng, tr, speed[batter], fielders, fld_skill, vinfo["dims"], vinfo["walls"],
                                               carry, outs, bases)
                            row.update({k: bip[k] for k in ("events", "bb_type", "launch_speed", "launch_angle",
                                                             "hit_distance_sc", "hc_x", "hc_y", "hit_location")})
                        rows.append(row)
                        if ev_ is not None:
                            break
                        # steal attempt during the first pitch (the row keeps the state before it)
                        if steal and pn == 1 and bases[0] is not None and bases[1] is None:
                            r1 = bases[0]
                            if speed[r1] > 27.5 and R.random() < 0.25:
                                if R.random() < 0.55 + 0.08 * (speed[r1] - 27):
                                    bases[1], bases[0] = r1, None
                                    sb_log.append((gpk, r1, 1))
                                else:
                                    bases[0] = None
                                    outs += 1
                                    sb_log.append((gpk, r1, 0))
                                    if outs >= 3:
                                        row["events"] = "caught_stealing_2b"
                                        row["post_bat_score"] = score[bat]
                                        ev_ = "cs_end"
                                        lpos[bat] -= 1      # the batter leads off next inning
                                        break
                    if ev_ == "cs_end":
                        break
                    # advance runners
                    outs, bases, runs_pa = _advance(R, ev_, bip, outs, bases, batter, speed)
                    if half == 1 and inning >= 9 and score[home] + runs_pa > score[away]:
                        walkoff = True
                    score[bat] += runs_pa
                    last = rows[-1]
                    if ev_ == "BIP":
                        last["events"] = bip["events"]
                    last["post_bat_score"] = score[bat]
                    if ev_ in ("BB", "HBP"):
                        last["woba_value"], last["woba_denom"] = WOBA_W[ev_], 1.0
                    elif ev_ == "K":
                        last["woba_value"], last["woba_denom"] = 0.0, 1.0
                    else:
                        cls = {"single": "1B", "double": "2B", "triple": "3B", "home_run": "HR"}.get(last["events"])
                        last["woba_value"] = WOBA_W.get(cls, 0.0) if cls else 0.0
                        last["woba_denom"] = 1.0
                    if walkoff:
                        break
                # runs to end of half-inning for every PA in it
                end_score = score[bat]
                complete = not (half == 1 and inning >= 9)
                for pa in half_pas:
                    truth_pa.append({**pa, "runs_to_end": end_score - pa["bat_score"], "complete": complete})
                if walkoff:
                    final = True
                    break
            if final:
                break
            if inning >= 9 and score[home] != score[away]:
                final = True
            inning += 1
            if inning > 20:
                final = True
        tid_h, tid_a = abbr_tid[home], abbr_tid[away]
        games[str(gpk)] = {"gpk": gpk, "date": date.isoformat(), "gtype": "R", "series": None, "home": tid_h, "away": tid_a,
                           "hs": score[home], "as": score[away], "status": "final", "venue": venue,
                           "weather": {"temp": round(temp), "wind": f"{wind_mph} mph, {wind_dir}", "cond": "Clear"},
                           "umpire_hp": str(ump), "probables": {"home": str(sp_[home]), "away": str(sp_[away])},
                           "lineups": None, "innings": inning, "lines": None, "abs": None, "has_statcast": True}
    df = pd.DataFrame(rows)
    for c in ("events", "bb_type", "launch_speed", "launch_angle", "hit_distance_sc", "hc_x", "hc_y", "hit_location",
              "post_bat_score", "woba_value", "woba_denom"):
        if c not in df:
            df[c] = np.nan
    # post_bat_score on every pitch (score after the pitch): forward-fill within the PA is the PA-end value for the
    # last pitch; earlier pitches carry the score at the pitch (runs only score on the PA-ending pitch here)
    df["post_bat_score"] = df["post_bat_score"].fillna(df["bat_score"])
    df["estimated_woba_using_speedangle"] = np.nan
    df["delta_run_exp"] = np.nan
    df["zone"] = np.nan
    df = df.sort_values(_c.PITCH_ORDER, ascending=False, kind="mergesort").reset_index(drop=True)   # Savant: newest first
    store = {"level": level, "season": season, "updated_at": None, "teams": teams, "venues": venues, "players": players,
             "games": games, "meta": {"synthetic": True}}
    truth = {"catcher": {str(k): float(v) for k, v in catcher_eff.items()}, "umpire": {str(k): v for k, v in ump_eff.items()},
             "fielder": {str(k): float(v) for k, v in fld_skill.items()}, "speed": {str(k): v for k, v in speed.items()},
             "pa": pd.DataFrame(truth_pa), "bat": {str(k): v for k, v in bat_traits.items()},
             "positions": {abbr: {str(p): v for p, v in r.items()} for abbr, r in team_def.items()},
             "catchers": {a: [str(c) for c in cs] for a, cs in catchers.items()},
             "steals": sb_log}
    return df, store, truth


def _hc(dist: float, spray: float) -> tuple[float, float]:
    a = math.radians(spray)
    return _c.HC_X0 + dist / _c.HC_FT * math.sin(a), _c.HC_Y0 - dist / _c.HC_FT * math.cos(a)


def _batted_ball(R, rng, tr, spd, fielders, fld_skill, dims, walls, carry, outs, bases) -> dict:
    ev = float(np.clip(rng.normal(tr["ev"], 12.0), 35, 118))
    la = float(np.clip(rng.normal(tr["la"], 24.0), -70, 80))
    pull = float(np.clip(rng.normal(tr["pull"], 20.0), -44, 44))
    spray = -pull if tr["stand"] == "R" else pull               # field spray: RHB pulls to left field (negative)
    shade = -3.0 if tr["stand"] == "R" else 3.0
    hang, dist = _fl(ev, la)
    dist *= carry * 0.96
    bb = "ground_ball" if la < 10 else "line_drive" if la < 25 else "fly_ball" if la < 50 else "popup"
    out = {"launch_speed": ev, "launch_angle": la, "bb_type": bb}
    if bb == "ground_ball":
        gaps = {p: abs(spray - (a + shade)) for p, a in IF_ANGLES.items()}
        pos = min(gaps, key=gaps.get)
        reach = 7.0 + fld_skill[fielders[pos]] + (95 - ev) * 0.06
        p_field = 1 / (1 + math.exp(-1.2 * (reach - gaps[pos])))
        if R.random() < p_field:
            # fielded: infield hit chance from weak contact and runner speed
            p_ih = 1 / (1 + math.exp(-((spd - 27) * 0.9 - 2.2 + (75 - ev) * 0.05 + (gaps[pos] - 4) * 0.15)))
            d = IF_DEPTH[pos]
            if R.random() < p_ih:
                ev_name = "single"
            elif R.random() < 0.015:
                ev_name = "field_error"
            else:
                ev_name = "out_gb"
            hx, hy = _hc(d, spray)
            out.update(hit_location=pos, hit_distance_sc=d * 0.6)
        else:
            dd = 190.0
            ev_name = "double" if (abs(spray) > 38 and ev > 95 and R.random() < 0.5) else "single"
            hx, hy = _hc(dd, spray)
            out.update(hit_location=7 if spray < -15 else 9 if spray > 15 else 8, hit_distance_sc=dd * 0.5)
        out.update(hc_x=hx, hc_y=hy)
    else:
        wall = wall_at(dims, spray)
        side = "lf" if spray < -22.5 else "rf" if spray > 22.5 else "cf"
        wall_h = walls.get(side, 8)
        if 18 <= la <= 45 and dist > wall + (wall_h - 8) * 1.2:
            hx, hy = _hc(dist, spray)
            out.update(events="home_run", hc_x=hx, hc_y=hy, hit_distance_sc=dist, hit_location=np.nan)
            return out
        dist_land = min(dist, wall - 3)
        lx, ly = math.sin(math.radians(spray)) * dist_land, math.cos(math.radians(spray)) * dist_land
        best, req = None, 1e9
        cands = {p: (a + shade, IF_DEPTH[p]) for p, a in IF_ANGLES.items()} if dist_land < 180 else {}
        cands.update({p: (a + shade, d) for p, (a, d) in OF_POS.items()})
        for p, (a, d) in cands.items():
            sx, sy = math.sin(math.radians(a)) * d, math.cos(math.radians(a)) * d
            rd = math.hypot(lx - sx, ly - sy)
            spd_f = fld_skill[fielders[p]] if p >= 7 else 26.0 + fld_skill[fielders[p]] * 0.5
            slack = spd_f * max(hang - 0.6, 0.0) - rd
            if best is None or slack > req:
                best, req = p, slack
        p_catch = 1 / (1 + math.exp(-req / 6.0))
        if bb == "popup":
            p_catch = max(p_catch, 0.97)
        hx, hy = _hc(dist_land, spray)
        out.update(hc_x=hx, hc_y=hy, hit_distance_sc=dist_land, hit_location=best)
        if R.random() < p_catch:
            ev_name = "field_error" if R.random() < 0.01 else "out_air"
        else:
            if dist_land < 200:
                ev_name = "single"
            elif dist_land > wall - 45 and R.random() < 1 / (1 + math.exp(-((spd - 28) * 1.5 - 1.0))):
                ev_name = "triple"
            elif dist_land > 250 and abs(spray) > 8:
                ev_name = "double" if R.random() < 0.7 else "single"
            else:
                ev_name = "double" if R.random() < 0.35 else "single"
    out["events"] = ev_name
    return out


def _advance(R, ev, bip, outs, bases, batter, speed):
    """Apply a PA result to (outs, bases). Returns (outs, bases, runs). Rewrites bip['events'] for outs."""
    b = list(bases)
    runs = 0

    def spd(r):
        return speed.get(r, 27.0)

    if ev in ("BB", "HBP"):
        if b[0] is not None:
            if b[1] is not None:
                if b[2] is not None:
                    runs += 1
                b[2] = b[1]
            b[1] = b[0]
        b[0] = batter
        return outs, b, runs
    if ev == "K":
        return outs + 1, b, 0
    e = bip["events"]
    if e == "home_run":
        runs = 1 + sum(r is not None for r in b)
        return outs, [None, None, None], runs
    if e == "triple":
        runs = sum(r is not None for r in b)
        return outs, [None, None, batter], runs
    if e == "double":
        runs = (b[2] is not None) + (b[1] is not None)
        nb = [None, batter, None]
        if b[0] is not None:
            if R.random() < 0.40 + 0.08 * (spd(b[0]) - 27):
                runs += 1
            else:
                nb[2] = b[0]
        return outs, nb, runs
    if e in ("single", "field_error"):
        runs = (b[2] is not None)
        nb = [batter, None, None]
        if b[1] is not None:
            if e == "single" and R.random() < 0.60 + 0.08 * (spd(b[1]) - 27):
                runs += 1
            else:
                nb[2] = b[1]
        if b[0] is not None:
            if e == "single" and nb[2] is None and R.random() < 0.28 + 0.08 * (spd(b[0]) - 27):
                nb[2] = b[0]
            else:
                nb[1] = b[0]
        return outs, nb, runs
    if e == "out_gb":
        if b[0] is not None and outs < 2 and R.random() < 0.45:
            bip["events"] = "grounded_into_double_play"
            outs += 2
            nb = [None, None, None]
            if outs < 3:
                if b[2] is not None:
                    runs += 1
                nb[2] = b[1]
            return outs, nb, runs
        outs += 1
        if b[0] is not None:          # force at second: lead runner out, batter safe, forced runners move up
            bip["events"] = "force_out"
            if outs >= 3:
                return outs, b, 0
            nb = [batter, None, b[2]]
            if b[1] is not None:
                if b[2] is not None:
                    runs += 1
                nb[2] = b[1]
            elif b[2] is not None and R.random() < 0.3:
                runs += 1
                nb[2] = None
            return outs, nb, runs
        bip["events"] = "field_out"
        if outs >= 3:
            return outs, b, 0
        nb = list(b)
        if nb[2] is not None and R.random() < 0.3:
            runs += 1
            nb[2] = None
        if nb[1] is not None and nb[2] is None and R.random() < 0.4:
            nb[2], nb[1] = nb[1], None
        return outs, nb, runs
    # out in the air
    outs += 1
    bip["events"] = "field_out"
    if outs >= 3:
        return outs, b, 0
    nb = list(b)
    if b[2] is not None and bip.get("bb_type") == "fly_ball" and (bip.get("hit_location") or 0) >= 7 and R.random() < 0.75:
        runs += 1
        nb[2] = None
        bip["events"] = "sac_fly"
    if nb[1] is not None and nb[2] is None and bip.get("bb_type") == "fly_ball" and R.random() < 0.3:
        nb[2], nb[1] = nb[1], None
    return outs, nb, runs


RETRO_CD = {"1B": "1b", "2B": "2b", "3B": "3b", "HR": "hr", "BB": "bb", "IBB": "ibb", "HBP": "hbp", "K": "k",
            "ROE": "e", "OUT": "out", "CI": "int"}


def retro_from_pitches(df: pd.DataFrame, season: int = 2025) -> pd.DataFrame:
    """Builder A's Retrosheet event-table shape from a synthetic pitch table: one PA row per plate appearance
    (pa=True) with Retrosheet-style ids ('b' + MLBAM id), pre/post base-out states, scores and runs."""
    from oddsmarkets.baseball.models import re24
    p = _c.prepare_pitches(df.copy())
    pa = re24.prepare_pa(_c.pa_table(p))
    rid = lambda x: None if pd.isna(x) else f"b{int(x)}"
    home = pa["half"] == 1
    out = pd.DataFrame({
        "game_id": "SYN" + pa["game_pk"].astype(str), "date": pa["game_date"].astype(str), "season": season, "gtype": "R",
        "home": pa["home_team"], "away": pa["away_team"], "park": pa["home_team"] + "01",
        "inning": pa["inning"].astype(int), "half": pa["half"].astype(int), "seq": np.arange(len(pa)),
        "bat_team": np.where(home, pa["home_team"], pa["away_team"]),
        "batter": pa["batter"].map(rid), "pitcher": pa["pitcher"].map(rid), "bat_hand": pa["stand"], "pit_hand": pa["p_throws"],
        "outs_pre": pa["outs_when_up"].astype(int), "bases_pre": pa["bases"].astype(int),
        "run1_pre": pa["on_1b"].map(rid), "run2_pre": pa["on_2b"].map(rid), "run3_pre": pa["on_3b"].map(rid),
        "away_score_pre": np.where(home, pa["fld_score"], pa["bat_score"]).astype(int),
        "home_score_pre": np.where(home, pa["bat_score"], pa["fld_score"]).astype(int),
        "balls": np.nan, "strikes": np.nan, "pitches": None, "event_tx": "",
        "event_cd": pa["cls"].map(RETRO_CD).fillna("oa"), "pa": pa["cls"].ne("").to_numpy(),
        "ab": pa["cls"].isin(["1B", "2B", "3B", "HR", "K", "OUT", "ROE"]).to_numpy(),
        "hit": pa["cls"].map({"1B": 1, "2B": 2, "3B": 3, "HR": 4}).fillna(0).astype(int),
        "err": (pa["cls"] == "ROE").astype(int), "runs_on_play": pa["runs_pa"].astype(int),
        "outs_on_play": (np.minimum(pa["end_outs"], 3) - pa["outs_when_up"]).clip(lower=0).astype(int),
        "outs_post": np.minimum(pa["end_outs"], 3).astype(int), "bases_post": pa["end_bases"].astype(int),
        "fielded_by": pd.to_numeric(pa.get("hit_location"), errors="coerce"), "hit_loc": None, "bb_type": None,
        "sh": pa["events"].astype(str).eq("sac_bunt").to_numpy(), "sf": pa["events"].astype(str).eq("sac_fly").to_numpy()})
    return out.reset_index(drop=True)
