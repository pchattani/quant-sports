"""Build The Quant Campus (docs/campus): the design kit, every level's payloads and the site-wide files.

    python scripts/build_campus.py                          # every level, every season with a store
    python scripts/build_campus.py --levels cfb --seasons 2025,2026 --sims 2000
    python scripts/build_campus.py --quick                  # current and previous season, 2,000 sims, no markets
    python scripts/build_campus.py --recent 2               # CI: per-level files from every season, season payloads
                                                            # for the newest two (older ones come from the live site)

Steps (oddsmarkets/college/CONTRACT.md section 4), each isolated so one failure never stops the rest; a failed
step is logged with its traceback and its payloads are written as {"ok": false, "reason"}:
  1. copy the kit (scripts/design_kit.copy_kit) into docs/campus/assets/qk
  2. per level: football (oddsmarkets.college.football.build) for cfb, basketball (oddsmarkets.college.hoops.build)
     for mbb and wbb: build_level(...) for the per-level files, then build(...) for each season, newest first.
     Game pages (full=True) only for the newest --game-page-seasons seasons (default 2: the current season and the
     previous one, whose postseason pages the site links to)
     Then, for the current season, who moves next (oddsmarkets/college/movement.py: <S>/movement.json and the team
     pages' `movement`)
  3. site-wide payloads: oddsmarkets/college/site.py (index.json, glossary.json, search.json)
  4. a size report by folder; exits non-zero over the 800 MB budget (PAYLOADS.md)

Payloads go to CAMPUS_DATA (default docs/campus/data). Set OMP_NUM_THREADS=1 (and MKL / OPENBLAS) for heavy runs:
the machine's four cores are shared.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

DOCS = ROOT / "docs"
SITE = DOCS / "campus"
BUDGET_MB = 800
LEVEL_BUDGET_MB = 250          # per level (PAYLOADS.md size budget); reported, the build fails only over BUDGET_MB
LEVELS = ("cfb", "mbb", "wbb")
MODULE = {"cfb": "oddsmarkets.college.football.build", "mbb": "oddsmarkets.college.hoops.build",
          "wbb": "oddsmarkets.college.hoops.build"}
# payloads a season must have; written as {"ok": false} when its build fails before writing them
SEASON_FILES = {"cfb": ("season", "schedule", "cfp", "teams", "players", "value", "moves", "fantasy", "lab_teams", "lab_players"),
                "mbb": ("season", "schedule", "bracket", "teams", "players", "value", "moves", "fantasy", "lab_teams", "lab_players")}
SEASON_FILES["wbb"] = SEASON_FILES["mbb"]
LEVEL_FILES = ("calibration", "history", "markets")

log = logging.getLogger("build_campus")


def fail_payload(reason: str) -> dict:
    return {"ok": False, "reason": reason}


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)


def fill_missing(folder: Path, names, reason: str) -> list[str]:
    """Write {"ok": false, "reason"} for every payload in `names` not present in `folder` (never overwrites)."""
    out = []
    for n in names:
        p = folder / f"{n}.json"
        if not p.exists():
            write_json(p, fail_payload(reason))
            out.append(n)
    return out


def call(fn, *args, **kw):
    """Call fn with only the keyword arguments its signature accepts (B's and C's builders differ slightly)."""
    try:
        params = inspect.signature(fn).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
            kw = {k: v for k, v in kw.items() if k in params}
    except (TypeError, ValueError):
        pass
    return fn(*args, **kw)


def step(name: str, fn, report: dict):
    t0 = time.perf_counter()
    try:
        res = fn()
        report[name] = {"ok": not (isinstance(res, dict) and res.get("ok") is False), "s": round(time.perf_counter() - t0, 1)}
        if isinstance(res, dict) and res.get("ok") is False:
            report[name]["reason"] = str(res.get("reason") or res.get("errors"))[:300]
            log.warning("%s: not ok (%s)", name, report[name]["reason"])
        else:
            log.info("%s: done in %.1fs", name, report[name]["s"])
        return res
    except Exception as exc:  # one step failing never stops the build
        tb = traceback.format_exc()
        log.error("%s failed:\n%s", name, tb)
        report[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "reason": f"{type(exc).__name__}: {exc}"}
        return None


def seasons_for(level: str, wanted: list[int] | None, quick: bool) -> list[int]:
    from oddsmarkets.college import canon, store
    cur = canon.current_season(level)
    have = store.seasons_on_disk(level)
    if wanted:
        ss = [s for s in wanted if s in have or s == cur]
    elif quick:
        ss = [s for s in (cur, cur - 1) if s in have]
    else:
        ss = list(have)
    return sorted(set(ss), reverse=True)


def build_level(level: str, data: Path, seasons: list[int], a, report: dict, level_seasons: list[int] | None = None) -> None:
    from oddsmarkets.college import canon
    cur = canon.current_season(level)
    try:
        mod = importlib.import_module(MODULE[level])
    except Exception as exc:
        reason = f"{MODULE[level]} not importable: {type(exc).__name__}: {exc}"
        log.error("%s: %s", level, reason)
        report[f"{level}:import"] = {"ok": False, "reason": reason}
        fill_missing(data / level, LEVEL_FILES, reason)
        for s in seasons:
            fill_missing(data / level / str(s), SEASON_FILES[level], reason)
        return
    fb = level == "cfb"
    sims = a.sims
    markets = not a.no_market
    # per-level files (calibration, history, players careers, markets); seasons are built one by one below
    if hasattr(mod, "build_level"):
        if fb:
            step(f"{level}:level", lambda: call(mod.build_level, data, level_seasons or seasons, cur, sims=sims, markets=markets, per_season=False), report)
        else:
            step(f"{level}:level", lambda: call(mod.build_level, level, data, level_seasons or seasons, cur, sims=sims, markets=markets, per_season=False), report)
    fill_missing(data / level, LEVEL_FILES, f"{level} level build did not write this payload")
    newest = sorted(seasons, reverse=True)[: max(0, a.game_page_seasons)]
    for s in seasons:
        full = s in newest
        name = f"{level}:{s}"
        if fb:
            step(name, lambda s=s, full=full: call(mod.build, s, data, None, full=full, sims=sims, markets=markets), report)
        else:
            step(name, lambda s=s, full=full: call(mod.build, level, s, data, None, full=full, sims=sims, markets=markets), report)
        missing = fill_missing(data / level / str(s), SEASON_FILES[level],
                               (report.get(name) or {}).get("reason") or f"not built for {level} {s}")
        if missing:
            log.warning("%s: wrote ok:false for %s", name, ", ".join(missing))
    # who moves next (oddsmarkets/college/movement.py): <S>/movement.json and `movement` on the team pages just written
    if cur in seasons:
        from oddsmarkets.college import movement
        step(f"{level}:movement", lambda: movement.write_movement(level, data, cur), report)
    # top performers on the team pages (oddsmarkets/college/top_performers.py), from each built season's players.json
    from oddsmarkets.college import top_performers
    for s in seasons:
        step(f"{level}:{s}:top", lambda s=s: top_performers.write_top(level, data, s), report)
    # seasons not rebuilt here (CI: restored from the live site) are upgraded to the builder's payload format
    if hasattr(mod, "migrate"):
        built = set(seasons)
        others = sorted(int(p.name) for p in (data / level).glob("*") if p.is_dir() and p.name.isdigit() and int(p.name) not in built)

        def _migrate():
            n = {s: call(mod.migrate, level, data, s) for s in others}
            done = {s: k for s, k in n.items() if k}
            if done:
                log.info("%s: migrated %d season folders to the current payload format (%d files)", level, len(done),
                         sum(done.values()))
            return {"ok": True, "migrated": done}
        if others:
            step(f"{level}:migrate", _migrate, report)


# ───────────────────────────────────────────────────────────── size report
def size_report(site: Path, budget_mb: float = BUDGET_MB) -> dict:
    """Bytes by folder (data/<L>/<S>, data/<L>/players, data/<L> files, data top level, assets, other)."""
    rows: dict[str, int] = {}
    total = 0
    for root, _dirs, files in os.walk(site):
        for f in files:
            p = Path(root) / f
            try:
                n = p.stat().st_size
            except OSError:
                continue
            total += n
            rel = p.relative_to(site).parts
            if rel[0] == "data" and len(rel) >= 3 and rel[1] in LEVELS:
                key = "/".join(rel[:3]) if (len(rel) > 3) else f"data/{rel[1]} (level files)"
            elif rel[0] == "data":
                key = "data (site-wide)"
            elif rel[0] == "assets":
                key = "assets"
            else:
                key = "(root)"
            rows[key] = rows.get(key, 0) + n
    mb = total / 1e6
    levels = {L: round(sum(v for k, v in rows.items() if k.startswith(f"data/{L}/") or k == f"data/{L} (level files)") / 1e6, 1)
              for L in LEVELS}
    return {"total_mb": round(mb, 1), "budget_mb": budget_mb, "over": mb > budget_mb, "levels": levels,
            "level_budget_mb": LEVEL_BUDGET_MB, "levels_over": [L for L, v in levels.items() if v > LEVEL_BUDGET_MB],
            "folders": {k: round(v / 1e6, 2) for k, v in sorted(rows.items(), key=lambda kv: -kv[1])}}


def print_size(rep: dict) -> None:
    print(f"\nSize report (docs/campus): {rep['total_mb']:.1f} MB of a {rep['budget_mb']} MB budget"
          + ("  ** OVER BUDGET **" if rep["over"] else ""))
    for L, v in (rep.get("levels") or {}).items():
        print(f"  {v:9.1f} MB  {L} (all files; budget {rep.get('level_budget_mb')} MB)"
              + ("  ** OVER THE LEVEL BUDGET **" if L in (rep.get("levels_over") or []) else ""))
    for k, v in rep["folders"].items():
        print(f"  {v:9.2f} MB  {k}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--levels", default=",".join(LEVELS), help="comma list of cfb,mbb,wbb")
    ap.add_argument("--seasons", default="", help="comma list of seasons (default: every season with a store)")
    ap.add_argument("--sims", type=int, default=20000, help="season simulations per season (default 20000)")
    ap.add_argument("--no-market", action="store_true", help="skip prediction-market fetches")
    ap.add_argument("--quick", action="store_true", help="current and previous season only, 2,000 sims, no markets")
    ap.add_argument("--game-page-seasons", type=int, default=2, help="newest seasons that get game pages (default 2)")
    ap.add_argument("--recent", type=int, default=0,
                    help="build season payloads only for the newest N seasons per level (per-level files still read every season)")
    ap.add_argument("--no-kit", action="store_true", help="do not copy the design kit")
    ap.add_argument("--site-only", action="store_true", help="only the site-wide payloads and the size report")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[build_campus] %(levelname)s %(message)s")
    if a.quick:
        a.sims = min(a.sims, 2000)
        a.no_market = True
    t0 = time.perf_counter()
    from oddsmarkets.college import site, store
    data = Path(store.paths()["data"])
    data.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    if not a.no_kit:
        step("kit", lambda: __import__("design_kit").copy_kit(SITE), report)
    levels = [x.strip() for x in a.levels.split(",") if x.strip() in LEVELS]
    wanted = [int(x) for x in a.seasons.split(",") if x.strip().isdigit()] or None
    if not a.site_only:
        for L in levels:
            ss = seasons_for(L, wanted, a.quick)
            every = None
            if a.recent > 0:
                every = seasons_for(L, None, False)
                ss = every[: a.recent]
            log.info("%s: seasons %s", L, ss)
            build_level(L, data, ss, a, report, level_seasons=every)
    res = step("site", lambda: site.build_all(data), report)
    if res:
        log.info("site: %s", res)
    rep = size_report(SITE)
    print_size(rep)
    bad = {k: v for k, v in report.items() if not v.get("ok")}
    print(f"\n{len(report) - len(bad)}/{len(report)} steps ok in {time.perf_counter() - t0:.0f}s")
    for k, v in bad.items():
        print(f"  FAILED {k}: {v.get('reason')}")
    return 1 if rep["over"] else 0


if __name__ == "__main__":
    sys.exit(main())
