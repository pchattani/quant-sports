"""
Monte Carlo season simulator for the Argentine Liga Profesional.

Vectorized over the simulation axis. This is a prerequisite rather than an
optimisation: the World Cup simulator draws one `rng.choice` per match, which is fine
at 104 matches per simulation but not at a league's ~255, where 100k simulations would
run for hours. Here every simulation advances together as a (n_sims, n_teams) array,
so a full season costs one vector operation per fixture rather than one per fixture
per simulation.

Vectorizing is possible because Argentine tiebreakers are points, then goal difference,
then goals for, then drawn lots — with no head-to-head clustering. Ranking is therefore
a pure lexsort. The World Cup's head-to-head mini-table logic is what forces its
per-simulation Python loop, and dropping it is what makes this tractable.

One pass yields every output. Zone position, top-8 qualification, playoff round reached,
the Clausura title, the Tabla Anual and its Campeon de Liga, continental berths and both
relegation routes are all functions of the same arrays, so computing them separately
would mean simulating the season several times over. Continental berths in particular
*must* be computed inside the simulation: they depend on who wins the tournament, so
they cannot be recovered from marginal probabilities afterwards.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from oddsmarkets.football.competitions.liga.config import (
    DEFAULT_CONFIG,
    PLAYOFF_PAIRINGS,
    PLAYOFF_ROUNDS,
    LigaConfig,
    ZONES,
)
from oddsmarkets.football.competitions.liga.season_state import SeasonState
from oddsmarkets.football.core.simulation import ScoreSampler, advance_matrix

logger = logging.getLogger(__name__)


@dataclass
class LigaResults:
    """Probabilities from one simulation run. All dicts are keyed by team name."""

    n_sims: int
    runtime_s: float
    teams: list[str] = field(default_factory=list)

    # Zone phase
    p_zone_position: dict[str, list[float]] = field(default_factory=dict)  # index 0 = 1st
    p_top8: dict[str, float] = field(default_factory=dict)
    p_zone_win: dict[str, float] = field(default_factory=dict)
    expected_points: dict[str, float] = field(default_factory=dict)

    # Playoffs
    p_reach: dict[str, dict[str, float]] = field(default_factory=dict)   # team -> round -> p
    p_title: dict[str, float] = field(default_factory=dict)

    # Tabla Anual
    p_anual_position: dict[str, list[float]] = field(default_factory=dict)
    p_anual_champion: dict[str, float] = field(default_factory=dict)
    expected_anual_points: dict[str, float] = field(default_factory=dict)

    # Continental berths
    p_libertadores: dict[str, float] = field(default_factory=dict)
    p_sudamericana: dict[str, float] = field(default_factory=dict)

    # Relegation — reported by route, because the two have very different narratives
    p_relegation_promedio: dict[str, float] = field(default_factory=dict)
    p_relegation_anual: dict[str, float] = field(default_factory=dict)
    p_relegation_any: dict[str, float] = field(default_factory=dict)
    promedio_quantiles: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    # Simulated league goals per club, for the top-scorer model
    team_goals_mean: dict[str, float] = field(default_factory=dict)

    # The stakes of the next fixtures (league/simulator.py's shape): the same seasons split by each result,
    # [{id, home, away, date, n: [H, D, A], title, bands: {key: [p|H, p|D, p|A] per team}}]
    stakes: list[dict] = field(default_factory=list)
    # Copa Argentina winners the berths were drawn from (club -> share of simulations), when given
    copa_winner_share: dict[str, float] = field(default_factory=dict)


# The races the stakes split on, beside "title" (the top of the Tabla Anual).
STAKE_KEYS = ("libertadores", "sudamericana", "relegation", "top8")


class LigaSimulator:
    """
    Simulates the remainder of a Liga Profesional season.

    `model` needs a `.predict(home, away, neutral=...) -> MatchProbabilities` method
    exposing a `.score_matrix`; both EnsembleModel and DixonColesModel qualify.
    """

    def __init__(
        self,
        model,
        state: SeasonState,
        cfg: LigaConfig | None = None,
        n_sims: int | None = None,
        seed: int | None = None,
        chunk: int | None = None,
        boot_model=None,
        copa_dist: dict[str, float] | None = None,
        stake_days: float = 7.0,
        stake_max: int = 15,
    ) -> None:
        self.model = model
        self.state = state
        # The Copa Argentina's winner takes a Libertadores place ahead of the Tabla Anual. Until it is known
        # (cfg.copa_argentina_winner, or a final already played) it is drawn per simulation from the cup's
        # own simulated winners (build_site_all's cup build); clubs outside the league take no league place.
        self.copa_dist = {t: float(p) for t, p in (copa_dist or {}).items() if p and p > 0}
        self.stake_days = stake_days
        self.stake_max = stake_max
        # Optional top-scorer model, fed the league-phase goals of every simulation.
        # The World Cup wiring calls GoldenBootModel.allocate() only from knockout
        # matches, so it sees 8 of 104 games; here that would hide ~240 of ~255.
        self.boot_model = boot_model
        self.cfg = cfg or state.cfg or DEFAULT_CONFIG
        self.n_sims = n_sims if n_sims is not None else self.cfg.n_sims
        self.seed = seed if seed is not None else self.cfg.random_seed
        self.chunk = chunk if chunk is not None else self.cfg.sim_chunk

        self.teams = state.teams
        self.n_teams = len(self.teams)
        self.team_idx = {t: i for i, t in enumerate(self.teams)}

        self._sampler = ScoreSampler(model, self.teams, max_goals=self.cfg.max_goals)
        self._p_advance: np.ndarray | None = None

    # ── precomputation ───────────────────────────────────────────────────────
    # Both primitives live in core/simulation.py and are shared with the league
    # simulator; these names are kept so the run loop reads as before.

    def _score_cdf(self, home: int, away: int, neutral: bool) -> np.ndarray:
        """Flattened cumulative score distribution for one ordered pairing (cached)."""
        return self._sampler.cdf(home, away, neutral)

    def _precompute_advance(self) -> np.ndarray:
        """P(home side advances) for every ordered pairing in a single-leg tie."""
        return advance_matrix(self.model, self.teams, self.cfg.extra_time_weight, self.cfg.max_goals)

    # ── main entry point ─────────────────────────────────────────────────────

    def run(self) -> LigaResults:
        start = time.perf_counter()
        torneo = self.state.live_torneo()
        if torneo is None:
            raise ValueError("Season is complete — nothing left to simulate")

        rng = np.random.default_rng(self.seed)
        n, T = self.n_sims, self.n_teams
        cfg = self.cfg

        zone_cols = {
            z: np.array([self.team_idx[t] for t in torneo.zones.get(z, [])], dtype=np.intp)
            for z in ZONES
        }
        n_qual = cfg.qualifiers_per_zone

        # Seed from results already on the board.
        records = torneo.records()
        seed_pts = np.zeros(T, dtype=np.int32)
        seed_gf = np.zeros(T, dtype=np.int32)
        seed_ga = np.zeros(T, dtype=np.int32)
        for team, rec in records.items():
            i = self.team_idx.get(team)
            if i is not None:
                seed_pts[i], seed_gf[i], seed_ga[i] = rec.points, rec.gf, rec.ga

        league_left = [
            m for m in torneo.remaining
            if not m.is_playoff
            and m.home_team in self.team_idx
            and m.away_team in self.team_idx
        ]
        fixtures = [(self.team_idx[m.home_team], self.team_idx[m.away_team]) for m in league_left]
        stake_at = self._stake_fixtures(league_left)
        K = len(stake_at)
        cnt_out = np.zeros((K, 3), dtype=np.int64)
        cnt_st = {key: np.zeros((K, 3, T), dtype=np.int64) for key in ("title",) + STAKE_KEYS}
        logger.info(
            "Simulating %s: %d fixtures remaining, %d sims",
            torneo.key, len(fixtures), n,
        )

        # Tabla Anual contribution from completed tournaments — constants.
        anual_base_pts = np.zeros(T, dtype=np.int32)
        anual_base_gf = np.zeros(T, dtype=np.int32)
        anual_base_ga = np.zeros(T, dtype=np.int32)
        anual_base_mp = np.zeros(T, dtype=np.int32)
        for team, rec in self.state.anual_base().items():
            i = self.team_idx.get(team)
            if i is not None:
                anual_base_pts[i] = rec.points
                anual_base_gf[i] = rec.gf
                anual_base_ga[i] = rec.ga
                anual_base_mp[i] = rec.played

        prior_pts = np.zeros(T, dtype=np.float64)
        prior_mp = np.zeros(T, dtype=np.float64)
        for team, (pts, mp) in self.state.promedios_prior.items():
            i = self.team_idx.get(team)
            if i is not None:
                prior_pts[i], prior_mp[i] = pts, mp

        # Matches each club will have played by season's end. Constant across
        # simulations — only the points vary — so compute it once.
        played_now = np.zeros(T, dtype=np.int32)
        for team, rec in records.items():
            i = self.team_idx.get(team)
            if i is not None:
                played_now[i] = rec.played
        per_team_remaining = np.zeros(T, dtype=np.int32)
        for h, a in fixtures:
            per_team_remaining[h] += 1
            per_team_remaining[a] += 1
        season_mp = (anual_base_mp + played_now + per_team_remaining).astype(np.float64)

        self._p_advance = self._precompute_advance()

        # Accumulators
        cnt_zone_pos = np.zeros((T, cfg.teams_per_zone), dtype=np.int64)
        cnt_top8 = np.zeros(T, dtype=np.int64)
        cnt_reach = {r: np.zeros(T, dtype=np.int64) for r in PLAYOFF_ROUNDS}
        cnt_title = np.zeros(T, dtype=np.int64)
        cnt_anual_pos = np.zeros((T, T), dtype=np.int64)
        cnt_anual_champ = np.zeros(T, dtype=np.int64)
        cnt_lib = np.zeros(T, dtype=np.int64)
        cnt_sud = np.zeros(T, dtype=np.int64)
        cnt_rel_prom = np.zeros(T, dtype=np.int64)
        cnt_rel_anual = np.zeros(T, dtype=np.int64)
        cnt_rel_any = np.zeros(T, dtype=np.int64)
        sum_pts = np.zeros(T, dtype=np.float64)
        sum_anual_pts = np.zeros(T, dtype=np.float64)
        sum_goals = np.zeros(T, dtype=np.float64)
        promedio_samples: list[np.ndarray] = []

        apertura_champ_idx = self.team_idx.get(self.state.apertura.champion or "")
        copa_idx = self.team_idx.get(cfg.copa_argentina_winner or "")
        copa_p = None
        if copa_idx is None and self.copa_dist:
            total = sum(self.copa_dist.values())
            copa_p = np.zeros(T + 1, dtype=np.float64)          # the last slot: a club outside the league
            for team, p in self.copa_dist.items():
                i = self.team_idx.get(team)
                copa_p[i if i is not None else T] += p / total
            copa_p = np.clip(copa_p, 0.0, None)
            copa_p /= copa_p.sum()
        cnt_copa = np.zeros(T + 1, dtype=np.int64)

        done = 0
        while done < n:
            S = min(self.chunk, n - done)

            pts = np.tile(seed_pts, (S, 1)).astype(np.int32)
            gf = np.tile(seed_gf, (S, 1)).astype(np.int32)
            ga = np.tile(seed_ga, (S, 1)).astype(np.int32)
            goals = np.zeros((S, T), dtype=np.int32)
            outcome = np.zeros((S, K), dtype=np.int8) if K else None

            # ── league phase ────────────────────────────────────────────────
            k = cfg.max_goals + 1
            for j, (h, a) in enumerate(fixtures):
                cdf = self._score_cdf(h, a, neutral=False)
                idx = np.searchsorted(cdf, rng.random(S), side="right")
                np.clip(idx, 0, cdf.size - 1, out=idx)
                hg, ag = np.divmod(idx, k)
                hg = hg.astype(np.int32)
                ag = ag.astype(np.int32)

                home_win = hg > ag
                draw = hg == ag
                away_win = ag > hg
                if K and j in stake_at:
                    outcome[:, stake_at[j]] = np.where(home_win, 0, np.where(draw, 1, 2))
                pts[:, h] += cfg.points_win * home_win + cfg.points_draw * draw
                pts[:, a] += cfg.points_win * away_win + cfg.points_draw * draw
                gf[:, h] += hg
                ga[:, h] += ag
                gf[:, a] += ag
                ga[:, a] += hg
                goals[:, h] += hg
                goals[:, a] += ag

            gd = gf - ga

            # ── zone ranking ────────────────────────────────────────────────
            # Random jitter is the honest representation of the "sorteo" tiebreak.
            # Sorting alphabetically instead would hand a systematic edge to clubs
            # early in the alphabet.
            qualifiers: dict[str, np.ndarray] = {}
            for zone in ZONES:
                cols = zone_cols[zone]
                if cols.size == 0:
                    continue
                jitter = rng.random((S, cols.size))
                order = np.lexsort(
                    (jitter, gf[:, cols], gd[:, cols], pts[:, cols]), axis=-1
                )[:, ::-1]
                rank = np.empty_like(order)
                np.put_along_axis(
                    rank, order, np.broadcast_to(np.arange(cols.size), order.shape), axis=-1
                )
                np.add.at(cnt_zone_pos, (cols[None, :], rank), 1)
                top = cols[order[:, :n_qual]]
                qualifiers[zone] = top
                np.add.at(cnt_top8, top.ravel(), 1)

            # ── build the bracket ───────────────────────────────────────────
            slots = np.empty((S, len(PLAYOFF_PAIRINGS) * 2), dtype=np.intp)
            seeds = np.empty((S, len(PLAYOFF_PAIRINGS) * 2), dtype=np.int32)
            for pos, (left, right) in enumerate(PLAYOFF_PAIRINGS):
                for offset, label in ((0, left), (1, right)):
                    zone = cfg.zone_of_seed(label)
                    rank = cfg.rank_of_seed(label) - 1
                    slots[:, pos * 2 + offset] = qualifiers[zone][:, rank]
                    seeds[:, pos * 2 + offset] = rank

            np.add.at(cnt_reach["r16"], slots.ravel(), 1)

            # ── play the bracket ────────────────────────────────────────────
            known = torneo.playoff_results
            for r_i, round_name in enumerate(PLAYOFF_ROUNDS):
                a_slot, b_slot = slots[:, 0::2], slots[:, 1::2]
                a_seed, b_seed = seeds[:, 0::2], seeds[:, 1::2]

                # Better seed (lower number) hosts. The final is neutral.
                neutral_round = round_name == "final" and cfg.final_at_neutral_venue
                swap = b_seed < a_seed
                host = np.where(swap, b_slot, a_slot)
                guest = np.where(swap, a_slot, b_slot)

                if neutral_round:
                    p_host = 0.5 * (
                        self._p_advance[host, guest] + 1.0 - self._p_advance[guest, host]
                    )
                else:
                    p_host = self._p_advance[host, guest]

                host_advances = rng.random(p_host.shape) < p_host
                winners = np.where(host_advances, host, guest)
                winner_seed = np.where(
                    host_advances,
                    np.where(swap, b_seed, a_seed),
                    np.where(swap, a_seed, b_seed),
                )

                # Force results that have already happened. Keyed by (round, slot) —
                # never by team pair, which would also fire in the league phase.
                for slot_i in range(winners.shape[1]):
                    forced = known.get(f"{round_name}:{slot_i}")
                    if forced is None:
                        continue
                    f_idx = self.team_idx.get(forced)
                    if f_idx is None:
                        continue
                    winners[:, slot_i] = f_idx
                    winner_seed[:, slot_i] = np.where(
                        a_slot[:, slot_i] == f_idx, a_seed[:, slot_i], b_seed[:, slot_i]
                    )

                if r_i + 1 < len(PLAYOFF_ROUNDS):
                    np.add.at(cnt_reach[PLAYOFF_ROUNDS[r_i + 1]], winners.ravel(), 1)
                slots, seeds = winners, winner_seed

            champions = slots[:, 0]
            np.add.at(cnt_title, champions, 1)

            # ── Tabla Anual ─────────────────────────────────────────────────
            anual_pts = pts + anual_base_pts
            anual_gd = gd + (anual_base_gf - anual_base_ga)
            anual_gf = gf + anual_base_gf
            jitter = rng.random((S, T))
            anual_order = np.lexsort((jitter, anual_gf, anual_gd, anual_pts), axis=-1)[:, ::-1]
            anual_rank = np.empty_like(anual_order)
            np.put_along_axis(
                anual_rank, anual_order,
                np.broadcast_to(np.arange(T), anual_order.shape), axis=-1,
            )
            np.add.at(cnt_anual_pos, (np.arange(T)[None, :], anual_rank), 1)
            np.add.at(cnt_anual_champ, anual_order[:, 0], 1)

            # ── continental berths ──────────────────────────────────────────
            rows = np.arange(S)
            qualified = np.zeros((S, T), dtype=bool)
            if apertura_champ_idx is not None:
                qualified[:, apertura_champ_idx] = True
            qualified[rows, champions] = True
            if copa_idx is not None:
                qualified[:, copa_idx] = True
            elif copa_p is not None:
                draw_c = rng.choice(T + 1, size=S, p=copa_p)
                np.add.at(cnt_copa, draw_c, 1)
                inside = draw_c < T
                qualified[rows[inside], draw_c[inside]] = True

            lib = qualified.copy()
            filled = lib.sum(axis=1)
            for pos in range(T):
                team_at = anual_order[:, pos]
                take = (~lib[rows, team_at]) & (filled < cfg.libertadores_berths)
                lib[rows[take], team_at[take]] = True
                filled = filled + take
            np.add.at(cnt_lib, np.nonzero(lib)[1], 1)

            sud = np.zeros((S, T), dtype=bool)
            filled_s = np.zeros(S, dtype=np.int64)
            for pos in range(T):
                team_at = anual_order[:, pos]
                take = (
                    (~lib[rows, team_at])
                    & (~sud[rows, team_at])
                    & (filled_s < cfg.sudamericana_berths)
                )
                sud[rows[take], team_at[take]] = True
                filled_s = filled_s + take
            np.add.at(cnt_sud, np.nonzero(sud)[1], 1)

            # ── relegation ──────────────────────────────────────────────────
            total_pts = prior_pts + anual_pts
            total_mp = prior_mp + season_mp
            safe_mp = np.where(total_mp > 0, total_mp, 1.0)
            promedio = total_pts / safe_mp

            prom_jitter = rng.random((S, T)) * 1e-9
            worst_prom = np.argmin(promedio + prom_jitter, axis=1)
            last_anual = anual_order[:, -1]

            # Two clubs go down. The first descent is always the worst promedio. The
            # second is normally last place in the Tabla Anual — but when that is the
            # same club, it passes to the next-worst promedio instead.
            #
            # That collision means the promedio table can account for both descents,
            # so it is counted as a promedio relegation rather than being dropped.
            # Attributing it to neither route (the obvious first cut) leaves
            # p_relegation_any exceeding the sum of its parts.
            collision = worst_prom == last_anual
            masked = promedio + prom_jitter
            masked[rows, worst_prom] = np.inf
            second_worst = np.argmin(masked, axis=1)
            second = np.where(collision, second_worst, last_anual)

            np.add.at(cnt_rel_prom, worst_prom, 1)
            np.add.at(cnt_rel_prom, second[collision], 1)
            np.add.at(cnt_rel_anual, second[~collision], 1)

            # The two descents are always distinct clubs, so per simulation each club
            # is counted at most once and p_any is exactly the sum of the two routes.
            np.add.at(cnt_rel_any, worst_prom, 1)
            np.add.at(cnt_rel_any, second, 1)

            # ── the stakes: the same seasons split by the next fixtures' results ──
            if K:
                onehot = (outcome[:, :, None] == np.arange(3)[None, None, :]).astype(np.int32)   # (S, K, 3)
                cnt_out += onehot.sum(axis=0)
                down = np.zeros((S, T), dtype=np.int32)
                down[rows, worst_prom] = 1
                down[rows, second] = 1
                top8 = np.zeros((S, T), dtype=np.int32)
                for zone_q in qualifiers.values():
                    top8[rows[:, None], zone_q] = 1
                first = np.zeros((S, T), dtype=np.int32)
                first[rows, anual_order[:, 0]] = 1
                ind = {"title": first, "libertadores": lib.astype(np.int32), "sudamericana": sud.astype(np.int32),
                       "relegation": down, "top8": top8}
                for key, mat in ind.items():
                    cnt_st[key] += np.einsum("sko,st->kot", onehot, mat)

            if self.boot_model is not None:
                self.boot_model.accumulate_batch(goals, self.teams)

            sum_pts += pts.sum(axis=0)
            sum_anual_pts += anual_pts.sum(axis=0)
            sum_goals += goals.sum(axis=0)
            if len(promedio_samples) * self.chunk < 5000:
                promedio_samples.append(promedio[: min(S, 2000)].copy())

            done += S

        # zone winners come from position counts
        cnt_zone_win = cnt_zone_pos[:, 0]

        runtime = time.perf_counter() - start
        logger.info("Simulated %d seasons in %.1fs", n, runtime)
        res = self._assemble(
            n, runtime, cnt_zone_pos, cnt_zone_win, cnt_top8, cnt_reach, cnt_title,
            cnt_anual_pos, cnt_anual_champ, cnt_lib, cnt_sud,
            cnt_rel_prom, cnt_rel_anual, cnt_rel_any,
            sum_pts, sum_anual_pts, sum_goals, promedio_samples,
        )
        if copa_p is not None:
            res.copa_winner_share = {t: float(cnt_copa[i] / n) for t, i in self.team_idx.items() if cnt_copa[i]}
            if cnt_copa[T]:
                res.copa_winner_share["(outside the league)"] = float(cnt_copa[T] / n)
        for j, slot in sorted(stake_at.items(), key=lambda kv: kv[1]):
            m = league_left[j]
            nk = cnt_out[slot]

            def cond(c, slot=slot, nk=nk):
                return [(c[slot, o] / nk[o]).tolist() if nk[o] else None for o in range(3)]

            res.stakes.append({
                "id": str(m.game_id), "home": m.home_team, "away": m.away_team,
                "date": m.date.isoformat().replace("+00:00", "Z") if m.date else None,
                "n": nk.tolist(), "title": cond(cnt_st["title"]),
                "bands": {key: cond(cnt_st[key]) for key in STAKE_KEYS},
            })
        return res

    def _stake_fixtures(self, league_left) -> dict[int, int]:
        """The fixtures the stakes split on: the dated zone-phase fixtures within `stake_days` of the first one
        still to play, at most `stake_max`, soonest first, as {fixture index: slot} (league/simulator.py)."""
        if not self.stake_max:
            return {}
        dated = [(m.date, j) for j, m in enumerate(league_left) if m.date is not None]
        if not dated:
            return {}
        dated.sort(key=lambda x: (x[0], x[1]))
        first = dated[0][0]
        pick = [j for d, j in dated if (d - first).total_seconds() <= self.stake_days * 86400][: self.stake_max]
        return {j: k for k, j in enumerate(pick)}

    def _assemble(
        self, n, runtime, cnt_zone_pos, cnt_zone_win, cnt_top8, cnt_reach, cnt_title,
        cnt_anual_pos, cnt_anual_champ, cnt_lib, cnt_sud,
        cnt_rel_prom, cnt_rel_anual, cnt_rel_any,
        sum_pts, sum_anual_pts, sum_goals, promedio_samples,
    ) -> LigaResults:
        res = LigaResults(n_sims=n, runtime_s=runtime, teams=list(self.teams))
        prom = np.concatenate(promedio_samples, axis=0) if promedio_samples else None

        for team, i in self.team_idx.items():
            res.p_zone_position[team] = (cnt_zone_pos[i] / n).tolist()
            res.p_top8[team] = float(cnt_top8[i] / n)
            res.p_zone_win[team] = float(cnt_zone_win[i] / n)
            res.expected_points[team] = float(sum_pts[i] / n)
            res.p_reach[team] = {r: float(cnt_reach[r][i] / n) for r in PLAYOFF_ROUNDS}
            res.p_title[team] = float(cnt_title[i] / n)
            res.p_anual_position[team] = (cnt_anual_pos[i] / n).tolist()
            res.p_anual_champion[team] = float(cnt_anual_champ[i] / n)
            res.expected_anual_points[team] = float(sum_anual_pts[i] / n)
            res.p_libertadores[team] = float(cnt_lib[i] / n)
            res.p_sudamericana[team] = float(cnt_sud[i] / n)
            res.p_relegation_promedio[team] = float(cnt_rel_prom[i] / n)
            res.p_relegation_anual[team] = float(cnt_rel_anual[i] / n)
            res.p_relegation_any[team] = float(cnt_rel_any[i] / n)
            res.team_goals_mean[team] = float(sum_goals[i] / n)
            if prom is not None:
                q = np.quantile(prom[:, i], [0.05, 0.50, 0.95])
                res.promedio_quantiles[team] = (float(q[0]), float(q[1]), float(q[2]))
        return res
