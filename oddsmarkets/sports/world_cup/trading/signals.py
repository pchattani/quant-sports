"""
Value signal detection and Kelly sizing for World Cup betting markets.
Compares model probabilities against market-implied fair odds to identify edges.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from oddsmarkets.sports.world_cup.models.dixon_coles import MatchProbabilities
from oddsmarkets.sports.world_cup.trading.simulator import SimulationResults

logger = logging.getLogger(__name__)


@dataclass
class ValueSignal:
    match_id: str
    detected_at: datetime
    model_version: str
    platform: str
    market_type: str
    outcome: str
    model_prob: float
    market_prob: float        # fair probability after margin removal
    decimal_odds: float       # raw decimal odds from exchange
    raw_edge: float           # model_prob / market_prob - 1
    kelly_fraction: float     # full Kelly
    half_kelly: float         # recommended bet size fraction
    status: str = "open"


class ValueSignalDetector:
    """
    Detects value bets by comparing model probabilities against exchange odds.
    Uses multiplicative normalization (Shin-equivalent) for margin removal.
    """

    def __init__(self, model_version: str, min_edge: float = 0.03, kelly_cap: float = 0.10) -> None:
        self.model_version = model_version
        self.min_edge = min_edge
        self.kelly_cap = kelly_cap

    def detect_match_signals(
        self,
        match_id: str,
        model_probs: MatchProbabilities,
        exchange_odds: list[dict],
        market_type: str = "match_winner",
    ) -> list[ValueSignal]:
        """
        Detect value in a 3-way match winner market.
        exchange_odds: list of dicts with keys: outcome, decimal_odds, platform
        outcomes: "home", "draw", "away"
        """
        if not exchange_odds:
            return []

        # Build outcome -> best available decimal odds per platform
        best_by_outcome: dict[str, dict] = {}
        for od in exchange_odds:
            outcome = od.get("outcome", "").lower()
            dec = od.get("decimal_odds", 0.0)
            if dec <= 1.0:
                continue
            if outcome not in best_by_outcome or dec > best_by_outcome[outcome]["decimal_odds"]:
                best_by_outcome[outcome] = od

        if len(best_by_outcome) < 2:
            return []

        # Margin removal via multiplicative normalization
        raw_implied = {o: 1.0 / d["decimal_odds"] for o, d in best_by_outcome.items()}
        total_implied = sum(raw_implied.values())
        if total_implied <= 0:
            return []
        fair_probs = {o: p / total_implied for o, p in raw_implied.items()}

        model_map = {
            "home": model_probs.home_win,
            "draw": model_probs.draw,
            "away": model_probs.away_win,
        }

        signals = []
        for outcome, fair_prob in fair_probs.items():
            model_prob = model_map.get(outcome)
            if model_prob is None or fair_prob <= 0:
                continue

            edge = model_prob / fair_prob - 1.0
            if edge < self.min_edge:
                continue

            od = best_by_outcome[outcome]
            dec_odds = od["decimal_odds"]
            b = dec_odds - 1.0
            kelly = (b * model_prob - (1.0 - model_prob)) / b
            kelly = max(0.0, min(kelly, self.kelly_cap))

            signals.append(ValueSignal(
                match_id=match_id,
                detected_at=datetime.now(timezone.utc),
                model_version=self.model_version,
                platform=od.get("platform", "unknown"),
                market_type=market_type,
                outcome=outcome,
                model_prob=round(model_prob, 4),
                market_prob=round(fair_prob, 4),
                decimal_odds=round(dec_odds, 3),
                raw_edge=round(edge, 4),
                kelly_fraction=round(kelly, 4),
                half_kelly=round(kelly / 2, 4),
            ))

        return signals

    def detect_outright_signals(
        self,
        sim_results: SimulationResults,
        outright_odds: list[dict],
        market_type: str = "tournament_winner",
        model_prob_key: str = "p_win_tournament",
    ) -> list[ValueSignal]:
        """
        Detect value in outright (tournament winner / reach final / etc.) markets.
        outright_odds: list of dicts with keys: team, decimal_odds, platform
        model_prob_key: attribute on SimulationResults to read probabilities from
        """
        if not outright_odds:
            return []

        model_probs_dict: dict[str, float] = getattr(sim_results, model_prob_key, {})

        # Margin removal across all outright outcomes
        valid = [(od, 1.0 / od["decimal_odds"]) for od in outright_odds if od.get("decimal_odds", 0) > 1.0]
        if not valid:
            return []
        total_implied = sum(ip for _, ip in valid)
        if total_implied <= 0:
            return []

        signals = []
        for od, raw_implied in valid:
            team = od.get("outcome") or od.get("team", "")
            fair_prob = raw_implied / total_implied
            model_prob = model_probs_dict.get(team, 0.0)
            if model_prob <= 0 or fair_prob <= 0:
                continue

            edge = model_prob / fair_prob - 1.0
            if edge < self.min_edge:
                continue

            dec_odds = od["decimal_odds"]
            b = dec_odds - 1.0
            kelly = (b * model_prob - (1.0 - model_prob)) / b
            kelly = max(0.0, min(kelly, self.kelly_cap))

            signals.append(ValueSignal(
                match_id=f"outright_{market_type}",
                detected_at=datetime.now(timezone.utc),
                model_version=self.model_version,
                platform=od.get("platform", "unknown"),
                market_type=market_type,
                outcome=team,
                model_prob=round(model_prob, 4),
                market_prob=round(fair_prob, 4),
                decimal_odds=round(dec_odds, 3),
                raw_edge=round(edge, 4),
                kelly_fraction=round(kelly, 4),
                half_kelly=round(kelly / 2, 4),
            ))

        return signals
