"""
Shot-quality model (xPTS): the probability a field-goal attempt goes in, from where and how
it was taken, and the expected points that implies.

Model
-----
For shot i (one row of the contract's SHOT table) a penalised logistic regression

    logit P(make_i) = a
                    + f_dist(dist_ft_i)                 smooth: piecewise-linear B-spline on DIST_KNOTS
                    + f_angle(|angle_deg_i|)            smooth: piecewise-linear B-spline on ANGLE_KNOTS
                    + zone + shot_type                  one-hot (rim, paint, mid, corner3, ab3, heave; dunk ... other)
                    + three * 1(value = 3)
                    + assisted + putback + transition   indicators
                    + period bucket (1, 2, 3, 4, OT) + clock bucket (<= 4 s left in the period: "end",
                      <= 24 s: "late", else "normal")
                    + margin bucket (shooting team's margin before the shot: <= -10, -9..-4, -3..3, 4..9, >= 10)
                    + league (only when the table mixes leagues)

The smooth terms carry a second-difference (P-spline) penalty LAMBDA_SMOOTH * sum (Δ² b_k)²
plus a tiny ridge, the one-hot and indicator terms a ridge LAMBDA_CAT * b² (a N(0, 1/LAMBDA_CAT)
prior on the log-odds), and the intercept is free. Fitted by Newton/IRLS on a sparse design
(`_io.logistic_fit`), which makes 220k shots a sub-second fit. Blocked is *not* a feature: it is
an outcome (a blocked shot is always a miss).

Expected points: xPTS_i = P(make_i) * value_i (2 or 3; free throws are outside the shot table, so
and-ones are not counted). Because the zone and intercept terms are (nearly) unpenalised score
equations, the fit is calibrated in-sample by zone; `calibration_table` reports it.

Derived tables
--------------
* `shot_making(shots, model, by)`: per shooter / team, shots, points, xPTS, points and xPTS per
  shot and points over expected per 100 shots (pox100, with a binomial se and a version shrunk
  by SHRINK_SHOTS pseudo-shots of zero).
* `defense_xpts(shots, model)`: per defending team, xPTS allowed per shot and points allowed over
  expected ("opponent shooting luck").
* `shot_diet(shots, by)`: share and FG% by zone and by shot type against the league.
* `shot_profile(shots, model, by)`: one wide row per entity (rim / mid / 3 / corner-3 frequency,
  average distance, assisted share, xPTS per shot, pox100): the shot features the box-impact model uses.
* `calibration_table`, `league_grid` (square or hex cells of league make rates for shot charts,
  x_ft -25..25, y_ft 0..GRID_Y_MAX, feet from the rim).
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
import scipy.sparse as sp

from oddsmarkets.basketball.models import _io

MODEL_VERSION = "xpts-1"

DIST_KNOTS = [0, 1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 23, 24, 25, 26, 28, 30, 34, 40, 50, 94]
ANGLE_KNOTS = [0, 15, 30, 45, 60, 75, 90, 120, 180]
ZONES = ["rim", "paint", "mid", "corner3", "ab3", "heave"]
SHOT_TYPES = ["dunk", "layup", "tip", "hook", "floater", "jumper", "pullup", "stepback", "fadeaway", "turnaround", "other"]
PERIODS = ["1", "2", "3", "4", "OT"]
CLOCKS = ["normal", "late", "end"]
MARGIN_EDGES = [-9.5, -3.5, 3.5, 9.5]          # 5 buckets
MARGINS = ["m<=-10", "m-9..-4", "m-3..3", "m4..9", "m>=10"]
BINARY = ["three", "assisted", "putback", "transition"]

LAMBDA_SMOOTH = 30.0       # second-difference penalty on the distance / angle splines
LAMBDA_TINY = 1e-3         # ridge on spline coefficients (they sum to the intercept's level)
LAMBDA_CAT = 1.0           # ridge on one-hot and indicator log-odds: prior sd 1
SHRINK_SHOTS = 250         # pseudo-shots at zero for the shrunk shot-making number
GRID_Y_MAX = 35.0


# ----------------------------------------------------------------------------- inputs

def as_shots(shots: Any) -> pd.DataFrame:
    """A SHOT table (DataFrame, contract {"cols","rows"} dict or row lists) with typed columns."""
    df = _io.as_frame(shots, _io.SHOT_COLS).copy()
    if df.empty:
        return pd.DataFrame(columns=_io.SHOT_COLS)
    for c in ("t", "period", "x_ft", "y_ft", "dist_ft", "angle_deg", "value", "made", "assisted", "blocked", "putback",
              "transition", "margin_before", "clutch"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "value" not in df or df["value"].isna().all():
        df["value"] = np.where(df.get("zone", pd.Series("", index=df.index)).isin(["corner3", "ab3"]), 3, 2)
    df["value"] = df["value"].fillna(2).astype(int)
    if "dist_ft" not in df or df["dist_ft"].isna().any():
        d = np.hypot(df.get("x_ft", 0).astype(float), df.get("y_ft", 0).astype(float))
        df["dist_ft"] = df["dist_ft"].fillna(pd.Series(d, index=df.index)) if "dist_ft" in df else d
    if "angle_deg" not in df:
        df["angle_deg"] = np.degrees(np.arctan2(df["x_ft"].astype(float), df["y_ft"].astype(float)))
    for c in ("made", "assisted", "putback", "transition", "blocked", "clutch"):
        df[c] = df[c].fillna(0).astype(int) if c in df else 0
    df["margin_before"] = df["margin_before"].fillna(0.0) if "margin_before" in df else 0.0
    df["zone"] = df["zone"].fillna("mid").astype(str) if "zone" in df else "mid"
    df["shot_type"] = df["shot_type"].fillna("other").astype(str) if "shot_type" in df else "other"
    for c in ("shooter", "team", "game_id"):
        if c in df:
            df[c] = df[c].astype(str)
    return df


def _clock_left(df: pd.DataFrame, league: str | pd.Series) -> np.ndarray:
    per = df["period"].fillna(1).astype(int).to_numpy()
    t = df["t"].fillna(0).astype(float).to_numpy()
    lg = df["league"].astype(str).to_numpy() if "league" in df else np.full(len(df), str(league))
    end = np.array([_io.period_start(l, p) + _io.period_len(l, p) for l, p in zip(lg, per)], float) if len(df) else np.zeros(0)
    return end - t


def _codes(values: pd.Series | np.ndarray, levels: list[str]) -> np.ndarray:
    m = {v: i for i, v in enumerate(levels)}
    return np.array([m.get(v, -1) for v in values], int)


def _onehot(codes: np.ndarray, k: int) -> sp.csr_matrix:
    n = len(codes)
    ok = codes >= 0
    return sp.csr_matrix((np.ones(ok.sum()), (np.arange(n)[ok], codes[ok])), shape=(n, k))


def _design(spec: dict, df: pd.DataFrame) -> sp.csr_matrix:
    n = len(df)
    league = spec.get("league", "nba")
    blocks = [sp.csr_matrix(np.ones((n, 1)))]
    blocks.append(_io.hat_basis(df["dist_ft"].astype(float).to_numpy(), spec["dist_knots"]))
    blocks.append(_io.hat_basis(np.abs(df["angle_deg"].fillna(0).astype(float).to_numpy()), spec["angle_knots"]))
    blocks.append(_onehot(_codes(df["zone"], spec["zones"]), len(spec["zones"])))
    blocks.append(_onehot(_codes(df["shot_type"], spec["types"]), len(spec["types"])))
    binv = np.column_stack([(df["value"].to_numpy() == 3).astype(float), df["assisted"].to_numpy(float),
                            df["putback"].to_numpy(float), df["transition"].to_numpy(float)])
    blocks.append(sp.csr_matrix(binv))
    per = df["period"].fillna(1).astype(int).to_numpy()
    blocks.append(_onehot(_codes(np.where(per > 4, "OT", per.astype(str)), PERIODS), len(PERIODS)))
    left = _clock_left(df, league)
    blocks.append(_onehot(_codes(np.where(left <= 4, "end", np.where(left <= 24, "late", "normal")), CLOCKS), len(CLOCKS)))
    mb = np.digitize(df["margin_before"].astype(float).to_numpy(), MARGIN_EDGES)
    blocks.append(_onehot(mb, len(MARGINS)))
    if len(spec.get("leagues") or []) > 1:
        blocks.append(_onehot(_codes(df["league"].astype(str), spec["leagues"]), len(spec["leagues"])))
    return sp.hstack(blocks, format="csr")


def _columns(spec: dict) -> list[tuple[str, str]]:
    cols = [("intercept", "")]
    cols += [("dist", str(k)) for k in spec["dist_knots"]]
    cols += [("angle", str(k)) for k in spec["angle_knots"]]
    cols += [("zone", z) for z in spec["zones"]]
    cols += [("type", t) for t in spec["types"]]
    cols += [("flag", b) for b in BINARY]
    cols += [("period", p) for p in PERIODS]
    cols += [("clock", c) for c in CLOCKS]
    cols += [("margin", m) for m in MARGINS]
    if len(spec.get("leagues") or []) > 1:
        cols += [("league", l) for l in spec["leagues"]]
    return cols


def _penalty(spec: dict, cols: list[tuple[str, str]], lam_smooth: float, lam_cat: float) -> np.ndarray:
    p = len(cols)
    P = np.zeros((p, p))
    kinds = [c[0] for c in cols]
    for kind in ("dist", "angle"):
        ix = [j for j, k in enumerate(kinds) if k == kind]
        P[np.ix_(ix, ix)] += lam_smooth * _io.diff_penalty(len(ix), 2) + LAMBDA_TINY * np.eye(len(ix))
    for j, k in enumerate(kinds):
        if k not in ("intercept", "dist", "angle"):
            P[j, j] += lam_cat
    return P


# ----------------------------------------------------------------------------- fit / predict

def fit_xpts(shots: Any, league: str = "nba", lam_smooth: float = LAMBDA_SMOOTH, lam_cat: float = LAMBDA_CAT,
             weights: np.ndarray | None = None) -> dict:
    """Fit the make-probability model on a SHOT table. Returns a JSON-serialisable model dict
    {"version","league","spec","coef":{kind:{level:b}},"beta","n","fg","pps","loglik","iters"}.
    With no shots returns {"ok": False, "reason"}."""
    df = as_shots(shots)
    df = df[df["dist_ft"].notna()]
    if len(df) < 50:
        return {"ok": False, "reason": f"only {len(df)} shots"}
    leagues = sorted(df["league"].astype(str).unique()) if "league" in df else [league]
    spec = {"league": league, "leagues": leagues, "dist_knots": DIST_KNOTS, "angle_knots": ANGLE_KNOTS,
            "zones": ZONES, "types": SHOT_TYPES}
    X = _design(spec, df)
    cols = _columns(spec)
    P = _penalty(spec, cols, lam_smooth, lam_cat)
    y = df["made"].to_numpy(float)
    fg = float(y.mean())
    b0 = np.zeros(len(cols))
    b0[0] = math.log(max(fg, 1e-3) / max(1 - fg, 1e-3))
    # the hat basis sums to one, so put the base level in the spline and keep the intercept at zero start
    res = _io.logistic_fit(X, y, P, w=weights, beta0=b0)
    beta = res["beta"]
    coef: dict[str, dict[str, float]] = {}
    for (k, lvl), b in zip(cols, beta):
        coef.setdefault(k, {})[lvl] = float(b)
    return {"ok": True, "version": MODEL_VERSION, "league": league, "spec": spec, "coef": coef,
            "beta": [float(b) for b in beta], "n": int(len(df)), "fg": fg,
            "pps": float((y * df["value"].to_numpy()).mean()), "loglik": float(res["loglik"]), "iters": int(res["iters"])}


def p_make(model: dict, shots: Any) -> np.ndarray:
    """Make probability per shot."""
    df = as_shots(shots)
    if df.empty or not model or not model.get("ok", True) or "beta" not in model:
        return np.zeros(len(df))
    X = _design(model["spec"], df)
    return _io.sigmoid(X @ np.asarray(model["beta"], float))


def xpts(model: dict, shots: Any) -> np.ndarray:
    """Expected points per shot: P(make) * value."""
    df = as_shots(shots)
    return p_make(model, df) * df["value"].to_numpy(float)


def distance_curve(model: dict, dists: np.ndarray | None = None, zone: str | None = None, shot_type: str = "jumper",
                   value: int | None = None) -> pd.DataFrame:
    """Make probability against distance with the other features at their baseline (straight on,
    unassisted half-court, period 2, normal clock, tied); zone and value follow the distance when not given."""
    d = np.arange(0, 31, 1.0) if dists is None else np.asarray(dists, float)
    z = [zone or ("rim" if x < 4 else "paint" if x < 14 else "mid" if x < 23.75 else "ab3" if x <= 40 else "heave") for x in d]
    v = [value or (3 if x >= 23.75 else 2) for x in d]
    df = pd.DataFrame({"t": 900.0, "period": 2, "dist_ft": d, "angle_deg": 0.0, "zone": z, "shot_type": shot_type,
                       "value": v, "made": 0, "assisted": 0, "putback": 0, "transition": 0, "margin_before": 0.0,
                       "x_ft": 0.0, "y_ft": d})
    df["p"] = p_make(model, df)
    df["xpts"] = df["p"] * df["value"]
    return df[["dist_ft", "zone", "value", "p", "xpts"]]


def with_xpts(shots: Any, model: dict) -> pd.DataFrame:
    df = as_shots(shots).copy()
    df["p"] = p_make(model, df)
    df["xpts"] = df["p"] * df["value"]
    df["pts"] = df["made"] * df["value"]
    return df


# ----------------------------------------------------------------------------- tables

def _agg(df: pd.DataFrame, key: str) -> pd.DataFrame:
    df = df.assign(_var=df["value"] ** 2 * df["p"] * (1 - df["p"]))
    g = df.groupby(key)
    out = pd.DataFrame({"shots": g.size(), "made": g["made"].sum(), "pts": g["pts"].sum(), "xpts": g["xpts"].sum(),
                        "var": g["_var"].sum()})
    out["fg"] = out["made"] / out["shots"]
    out["pps"] = out["pts"] / out["shots"]
    out["xpps"] = out["xpts"] / out["shots"]
    out["pox"] = out["pts"] - out["xpts"]
    out["pox100"] = 100 * out["pox"] / out["shots"]
    out["se_pox100"] = 100 * np.sqrt(out["var"]) / out["shots"]
    out["pox100_shrunk"] = 100 * out["pox"] / (out["shots"] + SHRINK_SHOTS)
    return out.drop(columns="var")


def shot_making(shots: Any, model: dict, by: str = "shooter", min_shots: int = 0) -> pd.DataFrame:
    """Per shooter (by="shooter") or shooting team (by="team"): shots, made, pts, xpts, fg, pps,
    xpps, pox (points over expected), pox100 (per 100 shots) with se and a shrunk version."""
    df = with_xpts(shots, model)
    if df.empty:
        return pd.DataFrame()
    out = _agg(df, by)
    return out[out["shots"] >= min_shots]


def _defender(df: pd.DataFrame, games: dict | None) -> pd.Series:
    if games:
        def opp(r):
            g = games.get(r["game_id"]) or {}
            return g.get("away") if r["team"] == g.get("home") else g.get("home")
        return df.apply(opp, axis=1).astype(str)
    teams = df.groupby("game_id")["team"].agg(lambda s: sorted(set(s)))
    other = {}
    for gid, ts in teams.items():
        if len(ts) == 2:
            other[(gid, ts[0])], other[(gid, ts[1])] = ts[1], ts[0]
    return pd.Series([other.get((g, t)) for g, t in zip(df["game_id"], df["team"])], index=df.index)


def defense_xpts(shots: Any, model: dict, games: dict | None = None) -> pd.DataFrame:
    """Per defending team: opponent shots, xPTS allowed per shot (shot quality conceded), points allowed
    per shot, and pox100 allowed (positive = opponents shot better than expected: bad luck or bad contests)."""
    df = with_xpts(shots, model)
    if df.empty:
        return pd.DataFrame()
    df["def_team"] = _defender(df, games)
    df = df[df["def_team"].notna()]
    return _agg(df, "def_team")


def shot_diet(shots: Any, by: str = "shooter", min_shots: int = 0) -> pd.DataFrame:
    """Long table: entity, kind ("zone" | "type"), cat, n, share, fg, lg_share, lg_fg, share_diff, fg_diff."""
    df = as_shots(shots)
    if df.empty:
        return pd.DataFrame()
    tot = df.groupby(by).size()
    keep = tot[tot >= min_shots].index
    out = []
    for kind, col in (("zone", "zone"), ("type", "shot_type")):
        lg = df.groupby(col)["made"].agg(["size", "mean"])
        lg_share = lg["size"] / len(df)
        g = df[df[by].isin(keep)].groupby([by, col])["made"].agg(["size", "mean"]).reset_index()
        g.columns = ["entity", "cat", "n", "fg"]
        g["kind"] = kind
        g["share"] = g["n"] / g["entity"].map(tot)
        g["lg_share"] = g["cat"].map(lg_share)
        g["lg_fg"] = g["cat"].map(lg["mean"])
        g["share_diff"] = g["share"] - g["lg_share"]
        g["fg_diff"] = g["fg"] - g["lg_fg"]
        out.append(g)
    return pd.concat(out, ignore_index=True)[["entity", "kind", "cat", "n", "share", "fg", "lg_share", "lg_fg",
                                               "share_diff", "fg_diff"]]


def shot_profile(shots: Any, model: dict | None = None, by: str = "shooter") -> pd.DataFrame:
    """One wide row per entity: shots, rim_freq, paint_freq, mid_freq, three_freq, corner3_freq, avg_dist,
    assisted_share (of makes), putback_freq, transition_freq, and with a model xpps and pox100."""
    df = with_xpts(shots, model) if model and model.get("ok", True) else as_shots(shots)
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(by)
    out = pd.DataFrame({"shots": g.size()})
    for z, name in (("rim", "rim_freq"), ("paint", "paint_freq"), ("mid", "mid_freq"), ("corner3", "corner3_freq")):
        out[name] = g["zone"].agg(lambda s, z=z: float(np.mean(s == z)))
    out["three_freq"] = g["value"].agg(lambda s: float(np.mean(s == 3)))
    out["avg_dist"] = g["dist_ft"].mean()
    made = df[df["made"] == 1].groupby(by)["assisted"].mean()
    out["assisted_share"] = made.reindex(out.index)
    out["putback_freq"] = g["putback"].mean()
    out["transition_freq"] = g["transition"].mean()
    if "xpts" in df:
        a = _agg(df, by)
        out["xpps"] = a["xpps"]
        out["pox100"] = a["pox100"]
        out["pox100_shrunk"] = a["pox100_shrunk"]
    return out


def calibration_table(shots: Any, model: dict, by: str = "zone", bins: int = 10) -> pd.DataFrame:
    """Observed against predicted by zone (by="zone"), shot type (by="shot_type") or probability decile
    (by="decile"): n, fg, p_mean, pts, xpts, diff (fg - p_mean), z (diff / binomial se), brier."""
    df = with_xpts(shots, model)
    if df.empty:
        return pd.DataFrame()
    if by == "decile":
        df["decile"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False)
    df["sq"] = (df["made"] - df["p"]) ** 2
    df["pv"] = df["p"] * (1 - df["p"])
    g = df.groupby(by)
    out = pd.DataFrame({"n": g.size(), "fg": g["made"].mean(), "p_mean": g["p"].mean(), "pts": g["pts"].sum(),
                        "xpts": g["xpts"].sum(), "brier": g["sq"].mean(), "pv": g["pv"].sum()})
    out["diff"] = out["fg"] - out["p_mean"]
    out["z"] = out["diff"] * out["n"] / np.sqrt(out["pv"].clip(lower=1e-9))
    return out.drop(columns="pv")


def _hex_centres(x: np.ndarray, y: np.ndarray, r: float) -> tuple[np.ndarray, np.ndarray]:
    """Nearest centre of a pointy-top hexagonal lattice with circumradius r (axial rounding)."""
    q = (math.sqrt(3) / 3 * x - y / 3) / r
    rr = (2 / 3 * y) / r
    xc, zc = q, rr
    yc = -xc - zc
    rx, ry, rz = np.round(xc), np.round(yc), np.round(zc)
    dx, dy, dz = np.abs(rx - xc), np.abs(ry - yc), np.abs(rz - zc)
    fx = (dx > dy) & (dx > dz)
    fz = ~fx & ~(dy > dz)
    rx = np.where(fx, -ry - rz, rx)
    rz = np.where(fz, -rx - ry, rz)
    cx = r * math.sqrt(3) * (rx + rz / 2)
    cy = r * 1.5 * rz
    return cx, cy


def league_grid(shots: Any, model: dict | None = None, kind: str = "square", size: float = 2.0,
                ref: pd.DataFrame | None = None, min_n: int = 1) -> pd.DataFrame:
    """Cells of make rates for shot charts in feet from the rim (x -25..25, y 0..GRID_Y_MAX).
    kind="square": size-ft squares; kind="hex": hexagons of circumradius `size`. Columns: x, y (cell centre),
    n, fg, pps, xpps (with a model), share (of all shots in the frame). With `ref` (a league grid of the
    same kind/size) adds lg_fg, lg_pps and fg_diff, pps_diff for a player or team chart."""
    df = with_xpts(shots, model) if model and model.get("ok", True) else as_shots(shots).assign(pts=lambda d: d["made"] * d["value"])
    df = df[df["x_ft"].notna() & df["y_ft"].notna()]
    df = df[(df["x_ft"].abs() <= 25) & (df["y_ft"] >= -5) & (df["y_ft"] <= GRID_Y_MAX)]
    if df.empty:
        return pd.DataFrame(columns=["x", "y", "n", "fg", "pps", "share"])
    x, y = df["x_ft"].to_numpy(float), df["y_ft"].to_numpy(float)
    if kind == "hex":
        cx, cy = _hex_centres(x, y, size)
    else:
        cx = (np.floor((x + 25) / size) + 0.5) * size - 25
        cy = (np.floor(np.clip(y, 0, None) / size) + 0.5) * size
    df = df.assign(x=np.round(cx, 3), y=np.round(cy, 3))
    g = df.groupby(["x", "y"])
    out = pd.DataFrame({"n": g.size(), "fg": g["made"].mean(), "pps": g["pts"].mean()})
    if "xpts" in df:
        out["xpps"] = g["xpts"].mean()
    out["share"] = out["n"] / len(df)
    out = out[out["n"] >= min_n].reset_index()
    if ref is not None and not ref.empty:
        r = ref.set_index(["x", "y"])
        k = list(zip(out["x"], out["y"]))
        out["lg_fg"] = [r["fg"].get(i, np.nan) for i in k]
        out["lg_pps"] = [r["pps"].get(i, np.nan) for i in k]
        out["fg_diff"] = out["fg"] - out["lg_fg"]
        out["pps_diff"] = out["pps"] - out["lg_pps"]
    return out


# ----------------------------------------------------------------------------- season loader

def _records(df: pd.DataFrame, nd: int = 4) -> dict:
    return {str(k): _io.clean(v, nd) for k, v in df.to_dict(orient="index").items()}


def for_season(league: str, season: int, through: str | None = None, use_cache: bool = True) -> dict:
    """Fit xPTS on one league-season's committed shots.json (optionally only games on or before
    `through`, YYYY-MM-DD, via store.json dates) and return a JSON payload:
    {"ok","league","season","model","players","teams","defense","calibration","calibration_type",
     "curve","grid","n_shots"}. Never raises; {"ok": False, "reason"} when there is nothing to fit."""
    try:
        path = _io.data_root() / league / str(season) / "shots.json"
        spath = _io.data_root() / league / str(season) / "store.json"
        key = _io.file_key(MODEL_VERSION, path, spath if through else "", through)

        def build():
            raw = _io.read_json(path)
            if not raw:
                return {"ok": False, "reason": "no shots.json"}
            df = as_shots(raw)
            games = None
            store = _io.read_json(spath) if spath.exists() else None
            if store:
                games = store.get("games") or {}
            if through and games:
                ok = {gid for gid, g in games.items() if str(g.get("date") or "")[:10] <= through}
                df = df[df["game_id"].isin(ok)]
            model = fit_xpts(df, league=league)
            if not model.get("ok"):
                return {"ok": False, "reason": model.get("reason")}
            return {"ok": True, "league": league, "season": int(season), "through": through, "n_shots": int(len(df)),
                    "model": model,
                    "players": _records(shot_making(df, model, "shooter").join(shot_profile(df, None, "shooter").drop(columns="shots"))),
                    "teams": _records(shot_making(df, model, "team").join(shot_profile(df, None, "team").drop(columns="shots"))),
                    "defense": _records(defense_xpts(df, model, games)),
                    "calibration": _records(calibration_table(df, model, "zone")),
                    "calibration_type": _records(calibration_table(df, model, "shot_type")),
                    "curve": _io.clean(distance_curve(model).to_dict(orient="records")),
                    "grid": _io.clean(league_grid(df, model, "hex", 1.5).to_dict(orient="records"))}

        return _io.cached("shots", f"{league}_{season}", key, build, use_cache)
    except Exception as exc:                                          # pragma: no cover - defensive
        return {"ok": False, "reason": f"xpts failed: {exc}"}
