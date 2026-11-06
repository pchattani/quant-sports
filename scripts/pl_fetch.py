#!/usr/bin/env python
"""Fetch the OpenPowerlifting weekly bulk zip into data/powerlifting.

    python scripts/pl_fetch.py              # download if the ETag changed, then rebuild parquet
    python scripts/pl_fetch.py --force      # re-parse even if the zip is unchanged

The dump is public domain (OpenPowerlifting). We do not scrape openpowerlifting.org.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oddsmarkets.powerlifting import store  # noqa: E402
from oddsmarkets.powerlifting.sources import opl  # noqa: E402

logger = logging.getLogger("pl_fetch")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[pl_fetch] %(levelname)s %(message)s")
    stamp = store.load_stamp()
    zip_path = store.root() / "openpowerlifting-latest.zip"
    info = opl.download(zip_path, etag=None if a.force else stamp.get("etag"))
    # a store from an older parse (schema 1 had no attempts) is re-parsed from the cached zip, without a download
    if not info["changed"] and store.entries_path().exists() and not a.force and stamp.get("schema", 1) >= opl.SCHEMA:
        logger.info("zip unchanged (%s bytes)", info["bytes"])
        return 0
    counts = opl.ingest(zip_path)
    stamp = {
        "etag": info.get("etag"),
        "url": info.get("url"),
        "bytes": info.get("bytes"),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **counts,
    }
    store.save_stamp(stamp)
    logger.info("ingested %s entries, %s meets (%s .. %s)", counts["entries"], counts["meets"],
                counts["from"], counts["to"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
