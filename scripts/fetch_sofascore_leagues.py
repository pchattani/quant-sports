#!/usr/bin/env python
"""
Incremental Sofascore fetch for every competition in the registry.

One script serves the Premier League, MLS, the Brasileirão, the cups and the rest
because the season-events endpoint does not care about format: it pages through
every fixture, played or not, with its round, status, score and kickoff.
Round-by-round fetching — what the Argentine fetcher does — cannot work for MLS,
which has no rounds.

Each competition's store lives at docs/site/data/<slug>/store.json and has the
same shape as the Argentine one, so the players, shots, match-detail and xG code
is shared unchanged. Per run: every fixture of the seasons in seasons.json is
refreshed (cheap, a few pages each), then per-match detail — lineups with player
metadata, the team statistics sheet, the shot map, the momentum graph and the
incidents — is fetched for finished current-season matches that lack it.

Detail is paid for from ONE CALL BUDGET PER RUN, spent in tiers and round-robin
across the competitions inside a tier, newest first within each: the current
season's new matches, then (`--refresh-detail`) those fetched in the older, thinner
format, then the previous season of every store in full (the followed leagues, then
the continental cups, then the rest), so a past season's player totals stop being a
rolling twelve-month slice. Sofascore answers an IP-wide 403 "challenge" for many
hours after a burst of a few thousand calls, and the hourly task used to be able to
reach that by itself on a busy weekend; the default budget keeps a run to thirty
full matches (or fifty past ones: a backfilled match is three calls, without the shot
map and the momentum graph).

Before the detail queue, the same budget pays for one call per league match kicking off within
PREMATCH_LEAD_MIN minutes (at most PREMATCH_MAX a run): its line-ups, kept under the store's `prematch`
with the time read until Sofascore marks them confirmed. The build applies the line-up term to those
fixtures (docs/MODELS.md 2.6).

A match Sofascore has no line-ups for (404, or line-ups without player statistics)
is recorded under the store's `detail_missing` {gid: {at, n, why}} and asked again
after RETRY_DAYS[n]; after len(RETRY_DAYS) answers like that it is `final` and never
asked again: the build calls it "unavailable" instead of "to backfill". Only a
missing answer (no response, a 403, a server error) counts toward stopping the run.

RUN THIS LOCALLY. Sofascore blocks datacenter IPs. Every network call degrades to
last-good data rather than failing the run.

    python scripts/fetch_sofascore_leagues.py --all
    python scripts/fetch_sofascore_leagues.py --league premier-league --league mls
    python scripts/fetch_sofascore_leagues.py --all --backfill --budget 2000
    python scripts/fetch_sofascore_leagues.py --all --refresh-detail
    python scripts/fetch_sofascore_leagues.py --probe
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.cup.config import CUPS  # noqa: E402
from oddsmarkets.football.competitions.league.config import LEAGUES  # noqa: E402
from oddsmarkets.football.competitions.league.store import store_signature  # noqa: E402
from oddsmarkets.football.competitions.liga.store import load_store, mark_superseded, save_store  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402
from oddsmarkets.football.sources.teams import normalize_cup_name, normalize_team_name  # noqa: E402

COMPETITIONS = {**LEAGUES, **CUPS}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch-leagues")

SITE_DATA = ROOT / "docs" / "site" / "data"
SEASONS_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "seasons.json"

# Detail calls per run: 30 matches at five calls each, spread over every competition.
# Together with the fixture pages that is under 300 calls an hour, paced at about
# one a second; Sofascore has challenged this IP after bursts of well under a
# thousand calls in an hour.
DEFAULT_BUDGET = 150
BACKFILL_BUDGET = 1000
DETAIL_PAUSE_S = 1.0
# Stop fetching detail after this many matches in a row return nothing: that is
# what a block looks like, and every further call prolongs it.
MAX_CONSECUTIVE_FAILURES = 3


def store_path(slug: str) -> Path:
    return SITE_DATA / slug / "store.json"


def load_seasons() -> dict:
    if not SEASONS_PATH.exists():
        logger.error(
            "No %s. Run scripts/discover_sofascore_leagues.py from a residential "
            "connection and commit the result.", SEASONS_PATH,
        )
        return {}
    try:
        return json.loads(SEASONS_PATH.read_text(encoding="utf-8")).get("leagues", {})
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not read %s: %s", SEASONS_PATH, exc)
        return {}


def refresh_fixtures(store: dict, cfg, entry: dict) -> dict:
    """Refresh every fixture of every configured season; no detail."""
    status = {"ok": False, "matches_seen": 0, "new_fetched": 0, "failures": 0}
    seasons = entry.get("seasons") or []
    if not seasons:
        logger.warning("%s: no seasons in seasons.json", cfg.slug)
        return status

    def canon(name: str) -> str:
        return normalize_team_name(name, cfg.registry)

    # Clubs in a cup canonicalise through their own country's league registry;
    # national teams through the international one.
    international = getattr(cfg, "family", "") == "international"
    canon2 = normalize_cup_name if (cfg.slug in CUPS and not international) else None
    round_slugs = dict(getattr(cfg, "round_slugs", ()) or ())
    bracket_rounds = {code for code, _legs in (getattr(cfg, "rounds", ()) or ())}

    current_id = int(seasons[0]["season_id"])
    fetched_any = False
    for season in seasons:
        sid = int(season["season_id"])
        tid = int(season.get("tournament_id") or cfg.sofascore_id)
        events = sofascore.season_events(tid, sid)
        if not events:
            logger.warning("%s: season %s returned no events — keeping stored fixtures", cfg.slug, sid)
            continue
        fetched_any = True
        n = 0
        for ev in events:
            rec = sofascore.event_record(ev, canon, sid, canon2=canon2, round_slugs=round_slugs, international=international)
            if rec is None:
                continue
            gid, record = rec
            # A knockout cup has no league play: a round outside its bracket
            # (preliminary and qualifying rounds, a bare numeric round) is a
            # qualifying round, listed but never simulated.
            if getattr(cfg, "kind", "") == "knockout" and record.get("stage") == "league":
                record["stage"] = "playoff" if record.get("round") in bracket_rounds else "qualifying"
            prev = store["matches"].get(gid, {})
            # A partial response must not erase what the store already knows.
            record["date"] = record["date"] or prev.get("date")
            # A club renamed by a registry change (or a fixed country code) must
            # rename in the detail already stored for the match, or the players
            # and shots would sit under a club the table no longer shows.
            renames = {prev[k]: record[k] for k in ("home", "away") if prev.get(k) and prev[k] != record[k]}
            if renames:
                for player in (store.get("lineups", {}).get(gid) or {}).values():
                    if isinstance(player, dict) and player.get("t") in renames:
                        player["t"] = renames[player["t"]]
                for shot in (store.get("shots", {}).get(gid) or []):
                    if isinstance(shot, dict) and shot.get("team") in renames:
                        shot["team"] = renames[shot["team"]]
                for inc in (store.get("incidents", {}).get(gid) or []):
                    if isinstance(inc, dict) and inc.get("team") in renames:
                        inc["team"] = renames[inc["team"]]
            store["matches"][gid] = record
            n += 1
        status["matches_seen"] += n
        finished = sum(1 for e in events if (e.get("status") or {}).get("type") == "finished")
        logger.info("%s: season %s (%s): %d fixtures, %d finished", cfg.slug, sid, season.get("name"), n, finished)

    if not fetched_any:
        return status
    status["ok"] = True
    # The season list rewrites a re-listed match's old id as "notstarted" every hour; close it against its new copy
    # again (load_store does the same on every read, so builds agree).
    closed = mark_superseded(store)
    if closed:
        status["superseded"] = len(closed)

    # Conference membership and the id of the season being simulated travel with the
    # store so the build needs nothing but the store and the config.
    store["conferences"] = entry.get("conferences") or {}
    store["meta"] = {
        **(store.get("meta") or {}),
        "league": cfg.slug,
        "season_id": current_id,
        "season_name": seasons[0].get("name"),
        "fixtures_refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return status


DORMANT_DAYS = 7
# Days before a match Sofascore had no line-ups for is asked again, by how many times it has been asked;
# after the last it is final (Sofascore fills line-ups of a just-finished match within hours, or never).
RETRY_DAYS = (1, 7, 30)
DORMANT_REFRESH_HOURS = 24


def is_dormant(store: dict, now: datetime | None = None) -> bool:
    """
    True when nothing is happening in the competition: no fixture within a week
    either side of today and the fixtures were refreshed in the last day. With
    fifty-odd cups and national-team competitions in the registry, most of them
    out of season at any moment, refetching every fixture list every hour would
    spend the Sofascore allowance on lists that cannot have changed.
    """
    matches = store.get("matches") or {}
    if not matches:
        return False
    now = now or datetime.now(timezone.utc)
    stamp = (store.get("meta") or {}).get("fixtures_refreshed_at")
    if not stamp:
        return False
    try:
        refreshed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    if (now - refreshed).total_seconds() > DORMANT_REFRESH_HOURS * 3600:
        return False
    lo = (now - timedelta(days=DORMANT_DAYS)).date().isoformat()
    hi = (now + timedelta(days=DORMANT_DAYS)).date().isoformat()
    for m in matches.values():
        if str(m.get("status") or "") in ("live", "inprogress"):
            return False
        d = str(m.get("date") or "")[:10]
        if d and lo <= d <= hi:
            return False
    return True


HEARTBEAT_HOURS = 20


def needs_heartbeat(previous_stamp: str | None, now: datetime | None = None) -> bool:
    """
    True when a store whose content did not change should still be saved, so
    its fixture-refresh stamp (and `updated_at`) reach disk and the commit.
    Without it the stamp only persists when something else changes, dormancy
    lapses a day after the last real change, and every quiet competition goes
    back to an hourly fixture fetch outside the call budget. Once every
    HEARTBEAT_HOURS keeps it inside DORMANT_REFRESH_HOURS and inside the
    build's 24-hour staleness window.
    """
    if not previous_stamp:
        return True
    now = now or datetime.now(timezone.utc)
    try:
        then = datetime.strptime(previous_stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (now - then).total_seconds() >= HEARTBEAT_HOURS * 3600


def followed_clubs(seasons: dict) -> set[str]:
    """Every club of a followed league, by canonical name, from the league stores."""
    out: set[str] = set()
    for slug in LEAGUES:
        entry = seasons.get(slug) or {}
        out.update(entry.get("teams") or [])
        store = load_store(store_path(slug)) if store_path(slug).exists() else {}
        current = (store.get("meta") or {}).get("season_id")
        for m in (store.get("matches") or {}).values():
            if current is None or m.get("season_id") == current:
                out.add(m.get("home"))
                out.add(m.get("away"))
    # Argentina's clubs are followed too (its own store and fetcher): without them the Copa Argentina and the
    # Supercopa fetched no line-ups at all (October 2026: 0 of 60 played ties), so those pages had no players.
    # Their detail comes out of this run's one budget like every other cup's.
    liga = ROOT / "docs" / "liga" / "data" / "liga_store.json"
    if liga.exists():
        lstore = load_store(liga)
        sids = [m.get("season_id") for m in (lstore.get("matches") or {}).values() if m.get("season_id")]
        current = max(sids) if sids else None
        for m in (lstore.get("matches") or {}).values():
            if current is None or m.get("season_id") == current:
                out.add(normalize_team_name(str(m.get("home") or ""), "liga_argentina") or None)
                out.add(normalize_team_name(str(m.get("away") or ""), "liga_argentina") or None)
    out.discard(None)
    return out


def _due(missing: dict, gid: str, now: datetime) -> bool:
    """Whether a match recorded under `detail_missing` may be asked again."""
    rec = missing.get(gid)
    if not isinstance(rec, dict):
        return True
    if rec.get("final"):
        return False
    try:
        at = datetime.strptime(str(rec.get("at")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    n = max(int(rec.get("n") or 1), 1)
    return now - at >= timedelta(days=RETRY_DAYS[min(n, len(RETRY_DAYS)) - 1])


def record_miss(store: dict, gid: str, why: str | None, now: datetime | None = None) -> None:
    """A match Sofascore answered without line-ups: asked again later, then given up on (`final`)."""
    now = now or datetime.now(timezone.utc)
    missing = store.setdefault("detail_missing", {})
    rec = missing.get(gid) if isinstance(missing.get(gid), dict) else {}
    n = int(rec.get("n") or 0) + 1
    missing[gid] = {"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "n": n, "why": why or "no-lineups"}
    if n >= len(RETRY_DAYS):
        missing[gid]["final"] = True


# Pre-match line-ups (football_edge.md "Round 3"): one call per league match kicking off within the next
# PREMATCH_LEAD_MIN minutes, until Sofascore marks its line-ups confirmed (announced about an hour before
# kick-off). Paid from the run's ONE call budget, before the detail queue, and capped per run, so the hourly
# task makes no more calls than before; the build applies the line-up term to those fixtures.
PREMATCH_LEAD_MIN = sofascore.PREMATCH_LEAD_MIN
PREMATCH_MAX = sofascore.PREMATCH_MAX
prematch_queue = sofascore.prematch_queue


# Tiers of the detail queue, spent in this order (round-robin across competitions inside each).
TIER_NEW, TIER_REFRESH, TIER_LEAGUE_PAST, TIER_CUP_PAST, TIER_OTHER_PAST = range(5)


def wants_detail(m: dict, followed: set[str] | None, club_followed: set[str] | None = None) -> bool:
    """
    Whether a finished match is in the fetch's scope: a national cup (`followed`
    given) only with a followed club in it; a qualifying round or other
    pre-competition tie only with a followed club (`club_followed`, every club of a
    followed league) in it, as Sofascore has no line-ups for many of the rest.
    """
    pool = followed if followed is not None else club_followed
    involved = pool is not None and (m.get("home") in pool or m.get("away") in pool)
    if m.get("stage") in ("qualifying", "other"):
        return involved
    return followed is None or involved


def detail_queue(store: dict, refresh: bool, followed: set[str] | None = None, past_tier: int = TIER_OTHER_PAST,
                 club_followed: set[str] | None = None, now: datetime | None = None) -> list[tuple[str, dict]]:
    """
    Finished matches that want detail, newest first within each tier: the current
    season's with none, then (with `refresh`) the current season's fetched before
    the team-stat sheet and the full stat set were kept, then every earlier season
    the store holds, in full. `followed` restricts a national cup to ties with a
    followed club; `club_followed` (every followed club) lets a qualifying tie in
    when one of them plays in it. Matches recorded as missing wait for their retry
    and are left out once final. Items are (gid, meta) and carry their tier in
    `meta["_tier"]`.
    """
    now = now or datetime.now(timezone.utc)
    current_id = (store.get("meta") or {}).get("season_id")
    missing = store.get("detail_missing") or {}
    lineups = store.get("lineups") or {}
    sheets = store.get("team_stats") or {}
    fresh: list[tuple[str, dict]] = []
    stale: list[tuple[str, dict]] = []
    past: list[tuple[str, dict]] = []
    for gid, m in (store.get("matches") or {}).items():
        if m.get("status") != sofascore.STATUS_FINISHED:
            continue
        if not wants_detail(m, followed, club_followed):
            continue
        if gid in lineups:
            if refresh and m.get("season_id") == current_id and gid not in sheets:
                stale.append((gid, {**m, "_tier": TIER_REFRESH}))
            continue
        if not _due(missing, gid, now):
            continue
        if m.get("season_id") == current_id:
            fresh.append((gid, {**m, "_tier": TIER_NEW}))
        else:
            past.append((gid, {**m, "_tier": past_tier}))
    key = lambda kv: kv[1].get("date") or ""  # noqa: E731
    fresh.sort(key=key, reverse=True)
    stale.sort(key=key, reverse=True)
    past.sort(key=key, reverse=True)
    return fresh + stale + past


def interleave(queues: dict[str, list[tuple[str, dict]]]) -> list[tuple[str, str, dict]]:
    """One order for every competition's queue: by tier, then round-robin across competitions, newest first in each."""
    items = []
    for order, (slug, q) in enumerate(queues.items()):
        rank: dict[int, int] = {}
        for gid, meta in q:
            t = int(meta.get("_tier", TIER_NEW))
            r = rank.get(t, 0)
            rank[t] = r + 1
            items.append(((t, r, order), slug, gid, meta))
    items.sort(key=lambda x: x[0])
    return [(slug, gid, meta) for _k, slug, gid, meta in items]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", action="append", help="slug; repeatable")
    parser.add_argument("--all", action="store_true", help="every competition in the registry")
    parser.add_argument("--backfill", action="store_true", help="a larger default budget")
    parser.add_argument("--budget", type=int, default=None, help="detail calls this run may make (5 per match)")
    parser.add_argument("--refresh-detail", action="store_true",
                        help="also re-fetch matches stored in the older, thinner detail format")
    parser.add_argument("--probe", action="store_true", help="connectivity check only")
    parser.add_argument("--force", action="store_true", help="rewrite stores even if only live scores changed")
    parser.add_argument("--refresh-dormant", action="store_true",
                        help="refetch the fixtures of out-of-season competitions too (they otherwise refresh daily)")
    args = parser.parse_args()

    seasons = load_seasons()
    if not seasons:
        return 1

    if args.probe:
        first = next(iter(seasons.values()))
        ok = sofascore.probe(first["tournament_id"], int(first["seasons"][0]["season_id"]))
        return 0 if ok else 1

    slugs = list(COMPETITIONS) if args.all or not args.league else args.league
    budget = sofascore.CallBudget(args.budget if args.budget is not None else (BACKFILL_BUDGET if args.backfill else DEFAULT_BUDGET))

    # One call before anything else: a challenged IP answers 403 to everything,
    # and a run that carries on regardless makes a hundred more wasted calls.
    first = next((seasons[s] for s in slugs if s in seasons), None)
    if first and not sofascore.probe(int(first["tournament_id"]), int(first["seasons"][0]["season_id"])):
        if sofascore.is_blocked():
            logger.error("Sofascore is challenging this IP (HTTP 403) — nothing fetched this run")
            return 1
        logger.warning("probe failed — carrying on, each competition degrades on its own")

    # Phase one: fixtures for every competition (cheap), and the detail queue each wants.
    comps: list[dict] = []
    failures = 0
    followed = followed_clubs(seasons)
    for slug in slugs:
        if sofascore.is_blocked():
            logger.error("Sofascore started challenging this IP mid-run — stopping before %s", slug)
            failures += 1
            continue
        cfg = COMPETITIONS.get(slug)
        entry = seasons.get(slug)
        if cfg is None:
            logger.error("unknown competition %s", slug)
            failures += 1
            continue
        if not entry:
            logger.error("%s: not in seasons.json — run discover_sofascore_leagues.py", slug)
            failures += 1
            continue
        path = store_path(slug)
        store = load_store(path)
        if (store.get("meta") or {}).get("synthetic"):
            logger.warning("%s: store is synthetic sample data — starting fresh", slug)
            store = sofascore.new_store()
        for key in ("matches", "lineups", "shots", "momentum", "incidents", "players", "team_stats", "lineup_extras"):
            store.setdefault(key, {})
        before = len(store["lineups"])
        signature = store_signature(store)
        stamp_before = (store.get("meta") or {}).get("fixtures_refreshed_at")
        if not args.refresh_dormant and is_dormant(store):
            logger.info("%s: dormant (no fixture within %d days, refreshed today) — fixture list kept", slug, DORMANT_DAYS)
            status = {"ok": True, "matches_seen": len(store["matches"]), "new_fetched": 0, "failures": 0, "dormant": True}
        else:
            try:
                status = refresh_fixtures(store, cfg, entry)
            except Exception as exc:  # noqa: BLE001
                logger.error("%s: unexpected failure: %s", slug, exc)
                status = {"ok": False, "new_fetched": 0, "failures": 0}
        if not status["ok"]:
            logger.warning("%s: fetch failed — store left untouched (%d with detail)", slug, before)
            failures += 1
            continue
        scope = followed if getattr(cfg, "detail_scope", "all") == "followed" else None
        past_tier = TIER_LEAGUE_PAST if slug in LEAGUES else TIER_CUP_PAST if getattr(cfg, "family", "") == "cup" else TIER_OTHER_PAST
        queue = detail_queue(store, args.refresh_detail, scope, past_tier=past_tier, club_followed=followed)
        if queue:
            logger.info("%s: %d matches want detail", slug, len(queue))
        else:
            logger.info("%s: detail up to date (%d matches with lineups)", slug, len(store["lineups"]))

        def canon(name: str, _cfg=cfg) -> str:
            return normalize_team_name(name, _cfg.registry)

        comps.append({"slug": slug, "cfg": cfg, "path": path, "store": store, "signature": signature,
                      "stamp_before": stamp_before,
                      "status": status, "queue": queue, "canon": canon})

    # Phase 1b: line-ups of league matches about to start (one call each, from the same budget, capped).
    pre = [(c, gid, m) for c in comps if c["slug"] in LEAGUES for gid, m in prematch_queue(c["store"])]
    pre.sort(key=lambda x: str(x[2].get("date") or ""))
    n_pre = 0
    for c, gid, m in pre[:PREMATCH_MAX]:
        if budget.left < 1 or sofascore.is_blocked():
            break
        try:
            ok = sofascore.fetch_prematch(c["store"], gid, m, budget=budget)
        except sofascore.BudgetExhausted:
            break
        if ok:
            c["status"]["prematch"] = c["status"].get("prematch", 0) + 1
            n_pre += 1
    if pre:
        logger.info("pre-match line-ups: %d of %d matches kicking off within %d min (%d calls)", n_pre, len(pre),
                    PREMATCH_LEAD_MIN, min(len(pre), PREMATCH_MAX))

    # Phase two: detail, in tiers and round-robin across competitions until the budget is spent.
    by_slug = {c["slug"]: c for c in comps}
    order = interleave({c["slug"]: c["queue"] for c in comps if c["queue"]})
    misses = 0
    for slug, gid, meta in order:
        c = by_slug[slug]
        lite = meta.get("_tier", TIER_NEW) >= TIER_LEAGUE_PAST
        need = sofascore.LITE_DETAIL_CALLS if lite else sofascore.DETAIL_CALLS
        if budget.left < need:
            if budget.left < sofascore.LITE_DETAIL_CALLS:
                break
            continue
        record = {k: v for k, v in meta.items() if k != "_tier"}
        try:
            ok = sofascore.fetch_match_detail(c["store"], gid, record, c["canon"], budget=budget, lite=lite)
        except sofascore.BudgetExhausted:
            break
        except Exception as exc:  # noqa: BLE001
            ok = False
            logger.debug("detail fetch failed for %s: %s", gid, exc)
        if ok:
            (c["store"].get("detail_missing") or {}).pop(gid, None)
            c["status"]["new_fetched"] += 1
            misses = 0
        else:
            c["status"]["failures"] += 1
            why = sofascore.LAST_DETAIL_MISS
            if why in ("no-lineups", "no-stats"):
                # Sofascore answered: the data is not there (yet). Not a sign of a block.
                record_miss(c["store"], gid, why)
                c["status"]["missing"] = c["status"].get("missing", 0) + 1
            else:
                misses += 1
        if sofascore.is_blocked() or misses >= MAX_CONSECUTIVE_FAILURES:
            logger.warning("Sofascore is not answering detail calls — stopping detail for this run")
            break
        time.sleep(DETAIL_PAUSE_S)
    logger.info("detail calls used: %d of %d", budget.used, budget.limit)

    # Phase three: save what changed.
    for c in comps:
        store, path, slug = c["store"], c["path"], c["slug"]
        # A store that only differs by live scores is not worth a commit: the hourly
        # task would otherwise push every league every hour of every match day.
        if not args.force and path.exists() and store_signature(store) == c["signature"] and not c["status"].get("missing") \
                and not c["status"].get("prematch"):
            if c["status"].get("dormant") or not needs_heartbeat(c.get("stamp_before")):
                logger.info("%s: nothing but live scores changed — store not rewritten", slug)
                continue
            logger.info("%s: unchanged, saved once a day so the refresh stamp persists", slug)
        save_store(store, path)
        logger.info(
            "%s: %d matches, %d with detail, %d with team stats (+%d this run, %d failures)", slug,
            len(store["matches"]), len(store["lineups"]), len(store.get("team_stats") or {}),
            c["status"]["new_fetched"], c["status"]["failures"],
        )

    # Partial success is success: the stores that updated are worth committing.
    return 0 if failures < len(slugs) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        sofascore.save_team_colours()   # teamColors from the answers this run received (no extra call)
