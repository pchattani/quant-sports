"""
Monte Carlo simulator for cups: a league or group phase, then a knockout bracket.

The league phase is the plain-league loop (fixtures fixed across simulations, one
vector operation each). The bracket is resolved from precomputed advance
probabilities — single-leg, single-leg neutral, and two-legged — looked up per
simulation, exactly as the MLS playoff is. Ties already decided are forced by
club pair; ties already drawn fix the bracket's shape.

Draws the competitions make at random (UEFA's play-off pairings within seeding
bands, CONMEBOL's Round of 16) are drawn here at random per simulation until the
real draw appears in the store.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from oddsmarkets.football.competitions.cup.config import CupConfig
from oddsmarkets.football.competitions.cup.season_state import CupState
from oddsmarkets.football.core.simulation import (
    ScoreSampler,
    advance_matrix,
    count_positions,
    rank_table,
    two_leg_advance_matrix,
)

logger = logging.getLogger(__name__)

# A stand-in for opponents from outside the competition: the Libertadores
# third-placed sides that enter the Sudamericana play-off, or a fixed-bracket slot
# with no distribution to draw from. It is the model's default club, and when it
# wins a tie it goes on in the bracket — as the real outside side would — so its
# share of the title is "any of them", not one club's.
AVERAGE = "Outside side (any)"


@dataclass
class CupResults:
    n_sims: int
    runtime_s: float
    teams: list[str] = field(default_factory=list)
    p_position: dict[str, list[float]] = field(default_factory=dict)      # league-phase table
    p_group_position: dict[str, list[float]] = field(default_factory=dict)
    expected_points: dict[str, float] = field(default_factory=dict)
    points_quantiles: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    p_band: dict[str, dict[str, float]] = field(default_factory=dict)
    p_reach: dict[str, dict[str, float]] = field(default_factory=dict)      # team -> round -> p
    p_win: dict[str, float] = field(default_factory=dict)
    team_goals_mean: dict[str, float] = field(default_factory=dict)

    # Duck-typing with LeagueResults for the shared payload builders.
    @property
    def p_title(self) -> dict[str, float]:
        return self.p_win

    def p_in_band(self, key: str, team: str) -> float:
        return self.p_band.get(key, {}).get(team, 0.0)


class CupSimulator:
    def __init__(
        self, model, state: CupState, cfg: CupConfig | None = None,
        n_sims: int | None = None, seed: int | None = None, chunk: int | None = None,
        boot_model=None, external_champions: dict[str, dict[str, float]] | None = None,
    ) -> None:
        self.model = model
        self.state = state
        self.cfg = cfg or state.cfg
        self.n_sims = n_sims if n_sims is not None else self.cfg.n_sims
        self.seed = seed if seed is not None else self.cfg.random_seed
        self.chunk = chunk if chunk is not None else self.cfg.sim_chunk
        self.boot_model = boot_model
        self.external = external_champions or {}

        teams = list(state.teams)
        # Clubs that can only enter through another competition's title.
        for dist in self.external.values():
            for t in dist:
                if t not in teams:
                    teams.append(t)
        if self.cfg.runners_up_playoff and AVERAGE not in teams:
            teams.append(AVERAGE)
        self.teams = teams
        self.n_teams = len(teams)
        self.team_idx = {t: i for i, t in enumerate(teams)}
        self.n_real = len(state.teams)
        self.sampler = ScoreSampler(model, self.teams, max_goals=self.cfg.max_goals)
        self._a1: np.ndarray | None = None
        self._a2: np.ndarray | None = None

        self._forced = np.full((self.n_teams, self.n_teams), -1, dtype=np.intp)
        for pair, winner in state.playoff_results.items():
            idx = [self.team_idx.get(t) for t in pair]
            w = self.team_idx.get(winner)
            if len(idx) == 2 and None not in idx and w is not None:
                self._forced[idx[0], idx[1]] = w
                self._forced[idx[1], idx[0]] = w

    # ── tie resolution ───────────────────────────────────────────────────────

    def _decide(self, home: np.ndarray, away: np.ndarray, rng, legs: int, neutral: bool = False) -> np.ndarray:
        """
        Winner per simulation of a tie between `home` and `away`, where for two
        legs `home` hosts the second leg and for one leg `home` hosts (unless
        neutral). Decided ties are forced.
        """
        if legs == 2:
            p_home = 1.0 - self._a2[away, home]
        elif neutral:
            p_home = 0.5 * (self._a1[home, away] + 1.0 - self._a1[away, home])
        else:
            p_home = self._a1[home, away]
        winners = np.where(rng.random(home.shape) < p_home, home, away)
        known = self._forced[home, away]
        return np.where(known >= 0, known, winners)

    def _known_slots(self, round_key: str, count: int) -> list[tuple[int, int]] | None:
        """Ties the store already knows for a round, as (leg-one host, leg-two host) indices."""
        pairs = self.state.known_pairs.get(round_key) or []
        idx = [(self.team_idx.get(a), self.team_idx.get(b)) for a, b in pairs]
        idx = [p for p in idx if None not in p]
        return idx if len(idx) == count else None

    # ── main ─────────────────────────────────────────────────────────────────

    def run(self) -> CupResults:
        start = time.perf_counter()
        cfg, state = self.cfg, self.state
        n, T = self.n_sims, self.n_teams
        rng = np.random.default_rng(self.seed)
        self._a1 = advance_matrix(self.model, self.teams, cfg.extra_time_weight, cfg.max_goals)
        if any(legs == 2 for _, legs in cfg.rounds):
            self._a2 = two_leg_advance_matrix(self.model, self.teams, cfg.extra_time_weight, cfg.max_goals)

        records = state.records()
        seed_pts = np.zeros(T, dtype=np.int32)
        seed_gf = np.zeros(T, dtype=np.int32)
        seed_ga = np.zeros(T, dtype=np.int32)
        for team, rec in records.items():
            i = self.team_idx.get(team)
            if i is not None:
                seed_pts[i], seed_gf[i], seed_ga[i] = rec.points, rec.gf, rec.ga
        fixtures = [
            (self.team_idx[m.home_team], self.team_idx[m.away_team])
            for m in state.remaining if not m.is_playoff
            and m.home_team in self.team_idx and m.away_team in self.team_idx
        ]
        group_cols = {
            g: np.array([self.team_idx[t] for t in members if t in self.team_idx], dtype=np.intp)
            for g, members in state.groups.items()
        }
        real = np.arange(self.n_real)
        logger.info("Simulating %s: %d fixtures remaining, %d sims", cfg.slug, len(fixtures), n)

        cnt_pos = np.zeros((T, max(self.n_real, 1)), dtype=np.int64)
        cnt_gpos = np.zeros((T, cfg.group_size), dtype=np.int64) if cfg.kind in ("groups", "regional_swiss") else None
        cnt_reach = {r: np.zeros(T, dtype=np.int64) for r in cfg.round_keys}
        cnt_win = np.zeros(T, dtype=np.int64)
        sum_pts = np.zeros(T, dtype=np.float64)
        sum_goals = np.zeros(T, dtype=np.float64)
        pts_samples: list[np.ndarray] = []

        done = 0
        while done < n:
            S = min(self.chunk, n - done)
            pts = np.tile(seed_pts, (S, 1)).astype(np.int32)
            gf = np.tile(seed_gf, (S, 1)).astype(np.int32)
            ga = np.tile(seed_ga, (S, 1)).astype(np.int32)
            goals = np.zeros((S, T), dtype=np.int32)
            for h, a in fixtures:
                hg, ag = self.sampler.sample(h, a, rng, S)
                hw, dr, aw = hg > ag, hg == ag, ag > hg
                pts[:, h] += cfg.points_win * hw + cfg.points_draw * dr
                pts[:, a] += cfg.points_win * aw + cfg.points_draw * dr
                gf[:, h] += hg; ga[:, h] += ag; gf[:, a] += ag; ga[:, a] += hg
                goals[:, h] += hg; goals[:, a] += ag
            gd = gf - ga

            if cfg.kind == "swiss":
                keys = [pts[:, real], gd[:, real], gf[:, real]]
                order, _ = rank_table(keys, rng)
                order = real[order]
                cnt_pos += self._count(order, T)
                self._swiss_bracket(order, rng, S, cnt_reach, cnt_win)
            elif cfg.kind in ("groups", "regional_swiss"):
                winners, runners, orders = [], [], {}
                for g in sorted(group_cols):
                    cols = group_cols[g]
                    if cols.size == 0:
                        continue
                    sub = [pts[:, cols], gd[:, cols], gf[:, cols]]
                    o, _ = rank_table(sub, rng)
                    tp = cols[o]
                    np.add.at(cnt_gpos, (tp, np.broadcast_to(np.arange(cols.size), tp.shape)), 1)
                    orders[g] = tp
                    if tp.shape[1] >= 2:
                        winners.append(tp[:, 0])
                        runners.append(tp[:, 1])
                if cfg.kind == "groups" and len(winners) == cfg.n_groups:
                    self._group_bracket(np.stack(winners, 1), np.stack(runners, 1), rng, S, cnt_reach, cnt_win)
                elif cfg.kind == "regional_swiss" and len(orders) == cfg.n_groups:
                    self._regional_bracket(orders, rng, S, cnt_reach, cnt_win)
            elif cfg.kind == "knockout":
                self._knockout_bracket(rng, S, cnt_reach, cnt_win)
            else:
                self._fixed_bracket(rng, S, cnt_reach, cnt_win)

            if self.boot_model is not None:
                self.boot_model.accumulate_batch(goals, self.teams)
            sum_pts += pts.sum(axis=0)
            sum_goals += goals.sum(axis=0)
            if len(pts_samples) * self.chunk < 5000:
                pts_samples.append(pts[: min(S, 2000)].copy())
            done += S

        runtime = time.perf_counter() - start
        logger.info("Simulated %d seasons in %.1fs", n, runtime)
        return self._assemble(n, runtime, cnt_pos, cnt_gpos, cnt_reach, cnt_win, sum_pts, sum_goals, pts_samples)

    def _count(self, order: np.ndarray, T: int) -> np.ndarray:
        S, P = order.shape
        counts = np.zeros((T, P), dtype=np.int64)
        np.add.at(counts, (order, np.broadcast_to(np.arange(P), order.shape)), 1)
        return counts

    # ── brackets ─────────────────────────────────────────────────────────────

    def _play_round(self, key: str, slots: list[tuple[np.ndarray, np.ndarray]], seed_of: dict | None,
                    rng, cnt_reach, legs: int, neutral: bool = False) -> list[np.ndarray]:
        """Play one round of ties; each slot is (leg-one host, leg-two host / away)."""
        for a, b in slots:
            np.add.at(cnt_reach[key], np.concatenate([a, b]), 1)
        return [self._decide(b, a, rng, legs, neutral) if legs == 2 else self._decide(a, b, rng, 1, neutral)
                for a, b in slots]

    def _pair_winners(self, key: str, winners: list[np.ndarray], seeds: np.ndarray, S: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """
        Next round's ties from this round's winners: adjacent pairs, the better
        seed hosting the second leg — unless the store already knows the ties.
        """
        known = self._known_slots(key, len(winners) // 2)
        if known is not None:
            return [(np.full(S, a, dtype=np.intp), np.full(S, b, dtype=np.intp)) for a, b in known]
        out = []
        for i in range(0, len(winners), 2):
            x, y = winners[i], winners[i + 1]
            x_better = seeds[np.arange(S), x] <= seeds[np.arange(S), y]
            host2 = np.where(x_better, x, y)
            host1 = np.where(x_better, y, x)
            out.append((host1, host2))
        return out

    def _swiss_bracket(self, order, rng, S, cnt_reach, cnt_win) -> None:
        cfg = self.cfg
        rows = np.arange(S)
        seeds = np.zeros((S, self.n_teams), dtype=np.int32)
        np.put_along_axis(seeds, order, np.broadcast_to(np.arange(1, order.shape[1] + 1), order.shape), axis=1)

        d = cfg.direct_qualifiers
        # Play-off: 9 v 24, 10 v 23 ... 16 v 17, the higher finisher at home second.
        po = self._known_slots("po", (cfg.playoff_last - d) // 2)
        if po is not None:
            po_slots = [(np.full(S, a, dtype=np.intp), np.full(S, b, dtype=np.intp)) for a, b in po]
        else:
            po_slots = [(order[:, cfg.playoff_last - 1 - i], order[:, d + i]) for i in range((cfg.playoff_last - d) // 2)]
        po_w = self._play_round("po", po_slots, None, rng, cnt_reach, legs=2)
        # Round of 16: seed 1 meets the winner of the last play-off pair (16 v 17) and so on.
        r16 = self._known_slots("r16", d)
        if r16 is not None:
            r16_slots = [(np.full(S, a, dtype=np.intp), np.full(S, b, dtype=np.intp)) for a, b in r16]
        else:
            r16_slots = [(po_w[len(po_w) - 1 - i], order[:, i]) for i in range(d)]
        w = self._play_round("r16", r16_slots, None, rng, cnt_reach, legs=2)
        # Fixed tree: [1, 8, 4, 5, 2, 7, 3, 6] by seed of the direct qualifier.
        tree = [0, 7, 3, 4, 1, 6, 2, 5] if d == 8 else list(range(d))
        w = [w[i] for i in tree]
        for key, legs in cfg.rounds[2:]:
            neutral = key == "final" and cfg.final_at_neutral_venue
            slots = self._pair_winners(key, w, seeds, S)
            w = self._play_round(key, slots, None, rng, cnt_reach, legs=legs, neutral=neutral)
        np.add.at(cnt_win, w[0], 1)

    def _group_bracket(self, winners, runners, rng, S, cnt_reach, cnt_win) -> None:
        cfg = self.cfg
        rows = np.arange(S)
        seeds = np.full((S, self.n_teams), 3, dtype=np.int32)
        seeds[rows[:, None], winners] = 1
        seeds[rows[:, None], runners] = 2
        legs = dict(cfg.rounds)
        # The first knockout round after the groups: a Round of 16 for eight
        # groups, quarter-finals for four.
        first = next(k for k, _ in cfg.rounds if k != "po")

        if cfg.runners_up_playoff:
            avg = np.full(S, self.team_idx[AVERAGE], dtype=np.intp)
            po = self._known_slots("po", cfg.n_groups)
            if po is not None:
                slots = [(np.full(S, a, dtype=np.intp), np.full(S, b, dtype=np.intp)) for a, b in po]
            else:
                slots = [(avg, runners[:, g]) for g in range(cfg.n_groups)]
            runners = np.stack(self._play_round("po", slots, None, rng, cnt_reach, legs=2), 1)

        known = self._known_slots(first, cfg.n_groups)
        if known is not None:
            slots = [(np.full(S, a, dtype=np.intp), np.full(S, b, dtype=np.intp)) for a, b in known]
        else:
            # Winners at home in the second leg against a runner-up from another group.
            perm = np.tile(np.arange(cfg.n_groups), (S, 1))
            for _ in range(20):
                bad = (perm == np.arange(cfg.n_groups)).any(axis=1)
                if not bad.any():
                    break
                perm[bad] = rng.permuted(perm[bad], axis=1)
            slots = [(runners[rows, perm[:, g]], winners[:, g]) for g in range(cfg.n_groups)]
        w = self._play_round(first, slots, None, rng, cnt_reach, legs=legs[first])
        for key, n_legs in cfg.rounds:
            if key in ("po", first):
                continue
            neutral = key in cfg.neutral_rounds or (key == "final" and cfg.final_at_neutral_venue)
            slots = self._pair_winners(key, w, seeds, S)
            w = self._play_round(key, slots, None, rng, cnt_reach, legs=n_legs, neutral=neutral)
        np.add.at(cnt_win, w[0], 1)

    def _random_pairs(self, arrs: list[np.ndarray], rng, S: int) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[np.ndarray]]:
        """Adjacent pairs of a per-simulation shuffle of `arrs`; an odd one out gets a bye."""
        stacked = rng.permuted(np.stack(arrs, 1), axis=1)
        k = stacked.shape[1]
        slots = [(stacked[:, i], stacked[:, i + 1]) for i in range(0, k - 1, 2)]
        byes = [stacked[:, k - 1]] if k % 2 else []
        return slots, byes

    def _const_slots(self, pairs: list[tuple[int, int]], S: int) -> list[tuple[np.ndarray, np.ndarray]]:
        return [(np.full(S, a, dtype=np.intp), np.full(S, b, dtype=np.intp)) for a, b in pairs]

    def _regional_bracket(self, orders: dict[str, np.ndarray], rng, S, cnt_reach, cnt_win) -> None:
        """
        The AFC shape: each region's top `direct_qualifiers` play a Round of 16
        within the region (1 v 8, 2 v 7 ... higher seed at home in the second
        leg); the quarter-finals pair one region's winners against the other's
        at random; from there the draw is open. Rounds in `neutral_rounds` are
        single matches with no home side.
        """
        cfg = self.cfg
        d = cfg.direct_qualifiers
        keys = [k for k, _ in cfg.rounds]
        legs = dict(cfg.rounds)
        region_of: dict[int, str] = {}
        for g, members in self.state.groups.items():
            for t in members:
                if t in self.team_idx:
                    region_of[self.team_idx[t]] = g
        regions = list(orders)

        first = keys[0]
        by_region: dict[str, list[np.ndarray]] = {g: [] for g in regions}
        known = self._known_slots(first, (d // 2) * len(regions))
        if known is not None:
            winners = self._play_round(first, self._const_slots(known, S), None, rng, cnt_reach, legs=legs[first])
            for (a, _b), w in zip(known, winners):
                by_region.setdefault(region_of.get(a, regions[0]), []).append(w)
        else:
            for g in regions:
                order = orders[g]
                n = min(d, order.shape[1])
                slots = [(order[:, n - 1 - i], order[:, i]) for i in range(n // 2)]
                by_region[g] = self._play_round(first, slots, None, rng, cnt_reach, legs=legs[first])

        rest = keys[1:]
        w: list[np.ndarray]
        counts = [len(by_region[g]) for g in regions]
        if len(regions) == 2 and counts[0] == counts[1] and counts[0] > 0 and rest:
            second = rest[0]
            known2 = self._known_slots(second, counts[0])
            if known2 is not None:
                slots = self._const_slots(known2, S)
            else:
                left = np.stack(by_region[regions[0]], 1)
                right = rng.permuted(np.stack(by_region[regions[1]], 1), axis=1)
                slots = [(left[:, i], right[:, i]) for i in range(left.shape[1])]
            neutral = second in cfg.neutral_rounds
            w = self._play_round(second, slots, None, rng, cnt_reach, legs=legs[second], neutral=neutral)
            rest = rest[1:]
        else:
            w = [x for g in regions for x in by_region[g]]
        for key in rest:
            if len(w) < 2:
                break
            neutral = key in cfg.neutral_rounds or (key == "final" and cfg.final_at_neutral_venue)
            known_k = self._known_slots(key, len(w) // 2)
            slots = self._const_slots(known_k, S) if known_k is not None else self._random_pairs(w, rng, S)[0]
            w = self._play_round(key, slots, None, rng, cnt_reach, legs=legs[key], neutral=neutral)
        if len(w) == 1:
            np.add.at(cnt_win, w[0], 1)

    def _knockout_bracket(self, rng, S, cnt_reach, cnt_win) -> None:
        """
        A straight knockout whose bracket comes from the store: each round's
        ties are the drawn pairs where the draw is known, else the previous
        round's survivors paired at random per simulation. When a round's draw is
        known its predecessor is complete, so survivors not drawn into it had a
        bye. Before the first draw there is nothing to simulate.
        """
        cfg = self.cfg
        legs = dict(cfg.rounds)
        survivors: list[np.ndarray] = []
        for key, _ in cfg.rounds:
            pairs = self.state.known_pairs.get(key) or []
            idx = [(self.team_idx.get(a), self.team_idx.get(b)) for a, b in pairs]
            idx = [pr for pr in idx if None not in pr]
            if idx:
                slots = self._const_slots(idx, S)
                drawn = {a for a, _ in idx} | {b for _, b in idx}
                byes = [s for s in survivors if int(s[0]) not in drawn and bool((s == s[0]).all())]
            elif len(survivors) >= 2:
                slots, byes = self._random_pairs(survivors, rng, S)
            else:
                continue
            neutral = key in cfg.neutral_rounds or (key == "final" and cfg.final_at_neutral_venue)
            winners = self._play_round(key, slots, None, rng, cnt_reach, legs=legs[key], neutral=neutral)
            survivors = winners + byes
        # An inconsistent store (a club drawn into a round it did not reach) can
        # leave more than one survivor after the last round; settle them at random
        # so every simulation still crowns exactly one club.
        while len(survivors) > 1:
            slots, byes = self._random_pairs(survivors, rng, S)
            survivors = [self._decide(a, b, rng, 1, neutral=True) for a, b in slots] + byes
        if len(survivors) == 1:
            np.add.at(cnt_win, survivors[0], 1)

    def _fixed_bracket(self, rng, S, cnt_reach, cnt_win) -> None:
        winners: dict[str, np.ndarray] = {}

        def resolve(source: str) -> np.ndarray:
            if source.startswith("winner:"):
                return winners[source.split(":", 1)[1]]
            if source.startswith("champion:"):
                slug = source.split(":", 1)[1]
                dist = self.external.get(slug) or {}
                names = [t for t in dist if t in self.team_idx]
                if not names:
                    return np.full(S, self.team_idx.get(AVERAGE, 0), dtype=np.intp)
                p = np.array([dist[t] for t in names], dtype=np.float64)
                p = p / p.sum()
                idx = np.array([self.team_idx[t] for t in names], dtype=np.intp)
                return idx[rng.choice(len(idx), size=S, p=p)]
            return np.full(S, self.team_idx[source], dtype=np.intp)

        last = None
        for tie in self.cfg.ties:
            home, away = resolve(tie.home.source), resolve(tie.away.source)
            np.add.at(cnt_reach[tie.key], np.concatenate([home, away]), 1)
            winners[tie.key] = self._decide(home, away, rng, 1, neutral=tie.neutral)
            last = winners[tie.key]
        if last is not None:
            np.add.at(cnt_win, last, 1)

    # ── assembly ─────────────────────────────────────────────────────────────

    def _assemble(self, n, runtime, cnt_pos, cnt_gpos, cnt_reach, cnt_win, sum_pts, sum_goals, pts_samples) -> CupResults:
        cfg = self.cfg
        res = CupResults(n_sims=n, runtime_s=runtime, teams=list(self.state.teams))
        samples = np.concatenate(pts_samples, axis=0) if pts_samples else None
        for team, i in self.team_idx.items():
            res.p_position[team] = (cnt_pos[i] / n).tolist() if cfg.kind == "swiss" else []
            if cnt_gpos is not None:
                res.p_group_position[team] = (cnt_gpos[i] / n).tolist()
            res.expected_points[team] = float(sum_pts[i] / n)
            res.team_goals_mean[team] = float(sum_goals[i] / n)
            res.p_reach[team] = {r: float(cnt_reach[r][i] / n) for r in cfg.round_keys}
            res.p_win[team] = float(cnt_win[i] / n)
            if samples is not None:
                q = np.quantile(samples[:, i], [0.05, 0.50, 0.95])
                res.points_quantiles[team] = (float(q[0]), float(q[1]), float(q[2]))
        source = res.p_group_position if cfg.kind in ("groups", "regional_swiss") else res.p_position
        for band in cfg.bands:
            res.p_band[band.key] = {t: float(sum(dist[band.first - 1: band.last])) for t, dist in source.items() if dist}
        return res
