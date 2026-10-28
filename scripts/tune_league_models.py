#!/usr/bin/env python
"""
Fit the model constants per league, and test whether a global model does better.

Three ways to set the constants, all scored by walk-forward log-loss on each
league's own matches (the only score that matters for a forecast):

  per-league   every league gets its own (xi, ridge, Elo home advantage, Elo K,
               Dixon-Coles weight), chosen on that league's matches alone.
  global       one parameter set for every league, chosen to minimise the
               match-weighted log-loss across all of them. Same per-league fits,
               shared hyper-parameters.
  pooled       one Dixon-Coles fit on every league at once (teams prefixed by
               league so nothing crosses), so home advantage, rho and the decay
               are estimated from ~5,000 matches instead of ~500; Elo and the
               draw/goal calibration stay per league.

Per league the winner is written to competitions/league/data/model_params.json,
which scripts/build_site_all.py reads. A per-league set only wins over the
global one by a margin (`--margin`), because a grid search on 400 matches will
always find *something* that fits the noise.

Two floors any fitted model must clear are printed alongside: a uniform
forecast and a home-advantage-only prior.

Every fold fits exactly the model the build publishes (since 21 October 2026): the
Dixon-Coles frame and fit come from `oddsmarkets.football.competitions.league.fitting`,
the module `scripts/build_site_all.py` and `scripts/build_site_liga.py` use, so each
fold's fit carries the market-rate rows (weight `market_rates.W_MKT`, own decay
`market_rates.XI_MKT`, measured against the candidate xi) and the club rho
(`fitting.club_rho`). Nothing in a fold sees the matches it scores: a fold starts at a day
boundary, the training rows are the matches of earlier days, the decay (goals and market
rows alike) is measured from the start of that day, and the draw rate and goal scale
(`empirical_calibration`) come from the training rows. `--no-market-rates` fits the
plain goals/xG frames, as the tuner did before (and as the build does with the flag of
the same name).

A re-run does not replace the parameters on file (the incumbent: per league, and the pooled
block) unless its new choice beats them on the same folds with a paired 95% CI (block
bootstrap by week) that excludes zero, the promotion rule of the model programme. Two
seasons of one league cannot overturn settings chosen and tested walk-forward on a decade of
football-data history (docs/research/football_edge.md). `--no-incumbent` chooses afresh.

    python scripts/tune_league_models.py                 # everything, ~15 min
    python scripts/tune_league_models.py --league mls --no-pooled
    python scripts/tune_league_models.py --quick
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.league import fitting  # noqa: E402
from oddsmarkets.football.competitions.league.config import LEAGUES, LIGA_ARGENTINA_SLUG  # noqa: E402
from oddsmarkets.football.competitions.league.store import (  # noqa: E402
    empirical_calibration,
    load_store,
    training_frame,
)
from oddsmarkets.football.competitions.liga import store as liga_store  # noqa: E402
from oddsmarkets.football.core import DixonColesModel, EloRatings, EnsembleModel  # noqa: E402
from oddsmarkets.football.sources import market_rates  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("tune-leagues")
# Every Elo seed logs a line; thousands of them here would bury the results.
logging.getLogger("oddsmarkets.sports.world_cup.models.elo").setLevel(logging.WARNING)
logging.getLogger("oddsmarkets.sports.world_cup.models.dixon_coles").setLevel(logging.WARNING)

SITE_DATA = ROOT / "docs" / "site" / "data"
LIGA_STORE = liga_store.store_path()
OUT_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "model_params.json"

# Staged grid: the Dixon-Coles side first, then Elo, then the blend. Staging keeps
# it to ~40 evaluations per league instead of the 1,500 of a full product, at the
# cost of ignoring interactions — acceptable, since the blend weight is where the
# two sides meet and it is searched last with both sides already at their best.
GRID = {
    "xi": [0.001, 0.002, 0.0035, 0.005, 0.008],
    "ridge": [0.25, 0.5, 1.0, 2.0],
    "elo_home_advantage": [30.0, 50.0, 70.0, 90.0, 110.0],
    "k_league": [15, 20, 30],
    "dc_weight": [0.5, 0.65, 0.8, 0.9, 1.0],
}
QUICK_GRID = {
    "xi": [0.002, 0.0035, 0.005],
    "ridge": [0.5, 1.0],
    "elo_home_advantage": [50.0, 70.0, 90.0],
    "k_league": [20],
    "dc_weight": [0.65, 0.8, 1.0],
}
POOLED_GRID = {"xi": [0.002, 0.0035, 0.005], "ridge": [0.5, 1.0]}

DEFAULTS = {"xi": 0.0035, "ridge": 0.5, "elo_home_advantage": 65.0, "k_league": 20, "dc_weight": 0.8}

_EPS = 1e-12


# ── scoring ──────────────────────────────────────────────────────────────────

def outcome_of(row) -> int:
    if row.home_goals > row.away_goals:
        return 0
    return 1 if row.home_goals == row.away_goals else 2


def log_loss(probs, outcomes) -> float:
    return -sum(math.log(max(p[o], _EPS)) for p, o in zip(probs, outcomes)) / len(probs)


def brier(probs, outcomes) -> float:
    return sum(
        (p[i] - (1.0 if i == o else 0.0)) ** 2 for p, o in zip(probs, outcomes) for i in range(3)
    ) / len(probs)


def baselines(df: pd.DataFrame, min_train: int) -> dict:
    test = df.iloc[min_train:]
    outcomes = [outcome_of(r) for r in test.itertuples()]
    train = df.iloc[:min_train]
    h = float((train["home_goals"] > train["away_goals"]).mean())
    d = float((train["home_goals"] == train["away_goals"]).mean())
    a = max(1.0 - h - d, _EPS)
    return {
        "uniform": round(log_loss([(1 / 3, 1 / 3, 1 / 3)] * len(outcomes), outcomes), 5),
        "home_advantage_only": round(log_loss([(h, d, a)] * len(outcomes), outcomes), 5),
    }


def _fold_starts(n: int, folds: int, min_train: int) -> list[tuple[int, int]]:
    step = max((n - min_train) // folds, 1)
    return [(s, min(s + step, n)) for s in range(min_train, n, step)]


def _day_folds(dates: pd.Series, folds: int, min_train: int) -> list[tuple[int, int, pd.Timestamp]]:
    """
    `_fold_starts` moved back to day boundaries: (start, end, as_of) where as_of is 00:00 UTC
    of the first scored day and every training row (index < start) kicked off before it, so no
    match of the scored day (or any later one) is in the fit. `dates` must be sorted.
    """
    d = pd.to_datetime(dates).reset_index(drop=True)
    d = d.dt.tz_localize("UTC") if d.dt.tz is None else d.dt.tz_convert("UTC")
    out: list[tuple[int, int, pd.Timestamp]] = []
    for s, e in _fold_starts(len(d), folds, min_train):
        day = d.iloc[s].normalize()
        s2 = int(d.searchsorted(day, side="left"))
        if out and s2 < out[-1][1]:
            # the day began inside the previous fold: that fold keeps scoring to here
            out[-1] = (out[-1][0], e, out[-1][2])
            continue
        if s2 < e:
            out.append((s2, e, day))
    return out


def _elo_for(train: pd.DataFrame, params: dict) -> EloRatings:
    """
    Elo replayed over the training rows, seeded from those rows' own table.

    The build seeds Elo from last season's final table. Seeding the walk-forward
    alphabetically instead handicapped Elo in every fold and pushed the blend
    weight to pure Dixon-Coles; seeding from points per game over the training
    window is the closest honest stand-in for what the build does.
    """
    elo = EloRatings(k_league=int(params["k_league"]), home_advantage=float(params["elo_home_advantage"]))
    pts: dict[str, float] = {}
    played: dict[str, int] = {}
    for row in train.itertuples():
        h, a = row.home_team, row.away_team
        hp, ap = (3, 0) if row.home_goals > row.away_goals else (0, 3) if row.home_goals < row.away_goals else (1, 1)
        pts[h] = pts.get(h, 0) + hp
        pts[a] = pts.get(a, 0) + ap
        played[h] = played.get(h, 0) + 1
        played[a] = played.get(a, 0) + 1
    ordered = sorted(pts, key=lambda t: -(pts[t] / max(played[t], 1)))
    elo.seed_from_ranking({t: i + 1 for i, t in enumerate(ordered)}, n_teams=len(ordered))
    for row in train.itertuples():
        elo.update(row.home_team, row.away_team, int(row.home_goals), int(row.away_goals),
                   tournament_type="league", neutral=False)
    return elo


def _predict_rows(model, test: pd.DataFrame, probs: list, outcomes: list, slugs: list | None, slug_col=None,
                  ids: list | None = None):
    for row in test.itertuples():
        try:
            p = model.predict(row.home_team, row.away_team, neutral=False)
        except Exception:  # noqa: BLE001
            continue
        total = p.home_win + p.draw + p.away_win
        if total <= 0:
            continue
        probs.append((p.home_win / total, p.draw / total, p.away_win / total))
        outcomes.append(outcome_of(row))
        if slugs is not None:
            slugs.append(getattr(row, slug_col))
        if ids is not None:
            ids.append((str(row.game_id), pd.Timestamp(row.match_date)))


def _row_losses(probs, outcomes, ids) -> dict:
    """{game_id: (log-loss, decision week)} for the paired comparison against the incumbent."""
    def week(t: pd.Timestamp) -> int:
        t = t.tz_convert("UTC").tz_localize(None) if t.tzinfo else t
        return t.to_period("W-SUN").ordinal
    return {gid: (-math.log(max(p[o], _EPS)), week(t)) for p, o, (gid, t) in zip(probs, outcomes, ids)}


def paired_gain(a: dict, b: dict, n_boot: int = 2000, seed: int = 11) -> dict | None:
    """
    a minus b on the matches both scored: mean log-loss difference and its 95% CI from a block
    bootstrap over weeks (the promotion rule of docs/research/*_edge.md, on the tuner's folds).
    """
    common = sorted(set(a) & set(b))
    if not common:
        return None
    d = np.array([a[g][0] - b[g][0] for g in common])
    wk = np.array([a[g][1] for g in common])
    codes, inv = np.unique(wk, return_inverse=True)
    sums, cnt = np.bincount(inv, d), np.bincount(inv)
    rng = np.random.default_rng(seed)
    bs = np.empty(n_boot)
    for i in range(n_boot):
        j = rng.integers(0, len(codes), len(codes))
        bs[i] = sums[j].sum() / cnt[j].sum()
    return {"d_ll": round(float(d.mean()), 5), "lo": round(float(np.percentile(bs, 2.5)), 5),
            "hi": round(float(np.percentile(bs, 97.5)), 5), "n": len(common)}


# ── per-league evaluation ────────────────────────────────────────────────────

class LeagueEvaluator:
    """Walk-forward scorer for one league, caching the Elo and DC fits per fold."""

    def __init__(self, df: pd.DataFrame, folds: int, min_train: int, slug: str = "", market: bool = True) -> None:
        self.df = df
        self.slug = slug
        self.market = market
        day_folds = _day_folds(df["match_date"], folds, min_train)
        self.folds = [(s, e) for s, e, _ in day_folds]
        self.as_of = [t for _, _, t in day_folds]
        # the draw rate and goal scale of each fold from its training rows only (the build
        # measures them on its own training frame, i.e. on matches already played)
        self.cals = [empirical_calibration(df.iloc[:s]) for s, _ in self.folds]
        self._dc: dict[tuple, list[DixonColesModel | None]] = {}
        self._elo: dict[tuple, list[EloRatings]] = {}

    def fit_frame(self, i: int, xi: float) -> pd.DataFrame:
        """Fold i's Dixon-Coles frame: the production frame (`fitting.dc_frame`) as of the fold's day."""
        s, _ = self.folds[i]
        return fitting.dc_frame(self.df.iloc[:s], self.slug, xi, market=self.market, now=self.as_of[i])

    def dc_fits(self, xi: float, ridge: float) -> list:
        key = (xi, ridge)
        if key not in self._dc:
            fits = []
            for i in range(len(self.folds)):
                try:
                    dc = fitting.fit_dc(self.fit_frame(i, xi), xi, ridge, as_of=self.as_of[i].to_pydatetime())
                except Exception:  # noqa: BLE001
                    dc = None
                fits.append(dc)
            self._dc[key] = fits
        return self._dc[key]

    def elo_fits(self, home_adv: float, k: int) -> list:
        key = (home_adv, k)
        if key not in self._elo:
            self._elo[key] = [
                _elo_for(self.df.iloc[:s], {"elo_home_advantage": home_adv, "k_league": k})
                for s, _ in self.folds
            ]
        return self._elo[key]

    def score(self, params: dict, only_ids: set | None = None, detail: bool = False) -> dict | None:
        """Walk-forward score; `only_ids` restricts the scored rows (the fits are unchanged).
        `detail` adds each scored match's log-loss and week (`losses`), for `paired_gain`."""
        dcs = self.dc_fits(params["xi"], params["ridge"])
        elos = self.elo_fits(params["elo_home_advantage"], params["k_league"])
        probs, outcomes, ids = [], [], []
        for (s, e), dc, elo, cal in zip(self.folds, dcs, elos, self.cals):
            if dc is None:
                continue
            model = EnsembleModel(dc, elo, dc_weight=params["dc_weight"],
                                  draw_rate=cal["draw_rate"], lam_scale=cal["lam_scale"],
                                  away_penalty=1.0)
            test = self.df.iloc[s:e]
            if only_ids is not None:
                test = test[test["game_id"].isin(only_ids)]
            _predict_rows(model, test, probs, outcomes, None, ids=ids)
        if not probs:
            return None
        out = {"log_loss": round(log_loss(probs, outcomes), 5), "brier": round(brier(probs, outcomes), 5), "n": len(probs)}
        if detail:
            out["losses"] = _row_losses(probs, outcomes, ids)
        return out


def staged_search(ev: LeagueEvaluator, grid: dict, label: str) -> tuple[dict, dict, list[dict]]:
    """Stage A: DC alone. Stage B: Elo alone. Stage C: the blend. Returns best, its score, every row."""
    rows: list[dict] = []

    def run(params):
        sc = ev.score(params)
        if sc:
            rows.append({**params, **sc})
        return sc["log_loss"] if sc else float("inf")

    best_dc = min(
        ((xi, r) for xi in grid["xi"] for r in grid["ridge"]),
        key=lambda t: run({"xi": t[0], "ridge": t[1], "elo_home_advantage": grid["elo_home_advantage"][0],
                           "k_league": grid["k_league"][0], "dc_weight": 1.0}),
    )
    best_elo = min(
        ((h, k) for h in grid["elo_home_advantage"] for k in grid["k_league"]),
        key=lambda t: run({"xi": best_dc[0], "ridge": best_dc[1], "elo_home_advantage": t[0],
                           "k_league": t[1], "dc_weight": 0.0}),
    )
    best_w = min(
        grid["dc_weight"],
        key=lambda w: run({"xi": best_dc[0], "ridge": best_dc[1], "elo_home_advantage": best_elo[0],
                           "k_league": best_elo[1], "dc_weight": w}),
    )
    best = {"xi": best_dc[0], "ridge": best_dc[1], "elo_home_advantage": best_elo[0],
            "k_league": best_elo[1], "dc_weight": best_w}
    score = ev.score(best)
    logger.info("%s: best %s -> log_loss %.5f", label, best, score["log_loss"])
    return best, score, rows


# ── global (shared hyper-parameters) ─────────────────────────────────────────

def global_search(evs: dict[str, LeagueEvaluator], grid: dict) -> dict:
    """The staged search again, scored on the match-weighted total across leagues."""
    def total(params):
        n = 0
        loss = 0.0
        for ev in evs.values():
            sc = ev.score(params)
            if sc:
                loss += sc["log_loss"] * sc["n"]
                n += sc["n"]
        return loss / n if n else float("inf")

    best_dc = min(((xi, r) for xi in grid["xi"] for r in grid["ridge"]),
                  key=lambda t: total({"xi": t[0], "ridge": t[1], "elo_home_advantage": grid["elo_home_advantage"][0],
                                       "k_league": grid["k_league"][0], "dc_weight": 1.0}))
    best_elo = min(((h, k) for h in grid["elo_home_advantage"] for k in grid["k_league"]),
                   key=lambda t: total({"xi": best_dc[0], "ridge": best_dc[1], "elo_home_advantage": t[0],
                                        "k_league": t[1], "dc_weight": 0.0}))
    best_w = min(grid["dc_weight"],
                 key=lambda w: total({"xi": best_dc[0], "ridge": best_dc[1], "elo_home_advantage": best_elo[0],
                                      "k_league": best_elo[1], "dc_weight": w}))
    best = {"xi": best_dc[0], "ridge": best_dc[1], "elo_home_advantage": best_elo[0],
            "k_league": best_elo[1], "dc_weight": best_w}
    logger.info("global: best %s -> weighted log_loss %.5f", best, total(best))
    return best


# ── pooled fit ───────────────────────────────────────────────────────────────

def pooled_scores(frames: dict[str, pd.DataFrame], params: dict, folds: int, min_train_frac: float,
                  market: bool = True) -> dict[str, dict]:
    """
    One Dixon-Coles over every league; Elo and calibration per league. Returns
    per-league walk-forward scores keyed by slug. Each league's share of a fold's fit is
    the build's (`fitting.pooled_part`: its matches plus market rows, prefixed), as of the
    fold's day.
    """
    parts = []
    for slug, df in frames.items():
        d = df.copy()
        d["slug"] = slug
        parts.append(d)
    plain = pd.concat(parts, ignore_index=True).sort_values("match_date", kind="stable").reset_index(drop=True)
    pooled = plain.assign(home_team=plain["slug"] + ":" + plain["home_team"],
                          away_team=plain["slug"] + ":" + plain["away_team"])
    n = len(pooled)
    min_train = int(n * min_train_frac)

    probs, outcomes, slugs, ids = [], [], [], []
    for s, e, as_of in _day_folds(pooled["match_date"], folds, min_train):
        train, test = pooled.iloc[:s], pooled.iloc[s:e]
        groups = {slug: g.drop(columns="slug").reset_index(drop=True) for slug, g in plain.iloc[:s].groupby("slug")}
        cals = {slug: empirical_calibration(g) for slug, g in groups.items()}
        fit_df = pd.concat([fitting.pooled_part(g, slug, params["xi"], market=market, now=as_of)
                            for slug, g in groups.items()], ignore_index=True)
        t0 = time.perf_counter()
        try:
            dc = fitting.fit_dc(fit_df, params["xi"], params["ridge"], as_of=as_of.to_pydatetime())
        except Exception as exc:  # noqa: BLE001
            logger.warning("pooled fit failed at %d: %s", s, exc)
            continue
        elo = _elo_for(train, params)
        logger.info("  pooled fold at %d/%d fitted in %.0fs", s, n, time.perf_counter() - t0)
        for slug in frames:
            sub = test[test["slug"] == slug]
            if sub.empty or slug not in cals:
                continue
            model = EnsembleModel(dc, elo, dc_weight=params["dc_weight"],
                                  draw_rate=cals[slug]["draw_rate"], lam_scale=cals[slug]["lam_scale"],
                                  away_penalty=1.0)
            _predict_rows(model, sub, probs, outcomes, slugs, "slug", ids=ids)

    out = {}
    for slug in frames:
        idx = [i for i, sl in enumerate(slugs) if sl == slug]
        if idx:
            p = [probs[i] for i in idx]
            o = [outcomes[i] for i in idx]
            sid = [ids[i] for i in idx]
            out[slug] = {"log_loss": round(log_loss(p, o), 5), "brier": round(brier(p, o), 5),
                         "n": len(p), "ids": {g for g, _ in sid}, "losses": _row_losses(p, o, sid)}
    return out


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", action="append", help="slug; repeatable")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--no-pooled", action="store_true", help="skip the pooled all-league fit")
    parser.add_argument("--folds", type=int, default=6)
    parser.add_argument("--min-train", type=int, default=200)
    parser.add_argument("--margin", type=float, default=0.002,
                        help="a per-league set must beat the global one by this much log-loss to be adopted")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--no-market-rates", action="store_true",
                        help="fit the plain goals/xG frames (the build's --no-market-rates); the default fits what the build fits")
    parser.add_argument("--no-incumbent", action="store_true",
                        help="choose afresh; by default a league keeps the parameters on file unless the new choice "
                             "beats them with a paired 95%% CI on its walk-forward log-loss that excludes zero")
    args = parser.parse_args()
    market = not args.no_market_rates

    grid = QUICK_GRID if args.quick else GRID
    slugs = args.league or (list(LEAGUES) + [LIGA_ARGENTINA_SLUG])

    # A partial run (--league) keeps the other leagues' entries and, when it has
    # them, reuses the global set already on file as the reference rather than
    # re-deriving "global" from one league.
    existing = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    partial = bool(args.league) and bool(existing.get("global"))

    frames: dict[str, pd.DataFrame] = {}
    for slug in slugs:
        if slug == LIGA_ARGENTINA_SLUG:
            df = liga_store.training_frame(load_store(LIGA_STORE))
        else:
            df = training_frame(load_store(SITE_DATA / slug / "store.json"), LEAGUES[slug])
        if len(df) < args.min_train + args.folds:
            logger.warning("%s: only %d matches — skipped", slug, len(df))
            continue
        frames[slug] = df
        logger.info("%s: %d matches (%s to %s)", slug, len(df), df["match_date"].min().date(), df["match_date"].max().date())

    t0 = time.perf_counter()
    evs = {slug: LeagueEvaluator(df, args.folds, args.min_train, slug=slug, market=market) for slug, df in frames.items()}
    per_league: dict[str, dict] = {}
    for slug, ev in evs.items():
        best, score, _rows = staged_search(ev, grid, slug)
        per_league[slug] = {"params": best, "score": score}
    logger.info("per-league search done in %.0fs", time.perf_counter() - t0)

    global_best = existing["global"] if partial else global_search(evs, grid)
    if partial:
        logger.info("global: reusing %s from %s", global_best, args.out)
    global_scores = {slug: ev.score(global_best) for slug, ev in evs.items()}
    default_scores = {slug: ev.score(DEFAULTS) for slug, ev in evs.items()}

    pooled: dict[str, dict] = {}
    pooled_best = None
    pool_frames = {k: v for k, v in frames.items() if k != LIGA_ARGENTINA_SLUG}
    if not args.no_pooled and len(pool_frames) > 1:
        t0 = time.perf_counter()
        best_loss = float("inf")
        for xi, ridge in itertools.product(POOLED_GRID["xi"], POOLED_GRID["ridge"]):
            params = {**global_best, "xi": xi, "ridge": ridge}
            logger.info("pooled: xi=%s ridge=%s", xi, ridge)
            scores = pooled_scores(pool_frames, params, args.folds, min_train_frac=0.3, market=market)
            n = sum(s["n"] for s in scores.values())
            loss = sum(s["log_loss"] * s["n"] for s in scores.values()) / n if n else float("inf")
            logger.info("pooled: xi=%s ridge=%s -> weighted log_loss %.5f", xi, ridge, loss)
            if loss < best_loss:
                best_loss, pooled_best, pooled = loss, params, scores
        logger.info("pooled search done in %.0fs", time.perf_counter() - t0)
    # The parameters on file (the incumbent), scored on the same folds: a re-run replaces them only
    # when the new choice is better beyond noise (the promotion rule), so one cannot undo a promotion
    # that was tested on far more data than these two seasons (docs/MODELS.md 5.1).
    incumbent_pooled: dict[str, dict] = {}
    inc_pool_params = existing.get("pooled") if not args.no_incumbent else None
    if inc_pool_params and pooled_best is not None:
        inc_pool_params = {**DEFAULTS, **inc_pool_params}
        if inc_pool_params == pooled_best:
            incumbent_pooled = pooled
        else:
            logger.info("pooled: scoring the parameters on file %s", inc_pool_params)
            incumbent_pooled = pooled_scores(pool_frames, inc_pool_params, args.folds, min_train_frac=0.3, market=market)

    # The pooled block itself (it sets the build's pooled fit) follows the same rule, on every pooled league.
    pooled_kept = False
    if incumbent_pooled and pooled_best is not None and incumbent_pooled is not pooled:
        a = {g: v for sl in pooled for g, v in pooled[sl]["losses"].items()}
        b = {g: v for sl in incumbent_pooled for g, v in incumbent_pooled[sl]["losses"].items()}
        gain = paired_gain(a, b)
        if not gain or gain["hi"] >= 0:
            logger.info("pooled: new %s v on file %s: %s -> keep the file's", pooled_best, inc_pool_params, gain)
            pooled_best, pooled, pooled_kept = inc_pool_params, incumbent_pooled, True
        else:
            logger.info("pooled: new %s beats the file's %s: %s", pooled_best, inc_pool_params, gain)

    # ── choose per league ────────────────────────────────────────────────────
    chosen: dict[str, dict] = {}
    print("\n%-18s %9s %9s %9s %9s %9s   %s" % ("league", "uniform", "home-only", "default", "global", "per-lg", "pooled  -> chosen"))
    print("(where the pooled fit ran, every column is scored on the same matches: its test window)")
    for slug, ev in evs.items():
        # Same rows for every method. Where the pooled fit ran, its test window is
        # the common one; otherwise each method is scored on the league's own folds.
        rows = pooled[slug]["ids"] if slug in pooled else None
        if rows is not None:
            global_scores[slug] = ev.score(global_best, rows) or global_scores[slug]
            default_scores[slug] = ev.score(DEFAULTS, rows) or default_scores[slug]
            per_league[slug]["score"] = ev.score(per_league[slug]["params"], rows) or per_league[slug]["score"]
            keep = ev.df["game_id"].isin(rows).to_numpy().copy()
            keep[: args.min_train] = True
            base = baselines(ev.df[keep].reset_index(drop=True), args.min_train)
        else:
            base = baselines(ev.df, args.min_train)
        cands = {"global": global_scores[slug]["log_loss"]}
        cands["per-league"] = per_league[slug]["score"]["log_loss"]
        if slug in pooled:
            cands["pooled"] = pooled[slug]["log_loss"]
        # The global set is the reference; another method has to beat it by the margin.
        method = "global"
        for name in ("pooled", "per-league"):
            if name in cands and cands[name] < cands[method] - args.margin:
                method = name
        params = {"global": global_best, "per-league": per_league[slug]["params"], "pooled": pooled_best}[method]
        floor = min(base.values())
        beats = cands[method] < floor
        chosen[slug] = {
            "method": method if beats else "default",
            "params": params if beats else DEFAULTS,
            "log_loss": cands[method], "baseline_log_loss": floor,
            "scores": {"default": default_scores[slug]["log_loss"], **cands},
            "n_eval": global_scores[slug]["n"],
            "per_league_params": per_league[slug]["params"],
        }
        inc = (existing.get("leagues") or {}).get(slug) if not args.no_incumbent else None
        if inc and inc.get("params"):
            inc_params = {**DEFAULTS, **inc["params"]}
            new_m, new_p = chosen[slug]["method"], chosen[slug]["params"]
            same = (inc.get("method") == new_m or {inc.get("method"), new_m} <= {"global", "per-league"}) and \
                inc_params == {**DEFAULTS, **new_p}
            if not same:
                if new_m == "pooled":
                    a = pooled[slug]["losses"]
                else:
                    a = ev.score(new_p, rows, detail=True)["losses"]
                if inc.get("method") == "pooled":
                    b = (incumbent_pooled.get(slug) or pooled.get(slug) or {}).get("losses", {})
                else:
                    sc = ev.score(inc_params, rows, detail=True)
                    b = sc["losses"] if sc else {}
                gain = paired_gain(a, b)
                chosen[slug]["challenger"] = {"method": new_m, "params": new_p, **(gain or {})}
                if not gain or gain["hi"] >= 0:
                    chosen[slug]["method"] = inc.get("method", "per-league")
                    chosen[slug]["params"] = inc["params"]
                    chosen[slug]["log_loss"] = round(sum(v[0] for v in b.values()) / len(b), 5) if b else None
                    chosen[slug]["kept"] = "the parameters on file: the new choice does not beat them beyond noise"
        ch = chosen[slug].get("challenger")
        print("%-18s %9.5f %9.5f %9.5f %9.5f %9.5f   %-8s -> %s%s%s" % (
            slug, base["uniform"], base["home_advantage_only"], default_scores[slug]["log_loss"],
            cands["global"], cands["per-league"],
            ("%.5f" % cands["pooled"]) if "pooled" in cands else "n/a",
            chosen[slug]["method"], "" if beats else "  (no method beats the home-advantage prior)",
            "" if not ch else "  [%s on file; new %s %s: %+.4f (%+.4f, %+.4f)]" % (
                "kept" if chosen[slug].get("kept") else "replaced", ch["method"],
                {k: ch["params"][k] for k in ("xi", "ridge", "dc_weight")}, ch.get("d_ll", float("nan")),
                ch.get("lo", float("nan")), ch.get("hi", float("nan"))),
        ))

    print("\nglobal params:", global_best)
    if pooled_best:
        print("pooled params:", pooled_best)
    for slug, c in chosen.items():
        if c["method"] == "per-league":
            print(f"{slug}: {c['params']}")

    # keep any extra keys of an entry the tuner does not produce (e.g. params_before_oct2026)
    leagues = dict(existing.get("leagues", {}))
    for slug, c in chosen.items():
        old = {k: v for k, v in (leagues.get(slug) or {}).items() if k not in ("challenger", "kept")}
        leagues[slug] = {**{k: v for k, v in old.items() if k not in c}, **c}
    payload = {
        **{k: v for k, v in existing.items() if k not in ("tuned_at", "folds", "min_train", "margin", "global",
                                                           "pooled", "leagues", "fit")},
        "tuned_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "folds": args.folds, "min_train": args.min_train, "margin": args.margin,
        "fit": {"market_rows": market, "w_mkt": market_rates.W_MKT, "xi_mkt": market_rates.XI_MKT,
                "rho": fitting.club_rho(), "incumbent_rule": not args.no_incumbent, "pooled_kept": pooled_kept},
        "global": global_best, "pooled": pooled_best or existing.get("pooled"),
        "leagues": leagues,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
