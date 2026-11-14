#!/usr/bin/env python
"""Build The Quant Scrum (docs/scrum): the design kit, every scope's payloads, the follow cards and the site-wide files.

    python scripts/build_scrum.py                    # men's and women's tests, 20,000 simulations
    python scripts/build_scrum.py --scopes men --sims 2000
    python scripts/build_scrum.py --no-match-pages   # skip the per-match pages (quicker local iterations)

Steps (each isolated by step(): one failure is logged with its traceback and never stops the rest; a failed scope
writes {"ok": false, "reason"} for its overview so the page says so instead of breaking). Every import that can fail
happens inside a step:
  1. copy the kit (scripts/design_kit.copy_kit) into docs/scrum/assets/qk
  2. per scope: oddsmarkets.rugby.pages.build_scope (overview, fixtures, years, ratings, rankings, comps, teams,
     players, matches, model, lab, records), then the follow cards (oddsmarkets.rugby.follow_build)
  3. site-wide: index.json, search.json, glossary.json (oddsmarkets.rugby.site)
  4. the power rankings: power.json and power/<S>.json (oddsmarkets.rugby.power_build)
  5. a size report; exits non-zero over the 400 MB budget

Inputs: the season stores (data/rugby/stores, written by scripts/scrum_fetch.py) and the fitted parameters
(oddsmarkets/rugby/fitted, written by scripts/scrum_fit.py). Payloads go to SCRUM_DATA (default docs/scrum/data).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SITE = ROOT / "docs" / "scrum"
BUDGET_MB = 400
log = logging.getLogger("build_scrum")


def step(name: str, fn, report: dict):
    t0 = time.perf_counter()
    try:
        res = fn()
        bad = isinstance(res, dict) and res.get("ok") is False
        report[name] = {"ok": not bad, "s": round(time.perf_counter() - t0, 1)}
        if bad:
            report[name]["reason"] = str(res.get("reason"))[:300]
            log.warning("%s: not ok (%s)", name, report[name]["reason"])
        else:
            log.info("%s: done in %.1fs", name, time.perf_counter() - t0)
        return res
    except Exception as exc:          # noqa: BLE001 - a step must never stop the build
        report[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "reason": f"{type(exc).__name__}: {exc}"[:300]}
        log.error("%s failed:\n%s", name, traceback.format_exc())
        return None


def size_report(site: Path) -> dict:
    by = {}
    total = 0
    for p in site.rglob("*"):
        if p.is_file():
            n = p.stat().st_size
            total += n
            rel = p.relative_to(site).parts
            key = "/".join(rel[:3]) if rel[0] == "data" else rel[0]
            by[key] = by.get(key, 0) + n
    return {"total_mb": round(total / 1e6, 1), "by": dict(sorted(by.items(), key=lambda kv: -kv[1])[:12]),
            "over": total / 1e6 > BUDGET_MB}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scopes", default="men,women")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--no-kit", action="store_true")
    ap.add_argument("--no-match-pages", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[build_scrum] %(levelname)s %(message)s")
    t0 = time.perf_counter()
    report: dict = {}
    data = Path(os.environ.get("SCRUM_DATA") or (SITE / "data"))
    data.mkdir(parents=True, exist_ok=True)
    if not a.no_kit:
        step("kit", lambda: __import__("design_kit").copy_kit(SITE), report)
    scopes, search = {}, []
    for scope in [s.strip() for s in a.scopes.split(",") if s.strip()]:
        def run(scope=scope):
            from oddsmarkets.rugby import pages
            return pages.build_scope(scope, data, sims=a.sims, game_pages=not a.no_match_pages)
        res = step(f"scope {scope}", run, report)
        if not res or not res.get("ok"):
            from oddsmarkets.rugby import config
            scopes[scope] = {"ok": False, "label": config.SCOPES[scope]["label"], "short": config.SCOPES[scope]["short"],
                             "reason": (res or {}).get("reason") or (report.get(f"scope {scope}") or {}).get("reason") or "not built"}
            continue
        scopes[scope] = res["info"]
        search += res["search"]
        log.info("%s sizes: %s", scope, {k: f"{v / 1e6:.1f} MB" for k, v in res["sizes"].items()})

        def cards(res=res):
            from oddsmarkets.rugby import follow_build
            return follow_build.build(res, data)
        fl = step(f"follow cards {scope}", cards, report)
        if fl:
            log.info("follow cards %s: %d, %.0f KB, largest %d bytes", scope, fl["n"], fl["bytes"] / 1024, fl["max"])

    def site_files():
        from oddsmarkets.rugby import site
        site.build_index(data, scopes)
        site.build_search(data, search)
        site.build_glossary(data)
        return {"ok": True}
    step("site", site_files, report)

    # power rankings: data/power/<S>.json and data/power.json (oddsmarkets/common/power.py), from the payloads just
    # written (index.json among them), so after the site files
    def power():
        from oddsmarkets.rugby import power_build
        return power_build.build(data)
    pw = step("power rankings", power, report)
    if pw:
        log.info("power rankings: %d files, %.0f KB, largest %d bytes", pw["n"], pw["bytes"] / 1024, pw["max"])
    rep = size_report(SITE)
    print(f"size {rep['total_mb']} MB: {rep['by']}")
    bad = {k: v for k, v in report.items() if not v.get("ok")}
    print(f"\n{len(report) - len(bad)}/{len(report)} steps ok in {time.perf_counter() - t0:.0f}s")
    for k, v in bad.items():
        print(f"  FAILED {k}: {v.get('reason')}")
    return 1 if rep["over"] else 0


if __name__ == "__main__":
    sys.exit(main())
