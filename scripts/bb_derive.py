#!/usr/bin/env python
"""
Derive the committed model inputs from the raw play-by-play, per league and season:

  docs/hardwood/data/<league>/<season>/shots.json    {"cols": SHOT_COLS, "rows": [...]}
  docs/hardwood/data/<league>/<season>/stints.json   {"cols": STINT_COLS, "rows": [...]}
  docs/hardwood/data/<league>/<season>/recon.json    per-game reconciliation and a season summary

shots.json and stints.json are also written gzipped beside the plain files (shots.json.gz,
stints.json.gz): completed seasons commit only those (see scripts/bb_pack.py and .gitignore),
and every loader reads the .gz when the plain file is absent or older.

Only games whose fetch stamp (store meta.fetched) or the derivation version changed are
re-parsed; the rows of every other game are kept, including games whose raw play-by-play
is not on this machine (CI holds only the current season's raw files), so history never
drops out. A season whose inputs are all unchanged is not rewritten.

    python scripts/bb_derive.py --league wnba --from 2026 --to 2026
    python scripts/bb_derive.py --league nba --from 2017 --to 2027 --force
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.basketball import canon  # noqa: E402
from oddsmarkets.basketball import pbp as pb  # noqa: E402
from oddsmarkets.basketball import store as st  # noqa: E402

logger = logging.getLogger("bb_derive")
VERSION = 1


def _table(obj, cols) -> list[list]:
    if isinstance(obj, dict) and obj.get("cols") == cols:
        return obj.get("rows") or []
    return []


def derive_season(league: str, season: int, force: bool = False) -> dict | None:
    s = st.load(league, season)
    if not s["games"]:
        return None
    shots_old = _table(st.load_table(league, season, "shots.json"), pb.SHOT_COLS)
    stints_old = _table(st.load_table(league, season, "stints.json"), pb.STINT_COLS)
    recon_old = st.load_table(league, season, "recon.json") or {}
    games_old = recon_old.get("games") or {} if recon_old.get("version") == VERSION else {}
    shots_by: dict[str, list] = {}
    for r in shots_old:
        shots_by.setdefault(str(r[0]), []).append(r)
    stints_by: dict[str, list] = {}
    for r in stints_old:
        stints_by.setdefault(str(r[0]), []).append(r)
    recon: dict[str, dict] = {}
    changed = 0
    missing = 0
    for gid, g in s["games"].items():
        if g.get("status") != "post" or not g.get("has_pbp"):
            continue
        sig = s["meta"]["fetched"].get(gid)
        old = games_old.get(gid)
        if old and old.get("sig") == sig and not force and (gid in shots_by or gid in stints_by):
            recon[gid] = old
            continue
        raw = st.load_pbp(league, season, gid)
        if raw is None:
            if old:                                  # keep what an earlier machine derived
                recon[gid] = old
            else:
                missing += 1
            continue
        try:
            d = pb.derive(raw, g, league, season)
        except Exception as exc:                     # one bad game never stops the season
            logger.warning("%s %d game %s: %s", league, season, gid, exc)
            recon[gid] = {"sig": sig, "error": str(exc)[:200]}
            shots_by.pop(gid, None)
            stints_by.pop(gid, None)
            changed += 1
            continue
        shots_by[gid] = d["shots"]
        stints_by[gid] = d["stints"]
        recon[gid] = {**d["recon"], "sig": sig}
        changed += 1
    dropped = set(games_old) - set(recon)
    if not changed and not dropped and not force and recon_old.get("version") == VERSION:
        logger.info("%s %d: unchanged (%d games)", league, season, len(recon))
        return recon_old.get("summary")
    order = [gid for gid in s["games"] if gid in recon]
    shot_rows = [r for gid in order for r in shots_by.get(gid, [])]
    stint_rows = [r for gid in order for r in stints_by.get(gid, [])]
    summary = _summary(recon, s, missing)
    for name, obj in (("shots.json", {"cols": pb.SHOT_COLS, "rows": shot_rows}), ("stints.json", {"cols": pb.STINT_COLS, "rows": stint_rows})):
        st.save_table(league, season, name, obj)
        st.save_table_gz(league, season, name, obj)       # completed seasons commit only the .gz (scripts/bb_pack.py)
    st.save_table(league, season, "recon.json", {"version": VERSION, "league": league, "season": season, "updated_at": st.now(),
                                                 "summary": summary, "games": {gid: recon[gid] for gid in order}})
    logger.info("%s %d: %d games re-derived; %d shots, %d stints; %s", league, season, changed, len(shot_rows), len(stint_rows), summary)
    return summary


def _summary(recon: dict[str, dict], s: dict, missing: int) -> dict:
    ok = [r for r in recon.values() if "error" not in r]
    n = len(ok)
    final = sum(1 for g in s["games"].values() if g.get("status") == "post" and g.get("stype") != "allstar")
    with_pbp = sum(1 for g in s["games"].values() if g.get("status") == "post" and g.get("has_pbp"))
    pos = [abs(r["poss"][0] - r["poss"][1]) for r in ok if r.get("poss")]
    agree = [r["three_agree"] for r in ok if r.get("three_agree") is not None]
    errs = sorted(r["max_err_s"] for r in ok)
    return {
        "games_final": final, "games_pbp": with_pbp, "derived": n, "errors": len(recon) - n, "raw_missing": missing,
        "share_all_within_60s": round(sum(1 for r in ok if r["ok"]) / n, 4) if n else None,
        "share_points_exact": round(sum(1 for r in ok if r["points_ok"]) / n, 4) if n else None,
        "share_poss_within_2": round(sum(1 for d in pos if d <= 2) / len(pos), 4) if pos else None,
        "median_max_err_s": errs[n // 2] if n else None, "p95_max_err_s": errs[min(n - 1, int(0.95 * n))] if n else None,
        "three_agree_mean": round(sum(agree) / len(agree), 4) if agree else None,
        "lineup_fixes_mean": round(sum(r.get("fixes", 0) for r in ok) / n, 2) if n else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=canon.LEAGUES, required=True)
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="re-derive every game")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    end = args.end or canon.current_season(args.league)
    start = args.start or end
    t0 = time.monotonic()
    for season in range(end, start - 1, -1):
        derive_season(args.league, season, args.force)
    logger.info("done in %.1f s", time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
