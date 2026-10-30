"""Umpire Scorecards source (oddsmarkets/baseball/sources/umpscorecards.py) and the shared polite client."""
from __future__ import annotations

import json
from pathlib import Path

from oddsmarkets.baseball.sources import umpscorecards as USC
from oddsmarkets.common import polite

FIX = Path(__file__).parent / "fixtures" / "umpscorecards" / "games_sample.json"


def test_parse_drops_failed_rows_and_trims_fields():
    rows = USC.parse(FIX.read_text(encoding="utf-8"))
    assert len(rows) == 3                                   # the fourth row is marked failed
    assert set(rows[0]) == set(USC.FIELDS)
    assert rows[0]["umpire"] == "Mark Ripperger" and rows[0]["game_pk"] == 778498


def test_parse_bad_input():
    assert USC.parse(None) == [] and USC.parse("not json") == [] and USC.parse('{"rows": null}') == []


def test_umpire_season_aggregates():
    games = {str(r["game_pk"]): r for r in USC.parse(FIX.read_text(encoding="utf-8"))}
    agg = USC.umpire_season(games)
    a = agg["Mark Ripperger"]
    assert a["games"] == 1 and a["called"] == 118
    assert abs(a["accuracy"] - 108 / 118) < 1e-4
    assert abs(a["consistency"] - 0.9237) < 1e-3          # fractions, not percent
    assert abs(a["batter_runs"] - (-0.55 + 0.11)) < 1e-9


def test_prior_profiles_has_no_look_ahead():
    games = {str(r["game_pk"]): r for r in USC.parse(FIX.read_text(encoding="utf-8"))}
    assert USC.prior_profiles(games, "2025-04-01") == {}     # scorecards of the game day itself are not yet known
    assert "Mark Wegner" in USC.prior_profiles(games, "2025-04-02")


def test_switch_off_drops_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_UMPSCORECARDS_ENABLED", "0")
    assert not USC.enabled()
    assert USC.season_games(2025) == {}
    assert USC.load_derived() is None
    assert USC.write_derived() is None


def test_offline_reads_cache_only(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCE_UMPSCORECARDS_ENABLED", "1")
    src = polite.Source(name="t", base="https://example.invalid", flag="SOURCE_UMPSCORECARDS_ENABLED", raw_dir=tmp_path)
    monkeypatch.setattr(USC, "SRC", src)
    assert USC.season_games(2025) == {}                      # nothing cached, offline: no request
    src.write_cached(USC.season_path(2025), {"path": "x", "status": 200, "fetched_at": "2026-10-30T00:00:00Z",
                                             "text": FIX.read_text(encoding="utf-8")})
    assert len(USC.season_games(2025)) == 3


def test_ci_never_fetches(monkeypatch):
    monkeypatch.setenv("SOURCE_UMPSCORECARDS_ENABLED", "1")
    monkeypatch.setenv("CI", "true")
    assert not USC.SRC.fetch_allowed()
    assert USC.SRC.client().offline


def test_robots_parser():
    txt = "User-agent: *\nDisallow: /db.php\nDisallow: /*.json\nCrawl-Delay: 10\n\nUser-agent: ClaudeBot\nDisallow: /\n"
    rules, delay = polite.parse_robots(txt)
    assert delay == 10.0
    assert not polite.robots_allows(rules, "/db.php?x=1")
    assert not polite.robots_allows(rules, "/2026_team_results.json")
    assert polite.robots_allows(rules, "/2026_team_results.csv")


def test_derived_file_is_aggregates_only():
    if not USC.DERIVED.exists():
        return
    d = json.loads(USC.DERIVED.read_text(encoding="utf-8"))
    assert d["credit"].startswith("Umpire Scorecards")
    one = next(iter(next(iter(d["seasons"].values())).values()))
    assert set(one) == {"games", "called", "accuracy", "acc_above_x", "consistency", "run_impact", "favor", "batter_runs"}
