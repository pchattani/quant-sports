"""
Reading a Sofascore store into simulator inputs.

The store is the single source of truth for the Liga dashboard. Unlike the World Cup
build, which pulled fixtures and standings from football-data.org and used Sofascore
only for advanced stats, the store already carries every match — including scheduled
ones — with teams, scores, status and round. Standings and remaining fixtures are
therefore derivable from it, which removes an entire API dependency, its key, and the
associated alias table.

The one thing the World Cup store does not record is a per-match date, which the
Dixon-Coles time decay needs. The Liga fetcher adds it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from oddsmarkets.football.competitions.liga.config import (
    APERTURA,
    CLAUSURA,
    DEFAULT_CONFIG,
    FALLBACK_ZONES_2026,
    LigaConfig,
    ZONES,
)
from oddsmarkets.football.competitions.liga.season_state import (
    LigaMatch,
    SeasonState,
    TorneoState,
)
from oddsmarkets.football.sources.teams import normalize_team_name

logger = logging.getLogger(__name__)

# Sofascore status strings that mean the match is over.
FINISHED_STATUSES = {"ended", "afterpenalties", "afterextratime", "ap", "aet", "finished"}
LIVE_STATUSES = {"inprogress", "live", "halftime", "firsthalf", "secondhalf"}

EMPTY_STORE: dict[str, Any] = {
    "matches": {},
    "lineups": {},
    "shots": {},
    "momentum": {},
    "incidents": {},
    "players": {},
    "team_stats": {},
    "lineup_extras": {},
    "zones": {},
    "meta": {},
}


def load_store(path: Path) -> dict[str, Any]:
    """Load a store, returning an empty one rather than raising if it is absent."""
    if not path.exists():
        logger.warning("No Liga store at %s — starting empty", path)
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in EMPTY_STORE.items()}
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Liga store at %s is unreadable (%s) — starting empty", path, exc)
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in EMPTY_STORE.items()}
    for key, default in EMPTY_STORE.items():
        store.setdefault(key, dict(default) if isinstance(default, dict) else default)
    return store


def save_store(store: dict[str, Any], path: Path) -> None:
    store["meta"] = dict(store.get("meta") or {})
    store["meta"]["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")


def store_age_hours(store: dict[str, Any]) -> float | None:
    stamp = (store.get("meta") or {}).get("updated_at")
    if not stamp:
        return None
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0


def _parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def _status_of(raw: str) -> str:
    low = (raw or "").strip().lower().replace(" ", "")
    if low in FINISHED_STATUSES:
        return "finished"
    if low in LIVE_STATUSES:
        return "live"
    return "scheduled"


def _derive_zone(
    zones: dict[str, list[str]] | None, home: str, away: str
) -> str | None:
    """
    A fixture's zone, from squad membership.

    None means interzone — the two clubs sit in different zones — which is a real
    category rather than missing data.
    """
    if not zones:
        return None
    home_zone = next((z for z, members in zones.items() if home in members), None)
    away_zone = next((z for z, members in zones.items() if away in members), None)
    return home_zone if home_zone and home_zone == away_zone else None


def iter_matches(
    store: dict[str, Any],
    torneo: str | None = None,
    zones: dict[str, list[str]] | None = None,
) -> Iterable[LigaMatch]:
    """
    Every match in the store, optionally filtered to one tournament.

    `zones` backfills the per-match zone when the store does not carry one. Stores
    fetched before the fetcher started deriving it have `zone: null` throughout, and
    anything filtering fixtures by zone would silently come back empty — so the zone
    is recomputed here rather than trusted.
    """
    for gid, raw in (store.get("matches") or {}).items():
        if torneo is not None and raw.get("torneo") != torneo:
            continue
        home = normalize_team_name(str(raw.get("home", "")), "liga_argentina")
        away = normalize_team_name(str(raw.get("away", "")), "liga_argentina")
        if not home or not away:
            continue
        status = _status_of(str(raw.get("status", "")))
        hs, as_ = raw.get("hs"), raw.get("as")
        yield LigaMatch(
            game_id=str(gid),
            home_team=home,
            away_team=away,
            home_goals=int(hs) if hs is not None else None,
            away_goals=int(as_) if as_ is not None else None,
            date=_parse_date(raw.get("date")),
            round_name=str(raw["round"]) if raw.get("round") is not None else None,
            torneo=raw.get("torneo"),
            zone=raw.get("zone") or _derive_zone(zones, home, away),
            status=status,
        )


def zones_from_store(
    store: dict[str, Any], torneo: str, cfg: LigaConfig | None = None
) -> dict[str, list[str]]:
    """
    Zone membership for a tournament.

    Read from the store where possible — zones are redrawn every season, so hardcoding
    them guarantees they go stale. The fallback exists only so the pipeline can be
    exercised offline and is logged loudly when used.
    """
    cfg = cfg or DEFAULT_CONFIG
    stored = (store.get("zones") or {}).get(torneo)
    if stored:
        out = {
            z: [normalize_team_name(t, "liga_argentina") for t in stored.get(z, [])]
            for z in ZONES
        }
        if all(len(out[z]) == cfg.teams_per_zone for z in ZONES):
            return out
        logger.warning(
            "Store zones for %s are the wrong size (%s) — falling back",
            torneo, {z: len(out[z]) for z in ZONES},
        )
    logger.warning(
        "No usable zone membership in store for %s — using the offline fallback, "
        "which will be wrong once the zones are redrawn.", torneo,
    )
    return {z: list(FALLBACK_ZONES_2026[z]) for z in ZONES}


def torneo_from_store(
    store: dict[str, Any],
    torneo: str,
    cfg: LigaConfig | None = None,
    champion: str | None = None,
) -> TorneoState:
    cfg = cfg or DEFAULT_CONFIG
    zones = zones_from_store(store, torneo, cfg)
    finished: list[LigaMatch] = []
    remaining: list[LigaMatch] = []
    playoff_results: dict[str, str] = {}

    playoffs_by_round: dict[str, list[LigaMatch]] = {}
    for match in iter_matches(store, torneo, zones=zones):
        if match.is_finished:
            finished.append(match)
            if match.is_playoff:
                playoffs_by_round.setdefault(match.round_name or "", []).append(match)
        else:
            remaining.append(match)

    # Playoff results are keyed by (round, slot) so a forced result cannot also fire
    # when the same two clubs meet in the league phase. The slot is the match's
    # position within its round; the store records it explicitly when known, and
    # otherwise it is inferred from kickoff order, which matches how brackets are
    # scheduled and listed.
    for round_name, played in playoffs_by_round.items():
        raw_matches = store.get("matches") or {}
        ordered = sorted(
            played,
            key=lambda m: (
                raw_matches.get(m.game_id, {}).get("slot")
                if raw_matches.get(m.game_id, {}).get("slot") is not None
                else 1_000_000,
                m.date or datetime.max.replace(tzinfo=timezone.utc),
                m.game_id,
            ),
        )
        for slot, match in enumerate(ordered):
            explicit = (store.get("matches") or {}).get(match.game_id, {}).get("slot")
            slot_idx = int(explicit) if explicit is not None else slot
            if match.home_goals > match.away_goals:
                playoff_results[f"{round_name}:{slot_idx}"] = match.home_team
            elif match.away_goals > match.home_goals:
                playoff_results[f"{round_name}:{slot_idx}"] = match.away_team
            # A drawn single-leg tie was decided on penalties; the store records the
            # winner via `winner` when the scoreline alone cannot say.
            elif (w := (store.get("matches") or {}).get(match.game_id, {}).get("winner")):
                playoff_results[f"{round_name}:{slot_idx}"] = normalize_team_name(
                    str(w), "liga_argentina"
                )

    return TorneoState(
        key=torneo, zones=zones, finished=finished, remaining=remaining,
        playoff_results=playoff_results, champion=champion, cfg=cfg,
    )


def season_state_from_store(
    store: dict[str, Any],
    cfg: LigaConfig | None = None,
    promedios_prior: dict[str, tuple[int, int]] | None = None,
    apertura_champion: str | None = None,
    clausura_champion: str | None = None,
) -> SeasonState:
    """Assemble a full SeasonState from a store plus committed historical inputs."""
    cfg = cfg or DEFAULT_CONFIG
    return SeasonState(
        year=cfg.season_year,
        apertura=torneo_from_store(store, APERTURA, cfg, champion=apertura_champion),
        clausura=torneo_from_store(store, CLAUSURA, cfg, champion=clausura_champion),
        promedios_prior=promedios_prior or {},
        cfg=cfg,
    )


def team_xg_map(
    store: dict[str, Any], registry: str = "liga_argentina"
) -> dict[str, tuple[float, float]]:
    """
    Per-match team xG, keyed by game_id.

    Keyed by match rather than by team pair. The World Cup code keys its equivalent by
    frozenset({home, away}), justified because teams meet at most once in a World Cup —
    an assumption that fails immediately in a league, where clubs meet in both
    tournaments and in the playoffs.
    """
    out: dict[str, tuple[float, float]] = {}
    lineups = store.get("lineups") or {}
    matches = store.get("matches") or {}
    for gid, players in lineups.items():
        meta = matches.get(gid) or {}
        home = normalize_team_name(str(meta.get("home", "")), registry)
        if not home or not isinstance(players, dict):
            continue
        home_xg = away_xg = 0.0
        seen = False
        for entry in players.values():
            if not isinstance(entry, dict):
                continue
            stats = entry.get("s") or {}
            xg = stats.get("expectedGoals")
            if xg is None:
                continue
            seen = True
            team = normalize_team_name(str(entry.get("t", "")), registry)
            if team == home:
                home_xg += float(xg)
            else:
                away_xg += float(xg)
        if seen:
            out[str(gid)] = (round(home_xg, 3), round(away_xg, 3))
    return out


def training_frame(store: dict[str, Any], include_xg: bool = True):
    """
    Dixon-Coles training frame from finished matches in the store.

    Returns the columns `fit` expects: home_team, away_team, home_goals, away_goals,
    match_date, weight, and optionally home_xg/away_xg. Rows carrying xG use the
    continuous likelihood; the rest fall back to the integer Poisson path, so partial
    xG coverage is fine by construction.
    """
    import pandas as pd

    xg = team_xg_map(store) if include_xg else {}
    rows = []
    for match in iter_matches(store):
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


def aggregate_players(store: dict[str, Any], registry: str = "liga_argentina") -> list[dict]:
    """Per-player season totals, rates and per-90s; see `analytics.players`."""
    from oddsmarkets.football.analytics.players import aggregate_players as _aggregate

    return _aggregate(store, registry=registry)


def shots_by_player(store: dict[str, Any], registry: str = "liga_argentina") -> dict[str, dict]:
    """Per-player shot lists with pitch coordinates, for shot maps. Keyed by player name."""
    by_player: dict[str, dict] = {}
    matches = store.get("matches") or {}
    for gid, shots in (store.get("shots") or {}).items():
        meta = matches.get(str(gid), {})
        label = (
            f"{meta.get('home', '?')} {meta.get('hs', '')}–"
            f"{meta.get('as', '')} {meta.get('away', '?')}"
        )
        if not isinstance(shots, list):
            continue
        for s in shots:
            if not isinstance(s, dict):
                continue
            name = s.get("player_name")
            if not name:
                continue
            entry = by_player.setdefault(name, {
                "team": normalize_team_name(str(s.get("team", "")), registry),
                "player_id": str(s["player_id"]) if s.get("player_id") else None,
                "shots": [],
            })
            if entry.get("player_id") is None and s.get("player_id"):
                entry["player_id"] = str(s["player_id"])
            entry["shots"].append({
                "x": s.get("x"), "y": s.get("y"),
                "xg": s.get("xg"), "xgot": s.get("xgot"),
                "type": s.get("shot_type"), "body": s.get("body_part"),
                "situation": s.get("situation"),
                "time": s.get("time"), "match": label, "gid": str(gid),
            })
    return by_player


def match_details(
    store: dict[str, Any], limit_ratings: int = 30, registry: str = "liga_argentina"
) -> dict[str, dict]:
    """Per-match momentum, incidents, shots, lineups, team stats and ratings; see `analytics.matches`."""
    from oddsmarkets.football.analytics.matches import match_details as _details

    return _details(store, limit_ratings=limit_ratings, registry=registry)


def player_match_logs(store: dict[str, Any], registry: str = "liga_argentina") -> dict[str, dict]:
    from oddsmarkets.football.analytics.players import player_match_logs as _logs

    return _logs(store, registry=registry)


def team_match_stats(store: dict[str, Any], registry: str = "liga_argentina") -> dict[str, list[dict]]:
    from oddsmarkets.football.analytics.teams import team_match_stats as _stats

    return _stats(store, registry=registry, xg_by_match=team_xg_map(store, registry=registry))


def empirical_calibration(df) -> dict[str, float]:
    """
    League scoring parameters measured from the training frame, replacing the
    World Cup constants baked into EnsembleModel.

    `draw_rate` splits Elo's non-home-win mass; `lam_scale` is twice the mean goals
    per team per match, so that at an even Elo the fallback path reproduces the
    league's actual scoring rate.
    """
    if df is None or len(df) == 0:
        return {"draw_rate": 0.25, "lam_scale": 2.6, "mean_goals": 1.3, "home_win_rate": 0.45}
    draws = float((df["home_goals"] == df["away_goals"]).mean())
    mean_goals = float((df["home_goals"].mean() + df["away_goals"].mean()) / 2.0)
    home_wins = float((df["home_goals"] > df["away_goals"]).mean())
    return {
        "draw_rate": round(draws, 4),
        "lam_scale": round(2.0 * mean_goals, 4),
        "mean_goals": round(mean_goals, 4),
        "home_win_rate": round(home_wins, 4),
    }
