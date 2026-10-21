"""
NCAA tournament: the actual field of a past season, resume features at Selection Sunday, the selection and seeding
proxy, S-curve brackets and the vectorised bracket simulation.

Actual field (`actual_field`): the teams of the season's NCAA tournament games; seeds from the games (`seeds`);
the First Four = the (field - 64) earliest tournament games (men 2002-2010: the one opening-round game); regions =
the region of a team's games (Final Four excluded); automatic bids: in each conference represented in the field,
the field team that won the conference's last intra-conference game before the tournament (the tournament final),
else the only field team of that conference, else its field team with the best conference record (the Ivy
League before 2017 had no tournament); every other field team is an at-large.

Resume (`resume`), from games before the first tournament day: our rating and its rank (ratings fitted through
Selection Sunday with the season prior), wins, losses, win pct, quadrant wins and losses on our rating rank with
the NET venue cut-offs (Q1: home 1-30, neutral 1-50, away 1-75; Q2: 31-75 / 51-100 / 76-135; Q3: 76-160 /
101-200 / 136-240; Q4 beyond), strength of schedule (mean opponent rating), conference mean rating.

Selection proxy: a ridge logistic regression of "picked as an at-large" on standardized resume features over the
non-automatic teams of past fields; the field = automatic bids + the top (field - autos) scores. Seeding proxy: a
linear regression of the seed on the same features over field teams; the field is ordered by predicted seed and
dealt into seed lines (four per line; First Four pairs share a line). Both are reported leave-one-season-out
(`loso`). Not modelled: the committee's conference-separation and geography rules in bracketing.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

import numpy as np
from scipy.stats import norm

from oddsmarkets.college.hoops import data as D

ROUND_KEYS = ["R64", "R32", "S16", "E8", "F4", "Final", "Champion"]
SIM_KEYS = {"R32": "r32", "S16": "s16", "E8": "e8", "F4": "f4", "Final": "final", "Champion": "title"}
SLOT_SEEDS = [1, 16, 8, 9, 5, 12, 4, 13, 6, 11, 3, 14, 7, 10, 2, 15]
FEATURES = ["rating", "rank_logit", "wpct", "wins", "q1w", "q1l", "q2w", "q34l", "sos", "conf_mean"]


def field_format(level: str, season: int) -> dict:
    """{"field","first_four","at_large"(approx)}: men 65 (2002-2010), 68 (2011 on); women 64, 68 from 2022."""
    if level == "mbb":
        n = 65 if season <= 2010 else 68
    else:
        n = 68 if season >= 2022 else 64
    return {"field": n, "first_four": n - 64, "verified": True}


# ── actual field ────────────────────────────────────────────────────────────

def ncaa_games(st: dict) -> list[dict]:
    return sorted((g for g in (st.get("games") or {}).values() if g.get("stype") == "ncaa" and g.get("status") == "post"
                   and g.get("hs") is not None), key=lambda g: (g.get("date") or "", str(g["id"])))


def conf_records(st: dict, before: str | None = None) -> dict[str, list[int]]:
    """{tid: [conf_w, conf_l]} from conference games (conf_game flag) before `before` (ISO)."""
    out: dict[str, list[int]] = {}
    teams = st.get("teams") or {}
    for g in (st.get("games") or {}).values():
        if g.get("status") != "post" or g.get("hs") is None or g.get("stype") != "reg":
            continue
        if before and (g.get("date") or "") >= before:
            continue
        h, a = str(g["home"]), str(g["away"])
        ch, ca = (teams.get(h) or {}).get("conference"), (teams.get(a) or {}).get("conference")
        if not ch or ch != ca:
            continue
        hw = g["hs"] > g["as"]
        out.setdefault(h, [0, 0])[0 if hw else 1] += 1
        out.setdefault(a, [0, 0])[1 if hw else 0] += 1
    return out


def conf_champions(st: dict, before: str) -> dict[str, str]:
    """{cid: tid}: winner of each conference's last intra-conference game in March before `before` (the conference
    tournament final where the conference has one)."""
    teams = st.get("teams") or {}
    last: dict[str, dict] = {}
    for g in (st.get("games") or {}).values():
        if g.get("status") != "post" or g.get("hs") is None or g.get("stype") not in ("conf", "reg"):
            continue
        dte = g.get("date") or ""
        if dte >= before or dte[5:7] not in ("02", "03"):
            continue
        h, a = str(g["home"]), str(g["away"])
        c = (teams.get(h) or {}).get("conference")
        if not c or c != (teams.get(a) or {}).get("conference"):
            continue
        if c not in last or dte > (last[c].get("date") or ""):
            last[c] = g
    return {c: str(g["home"] if g["hs"] > g["as"] else g["away"]) for c, g in last.items()}


def actual_field(level: str, season: int, st: dict) -> dict | None:
    """{"teams": {tid: {"seed","region","auto": bool,"ff": bool,"wins","reached": round key}}, "regions": [4 names in
    bracket order: semifinal pairs (0,1), (2,3)], "first_four": [[a, b, winner]], "first_day": iso, "champion",
    "field", "n_auto", "n_at_large"} or None (no tournament)."""
    gs = ncaa_games(st)
    if len(gs) < 60:
        return None
    teams_all = {}
    for g in gs:
        for side in ("home", "away"):
            t = str(g[side])
            rec = teams_all.setdefault(t, {"seed": None, "regions": Counter(), "wins": 0, "ff": False})
            sd = (g.get("seeds") or {}).get(side)
            if sd and not rec["seed"]:
                rec["seed"] = int(sd)
    n = len(teams_all)
    n_ff = max(0, n - 64)
    ff_games = gs[:n_ff]
    ff_ids = {str(g["id"]) for g in ff_games}
    first_four = []
    for g in ff_games:
        w = str(g["home"] if g["hs"] > g["as"] else g["away"])
        first_four.append([str(g["home"]), str(g["away"]), w])
        teams_all[str(g["home"])]["ff"] = teams_all[str(g["away"])]["ff"] = True
    for a, b, _w in first_four:                      # an opening-round team without a seed takes its opponent's
        if not teams_all[a]["seed"]:
            teams_all[a]["seed"] = teams_all[b]["seed"]
        if not teams_all[b]["seed"]:
            teams_all[b]["seed"] = teams_all[a]["seed"]
    main = [g for g in gs if str(g["id"]) not in ff_ids]
    final = main[-1] if main else None
    semis = main[-3:-1] if len(main) >= 3 else []
    late_rounds = {str(g["id"]) for g in semis} | ({str(final["id"])} if final else set())
    for g in gs:
        if str(g["id"]) in late_rounds:
            continue
        r = g.get("region")
        if r:
            teams_all[str(g["home"])]["regions"][r] += 1
            teams_all[str(g["away"])]["regions"][r] += 1
    for g in main:
        w = str(g["home"] if g["hs"] > g["as"] else g["away"])
        teams_all[w]["wins"] += 1
    regions_seen = Counter()
    for t, v in teams_all.items():
        v["region"] = v["regions"].most_common(1)[0][0] if v["regions"] else None
        regions_seen[v["region"]] += 1
        del v["regions"]
    # Final Four region pairs
    pairs = []
    for g in semis:
        pairs.append([teams_all[str(g["home"])]["region"], teams_all[str(g["away"])]["region"]])
    regions = [r for r, _ in regions_seen.most_common() if r][:4]
    order = []
    for p in pairs:
        for r in p:
            if r and r not in order:
                order.append(r)
    for r in regions:
        if r not in order:
            order.append(r)
    order = order[:4]
    for v in teams_all.values():
        v["reached"] = ROUND_KEYS[min(v["wins"], 6)] if True else None
    first_day = gs[0].get("date")
    # automatic bids
    tinfo = st.get("teams") or {}
    champs = conf_champions(st, first_day)
    crec = conf_records(st, first_day)
    by_conf: dict[str, list[str]] = {}
    for t in teams_all:
        c = (tinfo.get(t) or {}).get("conference")
        if c:
            by_conf.setdefault(c, []).append(t)
    autos = set()
    for c, ts in by_conf.items():
        if (st.get("conferences") or {}).get(c, {}).get("name", "").lower().find("independ") >= 0:
            continue
        ch = champs.get(c)
        if ch in ts:
            autos.add(ch)
        elif len(ts) == 1:
            autos.add(ts[0])
        else:
            best = max(ts, key=lambda t: (crec.get(t, [0, 0])[0] - crec.get(t, [0, 0])[1], -(teams_all[t]["seed"] or 99)))
            autos.add(best)
    for t, v in teams_all.items():
        v["auto"] = t in autos
    champion = str(final["home"] if final["hs"] > final["as"] else final["away"]) if final else None
    return {"teams": teams_all, "regions": order, "first_four": first_four, "first_day": first_day,
            "champion": champion, "field": n, "n_auto": len(autos), "n_at_large": n - len(autos)}


# ── resume features ─────────────────────────────────────────────────────────

Q_CUTS = {"home": (30, 75, 160), "neutral": (50, 100, 200), "away": (75, 135, 240)}


def quadrant(opp_rank: np.ndarray, venue: np.ndarray) -> np.ndarray:
    """1..4 from the opponent's rank and the venue code (0 home, 1 neutral, 2 away)."""
    cuts = np.array([Q_CUTS["home"], Q_CUTS["neutral"], Q_CUTS["away"]])
    c = cuts[venue]
    return 1 + (opp_rank > c[:, 0]).astype(int) + (opp_rank > c[:, 1]) + (opp_rank > c[:, 2])


def team_games(tab: dict, m: np.ndarray) -> dict:
    """Both teams' perspective of the masked finished games: team, opp, win, venue code."""
    G = tab["g"]
    h, a = G["h"][m], G["a"][m]
    hw = (G["hs"][m] > G["as"][m])
    neu = G["neutral"][m]
    team = np.concatenate([h, a])
    opp = np.concatenate([a, h])
    win = np.concatenate([hw, ~hw])
    venue = np.concatenate([np.where(neu, 1, 0), np.where(neu, 1, 2)])
    return {"team": team, "opp": opp, "win": win, "venue": venue}


def resume(tab: dict, fitres: dict, before_day: int, conf_of: list | None = None) -> dict[str, np.ndarray]:
    """Arrays over tab["teams"] (members meaningful): FEATURES + "rank","w","l"."""
    G, T = tab["g"], tab["T"]
    m = (G["day"] < before_day) & np.isin(G["stype"], ["reg", "conf"])
    tg = team_games(tab, m)
    net = fitres["net"]
    mem = tab["member"]
    order = np.argsort(-np.where(mem, net, -1e9))
    rank = np.empty(T, int)
    rank[order] = np.arange(1, T + 1)
    rank[~mem] = 400
    q = quadrant(rank[tg["opp"]], tg["venue"])
    w = np.bincount(tg["team"], weights=tg["win"], minlength=T)
    gp = np.bincount(tg["team"], minlength=T).astype(float)
    l = gp - w
    def cnt(mask):
        return np.bincount(tg["team"][mask], minlength=T).astype(float)
    q1w = cnt(tg["win"] & (q == 1))
    q1l = cnt(~tg["win"] & (q == 1))
    q2w = cnt(tg["win"] & (q == 2))
    q34l = cnt(~tg["win"] & (q >= 3))
    sos = np.bincount(tg["team"], weights=net[tg["opp"]], minlength=T) / np.maximum(gp, 1)
    confs = conf_of if conf_of is not None else tab["conf"]
    cm = {}
    for i, c in enumerate(confs):
        if c and mem[i]:
            cm.setdefault(c, []).append(net[i])
    conf_mean = np.array([np.mean(cm[c]) if c in cm else -10.0 for c in confs])
    rl = np.log(rank / (366.0 - np.minimum(rank, 365)))
    return {"rating": net.copy(), "rank": rank, "rank_logit": rl, "w": w, "l": l, "wpct": w / np.maximum(gp, 1),
            "wins": w, "q1w": q1w, "q1l": q1l, "q2w": q2w, "q34l": q34l, "sos": sos, "conf_mean": conf_mean}


def feature_matrix(res: dict, idx: np.ndarray) -> np.ndarray:
    return np.column_stack([res[k][idx] for k in FEATURES])


# ── models ──────────────────────────────────────────────────────────────────

def logit_fit(X: np.ndarray, y: np.ndarray, ridge: float = 1.0, iters: int = 60) -> np.ndarray:
    Xb = np.column_stack([np.ones(len(X)), X])
    b = np.zeros(Xb.shape[1])
    P = np.eye(Xb.shape[1]) * ridge
    P[0, 0] = 0.0
    for _ in range(iters):
        z = np.clip(Xb @ b, -30, 30)
        p = 1 / (1 + np.exp(-z))
        g = Xb.T @ (y - p) - P @ b
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + P
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return b


def fit_selection(rows: list[dict]) -> dict:
    """rows: per season {"X": features of eligible teams, "auto","in_field","seed"} -> model dict."""
    Xa = np.concatenate([r["X"] for r in rows])
    mu, sd = Xa.mean(0), Xa.std(0) + 1e-9
    na = np.concatenate([~r["auto"] for r in rows])
    yin = np.concatenate([r["in_field"] for r in rows]).astype(float)
    Z = (Xa - mu) / sd
    b_sel = logit_fit(Z[na], yin[na], ridge=1.0)
    inf = yin > 0
    seeds = np.concatenate([r["seed"] for r in rows]).astype(float)
    Zi = Z[inf]
    A = np.column_stack([np.ones(inf.sum()), Zi])
    reg = np.eye(A.shape[1]) * 1.0
    reg[0, 0] = 0
    b_seed = np.linalg.solve(A.T @ A + reg, A.T @ seeds[inf])
    return {"mu": mu.tolist(), "sd": sd.tolist(), "b_sel": b_sel.tolist(), "b_seed": b_seed.tolist(), "features": FEATURES}


def sel_score(model: dict, X: np.ndarray) -> np.ndarray:
    Z = (X - np.array(model["mu"])) / np.array(model["sd"])
    return np.column_stack([np.ones(len(Z)), Z]) @ np.array(model["b_sel"])


def seed_score(model: dict, X: np.ndarray) -> np.ndarray:
    Z = (X - np.array(model["mu"])) / np.array(model["sd"])
    return np.column_stack([np.ones(len(Z)), Z]) @ np.array(model["b_seed"])


def seed_lines(n_field: int) -> list[int]:
    """The seed of each S-curve position (64 slots: four per line); First Four pairs share a slot."""
    return [k // 4 + 1 for k in range(64)]


def build_field(teams_idx: np.ndarray, autos: np.ndarray, sel: np.ndarray, seedsc: np.ndarray, n_field: int,
                n_ff: int) -> dict:
    """One projected field from candidate team indices (eligible members), their auto flags, selection scores and
    predicted-seed scores. Returns {"field": [idx], "entries": [[idx] or [a, b]] (64, S-curve order), "seed": {idx: seed},
    "last_in": [..], "first_out": [..], "ff_pairs": [[a, b]]}."""
    auto_ids = teams_idx[autos]
    rest = np.where(~autos)[0]
    n_at = n_field - len(auto_ids)
    order = rest[np.argsort(-sel[rest])]
    at_ids = teams_idx[order[:max(n_at, 0)]]
    first_out = teams_idx[order[n_at:n_at + 4]].tolist()
    field = np.concatenate([auto_ids, at_ids])
    sc = {int(t): float(s) for t, s in zip(teams_idx, seedsc)}
    g_at = n_ff // 2                                  # First Four games between the last at-large teams
    g_auto = n_ff - g_at                              # ... and between the lowest automatic bids
    last_in = [int(t) for t in at_ids[max(0, len(at_ids) - 4):]]
    ff_at = [int(t) for t in at_ids[len(at_ids) - 2 * g_at:]] if g_at else []
    autos_sorted = sorted((int(t) for t in auto_ids), key=lambda t: sc[t])
    ff_auto = autos_sorted[len(autos_sorted) - 2 * g_auto:] if g_auto else []
    ranked = sorted((int(t) for t in field), key=lambda t: sc[t])
    entries: list[list[int]] = []
    used = set()
    ffa = sorted(ff_at, key=lambda t: sc[t])
    pairs_at = [ffa[i:i + 2] for i in range(0, len(ffa), 2)]
    ffu = sorted(ff_auto, key=lambda t: sc[t])
    pairs_auto = [ffu[i:i + 2] for i in range(0, len(ffu), 2)]
    pair_of = {}
    for p in pairs_at + pairs_auto:
        for t in p:
            pair_of[t] = p
    for t in ranked:
        if t in used:
            continue
        if t in pair_of:
            p = pair_of[t]
            entries.append(list(p))
            used.update(p)
        else:
            entries.append([t])
            used.add(t)
    entries = entries[:64]
    seed = {}
    for k, e in enumerate(entries):
        for t in e:
            seed[t] = k // 4 + 1
    return {"field": [int(t) for t in field], "entries": entries, "seed": seed, "last_in": last_in,
            "first_out": [int(t) for t in first_out], "ff_pairs": [p for p in pairs_at + pairs_auto if len(p) == 2]}


def regions_from_entries(entries: list[list[int]]) -> list[dict[int, list[int]]]:
    """S-curve snake: line k's four entries go to regions 0-3 (odd lines) or 3-0 (even lines). Returns 4 dicts
    {seed: entry}; semifinal pairs are regions (0, 3) and (1, 2) (overall #1's region meets #4's)."""
    regs = [dict() for _ in range(4)]
    for k, e in enumerate(entries):
        line, j = divmod(k, 4)
        r = j if line % 2 == 0 else 3 - j
        regs[r][line + 1] = e
    # bracket order: semis (0, 3) and (1, 2) -> positions [0, 3, 1, 2]
    return [regs[0], regs[3], regs[1], regs[2]]


# ── bracket simulation ──────────────────────────────────────────────────────

def bracket_arrays(regions: list[dict[int, list[int]]]) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """64 bracket positions -> team index (-1 where a First Four pair goes) and the First Four list
    [(position, a, b)]. Regions in bracket order (semis 0v1, 2v3)."""
    pos = np.full(64, -1, int)
    ff = []
    for r, reg in enumerate(regions):
        for k, sd in enumerate(SLOT_SEEDS):
            e = reg.get(sd) or reg.get(str(sd))
            p = r * 16 + k
            if not e:
                continue
            if len(e) == 1:
                pos[p] = e[0]
            else:
                ff.append((p, e[0], e[1]))
    return pos, ff


def win_prob(si: np.ndarray, sj: np.ndarray, ti: np.ndarray, tj: np.ndarray, P: float, prm: dict,
             home_i: np.ndarray | None = None) -> np.ndarray:
    pace = ti + tj - P
    mu = prm["s"] * (si - sj) * pace / 100.0
    if home_i is not None:
        mu = mu + prm["hca"] * home_i
    return norm.cdf(mu / prm["s0"])


def sim_bracket(pos: np.ndarray, ff: list, strength: np.ndarray, tempo: np.ndarray, P: float, prm: dict,
                rng: np.random.Generator, seeds_of: np.ndarray | None = None, host_hca: bool = False) -> dict:
    """pos: (64,) or (n, 64) team indices; ff: [(position, a, b)] (shared) or per-sim arrays via pos=-1 handled by
    `ff` arrays (n, k) [(pos, a, b)]; strength: (n, T). Returns {"reach": (T, 7) counts for R64..Champion,
    "champ": (n,) team index}."""
    n, T = strength.shape
    B = np.broadcast_to(pos, (n, 64)).copy() if pos.ndim == 1 else pos.copy()
    reach = np.zeros((T, 7))
    rows = np.arange(n)
    if ff:
        if isinstance(ff, list):
            for p, a, b in ff:
                pa = win_prob(strength[:, a], strength[:, b], tempo[a], tempo[b], P, prm)
                w = np.where(rng.random(n) < pa, a, b)
                B[:, p] = w
        else:
            fp, fa, fb = ff                                   # arrays (n, k)
            for k in range(fp.shape[1]):
                a, b = fa[:, k], fb[:, k]
                ok = a >= 0
                pa = win_prob(strength[rows, a], strength[rows, b], tempo[a], tempo[b], P, prm)
                w = np.where(rng.random(n) < pa, a, b)
                B[rows[ok], fp[ok, k]] = w[ok]
    def tally(col, arr):
        a = arr.ravel()
        np.add.at(reach[:, col], a[a >= 0], 1.0)
    tally(0, B)
    cur = B
    for rd in range(6):
        i, j = cur[:, 0::2], cur[:, 1::2]
        si = np.take_along_axis(strength, np.maximum(i, 0), 1)
        sj = np.take_along_axis(strength, np.maximum(j, 0), 1)
        home = None
        if host_hca and rd <= 1 and seeds_of is not None:
            # women's first and second rounds: a top-4 seed hosts on its own floor
            sdi, sdj = seeds_of[np.maximum(i, 0)], seeds_of[np.maximum(j, 0)]
            home = np.where(sdi <= 4, 1.0, 0.0) - np.where(sdj <= 4, 1.0, 0.0)
        p = win_prob(si, sj, tempo[np.maximum(i, 0)], tempo[np.maximum(j, 0)], P, prm, home)
        p = np.where(j < 0, 1.0, np.where(i < 0, 0.0, p))
        w = np.where(rng.random(p.shape) < p, i, j)
        tally(rd + 1, w)
        cur = w
    return {"reach": reach, "champ": cur[:, 0]}
