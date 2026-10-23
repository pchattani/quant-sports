"""The Quant Campus build orchestrator (scripts/build_campus.py), the kit's pending gate and the home page gate,
and the front end's static rules. No network, no stores."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bc = _load("build_campus_t", ROOT / "scripts" / "build_campus.py")
bh = _load("build_home_t", ROOT / "scripts" / "build_home.py")
fixture = _load("cc_site_fixture2", ROOT / "tests" / "college" / "fixtures" / "site" / "fixture_data.py")


# ── build_campus ──────────────────────────────────────────────────────────
def test_size_report_groups_and_budget(tmp_path):
    site = tmp_path / "campus"
    (site / "data" / "cfb" / "2026" / "games").mkdir(parents=True)
    (site / "data" / "cfb" / "2026" / "games" / "1.json").write_bytes(b"x" * 600_000)
    (site / "data" / "cfb" / "calibration.json").write_bytes(b"x" * 100_000)
    (site / "data" / "index.json").write_bytes(b"x" * 50_000)
    (site / "assets").mkdir()
    (site / "assets" / "a.css").write_bytes(b"x" * 10_000)
    rep = bc.size_report(site, budget_mb=0.5)
    assert rep["over"] is True and rep["total_mb"] == 0.8
    f = rep["folders"]
    assert f["data/cfb/2026"] == 0.6 and f["data/cfb (level files)"] == 0.1 and f["data (site-wide)"] == 0.05 and f["assets"] == 0.01
    assert bc.size_report(site)["over"] is False


def test_fill_missing_never_overwrites(tmp_path):
    (tmp_path / "season.json").write_text('{"ok": true}', encoding="utf-8")
    wrote = bc.fill_missing(tmp_path, ["season", "schedule"], "boom")
    assert wrote == ["schedule"]
    assert json.loads((tmp_path / "season.json").read_text()) == {"ok": True}
    assert json.loads((tmp_path / "schedule.json").read_text()) == {"ok": False, "reason": "boom"}


def test_call_passes_only_accepted_kwargs():
    def f(a, *, sims=1):
        return a, sims
    assert bc.call(f, 1, sims=5, per_season=False, markets=True) == (1, 5)
    def g(a, **kw):
        return kw
    assert bc.call(g, 1, sims=5, per_season=False) == {"sims": 5, "per_season": False}


def test_step_isolates_failures():
    rep = {}
    assert bc.step("x", lambda: 1 / 0, rep) is None
    assert rep["x"]["ok"] is False and "ZeroDivisionError" in rep["x"]["reason"]
    bc.step("y", lambda: {"ok": False, "reason": "no store"}, rep)
    assert rep["y"]["ok"] is False and rep["y"]["reason"] == "no store"
    bc.step("z", lambda: {"ok": True}, rep)
    assert rep["z"]["ok"] is True


def test_build_level_failures_write_not_ok_payloads(tmp_path, monkeypatch):
    calls = []
    fake = types.SimpleNamespace(
        build_level=lambda level, out_dir, seasons, current, *, sims=1, per_season=True: calls.append(("level", level, per_season)),
        build=lambda level, season, out_dir, stores, *, full, sims, markets: (_ for _ in ()).throw(RuntimeError("model blew up")) if season == 2026 else calls.append(("season", season, full)))
    monkeypatch.setitem(sys.modules, "fake_hoops_build", fake)
    monkeypatch.setitem(bc.MODULE, "mbb", "fake_hoops_build")
    a = types.SimpleNamespace(sims=10, no_market=True, game_page_seasons=1)
    rep = {}
    bc.build_level("mbb", tmp_path, [2027, 2026, 2025], a, rep)
    assert ("level", "mbb", False) in calls                      # per-season builds are ours, not the level builder's
    assert ("season", 2027, True) in calls and ("season", 2025, False) in calls   # game pages only for the newest
    assert rep["mbb:2026"]["ok"] is False
    s = json.loads((tmp_path / "mbb" / "2026" / "season.json").read_text())
    assert s["ok"] is False and "model blew up" in s["reason"]
    assert json.loads((tmp_path / "mbb" / "calibration.json").read_text())["ok"] is False


def test_build_level_import_error(tmp_path, monkeypatch):
    monkeypatch.setitem(bc.MODULE, "cfb", "no_such_module_cc")
    rep = {}
    bc.build_level("cfb", tmp_path, [2026], types.SimpleNamespace(sims=1, no_market=True, game_page_seasons=1), rep)
    assert rep["cfb:import"]["ok"] is False
    assert json.loads((tmp_path / "cfb" / "2026" / "cfp.json").read_text())["ok"] is False


# ── kit: college entry and the pending gate ───────────────────────────────
KIT = ROOT / "docs" / "_design"


def test_kit_college_entry_is_launched_and_the_gate_remains():
    js = (KIT / "quant.js").read_text(encoding="utf-8")
    line = [ln for ln in js.splitlines() if "key: 'college'" in ln][0]
    assert "site: 'The Quant Campus'" in line and "repo: 'the-quant-campus'" in line and "pending" not in line  # launched 21 Oct 2026
    assert "QK.SPORTS = QK.ALL_SPORTS.filter(QK.visible);" in js
    assert "college: { fixtures: 'Games' }" in js and "  college: '<svg" in js
    # the switcher and footer still iterate QK.SPORTS (the filtered list); lookups use every site
    assert "QK.SPORTS.map(function (s) {" in js
    assert "for (var i = 0; i < QK.ALL_SPORTS.length; i++)" in js


def test_tokens_college_accent_both_themes():
    css = (KIT / "tokens.css").read_text(encoding="utf-8")
    assert css.count("--a-college:") == 3          # dark, light (media query), light (data-theme)
    assert ':root[data-sport="college"]    { --accent: var(--a-college); }' in css

    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def cr(a, b):
        x, y = lum(a), lum(b)
        return (max(x, y) + 0.05) / (min(x, y) + 0.05)
    dark = re.search(r"--a-college:\s*(#[0-9a-f]{6})", css).group(1)
    light = re.findall(r"--a-college: (#[0-9a-f]{6})", css)[-1]
    assert cr(dark, "#11151b") >= 4.5 and cr(light, "#ffffff") >= 4.5


# ── home page gate ────────────────────────────────────────────────────────
def test_home_college_is_launched():
    assert "college" in [s[0] for s in bh.PENDING]
    assert "college" in bh.LAUNCHED


def _home(tmp_path, monkeypatch, argv):
    docs = tmp_path / "docs"
    fixture.make(docs / "campus" / "data")
    from oddsmarkets.college import site
    from datetime import datetime, timezone
    site.build_all(docs / "campus" / "data", datetime.now(timezone.utc))
    monkeypatch.setattr(bh, "DOCS", docs)
    monkeypatch.setattr(bh, "OUT", docs / "home")
    bh.main(argv + ["--no-kit"])
    home = json.loads((docs / "home" / "data" / "home.json").read_text(encoding="utf-8"))
    search = json.loads((docs / "home" / "data" / "search.json").read_text(encoding="utf-8"))
    return home, search


def test_home_leaves_a_pending_site_out_until_launched(tmp_path, monkeypatch):
    monkeypatch.setattr(bh, "LAUNCHED", set())
    home, search = _home(tmp_path, monkeypatch, [])
    assert "college" not in [s["key"] for s in home["sports"]]
    assert not [g for g in home["games"] if g["sport"] == "college"]
    assert not [r for r in search["rows"] if r[0] == "college"]
    monkeypatch.setattr(bh, "LAUNCHED", {"college"})
    home, search = _home(tmp_path, monkeypatch, [])
    assert "college" in [s["key"] for s in home["sports"]]


def test_home_with_pending_includes_college(tmp_path, monkeypatch):
    home, search = _home(tmp_path, monkeypatch, ["--links", "local", "--with-pending"])
    entry = [s for s in home["sports"] if s["key"] == "college"][0]
    assert entry["ok"] is True and entry["url"] == "../campus/"
    rows = [r for r in search["rows"] if r[0] == "college"]
    assert any(r[3] == "../campus/#/cfb/team/1" for r in rows)
    assert "college" in home["futures"]


# ── front end static rules ────────────────────────────────────────────────
FRONT = ROOT / "docs" / "campus"


def test_front_end_files_and_older_browser_rule():
    js = sorted((FRONT / "assets" / "js").glob("*.js"))
    assert {p.name for p in js} >= {"cc-core.js", "cc-overview.js", "cc-games.js", "cc-standings.js", "cc-teams.js", "cc-players.js", "cc-value.js", "cc-model.js"}
    for p in js:
        src = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|/\*.*?\*/|//[^\n]*", "", p.read_text(encoding="utf-8"), flags=re.S)
        assert "?." not in re.sub(r"\?\.\d", "", src), p.name
        assert "??" not in src, p.name
    html = (FRONT / "index.html").read_text(encoding="utf-8")
    assert '<html lang="en" data-sport="college">' in html
    assert "qc-notice-v1" in html and "not affiliated" in html and "College Football Playoff" in html
    # cc-metrics.js (the generated comparison metric sets) is loaded on demand by cc-core.js, not by a script tag
    lazy = {"cc-metrics.js"}
    core = (FRONT / "assets" / "js" / "cc-core.js").read_text(encoding="utf-8")
    for p in js:
        if p.name in lazy:
            assert f"'assets/js/{p.name}'" in core, p.name
        else:
            assert f'src="assets/js/{p.name}"' in html, p.name
    assert "<img" not in html


def test_routes_cover_the_nine_sections():
    src = "".join(p.read_text(encoding="utf-8") for p in (FRONT / "assets" / "js").glob("*.js"))
    routes = set(re.findall(r"CC\.route\('([a-z]+)'", src))
    assert routes >= {"overview", "games", "game", "standings", "teams", "team", "players", "player", "value", "fantasy", "lab", "model"}
