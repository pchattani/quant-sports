#!/usr/bin/env python
"""
Dates of birth and draft slots for The Quant Hardwood from ESPN (valuation v2's ageing and survival curves, the
roster prior's ageing step for past seasons, and the trade ratings' pick-value curve). Only the current season's
store carries dates of birth (bb_fetch.py reads them from today's rosters), so every earlier season's players had
no age before this file.

    core  https://sports.core.api.espn.com/v2/sports/basketball/leagues/{league}/athletes/<id>
              -> dateOfBirth, draft {year, round, selection, team}, debutYear
    site  https://site.api.espn.com/apis/site/v2/sports/basketball/{league}/draft?season=Y
              -> every pick of draft Y with the ESPN athlete id (NBA 2003 on, WNBA about 2017 on), including
                 picks who never played (needed so the pick-value curve counts them as zero)

Writes docs/hardwood/data/<league>/bio.json (committed; the build only reads it):

    {"_meta": {"source", "updated_at", "players", "with_dob", "with_draft"},
     "_drafts": {"YYYY": [[overall, round, pick, team_id, athlete_id, name, traded], ...]},
     pid: {"dob": "YYYY-MM-DD" | null, "draft": [year, round, pick, team_id] | null, "debut": year | null,
           "checked": "YYYY-MM-DD"}}

Candidates: every player id in the league's season stores, most recent seasons first, not yet asked (a player
ESPN answered without a date is re-asked after --recheck-days). Paced (0.5 s), --budget calls per run, saved every
100 players, so an interrupted run keeps what it fetched and the next run resumes. Drafts: every year from the
first ESPN serves to this year, a completed year asked once (a year ESPN answers empty is re-asked after
--recheck-days).

    python scripts/bb_bio.py --league nba
    python scripts/bb_bio.py --league wnba --budget 500
    python scripts/bb_bio.py --league nba --dry-run         # count the candidates
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.basketball import analytics as an  # noqa: E402
from oddsmarkets.basketball.analytics import bio as BIO  # noqa: E402
from oddsmarkets.basketball.sources import espn  # noqa: E402

logger = logging.getLogger("bb_bio")
DRAFT_FROM = {"nba": 2003, "wnba": 2015}


def _day(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def candidates(league: str, bio: dict, recheck_days: int, today: date) -> list[str]:
    """Player ids of every season store, latest season first, that still need asking."""
    last: dict[str, int] = {}
    for s in an.seasons_on_disk(league):
        for pid in (an.load_store(league, s).get("players") or {}):
            last[str(pid)] = max(last.get(str(pid), 0), s)
    out = []
    for pid, s in sorted(last.items(), key=lambda kv: (-kv[1], kv[0])):
        if not pid.isdigit():
            continue
        prev = bio.get(pid) or {}
        if prev.get("checked") and (prev.get("dob") or prev.get("draft")):
            continue
        chk = _day(prev.get("checked"))
        if chk is not None and (today - chk).days < recheck_days:
            continue
        out.append(pid)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=list(an.LEAGUES), required=True)
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--recheck-days", type=int, default=120)
    ap.add_argument("--no-drafts", action="store_true")
    ap.add_argument("--no-players", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    today = datetime.now(timezone.utc).date()
    lg = args.league
    path = BIO.bio_path(lg)
    bio = an.read_json(path) or {}
    drafts = dict(bio.get("_drafts") or {})
    drafts_checked = dict((bio.get("_meta") or {}).get("drafts_checked") or {})
    players = {k: v for k, v in bio.items() if not k.startswith("_")}
    todo = [] if args.no_players else candidates(lg, players, args.recheck_days, today)
    years = []
    if not args.no_drafts:
        for y in range(DRAFT_FROM[lg], today.year + 1):
            have = drafts.get(str(y))
            chk = _day(drafts_checked.get(str(y)))
            done = bool(have) and (y < today.year or (chk is not None and (today - chk).days < 7))
            if done or (not have and chk is not None and (today - chk).days < args.recheck_days):
                continue
            years.append(y)
    logger.info("%s: %d players and %d drafts to ask ESPN (%d players and %d drafts in %s)", lg, len(todo), len(years),
                len(players), len(drafts), path)
    if args.dry_run or (not todo and not years):
        return 0
    c = espn.Client(budget=args.budget, interval=args.interval)
    t0 = time.monotonic()

    def save():
        meta = {"source": "ESPN core athlete API (dateOfBirth, draft) and site draft API", "updated_at": an.now(),
                "players": len(players), "with_dob": sum(1 for v in players.values() if (v or {}).get("dob")),
                "with_draft": sum(1 for v in players.values() if (v or {}).get("draft")), "drafts_checked": drafts_checked}
        an.write_json(path, {"_meta": meta, "_drafts": {k: drafts[k] for k in sorted(drafts)},
                             **{k: players[k] for k in sorted(players, key=lambda x: (len(x), x))}})

    try:
        for y in years:
            d = espn.parse_draft(espn.draft_raw(c, lg, y))
            if d:
                drafts[str(y)] = d
            drafts_checked[str(y)] = today.isoformat()
            logger.info("%s draft %d: %d picks", lg, y, len(d))
        save()
        got = 0
        for i, pid in enumerate(todo):
            rec = espn.parse_athlete(espn.athlete_raw(c, lg, pid)) or {}
            players[pid] = {"dob": rec.get("dob"), "draft": rec.get("draft"), "debut": rec.get("debut"), "checked": today.isoformat()}
            got += 1 if rec.get("dob") else 0
            if (i + 1) % 100 == 0:
                save()
                logger.info("%d / %d asked, %d dates, %.0f s", i + 1, len(todo), got, time.monotonic() - t0)
    except espn.BudgetExhausted as exc:
        logger.info("stopping: %s", exc)
    save()
    logger.info("%s: done in %.0f s (%d calls, %d failures) -> %s", lg, time.monotonic() - t0, c.used, c.failures, path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
