"""
Season simulation for college hockey (numpy, vectorised across simulated seasons).

1. every remaining regular-season game is drawn from the game model (model.outcome on the current ratings, with a
   per-run team strength shift ~ N(0, se) so the uncertainty in the ratings carries into the chances): regulation
   win / level after 60 / regulation loss, then overtime (decided with the era's chance, the stronger side more
   often) or a tie (a shootout: a tie in the NCAA record, a coin flip for the conference's extra point);
2. conference standings by conference points (3 a regulation win, 2 an overtime or shootout win, 1 an overtime or
   shootout loss, the format every Division I conference has used since 2021-22; earlier seasons 2-1-0), a random
   draw breaking ties;
3. conference tournaments, GENERIC and APPROXIMATE (formats differ by conference and change often; no free feed
   lists them): every member, single elimination seeded by the simulated standings, byes to the top seeds up to the
   next power of two, the higher seed at home before the semifinals and a neutral rink from the semifinals; a
   conference whose tournament has started keeps its real results (eliminated teams stay out, a decided final keeps
   its champion). The champion takes the automatic bid;
4. selection on each run's resume: the NPI (npi.py, vectorised here) from 2025-26 on, the RPI before (a proxy for the
   PairWise, which ranks the field almost identically: see the PairWise validation); men 16 = six automatic bids +
   ten at-large, women 11 = five automatic bids + six at-large (8 before 2021-22);
5. the bracket: men four regionals of four (bands of four, serpentine, No. 1 overall's region meets No. 4's in the
   Frozen Four; regional hosts and the first-round conference swap are not modelled), women 6v11 / 7v10 / 8v9 first
   round, quarterfinals at the top four seeds, then the Frozen Four, all simulated with the same run's strengths.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np

from . import model as M
from . import npi as N

CHUNK = 1000


def _bracket_order(B: int) -> list[int]:
    order = [1]
    while len(order) < B:
        m = 2 * len(order) + 1
        order = [x for s in order for x in (s, m - s)]
    return order


class Ctx:
    """Teams, ratings and fixed results of a season as arrays."""

    def __init__(self, store: dict, fit: M.Fit, p: dict, season: int, se: float = 0.08):
        self.season = season
        self.p = {**M.DEFAULTS, **(p or {})}
        self.teams = sorted(t for t, v in store["teams"].items() if v.get("d1"))
        self.idx = {t: i for i, t in enumerate(self.teams)}
        self.conf = [store["teams"][t].get("conf") for t in self.teams]
        self.T = len(self.teams)
        self.att = np.array([fit.rating(t)[0] for t in self.teams])
        self.dfn = np.array([fit.rating(t)[1] for t in self.teams])
        self.mu, self.hfa = fit.mu, fit.hfa
        self.se = se
        self.store = store
        games = [g for g in store["games"] if g.get("stype") != "exh" and g.get("status") not in ("canceled", "postponed")]
        self.played = [g for g in games if g.get("status") == "post" and g.get("res") in ("W", "L", "T")]
        self.remaining = [g for g in games if g.get("status") != "post" and g.get("stype") == "reg"
                          and g["home"] in self.idx and g["away"] in self.idx]
        self.conf_post_played = [g for g in self.played if g.get("stype") == "conf"]
        self.ncaa_played = [g for g in self.played if g.get("stype") == "ncaa"]


def _means(ctx: Ctx, h: np.ndarray, a: np.ndarray, neutral: np.ndarray, shift: np.ndarray | None = None):
    """lam_h, lam_a for arrays of team indices; shift (sims x T) adds to attack and defence equally."""
    ah, aa = ctx.att[h], ctx.att[a]
    dh, da = ctx.dfn[h], ctx.dfn[a]
    if shift is not None:
        ah = ah + shift[:, h] / 2
        dh = dh + shift[:, h] / 2
        aa = aa + shift[:, a] / 2
        da = da + shift[:, a] / 2
    lh = np.exp(ctx.mu + np.where(neutral, 0.0, ctx.hfa) + ah - da)
    la = np.exp(ctx.mu + aa - dh)
    return lh, la


def _probs(lh: np.ndarray, la: np.ndarray, p: dict, ties: bool, season: int) -> tuple[np.ndarray, ...]:
    """Vectorised outcome: (p_reg_home, p_reg_tie, p_reg_away, q_decided, share_home)."""
    n = p.get("max_goals", 10)
    k = np.arange(n + 1)
    lg = np.array([math.lgamma(i + 1) for i in k])
    LH = np.exp(np.multiply.outer(np.log(np.maximum(lh, 1e-9)), k) - lh[..., None] - lg)
    LA = np.exp(np.multiply.outer(np.log(np.maximum(la, 1e-9)), k) - la[..., None] - lg)
    tie = (LH * LA).sum(-1)
    cdfA = np.cumsum(LA, -1)
    # P(home > away) = sum_k P(H = k) P(A < k)
    win = (LH[..., 1:] * cdfA[..., :-1]).sum(-1)
    loss = 1.0 - win - tie
    tie = tie * (1 + p["rho"])
    s = win + loss + tie
    win, loss, tie = win / s, loss / s, tie / s
    share = lh ** p.get("k_ot", 1.0) / (lh ** p.get("k_ot", 1.0) + la ** p.get("k_ot", 1.0))
    q = (p["q_3v3"] if season >= 2022 else p["q_pre"]) if ties else 1.0
    return win, tie, loss, np.full_like(win, q), share


def _play(rng, win, tie, loss, q, share):
    """codes: 0 home reg win, 1 home OT win, 2 tie (shootout), 3 away OT win, 4 away reg win."""
    u = rng.random(win.shape)
    v = rng.random(win.shape)
    w = rng.random(win.shape)
    out = np.full(win.shape, 4, dtype=np.int8)
    out[u < win] = 0
    lev = (u >= win) & (u < win + tie)
    dec = lev & (v < q)
    out[dec & (w < share)] = 1
    out[dec & (w >= share)] = 3
    out[lev & ~(v < q)] = 2
    return out


def _single(rng, ctx: Ctx, A: np.ndarray, B: np.ndarray, homeA: np.ndarray | bool, shift: np.ndarray, rows: np.ndarray):
    """Winners of single games A v B (arrays over sims), A at home where homeA else neutral."""
    neutral = ~np.asarray(homeA, dtype=bool) if not isinstance(homeA, bool) else np.full(A.shape, not homeA)
    lh, la = _means(ctx, A, B, neutral, None)
    sA = shift[rows, A]
    sB = shift[rows, B]
    lh = lh * np.exp((sA - sB) / 2)
    la = la * np.exp((sB - sA) / 2)
    win, tie, loss, q, share = _probs(lh, la, ctx.p, ties=False, season=ctx.season)
    pA = win + tie * share
    return np.where(rng.random(A.shape) < pA, A, B)


def _npi_vec(T: int, rows_t: np.ndarray, rows_o: np.ndarray, wW: np.ndarray, wL: np.ndarray, iters: int = 40,
             qwb_floor: float = 51.0, qwb_rate: float = 0.5) -> np.ndarray:
    """NPI for many runs at once. rows_*: (R,) team / opponent of each team-game row; wW, wL: (S, R) weights.
    Returns (S, T)."""
    S = wW.shape[0]
    x = np.full((S, T), 50.0)
    ww_tot = np.zeros((S, T))
    # weighted wins per team (for the 12-win threshold)
    ww_tot = np.zeros((S, T))
    np.add.at(ww_tot.T, rows_t, wW.T)
    for _ in range(iters):
        xo = x[:, rows_o]
        W = 25.0 + 0.75 * xo + np.where(xo > qwb_floor, qwb_rate * (xo - qwb_floor), 0.0)
        L = 0.75 * xo
        num = np.zeros((S, T))
        den = np.zeros((S, T))
        np.add.at(num.T, rows_t, (wW * W + wL * L).T)
        np.add.at(den.T, rows_t, (wW + wL).T)
        cur = np.where(den > 0, num / np.maximum(den, 1e-9), 50.0)
        cur_r = cur[:, rows_t]
        keepW = ~((ww_tot[:, rows_t] >= 12.0) & (W < cur_r))
        keepL = ~(L > cur_r)
        num = np.zeros((S, T))
        den = np.zeros((S, T))
        np.add.at(num.T, rows_t, (wW * W * keepW + wL * L * keepL).T)
        np.add.at(den.T, rows_t, (wW * keepW + wL * keepL).T)
        new = np.where(den > 0, num / np.maximum(den, 1e-9), cur)
        if np.max(np.abs(new - x)) < 1e-4:
            x = new
            break
        x = new
    return x


def _rpi_vec(T: int, rows_t: np.ndarray, rows_o: np.ndarray, wW: np.ndarray, wL: np.ndarray) -> np.ndarray:
    """RPI (0.25 / 0.21 / 0.54, weighted components, no bonus) for many runs: (S, T)."""
    S = wW.shape[0]
    ww = np.zeros((S, T))
    wn = np.zeros((S, T))
    np.add.at(ww.T, rows_t, wW.T)
    np.add.at(wn.T, rows_t, (wW + wL).T)
    wp = np.where(wn > 0, ww / np.maximum(wn, 1e-9), 0)
    owp_rows = wp[:, rows_o]
    cnt = np.zeros(T)
    np.add.at(cnt, rows_t, 1.0)
    owp = np.zeros((S, T))
    np.add.at(owp.T, rows_t, owp_rows.T)
    owp = owp / np.maximum(cnt, 1)
    oowp = np.zeros((S, T))
    np.add.at(oowp.T, rows_t, owp[:, rows_o].T)
    oowp = oowp / np.maximum(cnt, 1)
    return 0.25 * wp + 0.21 * owp + 0.54 * oowp


def _weights_vec(code: np.ndarray, site_home: np.ndarray, site_neu: np.ndarray, conf_post: np.ndarray, season: int,
                 use_npi: bool, rules: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(wW, wL) for the HOME side of game codes (S, G); the away side mirrors by swapping."""
    weighted = (~site_neu) & (~conf_post)
    if use_npi and rules is not None and not rules.get("weighted", True):
        weighted = np.zeros_like(weighted)
    if not use_npi and season < 2014:
        weighted = np.zeros_like(weighted)
    hwW = np.where(weighted, 0.8, 1.0)       # home win weight
    hwL = np.where(weighted, 1.2, 1.0)       # home loss weight
    awW = np.where(weighted, 1.2, 1.0)       # away win weight
    awL = np.where(weighted, 0.8, 1.0)
    lose_share = (rules or {}).get("ot_lose", 0.4) if use_npi else (1 / 3 if season >= 2022 else 0.0)
    extra = 1 - 2 * lose_share
    hW = np.zeros(code.shape)
    hL = np.zeros(code.shape)
    aW = np.zeros(code.shape)
    aL = np.zeros(code.shape)
    # regulation home win
    m = code == 0
    hW = np.where(m, hwW, hW); aL = np.where(m, awL, aL)
    m = code == 4
    hL = np.where(m, hwL, hL); aW = np.where(m, awW, aW)
    m = code == 2
    hW = np.where(m, 0.5 * hwW, hW); hL = np.where(m, 0.5 * hwL, hL)
    aW = np.where(m, 0.5 * awW, aW); aL = np.where(m, 0.5 * awL, aL)
    if lose_share > 0:
        m = code == 1
        hW = np.where(m, lose_share * hwW + extra, hW); hL = np.where(m, lose_share * hwL, hL)
        aW = np.where(m, lose_share * awW, aW); aL = np.where(m, lose_share * awL + extra, aL)
        m = code == 3
        hW = np.where(m, lose_share * hwW, hW); hL = np.where(m, lose_share * hwL + extra, hL)
        aW = np.where(m, lose_share * awW + extra, aW); aL = np.where(m, lose_share * awL, aL)
    else:
        m = code == 1
        hW = np.where(m, hwW, hW); aL = np.where(m, awL, aL)
        m = code == 3
        hL = np.where(m, hwL, hL); aW = np.where(m, awW, aW)
    return hW, hL, aW, aL


def _code_of(g: dict) -> int:
    r = g.get("res")
    ot = (g.get("ot") or 0) > 0 and r != "T"
    if r == "T":
        return 2
    if r == "W":
        return 1 if ot else 0
    return 3 if ot else 4


def field_format(level: str, season: int) -> dict:
    if level == "mch":
        return {"field": 16, "auto": 6, "kind": "regionals", "verified": True,
                "rule": "16 teams: six conference tournament champions and ten at-large by the " +
                        ("NPI" if season >= 2026 else "PairWise") + "; four regionals of four, then the Frozen Four"}
    if season >= 2022:
        return {"field": 11, "auto": 5, "kind": "women11", "verified": season <= 2026,
                "rule": "11 teams: five conference champions and six at-large by the " + ("NPI" if season >= 2026 else "PairWise") +
                        "; seeds 6-11 play a first round, quarterfinals at the top four seeds, then the Frozen Four"}
    return {"field": 8, "auto": 4, "kind": "women8", "verified": False,
            "rule": "8 teams: quarterfinals at the higher seeds, then the Frozen Four"}


def simulate(ctx: Ctx, level: str, n: int = 4000, seed: int = 0) -> dict:
    """Simulate the rest of the season. Returns per-team tallies (probabilities) and distributions."""
    rng = np.random.default_rng(seed)
    T = ctx.T
    season = ctx.season
    use_npi = season >= 2026
    fmt = field_format(level, season)
    # conference groups (members with 2+ teams; Independents are not a conference)
    groups = defaultdict(list)
    for i, c in enumerate(ctx.conf):
        if c and c not in ("ind", "independent", "d-i-independent"):
            groups[c].append(i)
    groups = {c: v for c, v in groups.items() if len(v) >= 4}
    # fixed results
    pl = [g for g in ctx.played if g["home"] in ctx.idx and g["away"] in ctx.idx and g.get("stype") in ("reg", "conf")]
    G0 = len(pl)
    rem = ctx.remaining
    R = len(rem)
    gh = np.array([ctx.idx[g["home"]] for g in pl + rem], dtype=int)
    ga = np.array([ctx.idx[g["away"]] for g in pl + rem], dtype=int)
    neu = np.array([bool(g.get("neutral")) for g in pl + rem])
    cpost = np.array([g.get("stype") == "conf" for g in pl + rem])
    confg = np.array([bool(g.get("conf_game")) for g in pl + rem])
    fixed = np.array([_code_of(g) for g in pl], dtype=np.int8)
    tallies = defaultdict(lambda: np.zeros(T))
    seed_cnt = np.zeros((T, fmt["field"] + 1))
    rank_sum = np.zeros(T)
    wins_dist = defaultdict(lambda: np.zeros(80))
    # conference tournament state
    elim, champ = _conf_state(ctx, groups)
    done = 0
    while done < n:
        S = min(CHUNK, n - done)
        shift = rng.normal(0, ctx.se, size=(S, T))
        rows = np.arange(S)[:, None]
        if R:
            h = np.broadcast_to(gh[G0:], (S, R))
            a = np.broadcast_to(ga[G0:], (S, R))
            lh, la = _means(ctx, gh[G0:], ga[G0:], neu[G0:])
            lh = lh[None, :] * np.exp((shift[:, gh[G0:]] - shift[:, ga[G0:]]) / 2)
            la = la[None, :] * np.exp((shift[:, ga[G0:]] - shift[:, gh[G0:]]) / 2)
            win, tie, loss, q, share = _probs(lh, la, ctx.p, ties=True, season=season)
            sim_codes = _play(rng, win, tie, loss, q, share)
            codes = np.concatenate([np.broadcast_to(fixed, (S, G0)), sim_codes], axis=1)
        else:
            codes = np.broadcast_to(fixed, (S, G0)).copy()
        Gn = codes.shape[1]
        # records
        W = np.zeros((S, T)); L = np.zeros((S, T)); Tt = np.zeros((S, T))
        for c, (hw, hl, ht) in {0: (1, 0, 0), 1: (1, 0, 0), 2: (0, 0, 1), 3: (0, 1, 0), 4: (0, 1, 0)}.items():
            m = (codes == c).astype(float)
            np.add.at(W.T, gh, (m * hw).T)
            np.add.at(L.T, gh, (m * hl).T)
            np.add.at(Tt.T, gh, (m * ht).T)
            np.add.at(W.T, ga, (m * hl).T)
            np.add.at(L.T, ga, (m * hw).T)
            np.add.at(Tt.T, ga, (m * ht).T)
        # conference points (regular-season conference games)
        pts3 = season >= 2022
        so_home = rng.random(codes.shape) < 0.5
        ph = np.select([codes == 0, codes == 1, codes == 2, codes == 3], [3 if pts3 else 2, 2 if pts3 else 2,
                       np.where(so_home, 2, 1) if pts3 else 1, 1 if pts3 else 0], 0)
        pa = np.select([codes == 4, codes == 3, codes == 2, codes == 1], [3 if pts3 else 2, 2 if pts3 else 2,
                       np.where(so_home, 1, 2) if pts3 else 1, 1 if pts3 else 0], 0)
        cmask = (confg & ~cpost)[None, :]
        CP = np.zeros((S, T))
        np.add.at(CP.T, gh, (ph * cmask).T)
        np.add.at(CP.T, ga, (pa * cmask).T)
        jitter = rng.random((S, T)) * 0.01
        autos = {}
        for c, mem in groups.items():
            mem = np.array(mem)
            score = CP[:, mem] + jitter[:, mem]
            order = np.argsort(-score, axis=1)
            seeded = mem[order]                                   # (S, m) best first
            tallies["p_conf_reg"][seeded[:, 0]] += 0
            np.add.at(tallies["p_conf_reg"], seeded[:, 0], 1)
            if c in champ:
                ch = np.full(S, champ[c])
            else:
                ch = _conf_tourney(rng, ctx, seeded, elim.get(c, set()), shift)
            np.add.at(tallies["p_conf_tourney"], ch, 1)
            autos[c] = ch
        # selection
        rt = np.concatenate([gh, ga])
        ro = np.concatenate([ga, gh])
        rules = N.NPI_RULES.get(level, N.NPI_RULES["mch"])
        hW, hL, aW, aL = _weights_vec(codes, ~neu[None, :], neu[None, :], cpost[None, :], season, use_npi, rules)
        wW = np.concatenate([hW, aW], axis=1)
        wL = np.concatenate([hL, aL], axis=1)
        if use_npi:
            score = _npi_vec(T, rt, ro, wW, wL, qwb_floor=rules["qwb_floor"])
        else:
            score = _rpi_vec(T, rt, ro, wW, wL)
        order = np.argsort(-score, axis=1)
        rank = np.empty_like(order)
        rank[rows, order] = np.arange(T)[None, :]
        rank_sum += (rank + 1).sum(0)
        field_n, n_auto = fmt["field"], len(autos)
        in_field = np.zeros((S, T), dtype=bool)
        auto_mask = np.zeros((S, T), dtype=bool)
        for c, ch in autos.items():
            auto_mask[np.arange(S), ch] = True
        in_field |= auto_mask
        # at-large: best ranked non-autos until the field is full
        need = field_n - auto_mask.sum(1)
        cand_rank = np.where(auto_mask, 10 ** 6, rank)
        ordc = np.argsort(cand_rank, axis=1)
        for s in range(S):
            in_field[s, ordc[s, :need[s]]] = True
        at_large = in_field & ~auto_mask
        tallies["p_ncaa"] += in_field.sum(0)
        tallies["p_auto"] += auto_mask.sum(0)
        tallies["p_at_large"] += at_large.sum(0)
        # field order by the selection ranking -> overall seeds
        fr = np.where(in_field, rank, 10 ** 6)
        fo = np.argsort(fr, axis=1)[:, :field_n]                  # (S, field) teams by overall seed
        for k in range(field_n):
            np.add.at(seed_cnt, (fo[:, k], k + 1), 1)
        # bracket
        res = _bracket(rng, ctx, fo, shift, fmt)
        for key, arr in res.items():
            tallies[key] += arr
        tallies["exp_w"] += W.sum(0)
        tallies["exp_l"] += L.sum(0)
        tallies["exp_t"] += Tt.sum(0)
        tallies["exp_cpts"] += CP.sum(0)
        for i in range(T):
            wins_dist[i] += np.bincount(W[:, i].astype(int), minlength=80)[:80]
        done += S
    out = {}
    for i, t in enumerate(ctx.teams):
        sd = {str(k): round(float(seed_cnt[i, k] / n), 4) for k in range(1, fmt["field"] + 1) if seed_cnt[i, k] > 0}
        sm = sum(k * seed_cnt[i, k] for k in range(1, fmt["field"] + 1))
        tot = seed_cnt[i, 1:].sum()
        rec = {k: round(float(v[i] / n), 4) for k, v in tallies.items()}
        rec.update({"seed_mean": round(float(sm / tot), 2) if tot else None, "seed_dist": sd,
                    "sel_rank_mean": round(float(rank_sum[i] / n), 1)})
        wd = wins_dist[i] / n
        rec["w_dist"] = [round(float(x), 4) for x in wd[: int(np.max(np.nonzero(wd)[0])) + 1]] if wd.any() else []
        out[t] = rec
    return {"teams": out, "n_sims": n, "format": fmt, "selection": "npi" if use_npi else "rpi_proxy"}


def _conf_state(ctx: Ctx, groups: dict) -> tuple[dict, dict]:
    elim: dict[str, set] = defaultdict(set)
    champ: dict[str, int] = {}
    teams = ctx.store["teams"]
    by = defaultdict(list)
    for g in ctx.conf_post_played:
        c = teams.get(g["home"], {}).get("conf")
        if c in groups and c == teams.get(g["away"], {}).get("conf"):
            by[c].append(g)
            if g.get("res") in ("W", "L"):
                loser = g["away"] if g["res"] == "W" else g["home"]
                # a best-of-three loss does not eliminate; only the series result does. Approximation: a team out
                # once it has lost two games in a round, or one game from the semifinals on
                elim[c].add(ctx.idx.get(loser))
    for c, gs in by.items():
        last = max(gs, key=lambda g: g["date"])
        if (last.get("round") or "") == "Final" and last.get("res") in ("W", "L"):
            w = last["home"] if last["res"] == "W" else last["away"]
            if w in ctx.idx:
                champ[c] = ctx.idx[w]
    # with best-of-three rounds the elimination guess above is loose: keep only teams with 2+ losses or a loss in
    # a semifinal / final
    for c, gs in by.items():
        losses = defaultdict(int)
        late = set()
        for g in gs:
            if g.get("res") in ("W", "L"):
                loser = g["away"] if g["res"] == "W" else g["home"]
                losses[loser] += 1
                if (g.get("round") or "") in ("Semifinal", "Final"):
                    late.add(loser)
        elim[c] = {ctx.idx[t] for t, k in losses.items() if (k >= 2 or t in late) and t in ctx.idx}
    return elim, champ


def _conf_tourney(rng, ctx: Ctx, seeded: np.ndarray, eliminated: set, shift: np.ndarray) -> np.ndarray:
    """Generic single-elimination conference tournament on the simulated seeding (S, m) -> champion (S,)."""
    S, m = seeded.shape
    B = 1
    while B < m:
        B *= 2
    order = _bracket_order(B)
    # slots: seed k (1-based) or a bye
    slots = []
    for sd in order:
        slots.append(seeded[:, sd - 1] if sd <= m else np.full(S, -1))
    cur = np.stack(slots, axis=1)                                   # (S, B)
    seedno = np.stack([np.full(S, sd if sd <= m else 999) for sd in order], axis=1)
    elim = np.array(sorted(x for x in eliminated if x is not None), dtype=int)
    rows = np.arange(S)
    rnd = 0
    while cur.shape[1] > 1:
        A, Bt = cur[:, 0::2], cur[:, 1::2]
        sA, sB = seedno[:, 0::2], seedno[:, 1::2]
        nxt = np.where(A < 0, Bt, np.where(Bt < 0, A, -2))
        need = nxt == -2
        if need.any():
            fav = np.where(sA <= sB, A, Bt)
            dog = np.where(sA <= sB, Bt, A)
            late = cur.shape[1] <= 4                                # semifinals on: neutral
            Af, Df = fav[need], dog[need]
            rr = np.broadcast_to(rows[:, None], need.shape)[need]
            w = _single(rng, ctx, Af, Df, not late, shift, rr)
            if len(elim):
                # a team already out loses
                Af_out = np.isin(Af, elim)
                Df_out = np.isin(Df, elim)
                w = np.where(Af_out & ~Df_out, Df, np.where(Df_out & ~Af_out, Af, w))
            nxt[need] = w
        nseed = np.where(nxt == A, sA, sB)
        cur, seedno = nxt, nseed
        rnd += 1
    return cur[:, 0]


def _bracket(rng, ctx: Ctx, fo: np.ndarray, shift: np.ndarray, fmt: dict) -> dict:
    """Simulate the NCAA tournament from the field in overall-seed order (S, field). Returns tallies {key: (T,)}."""
    S = fo.shape[0]
    T = ctx.T
    rows = np.arange(S)
    tal = {k: np.zeros(T) for k in ("p_qf", "p_f4", "p_final", "p_title")}

    def win(a, b, home_a=False):
        return _single(rng, ctx, a, b, home_a, shift, rows)

    if fmt["kind"] == "regionals":
        # bands: region r has seeds (r, 7-r, 8+r, 15-r) in 0-based overall order (serpentine)
        reg = []
        for r in range(4):
            s1, s2, s3, s4 = fo[:, r], fo[:, 7 - r], fo[:, 8 + r], fo[:, 15 - r]
            w14 = win(s1, s4)
            w23 = win(s2, s3)
            for x in (w14, w23):
                np.add.at(tal["p_qf"], x, 1)
            reg.append(win(w14, w23))
        for x in reg:
            np.add.at(tal["p_f4"], x, 1)
        f1 = win(reg[0], reg[3])
        f2 = win(reg[1], reg[2])
        np.add.at(tal["p_final"], f1, 1)
        np.add.at(tal["p_final"], f2, 1)
        ch = win(f1, f2)
        np.add.at(tal["p_title"], ch, 1)
        return tal
    if fmt["kind"] == "women11":
        s = [fo[:, k] for k in range(11)]
        a = win(s[7], s[8], True)        # 8 v 9
        b = win(s[6], s[9], True)        # 7 v 10
        c = win(s[5], s[10], True)       # 6 v 11
        for x in (s[0], s[1], s[2], s[3], s[4], a, b, c):
            np.add.at(tal["p_qf"], x, 1)
        q1 = win(s[0], a, True)
        q2 = win(s[1], b, True)
        q3 = win(s[2], c, True)
        q4 = win(s[3], s[4], True)
        for x in (q1, q2, q3, q4):
            np.add.at(tal["p_f4"], x, 1)
        f1 = win(q1, q4)
        f2 = win(q2, q3)
        np.add.at(tal["p_final"], f1, 1)
        np.add.at(tal["p_final"], f2, 1)
        np.add.at(tal["p_title"], win(f1, f2), 1)
        return tal
    s = [fo[:, k] for k in range(8)]
    for x in s:
        np.add.at(tal["p_qf"], x, 1)
    q = [win(s[0], s[7], True), win(s[3], s[4], True), win(s[1], s[6], True), win(s[2], s[5], True)]
    for x in q:
        np.add.at(tal["p_f4"], x, 1)
    f1, f2 = win(q[0], q[1]), win(q[2], q[3])
    np.add.at(tal["p_final"], f1, 1)
    np.add.at(tal["p_final"], f2, 1)
    np.add.at(tal["p_title"], win(f1, f2), 1)
    return tal


def bracket_odds(ctx: Ctx, level: str, regions: dict[str, list], n: int = 20000, seed: int = 0) -> dict:
    """Our chances through a KNOWN bracket (the field as seeded): {team: {p_qf, p_f4, p_final, p_title}}.
    `regions` for men: {name: [(seed, team), ...4]} in the order of ncaa regional play; the Frozen Four pairs the
    first listed region with the fourth and the second with the third. Women: {"seeds": [team by seed 1..11]}."""
    rng = np.random.default_rng(seed)
    S = n
    shift = rng.normal(0, ctx.se, size=(S, ctx.T))
    fmt = field_format(level, ctx.season)
    if level == "mch":
        names = list(regions)
        fo = np.zeros((S, 16), dtype=int)
        # rebuild an overall order consistent with _bracket's serpentine slots
        slot = {}
        for r, nm in enumerate(names[:4]):
            seeds = dict(regions[nm])
            for k, pos in ((1, r), (2, 7 - r), (3, 8 + r), (4, 15 - r)):
                t = seeds.get(k)
                if t is None or t not in ctx.idx:
                    return {}
                fo[:, pos] = ctx.idx[t]
        res = _bracket(rng, ctx, fo, shift, fmt)
    else:
        seeds = regions.get("seeds") or []
        if len(seeds) < fmt["field"] or any(t not in ctx.idx for t in seeds[: fmt["field"]]):
            return {}
        fo = np.tile(np.array([ctx.idx[t] for t in seeds[: fmt["field"]]]), (S, 1))
        res = _bracket(rng, ctx, fo, shift, fmt)
    return {t: {k: round(float(v[i] / n), 4) for k, v in res.items()} for i, t in enumerate(ctx.teams)
            if any(v[i] for v in res.values())}
