"""
Invariant tests for the plain-league simulator, including the MLS playoff.

Monte Carlo output cannot be eyeballed, so these pin properties that must hold
exactly regardless of the model: distributions that sum to a known count, bands that
are ranges of the position distribution, conservation of points, and behaviour under
a degenerate model whose outcome is known in advance.
"""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.football.competitions.league.config import (
    BUNDESLIGA,
    MLS,
    MLS_ROUNDS,
    PREMIER_LEAGUE,
    LeagueConfig,
    with_sims,
)
from oddsmarkets.football.competitions.league.season_state import LeagueMatch, LeagueState
from oddsmarkets.football.competitions.league.simulator import LeagueSimulator

from tests.test_liga_simulator import _FixedModel, _HomeAlwaysWins


def _fixtures(teams: list[str], prefix: str) -> list[LeagueMatch]:
    """Double round-robin: every ordered pair once."""
    out = []
    for i, home in enumerate(teams):
        for j, away in enumerate(teams):
            if i == j:
                continue
            out.append(LeagueMatch(
                game_id=f"{prefix}-{i}-{j}", home_team=home, away_team=away,
                round_name=str((i + j) % (len(teams) - 1) + 1),
            ))
    return out


def make_state(cfg: LeagueConfig, played_fraction: float = 0.3, seed: int = 3) -> LeagueState:
    rng = np.random.default_rng(seed)
    if cfg.conferences:
        per = cfg.teams_per_conference
        confs = {c: [f"{c[:1]}{k:02d}" for k in range(per)] for c in cfg.conferences}
        teams = [t for members in confs.values() for t in members]
        fixtures = []
        for c, members in confs.items():
            fixtures += _fixtures(members, c)
    else:
        confs = {}
        teams = [f"T{k:02d}" for k in range(cfg.n_teams)]
        fixtures = _fixtures(teams, "L")
    fixtures.sort(key=lambda m: (int(m.round_name), m.game_id))
    split = int(len(fixtures) * played_fraction)
    finished = [
        LeagueMatch(
            game_id=m.game_id, home_team=m.home_team, away_team=m.away_team,
            home_goals=int(rng.integers(0, 4)), away_goals=int(rng.integers(0, 3)),
            round_name=m.round_name, status="finished",
        )
        for m in fixtures[:split]
    ]
    return LeagueState(
        cfg=cfg, teams=teams, finished=finished, remaining=fixtures[split:],
        conferences=confs, previous_rank={t: i + 1 for i, t in enumerate(teams)},
    )


EPL = with_sims(PREMIER_LEAGUE, 2_000)
MLS_CFG = with_sims(MLS, 2_000)


@pytest.fixture(scope="module")
def epl():
    state = make_state(EPL)
    return state, LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=EPL).run()


@pytest.fixture(scope="module")
def mls():
    state = make_state(MLS_CFG)
    return state, LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=MLS_CFG).run()


# ── plain league ─────────────────────────────────────────────────────────────

def test_every_team_is_represented(epl) -> None:
    state, res = epl
    assert set(res.p_position) == set(state.teams)
    assert len(res.teams) == EPL.n_teams


def test_positions_sum_to_one_per_team_and_per_slot(epl) -> None:
    _, res = epl
    matrix = np.array([res.p_position[t] for t in res.teams])
    assert matrix.shape == (EPL.n_teams, EPL.n_teams)
    assert np.allclose(matrix.sum(axis=1), 1.0)
    assert np.allclose(matrix.sum(axis=0), 1.0)


def test_title_is_first_place(epl) -> None:
    _, res = epl
    assert sum(res.p_title.values()) == pytest.approx(1.0)
    for t in res.teams:
        assert res.p_title[t] == pytest.approx(res.p_position[t][0])


def test_bands_are_ranges_of_the_position_distribution(epl) -> None:
    _, res = epl
    for band in EPL.bands:
        assert band.key in res.p_band
        total = sum(res.p_band[band.key].values())
        assert total == pytest.approx(band.last - band.first + 1)
        for t in res.teams:
            expected = sum(res.p_position[t][band.first - 1: band.last])
            assert res.p_band[band.key][t] == pytest.approx(expected)


def test_exactly_three_are_relegated(epl) -> None:
    _, res = epl
    assert sum(res.p_band["rel"].values()) == pytest.approx(3.0)


def test_all_probabilities_in_range(epl) -> None:
    _, res = epl
    for d in (res.p_title, *res.p_band.values()):
        for v in d.values():
            assert 0.0 <= v <= 1.0
    for t in res.teams:
        assert all(0.0 <= p <= 1.0 for p in res.p_position[t])
        lo, mid, hi = res.points_quantiles[t]
        assert lo <= mid <= hi


def test_points_are_conserved() -> None:
    """Home always wins 1-0: every remaining fixture adds exactly three points."""
    state = make_state(EPL, played_fraction=0.5)
    res = LeagueSimulator(_HomeAlwaysWins(), state, cfg=EPL).run()
    seeded = sum(r.points for r in state.records().values())
    remaining = sum(1 for m in state.remaining if not m.is_playoff)
    assert sum(res.expected_points.values()) == pytest.approx(seeded + 3 * remaining)
    # And every simulated goal is a home goal, one per fixture.
    assert sum(res.team_goals_mean.values()) == pytest.approx(remaining)


def test_degenerate_model_is_deterministic() -> None:
    state = make_state(EPL, played_fraction=0.0)
    res = LeagueSimulator(_HomeAlwaysWins(), state, cfg=EPL).run()
    # With a symmetric double round-robin and home always winning, every team
    # finishes on the same points; only the jittered tiebreak varies. Each team
    # therefore has an equal share of every position.
    for t in res.teams:
        assert res.p_position[t][0] == pytest.approx(1 / EPL.n_teams, abs=0.05)


def test_run_is_reproducible() -> None:
    state = make_state(EPL)
    a = LeagueSimulator(_FixedModel(0.2), state, cfg=EPL, seed=9).run()
    b = LeagueSimulator(_FixedModel(0.2), state, cfg=EPL, seed=9).run()
    assert a.p_position == b.p_position
    assert a.p_band == b.p_band


def test_chunking_does_not_change_results() -> None:
    state = make_state(EPL)
    whole = LeagueSimulator(_FixedModel(0.2), state, cfg=EPL, seed=5, chunk=2_000).run()
    parts = LeagueSimulator(_FixedModel(0.2), state, cfg=EPL, seed=5, chunk=500).run()
    # Different chunking consumes the RNG differently, so results differ by
    # sampling noise only. Compare at a tolerance that a structural bug would blow.
    for t in state.teams:
        assert abs(whole.expected_points[t] - parts.expected_points[t]) < 2.5


def test_seeded_results_carry_into_expected_points() -> None:
    state = make_state(EPL, played_fraction=0.6)
    res = LeagueSimulator(_FixedModel(), state, cfg=EPL).run()
    for team, rec in state.records().items():
        assert res.expected_points[team] >= rec.points - 1e-9


def test_relegation_playoff_band_is_one_place() -> None:
    cfg = with_sims(BUNDESLIGA, 1_000)
    res = LeagueSimulator(_FixedModel(), make_state(cfg), cfg=cfg).run()
    assert sum(res.p_band["rel_playoff"].values()) == pytest.approx(1.0)
    assert sum(res.p_band["rel"].values()) == pytest.approx(2.0)
    assert not res.p_cup and not res.p_playoffs


# ── MLS: conferences and playoffs ────────────────────────────────────────────

def test_conference_positions_sum_to_one(mls) -> None:
    state, res = mls
    per = MLS_CFG.teams_per_conference
    for conf, members in state.conferences.items():
        matrix = np.array([res.p_conf_position[t] for t in members])
        assert matrix.shape == (per, per)
        assert np.allclose(matrix.sum(axis=1), 1.0)
        assert np.allclose(matrix.sum(axis=0), 1.0)


def test_overall_table_still_covers_everyone(mls) -> None:
    _, res = mls
    matrix = np.array([res.p_position[t] for t in res.teams])
    assert np.allclose(matrix.sum(axis=1), 1.0)
    assert sum(res.p_title.values()) == pytest.approx(1.0)   # Supporters' Shield


def test_playoff_field_counts_are_exact(mls) -> None:
    _, res = mls
    q = MLS_CFG.playoff.qualifiers_per_conference
    assert sum(res.p_playoffs.values()) == pytest.approx(2 * q)
    assert sum(res.p_band["playoffs"].values()) == pytest.approx(14.0)
    assert sum(res.p_band["wildcard"].values()) == pytest.approx(4.0)
    totals = {r: sum(res.p_reach[t][r] for t in res.teams) for r in MLS_ROUNDS}
    assert totals["wc"] == pytest.approx(4.0)       # two wildcard matches
    assert totals["r1"] == pytest.approx(16.0)      # eight series
    assert totals["csf"] == pytest.approx(8.0)
    assert totals["cf"] == pytest.approx(4.0)
    assert totals["final"] == pytest.approx(2.0)    # two conference champions
    assert sum(res.p_cup.values()) == pytest.approx(1.0)


def test_playoff_ladder_is_monotone(mls) -> None:
    _, res = mls
    for t in res.teams:
        r = res.p_reach[t]
        assert res.p_playoffs[t] >= r["r1"] - 1e-9
        assert r["r1"] >= r["csf"] >= r["cf"] >= r["final"] >= res.p_cup[t]
        assert res.p_playoffs[t] == pytest.approx(
            res.p_band["playoffs"][t] + res.p_band["wildcard"][t]
        )


def test_cup_winner_must_have_made_the_playoffs(mls) -> None:
    _, res = mls
    for t in res.teams:
        if res.p_playoffs[t] == 0.0:
            assert res.p_cup[t] == 0.0


def test_mls_reproducible_and_bounded(mls) -> None:
    state, res = mls
    again = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=MLS_CFG).run()
    assert again.p_cup == res.p_cup
    for v in res.p_cup.values():
        assert 0.0 <= v <= 1.0


# ── forcing played playoff ties ──────────────────────────────────────────────

def _mls_state_with_results() -> LeagueState:
    """A complete MLS regular season, so seeds are fixed, plus decided playoff ties."""
    state = make_state(MLS_CFG, played_fraction=1.0)
    east = state.standings("Eastern")
    s1, s8, s9 = east[0][0], east[7][0], east[8][0]
    # Seed 9 beat seed 8 in the wild card, then beat seed 1 in Round One 2-1.
    state.playoff_results = {frozenset((s8, s9)): s9, frozenset((s1, s9)): s9}
    return state


def test_forced_wildcard_and_series_results_are_certain() -> None:
    state = _mls_state_with_results()
    east = state.standings("Eastern")
    s1, s8, s9 = east[0][0], east[7][0], east[8][0]
    res = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=MLS_CFG).run()
    assert res.p_reach[s9]["r1"] == pytest.approx(1.0)
    assert res.p_reach[s8]["r1"] == pytest.approx(0.0)
    assert res.p_reach[s9]["csf"] == pytest.approx(1.0)
    assert res.p_reach[s1]["csf"] == pytest.approx(0.0)
    assert res.p_cup[s1] == pytest.approx(0.0)
    # Counts still balance: eight clubs per conference reach Round One.
    assert sum(res.p_reach[t]["r1"] for t in res.teams) == pytest.approx(16.0)


def test_undecided_series_is_left_to_the_simulation() -> None:
    state = make_state(MLS_CFG, played_fraction=1.0)
    east = state.standings("Eastern")
    s1, s9 = east[0][0], east[8][0]
    open_state = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=MLS_CFG).run()
    assert 0.0 < open_state.p_reach[s1]["csf"] < 1.0
    assert 0.0 < open_state.p_reach[s9]["r1"] < 1.0


# ── Liga MX Liguilla and the Belgian split ───────────────────────────────────

from oddsmarkets.football.competitions.league.config import BELGIAN_PRO_LEAGUE, LIGA_MX, LIGUILLA_ROUNDS  # noqa: E402

MX = with_sims(LIGA_MX, 2_000)
BEL = with_sims(BELGIAN_PRO_LEAGUE, 1_000)


def test_liguilla_counts_are_exact() -> None:
    state = make_state(MX, played_fraction=0.5)
    res = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=MX).run()
    assert sum(res.p_playoffs.values()) == pytest.approx(10.0)
    assert sum(res.p_band["liguilla"].values()) == pytest.approx(6.0)
    assert sum(res.p_band["play_in"].values()) == pytest.approx(4.0)
    totals = {r: sum(res.p_reach[t][r] for t in res.teams) for r in LIGUILLA_ROUNDS}
    assert totals == pytest.approx({"play_in": 4.0, "qf": 8.0, "sf": 4.0, "final": 2.0})
    assert sum(res.p_cup.values()) == pytest.approx(1.0)
    for t in res.teams:
        r = res.p_reach[t]
        assert r["qf"] >= r["sf"] >= r["final"] >= res.p_cup[t] - 1e-9
        assert res.p_playoffs[t] == pytest.approx(res.p_band["liguilla"][t] + res.p_band["play_in"][t])


def test_liguilla_decided_ties_are_forced() -> None:
    state = make_state(MX, played_fraction=1.0)
    table = [t for t, _ in state.standings()]
    s2, s7, s8 = table[1], table[6], table[7]
    # Seed 7 won the play-in (keeping seed 7, so it meets seed 2) and then knocked
    # seed 2 out of the quarter-final.
    state.playoff_results = {frozenset((s7, s8)): s7, frozenset((s2, s7)): s7}
    res = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=MX).run()
    assert res.p_reach[s7]["qf"] == pytest.approx(1.0)
    assert res.p_reach[s7]["sf"] == pytest.approx(1.0)
    assert res.p_reach[s2]["sf"] == pytest.approx(0.0)


def test_belgian_split_produces_a_full_final_order() -> None:
    state = make_state(BEL, played_fraction=0.6)
    res = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=BEL).run()
    matrix = np.array([res.p_final_position[t] for t in res.teams])
    assert matrix.shape == (18, 18)
    assert np.allclose(matrix.sum(axis=1), 1.0) and np.allclose(matrix.sum(axis=0), 1.0)
    assert sum(res.p_title.values()) == pytest.approx(1.0)
    for t in res.teams:
        assert res.p_title[t] == pytest.approx(res.p_final_position[t][0])
    assert sum(res.p_band["euro_group"].values()) == pytest.approx(6.0)
    assert sum(res.p_band["rel"].values()) == pytest.approx(1.0)
    # The regular-season table still sums to one per club.
    reg = np.array([res.p_position[t] for t in res.teams])
    assert np.allclose(reg.sum(axis=1), 1.0)


def test_belgian_split_keeps_regular_season_groups() -> None:
    """A club in the regular-season top six can only finish 1-6; one in 13-18 only 13-18."""
    state = make_state(BEL, played_fraction=1.0)
    res = LeagueSimulator(_FixedModel(home_bias=0.25), state, cfg=BEL).run()
    table = [t for t, _ in state.standings()]
    for pos, t in enumerate(table, start=1):
        dist = res.p_final_position[t]
        if pos <= 6:
            assert sum(dist[:6]) == pytest.approx(1.0)
        elif pos <= 12:
            assert sum(dist[6:12]) == pytest.approx(1.0)
        else:
            assert sum(dist[12:]) == pytest.approx(1.0)
