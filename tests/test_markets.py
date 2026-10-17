"""
Tests for market de-vigging and model edge.

The central property: comparing model probabilities against raw bookmaker odds would
show an edge against every outcome, because implied probabilities sum to more than 1
and the surplus is the book's margin. Everything here must work on de-vigged prices,
or the dashboard manufactures signal that is not there.
"""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.football.core.markets import (
    MIN_EDGE,
    build_match_markets,
    build_outright_markets,
    consensus,
    devig,
    edge,
    overround,
)


class _Model:
    """Fixed match probabilities, so edges are exactly predictable."""

    def __init__(self, home=0.50, draw=0.28, away=0.22):
        self._p = (home, draw, away)

    def predict(self, home, away, neutral=True, max_goals=8):
        from oddsmarkets.football.core import MatchProbabilities
        h, d, a = self._p
        return MatchProbabilities(h, d, a, 1.4, 1.0, np.ones((9, 9)) / 81)


# ── de-vigging ───────────────────────────────────────────────────────────────

def test_devig_normalises_to_one() -> None:
    fair = devig({"home": 2.10, "draw": 3.40, "away": 3.60})
    assert sum(fair.values()) == pytest.approx(1.0)
    assert all(0 < v < 1 for v in fair.values())


def test_devig_preserves_ordering() -> None:
    """Stripping the margin must not change which outcome the book thinks likeliest."""
    prices = {"home": 1.80, "draw": 3.60, "away": 4.50}
    fair = devig(prices)
    assert fair["home"] > fair["draw"] > fair["away"]


def test_devig_removes_the_margin_not_the_signal() -> None:
    """
    A fair book and a heavily margined book with the same relative prices must give
    the same de-vigged probabilities.
    """
    fair_book = {"home": 2.00, "draw": 4.00, "away": 4.00}
    greedy = {k: v * 0.9 for k, v in fair_book.items()}
    assert devig(fair_book) == pytest.approx(devig(greedy))


def test_overround_measures_the_margin() -> None:
    # A perfectly fair three-way book sums to exactly 1.
    assert overround({"home": 3.0, "draw": 3.0, "away": 3.0}) == pytest.approx(0.0)
    margined = overround({"home": 2.70, "draw": 2.70, "away": 2.70})
    assert margined > 0.1


def test_devig_ignores_unusable_prices() -> None:
    """Odds of 1.0 or below, or non-numeric, are dropped rather than crashing."""
    fair = devig({"home": 2.0, "draw": 1.0, "away": "n/a", "extra": None})
    assert set(fair) == {"home"}
    assert fair["home"] == pytest.approx(1.0)
    assert devig({}) == {}
    assert devig({"home": 0.5}) == {}


# ── consensus ────────────────────────────────────────────────────────────────

def test_consensus_pools_across_books() -> None:
    books = {
        "a": {"home": 2.10, "draw": 3.40, "away": 3.60},
        "b": {"home": 2.05, "draw": 3.50, "away": 3.70},
        "c": {"home": 2.15, "draw": 3.30, "away": 3.55},
    }
    fair = consensus(books)
    assert sum(fair.values()) == pytest.approx(1.0)
    assert fair["home"] > fair["away"]


def test_consensus_resists_one_mispriced_book() -> None:
    """
    Median rather than mean, so a single stale line cannot drag the consensus. This
    matters most in a thin market, which Argentine league futures are likely to be.
    """
    sane = {"home": 2.10, "draw": 3.40, "away": 3.60}
    books = {"a": dict(sane), "b": dict(sane), "c": dict(sane)}
    with_outlier = dict(books)
    with_outlier["bad"] = {"home": 15.0, "draw": 3.40, "away": 1.10}

    base = consensus(books)
    skewed = consensus(with_outlier)
    assert skewed["home"] == pytest.approx(base["home"], abs=0.05)


def test_consensus_of_nothing_is_empty() -> None:
    assert consensus({}) == {}
    assert consensus({"a": {"home": 0.0}}) == {}


# ── edge ─────────────────────────────────────────────────────────────────────

def test_edge_is_relative_not_absolute() -> None:
    """
    Two percentage points means something very different at 5% than at 50%, so the
    edge is expressed as a fraction of the market probability.
    """
    assert edge(0.07, 0.05) == pytest.approx(0.4)
    assert edge(0.52, 0.50) == pytest.approx(0.04)
    assert edge(0.5, 0.5) == pytest.approx(0.0)
    assert edge(0.4, 0.5) < 0
    assert edge(0.5, 0.0) == 0.0


def test_a_fair_book_matching_the_model_shows_no_edge() -> None:
    """
    The property the whole module exists for: if the model agrees with the market,
    the reported edge must be zero — not the book's margin.
    """
    model = _Model(home=0.50, draw=0.28, away=0.22)
    # Prices that de-vig to exactly the model's probabilities, plus a 6% margin.
    prices = {o: (1.0 / p) / 1.06 for o, p in (("home", 0.50), ("draw", 0.28), ("away", 0.22))}
    payload = build_match_markets(
        [{"match_id": "m1", "home": "Boca Juniors", "away": "River Plate",
          "books": {"a": prices}}],
        model,
    )
    fixture = payload["fixtures"][0]
    assert fixture["overround"] > 0.0, "test fixture should carry a margin"
    for outcome in ("home", "draw", "away"):
        assert fixture["edges"][outcome] == pytest.approx(0.0, abs=1e-6)
    assert fixture["actionable"] is False


def test_match_markets_flag_a_genuine_edge() -> None:
    model = _Model(home=0.60, draw=0.25, away=0.15)
    prices = {"home": 2.10, "draw": 3.40, "away": 3.60}   # market has home near 47%
    payload = build_match_markets(
        [{"match_id": "m1", "home": "Boca Juniors", "away": "River Plate",
          "books": {"a": prices}}],
        model,
    )
    fixture = payload["fixtures"][0]
    assert fixture["best_outcome"] == "home"
    assert fixture["best_edge"] > MIN_EDGE
    assert fixture["actionable"] is True
    assert payload["actionable"] == 1


def test_match_markets_sorted_by_edge_and_skip_unusable_rows() -> None:
    model = _Model()
    rows = [
        {"match_id": "a", "home": "Boca Juniors", "away": "River Plate",
         "books": {"x": {"home": 2.10, "draw": 3.40, "away": 3.60}}},
        {"match_id": "b", "home": "Racing Club", "away": "Independiente",
         "books": {"x": {"home": 1.40, "draw": 4.50, "away": 8.00}}},
        {"match_id": "c", "home": None, "away": "Talleres", "books": {}},   # unusable
        {"match_id": "d", "home": "Lanús", "away": "Tigre", "books": {}},   # no prices
    ]
    payload = build_match_markets(rows, model)
    assert len(payload["fixtures"]) == 2
    edges = [f["best_edge"] for f in payload["fixtures"]]
    assert edges == sorted(edges, reverse=True)


# ── outrights ────────────────────────────────────────────────────────────────

def test_outrights_absent_is_normal_not_an_error() -> None:
    """
    Whether Argentine league futures exist at all is unverified, so an empty market
    must produce a clean "unavailable" payload rather than raising.
    """
    payload = build_outright_markets({}, {"Boca Juniors": 0.2})
    assert payload["available"] is False
    assert payload["teams"] == []


def test_outrights_compare_against_the_simulation() -> None:
    """A realistic outright market prices the whole field, so it carries a margin."""
    prices = {
        "Boca Juniors": 3.5, "River Plate": 4.0, "Racing Club": 6.0,
        "Vélez Sarsfield": 9.0, "Estudiantes": 11.0, "Talleres": 13.0,
        "Independiente": 15.0, "San Lorenzo": 18.0, "Lanús": 22.0, "Huracán": 26.0,
    }
    model_probs = {
        "Boca Juniors": 0.30, "River Plate": 0.18, "Racing Club": 0.12,
        "Vélez Sarsfield": 0.09, "Estudiantes": 0.07, "Talleres": 0.06,
        "Independiente": 0.05, "San Lorenzo": 0.04, "Lanús": 0.03, "Huracán": 0.02,
    }
    payload = build_outright_markets(prices, model_probs)

    assert payload["available"] is True
    assert payload["overround"] > 0
    assert payload["field_complete"] is True
    assert len(payload["teams"]) == len(prices)
    edges = [t["edge"] for t in payload["teams"]]
    assert edges == sorted(edges, reverse=True)
    # Values are rounded to 5dp before summing, so 10 rows cannot agree tighter than 1e-5.
    assert sum(t["market"] for t in payload["teams"]) == pytest.approx(1.0, abs=1e-4)


def test_partial_outright_field_is_flagged() -> None:
    """
    Three of thirty runners implies a total well below 1, which inflates every
    de-vigged probability and makes each edge look better than it is. That must be
    surfaced, not silently priced.
    """
    payload = build_outright_markets(
        {"Boca Juniors": 4.0, "River Plate": 5.0, "Racing Club": 8.0},
        {"Boca Juniors": 0.35, "River Plate": 0.20, "Racing Club": 0.10},
    )
    assert payload["available"] is True
    assert payload["overround"] < 0
    assert payload["field_complete"] is False


def test_outrights_ignore_teams_the_model_does_not_know() -> None:
    payload = build_outright_markets(
        {"Boca Juniors": 4.0, "Some Other Club": 6.0}, {"Boca Juniors": 0.30}
    )
    assert [t["team"] for t in payload["teams"]] == ["Boca Juniors"]
