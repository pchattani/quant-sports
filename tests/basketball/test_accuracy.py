"""Data-accuracy fixes found by the cross-site audit (22 Oct 2026): unplayed 'if necessary' playoff games, the season
aggregates' game set, a traded player's shown team and the calibration page's backtest. Synthetic data; no network."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from oddsmarkets.basketball import analytics as an
from oddsmarkets.basketball.analytics import context as CX
from oddsmarkets.basketball.analytics import players as PL
from oddsmarkets.basketball.analytics import season as SN

NOW = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)


def _g(gid, d, stype, status, home="1", away="2", summary=None):
    return {"id": gid, "date": d, "stype": stype, "status": status, "home": home, "away": away,
            "series": {"round": "Playoff Series", "game": None, "summary": summary} if summary else None}


def test_unneeded_playoff_games():
    st = {"games": {
        "a": _g("a", "2026-10-09T23:30:00Z", "post", "post", summary="ATL wins series 3-0"),
        "b": _g("b", "2026-10-11T04:00:00Z", "post", "pre", summary="ATL wins series 3-0"),       # game 4 never needed
        "c": _g("c", "2026-10-14T04:00:00Z", "post", "pre", summary="ATL leads series 3-0"),      # stale: two days gone
        "d": _g("d", "2026-10-24T17:00:00Z", "post", "pre", summary="ATL leads series 2-1"),      # upcoming: kept
        "e": _g("e", "2026-10-23T17:00:00Z", "post", "pre", summary="BOS win series 4-1"),
        "f": _g("f", "2026-10-01T23:00:00Z", "reg", "pre"),                                       # not a playoff game
    }}
    assert an.unneeded_playoff_games(st, now=NOW) == {"b", "c", "e"}
    assert {"b", "e"} <= an.superseded(st)


def test_latest_team_follows_a_trade():
    bf = pd.DataFrame([
        {"player_id": "9", "team": "6", "game_id": "1", "date": "2026-05-01", "sec": 2000.0},
        {"player_id": "9", "team": "6", "game_id": "2", "date": "2026-06-01", "sec": 2000.0},
        {"player_id": "9", "team": "6", "game_id": "3", "date": "2026-07-01", "sec": 2000.0},
        {"player_id": "9", "team": "11", "game_id": "4", "date": "2026-08-10", "sec": 1200.0},
        {"player_id": "7", "team": "6", "game_id": "1", "date": "2026-05-01", "sec": 600.0},
    ])
    assert PL._primary_team(bf)["9"] == "6"
    assert PL._latest_team(bf)["9"] == "11" and PL._latest_team(bf)["7"] == "6"


def test_season_aggregates_drop_preseason_and_playoffs():
    ctx = CX.SeasonContext("nba", 2027, current=2027, today=date(2026, 10, 22))
    ctx.__dict__["games"] = {"p1": _g("p1", "2026-10-05T23:00:00Z", "pre", "post"),
                             "r1": _g("r1", "2026-10-21T23:00:00Z", "reg", "post"),
                             "c1": _g("c1", "2026-12-16T23:00:00Z", "cup", "post"),
                             "x1": _g("x1", "2027-04-20T23:00:00Z", "post", "post")}
    ctx.__dict__["shots"] = pd.DataFrame({"game_id": ["p1", "p1", "r1", "c1", "x1"], "shooter": ["a"] * 5})
    ctx.__dict__["stints"] = pd.DataFrame({"game_id": ["p1", "r1"], "t0": [0.0, 0.0]})
    ctx.__dict__["team_stints"] = pd.DataFrame({"game_id": ["p1", "p1", "r1", "r1"], "team": ["1", "2", "1", "2"]})
    assert ctx.season_game_ids == {"r1"}
    assert ctx.season_shots["game_id"].tolist() == ["r1"]
    assert ctx.season_stints["game_id"].tolist() == ["r1"]
    assert ctx.season_team_stints["game_id"].tolist() == ["r1", "r1"]
    assert ctx.shots.shape[0] == 5                                     # game pages keep the full table
    assert set(ctx.season_pbp_summaries({"p1": {}, "r1": {}, "x1": {}})) == {"r1"}


def test_calibration_prefers_the_newer_backtest(tmp_path, monkeypatch):
    cache, data = tmp_path / "cache", tmp_path / "data"
    (data / "nba").mkdir(parents=True)
    cache.mkdir()
    monkeypatch.setenv("HARDWOOD_CACHE", str(cache))
    monkeypatch.setattr(SN, "winprob_calibration", lambda *a, **k: None)
    monkeypatch.setattr(SN, "shots_calibration", lambda *a, **k: None)
    from oddsmarkets.basketball.models import backtest as BT
    monkeypatch.setattr(BT, "summary_table", lambda d: [{"model": "cached"}])
    (cache / "backtest_nba.json").write_text(json.dumps({"generated_at": "2026-10-01T16:13:34Z", "tag": "cache"}), encoding="utf-8")
    committed = {"ok": True, "generated_at": "2026-10-21T18:36:38Z", "updated_at": "2026-10-21T18:36:38Z", "tag": "committed"}
    (data / "nba" / "calibration.json").write_text(json.dumps(committed), encoding="utf-8")
    assert SN.calibration("nba", data, seasons=[2027])["tag"] == "committed"
    # a newer cached backtest (a local re-run) still wins over the committed copy
    (cache / "backtest_nba.json").write_text(json.dumps({"generated_at": "2026-10-23T09:00:00Z", "tag": "cache"}), encoding="utf-8")
    out = SN.calibration("nba", data, seasons=[2027])
    assert out["tag"] == "cache" and out["summary"] == [{"model": "cached"}]
