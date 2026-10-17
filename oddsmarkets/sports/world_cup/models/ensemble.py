"""
Ensemble model combining Dixon-Coles and Elo for World Cup 2026 predictions.

Weighting rationale:
- Dixon-Coles (70%) is more accurate for teams with rich recent match data
- Elo (30%) provides stable prior for first-time qualifiers / teams with sparse xG data
- Elo weight increases when Dixon-Coles team has fewer than 5 training matches
"""
from __future__ import annotations

import logging

from oddsmarkets.sports.world_cup.models.dixon_coles import DixonColesModel, MatchProbabilities
from oddsmarkets.sports.world_cup.models.elo import EloRatings

logger = logging.getLogger(__name__)

# Historical WC group-stage draw rate (used to split Elo "non-home-win" probability)
WC_DRAW_RATE = 0.25   # ~25% of WC group-stage matches end in a draw

# Scale converting an Elo win probability into an expected goal count on the
# Elo-only fallback path: at p=0.5 each side is expected to score LAM_SCALE/2.
# 2.6 reflects World Cup scoring; leagues should pass twice their observed mean
# goals per team per match.
WC_LAM_SCALE = 2.6

# Multiplier applied to the away side's lambda on the Elo-only path for non-neutral
# fixtures. This is a crude stand-in for home advantage; models that carry a real
# home-advantage term should pass 1.0 so the asymmetry is not applied twice.
WC_AWAY_PENALTY = 0.75


class EnsembleModel:
    """
    Combines Dixon-Coles score-matrix probabilities with Elo-derived win probability.

    `draw_rate`, `lam_scale` and `away_penalty` default to the World Cup calibration.
    Domestic leagues should pass empirical values — Argentine top-flight football, for
    instance, is both lower-scoring and more draw-heavy than World Cup group play.
    """

    def __init__(
        self,
        dc_model: DixonColesModel,
        elo: EloRatings,
        dc_weight: float = 0.70,
        draw_rate: float = WC_DRAW_RATE,
        lam_scale: float = WC_LAM_SCALE,
        away_penalty: float = WC_AWAY_PENALTY,
    ) -> None:
        self.dc = dc_model
        self.elo = elo
        self.dc_weight = dc_weight
        self.elo_weight = 1.0 - dc_weight
        self.draw_rate = draw_rate
        self.lam_scale = lam_scale
        self.away_penalty = away_penalty

    def _elo_lambdas(self, elo_p_home: float, neutral: bool) -> tuple[float, float]:
        """Expected goals for each side derived from an Elo win probability."""
        away_adj = 1.0 if neutral else self.away_penalty
        lam_h = max(elo_p_home * self.lam_scale, 0.3)
        lam_a = max((1 - elo_p_home) * self.lam_scale * away_adj, 0.3)
        return lam_h, lam_a

    def predict(
        self,
        home: str,
        away: str,
        neutral: bool = True,
        max_goals: int = 8,
    ) -> MatchProbabilities:
        """
        Blend Dixon-Coles and Elo predictions.
        Returns a MatchProbabilities with ensemble win/draw/loss probs
        but the Dixon-Coles score matrix (more granular and useful for
        exact-score markets).
        """
        # Determine effective DC weight before attempting DC prediction
        dc_w = self._adaptive_dc_weight(home, away)
        elo_w = 1.0 - dc_w

        elo_p_home, elo_p_away_or_draw = self.elo.expected_outcome(home, away, neutral=neutral)
        elo_draw = elo_p_away_or_draw * self.draw_rate
        elo_away = elo_p_away_or_draw * (1.0 - self.draw_rate)

        if dc_w == 0.0 or not self.dc.is_fitted:
            # Elo-only path — build a Poisson score matrix from Elo-derived lambdas.
            # For neutral matches there is no away-team penalty; it only applies to
            # genuine home/away fixtures.
            import numpy as np
            from math import factorial
            lam_h, lam_a = self._elo_lambdas(elo_p_home, neutral)
            k = max_goals + 1
            k_arr = np.arange(k, dtype=np.float64)
            facts = np.array([factorial(i) for i in range(k)], dtype=np.float64)
            ph = np.exp(-lam_h) * np.power(lam_h, k_arr) / facts
            pa = np.exp(-lam_a) * np.power(lam_a, k_arr) / facts
            score_matrix = np.outer(ph, pa)
            score_matrix /= score_matrix.sum()
            # Derive W/D/L directly from the Poisson score matrix — never clamps to zero.
            # (The old linear formula max(p_h - d/2, 0) wrongly assigned 0% upset probability
            # to any matchup where elo_p_home > 0.875, e.g. Argentina vs Saudi Arabia.)
            home_win = float(np.tril(score_matrix, -1).sum())
            draw     = float(np.trace(score_matrix))
            away_win = float(np.triu(score_matrix, 1).sum())
            return MatchProbabilities(
                home_win=home_win,
                draw=draw,
                away_win=away_win,
                lambda_home=lam_h,
                lambda_away=lam_a,
                score_matrix=score_matrix,
            )

        dc_probs = self.dc.predict_match(home, away, neutral=neutral, max_goals=max_goals)

        h = dc_w * dc_probs.home_win + elo_w * elo_p_home
        d = dc_w * dc_probs.draw + elo_w * elo_draw
        a = dc_w * dc_probs.away_win + elo_w * elo_away

        total = h + d + a

        # Blend score matrices so the simulator samples goals consistently with
        # the blended win/draw/loss probabilities.  The Elo-only path (dc_w==0)
        # already builds its own Poisson matrix above; here we only need to blend
        # when 0 < elo_w < 1.
        if elo_w > 0:
            import numpy as np
            from math import factorial
            lam_h_e, lam_a_e = self._elo_lambdas(elo_p_home, neutral)
            k = max_goals + 1
            k_arr = np.arange(k, dtype=np.float64)
            facts = np.array([factorial(i) for i in range(k)], dtype=np.float64)
            ph = np.exp(-lam_h_e) * np.power(lam_h_e, k_arr) / facts
            pa = np.exp(-lam_a_e) * np.power(lam_a_e, k_arr) / facts
            elo_matrix = np.outer(ph, pa)
            elo_matrix /= elo_matrix.sum()
            blended_matrix = dc_w * dc_probs.score_matrix + elo_w * elo_matrix
            blended_matrix = np.maximum(blended_matrix, 0.0)
            blended_matrix /= blended_matrix.sum()
        else:
            blended_matrix = dc_probs.score_matrix

        return MatchProbabilities(
            home_win=h / total,
            draw=d / total,
            away_win=a / total,
            lambda_home=dc_probs.lambda_home,
            lambda_away=dc_probs.lambda_away,
            score_matrix=blended_matrix,
        )

    def _adaptive_dc_weight(self, home: str, away: str) -> float:
        """Reduce DC weight if either team has no training data or model hasn't converged."""
        if not self.dc.is_fitted:
            return 0.0

        # Only fall back to Elo-only if rho is literally at the hard L-BFGS-B bound (-0.99),
        # meaning the optimizer hit the wall and the DC fit is degenerate.
        # With L2 regularization this should not occur in normal operation.
        rho = self.dc.params_.get("rho", 0.0)
        if abs(rho) >= 0.99:
            logger.warning(
                "DC rho=%.4f at hard bound — falling back to Elo-only for %s vs %s",
                rho, home, away,
            )
            return 0.0

        home_has_data = f"attack_{home}" in self.dc.params_
        away_has_data = f"attack_{away}" in self.dc.params_
        if not home_has_data or not away_has_data:
            return max(self.dc_weight - 0.30, 0.40)
        return self.dc_weight
