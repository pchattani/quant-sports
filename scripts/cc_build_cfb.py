"""Build The Quant Campus college football payloads (oddsmarkets/college/football/build.py) from the command line.

    uv run --frozen python scripts/cc_build_cfb.py                      # current and previous season + level files
    uv run --frozen python scripts/cc_build_cfb.py --seasons all        # every season on disk
    uv run --frozen python scripts/cc_build_cfb.py --seasons 2024,2025 --no-market --sims 5000
    uv run --frozen python scripts/cc_build_cfb.py --level-only

Heavy numpy work: run with OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 on a shared machine.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

from oddsmarkets.college import canon, store
from oddsmarkets.college.football import build, data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seasons", default="", help="comma list, 'all', or empty for the current and previous season")
    ap.add_argument("--out", default=None, help="data root (default CAMPUS_DATA / docs/campus/data)")
    ap.add_argument("--sims", type=int, default=20000)
    ap.add_argument("--no-market", action="store_true")
    ap.add_argument("--quick", action="store_true", help="no game pages, no career files")
    ap.add_argument("--level-only", action="store_true")
    ap.add_argument("--no-level", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    out = a.out or str(store.paths()["data"])
    cur = canon.current_season("cfb")
    if a.seasons == "all":
        seasons = sorted(data.seasons_available(), reverse=True)
    elif a.seasons:
        seasons = [int(x) for x in a.seasons.split(",") if x.strip()]
    else:
        seasons = [cur, cur - 1]
    rc = 0
    if not a.level_only:
        for s in seasons:
            t = time.time()
            try:
                r = build.build(s, out, full=not a.quick, sims=a.sims, markets=not a.no_market)
            except Exception as exc:
                logging.getLogger("cc_build_cfb").exception("season %s failed", s)
                r, rc = {"ok": False, "season": s, "reason": str(exc)}, 1
            print(json.dumps(r), f"{time.time() - t:.0f}s", flush=True)
    if not a.no_level:
        r = build.build_level(out, None, None, markets=not a.no_market, careers=not a.quick, sims=a.sims)
        print(json.dumps(r), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
