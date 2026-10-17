"""
Kicking: field-goal make probability, kicker value (field goals over expected), extra points, and the
punt model (where the receiving team starts) with punter value.

Field goals
-----------
Every field-goal attempt (blocked counts as a miss). Logistic regression (Newton, small ridge) on

    x = (distance - 40) / 10:  1, x, (x + 1)+, x+, (x - 1)+, era, era * x, wind10 * outdoors,
                               wind10 * x * outdoors, cold * outdoors, indoor, altitude (>= 3,000 ft), altitude * x

(a piecewise-linear logit in distance with knots at 30, 40 and 50 yards, so it extrapolates linearly past
the longest attempts instead of bending back up as a polynomial can)

with era = (season - 2010) / 10, wind10 = wind / 10 mph, cold = max(0, 50 - temp) / 10. Distance is
nflverse `kick_distance` (line of scrimmage + 17 or 18 yards). Kicker skill is a random effect on the
logit scale: each kicker's offset b_k is the posterior mode under b_k ~ N(0, tau^2) given the fixed part
as an offset, with tau^2 by the method of moments (variance of the raw offsets less their mean sampling
variance). `fg_prob` uses the offset of a known kicker (shrunk), 0 otherwise.

Kicker value: field goals over expected (FGOE = makes - sum p, with p the fixed part: league kicker in
these conditions) and points over expected (3 FGOE plus extra points over the season's league PAT rate).

Punts
-----
The receiving team's yard line after a punt (from its own goal: 100 - yardline_100 + kick_distance -
return_yards; 80 on a touchback; the next snap's spot when the kick distance is missing, e.g. blocked)
as empirical quantiles per yard line of the punt (5-yard window, widened until N_MIN punts), plus
the rate of return touchdowns. Punter value: the receiving team's spot over expected, in yards (positive =
pinned deeper than expected), per punt and in total.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.models import _io

MODEL_VERSION = "kick-3"
FG_TERMS = ["const", "x", "k30", "k40", "k50", "era", "era_x", "wind", "wind_x", "cold", "indoor", "alt", "alt_x"]
RIDGE = 1e-3
QUANTS = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
PUNT_BIN = 5
N_MIN = 60
ALT_FT = 3000.0


# ============================================================================ field goals

def fg_attempts(d: pd.DataFrame) -> pd.DataFrame:
    pt = d["play_type"].astype(str)
    r = d["field_goal_result"].astype(str)
    m = (pt == "field_goal") & r.isin(["made", "missed", "blocked"]) & pd.to_numeric(d["kick_distance"], errors="coerce").notna()
    f = d[m]
    out = pd.DataFrame({
        "season": pd.to_numeric(f["season"], errors="coerce").to_numpy(float),
        "game_id": f["game_id"].astype(str).to_numpy(),
        "kicker": f["kicker_player_id"].astype(object).to_numpy(),
        "kicker_name": f["kicker_player_name"].astype(object).to_numpy() if "kicker_player_name" in f else None,
        "team": f["posteam"].astype(object).to_numpy(),
        "distance": pd.to_numeric(f["kick_distance"], errors="coerce").to_numpy(float),
        "made": (r[m] == "made").astype(float).to_numpy(),
        "wind": pd.to_numeric(f["wind"], errors="coerce").to_numpy(float),
        "temp": pd.to_numeric(f["temp"], errors="coerce").to_numpy(float),
        "indoor": pd.to_numeric(f["indoor"], errors="coerce").to_numpy(float) if "indoor" in f else 0.0,
        "altitude": pd.to_numeric(f["altitude"], errors="coerce").to_numpy(float) if "altitude" in f else 0.0,
    })
    return out


def design(distance, season, wind=None, temp=None, indoor=None, altitude=None) -> np.ndarray:
    dist = np.asarray(distance, float)
    n = len(dist)
    x = (dist - 40.0) / 10.0
    era = (np.broadcast_to(np.asarray(season, float), (n,)) - 2010.0) / 10.0
    ind = np.nan_to_num(np.broadcast_to(np.asarray(0.0 if indoor is None else indoor, float), (n,)), nan=0.0)
    out = 1.0 - ind
    w = np.nan_to_num(np.broadcast_to(np.asarray(0.0 if wind is None else wind, float), (n,)), nan=0.0) / 10.0 * out
    t = np.broadcast_to(np.asarray(np.nan if temp is None else temp, float), (n,))
    cold = np.nan_to_num(np.clip(50.0 - t, 0, None), nan=0.0) / 10.0 * out
    alt = (np.nan_to_num(np.broadcast_to(np.asarray(0.0 if altitude is None else altitude, float), (n,))) >= ALT_FT).astype(float)
    return np.column_stack([np.ones(n), x, np.maximum(x + 1, 0), np.maximum(x, 0), np.maximum(x - 1, 0), era, era * x,
                            w, w * x, cold, ind, alt, alt * x])


def fit_fg(att: pd.DataFrame) -> dict:
    a = att[np.isfinite(att["distance"]) & (att["distance"] >= 15) & (att["distance"] <= 75)].reset_index(drop=True)
    if len(a) < 50:
        return {"ok": False, "reason": f"only {len(a)} attempts"}
    X = design(a["distance"], a["season"], a["wind"], a["temp"], a["indoor"], a["altitude"])
    y = a["made"].to_numpy(float)
    r = _io.logit_fit(X, y, ridge=np.r_[0.0, np.full(X.shape[1] - 1, RIDGE)])
    beta = r["beta"]
    p_fixed = _io.sigmoid(X @ beta)
    re = kicker_effects(a["kicker"].to_numpy(object), y, X @ beta)
    return {"ok": True, "version": MODEL_VERSION, "terms": FG_TERMS, "beta": beta.tolist(), "se": r["se"].tolist(),
            "n": int(len(a)), "tau": re["tau"], "kickers": re["effects"],
            "logloss": _io.log_loss(y, p_fixed), "base_rate": float(y.mean())}


def kicker_effects(kickers: np.ndarray, y: np.ndarray, eta: np.ndarray, iters: int = 30) -> dict:
    """Random-effect posterior modes b_k (logit scale) with tau^2 by moments; {"tau", "effects": {k: [b, n]}}."""
    k = pd.Series(kickers).astype(str).to_numpy()
    ok = pd.Series(kickers).notna().to_numpy()
    codes, uniq = pd.factorize(k[ok])
    yy, ee = y[ok], eta[ok]
    if not len(uniq):
        return {"tau": 0.0, "effects": {}}
    nk = len(uniq)
    # raw (nearly unpenalised) offsets and their sampling variances -> tau^2 by moments
    braw, inf_raw = _re_solve(codes, yy, ee, nk, 100.0, iters)
    n_att = np.bincount(codes, minlength=nk)
    m = n_att >= 20
    if m.sum() >= 5:
        tau2 = float(max(0.005, np.average(braw[m] ** 2, weights=n_att[m]) - np.average(1.0 / inf_raw[m], weights=n_att[m])))
    else:
        tau2 = 0.09
    b, _ = _re_solve(codes, yy, ee, nk, tau2, iters)
    return {"tau": float(np.sqrt(tau2)), "effects": {u: [float(b[i]), int(n_att[i])] for i, u in enumerate(uniq)}}


def _re_solve(codes: np.ndarray, y: np.ndarray, eta: np.ndarray, nk: int, tau2: float, iters: int) -> tuple[np.ndarray, np.ndarray]:
    """Posterior modes of per-group logit offsets under N(0, tau2), the fixed part as an offset."""
    b = np.zeros(nk)
    info = np.ones(nk)
    for _ in range(iters):
        p = _io.sigmoid(eta + b[codes])
        g = np.bincount(codes, y - p, nk) - b / tau2
        info = np.bincount(codes, p * (1 - p), nk) + 1.0 / tau2
        step = g / info
        b = b + step
        if np.max(np.abs(step)) < 1e-8:
            break
    return b, info


def fg_prob(fit: dict, distance, season, wind=None, temp=None, indoor=None, altitude=None, kicker=None) -> np.ndarray:
    """Make probability (vectorised). `kicker` (ids, aligned) adds the kicker's shrunk random effect."""
    X = design(np.atleast_1d(np.asarray(distance, float)), season, wind, temp, indoor, altitude)
    eta = X @ np.asarray(fit["beta"], float)
    if kicker is not None:
        eff = fit.get("kickers") or {}
        ks = np.atleast_1d(np.asarray(kicker, object))
        eta = eta + np.array([(eff.get(str(k)) or [0.0])[0] if k is not None else 0.0 for k in ks])
    return _io.sigmoid(eta)


def kicker_value(att: pd.DataFrame, fit: dict, pats: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per kicker and season: attempts, makes, expected (league kicker), FGOE, points over expected (FG and
    PAT), the random effect and its make-probability lift at 50 yards."""
    a = att.copy()
    a["p"] = fg_prob(fit, a["distance"], a["season"], a["wind"], a["temp"], a["indoor"], a["altitude"])
    g = a.groupby(["kicker", "season"], dropna=True).agg(name=("kicker_name", "last"), team=("team", "last"),
                                                         att=("made", "size"), made=("made", "sum"),
                                                         exp=("p", "sum"), avg_dist=("distance", "mean"),
                                                         long_att=("distance", lambda s: int((s >= 50).sum())))
    g = g.reset_index()
    g["fgoe"] = g["made"] - g["exp"]
    g["fg_pts_oe"] = 3.0 * g["fgoe"]
    g["pat_att"] = 0
    g["pat_oe"] = 0.0
    if pats is not None and len(pats):
        pg = pats.groupby(["kicker", "season"]).agg(pat_att=("good", "size"), pat_good=("good", "sum"), pat_exp=("p", "sum")).reset_index()
        g = g.drop(columns=["pat_att", "pat_oe"]).merge(pg, on=["kicker", "season"], how="left")
        g["pat_att"] = g["pat_att"].fillna(0).astype(int)
        g["pat_oe"] = (g["pat_good"] - g["pat_exp"]).fillna(0.0)
        g = g.drop(columns=["pat_good", "pat_exp"])
    g["pts_oe"] = g["fg_pts_oe"] + g["pat_oe"]
    eff = fit.get("kickers") or {}
    g["re"] = g["kicker"].map(lambda k: (eff.get(str(k)) or [0.0])[0])
    base50 = fg_prob(fit, [50.0], 2020)[0]
    g["lift50"] = _io.sigmoid(_io.logit(base50) + g["re"].to_numpy(float)) - base50
    return g.sort_values("pts_oe", ascending=False).reset_index(drop=True)


def pat_attempts(d: pd.DataFrame) -> pd.DataFrame:
    m = d["play_type"].astype(str) == "extra_point"
    e = d[m]
    r = e["extra_point_result"].astype(str)
    out = pd.DataFrame({"kicker": e["kicker_player_id"].astype(object).to_numpy(),
                        "season": pd.to_numeric(e["season"], errors="coerce").to_numpy(float),
                        "good": (r == "good").astype(float).to_numpy()})
    return out[r.isin(["good", "failed", "blocked"]).to_numpy()]


# ============================================================================ punts

def punt_rows(d: pd.DataFrame) -> pd.DataFrame:
    """Punts with the receiving team's resulting yard line (from its own goal) and a return-TD flag."""
    d = d.sort_values(["game_id", "play_id"], kind="mergesort").reset_index(drop=True)
    pt = d["play_type"].astype(str).to_numpy()
    idx = np.flatnonzero(pt == "punt")
    if not len(idx):
        return pd.DataFrame(columns=["season", "punter", "team", "yl", "opp_yl", "ret_td", "wind", "indoor"])
    yl = pd.to_numeric(d["yardline_100"], errors="coerce").to_numpy(float)
    kd = pd.to_numeric(d["kick_distance"], errors="coerce").to_numpy(float)
    rt = pd.to_numeric(d["return_yards"], errors="coerce").fillna(0).to_numpy(float)
    tb = pd.to_numeric(d["touchback"], errors="coerce").fillna(0).to_numpy(float)
    opp = 100 - yl + kd - rt
    opp = np.where(tb == 1, 80.0, opp)
    # next snap of the other team when the formula has no kick distance (blocked / aborted)
    g = d["game_id"].astype(str).to_numpy()
    pos = d["posteam"].astype(object).to_numpy()
    dn = pd.to_numeric(d["down"], errors="coerce").to_numpy(float)
    nxt_yl = np.full(len(d), np.nan)
    for i in idx:
        if np.isfinite(opp[i]):
            continue
        for j in range(i + 1, min(i + 4, len(d))):
            if g[j] != g[i]:
                break
            if np.isfinite(dn[j]) and pos[j] != pos[i]:
                nxt_yl[i] = yl[j]
                break
    opp = np.where(np.isfinite(opp), opp, nxt_yl)
    td = (pd.to_numeric(d["touchdown"], errors="coerce").fillna(0).to_numpy() == 1) & \
         (d["td_team"].astype(object).to_numpy() == d["defteam"].astype(object).to_numpy())
    out = pd.DataFrame({"season": pd.to_numeric(d["season"], errors="coerce").to_numpy(float)[idx],
                        "punter": d["punter_player_id"].astype(object).to_numpy()[idx],
                        "punter_name": (d["punter_player_name"].astype(object).to_numpy()[idx] if "punter_player_name" in d else None),
                        "team": pos[idx], "yl": yl[idx], "opp_yl": np.clip(opp[idx], 1, 99), "ret_td": td[idx].astype(float),
                        "wind": pd.to_numeric(d["wind"], errors="coerce").to_numpy(float)[idx],
                        "indoor": pd.to_numeric(d.get("indoor"), errors="coerce").to_numpy(float)[idx] if "indoor" in d else 0.0})
    return out[np.isfinite(out["opp_yl"]) & np.isfinite(out["yl"])].reset_index(drop=True)


def fit_punt(p: pd.DataFrame) -> dict:
    """Per yard line (1..99): quantiles of the receiving team's spot, its mean, and the return-TD rate."""
    yl = p["yl"].to_numpy(float)
    oy = p["opp_yl"].to_numpy(float)
    td = p["ret_td"].to_numpy(float)
    q, mean, rtd, nn = [], [], [], []
    for y in range(1, 100):
        w = PUNT_BIN // 2
        while True:
            m = np.abs(yl - y) <= w
            if m.sum() >= N_MIN or w >= 40:
                break
            w += 2
        if m.sum() == 0:
            q.append([float(min(99, 100 - y + 40))] * len(QUANTS))
            mean.append(float(min(99, 100 - y + 40)))
            rtd.append(0.005)
            nn.append(0)
            continue
        # neighbours pooled as they are (shifting them with the line of scrimmage breaks near the end zone,
        # where touchbacks cap the result)
        adj = np.clip(oy[m], 1, 99)
        q.append([float(v) for v in np.quantile(adj, QUANTS)])
        mean.append(float(adj.mean()))
        rtd.append(float((td[m].sum() + 0.5) / (m.sum() + 100)))
        nn.append(int(m.sum()))
    return {"ok": True, "quants": QUANTS.tolist(), "q": q, "mean": mean, "ret_td": rtd, "n": nn, "n_punts": int(len(p))}


def punt_outcomes(pfit: dict, yl) -> tuple[np.ndarray, np.ndarray]:
    """(receiving team's spot quantile points (n, 5), return-TD probability (n,)) for punts from `yl`."""
    y = np.clip(np.rint(np.asarray(yl, float)), 1, 99).astype(int) - 1
    return np.asarray(pfit["q"], float)[y], np.asarray(pfit["ret_td"], float)[y]


def punter_value(p: pd.DataFrame, pfit: dict) -> pd.DataFrame:
    y = np.clip(np.rint(p["yl"].to_numpy(float)), 1, 99).astype(int) - 1
    exp = np.asarray(pfit["mean"], float)[y]
    a = p.assign(exp=exp, oe=exp - p["opp_yl"].to_numpy(float))
    g = a.groupby(["punter", "season"], dropna=True).agg(name=("punter_name", "last"), team=("team", "last"),
                                                         punts=("oe", "size"), yds_oe=("oe", "sum"),
                                                         per_punt=("oe", "mean")).reset_index()
    return g.sort_values("yds_oe", ascending=False).reset_index(drop=True)


# ============================================================================ pipeline

def _rows(d: pd.DataFrame) -> pd.DataFrame:
    a = fg_attempts(d)
    a["kind"] = "fg"
    p = pat_attempts(d)
    p["kind"] = "pat"
    u = punt_rows(d)
    u["kind"] = "punt"
    return pd.concat([a, p, u], ignore_index=True)


def fit(seasons=None, use_cache: bool = True) -> dict:
    seasons = _io.season_range(seasons)
    key = _io.file_key(*[p for s in seasons for p in _io.source_files(s)], MODEL_VERSION)
    if use_cache:
        f = _io.get_fit("kicking", MODEL_VERSION)
        if f and f.get("key") == key:
            return f
    t = _io.stack(seasons, _rows)
    att = t[t["kind"] == "fg"].reset_index(drop=True)
    pats = t[t["kind"] == "pat"].reset_index(drop=True)
    punts = t[t["kind"] == "punt"].reset_index(drop=True)
    fg = fit_fg(att)
    pat_rate = pats.groupby("season")["good"].mean().to_dict() if len(pats) else {}
    out = {"ok": bool(fg.get("ok")), "version": MODEL_VERSION, "key": key, "fg": fg,
           "pat_rate": {str(int(k)): float(v) for k, v in pat_rate.items()},
           "punt": fit_punt(punts) if len(punts) else {"ok": False}}
    _io.store_fit("kicking", out)
    return out


def current_fit() -> dict | None:
    return _io.get_fit("kicking", MODEL_VERSION)


def pat_prob(fit: dict, season: int) -> float:
    r = (fit.get("pat_rate") or {}).get(str(int(season)))
    if r is not None:
        return float(r)
    return 0.94 if int(season) >= 2015 else 0.99


def values(season: int, d: pd.DataFrame | None = None, fit_: dict | None = None) -> dict:
    """Kicker and punter tables for one season (lists of records)."""
    f = fit_ or current_fit()
    d = _io.plays(season) if d is None else d
    if f is None or d is None or not len(d) or not f.get("ok"):
        return {"kickers": [], "punters": []}
    att = fg_attempts(d)
    pats = pat_attempts(d)
    pats["p"] = pats["season"].map(lambda s: pat_prob(f, s))
    kv = kicker_value(att, f["fg"], pats) if len(att) else pd.DataFrame()
    pv = punter_value(punt_rows(d), f["punt"]) if f.get("punt", {}).get("ok") else pd.DataFrame()
    return {"kickers": _io.clean(kv.to_dict("records")), "punters": _io.clean(pv.to_dict("records"))}


def for_season(season: int, use_cache: bool = True) -> dict:
    f = current_fit()
    srcs = _io.source_files(season)
    key = _io.file_key(*srcs, MODEL_VERSION, (f or {}).get("key"))
    return _io.cached("kicking", str(int(season)), key, lambda: values(season, fit_=f), use_cache)


def export_fits(seasons=None) -> dict:
    f = fit(seasons)
    _io.export_fit("kicking", f)
    return f
