#!/usr/bin/env python
"""
Per-player style tables from the Match Charting Project (CC BY-NC-SA 4.0, attributed).

Downloads the tour's matches and points files once (data/tennis/charting, git-ignored; about
95 MB men, 60 MB women; --refresh re-downloads), parses every point with the MCP shot-code
grammar (oddsmarkets/tennis/sources/charting.py) and writes

    docs/ace/data/<tour>/style.json
    {"_meta": {licence, attribution, source, files, counts, unresolved names},
     pid: {"name", "hand", "matches", "points", "points_won",
           "serve": {first_in, first_won, second_won, ace_rate, df_rate, unret_rate, snv_rate, won,
                     direction: {first_deuce|first_ad|second_deuce|second_ad: {wide, body, t, n}}},
           "return": {won, depth: {shallow, mid, deep, n}, fh_share},
           "rally": {mean_len, dist: {"1-3","4-6","7-9","10+"}, won: {...}},
           "shots": {winners_per_pt, ue_per_pt, fh/bh_winners_per_pt, fh/bh_ue_per_pt,
                     induced_fe_per_pt, fh_share, winner_ue_ratio},
           "net": {rate, won, n}, "aggression"}}

Players are matched to registry pids by full name (no new registry entries); charted players the
registry does not know (pre-2000 careers, juniors, challengers) are keyed "x:<slug>" and flagged
"linked": false. Consumers skip keys starting with "_".

    python scripts/tn_charting.py --tour atp
    python scripts/tn_charting.py --tour wta --refresh --min-points 200
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.tennis import canon  # noqa: E402
from oddsmarkets.tennis.sources import charting  # noqa: E402
from oddsmarkets.tennis.sources._client import Client  # noqa: E402

logger = logging.getLogger("tn_charting")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tour", choices=canon.TOURS, required=True)
    ap.add_argument("--refresh", action="store_true", help="download the files again")
    ap.add_argument("--min-points", type=int, default=0, help="drop players with fewer charted points")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--save-registry", action="store_true",
                    help="write charting aliases and hands into the registry (not while a backfill of the tour runs)")
    args = ap.parse_args()
    log = ROOT / "logs" / f"tn_charting_{args.tour}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(log, encoding="utf-8")])
    t0 = time.monotonic()
    c = Client(budget=20, interval=args.interval, name="charting")
    paths = charting.download(c, args.tour, refresh=args.refresh)
    logger.info("charting %s files: %s (%s)", args.tour, {k: v.stat().st_size for k, v in paths.items()}, c.report())
    reg = canon.Registry.load(args.tour)
    unlinked = set()

    def resolve(name: str, hand: str | None) -> str:
        pid = reg.find("charting", name, hand)
        if pid:
            return pid
        unlinked.add(name)
        return "x:" + canon.slug(name)

    table, info = charting.build_style(args.tour, paths, resolve, min_points=args.min_points)
    for pid, row in table.items():
        row["linked"] = row["name"] not in unlinked
    rep = reg.report().get("charting", {})
    meta = {**charting.LICENSE, "tour": args.tour, "updated_at": canon.now(),
            "files": {k: v.name for k, v in paths.items()}, "points": info["points"], "unparsed_points": info["unparsed"],
            "matches": info["matches_with_points"], "matches_listed": info["matches_file"], "dates": info["dates"],
            "players": len(table), "players_linked": sum(1 for r in table.values() if r["linked"]),
            "identity": {k: v for k, v in rep.items() if k != "unresolved_examples"},
            "unlinked_examples": sorted(unlinked)[:60],
            "metrics_doc": "rates per point played by the player unless named otherwise; serve direction shares by court "
                           "side and serve (first/second); aggression = (winners + unforced errors) / shots hit; "
                           "unret_rate = aces + unreturnables + return errors per service point"}
    out = {"_meta": meta}
    out.update(dict(sorted(table.items(), key=lambda kv: -kv[1]["points"])))
    p = canon.data_root() / args.tour / "style.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if reg.dirty and args.save_registry:
        reg.save()
    logger.info("charting %s: %d points (%d unparsed) in %d matches %s; %d players (%d linked to the registry); "
                "wrote %s (%.0f KB) in %.0f s", args.tour, info["points"], info["unparsed"], info["matches_with_points"],
                info["dates"], len(table), meta["players_linked"], p, p.stat().st_size / 1024, time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
