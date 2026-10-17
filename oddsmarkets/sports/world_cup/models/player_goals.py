"""
Golden Boot model — Monte-Carlo estimate of P(each player finishes top scorer).

Plugged into TournamentSimulator: during each simulated tournament the simulator
reports every sampled knockout scoreline; we accumulate each team's future goals
and, at the end of the sim, distribute them across that team's candidate scorers
via a single Multinomial draw (statistically identical to allocating per match,
since a player's within-team goal share is constant). Each player's final total =
current goals already scored + simulated future goals. The per-sim leader (FIFA
tiebreak: goals → assists → random) increments a Golden-Boot counter.

Goal shares blend current-tournament output, historical scoring rate (StatsBomb
per-90), and a small role prior, plus a per-team "other players" bucket so that
depth scorers absorb realistic mass instead of inflating the tracked stars.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

# Share-weight blend (see module docstring)
W_CURRENT = 2.0      # each goal already scored this tournament
W_HIST = 1.2         # historical goals per 90
OTHER_TEAM_WEIGHT = 1.5   # unranked squad depth per team (untracked "other" bucket)
ROLE_BASE = {"FWD": 0.40, "MID": 0.15, "DEF": 0.05, "GK": 0.0, "": 0.15}


class GoldenBootModel:
    """Accumulator the simulator drives; call order per sim: start → allocate* → finalize."""

    def __init__(self, candidates: list[dict], seed: int = 7) -> None:
        # candidates: [{name, team, cur_goals, cur_assists, hist_goals_90, role}]
        self._rng = np.random.default_rng(seed)
        self.names = [c["name"] for c in candidates]
        self.teams = [c["team"] for c in candidates]
        n = len(candidates)
        self._cur_goals = np.array([c.get("cur_goals", 0) for c in candidates], dtype=float)
        self._cur_assists = np.array([c.get("cur_assists", 0) for c in candidates], dtype=float)
        self._boot_counts = np.zeros(n, dtype=np.int64)
        self._tally = np.zeros(n, dtype=float)
        self._team_goals: dict[str, int] = {}

        # Per team: global candidate indices + a probability vector over
        # [candidate_1..candidate_k, OTHER]. Weight blends current + historical + role.
        by_team: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(candidates):
            by_team[c["team"]].append(i)
        self._team_cand: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for team, idxs in by_team.items():
            weights = []
            for i in idxs:
                c = candidates[i]
                w = (W_CURRENT * c.get("cur_goals", 0)
                     + W_HIST * c.get("hist_goals_90", 0.0)
                     + ROLE_BASE.get(c.get("role", ""), 0.15))
                weights.append(max(w, 1e-4))
            weights.append(OTHER_TEAM_WEIGHT)      # untracked depth bucket
            probs = np.array(weights, dtype=float)
            probs /= probs.sum()
            self._team_cand[team] = (np.array(idxs, dtype=int), probs)

    # ── simulator-driven lifecycle ──────────────────────────────────────────
    def start_sim(self) -> None:
        self._team_goals.clear()

    def allocate(self, team: str, goals: int) -> None:
        if goals > 0 and team in self._team_cand:
            self._team_goals[team] = self._team_goals.get(team, 0) + goals

    def finalize_sim(self) -> None:
        self._tally.fill(0.0)
        for team, g in self._team_goals.items():
            if g <= 0:
                continue
            idx, probs = self._team_cand[team]
            draw = self._rng.multinomial(int(g), probs)
            self._tally[idx] += draw[:len(idx)]
        self._team_goals.clear()

        totals = self._cur_goals + self._tally
        top = totals.max()
        winners = np.flatnonzero(totals == top)
        if winners.size > 1:                     # tiebreak: assists, then random
            a = self._cur_assists[winners]
            winners = winners[a == a.max()]
        w = int(winners[0]) if winners.size == 1 else int(self._rng.choice(winners))
        self._boot_counts[w] += 1

    # ── batch lifecycle, for vectorized simulators ──────────────────────────
    def accumulate_batch(self, team_goals: "np.ndarray", teams: list[str]) -> None:
        """
        Score a whole chunk of simulations at once.

        The start_sim/allocate/finalize_sim lifecycle above assumes a simulator that
        walks matches one at a time in Python. A simulator vectorized over the
        simulation axis has no such hook — it advances every simulation together —
        so this takes the finished `(n_sims, n_teams)` goal totals directly.

        Statistically identical to the per-match path: a player's within-team goal
        share is constant, so allocating a team's season total in one Multinomial
        draw is the same as allocating each match separately.

        `team_goals[s, t]` is goals scored by `teams[t]` in simulation `s`.
        """
        if team_goals.ndim != 2 or team_goals.shape[1] != len(teams):
            raise ValueError(
                f"team_goals has shape {team_goals.shape}, expected (n_sims, {len(teams)})"
            )

        n_sims = team_goals.shape[0]
        tally = np.zeros((n_sims, len(self.names)), dtype=float)

        for t, team in enumerate(teams):
            entry = self._team_cand.get(team)
            if entry is None:
                continue
            idx, probs = entry
            goals = np.asarray(team_goals[:, t], dtype=np.int64)
            if not goals.any():
                continue
            # Generator.multinomial broadcasts over an array of trial counts, so the
            # whole chunk is one call rather than one per simulation.
            draws = self._rng.multinomial(goals, probs)
            tally[:, idx] += draws[:, : len(idx)]

        totals = self._cur_goals[None, :] + tally

        # Tiebreak goals -> assists -> random, expressed as a single sort key so the
        # winner is one argmax rather than a per-row search.
        jitter = self._rng.random(totals.shape) * 1e-6
        score = totals * 1e6 + self._cur_assists[None, :] * 1e-1 + jitter
        winners = np.argmax(score, axis=1)
        np.add.at(self._boot_counts, winners, 1)

    # ── output ──────────────────────────────────────────────────────────────
    def probabilities(self, n_sims: int) -> dict[str, float]:
        return {
            self.names[i]: self._boot_counts[i] / n_sims
            for i in range(len(self.names))
            if self._boot_counts[i] > 0
        }
