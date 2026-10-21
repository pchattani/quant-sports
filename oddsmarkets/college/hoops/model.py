"""
Level pipeline: season tables -> season-end ratings -> carryover (walk-forward) -> preseason priors -> walk-forward
pregame ratings for every game -> game-model parameters (walk-forward) -> pregame predictions.

Game model (per game, from the pregame ratings of both teams):

    pace_g = tempo_h + tempo_a - P                                   expected possessions
    x      = (rating_h - rating_a) * pace_g / 100                    rating gap in points
    margin = s * x + HCA * [not neutral]
    sd^2   = s0^2 + s1 * (se_h^2 + se_a^2) * (pace_g / 100)^2        wider while ratings are uncertain
    p_home = Phi(margin / sd)
    total  = t0 + t1 * (off_h + def_a + off_a + def_h - 2 L) * pace_g / 100

s, HCA by least squares (no intercept) of the margin on [x, 1(not neutral)]; s0, s1 by least squares of the squared
residual on [1, v]; t0, t1 by least squares of the total; all on games between two D-I members of EARLIER seasons
only (season S uses seasons < S; the first season uses DEFAULTS), so the backtest never sees its own results.
"""
from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import Any

import numpy as np
from scipy.stats import norm

from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import elo as E
from oddsmarkets.college.hoops import ratings as R

logger = logging.getLogger(__name__)
VERSION = 4
DEFAULTS = {"mbb": {"s": 1.0, "hca": 3.2, "s0": 10.8, "s1": 1.0, "t0": 0.0, "t1": 1.0, "ca": 1.0, "cb": 0.0},
            "wbb": {"s": 1.0, "hca": 3.2, "s0": 11.5, "s1": 1.0, "t0": 0.0, "t1": 1.0, "ca": 1.0, "cb": 0.0}}
WALK_KEYS = ("net_h", "net_a", "off_h", "off_a", "def_h", "def_a", "tempo_h", "tempo_a", "L", "P", "hca", "se_h", "se_a",
             "nprior_h", "nprior_a")


def _walk_cached(level: str, season: int, tab: dict, prior: dict, coef: dict, use_cache: bool) -> dict:
    def run():
        w = R.walk(tab, prior)
        out = {k: [None if not np.isfinite(x) else round(float(x), 4) for x in w[k]] for k in WALK_KEYS}
        out["snaps"] = w["snaps"]
        return out
    key = [VERSION, R.VERSION, level, season, D.content_sig(level, [season - 1, season]),
           {k: round(v, 4) if isinstance(v, float) else v for k, v in coef.items()}, R.HALF_LIFE[level], R.RIDGE[level],
           {k: round(v, 4) if isinstance(v, float) else v for k, v in (prior.get("roster_fit") or {}).items()},
           round(tab["k_poss"], 4)]
    if use_cache:
        res = D.cached(f"walk_{level}_{season}", key, run, "walk")
    else:
        res = run()
    out = {k: np.array([np.nan if x is None else x for x in res[k]], float) for k in WALK_KEYS}
    out["snaps"] = res["snaps"]
    return out


def features(tab: dict, w: dict) -> dict:
    G = tab["g"]
    pace = w["tempo_h"] + w["tempo_a"] - w["P"]
    x = (w["net_h"] - w["net_a"]) * pace / 100.0
    nn = (~G["neutral"]).astype(float)
    raw = (w["off_h"] + w["def_a"] + w["off_a"] + w["def_h"] - 2 * w["L"]) * pace / 100.0
    v = (w["se_h"] ** 2 + w["se_a"] ** 2) * (pace / 100.0) ** 2
    both = ~(G["nh"] | G["na"])
    return {"x": x, "nn": nn, "raw": raw, "v": v, "pace": pace, "both": both,
            "margin": G["hs"] - G["as"], "total": G["hs"] + G["as"]}


def fit_params(level: str, F: list[dict]) -> dict:
    p = dict(DEFAULTS[level])
    p["n"] = 0
    if not F:
        return p
    cat = {k: np.concatenate([f[k] for f in F]) for k in ("x", "nn", "raw", "v", "margin", "total", "both")}
    m = cat["both"] & np.isfinite(cat["x"])
    if m.sum() < 500:
        return p
    X = np.column_stack([cat["x"][m], cat["nn"][m]])
    y = cat["margin"][m]
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    r2 = (y - X @ b) ** 2
    V = np.column_stack([np.ones(m.sum()), cat["v"][m]])
    c, *_ = np.linalg.lstsq(V, r2, rcond=None)
    s0sq = max(float(c[0]), 25.0)
    s1 = float(np.clip(c[1], 0.0, 3.0))
    Tt = np.column_stack([np.ones(m.sum()), cat["raw"][m]])
    t, *_ = np.linalg.lstsq(Tt, cat["total"][m], rcond=None)
    p.update({"s": float(b[0]), "hca": float(b[1]), "s0": math.sqrt(s0sq), "s1": s1, "t0": float(t[0]),
              "t1": float(t[1]), "n": int(m.sum())})
    # a probit recalibration Phi(ca z + cb) fitted the same way did not help out of sample (log loss 0.5216 v
    # 0.5214 men, 19 Oct 2026), so ca = 1, cb = 0
    return p


def predict_arrays(f: dict, prm: dict) -> dict:
    mu = prm["s"] * f["x"] + prm["hca"] * f["nn"]
    sd = np.sqrt(prm["s0"] ** 2 + prm["s1"] * np.nan_to_num(f["v"], nan=0.0))
    p = norm.cdf(prm.get("ca", 1.0) * mu / sd + prm.get("cb", 0.0))
    total = prm["t0"] + prm["t1"] * f["raw"]
    return {"mu": mu, "sd": sd, "p": p, "total": total}


def predict_one(fitres: dict, i: int, j: int, neutral: bool, prm: dict, se: np.ndarray | None = None) -> dict:
    """Pregame prediction for team index i (home) v j from a ratings fit (arrays over a season table)."""
    P = fitres["league_pace"]
    pace = fitres["tempo"][i] + fitres["tempo"][j] - P
    x = (fitres["net"][i] - fitres["net"][j]) * pace / 100.0
    mu = prm["s"] * x + (0.0 if neutral else prm["hca"])
    v = 0.0
    if se is not None:
        v = (se[i] ** 2 + se[j] ** 2) * (pace / 100.0) ** 2
    sd = math.sqrt(prm["s0"] ** 2 + prm["s1"] * v)
    raw = (fitres["off"][i] + fitres["def"][j] + fitres["off"][j] + fitres["def"][i] - 2 * fitres["L"]) * pace / 100.0
    total = prm["t0"] + prm["t1"] * raw
    return {"p_home": float(norm.cdf(prm.get("ca", 1.0) * mu / sd + prm.get("cb", 0.0))), "margin": float(mu), "sd": float(sd), "total": float(total),
            "spread_fair": float(-mu), "pace": float(pace)}


def level_state(level: str, seasons: list[int] | None = None, use_cache: bool = True, log: bool = True) -> dict:
    """Everything the backtest, sims and payloads need for a level (module docstring).
    {"level","seasons","k_poss","tabs","ends","coef","priors","walks","feats","params","preds","elo"}"""
    lv = D.level_of(level)
    t0 = time.perf_counter()
    ss = sorted(seasons if seasons is not None else D.seasons(lv))
    kr = D.cached(f"poss_{lv}", [VERSION, D.content_sig(lv, ss)], lambda: D.poss_ratio(lv, ss), "fits") if use_cache \
        else D.poss_ratio(lv, ss)
    k_pooled = round(float(kr["pooled"]), 2)           # quantized: keeps the walk caches stable as box scores land
    tabs = {s: D.season_table(lv, s, k_poss=k_pooled) for s in ss}
    ends = {s: R.end_ratings(tabs[s], lv) for s in ss}
    pairs = {}
    for s in ss:
        if ends.get(s) and ends.get(s - 1):
            conf_cur = {t: tabs[s]["conf"][i] for i, t in enumerate(tabs[s]["teams"])}
            pairs[s] = R.carry_pairs(ends[s - 1], ends[s], conf_cur)
    coef, priors, walks, feats = {}, {}, {}, {}
    for s in ss:
        coef[s] = R.fit_carry([pairs[q] for q in pairs if q < s])
    rfeat = roster_features(lv, ss, tabs, ends, use_cache) if use_cache is not None else {}
    radj, rfit = roster_adjustments(lv, ss, tabs, ends, coef, rfeat)
    for s in ss:
        priors[s] = R.prior_for(tabs[s], lv, ends.get(s - 1), coef[s], roster_adj=radj.get(s))
        priors[s]["roster_fit"] = rfit.get(s)
        if rfit.get(s) and rfit[s]["sd_before"] > 0:
            ratio = min(1.0, rfit[s]["resid_sd"] / rfit[s]["sd_before"])
            mem = np.array([t != D.ND1 for t in tabs[s]["teams"]])
            priors[s]["se"] = np.where(mem, np.asarray(priors[s]["se"]) * ratio, priors[s]["se"])
        walks[s] = _walk_cached(lv, s, tabs[s], priors[s], coef[s], use_cache)
        feats[s] = features(tabs[s], walks[s])
    params, preds = {}, {}
    for s in ss:
        params[s] = fit_params(lv, [feats[q] for q in ss if q < s])
        preds[s] = predict_arrays(feats[s], params[s])
    params["latest"] = fit_params(lv, [feats[q] for q in ss])
    el = E.run(tabs)
    if log:
        logger.info("%s level state: %d seasons in %.1fs", lv, len(ss), time.perf_counter() - t0)
    return {"level": lv, "seasons": ss, "k_poss": kr, "tabs": tabs, "ends": ends, "coef": coef, "priors": priors,
            "roster_fit": rfit,
            "walks": walks, "feats": feats, "params": params, "preds": preds, "elo": el}


def roster_features(level: str, ss: list[int], tabs: dict, ends: dict, use_cache: bool = True) -> dict[int, dict]:
    """{season: {tid: {"ret","lost","prev","ret_min","prev_min"}}} for seasons whose previous season has box scores:
    last season's player values (players.season_players on last season's team ratings) mapped to this season's
    teams (this season's box-score team where the player has played, else this season's roster)."""
    from oddsmarkets.college.hoops import players as PL
    out = {}
    for s in ss:
        if s - 1 not in ss or not ends.get(s - 1):
            continue

        def run(s=s):
            st0 = D.load(level, s - 1)
            fin = sum(1 for g in (st0.get("games") or {}).values() if g.get("status") == "post")
            # a box with player rows on both sides (older stores carry empty box shells: no players, null team stats)
            boxed = sum(1 for g in (st0.get("games") or {}).values() if g.get("status") == "post"
                        and D.box_ok(g, rel=0.1) and all((v or {}).get("players") for v in g["box"].values()))
            if fin == 0 or boxed < 0.75 * fin:
                return None                                  # last season's box scores not (yet) complete
            br0 = PL.box_rows(level, s - 1, st0)
            e0 = ends[s - 1]["teams"]
            prev = PL.season_players(level, s - 1, {t: {"rating": v["net"], "tempo": v["tempo"]} for t, v in e0.items()}, br0)["rows"]
            st = D.load(level, s)
            br1 = PL.box_rows(level, s, st)
            cur = {}
            if len(br1["pid"]):
                mins = defaultdict(float)
                for p, t, x in zip(br1["pid"], br1["tid"], br1["X"][:, 0]):
                    mins[(p, t)] += x
                best = {}
                for (p, t), m in mins.items():
                    if m > best.get(p, (None, -1))[1]:
                        best[p] = (t, m)
                cur = {p: t for p, (t, m) in best.items()}
            if len(cur) < 1000:
                cur = {**PL.current_team_map(st, None), **cur}
            members = [t for t in tabs[s]["teams"] if t != D.ND1]
            return PL.returning_value(prev, cur, members)
        key = [VERSION, "roster-feat-4", level, s, D.content_sig(level, [s - 1, s])]
        res = D.cached(f"roster_{level}_{s}", key, run, "fits") if use_cache else run()
        if res:
            out[s] = res
    return out


def roster_adjustments(level: str, ss: list[int], tabs: dict, ends: dict, coef: dict, rfeat: dict) -> tuple[dict, dict]:
    """Walk-forward roster-turnover adjustment of the preseason prior: on earlier seasons, the residual of the
    season-end rating from the regressed-rating prior is regressed (ridge) on [returning value / 100, last season's
    team value / 100] (points above replacement of the players now on the team, and of the team's own players last
    season, split into the team's own returning players and incoming transfers since the two carry over differently); applied to season S only when at least 300 team-seasons before S exist. ({season: {tid: adj}},
    {season: fit})."""
    rows_by = {}
    for s in ss:
        f = rfeat.get(s)
        e1, e0 = ends.get(s), ends.get(s - 1)
        if not f or not e1 or not e0 or s not in coef:
            continue
        pr = R.prior_for(tabs[s], level, e0, coef[s])
        net_pr = np.asarray(pr["off"]) - np.asarray(pr["def"])
        rows = []
        for i, t in enumerate(tabs[s]["teams"]):
            if t == D.ND1 or t not in f or t not in e1["teams"] or e1["teams"][t]["games"] < 15:
                continue
            x = f[t]
            rows.append([_rs(x) / 100.0, x.get("ret_in", 0.0) / 100.0, x["prev"] / 100.0, e1["teams"][t]["net"] - net_pr[i]])
        rows_by[s] = rows
    adj, fits = {}, {}
    for s in ss:
        train = [r for q, rows in rows_by.items() if q < s for r in rows]
        f = rfeat.get(s)
        if len(train) < 300 or not f:
            continue
        A = np.array(train)
        X = np.column_stack([np.ones(len(A)), A[:, 0], A[:, 1], A[:, 2]])
        P = np.diag([0.0, 1.0, 1.0, 1.0])
        beta = np.linalg.solve(X.T @ X + P, X.T @ A[:, 3])
        resid = A[:, 3] - X @ beta
        fits[s] = {"b0": float(beta[0]), "b_same": float(beta[1]), "b_in": float(beta[2]), "b_prev": float(beta[3]),
                   "n": len(A), "resid_sd": float(np.sqrt(np.mean(resid ** 2))),
                   "sd_before": float(np.sqrt(np.mean(A[:, 3] ** 2)))}
        adj[s] = {t: float(beta[0] + beta[1] * _rs(x) / 100.0 + beta[2] * x.get("ret_in", 0.0) / 100.0
                           + beta[3] * x["prev"] / 100.0) for t, x in f.items()}
    return adj, fits


def _rs(x: dict) -> float:
    """Value of the team's own returning players (older caches: ret - ret_in)."""
    return x["ret_same"] if "ret_same" in x else x["ret"] - x.get("ret_in", 0.0)


def current_fit(state: dict, season: int, through_day: int | None = None, want_se: bool = True) -> dict:
    """Ratings of a season from its games on or before `through_day` (all when None), with the season's prior."""
    tab = state["tabs"][season]
    G = tab["g"]
    m = np.ones(len(G["day"]), bool) if through_day is None else G["day"] <= through_day
    pr = state["priors"][season]
    if not m.any():
        f = R.fit(tab, m, pr, ref_day=through_day, want_se=False)
        f["se"] = np.asarray(pr["se"], float)
        return f
    return R.fit(tab, m, pr, ref_day=through_day if through_day is not None else None, want_se=want_se)
