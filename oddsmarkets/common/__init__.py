"""
Sport-neutral helpers shared by the football and F1 sites.

    oddsmarkets.common.markets             de-vig, overround, consensus, edge (re-exported from football)
    oddsmarkets.common.prediction_markets  Kalshi / Polymarket fetchers, quote midpoints, name matching
    oddsmarkets.common.ranking             Plackett-Luce ranking model (fit, probabilities, sampling)

The football implementations remain the source of truth; this package re-exports
them so football behaviour cannot drift, and adds helpers that take a Kalshi
series ticker or a Polymarket slug instead of a football competition slug.
"""
from oddsmarkets.common.markets import consensus, consensus_field, devig, edge, overround  # noqa: F401
from oddsmarkets.common.prediction_markets import (  # noqa: F401
    _get,
    _mid,
    best_match,
    fold,
    kalshi_events,
    kalshi_price,
    poly_price,
    polymarket_event,
    polymarket_search,
)
