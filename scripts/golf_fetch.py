#!/usr/bin/env python
"""
Fetch golf seasons from ESPN into the store (oddsmarkets/golf/store.py).

Per tour and season: one season scoreboard (the event list; hole-by-hole on the PGA Tour), then one leaderboard for
every event not yet stored as final. Past seasons whose events are all final are skipped without a call; the
current season's scoreboard is fetched every run. A spent call budget stops cleanly and the next run resumes.

    python scripts/golf_fetch.py                              # every tour, its current season
    python scripts/golf_fetch.py --tours pga --seasons 2001-2026
    python scripts/golf_fetch.py --tours pga eur liv lpga --backfill
    python scripts/golf_fetch.py --stats --bios --budget 6000  # season statistics and bios still missing (6 Nov 2026)

Season statistics (--stats): one ESPN core call per player and season for the tours in canon.STATS_TOURS from
canon.STATS_FROM, for every player with STATS_MIN_ROUNDS rounds in the season; a past season's answer (or its 404) is
kept for good, the current season's is re-read after STATS_MAX_AGE_D days. Bios (--bios): one call per player with
BIO_MIN_ROUNDS rounds, kept for good. Both write under data/golf (stats/<tour>/<season>.json, bios.json).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from oddsmarkets.golf import canon, store  # noqa: E402
from oddsmarkets.golf.sources import espn  # noqa: E402

logger = logging.getLogger("golf_fetch")


def _seasons(spec: list[str] | None, tour: str, backfill: bool, today: date) -> list[int]:
    if backfill:
        return list(range(today.year, canon.TOURS[tour]["from"] - 1, -1))
    if not spec:
        return [today.year]
    out: list[int] = []
    for s in spec:
        if "-" in s:
            a, b = (int(x) for x in s.split("-", 1))
            out += list(range(max(a, b), min(a, b) - 1, -1))
        else:
            out.append(int(s))
    return out


def _season_stamp(tour: str, season: int) -> Path:
    return store.season_dir(tour, season) / "season_scoreboard_at.txt"


def fetch_season(c, tour: str, season: int, today: date, max_age_h: float = 0.0) -> dict:
    events = store.load_events(tour, season)
    current = season >= today.year
    if events and not current and all(e.get("status") in ("final", "canceled") for e in events.values()):
        return {"skipped": True}
    stamp = _season_stamp(tour, season)
    age_h = None
    if stamp.exists():
        try:
            age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(stamp.read_text().strip())).total_seconds() / 3600
        except ValueError:
            age_h = None
    week = bool(current and events and max_age_h and age_h is not None and age_h < max_age_h)
    if week:
        sb = espn.parse_scoreboard(espn.week_scoreboard(c, tour), tour)
        sb["events"] = [e for e in sb["events"] if e["id"] in events or (e.get("start") or "")[:4] == str(season)]
    else:
        sb = espn.parse_scoreboard(espn.season_scoreboard(c, tour, season), tour)
        if sb["events"]:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if not sb["events"]:
        logger.info("%s %s: no events", tour, season)
        return {"events": 0}
    players = store.load_players()
    for pid, p in sb["players"].items():
        players.setdefault(pid, {}).update({k: v for k, v in p.items() if v is not None and not players[pid].get(k)})
    due = [e for e in sb["events"] if (events.get(e["id"]) or {}).get("status") != "final" and e["status"] != "canceled"
           and (e["status"] != "upcoming" or (e["start"] or "") <= (today.isoformat()))]
    for e in sb["events"]:
        if e["status"] == "canceled" or (e["status"] == "upcoming" and e not in due):
            events[e["id"]] = {**events.get(e["id"], {}), **e}
    res, rnd = store.load_table(tour, season, "results"), store.load_table(tour, season, "rounds")
    holes = store.load_table(tour, season, "holes")
    new_res, new_rnd, done = [], [], set()
    spent = None
    for e in due:
        try:
            raw = espn.leaderboard(c, tour, e["id"])
        except espn.BudgetExhausted as exc:
            spent = exc
            break
        lb = espn.parse_leaderboard(raw, tour)
        if lb is None:
            logger.warning("%s %s: empty leaderboard for %s %s", tour, season, e["id"], e["name"])
            continue
        meta = {**e, **{k: v for k, v in lb["event"].items() if v is not None}}
        # the scoreboard's state is the event's; the leaderboard's can lag a day after the final round
        meta["status"] = e["status"] if e["status"] == "final" else meta.get("status")
        events[e["id"]] = meta
        for pid, p in lb["players"].items():
            players.setdefault(pid, {}).update({k: v for k, v in p.items() if v is not None})
        new_res += lb["results"]
        new_rnd += lb["rounds"]
        done.add(e["id"])
    if done:
        sb_r = pd.DataFrame(sb["rounds"])
        lb_r = pd.DataFrame(new_rnd)
        if len(lb_r) and len(sb_r):
            lb_r = lb_r.merge(sb_r[sb_r["event"].isin(done)][["event", "pid", "round", "holes"]], on=["event", "pid", "round"], how="left")
        res = store.replace_events(res, pd.DataFrame(new_res), done)
        rnd = store.replace_events(rnd, lb_r, done)
        sb_h = pd.DataFrame(sb["holes"])
        if len(sb_h):
            keep = {x for x in done if not events[x].get("team")}
            holes = store.replace_events(holes, sb_h[sb_h["event"].isin(keep)], done)
        store.save_table(tour, season, "results", res)
        store.save_table(tour, season, "rounds", rnd)
        if len(holes):
            store.save_table(tour, season, "holes", holes)
    store.save_events(tour, season, events)
    store.save_players(players)
    logger.info("%s %s: %d events, %d fetched now (%d players-results, %d rounds, %d holes in store)", tour, season,
                len(sb["events"]), len(done), len(res), len(rnd), len(holes))
    if spent is not None:
        raise spent
    return {"events": len(sb["events"]), "fetched": len(done)}


STATS_MIN_ROUNDS = 8
STATS_MAX_AGE_D = 7
BIO_MIN_ROUNDS = 20


def fetch_stats(c, tour: str, season: int, today: date) -> int:
    """Season statistics of the season's regulars still missing (or stale in the current season). Returns calls made."""
    rnd = store.load_table(tour, season, "rounds")
    if not len(rnd):
        return 0
    cnt = rnd.groupby("pid").size()
    pids = sorted(cnt[cnt >= STATS_MIN_ROUNDS].index.astype(str))
    have = store.load_stats(tour, season)
    now = datetime.now(timezone.utc)

    def due(pid: str) -> bool:
        x = have.get(pid)
        if x is None:
            return True
        if season < today.year:
            return False
        try:
            return (now - datetime.fromisoformat(x.get("_at"))).days >= STATS_MAX_AGE_D
        except (TypeError, ValueError):
            return True
    todo = [p for p in pids if due(p)]
    n = 0
    try:
        for pid in todo:
            row = espn.parse_stats(espn.season_stats(c, tour, season, pid))
            row["_at"] = now.isoformat(timespec="seconds")
            have[pid] = row
            n += 1
            if n % 50 == 0:
                store.save_stats(tour, season, have)
    finally:
        if n:
            store.save_stats(tour, season, have)
            logger.info("%s %s stats: %d fetched, %d of %d regulars on file", tour, season, n, len(have), len(pids))
    return n


def fetch_bios(c, today: date) -> int:
    """Bios of every player with BIO_MIN_ROUNDS rounds, not yet on file (a 404 is kept as {} and not asked again)."""
    from collections import Counter
    rounds: Counter = Counter()
    tour_of: dict = {}
    for tour in canon.TOURS:
        for season in store.seasons(tour):
            r = store.load_table(tour, season, "rounds")
            if len(r):
                vc = r["pid"].astype(str).value_counts()
                for pid, k in vc.items():
                    rounds[pid] += int(k)
                    tour_of.setdefault(pid, Counter())[tour] += int(k)
    bios = store.load_bios()
    todo = sorted((p for p, k in rounds.items() if k >= BIO_MIN_ROUNDS and p not in bios), key=lambda p: -rounds[p])
    n = 0
    try:
        for pid in todo:
            tours = [t for t, _ in tour_of[pid].most_common()]
            row: dict = {}
            for t in tours[:2]:
                row = espn.parse_athlete(espn.athlete(c, t, pid))
                n += 1
                if row:
                    break
            bios[pid] = row
            if n % 50 == 0:
                store.save_bios(bios)
    finally:
        if n:
            store.save_bios(bios)
            logger.info("bios: %d calls, %d players on file", n, len(bios))
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tours", nargs="*", default=list(canon.TOURS), choices=list(canon.TOURS))
    ap.add_argument("--seasons", nargs="*", help="years or ranges (2001-2026); default the current season")
    ap.add_argument("--backfill", action="store_true", help="every season ESPN carries for the tour, newest first")
    ap.add_argument("--budget", type=int, default=3000, help="ESPN calls this run (default 3000)")
    ap.add_argument("--today", default=None)
    ap.add_argument("--max-age-h", type=float, default=0.0,
                    help="re-read the current season's full scoreboard only when the last read is older than this; "
                         "between, this week's scoreboard only (0: always the full season)")
    ap.add_argument("--stats", action="store_true", help="season statistics still missing (canon.STATS_TOURS)")
    ap.add_argument("--bios", action="store_true", help="player bios still missing")
    ap.add_argument("--only-extras", action="store_true", help="with --stats/--bios: skip the scoreboards")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    today = date.fromisoformat(a.today) if a.today else date.today()
    c = espn.client(budget=a.budget)
    try:
        if not a.only_extras:
            for tour in a.tours:
                for season in _seasons(a.seasons, tour, a.backfill, today):
                    fetch_season(c, tour, season, today, a.max_age_h)
        if a.stats:
            for tour in canon.STATS_TOURS:
                for season in range(today.year, canon.STATS_FROM - 1, -1):
                    fetch_stats(c, tour, season, today)
        if a.bios:
            fetch_bios(c, today)
    except espn.BudgetExhausted as exc:
        logger.warning("%s; the next run resumes", exc)
    logger.info("calls: %s", c.report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
