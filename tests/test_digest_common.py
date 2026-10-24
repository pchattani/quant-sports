"""oddsmarkets/common/digest.py: the "This week in <sport>" top lines (record, upset, hot side, chance log, movers)."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.common import digest as DG

NOW = datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)


def g(i, day, home, away, hs, as_, ph, pd=None, status="final"):
    x = {"id": i, "start": f"2026-10-{day:02d}T23:00:00Z", "status": status, "home": home, "away": away, "hs": hs, "as": as_, "p_home": ph}
    if pd is not None:
        x["p_draw"] = pd
    return x


GAMES = [
    g(1, 22, "A", "B", 3, 1, 0.70),      # favourite A won
    g(2, 21, "C", "D", 1, 4, 0.75),      # upset: D won at 25%
    g(3, 20, "A", "C", 2, 0, 0.60),      # favourite A won
    g(4, 19, "B", "D", 2, 3, 0.35),      # favourite D (65%) won
    g(5, 10, "A", "D", 0, 9, 0.90),      # outside the week: never counted
    g(6, 23, "B", "C", None, None, 0.5, status="pre"),
    g(7, 18, "E", "F", 1, 1, 0.45, pd=0.27),  # football draw
]


def test_record_counts_favourites_against_expected():
    r = DG.record(GAMES, NOW)
    assert r["n"] == 5 and r["won"] == 3 and r["upsets"] == 1 and r["draws"] == 1
    assert r["expected"] == round(0.70 + 0.75 + 0.60 + 0.65 + 0.45, 1)
    assert r["expected_rate"] == round((0.70 + 0.75 + 0.60 + 0.65 + 0.45) / 5, 4)
    assert r["from"] == "2026-10-16" and r["to"] == "2026-10-23"


def test_record_on_the_home_game_shape_by_sport():
    """featured.py's game dict (team dicts, a sport per game); an NFL tie (no draw chance) has no result."""
    t = lambda a: {"abbr": a, "name": a + " FC"}
    games = [dict(g(1, 22, t("A"), t("B"), 3, 1, 0.7), sport="hockey"), dict(g(2, 21, t("C"), t("D"), 0, 2, 0.6), sport="hockey"),
             dict(g(3, 20, t("E"), t("F"), 24, 17, 0.8), sport="nfl"), dict(g(4, 20, t("G"), t("H"), 20, 20, 0.55), sport="nfl")]
    r = DG.record(games, NOW)
    assert r["n"] == 3 and r["won"] == 2 and r["draws"] == 0
    assert r["by"] == [{"sport": "hockey", "n": 2, "won": 1, "expected": 1.3}, {"sport": "nfl", "n": 1, "won": 1, "expected": 0.8}]
    assert DG.hot(games, NOW) is None                 # nobody played twice
    u = DG.upset(games, NOW, full=True)
    assert u["winner"] == {"abbr": "D", "name": "D FC"} and u["p"] == 0.4 and u["sport"] == "hockey" and u["game"]["id"] == 2


def test_record_needs_a_few_games():
    assert DG.record(GAMES[:2], NOW) is None


def test_upset_is_the_lowest_pre_game_winner_this_week():
    u = DG.upset(GAMES, NOW)
    assert u["id"] == 2 and u["winner"] == "D" and u["loser"] == "C" and u["p"] == 0.25 and u["side"] == "away"
    # game 5 (D at 10%) is older than a week, so never the upset of this week
    assert DG.upset([GAMES[0], GAMES[2]], NOW) is None


def test_hot_side_most_wins_then_margin():
    h = DG.hot(GAMES, NOW)
    assert h["key"] in ("A", "D") and h["w"] == 2 and h["l"] == 0
    assert h["key"] == "A" and h["margin"] == 4.0   # A and D both 2-0, +4: the name breaks the tie
    assert DG.hot([], NOW) is None


def test_chance_log_rolls_one_snapshot_a_day():
    log = {}
    for d in range(10, 24):
        log = DG.roll_log(log, datetime(2026, 10, d, 12, tzinfo=timezone.utc), {"A": 0.5 + d / 100, "B": 0.5 - d / 100}, keep=10)
    assert len(log) == 10 and min(log) == "2026-10-14" and max(log) == "2026-10-23"
    again = DG.roll_log(log, datetime(2026, 10, 23, 22, tzinfo=timezone.utc), {"A": 0.9})
    assert again["2026-10-23"] == {"A": 0.9} and len(again) == 10
    assert DG.roll_log(log, NOW, {}) == log


def test_movers_since_about_a_week_ago():
    log = {"2026-10-15": {"A": 0.40, "B": 0.60, "C": 0.50}, "2026-10-16": {"A": 0.42, "B": 0.58, "C": 0.5}, "2026-10-23": {"A": 0.7}}
    m = DG.movers(log, {"A": 0.70, "B": 0.45, "C": 0.51}, NOW)
    assert m["since"] == "2026-10-16" and m["days"] == 7
    assert m["up"][0]["key"] == "A" and abs(m["up"][0]["d"] - 0.28) < 1e-9
    assert m["down"][0]["key"] == "B" and all(r["key"] != "C" for r in m["up"] + m["down"])
    # only today's snapshot: no movers yet (never compared with itself)
    assert DG.movers({"2026-10-23": {"A": 0.5}}, {"A": 0.9}, NOW) is None


def test_swing_is_the_biggest_move_this_week():
    series = [{"name": "A", "kind": "title", "points": [["2026-10-10T00:00:00Z", 0.9], ["2026-10-17T00:00:00Z", 0.30], ["2026-10-23T00:00:00Z", 0.45]]},
              {"name": "B", "kind": "playoff", "points": [["2026-10-18T00:00:00Z", 0.50], ["2026-10-23T00:00:00Z", 0.30]]},
              {"name": "C", "points": [["2026-10-23T00:00:00Z", 0.9]]}]
    s = DG.swing(series, NOW)
    assert s["name"] == "B" and s["delta"] == -0.2 and s["kind"] == "playoff" and s["since"] == "2026-10-18T00:00:00Z"
    assert DG.swing(series, NOW, min_move=0.5) is None


def test_log_series_feeds_swing():
    log = {"2026-10-17": {"A": 0.2, "B": 0.5}, "2026-10-23": {"A": 0.5, "B": 0.45}}
    ser = DG.log_series(log, kind="playoff", names={"A": "Alpha"}, league="NHL")
    assert {x["key"] for x in ser} == {"A", "B"} and next(x for x in ser if x["key"] == "A")["name"] == "Alpha"
    s = DG.swing(ser, NOW)
    assert s["name"] == "Alpha" and s["delta"] == 0.3 and s["league"] == "NHL"


def test_hot_needs_no_pre_game_chance():
    """Team of the week reads results only (football keeps no forecast on a finished match); `winner` marks a draw."""
    games = [{"id": 1, "start": "2026-10-22T19:00:00Z", "status": "final", "home": "A", "away": "B", "hs": 2, "as": 0},
             {"id": 2, "start": "2026-10-19T19:00:00Z", "status": "final", "home": "C", "away": "A", "hs": 1, "as": 1, "winner": "draw"},
             {"id": 3, "start": "2026-10-18T19:00:00Z", "status": "final", "home": "A", "away": "D", "hs": 3, "as": 1}]
    h = DG.hot(games, NOW)
    assert (h["key"], h["w"], h["d"], h["gp"], h["margin"]) == ("A", 2, 1, 3, 4.0)
    assert DG.record(games, NOW) is None and DG.upset(games, NOW) is None
