"""Home page builder: stale inputs never show as live, and CI fetches the season-dependent files it reads."""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("build_home", ROOT / "scripts" / "build_home.py")
bh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bh)

NOW = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)


def _g(status, hours_from_now):
    return bh.game("football", "X", "1", bh.iso(NOW + timedelta(hours=hours_from_now)), status,
                   bh.team("A"), bh.team("B"))


def test_stale_live_and_overdue_pre_games_are_dropped():
    ctx = bh.Ctx("public", NOW)
    assert bh.in_window(ctx, _g("live", -1.5))            # a game in progress
    assert not bh.in_window(ctx, _g("live", -5 * 24))     # "live" since 17 Oct: a stale input
    assert not bh.in_window(ctx, _g("live", -10))         # longer than any game lasts
    assert bh.in_window(ctx, _g("pre", 2))
    assert bh.in_window(ctx, _g("pre", -1))               # just started, status not updated yet
    assert not bh.in_window(ctx, _g("pre", -30))          # never started per the input: stale
    assert bh.in_window(ctx, _g("final", -30))
    assert not bh.in_window(ctx, _g("final", -50))
    picked = bh.pick_games(ctx, [_g("live", -100), _g("live", -1), _g("pre", -30), _g("pre", 5)])
    assert [g["status"] for g in picked] == ["live", "pre"]


def test_season_files_follow_each_sites_index(tmp_path):
    def put(rel, obj):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj), encoding="utf-8")

    put("paddock/data/index.json", {"current_season": 2026})
    put("hardwood/data/index.json", {"leagues": {"nba": {"current_season": 2027}, "wnba": {"current_season": 2026}}})
    put("gridiron/data/index.json", {"season": 2026})
    put("rink/data/index.json", {"season": "20262027"})
    rows = bh.season_files(tmp_path)
    assert ("paddock", "the-quant-paddock", "2026/season.json") in rows
    assert ("hardwood", "the-quant-hardwood", "nba/2027/season.json") in rows
    assert ("hardwood", "the-quant-hardwood", "wnba/2026/season.json") in rows
    assert ("gridiron", "the-quant-gridiron", "2026/season.json") in rows
    assert ("rink", "the-quant-rink", "20262027/season.json") in rows
    assert ("site", "the-quant-footballer", "premier-league/probs.json") in rows
    assert ("site", "the-quant-footballer", "premier-league/market_odds.json") in rows
    # a missing tree gives no rows for that site rather than an error
    assert all(r[0] == "site" for r in bh.season_files(tmp_path / "nothing"))


def test_home_workflow_fetches_the_season_files():
    gen = (ROOT / "scripts" / "gen_ci_workflows.py").read_text(encoding="utf-8")
    assert "build_home.py --season-files" in gen
