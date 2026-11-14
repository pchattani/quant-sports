#!/usr/bin/env python
"""Build The Quant Green (docs/green): the design kit and every payload (oddsmarkets/golf/pages.py).

    python scripts/build_green.py                 # final event pages already on file are kept
    python scripts/build_green.py --full          # re-simulate every event (after a model change)

Steps (each isolated by step(): a failure is logged with its traceback; the build exits non-zero when the payloads
step fails, so a broken run never deploys). Every import that can fail happens inside a step.
Inputs: the season stores (data/golf, written by scripts/golf_fetch.py). Payloads go to GREEN_DATA (default
docs/green/data).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SITE = ROOT / "docs" / "green"
BUDGET_MB = 600
log = logging.getLogger("build_green")


def step(name: str, fn, report: dict):
    t0 = time.perf_counter()
    try:
        res = fn()
        report[name] = {"ok": True, "s": round(time.perf_counter() - t0, 1)}
        log.info("%s: done in %.1fs", name, time.perf_counter() - t0)
        return res
    except Exception as exc:          # noqa: BLE001 - a step must never stop the build
        report[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "reason": f"{type(exc).__name__}: {exc}"[:300]}
        log.error("%s failed:\n%s", name, traceback.format_exc())
        return None


def size_mb(site: Path) -> float:
    return round(sum(p.stat().st_size for p in site.rglob("*") if p.is_file()) / 1e6, 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--no-kit", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[build_green] %(levelname)s %(message)s")
    t0 = time.perf_counter()
    report: dict = {}
    data = Path(os.environ.get("GREEN_DATA") or (SITE / "data"))
    data.mkdir(parents=True, exist_ok=True)
    if not a.no_kit:
        step("kit", lambda: __import__("design_kit").copy_kit(SITE), report)

    def payloads():
        from oddsmarkets.golf import pages
        return pages.build(data, today=date.fromisoformat(a.today) if a.today else None, full=a.full)
    counts = step("payloads", payloads, report)
    if counts:
        log.info("payloads: %s", counts)

    def follow():
        # My Teams: one card per golfer (data/follow/golfm|golfw/<pid>.json) from the payloads just written
        from oddsmarkets.golf import follow_build as FLB
        return FLB.build(data)
    if counts:
        fl = step("follow", follow, report)
        if fl:
            log.info("follow cards: %s", fl)

    def power():
        # power rankings: data/power/men.json, women.json and data/power.json (oddsmarkets/common/power.py), from the
        # payloads just written
        from oddsmarkets.golf import power_build as PWB
        return PWB.build(data)
    if counts:
        pw = step("power rankings", power, report)
        if pw:
            log.info("power rankings: %d league files, %.0f KB", pw["n"], pw["bytes"] / 1024)
    mb = size_mb(SITE)
    print(f"size {mb} MB")
    bad = {k: v for k, v in report.items() if not v.get("ok")}
    print(f"\n{len(report) - len(bad)}/{len(report)} steps ok in {time.perf_counter() - t0:.0f}s")
    for k, v in bad.items():
        print(f"  FAILED {k}: {v.get('reason')}")
    return 1 if ("payloads" in bad or mb > BUDGET_MB) else 0


if __name__ == "__main__":
    sys.exit(main())
