"""
Invariant tests for the Liga season simulator.

Monte Carlo output cannot be eyeballed — plausible-looking probabilities can hide a
structural bug for a long time. These check properties that must hold exactly
regardless of the model: probabilities that must sum to a known count, conservation of
points, and behaviour under a degenerate model whose outcome is known in advance.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from oddsmarkets.football.competitions.liga.config import (
    APERTURA,
    CLAUSURA,
    DEFAULT_CONFIG,
    FALLBACK_ZONES_2026,
    LigaConfig,
    PLAYOFF_ROUNDS,
    ZONE_A,
    ZONE_B,
    ZONES,
)
from oddsmarkets.football.competitions.liga.season_state import (
    LigaMatch,
    SeasonState,
    TorneoState,
)
from oddsmarkets.football.competitions.liga.simulator import LigaSimulator

CFG = LigaConfig(n_sims=2_000, sim_chunk=1_000, random_seed=7)


class _FixedModel:
    """
    Model returning a fixed score distribution, so simulator behaviour can be
    reasoned about exactly. `home_bias` shifts mass toward the home side.
    """

    def __init__(self, home_bias: float = 0.0, max_goals: int = 8) -> None:
        self.home_bias = home_bias
        self.max_goals = max_goals

    def predict(self, home, away, neutral=True, max_goals=8):
        from oddsmarkets.football.core import MatchProbabilities

        k = max_goals + 1
        lam_h = 1.3 + (0.0 if neutral else self.home_bias)
        lam_a = 1.1
        ks = np.arange(k)
        facts = np.array([float(math.factorial(i)) for i in range(k)])
        ph = np.exp(-lam_h) * lam_h ** ks / facts
        pa = np.exp(-lam_a) * lam_a ** ks / facts
        m = np.outer(ph, pa)
        m /= m.sum()
        return MatchProbabilities(
            home_win=float(np.tril(m, -1).sum()),
            draw=float(np.trace(m)),
            away_win=float(np.triu(m, 1).sum()),
            lambda_home=lam_h,
            lambda_away=lam_a,
            score_matrix=m,
        )


class _HomeAlwaysWins:
    """Degenerate model: the home side always wins 1-0."""

    def predict(self, home, away, neutral=True, max_goals=8):
        from oddsmarkets.football.core import MatchProbabilities

        k = max_goals + 1
        m = np.zeros((k, k))
        m[1, 0] = 1.0
        return MatchProbabilities(1.0, 0.0, 0.0, 1.0, 0.0, m)


def _round_robin(teams: list[str], torneo: str, zone: str) -> list[LigaMatch]:
    """Single round-robin, alternating home advantage for balance."""
    out = []
    for i, home in enumerate(teams):
        for j, away in enumerate(teams):
            if j <= i:
                continue
            h, a = (home, away) if (i + j) % 2 == 0 else (away, home)
            out.append(LigaMatch(
                game_id=f"{torneo}-{zone}-{i}-{j}",
                home_team=h, away_team=a,
                round_name=str(i + 1), torneo=torneo, zone=zone,
            ))
    return out


def _make_state(
    played_fraction: float = 0.0,
    apertura_champion: str | None = "Belgrano",
    cfg: LigaConfig = CFG,
) -> SeasonState:
    """
    Build a season with a complete Apertura and a Clausura `played_fraction` through
    its league phase.
    """
    zones = {z: list(FALLBACK_ZONES_2026[z]) for z in ZONES}

    apertura_fixtures = []
    for zone in ZONES:
        apertura_fixtures += _round_robin(zones[zone], APERTURA, zone)
    rng = np.random.default_rng(3)
    apertura_finished = [
        LigaMatch(
            game_id=m.game_id, home_team=m.home_team, away_team=m.away_team,
            home_goals=int(rng.integers(0, 4)), away_goals=int(rng.integers(0, 3)),
            round_name=m.round_name, torneo=APERTURA, zone=m.zone, status="finished",
        )
        for m in apertura_fixtures
    ]
    apertura = TorneoState(
        key=APERTURA, zones=zones, finished=apertura_finished,
        remaining=[], champion=apertura_champion, cfg=cfg,
    )

    clausura_fixtures = []
    for zone in ZONES:
        clausura_fixtures += _round_robin(zones[zone], CLAUSURA, zone)
    # Order by round so a partial season advances both zones together, as a real one
    # does. Slicing the zone-concatenated list instead completes all of Zona A before
    # Zona B starts, which leaves half the league with no matches at all — and quietly
    # invalidates anything that reads per-team history.
    clausura_fixtures.sort(key=lambda m: (int(m.round_name), m.game_id))
    split = int(len(clausura_fixtures) * played_fraction)
    finished = [
        LigaMatch(
            game_id=m.game_id, home_team=m.home_team, away_team=m.away_team,
            home_goals=int(rng.integers(0, 4)), away_goals=int(rng.integers(0, 3)),
            round_name=m.round_name, torneo=CLAUSURA, zone=m.zone, status="finished",
        )
        for m in clausura_fixtures[:split]
    ]
    clausura = TorneoState(
        key=CLAUSURA, zones=zones, finished=finished,
        remaining=clausura_fixtures[split:], cfg=cfg,
    )

    prior = {t: (int(rng.integers(40, 90)), 60) for t in apertura.teams}
    return SeasonState(
        year=2026, apertura=apertura, clausura=clausura,
        promedios_prior=prior, cfg=cfg,
    )


@pytest.fixture(scope="module")
def results():
    state = _make_state(played_fraction=0.3)
    return LigaSimulator(_FixedModel(home_bias=0.25), state, cfg=CFG).run()


# ── structural invariants ────────────────────────────────────────────────────

def test_every_team_is_represented(results) -> None:
    assert len(results.teams) == DEFAULT_CONFIG.n_teams
    assert len(results.p_title) == DEFAULT_CONFIG.n_teams


def test_zone_positions_sum_to_one_per_team(results) -> None:
    for team, dist in results.p_zone_position.items():
        assert sum(dist) == pytest.approx(1.0, abs=1e-9), team


def test_zone_positions_sum_to_one_per_slot(results) -> None:
    """Each finishing position in a zone is occupied by exactly one club."""
    state = _make_state(played_fraction=0.3)
    for zone in ZONES:
        members = state.clausura.zones[zone]
        for pos in range(CFG.teams_per_zone):
            total = sum(results.p_zone_position[t][pos] for t in members)
            assert total == pytest.approx(1.0, abs=1e-9), (zone, pos)


def test_qualifier_and_round_counts(results) -> None:
    """16 clubs reach the R16, 8 the QF, 4 the SF, 2 the final, 1 wins."""
    expected = {"r16": 16, "qf": 8, "sf": 4, "final": 2}
    for rnd, count in expected.items():
        total = sum(results.p_reach[t][rnd] for t in results.teams)
        assert total == pytest.approx(count, abs=1e-6), rnd
    assert sum(results.p_title.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(results.p_top8.values()) == pytest.approx(16, abs=1e-6)


def test_top8_matches_r16_entry(results) -> None:
    """Reaching the R16 is exactly finishing top 8 of your zone."""
    for team in results.teams:
        assert results.p_top8[team] == pytest.approx(results.p_reach[team]["r16"], abs=1e-9)


def test_anual_positions_sum_to_one(results) -> None:
    for team, dist in results.p_anual_position.items():
        assert sum(dist) == pytest.approx(1.0, abs=1e-9), team
    for pos in range(len(results.teams)):
        total = sum(results.p_anual_position[t][pos] for t in results.teams)
        assert total == pytest.approx(1.0, abs=1e-9), pos
    assert sum(results.p_anual_champion.values()) == pytest.approx(1.0, abs=1e-6)


def test_exactly_two_teams_are_relegated(results) -> None:
    """
    The headline relegation invariant. Two clubs go down every season, so the
    probabilities must sum to exactly 2 — including when both routes name the
    same club and the collision rule promotes the next-worst promedio.
    """
    assert sum(results.p_relegation_any.values()) == pytest.approx(2.0, abs=1e-6)
    # The two routes partition the two descents. The promedio route carries more than
    # half because it absorbs the second descent whenever both routes name the same
    # club, so the split is not 1.0/1.0.
    total_prom = sum(results.p_relegation_promedio.values())
    total_anual = sum(results.p_relegation_anual.values())
    assert total_prom + total_anual == pytest.approx(2.0, abs=1e-6)
    assert total_prom >= 1.0 - 1e-9


def test_relegation_routes_partition_exactly(results) -> None:
    """
    Within a simulation the two descents are always distinct clubs, so per club the
    two route probabilities must add up exactly to the overall relegation probability.
    """
    for team in results.teams:
        prom = results.p_relegation_promedio[team]
        anual = results.p_relegation_anual[team]
        any_ = results.p_relegation_any[team]
        assert any_ == pytest.approx(prom + anual, abs=1e-9), team


def test_berth_counts_are_exact(results) -> None:
    assert sum(results.p_libertadores.values()) == pytest.approx(
        CFG.libertadores_berths, abs=1e-6
    )
    assert sum(results.p_sudamericana.values()) == pytest.approx(
        CFG.sudamericana_berths, abs=1e-6
    )


def test_libertadores_and_sudamericana_are_disjoint(results) -> None:
    """A club cannot hold both berths, so the two probabilities cannot both be 1."""
    for team in results.teams:
        assert results.p_libertadores[team] + results.p_sudamericana[team] <= 1.0 + 1e-9


def test_all_probabilities_in_range(results) -> None:
    fields = [
        results.p_top8, results.p_title, results.p_anual_champion,
        results.p_libertadores, results.p_sudamericana, results.p_relegation_any,
    ]
    for mapping in fields:
        for team, p in mapping.items():
            assert 0.0 <= p <= 1.0, (team, p)


# ── behavioural checks ───────────────────────────────────────────────────────

def test_apertura_champion_always_has_a_libertadores_berth() -> None:
    """The Apertura winner is already qualified, so its probability is exactly 1."""
    state = _make_state(played_fraction=0.3, apertura_champion="Belgrano")
    res = LigaSimulator(_FixedModel(), state, cfg=CFG).run()
    assert res.p_libertadores["Belgrano"] == pytest.approx(1.0)
    assert res.p_sudamericana["Belgrano"] == pytest.approx(0.0)


def test_copa_argentina_winner_consumes_a_berth() -> None:
    """
    An exogenous Copa Argentina winner takes a Libertadores place, which must
    displace someone rather than expanding the berth count.
    """
    cfg = LigaConfig(
        n_sims=2_000, sim_chunk=1_000, random_seed=7, copa_argentina_winner="Aldosivi"
    )
    state = _make_state(played_fraction=0.3, cfg=cfg)
    res = LigaSimulator(_FixedModel(), state, cfg=cfg).run()
    assert res.p_libertadores["Aldosivi"] == pytest.approx(1.0)
    assert sum(res.p_libertadores.values()) == pytest.approx(cfg.libertadores_berths, abs=1e-6)


def test_points_are_conserved() -> None:
    """
    Expected points must equal seeded points plus 3 per remaining match minus one
    per draw. A structural bug in the fixture loop shows up here immediately.
    """
    state = _make_state(played_fraction=0.0)
    model = _FixedModel()
    res = LigaSimulator(model, state, cfg=CFG).run()

    p = model.predict("A", "B", neutral=False)
    n_fixtures = len(state.clausura.remaining)
    expected_total = n_fixtures * (3.0 - p.draw)
    assert sum(res.expected_points.values()) == pytest.approx(
        expected_total, rel=0.02
    )


def test_degenerate_model_is_deterministic() -> None:
    """
    With a model where the home side always wins 1-0, every club's points are fully
    determined by its home fixtures, so the simulation must be noiseless.
    """
    state = _make_state(played_fraction=0.0)
    res = LigaSimulator(_HomeAlwaysWins(), state, cfg=CFG).run()

    home_counts: dict[str, int] = {t: 0 for t in state.teams}
    for m in state.clausura.remaining:
        home_counts[m.home_team] += 1
    for team, n_home in home_counts.items():
        assert res.expected_points[team] == pytest.approx(3.0 * n_home, abs=1e-9), team
        assert res.team_goals_mean[team] == pytest.approx(float(n_home), abs=1e-9)


def test_promedio_prior_drives_relegation() -> None:
    """
    A club with a catastrophic three-season promedio must be nearly certain to go
    down, regardless of current form — and one with a strong prior must be safe.

    This also pins the team indexing on the promedio path: a misalignment here would
    silently relegate the wrong club, which no aggregate invariant would catch.
    """
    state = _make_state(played_fraction=0.3)
    doomed, safe = state.teams[0], state.teams[1]
    state.promedios_prior = {t: (90, 60) for t in state.teams}
    state.promedios_prior[doomed] = (5, 60)      # ~0.08 points per match
    state.promedios_prior[safe] = (170, 60)      # ~2.8 points per match

    res = LigaSimulator(_FixedModel(), state, cfg=CFG).run()
    assert res.p_relegation_promedio[doomed] > 0.95
    assert res.p_relegation_promedio[safe] == pytest.approx(0.0, abs=1e-6)


def test_promedio_counts_the_whole_season_not_just_this_tournament() -> None:
    """
    Promedios span the full calendar, so a club bottom of the current tournament but
    strong across the season is safe. This is why the relegation table does not track
    the live zone table, which reads as a bug until you check it.
    """
    state = _make_state(played_fraction=0.3)
    promedios = state.promedio_now()
    base = state.anual_base()
    for team in state.teams:
        prior_pts, prior_mp = state.promedios_prior.get(team, (0, 0))
        rec = base[team]
        expected = (prior_pts + rec.points) / (prior_mp + rec.played)
        assert promedios[team] == pytest.approx(expected), team


def test_qualification_is_monotone_in_expected_points() -> None:
    """Within a zone, a club projected more points must not be less likely to qualify."""
    state = _make_state(played_fraction=0.3)
    res = LigaSimulator(_FixedModel(home_bias=0.2), state, cfg=CFG).run()
    for zone in ZONES:
        members = state.clausura.zones[zone]
        ordered = sorted(members, key=lambda t: -res.expected_points[t])
        top, bottom = ordered[0], ordered[-1]
        assert res.p_top8[top] > res.p_top8[bottom], zone


def test_completed_season_raises() -> None:
    state = _make_state(played_fraction=1.0)
    state.clausura.champion = "River Plate"
    with pytest.raises(ValueError, match="complete"):
        LigaSimulator(_FixedModel(), state, cfg=CFG).run()


def test_known_playoff_result_is_forced() -> None:
    """
    A playoff result already on the board must be honoured — and keyed by (round, slot),
    so it cannot leak into the league phase the way a team-pair key would.
    """
    state = _make_state(played_fraction=1.0)
    winner = state.clausura.standings(ZONE_A)[0][0]
    state.clausura.playoff_results["r16:0"] = winner
    res = LigaSimulator(_FixedModel(), state, cfg=CFG).run()
    assert res.p_reach[winner]["qf"] == pytest.approx(1.0)


def test_seeded_results_carry_into_expected_points() -> None:
    """Points already earned must appear in the projection, not be discarded."""
    state = _make_state(played_fraction=0.5)
    res = LigaSimulator(_FixedModel(), state, cfg=CFG).run()
    records = state.clausura.records()
    for team in state.teams:
        assert res.expected_points[team] >= records[team].points - 1e-9, team


def test_home_advantage_shows_up_in_results() -> None:
    """A model with home bias must produce more goals than one without."""
    state = _make_state(played_fraction=0.0)
    flat = LigaSimulator(_FixedModel(home_bias=0.0), state, cfg=CFG).run()
    biased = LigaSimulator(_FixedModel(home_bias=0.6), state, cfg=CFG).run()
    assert sum(biased.team_goals_mean.values()) > sum(flat.team_goals_mean.values())


def test_run_is_reproducible() -> None:
    state = _make_state(played_fraction=0.3)
    a = LigaSimulator(_FixedModel(), state, cfg=CFG, seed=99).run()
    b = LigaSimulator(_FixedModel(), state, cfg=CFG, seed=99).run()
    assert a.p_title == b.p_title
    assert a.p_relegation_any == b.p_relegation_any


def test_chunking_does_not_change_results() -> None:
    """Chunk size is a memory knob and must not alter the answer."""
    state = _make_state(played_fraction=0.3)
    one = LigaSimulator(_FixedModel(), state, cfg=CFG, seed=5, chunk=2_000).run()
    many = LigaSimulator(_FixedModel(), state, cfg=CFG, seed=5, chunk=500).run()
    for team in one.teams:
        assert one.p_title[team] == pytest.approx(many.p_title[team], abs=0.05)
