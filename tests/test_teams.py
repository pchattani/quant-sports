"""
Tests for cross-provider team-name normalisation.

A failed name join is silent — the team is dropped from a merge and the dashboard
shows a gap rather than an error — so these cases are worth pinning explicitly.
"""
from __future__ import annotations

import pytest

from oddsmarkets.football.sources.teams import (
    canonical_teams,
    normalize_team_name,
    LIGA_ARGENTINA_ALIASES,
)


def test_broken_import_is_fixed() -> None:
    """
    Regression guard: `world_cup/data/__init__.py` was empty, so importing either
    odds fetcher raised ImportError. Both must import cleanly.
    """
    import oddsmarkets.sports.world_cup.trading.the_odds_api as odds
    import oddsmarkets.sports.world_cup.trading.betfair_fetcher as betfair

    assert odds.WC_SPORT == "soccer_fifa_world_cup"
    assert betfair.SOCCER_EVENT_TYPE_ID == "1"

    from oddsmarkets.sports.world_cup.data import normalize_team_name as wc_normalize
    assert wc_normalize("Türkiye") == "Turkey"


@pytest.mark.parametrize("raw,expected", [
    ("United States", "USA"),
    ("Côte d'Ivoire", "Ivory Coast"),
    ("Cote d'Ivoire", "Ivory Coast"),
    ("Türkiye", "Turkey"),
    ("Korea Republic", "South Korea"),
    ("Czechia", "Czech Republic"),
    ("Bosnia and Herzegovina", "Bosnia-Herzegovina"),
])
def test_international_aliases(raw: str, expected: str) -> None:
    assert normalize_team_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("CA Boca Juniors", "Boca Juniors"),
    ("Boca Jrs", "Boca Juniors"),
    ("CA River Plate", "River Plate"),
    ("Belgrano de Córdoba", "Belgrano"),
    ("Belgrano Cordoba", "Belgrano"),
    ("Newells Old Boys", "Newell's Old Boys"),
    ("Gimnasia y Esgrima La Plata", "Gimnasia LP"),
    ("Estudiantes de La Plata", "Estudiantes"),
])
def test_liga_aliases(raw: str, expected: str) -> None:
    assert normalize_team_name(raw, "liga_argentina") == expected


@pytest.mark.parametrize("raw", [
    "Vélez Sarsfield", "Velez Sarsfield", "CA Vélez Sarsfield", "CA Velez Sarsfield",
])
def test_accent_and_prefix_folding(raw: str) -> None:
    """Accent, case and punctuation variants must not each need their own entry."""
    assert normalize_team_name(raw, "liga_argentina") == "Vélez Sarsfield"


def test_canonical_names_are_idempotent() -> None:
    """Normalising an already-canonical name must be a no-op, or repeated passes drift."""
    for canonical in canonical_teams("liga_argentina"):
        assert normalize_team_name(canonical, "liga_argentina") == canonical
    for canonical in canonical_teams("international"):
        assert normalize_team_name(canonical) == canonical


def test_unknown_names_pass_through() -> None:
    """A provider adding an unseen team should degrade to a missing join, not a crash."""
    assert normalize_team_name("Some New Club", "liga_argentina") == "Some New Club"
    assert normalize_team_name("") == ""


def test_registries_are_separate_namespaces() -> None:
    """
    National and club names must not share a namespace. "Argentina" the country has
    nothing to do with Argentine clubs, and resolving it through the club registry
    must not invent a match.
    """
    assert normalize_team_name("Argentina") == "Argentina"
    assert normalize_team_name("Argentina", "liga_argentina") == "Argentina"


def test_colliding_club_names_stay_distinct() -> None:
    """
    Argentine club naming is full of near-collisions. These pairs must never
    collapse into each other — that would silently merge two clubs' results.
    """
    liga = "liga_argentina"
    assert normalize_team_name("Independiente", liga) != normalize_team_name(
        "Independiente Rivadavia", liga
    )
    assert normalize_team_name("Estudiantes de La Plata", liga) != normalize_team_name(
        "Deportivo Estudiantes Río Cuarto", liga
    )
    assert normalize_team_name("Central Córdoba", liga) != normalize_team_name(
        "Rosario Central", liga
    )
    assert normalize_team_name("San Lorenzo", liga) != normalize_team_name(
        "San Martín SJ", liga
    )


def test_explicit_registry_mapping_accepted() -> None:
    """A caller may pass its own alias table rather than a registry name."""
    assert normalize_team_name("Foo FC", {"Foo FC": "Foo"}) == "Foo"


def test_no_alias_maps_to_another_alias_key() -> None:
    """
    An alias whose target is itself an alias key would make results depend on how
    many times you normalise. Catch that at test time rather than in production.
    """
    keys = set(LIGA_ARGENTINA_ALIASES)
    for alias, canonical in LIGA_ARGENTINA_ALIASES.items():
        assert canonical not in keys, f"{alias!r} -> {canonical!r}, which is itself an alias"
