"""
De-vig and consensus, shared across sports.

Re-exports the football implementation unchanged (`oddsmarkets.football.core.markets`):

    devig(prices)        decimal odds o_i -> fair p_i = (1/o_i) / sum_j (1/o_j)   (multiplicative de-vig)
    overround(prices)    sum_i (1/o_i) - 1                                      (negative = field incomplete)
    consensus(books)     median of each book's de-vigged home/draw/away, renormalised (three-way markets only)
    edge(model, market)  model / market - 1
    build_outright_markets(prices, model_probs)

and adds `consensus_field`, the field-market (many runners) analogue of `consensus`.
"""
from __future__ import annotations

from statistics import median

from oddsmarkets.football.core.markets import (  # noqa: F401
    MIN_EDGE,
    build_match_markets,
    build_outright_markets,
    consensus,
    devig,
    edge,
    overround,
)


def consensus_field(books: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    Consensus fair probability for a many-runner market (a title or a race winner).

    Each book is a `{runner: decimal_odds}` map; each is de-vigged on its own
    (p_i = (1/o_i) / sum_j 1/o_j), then each runner's fair probability is the
    median across the books that price it, and the result is renormalised to sum
    to one. Runners missing from a book are not treated as zero.
    """
    fair = [f for f in (devig(p) for p in books.values()) if f]
    if not fair:
        return {}
    runners = {r for f in fair for r in f}
    out = {r: median([f[r] for f in fair if r in f]) for r in runners}
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total > 0 else {}
