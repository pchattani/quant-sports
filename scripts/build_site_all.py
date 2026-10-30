#!/usr/bin/env python
"""
Build the combined football hub: every league and cup in the registry plus the
Argentine Liga Profesional, into docs/site/data/.

Like the single-competition builds, this emits only JSON. docs/site/{index.html,
assets/} are hand-maintained and shipped verbatim, and docs/site/ becomes the root
of the published Pages repo. Each competition gets its own directory of payloads,
loaded lazily by the front-end, and docs/site/data/competitions.json is the index
that drives the competition picker and the tab list.

Per competition, on top of the simulation payloads (table, probabilities,
bracket, strength, history, market):

  fixtures.json         every match of the season with status, score, xG and —
                        for matches still to play — the model's win/draw/loss
                        probabilities, expected goals, most likely score and fair
                        decimal odds
  players_live.json     every player's season line: totals, per-90 rates and
                        percentiles against positional peers, with the metric
                        catalogue that drives the front-end
  players/<club>.json   match-by-match logs (and shots) for a club's players
  team_stats.json       per-team match statistics and season averages with
                        percentiles within the competition
  matches.json          the season's matches with a detail page
  matches/<id>.json     one match: lineups with each player's line, the team-stat
                        sheet, shots, momentum, incidents, ratings

And site-wide: data/hub.json (the scoreboard: results and fixtures across every
competition for the coming week, with the model's numbers) and data/search.json
(every club and player, for the search box).

Per league, sensitivity.json: each club's title, band and relegation odds and
expected points re-simulated at a few shifts of its strength, for the transfer
simulator (analytics/sensitivity.py). Last, the value layer (data/value/): the
player value model fitted walk-forward over every store's line-ups, the
leaderboard payloads, and one strengths-and-needs file per league club
(analytics/value.py, analytics/value_payloads.py).

Every competition degrades independently. A league whose store is missing or
empty is listed in the index with `ok: false` and skipped; one that fails mid-build
is logged and skipped the same way; a cup whose main phase has not started is
built as fixtures only. The Argentine build is scripts/build_site_liga.py pointed
at a directory under the combined site, so its payloads and its own tests are
untouched; the analytics payloads are added on top from the same store.

    python scripts/build_site_all.py
    python scripts/build_site_all.py --sims 20000 --no-market      # faster local iteration
    python scripts/build_site_all.py --only premier-league --only mls
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from typing import Any

import numpy as np

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.analytics.glossary import build_glossary  # noqa: E402
from oddsmarkets.football.analytics.insights import build_analytics  # noqa: E402
from oddsmarkets.football.analytics.players import METRICS, POSITION_LABELS, add_percentiles, set_fallback_positions  # noqa: E402
from oddsmarkets.football.analytics.unified import MATCH_PAGE_DAYS  # noqa: E402
from oddsmarkets.football.analytics.teams import TEAM_METRICS, season_team_stats  # noqa: E402
from oddsmarkets.football.competitions.cup import store as cup_store  # noqa: E402
from oddsmarkets.football.analytics.confederations import confederation_of  # noqa: E402
from oddsmarkets.football.competitions.cup.config import CUPS, CUP_FAMILIES, INTERNATIONALS, ROUND_LABELS as CUP_ROUND_LABELS, CupConfig  # noqa: E402
from oddsmarkets.football.competitions.cup.simulator import AVERAGE, CupSimulator  # noqa: E402
from oddsmarkets.football.competitions.league.config import (  # noqa: E402
    LEAGUES,
    LIGA_ARGENTINA_SLUG,
    LIGUILLA_ROUND_LABELS,
    LIGUILLA_ROUNDS,
    MLS_ROUND_LABELS,
    MLS_ROUNDS,
    LeagueConfig,
    with_sims,
)
from oddsmarkets.football.competitions.league.simulator import LeagueResults, LeagueSimulator  # noqa: E402
from oddsmarkets.football.competitions.league.store import (  # noqa: E402
    _POSTPONED,
    _status_of,
    aggregate_players,
    empirical_calibration,
    last_finished_date,
    league_state_from_store,
    load_store,
    match_details,
    player_match_logs,
    shots_by_player,
    store_age_hours,
    team_match_stats,
    team_xg_map,
    training_frame,
)
from oddsmarkets.football.competitions.liga import store as _liga  # noqa: E402
from oddsmarkets.football.competitions.liga.store import overdue as _liga_overdue  # noqa: E402
from oddsmarkets.football.competitions.liga.store import store_path as _liga_store_path  # noqa: E402
from oddsmarkets.football.core.markets import build_match_markets, build_outright_markets  # noqa: E402
from oddsmarkets.football.competitions.liga.strength import (  # noqa: E402
    FORM_WINDOW,
    build_team_strength,
    elo_trajectories,
)
from oddsmarkets.football.core import (  # noqa: E402
    DixonColesModel,
    EloRatings,
    EnsembleModel,
    GoldenBootModel,
)
from oddsmarkets.football.sources.teams import normalize_team_name  # noqa: E402
from oddsmarkets.football.sources import market_rates  # noqa: E402
from oddsmarkets.football.competitions.league import fitting  # noqa: E402
from oddsmarkets.football.analytics import lineup_strength  # noqa: E402
from oddsmarkets.football.sources import kalshi_rates  # noqa: E402
from oddsmarkets.football.analytics.archive import load_archive  # noqa: E402
from oddsmarkets.football.analytics.sensitivity import league_sensitivity, liga_sensitivity  # noqa: E402
from oddsmarkets.football.analytics import race as _race  # noqa: E402
from oddsmarkets.football.analytics.pool import block_bridges, connections_from_frames, dc_score_matrix, outcome_probs  # noqa: E402
import scripts.build_site_global as site_global  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("build-all")

SITE_DIR = ROOT / "docs" / "site"
DATA_DIR = SITE_DIR / "data"
SEASONS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "seasons.json"
LIGA_STORE = _liga_store_path()       # docs/site/data/liga-argentina/store.json (legacy docs/liga copy before)
# How many cup matches bridge each league into the pooled fit, and each
# continental block to the others, from the last pooled frame.
POOL_CONNECTIONS: dict[str, int] = {}
# Market-implied goal rates of past matches as extra Dixon-Coles rows (market_rates.py;
# docs/research/football_edge.md). Off with --no-market-rates; a no-op without the
# football-data files, so CI and a fresh clone build exactly the goals/xG model.
USE_MARKET_RATES = True
POOL_BRIDGES: dict[str, int] = {}
# Per-club sensitivity curves for the transfer simulator (off with --no-sensitivity), with
# a time budget per league so a slow machine never stretches the hourly build.
USE_SENSITIVITY = True
# slug -> gid -> line-up term of fixtures whose confirmed XIs are posted (main(), lineup_strength.live_terms).
LINEUP_TERMS: dict[str, dict[str, dict]] = {}


# A fit identifies rho only from its goals rows (matches without xG on both sides; xG and market-rate rows carry
# no tau). Below this many it holds the club rho instead of leaving rho at the optimiser's start (-0.1) or a bound
# (docs/MODELS.md 2.4). On the stores of 22 October 2026 the international frame has about 3,560 goals rows
# (the backfilled earlier editions) and its own rho is identified: -0.06 by profile likelihood, 95% CI -0.11 to
# -0.02, which holds the club value -0.045 (docs/research/football_edge.md 3.4).
MIN_GOALS_ROWS_FOR_RHO = 300


def rho_hold(df) -> float | None:
    """None (fit rho) when `df` has enough goals rows to identify it, else the club rho to hold."""
    if df is None or not len(df):
        return fitting.club_rho()
    if "home_xg" not in df.columns or "away_xg" not in df.columns:
        n = len(df)
    else:
        n = int((~(np.isfinite(df["home_xg"].to_numpy(float)) & np.isfinite(df["away_xg"].to_numpy(float)))).sum())
    return None if n >= MIN_GOALS_ROWS_FOR_RHO else fitting.club_rho()


PARTIAL_FIELD_NOTE = ("The top-flight clubs have not entered this edition yet (they join in a later round), so the "
                      "simulation knows only the clubs already in the draw. Winner and final chances are not shown until "
                      "they enter; the round-by-round chances count only today's field.")


def cup_field_partial(cfg, state, top_flight: dict[str, set[str]] | None = None) -> bool:
    """
    A national cup whose current field has no club of the country's followed top league yet (the FA Cup and the
    Coupe de France before the top flight enters): the simulated winner would be the best of the clubs already in
    the draw, a lower-division side (Waltham Abbey 10% to win the FA Cup, 22 Oct 2026).

    `top_flight` (league slug -> its clubs this season, from top_flight_clubs) is what membership means: the state's
    team_league maps every club of the country to the league (it comes from the country code), so without it any
    English club counted as Premier League and the rule never fired (Burton Albion 15% to win the FA Cup, 22 Oct).
    """
    if getattr(cfg, "family", "") != "domestic":
        return False
    field = [t for t in getattr(state, "teams", []) if t != AVERAGE]
    league_of = getattr(state, "team_league", {}) or {}
    def top(t: str) -> bool:
        league = league_of.get(t)
        clubs = (top_flight or {}).get(league or "")
        # A league whose clubs are unknown (no teams.json: its build failed or was not run) keeps the country reading.
        return bool(league) and (t in clubs if clubs else True)

    return bool(field) and not any(top(t) for t in field)


def top_flight_clubs(state) -> dict[str, set[str]]:
    """League slug -> the clubs of its current season (its teams.json, written by this build's league pass)."""
    out: dict[str, set[str]] = {}
    for league in set((getattr(state, "team_league", {}) or {}).values()):
        teams = (_read_json(DATA_DIR / str(league) / "teams.json", {}) or {}).get("teams") or {}
        out[str(league)] = set(teams)
    return out


def lineup_lines(fixtures: list[dict]) -> dict[str, dict[str, float]]:
    """match id -> the H/D/A after the line-up term, for the model-v-market comparison."""
    return {str(r["id"]): {"home": r["model"]["h"], "draw": r["model"]["d"], "away": r["model"]["a"]}
            for r in fixtures if (r.get("model") or {}).get("lineups")}
SENS_BUDGET_S = 90.0

# Model constants used when a league has no tuned entry in model_params.json —
# the Argentine starting points with a slightly larger home advantage. The tuned
# values come from scripts/tune_league_models.py, which scores each league's own
# constants against one global set and a pooled all-league fit by walk-forward
# log-loss and records the winner per league.
DEFAULT_PARAMS = {
    "elo_home_advantage": 65.0, "k_league": 20,
    "dc_weight": 0.80, "ridge": 0.5, "xi": 0.0035,
}
MODEL_PARAMS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "model_params.json"
# The match model's walk-forward calibration (oddsmarkets/football/research/site_calibration.py, committed), published as
# data/calibration.json for the kit's "How sure are we?" (QK.calib.find reads metrics.model).
CALIBRATION_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "calibration.json"


def model_params_for(slug: str) -> tuple[dict, str]:
    """(params, method) for a league: its tuned entry, or the defaults."""
    tuned = _read_json(MODEL_PARAMS_PATH, {}).get("leagues", {}).get(slug)
    if tuned and tuned.get("params"):
        return {**DEFAULT_PARAMS, **tuned["params"]}, tuned.get("method", "tuned")
    return dict(DEFAULT_PARAMS), "default"

STALE_AFTER_HOURS = 24.0
# A competition with no fixture within a week either side is "dormant": the hourly
# task refreshes its fixtures once a day, so a store a day and an hour old is on
# schedule, not stale.
DORMANT_STALE_AFTER_HOURS = 50.0
DORMANT_WINDOW_DAYS = 7
SEASON_STALE_DAYS = 30


def _stale_after(store: dict) -> float:
    """Hours after which a store's data counts as stale: longer for a dormant competition."""
    now = datetime.now(timezone.utc)
    lo = (now - timedelta(days=DORMANT_WINDOW_DAYS)).date().isoformat()
    hi = (now + timedelta(days=DORMANT_WINDOW_DAYS)).date().isoformat()
    ms = store.get("matches") or {}
    for m in (ms.values() if isinstance(ms, dict) else ms):
        d = str((m or {}).get("date") or "")[:10] if isinstance(m, dict) else ""
        if d and lo <= d <= hi:
            return STALE_AFTER_HOURS
    return DORMANT_STALE_AFTER_HOURS


HUB_DAYS_BACK = 3
HUB_DAYS_AHEAD = 7

TABS_LEAGUE = ["overview", "table", "fixtures", "probs", "power", "team", "players", "analytics", "matches", "market", "history", "methodology"]
TABS_PLAYOFF = ["overview", "table", "bracket", "fixtures", "probs", "power", "team", "players", "analytics", "matches", "market", "history", "methodology"]
TABS_CONFERENCE = TABS_PLAYOFF
TABS_CUP = ["overview", "table", "bracket", "fixtures", "probs", "power", "team", "players", "analytics", "matches", "market", "history", "methodology"]
TABS_KNOCKOUT = ["overview", "bracket", "fixtures", "probs", "power", "team", "players", "analytics", "matches", "market", "history", "methodology"]
TABS_FIXED = ["overview", "bracket", "fixtures", "probs", "matches", "history", "methodology"]
TABS_PRE = ["overview", "fixtures", "matches", "methodology"]
TABS_INTERNATIONAL = ["overview", "table", "bracket", "fixtures", "power", "team", "players", "analytics", "matches", "market", "methodology"]
TABS_LIGA = ["overview", "zones", "table", "bracket", "fixtures", "anual", "relegation", "probs", "power", "team", "players", "analytics", "matches", "market", "history", "methodology"]

# Why a cup is fixtures-only before its main phase, per competition.
PRE_PHASE_NOTES = {
    "caf-champions-league": "Qualifying rounds are in progress; the group stage begins on 27 November.",
    "concacaf-champions-cup": "The next edition begins in February; the bracket is simulated once the draw is made.",
    "afc-champions-league": "The league stage has not started.",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(out_dir: Path, name: str, payload: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read %s: %s", path, exc)
        return default


def fallback_positions(squads: dict | None, stores: Iterable[dict] = ()) -> dict[str, str]:
    """
    Player id -> position letter from the current squads (first) and every given store's player metadata, for
    players a competition's store saw only in line-ups without a position (UEFA qualifiers, clubs outside the
    followed leagues). Installed with players.set_fallback_positions before the competitions are built.
    """
    out: dict[str, str] = {}
    for team in ((squads or {}).get("teams") or {}).values():
        for p in (team or {}).get("players") or []:
            if isinstance(p, dict) and p.get("id") is not None and p.get("pos"):
                out.setdefault(str(p["id"]), str(p["pos"]))
    for store in stores:
        for pid, m in ((store or {}).get("players") or {}).items():
            if isinstance(m, dict) and m.get("pos"):
                out.setdefault(str(pid), str(m["pos"]))
    return out


def _slug(team: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in str(team).lower()).strip("-")


CRESTS_DIR = SITE_DIR / "assets" / "crests"


def crests_enabled() -> bool:
    """Club crests are Sofascore team images, shown small as identifiers under the user's unclear-terms rule (30 Oct
    2026, credited on the Terms page). SOURCE_SOFASCORE_CRESTS_ENABLED=0 drops every crest from the payloads."""
    from oddsmarkets.common.polite import flag_on
    return flag_on("SOURCE_SOFASCORE_CRESTS_ENABLED")


def crest_path(league_slug: str, team_id: int | None) -> str | None:
    """Relative path of a committed crest, or None when none has been fetched (or crests are switched off)."""
    if not team_id or not crests_enabled():
        return None
    rel = f"assets/crests/{team_id}.png"
    return rel if (SITE_DIR / rel).exists() else None


# ── model ────────────────────────────────────────────────────────────────────

class LeagueView:
    """
    One league's view of a Dixon-Coles model fitted on every league at once.

    The pooled fit prefixes team names with the league slug so nothing crosses
    between leagues; this maps the league's plain names onto that, and presents a
    `params_` dict re-keyed to plain names so EnsembleModel and the strength module
    read attack/defence/rho/home_adv exactly as from a per-league fit.
    """

    def __init__(self, pooled: DixonColesModel, slug: str) -> None:
        self._dc = pooled
        self._prefix = slug + ":"
        self.params_: dict[str, float] = {}
        for key, value in pooled.params_.items():
            for kind in ("attack_", "defense_"):
                if key.startswith(kind + self._prefix):
                    self.params_[kind + key[len(kind) + len(self._prefix):]] = value
                    break
            else:
                if not key.startswith(("attack_", "defense_")):
                    self.params_[key] = value
        self.xi = pooled.xi
        self.ridge = pooled.ridge

    @property
    def is_fitted(self) -> bool:
        return bool(self._dc.params_)

    def predict_match(self, home: str, away: str, neutral: bool = True, max_goals: int = 8):
        return self._dc.predict_match(self._prefix + home, self._prefix + away,
                                      neutral=neutral, max_goals=max_goals)


def pooled_training_frame(stores: dict[str, dict], cup_stores: dict[str, dict] | None = None,
                          xi: float | None = None):
    """
    Every league's matches under its own prefix, plus every cup's with each club
    under the prefix of the league it plays in — which is what connects the
    leagues into one graph. A cup entrant from a league the site does not follow
    keeps the cup's prefix. `xi` is the pooled fit's decay (default: the `pooled`
    block of model_params.json), against which the market rows' own decay is set.
    """
    import pandas as pd

    from oddsmarkets.football.competitions.cup.config import COUNTRY_LEAGUE

    parts = []
    cup_frames: dict[str, Any] = {}
    league_teams: dict[str, set] = {}
    if xi is None:
        xi = float((_read_json(MODEL_PARAMS_PATH, {}).get("pooled") or {}).get("xi", DEFAULT_PARAMS["xi"]))
    for slug, store in stores.items():
        df = training_frame(store, LEAGUES[slug])
        if len(df):
            league_teams[slug] = set(df["home_team"]) | set(df["away_team"])
            parts.append(fitting.pooled_part(df, slug, xi, market=USE_MARKET_RATES))
    for slug, store in (cup_stores or {}).items():
        df = cup_store.training_frame(store)
        if not len(df):
            continue
        # Kalshi market rows for the UEFA cups (kalshi_rates; off unless switched on), matched on plain names.
        kx = (kalshi_rates.rows(df, slug, xi_fit=xi)
              if USE_MARKET_RATES and kalshi_rates.on() and slug in kalshi_rates.CUP_SLUGS else None)

        def prefixed(name, country):
            league = COUNTRY_LEAGUE.get(str(country or ""))
            if league and name in league_teams.get(league, set()):
                return f"{league}:{name}"
            return f"{slug}:{name}"

        df = df.assign(
            home_team=[prefixed(n, c) for n, c in zip(df["home_team"], df["home_country"])],
            away_team=[prefixed(n, c) for n, c in zip(df["away_team"], df["away_country"])],
        )
        parts.append(df[["game_id", "home_team", "away_team", "home_goals", "away_goals", "match_date", "weight"]
                        + [c for c in ("home_xg", "away_xg") if c in df.columns]])
        if kx is not None and len(kx):
            kx = kx.assign(home_team=[prefixed(n, c) for n, c in zip(kx["home_team"], kx["home_country"])],
                           away_team=[prefixed(n, c) for n, c in zip(kx["away_team"], kx["away_country"])])
            parts.append(kx[["game_id", "home_team", "away_team", "home_goals", "away_goals", "match_date", "weight",
                             "home_xg", "away_xg"]])
            logger.info("%s: %d Kalshi market-rate rows added to the pooled fit", slug, len(kx))
        cup_frames[slug] = df
    POOL_CONNECTIONS.clear()
    POOL_CONNECTIONS.update(connections_from_frames(cup_frames, list(stores)))
    POOL_BRIDGES.clear()
    POOL_BRIDGES.update(block_bridges(cup_frames))
    if not parts:
        return None
    return pd.concat(parts, ignore_index=True).sort_values("match_date").reset_index(drop=True)


class CupView:
    """
    A cup's view of the pooled Dixon-Coles fit: each club is looked up under the
    prefix of its league where it has one, else under the cup's own prefix. A
    club under neither (a first appearance) gets the model's default — the
    pool's average — which EnsembleModel also blends toward Elo for.
    """

    def __init__(self, pooled: DixonColesModel, slug: str, team_league: dict[str, str]) -> None:
        self._dc = pooled
        self._slug = slug
        self._map: dict[str, str] = {}
        for team, league in team_league.items():
            if f"attack_{league}:{team}" in pooled.params_:
                self._map[team] = f"{league}:{team}"
        self.params_: dict[str, float] = {k: v for k, v in pooled.params_.items() if not k.startswith(("attack_", "defense_"))}
        for k, v in pooled.params_.items():
            for kind in ("attack_", "defense_"):
                if k.startswith(kind):
                    full = k[len(kind):]
                    if full.startswith(slug + ":"):
                        self.params_[kind + full[len(slug) + 1:]] = v
        for team, full in self._map.items():
            for kind in ("attack_", "defense_"):
                if kind + full in pooled.params_:
                    self.params_[kind + team] = pooled.params_[kind + full]
        self.xi, self.ridge = pooled.xi, pooled.ridge

    def _name(self, team: str) -> str:
        return self._map.get(team, f"{self._slug}:{team}")

    @property
    def is_fitted(self) -> bool:
        return bool(self._dc.params_)

    def predict_match(self, home: str, away: str, neutral: bool = True, max_goals: int = 8):
        return self._dc.predict_match(self._name(home), self._name(away), neutral=neutral, max_goals=max_goals)


def fit_pooled(stores: dict[str, dict], params: dict, cup_stores: dict[str, dict] | None = None) -> DixonColesModel | None:
    """The pooled fit, once per build: the leagues whose tuned choice was `pooled`, and every cup."""
    df = pooled_training_frame(stores, cup_stores, xi=float(params["xi"]))
    if df is None or len(df) < 50:
        return None
    dc = fitting.new_dc(params["xi"], params["ridge"], prior_group=fitting.tier_function() if fitting.tier_prior_on() else None)
    try:
        dc.fit(df)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pooled Dixon-Coles fit failed (%s) — those leagues fall back to their own fit", exc)
        return None
    logger.info("pooled Dixon-Coles fitted on %d matches across %d leagues", len(df), len(stores))
    return dc


def build_model(train_df, teams: list[str], previous_rank: dict[str, int], cfg: LeagueConfig,
                params: dict | None = None, pooled: DixonColesModel | None = None):
    """
    Fit the ensemble for one league.

    Elo is seeded from last season's final table; clubs absent from it (promoted)
    start at the bottom, which is the right prior. The draw rate and lambda scale are
    measured from this league's own matches rather than inherited.
    """
    params = params or dict(DEFAULT_PARAMS)
    cal = empirical_calibration(train_df)
    logger.info(
        "%s calibration: draw_rate=%.3f mean_goals=%.2f home_win_rate=%.3f",
        cfg.slug, cal["draw_rate"], cal["mean_goals"], cal["home_win_rate"],
    )
    elo = EloRatings(k_league=int(params["k_league"]), home_advantage=float(params["elo_home_advantage"]))
    bottom = cfg.n_teams
    ranking = {t: int(previous_rank.get(t, bottom)) for t in teams}
    elo.seed_from_ranking(ranking, n_teams=cfg.n_teams)
    if train_df is not None and len(train_df):
        for row in train_df.itertuples():
            elo.update(
                row.home_team, row.away_team, int(row.home_goals), int(row.away_goals),
                tournament_type="league", neutral=False,
            )

    if pooled is not None:
        dc = LeagueView(pooled, cfg.slug)
    else:
        dc = fitting.new_dc(params["xi"], params["ridge"])
        if train_df is not None and len(train_df) >= 50:
            try:
                # Market rows feed the Dixon-Coles fit only; Elo and the calibration above
                # read the plain frame, one row per match. The tuner builds the same frame.
                dc.fit(fitting.dc_frame(train_df, cfg.slug, params["xi"], market=USE_MARKET_RATES))
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: Dixon-Coles fit failed (%s) — Elo only", cfg.slug, exc)
        else:
            logger.warning("%s: only %d training matches — Elo only", cfg.slug,
                           0 if train_df is None else len(train_df))

    return EnsembleModel(
        dc, elo,
        dc_weight=float(params["dc_weight"]) if dc.is_fitted else 0.0,
        draw_rate=cal["draw_rate"], lam_scale=cal["lam_scale"],
        away_penalty=1.0,
    ), cal


# ── match predictions ────────────────────────────────────────────────────────

def _odds(p: float) -> float | None:
    return round(1.0 / p, 2) if p > 0.005 else None


def predict_fixture(model, home: str, away: str, neutral: bool = False, lineup: dict | None = None) -> dict | None:
    """
    The model's line on one match: win/draw/loss, expected goals, over 2.5, both
    to score, the most likely score, and the fair decimal odds (1/p, no margin).
    None when the model cannot price the pair (a club it has never seen).
    `lineup` (an applied line-up term, lineup_strength.live_terms) tilts the score
    matrix by the confirmed XIs (docs/MODELS.md 2.6).
    """
    if model is None:
        return None
    try:
        p = model.predict(home, away, neutral=neutral)
    except Exception:  # noqa: BLE001
        return None
    m = np.asarray(p.score_matrix, dtype=float)
    if m.size == 0 or not np.isfinite(m).all():
        return None
    lam_h, lam_a = float(p.lambda_home), float(p.lambda_away)
    h, d, a = float(p.home_win), float(p.draw), float(p.away_win)
    if lineup and lineup.get("applied") and lineup.get("d") is not None:
        m = lineup_strength.tilt_matrix(m / m.sum(), lam_h, lam_a, float(lineup["d"]), float(lineup["c"]))
        i_, j_ = np.indices(m.shape)
        h, d, a = float(m[i_ > j_].sum()), float(m[i_ == j_].sum()), float(m[i_ < j_].sum())
        lam_h = float((m.sum(1) * np.arange(m.shape[0])).sum())
        lam_a = float((m.sum(0) * np.arange(m.shape[1])).sum())
    goals = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
    i, j = np.unravel_index(int(m.argmax()), m.shape)
    return {
        "h": round(h, 4), "d": round(d, 4), "a": round(a, 4),
        "lh": round(lam_h, 2), "la": round(lam_a, 2),
        "o25": round(float(m[goals >= 3].sum()), 4), "btts": round(float(m[1:, 1:].sum()), 4),
        "score": f"{int(i)}-{int(j)}", "p_score": round(float(m[i, j]), 4),
        "fair": [_odds(h), _odds(d), _odds(a)],
    }


# ── payloads ─────────────────────────────────────────────────────────────────

def _band_list(cfg) -> list[dict]:
    return [{"key": b.key, "label": b.label, "first": b.first, "last": b.last, "kind": b.kind}
            for b in cfg.bands]


def _standing_rows(state, results: LeagueResults, cfg: LeagueConfig, zone: str | None) -> list[dict]:
    rows = []
    dist = results.p_conf_position if (cfg.conferences and zone) else results.p_position
    for pos, (team, rec) in enumerate(state.standings(zone), start=1):
        q = results.points_quantiles.get(team, (0.0, 0.0, 0.0))
        rows.append({
            "pos": pos, "team": team,
            "played": rec.played, "w": rec.won, "d": rec.drawn, "l": rec.lost,
            "gf": rec.gf, "ga": rec.ga, "gd": rec.gd, "pts": rec.points,
            "exp_pts": round(results.expected_points.get(team, 0.0), 2),
            "p05": round(q[0], 1), "p50": round(q[1], 1), "p95": round(q[2], 1),
            "p_title": round(results.p_title.get(team, 0.0), 5),
            "p_pos": [round(p, 5) for p in dist.get(team, [])],
            "bands": {b.key: round(results.p_in_band(b.key, team), 5) for b in cfg.bands},
        })
    return rows


def derived_groups(matches, max_size: int = 6) -> dict[str, list[dict]]:
    """
    Group tables for a league phase whose store carries no groups: the league-stage pairings' connected components
    (sides that play each other), each a group of at most `max_size`, ordered by points, goal difference and goals,
    labelled "1", "2", ... in order of their strongest side's points. {} when the matches do not split that way.
    """
    league = [m for m in matches if (m.stage or "league") == "league" and m.home_team and m.away_team]
    if not league:
        return {}
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for m in league:
        a, b = find(m.home_team), find(m.away_team)
        if a != b:
            parent[a] = b
    comps: dict[str, list[str]] = {}
    for t in list(parent):
        comps.setdefault(find(t), []).append(t)
    if len(comps) < 2 or any(len(v) > max_size or len(v) < 2 for v in comps.values()):
        return {}
    tables = []
    for members in comps.values():
        rec = {t: {"pos": 0, "team": t, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "gd": 0, "pts": 0, "exp_pts": None,
                   "p05": None, "p50": None, "p95": None, "p_title": None, "p_pos": [], "bands": {}} for t in members}
        for m in league:
            if m.home_team not in rec or not m.is_finished or m.home_goals is None or m.away_goals is None:
                continue
            h, a = rec[m.home_team], rec[m.away_team]
            for r, gf, ga in ((h, m.home_goals, m.away_goals), (a, m.away_goals, m.home_goals)):
                r["played"] += 1; r["gf"] += gf; r["ga"] += ga
                r["w" if gf > ga else "d" if gf == ga else "l"] += 1
        rows = list(rec.values())
        for r in rows:
            r["gd"] = r["gf"] - r["ga"]
            r["pts"] = 3 * r["w"] + r["d"]
        rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))
        for i, r in enumerate(rows, start=1):
            r["pos"] = i
        tables.append(rows)
    tables.sort(key=lambda rows: (-rows[0]["pts"], -rows[0]["gd"], rows[0]["team"]))
    return {str(i): rows for i, rows in enumerate(tables, start=1)}


def _fixture_rows(matches) -> list[dict]:
    return [
        {
            "round": m.round_name, "home": m.home_team, "away": m.away_team,
            "hg": m.home_goals, "ag": m.away_goals,
            "date": m.date.strftime("%Y-%m-%d") if m.date else None,
            "done": m.is_finished, "stage": m.stage, "id": m.game_id,
        }
        for m in sorted(matches, key=lambda x: (x.date or datetime.max.replace(tzinfo=timezone.utc), x.game_id))
    ]


def build_table_json(state, results: LeagueResults, cfg: LeagueConfig) -> dict:
    payload = {
        "season": state.season_name,
        "bands": _band_list(cfg),
        "tiebreak": list(cfg.tiebreak),
        "h2h_tiebreak": cfg.h2h_tiebreak,
        "fixtures": _fixture_rows(state.finished + state.remaining),
        "games_played": state.games_played,
        "total_games": state.total_league_games,
        "matches_per_team": state.matches_per_team,
        "updated_at": _now(),
    }
    if cfg.conferences:
        payload["conferences"] = {
            conf: _standing_rows(state, results, cfg, conf) for conf in cfg.conferences
        }
        payload["overall"] = _standing_rows(state, results, cfg, None)
        payload["overall_label"] = "Supporters' Shield"
    else:
        payload["standings"] = _standing_rows(state, results, cfg, None)
        if cfg.split:
            sp = cfg.split
            payload["split"] = {"top": sp.top, "europe": sp.europe, "relegation": sp.relegation, "halve_points": sp.halve_points}
            for row in payload["standings"]:
                row["p_final_pos"] = [round(p, 5) for p in results.p_final_position.get(row["team"], [])]
                row["p_top_group"] = round(sum(row["p_pos"][: sp.top]), 5)
    return payload


def build_probs_json(state, results: LeagueResults, cfg: LeagueConfig) -> dict:
    teams = []
    for team in state.teams:
        row = {
            "team": team, "conference": state.zone_of(team),
            "exp_pts": round(results.expected_points.get(team, 0.0), 2),
            "p_title": round(results.p_title.get(team, 0.0), 5),
            "bands": {b.key: round(results.p_in_band(b.key, team), 5) for b in cfg.bands},
        }
        if cfg.playoff:
            row["p_playoffs"] = round(results.p_playoffs.get(team, 0.0), 5)
            row["p_cup"] = round(results.p_cup.get(team, 0.0), 5)
            row["p_conference"] = round(results.p_reach.get(team, {}).get("final", 0.0), 5)
        teams.append(row)
    sort_key = "p_cup" if cfg.playoff else "p_title"
    teams.sort(key=lambda t: -t.get(sort_key, 0.0))
    out = {"teams": teams, "bands": _band_list(cfg), "has_playoff": bool(cfg.playoff), "updated_at": _now()}
    # What rides on the next fixtures (the Race tab): the same simulated seasons split by each result.
    stakes = _race.stakes_payload(results, cfg)
    if stakes:
        out["stakes"] = stakes
    return out


def build_bracket_json(state, results: LeagueResults, cfg: LeagueConfig) -> dict:
    """MLS: likely seeds per conference and the probability ladder. Liga MX: the Liguilla ladder."""
    po = cfg.playoff
    if po.kind == "liguilla":
        standings = state.standings()
        return {
            "kind": "liguilla",
            "rounds": list(LIGUILLA_ROUNDS),
            "round_labels": LIGUILLA_ROUND_LABELS,
            "format": {"direct": po.direct, "play_in": list(po.play_in)},
            "seeds": {"Liguilla": [
                {"seed": i + 1, "team": standings[i][0] if i < len(standings) else None, "direct": i + 1 <= po.direct}
                for i in range(po.qualifiers)
            ]},
            "confirmed": state.league_complete,
            "reach": {t: {r: round(p, 5) for r, p in reach.items()} for t, reach in results.p_reach.items()},
            "p_playoffs": {t: round(p, 5) for t, p in results.p_playoffs.items()},
            "p_cup": {t: round(p, 5) for t, p in results.p_cup.items()},
            "forced": {" v ".join(sorted(pair)): winner for pair, winner in state.playoff_results.items()},
            "note": (
                "Seeds 1-6 qualify directly; 7-10 play a play-in (7 hosts 8, 9 hosts 10; the "
                "7v8 winner is seed 7, its loser hosts the 9v10 winner for seed 8). Quarter-finals, "
                "semi-finals and the final are two-legged with the higher seed at home in the "
                "second leg, re-seeded after each round. Ties already decided are taken as played."
            ),
            "updated_at": _now(),
        }
    seeds = {}
    for conf in cfg.conferences or ():
        standings = state.standings(conf)
        seeds[conf] = [
            {"seed": i + 1, "team": standings[i][0] if i < len(standings) else None,
             "direct": i + 1 <= po.direct_per_conference}
            for i in range(po.qualifiers_per_conference)
        ]
    return {
        "rounds": list(MLS_ROUNDS),
        "round_labels": MLS_ROUND_LABELS,
        "format": {
            "direct_per_conference": po.direct_per_conference,
            "wildcard_seeds": list(po.wildcard_seeds),
            "round_one_best_of": po.round_one_best_of,
        },
        "seeds": seeds,
        "confirmed": state.league_complete,
        "reach": {t: {r: round(p, 5) for r, p in reach.items()} for t, reach in results.p_reach.items()},
        "p_playoffs": {t: round(p, 5) for t, p in results.p_playoffs.items()},
        "p_cup": {t: round(p, 5) for t, p in results.p_cup.items()},
        "forced": {" v ".join(sorted(pair)): winner for pair, winner in state.playoff_results.items()},
        "note": (
            "Round One is a best-of-three with the higher seed hosting games one and "
            "three; winners are re-seeded so the best remaining seed meets the worst. "
            "Later rounds are single matches hosted by the higher seed, and MLS Cup by "
            "the finalist with the better regular season. Ties already decided in the "
            "postseason are taken as played."
        ),
        "updated_at": _now(),
    }


def build_strength_json(model, state, store, cfg) -> dict:
    rows = build_team_strength(model, state, state.teams, xg_by_match=team_xg_map(store, cfg))

    params, _ = model_params_for(cfg.slug)

    def _elo_factory():
        elo = EloRatings(k_league=int(params["k_league"]), home_advantage=float(params["elo_home_advantage"]))
        elo.seed_from_ranking(
            {t: int(state.previous_rank.get(t, cfg.n_teams)) for t in state.teams},
            n_teams=max(cfg.n_teams, len(state.teams)),
        )
        return elo

    return {
        "form_window": FORM_WINDOW,
        "rows": [
            {
                "team": r.team, "conference": state.zone_of(r.team),
                "elo": r.elo, "attack": r.attack, "defence": r.defence,
                "strength_ppg": r.strength_ppg, "strength_rank": r.strength_rank,
                "table_rank": r.table_rank, "rank_delta": r.rank_delta,
                "played": r.played, "points": r.points, "ppg": r.ppg,
                "form_points": r.form_points, "form_ppg": r.form_ppg,
                "form_gf": r.form_gf, "form_ga": r.form_ga, "form_results": r.form_results,
                "xg_for": r.xg_for, "xg_against": r.xg_against, "xg_diff": r.xg_diff,
                "expected_points": r.expected_points, "luck": r.luck,
                "sos_played": r.sos_played, "sos_remaining": r.sos_remaining, "sos_delta": r.sos_delta,
            }
            for r in rows
        ],
        "elo_history": elo_trajectories(_elo_factory, state, state.teams),
        "notes": {
            "strength_ppg": (
                "Expected points per game against an average opponent at a neutral venue. "
                "Averaging over every possible opponent removes the schedule, which real "
                "points per game cannot."
            ),
            "rank_delta": (
                "Table position minus the model's strength rank. Positive means the club "
                "is performing below where it sits."
            ),
            "luck": (
                "Actual points minus the points the xG deserved. Sustained over time it is "
                "usually finishing variance, not a skill."
            ),
            "sos_delta": (
                "Mean strength of opponents still to play minus those already played. "
                "Positive means the hard part is still to come."
            ),
        },
        "updated_at": _now(),
    }


def fit_international(stores: dict[str, dict]) -> tuple[EnsembleModel | None, dict]:
    """
    One Dixon-Coles fit over every national-team match the site follows —
    tournaments, qualifiers, the Nations Leagues, friendlies at half weight —
    wrapped like a league model so the same readers price fixtures and rank
    teams. One home-advantage term serves qualifiers and neutral finals alike,
    which is an approximation the methodology tab states.
    """
    import pandas as pd

    frames = []
    for slug, store in stores.items():
        cfg = CUPS[slug]
        df = cup_store.international_training_frame(store, neutral=cfg.neutral_venues, weight=0.5 if cfg.friendly else 1.0)
        if len(df):
            frames.append(df)
    if not frames:
        return None, {}
    df = pd.concat(frames, ignore_index=True).sort_values("match_date").reset_index(drop=True)
    cal = empirical_calibration(df)
    if len(df) < 30:
        return None, cal
    dc = DixonColesModel(xi=0.002, ridge=1.0, fixed_rho=rho_hold(df))
    try:
        dc.fit(df[[c for c in df.columns if c != "neutral"]])
    except Exception as exc:  # noqa: BLE001
        logger.warning("international fit failed: %s", exc)
        return None, cal
    elo = EloRatings(k_league=20, home_advantage=50.0)
    for row in df.itertuples():
        elo.update(row.home_team, row.away_team, int(row.home_goals), int(row.away_goals),
                   tournament_type="league", neutral=bool(getattr(row, "neutral", False)))
    logger.info("international fit: %d matches, %d teams", len(df), len(dc.teams_) if hasattr(dc, "teams_") else 0)
    return EnsembleModel(dc, elo, dc_weight=1.0, draw_rate=cal["draw_rate"], lam_scale=cal["lam_scale"], away_penalty=1.0), cal


def build_nations(data_dir: Path, model, cal: dict, stores: dict[str, dict]) -> None:
    """nations.json: every national team's attack, defence and strength from the international fit."""
    if model is None or not model.dc.is_fitted:
        _write(data_dir, "nations.json", {"teams": [], "model": None, "note": "No international fit this run.", "updated_at": _now()})
        return
    params = model.dc.params_
    rho, home_adv = float(params.get("rho", 0.0)), float(params.get("home_adv", 0.0))
    teams = {k[len("attack_"):]: {"attack": float(v)} for k, v in params.items() if k.startswith("attack_")}
    for k, v in params.items():
        if k.startswith("defense_") and k[len("defense_"):] in teams:
            teams[k[len("defense_"):]]["defence"] = float(v)
    att_bar = sum(t["attack"] for t in teams.values()) / len(teams)
    def_bar = sum(t.get("defence", 0.0) for t in teams.values()) / len(teams)
    # Confederation and match counts from the competitions each team appears in.
    conf_of: dict[str, str] = {}
    played: dict[str, int] = {}
    hints = {"Europe": "UEFA", "South America": "CONMEBOL", "North & Central America": "CONCACAF", "Africa": "CAF", "Asia": "AFC"}
    for slug, store in stores.items():
        cfg = CUPS[slug]
        conf = hints.get(cfg.country_hint or "")
        for m in (store.get("matches") or {}).values():
            for side in ("home", "away"):
                t = m.get(side)
                if not t:
                    continue
                if conf:
                    conf_of.setdefault(t, conf)
                if m.get("status") == "finished":
                    played[t] = played.get(t, 0) + 1
    rows = []
    for name, t in teams.items():
        m = dc_score_matrix(t["attack"], t.get("defence", 0.0), att_bar, def_bar, rho)
        h, d, a = outcome_probs(m)
        rows.append({
            "team": name, "confederation": conf_of.get(name) or confederation_of(name), "played": played.get(name, 0),
            "attack": round(t["attack"], 4), "defence": round(t.get("defence", 0.0), 4),
            "strength": round(3 * h + d, 4),
            "elo": round(float(model.elo.get_rating(name)), 0) if name in getattr(model.elo, "_ratings", {}) else None,
        })
    rows.sort(key=lambda r: -r["strength"])
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    _write(data_dir, "nations.json", {
        "teams": rows, "calibration": cal,
        "model": {"rho": round(rho, 5), "home_adv": round(home_adv, 5), "attack_mean": round(att_bar, 5), "defence_mean": round(def_bar, 5), "max_goals": 8},
        "note": ("One Dixon-Coles fit over every national-team match the site follows (tournaments, qualifiers, the "
                 "Nations Leagues; friendlies at half weight), time-decayed. Strength is expected points per game "
                 "against the average national team at a neutral venue. One home-advantage term serves qualifiers "
                 "and neutral finals alike."),
        "updated_at": _now(),
    })


def build_international(cfg: CupConfig, store: dict, out_dir: Path, base: dict, args, model) -> dict:
    """
    A national-team competition: fixtures and results with the international
    fit's line, group tables where there are groups, the knockout ladder as
    drawn, players, team statistics, match pages. Not simulated.
    """
    state = cup_store.cup_state_from_store(store, cfg)
    logger.info(state.summary())
    age = store_age_hours(store)
    store_fresh = age is not None and age < _stale_after(store)
    players = cup_store.aggregate_players(_season_view(store))
    floor = add_percentiles(players)
    teams_payload = {
        "teams": {t: {"slug": _slug(t), "conference": state.zone_of(t), "team_id": state.team_ids.get(t),
                      "crest": crest_path(cfg.slug, state.team_ids.get(t)), "league": None} for t in state.teams},
        "updated_at": _now(),
    }
    _write(out_dir, "teams.json", teams_payload)

    def _rows(zone):
        out = []
        for pos, (team, rec) in enumerate(state.standings(zone), start=1):
            out.append({"pos": pos, "team": team, "played": rec.played, "w": rec.won, "d": rec.drawn, "l": rec.lost,
                        "gf": rec.gf, "ga": rec.ga, "gd": rec.gd, "pts": rec.points, "exp_pts": None,
                        "p05": None, "p50": None, "p95": None, "p_title": None, "p_pos": [], "bands": {}})
        return out

    table = {
        "season": state.season_name, "bands": [], "tiebreak": list(cfg.tiebreak), "h2h_tiebreak": False,
        "fixtures": _fixture_rows(state.finished + state.remaining + state.playoff_matches),
        "games_played": state.games_played, "total_games": state.total_league_games,
        "matches_per_team": state.matches_per_team, "updated_at": _now(), "unsimulated": True,
    }
    if state.groups:
        table["conferences"] = {g: _rows(g) for g in sorted(state.groups)}
        table["overall"] = []
        table["group_label"] = "Group"
    else:
        derived = derived_groups(state.finished + state.remaining) if len(state.teams) > 40 else {}
        if derived:
            # A league phase the store gives no groups for (the Nations League's leagues A-D): the groups are the
            # sets of sides that play each other, and each one's table is computed from its results.
            table["conferences"] = derived
            table["overall"] = []
            table["group_label"] = "Group"
        else:
            table["standings"] = _rows(None) if state.games_played and len(state.teams) <= 40 else []
    _write(out_dir, "table.json", table)
    labels = {**CUP_ROUND_LABELS, "r32": "Round of 32", "r64": "Round of 64", "3rd": "Third place", "po": "Play-off"}
    _write(out_dir, "bracket.json", {
        "kind": cfg.kind, "rounds": list(cfg.round_keys), "round_labels": labels, "seeds": {}, "confirmed": False,
        "known": {r: [list(p) for p in pairs] for r, pairs in state.known_pairs.items()},
        "forced": {" v ".join(sorted(pair)): w for pair, w in state.playoff_results.items()},
        "reach": {}, "p_playoffs": {}, "p_cup": {},
        "note": "Knockout ties as drawn and decided; national-team competitions are not simulated.",
        "updated_at": _now(),
    })
    _write(out_dir, "probs.json", {"teams": [], "bands": [], "has_playoff": False, "updated_at": _now()})
    if model is not None and model.dc.is_fitted and state.teams:
        try:
            _write(out_dir, "strength.json", build_strength_json(model, state, store, cfg))
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: strength failed: %s", cfg.slug, exc)
            _write(out_dir, "strength.json", {"rows": [], "elo_history": {}, "notes": {}, "updated_at": _now()})
    else:
        _write(out_dir, "strength.json", {"rows": [], "elo_history": {}, "notes": {}, "updated_at": _now()})
    live_players, leaders = build_players_json(players, store, {}, [], floor)
    _write(out_dir, "players_live.json", live_players)
    _write(out_dir, "player_leaders.json", leaders)
    _write(out_dir, "shots.json", {"players": cup_store.shots_by_player(_season_view(store))})
    _write(out_dir, "history.json", {"snapshots": [], "updated_at": _now()})
    season_id = (store.get("meta") or {}).get("season_id")
    fixtures = write_analytics(
        out_dir, store, "international", model, _season_filter(season_id), players,
        cup_store.player_match_logs(_season_view(store)), cup_store.team_match_stats(_season_view(store)), cup_store.match_details(store),
        neutral_when=lambda raw: cfg.neutral_venues,
        floor=floor, season=state.season_name, round_labels=CUP_ROUND_LABELS,
    )
    write_market_odds(out_dir, None if (args.no_market or model is None) else fetch_markets_safe(cfg, fixtures["matches"]), model)
    last = max((m.date for m in state.finished + state.playoff_matches if m.date), default=None)
    meta = {
        "updated_at": _now(), "n_sims": 0, "runtime_s": 0.0, "season": state.season_name,
        "games_played": state.games_played, "games_total": state.total_league_games, "league_complete": state.league_complete,
        "store_fresh": store_fresh, "synthetic": bool((store.get("meta") or {}).get("synthetic")),
        "store_age_hours": round(age, 1) if age is not None else None,
        "season_stale": bool(last and (datetime.now(timezone.utc) - last).days > 120),
        "training_matches": 0, "calibration": {},
        "model": {"dc_fitted": bool(model is not None and model.dc.is_fitted), "params_method": "international fit"},
        "h2h_tiebreak": False, "source": "Sofascore", "cup_kind": cfg.kind, "phase": "live", "unsimulated": True,
        "detail_matches": len(store.get("lineups") or {}), "detail_season": len(_season_view(store).get("lineups") or {}), "sheet_matches": len(store.get("team_stats") or {}),
    }
    _write(out_dir, "meta.json", meta)
    tabs = [t for t in TABS_INTERNATIONAL if not (t == "table" and not (state.groups or table.get("standings") or table.get("conferences")))
            and not (t == "bracket" and not state.known_pairs)]
    standings = table.get("standings") or next(iter(table.get("conferences", {}).values()), None) or []
    return {
        **base, "tabs": tabs, "ok": True, "season": state.season_name, "updated_at": meta["updated_at"],
        "games_played": state.games_played, "games_total": state.total_league_games,
        "synthetic": meta["synthetic"], "store_fresh": store_fresh, "season_stale": meta["season_stale"],
        "favourite": None, "p_favourite": None, "favourite_label": "Winner", "unsimulated": True,
        **index_extras(fixtures["matches"], players, standings if table.get("standings") else None),
        "_fixtures": fixtures["matches"], "_players": players, "_teams": teams_payload["teams"],
        "_strength": (_read_json(out_dir / "strength.json", {}) or {}).get("rows") or [], "_probs": [], "_floor": floor,
    }


def build_season_index(data_dir: Path, entries: list[dict]) -> int:
    """season_index.json: every player's line in every competition this season, by player id."""
    players: dict[str, dict] = {}
    for c in entries:
        if not c.get("ok"):
            continue
        short = c.get("short_name") or c["name"]
        for p in c.get("_players") or []:
            if not p.get("minutes"):
                continue
            entry = players.setdefault(str(p["player_id"]), {"n": p.get("name"), "rows": []})
            entry["rows"].append({
                "comp": c["slug"], "cn": short, "kind": c.get("kind"), "fam": c.get("family") or ("league" if c.get("kind") != "cup" else "cup"),
                "t": p.get("team"), "pos": p.get("position"), "apps": p.get("matches"), "min": p.get("minutes"),
                "g": p.get("goals"), "a": p.get("assists"), "xg": p.get("xg"), "xa": p.get("xa"), "rt": p.get("rating"),
                "sh": p.get("shots"), "kp": p.get("key_passes"), "y": p.get("yellow"), "r": p.get("red"),
            })
    _write(data_dir, "season_index.json", {"players": players, "updated_at": _now()})
    return len(players)


def build_club_matches(data_dir: Path, entries: list[dict]) -> None:
    """Per league, every club's matches in every competition this season (cups and super cups included)."""
    by_league = {c["slug"]: c for c in entries if c.get("ok") and c.get("kind") in ("league", "conference", "playoff", "liga")}
    club_league: dict[str, str] = {}
    for slug, c in by_league.items():
        for t in (c.get("_teams") or {}):
            club_league.setdefault(t, slug)
    rows: dict[str, dict[str, list[dict]]] = {slug: {} for slug in by_league}
    for c in entries:
        if not c.get("ok") or c.get("family") == "international":
            continue
        for f in c.get("_fixtures") or []:
            for side in ("home", "away"):
                club = f.get(side)
                league = club_league.get(club)
                if not league:
                    continue
                item = {k: f.get(k) for k in ("id", "date", "round", "stage", "status", "home", "away", "hs", "as", "xg", "detail")}
                item["comp"] = c["slug"]
                item["cn"] = c.get("short_name") or c["name"]
                if f.get("model"):
                    item["model"] = {k: f["model"][k] for k in ("h", "d", "a")}
                rows[league].setdefault(club, []).append(item)
    for slug, clubs in rows.items():
        for lst in clubs.values():
            lst.sort(key=lambda r: (r.get("date") or "9999", r["id"]))
        _write(data_dir / slug, "club_matches.json", {"clubs": clubs, "updated_at": _now()})


def build_boot_candidates_from(players: list[dict], cap_per_team: int = 12) -> list[dict]:
    by_team: dict[str, list[dict]] = {}
    for p in players:
        if not p["team"] or p["is_gk"]:
            continue
        by_team.setdefault(p["team"], []).append(p)
    candidates = []
    for team, squad in by_team.items():
        squad.sort(key=lambda r: (-r["goals"], -r["xg"], -r["minutes"]))
        for p in squad[:cap_per_team]:
            per90 = float(p.get("goals_90") or 0.0)
            candidates.append({
                "name": p["name"], "team": team,
                "cur_goals": p["goals"], "cur_assists": p["assists"],
                "hist_goals_90": per90,
                "role": "FWD" if per90 >= 0.25 else "MID",
            })
    merged: dict[str, dict] = {}
    for c in candidates:
        prev = merged.get(c["name"])
        if prev is None or c["cur_goals"] > prev["cur_goals"]:
            merged[c["name"]] = c
    return list(merged.values())


def player_team_ids(store: dict) -> dict[str, list[tuple[str, str, int]]]:
    """{player id: [(date, the club's name as the line-up gives it, its Sofascore team id), ...]}, latest first, from
    the store's line-ups and the matches' home_id / away_id (no new data: both are in the store already)."""
    matches = store.get("matches") or {}
    out: dict[str, list[tuple[str, str, int]]] = {}
    for gid, lu in (store.get("lineups") or {}).items():
        m = matches.get(str(gid)) or {}
        if not isinstance(lu, dict) or not isinstance(m, dict):
            continue
        ids = {}
        for side in ("home", "away"):
            tid = m.get(f"{side}_id")
            if m.get(side) and str(tid or "").isdigit():
                ids[str(m[side])] = int(tid)
        for pid, p in lu.items():
            t = str((p or {}).get("t") or "") if isinstance(p, dict) else ""
            if t in ids:
                out.setdefault(str(pid), []).append((str(m.get("date") or ""), t, ids[t]))
    for v in out.values():
        v.sort(reverse=True)
    return out


def _tid_for(row: dict, seen: list[tuple[str, str, int]] | None) -> int | None:
    """The team id of a players_live row's club: the latest appearance under that club's name, else the latest one
    (the row's club is the player's latest club, and the build may have normalised its name)."""
    if not seen:
        return None
    for _d, name, tid in seen:
        if name == row.get("team"):
            return tid
    return seen[0][2]


def build_players_json(players: list[dict], store, boot_probs: dict, candidates: list[dict], floor: int) -> tuple[dict, dict]:
    """players_live.json (every player's line, the catalogue, percentiles) and player_leaders.json. Each row carries
    `tid`, its club's team id (the front end's tale of the tape finds the club by id, not by name)."""
    tids = player_team_ids(store)
    age = store_age_hours(store)
    fresh = age is not None and age < _stale_after(store)
    prob_team = {c["name"]: c["team"] for c in candidates}
    leaders = []
    for p in players:
        prob = boot_probs.get(p["name"])
        if prob is not None and prob_team.get(p["name"]) not in (None, p["team"]):
            prob = None
        leaders.append({
            "id": p["player_id"], "name": p["name"], "team": p["team"], "goals": p["goals"], "assists": p["assists"],
            "xg": p["xg"], "minutes": p["minutes"],
            "model": round(prob, 4) if prob is not None else None,
        })
    leaders.sort(key=lambda r: (-(r["model"] or 0), -r["goals"], -r["xg"]))
    # Nulls are dropped from every row (a goalkeeper has no shooting rates, an
    # outfielder no save percentage): the payload is a third smaller for it and
    # the front-end reads absent keys as unknown anyway.
    live = {
        "ok": bool(players) or fresh, "updated_at": _now(), "checked_at": _now(),
        "matches_covered": len(store.get("lineups", {})), "minutes_floor": floor,
        "metrics": METRICS, "positions": POSITION_LABELS,
        # the row's club id rides on the payload row only (the player lines elsewhere stay as they are)
        "players": [{**{k: v for k, v in p.items() if v is not None},
                     **({"tid": t} if (t := _tid_for(p, tids.get(str(p.get("player_id"))))) is not None else {})} for p in players],
    }
    return live, {"top_scorer": leaders[:40], "live": leaders}


def build_history_json(out_dir: Path, results, cfg, keep_store: int = 400, keep_out: int = 60,
                       season: str | None = None) -> dict:
    """Append this run's headline probabilities to the competition's history store. The store also keeps the
    daily race history (one snapshot per UTC day for the whole season: the Race tab's lines), which history.json
    carries as "daily"."""
    path = out_dir / "history_store.json"
    store = _read_json(path, {"snapshots": []})
    snapshots = store.get("snapshots", [])
    stamp = _now()

    def top(d: dict, n: int = 16) -> dict:
        return {t: round(p, 5) for t, p in sorted(d.items(), key=lambda kv: -kv[1])[:n]}

    snapshot = {"ts": stamp, "title": top(results.p_cup if cfg.playoff else results.p_title)}
    down = [b for b in cfg.bands if b.kind == "down"]
    if down:
        snapshot["relegation"] = top({
            t: sum(results.p_in_band(b.key, t) for b in down) for t in results.teams
        })
    first_up = next((b for b in cfg.bands if b.kind == "up"), None)
    if first_up:
        snapshot["band"] = top(results.p_band.get(first_up.key, {}))
        snapshot["band_key"] = first_up.key
    if cfg.playoff:
        snapshot["shield"] = top(results.p_title)

    if not any(s.get("ts") == stamp for s in snapshots):
        snapshots.append(snapshot)
    snapshots = snapshots[-keep_store:]
    daily = _race.roll_daily(store.get("daily"), snapshots, season, results.teams)
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"snapshots": snapshots, "daily": daily}, ensure_ascii=False), encoding="utf-8")
    return {"snapshots": snapshots[-keep_out:], "daily": daily["days"], "updated_at": stamp}


def fetch_markets_safe(cfg, fixtures: list[dict] | None = None, teams: Iterable[str] | None = None,
                       season_hint: str | None = None) -> dict | None:
    """
    Market prices for a competition. Polymarket and Kalshi need no key and are
    always tried (the World Cup site priced its markets the same way); The Odds
    API's bookmakers are added when ODDS_API_KEY is set. Returns
    {"h2h": [fixture rows with books], "outright": {club: decimal odds}} or None.
    """
    from oddsmarkets.football.sources import prediction_markets as pm

    rows: list[dict] = []
    outright: dict[str, float] = {}
    try:
        rows = pm.match_rows(cfg.slug, fixtures or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: prediction-market match prices failed: %s", cfg.slug, exc)
    try:
        if teams:
            outright = pm.title_prices(cfg.slug, cfg.name, teams, season_hint)
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: prediction-market title prices failed: %s", cfg.slug, exc)
    api_key = os.getenv("ODDS_API_KEY", "")
    if api_key and getattr(cfg, "odds_api_sport", None):
        try:
            import asyncio
            from oddsmarkets.sports.world_cup.trading.the_odds_api import TheOddsAPIFetcher

            async def _go():
                async with TheOddsAPIFetcher(api_key) as fetcher:
                    return await fetcher.fetch_match_odds(sport=cfg.odds_api_sport)

            books = asyncio.run(_go()) or []
            have = {(pm.fold(r["home"]), pm.fold(r["away"])) for r in rows}
            rows += [r for r in books if isinstance(r, dict) and r.get("books") and (pm.fold(r.get("home", "")), pm.fold(r.get("away", ""))) not in have]
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: The Odds API fetch failed: %s", cfg.slug, exc)
    if not rows and not outright:
        return None
    logger.info("%s: market prices for %d fixtures, %d clubs in the title market", cfg.slug, len(rows), len(outright))
    return {"h2h": rows, "outright": outright}


# A title market kept from an earlier build when the markets return nothing (a transient failure) is dropped after
# this many hours; match lines are kept only until kick-off.
MARKET_KEEP_HOURS = 48


def _parse_utc(s: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def prune_stale_markets(prev: dict, now: datetime | None = None) -> dict:
    """The previous market_odds.json reduced to what is still current: fixtures that have not kicked off, and the
    title market while it is under MARKET_KEEP_HOURS old. Before 18 Oct 2026 the whole previous file was kept with
    ok:false, so a competition between matchdays (AFC Champions League, the Nations Leagues, friendlies, Copa
    Argentina) went on showing last matchday's lines, played fixtures included, with updated_at frozen at the last
    fetch that found any."""
    now = now or datetime.now(timezone.utc)
    m = dict(prev.get("matches") or {})
    keep = [f for f in m.get("fixtures") or [] if (_parse_utc(f.get("commence")) or now) > now]
    m["fixtures"] = keep
    m["actionable"] = sum(1 for f in keep if f.get("actionable"))
    upd = _parse_utc(prev.get("updated_at"))
    out = prev.get("outrights") or {}
    if not (out.get("available") and upd is not None and now - upd <= timedelta(hours=MARKET_KEEP_HOURS)):
        out = {"available": False, "teams": []}
    return {**prev, "ok": False, "checked_at": _now(), "matches": m, "outrights": out}


def write_market_odds(out_dir: Path, raw: dict | None, model, title_model: dict[str, float] | None = None,
                      adjust: dict[str, dict[str, float]] | None = None) -> None:
    """market_odds.json: match lines and the title market against the model. When nothing came back, the previous file
    is kept with ok:false but only for what is still current (prune_stale_markets): lines of fixtures not yet kicked
    off and a title market from the last MARKET_KEEP_HOURS."""
    path = out_dir / "market_odds.json"
    matches = build_match_markets(raw["h2h"], model, adjust=adjust) if raw and raw.get("h2h") and model is not None else {"fixtures": []}
    outrights = build_outright_markets(raw["outright"], title_model or {}) if raw and raw.get("outright") and title_model else {"available": False, "teams": []}
    if matches.get("fixtures") or outrights.get("available"):
        _write(out_dir, "market_odds.json", {
            "ok": True, "updated_at": _now(), "checked_at": _now(),
            "sources": sorted({src for r in (raw or {}).get("h2h") or [] for src in (r.get("books") or {})}),
            "matches": matches, "outrights": outrights,
        })
        return
    prev = _read_json(path, None)
    if prev:
        path.write_text(json.dumps(prune_stale_markets(prev), ensure_ascii=False), encoding="utf-8")
    else:
        _write(out_dir, "market_odds.json", {
            "ok": False, "updated_at": None, "checked_at": _now(),
            "matches": {"fixtures": []}, "outrights": {"available": False, "teams": []},
        })


# The cards and the match page hide a market snapshot older than this (docs/site/assets/app/core.js MKT_MAX_AGE).
MARKET_FRESH_HOURS = 72
# A watched competition with a fixture this close to kick-off is expected to carry a market (Kalshi and Polymarket
# list the big leagues' and the UEFA cups' matches several days ahead).
MARKET_EXPECT_HOURS = 48
MARKET_WATCH_CUPS = ("champions-league", "europa-league", "conference-league")


def market_freshness(data_dir: Path, slugs: Iterable[str], now: datetime | None = None) -> dict:
    """How fresh the competitions' market files are after a build. Returns {"fresh": [slugs priced within
    MARKET_FRESH_HOURS], "stale": [(slug, hours since the last priced snapshot or None, fixtures due)]}: a competition
    is stale when it has a not-started fixture kicking off within MARKET_EXPECT_HOURS and no market snapshot under
    MARKET_FRESH_HOURS old, so its cards show no market. (Before 28 Oct 2026 nothing reported this: a fetch that kept
    returning nothing only showed as missing markets on the site.)"""
    now = now or datetime.now(timezone.utc)
    fresh: list[str] = []
    stale: list[tuple[str, float | None, int]] = []
    for slug in slugs:
        mk = _read_json(data_dir / slug / "market_odds.json", None)
        if mk is None:
            continue
        upd = _parse_utc(mk.get("updated_at")) if mk.get("updated_at") else None
        age = (now - upd).total_seconds() / 3600 if upd else None
        if age is not None and age <= MARKET_FRESH_HOURS:
            fresh.append(slug)
            continue
        due = 0
        for f in _read_json(data_dir / slug / "fixtures.json", {}).get("matches") or []:
            k = _parse_utc(f.get("date")) if f.get("status") == "scheduled" and f.get("date") else None
            if k is not None and now < k <= now + timedelta(hours=MARKET_EXPECT_HOURS):
                due += 1
        if due:
            stale.append((slug, age, due))
    return {"fresh": fresh, "stale": stale}


def report_market_freshness(fr: dict) -> None:
    """One log line on the markets' freshness, and a GitHub Actions warning (an annotation on the run's summary page)
    when a watched competition with fixtures due has no fresh market."""
    stale = fr["stale"]
    logger.info("market freshness: %d competitions priced within %d h; stale with fixtures due in %d h: %s",
                len(fr["fresh"]), MARKET_FRESH_HOURS, MARKET_EXPECT_HOURS,
                ", ".join(f"{s} ({'never' if a is None else f'{a:.0f} h'}, {n} due)" for s, a, n in stale) or "none")
    if stale and os.getenv("GITHUB_ACTIONS") == "true":
        head = "no football market priced in this build" if not fr["fresh"] else "football markets stale"
        print(f"::warning title=Stale football markets::{head}: "
              + ", ".join(f"{s} last priced {'never' if a is None else f'{a:.0f} h ago'}" for s, a, _n in stale)
              + " (cards hide a market older than 3 days; check the Kalshi / Polymarket fetch in this log)", flush=True)


# ── analytics payloads (shared by leagues, cups and Argentina) ───────────────

def build_fixtures_json(store: dict, norm, model, season_filter, xg_map: dict, neutral_when=None,
                        lineup_terms: dict[str, dict] | None = None) -> dict:
    """
    Every match the season filter admits, in kickoff order, with its status,
    score, xG where the detail exists, and the model's line where it is still
    to be played. Matches of every stage are listed (a cup's qualifying rounds
    included) so the scoreboard is complete. A fixture in `lineup_terms` (its
    confirmed XIs are posted) carries them as `xi`, its line before them as
    `model_pre`, and `model` after the line-up term where it applies.
    """
    lineups = store.get("lineups") or {}
    rows = []
    now = datetime.now(timezone.utc)
    for gid, raw in (store.get("matches") or {}).items():
        if not isinstance(raw, dict) or not season_filter(raw) or raw.get("superseded_by"):
            continue                                  # superseded: the old copy of a re-listed fixture
        home, away = norm(str(raw.get("home") or "")), norm(str(raw.get("away") or ""))
        if not home or not away:
            continue
        raw_status = str(raw.get("status") or "").strip().lower()
        status = _status_of(raw.get("status"))
        # Cancelled before postponed: _POSTPONED holds "canceled" too (for the simulator, which treats both as
        # still to be played), so the cancelled branch never ran and a cancelled match showed as postponed.
        if raw_status in ("cancelled", "canceled"):
            status = "cancelled"
        elif raw_status in _POSTPONED:
            status = "postponed"
        # Still "not started" hours after kick-off and held nowhere else: the source never closed it. It is not
        # shown as to come (pages treat postponed as void); the model keeps pricing it as still to be played.
        missing = status == "scheduled" and _liga_overdue(raw, now)
        if missing:
            status = "postponed"
        void = status in ("postponed", "cancelled")
        row: dict = {
            "id": str(gid), "date": raw.get("date"), "round": raw.get("round"),
            "stage": raw.get("stage") or "league", "status": status,
            # A void match has no result: the source's 0-0 on a cancelled event is a placeholder, not a score.
            "home": home, "away": away, "hs": None if void else raw.get("hs"), "as": None if void else raw.get("as"),
            "detail": str(gid) in lineups,
        }
        if missing:
            row["result_missing"] = True
        for key in ("group", "split_group", "torneo", "zone"):
            if raw.get(key):
                row[key] = raw[key]
        if raw.get("winner"):
            row["winner"] = norm(str(raw["winner"]))
        if raw.get("agg_winner"):
            row["agg_winner"] = norm(str(raw["agg_winner"]))
        if str(gid) in xg_map:
            row["xg"] = [round(float(xg_map[str(gid)][0]), 2), round(float(xg_map[str(gid)][1]), 2)]
        if status not in ("finished", "cancelled") and model is not None:
            neutral = bool(raw.get("neutral")) or bool(neutral_when and neutral_when(raw))
            pred = predict_fixture(model, home, away, neutral=neutral)
            term = (lineup_terms or {}).get(str(gid))
            if pred and term:
                row["xi"] = term
                if term.get("applied"):
                    after = predict_fixture(model, home, away, neutral=neutral, lineup=term)
                    if after:
                        row["model_pre"] = {k: pred[k] for k in ("h", "d", "a", "lh", "la")}
                        pred = {**after, "lineups": True}
            if pred:
                row["model"] = pred
        rows.append(row)
    rows.sort(key=lambda r: (r["date"] or "9999", r["id"]))
    return {"matches": rows, "updated_at": _now()}


def _prune(dir_path: Path, keep: set[str]) -> None:
    """Remove shard files a rebuild no longer writes (a season rollover, a renamed club)."""
    if not dir_path.exists():
        return
    for f in dir_path.glob("*.json"):
        if f.stem not in keep:
            try:
                f.unlink()
            except OSError:
                pass


def has_match_page(gid, date, current_ids: set[str] | None = None, now: datetime | None = None) -> bool:
    """
    Whether a match with detail gets its own page (matches/<id>.json): every match of
    the current edition, and earlier ones from the last MATCH_PAGE_DAYS. Older detail
    (the previous season backfilled in full for the season totals) feeds the people,
    clubs and season payloads but no page, so the site does not grow by a page a match.
    """
    if current_ids is not None and str(gid) in current_ids:
        return True
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=MATCH_PAGE_DAYS)).strftime("%Y-%m-%d")
    return str(date or "")[:10] >= since


def write_match_pages(out_dir: Path, details: dict[str, dict], fixtures: list[dict]) -> dict:
    """matches.json (the season's played matches) and one shard per match with detail (has_match_page)."""
    current_ids = {str(r.get("id")) for r in fixtures}
    details = {g: m for g, m in details.items() if has_match_page(g, (m or {}).get("date"), current_ids)}
    index = []
    for r in fixtures:
        if r["status"] != "finished":
            continue
        index.append({k: r.get(k) for k in ("id", "date", "round", "stage", "group", "home", "away", "hs", "as", "xg", "detail")
                      if r.get(k) is not None})
    index.sort(key=lambda r: (r.get("date") or "", r["id"]), reverse=True)
    shard_dir = out_dir / "matches"
    shard_dir.mkdir(parents=True, exist_ok=True)
    legacy = out_dir / "match_detail.json"      # the pre-shard payload
    if legacy.exists():
        legacy.unlink()
    for gid, m in details.items():
        _write(shard_dir, f"{gid}.json", m)
    _prune(shard_dir, set(details))
    payload = {"matches": index, "with_detail": len(details), "updated_at": _now()}
    _write(out_dir, "matches.json", payload)
    return payload


def write_player_shards(out_dir: Path, logs: dict[str, dict], players: list[dict]) -> None:
    """players/<club-slug>.json: the match logs of every player whose current club that is."""
    team_of = {p["player_id"]: p["team"] for p in players}
    by_team: dict[str, dict] = {}
    for pid, entry in logs.items():
        team = team_of.get(pid) or entry.get("team") or ""
        if not team:
            continue
        by_team.setdefault(team, {})[pid] = entry
    shard_dir = out_dir / "players"
    shard_dir.mkdir(parents=True, exist_ok=True)
    keep = set()
    for team, members in by_team.items():
        slug = _slug(team)
        keep.add(slug)
        _write(shard_dir, f"{slug}.json", {"team": team, "players": members})
    _prune(shard_dir, keep)


def build_team_stats_json(by_team: dict[str, list[dict]]) -> dict:
    season = season_team_stats(by_team)
    return {
        "teams": {t: {"season": season.get(t, {}), "matches": rows} for t, rows in by_team.items()},
        "metrics": TEAM_METRICS,
        "updated_at": _now(),
    }


def write_analytics(out_dir: Path, store: dict, registry, model, season_filter, players: list[dict],
                    logs: dict, by_team: dict, details: dict, neutral_when=None,
                    floor: int | None = None, season: str | None = None, round_labels: dict | None = None,
                    lineup_terms: dict[str, dict] | None = None, extra: dict | None = None) -> dict:
    """
    The analytics payloads every competition gets; returns the fixtures payload
    for the hub. `floor` is the competition's minutes floor (the one its
    percentiles used), `season` its season name and `round_labels` the labels
    of its knockout rounds; the analytics.json insights read all three.
    """
    xg_map = _liga.team_xg_map(store, registry=registry)
    norm = lambda name: normalize_team_name(name, registry)  # noqa: E731
    fixtures = build_fixtures_json(store, norm, model, season_filter, xg_map, neutral_when, lineup_terms=lineup_terms)
    _write(out_dir, "fixtures.json", fixtures)
    write_match_pages(out_dir, details, fixtures["matches"])
    write_player_shards(out_dir, logs, players)
    _write(out_dir, "team_stats.json", build_team_stats_json(by_team))
    analytics = build_analytics(players, logs, by_team, fixtures["matches"], floor=floor,
                                season=season, round_labels=round_labels, updated_at=_now())
    for k, v in (extra or {}).items():
        if v:
            analytics[k] = v
    _write(out_dir, "analytics.json", analytics)
    return fixtures


SEASON_KEYS = ("lineups", "shots", "incidents", "team_stats", "momentum", "lineup_extras")


def _season_view(store: dict) -> dict:
    """
    The store restricted to the current season's matches, for everything that
    aggregates a season: player lines, match logs, shot lists, team sheets. The
    fetcher also backfills last season's detail for the calendar views, and a
    season page must not count it. Match pages keep reading the whole store.
    """
    season_id = (store.get("meta") or {}).get("season_id")
    if season_id is None:
        return store
    matches = store.get("matches") or {}
    keep = {g for g, m in matches.items() if m.get("season_id") == season_id}
    if all(g in keep for g in (store.get("lineups") or {})):
        return store
    view = dict(store)
    for key in SEASON_KEYS:
        if isinstance(store.get(key), dict):
            view[key] = {g: v for g, v in store[key].items() if g in keep}
    return view


def _torneo_view(store: dict, keep_match) -> dict:
    """The store restricted to the matches `keep_match` admits (Argentina: one torneo of one year)."""
    matches = store.get("matches") or {}
    keep = {g for g, m in matches.items() if isinstance(m, dict) and keep_match(m)}
    view = dict(store)
    view["matches"] = {g: m for g, m in matches.items() if g in keep}
    for key in SEASON_KEYS:
        if isinstance(store.get(key), dict):
            view[key] = {g: v for g, v in store[key].items() if g in keep}
    return view


def _season_filter(season_id) -> callable:
    return lambda raw: raw.get("season_id") == season_id


def index_extras(fixtures: list[dict], players: list[dict], standings: list[dict] | None) -> dict:
    """The bits of a competition the hub cards show: leader, top scorer, next fixture, last result."""
    out: dict = {}
    if standings:
        top = standings[0]
        out["leader"] = {"team": top["team"], "pts": top.get("pts"), "played": top.get("played")}
    scorers = sorted((p for p in players if p.get("goals")), key=lambda p: (-p["goals"], -p["xg"]))
    if scorers:
        s = scorers[0]
        out["top_scorer"] = {"id": s["player_id"], "name": s["name"], "team": s["team"], "goals": s["goals"]}
    upcoming = [f for f in fixtures if f["status"] in ("scheduled", "live")]
    if upcoming:
        f = upcoming[0]
        out["next"] = {k: f.get(k) for k in ("id", "date", "home", "away", "status")}
        if f.get("model"):
            out["next"]["model"] = {k: f["model"][k] for k in ("h", "d", "a")}
    played = [f for f in fixtures if f["status"] == "finished"]
    if played:
        f = played[-1]
        out["last"] = {k: f.get(k) for k in ("id", "date", "home", "away", "hs", "as")}
    return out


# ── one league ───────────────────────────────────────────────────────────────

def write_sensitivity(out_dir: Path, slug: str, compute) -> None:
    """sensitivity.json for the transfer simulator; never fails the competition's build."""
    if not USE_SENSITIVITY:
        return
    try:
        payload = compute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s: sensitivity curves failed: %s", slug, exc)
        return
    if payload is None:
        payload = {"teams": {}, "note": "The season is complete: nothing left to simulate."}
    _write(out_dir, "sensitivity.json", {**payload, "updated_at": _now()})
    logger.info("%s: sensitivity curves for %d clubs in %.1fs", slug, len(payload.get("teams") or {}), payload.get("runtime_s") or 0.0)


def build_league(cfg: LeagueConfig, entry: dict, args, sims: int | None,
                 pooled: DixonColesModel | None = None) -> dict:
    out_dir = DATA_DIR / cfg.slug
    if sims:
        cfg = with_sims(cfg, sims)
    kind = "conference" if cfg.conferences else ("playoff" if cfg.playoff else "league")
    base = {
        "slug": cfg.slug, "name": cfg.name, "short_name": cfg.short_name,
        "country": cfg.country, "kind": kind,
        "tabs": TABS_CONFERENCE if cfg.conferences else (TABS_PLAYOFF if cfg.playoff else TABS_LEAGUE),
    }

    store = load_store(out_dir / "store.json")
    if not store.get("matches"):
        logger.warning("%s: no store — skipped", cfg.slug)
        return {**base, "ok": False, "reason": "no store yet"}

    age = store_age_hours(store)
    store_fresh = age is not None and age < _stale_after(store)
    synthetic = bool((store.get("meta") or {}).get("synthetic"))

    state = league_state_from_store(
        store, cfg,
        previous_rank=entry.get("previous_rank") or {},
        conferences=entry.get("conferences") or {},
        teams=entry.get("teams") or [],
    )
    logger.info(state.summary())
    if not state.teams:
        return {**base, "ok": False, "reason": "no teams"}

    train_df = training_frame(store, cfg)
    params, method = model_params_for(cfg.slug)
    use_pooled = pooled if method == "pooled" else None
    if method == "pooled" and pooled is None:
        method = "pooled (fit unavailable; own fit)"
    logger.info("%s model params (%s): %s", cfg.slug, method, params)
    model, cal = build_model(train_df, state.teams, state.previous_rank, cfg, params, pooled=use_pooled)

    players = aggregate_players(_season_view(store), cfg)
    floor = add_percentiles(players)
    candidates = build_boot_candidates_from(players)
    boot = GoldenBootModel(candidates, seed=cfg.random_seed) if candidates else None

    if state.league_complete and not cfg.playoff:
        logger.warning("%s: season complete — probabilities are the final table", cfg.slug)
    results = LeagueSimulator(model, state, cfg=cfg, seed=args.seed, boot_model=boot).run()
    boot_probs = boot.probabilities(results.n_sims) if boot else {}
    write_sensitivity(out_dir, cfg.slug, lambda: None if state.league_complete and not cfg.playoff else
                      league_sensitivity(model, state, cfg, budget_s=SENS_BUDGET_S))

    teams_payload = {
        "teams": {
            t: {"slug": _slug(t), "conference": state.zone_of(t), "team_id": state.team_ids.get(t),
                "crest": crest_path(cfg.slug, state.team_ids.get(t))}
            for t in state.teams
        },
        "updated_at": _now(),
    }
    _write(out_dir, "teams.json", teams_payload)
    table = build_table_json(state, results, cfg)
    _write(out_dir, "table.json", table)
    probs_payload = build_probs_json(state, results, cfg)
    _write(out_dir, "probs.json", probs_payload)
    if cfg.playoff:
        _write(out_dir, "bracket.json", build_bracket_json(state, results, cfg))
    strength_payload = build_strength_json(model, state, store, cfg)
    _write(out_dir, "strength.json", strength_payload)
    live_players, leaders = build_players_json(players, store, boot_probs, candidates, floor)
    _write(out_dir, "players_live.json", live_players)
    _write(out_dir, "player_leaders.json", leaders)
    _write(out_dir, "shots.json", {"players": shots_by_player(_season_view(store), cfg)})
    _write(out_dir, "history.json", build_history_json(out_dir, results, cfg, season=state.season_name))
    season_id = (store.get("meta") or {}).get("season_id")
    sp = {}
    try:
        sp = _race.set_pieces(_season_view(store), lambda name: normalize_team_name(name, cfg.registry))
    except Exception as exc:  # noqa: BLE001 - a Race-tab extra never fails the competition's build
        logger.warning("%s: set-piece profile failed: %s", cfg.slug, exc)
    fixtures = write_analytics(
        out_dir, store, cfg.registry, model, _season_filter(season_id), players,
        player_match_logs(_season_view(store), cfg), team_match_stats(_season_view(store), cfg), match_details(store, cfg),
        floor=floor, season=state.season_name, lineup_terms=LINEUP_TERMS.get(cfg.slug), extra={"set_pieces": sp},
    )
    title_model = dict(results.p_cup if cfg.playoff else results.p_title)
    write_market_odds(out_dir, None if args.no_market else fetch_markets_safe(cfg, fixtures["matches"], title_model.keys(), state.season_name),
                      model, title_model, adjust=lineup_lines(fixtures["matches"]))

    last = last_finished_date(state)
    season_stale = bool(last and (datetime.now(timezone.utc) - last).days > SEASON_STALE_DAYS)
    dist = results.p_cup if cfg.playoff else results.p_title
    favourite = max(dist, key=lambda t: dist[t])
    fav_p = dist[favourite]
    meta = {
        "updated_at": _now(), "n_sims": results.n_sims, "runtime_s": round(results.runtime_s, 2),
        "season": state.season_name, "games_played": state.games_played,
        "games_total": state.total_league_games, "league_complete": state.league_complete,
        "store_fresh": store_fresh, "synthetic": synthetic,
        "store_age_hours": round(age, 1) if age is not None else None,
        "season_stale": season_stale, "training_matches": int(len(train_df)),
        "calibration": cal,
        "model": {
            "elo_home_advantage": params["elo_home_advantage"], "elo_k_league": params["k_league"],
            "dc_weight": params["dc_weight"] if model.dc.is_fitted else 0.0, "dc_xi": params["xi"],
            "dc_ridge": params["ridge"], "dc_fitted": model.dc.is_fitted,
            "params_method": method,
        },
        "h2h_tiebreak": cfg.h2h_tiebreak,
        "source": "Sofascore",
        "detail_matches": len(store.get("lineups") or {}), "detail_season": len(_season_view(store).get("lineups") or {}),
        "sheet_matches": len(store.get("team_stats") or {}),
    }
    _write(out_dir, "meta.json", meta)
    standings = table.get("standings") or table.get("overall") or []
    return {
        **base, "ok": True, "season": state.season_name, "updated_at": meta["updated_at"],
        "games_played": state.games_played, "games_total": state.total_league_games,
        "synthetic": synthetic, "store_fresh": store_fresh, "season_stale": season_stale,
        "favourite": favourite, "p_favourite": round(fav_p, 4),
        "favourite_label": "MLS Cup" if cfg.conferences else ("Liguilla" if cfg.playoff else "Title"),
        **index_extras(fixtures["matches"], players, standings),
        "_fixtures": fixtures["matches"], "_players": players, "_teams": teams_payload["teams"],
        "_strength": strength_payload["rows"], "_probs": probs_payload["teams"], "_floor": floor,
    }


# ── cups ─────────────────────────────────────────────────────────────────────

def knockout_note(cfg) -> str:
    """The bracket note of a straight knockout, from its own rounds: which are single matches, which two-legged,
    and where they are played (it once said "two-legged ties until a single-match final" for every national cup,
    the single-match Copa Argentina, FA Cup and DFB-Pokal included)."""
    labels = {**CUP_ROUND_LABELS, **{t.key: t.label for t in getattr(cfg, "ties", ()) or ()}}
    rounds = list(getattr(cfg, "rounds", ()) or ())
    two = [labels.get(k, k) for k, legs in rounds if legs == 2]
    neutral = set(getattr(cfg, "neutral_rounds", ()) or ()) | ({"final"} if getattr(cfg, "final_at_neutral_venue", False) else set())
    if not two:
        legs = "Every tie is a single match"
    elif len(two) == len(rounds):
        legs = "Every tie is two-legged"
    else:
        legs = "Single matches, except the " + ", ".join(two) + " (two legs)"
    if rounds and all(k in neutral for k, _ in rounds):
        venue = ", all at neutral grounds"
    elif "final" in neutral:
        venue = "; the final is at a neutral ground"
    else:
        venue = ""
    return ("A straight knockout whose bracket is read from the draw as it is made. " + legs + venue + ". Rounds "
            "not yet drawn pair the survivors at random; ties already decided are taken as played.")


def build_cup_pre(cfg: CupConfig, store: dict, out_dir: Path, base: dict, args) -> tuple[dict, None]:
    """A cup before its main phase: fixtures, results and match pages only."""
    note = PRE_PHASE_NOTES.get(cfg.slug, "The main phase has not started; the fixtures played so far are listed.")
    season_id = (store.get("meta") or {}).get("season_id")
    ids: dict[str, int] = {}
    for raw in (store.get("matches") or {}).values():
        for side in ("home", "away"):
            if raw.get(f"{side}_id") and raw.get(side):
                ids.setdefault(str(raw[side]), int(raw[f"{side}_id"]))
    players = cup_store.aggregate_players(_season_view(store))
    floor = add_percentiles(players)
    fixtures = write_analytics(
        out_dir, store, cup_store.NO_REGISTRY, None, _season_filter(season_id), players,
        cup_store.player_match_logs(_season_view(store)), cup_store.team_match_stats(_season_view(store)), cup_store.match_details(store),
        floor=floor, season=(store.get("meta") or {}).get("season_name"), round_labels=CUP_ROUND_LABELS,
    )
    teams = sorted({t for r in fixtures["matches"] for t in (r["home"], r["away"])})
    teams_payload = {"teams": {t: {"slug": _slug(t), "conference": None, "team_id": ids.get(t), "crest": crest_path(cfg.slug, ids.get(t))}
                               for t in teams}, "updated_at": _now()}
    _write(out_dir, "teams.json", teams_payload)
    _write(out_dir, "table.json", {"season": (store.get("meta") or {}).get("season_name"), "bands": [], "tiebreak": [],
                                   "h2h_tiebreak": False, "fixtures": [], "standings": [], "games_played": 0,
                                   "total_games": 0, "matches_per_team": 0, "updated_at": _now()})
    _write(out_dir, "probs.json", {"teams": [], "bands": [], "has_playoff": True, "updated_at": _now()})
    _write(out_dir, "bracket.json", {"kind": cfg.kind, "rounds": [], "round_labels": {}, "seeds": {}, "known": {},
                                     "forced": {}, "reach": {}, "p_playoffs": {}, "p_cup": {}, "note": note, "updated_at": _now()})
    _write(out_dir, "strength.json", {"rows": [], "elo_history": {}, "notes": {}, "updated_at": _now()})
    live, leaders = build_players_json(players, store, {}, [], floor)
    _write(out_dir, "players_live.json", live)
    _write(out_dir, "player_leaders.json", leaders)
    _write(out_dir, "shots.json", {"players": cup_store.shots_by_player(_season_view(store))})
    _write(out_dir, "history.json", {"snapshots": _read_json(out_dir / "history_store.json", {"snapshots": []}).get("snapshots", [])[-60:], "updated_at": _now()})
    write_market_odds(out_dir, None, None)
    played = sum(1 for r in fixtures["matches"] if r["status"] == "finished")
    age = store_age_hours(store)
    meta = {
        "updated_at": _now(), "n_sims": 0, "runtime_s": 0.0, "season": (store.get("meta") or {}).get("season_name"),
        "games_played": played, "games_total": len(fixtures["matches"]), "league_complete": False,
        "store_fresh": age is not None and age < _stale_after(store), "synthetic": bool((store.get("meta") or {}).get("synthetic")),
        "store_age_hours": round(age, 1) if age is not None else None, "season_stale": False,
        "training_matches": 0, "calibration": {}, "model": {"dc_fitted": False, "params_method": "none"},
        "h2h_tiebreak": False, "source": "Sofascore", "cup_kind": cfg.kind, "phase": "pre", "phase_note": note,
        "detail_matches": len(store.get("lineups") or {}), "detail_season": len(_season_view(store).get("lineups") or {}), "sheet_matches": len(store.get("team_stats") or {}),
    }
    _write(out_dir, "meta.json", meta)
    return {
        **base, "ok": True, "phase": "pre", "reason": note, "tabs": TABS_PRE,
        "season": meta["season"], "updated_at": meta["updated_at"],
        "games_played": played, "games_total": len(fixtures["matches"]),
        "synthetic": meta["synthetic"], "store_fresh": meta["store_fresh"], "season_stale": False,
        "favourite": None, "p_favourite": None, "favourite_label": "Winner",
        **index_extras(fixtures["matches"], players, None),
        "_fixtures": fixtures["matches"], "_players": players, "_teams": teams_payload["teams"],
    }, None


def build_cup(cfg: CupConfig, entry: dict, args, sims: int | None, pooled: DixonColesModel | None,
              champions: dict[str, dict[str, float]], intl_model=None) -> tuple[dict, dict[str, float] | None]:
    """Build one cup; returns its index entry and its winner distribution for fixed brackets downstream."""
    from oddsmarkets.football.competitions.league.config import with_sims as _ws
    out_dir = DATA_DIR / cfg.slug
    if sims:
        cfg = _ws(cfg, sims)
    tabs = {"fixed": TABS_FIXED, "knockout": TABS_KNOCKOUT, "international": TABS_INTERNATIONAL}.get(cfg.kind, TABS_CUP)
    base = {
        "slug": cfg.slug, "name": cfg.name, "short_name": cfg.short_name, "country": cfg.region,
        "kind": "cup", "cup_kind": cfg.kind, "tabs": tabs,
        "family": cfg.family, "family_label": CUP_FAMILIES.get(cfg.family, cfg.family),
    }
    store = load_store(out_dir / "store.json")
    if not store.get("matches") and cfg.kind != "fixed":
        logger.warning("%s: no store — skipped", cfg.slug)
        return {**base, "ok": False, "reason": "no store yet"}, None
    if cfg.kind == "international":
        return build_international(cfg, store, out_dir, base, args, intl_model), None
    # A national cup's "Round 2", "Round 3" ... onto its bracket, its qualifying rounds off it (cup_store docstring).
    relabelled = cup_store.normalize_knockout_rounds(store, cfg)
    if relabelled:
        logger.info("%s: %d matches put on the bracket's rounds", cfg.slug, relabelled)
    age = store_age_hours(store)
    store_fresh = age is not None and age < _stale_after(store)
    synthetic = bool((store.get("meta") or {}).get("synthetic"))

    state = cup_store.cup_state_from_store(store, cfg, groups=entry.get("conferences") or {})
    logger.info(state.summary())
    if not state.teams and cfg.kind != "fixed":
        return build_cup_pre(cfg, store, out_dir, base, args)

    train_df = cup_store.training_frame(store)
    cal = empirical_calibration(train_df) if len(train_df) >= 30 else empirical_calibration(None)
    elo = EloRatings(k_league=20, home_advantage=50.0)
    if pooled is not None:
        dc = CupView(pooled, cfg.slug, state.team_league)
        method = "pooled"
    else:
        dc = DixonColesModel(xi=0.0035, ridge=1.0, fixed_rho=rho_hold(train_df))
        method = "own"
        if len(train_df) >= 50:
            try:
                dc.fit(train_df)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: fit failed (%s)", cfg.slug, exc)
    model = EnsembleModel(dc, elo, dc_weight=1.0 if dc.is_fitted else 0.0,
                          draw_rate=cal["draw_rate"], lam_scale=cal["lam_scale"], away_penalty=1.0)

    # Only the competitions this bracket actually draws from, or every other
    # cup's candidates would sit in the ladder at 0%.
    wanted = {slot.source.split(":", 1)[1] for tie in cfg.ties for slot in (tie.home, tie.away)
              if slot.source.startswith("champion:")}
    external = {k: v for k, v in champions.items() if k in wanted}
    results = CupSimulator(model, state, cfg=cfg, seed=args.seed, external_champions=external).run()
    winner_dist = {t: p for t, p in results.p_win.items() if p > 0 and t != AVERAGE}
    partial = cup_field_partial(cfg, state, top_flight_clubs(state))
    if partial:
        logger.info("%s: the top flight has not entered yet; winner chances withheld", cfg.slug)
        winner_dist = {}

    teams_payload = {
        "teams": {t: {"slug": _slug(t), "conference": state.zone_of(t), "team_id": state.team_ids.get(t),
                      "crest": crest_path(cfg.slug, state.team_ids.get(t)), "league": state.team_league.get(t)}
                  for t in results.teams},
        "updated_at": _now(),
    }
    _write(out_dir, "teams.json", teams_payload)

    def _rows(zone):
        out = []
        dist = results.p_group_position if zone else results.p_position
        for pos, (team, rec) in enumerate(state.standings(zone), start=1):
            q = results.points_quantiles.get(team, (0.0, 0.0, 0.0))
            out.append({
                "pos": pos, "team": team, "played": rec.played, "w": rec.won, "d": rec.drawn, "l": rec.lost,
                "gf": rec.gf, "ga": rec.ga, "gd": rec.gd, "pts": rec.points,
                "exp_pts": round(results.expected_points.get(team, 0.0), 2),
                "p05": round(q[0], 1), "p50": round(q[1], 1), "p95": round(q[2], 1),
                "p_title": round(results.p_win.get(team, 0.0), 5),
                "p_pos": [round(p, 5) for p in dist.get(team, [])],
                "bands": {b.key: round(results.p_in_band(b.key, team), 5) for b in cfg.bands},
            })
        return out

    table = {
        "season": state.season_name, "bands": _band_list(cfg), "tiebreak": list(cfg.tiebreak), "h2h_tiebreak": False,
        "fixtures": _fixture_rows(state.finished + state.remaining + state.playoff_matches),
        "games_played": state.games_played, "total_games": state.total_league_games,
        "matches_per_team": state.matches_per_team, "updated_at": _now(),
    }
    if cfg.kind in ("groups", "regional_swiss"):
        table["conferences"] = {g: _rows(g) for g in sorted(state.groups)}
        table["overall"] = []
        table["group_label"] = "Region" if cfg.kind == "regional_swiss" else "Group"
    elif cfg.kind == "swiss":
        table["standings"] = _rows(None)
    else:
        table["standings"] = []
    _write(out_dir, "table.json", table)

    labels = {**CUP_ROUND_LABELS, **{t.key: t.label for t in cfg.ties}}
    bracket_payload = {
        "kind": cfg.kind, "rounds": list(cfg.round_keys), "round_labels": labels,
        "seeds": {}, "confirmed": state.league_complete,
        "known": {r: [list(p) for p in pairs] for r, pairs in state.known_pairs.items()},
        "forced": {" v ".join(sorted(pair)): w for pair, w in state.playoff_results.items()},
        # The outside stand-in stays in the ladder so the columns still sum: its
        # row reads as "any of the outside sides".
        "reach": {t: {r: round(p, 5) for r, p in reach.items()} for t, reach in results.p_reach.items()
                  if t != AVERAGE or results.p_win.get(t, 0.0) > 0},
        "p_playoffs": {}, "p_cup": {} if partial else {t: round(p, 5) for t, p in results.p_win.items() if t != AVERAGE or p > 0},
        "field_partial": partial,
        "note": {
            "swiss": "Top eight go straight to the Round of 16; 9-24 play a two-legged play-off with the higher "
                     "finisher at home in the second leg. From the Round of 16 the bracket is fixed and two-legged; "
                     "the final is a single match. Pairings not yet drawn are drawn at random within the seeding "
                     "bands; ties already drawn or decided are taken as they stand.",
            "groups": "The top two of each group reach the two-legged knockout rounds, group winners at home in the "
                      "second leg against a runner-up from another group (drawn at random until the real draw is "
                      "known). Ties already decided are taken as played.",
            "regional_swiss": "The top eight of each region reach a two-legged Round of 16 played within the region "
                              "(1 v 8, 2 v 7 and so on, the higher finisher at home in the second leg). The "
                              "quarter-finals pair one region's winners against the other's; from the quarter-finals "
                              "every tie is a single match at the centralised finals venue with no home side. "
                              "Pairings not yet drawn are drawn at random; ties already drawn or decided are taken "
                              "as they stand.",
            "knockout": knockout_note(cfg),
            "fixed": "A fixed ladder of continental champions. A slot filled by another competition's champion "
                     "is drawn per simulation from that competition's own title probabilities. Rounds already "
                     "played are taken as they stand.",
        }[cfg.kind],
        "updated_at": _now(),
    }
    if partial:
        bracket_payload["note"] = PARTIAL_FIELD_NOTE
    _write(out_dir, "bracket.json", bracket_payload)
    probs = []
    for team in results.teams:
        probs.append({
            "team": team, "conference": state.zone_of(team), "exp_pts": round(results.expected_points.get(team, 0.0), 2),
            "p_title": round(results.p_win.get(team, 0.0), 5),
            "bands": {b.key: round(results.p_in_band(b.key, team), 5) for b in cfg.bands},
            "p_playoffs": round(results.p_reach.get(team, {}).get(cfg.round_keys[0], 0.0), 5),
            "p_cup": round(results.p_win.get(team, 0.0), 5),
            "p_conference": round(results.p_reach.get(team, {}).get("final", 0.0), 5),
        })
    probs.sort(key=lambda t: -t["p_cup"])
    if partial:
        for row in probs:
            row["p_title"] = row["p_cup"] = row["p_conference"] = None
    _write(out_dir, "probs.json", {"teams": probs, "bands": _band_list(cfg), "has_playoff": True, "field_partial": partial,
                                   "updated_at": _now()})

    players = cup_store.aggregate_players(_season_view(store)) if cfg.kind != "fixed" else []
    floor = add_percentiles(players) if players else 0
    strength_rows: list[dict] = []
    if cfg.kind != "fixed":
        strength_payload = build_strength_json(model, state, store, cfg)
        strength_rows = strength_payload["rows"]
        _write(out_dir, "strength.json", strength_payload)
        candidates = build_boot_candidates_from(players)
        live_players, leaders = build_players_json(players, store, {}, candidates, floor)
        _write(out_dir, "players_live.json", live_players)
        _write(out_dir, "player_leaders.json", leaders)
        _write(out_dir, "shots.json", {"players": cup_store.shots_by_player(_season_view(store))})
    else:
        _write(out_dir, "strength.json", {"rows": [], "elo_history": {}, "notes": {}, "updated_at": _now()})
        _write(out_dir, "players_live.json", {"ok": False, "players": [], "metrics": METRICS, "positions": POSITION_LABELS, "updated_at": _now()})
        _write(out_dir, "player_leaders.json", {"top_scorer": [], "live": []})
        _write(out_dir, "shots.json", {"players": {}})
    _write(out_dir, "history.json", build_history_json(out_dir, results, cfg))

    season_id = (store.get("meta") or {}).get("season_id")
    neutral_rounds = set(cfg.neutral_rounds) | ({"final"} if cfg.final_at_neutral_venue else set())
    fixtures = write_analytics(
        out_dir, store, cup_store.NO_REGISTRY, model, _season_filter(season_id), players,
        cup_store.player_match_logs(_season_view(store)), cup_store.team_match_stats(_season_view(store)), cup_store.match_details(store),
        neutral_when=lambda raw: raw.get("stage") == "playoff" and str(raw.get("round")) in neutral_rounds,
        floor=floor, season=state.season_name, round_labels=labels,
    )
    title_model = {} if partial else {t: p for t, p in results.p_win.items() if t != AVERAGE and p > 0}
    write_market_odds(out_dir, None if args.no_market else fetch_markets_safe(cfg, fixtures["matches"], title_model.keys(), state.season_name),
                      model, title_model)

    last = max((m.date for m in state.finished + state.playoff_matches if m.date), default=None)
    favourite = max(winner_dist, key=winner_dist.get) if winner_dist else None
    complete = bool(favourite and winner_dist.get(favourite, 0.0) >= 0.9999)
    meta = {
        "updated_at": _now(), "n_sims": results.n_sims, "runtime_s": round(results.runtime_s, 2),
        "season": state.season_name, "games_played": state.games_played, "games_total": state.total_league_games,
        "league_complete": state.league_complete, "store_fresh": store_fresh, "synthetic": synthetic,
        "store_age_hours": round(age, 1) if age is not None else None,
        "season_stale": bool(last and (datetime.now(timezone.utc) - last).days > 60),
        "training_matches": int(len(train_df)), "calibration": cal,
        "model": {"elo_home_advantage": 50.0, "elo_k_league": 20, "dc_weight": 1.0 if dc.is_fitted else 0.0,
                  "dc_xi": getattr(dc, "xi", None), "dc_ridge": getattr(dc, "ridge", None),
                  "dc_fitted": dc.is_fitted, "params_method": method},
        "h2h_tiebreak": False, "source": "Sofascore", "cup_kind": cfg.kind,
        "forced_ties": len(state.playoff_results), "cup_complete": complete, "field_partial": partial,
        "detail_matches": len(store.get("lineups") or {}), "detail_season": len(_season_view(store).get("lineups") or {}), "sheet_matches": len(store.get("team_stats") or {}),
    }
    _write(out_dir, "meta.json", meta)
    standings = table.get("standings") or (next(iter(table.get("conferences", {}).values()), None)) or []
    return {
        **base, "ok": True, "season": state.season_name, "updated_at": meta["updated_at"],
        "games_played": state.games_played, "games_total": state.total_league_games,
        "synthetic": synthetic, "store_fresh": store_fresh, "season_stale": meta["season_stale"],
        "favourite": favourite, "p_favourite": round(winner_dist.get(favourite, 0.0), 4) if favourite else None,
        "favourite_label": "Champion" if complete else "Winner", "complete": complete, "field_partial": partial,
        **index_extras(fixtures["matches"], players, standings if table.get("standings") else None),
        "_fixtures": fixtures["matches"], "_players": players, "_teams": teams_payload["teams"],
        "_strength": strength_rows, "_bracket": {"p_cup": bracket_payload["p_cup"], "reach": bracket_payload["reach"]},
        "_probs": probs, "_floor": floor,
    }, winner_dist


# ── Argentina, via its own build ─────────────────────────────────────────────

def build_liga(args, sims: int | None, copa_dist: dict[str, float] | None = None) -> dict:
    """Argentina: the zones, playoffs, Tabla Anual, promedios and berths (scripts/build_site_liga.py), then the
    same analytics payloads as every league. `copa_dist` is this run's Copa Argentina winner distribution (the
    cups are built first), from which the simulation draws the cup's Libertadores place."""
    out_dir = DATA_DIR / LIGA_ARGENTINA_SLUG
    base = {
        "slug": LIGA_ARGENTINA_SLUG, "name": "Liga Profesional de Fútbol",
        "short_name": "Liga Argentina", "country": "Argentina", "kind": "liga",
        "tabs": TABS_LIGA,
    }
    if not LIGA_STORE.exists():
        return {**base, "ok": False, "reason": "no store yet"}

    import scripts.build_site_liga as liga_build

    liga_build.SITE_DIR = out_dir
    liga_build.DATA_DIR = out_dir
    liga_build.STORE_PATH = LIGA_STORE
    liga_build.HISTORY_STORE = out_dir / "history_store.json"
    liga_build.PAST_STORE = DATA_DIR / "past" / "store.json"
    liga_build.COPA_BRACKET = DATA_DIR / "copa-argentina" / "bracket.json"
    liga_build.COPA_DIST = copa_dist or None
    argv = ["build"]
    if sims:
        argv += ["--sims", str(sims)]
    # The markets come from the leagues' pipeline below (Polymarket and Kalshi, The Odds API with a key), not the
    # Argentine build's own Odds-API-only fetch, which never read the Kalshi and Polymarket listings Argentina has.
    argv.append("--no-market")
    if args.seed is not None:
        argv += ["--seed", str(args.seed)]
    saved = sys.argv
    sys.argv = argv
    try:
        rc = liga_build.main()
    finally:
        sys.argv = saved
    if rc != 0:
        return {**base, "ok": False, "reason": f"liga build exited {rc}"}

    meta = _read_json(out_dir / "meta.json", {})
    probs = _read_json(out_dir / "probs.json", {"teams": []})
    top = max(probs.get("teams", []), key=lambda t: t.get("p_title", 0.0), default=None)
    entry = {
        **base, "ok": True,
        "season": f"{meta.get('phase', '').capitalize()} {liga_build.DEFAULT_CONFIG.season_year}".strip(),
        "updated_at": meta.get("updated_at"),
        "games_played": meta.get("games_played"), "games_total": meta.get("games_total"),
        "synthetic": meta.get("synthetic"), "store_fresh": meta.get("store_fresh"),
        "season_stale": meta.get("season_stale"),
        "favourite": top["team"] if top else None,
        "p_favourite": round(top["p_title"], 4) if top else None,
        "favourite_label": "Clausura",
    }

    # The analytics payloads on top, from the same store and the model just fitted.
    last = getattr(liga_build, "LAST_BUILD", None) or {}
    store = last.get("store") or load_store(LIGA_STORE)
    model = last.get("model")
    if last.get("model") is not None and last.get("state") is not None:
        write_sensitivity(out_dir, LIGA_ARGENTINA_SLUG, lambda: liga_sensitivity(last["model"], last["state"], last["cfg"], budget_s=SENS_BUDGET_S))
    registry = "liga_argentina"
    year = str(liga_build.DEFAULT_CONFIG.season_year)
    # The season is the torneo being played (Clausura), not the calendar year the
    # store holds: aggregating the year kept Apertura players (Ander Herrera at
    # Boca Juniors) on the current pages. The Apertura is a past season in the
    # season picker (analytics/unified.py).
    torneo = str(meta.get("phase") or "")
    in_season = lambda raw: str(raw.get("date") or "").startswith(year) and (not torneo or raw.get("torneo") == torneo)  # noqa: E731
    view = _torneo_view(store, in_season)
    players = _liga.aggregate_players(view, registry=registry)
    floor = add_percentiles(players)
    # Re-write the player payloads with the catalogue and percentiles the hub expects;
    # the scorer race's probabilities come from the Argentine build's own leaders.
    live, leaders = build_players_json(players, store, {}, [], floor)
    prev_leaders = _read_json(out_dir / "player_leaders.json", None) or {}
    model_p = {str(r.get("id")): r.get("model") for r in (prev_leaders.get("live") or []) if r.get("model") is not None}
    for r in leaders["live"]:
        if model_p.get(str(r["id"])) is not None:
            r["model"] = model_p[str(r["id"])]
    leaders["live"].sort(key=lambda r: (-(r["model"] or 0), -r["goals"], -r["xg"]))
    leaders["top_scorer"] = leaders["live"][:40]
    _write(out_dir, "players_live.json", live)
    _write(out_dir, "player_leaders.json", leaders)
    _write(out_dir, "shots.json", {"players": _liga.shots_by_player(view, registry=registry)})
    fixtures = write_analytics(
        out_dir, store, registry, model, in_season, players,
        _liga.player_match_logs(view, registry=registry), _liga.team_match_stats(view, registry=registry),
        _liga.match_details(store, registry=registry),
        floor=floor, season=entry["season"] or year, lineup_terms=LINEUP_TERMS.get(LIGA_ARGENTINA_SLUG),
    )
    # The market beside our lines, as for every league: the match listings and the title market (the torneo's).
    if model is not None:
        from types import SimpleNamespace
        from oddsmarkets.football.competitions.liga.config import ODDS_API_SPORT
        mcfg = SimpleNamespace(slug=LIGA_ARGENTINA_SLUG, name=base["name"], odds_api_sport=ODDS_API_SPORT)
        title_model = {r["team"]: r.get("p_title", 0.0) for r in probs.get("teams") or [] if r.get("team")}
        try:
            write_market_odds(out_dir, None if args.no_market else fetch_markets_safe(mcfg, fixtures["matches"], title_model.keys(), entry["season"]),
                              model, title_model, adjust=lineup_lines(fixtures["matches"]))
        except Exception as exc:  # noqa: BLE001 - the market is a reference; the competition stands without it
            logger.warning("%s: market odds failed: %s", LIGA_ARGENTINA_SLUG, exc)
    # The Argentine build resolves crests against its own site; the hub keeps
    # every crest under docs/site/assets/crests, so fill them in here.
    teams_payload = _read_json(out_dir / "teams.json", {}) or {}
    teams = teams_payload.get("teams") or {}
    for info in teams.values():
        if isinstance(info, dict) and not info.get("crest"):
            info["crest"] = crest_path(LIGA_ARGENTINA_SLUG, info.get("team_id"))
    if teams:
        _write(out_dir, "teams.json", teams_payload)
    return {
        **entry, **index_extras(fixtures["matches"], players, None),
        "_fixtures": fixtures["matches"], "_players": players, "_teams": teams,
        "_strength": (_read_json(out_dir / "strength.json", {}) or {}).get("rows") or [],
        "_probs": probs.get("teams") or [], "_floor": floor,
    }


# ── site-wide payloads ───────────────────────────────────────────────────────

HUB_RATING_MINUTES = 450
UPCOMING_STATUSES = ("scheduled", "live")


def _once(rows: list[dict]) -> list[dict]:
    """Each player's first (best) row of a sorted leader list: a player in two competitions is listed once."""
    seen: set[str] = set()
    return [r for r in rows if not (str(r.get("id")) in seen or seen.add(str(r.get("id"))))]


def build_hub(entries: list[dict], now: datetime | None = None) -> dict:
    """The scoreboard across competitions for the coming week, and the leaders across them."""
    today = (now or datetime.now(timezone.utc)).date()
    today_s = today.isoformat()
    lo = (today - timedelta(days=HUB_DAYS_BACK)).isoformat()
    hi = (today + timedelta(days=HUB_DAYS_AHEAD)).isoformat()
    days: dict[str, list[dict]] = {}
    goals: list[dict] = []
    assists: list[dict] = []
    ratings: list[dict] = []
    recent: list[dict] = []
    upcoming: list[dict] = []
    for c in entries:
        if not c.get("ok"):
            continue
        crests = {t: (info or {}).get("crest") for t, info in (c.get("_teams") or {}).items()}
        # Club ids too: the public build ships no crests (D6), and the pages find a club's kit colours
        # (clubs_index.json) and its link by id.
        tids = {t: (info or {}).get("team_id") for t, info in (c.get("_teams") or {}).items()}
        rows = c.get("_fixtures") or []
        # Outside the window every competition still contributes its latest
        # results day and its next fixtures day, so the scoreboard is never
        # empty during an international break. The next day is today or later and
        # lists only matches still to play: a fixture the store never closed (a
        # postponed or re-listed tie keeps "scheduled" under its old id) once made a
        # September day of finished CAF ties "upcoming" in October.
        played_days = sorted({d for r in rows if r.get("status") == "finished" and (d := (r.get("date") or "")[:10]) and d <= today_s})
        next_days = sorted({d for r in rows if r.get("status") in UPCOMING_STATUSES and (d := (r.get("date") or "")[:10]) and d >= today_s})
        last_day = played_days[-1] if played_days else None
        next_day = next_days[0] if next_days else None
        for r in rows:
            d = (r.get("date") or "")[:10]
            bucket = "window" if d and lo <= d <= hi else "recent" if d and d == last_day else \
                "upcoming" if d and d == next_day and r.get("status") in UPCOMING_STATUSES else None
            if not bucket:
                continue
            item = {
                "comp": c["slug"], "comp_name": c.get("short_name") or c["name"], "kind": c["kind"], "family": c.get("family"),
                "id": r["id"], "date": r["date"], "home": r["home"], "away": r["away"],
                "hs": r.get("hs"), "as": r.get("as"), "status": r["status"], "stage": r.get("stage"),
                "round": r.get("round"), "detail": r.get("detail", False),
                "crests": [crests.get(r["home"]), crests.get(r["away"])],
            }
            if tids.get(r["home"]):
                item["home_id"] = int(tids[r["home"]])
            if tids.get(r["away"]):
                item["away_id"] = int(tids[r["away"]])
            if r.get("model"):
                item["model"] = {k: r["model"][k] for k in ("h", "d", "a")}
                if r["model"].get("lineups"):
                    item["model"]["lineups"] = True
            if r.get("xg"):
                item["xg"] = r["xg"]
            if bucket == "window":
                days.setdefault(d, []).append(item)
            elif bucket == "recent":
                recent.append(item)
            else:
                upcoming.append(item)
        for p in c.get("_players") or []:
            row = {"id": p["player_id"], "name": p["name"], "team": p["team"], "comp": c["slug"],
                   "comp_name": c.get("short_name") or c["name"], "pos": p.get("position")}
            if p.get("goals"):
                goals.append({**row, "value": p["goals"], "xg": p.get("xg")})
            if p.get("assists"):
                assists.append({**row, "value": p["assists"], "xa": p.get("xa")})
            # A cup two matches old qualifies everyone; the site-wide list wants a season's worth.
            if p.get("rating") is not None and p.get("qualified") and (p.get("minutes") or 0) >= HUB_RATING_MINUTES:
                ratings.append({**row, "value": p["rating"], "minutes": p.get("minutes")})
    for d in days:
        days[d].sort(key=lambda i: (i["date"] or "", i["comp"]))
    recent.sort(key=lambda i: (i["date"] or "", i["comp"]), reverse=True)
    upcoming.sort(key=lambda i: (i["date"] or "", i["comp"]))
    goals.sort(key=lambda r: (-r["value"], -(r.get("xg") or 0)))
    assists.sort(key=lambda r: (-r["value"], -(r.get("xa") or 0)))
    ratings.sort(key=lambda r: -r["value"])
    return {
        "days": days, "window": [lo, hi], "today": today.isoformat(),
        "recent": recent, "upcoming": upcoming,
        # One row per player (his best line): the cross-competition totals are data/lab/leaders.json.
        "leaders": {"goals": _once(goals)[:15], "assists": _once(assists)[:15], "rating": _once(ratings)[:15]},
        "updated_at": _now(),
    }


# ── the overview's "This week in football" digest (hub.json "digest") ──────────────────────────────────────────

DIGEST_BIG = ("premier-league", "la-liga", "serie-a", "bundesliga", "ligue-1", "champions-league")
DIGEST_MIN_TIER = 30          # featured.TIERS: the competitions whose clubs can be "team of the week" or a title mover
FORECAST_LOG_DAYS = 9


def _forecast_log(prev: dict | None, rows_by_comp: dict, now: datetime) -> dict:
    """data/forecast_log.json: our pre-match chance for each match, frozen at the last build before kick-off. Football
    drops a match's forecast once it is finished (the fixtures carry none), so this log is the only no-look-ahead
    source of "what we said" for the week's record and upset. {match id: [h, d, a, kick-off ISO, comp]}; an entry is
    only ever written while its kick-off is still ahead, and kept FORECAST_LOG_DAYS days after it."""
    log = {k: v for k, v in (prev or {}).items() if isinstance(v, list) and len(v) >= 4}
    lo = now - timedelta(days=FORECAST_LOG_DAYS)
    for slug, rows in rows_by_comp.items():
        for r in rows:
            m, d = r.get("model") or {}, r.get("date")
            if r.get("status") != "scheduled" or not d or m.get("h") is None:
                continue
            try:
                ko = datetime.fromisoformat(str(d).replace("Z", "+00:00"))
            except ValueError:
                continue
            if now < ko <= now + timedelta(days=FORECAST_LOG_DAYS):
                log[str(r["id"])] = [round(float(m["h"]), 4), round(float(m.get("d") or 0.0), 4), round(float(m.get("a") or 0.0), 4), d, slug]
    out = {}
    for k, v in log.items():
        try:
            ko = datetime.fromisoformat(str(v[3]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if ko >= lo:
            out[k] = v
    return out


def build_digest(entries: list[dict], data_dir: Path, now: datetime | None = None) -> dict:
    """hub.json "digest": the overview's top lines (oddsmarkets/common/digest.py) and the featured matches
    (oddsmarkets/common/featured.py rank_featured). Record and upset read only data/forecast_log.json (the chance
    frozen before kick-off); movers read each big league's history.json (our title chance run by run)."""
    from oddsmarkets.common import digest as DG
    from oddsmarkets.common import featured as FT
    now = now or datetime.now(timezone.utc)
    ok = [c for c in entries if c.get("ok")]
    rows_by = {c["slug"]: (c.get("_fixtures") or []) for c in ok}

    def tier(slug):
        return FT.TIERS["football"].get(slug, FT.TIERS["football"]["*"])
    ids = {c["slug"]: {t: (info or {}).get("team_id") for t, info in (c.get("_teams") or {}).items()} for c in ok}
    names = {c["slug"]: c.get("short_name") or c.get("name") for c in ok}

    def side(slug, t):
        return {"name": t, "id": ids.get(slug, {}).get(t) or t}
    out: dict = {"asof": now.isoformat().replace("+00:00", "Z")[:16] + "Z"}

    # the week's record and upset, from the frozen pre-match chances only
    log = _forecast_log(_read_json(data_dir / "forecast_log.json", {}), rows_by, now)
    _write(data_dir, "forecast_log.json", log)
    fin = []
    for slug, rows in rows_by.items():
        for r in rows:
            f = log.get(str(r.get("id")))
            if r.get("status") != "finished" or not f:
                continue
            fin.append({"id": r["id"], "sport": "football", "comp": slug, "league": names.get(slug), "start": r.get("date"), "status": "final",
                        "home": side(slug, r["home"]), "away": side(slug, r["away"]), "hs": r.get("hs"), "as": r.get("as"),
                        "p_home": f[0], "p_draw": f[1], "p_away": f[2]})
    rec = DG.record(fin, now)
    if rec:
        rec.pop("by", None)
        out["record"] = rec
    up = DG.upset(fin, now)
    if up:
        up["comp"] = next(x["comp"] for x in fin if x["id"] == up["id"])
        out["upset"] = up

    # team of the week, among the clubs of the biggest competitions (two or more matches this week)
    week = []
    for slug, rows in rows_by.items():
        if tier(slug) < DIGEST_MIN_TIER:
            continue
        for r in rows:
            if r.get("status") == "finished" and r.get("hs") is not None:
                week.append({"id": r["id"], "start": r.get("date"), "status": "final", "home": side(slug, r["home"]), "away": side(slug, r["away"]),
                             "hs": r.get("hs"), "as": r.get("as"), "comp": slug, **({"winner": "draw"} if r.get("hs") == r.get("as") else {})})
    hot = DG.hot(week, now)
    if hot:
        hot["name"] = next((g[s]["name"] for g in week for s in ("home", "away") if g[s]["id"] == hot["key"]), str(hot["key"]))
        out["hot"] = hot

    # the biggest title-chance moves this week in the big leagues (history.json: our title chance after each run)
    moves = []
    for c in ok:
        slug = c["slug"]
        if c.get("kind") != "league" or tier(slug) < DIGEST_MIN_TIER:
            continue
        snaps = (_read_json(data_dir / slug / "history.json", {}) or {}).get("snapshots") or []
        teams = {t for s in snaps[-1:] for t, p in (s.get("title") or {}).items() if (p or 0) >= 0.01}
        for t in sorted(teams):
            pts = [[s["ts"], (s.get("title") or {}).get(t)] for s in snaps if s.get("ts") and (s.get("title") or {}).get(t) is not None]
            sw = DG.swing([{"name": t, "league": names.get(slug), "kind": "title", "points": pts}], now, min_move=0.02)
            if sw:
                sw.update({"comp": slug, "id": ids.get(slug, {}).get(t)})
                sw.pop("href", None)
                sw.pop("sport", None)
                moves.append(sw)
    if moves:
        out["movers"] = {"up": sorted([m for m in moves if m["delta"] > 0], key=lambda m: -m["delta"])[:2],
                         "down": sorted([m for m in moves if m["delta"] < 0], key=lambda m: m["delta"])[:2]}

    # the stage: how far the big competitions have gone
    st = []
    for slug in DIGEST_BIG:
        c = next((x for x in ok if x["slug"] == slug), None)
        if not c:
            continue
        rows = [r for r in rows_by.get(slug) or [] if r.get("stage") == "league" and isinstance(r.get("round"), int)]
        played = [r["round"] for r in rows if r.get("status") == "finished"]
        nxt = sorted(r["date"] for r in rows if r.get("status") in UPCOMING_STATUSES and r.get("date"))
        st.append({"comp": slug, "name": c.get("short_name") or c.get("name"), "round": max(played) if played else 0,
                   "rounds": max((r["round"] for r in rows), default=0), "next": nxt[0] if nxt else None})
    out["stage"] = {"in_season": sum(1 for c in ok if not c.get("complete")), "big": st}

    # the featured matches: the shared significance rule over the coming week
    title_p = {c["slug"]: {t.get("team"): t.get("p_title") for t in c.get("_probs") or [] if t.get("team")} for c in ok}
    games, comp_of = [], {}
    for slug, rows in rows_by.items():
        tp = title_p.get(slug) or {}
        for r in rows:
            stt = r.get("status")
            if stt not in UPCOMING_STATUSES or not r.get("date"):
                continue
            m = r.get("model") or {}
            rnd = r.get("round") if isinstance(r.get("round"), str) else None
            stage = FT.stage_of({"sig": {"round": rnd}}) or ("knockout" if r.get("stage") == "playoff" else None)
            comp_of[str(r["id"])] = slug
            games.append({"sport": "football", "league": names.get(slug), "id": r["id"], "start": r["date"],
                          "status": "live" if stt == "live" else "pre", "home": r["home"], "away": r["away"],
                          "p_home": m.get("h"), "p_draw": m.get("d"), "p_away": m.get("a"),
                          "sig": {"comp": slug, "stage": stage, "title": [tp.get(r["home"]) or 0.0, tp.get(r["away"]) or 0.0] if tp else None,
                                  "rivalry": FT.RIVALRIES.get(frozenset((r["home"], r["away"])))}})

    title_of = {str(g["id"]): g["sig"]["title"] for g in games if g["sig"].get("title") and max(g["sig"]["title"]) >= 0.005}

    def row(x):
        i = x["key"].split(":", 1)[1]
        out_ = {"id": i, "comp": comp_of.get(i), "score": x["score"], "why": x.get("reasons") or []}
        if i in title_of:
            out_["title"] = [round(float(p), 3) for p in title_of[i]]     # our title chance, home and away
        return out_
    r = FT.rank_featured(games, now)
    today_ids = {x["key"] for x in r["today"]}
    nxt = FT.rank_featured(games, now, horizon_h=168, limit=13)
    out["featured"] = {"today": [row(x) for x in r["today"]], "next": [row(x) for x in nxt["today"] if x["key"] not in today_ids][:5],
                       "week": row(r["week"]) if r.get("week") else None}
    return out


def build_search(entries: list[dict]) -> dict:
    teams, players = [], []
    for c in entries:
        if not c.get("ok"):
            continue
        for t, info in (c.get("_teams") or {}).items():
            teams.append({"n": t, "comp": c["slug"], "comp_name": c.get("short_name") or c["name"],
                          "slug": (info or {}).get("slug") or _slug(t), "crest": (info or {}).get("crest")})
        for p in c.get("_players") or []:
            players.append({"id": p["player_id"], "n": p["name"], "t": p["team"], "comp": c["slug"],
                            "pos": p.get("position"), "min": p.get("minutes", 0)})
    players.sort(key=lambda p: -p["min"])
    # One row per player: his competition with most minutes, the others listed (the people index is the full registry).
    comps: dict[str, list[str]] = {}
    for p in players:
        comps.setdefault(str(p["id"]), []).append(p["comp"])
    once = _once(players)
    for p in once:
        p["comps"] = comps[str(p["id"])]
    return {"teams": teams, "players": once, "updated_at": _now()}


# ── people, clubs, seasons ───────────────────────────────────────────────────

def build_unified(entries: list[dict], seasons: dict, archive: dict) -> dict[str, dict]:
    """
    The unified registries (data/people/, data/clubs/, the two indexes) and every
    competition's season list and past-season payloads (data/<slug>/seasons.json,
    data/<slug>/s/<sid>/season.json); see docs/site/UNIFIED_PAYLOADS.md. Stores
    are read one at a time. Returns the per-competition keys for competitions.json.
    """
    from oddsmarkets.football.analytics.people_lines import PeopleLines
    from oddsmarkets.football.analytics.unified import (
        INTL_SPLIT_START_MONTH, NEUTRAL_COMPETITIONS, Unified, competitions, liga_season_key,
    )
    from oddsmarkets.football.analytics.value import ValueCollector

    global LAST_UNIFIED
    comps_u = competitions()
    collector = ValueCollector()

    def gather(slug: str, store: dict, key_of=lambda m: m.get("season_id")) -> None:
        # One line per person (data/lab/): the same stores, each edition in its season (u.season_meta).
        try:
            lines.add_store(slug, store, era_of=lambda m: (u.season_meta.get((slug, str(key_of(m)))) or {}).get("era"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("people lines: %s skipped: %s", slug, exc)

    def collect(slug: str, store: dict, **kw) -> None:
        # The value model reads the same stores; one failing store must not stop the registries.
        try:
            collector.add_store(slug, store, scope=(comps_u.get(slug) or {}).get("scope", "club"), **kw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("value: %s line-ups skipped: %s", slug, exc)

    u = Unified(DATA_DIR, seasons, archive=archive,
                past=_read_json(DATA_DIR / "past" / "store.json", {}) or {},
                squads=_read_json(DATA_DIR / "squads" / "store.json", {}) or {},
                entries=entries, pool=_read_json(DATA_DIR / "pool.json", {}) or {})
    lines = PeopleLines(comps_u, today=u.today, neutral=NEUTRAL_COMPETITIONS, intl_split_month=INTL_SPLIT_START_MONTH)
    for slug in list(LEAGUES) + list(CUPS):
        path = DATA_DIR / slug / "store.json"
        if path.exists():
            store = load_store(path)
            u.add_store(slug, store)
            collect(slug, store, current_key=u.current.get(slug))
            gather(slug, store)
            del store
    if LIGA_STORE.exists():
        import scripts.build_site_liga as liga_build

        phase = (_read_json(DATA_DIR / LIGA_ARGENTINA_SLUG / "meta.json", {}) or {}).get("phase")
        year = liga_build.DEFAULT_CONFIG.season_year
        store = load_store(LIGA_STORE)
        u.add_store(LIGA_ARGENTINA_SLUG, store, current_key=f"{year}-{phase}" if phase else None)
        collect(LIGA_ARGENTINA_SLUG, store, season_key=liga_season_key, current_key=u.current.get(LIGA_ARGENTINA_SLUG))
        gather(LIGA_ARGENTINA_SLUG, store, key_of=liga_season_key)
        del store
    counts = u.finish()
    u.mark_departed()
    try:
        pool = _read_json(DATA_DIR / "pool.json", {}) or {}
        factors = {s: float(L["factor_att"]) for s, L in (pool.get("leagues") or {}).items() if L.get("factor_att") is not None}
        lines.merge_aliases(u.aliases)
        lines.finish(DATA_DIR, frames=u.frame_of_person, people=u.people, club_of=getattr(u, "club_of", {}) or {},
                     clubs=u.clubs, factors=factors)
    except Exception as exc:  # noqa: BLE001
        logger.error("people lines failed: %s\n%s", exc, traceback.format_exc())
    lines.release()                       # the Lab is written; the window logic stays for the value step (value_views)
    LAST_UNIFIED = {"unified": u, "rows": collector.finish(), "comps": comps_u, "lines": lines}
    logger.info("unified: %d people, %d clubs, %d competitions with seasons", counts["people"], counts["clubs"], len(u.manifests))
    return u.competition_fields()


LAST_UNIFIED: dict | None = None


def build_value_layer(entries: list[dict], archive: dict) -> dict:
    """data/value/: the player value model and its payloads, from the line-ups the unified step collected."""
    from oddsmarkets.football.analytics.value_payloads import ValueContext, build_value

    last = LAST_UNIFIED or {}
    u, rows = last.get("unified"), last.get("rows")
    if u is None or rows is None:
        raise RuntimeError("the unified step did not run")
    ctx = ValueContext(
        data_dir=DATA_DIR, comps=last.get("comps") or {}, pool=_read_json(DATA_DIR / "pool.json", {}) or {},
        people=u.people, club_of=getattr(u, "club_of", {}) or {}, clubs=u.clubs, squads=u.squads, archive=archive,
        entries=entries,
    )
    return build_value(ctx, rows)


def lab_value_windows(row_gar, row_extra=None) -> dict | None:
    """PeopleLines.value_views over the value model's rows: {"windows": {window: {pid: {slug: [GAR, minutes, PAR,
    rating x minutes, rated minutes, components...]}}}, "intl": [...]}, tagged as the Lab tags each match (None
    without the unified step or the value layer)."""
    last = LAST_UNIFIED or {}
    u, rows, lines = last.get("unified"), last.get("rows"), last.get("lines")
    if u is None or rows is None or lines is None or row_gar is None:
        return None
    meta = u.season_meta
    out = lines.value_views(rows, row_gar, lambda slug, key: (meta.get((slug, str(key))) or {}).get("era"), u.frame_of_person,
                            extra=row_extra)
    logger.info("value by Lab window: %s", ", ".join(f"{w} {len(v)} people" for w, v in out["windows"].items()))
    return out


def build_fantasy_layer(entries: list[dict], value_score: dict) -> dict:
    """data/fantasy/: FPL-style projections, picks, squads and the walk-forward backtest (analytics/fantasy.py)."""
    from oddsmarkets.football.analytics.fantasy import build_fantasy

    last = LAST_UNIFIED or {}
    u, rows = last.get("unified"), last.get("rows")
    if u is None or rows is None:
        raise RuntimeError("the unified step did not run")
    return build_fantasy(rows, people=u.people, club_of=getattr(u, "club_of", {}) or {}, entries=entries, value_score=value_score,
                         out_dir=DATA_DIR / "fantasy", today=datetime.now(timezone.utc).date(), comps=last.get("comps") or {})


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sims", type=int, default=None, help="override simulation count")
    parser.add_argument("--no-market", action="store_true", help="skip the odds fetch")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--only", action="append", help="build only these slugs")
    parser.add_argument("--skip-liga", action="store_true", help="skip the Argentine build")
    parser.add_argument("--no-market-rates", action="store_true",
                        help="fit without the market-implied rates of past matches (football-data closing prices)")
    parser.add_argument("--no-sensitivity", action="store_true",
                        help="skip the per-club sensitivity curves (the transfer simulator then shows values only)")
    parser.add_argument("--no-value", action="store_true", help="skip the player value layer (data/value/)")
    parser.add_argument("--no-fantasy", action="store_true", help="skip the fantasy layer (data/fantasy/)")
    args = parser.parse_args()
    global USE_MARKET_RATES, USE_SENSITIVITY, LAST_UNIFIED
    USE_MARKET_RATES = not args.no_market_rates
    USE_SENSITIVITY = not args.no_sensitivity
    if not USE_MARKET_RATES:
        os.environ["NO_MARKET_RATES"] = "1"  # read by the Argentine build
    if USE_MARKET_RATES and not args.no_market:
        market_rates.refresh()  # at most once a day per file; cached under data/football/odds/raw
        if kalshi_rates.on():
            kalshi_rates.refresh()  # Kalshi listings and new games' candles, paced and capped; data/football/odds/kalshi

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # The shared design kit (docs/_design -> docs/site/assets/qk): the front end is built on it (docs/REDESIGN.md).
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from design_kit import copy_kit
        copy_kit(SITE_DIR)
    except Exception as exc:  # noqa: BLE001 - a missing kit must not stop the data build
        logger.error("design kit copy failed: %s", exc)
    seasons = _read_json(SEASONS_PATH, {}).get("leagues", {})
    if not seasons:
        logger.warning("No %s — leagues will build from their stores alone", SEASONS_PATH)

    # One pooled fit serves every league whose tuned choice was "pooled".
    pooled_slugs = [
        slug for slug in LEAGUES
        if model_params_for(slug)[1] == "pooled" and (not args.only or slug in args.only)
    ]
    cup_slugs = [slug for slug in CUPS if not args.only or slug in args.only]
    pooled = None
    if pooled_slugs or cup_slugs:
        stores = {slug: load_store(DATA_DIR / slug / "store.json") for slug in LEAGUES}
        stores = {k: v for k, v in stores.items() if v.get("matches")}
        cup_stores = {slug: load_store(DATA_DIR / slug / "store.json") for slug in CUPS if CUPS[slug].family != "international"}
        cup_stores = {k: v for k, v in cup_stores.items() if v.get("matches")}
        pooled_params = _read_json(MODEL_PARAMS_PATH, {}).get("pooled") or DEFAULT_PARAMS
        pooled = fit_pooled(stores, pooled_params, cup_stores)

    # Positions for players a store saw without one (players.positions_from_store's fallback).
    try:
        loaded = list(stores.values()) + list(cup_stores.values()) if (pooled_slugs or cup_slugs) else []
        set_fallback_positions(fallback_positions(_read_json(DATA_DIR / "squads" / "store.json", {}), loaded))
    except Exception as exc:  # noqa: BLE001 - positions are an extra; the builds stand without them
        logger.warning("fallback positions skipped: %s", exc)

    # Line-up term (docs/MODELS.md 2.6): fixtures whose confirmed XIs the fetcher stored in the last hour.
    global LINEUP_TERMS
    try:
        have = bool(pooled_slugs or cup_slugs)
        lg_stores = stores if have else {s: load_store(DATA_DIR / s / "store.json") for s in LEAGUES}
        terms_in = {k: v for k, v in lg_stores.items() if not args.only or k in args.only}
        if LIGA_STORE.exists() and not args.skip_liga and (not args.only or LIGA_ARGENTINA_SLUG in args.only):
            terms_in[LIGA_ARGENTINA_SLUG] = load_store(LIGA_STORE)
        LINEUP_TERMS = lineup_strength.live_terms(terms_in, cup_stores if have else {})
        if LINEUP_TERMS:
            logger.info("line-ups posted: %s", {k: len(v) for k, v in LINEUP_TERMS.items()})
    except Exception as exc:  # noqa: BLE001 - the term is an extra; the lines without it stand
        logger.error("line-up term failed: %s\n%s", exc, traceback.format_exc())
        LINEUP_TERMS = {}

    competitions = []
    for slug, cfg in LEAGUES.items():
        if args.only and slug not in args.only:
            continue
        try:
            competitions.append(build_league(cfg, seasons.get(slug) or {}, args, args.sims, pooled=pooled))
        except Exception as exc:  # noqa: BLE001
            logger.error("%s: build failed: %s\n%s", slug, exc, traceback.format_exc())
            competitions.append({
                "slug": slug, "name": cfg.name, "short_name": cfg.short_name,
                "country": cfg.country, "kind": "league", "ok": False, "reason": str(exc),
                "tabs": TABS_LEAGUE,
            })

    # The national teams' fit, over every international store.
    intl_stores = {slug: load_store(DATA_DIR / slug / "store.json") for slug in INTERNATIONALS}
    intl_stores = {k: v for k, v in intl_stores.items() if v.get("matches")}
    intl_model, intl_cal = fit_international(intl_stores) if intl_stores else (None, {})

    # Cups after the leagues, and the fixed brackets last so they can draw from
    # the others' simulated champions.
    champions: dict[str, dict[str, float]] = {}
    seasons_all = seasons
    for slug in sorted(cup_slugs, key=lambda s_: CUPS[s_].kind == "fixed"):
        cfg = CUPS[slug]
        try:
            entry, dist = build_cup(cfg, seasons_all.get(slug) or {}, args, args.sims, pooled, champions, intl_model=intl_model)
            competitions.append(entry)
            if dist:
                champions[slug] = dist
        except Exception as exc:  # noqa: BLE001
            logger.error("%s: build failed: %s\n%s", slug, exc, traceback.format_exc())
            competitions.append({
                "slug": slug, "name": cfg.name, "short_name": cfg.short_name, "country": cfg.region,
                "kind": "cup", "cup_kind": cfg.kind, "ok": False, "reason": str(exc), "tabs": TABS_CUP,
                "family": cfg.family, "family_label": CUP_FAMILIES.get(cfg.family, cfg.family),
            })

    if not args.skip_liga and (not args.only or LIGA_ARGENTINA_SLUG in args.only):
        try:
            competitions.append(build_liga(args, args.sims, champions.get("copa-argentina")))
        except Exception as exc:  # noqa: BLE001
            logger.error("liga build failed: %s\n%s", exc, traceback.format_exc())
            competitions.append({
                "slug": LIGA_ARGENTINA_SLUG, "name": "Liga Profesional de Fútbol",
                "short_name": "Liga Argentina", "country": "Argentina", "kind": "liga",
                "ok": False, "reason": str(exc), "tabs": TABS_LIGA,
            })

    # Site-wide payloads from what was built this run; competitions not rebuilt
    # (--only) keep their previous hub entries by re-reading their fixtures.
    prev = {c["slug"]: c for c in _read_json(DATA_DIR / "competitions.json", {}).get("competitions", [])}
    built = {c["slug"] for c in competitions}
    hub_entries = list(competitions)
    for slug, c in prev.items():
        if slug in built or not c.get("ok"):
            continue
        fx = _read_json(DATA_DIR / slug / "fixtures.json", {}).get("matches") or []
        live = _read_json(DATA_DIR / slug / "players_live.json", {})
        tm = _read_json(DATA_DIR / slug / "teams.json", {}).get("teams") or {}
        br = _read_json(DATA_DIR / slug / "bracket.json", {})
        hub_entries.append({
            **c, "_fixtures": fx, "_players": live.get("players") or [], "_teams": tm, "_floor": live.get("minutes_floor"),
            "_strength": _read_json(DATA_DIR / slug / "strength.json", {}).get("rows") or [],
            "_probs": _read_json(DATA_DIR / slug / "probs.json", {}).get("teams") or [],
            "_bracket": {"p_cup": br.get("p_cup") or {}, "reach": br.get("reach") or {}} if br else None,
        })
    hub = build_hub(hub_entries)
    try:
        hub["digest"] = build_digest(hub_entries, DATA_DIR)
    except Exception as exc:  # noqa: BLE001  (a top line is never the reason the hub goes unwritten)
        logger.error("hub digest failed: %s\n%s", exc, traceback.format_exc())
    _write(DATA_DIR, "hub.json", hub)
    _write(DATA_DIR, "search.json", build_search(hub_entries))

    # The layer above the competitions: the pool, the nations, the archive. Each step degrades on its own; one failing must not take the
    # others with it (a missing reference file once emptied the whole layer).
    def _step(name, fn):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            logger.error("site-wide build: %s failed: %s\n%s", name, exc, traceback.format_exc())
            return None

    _step("nations", lambda: build_nations(DATA_DIR, intl_model, intl_cal, intl_stores))
    _step("glossary", lambda: _write(DATA_DIR, "glossary.json", build_glossary()))
    n_index = _step("season index", lambda: build_season_index(DATA_DIR, hub_entries))
    _step("club matches", lambda: build_club_matches(DATA_DIR, hub_entries))
    if n_index is not None:
        logger.info("season index: %d players", n_index)
    _step("pool", lambda: site_global.build_global(DATA_DIR, hub_entries, pooled, POOL_CONNECTIONS, POOL_BRIDGES))
    archive = _step("archive", lambda: load_archive(DATA_DIR / "archive" / "store.json")) or {}
    counts = _step("archive pages", lambda: site_global.build_archive_pages(DATA_DIR, archive)) or {"careers": 0, "seasons": 0}
    logger.info("site-wide payloads: %d careers, %d past seasons", counts["careers"], counts["seasons"])

    unified = _step("people, clubs and seasons", lambda: build_unified(hub_entries, seasons, archive)) or {}
    from oddsmarkets.football.analytics import value_fields
    roles_before = value_fields.roles(DATA_DIR)
    value = None
    if not args.no_value:
        value = _step("player value", lambda: build_value_layer(hub_entries, archive))
        if value:
            logger.info("player value: %d players, %d lines, %d clubs", value["players"], value["lines"], value["clubs"])
            if not args.no_fantasy:
                fan = _step("fantasy", lambda: build_fantasy_layer(hub_entries, value.get("_fantasy_score") or {}))
                if fan:
                    logger.info("fantasy: %d leagues in %.1fs", fan["leagues"], fan["runtime_s"])
    # the value model's role and GAR/90 on players_live, the lab and people files (METRICS_SPEC peer groups)
    # the value model's GAR over exactly each Lab line's matches (window, scope and the person's frame), so a national
    # team line carries its own matches' value and never the club figure
    lab_value = _step("value by Lab window", lambda: lab_value_windows((value or {}).get("_row_gar"),
                                                                       (value or {}).get("_row_extra"))) if value else None
    _step("value fields", lambda: value_fields.apply(DATA_DIR, roles_before, (value or {}).get("_prev_lines"),
                                                     (value or {}).get("_prev_sid"), lab_value=lab_value))
    # progression (round 6): every person's seasons, club and international, on the role group's deep set, and the
    # peers' quantiles (data/progression_ref.json); after the value fields so the Lab lines carry GAR/90
    from oddsmarkets.football.analytics import progression as football_progression
    _step("progression", lambda: football_progression.apply(DATA_DIR))
    LAST_UNIFIED = None

    # Keep entries for competitions not rebuilt this run, so --only never drops
    # the rest of the site from the index.
    for c in competitions:
        prev[c["slug"]] = {k: v for k, v in c.items() if not k.startswith("_")}
    for slug, fields in unified.items():
        if slug in prev:
            prev[slug].pop("winner", None)      # set again below only while the competition is between editions
            prev[slug].update(fields)
    cal = _read_json(CALIBRATION_PATH, None)
    if isinstance(cal, dict) and cal.get("ok"):
        _step("calibration", lambda: _write(DATA_DIR, "calibration.json", cal))
    # Which clubs have a crest file: the front end draws a monogram for any other id instead of requesting a 404.
    _step("crest list", lambda: _write(DATA_DIR, "crests.json", {"ids": sorted(
        int(f.stem) for f in CRESTS_DIR.glob("*.png") if f.stem.isdigit()) if crests_enabled() else []}))
    ordered = [prev[s] for s in list(LEAGUES) + [LIGA_ARGENTINA_SLUG] + list(CUPS) if s in prev]
    _write(DATA_DIR, "competitions.json", {"competitions": ordered, "updated_at": _now()})

    n_built = sum(1 for c in competitions if c.get("ok"))
    logger.info("Built %d/%d competitions", n_built, len(competitions))
    if not args.no_market:
        watched = [c["slug"] for c in competitions if c.get("ok") and (c["slug"] in LEAGUES or c["slug"] in MARKET_WATCH_CUPS)]
        _step("market freshness", lambda: report_market_freshness(market_freshness(DATA_DIR, watched)))
    return 0 if n_built else 1


if __name__ == "__main__":
    raise SystemExit(main())
