"""
World Cup data sources.

`normalize_team_name` is re-exported from the shared registry in
`oddsmarkets.football.sources.teams`, defaulting to the international registry.
Both `trading/the_odds_api.py` and `trading/betfair_fetcher.py` import it from here;
until now this module was empty, so importing either of them raised ImportError.
"""
from functools import partial

from oddsmarkets.football.sources.teams import normalize_team_name as _normalize

# World Cup callers deal in national teams.
normalize_team_name = partial(_normalize, registry="international")

__all__ = ["normalize_team_name"]
