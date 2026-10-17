"""
The Odds API fetcher — aggregates decimal odds from 70+ bookmakers.
https://the-odds-api.com

For Canadian users, use regions=ca to get:
  BetMGM, DraftKings (ON), FanDuel, Bet365, Sports Interaction
All licensed under Ontario's AGCO framework (Bill C-218, 2021).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from oddsmarkets.sports.world_cup.data import normalize_team_name

logger = logging.getLogger(__name__)

_BASE = "https://api.the-odds-api.com/v4"

# Soccer World Cup sport key on The Odds API
WC_SPORT = "soccer_fifa_world_cup"

# Bookmakers accessible to Canadian residents
CANADIAN_BOOKMAKERS = {
    "betmgm",
    "draftkings",
    "fanduel",
    "bet365",
    "sportsinteraction",
    "pinnacle",    # offshore, sharp reference line
    "betrivers",
    "pointsbet",
    "caesars",
}


class TheOddsAPIFetcher:
    """
    Async fetcher for The Odds API.
    Fetches match winner (h2h) and outright odds for World Cup 2026.
    """

    def __init__(self, api_key: str, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.api_key = api_key
        self._session = session
        self._own_session = session is None

    async def __aenter__(self) -> "TheOddsAPIFetcher":
        if self._own_session:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._own_session and self._session:
            await self._session.close()

    async def fetch_events(self, sport: str = WC_SPORT) -> list[dict]:
        """Fetch upcoming event list (no odds, just event IDs and teams)."""
        data = await self._get(f"/sports/{sport}/events", {})
        return data if isinstance(data, list) else []

    async def fetch_match_odds(
        self,
        sport: str = WC_SPORT,
        regions: str = "eu,uk",
    ) -> list[dict]:
        """
        Fetch h2h odds for all upcoming WC matches.
        Returns flat list of exchange_odds-compatible dicts.
        """
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
        data = await self._get(f"/sports/{sport}/odds", params)
        if not isinstance(data, list):
            return []

        now = datetime.now(timezone.utc)
        rows = []
        for event in data:
            match_id = self._event_to_match_id(event)
            for bookmaker in event.get("bookmakers", []):
                book_key = bookmaker.get("key", "")
                if book_key not in CANADIAN_BOOKMAKERS:
                    continue
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    outcomes = market.get("outcomes", [])
                    if len(outcomes) < 2:
                        continue
                    # Map names to home/draw/away
                    home = normalize_team_name(event.get("home_team", ""))
                    away = normalize_team_name(event.get("away_team", ""))
                    for outcome in outcomes:
                        name = outcome.get("name", "")
                        price = outcome.get("price", 0.0)
                        if price <= 1.0:
                            continue
                        if name == event.get("home_team"):
                            outcome_key = "home"
                        elif name == event.get("away_team"):
                            outcome_key = "away"
                        elif name.lower() in ("draw", "tie"):
                            outcome_key = "draw"
                        else:
                            outcome_key = normalize_team_name(name)

                        rows.append({
                            "match_id":    match_id,
                            "platform":    "the_odds_api",
                            "market_type": "match_winner",
                            "outcome":     outcome_key,
                            "decimal_odds": float(price),
                            "implied_prob": round(1.0 / float(price), 5),
                            "bookmaker":   book_key,
                            "captured_at": now,
                        })
        return rows

    async def fetch_outright_odds(
        self,
        sport: str = WC_SPORT,
        regions: str = "eu,uk",
    ) -> list[dict]:
        """Fetch tournament winner outright odds."""
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": "outrights",
            "oddsFormat": "decimal",
        }
        data = await self._get(f"/sports/{sport}/odds", params)
        if not isinstance(data, list):
            return []

        now = datetime.now(timezone.utc)
        rows = []
        for event in data:
            for bookmaker in event.get("bookmakers", []):
                if bookmaker.get("key") not in CANADIAN_BOOKMAKERS:
                    continue
                for market in bookmaker.get("markets", []):
                    if market.get("key") != "outrights":
                        continue
                    for outcome in market.get("outcomes", []):
                        price = outcome.get("price", 0.0)
                        if price <= 1.0:
                            continue
                        team = normalize_team_name(outcome.get("name", ""))
                        rows.append({
                            "match_id":    "outright_tournament_winner",
                            "platform":    "the_odds_api",
                            "market_type": "tournament_winner",
                            "outcome":     team,
                            "decimal_odds": float(price),
                            "implied_prob": round(1.0 / float(price), 5),
                            "bookmaker":   bookmaker.get("key"),
                            "captured_at": now,
                        })
        return rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _event_to_match_id(self, event: dict) -> str:
        home = normalize_team_name(event.get("home_team", ""))
        away = normalize_team_name(event.get("away_team", ""))
        commence = event.get("commence_time", "")
        try:
            dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            date_str = dt.date().isoformat()
        except Exception:
            date_str = "unknown"
        return f"{home}_{away}_{date_str}"

    async def _get(self, path: str, params: dict) -> object:
        url = _BASE + path
        if "apiKey" not in params:
            params = {**params, "apiKey": self.api_key}
        for attempt in range(4):
            try:
                async with self._session.get(url, params=params) as resp:  # type: ignore[union-attr]
                    if resp.status == 429:
                        wait = 2 ** attempt * 5
                        logger.warning("The Odds API rate limit, retrying in %ds", wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
            except aiohttp.ClientResponseError as exc:
                logger.error("The Odds API error %d: %s", exc.status, exc.message)
                raise
        return []
