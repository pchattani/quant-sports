#!/usr/bin/env python
"""
Fill The Quant Hardwood's season stores from ESPN, resumably.

Phases, per season, newest season first (so the current season is usable first):
  schedule   the season's game days come from ESPN's scoreboard calendar (1 call), then one
             scoreboard per game day (NBA about 230, WNBA about 140) gives every game's
             skeleton (teams, date, status, scores, line score); plus one standings call for
             conferences and divisions
  games      one summary per finished game (box score, odds, series, venue, play-by-play):
             the GAME record goes into store.json, the compact play-by-play to
             data/basketball/pbp/<league>/<season>/<id>.json.gz (git-ignored)

Games already fetched as final are skipped, and so are days already scanned in past
seasons, so a stopped run picks up where it left off. `--refresh-current` re-scans the
current season's days from two days ago to a week ahead, refetches games that finished in
the last two days (late stat corrections) and fetches summaries for games in the next 36
hours (lines and injuries; every change of a game's pre-game injury list is appended, with the fetch
time, to <season>/injury_log.json.gz), for the hourly job; it also reads the current rosters (one call per
team, at most every 20 hours) for players' dates of birth and positions (`--rosters` forces it).

    python scripts/bb_fetch.py --league nba --from 1997 --to 2027 --budget 60000
    python scripts/bb_fetch.py --league wnba --from 2026 --to 2026 --budget 400
    python scripts/bb_fetch.py --league nba --refresh-current --budget 300
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.basketball import canon  # noqa: E402
from oddsmarkets.basketball import store as st  # noqa: E402
from oddsmarkets.basketball.sources import espn  # noqa: E402

logger = logging.getLogger("bb_fetch")
PHASES = ("schedule", "games")


def _day(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _probe_day(league: str, season: int) -> str:
    """A day inside the season, used to read the season's calendar."""
    return f"{season}0715" if league == "wnba" else f"{season}0115"


def _add_event_teams(s: dict, ev: dict) -> None:
    for tid, rec in espn.teams_from_event(ev).items():
        old = s["teams"].get(tid) or {}
        rec["conference"], rec["division"] = old.get("conference"), old.get("division")
        s["teams"][tid] = {**old, **{k: v for k, v in rec.items() if v is not None or k not in old}}


def schedule(c: espn.Client, league: str, s: dict, refresh: bool, today: date) -> None:
    meta = s["meta"]
    season = s["season"]
    current = season == canon.current_season(league, today)
    scanned = meta.setdefault("days", {})
    cal = meta.get("calendar") or []
    if not cal or current:
        probe = _probe_day(league, season)
        raw = espn.scoreboard_raw(c, league, probe)
        if raw is None:
            logger.warning("%s %d: no scoreboard for %s", league, season, probe)
            return
        cal = espn.calendar(raw)
        if not cal:
            lo, hi = canon.season_window(league, season)
            cal = [(lo + timedelta(days=i)).strftime("%Y%m%d") for i in range((hi - lo).days + 1)]
            logger.info("%s %d: no calendar; scanning the %d-day window", league, season, len(cal))
        meta["calendar"] = cal
        if probe in cal:
            for ev in raw.get("events") or []:
                _take_event(s, ev)
            scanned[probe] = st.now()
    lo_refresh, hi_refresh = today - timedelta(days=2), today + timedelta(days=7)
    todo = []
    for d in cal:
        dd = _day(d)
        if d not in scanned:
            todo.append(d)
        elif current and (refresh or not meta.get("complete_through")) and lo_refresh <= dd <= hi_refresh:
            todo.append(d)
    for d in sorted(set(todo), reverse=True):
        raw = espn.scoreboard_raw(c, league, d)
        if raw is None:
            continue
        for ev in raw.get("events") or []:
            _take_event(s, ev)
        scanned[d] = st.now()
    if not any(t.get("conference") for t in s["teams"].values()) or (current and refresh and today.weekday() == 0):
        groups = espn.standings(c, league, season)
        for tid, g in groups.items():
            if tid in s["teams"]:
                s["teams"][tid].update(g)
    logger.info("%s %d schedule: %d games on %d days (%d scoreboards this run, %d calls used)",
                league, season, len(s["games"]), len(cal), len(todo), c.used)


def _keep_event(league: str, season: int, g: dict) -> bool:
    """False for scoreboard events that do not belong in the season's store: games dated outside the
    season's window (ESPN's calendar for NBA 2000 also covered the 1999 season) and 0-0 "finals",
    ESPN placeholders without a box score (NBA 1999-2002 carry dozens, mostly duplicates of real games)."""
    try:
        tip = datetime.fromisoformat(str(g.get("date") or "").replace("Z", "+00:00"))
    except ValueError:
        return True
    lo, hi = canon.season_window(league, season)
    if not lo <= (tip - timedelta(hours=6)).date() <= hi:     # US calendar day, as models/_games.local_day
        return False
    if g.get("status") == "post" and g.get("hs") == 0 and g.get("as") == 0:
        return False
    return True


def _take_event(s: dict, ev: dict) -> None:
    g = espn.compact_event(ev)
    if not g["home"] or not g["away"]:
        return
    if g["stype"] == "allstar":          # exhibition teams with their own ids: kept out of the season
        return
    if not _keep_event(s["league"], s["season"], g):
        return
    st.merge_game(s, g)
    _add_event_teams(s, ev)


def _merge_players(s: dict, raw: dict) -> None:
    for pid, p in espn.players_from_summary(raw).items():
        old = s["players"].get(pid)
        if not old:
            s["players"][pid] = {k: v for k, v in p.items() if k != "id"}
            continue
        for k in ("name", "short", "pos", "pool", "jersey"):
            if p.get(k):
                old[k] = p[k]
        for t in p.get("teams") or []:
            if t not in old.setdefault("teams", []):
                old["teams"].append(t)


def games(c: espn.Client, league: str, s: dict, refresh: bool, now: datetime) -> None:
    season = s["season"]
    current = season == canon.current_season(league, now.date())
    todo = []
    for gid, g in s["games"].items():
        when = datetime.fromisoformat(str(g.get("date") or "1900-01-01T00:00:00Z").replace("Z", "+00:00"))
        age_h = (now - when).total_seconds() / 3600
        final_fetched = st.fetched(s, gid) and g.get("status") == "post" and bool(g.get("box"))
        if g.get("status") in ("postponed", "canceled"):
            continue
        if g.get("status") == "post" and not final_fetched:
            todo.append((gid, g))
        elif g.get("status") == "post" and refresh and current and age_h < 48:
            fetched_at = s["meta"]["fetched"].get(gid) or ""
            if fetched_at < (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"):
                todo.append((gid, g))
        elif g.get("status") == "in" and age_h > 0:
            todo.append((gid, g))
        elif refresh and current and g.get("status") == "pre" and -36 < age_h <= 0:
            todo.append((gid, g))
    todo.sort(key=lambda kv: kv[1].get("date") or "", reverse=True)
    n_pbp = 0
    inj_log = st.load_injury_log(league, season) if current else None
    n_inj = 0
    t0 = time.monotonic()
    for k, (gid, g) in enumerate(todo, 1):
        raw = espn.summary(c, league, gid)
        if raw is None:
            continue
        rec = espn.compact_game(raw)
        if rec.get("stype") == "allstar":
            s["games"].pop(gid, None)
            continue
        st.merge_game(s, rec)
        if inj_log is not None and rec.get("status") == "pre":
            # timestamped pre-game injury history (ESPN keeps none): every change, stamped with this fetch
            n_inj += st.append_injury_log(inj_log, gid, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                          espn.summary_injury_rows(raw))
        for tid, trec in espn.teams_from_summary(raw).items():
            old = s["teams"].setdefault(tid, trec)
            for kk, v in trec.items():
                if v is not None and kk not in ("conference", "division"):
                    old[kk] = v
        _merge_players(s, raw)
        if rec.get("has_pbp"):
            pb = espn.compact_pbp(raw)
            if pb:
                st.save_pbp(league, season, pb)
                n_pbp += 1
        if rec.get("status") == "post":
            st.mark(s, gid)
        if k % 25 == 0:
            _complete_through(s)
            st.save(s)
            rate = (time.monotonic() - t0) / k
            logger.info("%s %d games: %d/%d (%d with pbp), %.2f s a game, %d calls used",
                        league, season, k, len(todo), n_pbp, rate, c.used)
    _complete_through(s)
    if n_inj:
        st.save_injury_log(league, season, inj_log)
        logger.info("%s %d injury log: %d new snapshot(s)", league, season, n_inj)
    logger.info("%s %d games: %d summaries this run (%d with pbp), %d calls used", league, season, len(todo), n_pbp, c.used)


ROSTER_EVERY_H = 20


def rosters(c: espn.Client, league: str, s: dict, now: datetime, force: bool = False) -> int:
    """Current rosters (one call per team, at most every ROSTER_EVERY_H hours): fills players' date of birth,
    position and team list. ESPN's roster endpoint is today's roster only, so this runs for the current season."""
    last = (s.get("meta") or {}).get("rosters_at") or ""
    if not force and last >= (now - timedelta(hours=ROSTER_EVERY_H)).strftime("%Y-%m-%dT%H:%M:%SZ"):
        return 0
    teams = [t for t, v in (s.get("teams") or {}).items() if (v or {}).get("conference") and str(v.get("abbr") or "").upper() != "TBD"]
    n = 0
    by_team: dict[str, list[str]] = {}
    for tid in teams:
        roster = espn.roster(c, league, tid)
        if roster:
            by_team[tid] = [str(p["id"]) for p in roster]
        for p in roster:
            pid = p.pop("id")
            old = s["players"].get(pid)
            if not old:
                s["players"][pid] = p
            else:
                for k in ("name", "short", "pos", "pool", "jersey", "dob"):
                    if p.get(k):
                        old[k] = p[k]
                for t in p.get("teams") or []:
                    if t not in old.setdefault("teams", []):
                        old["teams"].append(t)
            n += 1
    s["meta"]["rosters_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    # today's roster per team (the preseason prior's roster impact reads it; a player's `teams` list
    # cannot tell a summer move from last season's team)
    s["meta"]["rosters"] = {**(s["meta"].get("rosters") or {}), **by_team}
    logger.info("%s %d rosters: %d players from %d teams (%d calls used)", league, s["season"], n, len(teams), c.used)
    return n


def _complete_through(s: dict) -> None:
    """The last date through which every game is final and fetched (or postponed/canceled)."""
    last = None
    for gid, g in sorted(s["games"].items(), key=lambda kv: kv[1].get("date") or ""):
        if g.get("status") in ("postponed", "canceled"):
            continue
        if g.get("status") == "post" and st.fetched(s, gid):
            last = (g.get("date") or "")[:10]
        else:
            break
    s["meta"]["complete_through"] = last


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=canon.LEAGUES, required=True)
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--phases", default=",".join(PHASES))
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between calls (0.5 = 2 a second)")
    ap.add_argument("--refresh-current", action="store_true", help="hourly mode for the current season")
    ap.add_argument("--rosters", action="store_true",
                    help="current rosters (dates of birth, positions); implied daily by --refresh-current")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    league = args.league
    now = datetime.now(timezone.utc)
    current = canon.current_season(league, now.date())
    end = args.end or current
    start = args.start or end
    seasons = list(range(end, start - 1, -1))
    if args.refresh_current:
        seasons = [current]
    phases = [x for x in args.phases.split(",") if x in PHASES]
    c = espn.Client(budget=args.budget, interval=args.interval)
    t0 = time.monotonic()
    try:
        for season in seasons:
            s = st.load(league, season)
            refresh = args.refresh_current and season == current
            used0 = c.used
            try:
                if "schedule" in phases:
                    schedule(c, league, s, refresh, now.date())
                    st.save(s)
                if "games" in phases:
                    games(c, league, s, refresh, now)
                if (refresh or args.rosters) and season == current:
                    rosters(c, league, s, now, force=args.rosters)
            finally:
                if s["games"]:
                    st.save(s)
            logger.info("%s %d done: %d games, %d fetched final, %d calls this season (%d total)",
                        league, season, len(s["games"]), len(s["meta"]["fetched"]), c.used - used0, c.used)
    except espn.BudgetExhausted as exc:
        logger.info("%s", exc)
    el = time.monotonic() - t0
    logger.info("calls used: %d in %.0f s (%.2f s a call; %.0f s waiting on ESPN; %d failures)",
                c.used, el, el / max(1, c.used), c.seconds, c.failures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
