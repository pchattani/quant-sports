"""
Tests for the offline logic in the backfill and tuning scripts.

The network paths need Sofascore and cannot run here, but the parts that decide
whether the output is trustworthy — the points-conservation check, the promedio
table, and the scoring functions the grid search ranks on — are pure and testable.
"""
from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def _load(name: str):
    """Import a script by path; they are scripts, not package modules."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


backfill = _load("backfill_liga_history")
tuning = _load("tune_liga_model")


# ── backfill: league table and consistency ───────────────────────────────────

def _match(home, away, hg, ag):
    return {
        "game_id": f"{home}-{away}", "home_team": home, "away_team": away,
        "home_goals": hg, "away_goals": ag, "match_date": "2025-03-01",
        "season": 2025, "torneo": "apertura", "weight": 1.0, "round": 1,
    }


def test_league_table_counts_points_correctly() -> None:
    rows = [
        _match("A", "B", 2, 0),   # A win
        _match("B", "C", 1, 1),   # draw
        _match("C", "A", 0, 3),   # A win away
    ]
    table = backfill.league_table(rows)
    assert table["A"] == {"points": 6, "matches": 2, "won": 2, "drawn": 0,
                          "lost": 0, "gf": 5, "ga": 0}
    assert table["B"]["points"] == 1
    assert table["B"]["drawn"] == 1
    assert table["C"]["points"] == 1
    assert table["C"]["lost"] == 1


def test_consistency_check_passes_on_a_complete_dump() -> None:
    rows = [_match("A", "B", 2, 0), _match("B", "C", 1, 1), _match("C", "A", 0, 3)]
    assert backfill.check_consistency(rows, backfill.league_table(rows), "test") is True


def test_consistency_check_catches_a_truncated_table() -> None:
    """
    The guard exists because a partial dump produces a plausible-looking table.
    Dropping a club's results must be detected, not silently averaged away.
    """
    rows = [_match("A", "B", 2, 0), _match("B", "C", 1, 1)]
    table = backfill.league_table(rows)
    del table["A"]
    assert backfill.check_consistency(rows, table, "truncated") is False


def test_promedios_accumulate_across_seasons() -> None:
    """
    Points per match, not per season: a club promoted midway through the window has
    fewer matches and must not be penalised for the seasons it was not in the division.
    """
    y2024 = [_match("A", "B", 1, 0), _match("B", "A", 0, 0)]
    y2025 = [_match("A", "C", 3, 0), _match("C", "A", 1, 1)]

    totals: dict[str, dict] = {}
    for rows in (y2024, y2025):
        for team, rec in backfill.league_table(rows).items():
            acc = totals.setdefault(team, {"points": 0, "matches": 0})
            acc["points"] += rec["points"]
            acc["matches"] += rec["matches"]

    assert totals["A"] == {"points": 8, "matches": 4}
    # C only appeared in one season and is scored on those matches alone.
    assert totals["C"]["matches"] == 2
    assert totals["C"]["points"] / totals["C"]["matches"] == pytest.approx(0.5)


# ── tuning: scoring functions ────────────────────────────────────────────────

def test_log_loss_rewards_confident_correctness() -> None:
    confident = [(0.9, 0.05, 0.05)]
    hedged = [(1 / 3, 1 / 3, 1 / 3)]
    assert tuning.log_loss(confident, [0]) < tuning.log_loss(hedged, [0])


def test_log_loss_punishes_confident_errors_hard() -> None:
    """
    The reason log-loss is the primary metric: a probability dashboard must be
    penalised much more for being confidently wrong than for hedging.
    """
    wrong = tuning.log_loss([(0.9, 0.05, 0.05)], [2])
    hedged = tuning.log_loss([(1 / 3, 1 / 3, 1 / 3)], [2])
    assert wrong > hedged * 2


def test_log_loss_of_a_uniform_forecast_is_ln3() -> None:
    uniform = [(1 / 3, 1 / 3, 1 / 3)] * 20
    assert tuning.log_loss(uniform, [0] * 20) == pytest.approx(math.log(3), abs=1e-9)


def test_log_loss_is_finite_on_a_zero_probability() -> None:
    """A model assigning zero to what happened must score badly, not crash."""
    score = tuning.log_loss([(1.0, 0.0, 0.0)], [1])
    assert math.isfinite(score)
    assert score > 10


def test_brier_is_zero_for_a_perfect_forecast() -> None:
    assert tuning.brier([(1.0, 0.0, 0.0)], [0]) == pytest.approx(0.0)
    assert tuning.brier([(0.0, 0.0, 1.0)], [0]) == pytest.approx(2.0)


def test_outcome_encoding() -> None:
    class Row:
        def __init__(self, h, a):
            self.home_goals, self.away_goals = h, a

    assert tuning.outcome_of(Row(2, 1)) == 0
    assert tuning.outcome_of(Row(1, 1)) == 1
    assert tuning.outcome_of(Row(0, 2)) == 2


def test_baselines_are_computed_and_beat_uniform() -> None:
    """
    A home-advantage-only prior should beat a uniform one on real football, since
    home wins are genuinely more common. If the fitted model cannot clear this floor,
    it is not worth adopting.
    """
    import pandas as pd

    rows = []
    for i in range(200):
        # Roughly 45% home wins, 28% draws, 27% away wins.
        hg, ag = (2, 0) if i % 100 < 45 else (1, 1) if i % 100 < 73 else (0, 1)
        rows.append({
            "home_team": f"T{i % 10}", "away_team": f"T{(i + 3) % 10}",
            "home_goals": hg, "away_goals": ag,
            "match_date": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=i),
        })
    df = pd.DataFrame(rows)

    base = tuning.baselines(df, min_train=100)
    assert set(base) == {"uniform", "home_advantage_only"}
    assert base["uniform"]["log_loss"] == pytest.approx(math.log(3), abs=1e-3)
    assert base["home_advantage_only"]["log_loss"] < base["uniform"]["log_loss"]


def test_baselines_handle_no_test_data() -> None:
    import pandas as pd
    assert tuning.baselines(pd.DataFrame({"home_goals": [], "away_goals": []}), 0) == {}
