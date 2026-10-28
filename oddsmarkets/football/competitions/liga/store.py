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

# Argentina's store sits with every other competition's since round 6 (28 October 2026):
# docs/site/data/liga-argentina/store.json. The old standalone site's copy is read only when the new one does not
# exist yet (the first hour after the move, or an old checkout).
_ROOT = Path(__file__).resolve().parents[4]
STORE_PATH = _ROOT / "docs" / "site" / "data" / "liga-argentina" / "store.json"
LEGACY_STORE_PATH = _ROOT / "docs" / "liga" / "data" / "liga_store.json"


def store_path() -> Path:
    """Where to read Argentina's store from: the shared location, else the legacy one while it is the only copy."""
    return STORE_PATH if STORE_PATH.exists() or not LEGACY_STORE_PATH.exists() else LEGACY_STORE_PATH

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


# Fixtures past their kick-off that the store still calls not started. Sofascore sometimes re-lists a match under a
# new event id (a moved kick-off, a postponed tie, a friendly entered twice) and keeps the old id as "notstarted"
# for good; the fetcher's season list then rewrites it every hour and nothing ever closes it (18 Oct 2026: eight
# such fixtures in friendlies, the CAF Champions League and the Copa del Rey, kick-offs 11 Sep to 11 Oct).
STALE_FIXTURE_HOURS = 6
NOT_STARTED = {"notstarted", "not_started", "scheduled", ""}
SUPERSEDE_DAYS_NO_ROUND = 3          # a re-listing without a round must kick off within this many days of the old one


def overdue(raw: dict, now: datetime | None = None, hours: float = STALE_FIXTURE_HOURS) -> bool:
    """True for a fixture still "not started" more than `hours` after its kick-off."""
    if str(raw.get("status") or "").strip().lower().replace(" ", "") not in NOT_STARTED:
        return False
    d = _parse_date(raw.get("date"))
    now = now or datetime.now(timezone.utc)
    return d is not None and (now - d).total_seconds() > hours * 3600


def mark_superseded(store: dict[str, Any], now: datetime | None = None) -> list[tuple[str, str]]:
    """
    Close overdue fixtures that the store holds again under another id, in place: same season, same home and away
    sides, same stage and round, and the other copy played, live or still to come (a fixture without a round must
    be within SUPERSEDE_DAYS_NO_ROUND days); or the sides swapped, played or live within a day of the old kick-off. The old copy becomes status "canceled" with "superseded_by" (the id of
    the copy kept) and "status_was"; every reader already drops a cancelled copy of a pair that exists twice.
    An overdue fixture with no other copy is left as it is (overdue() lets a page call it "result missing").
    Returns [(old id, kept id)]. Idempotent; the fetcher runs it after every fixture refresh and load_store on load.
    """
    matches = store.get("matches") or {}
    now = now or datetime.now(timezone.utc)
    stale = [(g, m) for g, m in matches.items() if isinstance(m, dict) and not m.get("superseded_by") and overdue(m, now)]
    if not stale:
        return []
    by_pair: dict[tuple, list[tuple[str, dict]]] = {}
    for g, m in matches.items():
        if isinstance(m, dict) and not m.get("superseded_by"):
            by_pair.setdefault((m.get("season_id"), m.get("home"), m.get("away")), []).append((g, m))
    out = []
    for gid, m in stale:
        d0 = _parse_date(m.get("date"))
        best = None
        same = [(g2, m2, False) for g2, m2 in by_pair.get((m.get("season_id"), m.get("home"), m.get("away")), [])]
        swapped = [(g2, m2, True) for g2, m2 in by_pair.get((m.get("season_id"), m.get("away"), m.get("home")), [])]
        for g2, m2, flipped in same + swapped:
            if g2 == gid or m2.get("stage") != m.get("stage") or m2.get("round") != m.get("round"):
                continue
            st = str(m2.get("status") or "").strip().lower().replace(" ", "")
            d2 = _parse_date(m2.get("date"))
            if flipped:
                # the same match listed with the sides the other way round (a neutral or swapped venue): played or
                # live, within a day; never a two-legged tie's other leg
                if not (st in FINISHED_STATUSES or st in LIVE_STATUSES) or d0 is None or d2 is None                         or abs((d2 - d0).total_seconds()) > 86400:
                    continue
            elif st in FINISHED_STATUSES or st in LIVE_STATUSES:
                pass
            elif st in NOT_STARTED and d2 is not None and d0 is not None and d2 > d0 and not overdue(m2, now):
                pass                                      # rescheduled, still to come
            else:
                continue
            if m.get("round") is None and (d0 is None or d2 is None or abs((d2 - d0).total_seconds()) > SUPERSEDE_DAYS_NO_ROUND * 86400):
                continue
            if best is None or (d2 and best[1] and abs((d2 - d0).total_seconds()) < abs((best[1] - d0).total_seconds())):
                best = (g2, d2)
        if best is not None:
            m["status_was"] = m.get("status")
            m["status"] = "canceled"
            m["superseded_by"] = str(best[0])
            out.append((str(gid), str(best[0])))
    if out:
        logger.info("closed %d overdue fixtures held again under another id: %s", len(out), out)
    return out


def load_store(path: Path) -> dict[str, Any]:
    """Load a store, returning an empty one rather than raising if it is absent. Overdue fixtures held again under
    another id are closed on load (mark_superseded), so every reader sees them cancelled."""
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
    try:
        mark_superseded(store)
    except Exception as exc:  # noqa: BLE001 - a malformed store must still load
        logger.warning("store at %s: stale-fixture check failed (%s)", path, exc)
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
        if raw.get("superseded_by"):
            # The old copy of a re-listed fixture (mark_superseded): the league and cup readers drop it too.
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
            elif isinstance(pens := (store.get("matches") or {}).get(match.game_id, {}).get("pens"), (list, tuple)) \
                    and len(pens) == 2 and pens[0] != pens[1]:
                playoff_results[f"{round_name}:{slot_idx}"] = match.home_team if pens[0] > pens[1] else match.away_team

    remaining = drop_dead_fixtures(finished, remaining)
    if champion is None:
        champion = champion_from_final(store, finished)

    return TorneoState(
        key=torneo, zones=zones, finished=finished, remaining=remaining,
        playoff_results=playoff_results, champion=champion, cfg=cfg,
    )


def _pair_round(m: LigaMatch) -> tuple:
    return (frozenset((m.home_team, m.away_team)), str(m.round_name))


def drop_dead_fixtures(finished: list[LigaMatch], remaining: list[LigaMatch]) -> list[LigaMatch]:
    """
    The fixtures still to play, without the dead ones.

    Sofascore re-lists a postponed match under a new event id and keeps the old one as "postponed" for good
    (2026 Apertura: eight round-6, 7 and 9 fixtures, all replayed under new ids; Clausura round 11, Sarmiento v
    River Plate, listed three times). Read as still to play, they kept the Apertura "incomplete", so the Tabla
    Anual, the promedios and every berth were computed without its 240 matches (October 2026). A fixture is dead
    when the same two clubs already played in the same round of the same tournament, or when the tournament's
    final has been played (nothing of its zone phase can still count).
    """
    played = {_pair_round(m) for m in finished}
    final_done = any(m.round_name == "final" for m in finished)
    keep = []
    for m in remaining:
        if _pair_round(m) in played:
            continue
        if final_done:
            continue
        keep.append(m)
    return keep


def champion_from_final(store: dict[str, Any], finished: list[LigaMatch]) -> str | None:
    """The winner of a played final: the score, else the stored shoot-out winner or penalties."""
    raw_matches = store.get("matches") or {}
    for m in finished:
        if m.round_name != "final":
            continue
        if m.home_goals > m.away_goals:
            return m.home_team
        if m.away_goals > m.home_goals:
            return m.away_team
        raw = raw_matches.get(m.game_id) or {}
        if raw.get("winner"):
            return normalize_team_name(str(raw["winner"]), "liga_argentina")
        pens = raw.get("pens")
        if isinstance(pens, (list, tuple)) and len(pens) == 2 and pens[0] != pens[1]:
            return m.home_team if pens[0] > pens[1] else m.away_team
    return None


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
