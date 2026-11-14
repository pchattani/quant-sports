#!/usr/bin/env python
"""Build The Quant Iron (docs/iron): the design kit and every payload (oddsmarkets/powerlifting/pages.py).

    python scripts/build_iron.py

Steps (each isolated by step(): a failure is logged with its traceback; the build exits non-zero when the payloads
step fails, so a broken run never deploys). Every import that can fail happens inside a step.
Inputs: the OpenPowerlifting stores (data/powerlifting, written by scripts/pl_fetch.py). Payloads go to IRON_DATA
(default docs/iron/data).
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

SITE = ROOT / "docs" / "iron"
BUDGET_MB = 400
log = logging.getLogger("build_iron")


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
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--no-kit", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild even if the dump, code and day are unchanged")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[build_iron] %(levelname)s %(message)s")
    t0 = time.perf_counter()
    report: dict = {}
    data = Path(os.environ.get("IRON_DATA") or (SITE / "data"))
    data.mkdir(parents=True, exist_ok=True)
    if not a.no_kit:
        step("kit", lambda: __import__("design_kit").copy_kit(SITE), report)

    def payloads():
        import json
        from oddsmarkets.powerlifting import pages, store
        today = date.fromisoformat(a.today) if a.today else date.today()
        # the dump changes weekly and the build is hourly: skip when the last build saw the same dump, code and day
        prev = data / "build.json"
        if prev.exists() and not a.force:
            b = json.loads(prev.read_text(encoding="utf-8"))
            # rank_paths.json (the power rankings' monthly climb, 13 Nov 2026) is written by pages.build: a tree without it
            # rebuilds once, so the climb does not fall back to two snapshots until the next day
            if (b.get("model") == pages.MODEL_VERSION and b.get("today") == today.isoformat()
                    and b.get("stamp") == store.load_stamp().get("etag") and (data / "index.json").exists()
                    and (data / "rank_paths.json").exists()):
                log.info("payloads: unchanged dump, code and day since %s: skipped (--force rebuilds)", b.get("updated_at"))
                return {"skipped": True}
        return pages.build(data, today=today)
    counts = step("payloads", payloads, report)
    if counts:
        log.info("payloads: %s", counts)

    def power():
        # power rankings: data/power/<stream>.json and data/power.json (oddsmarkets/common/power.py), from the payloads
        # on disk (rankings.json, rank_paths.json, players/, scout/); also after a skipped payload step, so the first
        # build with this step writes them
        from oddsmarkets.powerlifting import power_build as PWB
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
