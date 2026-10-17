"""
Competition-agnostic models.

These currently live under `oddsmarkets.sports.world_cup.models` for historical
reasons and are re-exported here, which is the namespace new code should import
from. The files move to this package during the repository rename; importing via
`oddsmarkets.football.core` now means that move will not require touching callers.
"""
from oddsmarkets.sports.world_cup.models.dixon_coles import (
    DixonColesModel,
    MatchProbabilities,
)
from oddsmarkets.sports.world_cup.models.elo import EloRatings
from oddsmarkets.sports.world_cup.models.ensemble import EnsembleModel
from oddsmarkets.sports.world_cup.models.player_goals import GoldenBootModel
from oddsmarkets.football.core import markets  # noqa: F401

__all__ = [
    "DixonColesModel",
    "MatchProbabilities",
    "EloRatings",
    "EnsembleModel",
    "GoldenBootModel",
    "markets",
]
