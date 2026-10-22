#!/usr/bin/env python
"""
Fill The Quant Rink's season stores, raw NHL files and derived tables, resumably, newest season first (CONTRACT.md
section 1). Within a season games are processed newest first too.

Phases, per season:
  schedule   api-web /schedule week by week over the season's window (stats REST season dates; ~40 calls), the
             season's teams (canon), a standings snapshot (today, or the last regular-season day), and the players of
             every club roster (32 calls; weekly for the current season). A week is rescanned until it has been read
             two days after its last date.
  pbp        play-by-play of every final regular-season / playoff game -> <raw>/pbp/<season>/<gameId>.json.gz (players
             from the roster spots; starters from the first goalie in net when a game has no boxscore).
  shifts     stats REST shift charts (2010-11 ->) -> <raw>/shifts/<season>/<gameId>.json.gz. An empty answer for a
             game less than two days old is asked again later.
  box        boxscores (goalies: starter, used) -> <raw>/box/..., and the stats REST season reports (skater / goalie /
             team summary and realtime, regular season and playoffs).
  edge       NHL EDGE (2021-22 ->): team-detail of every club, skater-detail / goalie-detail of every player in the
             season reports. Completed seasons once; the current season weekly.
  espn       (2019-20 ->) one ESPN scoreboard per game day maps events to gameIds (espn_id, attendance); one core
             odds call per final game gives GAME.lines (moneyline, puck line, total; open / close from 2022-23; every
             book); upcoming games read the summary pickcenter (DraftKings open / close) and, with --refresh-current,
             the NHL partner odds. Paced at --espn-interval (default 1 s).
  moneypuck  the season's MoneyPuck shot file (benchmark only; "Data from MoneyPuck.com") -> a slim Parquet; a
             completed season once, the current season at most daily.
  html_retry (only when named) games whose shift charts agree with the play-by-play's on-ice counts on < 98% of
             events: shifts rebuilt from the HTML TOI reports, kept when they agree better (REST copy under
             shifts/<S>/rest/); each game tried once (meta.html_retry); the season is re-derived when any switched.
After pbp / shifts the season's derived tables are rebuilt (events.parquet, stints.parquet, onice_check.json) when
anything new arrived or they are missing (--no-derive skips; --derive-only rebuilds without fetching).

--refresh-current (the scheduled job) rescans the current season from three days ago to a week ahead, re-reads the
standings, fetches new final games, re-reads games finished in the last two days once they have settled, refreshes
lines for upcoming and just-finished games.

    python scripts/nhl_fetch.py --from 2026 --to 2026 --budget 20000
    python scripts/nhl_fetch.py --from 2009 --to 2025 --phases schedule,pbp,shifts,box,edge --min-gap 0.25 --log logs/nhl_backfill_nhl.log
    python scripts/nhl_fetch.py --from 2019 --to 2025 --phases schedule,espn --espn-interval 1.0 --log logs/nhl_backfill_espn.log
    python scripts/nhl_fetch.py --refresh-current --budget 3000
    python scripts/nhl_fetch.py --seasons 2019 --phases html_retry --min-gap 0.5 --interval 0.5
    python scripts/nhl_fetch.py --report --from 2009 --to 2026
    python scripts/nhl_fetch.py --check-canon --from 2009 --to 2026
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

from oddsmarkets.nhl import canon  # noqa: E402
from oddsmarkets.nhl import derive  # noqa: E402
from oddsmarkets.nhl import store as st  # noqa: E402
from oddsmarkets.nhl.sources import edge, espn, moneypuck, nhl, stats  # noqa: E402
from oddsmarkets.nhl.sources._client import BudgetExhausted, Client  # noqa: E402

logger = logging.getLogger("nhl_fetch")
PHASES = ("schedule", "pbp", "shifts", "box", "edge", "espn", "moneypuck", "html_retry")
DEFAULT_PHASES = PHASES[:-1]            # html_retry runs only when named
SAVE_EVERY = 100


def _d(s: str) -> date:
    return date.fromisoformat(str(s)[:10])


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def settled(game_date: str | None, fetched_at: str | None) -> bool:
    """A game's files are settled when fetched after noon UTC of the day after the game."""
    if not fetched_at or not game_date:
        return False
    cut = datetime.combine(_d(game_date) + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=12)
    f = _dt(fetched_at)
    return bool(f and f >= cut)


# ── season dates ────────────────────────────────────────────────────────────

_SEASONS: dict | None = None


def season_dates(c: Client, season: int, today: date) -> dict:
    global _SEASONS
    p = st.cache_root() / "stats_seasons.json"
    if _SEASONS is None:
        cached = st.read_json(p) or {}
        fresh = cached.get("at") and (datetime.now(timezone.utc) - _dt(cached["at"])).total_seconds() < 86400
        if not fresh or str(season) not in (cached.get("seasons") or {}):
            got = stats.seasons(c)
            if got:
                cached = {"at": st.now(), "seasons": {str(k): v for k, v in got.items()}}
                st.write_json(p, cached)
        _SEASONS = cached.get("seasons") or {}
    rec = _SEASONS.get(str(season))
    if rec and rec.get("start"):
        return rec
    y = canon.start_year(season)
    return {"start": f"{y}-09-25", "regular_end": f"{y + 1}-04-20", "end": f"{y + 1}-06-30"}


def final_games(s: dict, newest_first: bool = True) -> list[dict]:
    gs = [g for g in s["games"].values() if g.get("status") == "final" and g.get("type") in canon.KEEP_TYPES]
    return sorted(gs, key=lambda g: (g.get("start") or g.get("date") or "", g["game_id"]), reverse=newest_first)


# ── schedule ────────────────────────────────────────────────────────────────

def schedule(c: Client, s: dict, refresh: bool, today: date) -> None:
    season = s["season"]
    current = season == canon.current_season(today)
    sd = season_dates(c, season, today)
    s["meta"]["season_dates"] = sd
    lo, hi = _d(sd["start"]), _d(sd.get("end") or sd["regular_end"])
    weeks_done = s["meta"].setdefault("weeks", {})
    n_calls = 0
    for a, b in nhl.weeks(lo, hi):
        key = a.isoformat()
        at = weeks_done.get(key)
        is_settled = at and _d(at) > b + timedelta(days=2)
        hot = current and refresh and b >= today - timedelta(days=3) and a <= today + timedelta(days=7)
        if (is_settled and not hot) or (current and at and not hot and a > today + timedelta(days=7)):
            continue
        raw = nhl.schedule_week(c, a)
        n_calls += 1
        if raw is None:
            continue
        for g in nhl.week_games(raw):
            if canon.season_of_game(g["game_id"]) != season:
                continue
            st.merge_game(s, g)
        weeks_done[key] = st.now()
    s["teams"] = canon.teams(season)
    s["meta"]["complete_through"] = st.complete_through(s)
    # standings snapshot
    have = (s.get("standings") or {}).get("date")
    if current or not have:
        day = min(today, _d(sd["regular_end"])) if sd.get("regular_end") else today
        if not current:
            day = _d(sd["regular_end"])
        raw = nhl.standings(c, day)
        n_calls += 1
        comp = nhl.compact_standings(raw, season)
        if comp:
            s["standings"] = comp
    # rosters -> players
    r_at = s["meta"].get("rosters_at")
    if not r_at or (current and (datetime.now(timezone.utc) - _dt(r_at)).days >= 7):
        n0 = len(s["players"])
        for ab in s["teams"]:
            raw = nhl.roster(c, ab, season)
            n_calls += 1
            for pid, rec in nhl.players_from_roster(raw, ab).items():
                old = s["players"].get(pid) or {}
                s["players"][pid] = {**old, **{k: v for k, v in rec.items() if v is not None}}
        s["meta"]["rosters_at"] = st.now()
        logger.info("%d rosters: %d players (%d new)", season, len(s["players"]), len(s["players"]) - n0)
    fin = sum(1 for g in s["games"].values() if g.get("status") == "final")
    logger.info("%d schedule: %d games (%d final; %d regular, %d playoffs), %d teams; %d calls", season,
                len(s["games"]), fin, sum(1 for g in s["games"].values() if g.get("type") == 2),
                sum(1 for g in s["games"].values() if g.get("type") == 3), len(s["teams"]), n_calls)


# ── per-game raw files ──────────────────────────────────────────────────────

def _todo(s: dict, kind: str, path_fn, refresh: bool, today: date, max_games: int | None) -> list[dict]:
    """Final games whose `kind` file is missing; with --refresh-current also recent games read before they settled
    (and empty shift answers, retried until settled)."""
    meta = s["meta"].setdefault(kind, {})
    out = []
    for g in final_games(s):
        gid = str(g["game_id"])
        at = meta.get(gid)
        at_ts = at.get("at") if isinstance(at, dict) else at
        empty = isinstance(at, dict) and bool(at.get("empty"))
        if not path_fn(s["season"], gid).exists():
            out.append(g)
        elif (refresh or empty) and not settled(g.get("date"), at_ts) and _d(g["date"]) >= today - timedelta(days=3):
            out.append(g)
    return out[:max_games] if max_games else out


def pbp_phase(c: Client, s: dict, refresh: bool, today: date, max_games: int | None) -> int:
    season = s["season"]
    todo = _todo(s, "pbp", st.pbp_path, refresh, today, max_games)
    n = 0
    for g in todo:
        gid = str(g["game_id"])
        raw = nhl.pbp(c, gid)
        if not raw or not raw.get("plays"):
            continue
        st.write_json_gz(st.pbp_path(season, gid), raw)
        st.mark(s, gid, "pbp")
        for pid, rec in nhl.players_from_pbp(raw, season).items():
            old = s["players"].get(pid) or {}
            s["players"][pid] = {**rec, **{k: v for k, v in old.items() if v is not None}}
        g = s["games"][gid]                       # fresh: save_owned replaces the game dicts
        if not g.get("goalies"):
            gl = nhl.goalies_from_pbp(raw, season)
            if gl:
                g["goalies"] = gl
        n += 1
        if n % SAVE_EVERY == 0:
            st.save_owned(s, ["pbp"])
            logger.info("%d pbp: %d / %d", season, n, len(todo))
    logger.info("%d pbp: %d fetched (%d to do)", season, n, len(todo))
    return n


def shifts_phase(c: Client, s: dict, refresh: bool, today: date, max_games: int | None) -> int:
    season = s["season"]
    if season < canon.SHIFTS_FROM:
        return 0
    todo = _todo(s, "shifts", st.shifts_path, refresh, today, max_games)
    # empty answers recorded before the HTML fallback existed: try the TOI reports once
    done = {str(g["game_id"]) for g in todo}
    for g in final_games(s):
        m = s["meta"]["shifts"].get(str(g["game_id"]))
        if isinstance(m, dict) and m.get("empty") and not m.get("html_tried") and str(g["game_id"]) not in done:
            todo.append(g)
    n = empty = n_html = 0
    for g in todo:
        gid = str(g["game_id"])
        raw = stats.shiftcharts(c, gid)
        if raw is None:
            continue
        if not raw.get("data") and settled(g.get("date"), st.now()):
            fb = html_shifts(c, season, gid)
            if fb:
                raw = fb
                n_html += 1
        st.write_json_gz(st.shifts_path(season, gid), raw)
        if not raw.get("data"):
            empty += 1
            s["meta"]["shifts"][gid] = {"at": st.now(), "empty": True, "html_tried": True}
        elif raw.get("source") == "html":
            s["meta"]["shifts"][gid] = {"at": st.now(), "html": True}
        else:
            st.mark(s, gid, "shifts")
        n += 1
        if n % SAVE_EVERY == 0:
            st.save_owned(s, ["shifts"])
            logger.info("%d shifts: %d / %d", season, n, len(todo))
    logger.info("%d shifts: %d fetched (%d from HTML TOI reports, %d empty; %d to do)", season, n, n_html, empty, len(todo))
    return n


def html_shifts(c: Client, season: int, gid: str) -> dict | None:
    """Shift charts rebuilt from the HTML TOI reports, for a game whose stats REST answer is empty."""
    pbp_raw = st.read_json_gz(st.pbp_path(season, gid)) or nhl.pbp(c, gid)
    if not pbp_raw:
        return None
    h, v = stats.toi_report(c, season, gid, "H"), stats.toi_report(c, season, gid, "V")
    fb = stats.shifts_from_toi_html(h, v, pbp_raw)
    if fb and fb["data"]:
        logger.info("%s shifts from HTML TOI reports: %d rows (%d unmatched)", gid, fb["total"], fb["unmatched"])
        return fb
    return None


HTML_RETRY_BELOW = 0.98
HTML_RETRY_GAIN = 0.005


def html_retry_phase(c: Client, s: dict, max_games: int | None, below: float = HTML_RETRY_BELOW) -> int:
    """Games whose stats REST shift charts agree with the play-by-play's on-ice counts on fewer than `below` of
    events (onice_check.json): rebuild the shifts from the HTML TOI reports and keep them when their agreement is
    better by HTML_RETRY_GAIN or more (the REST answer is kept under shifts/<S>/rest/). Every game is tried once
    (meta.html_retry[gid] = {rest, html, kept}). Returns the number of games switched (re-derive afterwards)."""
    season = s["season"]
    chk = st.read_json(st.onice_check_path(season)) or {}
    low = [str(g) for g in (chk.get("games_below_98") or [])]
    per = chk.get("per_game") or {}
    tried = s["meta"].setdefault("html_retry", {})
    shm = s["meta"].setdefault("shifts", {})
    todo = [g for g in low if g not in tried and not (isinstance(shm.get(g), dict) and shm[g].get("html"))
            and (per.get(g) or [None, None, 1.0])[2] is not None and per[g][2] < below]
    if max_games:
        todo = todo[:max_games]
    switched = 0
    for k, gid in enumerate(todo):
        pbp_raw = st.read_json_gz(st.pbp_path(season, gid))
        rest = st.read_json_gz(st.shifts_path(season, gid))
        if not pbp_raw or not rest:
            continue
        h, v = stats.toi_report(c, season, gid, "H"), stats.toi_report(c, season, gid, "V")
        fb = stats.shifts_from_toi_html(h, v, pbp_raw)
        rec: dict = {"at": st.now(), "rest": per[gid][2], "html": None, "kept": "rest"}
        if fb and fb.get("data"):
            try:
                rate_rest = derive.derive_game(pbp_raw, rest)[2].get("rate")
                rate_html = derive.derive_game(pbp_raw, fb)[2].get("rate")
            except Exception as exc:  # noqa: BLE001 - one bad game must not stop the pass
                logger.warning("%s html retry failed: %s", gid, exc)
                rate_rest = rate_html = None
            rec.update({"rest": rate_rest, "html": rate_html, "unmatched": fb.get("unmatched")})
            if rate_html is not None and rate_rest is not None and rate_html >= rate_rest + HTML_RETRY_GAIN:
                keep = st.shifts_path(season, gid).parent / "rest" / f"{gid}.json.gz"
                keep.parent.mkdir(parents=True, exist_ok=True)
                st.write_json_gz(keep, rest)
                st.write_json_gz(st.shifts_path(season, gid), fb)
                shm[gid] = {"at": st.now(), "html": True, "replaced_rest": True}
                rec["kept"] = "html"
                switched += 1
        tried[gid] = rec
        if (k + 1) % SAVE_EVERY == 0:
            st.save_owned(s, ["shifts"])
            logger.info("%d html retry: %d / %d (%d switched)", season, k + 1, len(todo), switched)
    logger.info("%d html retry: %d tried, %d switched to the HTML TOI reports", season, len(todo), switched)
    return switched


def box_phase(c: Client, s: dict, refresh: bool, today: date, max_games: int | None) -> int:
    season = s["season"]
    todo = _todo(s, "box", st.box_path, refresh, today, max_games)
    n = 0
    for g in todo:
        gid = str(g["game_id"])
        raw = nhl.boxscore(c, gid)
        if not raw:
            continue
        st.write_json_gz(st.box_path(season, gid), raw)
        st.mark(s, gid, "box")
        gl = nhl.goalies_from_box(raw)
        if gl:
            s["games"][gid]["goalies"] = gl       # fresh: save_owned replaces the game dicts
        n += 1
        if n % SAVE_EVERY == 0:
            st.save_owned(s, ["box"])
            logger.info("%d box: %d / %d", season, n, len(todo))
    # repair: goalies of games whose boxscore is on disk but whose record lacks them (no network)
    fixed = 0
    for gid, g in s["games"].items():
        if g.get("status") == "final" and not (g.get("goalies") or {}).get("home", {}).get("used")                 and st.box_path(season, gid).exists():
            gl = nhl.goalies_from_box(st.read_json_gz(st.box_path(season, gid)))
            if gl:
                g["goalies"] = gl
                fixed += 1
    if fixed:
        logger.info("%d box: goalies refilled from %d boxscores on disk", season, fixed)
    # season reports
    current = season == canon.current_season(today)
    rep = s["meta"].setdefault("reports", {})
    for name in stats.REPORTS:
        for gt in (2, 3):
            key = f"{name}_{gt}"
            at = rep.get(key)
            if at and (not current or (datetime.now(timezone.utc) - _dt(at)).total_seconds() < 20 * 3600):
                continue
            if gt == 3 and current and not any(x.get("type") == 3 for x in s["games"].values()):
                continue
            rows = stats.report(c, name, season, gt)
            if rows is None:
                continue
            st.write_json_gz(st.stats_report_path(season, key), rows)
            rep[key] = st.now()
    logger.info("%d box: %d fetched (%d to do); reports %d", season, n, len(todo), len(rep))
    return n


# ── EDGE ────────────────────────────────────────────────────────────────────

def edge_phase(c: Client, s: dict, refresh: bool, today: date) -> int:
    season = s["season"]
    if season < canon.EDGE_FROM:
        return 0
    current = season == canon.current_season(today)
    meta = s["meta"].setdefault("edge", {})
    max_age = 7 * 86400 if current else None
    n = 0
    jobs: list[tuple[str, int, int]] = []
    for ab, t in (s["teams"] or canon.teams(season)).items():
        jobs.append(("team", t["id"], 2))
        if any(g.get("type") == 3 and ab in (g.get("home"), g.get("away")) for g in s["games"].values()):
            jobs.append(("team", t["id"], 3))
    for kind, rep in (("skater", "skater_summary"), ("goalie", "goalie_summary")):
        for gt in (2, 3):
            rows = st.read_json_gz(st.stats_report_path(season, f"{rep}_{gt}"))
            if rows is None and gt == 2:
                rows = stats.report(c, rep, season, gt) or []
                st.write_json_gz(st.stats_report_path(season, f"{rep}_{gt}"), rows)
            for r in rows or []:
                if r.get("playerId"):
                    jobs.append((kind, int(r["playerId"]), gt))
    seen = set()
    for kind, ident, gt in jobs:
        if (kind, ident, gt) in seen:
            continue
        seen.add((kind, ident, gt))
        p = st.edge_path(season, kind, f"{ident}_{gt}")
        key = f"{kind}/{ident}/{gt}"
        at = meta.get(key)
        if p.exists() or (at and at != "none"):
            if not max_age or (at and at != "none" and (datetime.now(timezone.utc) - _dt(at)).total_seconds() < max_age):
                continue
        if at == "none" and not current:
            continue
        raw = edge.detail(c, kind, ident, season, gt)
        if raw is None:
            meta[key] = "none"
            continue
        st.write_json_gz(p, raw)
        meta[key] = st.now()
        n += 1
        if n % SAVE_EVERY == 0:
            st.save_owned(s, ["edge"])
            meta = s["meta"].setdefault("edge", {})      # save_owned replaced the meta dicts
            logger.info("%d edge: %d fetched", season, n)
    have = sum(1 for v in meta.values() if v != "none")
    logger.info("%d edge: %d fetched; %d pages on file, %d without EDGE data", season, n, have,
                sum(1 for v in meta.values() if v == "none"))
    return n


# ── ESPN ────────────────────────────────────────────────────────────────────

def espn_phase(c: Client, s: dict, refresh: bool, now: datetime) -> int:
    season = s["season"]
    if season < canon.ESPN_ODDS_FROM:
        return 0
    today = now.date()
    days_meta = s["meta"].setdefault("espn_days", {})
    odds_meta = s["meta"].setdefault("espn_odds", {})
    by_day: dict[str, dict[str, dict]] = {}
    for gid, g in s["games"].items():
        if g.get("type") in canon.KEEP_TYPES and g.get("date") and g.get("status") not in ("postponed", "cancelled"):
            by_day.setdefault(g["date"], {})[gid] = g
    n_sb = n_odds = n_sum = last_save = 0
    unmatched = 0
    for gid, g in s["games"].items():          # lines stored by an earlier parser version: re-pick from the books
        if (g.get("lines") or {}).get("books") and (g["lines"].get("v") or 1) < espn.LINES_VERSION:
            g["lines"] = espn.reselect(g["lines"])
    for day in sorted(by_day, reverse=True):
        d = _d(day)
        if d > today + timedelta(days=7):
            continue
        games = by_day[day]
        at = days_meta.get(day)
        day_settled = at and isinstance(at, dict) and _d(at["at"][:10]) > d + timedelta(days=1)
        if day_settled and not (refresh and d >= today - timedelta(days=2)):
            pass
        else:
            evs = espn.scoreboard(c, day)
            n_sb += 1
            if evs is None:
                continue
            refs = [r for r in (espn.event_ref(e, season) for e in evs) if r]
            m = espn.match_events(refs, games, season=season)
            for r in refs:
                gid = m.get(r["id"])
                if gid is None:
                    unmatched += 1
                    continue
                g = s["games"][gid]
                g["espn_id"] = r["id"]
                if r.get("attendance"):
                    g["attendance"] = r["attendance"]
                # probable starting goalies with the capture time, before the start only (ESPN rewrites them to the
                # actual starters afterwards); no extra call: the scoreboard carries them
                stt = _dt(g.get("start"))
                if (r.get("probables") and r.get("state") == "pre" and g.get("status") == "scheduled"
                        and stt is not None and now < stt):
                    g["probables"] = espn.update_probables(g.get("probables"), r["probables"], st.now(), s.get("players"),
                                                           {"home": g.get("home"), "away": g.get("away")})
            days_meta[day] = {"at": st.now(), "events": len(refs), "matched": len(m)}
        for gid in games:
            g = s["games"][gid]                   # fresh: save_owned replaces the game dicts
            eid = g.get("espn_id")
            if not eid:
                continue
            seen = odds_meta.get(gid)
            if g.get("status") == "final":
                if seen and seen.get("final"):
                    continue
                raw = espn.odds(c, eid)
                n_odds += 1
                lines = espn.compact_lines(raw)
                if lines:
                    g["lines"] = _keep_open(g.get("lines"), lines)
                odds_meta[gid] = {"at": st.now(), "final": True, "books": len((lines or {}).get("books") or [])}
            elif refresh and d <= today + timedelta(days=2):
                raw = espn.summary(c, eid)
                n_sum += 1
                lines = espn.lines_from_pickcenter(raw)
                if lines:
                    g["lines"] = _keep_open(g.get("lines"), lines)
                odds_meta[gid] = {"at": st.now(), "final": False}
        if n_odds + n_sb - last_save >= SAVE_EVERY:
            last_save = n_odds + n_sb
            st.save_owned(s, ["espn"])
            days_meta = s["meta"].setdefault("espn_days", {})    # save_owned replaced the meta dicts
            odds_meta = s["meta"].setdefault("espn_odds", {})
            logger.info("%d espn: %d scoreboards, %d odds so far", season, n_sb, n_odds)
    if refresh:
        raw = nhl.partner_odds(c)
        for gid, rec in nhl.partner_lines(raw).items():
            g = s["games"].get(str(gid))
            if g and g.get("status") == "scheduled" and not g.get("lines"):
                g["lines"] = {**rec, "open": None, "close": None, "books": None, "consensus": None}
    with_lines = sum(1 for g in s["games"].values() if g.get("lines") and g.get("status") == "final")
    logger.info("%d espn: %d scoreboards, %d odds, %d summaries; %d unmatched events; final games with lines %d / %d",
                season, n_sb, n_odds, n_sum, unmatched, with_lines,
                sum(1 for g in s["games"].values() if g.get("status") == "final"))
    return n_odds


def _keep_open(old: dict | None, new: dict) -> dict:
    """Keep an opening line seen earlier when the new record has none."""
    if old and old.get("open") and not new.get("open"):
        new = {**new, "open": old["open"]}
    return new


# ── MoneyPuck ───────────────────────────────────────────────────────────────

def moneypuck_phase(c: Client, s: dict, today: date) -> None:
    season = s["season"]
    current = season == canon.current_season(today)
    known = s["meta"].get("moneypuck")
    dest = st.moneypuck_path(season)
    if known and dest.exists():
        if not current:
            return
        if (datetime.now(timezone.utc) - _dt(known.get("at"))).total_seconds() < 20 * 3600:
            return
    marker = moneypuck.fetch(c, season, dest, known)
    if marker:
        s["meta"]["moneypuck"] = {**marker, "at": st.now()}
        logger.info("%d moneypuck: %s rows (%s)", season, marker.get("rows"), marker.get("last_modified"))


# ── derive ──────────────────────────────────────────────────────────────────

def derive_phase(s: dict) -> None:
    season = s["season"]
    t0 = time.monotonic()
    out = derive.build_season(season)
    keep = {k: out.get(k) for k in ("games", "events", "stints", "games_with_shifts", "shots", "shots_xy", "checked",
                                    "ok", "rate", "rate_strict", "side_checked", "side_disagree", "zone_checked", "zone_agree", "mismatch_types",
                                    "built_at")}
    keep["games_below_98"] = len(out.get("games_below_98") or [])
    keep["no_shifts"] = len(out.get("no_shifts") or [])
    s["meta"]["derived"] = keep
    logger.info("%d derived in %.0f s: %s", season, time.monotonic() - t0, keep)


# ── report / canon check ────────────────────────────────────────────────────

def report(seasons: list[int]) -> None:
    for season in sorted(seasons):
        s = st.load(season)
        fin = [g for g in s["games"].values() if g.get("status") == "final"]
        reg = sum(1 for g in fin if g.get("type") == 2)
        po = sum(1 for g in fin if g.get("type") == 3)
        pbp = len(list(st.pbp_path(season, 0).parent.glob("*.json.gz"))) if st.pbp_path(season, 0).parent.exists() else 0
        sh_meta = s["meta"].get("shifts") or {}
        sh_html = sum(1 for v in sh_meta.values() if isinstance(v, dict) and v.get("html") and not v.get("empty"))
        sh = sum(1 for v in sh_meta.values() if not isinstance(v, dict)) + sh_html
        sh_empty = sum(1 for v in sh_meta.values() if isinstance(v, dict) and v.get("empty"))
        box = len(s["meta"].get("box") or {})
        dv = s["meta"].get("derived") or {}
        ed = s["meta"].get("edge") or {}
        lines = sum(1 for g in fin if g.get("lines"))
        oc = sum(1 for g in fin if (g.get("lines") or {}).get("close") or (g.get("lines") or {}).get("open"))
        print(f"{canon.season_label(season)}: games {len(s['games'])} ({reg} regular, {po} playoffs final); pbp {pbp}; "
              f"shifts {sh} ({sh_html} from HTML TOI reports; +{sh_empty} empty); box {box}; events {dv.get('events')}; shots {dv.get('shots')} "
              f"({dv.get('shots_xy')} with x/y); stints {dv.get('stints')}; on-ice {dv.get('ok')}/{dv.get('checked')} "
              f"= {dv.get('rate')} (strict {dv.get('rate_strict')}; {dv.get('games_below_98')} games < 98%); EDGE {sum(1 for v in ed.values() if v != 'none')} "
              f"pages; lines {lines}/{len(fin)} (open/close {oc}); attendance {sum(1 for g in fin if g.get('attendance'))}; "
              f"players {len(s['players'])}; moneypuck {(s['meta'].get('moneypuck') or {}).get('rows')}")


def check_canon(c: Client, seasons: list[int], today: date) -> int:
    bad = 0
    for season in sorted(seasons):
        sd = season_dates(c, season, today)
        day = min(_d(sd["regular_end"]), today)
        raw = nhl.standings(c, day)
        rows = (raw or {}).get("standings") or []
        ts = canon.teams(season)
        got = {r["teamAbbrev"]["default"]: r.get("divisionName") for r in rows}
        miss = sorted(set(ts) ^ set(got))
        wrong = sorted(a for a in set(ts) & set(got) if ts[a]["division"] != got[a]
                       and not (got[a] or "").endswith(ts[a]["division"]))
        n_games = canon.games_per_team(season)
        sea = (_SEASONS or {}).get(str(season)) or {}
        fmt_ok = sea.get("games") in (None, n_games) or canon.start_year(season) == 2019
        print(f"{canon.season_label(season)} ({day}): {len(got)} clubs; canon {len(ts)}; symmetric difference {miss}; "
              f"division mismatches {wrong}; games {n_games} v stats {sea.get('games')} {'ok' if fmt_ok else 'MISMATCH'}")
        bad += len(miss) + len(wrong) + (0 if fmt_ok else 1)
    return bad


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start", default=None, help="season: 2009, 20092010 or 2009-10")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--seasons", default=None, help="explicit comma list (overrides --from / --to), processed in order")
    ap.add_argument("--phases", default=",".join(DEFAULT_PHASES))
    ap.add_argument("--budget", type=int, default=5000)
    ap.add_argument("--interval", type=float, default=nhl.INTERVAL, help="seconds between calls to one NHL host")
    ap.add_argument("--min-gap", type=float, default=0.25, help="seconds between any two calls (0.25 = 4 a second)")
    ap.add_argument("--espn-interval", type=float, default=espn.INTERVAL)
    ap.add_argument("--max-games", type=int, default=None, help="cap games per phase per season (smoke runs)")
    ap.add_argument("--refresh-current", action="store_true")
    ap.add_argument("--no-derive", action="store_true")
    ap.add_argument("--derive-only", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--check-canon", action="store_true")
    ap.add_argument("--log", default=None)
    args = ap.parse_args()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", handlers=handlers)
    now = datetime.now(timezone.utc)
    today = now.date()
    current = canon.current_season(today)
    end = canon.norm_season(args.end) if args.end else current
    start = canon.norm_season(args.start) if args.start else end
    seasons = list(reversed(canon.seasons_between(start, end)))
    if args.seasons:
        seasons = [canon.norm_season(x) for x in args.seasons.split(",") if x.strip()]
    if args.refresh_current:
        seasons = [current]
    seasons = [x for x in seasons if x >= canon.FIRST_SEASON or "moneypuck" in args.phases]
    if args.report:
        report(seasons)
        return 0
    c = Client(budget=args.budget, interval=args.interval, name="rink", min_gap=args.min_gap,
               intervals={"espn.com": args.espn_interval, "peter-tanner.com": 2.0})
    if args.check_canon:
        return 1 if check_canon(c, seasons, today) else 0
    phases = [x for x in args.phases.split(",") if x in PHASES]
    t0 = time.monotonic()
    try:
        for season in seasons:
            s = st.load(season)
            refresh = args.refresh_current and season == current
            used0, ts0 = c.used, time.monotonic()
            if args.derive_only:
                derive_phase(s)
                st.save_owned(s, ["derive"])
                continue
            ran: list[str] = []
            new_raw = 0

            def step(name, fn, *a):
                ran.append(name)
                r = fn(*a)
                st.save_owned(s, [name])
                return r or 0

            try:
                needs_games = any(x in phases for x in ("pbp", "shifts", "box", "edge", "espn"))
                if "schedule" in phases or (needs_games and not s["games"]):
                    step("schedule", schedule, c, s, refresh, today)
                if "pbp" in phases:
                    new_raw += step("pbp", pbp_phase, c, s, refresh, today, args.max_games)
                if "shifts" in phases:
                    new_raw += step("shifts", shifts_phase, c, s, refresh, today, args.max_games)
                if "html_retry" in phases:
                    new_raw += step("shifts", html_retry_phase, c, s, args.max_games)
                    if new_raw:
                        ran.append("derive")
                        derive_phase(s)
                        st.save_owned(s, ["derive"])
                        new_raw = 0
                if "box" in phases:
                    step("box", box_phase, c, s, refresh, today, args.max_games)
                if not args.no_derive and ("pbp" in phases or "shifts" in phases) \
                        and (new_raw or not st.events_path(season).exists()):
                    ran.append("derive")
                    derive_phase(s)
                    st.save_owned(s, ["derive"])
                if "edge" in phases:
                    step("edge", edge_phase, c, s, refresh, today)
                if "espn" in phases:
                    step("espn", espn_phase, c, s, refresh, now)
                if "moneypuck" in phases:
                    step("moneypuck", moneypuck_phase, c, s, today)
            finally:
                if s["games"] and ran:
                    st.save_owned(s, [r for r in ran if r != "derive"])
            logger.info("%d done: %d games, %d calls, %.0f s this season (%d calls total)", season, len(s["games"]),
                        c.used - used0, time.monotonic() - ts0, c.used)
    except BudgetExhausted as exc:
        logger.info("%s", exc)
    logger.info("calls: %s; %.0f s elapsed", c.report(), time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
