#!/usr/bin/env python
"""
Fit the Liga model's constants by walk-forward evaluation.

`scripts/build_site_liga.py` carries reasoned starting points for the Elo home
advantage, K-factor and rank scale, and for the Dixon-Coles weight, ridge and time
decay. This replaces guesses with measurements.

Walk-forward, not a random split: the model predicts each match using only what was
known before it, exactly as the live build does. A shuffled split would let the model
train on the future and would flatter the time-decay parameter in particular.

Scored on log-loss (primary — it punishes confident errors, which is what a
probability dashboard must avoid) and Brier. Both are compared against two baselines,
because a grid search always produces a winner and the only question that matters is
whether the winner beats doing something trivial:

  - a fixed league-average prior, and
  - a home-advantage-only model that ignores team identity entirely.

    python scripts/tune_liga_model.py                     # committed history
    python scripts/tune_liga_model.py --store docs/liga/data/liga_store.json
    python scripts/tune_liga_model.py --quick             # coarse grid
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.liga.store import (  # noqa: E402
    empirical_calibration,
    load_store,
    training_frame,
)
from oddsmarkets.football.core import DixonColesModel, EloRatings, EnsembleModel  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("tune-liga")

PKG_DATA = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data"
HISTORY_CSV = PKG_DATA / "history_matches.csv"

FULL_GRID = {
    "xi": [0.0015, 0.0025, 0.0035, 0.0045, 0.0060],
    "dc_weight": [0.5, 0.65, 0.8, 0.9],
    "ridge": [0.2, 0.5, 1.0],
    "elo_home_advantage": [0.0, 30.0, 50.0, 70.0, 90.0, 110.0],
    "elo_rank_scale": [8.0, 10.0, 15.0],
}
QUICK_GRID = {
    "xi": [0.0025, 0.0035],
    "dc_weight": [0.65, 0.8],
    "ridge": [0.5],
    "elo_home_advantage": [50.0, 70.0, 90.0],
    "elo_rank_scale": [10.0],
}

_EPS = 1e-12


def log_loss(probs: list[tuple[float, float, float]], outcomes: list[int]) -> float:
    total = 0.0
    for p, o in zip(probs, outcomes):
        total -= math.log(max(p[o], _EPS))
    return total / len(probs) if probs else float("inf")


def brier(probs: list[tuple[float, float, float]], outcomes: list[int]) -> float:
    total = 0.0
    for p, o in zip(probs, outcomes):
        for i in range(3):
            total += (p[i] - (1.0 if i == o else 0.0)) ** 2
    return total / len(probs) if probs else float("inf")


def outcome_of(row) -> int:
    """0 home win, 1 draw, 2 away win."""
    if row.home_goals > row.away_goals:
        return 0
    return 1 if row.home_goals == row.away_goals else 2


def load_history(store_path: Path | None) -> pd.DataFrame:
    if store_path:
        logger.info("Loading matches from store %s", store_path)
        return training_frame(load_store(store_path))
    if HISTORY_CSV.exists():
        logger.info("Loading matches from %s", HISTORY_CSV)
        df = pd.read_csv(HISTORY_CSV, parse_dates=["match_date"])
        df["match_date"] = pd.to_datetime(df["match_date"], utc=True)
        return df.sort_values("match_date").reset_index(drop=True)
    logger.error(
        "No history. Run scripts/backfill_liga_history.py, or pass --store to use the "
        "committed Sofascore store."
    )
    return pd.DataFrame()


def evaluate(df: pd.DataFrame, params: dict, folds: int, min_train: int) -> dict | None:
    """Walk forward through the season in folds, scoring each unseen block."""
    n = len(df)
    if n < min_train + folds:
        return None

    cal = empirical_calibration(df)
    probs: list[tuple[float, float, float]] = []
    outcomes: list[int] = []

    step = max((n - min_train) // folds, 1)
    for start in range(min_train, n, step):
        train = df.iloc[:start]
        test = df.iloc[start:start + step]
        if test.empty:
            break

        elo = EloRatings(
            k_league=int(params.get("k_league", 20)),
            home_advantage=params["elo_home_advantage"],
        )
        teams = sorted(set(train["home_team"]) | set(train["away_team"]))
        elo.seed_from_ranking({t: i + 1 for i, t in enumerate(teams)}, n_teams=len(teams))
        for row in train.itertuples():
            elo.update(
                row.home_team, row.away_team,
                int(row.home_goals), int(row.away_goals),
                tournament_type="league", neutral=False,
            )

        dc = DixonColesModel(xi=params["xi"], ridge=params["ridge"])
        try:
            dc.fit(train)
        except Exception as exc:  # noqa: BLE001
            logger.debug("fit failed: %s", exc)
            continue

        model = EnsembleModel(
            dc, elo,
            dc_weight=params["dc_weight"],
            draw_rate=cal["draw_rate"], lam_scale=cal["lam_scale"],
            away_penalty=1.0,
        )

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

    if not probs:
        return None
    return {
        "log_loss": round(log_loss(probs, outcomes), 5),
        "brier": round(brier(probs, outcomes), 5),
        "n": len(probs),
    }


def baselines(df: pd.DataFrame, min_train: int) -> dict:
    """
    Two floors any fitted model must clear.

    A grid search always returns a best row; without these there is no way to tell
    whether it is actually worth anything.
    """
    test = df.iloc[min_train:]
    if test.empty:
        return {}
    outcomes = [outcome_of(r) for r in test.itertuples()]

    train = df.iloc[:min_train]
    h = float((train["home_goals"] > train["away_goals"]).mean())
    d = float((train["home_goals"] == train["away_goals"]).mean())
    a = max(1.0 - h - d, _EPS)

    flat = [(1 / 3, 1 / 3, 1 / 3)] * len(outcomes)
    prior = [(h, d, a)] * len(outcomes)
    return {
        "uniform": {"log_loss": round(log_loss(flat, outcomes), 5),
                    "brier": round(brier(flat, outcomes), 5)},
        "home_advantage_only": {"log_loss": round(log_loss(prior, outcomes), 5),
                                "brier": round(brier(prior, outcomes), 5)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, help="use a Sofascore store instead of the CSV")
    parser.add_argument("--quick", action="store_true", help="coarse grid")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--min-train", type=int, default=150)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--out", type=Path, help="write full results as JSON")
    args = parser.parse_args()

    df = load_history(args.store)
    if df.empty:
        return 1
    if len(df) < args.min_train + args.folds:
        logger.error(
            "Only %d matches; need at least %d. Backfill more seasons before tuning.",
            len(df), args.min_train + args.folds,
        )
        return 1

    logger.info("Tuning on %d matches (%s to %s)", len(df),
                df["match_date"].min().date(), df["match_date"].max().date())

    base = baselines(df, args.min_train)
    for name, scores in base.items():
        logger.info("baseline %-20s log_loss=%.5f brier=%.5f",
                    name, scores["log_loss"], scores["brier"])

    grid = QUICK_GRID if args.quick else FULL_GRID
    keys = list(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    logger.info("Evaluating %d parameter combinations × %d folds…", len(combos), args.folds)

    results = []
    for i, values in enumerate(combos, start=1):
        params = dict(zip(keys, values))
        scores = evaluate(df, params, args.folds, args.min_train)
        if scores:
            results.append({**params, **scores})
        if i % 20 == 0:
            logger.info("  %d/%d", i, len(combos))

    if not results:
        logger.error("No combination produced a usable fit")
        return 1

    results.sort(key=lambda r: r["log_loss"])
    best = results[0]

    print("\nTop %d by log-loss:\n" % args.top)
    header = f"{'log_loss':>9} {'brier':>8}  " + "  ".join(f"{k:>18}" for k in keys)
    print(header)
    print("-" * len(header))
    for r in results[: args.top]:
        print(f"{r['log_loss']:9.5f} {r['brier']:8.5f}  " +
              "  ".join(f"{r[k]:>18}" for k in keys))

    floor = min(s["log_loss"] for s in base.values()) if base else float("inf")
    print("\nBest vs best baseline: %.5f against %.5f (%s)" % (
        best["log_loss"], floor,
        "improvement" if best["log_loss"] < floor else "NO IMPROVEMENT — do not adopt",
    ))
    if best["log_loss"] >= floor:
        print(
            "\nThe fitted model does not beat a home-advantage-only prior on this data.\n"
            "That usually means too few matches rather than a broken model. Keep the\n"
            "current constants and re-run once more seasons are backfilled."
        )

    print("\nTo adopt, set in scripts/build_site_liga.py:")
    print(f"  ELO_HOME_ADVANTAGE = {best['elo_home_advantage']}")
    print(f"  ELO_RANK_SCALE     = {best['elo_rank_scale']}")
    print(f"  DC_WEIGHT          = {best['dc_weight']}")
    print(f"  DC_RIDGE           = {best['ridge']}")
    print(f"  DC_XI              = {best['xi']}")
    print(f"  # walk-forward log-loss {best['log_loss']}, brier {best['brier']}, "
          f"n={best['n']}")

    if args.out:
        args.out.write_text(
            json.dumps({"baselines": base, "results": results}, indent=2), encoding="utf-8"
        )
        logger.info("Wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
