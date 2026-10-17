"""
Monte Carlo season simulator for plain leagues, and for MLS.

Vectorized over the simulation axis, as the Argentine simulator is: every
simulation advances together as a (n_sims, n_teams) array, so a season costs one
vector operation per fixture rather than one per fixture per simulation. Ranking is
a lexsort over the league's tiebreak keys, which is what makes that possible —
head-to-head clustering (La Liga, Serie A) cannot be vectorised and is approximated
by goal difference. The approximation only bites on exact ties and is declared on
the methodology tab.

One pass yields everything. For a plain league the finishing-position distribution
is the whole story: the title, every continental band and relegation are ranges of
it. MLS adds a conference ranking and a re-seeded playoff, which is simulated
inside the same pass because MLS Cup depends on who finishes where.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from oddsmarkets.football.competitions.league.config import (
    LIGUILLA_ROUNDS,
    LeagueConfig,
    MLS_ROUNDS,
)
from oddsmarkets.football.competitions.league.season_state import LeagueState
from oddsmarkets.football.core.simulation import (
    PairSampler,
    ScoreSampler,
    advance_matrix,
    count_positions,
    rank_table,
    two_leg_advance_matrix,
)

logger = logging.getLogger(__name__)


@dataclass
class LeagueResults:
    """Probabilities from one run. Every dict is keyed by team name."""

    n_sims: int
    runtime_s: float
    teams: list[str] = field(default_factory=list)

    # The table
    p_position: dict[str, list[float]] = field(default_factory=dict)   # index 0 = 1st
    p_title: dict[str, float] = field(default_factory=dict)
    expected_points: dict[str, float] = field(default_factory=dict)
    points_quantiles: dict[str, tuple[float, float, float]] = field(default_factory=dict)
    # band key -> team -> probability of finishing inside it
    p_band: dict[str, dict[str, float]] = field(default_factory=dict)
    # Simulated league goals per club, for the top-scorer model
    team_goals_mean: dict[str, float] = field(default_factory=dict)

    # Conferences and playoffs (empty for a plain league)
    p_conf_position: dict[str, list[float]] = field(default_factory=dict)
    # Belgian split: the post-split order (1-6 championship group, then the
    # European group, then the relegation group).
    p_final_position: dict[str, list[float]] = field(default_factory=dict)
    p_playoffs: dict[str, float] = field(default_factory=dict)
    p_reach: dict[str, dict[str, float]] = field(default_factory=dict)  # team -> round -> p
    p_cup: dict[str, float] = field(default_factory=dict)

    def p_in_band(self, key: str, team: str) -> float:
        return self.p_band.get(key, {}).get(team, 0.0)


class LeagueSimulator:
    """
    Simulates the remainder of a league season.

    `model` needs a `.predict(home, away, neutral=...) -> MatchProbabilities` method
    exposing a `.score_matrix`; both EnsembleModel and DixonColesModel qualify.
    """

    def __init__(
        self,
        model,
        state: LeagueState,
        cfg: LeagueConfig | None = None,
        n_sims: int | None = None,
        seed: int | None = None,
        chunk: int | None = None,
        boot_model=None,
    ) -> None:
        self.model = model
        self.state = state
        self.boot_model = boot_model
        self.cfg = cfg or state.cfg
        self.n_sims = n_sims if n_sims is not None else self.cfg.n_sims
        self.seed = seed if seed is not None else self.cfg.random_seed
        self.chunk = chunk if chunk is not None else self.cfg.sim_chunk

        self.teams = list(state.teams)
        self.n_teams = len(self.teams)
        self.team_idx = {t: i for i, t in enumerate(self.teams)}
        self.sampler = ScoreSampler(model, self.teams, max_goals=self.cfg.max_goals)
        self._p_adv: np.ndarray | None = None
        self._p_adv2: np.ndarray | None = None
        # forced[h, a] is the index of the club known to have won the playoff tie
        # between h and a, or -1. Symmetric, so it does not matter who hosted.
        self._forced = np.full((self.n_teams, self.n_teams), -1, dtype=np.intp)
        for pair, winner in (state.playoff_results or {}).items():
            idx = [self.team_idx.get(t) for t in pair]
            w = self.team_idx.get(winner)
            if len(idx) == 2 and None not in idx and w is not None:
                self._forced[idx[0], idx[1]] = w
                self._forced[idx[1], idx[0]] = w

    def _decide(self, host: np.ndarray, guest: np.ndarray, rng: np.random.Generator,
                p_host: np.ndarray | None = None) -> np.ndarray:
        """
        Winner of a single-match tie per simulation, forcing ties already played.

        `p_host` defaults to the advance matrix for the pairing; a best-of-three
        passes its series probability instead.
        """
        if p_host is None:
            p_host = self._p_adv[host, guest]
        winners = np.where(rng.random(host.shape) < p_host, host, guest)
        known = self._forced[host, guest]
        return np.where(known >= 0, known, winners)

    # ── main entry point ─────────────────────────────────────────────────────

    def run(self) -> LeagueResults:
        start = time.perf_counter()
        cfg, state = self.cfg, self.state
        n, T = self.n_sims, self.n_teams
        if T == 0:
            raise ValueError("No teams to simulate")
        rng = np.random.default_rng(self.seed)

        # Seed from results already on the board.
        records = state.records()
        seed_pts = np.zeros(T, dtype=np.int32)
        seed_gf = np.zeros(T, dtype=np.int32)
        seed_ga = np.zeros(T, dtype=np.int32)
        seed_w = np.zeros(T, dtype=np.int32)
        for team, rec in records.items():
            i = self.team_idx.get(team)
            if i is not None:
                seed_pts[i], seed_gf[i], seed_ga[i], seed_w[i] = rec.points, rec.gf, rec.ga, rec.won

        fixtures = [
            (self.team_idx[m.home_team], self.team_idx[m.away_team])
            for m in state.remaining
            if not m.is_playoff and m.home_team in self.team_idx and m.away_team in self.team_idx
        ]
        logger.info("Simulating %s: %d fixtures remaining, %d sims", cfg.slug, len(fixtures), n)

        conf_cols: dict[str, np.ndarray] = {}
        if cfg.conferences:
            for conf in cfg.conferences:
                members = state.conferences.get(conf, [])
                conf_cols[conf] = np.array(
                    [self.team_idx[t] for t in members if t in self.team_idx], dtype=np.intp
                )
            if cfg.playoff and all(c.size >= cfg.playoff.qualifiers_per_conference for c in conf_cols.values()):
                self._p_adv = advance_matrix(
                    self.model, self.teams, cfg.extra_time_weight, cfg.max_goals
                )
            elif cfg.playoff:
                logger.warning("%s: conferences too small for the playoff format — skipping playoffs", cfg.slug)
        liguilla = cfg.playoff is not None and cfg.playoff.kind == "liguilla" and T >= cfg.playoff.qualifiers
        if liguilla:
            self._p_adv = advance_matrix(self.model, self.teams, cfg.extra_time_weight, cfg.max_goals)
            # A level aggregate favours the higher seed in the Liguilla, which is
            # extra_time_weight=1 with the seed's share; approximated by giving the
            # drawn mass entirely to the strength share.
            self._p_adv2 = two_leg_advance_matrix(self.model, self.teams, 1.0, cfg.max_goals)
        pair_sampler = PairSampler(self.sampler) if cfg.split else None

        # Accumulators
        cnt_pos = np.zeros((T, T), dtype=np.int64)
        cnt_title = np.zeros(T, dtype=np.int64)
        sum_pts = np.zeros(T, dtype=np.float64)
        sum_goals = np.zeros(T, dtype=np.float64)
        pts_samples: list[np.ndarray] = []
        n_conf = cfg.teams_per_conference if cfg.conferences else 0
        cnt_conf_pos = np.zeros((T, n_conf), dtype=np.int64) if cfg.conferences else None
        cnt_playoffs = np.zeros(T, dtype=np.int64)
        rounds = LIGUILLA_ROUNDS if liguilla else MLS_ROUNDS
        cnt_reach = {r: np.zeros(T, dtype=np.int64) for r in rounds}
        cnt_cup = np.zeros(T, dtype=np.int64)
        cnt_final = np.zeros((T, T), dtype=np.int64) if cfg.split else None
        cnt_split_title = np.zeros(T, dtype=np.int64)

        done = 0
        while done < n:
            S = min(self.chunk, n - done)
            pts = np.tile(seed_pts, (S, 1)).astype(np.int32)
            gf = np.tile(seed_gf, (S, 1)).astype(np.int32)
            ga = np.tile(seed_ga, (S, 1)).astype(np.int32)
            w = np.tile(seed_w, (S, 1)).astype(np.int32)
            goals = np.zeros((S, T), dtype=np.int32)

            # ── league phase ────────────────────────────────────────────────
            for h, a in fixtures:
                hg, ag = self.sampler.sample(h, a, rng, S)
                home_win = hg > ag
                draw = hg == ag
                away_win = ag > hg
                pts[:, h] += cfg.points_win * home_win + cfg.points_draw * draw
                pts[:, a] += cfg.points_win * away_win + cfg.points_draw * draw
                w[:, h] += home_win
                w[:, a] += away_win
                gf[:, h] += hg
                ga[:, h] += ag
                gf[:, a] += ag
                ga[:, a] += hg
                goals[:, h] += hg
                goals[:, a] += ag
            gd = gf - ga

            # ── ranking ─────────────────────────────────────────────────────
            by_name = {"pts": pts, "gd": gd, "gf": gf, "w": w}
            keys = [by_name[k] for k in cfg.tiebreak]
            order, _rank = rank_table(keys, rng)
            cnt_pos += count_positions(order, T)
            np.add.at(cnt_title, order[:, 0], 1)

            # ── Liga MX: play-in and the two-legged Liguilla ────────────────
            if liguilla:
                self._liguilla(order, rng, cnt_playoffs, cnt_reach, cnt_cup)

            # ── Belgium: the split, with halved points ──────────────────────
            if cfg.split:
                final_order = self._split(order, pts, gd, gf, pair_sampler, rng, goals)
                np.add.at(cnt_final, (final_order, np.broadcast_to(np.arange(T), final_order.shape)), 1)
                # The champion is first after the split, not first before it.
                np.add.at(cnt_split_title, final_order[:, 0], 1)

            # ── conferences and playoffs ────────────────────────────────────
            if cfg.conferences:
                seeds: dict[str, np.ndarray] = {}
                for conf, cols in conf_cols.items():
                    if cols.size == 0:
                        continue
                    sub = [k[:, cols] for k in keys]
                    c_order, _ = rank_table(sub, rng)
                    teams_in_pos = cols[c_order]                       # (S, n_c)
                    np.add.at(
                        cnt_conf_pos,
                        (teams_in_pos, np.broadcast_to(np.arange(cols.size), teams_in_pos.shape)),
                        1,
                    )
                    if self._p_adv is not None:
                        seeds[conf] = teams_in_pos[:, : cfg.playoff.qualifiers_per_conference]
                if self._p_adv is not None and len(seeds) == len(cfg.conferences):
                    self._playoffs(seeds, pts, gd, rng, cnt_playoffs, cnt_reach, cnt_cup)

            if self.boot_model is not None:
                self.boot_model.accumulate_batch(goals, self.teams)

            sum_pts += pts.sum(axis=0)
            sum_goals += goals.sum(axis=0)
            if len(pts_samples) * self.chunk < 5000:
                pts_samples.append(pts[: min(S, 2000)].copy())
            done += S

        runtime = time.perf_counter() - start
        logger.info("Simulated %d seasons in %.1fs", n, runtime)
        return self._assemble(
            n, runtime, cnt_pos, cnt_split_title if cfg.split else cnt_title, sum_pts, sum_goals, pts_samples,
            cnt_conf_pos, cnt_playoffs, cnt_reach, cnt_cup, cnt_final, rounds,
        )

    # ── MLS Cup playoffs ─────────────────────────────────────────────────────

    def _playoffs(self, seeds, pts, gd, rng, cnt_playoffs, cnt_reach, cnt_cup) -> None:
        """
        Re-seeded conference brackets and MLS Cup, vectorized over simulations.

        Wildcard (8 hosts 9) → Round One best-of-three (1 v wildcard, 2 v 7, 3 v 6,
        4 v 5; the higher seed hosts games one and three) → winners re-seeded so
        the best remaining seed meets the worst → single-match semi-finals and
        final hosted by the higher seed → MLS Cup hosted by the champion with the
        better regular season.
        """
        P = self._p_adv
        S = pts.shape[0]
        rows = np.arange(S)
        champs: list[tuple[np.ndarray, np.ndarray]] = []

        for conf, s in seeds.items():
            np.add.at(cnt_playoffs, s.ravel(), 1)

            # Wildcard: seed 8 hosts seed 9. A single match with no draw.
            s8, s9 = s[:, 7], s[:, 8]
            np.add.at(cnt_reach["wc"], np.concatenate([s8, s9]), 1)
            w89 = self._decide(s8, s9, rng)
            seed89 = np.where(w89 == s8, 8, 9)

            # Round One, best of three. p_h: the higher seed wins at home; p_a: it
            # wins away. It takes the series by winning games 1 and 2, or 1 and 3,
            # or 2 and 3.
            hi = s[:, :4]
            lo = np.stack([w89, s[:, 6], s[:, 5], s[:, 4]], axis=1)
            hi_seed = np.broadcast_to(np.arange(1, 5), (S, 4))
            lo_seed = np.stack([seed89, np.full(S, 7), np.full(S, 6), np.full(S, 5)], axis=1)
            np.add.at(cnt_reach["r1"], np.concatenate([hi.ravel(), lo.ravel()]), 1)
            p_h = P[hi, lo]
            p_a = 1.0 - P[lo, hi]
            p_series = p_h * p_a + p_h * (1 - p_a) * p_h + (1 - p_h) * p_a * p_h
            win = self._decide(hi, lo, rng, p_host=p_series)
            hi_wins = win == hi
            win_seed = np.where(hi_wins, hi_seed, lo_seed)
            np.add.at(cnt_reach["csf"], win.ravel(), 1)

            # Re-seed: best remaining meets worst remaining.
            o = np.argsort(win_seed, axis=1)
            wt = np.take_along_axis(win, o, axis=1)
            ws = np.take_along_axis(win_seed, o, axis=1)
            f1 = self._decide(wt[:, 0], wt[:, 3], rng)
            f1s = np.where(f1 == wt[:, 0], ws[:, 0], ws[:, 3])
            f2 = self._decide(wt[:, 1], wt[:, 2], rng)
            f2s = np.where(f2 == wt[:, 1], ws[:, 1], ws[:, 2])
            np.add.at(cnt_reach["cf"], np.concatenate([f1, f2]), 1)

            # Conference final: the better seed hosts.
            f1_hosts = f1s <= f2s
            host = np.where(f1_hosts, f1, f2)
            guest = np.where(f1_hosts, f2, f1)
            champ = self._decide(host, guest, rng)
            np.add.at(cnt_reach["final"], champ, 1)
            champs.append((champ, pts[rows, champ] * 1000 + gd[rows, champ] + rng.random(S)))

        if len(champs) != 2:
            return
        (a, a_key), (b, b_key) = champs
        a_hosts = a_key >= b_key
        host = np.where(a_hosts, a, b)
        guest = np.where(a_hosts, b, a)
        cup = self._decide(host, guest, rng)
        np.add.at(cnt_cup, cup, 1)

    # ── Liga MX Liguilla ─────────────────────────────────────────────────────

    def _decide2(self, host2: np.ndarray, other: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        """Winner of a two-legged tie with `host2` at home in the second leg; decided ties forced."""
        p_host = 1.0 - self._p_adv2[other, host2]
        winners = np.where(rng.random(host2.shape) < p_host, host2, other)
        known = self._forced[host2, other]
        return np.where(known >= 0, known, winners)

    def _liguilla(self, order, rng, cnt_playoffs, cnt_reach, cnt_cup) -> None:
        """
        Play-in: 7 hosts 8 and 9 hosts 10; the 7v8 winner is seed 7, its loser
        hosts the 9v10 winner for seed 8. Quarter-finals 1v8, 2v7, 3v6, 4v5, then
        semi-finals and the final, all two-legged with the higher seed at home in
        the second leg and re-seeding after each round.
        """
        po = self.cfg.playoff
        S = order.shape[0]
        rows = np.arange(S)
        seeds_of = np.zeros((S, self.n_teams), dtype=np.int32)
        np.put_along_axis(seeds_of, order, np.broadcast_to(np.arange(1, self.n_teams + 1), order.shape), axis=1)
        q = order[:, : po.qualifiers]
        np.add.at(cnt_playoffs, q.ravel(), 1)

        s7, s8, s9, s10 = (order[:, k - 1] for k in po.play_in)
        np.add.at(cnt_reach["play_in"], np.concatenate([s7, s8, s9, s10]), 1)
        w78 = self._decide(s7, s8, rng)
        l78 = np.where(w78 == s7, s8, s7)
        w910 = self._decide(s9, s10, rng)
        seed8 = self._decide(l78, w910, rng)

        hi = [order[:, k] for k in range(po.direct)]                  # seeds 1..6
        ties = [(hi[0], seed8), (hi[1], w78), (hi[2], hi[5]), (hi[3], hi[4])]
        winners = []
        for host2, other in ties:
            np.add.at(cnt_reach["qf"], np.concatenate([host2, other]), 1)
            winners.append(self._decide2(host2, other, rng))
        for key in ("sf", "final"):
            win = np.stack(winners, 1)
            seed = seeds_of[rows[:, None], win]
            o = np.argsort(seed, axis=1)
            win = np.take_along_axis(win, o, axis=1)
            nxt = []
            for i in range(win.shape[1] // 2):
                host2, other = win[:, i], win[:, win.shape[1] - 1 - i]
                np.add.at(cnt_reach[key], np.concatenate([host2, other]), 1)
                nxt.append(self._decide2(host2, other, rng))
            winners = nxt
        np.add.at(cnt_cup, winners[0], 1)

    # ── Belgian split ────────────────────────────────────────────────────────

    def _split(self, order, pts, gd, gf, pair_sampler, rng, goals) -> np.ndarray:
        """
        Divide the table into the configured groups, halve the points (rounded
        up), play a double round-robin within each group with the clubs drawn per
        simulation, and return the final order: championship group first.
        """
        sp = self.cfg.split
        S, T = pts.shape
        rows = np.arange(S)
        sizes = (sp.top, sp.europe, sp.relegation)
        final_cols = []
        start = 0
        for size in sizes:
            members = order[:, start:start + size]                    # (S, size) team indices
            start += size
            base = pts[rows[:, None], members]
            g_pts = (np.ceil(base / 2.0).astype(np.int32) if sp.halve_points else base.copy())
            g_gd = gd[rows[:, None], members].copy()
            g_gf = gf[rows[:, None], members].copy()
            for i in range(size):
                for j in range(size):
                    if i == j:
                        continue
                    hg, ag = pair_sampler.sample(members[:, i], members[:, j], rng)
                    g_pts[:, i] += 3 * (hg > ag) + (hg == ag)
                    g_pts[:, j] += 3 * (ag > hg) + (hg == ag)
                    g_gd[:, i] += hg - ag
                    g_gd[:, j] += ag - hg
                    g_gf[:, i] += hg
                    g_gf[:, j] += ag
                    goals[rows, members[:, i]] += hg
                    goals[rows, members[:, j]] += ag
            o, _ = rank_table([g_pts, g_gd, g_gf], rng)
            final_cols.append(np.take_along_axis(members, o, axis=1))
        return np.concatenate(final_cols, axis=1)

    # ── assembly ─────────────────────────────────────────────────────────────

    def _assemble(
        self, n, runtime, cnt_pos, cnt_title, sum_pts, sum_goals, pts_samples,
        cnt_conf_pos, cnt_playoffs, cnt_reach, cnt_cup, cnt_final=None, rounds=MLS_ROUNDS,
    ) -> LeagueResults:
        cfg = self.cfg
        res = LeagueResults(n_sims=n, runtime_s=runtime, teams=list(self.teams))
        samples = np.concatenate(pts_samples, axis=0) if pts_samples else None
        has_playoffs = self._p_adv is not None

        for team, i in self.team_idx.items():
            res.p_position[team] = (cnt_pos[i] / n).tolist()
            res.p_title[team] = float(cnt_title[i] / n)
            res.expected_points[team] = float(sum_pts[i] / n)
            res.team_goals_mean[team] = float(sum_goals[i] / n)
            if samples is not None:
                q = np.quantile(samples[:, i], [0.05, 0.50, 0.95])
                res.points_quantiles[team] = (float(q[0]), float(q[1]), float(q[2]))
            if cnt_conf_pos is not None:
                res.p_conf_position[team] = (cnt_conf_pos[i] / n).tolist()
            if has_playoffs:
                res.p_playoffs[team] = float(cnt_playoffs[i] / n)
                res.p_reach[team] = {r: float(cnt_reach[r][i] / n) for r in rounds}
                res.p_cup[team] = float(cnt_cup[i] / n)
            if cnt_final is not None:
                res.p_final_position[team] = (cnt_final[i] / n).tolist()

        # Bands are ranges of the position distribution — the conference one where
        # the league has conferences, the post-split order in Belgium, since that
        # is the table the rules read.
        source = res.p_conf_position if cfg.conferences else (res.p_final_position if cfg.split else res.p_position)
        for band in cfg.bands:
            res.p_band[band.key] = {
                team: float(sum(dist[band.first - 1: band.last]))
                for team, dist in source.items()
            }
        return res
