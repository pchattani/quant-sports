#!/usr/bin/env python
"""
Build The Quant Hardwood's payloads (oddsmarkets/basketball/PAYLOADS.md) into docs/hardwood/data/.

Site-wide: index.json, glossary.json; and docs/hardwood/assets/base.css (copied from the football
site's docs/site/assets/style.css).

Per league, data/<L>/: history.json, lab.json, markets.json, calibration.json (the cached backtest;
the committed copy is kept when there is no cache, as in CI) and players/<pid>.json careers.

Per league and season, data/<L>/<S>/: season.json, teams.json, players.json, awards.json,
shots_league.json, value.json (every season; rewritten only when its content changes), games/<id>.json and
manifest.json (input signatures, so unchanged work is skipped). For each league's current season also
trade.json and needs/<tid>.json (player value, team strengths and needs, the trade simulator's inputs and the
season simulation's per-team sensitivity curves: analytics/value.py).

Seasons come in two weights:
  full   (--seasons, default each league's current season): the season simulation (--sims, 20,000),
         markets, award races, the player "current" blocks of the career files, and game pages for
         every game whose inputs changed plus every game within --games-recent days of today
         (--all-games rebuilds every page).
  light  every other season with a store (skip with --no-light): catalogues, season.json without a
         simulation, awards and game pages, all from the stores and derived inputs; a light season
         whose inputs are unchanged since its manifest was written is skipped entirely (--force
         rebuilds it).

A game page is never downgraded: when its raw play-by-play is not on this machine (CI holds only the
current season's) and the page on disk already carries play-by-play blocks, the page is kept.

Every step is isolated: a failure is logged with its traceback and the build goes on; a payload that
cannot be built is written as {"ok": false, "reason": ...}.

Roots: --data / HARDWOOD_DATA (default docs/hardwood/data) for stores in and payloads out,
--cache / HARDWOOD_CACHE (default data/basketball/cache) for model caches, HARDWOOD_PBP
(default data/basketball/pbp) for raw play-by-play.

    python scripts/build_hardwood.py                                   # every league: current full, the rest light
    python scripts/build_hardwood.py --leagues wnba --seasons 2026
    python scripts/build_hardwood.py --leagues nba --seasons 2027 2026 --sims 20000
    python scripts/build_hardwood.py --quick --no-market --no-light    # fast local check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.basketball import analytics as an  # noqa: E402
from oddsmarkets.basketball import canon  # noqa: E402

logger = logging.getLogger("build_hardwood")
CSS_SRC = ROOT / "docs" / "site" / "assets" / "style.css"
BUILD_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(o: Any) -> Any:
    """JSON-safe copy: NaN/inf -> None, numpy scalars -> Python, tuples/sets -> lists, keys -> str."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            return _clean(o.item())
        except Exception:                                        # pragma: no cover - defensive
            return None
    if hasattr(o, "isoformat") and not isinstance(o, str):
        return o.isoformat()
    return o


class Build:
    def __init__(self, data: Path):
        self.data = data
        self.errors: list[str] = []
        self.written: list[Path] = []
        self.timings: dict[str, float] = {}

    def step(self, name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        t0 = time.perf_counter()
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - never let one step take down the build
            logger.error("step %s failed: %s\n%s", name, exc, traceback.format_exc())
            self.errors.append(f"{name}: {exc}")
            return default
        finally:
            self.timings[name] = self.timings.get(name, 0.0) + time.perf_counter() - t0

    def write(self, rel: str, payload: Any) -> None:
        p = self.data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(_clean(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        tmp.replace(p)
        self.written.append(p)

    def write_if_changed(self, rel: str, payload: Any, ignore: tuple = ("updated_at",)) -> bool:
        """Write unless the file on disk already holds the same payload (keys in `ignore` aside), so an
        unchanged past season's file keeps its bytes and the deploy copies nothing."""
        p = self.data / rel
        if p.exists():
            old = an.read_json(p)
            if isinstance(old, dict) and isinstance(payload, dict):
                a = {k: v for k, v in _clean(old).items() if k not in ignore}
                bb = {k: v for k, v in _clean(payload).items() if k not in ignore}
                if json.dumps(a, sort_keys=True) == json.dumps(bb, sort_keys=True):
                    return False
        self.write(rel, payload)
        return True

    def write_or_fail(self, rel: str, name: str, fn: Callable[[], Any], **extra) -> Any:
        """Build a payload; on failure write {"ok": false, "reason"} in its place."""
        payload = self.step(name, fn)
        if payload is None:
            payload = {"ok": False, "reason": f"{name} could not be built (see the build log)", **extra}
        self.step(f"write {rel}", lambda: self.write(rel, payload))
        return payload


# ---------------------------------------------------------------------------------------------- signatures

def _file_sig(p: Path) -> str | None:
    from oddsmarkets.basketball.models import _io
    q = _io.resolve(p)
    if not q.exists():
        return None
    h = hashlib.sha1()
    if q.name.endswith(".gz"):
        import gzip
        with gzip.open(q, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    else:
        with open(q, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()[:20]


def season_sig(league: str, season: int) -> dict:
    d = an.data_root() / league / str(season)
    pb = an.pbp_root() / league / str(season)
    try:
        n_pbp = sum(1 for _ in pb.glob("*.json.gz")) if pb.exists() else 0
    except OSError:
        n_pbp = 0
    return {"version": BUILD_VERSION, "store": _file_sig(d / "store.json"), "shots": _file_sig(d / "shots.json"),
            "stints": _file_sig(d / "stints.json"), "n_pbp": n_pbp}


def sig_unchanged(old: dict | None, new: dict) -> bool:
    """A light season's inputs are unchanged. The raw play-by-play count only counts when this machine has
    raw files for the season: a season built where the raw files were (locally, with WPA and the pbp pass)
    is at least as complete as a rebuild without them, so CI, which holds only the current season's raw
    files, keeps it instead of rebuilding every past season (which overruns the build step's time limit)."""
    if not old:
        return False
    if old == new:
        return True
    if not new.get("n_pbp") and (old.get("n_pbp") or 0) > 0:
        return {k: v for k, v in old.items() if k != "n_pbp"} == {k: v for k, v in new.items() if k != "n_pbp"}
    return False


def page_sig(store: dict, gid: str, has_raw: bool) -> str:
    g = (store.get("games") or {}).get(gid) or {}
    from oddsmarkets.basketball.analytics import pbpx
    from oddsmarkets.basketball.models import winprob
    # model versions, not fitted coefficients: a refit on new games should not rebuild every page,
    # but a change to how win probability or WPA is computed must
    parts = [BUILD_VERSION, winprob.MODEL_VERSION, pbpx.VERSION, (store.get("meta") or {}).get("fetched", {}).get(gid),
             g.get("status"), g.get("hs"), g.get("as"), bool(g.get("box")), has_raw]
    return hashlib.sha1(json.dumps(parts, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------------------------- one season

def build_season(b: Build, league: str, season: int, full: bool, cfg: dict, shared: dict) -> dict:
    from oddsmarkets.basketball import store as bst
    from oddsmarkets.basketball.analytics import awards as AWD
    from oddsmarkets.basketball.analytics import games as GMS
    from oddsmarkets.basketball.analytics import lineups as LU
    from oddsmarkets.basketball.analytics import pbpx
    from oddsmarkets.basketball.analytics import players as PL
    from oddsmarkets.basketball.analytics import season as SN
    from oddsmarkets.basketball.analytics import teams as TM
    from oddsmarkets.basketball.analytics.context import SeasonContext
    t0 = time.perf_counter()
    d = f"{league}/{season}/"
    mpath = b.data / league / str(season) / "manifest.json"
    manifest = an.read_json(mpath) or {}
    sig = season_sig(league, season)
    if not full and not cfg["force"] and sig_unchanged(manifest.get("sig"), sig) and (b.data / league / str(season) / "players.json").exists():
        logger.info("%s %s light: inputs unchanged, skipped", league, season)
        return {"catalogue": an.read_json(b.data / league / str(season) / "players.json"), "skipped": True}
    today = cfg["today"]
    ctx = SeasonContext(league, season, current=shared["current"], full=full, elo=shared.get("elo"), sims=cfg["sims"],
                        fetch_markets=cfg["markets"] and full, today=today)
    store = ctx.store
    pages_old = manifest.get("games") or {}
    pages_new: dict[str, str] = {}
    written: set[str] = set()
    recent = timedelta(days=cfg["games_recent"])

    def has_raw(gid):
        return bst.pbp_path(league, season, gid).exists()

    pages_on = season >= shared.get("page_cutoff", 0)

    def due(gid) -> bool:
        if not pages_on:
            return False
        g = ctx.games.get(gid) or {}
        if cfg["all_games"] or full and cfg["games_recent"] < 0:
            return True
        ps = page_sig(store, gid, has_raw(gid))
        if pages_old.get(gid) != ps or not (b.data / league / str(season) / "games" / f"{gid}.json").exists():
            return True
        if full:
            from oddsmarkets.basketball.models._games import local_day
            dd = local_day(g)
            if dd is not None and abs((dd - today).days) <= recent.days and g.get("status") != "post" or \
                    (dd is not None and g.get("status") == "post" and (today - dd).days <= 1):
                return True
        return False

    def write_page(gid, g, parsed):
        if gid not in ctx.games or not due(gid):
            return
        payload = GMS.build_game(ctx, gid, parsed)
        b.write(f"{d}games/{gid}.json", payload)
        written.add(gid)
        pages_new[gid] = page_sig(store, gid, has_raw(gid))

    # play-by-play pass (feeds catalogues and the pages that are due)
    if an.has_pbp_dir(league, season):
        ctx.pbp_available = True
        res = b.step(f"{league} {season} pbp pass", lambda: pbpx.season_pass(league, season, store, ctx.games, ctx.wp_model,
                                                                              on_game=write_page, want_page=due), None)
        if res:
            ctx.pbp_summaries = res["games"]
            ctx.pbp_totals = pbpx.season_totals(ctx.season_pbp_summaries())    # the catalogue's games only
            logger.info("%s %s pbp pass: %d parsed, %d cached, %d without raw", league, season, res["n_parsed"], res["n_cached"],
                        res["n_missing"])
    else:
        # no raw files here: reuse the cached per-game summaries (CI for past seasons, or a cold machine)
        res = b.step(f"{league} {season} pbp cache", lambda: pbpx.season_pass(league, season, store, ctx.games, None,
                                                                               use_cache=True), None)
        if res and res["games"]:
            ctx.pbp_summaries = res["games"]
            ctx.pbp_totals = pbpx.season_totals(ctx.season_pbp_summaries())

    # the rest of the game pages (no raw play-by-play: pregame, box-only, or raw not on this machine)
    def other_pages():
        n = 0
        for gid, g in ctx.games.items():
            if gid in written or not due(gid):
                if gid not in written and gid in pages_old:
                    pages_new[gid] = pages_old[gid]
                continue
            path = b.data / league / str(season) / "games" / f"{gid}.json"
            if g.get("has_pbp") and not has_raw(gid) and path.exists():
                old = an.read_json(path) or {}
                if old.get("has_pbp") and old.get("status") == g.get("status") and old.get("hs") == g.get("hs"):
                    pages_new[gid] = page_sig(store, gid, False)
                    continue                          # never downgrade a page built with play-by-play
            payload = b.step(f"game {league}/{gid}", lambda: GMS.build_game(ctx, gid, None))
            failed = payload is None
            if failed:
                payload = {"ok": False, "reason": "game page could not be built", "id": gid}
            b.write(f"{d}games/{gid}.json", payload)
            # Unsigned (retried next run) when the page failed, or when the play-by-play pass should have built it
            # (raw on disk, the game has play-by-play) but its callback failed: a signed box-only page is never redone.
            pbp_missed = bool(g.get("has_pbp") and has_raw(gid) and ctx.pbp_available)
            pages_new[gid] = None if (failed or pbp_missed) else page_sig(store, gid, has_raw(gid))
            n += 1
        return n
    n_other = b.step(f"{league} {season} game pages", other_pages, 0)
    logger.info("%s %s: %d game pages written (%d with play-by-play)", league, season, len(written) + (n_other or 0), len(written))

    # lineups (5-man tables per team, shared by players and teams)
    lineup_tables = b.step(f"{league} {season} lineups", lambda: {
        t: LU.lineup_table(ctx.season_team_stints, t, 5, ctx.hpm) for t in ctx.teams}
        if ctx.season_team_stints is not None and not ctx.season_team_stints.empty
        else {}, {}) or {}
    hist = _player_history(shared.get("catalogues") or {}, season)
    cat = b.write_or_fail(d + "players.json", f"players {league} {season}", lambda: PL.build(ctx, hist, lineup_tables),
                          league=league, season=season)
    ratings_7d = None
    if full and ctx.phase not in ("offseason", "preseason"):
        from oddsmarkets.basketball.models import ratings as R
        ratings_7d = b.step(f"{league} {season} ratings 7d", lambda: R.fit_ratings(
            store.get("games") or {}, through=today - timedelta(days=7), prior=ctx.prior or None, league=league,
            teams=ctx.teams).get("teams"), None)
    prev_box = None
    prev_store = an.load_store(league, season - 1)
    if prev_store.get("games"):
        from oddsmarkets.basketball.models import _io
        prev_box = b.step(f"{league} {season} previous box", lambda: _io.box_frame(an.real_games(prev_store), ("reg",)), None)
    teams_payload = b.write_or_fail(d + "teams.json", f"teams {league} {season}",
                                    lambda: TM.build(ctx, cat, lineup_tables, prev_box, ratings_7d), league=league, season=season)
    season_payload = b.step(f"season {league} {season}", lambda: SN.build_season(ctx, cat, ratings_7d))
    sched_payload = b.step(f"schedule {league} {season} build", lambda: schedule_payload(ctx))
    if full and season == shared["current"]:
        season_payload = with_league(b, league, season, season_payload, teams_payload, (sched_payload or {}).get("games") or [], cfg, ctx)
    b.write_or_fail(d + "season.json", f"season.json {league} {season}", lambda: season_payload, league=league, season=season)
    b.write_or_fail(d + "schedule.json", f"schedule {league} {season}", lambda: sched_payload, league=league, season=season)
    awards = None
    if full or cfg["light_awards"]:
        awards = b.write_or_fail(d + "awards.json", f"awards {league} {season}", lambda: AWD.build(ctx), league=league, season=season)
    b.write_or_fail(d + "shots_league.json", f"shots_league {league} {season}", lambda: shots_league(ctx), league=league, season=season)
    if full and season == shared["current"]:
        value_current(b, ctx, cat, (shared.get("catalogues") or {}).get(season - 1), teams_payload, season_payload, cfg["markets"])
    blocks = {}
    if full and not cfg["no_careers"]:
        blocks = b.step(f"{league} {season} player blocks", lambda: PL.current_blocks(
            ctx, cat, lineup_tables, AWD.award_probs(awards)), {}) or {}
    manifest = {"sig": sig, "built_at": _now(), "full": full, "games": pages_new, "phase": ctx.phase}
    b.step(f"manifest {league} {season}", lambda: b.write(f"{d}manifest.json", manifest))
    logger.info("%s %s (%s): %.1f s", league, season, "full" if full else "light", time.perf_counter() - t0)
    return {"catalogue": cat, "ctx": ctx, "blocks": blocks, "awards": awards}


def with_league(b: Build, league: str, season: int, sp: dict | None, tp: dict | None, cards: list[dict], cfg: dict, ctx=None) -> dict | None:
    """season.json with its "league" block (how the race is shaping up, strengths and weaknesses:
    oddsmarkets/basketball/analytics/race.py on oddsmarkets/common/league.py) and data/<L>/race_log.json carried
    forward (the whole season's chances, one snapshot a day; the dates before live tracking, or a finished season's
    whole regular season, rebuilt from the season simulation as of each date inside a time budget a build). A failure
    leaves season.json as it was."""
    if not isinstance(sp, dict) or sp.get("ok") is False:
        return sp
    from oddsmarkets.basketball.analytics import race as RC

    def run():
        prev = an.read_json(b.data / league / "race_log.json") or {}
        runner = RC.asof_runner(league, season, ctx=ctx)
        budget = RC.REBUILD_BUDGET_S if cfg.get("sims", 0) >= 2000 else 5.0      # --quick (tests, smoke runs): a token rebuild
        blk, log = RC.build(league, season, sp, tp if isinstance(tp, dict) else None, cards, prev, _digest_now(cfg["today"]),
                            run_asof=runner, budget_s=budget)
        if log.get(str(season)):
            b.write(f"{league}/race_log.json", log)
        return blk
    blk = b.step(f"{league} league block {season}", run, None)
    if blk:
        sp["league"] = blk
    return sp


def value_current(b: Build, ctx, cat, prev_cat, teams_payload, season_payload, refresh: bool = True) -> None:
    """trade.json and needs/<tid>.json for the current season (analytics/value.py), then the valuation, moves and fantasy
    layers (`layers_current`; `refresh` lets the transactions cache refresh from ESPN)."""
    from oddsmarkets.basketball.analytics import value as VAL
    league, season = ctx.league, ctx.season
    d = f"{league}/{season}/"
    res = b.step(f"value {league} {season}", lambda: VAL.build_current(ctx, cat, prev_cat, teams_payload, season_payload))
    if not res:
        b.step(f"write {d}trade.json", lambda: b.write(d + "trade.json", {"ok": False, "reason": "the trade simulator's inputs could not be built (see the build log)", "league": league, "season": season}))
        return
    b.step(f"write {d}trade.json", lambda: b.write(d + "trade.json", res["trade"]))
    for tid, payload in res["needs"].items():
        b.step(f"write {d}needs/{tid}.json", lambda: b.write(f"{d}needs/{tid}.json", payload))
    logger.info("%s %s value: %d players, %d team pages, curves %s", league, season, res["n_players"], len(res["needs"]),
                "yes" if (res["trade"] or {}).get("curves") else "no")
    layers_current(b, ctx, cat, prev_cat, res, refresh)


def layers_current(b: Build, ctx, cat, prev_cat, res: dict, refresh: bool) -> None:
    """valuation.json (valuation v2), transactions.json and deals.json (trade ratings) and fantasy.json for the current
    season (analytics/valuation.py, moves.py, fantasy.py); each isolated, each written {"ok": false} on failure."""
    from oddsmarkets.basketball.analytics import fantasy as FN
    from oddsmarkets.basketball.analytics import moves as MV
    from oddsmarkets.basketball.analytics import valuation as VV
    league, season = ctx.league, ctx.season
    d = f"{league}/{season}/"
    fit = b.step(f"valuation fits {league}", lambda: VV.fits(league, season), None) or dict(VV.DEFAULT_FITS)
    val = b.write_or_fail(d + "valuation.json", f"valuation {league} {season}", lambda: VV.build(
        ctx, cat, prev_cat, res["proj"], res["prm"], res["games_left"], res["injuries"], fit), league=league, season=season)
    mv = b.step(f"moves {league} {season}", lambda: MV.build(ctx, val if (val or {}).get("ok") else None, res["prm"], fit, refresh=refresh))
    for name in ("transactions", "deals"):
        payload = (mv or {}).get(name) or {"ok": False, "reason": f"{name} could not be built (see the build log)", "league": league, "season": season}
        b.step(f"write {d}{name}.json", lambda: b.write(f"{d}{name}.json", payload))
    if mv:
        logger.info("%s %s moves: %s", league, season, mv.get("info"))
    b.step(f"movement {league}", lambda: movement_current(b, league, ctx.today))
    rest = b.step(f"fantasy rest factors {league}", lambda: FN.cached_rest(league, season), None)
    prev2 = an.read_json(b.data / league / str(season - 2) / "players.json")
    bt = an.read_json(b.data / league / "fantasy_backtest.json")
    summary = {k: bt.get(k) for k in ("summary", "updated_at", "seasons", "checkpoints", "n")} if isinstance(bt, dict) and bt.get("ok") else None
    b.write_or_fail(d + "fantasy.json", f"fantasy {league} {season}", lambda: FN.build(
        ctx, cat, prev_cat, res["proj"], res["prm"], val if (val or {}).get("ok") else None, res["injuries"], prev2_cat=prev2,
        rest=rest, backtest=summary), league=league, season=season)


def movement_current(b: Build, league: str, today) -> None:
    """<league>/movement.json (analytics/movement.py: chance of moving, outlook, targets), refreshed once a day."""
    from oddsmarkets.basketball.analytics import movement as MOV
    rel = f"{league}/movement.json"
    old = an.read_json(b.data / rel) if (b.data / rel).exists() else None
    if old and old.get("snapshot") == today.isoformat() and old.get("version") == MOV.VERSION:
        return
    pay = MOV.build(league, today)
    if pay:
        b.write_if_changed(rel, pay)


def value_seasons(b: Build, league: str, seasons: list[int], cats: dict[int, dict], ctx) -> int:
    """value.json for every season with a catalogue (rewritten only when it changed)."""
    from oddsmarkets.basketball.analytics import value as VAL
    n = 0
    ppw = VAL.points_per_win(league)
    for s in seasons:
        cat = cats.get(s)
        if not cat or cat.get("players") is None:
            continue
        sj = an.read_json(b.data / league / str(s) / "season.json") or {}
        pace = an.fnum(sj.get("league_pace"))
        phase = ctx.phase if ctx is not None and ctx.season == s else sj.get("phase")
        payload = b.step(f"value {league} {s}", lambda: VAL.season_value(league, s, cat, cats.get(s - 1), pace, phase, ppw))
        if payload and b.write_if_changed(f"{league}/{s}/value.json", payload):
            n += 1
    return n


def _digest_now(today: date) -> datetime:
    """The digest's clock: now, or the end of --today's UTC day for a dated build (tests, backfills)."""
    now = datetime.now(timezone.utc)
    return now if today == now.date() else datetime(today.year, today.month, today.day, 23, 59, tzinfo=timezone.utc)


def _series_sig(post: dict | None, fmt: dict | None, h: str, a: str) -> dict | None:
    """featured.py's sig.series for a playoff game: the round's name, the wins so far (home, away), best of."""
    rounds = (fmt or {}).get("series") or []
    names: list = []
    for x in (post or {}).get("series") or []:
        if x.get("round") not in names:
            names.append(x.get("round"))
    for x in (post or {}).get("series") or []:
        t = [str(v) for v in x.get("teams") or []]
        if sorted(t) == sorted([h, a]) and not str(x.get("summary") or "").lower().count("wins series"):
            w = x.get("wins") or {}
            wh, wa = int(w.get(h) or 0), int(w.get(a) or 0)
            name = str(x.get("round") or "")
            k = names.index(x.get("round"))
            best = rounds[min(k, len(rounds) - 1)] if rounds else 7
            return {"game": wh + wa + 1, "wins": [wh, wa], "best_of": best, "name": name}
    return None


def league_digest(b: "Build", league: str, season: int, today: date) -> dict:
    """index.json leagues.<L>.digest: "This week in the <league>" (oddsmarkets/common/digest.py: record, upset, hot,
    movers from the chance log, the stage) and the games that matter most (oddsmarkets/common/featured.py
    rank_featured: "today" within 18 hours, "next" the best of the coming week after those, "week" the biggest
    occasion). Reads the current season's schedule.json and season.json this build wrote: the chance on a
    finished game is the one schedule.json shows, from the ratings before its day (walk-forward, no injuries), so no
    look-ahead. Exhibition games are left out of the week. <L>/chance_log.json keeps one title and playoff snapshot a
    day per team for the movers; the front end never reads it."""
    from oddsmarkets.common import digest as DG
    from oddsmarkets.common import featured as FT
    now = _digest_now(today)
    d = f"{league}/{season}/"
    sched = (an.read_json(b.data / (d + "schedule.json")) or {}).get("games") or []
    sp = an.read_json(b.data / (d + "season.json")) or {}
    sim = ((sp.get("sim") or {}).get("teams") or {}) if isinstance(sp.get("sim"), dict) else {}
    phase = sp.get("phase")
    lg = an.LEAGUE_NAMES.get(league, league.upper())
    st = lambda c: "final" if c.get("status") == "post" else "live" if c.get("status") == "in" else "pre"
    games = [{"id": c.get("id"), "sport": "basketball", "league": lg, "start": c.get("date"), "status": st(c), "home": c.get("home"),
              "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"), "p_home": (c.get("model") or {}).get("p_home")}
             for c in sched if c.get("stype") != "pre"]
    out: dict = {"asof": now.isoformat().replace("+00:00", "Z")[:16] + "Z"}
    rec = DG.record(games, now)
    if rec:
        rec.pop("by", None)
        out["record"] = rec
    for k, v in (("upset", DG.upset(games, now)), ("hot", DG.hot(games, now))):
        if v:
            out[k] = v
    metric = "p_title" if phase == "playoffs" else "p_playoffs"
    cur = {m: {t: v.get(m) for t, v in sim.items() if v.get(m) is not None} for m in ("p_playoffs", "p_title")}
    log_all = an.read_json(b.data / league / "chance_log.json") or {}
    log_s = (log_all.get(str(season)) or {}) if isinstance(log_all, dict) else {}
    new_log = {m: DG.roll_log(log_s.get(m), now, cur[m]) for m in cur}
    if any(cur.values()):
        b.write(f"{league}/chance_log.json", {str(season): new_log})
    if phase != "offseason":
        mv = DG.movers(new_log.get(metric), cur.get(metric) or {}, now)
        if mv:
            out["movers"] = dict(mv, metric=metric)
    reg = [c for c in sched if c.get("stype") == "reg" and c.get("date")]
    if reg:
        days = sorted(str(c["date"])[:10] for c in reg)
        first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        stage = {"phase": phase, "played": sum(1 for c in reg if c.get("status") == "post"), "total": len(reg), "first": days[0], "last": days[-1],
                 "week": max(1, min((now.date() - first).days // 7 + 1, (last - first).days // 7 + 1)), "weeks": (last - first).days // 7 + 1}
        live_series = [x for x in ((sp.get("postseason") or {}).get("series") or []) if "wins series" not in str(x.get("summary") or "").lower()]
        if phase == "playoffs" and live_series:
            stage["round"] = live_series[-1].get("round")
        out["stage"] = stage
    post, fmt = sp.get("postseason"), sp.get("format")
    fg = []
    for c in sched:
        if c.get("status") == "post":
            continue
        h, a = str(c.get("home")), str(c.get("away"))
        sh, sa = sim.get(h) or {}, sim.get(a) or {}
        sig = {"playoff": [sh.get("p_playoffs"), sa.get("p_playoffs")], "title": [sh.get("p_title"), sa.get("p_title")]}
        if c.get("stype") == "pre":
            sig["preseason"] = True
        if c.get("stype") == "post":
            ser = _series_sig(post, fmt, h, a)
            if ser:
                sig["series"] = ser
            sig.pop("playoff")
        fg.append({"sport": "basketball", "league": lg, "id": c.get("id"), "start": c.get("date"), "status": st(c), "home": h, "away": a,
                   "p_home": (c.get("model") or {}).get("p_home"), "wp_home": c.get("wp_home"), "sig": sig})
    r = FT.rank_featured(fg, now)
    row = lambda x: {"id": x["key"].split(":", 1)[1], "score": x["score"], "why": x.get("reasons") or []}
    nxt = FT.rank_featured(fg, now, horizon_h=24 * 7, limit=8)["today"]   # the rest of the week, for a reader after "today"
    out["featured"] = {"today": [row(x) for x in r["today"]], "next": [row(x) for x in nxt if x["key"] not in {y["key"] for y in r["today"]}],
                       "week": row(r["week"]) if r.get("week") else None}
    return out


def schedule_payload(ctx) -> dict:
    """schedule.json: every game of the season (league members only) as a GAME_CARD, in date order."""
    from oddsmarkets.basketball.analytics.games import card, live_state
    games = []
    for gid, g in sorted(ctx.games.items(), key=lambda kv: (str(kv[1].get("date") or ""), kv[0])):
        live = live_state(ctx, g) if g.get("status") == "in" else None
        games.append(card(ctx, g, live))
    return {"ok": True, "league": ctx.league, "season": ctx.season, "updated_at": _now(), "games": games}


def shots_league(ctx) -> dict:
    from oddsmarkets.basketball.analytics.players import grid_payload, zones_table
    from oddsmarkets.basketball.models import shots as SH
    x = ctx.xpts or {}
    sh = ctx.season_shots
    if sh is None or sh.empty:
        return {"ok": False, "reason": "no shot table for this season (box-score era or not derived yet)", "league": ctx.league,
                "season": ctx.season}
    grid = SH.league_grid(sh, ctx.xmodel, "hex", 1.5)
    sq = SH.league_grid(sh, ctx.xmodel, "square", 2.0)
    m = x.get("model") or {}
    return {"ok": True, "league": ctx.league, "season": ctx.season, "updated_at": _now(), "n_shots": int(len(sh)),
            "grid": grid_payload(grid), "grid_square": grid_payload(sq), "grid_kind": {"grid": "hex r=1.5 ft", "grid_square": "2 ft squares"},
            "zones": zones_table(sh, sh), "types": _types(sh), "calibration": x.get("calibration"), "calibration_type": x.get("calibration_type"),
            "curve": x.get("curve"), "model": {k: m.get(k) for k in ("version", "n", "fg", "pps", "loglik")} if m else None}


def _types(sh) -> dict:
    from oddsmarkets.basketball.analytics.players import types_table
    return types_table(sh)


def _player_history(catalogues: dict[int, dict], season: int) -> dict:
    seasons: dict[str, int] = {}
    career: dict[str, tuple[float, float]] = {}
    prev_hpm: dict[str, float] = {}
    for s in sorted(catalogues):
        if s >= season:
            continue
        for pid, r in ((catalogues[s] or {}).get("players") or {}).items():
            seasons[pid] = seasons.get(pid, 0) + 1
            v = r.get("values") or {}
            if v.get("hpm") is not None and r.get("min"):
                m, h = career.get(pid, (0.0, 0.0))
                career[pid] = (m + r["min"], h + v["hpm"] * r["min"])
            if s == season - 1 and v.get("hpm") is not None:
                prev_hpm[pid] = v["hpm"]
    return {"seasons": seasons, "career": career, "prev_hpm": prev_hpm}


# ---------------------------------------------------------------------------------------------- one league

def build_league(b: Build, league: str, args, cfg: dict) -> dict:
    from oddsmarkets.basketball.analytics import awards as AWD
    from oddsmarkets.basketball.analytics import players as PL
    from oddsmarkets.basketball.analytics import season as SN
    from oddsmarkets.basketball.models import elo as E
    seasons = an.seasons_on_disk(league)
    if not seasons:
        logger.warning("%s: no season stores under %s", league, b.data)
        return {"seasons": [], "ctx": None, "history": None}
    cur = canon.current_season(league, cfg["today"])
    current = cur if cur in seasons else max(seasons)
    full = [s for s in (args.seasons or [current]) if s in seasons]
    light = [] if args.no_light else [s for s in seasons if s not in full]
    keep = sorted(seasons)[-cfg["game_page_seasons"]:] if cfg["game_page_seasons"] > 0 else seasons
    logger.info("%s: seasons on disk %s; full %s; light %d", league, seasons, full, len(light))
    shared: dict[str, Any] = {"current": current, "catalogues": {}, "page_cutoff": min(keep) if keep else 0}
    shared["elo"] = b.step(f"{league} elo history", lambda: E.history(league), {}) or {}
    out_ctx = None
    blocks: dict[str, dict] = {}
    built: dict[int, dict] = {}
    for s in sorted(full + light):
        r = b.step(f"{league} season {s}", lambda: build_season(b, league, s, s in full, cfg, shared), {}) or {}
        cat = r.get("catalogue")
        if cat and cat.get("ok", True):
            shared["catalogues"][s] = cat
        built[s] = r
        if s in full and r.get("blocks"):
            for pid, blk in r["blocks"].items():
                if pid not in blocks or blocks[pid]["season"] < blk["season"]:
                    blocks[pid] = blk
        if s == current and r.get("ctx") is not None:
            out_ctx = r["ctx"]
    for s in seasons:                                      # seasons not built this run: their catalogue on disk
        if s not in shared["catalogues"]:
            c = an.read_json(b.data / league / str(s) / "players.json")
            if c and c.get("players") is not None:
                shared["catalogues"][s] = c
    cats = shared["catalogues"]
    nv = b.step(f"{league} value seasons", lambda: value_seasons(b, league, seasons, cats, out_ctx), 0)
    logger.info("%s value.json: %s seasons rewritten", league, nv)
    hist = b.write_or_fail(f"{league}/history.json", f"{league} history", lambda: SN.history(league, seasons, shared["elo"]))
    vcols = {s: SN.value_columns(an.read_json(b.data / league / str(s) / "value.json")) for s in seasons if s in cats}
    b.write_or_fail(f"{league}/lab.json", f"{league} lab", lambda: SN.lab_payload(league, cats, vcols))
    b.write_or_fail(f"{league}/calibration.json", f"{league} calibration", lambda: SN.calibration(league, b.data))
    if out_ctx is not None:
        b.write_or_fail(f"{league}/markets.json", f"{league} markets", lambda: SN.markets_payload(out_ctx))
    if not args.no_careers:
        n = b.step(f"{league} careers", lambda: careers(b, league, cats, blocks), 0)
        logger.info("%s careers: %s players", league, n)
    return {"seasons": seasons, "ctx": out_ctx, "history": hist}


def jersey_number(v) -> str | None:
    """A jersey number as ESPN's roster gives it ("7", "00"); None unless one or two digits."""
    t = str(v).strip() if v is not None else ""
    return t if t.isdigit() and len(t) <= 2 else None


def careers(b: Build, league: str, cats: dict[int, dict], blocks: dict[str, dict]) -> int:
    from oddsmarkets.basketball.analytics import awards as AWD
    from oddsmarkets.basketball.analytics import players as PL
    index = PL.similar_index(cats)
    # role peers for every season's catalogue: seasons built before the role fields (0181c2cc) get role and pct_role here,
    # in memory, so the player files carry them for every season
    sim_role: dict[str, list] = {}
    for s in sorted(cats):
        P = (cats[s] or {}).get("players") or {}
        if not P:
            continue
        if not all(r.get("role") and "pct_role" in r for r in P.values()):
            roles = PL._roles_of(P)
            for pid, r in P.items():
                r["role"] = roles.get(pid, "W")
            PL.role_percentiles(P, [p for p, r in P.items() if r.get("qualified")])
        for pid, nb in PL.role_similar(P, league).items():
            sim_role.setdefault(pid, []).extend({"season": int(s), **x} for x in nb)
    names: dict[str, str] = {}
    rows: dict[str, list] = {}
    latest: dict[str, tuple[int, dict]] = {}
    for s in sorted(cats):
        for pid, r in ((cats[s] or {}).get("players") or {}).items():
            names[pid] = r.get("name") or names.get(pid) or pid
            rows.setdefault(pid, []).append(PL.season_row(s, r))
            latest[pid] = (s, r)
    ca = AWD.career_awards(league, sorted(cats), cats)
    stores_players: dict[str, dict] = {}
    numbers: dict[str, str] = {}      # the player hero's outlined number: the latest ESPN roster `jersey` on file
    for s in sorted(cats, reverse=True)[:3]:
        for pid, info in (an.load_store(league, s).get("players") or {}).items():
            stores_players.setdefault(pid, info)
            j = jersey_number((info or {}).get("jersey"))
            if j is not None:
                numbers.setdefault(pid, j)
    curs: dict[str, dict | None] = {}
    for pid in rows:
        path = b.data / league / "players" / f"{pid}.json"
        cur = blocks.get(pid)
        if cur is None and path.exists():
            old = an.read_json(path) or {}
            cur = old.get("current")
        curs[pid] = cur
    # last season's role percentiles on the current block (the player page's rail rings)
    roles_now = {pid: ((((cats.get(int(c["season"])) or {}).get("players") or {}).get(pid)) or {}).get("role")
                 for pid, c in curs.items() if c and c.get("season")}
    n_prev = PL.prev_role_pct(cats, curs, {p: r for p, r in roles_now.items() if r})
    logger.info("%s careers: last-season role percentiles on %d current blocks", league, n_prev)
    n = 0
    for pid, seasons in rows.items():
        s, r = latest[pid]
        info = stores_players.get(pid) or {}
        cur = curs.get(pid)
        payload = {"id": pid, "name": names.get(pid), "pos": info.get("pos") or r.get("pos"), "pool": r.get("pool"),
                   "dob": info.get("dob"), "number": numbers.get(pid), "league": league, "seasons": seasons, "current": cur,
                   "similar": PL.similar(pid, s, r, index, names), "similar_role": sim_role.get(pid, []),
                   "role_card": PL.role_card((cats[s] or {}).get("players") or {}, pid, league, s, cats[s]),
                   "career_awards": ca.get(pid, []), "updated_at": _now()}
        b.write(f"{league}/players/{pid}.json", payload)
        n += 1
    return n


# ---------------------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--leagues", nargs="*", choices=list(canon.LEAGUES), default=list(canon.LEAGUES))
    ap.add_argument("--seasons", type=int, nargs="*", help="seasons to build in full (default: each league's current season)")
    ap.add_argument("--sims", type=int, default=20000, help="season simulations (default 20000)")
    ap.add_argument("--quick", action="store_true", help="few simulations (tests and smoke runs)")
    ap.add_argument("--no-market", action="store_true", help="skip the Kalshi / Polymarket fetch")
    ap.add_argument("--no-light", action="store_true", help="build only the full seasons")
    ap.add_argument("--no-careers", action="store_true", help="skip data/<L>/players/<id>.json")
    ap.add_argument("--games-recent", type=int, default=3, help="also rebuild game pages within N days of today (default 3)")
    ap.add_argument("--all-games", action="store_true", help="rebuild every game page")
    ap.add_argument("--game-page-seasons", type=int, default=0,
                    help="game pages only for each league's N most recent seasons (default 0 = every season; an NBA "
                         "play-by-play season is about 70 MB of pages)")
    ap.add_argument("--force", action="store_true", help="rebuild light seasons even when their inputs are unchanged")
    ap.add_argument("--no-light-awards", action="store_true", help="skip awards.json for light seasons")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--data", default=None, help="data root (default HARDWOOD_DATA or docs/hardwood/data)")
    ap.add_argument("--cache", default=None, help="model cache root (default HARDWOOD_CACHE or data/basketball/cache)")
    ap.add_argument("--pbp", default=None, help="raw play-by-play root (default HARDWOOD_PBP or data/basketball/pbp)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    t_start = time.perf_counter()
    if args.data:
        an.set_data_root(args.data)
    if args.cache:
        an.set_cache_root(args.cache)
    if args.pbp:
        an.set_pbp_root(args.pbp)
    data = an.data_root()
    b = Build(data)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    cfg = {"sims": min(args.sims, 400) if args.quick else args.sims, "markets": not args.no_market, "today": today,
           "games_recent": args.games_recent, "all_games": args.all_games, "game_page_seasons": args.game_page_seasons, "force": args.force, "no_careers": args.no_careers,
           "light_awards": not args.no_light_awards}

    def css():
        dst = data.parent / "assets" / "base.css"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CSS_SRC, dst)
        b.written.append(dst)
    b.step("copy base.css", css)

    def kit():
        # The Quant design kit (docs/_design: tokens, components, chart kit) -> docs/hardwood/assets/qk/
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from design_kit import copy_kit
        dst = copy_kit(data.parent)
        b.written.extend(sorted(dst.glob("*")))
    b.step("copy design kit", kit)
    from oddsmarkets.basketball.analytics.glossary import build_glossary
    b.write_or_fail("glossary.json", "glossary", build_glossary)

    leagues: dict[str, dict] = {}
    for league in args.leagues:
        leagues[league] = b.step(f"league {league}", lambda: build_league(b, league, args, cfg), {}) or {}

    def index():
        from oddsmarkets.basketball.analytics import season as SN
        prev = an.read_json(data / "index.json") or {}
        out = {"ok": True, "updated_at": _now(), "leagues": dict(prev.get("leagues") or {})}
        for lg, r in leagues.items():
            if not r.get("seasons"):
                continue
            if r.get("ctx") is None and lg in out["leagues"]:
                continue                  # the current season was not built this run: keep its entry
            out["leagues"][lg] = SN.league_index(lg, r.get("ctx"), r["seasons"], r.get("history"), today)
            if r.get("ctx") is not None:
                out["leagues"][lg]["digest"] = b.step(f"{lg} digest", lambda: league_digest(b, lg, r["ctx"].season, today), {}) or {}
        return out
    b.write_or_fail("index.json", "index", index)

    total = sum(p.stat().st_size for p in set(b.written) if p.exists())
    logger.info("wrote %d files (%.1f MB) in %.1f s; %d step errors", len(set(b.written)), total / 1e6, time.perf_counter() - t_start,
                len(b.errors))
    slow = sorted(b.timings.items(), key=lambda kv: -kv[1])[:15]
    for k, v in slow:
        logger.info("  %-50s %7.1f s", k, v)
    for e in b.errors[:50]:
        logger.info("  error: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
