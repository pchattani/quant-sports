"""Data providers and cross-provider name normalisation."""
from oddsmarkets.football.sources.teams import (
    canonical_teams,
    normalize_team_name,
    INTERNATIONAL_ALIASES,
    LIGA_ARGENTINA_ALIASES,
    REGISTRIES,
)

__all__ = [
    "canonical_teams",
    "normalize_team_name",
    "INTERNATIONAL_ALIASES",
    "LIGA_ARGENTINA_ALIASES",
    "REGISTRIES",
]
