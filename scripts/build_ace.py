#!/usr/bin/env python
"""
Build The Quant Ace's payloads (oddsmarkets/tennis/PAYLOADS.md) into docs/ace/data/.

Site-wide: index.json, glossary.json; and docs/ace/assets/base.css (copied from the football site's
docs/site/assets/style.css).

Per tour, data/<T>/: rankings.json, race.json, elo.json, players.json (the current season's catalogue),
players_index.json, history.json, lab.json, markets.json, model.json (pricing constants for the browser),
calibration.json (builder C's backtest page copy; the WTA's adds B's inferred-v-real stats validation; {"ok": false}
until the backtest has run), value.json and value_validation.json (the Value section: breakout forecasts, luck, the ranking
and the market against the model; analytics/value.py, its validation cached per quarter), players/<pid>.json careers,
events/<event_id>.json tournament pages, matches/<mid>.json match centres and manifest.json (page signatures and payload
hashes).
Per tour and year, data/<T>/<year>/: players.json, events.json, schedule.json.

Years come in two weights:
  full   (--years, default the current year): predictions for every match, tournament simulations for live
         and upcoming events (--sims, 20,000), the season simulation (--season-sims, 10,000), markets
         (Kalshi / Polymarket, skipped with --no-market), the index entry;
  light  every other year with a store (skip with --no-light): catalogue, calendar, schedule and event pages
         from the stores and the cached model fits; a light year whose inputs are unchanged is skipped.
Match pages are written for tour-level matches of the --match-page-years most recent years (default 2), only
when a page's inputs changed (--all-matches rebuilds them all); live and upcoming matches are always rebuilt.
Event pages are written for the --event-page-years most recent years (default 3). Unchanged payloads are not
rewritten (their hashes are in the tour's manifest).

Every step is isolated: a failure is logged with its traceback and the build goes on; a payload that cannot
be built is written as {"ok": false, "reason": ...}. A run that did not build a tour's current year (or whose
index step failed) keeps that tour's previous entry in index.json.

Roots: --data / ACE_DATA (default docs/ace/data), --cache / ACE_CACHE (default data/tennis/cache).

    python scripts/build_ace.py                                    # both tours: current full, the rest light
    python scripts/build_ace.py --tours atp wta --years 2026 2025
    python scripts/build_ace.py --quick --no-market --no-light     # fast local check
"""
from __future__ import annotations

import argparse
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

from oddsmarkets.tennis import analytics as an  # noqa: E402

logger = logging.getLogger("build_ace")
CSS_SRC = ROOT / "docs" / "site" / "assets" / "style.css"
BUILD_VERSION = 1


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
        self.skipped = 0
        self.timings: dict[str, float] = {}
        self.manifests: dict[str, dict] = {}

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

    def manifest(self, tour: str) -> dict:
        m = self.manifests.get(tour)
        if m is None:
            m = an.read_json(self.data / tour / "manifest.json") or {}
            if m.get("version") != BUILD_VERSION:
                m = {}
            m.setdefault("files", {})
            m.setdefault("pages", {})
            m.setdefault("years", {})
            m["version"] = BUILD_VERSION
            self.manifests[tour] = m
        return m

    def write_if_changed(self, tour: str, rel: str, payload: Any) -> bool:
        """Write unless the payload (less its updated_at) hashes as in the tour's manifest and the file exists."""
        man = self.manifest(tour)
        body = {k: v for k, v in payload.items() if k != "updated_at"} if isinstance(payload, dict) else payload
        h = an.digest(_clean(body))
        if man["files"].get(rel) == h and (self.data / rel).exists():
            self.skipped += 1
            return False
        self.write(rel, payload)
        man["files"][rel] = h
        return True

    def write_or_fail(self, rel: str, name: str, fn: Callable[[], Any], tour: str | None = None, **extra) -> Any:
        """Build a payload; on failure write {"ok": false, "reason"} in its place."""
        payload = self.step(name, fn)
        if payload is None:
            payload = {"ok": False, "reason": f"{name} could not be built (see the build log)", **extra}
        if tour:
            self.step(f"write {rel}", lambda: self.write_if_changed(tour, rel, payload))
        else:
            self.step(f"write {rel}", lambda: self.write(rel, payload))
        return payload

    def save_manifests(self) -> None:
        for tour, m in self.manifests.items():
            m["built_at"] = an.now()
            self.write(f"{tour}/manifest.json", m)


# ---------------------------------------------------------------------------------------------- signatures

def year_sig(td: an.TourData, year: int) -> str:
    """A light year's inputs (its and the previous year's stores, the style table, the model code versions and
    the committed fits): its catalogue, schedule and event pages are rebuilt when it changes, so a refit
    rebuilds finished event pages."""
    from oddsmarkets.tennis.models import _io
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import predict as P
    from oddsmarkets.tennis.models import serve_return as SR
    sigs = []
    for y in (year - 1, year):
        p = an.data_root() / td.tour / str(y) / "store.json"
        try:
            st = p.stat()
            sigs.append([y, st.st_size, st.st_mtime_ns])
        except OSError:
            sigs.append([y, None, None])
    sty = an.data_root() / td.tour / "style.json"
    return an.digest(BUILD_VERSION, E.VERSION, SR.VERSION, P.VERSION, _io.fits_signature(td.tour), sigs,
                     sty.stat().st_size if sty.exists() else None)


# ---------------------------------------------------------------------------------------------- one tour

def build_tour(b: Build, tour: str, args, cfg: dict) -> dict:
    from oddsmarkets.tennis.analytics import events as EV
    from oddsmarkets.tennis.analytics import matches as MT
    from oddsmarkets.tennis.analytics import players as PL
    from oddsmarkets.tennis.analytics import race as RC
    from oddsmarkets.tennis.analytics import rankings as RK
    from oddsmarkets.tennis.analytics import site as SI
    t_tour = time.perf_counter()
    td = an.TourData(tour, cfg["today"])
    if not td.years:
        logger.warning("%s: no stores under %s", tour, b.data)
        return {"years": [], "entry": None}
    cur = td.current
    full = [y for y in (args.years or [cur]) if y in td.years]
    light = [] if args.no_light else [y for y in td.years if y not in full]
    page_years = {y for y in td.years if y > cur - cfg["match_page_years"]} if cfg["match_page_years"] > 0 else set(td.years)
    event_years = {y for y in td.years if y > cur - cfg["event_page_years"]} if cfg["event_page_years"] > 0 else set(td.years)
    man = b.manifest(tour)
    cur_full = cur in full
    logger.info("%s: years %s..%s on disk; full %s; light %d; match pages %s", tour, td.years[0], td.years[-1], full, len(light),
                sorted(page_years))
    b.step(f"{tour} elo", lambda: td.elo)

    # markets (current year, full builds only)
    prices, futures = {}, {}
    if cur_full and cfg["markets"]:
        from oddsmarkets.tennis.sources import markets as MK
        poly = cfg.get("poly_events")
        prices = b.step(f"{tour} match prices", lambda: MK.match_prices(tour, td.today, store=td.store(cur), poly_events=poly), {}) or {}
        stores = {y: td.store(y) for y in (cur, cur + 1) if y in td.years}
        futures = b.step(f"{tour} futures", lambda: MK.futures(tour, cur, stores=stores or None, poly_events=poly), {}) or {}
        logger.info("%s markets: %d match prices, %d tournament fields", tour, len(prices), len((futures or {}).get("tournaments") or {}))

    # predictions for the match-page years (light: no distributions)
    preds: dict[str, dict] = {}
    for y in sorted(page_years):
        ms = [m for m in td.matches(y).values() if an.is_tour_level(m)]
        preds.update(b.step(f"{tour} {y} predictions", lambda: MT.predictions(td, ms, with_dist=False), {}) or {})
    # full predictions (distributions) for the current year's open and recent matches (index cards, markets)
    recent = []
    if cur_full:
        for m in td.matches(cur).values():
            d = an.day(m.get("date"))
            if an.is_tour_level(m) and (m.get("status") in ("live", "upcoming") or (d and abs((d - td.today).days) <= 2)):
                recent.append(m)
        preds.update(b.step(f"{tour} open-match predictions", lambda: MT.predictions(td, recent, with_dist=True), {}) or {})

    # simulations
    sims: dict[str, dict] = {}
    race_sim = None
    if cur_full:
        ctx = b.step(f"{tour} today context", td.today_context)
        for eid, ev in td.events(cur).items():
            if ev.get("status") not in ("live", "upcoming") or str(ev.get("level")) not in an.TOUR_LEVELS:
                continue
            ms = EV.event_matches(td, eid, cur)
            r = b.step(f"{tour} sim {eid}", lambda: EV.simulate(td, dict(ev, id=eid, year=cur), ms, cfg["sims"], ctx))
            if r:
                sims[eid] = r
        race_sim = b.step(f"{tour} season sim", lambda: RC.simulate(td, cfg["season_sims"], ctx))
        logger.info("%s: %d event simulations; season simulation %s", tour, len(sims), "ok" if (race_sim or {}).get("ok") else "failed")

    # rankings, race, Elo
    cur_pts = b.step(f"{tour} event points {cur}", lambda: RK.event_points(td, cur), {}) or {}
    prev_pts = b.step(f"{tour} event points {cur - 1}", lambda: RK.event_points(td, cur - 1), {}) if (cur - 1) in td.years else {}
    defend = b.step(f"{tour} to defend", lambda: RK.to_defend(td, td.today, prev_pts or {}), {}) or {}
    race_rows = b.step(f"{tour} race", lambda: RK.race(td, cur, cur_pts), []) or []
    if cur_full:
        prev_rk = an.read_json(b.data / tour / "rankings.json") or {}
        b.write_or_fail(f"{tour}/rankings.json", f"{tour} rankings", lambda: RK.build_rankings(td, prev_rk, defend, race_rows), tour=tour)
        b.write_or_fail(f"{tour}/race.json", f"{tour} race.json", lambda: RC.build(td, race_sim, futures), tour=tour)
        b.write_or_fail(f"{tour}/elo.json", f"{tour} elo.json", lambda: RK.build_elo(td), tour=tour)

    # catalogues, calendars, schedules and event pages per year
    official = {r[1]: (int(r[0]), r[2] if len(r) > 2 else None) for r in (td.store(cur).get("rankings") or {}).get("rows") or []}
    proj = RC.proj_ranks(race_sim)
    extras_cur: dict[str, dict] = {}
    for p, (rk, pts) in official.items():
        extras_cur.setdefault(p, {}).update(rank=rk, points=pts)
    for p, v in race_rows:
        extras_cur.setdefault(p, {})["race_pts"] = v
    for p, rows in defend.items():
        extras_cur.setdefault(p, {})["to_defend"] = sum(r[2] for r in rows)
    for p, r in proj.items():
        extras_cur.setdefault(p, {})["proj_rank"] = r
    for p, v in ((race_sim or {}).get("finals_qual") or {}).items():
        extras_cur.setdefault(p, {})["p_finals"] = v
    for p, v in ((race_sim or {}).get("year_end_no1") or {}).items():
        extras_cur.setdefault(p, {})["p_no1"] = v
    hist = b.write_or_fail(f"{tour}/history.json", f"{tour} history", lambda: EV.history(td), tour=tour)
    entries: dict[int, dict] = {}
    catalogues: dict[int, dict] = {}
    want_entries = set(full) | set(light) | (set(td.years) if not args.no_careers else set())
    for y in sorted(want_entries, reverse=True):
        entries[y] = b.step(f"{tour} {y} entries", lambda: PL.season_entries(td, y), {}) or {}
    for y in sorted(set(full) | set(light), reverse=True):
        sig = year_sig(td, y)
        is_full = y in full
        if not is_full and not cfg["force"] and man["years"].get(str(y)) == sig and (b.data / tour / str(y) / "players.json").exists():
            logger.info("%s %s light: inputs unchanged, skipped", tour, y)
            continue
        t0 = time.perf_counter()
        n_skip = len(td.sr_skipped)
        ex = extras_cur if y == cur else None
        cat = b.write_or_fail(f"{tour}/{y}/players.json", f"{tour} {y} catalogue", lambda: PL.build(td, y, entries.get(y), ex), tour=tour,
                              year=y)
        if cat and cat.get("ok") is not False:
            catalogues[y] = cat
            if y == cur:
                b.step(f"write {tour}/players.json", lambda: b.write_if_changed(tour, f"{tour}/players.json", cat))
        pages = {eid for eid, ev in td.events(y).items() if str(ev.get("level")) in an.TOUR_LEVELS} if y in event_years else set()
        b.write_or_fail(f"{tour}/{y}/events.json", f"{tour} {y} events", lambda: EV.events_year(td, y, pages), tour=tour, year=y)
        b.write_or_fail(f"{tour}/{y}/schedule.json", f"{tour} {y} schedule",
                        lambda: MT.schedule(td, y, preds, prices if y == cur else None), tour=tour, year=y)
        n_ev = 0
        for eid in sorted(pages):
            mk = None
            if y == cur:
                t = next((t for k, t in ((futures or {}).get("tournaments") or {}).items() if (t or {}).get("event") == eid or k == eid), None)
                mk = SI._title(t)
            payload = b.step(f"{tour} event {eid}", lambda: EV.build_event(td, eid, y, preds, sims.get(eid), mk, hist, prices))
            if payload is None:
                payload = {"ok": False, "reason": "event page could not be built", "event": {"id": eid}}
            if b.write_if_changed(tour, f"{tour}/events/{eid}.json", payload):
                n_ev += 1
        # a year built while the refit budget left a serve/return checkpoint unfitted is not signed: the next run redoes it
        man["years"][str(y)] = sig if len(td.sr_skipped) == n_skip else None
        logger.info("%s %s (%s): %d event pages written, %.1f s", tour, y, "full" if is_full else "light", n_ev, time.perf_counter() - t0)

    # match pages
    def match_pages() -> int:
        due = []
        live_ids = set()
        for y in sorted(page_years):
            if y not in full and y not in light:
                continue
            for mid, m in td.matches(y).items():
                if not an.is_tour_level(m):
                    continue
                sig = MT.page_sig(m, tour)
                path = b.data / tour / "matches" / f"{an.fname(mid)}.json"
                if m.get("status") in ("live", "upcoming"):
                    live_ids.add(mid)
                if cfg["all_matches"] or m.get("status") in ("live", "upcoming") or man["pages"].get(mid) != sig or not path.exists():
                    due.append((y, m, sig))
        logger.info("%s: %d match pages due", tour, len(due))
        n = 0
        for k in range(0, len(due), 400):
            chunk = due[k:k + 400]
            full_preds = MT.predictions(td, [m for _, m, _ in chunk], with_dist=True)
            for y, m, sig in chunk:
                payload = b.step(f"match {tour}/{m['id']}", lambda: MT.build_match(td, m, full_preds.get(m["id"]) or preds.get(m["id"]),
                                                                                  prices.get(m["id"]), td.events(y).get(m.get("event"))))
                if payload is None:
                    payload = {"ok": False, "reason": "match page could not be built", "id": m["id"]}
                b.write(f"{tour}/matches/{an.fname(m['id'])}.json", payload)
                skipped = bool((full_preds.get(m["id"]) or {}).get("_sr_skipped"))
                man["pages"][m["id"]] = sig if (m["id"] not in live_ids and not skipped) else None
                n += 1
        return n
    n_pages = b.step(f"{tour} match pages", match_pages, 0)
    logger.info("%s: %s match pages written", tour, n_pages)

    # tour-wide payloads
    for y in td.years:                                          # catalogues not rebuilt this run: from disk
        if y not in catalogues:
            c = an.read_json(b.data / tour / str(y) / "players.json")
            if c and c.get("players") is not None:
                catalogues[y] = c
    b.write_or_fail(f"{tour}/players_index.json", f"{tour} players index", lambda: SI.players_index(td), tour=tour)
    b.write_or_fail(f"{tour}/lab.json", f"{tour} lab", lambda: SI.lab(td, catalogues), tour=tour)
    if cur_full:
        b.write_or_fail(f"{tour}/markets.json", f"{tour} markets",
                        lambda: SI.markets_payload(td, prices, futures, preds, sims, race_sim), tour=tour)
        b.write_or_fail(f"{tour}/model.json", f"{tour} model.json", lambda: SI.model_payload(td), tour=tour)
    b.step(f"{tour} calibration", lambda: calibration(b, td, cfg))
    if cur_full:
        b.step(f"{tour} value", lambda: value(b, td, entries, preds))
    if not args.no_careers:
        n = b.step(f"{tour} careers", lambda: careers(b, td, entries, preds, defend, race_sim, extras_cur), 0)
        logger.info("%s careers: %s written", tour, n)
    entry = None
    if cur_full:
        entry = b.step(f"{tour} index entry", lambda: SI.index_entry(td, preds, prices, sims, race_sim, race_rows))
    logger.info("%s: %.1f s", tour, time.perf_counter() - t_tour)
    return {"years": td.years, "entry": entry}


def calibration(b: Build, td: an.TourData, cfg: dict) -> None:
    """data/<T>/calibration.json is builder C's backtest page copy (backtest.backtest writes it; the newer of it and
    <ACE_CACHE>/backtest_<T>.json's page copy is kept). For the WTA, "validation_stats" adds B's score-inferred v
    real-stats check (serve_return.validate_stats) on the completed seasons with stats, cached on those matches.
    Without a backtest the file is {"ok": false, "reason"} (plus the validation when it exists)."""
    import hashlib
    from oddsmarkets.tennis.models import _io
    path = b.data / td.tour / "calibration.json"
    cur = an.read_json(path) or {}
    cached = an.read_json(an.cache_root() / f"backtest_{td.tour}.json")
    if isinstance(cached, dict) and str(cached.get("generated_at") or "") > str(cur.get("generated_at") or ""):
        from oddsmarkets.tennis.models import backtest as BT
        cur = BT.page_copy(cached)
    if not cur.get("generated_at"):
        cur = {"ok": False, "reason": "the walk-forward backtest has not been run yet (scripts/tn_fit.py --backtest)",
               "tour": td.tour, **({"validation_stats": cur["validation_stats"]} if cur.get("validation_stats") else {})}
    if td.tour == "wta" and cfg.get("validate", True):
        from oddsmarkets.tennis.models import serve_return as SR
        cut = f"{td.today.year}-07-01"
        ms = [m for m in td.rated_matches() if str(m.get("date"))[:10] < cut]
        years = sorted({int(str(m["date"])[:4]) for m in ms if m.get("stats")} - {td.today.year})
        if years and hasattr(SR, "validate_stats"):
            key = an.digest(SR.VERSION, years, len(ms), hashlib.sha1("".join(
                f"{m['id']}{bool(m.get('stats'))}{m.get('sets')}" for m in ms).encode()).hexdigest())
            cur["validation_stats"] = _io.cached("ace_validation", td.tour, key, lambda: SR.validate_stats(ms, years))
    b.write_if_changed(td.tour, f"{td.tour}/calibration.json", cur)


def value(b: Build, td: an.TourData, entries: dict[int, dict], preds: dict) -> None:
    """data/<T>/value.json (breakout and regression candidates, luck, ranking and market against the model) and
    data/<T>/value_validation.json (the walk-forward validation, cached per quarter under ACE_CACHE/ace_value):
    analytics/value.py. On failure both are written as {"ok": false, "reason"}."""
    from oddsmarkets.tennis.analytics import value as VL
    out = b.step(f"{td.tour} value build", lambda: VL.build_value(td, entries, preds))
    if not out:
        fail = {"ok": False, "reason": "the Value section could not be built (see the build log)", "tour": td.tour}
        out = (fail, fail)
    b.write_if_changed(td.tour, f"{td.tour}/value.json", out[0])
    b.write_if_changed(td.tour, f"{td.tour}/value_validation.json", out[1])


def careers(b: Build, td: an.TourData, entries: dict[int, dict], preds: dict, defend: dict, race_sim: dict | None,
            extras_cur: dict) -> int:
    from oddsmarkets.tennis.analytics import players as PL
    from oddsmarkets.tennis.analytics.rankings import active_elo
    per: dict[str, dict[int, list]] = {}
    for y, E in entries.items():
        for p, lst in (E or {}).items():
            per.setdefault(p, {})[y] = lst
    sr_by_year = {y: td.season_sr(y) for y in entries}
    elo_series = PL.elo_path(td)
    ranks = PL.rank_paths(td)
    h2h = PL.h2h_lists(td)
    r_all = PL.results_all_rows(td)
    last2 = {td.current, td.current - 1}
    recent: dict[str, list] = {}
    for y in last2 & set(td.years):
        for m in td.matches(y).values():
            if m.get("status") not in an.FINISHED or not m.get("p1") or not m.get("p2"):
                continue
            for p in (m["p1"], m["p2"]):
                recent.setdefault(str(p), []).append(m)
    fq = (race_sim or {}).get("finals_qual") or {}
    no1 = (race_sim or {}).get("year_end_no1") or {}
    act = active_elo(td, td.today + timedelta(days=1))
    order = sorted(act, key=lambda p: -act[p]["all"])
    erank = {p: i + 1 for i, p in enumerate(order)}
    srp = (td.season_sr(td.current) or {}).get("players") or {}
    n = 0
    for pid in sorted(per):
        ex = extras_cur.get(pid) or {}
        e = act.get(pid)
        rec = (srp.get(pid) or {}).get("all") or {}
        cur = {"rank": ex.get("rank"), "points": ex.get("points"), "race": ex.get("race_pts"), "to_defend": ex.get("to_defend"),
               "elo": {k: round(e[k], 1) for k in ("all",) + an.SURFACES} if e else None, "elo_rank": erank.get(pid),
               "hold": an.rnd(rec.get("hold"), 3), "brk": an.rnd(rec.get("break"), 3), "age": td.age(pid, td.today)}
        payload = PL.career_payload(td, pid, per[pid], sr_by_year, elo_series.get(pid), ranks.get(pid),
                                    PL.results_rows(td, pid, recent.get(pid) or [], preds), h2h.get(pid), defend.get(pid),
                                    {"finals_qual": an.prob(fq.get(pid)), "year_end_no1": an.prob(no1.get(pid))}, cur,
                                    r_all.get(pid))
        if b.write_if_changed(td.tour, f"{td.tour}/players/{an.fname(pid)}.json", payload):
            n += 1
    return n


# ---------------------------------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tours", nargs="*", choices=list(an.TOURS), default=list(an.TOURS))
    ap.add_argument("--years", type=int, nargs="*", help="years to build in full (default: the current year)")
    ap.add_argument("--sims", type=int, default=20000, help="tournament simulations (default 20000)")
    ap.add_argument("--season-sims", type=int, default=10000, help="season simulations (default 10000)")
    ap.add_argument("--quick", action="store_true", help="few simulations (tests and smoke runs)")
    ap.add_argument("--no-market", action="store_true", help="skip the Kalshi / Polymarket fetch")
    ap.add_argument("--no-light", action="store_true", help="build only the full years")
    ap.add_argument("--no-careers", action="store_true", help="skip data/<T>/players/<pid>.json")
    ap.add_argument("--match-page-years", type=int, default=2, help="match pages for the N most recent years (default 2; 0 = all)")
    ap.add_argument("--event-page-years", type=int, default=3, help="event pages for the N most recent years (default 3; 0 = all)")
    ap.add_argument("--all-matches", action="store_true", help="rebuild every match page in the window")
    ap.add_argument("--no-validate", action="store_true", help="skip the WTA inferred-v-real stats validation (slow when cold)")
    ap.add_argument("--force", action="store_true", help="rebuild light years even when their inputs are unchanged")
    ap.add_argument("--today", default=None, help="YYYY-MM-DD (default: today, UTC)")
    ap.add_argument("--data", default=None, help="data root (default ACE_DATA or docs/ace/data)")
    ap.add_argument("--cache", default=None, help="model cache root (default ACE_CACHE or data/tennis/cache)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("urllib3", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    t_start = time.perf_counter()
    if args.data:
        an.set_data_root(args.data)
    if args.cache:
        an.set_cache_root(args.cache)
    data = an.data_root()
    b = Build(data)
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    cfg = {"sims": min(args.sims, 1000) if args.quick else args.sims,
           "season_sims": min(args.season_sims, 500) if args.quick else args.season_sims,
           "markets": not args.no_market, "today": today, "match_page_years": args.match_page_years,
           "event_page_years": args.event_page_years, "all_matches": args.all_matches, "force": args.force,
           "validate": not args.no_validate}

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
    from oddsmarkets.tennis.analytics.glossary import build_glossary
    b.write_or_fail("glossary.json", "glossary", build_glossary)
    if cfg["markets"]:
        from oddsmarkets.tennis.sources import markets as MK
        cfg["poly_events"] = b.step("polymarket tennis events", MK.poly_tennis_events, None)

    tours: dict[str, dict] = {}
    for tour in args.tours:
        tours[tour] = b.step(f"tour {tour}", lambda: build_tour(b, tour, args, cfg), {}) or {}

    def index():
        prev = an.read_json(data / "index.json") or {}
        out = {"ok": True, "updated_at": an.now(), "tours": dict(prev.get("tours") or {})}
        for t, r in tours.items():
            if r.get("entry") is None:
                continue                  # the current year was not built (or its index step failed): keep the entry
            out["tours"][t] = r["entry"]
        return out
    b.write_or_fail("index.json", "index", index)
    b.step("manifests", b.save_manifests)

    total = sum(p.stat().st_size for p in set(b.written) if p.exists())
    logger.info("wrote %d files (%.1f MB), %d unchanged, in %.1f s; %d step errors", len(set(b.written)), total / 1e6, b.skipped,
                time.perf_counter() - t_start, len(b.errors))
    slow = sorted(((k, v) for k, v in b.timings.items() if not k.startswith(("match ", "write "))), key=lambda kv: -kv[1])[:25]
    for k, v in slow:
        logger.info("  %-50s %7.1f s", k, v)
    for e in b.errors[:50]:
        logger.info("  error: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
