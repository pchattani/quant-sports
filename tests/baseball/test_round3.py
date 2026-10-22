"""Round 3 (22 Oct 2026): timecoded pre-game snapshots, pre-game timestamps in the store, lineup strength and the
starter status on game pages. No network (a stub client), synthetic data."""
from __future__ import annotations

import types

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball import store as ST
from oddsmarkets.baseball.models import lineup_strength as LS
from oddsmarkets.baseball.sources import statsapi as SA


# ── snapshots ────────────────────────────────────────────────────────────────

FEED = {"metaData": {"timeStamp": "20240404_223431"},
        "gameData": {"datetime": {"dateTime": "2024-04-04T23:40:00Z"}, "status": {"detailedState": "Pre-Game"},
                     "probablePitchers": {"home": {"id": 607625}, "away": {"id": 647336}}},
        "liveData": {"boxscore": {"teams": {"home": {"battingOrder": [1, 2, 3, 4, 5, 6, 7, 8, 9]},
                                            "away": {"battingOrder": []}}}}}


def test_compact_snapshot_reads_time_lead_lineups_and_probables():
    r = SA.compact_snapshot(FEED, "2024-04-04T23:40:00Z")
    assert r["ts"] == "2024-04-04T22:34:31Z"
    assert r["lead_min"] == pytest.approx(65.5, abs=0.1)
    assert r["state"] == "Pre-Game"
    assert r["lineups"]["home"] == [str(i) for i in range(1, 10)] and r["lineups"]["away"] == []
    assert r["probables"] == {"home": "607625", "away": "647336"}


def test_pregame_snapshot_asks_for_a_time_well_before_first_pitch():
    calls = []

    class Stub:
        def get(self, url, params=None):
            calls.append((url, params))
            return FEED
    r = SA.pregame_snapshot(Stub(), "746327", "2024-04-04T23:40:00Z")
    url, params = calls[0]
    assert url.endswith("/v1.1/game/746327/feed/live")
    assert params["timecode"] == "20240404_174000"          # six hours before
    assert "battingOrder" in params["fields"] and "timeStamp" in params["fields"]
    assert r["lead_min"] > 0


def test_pregame_snapshot_none_on_failure_or_bad_start():
    class Stub:
        def get(self, url, params=None):
            return None
    assert SA.pregame_snapshot(Stub(), "1", "2024-04-04T23:40:00Z") is None
    assert SA.pregame_snapshot(Stub(), "1", "not a time") is None


# ── pre-game timestamps in the store ─────────────────────────────────────────

def _store():
    return {"games": {}, "meta": {}}


def _g(status="pre", lineups=None, probables=("10", "20")):
    return {"gpk": "1", "date": "2026-05-01", "status": status, "home": "1", "away": "2", "lineups": lineups,
            "probables": {"home": probables[0], "away": probables[1]}}


def test_stamps_lineups_once_and_again_when_they_change(monkeypatch):
    t = iter(["T1", "T2", "T3", "T4"])
    monkeypatch.setattr(ST, "now", lambda: next(t))
    s = _store()
    ST.merge_game(s, _g())                                           # T1: probables only
    assert "lineups_at" not in s["games"]["1"]
    assert s["games"]["1"]["probables_log"] == [["T1", "10", "20"]]
    lu = {"1": [str(i) for i in range(9)]}
    ST.merge_game(s, _g(lineups=lu))                                 # T2: home lineup posted
    assert s["games"]["1"]["lineups_at"] == {"1": "T2"}
    ST.merge_game(s, _g(lineups=lu))                                 # T3: unchanged: no new stamp, no new log row
    assert s["games"]["1"]["lineups_at"] == {"1": "T2"}
    assert len(s["games"]["1"]["probables_log"]) == 1
    lu2 = {"1": [str(i) for i in range(1, 10)]}
    ST.merge_game(s, _g(lineups=lu2, probables=("11", "20")))        # T4: a late change and a scratch
    assert s["games"]["1"]["lineups_at"] == {"1": "T4"}
    assert s["games"]["1"]["probables_log"][-1] == ["T4", "11", "20"]


def test_never_stamps_games_that_have_started(monkeypatch):
    monkeypatch.setattr(ST, "now", lambda: "T")
    s = _store()
    ST.merge_game(s, _g(status="final", lineups={"1": [str(i) for i in range(9)]}))
    assert "lineups_at" not in s["games"]["1"] and "probables_log" not in s["games"]["1"]
    ST.merge_game(s, _g(status="live", lineups={"1": [str(i) for i in range(9)]}))
    assert "lineups_at" not in s["games"]["1"]


# ── lineup strength ──────────────────────────────────────────────────────────

def test_strength_weights_slots_and_needs_nine():
    vals = {str(i): 0.300 for i in range(9)}
    assert LS.strength([str(i) for i in range(9)], vals) == pytest.approx(0.300)
    vals["0"] = 0.400                                                # the lead-off man gets the most plate appearances
    up_top = LS.strength([str(i) for i in range(9)], vals)
    down = LS.strength([str(i) for i in range(1, 9)] + ["0"], vals)
    assert up_top > down > 0.300
    assert LS.strength([str(i) for i in range(8)], vals) is None
    assert LS.strength(["x"] * 9, {}) == pytest.approx(LS.REG_TARGET)


def test_typical_uses_only_earlier_lineups():
    lu_a = [f"a{i}" for i in range(9)]
    lu_b = [f"b{i}" for i in range(9)]
    hist = {"1": [(f"2026-05-{d:02d}", lu_a) for d in range(1, 11)] + [("2026-05-11", lu_b)]}
    vals = {**{p: 0.300 for p in lu_a}, **{p: 0.400 for p in lu_b}}
    assert LS.typical("1", "2026-05-11", hist, vals) == pytest.approx(0.300)      # the day's own lineup is excluded
    assert LS.typical("1", "2026-05-12", hist, vals) > 0.300
    assert LS.typical("1", "2026-05-04", hist, vals) is None                       # fewer than five earlier lineups
    assert LS.delta("1", "2026-05-11", lu_b, hist, vals) == pytest.approx(0.100)


def test_game_block_effect_sign():
    lu = [f"a{i}" for i in range(9)]
    hist = {"1": [(f"2026-05-{d:02d}", lu) for d in range(1, 11)], "2": [(f"2026-05-{d:02d}", lu) for d in range(1, 11)]}
    vals = {p: 0.300 for p in lu}
    better = [f"b{i}" for i in range(9)]
    vals.update({p: 0.320 for p in better})
    out = LS.game_block("1", "2", "2026-05-20", {"home": better, "away": lu}, hist, vals, 0.5)
    assert out["home"]["delta"] == pytest.approx(0.02) and out["away"]["delta"] == pytest.approx(0.0)
    assert out["effect_home"] == pytest.approx(0.25 * LS.SIM_LOGIT_PER_WOBA * 0.02, abs=1e-4)
    assert LS.game_block("1", "2", "2026-05-20", {"home": None, "away": None}, hist, vals, 0.5) is None


def test_values_use_only_days_before(monkeypatch):
    cur = pd.DataFrame({"game_date": ["2026-04-01", "2026-04-02", "2026-04-03"], "batter": ["7", "7", "7"],
                        "woba_value": [2.0, 2.0, 0.0], "woba_denom": [1.0, 1.0, 1.0]})
    monkeypatch.setattr(LS, "_sums", lambda level, s: cur if s == 2026 else None)
    V = LS.Values("mlb", 2026)
    assert "7" not in V.on("2026-04-01")
    v2 = V.on("2026-04-02")["7"]
    assert v2 == pytest.approx((5 * 2.0 + LS.REG_N * LS.REG_TARGET) / (5 * 1.0 + LS.REG_N))
    assert V.on("2026-04-04")["7"] == pytest.approx((5 * 4.0 + LS.REG_N * LS.REG_TARGET) / (5 * 3.0 + LS.REG_N))


# ── starter status on game pages ─────────────────────────────────────────────

def test_starters_status_flags(monkeypatch):
    from oddsmarkets.baseball.analytics import games as GM
    from oddsmarkets.baseball.models import _dio
    games = {}
    k = 0
    for sp, dates in (("vet", [f"2026-04-{d:02d}" for d in range(1, 30, 5)]), ("rook", ["2026-04-20"]),
                      ("hurt", [f"2026-03-{d:02d}" for d in range(26, 31)] + ["2026-04-01"])):
        for d in dates:
            k += 1
            games[str(k)] = {"status": "final", "date": d, "probables": {"home": sp, "away": None}}
    st = {"games": games}
    monkeypatch.setattr(_dio, "load_store", lambda level, s: {"games": {}})
    ctx = types.SimpleNamespace(level="mlb", season=2026, store=st, players={"new": {"debut": None, "throws": "L"}})
    out = GM._starters_status(ctx, {"date": "2026-06-15", "probables": {"home": "vet", "away": "rook"}})
    assert out["home"]["flag"] is None and out["home"]["days_since"] == 50
    assert out["away"]["flag"] == "few" and out["away"]["starts"] == 1
    g = {"date": "2026-06-15", "probables": {"home": "hurt", "away": None}}
    out = GM._starters_status(ctx, g)
    assert out["home"]["flag"] == "back" and out["home"]["days_since"] > 60 and out["away"] is None
    g = {"date": "2026-04-10", "probables": {"home": "vet", "away": "new"}}
    out = GM._starters_status(ctx, g)
    assert out["home"]["starts"] == 2 and out["home"]["flag"] == "few"               # only starts before the date
    assert out["away"]["flag"] == "debut" and out["away"]["throws"] == "L"
