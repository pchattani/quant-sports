"""
NCAA tournament layer on a level state (model.level_state): pre-tournament ratings, the selection and seeding proxy
(leave-one-season-out accuracy), the actual bracket of past seasons, and the tournament-forecast backtest.

Tournament backtest (`tourney_backtest`): for every season with a tournament, ratings fitted on games before the
first tournament day (with the season prior), the ACTUAL bracket simulated (`n` runs, team strengths drawn from their
posterior N(rating, se)), P(reach each round) scored against what happened:
  round Brier   mean over field teams and the six rounds R32..Champion of (P(reach) - reached)^2
  champion LL   -log P(champion)
  game LL/Brier every tournament game (First Four included) from the same fixed pre-tournament ratings
against a seed-only baseline (P(i beats j) = Phi(c (seed_j - seed_i)), c fitted by maximum likelihood on the
tournament games of EARLIER seasons only; 0.13 before two seasons exist), simulated through the same bracket.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import norm

from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import model as M
from oddsmarkets.college.hoops import tourney as TT

EPS = 1e-4


def host_rule(level: str, season: int) -> bool:
    """Women's first and second rounds on the top-16 seeds' floors (2016 on, not the 2021 bubble)."""
    return level == "wbb" and season >= 2016 and season != 2021


def pretourney(state: dict, season: int) -> dict | None:
    st = D.load(state["level"], season)
    af = TT.actual_field(state["level"], season, st)
    if not af:
        return None
    tab = state["tabs"][season]
    d0 = D.local_day(af["first_day"]).toordinal()
    fit = M.current_fit(state, season, through_day=d0 - 1, want_se=True)
    res = TT.resume(tab, fit, d0)
    return {"af": af, "fit": fit, "res": res, "day": d0, "st": st}


def selection_rows(state: dict, pre: dict[int, dict]) -> dict[int, dict]:
    rows = {}
    for s, p in pre.items():
        if not p:
            continue
        tab, af = state["tabs"][s], p["af"]
        mem = np.where(tab["member"])[0]
        tids = [tab["teams"][i] for i in mem]
        in_field = np.array([t in af["teams"] for t in tids])
        auto = np.array([bool(af["teams"].get(t, {}).get("auto")) for t in tids])
        seed = np.array([af["teams"].get(t, {}).get("seed") or 0 for t in tids])
        X = TT.feature_matrix(p["res"], mem)
        has_seed = bool((seed[in_field] > 0).all()) and in_field.sum() >= 60
        rows[s] = {"X": X, "auto": auto, "in_field": in_field, "seed": np.where(in_field, seed, 0), "idx": mem,
                   "has_seed": has_seed, "n_field": int(in_field.sum()), "n_ff": max(0, int(in_field.sum()) - 64)}
    return rows


def fit_on(rows: dict[int, dict], seasons: list[int]) -> dict:
    use = [rows[s] for s in seasons if s in rows and rows[s]["has_seed"]]
    return TT.fit_selection(use)


def predict_season(model: dict, r: dict) -> dict:
    sel = TT.sel_score(model, r["X"])
    sd = TT.seed_score(model, r["X"])
    fld = TT.build_field(np.arange(len(r["X"])), r["auto"], sel, sd, r["n_field"], r["n_ff"])
    return {"sel": sel, "seedsc": sd, "field": fld}


def selection_loso(rows: dict[int, dict]) -> dict:
    """Leave-one-season-out at-large hit rate and seed MAE (seeds dealt in predicted order onto the season's actual
    seed multiset)."""
    out = []
    hits = n_at = 0
    errs = []
    for s, r in sorted(rows.items()):
        others = [q for q in rows if q != s]
        model = fit_on(rows, others)
        pr = predict_season(model, r)
        actual_at = set(np.where(r["in_field"] & ~r["auto"])[0].tolist())
        pred_at = set(pr["field"]["field"]) - set(np.where(r["auto"])[0].tolist())
        h = len(actual_at & pred_at)
        hits += h
        n_at += len(actual_at)
        row = {"season": s, "at_large": len(actual_at), "hit": h}
        if r["has_seed"]:
            fi = np.where(r["in_field"])[0]
            order = fi[np.argsort(pr["seedsc"][fi])]
            dealt = np.sort(r["seed"][fi])
            e = np.abs(dealt - r["seed"][order])
            errs.append(e)
            row.update({"seed_mae": round(float(e.mean()), 3), "exact": round(float((e == 0).mean()), 3)})
        out.append(row)
    e = np.concatenate(errs) if errs else np.zeros(0)
    return {"n_seasons": len(out), "at_large_acc": round(hits / max(n_at, 1), 4), "at_large_n": n_at,
            "seed_mae": round(float(e.mean()), 3) if len(e) else None,
            "seed_exact": round(float((e == 0).mean()), 3) if len(e) else None,
            "seed_within1": round(float((e <= 1).mean()), 3) if len(e) else None,
            "features": TT.FEATURES, "per_season": out}


# ── actual bracket ──────────────────────────────────────────────────────────

def actual_regions(af: dict, idx: dict[str, int]) -> tuple[list[dict[int, list[int]]], np.ndarray]:
    """Regions in bracket order as {seed: [team index] or [a, b] (First Four)} and seeds per team index."""
    teams = af["teams"]
    for a, b, w in af["first_four"]:
        for x, y in ((a, b), (b, a)):
            if not teams[x].get("region"):
                teams[x]["region"] = teams[y].get("region")
            if not teams[x].get("seed"):
                teams[x]["seed"] = teams[y].get("seed")
    regs = [dict() for _ in af["regions"]]
    ri = {r: k for k, r in enumerate(af["regions"])}
    for t, v in teams.items():
        if v.get("region") not in ri or not v.get("seed") or t not in idx:
            continue
        regs[ri[v["region"]]].setdefault(int(v["seed"]), []).append(idx[t])
    seeds = np.full(max(idx.values()) + 1, 99)
    for t, v in teams.items():
        if t in idx and v.get("seed"):
            seeds[idx[t]] = int(v["seed"])
    return regs, seeds


def _seed_c(games: list[tuple[int, int, int]]) -> float:
    """MLE c of P(a beats b) = Phi(c (seed_b - seed_a)) over (seed_a, seed_b, a_won)."""
    if len(games) < 100:
        return 0.13
    g = np.array(games, float)
    d = g[:, 1] - g[:, 0]
    y = g[:, 2]

    def nll(c):
        p = np.clip(norm.cdf(c * d), EPS, 1 - EPS)
        return -np.sum(y * np.log(p) + (1 - y) * np.log(1 - p))
    return float(minimize_scalar(nll, bounds=(0.01, 1.0), method="bounded").x)


def tourney_backtest(state: dict, pre: dict[int, dict], n: int = 4000, seed: int = 7) -> dict:
    lv = state["level"]
    rng = np.random.default_rng(seed)
    per = []
    hist_games: list[tuple[int, int, int]] = []
    agg = {k: [] for k in ("brier_model", "brier_seed", "ll_model", "ll_seed", "gb_model", "gb_seed", "champ_model", "champ_seed")}
    for s in sorted(pre):
        p = pre[s]
        if not p:
            continue
        tab, af, fit = state["tabs"][s], p["af"], p["fit"]
        idx = tab["idx"]
        regs, seeds_of = actual_regions(af, idx)
        if len(regs) != 4 or any(len(r) < 14 for r in regs):
            continue
        prm = state["params"][s]
        pos, ff = TT.bracket_arrays(regs)
        T = tab["T"]
        strength = fit["net"][None, :] + fit["se"][None, :] * rng.standard_normal((n, T))
        host = host_rule(lv, s)
        sim = TT.sim_bracket(pos, ff, strength, fit["tempo"], fit["league_pace"], prm, rng, seeds_of=seeds_of, host_hca=host)
        c = _seed_c(hist_games)
        sstr = np.broadcast_to(-c * seeds_of.astype(float), (n, T)).copy()
        sprm = {"s": 1.0, "s0": 1.0, "hca": 0.0}
        ssim = TT.sim_bracket(pos, ff, sstr, np.full(T, 50.0), 0.0, sprm, rng)
        field = [idx[t] for t in af["teams"] if t in idx]
        reached = np.zeros((len(field), 6))
        for k, t in enumerate(field):
            w = af["teams"][tab["teams"][t]]["wins"]
            reached[k, :min(w, 6)] = 1
        pm = sim["reach"][field, 1:] / n
        ps = ssim["reach"][field, 1:] / n
        bm, bs = float(np.mean((pm - reached) ** 2)), float(np.mean((ps - reached) ** 2))
        ch = idx.get(af["champion"])
        cm = -math.log(max(sim["reach"][ch, 6] / n, 1e-4)) if ch is not None else None
        cs = -math.log(max(ssim["reach"][ch, 6] / n, 1e-4)) if ch is not None else None
        # game level
        G = tab["g"]
        mt = G["stype"] == "ncaa"
        pg, pgs, yg = [], [], []
        for k in np.where(mt)[0]:
            i, j = G["h"][k], G["a"][k]
            home = 0.0
            if host and seeds_of[i] <= 4 and not G["neutral"][k]:
                home = 1.0
            elif host and seeds_of[j] <= 4 and not G["neutral"][k]:
                home = -1.0
            pace = fit["tempo"][i] + fit["tempo"][j] - fit["league_pace"]
            mu = prm["s"] * (fit["net"][i] - fit["net"][j]) * pace / 100.0 + prm["hca"] * home
            sd = math.sqrt(prm["s0"] ** 2 + prm["s1"] * (fit["se"][i] ** 2 + fit["se"][j] ** 2) * (pace / 100) ** 2)
            pg.append(norm.cdf(mu / sd))
            pgs.append(norm.cdf(c * (seeds_of[j] - seeds_of[i])) if seeds_of[i] < 99 and seeds_of[j] < 99 else 0.5)
            yg.append(1.0 if G["hs"][k] > G["as"][k] else 0.0)
            if seeds_of[i] < 99 and seeds_of[j] < 99:
                hist_games.append((int(seeds_of[i]), int(seeds_of[j]), int(yg[-1])))
        pg, pgs, yg = np.clip(np.array(pg), EPS, 1 - EPS), np.clip(np.array(pgs), EPS, 1 - EPS), np.array(yg)
        llm = float(-np.mean(yg * np.log(pg) + (1 - yg) * np.log(1 - pg)))
        lls = float(-np.mean(yg * np.log(pgs) + (1 - yg) * np.log(1 - pgs)))
        row = {"season": s, "n_games": int(len(yg)), "round_brier": round(bm, 5), "round_brier_seed": round(bs, 5),
               "game_ll": round(llm, 4), "game_ll_seed": round(lls, 4),
               "game_brier": round(float(np.mean((pg - yg) ** 2)), 4), "game_brier_seed": round(float(np.mean((pgs - yg) ** 2)), 4),
               "champ_ll": round(cm, 3) if cm is not None else None, "champ_ll_seed": round(cs, 3) if cs is not None else None,
               "p_champ": round(float(sim["reach"][ch, 6] / n), 4) if ch is not None else None, "seed_c": round(c, 4)}
        per.append(row)
        agg["brier_model"].append(bm)
        agg["brier_seed"].append(bs)
        agg["ll_model"].append(llm * len(yg))
        agg["ll_seed"].append(lls * len(yg))
        agg["gb_model"].append(float(np.sum((pg - yg) ** 2)))
        agg["gb_seed"].append(float(np.sum((pgs - yg) ** 2)))
        if cm is not None:
            agg["champ_model"].append(cm)
            agg["champ_seed"].append(cs)
    ng = sum(r["n_games"] for r in per)
    summ = {"n_seasons": len(per), "n_games": ng,
            "round_brier": round(float(np.mean(agg["brier_model"])), 5) if per else None,
            "round_brier_seed": round(float(np.mean(agg["brier_seed"])), 5) if per else None,
            "game_ll": round(sum(agg["ll_model"]) / max(ng, 1), 4), "game_ll_seed": round(sum(agg["ll_seed"]) / max(ng, 1), 4),
            "game_brier": round(sum(agg["gb_model"]) / max(ng, 1), 4), "game_brier_seed": round(sum(agg["gb_seed"]) / max(ng, 1), 4),
            "champ_ll": round(float(np.mean(agg["champ_model"])), 3) if agg["champ_model"] else None,
            "champ_ll_seed": round(float(np.mean(agg["champ_seed"])), 3) if agg["champ_seed"] else None,
            "sims": n}
    return {"summary": summ, "per_season": per}
