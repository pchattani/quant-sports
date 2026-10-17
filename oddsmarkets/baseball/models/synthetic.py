"""
Synthetic Statcast pitch tables (Savant column names) with planted truth, for the builder-B tests and for
developing models before real seasons land.

Games: one starter and one reliever per side (the starter is lifted after STARTER_PITCHES), nine-man
lineups, plate appearances simulated pitch by pitch from 0-0 until a walk, strikeout or ball in play, with
half-innings of three outs. Each pitch is a physically consistent 9-parameter trajectory: release point,
speed, drag, and the planted movement (against the release tangent line, Savant's definition) give vx0..az; the
Savant movement columns are derived from the same constant-acceleration flight.

Planted effects (all in `truth`):
* stuff: a family-specific latent s(pitch) from the physics (fastballs: velocity, IVB, extension; breaking:
  velocity, glove-side break, spin; offspeed: velocity gap and drop against the fastball) raises the whiff
  log-odds by s and lowers xwOBA on contact by 0.05 s.
* location: called-strike probability falls steeply outside the zone (logit -9 x signed distance);
  pitches in the heart are hit harder (+0.06 xwOBA) and edges less so; pitcher command = location noise SD.
* swing: league P(swing) rises in the zone and with two strikes; batter aggression shifts it everywhere,
  batter discipline raises zone swings and cuts chases (planted per batter: `truth["batters"]`).
* tunneling: when the previous pitch of the PA exists, whiff log-odds += TUNNEL_B * clip(plate_dist -
  2 dp_dist, -15, 15) / 10 (inches), i.e. pitches that look alike at the decision point and split late.
* bat tracking: bat speed = batter talent + 0.15 (velo - 93) - 1.5 (two strikes) - 2 |x_away - 0.1| + noise;
  launch speed on contact uses a squared-up efficiency that falls with |attack angle + VAA|.
* fatigue: velocity falls by the pitcher's planted rate (mph per 100 pitches in the game); a planted
  times-through-order penalty adds to xwOBA from the second time through.
* run values: delta_run_exp from a count-value table (CV) and PA outcomes (walk 0.32, strikeout -0.27, ball
  in play 0.8 (wOBA - 0.32)), so per-pitch values sum to the PA's run value.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io

G = _io.G_FT
CV = {(0, 0): 0.0, (1, 0): 0.032, (2, 0): 0.088, (3, 0): 0.173, (0, 1): -0.038, (1, 1): -0.011, (2, 1): 0.032,
      (3, 1): 0.113, (0, 2): -0.091, (1, 2): -0.076, (2, 2): -0.044, (3, 2): 0.042}
RV_WALK, RV_K = 0.32, -0.27
STARTER_PITCHES = 95
TUNNEL_B = 0.6
ARSENALS = {"power": ["FF", "SL", "CH"], "sinker": ["SI", "SL", "CH", "FF"], "curve": ["FF", "CU", "CH"],
            "cutter": ["FC", "ST", "FS", "SI"]}
USAGE = {"FF": 0.45, "SI": 0.40, "FC": 0.35, "SL": 0.30, "ST": 0.30, "CU": 0.22, "CH": 0.18, "FS": 0.18}
SZ_HALF = 0.83


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _t_at(y: float, vy0: float, ay: float) -> float:
    c = 50.0 - y
    return (-vy0 - math.sqrt(max(vy0 * vy0 - 2 * ay * c, 0.0))) / ay


def trajectory_one(speed_mph: float, pfx_x: float, pfx_z: float, xr: float, zr: float, ext: float,
                   px: float, pz: float) -> dict:
    """Constant-acceleration flight from the release point (xr, 60.5 - ext, zr) to the plate location
    (px, pz) at y = 17/12 whose movement against the release tangent line (Savant's definition, physics.py)
    is the planted pfx: horizontal deviation pfx_x, and vertical pfx_z = 1/2 g T^2 - total drop. The
    accelerations are found by fixed-point iteration; the returned pfx/break values are measured from
    the final flight (scalar maths, independent of physics.py)."""
    v = speed_mph / _io.FTS_TO_MPH
    ay = 0.00155 * v * v
    yr = 60.5 - ext
    vy_r = -v * 0.995
    vy0 = -math.sqrt(vy_r * vy_r - 2 * ay * (yr - 50.0))
    tp = _t_at(_io.Y_FRONT, vy0, ay)
    tr = _t_at(yr, vy0, ay)
    T = tp - tr
    ax = 2 * pfx_x / T ** 2
    az = 2 * pfx_z / T ** 2 - G
    for _ in range(30):
        vx0 = (px - xr - 0.5 * ax * (tp * tp - tr * tr)) / (tp - tr)
        vz0 = (pz - zr - 0.5 * az * (tp * tp - tr * tr)) / (tp - tr)
        vxr, vyr_, vzr = vx0 + ax * tr, vy0 + ay * tr, vz0 + az * tr
        x_line = xr + vxr / vyr_ * (_io.Y_FRONT - yr)
        z_line = zr + vzr / vyr_ * (_io.Y_FRONT - yr)
        mx = px - x_line
        mz = 0.5 * G * T * T - (z_line - pz)
        if abs(mx - pfx_x) < 1e-9 and abs(mz - pfx_z) < 1e-9:
            break
        ax += 2 * (pfx_x - mx) / T ** 2
        az += 2 * (pfx_z - mz) / T ** 2
    x0 = px - vx0 * tp - 0.5 * ax * tp * tp
    z0 = pz - vz0 * tp - 0.5 * az * tp * tp
    td = tp - _io.DECISION_S
    vzf, vyf, vxf = vz0 + az * tp, vy0 + ay * tp, vx0 + ax * tp
    return {"vx0": vx0, "vy0": vy0, "vz0": vz0, "ax": ax, "ay": ay, "az": az,
            "release_speed": math.sqrt(vxr ** 2 + vyr_ ** 2 + vzr ** 2) * _io.FTS_TO_MPH,
            "x_dp": x0 + vx0 * td + 0.5 * ax * td * td, "z_dp": z0 + vz0 * td + 0.5 * az * td * td,
            "vaa": math.degrees(math.atan2(vzf, -vyf)), "haa": math.degrees(math.atan2(vxf, -vyf)),
            "pfx_x": mx, "pfx_z": mz, "brk_z": z_line - pz, "brk_x": mx}


def _zone(px: float, pz: float, top: float, bot: float) -> int:
    if abs(px) <= SZ_HALF and bot <= pz <= top:
        col = min(int((px + SZ_HALF) / (2 * SZ_HALF / 3)), 2)
        row = min(int((top - pz) / ((top - bot) / 3)), 2)
        return 1 + row * 3 + col
    mid = (top + bot) / 2
    if pz >= mid:
        return 11 if px < 0 else 12
    return 13 if px < 0 else 14


def _signed_dist(px: float, pz: float, top: float, bot: float) -> float:
    """Signed distance (ft) to the strike-zone edge (ball radius allowed): negative inside."""
    dx = abs(px) - (SZ_HALF + 0.12)
    dz = max(bot - 0.12 - pz, pz - top - 0.12)
    if dx <= 0 and dz <= 0:
        return max(dx, dz)
    return math.hypot(max(dx, 0.0), max(dz, 0.0))


def _pitchers(rng, n: int, start_id: int = 600000) -> list[dict]:
    out = []
    styles = list(ARSENALS)
    for i in range(n):
        st = styles[i % len(styles)]
        hand = "L" if rng.random() < 0.3 else "R"
        fbv = rng.normal(94.0, 1.8)
        p = {"id": start_id + i, "hand": hand, "style": st, "fb_velo": fbv, "fb_ivb": rng.normal(15.5, 2.2),
             "rel_z": rng.normal(5.9, 0.35), "rel_x": abs(rng.normal(1.9, 0.35)), "ext": rng.normal(6.4, 0.35),
             "command": float(np.clip(rng.normal(0.75, 0.12), 0.5, 1.1)), "fatigue": max(0.0, rng.normal(1.0, 0.8)),
             "tto_pen": rng.normal(0.012, 0.012), "ssw": rng.random() < 0.35, "spin_mult": rng.normal(1.0, 0.08),
             "brk_extra": rng.normal(0, 2.0), "ch_gap": rng.normal(9.0, 1.5)}
        p["arsenal"] = ARSENALS[st]
        p["arm_angle"] = math.degrees(math.atan2(p["rel_z"] - 4.6, p["rel_x"])) + rng.normal(0, 4)
        w = np.array([USAGE.get(t, 0.15) for t in p["arsenal"]])
        p["usage"] = w / w.sum()
        out.append(p)
    return out


def _batters(rng, n: int, start_id: int = 650000) -> list[dict]:
    return [{"id": start_id + i, "stand": "L" if rng.random() < 0.4 else "R", "aggr": rng.normal(0, 0.35),
             "disc": rng.normal(0, 0.45), "contact": rng.normal(0, 0.3), "power": rng.normal(0, 0.03),
             "bat_speed": rng.normal(72.0, 2.5), "attack": rng.normal(10.0, 4.0), "icpt_y": rng.normal(30.0, 3.0)}
            for i in range(n)]


def _pitch_shape(rng, p: dict, pt: str, game_pitch: int) -> dict:
    """Velocity (mph), pfx (ft, catcher's view), spin, axis for one pitch of type pt."""
    arm = 1.0 if p["hand"] == "L" else -1.0           # arm-side sign in catcher's-view x
    fade = p["fatigue"] * game_pitch / 100.0
    if pt == "FF":
        v, ivb, hb = p["fb_velo"], p["fb_ivb"], 8.0
        spin = 2300 * p["spin_mult"]
    elif pt == "SI":
        v, ivb, hb = p["fb_velo"] - 0.7, p["fb_ivb"] - 8.0, 15.0
        spin = 2150 * p["spin_mult"]
    elif pt == "FC":
        v, ivb, hb = p["fb_velo"] - 4.0, p["fb_ivb"] - 6.0, -2.5
        spin = 2400 * p["spin_mult"]
    elif pt in ("SL", "ST"):
        v = p["fb_velo"] - (8.0 if pt == "SL" else 11.0)
        ivb, hb = 1.0, -(5.0 if pt == "SL" else 14.0) - p["brk_extra"]
        spin = 2450 * p["spin_mult"]
    elif pt == "CU":
        v, ivb, hb = p["fb_velo"] - 15.0, -13.0 - abs(p["brk_extra"]), -8.0
        spin = 2600 * p["spin_mult"]
    else:  # CH / FS
        v = p["fb_velo"] - p["ch_gap"]
        ivb, hb = p["fb_ivb"] - 9.0 - (3.0 if pt == "FS" else 0.0), 13.0
        spin = 1750 * p["spin_mult"] if pt == "CH" else 1300
    v = v - fade + rng.normal(0, 0.7)
    ivb += rng.normal(0, 1.4)
    hb += rng.normal(0, 1.4)
    pfx_x = hb * arm / 12.0
    pfx_z = ivb / 12.0
    axis = (math.degrees(math.atan2(-pfx_x, pfx_z)) + 180.0) % 360.0
    if p["ssw"] and pt in ("SI", "CH", "FS"):
        axis = (axis - arm * 25.0) % 360.0       # measured spin axis differs from the movement-implied one
    axis = (axis + rng.normal(0, 4.0)) % 360.0
    return {"v": v, "pfx_x": pfx_x, "pfx_z": pfx_z, "spin": spin + rng.normal(0, 60), "axis": axis,
            "ivb": ivb, "hb_arm": hb}


def stuff_latent(fam: str, velo: float, ivb: float, hb_arm: float, ext: float, spin: float,
                 d_velo: float, d_ivb: float) -> float:
    """The planted physical 'stuff' term (whiff log-odds)."""
    if fam == "fastball":
        return 0.12 * (velo - 93.5) + 0.07 * (ivb - 12.0) + 0.25 * (ext - 6.4)
    if fam == "breaking":
        return 0.06 * (velo - 82.0) + 0.05 * (-hb_arm - 8.0) + 0.0015 * (spin - 2500)
    return 0.10 * (-d_velo - 9.0) + 0.06 * (-d_ivb - 9.0)


def season(seed: int = 0, n_games: int = 200, n_pitchers: int = 60, n_batters: int = 120, season_year: int = 2024,
           bat_tracking: bool = True) -> tuple[pd.DataFrame, dict]:
    """A synthetic season. Returns (pitch table with Savant columns, truth dict)."""
    rng = np.random.default_rng(seed)
    P = _pitchers(rng, n_pitchers)
    B = _batters(rng, n_batters)
    rows = []
    start = date(season_year, 4, 1)
    for gi in range(n_games):
        gdate = (start + timedelta(days=gi // 8)).isoformat()
        gpk = 700000 + season_year * 1000 + gi
        idx = rng.choice(n_pitchers, 4, replace=False)
        staffs = {"Top": [P[idx[0]], P[idx[1]]], "Bot": [P[idx[2]], P[idx[3]]]}   # pitchers facing that half
        lineups = {h: list(rng.choice(n_batters, 9, replace=False)) for h in ("Top", "Bot")}
        state = {h: {"pc": [0, 0], "bf": [0, 0], "lu": 0, "cur": 0} for h in ("Top", "Bot")}
        ab = 0
        for inning in range(1, 10):
            for half in ("Top", "Bot"):
                s = state[half]
                outs = 0
                while outs < 3:
                    if s["cur"] == 0 and s["pc"][0] >= STARTER_PITCHES:
                        s["cur"] = 1
                    p = staffs[half][s["cur"]]
                    b = B[lineups[half][s["lu"] % 9]]
                    s["lu"] += 1
                    tto = s["bf"][s["cur"]] // 9 + 1
                    s["bf"][s["cur"]] += 1
                    ab += 1
                    balls = strikes = 0
                    pn = 0
                    prev = None
                    while True:
                        pn += 1
                        gp = s["pc"][s["cur"]]
                        s["pc"][s["cur"]] += 1
                        r = _one_pitch(rng, p, b, balls, strikes, gp, prev, tto, bat_tracking)
                        r.update({"game_pk": gpk, "game_date": gdate, "game_type": "R", "at_bat_number": ab,
                                  "pitch_number": pn, "pitcher": p["id"], "batter": b["id"], "inning": inning,
                                  "inning_topbot": half, "outs_when_up": outs, "balls": balls, "strikes": strikes,
                                  "n_thruorder_pitcher": tto, "home_team": "HOM", "away_team": "AWY"})
                        prev = r
                        d = r["description"]
                        end = None
                        if d in ("ball", "blocked_ball"):
                            if balls == 3:
                                end = "walk"
                            else:
                                balls += 1
                        elif d in ("called_strike", "swinging_strike", "foul_tip"):
                            if strikes == 2:
                                end = "strikeout"
                            else:
                                strikes += 1
                        elif d == "foul":
                            strikes = min(strikes + 1, 2)
                        else:
                            end = "inplay"
                        before = CV[(r["balls"], r["strikes"])]
                        if end == "walk":
                            r["events"], r["woba_value"], r["woba_denom"] = "walk", 0.69, 1
                            after = RV_WALK
                        elif end == "strikeout":
                            r["events"], r["woba_value"], r["woba_denom"] = "strikeout", 0.0, 1
                            after = RV_K
                            outs += 1
                        elif end == "inplay":
                            after = 0.8 * (r["woba_value"] - 0.32)
                            if r["woba_value"] == 0:
                                outs += 1
                        else:
                            after = CV[(balls, strikes)]
                        r["delta_run_exp"] = after - before
                        rows.append(r)
                        if end:
                            break
    df = pd.DataFrame(rows)
    df = _finish(df, season_year, bat_tracking)
    truth = {"pitchers": {p["id"]: {k: v for k, v in p.items() if k not in ("usage", "arsenal")} | {"arsenal": p["arsenal"]}
                          for p in P},
             "batters": {b["id"]: b for b in B}, "tunnel_b": TUNNEL_B}
    return df, truth


def _one_pitch(rng, p: dict, b: dict, balls: int, strikes: int, gp: int, prev: dict | None, tto: int,
               bat_tracking: bool) -> dict:
    pt = p["arsenal"][rng.choice(len(p["arsenal"]), p=p["usage"])]
    fam = _io.FAMILY[pt]
    sh = _pitch_shape(rng, p, pt, gp)
    away = 1.0 if b["stand"] == "R" else -1.0
    top, bot = rng.normal(3.4, 0.12), rng.normal(1.6, 0.08)
    # intended location (batter-relative x: + away), shaded by count
    if fam == "fastball":
        tx, tz = 0.25, 2.9
    elif fam == "breaking":
        tx, tz = 0.55, 1.7
    else:
        tx, tz = 0.35, 1.6
    if balls == 3 or balls - strikes >= 2:
        tx, tz = tx * 0.5, (tz + 2.5) / 2
    if strikes == 2 and balls < 2:
        tx, tz = tx + 0.25, tz - 0.25
    xa = tx + rng.normal(0, p["command"])
    pz = tz + rng.normal(0, p["command"])
    px = xa * away
    arm = 1.0 if p["hand"] == "L" else -1.0
    xr = arm * p["rel_x"] + rng.normal(0, 0.12)
    zr = p["rel_z"] + rng.normal(0, 0.10)
    ext = p["ext"] + rng.normal(0, 0.12)
    tr = trajectory_one(sh["v"], sh["pfx_x"], sh["pfx_z"], xr, zr, ext, px, pz)
    velo = tr["release_speed"]
    fbv = p["fb_velo"] if pt != "SI" else p["fb_velo"]
    s = stuff_latent(fam, velo, sh["ivb"], sh["hb_arm"], ext, sh["spin"], velo - fbv, sh["ivb"] - p["fb_ivb"])
    sd = _signed_dist(px, pz, top, bot)
    zone_soft = _sig(-6.0 * sd)
    # swing
    disc = b["disc"] * (1.0 if sd < 0 else -1.0)
    ls = -1.1 + 2.6 * zone_soft + (0.7 if strikes == 2 else 0.0) - (0.8 if balls == 3 and strikes < 2 else 0.0) \
        + b["aggr"] + disc
    swing = rng.random() < _sig(ls)
    tunnel = 0.0
    if prev is not None:
        dp = math.hypot(tr["x_dp"] - prev["_x_dp"], tr["z_dp"] - prev["_z_dp"]) * 12
        pl = math.hypot(px - prev["plate_x"], pz - prev["plate_z"]) * 12
        tunnel = max(-15.0, min(15.0, pl - 2 * dp)) / 10.0
    out = {"pitch_type": pt, "pitch_name": pt, "stand": b["stand"], "p_throws": p["hand"], "release_speed": velo,
           "effective_speed": velo + (ext - 6.3) * 1.5, "release_spin_rate": sh["spin"], "spin_axis": sh["axis"],
           "release_extension": ext, "release_pos_x": xr, "release_pos_y": 60.5 - ext, "release_pos_z": zr,
           "arm_angle": p["arm_angle"] + rng.normal(0, 1.5), "pfx_x": tr["pfx_x"], "pfx_z": tr["pfx_z"],
           "plate_x": px, "plate_z": pz, "sz_top": top, "sz_bot": bot, "zone": _zone(px, pz, top, bot),
           "vx0": tr["vx0"], "vy0": tr["vy0"], "vz0": tr["vz0"], "ax": tr["ax"], "ay": tr["ay"], "az": tr["az"],
           "api_break_z_with_gravity": tr["brk_z"], "api_break_x_arm": tr["brk_x"] * arm,
           "api_break_x_batter_in": -tr["brk_x"] * away, "_x_dp": tr["x_dp"], "_z_dp": tr["z_dp"],
           "_stuff": s, "_tunnel": tunnel, "events": None, "bb_type": None, "launch_speed": np.nan,
           "launch_angle": np.nan, "estimated_woba_using_speedangle": np.nan, "woba_value": np.nan,
           "woba_denom": np.nan, "bat_speed": np.nan, "swing_length": np.nan, "attack_angle": np.nan,
           "intercept_ball_minus_batter_pos_y_inches": np.nan, "_vaa": tr["vaa"]}
    if not swing:
        called = rng.random() < _sig(-9.0 * sd)
        out["description"] = "called_strike" if called else "ball"
        return out
    lw = -1.5 + s + TUNNEL_B * tunnel + 0.6 * (sd > 0) - 0.5 * b["contact"] + (0.3 if fam != "fastball" else 0.0)
    if bat_tracking:
        bs = b["bat_speed"] + 0.15 * (velo - 93.0) - (1.5 if strikes == 2 else 0.0) - 2.0 * abs(xa - 0.1) + rng.normal(0, 2.5)
        out["bat_speed"] = bs
        out["swing_length"] = 7.2 + 0.08 * (bs - 72) + rng.normal(0, 0.4)
        out["attack_angle"] = b["attack"] + 6.0 * (pz - 2.5) + rng.normal(0, 4)
        out["intercept_ball_minus_batter_pos_y_inches"] = b["icpt_y"] + (4.0 if fam != "fastball" else 0.0) + rng.normal(0, 5)
    if rng.random() < _sig(lw):
        out["description"] = "swinging_strike"
        return out
    if rng.random() < 0.48:
        out["description"] = "foul"
        return out
    out["description"] = "hit_into_play"
    heart = 1.0 if (abs(xa) < 0.45 and abs(pz - (top + bot) / 2) < 0.5) else 0.0
    xw = 0.37 - 0.05 * s + 0.06 * heart - 0.06 * (sd > 0) + b["power"] + p["tto_pen"] * (tto - 1)
    xw = float(np.clip(xw + rng.normal(0, 0.12), 0.0, 1.9))
    out["estimated_woba_using_speedangle"] = xw
    ph = min(max(xw / 1.15, 0.0), 0.95)
    if rng.random() < ph:
        out["woba_value"] = float(rng.choice([0.9, 1.25, 1.6, 2.0], p=[0.66, 0.2, 0.02, 0.12]))
        out["events"] = "single"
    else:
        out["woba_value"] = 0.0
        out["events"] = "field_out"
    out["woba_denom"] = 1
    if bat_tracking:
        plate_speed = velo * 0.92
        mism = abs(out["attack_angle"] + tr["vaa"])
        eff = float(np.clip(rng.beta(6, 2.2) - 0.012 * mism, 0.2, 1.0))
        out["launch_speed"] = eff * (1.23 * out["bat_speed"] + 0.23 * plate_speed)
    else:
        out["launch_speed"] = float(np.clip(rng.normal(88 + 40 * (xw - 0.37), 10), 40, 118))
    out["launch_angle"] = float(rng.normal(12, 22))
    return out


def _finish(df: pd.DataFrame, season_year: int, bat_tracking: bool) -> pd.DataFrame:
    df["type"] = np.where(df["description"].isin(["ball", "blocked_ball"]), "B",
                          np.where(df["description"] == "hit_into_play", "X", "S"))
    df["delta_pitcher_run_exp"] = -df["delta_run_exp"]
    if not bat_tracking:
        for c in ("bat_speed", "swing_length", "attack_angle", "intercept_ball_minus_batter_pos_y_inches"):
            df[c] = np.nan
    df["intercept_ball_minus_batter_pos_x_inches"] = np.nan
    df["attack_direction"] = np.nan
    df["swing_path_tilt"] = np.nan
    df["pitcher_days_since_prev_game"] = np.nan
    df["on_1b"] = df["on_2b"] = df["on_3b"] = np.nan
    return df


def write_season(root, level: str = "mlb", **kw) -> tuple[pd.DataFrame, dict]:
    """Write a synthetic season as <root>/statcast/<level>/<season>.parquet (drops the '_' truth columns)."""
    from pathlib import Path
    df, truth = season(**kw)
    p = Path(root) / "statcast" / level / f"{kw.get('season_year', 2024)}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df[[c for c in df.columns if not c.startswith("_")]].to_parquet(p, index=False)
    return df, truth
