"""
Game model: a predictive blend of the walk-forward ratings, and an Elo baseline.

    margin_home = b_home * home + b_pts * d_pts + b_epa * d_epa + b_sr * d_sr + b_rest * d_rest
    d_pts = net points rating (off + def) home - away;  d_epa / d_sr = net EPA/play and success-rate ratings
    d_rest = days since each team's last game (capped 14), home - away
    total = a + c * (points-model expected points of both teams)
    p_home = Phi(margin / sd), sd by phase (weeks 1-3 / later / postseason) from the residuals

The blend weights, the totals line and the sd are fitted by least squares on the walk-forward pregame rows of
EARLIER seasons only (the backtest refits them before every season), so no weight has seen the season it
predicts. Seasons (or games) without play-by-play ratings use the points-only blend fitted the same way.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

FEATS_FULL = ["is_home", "d_pts", "d_epa", "d_sr", "d_rest"]
FEATS_PTS = ["is_home", "d_pts", "d_rest"]
RIDGE_EFF = 0.05
DEFAULT_BLEND = {"full": None, "pts": {"coef": [2.5, 1.0, 0.0], "n": 0}, "total": {"a": 0.0, "c": 1.0, "n": 0},
                 "sd": {"early": 16.5, "mid": 15.5, "post": 15.5}, "seasons": []}


def features(pre: pd.DataFrame, gf: pd.DataFrame) -> pd.DataFrame:
    """Join pregame ratings to the game frame and build the blend features."""
    m = gf.merge(pre, on="gid", how="inner")
    m["is_home"] = np.where(m["neutral"].to_numpy(bool), 0.0, 1.0)
    m["d_pts"] = (m["pts_off_h"] + m["pts_def_h"]) - (m["pts_off_a"] + m["pts_def_a"])
    m["pts_total"] = 2 * m["pts_mu"] + m["pts_off_h"] - m["pts_def_a"] + m["pts_off_a"] - m["pts_def_h"]
    m["pts_hfa_term"] = m["is_home"] * m["pts_hfa"]
    if "epa_off_h" in m:
        m["d_epa"] = (m["epa_off_h"] + m["epa_def_h"]) - (m["epa_off_a"] + m["epa_def_a"])
        m["d_sr"] = (m["sr_off_h"] + m["sr_def_h"]) - (m["sr_off_a"] + m["sr_def_a"])
    else:
        m["d_epa"] = np.nan
        m["d_sr"] = np.nan
    m["d_rest"] = rest_diff(gf).reindex(m["gid"]).to_numpy() if len(m) else np.zeros(0)
    return m


def rest_diff(gf: pd.DataFrame) -> pd.Series:
    """Days since each team's previous game (capped at 14; 14 for a season opener), home minus away, by gid."""
    g = gf.sort_values("date")
    last: dict[str, float] = {}
    out = {}
    for r in g.itertuples(index=False):
        d = pd.Timestamp(r.day).toordinal() if r.day else None
        rh = min(d - last[r.home], 14) if (d is not None and r.home in last) else 14
        ra = min(d - last[r.away], 14) if (d is not None and r.away in last) else 14
        out[r.gid] = float(rh - ra)
        if d is not None:
            last[r.home] = d
            last[r.away] = d
    return pd.Series(out, dtype=float)


def phase(week, stype) -> str:
    if stype in ("bowl", "cfp"):
        return "post"
    try:
        return "early" if int(week) <= 3 else "mid"
    except (TypeError, ValueError):
        return "mid"


def _ols(X: np.ndarray, y: np.ndarray, ridge: float = 1e-6) -> np.ndarray:
    A = X.T @ X + ridge * np.eye(X.shape[1])
    return np.linalg.solve(A, X.T @ y)


def fit_blend(rows: pd.DataFrame) -> dict:
    """Blend weights from walk-forward rows of finished games involving an FBS team (earlier seasons)."""
    b = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_BLEND.items()}
    if rows is None or not len(rows):
        return b
    r = rows[rows["final"] & (rows["h_member"] | rows["a_member"])].copy()
    r = r[np.isfinite(r["d_pts"])]
    if len(r) < 100:
        return b
    r["margin"] = r["hs"] - r["as"]
    r["tot"] = r["hs"] + r["as"]
    Xp = r[FEATS_PTS].fillna(0).to_numpy(float)
    cp = _ols(Xp, r["margin"].to_numpy(float))
    b["pts"] = {"coef": [round(float(c), 4) for c in cp], "n": len(r)}
    full = r[np.isfinite(r["d_epa"]) & np.isfinite(r["d_sr"])]
    if len(full) >= 100:
        Xf = full[FEATS_FULL].fillna(0).to_numpy(float)
        # ridge on the EPA / success columns (scaled to their spread): they are collinear with the points rating
        sc = Xf.std(axis=0)
        pen = np.zeros(Xf.shape[1])
        pen[2], pen[3] = RIDGE_EFF * len(full) * sc[2] ** 2, RIDGE_EFF * len(full) * sc[3] ** 2
        cf = np.linalg.solve(Xf.T @ Xf + np.diag(pen) + 1e-6 * np.eye(Xf.shape[1]), Xf.T @ full["margin"].to_numpy(float))
        b["full"] = {"coef": [round(float(c), 4) for c in cf], "n": len(full)}
    Xt = np.column_stack([np.ones(len(r)), r["pts_total"].to_numpy(float)])
    ct = _ols(Xt, r["tot"].to_numpy(float))
    b["total"] = {"a": round(float(ct[0]), 3), "c": round(float(ct[1]), 4), "n": len(r)}
    pred = predict_margin(r, b)
    res = r["margin"].to_numpy(float) - pred
    ph = np.array([phase(w, s) for w, s in zip(r["week"], r["stype"])])
    sd = {}
    for k in ("early", "mid", "post"):
        m = ph == k
        sd[k] = round(float(np.sqrt(np.mean(res[m] ** 2))), 3) if m.sum() >= 50 else DEFAULT_BLEND["sd"][k]
    b["sd"] = sd
    b["seasons"] = sorted(int(x) for x in r["season"].unique())
    return b


def predict_margin(m: pd.DataFrame, b: dict) -> np.ndarray:
    cp = np.asarray(b["pts"]["coef"])
    out = m[FEATS_PTS].fillna(0).to_numpy(float) @ cp
    if b.get("full"):
        cf = np.asarray(b["full"]["coef"])
        ok = np.isfinite(m["d_epa"].to_numpy(float)) & np.isfinite(m["d_sr"].to_numpy(float))
        if ok.any():
            out = np.where(ok, m[FEATS_FULL].fillna(0).to_numpy(float) @ cf, out)
    return out


def predict_frame(m: pd.DataFrame, b: dict) -> pd.DataFrame:
    """margin, sd, p_home, total, spread_fair per row of a features frame."""
    margin = predict_margin(m, b)
    sd = np.array([b["sd"].get(phase(w, s), 15.5) for w, s in zip(m["week"], m["stype"])])
    tot = b["total"]["a"] + b["total"]["c"] * m["pts_total"].to_numpy(float)
    out = pd.DataFrame({"gid": m["gid"].to_numpy(), "margin": margin, "sd": sd,
                        "p_home": norm.cdf(margin / sd), "total": tot})
    out["spread_fair"] = -out["margin"]
    return out


def predict(home: str, away: str, date, ctx: dict) -> dict:
    """CONTRACT.md 2: predict(home, away, date, ctx) -> {"p_home","margin","sd","total","spread_fair","detail"}.
    ctx: {"ratings": {kind: {"off","def","mu","hfa"}} (ratings as of `date`), "blend": fit_blend output,
    "neutral": bool, "rest_diff": days (home - away), "week": int|None, "stype": str}."""
    out = predict_ratings(home, away, ctx["ratings"], ctx.get("blend") or DEFAULT_BLEND, neutral=bool(ctx.get("neutral")),
                          rest_diff_days=float(ctx.get("rest_diff") or 0.0), week=ctx.get("week"), stype=ctx.get("stype") or "reg")
    out["detail"]["date"] = str(date)[:10] if date else None
    return out


def predict_ratings(home: str, away: str, ratings: dict, b: dict, *, neutral: bool = False, rest_diff_days: float = 0.0,
                    week=None, stype: str = "reg") -> dict:
    """{"p_home","margin","sd","total","spread_fair","detail"} from current ratings
    (ratings[kind] = {"off": {t: v}, "def": {...}, "mu", "hfa"})."""
    def net(k, t):
        r = ratings.get(k) or {}
        o, d = (r.get("off") or {}).get(t), (r.get("def") or {}).get(t)
        return None if o is None or d is None else o + d
    hp, ap = net("pts", home), net("pts", away)
    if hp is None or ap is None:
        return {"p_home": None, "margin": None, "sd": None, "total": None, "spread_fair": None, "detail": {}}
    row = {"is_home": 0.0 if neutral else 1.0, "d_pts": hp - ap, "d_rest": float(rest_diff_days), "week": week, "stype": stype}
    he, ae, hs_, as_ = net("epa", home), net("epa", away), net("sr", home), net("sr", away)
    row["d_epa"] = (he - ae) if he is not None and ae is not None else np.nan
    row["d_sr"] = (hs_ - as_) if hs_ is not None and as_ is not None else np.nan
    p = ratings["pts"]
    row["pts_total"] = 2 * p["mu"] + p["off"][home] - p["def"][away] + p["off"][away] - p["def"][home]
    m = pd.DataFrame([row])
    m["gid"] = "x"
    f = predict_frame(m, b).iloc[0]
    return {"p_home": round(float(f["p_home"]), 4), "margin": round(float(f["margin"]), 2), "sd": round(float(f["sd"]), 2),
            "total": round(float(f["total"]), 1), "spread_fair": round(float(f["spread_fair"]), 1),
            "detail": {"d_pts": round(row["d_pts"], 2),
                       "d_epa": None if not np.isfinite(row["d_epa"]) else round(float(row["d_epa"]), 4),
                       "d_sr": None if not np.isfinite(row["d_sr"]) else round(float(row["d_sr"]), 4),
                       "home": row["is_home"], "rest": row["d_rest"],
                       "model": "full" if (b.get("full") and np.isfinite(row["d_epa"])) else "points"}}


# ── Elo baseline ────────────────────────────────────────────────────────────

ELO_K = 25.0
ELO_HFA = 65.0
ELO_FCS = 1250.0
ELO_REGRESS = 0.35


def elo_run(seasons_frames: list[pd.DataFrame], conf_maps: list[dict]) -> pd.DataFrame:
    """Margin-of-victory Elo across seasons (pregame p_home and margin per gid). Between seasons ratings regress
    a third of the way to the mean of the team's conference (FCS teams to 1250)."""
    elo: dict[str, float] = {}
    out = []
    for gf, (conf, member) in zip(seasons_frames, conf_maps):
        if elo:
            by_c: dict = {}
            for t, v in elo.items():
                if member.get(t):
                    by_c.setdefault(conf.get(t), []).append(v)
            cm = {c: float(np.mean(v)) for c, v in by_c.items()}
            for t in list(elo):
                target = cm.get(conf.get(t), 1500.0) if member.get(t) else ELO_FCS
                elo[t] = elo[t] + ELO_REGRESS * (target - elo[t])
        g = gf.sort_values("date")
        for gid, h, a, hm, am, neu, fin, hs, as_ in zip(g["gid"], g["home"], g["away"], g["h_member"], g["a_member"],
                                                       g["neutral"], g["final"], g["hs"], g["as"]):
            eh = elo.get(h, 1500.0 if hm else ELO_FCS)
            ea = elo.get(a, 1500.0 if am else ELO_FCS)
            dr = eh - ea + (0.0 if neu else ELO_HFA)
            p = 1.0 / (1.0 + 10 ** (-dr / 400.0))
            out.append((gid, p, dr / 28.0))
            if fin:
                mv = float(hs) - float(as_)
                y = 1.0 if mv > 0 else (0.5 if mv == 0 else 0.0)
                mult = math.log(abs(mv) + 1.0) * (2.2 / ((dr if mv > 0 else -dr) * 0.001 + 2.2))
                d = ELO_K * mult * (y - p)
                elo[h] = eh + d
                elo[a] = ea - d
    return pd.DataFrame(out, columns=["gid", "elo_p_home", "elo_margin"])
