"""The Quant Campus in the CI / PC pipeline: prune rules, the not-launched workflow, the public-export allowlist."""
from __future__ import annotations

import sys
from pathlib import PurePosixPath, Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ci_site  # noqa: E402
import export_public  # noqa: E402
import gen_ci_workflows  # noqa: E402

CTX = {"leagues": {"cfb": {"current": 2026, "in_season": True}, "mbb": {"current": 2027, "in_season": True},
                   "wbb": {"current": 2027, "in_season": True}}}


def test_prune_keeps_current_and_previous_season_game_pages_only():
    pr = ci_site.SITES["campus"]["prune"]
    assert not pr(PurePosixPath("data/cfb/2026/games/401.json"), CTX)
    assert not pr(PurePosixPath("data/cfb/2025/games/401.json"), CTX)
    assert pr(PurePosixPath("data/cfb/2024/games/401.json"), CTX)
    assert not pr(PurePosixPath("data/mbb/2026/games/401.json"), CTX)
    assert pr(PurePosixPath("data/mbb/2025/games/401.json"), CTX)
    assert not pr(PurePosixPath("data/mbb/2024/season.json"), CTX)       # season payloads stay
    assert not pr(PurePosixPath("data/index.json"), CTX)


def test_campus_workflow_is_launched():
    c = gen_ci_workflows.SITES["campus"]
    yml = gen_ci_workflows.gen("campus", c)
    assert "workflow_dispatch" in yml and "schedule:" in yml and "repository_dispatch" in yml
    # a site not launched yet runs by hand only
    yml = gen_ci_workflows.gen("campus", {**c, "launched": False})
    assert "workflow_dispatch" in yml
    assert "schedule:" not in yml and "repository_dispatch" not in yml
    assert "scripts/build_campus.py --recent 2" in yml
    assert "ci_site.py guard --site campus" in yml


def test_launched_sites_keep_their_triggers():
    yml = gen_ci_workflows.gen("hardwood", gen_ci_workflows.SITES["hardwood"])
    assert "schedule:" in yml and "repository_dispatch" in yml


def test_export_allowlist():
    c = export_public.classify
    assert c("oddsmarkets/college/football/ratings.py") == "public"
    assert c("scripts/cc_fetch.py") == "public" and c("scripts/build_campus.py") == "public"
    assert c("docs/campus/assets/js/cc-core.js") == "public"
    assert c("tests/college/fixtures/cfb_summary_2025.json") == "private"     # raw third-party answers (D5)
    assert c("tests/college/fixtures/site/index.json") == "public"            # our own synthetic payloads
