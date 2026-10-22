"""
Dixon-Coles bivariate Poisson model for international football.

Reference: Dixon & Coles (1997) "Modelling Association Football Scores
and Inefficiencies in the Football Betting Market".

Key design choices for World Cup 2026:
- neutral=True by default (all matches at USA/Canada/Mexico neutral sites)
- Time-weighted MLE with exponential decay (xi per day) so qualifiers from
  2023-2025 dominate; WC 2022 (~3.5 yrs) contributes ~10% weight
- rho correction on low-score cells (0-0, 1-0, 0-1, 1-1)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.special import gammaln
from scipy.stats import poisson

logger = logging.getLogger(__name__)

GLOBAL_MEAN_GOALS = 1.15  # FIFA WC historical average goals per team per match
RHO_BOUNDS = (-0.99, 0.0)


def estimate_rho(home_goals, away_goals, lam_h, lam_a, weights, bounds=RHO_BOUNDS) -> float:
    """
    Weighted maximum-likelihood rho of the Dixon-Coles low-score correction, given each
    match's goal rates.

    The correction tau(x, y) leaves every row and column sum of the score matrix
    unchanged, so with the rates held fixed the only part of the scoreline likelihood
    that depends on rho is sum_i w_i log tau(hg_i, ag_i; lam_h_i, lam_a_i, rho): a
    one-dimensional, smooth problem on a bounded interval. Only 0-0, 1-0, 0-1 and 1-1
    scorelines carry information.
    """
    hg = np.asarray(home_goals, float)
    ag = np.asarray(away_goals, float)
    lh = np.asarray(lam_h, float)
    la = np.asarray(lam_a, float)
    w = np.asarray(weights, float)
    low = (hg <= 1) & (ag <= 1) & (w > 0) & np.isfinite(lh) & np.isfinite(la)
    if not low.any():
        return float("nan")
    hg, ag, lh, la, w = hg[low], ag[low], lh[low], la[low], w[low]
    m00 = (hg == 0) & (ag == 0)
    m10 = (hg == 1) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m11 = (hg == 1) & (ag == 1)

    def nll(rho: float) -> float:
        tau = np.where(m00, 1 - lh * la * rho, np.where(m10, 1 + la * rho, np.where(m01, 1 + lh * rho,
                       np.where(m11, 1 - rho, 1.0))))
        return -float(np.dot(w, np.log(np.maximum(tau, 1e-10))))

    res = minimize_scalar(nll, bounds=bounds, method="bounded", options={"xatol": 1e-6})
    return float(res.x)


@dataclass
class MatchProbabilities:
    home_win: float
    draw: float
    away_win: float
    lambda_home: float
    lambda_away: float
    score_matrix: np.ndarray  # shape (max_k+1, max_k+1), rows=home goals, cols=away


class DixonColesModel:
    """
    Fits attack/defense parameters per team via time-weighted MLE.
    All World Cup matches are treated as neutral-site (home_adv=0 in prediction).
    """

    def __init__(self, xi: float = 0.0018, ridge: float = 1.0, analytic_grad: bool = False,
                 fixed_rho: float | None = None, prior_group=None) -> None:
        self.xi = xi       # daily decay constant
        self.ridge = ridge  # L2 regularization on attack/defense (stabilises sparse WC-only fits)
        # Opt-in: hand L-BFGS-B the exact gradient instead of finite differences. Same
        # objective and optimum, tens of times faster on the large pooled fits. Off by
        # default so the World Cup path (and its golden test) is unchanged.
        self.analytic_grad = analytic_grad
        # Opt-in: hold rho at this value instead of fitting it. rho is identified only by
        # goals rows (an xG or market-rate row is fitted on its rates, with no tau), so on a
        # frame where nearly every match carries xG it stays at its starting value of -0.1,
        # or two or three goals rows push it to a bound (at -0.99 EnsembleModel drops the
        # Dixon-Coles side). The club fits pass a rho estimated separately, from many
        # leagues' scorelines (oddsmarkets/football/competitions/league/fitting.py,
        # `estimate_rho`). None (the default) fits rho as before, so the World Cup path and
        # its golden test are unchanged.
        self.fixed_rho = fixed_rho
        # Opt-in (analytic gradient only): a hierarchical prior. `prior_group(team)` names the
        # team's tier (or None); a tier's teams are shrunk toward its own attack and defence
        # offsets (free parameters, stored as tier_attack_<g> / tier_defense_<g>), not toward 0,
        # and a team the fit never saw takes its tier's offsets. The pooled club fit passes
        # the cup tiers (docs/research/football_edge.md 3.5); None keeps every fit as before.
        self.prior_group = prior_group
        self.params_: dict[str, float] = {}
        self.teams_: list[str] = []
        self.fitted_at_: Optional[datetime] = None
        self._anchor_team: Optional[str] = None  # defense fixed to 0 for identifiability

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, matches: pd.DataFrame, *, as_of: Optional[datetime] = None) -> None:
        """
        Fit the model on historical match data.

        matches: DataFrame with columns
            home_team, away_team, home_goals, away_goals, match_date
            Optional: weight (float, 0-1) — match-type weight (1.0=qualifier/major, 0.5=friendly)
        as_of: the reference time the exponential decay is measured from (default: now).
            The decay rescales every weight by the same factor as the clock advances,
            which changes their size relative to the fixed ridge penalty, so a fit on
            identical data drifts from one day to the next. Pass a fixed as_of when
            the output must be reproducible.
        """
        df = matches.dropna(subset=["home_goals", "away_goals"]).copy()
        df["home_goals"] = df["home_goals"].astype(int)
        df["away_goals"] = df["away_goals"].astype(int)
        # A negative "score" is an awarded or voided match, not data; a row that
        # would make the likelihood non-finite would freeze the optimiser at its
        # starting point and hand back a model in which every team is average.
        bad = (df["home_goals"] < 0) | (df["away_goals"] < 0)
        if bad.any():
            logger.warning("Dixon-Coles: dropping %d matches with a negative score", int(bad.sum()))
            df = df[~bad].copy()
        if len(df) < 2:
            raise ValueError("Dixon-Coles: not enough matches to fit")

        now = as_of if as_of is not None else datetime.now(timezone.utc)
        if df["match_date"].dt.tz is None:
            df["match_date"] = df["match_date"].dt.tz_localize("UTC")
        days_ago = (now - df["match_date"]).dt.total_seconds() / 86400
        time_weight = np.exp(-self.xi * days_ago.values)

        if "weight" in df.columns:
            time_weight = time_weight * df["weight"].values

        self.teams_ = sorted(set(df["home_team"]) | set(df["away_team"]))
        n = len(self.teams_)
        self._anchor_team = self.teams_[0]
        team_idx = {t: i for i, t in enumerate(self.teams_)}

        # Parameter vector layout:
        #   [attack_0..attack_{n-1}, defense_0..defense_{n-1}, home_adv, rho]
        # Constraint: defense[anchor] = 0 (fixed via bounds)
        anchor_idx = team_idx[self._anchor_team]
        groups = [self.prior_group(t) if self.prior_group is not None else None for t in self.teams_]
        tiers = sorted({g for g in groups if g})
        G = len(tiers) if self.analytic_grad else 0
        tier_of = np.array([tiers.index(g) if (G and g) else -1 for g in groups], dtype=int)
        in_tier = tier_of >= 0
        x0 = np.zeros(2 * n + 2 * G + 2)
        x0[-2] = 0.1  # home_adv initial guess
        x0[-1] = -0.1  # rho initial guess
        if self.fixed_rho is not None:
            x0[-1] = float(self.fixed_rho)

        bounds = []
        for i in range(n):
            bounds.append((None, None))  # attack_i
        for i in range(n):
            if i == anchor_idx:
                bounds.append((0.0, 0.0))  # defense anchor fixed to 0
            else:
                bounds.append((None, None))
        bounds += [(None, None)] * (2 * G)   # tier offsets
        bounds.append((None, None))   # home_adv
        bounds.append((-0.99, 0.0) if self.fixed_rho is None   # rho must be negative or zero
                      else (float(self.fixed_rho), float(self.fixed_rho)))

        home_teams = np.array([team_idx[t] for t in df["home_team"]])
        away_teams = np.array([team_idx[t] for t in df["away_team"]])
        home_goals = df["home_goals"].values
        away_goals = df["away_goals"].values

        # xG observations (continuous Poisson, no DC tau correction).
        # Rows without xG use integer goals + tau correction (classic DC).
        has_xg = (
            ("home_xg" in df.columns and "away_xg" in df.columns)
            and np.isfinite(df["home_xg"].values).any()
        )
        if has_xg:
            home_xg = df["home_xg"].values.astype(float)
            away_xg = df["away_xg"].values.astype(float)
            xg_mask = np.isfinite(home_xg) & np.isfinite(away_xg)
            goals_mask = ~xg_mask
            n_xg = int(xg_mask.sum())
            logger.info("DC fit: %d matches use xG likelihood, %d use goals", n_xg, int(goals_mask.sum()))
        else:
            xg_mask = np.zeros(len(df), dtype=bool)
            goals_mask = np.ones(len(df), dtype=bool)
            home_xg = np.zeros(len(df))
            away_xg = np.zeros(len(df))

        ridge = self.ridge

        def neg_log_likelihood(x: np.ndarray) -> float:
            attack = x[:n]
            defense = x[n : 2 * n]
            home_adv = x[-2]
            rho = x[-1]

            lam_h = np.exp(attack[home_teams] + defense[away_teams] + home_adv)
            lam_a = np.exp(attack[away_teams] + defense[home_teams])

            ll = np.empty(len(df))

            # xG rows: continuous generalised Poisson (gammaln for non-integer x),
            # independent home/away (no tau — DC tau defined only for integer counts).
            if xg_mask.any():
                hx = home_xg[xg_mask]
                ax = away_xg[xg_mask]
                lh = lam_h[xg_mask]
                la = lam_a[xg_mask]
                ll[xg_mask] = (
                    hx * np.log(lh) - lh - gammaln(hx + 1)
                    + ax * np.log(la) - la - gammaln(ax + 1)
                )

            # Goals rows: integer Poisson + DC tau low-score correction.
            if goals_mask.any():
                hg = home_goals[goals_mask]
                ag = away_goals[goals_mask]
                lh = lam_h[goals_mask]
                la = lam_a[goals_mask]
                tau = self._tau_vec(hg, ag, lh, la, rho)
                ll[goals_mask] = (
                    poisson.logpmf(hg, lh)
                    + poisson.logpmf(ag, la)
                    + np.log(np.maximum(tau, 1e-10))
                )

            # L2 regularization: shrinks attack/defense toward 0 (= global mean in log-space).
            # Prevents degenerate parameter values when n_matches < n_params (WC-only fit).
            penalty = ridge * (np.dot(attack, attack) + np.dot(defense, defense))
            return -np.dot(time_weight, ll) + penalty

        # maxfun must be set explicitly — scipy's L-BFGS-B defaults to 15000 which
        # is far too low for large parameter spaces (2 * n_teams + 2 params).
        n_params = len(x0)
        f0 = neg_log_likelihood(x0)
        if not np.isfinite(f0):
            raise ValueError("Dixon-Coles: the likelihood is not finite at the starting point (bad rows in the training data)")
        if self.analytic_grad:
            hg_all = home_goals.astype(float)
            ag_all = away_goals.astype(float)
            hx_all = np.where(xg_mask, home_xg, 0.0)
            ax_all = np.where(xg_mask, away_xg, 0.0)
            m00 = goals_mask & (hg_all == 0) & (ag_all == 0)
            m10 = goals_mask & (hg_all == 1) & (ag_all == 0)
            m01 = goals_mask & (hg_all == 0) & (ag_all == 1)
            m11 = goals_mask & (hg_all == 1) & (ag_all == 1)

            def objective(x: np.ndarray):
                attack, defense, home_adv, rho = x[:n], x[n:2 * n], x[-2], x[-1]
                ta, td = x[2 * n:2 * n + G], x[2 * n + G:2 * n + 2 * G]
                ca = attack - np.where(in_tier, ta[tier_of] if G else 0.0, 0.0)
                cd = defense - np.where(in_tier, td[tier_of] if G else 0.0, 0.0)
                eh = attack[home_teams] + defense[away_teams] + home_adv
                ea = attack[away_teams] + defense[home_teams]
                lh, la = np.exp(eh), np.exp(ea)
                # observed counts: goals on goals rows, xG on xG rows
                oh = np.where(xg_mask, hx_all, hg_all)
                oa = np.where(xg_mask, ax_all, ag_all)
                tau = np.ones(len(lh))
                tau[m00] = 1 - lh[m00] * la[m00] * rho
                tau[m10] = 1 + la[m10] * rho
                tau[m01] = 1 + lh[m01] * rho
                tau[m11] = 1 - rho
                clamp = tau < 1e-10
                tau_c = np.maximum(tau, 1e-10)
                ll = oh * eh - lh - gammaln(oh + 1) + oa * ea - la - gammaln(oa + 1) + np.log(tau_c)
                gh = oh - lh
                ga = oa - la
                grho = np.zeros(len(lh))
                live = ~clamp
                k = m00 & live
                d = -lh[k] * la[k] * rho / tau_c[k]
                gh[k] += d
                ga[k] += d
                grho[k] = -lh[k] * la[k] / tau_c[k]
                k = m10 & live
                ga[k] += la[k] * rho / tau_c[k]
                grho[k] = la[k] / tau_c[k]
                k = m01 & live
                gh[k] += lh[k] * rho / tau_c[k]
                grho[k] = lh[k] / tau_c[k]
                k = m11 & live
                grho[k] = -1.0 / tau_c[k]
                w = time_weight
                g = np.zeros_like(x)
                g[:n] = np.bincount(home_teams, w * gh, n) + np.bincount(away_teams, w * ga, n)
                g[n:2 * n] = np.bincount(away_teams, w * gh, n) + np.bincount(home_teams, w * ga, n)
                g[-2] = np.dot(w, gh)
                g[-1] = np.dot(w, grho)
                val = -np.dot(w, ll) + ridge * (np.dot(ca, ca) + np.dot(cd, cd))
                grad = -g
                grad[:n] += 2 * ridge * ca
                grad[n:2 * n] += 2 * ridge * cd
                if G:
                    grad[2 * n:2 * n + G] -= 2 * ridge * np.bincount(tier_of[in_tier], ca[in_tier], G)
                    grad[2 * n + G:2 * n + 2 * G] -= 2 * ridge * np.bincount(tier_of[in_tier], cd[in_tier], G)
                return val, grad

            result = minimize(
                objective,
                x0,
                jac=True,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 5_000, "ftol": 1e-12, "gtol": 1e-7},
            )
        else:
            result = minimize(
                neg_log_likelihood,
                x0,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 5_000, "maxfun": max(50_000, n_params * 200), "ftol": 1e-8},
            )
        if not result.success:
            logger.warning("Dixon-Coles optimization did not fully converge: %s", result.message)
        if not np.isfinite(result.fun) or (result.nit == 0 and np.allclose(result.x, x0)):
            raise ValueError(f"Dixon-Coles: the optimiser aborted at its starting point ({result.message})")

        x = result.x
        attack = x[:n]
        defense = x[n : 2 * n]
        home_adv = x[-2]
        rho = x[-1]

        self.params_ = {f"attack_{t}": float(attack[i]) for i, t in enumerate(self.teams_)}
        self.params_.update({f"defense_{t}": float(defense[i]) for i, t in enumerate(self.teams_)})
        self.params_["home_adv"] = float(home_adv)
        self.params_["rho"] = float(rho)
        for k, g in enumerate(tiers[:G]):
            self.params_[f"tier_attack_{g}"] = float(x[2 * n + k])
            self.params_[f"tier_defense_{g}"] = float(x[2 * n + G + k])
        self.fitted_at_ = datetime.now(timezone.utc)
        logger.info(
            "Dixon-Coles fitted on %d matches (%d teams), rho=%.4f, home_adv=%.4f",
            len(df), n, rho, home_adv,
        )

    @property
    def is_fitted(self) -> bool:
        return bool(self.params_)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def team_params(self, team: str) -> tuple[float, float]:
        """(attack, defence) of a team; one the fit never saw takes its tier's offsets (prior_group), else 0."""
        if f"attack_{team}" in self.params_:
            return self.params_[f"attack_{team}"], self.params_.get(f"defense_{team}", 0.0)
        g = self.prior_group(team) if self.prior_group is not None else None
        if g and f"tier_attack_{g}" in self.params_:
            return self.params_[f"tier_attack_{g}"], self.params_[f"tier_defense_{g}"]
        return 0.0, 0.0

    def predict_match(
        self,
        home: str,
        away: str,
        neutral: bool = True,
        max_goals: int = 8,
    ) -> MatchProbabilities:
        """
        Predict match outcome probabilities.
        neutral=True zeroes out home advantage (all WC 2026 matches).
        """
        if not self.params_:
            raise RuntimeError("Model has not been fitted yet. Call fit() first.")

        att_h, def_h = self.team_params(home)
        att_a, def_a = self.team_params(away)
        home_adv = 0.0 if neutral else self.params_.get("home_adv", 0.0)
        rho = self.params_.get("rho", 0.0)

        lam_h = np.exp(att_h + def_a + home_adv)
        lam_a = np.exp(att_a + def_h)

        k = max_goals + 1
        score_matrix = np.zeros((k, k))
        for i in range(k):
            for j in range(k):
                p = poisson.pmf(i, lam_h) * poisson.pmf(j, lam_a)
                score_matrix[i, j] = p * self._tau(i, j, lam_h, lam_a, rho)

        # Clamp negative cells (can occur with sparse data + rho correction)
        score_matrix = np.maximum(score_matrix, 0)
        total = score_matrix.sum()
        if total > 0:
            score_matrix /= total

        home_win = float(np.tril(score_matrix, -1).sum())
        draw = float(np.trace(score_matrix))
        away_win = float(np.triu(score_matrix, 1).sum())

        return MatchProbabilities(
            home_win=home_win,
            draw=draw,
            away_win=away_win,
            lambda_home=float(lam_h),
            lambda_away=float(lam_a),
            score_matrix=score_matrix,
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "xi": self.xi,
            "ridge": self.ridge,
            "teams": self.teams_,
            "anchor_team": self._anchor_team,
            "params": self.params_,
            "fitted_at": self.fitted_at_.isoformat() if self.fitted_at_ else None,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "DixonColesModel":
        data = json.loads(path.read_text())
        model = cls(xi=data["xi"], ridge=data.get("ridge", 1.0))
        model.teams_ = data["teams"]
        model._anchor_team = data.get("anchor_team")
        model.params_ = data["params"]
        if data.get("fitted_at"):
            model.fitted_at_ = datetime.fromisoformat(data["fitted_at"])
        return model

    def is_stale(self, max_age_hours: float = 24.0) -> bool:
        if self.fitted_at_ is None:
            return True
        age = (datetime.now(timezone.utc) - self.fitted_at_).total_seconds() / 3600
        return age > max_age_hours

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tau(x: int, y: int, lam_h: float, lam_a: float, rho: float) -> float:
        if x == 0 and y == 0:
            return 1 - lam_h * lam_a * rho
        if x == 1 and y == 0:
            return 1 + lam_a * rho
        if x == 0 and y == 1:
            return 1 + lam_h * rho
        if x == 1 and y == 1:
            return 1 - rho
        return 1.0

    @staticmethod
    def _tau_vec(
        h: np.ndarray, a: np.ndarray, lam_h: np.ndarray, lam_a: np.ndarray, rho: float
    ) -> np.ndarray:
        tau = np.ones(len(h))
        m00 = (h == 0) & (a == 0)
        m10 = (h == 1) & (a == 0)
        m01 = (h == 0) & (a == 1)
        m11 = (h == 1) & (a == 1)
        tau[m00] = 1 - lam_h[m00] * lam_a[m00] * rho
        tau[m10] = 1 + lam_a[m10] * rho
        tau[m01] = 1 + lam_h[m01] * rho
        tau[m11] = 1 - rho
        return tau
