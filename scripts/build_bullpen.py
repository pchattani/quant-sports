#!/usr/bin/env python
"""
Build The Quant Bullpen's payloads (oddsmarkets/baseball/PAYLOADS.md) into docs/bullpen/data/.

Site-wide: index.json, glossary.json, players_index.json, players/<pid>.json (careers, all levels); and
docs/bullpen/assets/base.css (copied from the football site's docs/site/assets/style.css).

NPB (level "npb", oddsmarkets/baseball/npb/build.py): data/npb/<S>/{season,schedule,players,teams}.json, game pages,
data/npb/history.json, careers/, names.json, calibration.json (its own stores are inputs and are not deployed).

data/mlb/team_history.json (analytics/team_history.py: champions, best team-seasons, franchise records; Lahman 1901 on);
data/mlb/award_history.json (analytics/award_history.py: the winners against our walk-forward pre-vote calls).
Per level, data/<L>/: history.json (MLB: Retrosheet-era careers and all-time leaderboards, with the Retrosheet
notice), calibration.json (builder D's backtest writes it; kept as is, an {"ok": false} placeholder when missing).

Per level and season, data/<L>/<S>/: hitters.json, pitchers.json, fielders.json, teams.json, season.json,
schedule.json, umpires.json, parks.json, leaders.json, lab.json, awards.json (MLB), prospects.json (AAA),
markets.json (MLB, current season), games/<gpk>.json and manifest.json (input signatures, frozen pre-game prices
and page signatures, so unchanged work is skipped); value.json (every season), value/<tid>.json (current season) and
trade.json (MLB and NPB, current season) from analytics/value_build.py (--no-value skips them).

Seasons come in two weights:
  full   (--seasons, default each level's current season): season simulation (--sims, 20,000), game-model prices
         for games not yet final (today - 1 .. today + --days-ahead), markets, award races, projections in the
         catalogues and the player "current" blocks of the career files.
  light  every other season with a store (skip with --no-light): catalogues, season.json without a simulation,
         umpires, parks, leaders, lab; a light season whose inputs are unchanged since its manifest is skipped
         (--force rebuilds it).
Game pages are written for each level's --game-page-seasons most recent seasons (default 2): pages whose signature
changed (status, score, lines, lineups, pitches in the table, model versions) plus every not-final game of the
current season within the pricing window; --all-games rebuilds every page of those seasons. A page is never
downgraded: when the pitch table for its game is not on this machine (CI holds only the current season's) the old
page's pitch-level blocks are kept, and a frozen pre-game price is carried into the live and final page.

Memory: one season's pitches at a time (column subsets, chunked aggregation); game pages load their pitches in
batches pushed down to Parquet.

Every step is isolated: a failure is logged with its traceback and the build goes on; a payload that cannot be
built is written as {"ok": false, "reason": ...}; a partial run never removes a level's entry from index.json.

Roots: --data / BULLPEN_DATA (default docs/bullpen/data) for stores in and payloads out, --raw / BULLPEN_RAW
(default data/baseball) for pitch tables and Retrosheet, --cache / BULLPEN_CACHE (default data/baseball/cache).

    python scripts/build_bullpen.py                                    # every level: current full, the rest light
    python scripts/build_bullpen.py --levels mlb --seasons 2026 2025
    python scripts/build_bullpen.py --quick --no-market --no-light      # fast local check
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import math
import shutil
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.baseball import analytics as an  # noqa: E402
from oddsmarkets.baseball import canon  # noqa: E402

logger = logging.getLogger("build_bullpen")
CSS_SRC = ROOT / "docs" / "site" / "assets" / "style.css"
BUILD_VERSION = 1
PAGE_BATCH = 150
HEADLINE_H = ["war", "xwoba_plus", "woba", "hr", "dv", "bat_speed_adj", "barrel_pct", "sprint_speed"]
HEADLINE_P = ["war", "stuff_plus", "pitching_plus", "k_pct", "ra9", "fb_velo", "csw_pct", "tunnel_index"]


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

def _file_sig(p: Path) -> str | None:
    """Size and content digest (memoised on size and mtime by `_io.content_digest`): the same file signs the same on
    any machine, whatever its path or modification time (CI restores and checkouts reset mtimes)."""
    from oddsmarkets.baseball.models import _io as _pio
    d = _pio.content_digest(p)
    if d is None:
        return None
    return f"{p.stat().st_size}-{d[:20]}"


def _content_sig(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha1()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:20]


def model_versions() -> dict:
    import importlib
    out = {}
    for mod, attr in (("physics", "MODEL_VERSION"), ("stuff", "MODEL_VERSION"), ("location", "MODEL_VERSION"), ("pitching", "MODEL_VERSION"),
                      ("tunneling", "MODEL_VERSION"), ("swing", "MODEL_VERSION"), ("battrack", "MODEL_VERSION"), ("fatigue", "MODEL_VERSION"),
                      ("xwoba", "MODEL_VERSION"), ("catchprob", "MODEL_VERSION"), ("framing", "MODEL_VERSION"), ("umpire", "MODEL_VERSION"),
                      ("re24", "MODEL_VERSION"), ("parks", "MODEL_VERSION"), ("war", "MODEL_VERSION"), ("stabilise", "MODEL_VERSION"),
                      ("projections", "VERSION"), ("game_sim", "VERSION"), ("season_sim", "N_SIMS")):
        try:
            out[mod] = str(getattr(importlib.import_module(f"oddsmarkets.baseball.models.{mod}"), attr))
        except Exception:                                        # noqa: BLE001
            out[mod] = None
    return out


def season_sig(level: str, season: int) -> dict:
    return {"version": BUILD_VERSION, "store": _content_sig(an.data_root() / level / str(season) / "store.json"),
            "pitches": _file_sig(an.pitch_path(level, season)), "models": model_versions()}


# ---------------------------------------------------------------------------------------------- one season

def reduce_cat(cat: dict | None, kind: str) -> dict | None:
    """The slice of a catalogue the career files need (keeps memory flat across seasons)."""
    from oddsmarkets.baseball.analytics import careers as CR
    if not cat or not cat.get("players"):
        return None
    deep = set(CR.prog_keys(kind))            # the progression deep set (round 6) and its position percentiles
    keys = set(CR.SEASON_KEYS_H + CR.SIMILAR_H) | deep if kind == "hitter" else set(CR.SEASON_KEYS_P + CR.SIMILAR_P) | deep
    out = {}
    for pid, r in cat["players"].items():
        out[pid] = {"name": r.get("name"), "team": r.get("team"), "pos": r.get("pos"), "role": r.get("role"), "pa": r.get("pa"),
                    "bf": r.get("bf"), "values": {k: v for k, v in (r.get("values") or {}).items() if k in keys},
                    "pct_role": {k: v for k, v in (r.get("pct_role") or {}).items() if k in deep}}
    return {"players": out, "team_games": cat.get("team_games")}


def small_files(b: Build, d: str, sdir: Path, level: str, season: int, hit: dict | None, pit: dict | None,
                only_missing: bool = False) -> None:
    """peers.json and league_types.json (analytics/peers.py): what the player page needs from the 4-7 MB catalogues;
    performers.json (analytics/performers.py): the standings page's top and bottom performers.
    Skipped seasons write them only when absent (from the catalogues on disk)."""
    from oddsmarkets.baseball.analytics import peers as PE
    from oddsmarkets.baseball.analytics import performers as PF
    if not (hit or {}).get("ok") and not (pit or {}).get("ok"):
        return
    for name, fn in (("peers.json", lambda: PE.build(hit, pit, level, season)), ("league_types.json", lambda: PE.league_types(pit, level, season)),
                     ("performers.json", lambda: PF.build(hit, pit, level, season))):
        if only_missing and (sdir / name).exists():
            continue
        b.write_or_fail(d + name, f"{name} {level} {season}", fn, level=level, season=season)


def build_season(b: Build, level: str, season: int, full: bool, cfg: dict, shared: dict) -> dict:
    from oddsmarkets.baseball.analytics import awards as AW
    from oddsmarkets.baseball.analytics import careers as CR
    from oddsmarkets.baseball.analytics import fielders as FD
    from oddsmarkets.baseball.analytics import hitters as HT
    from oddsmarkets.baseball.analytics import leaders as LD
    from oddsmarkets.baseball.analytics import parks as PK
    from oddsmarkets.baseball.analytics import pitchers as PT
    from oddsmarkets.baseball.analytics import prospects as PR
    from oddsmarkets.baseball.analytics import season as SN
    from oddsmarkets.baseball.analytics import teams as TM
    from oddsmarkets.baseball.analytics import umpires as UM
    from oddsmarkets.baseball.analytics.context import SeasonContext
    t0 = time.perf_counter()
    d = f"{level}/{season}/"
    sdir = b.data / level / str(season)
    mpath = sdir / "manifest.json"
    manifest = an.read_json(mpath) or {}
    sig = season_sig(level, season)
    current = season == shared["current"]
    skip = None
    if not full and not cfg["force"] and manifest.get("sig") == sig and (sdir / "hitters.json").exists() \
            and season not in shared["page_seasons"]:
        skip = "inputs unchanged"
    elif not current and not cfg["force"] and not an.pitch_path(level, season).exists() and \
            ((an.read_json(sdir / "hitters.json") or {}).get("ok")):
        # CI holds only the current season's pitch table: never overwrite a past season built elsewhere
        skip = "pitch table not on this machine; payloads kept"
    if skip:
        logger.info("%s %s: %s, skipped", level, season, skip)
        hit0, pit0 = an.read_json(sdir / "hitters.json"), an.read_json(sdir / "pitchers.json")
        small_files(b, d, sdir, level, season, hit0, pit0, only_missing=True)
        refresh_season_json(b, level, season, sdir, cfg)
        return {"skipped": True, "hitters": reduce_cat(hit0, "hitter"), "pitchers": reduce_cat(pit0, "pitcher")}
    ctx = SeasonContext(level, season, full=full, today=cfg["today"], current=current, sims=cfg["sims"],
                        fetch_markets=cfg["markets"] and full and current and level == "mlb", use_models=not cfg["no_models"])
    logger.info("%s %s (%s): %d games, phase %s, pitches %s", level, season, "full" if full else "light", len(ctx.games), ctx.phase,
                ctx.has_pitches())
    hit = b.write_or_fail(d + "hitters.json", f"hitters {level} {season}", lambda: HT.build(ctx), level=level, season=season)
    pit = b.write_or_fail(d + "pitchers.json", f"pitchers {level} {season}", lambda: PT.build(ctx), level=level, season=season)
    fldp = b.write_or_fail(d + "fielders.json", f"fielders {level} {season}", lambda: FD.build(ctx, hit), level=level, season=season)
    small_files(b, d, sdir, level, season, hit, pit)
    sim = None
    if full and level == "mlb":
        sim = b.step(f"season sim {level} {season}", ctx.sim, None)
    markets = b.step(f"markets fetch {level} {season}", ctx.markets, {}) if ctx.fetch_markets else {}
    # prices and the schedule (game cards) before the teams, whose game logs carry the cards' model and market prices
    prices: dict[str, dict] = {}
    if full and current:
        prices = b.step(f"game prices {level} {season}", lambda: price_window(ctx, cfg), {}) or {}
    frozen = dict(manifest.get("prices") or {})
    sim_ledger = dict(manifest.get("sim_prices") or {})
    for gpk, pr in prices.items():
        if pr.get("model"):
            frozen[gpk] = pr["model"]
        if pr.get("sim") and str((ctx.games.get(gpk) or {}).get("status")) in ("pre", "scheduled"):
            sim_ledger[gpk] = pr["sim"]
    sched = b.write_or_fail(d + "schedule.json", f"schedule {level} {season}", lambda: schedule(ctx, prices, frozen, markets),
                            level=level, season=season)
    tms = b.write_or_fail(d + "teams.json", f"teams {level} {season}", lambda: TM.build(ctx, hit, pit, sim, (sched or {}).get("games")),
                          level=level, season=season)
    spl = b.write_or_fail(d + "season.json", f"season {level} {season}",
                          lambda: with_league(b, level, season, SN.build(ctx, tms, sim, markets), tms, (sched or {}).get("games") or [], cfg)
                          if full and current else SN.build(ctx, tms, sim, markets), level=level, season=season)
    ump = b.write_or_fail(d + "umpires.json", f"umpires {level} {season}", lambda: UM.build(ctx), level=level, season=season)
    b.write_or_fail(d + "parks.json", f"parks {level} {season}", lambda: PK.build(ctx), level=level, season=season)
    b.write_or_fail(d + "leaders.json", f"leaders {level} {season}", lambda: LD.build(ctx, hit, pit, tms), level=level, season=season)
    b.write_or_fail(d + "lab.json", f"lab {level} {season}", lambda: LD.lab(ctx, hit, pit), level=level, season=season)
    awards = None
    if level == "mlb" and (full or cfg["light_awards"]):
        awards = b.write_or_fail(d + "awards.json", f"awards {level} {season}", lambda: AW.build(ctx, hit, pit), level=level, season=season)
    if level == "aaa":
        mlb = shared.get("mlb_full", {}).get(season) or {}
        b.write_or_fail(d + "prospects.json", f"prospects {season}", lambda: PR.build(ctx, hit, pit, mlb.get("proj"), mlb.get("hitters"),
                                                                                       mlb.get("pitchers")), level=level, season=season)
    # game pages
    pages = manifest.get("games") or {}
    pages_kept = not current and not ctx.has_pitches() and (sdir / "games").exists() and not cfg["all_games"]
    if season in shared["page_seasons"] and not pages_kept:
        pages = b.step(f"game pages {level} {season}", lambda: game_pages(b, ctx, cfg, manifest, prices, sched, pit, ump), pages) or pages
    if full and current and level == "mlb":
        b.write_or_fail(d + "markets.json", f"markets {level} {season}",
                        lambda: SN.markets_payload(ctx, sim, (awards or {}).get("awards"), prices, (spl or {}).get("postseason", {}) and
                                                   ((spl or {}).get("postseason") or {}).get("series")), level=level, season=season)
    blocks = {}
    if full and not cfg["no_careers"]:
        blocks = b.step(f"player blocks {level} {season}", lambda: CR.current_blocks(ctx, hit, pit), {}) or {}
    if full and current and level == "mlb":
        # on pace for history (round 9): the season's leaders against the top single seasons since 1901
        from oddsmarkets.baseball.analytics import records as RD
        ch = b.step(f"chases {level} {season}", lambda: RD.build(season, hit, pit, ctx.phase), None)
        if ch:
            b.write(d + "chases.json", ch)
    if full and current and blocks:
        # who is hot and who is cold (round 9): the rolling windows of the blocks against each player's season
        from oddsmarkets.baseball.analytics import form as FM
        fm = b.step(f"form {level} {season}", lambda: FM.build(level, season, blocks, hit, pit), None)
        if fm:
            b.write(d + "form.json", fm)
    out = {"hitters": reduce_cat(hit, "hitter"), "pitchers": reduce_cat(pit, "pitcher"), "blocks": blocks, "current": current,
           "phase": ctx.phase, "season": season, "fld_validation": (fldp or {}).get("validation") if (fldp or {}).get("ok") else None}
    if full and current:
        out.update(cards=(sched or {}).get("games") or [], season_payload=spl, teams=tms, hit_full=_headline(hit, HEADLINE_H),
                   pit_full=_headline(pit, HEADLINE_P), ctx_entry=SN.level_entry(ctx, an.seasons_on_disk(level), tms, sim))
    if level == "mlb" and full:
        out["proj"] = ctx.model("proj_next") if not cfg["no_models"] else None
        out["hit_cat"], out["pit_cat"] = hit, pit
    manifest = {"sig": sig, "built_at": _now(), "full": full, "phase": ctx.phase, "games": pages, "prices": frozen, "sim_prices": sim_ledger,
                "model_errors": ctx.model_errors, "timings": {k: round(v, 1) for k, v in ctx.timings.items()}}
    b.step(f"manifest {level} {season}", lambda: b.write(d + "manifest.json", manifest))
    for k, v in ctx.timings.items():
        b.timings[f"{level} {season} {k}"] = v
    ctx.release()
    del ctx
    gc.collect()
    logger.info("%s %s (%s): %.1f s", level, season, "full" if full else "light", time.perf_counter() - t0)
    return out


def refresh_season_json(b: Build, level: str, season: int, sdir: Path, cfg: dict) -> None:
    """A skipped season keeps its payloads, but a season.json from an older layout (analytics/season.py SEASON_VERSION:
    2 adds the postseason as played, the final seeds, division winners and clinches) is rebuilt from the store and the
    teams.json on disk. No simulation: a past season's bracket is the one that was played."""
    from oddsmarkets.baseball.analytics import season as SN
    from oddsmarkets.baseball.analytics.context import SeasonContext
    old = an.read_json(sdir / "season.json") or {}
    if (old.get("version") or 1) >= SN.SEASON_VERSION or not (sdir / "teams.json").exists():
        return
    tms = an.read_json(sdir / "teams.json")
    if not (tms or {}).get("ok", True):
        return

    def run():
        ctx = SeasonContext(level, season, full=False, today=cfg["today"], current=False, use_models=False)
        out = SN.build(ctx, tms, None, None)
        if old.get("league") and "league" not in out:
            out["league"] = old["league"]
        ctx.release()
        return out
    b.write_or_fail(f"{level}/{season}/season.json", f"season (refresh) {level} {season}", run, level=level, season=season)


def with_league(b: Build, level: str, season: int, spl: dict | None, tms: dict | None, cards: list[dict], cfg: dict) -> dict | None:
    """season.json with its "league" block (how the races are shaping up, strengths and weaknesses:
    oddsmarkets/baseball/analytics/race.py on oddsmarkets/common/league.py) and data/<level>/race_log.json carried
    forward (the whole season's chances, one snapshot a day; MLB's dates before live tracking rebuilt from the season
    simulation as of each date, within a time budget a build). Triple-A has no simulation: its block carries the
    strengths and weaknesses only. A failure leaves season.json as it was."""
    if not isinstance(spl, dict) or not spl.get("ok", True):
        return spl
    from oddsmarkets.baseball.analytics import race as RC

    def run():
        prev = an.read_json(b.data / level / "race_log.json") or {}
        runner = RC.asof_runner(level, season) if level == "mlb" and not cfg.get("no_models") else None
        blk, log = RC.build(level, season, spl, tms, cards, prev, _digest_now(cfg["today"]), run_asof=runner)
        if log.get(str(season)):
            b.write(f"{level}/race_log.json", log)
        # a decided World Series: our calls for the recap from the race log (season.calls_from_log, no simulation)
        pst = spl.get("postseason") or {}
        if level == "mlb" and pst.get("complete") and not spl.get("calls"):
            from oddsmarkets.baseball.analytics import season as SN
            spl["calls"] = SN.calls_from_log(log.get(str(season)), cards)
        return blk
    blk = b.step(f"league block {level} {season}", run, None)
    if blk:
        spl["league"] = blk
    return spl


def _headline(cat: dict | None, keys: list[str]) -> dict:
    """Top 10 per headline metric among the reference pool: {key: [[pid, value], ...]}."""
    out = {}
    if not cat or not cat.get("players"):
        return out
    mets = {m["key"]: m for m in cat.get("metrics") or []}
    ref_n = (cat.get("reference") or {}).get("min_pa") or (cat.get("reference") or {}).get("min_bf") or 0
    for k in keys:
        m = mets.get(k)
        if not m:
            continue
        nk = "pa" if cat.get("kind") == "hitter" else "bf"
        cand = [(p, r["values"].get(k)) for p, r in cat["players"].items() if r["values"].get(k) is not None and (r.get(nk) or 0) >= ref_n]
        cand.sort(key=lambda x: x[1], reverse=not m.get("lower"))
        out[k] = [[p, v] for p, v in cand[:10]]
    return out


def price_window(ctx, cfg: dict) -> dict[str, dict]:
    """Game-model prices (and market rows) for the season's games not yet final from yesterday to --days-ahead."""
    from oddsmarkets.baseball.analytics import games as GM
    lo = cfg["today"] - timedelta(days=1)
    hi = cfg["today"] + timedelta(days=cfg["days_ahead"])
    mk = (ctx.markets() or {}).get("games") or {}
    out = {}
    for gpk, g in ctx.games.items():
        if g.get("status") not in ("pre", "live", "scheduled"):
            continue
        try:
            d = date.fromisoformat(str(g.get("date"))[:10])
        except ValueError:
            continue
        if not (lo <= d <= hi):
            continue
        summ = None
        try:
            summ = GM.price(ctx, g, cfg["game_sims"])
        except Exception as exc:                                 # noqa: BLE001
            logger.info("price %s failed: %s", gpk, exc)
        out[str(gpk)] = {"summary": summ, "model": GM.model_block(summ, g), "market": mk.get(str(gpk)), "priced_at": _now(),
                         "sim": sim_price(summ)}
    return out


def sim_price(summ: dict | None) -> dict | None:
    """The simulation's own pre-game price {"p", "t"} (before the market layer): the ledger the market layer learns from
    (manifest "sim_prices"; models/market_layer.py)."""
    if not summ or summ.get("p_home") is None:
        return None
    sim = summ.get("sim") or {}
    p = sim.get("p_home", summ.get("p_home"))
    t = sim.get("total", (summ.get("runs") or {}).get("total"))
    return {"p": an.rnd(p, 5), "t": an.rnd(t, 3)}


def schedule(ctx, prices: dict, frozen: dict, markets: dict | None) -> dict:
    from oddsmarkets.baseball.analytics import games as GM
    bt = GM.backtest_prices(ctx.level, ctx.season)
    mk = (markets or {}).get("games") or {}
    cards = []
    for gpk, g in sorted(ctx.games.items(), key=lambda kv: (str(kv[1].get("date")), str(kv[1].get("start") or ""), kv[0])):
        if g.get("gtype") not in ("R", "F", "D", "L", "W", "C"):
            continue
        pr = prices.get(gpk) or {}
        model = pr.get("model") or frozen.get(gpk)
        if model is None and gpk in bt:
            b = bt[gpk]
            model = {"p_home": an.rnd(b.get("p_home"), 4), "total": an.rnd(b.get("total"), 2), "rl_home": an.rnd(b.get("rl_home"), 4),
                     "source": "backtest"}
        m = mk.get(gpk)
        market = {"p_home": m.get("p_home"), "sources": [s.get("source") for s in (m.get("sources") or [])]} if m and m.get("p_home") is not None \
            else GM.market_from_store(g)
        cards.append(GM.card(ctx, g, model, market))
    return {"ok": True, "level": ctx.level, "season": ctx.season, "updated_at": an.now(), "games": cards}


def game_pages(b: Build, ctx, cfg: dict, manifest: dict, prices: dict, sched: dict | None, pit: dict | None, ump: dict | None) -> dict:
    from oddsmarkets.baseball.analytics import games as GM
    from oddsmarkets.baseball.analytics import umpires as UM
    old_sigs = dict(manifest.get("games") or {})
    counts = GM.pitch_counts(ctx.level, ctx.season)
    mv = GM.model_versions()
    gdir = b.data / ctx.level / str(ctx.season) / "games"
    cards = {c["gpk"]: c for c in ((sched or {}).get("games") or [])}
    window_lo = cfg["today"] - timedelta(days=1)
    window_hi = cfg["today"] + timedelta(days=cfg["days_ahead"])
    due = []
    new_sigs = {}
    for gpk, g in ctx.games.items():
        if gpk not in cards:
            continue
        s = GM.page_sig(g, counts.get(gpk, 0), mv)
        new_sigs[gpk] = s
        exists = (gdir / f"{gpk}.json").exists()
        live = g.get("status") in ("pre", "live", "scheduled")
        try:
            dd = date.fromisoformat(str(g.get("date"))[:10])
        except ValueError:
            dd = None
        in_window = dd is not None and window_lo <= dd <= window_hi
        if cfg["all_games"] or not exists or old_sigs.get(gpk) != s or (ctx.current and live and in_window):
            due.append(gpk)
    logger.info("%s %s: %d game pages due of %d", ctx.level, ctx.season, len(due), len(cards))
    if not due:
        return new_sigs
    umps = UM.profiles(ump)
    re_info = None
    try:
        r = ctx.model("re24")
        if r.get("ok"):
            re_info = {"re": r.get("re"), "counts": r.get("counts")}
    except Exception:                                            # noqa: BLE001
        re_info = None
    parks = ctx.model("parks") if ctx.has_pitches() else {}
    arsenal = (pit or {}).get("arsenal") or {}
    have = [g for g in due if counts.get(g)]
    without = [g for g in due if not counts.get(g)]
    written = 0
    for lo in range(0, len(have), PAGE_BATCH):
        batch = have[lo:lo + PAGE_BATCH]
        gp_all = b.step(f"game pitches {ctx.level} {ctx.season}", lambda: GM.game_pitches(ctx, batch), None)
        groups, fls, pas = {}, {}, {}
        if gp_all is not None and len(gp_all):
            from oddsmarkets.baseball.analytics import pitchagg as PG
            gp_all = gp_all.sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)
            fl_all = b.step("game flags", lambda: PG.flags(gp_all), None)
            pa_all = b.step("game PA table", lambda: PG.pa_table(gp_all), None)
            for k, v in gp_all.groupby("game_pk"):
                gk = str(k)
                groups[gk] = v.reset_index(drop=True)
                if fl_all is not None:
                    fls[gk] = fl_all.loc[v.index].reset_index(drop=True)
            if pa_all is not None and len(pa_all):
                pas = {str(k): v for k, v in pa_all.groupby("game_pk")}
        for gpk in batch:
            written += _one_page(b, ctx, gpk, groups.get(gpk), cards, prices, gdir, arsenal, umps, re_info, parks, fls.get(gpk), pas.get(gpk),
                                 sigs=new_sigs)
        del gp_all, groups, fls, pas
        gc.collect()
    for gpk in without:
        written += _one_page(b, ctx, gpk, None, cards, prices, gdir, arsenal, umps, re_info, parks, sigs=new_sigs)
    logger.info("%s %s: %d game pages written", ctx.level, ctx.season, written)
    return new_sigs


def _one_page(b: Build, ctx, gpk: str, gp, cards: dict, prices: dict, gdir: Path, arsenal: dict, umps: dict, re_info, parks,
              fl=None, pa=None, sigs: dict | None = None) -> int:
    from oddsmarkets.baseball.analytics import games as GM
    g = ctx.games[gpk]
    old = an.read_json(gdir / f"{gpk}.json") if (gdir / f"{gpk}.json").exists() else None
    pr = prices.get(gpk) or {}
    pregame = None
    if pr.get("summary"):
        pregame = {"model": pr["summary"], "market": pr.get("market"), "store_market": GM.market_from_store(g), "line": g.get("lines"),
                   "priced_at": pr.get("priced_at")}

    def build():
        return GM.build_page(ctx, g, gp, cards.get(gpk) or GM.card(ctx, g), pregame, old, arsenal, umps, re_info, parks, fl, pa)
    payload = b.step(f"game {ctx.level}/{gpk}", build)
    if payload is None:
        payload = {"ok": False, "reason": "game page could not be built", "gpk": gpk}
        if sigs is not None:
            sigs[gpk] = None                                     # unsigned: the next run tries again
    b.write(f"{ctx.level}/{ctx.season}/games/{gpk}.json", payload)
    return 1


# ---------------------------------------------------------------------------------------------- one level

def build_level(b: Build, level: str, args, cfg: dict, shared_all: dict) -> dict:
    from oddsmarkets.baseball import canon
    seasons = an.seasons_on_disk(level)
    if not seasons:
        logger.warning("%s: no season stores under %s", level, b.data)
        return {"seasons": []}
    cur = canon.current_season(cfg["today"])
    current = cur if cur in seasons else max(seasons)
    full = [s for s in (args.seasons or [current]) if s in seasons]
    light = [] if args.no_light else [s for s in seasons if s not in full]
    page_seasons = set(sorted(seasons)[-cfg["game_page_seasons"]:]) if cfg["game_page_seasons"] > 0 else set()
    logger.info("%s: seasons on disk %s; full %s; light %d; game pages %s", level, seasons, full, len(light), sorted(page_seasons))
    shared = {"current": current, "page_seasons": page_seasons, "mlb_full": shared_all.get("mlb_full", {})}
    res: dict[int, dict] = {}
    for s in sorted(full + light, reverse=True):
        r = b.step(f"{level} season {s}", lambda: build_season(b, level, s, s in full, cfg, shared), {}) or {}
        if level == "mlb" and s in full:
            shared_all.setdefault("mlb_full", {})[s] = {"proj": r.pop("proj", None), "hitters": r.pop("hit_cat", None),
                                                        "pitchers": r.pop("pit_cat", None)}
        res[s] = r
    for s in seasons:                                    # seasons not built this run: their catalogues on disk
        if s not in res or not res[s].get("hitters"):
            sd = b.data / level / str(s)
            res.setdefault(s, {})
            res[s]["hitters"] = res[s].get("hitters") or reduce_cat(an.read_json(sd / "hitters.json"), "hitter")
            res[s]["pitchers"] = res[s].get("pitchers") or reduce_cat(an.read_json(sd / "pitchers.json"), "pitcher")
    if not cfg.get("no_value"):                          # value, strengths and needs, the trade simulator (analytics/value_build.py)
        from oddsmarkets.baseball.analytics import value_build as VB
        b.step(f"{level} value", lambda: VB.build_level(b, level, current, cfg, sims=max(200, min(1000, cfg["sims"] // 20))))
    cal = b.data / level / "calibration.json"
    if level == "mlb" and not cfg["no_models"] and len(an.pitch_seasons(level)) >= 2:
        b.step(f"{level} calibration xwoba", lambda: calibration_xwoba(b, level))
    fv = {s: r.get("fld_validation") for s, r in res.items() if r.get("fld_validation")}
    if fv:
        b.step(f"{level} calibration fielding", lambda: merge_calibration(b, level, {
            "oaa": {str(s): v.get("oaa") for s, v in fv.items()}, "framing": {str(s): v.get("framing") for s, v in fv.items()}}))
    if not cal.exists():
        b.step(f"{level} calibration placeholder", lambda: b.write(f"{level}/calibration.json", {
            "ok": False, "reason": "no backtest yet: run builder D's backtest (models/backtest.py) to write it", "level": level}))
    return {"seasons": seasons, "current": current, "results": res}


def calibration_xwoba(b: Build, level: str, n_seasons: int | None = None) -> None:
    """Builder C's xwOBA+ v Savant xwOBA predictive test (first half -> second half, second half -> next season's first
    half) for every season on disk (the last n_seasons when given), cached on the Parquet files and merged into calibration.json["checks"]["xwoba"]
    (builder D's backtest owns the rest of the file). Needs two seasons on disk, so CI keeps the deployed copy."""
    from oddsmarkets.baseball.models import xwoba
    seasons = an.pitch_seasons(level)[-n_seasons:] if n_seasons else an.pitch_seasons(level)
    key = hashlib.sha1(json.dumps([xwoba.MODEL_VERSION] + [[s, _file_sig(an.pitch_path(level, s))] for s in seasons]).encode()).hexdigest()[:16]
    cp = an.an_cache() / "calibration" / f"xwoba_{level}_{key}.json"
    res = an.read_json(cp)
    if res is not None:
        res = _neutral(res)
    else:
        res = _neutral(xwoba.predictive_test(level, seasons))
        res = {"seasons": seasons, "computed_at": _now(), "labels": {"xwoba": "xwOBA+ (ours)", "savant_xwoba": "xwOBA (Savant)",
                                                                       "woba": "wOBA"}, **an.clean(res)}
        an.write_json(cp, res)
    merge_calibration(b, level, {"xwoba": res})


def _neutral(x):
    """The predictive test without its "winner" verdicts: the site reports the numbers side by side."""
    if isinstance(x, dict):
        return {k: _neutral(v) for k, v in x.items() if k != "winner"}
    if isinstance(x, list):
        return [_neutral(v) for v in x]
    return x


def merge_calibration(b: Build, level: str, checks: dict) -> None:
    """Merge check blocks into data/<L>/calibration.json["checks"] (per-season blocks merged key by key); the rest of the
    file (builder D's backtest: games, other checks) is kept."""
    p = b.data / level / "calibration.json"
    cur = an.read_json(p) or {}
    if cur.get("ok") is False:                       # the placeholder written before any backtest
        cur = {"games": None}
    ch = cur.setdefault("checks", {})
    for k, v in checks.items():
        if isinstance(v, dict) and isinstance(ch.get(k), dict) and all(str(x).isdigit() for x in v):
            ch[k] = {**ch[k], **v}
        else:
            ch[k] = v
    cur.setdefault("generated_at", _now())
    cur["checks_updated_at"] = _now()
    b.write(f"{level}/calibration.json", cur)


# ---------------------------------------------------------------------------------------------- site-wide

def _digest_now(today: date) -> datetime:
    """The digest's clock: now, or the end of --today's UTC day for a dated build (tests, backfills)."""
    now = datetime.now(timezone.utc)
    return now if today == now.date() else datetime(today.year, today.month, today.day, 23, 59, tzinfo=timezone.utc)


POST_STAGE = {"WS": "final", "CS": "semi", "DS": "quarter", "WC": "playoff"}


def _card_status(c: dict) -> str:
    st = str(c.get("status") or "")
    return "final" if st == "final" else "live" if st == "live" else "pre"


def _series_of(c: dict, post: dict | None) -> dict | None:
    """The postseason series a card belongs to (index.json postseason.series), matched on the two clubs."""
    pair = {str(c.get("home")), str(c.get("away"))}
    for s in ((post or {}).get("series") or []):
        if set(map(str, s.get("teams") or [])) == pair:
            return s
    return None


def featured_payload(cards: list[dict], teams: dict, post: dict | None, now: datetime) -> dict:
    """digest.featured: the games that matter most on the shared significance rule (oddsmarkets/common/featured.py:
    the MLB tier, the postseason stage and series state, the stakes in our season simulation, the start time and
    hour, live-ness; closeness a small bonus). {"today": [{"id", "score", "why"}] best first, "week": the biggest
    game of the next seven days}. A postseason card for a series already decided (an "if necessary" game) is left
    out. The front end takes the first game still upcoming or live at the reader's clock."""
    from oddsmarkets.common import featured as FT
    pt = (post or {}).get("teams") or {}
    games = []
    for c in cards:
        st = _card_status(c)
        if st == "final":
            continue
        h, a = str(c.get("home")), str(c.get("away"))
        th, ta = (teams or {}).get(h) or {}, (teams or {}).get(a) or {}
        sig = {"title": [(pt.get(h) or {}).get("p_ws", th.get("p_ws")), (pt.get(a) or {}).get("p_ws", ta.get("p_ws"))]}
        if c.get("series"):
            ser = _series_of(c, post)
            if ser and ser.get("done"):
                continue                                   # an "if necessary" game the series never needs
            sig["stage"] = POST_STAGE.get(str((ser or {}).get("round") or ""), "playoff")
            cs = c.get("series") or {}
            wins = None
            tm = [str(x) for x in (ser or {}).get("teams") or []]
            if ser and len(ser.get("wins") or []) == 2 and h in tm and a in tm:
                wins = [ser["wins"][tm.index(h)], ser["wins"][tm.index(a)]]
            sig["series"] = {"game": cs.get("game"), "best_of": cs.get("of") or (ser or {}).get("best_of"), "name": cs.get("desc")}
            if wins:
                sig["series"]["wins"] = wins
        else:
            sig["playoff"] = [th.get("p_postseason"), ta.get("p_postseason")]
        if c.get("gtype") == "S":
            sig["preseason"] = True
        games.append({"sport": "baseball", "league": "MLB", "id": c.get("gpk"), "start": c.get("start"), "status": st,
                      "home": h, "away": a, "p_home": (c.get("model") or {}).get("p_home"), "wp_home": c.get("wp_home"), "sig": sig})
    r = FT.rank_featured(games, now)

    def row(x):
        return {"id": x["key"].split(":", 1)[1], "score": x["score"], "why": x.get("reasons") or []}
    return {"today": [row(x) for x in r["today"]], "week": row(r["week"]) if r.get("week") else None}


def digest_payload(b: Build, cards: list[dict], teams: dict, post: dict | None, phase: str | None, season: int, today: date,
                   calls: dict | None = None) -> dict:
    """index.json "digest" (MLB): the "This week in MLB" top lines (oddsmarkets/common/digest.py), the stage and the
    featured candidates (featured.py). Finished games carry the frozen pre-game price (manifest "prices", written
    while the game was still to come, else the walk-forward backtest), so nothing here is look-ahead.
    mlb/chance_log.json keeps one snapshot a day of every club's postseason and World Series chance for the movers;
    the front end never reads it."""
    from oddsmarkets.common import digest as DG
    now = _digest_now(today)
    games = [{"id": c.get("gpk"), "sport": "baseball", "start": c.get("start"), "status": _card_status(c), "home": c.get("home"),
              "away": c.get("away"), "hs": c.get("hs"), "as": c.get("as"), "p_home": (c.get("model") or {}).get("p_home")} for c in cards]
    out: dict = {"asof": now.isoformat().replace("+00:00", "Z")[:16] + "Z"}
    rec = DG.record(games, now)
    if rec:
        rec.pop("by", None)                               # one sport here: the split is the Home page's
        out["record"] = rec
    for k, v in (("upset", DG.upset(games, now)), ("hot", DG.hot(games, now))):
        if v:
            out[k] = v
    pt = (post or {}).get("teams") or {}
    cur = {"p_ws": {t: (pt.get(t) or {}).get("p_ws", v.get("p_ws")) for t, v in (teams or {}).items()},
           "p_postseason": {t: v.get("p_postseason") for t, v in (teams or {}).items()}}
    cur = {m: {t: p for t, p in d.items() if p is not None} for m, d in cur.items()}
    log_all = an.read_json(b.data / "mlb" / "chance_log.json") or {}
    log_s = (log_all.get(str(season)) or {}) if isinstance(log_all, dict) else {}
    new_log = {m: DG.roll_log(log_s.get(m), now, cur[m]) for m in cur}
    if any(cur.values()):
        b.write("mlb/chance_log.json", {str(season): new_log})
    metric = "p_ws" if phase == "postseason" else "p_postseason"
    mv = DG.movers(new_log.get(metric), cur.get(metric) or {}, now)
    if mv:
        out["movers"] = dict(mv, metric=metric)
    reg = [c for c in cards if c.get("gtype") == "R"]
    st: dict = {"phase": phase}
    days = sorted(str(c.get("date"))[:10] for c in reg if c.get("date"))
    if days:
        first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        st.update(played=sum(1 for c in reg if c.get("status") == "final"), total=len(reg), first=days[0], last=days[-1],
                  week=max(1, min((now.date() - first).days // 7 + 1, (last - first).days // 7 + 1)), weeks=(last - first).days // 7 + 1)
    if post and post.get("series"):
        alive = [s for s in post["series"] if not s.get("done")]
        st.update(round=post.get("round"), alive=[{"round": s.get("round"), "name": s.get("round_name"), "teams": s.get("teams"),
                                                    "wins": s.get("wins"), "best_of": s.get("best_of")} for s in alive])
        champ = [s for s in post["series"] if s.get("round") == "WS" and s.get("done")]
        if champ:
            w = champ[0].get("wins") or [0, 0]
            st["champion"] = champ[0]["teams"][0] if w[0] > w[1] else champ[0]["teams"][1]
            st["title"] = title_block(champ[0], st["champion"], cards, calls)
    out["stage"] = st
    out["featured"] = featured_payload(cards, teams, post, now)
    return out


def title_block(ws: dict, champ: str, cards: list[dict], calls: dict | None) -> dict:
    """digest.stage.title once the World Series is decided (read by the Bullpen overview and scripts/build_home.py):
    the champion and runner-up, the series score from the champion's side, its games (gpk, date, the champion's runs
    first), the day it was decided, and our World Series chance for the champion on the eve of the postseason."""
    teams = [str(t) for t in ws.get("teams") or []]
    i = teams.index(champ)
    w = ws.get("wins") or [0, 0]
    by = {str(c.get("gpk")): c for c in cards}
    games = []
    for gid in ws.get("games") or []:
        c = by.get(str(gid)) or {}
        if c.get("status") != "final" or c.get("hs") is None:
            continue
        home = str(c.get("home")) == champ
        games.append({"gpk": str(gid), "date": str(c.get("date"))[:10], "home": home,
                      "score": [c["hs"], c["as"]] if home else [c["as"], c["hs"]]})
    games.sort(key=lambda g: g["date"])
    pre = (calls or {}).get("preplayoff") or {}
    p = (pre.get("p_ws") or {}).get(champ)
    ranked = sorted((pre.get("p_ws") or {}).items(), key=lambda kv: -kv[1])
    return {"event": ws.get("round_name") or "World Series", "champion": champ, "runner_up": teams[1 - i],
            "result": [w[i], w[1 - i]], "games": games, "decided": games[-1]["date"] if games else None,
            "pre_p": p, "pre_asof": pre.get("asof"), "pre_rank": next((k + 1 for k, (t, _) in enumerate(ranked) if t == champ), None),
            "pre_n": len(ranked) or None}


def index_payload(b: Build, levels: dict[str, dict], today: date) -> dict:
    prev = an.read_json(b.data / "index.json") or {}
    out = {"ok": True, "updated_at": _now(), "levels": dict(prev.get("levels") or {})}
    if "npb" not in levels:
        out["levels"].pop("npb", None)                # NPB is not published (npb.jp terms)
    for k in ("season", "phase", "today", "recent", "upcoming", "postseason", "leaders", "teams", "digest"):
        out[k] = prev.get(k)
    for lvl, r in levels.items():
        if not r.get("seasons"):
            continue
        if lvl == "npb":                                  # oddsmarkets/baseball/npb/build.py writes its own entry
            if r.get("entry"):
                out["levels"][lvl] = r["entry"]
            continue
        cur = (r.get("results") or {}).get(r.get("current")) or {}
        if not cur.get("ctx_entry"):
            if lvl not in out["levels"]:
                out["levels"][lvl] = {"seasons": r["seasons"], "season": r.get("current")}
            continue                                      # the current season was not built this run: keep its entry
        out["levels"][lvl] = dict(cur["ctx_entry"])
        cards = cur.get("cards") or []
        t = today.isoformat()
        recent_lo = (today - timedelta(days=2)).isoformat()
        up_hi = (today + timedelta(days=3)).isoformat()
        games = {"today": [c for c in cards if c.get("date") == t],
                 "recent": [c for c in cards if c.get("status") == "final" and recent_lo <= str(c.get("date")) < t][-30:],
                 "upcoming": [c for c in cards if c.get("status") in ("pre", "scheduled") and t < str(c.get("date")) <= up_hi][:40]}
        leaders = {**{f"h_{k}": v for k, v in (cur.get("hit_full") or {}).items()},
                   **{f"p_{k}": v for k, v in (cur.get("pit_full") or {}).items()}}
        if lvl != "mlb":
            # the hub reads a minor level's games and leaders from its levels entry (hub.js: src = lv)
            out["levels"][lvl].update(games, leaders=leaders)
            # and its team names (core.js registers levels[L].teams; the count moves to n_teams)
            ent = out["levels"][lvl]
            ent["n_teams"] = ent.get("teams") if isinstance(ent.get("teams"), int) else None
            ent["teams"] = {t_: {k: r_.get(k) for k in ("name", "abbr", "short", "league", "division", "colour")}
                            for t_, r_ in ((cur.get("teams") or {}).get("teams") or {}).items()}
            continue
        out["season"] = r.get("current")
        out["phase"] = cur.get("phase")
        out.update(games)
        sp = cur.get("season_payload") or {}
        post = sp.get("postseason") if isinstance(sp, dict) else None
        out["postseason"] = {"round": post.get("round"), "series": post.get("series"), "seeds": post.get("seeds"),
                             "teams": post.get("teams"),
                             **{k: post.get(k) for k in ("actual", "champion", "complete") if post.get(k)}} if post else None
        out["leaders"] = leaders
        tms = cur.get("teams") or {}
        # alt: the second kit colour for the Broadcast hero's clash rule (canon.ALT when the season payload predates it)
        out["teams"] = {t_: {k: r_.get(k) for k in ("name", "abbr", "short", "league", "division", "colour")} |
                        {"alt": r_.get("alt") or canon.team_alt(t_)} |
                        {k: (r_.get("values") or {}).get(k) for k in ("w", "l", "rating", "p_postseason", "p_ws")}
                        for t_, r_ in (tms.get("teams") or {}).items()}
        calls = sp.get("calls") if isinstance(sp, dict) else None
        out["digest"] = b.step("digest", lambda: digest_payload(b, cards, out["teams"], out["postseason"], out["phase"], out["season"], today, calls), {}) or {}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # NPB (npb.jp data) was taken off the public site on 15 Oct 2026 because of npb.jp's terms; `--levels npb` still
    # builds it locally, and index_payload drops its entry from any run that does not build it.
    ap.add_argument("--levels", nargs="*", choices=list(an.LEVELS) + ["npb"], default=list(an.LEVELS))
    ap.add_argument("--seasons", type=int, nargs="*", help="seasons to build in full (default: each level's current season)")
    ap.add_argument("--sims", type=int, default=20000, help="season simulations (default 20000)")
    ap.add_argument("--game-sims", type=int, default=20000, help="simulations per game price (default 20000)")
    ap.add_argument("--days-ahead", type=int, default=3, help="price games up to N days ahead (default 3)")
    ap.add_argument("--quick", action="store_true", help="few simulations (tests and smoke runs)")
    ap.add_argument("--no-market", action="store_true", help="skip the Kalshi / Polymarket fetch")
    ap.add_argument("--no-light", action="store_true", help="build only the full seasons")
    ap.add_argument("--no-careers", action="store_true", help="skip data/players/<pid>.json")
    ap.add_argument("--no-history", action="store_true", help="skip history.json and the Retrosheet-era career rows")
    ap.add_argument("--no-models", action="store_true", help="catalogues from the pitch tables only (no builder B/C/D models)")
    ap.add_argument("--light-awards", action="store_true", help="also build awards.json for light seasons")
    ap.add_argument("--no-value", action="store_true", help="skip the value section and the trade simulator's payloads")
    ap.add_argument("--no-moves", action="store_true", help="skip valuation v2, the transactions and the trade ratings")
    ap.add_argument("--no-fantasy", action="store_true", help="skip the fantasy payloads")
    ap.add_argument("--no-statsapi", action="store_true", help="no MLB Stats API calls for transactions and stat lines (cache only)")
    ap.add_argument("--all-games", action="store_true", help="rebuild every game page of the page seasons")
    ap.add_argument("--game-page-seasons", type=int, default=2, help="game pages for each level's N most recent seasons (default 2)")
    ap.add_argument("--force", action="store_true", help="rebuild light seasons even when their inputs are unchanged")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--data", default=None, help="data root (default BULLPEN_DATA or docs/bullpen/data)")
    ap.add_argument("--raw", default=None, help="raw root (default BULLPEN_RAW or data/baseball)")
    ap.add_argument("--cache", default=None, help="cache root (default BULLPEN_CACHE or data/baseball/cache)")
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
    from oddsmarkets.baseball.analytics import fallbacks
    b.step("install fallbacks", fallbacks.install)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    cfg = {"sims": min(args.sims, 1000) if args.quick else args.sims, "game_sims": min(args.game_sims, 2000) if args.quick else args.game_sims,
           "markets": not args.no_market, "today": today, "days_ahead": args.days_ahead, "all_games": args.all_games,
           "game_page_seasons": args.game_page_seasons, "force": args.force, "no_careers": args.no_careers, "no_models": args.no_models,
           "light_awards": args.light_awards, "no_value": args.no_value, "no_moves": args.no_moves, "no_fantasy": args.no_fantasy,
           "statsapi": not args.no_statsapi}

    def css():
        dst = data.parent / "assets" / "base.css"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CSS_SRC, dst)
        b.written.append(dst)
    b.step("copy base.css", css)

    # the shared design kit (docs/_design -> assets/qk): the front end is built on it (docs/REDESIGN.md)
    def kit():
        sys.path.insert(0, str(ROOT / "scripts"))
        from design_kit import copy_kit
        b.written.append(copy_kit(data.parent))
    b.step("copy the design kit", kit)
    from oddsmarkets.baseball.analytics import glossary as GL
    b.write_or_fail("glossary.json", "glossary", GL.build)
    shared_all: dict = {}
    levels: dict[str, dict] = {}
    for level in ["mlb", "aaa"]:
        if level in args.levels:
            levels[level] = b.step(f"level {level}", lambda: build_level(b, level, args, cfg, shared_all), {}) or {}
    shared_all.pop("mlb_full", None)
    gc.collect()
    if "mlb" in levels and not cfg["no_value"] and not cfg["no_fantasy"]:   # the fantasy layer (analytics/fantasy_build.py)
        from oddsmarkets.baseball.analytics import fantasy_build as FB
        from oddsmarkets.baseball.analytics import value_build as VB
        vctx = next(iter(VB._CTX.values()), None) if not cfg["no_moves"] else None
        b.step("fantasy mlb", lambda: FB.build(b, cfg, vctx))
        gc.collect()
    if "npb" in args.levels:                              # Nippon Professional Baseball (oddsmarkets/baseball/npb/)
        from oddsmarkets.baseball.npb import build as NPB
        levels["npb"] = b.step("level npb", lambda: NPB.build_level(b, cfg), {}) or {}
        gc.collect()
    # the clubs' history (Standings > History): Lahman Teams.csv 1901 on, then our finished seasons; kept when the cached
    # Lahman file is not on this machine
    if "mlb" in levels:
        from oddsmarkets.baseball.analytics import team_history as TH

        def team_hist():
            out = TH.build(an.seasons_on_disk("mlb"))
            if out is None:
                logger.info("team history: no Lahman Teams.csv on this machine; team_history.json kept")
            return out
        th = b.step("team history mlb", team_hist, None)
        if th:
            b.write("mlb/team_history.json", th)
        # the award winners against our pre-vote calls (Standings > Races): the committed walk-forward calls, plus this
        # season's call once its regular season is over
        from oddsmarkets.baseball.analytics import award_history as AH

        def award_hist():
            cur = max(an.seasons_on_disk("mlb") or [0])
            sj = an.read_json(data / "mlb" / str(cur) / "season.json") or {}
            return AH.build(cur, an.read_json(data / "mlb" / str(cur) / "awards.json"), str(sj.get("phase") or "") in ("postseason", "offseason", "complete"))
        ah = b.step("award history mlb", award_hist, None)
        if ah:
            b.write("mlb/award_history.json", ah)
    # history (MLB, Retrosheet era) and the career files
    hist_rows = None
    hist_extra: set[str] = set()
    if "mlb" in levels and not args.no_history and not args.no_models:
        from oddsmarkets.baseball.analytics import history as HS
        rows = b.step("history rows", lambda: HS.season_rows("mlb"), None)
        prev_hist = an.read_json(data / "mlb" / "history.json") or {}
        if (rows is None or not (len(rows[0]) or len(rows[1]))) and prev_hist.get("ok"):
            logger.info("history: no Retrosheet tables on this machine; history.json kept")
            hp = prev_hist
            rows = None
        else:
            hp = b.write_or_fail("mlb/history.json", "history mlb", lambda: HS.build("mlb", rows) if rows is not None else None,
                                 level="mlb", meta=HS.notice_meta())
        if rows is not None and not args.no_careers:
            for board in ((hp or {}).get("leaders") or {}).values():
                cols = board.get("cols") or []
                if "pid" in cols:
                    i = cols.index("pid")
                    hist_extra |= {str(r[i]) for r in board.get("rows") or [] if r[i] is not None}
            stat_pids = set()
            for r in levels.values():
                for s, x in (r.get("results") or {}).items():
                    for kind in ("hitters", "pitchers"):
                        stat_pids |= set(((x or {}).get(kind) or {}).get("players") or {})
            hist_rows = b.step("history player rows", lambda: HS.player_history(rows, stat_pids | hist_extra), {})
        del rows
        gc.collect()
    if not args.no_careers:
        from oddsmarkets.baseball.analytics import careers as CR
        cats: dict[tuple, dict] = {}
        blocks: dict[str, dict] = {}
        for lvl, r in levels.items():
            for s, x in (r.get("results") or {}).items():
                cats[(lvl, s)] = {"hitters": x.get("hitters"), "pitchers": x.get("pitchers")}
                for pid, blk in (x.get("blocks") or {}).items():
                    if pid not in blocks or (blocks[pid].get("season", 0), lvl == "mlb") < (blk.get("season", 0), lvl == "mlb"):
                        blocks[pid] = blk

        def old_reader(pid):
            p = data / "players" / f"{pid}.json"
            return an.read_json(p) if p.exists() else None

        def cat_reader(lvl, s, kind):              # last season's full catalogue: the one on disk, else this run's
            # this run's catalogues are reduce_cat slices without pct_role / qualified, so the ring percentiles
            # (add_prev_pct) need the file on disk (written earlier in this run when the season was rebuilt)
            p = data / lvl / str(s) / f"{kind}.json"
            if p.exists():
                return an.read_json(p)
            return (cats.get((lvl, s)) or {}).get(kind)
        n_prev = b.step("last-season percentiles", lambda: CR.add_prev_pct(blocks, cat_reader), 0)
        logger.info("careers: last-season percentiles on %s current sub-blocks", n_prev)
        idx = b.step("careers", lambda: CR.write_careers(b.write, cats, blocks, hist_rows, hist_extra, old_reader), {}) or {}
        if idx:
            prev = an.read_json(data / "players_index.json") or {}
            prev = {k: v for k, v in prev.items() if isinstance(v, list)}
            prev.update(idx)
            b.step("players_index", lambda: b.write("players_index.json", prev))
        logger.info("careers: %d player files", len(idx))
    b.write_or_fail("index.json", "index", lambda: index_payload(b, levels, today))
    total = sum(p.stat().st_size for p in set(b.written) if p.exists())
    logger.info("wrote %d files (%.1f MB) in %.1f s; %d step errors", len(set(b.written)), total / 1e6, time.perf_counter() - t_start,
                len(b.errors))
    slow = sorted(b.timings.items(), key=lambda kv: -kv[1])[:25]
    for k, v in slow:
        logger.info("  %-60s %7.1f s", k, v)
    for e in b.errors[:60]:
        logger.info("  error: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
