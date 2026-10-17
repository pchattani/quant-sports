#!/usr/bin/env python
"""
Dates of birth for The Quant Ace from ESPN's core athlete API (the age curve of the Value section, and the age shown on
ATP player pages: neither tennis-data nor ESPN's scoreboards carry one, and the WTA API covers only some players).

    https://sports.core.api.espn.com/v2/sports/tennis/leagues/{atp,wta}/athletes/<espn id>   ->  "dateOfBirth"

Writes docs/ace/data/<tour>/bio.json:

    {"_meta": {"source", "updated_at", "players", "with_dob"},
     pid: {"dob": "YYYY-MM-DD" | null, "espn": id, "checked": "YYYY-MM-DD"}}

Candidates: players with an ESPN id (the pid itself when numeric, else the registry's "espn") and at least --min-matches
rated matches since --since on disk, who have no date of birth yet (from the WTA API or an earlier run). A player ESPN
answered without a date is re-asked after --recheck-days. Paced like every tennis source (0.5 s, --budget calls per run;
an interrupted run keeps what it fetched: the file is saved every 100 players). The build only reads the file
(TourData.players fills a missing "dob" from it); it never calls ESPN for it.

    python scripts/tn_bio.py --tour atp
    python scripts/tn_bio.py --tour wta --budget 500
    python scripts/tn_bio.py --tour atp --dry-run          # count the candidates
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.tennis import analytics as an  # noqa: E402
from oddsmarkets.tennis.sources import espn  # noqa: E402

logger = logging.getLogger("tn_bio")


def bio_path(tour: str) -> Path:
    return an.data_root() / tour / "bio.json"


def candidates(td: an.TourData, bio: dict, since: str, min_matches: int, recheck_days: int, today: date) -> list[tuple[str, str]]:
    n = Counter()
    for m in td.rated_matches():
        if str(m.get("date") or "") >= since:
            n[str(m["p1"])] += 1
            n[str(m["p2"])] += 1
    out = []
    for pid, k in n.most_common():
        if k < min_matches:
            break
        info = td.players.get(pid) or {}
        if info.get("dob"):
            continue
        espn_id = pid if pid.isdigit() else str(info.get("espn") or "")
        if not espn_id.isdigit():
            continue
        prev = bio.get(pid) or {}
        if prev.get("dob"):
            continue
        chk = an.day(prev.get("checked"))
        if chk is not None and (today - chk).days < recheck_days:
            continue
        out.append((pid, espn_id))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tour", choices=list(an.TOURS), required=True)
    ap.add_argument("--budget", type=int, default=2500)
    ap.add_argument("--interval", type=float, default=0.5)
    ap.add_argument("--since", default="2005-01-01", help="count rated matches from this date (default 2005-01-01)")
    ap.add_argument("--min-matches", type=int, default=5)
    ap.add_argument("--recheck-days", type=int, default=180)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    today = datetime.now(timezone.utc).date()
    td = an.TourData(args.tour, today)
    path = bio_path(td.tour)
    bio = an.read_json(path) or {}
    todo = candidates(td, bio, args.since, args.min_matches, args.recheck_days, today)
    logger.info("%s: %d players to ask ESPN for a date of birth (%d already in %s)", td.tour, len(todo),
                sum(1 for k, v in bio.items() if not k.startswith("_") and (v or {}).get("dob")), path)
    if args.dry_run or not todo:
        return 0
    c = espn.client(budget=args.budget, interval=args.interval)
    t0 = time.monotonic()
    got = 0

    def save():
        meta = {"source": "ESPN core athlete API (dateOfBirth)", "updated_at": an.now(),
                "players": sum(1 for k in bio if not k.startswith("_")),
                "with_dob": sum(1 for k, v in bio.items() if not k.startswith("_") and (v or {}).get("dob"))}
        an.write_json(path, {"_meta": meta, **{k: v for k, v in sorted(bio.items()) if not k.startswith("_")}})

    try:
        for i, (pid, espn_id) in enumerate(todo):
            rec = espn.parse_athlete(espn.athlete_raw(c, td.tour, espn_id))
            bio[pid] = {"dob": (rec or {}).get("dob"), "espn": espn_id, "checked": today.isoformat()}
            got += 1 if (rec or {}).get("dob") else 0
            if (i + 1) % 100 == 0:
                save()
                logger.info("%d / %d asked, %d dates, %.0f s", i + 1, len(todo), got, time.monotonic() - t0)
    except espn.BudgetExhausted as exc:
        logger.info("stopping: %s", exc)
    save()
    logger.info("%s: %d dates of birth from %s; %s", td.tour, got, c.report(), path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
