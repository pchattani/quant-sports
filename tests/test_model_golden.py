"""
Golden-output guard for the shared model layer.

The World Cup site is served from a public Pages repo fed by `scripts/build_site_wc.py`.
Its models (`DixonColesModel`, `EloRatings`, `EnsembleModel`) are now shared with other
competitions, so every generalisation must be *additive*: new keyword arguments whose
defaults reproduce the existing behaviour exactly.

These tests pin that contract. They are deterministic and offline — a synthetic fixture
league is fitted with a fixed seed, and the resulting probabilities are compared against
values captured before the shared-model changes. If a refactor shifts WC output at all,
these fail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.sports.world_cup.models.dixon_coles import DixonColesModel
from oddsmarkets.sports.world_cup.models.elo import EloRatings
from oddsmarkets.sports.world_cup.models.ensemble import EnsembleModel

TEAMS = ["Argentina", "Brazil", "France", "Germany", "Japan", "Morocco"]

# Attack/defence strengths used to generate the fixture results, so the fit has
# a real signal to recover rather than noise.
_STRENGTH = {
    "Argentina": 1.7, "Brazil": 1.6, "France": 1.55,
    "Germany": 1.3, "Japan": 1.0, "Morocco": 0.9,
}


# The date the golden values in this file were captured (commit 41244bb).
_GOLDEN_AS_OF = pd.Timestamp("2026-08-18", tz="UTC").to_pydatetime()


def _fixture_matches() -> pd.DataFrame:
    """Deterministic synthetic double round-robin with Poisson scorelines."""
    rng = np.random.default_rng(20260818)
    base = pd.Timestamp("2025-01-01", tz="UTC")
    rows = []
    day = 0
    for _ in range(4):  # four passes, so each ordered pair appears several times
        for home in TEAMS:
            for away in TEAMS:
                if home == away:
                    continue
                day += 3
                lam_h = _STRENGTH[home] / _STRENGTH[away]
                lam_a = _STRENGTH[away] / _STRENGTH[home]
                rows.append({
                    "home_team": home,
                    "away_team": away,
                    "home_goals": int(rng.poisson(lam_h)),
                    "away_goals": int(rng.poisson(lam_a)),
                    "match_date": base + pd.Timedelta(days=day),
                    "weight": 1.0,
                })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def fitted_dc() -> DixonColesModel:
    dc = DixonColesModel(ridge=1.0)
    # The decay weights are measured from `as_of`. Left at its default (now), they all
    # shrink by exp(-xi) a day against the fixed ridge penalty, so the fit moved by
    # about 3e-5 a day and the golden values below went stale on their own. Pin it to
    # the date they were captured.
    dc.fit(_fixture_matches(), as_of=_GOLDEN_AS_OF)
    return dc


@pytest.fixture(scope="module")
def seeded_elo() -> EloRatings:
    elo = EloRatings()
    elo.seed_from_ranking({t: i + 1 for i, t in enumerate(TEAMS)}, n_teams=len(TEAMS))
    return elo


def test_elo_seeding_is_stable(seeded_elo: EloRatings) -> None:
    """_rank_to_elo's linear mapping must not drift."""
    assert seeded_elo.get_rating("Argentina") == pytest.approx(1575.0)
    assert seeded_elo.get_rating("Morocco") == pytest.approx(1500.0)
    assert seeded_elo.get_rating("Unknown Team") == pytest.approx(1500.0)


def test_elo_neutral_default_unchanged(seeded_elo: EloRatings) -> None:
    """
    Default construction must behave as a neutral-venue model.

    Historically `neutral` was a no-op: `update()` contained `if neutral: dr = dr` and
    `expected_outcome()` ignored the argument entirely. Adding a real home-advantage term
    must not change the default, so neutral and non-neutral agree at home_advantage=0.
    """
    p_neutral, _ = seeded_elo.expected_outcome("Argentina", "Morocco", neutral=True)
    p_home, _ = seeded_elo.expected_outcome("Argentina", "Morocco", neutral=False)
    assert p_neutral == pytest.approx(p_home)
    assert p_neutral == pytest.approx(0.606288, abs=1e-5)


def test_elo_update_is_deterministic() -> None:
    elo = EloRatings()
    elo.seed_from_ranking({t: i + 1 for i, t in enumerate(TEAMS)}, n_teams=len(TEAMS))
    before = elo.get_rating("Morocco")
    new_h, new_a = elo.update("Morocco", "Argentina", 2, 0, tournament_type="world_cup")
    assert new_h > before
    assert new_h == pytest.approx(1536.3773, abs=1e-3)
    assert new_a == pytest.approx(1538.6227, abs=1e-3)


def test_dixon_coles_fit_recovers_ordering(fitted_dc: DixonColesModel) -> None:
    assert fitted_dc.is_fitted
    attacks = {t: fitted_dc.params_[f"attack_{t}"] for t in TEAMS}
    assert attacks["Argentina"] > attacks["Morocco"]
    assert fitted_dc.params_["rho"] <= 0.0


def test_dixon_coles_home_advantage_is_fitted_and_applied(fitted_dc: DixonColesModel) -> None:
    """
    Dixon-Coles already fits a home_adv term; it is applied only when neutral=False.
    This is the mechanism the league model depends on, so pin it.
    """
    assert "home_adv" in fitted_dc.params_
    neutral = fitted_dc.predict_match("Germany", "Japan", neutral=True)
    at_home = fitted_dc.predict_match("Germany", "Japan", neutral=False)
    assert at_home.lambda_home > neutral.lambda_home
    assert at_home.home_win > neutral.home_win


def test_probabilities_normalise(fitted_dc: DixonColesModel, seeded_elo: EloRatings) -> None:
    ens = EnsembleModel(fitted_dc, seeded_elo)
    for home in TEAMS:
        for away in TEAMS:
            if home == away:
                continue
            p = ens.predict(home, away)
            assert p.home_win + p.draw + p.away_win == pytest.approx(1.0)
            assert p.score_matrix.sum() == pytest.approx(1.0)
            assert (p.score_matrix >= 0).all()


def test_ensemble_default_weight_unchanged(fitted_dc: DixonColesModel, seeded_elo: EloRatings) -> None:
    """The default dc_weight is 0.70; build_site_wc.py overrides it to 0.50."""
    ens = EnsembleModel(fitted_dc, seeded_elo)
    assert ens.dc_weight == pytest.approx(0.70)
    assert ens.elo_weight == pytest.approx(0.30)


def test_ensemble_golden_predictions(fitted_dc: DixonColesModel, seeded_elo: EloRatings) -> None:
    """
    The core guard: ensemble output for the WC configuration.

    Captured before the shared-model generalisation. Any change to the hardcoded
    0.25 draw rate, the 2.6 lambda scale, or the 0.75 away penalty that is not purely
    additive will move these numbers.

    On tolerance: the fit is pinned to `_GOLDEN_AS_OF`. Before that, it used the wall
    clock, and the decay weights shrank against the ridge penalty every day. That
    drift (about 3e-5 a day, and 1.3e-3 by 2026-10-01) accounts for the original
    abs=1e-5 failure a day after capture, and it later failed the 1e-3 one too. It
    was put down to BLAS or optimiser noise, but neither caused it. With the date
    pinned, the default L-BFGS-B fit converges (success, 12 iterations), and a fit at
    ftol=1e-15/gtol=1e-12 agrees with the values below to 4e-6. So abs=1e-4 leaves
    room for genuine cross-platform optimiser variation. It is still far tighter
    than the calibration changes this test exists to catch (a draw rate of 0.283
    against 0.25, or a lambda scale of 2.26 against 2.6, moves these outputs by 3e-2
    or more).
    """
    ens = EnsembleModel(fitted_dc, seeded_elo, dc_weight=0.50)
    p = ens.predict("Argentina", "Morocco", neutral=True)
    assert p.home_win == pytest.approx(0.64585, abs=1e-4)
    assert p.draw == pytest.approx(0.15758, abs=1e-4)
    assert p.away_win == pytest.approx(0.19657, abs=1e-4)


def test_golden_score_matrix(fitted_dc: DixonColesModel, seeded_elo: EloRatings) -> None:
    """
    Guard the score matrix, not just win/draw/loss.

    These are separable: W/D/L comes from blending the component probabilities
    directly, while the score matrix is blended on its own. So `lam_scale` changes
    the matrix while leaving W/D/L untouched — and the simulator samples goals from
    the matrix, so such a change would silently alter every simulated scoreline
    without moving a single number the previous test looks at.
    """
    ens = EnsembleModel(fitted_dc, seeded_elo, dc_weight=0.50)
    p = ens.predict("Argentina", "Morocco", neutral=True)

    m = p.score_matrix
    goals = np.arange(m.shape[0])
    exp_home = float((m.sum(axis=1) * goals).sum())
    exp_away = float((m.sum(axis=0) * goals).sum())

    assert exp_home == pytest.approx(1.685, abs=1e-2)
    assert exp_away == pytest.approx(0.768, abs=1e-2)
    assert float(m[0, 0]) == pytest.approx(0.0875, abs=5e-3)

    # A league-calibrated lambda scale must visibly move the matrix even though it
    # leaves win/draw/loss identical.
    liga = EnsembleModel(fitted_dc, seeded_elo, dc_weight=0.50, lam_scale=2.26)
    q = liga.predict("Argentina", "Morocco", neutral=True)
    assert q.home_win == pytest.approx(p.home_win, abs=1e-9)
    assert float((q.score_matrix.sum(axis=1) * goals).sum()) < exp_home


def test_elo_home_advantage_applies_when_configured() -> None:
    """
    The league capability: with a home_advantage set, playing at home must raise the
    home side's win probability, and two evenly-rated sides must no longer be a coin flip.
    """
    elo = EloRatings(home_advantage=70.0)
    elo.seed_from_ranking({"A": 1, "B": 2}, n_teams=2)

    neutral, _ = elo.expected_outcome("A", "B", neutral=True)
    at_home, _ = elo.expected_outcome("A", "B", neutral=False)
    assert at_home > neutral

    # Equal ratings: neutral is exactly 50/50, home is clearly not.
    level = EloRatings(home_advantage=70.0)
    assert level.expected_outcome("X", "Y", neutral=True)[0] == pytest.approx(0.5)
    assert level.expected_outcome("X", "Y", neutral=False)[0] == pytest.approx(0.59940, abs=1e-5)


def test_elo_update_uses_the_same_expectation_it_predicts() -> None:
    """
    Rating updates must apply home advantage too. If `update` ignored it while
    `expected_outcome` applied it, home wins would be systematically over-rewarded
    and the ratings would drift toward whoever had the most home fixtures.
    """
    elo = EloRatings(home_advantage=70.0, k_league=20)
    elo.seed_from_ranking({"A": 1, "B": 2}, n_teams=2)
    start = elo.get_rating("A")

    # A home win by the favourite is largely expected, so the rating barely moves.
    elo.update("A", "B", 1, 0, tournament_type="league", neutral=False)
    gain_at_home = elo.get_rating("A") - start

    elo2 = EloRatings(home_advantage=70.0, k_league=20)
    elo2.seed_from_ranking({"A": 1, "B": 2}, n_teams=2)
    elo2.update("A", "B", 1, 0, tournament_type="league", neutral=True)
    gain_neutral = elo2.get_rating("A") - start

    assert gain_at_home < gain_neutral


def test_league_k_factor_is_selectable() -> None:
    elo = EloRatings(k_league=20)
    elo.seed_from_ranking({"A": 1, "B": 2}, n_teams=2)
    elo.update("A", "B", 3, 0, tournament_type="league")
    league_move = abs(elo.get_rating("A") - 1515.0)

    elo2 = EloRatings()
    elo2.seed_from_ranking({"A": 1, "B": 2}, n_teams=2)
    elo2.update("A", "B", 3, 0, tournament_type="world_cup")
    wc_move = abs(elo2.get_rating("A") - 1515.0)

    # K=20 must move ratings a third as far as K=60 for the same result.
    assert league_move == pytest.approx(wc_move / 3, rel=1e-6)


def test_ensemble_league_parameters_change_output(
    fitted_dc: DixonColesModel, seeded_elo: EloRatings
) -> None:
    """A league-calibrated ensemble must produce a higher draw rate than the WC default."""
    wc = EnsembleModel(fitted_dc, seeded_elo, dc_weight=0.0)
    liga = EnsembleModel(
        fitted_dc, seeded_elo, dc_weight=0.0,
        draw_rate=0.30, lam_scale=2.2, away_penalty=1.0,
    )
    p_wc = wc.predict("Argentina", "Morocco", neutral=True)
    p_liga = liga.predict("Argentina", "Morocco", neutral=True)

    # Lower scoring means more draws on the Elo-only Poisson path.
    assert p_liga.draw > p_wc.draw
    assert p_liga.lambda_home < p_wc.lambda_home
    assert p_liga.home_win + p_liga.draw + p_liga.away_win == pytest.approx(1.0)


def test_adaptive_weight_floors_unknown_teams_above_zero(
    fitted_dc: DixonColesModel, seeded_elo: EloRatings
) -> None:
    """
    Documented quirk, pinned so it is not changed by accident: when either side is
    absent from the Dixon-Coles fit, `_adaptive_dc_weight` returns
    max(dc_weight - 0.30, 0.40) — which *raises* an explicitly requested dc_weight of
    0.0 to 0.40. Asking a fitted model for Elo-only predictions therefore does not
    give you Elo-only unless both teams are unknown to it.
    """
    ens = EnsembleModel(fitted_dc, seeded_elo, dc_weight=0.0)
    assert ens._adaptive_dc_weight("Nowhere United", "Parts Unknown") == pytest.approx(0.40)
    # An unfitted model is the reliable way to force the Elo-only path.
    assert EnsembleModel(DixonColesModel(), seeded_elo, dc_weight=0.0)._adaptive_dc_weight(
        "Nowhere United", "Parts Unknown"
    ) == pytest.approx(0.0)


def test_away_penalty_of_one_avoids_double_counting() -> None:
    """
    With a real Elo home-advantage term, the legacy 0.75 away multiplier would apply
    the same asymmetry twice. Passing away_penalty=1.0 must leave the away lambda
    driven solely by the Elo probability.

    Uses an unfitted Dixon-Coles model so the Elo-only path is genuinely taken.
    """
    elo = EloRatings(home_advantage=70.0)
    elo.seed_from_ranking({"A": 1, "B": 2}, n_teams=2)

    doubled = EnsembleModel(DixonColesModel(), elo, dc_weight=0.0, away_penalty=0.75)
    single = EnsembleModel(DixonColesModel(), elo, dc_weight=0.0, away_penalty=1.0)

    p_doubled = doubled.predict("A", "B", neutral=False)
    p_single = single.predict("A", "B", neutral=False)
    assert p_single.lambda_away > p_doubled.lambda_away


def test_elo_only_path_never_clamps_to_zero(seeded_elo: EloRatings) -> None:
    """
    Regression guard for a documented past bug: the old linear formula assigned 0%
    upset probability whenever elo_p_home > 0.875. The Poisson-matrix derivation must
    keep every outcome strictly positive.
    """
    lopsided = EloRatings()
    lopsided.seed_from_ranking({"Strong": 1, "Weak": 60}, n_teams=60)
    ens = EnsembleModel(DixonColesModel(), lopsided, dc_weight=0.0)
    p = ens.predict("Strong", "Weak", neutral=True)
    assert p.away_win > 0.0
    assert p.draw > 0.0
    assert p.home_win + p.draw + p.away_win == pytest.approx(1.0)
