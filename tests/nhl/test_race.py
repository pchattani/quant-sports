"""oddsmarkets/nhl/analytics/race.py: the Rink's league block and race log on a small synthetic season (no network, no
models)."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.nhl.analytics import race as RC

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
TEAMS = {"AAA": ("Eastern", "Atlantic"), "BBB": ("Eastern", "Atlantic"), "CCC": ("Eastern", "Metropolitan"),
         "DDD": ("Eastern", "Metropolitan"), "EEE": ("Western", "Pacific"), "FFF": ("Western", "Pacific")}


def _card(gid, day, home, away, hs=None, as_=None, ot=False, ph=0.5):
    return {"game_id": gid, "date": day, "start": day + "T23:00:00Z", "type": "REG", "home": home, "away": away, "hs": hs, "as": as_,
            "ot": ot, "so": False, "status": "final" if hs is not None else "scheduled", "model": {"p_home": ph}}


CARDS = [
    _card("1", "2026-10-01", "AAA", "BBB", 4, 1), _card("2", "2026-10-02", "CCC", "DDD", 2, 3, ot=True),
    _card("3", "2026-10-19", "AAA", "CCC", 3, 2), _card("4", "2026-10-20", "BBB", "DDD", 1, 5), _card("5", "2026-10-21", "EEE", "FFF", 2, 1),
    _card("6", "2026-10-25", "AAA", "DDD", ph=0.6), _card("7", "2026-10-25", "BBB", "CCC", ph=0.45), _card("8", "2026-10-26", "EEE", "FFF", ph=0.5),
]
P = {"AAA": (0.9, 0.2), "BBB": (0.3, 0.01), "CCC": (0.5, 0.04), "DDD": (0.7, 0.08), "EEE": (0.6, 0.1), "FFF": (0.2, 0.01)}
NEXT = {"AAA": "6", "DDD": "6", "BBB": "7", "CCC": "7", "EEE": "8", "FFF": "8"}


def _season():
    rows, sim, ratings = [], {}, {}
    for i, (t, (c, d)) in enumerate(TEAMS.items()):
        gp = 10 + i % 2
        rows.append({"team": t, "conference": c, "division": d, "gp": gp, "w": 6 - i, "l": 3 + i // 2, "otl": 1, "pts": 2 * (6 - i) + 1,
                     "gf": 30 - i, "ga": 25 + i, "rating": 0.4 - 0.15 * i})
        p, cup = P[t]
        sim[t] = {"p_playoffs": p, "p_div": p / 2, "p_cup": cup, "magic": {"playoffs": 60 if i == 0 else 150}, "tragic": {"playoffs": 140},
                  "clinched": {"playoffs": False}, "eliminated": {"playoffs": False},
                  "next_game": {"game_id": NEXT[t], "date": "2026-10-25", "opp": "x", "home": True, "p_win": 0.5,
                                "if_win": {"p_playoffs": min(1, p + 0.05)}, "if_loss": {"p_playoffs": max(0, p - 0.05)}}}
        ratings[t] = {"units": {"rating": 0.4 - 0.15 * i, "off5": 2.4 + 0.1 * ((i * 3) % 6), "def5": 2.2 + 0.1 * i, "pp": 6 + i, "pk": 7 - 0.3 * i,
                                "goalie": 0.5 - 0.2 * ((i * 5) % 6), "xgf_pct5": 0.55 - 0.02 * i, "cf_pct5": 0.52 - 0.01 * ((i * 2) % 6),
                                "xgf_g": 3.0 - 0.1 * i, "xga_g": 2.6 + 0.05 * i, "pp_pct": 0.2, "pk_pct": 0.8}}
    return {"ok": True, "season": 20262027, "phase": "regular", "season_games": 84,
            "standings": {"rows": rows, "divisions": []}, "sim": {"ok": True, "teams": sim}, "ratings": ratings,
            "teams": {t: {"conference": c, "division": d} for t, (c, d) in TEAMS.items()}}


def test_block_race_and_profile():
    blk, log = RC.build(20262027, _season(), None, CARDS, None, NOW)
    assert blk["v"] == 1 and [m["key"] for m in blk["metrics"]] == ["p_playoffs", "p_div", "p_cup"]
    assert log["20262027"]["p_playoffs"]["2026-10-24"]["AAA"] == 0.9 and blk["history"]["live_from"] == "2026-10-24"
    assert blk["current"]["p_cup"]["AAA"] == 0.2
    # the magic number shows only once within reach (at most a point a game left: 74 games left here)
    assert blk["race"]["AAA"]["magic"] == 60 and "magic" not in blk["race"]["BBB"] and blk["race"]["AAA"]["unit"] == "points"
    # games that matter: the next-game swings, both sides summed
    assert [g["id"] for g in blk["games"]] == ["6", "7", "8"] and blk["games"][0]["swing"] == 0.2
    # schedule strength ranked, the profile ranked on the spec's set, chips in words
    assert set(blk["race"]["AAA"]["sos"][1:]) and blk["teams"]["AAA"]["pct"]["rating"] == 100
    assert blk["teams"]["AAA"]["vals"]["def5"] == 2.2 and blk["quad"]["flipY"] is True
    assert all(isinstance(c, list) and len(c) == 2 for t in blk["teams"].values() for c in t.get("chips", []))
    assert {x["key"] for x in blk["tiers"]} <= {"contend", "solid", "bubble", "long", "rebuild"}


def test_rebuild_fills_the_days_before_live_tracking_inside_the_budget():
    seen = []

    def run(day):
        seen.append(day)
        return {"p_playoffs": {"AAA": 0.5}, "p_div": {"AAA": 0.2}, "p_cup": {"AAA": 0.05}}
    blk, log = RC.build(20262027, _season(), None, CARDS, None, NOW, run_asof=run)
    s = log["20262027"]
    assert seen[0] == "2026-10-01" and seen[-1] < "2026-10-24" and s["_meta"]["rebuilt"] == seen
    assert blk["history"]["rebuilt"] == seen and blk["history"]["first"] == "2026-10-01"
    # a second build finds nothing left to rebuild
    seen.clear()
    RC.build(20262027, _season(), None, CARDS, log, NOW, run_asof=run)
    assert seen == []
    # movers now have a week-old snapshot to compare against, with reasons
    mv = blk["movers"]
    assert mv and mv["metric"] == "p_playoffs" and all(r.get("why") for r in mv["up"] + mv["down"])


def test_no_standings_no_block():
    blk, log = RC.build(20262027, {"ok": True, "standings": {"rows": []}}, None, [], {"x": 1}, NOW)
    assert blk is None and log == {"x": 1}
