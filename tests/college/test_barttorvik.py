"""Barttorvik T-Rank source (oddsmarkets/college/sources/barttorvik.py)."""
from __future__ import annotations

from pathlib import Path

from oddsmarkets.college.sources import barttorvik as BT
from oddsmarkets.common import polite

FIX = Path(__file__).parent / "fixtures" / "barttorvik" / "2025_team_results_head.csv"


def test_parse_team_results():
    rows = BT.parse_team_results(FIX.read_text(encoding="utf-8"))
    assert [r["team"] for r in rows] == ["Houston", "Duke", "Auburn"]
    h = rows[0]
    assert h["rank"] == 1 and h["conf"] == "B12" and h["record"] == "35-5"
    assert abs(h["net"] - (h["adjoe"] - h["adjde"])) < 0.02
    assert 0.98 < h["barthag"] < 0.99


def test_parse_rejects_html_and_empty():
    assert BT.parse_team_results("<html><body>challenge</body></html>") == []
    assert BT.parse_team_results("") == [] and BT.parse_team_results(None) == []


def test_paths_are_allowed_by_robots_and_game_pages_are_not():
    txt = ("User-agent: *\nDisallow: /db.php\nDisallow: /trank-time-machine.php\nDisallow: /*.json\n"
           "Disallow: ncaaw/db.php\nCrawl-Delay: 10\n")
    rules, delay = polite.parse_robots(txt)
    assert delay == 10.0
    assert polite.robots_allows(rules, BT.csv_path("mbb", 2025))
    assert polite.robots_allows(rules, BT.csv_path("wbb", 2025))
    assert not polite.robots_allows(rules, "/trank-time-machine.php?date=20250301")
    assert not polite.robots_allows(rules, "/ncaaw/db.php")
    assert BT.SRC.interval >= 10


def test_name_matching_exact_and_alias_only():
    ours = {"1": "NC State", "2": "IU Indianapolis", "3": "Texas", "4": "St. John's", "5": "Saint Mary's"}
    m = BT.match_names(["N.C. State", "IU Indy", "Texas Southern", "St. John's", "Saint Mary's", "Texas"], ours)
    assert m == {"N.C. State": "1", "IU Indy": "2", "St. John's": "4", "Saint Mary's": "5", "Texas": "3"}
    assert "Texas Southern" not in m                      # never a loose prefix match


def test_switch_off(monkeypatch):
    monkeypatch.setenv("SOURCE_BARTTORVIK_ENABLED", "0")
    assert BT.season_teams("mbb", 2025) == []
    assert BT.load_derived() is None
    assert BT.write_derived({"mbb": {"2025": {"1": "Houston"}}}) is None


def test_offline_cache_only(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_BARTTORVIK_ENABLED", "1")
    src = polite.Source(name="t", base="https://example.invalid", flag="SOURCE_BARTTORVIK_ENABLED", raw_dir=tmp_path)
    monkeypatch.setattr(BT, "SRC", src)
    assert BT.season_teams("mbb", 2025) == []
    src.write_cached(BT.csv_path("mbb", 2025), {"status": 200, "fetched_at": "2026-10-30T00:00:00Z",
                                                "text": FIX.read_text(encoding="utf-8")})
    assert len(BT.season_teams("mbb", 2025)) == 3
