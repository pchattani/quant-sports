"""
Season simulation: the rest of the regular season (2-1-0 points), the NHL standings tiebreakers, divisional + wild-card
playoff qualification, the best-of-seven bracket, the Presidents' Trophy and the draft lottery, 20,000 times,
vectorised over simulations in chunks (bounded memory).

Simulated games (simulation s, game g, home h, away a)
-------------------------------------------------------
    mu_h,s = mu_h,g * exp(+(x_s,h - x_s,a) / (2 Gbar)),   mu_a,s = mu_a,g * exp(-(x_s,h - x_s,a) / (2 Gbar))
mu_g are the game model's regulation means (game.features / game.means: ratings with each team's usual starter, home
ice, rest, back-to-backs, travel, time zones), Gbar the league goals per team-game, x_s,t = z_s,t + sum_{k<=w(g)}
u_s,t,k a team's strength error in goals per game: z ~ N(0, (se_scale * se_t)^2) (se_t from team_strength), u ~
N(0, drift^2) a weekly random walk. Scores come from game.simulate_scores (the same bivariate-Poisson + empty-net
process as the analytic game model, then 3-on-3 overtime and the shootout), so wins, regulation wins (RW),
regulation + overtime wins (ROW), points (W 2, OTL/SOL 1), goals for and against (the shootout winner credited one
goal, as in the NHL's GF / DIFF columns) and head-to-head points are all exact per simulation.

Standings and tiebreakers (builder A's canon: canon.TIEBREAK_STEPS / order_tied, quoting
https://www.nhl.com/info/standings-info/tie-breaking-procedure, verified 2026-10-01)
-----------------------------------------------------------------------------------------------------------
Clubs are ordered by points; clubs tied in points are separated by, in order (2019-20 onward):
    1. fewer games played (higher points percentage)          4. more wins in any manner (W)
    2. more regulation wins (RW)                              5. more points in games among the tied clubs (for three
    3. more regulation + overtime wins (ROW)                     or more: the percentage of available points in those
                                                                 games), the odd game excluded (see below)
    6. greater goal differential                              7. more goals scored (overtime goals and the shootout
                                                                 goal included)
then (simulations only) a random draw. Steps 1-4 are team-level and are applied as one lexicographic key. Steps 5-7
run in order on each group still tied; a step that separates clubs splits the group and each still-tied subgroup
carries on from the next step, head-to-head computed among the clubs still tied at that point (canon.order_tied; the
published procedure has no restart clause). Odd-game rule: between two clubs that have not played an even number of
games, the first game played in the city that has the extra game is not counted. 2010-11 to 2018-19: points, games
played, ROW, head-to-head, goal differential. The current standings (`standings`, `_current_order`) are canon.rank
itself when canon is importable.

Playoffs
--------
2013-14 onward (not 2019-20 / 2020-21): the top three of each division plus two wild cards per conference (the best two
of the remaining conference clubs by the same procedure). The division winner with the better record (procedure) plays
the second wild card, the other winner the first; second v third in each division. Winners advance within the
division bracket, then the conference final and the Stanley Cup Final. Home ice in every series goes to the club with
the better regular-season record (points, then the procedure) regardless of seed. 2010-11 to 2012-13: three division
winners seeded 1-3, five more by points; 1v8, 2v7, 3v6, 4v5, reseeded after each round. 2020-21: top four of each of
four divisions, 1v4 and 2v3 within the division, division final, semi-finals reseeded by points (1v4, 2v3), final.
Series: best of seven, 2-2-1-1-1, the home side of each game winning with probability
logistic(logit P0[h, a] + k_po (x_h - x_a)), P0 the game model's playoff win probability at the base ratings (sudden-death
5-on-5 overtime) and k_po its slope in goals per game. Played playoff games are fixed; a series in progress continues.

Draft lottery (current format, verified 2026-10-01: https://en.wikipedia.org/wiki/2026_NHL_entry_draft and Yahoo Sports,
"How does the NHL Draft Lottery work?"): the 16 non-playoff clubs in reverse order of the standings, odds for the first
draw 18.5, 13.5, 11.5, 9.5, 8.5, 7.5, 6.5, 6.0, 5.0, 3.5, 3.0, 2.5, 2.0, 1.5, 0.5, 0.5 %. Two draws (picks 1 and 2); a
club may move up at most ten places, so a winner that cannot reach the pick moves up ten places and the pick goes to the
best-placed remaining club; the second draw is among the clubs other than the first draw's winner and the first pick's
holder. The rest pick in order. (The twice-in-five-years limit is not modelled.) `lottery_matrix` enumerates both draws
exactly.

Magic numbers (deterministic, points; tiebreaks assumed lost): for "finish ahead of all but k-1 rivals" magic_i =
k-th largest (P_j + 2 R_j - P_i + 1) over rivals j, tragic_i = k-th smallest (P_i + 2 R_i - P_j + 1); clinched when
magic <= 0, eliminated when tragic <= 0. Division title k = 1 (division), Presidents' Trophy k = 1 (league). Playoffs
(sufficient conditions): clinched when top-3 of the division is clinched or at most four conference rivals can still
reach the club (it is then at worst the second wild card); eliminated when top-3 of the division is lost and eight
conference rivals are already out of reach above.

Next-game odds are interventional: each simulation where the club won (lost) its next game is weighted by 1 / P(result |
that simulation's strength draws), so if_win / if_loss isolate the game's own effect (see basketball season_sim).
"""
from __future__ import annotations

import itertools
import logging
import math
import time
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from oddsmarkets.nhl.models import _cdata as D
from oddsmarkets.nhl.models import game as GM
from oddsmarkets.nhl.models import team_strength as TS

logger = logging.getLogger(__name__)

CHUNK = 1000
DRIFT = 0.035
LOTTERY_ODDS = (18.5, 13.5, 11.5, 9.5, 8.5, 7.5, 6.5, 6.0, 5.0, 3.5, 3.0, 2.5, 2.0, 1.5, 0.5, 0.5)
LOTTERY_SOURCES = ["https://en.wikipedia.org/wiki/2026_NHL_entry_draft",
                   "https://sports.yahoo.com/articles/does-nhl-draft-lottery-explaining-111217430.html"]
TIEBREAK_SOURCE = "https://www.nhl.com/info/standings-info/tie-breaking-procedure"
PTS_LADDER = list(range(50, 135, 5))


def sim_params() -> dict:
    for path in (D.c_cache() / "season_sim_params.json", D.FITTED / "season_sim_params.json"):
        c = D.read_json(path)
        if c:
            return c.get("result") or c
    return {"se_scale": 1.0, "drift": DRIFT}


def fmt(season: int) -> str:
    """"wildcard" (divisional + wild card), "conf8" (conference top eight), "div4" (2020-21) or "rtp" (2019-20)."""
    y = D.start_year(season)
    try:
        from oddsmarkets.nhl import canon
        kind = canon.formats(season)["playoff"]["kind"]
        m = {"divisional_wildcard": "wildcard", "conference": "conf8", "division_2021": "div4", "return_to_play": "rtp"}
        if kind in m:
            return m[kind]
    except Exception:  # noqa: BLE001
        pass
    if y == 2020:
        return "div4"
    if y <= 2012:
        return "conf8"
    return "wildcard"


def tiebreak_steps(season: int) -> tuple[str, list[str]]:
    """(key kind, group steps): "rw" -> (P, -GP, RW, ROW, W) then H2H, GD, GF; "row" -> (P, -GP, ROW) then H2H, GD."""
    try:
        from oddsmarkets.nhl import canon
        v = [str(x).lower() for x in canon.TIEBREAK_STEPS[canon.tiebreak_era(season)]]
        if v:
            kind = "rw" if "rw" in v else "row"
            grp = [{"h2h": "H2H", "diff": "GD", "gf": "GF"}[x] for x in v if x in ("h2h", "diff", "gf")]
            return kind, grp or ["H2H", "GD"]
    except Exception:  # noqa: BLE001
        pass
    return ("rw", ["H2H", "GD", "GF"]) if D.start_year(season) >= 2019 else ("row", ["H2H", "GD"])


def sort_key(P, GP, RW, ROW, W, kind: str = "rw"):
    """Lexicographic standings key (higher = better) as one float64 (all parts < 100 except points)."""
    P, GP, RW, ROW, W = (np.asarray(x, np.float64) for x in (P, GP, RW, ROW, W))
    if kind == "row":
        return (P * 100.0 + (99.0 - GP)) * 100.0 + ROW
    return (((P * 100.0 + (99.0 - GP)) * 100.0 + RW) * 100.0 + ROW) * 100.0 + W


# ── lottery ──────────────────────────────────────────────────────────────────

@lru_cache(maxsize=8)
def lottery_matrix(odds: tuple = LOTTERY_ODDS, max_jump: int = 10) -> np.ndarray:
    """M[slot, pick] for slots 0 (worst record) .. n-1: two draws with the max-jump rule (module doc)."""
    n = len(odds)
    w = np.array(odds, float)
    w = w / w.sum()
    M = np.zeros((n, n))
    for i in range(n):
        pi = w[i]
        if pi == 0:
            continue
        if i <= max_jump:                                     # can reach pick 1 (index 0)
            p1, moved1 = i, None
        else:
            p1, moved1 = 0, i
        excl = {i, p1}
        left = [j for j in range(n) if j not in excl]
        wl = sum(w[j] for j in left)
        order = _order_after([p1], {moved1} - {None}, n, max_jump)
        for j in left:
            pj = w[j] / wl
            if j - 1 <= max_jump:                             # from slot j to pick 2 is at most max_jump places
                p2, moved2 = j, None
            else:
                p2, moved2 = order[0], j
            rest = _order_after([p1, p2], ({moved1} | {moved2}) - {None}, n, max_jump)
            final = [p1, p2] + rest
            for k, t in enumerate(final):
                M[t, k] += pi * pj
    return M


def _order_after(taken: list[int], moved: set, n: int, max_jump: int) -> list[int]:
    """Remaining clubs in pick order: original slot order, a club that won a draw it could not use moved up max_jump
    places (ahead of the club previously there)."""
    pos = {t: float(t) for t in range(n) if t not in taken}
    for m in moved:
        if m in pos:
            pos[m] = max(m - max_jump, 0) - 0.5
    return sorted(pos, key=lambda t: pos[t])


def lottery_table() -> list[dict]:
    M = lottery_matrix()
    return [{"slot": i + 1, "odds_first": LOTTERY_ODDS[i] / 100.0, "p_first": round(float(M[i, 0]), 4),
             "p_second": round(float(M[i, 1]), 4), "pick_dist": [round(float(x), 4) for x in M[i]]} for i in range(len(LOTTERY_ODDS))]


# ── state ────────────────────────────────────────────────────────────────────

def build_state(season: int, store: dict | None = None, games: pd.DataFrame | None = None, through: Any = None,
                teams_info: dict | None = None) -> dict:
    """Teams, groups, current tallies, remaining regular-season games, head-to-head bookkeeping and playoff results."""
    st = store if store is not None else D.load_store(season)
    G = games if games is not None else D.games_from_store(st, season)
    G = G[G["season"] == int(season)] if len(G) else G
    info = teams_info or {}
    if not info:
        ti = D.teams_for(season)
        sti = (st or {}).get("teams") or {}
        names = sorted(set(G["home"]) | set(G["away"])) if len(G) else sorted(ti)
        for t in names or sorted(ti):
            v = sti.get(t) if isinstance(sti, dict) else None
            div = (v or {}).get("division") or ti.get(t, {}).get("division")
            conf = (v or {}).get("conference") or ti.get(t, {}).get("conference")
            info[t] = {"division": div, "conference": conf}
    teams = sorted(info)
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    divs = sorted({info[t]["division"] for t in teams if info[t].get("division")})
    confs = sorted({info[t]["conference"] for t in teams if info[t].get("conference")})
    div_id = np.array([divs.index(info[t]["division"]) if info[t].get("division") in divs else 0 for t in teams])
    conf_id = np.array([confs.index(info[t]["conference"]) if info[t].get("conference") in confs else 0 for t in teams])
    thr = pd.Timestamp(through) if through is not None else None
    reg = G[(G["gtype"] == "REG")] if len(G) else G
    reg = reg[reg["home"].isin(idx) & reg["away"].isin(idx)] if len(reg) else reg
    played_m = reg["played"].to_numpy(bool) if len(reg) else np.zeros(0, bool)
    if thr is not None and len(reg):
        played_m = played_m & (reg["date"] < thr).to_numpy()
    pl = reg[played_m] if len(reg) else reg
    rem = reg[~played_m] if len(reg) else reg
    z = lambda: np.zeros(T, np.int64)                       # noqa: E731
    GP, W, L, OTL, RW, ROW, GF, GA = z(), z(), z(), z(), z(), z(), z(), z()
    for r in pl.itertuples(index=False):
        h, a = idx[r.home], idx[r.away]
        hw = r.hs > r.as_
        win, los = (h, a) if hw else (a, h)
        GP[h] += 1
        GP[a] += 1
        W[win] += 1
        if r.ot or r.so:
            OTL[los] += 1
        else:
            L[los] += 1
            RW[win] += 1
        if not r.so:
            ROW[win] += 1
        GF[h] += int(r.hs)
        GA[h] += int(r.as_)
        GF[a] += int(r.as_)
        GA[a] += int(r.hs)
    P = 2 * W + OTL
    # head-to-head: every regular-season meeting (played and remaining), the odd game excluded per the rule
    allg = pd.concat([pl.assign(is_pl=True), rem.assign(is_pl=False)]) if len(reg) else reg
    excl: set[str] = set()
    if len(allg):
        allg = allg.sort_values(["date", "game_id"])
        for (x, y), grp in allg.groupby([allg[["home", "away"]].min(axis=1), allg[["home", "away"]].max(axis=1)]):
            if len(grp) % 2 == 1:
                hc = grp["home"].value_counts()
                city = hc.idxmax() if len(hc) == 1 or hc.iloc[0] != hc.iloc[1] else None
                if city is not None:
                    excl.add(str(grp[grp["home"] == city].iloc[0]["game_id"]))
    HP0 = np.zeros((T, T), np.int64)                         # points i earned against j (played, odd game excluded)
    NG = np.zeros((T, T), np.int64)                          # counted meetings (played + remaining)
    for r in (allg.itertuples(index=False) if len(allg) else []):
        if str(r.game_id) in excl:
            continue
        h, a = idx[r.home], idx[r.away]
        NG[h, a] += 1
        NG[a, h] += 1
        if r.is_pl:
            hw = r.hs > r.as_
            HP0[h, a] += 2 if hw else (1 if (r.ot or r.so) else 0)
            HP0[a, h] += 0 if hw and not (r.ot or r.so) else (1 if hw else 2)
    rem_rows = [{"game_id": str(r.game_id), "home": idx[r.home], "away": idx[r.away], "date": r.date,
                 "counted": str(r.game_id) not in excl} for r in rem.itertuples(index=False)] if len(rem) else []
    # playoffs
    po = G[(G["gtype"] == "PO") & G["played"]] if len(G) else G
    if thr is not None and len(po):
        po = po[po["date"] < thr]
    SW = np.zeros((T, T), np.int64)
    for r in (po.itertuples(index=False) if len(po) else []):
        if r.home in idx and r.away in idx:
            w_, l_ = (idx[r.home], idx[r.away]) if r.hs > r.as_ else (idx[r.away], idx[r.home])
            SW[w_, l_] += 1
    return {"season": int(season), "teams": teams, "idx": idx, "T": T, "info": info, "divs": divs, "confs": confs,
            "div_id": div_id, "conf_id": conf_id, "GP": GP, "W": W, "L": L, "OTL": OTL, "RW": RW, "ROW": ROW, "GF": GF,
            "GA": GA, "P": P, "HP0": HP0, "NG": NG, "rem": rem_rows, "rem_frame": rem, "SW": SW,
            "post_started": bool(len(po)), "games": G}


# ── ranking ──────────────────────────────────────────────────────────────────

class Ranker:
    """Orders clubs per simulation: the lexicographic key, then H2H / GD / GF on tied groups with restarts."""

    def __init__(self, K, HP, NG, GD, GF, steps, rng):
        self.K, self.HP, self.NG, self.GD, self.GF = K, HP, NG, GD, GF
        self.steps = steps
        self.rng = rng
        self.n_resolved = 0

    def _value(self, step, Q, s):
        Q = np.asarray(Q)
        if step == "H2H":
            sub = self.HP[s][np.ix_(Q, Q)].sum(1).astype(float)
            ng = self.NG[np.ix_(Q, Q)].sum(1).astype(float)
            return np.where(ng > 0, sub / np.maximum(2.0 * ng, 1e-9), 0.5)
        if step == "GD":
            return self.GD[s, Q].astype(float)
        return self.GF[s, Q].astype(float)

    def resolve(self, Q: list[int], s: int, start: int = 0) -> list[int]:
        if len(Q) <= 1:
            return list(Q)
        for k in range(start, len(self.steps)):
            v = self._value(self.steps[k], Q, s)
            if np.ptp(v) > 1e-12:
                out = []
                for val in sorted(set(np.round(v, 12)), reverse=True):
                    cls = [q for q, x in zip(Q, np.round(v, 12)) if x == val]
                    out += self.resolve(cls, s, k + 1) if len(cls) > 1 else cls
                return out
        self.n_resolved += 1
        return list(self.rng.permutation(Q))

    def rank(self, mem) -> np.ndarray:
        """(S, len(mem)) team indices best first."""
        mem = np.asarray(mem)
        Km = self.K[:, mem]
        order = np.argsort(-Km, axis=1, kind="stable")
        ranked = mem[order]
        Ks = np.take_along_axis(Km, order, 1)
        tie = np.any(Ks[:, 1:] == Ks[:, :-1], axis=1) if len(mem) > 1 else np.zeros(len(Km), bool)
        for s in np.nonzero(tie)[0]:
            row = list(ranked[s])
            ks = Ks[s]
            out, i = [], 0
            while i < len(row):
                j = i + 1
                while j < len(row) and ks[j] == ks[i]:
                    j += 1
                out += self.resolve(row[i:j], s) if j - i > 1 else row[i:j]
                i = j
            ranked[s] = out
        return ranked


# ── magic numbers ────────────────────────────────────────────────────────────

def magic_numbers(P: np.ndarray, R: np.ndarray, div_id: np.ndarray, conf_id: np.ndarray, fmt_name: str = "wildcard") -> list[dict]:
    T = len(P)
    Pmax = P + 2 * R
    out = []
    for i in range(T):
        rec = {"magic": {}, "tragic": {}, "clinched": {}, "eliminated": {}}

        def kth(rivals, k):
            if len(rivals) < k:
                return 0, None
            M = sorted((int(Pmax[j] - P[i] + 1) for j in rivals), reverse=True)
            E = sorted(int(Pmax[i] - P[j] + 1) for j in rivals)
            return M[k - 1], E[k - 1]
        dr = [j for j in range(T) if j != i and div_id[j] == div_id[i]]
        cr = [j for j in range(T) if j != i and conf_id[j] == conf_id[i]]
        lr = [j for j in range(T) if j != i]
        for name, rivals, k in (("division", dr, 1), ("presidents", lr, 1)):
            m, e = kth(rivals, k)
            rec["magic"][name], rec["tragic"][name] = max(0, m), (max(0, e) if e is not None else None)
            rec["clinched"][name], rec["eliminated"][name] = m <= 0, (e is not None and e <= 0)
        if fmt_name == "wildcard":
            m3, e3 = kth(dr, 3)
            m5, _ = kth(cr, 5)
            _, e8 = kth(cr, 8)
            rec["magic"]["playoffs"] = max(0, min(m3, m5))
            rec["clinched"]["playoffs"] = m3 <= 0 or m5 <= 0
            rec["eliminated"]["playoffs"] = (e3 is not None and e3 <= 0) and (e8 is not None and e8 <= 0)
            rec["tragic"]["playoffs"] = max(0, max(e3 or 0, e8 or 0))
        out.append(rec)
    return out


# ── series ───────────────────────────────────────────────────────────────────

PATTERN = "HHAAHAH"


def _series(A, B, P0, kpo, x, SW, rng):
    """Winner per simulation of a best-of-seven; A holds home ice (2-2-1-1-1)."""
    S = len(A)
    ar = np.arange(S)
    d = x[ar, A] - x[ar, B]
    la = np.log(P0[A, B] / (1 - P0[A, B])) + kpo * d             # A at home
    lb = np.log(P0[B, A] / (1 - P0[B, A])) - kpo * d             # B at home (prob B wins)
    pA_home = 1 / (1 + np.exp(-la))
    pA_away = 1 - 1 / (1 + np.exp(-lb))
    wa = SW[A, B].astype(int).copy()
    wb = SW[B, A].astype(int).copy()
    for gi, ch in enumerate(PATTERN):
        play = (wa + wb == gi) & (wa < 4) & (wb < 4)
        if not play.any():
            continue
        win = rng.random(S) < (pA_home if ch == "H" else pA_away)
        wa += play & win
        wb += play & ~win
    return np.where(wa >= 4, A, B)


def _better(a, b, lpos):
    """The club with the better regular-season record (lower league position) per simulation."""
    ar = np.arange(len(a))
    return np.where(lpos[ar, a] <= lpos[ar, b], a, b)


# ── the simulation ───────────────────────────────────────────────────────────

def simulate(season: int, n: int = 20000, seed: int = 0, state: dict | None = None) -> dict:
    """
    {"ok", "teams": {abbr: {...}}, "bracket", "lottery", "n_sims", "runtime_s", "format", "notes", ...}
    state (all optional): "store", "games" (games frame), "through", "ratings" (team_strength.for_season dict),
    "params" (game params), "se_scale", "drift", "chunk", "teams_info".
    """
    t0 = time.perf_counter()
    state = dict(state or {})
    season = int(season)
    cache = state.get("_cache")             # sensitivity runs share the setup (it does not depend on a shift)
    if isinstance(cache, dict) and "S0" in cache:
        S0 = cache["S0"]
    else:
        S0 = build_state(season, state.get("store"), state.get("games"), state.get("through"), state.get("teams_info"))
        if isinstance(cache, dict):
            cache["S0"] = S0
    teams, T = S0["teams"], S0["T"]
    if T < 4:
        return {"ok": False, "reason": "fewer than four teams", "teams": {}, "n_sims": 0}
    fname = state.get("format") or fmt(season)
    kind, steps = tiebreak_steps(season)
    rd = state.get("ratings")
    if rd is None:
        try:
            rd = TS.for_season(season, through=state.get("through"))
        except Exception as exc:  # noqa: BLE001
            logger.info("season_sim: ratings unavailable (%s)", exc)
            rd = {"teams": {}, "league": dict(TS.DEFAULTS["league"]), "mode": "goals"}
    prm = GM.params(state.get("params"))
    sp = sim_params()
    se_scale = float(state.get("se_scale", sp.get("se_scale", 1.0)))
    drift = float(state.get("drift", sp.get("drift", DRIFT)))
    rteams = rd.get("teams") or {}
    se = se_scale * np.array([float((rteams.get(t) or {}).get("se_net", 0.25)) for t in teams])
    base = np.array([float((rteams.get(t) or {}).get("net", 0.0)) for t in teams])
    gbar = float((rd.get("league") or {}).get("goals_pg", 3.0))
    # remaining games: base means
    rem = S0["rem"]
    Gn = len(rem)
    if isinstance(cache, dict) and "games" in cache:
        mu_h0, mu_a0, hi, ai, week, counted, p_home0 = cache["games"]
    elif Gn:
        Gall = D.add_context(S0["games"])
        ctx = Gall.set_index("game_id")
        rf = ctx.loc[[r["game_id"] for r in rem]].reset_index()
        F = GM.features(rf, rd)
        mu_h0, mu_a0 = GM.means(F, prm)
        hi = np.array([r["home"] for r in rem], int)
        ai = np.array([r["away"] for r in rem], int)
        d0 = pd.to_datetime(rf["date"]).min()
        week = ((pd.to_datetime(rf["date"]) - d0).dt.days // 7).to_numpy(int)
        counted = np.array([r["counted"] for r in rem], bool)
        p_home0 = GM.outcome_probs(mu_h0, mu_a0, prm, False, season)["p_home"]
    else:
        mu_h0 = mu_a0 = p_home0 = np.zeros(0)
        hi = ai = week = np.zeros(0, int)
        counted = np.zeros(0, bool)
    if isinstance(cache, dict):
        cache["games"] = (mu_h0, mu_a0, hi, ai, week, counted, p_home0)
    n_weeks = int(week.max()) + 1 if Gn else 1
    # playoff base matrix and slope
    if isinstance(cache, dict) and "po" in cache:
        P0, kpo, kreg = cache["po"]
    else:
        P0, kpo, kreg = _po_matrix(rd, teams, prm, season)
        if isinstance(cache, dict):
            cache["po"] = (P0, kpo, kreg)
    sh = state.get("shift") or {}
    dv = np.array([float(sh.get(t, 0.0) or 0.0) for t in teams]) if sh else None
    # one-hot
    OHh = np.zeros((Gn, T), np.float32)
    OHa = np.zeros((Gn, T), np.float32)
    if Gn:
        OHh[np.arange(Gn), hi] = 1
        OHa[np.arange(Gn), ai] = 1
    # pair columns for head-to-head
    pairs: dict[tuple, list] = {}
    for k in range(Gn):
        if not counted[k]:
            continue
        i, j = (hi[k], ai[k]) if hi[k] < ai[k] else (ai[k], hi[k])
        pairs.setdefault((int(i), int(j)), []).append(k)
    PI = np.array([k[0] for k in pairs], int)
    PJ = np.array([k[1] for k in pairs], int)
    width = max((len(v) for v in pairs.values()), default=1)
    PC = np.full((len(pairs), width), Gn, int)
    PS = np.zeros((len(pairs), width), np.int8)              # +1: i home, -1: i away
    for r_, (key, cols) in enumerate(pairs.items()):
        PC[r_, :len(cols)] = cols
        PS[r_, :len(cols)] = [1 if hi[c] == key[0] else -1 for c in cols]
    # groups
    conf_id, div_id = S0["conf_id"], S0["div_id"]
    confs, divs = S0["confs"], S0["divs"]
    div_mem = {d: np.nonzero(div_id == k)[0] for k, d in enumerate(divs)}
    conf_mem = {c: np.nonzero(conf_id == k)[0] for k, c in enumerate(confs)}
    all_mem = np.arange(T)
    # next game per team
    next_col: dict[int, int] = {}
    for k in range(Gn):
        for t in (hi[k], ai[k]):
            next_col.setdefault(int(t), k)
    # accumulators
    maxp = 2 * (int(S0["GP"].max()) + int(np.bincount(np.concatenate([hi, ai]), minlength=T).max() if Gn else 0)) + 2
    pts_hist = np.zeros((T, maxp + 1))
    acc = {k: np.zeros(T) for k in ("playoffs", "div", "top3", "wc", "pres", "conf", "cup", "pts", "w", "rw")}
    div_rank = np.zeros((T, 8))
    rounds = ["r1", "r2", "conf_final", "final"]
    reach = {r: np.zeros(T) for r in rounds}
    pair_ct: list[dict] = [dict() for _ in rounds]
    nl = 16
    LM = lottery_matrix()
    lot = np.zeros((T, nl))
    nx = {t: {"n": 0.0, "p_sum": 0.0, "w_win": 0.0, "w_loss": 0.0, "win": np.zeros(4), "loss": np.zeros(4)} for t in next_col}
    rng = np.random.default_rng(seed)
    chunk = int(state.get("chunk", CHUNK))
    done = 0
    nres = 0
    while done < n:
        S = min(chunk, n - done)
        done += S
        z = rng.normal(0.0, 1.0, (S, T)) * se[None, :]
        if dv is not None:
            z = z + dv[None, :]                 # the team is d goals a game (net) better for the rest of the season
        if Gn:
            U = rng.normal(0.0, drift, (S, T, n_weeks)).cumsum(axis=2) if drift > 0 else np.zeros((S, T, n_weeks))
            dx = (z[:, hi] + U[:, hi, week]) - (z[:, ai] + U[:, ai, week])
            f = np.exp(dx / (2.0 * gbar))
            sim = GM.simulate_scores(mu_h0[None, :] * f, mu_a0[None, :] / f, rng, prm, False, season)
            hw = sim["home_win"]
            ot = sim["ot"]
            so = sim["so"]
            x_end = z + U[:, :, -1]
            del U
            ph = np.where(hw, 2, np.where(ot, 1, 0)).astype(np.float32)
            pa = np.where(~hw, 2, np.where(ot, 1, 0)).astype(np.float32)
            hwf = hw.astype(np.float32)
            awf = 1.0 - hwf
            P = S0["P"][None, :] + np.rint(ph @ OHh + pa @ OHa).astype(np.int64)
            W = S0["W"][None, :] + np.rint(hwf @ OHh + awf @ OHa).astype(np.int64)
            rwh = (hw & ~ot).astype(np.float32)
            rwa = (~hw & ~ot).astype(np.float32)
            RW = S0["RW"][None, :] + np.rint(rwh @ OHh + rwa @ OHa).astype(np.int64)
            rowh = (hw & ~so).astype(np.float32)
            rowa = (~hw & ~so).astype(np.float32)
            ROW = S0["ROW"][None, :] + np.rint(rowh @ OHh + rowa @ OHa).astype(np.int64)
            gfh = sim["hs"].astype(np.float32)
            gfa = sim["as_"].astype(np.float32)
            GFm = S0["GF"][None, :] + np.rint(gfh @ OHh + gfa @ OHa).astype(np.int64)
            GAm = S0["GA"][None, :] + np.rint(gfa @ OHh + gfh @ OHa).astype(np.int64)
            GPm = np.broadcast_to(S0["GP"] + np.bincount(np.concatenate([hi, ai]), minlength=T), (S, T))
            HP = np.broadcast_to(S0["HP0"], (S, T, T)).astype(np.int16).copy()
            if len(pairs):
                phx = np.concatenate([ph, np.zeros((S, 1), np.float32)], 1)[:, PC]
                pax = np.concatenate([pa, np.zeros((S, 1), np.float32)], 1)[:, PC]
                pi_pts = np.where(PS > 0, phx, np.where(PS < 0, pax, 0)).sum(2).astype(np.int16)
                pj_pts = np.where(PS > 0, pax, np.where(PS < 0, phx, 0)).sum(2).astype(np.int16)
                HP[:, PI, PJ] += pi_pts
                HP[:, PJ, PI] += pj_pts
            del ph, pa
        else:
            x_end = z
            P, W, RW, ROW = (np.broadcast_to(S0[k], (S, T)).copy() for k in ("P", "W", "RW", "ROW"))
            GFm, GAm, GPm = (np.broadcast_to(S0[k], (S, T)).copy() for k in ("GF", "GA", "GP"))
            HP = np.broadcast_to(S0["HP0"], (S, T, T)).astype(np.int16).copy()
        K = sort_key(P, GPm, RW, ROW, W, kind)
        rk = Ranker(K, HP, S0["NG"], GFm - GAm, GFm, steps, rng)
        league_order = rk.rank(all_mem)
        lpos = np.empty_like(league_order)
        ar = np.arange(S)
        lpos[ar[:, None], league_order] = np.arange(T)[None, :]
        acc["pres"] += np.bincount(league_order[:, 0], minlength=T)
        acc["pts"] += P.sum(0)
        acc["w"] += W.sum(0)
        acc["rw"] += RW.sum(0)
        pts_hist += np.bincount((np.arange(T)[None, :] * (maxp + 1) + np.clip(P, 0, maxp)).ravel(),
                                minlength=T * (maxp + 1)).reshape(T, maxp + 1)
        made = np.zeros((S, T), bool)
        div_orders = {d: rk.rank(m) for d, m in div_mem.items()}
        for d, o in div_orders.items():
            acc["div"] += np.bincount(o[:, 0], minlength=T)
            m = o.shape[1]
            div_rank[:, :m] += np.bincount((o * 8 + np.arange(m)[None, :]).ravel(), minlength=T * 8).reshape(T, 8)[:, :m]
        champ_by_conf = []
        if fname == "wildcard":
            for c, cm in conf_mem.items():
                cdivs = [d for d in divs if set(div_mem[d]) <= set(cm)]
                if len(cdivs) != 2:
                    continue
                top = {d: div_orders[d][:, :3] for d in cdivs}
                inn = np.zeros((S, T), bool)
                for d in cdivs:
                    inn[ar[:, None], top[d]] = True
                    acc["top3"] += np.bincount(top[d].ravel(), minlength=T)
                # wild cards: best two of the rest of the conference
                corder = rk.rank(cm)
                rest = np.where(inn[ar[:, None], corder], 10 ** 6, np.arange(len(cm))[None, :])
                wpos = np.argsort(rest, axis=1, kind="stable")[:, :2]
                wc = np.take_along_axis(corder, wpos, 1)
                acc["wc"] += np.bincount(wc.ravel(), minlength=T)
                made[ar[:, None], wc] = True
                made |= inn
                # bracket
                w1, w2 = top[cdivs[0]][:, 0], top[cdivs[1]][:, 0]
                best = _better_rank(rk, w1, w2)
                other = np.where(best == w1, w2, w1)
                best_div0 = best == w1
                # division A bracket half: winner A plays WC2 if A's winner is the better winner else WC1
                halves = []
                for di, d in enumerate(cdivs):
                    win = top[d][:, 0]
                    is_best = (best_div0 if di == 0 else ~best_div0)
                    opp = np.where(is_best, wc[:, 1], wc[:, 0])
                    halves.append([(win, opp), (top[d][:, 1], top[d][:, 2])])
                r2 = []
                for half in halves:
                    ws = []
                    for (a, b) in half:
                        reach["r1"] += np.bincount(np.concatenate([a, b]), minlength=T)
                        hh = _better(a, b, lpos)
                        ll = np.where(hh == a, b, a)
                        wv = _series(hh, ll, P0, kpo, x_end, S0["SW"], rng)
                        _tally(pair_ct[0], hh, ll, wv)
                        ws.append(wv)
                    a, b = ws
                    reach["r2"] += np.bincount(np.concatenate([a, b]), minlength=T)
                    hh = _better(a, b, lpos)
                    ll = np.where(hh == a, b, a)
                    wv = _series(hh, ll, P0, kpo, x_end, S0["SW"], rng)
                    _tally(pair_ct[1], hh, ll, wv)
                    r2.append(wv)
                a, b = r2
                reach["conf_final"] += np.bincount(np.concatenate([a, b]), minlength=T)
                hh = _better(a, b, lpos)
                ll = np.where(hh == a, b, a)
                cw = _series(hh, ll, P0, kpo, x_end, S0["SW"], rng)
                _tally(pair_ct[2], hh, ll, cw)
                champ_by_conf.append(cw)
        elif fname == "conf8":
            for c, cm in conf_mem.items():
                cdivs = [d for d in divs if set(div_mem[d]) <= set(cm)]
                winners = np.stack([div_orders[d][:, 0] for d in cdivs], 1)
                worder = _rank_subset(rk, winners)
                corder = rk.rank(cm)
                isw = np.zeros((S, T), bool)
                isw[ar[:, None], winners] = True
                rest = np.where(isw[ar[:, None], corder], 10 ** 6, np.arange(len(cm))[None, :])
                others = np.take_along_axis(corder, np.argsort(rest, axis=1, kind="stable")[:, :8 - len(cdivs)], 1)
                seeds = np.concatenate([worder, others], 1)            # seed 1..8
                made[ar[:, None], seeds] = True
                cur = seeds
                for rnd in range(3):
                    m = cur.shape[1]
                    nxt = []
                    for k in range(m // 2):
                        a, b = cur[:, k], cur[:, m - 1 - k]
                        reach[rounds[rnd]] += np.bincount(np.concatenate([a, b]), minlength=T)
                        wv = _series(a, b, P0, kpo, x_end, S0["SW"], rng)       # higher seed home ice
                        _tally(pair_ct[rnd], a, b, wv)
                        nxt.append(wv)
                    cur = np.stack(nxt, 1)
                    # reseed: the winners in original seed order (best remaining seed v worst)
                    pos = np.full((S, T), 99)
                    pos[ar[:, None], seeds] = np.arange(8)[None, :]
                    o = np.argsort(pos[ar[:, None], cur], axis=1)
                    cur = np.take_along_axis(cur, o, 1)
                champ_by_conf.append(cur[:, 0])
        elif fname == "div4":
            semis = []
            for d, m in div_mem.items():
                o = div_orders[d][:, :4]
                made[ar[:, None], o] = True
                reach["r1"] += np.bincount(o.ravel(), minlength=T)
                w1 = _series(o[:, 0], o[:, 3], P0, kpo, x_end, S0["SW"], rng)
                w2 = _series(o[:, 1], o[:, 2], P0, kpo, x_end, S0["SW"], rng)
                reach["r2"] += np.bincount(np.concatenate([w1, w2]), minlength=T)
                hh = _better(w1, w2, lpos)
                ll = np.where(hh == w1, w2, w1)
                semis.append(_series(hh, ll, P0, kpo, x_end, S0["SW"], rng))
            sm = np.stack(semis, 1)
            o = np.argsort(np.take_along_axis(lpos, sm, 1), axis=1)
            sm = np.take_along_axis(sm, o, 1)
            reach["conf_final"] += np.bincount(sm.ravel(), minlength=T)
            champ_by_conf = [_series(sm[:, 0], sm[:, 3], P0, kpo, x_end, S0["SW"], rng),
                             _series(sm[:, 1], sm[:, 2], P0, kpo, x_end, S0["SW"], rng)]
        cup = None
        if len(champ_by_conf) >= 2:
            a, b = champ_by_conf[0], champ_by_conf[1]
            reach["final"] += np.bincount(np.concatenate([a, b]), minlength=T)
            acc["conf"] += np.bincount(np.concatenate([a, b]), minlength=T)
            hh = _better(a, b, lpos)
            ll = np.where(hh == a, b, a)
            cup = _series(hh, ll, P0, kpo, x_end, S0["SW"], rng)
            _tally(pair_ct[3], hh, ll, cup)
            acc["cup"] += np.bincount(cup, minlength=T)
        acc["playoffs"] += made.sum(0)
        # lottery: non-playoff clubs, worst first
        non = ~made
        nn = int(non.sum(1).min())
        if nn > 0:
            k_l = min(nl, nn)
            lo = league_order[:, ::-1]
            keep = np.take_along_axis(non, lo, 1)
            pos = np.where(keep, np.arange(T)[None, :], 10 ** 6)
            sel = np.take_along_axis(lo, np.argsort(pos, axis=1, kind="stable")[:, :k_l], 1)
            Mk = LM if k_l == nl else lottery_matrix(LOTTERY_ODDS[:k_l])
            np.add.at(lot[:, :k_l], sel.ravel(), np.tile(Mk, (S, 1)))
        # interventional next-game odds
        if Gn:
            outs = np.stack([made, np.zeros((S, T), bool), np.zeros((S, T), bool), np.zeros((S, T), bool)], 2)
            for d, o in div_orders.items():
                outs[ar, o[:, 0], 1] = True
            if cup is not None:
                outs[ar, cup, 2] = True
            outs[ar, league_order[:, 0], 3] = True
            for t, k in next_col.items():
                is_home = hi[k] == t
                won = hw[:, k] if is_home else ~hw[:, k]
                lg = np.log(p_home0[k] / (1 - p_home0[k])) + kreg * dx[:, k]
                pk = 1 / (1 + np.exp(-lg))
                p_t = np.clip(pk if is_home else 1 - pk, 1e-3, 1 - 1e-3)
                ww, wl = 1.0 / p_t, 1.0 / (1.0 - p_t)
                r_ = nx[t]
                r_["n"] += S
                r_["p_sum"] += float(p_t.sum())
                r_["win"] += (outs[won, t, :] * ww[won, None]).sum(0)
                r_["loss"] += (outs[~won, t, :] * wl[~won, None]).sum(0)
                r_["w_win"] += float(ww[won].sum())
                r_["w_loss"] += float(wl[~won].sum())
        nres += rk.n_resolved
        del HP, K
    nsim = float(n)
    Rm = np.bincount(np.concatenate([hi, ai]), minlength=T) if Gn else np.zeros(T, int)
    mg = magic_numbers(S0["P"], Rm, div_id, conf_id, fname)
    if isinstance(cache, dict) and "order" in cache:
        cur_order = cache["order"]
    else:
        cur_order = _current_order(S0, kind, steps, seed)
        if isinstance(cache, dict):
            cache["order"] = cur_order
    out_teams = {}
    ph_ = pts_hist / nsim
    cdf = ph_.cumsum(1)
    for i, t in enumerate(teams):
        nxt = None
        if i in nx and nx[i]["n"] > 0:
            r_ = nx[i]
            k = next_col[i]
            keys = ("p_playoffs", "p_div", "p_cup", "p_pres")
            nxt = {"game_id": rem[k]["game_id"], "date": str(rem[k]["date"])[:10], "opp": teams[ai[k] if hi[k] == i else hi[k]],
                   "home": bool(hi[k] == i), "p_win": float(r_["p_sum"] / r_["n"]),
                   "if_win": {kk: float(v / r_["w_win"]) if r_["w_win"] > 0 else None for kk, v in zip(keys, r_["win"])},
                   "if_loss": {kk: float(v / r_["w_loss"]) if r_["w_loss"] > 0 else None for kk, v in zip(keys, r_["loss"])}}
        pd_ = ph_[i]
        out_teams[t] = {
            "conference": S0["info"][t].get("conference"), "division": S0["info"][t].get("division"),
            "current": {"gp": int(S0["GP"][i]), "w": int(S0["W"][i]), "l": int(S0["L"][i]), "otl": int(S0["OTL"][i]),
                        "pts": int(S0["P"][i]), "rw": int(S0["RW"][i]), "row": int(S0["ROW"][i]), "gf": int(S0["GF"][i]),
                        "ga": int(S0["GA"][i]), "p_pct": float(S0["P"][i] / (2 * S0["GP"][i])) if S0["GP"][i] else None,
                        "remaining": int(Rm[i]), "div_rank": cur_order["div"].get(t), "conf_rank": cur_order["conf"].get(t),
                        "league_rank": cur_order["league"].get(t)},
            "rating": float(base[i]), "rating_se": float(se[i]),
            "exp_pts": float(acc["pts"][i] / nsim), "exp_w": float(acc["w"][i] / nsim), "exp_rw": float(acc["rw"][i] / nsim),
            "pts_p05": int(np.searchsorted(cdf[i], 0.05)), "pts_p50": int(np.searchsorted(cdf[i], 0.5)),
            "pts_p95": int(np.searchsorted(cdf[i], 0.95)),
            "points_dist": {int(k): round(float(v), 5) for k, v in enumerate(pd_) if v > 0},
            "p_points_ge": {int(N): round(float(pd_[N:].sum()), 5) for N in PTS_LADDER if N <= maxp},
            "p_playoffs": float(acc["playoffs"][i] / nsim), "p_div": float(acc["div"][i] / nsim),
            "p_top3": float(acc["top3"][i] / nsim), "p_wildcard": float(acc["wc"][i] / nsim),
            "p_pres": float(acc["pres"][i] / nsim), "p_conf": float(acc["conf"][i] / nsim), "p_cup": float(acc["cup"][i] / nsim),
            "p_reach": {r: float(reach[r][i] / nsim) for r in rounds},
            "div_rank_dist": [round(float(x / nsim), 5) for x in div_rank[i, :len(div_mem.get(S0["info"][t].get("division"), []))]],
            "lottery": {"p_first": float(lot[i, 0] / nsim), "p_top2": float(lot[i, :2].sum() / nsim),
                        "pick_dist": [round(float(x / nsim), 5) for x in lot[i]]},
            "magic": mg[i]["magic"], "tragic": mg[i]["tragic"], "clinched": mg[i]["clinched"], "eliminated": mg[i]["eliminated"],
            "next": nxt,
        }
    bracket = {"format": fname, "rounds": rounds, "matchups": {}}
    for r, cts in zip(rounds, pair_ct):
        rows = sorted(cts.items(), key=lambda kv: -kv[1][0])[:24]
        bracket["matchups"][r] = [{"home_ice": teams[a], "other": teams[b], "p": round(c / nsim, 5),
                                   "p_home_ice_wins": round(w / c, 4) if c else None} for (a, b), (c, w) in rows]
    notes = []
    if S0["post_started"]:
        notes.append("postseason under way: played playoff games fixed")
    if fname != "wildcard":
        notes.append(f"historical format {fname}")
    return {"ok": True, "season": season, "teams": out_teams, "bracket": bracket, "n_sims": int(n),
            "runtime_s": round(time.perf_counter() - t0, 3), "format": fname, "tiebreak": {"key": kind, "steps": steps,
                                                                                         "source": TIEBREAK_SOURCE},
            "remaining_games": Gn, "groups": {"divisions": {d: [teams[i] for i in m] for d, m in div_mem.items()},
                                              "conferences": {c: [teams[i] for i in m] for c, m in conf_mem.items()}},
            "lottery": {"odds": list(LOTTERY_ODDS), "sources": LOTTERY_SOURCES, "table": lottery_table()},
            "ties_drawn": int(nres), "se_scale": se_scale, "drift": drift, "k_po": kpo, "notes": notes,
            "through": str(state.get("through")) if state.get("through") else None}


SENS_SHIFTS = (-0.75, -0.4, -0.15, 0.0, 0.15, 0.4, 0.75)   # goals a game, net (a star skater ~0.2, a starting goalie ~0.5)
SENS_SIMS = 1000


def _sens_values(rec: dict) -> dict:
    lot = rec.get("lottery") or {}
    return {"exp_pts": rec.get("exp_pts"), "p_playoffs": rec.get("p_playoffs"), "p_div": rec.get("p_div"),
            "p_conf": rec.get("p_conf"), "p_cup": rec.get("p_cup"), "p_first": lot.get("p_first"),
            "p_top2": lot.get("p_top2")}


def sensitivity(season: int, shifts=SENS_SHIFTS, n: int = SENS_SIMS, seed: int = 0, state: dict | None = None,
                teams: list[str] | None = None) -> dict:
    """{"ok", "shifts", "n_sims", "keys", "teams": {abbr: {key: [value at each shift]}}, "runtime_s"}: each club's
    expected points and its playoff, division, conference, Cup and draft-lottery odds when that club alone is `shift`
    goals a game (net) better for the rest of the season. Every run re-simulates the whole season with the same seed
    (common random numbers) and shares the setup (state, game means, playoff matrix)."""
    t0 = time.perf_counter()
    st = dict(state or {})
    st["_cache"] = {}
    st.pop("shift", None)
    shifts = [float(x) for x in shifts]
    base = simulate(season, n=n, seed=seed, state=st)
    if not base.get("ok") or not base.get("teams"):
        return {"ok": False, "reason": base.get("reason") or "no simulation", "teams": {}}
    tids = [t for t in (teams or list(base["teams"])) if t in base["teams"]]
    keys = list(_sens_values(next(iter(base["teams"].values()))))
    out: dict[str, dict] = {}
    for t in tids:
        cols = {}
        for d in shifts:
            rec = base["teams"][t] if d == 0.0 else simulate(season, n=n, seed=seed, state={**st, "shift": {t: d}})["teams"][t]
            cols[d] = _sens_values(rec)
        out[t] = {k: [None if cols[d][k] is None else round(float(cols[d][k]), 5) for d in shifts] for k in keys}
    return {"ok": True, "shifts": shifts, "n_sims": int(n), "seed": int(seed), "keys": keys, "teams": out,
            "runtime_s": round(time.perf_counter() - t0, 2)}


def _tally(store: dict, hh, ll, win) -> None:
    key = hh.astype(np.int64) * 1000 + ll
    u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    wins = np.bincount(inv, weights=(win == hh).astype(float), minlength=len(u))
    for k, c, w in zip(u, cnt, wins):
        a, b = divmod(int(k), 1000)
        cur = store.get((a, b), (0, 0.0))
        store[(a, b)] = (cur[0] + int(c), cur[1] + float(w))


def _better_rank(rk: Ranker, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per simulation, which of two clubs ranks higher by the procedure."""
    out = np.where(rk.K[np.arange(len(a)), a] > rk.K[np.arange(len(a)), b], a, b)
    eq = rk.K[np.arange(len(a)), a] == rk.K[np.arange(len(a)), b]
    for s in np.nonzero(eq)[0]:
        out[s] = rk.resolve([int(a[s]), int(b[s])], int(s))[0]
    return out


def _rank_subset(rk: Ranker, M: np.ndarray) -> np.ndarray:
    """Order each row's clubs (S, m) by the procedure."""
    S, m = M.shape
    Km = rk.K[np.arange(S)[:, None], M]
    o = np.argsort(-Km, axis=1, kind="stable")
    R = np.take_along_axis(M, o, 1)
    Ks = np.take_along_axis(Km, o, 1)
    for s in np.nonzero(np.any(Ks[:, 1:] == Ks[:, :-1], axis=1))[0]:
        row, ks, out, i = list(R[s]), Ks[s], [], 0
        while i < m:
            j = i + 1
            while j < m and ks[j] == ks[i]:
                j += 1
            out += rk.resolve(row[i:j], int(s)) if j - i > 1 else row[i:j]
            i = j
        R[s] = out
    return R


def _po_matrix(rd: dict, teams: list[str], prm: dict, season: int) -> tuple[np.ndarray, float, float]:
    """P0[h, a] = P(h wins a playoff game at home); k_po / k_reg = d logit / d (goal-rate edge) for playoff and regular
    season games (numerical, at the league mean)."""
    T = len(teams)
    hh, aa = np.meshgrid(np.arange(T), np.arange(T), indexing="ij")
    g = pd.DataFrame({"home": [teams[i] for i in hh.ravel()], "away": [teams[j] for j in aa.ravel()],
                      "neutral": False, "season": season, "rest_h": 1.0, "rest_a": 1.0, "b2b_h": 0.0, "b2b_a": 0.0,
                      "km_h": 0.0, "km_a": 0.0, "tz_h": 0.0, "tz_a": 0.0})
    F = GM.features(g, rd)
    mh, ma = GM.means(F, prm)
    P0 = GM.outcome_probs(mh, ma, prm, True, season)["p_home"].reshape(T, T)
    P0 = np.clip(P0, 0.02, 0.98)
    gbar = float((rd.get("league") or {}).get("goals_pg", 3.0))
    m = float(np.mean(mh))
    eps = 0.1
    slopes = []
    for po in (True, False):
        f = math.exp(eps / (2 * gbar))
        p1 = GM.outcome_probs([m * f], [m / f], prm, po, season)["p_home"][0]
        p0 = GM.outcome_probs([m / f], [m * f], prm, po, season)["p_home"][0]
        slopes.append(float((math.log(p1 / (1 - p1)) - math.log(p0 / (1 - p0))) / (2 * eps)))
    return P0, slopes[0], slopes[1]


def _canon_order(S0: dict) -> dict | None:
    """canon.rank over the played regular-season games (league, conference and division orders), or None."""
    try:
        from oddsmarkets.nhl import canon
    except Exception:  # noqa: BLE001
        return None
    G = S0["games"]
    if G is None or not len(G):
        return None
    pl = G[(G["gtype"] == "REG") & G["played"]]
    games = [{"home": r.home, "away": r.away, "hs": int(r.hs), "as": int(r.as_), "ot": bool(r.ot), "so": bool(r.so),
              "status": "final", "type": 2, "start": str(r.date)[:10], "game_id": r.game_id} for r in pl.itertuples(index=False)]
    rec = {}
    for i, t in enumerate(S0["teams"]):
        rec[t] = {"gp": int(S0["GP"][i]), "w": int(S0["W"][i]), "l": int(S0["L"][i]), "otl": int(S0["OTL"][i]),
                  "pts": int(S0["P"][i]), "rw": int(S0["RW"][i]), "row": int(S0["ROW"][i]), "gf": int(S0["GF"][i]),
                  "ga": int(S0["GA"][i])}
    season = S0["season"]
    try:
        out = {"league": {t: k + 1 for k, t in enumerate(canon.rank(list(S0["teams"]), rec, games, season))}, "conf": {}, "div": {}}
        for k, c in enumerate(S0["confs"]):
            mem = [S0["teams"][i] for i in np.nonzero(S0["conf_id"] == k)[0]]
            out["conf"].update({t: j + 1 for j, t in enumerate(canon.rank(mem, rec, games, season))})
        for k, d in enumerate(S0["divs"]):
            mem = [S0["teams"][i] for i in np.nonzero(S0["div_id"] == k)[0]]
            out["div"].update({t: j + 1 for j, t in enumerate(canon.rank(mem, rec, games, season))})
        return out
    except Exception as exc:  # noqa: BLE001
        logger.info("canon.rank failed (%s); using the simulator's ranker", exc)
        return None


def _current_order(S0: dict, kind: str, steps: list[str], seed: int) -> dict:
    co = _canon_order(S0)
    if co is not None:
        return co
    T = S0["T"]
    K = sort_key(S0["P"], S0["GP"], S0["RW"], S0["ROW"], S0["W"], kind)[None, :]
    rk = Ranker(K, S0["HP0"][None].astype(np.int16), S0["NG"], (S0["GF"] - S0["GA"])[None], S0["GF"][None], steps,
                np.random.default_rng(seed + 1))
    teams = S0["teams"]
    out = {"league": {}, "conf": {}, "div": {}}
    for i, t in enumerate(rk.rank(np.arange(T))[0]):
        out["league"][teams[t]] = i + 1
    for k, c in enumerate(S0["confs"]):
        for i, t in enumerate(rk.rank(np.nonzero(S0["conf_id"] == k)[0])[0]):
            out["conf"][teams[t]] = i + 1
    for k, d in enumerate(S0["divs"]):
        for i, t in enumerate(rk.rank(np.nonzero(S0["div_id"] == k)[0])[0]):
            out["div"][teams[t]] = i + 1
    return out


def standings(season: int, store: dict | None = None, through: Any = None) -> list[dict]:
    """Current standings rows (league order by the procedure) with division / conference / league ranks."""
    S0 = build_state(season, store, None, through)
    kind, steps = tiebreak_steps(season)
    o = _current_order(S0, kind, steps, 0)
    rows = []
    for i, t in enumerate(S0["teams"]):
        rows.append({"team": t, "division": S0["info"][t].get("division"), "conference": S0["info"][t].get("conference"),
                     "gp": int(S0["GP"][i]), "w": int(S0["W"][i]), "l": int(S0["L"][i]), "otl": int(S0["OTL"][i]),
                     "pts": int(S0["P"][i]), "rw": int(S0["RW"][i]), "row": int(S0["ROW"][i]), "gf": int(S0["GF"][i]),
                     "ga": int(S0["GA"][i]), "p_pct": round(float(S0["P"][i] / (2 * S0["GP"][i])), 3) if S0["GP"][i] else None,
                     "league_rank": o["league"][t], "conf_rank": o["conf"][t], "div_rank": o["div"][t]})
    rows.sort(key=lambda r: r["league_rank"])
    return rows


def for_season(season: int, n: int = 20000, seed: int = 0, through: Any = None, state: dict | None = None) -> dict:
    st = dict(state or {})
    st.setdefault("through", through)
    try:
        return simulate(season, n=n, seed=seed, state=st)
    except Exception as exc:  # noqa: BLE001
        logger.exception("season_sim failed")
        return {"ok": False, "reason": f"error: {exc}", "teams": {}, "n_sims": 0}
