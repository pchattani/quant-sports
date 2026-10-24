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
    assert len((dst / "metrics" / "football.labels.json").read_bytes()) < 40_000


def test_every_sport_registers_its_own_models():
    for sport in set(design_kit.SITE_SPORT.values()):
        spec = json.loads((design_kit.METRICS / f"{sport}.json").read_text(encoding="utf-8"))
        reg = spec.get("our_models") or {}
        assert reg.get("models") and reg.get("metrics"), sport
        assert set(reg["metrics"].values()) <= set(reg["models"]), sport
        ids = {m["id"] for g in spec["groups"] for m in g["metrics"]}
        assert ids & set(reg["metrics"]), sport          # at least one spec metric is ours
