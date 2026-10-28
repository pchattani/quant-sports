"""scripts/design_kit.py: the kit and the site's metrics spec land in assets/qk/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import design_kit  # noqa: E402


def test_every_sport_site_has_a_metrics_file():
    for folder, sport in design_kit.SITE_SPORT.items():
        assert (design_kit.METRICS / f"{sport}.json").exists(), (folder, sport)
        assert (ROOT / "docs" / folder).is_dir(), folder


def test_copy_kit_copies_the_sites_metrics_file(tmp_path):
    site = tmp_path / "rink"
    dst = design_kit.copy_kit(site)
    assert dst == site / "assets" / "qk"
    for f in design_kit.KIT_FILES:
        assert (dst / f).read_bytes() == (design_kit.DESIGN / f).read_bytes()
    out = dst / "metrics" / "hockey.json"
    assert out.read_bytes() == (design_kit.METRICS / "hockey.json").read_bytes()
    json.loads(out.read_text(encoding="utf-8"))
    assert sorted(p.name for p in (dst / "metrics").iterdir()) == ["hockey.json", "hockey.labels.json"]   # only its own sport


def test_home_and_unknown_folders_get_no_metrics(tmp_path):
    for name in ("home", "somewhere"):
        dst = design_kit.copy_kit(tmp_path / name)
        assert not (dst / "metrics").exists()
        assert (dst / "quant.js").exists()


def test_committed_site_copies_match_the_source():
    """design_kit.py was run after the last metrics edit: every site's copy equals docs/_design/metrics."""
    for folder, sport in design_kit.SITE_SPORT.items():
        site_copy = ROOT / "docs" / folder / "assets" / "qk" / "metrics" / f"{sport}.json"
        assert site_copy.read_bytes() == (design_kit.METRICS / f"{sport}.json").read_bytes(), folder


def test_labels_file_carries_display_names_headlines_and_our_models(tmp_path):
    dst = design_kit.copy_kit(tmp_path / "site")
    lab = json.loads((dst / "metrics" / "football.labels.json").read_text(encoding="utf-8"))
    spec = json.loads((design_kit.METRICS / "football.json").read_text(encoding="utf-8"))
    assert lab["sport"] == "football"
    gar = lab["m"]["player"]["gar90"]
    assert gar[0] == "Value added (GAR/90)" and gar[3] == "h" and gar[6]
    assert lab["ours"]["metrics"]["gar90"] in lab["ours"]["models"]
    cb = next(g for g in lab["groups"] if g["id"] == "cb")
    want = [m["id"] for m in sorted((m for m in next(g for g in spec["groups"] if g["id"] == "cb")["metrics"] if m["set"] == "headline"), key=lambda m: m["order"])]
    assert cb["headline"] == want and cb["headline"][0] == "gar90"
    assert cb["field"] == "role" and cb["codes"] == ["CB"] and cb["min"]["value"] == 450
    gk = next(g for g in lab["groups"] if g["id"] == "gk")
    assert gk["min"] == {"field": "minutes", "value": 900, "unit": "minutes"}
    assert len((dst / "metrics" / "football.labels.json").read_bytes()) < 40_000


def test_labels_carry_the_peer_groups_for_the_labs(tmp_path):
    """The Labs' "Compare within: Position" reads each group's field, codes and minimum from the labels file:
    baseball's starters and relievers are separate groups with separate floors."""
    dst = design_kit.copy_kit(tmp_path / "bullpen")
    lab = json.loads((dst / "metrics" / "baseball.labels.json").read_text(encoding="utf-8"))
    g = {x["id"]: x for x in lab["groups"]}
    assert g["sp"]["codes"] == ["SP"] and g["sp"]["min"]["value"] == 300
    assert g["rp"]["codes"] == ["RP"] and g["rp"]["min"]["value"] == 120
    assert "codes" not in g["teams"]


def test_every_sport_registers_its_own_models():
    for sport in set(design_kit.SITE_SPORT.values()):
        spec = json.loads((design_kit.METRICS / f"{sport}.json").read_text(encoding="utf-8"))
        reg = spec.get("our_models") or {}
        assert reg.get("models") and reg.get("metrics"), sport
        assert set(reg["metrics"].values()) <= set(reg["models"]), sport
        ids = {m["id"] for g in spec["groups"] for m in g["metrics"]}
        assert ids & set(reg["metrics"]), sport          # at least one spec metric is ours


def test_scout_kit_ships_and_switches_the_nav():
    """Round 8: scout.js is a kit file (every site gets it) and quant.js carries the one-line nav switch."""
    assert "scout.js" in design_kit.KIT_FILES
    src = (design_kit.DESIGN / "scout.js").read_text(encoding="utf-8")
    for api in ("QK.board = ", "QK.heatGrid = ", "QK.powerBars = ", "QK.leaderCard = ", "QKC.strip = ", "QK.drawer = ",
                "QK.profile = ", "QK.tray = ", "QK.trayCompare = ", "QK.strengths = ", "QK.csv = "):
        assert api in src, api
    assert "?." not in src.replace("'?.'", "") and "??" not in src
    q = (design_kit.DESIGN / "quant.js").read_text(encoding="utf-8")
    assert "QK.SCOUT = { key: 'scout', label: 'Scouting Room', route: '#/scout' }" in q
    assert "if (scout && s.key === 'lab') return null;" in q
    for folder in list(design_kit.SITE_SPORT) + ["home"]:
        copy = ROOT / "docs" / folder / "assets" / "qk" / "scout.js"
        assert copy.read_bytes() == (design_kit.DESIGN / "scout.js").read_bytes(), folder
