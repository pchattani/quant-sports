"""
Catch probability and fielding runs (an OAA-style measure built from the pitch table).

For every ball in play that stays in the park we estimate P(out) from where it went and how long it
was in the air, given where the fielders were standing, and credit the fielder responsible with
(out - P(out)) outs and (out - P(out)) x the run value of the play.

Geometry
--------
* Landing point: distance = hit_distance_sc (else 2.495 ft per hit-coordinate unit), direction = spray
  angle; field coordinates x (toward right field) and y (toward centre).
* Hang time from launch physics (`_c.flight`); grounders use the time the ball takes to reach the
  infielder's depth at 0.75 x exit velocity.
* Start positions: the CSV has the alignment (if_fielding_alignment: Standard / Strategic /
  Infield shift; of_fielding_alignment: Standard / Strategic / 4th outfielder) but no coordinates,
  so each position starts at a typical (angle, depth) for the alignment, shaded toward the batter's
  pull side (START table; documented constants). Fielder identity comes from fielder_2..fielder_9
  (pitcher = the pitcher column).
* Geometry features come from the *outcome-independent* nearest fielder: for air balls the one needing the
  lowest speed to reach the landing point, for grounders the infielder with the least lateral distance to
  the ball's path. The model therefore cannot learn "the credited fielder made the play" (crediting outs by
  hit_location while charging hits geometrically made every shortstop hole ball an out in the training data).

Model: LightGBM binary on hang time, landing distance (air balls only: where a grounder stopped depends
on whether it was fielded), required distance and speed from the nearest fielder's start, the radial
(back/in) and lateral components of that run, distance to the wall, exit velocity, launch angle, the angle
gap to the nearest and second-nearest infielder, the signed gap, fielder depth, the throw to first, the
nearest position, batter sprint speed, outs and a force-play flag; cross-fitted by game; calibrated to the
season's out rate for air balls and grounders. Fielder identity is never a feature.

Credit (as Savant's OAA scope: infielders on grounders, outfielders on air balls in outfield territory):
an out goes to the fielder who made it (hit_location) as 1 - p; a ball that was not turned into an out is
charged to every fielder in scope by his share, -p x P(k fields it | direction, launch, alignment, batter
side), the share model a multinomial LightGBM fitted on the season's outs. Per play the credits sum to
out - p, so team totals do not depend on the split.

Fielding runs: rv_play = E[linear weight | not an out] - lw_out, where E[lw | not an out] is the
season's mean linear weight of non-outs in the same (air/ground, 40-ft landing band, spray band)
cell. OAA = sum of credits; runs = sum(credit * rv_play). Reported by fielder, primary position and
direction of the required run (back, in, toward 3B line, toward 1B line). 2025 validation against Savant's
OAA leaderboard (256 fielders): r = 0.61 (outfield 0.65-0.81, 1B/2B/3B 0.65-0.68, SS 0.44).
"""
from __future__ import annotations


import numpy as np
import pandas as pd

from oddsmarkets.baseball.models import _c

MODEL_VERSION = "catch-2"
OUTS = {"field_out", "force_out", "grounded_into_double_play", "double_play", "triple_play", "fielders_choice_out",
        "fielders_choice", "sac_fly", "sac_fly_double_play", "sac_bunt", "sac_bunt_double_play"}
# infield (angle deg, depth ft) per alignment and batter hand; angles: 0 = up the middle, - = 3B side
START = {
    "Standard": {"R": {3: (30.0, 110.0), 4: (11.0, 150.0), 6: (-15.0, 150.0), 5: (-34.0, 115.0)},
                 "L": {3: (34.0, 110.0), 4: (15.0, 150.0), 6: (-9.0, 150.0), 5: (-28.0, 115.0)}},
    "Strategic": {"R": {3: (29.0, 110.0), 4: (6.0, 155.0), 6: (-18.0, 152.0), 5: (-35.0, 118.0)},
                  "L": {3: (35.0, 110.0), 4: (19.0, 160.0), 6: (-4.0, 152.0), 5: (-27.0, 120.0)}},
    "Infield shade": {"R": {3: (28.0, 110.0), 4: (8.0, 152.0), 6: (-17.0, 151.0), 5: (-35.0, 116.0)},
                      "L": {3: (36.0, 110.0), 4: (17.0, 155.0), 6: (-6.0, 151.0), 5: (-26.0, 117.0)}},
    "Infield shift": {"R": {3: (28.0, 108.0), 4: (-4.0, 155.0), 6: (-20.0, 158.0), 5: (-35.0, 120.0)},
                      "L": {3: (37.0, 112.0), 4: (22.0, 175.0), 6: (6.0, 155.0), 5: (-12.0, 150.0)}},
}
# outfield for a straight-up alignment, then shaded toward the pull side by OF_SHADE degrees
OF_BASE = {7: (-28.0, 295.0), 8: (0.0, 320.0), 9: (28.0, 295.0)}
OF_SHADE = {"Standard": 3.0, "Strategic": 7.0, "4th outfielder": 9.0, "Extreme outfield shift": 12.0}
SHADE_DEG = 3.0                         # standard shade toward the pull side
DEFAULT_LW = {"1B": 0.47, "2B": 0.77, "3B": 1.04, "HR": 1.40, "ROE": 0.50, "out": -0.27}
LGB = {"objective": "binary", "learning_rate": 0.06, "num_leaves": 31, "min_data_in_leaf": 60, "feature_fraction": 0.9,
       "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1, "num_threads": 8, "seed": 11}
N_ROUNDS = 250
N_FOLDS = 3
FEATS = ["is_air", "hang", "land_air", "req_dist", "req_speed", "radial", "lateral", "wall_gap", "launch_speed",
         "launch_angle", "gap1", "gap2", "depth", "speed", "outs", "force", "is_of", "resp_pos", "signed_gap",
         "throw_dist"]
FIRST_BASE = (63.64, 63.64)       # field coordinates of first base (ft)
SHARE_FEATS = {"ground": ["spray", "stand_l", "if_al", "launch_speed", "launch_angle"],
               "air": ["spray", "land_air", "hang", "stand_l", "of_al"]}
SCOPE = {"ground": [3, 4, 5, 6], "air": [7, 8, 9]}
COLUMNS = ["game_pk", "game_date", "at_bat_number", "pitch_number", "batter", "pitcher", "stand", "home_team", "away_team",
           "inning_topbot", "events", "description", "bb_type", "launch_speed", "launch_angle", "hc_x", "hc_y",
           "hit_distance_sc", "hit_location", "outs_when_up", "on_1b", "on_2b", "on_3b", "if_fielding_alignment",
           "of_fielding_alignment", "woba_value", "woba_denom"] + [f"fielder_{i}" for i in range(2, 10)]


def _starts(stand: np.ndarray, if_al: np.ndarray, of_al: np.ndarray) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Per position (3..9) arrays of start angle and depth for every ball (alignment and batter hand)."""
    lefty = np.asarray(pd.Series(stand).astype(str).str.upper().str.startswith("L"))
    n = len(lefty)
    ifk = np.array([a if a in START else "Standard" for a in pd.Series(if_al).astype(str)])
    ofk = pd.Series(of_al).astype(str).to_numpy()
    out = {}
    for pos in range(3, 7):
        ang = np.zeros(n); dep = np.zeros(n)
        for al, hands in START.items():
            for hand, lm in (("R", ~lefty), ("L", lefty)):
                m = (ifk == al) & lm
                if m.any():
                    ang[m], dep[m] = hands[hand][pos]
        out[pos] = (ang, dep)
    shade = np.array([OF_SHADE.get(a, OF_SHADE["Standard"]) for a in ofk])
    sign = np.where(lefty, 1.0, -1.0)            # pull side: left field (-) for right-handed batters
    for pos, (a, d) in OF_BASE.items():
        out[pos] = (a + sign * shade, np.full(n, d))
    return out


def prepare(pitches: pd.DataFrame, speed_map: dict | None = None) -> pd.DataFrame:
    """Batted balls in the park with geometry, responsible fielder and features."""
    ev = pitches["events"].astype(object).fillna("").astype(str)
    m = ev.isin(_c.BIP_EVENTS - {"home_run"}) & pitches["hc_x"].notna() & pitches["hc_y"].notna()
    b = pitches[m].copy().reset_index(drop=True)
    n = len(b)
    if not n:
        return b
    b["out"] = b["events"].astype(str).isin(OUTS).astype(int)
    b["spray"] = _c.spray_angle(b["hc_x"], b["hc_y"])
    la = b["launch_angle"].astype(float)
    bbt = b["bb_type"].astype(str)
    b["is_air"] = ((bbt.isin(["line_drive", "fly_ball", "popup"])) | ((bbt.isin(["nan", "None", ""])) & (la >= 10))).astype(int)
    hcd = _c.hc_distance(b["hc_x"], b["hc_y"])
    b["land_dist"] = b["hit_distance_sc"].astype(float).fillna(pd.Series(hcd)).to_numpy()
    fl = _c.flight(b["launch_speed"].to_numpy(float), la.to_numpy(float))
    starts = _starts(b["stand"].to_numpy(), b.get("if_fielding_alignment", pd.Series("Standard", index=b.index)).to_numpy(),
                     b.get("of_fielding_alignment", pd.Series("Standard", index=b.index)).to_numpy())
    lx, ly = _c.landing_xy(b["land_dist"].to_numpy(float), b["spray"].to_numpy(float))
    ev_fps = np.nan_to_num(b["launch_speed"].to_numpy(float), nan=85.0) * 1.467
    spray = b["spray"].to_numpy(float)
    air = b["is_air"].to_numpy(bool)
    hang_air = np.where(np.isfinite(fl["hang"]), fl["hang"], 3.0)
    # required distance / speed for each position
    req = {}
    for pos, (ang, dep) in starts.items():
        sx, sy = _c.landing_xy(dep, ang)
        if pos <= 6:
            # grounders: intercept on the ball's line at the fielder's depth
            gx, gy = _c.landing_xy(dep, spray)
        else:
            gx, gy = _c.landing_xy(np.maximum(dep, 0), spray)
        tx = np.where(air, lx, gx); ty = np.where(air, ly, gy)
        d = np.hypot(tx - sx, ty - sy)
        t_ball = np.where(air, hang_air, dep / np.maximum(ev_fps * 0.75, 30.0))
        req[pos] = (d, t_ball, tx - sx, ty - sy, sx, sy, dep, ang)
    # responsible fielder
    hl = pd.to_numeric(b.get("hit_location", pd.Series(np.nan, index=b.index)), errors="coerce").to_numpy()
    cand_air = np.array([req[p][0] / np.maximum(req[p][1] - 0.5, 0.3) for p in range(3, 10)])     # (7, n)
    land = b["land_dist"].to_numpy(float)
    cand_air[:4] = np.where(land[None, :] > 220, np.inf, cand_air[:4])
    gaps = np.array([np.abs(spray - req[p][7]) for p in range(3, 7)])                                 # (4, n)
    # grounders: the infielder with the least lateral distance to the ball's path (depth x sin(angle gap)); this
    # never looks at the outcome, so the catch model cannot learn "whoever is credited made the play"
    lat = np.array([req[p][6] * np.sin(np.radians(np.minimum(np.abs(spray - req[p][7]), 89.0))) for p in range(3, 7)])
    geo = np.where(air, np.argmin(cand_air, axis=0) + 3, np.argmin(lat, axis=0) + 3)
    # every feature is computed from the outcome-independent nearest fielder (`geo`): the catch model never sees
    # who was credited, so it cannot learn "the credited fielder made the play"
    resp = geo.astype(int)
    b["pos"] = resp
    b["hl"] = np.where(np.isfinite(hl), hl, np.nan)
    for p_ in range(3, 10):
        d_, tb_, dx_, dy_, sx_, sy_, dep_, ang_ = req[p_]
        nrm = np.maximum(np.hypot(sx_, sy_), 1e-6)
        b[f"rad_{p_}"] = (dx_ * sx_ + dy_ * sy_) / nrm
        b[f"lat_{p_}"] = (dx_ * sy_ - dy_ * sx_) / nrm
    def pick(k):
        arr = np.array([req[p][k] for p in range(3, 10)])
        idx = np.clip(resp - 3, 0, 6)
        v = arr[idx, np.arange(n)]
        return np.where(resp >= 3, v, np.nan)
    d, tb, dx, dy, sx, sy, dep, ang = (pick(k) for k in range(8))
    b["req_dist"] = d
    b["hang"] = np.where(air, hang_air, tb)
    b["req_speed"] = d / np.maximum(b["hang"].to_numpy() - 0.5, 0.3)
    # radial: + = back (away from home), lateral: + = toward the 1B line
    r_hat_x, r_hat_y = np.where(np.isfinite(sx), sx, 0), np.where(np.isfinite(sy), sy, 1)
    norm = np.maximum(np.hypot(r_hat_x, r_hat_y), 1e-6)
    b["radial"] = (dx * r_hat_x + dy * r_hat_y) / norm
    b["lateral"] = (dx * r_hat_y - dy * r_hat_x) / norm
    gs = np.sort(gaps, axis=0)
    b["gap1"], b["gap2"] = gs[0], gs[1]
    b["depth"] = dep
    b["is_of"] = (resp >= 7).astype(int)
    b["resp_pos"] = resp.astype(float)
    b["signed_gap"] = spray - ang
    tx = np.where(air, lx, _c.landing_xy(dep, spray)[0]); ty = np.where(air, ly, _c.landing_xy(dep, spray)[1])
    b["throw_dist"] = np.hypot(tx - FIRST_BASE[0], ty - FIRST_BASE[1])
    # grounders: where a ground ball was stopped depends on whether it was fielded, so only its direction and
    # launch enter (land_air and wall_gap are air-ball features)
    b["land_air"] = np.where(air, b["land_dist"].to_numpy(float), np.nan)
    b["wall_gap"] = np.where(air, _wall_gap(b), np.nan)
    b["outs"] = b["outs_when_up"].astype(float)
    b["force"] = (b["on_1b"].notna() & (b["outs_when_up"].astype(float) < 2)).astype(int)
    if speed_map:
        b["speed"] = b["batter"].astype(str).map(speed_map).astype(float)
    else:
        b["speed"] = np.nan
    b["stand_l"] = b["stand"].astype(str).str.upper().str.startswith("L").astype(float)
    b["if_al"] = pd.Series(b.get("if_fielding_alignment", "Standard")).astype(str).map(
        {k: i for i, k in enumerate(START)}).fillna(0).to_numpy(float)
    b["of_al"] = pd.Series(b.get("of_fielding_alignment", "Standard")).astype(str).map(
        {k: i for i, k in enumerate(OF_SHADE)}).fillna(0).to_numpy(float)
    fcol = b.apply(lambda r: r.get(f"fielder_{int(r['pos'])}") if 2 <= int(r["pos"]) <= 9 else r.get("pitcher"), axis=1) \
        if n < 2000 else _fielder_ids(b, resp)
    b["fielder"] = pd.Series(fcol).astype(object).map(lambda x: str(int(x)) if pd.notna(x) else None).to_numpy()
    b["direction"] = _direction(b["radial"].to_numpy(float), b["lateral"].to_numpy(float), air)
    return b


def _fielder_ids(b: pd.DataFrame, resp: np.ndarray) -> np.ndarray:
    out = np.full(len(b), np.nan)
    for pos in range(2, 10):
        m = resp == pos
        c = f"fielder_{pos}"
        if m.any() and c in b:
            out[m] = pd.to_numeric(b.loc[m, c], errors="coerce").to_numpy()
    m = resp == 1
    if m.any():
        out[m] = pd.to_numeric(b.loc[m, "pitcher"], errors="coerce").to_numpy()
    return out


def _wall_gap(b: pd.DataFrame) -> np.ndarray:
    from oddsmarkets.baseball.models import xwoba
    std = np.tile([xwoba.STD_DIMS[k] for k in xwoba.DIM_KEYS], (len(b), 1))
    wall = xwoba._interp_rows(b["spray"].to_numpy(float), std)
    return wall - b["land_dist"].to_numpy(float)


def _direction(radial, lateral, air) -> np.ndarray:
    out = np.where(np.abs(radial) >= np.abs(lateral), np.where(radial >= 0, "back", "in"),
                   np.where(lateral >= 0, "toward_1b", "toward_3b"))
    return np.where(~air & (out == "back"), "in", out)


def play_values(b: pd.DataFrame, lw: dict | None = None) -> np.ndarray:
    """rv_play per ball: E[linear weight | not an out] in its cell minus lw_out."""
    lw = dict(DEFAULT_LW, **(lw or {}))
    ev = b["events"].astype(str)
    val = ev.map({"single": lw["1B"], "double": lw["2B"], "triple": lw["3B"], "field_error": lw["ROE"]}).astype(float)
    band = (np.clip(b["land_dist"].to_numpy(float), 0, 440) // 40).astype(int)
    sb = np.digitize(np.abs(b["spray"].to_numpy(float)), [15, 30])
    cell = b["is_air"].to_numpy(int) * 100 + band * 3 + sb
    df = pd.DataFrame({"cell": cell, "v": val})
    m = df[df["v"].notna()].groupby("cell")["v"].agg(["sum", "count"])
    prior = float(np.nanmean(val)) if np.isfinite(np.nanmean(val)) else lw["1B"]
    mean = ((m["sum"] + 20 * prior) / (m["count"] + 20)).to_dict()
    e_hit = np.array([mean.get(c, prior) for c in cell])
    return e_hit - lw["out"]


def fit_predict(b: pd.DataFrame, folds: int = N_FOLDS, rounds: int = N_ROUNDS) -> np.ndarray:
    import lightgbm as lgb
    from oddsmarkets.baseball.models import xwoba
    fid = xwoba.fold_ids(b["game_pk"], folds)
    y = b["out"].to_numpy(int)
    p = np.zeros(len(b))
    for k in np.unique(fid):
        tr, te = fid != k, fid == k
        m = lgb.train(LGB, lgb.Dataset(b.loc[tr, FEATS].astype(float), label=y[tr]), num_boost_round=rounds)
        p[te] = m.predict(b.loc[te, FEATS].astype(float))
    # calibrate the cross-fitted probabilities to the season's out rate per air/ground
    for a in (0, 1):
        mm = b["is_air"].to_numpy() == a
        if mm.any():
            target = y[mm].mean()
            lo, hi = -3.0, 3.0
            lg = np.log(np.clip(p[mm], 1e-6, 1 - 1e-6) / np.clip(1 - p[mm], 1e-6, 1))
            for _ in range(40):
                mid = (lo + hi) / 2
                if _c.sigmoid(lg + mid).mean() > target:
                    hi = mid
                else:
                    lo = mid
            p[mm] = _c.sigmoid(lg + (lo + hi) / 2)
    return p


def score(pitches: pd.DataFrame, lw: dict | None = None, speed_map: dict | None = None) -> pd.DataFrame:
    """Prepared balls in play with p_out, oae (out - p) and runs."""
    b = prepare(pitches, speed_map)
    if not len(b):
        return b
    b["p_out"] = fit_predict(b)
    b["oae"] = b["out"] - b["p_out"]
    b["rv_play"] = play_values(b, lw)
    b["runs"] = b["oae"] * b["rv_play"]
    return b


def _scope(b: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Balls in OAA scope (as Savant): grounders for infielders; air balls in outfield territory for outfielders."""
    gr = (b["is_air"].to_numpy() == 0)
    ai = (b["is_air"].to_numpy() == 1) & (b["pos"].to_numpy() >= 7)
    return gr, ai


def share_models(b: pd.DataFrame) -> dict:
    """P(position k fields the ball | ball, alignment, batter side): multinomial LightGBM fitted on the outs in
    scope whose hit_location is a scope position (infield on grounders, outfield on air balls)."""
    import lightgbm as lgb
    gr, ai = _scope(b)
    out = {}
    for kind, m in (("ground", gr), ("air", ai)):
        ks = SCOPE[kind]
        tr = m & (b["out"].to_numpy() == 1) & b["hl"].isin(ks).to_numpy()
        if tr.sum() < 200:
            continue
        y = b.loc[tr, "hl"].map({k: i for i, k in enumerate(ks)}).to_numpy(int)
        params = {"objective": "multiclass", "num_class": len(ks), "learning_rate": 0.08, "num_leaves": 31,
                  "min_data_in_leaf": 50, "verbose": -1, "num_threads": 8, "seed": 5}
        out[kind] = lgb.train(params, lgb.Dataset(b.loc[tr, SHARE_FEATS[kind]].astype(float), label=y), num_boost_round=120)
    return out


def credits(b: pd.DataFrame, models: dict | None = None) -> pd.DataFrame:
    """Long table of fielding credit: an out goes to the fielder who made it (1 - p); a ball that was not
    turned into an out is charged to every fielder in scope by his share (-p x share). Sums of `oae` over a
    play equal (out - p), so team totals are unchanged by the split."""
    models = share_models(b) if models is None else models
    gr, ai = _scope(b)
    rows = []
    for kind, m in (("ground", gr), ("air", ai)):
        ks = SCOPE[kind]
        sub = b[m]
        if not len(sub):
            continue
        out = sub["out"].to_numpy() == 1
        hl = sub["hl"].to_numpy()
        made = out & np.isin(hl, ks)
        if made.any():
            s_ = sub[made]
            k_ = s_["hl"].astype(int).to_numpy()
            rows.append(pd.DataFrame({"row": s_.index.to_numpy(), "pos": k_, "share": 1.0,
                                      "oae": 1.0 - s_["p_out"].to_numpy(), "air": kind == "air"}))
        miss = ~out
        if miss.any() and kind in models:
            s_ = sub[miss]
            sh = models[kind].predict(s_[SHARE_FEATS[kind]].astype(float))
            for j, k in enumerate(ks):
                rows.append(pd.DataFrame({"row": s_.index.to_numpy(), "pos": k, "share": sh[:, j],
                                          "oae": -s_["p_out"].to_numpy() * sh[:, j], "air": kind == "air"}))
    if not rows:
        return pd.DataFrame(columns=["row", "pos", "share", "oae", "fielder", "runs", "direction"])
    c = pd.concat(rows, ignore_index=True)
    src = b.loc[c["row"].to_numpy()]
    fid = np.full(len(c), np.nan)
    for k in range(3, 10):
        mk = c["pos"].to_numpy() == k
        col = f"fielder_{k}"
        if mk.any() and col in src:
            fid[mk] = pd.to_numeric(src[col], errors="coerce").to_numpy()[mk]
    c["fielder"] = [str(int(x)) if np.isfinite(x) else None for x in fid]
    c["runs"] = c["oae"].to_numpy() * src["rv_play"].to_numpy()
    rad = np.choose(c["pos"].to_numpy() - 3, [src[f"rad_{k}"].to_numpy() for k in range(3, 10)])
    lat = np.choose(c["pos"].to_numpy() - 3, [src[f"lat_{k}"].to_numpy() for k in range(3, 10)])
    c["direction"] = _direction(rad, lat, c["air"].to_numpy())
    c["game_pk"] = src["game_pk"].to_numpy()
    top = src["inning_topbot"].astype(str).str.lower().str.startswith("t").to_numpy()
    c["team"] = np.where(top, src["home_team"].to_numpy(), src["away_team"].to_numpy())
    return c


def fielder_table(b: pd.DataFrame, min_chances: float = 0.0, cr: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per fielder: chances (outs made + shares of balls not turned into outs), outs, OAA, fielding runs,
    primary position, success rate added and OAA by direction (back, in, toward 3B, toward 1B)."""
    d = credits(b) if cr is None else cr
    d = d[d["fielder"].notna()]
    if not len(d):
        return pd.DataFrame(columns=["pid", "chances", "outs", "oaa", "runs", "pos"])
    g = d.groupby("fielder")
    t = pd.DataFrame({"chances": g["share"].sum(), "outs": g.apply(lambda x: float((x["share"] == 1.0).sum()), include_groups=False),
                      "oaa": g["oae"].sum(), "runs": g["runs"].sum(),
                      "pos": g.apply(lambda x: int(x.groupby("pos")["share"].sum().idxmax()), include_groups=False)})
    t["sra"] = t["oaa"] / t["chances"].replace(0, np.nan)
    piv = d.pivot_table(index="fielder", columns="direction", values="oae", aggfunc="sum", fill_value=0.0)
    for c in ("back", "in", "toward_1b", "toward_3b"):
        t[f"oaa_{c}"] = piv[c] if c in piv else 0.0
    t = t[t["chances"] >= min_chances].fillna(0.0)
    return t.reset_index().rename(columns={"fielder": "pid"})


def team_table(b: pd.DataFrame, cr: pd.DataFrame | None = None) -> pd.DataFrame:
    d = credits(b) if cr is None else cr
    g = d.groupby("team")
    return pd.DataFrame({"chances": g["share"].sum(), "oaa": g["oae"].sum(), "runs": g["runs"].sum()}).reset_index()


def validate_oaa(table: pd.DataFrame, season: int, min_chances: int = 50) -> dict:
    """Correlation of our OAA (and runs) with Savant's OAA leaderboard when cached."""
    lb = _c.leaderboard("oaa", season)
    if lb is None or not len(lb):
        return {"ok": False, "reason": "no Savant OAA leaderboard cached"}
    idc = next((c for c in ("player_id", "fielder_id", "entity_id", "id") if c in lb), None)
    vc = next((c for c in ("outs_above_average", "oaa", "OAA") if c in lb), None)
    rc = next((c for c in ("fielding_runs_prevented", "runs_prevented") if c in lb), None)
    if not idc or not vc:
        return {"ok": False, "reason": f"unrecognised columns {list(lb.columns)[:12]}"}
    s = lb.groupby(lb[idc].astype(str))[[vc] + ([rc] if rc else [])].sum()
    m = table.set_index("pid").join(s, how="inner")
    m = m[m["chances"] >= min_chances]
    out = {"ok": True, "n": int(len(m)), "r_oaa": _c.pearson(m["oaa"], m[vc])}
    if rc:
        out["r_runs"] = _c.pearson(m["runs"], m[rc])
    return out


def for_season(level: str, season: int, use_cache: bool = True) -> dict:
    path = _c.pitch_path(level, season)
    if not path.exists():
        return {"ok": False, "reason": f"no pitch table for {level} {season}"}

    def build():
        from oddsmarkets.baseball.models import re24, xwoba
        p = _c.load_pitches(level, season, COLUMNS)
        if p is None or not len(p):
            return {"ok": False, "reason": "empty"}
        w = re24.weights(level, season) or {}
        lw = _lw_from(w)
        b = score(p, lw, xwoba.sprint_map(season))
        try:
            cp = _c.cache_root() / "catchprob" / f"{level}_{season}_bip.parquet"
            cp.parent.mkdir(parents=True, exist_ok=True)
            b[["game_pk", "at_bat_number", "fielder", "pos", "direction", "is_air", "land_dist", "spray", "hang",
               "req_speed", "p_out", "out", "oae", "runs"]].to_parquet(cp, index=False)
        except Exception:
            pass
        cr = credits(b)
        ft = fielder_table(b, cr=cr)
        return {"ok": True, "version": MODEL_VERSION, "n": int(len(b)), "out_rate": float(b["out"].mean()),
                "fielders": _c.frame_rows(ft), "teams": _c.frame_rows(team_table(b, cr)),
                "validation": validate_oaa(ft, season)}
    return _c.cached("catchprob", f"{level}_{season}", _c.file_key(path, MODEL_VERSION), build, use_cache)


def _lw_from(w: dict) -> dict:
    lw = (w or {}).get("lw") or {}
    out = dict(DEFAULT_LW)
    for k in ("1B", "2B", "3B", "HR", "ROE"):
        if lw.get(k) is not None:
            out[k] = float(lw[k])
    if (w or {}).get("lw", {}).get("OUT") is not None:
        out["out"] = float(w["lw"]["OUT"])
    return out


def export_fits(level: str = "mlb", season: int | None = None) -> dict:
    """Train on the latest season and write models/fitted/catchprob_<level>.txt.gz + .json (start table, features)."""
    import gzip
    import lightgbm as lgb
    seasons = _c.pitch_seasons(level)
    season = season or (seasons[-1] if seasons else None)
    if season is None:
        return {"ok": False, "reason": "no seasons"}
    p = _c.load_pitches(level, season, COLUMNS)
    b = prepare(p)
    m = lgb.train(LGB, lgb.Dataset(b[FEATS].astype(float), label=b["out"].to_numpy(int)), num_boost_round=N_ROUNDS)
    _c.FITTED.mkdir(parents=True, exist_ok=True)
    with gzip.open(_c.FITTED / f"catchprob_{level}.txt.gz", "wt", encoding="utf-8") as fh:
        fh.write(m.model_to_string())
    meta = {"version": MODEL_VERSION, "season": season, "feats": FEATS, "start_if": START, "of_base": OF_BASE, "of_shade": OF_SHADE}
    _c.write_fit(f"catchprob_{level}", meta)
    return {"ok": True, **meta}
