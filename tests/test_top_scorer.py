"""
Tests for the batch top-scorer path.

The World Cup drives GoldenBootModel one match at a time and calls `allocate()` only
from `_knockout_match`, so group goals never reach it — it sees 8 of 104 matches. In a
league that would hide roughly 240 of 255, making the model meaningless. The batch
entry point exists to fix that for a simulator vectorized over the simulation axis.
"""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.football.core import GoldenBootModel

CANDIDATES = [
    {"name": "Striker A", "team": "Boca Juniors", "cur_goals": 5, "cur_assists": 2,
     "hist_goals_90": 0.6, "role": "FWD"},
    {"name": "Striker B", "team": "River Plate", "cur_goals": 5, "cur_assists": 0,
     "hist_goals_90": 0.6, "role": "FWD"},
    {"name": "Midfielder C", "team": "Boca Juniors", "cur_goals": 0, "cur_assists": 4,
     "hist_goals_90": 0.1, "role": "MID"},
    {"name": "Defender D", "team": "Racing Club", "cur_goals": 0, "cur_assists": 0,
     "hist_goals_90": 0.02, "role": "DEF"},
]
TEAMS = ["Boca Juniors", "River Plate", "Racing Club"]


def test_batch_produces_a_valid_distribution() -> None:
    model = GoldenBootModel(CANDIDATES, seed=3)
    rng = np.random.default_rng(1)
    goals = rng.poisson(20, size=(4000, len(TEAMS)))

    model.accumulate_batch(goals, TEAMS)
    probs = model.probabilities(4000)

    assert probs, "no player ever won the race"
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
    for name, p in probs.items():
        assert 0.0 <= p <= 1.0, name


def test_more_team_goals_means_more_top_scorer_probability() -> None:
    """A club scoring far more must carry its forward up the race."""
    rng = np.random.default_rng(5)
    n = 4000

    boca_heavy = np.column_stack([
        rng.poisson(45, n), rng.poisson(10, n), rng.poisson(10, n),
    ])
    river_heavy = np.column_stack([
        rng.poisson(10, n), rng.poisson(45, n), rng.poisson(10, n),
    ])

    m1 = GoldenBootModel(CANDIDATES, seed=3)
    m1.accumulate_batch(boca_heavy, TEAMS)
    p1 = m1.probabilities(n)

    m2 = GoldenBootModel(CANDIDATES, seed=3)
    m2.accumulate_batch(river_heavy, TEAMS)
    p2 = m2.probabilities(n)

    assert p1.get("Striker A", 0) > p2.get("Striker A", 0)
    assert p2.get("Striker B", 0) > p1.get("Striker B", 0)


def test_zero_goals_leaves_the_current_leader_on_top() -> None:
    """
    With no goals left to score, the race is decided by what is already on the board:
    two players tied on 5 goals, broken by assists.
    """
    model = GoldenBootModel(CANDIDATES, seed=3)
    model.accumulate_batch(np.zeros((500, len(TEAMS)), dtype=int), TEAMS)
    probs = model.probabilities(500)
    # Striker A and B are level on 5 goals; A has more assists and must always win.
    assert probs.get("Striker A", 0) == pytest.approx(1.0)


def test_unknown_teams_are_ignored_not_fatal() -> None:
    """A club with no tracked candidates must not raise or absorb probability."""
    model = GoldenBootModel(CANDIDATES, seed=3)
    teams = TEAMS + ["Some Promoted Club"]
    goals = np.full((200, len(teams)), 3, dtype=int)
    model.accumulate_batch(goals, teams)
    assert sum(model.probabilities(200).values()) == pytest.approx(1.0, abs=1e-9)


def test_shape_mismatch_is_rejected() -> None:
    """Silently mis-aligning teams would attribute goals to the wrong clubs."""
    model = GoldenBootModel(CANDIDATES, seed=3)
    with pytest.raises(ValueError, match="expected"):
        model.accumulate_batch(np.zeros((10, 2), dtype=int), TEAMS)
    with pytest.raises(ValueError, match="expected"):
        model.accumulate_batch(np.zeros(10, dtype=int), TEAMS)


def test_per_match_lifecycle_still_works() -> None:
    """
    The World Cup path must be untouched — it is still what build_site_wc.py drives.
    """
    model = GoldenBootModel(CANDIDATES, seed=3)
    for _ in range(200):
        model.start_sim()
        model.allocate("Boca Juniors", 4)
        model.allocate("River Plate", 1)
        model.finalize_sim()
    probs = model.probabilities(200)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
    assert probs.get("Striker A", 0) > 0


def test_simulator_feeds_league_goals_to_the_model() -> None:
    """
    End to end: the league phase must reach the top-scorer model. This is the
    regression the batch path exists to prevent.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from test_liga_simulator import CFG, _FixedModel, _make_state

    from oddsmarkets.football.competitions.liga.simulator import LigaSimulator

    state = _make_state(played_fraction=0.2)
    candidates = [
        {"name": f"{team} Forward", "team": team, "cur_goals": 3, "cur_assists": 1,
         "hist_goals_90": 0.5, "role": "FWD"}
        for team in state.teams
    ]
    boot = GoldenBootModel(candidates, seed=11)
    results = LigaSimulator(_FixedModel(), state, cfg=CFG, boot_model=boot).run()

    probs = boot.probabilities(results.n_sims)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9)
    # Many clubs must be represented; if only knockout goals counted, the field would
    # collapse to the handful of clubs that reach the final rounds.
    assert len(probs) > 10
