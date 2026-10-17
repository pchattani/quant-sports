"""
Tests for team strength, form, schedule strength and luck.

These describe what has happened and what the fitted model believes — the forecast
lives in the simulator. The properties worth pinning are the ones that make the view
trustworthy: that neutral strength really is schedule-independent, that luck is
computed against xG rather than the result, and that the ranks compare like with like.
"""
from __future__ import annotations

import pytest

from oddsmarkets.football.competitions.liga.strength import (
    build_team_strength,
    elo_trajectories,
    expected_points_from_xg,
    neutral_strength,
)
from oddsmarkets.football.core import EloRatings

from tests.test_liga_simulator import CFG, _FixedModel, _make_state


# ── expected points from xG ──────────────────────────────────────────────────

def test_equal_xg_gives_equal_expected_points() -> None:
    home, away = expected_points_from_xg(1.4, 1.4)
    assert home == pytest.approx(away)


def test_more_xg_earns_more_expected_points() -> None:
    strong, weak = expected_points_from_xg(2.5, 0.5)
    assert strong > weak
    assert strong > 2.0
    assert weak < 1.0


def test_expected_points_stay_within_bounds() -> None:
    """A single match cannot be worth more than 3 points or fewer than 0."""
    for h in (0.0, 0.3, 1.2, 3.0, 6.0):
        for a in (0.0, 0.3, 1.2, 3.0, 6.0):
            home, away = expected_points_from_xg(h, a)
            assert 0.0 <= home <= 3.0, (h, a)
            assert 0.0 <= away <= 3.0, (h, a)
            # Both sides cannot win, so the pair cannot exceed a 3-point match by much;
            # the draw mass is counted once for each side.
            assert home + away <= 3.0 + 1e-9, (h, a)


def test_zero_xg_is_a_goalless_draw() -> None:
    home, away = expected_points_from_xg(0.0, 0.0)
    assert home == pytest.approx(1.0)
    assert away == pytest.approx(1.0)


# ── neutral strength ─────────────────────────────────────────────────────────

def test_neutral_strength_is_points_per_game_scaled() -> None:
    state = _make_state(played_fraction=0.3)
    strength = neutral_strength(_FixedModel(), state.teams)
    assert len(strength) == len(state.teams)
    for team, value in strength.items():
        assert 0.0 <= value <= 3.0, team


def test_neutral_strength_is_schedule_independent() -> None:
    """
    The point of averaging over every opponent: the value must not depend on which
    matches a club happens to have played, so it is identical however far the season
    has progressed.
    """
    early = _make_state(played_fraction=0.0)
    late = _make_state(played_fraction=0.8)
    model = _FixedModel(home_bias=0.3)
    assert neutral_strength(model, early.teams) == neutral_strength(model, late.teams)


# ── the assembled view ───────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def rows():
    state = _make_state(played_fraction=0.4)
    return build_team_strength(_FixedModel(home_bias=0.2), state, state.teams), state


def test_every_club_is_described(rows) -> None:
    table, state = rows
    assert len(table) == len(state.teams)
    assert {r.team for r in table} == set(state.teams)


def test_sorted_by_strength_and_ranked_consistently(rows) -> None:
    table, _ = rows
    values = [r.strength_ppg for r in table]
    assert values == sorted(values, reverse=True)
    assert [r.strength_rank for r in table] == list(range(1, len(table) + 1))


def test_points_and_ppg_match_the_table(rows) -> None:
    table, state = rows
    records = state.clausura.records()
    for r in table:
        assert r.points == records[r.team].points, r.team
        assert r.played == records[r.team].played, r.team
        if r.played:
            assert r.ppg == pytest.approx(r.points / r.played, abs=1e-3), r.team


def test_form_window_is_respected(rows) -> None:
    table, _ = rows
    for r in table:
        assert len(r.form_results) <= 6, r.team
        assert set(r.form_results) <= {"W", "D", "L"}, r.team
        expected = sum(3 if x == "W" else 1 if x == "D" else 0 for x in r.form_results)
        assert r.form_points == expected, r.team
        # Form is a subset of the season, so it cannot exceed the season total.
        assert r.form_points <= r.points, r.team


def test_rank_delta_compares_within_zone(rows) -> None:
    """
    A 30-club strength ranking against a 15-club zone table would be meaningless, so
    the delta is computed inside the zone. It must therefore stay in range.
    """
    table, state = rows
    zones = state.clausura.zones
    for r in table:
        zone = next(z for z, members in zones.items() if r.team in members)
        assert 1 <= r.table_rank <= len(zones[zone]), r.team
        assert abs(r.rank_delta) < len(zones[zone]), r.team


def test_schedule_strength_is_populated_and_bounded(rows) -> None:
    table, _ = rows
    for r in table:
        assert 0.0 <= r.sos_played <= 3.0, r.team
        assert 0.0 <= r.sos_remaining <= 3.0, r.team
        assert r.sos_delta == pytest.approx(r.sos_remaining - r.sos_played, abs=1e-6)


def test_luck_is_measured_against_xg_not_results() -> None:
    """
    The core property of the luck column: a club that wins while being outshot must
    read as lucky, and one that loses while creating more must read as unlucky. If
    luck were derived from results it would be identically zero.
    """
    state = _make_state(played_fraction=0.4)
    finished = [m for m in state.clausura.finished if m.is_finished]
    assert finished, "fixture produced no finished matches"

    # Whoever actually won created the *fewer* chances in every match. If luck were
    # derived from results rather than xG this would be invisible.
    xg = {}
    for m in finished:
        if m.home_goals > m.away_goals:
            xg[m.game_id] = (0.3, 2.4)      # home won despite being outplayed
        elif m.away_goals > m.home_goals:
            xg[m.game_id] = (2.4, 0.3)      # away won despite being outplayed
        else:
            xg[m.game_id] = (1.2, 1.2)

    table = {r.team: r for r in build_team_strength(
        _FixedModel(), state, state.teams, xg_by_match=xg
    )}

    # Clubs that won most of their matches must come out ahead of their xG.
    winners = [
        t for t in state.teams
        if table[t].played >= 3 and table[t].points >= 2 * table[t].played
    ]
    assert winners, "fixture produced no clear winners to test with"
    for team in winners:
        assert table[team].luck > 0, team
        assert table[team].expected_points < table[team].points, team

    # The mirror image: clubs that lost most of their matches while creating more
    # must read as unlucky.
    losers = [
        t for t in state.teams
        if table[t].played >= 3 and table[t].points <= table[t].played
    ]
    assert losers, "fixture produced no clear losers to test with"
    for team in losers:
        assert table[team].luck < 0, team

    # Note on what is deliberately *not* asserted here: league-wide luck does not sum
    # to zero. A match distributes 3 - P(draw) expected points but only 3 - is_draw
    # real ones, so the totals agree only when the draw rate implied by xG matches the
    # actual one. With lopsided synthetic xG they diverge by construction.


def test_luck_equals_points_minus_expected(rows) -> None:
    table, _ = rows
    for r in table:
        if r.expected_points:
            assert r.luck == pytest.approx(r.points - r.expected_points, abs=1e-2), r.team


def test_missing_xg_leaves_luck_at_zero_not_wrong() -> None:
    """
    Without xG coverage the honest answer is "no reading", not a fabricated one.
    Reporting points-minus-zero would make every club look wildly lucky.
    """
    state = _make_state(played_fraction=0.4)
    table = build_team_strength(_FixedModel(), state, state.teams, xg_by_match={})
    for r in table:
        assert r.xg_for == 0.0
        assert r.luck == 0.0


def test_elo_trajectory_tracks_the_season() -> None:
    state = _make_state(played_fraction=0.5)

    def factory():
        elo = EloRatings(k_league=20, home_advantage=70.0)
        elo.seed_from_ranking(
            {t: i + 1 for i, t in enumerate(state.teams)}, n_teams=len(state.teams)
        )
        return elo

    history = elo_trajectories(factory, state, state.teams)
    assert set(history) == set(state.teams)

    records = state.clausura.records()
    for team, points in history.items():
        assert len(points) == records[team].played, team
        for entry in points:
            assert "elo" in entry and entry["elo"] > 0

    # Ratings must actually move — a flat line would mean the replay did nothing.
    moved = [t for t, pts in history.items() if len(pts) > 1 and pts[0]["elo"] != pts[-1]["elo"]]
    assert len(moved) > 20


def test_handles_a_season_with_nothing_played() -> None:
    state = _make_state(played_fraction=0.0)
    table = build_team_strength(_FixedModel(), state, state.teams)
    assert len(table) == len(state.teams)
    for r in table:
        assert r.played == 0
        assert r.form_results == []
        assert r.ppg == 0.0
        # Strength is model-derived, so it exists before a ball is kicked.
        assert r.strength_ppg > 0
        # Every match is still to come, so the schedule is entirely ahead.
        assert r.sos_remaining > 0
        assert r.sos_played == 0.0
