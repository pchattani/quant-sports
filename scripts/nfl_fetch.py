#!/usr/bin/env python
"""
Fill The Quant Gridiron's raw mirror, season stores and derived play tables, resumably (CONTRACT.md section 1).

Phases:
  releases   nflverse-data release assets through the timestamp gate (sources/nflverse.py): one timestamp.txt
             per release, a HEAD per file only when that timestamp moved, a download only when the file did.
  schedule   docs/gridiron/data/<season>/store.json from schedules (games.parquet): every GAME with result,
             nflverse closing line, roof/surface/weather, referee, starting QBs, coaches, stadium coordinates,
             ESPN id; teams of the season (canon) with home stadium and record.
  plays      data/nfl/derived/<season>/plays.parquet: the pbp subset the models use, FTN charting (2022->) and
             participation (2016-2025) joined on game and play id. Rebuilt when an input is newer.
  espn       (with --espn) core odds by book for final games from --espn-from (default 2017): open/close,
             every book, consensus; read once after the game (a pre-game read is repeated after kickoff). Paced
             <= 1 request a second. With --refresh-current also games kicking off within 7 days.
  live       (with --espn --refresh-current) the week's scoreboard, then the ESPN summary for games in progress,
             kicking off within 24 h, or final within 36 h without a final summary: the compact live record
             (drives, plays, win probability, DraftKings open/close, predictor, injuries) goes to
             data/nfl/cache/espn/summary/<season>/<game_id>.json and a small `live` block onto the GAME.

--refresh-current (the scheduled job) limits everything to the current season (and season-less files).

    python scripts/nfl_fetch.py --from 1999 --to 2026                       # releases + stores + plays
    python scripts/nfl_fetch.py --from 2017 --to 2026 --phases espn --espn --log logs/nfl_backfill_espn.log
    python scripts/nfl_fetch.py --refresh-current --espn                    # hourly
    python scripts/nfl_fetch.py --report --from 1999 --to 2026
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from oddsmarkets.nfl import canon  # noqa: E402
from oddsmarkets.nfl import store as st  # noqa: E402
from oddsmarkets.nfl.sources import espn, nflverse  # noqa: E402
from oddsmarkets.nfl.sources._client import BudgetExhausted, Client  # noqa: E402

logger = logging.getLogger("nfl_fetch")
PHASES = ("releases", "schedule", "plays", "espn", "live")


def _iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── releases ────────────────────────────────────────────────────────────────

def releases(c: Client, names: list[str], seasons: list[int], refresh: bool) -> dict:
    t0 = time.monotonic()
    got = Counter()
    for rel in names:
        spec = nflverse.RELEASES[rel]
        if spec["from"] is None:
            todo = [None]
        else:
            lo, hi = spec["from"], spec.get("to") or 9999
            todo = [s for s in seasons if lo <= s <= hi]
        for s in todo:
            paths = nflverse.fetch_all(rel, s, c=c)
            got[rel] += len(paths)
        logger.info("releases %s: %d files current (timestamp %s); %d calls so far", rel, got[rel],
                    nflverse.release_timestamp(rel, c), c.used)
    logger.info("releases: %s in %.0f s", dict(got), time.monotonic() - t0)
    return dict(got)


# ── schedule -> stores ──────────────────────────────────────────────────────

def build_store(sched: pd.DataFrame, s: dict) -> None:
    season = s["season"]
    games = nflverse.games_for_season(sched, season)
    for g in games:
        st.merge_game(s, g)
    keep = {g["game_id"] for g in games}
    for gid in [k for k in s["games"] if k not in keep]:        # a game nflverse dropped (rescheduled id)
        del s["games"][gid]
    teams = canon.teams(season)
    home_st: dict[str, Counter] = {t: Counter() for t in teams}
    rec = {t: [0, 0, 0, 0, 0] for t in teams}                       # w, l, t, pf, pa (regular season)
    coach: dict[str, str] = {}
    for g in sorted(s["games"].values(), key=lambda x: (x.get("kickoff") or "", x["game_id"])):
        if g["home"] in home_st and not g.get("neutral") and g.get("stadium"):
            home_st[g["home"]][g["stadium"]] += 1
        for side, opp in (("home", "away"), ("away", "home")):
            t = g[side]
            if g.get(f"{side}_coach") and t in teams:
                coach[t] = g[f"{side}_coach"]
            if g.get("gtype") == "REG" and g.get("status") == "final" and t in rec:
                pf, pa = g["hs" if side == "home" else "as"], g["as" if side == "home" else "hs"]
                r = rec[t]
                r[0 if pf > pa else 1 if pf < pa else 2] += 1
                r[3] += pf
                r[4] += pa
    for t, v in teams.items():
        sid = home_st[t].most_common(1)[0][0] if home_st[t] else None
        v["stadium"] = sid
        v["stadium_name"] = (canon.stadium(sid) or {}).get("name")
        v["coach"] = coach.get(t)
        v["record"] = rec[t][:3]
        v["pf"], v["pa"] = rec[t][3], rec[t][4]
    s["teams"] = teams
    s["meta"]["complete_through"] = st.complete_through(s)
    m = nflverse.load_manifest("schedules")
    s["meta"]["sources"]["schedules"] = {"timestamp": m.get("timestamp"), "at": st.now()}
    s["meta"]["format"] = canon.formats(season)
    fin = [g for g in s["games"].values() if g["status"] == "final"]
    logger.info("%d schedule: %d games (%d final, %d post), %d with nflverse lines, %d with moneylines, %d espn ids",
                season, len(s["games"]), len(fin), sum(1 for g in s["games"].values() if g["gtype"] != "REG"),
                sum(1 for g in s["games"].values() if (g.get("lines") or {}).get("spread_home") is not None),
                sum(1 for g in s["games"].values() if (g.get("lines") or {}).get("ml_home") is not None),
                sum(1 for g in s["games"].values() if g.get("espn_id")))


# ── plays ───────────────────────────────────────────────────────────────────

def plays(season: int, force: bool = False) -> dict | None:
    inputs = [nflverse.path("pbp", season)]
    if season >= canon.FTN_FROM:
        inputs.append(nflverse.path("ftn_charting", season))
    if canon.PARTICIPATION[0] <= season <= canon.PARTICIPATION[1]:
        inputs.append(nflverse.path("pbp_participation", season))
    inputs = [p for p in inputs if p.exists()]
    if not inputs or not nflverse.path("pbp", season).exists():
        return None
    out = st.plays_path(season)
    if not force and out.exists() and out.stat().st_mtime >= max(p.stat().st_mtime for p in inputs):
        return None
    t0 = time.monotonic()
    info = nflverse.build_plays(season)
    logger.info("%d plays: %s (%.1f s)", season, info, time.monotonic() - t0)
    return info


# ── ESPN odds ───────────────────────────────────────────────────────────────

def espn_odds(c: Client, s: dict, refresh: bool, now: datetime, save_every: int = 50) -> None:
    season = s["season"]
    current = season == canon.current_season(now.date())
    got = s["meta"].setdefault("espn_odds", {})
    todo = []
    for gid, g in s["games"].items():
        if not g.get("espn_id"):
            continue
        ko = _iso_dt(g.get("kickoff"))
        at = _iso_dt((got.get(gid) or {}).get("at") if isinstance(got.get(gid), dict) else got.get(gid))
        if g.get("status") == "final":
            if at is None or (ko and at < ko + timedelta(hours=3)):
                todo.append(gid)
        elif refresh and current and ko and now - timedelta(hours=4) <= ko <= now + timedelta(days=7):
            stale = at is None or (now - at) > (timedelta(hours=1) if ko - now < timedelta(hours=36) else timedelta(hours=12))
            if stale:
                todo.append(gid)
    todo.sort(key=lambda x: s["games"][x].get("kickoff") or "", reverse=True)
    t0 = time.monotonic()
    n_lines = 0
    for k, gid in enumerate(todo, 1):
        g = s["games"][gid]
        raw = espn.odds(c, g["espn_id"])
        if raw is None:
            continue
        st.write_json_gz(st.espn_odds_raw_path(season, gid), raw)
        ln = espn.compact_lines(raw)
        if ln:
            lines = dict(g.get("lines") or {})
            for key in st.LINES_ESPN:
                if ln.get(key) is not None:
                    lines[key] = ln[key]
            g["lines"] = lines
            n_lines += 1
        got[gid] = {"at": st.now(), "books": len((ln or {}).get("books") or []), "items": len(raw.get("items") or [])}
        if k % save_every == 0:
            st.save_owned(s, ["espn"])
            got = s["meta"].setdefault("espn_odds", {})
            el = time.monotonic() - t0
            logger.info("%d espn: %d/%d odds calls, %d with lines, %.2f s a call, ETA %.0f min", season, k, len(todo),
                        n_lines, el / k, el / k * (len(todo) - k) / 60)
    fin = [g for g in s["games"].values() if g.get("status") == "final"]
    logger.info("%d espn: %d odds calls, %d with lines; %d/%d final games with ESPN books, %d with open, %d with close",
                season, len(todo), n_lines, sum(1 for g in fin if (g.get("lines") or {}).get("books")), len(fin),
                sum(1 for g in fin if (g.get("lines") or {}).get("open")), sum(1 for g in fin if (g.get("lines") or {}).get("close")))


# ── ESPN live ───────────────────────────────────────────────────────────────

LIVE_KEYS = ("status", "detail", "period", "clock", "possession", "down", "distance", "yardline_100", "home_score",
             "away_score", "wp_home")


def espn_live(c: Client, s: dict, now: datetime) -> None:
    season = s["season"]
    xw = {g["espn_id"]: gid for gid, g in s["games"].items() if g.get("espn_id")}
    # the scoreboard of the week(s) around now: statuses and any ESPN event missing from the schedules
    weeks = sorted({g["week"] for g in s["games"].values()
                    if (ko := _iso_dt(g.get("kickoff"))) and now - timedelta(days=2) <= ko <= now + timedelta(days=2)})
    states: dict[str, dict] = {}
    for wk in weeks:
        gt = canon.gtype_of_week(season, wk)
        if gt == "REG":
            evs = espn.scoreboard(c, week=wk, season=season, seasontype=2)
        else:
            ew = {v: k for k, v in espn.POST_WEEK.items()}[gt]
            evs = espn.scoreboard(c, week=ew, season=season, seasontype=3)
        for ev in evs or []:
            ref = espn.event_ref(ev, season)
            gid = espn.map_game_id(ref or {}, xw, s["games"]) if ref else None
            if gid and gid in s["games"]:
                states[gid] = ref
                if not s["games"][gid].get("espn_id"):
                    s["games"][gid]["espn_id"] = ref["id"]
    n = 0
    for gid, g in s["games"].items():
        ko = _iso_dt(g.get("kickoff"))
        if not g.get("espn_id") or ko is None:
            continue
        ref = states.get(gid) or {}
        in_play = ref.get("state") == "in"
        soon = now <= ko <= now + timedelta(hours=24)
        cached = st.read_json(st.espn_summary_path(season, gid)) or {}
        just_final = (ref.get("state") == "post" or g.get("status") == "final") and now - ko < timedelta(hours=36) \
            and cached.get("status") != "final"
        if not (in_play or soon or just_final):
            continue
        raw = espn.summary(c, g["espn_id"])
        rec = espn.compact_summary(raw, gid, season)
        if not rec:
            continue
        st.write_json(st.espn_summary_path(season, gid), rec)
        live = {k: rec.get(k) for k in LIVE_KEYS}
        live["at"] = st.now()
        if rec.get("odds"):
            live["dk"] = {k: rec["odds"].get(k) for k in ("open", "close", "spread_home", "total", "ml_home", "ml_away")}
        g["live"] = live
        if rec["status"] in ("live", "final"):
            g["status"] = rec["status"]
            g["hs"], g["as"] = rec.get("home_score"), rec.get("away_score")
        n += 1
    s["meta"]["live_at"] = st.now()
    logger.info("%d live: %d scoreboard weeks, %d summaries", season, len(weeks), n)


# ── report ──────────────────────────────────────────────────────────────────

def report(seasons: list[int]) -> None:
    import pyarrow.parquet as pq
    ngs = {}
    for kind in ("passing", "rushing", "receiving"):
        df = nflverse.load("nextgen_stats", kind=kind, columns=["season", "week"])
        if df is not None:
            ngs[kind] = df.groupby("season").size().to_dict()
    pl = nflverse.load("players", columns=["gsis_id", "espn_id", "pff_id", "otc_id", "smart_id", "nfl_id"])
    if pl is not None:
        print("players crosswalk:", len(pl), "gsis;", {c: int(pl[c].notna().sum()) for c in pl.columns if c != "gsis_id"})
    for season in sorted(seasons):
        s = st.load(season)
        fin = [g for g in s["games"].values() if g.get("status") == "final"]
        ln = [g.get("lines") or {} for g in fin]
        pp = st.plays_path(season)
        nplays = pq.read_metadata(pp).num_rows if pp.exists() else 0
        ftn = part = 0
        if pp.exists():
            names = set(pq.read_schema(pp).names)
            cols = [c for c in ("ftn_is_play_action", "part_offense_players") if c in names]
            if cols:
                d = pd.read_parquet(pp, columns=cols)
                ftn = int(d["ftn_is_play_action"].notna().sum()) if "ftn_is_play_action" in d else 0
                part = int(d["part_offense_players"].notna().sum()) if "part_offense_players" in d else 0
        print(f"{season}: games {len(s['games'])} ({len(fin)} final); plays {nplays:,} (FTN {ftn:,}, participation {part:,}); "
              f"NGS rows p/r/rec {ngs.get('passing', {}).get(season, 0)}/{ngs.get('rushing', {}).get(season, 0)}/"
              f"{ngs.get('receiving', {}).get(season, 0)}; nflverse lines spread {sum(1 for x in ln if x.get('spread_home') is not None)} "
              f"total {sum(1 for x in ln if x.get('total') is not None)} ml {sum(1 for x in ln if x.get('ml_home') is not None)}; "
              f"ESPN books {sum(1 for x in ln if x.get('books'))} open {sum(1 for x in ln if x.get('open'))} "
              f"close {sum(1 for x in ln if x.get('close'))}; espn ids {sum(1 for g in s['games'].values() if g.get('espn_id'))}")


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", type=int, default=None)
    ap.add_argument("--to", dest="end", type=int, default=None)
    ap.add_argument("--phases", default="releases,schedule,plays")
    ap.add_argument("--releases", default="all", help="comma list of nflverse releases, 'all' or 'none'")
    ap.add_argument("--espn", action="store_true", help="also ESPN odds (and live with --refresh-current)")
    ap.add_argument("--espn-from", type=int, default=canon.ESPN_ODDS_FROM)
    ap.add_argument("--espn-interval", type=float, default=espn.INTERVAL)
    ap.add_argument("--budget", type=int, default=20000)
    ap.add_argument("--refresh-current", action="store_true", help="scheduled mode for the current season")
    ap.add_argument("--force-plays", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=handlers)
    now = datetime.now(timezone.utc)
    current = canon.current_season(now.date())
    end = args.end or current
    start = args.start or end
    seasons = list(range(end, start - 1, -1))
    if args.refresh_current:
        seasons = [current]
    if args.report:
        report(seasons)
        return 0
    phases = [x for x in args.phases.split(",") if x in PHASES]
    if args.espn:
        phases += [p for p in (["espn", "live"] if args.refresh_current else ["espn"]) if p not in phases]
    if args.releases == "none":
        rel_names = []
    elif args.releases == "all":
        rel_names = [r for r, spec in nflverse.RELEASES.items() if not spec.get("optional")]
    else:
        rel_names = [r for r in args.releases.split(",") if r in nflverse.RELEASES]
    c = Client(budget=args.budget, interval=0.5, name="gridiron",
               intervals={"espn.com": args.espn_interval, "github.com": 0.2, "githubusercontent.com": 0.2})
    t0 = time.monotonic()
    try:
        if "releases" in phases and rel_names:
            releases(c, rel_names, seasons, args.refresh_current)
        sched = None
        if "schedule" in phases:
            if not nflverse.path("schedules").exists():
                nflverse.fetch("schedules", c=c)
            sched = nflverse.load_schedules()
        for season in seasons:
            s = st.load(season)
            ran: list[str] = []
            try:
                if "schedule" in phases and sched is not None:
                    build_store(sched, s)
                    ran.append("schedule")
                    st.save_owned(s, ["schedule"])
                if "plays" in phases:
                    plays(season, force=args.force_plays)
                if "espn" in phases and season >= args.espn_from and s["games"]:
                    ran.append("espn")
                    espn_odds(c, s, args.refresh_current and season == current, now)
                    st.save_owned(s, ["espn"])
                if "live" in phases and season == current and s["games"]:
                    ran.append("live")
                    espn_live(c, s, now)
                    st.save_owned(s, ["live"])
            finally:
                if s["games"] and ran:
                    st.save_owned(s, ran)
            logger.info("%d done (%s): %d games; %d calls so far", season, ",".join(ran) or "-", len(s["games"]), c.used)
    except BudgetExhausted as exc:
        logger.info("%s", exc)
    logger.info("calls: %s; %.0f s elapsed", c.report(), time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
