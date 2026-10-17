"""
The glossary: every catalogue metric has a definition and carries it, the team
metrics and model terms are complete, and glossary.json has the shape the
front-end reads.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oddsmarkets.football.analytics import glossary as g  # noqa: E402
from oddsmarkets.football.analytics.players import METRICS  # noqa: E402

REQUIRED_MODEL_TERMS = {
    "xg", "npxg", "xgot", "xa", "xpts", "luck", "strength", "elo", "attack_defence", "home_advantage", "rho", "time_decay",
    "ridge", "pooled_scale", "scoring_factor", "fair_odds", "de_vig", "edge", "consensus", "percentile", "minutes_floor",
    "shrinkage", "field_tilt", "ppda", "monte_carlo", "position_distribution", "bands", "expected_result", "rating",
    "formation", "form",
}


def test_every_metric_has_a_definition_and_carries_it() -> None:
    keys = [m["key"] for m in METRICS]
    missing = [k for k in keys if not g.PLAYER_DEFINITIONS.get(k, "").strip()]
    assert not missing, missing
    # No orphan definitions either: a renamed metric must rename its definition.
    orphans = sorted(set(g.PLAYER_DEFINITIONS) - set(keys))
    assert not orphans, orphans
    for m in METRICS:
        assert m["desc"] == g.PLAYER_DEFINITIONS[m["key"]]
        assert len(m["desc"]) >= 20, m["key"]
        # Two sentences at most.
        assert m["desc"].count(". ") <= 2, m["key"]
    # Per-90 metrics say so; percentages name the denominator.
    for m in METRICS:
        if m["key"].endswith("_90"):
            assert "per 90 minutes played" in m["desc"], m["key"]
        if m["fmt"] == "pct":
            assert "denominator" in m["desc"], m["key"]
    # The Advanced group is covered.
    assert all(m["desc"] for m in METRICS if m["group"] == "Advanced")


def test_team_metrics_and_model_terms_are_complete() -> None:
    keys = [t["key"] for t in g.TEAM_METRICS]
    assert len(keys) == len(set(keys))
    assert {"xg_for", "xg_against", "xg_diff", "goals_for", "goals_against", "finishing", "keeping", "xpts_per_match", "luck",
            "possession", "field_tilt", "ppda", "shots", "shots_against", "shot_quality", "shot_quality_against", "sot_pct",
            "big_chances", "big_chances_missed", "corners", "aerial_pct", "ground_duel_pct", "passes", "pass_pct",
            "long_ball_share", "crosses", "dribbles", "fouls", "cards", "km", "sprints", "rating"} == set(keys)
    for t in g.TEAM_METRICS:
        assert set(t) == {"key", "label", "desc", "fmt", "lower", "group"}
        assert isinstance(t["lower"], bool) and t["desc"] and t["fmt"] in ("int", "1", "2", "3", "pct")
    lower = {t["key"] for t in g.TEAM_METRICS if t["lower"]}
    assert {"xg_against", "goals_against", "ppda", "shots_against", "shot_quality_against", "big_chances_missed", "fouls", "cards"} == lower
    terms = {t["key"] for t in g.MODEL_TERMS}
    assert REQUIRED_MODEL_TERMS <= terms
    for t in g.MODEL_TERMS:
        assert set(t) == {"key", "label", "desc", "group"} and len(t["desc"]) > 40


def test_glossary_payload_shape() -> None:
    payload = g.build_glossary()
    assert set(payload) == {"groups", "model", "updated_at"}
    names = [grp["name"] for grp in payload["groups"]]
    assert names[0] == "Scoring" and names[-1] == "Team metrics" and "Advanced" in names
    entries = [e for grp in payload["groups"] for e in grp["entries"]]
    assert len(entries) == len(METRICS) + len(g.TEAM_METRICS)
    for e in entries:
        assert set(e) == {"key", "label", "desc", "fmt", "scope", "lower", "group"}
        assert e["desc"] and isinstance(e["lower"], bool)
    assert {e["scope"] for e in entries} == {"out", "gk", "all", "team"}
    assert payload["model"] == g.MODEL_TERMS
    json.dumps(payload)
