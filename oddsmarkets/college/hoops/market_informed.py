"""
The market-informed game model for college basketball (round 4, 22 Oct 2026; docs/research/college_edge.md).

    mk  = h [not neutral] + r_home - r_away       market ratings from the closing spreads of games on earlier days
                                                  (half-life 60 days, ridge 0.25, prior 0.7 x last season's final)
    rd  = h' [not neutral] + d_home - d_away      residual ratings: the same ridge on (line - base model margin)
                                                  (half-life 60 days, ridge 4, carry 0.5)
    margin = c + b . [nn, m0, mk, rd]             fitted to closing spreads of seasons 2013 .. S-1
    P(home) = Phi((margin + c0) / sd_phase)       probit on the last two seasons' walk-forward predictions

Men's basketball only, and **on trial** (`fitted/informed_mbb.json`, status "trial"): on the sealed 2021-2026 test it
cut log-loss by 0.0071 [-0.0085, -0.0057] and closed 73 % of the gap to the de-vigged moneyline, but its calibration
slope (0.94) missed the pre-registered tolerance. The recalibrated version (two-season probit, chosen on dev) is being
tested forward on 2026-27; until it passes the site shows it beside the published model, never in its place.
Women's basketball: no gain on the test seasons (the base model already beats the thin women's lines), not used.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from oddsmarkets.college import informed as INF
from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import model as M

logger = logging.getLogger(__name__)
POST = ("ncaa", "nit", "wbit", "post")


def fit_for(level: str, season: int) -> dict | None:
    f = INF.load_fit(level)
    if not f or not f.get("coefs") or int(f.get("season") or -1) != int(season):
        return None
    return f


def season_frame(state: dict, season: int, fitres: dict | None = None) -> pd.DataFrame:
    """One season's rows (finished games with their walk-forward base prediction, scheduled games with the current
    ratings), in the research frame's columns (scripts/campus_r4.py rows_hoops)."""
    tab = state["tabs"][season]
    G, Pd = tab["g"], tab["pend"]
    teams = tab["teams"]
    conf = tab["conf"]
    pr = state["preds"][season]
    W = state["walks"][season]
    nd1 = len(teams) - 1
    rows = {"gid": [str(x) for x in G["gid"]], "dayn": list(np.asarray(G["day"], np.int64)), "h": list(G["h"]),
            "a": list(G["a"]), "neutral": list(np.asarray(G["neutral"], bool)), "stype": [str(x) for x in G["stype"]],
            "hs": list(G["hs"]), "as": list(G["as"]), "spread": list(G["spread"]), "m0": list(pr["mu"]),
            "p0": list(pr["p"]), "sd0": list(pr["sd"]), "final": [True] * len(G["gid"]),
            "nprior": list(np.minimum(W["nprior_h"], W["nprior_a"]))}
    if len(Pd.get("gid", [])):
        f = fitres
        prm = state["params"].get(season) or state["params"]["latest"]
        played = np.zeros(len(teams))
        for hi, ai in zip(G["h"], G["a"]):
            played[hi] += 1
            played[ai] += 1
        for gid, d, hi, ai, neu, stp in zip(Pd["gid"], Pd["day"], Pd["h"], Pd["a"], Pd["neutral"], Pd["stype"]):
            p = M.predict_one(f, int(hi), int(ai), bool(neu), prm, se=f.get("se")) if f is not None and hi != ai else None
            rows["gid"].append(str(gid))
            rows["dayn"].append(int(d))
            rows["h"].append(int(hi))
            rows["a"].append(int(ai))
            rows["neutral"].append(bool(neu))
            rows["stype"].append(str(stp))
            rows["hs"].append(np.nan)
            rows["as"].append(np.nan)
            rows["spread"].append(np.nan)
            rows["m0"].append(p["margin"] if p else np.nan)
            rows["p0"].append(p["p_home"] if p else np.nan)
            rows["sd0"].append(p["sd"] if p else np.nan)
            rows["final"].append(False)
            rows["nprior"].append(float(min(played[int(hi)], played[int(ai)])))
    F = pd.DataFrame(rows)
    F["season"] = int(season)
    F["home"] = [str(teams[i]) for i in F["h"]]
    F["away"] = [str(teams[i]) for i in F["a"]]
    F["conf_h"] = [str(conf[i]) for i in F["h"]]
    F["conf_a"] = [str(conf[i]) for i in F["a"]]
    F["group_h"] = "d1"
    F["group_a"] = "d1"
    F["fcs"] = False
    both = (F["h"] != nd1) & (F["a"] != nd1)
    F["y"] = F["hs"] - F["as"]
    F["scope"] = both & F["final"] & np.isfinite(F["m0"]) & (F["y"] != 0)
    F["fit_line"] = both & F["final"] & np.isfinite(F["spread"].astype(float))
    F["phase"] = np.where(F["stype"].isin(POST), "post", np.where(F["nprior"] < 5, "early", "mid"))
    return F.sort_values(["dayn", "gid"], kind="mergesort").reset_index(drop=True)


def predict(state: dict, level: str, season: int, fitres: dict | None = None) -> dict[str, dict]:
    """{gid: {"p_home", "margin", "mk", "rd", "base_margin", "base_p", "status"}} for the season's games, or {}."""
    fit = fit_for(level, season)
    if not fit or season not in state["tabs"]:
        return {}
    F = season_frame(state, season, fitres)
    if not len(F):
        return {}
    out = INF.predict_season(F, D.level_of(level), fit)
    res = {}
    for r, o in zip(F.itertuples(index=False), out.itertuples(index=False)):
        if not np.isfinite(o.mu) or r.h == r.a:
            continue
        res[str(r.gid)] = {"p_home": float(o.p), "margin": float(o.mu), "mk": float(getattr(o, "mk", np.nan)),
                           "rd": float(getattr(o, "rd", np.nan)), "base_margin": float(r.m0), "base_p": float(r.p0),
                           "status": fit.get("status") or "trial"}
    return res
