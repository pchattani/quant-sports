#!/usr/bin/env python
"""
Build The Quant Paddock's payloads (oddsmarkets/f1/PAYLOADS.md) into docs/paddock/data/.

Site-wide: index.json, glossary.json, calibration.json (the cached walk-forward backtest),
markets.json (title and next-race markets v the model), elo.json, lab.json, circuits.json and
drivers/<driverId>.json careers.

Per season, data/<year>/: season.json, drivers.json, teams.json, circuits.json,
races/<round>.json for every round, done and upcoming, and value.json (driver value and
constructors by car pace, 1994 onward); for the current unfinished season also swap.json (the
driver-swap simulator: every pair of drivers swapped through the championship simulation) and
needs.json (constructors' strengths and needs) (docs/VALUE_SECTIONS.md); for the current season
fantasy.json (our fantasy-style projections and picks) and, site-wide, fantasy_backtest.json (the
walk-forward fantasy backtest, extended with the current season's weekends; the full multi-season
run is `python -m oddsmarkets.f1.analytics.fantasy backtest`).

Seasons come in two weights:
  full   (--seasons, default the current season): walk-forward race forecasts for every round
         (pre- and post-qualifying and sprint; cached under data/f1/cache/forecasts), "points v
         expected" and the awards that need a forecast, and for an unfinished season the
         championship simulation (--sims, 20,000 by default).
  light  every other season on disk (skip with --no-light): the same payloads from results,
         qualifying, laps and the pace models where they exist, without forecasts or a
         championship simulation. Seasons before lap times (pre-1996) get results/qualifying and
         empty lap sections.

Every step is isolated: a failure is logged with its traceback and the rest of the build goes
on; a payload that cannot be built is written with {"ok": false, "reason": ...}.

The data root (season stores in, payloads out) is docs/paddock/data unless --data or the
PADDOCK_DATA environment variable points elsewhere (tests build into a temporary folder);
model caches can be redirected with --cache / PADDOCK_CACHE.

    python scripts/build_paddock.py                                   # current season full + every season light
    python scripts/build_paddock.py --seasons 2026 2025 --sims 20000
    python scripts/build_paddock.py --quick --no-market --no-light    # fast local check
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oddsmarkets.f1 import canon  # noqa: E402
from oddsmarkets.f1 import analytics as an  # noqa: E402

logger = logging.getLogger("build_paddock")


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
    return o


class Build:
    def __init__(self, data: Path):
        self.data = data
        self.errors: list[str] = []
        self.written: list[Path] = []

    def step(self, name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - never let one step take down the build
            logger.error("step %s failed: %s\n%s", name, exc, traceback.format_exc())
            self.errors.append(f"{name}: {exc}")
            return default

    def write(self, rel: str, payload: Any) -> None:
        p = self.data / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(_clean(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        tmp.replace(p)
        self.written.append(p)

    def write_or_fail(self, rel: str, name: str, fn: Callable[[], Any], **extra) -> Any:
        """Build a payload; on failure write {"ok": false, "reason"} in its place."""
        payload = self.step(name, fn)
        if payload is None:
            payload = {"ok": False, "reason": f"{name} could not be built (see the build log)", **extra}
        self.step(f"write {rel}", lambda: self.write(rel, payload))
        return payload


def pick_calibration(committed: Path, cache: Path | None = None) -> dict:
    """calibration.json: the newer of the cached walk-forward backtest (`models.backtest.OUT`) and the committed
    calibration.json, by `generated_at`. The full backtest runs locally and its output is committed; CI restores an
    older model cache, which must not overwrite a newer committed run (it did from 2 to 22 October 2026)."""
    from oddsmarkets.f1.models import backtest as bt
    cache = Path(bt.OUT) if cache is None else cache
    old = None
    if committed.exists():
        try:
            old = json.loads(committed.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = None
        if not (old or {}).get("ok"):
            old = None
    if not cache.exists():
        if old:
            return old
        return {"ok": False, "reason": "no cached backtest (run oddsmarkets.f1.models.backtest.backtest())", "updated_at": _now()}
    d = json.loads(cache.read_text(encoding="utf-8"))
    if old and str(old.get("generated_at") or "") > str(d.get("generated_at") or ""):
        return old
    d.update({"ok": True, "updated_at": d.get("generated_at") or _now(), "races": d.get("races"),
              "seasons": sorted(int(y) for y in (d.get("seasons_used") or {})), "skipped": d.get("skipped") or {},
              "summary": bt.summary_table(d)})
    return d


def current_season(years: list[int]) -> int | None:
    """The newest season on disk with a calendar."""
    for y in sorted(years, reverse=True):
        if canon.rounds(y):
            return y
    return max(years) if years else None


def season_forecasts(b: Build, year: int, race_sims: int, next_sims: int) -> tuple[dict[int, dict], tuple[int, dict] | None]:
    """{round: {"pre", "post", "sprint"}} walk-forward forecasts for every round, and (next round, its SIM)."""
    from oddsmarkets.f1.analytics import forecasts as fc
    out: dict[int, dict] = {}
    nxt = None
    for r in canon.rounds(year):
        race = canon.race(year, r)
        done = bool(race.get("results"))
        is_next = not done and nxt is None
        n = race_sims if done or not is_next else next_sims
        f = {"pre": b.step(f"forecast {year}/{r} pre", lambda: fc.forecast(year, r, "pre", n)),
             "post": b.step(f"forecast {year}/{r} post", lambda: fc.forecast(year, r, "post", n)) if (race.get("qualifying") or done) else None,
             "sprint": b.step(f"forecast {year}/{r} sprint", lambda: fc.forecast(year, r, "sprint", n)) if fc.is_sprint_weekend(year, r) else None}
        out[r] = f
        if is_next:
            nxt = (r, f.get("post") or f.get("pre"))
    return out, nxt


def build_season(b: Build, year: int, current: int, full: bool, cfg: dict, shared: dict) -> dict:
    """Every per-season payload for one year; returns what the site-wide payloads need."""
    from oddsmarkets.f1.analytics import circuits as circ
    from oddsmarkets.f1.analytics import drivers as drv
    from oddsmarkets.f1.analytics import races as rc
    from oddsmarkets.f1.analytics import season as ssn
    from oddsmarkets.f1.analytics import teams as tms
    t0 = time.perf_counter()
    d = f"{year}/"
    stand = shared["standings"].get(year) or b.step(f"standings {year}", lambda: ssn.standings(year))
    colours = b.step(f"colours {year}", lambda: ssn.team_colours(year), {}) or {}
    effects: dict = {}
    if year >= 1994:
        from oddsmarkets.f1.models.decomposition import season_effects
        effects = (shared.get("effects") or {}).get(year) or b.step(f"effects {year}", lambda: season_effects(year), {}) or {}
    forecasts, nxt = ({}, None)
    if full:
        forecasts, nxt = b.step(f"forecasts {year}", lambda: season_forecasts(b, year, cfg["race_sims"], cfg["sims"]), ({}, None))
    records = b.step(f"driver records {year}", lambda: drv.collect(year, forecasts), {}) or {}
    elo_y = ssn.season_elo(shared.get("elo"), year)
    dcat = b.write_or_fail(d + "drivers.json", f"drivers {year}",
                           lambda: drv.build(year, records, forecasts, effects, elo_y, (stand or {}).get("drivers")), year=year)
    split = b.step(f"car/driver split {year}", lambda: tms.car_driver_split(year, effects, cfg["split_sims"] if full else cfg["split_sims_light"]), {}) or {}
    dvals = {k: v.get("values") or {} for k, v in ((dcat or {}).get("drivers") or {}).items()}
    tcat = b.write_or_fail(d + "teams.json", f"teams {year}", lambda: tms.build(year, records, dvals, effects, colours, split, forecasts), year=year)
    champ = None
    if full and not ssn.finished(year, current):
        from oddsmarkets.f1.models.championship import simulate_championship
        champ = b.step(f"championship {year}", lambda: simulate_championship(year, n=cfg["sims"], seed=year))
    sp = b.data / d / "season.json"
    prev = b.step(f"read {sp}", lambda: json.loads(sp.read_text(encoding="utf-8"))) if sp.exists() else None
    b.write_or_fail(d + "season.json", f"season {year}",
                    lambda: ssn.build_season(year, current, forecasts=forecasts, effects=effects, split=split, championship=champ,
                                             elo=shared.get("elo"), colours=colours, stand=stand, prev=prev), year=year,
                    **({"title_history": prev["title_history"]} if (prev or {}).get("title_history") else {}))
    shared.setdefault("effects", {})[year] = effects
    b.step(f"value pages {year}", lambda: value_pages(b, year, current, full, effects, dcat, tcat, champ, cfg, shared))
    if full and year == current:
        b.step(f"fantasy pages {year}", lambda: fantasy_pages(b, year, dcat, cfg, shared))
    for r in canon.rounds(year):
        b.write_or_fail(f"{d}races/{r}.json", f"race {year}/{r}", lambda: rc.build_race(year, r, forecasts.get(r), effects), year=year, round=r)
    if shared.get("circuits"):
        b.write_or_fail(d + "circuits.json", f"circuits {year}", lambda: circ.build_season(year, shared["circuits"]))
    logger.info("season %s (%s): %.1f s", year, "full" if full else "light", time.perf_counter() - t0)
    return {"catalogue": dcat, "championship": champ, "next": nxt}


def value_pages(b: Build, year: int, current: int, full: bool, effects: dict, dcat: dict | None, tcat: dict | None, champ: dict | None,
                cfg: dict, shared: dict) -> None:
    """value.json (1994 onward, when the decomposition has a season); for the current unfinished season the swap table
    (every pair of drivers on different teams swapped through the championship simulation, cached on its inputs),
    swap.json and needs.json."""
    from oddsmarkets.f1.analytics import forecasts as fc
    from oddsmarkets.f1.analytics import value as VL
    d = f"{year}/"
    if not (effects or {}).get("driver"):
        return
    prev = (shared.get("effects") or {}).get(year - 1)
    if prev is None and year - 1 >= 1994:
        from oddsmarkets.f1.models.decomposition import season_effects
        prev = b.step(f"effects {year - 1} (trend)", lambda: season_effects(year - 1), {}) or {}
        shared.setdefault("effects", {})[year - 1] = prev
    b.write_or_fail(d + "value.json", f"value {year}", lambda: VL.value_payload(year, effects, prev, dcat, tcat, champ, year == current), year=year)
    if not (full and champ):
        return
    names = {k: v.get("name") or k for k, v in ((dcat or {}).get("drivers") or {}).items()}
    t0 = time.perf_counter()
    table = b.step(f"swap table {year}", lambda: VL.swap_table(year, effects, n=cfg["swap_sims"], cache_dir=Path(fc.CACHE).parent / "swaps"),
                   {"ok": False, "reason": "swap table failed"}) or {}
    logger.info("swap table %s: %s pairs, %s (%.1f s)", year, len(table.get("pairs") or {}), "cached" if table.get("cached") else "computed",
                time.perf_counter() - t0)
    b.write_or_fail(d + "swap.json", f"swap {year}", lambda: VL.swap_payload(year, table, champ, names), year=year)
    b.write_or_fail(d + "needs.json", f"needs {year}", lambda: VL.needs_payload(year, tcat, dcat, table, names), year=year)


def fantasy_pages(b: Build, year: int, dcat: dict | None, cfg: dict, shared: dict) -> None:
    """data/<year>/fantasy.json (analytics/fantasy.py): the walk-forward fantasy backtest brought up to date (cached per
    weekend; kept in `shared` for the site-wide fantasy_backtest.json), the next-weekend and rest-of-season projection,
    value against the form line and our picks."""
    from oddsmarkets.f1.analytics import fantasy as FT
    t0 = time.perf_counter()
    bt = b.step("fantasy backtest", lambda: FT.update_backtest(year, n=cfg["fantasy_bt_sims"]))
    shared["fantasy_bt"] = bt
    logger.info("fantasy backtest: %s races (%s new) in %.1f s", (bt or {}).get("races"), (bt or {}).get("new"), time.perf_counter() - t0)
    t1 = time.perf_counter()
    proj = b.step(f"fantasy projection {year}", lambda: FT.season_projection(year, n=cfg["fantasy_sims"]),
                  {"ok": False, "reason": "the projection failed (see the build log)"}) or {"ok": False, "reason": "no projection"}
    logger.info("fantasy projection %s: %s (%.1f s)", year, "ok" if proj.get("ok") else proj.get("reason"), time.perf_counter() - t1)
    vp = b.data / str(year) / "value.json"
    value = b.step(f"read {vp}", lambda: json.loads(vp.read_text(encoding="utf-8"))) if vp.exists() else None
    b.write_or_fail(f"{year}/fantasy.json", f"fantasy {year}",
                    lambda: FT.fantasy_payload(year, proj, FT.season_actuals(year), FT.season_actuals(year - 1), value, dcat, bt=bt), year=year)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", type=int, nargs="*", help="seasons to build in full (default: the current season)")
    ap.add_argument("--sims", type=int, default=20000, help="championship and next-race simulations (default 20000)")
    ap.add_argument("--race-sims", type=int, default=3000, help="simulations per walk-forward race forecast (default 3000)")
    ap.add_argument("--swap-sims", type=int, default=1000, help="championship simulations per driver swap (default 1000)")
    ap.add_argument("--no-market", action="store_true", help="skip the Kalshi / Polymarket fetch")
    ap.add_argument("--no-light", action="store_true", help="build only the --seasons, not the light payloads for every other season")
    ap.add_argument("--quick", action="store_true", help="few simulations (tests and smoke runs)")
    ap.add_argument("--data", default=None, help="data root (default PADDOCK_DATA or docs/paddock/data)")
    ap.add_argument("--cache", default=None, help="model cache root (default PADDOCK_CACHE or data/f1/cache)")
    ap.add_argument("--no-careers", action="store_true", help="skip data/drivers/<id>.json")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("urllib3", "requests", "oddsmarkets.f1.models.race_sim"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    t_start = time.perf_counter()
    if args.data or os.environ.get("PADDOCK_DATA"):
        an.set_data_root(args.data or os.environ["PADDOCK_DATA"])
    if args.cache or os.environ.get("PADDOCK_CACHE"):
        an.set_cache_root(args.cache or os.environ["PADDOCK_CACHE"])
    data = an.data_root()
    b = Build(data)
    cfg = {"sims": args.sims, "race_sims": args.race_sims, "split_sims": 2000, "split_sims_light": 500, "swap_sims": args.swap_sims,
           "fantasy_sims": 4000, "fantasy_bt_sims": 2000}
    if args.quick:
        cfg = {"sims": min(args.sims, 400), "race_sims": min(args.race_sims, 150), "split_sims": 150, "split_sims_light": 100,
               "swap_sims": min(args.swap_sims, 150), "fantasy_sims": 300, "fantasy_bt_sims": 100}

    from oddsmarkets.f1.analytics import circuits as circ
    from oddsmarkets.f1.analytics import season as ssn
    from oddsmarkets.f1.analytics.glossary import build_glossary

    years = an.seasons_on_disk()
    current = current_season(years)
    logger.info("data root %s: %d seasons on disk, current %s", data, len(years), current)

    # the shared design kit (docs/_design -> assets/qk), as every redesigned site does
    def kit():
        sys.path.insert(0, str(ROOT / "scripts"))
        from design_kit import copy_kit
        b.written.append(copy_kit(data.parent))
    b.step("copy the design kit", kit)
    b.write_or_fail("glossary.json", "glossary", build_glossary)
    if current is None:
        b.write("index.json", {"ok": False, "reason": "no season stores on disk", "updated_at": _now(), "seasons": []})
        logger.error("no season stores under %s", data)
        return 1

    full = [y for y in (args.seasons or [current]) if y in years]
    light = [] if args.no_light else [y for y in years if y not in full]
    shared: dict[str, Any] = {}
    from oddsmarkets.f1.models.elo import elo_history
    shared["elo"] = b.step("elo history", lambda: elo_history(seasons=range(min(years), max(years) + 1)), {}) or {}
    shared["standings"] = {y: b.step(f"standings {y}", lambda: ssn.standings(y)) for y in years}
    finished_years = {y for y in years if b.step(f"finished {y}", lambda: ssn.finished(y, current), False)}
    shared["circuits"] = b.step("circuits", lambda: circ.build_all(years), {}) or {}

    out: dict[int, dict] = {}
    for y in full + light:
        out[y] = b.step(f"season {y}", lambda: build_season(b, y, current, y in full, cfg, shared), {}) or {}

    # site-wide
    metas = {y: b.step(f"meta {y}", lambda: ssn.season_meta(y, current, shared["standings"].get(y))) for y in years}
    cols = b.step("colours current", lambda: ssn.team_colours(current), {})
    b.write_or_fail("index.json", "index", lambda: ssn.index(current, years, metas, cols))
    b.write_or_fail("elo.json", "elo", lambda: ssn.elo_payload(shared["elo"]))
    cats = {y: o.get("catalogue") for y, o in out.items() if (o or {}).get("catalogue") and o["catalogue"].get("ok", True)}
    for y in years:                                       # seasons not rebuilt this run: reuse their drivers.json on disk
        if y not in cats and y >= 1996:
            p = data / str(y) / "drivers.json"
            if p.exists():
                cats[y] = b.step(f"read {p}", lambda: json.loads(p.read_text(encoding="utf-8")))
    b.write_or_fail("lab.json", "lab", lambda: ssn.lab_payload({y: c for y, c in cats.items() if c}, current))

    def similar_drivers() -> int:
        """Similar drivers (drivers.add_similar) need every season's catalogue from 1996: the ones built this run, the
        rest from disk; each catalogue that gains the field is rewritten."""
        from oddsmarkets.f1.analytics import drivers as drv
        allc = {y: c for y, c in cats.items() if c and y >= drv.SIMILAR_FROM}
        for y in years:
            if y >= drv.SIMILAR_FROM and y not in allc:
                p = data / str(y) / "drivers.json"
                if p.exists():
                    c = b.step(f"read {p}", lambda: json.loads(p.read_text(encoding="utf-8")))
                    if c and c.get("ok", True) and c.get("drivers"):
                        allc[y] = c
        changed = drv.add_similar(allc)
        for y in changed:
            b.write(f"{y}/drivers.json", allc[y])
        return len(changed)
    n_sim = b.step("similar drivers", similar_drivers, 0)
    logger.info("similar drivers: %s seasons", n_sim)
    b.write_or_fail("circuits.json", "circuits site-wide", lambda: shared["circuits"] or None)

    b.write_or_fail("calibration.json", "calibration", lambda: pick_calibration(an.data_root() / "calibration.json"))

    def fantasy_backtest():
        from oddsmarkets.f1.analytics import fantasy as FT
        bt = shared.get("fantasy_bt")
        if not (bt or {}).get("ok"):
            # not rebuilt this run (or failed): the cached run, else keep the published payload rather than "not built"
            cp = FT.cache_dir() / "backtest.json"
            if cp.exists():
                bt = json.loads(cp.read_text(encoding="utf-8"))
        pay = FT.backtest_payload(bt)
        if pay is None:
            prev = an.data_root() / "fantasy_backtest.json"
            if prev.exists():
                old = json.loads(prev.read_text(encoding="utf-8"))
                if old.get("ok"):
                    return old
            return {"ok": False, "reason": "no fantasy backtest yet (python -m oddsmarkets.f1.analytics.fantasy backtest)", "updated_at": _now()}
        return pay
    b.write_or_fail("fantasy_backtest.json", "fantasy backtest", fantasy_backtest)
    cur = out.get(current) or {}
    champ_block = None
    if cur.get("championship"):
        champ_block = ssn._champ_block(cur["championship"])
    b.write_or_fail("markets.json", "markets", lambda: ssn.markets_payload(current, champ_block, cur.get("next"), fetch=not args.no_market))
    if not args.no_careers:
        def careers():
            cs = ssn.careers(years, shared["standings"], shared["elo"], finished_years)
            for d, c in cs.items():
                b.write(f"drivers/{d}.json", c)
            return len(cs)
        n = b.step("careers", careers, 0)
        logger.info("careers: %s drivers", n)

    total = sum(p.stat().st_size for p in b.written if p.exists())
    logger.info("wrote %d files (%.1f MB) in %.1f s; %d step errors", len(b.written), total / 1e6, time.perf_counter() - t_start, len(b.errors))
    for e in b.errors[:50]:
        logger.info("  error: %s", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
