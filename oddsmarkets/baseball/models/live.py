"""
Live win probability from the game state, using the pre-game model's team strengths for what remains.

Method (exact Markov chain, milliseconds per state)
---------------------------------------------------
For each batting team and pitching phase (starter still in / bullpen) the pre-game spec gives a PA outcome
vector q (the lineup's average of game_sim.prob_table rows: starter rows at his current times through the
order, bullpen rows afterwards). With the same base-out tables as the simulator (a running transition, then
the PA transition), the distribution of runs scored from (outs, bases) to the end of the half inning,
F[o, b, r], solves the fixed point

    F[o, b] = sum_running sum_events q_e sum_k T(.) shift_r( F[o', b'] or delta_0 when o' >= 3 )

(value iteration; base states can cycle, outs never decrease). The game value then follows by backward
recursion over half innings on the run differential d = home - away:

    top of inning i:     W_t(i, d) = sum_r A(r) [ 1 if i >= 9 and d - r > 0 else W_b(i, d - r) ]
    bottom of inning i:  W_b(i, d) = sum_r H(r) W_t(i + 1, d + r)                     (i < 9)
                         W_b(i, d) = P(d + r > 0) + P(d + r = 0) W_t(i + 1, 0)         (i >= 9: walk-off)

with extra half innings starting from a runner on second when the automatic-runner rule applies, and
W = 0.5 / 1 / 0 for a tie / lead / deficit after the 30th inning. A state in mid-half-inning uses
F[outs, bases] for the rest of that half; the PA in progress uses the count multipliers (game_sim.COUNT_MULT).

`live_sim` runs the full simulator from the state instead (lineup position, the starter's pitch count and the
exit model), slower but richer; `win_prob` is the default for refreshes during games.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from oddsmarkets.baseball.models import game_sim as G
from oddsmarkets.baseball.models._dio import NE

R = 25                 # run support of a half inning
D = 30                 # |run differential| support
MAX_INN = 30


def _probs_from_cum(cum: np.ndarray) -> np.ndarray:
    return np.diff(np.concatenate([np.zeros(cum.shape[:-1] + (1,)), cum], axis=-1), axis=-1)


def _chain(q: np.ndarray, trans: G.Transitions):
    """Flattened one-PA operator: (state, next state, runs, weight) and terminal (state, runs, weight)."""
    pt = _probs_from_cum(trans.cum)            # [NE, 8, 3, K]
    pr = _probs_from_cum(trans.run_cum)[0]     # [8, 3, K]
    S, S2, RR, W = [], [], [], []
    TS, TR, TW = [], [], []
    for o in range(3):
        for b in range(8):
            s = o * 8 + b
            for k in range(pr.shape[-1]):
                w = pr[b, o, k]
                if w <= 0:
                    continue
                b1, r1, o1 = int(trans.run_nb[0, b, o, k]), int(trans.run_runs[0, b, o, k]), o + int(trans.run_douts[0, b, o, k])
                if o1 >= 3:
                    TS.append(s); TR.append(r1); TW.append(w)
                    continue
                for e in range(NE):
                    if q[e] <= 0:
                        continue
                    for kk in range(pt.shape[-1]):
                        p = pt[e, b1, o1, kk]
                        if p <= 0:
                            continue
                        nb, r2, d2 = int(trans.nb[e, b1, o1, kk]), int(trans.runs[e, b1, o1, kk]), int(trans.douts[e, b1, o1, kk])
                        if o1 + d2 >= 3:
                            TS.append(s); TR.append(r1 + r2); TW.append(w * q[e] * p)
                        else:
                            S.append(s); S2.append((o1 + d2) * 8 + nb); RR.append(r1 + r2); W.append(w * q[e] * p)
    return (np.array(S), np.array(S2), np.minimum(np.array(RR), R - 1), np.array(W),
            np.array(TS), np.minimum(np.array(TR), R - 1), np.array(TW))


def half_inning(q: np.ndarray, trans: G.Transitions | None = None, first_mult: np.ndarray | None = None,
                tol: float = 1e-12, max_iter: int = 200) -> np.ndarray:
    """F[o, b, r]: runs scored from (outs o, bases b) to the end of the half inning, PA vector q."""
    trans = trans or G.transitions()
    q = np.asarray(q, float) / np.sum(q)
    j = np.arange(R)

    def op(qv):
        S, S2, RR, W, TS, TR, TW = _chain(qv, trans)
        src = j[None, :] - RR[:, None]
        ok = src >= 0
        term = np.zeros((24, R))
        np.add.at(term, (TS, TR), TW)

        def apply(F):
            Ff = F.reshape(24, R)
            g = np.where(ok, Ff[S2[:, None], np.clip(src, 0, R - 1)], 0.0) * W[:, None]
            out = term.copy()
            np.add.at(out, S, g)
            return out.reshape(3, 8, R)
        return apply

    step = op(q)
    F = np.zeros((3, 8, R))
    F[..., 0] = 1.0
    for _ in range(max_iter):
        F2 = step(F)
        if np.abs(F2 - F).max() < tol:
            F = F2
            break
        F = F2
    if first_mult is not None:
        q1 = q * first_mult
        F = op(q1 / q1.sum())(F)            # the in-progress PA with its count, then the converged chain
    return F


def game_values(A: dict, H: dict, auto_runner: bool, innings: int = 9) -> tuple[np.ndarray, np.ndarray]:
    """
    (Wt, Wb) [MAX_INN + 2, 2D + 1]: P(home wins) at the start of the top / bottom of inning i with differential d.
    A, H: {"start": runs dist from (0 outs, empty), "xtra": runs dist from (0 outs, runner on 2nd)} per batting team
    (each may also carry an "early"/"late" phase pair; see team_dists).
    """
    n = 2 * D + 1
    ds = np.arange(-D, D + 1)
    Wt = np.zeros((MAX_INN + 2, n))
    Wb = np.zeros((MAX_INN + 2, n))
    Wt[MAX_INN + 1] = np.where(ds > 0, 1.0, np.where(ds < 0, 0.0, 0.5))
    for i in range(MAX_INN, 0, -1):
        xtra = i > innings and auto_runner
        a = A["xtra" if xtra else "start"](i)
        h = H["xtra" if xtra else "start"](i)
        # bottom
        wb = np.zeros(n)
        for j, d in enumerate(ds):
            if i >= innings:
                tot = 0.0
                for r in range(R):
                    nd = d + r
                    if nd > 0:
                        tot += h[r]
                    elif nd == 0:
                        tot += h[r] * Wt[i + 1, D]
                wb[j] = tot
            else:
                idx = np.clip(d + np.arange(R) + D, 0, n - 1)
                wb[j] = np.dot(h, Wt[i + 1, idx])
        Wb[i] = wb
        wt = np.zeros(n)
        for j, d in enumerate(ds):
            nd = d - np.arange(R)
            idx = np.clip(nd + D, 0, n - 1)
            vals = np.where((i >= innings) & (nd > 0), 1.0, Wb[i, idx])
            wt[j] = np.dot(a, vals)
        Wt[i] = wt
    return Wt, Wb


def team_vectors(spec: dict) -> dict:
    """{"away": {"starter": q, "bullpen": q}, "home": {...}}: lineup-average PA vectors from the spec."""
    P = G.prob_table(spec)
    out = {}
    for t, side in ((0, "away"), (1, "home")):
        out[side] = {"starter": P[t, :, 0:3].mean(axis=(0, 1)), "bullpen": P[t, :, 3:5].mean(axis=(0, 1))}
    return out


class LiveModel:
    """Precomputes the half-inning run distributions for a game spec; `win_prob(state)` is then cheap."""

    def __init__(self, spec: dict, starter_innings: float = 5.5):
        self.spec = spec
        self.trans = G.transitions(spec.get("level", "mlb"))
        self.auto = bool(spec.get("auto_runner", False))
        self.inn = int(spec.get("innings", 9))
        self.vec = team_vectors(spec)
        self.F = {side: {ph: half_inning(v, self.trans) for ph, v in d.items()} for side, d in self.vec.items()}
        self.si = starter_innings

    def _phase(self, i: int, starter_in: bool | None = None) -> str:
        if starter_in is False:
            return "bullpen"
        return "starter" if i <= int(self.si) else "bullpen"

    def _dists(self, side: str):
        F = self.F[side]

        def start(i):
            return F[self._phase(i)][0, 0]

        def xtra(i):
            return F["bullpen"][0, 2]
        return {"start": start, "xtra": xtra}

    def values(self):
        if not hasattr(self, "_W"):
            self._W = game_values(self._dists("away"), self._dists("home"), self.auto, self.inn)
        return self._W

    def win_prob(self, state: dict) -> float:
        """state: inning, top (bool), outs, bases (bitmask), score [away, home], count [b, s] (optional),
        sp_in [away, home] (optional: starter still pitching for that team)."""
        Wt, Wb = self.values()
        i = int(state.get("inning", 1))
        top = bool(state.get("top", True))
        o = int(state.get("outs", 0))
        b = int(state.get("bases", 0))
        sa, sh = (int(x) for x in state.get("score", [0, 0]))
        d = sh - sa
        if o >= 3:                                    # between halves
            if top:
                if i >= self.inn and d > 0:
                    return 1.0
                return float(Wb[i, np.clip(d + D, 0, 2 * D)])
            if i >= self.inn and d != 0:
                return float(d > 0)
            return float(Wt[min(i + 1, MAX_INN + 1), np.clip(d + D, 0, 2 * D)])
        side = "away" if top else "home"
        sp_in = state.get("sp_in")
        fld = 1 if top else 0
        ph = self._phase(i, None if sp_in is None else bool(sp_in[fld]))
        count = state.get("count")
        if count:
            F = half_inning(self.vec[side][ph], self.trans, G.COUNT_MULT[int(count[0]), int(count[1])])
        else:
            F = self.F[side][ph]
        dist = F[min(o, 2), b]
        n = 2 * D + 1
        if top:
            nd = d - np.arange(R)
            idx = np.clip(nd + D, 0, n - 1)
            vals = np.where((i >= self.inn) & (nd > 0), 1.0, Wb[i, idx])
            return float(np.dot(dist, vals))
        if i >= self.inn:
            nd = d + np.arange(R)
            return float(dist[nd > 0].sum() + dist[nd == 0].sum() * Wt[min(i + 1, MAX_INN + 1), D])
        idx = np.clip(d + np.arange(R) + D, 0, n - 1)
        return float(np.dot(dist, Wt[i + 1, idx]))


def win_prob(spec: dict, state: dict, model: LiveModel | None = None) -> dict:
    m = model or LiveModel(spec)
    p = m.win_prob(state)
    return {"p_home": round(p, 5), "method": "markov", "pregame": round(m.win_prob({"inning": 1, "top": True, "outs": 0,
                                                                                      "bases": 0, "score": [0, 0]}), 5)}


def live_sim(spec: dict, state: dict, n: int = 5000, seed: int = 0) -> dict:
    """Full simulation from the state (lineup position, the starter's pitch count, the exit model)."""
    st = dict(state)
    st.setdefault("bidx", [0, 0])
    st.setdefault("sp_in", [True, True])
    res = G.simulate(spec, n=n, seed=seed, state=st)
    return {"p_home": res["p_home"], "method": "simulation", "sims": n, "total_mean": res["runs"]["total"]}


def league_win_expectancy(state: dict, auto_runner: bool = True) -> float:
    """Win expectancy between two league-average teams (neutral reference curve)."""
    L = G.league_split()
    spec = {"home": G.neutral_side(L), "away": G.neutral_side(L), "league": L, "auto_runner": auto_runner,
            "hfa": np.ones(NE)}
    return LiveModel(spec).win_prob(state)
