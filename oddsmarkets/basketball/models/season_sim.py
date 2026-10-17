"""
Season simulation: the rest of the regular season, tiebreakers, the play-in, the playoffs and
(NBA) the draft lottery, 20,000 times, vectorised over simulations in chunks.

State
-----
Results so far come from the store: standings games are stype "reg" (ESPN files NBA Cup group
and knockout games as regular season, and canon.stype marks only the Cup final, which does not
count, as "cup"; the WNBA Commissioner's Cup final likewise), "playin" and "post" games are the
postseason. A game after `state["through"]` or not final is unplayed. When a team has fewer
standings games scheduled than the format's total (the NBA Cup's two "TBD" games before the
knockout draw), the shortfall is filled with games between conference rivals that are short too.

Simulated games (per simulation s, game g between home h and away a)
-----------------------------------------------------------------
    margin = mu_g + (x_{s,h,w(g)} - x_{s,a,w(g)}) * pace / 100 + sigma_n * eps
    x_{s,t,w} = z_{s,t} + sum_{k<=w} u_{s,t,k},   z ~ N(0, se_t^2),  u ~ N(0, drift^2)

mu_g is the game model's mean (`game.predict`: ratings, home court, rest, travel, altitude),
z the season-level draw of team t's rating error (its se from the ratings fit) so a team that
is better than its rating is better in every game, and u a weekly random walk. Because sigma
was fitted on walk-forward residuals, which already contain rating error, the game-level
noise is sigma_n = sqrt(max(sigma^2 - mean rating variance, (0.85 sigma)^2)).

Ranking and tiebreakers
-----------------------
Teams are ranked within their seeding group (conference, or the league for the WNBA) by
win percentage. Exact ties are broken by `fmt.tb_two` (two teams) or `fmt.tb_multi` (three or
more): each criterion splits the tied teams into value classes; any class still tied
restarts the procedure from the top with the two-team or multi-team list as appropriate;
a tie surviving every criterion is a random draw. Two-team ties are resolved vectorised,
larger ties one by one. Criteria:

    h2h               win % in games among the tied teams
    div_winner        division winner ahead of a non-winner (winners decided first, same rules)
    div_record        division win % (only when all tied teams share a division)
    conf_record       conference win %
    vs_playoff_own    win % against teams in its own conference at or above the
                      `eligible_n`-th place win % (ties included)
    vs_playoff_other  the same against the other conference
    vs_500            win % against teams finishing .500 or better (WNBA)
    h2h_pd            point differential in games among the tied teams (WNBA)
    pd                point differential in all games

Postseason
----------
NBA: seeds 1-6 go straight in; play-in 7 v 8 (winner = 7th seed), 9 v 10 (loser out), loser of
7 v 8 v winner of 9 v 10 (winner = 8th seed). Fixed bracket 1/8-4/5, 3/6-2/7, no reseeding.
Series games follow the format's home pattern (2-2-1-1-1), the higher seed holding home
court; in the Finals the better regular-season record. Each game is
Phi((x_A - x_B) * pace / 100 +- HCA) / sigma_n) for the end-of-season strengths. Played
play-in games and played series games are fixed; a series in progress continues from its score.
When the regular season is over the seeds are computed once (or taken from `state["seeds"]`),
and observed first-round pairings override the computed bracket slots.

Lottery (NBA)
-------------
The 14 non-playoff teams in reverse order of win % (ties drawn at random) take the slots of the
lottery table (combinations of 1000 for the #1 pick); picks 1-4 are drawn without replacement
in proportion to combinations, the rest go in slot order. Exact slot-to-pick probabilities are
enumerated once; pick trades and protections are not modelled (the pick is the team's own).

Odds conditional on the next game
--------------------------------
`next.if_win` / `if_loss` are interventional: each simulation where the team won (lost) its next
game is weighted by 1 / P(win | that simulation's rating draws) (1 / P(loss | ...)), so the draws
keep their prior distribution and the difference measures the game's own effect, not the fact
that teams which win a game tend to be the stronger draws. `p_win` is the mean of P(win | draws).
Because of that covariance, p_win * if_win + (1 - p_win) * if_loss is close to, not exactly, the
unconditional odds.

Magic numbers (deterministic, no simulation)
--------------------------------------------
For a target "finish in the top k of group X": M_ij = W_j + R_j - W_i + 1 (wins by i plus losses
by j that put j out of reach, the +1 assuming i loses the tiebreak). magic_i = the k-th largest
M_ij over rivals j; clinched when <= 0. tragic_i = the k-th smallest W_i + R_i - W_j + 1;
eliminated when <= 0. Targets: NBA top6, postseason (top 10), division, top_seed; WNBA
postseason (top 8), top_seed.

Rating shifts and sensitivity curves
------------------------------------
`state["shift"]` = {tid: d} adds d (net points per 100) to that team's season-level draw z in every
simulation, which moves every remaining game's margin by d * pace / 100 and its end-of-season strength
in the playoffs by d: the team is d better than its rating for the rest of the season. `sensitivity`
re-runs the whole season at a grid of shifts for one team at a time (the other teams at their
ratings), with the same seed so every run uses the same random numbers and the differences between
shifts are smooth; the trade simulator interpolates these curves (analytics/value.py).
"""
from __future__ import annotations

import itertools
import logging
import math
import time
from datetime import timedelta
from functools import lru_cache
from typing import Any

import numpy as np
from scipy.special import ndtr

from oddsmarkets.basketball.models import _games as G
from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.models.config import SeasonFormat, canonical_alignment, fmt as get_fmt, norm_conf, with_teams

logger = logging.getLogger(__name__)

CRITERIA = ("h2h", "div_winner", "div_record", "conf_record", "vs_playoff_own", "vs_playoff_other", "vs_500", "h2h_pd", "pd")
DRIFT = {"nba": 0.35, "wnba": 0.45}
CHUNK = 5000
EPS = 1e-9


# ── helpers ──────────────────────────────────────────────────────────────────

def bracket_slots(n: int) -> list[int]:
    """Seed numbers in bracket order: 8 -> [1, 8, 4, 5, 3, 6, 2, 7]."""
    if n == 8:
        return [1, 8, 4, 5, 3, 6, 2, 7]                    # the NBA / WNBA display order
    slots = [1]
    while len(slots) < n:
        m = 2 * len(slots) + 1
        slots = [x for s in slots for x in (s, m - s)]
    return slots


@lru_cache(maxsize=8)
def lottery_matrix(table: tuple, draws: int) -> np.ndarray:
    """P[slot, pick] for a lottery table of combinations, `draws` picks drawn, the rest in slot order."""
    n = len(table)
    w = np.array(table, float)
    M = np.zeros((n, n))
    for seq in itertools.permutations(range(n), draws):
        p, left = 1.0, w.sum()
        for t in seq:
            p *= w[t] / left
            left -= w[t]
        if p == 0:
            continue
        for k, t in enumerate(seq):
            M[t, k] += p
        rest = [t for t in range(n) if t not in seq]
        for k, t in enumerate(rest):
            M[t, draws + k] += p
    return M


def _pct(w, l):
    tot = w + l
    return np.where(tot > 0, w / np.maximum(tot, 1), 0.5)


class Ranker:
    """Tiebreak engine over one chunk of simulated final tables."""

    def __init__(self, f: SeasonFormat, conf_id: np.ndarray, div_id: np.ndarray, W, L, H, CW, CL, DW, DL, PD,
                 HPD=None, rng=None):
        self.f = f
        self.conf_id, self.div_id = conf_id, div_id
        self.rng = rng or np.random.default_rng(0)
        self.W, self.L, self.H, self.PD, self.HPD = W, L, H, PD, HPD
        self.pct = _pct(W.astype(float), L.astype(float))
        self.conf_pct = _pct(CW.astype(float), CL.astype(float))
        self.div_pct = _pct(DW.astype(float), DL.astype(float))
        S, T = W.shape
        self.S, self.T = S, T
        same = conf_id[:, None] == conf_id[None, :]
        np.fill_diagonal(same, False)
        other = conf_id[:, None] != conf_id[None, :]
        need = set(f.tb_two) | set(f.tb_multi)
        Hf = H.astype(np.float32)
        HT = np.swapaxes(Hf, 1, 2)
        if {"vs_playoff_own", "vs_playoff_other"} & need:
            elig = np.zeros((S, T), bool)
            for c in np.unique(conf_id):
                mem = np.nonzero(conf_id == c)[0]
                k = min(f.eligible_n, len(mem))
                thr = -np.sort(-self.pct[:, mem], axis=1)[:, k - 1]
                elig[:, mem] = self.pct[:, mem] >= thr[:, None] - EPS
            self.elig = elig
            for name, rel in (("vs_playoff_own", same), ("vs_playoff_other", other)):
                mask = (elig[:, None, :] & rel[None, :, :]).astype(np.float32)
                w = (Hf * mask).sum(2)
                l = (HT * mask).sum(2)
                setattr(self, name, _pct(w, l))
        if "vs_500" in need:
            m5 = (self.pct >= 0.5 - EPS).astype(np.float32)
            mask = m5[:, None, :] * (1 - np.eye(T, dtype=np.float32))[None]
            self.vs_500 = _pct((Hf * mask).sum(2), (HT * mask).sum(2))
        self.divw = np.zeros((S, T), bool)
        if "div_winner" in need:
            for d in np.unique(div_id):
                mem = np.nonzero(div_id == d)[0]
                if len(mem) == 0:
                    continue
                order = self.rank(mem, use_divw=False)
                self.divw[np.arange(S), order[:, 0]] = True

    # criterion values (n, k) for groups g (n, k) in sims s (n,)
    def crit(self, c: str, s: np.ndarray, g: np.ndarray) -> np.ndarray:
        if c == "h2h":
            sub = self.H[s[:, None, None], g[:, :, None], g[:, None, :]].astype(float)
            return _pct(sub.sum(2), sub.sum(1))
        if c == "h2h_pd":
            if self.HPD is None:
                return np.zeros(g.shape)
            return self.HPD[s[:, None, None], g[:, :, None], g[:, None, :]].sum(2)
        if c == "div_winner":
            return self.divw[s[:, None], g].astype(float)
        if c == "div_record":
            dv = self.div_id[g]
            same = (dv == dv[:, :1]).all(1)
            return np.where(same[:, None], self.div_pct[s[:, None], g], 0.0)
        if c == "conf_record":
            return self.conf_pct[s[:, None], g]
        if c == "pd":
            return self.PD[s[:, None], g].astype(float)
        arr = getattr(self, c, None)
        if arr is None:
            return np.zeros(g.shape)
        return arr[s[:, None], g]

    def resolve_pairs(self, s: np.ndarray, g: np.ndarray, use_divw: bool = True) -> np.ndarray:
        """True where g[:, 0] ranks ahead of g[:, 1]."""
        n = len(s)
        res = np.zeros(n, bool)
        und = np.ones(n, bool)
        for c in self.f.tb_two:
            if c == "div_winner" and not use_divw:
                continue
            u = np.nonzero(und)[0]
            if len(u) == 0:
                break
            v = self.crit(c, s[u], g[u])
            d = np.abs(v[:, 0] - v[:, 1]) > EPS
            res[u[d]] = v[d, 0] > v[d, 1]
            und[u[d]] = False
        u = np.nonzero(und)[0]
        res[u] = self.rng.random(len(u)) < 0.5
        return res

    def resolve_one(self, s: int, teams: list[int], use_divw: bool = True) -> list[int]:
        k = len(teams)
        if k <= 1:
            return list(teams)
        if k == 2:
            first = self.resolve_pairs(np.array([s]), np.array([teams]), use_divw)[0]
            return list(teams) if first else [teams[1], teams[0]]
        for c in self.f.tb_multi:
            if c == "div_winner" and not use_divw:
                continue
            v = self.crit(c, np.array([s]), np.array([teams]))[0]
            vals = sorted({round(float(x), 9) for x in v}, reverse=True)
            if len(vals) > 1:
                out = []
                for u in vals:
                    sub = [t for t, x in zip(teams, v) if round(float(x), 9) == u]
                    out += self.resolve_one(s, sub, use_divw)
                return out
        return [teams[i] for i in self.rng.permutation(k)]

    def rank(self, members, use_divw: bool = True) -> np.ndarray:
        """(S, m) team indices of `members` in finishing order."""
        mem = np.asarray(members)
        m = len(mem)
        p = self.pct[:, mem]
        o = np.argsort(-p, axis=1, kind="stable")
        order = mem[o]
        if m < 2:
            return order
        sp_ = np.take_along_axis(p, o, 1)
        eq = np.abs(np.diff(sp_, axis=1)) < EPS
        pad = np.pad(eq, ((0, 0), (1, 1)))
        pair = pad[:, 1:-1] & ~pad[:, :-2] & ~pad[:, 2:]
        si, ji = np.nonzero(pair)
        if len(si):
            g = np.stack([order[si, ji], order[si, ji + 1]], 1)
            first = self.resolve_pairs(si, g, use_divw)
            sw = ~first
            order[si[sw], ji[sw]] = g[sw, 1]
            order[si[sw], ji[sw] + 1] = g[sw, 0]
        long_ = pad[:, 1:-1] & ~pad[:, :-2] & pad[:, 2:]
        for s, j in zip(*np.nonzero(long_)):
            k = j
            while k < m - 1 and eq[s, k]:
                k += 1
            order[s, j:k + 1] = self.resolve_one(int(s), [int(t) for t in order[s, j:k + 1]], use_divw)
        return order


# ── state from the store ─────────────────────────────────────────────────────

def build_state(league: str, season: int, store: dict, through: Any = None) -> dict:
    """Teams, alignment, played tallies and the remaining schedule."""
    league = "wnba" if str(league).lower() == "wnba" else "nba"
    games = store.get("games") or {}
    tdict = store.get("teams") or {}
    cut = G.day(through) if through else None
    std, post, playin = [], [], []
    placeholder = {t for t, v in tdict.items()
                   if str((v or {}).get("abbr") or "").upper() in ("TBD", "TBA") or "tbd" in str((v or {}).get("name") or "").lower()}
    for g in games.values():
        if not g or g.get("status") == "canceled":
            continue
        if str(g.get("home")) in placeholder or str(g.get("away")) in placeholder:
            continue
        st = g.get("stype") or "reg"
        if st == "reg":
            std.append(g)
        elif st == "post":
            post.append(g)
        elif st == "playin":
            playin.append(g)
    teams = sorted({str(g.get("home")) for g in std} | {str(g.get("away")) for g in std})
    if not teams:
        teams = sorted(tdict)
    f = get_fmt(league, season)
    if len(teams) != f.n_teams:
        f = with_teams(f, len(teams))
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    confs, divs = [], []
    for t in teams:
        info = tdict.get(t) or {}
        c, d = norm_conf(info.get("conference")), info.get("division")
        if not c or (league == "nba" and not d):
            cc, dd = canonical_alignment(league, info.get("abbr") or "")
            c, d = c or cc, d or dd
        confs.append(c or "League")
        divs.append(d or c or "League")
    cnames = sorted(set(confs))
    dnames = sorted(set(divs))
    conf_id = np.array([cnames.index(c) for c in confs])
    div_id = np.array([dnames.index(d) for d in divs])

    def played(g):
        return g.get("status") == "post" and g.get("hs") is not None and g.get("as") is not None and \
            (cut is None or (G.local_day(g) or cut) <= cut)

    W = np.zeros(T, int); L = np.zeros(T, int); H = np.zeros((T, T), int)
    CW = np.zeros(T, int); CL = np.zeros(T, int); DW = np.zeros(T, int); DL = np.zeros(T, int)
    PD = np.zeros(T, float); HPD = np.zeros((T, T), float)
    remaining = []
    for g in std:
        h, a = idx.get(str(g.get("home"))), idx.get(str(g.get("away")))
        if h is None or a is None:
            continue
        if played(g):
            m = int(g["hs"]) - int(g["as"])
            w, l = (h, a) if m > 0 else (a, h)
            W[w] += 1; L[l] += 1; H[w, l] += 1
            if conf_id[h] == conf_id[a]:
                CW[w] += 1; CL[l] += 1
                if div_id[h] == div_id[a]:
                    DW[w] += 1; DL[l] += 1
            PD[h] += m; PD[a] -= m; HPD[h, a] += m; HPD[a, h] -= m
        else:
            remaining.append({"id": str(g.get("id")), "home": h, "away": a, "neutral": bool(g.get("neutral")),
                              "day": G.local_day(g), "date": g.get("date"), "postponed": g.get("status") == "postponed"})
    # postseason so far
    SW = np.zeros((T, T), int)
    for g in post:
        h, a = idx.get(str(g.get("home"))), idx.get(str(g.get("away")))
        if h is not None and a is not None and played(g):
            if int(g["hs"]) > int(g["as"]):
                SW[h, a] += 1
            else:
                SW[a, h] += 1
    FP = np.full((T, T), -1, int)
    for g in playin:
        h, a = idx.get(str(g.get("home"))), idx.get(str(g.get("away")))
        if h is not None and a is not None and played(g):
            w = h if int(g["hs"]) > int(g["as"]) else a
            FP[h, a] = FP[a, h] = w
    post_started = bool(SW.sum() or (FP >= 0).any())
    dropped = 0
    if post_started:
        # the postseason has begun: any regular-season game still on the books will not be played
        dropped, remaining = len(remaining), []
    else:
        # a postponed game whose teams already have a full schedule was rescheduled under another id
        sched = W + L + np.bincount([r["home"] for r in remaining if not r["postponed"]] +
                                    [r["away"] for r in remaining if not r["postponed"]], minlength=T)
        keep = [r for r in remaining if not r["postponed"] or (sched[r["home"]] < f.games and sched[r["away"]] < f.games)]
        dropped, remaining = len(remaining) - len(keep), keep
    # fill shortfalls (NBA Cup TBD games)
    have = W + L + np.bincount([r["home"] for r in remaining] + [r["away"] for r in remaining], minlength=T)
    short = np.maximum(0, f.games - have)
    if post_started or short.max() > 4 or have.max() > f.games:
        # not a Cup gap: the season is over, the schedule is incomplete or the format differs
        short[:] = 0
        f = with_teams(f, T, games=int(max(have.max(), 1)))
    fills = 0
    last_day = max([r["day"] for r in remaining if r["day"]] or [cut or G.day(store.get("updated_at")) or None] or [None])
    rng = np.random.default_rng(season)
    while short.sum() > 1 and fills < 5 * T:
        i = int(np.argmax(short))
        cand = [j for j in range(T) if j != i and short[j] > 0]
        if not cand:
            break
        same = [j for j in cand if conf_id[j] == conf_id[i]]
        j = max(same or cand, key=lambda x: short[x])
        h, a = (i, j) if rng.random() < 0.5 else (j, i)
        remaining.append({"id": f"fill-{fills}", "home": h, "away": a, "neutral": False, "day": last_day, "date": None,
                          "postponed": False})
        short[i] -= 1; short[j] -= 1
        fills += 1
    remaining.sort(key=lambda r: (str(r["day"]), r["id"]))
    return {"league": league, "season": int(season), "fmt": f, "teams": teams, "idx": idx, "conf_id": conf_id,
            "div_id": div_id, "conf_names": cnames, "div_names": dnames, "W": W, "L": L, "H": H, "CW": CW, "CL": CL,
            "DW": DW, "DL": DL, "PD": PD, "HPD": HPD, "remaining": remaining, "fills": fills, "SW": SW, "FP": FP,
            "post_started": post_started, "dropped": dropped}


# ── magic numbers ────────────────────────────────────────────────────────────

def magic_numbers(W: np.ndarray, R_: np.ndarray, groups: dict[str, list[int]], targets: dict[str, tuple[str, int]],
                  group_of: dict[str, np.ndarray]) -> list[dict]:
    """
    Per team {"magic": {target: n}, "tragic": {...}, "clinched": {...}, "eliminated": {...}}.
    targets: {name: (grouping, k)}; group_of[grouping][t] = group id of team t.
    """
    T = len(W)
    out = [{"magic": {}, "tragic": {}, "clinched": {}, "eliminated": {}} for _ in range(T)]
    for name, (grouping, k) in targets.items():
        gid = group_of[grouping]
        for i in range(T):
            rivals = [j for j in range(T) if j != i and gid[j] == gid[i]]
            if len(rivals) < k:
                out[i]["magic"][name] = 0
                out[i]["tragic"][name] = None
                out[i]["clinched"][name] = True
                out[i]["eliminated"][name] = False
                continue
            M = sorted((W[j] + R_[j] - W[i] + 1 for j in rivals), reverse=True)
            E = sorted(W[i] + R_[i] - W[j] + 1 for j in rivals)
            mg = int(M[k - 1])
            tg = int(E[k - 1])
            out[i]["magic"][name] = max(0, mg)
            out[i]["tragic"][name] = max(0, tg)
            out[i]["clinched"][name] = mg <= 0
            out[i]["eliminated"][name] = tg <= 0
    return out


# ── the simulation ───────────────────────────────────────────────────────────

def _series(A, B, best_of, pattern, x, scale, hca, sd, SW, rng):
    """Winner (and games) of a best-of series per simulation; A holds home court."""
    S = len(A)
    need = best_of // 2 + 1
    ar = np.arange(S)
    d = (x[ar, A] - x[ar, B]) * scale
    pH = ndtr((d + hca) / sd)
    pA = ndtr((d - hca) / sd)
    wa = SW[A, B].astype(int).copy()
    wb = SW[B, A].astype(int).copy()
    for gi, ch in enumerate(pattern):
        play = (wa + wb == gi) & (wa < need) & (wb < need)
        if not play.any():
            continue
        win = rng.random(S) < (pH if ch == "H" else pA)
        wa += play & win
        wb += play & ~win
    return np.where(wa >= need, A, B), wa + wb


def _single(h, a, x, scale, hca, sd, FP, rng):
    ar = np.arange(len(h))
    p = ndtr(((x[ar, h] - x[ar, a]) * scale + hca) / sd)
    w = np.where(rng.random(len(h)) < p, h, a)
    known = FP[h, a]
    return np.where(known >= 0, known, w)


def simulate(league: str, season: int, n: int = 20000, seed: int = 0, state: dict | None = None) -> dict:
    """
    {"teams": {tid: {"exp_w","exp_l","w_p05","w_p95","seed_dist","p_playoffs","p_playin","p_top6","p_conf",
                     "p_title","p_div","p_reach","p_lottery_pick","magic","tragic","eliminated","clinched",
                     "win_dist","next","current"}},
     "bracket": {...}, "n_sims", "runtime_s", "format", "groups", "notes"}

    state (all optional): "store" (else read from disk), "through" (last day counted as played),
    "ratings" (a fit_ratings result; else ratings.for_season), "params" (game-model parameters),
    "injuries", "seeds" ({tid: seed} once the regular season is over), "drift", "chunk".
    """
    t0 = time.perf_counter()
    state = dict(state or {})
    league = "wnba" if str(league).lower() == "wnba" else "nba"
    store = state.get("store") or G.load_store(league, season) or {}
    cache = state.get("_cache")             # sensitivity runs share the setup (it does not depend on a shift)
    if isinstance(cache, dict) and "S0" in cache:
        S0 = cache["S0"]
    else:
        S0 = build_state(league, season, store, state.get("through"))
        if isinstance(cache, dict):
            cache["S0"] = S0
    f: SeasonFormat = S0["fmt"]
    teams, T = S0["teams"], len(S0["teams"])
    if T < 2:
        return {"ok": False, "reason": "fewer than two teams in the store", "teams": {}, "n_sims": 0}
    rt = state.get("ratings")
    if rt is None:
        try:
            rt = R.for_season(league, season, through=state.get("through"))
        except Exception as exc:  # noqa: BLE001
            logger.info("season_sim: ratings unavailable (%s); using a flat prior", exc)
            rt = {"teams": {}}
    prm = dict(GM.params(league))
    prm.update(state.get("params") or {})
    P = float(rt.get("league_pace") or prm["pace"])
    scale = P / 100.0
    hca = float(prm["hca"])
    sigma = float(prm["sigma"])
    rteams = rt.get("teams") or {}
    se = np.array([float((rteams.get(t) or {}).get("se_net", 4.0)) for t in teams])
    base = np.array([float((rteams.get(t) or {}).get("net", 0.0)) for t in teams])
    rating_var = float(np.mean(2 * se ** 2)) * scale ** 2
    sd_n = math.sqrt(max(sigma ** 2 - rating_var, (0.85 * sigma) ** 2))
    drift = float(state.get("drift", DRIFT[league]))
    # game means for the remaining schedule
    rem = S0["remaining"]
    if isinstance(cache, dict) and "mu" in cache:
        mu = cache["mu"]
    else:
        ctx = GM.context(league, store=store, ratings=rt, injuries=state.get("injuries"), prm=prm)
        mu = np.zeros(len(rem))
        for k, r in enumerate(rem):
            c = dict(ctx)
            c["neutral"] = r["neutral"]
            mu[k] = GM.predict(teams[r["home"]], teams[r["away"]], r["day"], c)["margin"] if r["day"] else \
                ((base[r["home"]] - base[r["away"]]) * scale + (0 if r["neutral"] else hca))
        if isinstance(cache, dict):
            cache["mu"] = mu
    sh = state.get("shift") or {}
    dv = np.array([float(sh.get(t, 0.0) or 0.0) for t in teams]) if sh else None
    G_ = len(rem)
    hi = np.array([r["home"] for r in rem], int)
    ai = np.array([r["away"] for r in rem], int)
    first_day = min([r["day"] for r in rem if r["day"]] or [None]) if rem else None
    week = np.array([((r["day"] - first_day).days // 7) if (r["day"] and first_day) else 0 for r in rem], int)
    n_weeks = int(week.max()) + 1 if G_ else 1
    conf_id, div_id = S0["conf_id"], S0["div_id"]
    is_conf = (conf_id[hi] == conf_id[ai]).astype(np.float32) if G_ else np.zeros(0, np.float32)
    is_div = (is_conf * (div_id[hi] == div_id[ai])).astype(np.float32) if G_ else np.zeros(0, np.float32)
    OHh = np.zeros((G_, T), np.float32)
    OHa = np.zeros((G_, T), np.float32)
    OHh[np.arange(G_), hi] = 1.0
    OHa[np.arange(G_), ai] = 1.0
    OHd = OHh - OHa
    # head-to-head: games grouped by unordered pair (i < j), padded to the longest series of meetings
    pairs: dict[tuple, list] = {}
    for k in range(G_):
        i, j = (hi[k], ai[k]) if hi[k] < ai[k] else (ai[k], hi[k])
        pairs.setdefault((int(i), int(j)), []).append(k)
    PI = np.array([k[0] for k in pairs], int)
    PJ = np.array([k[1] for k in pairs], int)
    width = max((len(v) for v in pairs.values()), default=1)
    PC = np.full((len(pairs), width), G_, int)                 # column G_ is a zero pad
    PS = np.zeros((len(pairs), width), np.float32)             # +1: i at home, -1: i away, 0: pad
    for r, (key, cols) in enumerate(pairs.items()):
        PC[r, :len(cols)] = cols
        PS[r, :len(cols)] = [1.0 if hi[c] == key[0] else -1.0 for c in cols]
    PN = (PS != 0).sum(1).astype(np.int16)
    need_hpd = "h2h_pd" in set(f.tb_two) | set(f.tb_multi)
    # groups
    if f.seeding == "league":
        groups = {"League": list(range(T))}
    else:
        groups = {S0["conf_names"][c]: list(np.nonzero(conf_id == c)[0]) for c in np.unique(conf_id)}
    gnames = list(groups)
    m_max = max(len(v) for v in groups.values())
    bteams = min(f.playoff_teams, min(len(v) for v in groups.values()))
    slots = bracket_slots(bteams)
    n_in_group = int(round(math.log2(bteams))) if bteams > 1 else 0
    rounds = list(f.rounds)
    series = list(f.series)
    patterns = list(f.patterns)
    cross_final = len(groups) > 1
    need_rounds = n_in_group + (1 if cross_final else 0)
    if len(series) < need_rounds:
        series = [series[0]] * (need_rounds - len(series)) + series
        patterns = [patterns[0]] * (len(series) - len(patterns)) + patterns
        rounds = [f"r{i + 1}" for i in range(len(series) - 1)] + ["finals"]
    # a smaller bracket than the format's (tiny leagues, history) drops the earliest rounds
    series, patterns, rounds = series[-need_rounds:], patterns[-need_rounds:], rounds[-need_rounds:]
    # fixed seeds once the regular season is over
    season_done = G_ == 0
    lottery = f.lottery if (f.lottery and league == "nba") else None
    LM = lottery_matrix(tuple(lottery), f.lottery_draws) if lottery else None
    # next game per team
    next_col = {}
    for k, r in enumerate(rem):
        for t in (r["home"], r["away"]):
            next_col.setdefault(t, k)
    # accumulators
    acc = {k: np.zeros(T) for k in ("w", "l", "playoffs", "playin", "top6", "conf", "title", "div")}
    seed_counts = np.zeros((T, m_max))
    reach = np.zeros((len(series), T))
    win_hist = np.zeros((T, f.games + 1))
    lot = np.zeros((T, len(lottery))) if lottery else None
    nx = {t: {"n_win": 0.0, "n": 0.0, "win": np.zeros(5), "loss": np.zeros(5)} for t in next_col}
    pair_n = [dict() for _ in series]
    rng = np.random.default_rng(seed)
    chunk = int(state.get("chunk", CHUNK))
    fixed_order = None
    fixed_divw = None
    if season_done:
        fixed_order, fixed_divw = _fixed_seeds(S0, f, groups, state.get("seeds"), rng)
    done = 0
    while done < n:
        S = min(chunk, n - done)
        done += S
        z = rng.normal(0.0, 1.0, (S, T)) * se[None, :]
        if dv is not None:
            z = z + dv[None, :]
        if G_:
            U = rng.normal(0.0, drift, (S, T, n_weeks)).cumsum(axis=2) if drift > 0 else np.zeros((S, T, n_weeks))
            xg_h = z[:, hi] + U[:, hi, week]
            xg_a = z[:, ai] + U[:, ai, week]
            marg = mu[None, :] + (xg_h - xg_a) * scale + sd_n * rng.standard_normal((S, G_))
            hw = (marg > 0).astype(np.float32)
            lw = 1.0 - hw
            x_end = base[None, :] + z + U[:, :, -1]
        else:
            x_end = base[None, :] + z
        W = np.broadcast_to(S0["W"], (S, T)).astype(np.int32).copy()
        L = np.broadcast_to(S0["L"], (S, T)).astype(np.int32).copy()
        CW = np.broadcast_to(S0["CW"], (S, T)).astype(np.int32).copy()
        CL = np.broadcast_to(S0["CL"], (S, T)).astype(np.int32).copy()
        DW = np.broadcast_to(S0["DW"], (S, T)).astype(np.int32).copy()
        DL = np.broadcast_to(S0["DL"], (S, T)).astype(np.int32).copy()
        PDm = np.broadcast_to(S0["PD"], (S, T)).astype(np.float64).copy()
        Hm = np.broadcast_to(S0["H"], (S, T, T)).astype(np.int16).copy()
        HPD = np.broadcast_to(S0["HPD"], (S, T, T)).astype(np.float32).copy() if need_hpd else None
        if G_:
            W += np.rint(hw @ OHh + lw @ OHa).astype(np.int32)
            L += np.rint(lw @ OHh + hw @ OHa).astype(np.int32)
            hc, lc = hw * is_conf, lw * is_conf
            CW += np.rint(hc @ OHh + lc @ OHa).astype(np.int32)
            CL += np.rint(lc @ OHh + hc @ OHa).astype(np.int32)
            hd, ld = hw * is_div, lw * is_div
            DW += np.rint(hd @ OHh + ld @ OHa).astype(np.int32)
            DL += np.rint(ld @ OHh + hd @ OHa).astype(np.int32)
            PDm += marg @ OHd.astype(np.float64)
            hwx = np.concatenate([hw, np.zeros((S, 1), np.float32)], 1)
            gw = hwx[:, PC]                                          # (S, pairs, width)
            wi = np.where(PS > 0, gw, np.where(PS < 0, 1.0 - gw, 0.0)).sum(2).astype(np.int16)
            Hm[:, PI, PJ] += wi
            Hm[:, PJ, PI] += PN[None, :] - wi
            if need_hpd:
                mx = np.concatenate([marg, np.zeros((S, 1))], 1)[:, PC]
                di = (mx * PS[None]).sum(2).astype(np.float32)        # point differential of i vs j
                HPD[:, PI, PJ] += di
                HPD[:, PJ, PI] -= di
        ar = np.arange(S)
        if fixed_order is not None:
            orders = {gname: np.broadcast_to(o, (S, len(o))).copy() for gname, o in fixed_order.items()}
            divw = np.broadcast_to(fixed_divw, (S, T))
        else:
            rk = Ranker(f, conf_id, div_id, W, L, Hm, CW, CL, DW, DL, PDm, HPD, rng)
            orders = {gname: rk.rank(mem) for gname, mem in groups.items()}
            divw = rk.divw
        pct = _pct(W.astype(float), L.astype(float))
        acc["w"] += W.sum(0)
        win_hist += np.bincount((np.arange(T)[None, :] * (f.games + 1) + np.clip(W, 0, f.games)).ravel(),
                                minlength=T * (f.games + 1)).reshape(T, f.games + 1)
        acc["div"] += divw.sum(0)
        made = np.zeros((S, T), bool)
        top6 = np.zeros((S, T), bool)
        pin = np.zeros((S, T), bool)
        conf_champ = np.zeros((S, T), bool)
        champs = []
        for gname, order in orders.items():
            m = order.shape[1]
            seed_counts[:, :m] += np.bincount((order * m + np.arange(m)[None, :]).ravel(),
                                              minlength=T * m).reshape(T, m)
            top6[ar[:, None], order[:, :min(6, m)]] = True
            seeds = order[:, :bteams].copy()
            if f.playin and m >= f.playin_seeds[1]:
                s7, s8, s9, s10 = (order[:, k] for k in range(6, 10))
                pin[ar[:, None], order[:, 6:10]] = True
                w1 = _single(s7, s8, x_end, scale, hca, sd_n, S0["FP"], rng)
                l1 = np.where(w1 == s7, s8, s7)
                w2 = _single(s9, s10, x_end, scale, hca, sd_n, S0["FP"], rng)
                w3 = _single(l1, w2, x_end, scale, hca, sd_n, S0["FP"], rng)
                seeds[:, 6] = w1
                seeds[:, 7] = w3
            made[ar[:, None], seeds] = True
            # bracket: slot k holds seed slots[k]
            cur = seeds[:, [s - 1 for s in slots]]
            cur_seed = np.broadcast_to(np.array(slots), cur.shape).copy()
            for r in range(n_in_group):
                reach[r] += np.bincount(cur.ravel(), minlength=T)
                if not cross_final and r == n_in_group - 1:
                    conf_champ[ar[:, None], cur] = True          # single-group league: the finalists
                nxt, nxt_seed = [], []
                for k in range(0, cur.shape[1], 2):
                    a, b = cur[:, k], cur[:, k + 1]
                    sa, sb = cur_seed[:, k], cur_seed[:, k + 1]
                    hi_t = np.where(sa < sb, a, b)
                    lo_t = np.where(sa < sb, b, a)
                    win, _ = _series(hi_t, lo_t, series[r], patterns[r], x_end, scale, hca, sd_n, S0["SW"], rng)
                    _tally_pairs(pair_n[r], hi_t, lo_t, win)
                    nxt.append(win)
                    nxt_seed.append(np.minimum(sa, sb))
                cur = np.stack(nxt, 1)
                cur_seed = np.stack(nxt_seed, 1)
            champs.append(cur[:, 0])
        if cross_final and len(champs) >= 2:
            a, b = champs[0], champs[1]
            for c in champs:
                conf_champ[ar, c] = True
            reach[-1] += np.bincount(np.concatenate([a, b]), minlength=T)
            better = (pct[ar, a] > pct[ar, b] + EPS) | ((np.abs(pct[ar, a] - pct[ar, b]) <= EPS) &
                                                        (PDm[ar, a] >= PDm[ar, b]))
            hi_t, lo_t = np.where(better, a, b), np.where(better, b, a)
            title, _ = _series(hi_t, lo_t, series[-1], patterns[-1], x_end, scale, hca, sd_n, S0["SW"], rng)
            _tally_pairs(pair_n[-1], hi_t, lo_t, title)
        else:
            title = champs[0]
        acc["l"] += L.sum(0)
        acc["title"] += np.bincount(title, minlength=T)
        acc["playoffs"] += made.sum(0)
        acc["top6"] += top6.sum(0)
        acc["playin"] += pin.sum(0)
        acc["conf"] += conf_champ.sum(0)
        if lottery is not None:
            non = ~made
            key = np.where(non, pct + rng.random((S, T)) * 1e-7, 9.0)
            lo = np.argsort(key, axis=1)[:, :len(lottery)]
            nl = min(len(lottery), int(non.sum(1).min()))
            lo = lo[:, :nl]
            np.add.at(lot, lo.ravel(), np.tile(LM[:nl, :], (S, 1)))
        # conditional on the next game. Sims where the team won its next game over-represent draws in
        # which it is strong (z, U), so raw conditioning mixes the game's effect with selection on the
        # team's rating. Each sim is reweighted by 1 / P(this result | its draws) so that, within the
        # wins and within the losses, the rating draws keep their prior distribution: if_win / if_loss
        # estimate the odds with the result forced and everything else as drawn.
        if G_:
            outs = np.stack([made, top6, conf_champ, np.zeros((S, T), bool), pin], 2)
            outs[ar, title, 3] = True
            for t, k in next_col.items():
                is_home = rem[k]["home"] == t
                won = hw[:, k] > 0.5 if is_home else hw[:, k] < 0.5
                p_home = ndtr((mu[k] + (xg_h[:, k] - xg_a[:, k]) * scale) / sd_n)
                p_t = np.clip(p_home if is_home else 1.0 - p_home, 1e-3, 1 - 1e-3)
                ww, wl = 1.0 / p_t, 1.0 / (1.0 - p_t)
                rec = nx[t]
                rec["n"] += S
                rec["n_win"] += won.sum()
                rec["p_sum"] = rec.get("p_sum", 0.0) + float(p_t.sum())
                rec["win"] += (outs[won, t, :] * ww[won, None]).sum(0)
                rec["loss"] += (outs[~won, t, :] * wl[~won, None]).sum(0)
                rec["w_win"] = rec.get("w_win", 0.0) + float(ww[won].sum())
                rec["w_loss"] = rec.get("w_loss", 0.0) + float(wl[~won].sum())
    nsim = float(n)
    # magic numbers
    Rm = np.bincount(np.concatenate([hi, ai]), minlength=T) if G_ else np.zeros(T, int)
    if league == "nba" and f.seeding == "conference":
        targets = {"top6": ("conf", 6), "postseason": ("conf", f.playin_seeds[1] if f.playin else f.playoff_teams),
                   "division": ("div", 1), "top_seed": ("conf", 1)}
    else:
        targets = {"postseason": ("conf" if f.seeding == "conference" else "league", f.playoff_teams),
                   "top_seed": ("conf" if f.seeding == "conference" else "league", 1)}
    group_of = {"conf": conf_id, "div": div_id, "league": np.zeros(T, int)}
    mg = magic_numbers(S0["W"], Rm, groups, targets, group_of)
    # current standings order
    rk0 = Ranker(f, conf_id, div_id, S0["W"][None], S0["L"][None], S0["H"][None].astype(np.int16), S0["CW"][None],
                 S0["CL"][None], S0["DW"][None], S0["DL"][None], S0["PD"][None],
                 S0["HPD"][None].astype(np.float32) if need_hpd else None, np.random.default_rng(seed + 1))
    cur_rank = {}
    for gname, mem in groups.items():
        o = rk0.rank(mem)[0]
        lead_w, lead_l = S0["W"][o[0]], S0["L"][o[0]]
        for pos, t in enumerate(o):
            cur_rank[int(t)] = (pos + 1, float(((lead_w - S0["W"][t]) + (S0["L"][t] - lead_l)) / 2.0))
    out_teams = {}
    wh = win_hist / nsim
    cdf = wh.cumsum(1)
    for i, t in enumerate(teams):
        q05 = int(np.searchsorted(cdf[i], 0.05))
        q95 = int(np.searchsorted(cdf[i], 0.95))
        gi = 0 if f.seeding == "league" else next(k for k, g in enumerate(gnames) if i in groups[g])
        m = len(groups[gnames[gi]])
        exp_w = acc["w"][i] / nsim
        nxt = None
        if i in nx and nx[i]["n"] > 0:
            rec = nx[i]
            k = next_col[i]
            r = rem[k]
            ww, wl = rec.get("w_win", 0.0), rec.get("w_loss", 0.0)
            keys = ("p_playoffs", "p_top6", "p_conf", "p_title", "p_playin")
            nxt = {"game": r["id"], "date": str(r["day"]) if r["day"] else None,
                   "opp": teams[r["away"] if r["home"] == i else r["home"]], "home": r["home"] == i,
                   "p_win": float(rec.get("p_sum", rec["n_win"]) / rec["n"]),
                   "if_win": {k_: float(v / ww) if ww > 0 else None for k_, v in zip(keys, rec["win"])},
                   "if_loss": {k_: float(v / wl) if wl > 0 else None for k_, v in zip(keys, rec["loss"])}}
        out_teams[t] = {
            "conference": S0["conf_names"][conf_id[i]], "division": S0["div_names"][div_id[i]],
            "current": {"w": int(S0["W"][i]), "l": int(S0["L"][i]), "conf_w": int(S0["CW"][i]), "conf_l": int(S0["CL"][i]),
                        "div_w": int(S0["DW"][i]), "div_l": int(S0["DL"][i]), "pd": float(S0["PD"][i]),
                        "remaining": int(Rm[i]), "rank": cur_rank.get(i, (None, None))[0],
                        "gb": cur_rank.get(i, (None, None))[1]},
            "rating": float(base[i]), "rating_se": float(se[i]),
            "exp_w": float(exp_w), "exp_l": float(acc["l"][i] / nsim),
            "w_p05": q05, "w_p95": q95,
            "seed_dist": [float(x) for x in seed_counts[i, :m] / nsim],
            "p_playoffs": float(acc["playoffs"][i] / nsim), "p_playin": float(acc["playin"][i] / nsim),
            "p_top6": float(acc["top6"][i] / nsim), "p_conf": float(acc["conf"][i] / nsim),
            "p_title": float(acc["title"][i] / nsim), "p_div": float(acc["div"][i] / nsim) if league == "nba" else None,
            "p_reach": {rounds[r]: float(reach[r][i] / nsim) for r in range(len(series))},
            "p_lottery_pick": [float(x) for x in lot[i] / nsim] if lot is not None else None,
            "magic": mg[i]["magic"], "tragic": mg[i]["tragic"], "clinched": mg[i]["clinched"],
            "eliminated": mg[i]["eliminated"],
            "win_dist": [round(float(x), 5) for x in wh[i]],
            "next": nxt,
        }
    bracket = {"rounds": rounds, "series": series, "patterns": patterns, "groups": {g: [teams[i] for i in v] for g, v in groups.items()},
               "slots": slots, "matchups": {}}
    for r in range(len(series)):
        rows = sorted(pair_n[r].items(), key=lambda kv: -kv[1][0])[:24]
        bracket["matchups"][rounds[r]] = [{"home_court": teams[a], "other": teams[b], "p": float(c / nsim),
                                           "p_home_court_wins": float(w / c) if c else None} for (a, b), (c, w) in rows]
    notes = []
    if S0["fills"]:
        notes.append(f"{S0['fills']} unscheduled standings games filled with conference rivals (NBA Cup TBD games)")
    if fixed_order is not None:
        notes.append("regular season complete: seeds fixed")
    if S0["dropped"]:
        notes.append(f"{S0['dropped']} unplayed regular-season games ignored (postseason started or rescheduled)")
    return {"ok": True, "league": league, "season": int(season), "teams": out_teams, "bracket": bracket, "n_sims": int(n),
            "runtime_s": round(time.perf_counter() - t0, 3), "format": f.as_dict(), "groups": list(groups),
            "remaining_games": G_, "sigma_noise": sd_n, "hca": hca, "notes": notes,
            "through": str(state.get("through")) if state.get("through") else None}


SENS_SHIFTS = (-6.0, -3.0, -1.5, 0.0, 1.5, 3.0, 6.0)      # net points per 100 (a star for a replacement player is ~4-6)
SENS_SIMS = 2000


def _sens_values(rec: dict) -> dict:
    lot = rec.get("p_lottery_pick")
    return {"exp_w": rec.get("exp_w"), "p_playoffs": rec.get("p_playoffs"), "p_top6": rec.get("p_top6"),
            "p_conf": rec.get("p_conf"), "p_title": rec.get("p_title"),
            "p_top4": float(sum(lot[:4])) if lot else None}


def sensitivity(league: str, season: int, shifts=SENS_SHIFTS, n: int = SENS_SIMS, seed: int = 0, state: dict | None = None,
                teams: list[str] | None = None) -> dict:
    """{"ok", "shifts", "n_sims", "keys", "teams": {tid: {key: [value at each shift]}}, "runtime_s"}: each team's
    expected wins, playoff (play-in winners included), top-six, Finals, title and (NBA) top-four-pick odds when
    that team alone is `shift` net points per 100 better for the rest of the season. Every run re-simulates
    the whole season with the same seed (common random numbers) and shares the setup."""
    t0 = time.perf_counter()
    st = dict(state or {})
    st["_cache"] = {}
    st.pop("shift", None)
    shifts = [float(x) for x in shifts]
    base = simulate(league, season, n=n, seed=seed, state=st)
    if not base.get("ok", True) or not base.get("teams"):
        return {"ok": False, "reason": base.get("reason") or "no simulation", "teams": {}}
    tids = [t for t in (teams or list(base["teams"])) if t in base["teams"]]
    keys = list(_sens_values(next(iter(base["teams"].values()))))
    out: dict[str, dict] = {}
    for t in tids:
        cols = {}
        for d in shifts:
            rec = base["teams"][t] if d == 0.0 else \
                simulate(league, season, n=n, seed=seed, state={**st, "shift": {t: d}})["teams"][t]
            cols[d] = _sens_values(rec)
        out[t] = {k: [None if cols[d][k] is None else round(float(cols[d][k]), 5) for d in shifts] for k in keys}
    keys = [k for k in keys if any(any(v is not None for v in out[t][k]) for t in out)]
    for t in out:
        out[t] = {k: out[t][k] for k in keys}
    return {"ok": True, "shifts": shifts, "n_sims": int(n), "seed": int(seed), "keys": keys, "teams": out,
            "runtime_s": round(time.perf_counter() - t0, 2)}


def _tally_pairs(store: dict, hi_t: np.ndarray, lo_t: np.ndarray, win: np.ndarray) -> None:
    code = hi_t.astype(np.int64) * 10000 + lo_t
    u, inv, cnt = np.unique(code, return_inverse=True, return_counts=True)
    wins = np.bincount(inv, weights=(win == hi_t).astype(float), minlength=len(u))
    for c, n_, w in zip(u, cnt, wins):
        key = (int(c // 10000), int(c % 10000))
        prev = store.get(key, (0, 0.0))
        store[key] = (prev[0] + int(n_), prev[1] + float(w))


def _fixed_seeds(S0: dict, f: SeasonFormat, groups: dict, seeds_override: dict | None, rng) -> tuple[dict, np.ndarray]:
    """Final standings once the regular season is over: computed once, overridden by `seeds` and by
    observed first-round pairings."""
    rk = Ranker(f, S0["conf_id"], S0["div_id"], S0["W"][None], S0["L"][None], S0["H"][None].astype(np.int16),
                S0["CW"][None], S0["CL"][None], S0["DW"][None], S0["DL"][None], S0["PD"][None],
                S0["HPD"][None].astype(np.float32), rng)
    out = {}
    idx = S0["idx"]
    for g, mem in groups.items():
        order = list(rk.rank(mem)[0])
        if seeds_override:
            ov = {idx[t]: int(s) for t, s in seeds_override.items() if t in idx and idx[t] in mem}
            if ov:
                fixed = sorted(ov, key=lambda t: ov[t])
                rest = [t for t in order if t not in ov]
                order = fixed + rest
        order = _apply_observed_pairs(order, S0["SW"], f)
        out[g] = np.array(order, int)
    return out, rk.divw[0]


def _apply_observed_pairs(order: list[int], SW: np.ndarray, f: SeasonFormat) -> list[int]:
    """If first-round series were played between pairs our seeding does not produce, swap seeds of
    tied-looking teams so each observed pair occupies one bracket slot (higher computed seed keeps home court)."""
    n = min(f.playoff_teams, len(order))
    if n < 2:
        return order
    played = (SW + SW.T) > 0
    top = order[:n]
    slots = bracket_slots(n)
    want = [(top[slots[k] - 1], top[slots[k + 1] - 1]) for k in range(0, n, 2)]
    obs = [(a, b) for a in top for b in top if a < b and played[a, b]]
    if not obs or all(played[a, b] for a, b in want):
        return order
    # rebuild: keep each observed pair's better-seeded team in place, put its opponent in the partner seed
    pos = {t: k for k, t in enumerate(order)}
    new = list(order)
    for a, b in obs:
        hi_t, lo_t = (a, b) if pos[a] < pos[b] else (b, a)
        s_hi = new.index(hi_t) + 1
        if s_hi > n:
            continue
        k = slots.index(s_hi)
        partner_seed = slots[k + 1] if k % 2 == 0 else slots[k - 1]
        j, cur = new.index(lo_t), partner_seed - 1
        if j != cur and cur < len(new):
            new[j], new[cur] = new[cur], new[j]
    return new


def for_season(league: str, season: int, n: int = 20000, seed: int = 0, through: Any = None) -> dict:
    """simulate() on the store on disk (never raises: failures return {"ok": False, "reason"})."""
    try:
        return simulate(league, season, n=n, seed=seed, state={"through": through} if through else None)
    except Exception as exc:  # noqa: BLE001
        logger.exception("season_sim failed")
        return {"ok": False, "reason": f"error: {exc}", "teams": {}, "n_sims": 0}
