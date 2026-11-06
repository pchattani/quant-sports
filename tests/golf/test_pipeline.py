"""The Quant Green in the CI / PC pipeline: workflow, export allowlist, kit entry."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_site  # noqa: E402
import export_public  # noqa: E402
import gen_ci_workflows  # noqa: E402


def test_green_workflow_is_launched():
    c = gen_ci_workflows.SITES["green"]
    yml = gen_ci_workflows.gen("green", c)
    assert "workflow_dispatch" in yml and "schedule:" in yml and "repository_dispatch" in yml
    assert "types: [hourly]" in yml
    assert "scripts/golf_fetch.py --max-age-h 6 --budget 300" in yml
    assert "scripts/build_green.py" in yml
    assert "ci_site.py guard --site green" in yml
    assert "secrets.GREEN_DEPLOY_KEY" in yml
    assert "green-raw-v1-" in yml
    assert ci_site.SITES["green"]["repo"] == "the-quant-green"
    assert ci_site.SITES["green"]["docs"] == "green"


def test_export_allowlist():
    c = export_public.classify
    assert c("oddsmarkets/golf/pages.py") == "public"
    assert c("oddsmarkets/golf/models/ratings.py") == "public"
    assert c("scripts/golf_fetch.py") == "public" and c("scripts/build_green.py") == "public"
    assert c("docs/green/index.html") == "public"
    assert c("docs/green/assets/app/core.js") == "public"
    assert c("tests/golf/test_espn.py") == "public"


def test_kit_golf_entry_is_launched():
    js = (ROOT / "docs" / "_design" / "quant.js").read_text(encoding="utf-8")
    line = [ln for ln in js.splitlines() if "key: 'golf'" in ln][0]
    assert "site: 'The Quant Green'" in line and "repo: 'the-quant-green'" in line
    assert "pending: true" not in line
    assert "golf: { fixtures: 'Events'" in js and "  golf: '<svg" in js
    css = (ROOT / "docs" / "_design" / "tokens.css").read_text(encoding="utf-8")
    assert css.count("--a-golf:") == 1
    assert ':root[data-sport="golf"]       { --accent: var(--a-golf); }' in css
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_home", ROOT / "scripts" / "build_home.py")
    bh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bh)
    assert "golf" in [s[0] for s in bh.PENDING] and "golf" in bh.LAUNCHED and "golf" in bh.BUILDERS


def test_front_end_has_no_optional_chaining():
    app = ROOT / "docs" / "green" / "assets" / "app"
    for p in sorted(app.glob("*.js")):
        src = p.read_text(encoding="utf-8")
        assert "?." not in src.replace("'?.'", "") and "??" not in src, p.name
