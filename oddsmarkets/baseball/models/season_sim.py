"""
Season and postseason simulation (MLB, 12-team format from 2022).

Series odds (closed form)
-------------------------
A best-of-n series in which team A holds home-field advantage follows a home pattern over game numbers:
    Wild Card Series   best of 3, every game at the higher seed            "HHH"
    Division Series    best of 5, 2-2-1                                    "HHAAH"
    LCS / World Series best of 7, 2-3-2                                    "HHAAAHH"
With p_h = P(A wins a game at home) and p_a = P(A wins away), P(A wins from wins (a, b)) is the recursion
    f(a, b) = 1 if a = need;  0 if b = need;  else p_g f(a+1, b) + (1 - p_g) f(a, b+1),  g = a + b
(`series_prob`, exact; the simulation reproduces it).

Bracket (per league, seeds 1-6)
-------------------------------
Seeds 1-3: division winners by record; 4-6: the best three other teams. WC: 3 v 6 and 4 v 5 at the higher
seed. DS: 1 v winner(4/5), 2 v winner(3/6), higher seed home in games 1, 2, 5. LCS: the better seed holds
home field. World Series: the better regular-season record holds home field (ties: random).
Played series games are fixed from the store (games with gtype F / D / L / W); a series in progress continues
from its score; a finished series fixes its winner. Observed pairings override computed seeds (a team's
home WC series reveals its seed slot).

Game probabilities
------------------
P[i, j] = P(team i beats team j at i's park), from the game model (`pair_matrix_sim`: our lineups and the
average of each team's top four starters, bullpens, home field) or from team ratings (log5 with home field:
logit P = r_i - r_j + HFA). Each simulation draws a team-strength error z_t ~ N(0, se_t) (logit) held for
the whole postseason (or season): logit p = logit P[i, j] + z_i - z_j.

Regular season
--------------
Unplayed regular-season games are simulated with the same rule; standings, then tiebreakers (2022+ rules,
in order): head-to-head win % among the tied teams, intradivision win %, intraleague win %, then a random
draw (the "last half of intraleague games" rules are not modelled). Division winners first, then seeds.
Outputs: P(division), P(wild card), P(bye: seeds 1-2), P(postseason), seed distribution, mean wins (p05/p95),
then the bracket's round odds. Magic numbers (deterministic): for "finish ahead of rival j", M = G - W_i - L_j + 1;
the division magic number is the max over division rivals of W_j + R_j - W_i + 1 (Hardwood's formula).

Odds conditional on the next game (interventional, as in Hardwood): each simulation in which the team wins
(loses) its next game is weighted by 1 / P(win | that simulation's strength draws) (1 / P(loss | ...)),
so the draws keep their prior distribution and the difference measures the game's own effect.
"""
from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Callable, Iterable

import numpy as np

from oddsmarkets.baseball.models import _dio

logger = logging.getLogger(__name__)

N_SIMS = 20000
CHUNK = 5000
HFA_LOGIT = 0.12                    # ~ .530 home win rate between equal teams (2026 regular season: .529)
RATING_PER_RUN = 0.40               # logit per run of run differential per game
RATING_G0 = 50.0                    # games of prior when regressing run differential
RD_SD = 4.3                         # sd of single-game run differential
ROUNDS = ("WC", "DS", "CS", "WS")
BEST_OF = {"WC": 3, "DS": 5, "CS": 7, "WS": 7}
PATTERN = {"WC": "HHH", "DS": "HHAAH", "CS": "HHAAAHH", "WS": "HHAAAHH"}
GTYPE_ROUND = {"F": "WC", "D": "DS", "L": "CS", "W": "WS"}
FINAL_STATUS = ("final", "completed", "game over", "post", "f", "o")


def _sig(x):
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


# ── closed form ──────────────────────────────────────────────────────────────

def series_prob(p_home: float, p_away: float, best_of: int, pattern: str | None = None, wa: int = 0, wb: int = 0) -> float:
    """P(A wins the series) given P(A wins at home) / away, the home pattern from A's view and the current score."""
    need = best_of // 2 + 1
    pattern = pattern or ("H" * best_of)
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def f(a, b):
        if a >= need:
            return 1.0
        if b >= need:
            return 0.0
        g = a + b
        p = p_home if pattern[g] == "H" else p_away
        return p * f(a + 1, b) + (1 - p) * f(a, b + 1)

    return float(f(wa, wb))


def series_length(p_home: float, p_away: float, best_of: int, pattern: str, wa: int = 0, wb: int = 0) -> dict:
    """{"A": {games: prob}, "B": {games: prob}} for the series' remaining paths."""
    need = best_of // 2 + 1
    out = {"A": {}, "B": {}}

    def rec(a, b, pr):
        if a >= need:
            out["A"][a + b] = out["A"].get(a + b, 0.0) + pr
            return
        if b >= need:
            out["B"][a + b] = out["B"].get(a + b, 0.0) + pr
            return
        p = p_home if pattern[a + b] == "H" else p_away
        rec(a + 1, b, pr * p)
        rec(a, b + 1, pr * (1 - p))

    rec(wa, wb, 1.0)
    return out


# ── store helpers ────────────────────────────────────────────────────────────

def is_final(g: dict) -> bool:
    st = str(g.get("status") or "").strip().lower()
    if g.get("hs") is None or g.get("as") is None:
        return False
    return any(st == s or st.startswith(s + " ") or (len(s) > 2 and s in st) for s in FINAL_STATUS)


def team_leagues(store: dict) -> tuple[dict, dict]:
    """(tid -> "AL"/"NL", tid -> division)"""
    lg, dv = {}, {}
    for tid, t in (store.get("teams") or {}).items():
        lg[str(tid)] = str(t.get("league") or "")
        dv[str(tid)] = str(t.get("division") or "")
    return lg, dv


def real_teams(store: dict) -> list[str]:
    """Teams in a league (the store also holds bracket placeholders such as "NL Wild Card winner")."""
    return sorted((str(t) for t, v in (store.get("teams") or {}).items()
                   if str((v or {}).get("league") or "") in ("AL", "NL") and not (v or {}).get("placeholder")
                   and (v or {}).get("division")), key=str)


def regular_games(store: dict) -> list[dict]:
    return [g for g in (store.get("games") or {}).values() if (g.get("gtype") or "R") == "R"]


# ── team ratings ─────────────────────────────────────────────────────────────

def team_ratings(store: dict, through: Any = None, prior: dict | None = None, g0: float = RATING_G0) -> dict:
    """{tid: {"r": logit rating, "se", "g", "rd_pg"}} from regressed run differential (+ an optional prior)."""
    th = _dio.to_date(through) if through else None
    rs, ra, gp = {}, {}, {}
    for g in regular_games(store):
        if not is_final(g):
            continue
        if th and (_dio.to_date(g.get("date")) or th) >= th:
            continue
        h, a = str(g["home"]), str(g["away"])
        hs, as_ = int(g["hs"]), int(g["as"])
        rs[h] = rs.get(h, 0) + hs
        ra[h] = ra.get(h, 0) + as_
        rs[a] = rs.get(a, 0) + as_
        ra[a] = ra.get(a, 0) + hs
        gp[h] = gp.get(h, 0) + 1
        gp[a] = gp.get(a, 0) + 1
    out = {}
    for t in real_teams(store):
        n = gp.get(t, 0)
        rd = (rs.get(t, 0) - ra.get(t, 0))
        pr = (prior or {}).get(t, 0.0)
        r = (RATING_PER_RUN * rd + g0 * pr) / (n + g0)
        se = RATING_PER_RUN * RD_SD / math.sqrt(n + g0) * 0.6
        out[t] = {"r": float(r), "se": float(se), "g": n, "rd_pg": round(rd / n, 3) if n else None}
    return out


def matrix_from_ratings(teams: list[str], ratings: dict, hfa: float = HFA_LOGIT) -> np.ndarray:
    r = np.array([ratings.get(t, {}).get("r", 0.0) for t in teams])
    return _sig(r[:, None] - r[None, :] + hfa)


def pair_matrix_sim(teams: list[str], ctx, n: int = 4000, seed: int = 0, top_starters: int = 4,
                    on: Any = None) -> np.ndarray:
    """P[i, j] from the game model: each team's latest lineup v a right-hander, its top starters' average, bullpen."""
    from oddsmarkets.baseball.models import game_sim as G
    from oddsmarkets.baseball.models.game_inputs import _arr
    d = _dio.to_date(on) or date(ctx.season, 10, 1)
    sides = {}
    for t in teams:
        ab = ctx.tid_to_abbr.get(t, t)
        A = ctx.usage.apps
        st = A[(A["team"] == ab) & A["start"].astype(bool) & (A["date"] < d.isoformat())]
        recent = st.sort_values("date").tail(30)
        cand = list(dict.fromkeys(reversed(recent["pitcher"].tolist())))[:8]
        cand = sorted(cand, key=lambda p: ctx.quality(p))[:top_starters] or [None]
        sps = [ctx.pitcher(p, d) for p in cand]
        comp = {"pid": None, "throws": "R" if sum(s["throws"] == "R" for s in sps) * 2 >= len(sps) else "L",
                "rates": {h: _arr(np.mean([s["rates"][h] for s in sps], axis=0)) for h in ("L", "R")},
                "pc_mean": float(np.mean([s["pc_mean"] for s in sps])), "pc_sd": 12.0, "ppa": 1.0}
        lu = ctx.usage.lineup(ab, d, "R") or []
        hitters = [ctx.hitter(x) for x in lu[:9]]
        while len(hitters) < 9:
            hitters.append(G.neutral_hitter(ctx.league, "R"))
        sides[t] = {"lineup": hitters, "starter": comp, "bullpen": ctx.bullpen(ab, d)}
    T = len(teams)
    P = np.full((T, T), 0.5)
    k = 0
    for i, a in enumerate(teams):
        for j, b in enumerate(teams):
            if i == j:
                continue
            spec = {"home": sides[a], "away": sides[b], "league": ctx.league, "auto_runner": False}
            P[i, j] = G.simulate(spec, n=n, seed=seed + k)["p_home"]
            k += 1
    return P


# ── series simulation (vectorised) ───────────────────────────────────────────

def _series(A, B, rnd: str, L: np.ndarray, z: np.ndarray, rng, observed: dict) -> tuple[np.ndarray, np.ndarray]:
    """Winner and number of games per simulation; A holds home field. L = logit P[i, j]."""
    S = len(A)
    best_of, pattern = BEST_OF[rnd], PATTERN[rnd]
    need = best_of // 2 + 1
    ar = np.arange(S)
    wa = np.zeros(S, int)
    wb = np.zeros(S, int)
    if observed:
        for (r, x, y), (wx, wy) in observed.items():
            if r != rnd:
                continue
            m1 = (A == x) & (B == y)
            m2 = (A == y) & (B == x)
            wa[m1], wb[m1] = wx, wy
            wa[m2], wb[m2] = wy, wx
    zA, zB = z[ar, A], z[ar, B]
    pH = _sig(L[A, B] + zA - zB)               # A at home
    pA = 1.0 - _sig(L[B, A] + zB - zA)          # A away
    for gi, ch in enumerate(pattern):
        play = (wa + wb == gi) & (wa < need) & (wb < need)
        if not play.any():
            continue
        win = rng.random(S) < (pH if ch == "H" else pA)
        wa += play & win
        wb += play & ~win
    return np.where(wa >= need, A, B), wa + wb


def postseason_sim(seeds: dict[str, list[int]], L: np.ndarray, n: int, rng, z: np.ndarray | None = None,
                   observed: dict | None = None, record: np.ndarray | None = None, T: int | None = None) -> dict:
    """
    seeds: {"AL": [t1..t6], "NL": [...]} as team indices per simulation-independent bracket, or arrays [S, 6].
    record: [S, T] win % for the World Series home field. Returns per-round reach counts and series results.
    """
    S = n
    T = T or L.shape[0]
    z = np.zeros((S, T)) if z is None else z
    observed = observed or {}
    reach = {k: np.zeros(T) for k in ("DS", "CS", "WS", "champion")}
    series_out = {}
    pennant = {}
    for lg in ("AL", "NL"):
        sd = np.asarray(seeds[lg])
        sd = np.tile(sd, (S, 1)) if sd.ndim == 1 else sd
        s1, s2, s3, s4, s5, s6 = (sd[:, i] for i in range(6))
        w36, g36 = _series(s3, s6, "WC", L, z, rng, observed)
        w45, g45 = _series(s4, s5, "WC", L, z, rng, observed)
        for t_arr in (s1, s2, w36, w45):
            np.add.at(reach["DS"], t_arr, 1)
        d1, _ = _series(s1, w45, "DS", L, z, rng, observed)
        d2, _ = _series(s2, w36, "DS", L, z, rng, observed)
        # LCS: the better seed (s1-branch winner is always the better seed unless 4/5 beat 1... compare seed numbers)
        seed_no = np.zeros((S, T)) + 99
        for i in range(6):
            seed_no[np.arange(S), sd[:, i]] = i + 1
        a_better = seed_no[np.arange(S), d1] <= seed_no[np.arange(S), d2]
        A = np.where(a_better, d1, d2)
        B = np.where(a_better, d2, d1)
        for t_arr in (d1, d2):
            np.add.at(reach["CS"], t_arr, 1)
        champ, _ = _series(A, B, "CS", L, z, rng, observed)
        np.add.at(reach["WS"], champ, 1)
        pennant[lg] = champ
        series_out[lg] = {"wc36": w36, "wc45": w45, "ds1": d1, "ds2": d2, "lcs": champ}
    al, nl = pennant["AL"], pennant["NL"]
    ar = np.arange(S)
    if record is None:
        rec_al = rng.random(S)
        rec_nl = rng.random(S)
    else:
        rec_al = record[ar, al] + rng.random(S) * 1e-6
        rec_nl = record[ar, nl] + rng.random(S) * 1e-6
    A = np.where(rec_al >= rec_nl, al, nl)
    B = np.where(rec_al >= rec_nl, nl, al)
    champ, games = _series(A, B, "WS", L, z, rng, observed)
    np.add.at(reach["champion"], champ, 1)
    return {"reach": reach, "series": series_out, "champion": champ, "ws_games": games, "pennant": pennant}


# ── standings and tiebreakers ────────────────────────────────────────────────

def rank_keys(W: np.ndarray, G: np.ndarray, H: np.ndarray, div_w: np.ndarray, div_g: np.ndarray, lg_w: np.ndarray,
              lg_g: np.ndarray, same_lg: np.ndarray, rng) -> np.ndarray:
    """
    A sortable key per (sim, team): win % first, then head-to-head win % among teams tied on win %, then
    intradivision win %, then intraleague win %, then a random draw. Shapes: W, G [S, T]; H [S, T, T] (i beat j).
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        pct = np.where(G > 0, W / np.maximum(G, 1), 0.0)
        pr = np.round(pct, 4)
        tied = (pr[:, :, None] == pr[:, None, :]) & same_lg[None, :, :]
        T = W.shape[1]
        tied &= ~np.eye(T, dtype=bool)[None]
        num = (H * tied).sum(2)
        den = ((H + np.transpose(H, (0, 2, 1))) * tied).sum(2)
        h2h = np.where(den > 0, num / np.maximum(den, 1), 0.5)
        dv = np.where(div_g > 0, div_w / np.maximum(div_g, 1), 0.5)
        lp = np.where(lg_g > 0, lg_w / np.maximum(lg_g, 1), 0.5)
    return pr * 1e14 + np.round(h2h, 4) * 1e9 + np.round(dv, 4) * 1e4 + np.round(lp, 4) * 0.5 + rng.random(W.shape) * 1e-3


def seeds_from_keys(key: np.ndarray, teams: list[str], leagues: dict, divisions: dict) -> dict[str, np.ndarray]:
    """{"AL": [S, 6], "NL": [S, 6]} team indices; also division winners."""
    S, T = key.shape
    out = {}
    idx = {t: i for i, t in enumerate(teams)}
    for lg in ("AL", "NL"):
        members = [i for i, t in enumerate(teams) if leagues.get(t) == lg]
        divs = sorted({divisions.get(teams[i]) for i in members})
        winners = []
        for dv in divs:
            mem = np.array([i for i in members if divisions.get(teams[i]) == dv])
            wi = mem[np.argmax(key[:, mem], axis=1)]
            winners.append(wi)
        Wn = np.stack(winners, axis=1)                                      # [S, ndiv]
        wk = np.take_along_axis(key, Wn, axis=1)
        order = np.argsort(-wk, axis=1)
        top = np.take_along_axis(Wn, order, axis=1)[:, :3]
        mem = np.array(members)
        k2 = key[:, mem].copy()
        is_w = (mem[None, :, None] == Wn[:, None, :]).any(2)
        k2[is_w] = -np.inf
        wc = mem[np.argsort(-k2, axis=1)[:, :3]]
        out[lg] = np.concatenate([top, wc], axis=1)
        out[lg + "_div"] = Wn
    return out


def _tables(games: list[dict], teams: list[str], leagues: dict, divisions: dict):
    T = len(teams)
    idx = {t: i for i, t in enumerate(teams)}
    W = np.zeros(T)
    G = np.zeros(T)
    H = np.zeros((T, T))
    dw, dg, lw, lgm = np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T)
    RS = np.zeros(T)
    RA = np.zeros(T)
    for g in games:
        h, a = idx.get(str(g["home"])), idx.get(str(g["away"]))
        if h is None or a is None:
            continue
        hw = int(g["hs"]) > int(g["as"])
        w, l = (h, a) if hw else (a, h)
        W[w] += 1
        G[h] += 1
        G[a] += 1
        H[w, l] += 1
        RS[h] += int(g["hs"]); RA[h] += int(g["as"]); RS[a] += int(g["as"]); RA[a] += int(g["hs"])
        if divisions.get(teams[h]) == divisions.get(teams[a]):
            dw[w] += 1
            dg[h] += 1
            dg[a] += 1
        if leagues.get(teams[h]) == leagues.get(teams[a]):
            lw[w] += 1
            lgm[h] += 1
            lgm[a] += 1
    return W, G, H, dw, dg, lw, lgm, RS, RA


def standings(store: dict, through: Any = None) -> dict:
    """Deterministic standings of completed regular-season games: per team W, L, pct, GB, RS/RA, seed (if any)."""
    teams = real_teams(store)
    leagues, divisions = team_leagues(store)
    th = _dio.to_date(through) if through else None
    done = [g for g in regular_games(store) if is_final(g) and (not th or (_dio.to_date(g.get("date")) or th) < th)]
    W, G, H, dw, dg, lw, lgm, RS, RA = _tables(done, teams, leagues, divisions)
    same = np.array([[leagues.get(a) == leagues.get(b) for b in teams] for a in teams])
    rng = np.random.default_rng(0)
    key = rank_keys(W[None], G[None], H[None], dw[None], dg[None], lw[None], lgm[None], same, rng)
    sd = seeds_from_keys(key, teams, leagues, divisions)
    out = {}
    for i, t in enumerate(teams):
        out[t] = {"w": int(W[i]), "l": int(G[i] - W[i]), "pct": round(W[i] / G[i], 4) if G[i] else None,
                  "rs": int(RS[i]), "ra": int(RA[i]), "league": leagues.get(t), "division": divisions.get(t),
                  "seed": None, "div_winner": False}
    for lg in ("AL", "NL"):
        if lg not in sd:
            continue
        for k, ti in enumerate(sd[lg][0]):
            out[teams[ti]]["seed"] = k + 1
        for ti in sd[lg + "_div"][0]:
            out[teams[ti]]["div_winner"] = True
    # games behind within division
    for dv in set(divisions.values()):
        mem = [t for t in teams if divisions.get(t) == dv]
        if not mem:
            continue
        lead = max(mem, key=lambda t: (out[t]["w"] - out[t]["l"]))
        for t in mem:
            out[t]["gb"] = ((out[lead]["w"] - out[t]["w"]) + (out[t]["l"] - out[lead]["l"])) / 2
    return {"teams": out, "order": teams, "seeds": {lg: [teams[i] for i in sd[lg][0]] for lg in ("AL", "NL") if lg in sd},
            "H": H, "W": W, "G": G}


# ── observed postseason ──────────────────────────────────────────────────────

def observed_series(store: dict, teams: list[str]) -> dict:
    """{(round, i, j): (wins_i, wins_j)} for postseason pairings in the store (i = the home team of game 1)."""
    idx = {t: k for k, t in enumerate(teams)}
    acc: dict = {}
    first_home: dict = {}
    for g in sorted((store.get("games") or {}).values(), key=lambda g: (str(g.get("date")), str(g.get("gpk")))):
        rnd = GTYPE_ROUND.get(str(g.get("gtype") or ""))
        if not rnd:
            continue
        h, a = idx.get(str(g["home"])), idx.get(str(g["away"]))
        if h is None or a is None:
            continue
        key = (rnd, frozenset((h, a)))
        first_home.setdefault(key, h)
        acc.setdefault(key, {h: 0, a: 0})
        if is_final(g):
            w = h if int(g["hs"]) > int(g["as"]) else a
            acc[key][w] += 1
    out = {}
    for key, wins in acc.items():
        rnd, pair = key
        h0 = first_home[key]
        other = next(iter(pair - {h0}))
        out[(rnd, h0, other)] = (wins[h0], wins[other])
    return out


def reconcile_seeds(seeds: dict[str, list[int]], observed: dict, leagues: dict, teams: list[str]) -> dict[str, list[int]]:
    """
    Make the computed seeds agree with the observed bracket (the store's postseason schedule is the truth;
    a tiebreak we cannot reproduce must not move a team). Rules: a Wild Card Series' home team is seed 3 or 4
    and its opponent 6 or 5; a Division Series' home team is a bye (seed 1 or 2), the better record being
    seed 1; seed 1 meets the winner of 4 v 5, seed 2 the winner of 3 v 6. Without Division Series pairings
    the Wild Card pair whose home team was computed higher is 3 v 6.
    """
    out = {k: list(v) for k, v in seeds.items()}
    for lg in ("AL", "NL"):
        s = out.get(lg)
        if not s:
            continue
        pos = {t: i for i, t in enumerate(s)}
        wc = [(h, a) for (r, h, a) in observed if r == "WC" and leagues.get(teams[h]) == lg]
        ds = [(h, a) for (r, h, a) in observed if r == "DS" and leagues.get(teams[h]) == lg]
        byes = list(dict.fromkeys(h for h, _ in ds))
        if len(byes) == 1:
            other = [t for t in s[:2] if t != byes[0]] or [t for t in s if t != byes[0] and t not in {x for p in wc for x in p}]
            byes = byes + other[:1]
        if len(byes) == 2:
            byes.sort(key=lambda t: pos.get(t, 9))
            s[0], s[1] = byes
        if len(wc) == 2:
            feeds = {}
            for h, a in ds:
                for k, (wh, wa) in enumerate(wc):
                    if a in (wh, wa):
                        feeds[h] = k
            if s[0] in feeds:
                k45 = feeds[s[0]]
            elif s[1] in feeds:
                k45 = 1 - feeds[s[1]]
            else:
                # the WC series whose home team is computed better is 3 v 6
                k45 = 0 if pos.get(wc[0][0], 9) > pos.get(wc[1][0], 9) else 1
            (h45, a45), (h36, a36) = wc[k45], wc[1 - k45]
            s[2], s[5], s[3], s[4] = h36, a36, h45, a45
        out[lg] = s
    return out


# ── postseason odds (current season) ─────────────────────────────────────────

def postseason(store: dict, P: np.ndarray | None = None, teams: list[str] | None = None, n: int = N_SIMS, seed: int = 0,
               ratings: dict | None = None, z_sd: float = 0.08, next_games: dict | None = None) -> dict:
    """
    Odds for every playoff team: reach DS / LCS / WS, champion; each live series (current score, P(win),
    length); the next game's interventional odds. P[i, j] over `teams` (default: matrix_from_ratings).
    next_games: {(home_tid, away_tid): p_home} overrides for each live series' next game (game model with probables).
    """
    st = standings(store)
    teams = teams or st["order"]
    leagues, divisions = team_leagues(store)
    T = len(teams)
    idx = {t: i for i, t in enumerate(teams)}
    if P is None:
        P = matrix_from_ratings(teams, ratings or team_ratings(store))
    L = _logit(P)
    obs = observed_series(store, teams)
    seeds = {lg: [idx[t] for t in st["seeds"].get(lg, [])] for lg in ("AL", "NL")}
    if any(len(v) < 6 for v in seeds.values()):
        return {"available": False, "reason": "seeds unavailable (regular season incomplete in the store)"}
    seeds = reconcile_seeds(seeds, obs, leagues, teams)
    rng = np.random.default_rng(seed)
    rec = np.array([st["teams"][t]["pct"] or 0.5 for t in teams])
    # next game of each live series, overridden by the game model's price when given
    Lx = L.copy()
    nxt = {}
    for (rnd, h, a), (wh, wa) in obs.items():
        need = BEST_OF[rnd] // 2 + 1
        if wh >= need or wa >= need:
            continue
        g = wh + wa
        home = h if PATTERN[rnd][g] == "H" else a
        away = a if home == h else h
        p = (next_games or {}).get((teams[home], teams[away]))
        nxt[(rnd, h, a)] = {"home": home, "away": away, "p_home": float(p) if p is not None else float(P[home, away])}
    acc = {k: np.zeros(T) for k in ("DS", "CS", "WS", "champion")}
    ser_acc: dict = {}
    cond: dict = {}
    done = 0
    while done < n:
        m = min(CHUNK, n - done)
        z = rng.normal(0, z_sd, (m, T))
        # live series: play the next game first with its own probability (so it can be conditioned on)
        obs_m = {k: v for k, v in obs.items()}
        per_sim_obs = []
        next_res = {}
        for key, ng in nxt.items():
            rnd, h, a = key
            ph = _sig(_logit(ng["p_home"]) + z[:, ng["home"]] - z[:, ng["away"]])
            win_home = rng.random(m) < ph
            next_res[key] = (win_home, ph)
        # run the bracket separately for the outcome combinations is expensive; instead fix the next game per sim
        # by splitting simulations by the result vector (2^k groups, k <= 4 live series)
        keys = list(nxt)
        combo = np.zeros(m, int)
        for b, key in enumerate(keys):
            combo |= (next_res[key][0].astype(int) << b)
        champ = np.zeros(m, int)
        res_all = {"reach": {k: np.zeros(T) for k in acc}, "champion": np.zeros(m, int), "series": {}}
        sim_series = {lg: {k: np.zeros(m, int) for k in ("wc36", "wc45", "ds1", "ds2", "lcs")} for lg in ("AL", "NL")}
        for c in np.unique(combo):
            sel = np.flatnonzero(combo == c)
            o2 = dict(obs_m)
            for b, key in enumerate(keys):
                rnd, h, a = key
                wh, wa = o2[key]
                hw = bool((c >> b) & 1)
                home = nxt[key]["home"]
                h_won = hw if home == h else not hw
                o2[key] = (wh + int(h_won), wa + int(not h_won))
            r = postseason_sim(seeds, L, len(sel), rng, z[sel], o2, np.tile(rec, (len(sel), 1)), T)
            for k in acc:
                acc[k] += r["reach"][k]
            champ[sel] = r["champion"]
            for lg in ("AL", "NL"):
                for k2, v in r["series"][lg].items():
                    sim_series[lg][k2][sel] = v
        # conditional (interventional) odds for each team in a live series
        for key in keys:
            win_home, ph = next_res[key]
            home, away = nxt[key]["home"], nxt[key]["away"]
            for t, won, pw in ((home, win_home, ph), (away, ~win_home, 1 - ph)):
                c = cond.setdefault(teams[t], {"w": 0.0, "l": 0.0, "cw": 0.0, "cl": 0.0, "pw": 0.0, "n": 0})
                wgt_w = won / pw
                wgt_l = (~won) / (1 - pw)
                c["w"] += float(wgt_w.sum())
                c["l"] += float(wgt_l.sum())
                c["cw"] += float((wgt_w * (champ == t)).sum())
                c["cl"] += float((wgt_l * (champ == t)).sum())
                c["pw"] += float(pw.sum())
                c["n"] += m
        done += m
    out_t = {}
    in_bracket = set(i for lg in ("AL", "NL") for i in seeds[lg])
    for i, t in enumerate(teams):
        if i not in in_bracket:
            continue
        lg = leagues.get(t)
        seed_no = seeds[lg].index(i) + 1
        rec_ = {"seed": seed_no, "league": lg, "p_ds": round(acc["DS"][i] / n, 5), "p_lcs": round(acc["CS"][i] / n, 5),
                "p_pennant": round(acc["WS"][i] / n, 5), "p_ws": round(acc["champion"][i] / n, 5)}
        c = cond.get(t)
        if c and c["w"] > 0 and c["l"] > 0:
            rec_["next"] = {"p_win": round(c["pw"] / c["n"], 4), "if_win": {"p_ws": round(c["cw"] / c["w"], 5)},
                            "if_loss": {"p_ws": round(c["cl"] / c["l"], 5)}}
        out_t[t] = rec_
    live = []
    nxt_round = {"WC": "DS", "DS": "CS", "CS": "WS", "WS": "champion"}
    for (rnd, h, a), (wh, wa) in obs.items():
        need = BEST_OF[rnd] // 2 + 1
        ph = series_prob(float(P[h, a]), 1 - float(P[a, h]), BEST_OF[rnd], PATTERN[rnd], wh, wa)
        live.append({"round": rnd, "home_field": teams[h], "other": teams[a], "wins": [wh, wa],
                     "done": wh >= need or wa >= need, "p_home_field_closed_form": round(ph, 5),
                     "p_home_field_sim": round(float(acc[nxt_round[rnd]][h] / n), 5),
                     "next": ({"home": teams[nxt[(rnd, h, a)]["home"]], "away": teams[nxt[(rnd, h, a)]["away"]],
                               "p_home": round(nxt[(rnd, h, a)]["p_home"], 4)} if (rnd, h, a) in nxt else None)})
    return {"available": True, "sims": n, "teams": out_t, "series": live,
            "seeds": {lg: [teams[i] for i in seeds[lg]] for lg in ("AL", "NL")},
            "matrix": {"teams": [teams[i] for i in sorted(in_bracket)],
                       "p": [[round(float(P[i, j]), 4) for j in sorted(in_bracket)] for i in sorted(in_bracket)]}}


# ── regular season ───────────────────────────────────────────────────────────

def regular_season(store: dict, n: int = N_SIMS, seed: int = 0, ratings: dict | None = None, through: Any = None,
                   game_p: dict | None = None, z_sd: float | None = None, P: np.ndarray | None = None) -> dict:
    """
    Simulate the unplayed regular season (store games, gtype R, not final or after `through`) and the
    postseason. game_p: {gpk: p_home} from the game model for specific games (else ratings + HFA).
    """
    teams = real_teams(store)
    T = len(teams)
    idx = {t: i for i, t in enumerate(teams)}
    leagues, divisions = team_leagues(store)
    th = _dio.to_date(through) if through else None
    ratings = ratings or team_ratings(store, through)
    r = np.array([ratings.get(t, {}).get("r", 0.0) for t in teams])
    se = np.array([ratings.get(t, {}).get("se", 0.1) for t in teams]) if z_sd is None else np.full(T, z_sd)
    played, todo = [], []
    for g in regular_games(store):
        if str(g.get("home")) not in idx or str(g.get("away")) not in idx:
            continue
        gd = _dio.to_date(g.get("date"))
        if is_final(g) and (not th or (gd and gd < th)):
            played.append(g)
        elif str(g.get("status") or "").lower() not in ("postponed", "cancelled", "canceled"):
            todo.append(g)
    todo.sort(key=lambda g: (str(g.get("date")), str(g.get("gpk"))))
    W0, G0, H0, dw0, dg0, lw0, lg0, _, _ = _tables(played, teams, leagues, divisions)
    same = np.array([[leagues.get(a) == leagues.get(b) for b in teams] for a in teams])
    hi = np.array([idx[str(g["home"])] for g in todo], int)
    ai = np.array([idx[str(g["away"])] for g in todo], int)
    sdiv = np.array([divisions.get(teams[h]) == divisions.get(teams[a]) for h, a in zip(hi, ai)], bool)
    slg = np.array([leagues.get(teams[h]) == leagues.get(teams[a]) for h, a in zip(hi, ai)], bool)
    base = np.array([_logit((game_p or {}).get(str(g.get("gpk")), np.nan)) if str(g.get("gpk")) in (game_p or {}) else np.nan
                     for g in todo])
    base = np.where(np.isfinite(base), base, r[hi] - r[ai] + HFA_LOGIT) if len(todo) else base
    Pm = P if P is not None else matrix_from_ratings(teams, ratings)
    Lm = _logit(Pm)
    rng = np.random.default_rng(seed)
    # next game per team (for interventional odds)
    nxt = {}
    for k, (h, a) in enumerate(zip(hi, ai)):
        nxt.setdefault(h, k)
        nxt.setdefault(a, k)
    acc = {k: np.zeros(T) for k in ("div", "wc", "bye", "post", "DS", "CS", "WS", "champion")}
    seed_hist = np.zeros((T, 7))
    wins_all = []
    cond = {t: np.zeros(4) for t in range(T)}   # w-weight, l-weight, post|w, post|l
    cond_ws = {t: np.zeros(2) for t in range(T)}
    pw_sum = np.zeros(T)
    done = 0
    while done < n:
        m = min(CHUNK, n - done)
        z = rng.normal(0, 1, (m, T)) * se[None, :]
        if len(todo):
            lp = base[None, :] + z[:, hi] - z[:, ai]
            p = _sig(lp)
            hw = rng.random((m, len(todo))) < p
        else:
            p = np.zeros((m, 0))
            hw = np.zeros((m, 0), bool)
        W = np.tile(W0, (m, 1))
        G = np.tile(G0, (m, 1)) + 0.0
        np.add.at(G, (slice(None), hi), 1)
        np.add.at(G, (slice(None), ai), 1)
        win_idx = np.where(hw, hi[None, :], ai[None, :])
        los_idx = np.where(hw, ai[None, :], hi[None, :])
        rows = np.repeat(np.arange(m), len(todo))
        np.add.at(W, (rows, win_idx.ravel()), 1)
        H = np.tile(H0, (m, 1, 1))
        np.add.at(H, (rows, win_idx.ravel(), los_idx.ravel()), 1)
        dw = np.tile(dw0, (m, 1))
        dg = np.tile(dg0, (m, 1)) + 0.0
        lw = np.tile(lw0, (m, 1))
        lgm = np.tile(lg0, (m, 1)) + 0.0
        if len(todo):
            dsel = np.flatnonzero(sdiv)
            np.add.at(dw, (np.repeat(np.arange(m), len(dsel)), win_idx[:, dsel].ravel()), 1)
            np.add.at(dg, (slice(None), hi[dsel]), 1)
            np.add.at(dg, (slice(None), ai[dsel]), 1)
            lsel = np.flatnonzero(slg)
            np.add.at(lw, (np.repeat(np.arange(m), len(lsel)), win_idx[:, lsel].ravel()), 1)
            np.add.at(lgm, (slice(None), hi[lsel]), 1)
            np.add.at(lgm, (slice(None), ai[lsel]), 1)
        key = rank_keys(W, G, H, dw, dg, lw, lgm, same, rng)
        sd = seeds_from_keys(key, teams, leagues, divisions)
        post = np.zeros((m, T), bool)
        for lg in ("AL", "NL"):
            for k in range(6):
                t_arr = sd[lg][:, k]
                seed_hist[:, k] += np.bincount(t_arr, minlength=T)
                post[np.arange(m), t_arr] = True
                if k < 3:
                    np.add.at(acc["div"], t_arr, 1)
                else:
                    np.add.at(acc["wc"], t_arr, 1)
                if k < 2:
                    np.add.at(acc["bye"], t_arr, 1)
        acc["post"] += post.sum(0)
        seed_hist[:, 6] += (~post).sum(0)
        pct = W / np.maximum(G, 1)
        r_ps = postseason_sim(sd, Lm + 0.0, m, rng, z, None, pct, T)
        for k in ("DS", "CS", "WS", "champion"):
            acc[k] += r_ps["reach"][k]
        champ = r_ps["champion"]
        wins_all.append(W.astype(np.int16))
        for t, k in nxt.items():
            ph = p[:, k]
            won = hw[:, k] if hi[k] == t else ~hw[:, k]
            pw = ph if hi[k] == t else 1 - ph
            ww = won / pw
            wl = (~won) / (1 - pw)
            cond[t] += [ww.sum(), wl.sum(), (ww * post[:, t]).sum(), (wl * post[:, t]).sum()]
            cond_ws[t] += [(ww * (champ == t)).sum(), (wl * (champ == t)).sum()]
            pw_sum[t] += pw.sum()
        done += m
    Wall = np.concatenate(wins_all, axis=0)
    out = {}
    for i, t in enumerate(teams):
        rec = {"exp_w": round(float(Wall[:, i].mean()), 2), "w_p05": int(np.percentile(Wall[:, i], 5)),
               "w_p95": int(np.percentile(Wall[:, i], 95)), "w_now": int(W0[i]), "l_now": int(G0[i] - W0[i]),
               "p_division": round(acc["div"][i] / n, 5), "p_wildcard": round(acc["wc"][i] / n, 5),
               "p_bye": round(acc["bye"][i] / n, 5), "p_postseason": round(acc["post"][i] / n, 5),
               "p_ds": round(acc["DS"][i] / n, 5), "p_lcs": round(acc["CS"][i] / n, 5),
               "p_pennant": round(acc["WS"][i] / n, 5), "p_ws": round(acc["champion"][i] / n, 5),
               "seed_dist": [round(x / n, 5) for x in seed_hist[i]], "rating": round(float(r[i]), 4),
               "league": leagues.get(t), "division": divisions.get(t)}
        if i in nxt and cond[i][0] > 0 and cond[i][1] > 0:
            g = todo[nxt[i]]
            rec["next"] = {"gpk": g.get("gpk"), "date": g.get("date"), "p_win": round(pw_sum[i] / n, 4),
                           "if_win": {"p_postseason": round(cond[i][2] / cond[i][0], 5), "p_ws": round(cond_ws[i][0] / cond[i][0], 5)},
                           "if_loss": {"p_postseason": round(cond[i][3] / cond[i][1], 5), "p_ws": round(cond_ws[i][1] / cond[i][1], 5)}}
        out[t] = rec
    magic = magic_numbers(W0, G0, store, teams, todo, divisions)
    for t, mg in magic.items():
        out[t]["magic"] = mg
    return {"available": True, "sims": n, "teams": out, "remaining_games": len(todo), "played": len(played)}


def magic_numbers(W0: np.ndarray, G0: np.ndarray, store: dict, teams: list[str], todo: list[dict], divisions: dict) -> dict:
    """Division magic / tragic numbers (deterministic): M_ij = W_j + R_j - W_i + 1 over division rivals."""
    idx = {t: i for i, t in enumerate(teams)}
    R = np.zeros(len(teams))
    for g in todo:
        R[idx[str(g["home"])]] += 1
        R[idx[str(g["away"])]] += 1
    out = {}
    for i, t in enumerate(teams):
        rivals = [j for j, u in enumerate(teams) if j != i and divisions.get(u) == divisions.get(t)]
        if not rivals:
            continue
        M = max(W0[j] + R[j] - W0[i] + 1 for j in rivals)
        E = min(W0[i] + R[i] - W0[j] + 1 for j in rivals)
        # tragic: the number of i losses + leader wins that eliminate i from the division
        lead = max(rivals, key=lambda j: W0[j])
        trag = W0[i] + R[i] - W0[lead] + 1
        out[t] = {"division_magic": int(max(0, M)), "clinched_division": bool(M <= 0),
                  "division_tragic": int(max(0, trag)), "eliminated_division": bool(trag <= 0)}
    return out


# ── payload ──────────────────────────────────────────────────────────────────

def phase(store: dict) -> str:
    """"preseason" | "regular" | "postseason" | "complete"."""
    games = list((store.get("games") or {}).values())
    post = [g for g in games if str(g.get("gtype")) in GTYPE_ROUND]
    if post:
        ws = [g for g in post if str(g.get("gtype")) == "W" and is_final(g)]
        if ws:
            obs_w = {}
            for g in ws:
                w = str(g["home"]) if int(g["hs"]) > int(g["as"]) else str(g["away"])
                obs_w[w] = obs_w.get(w, 0) + 1
            if max(obs_w.values()) >= 4:
                return "complete"
        # Triple-A's postseason (two best-of-three league finals and a one-game championship, all typed "W")
        # never reaches four wins: it is over when nothing is left to play
        if str(store.get("level") or "mlb") != "mlb" and all(
                is_final(g) or str(g.get("status") or "").lower() in ("postponed", "cancelled") for g in games):
            return "complete"
        return "postseason"
    reg = regular_games(store)
    if reg and all(is_final(g) or str(g.get("status") or "").lower() in ("postponed", "cancelled") for g in reg):
        return "postseason"
    if reg and any(is_final(g) for g in reg):
        return "regular"
    return "preseason"


def for_season(level: str, season: int, n: int = N_SIMS, seed: int = 0, use_model: bool = True, ctx=None) -> dict:
    """Season payload: postseason odds when the bracket is set, else the regular season (with the postseason)."""
    store = _dio.load_store(level, season)
    if not store:
        return {"available": False, "reason": f"no store for {level} {season}"}
    ph = phase(store)
    out: dict[str, Any] = {"season": season, "level": level, "phase": ph}
    try:
        st = standings(store)
        out["standings"] = st["teams"]
        teams = st["order"]
        P = None
        basis = "ratings"
        if use_model:
            try:
                from oddsmarkets.baseball.models import game_inputs as GI
                ctx = ctx or GI.build_context(level, season, store)
                in_play = [t for lg in ("AL", "NL") for t in st["seeds"].get(lg, [])] if ph != "regular" else teams
                Psub = pair_matrix_sim(in_play, ctx, n=4000, seed=seed)
                ratings = team_ratings(store)
                P = matrix_from_ratings(teams, ratings)
                ix = {t: i for i, t in enumerate(teams)}
                for a, ta in enumerate(in_play):
                    for b, tb in enumerate(in_play):
                        if a != b:
                            P[ix[ta], ix[tb]] = Psub[a, b]
                basis = "game_model"
            except Exception as exc:  # noqa: BLE001
                logger.info("pair matrix from the game model failed (%s); ratings used", exc)
                P = None
        out["basis"] = basis
        if ph in ("postseason", "complete"):
            nxt = {}
            if basis == "game_model":
                # each live series' next scheduled game priced with its probables and posted lineups
                from oddsmarkets.baseball.models import game_inputs as GI
                real = set(teams)
                seen = set()
                for g in sorted(store["games"].values(), key=lambda g: (str(g.get("date")), str(g.get("gpk")))):
                    if str(g.get("gtype")) not in GTYPE_ROUND or is_final(g):
                        continue
                    h, a = str(g["home"]), str(g["away"])
                    if h not in real or a not in real or frozenset((h, a)) in seen:
                        continue
                    seen.add(frozenset((h, a)))
                    try:
                        r = GI.predict(g, ctx, n=20000, seed=seed)
                        nxt[(h, a)] = r["p_home"]
                        out.setdefault("next_games", []).append({"gpk": g.get("gpk"), "date": g.get("date"), "home": h,
                                                                 "away": a, "p_home": r["p_home"], "inputs": r.get("inputs"),
                                                                 "total_mean": r["runs"]["total"], "f5": r["f5"],
                                                                 "runline": r["runline"]})
                    except Exception as exc:  # noqa: BLE001
                        logger.info("next game %s failed: %s", g.get("gpk"), exc)
            out["postseason"] = postseason(store, P, teams, n=n, seed=seed, next_games=nxt)
        else:
            out["regular"] = regular_season(store, n=n, seed=seed, P=P)
        out["available"] = True
    except Exception as exc:  # noqa: BLE001
        logger.exception("season_sim failed")
        out.update({"available": False, "reason": f"error: {exc}"})
    return out
