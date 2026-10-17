"""
Win-probability path of a match, game by game, from the live or finished score.

The chain (match_chain.LiveTable) gives P(player 1 wins) from any (sets, games, server, points) state
for the match's serve-point probabilities (pre-match, from predict(); they are held fixed during the
match: no in-match updating of strength).

Game order. Sources give games per set, not the order of games within a set. When the order is not
observed (`sequence` not given) it is reconstructed, and the path says so ("reconstructed": true):
  * the match's first server is the one that makes the observed set scores most likely
    (product of the exact set-score probabilities, each set's first server following from the
    parity of the games before it); when the live feed names the current server, that fixes it;
  * within a set, among all game sequences that reach the score without ending the set early, the most
    likely under the hold probabilities (holds as served, only the breaks the score needs); ties between
    equally likely orders go to the one whose breaks are most evenly spread through the set;
  * a set that went to a tiebreak is 12 games to 6-6 plus the tiebreak as one step; an advantage set
    beyond 5-5 is split pairs of holds and then the two games that decide it.
So excitement and comeback are exact at set boundaries and approximate within sets for reconstructed
paths; with an observed `sequence` they are exact at game level.

Measures
  leverage of a game = P(win | player 1 wins the game) - P(win | player 1 loses it), at the state before it;
  excitement = sum over steps of |delta p| (pre-match to final, 0/1 at the end of a finished match);
  comeback = the winner's minimum win probability along the path (pre-match included), and where;
  swings = the largest |delta p| steps.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from oddsmarkets.tennis.models import match_chain as mc

MAX_SWINGS = 5


def _hold(p):
    return float(mc.game_win(p))


def set_sequence(a: int, c: int, b: int, hA: float, hB: float, rule: str = "tb7", complete: bool = True) -> dict:
    """
    Most likely game order for a set ending (or standing, if not complete) at a-c, player 1's games first,
    first served by `b`. -> {"games": [0/1 winner per game], "tiebreak": 0/1 winner | None}.
    """
    tb_at, _ = mc._rule(rule)
    tb = complete and tb_at is not None and max(a, c) == tb_at + 1 and min(a, c) == tb_at
    ta, tc = (tb_at, tb_at) if tb else (a, c)
    lh = {0: (math.log(max(hA, 1e-12)), math.log(max(1 - hA, 1e-12))),
          1: (math.log(max(hB, 1e-12)), math.log(max(1 - hB, 1e-12)))}

    def ll(g, srv):
        return lh[srv][0] if g == srv else lh[srv][1]

    tail: list[int] = []
    # long sets: prefix to 5-5, then pairs of holds, then the leader's games
    if ta + tc > 12 or (tb_at == 12 and tb):
        lo = min(ta, tc)
        pre = (5, 5)
        n = 10
        for g in range(5, lo):
            for k in range(2):
                srv = b if (n % 2 == 0) else 1 - b
                tail.append(srv)                          # holds
                n += 1
        lead = 0 if ta > tc else 1
        for _ in range(abs(ta - tc)):
            tail.append(lead)
        ta, tc = pre
    best: list = [None, None, None]                       # (ll, evenness, seq)

    def finish(seq, lsum):
        brk = [i for i, g in enumerate(seq) if g != (b if i % 2 == 0 else 1 - b)]
        L = max(len(seq), 1)
        K = len(brk)
        even = sum(abs((p + 0.5) / L - (j + 0.5) / K) for j, p in enumerate(brk)) if K else 0.0
        key = (round(lsum, 9), -even)
        if best[0] is None or key > (best[0], best[1]):
            best[0], best[1], best[2] = key[0], key[1], list(seq)

    seq: list[int] = []

    def dfs(g1, g2, lsum):
        if (g1, g2) == (ta, tc):
            finish(seq, lsum)
            return
        if g1 > ta or g2 > tc:
            return
        if mc._terminal(g1, g2, tb_at) or (tb_at is not None and g1 == g2 == tb_at):
            return
        srv = b if (g1 + g2) % 2 == 0 else 1 - b
        for g in (0, 1):
            seq.append(g)
            dfs(g1 + (g == 0), g2 + (g == 1), lsum + ll(g, srv))
            seq.pop()

    dfs(0, 0, 0.0)
    games = (best[2] or []) + tail
    return {"games": games, "tiebreak": (0 if a > c else 1) if tb else None}


def _set_scores(match: dict) -> tuple[list[tuple[int, int]], tuple[int, int] | None]:
    """(completed sets, current set games | None) from a MATCH (p1's view)."""
    sets = [(int(s[0]), int(s[1])) for s in (match.get("sets") or []) if s and s[0] is not None and s[1] is not None]
    live = match.get("live") or None
    status = str(match.get("status") or "")
    if live and status == "live":
        k = int(live.get("set") or len(sets) or 1)
        done = sets[:k - 1]
        g = live.get("games") or (sets[k - 1] if len(sets) >= k else [0, 0])
        return done, (int(g[0]), int(g[1]))
    if status in ("ret", "def") and sets:
        last = sets[-1]
        hi, lo = max(last), min(last)
        finished = (hi >= 6 and hi - lo >= 2) or (hi == 7 and lo == 6)
        if not finished:
            return sets[:-1], last
    return sets, None


def _set_winner(a, c):
    return 0 if a > c else 1


def first_server_ml(sets: list[tuple[int, int]], p1: float, p2: float, best_of: int, final_rule: str) -> int:
    """The match's first server (0/1) that makes the completed set scores most likely."""
    need = best_of // 2 + 1
    best, arg = -1.0, 0
    for F in (0, 1):
        b, s1, s2, lik = F, 0, 0, 1.0
        for (a, c) in sets:
            rule = final_rule if s1 == s2 == need - 1 else "tb7"
            d = mc.set_dist(p1, p2, b, rule)
            lik *= float(np.asarray(d.get((a, c), 0.0)).ravel()[0]) if (a, c) in d else 1e-12
            if (a + c) % 2 == 1:
                b = 1 - b
            s1 += a > c
            s2 += c > a
        if lik > best:
            best, arg = lik, F
    return arg


def path(match: dict, p_srv: tuple[float, float], sequence: list[list[int]] | None = None,
         first_server: int | None = None) -> dict:
    """
    Game-by-game P(player 1 wins) for a MATCH, given the pre-match serve-point probabilities (p1, p2).
    `sequence`: optional observed game winners per set ([[0, 1, 1, ...], ...], the tiebreak as the last entry
    of a 7-6 set). -> {"steps": [...], "p_pre", "excitement", "comeback", "swings", "set_path", "reconstructed",
    "first_server", "final_set_rule", "best_of"}.
    """
    pA, pB = float(p_srv[0]), float(p_srv[1])
    bo = 5 if int(match.get("best_of") or 3) == 5 else 3
    need = bo // 2 + 1
    rule = str(match.get("final_set_rule") or "tb7")
    lt = mc.LiveTable(pA, pB, bo, rule)
    hA, hB = _hold(pA), _hold(pB)
    done, cur = _set_scores(match)
    live = match.get("live") or {}
    # first server
    F = first_server
    if F is None and live and live.get("server") is not None and cur is not None:
        srv = 0 if str(live["server"]) == str(match.get("p1")) else 1
        n_before = sum(a + c for a, c in done) + cur[0] + cur[1]          # a tiebreak counts as one game
        F = srv if n_before % 2 == 0 else 1 - srv
    if F is None:
        F = first_server_ml(done + ([cur] if cur else []), pA, pB, bo, rule) if (done or cur) else 0
    p0 = float(lt.p_pre()[0])
    steps = [{"i": 0, "set": 1, "sets": [0, 0], "games": [0, 0], "server": None, "kind": "start", "p1": round(p0, 5),
              "delta": 0.0, "leverage": None, "winner": None}]
    set_path = [round(p0, 5)]
    s1 = s2 = 0
    b = F
    reconstructed = sequence is None
    all_sets = [(a, c, True) for a, c in done] + ([(cur[0], cur[1], False)] if cur else [])
    prev = p0
    i = 0
    for k, (a, c, complete) in enumerate(all_sets):
        srule = rule if s1 == s2 == need - 1 else "tb7"
        if sequence is not None and k < len(sequence):
            seqk = list(sequence[k])
            tb_at, _ = mc._rule(srule)
            is_tb = complete and tb_at is not None and max(a, c) == tb_at + 1 and min(a, c) == tb_at
            sq = {"games": seqk[:-1] if is_tb else seqk, "tiebreak": seqk[-1] if is_tb else None}
        else:
            sq = set_sequence(a, c, b, hA, hB, srule, complete)
        g1 = g2 = 0
        for g in sq["games"]:
            srv = b if (g1 + g2) % 2 == 0 else 1 - b
            before = float(lt.p((s1, s2), (g1, g2), srv)[0])
            nxt_srv = 1 - srv
            p_if_w = _after(lt, s1, s2, g1 + 1, g2, nxt_srv, srule, need, b)
            p_if_l = _after(lt, s1, s2, g1, g2 + 1, nxt_srv, srule, need, b)
            g1, g2 = g1 + (g == 0), g2 + (g == 1)
            now = p_if_w if g == 0 else p_if_l
            i += 1
            steps.append({"i": i, "set": k + 1, "sets": [s1, s2], "games": [g1, g2], "server": srv,
                          "kind": "hold" if g == srv else "break", "winner": g, "p1": round(now, 5),
                          "delta": round(now - before, 5), "leverage": round(p_if_w - p_if_l, 5)})
            prev = now
        if sq["tiebreak"] is not None:
            g = sq["tiebreak"]
            srv = b if (g1 + g2) % 2 == 0 else 1 - b
            before = float(lt.p((s1, s2), (g1, g2), srv)[0])
            p_if_w = _after(lt, s1, s2, g1 + 1, g2, 1 - srv, srule, need, b)
            p_if_l = _after(lt, s1, s2, g1, g2 + 1, 1 - srv, srule, need, b)
            g1, g2 = g1 + (g == 0), g2 + (g == 1)
            now = p_if_w if g == 0 else p_if_l
            i += 1
            steps.append({"i": i, "set": k + 1, "sets": [s1, s2], "games": [g1, g2], "server": srv, "kind": "tiebreak",
                          "winner": g, "p1": round(now, 5), "delta": round(now - before, 5),
                          "leverage": round(p_if_w - p_if_l, 5)})
            prev = now
        if complete:
            s1 += a > c
            s2 += c > a
            if (g1 + g2) % 2 == 1:
                b = 1 - b
            set_path.append(round(prev, 5))
    # the current point score (live)
    if cur is not None and live.get("points") and str(match.get("status")) == "live":
        srv = 0 if str(live.get("server")) == str(match.get("p1")) else (1 if live.get("server") is not None else None)
        pl = float(lt.p((s1, s2), cur, srv, live.get("points"))[0])
        i += 1
        steps.append({"i": i, "set": len(done) + 1, "sets": [s1, s2], "games": list(cur), "server": srv, "kind": "points",
                      "points": live.get("points"), "winner": None, "p1": round(pl, 5), "delta": round(pl - prev, 5),
                      "leverage": None})
        prev = pl
    status = str(match.get("status") or "")
    winner = None
    if status in ("done", "ret", "def", "wo") and match.get("winner") is not None:
        winner = 0 if str(match.get("winner")) == str(match.get("p1")) else 1
        end = 1.0 if winner == 0 else 0.0
        if abs(end - prev) > 1e-9:
            i += 1
            steps.append({"i": i, "set": len(all_sets), "sets": [s1, s2], "games": None, "server": None,
                          "kind": "retirement" if status in ("ret", "def") else "end", "winner": winner, "p1": end,
                          "delta": round(end - prev, 5), "leverage": None})
            prev = end
    ps = np.array([s["p1"] for s in steps])
    excitement = float(np.abs(np.diff(ps)).sum()) if len(ps) > 1 else 0.0
    comeback = None
    if winner is not None:
        wp = ps if winner == 0 else 1 - ps
        j = int(np.argmin(wp))
        comeback = {"winner": winner, "min_p": round(float(wp[j]), 5), "at": steps[j]["i"],
                    "sets": steps[j]["sets"], "games": steps[j]["games"]}
    swings = sorted([s for s in steps if s["kind"] in ("hold", "break", "tiebreak", "points")],
                    key=lambda s: -abs(s["delta"]))[:MAX_SWINGS]
    lev = [s["leverage"] for s in steps if s.get("leverage") is not None]
    return {"steps": steps, "p_pre": round(p0, 5), "excitement": round(excitement, 5), "comeback": comeback,
            "swings": [{"i": s["i"], "set": s["set"], "sets": s["sets"], "games": s["games"], "kind": s["kind"],
                        "winner": s["winner"], "delta": s["delta"]} for s in swings],
            "mean_leverage": round(float(np.mean(lev)), 5) if lev else None,
            "max_leverage": round(float(np.max(lev)), 5) if lev else None,
            "set_path": set_path, "reconstructed": reconstructed, "first_server": F, "best_of": bo,
            "final_set_rule": rule, "p_srv": [pA, pB]}


def _after(lt: mc.LiveTable, s1: int, s2: int, g1: int, g2: int, srv: int, rule: str, need: int, b: int) -> float:
    """P(player 1 wins) at games g1-g2 (next game served by `srv`), moving to the next set if this one ended."""
    tb_at, _ = mc._rule(rule)
    if mc._terminal(g1, g2, tb_at):
        n1, n2 = s1 + (g1 > g2), s2 + (g2 > g1)
        nb = b if (g1 + g2) % 2 == 0 else 1 - b
        return float(lt.p((n1, n2), (0, 0), nb)[0])
    return float(lt.p((s1, s2), (g1, g2), srv)[0])


def for_match(match: dict, ctx=None, tour: str | None = None, p_srv: tuple | None = None, **kw) -> dict:
    """path() with the serve-point probabilities from predict() as of the match date (or `p_srv`)."""
    if p_srv is None:
        from oddsmarkets.tennis.models import predict as P
        tour = tour or ("wta" if str(match.get("id", "")).startswith("wta") else "atp")
        ctx = ctx or P.context(tour, match.get("date"))
        r = P.predict(tour, match["p1"], match["p2"], match.get("surface") or "hard", int(match.get("best_of") or 3),
                      match.get("date"), match.get("level") or "250", ctx=ctx, final_set_rule=match.get("final_set_rule"),
                      with_dist=False)
        p_srv = tuple(r["p_srv"])
    return path(match, p_srv, **kw)
