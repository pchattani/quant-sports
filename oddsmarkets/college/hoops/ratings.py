"""
Opponent-adjusted efficiency ratings and tempo for college basketball (per 100 possessions; tempo per 40 minutes).

Efficiency fit (`fit`): every finished game gives two observations, one per offence,

    100 * pts_home / poss = mu + o_home + d_away + h/2 * [not neutral] + e
    100 * pts_away / poss = mu + o_away + d_home - h/2 * [not neutral] + e

weighted w = 0.5 ** (age_days / half_life) * poss / mean(poss), with a ridge penalty
lam_i * ((o_i - o_i^prior)^2 + (d_i - d_i^prior)^2) toward the preseason prior (lam in games-equivalents), solved
by the dense normal equations (about 370 teams). Non-Division-I opponents are one pooled team (`data.ND1`).
Reported, centred on the Division I members (the pooled team excluded from the mean):

    off_i = L + o_i - mean(o),  def_i = L + d_i - mean(d),  rating_i = off_i - def_i
    L = mu + mean(o) + mean(d)   (an average D-I offence v an average D-I defence)

`rating` is the adjusted efficiency margin per 100 possessions v an average D-I team on a neutral floor;
`se` from the posterior covariance s^2 (X'WX + P)^-1.

Tempo: possessions per 40 minutes, pace_game = P + p_home + p_away (ridge toward the prior), reported as
tempo_i = P + mean(p) + p_i; games without a possession count get poss = (P + p_h + p_a) scaled for overtime.

Kalman paths (`paths`): the rating vector as a random walk (q per day), each game observing
100 * margin / poss - h [not neutral] = r_home - r_away + e.

Preseason prior (`prior_for`): last season's full-season rating regressed,
    rating_prior = b1 * rating_last + b2 * conf_mean_last + c
(conf_mean_last = last season's mean rating of the team's conference as constituted this season; new members get
the fitted new-member mean), b1, b2, c and the residual sd fitted walk-forward on season pairs before the target
season only. Offence and defence keep last season's split scaled by b1; tempo regressed with its own slope.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import scipy.linalg as sla

from oddsmarkets.college.hoops import data as D

VERSION = 4
HALF_LIFE = {"mbb": 60.0, "wbb": 60.0}
RIDGE = {"mbb": 6.0, "wbb": 6.0}
RIDGE_PACE = 4.0
Q_PER_DAY = {"mbb": 0.04, "wbb": 0.04}
HCA0 = {"mbb": 4.5, "wbb": 4.5}
DAMP: dict[str, tuple[float, float] | None] = {"mbb": None, "wbb": None}   # blowout damping (cap per 100, slope beyond)


def _normal(npar: int, cols: np.ndarray, vals: np.ndarray, w: np.ndarray, y: np.ndarray):
    """X'WX and X'Wy for a sparse design given as per-row column indices and values."""
    if not len(w):
        return np.zeros((npar, npar)), np.zeros(npar)
    idx = (cols[:, :, None] * npar + cols[:, None, :]).ravel()
    wt = (vals[:, :, None] * vals[:, None, :] * w[:, None, None]).ravel()
    H = np.bincount(idx, weights=wt, minlength=npar * npar).reshape(npar, npar)
    b = np.bincount(cols.ravel(), weights=(vals * (w * y)[:, None]).ravel(), minlength=npar)
    return H, b


def empty_prior(tab: dict, level: str) -> dict:
    T = tab["T"]
    L, P = D.DEFAULT_ORTG[level], D.DEFAULT_PACE[level]
    off = np.full(T, L)
    de = np.full(T, L)
    off[-1], de[-1] = L - 10.0, L + 10.0
    return {"off": off, "def": de, "pace": np.full(T, P), "lam": np.full(T, 0.3), "se": np.full(T, 10.0),
            "L": L, "P": P, "hca": HCA0[level], "source": "none"}


def fit_tempo(tab: dict, m: np.ndarray, prior: dict, w: np.ndarray) -> dict:
    G, T = tab["g"], tab["T"]
    has = m & np.isfinite(G["pace40"])
    P0 = float(prior["P"])
    ppr = np.asarray(prior["pace"], float) - P0
    npar = 1 + T
    hi, ai = G["h"][has], G["a"][has]
    cols = np.stack([np.zeros(len(hi), int), 1 + hi, 1 + ai], 1)
    vals = np.ones(cols.shape)
    H, b = _normal(npar, cols, vals, w[has], G["pace40"][has])
    lam = RIDGE_PACE * np.asarray(prior.get("lam", np.ones(T)), float).clip(0.3, None)
    H[1:, 1:] += np.diag(lam)
    b[1:] += lam * ppr
    H[0, 0] += 1e-3
    b[0] += 1e-3 * P0
    try:
        sol = sla.solve(H, b, assume_a="pos")
    except (sla.LinAlgError, ValueError):
        sol = np.linalg.lstsq(H, b, rcond=None)[0]
    p = sol[1:]
    pm = p[tab["member"]].mean()
    return {"P": float(sol[0]), "p": p, "league_pace": float(sol[0] + 2 * pm), "tempo": sol[0] + pm + p}


def fit(tab: dict, m: np.ndarray | None, prior: dict, ref_day: int | None = None, half_life: float | None = None,
        ridge: float | None = None, want_se: bool = False) -> dict:
    """Ratings from the games in mask `m` (all finished games when None). Arrays over tab["teams"]:
    {"off","def","net","tempo","se"(want_se),"games"} plus "L","league_pace","hca","hca_pts","resid_sd","n"."""
    lv = tab["level"]
    G, T = tab["g"], tab["T"]
    n_all = len(G["day"])
    m = np.ones(n_all, bool) if m is None else m
    hl = float(half_life if half_life is not None else HALF_LIFE[lv])
    lam0 = float(ridge if ridge is not None else RIDGE[lv])
    ref = int(ref_day if ref_day is not None else (G["day"][m].max() if m.any() else 0))
    age = np.maximum(ref - G["day"], 0).astype(float)
    wday = 0.5 ** (age / hl) if hl < 1e8 else np.ones(n_all)
    tp = fit_tempo(tab, m, prior, wday)
    poss = G["poss"].copy()
    miss = ~np.isfinite(poss)
    if miss.any():
        poss[miss] = (tp["P"] + tp["p"][G["h"][miss]] + tp["p"][G["a"][miss]]) * (40.0 + 5.0 * G["ot"][miss]) / 40.0
    L0 = float(prior["L"])
    o_pr = np.asarray(prior["off"], float) - L0
    d_pr = np.asarray(prior["def"], float) - L0
    lam = lam0 * np.asarray(prior.get("lam", np.ones(T)), float)
    npar = 2 + 2 * T
    hi, ai = G["h"][m], G["a"][m]
    pm_ = poss[m]
    w = wday[m] * pm_ / (pm_.mean() if len(pm_) else 1.0)
    hn = np.where(G["neutral"][m], 0.0, 0.5)
    n = len(hi)
    z = np.zeros(n, int)
    cols = np.concatenate([np.stack([z, z + 1, 2 + hi, 2 + T + ai], 1), np.stack([z, z + 1, 2 + ai, 2 + T + hi], 1)])
    vals = np.concatenate([np.stack([np.ones(n), hn, np.ones(n), np.ones(n)], 1),
                           np.stack([np.ones(n), -hn, np.ones(n), np.ones(n)], 1)])
    yh, ya = 100 * G["hs"][m] / pm_, 100 * G["as"][m] / pm_
    dmp = DAMP.get(lv)
    if dmp:
        c_, sl = dmp
        mm = yh - ya
        am = np.abs(mm)
        mm2 = np.sign(mm) * (np.minimum(am, c_) + sl * np.maximum(am - c_, 0.0))
        mid = (yh + ya) / 2
        yh, ya = mid + mm2 / 2, mid - mm2 / 2
    y = np.concatenate([yh, ya])
    ww = np.concatenate([w, w])
    H, b = _normal(npar, cols, vals, ww, y)
    H[2:2 + T, 2:2 + T] += np.diag(lam)
    H[2 + T:, 2 + T:] += np.diag(lam)
    b[2:2 + T] += lam * o_pr
    b[2 + T:] += lam * d_pr
    H[0, 0] += 1e-3
    b[0] += 1e-3 * L0
    h0 = float(prior.get("hca", HCA0[lv]))
    H[1, 1] += 0.5
    b[1] += 0.5 * h0
    try:
        cf = sla.cho_factor(H)
        sol = sla.cho_solve(cf, b)
    except (sla.LinAlgError, ValueError):
        cf = None
        sol = np.linalg.lstsq(H, b, rcond=None)[0]
    mu, h = sol[0], sol[1]
    o, d = sol[2:2 + T], sol[2 + T:]
    mem = tab["member"]
    om, dm = o[mem].mean(), d[mem].mean()
    L = mu + om + dm
    off = L + o - om
    de = L + d - dm
    resid = y - (vals * sol[cols]).sum(1)
    s2 = float(np.sum(ww * resid ** 2) / max(1.0, ww.sum() - npar * 0.5)) if n else 120.0
    games = np.bincount(np.concatenate([hi, ai]), minlength=T)
    out = {"off": off, "def": de, "net": off - de, "tempo": tp["tempo"], "games": games, "L": float(L),
           "league_pace": tp["league_pace"], "hca": float(h), "hca_pts": float(h * tp["league_pace"] / 100.0),
           "resid_sd": math.sqrt(s2), "n": int(n), "ref_day": ref}
    if want_se:
        try:
            Hi = sla.cho_solve(cf, np.eye(npar)) if cf is not None else np.linalg.pinv(H)
        except (sla.LinAlgError, ValueError):
            Hi = np.linalg.pinv(H)
        # var(o_i - d_i) (centring ignored: the mean of ~365 teams is nearly fixed)
        io, idd = np.arange(T) + 2, np.arange(T) + 2 + T
        var = (Hi[io, io] + Hi[idd, idd] - 2 * Hi[io, idd]) * s2
        out["se"] = np.sqrt(np.maximum(var, 1e-6))
    return out


def as_prior(fitres: dict, tab: dict, se: np.ndarray | None = None, lam: float = 1.0) -> dict:
    """A fit result used as the prior of a later fit on the same season table (e.g. the live season)."""
    T = tab["T"]
    return {"off": fitres["off"], "def": fitres["def"], "pace": fitres["tempo"], "lam": np.full(T, lam),
            "se": se if se is not None else fitres.get("se", np.full(T, 5.0)), "L": fitres["L"],
            "P": fitres["league_pace"] - 0.0, "hca": fitres["hca"], "source": "fit"}


# ── season end ratings and the carryover fit ────────────────────────────────

def end_ratings(tab: dict, level: str) -> dict | None:
    """Full-season ratings (no recency decay, light ridge toward zero) as a team dict, or None (< 300 games)."""
    if len(tab["g"]["day"]) < 300:
        return None
    pr = empty_prior(tab, level)
    pr["lam"] = np.full(tab["T"], 0.5)
    f = fit(tab, None, pr, half_life=1e9, ridge=2.0, want_se=False)
    teams = {}
    for i, t in enumerate(tab["teams"]):
        teams[t] = {"off": float(f["off"][i]), "def": float(f["def"][i]), "net": float(f["net"][i]),
                    "tempo": float(f["tempo"][i]), "games": int(f["games"][i]), "conf": tab["conf"][i]}
    return {"teams": teams, "L": f["L"], "league_pace": f["league_pace"], "hca": f["hca"]}


def _conf_means(end: dict, conf_of: dict[str, str | None]) -> dict[str, float]:
    acc: dict[str, list[float]] = {}
    for t, c in conf_of.items():
        u = end["teams"].get(t)
        if c and u and t != D.ND1:
            acc.setdefault(c, []).append(u["net"])
    return {c: float(np.mean(v)) for c, v in acc.items() if v}


def carry_pairs(prev_end: dict, cur_end: dict, conf_cur: dict[str, str | None]) -> dict:
    """Rows for the carryover fit: x1 last net, x2 conference mean last season (this season's conference), y net;
    new members' y; tempo pairs."""
    cm = _conf_means(prev_end, conf_cur)
    rows, new, pace = [], [], []
    for t, v in cur_end["teams"].items():
        if t == D.ND1 or v["games"] < 15:
            continue
        u = prev_end["teams"].get(t)
        c = conf_cur.get(t)
        if u and u["games"] >= 15:
            rows.append([u["net"], cm.get(c, 0.0), v["net"]])
            pace.append([u["tempo"] - prev_end["league_pace"], v["tempo"] - cur_end["league_pace"]])
        else:
            new.append(v["net"])
    return {"rows": rows, "new": new, "pace": pace,
            "nd1": [prev_end["teams"].get(D.ND1, {}).get("net"), cur_end["teams"].get(D.ND1, {}).get("net")]}


def fit_carry(pairs: list[dict]) -> dict:
    rows = [r for p in pairs for r in p["rows"]]
    res = {"b1": 0.7, "b2": 0.2, "c": 0.0, "se": 6.0, "new": -10.0, "b_pace": 0.6, "nd1_delta": 0.0,
           "pairs": len(rows), "fitted": False}
    if len(rows) >= 200:
        A = np.array(rows, float)
        X = np.column_stack([A[:, 0], A[:, 1], np.ones(len(A))])
        beta, *_ = np.linalg.lstsq(X, A[:, 2], rcond=None)
        r = A[:, 2] - X @ beta
        res.update({"b1": float(beta[0]), "b2": float(beta[1]), "c": float(beta[2]),
                    "se": float(np.sqrt(np.mean(r ** 2))), "fitted": True})
        pc = np.array([q for p in pairs for q in p["pace"]], float)
        if len(pc) > 50 and (pc[:, 0] @ pc[:, 0]) > 0:
            res["b_pace"] = float(pc[:, 0] @ pc[:, 1] / (pc[:, 0] @ pc[:, 0]))
    nw = [x for p in pairs for x in p["new"]]
    if len(nw) >= 5:
        res["new"] = float(np.mean(nw))
    return res


def prior_for(tab: dict, level: str, prev_end: dict | None, coef: dict, roster_adj: dict[str, float] | None = None) -> dict:
    """Preseason prior arrays over tab["teams"] (module docstring). `roster_adj` ({tid: points per 100}) is added
    to the regressed rating when given (returning production, see players.returning_adjustment)."""
    if prev_end is None:
        return empty_prior(tab, level)
    T = tab["T"]
    L, P = float(prev_end["L"]), float(prev_end["league_pace"])
    conf_cur = {t: tab["conf"][i] for i, t in enumerate(tab["teams"])}
    cm = _conf_means(prev_end, conf_cur)
    b1, b2, c = coef["b1"], coef["b2"], coef["c"]
    off, de, pace, lam, se = (np.zeros(T) for _ in range(5))
    for i, t in enumerate(tab["teams"]):
        u = prev_end["teams"].get(t)
        if t == D.ND1:
            net = float(u["net"]) if u else -15.0
            off[i], de[i], pace[i], lam[i], se[i] = L + net / 2, L - net / 2, P, 1.0, 4.0
            continue
        if u and u["games"] >= 10:
            net = b1 * u["net"] + b2 * cm.get(tab["conf"][i], 0.0) + c
            od, dd = b1 * (u["off"] - prev_end["L"]), b1 * (u["def"] - prev_end["L"])
            shift = net - (od - dd)
            off[i], de[i] = L + od + shift / 2, L + dd - shift / 2
            pace[i] = P + coef["b_pace"] * (u["tempo"] - P)
            lam[i], se[i] = 1.0, coef["se"]
        else:
            net = coef["new"]
            off[i], de[i], pace[i], lam[i], se[i] = L + net / 2, L - net / 2, P, 0.5, coef["se"] * 1.3
        if roster_adj and t in roster_adj:
            a = float(roster_adj[t])
            off[i] += a / 2
            de[i] -= a / 2
    return {"off": off, "def": de, "pace": pace, "lam": lam, "se": se, "L": L, "P": P,
            "hca": float(prev_end.get("hca", HCA0[level])), "source": "last_season", "coef": coef}


# ── walk-forward (no peeking) ───────────────────────────────────────────────

def walk(tab: dict, prior: dict, half_life: float | None = None, ridge: float | None = None,
         snap_every: int = 7) -> dict:
    """Pregame ratings for every finished game, each from games on earlier days only (refit every game day).
    {"net_h","net_a","off_h","off_a","def_h","def_a","tempo_h","tempo_a","L","P","hca","n_prior": games before,
     "snaps": [[day, net[T]]] (every `snap_every` days), "pend": the latest fit (for scheduled games)}."""
    G = tab["g"]
    n = len(G["day"])
    keys = ("net_h", "net_a", "off_h", "off_a", "def_h", "def_a", "tempo_h", "tempo_a", "L", "P", "hca", "se_h", "se_a")
    out = {k: np.full(n, np.nan) for k in keys}
    out["nprior_h"] = np.zeros(n)
    out["nprior_a"] = np.zeros(n)
    snaps = []
    days = np.unique(G["day"]) if n else np.zeros(0, int)
    last_snap = None
    f = None
    se_pr = np.asarray(prior["se"], float)
    for d in days:
        m = G["day"] < d
        f = fit(tab, m, prior, ref_day=int(d) - 1, half_life=half_life, ridge=ridge)
        sel = G["day"] == d
        h, a = G["h"][sel], G["a"][sel]
        out["net_h"][sel], out["net_a"][sel] = f["net"][h], f["net"][a]
        out["off_h"][sel], out["off_a"][sel] = f["off"][h], f["off"][a]
        out["def_h"][sel], out["def_a"][sel] = f["def"][h], f["def"][a]
        out["tempo_h"][sel], out["tempo_a"][sel] = f["tempo"][h], f["tempo"][a]
        out["L"][sel], out["P"][sel], out["hca"][sel] = f["L"], f["league_pace"], f["hca"]
        gp = f["games"]
        out["nprior_h"][sel], out["nprior_a"][sel] = gp[h], gp[a]
        # approximate se: the prior's, shrinking with games played (one game ~ sd 15 per 100 on the margin)
        se_now = 1.0 / np.sqrt(1.0 / se_pr ** 2 + gp / 225.0)
        out["se_h"][sel], out["se_a"][sel] = se_now[h], se_now[a]
        if last_snap is None or d - last_snap >= snap_every:
            snaps.append([int(d), np.round(f["net"], 2).tolist()])
            last_snap = d
    out["snaps"] = snaps
    return out


# ── Kalman paths ────────────────────────────────────────────────────────────

def paths(tab: dict, prior: dict, hca: float, q_per_day: float | None = None, r: float | None = None) -> dict:
    """{"days": [day...], "net": array (len(days), T)}: filtered ratings at the end of each game day."""
    G, T = tab["g"], tab["T"]
    q = float(q_per_day if q_per_day is not None else Q_PER_DAY[tab["level"]])
    m = np.asarray(prior["net"] if "net" in prior else np.asarray(prior["off"]) - np.asarray(prior["def"]), float).copy()
    Pm = np.diag(np.asarray(prior["se"], float) ** 2)
    poss = G["poss"].copy()
    miss = ~np.isfinite(poss)
    if miss.any():
        poss[miss] = float(np.nanmean(poss)) if np.isfinite(poss).any() else D.DEFAULT_PACE[tab["level"]]
    yv = 100 * (G["hs"] - G["as"]) / poss - np.where(G["neutral"], 0.0, hca)
    if r is None:
        r = float(np.var(yv)) * 0.75 if len(yv) > 50 else 250.0
    days_out, nets = [], []
    last = None
    n = len(yv)
    for k in range(n):
        d = G["day"][k]
        if last is not None and d != last:
            days_out.append(int(last))
            nets.append(m.copy())
            Pm[np.diag_indices(T)] += q * min(d - last, 30)
        last = d
        i, j = G["h"][k], G["a"][k]
        Ph = Pm[:, i] - Pm[:, j]
        S = Ph[i] - Ph[j] + r
        K = Ph / S
        m += K * (yv[k] - (m[i] - m[j]))
        Pm -= np.outer(K, Ph)
    if last is not None:
        days_out.append(int(last))
        nets.append(m.copy())
    return {"days": days_out, "net": np.array(nets) if nets else np.zeros((0, T))}
