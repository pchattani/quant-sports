#!/usr/bin/env python
"""
Incremental Sofascore fetch for the Argentine Liga Profesional.

Mirrors scripts/fetch_sofascore.py, retargeted from the World Cup (tournament 16) to
Liga Profesional (tournament 155) and generalised over seasons, since a calendar year
holds two tournaments rather than one.

Two differences from the World Cup fetcher that matter:

  - Per-match `date`, `torneo` and `season_id` are recorded. The World Cup store omits
    the date because its model treats the whole tournament as one instant; a league
    spans a year, so Dixon-Coles time decay needs it.
  - League rounds are plain numbers, so the tournament_type/tournament_stage handling
    the World Cup needs disappears. Playoff rounds are still slugged, and their slugs
    are mapped onto r16/qf/sf/final — without that, `LigaMatch.is_playoff` never fires
    and playoff results are counted as league-phase results.
  - Each fixture's zone is derived from squad membership rather than carried forward,
    since nothing upstream supplies one. Interzone fixtures correctly have no zone.

Fixtures come from the season-events endpoint and per-match detail (lineups with
player metadata, the team-stat sheet, shots, momentum, incidents) from the direct
calls in `sources/sofascore.py`, the same route every other competition uses,
under one call budget per run. datafc is no longer involved: its client
fingerprint started drawing a 403 from Sofascore while the direct route did not.

RUN THIS LOCALLY. Sofascore blocks datacenter IPs, so the scheduled CI build cannot
reach it; scripts/refresh_sofascore_all.ps1 runs this from a residential connection
and commits the store, which CI then hydrates. Every network call degrades to
last-good data rather than failing the build.

    python scripts/fetch_sofascore_liga.py                      # incremental update
    python scripts/fetch_sofascore_liga.py --backfill           # a larger budget
    python scripts/fetch_sofascore_liga.py --refresh-detail     # upgrade older detail too
    python scripts/fetch_sofascore_liga.py --probe              # connectivity check only
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.liga.config import (  # noqa: E402
    APERTURA,
    CLAUSURA,
    SOFASCORE_TOURNAMENT_ID,
)
from oddsmarkets.football.competitions.liga.store import (  # noqa: E402
    EMPTY_STORE,
    load_store,
    save_store,
)
from oddsmarkets.football.sources import sofascore  # noqa: E402
from oddsmarkets.football.sources.teams import normalize_team_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch-liga")

STORE_PATH = ROOT / "docs" / "liga" / "data" / "liga_store.json"
SEASONS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data" / "seasons.json"

# Detail calls per run (five per match): twenty matches by default, paced at about
# a call a second. Sofascore has challenged this IP after bursts of well under a
# thousand calls in an hour, and the league fetcher shares the hour.
DEFAULT_BUDGET = 100
BACKFILL_BUDGET = 1000
DETAIL_PAUSE_S = 1.0
MAX_CONSECUTIVE_FAILURES = 3
# Sofascore's standings for the season (the zones of both tournaments, the Tabla Anual and the promedios): one
# call from the run's own budget, at most every STANDINGS_EVERY_HOURS. The build checks our tables against it
# and takes the promedio history from it (liga/tables.py); nothing else depends on it.
STANDINGS_EVERY_HOURS = 6

FINISHED = {"ended", "afterpenalties", "afterextratime", "ap", "aet", "finished"}


def _canon(name: str) -> str:
    return normalize_team_name(str(name or ""), "liga_argentina")


def load_seasons() -> list[dict]:
    """
    Season ids to fetch, newest first.

    These are committed static configuration produced by discover_sofascore_liga.py.
    They cannot be discovered in CI, so an absent file is a hard stop with an
    actionable message rather than a silent empty run.
    """
    if not SEASONS_PATH.exists():
        logger.error(
            "No %s. Run scripts/discover_sofascore_liga.py from a residential "
            "connection and commit the result.", SEASONS_PATH,
        )
        return []
    try:
        payload = json.loads(SEASONS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read %s: %s", SEASONS_PATH, exc)
        return []
    return payload.get("seasons", [])


def load_zones(year: object) -> dict[str, dict[str, list[str]]]:
    """
    Zone membership per tournament for one year, as {torneo: {zone: [teams]}}.

    Discovered alongside the season ids and committed in the same file, because it
    comes from the same Sofascore standings call that CI cannot make.
    """
    if year is None or not SEASONS_PATH.exists():
        return {}
    try:
        payload = json.loads(SEASONS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read %s: %s", SEASONS_PATH, exc)
        return {}
    return (payload.get("zones") or {}).get(str(year)) or {}


def _first(row: pd.Series, names: tuple[str, ...]):
    for name in names:
        if name in row and pd.notna(row.get(name)):
            return row[name]
    return None


# Sofascore labels knockout rounds with a slug rather than a plain number. Mapping
# them onto our round keys is what makes `LigaMatch.is_playoff` fire — without it every
# playoff match is treated as a league-phase result and corrupts the zone standings.
PLAYOFF_SLUGS: dict[str, str] = {
    "round-of-16": "r16", "1-8": "r16", "octavos": "r16", "eighth-finals": "r16",
    "quarterfinals": "qf", "quarter-finals": "qf", "1-4": "qf", "cuartos": "qf",
    "semifinals": "sf", "semi-finals": "sf", "1-2": "sf", "semifinal": "sf",
    "final": "final",
}


def zone_of_fixture(store: dict, torneo: str | None, home: str, away: str) -> str | None:
    """
    The zone a fixture belongs to, from squad membership.

    Returns None for interzone fixtures — where the two clubs sit in different zones —
    which is correct rather than missing: those matches count toward both zone tables
    but belong to neither.
    """
    zones = (store.get("zones") or {}).get(torneo) or {}
    home_zone = next((z for z, members in zones.items() if home in members), None)
    away_zone = next((z for z, members in zones.items() if away in members), None)
    return home_zone if home_zone and home_zone == away_zone else None


def playoff_round(slug: object, name: object = None) -> str | None:
    """Map a Sofascore round slug (or name) onto r16/qf/sf/final, else None."""
    for raw in (slug, name):
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        # Normalise separators together: Sofascore uses "round-of-16", "Round of 16"
        # and the fractional "1/8" and "1/4" forms interchangeably across competitions.
        key = re.sub(r"[\s_/]+", "-", str(raw).strip().lower())
        if key in PLAYOFF_SLUGS:
            return PLAYOFF_SLUGS[key]
        for needle, mapped in PLAYOFF_SLUGS.items():
            if needle in key:
                return mapped
    return None


def torneo_of_label(label: object) -> str | None:
    """
    The tournament a match belongs to, from its Sofascore `tournament` label.

    The label is spelled inconsistently across tournaments — "Liga Profesional de
    Fútbol, Apertura" against "Liga Profesional, Clausura" — so only the tournament
    word is matched, not the whole string.
    """
    text = str(label or "").lower()
    if APERTURA in text:
        return APERTURA
    if CLAUSURA in text:
        return CLAUSURA
    return None


def _shared_record(ev: dict, season_id: int) -> dict | None:
    try:
        out = sofascore.event_record(ev, _canon, season_id, round_slugs=PLAYOFF_SLUGS)
    except Exception:  # noqa: BLE001 - the Argentine columns still stand without it
        return None
    return out[1] if out else None


def refresh_standings(store: dict, season_id: int, budget=None, now: datetime | None = None) -> bool:
    """
    Sofascore's standings blocks for the season into store["standings"] ({season_id, at, blocks}), when the
    copy held is older than STANDINGS_EVERY_HOURS or from another season. One call, charged to the run's
    budget; a failed or empty answer keeps the previous copy. Returns whether a new copy was stored.
    """
    now = now or datetime.now(timezone.utc)
    held = store.get("standings") or {}
    try:
        at = datetime.strptime(str(held.get("at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        at = None
    if held.get("season_id") == int(season_id) and at is not None \
            and (now - at).total_seconds() < STANDINGS_EVERY_HOURS * 3600:
        return False
    if budget is not None and not budget.take():
        return False
    blocks = sofascore.standings_blocks(SOFASCORE_TOURNAMENT_ID, int(season_id))
    if not blocks:
        logger.warning("standings: nothing for season %s; the previous copy is kept", season_id)
        return False
    store["standings"] = {"season_id": int(season_id), "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "blocks": blocks}
    logger.info("standings: %s", [b.get("name") for b in blocks])
    return True


def fetch_season_matches(season_id: int, torneos: tuple[str, ...]) -> pd.DataFrame | None:
    """
    Every match of one season id, from the paginated season-events endpoint.

    From 2026 Sofascore serves both tournaments under a single season id, so the
    tournament is read from each match's own label rather than assumed from the
    season. `torneos` is what the season is expected to contain; when it names
    exactly one — the pre-2026 shape, one id per tournament — it also serves as the
    fallback for matches whose label cannot be read.

    Returns a frame with the columns `update_store` reads (game_id, the clubs and
    their ids, the scores, kickoff, status, round, `_torneo`, `_season_id`,
    `_ko_round`), or None when nothing arrived.
    """
    events = sofascore.season_events(SOFASCORE_TOURNAMENT_ID, int(season_id))
    if not events:
        logger.warning("Season %s returned no events", season_id)
        return None
    rows = []
    for ev in events:
        ri = ev.get("roundInfo") or {}
        label = (ev.get("tournament") or {}).get("name")
        torneo = torneo_of_label(label)
        if torneo is None and len(torneos) == 1:
            torneo = torneos[0]
        rows.append({
            "game_id": ev.get("id"),
            "home_team": (ev.get("homeTeam") or {}).get("name", ""),
            "away_team": (ev.get("awayTeam") or {}).get("name", ""),
            "home_team_id": (ev.get("homeTeam") or {}).get("id"),
            "away_team_id": (ev.get("awayTeam") or {}).get("id"),
            "home_score_display": (ev.get("homeScore") or {}).get("display"),
            "away_score_display": (ev.get("awayScore") or {}).get("display"),
            "start_timestamp": ev.get("startTimestamp"),
            "status": str((ev.get("status") or {}).get("type") or ""),
            "week": ri.get("round"),
            "tournament": label,
            "_torneo": torneo,
            "_season_id": int(season_id),
            "_ko_round": playoff_round(ri.get("slug"), ri.get("name")),
            # The record every other competition's store holds for this event (stage, shoot-out winner and
            # penalties, countries); update_store lays the Argentine fields over it.
            "_record": _shared_record(ev, int(season_id)),
        })
    allm = pd.DataFrame(rows).drop_duplicates(subset="game_id")

    counts = allm["_torneo"].value_counts(dropna=False).to_dict()
    logger.info("season %s: %d matches %s", season_id, len(allm), counts)
    unlabelled = int(allm["_torneo"].isna().sum())
    if unlabelled:
        logger.warning(
            "%d matches in season %s carry no readable tournament label — they will "
            "be excluded from both tables", unlabelled, season_id,
        )
    return allm


def update_store(store: dict, max_new: int = 40, budget=None, refresh: bool = False) -> dict:
    """
    Refresh match metadata for everything, then fetch detail for finished matches
    without it (and, with `refresh`, for those stored before the team-stat sheet
    was kept), newest first, under the call budget.
    """
    status = {"ok": False, "matches_seen": 0, "new_fetched": 0, "failures": 0}
    for key in ("matches", "lineups", "shots", "momentum", "incidents", "players", "team_stats", "lineup_extras"):
        store.setdefault(key, {})
    seasons = load_seasons()
    if not seasons:
        return status

    current = seasons[0]

    # Zone membership has to be in the store before any fixture is written, because
    # each fixture's zone is derived from squad membership. Nothing else populates it:
    # without this, store["zones"] stays empty and store.py silently falls back to
    # FALLBACK_ZONES_2026, which is a development aid and wrong once zones are redrawn.
    zones = load_zones(current.get("year"))
    if zones:
        store["zones"] = {**(store.get("zones") or {}), **zones}
        logger.info(
            "Zones: %s",
            {t: {z: len(m) for z, m in per.items()} for t, per in zones.items()},
        )
    else:
        logger.warning(
            "No zone membership in seasons.json for %s — fixtures will carry no zone "
            "and the build will fall back to hardcoded zones. Re-run "
            "scripts/discover_sofascore_liga.py.", current.get("year"),
        )

    # One season id can serve both tournaments (2026 onward), so fetch each distinct
    # id once and let the per-match label decide the tournament.
    by_season: dict[int, list[str]] = {}
    for torneo in (CLAUSURA, APERTURA):
        season_id = current.get(torneo)
        if not season_id:
            continue
        by_season.setdefault(int(season_id), []).append(torneo)

    frames = []
    for season_id, torneos in by_season.items():
        df = fetch_season_matches(season_id, tuple(torneos))
        if df is not None:
            frames.append(df)

    if not frames:
        logger.warning("No matches fetched — keeping the existing store")
        return status

    matches = pd.concat(frames, ignore_index=True)
    status["ok"] = True
    status["matches_seen"] = len(matches)

    for _, m in matches.iterrows():
        gid = str(m["game_id"])
        hs = _first(m, ("home_score_display", "home_score", "home_score_current"))
        as_ = _first(m, ("away_score_display", "away_score", "away_score_current"))
        ts = _first(m, ("start_timestamp", "startTimestamp", "start_time"))
        date = None
        if ts is not None:
            try:
                date = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except (ValueError, OSError, OverflowError):
                date = None

        prev = store["matches"].get(gid, {})
        home = _canon(m.get("home_team", ""))
        away = _canon(m.get("away_team", ""))
        # pandas turns a missing label into NaN, which is truthy and would survive the
        # fallback below and land in the store as a float.
        torneo = m.get("_torneo")
        if isinstance(torneo, float) and pd.isna(torneo):
            torneo = None
        torneo = torneo or prev.get("torneo")

        # Knockout rounds carry their slug-derived key; league rounds stay numeric.
        ko = m.get("_ko_round")
        if isinstance(ko, float) and pd.isna(ko):
            ko = None
        round_key = ko or (int(m["week"]) if pd.notna(m.get("week")) else None)

        shared = m.get("_record") if isinstance(m.get("_record"), dict) else {}
        store["matches"][gid] = {
            # The shared record first (stage, winner, pens, countries ...), the Argentine reading over it.
            **{k: v for k, v in shared.items() if v is not None},
            "home": home,
            "away": away,
            "round": round_key,
            "status": str(m.get("status", "")),
            "hs": int(hs) if hs is not None else None,
            "as": int(as_) if as_ is not None else None,
            # Keep a previously recorded date if this response omits one, so a
            # partial payload cannot erase information the store already has.
            "date": date or prev.get("date"),
            "torneo": torneo,
            "season_id": int(m["_season_id"]) if pd.notna(m.get("_season_id")) else None,
            # Derive the zone from squad membership rather than carrying forward a
            # value nothing ever sets. Interzone fixtures legitimately have no zone.
            "zone": zone_of_fixture(store, torneo, home, away) or prev.get("zone"),
            # Team ids drive crests on the combined site.
            "home_id": int(m["home_team_id"]) if pd.notna(m.get("home_team_id")) else prev.get("home_id"),
            "away_id": int(m["away_team_id"]) if pd.notna(m.get("away_team_id")) else prev.get("away_id"),
        }

    finished = matches[
        matches["status"].astype(str).str.lower().str.replace(" ", "").isin(FINISHED)
    ]
    ids = [str(x) for x in finished["game_id"]]
    by_date = lambda g: str((store["matches"].get(g) or {}).get("date") or "")  # noqa: E731
    fresh = sorted((g for g in ids if g not in store["lineups"]), key=by_date, reverse=True)
    stale = sorted((g for g in ids if refresh and g in store["lineups"] and g not in store["team_stats"]),
                   key=by_date, reverse=True)
    queue = (fresh + stale)[:max_new]
    if not queue:
        logger.info("Store up to date (%d finished matches)", len(finished))
        return status

    logger.info("Fetching detail for %d matches (%d without any, cap %d)", len(queue), len(fresh), max_new)
    misses = 0
    for gid in queue:
        if budget is not None and budget.left < sofascore.DETAIL_CALLS:
            logger.info("call budget spent — the rest waits for the next run")
            break
        meta = store["matches"].get(gid, {})
        try:
            ok = _fetch_match_detail(store, gid, meta, budget=budget)
        except sofascore.BudgetExhausted:
            break
        except Exception as exc:  # noqa: BLE001
            ok = False
            logger.debug("detail fetch failed for %s: %s", gid, exc)
        status["new_fetched" if ok else "failures"] += 1
        misses = 0 if ok else misses + 1
        if sofascore.is_blocked() or misses >= MAX_CONSECUTIVE_FAILURES:
            logger.warning("Sofascore is not answering detail calls — stopping detail for this run")
            break
        time.sleep(DETAIL_PAUSE_S)

    return status


def _fetch_match_detail(store: dict, gid: str, meta: dict, mdf=None, budget=None) -> bool:
    """
    One match's detail through the shared direct route: lineups with player
    metadata, the team-stat sheet, shots, momentum and incidents. Returns whether
    the lineups arrived — they carry the per-player stats every other payload
    builds on, so a match without them is a failure rather than a success with
    empty detail. `mdf` is accepted for the old call shape and ignored.
    """
    return sofascore.fetch_match_detail(store, gid, meta, _canon, budget=budget)


def probe() -> bool:
    seasons = load_seasons()
    if not seasons:
        return False
    season_id = seasons[0].get(CLAUSURA) or seasons[0].get(APERTURA)
    if not season_id:
        logger.error("No season id in seasons.json for the current year")
        return False
    return sofascore.probe(SOFASCORE_TOURNAMENT_ID, int(season_id))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill", action="store_true", help="a larger call budget")
    parser.add_argument("--budget", type=int, default=None, help="detail calls this run may make (5 per match)")
    parser.add_argument("--refresh-detail", action="store_true",
                        help="also re-fetch matches stored in the older, thinner detail format")
    parser.add_argument("--probe", action="store_true", help="connectivity check only")
    args = parser.parse_args()

    if args.probe:
        return 0 if probe() else 1

    # One call before anything else: a challenged IP answers 403 to everything.
    if not probe():
        if sofascore.is_blocked():
            logger.error("Sofascore is challenging this IP (HTTP 403) — nothing fetched this run")
            return 1
        logger.warning("probe failed — carrying on")

    store = load_store(STORE_PATH)
    if (store.get("meta") or {}).get("synthetic"):
        # The committed placeholder store is generated, and its fixtures carry their
        # own ids. Merging real matches into it would leave both sets in place, and
        # the fabricated ones would flow into the standings, the promedios and the
        # Dixon-Coles fit with nothing marking them as invented.
        logger.warning(
            "Store at %s is synthetic sample data — discarding it and starting fresh "
            "rather than merging real matches into fabricated ones.", STORE_PATH,
        )
        store = {k: (dict(v) if isinstance(v, dict) else v) for k, v in EMPTY_STORE.items()}
    before = len(store.get("lineups", {}))
    budget = sofascore.CallBudget(args.budget if args.budget is not None else (BACKFILL_BUDGET if args.backfill else DEFAULT_BUDGET))
    # Line-ups of matches about to start (docs/MODELS.md 2.6): one call each from the same budget, capped.
    n_pre = 0
    for gid, m in sofascore.prematch_queue(store)[:sofascore.PREMATCH_MAX]:
        if budget.left < 1 or sofascore.is_blocked():
            break
        try:
            n_pre += bool(sofascore.fetch_prematch(store, gid, {**m, "home": _canon(str(m.get("home") or "")),
                                                                "away": _canon(str(m.get("away") or ""))}, budget=budget))
        except sofascore.BudgetExhausted:
            break
    if n_pre:
        logger.info("pre-match line-ups: %d matches", n_pre)
    # The season's standings (zones, Tabla Anual, promedios), a few times a day, from the same budget.
    seasons = load_seasons()
    current_sid = (seasons[0].get(CLAUSURA) or seasons[0].get(APERTURA)) if seasons else None
    if current_sid and not sofascore.is_blocked():
        try:
            refresh_standings(store, int(current_sid), budget=budget)
        except Exception as exc:  # noqa: BLE001 - a check, never the reason a run fails
            logger.warning("standings refresh failed: %s", exc)
    status = update_store(store, max_new=budget.left // sofascore.DETAIL_CALLS, budget=budget, refresh=args.refresh_detail)
    logger.info("detail calls used: %d of %d", budget.used, budget.limit)

    if not status["ok"]:
        logger.warning(
            "Fetch failed — store left untouched with %d matches. The site will serve "
            "the retained store and mark it stale.", before,
        )
        return 1

    save_store(store, STORE_PATH)
    logger.info(
        "Store: %d matches, %d with detail, %d with team stats (+%d this run, %d failures)",
        len(store["matches"]), len(store["lineups"]), len(store.get("team_stats") or {}),
        status["new_fetched"], status["failures"],
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        sofascore.save_team_colours()   # teamColors from the answers this run received (no extra call)
