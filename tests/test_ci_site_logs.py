"""scripts/ci_site.py persistent logs: the overview chance logs and the Footballer's forecast log come from the
previous deploy on every CI run (football included, which restores nothing else), and a deploy whose build lost
history the live copy still holds merges it back, so no run resets a log."""
import importlib.util
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_site", ROOT / "scripts" / "ci_site.py")
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")


def _r(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_constants_agree_with_the_builders():
    from oddsmarkets.common import digest
    assert inspect.signature(digest.roll_log).parameters["keep"].default == ci.CHANCE_LOG_KEEP
    src = (ROOT / "scripts" / "build_site_all.py").read_text(encoding="utf-8")
    assert int(re.search(r"^FORECAST_LOG_DAYS = (\d+)", src, re.M).group(1)) == ci.FORECAST_LOG_DAYS


def test_every_site_lists_its_logs_and_the_patterns_match_only_them():
    assert set(ci.LOGS) == set(ci.SITES)
    assert ci.is_log("hardwood", "data/nba/chance_log.json")
    assert not ci.is_log("hardwood", "data/nba/2027/chance_log.json")
    assert ci.is_log("rink", "data/chance_log.json") and not ci.is_log("rink", "data/x/chance_log.json")
    assert ci.is_log("football", "data/forecast_log.json") and not ci.is_log("football", "data/x/forecast_log.json")
    assert not ci.is_log("paddock", "data/chance_log.json")


def test_football_restores_only_its_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    prev = tmp_path / "prev"
    _w(prev / "data" / "forecast_log.json", {"1": [0.5, 0.3, 0.2, "2026-10-23T15:00:00Z", "premier-league"]})
    _w(prev / "data" / "hub.json", {"stale": True})
    assert ci.main(["restore", "--site", "football", "--prev", str(prev)]) == 0
    data = tmp_path / "docs" / "site" / "data"
    assert _r(data / "forecast_log.json")["1"][4] == "premier-league"
    assert not (data / "hub.json").exists()


def test_football_restores_its_market_files_for_the_builder_to_read_back(tmp_path, monkeypatch):
    """market_odds.json comes back from the deploy (a fetch that returns nothing then keeps the unplayed lines and
    their updated_at, so staleness shows); a copy the checkout has is left alone, and nothing deeper matches."""
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    prev = tmp_path / "prev"
    _w(prev / "data" / "premier-league" / "market_odds.json", {"ok": True, "updated_at": "2026-10-28T05:43:58Z"})
    _w(prev / "data" / "la-liga" / "market_odds.json", {"ok": True, "updated_at": "2026-10-28T05:44:08Z"})
    _w(prev / "data" / "archive" / "x" / "market_odds.json", {"deep": True})
    data = tmp_path / "docs" / "site" / "data"
    _w(data / "la-liga" / "market_odds.json", {"ok": False, "updated_at": None})
    assert ci.main(["restore", "--site", "football", "--prev", str(prev)]) == 0
    assert _r(data / "premier-league" / "market_odds.json")["updated_at"] == "2026-10-28T05:43:58Z"
    assert _r(data / "la-liga" / "market_odds.json")["updated_at"] is None
    assert not (data / "archive" / "x" / "market_odds.json").exists()


def test_the_deployed_log_wins_over_a_checkout_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    prev = tmp_path / "prev"
    _w(prev / "data" / "nba" / "chance_log.json", {"2027": {"p_title": {"2026-10-23": {"BOS": 0.1}}}})
    _w(tmp_path / "docs" / "hardwood" / "data" / "nba" / "chance_log.json", {"2027": {}})
    assert ci.main(["restore", "--site", "hardwood", "--prev", str(prev)]) == 0
    assert _r(tmp_path / "docs" / "hardwood" / "data" / "nba" / "chance_log.json")["2027"]["p_title"]["2026-10-23"] == {"BOS": 0.1}


def _site(tmp_path, monkeypatch, site, rel, live, new):
    monkeypatch.setattr(ci, "ROOT", tmp_path)
    clone = tmp_path / "clone"
    _w(clone / rel, live)
    if new is not None:
        _w(tmp_path / "docs" / ci.SITES[site]["docs"] / rel, new)
    return clone, tmp_path / "docs" / ci.SITES[site]["docs"] / rel


def test_a_reset_chance_log_is_merged_back(tmp_path, monkeypatch):
    days = {f"2026-10-{d:02d}": {"COL": 0.1 + d / 100} for d in range(14, 24)}     # ten days live
    clone, out = _site(tmp_path, monkeypatch, "rink", "data/chance_log.json",
                       {"20262027": {"p_cup": days}}, {"20262027": {"p_cup": {"2026-10-24": {"COL": 0.5}}}})
    fixed = ci.repair_logs("rink", clone, NOW)
    assert len(fixed) == 1
    got = _r(out)["20262027"]["p_cup"]
    assert sorted(got) == [f"2026-10-{d:02d}" for d in range(15, 25)]      # the last ten days, the build's today kept
    assert got["2026-10-24"] == {"COL": 0.5}


def test_a_normal_append_is_left_alone(tmp_path, monkeypatch):
    live = {f"2026-10-{d:02d}": {"COL": 0.2} for d in range(14, 24)}
    new = dict({d: v for d, v in live.items() if d != "2026-10-14"}, **{"2026-10-24": {"COL": 0.3}})
    clone, out = _site(tmp_path, monkeypatch, "rink", "data/chance_log.json", {"20262027": {"p_cup": live}}, {"20262027": {"p_cup": new}})
    before = out.read_text(encoding="utf-8")
    assert ci.repair_logs("rink", clone, NOW) == []
    assert out.read_text(encoding="utf-8") == before


def test_a_new_season_retires_the_old_log(tmp_path, monkeypatch):
    clone, out = _site(tmp_path, monkeypatch, "gridiron", "data/chance_log.json",
                       {"2025": {"p_title": {"2026-02-01": {"KC": 0.4}}}}, {"2026": {"p_title": {"2026-10-24": {"KC": 0.2}}}})
    assert ci.repair_logs("gridiron", clone, NOW) == []
    assert list(_r(out)) == ["2026"]


def test_a_missing_or_reset_forecast_log_is_merged_back(tmp_path, monkeypatch):
    live = {"1": [0.5, 0.3, 0.2, "2026-10-22T15:00:00Z", "epl"],     # played two days ago: must survive
            "2": [0.4, 0.3, 0.3, "2026-10-10T15:00:00Z", "epl"],     # past the nine-day window: may go
            "3": [0.6, 0.2, 0.2, "2026-10-25T15:00:00Z", "epl"]}     # still ahead: the build's copy wins
    clone, out = _site(tmp_path, monkeypatch, "football", "data/forecast_log.json", live,
                       {"3": [0.61, 0.2, 0.19, "2026-10-25T15:00:00Z", "epl"]})
    assert len(ci.repair_logs("football", clone, NOW)) == 1
    got = _r(out)
    assert sorted(got) == ["1", "3"] and got["3"][0] == 0.61
    out.unlink()                                                      # the build wrote none at all
    assert len(ci.repair_logs("football", clone, NOW)) == 1
    assert sorted(_r(out)) == ["1", "3"]


def test_the_generated_football_workflow_restores_its_logs():
    wf = (ROOT / "public_repo" / ".github" / "workflows" / "football.yml").read_text(encoding="utf-8")
    assert "ci_site.py restore --site football" in wf
    for site in ("rink", "hardwood", "gridiron", "bullpen", "ace", "campus"):
        assert f"ci_site.py restore --site {site}" in (ROOT / "public_repo" / ".github" / "workflows" / f"{site}.yml").read_text(encoding="utf-8")


def test_the_us_sports_race_logs_are_kept_between_builds():
    """oddsmarkets/common/league.py race logs: the whole season (a "_meta" entry lists the rebuilt days)."""
    assert ci.is_log("rink", "data/race_log.json") and ci.is_log("gridiron", "data/race_log.json")
    assert ci.is_log("hardwood", "data/nba/race_log.json") and ci.is_log("bullpen", "data/mlb/race_log.json")
    assert not ci.is_log("rink", "data/20262027/race_log.json")
    days = {f"2026-{m:02d}-{d:02d}": {"A": 0.5} for m in (4, 5, 6, 7, 8, 9) for d in range(1, 29)}
    live = {"2026": {"p_postseason": days, "_meta": {"rebuilt": sorted(days)[:20], "n": 2000}}}
    new = {"2026": {"p_postseason": {"2026-10-24": {"A": 1.0}}}}
    out, lost = ci.merge_log("race_log.json", live, new, datetime(2026, 10, 24, tzinfo=timezone.utc))
    assert lost == len(days) + 2 and len(out["2026"]["p_postseason"]) == len(days) + 1
    assert out["2026"]["_meta"]["rebuilt"] == sorted(days)[:20]
