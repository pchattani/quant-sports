"""
Season simulation: the rest of the regular season, the NFL tiebreakers, the 7-team (6 before 2020) conference playoffs
with byes and reseeding, the draft order, 20,000 times, vectorised over simulations in chunks.

Simulated games (simulation s, game g between home h and away a)
-----------------------------------------------------------------
    margin = mu_g + (x_{s,h,w(g)} - x_{s,a,w(g)}) + sigma_n * eps,  x_{s,t,w} = z_{s,t} + sum_{k<=w} u_{s,t,k}
    z ~ N(0, se_t^2) (the team's rating error, from team_strength), u ~ N(0, DRIFT^2) a weekly random walk;
    mu_g = game.predict_frame mean (ratings with each side's QB, home field by season, rest, travel, time zones).
    sigma_n = sqrt(max(sigma^2 - mean rating variance of a game, (0.85 sigma)^2)): sigma was fitted on walk-forward
    residuals, which already contain rating error. A regular-season game is a tie with probability P_TIE (era rate)
    independent of the draw; otherwise the sign of the margin decides it. Scores are integers: margin m = round(margin)
    (at least 1 point), total ~ Normal(game total, sigma_total) rounded to the parity of m, so every tiebreak
    quantity (points, net points, ranks) is exact.

Tiebreakers
-----------
Exactly canon.DIVISION_TWO / DIVISION_THREE / WILDCARD_TWO / WILDCARD_THREE with the semantics of builder A's
`tiebreak.Table` (one club advances per application; the rest restart at step 1; two-club remainders restart at step 1
of the two-club format; a Wild Card group of one division uses the division procedure; division winners are seeded by
the Wild Card procedure). `FastTable` evaluates the steps on arrays: team-level steps (division, conference, SOV, SOS,
points rankings, net points) are computed once per chunk for every simulation; group steps (head-to-head, sweep,
common games) per tie from the simulated result matrices. A simulation whose seeds are decided by percentages alone
(no equal percentages where they matter) never enters the per-tie code. Net touchdowns are not simulated: that step
passes to the coin toss, as in Table without touchdown counts. `RESTART_THREE` (default True) applies the published
rule "if three clubs remain tied after a fourth is eliminated, restart at step 1 of the three-club format (Wild Card:
step 2)"; with False the procedure continues with the next step, as tiebreak.Table currently does.

Playoffs
--------
Seeds 1..4 division winners, 5..7 Wild Cards (5..6 before 2020); byes 1 (2 before 2020). Wild Card round: seed b+1 v
the lowest seed, b+2 v the next, ...; then reseeding: the best remaining seed hosts the worst. Conference finals at the
better seed; Super Bowl neutral. P(home) = Phi((x_h - x_a + HFA) / sigma_n) with end-of-season strengths; played
playoff games are fixed.

Draft order: non-playoff clubs by win percentage (worst first), then strength of schedule (lower picks first), then a
random draw; playoff clubs by round of elimination (Wild Card losers, Divisional, Conference, Super Bowl loser,
champion), within a round by percentage then SOS. Trades and forfeits are not modelled (a club's own pick).

Next-game odds are interventional (see basketball season_sim): each simulation is weighted by 1 / P(result | draws).

Magic numbers (deterministic): division and #1 seed: magic_i = k-th largest (W_j + R_j - W_i + 1) over rivals,
tragic_i = k-th smallest (W_i + R_i - W_j + 1), wins only (ties ignored), tiebreaks assumed lost. Playoff berth uses
sufficient conditions: clinched when the division is clinched or at most 3 conference rivals can still reach i's
wins; eliminated when the division is lost and at least 7 conference rivals are already out of reach above.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import ndtr

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import team_strength as TS

logger = logging.getLogger(__name__)

CHUNK = 4000
DRIFT = 0.35            # points per week, random walk of a team's strength
EPS = 1e-9
RESTART_THREE = True


def sim_params() -> dict:
    """Fitted simulation constants (se_scale: multiplier on team_strength's rating sd; drift), from the backtest's
    season-odds calibration (models/fitted/season_sim_params.json), else defaults."""
    for path in (D.c_cache() / "season_sim_params.json", D.FITTED / "season_sim_params.json"):
        c = D.read_json(path)
        if c:
            return c.get("result") or c
    return {"se_scale": 1.0, "drift": DRIFT}


def p_tie(season: int) -> float:
    """Era tie rate of regular-season games (OT: 15 min to 2016, 10 min 2017-2024, both possess from 2025)."""
    return 0.0035 if season < 2017 else (0.005 if season < 2025 else 0.004)


def _canon():
    try:
        from oddsmarkets.nfl import canon
        return canon
    except Exception:  # noqa: BLE001
        return None


def steps() -> dict[str, list[str]]:
    cn = _canon()
    if cn is not None:
        return {"div2": [k for k, _ in cn.DIVISION_TWO], "div3": [k for k, _ in cn.DIVISION_THREE],
                "wc2": [k for k, _ in cn.WILDCARD_TWO], "wc3": [k for k, _ in cn.WILDCARD_THREE]}
    d2 = ["h2h", "div_pct", "common_pct", "conf_pct", "sov", "sos", "conf_rank", "all_rank", "common_net", "all_net",
          "net_td", "coin"]
    w2 = ["h2h_if", "conf_pct", "common_pct4", "sov", "sos", "conf_rank", "all_rank", "conf_net", "all_net", "net_td", "coin"]
    return {"div2": d2, "div3": d2, "wc2": w2, "wc3": ["div_reduce", "h2h_sweep"] + w2[1:]}


def fmt(season: int) -> dict:
    cn = _canon()
    if cn is not None:
        f = cn.formats(season)
        return {"games": f["games"], "wc": f["wild_cards_per_conf"], "byes": f["byes_per_conf"],
                "seeds": f["playoff_teams_per_conf"], "divs": f["divisions_per_conf"]}
    if season >= 2020:
        return {"games": 17 if season >= 2021 else 16, "wc": 3, "byes": 1, "seeds": 7, "divs": 4}
    return {"games": 16, "wc": 2, "byes": 2, "seeds": 6, "divs": 4}


# ── per-chunk tiebreak data ──────────────────────────────────────────────────

class ChunkStats:
    """Team-level tiebreak quantities for every simulation of a chunk (float64, exact on integer scores)."""

    def __init__(self, conf_id, div_id, Gm, R, Wn, NPm, PF, PA):
        self.conf_id, self.div_id, self.Gm = conf_id, div_id, Gm
        self.R, self.Wn, self.NPm, self.PF, self.PA = R, Wn, NPm, PF, PA
        S, T, _ = R.shape
        Gt = Gm.sum(1).astype(float)
        self.Gt = Gt
        Rsum = R.sum(2, dtype=np.float64)
        self.Rsum = Rsum
        self.pct = np.where(Gt > 0, Rsum / np.maximum(Gt, 1), 0.5)
        same_div = (div_id[:, None] == div_id[None, :]) & ~np.eye(T, dtype=bool)
        same_conf = (conf_id[:, None] == conf_id[None, :]) & ~np.eye(T, dtype=bool)
        self.same_conf = same_conf
        for name, m in (("div_pct", same_div), ("conf_pct", same_conf)):
            g = (Gm * m).sum(1).astype(float)
            w = np.einsum("stj,tj->st", R.astype(np.float64), m.astype(np.float64))
            setattr(self, name, np.where(g > 0, w / np.maximum(g, 1), 0.5))
        Wf = Wn.astype(np.float64)
        num = np.einsum("stj,sj->st", Wf, Rsum)
        den = np.einsum("stj,j->st", Wf, Gt)
        self.sov = np.where(den > 0, num / np.maximum(den, 1e-12), 0.0)
        Gf = Gm.astype(np.float64)
        self.sos = (Rsum @ Gf.T) / np.maximum(Gf @ Gt, 1e-12)[None, :]
        # combined points rankings (competition ranking, lower sum better -> metric = -sum)
        def ranks(vals, higher_better, mask):
            if higher_better:
                better = vals[:, None, :] > vals[:, :, None]
            else:
                better = vals[:, None, :] < vals[:, :, None]
            return 1 + (better & mask[None]).sum(2)
        cm = (conf_id[:, None] == conf_id[None, :])
        am = np.ones((T, T), bool)
        self.conf_rank = -(ranks(PF, True, cm) + ranks(PA, False, cm)).astype(float)
        self.all_rank = -(ranks(PF, True, am) + ranks(PA, False, am)).astype(float)
        self.conf_net = np.einsum("stj,tj->st", NPm.astype(np.float64), same_conf.astype(np.float64))
        self.all_net = NPm.sum(2, dtype=np.float64)


class FastTable:
    """tiebreak.Table semantics for one simulation, on the chunk's arrays."""

    def __init__(self, cs: ChunkStats, s: int, teams: list[str], div_names: list[str], conf_names: list[str], rng,
                 st: dict, restart_three: bool = RESTART_THREE):
        self.cs, self.s, self.teams, self.rng, self.st = cs, s, teams, rng, st
        self.div_names, self.conf_names = div_names, conf_names
        self.restart_three = restart_three
        self._div_order: dict[int, list[int]] = {}
        self.coin_used = False
        self.pct = cs.pct[s]

    # metrics: dict club -> value, higher better; None = not applicable
    def metric(self, key: str, clubs: list[int]) -> dict | None:
        cs, s = self.cs, self.s
        if key in ("h2h", "h2h_if"):
            if key == "h2h_if" and (len(clubs) != 2 or cs.Gm[clubs[0], clubs[1]] == 0):
                return None
            out = {}
            for c in clubs:
                others = [x for x in clubs if x != c]
                g = cs.Gm[c, others].sum()
                if g == 0:
                    if key == "h2h_if":
                        return None
                    out[c] = 0.5
                else:
                    out[c] = float(cs.R[s, c, others].sum()) / g
            return out
        if key in ("div_pct", "conf_pct", "sov", "sos", "conf_rank", "all_rank", "conf_net", "all_net"):
            arr = getattr(cs, key)[s]
            return {c: float(arr[c]) for c in clubs}
        if key in ("common_pct", "common_pct4", "common_net"):
            co = np.all(cs.Gm[clubs] > 0, axis=0)
            if not co.any():
                return None
            co_idx = np.nonzero(co)[0]
            g = cs.Gm[np.ix_(clubs, co_idx)].sum(1)
            if key == "common_pct4" and (g < 4).any():
                return None
            if key == "common_net":
                v = cs.NPm[s][np.ix_(clubs, co_idx)].sum(1)
                return {c: float(x) for c, x in zip(clubs, v)}
            w = cs.R[s][np.ix_(clubs, co_idx)].sum(1)
            return {c: (float(ww) / gg if gg else 0.5) for c, ww, gg in zip(clubs, w, g)}
        if key == "net_td":
            return None
        raise KeyError(key)

    def sweep(self, clubs: list[int]):
        cs, s = self.cs, self.s
        for c in clubs:
            others = [x for x in clubs if x != c]
            g = cs.Gm[c, others]
            if (g > 0).all() and (cs.Wn[s, c, others] == g).all():
                return "won", c
        for c in clubs:
            others = [x for x in clubs if x != c]
            g = cs.Gm[c, others]
            if (g > 0).all() and (cs.Wn[s, others, c] == g).all():
                return "lost", c
        return None

    def pick_one(self, clubs: list[int], kind: str, start: int = 0) -> int:
        clubs = sorted(clubs, key=lambda i: self.teams[i])
        if len(clubs) == 1:
            return clubs[0]
        if kind == "wc" and len({int(self.cs.div_id[c]) for c in clubs}) == 1:
            kind = "div"
        key = ("div2" if len(clubs) == 2 else "div3") if kind == "div" else ("wc2" if len(clubs) == 2 else "wc3")
        sts = self.st[key]
        pool = list(clubs)
        k0 = start
        for k in range(k0, len(sts)):
            step = sts[k]
            if step == "coin":
                self.coin_used = True
                return pool[int(self.rng.integers(len(pool)))]
            if step == "div_reduce":
                best: dict[int, int] = {}
                for c in pool:
                    d = int(self.cs.div_id[c])
                    order = self.division_order(d)
                    if d not in best or order.index(c) < order.index(best[d]):
                        best[d] = c
                reduced = sorted(best.values(), key=lambda i: self.teams[i])
                pool = reduced
                if len(pool) == 1:
                    return pool[0]
                if len(pool) == 2:
                    return self.pick_one(pool, "wc")
                continue
            if step == "h2h_sweep":
                sw = self.sweep(pool)
                if sw is None:
                    continue
                kind_s, club = sw
                if kind_s == "won":
                    return club
                before = len(pool)
                pool = [c for c in pool if c != club]
                if len(pool) == 2:
                    return self.pick_one(pool, "wc")
                if len(pool) == 1:
                    return pool[0]
                if self.restart_three and before >= 4 and len(pool) == 3:
                    return self.pick_one(pool, kind, start=self._restart_index(key))
                continue
            vals = self.metric(step, pool)
            if vals is None:
                continue
            top_v = max(vals.values())
            top = [c for c in pool if vals[c] >= top_v - EPS]
            if len(top) == 1:
                return top[0]
            if len(top) < len(pool):
                before = len(pool)
                pool = top
                if len(pool) == 2:
                    return self.pick_one(pool, kind)
                if self.restart_three and before >= 4 and len(pool) == 3:
                    return self.pick_one(pool, kind, start=self._restart_index(key))
        raise AssertionError("unreachable: the coin toss always decides")

    @staticmethod
    def _restart_index(key: str) -> int:
        # division: step 1 of the three-club format; Wild Card: step 2 (after the division reduction)
        return 0 if key.startswith("div") else 1

    def order(self, clubs, kind: str) -> list[int]:
        rest = sorted(set(clubs), key=lambda i: self.teams[i])
        out = []
        while rest:
            w = self.pick_one(rest, kind)
            out.append(w)
            rest.remove(w)
        return out

    def rank(self, clubs, kind: str) -> list[int]:
        groups: dict[float, list[int]] = {}
        for c in clubs:
            groups.setdefault(round(float(self.pct[c]), 9), []).append(c)
        out = []
        for p in sorted(groups, reverse=True):
            out += self.order(groups[p], kind) if len(groups[p]) > 1 else groups[p]
        return out

    def division_order(self, d: int) -> list[int]:
        if d not in self._div_order:
            mem = [int(t) for t in np.nonzero(self.cs.div_id == d)[0]]
            self._div_order[d] = self.rank(mem, "div")
        return self._div_order[d]

    def seed_conference(self, c: int, n_wc: int) -> list[int]:
        divs = sorted({int(self.cs.div_id[t]) for t in np.nonzero(self.cs.conf_id == c)[0]}, key=lambda d: self.div_names[d])
        winners = [self.division_order(d)[0] for d in divs]
        w_order = self.rank(winners, "wc")
        pool = [int(t) for t in np.nonzero(self.cs.conf_id == c)[0] if int(t) not in winners]
        rest = self.rank(pool, "wc")
        return w_order + rest[:n_wc]


def seed_chunk(cs: ChunkStats, teams, div_names, conf_names, f: dict, rng, st: dict, restart_three: bool = RESTART_THREE):
    """seeds[c] (S, n_seeds) team indices; div_winner (S, T) bool; n_slow (conference-simulations resolved one by
    one). A conference whose seeds are decided by percentages alone (no equal percentages at a division top, among
    the division winners, or among the Wild Card places and the first club out) takes the vectorised path."""
    S, T = cs.pct.shape
    conf_ids = sorted(set(int(x) for x in cs.conf_id), key=lambda c: conf_names[c])
    seeds = {}
    divw = np.zeros((S, T), bool)
    ar = np.arange(S)
    n_wc = f["wc"]
    slow = {}
    for c in conf_ids:
        divs = sorted({int(cs.div_id[t]) for t in np.nonzero(cs.conf_id == c)[0]}, key=lambda d: div_names[d])
        sl = np.zeros(S, bool)
        wins = []
        for d in divs:
            mem = np.nonzero(cs.div_id == d)[0]
            p = cs.pct[:, mem]
            mx = p.max(1)
            sl |= (p >= mx[:, None] - EPS).sum(1) > 1
            wins.append(mem[np.argmax(p, 1)])
        W = np.stack(wins, 1)
        pw = np.take_along_axis(cs.pct, W, 1)
        o = np.argsort(-pw, 1, kind="stable")
        Ws = np.take_along_axis(W, o, 1)
        pws = np.take_along_axis(pw, o, 1)
        sl |= (np.abs(np.diff(pws, axis=1)) < EPS).any(1)
        mem = np.nonzero(cs.conf_id == c)[0]
        isw = np.zeros((S, T), bool)
        isw[ar[:, None], W] = True
        pp = np.where(isw[:, mem], -9.0, cs.pct[:, mem])
        o2 = np.argsort(-pp, 1, kind="stable")
        top = mem[o2[:, : n_wc + 1]]
        ptop = np.take_along_axis(pp, o2[:, : n_wc + 1], 1)
        sl |= (np.abs(np.diff(ptop, axis=1)) < EPS).any(1)
        seeds[c] = np.concatenate([Ws, top[:, :n_wc]], 1)
        divw[:, mem] = isw[:, mem]
        slow[c] = sl
    any_slow = np.zeros(S, bool)
    for c in conf_ids:
        any_slow |= slow[c]
    n_slow = 0
    for s in np.nonzero(any_slow)[0]:
        tb = FastTable(cs, int(s), teams, div_names, conf_names, rng, st, restart_three)
        for c in conf_ids:
            if not slow[c][s]:
                continue
            n_slow += 1
            seeds[c][s] = tb.seed_conference(c, n_wc)
            mem = np.nonzero(cs.conf_id == c)[0]
            divw[s, mem] = False
            for d in {int(cs.div_id[t]) for t in mem}:
                divw[s, tb.division_order(d)[0]] = True
    return seeds, divw, n_slow


# ── state ────────────────────────────────────────────────────────────────────

def build_state(season: int, games: pd.DataFrame, through: Any = None) -> dict:
    """Teams, alignment, played results and the remaining schedule from a games frame (_cdata.games_frame)."""
    tinfo = D.teams_for(season)
    g = games[games["season"] == season].copy()
    if through is not None:
        cut = pd.Timestamp(through)
        g.loc[g["date"] >= cut, "played"] = False
    reg = g[g["gtype"] == "REG"]
    teams = sorted(set(reg["home"]) | set(reg["away"]) | set(tinfo))
    teams = [t for t in teams if t in tinfo]
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    conf_names = sorted({tinfo[t]["conference"] for t in teams})
    div_names = sorted({tinfo[t]["division"] for t in teams})
    conf_id = np.array([conf_names.index(tinfo[t]["conference"]) for t in teams])
    div_id = np.array([div_names.index(tinfo[t]["division"]) for t in teams])
    Gm = np.zeros((T, T), np.int16)
    R = np.zeros((T, T), np.float32)
    Wn = np.zeros((T, T), np.int16)
    NPm = np.zeros((T, T), np.float32)
    PF = np.zeros(T)
    PA = np.zeros(T)
    W = np.zeros(T, int)
    L = np.zeros(T, int)
    Ti = np.zeros(T, int)
    rem = []
    for r in reg.itertuples(index=False):
        h, a = idx.get(r.home), idx.get(r.away)
        if h is None or a is None:
            continue
        Gm[h, a] += 1
        Gm[a, h] += 1
        if bool(r.played) and np.isfinite(r.hs) and np.isfinite(r.as_):
            m = int(r.hs) - int(r.as_)
            PF[h] += r.hs; PA[h] += r.as_; PF[a] += r.as_; PA[a] += r.hs
            NPm[h, a] += m; NPm[a, h] -= m
            if m > 0:
                R[h, a] += 1; Wn[h, a] += 1; W[h] += 1; L[a] += 1
            elif m < 0:
                R[a, h] += 1; Wn[a, h] += 1; W[a] += 1; L[h] += 1
            else:
                R[h, a] += 0.5; R[a, h] += 0.5; Ti[h] += 1; Ti[a] += 1
        else:
            rem.append(r)
    post = g[g["gtype"] != "REG"]
    FP = np.full((T, T), -1, int)
    post_played = []
    for r in post.itertuples(index=False):
        h, a = idx.get(r.home), idx.get(r.away)
        if h is None or a is None or not bool(r.played) or not np.isfinite(r.hs):
            continue
        w = h if r.hs > r.as_ else a
        FP[h, a] = FP[a, h] = w
        post_played.append((r.gtype, h, a, w))
    return {"season": season, "teams": teams, "idx": idx, "conf_id": conf_id, "div_id": div_id, "conf_names": conf_names,
            "div_names": div_names, "Gm": Gm, "R": R, "Wn": Wn, "NPm": NPm, "PF": PF, "PA": PA, "W": W, "L": L, "Ti": Ti,
            "remaining": pd.DataFrame([r._asdict() for r in rem]) if rem else pd.DataFrame(),
            "FP": FP, "post_played": post_played, "games": g}


# ── magic numbers ────────────────────────────────────────────────────────────

def magic_numbers(W, Rm, conf_id, div_id, n_seeds: int) -> list[dict]:
    T = len(W)
    out = []
    for i in range(T):
        rec = {"magic": {}, "tragic": {}, "clinched": {}, "eliminated": {}}
        for name, grp, k in (("division", div_id, 1), ("top_seed", conf_id, 1)):
            rivals = [j for j in range(T) if j != i and grp[j] == grp[i]]
            M = sorted((W[j] + Rm[j] - W[i] + 1 for j in rivals), reverse=True)
            E = sorted(W[i] + Rm[i] - W[j] + 1 for j in rivals)
            mg, tg = int(M[k - 1]), int(E[k - 1])
            rec["magic"][name], rec["tragic"][name] = max(0, mg), max(0, tg)
            rec["clinched"][name], rec["eliminated"][name] = mg <= 0, tg <= 0
        rivals = [j for j in range(T) if j != i and conf_id[j] == conf_id[i]]
        reach = sum(1 for j in rivals if W[j] + Rm[j] >= W[i])
        ahead = sum(1 for j in rivals if W[j] > W[i] + Rm[i])
        M4 = sorted((W[j] + Rm[j] - W[i] + 1 for j in rivals), reverse=True)
        m4 = M4[3] if len(M4) >= 4 else 0
        rec["magic"]["playoffs"] = 0 if rec["clinched"]["division"] else max(0, int(min(m4, rec["magic"]["division"])))
        rec["clinched"]["playoffs"] = bool(rec["clinched"]["division"] or reach <= 3)
        rec["eliminated"]["playoffs"] = bool(rec["eliminated"]["division"] and ahead >= 7)
        rec["tragic"]["playoffs"] = None
        out.append(rec)
    return out


# ── simulation ───────────────────────────────────────────────────────────────

def _pair_index(hi: np.ndarray, ai: np.ndarray):
    pairs: dict[tuple, list] = {}
    G_ = len(hi)
    for k in range(G_):
        i, j = (hi[k], ai[k]) if hi[k] < ai[k] else (ai[k], hi[k])
        pairs.setdefault((int(i), int(j)), []).append(k)
    PI = np.array([k[0] for k in pairs], int)
    PJ = np.array([k[1] for k in pairs], int)
    width = max((len(v) for v in pairs.values()), default=1)
    PC = np.full((len(pairs), width), G_, int)
    PS = np.zeros((len(pairs), width), np.float32)
    for r, (key, cols) in enumerate(pairs.items()):
        PC[r, :len(cols)] = cols
        PS[r, :len(cols)] = [1.0 if hi[c] == key[0] else -1.0 for c in cols]
    return PI, PJ, PC, PS


def _single(h, a, x, hfa, sd, FP, rng):
    ar = np.arange(len(h))
    p = ndtr((x[ar, h] - x[ar, a] + hfa) / sd)
    w = np.where(rng.random(len(h)) < p, h, a)
    known = FP[h, a]
    return np.where(known >= 0, known, w)


def _playoffs(seeds_c: np.ndarray, x, hfa, sd, FP, rng, byes: int):
    """Conference bracket with reseeding. Returns (champion (S,), losers by round {round: list of (S,) arrays},
    reached {round: (S, k) teams})."""
    S, n = seeds_c.shape
    seed_no = np.broadcast_to(np.arange(1, n + 1), (S, n))
    alive_t = seeds_c.copy()
    alive_s = seed_no.copy()
    losers = {"WC": [], "DIV": [], "CON": []}
    reached = {"WC": seeds_c[:, byes:].copy(), "DIV": None, "CON": None}
    # Wild Card round
    n_games = (n - byes) // 2
    wc_w, wc_ws = [], []
    for k in range(n_games):
        hi_c, lo_c = byes + k, n - 1 - k
        h, a = seeds_c[:, hi_c], seeds_c[:, lo_c]
        w = _single(h, a, x, hfa, sd, FP, rng)
        wc_w.append(w)
        wc_ws.append(np.where(w == h, hi_c + 1, lo_c + 1))
        losers["WC"].append(np.where(w == h, a, h))
    alive_t = np.concatenate([seeds_c[:, :byes]] + [w[:, None] for w in wc_w], 1)
    alive_s = np.concatenate([seed_no[:, :byes]] + [s[:, None] for s in wc_ws], 1)
    for rnd in ("DIV", "CON"):
        reached[rnd] = alive_t.copy()
        o = np.argsort(alive_s, 1)
        t_sorted = np.take_along_axis(alive_t, o, 1)
        s_sorted = np.take_along_axis(alive_s, o, 1)
        m = t_sorted.shape[1]
        nt, ns = [], []
        for k in range(m // 2):
            h, a = t_sorted[:, k], t_sorted[:, m - 1 - k]
            w = _single(h, a, x, hfa, sd, FP, rng)
            nt.append(w)
            ns.append(np.where(w == h, s_sorted[:, k], s_sorted[:, m - 1 - k]))
            losers[rnd].append(np.where(w == h, a, h))
        alive_t = np.stack(nt, 1)
        alive_s = np.stack(ns, 1)
    return alive_t[:, 0], losers, reached


def prepare(season: int, state: dict | None = None) -> dict:
    """Everything simulate() computes before its first random draw (the state, the ratings, each remaining game's
    mean margin and total): pass the result as state["prepared"] to run many simulations of the same season (the
    trade sensitivity curves) without recomputing it. Uses the same state keys as simulate()."""
    st = dict(state or {})
    games = st.get("games")
    if games is None:
        games = D.games_frame([season - 1, season])
    S0 = build_state(season, games, st.get("through"))
    teams = S0["teams"]
    rt = st.get("ratings")
    if rt is None:
        try:
            rt = TS.for_season(season, st.get("through"))
        except Exception as exc:  # noqa: BLE001
            logger.info("season_sim: ratings unavailable (%s); flat prior", exc)
            rt = {"teams": {}, "league": {}}
    prm = GM.params(st.get("params"))
    rteams = rt.get("teams") or {}
    qb_over = st.get("qb") or {}
    base = np.array([TS.team_net(rt, t, qb_over.get(t)) for t in teams])
    se = np.array([float((rteams.get(t) or {}).get("se_net", 3.0)) for t in teams])
    se = np.where(np.isfinite(se), se, 3.0) * float(st.get("se_scale", sim_params().get("se_scale", 1.0)))
    rem = S0["remaining"]
    G_ = len(rem)
    hfa_eff = float(prm["hfa"] + prm["hfa_trend"] * (season - 2015) / 10.0 + float((prm.get("hfa_by_season") or {}).get(str(season), 0.0)))
    if G_:
        ctx = D.add_context(S0["games"].sort_values(["date", "game_id"]))
        ctx = ctx[ctx["game_id"].isin(set(rem["game_id"]))].set_index("game_id").loc[rem["game_id"]].reset_index()
        base_tot = _scoring_level(games, season)
        mg = games.copy()
        if st.get("through") is not None:                 # market ratings only from games played before `through`
            mg.loc[pd.to_datetime(mg["date"]) >= pd.Timestamp(st["through"]), "played"] = False
        pf = GM.predict_frame(ctx, rt, prm, base=base_tot, qb_override=qb_over, market_games=mg)
        mu = pf["mu"].to_numpy(float)
        mt = pf["mu_total"].to_numpy(float)
        hi = np.array([S0["idx"][h] for h in rem["home"]], int)
        ai = np.array([S0["idx"][a] for a in rem["away"]], int)
        wk = rem["week"].to_numpy(int)
        week = wk - wk.min()
        n_weeks = int(week.max()) + 1
    else:
        mu = mt = np.zeros(0)
        hi = ai = week = np.zeros(0, int)
        n_weeks = 1
    return {"season": int(season), "S0": S0, "rt": rt, "prm": prm, "base": base, "se": se, "mu": mu, "mt": mt, "hi": hi, "ai": ai,
            "week": week, "n_weeks": n_weeks, "hfa_eff": hfa_eff}


def simulate(season: int, n: int = 20000, seed: int = 0, state: dict | None = None) -> dict:
    """
    {"teams": {abbr: {...}}, "bracket", "draft", "n_sims", "runtime_s", ...}

    state (optional): "games" (a _cdata games frame; else games_frame(season)), "through" (date: later games count as
    unplayed), "ratings" (team_strength dict; else for_season), "params" (game-model overrides), "qb" ({team: gsis id}
    starter overrides, e.g. injuries), "drift", "se_scale", "chunk", "restart_three".
    Sensitivity runs (none of these change a run without them): "prepared" (prepare()'s output, reused), "shift"
    ({team: points per game} added to the team's strength in every remaining game and in the playoffs), "z_scale"
    ({team: k}: that team's rating error is drawn with k times its sd, the importance-sampling proposal of
    sensitivity()), "record" (a team: the result carries "_record", that team's per-simulation rating draw and
    outcomes).
    """
    t0 = time.perf_counter()
    st = dict(state or {})
    prep = st.get("prepared") or prepare(season, st)
    S0, rt, prm = prep["S0"], prep["rt"], prep["prm"]
    teams, T = S0["teams"], len(S0["teams"])
    f = fmt(season)
    stp = steps()
    sigma = float(prm["sigma"])
    base = prep["base"].copy()
    se = prep["se"]
    rem = S0["remaining"]
    G_ = len(rem)
    hfa_eff = prep["hfa_eff"]
    mu, mt, hi, ai, week, n_weeks = prep["mu"].copy(), prep["mt"], prep["hi"], prep["ai"], prep["week"], prep["n_weeks"]
    for t, dx in (st.get("shift") or {}).items():
        i = S0["idx"].get(t)
        if i is None or not dx:
            continue
        base[i] += float(dx)
        if G_:
            mu = mu + float(dx) * ((hi == i).astype(float) - (ai == i).astype(float))
    se_draw = se.copy()
    for t, k in (st.get("z_scale") or {}).items():
        i = S0["idx"].get(t)
        if i is not None:
            se_draw[i] = se[i] * float(k)
    rec_i = S0["idx"].get(st.get("record")) if st.get("record") is not None else None
    rec_parts: dict[str, list] = {k: [] for k in ("z", "playoffs", "div", "bye", "conf", "sb", "wins", "pick")}
    rating_var = float(np.mean(2 * se ** 2))
    sd_n = math.sqrt(max(sigma ** 2 - rating_var, (0.85 * sigma) ** 2))
    sd_t = float(prm["sigma_total"])
    drift = float(st.get("drift", sim_params().get("drift", DRIFT)))
    ptie = p_tie(season)
    conf_id, div_id = S0["conf_id"], S0["div_id"]
    PI, PJ, PC, PS = _pair_index(hi, ai) if G_ else (np.zeros(0, int),) * 2 + (np.zeros((0, 1), int), np.zeros((0, 1), np.float32))
    OHh = np.zeros((G_, T), np.float32); OHa = np.zeros((G_, T), np.float32)
    if G_:
        OHh[np.arange(G_), hi] = 1.0
        OHa[np.arange(G_), ai] = 1.0
    next_col = {}
    for k in range(G_):
        for t in (hi[k], ai[k]):
            next_col.setdefault(int(t), k)
    conf_ids = sorted(set(int(x) for x in conf_id), key=lambda c: S0["conf_names"][c])
    n_seeds = f["seeds"]
    acc = {k: np.zeros(T) for k in ("w", "l", "t", "playoffs", "div", "bye", "wc", "conf", "sb", "r_div", "r_con", "r_sb")}
    seed_counts = np.zeros((T, n_seeds))
    win_hist = np.zeros((T, f["games"] + 1))
    pick = np.zeros((T, T))
    nx = {t: {"n": 0.0, "p_sum": 0.0, "win": np.zeros(5), "loss": np.zeros(5), "w_win": 0.0, "w_loss": 0.0} for t in next_col}
    sb_pairs: dict = {}
    rng = np.random.default_rng(seed)
    chunk = int(st.get("chunk", CHUNK))
    restart_three = bool(st.get("restart_three", RESTART_THREE))
    n_slow = 0
    done = 0
    while done < n:
        S = min(chunk, n - done)
        done += S
        ar = np.arange(S)
        z = rng.normal(0.0, 1.0, (S, T)) * se_draw[None, :]
        R = np.broadcast_to(S0["R"], (S, T, T)).copy()
        Wn = np.broadcast_to(S0["Wn"], (S, T, T)).copy()
        NPm = np.broadcast_to(S0["NPm"], (S, T, T)).copy()
        PF = np.broadcast_to(S0["PF"], (S, T)).copy()
        PA = np.broadcast_to(S0["PA"], (S, T)).copy()
        Wc = np.broadcast_to(S0["W"], (S, T)).astype(np.int32).copy()
        Lc = np.broadcast_to(S0["L"], (S, T)).astype(np.int32).copy()
        Tc = np.broadcast_to(S0["Ti"], (S, T)).astype(np.int32).copy()
        if G_:
            U = rng.normal(0.0, drift, (S, T, n_weeks)).cumsum(axis=2) if drift > 0 else np.zeros((S, T, n_weeks))
            xg_h = z[:, hi] + U[:, hi, week]
            xg_a = z[:, ai] + U[:, ai, week]
            marg = mu[None, :] + (xg_h - xg_a) + sd_n * rng.standard_normal((S, G_))
            tie = rng.random((S, G_)) < ptie
            m_int = np.where(tie, 0, np.where(marg >= 0, np.maximum(np.rint(marg), 1), np.minimum(np.rint(marg), -1))).astype(np.int32)
            tot = mt[None, :] + sd_t * rng.standard_normal((S, G_))
            tot_int = m_int + 2 * np.rint((tot - m_int) / 2.0).astype(np.int32)
            tot_int = np.maximum(tot_int, np.abs(m_int))
            hs = (tot_int + m_int) // 2
            as_ = (tot_int - m_int) // 2
            hw = np.where(m_int > 0, 1.0, np.where(m_int < 0, 0.0, 0.5)).astype(np.float32)
            hwin = (m_int > 0).astype(np.float32)
            awin = (m_int < 0).astype(np.float32)
            tiex = (m_int == 0).astype(np.float32)
            Wc += np.rint(hwin @ OHh + awin @ OHa).astype(np.int32)
            Lc += np.rint(awin @ OHh + hwin @ OHa).astype(np.int32)
            Tc += np.rint(tiex @ (OHh + OHa)).astype(np.int32)
            PF += hs.astype(np.float64) @ OHh + as_.astype(np.float64) @ OHa
            PA += as_.astype(np.float64) @ OHh + hs.astype(np.float64) @ OHa
            pad = lambda X: np.concatenate([X, np.zeros((S, 1), X.dtype)], 1)   # noqa: E731
            gw = pad(hw)[:, PC]
            wi = np.where(PS > 0, gw, np.where(PS < 0, 1.0 - gw, 0.0)).sum(2)
            pn = (PS != 0).sum(1).astype(np.float32)
            R[:, PI, PJ] += wi
            R[:, PJ, PI] += pn[None, :] - wi
            gwin = pad(hwin)[:, PC]
            gaw = pad(awin)[:, PC]
            wins_i = np.where(PS > 0, gwin, np.where(PS < 0, gaw, 0.0)).sum(2)
            wins_j = np.where(PS > 0, gaw, np.where(PS < 0, gwin, 0.0)).sum(2)
            Wn[:, PI, PJ] += wins_i.astype(Wn.dtype)
            Wn[:, PJ, PI] += wins_j.astype(Wn.dtype)
            mx = pad(m_int.astype(np.float32))[:, PC]
            di = (mx * PS[None]).sum(2)
            NPm[:, PI, PJ] += di
            NPm[:, PJ, PI] -= di
            x_end = base[None, :] + z + U[:, :, -1]
        else:
            x_end = base[None, :] + z
        cs = ChunkStats(conf_id, div_id, S0["Gm"], R, Wn, NPm, PF, PA)
        seeds, divw, ns = seed_chunk(cs, teams, S0["div_names"], S0["conf_names"], f, rng, stp, restart_three)
        n_slow += ns
        acc["w"] += Wc.sum(0); acc["l"] += Lc.sum(0); acc["t"] += Tc.sum(0)
        win_hist += np.bincount((np.arange(T)[None, :] * (f["games"] + 1) + np.clip(Wc, 0, f["games"])).ravel(),
                                minlength=T * (f["games"] + 1)).reshape(T, f["games"] + 1)
        acc["div"] += divw.sum(0)
        made = np.zeros((S, T), bool)
        bye = np.zeros((S, T), bool)
        conf_champ = np.zeros((S, T), bool)
        exit_round = np.zeros((S, T), np.int8)          # 0 out, 1 WC loss, 2 DIV loss, 3 CON loss, 4 SB loss, 5 champion
        champs = []
        for c in conf_ids:
            sc = seeds[c]
            np.add.at(seed_counts, (sc.ravel(), np.tile(np.arange(n_seeds), S)), 1.0)
            made[ar[:, None], sc] = True
            bye[ar[:, None], sc[:, : f["byes"]]] = True
            champ, losers, reached = _playoffs(sc, x_end, hfa_eff, sd_n, S0["FP"], rng, f["byes"])
            for rnd, code in (("WC", 1), ("DIV", 2), ("CON", 3)):
                for lo in losers[rnd]:
                    exit_round[ar, lo] = code
            acc["r_div"] += np.bincount(reached["DIV"].ravel(), minlength=T)
            acc["r_con"] += np.bincount(reached["CON"].ravel(), minlength=T)
            conf_champ[ar, champ] = True
            champs.append(champ)
        a_, b_ = champs[0], champs[1]
        title = _single(a_, b_, x_end, 0.0, sd_n, S0["FP"], rng)
        sb_loser = np.where(title == a_, b_, a_)
        exit_round[ar, sb_loser] = 4
        exit_round[ar, title] = 5
        acc["r_sb"] += np.bincount(np.concatenate([a_, b_]), minlength=T)
        code = a_.astype(np.int64) * 100 + b_
        u_, cnt = np.unique(code, return_counts=True)
        for cc, nn in zip(u_, cnt):
            sb_pairs[int(cc)] = sb_pairs.get(int(cc), 0) + int(nn)
        acc["playoffs"] += made.sum(0); acc["bye"] += bye.sum(0); acc["conf"] += conf_champ.sum(0)
        acc["sb"] += np.bincount(title, minlength=T)
        acc["wc"] += (made & ~divw).sum(0)
        # draft order: lexsort keys, last is primary
        key_rand = rng.random((S, T))
        order = np.lexsort((key_rand, cs.sos, cs.pct, exit_round.astype(float)), axis=1) if False else \
            _draft_order(exit_round, cs.pct, cs.sos, key_rand)
        np.add.at(pick, (order.ravel(), np.tile(np.arange(T), S)), 1.0)
        if rec_i is not None:
            rec_parts["z"].append(z[:, rec_i].copy())
            rec_parts["playoffs"].append(made[:, rec_i].copy())
            rec_parts["div"].append(divw[:, rec_i].copy())
            rec_parts["bye"].append(bye[:, rec_i].copy())
            rec_parts["conf"].append(conf_champ[:, rec_i].copy())
            rec_parts["sb"].append(title == rec_i)
            rec_parts["wins"].append(Wc[:, rec_i].astype(float))
            rec_parts["pick"].append(np.argmax(order == rec_i, axis=1) + 1.0)
        if G_:
            outs = np.stack([made, divw, bye, conf_champ, np.zeros((S, T), bool)], 2)
            outs[ar, title, 4] = True
            for t, k in next_col.items():
                is_home = hi[k] == t
                won = (m_int[:, k] > 0) if is_home else (m_int[:, k] < 0)
                p_home = ndtr((mu[k] + (xg_h[:, k] - xg_a[:, k])) / sd_n)
                p_t = np.clip(p_home if is_home else 1.0 - p_home, 1e-3, 1 - 1e-3)
                ww, wl = 1.0 / p_t, 1.0 / (1.0 - p_t)
                rec = nx[t]
                rec["n"] += S
                rec["p_sum"] += float(p_t.sum())
                rec["win"] += (outs[won, t, :] * ww[won, None]).sum(0)
                rec["loss"] += (outs[~won, t, :] * wl[~won, None]).sum(0)
                rec["w_win"] += float(ww[won].sum())
                rec["w_loss"] += float(wl[~won].sum())
        del R, Wn, NPm, cs
    nsim = float(n)
    Rm = np.bincount(np.concatenate([hi, ai]), minlength=T) if G_ else np.zeros(T, int)
    mg = magic_numbers(S0["W"], Rm, conf_id, div_id, n_seeds)
    wh = win_hist / nsim
    cdf = wh.cumsum(1)
    out_teams = {}
    pk = pick / nsim
    keys5 = ("p_playoffs", "p_div", "p_bye", "p_conf", "p_sb")
    for i, t in enumerate(teams):
        nxt = None
        if i in nx and nx[i]["n"] > 0:
            rec = nx[i]
            k = next_col[i]
            r = rem.iloc[k]
            nxt = {"game_id": str(r["game_id"]), "week": int(r["week"]), "opp": r["away"] if r["home"] == t else r["home"],
                   "home": bool(r["home"] == t), "p_win": rec["p_sum"] / rec["n"],
                   "if_win": {kk: float(v / rec["w_win"]) if rec["w_win"] > 0 else None for kk, v in zip(keys5, rec["win"])},
                   "if_loss": {kk: float(v / rec["w_loss"]) if rec["w_loss"] > 0 else None for kk, v in zip(keys5, rec["loss"])}}
        out_teams[t] = {
            "conference": S0["conf_names"][conf_id[i]], "division": S0["div_names"][div_id[i]],
            "current": {"w": int(S0["W"][i]), "l": int(S0["L"][i]), "t": int(S0["Ti"][i]), "pf": float(S0["PF"][i]),
                        "pa": float(S0["PA"][i]), "remaining": int(Rm[i])},
            "rating": float(base[i]), "rating_se": float(se[i]),
            "exp_w": float(acc["w"][i] / nsim), "exp_l": float(acc["l"][i] / nsim), "exp_t": float(acc["t"][i] / nsim),
            "w_p05": int(np.searchsorted(cdf[i], 0.05)), "w_p95": int(np.searchsorted(cdf[i], 0.95)),
            "win_dist": [round(float(x), 5) for x in wh[i]],
            "seed_dist": [float(x) for x in seed_counts[i] / nsim],
            "p_playoffs": float(acc["playoffs"][i] / nsim), "p_div": float(acc["div"][i] / nsim),
            "p_bye": float(acc["bye"][i] / nsim), "p_wildcard": float(acc["wc"][i] / nsim),
            "p_reach": {"DIV": float(acc["r_div"][i] / nsim), "CON": float(acc["r_con"][i] / nsim),
                        "SB": float(acc["r_sb"][i] / nsim)},
            "p_conf": float(acc["conf"][i] / nsim), "p_sb": float(acc["sb"][i] / nsim),
            "draft": {"p_pick1": float(pk[i, 0]), "p_top5": float(pk[i, :5].sum()), "p_top10": float(pk[i, :10].sum()),
                      "exp_pick": float((pk[i] * np.arange(1, T + 1)).sum()), "dist": [round(float(x), 5) for x in pk[i]]},
            "magic": mg[i]["magic"], "tragic": mg[i]["tragic"], "clinched": mg[i]["clinched"], "eliminated": mg[i]["eliminated"],
            "next": nxt,
        }
    sbp = sorted(sb_pairs.items(), key=lambda kv: -kv[1])[:20]
    bracket = {"sb_matchups": [{"afc" if S0["conf_names"][conf_ids[0]] == "AFC" else "a": teams[c // 100],
                                "nfc" if S0["conf_names"][conf_ids[1]] == "NFC" else "b": teams[c % 100],
                                "p": cnt / nsim} for c, cnt in sbp],
               "format": f}
    out = {"ok": True, "season": int(season), "teams": out_teams, "bracket": bracket, "n_sims": int(n),
           "runtime_s": round(time.perf_counter() - t0, 3), "remaining_games": int(G_), "sigma_noise": sd_n,
           "hfa": hfa_eff, "drift": drift, "p_tie": ptie, "slow_sims": n_slow, "restart_three": restart_three,
           "through": str(st.get("through")) if st.get("through") is not None else None}
    if rec_i is not None:
        out["_record"] = {k: np.concatenate(v).astype(float) for k, v in rec_parts.items()}
        out["_record"]["se"] = float(se[rec_i])
        out["_record"]["se_draw"] = float(se_draw[rec_i])
    return out


# ── sensitivity curves (the trade simulator) ─────────────────────────────────

SENS_GRID = (-10.0, -8.0, -6.0, -4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0)
SENS_KEYS = ("p_playoffs", "p_div", "p_bye", "p_conf", "p_sb", "mean_wins", "mean_pick")
SENS_PROPOSAL = 3.0          # the target team's rating error is drawn with 3x its sd, then reweighted
_REC_OF = {"p_playoffs": "playoffs", "p_div": "div", "p_bye": "bye", "p_conf": "conf", "p_sb": "sb", "mean_wins": "wins",
           "mean_pick": "pick"}


def _isotonic(y: np.ndarray, w: np.ndarray, increasing: bool = True) -> np.ndarray:
    """Weighted pool-adjacent-violators fit (non-decreasing, or non-increasing with increasing=False)."""
    y = np.asarray(y, float) if increasing else -np.asarray(y, float)
    w = np.maximum(np.asarray(w, float), 1e-12)
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi); wts.append(wi); cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            wts[-2] += wts[-1]; cnt[-2] += cnt[-1]; vals[-2] = v
            vals.pop(); wts.pop(); cnt.pop()
    out = np.repeat(vals, cnt)
    return out if increasing else -out


def curve_from_record(rec: dict, grid=SENS_GRID) -> dict:
    """Importance-sampled outcome curves of one team against a strength shift, from a run whose rating error for
    that team was drawn from N(0, (k se)^2): each simulation is weighted by N(z; shift, se^2) / N(z; 0, (k se)^2), so
    the weighted means are the outcomes with the team's true strength moved by `shift` points per game. Returns
    {key: [value per grid point]} (raw weighted means), "ess" (effective sample size per grid point) and "n"."""
    z = np.asarray(rec["z"], float)
    se, sp = float(rec["se"]), float(rec["se_draw"])
    out: dict[str, Any] = {k: [] for k in SENS_KEYS}
    ess = []
    lq = -0.5 * (z / sp) ** 2 - math.log(sp)
    for dx in grid:
        lw = -0.5 * ((z - dx) / se) ** 2 - math.log(se) - lq
        w = np.exp(lw - lw.max())
        sw = w.sum()
        ess.append(float(sw ** 2 / (w ** 2).sum()))
        for k in SENS_KEYS:
            out[k].append(float((w * rec[_REC_OF[k]]).sum() / sw))
    out["ess"] = ess
    out["n"] = int(len(z))
    return out


def anchor_curve(raw: dict, baseline: dict, grid=SENS_GRID) -> dict:
    """Monotone non-decreasing in the shift (isotonic, weighted by ESS; the mean draft slot rises too, a stronger team
    picks later) and anchored at shift 0 to the published simulation: probabilities
    move by the curve's change in log-odds (clipped at 1e-4), wins and pick by its change in level."""
    g = list(grid)
    i0 = g.index(0.0)
    w = np.asarray(raw.get("ess") or [1.0] * len(g), float)
    out: dict[str, list] = {}
    for k in SENS_KEYS:
        y = np.asarray(raw[k], float)
        iso = _isotonic(y, w, increasing=True)          # all rise with strength (a stronger team picks later)
        b = baseline.get(k)
        if b is None or not np.isfinite(b):
            b = float(iso[i0])
        if k.startswith("p_"):
            eps = 1e-4
            lg = lambda p: np.log(np.clip(p, eps, 1 - eps) / (1 - np.clip(p, eps, 1 - eps)))   # noqa: E731
            v = lg(iso) - lg(np.array([iso[i0]]))[0] + lg(np.array([b]))[0]
            v = 1.0 / (1.0 + np.exp(-v))
            v = np.where(v <= eps * 1.0001, 0.0, v)
            v[i0] = b
            out[k] = [round(float(x), 4) for x in v]
        else:
            v = iso - iso[i0] + b
            out[k] = [round(float(x), 3) for x in v]
    out["ess"] = [int(round(x)) for x in raw.get("ess") or []]
    return out


def sensitivity(season: int, n: int = 2000, seed: int = 101, state: dict | None = None, teams: list[str] | None = None,
                baseline: dict | None = None, grid=SENS_GRID) -> dict:
    """Per-team outcome curves against a strength shift (points per game against an average team, applied to every
    remaining game and to the playoffs): one run of `n` simulations per team in which only that team's rating error
    is drawn from a 3x wider proposal, reweighted to each shift (curve_from_record), made monotone and anchored at 0
    to `baseline` ({team: {p_playoffs, ..., mean_wins, mean_pick}}, the published simulation). Never raises.
    {"ok", "grid", "keys", "teams": {abbr: {key: [...], "ess": [...]}}, "n", "runtime_s"}."""
    t0 = time.perf_counter()
    try:
        st = dict(state or {})
        prep = st.get("prepared") or prepare(season, st)
        st["prepared"] = prep
        tm = list(teams or prep["S0"]["teams"])
        out: dict[str, Any] = {}
        for j, t in enumerate(tm):
            res = simulate(season, n=n, seed=seed + j, state={**st, "z_scale": {t: SENS_PROPOSAL}, "record": t})
            raw = curve_from_record(res["_record"], grid)
            out[t] = anchor_curve(raw, (baseline or {}).get(t) or {}, grid)
        return {"ok": True, "season": int(season), "grid": list(grid), "keys": list(SENS_KEYS), "teams": out, "n": int(n),
                "proposal": SENS_PROPOSAL, "runtime_s": round(time.perf_counter() - t0, 1),
                "remaining_games": int(len(prep["S0"]["remaining"]))}
    except Exception as exc:  # noqa: BLE001
        logger.exception("season_sim sensitivity failed")
        return {"ok": False, "reason": f"error: {exc}", "teams": {}}


def _draft_order(exit_round, pct, sos, key_rand) -> np.ndarray:
    """(S, T) team indices in pick order: exit round ascending, then pct ascending, SOS ascending, random."""
    return np.lexsort((key_rand, np.round(sos, 9), np.round(pct, 9), exit_round.astype(np.float64)), axis=-1)


def _scoring_level(games: pd.DataFrame, season: int) -> float:
    g = games[(games["season"] <= season) & games["played"].astype(bool)].sort_values("date")
    if g.empty:
        return float(GM.DEFAULTS["t_base"])
    tot = g["total"].to_numpy(float)[-600:]
    w = 0.5 ** (np.arange(len(tot))[::-1] / 256.0)
    return float((w * tot).sum() / w.sum())


def for_season(season: int, n: int = 20000, seed: int = 0, through: Any = None, state: dict | None = None) -> dict:
    """simulate() on the data on disk (never raises)."""
    try:
        st = dict(state or {})
        if through is not None:
            st["through"] = through
        return simulate(season, n=n, seed=seed, state=st)
    except Exception as exc:  # noqa: BLE001
        logger.exception("season_sim failed")
        return {"ok": False, "reason": f"error: {exc}", "teams": {}, "n_sims": 0}


def current_order(season: int, games: pd.DataFrame | None = None) -> dict:
    """Standings as they stand (tiebreak.Table on the completed regular-season games): {conf: seed_conference}."""
    try:
        from oddsmarkets.nfl import tiebreak as TB
    except Exception:  # noqa: BLE001
        return {}
    g = games if games is not None else D.games_frame([season])
    rows = [{"home": r.home, "away": r.away, "hs": r.hs, "as": r.as_, "gtype": r.gtype}
            for r in g[(g["season"] == season) & g["played"].astype(bool)].itertuples(index=False)]
    return TB.Table(rows, season).seeds()
