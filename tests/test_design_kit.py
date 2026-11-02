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


def test_every_spec_metric_has_a_short_board_head(tmp_path):
    """Round 10 (the Board's "Bloomberg view"): every metric in every spec group carries a `short` one-line head of at
    most 12 characters, and the labels file appends it and the short unit to each row ([7], [8]) without moving
    [0]..[6]."""
    for sport in sorted(set(design_kit.SITE_SPORT.values())):
        spec = json.loads((design_kit.METRICS / f"{sport}.json").read_text(encoding="utf-8"))
        for g in spec["groups"]:
            for m in g.get("metrics") or []:
                assert m.get("short"), (sport, g["id"], m["id"])
                assert len(m["short"]) <= 12, (sport, m["id"], m["short"])
    dst = design_kit.copy_kit(tmp_path / "site")
    lab = json.loads((dst / "metrics" / "football.labels.json").read_text(encoding="utf-8"))
    row = lab["m"]["player"]["padj_tkl_int_90"]
    assert row[0] == "Tackles + interceptions (possession-adjusted)" and row[1] == "per 90"
    assert row[7] == "PAdj Tkl+Int" and row[8] == "/90"
    assert lab["m"]["player"]["aerial_pct"][8] == "%"
    assert design_kit.short_unit({"unit": "goals per 90"}) == "/90"
    assert design_kit.short_unit({"unit": "per 90", "unit_short": "per 90 min"}) == "per 90 min"
    assert design_kit.short_unit({"unit": "something new"}) == ""


def test_board_kit_round_10_api():
    """The Board keeps its round-8 API and adds the summary column, the capped first set, the site heads map and the
    phone card list; the spec catalogue reads the short head."""
    src = (design_kit.DESIGN / "scout.js").read_text(encoding="utf-8")
    for bit in ("QK.board.pick = ", "S.summary", "S.abbr", "S.family", "qk-bdc-list", "BD_PHONE = '(max-width: 600px)'",
                "BD_HOT = 90, BD_COLD = 10", "function drawGrid()", "function drawBoard()"):
        assert bit in src, bit
    q = (design_kit.DESIGN / "quant.js").read_text(encoding="utf-8")
    assert "SpecCat.prototype.short = " in q and "short: r[7] || r[0], su: r[8] || ''" in q
    css = (design_kit.DESIGN / "quant.css").read_text(encoding="utf-8")
    assert ".qk-bd-v10 {" in css and ".qk-room {" in css


def test_follow_kit_round_12_api_and_copies():
    """Round 12 (My Teams): quant.js carries QK.follow (localStorage 'qk-follow-v1', at most 30 follows, through the
    kit's try/catch store), the follow button, picker, card, chip and section; the card registry names the sites
    that publish cards; quant.css styles them; every site and Home ship the same copy."""
    q = (design_kit.DESIGN / "quant.js").read_text(encoding="utf-8")
    for bit in ("var FOLLOW_KEY = 'qk-follow-v1', FOLLOW_MAX = 30;", "QK.follow = {", "QK.followButton = function",
                "QK.followPicker = function", "QK.followCard = function", "QK.followChip = function", "QK.followSection = function",
                "QK.toast = function", "QK.fetchCard = function", "QK.FOLLOW_CARDS = { bullpen: ['mlb', 'aaa'], site: ['club'],",
                "root.addEventListener('storage'", "importHash: function", "shareUrl: function", "fromHref: function",
                "cardUrl: function", "gameOf: function", "forSite: function", "onChange: function"):
        assert bit in q, bit
    # every read and write of the list goes through the kit's store() (try/catch: blocked storage never breaks a page)
    blk = q[q.index("var FOLLOW_KEY"):q.index("root.QK = QK;")]
    assert "localStorage" not in blk and "store(FOLLOW_KEY" in blk
    assert "?." not in blk and "??" not in blk
    # one route pattern per site, so a picker row or a share link maps to a key on every site
    for site in design_kit.SITE_SPORT:
        assert f"  {site}: function (r)" in blk, site
    css = (design_kit.DESIGN / "quant.css").read_text(encoding="utf-8")
    for cls in (".qk-fbtn {", ".qk-fbtn.on", ".qk-fp-dlg {", ".qk-fp-row {", ".qk-fc {", ".qk-fc-top {", ".qk-fchip {",
                ".qk-fl-cards {", ".qk-fl-week-row {", ".qk-fl-empty {", ".qk-fl-prompt {", ".qk-fl-import {", ".qk-toast {", ".qk-pw-tw {"):
        assert cls in css, cls
    s = (design_kit.DESIGN / "scout.js").read_text(encoding="utf-8")
    assert "if (r.follow && QK.followButton)" in s
    for folder in list(design_kit.SITE_SPORT) + ["home"]:
        for f in ("quant.js", "quant.css", "scout.js"):
            assert (ROOT / "docs" / folder / "assets" / "qk" / f).read_bytes() == (design_kit.DESIGN / f).read_bytes(), (folder, f)


def test_follow_card_registry_matches_the_published_scopes():
    """A site listed in QK.FOLLOW_CARDS must write cards (its builder calls oddsmarkets/common/follow.py), so Home
    never fetches a card that does not exist: every site's build calls its follow_build for exactly the scopes listed
    (1 Nov 2026: all eight sites publish cards)."""
    import re
    q = (design_kit.DESIGN / "quant.js").read_text(encoding="utf-8")
    reg = re.search(r"QK\.FOLLOW_CARDS = \{(.*?)\};", q, re.S).group(1)
    sites = dict((m.group(1), re.findall(r"'([a-z]+)'", m.group(2))) for m in re.finditer(r"(\w+): \[([^\]]*)\]", reg))
    assert sites == {"bullpen": ["mlb", "aaa"], "site": ["club"], "rink": ["team"], "gridiron": ["team"], "hardwood": ["nba", "wnba"],
                     "campus": ["cfb", "mbb", "wbb", "mch", "wch"], "ace": ["atp", "wta"], "paddock": ["driver", "team"],
                     "scrum": ["men", "women"]}
    assert set(sites) == set(design_kit.SITE_SPORT)
    src = lambda f: (ROOT / "scripts" / f).read_text(encoding="utf-8")
    pkg = lambda f: (ROOT / "oddsmarkets" / f).read_text(encoding="utf-8")
    b = src("build_bullpen.py")
    assert 'for lvl in ("mlb", "aaa"):' in b and "FLB.build(data, lvl" in b
    assert "football_follow.build(DATA_DIR)" in src("build_site_all.py")
    assert 'SITE, SPORT, SCOPE = "site", "football", "club"' in pkg("football/analytics/follow_build.py")
    for f, mod in (("build_rink.py", "nhl"), ("build_gridiron.py", "nfl")):
        assert f"from oddsmarkets.{mod}.analytics import follow_build as FLB" in src(f) and 'data / "follow" / "team"' in src(f)
    h = src("build_hardwood.py")
    assert 'for lg in ("nba", "wnba"):' in h and "FLB.build(data, lg" in h
    c = src("build_campus.py")
    assert 'LEVELS = ("cfb", "mbb", "wbb", "mch", "wch")' in c and "FLB.build(data, L)" in c
    a = src("build_ace.py")
    assert "FLB.build(data, t," in a and 'TOURS = ("atp", "wta")' in pkg("tennis/analytics/__init__.py")
    assert '-> {"driver": summary, "team": summary}' in pkg("f1/analytics/follow_build.py") and "FLB.build(data)" in src("build_paddock.py")
    sc = src("build_scrum.py")
    assert 'ap.add_argument("--scopes", default="men,women")' in sc and "follow_build.build(res, data)" in sc
