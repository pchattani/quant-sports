#!/usr/bin/env python
"""
Build The Quant Gridiron's payloads (oddsmarkets/nfl/PAYLOADS.md) into docs/gridiron/data/.

Site-wide: index.json, glossary.json, calibration.json, history.json (1999 onward, era-adjusted), coaches.json,
referees.json, players_index.json, players/<pid>.json (careers); and docs/gridiron/assets/qk/ (the shared design kit, copied from
docs/_design).

Per season, data/<S>/: players.json, teams.json, season.json, schedule.json, weeks/<w>.json, fourth_downs.json,
referees.json, leaders.json, lab.json, awards.json, value.json (player value and the best at each position),
markets.json, trade.json and needs/<abbr>.json (current season: the trade simulator and each team's strengths and
needs, docs/VALUE_SECTIONS.md), games/<game_id>.json and manifest.json (input signatures, frozen pre-game prices and
page signatures, so unchanged work is skipped).

Seasons come in two weights:
  full   (--seasons, default the current season): season simulation (--sims), game-model prices for games not yet
         final in the pricing window (today - 1 .. today + --days-ahead), markets, award races, team-strength history
         and the player "current" blocks of the career files.
  light  every other season with a store or play-by-play (skip with --no-light): catalogues, teams, season.json
         without a simulation, weeks, fourth downs, referees, leaders, lab, awards (ranking); a light season whose
         inputs are unchanged since its manifest is skipped (--force rebuilds it).
Game pages are written for the --game-page-seasons most recent seasons (default 2): pages whose signature changed
(status, score, lines, QBs, plays on the table, model versions) plus every not-final game of the current season in
the pricing window; --all-games rebuilds every page of those seasons. A page is never downgraded: without the game's
play-by-play on this machine the old page's play-level blocks are kept.

Memory: one season of plays at a time; the context is released after each season.

Every step is isolated: a failure is logged with its traceback and the build goes on; a payload that cannot be
built is written as {"ok": false, "reason": ...}; index.json is never overwritten when the current season was not
built this run.

Roots: --data / GRIDIRON_DATA (default docs/gridiron/data), --raw / GRIDIRON_RAW (default data/nfl), --cache /
GRIDIRON_CACHE (default data/nfl/cache).

    python scripts/build_gridiron.py                                 # current season full, the rest light
    python scripts/build_gridiron.py --seasons 2026 2025
    python scripts/build_gridiron.py --quick --no-market --no-light   # fast local check
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.nfl import analytics as an  # noqa: E402

logger = logging.getLogger("build_gridiron")
BUILD_VERSION = 2              # 2: value.json for every season (15 Oct 2026)


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
        an.write_json(p, payload)
        self.written.append(p)

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
    from oddsmarkets.nfl.analytics import adapters
    gp = None
    try:
        from oddsmarkets.nfl.models import game as GMm
        gp = hashlib.sha1(repr(sorted(GMm.params().items())).encode()).hexdigest()[:12]
    except Exception:                                            # noqa: BLE001
        pass
    return {**adapters.model_versions(), "fits": adapters.fitted_keys(), "game_params": gp}


def season_sig(season: int) -> dict:
    from oddsmarkets.nfl.analytics.context import release_files
    files = {}
    for rel in ("pbp", "ftn_charting", "pbp_participation", "nextgen_stats", "schedules", "players"):
        fs = release_files(rel, season) if rel not in ("nextgen_stats", "players", "schedules") else release_files(rel)
        files[rel] = [_file_sig(p) for p in fs[:6]]
    return {"version": BUILD_VERSION, "store": _content_sig(an.store_path(season)), "files": files, "models": model_versions()}


# ---------------------------------------------------------------------------------------------- one season

def build_season(b: Build, season: int, full: bool, cfg: dict, shared: dict) -> dict:
    from oddsmarkets.nfl.analytics import careers as CR
    from oddsmarkets.nfl.analytics import fourth as FD
    from oddsmarkets.nfl.analytics import history as HS
    from oddsmarkets.nfl.analytics import leaders as LD
    from oddsmarkets.nfl.analytics import players as PL
    from oddsmarkets.nfl.analytics import season as SN
    from oddsmarkets.nfl.analytics import teams as TM
    from oddsmarkets.nfl.analytics.context import SeasonContext
    t0 = time.perf_counter()
    d = f"{season}/"
    sdir = b.data / str(season)
    manifest = an.read_json(sdir / "manifest.json") or {}
    sig = season_sig(season)
    current = season == shared["current"]
    skip = None
    # last season's catalogue feeds the player files' last-season role percentiles (careers.add_prev_pct): rebuild it
    # once if it predates the role fields (9d6e9722), even when its inputs are unchanged
    stale_roles = season == shared["current"] - 1 and (sdir / "players.json").exists() and \
        not any("pct_role" in r for r in ((an.read_json(sdir / "players.json") or {}).get("players") or {}).values())
    if not full and not cfg["force"] and manifest.get("sig") == sig and (sdir / "players.json").exists() \
            and season not in shared["page_seasons"] and not stale_roles:
        skip = "inputs unchanged"
    elif not current and not cfg["force"] and not sig["files"]["pbp"] and (an.read_json(sdir / "players.json") or {}).get("ok"):
        skip = "play-by-play not on this machine; payloads kept"
    if skip:
        logger.info("%s: %s, skipped", season, skip)
        if not (sdir / "performers.json").exists() and (sdir / "players.json").exists():
            # a season built before the standings page's performers: derive them from the payloads on disk
            from oddsmarkets.nfl.analytics import performers as PF
            b.write_or_fail(d + "performers.json", f"performers {season}",
                            lambda: PF.build(an.read_json(sdir / "players.json"), an.read_json(sdir / "value.json"), season), season=season)
        return {"skipped": True, "rows": CR.reduce_cat(an.read_json(sdir / "players.json"), season), "league": manifest.get("league"),
                "fourth": an.read_json(sdir / "fourth_downs.json"), "referees": an.read_json(sdir / "referees.json")}
    ctx = SeasonContext(season, full=full, today=cfg["today"], current=current, sims=cfg["sims"],
                        fetch_markets=cfg["markets"] and full and current, use_models=not cfg["no_models"])
    logger.info("%s (%s): %d games (%s), phase %s, week %s, pbp %s", season, "full" if full else "light", len(ctx.games),
                ctx.store_source, ctx.phase, ctx.week, ctx.has_pbp())
    cat = b.write_or_fail(d + "players.json", f"players {season}", lambda: PL.build(ctx), season=season)
    markets = b.step(f"markets fetch {season}", ctx.markets, {}) if ctx.fetch_markets else {}
    from oddsmarkets.nfl.analytics import adapters
    prices: dict[str, dict] = {}
    if full and current:
        prices = b.step(f"game prices {season}", lambda: price_window(ctx, cfg), {}) or {}
    wf = b.step(f"walk-forward prices {season}", lambda: adapters.walk_forward_prices(ctx), {}) or {}
    frozen = dict(manifest.get("prices") or {})
    for gid, pr in prices.items():
        if pr.get("p_home") is not None:
            frozen[gid] = {k: pr.get(k) for k in ("p_home", "spread", "total", "home_pts", "away_pts")} | {"source": "frozen"}
    sched = b.write_or_fail(d + "schedule.json", f"schedule {season}", lambda: SN.schedule(ctx, prices, frozen, markets, wf), season=season)
    cards = (sched or {}).get("games") or []
    sim = b.step(f"season sim {season}", ctx.sim, None) if full and current else None
    tms = b.write_or_fail(d + "teams.json", f"teams {season}", lambda: TM.build(ctx, cat, sim, cards), season=season)
    spl = b.write_or_fail(d + "season.json", f"season {season}",
                          lambda: with_league(b, season, SN.build(ctx, tms, sim, cards), tms, cards, cfg) if full and current
                          else SN.build(ctx, tms, sim, cards), season=season)

    def weeks():
        wk = SN.weeks(ctx, cards, tms)
        for w, p in wk.items():
            b.write(f"{season}/weeks/{w}.json", p)
        return len(wk)
    b.step(f"weeks {season}", weeks)
    fd = b.write_or_fail(d + "fourth_downs.json", f"fourth downs {season}", lambda: FD.build(ctx), season=season)
    refs = b.write_or_fail(d + "referees.json", f"referees {season}", lambda: FD.referees_season(ctx), season=season)
    b.write_or_fail(d + "leaders.json", f"leaders {season}", lambda: LD.build(season, cat, tms), season=season)
    b.write_or_fail(d + "lab.json", f"lab {season}", lambda: LD.lab(season, cat, tms), season=season)
    value_pages(b, ctx, cfg, cat, tms, sim, full and current)
    if full and current and not cfg.get("no_fantasy"):
        fantasy_pages(b, ctx)
    aw_model = None
    if full and current:
        aw_model = b.step(f"awards model {season}", lambda: adapters.awards(ctx, sim), None)
    awards = b.write_or_fail(d + "awards.json", f"awards {season}", lambda: LD.awards(ctx, cat, aw_model), season=season)
    if full and current:
        b.write_or_fail(d + "markets.json", f"markets {season}", lambda: SN.markets_payload(ctx, sim, aw_model, cards, markets), season=season)
    league = b.step(f"league summary {season}", lambda: HS.league_summary(ctx), None)
    # game pages
    pages = manifest.get("games") or {}
    if season in shared["page_seasons"]:
        pages = b.step(f"game pages {season}", lambda: game_pages(b, ctx, cfg, manifest, prices, cards, cat, tms, frozen, wf, markets),
                       pages) or pages
    blocks = {}
    if full and not cfg["no_careers"]:
        blocks = b.step(f"player blocks {season}", lambda: CR.current_blocks(ctx, cat, an.read_json(sdir / "value.json")), {}) or {}
    rows = CR.reduce_cat(cat, season) if (cat or {}).get("ok") else CR.reduce_cat(an.read_json(sdir / "players.json"), season)
    out = {"rows": rows, "blocks": blocks, "current": current, "phase": ctx.phase, "week": ctx.week, "league": league,
           "fourth": fd if (fd or {}).get("ok") else None, "referees": refs if (refs or {}).get("ok") else None}
    if full and current:
        from oddsmarkets.nfl.analytics import leaders as LD2
        out.update(cards=cards, season_payload=spl, teams=tms, sim=sim, leaders=LD2.index_leaders(cat), markets=markets,
                   futures=None, teams_info=ctx.teams)
        mk = an.read_json(sdir / "markets.json") or {}
        out["futures"] = mk.get("futures") if mk.get("ok") else None
    manifest = {"sig": sig, "built_at": _now(), "full": full, "phase": ctx.phase, "week": ctx.week, "games": pages, "prices": frozen,
                "league": league, "model_errors": dict(ctx.model_errors), "store_source": ctx.store_source,
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
    """season.json with its "league" block (how the playoff race is shaping up, strengths and weaknesses:
    oddsmarkets/nfl/analytics/race.py on oddsmarkets/common/league.py) and data/race_log.json carried forward (the
    whole season's chances, one snapshot a day; the opening day and each Tuesday before live tracking rebuilt from the
    season simulation as of that date, inside a time budget a build). A failure leaves season.json as it was."""
    if not isinstance(spl, dict) or not spl.get("ok", True):
        return spl
    from oddsmarkets.nfl.analytics import race as RC

    def run():
        prev = an.read_json(b.data / "race_log.json") or {}
        runner = None if cfg.get("no_models") else RC.asof_runner(season)
        blk, log = RC.build(season, spl, tms, cards, prev, _digest_now(cfg.get("today")), run_asof=runner)
        if log.get(str(season)):
            b.write("race_log.json", log)
        return blk
    blk = b.step(f"league block {season}", run, None)
    if blk:
        spl["league"] = blk
    return spl


def value_pages(b: Build, ctx, cfg: dict, cat: dict | None, tms: dict | None, sim: dict | None, full_current: bool) -> None:
    """value.json for every season; for the full current season also the sensitivity curves (season_sim), trade.json
    and needs/<abbr>.json (docs/VALUE_SECTIONS.md)."""
    from oddsmarkets.nfl.analytics import adapters
    from oddsmarkets.nfl.analytics import contracts as CT
    from oddsmarkets.nfl.analytics import value as VL
    season, d = ctx.season, f"{ctx.season}/"
    if not (cat or {}).get("ok") and not full_current:
        return
    sens = None
    if full_current and sim is not None and (sim or {}).get("ok"):
        n_s = 300 if cfg["sims"] <= 1000 else 2000
        sens = b.step(f"sensitivity {season}", lambda: adapters.season_sensitivity(ctx, sim, n=n_s), None)
    prev_cat = an.read_json(b.data / str(season - 1) / "players.json")
    prev_cat = prev_cat if (prev_cat or {}).get("ok") else None
    prev_pv = b.step(f"player value {season - 1}", lambda: adapters.player_value_season(ctx, season - 1), None) if full_current else None
    if cfg.get("contracts"):
        CT.set_enabled(True)
    on = CT.enabled()
    tab = b.step(f"contracts {season}", lambda: CT.table(season), {}) if (on and full_current) else {}
    res = b.step(f"value {season}", lambda: VL.build(ctx, cat, tms, sim if full_current else None, sens, prev_cat, prev_pv, tab, on), None) or {}
    b.write_or_fail(d + "value.json", f"value page {season}", lambda: res.get("value"), season=season)
    # the standings page's top and bottom performers (oddsmarkets/nfl/analytics/performers.py)
    from oddsmarkets.nfl.analytics import performers as PF
    b.write_or_fail(d + "performers.json", f"performers {season}", lambda: PF.build(cat, res.get("value"), season), season=season)
    if full_current:
        b.write_or_fail(d + "trade.json", f"trade {season}", lambda: res.get("trade"), season=season)
        for t, pl in (res.get("needs") or {}).items():
            b.step(f"write needs {t}", lambda t=t, pl=pl: b.write(f"{season}/needs/{t}.json", pl))
        if sens:
            logger.info("%s: sensitivity %s (%s s, n %s)", season, "cached" if sens.get("cached") else "computed", sens.get("runtime_s"), sens.get("n"))
        vc = res.get("_ctx")
        if vc:
            val = b.write_or_fail(d + "valuation.json", f"valuation {season}", lambda: valuation_payload(season, vc), season=season)
            if not cfg.get("no_transactions"):
                transactions_pages(b, season, cfg, vc, val if (val or {}).get("ok") else None)
            if not cfg.get("no_transactions"):
                b.step(f"movement {season}", lambda: movement_page(b, season, cfg))


def movement_page(b: Build, season: int, cfg: dict) -> None:
    """<S>/movement.json (analytics/movement.py: chance of moving, outlook, targets), refreshed once a day."""
    from oddsmarkets.nfl.analytics import movement as MVN
    rel = f"{season}/movement.json"
    old = an.read_json(b.data / rel) if (b.data / rel).exists() else None
    if old and old.get("snapshot") == cfg["today"].isoformat() and old.get("version") == MVN.VERSION:
        return
    pay = MVN.build(cfg["today"])
    if pay and pay.get("season") == season:
        b.write(rel, pay)


def fantasy_pages(b: Build, ctx) -> None:
    """<S>/fantasy.json for the week to come and fantasy_backtest.json (analytics/fantasy_model.py). The model's
    constants and the 2019-2025 walk-forward backtest are fitted offline (models/fitted/fantasy.json, refitted with
    scripts/nfl_fantasy_fit.py); the build adds this season's weeks so far."""
    from oddsmarkets.nfl.analytics import fantasy_model as FM
    season = ctx.season
    wk = an.inum(getattr(ctx, "week", None))
    if ctx.phase not in ("regular", "preseason") or not wk or wk > 18:
        b.write(f"{season}/fantasy.json", {"ok": False, "season": season, "reason": "projections run in the regular season"})
        return
    P = FM.load_params()
    fitted = an.read_json(FM.fitted_path()) or {}
    pl = b.write_or_fail(f"{season}/fantasy.json", f"fantasy {season}", lambda: FM.build(season, wk, P, fitted), season=season)
    cur = b.step(f"fantasy backtest {season}", lambda: FM.current_backtest(season, wk, P), None)

    def bt():
        if not fitted.get("backtest"):
            return {"ok": False, "reason": "the fantasy model has not been fitted (scripts/nfl_fantasy_fit.py)"}
        return {"ok": True, "updated_at": an.now(), "version": fitted.get("version"), "fitted_at": fitted.get("fitted_at"),
                "tune_seasons": fitted.get("tune_seasons"), "eval_seasons": fitted.get("eval_seasons"), "grid": fitted.get("grid"),
                "params": fitted.get("params"), "sd": fitted.get("sd"), "backtest": fitted.get("backtest"),
                "current": {"season": season, **cur} if cur else None, "credits": [an.NFLVERSE_CREDIT]}
    b.write_or_fail("fantasy_backtest.json", "fantasy backtest", bt)
    del pl


def valuation_payload(season: int, vc: dict) -> dict:
    """valuation.json (analytics/valuation.py) from the value build's inputs; before the season's first games the
    records are last season's, so they enter as last season's form."""
    from oddsmarkets.nfl.analytics import valuation as VA
    recs = vc["recs"]
    if vc.get("basis") != season:
        recs = {p: dict(rc, src=season - 1) for p, rc in recs.items()}
    return VA.build(season, recs, vc.get("qbs"), float(vc.get("np") or 35.0), float(vc.get("qb_new") or -0.02), vc.get("remaining") or {},
                    float(vc.get("k_resp") or 0.85), vc.get("prev_recs"), vc.get("unsigned"),
                    tg_cur=vc.get("tg") if vc.get("basis") == season else None, roster=vc.get("roster"))


def transactions_pages(b: Build, season: int, cfg: dict, vc: dict, val: dict | None) -> None:
    """transactions.json and ledgers/<abbr>.json (analytics/transactions.py): ESPN's notes for the last twelve months,
    cached under <cache>/espn/transactions (refetched at most every six hours; never with --no-market)."""
    from oddsmarkets.nfl.analytics import transactions as TX
    out = b.step(f"transactions {season}", lambda: TX.run(season, cfg["today"], vc["recs"], val, vc.get("roster") or {}, float(vc.get("k_resp") or 0.85),
                                                          list(vc.get("teams") or []), fetch=bool(cfg.get("markets"))), None) or {}
    b.write_or_fail(f"{season}/transactions.json", f"transactions page {season}", lambda: out.get("transactions"), season=season)
    for t, pl in (out.get("ledgers") or {}).items():
        b.step(f"write ledger {t}", lambda t=t, pl=pl: b.write(f"{season}/ledgers/{t}.json", pl))


def price_window(ctx, cfg: dict) -> dict[str, dict]:
    """Game-model prices for the season's games not yet final, kicking off from yesterday to --days-ahead."""
    from oddsmarkets.nfl.analytics import adapters
    lo = cfg["today"] - timedelta(days=1)
    hi = cfg["today"] + timedelta(days=cfg["days_ahead"])
    due = []
    for gid, g in ctx.games.items():
        if g.get("status") == "final":
            continue
        try:
            dd = date.fromisoformat(str(g.get("date") or g.get("kickoff") or "")[:10])
        except ValueError:
            continue
        if lo <= dd <= hi:
            due.append(g)
    logger.info("%s: pricing %d games", ctx.season, len(due))
    out = adapters.game_prices(ctx, due)
    n = 2000 if cfg["sims"] <= 1000 else 10000
    for gid in out:
        out[gid]["priced_at"] = _now()
        d = adapters.price_dist(ctx, out[gid], ctx.games[gid], n=n)
        if d:
            out[gid]["dist"] = d
    return out


def _stub(p: Path) -> bool:
    """A final game's page that holds a failure stub or no play-level data (an empty page): rebuilt on the next run even
    when its signature matches (pages failed before 21 Oct 2026 were still signed). Only small files are read."""
    try:
        if p.stat().st_size > 24_000:
            return False
    except OSError:
        return False
    d = an.read_json(p) or {}
    return not d.get("ok") or not (d.get("plays") or d.get("espn_plays"))


def game_pages(b: Build, ctx, cfg: dict, manifest: dict, prices: dict, cards: list[dict], cat: dict | None, tms: dict | None,
               frozen: dict | None = None, wf: dict | None = None, markets: dict | None = None) -> dict:
    import pandas as pd
    from oddsmarkets.nfl.analytics import games as GM
    from oddsmarkets.nfl.analytics import people
    from oddsmarkets.nfl.analytics import season as SN
    old_sigs = dict(manifest.get("games") or {})
    mv = model_versions()
    gdir = b.data / str(ctx.season) / "games"
    by_card = {c["game_id"]: c for c in cards}
    P = ctx.plays() if ctx.has_pbp() else pd.DataFrame(columns=["game_id"])
    counts = P.groupby("game_id").size().to_dict() if len(P) else {}
    lo = cfg["today"] - timedelta(days=1)
    hi = cfg["today"] + timedelta(days=cfg["days_ahead"])
    due, new_sigs = [], {}
    for gid, g in ctx.games.items():
        if gid not in by_card:
            continue
        ep = GM.espn_plays(g)
        s = GM.page_sig(g, counts.get(gid, 0), mv, len(ep or []))
        new_sigs[gid] = s
        exists = (gdir / f"{gid}.json").exists()
        try:
            dd = date.fromisoformat(str(g.get("date") or g.get("kickoff") or "")[:10])
        except ValueError:
            dd = None
        live = g.get("status") != "final"
        in_window = dd is not None and lo <= dd <= hi
        if cfg["all_games"] or not exists or old_sigs.get(gid) != s or (ctx.current and live and in_window)                 or (not live and _stub(gdir / f"{gid}.json")):
            due.append(gid)
    logger.info("%s: %d game pages due of %d", ctx.season, len(due), len(by_card))
    if not due:
        return new_sigs
    names = {p: r.get("name") for p, r in ((cat or {}).get("players") or {}).items()}
    for c_id, c_nm in (("passer_player_id", "passer_player_name"), ("rusher_player_id", "rusher_player_name"),
                       ("receiver_player_id", "receiver_player_name")):
        if c_id in P and c_nm in P:
            dd_ = P[[c_id, c_nm]].dropna().drop_duplicates(c_id)
            for a, nm in zip(dd_[c_id].astype(str), dd_[c_nm].astype(str)):
                names.setdefault(a, nm)
    ppl = people.people()

    class Names(dict):
        def __missing__(self, k):
            return (ppl.get(k) or {}).get("name")

        def get(self, k, default=None):
            v = dict.get(self, k)
            return v if v is not None else ((ppl.get(k) or {}).get("name") or default)
    nm = Names(names)
    ngs: dict[tuple, dict] = {}
    for kind in ("passing", "rushing", "receiving"):
        df = ctx.ngs_weekly(kind)
        if df is not None and len(df) and "player_gsis_id" in df:
            for r in df.to_dict("records"):
                ngs[(kind, str(r["player_gsis_id"]), an.inum(r.get("week")))] = r
    tt = (tms or {}).get("teams") or {}
    from oddsmarkets.nfl.analytics import adapters
    inj = b.step(f"injuries {ctx.season}", lambda: GM.injuries_by_game(ctx), {}) or {}
    avail = b.step(f"availability {ctx.season}", lambda: GM.availability_by_game(ctx), {}) or {}
    mk_games = (markets or {}).get("games") or {}
    groups = {k: v for k, v in P[P["game_id"].isin(set(due))].groupby("game_id")} if len(P) else {}
    written = 0
    for gid in due:
        g = ctx.games[gid]
        old = an.read_json(gdir / f"{gid}.json") if (gdir / f"{gid}.json").exists() else None
        pr = prices.get(gid) or (frozen or {}).get(gid) or (wf or {}).get(gid)
        pregame = None
        if pr:
            if not pr.get("dist"):
                pr = {**pr, "dist": b.step(f"dist {gid}", lambda pr=pr, g=g: adapters.price_dist(ctx, pr, g, n=0), None)}
            pregame = {"model": pr, "source": pr.get("source") or "game", "market": (by_card.get(gid) or {}).get("market"),
                       "market_detail": mk_games.get(gid), "line": g.get("lines"), "priced_at": pr.get("priced_at"),
                       "qbs": (by_card.get(gid) or {}).get("qbs"), "weather": GM.weather(g)}
        wk = an.inum(g.get("week"))
        ngs_w = {(k, p): r for (k, p, w), r in ngs.items() if w == wk}

        def build(g=g, gid=gid, old=old, pregame=pregame, ngs_w=ngs_w):
            G = groups.get(gid)
            return GM.build_page(ctx, g, G, by_card.get(gid) or GM.card(ctx, g), pregame, old, nm, ngs_w,
                                 SN.matchup(tt.get(g.get("home")), tt.get(g.get("away"))), inj, avail)
        payload = b.step(f"game {gid}", build)
        if payload is None:
            payload = {"ok": False, "reason": "game page could not be built", "game_id": gid}
            new_sigs[gid] = None                                 # unsigned: the next build retries it
        b.write(f"{ctx.season}/games/{gid}.json", payload)
        written += 1
    del groups
    gc.collect()
    logger.info("%s: %d game pages written", ctx.season, written)
    return new_sigs


# ---------------------------------------------------------------------------------------------- site-wide

def _digest_now(today: date | None) -> datetime:
    """The digest's clock: now, or the end of --today's UTC day for a dated build (tests, backfills)."""
    now = datetime.now(timezone.utc)
    return now if today is None or today == now.date() else datetime(today.year, today.month, today.day, 23, 59, tzinfo=timezone.utc)


POST_STAGE = {"WC": "playoff", "DIV": "quarter", "CON": "semi", "SB": "final"}
POST_NAME = {"WC": "Wild Card round", "DIV": "Divisional round", "CON": "Conference championships", "SB": "Super Bowl"}


def _card_status(c: dict) -> str:
    st = str(c.get("status") or "")
    return "final" if st == "final" else "live" if st == "live" else "pre"


def featured_payload(cards: list[dict], odds: dict, teams_info: dict, now: datetime) -> dict:
    """digest.featured: the games that matter most on the shared significance rule (oddsmarkets/common/featured.py:
    the NFL tier, the postseason round, the playoff and Super Bowl stakes in our season simulation, the start time
    and hour, live-ness; closeness a small bonus; known rivalries). {"today": [{"id", "score", "why"}] best first,
    "week": the biggest game of the next seven days}. The front end takes the first game still upcoming or live at
    the reader's clock."""
    from oddsmarkets.common import featured as FT
    nick = {t: str((v or {}).get("name") or t) for t, v in (teams_info or {}).items()}

    def rivalry(h, a):
        nh, na = nick.get(h, h), nick.get(a, a)
        for pair, name in FT.RIVALRIES.items():
            x, y = tuple(pair)
            if (nh.endswith(" " + x) and na.endswith(" " + y)) or (nh.endswith(" " + y) and na.endswith(" " + x)):
                return name
        return None
    games = []
    for c in cards:
        st = _card_status(c)
        if st == "final":
            continue
        h, a = c.get("home"), c.get("away")
        oh, oa = (odds or {}).get(h) or {}, (odds or {}).get(a) or {}
        sig = {"title": [oh.get("p_sb"), oa.get("p_sb")]}
        gt = str(c.get("gtype") or "REG")
        if gt in POST_STAGE:
            sig["stage"] = POST_STAGE[gt]
        else:
            sig["playoff"] = [oh.get("p_playoffs"), oa.get("p_playoffs")]
        if gt == "PRE":
            sig["preseason"] = True
        rv = rivalry(h, a)
        if rv:
            sig["rivalry"] = rv
        games.append({"sport": "nfl", "league": "NFL", "id": c.get("game_id"), "start": c.get("kickoff"), "status": st,
                      "home": h, "away": a, "p_home": (c.get("model") or {}).get("p_home"), "wp_home": c.get("wp_home"), "sig": sig})
    r = FT.rank_featured(games, now)

    def row(x):
        return {"id": x["key"].split(":", 1)[1], "score": x["score"], "why": x.get("reasons") or []}
    return {"today": [row(x) for x in r["today"]], "week": row(r["week"]) if r.get("week") else None}


def digest_payload(b: Build, cards: list[dict], odds: dict, phase: str | None, week: int | None, current: int, today: date | None,
                   teams_info: dict | None = None) -> dict:
    """index.json "digest": the "This week in the NFL" top lines (oddsmarkets/common/digest.py), the stage (the week
    and the regular season's length) and the featured candidates (featured.py). Finished games carry the frozen
    pre-game price (manifest "prices", written before kick-off) or the walk-forward backtest price, never one made
    after the game: no look-ahead. A tie has no result and is left out of the record. chance_log.json keeps one
    snapshot a day of every team's playoff and Super Bowl chance for the movers; the front end never reads it."""
    from oddsmarkets.common import digest as DG
    now = _digest_now(today)
    games = [{"id": c.get("game_id"), "sport": "nfl", "start": c.get("kickoff"), "status": _card_status(c), "home": c.get("home"),
              "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"), "p_home": (c.get("model") or {}).get("p_home")} for c in cards]
    out: dict = {"asof": now.isoformat().replace("+00:00", "Z")[:16] + "Z"}
    rec = DG.record(games, now)
    if rec:
        rec.pop("by", None)                               # one sport here: the split is the Home page's
        out["record"] = rec
    for k, v in (("upset", DG.upset(games, now)), ("hot", DG.hot(games, now, min_games=1))):
        if v:
            out[k] = v
    post = any(str(c.get("gtype")) in POST_STAGE and _card_status(c) != "final" for c in cards)
    cur = {m: {t: o.get(m) for t, o in (odds or {}).items() if o.get(m) is not None} for m in ("p_playoffs", "p_sb")}
    log_all = an.read_json(b.data / "chance_log.json") or {}
    log_s = (log_all.get(str(current)) or {}) if isinstance(log_all, dict) else {}
    new_log = {m: DG.roll_log(log_s.get(m), now, cur[m]) for m in cur}
    if any(cur.values()):
        b.write("chance_log.json", {str(current): new_log})
    metric = "p_sb" if post else "p_playoffs"
    mv = DG.movers(new_log.get(metric), cur.get(metric) or {}, now)
    if mv:
        out["movers"] = dict(mv, metric=metric)
    reg = [c for c in cards if str(c.get("gtype") or "REG") == "REG"]
    st: dict = {"phase": phase, "week": week}
    if reg:
        days = sorted(str(c.get("kickoff"))[:10] for c in reg if c.get("kickoff"))
        st.update(played=sum(1 for c in reg if c.get("status") == "final"), total=len(reg), weeks=max((c.get("week") or 0) for c in reg))
        if days:
            st.update(first=days[0], last=days[-1])
    rounds = [str(c.get("gtype")) for c in cards if str(c.get("gtype")) in POST_STAGE and _card_status(c) != "final"]
    if rounds:
        order = list(POST_STAGE)
        r0 = min(rounds, key=order.index)
        st.update(round=r0, round_name=POST_NAME[r0])
    out["stage"] = st
    out["featured"] = featured_payload(cards, odds, teams_info or {}, now)
    return out


def index_payload(b: Build, res: dict, current: int, seasons: list[int], today: date | None = None) -> dict | None:
    """index.json from the current season's results; None (keep the old file) when the current season was not built."""
    from oddsmarkets.nfl.analytics import season as SN
    cur = res.get(current) or {}
    if not cur.get("cards"):
        return None
    cards = cur["cards"]
    wk = cur.get("week")
    games = [c for c in cards if c.get("week") == wk]
    live = [c for c in cards if c.get("status") == "live"]
    recent = [c for c in cards if c.get("status") == "final" and wk is not None and (c.get("week") or 0) in (wk - 1, wk)][-24:]
    sp = cur.get("season_payload") or {}
    top: dict[str, list] = {}
    for conf, v in (sp.get("seeds_today") or {}).items():
        rec = {r["team"]: r for d in sp.get("standings") or [] for r in d.get("teams") or []}
        top[conf] = [[t, (rec.get(t) or {}).get("w"), (rec.get(t) or {}).get("l"), (rec.get(t) or {}).get("t"), i + 1]
                     for i, t in enumerate(v.get("seeds") or [])]
    sim = cur.get("sim") or {}
    odds = {t: {k: an.rnd(s.get(k), 4) for k in ("p_playoffs", "p_div", "p_bye", "p_sb")} for t, s in (sim.get("teams") or {}).items()} \
        if sim.get("ok") else {}
    teams = {t: {"name": r.get("name"), "colour": r.get("colour"), "alt": r.get("alt"), "division": r.get("division"),
                 "conference": r.get("conference")} for t, r in (cur.get("teams_info") or {}).items()}
    return {"ok": True, "updated_at": _now(), "season": current, "week": wk, "phase": _phase(cur.get("phase")), "games": games, "live": live,
            "recent": recent, "standings_top": top, "playoff_odds": odds, "leaders": cur.get("leaders") or {},
            "gaps": SN.gaps(cards, cur.get("futures")), "teams": teams, "seasons": seasons, "models": model_versions(),
            "sim_reason": None if sim.get("ok") else (sim or {}).get("reason"),
            "digest": b.step("digest", lambda: digest_payload(b, cards, odds, _phase(cur.get("phase")), wk, current, today, cur.get("teams_info")), {}) or {}}


def calibration(b: Build, adapters) -> None:
    """calibration.json, merged: builder C's sections (game_model, season_sim: models/backtest.py's write_calibration)
    and any other section are kept as they are; when C's sections are missing they are restored from the backtest
    output cached under <cache>/analytics/backtest_out.json (or a backtest payload function, when C provides one).
    This build owns only "ep" and "wp" (builder B's validation in models/fitted/<ep|wp>.json), "ok" and "updated_at"."""
    p = b.data / "calibration.json"
    cur = an.read_json(p) or {}
    if cur.get("ok") is False and set(cur) <= {"ok", "reason"}:
        cur = {}
    cur.pop("backtest", None)                                    # an empty placeholder from earlier builds
    cur.pop("backtest_reason", None)
    if not cur.get("game_model"):
        bt = adapters.calibration() or an.read_json(an.an_cache() / "backtest_out.json")
        if isinstance(bt, dict) and bt.get("metrics"):
            cur["game_model"] = {k: v for k, v in bt.items() if k != "season_sim"}
            cur["season_sim"] = bt.get("season_sim")
    fitted = ROOT / "oddsmarkets" / "nfl" / "models" / "fitted"
    for name in ("ep", "wp"):
        f = an.read_json(fitted / f"{name}.json") or {}
        if f.get("validation"):
            cur[name] = {"version": f.get("version"), "seasons": f.get("seasons"), "n": f.get("n"), "validation": f["validation"]}
    if not any(k in cur for k in ("ep", "wp", "game_model", "season_sim")):
        cur = {"ok": False, "reason": "no backtest and no EP / WP validation yet"}
    else:
        cur["ok"] = True
        cur["updated_at"] = calibration_stamp(cur) or _now()
    b.write("calibration.json", cur)


def calibration_stamp(cur: dict) -> str | None:
    """calibration.json's updated_at is its content's stamp (the backtest's generated_at), never the build time: CI
    restores the deployed copy over the committed one when its stamp is newer (ci_site.py restore, newer_wins), so a
    build-time stamp kept the 2 Oct backtest on the site after the 21 Oct refit was committed (accuracy audit,
    22 Oct 2026)."""
    gm = cur.get("game_model") if isinstance(cur.get("game_model"), dict) else {}
    return str(gm.get("generated_at")) if gm.get("generated_at") else None


def _phase(p: str | None) -> str:
    return {"postseason": "playoffs"}.get(p or "", p or "regular")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="*", help="seasons to build in full (default: the current season)")
    ap.add_argument("--sims", type=int, default=20000, help="season simulations (default 20000)")
    ap.add_argument("--days-ahead", type=int, default=7, help="price games kicking off up to N days ahead (default 7)")
    ap.add_argument("--quick", action="store_true", help="few simulations (tests and smoke runs)")
    ap.add_argument("--no-market", action="store_true", help="skip the Kalshi / Polymarket fetch")
    ap.add_argument("--no-light", action="store_true", help="build only the full seasons")
    ap.add_argument("--no-careers", action="store_true", help="skip data/players/<pid>.json")
    ap.add_argument("--no-history", action="store_true", help="skip history.json")
    ap.add_argument("--no-models", action="store_true", help="catalogues from play-by-play only (no builder B/C models)")
    ap.add_argument("--all-games", action="store_true", help="rebuild every game page of the page seasons")
    ap.add_argument("--game-page-seasons", type=int, default=2, help="game pages for the N most recent seasons (default 2)")
    ap.add_argument("--force", action="store_true", help="rebuild light seasons even when their inputs are unchanged")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--no-transactions", action="store_true", help="skip transactions.json and the team ledgers")
    ap.add_argument("--no-fantasy", action="store_true", help="skip fantasy.json and the fantasy backtest")
    ap.add_argument("--contracts", action="store_true", help="publish cap hits and the cap check from nflverse's OverTheCap "
                    "contracts (or GRIDIRON_CONTRACTS=1; off by default: OverTheCap's terms, see analytics/contracts.py)")
    ap.add_argument("--data", default=None, help="data root (default GRIDIRON_DATA or docs/gridiron/data)")
    ap.add_argument("--raw", default=None, help="raw root (default GRIDIRON_RAW or data/nfl)")
    ap.add_argument("--cache", default=None, help="cache root (default GRIDIRON_CACHE or data/nfl/cache)")
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
           "no_careers": args.no_careers, "no_models": args.no_models, "contracts": args.contracts,
           "no_transactions": args.no_transactions, "no_fantasy": args.no_fantasy}

    def kit():
        sys.path.insert(0, str(ROOT / "scripts"))
        from design_kit import copy_kit      # scripts/design_kit.py: the shared design kit into assets/qk/
        b.written.append(copy_kit(data.parent))
    b.step("copy the design kit", kit)
    from oddsmarkets.nfl.analytics import leaders as LD
    b.write_or_fail("glossary.json", "glossary", LD.glossary)
    seasons = an.seasons_on_disk()
    if not seasons:
        logger.warning("no season stores under %s and no play-by-play under %s", data, an.raw_root())
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
    # seasons not built this run: their payloads on disk
    from oddsmarkets.nfl.analytics import careers as CR
    from oddsmarkets.nfl.analytics import fourth as FD
    from oddsmarkets.nfl.analytics import history as HS
    for s in seasons:
        r = res.setdefault(s, {})
        sd = data / str(s)
        if not r.get("rows"):
            r["rows"] = CR.reduce_cat(an.read_json(sd / "players.json"), s)
        if not r.get("fourth"):
            r["fourth"] = an.read_json(sd / "fourth_downs.json")
        if not r.get("referees"):
            r["referees"] = an.read_json(sd / "referees.json")
        if not r.get("league"):
            r["league"] = (an.read_json(sd / "manifest.json") or {}).get("league")
    gc.collect()
    fds = {s: r.get("fourth") for s, r in res.items() if (r.get("fourth") or {}).get("ok")}
    if fds:
        stores = {s: (an.load_store(s).get("games") or {}) for s in fds}
        b.write_or_fail("coaches.json", "coaches", lambda: FD.coaches(fds, stores))
        del stores
    refs = {s: r.get("referees") for s, r in res.items() if (r.get("referees") or {}).get("ok")}
    if refs:
        b.write_or_fail("referees.json", "referees", lambda: FD.referees(refs))
    rows_by = {s: r.get("rows") for s, r in res.items() if r.get("rows")}
    prog = None
    if not args.no_careers and rows_by:
        # Progression (common.progression): dv / dp / pg on the rows (the career files carry them) and progression_ref.json
        prog = b.step("progression", lambda: CR.progression(rows_by, lambda s: an.read_json(data / str(s) / "value.json")), None)
        if prog:
            b.step("write progression_ref.json", lambda: b.write(CR.PROG_FILE, prog[0]))
    if not args.no_history and rows_by:
        b.write_or_fail("history.json", "history", lambda: HS.build(rows_by, {s: r.get("league") for s, r in res.items()}))
    # calibration: builder C's backtest when it has written one; the existing file otherwise; else a placeholder
    from oddsmarkets.nfl.analytics import adapters
    b.step("calibration", lambda: calibration(b, adapters))
    if not args.no_careers and rows_by:
        blocks: dict[str, dict] = {}
        for s, r in res.items():
            for pid, blk in (r.get("blocks") or {}).items():
                if pid not in blocks or blocks[pid].get("season", 0) < blk.get("season", 0):
                    blocks[pid] = blk

        def old_reader(pid):
            p = data / "players" / f"{pid}.json"
            return an.read_json(p) if p.exists() else None

        def cat_reader(s):
            p = data / str(s) / "players.json"
            return an.read_json(p) if p.exists() else None
        n_prev = b.step("last-season percentiles", lambda: CR.add_prev_pct(blocks, cat_reader), 0)
        logger.info("careers: last-season percentiles on %s current blocks", n_prev)
        idx = b.step("careers", lambda: CR.write_careers(b.write, rows_by, blocks, old_reader, current,
                                                          prog[1] if prog else None), {}) or {}
        if idx:
            prev = an.read_json(data / "players_index.json") or {}
            prev = {k: v for k, v in prev.items() if isinstance(v, list) and CR.real_pid(k)}
            prev.update(idx)
            b.step("players_index", lambda: b.write("players_index.json", prev))
        logger.info("careers: %d players indexed", len(idx))
    idx_payload = b.step("index", lambda: index_payload(b, res, current, seasons, cfg["today"]), None)
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
