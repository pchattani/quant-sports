"""
Season simulation for college basketball (numpy, chunks of sims):

1. team strengths drawn per run from N(rating, se) (ratings as of the simulation day, with the season prior);
2. every remaining regular-season game: home margin ~ N(s * (r_h - r_a) * pace / 100 + HCA [not neutral], s0);
3. conference standings by conference win pct (overall win pct, then a random draw, break ties);
4. conference tournaments, GENERIC and APPROXIMATE (per-conference formats are not in any free feed): every member,
   single elimination on a neutral floor, seeded by the simulated standings, byes to the top seeds up to the next
   power of two. Teams that already lost a conference-tournament game this season are out; a conference whose
   final has been played keeps its champion. The winner takes the automatic bid;
5. selection and seeding proxy (ncaa.py / tourney.py) on each run's simulated resume (wins, quadrant results on the
   expected rating ranks, the run's strengths as the rating); the field = autos + top at-large scores;
6. S-curve bracket (four per line, snake into regions, First Four for the last four at-large and the four lowest
   automatic bids) and the bracket simulated with the same run's strengths (women: top-4 seeds host the first two
   rounds).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

import numpy as np
import scipy.sparse as sp
from scipy.stats import norm

from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.hoops import ncaa as N
from oddsmarkets.college.hoops import tourney as TT

CHUNK = 1000


def _bracket_order(B: int) -> list[int]:
    """Seed order of a standard single-elimination bracket of size B (1-based seeds)."""
    order = [1]
    while len(order) < B:
        m = 2 * len(order) + 1
        order = [x for s in order for x in (s, m - s)]
    return order


def conf_groups(tab: dict) -> dict[str, list[int]]:
    g: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(tab["conf"]):
        if c and tab["member"][i]:
            g[c].append(i)
    return {c: v for c, v in g.items() if len(v) >= 2}


def conf_tourney_state(st: dict, tab: dict) -> dict:
    """{"eliminated": set(team idx), "champion": {cid: idx}} from this season's played conference-tournament games."""
    idx = tab["idx"]
    teams = st.get("teams") or {}
    elim, by_conf = set(), defaultdict(list)
    for g in (st.get("games") or {}).values():
        if g.get("stype") != "conf" or g.get("status") != "post" or g.get("hs") is None:
            continue
        h, a = str(g["home"]), str(g["away"])
        ch = (teams.get(h) or {}).get("conference")
        if not ch or ch != (teams.get(a) or {}).get("conference") or (g.get("date") or "")[5:7] not in ("02", "03"):
            continue
        loser = a if g["hs"] > g["as"] else h
        if loser in idx:
            elim.add(idx[loser])
        by_conf[ch].append(g)
    champ = {}
    for c, gs in by_conf.items():
        last = max(gs, key=lambda g: g.get("date") or "")
        rnd = str(last.get("round") or last.get("note") or "").lower()
        if "final" in rnd and "semi" not in rnd and "quarter" not in rnd or "championship" == rnd.strip():
            w = str(last["home"] if last["hs"] > last["as"] else last["away"])
            if w in idx:
                champ[c] = idx[w]
    return {"eliminated": elim, "champion": champ}


def simulate(state: dict, season: int, fit: dict, n: int = 10000, seed: int = 0, as_of_day: int | None = None,
             sel_model: dict | None = None) -> dict:
    """Full-season simulation from `fit` (arrays over the season table, with "se"). Returns per team index tallies
    and the per-conference tournament results (see module docstring)."""
    lv = state["level"]
    tab = state["tabs"][season]
    st = D.load(lv, season)
    prm = state["params"].get(season) or state["params"]["latest"]
    T = tab["T"]
    G, Pd = tab["g"], tab["pend"]
    rng = np.random.default_rng(seed)
    mem = tab["member"]
    fmt = TT.field_format(lv, season)
    n_field, n_ff = fmt["field"], fmt["first_four"]
    groups = conf_groups(tab)
    cts = conf_tourney_state(st, tab)
    # played games (regular season only feed the standings; conf tourney games are in cts)
    dmax = as_of_day if as_of_day is not None else 10 ** 9
    mp = (G["day"] <= dmax) & np.isin(G["stype"], ["reg"])
    hw = (G["hs"] > G["as"])[mp]
    w0 = np.bincount(np.concatenate([G["h"][mp][hw], G["a"][mp][~hw]]), minlength=T).astype(float)
    l0 = np.bincount(np.concatenate([G["a"][mp][hw], G["h"][mp][~hw]]), minlength=T).astype(float)
    cmask = G["conf"][mp]
    cw0 = np.bincount(np.concatenate([G["h"][mp][hw & cmask], G["a"][mp][~hw & cmask]]), minlength=T).astype(float)
    cl0 = np.bincount(np.concatenate([G["a"][mp][hw & cmask], G["h"][mp][~hw & cmask]]), minlength=T).astype(float)
    # remaining regular-season games
    rm = np.isin(Pd["stype"], ["reg"]) & ((Pd["day"] > dmax) if as_of_day is not None else np.ones(len(Pd["day"]), bool))
    rh, ra, rn, rc = Pd["h"][rm], Pd["a"][rm], Pd["neutral"][rm], Pd["conf"][rm]
    Gn = len(rh)
    # quadrant tiers on the expected rating rank
    net = fit["net"]
    order = np.argsort(-np.where(mem, net, -1e9))
    rank = np.empty(T, int)
    rank[order] = np.arange(1, T + 1)
    rank[~mem] = 400
    # played games' quadrant results are fixed
    mp2 = (G["day"] <= dmax) & np.isin(G["stype"], ["reg", "conf"])
    tg = TT.team_games(tab, mp2)
    q = TT.quadrant(rank[tg["opp"]], tg["venue"])

    def cnt(mask):
        return np.bincount(tg["team"][mask], minlength=T).astype(float)
    fixed = {"q1w": cnt(tg["win"] & (q == 1)), "q1l": cnt(~tg["win"] & (q == 1)), "q2w": cnt(tg["win"] & (q == 2)),
             "q34l": cnt(~tg["win"] & (q >= 3))}
    # remaining games' quadrant incidence (home perspective and away perspective)
    vh = np.where(rn, 1, 0)
    va = np.where(rn, 1, 2)
    qh = TT.quadrant(rank[ra], vh) if Gn else np.zeros(0, int)
    qa = TT.quadrant(rank[rh], va) if Gn else np.zeros(0, int)

    def inc(teams, mask):
        rows = np.where(mask)[0]
        return sp.csr_matrix((np.ones(len(rows)), (rows, teams[rows])), shape=(Gn, T))
    Hall, Aall = inc(rh, np.ones(Gn, bool)), inc(ra, np.ones(Gn, bool))
    Hc, Ac = inc(rh, rc), inc(ra, rc)
    Hq = {k: inc(rh, qh == k) for k in (1, 2)}
    Aq = {k: inc(ra, qa == k) for k in (1, 2)}
    Hq34, Aq34 = inc(rh, qh >= 3), inc(ra, qa >= 3)
    # schedule-based fixed features
    allh = np.concatenate([G["h"], Pd["h"]])
    alla = np.concatenate([G["a"], Pd["a"]])
    gp_all = np.bincount(np.concatenate([allh, alla]), minlength=T).astype(float)
    sos = (np.bincount(allh, weights=net[alla], minlength=T) + np.bincount(alla, weights=net[allh], minlength=T)) / np.maximum(gp_all, 1)
    cm = {c: float(np.mean(net[v])) for c, v in groups.items()}
    conf_mean = np.array([cm.get(c, -10.0) if c else -10.0 for c in tab["conf"]])
    mem_idx = np.where(mem)[0]
    host = N.host_rule(lv, season)
    tempo, P = fit["tempo"], fit["league_pace"]
    # tallies
    acc = {k: np.zeros(T) for k in ("w", "l", "cw", "cl", "conf_reg", "conf_t", "ncaa", "auto", "at_large", "seed_sum")}
    seed_cnt = np.zeros((T, 17))
    reach = np.zeros((T, 7))
    conf_win = defaultdict(lambda: np.zeros(T))
    done = 0
    while done < n:
        k = min(CHUNK, n - done)
        S = net[None, :] + fit["se"][None, :] * rng.standard_normal((k, T))
        if Gn:
            pace = tempo[rh] + tempo[ra] - P
            mu = prm["s"] * (S[:, rh] - S[:, ra]) * pace / 100.0 + prm["hca"] * (~rn)
            O = (rng.random((k, Gn)) < norm.cdf(mu / prm["s0"])).astype(float)
            NO = 1.0 - O
            W = w0 + (Hall.T @ O.T).T + (Aall.T @ NO.T).T
            L = l0 + (Hall.T @ NO.T).T + (Aall.T @ O.T).T
            CW = cw0 + (Hc.T @ O.T).T + (Ac.T @ NO.T).T
            CL = cl0 + (Hc.T @ NO.T).T + (Ac.T @ O.T).T
            q1w = fixed["q1w"] + (Hq[1].T @ O.T).T + (Aq[1].T @ NO.T).T
            q1l = fixed["q1l"] + (Hq[1].T @ NO.T).T + (Aq[1].T @ O.T).T
            q2w = fixed["q2w"] + (Hq[2].T @ O.T).T + (Aq[2].T @ NO.T).T
            q34l = fixed["q34l"] + (Hq34.T @ NO.T).T + (Aq34.T @ O.T).T
        else:
            W, L, CW, CL = (np.broadcast_to(x, (k, T)).copy() for x in (w0, l0, cw0, cl0))
            q1w, q1l, q2w, q34l = (np.broadcast_to(fixed[x], (k, T)).copy() for x in ("q1w", "q1l", "q2w", "q34l"))
        acc["w"] += W.sum(0)
        acc["l"] += L.sum(0)
        acc["cw"] += CW.sum(0)
        acc["cl"] += CL.sum(0)
        # conference standings and tournaments
        auto = np.full((k, len(groups)), -1)
        wp = W / np.maximum(W + L, 1)
        cwp = CW / np.maximum(CW + CL, 1)
        key = cwp + 0.01 * wp + 1e-4 * rng.random((k, T))
        rows = np.arange(k)
        for gi, (c, members) in enumerate(sorted(groups.items())):
            mbr = np.array(members)
            kk = key[:, mbr]
            top = mbr[np.argmax(kk, 1)]
            np.add.at(acc["conf_reg"], top, 1.0)
            if c in cts["champion"]:
                ch = np.full(k, cts["champion"][c])
            else:
                alive = np.array([m not in cts["eliminated"] for m in members])
                mbr_a = mbr[alive] if alive.sum() >= 1 else mbr
                ka = key[:, mbr_a]
                seeded = mbr_a[np.argsort(-ka, 1)]                     # (k, m) team idx by seed
                m = seeded.shape[1]
                if m == 1:
                    ch = seeded[:, 0]
                else:
                    B = 1 << (m - 1).bit_length()
                    bo = _bracket_order(B)
                    cur = np.stack([seeded[:, s - 1] if s <= m else np.full(k, -1) for s in bo], 1)
                    while cur.shape[1] > 1:
                        i, j = cur[:, 0::2], cur[:, 1::2]
                        si = np.take_along_axis(S, np.maximum(i, 0), 1)
                        sj = np.take_along_axis(S, np.maximum(j, 0), 1)
                        pg = TT.win_prob(si, sj, tempo[np.maximum(i, 0)], tempo[np.maximum(j, 0)], P, prm)
                        pg = np.where(j < 0, 1.0, np.where(i < 0, 0.0, pg))
                        cur = np.where(rng.random(pg.shape) < pg, i, j)
                    ch = cur[:, 0]
            auto[:, gi] = ch
            np.add.at(acc["conf_t"], ch, 1.0)
            conf_win[c] += np.bincount(ch, minlength=T)
        # selection
        order_r = np.argsort(-np.where(mem[None, :], S, -1e9), 1)
        rk = np.empty((k, T), int)
        np.put_along_axis(rk, order_r, np.arange(1, T + 1)[None, :], 1)
        rl = np.log(rk / (366.0 - np.minimum(rk, 365)))
        feats = {"rating": S, "rank_logit": rl, "wpct": wp, "wins": W, "q1w": q1w, "q1l": q1l, "q2w": q2w,
                 "q34l": q34l, "sos": np.broadcast_to(sos, (k, T)), "conf_mean": np.broadcast_to(conf_mean, (k, T))}
        X = np.stack([feats[f][:, mem_idx] for f in TT.FEATURES], 2)          # (k, M, F)
        Z = (X - np.array(sel_model["mu"])) / np.array(sel_model["sd"])
        bs, bd = np.array(sel_model["b_sel"]), np.array(sel_model["b_seed"])
        sel = bs[0] + Z @ bs[1:]
        sds = bd[0] + Z @ bd[1:]
        posM = np.full(T, -1)
        posM[mem_idx] = np.arange(len(mem_idx))
        Bk = np.full((k, 64), -1)
        ffp = np.full((k, 4), -1)
        ffa = np.full((k, 4), -1)
        ffb = np.full((k, 4), -1)
        seeds_run = np.full((k, T), 99)
        for r in range(k):
            au = np.zeros(len(mem_idx), bool)
            au[posM[auto[r]]] = True
            fld = TT.build_field(mem_idx, au, sel[r], sds[r], n_field, n_ff)
            regs = TT.regions_from_entries(fld["entries"])
            pos, ff = TT.bracket_arrays(regs)
            Bk[r] = pos
            for q_, (p_, a_, b_) in enumerate(ff[:4]):
                ffp[r, q_], ffa[r, q_], ffb[r, q_] = p_, a_, b_
            for t_, sd_ in fld["seed"].items():
                seeds_run[r, t_] = sd_
            f_ = np.array(fld["field"])
            acc["ncaa"][f_] += 1
            a_ids = mem_idx[au]
            acc["auto"][a_ids] += 1
            acc["at_large"][np.setdiff1d(f_, a_ids)] += 1
        sr = seeds_run
        inf = sr < 99
        acc["seed_sum"] += np.where(inf, sr, 0).sum(0)
        for sd_ in range(1, 17):
            seed_cnt[:, sd_] += (sr == sd_).sum(0)
        res = _sim_brackets(Bk, (ffp, ffa, ffb), S, tempo, P, prm, rng, sr, host)
        reach += res
        done += k
    out = {"n": n, "exp_w": acc["w"] / n, "exp_l": acc["l"] / n, "exp_cw": acc["cw"] / n, "exp_cl": acc["cl"] / n,
           "p_conf_reg": acc["conf_reg"] / n, "p_conf_t": acc["conf_t"] / n, "p_ncaa": acc["ncaa"] / n,
           "p_auto": acc["auto"] / n, "p_at_large": acc["at_large"] / n,
           "seed_mean": np.where(acc["ncaa"] > 0, acc["seed_sum"] / np.maximum(acc["ncaa"], 1), np.nan),
           "seed_dist": seed_cnt / n, "reach": reach / n,
           "conf_win": {c: v / n for c, v in conf_win.items()}, "groups": groups}
    return out


def _sim_brackets(Bk, ff, S, tempo, P, prm, rng, seeds_run, host) -> np.ndarray:
    """Per-run brackets (k, 64) with First Four arrays; returns reach counts (T, 7)."""
    k, T = S.shape
    rows = np.arange(k)
    B = Bk.copy()
    fp, fa, fb = ff
    for q in range(fp.shape[1]):
        ok = fp[:, q] >= 0
        if not ok.any():
            continue
        a, b = np.maximum(fa[:, q], 0), np.maximum(fb[:, q], 0)
        pa = TT.win_prob(S[rows, a], S[rows, b], tempo[a], tempo[b], P, prm)
        w = np.where(rng.random(k) < pa, a, b)
        B[rows[ok], fp[ok, q]] = w[ok]
    reach = np.zeros((T, 7))

    def tally(col, arr):
        a_ = arr.ravel()
        np.add.at(reach[:, col], a_[a_ >= 0], 1.0)
    tally(0, B)
    cur = B
    for rd in range(6):
        i, j = cur[:, 0::2], cur[:, 1::2]
        ii, jj = np.maximum(i, 0), np.maximum(j, 0)
        si, sj = np.take_along_axis(S, ii, 1), np.take_along_axis(S, jj, 1)
        home = None
        if host and rd <= 1:
            sdi, sdj = np.take_along_axis(seeds_run, ii, 1), np.take_along_axis(seeds_run, jj, 1)
            home = (sdi <= 4).astype(float) - (sdj <= 4).astype(float)
        p = TT.win_prob(si, sj, tempo[ii], tempo[jj], P, prm, home)
        p = np.where(j < 0, 1.0, np.where(i < 0, 0.0, p))
        w = np.where(rng.random(p.shape) < p, i, j)
        tally(rd + 1, w)
        cur = w
    return reach


def bracket_from_actual(state: dict, season: int, pre: dict, n: int = 10000, seed: int = 0) -> dict:
    """Pre-tournament P(reach) on the actual bracket of a finished season: {"reach": (T, 7), "seeds_of", "regs"}."""
    tab = state["tabs"][season]
    af, fit = pre["af"], pre["fit"]
    regs, seeds_of = N.actual_regions(af, tab["idx"])
    pos, ff = TT.bracket_arrays(regs)
    rng = np.random.default_rng(seed)
    T = tab["T"]
    S = fit["net"][None, :] + fit["se"][None, :] * rng.standard_normal((n, T))
    prm = state["params"][season]
    res = TT.sim_bracket(pos, ff, S, fit["tempo"], fit["league_pace"], prm, rng, seeds_of=seeds_of,
                         host_hca=N.host_rule(state["level"], season))
    return {"reach": res["reach"] / n, "seeds_of": seeds_of, "regs": regs}
