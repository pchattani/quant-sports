#!/usr/bin/env python
"""
Build The Quant Rink's payloads (oddsmarkets/nhl/PAYLOADS.md) into docs/rink/data/.

Site-wide: index.json, glossary.json, calibration.json, history.json (champions since 1917-18, season leaders),
players_index.json, players/<pid>.json (careers); and docs/rink/assets/base.css (copied from the football site's
docs/site/assets/style.css).

Per season, data/<S>/: skaters.json, goalies.json, teams.json, season.json, schedule.json, lines.json, leaders.json,
lab.json, awards.json, value.json (every season; rewritten only when its content changes), markets.json (current
season), games/<game_id>.json and manifest.json (input signatures, frozen pre-game prices and page signatures, so
unchanged work is skipped). For the current season also trade.json and needs/<abbr>.json (player value, team
strengths and needs, the trade simulator's inputs and the season simulation's per-team sensitivity curves:
analytics/value.py), and valuation.json (multi-season valuation: analytics/valuation.py), transactions.json and
deals.json (ESPN transactions, deals and trade ratings: analytics/moves.py) and fantasy.json (analytics/fantasy.py), with
the site-wide fantasy_backtest.json (cached; scripts/nhl_fantasy_backtest.py).

Seasons come in two weights:
  full   (--seasons, default the current season): season simulation (--sims), game-model prices for games not yet
         final in the pricing window (today - 1 .. today + --days-ahead), markets, award races, and the player
         "current" blocks of the career files.
  light  every other season with a store or derived events (skip with --no-light): catalogues, teams, season.json
         without a simulation, lines, leaders, lab, awards (boards); a light season whose inputs are unchanged since
         its manifest is skipped (--force rebuilds it).
Game pages are written for the --game-page-seasons most recent seasons (default 2): pages whose signature changed
(status, score, lines, goalies, events on the table, model versions) plus every not-final game of the current
season in the pricing window; --all-games rebuilds every page of those seasons. A page is never downgraded: without
the game's events on this machine the old page's event-level blocks are kept.

Memory: one season of events and stints at a time; the context is released after each season.

Every step is isolated: a failure is logged with its traceback and the build goes on; a payload that cannot be
built is written as {"ok": false, "reason": ...}; index.json is never overwritten when the current season was not
built this run.

Roots: --data / RINK_DATA (default docs/rink/data), --raw / RINK_RAW (default data/nhl), --cache / RINK_CACHE
(default data/nhl/cache).

    python scripts/build_rink.py                                    # current season full, the rest light
    python scripts/build_rink.py --seasons 20262027 20252026
    python scripts/build_rink.py --quick --no-market --no-light      # fast local check
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import logging
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.nhl import analytics as an  # noqa: E402

logger = logging.getLogger("build_rink")
CSS_SRC = ROOT / "docs" / "site" / "assets" / "style.css"
BUILD_VERSION = 2                  # bump when payload code changes: season signatures and game-page signatures move


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
            self.errors.append(f"{name}: {type(exc).__name__}: {exc}")
            return default
        finally:
            self.timings[name] = self.timings.get(name, 0.0) + time.perf_counter() - t0

    def write(self, rel: str, payload: Any) -> None:
        p = self.data / rel
        an.write_json(p, an.scrub(payload))           # no internal builder references in published text
        self.written.append(p)

    def write_if_changed(self, rel: str, payload: Any, ignore: tuple = ("updated_at",)) -> bool:
        """Write unless the file on disk already holds the same payload (keys in `ignore` aside)."""
        import json
        p = self.data / rel
        if p.exists():
            old = an.read_json(p)
            if isinstance(old, dict) and isinstance(payload, dict):
                a = {k: v for k, v in an.clean(old).items() if k not in ignore}
                bb = {k: v for k, v in an.clean(an.scrub(payload)).items() if k not in ignore}
                if json.dumps(a, sort_keys=True) == json.dumps(bb, sort_keys=True):
                    return False
        self.write(rel, payload)
        return True

    def write_or_fail(self, rel: str, name: str, fn: Callable[[], Any], **extra) -> Any:
        """Build a payload; on failure (exception or None) write {"ok": false, "reason"} in its place."""
        payload = self.step(name, fn)
        if payload is None:
            payload = {"ok": False, "reason": f"{name} could not be built (see the build log)", **extra}
        self.step(f"write {rel}", lambda: self.write(rel, payload))
        return payload


# ---------------------------------------------------------------------------------------------- signatures

def _file_sig(p: Path | None) -> str | None:
    if p is None:
        return None
    try:
        st = p.stat()
    except OSError:
        return None
    return f"{st.st_size}-{st.st_mtime_ns}"


def _content_sig(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha1()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:20]


def model_versions() -> dict:
    from oddsmarkets.nhl.analytics import adapters
    return adapters.model_versions()


def season_sig(season: int) -> dict:
    return {"version": BUILD_VERSION, "store": _content_sig(an.store_path(season)), "events": _file_sig(an.events_path(season)),
            "stints": _file_sig(an.stints_path(season)), "models": model_versions()}


# ---------------------------------------------------------------------------------------------- one season

def build_season(b: Build, season: int, full: bool, cfg: dict, shared: dict) -> dict:
    from oddsmarkets.nhl.analytics import careers as CR
    from oddsmarkets.nhl.analytics import games as GM
    from oddsmarkets.nhl.analytics import goalies as GK
    from oddsmarkets.nhl.analytics import history as HS
    from oddsmarkets.nhl.analytics import leaders as LD
    from oddsmarkets.nhl.analytics import performers as PF
    from oddsmarkets.nhl.analytics import season as SN
    from oddsmarkets.nhl.analytics import skaters as SK
    from oddsmarkets.nhl.analytics import teams as TM
    from oddsmarkets.nhl.analytics import tables
    from oddsmarkets.nhl.analytics.context import SeasonContext
    t0 = time.perf_counter()
    d = f"{season}/"
    sdir = b.data / str(season)
    manifest = an.read_json(sdir / "manifest.json") or {}
    sig = season_sig(season)
    current = season == shared["current"]
    skip = None
    if not full and not cfg["force"] and manifest.get("sig") == sig and (sdir / "skaters.json").exists() \
            and season not in shared["page_seasons"]:
        skip = "inputs unchanged"
    elif not current and not cfg["force"] and not sig["events"] and (an.read_json(sdir / "skaters.json") or {}).get("ok"):
        skip = "events not on this machine; payloads kept"
    if skip:
        logger.info("%s: %s, skipped", season, skip)
        if not (sdir / "performers.json").exists() and (sdir / "skaters.json").exists():
            # a season built before the league page's performers: derive them from the catalogues on disk
            b.write_or_fail(d + "performers.json", f"performers {season}",
                            lambda: PF.build(an.read_json(sdir / "skaters.json"), an.read_json(sdir / "goalies.json"), season), season=season)
        return {"skipped": True, **_reduced_from_disk(sdir, season), "hist": manifest.get("hist")}
    ctx = SeasonContext(season, full=full, today=cfg["today"], current=current, sims=cfg["sims"],
                        fetch_markets=cfg["markets"] and full and current, use_models=not cfg["no_models"])
    logger.info("%s (%s): %d games, phase %s, events %s, stints %s", season, "full" if full else "light", len(ctx.games), ctx.phase,
                ctx.has_events(), ctx.has_stints())
    b.step(f"tables {season}", lambda: tables.tables(ctx))
    sk = b.write_or_fail(d + "skaters.json", f"skaters {season}", lambda: SK.build(ctx), season=season)
    gk = b.write_or_fail(d + "goalies.json", f"goalies {season}", lambda: GK.build(ctx), season=season)
    markets = b.step(f"markets fetch {season}", ctx.markets, {}) if ctx.fetch_markets else {}
    from oddsmarkets.nhl.analytics import adapters
    prices: dict[str, dict] = {}
    if full and current:
        prices = b.step(f"game prices {season}", lambda: price_window(ctx, cfg), {}) or {}
    wf = b.step(f"walk-forward prices {season}", lambda: adapters.walk_forward(ctx), {}) or {}
    frozen = dict(manifest.get("prices") or {})
    for gid, pr in prices.items():
        if pr.get("p_home") is not None:
            frozen[gid] = {k: v for k, v in pr.items() if k in ("p_home", "p_reg_home", "p_reg_away", "p_ot", "p_so", "total", "home_goals", "away_goals", "score_dist", "total_dist", "p_over", "total_line", "fair_total",
                                                                 "puck_line_home")} | {"source": "frozen"}
    xg = b.step(f"xg by game {season}", lambda: GM.xg_by_game(tables.tables(ctx)["ev"]), {}) or {}
    sched = b.write_or_fail(d + "schedule.json", f"schedule {season}", lambda: SN.schedule(ctx, prices, frozen, wf, markets, xg), season=season)
    cards = (sched or {}).get("games") or []
    sim = b.step(f"season sim {season}", ctx.sim, None) if full and current else None
    tms = b.write_or_fail(d + "teams.json", f"teams {season}", lambda: TM.build(ctx, sk, gk, sim, cards), season=season)
    spl = b.write_or_fail(d + "season.json", f"season {season}",
                          lambda: with_league(b, season, SN.build(ctx, tms, sim), tms, cards, cfg) if full and current else SN.build(ctx, tms, sim),
                          season=season)
    lns = b.write_or_fail(d + "lines.json", f"lines {season}", lambda: LD.lines(ctx, sk), season=season)
    b.write_or_fail(d + "leaders.json", f"leaders {season}", lambda: LD.build(ctx, sk, gk, tms), season=season)
    # the league page's top and bottom performers (oddsmarkets/nhl/analytics/performers.py)
    b.write_or_fail(d + "performers.json", f"performers {season}", lambda: PF.build(sk, gk, season), season=season)
    b.write_or_fail(d + "lab.json", f"lab {season}", lambda: LD.lab(ctx, sk, gk, tms, lns), season=season)
    aw_model = b.step(f"awards model {season}", lambda: adapters.awards(ctx, sim), None) if full and current else None
    b.write_or_fail(d + "awards.json", f"awards {season}", lambda: LD.awards(ctx, sk, gk, aw_model), season=season)
    if full and current:
        b.write_or_fail(d + "markets.json", f"markets {season}", lambda: SN.markets_payload(ctx, sim, aw_model, cards, markets), season=season)
    # game pages
    pages = manifest.get("games") or {}
    if season in shared["page_seasons"]:
        pages = b.step(f"game pages {season}", lambda: game_pages(b, ctx, cfg, manifest, prices, frozen, wf, cards, markets), pages) or pages
    blocks = {}
    if full and not cfg["no_careers"]:
        blocks = b.step(f"player blocks {season}", lambda: CR.current_blocks(ctx, sk, gk), {}) or {}
    rows = _reduce(sk, gk, season)
    hist = b.step(f"history rows {season}", lambda: {"champion": SN.champion(ctx), "finalist": _finalist(ctx),
                                                     "leaders": HS.season_leaders(season, sk, gk),
                                                     "league": HS.league_summary(ctx, tables.tables(ctx))}, None)
    xg_cal = b.step(f"xg benchmark {season}", lambda: adapters.xg_benchmark(ctx), None)
    out = {"rows": rows, "blocks": blocks, "current": current, "phase": ctx.phase, "hist": hist, "xg_cal": xg_cal,
           "people": {p: v for p, v in ctx.players.items()}}
    if full and current:
        out.update(cards=cards, season_payload=spl, teams=tms, sim=sim, leaders=LD.index_leaders(sk, gk), markets=markets,
                   teams_info=ctx.teams)
    manifest = {"sig": sig, "built_at": _now(), "full": full, "phase": ctx.phase, "games": pages, "prices": frozen, "hist": hist,
                "model_errors": dict(ctx.model_errors), "xg_source": ctx.xg_source,
                "timings": {k: round(v, 1) for k, v in ctx.timings.items()}}
    b.step(f"manifest {season}", lambda: b.write(d + "manifest.json", manifest))
    for k, v in ctx.timings.items():
        b.timings[f"{season} {k}"] = v
    ctx.free()
    del ctx
    gc.collect()
    logger.info("%s (%s): %.1f s", season, "full" if full else "light", time.perf_counter() - t0)
    return out


def with_league(b: Build, season: int, spl: dict | None, tms: dict | None, cards: list[dict], cfg: dict) -> dict | None:
    """season.json with its "league" block (how the race is shaping up, strengths and weaknesses:
    oddsmarkets/nhl/analytics/race.py on oddsmarkets/common/league.py) and data/race_log.json carried forward (the
    whole season's chances, one snapshot a day; the dates before live tracking rebuilt from the season simulation as
    of each date, a time budget a build). A failure leaves season.json as it was."""
    if not isinstance(spl, dict) or not spl.get("ok", True):
        return spl
    from oddsmarkets.nhl.analytics import race as RC

    def run():
        prev = an.read_json(b.data / "race_log.json") or {}
        runner = None if cfg.get("no_models") else RC.asof_runner(season)
        blk, log = RC.build(season, spl, tms, cards, prev, _digest_now(cfg["today"]), run_asof=runner)
        if log.get(str(season)):
            b.write("race_log.json", log)
        return blk
    blk = b.step(f"league block {season}", run, None)
    if blk:
        spl["league"] = blk
    return spl


def _finalist(ctx) -> str | None:
    from oddsmarkets.nhl.analytics import season as SN
    ss = SN.series_from_store(ctx)
    if not ss:
        return None
    last = max(s["round"] for s in ss)
    fin = [s for s in ss if s["round"] == last]
    if len(fin) != 1 or not fin[0].get("winner"):
        return None
    return next((t for t in fin[0]["teams"] if t != fin[0]["winner"]), None)


def _reduce(sk: dict | None, gk: dict | None, season: int) -> dict:
    from oddsmarkets.nhl.analytics import careers as CR
    rows = {}
    rows.update(CR.reduce_cat(gk, season, "goalie") or {})
    rows.update(CR.reduce_cat(sk, season, "skater") or {})
    return rows


def _reduced_from_disk(sdir: Path, season: int) -> dict:
    return {"rows": _reduce(an.read_json(sdir / "skaters.json"), an.read_json(sdir / "goalies.json"), season)}


def price_window(ctx, cfg: dict) -> dict[str, dict]:
    """Game-model prices for the season's games not yet final, starting from yesterday to --days-ahead."""
    from oddsmarkets.nhl.analytics import adapters
    lo = cfg["today"] - timedelta(days=1)
    hi = cfg["today"] + timedelta(days=cfg["days_ahead"])
    due = []
    for gid, g in ctx.games.items():
        if g.get("status") == "final" or g.get("gtype") not in ("REG", "PO"):
            continue
        try:
            dd = date.fromisoformat(str(g.get("date") or "")[:10])
        except ValueError:
            continue
        if lo <= dd <= hi:
            due.append(g)
    logger.info("%s: pricing %d games", ctx.season, len(due))
    out = adapters.game_prices(ctx, due)
    for gid in out:
        out[gid]["priced_at"] = _now()
    return out


def game_pages(b: Build, ctx, cfg: dict, manifest: dict, prices: dict, frozen: dict, wf: dict, cards: list[dict], markets: dict | None) -> dict:
    from oddsmarkets.nhl.analytics import games as GM
    from oddsmarkets.nhl.analytics import tables
    old_sigs = dict(manifest.get("games") or {})
    mv = {**model_versions(), "build": BUILD_VERSION, "xg": ctx.xg_source}
    gdir = b.data / str(ctx.season) / "games"
    by_card = {c["game_id"]: c for c in cards}
    T = tables.tables(ctx)
    ev, st, pg, gg = T["ev"], T["st"], T["pg"], T["gg"]
    ev_idx = ev.groupby("game_id").indices if len(ev) else {}
    st_idx = st.groupby("game_id").indices if len(st) else {}
    pg_idx = pg.groupby("game_id").indices if len(pg) else {}
    gg_idx = gg.groupby("game_id").indices if len(gg) else {}
    # current season only: shift charts there can still be filling in (past seasons' pages keep their signatures)
    st_sec = st.groupby("game_id")["dur"].sum().round().astype(int).to_dict() if ctx.current and len(st) and "dur" in st else {}
    lo = cfg["today"] - timedelta(days=1)
    hi = cfg["today"] + timedelta(days=cfg["days_ahead"])
    due, new_sigs = [], {}
    for gid, g in ctx.games.items():
        if gid not in by_card:
            continue
        s = GM.page_sig(g, len(ev_idx.get(gid, ())), mv, st_sec.get(gid, 0) if ctx.current else None)
        new_sigs[gid] = s
        exists = (gdir / f"{gid}.json").exists()
        try:
            dd = date.fromisoformat(str(g.get("date") or "")[:10])
        except ValueError:
            dd = None
        live = g.get("status") != "final"
        in_window = dd is not None and lo <= dd <= hi
        if cfg["all_games"] or not exists or old_sigs.get(gid) != s or (ctx.current and live and in_window):
            due.append(gid)
    logger.info("%s: %d game pages due of %d", ctx.season, len(due), len(by_card))
    mk_games = (markets or {}).get("games") or {}
    written = 0
    for gid in due:
        g = ctx.games[gid]
        p = gdir / f"{gid}.json"
        old = an.read_json(p) if p.exists() else None
        pr = prices.get(gid) or frozen.get(gid) or wf.get(gid)
        pregame = None
        if pr:
            c = by_card.get(gid) or {}
            pregame = {"model": pr, "source": pr.get("source") or "game", "market": c.get("market"), "market_detail": mk_games.get(gid),
                       "line": c.get("line"), "goalies": c.get("goalies"), "priced_at": pr.get("priced_at")}
        elif old and old.get("pregame"):
            pregame = old["pregame"]

        def build(g=g, gid=gid, old=old, pregame=pregame):
            evg = ev.iloc[ev_idx[gid]] if gid in ev_idx else None
            stg = st.iloc[st_idx[gid]] if gid in st_idx else None
            pgg = pg.iloc[pg_idx[gid]] if gid in pg_idx else None
            ggg = gg.iloc[gg_idx[gid]] if gid in gg_idx else None
            return GM.build_page(ctx, g, evg, stg, pgg, ggg, by_card.get(gid) or GM.card(g), pregame, old, T["pos"])
        payload = b.step(f"game {gid}", build)
        if payload is None:
            payload = {"ok": False, "reason": "game page could not be built", "game_id": gid}
            new_sigs[gid] = None                                 # unsigned: the next run tries again
        b.write(f"{ctx.season}/games/{gid}.json", payload)
        written += 1
    gc.collect()
    logger.info("%s: %d game pages written", ctx.season, written)
    return new_sigs


# ---------------------------------------------------------------------------------------------- site-wide

def value_all(b: Build, seasons: list[int], current: int, res: dict) -> dict:
    """value.json for every season with catalogues (rewritten only when it changed), the aging curves fitted on the
    completed seasons, and for the current season (when built this run) trade.json and needs/<abbr>.json."""
    from oddsmarkets.nhl.analytics import value as VAL
    rows_by: dict[int, list[dict]] = {}
    cats: dict[int, tuple] = {}
    n = 0
    for s in sorted(seasons):
        sk, gk = an.read_json(b.data / str(s) / "skaters.json"), an.read_json(b.data / str(s) / "goalies.json")
        if not (sk or {}).get("players"):
            continue
        cats[s] = (sk, gk)
        p = an.prev_season(s)
        psk, pgk = cats.get(p) or (None, None)
        phase = (res.get(s) or {}).get("phase")
        payload = b.step(f"value {s}", lambda: VAL.season_value(s, sk, gk, psk, pgk, phase))
        if payload:
            rows_by[s] = [dict(zip(payload["cols"], r)) for r in payload["rows"]]
            if b.write_if_changed(f"{s}/value.json", payload):
                n += 1
    aging = {k: VAL.aging_curve({s: r for s, r in rows_by.items() if s != current}, k) for k in ("S", "G")}
    out = {"rewritten": n, "aging": aging}
    cur = res.get(current) or {}
    if "teams_info" not in cur or current not in cats:
        logger.info("value: the current season %s was not built this run; trade.json and needs kept", current)
        return out
    sim = cur.get("sim") or {}
    games = 82
    for t in (sim.get("teams") or {}).values():
        c = t.get("current") or {}
        if c.get("gp") is not None and c.get("remaining") is not None:
            games = int(c["gp"]) + int(c["remaining"])
            break
    sk, gk = cats[current]
    psk, pgk = cats.get(an.prev_season(current)) or (None, None)
    r = b.step(f"value current {current}", lambda: VAL.build_current(current, an.load_store(current), list(cur["teams_info"]), sk, gk, psk, pgk,
                                                                      sim, aging, phase=cur.get("phase"), games=games))
    if not r:
        b.step(f"write {current}/trade.json", lambda: b.write(f"{current}/trade.json", {"ok": False, "season": current,
               "reason": "the trade simulator's inputs could not be built (see the build log)"}))
        return out
    b.step(f"write {current}/trade.json", lambda: b.write(f"{current}/trade.json", r["trade"]))
    for t, payload in r["needs"].items():
        b.step(f"write {current}/needs/{t}.json", lambda: b.write(f"{current}/needs/{t}.json", payload))
    out.update(players=r["n_players"], teams=len(r["needs"]), curves=bool(r["trade"].get("curves")))
    return out


def extras_all(b: Build, seasons: list[int], current: int, res: dict, vres: dict, today: date, fetch: bool = True) -> dict:
    """Valuation v2 (valuation.json), transactions and trade ratings (transactions.json, deals.json) and the fantasy
    layer (fantasy.json, data/fantasy_backtest.json) for the current season, when it was built this run. Every part is
    its own step; network calls (ESPN transactions and injuries, records.nhl.com drafts, NHL player search) are a
    handful an hour, cached, and skipped silently offline."""
    from oddsmarkets.nhl.analytics import fantasy as FA
    from oddsmarkets.nhl.analytics import gamelog as GL
    from oddsmarkets.nhl.analytics import moves as MV
    from oddsmarkets.nhl.analytics import valuation as VV
    from oddsmarkets.nhl.sources import moves as SM
    cur = res.get(current) or {}
    out: dict = {}
    if "teams_info" not in cur:
        logger.info("extras: the current season %s was not built this run; valuation, moves and fantasy kept", current)
        return out
    phase = cur.get("phase")
    prev, prev2 = an.prev_season(current), an.prev_season(an.prev_season(current))
    vr = b.step("valuation inputs", VV.value_rows, {}) or {}
    completed = sorted(s for s in vr if s < current)
    if not completed:
        return out
    f = b.step("valuation fits", lambda: VV.fits(vr, completed, vres.get("aging")))
    if not f:
        return out
    store = an.load_store(current)
    players = {an.sid(k): v for k, v in (store.get("players") or {}).items() if isinstance(v, dict)}
    inj_raw = b.step("injuries fetch", lambda: SM.injuries(refresh_now=fetch), {}) or {}
    injp = b.step("injuries match", lambda: VV.injuries_by_pid(inj_raw.get("rows") or [], players), {}) or {}
    rd = lambda s, n: an.read_json(b.data / str(s) / n)          # noqa: E731
    gpw = vr.get(completed[-1], {}).get("gpw") or 6.0
    val = b.step("valuation", lambda: VV.current_payload(current, store, rd(current, "skaters.json"), rd(current, "goalies.json"),
                                                         rd(prev, "skaters.json"), rd(prev, "goalies.json"),
                                                         (rd(prev2, "skaters.json"), rd(prev2, "goalies.json")), f, gpw, today, injp, phase))
    ev = (val or {}).pop("_ev", {}) if val else {}
    if val:
        val["injuries"] = {"source": "ESPN public site API (injury status and return date only)", "fetched_at": inj_raw.get("fetched_at"),
                           "rows": len(inj_raw.get("rows") or []), "matched": len(injp)}
    b.step(f"write {current}/valuation.json", lambda: b.write(f"{current}/valuation.json", val or {
        "ok": False, "season": current, "reason": "valuation could not be built (see the build log)"}))
    out["valuation"] = len((val or {}).get("rows") or [])
    logs = b.step("game logs", lambda: GL.logs([prev2, prev, current], current=current), None)
    if logs is None:
        return out
    # transactions, deals, trade ratings
    if fetch:
        out["tx_fetch"] = b.step("transactions fetch", lambda: SM.refresh(today), None)
    drafts = b.step("drafts", lambda: SM.drafts(list(range(2005, MV.next_draft_year(today))), fetch=fetch), {}) or {}
    curve = b.step("pick curve", lambda: MV.pick_curve(drafts, vr), None)

    def moves():
        stores = {s: an.load_store(s) if s == current else (an.read_json(an.store_path(s)) or {}) for s in (prev2, prev, current)}
        pidx = an.read_json(b.data / "players_index.json") or {}
        ix = MV.build_index(stores, pidx, drafts, logs.get("sk"))
        asof = VV.AsOf(vr, f, logs, stores, today)
        roster = {pid: p.get("team") for pid, p in players.items()}
        rows = SM.tx_rows([today.year - 1, today.year])
        resolver = lambda names: SM.search(names, fetch=fetch)            # noqa: E731
        return MV.build(current, rows, ix, asof, ev, roster, curve, vr, logs, f, today, drafts, phase, resolver=resolver)
    mv = b.step("moves", moves, None)
    if mv:
        b.step(f"write {current}/transactions.json", lambda: b.write(f"{current}/transactions.json", mv["transactions"]))
        b.step(f"write {current}/deals.json", lambda: b.write(f"{current}/deals.json", mv["deals"]))
        out["moves"] = mv["n"]
    else:
        for name in ("transactions", "deals"):
            b.step(f"write {current}/{name}.json", lambda name=name: b.write(f"{current}/{name}.json", {
                "ok": False, "season": current, "reason": "transactions could not be built (see the build log)"}))

    # player movement: chance of moving, outlook by position, targets (analytics/movement.py), once a day
    def movement():
        from oddsmarkets.nhl.analytics import movement as MO
        old = an.read_json(b.data / str(current) / "movement.json")
        if old and old.get("snapshot") == today.isoformat() and old.get("version") == MO.VERSION:
            return None
        return MO.build(today)
    mov = b.step("movement", movement, None)
    if mov and mov.get("season") == current:
        b.step(f"write {current}/movement.json", lambda: b.write(f"{current}/movement.json", mov))
        out["movement"] = len(mov.get("players") or [])
    # fantasy
    bt_seasons = [an.season_id(an.start_year(current) - k) for k in range(FA.BT_SEASONS, 0, -1)]
    bt = b.step("fantasy backtest (cached)", lambda: FA.backtest_cached(bt_seasons, compute=False), None)
    if bt:
        b.step("write fantasy_backtest.json", lambda: b.write("fantasy_backtest.json", bt))
    fan = b.step("fantasy", lambda: FA.build_current(current, logs, store, today, injp, rd(current, "skaters.json"),
                                                     FA.backtest_summary(bt), phase))
    b.step(f"write {current}/fantasy.json", lambda: b.write(f"{current}/fantasy.json", fan or {
        "ok": False, "season": current, "reason": "the fantasy projections could not be built (see the build log)"}))
    out["fantasy"] = len((fan or {}).get("rows") or [])
    return out


def _digest_now(today: date) -> datetime:
    """The digest's clock: now, or the end of --today's UTC day for a dated build (tests, backfills)."""
    now = datetime.now(timezone.utc)
    return now if today == now.date() else datetime(today.year, today.month, today.day, 23, 59, tzinfo=timezone.utc)


def featured_payload(cards: list[dict], odds: dict, teams_info: dict, now: datetime) -> dict:
    """digest.featured: the games that matter most, on the shared significance rule (oddsmarkets/common/featured.py:
    the NHL tier, the stage, the stakes in our season simulation, the start time and hour, live-ness; closeness a
    small bonus). {"today": [{"id", "score", "why"}] best first, "next": the big games later in the week, "week": the
    biggest game of the next seven days}.
    The front end takes the first game still upcoming or live at the reader's clock."""
    from oddsmarkets.common import featured as FT
    nick = {t: str((v or {}).get("name") or t) for t, v in (teams_info or {}).items()}

    def rivalry(h, a):
        nh, na = nick.get(h, h), nick.get(a, a)
        for pair, name in FT.RIVALRIES.items():
            x, y = tuple(pair)
            if (nh.endswith(x) and na.endswith(y)) or (nh.endswith(y) and na.endswith(x)):
                return name
        return None
    games = []
    for c in cards:
        st = "final" if c.get("status") == "final" else "live" if c.get("status") in ("live", "int") else "pre"
        if st == "final":
            continue
        h, a = c.get("home"), c.get("away")
        oh, oa = (odds or {}).get(h) or {}, (odds or {}).get(a) or {}
        sig = {"playoff": [oh.get("p_playoffs"), oa.get("p_playoffs")], "title": [oh.get("p_cup"), oa.get("p_cup")]}
        if c.get("type") == "PRE":
            sig["preseason"] = True
        ser = c.get("series")
        if c.get("type") == "PO":
            sig["stage"] = "playoff"
        if isinstance(ser, dict) and ser:
            sig["series"] = ser
        rv = rivalry(h, a)
        if rv:
            sig["rivalry"] = rv
        games.append({"sport": "hockey", "league": "NHL", "id": c.get("game_id"), "start": c.get("start"), "status": st,
                      "home": h, "away": a, "p_home": (c.get("model") or {}).get("p_home"), "wp_home": c.get("wp_home"), "sig": sig})
    r = FT.rank_featured(games, now)
    row = lambda x: {"id": x["key"].split(":", 1)[1], "score": x["score"], "why": x.get("reasons") or []}
    # "next": the big games after the build's 18-hour window, so a reader later in the day still gets one
    seen = {x["key"] for x in r["today"]}
    nxt = [x for x in FT.rank_featured(games, now, horizon_h=168, limit=13)["today"] if x["key"] not in seen][:5]
    return {"today": [row(x) for x in r["today"]], "next": [row(x) for x in nxt], "week": row(r["week"]) if r.get("week") else None}


def digest_payload(b: Build, cards: list[dict], odds: dict, phase: str | None, current: int, today: date,
                   teams_info: dict | None = None) -> dict:
    """index.json "digest": the "This week in the NHL" top lines (oddsmarkets/common/digest.py) and the featured
    candidates (oddsmarkets/common/featured.py, when present). The chance log (data/chance_log.json, one snapshot of
    every club's playoff and Cup chance per day) is carried forward from the last build; it is never read by the
    front end."""
    from oddsmarkets.common import digest as DG
    now = _digest_now(today)
    games = [{"id": c.get("game_id"), "start": c.get("start"), "status": "final" if c.get("status") == "final" else "live" if c.get("status") == "live" else "pre",
              "home": c.get("home"), "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"),
              "p_home": (c.get("model") or {}).get("p_home"), "type": c.get("type")} for c in cards]
    out: dict = {"asof": now.isoformat().replace("+00:00", "Z")[:16] + "Z"}
    rec = DG.record(games, now)
    if rec:
        rec.pop("by", None)                               # one sport here: the split is the Home page's
        out["record"] = rec
    up = DG.upset(games, now)
    if up:
        out["upset"] = up
    hot = DG.hot(games, now)
    if hot:
        out["hot"] = hot
    metric = "p_cup" if phase == "playoffs" else "p_playoffs"
    log_all = an.read_json(b.data / "chance_log.json") or {}
    log_s = (log_all.get(str(current)) or {}) if isinstance(log_all, dict) else {}
    cur = {m: {t: o.get(m) for t, o in (odds or {}).items() if o.get(m) is not None} for m in ("p_playoffs", "p_cup")}
    new_log = {m: DG.roll_log(log_s.get(m), now, cur[m]) for m in ("p_playoffs", "p_cup")}
    if any(cur.values()):
        b.write("chance_log.json", {str(current): new_log})
    mv = DG.movers(new_log.get(metric), cur.get(metric) or {}, now)
    if mv:
        out["movers"] = dict(mv, metric=metric)
    reg = [c for c in cards if c.get("type") == "REG"]
    if reg:
        days = sorted(str(c.get("date")) for c in reg if c.get("date"))
        played = sum(1 for c in reg if c.get("status") == "final")
        first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        out["stage"] = {"phase": phase, "played": played, "total": len(reg), "first": days[0], "last": days[-1],
                        "week": max(1, min((now.date() - first).days // 7 + 1, (last - first).days // 7 + 1)), "weeks": (last - first).days // 7 + 1}
    out["featured"] = featured_payload(cards, odds, teams_info or {}, now)
    return out


def index_payload(b: Build, res: dict, current: int, seasons: list[int], today: date) -> dict | None:
    """index.json from the current season's results; None (keep the old file) when the current season was not built."""
    cur = res.get(current) or {}
    if "cards" not in cur:
        return None
    cards = cur["cards"]
    t = today.isoformat()
    todays = [c for c in cards if c.get("date") == t]
    live = [c for c in cards if c.get("status") == "live"]
    recent_lo = (today - timedelta(days=2)).isoformat()
    recent = [c for c in cards if c.get("status") == "final" and recent_lo <= str(c.get("date")) < t][-30:]
    up_hi = (today + timedelta(days=3)).isoformat()
    upcoming = [c for c in cards if c.get("status") not in ("final", "live") and t < str(c.get("date")) <= up_hi][:40]
    sim = cur.get("sim") or {}
    odds = {tm: {k: an.rnd(s.get(k), 4) for k in ("p_playoffs", "p_div", "p_pres", "p_cup")} for tm, s in (sim.get("teams") or {}).items()} \
        if sim.get("ok") else {}
    teams = {tm: {"name": r.get("name"), "colour": r.get("colour"), "alt": r.get("alt"), "division": r.get("division"),
                  "conference": r.get("conference")} for tm, r in (cur.get("teams_info") or {}).items()}
    gaps = []
    for c in todays + upcoming:
        pm = (c.get("model") or {}).get("p_home")
        pk = (c.get("market") or {}).get("p_home") if c.get("market") else None
        if pm is not None and pk is not None and abs(pm - pk) >= 0.03:
            gaps.append({"kind": "game", "game_id": c["game_id"], "date": c.get("date"), "home": c.get("home"), "away": c.get("away"),
                         "model": pm, "market": pk, "edge": round(pm - pk, 4)})
    mk = an.read_json(b.data / str(current) / "markets.json") or {}
    for key, rows in ((mk.get("futures") or {}) if mk.get("ok") else {}).items():
        for r in rows or []:
            if r.get("edge") is not None and abs(r["edge"]) >= 0.03:
                gaps.append({"kind": key, "team": r["team"], "model": r.get("model"), "market": r.get("market"), "edge": r["edge"]})
    gaps.sort(key=lambda x: -abs(x.get("edge") or 0))
    return {"ok": True, "updated_at": _now(), "season": current, "phase": cur.get("phase"), "today": todays, "live": live,
            "recent": recent, "upcoming": upcoming, "playoff_odds": odds, "leaders": cur.get("leaders") or {}, "gaps": gaps[:20],
            "teams": teams, "seasons": seasons, "models": model_versions(), "sim_reason": None if sim.get("ok") else (sim or {}).get("reason"),
            "digest": b.step("digest", lambda: digest_payload(b, cards, odds, cur.get("phase"), current, today, cur.get("teams_info")), {}) or {}}


def players_index_from_stores(b: Build, seasons: list[int]) -> int:
    """players_index.json from the season stores' players alone (used with --no-careers): {pid: [name, team, pos,
    first_season, last_season]}, merged over the existing file."""
    prev = an.read_json(b.data / "players_index.json") or {}
    out = {k: v for k, v in prev.items() if isinstance(v, list)}
    for s in sorted(seasons):
        st = an.read_json(an.store_path(s)) or {}
        pl = st.get("players") or {}
        items = pl.items() if isinstance(pl, dict) else ((p.get("id"), p) for p in pl if isinstance(p, dict))
        for pid, p in items:
            pid = an.sid(pid)
            if not pid or not isinstance(p, dict):
                continue
            name = p.get("name") or " ".join(x for x in (p.get("first"), p.get("last")) if x) or None
            cur = out.get(pid)
            if cur:
                cur[0] = name or cur[0]
                cur[1] = p.get("team") or cur[1]
                cur[2] = p.get("pos") or cur[2]
                cur[3] = min(cur[3] or s, s)
                cur[4] = max(cur[4] or s, s)
            else:
                out[pid] = [name, p.get("team"), p.get("pos"), s, s]
    b.write("players_index.json", out)
    return len(out)


def calibration(b: Build, res: dict | None = None) -> None:
    """calibration.json: the game-model and season-simulation backtest (written by models/backtest.py into the same
    file; passed through untouched), plus the xG model's out-of-fold validation and MoneyPuck benchmark per season
    built this run ("xg": {season: {...}}, merged). A placeholder when neither exists."""
    from oddsmarkets.nhl.analytics import adapters
    p = b.data / "calibration.json"
    cur = b.step("calibration", adapters.calibration, None) or an.read_json(p) or {}
    if cur.get("ok") is False:
        cur = {}
    xg = {str(s): r.get("xg_cal") for s, r in (res or {}).items() if (r or {}).get("xg_cal")}
    if xg:
        cur["xg"] = {**(cur.get("xg") or {}), **xg}
        cur["xg_credit"] = an.MONEYPUCK_CREDIT
    if not cur:
        cur = {"ok": False, "reason": "no backtest yet"}
    # the committed fits the site runs on, for the Methodology page to quote (docs.js fills data-fit spans)
    cats = {}
    for kind in ("skaters", "goalies"):
        for d in sorted((x for x in b.data.iterdir() if x.is_dir() and x.name.isdigit()), reverse=True):
            c = an.read_json(d / f"{kind}.json") or {}
            if c.get("metrics"):
                cats[kind] = {"metrics": len(c["metrics"]), "season": int(d.name)}
                break
    fs = b.step("fitted", lambda: adapters.fitted_summary(cats), None)
    if fs:
        cur["fitted"] = fs
    b.write("calibration.json", cur)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="*", help="seasons to build in full, NHL ids (default: the current season)")
    ap.add_argument("--sims", type=int, default=20000, help="season simulations (default 20000)")
    ap.add_argument("--days-ahead", type=int, default=3, help="price games starting up to N days ahead (default 3)")
    ap.add_argument("--quick", action="store_true", help="few simulations (tests and smoke runs)")
    ap.add_argument("--no-market", action="store_true", help="skip the Kalshi / Polymarket fetch")
    ap.add_argument("--no-light", action="store_true", help="build only the full seasons")
    ap.add_argument("--no-careers", action="store_true", help="skip data/players/<pid>.json")
    ap.add_argument("--no-history", action="store_true", help="skip history.json")
    ap.add_argument("--no-models", action="store_true", help="catalogues from events and stints only (no builder B/C models)")
    ap.add_argument("--all-games", action="store_true", help="rebuild every game page of the page seasons")
    ap.add_argument("--game-page-seasons", type=int, default=2, help="game pages for the N most recent seasons (default 2)")
    ap.add_argument("--force", action="store_true", help="rebuild light seasons even when their inputs are unchanged")
    ap.add_argument("--no-extras", action="store_true", help="skip valuation.json, transactions / deals and fantasy")
    ap.add_argument("--no-fetch", action="store_true", help="no network for the extras (transactions, injuries, drafts, search)")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--data", default=None, help="data root (default RINK_DATA or docs/rink/data)")
    ap.add_argument("--raw", default=None, help="raw root (default RINK_RAW or data/nhl)")
    ap.add_argument("--cache", default=None, help="cache root (default RINK_CACHE or data/nhl/cache)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    t_start = time.perf_counter()
    if args.data:
        an.set_data_root(args.data)
    if args.raw:
        an.set_raw_root(args.raw)
    if args.cache:
        an.set_cache_root(args.cache)
    data = an.data_root()
    b = Build(data)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    cfg = {"sims": min(args.sims, 1000) if args.quick else args.sims, "markets": not args.no_market, "today": today,
           "days_ahead": args.days_ahead, "all_games": args.all_games, "game_page_seasons": args.game_page_seasons, "force": args.force,
           "no_careers": args.no_careers, "no_models": args.no_models}

    def css():
        dst = data.parent / "assets" / "base.css"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CSS_SRC, dst)
        b.written.append(dst)
    b.step("copy base.css", css)

    def kit():
        # The Quant design kit (docs/_design: tokens, components, chart kit) -> docs/rink/assets/qk/
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from design_kit import copy_kit
        dst = copy_kit(data.parent)
        b.written.extend(sorted(dst.glob("*")))
    b.step("copy design kit", kit)
    from oddsmarkets.nhl.analytics import glossary as GL
    b.write_or_fail("glossary.json", "glossary", GL.build)
    seasons = an.seasons_on_disk()
    if not seasons:
        logger.warning("no season stores under %s and no derived events under %s", data, an.raw_root())
    cur = an.current_season(today)
    current = cur if cur in seasons else (max(seasons) if seasons else cur)
    full = [s for s in (args.seasons or [current]) if s in seasons]
    light = [] if args.no_light else [s for s in seasons if s not in full]
    page_seasons = set(sorted(seasons)[-cfg["game_page_seasons"]:]) if cfg["game_page_seasons"] > 0 and seasons else set()
    logger.info("seasons on disk %s..%s (%d); full %s; light %d; game pages %s", seasons[0] if seasons else None,
                seasons[-1] if seasons else None, len(seasons), full, len(light), sorted(page_seasons))
    shared = {"current": current, "page_seasons": page_seasons}
    res: dict[int, dict] = {}
    for s in sorted(full + light, reverse=True):
        res[s] = b.step(f"season {s}", lambda s=s: build_season(b, s, s in full, cfg, shared), {}) or {}
    for s in seasons:                                     # seasons not built this run: their catalogues on disk
        r = res.setdefault(s, {})
        if not r.get("rows"):
            r.update(_reduced_from_disk(data / str(s), s))
        if not r.get("hist"):
            r["hist"] = (an.read_json(data / str(s) / "manifest.json") or {}).get("hist")
    gc.collect()
    vres = b.step("value", lambda: value_all(b, seasons, current, res), {}) or {}
    logger.info("value: %s", {k: v for k, v in vres.items() if k != "aging"})
    if not args.no_extras:
        xres = b.step("extras", lambda: extras_all(b, seasons, current, res, vres, today, fetch=not args.no_fetch), {}) or {}
        logger.info("extras (valuation, moves, fantasy): %s", xres)
    calibration(b, res)
    if not args.no_history:
        from oddsmarkets.nhl.analytics import history as HS
        names = {}
        for s in sorted(seasons):
            from oddsmarkets.nhl.analytics.context import _canon_teams
            names.update({t: v.get("name") for t, v in _canon_teams(s).items() if v.get("name")})
        b.write_or_fail("history.json", "history", lambda: HS.build({s: r.get("hist") or {} for s, r in res.items()}, names))
    if not args.no_careers:
        from oddsmarkets.nhl.analytics import careers as CR
        rows_by: dict[int, dict] = {}
        for s in seasons:
            rows = dict((res.get(s) or {}).get("rows") or {})
            extra = b.step(f"stats rows {s}", lambda s=s: CR.stats_rows(s), {}) or {}
            for p, r in extra.items():
                if p in rows and str(rows[p].get("name") or p) == p and r.get("name"):
                    rows[p] = {**rows[p], "name": r["name"]}
                rows.setdefault(p, r)
            rows_by[s] = rows
        blocks: dict[str, dict] = {}
        people: dict[str, dict] = {}
        for s in sorted(res):
            people.update({p: v for p, v in ((res[s] or {}).get("people") or {}).items() if p})
            for pid, blk in ((res[s] or {}).get("blocks") or {}).items():
                if pid not in blocks or blocks[pid].get("season", 0) < blk.get("season", 0):
                    blocks[pid] = blk

        def old_reader(pid):
            p = data / "players" / f"{pid}.json"
            return an.read_json(p) if p.exists() else None

        def cat_reader(s, fn):
            p = data / str(s) / fn
            return an.read_json(p) if p.exists() else None
        n_prev = b.step("last-season percentiles", lambda: CR.add_prev_pct(blocks, cat_reader), 0)
        logger.info("careers: last-season percentiles on %s current blocks", n_prev)
        idx = b.step("careers", lambda: CR.write_careers(b.write, rows_by, blocks, old_reader, current, people), {}) or {}
        if idx:
            prev = an.read_json(data / "players_index.json") or {}
            prev = {k: v for k, v in prev.items() if isinstance(v, list)}
            prev.update(idx)
            b.step("players_index", lambda: b.write("players_index.json", prev))
        logger.info("careers: %d players indexed", len(idx))
        del rows_by, blocks, people
    else:
        b.step("players_index (stores)", lambda: players_index_from_stores(b, seasons))
    idx_payload = b.step("index", lambda: index_payload(b, res, current, seasons, today), None)
    if idx_payload:
        b.step("write index.json", lambda: b.write("index.json", idx_payload))
    else:
        logger.warning("index.json kept: the current season %s was not built this run", current)
    total = sum(p.stat().st_size for p in set(b.written) if p.exists())
    logger.info("wrote %d files (%.1f MB) in %.1f s; %d step errors", len(set(b.written)), total / 1e6, time.perf_counter() - t_start,
                len(b.errors))
    for k, v in sorted(b.timings.items(), key=lambda kv: -kv[1])[:25]:
        logger.info("  %-60s %7.1f s", k, v)
    for e in b.errors[:60]:
        logger.info("  error: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
