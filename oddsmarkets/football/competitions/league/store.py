"""
Reading a league's Sofascore store into simulator inputs.

The store has the same shape as the Argentine one — `matches`, `lineups`, `shots`,
`momentum`, `incidents`, `meta` — plus `conferences` for MLS, so everything below
match level (per-player aggregation, shot maps, match detail, xG per match, the
scoring calibration) is the Argentine reader called with this league's name
registry. Only the season assembly is new: one table, one season id, no zones.

The store carries two seasons. Only matches of `meta.season_id` are the live
season; the previous one exists to train the model and never reaches the table.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from oddsmarkets.football.competitions.league.config import LeagueConfig
from oddsmarkets.football.competitions.league.season_state import LeagueMatch, LeagueState
from oddsmarkets.football.competitions.liga import store as _liga
from oddsmarkets.football.sources.teams import normalize_team_name

logger = logging.getLogger(__name__)

# Re-exported so callers have one import for the store layer.
load_store = _liga.load_store
save_store = _liga.save_store
store_age_hours = _liga.store_age_hours
empirical_calibration = _liga.empirical_calibration

# Sofascore `status.type` values plus the description strings the Argentine
# fetcher stores, so either shape of store reads the same way.
_FINISHED = {"finished"} | _liga.FINISHED_STATUSES
_LIVE = {"inprogress"} | _liga.LIVE_STATUSES
_POSTPONED = {"postponed", "canceled", "cancelled", "interrupted", "suspended", "delayed"}


def _status_of(raw: object) -> str:
    low = str(raw or "").strip().lower().replace(" ", "")
    if low in _FINISHED:
        return "finished"
    if low in _LIVE:
        return "live"
    return "scheduled"


def iter_matches(store: dict[str, Any], cfg: LeagueConfig,
                 season_id: int | None = None) -> Iterable[LeagueMatch]:
    """Every match in the store, optionally restricted to one season id."""
    for gid, raw in (store.get("matches") or {}).items():
        if season_id is not None and raw.get("season_id") != season_id:
            continue
        home = normalize_team_name(str(raw.get("home", "")), cfg.registry)
        away = normalize_team_name(str(raw.get("away", "")), cfg.registry)
        if not home or not away:
            continue
        hs, as_ = raw.get("hs"), raw.get("as")
        winner = raw.get("winner")
        yield LeagueMatch(
            game_id=str(gid),
            home_team=home,
            away_team=away,
            home_goals=int(hs) if hs is not None else None,
            away_goals=int(as_) if as_ is not None else None,
            date=_liga._parse_date(raw.get("date")),
            round_name=str(raw["round"]) if raw.get("round") is not None else None,
            stage="playoff" if raw.get("stage") == "playoff" else "league",
            status=_status_of(raw.get("status")),
            winner=normalize_team_name(str(winner), cfg.registry) if winner else None,
            postponed=str(raw.get("status") or "").strip().lower() in _POSTPONED,
        )


def current_season_id(store: dict[str, Any]) -> int | None:
    sid = (store.get("meta") or {}).get("season_id")
    if sid is not None:
        return int(sid)
    # A store written before the fetcher recorded it: take the newest id present.
    ids = [m.get("season_id") for m in (store.get("matches") or {}).values() if m.get("season_id")]
    return max(int(i) for i in ids) if ids else None


def conferences_from_store(store: dict[str, Any], cfg: LeagueConfig,
                           fallback: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """Conference membership, normalised; empty for a league without conferences."""
    if not cfg.conferences:
        return {}
    raw = store.get("conferences") or fallback or {}
    out: dict[str, list[str]] = {}
    for conf in cfg.conferences:
        members = raw.get(conf) or []
        out[conf] = [normalize_team_name(str(t), cfg.registry) for t in members]
    sizes = {c: len(m) for c, m in out.items()}
    if any(n != cfg.teams_per_conference for n in sizes.values()):
        logger.warning("%s: conference sizes %s do not match config (%d each)",
                       cfg.slug, sizes, cfg.teams_per_conference)
    return out


def league_state_from_store(
    store: dict[str, Any],
    cfg: LeagueConfig,
    previous_rank: dict[str, int] | None = None,
    conferences: dict[str, list[str]] | None = None,
    teams: list[str] | None = None,
) -> LeagueState:
    """
    Assemble the live season from the store.

    The team list comes from the season's own fixture list — every club appears in
    it from day one, played or not — with the discovery file's list as a fallback
    for a store that has no fixtures yet.
    """
    season_id = current_season_id(store)
    matches = list(iter_matches(store, cfg, season_id=season_id))
    # A postponed fixture stays in the feed next to its rescheduled copy. Keep the
    # copy; otherwise the pair is simulated twice and one club's season is a game
    # too long.
    pairs: dict[tuple[str, str], int] = {}
    for m in matches:
        pairs[(m.home_team, m.away_team)] = pairs.get((m.home_team, m.away_team), 0) + 1
    finished: list[LeagueMatch] = []
    remaining: list[LeagueMatch] = []
    seen: dict[str, None] = {}
    for m in matches:
        seen.setdefault(m.home_team)
        seen.setdefault(m.away_team)
        if m.postponed and pairs[(m.home_team, m.away_team)] > 1:
            continue
        (finished if m.is_finished else remaining).append(m)

    conf = conferences_from_store(store, cfg, fallback=conferences)
    all_teams = list(seen) or [normalize_team_name(t, cfg.registry) for t in (teams or [])]
    for members in conf.values():
        for t in members:
            if t not in all_teams:
                all_teams.append(t)
    if len(all_teams) != cfg.n_teams:
        logger.warning("%s: %d teams in the store, config expects %d",
                       cfg.slug, len(all_teams), cfg.n_teams)

    prev = {
        normalize_team_name(str(t), cfg.registry): int(r)
        for t, r in (previous_rank or {}).items()
    }
    return LeagueState(
        cfg=cfg, teams=all_teams, finished=finished, remaining=remaining,
        conferences=conf, previous_rank=prev,
        season_name=(store.get("meta") or {}).get("season_name"),
        team_ids=team_ids_from_store(store, cfg),
        playoff_results=playoff_results([m for m in finished if m.is_playoff], cfg),
    )


def team_ids_from_store(store: dict[str, Any], cfg: LeagueConfig) -> dict[str, int]:
    """Sofascore team ids by canonical name, from whichever matches carry them."""
    out: dict[str, int] = {}
    for raw in (store.get("matches") or {}).values():
        for side, key in (("home", "home_id"), ("away", "away_id")):
            tid = raw.get(key)
            if tid:
                out.setdefault(normalize_team_name(str(raw.get(side, "")), cfg.registry), int(tid))
    return out


def playoff_results(played: list[LeagueMatch], cfg: LeagueConfig) -> dict[frozenset, str]:
    """
    Decided playoff ties, keyed by the pair of clubs.

    A single match decides on the scoreline, or on `winner` when it was drawn and
    settled on penalties. A best-of-three (MLS Round One) is decided by the first
    club to two wins; a series at 1-1 is undecided and left to the simulation.
    """
    wins: dict[frozenset, dict[str, int]] = {}
    for m in played:
        if not m.is_finished:
            continue
        pair = frozenset((m.home_team, m.away_team))
        if m.home_goals > m.away_goals:
            w = m.home_team
        elif m.away_goals > m.home_goals:
            w = m.away_team
        else:
            w = m.winner
        if not w:
            continue
        wins.setdefault(pair, {})[w] = wins.setdefault(pair, {}).get(w, 0) + 1

    need = (cfg.playoff.round_one_best_of // 2 + 1) if cfg.playoff else 1
    out: dict[frozenset, str] = {}
    for pair, tally in wins.items():
        n_games = sum(tally.values())
        top, top_wins = max(tally.items(), key=lambda kv: kv[1])
        # One game decides a single-match round outright. A best-of-three needs
        # two wins — and a tie can only be one of the two shapes, so if more than
        # one game was played it was the series.
        if n_games == 1 or top_wins >= need:
            out[pair] = top
    return out


def training_frame(store: dict[str, Any], cfg: LeagueConfig, include_xg: bool = True):
    """
    Dixon-Coles training frame from every finished match in the store, both seasons.

    Playoff matches are real matches and are kept; the model does not care what
    was at stake. Rows carrying xG use the continuous likelihood and the rest fall
    back to the integer Poisson path, so partial xG coverage is fine by design.
    """
    import pandas as pd

    xg = _liga.team_xg_map(store, registry=cfg.registry) if include_xg else {}
    rows = []
    for match in iter_matches(store, cfg):
        if not match.is_finished or match.date is None:
            continue
        row = {
            "game_id": match.game_id,
            "home_team": match.home_team,
            "away_team": match.away_team,
            "home_goals": int(match.home_goals),
            "away_goals": int(match.away_goals),
            "match_date": match.date,
            "weight": 1.0,
        }
        if match.game_id in xg:
            row["home_xg"], row["away_xg"] = xg[match.game_id]
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=[
            "game_id", "home_team", "away_team", "home_goals",
            "away_goals", "match_date", "weight",
        ])
    df = pd.DataFrame(rows)
    df["match_date"] = pd.to_datetime(df["match_date"], utc=True)
    return df.sort_values("match_date").reset_index(drop=True)


def team_xg_map(store: dict[str, Any], cfg: LeagueConfig) -> dict[str, tuple[float, float]]:
    return _liga.team_xg_map(store, registry=cfg.registry)


def aggregate_players(store: dict[str, Any], cfg: LeagueConfig) -> list[dict]:
    return _liga.aggregate_players(store, registry=cfg.registry)


def shots_by_player(store: dict[str, Any], cfg: LeagueConfig) -> dict[str, dict]:
    return _liga.shots_by_player(store, registry=cfg.registry)


def match_details(store: dict[str, Any], cfg: LeagueConfig, limit_ratings: int = 30) -> dict[str, dict]:
    return _liga.match_details(store, limit_ratings=limit_ratings, registry=cfg.registry)


def player_match_logs(store: dict[str, Any], cfg: LeagueConfig) -> dict[str, dict]:
    return _liga.player_match_logs(store, registry=cfg.registry)


def team_match_stats(store: dict[str, Any], cfg: LeagueConfig) -> dict[str, list[dict]]:
    return _liga.team_match_stats(store, registry=cfg.registry)


def store_signature(store: dict[str, Any]) -> tuple:
    """
    What a store refresh is worth committing for.

    Finished results, fixture dates and detail coverage change the forecast; a
    score ticking over during a live match does not survive to the next build
    anyway. Saving only when this changes keeps the hourly commits to match days'
    real changes rather than every scoreline.
    """
    matches = store.get("matches") or {}
    finished = tuple(sorted(
        (gid, m.get("hs"), m.get("as"), m.get("winner"))
        for gid, m in matches.items() if m.get("status") == "finished"
    ))
    dates = tuple(sorted((gid, m.get("date"), m.get("status") == "finished") for gid, m in matches.items()))
    return (
        len(matches), finished, dates, len(store.get("lineups") or {}), len(store.get("team_stats") or {}),
        (store.get("meta") or {}).get("season_id"),
    )


def last_finished_date(state: LeagueState) -> datetime | None:
    dates = [m.date for m in state.finished if m.date]
    return max(dates) if dates else None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
