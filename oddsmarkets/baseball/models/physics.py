"""
Pitch trajectory physics from Statcast's 9-parameter fit.

Coordinates (Statcast, catcher's view): x positive toward the first-base side, y from the point of home plate
toward the mound, z up; feet and seconds. The fit is constant acceleration with its origin at y0 = 50 ft:

    x(t) = x0 + vx0 t + 1/2 ax t^2,   y(t) = 50 + vy0 t + 1/2 ay t^2,   z(t) = z0 + vz0 t + 1/2 az t^2

The CSV carries vx0, vy0, vz0, ax, ay, az but not x0, z0; they are backed out from the plate location
(plate_x, plate_z at the front of the plate, y = 17/12 ft), or from the release point when the plate location
is missing. Times solve the y quadratic:  t(y) = (-vy0 - sqrt(vy0^2 - 2 ay (50 - y))) / ay.

Derived per pitch (`add_physics`):
* `t_plate`  release -> front of plate flight time (s); `t50` time from y = 50 to the plate.
* `vaa`, `haa`  vertical / horizontal approach angle at the front of the plate (deg):
  vaa = atan(vz_f / -vy_f) (negative = descending), haa = atan(vx_f / -vy_f) (positive = moving toward 1B).
* Movement against the release tangent line (the line along the release velocity, extended to the front
  of the plate; the definition that reproduces Savant's columns, checked on 2026 pitches to ~0.13 in):
  `brk_x` = plate_x - x_line, `brk_z_grav` = z_line - plate_z (total drop, gravity included),
  `pfx_x_calc` = brk_x and `pfx_z_calc` = 1/2 g T^2 - brk_z_grav (induced vertical break: gravity's drop over
  the flight time T added back). Note the 9-parameter constant-acceleration form alone (1/2 a t^2 over
  y = 40 ft -> plate, the PITCHf/x convention) misses Savant's Hawk-Eye-era pfx by ~4 in. `ivb` and `hb`
  (inches) use Savant's pfx when present and ours otherwise; `hb_arm` is positive toward the pitcher's arm
  side; `brk_x_arm` / `brk_x_in` re-sign the horizontal break toward the arm side / the batter (Savant's
  api_break_x_arm / api_break_x_batter_in are exactly that, in feet).
* `x_dp`, `y_dp`, `z_dp`  ball position at the decision point (DECISION_S before reaching the plate).
* `plate_speed` (mph) at the front of the plate.
* `axis_move`  spin axis implied by the observed movement (deg, Savant convention: 180 = pure backspin,
  measured so that a right-hander's riding fastball sits near 200-215), `axis_dev` = axis_move - spin_axis
  wrapped to (-180, 180], and `ssw` = |axis_dev| >= SSW_DEG (a seam-shifted-wake indicator: movement that
  the measured spin direction does not explain).
* `spin_eff`  spin-efficiency proxy: the Magnus acceleration (non-gravity acceleration with its component along
  the velocity, the drag, removed) gives a lift coefficient C_L = |a_M| / (K v^2); inverting the
  Sawicki-Hubbard-Stronge lift curve (C_L = 1.5 S for S < 0.1, 0.09 + 0.6 S above) gives the transverse spin
  parameter S = r w_T / v, hence the transverse spin, as a share of the measured spin rate. Air density is the sea-level standard, so Coors-like parks read low.

`release_consistency` summarises release-point, extension and arm-angle spread per pitcher (and per pitch type),
plus how far apart the pitch types' mean release points sit (a tipping indicator).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _io

MODEL_VERSION = "physics-2"

SSW_DEG = 20.0
BALL_R_FT = 1.4524 / 12.0                      # radius of a 9.125 in circumference ball
BALL_MASS_LB = 5.125 / 16.0
AIR_RHO_LB_FT3 = 0.0745                         # 70 F, sea level, 50% humidity
K_MAGNUS = AIR_RHO_LB_FT3 * math.pi * BALL_R_FT ** 2 / (2 * BALL_MASS_LB)   # a = K C_L v^2 (ft^-1)

TRAJ_COLS = ["vx0", "vy0", "vz0", "ax", "ay", "az", "plate_x", "plate_z", "release_pos_x", "release_pos_y",
             "release_pos_z", "release_extension", "release_speed", "release_spin_rate", "spin_axis", "p_throws",
             "stand", "pfx_x", "pfx_z", "api_break_z_with_gravity", "api_break_x_arm", "api_break_x_batter_in",
             "arm_angle"]


def _f(df: pd.DataFrame, c: str) -> np.ndarray:
    return pd.to_numeric(df[c], errors="coerce").to_numpy(float) if c in df else np.full(len(df), np.nan)


def time_at_y(y: np.ndarray | float, vy0: np.ndarray, ay: np.ndarray) -> np.ndarray:
    """Time (s, from the y = 50 ft origin) at which the ball reaches distance y: the root of
    50 + vy0 t + 1/2 ay t^2 = y on the ball's path (negative before y = 50)."""
    vy0 = np.asarray(vy0, float)
    ay = np.asarray(ay, float)
    c = _io.Y0 - np.asarray(y, float)
    disc = vy0 ** 2 - 2.0 * ay * c
    with np.errstate(invalid="ignore", divide="ignore"):
        quad = (-vy0 - np.sqrt(np.maximum(disc, 0.0))) / ay
        lin = -c / vy0
    return np.where(np.abs(ay) > 1e-6, quad, lin)


def trajectory(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """The 9 parameters with x0, z0 at y = 50 backed out from the plate location (or the release point)."""
    vx0, vy0, vz0 = _f(df, "vx0"), _f(df, "vy0"), _f(df, "vz0")
    ax, ay, az = _f(df, "ax"), _f(df, "ay"), _f(df, "az")
    tp = time_at_y(_io.Y_FRONT, vy0, ay)
    px, pz = _f(df, "plate_x"), _f(df, "plate_z")
    yr = _f(df, "release_pos_y")
    ext = _f(df, "release_extension")
    yr = np.where(np.isfinite(yr), yr, 60.5 - ext)
    tr = time_at_y(yr, vy0, ay)
    x0p = px - vx0 * tp - 0.5 * ax * tp ** 2
    z0p = pz - vz0 * tp - 0.5 * az * tp ** 2
    x0r = _f(df, "release_pos_x") - vx0 * tr - 0.5 * ax * tr ** 2
    z0r = _f(df, "release_pos_z") - vz0 * tr - 0.5 * az * tr ** 2
    x0 = np.where(np.isfinite(x0p), x0p, x0r)
    z0 = np.where(np.isfinite(z0p), z0p, z0r)
    return {"vx0": vx0, "vy0": vy0, "vz0": vz0, "ax": ax, "ay": ay, "az": az, "x0": x0, "z0": z0,
            "t_plate": tp, "t_rel": tr}


def position(tr: dict, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = tr["x0"] + tr["vx0"] * t + 0.5 * tr["ax"] * t ** 2
    y = _io.Y0 + tr["vy0"] * t + 0.5 * tr["ay"] * t ** 2
    z = tr["z0"] + tr["vz0"] * t + 0.5 * tr["az"] * t ** 2
    return x, y, z


def velocity(tr: dict, t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return tr["vx0"] + tr["ax"] * t, tr["vy0"] + tr["ay"] * t, tr["vz0"] + tr["az"] * t


def wrap180(a: np.ndarray) -> np.ndarray:
    return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


def movement_axis(pfx_x: np.ndarray, pfx_z: np.ndarray) -> np.ndarray:
    """Spin axis (deg, Savant convention) implied by the movement direction: the movement's clock angle seen
    from behind the pitcher (clockwise from 12, right = third-base side = -x) plus 180."""
    ang = np.degrees(np.arctan2(-np.asarray(pfx_x, float), np.asarray(pfx_z, float)))
    return (ang + 180.0) % 360.0


def add_physics(df: pd.DataFrame, decision_s: float = _io.DECISION_S) -> pd.DataFrame:
    """Add the derived physics columns (module docstring) to a pitch table; returns the same frame."""
    n = len(df)
    if n == 0:
        for c in ("t_plate", "t50", "vaa", "haa", "pfx_x_calc", "pfx_z_calc", "ivb", "hb", "hb_arm", "brk_z_grav",
                  "brk_x_arm", "brk_x_in", "x_dp", "y_dp", "z_dp", "plate_speed", "axis_move", "axis_dev", "ssw",
                  "spin_eff", "release_side_arm"):
            df[c] = pd.Series(dtype=float)
        return df
    tr = trajectory(df)
    tp, t_rel = tr["t_plate"], tr["t_rel"]
    vxf, vyf, vzf = velocity(tr, tp)
    df["t50"] = tp.astype(np.float32)
    df["t_plate"] = (tp - t_rel).astype(np.float32)
    df["vaa"] = np.degrees(np.arctan2(vzf, -vyf)).astype(np.float32)
    df["haa"] = np.degrees(np.arctan2(vxf, -vyf)).astype(np.float32)
    df["plate_speed"] = (np.sqrt(vxf ** 2 + vyf ** 2 + vzf ** 2) * _io.FTS_TO_MPH).astype(np.float32)
    T = tp - t_rel
    xr, yr, zr = position(tr, t_rel)
    vxr, vyr, vzr = velocity(tr, t_rel)
    with np.errstate(invalid="ignore", divide="ignore"):
        x_line = xr + vxr / vyr * (_io.Y_FRONT - yr)
        z_line = zr + vzr / vyr * (_io.Y_FRONT - yr)
    xp, _, zp = position(tr, tp)
    brk_x = xp - x_line
    brk_z = z_line - zp
    pfx_x = brk_x
    pfx_z = 0.5 * _io.G_FT * T ** 2 - brk_z
    df["pfx_x_calc"] = pfx_x.astype(np.float32)
    df["pfx_z_calc"] = pfx_z.astype(np.float32)
    # movement in inches from Savant's own pfx when present, else ours
    sx, sz = _f(df, "pfx_x"), _f(df, "pfx_z")
    mx = np.where(np.isfinite(sx), sx, pfx_x)
    mz = np.where(np.isfinite(sz), sz, pfx_z)
    df["ivb"] = (12.0 * mz).astype(np.float32)
    df["hb"] = (12.0 * mx).astype(np.float32)
    arm = _io.arm_sign(df["p_throws"]) if "p_throws" in df else np.full(n, -1.0)
    away = _io.away_sign(df["stand"]) if "stand" in df else np.ones(n)
    df["hb_arm"] = (12.0 * mx * arm).astype(np.float32)
    df["brk_z_grav"] = brk_z.astype(np.float32)
    df["brk_x_arm"] = (brk_x * arm).astype(np.float32)
    # toward the batter: a right-handed batter stands on the third-base (-x) side
    df["brk_x_in"] = (-brk_x * away).astype(np.float32)
    tdp = tp - decision_s
    xd, yd, zd = position(tr, tdp)
    df["x_dp"] = xd.astype(np.float32)
    df["y_dp"] = yd.astype(np.float32)
    df["z_dp"] = zd.astype(np.float32)
    df["release_side_arm"] = (_f(df, "release_pos_x") * arm).astype(np.float32)
    # spin axis implied by movement v measured
    am = movement_axis(mx, mz)
    df["axis_move"] = am.astype(np.float32)
    sa = _f(df, "spin_axis")
    dev = wrap180(am - sa)
    df["axis_dev"] = dev.astype(np.float32)
    df["ssw"] = np.where(np.isfinite(dev), (np.abs(dev) >= SSW_DEG).astype(float), np.nan).astype(np.float32)
    df["spin_eff"] = spin_efficiency(tr, _f(df, "release_spin_rate")).astype(np.float32)
    return df


def spin_efficiency(tr: dict, spin_rpm: np.ndarray) -> np.ndarray:
    """Transverse spin share from the Magnus acceleration (module docstring), clipped to [0, 1.2]."""
    tm = 0.5 * (tr["t_rel"] + tr["t_plate"])
    vx, vy, vz = velocity(tr, tm)
    v = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
    ux, uy, uz = vx / v, vy / v, vz / v
    a1, a2, a3 = tr["ax"], tr["ay"], tr["az"] + _io.G_FT
    along = a1 * ux + a2 * uy + a3 * uz
    mx, my, mz = a1 - along * ux, a2 - along * uy, a3 - along * uz
    am = np.sqrt(mx ** 2 + my ** 2 + mz ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        cl = am / (K_MAGNUS * v ** 2)
        cl = np.clip(cl, 1e-4, 0.6)
        # Sawicki-Hubbard-Stronge lift: C_L = 1.5 S (S < 0.1), 0.09 + 0.6 S above
        S = np.where(cl < 0.15, cl / 1.5, (cl - 0.09) / 0.6)
        w_t = S * v / BALL_R_FT * 60.0 / (2 * math.pi)
        eff = w_t / spin_rpm
    return np.where(np.isfinite(eff) & (spin_rpm > 0), np.clip(eff, 0.0, 1.2), np.nan)


def vaa_slope(df: pd.DataFrame) -> dict:
    """Per pitch family, the least-squares slope of VAA on plate_z (deg per ft) and the mean plate_z: the
    location adjustment used by the stuff model (vaa_adj = vaa - slope (plate_z - z_ref))."""
    out = {}
    fam = df["family"] if "family" in df else _io.family_of(df["pitch_type"])
    for f in _io.FAMILIES:
        m = (fam == f).to_numpy() & np.isfinite(_f(df, "vaa")) & np.isfinite(_f(df, "plate_z"))
        if m.sum() < 30:
            out[f] = {"slope": 0.0, "z_ref": 2.3}
            continue
        z = _f(df, "plate_z")[m]
        a = _f(df, "vaa")[m]
        zc = z - z.mean()
        slope = float((zc * (a - a.mean())).sum() / max((zc ** 2).sum(), 1e-9))
        out[f] = {"slope": round(slope, 4), "z_ref": round(float(z.mean()), 4)}
    return out


def vaa_adjusted(df: pd.DataFrame, slopes: dict) -> np.ndarray:
    fam = (df["family"] if "family" in df else _io.family_of(df["pitch_type"])).to_numpy()
    vaa, z = _f(df, "vaa"), _f(df, "plate_z")
    s = np.array([(slopes.get(f) or {}).get("slope", 0.0) for f in _io.FAMILIES] + [0.0])
    zr = np.array([(slopes.get(f) or {}).get("z_ref", 2.3) for f in _io.FAMILIES] + [2.3])
    idx = np.array([_io.FAMILY_CODE.get(f, 3) for f in fam], int) if len(fam) else np.zeros(0, int)
    return vaa - s[idx] * (np.where(np.isfinite(z), z, zr[idx]) - zr[idx])


# ----------------------------------------------------------------------------- validation and summaries

def validate(df: pd.DataFrame) -> dict:
    """Mean absolute error (inches) of our movement and breaks against Savant's columns, and of the release
    point implied by the plate-anchored trajectory against release_pos_x/z."""
    if "vaa" not in df:
        df = add_physics(df.copy())
    out: dict[str, Any] = {"n": int(len(df))}

    def mae(a, b, scale=12.0):
        a, b = np.asarray(a, float), np.asarray(b, float)
        m = np.isfinite(a) & np.isfinite(b)
        return {"mae_in": round(float(np.mean(np.abs(a[m] - b[m])) * scale), 4) if m.any() else None,
                "bias_in": round(float(np.mean(a[m] - b[m]) * scale), 4) if m.any() else None, "n": int(m.sum())}

    out["pfx_x"] = mae(df["pfx_x_calc"], _f(df, "pfx_x"))
    out["pfx_z"] = mae(df["pfx_z_calc"], _f(df, "pfx_z"))
    out["api_break_z_with_gravity"] = mae(df["brk_z_grav"], _f(df, "api_break_z_with_gravity"))
    out["api_break_x_arm"] = mae(df["brk_x_arm"], _f(df, "api_break_x_arm"))
    out["api_break_x_batter_in"] = mae(df["brk_x_in"], _f(df, "api_break_x_batter_in"))
    tr = trajectory(df)
    xr, _, zr = position(tr, tr["t_rel"])
    out["release_x"] = mae(xr, _f(df, "release_pos_x"))
    out["release_z"] = mae(zr, _f(df, "release_pos_z"))
    out["release_speed_mph"] = mae(np.sqrt(sum(v ** 2 for v in velocity(tr, tr["t_rel"]))) * _io.FTS_TO_MPH,
                                   _f(df, "release_speed"), scale=1.0)
    return out


def release_consistency(df: pd.DataFrame, by: tuple[str, ...] = ("pitcher",), min_n: int = 30) -> pd.DataFrame:
    """Per group: n, SD (inches) of release side and height, combined release spread, SD of extension (in)
    and arm angle (deg). With by=("pitcher",) also `type_spread_in`: the largest distance between two
    pitch types' mean release points (types with >= min_n pitches)."""
    d = df.copy()
    for c in ("release_pos_x", "release_pos_z", "release_extension", "arm_angle"):
        d[c] = pd.to_numeric(d[c], errors="coerce") if c in d else np.nan
    g = d.groupby(list(by), observed=True)
    out = pd.DataFrame({"n": g.size(),
                        "sd_side_in": g["release_pos_x"].std() * 12, "sd_height_in": g["release_pos_z"].std() * 12,
                        "sd_ext_in": g["release_extension"].std() * 12, "sd_arm_angle": g["arm_angle"].std(),
                        "release_height": g["release_pos_z"].mean(), "extension": g["release_extension"].mean(),
                        "arm_angle": g["arm_angle"].mean()})
    out["spread_in"] = np.sqrt(out["sd_side_in"] ** 2 + out["sd_height_in"] ** 2)
    out = out[out["n"] >= min_n]
    if tuple(by) == ("pitcher",) and "pitch_type" in d:
        m = d.groupby(["pitcher", "pitch_type"], observed=True).agg(
            n=("release_pos_x", "size"), x=("release_pos_x", "mean"), z=("release_pos_z", "mean"))
        m = m[m["n"] >= min_n].reset_index()
        spread = {}
        for pid, grp in m.groupby("pitcher"):
            if len(grp) < 2:
                continue
            xy = grp[["x", "z"]].to_numpy(float)
            dd = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
            spread[pid] = float(dd.max() * 12)
        out["type_spread_in"] = pd.Series(spread)
    return out


def arsenal(df: pd.DataFrame, min_n: int = 1) -> pd.DataFrame:
    """Per pitcher x pitch type: pitches and the mean physics (velo, spin, IVB, arm-side HB, VAA, HAA, plate
    speed, flight time, spin efficiency, axis gap, SSW share, release height / side / extension, arm angle)."""
    d = df.copy()
    agg = {"n": ("release_speed", "size"), "velo": ("release_speed", "mean"), "spin": ("release_spin_rate", "mean"),
           "ivb": ("ivb", "mean"), "hb": ("hb_arm", "mean"), "vaa": ("vaa", "mean"), "haa": ("haa", "mean"),
           "plate_speed": ("plate_speed", "mean"), "flight_s": ("t_plate", "mean"), "spin_eff": ("spin_eff", "mean"),
           "axis_meas": ("spin_axis", "mean"), "axis_move": ("axis_move", "mean"), "axis_dev": ("axis_dev", "mean"),
           "ssw": ("ssw", "mean"), "rel_z": ("release_pos_z", "mean"), "rel_side": ("release_side_arm", "mean"),
           "ext": ("release_extension", "mean"), "arm_angle": ("arm_angle", "mean")}
    for c in ("release_spin_rate", "spin_axis", "release_pos_z", "release_extension", "arm_angle", "release_speed"):
        d[c] = pd.to_numeric(d[c], errors="coerce") if c in d else np.nan
    g = d.groupby(["pitcher", "pitch_type"], observed=True).agg(**agg).reset_index()
    return g[g["n"] >= min_n]


def for_season(level: str, season: int, use_cache: bool = True, min_n: int = 10) -> dict:
    """{"ok","level","season","validation": validate() on the season, "pitchers": {pid: {"release": {...},
    "types": {pt: {...physics, release consistency}}}}, "league": {pt: {...}}}."""
    try:
        from oddsmarkets.baseball.models import prep
        src = _io.pitch_path(level, season)
        if not src.exists():
            return {"ok": False, "reason": "no pitch table"}
        key = _io.file_key(MODEL_VERSION, src, min_n)

        def build():
            raw = _io.load_pitches(level, season, TRAJ_COLS + ["pitch_type"])
            val = validate(raw)
            del raw
            df = prep.prepared(level, season)
            df = df[df["pitch_type"].notna()]
            ars = arsenal(df, min_n)
            rc = release_consistency(df, ("pitcher",), min_n)
            rct = release_consistency(df, ("pitcher", "pitch_type"), min_n).reset_index()
            rct = rct.set_index(["pitcher", "pitch_type"])[["sd_side_in", "sd_height_in", "sd_ext_in", "spread_in"]]
            ars = ars.join(rct, on=["pitcher", "pitch_type"])
            pitchers: dict[str, Any] = {}
            for r in ars.to_dict("records"):
                pid = str(r.pop("pitcher"))
                pt = r.pop("pitch_type")
                pitchers.setdefault(pid, {"types": {}})["types"][pt] = r
            for pid, r in rc.to_dict("index").items():
                pitchers.setdefault(str(pid), {"types": {}})["release"] = r
            lg = arsenal(df.assign(pitcher=0), 1).drop(columns=["pitcher"]).set_index("pitch_type").to_dict("index")
            return _io.clean({"ok": True, "level": level, "season": season, "version": MODEL_VERSION, "validation": val,
                              "pitchers": pitchers, "league": lg}, 4)

        return _io.cached("physics", f"season_{level}_{season}", key, build, use_cache)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"{type(e).__name__}: {e}"}
