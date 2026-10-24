#!/usr/bin/env python
"""
Current squads from Sofascore, on a rotation, into docs/site/data/squads/store.json.

Squads on the site used to be derived from lineups: a player was listed at the
club he last appeared for in that competition's store, so a player who had left
(Ander Herrera at Boca Juniors, gone to Real Zaragoza) stayed listed until he
appeared elsewhere in a store the site follows. This fetcher asks Sofascore for
each club's current squad (`/team/{id}/players`, one call a club) and the build
reads it as the authority on who plays where.

Which clubs: every club of a followed league's current season, the Argentine
league, and the club sides of the continental and world club cups. National
teams have no fixed squad and are left to their latest call-ups (the build).

Rotation, inside a small per-run budget (default 20 calls):

  - the followed leagues and Argentina before the cups; within each, a club never
    fetched first, then any club whose squad is older than REFRESH_DAYS (3), or older
    than one day inside a transfer window (TRANSFER_WINDOWS), oldest first;
  - a club Sofascore answers with "not found" (404 and the like: a small cup club
    without a squad page) is noted under `failed` and skipped for FAILED_RETRY_DAYS.
    Until 15 October 2026 such a club stayed at the head of the queue and three of
    them ended every run, so the store did not change from 5 to 15 October.

Each squad row also keeps Sofascore's proposed market value (`mv`, EUR unless `mvc`
says otherwise), which the value and transfer pages read.

With about 620 clubs that is a full pass in about thirty-one hours from empty and
about 210 calls a day once warm (one a day per club in a window: about 620).

Departures: when a club's new squad lacks a player its previous squad listed, or
a player who appeared for it in the last year, his Sofascore profile
(`/player/{id}`) is looked up — a few per run, queued across runs — and his new
club recorded under `people`, so the site can say where he went.

Like the other fetchers: residential IP only, stops at the first 403.

    python scripts/fetch_sofascore_squads.py                 # the hourly task's call
    python scripts/fetch_sofascore_squads.py --budget 40
    python scripts/fetch_sofascore_squads.py --team 3202     # one club now
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.football.competitions.cup.config import CUPS  # noqa: E402
from oddsmarkets.football.competitions.league.config import LEAGUES  # noqa: E402
from oddsmarkets.football.sources import sofascore  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("fetch-squads")

SITE_DATA = ROOT / "docs" / "site" / "data"
SQUADS_PATH = SITE_DATA / "squads" / "store.json"
LIGA_STORE = ROOT / "docs" / "liga" / "data" / "liga_store.json"

DEFAULT_BUDGET = 20
REFRESH_DAYS = 3
WINDOW_REFRESH_DAYS = 1
DEPARTURE_LOOKUPS = 8          # profile calls per run, from the budget
RECENT_DAYS = 365              # a player who appeared for a club this recently is expected in its squad
PAUSE_S = 1.0
MAX_CONSECUTIVE_FAILURES = 3
MAX_PENDING = 400
FAILED_RETRY_DAYS = 14         # a club whose squad page is missing is retried after this

# (month, day) to (month, day), inclusive: the main windows across the followed
# leagues (Europe and Saudi summer and January, South America's January-March and
# July, MLS's spring and summer). A club refreshes daily inside any of them.
TRANSFER_WINDOWS = (((1, 1), (2, 10)), ((6, 10), (9, 5)))


def in_transfer_window(day: date) -> bool:
    md = (day.month, day.day)
    return any(lo <= md <= hi for lo, hi in TRANSFER_WINDOWS)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_squads(path: Path = SQUADS_PATH) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        doc = {}
    doc.setdefault("teams", {})
    doc.setdefault("people", {})
    doc.setdefault("pending", [])
    doc.setdefault("failed", {})
    doc.setdefault("meta", {})
    return doc


def save_squads(doc: dict, path: Path = SQUADS_PATH) -> None:
    doc["meta"]["updated_at"] = _now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def candidate_clubs(site_data: Path = SITE_DATA, liga_store: Path = LIGA_STORE) -> tuple[dict[str, dict], dict[str, dict[str, str]]]:
    """
    {tid: {name, priority}} for the clubs whose squads are kept, and
    {tid: {pid: last appearance date}} for the players seen with each in the last
    RECENT_DAYS (for departures). Priority 0: a followed league or Argentina
    (current season); 1: a continental or world club cup (current season).
    """
    clubs: dict[str, dict] = {}
    recent: dict[str, dict[str, str]] = {}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
    sources: list[tuple[Path, int, bool]] = [(site_data / slug / "store.json", 0, True) for slug in LEAGUES]
    sources.append((liga_store, 0, False))
    sources += [(site_data / slug / "store.json", 1, True) for slug, cfg in CUPS.items() if cfg.family == "cup"]
    for path, priority, by_season in sources:
        st = _read(path)
        matches = st.get("matches") or {}
        current = (st.get("meta") or {}).get("season_id")
        for m in matches.values():
            if by_season and current is not None and m.get("season_id") != current:
                continue
            for side in ("home", "away"):
                tid = m.get(f"{side}_id")
                if tid is None:
                    continue
                c = clubs.setdefault(str(tid), {"name": m.get(side), "priority": priority})
                c["priority"] = min(c["priority"], priority)
        for gid, lineup in (st.get("lineups") or {}).items():
            m = matches.get(gid) or {}
            d = str(m.get("date") or "")[:10]
            if not d or d < cutoff or not isinstance(lineup, dict):
                continue
            for pid, p in lineup.items():
                if not isinstance(p, dict):
                    continue
                team = p.get("t")
                tid = m.get("home_id") if team == m.get("home") else m.get("away_id") if team == m.get("away") else None
                if tid is None:
                    continue
                row = recent.setdefault(str(tid), {})
                if d > row.get(str(pid), ""):
                    row[str(pid)] = d
    # Keep a player only under the club of his latest appearance: one who has
    # since played for another followed club has visibly moved and needs no lookup.
    latest: dict[str, tuple[str, str]] = {}
    for tid, row in recent.items():
        for pid, d in row.items():
            if d > latest.get(pid, ("", ""))[0]:
                latest[pid] = (d, tid)
    recent = {tid: {pid: d for pid, d in row.items() if latest[pid][1] == tid} for tid, row in recent.items()}
    return clubs, recent


def due_clubs(clubs: dict[str, dict], squads: dict, today: datetime | None = None) -> list[str]:
    """
    Clubs to fetch, in order: by priority (followed leagues first), within it never
    fetched, then stale (oldest first). A club whose page was missing recently is skipped.
    """
    today = today or datetime.now(timezone.utc)
    max_age = timedelta(days=WINDOW_REFRESH_DAYS if in_transfer_window(today.date()) else REFRESH_DAYS)
    failed = squads.get("failed") or {}
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    queue = []
    for tid, info in clubs.items():
        bad = _parse((failed.get(tid) or {}).get("at"))
        if bad is not None and today - bad < timedelta(days=FAILED_RETRY_DAYS):
            continue
        rec = squads["teams"].get(tid)
        fetched = _parse((rec or {}).get("fetched_at"))
        if fetched is None:
            queue.append((info["priority"], 0, epoch, tid))
        elif today - fetched >= max_age:
            queue.append((info["priority"], 1, fetched, tid))
    queue.sort()
    return [q[3] for q in queue]


def departures(old: list[dict] | None, new: list[dict], recent: dict[str, str] | None) -> list[str]:
    """Players the club had (previous squad, or a recent appearance) who are not in the new squad."""
    now_ids = {p["id"] for p in new}
    had = {p["id"] for p in old or []} | set(recent or {})
    return sorted(had - now_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="calls this run may make")
    parser.add_argument("--team", action="append", help="fetch these team ids now (ignores the rotation)")
    args = parser.parse_args()

    squads = load_squads()
    clubs, recent = candidate_clubs()
    queue = [str(t) for t in args.team] if args.team else due_clubs(clubs, squads)
    budget = sofascore.CallBudget(args.budget)
    logger.info("squads: %d clubs followed, %d stored, %d due, %d departures pending; budget %d",
                len(clubs), len(squads["teams"]), len(queue), len(squads["pending"]), budget.limit)
    changed = False
    misses = 0
    # Profiles of departed players first, a few a run, so they never starve.
    lookups = 0
    while squads["pending"] and lookups < DEPARTURE_LOOKUPS and budget.left > 0 and not sofascore.is_blocked():
        pid = squads["pending"].pop(0)
        changed = True
        try:
            det = sofascore.player_details(pid, budget=budget)
        except sofascore.BudgetExhausted:
            squads["pending"].insert(0, pid)
            break
        lookups += 1
        time.sleep(PAUSE_S)
        if det is None:
            if sofascore.is_blocked():
                squads["pending"].insert(0, pid)
                break
            continue
        squads["people"][str(pid)] = {"team_id": det.get("team_id"), "team": det.get("team"),
                                      "name": det.get("name"), "fetched_at": _now()}
    for tid in queue:
        if budget.left < 1 or sofascore.is_blocked():
            break
        try:
            rows = sofascore.team_players(tid, budget=budget)
        except sofascore.BudgetExhausted:
            break
        time.sleep(PAUSE_S)
        if rows is None:
            if sofascore.LAST_STATUS in (404, 410, 422) or (sofascore.LAST_STATUS == 200):
                # Sofascore has no squad page for this club: note it and move on, so it
                # cannot block the clubs behind it.
                squads["failed"][tid] = {"at": _now(), "status": sofascore.LAST_STATUS}
                changed = True
                logger.info("%s %s: no squad page (HTTP %s), retried in %d days", tid, (clubs.get(tid) or {}).get("name"),
                            sofascore.LAST_STATUS, FAILED_RETRY_DAYS)
                continue
            misses += 1
            if sofascore.is_blocked() or misses >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("Sofascore is not answering (status %s) — stopping", sofascore.LAST_STATUS)
                break
            continue
        misses = 0
        squads["failed"].pop(tid, None)
        old = (squads["teams"].get(tid) or {}).get("players")
        gone = departures(old, rows, recent.get(tid))
        known = set(squads["people"]) | set(squads["pending"])
        squads["pending"].extend(p for p in gone if p not in known)
        del squads["pending"][MAX_PENDING:]
        squads["teams"][tid] = {"name": (clubs.get(tid) or {}).get("name") or (squads["teams"].get(tid) or {}).get("name"),
                                "fetched_at": _now(), "players": rows}
        # A player now in a fetched squad no longer needs a profile lookup.
        listed = {p["id"] for p in rows}
        squads["pending"] = [p for p in squads["pending"] if p not in listed]
        for pid in listed:
            squads["people"].pop(pid, None)
        changed = True
        logger.info("%s %s: %d players, %d left since last seen", tid, squads["teams"][tid]["name"], len(rows), len(gone))
    logger.info("calls used: %d of %d", budget.used, budget.limit)
    if changed:
        save_squads(squads)
    if sofascore.is_blocked() and budget.used <= 1:
        logger.error("Sofascore is challenging this IP (HTTP 403) — nothing fetched this run")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        sofascore.save_team_colours()   # teamColors from the answers this run received (no extra call)
