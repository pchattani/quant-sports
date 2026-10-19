#!/usr/bin/env python
"""
Build The Quant Bullpen's payloads (oddsmarkets/baseball/PAYLOADS.md) into docs/bullpen/data/.

Site-wide: index.json, glossary.json, players_index.json, players/<pid>.json (careers, all levels); and
docs/bullpen/assets/base.css (copied from the football site's docs/site/assets/style.css).

NPB (level "npb", oddsmarkets/baseball/npb/build.py): data/npb/<S>/{season,schedule,players,teams}.json, game pages,
data/npb/history.json, careers/, names.json, calibration.json (its own stores are inputs and are not deployed).

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
    keys = set(CR.SEASON_KEYS_H + CR.SIMILAR_H) if kind == "hitter" else set(CR.SEASON_KEYS_P + CR.SIMILAR_P)
    out = {}
    for pid, r in cat["players"].items():
        out[pid] = {"name": r.get("name"), "team": r.get("team"), "pos": r.get("pos"), "role": r.get("role"), "pa": r.get("pa"),
                    "bf": r.get("bf"), "values": {k: v for k, v in (r.get("values") or {}).items() if k in keys}}
    return {"players": out}


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
        return {"skipped": True, "hitters": reduce_cat(an.read_json(sdir / "hitters.json"), "hitter"),
                "pitchers": reduce_cat(an.read_json(sdir / "pitchers.json"), "pitcher")}
    ctx = SeasonContext(level, season, full=full, today=cfg["today"], current=current, sims=cfg["sims"],
                        fetch_markets=cfg["markets"] and full and current and level == "mlb", use_models=not cfg["no_models"])
    logger.info("%s %s (%s): %d games, phase %s, pitches %s", level, season, "full" if full else "light", len(ctx.games), ctx.phase,
                ctx.has_pitches())
    hit = b.write_or_fail(d + "hitters.json", f"hitters {level} {season}", lambda: HT.build(ctx), level=level, season=season)
    pit = b.write_or_fail(d + "pitchers.json", f"pitchers {level} {season}", lambda: PT.build(ctx), level=level, season=season)
    fldp = b.write_or_fail(d + "fielders.json", f"fielders {level} {season}", lambda: FD.build(ctx, hit), level=level, season=season)
    sim = None
    if full and level == "mlb":
        sim = b.step(f"season sim {level} {season}", ctx.sim, None)
    markets = b.step(f"markets fetch {level} {season}", ctx.markets, {}) if ctx.fetch_markets else {}
    # prices and the schedule (game cards) before the teams, whose game logs carry the cards' model and market prices
    prices: dict[str, dict] = {}
    if full and current:
        prices = b.step(f"game prices {level} {season}", lambda: price_window(ctx, cfg), {}) or {}
    frozen = dict(manifest.get("prices") or {})
    for gpk, pr in prices.items():
        if pr.get("model"):
            frozen[gpk] = pr["model"]
    sched = b.write_or_fail(d + "schedule.json", f"schedule {level} {season}", lambda: schedule(ctx, prices, frozen, markets),
                            level=level, season=season)
    tms = b.write_or_fail(d + "teams.json", f"teams {level} {season}", lambda: TM.build(ctx, hit, pit, sim, (sched or {}).get("games")),
                          level=level, season=season)
    spl = b.write_or_fail(d + "season.json", f"season {level} {season}", lambda: SN.build(ctx, tms, sim, markets), level=level, season=season)
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
    out = {"hitters": reduce_cat(hit, "hitter"), "pitchers": reduce_cat(pit, "pitcher"), "blocks": blocks, "current": current,
           "phase": ctx.phase, "season": season, "fld_validation": (fldp or {}).get("validation") if (fldp or {}).get("ok") else None}
    if full and current:
        out.update(cards=(sched or {}).get("games") or [], season_payload=spl, teams=tms, hit_full=_headline(hit, HEADLINE_H),
                   pit_full=_headline(pit, HEADLINE_P), ctx_entry=SN.level_entry(ctx, an.seasons_on_disk(level), tms, sim))
    if level == "mlb" and full:
        out["proj"] = ctx.model("proj_next") if not cfg["no_models"] else None
        out["hit_cat"], out["pit_cat"] = hit, pit
    manifest = {"sig": sig, "built_at": _now(), "full": full, "phase": ctx.phase, "games": pages, "prices": frozen,
                "model_errors": ctx.model_errors, "timings": {k: round(v, 1) for k, v in ctx.timings.items()}}
    b.step(f"manifest {level} {season}", lambda: b.write(d + "manifest.json", manifest))
    for k, v in ctx.timings.items():
        b.timings[f"{level} {season} {k}"] = v
    ctx.release()
    del ctx
    gc.collect()
    logger.info("%s %s (%s): %.1f s", level, season, "full" if full else "light", time.perf_counter() - t0)
    return out


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
        out[str(gpk)] = {"summary": summ, "model": GM.model_block(summ, g), "market": mk.get(str(gpk)), "priced_at": _now()}
    return out


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
            written += _one_page(b, ctx, gpk, groups.get(gpk), cards, prices, gdir, arsenal, umps, re_info, parks, fls.get(gpk), pas.get(gpk))
        del gp_all, groups, fls, pas
        gc.collect()
    for gpk in without:
        written += _one_page(b, ctx, gpk, None, cards, prices, gdir, arsenal, umps, re_info, parks)
    logger.info("%s %s: %d game pages written", ctx.level, ctx.season, written)
    return new_sigs


def _one_page(b: Build, ctx, gpk: str, gp, cards: dict, prices: dict, gdir: Path, arsenal: dict, umps: dict, re_info, parks,
              fl=None, pa=None) -> int:
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

def index_payload(b: Build, levels: dict[str, dict], today: date) -> dict:
    prev = an.read_json(b.data / "index.json") or {}
    out = {"ok": True, "updated_at": _now(), "levels": dict(prev.get("levels") or {})}
    if "npb" not in levels:
        out["levels"].pop("npb", None)                # NPB is not published (npb.jp terms)
    for k in ("season", "phase", "today", "recent", "upcoming", "postseason", "leaders", "teams"):
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
                             "teams": post.get("teams")} if post else None
        out["leaders"] = leaders
        tms = cur.get("teams") or {}
        out["teams"] = {t_: {k: r_.get(k) for k in ("name", "abbr", "short", "league", "division", "colour")} |
                        {k: (r_.get("values") or {}).get(k) for k in ("w", "l", "rating", "p_postseason", "p_ws")}
                        for t_, r_ in (tms.get("teams") or {}).items()}
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
