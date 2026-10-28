#!/usr/bin/env python
"""
Discover Sofascore season ids, team lists, conferences and last season's final
table for every league in the registry.

RUN THIS LOCALLY, NOT IN CI. Sofascore blocks datacenter IPs. The output is committed
as static configuration and read by the fetcher and the build, so it only has to run
at a season rollover — or when a league is added to
`oddsmarkets/football/competitions/league/config.py`.

    python scripts/discover_sofascore_leagues.py             # write seasons.json
    python scripts/discover_sofascore_leagues.py --verify    # print, do not write
    python scripts/discover_sofascore_leagues.py --league mls --league premier-league

What it records per league, and why:

  - The newest season id (the one being simulated) and the one before it, whose
    results train the model. Ids are opaque, and picking the wrong one silently
    produces last season's dashboard, so the names are stored beside them for
    eyeballing.
  - The previous season's final table, which seeds Elo. Promoted clubs are absent
    from it and start at the bottom, which is the right prior.
  - Conference membership, for MLS, from the per-conference standings blocks.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.cup.config import CUPS  # noqa: E402
from oddsmarkets.football.competitions.league.config import LEAGUES  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402
from oddsmarkets.football.sources.sofascore import list_seasons, standings_blocks  # noqa: E402
from oddsmarkets.football.sources.teams import normalize_team_name  # noqa: E402

COMPETITIONS = {**LEAGUES, **CUPS}

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("discover-leagues")

OUT_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "league" / "data" / "seasons.json"

# How many seasons back to keep. The current season plus one of history is what the
# model trains on; anything older is decayed to near nothing by the time weighting.
KEEP_SEASONS = 2


def _overall_block(blocks: list[dict], cfg) -> dict | None:
    """The single whole-league table: the block whose name carries no conference."""
    if cfg.conferences:
        plain = [b for b in blocks if not any(c.lower() in b["name"].lower() for c in cfg.conferences)]
    else:
        plain = blocks
    plain = [b for b in plain if b["rows"]]
    return max(plain, key=lambda b: len(b["rows"])) if plain else None


def resolve_id(cfg) -> int | None:
    """The Sofascore id: the config's, or the one search finds for its name and country."""
    if cfg.sofascore_id:
        return int(cfg.sofascore_id)
    if not getattr(cfg, "search", None):
        return None
    hit = sofascore.search_tournament(cfg.search, getattr(cfg, "country_hint", None))
    if not hit:
        logger.error("%s: Sofascore search found nothing for %r (%s)", cfg.slug, cfg.search, cfg.country_hint)
        return None
    # A national or super cup must be its own country's: search can rank another country's namesake first when the
    # country's own is missing (a "Trofeo de Campeones" exists in more than one country).
    hint = getattr(cfg, "country_hint", None)
    if getattr(cfg, "family", "") in ("domestic", "super") and hint and sofascore._fold(hint) not in sofascore._fold(hit.get("category")):
        logger.error("%s: search found %s %r in %s, not %s; not taken", cfg.slug, hit["id"], hit["name"], hit["category"], hint)
        return None
    logger.info("%s: resolved to %s %r (%s)", cfg.slug, hit["id"], hit["name"], hit["category"])
    return int(hit["id"])


def discover_cup(cfg) -> dict | None:
    """A cup: two seasons, and the current season's league-phase table or groups."""
    tid = resolve_id(cfg)
    if not tid:
        return None
    seasons = list_seasons(tid)
    if not seasons:
        logger.error("%s: no seasons returned", cfg.slug)
        return None
    kept = [{**s, "tournament_id": tid} for s in seasons[:KEEP_SEASONS]]
    logger.info("%s: %s", cfg.slug, ", ".join(f"{s['season_id']} ({s['name']})" for s in kept))
    entry = {"tournament_id": tid, "seasons": kept, "teams": [], "conferences": {}, "previous_rank": {},
             "family": getattr(cfg, "family", "cup")}
    if cfg.kind in ("fixed", "knockout", "international"):
        return entry
    blocks = standings_blocks(tid, int(kept[0]["season_id"]))
    if cfg.kind == "groups":
        for b in blocks:
            name = b["name"]
            if "group" in name.lower() and b["rows"]:
                letter = name.strip()[-1].upper()
                entry["conferences"][letter] = [r["team"] for r in b["rows"]]
        entry["teams"] = [t for members in entry["conferences"].values() for t in members]
    else:
        plain = [b for b in blocks if b["rows"]]
        if plain:
            entry["teams"] = [r["team"] for r in max(plain, key=lambda b: len(b["rows"]))["rows"]]
    if len(entry["teams"]) != cfg.n_teams:
        logger.warning("%s: %d teams listed, config says %d (a phase may not have started)",
                       cfg.slug, len(entry["teams"]), cfg.n_teams)
    return entry


def discover_league(cfg) -> dict | None:
    seasons = list_seasons(cfg.sofascore_id)
    if not seasons:
        logger.error("%s: no seasons returned", cfg.slug)
        return None
    kept = [{**s, "tournament_id": cfg.sofascore_id} for s in seasons[:KEEP_SEASONS]]
    # A league split across two Sofascore tournaments (Liga MX's Apertura and
    # Clausura): the current season is the newer of the two newest, and the
    # history is the other plus the current tournament's previous edition.
    alt_id = getattr(cfg, "alt_sofascore_id", None)
    if alt_id:
        alt = [{**s, "tournament_id": alt_id} for s in list_seasons(alt_id)[:1]]
        cand = sorted(kept[:1] + alt, key=lambda s: -int(s["season_id"]))
        current = cand[0]
        rest = [s for s in cand[1:]] + [s for s in kept[1:] if s["tournament_id"] == current["tournament_id"]]
        kept = [current] + rest[:KEEP_SEASONS]
    logger.info("%s: %s", cfg.slug, ", ".join(f"{s['season_id']} ({s['name']})" for s in kept))

    current = kept[0]
    entry = {
        "tournament_id": cfg.sofascore_id,
        "seasons": kept,
        "teams": [],
        "conferences": {},
        "previous_rank": {},
    }

    blocks = standings_blocks(current["tournament_id"], int(current["season_id"]))
    overall = _overall_block(blocks, cfg)
    if overall:
        entry["teams"] = [normalize_team_name(r["team"], cfg.registry) for r in overall["rows"]]
        entry["bands_seen"] = sorted({r["promotion"] for r in overall["rows"] if r["promotion"]})
    if cfg.conferences:
        for conf in cfg.conferences:
            block = next((b for b in blocks if conf.lower() in b["name"].lower()), None)
            if block:
                entry["conferences"][conf] = [
                    normalize_team_name(r["team"], cfg.registry) for r in block["rows"]
                ]
                entry.setdefault("bands_seen", [])
                entry["bands_seen"] = sorted(
                    set(entry["bands_seen"]) | {r["promotion"] for r in block["rows"] if r["promotion"]}
                )
        sizes = {c: len(t) for c, t in entry["conferences"].items()}
        if sizes != {c: cfg.teams_per_conference for c in cfg.conferences}:
            logger.warning("%s: conference sizes %s do not match config", cfg.slug, sizes)

    if len(entry["teams"]) != cfg.n_teams:
        logger.warning(
            "%s: standings list %d teams but config says %d", cfg.slug,
            len(entry["teams"]), cfg.n_teams,
        )

    if len(kept) > 1:
        prev_blocks = standings_blocks(kept[1]["tournament_id"], int(kept[1]["season_id"]))
        prev = _overall_block(prev_blocks, cfg)
        if prev:
            entry["previous_rank"] = {
                normalize_team_name(r["team"], cfg.registry): int(r["position"])
                for r in prev["rows"] if r.get("position")
            }
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="print, do not write")
    parser.add_argument("--league", action="append", help="restrict to these slugs")
    parser.add_argument("--missing", action="store_true", help="only competitions not yet in seasons.json")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many competitions, so discovery spreads over several runs")
    args = parser.parse_args()

    slugs = args.league or list(COMPETITIONS)
    existing = {}
    if OUT_PATH.exists() and (args.league or args.missing or args.limit):
        try:
            existing = json.loads(OUT_PATH.read_text(encoding="utf-8")).get("leagues", {})
        except Exception:  # noqa: BLE001
            existing = {}
    if args.missing:
        slugs = [s for s in slugs if s not in existing]
    if args.limit:
        slugs = slugs[: args.limit]
    if not slugs:
        logger.info("nothing to discover")
        return 0

    leagues = dict(existing)
    failed = []
    for slug in slugs:
        if sofascore.is_blocked():
            logger.error("Sofascore is challenging this IP — stopping before %s", slug)
            failed.append(slug)
            continue
        cfg = COMPETITIONS[slug]
        entry = discover_cup(cfg) if slug in CUPS else discover_league(cfg)
        if entry is None:
            failed.append(slug)
            continue
        leagues[slug] = entry
    if len(failed) == len(slugs):
        logger.error("nothing discovered this run")
        return 1

    payload = {
        "discovered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "leagues": leagues,
    }
    if args.verify:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1 if failed else 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s (%d leagues%s)", OUT_PATH, len(leagues),
                f", failed: {failed}" if failed else "")
    logger.info("Commit this file — CI reads it and cannot regenerate it.")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        sofascore.save_team_colours()   # teamColors from the answers this run received (no extra call)
