"""A decided World Series in the current season (29 Oct 2026: the Brewers beat the Rays 4-1): the simulated bracket is
marked as played (season.mark_decided), our calls come from the race log (season.calls_from_log), and the digest's
stage carries the title block (build_bullpen.title_block) that the overview and the Home page read."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from oddsmarkets.baseball.analytics import season as SN

ROOT = Path(__file__).resolve().parents[2]


def _bullpen():
    spec = importlib.util.spec_from_file_location("build_bullpen_t", ROOT / "scripts" / "build_bullpen.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_bullpen_t"] = mod
    spec.loader.exec_module(mod)
    return mod


def _bracket(ws_wins, done):
    return {"round": "WS", "series": [
        {"id": "CS-158-119", "round": "CS", "teams": ["158", "119"], "wins": [4, 2], "done": True, "games": []},
        {"id": "WS-158-139", "round": "WS", "round_name": "World Series", "teams": ["158", "139"], "wins": ws_wins, "done": done,
         "games": ["1", "2", "3", "4", "5", "6", "7"]}],
        "teams": {"158": {"p_ws": 1.0 if done else 0.6}, "139": {"p_ws": 0.0 if done else 0.4}, "119": {"p_ws": 0.0}}}


def test_mark_decided_sets_champion_and_winners():
    b = SN.mark_decided(_bracket([4, 1], True))
    assert b["actual"] and b["complete"] and b["champion"] == "158"
    assert [s["winner"] for s in b["series"]] == ["158", "158"]
    assert b["teams"]["158"]["champion"] and not b["teams"]["139"]["champion"]
    assert b["teams"]["139"]["reached"] == "WS" and b["teams"]["119"]["reached"] == "CS"


def test_mark_decided_leaves_a_live_series_alone():
    b = SN.mark_decided(_bracket([3, 1], False))
    assert "actual" not in b and "champion" not in b
    assert b["series"][1].get("winner") is None


def _cards():
    cards = [{"gpk": "r1", "gtype": "R", "date": "2026-03-25", "status": "final"},
             {"gpk": "r2", "gtype": "R", "date": "2026-09-27", "status": "final"},
             {"gpk": "w1", "gtype": "F", "date": "2026-09-29", "status": "final"}]
    for k, (d, h, hs, a_s) in enumerate([("2026-10-23", "158", 3, 2), ("2026-10-24", "158", 5, 1), ("2026-10-26", "139", 4, 2),
                                         ("2026-10-27", "139", 1, 6), ("2026-10-28", "139", 2, 7)]):
        cards.append({"gpk": str(k + 1), "gtype": "W", "date": d, "status": "final", "home": h, "away": "139" if h == "158" else "158", "hs": hs, "as": a_s})
    cards += [{"gpk": "6", "gtype": "W", "date": "2026-10-30", "status": "scheduled", "home": "158", "away": "139"}]
    return cards


def test_calls_from_log_picks_week_one_and_the_eve():
    log = {"p_ws": {"2026-03-30": {"158": 0.05}, "2026-04-01": {"158": 0.06, "139": 0.04}, "2026-09-28": {"158": 0.228, "139": 0.11, "119": 0.0},
                    "2026-10-01": {"158": 0.25}}, "p_postseason": {"2026-04-01": {"158": 0.5}}}
    c = SN.calls_from_log(log, _cards())
    assert c["first"]["asof"] == "2026-04-01" and c["first"]["p_ws"]["158"] == 0.06
    assert c["preplayoff"]["asof"] == "2026-09-28" and c["preplayoff"]["p_ws"] == {"158": 0.228, "139": 0.11}
    assert SN.calls_from_log({}, _cards()) is None


def test_title_block_reads_from_the_champions_side():
    bp = _bullpen()
    calls = {"preplayoff": {"asof": "2026-09-28", "p_ws": {"158": 0.228, "139": 0.11, "119": 0.2}}}
    ws = _bracket([4, 1], True)["series"][1]
    t = bp.title_block(ws, "158", _cards(), calls)
    assert t["champion"] == "158" and t["runner_up"] == "139" and t["result"] == [4, 1]
    assert [g["score"] for g in t["games"]] == [[3, 2], [5, 1], [2, 4], [6, 1], [7, 2]]
    assert t["decided"] == "2026-10-28" and t["pre_p"] == 0.228 and t["pre_rank"] == 1 and t["pre_n"] == 3
    # the runner-up listed first in the series
    ws2 = dict(ws, teams=["139", "158"], wins=[1, 4])
    assert bp.title_block(ws2, "158", _cards(), None)["result"] == [4, 1]
