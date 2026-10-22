"""Copy The Quant design kit (docs/_design) into a site's assets, the way base.css is copied today.

    from design_kit import copy_kit
    copy_kit(DOCS / "rink")          # -> docs/rink/assets/qk/{tokens.css, quant.css, quant.js, quant-charts.js, plotly-ec.js}
                                     #    and docs/rink/assets/qk/metrics/hockey.json

Every site build calls this once, so all sites ship the same kit version. The style guide
(docs/_design/index.html, guide.js) is not copied.

The site's metrics spec (docs/_design/metrics/<sport>.json, the machine-readable form of docs/METRICS_SPEC.md:
headline metrics, peer groups, minimums, year-to-year reliability) is copied to assets/qk/metrics/<sport>.json so
the front end can read it in the browser (fetch("assets/qk/metrics/hockey.json")). Only the site's own sport is
copied; the home page gets none.
"""
from __future__ import annotations

import shutil
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[1] / "docs" / "_design"
METRICS = DESIGN / "metrics"
# plotly-ec.js is optional on a page (window.Plotly on ECharts for views still written against Plotly) but is
# copied everywhere so any site can load it without its own copy.
KIT_FILES = ["tokens.css", "quant.css", "quant.js", "quant-charts.js", "plotly-ec.js"]
# site folder (docs/<folder>) -> the sport of its metrics file (docs/_design/metrics/<sport>.json)
SITE_SPORT = {
    "site": "football",
    "paddock": "f1",
    "hardwood": "basketball",
    "ace": "tennis",
    "bullpen": "baseball",
    "gridiron": "nfl",
    "rink": "hockey",
    "campus": "college",
}


def metrics_files(site_dir: Path) -> list[Path]:
    """The metrics spec file(s) a site ships: its own sport's, or none (home, unknown folders)."""
    sport = SITE_SPORT.get(Path(site_dir).name)
    if sport is None:
        return []
    src = METRICS / f"{sport}.json"
    return [src] if src.exists() else []


def copy_kit(site_dir: Path, sub: str = "assets/qk") -> Path:
    dst = Path(site_dir) / sub
    dst.mkdir(parents=True, exist_ok=True)
    for f in KIT_FILES:
        shutil.copyfile(DESIGN / f, dst / f)
    mfiles = metrics_files(site_dir)
    if mfiles:
        (dst / "metrics").mkdir(exist_ok=True)
        for src in mfiles:
            shutil.copyfile(src, dst / "metrics" / src.name)
    return dst


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        print(copy_kit(Path(d)))
