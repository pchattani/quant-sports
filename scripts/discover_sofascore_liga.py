#!/usr/bin/env python
"""
Discover Sofascore season ids and zone membership for the Liga Profesional.

RUN THIS LOCALLY, NOT IN CI. Sofascore blocks datacenter IPs, so GitHub Actions
cannot reach it; this needs a residential connection. Its output is committed as
static configuration and read by everything else, so it only has to run at a season
rollover, not on a schedule.

    python scripts/discover_sofascore_liga.py            # write seasons.json
    python scripts/discover_sofascore_liga.py --verify   # print, do not write

The season list is the piece that cannot be guessed: Sofascore ids are opaque, and
picking the wrong one silently produces a dashboard for last season. `--verify`
prints each id next to its name so the mapping can be eyeballed before committing.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.liga.config import (  # noqa: E402
    APERTURA,
    CLAUSURA,
    SOFASCORE_TOURNAMENT_ID,
    ZONES,
)
from oddsmarkets.football.sources.teams import normalize_team_name  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("discover-liga")

OUT_PATH = ROOT / "oddsmarkets" / "football" / "competitions" / "liga" / "data" / "seasons.json"

# datafc exposes no seasons-list wrapper, so this endpoint is called directly, using
# the same host failover datafc itself relies on.
_HOSTS = ["api.sofascore.com", "api.sofavpn.com"]

# How many of the newest seasons to probe for a combined Apertura+Clausura season id.
# One standings call each, so this stays small; older seasons predate the format.
_PROBE_NEWEST = 3


def _get(path: str) -> dict | None:
    """GET a Sofascore API path, trying each host. Returns None on total failure."""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        logger.error("curl_cffi is required (it ships with datafc). Run: uv sync")
        return None

    for host in _HOSTS:
        url = f"https://{host}/api/v1{path}"
        try:
            resp = curl_requests.get(url, impersonate="chrome", timeout=20)
            if resp.status_code == 200:
                return resp.json()
            logger.debug("%s -> HTTP %s", url, resp.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.debug("%s failed: %s", url, exc)
    logger.warning("All hosts failed for %s", path)
    return None


def _classify(name: str) -> str | None:
    """Map a Sofascore season name onto our torneo keys."""
    low = name.lower()
    if "apertura" in low:
        return APERTURA
    if "clausura" in low:
        return CLAUSURA
    return None


def _year_of(name: str) -> int | None:
    match = re.search(r"(20\d{2})", name)
    return int(match.group(1)) if match else None


def discover_seasons(tournament_id: int = SOFASCORE_TOURNAMENT_ID) -> list[dict]:
    payload = _get(f"/unique-tournament/{tournament_id}/seasons")
    if not payload:
        return []
    out = []
    for season in payload.get("seasons", []):
        name = str(season.get("name", ""))
        out.append({
            "season_id": season.get("id"),
            "name": name,
            "year": season.get("year"),
            "parsed_year": _year_of(name),
            "torneo": _classify(name),
        })
    return out


def discover_zones(
    tournament_id: int, season_id: int, default_torneo: str | None = None
) -> dict[str, dict[str, list[str]]]:
    """
    Zone membership per tournament, as {torneo: {zone: [teams]}}.

    Sofascore returns one standings block per zone; the names are matched loosely
    because the API labels them variously ("Zona A", "Group A", "A").

    From 2026 a single season id serves both tournaments, so one payload carries
    "Apertura, Group A" and "..., Clausura, Group A" side by side. The torneo is
    therefore read from each block's own label; keying on the zone letter alone
    would let whichever block came last overwrite the other. `default_torneo`
    covers the pre-2026 shape, where the season is one tournament and its blocks
    are labelled with the zone only.

    Aggregate blocks ("Anual", "Promedios") carry no zone letter and are skipped.
    """
    payload = _get(f"/unique-tournament/{tournament_id}/season/{season_id}/standings/total")
    if not payload:
        return {}
    zones: dict[str, dict[str, list[str]]] = {}
    for block in payload.get("standings", []):
        label = str(block.get("name", "")).strip()
        letter = None
        for candidate in ZONES:
            if re.search(rf"\b{candidate}\b", label, flags=re.IGNORECASE):
                letter = candidate
                break
        if letter is None:
            continue
        torneo = _classify(label) or default_torneo
        if torneo is None:
            continue
        teams = [
            normalize_team_name(str(row.get("team", {}).get("name", "")), "liga_argentina")
            for row in block.get("rows", [])
        ]
        zones.setdefault(torneo, {})[letter] = [t for t in teams if t]
    return zones


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="print, do not write")
    parser.add_argument("--tournament-id", type=int, default=SOFASCORE_TOURNAMENT_ID)
    parser.add_argument("--years", type=int, nargs="*", help="restrict to these years")
    args = parser.parse_args()

    seasons = discover_seasons(args.tournament_id)
    if not seasons:
        logger.error(
            "No seasons returned. Sofascore blocks datacenter IPs — run this from a "
            "residential connection, not CI."
        )
        return 1

    logger.info("Found %d seasons for tournament %d:", len(seasons), args.tournament_id)
    for s in seasons[:20]:
        logger.info(
            "  id=%-8s year=%-6s torneo=%-9s name=%s",
            s["season_id"], s["year"], s["torneo"] or "-", s["name"],
        )

    # A season whose name carries "Apertura" or "Clausura" classifies on the name
    # alone. From 2026 Sofascore stopped splitting them: "Primera LPF 2026" is a
    # single season id serving both tournaments, and only its standings blocks say
    # so. The newest unnamed seasons are therefore probed. Genuinely
    # single-tournament seasons ("Liga Profesional 2024") probe to nothing and are
    # left unclassified, which is what we want — they are not two tournaments.
    probed: dict[int, dict[str, dict[str, list[str]]]] = {}
    for s in seasons[:_PROBE_NEWEST]:
        if s["torneo"] or not s["season_id"]:
            continue
        found = discover_zones(args.tournament_id, int(s["season_id"]))
        if found:
            probed[int(s["season_id"])] = found
            logger.info(
                "season %s (%s) serves %s under one id",
                s["season_id"], s["name"], " + ".join(sorted(found)),
            )

    for s in seasons:
        sid = s["season_id"]
        s["torneos"] = (
            sorted(probed[int(sid)]) if sid and int(sid) in probed
            else [s["torneo"]] if s["torneo"]
            else []
        )

    wanted = [
        s for s in seasons
        if s["torneos"] and (not args.years or (s["parsed_year"] or 0) in args.years)
    ]

    by_year: dict[int, dict] = {}
    for s in wanted:
        # Sofascore returns `year` as a string, and only some season names carry a
        # year to parse out ("Torneo Clausura" does not). Split-year labels like
        # "19/20" have no single calendar year and are skipped.
        year = s["parsed_year"] or s["year"]
        if not isinstance(year, int):
            try:
                year = int(str(year).strip())
            except (TypeError, ValueError):
                continue
        entry = by_year.setdefault(year, {"year": year})
        for torneo in s["torneos"]:
            entry[torneo] = s["season_id"]
            entry.setdefault("names", {})[torneo] = s["name"]

    zones: dict[str, dict] = {}
    for year, entry in sorted(by_year.items(), reverse=True)[:1]:
        for torneo in (CLAUSURA, APERTURA):
            season_id = entry.get(torneo)
            if not season_id:
                continue
            # Reuse the probe rather than re-fetching the same payload per torneo.
            found = probed.get(int(season_id))
            if found is None:
                found = discover_zones(
                    args.tournament_id, int(season_id), default_torneo=torneo
                )
            per_torneo = found.get(torneo) if found else None
            if per_torneo:
                zones.setdefault(str(year), {})[torneo] = per_torneo
                logger.info(
                    "Zones for %s %s: %s",
                    torneo, year, {z: len(t) for z, t in per_torneo.items()},
                )

    payload = {
        "tournament_id": args.tournament_id,
        "discovered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seasons": [by_year[y] for y in sorted(by_year, reverse=True)],
        "zones": zones,
    }

    if args.verify:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s (%d seasons)", OUT_PATH, len(payload["seasons"]))
    logger.info("Commit this file — CI reads it and cannot regenerate it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
