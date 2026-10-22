"""
Market odds and model edge.

Bookmaker prices carry a margin — the implied probabilities of a three-way market sum
to more than 1, and the surplus is the book's cut. Comparing model probabilities to
raw implied odds would therefore show a systematic edge against every outcome, which
is an artefact rather than a finding. Everything here works on de-vigged prices.

Coverage caveat, deliberately built for rather than assumed away: whether Argentine
league *outright* markets exist is unverified — both Kalshi and The Odds API are
unreachable from the build sandbox. Match odds are near-certain to be available;
futures may not be. The payload therefore treats outrights as optional, and the
front-end hides that section when it is empty rather than showing a broken panel.
"""
from __future__ import annotations

import logging
from statistics import median

logger = logging.getLogger(__name__)

# Minimum edge worth surfacing. Below this, the difference is inside the noise of both
# the model and the price, and highlighting it would manufacture false signal.
MIN_EDGE = 0.03

OUTCOMES = ("home", "draw", "away")


def devig(prices: dict[str, float]) -> dict[str, float]:
    """
    Strip the bookmaker margin from a set of decimal odds.

    Multiplicative normalisation: convert to implied probabilities and rescale so they
    sum to 1. This assumes the margin is spread proportionally, which is the standard
    simplification — it slightly understates the favourite's true probability, but
    needs no extra parameters.
    """
    # imported here: oddsmarkets.common re-exports this module, so a top-level import would be circular
    from oddsmarkets.common.edge.devig import multiplicative_dict
    return multiplicative_dict(prices)          # common/edge/devig.py


def overround(prices: dict[str, float]) -> float:
    """
    The book's margin, as a fraction. 0.05 means a 5% overround.

    Only meaningful when the full field is priced. A partial outright market — three
    of thirty clubs, say — implies a total below 1 and returns a negative value, which
    reflects the missing runners rather than a book pricing below fair. Callers should
    treat a negative result as "field incomplete", not as free money.
    """
    implied = []
    for odds in prices.values():
        try:
            value = float(odds)
        except (TypeError, ValueError):
            continue
        if value > 1.0:
            implied.append(1.0 / value)
    return sum(implied) - 1.0 if implied else 0.0


def consensus(books: dict[str, dict[str, float]]) -> dict[str, float]:
    """
    Consensus fair probability across bookmakers.

    Median rather than mean, so one book with a stale or mispriced line cannot drag
    the consensus. Each book is de-vigged before being pooled — averaging raw prices
    would carry every book's margin into the result.
    """
    fair_by_book = [devig(prices) for prices in books.values()]
    fair_by_book = [f for f in fair_by_book if f]
    if not fair_by_book:
        return {}

    out = {}
    for outcome in OUTCOMES:
        values = [f[outcome] for f in fair_by_book if outcome in f]
        if values:
            out[outcome] = median(values)
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total > 0 else {}


def edge(model_prob: float, market_prob: float) -> float:
    """
    Model probability against the market's, as a fraction of the market's.

    Expressed relatively rather than as a raw difference because a 2-point gap means
    something very different at 5% than at 50%.
    """
    if not market_prob:
        return 0.0
    return model_prob / market_prob - 1.0


def build_match_markets(
    rows: list[dict],
    model,
    min_edge: float = MIN_EDGE,
    adjust: dict[str, dict[str, float]] | None = None,
) -> dict:
    """
    Compare model match probabilities against de-vigged bookmaker consensus.

    `rows` are per-fixture records shaped as The Odds API returns them once grouped:
    `{match_id, home, away, commence, books: {book_key: {home, draw, away}}}` with
    decimal odds. `adjust` (match_id -> {home, draw, away}) replaces the model's line
    for those fixtures: the line after the confirmed line-ups (docs/MODELS.md 2.6).
    """
    fixtures = []
    for row in rows:
        home, away = row.get("home"), row.get("away")
        if not home or not away:
            continue
        books = row.get("books") or {}
        market = consensus(books)
        if not market:
            continue

        try:
            probs = model.predict(home, away, neutral=False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("model prediction failed for %s v %s: %s", home, away, exc)
            continue

        model_probs = {
            "home": probs.home_win, "draw": probs.draw, "away": probs.away_win,
        }
        adj = (adjust or {}).get(str(row.get("match_id")))
        if adj:
            model_probs = {o: float(adj[o]) for o in OUTCOMES}
        total = sum(model_probs.values())
        if total <= 0:
            continue
        model_probs = {k: v / total for k, v in model_probs.items()}

        edges = {
            o: round(edge(model_probs[o], market.get(o, 0.0)), 4)
            for o in OUTCOMES if o in market
        }
        best = max(edges, key=lambda o: edges[o]) if edges else None

        fixtures.append({
            "match_id": row.get("match_id") or f"{home}-{away}",
            "home": home, "away": away,
            "commence": row.get("commence"),
            "books": len(books),
            "overround": round(
                median([overround(p) for p in books.values()]) if books else 0.0, 4
            ),
            "model": {o: round(model_probs[o], 4) for o in OUTCOMES},
            "market": {o: round(v, 4) for o, v in market.items()},
            "edges": edges,
            "best_outcome": best,
            "best_edge": edges.get(best, 0.0) if best else 0.0,
            "actionable": bool(best and edges[best] >= min_edge),
            **({"lineups": True} if adj else {}),
        })

    fixtures.sort(key=lambda f: -f["best_edge"])
    return {
        "min_edge": min_edge,
        "fixtures": fixtures,
        "actionable": sum(1 for f in fixtures if f["actionable"]),
    }


def build_outright_markets(
    prices: dict[str, float],
    model_probs: dict[str, float],
    min_edge: float = MIN_EDGE,
) -> dict:
    """
    Title-winner market against the simulation, when such a market exists.

    Returns an empty payload rather than raising when it does not — this is the case
    the coverage caveat above is about, and an absent market is normal, not an error.
    """
    fair = devig(prices) if prices else {}
    if not fair:
        return {"available": False, "teams": []}

    teams = []
    for team, market_prob in fair.items():
        model_prob = model_probs.get(team)
        if model_prob is None:
            continue
        e = edge(model_prob, market_prob)
        teams.append({
            "team": team,
            "model": round(model_prob, 5),
            "market": round(market_prob, 5),
            "edge": round(e, 4),
            "actionable": e >= min_edge,
        })
    teams.sort(key=lambda t: -t["edge"])
    raw_overround = overround(prices)
    return {
        "available": True,
        "min_edge": min_edge,
        "overround": round(raw_overround, 4),
        # A negative overround means runners are missing from the quoted field, so the
        # de-vigged probabilities are inflated across the board and every edge computed
        # against them is optimistic. Flag it rather than presenting the numbers plainly.
        "field_complete": raw_overround >= 0,
        "teams": teams,
    }
