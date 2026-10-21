#!/usr/bin/env python
"""
Fill The Quant Campus season stores from ESPN, resumably (CONTRACT.md section 1.3).

Phases (per season, newest season first):
  scoreboard  the season's calendar (1 call), then every game day (basketball, about 150 a season) or week
              (football, about 17) at groups=80 / 50: every game's skeleton (teams, date, status, scores, line
              score, AP rank / seed, basketball team stats); plus one standings call for the season's conferences
              and membership (realignment is per season) and the classification post-passes (conference games,
              NCAA rounds, CFP seeds)
  summary     one summary per finished game: box score, venue, predictor, the pickcenter line (DraftKings with
              its open/close blocks), basketball play-by-play to data/college/pbp/<L>/<S>/<gid>.json.gz, football
              plays to data/college/cfb/plays/<S>.json.gz; when the pickcenter has no closing line, the core
              odds endpoint is read in the same pass
  odds        core odds for finished games not yet tried (seasons whose sample of 40 games has no lines are
              skipped and recorded in meta.odds_none)
  rankings    AP, Coaches (and CFP, CFP seedings for football): every week ESPN lists (core API)
  rosters     today's roster per member team (class year, height, weight, hometown, position): current season
  rosters_hist  past seasons' rosters as athlete ids (core season rosters; one call per team)
  injuries    today's injury list (current season)

`--backfill` runs the priority plan for a level (the order the models need it):
  1. scoreboards of the current season, current rosters, then scoreboards of every season (newest first)
  2. rankings of every season
  3. summaries (+ odds) newest first: football every season; basketball 2026 back to 2022
  4. basketball core odds for every older season with lines
  5. basketball summaries for older seasons
  6. past rosters (athlete ids) for every season
Each step skips what is already stored, so a restarted backfill resumes. Two worker threads share one pacer
(`--interval` seconds between any two calls). Stores are saved every `--save-every` calls.

    python scripts/cc_fetch.py --level cfb --backfill --interval 0.5 --budget 1000000
    python scripts/cc_fetch.py --level mbb --seasons 2026 --phases scoreboard,summary --budget 20000
    python scripts/cc_fetch.py --level wbb --refresh-current --budget 1500
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.college import canon  # noqa: E402
from oddsmarkets.college import store as st  # noqa: E402
from oddsmarkets.college.sources import espn  # noqa: E402

logger = logging.getLogger("cc_fetch")
PHASES = ("scoreboard", "summary", "odds", "rankings", "rosters", "rosters_hist", "injuries")
BB_FULL_FROM = 2022          # basketball seasons whose summaries come in step 3 (newest block)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Fetcher:
    def __init__(self, level: str, c: espn.Client, workers: int = 2, save_every: int = 300):
        self.level, self.c, self.workers, self.save_every = level, c, max(1, workers), save_every
        self.today = utcnow().date()
        self.current = canon.current_season(level, self.today)
        self.pool = ThreadPoolExecutor(max_workers=self.workers)
        self._last_save_calls = 0
        self.stores: dict[int, dict] = {}
        self.plays: dict[int, dict] = {}

    # ── store io ──────────────────────────────────────────────────────────
    def store(self, season: int) -> dict:
        if season not in self.stores:
            self.stores = {k: v for k, v in self.stores.items() if k == self.current}     # keep memory small
            self.plays = {k: v for k, v in self.plays.items() if k in self.stores}
            self.stores[season] = st.load(self.level, season)
        return self.stores[season]

    def plays_of(self, season: int) -> dict:
        if season not in self.plays:
            self.plays[season] = st.load_plays(season)
        return self.plays[season]

    def save(self, s: dict, force: bool = False) -> None:
        if not force and self.c.used - self._last_save_calls < self.save_every:
            return
        self._last_save_calls = self.c.used
        complete_through(s)
        st.save(s)
        if canon.is_football(self.level) and s["season"] in self.plays:
            st.save_plays(self.plays[s["season"]])

    # ── scoreboard ────────────────────────────────────────────────────────
    def take_event(self, s: dict, ev: dict) -> None:
        if espn._int((ev.get("season") or {}).get("year")) not in (None, s["season"]):
            return
        g = espn.compact_event(self.level, ev)
        if not g["home"] or not g["away"] or not g["id"]:
            return
        st.merge_game(s, g)
        for tid, rec in espn.teams_from_event(ev).items():
            st.merge_team(s, tid, rec, weak=("conference",))

    def scoreboard(self, season: int, refresh: bool = False) -> None:
        s = self.store(season)
        meta = s["meta"]
        current = season == self.current
        scanned = meta.setdefault("scanned", {})
        if not meta.get("calendar") or current:
            cal = espn.calendar(self.c, self.level, season)
            if cal:
                meta["calendar"] = cal
        cal = meta.get("calendar") or []
        lo, hi = self.today - timedelta(days=3), self.today + timedelta(days=8)
        if canon.is_football(self.level):
            keys = [f"{x[0]}-{x[1]}" for x in cal if x[1] is not None]
            if "3-1" not in keys:
                keys.append("3-1")

            def window(k):
                ent = next((x for x in cal if f"{x[0]}-{x[1]}" == k), None)
                if not ent or not ent[3]:
                    return True
                a, b = date.fromisoformat(ent[3]), date.fromisoformat(ent[4] or ent[3])
                return a <= hi and b >= lo
            todo = [k for k in keys if k not in scanned or (current and (refresh or not meta.get("complete_through")) and window(k))]
            todo = list(dict.fromkeys(todo))
            raws = self.pool.map(lambda k: (k, espn.scoreboard_week(self.c, season, int(k.split("-")[0]), int(k.split("-")[1]))), todo)
        else:
            def in_win(d):
                dd = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
                return lo <= dd <= hi
            todo = [d for d in cal if d not in scanned or (current and (refresh or not meta.get("complete_through")) and in_win(d))]
            todo = sorted(set(todo), reverse=True)
            raws = self.pool.map(lambda d: (d, espn.scoreboard_day(self.c, self.level, d)), todo)
        n = 0
        for k, raw in raws:
            if raw is None:
                continue
            for ev in raw.get("events") or []:
                self.take_event(s, ev)
            scanned[k] = st.now()
            n += 1
            self.save(s)
        if not s["conferences"] or current or not meta.get("standings_at"):
            confs, members = espn.conferences(self.c, self.level, season)
            if confs:
                s["conferences"] = confs
                for tid, m in members.items():
                    st.merge_team(s, tid, {"conference": m["conference"], "division": m["division"], "member": True})
                for tid, t in s["teams"].items():
                    if tid not in members:
                        t["member"] = False
                meta["standings_at"] = st.now()
        post_pass(s)
        self.save(s, force=True)
        logger.info("%s %d scoreboard: %d games, %d teams (%d members), %d conferences; %d pages this run; %d calls used",
                    self.level, season, len(s["games"]), len(s["teams"]), sum(1 for t in s["teams"].values() if t.get("member")),
                    len(s["conferences"]), n, self.c.used)

    # ── summaries and odds ────────────────────────────────────────────────
    def _summary_job(self, gid: str, want_odds: bool) -> tuple:
        raw = espn.summary(self.c, self.level, gid)
        core = None
        if raw is not None and want_odds:
            pc = espn.odds_from_pickcenter(raw)
            if not (pc and pc.get("has_close_block")):
                core = espn.core_odds(self.c, self.level, gid)
        return gid, raw, core, want_odds

    def summaries(self, season: int, refresh: bool = False, odds: bool = True) -> None:
        s = self.store(season)
        now = utcnow()
        current = season == self.current
        todo = []
        for gid, g in s["games"].items():
            if g.get("status") in ("postponed", "canceled"):
                continue
            when = _dt(g.get("date"))
            age_h = (now - when).total_seconds() / 3600
            done = st.fetched(s, gid) and g.get("summary")
            if g.get("status") == "post" and not done:
                todo.append(gid)
            elif g.get("status") == "in" and age_h > 5:
                todo.append(gid)
            elif refresh and current and g.get("status") == "post" and age_h < 48:
                if (s["meta"]["fetched"].get(gid) or "") < (now - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"):
                    todo.append(gid)
            elif refresh and current and g.get("status") == "pre" and -36 < age_h <= 0:
                todo.append(gid)
        todo.sort(key=lambda x: s["games"][x].get("date") or "", reverse=True)
        if not todo:
            return
        logger.info("%s %d summary: %d games to fetch", self.level, season, len(todo))
        t0, n_pbp, n_core, k = time.monotonic(), 0, 0, 0
        plays = self.plays_of(season) if canon.is_football(self.level) else None
        for chunk in _chunks(todo, 40):
            for gid, raw, core, want_odds in self.pool.map(lambda x: self._summary_job(x, odds and not st.odds_fetched(s, x)), chunk):
                k += 1
                if raw is None:
                    continue
                try:
                    rec = espn.compact_game(self.level, raw)
                    if rec["id"] != gid:
                        rec["id"] = gid
                    old = s["games"].get(gid) or {}
                    if old.get("stype") and rec.get("stype") == "reg" and old.get("stype") != "reg":
                        rec["stype"], rec["round"], rec["region"] = old["stype"], old.get("round"), old.get("region")
                    if core is not None:
                        o = espn.parse_odds(core)
                        if o:
                            rec["odds"] = o
                            n_core += 1
                    st.merge_game(s, rec)
                    if want_odds and (core is not None or (rec.get("odds") or {}).get("has_close_block")):
                        st.mark_odds(s, gid)
                    for tid, trec in espn.teams_from_summary(raw).items():
                        st.merge_team(s, tid, trec, weak=("conference",))
                    for pid, p in espn.players_from_summary(self.level, raw).items():
                        st.merge_player(s, pid, p)
                    if rec.get("has_pbp"):
                        if plays is not None:
                            pl = espn.compact_plays_cfb(raw)
                            if pl:
                                plays["types"].update(pl.pop("types"))
                                plays["games"][gid] = pl
                                n_pbp += 1
                        else:
                            pb = espn.compact_pbp_bb(raw)
                            if pb:
                                pb["id"] = gid
                                st.save_pbp(self.level, season, pb)
                                n_pbp += 1
                    if rec.get("status") == "post":
                        st.mark(s, gid)
                except Exception:  # noqa: BLE001  a bad game never stops the backfill
                    logger.exception("%s %d summary %s: parse failed", self.level, season, gid)
            self.save(s)
            if k % 400 < 40:
                rate = (time.monotonic() - t0) / max(1, k)
                logger.info("%s %d summary: %d/%d (%d plays, %d core odds), %.2f s a game, %d calls, %d throttled",
                            self.level, season, k, len(todo), n_pbp, n_core, rate, self.c.used, self.c.throttled)
        post_pass(s)
        self.save(s, force=True)
        logger.info("%s %d summary done: %d games (%d plays, %d core odds); odds coverage %s; %d calls used",
                    self.level, season, len(todo), n_pbp, n_core, s["meta"]["odds_coverage"], self.c.used)

    def odds(self, season: int, sample: int = 40) -> None:
        s = self.store(season)
        meta = s["meta"]
        if meta.get("odds_none"):
            return
        fin = [gid for gid, g in s["games"].items() if g.get("status") == "post"]
        todo = [gid for gid in fin if not st.odds_fetched(s, gid) and not ((s["games"][gid].get("odds") or {}).get("source") == "core")]
        if not todo:
            return
        tried = [gid for gid in fin if st.odds_fetched(s, gid)]
        if len(tried) < sample:
            step = max(1, len(todo) // sample)
            probe = todo[::step][:sample]
            hits = 0
            for gid, raw in self.pool.map(lambda x: (x, espn.core_odds(self.c, self.level, x)), probe):
                if raw is None:
                    continue
                st.mark_odds(s, gid)
                o = espn.parse_odds(raw)
                if o:
                    hits += 1
                    st.merge_game(s, {"id": gid, "odds": o})
            if hits == 0:
                meta["odds_none"] = st.now()
                self.save(s, force=True)
                logger.info("%s %d odds: no lines in a sample of %d games; season skipped", self.level, season, len(probe))
                return
            todo = [gid for gid in todo if not st.odds_fetched(s, gid)]
            logger.info("%s %d odds: %d of %d sampled games have lines; %d to fetch", self.level, season, hits, len(probe), len(todo))
        todo.sort(key=lambda x: s["games"][x].get("date") or "", reverse=True)
        n = 0
        for chunk in _chunks(todo, 60):
            for gid, raw in self.pool.map(lambda x: (x, espn.core_odds(self.c, self.level, x)), chunk):
                if raw is None:
                    continue
                st.mark_odds(s, gid)
                o = espn.parse_odds(raw)
                if o:
                    n += 1
                    st.merge_game(s, {"id": gid, "odds": o})
            self.save(s)
        self.save(s, force=True)
        logger.info("%s %d odds: %d of %d games with lines; coverage %s; %d calls used", self.level, season, n, len(todo),
                    s["meta"]["odds_coverage"], self.c.used)

    # ── rankings, rosters, injuries ───────────────────────────────────────
    def rankings(self, season: int, force: bool = False) -> None:
        s = self.store(season)
        if s["rankings"] and not force and season != self.current and s["meta"].get("rankings_at"):
            return
        r = espn.rankings(self.c, self.level, season)
        if r:
            s["rankings"] = r
            s["meta"]["rankings_at"] = st.now()
            post_pass(s)
        self.save(s, force=True)
        logger.info("%s %d rankings: %s; %d calls used", self.level, season,
                    {k: len(v) for k, v in (s["rankings"] or {}).items()}, self.c.used)

    def rosters(self, season: int, force: bool = False) -> None:
        s = self.store(season)
        last = s["meta"].get("rosters_at") or ""
        if not force and last >= (utcnow() - timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ") and s["meta"].get("rosters_full"):
            return
        teams = [t for t, v in s["teams"].items() if v.get("member")]
        n = 0
        for tid, ros in self.pool.map(lambda t: (t, espn.roster(self.c, self.level, t)), teams):
            if not ros:
                continue
            s["rosters"][tid] = [p["id"] for p in ros]
            for p in ros:
                pid = p.pop("id")
                p.pop("pool", None)
                st.merge_player(s, pid, p, tid)
                n += 1
        s["meta"]["rosters_at"] = st.now()
        s["meta"]["rosters_full"] = True          # fetched with limit=500 (ESPN truncates at 100 otherwise)
        self.save(s, force=True)
        logger.info("%s %d rosters: %d players from %d teams; %d calls used", self.level, season, n, len(teams), self.c.used)

    def rosters_hist(self, season: int) -> None:
        s = self.store(season)
        if season == self.current or s["meta"].get("rosters_hist_at"):
            return
        teams = [t for t, v in s["teams"].items() if v.get("member")]
        for tid, ros in self.pool.map(lambda t: (t, espn.roster(self.c, self.level, t, season)), teams):
            if ros:
                s["rosters"][tid] = [p["id"] for p in ros]
                for p in ros:
                    pl = s["players"].get(p["id"])
                    if pl is not None and tid not in pl.setdefault("teams", []):
                        pl["teams"].append(tid)
        s["meta"]["rosters_hist_at"] = st.now()
        self.save(s, force=True)
        logger.info("%s %d past rosters: %d teams; %d calls used", self.level, season, len(s["rosters"]), self.c.used)

    def injuries(self, season: int) -> None:
        if season != self.current:
            return
        s = self.store(season)
        s["meta"]["injuries"] = espn.injuries(self.c, self.level)
        s["meta"]["injuries_at"] = st.now()
        self.save(s, force=True)
        logger.info("%s %d injuries: %d teams listed", self.level, season, len(s["meta"]["injuries"]))

    def close(self) -> None:
        for s in self.stores.values():
            if s["games"] or s["teams"]:
                self.save(s, force=True)
        self.pool.shutdown(wait=False, cancel_futures=True)


# ── post-passes ─────────────────────────────────────────────────────────────

def post_pass(s: dict) -> None:
    """Season-level fixes after scoreboards / rankings: conference games from the season's membership (ESPN's
    flag is missing before about 2010), NCAA rounds from the bracket, CFP seeds from ESPN's CFP seedings,
    and the membership flag of teams seen only in games."""
    teams = s.get("teams") or {}
    have_members = any(t.get("member") for t in teams.values())
    level = s["level"]
    indep = {cid for cid, c in (s.get("conferences") or {}).items() if "indep" in str(c.get("name") or "").lower()}
    for g in s["games"].values():
        if have_members:
            th, ta = teams.get(g["home"]) or {}, teams.get(g["away"]) or {}
            same = th.get("member") and ta.get("member") and th.get("conference") and th.get("conference") == ta.get("conference") \
                and th.get("conference") not in indep
            if g.get("stype") in ("reg", "conf"):
                g["conf_game"] = bool(same)
    if not canon.is_football(level):
        for gid, rnd in canon.ncaa_rounds(s["games"]).items():
            s["games"][gid]["round"] = rnd
        canon.ncaa_regions(s["games"])
    else:
        canon.fix_cfb_postseason(s["season"], s["games"], teams)
        # seeds: ESPN's CFP seedings (2024 on), else the last weekly CFP ranking before the bowls (4-team era:
        # the committee's top four are the seeds)
        rk = s.get("rankings") or {}
        src, top = rk.get("cfp_seeds") or {}, 12
        if not src:
            src = {w: v for w, v in (rk.get("cfp") or {}).items() if str(w).isdigit()}
            top = 4 if s["season"] < 2024 else 12
        if src:
            last = src[max(src, key=lambda w: int(w) if str(w).isdigit() else 99)]
            sd = {r[1]: r[0] for r in last if r[0] and r[0] <= top}
            for g in s["games"].values():
                if g.get("stype") == "cfp" and (sd.get(g["home"]) or sd.get(g["away"])):
                    g["seeds"] = {"home": sd.get(g["home"]), "away": sd.get(g["away"])}


def complete_through(s: dict) -> None:
    last = None
    for gid, g in sorted(s["games"].items(), key=lambda kv: kv[1].get("date") or ""):
        if g.get("status") in ("postponed", "canceled"):
            continue
        if g.get("status") == "post" and st.fetched(s, gid):
            last = (g.get("date") or "")[:10]
        else:
            break
    s["meta"]["complete_through"] = last


def _dt(s) -> datetime:
    try:
        return datetime.fromisoformat(str(s or "1900-01-01T00:00:00Z").replace("Z", "+00:00"))
    except ValueError:
        return datetime(1900, 1, 1, tzinfo=timezone.utc)


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


# ── plans ───────────────────────────────────────────────────────────────────

def _safe(fn, *a, **k) -> None:
    """Run one phase of one season; an unexpected error is logged and the backfill moves on."""
    try:
        fn(*a, **k)
    except espn.BudgetExhausted:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("phase %s%s failed", getattr(fn, "__name__", fn), a)


def backfill(f: Fetcher, seasons: list[int]) -> None:
    lv = f.level
    cur = f.current
    seasons = sorted(seasons, reverse=True)
    step = lambda name: logger.info("=== %s backfill step: %s ===", lv, name)  # noqa: E731
    step("1 scoreboards (current season first), current rosters")
    if cur in seasons:
        _safe(f.scoreboard, cur)
        _safe(f.rosters, cur)
        _safe(f.injuries, cur)
    for y in seasons:
        if y != cur:
            _safe(f.scoreboard, y)
    step("2 rankings")
    for y in seasons:
        _safe(f.rankings, y)
    if canon.is_football(lv):
        step("3 summaries + odds, every season")
        for y in seasons:
            _safe(f.summaries, y)
    else:
        recent = [y for y in seasons if y >= BB_FULL_FROM]
        step(f"3 summaries + odds {recent}")
        for y in recent:
            _safe(f.summaries, y)
        older = [y for y in seasons if y < BB_FULL_FROM]
        step("4 core odds, older seasons")
        for y in older:
            _safe(f.odds, y)
        step("5 summaries, older seasons")
        for y in older:
            _safe(f.summaries, y, odds=False)
    step("6 past rosters")
    for y in seasons:
        _safe(f.rosters_hist, y)
    logger.info("=== %s backfill complete ===", lv)


def print_coverage(level: str, seasons: list[int]) -> None:
    hdr = ["season", "games", "final", "summaries", "pbp", "odds_any", "odds_close", "odds_core", "ap", "coaches", "cfp", "seeded", "members", "players"]
    print(" ".join(f"{h:>9}" for h in hdr))
    for y in sorted(seasons, reverse=True):
        c = st.coverage(level, y)
        rw = c["rank_weeks"]
        row = [y, c["games"], c["final"], c["summaries"], c["pbp"], c["odds_any"], c["odds_close"],
               c["odds_core"] if not c["odds_none_sampled"] else "none", rw.get("ap", 0), rw.get("coaches", 0), rw.get("cfp", 0),
               c["seeded_games"], c["members"], c["players"]]
        print(" ".join(f"{str(v):>9}" for v in row))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", choices=canon.LEVELS, required=True)
    ap.add_argument("--seasons", default=None, help="comma list (e.g. 2026,2025) or range 2001-2026")
    ap.add_argument("--phases", default="scoreboard,summary,rankings")
    ap.add_argument("--budget", type=int, default=2000)
    ap.add_argument("--interval", type=float, default=0.5, help="seconds between calls (0.5 = 2 a second)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--save-every", type=int, default=300)
    ap.add_argument("--backfill", action="store_true", help="the full priority plan for the level")
    ap.add_argument("--refresh-current", action="store_true", help="hourly mode for the current season")
    ap.add_argument("--coverage", action="store_true", help="print what the stores hold per season (no network) and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    lv = args.level
    cur = canon.current_season(lv)
    if args.coverage:
        print_coverage(lv, st.seasons_on_disk(lv))
        return 0
    if args.seasons:
        if "-" in args.seasons:
            a, b = (int(x) for x in args.seasons.split("-"))
            seasons = list(range(max(a, b), min(a, b) - 1, -1))
        else:
            seasons = [int(x) for x in args.seasons.split(",") if x]
    else:
        seasons = list(range(cur, canon.FIRST_SEASON[lv] - 1, -1)) if args.backfill else [cur]
    c = espn.Client(budget=args.budget, interval=args.interval)
    f = Fetcher(lv, c, workers=args.workers, save_every=args.save_every)
    t0 = time.monotonic()
    try:
        if args.backfill:
            backfill(f, seasons)
        elif args.refresh_current:
            f.scoreboard(cur, refresh=True)
            f.summaries(cur, refresh=True)
            f.rankings(cur, force=True)
            f.injuries(cur)
            if utcnow().weekday() == 0 or not f.store(cur)["meta"].get("rosters_at"):
                f.rosters(cur)
        else:
            phases = [p for p in args.phases.split(",") if p in PHASES]
            for y in sorted(seasons, reverse=True):
                for p in phases:
                    if p == "scoreboard":
                        f.scoreboard(y)
                    elif p == "summary":
                        f.summaries(y)
                    elif p == "odds":
                        f.odds(y)
                    elif p == "rankings":
                        f.rankings(y, force=True)
                    elif p == "rosters" and y == cur:
                        f.rosters(y, force=True)
                    elif p == "rosters_hist":
                        f.rosters_hist(y)
                    elif p == "injuries":
                        f.injuries(y)
    except espn.BudgetExhausted as exc:
        logger.info("%s", exc)
    finally:
        f.close()
    el = time.monotonic() - t0
    logger.info("calls used: %d in %.0f s (%.2f s a call; %d failures; %d throttled)", c.used, el, el / max(1, c.used),
                c.failures, c.throttled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
