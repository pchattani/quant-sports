"""Club crests (Sofascore team images) behind SOURCE_SOFASCORE_CRESTS_ENABLED (D6 revised, 30 Oct 2026)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_crest_path_follows_the_switch(monkeypatch):
    import scripts.build_site_all as b
    tid = next((int(p.stem) for p in b.CRESTS_DIR.glob("*.png") if p.stem.isdigit()), None)
    monkeypatch.setenv("SOURCE_SOFASCORE_CRESTS_ENABLED", "0")
    assert b.crest_path("premier-league", tid or 1) is None
    monkeypatch.setenv("SOURCE_SOFASCORE_CRESTS_ENABLED", "1")
    if tid is not None:                                     # the public checkout may have no crests
        assert b.crest_path("premier-league", tid) == f"assets/crests/{tid}.png"


def test_export_keeps_crests_private_when_switched_off(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    monkeypatch.setenv("SOURCE_SOFASCORE_CRESTS_ENABLED", "0")
    import export_public as E
    E = importlib.reload(E)
    assert E.classify("docs/site/assets/crests/11.png") == "private"
    monkeypatch.setenv("SOURCE_SOFASCORE_CRESTS_ENABLED", "1")
    E = importlib.reload(E)
    assert E.classify("docs/site/assets/crests/11.png") == "public"
    # raw excerpts of the unclear-terms sources never leave the engine
    assert E.classify("tests/baseball/fixtures/umpscorecards/games_sample.json") == "private"
    assert E.classify("tests/college/fixtures/barttorvik/2025_team_results_head.csv") == "private"
