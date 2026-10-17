"""
Tournament simulation: Monte Carlo over the real bracket (knockout) or the round-robin format of the
ATP / WTA Finals, with the results so far fixed and the remaining matches priced by predict().

Knockout
--------
The DRAW's round-1 slots (`[[slot, pid|null, seed|null, entry]]`) are padded to a power of two. A slot
with no player is a bye, unless its entry is "Q" / "LL" (a qualifier or lucky loser not yet known):
that slot holds a placeholder priced as an average qualifier (QUALIFIER_LOGIT below the field's median).
Each finished match of the event (status done / ret / wo / def) fixes its bracket node's winner, and
because a later result implies the earlier ones, both players' earlier nodes are fixed as wins too (so
gaps in the data cannot eliminate a player who is known to have reached a later round). A player who
replaced someone in the draw (a lucky loser) is added when his results name him.

Each remaining match is won with P(i beats j) from predict.prob_matrix (exact chain, Elo + serve/return
blend). Optional strength uncertainty: every simulation draws a logit shift z_i ~ N(0, strength_sd^2) per
player (default STRENGTH_SD), so P = sigmoid(logit P_ij + z_i - z_j).

Outputs per player: p_title, p_final, p_sf, p_qf, reach {round: p} (being in that round), exp_points
(ranking points by exit round, from _points.table / canon; a bye followed by a loss earns first-round
points) and `next`: the player's next match with its interventional conditional odds. Sims in which the
player won the next match over-represent the weaker opponents and the favourable strength draws; each is
weighted by 1 / P(win | that sim's opponent and draws) (losses by 1 / P(loss | ...)), so the conditional
odds measure the match's own effect (the basketball season_sim fix).

Round robin (ATP / WTA Finals)
------------------------------
Two groups of four (event["groups"], else the RR results' pairings, else draw slots 1-4 and 5-8), every
pair plays once (best of 3, tiebreak in every set), the top two of each group reach the semi-finals
(A1 v B2, B1 v A2), then the final. Group order: wins; two tied -> head to head; three tied -> % of sets
won, then % of games won, then the better seed/rank, and whenever a criterion leaves exactly two tied
their head to head decides. Simulated set and game counts come from the chain: the match winner is drawn
with P, the 2-0 / 2-1 split from the chain's set-score distribution given the winner, and each set's
games from the set-score distribution given the set winner (first server averaged; sets independent).
Points: RR_win per round-robin win, SF_win, F_win.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, Iterable

import numpy as np

from oddsmarkets.tennis.models import _points
from oddsmarkets.tennis.models import match_chain as mc

logger = logging.getLogger(__name__)

N_SIMS = 20000
STRENGTH_SD = 0.0
QUALIFIER_LOGIT = 0.4               # a TBD qualifier is this far (logit) below the field median in every pairing
FINISHED = ("done", "ret", "wo", "def")
KO_ROUNDS = ("R128", "R64", "R32", "R16", "QF", "SF", "F")


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _pow2(n: int) -> int:
    k = 1
    while k < max(int(n), 2):
        k *= 2
    return k


def _matches_list(matches) -> list[dict]:
    if matches is None:
        return []
    if isinstance(matches, dict):
        return [m for m in matches.values() if isinstance(m, dict)]
    return [m for m in matches if isinstance(m, dict)]


# ── draw ─────────────────────────────────────────────────────────────────────

def draw_leaves(draw: dict) -> tuple[list, dict, int]:
    """(leaves [pid | None (bye) | "tbd:<slot>"], seeds {pid: seed}, size) from a DRAW."""
    slots = sorted((draw or {}).get("slots") or [], key=lambda s: int(s[0]))
    size = _pow2(max(int((draw or {}).get("size") or 0), len(slots), 2))
    leaves: list = [None] * size
    seeds: dict = {}
    base = min((int(s[0]) for s in slots), default=1)
    for s in slots:
        idx = int(s[0]) - base
        if not 0 <= idx < size:
            continue
        pid = s[1] if len(s) > 1 else None
        entry = s[3] if len(s) > 3 else None
        if pid:
            leaves[idx] = str(pid)
            if len(s) > 2 and s[2]:
                try:
                    seeds[str(pid)] = int(s[2])
                except (TypeError, ValueError):
                    pass
        elif entry in ("Q", "LL"):
            leaves[idx] = f"tbd:{s[0]}"
    return leaves, seeds, size


def bracket_from_results(matches) -> dict | None:
    """
    A DRAW reconstructed from a finished knockout's results (the tree of who met whom; byes where a
    player's first match is in a later round). None without a final.
    """
    ms = [m for m in _matches_list(matches) if str(m.get("round")) in KO_ROUNDS and m.get("winner")]
    final = [m for m in ms if m.get("round") == "F"]
    if not final:
        return None
    present = [r for r in KO_ROUNDS if any(m.get("round") == r for m in ms)]
    rounds = list(KO_ROUNDS[KO_ROUNDS.index(present[0]):])
    by = {}
    for m in ms:
        for p in (m.get("p1"), m.get("p2")):
            by[(str(p), m["round"])] = m

    def leaves_of(p: str, idx: int) -> list:
        if idx == 0:
            return [p]
        m = by.get((p, rounds[idx - 1]))
        if m is None:
            return [p] + [None] * (2 ** idx - 1)
        a, b = str(m["winner"]), str(m["p2"] if str(m["p1"]) == str(m["winner"]) else m["p1"])
        return leaves_of(a, idx - 1) + leaves_of(b, idx - 1)

    f = final[0]
    w = str(f["winner"])
    l_ = str(f["p2"] if str(f["p1"]) == w else f["p1"])
    R = len(rounds) - 1
    leaves = leaves_of(w, R) + leaves_of(l_, R)
    return {"size": len(leaves), "slots": [[i + 1, p, None, None] for i, p in enumerate(leaves)]}


# ── pricing ──────────────────────────────────────────────────────────────────

def _prob_fn(event: dict, tour: str, ctx=None) -> Callable[[list[str]], np.ndarray]:
    from oddsmarkets.tennis.models import predict as P
    bo = 5 if int(event.get("best_of") or 3) == 5 else 3
    yr = int(event.get("year") or (str(event.get("start") or "2026")[:4]))
    rule = event.get("final_set_rule") or P.default_final_rule(event.get("level"), bo, yr, event.get("tid"))
    c = ctx or P.context(tour, event.get("start"))

    def f(pids):
        return P.prob_matrix(c, pids, event.get("surface") or "hard", bo, event.get("level") or "250", rule)
    return f


def _logit_matrix(pids: list[str], prob) -> np.ndarray:
    """Logit matrix over real players; TBD placeholders priced QUALIFIER_LOGIT below the median player."""
    real = [p for p in pids if not str(p).startswith("tbd:")]
    n = len(pids)
    L = np.zeros((n, n))
    if real:
        Pm = np.asarray(prob(real), float)
        Lr = _logit(Pm)
        np.fill_diagonal(Lr, 0.0)
        ix = [i for i, p in enumerate(pids) if not str(p).startswith("tbd:")]
        L[np.ix_(ix, ix)] = Lr
        # a placeholder plays like the median real player minus QUALIFIER_LOGIT
        med = np.median(Lr, axis=1) if len(real) > 1 else np.zeros(len(real))
        for t, p in enumerate(pids):
            if str(p).startswith("tbd:"):
                for k, i in enumerate(ix):
                    L[i, t] = med[k] + QUALIFIER_LOGIT
                    L[t, i] = -L[i, t]
    return L


# ── knockout core ────────────────────────────────────────────────────────────

def knockout(L: np.ndarray, leaf_idx: np.ndarray, fixed: dict, n: int, rng: np.random.Generator,
             z: np.ndarray | None = None) -> list[np.ndarray]:
    """
    occ[r] (n, S / 2^r): the players in round r (r = 0 first round); the last entry (n, 1) is the champion.
    `leaf_idx` (S,) or per simulation (n, S); `fixed` {(r, m): winner index}; -1 marks a bye / empty node.
    """
    occ = [np.asarray(leaf_idx) if np.ndim(leaf_idx) == 2 else np.tile(leaf_idx, (n, 1))]
    rows = np.arange(n)[:, None]
    r = 0
    while occ[-1].shape[1] > 1:
        cur = occ[-1]
        a, b = cur[:, 0::2], cur[:, 1::2]
        aa, bb = np.maximum(a, 0), np.maximum(b, 0)
        lg = L[aa, bb]
        if z is not None:
            lg = lg + z[rows, aa] - z[rows, bb]
        u = rng.random(a.shape)
        w = np.where(u < _sig(lg), a, b)
        w = np.where(a < 0, b, np.where(b < 0, a, w))
        for (fr, m), widx in fixed.items():
            if fr == r and m < w.shape[1]:
                w[:, m] = widx
        occ.append(w)
        r += 1
    return occ


def _fix_results(ms: list[dict], leaves: list, rnames: list[str], pids: list[str]) -> tuple[dict, set]:
    """{(r, m): winner index} from finished matches; eliminated pids."""
    pos = {p: i for i, p in enumerate(leaves) if p}
    idx = {p: i for i, p in enumerate(pids)}
    fixed: dict = {}
    out = set()
    for m in sorted(ms, key=lambda m: rnames.index(m["round"]) if m.get("round") in rnames else 99):
        if m.get("round") not in rnames or m.get("status") not in FINISHED or not m.get("winner"):
            continue
        r = rnames.index(m["round"])
        w = str(m["winner"])
        l_ = str(m["p2"] if str(m["p1"]) == w else m["p1"])
        slot = pos.get(w, pos.get(l_))
        if slot is None or w not in idx:
            continue
        node = slot >> (r + 1)
        fixed[(r, node)] = idx[w]
        out.add(l_)
        # earlier rounds: both players won their way here
        for p in (w, l_):
            if p in pos and p in idx:
                for rr in range(r):
                    k = (rr, pos[p] >> (rr + 1))
                    fixed.setdefault(k, idx[p])
    return fixed, out


def _ko_simulate(event: dict, ms: list[dict], prob, n: int, seed: int, strength_sd: float, points: dict,
                 conditional: bool) -> dict:
    t0 = time.perf_counter()
    leaves, seeds, S = draw_leaves(event.get("draw") or {})
    rnames = _points.round_names(S)
    pos = {p: i for i, p in enumerate(leaves) if p}
    # lucky losers / replacements named by first-round results: they take the slot opposite their opponent
    # when that slot's listed player never appears in the event's results
    named = {str(x.get("p1")) for x in ms} | {str(x.get("p2")) for x in ms}
    for m in ms:
        if m.get("round") != rnames[0]:
            continue
        a, b = str(m.get("p1")), str(m.get("p2"))
        for x, y in ((a, b), (b, a)):
            if x in pos and y not in pos:
                j = pos[x] ^ 1
                if leaves[j] is None or str(leaves[j]).startswith("tbd:") or leaves[j] not in named:
                    pos.pop(leaves[j], None)
                    leaves[j] = y
                    pos[y] = j
    pids = [p for p in leaves if p]
    if len(pids) < 2:
        return {"ok": False, "reason": "draw has fewer than two players", "players": {}}
    idx = {p: i for i, p in enumerate(pids)}
    leaf_idx = np.array([idx[p] if p else -1 for p in leaves])
    L = _logit_matrix(pids, prob)
    fixed, elim = _fix_results(ms, leaves, rnames, pids)
    rng = np.random.default_rng(seed)
    P_ = len(pids)
    z = rng.normal(0, strength_sd, (n, P_)) if strength_sd > 0 else None
    occ = knockout(L, leaf_idx, fixed, n, rng, z)
    R = len(rnames)
    reach = np.zeros((R + 1, P_))
    present = []
    for r in range(R + 1):
        o = occ[r]
        pres = np.zeros((n, P_), bool)
        valid = o >= 0
        rr_, cc_ = np.nonzero(valid)
        pres[rr_, o[valid]] = True
        present.append(pres)
        reach[r] = pres.mean(0)
    exitr = np.stack(present, 0).sum(0) - 1                    # (n, P): index of the round lost in; R = champion
    # byes: a first-round opponent slot that is empty
    had_bye = np.zeros(P_, bool)
    for p, i in pos.items():
        if p in idx and leaves[i ^ 1] is None:
            had_bye[idx[p]] = True
    labels = rnames + ["W"]
    pts_by_exit = np.array([float(points.get(lab, 0.0)) for lab in labels])
    pts = pts_by_exit[np.clip(exitr, 0, R)]
    # a bye then a loss in the first match played: first-round points
    bye_loss = had_bye[None, :] & (exitr == 1)
    pts = np.where(bye_loss, float(points.get(rnames[0], 0.0)), pts)
    pts = np.where(exitr < 0, 0.0, pts)
    exp_pts = pts.mean(0)
    players = {}
    for p, i in idx.items():
        rd = {rnames[r]: round(float(reach[r, i]), 5) for r in range(R)}
        rd["W"] = round(float(reach[R, i]), 5)
        players[p] = {"p_title": rd["W"], "p_final": rd.get("F", 0.0), "p_sf": rd.get("SF", 0.0), "p_qf": rd.get("QF", 0.0),
                      "reach": rd, "exp_points": round(float(exp_pts[i]), 2), "seed": seeds.get(p),
                      "eliminated": p in elim, "slot": pos.get(p)}
    # fixed / upcoming matches with known players
    matches_out = {}
    upcoming = {(frozenset((str(m.get("p1")), str(m.get("p2")))), m.get("round")): m.get("id") for m in ms
                if m.get("status") not in FINISHED}
    for r in range(R):
        o = occ[r]
        for m in range(o.shape[1] // 2):
            if (r, m) in fixed:
                continue
            a, b = o[:, 2 * m], o[:, 2 * m + 1]
            if (a == a[0]).all() and (b == b[0]).all() and a[0] >= 0 and b[0] >= 0:
                pa, pb = pids[a[0]], pids[b[0]]
                key = f"{rnames[r]}:{m}"
                matches_out[key] = {"round": rnames[r], "node": m, "p1": pa, "p2": pb,
                                    "p1_win": round(float(_sig(L[a[0], b[0]])), 5),
                                    "mid": upcoming.get((frozenset((pa, pb)), rnames[r]))}
    # interventional conditional odds on the next match
    if conditional:
        champ = occ[R][:, 0]
        final_pres = present[R - 1] if R >= 1 else None
        rows = np.arange(n)
        for p, i in idx.items():
            if p in elim or p not in pos:
                continue
            slot = pos[p]
            nxt = None
            for r in range(R):
                if (r, slot >> (r + 1)) in fixed:
                    continue
                nd = slot >> (r + 1)
                other = occ[r][:, 2 * nd + 1] if (slot >> r) % 2 == 0 else occ[r][:, 2 * nd]
                if (other < 0).all():                       # a bye
                    continue
                nxt = r
                break
            if nxt is None:
                continue
            node = slot >> (nxt + 1)
            o = occ[nxt]
            a, b = o[:, 2 * node], o[:, 2 * node + 1]
            plays = (a == i) | (b == i)
            opp = np.where(a == i, b, a)
            plays &= opp >= 0
            if not plays.any():
                continue
            won = occ[nxt + 1][:, node] == i
            oo = np.maximum(opp, 0)
            lg = L[i, oo]
            if z is not None:
                lg = lg + z[rows, i] - z[rows, oo]
            pw = np.clip(_sig(lg), 1e-4, 1 - 1e-4)
            wsel, lsel = plays & won, plays & ~won
            ww = 1.0 / pw
            title = (champ == i).astype(float)
            fin = final_pres[:, i].astype(float) if final_pres is not None else title
            ifw = {}
            if wsel.any():
                W = ww[wsel].sum()
                ifw = {"p_title": round(float((title[wsel] * ww[wsel]).sum() / W), 5),
                       "p_final": round(float((fin[wsel] * ww[wsel]).sum() / W), 5)}
            opps, cnt = np.unique(opp[plays], return_counts=True)
            od = sorted(((pids[o_], c / plays.sum()) for o_, c in zip(opps, cnt)), key=lambda x: -x[1])[:5]
            players[p]["next"] = {"round": rnames[nxt], "p_play": round(float(plays.mean()), 5),
                                  "p_win": round(float(pw[plays].mean()), 5),
                                  "opponents": {o_: round(float(c), 4) for o_, c in od},
                                  "if_win": ifw, "if_loss": {"p_title": 0.0, "p_final": 0.0} if lsel.any() else {}}
    return {"ok": True, "format": "knockout", "size": S, "rounds": rnames, "players": players, "matches": matches_out,
            "n_sims": n, "strength_sd": strength_sd, "points_table": points, "fixed_nodes": len(fixed),
            "runtime_s": round(time.perf_counter() - t0, 3), "_exit": exitr, "_pids": pids, "_points": pts}


# ── round robin (Finals) ─────────────────────────────────────────────────────

def _groups(event: dict, ms: list[dict]) -> dict[str, list[str]]:
    g = event.get("groups")
    if isinstance(g, dict) and g:
        return {str(k): [str(x) for x in v] for k, v in g.items()}
    rr = [m for m in ms if m.get("round") == "RR"]
    if rr:
        adj: dict = {}
        for m in rr:
            a, b = str(m["p1"]), str(m["p2"])
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        seen, comps = set(), []
        for p in sorted(adj):
            if p in seen:
                continue
            stack, comp = [p], []
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.append(x)
                stack.extend(adj[x] - seen)
            comps.append(sorted(comp))
        if len(comps) == 2 and all(len(c) == 4 for c in comps):
            return {"A": comps[0], "B": comps[1]}
    leaves, _, _ = draw_leaves(event.get("draw") or {})
    pl = [p for p in leaves if p]
    return {"A": pl[:4], "B": pl[4:8]}


def rr_order(wins, sw, sl, gw, gl, h2h, tie_rank) -> list[int]:
    """Group order (indices) for one simulation: wins; h2h for two; sets %, games %, rank for three+."""
    n = len(wins)

    def pct(w, l):
        return w / (w + l) if (w + l) > 0 else 0.0

    def resolve(group: list[int]) -> list[int]:
        if len(group) <= 1:
            return group
        if len(group) == 2:
            a, b = group
            if h2h[a][b] > h2h[b][a]:
                return [a, b]
            if h2h[b][a] > h2h[a][b]:
                return [b, a]
            return sorted(group, key=lambda i: tie_rank[i])
        for key in (lambda i: pct(sw[i], sl[i]), lambda i: pct(gw[i], gl[i])):
            vals = {i: round(key(i), 12) for i in group}
            levels = sorted(set(vals.values()), reverse=True)
            if len(levels) > 1:
                out = []
                for v in levels:
                    out += resolve([i for i in group if vals[i] == v])
                return out
        return sorted(group, key=lambda i: tie_rank[i])

    out = []
    for w in sorted(set(wins), reverse=True):
        out += resolve([i for i in range(n) if wins[i] == w])
    return out


def _set_sampler(pa: float, pb: float):
    """Per set: score lists for player-1 set wins and losses with probabilities (first server averaged)."""
    d0 = mc.set_dist(pa, pb, 0, "tb7")
    d1 = mc.set_dist(pa, pb, 1, "tb7")
    sc = {k: 0.5 * float(np.ravel(d0.get(k, 0))[0]) + 0.5 * float(np.ravel(d1.get(k, 0))[0]) for k in set(d0) | set(d1)}
    win = [(k, v) for k, v in sc.items() if k[0] > k[1]]
    los = [(k, v) for k, v in sc.items() if k[1] > k[0]]
    pw = sum(v for _, v in win)
    return ([k for k, _ in win], np.array([v for _, v in win]) / pw,
            [k for k, _ in los], np.array([v for _, v in los]) / (1 - pw))


def _rr_simulate(event: dict, ms: list[dict], prob, n: int, seed: int, strength_sd: float, points: dict,
                 conditional: bool, tour: str, psrv_fn=None) -> dict:
    t0 = time.perf_counter()
    groups = _groups(event, ms)
    pids = [p for g in groups.values() for p in g]
    if len(pids) < 4:
        return {"ok": False, "reason": "round robin needs groups of players", "players": {}}
    idx = {p: i for i, p in enumerate(pids)}
    P_ = len(pids)
    L = _logit_matrix(pids, prob)
    Pm = _sig(L)
    rng = np.random.default_rng(seed)
    z = rng.normal(0, strength_sd, (n, P_)) if strength_sd > 0 else None
    seeds = {}
    for s in ((event.get("draw") or {}).get("slots") or []):
        if len(s) > 2 and s[1] and s[2]:
            seeds[str(s[1])] = int(s[2])
    tie_rank = np.array([seeds.get(p, 100 + i) for i, p in enumerate(pids)])
    # serve-point probabilities per pair (for set / game counts)
    from oddsmarkets.tennis.models import predict as Pr
    base = Pr.BASE_SPW["wta" if tour == "wta" else "atp"][(event.get("surface") or "hard") if (event.get("surface") or "hard") in ("hard", "clay", "grass") else "hard"]
    W = np.zeros((n, P_), int)
    SW, SL, GW, GL = (np.zeros((n, P_), int) for _ in range(4))
    H2H = np.zeros((n, P_, P_), np.int8)
    done_rr = {}
    for m in ms:
        if m.get("round") == "RR" and m.get("status") in FINISHED and m.get("winner"):
            a, b = str(m["p1"]), str(m["p2"])
            if a in idx and b in idx:
                done_rr[frozenset((a, b))] = m
    rows = np.arange(n)
    next_rr: dict = {}
    upcoming_order = sorted([m for m in ms if m.get("round") == "RR" and m.get("status") not in FINISHED],
                            key=lambda m: (str(m.get("date") or "9999"), str(m.get("id"))))
    for m in upcoming_order:
        for p in (str(m.get("p1")), str(m.get("p2"))):
            if p in idx and p not in next_rr:
                next_rr[p] = frozenset((str(m["p1"]), str(m["p2"])))
    pair_draws = {}
    for gname, g in groups.items():
        for x in range(len(g)):
            for y in range(x + 1, len(g)):
                a, b = g[x], g[y]
                i, j = idx[a], idx[b]
                key = frozenset((a, b))
                if key in done_rr:
                    m = done_rr[key]
                    wpid = str(m["winner"])
                    wi, li = idx[wpid], idx[b if wpid == a else a]
                    sets = m.get("sets") or ([[6, 0], [6, 0]] if m.get("status") == "wo" else [])
                    p1_is_w = str(m["p1"]) == wpid
                    sw_ = sl_ = gw_ = gl_ = 0
                    for s in sets:
                        x1, x2 = int(s[0]), int(s[1])
                        if not p1_is_w:
                            x1, x2 = x2, x1
                        gw_ += x1
                        gl_ += x2
                        sw_ += x1 > x2
                        sl_ += x2 > x1
                    W[:, wi] += 1
                    SW[:, wi] += sw_; SL[:, wi] += sl_; GW[:, wi] += gw_; GL[:, wi] += gl_
                    SW[:, li] += sl_; SL[:, li] += sw_; GW[:, li] += gl_; GL[:, li] += gw_
                    H2H[:, wi, li] = 1
                    continue
                lg = L[i, j] + (z[:, i] - z[:, j] if z is not None else 0.0)
                pw = np.broadcast_to(_sig(lg), (n,)).copy()
                won = rng.random(n) < pw
                pair_draws[key] = (i, j, won, pw)
                # serve-point probabilities consistent with P(i beats j)
                if psrv_fn is not None:
                    try:
                        pa, pb = psrv_fn(a, b)
                    except Exception:  # noqa: BLE001
                        pa, pb = base, base
                else:
                    pa, pb = base, base
                dlt = float(mc.solve_shift(Pm[i, j], pa, pb, 3, "tb7")[0])
                pa, pb = pa + dlt, pb - dlt
                dist = mc.match(pa, pb, 3, "tb7")
                p20 = dist["sets"]["2-0"] / max(dist["p1_win"], 1e-9)
                p02 = dist["sets"]["0-2"] / max(dist["p2_win"], 1e-9)
                wk, wp, lk, lp = _set_sampler(pa, pb)
                straight = rng.random(n) < np.where(won, p20, p02)
                # sets: winner's sets 2, loser 0 or 1
                si = np.where(won, 2, np.where(straight, 0, 1))
                sj = np.where(won, np.where(straight, 0, 1), 2)
                nsets = si + sj
                gi = np.zeros(n, int)
                gj = np.zeros(n, int)
                loser_set = rng.integers(0, 2, n)           # in a 2-1, the loser's set is the first or the second
                for k in range(3):
                    active = k < nsets
                    if k == 2:
                        i_set = won
                    else:
                        i_set = np.where(straight, won, np.where(loser_set == k, ~won, won))
                    ws = rng.choice(len(wk), n, p=wp)
                    ls = rng.choice(len(lk), n, p=lp)
                    a_g = np.where(i_set, np.array([s[0] for s in wk])[ws], np.array([s[0] for s in lk])[ls])
                    b_g = np.where(i_set, np.array([s[1] for s in wk])[ws], np.array([s[1] for s in lk])[ls])
                    gi += np.where(active, a_g, 0)
                    gj += np.where(active, b_g, 0)
                W[:, i] += won
                W[:, j] += ~won
                SW[:, i] += si; SL[:, i] += sj; SW[:, j] += sj; SL[:, j] += si
                GW[:, i] += gi; GL[:, i] += gj; GW[:, j] += gj; GL[:, j] += gi
                H2H[:, i, j] = won
                H2H[:, j, i] = ~won
    # group order per simulation
    first = {}
    second = {}
    for gname, g in groups.items():
        gi_ = [idx[p] for p in g]
        f_arr = np.zeros(n, int)
        s_arr = np.zeros(n, int)
        Wg, SWg, SLg, GWg, GLg = W[:, gi_], SW[:, gi_], SL[:, gi_], GW[:, gi_], GL[:, gi_]
        Hg = H2H[:, gi_][:, :, gi_]
        tr = tie_rank[gi_]
        cache: dict = {}
        for s in range(n):
            key = (tuple(Wg[s]), tuple(SWg[s]), tuple(SLg[s]), tuple(GWg[s]), tuple(GLg[s]), Hg[s].tobytes())
            o = cache.get(key)
            if o is None:
                o = rr_order(Wg[s], SWg[s], SLg[s], GWg[s], GLg[s], Hg[s], tr)
                cache[key] = o
            f_arr[s], s_arr[s] = gi_[o[0]], gi_[o[1]]
        first[gname], second[gname] = f_arr, s_arr
    gnames = list(groups)
    A, Bn = gnames[0], gnames[1] if len(gnames) > 1 else gnames[0]

    def play(a, b):
        lg = L[a, b] + (z[rows, a] - z[rows, b] if z is not None else 0.0)
        return np.where(rng.random(n) < _sig(lg), a, b)
    sf1 = (first[A], second[Bn])
    sf2 = (first[Bn], second[A])
    f1, f2 = play(*sf1), play(*sf2)
    champ = play(f1, f2)
    in_sf = np.zeros((n, P_), bool)
    for arr in (first[A], second[A], first[Bn], second[Bn]):
        in_sf[rows, arr] = True
    in_f = np.zeros((n, P_), bool)
    in_f[rows, f1] = True
    in_f[rows, f2] = True
    is_c = np.zeros((n, P_), bool)
    is_c[rows, champ] = True
    gw_ = np.zeros((n, P_), bool)
    gw_[rows, first[A]] = True
    gw_[rows, first[Bn]] = True
    pts = W * points.get("RR_win", 200.0) + in_f * points.get("SF_win", 400.0) + is_c * points.get("F_win", 500.0)
    players = {}
    for p, i in idx.items():
        players[p] = {"p_title": round(float(is_c[:, i].mean()), 5), "p_final": round(float(in_f[:, i].mean()), 5),
                      "p_sf": round(float(in_sf[:, i].mean()), 5), "p_qf": 1.0,
                      "p_group_winner": round(float(gw_[:, i].mean()), 5),
                      "reach": {"RR": 1.0, "SF": round(float(in_sf[:, i].mean()), 5), "F": round(float(in_f[:, i].mean()), 5),
                                "W": round(float(is_c[:, i].mean()), 5)},
                      "exp_rr_wins": round(float(W[:, i].mean()), 4), "exp_points": round(float(pts[:, i].mean()), 2),
                      "group": next(g for g, v in groups.items() if p in v), "seed": seeds.get(p)}
    if conditional:
        for p, i in idx.items():
            key = next_rr.get(p)
            if key is None:
                key = next((k for k in pair_draws if p in k), None)
            if key is None or key not in pair_draws:
                continue
            a, b, won_a, pw_a = pair_draws[key]
            won = won_a if a == i else ~won_a
            pw = np.clip(pw_a if a == i else 1 - pw_a, 1e-4, 1 - 1e-4)
            out = {}
            for lab, sel, wts in (("if_win", won, 1.0 / pw), ("if_loss", ~won, 1.0 / (1 - pw))):
                if sel.any():
                    Wt = wts[sel].sum()
                    out[lab] = {"p_sf": round(float((in_sf[sel, i] * wts[sel]).sum() / Wt), 5),
                                "p_title": round(float((is_c[sel, i] * wts[sel]).sum() / Wt), 5)}
            opp = pids[b if a == i else a]
            players[p]["next"] = {"round": "RR", "opponents": {opp: 1.0}, "p_play": 1.0, "p_win": round(float(pw.mean()), 5), **out}
    exitr = np.where(is_c, 3, np.where(in_f, 2, np.where(in_sf, 1, 0)))
    return {"ok": True, "format": "round_robin", "groups": groups, "players": players, "matches": {},
            "n_sims": n, "strength_sd": strength_sd, "points_table": points,
            "runtime_s": round(time.perf_counter() - t0, 3), "_exit": exitr, "_pids": pids, "_points": pts}


# ── public ───────────────────────────────────────────────────────────────────

def is_round_robin(event: dict, ms: list[dict] | None = None) -> bool:
    if str(event.get("level")) == "finals":
        return True
    return any(m.get("round") == "RR" for m in (ms or []))


def simulate(event: dict, n: int = N_SIMS, matches: Any = None, tour: str | None = None, ctx=None,
             prob: Callable[[list[str]], np.ndarray] | None = None, seed: int = 0, strength_sd: float = STRENGTH_SD,
             points: dict | None = None, conditional: bool = True, keep_sims: bool = False, psrv_fn=None) -> dict:
    """
    Contract: {"players": {pid: {"p_title","p_final","p_sf","p_qf","reach": {round: p},"exp_points", "next"...}},
    "matches": {...}, "format", "n_sims", "runtime_s"}. `matches` are the event's MATCH rows (results fixed);
    `prob(pids) -> P` overrides predict.prob_matrix. With keep_sims the per-simulation exits ("_exit": (n, P)
    round index lost in, last = champion) and points ("_points") stay in the result (season_sim).
    """
    tour = (tour or event.get("tour") or "atp").lower()
    ms = [m for m in _matches_list(matches) if (not event.get("id") or not m.get("event") or m.get("event") == event.get("id"))]
    try:
        prob = prob or _prob_fn(event, tour, ctx)
        lvl = str(event.get("level") or "250")
        if points is None:
            yr = int(event.get("year") or str(event.get("start") or "2026")[:4])
            points = _points.table(tour, lvl, event.get("draw_size"), yr)
        if is_round_robin(event, ms):
            if "RR_win" not in points:
                points = _points.table(tour, "finals")
            out = _rr_simulate(event, ms, prob, n, seed, strength_sd, points, conditional, tour, psrv_fn)
        else:
            out = _ko_simulate(event, ms, prob, n, seed, strength_sd, points, conditional)
    except Exception as exc:  # noqa: BLE001
        logger.exception("tournament simulate failed")
        return {"ok": False, "reason": f"error: {exc}", "players": {}}
    out["event"] = event.get("id")
    if not keep_sims:
        for k in ("_exit", "_pids", "_points"):
            out.pop(k, None)
    return out
