#!/usr/bin/env python
"""
Fill The Quant Bullpen's season stores and Statcast pitch tables, resumably, newest season first.

Phases, per season (CONTRACT.md section 1):
  schedule   the Stats API schedule in week windows (hydrated: probables, line score, weather, umpires,
             lineups, decisions; ~35 calls a season), the season's teams (1 call) and venues (1-2 calls).
             A week is rescanned until it has been read two days after its last date.
  statcast   Baseball Savant pitch by pitch for every day with a final game: one request per day (or
             --chunk-days), 3 s apart, re-split when an answer hits the silent 25,000-row cap; one Parquet
             part per day, compacted into data/baseball/statcast/<level>/<season>.parquet at the end of the
             season's pass. Days already fetched (and settled) are skipped.
  games      the live feed (trimmed with `fields`, ~10 KB) for final games from the ABS season on (ABS
             challenges, mound visits, batting order) and for games without a lineup; live games in
             --refresh-current read the full feed into the git-ignored cache.
  espn       (MLB) one ESPN scoreboard per game day maps ESPN events to gamePks; one core odds call per game
             gives the lines (moneyline, run line, total; open/close; every book). Lines fetched before a
             game started are read again once it is final (closing line).
  people     every player in the store (lineups, probables, decisions) and in the season's pitch table, from
             /people (150 per call), enriched with Retrosheet / bbref / FanGraphs ids from the Chadwick
             register (people.json, rebuilt when older than 30 days).

--refresh-current (the scheduled job) rescans the current season from three days ago to a week ahead,
re-pulls Savant for yesterday and today, refreshes lines for upcoming and just-finished games, and reads
standings, 40-man rosters, injured lists and the last two weeks of transactions.

    python scripts/mlb_fetch.py --level mlb --from 2026 --to 2026 --budget 20000
    python scripts/mlb_fetch.py --level mlb --from 2015 --to 2025 --phases statcast --log logs/mlb_backfill_savant.log
    python scripts/mlb_fetch.py --level aaa --from 2023 --to 2026 --phases schedule,statcast
    python scripts/mlb_fetch.py --level mlb --refresh-current --budget 600
    python scripts/mlb_fetch.py --level mlb --report --from 2015 --to 2026
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

import pandas as pd  # noqa: E402

from oddsmarkets.baseball import canon  # noqa: E402
from oddsmarkets.baseball import store as st  # noqa: E402
from oddsmarkets.baseball.sources import chadwick, espn, savant, statsapi  # noqa: E402
from oddsmarkets.baseball.sources._client import BudgetExhausted, Client  # noqa: E402

logger = logging.getLogger("mlb_fetch")
PHASES = ("schedule", "statcast", "games", "espn", "people")
ABS_FROM = {"mlb": 2026, "aaa": 2024}


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── schedule ────────────────────────────────────────────────────────────────

def schedule(c: Client, level: str, s: dict, refresh: bool, today: date) -> None:
    season = s["season"]
    current = season == canon.current_season(today)
    lo, hi = canon.season_window(season)
    if current:
        hi = min(hi, today + timedelta(days=10))
    weeks_done = s["meta"].setdefault("weeks", {})
    n_calls = 0
    for a, b in statsapi.weeks(lo, hi):
        key = a.isoformat()
        at = weeks_done.get(key)
        settled = at and _d(at) > b + timedelta(days=2)
        hot = current and refresh and b >= today - timedelta(days=3) and a <= today + timedelta(days=7)
        if settled and not hot:
            continue
        games = statsapi.schedule(c, level, a, b)
        n_calls += 1
        if games is None:
            continue
        for g in games:
            if statsapi.take_game(s, g, st.merge_game):
                for tid, t in statsapi.team_refs(g).items():
                    if tid not in s["teams"]:
                        s["teams"][tid] = statsapi.team_record(t, level, season)
                        if level == "mlb" and tid not in canon.TEAMS:      # "NL Higher Seed", "ATL/PHI" ...
                            s["teams"][tid]["placeholder"] = True
        weeks_done[key] = st.now()
    # teams of the season (names, divisions, venues) once, weekly for the current season
    t_at = s["meta"].get("teams_at")
    if not t_at or (current and (today - _d(t_at)).days >= 7) or len(s["teams"]) < (30 if level == "mlb" else 28):
        for t in statsapi.teams(c, level, season):
            rec = statsapi.team_record(t, level, season)
            old = s["teams"].get(str(t["id"])) or {}
            s["teams"][str(t["id"])] = {**old, **{k: v for k, v in rec.items() if v is not None}}
        s["meta"]["teams_at"] = st.now()
    need = {g.get("venue") for g in s["games"].values()} | {t.get("venue") for t in s["teams"].values()}
    need = {v for v in need if v and v not in s["venues"]}
    if need:
        s["venues"].update(statsapi.venues(c, need, season))
    s["meta"]["complete_through"] = st.complete_through(s)
    logger.info("%s %d schedule: %d games (%d final), %d teams, %d venues; %d schedule calls",
                level, season, len(s["games"]), sum(1 for g in s["games"].values() if g.get("status") == "final"),
                len(s["teams"]), len(s["venues"]), n_calls)


def current_extras(c: Client, level: str, s: dict, today: date) -> None:
    """Standings, 40-man rosters, injured lists and recent transactions (current season, refresh mode)."""
    season = s["season"]
    s["meta"]["standings"] = statsapi.standings(c, season, level)
    last = s["meta"].get("rosters_at")
    if not last or (datetime.now(timezone.utc) - _iso_dt(last)).total_seconds() > 20 * 3600:
        ros = {}
        for tid in sorted(s["teams"]):
            forty, inj = statsapi.roster(c, tid, "40Man", season), statsapi.roster(c, tid, "injured", season)
            # names and positions too: a 40-man player without a game this season is in no other table, and the team
            # page would otherwise show their MLBAM id
            ros[tid] = {"40man": [r["pid"] for r in forty], "injured": [[r["pid"], r["status"], r["note"]] for r in inj],
                        "names": {r["pid"]: r["name"] for r in forty + inj if r.get("pid") and r.get("name")},
                        "pos": {r["pid"]: r["pos"] for r in forty + inj if r.get("pid") and r.get("pos")}}
        s["meta"]["rosters"] = ros
        s["meta"]["rosters_at"] = st.now()
    tx = statsapi.transactions(c, today - timedelta(days=14), today, level)
    st.write_json(st.cache_root() / "statsapi" / f"transactions_{level}_{season}.json", tx)
    logger.info("%s %d extras: standings %d teams, rosters %d teams, %d transactions",
                level, season, len(s["meta"]["standings"]), len(s["meta"].get("rosters") or {}), len(tx))


# ── statcast ────────────────────────────────────────────────────────────────

def _settled(day: str, at: str | None) -> bool:
    """A Savant day is settled when it was fetched after noon UTC of the following day."""
    if not at:
        return False
    return at >= (_d(day) + timedelta(days=1)).isoformat() + "T12:00:00Z"


def statcast(c: Client, level: str, s: dict, refresh: bool, today: date, chunk_days: int = 1) -> None:
    season = s["season"]
    if season < canon.STATCAST_FROM[level]:
        return
    m = savant.load_manifest(level, season)
    days = sorted({g["date"] for g in s["games"].values()
                   if g.get("status") in ("final", "live") and g.get("gtype") in canon.SEASON_TYPES and g.get("date")})
    if not s["games"]:
        lo, hi = canon.season_window(season)
        hi = min(hi, today)
        days = [(lo + timedelta(days=k)).isoformat() for k in range((hi - lo).days + 1)]
    todo = [d for d in days if not _settled(d, (m["days"].get(d) or {}).get("at"))]
    if refresh:
        todo = sorted(set(todo) | {d for d in days if _d(d) >= today - timedelta(days=1)})
    todo = sorted(todo, reverse=True)
    if not todo:
        logger.info("%s %d statcast: nothing to fetch (%d days on file)", level, season, len(m["days"]))
        _mark_statcast(s, m)
        return
    teams = [t.get("abbr") for t in s["teams"].values() if t.get("abbr")]
    chunks: list[tuple[date, date]] = []
    k = 0
    while k < len(todo):
        hi_d = _d(todo[k])
        lo_d = hi_d
        j = k + 1
        while j < len(todo) and (hi_d - _d(todo[j])).days < chunk_days and _d(todo[j]) == lo_d - timedelta(days=1):
            lo_d = _d(todo[j])
            j += 1
        chunks.append((lo_d, hi_d))
        k = j
    t0 = time.monotonic()
    rows_run = 0
    for n, (lo_d, hi_d) in enumerate(chunks, 1):
        frames = savant.fetch_range(c, level, lo_d, hi_d, teams=teams, capped=m["capped"])
        if frames is None:
            logger.warning("%s %s..%s: Savant request failed; will retry next run", level, lo_d, hi_d)
            continue
        raw = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
        df = savant.typed(raw)
        del raw, frames
        dates = df["game_date"].dt.strftime("%Y-%m-%d") if len(df) else pd.Series([], dtype=str)
        d = lo_d
        while d <= hi_d:
            ds = d.isoformat()
            part = df[dates == ds] if len(df) else df
            savant.write_day(level, season, ds, part)
            m["days"][ds] = {"rows": int(len(part)), "games": sorted({int(x) for x in part["game_pk"].dropna()}) if len(part) else [],
                             "at": st.now()}
            rows_run += len(part)
            d += timedelta(days=1)
        del df
        if n % 10 == 0 or n == len(chunks):
            savant.save_manifest(m)
            el = time.monotonic() - t0
            logger.info("%s %d statcast: %d/%d requests, %d pitches this run, %.1f s a request, ETA %.0f min (%d calls)",
                        level, season, n, len(chunks), rows_run, el / n, el / n * (len(chunks) - n) / 60, c.used)
    info = savant.compact(level, season)
    m.update(rows=info["rows"], columns_present=info["columns_present"], compacted_at=st.now())
    savant.save_manifest(m)
    _mark_statcast(s, m)
    logger.info("%s %d statcast: season file %d pitches over %d days, %d columns with data, %d capped requests",
                level, season, info["rows"], info["days"], len(info["columns_present"]), len(m["capped"]))


def _mark_statcast(s: dict, m: dict) -> None:
    have = {str(g) for d in m["days"].values() for g in (d.get("games") or [])}
    for gpk, g in s["games"].items():
        if gpk in have:
            g["has_statcast"] = True


# ── games (live feed) ───────────────────────────────────────────────────────

def games(c: Client, level: str, s: dict, refresh: bool, now: datetime) -> None:
    season = s["season"]
    current = season == canon.current_season(now.date())
    todo = []
    for gpk, g in s["games"].items():
        if g.get("gtype") not in canon.SEASON_TYPES:
            continue
        stt = g.get("status")
        start = _iso_dt(g.get("start"))
        age_h = (now - start).total_seconds() / 3600 if start else 1e9
        if stt == "live" and refresh and current:
            todo.append((gpk, g, True))
        elif stt == "final" and not st.fetched(s, gpk, "feed"):
            if season >= ABS_FROM[level] or not g.get("lineups"):
                todo.append((gpk, g, False))
        elif stt == "final" and refresh and current and age_h < 36:
            at = (s["meta"].get("feed") or {}).get(gpk) or ""
            if at < (start + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"):
                todo.append((gpk, g, False))
    todo.sort(key=lambda x: x[1].get("start") or "", reverse=True)
    t0 = time.monotonic()
    for k, (gpk, g, full) in enumerate(todo, 1):
        f = statsapi.feed(c, gpk, full=full)
        if f is None:
            continue
        if full:
            st.write_json_gz(st.feed_path(level, season, gpk), f)
        ex = statsapi.feed_extras(f)
        rec = dict(g)
        for key, v in ex.items():
            if key == "lineups" and g.get("lineups"):
                continue
            rec[key] = v
        st.merge_game(s, rec)
        if g.get("status") == "final":
            st.mark(s, gpk, "feed")
        if k % 200 == 0:
            st.save_owned(s, ["games"])
            el = time.monotonic() - t0
            logger.info("%s %d games: %d/%d feeds, %.2f s a feed, ETA %.0f min", level, season, k, len(todo),
                        el / k, el / k * (len(todo) - k) / 60)
    logger.info("%s %d games: %d feeds this run (%d with ABS)", level, season, len(todo),
                sum(1 for g in s["games"].values() if g.get("abs")))


# ── ESPN lines ──────────────────────────────────────────────────────────────

def espn_lines(c: Client, level: str, s: dict, refresh: bool, now: datetime) -> None:
    if level != "mlb":
        return
    season = s["season"]
    current = season == canon.current_season(now.date())
    today = now.date()
    scanned = s["meta"].setdefault("espn_days", {})
    by_date: dict[str, dict[str, dict]] = {}
    for gpk, g in s["games"].items():
        if g.get("status") in ("cancelled",) or g.get("gtype") not in canon.SEASON_TYPES:
            continue
        by_date.setdefault(g.get("date"), {})[gpk] = g
    days = sorted(by_date, reverse=True)
    n_sb = 0
    for d in days:
        if not d:
            continue
        hot = current and refresh and today - timedelta(days=2) <= _d(d) <= today + timedelta(days=2)
        unmatched = any(not g.get("espn") for g in by_date[d].values() if g.get("status") != "postponed")
        if d in scanned and not hot and not unmatched:
            continue
        if d in scanned and unmatched and not hot and _d(scanned[d]) > _d(d) + timedelta(days=2):
            continue                                  # read after the day settled: what is unmatched stays so
        evs = espn.scoreboard(c, d.replace("-", ""))
        n_sb += 1
        if evs is None:
            continue
        near = {}
        for dd in (_d(d) - timedelta(days=1), _d(d), _d(d) + timedelta(days=1)):
            near.update(by_date.get(dd.isoformat(), {}))
        refs = [r for r in (espn.event_ref(e) for e in evs) if r]
        for eid, gpk in espn.match_events(refs, near).items():
            s["games"][gpk]["espn"] = eid
        scanned[d] = st.now()
    got = s["meta"].setdefault("espn_odds", {})
    todo = []
    for gpk, g in s["games"].items():
        eid = g.get("espn")
        if not eid or g.get("status") in ("postponed", "cancelled"):
            continue
        start = _iso_dt(g.get("start"))
        at = got.get(gpk)
        if g.get("status") == "final":
            pre_close = at and start and _iso_dt(at) < start + timedelta(hours=2)
            if not at or pre_close:
                todo.append(gpk)
        elif refresh and current and start and now - timedelta(hours=6) <= start <= now + timedelta(hours=36):
            todo.append(gpk)
    todo.sort(key=lambda x: s["games"][x].get("start") or "", reverse=True)
    t0 = time.monotonic()
    n_lines = 0
    for k, gpk in enumerate(todo, 1):
        raw = espn.odds(c, s["games"][gpk]["espn"])
        if raw is None:
            continue
        ln = espn.compact_lines(raw)
        if ln:
            s["games"][gpk]["lines"] = ln
            n_lines += 1
        got[gpk] = st.now()
        if k % 200 == 0:
            st.save_owned(s, ["espn"])
            el = time.monotonic() - t0
            logger.info("%s %d espn: %d/%d odds calls, %d with lines, ETA %.0f min", level, season, k, len(todo),
                        n_lines, el / k * (len(todo) - k) / 60)
    if refresh and current:
        wp_dir = st.cache_root() / "espn_wp" / str(season)
        for gpk, g in s["games"].items():
            start = _iso_dt(g.get("start"))
            if g.get("espn") and g.get("status") == "final" and start and now - start < timedelta(hours=36) \
                    and not (wp_dir / f"{gpk}.json").exists():
                sm = espn.summary(c, g["espn"])
                wp = espn.win_probability(sm)
                if wp:
                    st.write_json(wp_dir / f"{gpk}.json", wp)
    fin = [g for g in s["games"].values() if g.get("status") == "final" and g.get("gtype") in canon.SEASON_TYPES]
    logger.info("%s %d espn: %d scoreboards, %d odds calls, %d new lines; %d/%d final games mapped, %d with lines",
                level, season, n_sb, len(todo), n_lines, sum(1 for g in fin if g.get("espn")), len(fin),
                sum(1 for g in fin if g.get("lines")))


# ── people ──────────────────────────────────────────────────────────────────

_CHADWICK_DONE = False


def people(c: Client, level: str, s: dict, refresh: bool) -> None:
    global _CHADWICK_DONE
    season = s["season"]
    pp = st.people_path()
    if not _CHADWICK_DONE and (not pp.exists() or (time.time() - pp.stat().st_mtime) > chadwick.MAX_AGE_DAYS * 86400):
        info = chadwick.build(c)
        logger.info("chadwick: %s", info)
    _CHADWICK_DONE = True
    ids: set[str] = set()
    ump: set[str] = set()
    for g in s["games"].values():
        for lu in (g.get("lineups") or {}).values():
            ids.update(x for x in lu if x)
        ids.update(x for x in (g.get("probables") or {}).values() if x)
        ids.update(x for x in (g.get("decisions") or {}).values() if x)
        if g.get("umpire_hp"):
            ump.add(g["umpire_hp"])
    p = st.statcast_path(level, season)
    if p.exists():
        import pyarrow.parquet as pq
        t = pq.read_table(p, columns=["pitcher", "batter"])
        for col in ("pitcher", "batter"):
            ids.update(str(x) for x in pd.unique(t.column(col).drop_null().to_numpy()))
        del t
    todo = sorted(i for i in ids if i not in s["players"] or (refresh and not s["players"][i].get("pos")))
    if todo:
        s["players"].update(statsapi.people(c, todo))
    ut = sorted(u for u in ump if u not in s.setdefault("umpires", {}))
    if ut:
        for pid, rec in statsapi.people(c, ut).items():
            s["umpires"][pid] = {"name": rec.get("name")}
    hit, tot = chadwick.enrich_players(s["players"], chadwick.load_people(), chadwick.load_mlbam_index())
    with_retro = sum(1 for x in s["players"].values() if x.get("retro"))
    s["meta"]["crosswalk"] = {"players": tot, "in_register": hit, "with_retro": with_retro,
                              "with_bbref": sum(1 for x in s["players"].values() if x.get("bbref"))}
    logger.info("%s %d people: %d players (%d new), %d umpires; crosswalk %d/%d in register, %d with Retrosheet id",
                level, season, len(s["players"]), len(todo), len(s.get("umpires") or {}), hit, tot, with_retro)


# ── report ──────────────────────────────────────────────────────────────────

def report(level: str, seasons: list[int]) -> None:
    for season in sorted(seasons):
        s = st.load(level, season)
        fin = [g for g in s["games"].values() if g.get("status") == "final" and g.get("gtype") in canon.SEASON_TYPES]
        sm = savant.summary(level, season)
        m = savant.load_manifest(level, season)
        cw = s["meta"].get("crosswalk") or {}
        print(f"{level} {season}: games {len(s['games'])} ({len(fin)} final, "
              f"{sum(1 for g in fin if g.get('gtype') != 'R')} postseason); statcast {sm['rows']:,} pitches over "
              f"{sm['days']} days ({sum(1 for g in fin if g.get('has_statcast'))} games), {len(sm['columns_present'])} "
              f"columns with data, {sm['capped']} capped; lines {sum(1 for g in fin if g.get('lines'))}/{len(fin)}; "
              f"lineups {sum(1 for g in fin if g.get('lineups'))}; abs {sum(1 for g in fin if g.get('abs'))}; "
              f"players {len(s['players'])} (retro {cw.get('with_retro')}, bbref {cw.get('with_bbref')})")
        missing = [c_ for c_ in savant.COLUMNS if c_ not in set(m.get("columns_present") or [])]
        if m.get("columns_present"):
            print(f"    columns without data: {', '.join(missing)}")


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", choices=canon.LEVELS, default="mlb")
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--phases", default=",".join(PHASES))
    ap.add_argument("--budget", type=int, default=5000)
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between Stats API calls")
    ap.add_argument("--savant-interval", type=float, default=savant.INTERVAL)
    ap.add_argument("--espn-interval", type=float, default=espn.INTERVAL)
    ap.add_argument("--chunk-days", type=int, default=1, help="days per Savant request")
    ap.add_argument("--refresh-current", action="store_true", help="scheduled mode for the current season")
    ap.add_argument("--leaderboards", action="store_true", help="also cache the Savant leaderboards of each season")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    handlers = [logging.StreamHandler()]
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=handlers)
    level = args.level
    now = datetime.now(timezone.utc)
    current = canon.current_season(now.date())
    end = args.end or current
    start = args.start or end
    seasons = list(range(end, start - 1, -1))
    if args.refresh_current:
        seasons = [current]
    if args.report:
        report(level, seasons)
        return 0
    phases = [x for x in args.phases.split(",") if x in PHASES]
    c = Client(budget=args.budget, interval=args.interval, name="bullpen",
               intervals={"baseballsavant.mlb.com": args.savant_interval, "espn.com": args.espn_interval,
                          "githubusercontent.com": 0.2})
    t0 = time.monotonic()
    try:
        for season in seasons:
            s = st.load(level, season)
            refresh = args.refresh_current and season == current
            used0 = c.used
            ran: list[str] = []

            def step(name, fn, *a):
                ran.append(name)
                fn(*a)
                st.save_owned(s, [name])

            try:
                if "schedule" in phases:
                    step("schedule", schedule, c, level, s, refresh, now.date())
                    if refresh:
                        current_extras(c, level, s, now.date())
                        st.save_owned(s, ["schedule"])
                if "statcast" in phases:
                    step("statcast", statcast, c, level, s, refresh, now.date(), args.chunk_days)
                if "games" in phases:
                    step("games", games, c, level, s, refresh, now)
                if "espn" in phases:
                    step("espn", espn_lines, c, level, s, refresh, now)
                if "people" in phases:
                    step("people", people, c, level, s, refresh)
                if args.leaderboards and level == "mlb" and season >= 2015:
                    for name in savant.LEADERBOARDS:
                        savant.leaderboard(c, name, season, refresh=refresh)
            finally:
                if s["games"] and ran:
                    st.save_owned(s, ran)
            logger.info("%s %d done: %d games, %d calls this season (%d total)", level, season, len(s["games"]),
                        c.used - used0, c.used)
    except BudgetExhausted as exc:
        logger.info("%s", exc)
    el = time.monotonic() - t0
    logger.info("calls: %s; %.0f s elapsed", c.report(), el)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
