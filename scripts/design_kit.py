"""Copy The Quant design kit (docs/_design) into a site's assets, the way base.css is copied today.

    from design_kit import copy_kit
    copy_kit(DOCS / "rink")          # -> docs/rink/assets/qk/{tokens.css, quant.css, quant.js, quant-charts.js, plotly-ec.js}

Every site build calls this once, so all sites ship the same kit version. The style guide
(docs/_design/index.html, guide.js) is not copied.
"""
from __future__ import annotations

import shutil
from pathlib import Path

DESIGN = Path(__file__).resolve().parents[1] / "docs" / "_design"
# plotly-ec.js is optional on a page (window.Plotly on ECharts for views still written against Plotly) but is
# copied everywhere so any site can load it without its own copy.
KIT_FILES = ["tokens.css", "quant.css", "quant.js", "quant-charts.js", "plotly-ec.js"]


def copy_kit(site_dir: Path, sub: str = "assets/qk") -> Path:
    dst = Path(site_dir) / sub
    dst.mkdir(parents=True, exist_ok=True)
    for f in KIT_FILES:
        shutil.copyfile(DESIGN / f, dst / f)
    return dst


if __name__ == "__main__":
    import sys
    for d in sys.argv[1:]:
        print(copy_kit(Path(d)))
