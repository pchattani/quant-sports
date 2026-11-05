"""The Quant Iron in the CI / PC pipeline: workflow, export allowlist, kit entry."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_site  # noqa: E402
import export_public  # noqa: E402
import gen_ci_workflows  # noqa: E402


def test_iron_workflow_is_launched():
    c = gen_ci_workflows.SITES["iron"]
    yml = gen_ci_workflows.gen("iron", c)
    assert "workflow_dispatch" in yml and "schedule:" in yml and "repository_dispatch" in yml
    assert "types: [hourly]" in yml
    assert "scripts/pl_fetch.py" in yml
    assert "scripts/build_iron.py" in yml
    assert "ci_site.py guard --site iron" in yml
    assert "secrets.IRON_DEPLOY_KEY" in yml
    assert ci_site.SITES["iron"]["repo"] == "the-quant-iron"
    assert ci_site.SITES["iron"]["docs"] == "iron"


def test_export_allowlist():
    c = export_public.classify
    assert c("oddsmarkets/powerlifting/pages.py") == "public"
    assert c("oddsmarkets/powerlifting/models/ratings.py") == "public"
    assert c("scripts/pl_fetch.py") == "public" and c("scripts/build_iron.py") == "public"
    assert c("docs/iron/index.html") == "public"
    assert c("docs/iron/assets/app/core.js") == "public"
    assert c("tests/powerlifting/test_dots.py") == "public"


def test_kit_powerlifting_entry_is_pending_until_the_hub_launch():
    js = (ROOT / "docs" / "_design" / "quant.js").read_text(encoding="utf-8")
    line = [ln for ln in js.splitlines() if "key: 'powerlifting'" in ln][0]
    assert "site: 'The Quant Iron'" in line and "repo: 'the-quant-iron'" in line and "pending: true" in line
    assert "powerlifting: { fixtures: 'Meets'" in js and "  powerlifting: '<svg" in js
    css = (ROOT / "docs" / "_design" / "tokens.css").read_text(encoding="utf-8")
    assert css.count("--a-powerlifting:") == 1
    assert ':root[data-sport="powerlifting"] { --accent: var(--a-powerlifting); }' in css
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_home", ROOT / "scripts" / "build_home.py")
    bh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bh)
    assert "powerlifting" in [s[0] for s in bh.PENDING] and "powerlifting" not in bh.LAUNCHED
    assert "powerlifting" in bh.BUILDERS


def test_front_end_has_no_optional_chaining():
    app = ROOT / "docs" / "iron" / "assets" / "app"
    for p in sorted(app.glob("*.js")):
        src = p.read_text(encoding="utf-8")
        assert "?." not in src.replace("'?.'", "") and "??" not in src, p.name
