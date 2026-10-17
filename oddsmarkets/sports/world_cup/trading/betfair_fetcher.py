"""
Betfair Exchange fetcher using betfairlightweight.
Betfair is accessible to Canadian residents under its Gibraltar/UK license.

Commission model: 5% on net winnings per market per day.
Best for in-play trading and getting true exchange back/lay prices.

Setup:
  1. Register at betfair.com (Canadian residents accepted)
  2. Create an application key at https://developer.betfair.com
  3. For non-interactive login (production), obtain a client SSL certificate
  4. For development, use interactive login (BETFAIR_USERNAME/PASSWORD)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from oddsmarkets.sports.world_cup.data import normalize_team_name

logger = logging.getLogger(__name__)

# Betfair event type ID for Soccer
SOCCER_EVENT_TYPE_ID = "1"

# Betfair market type codes we care about
MARKET_TYPES = ["MATCH_ODDS", "NEXT_GOAL", "BOTH_TEAMS_TO_SCORE"]
OUTRIGHT_MARKET_TYPES = ["WINNER", "TO_BE_PLACED"]


class BetfairFetcher:
    """
    Wraps betfairlightweight to fetch World Cup exchange markets.
    Requires: pip install betfairlightweight>=3.10
    """

    def __init__(self, username: str, password: str, app_key: str) -> None:
        self.username = username
        self.password = password
        self.app_key = app_key
        self._client: Optional[object] = None

    def _ensure_client(self) -> object:
        """Lazy-init the betfairlightweight client."""
        if self._client is None:
            try:
                import betfairlightweight
                self._client = betfairlightweight.APIClient(
                    username=self.username,
                    password=self.password,
                    app_key=self.app_key,
                )
                self._client.login()  # type: ignore[attr-defined]
                logger.info("Betfair login successful.")
            except ImportError:
                raise ImportError(
                    "betfairlightweight not installed. Run: pip install betfairlightweight>=3.10"
                )
            except Exception as exc:
                logger.error("Betfair login failed: %s", exc)
                raise
        return self._client

    def fetch_wc_events(self) -> list[dict]:
        """Fetch World Cup events (competition ID ~football events named 'World Cup')."""
        client = self._ensure_client()
        try:
            events = client.betting.list_events(  # type: ignore[attr-defined]
                filter=client.betting.market_filter(  # type: ignore[attr-defined]
                    event_type_ids=[SOCCER_EVENT_TYPE_ID],
                    text_query="World Cup",
                )
            )
            return [
                {
                    "event_id": e.event.id,
                    "event_name": e.event.name,
                    "country": getattr(e.event, "country_code", None),
                    "open_date": e.event.open_date,
                }
                for e in events
            ]
        except Exception as exc:
            logger.error("Betfair fetch_wc_events failed: %s", exc)
            return []

    def fetch_market_catalogue(self, event_ids: list[str]) -> list[dict]:
        """Fetch market metadata for given events."""
        client = self._ensure_client()
        if not event_ids:
            return []
        try:
            markets = client.betting.list_market_catalogue(  # type: ignore[attr-defined]
                filter=client.betting.market_filter(  # type: ignore[attr-defined]
                    event_ids=event_ids,
                    market_type_codes=MARKET_TYPES,
                ),
                market_projection=["RUNNER_DESCRIPTION", "MARKET_START_TIME", "EVENT"],
                max_results=100,
            )
            return [
                {
                    "market_id":   m.market_id,
                    "market_name": m.market_name,
                    "market_type": getattr(m, "market_type", None),
                    "start_time":  m.market_start_time,
                    "runners":     [
                        {"runner_id": r.selection_id, "name": normalize_team_name(r.runner_name)}
                        for r in (m.runners or [])
                    ],
                }
                for m in markets
            ]
        except Exception as exc:
            logger.error("Betfair fetch_market_catalogue failed: %s", exc)
            return []

    def fetch_market_book(self, market_ids: list[str]) -> list[dict]:
        """
        Fetch best 3 back/lay prices for given market IDs.
        Returns exchange_odds-compatible rows.
        """
        client = self._ensure_client()
        if not market_ids:
            return []
        try:
            import betfairlightweight.resources.bettingresources as br
            books = client.betting.list_market_book(  # type: ignore[attr-defined]
                market_ids=market_ids,
                price_projection={"priceData": ["EX_BEST_OFFERS"]},
            )
            now = datetime.now(timezone.utc)
            rows = []
            for book in books:
                for runner in (book.runners or []):
                    best_back = runner.ex.available_to_back
                    if best_back:
                        best_price = best_back[0].price
                        rows.append({
                            "match_id":    book.market_id,
                            "platform":    "betfair",
                            "market_type": "match_winner",
                            "outcome":     normalize_team_name(
                                getattr(runner, "runner_name", str(runner.selection_id))
                            ),
                            "decimal_odds": float(best_price),
                            "implied_prob": round(1.0 / float(best_price), 5) if best_price > 1 else 0.0,
                            "bookmaker":   "betfair_exchange",
                            "captured_at": now,
                        })
            return rows
        except Exception as exc:
            logger.error("Betfair fetch_market_book failed: %s", exc)
            return []

    def keep_alive(self) -> None:
        """Refresh the Betfair session (call every 20 minutes to prevent timeout)."""
        if self._client is not None:
            try:
                self._client.keep_alive()  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("Betfair keep_alive failed: %s", exc)
                self._client = None  # force re-login on next call
