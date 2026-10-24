"""oddsmarkets/nfl/analytics/race.py: the Gridiron's league block and race log, on a small synthetic season (no network,
no models)."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.nfl.analytics import race as RC

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
TEAMS = {"AAA": ("AFC", "AFC East"), "BBB": ("AFC", "AFC East"), "CCC": ("AFC", "AFC West"), "DDD": ("AFC", "AFC West"),
         "EEE": ("NFC", "NFC East"), "FFF": ("NFC", "NFC East"), "GGG": ("NFC", "NFC West"), "HHH": ("NFC", "NFC West")}


def _card(gid, ko, home, away, hs=None, as_=None, ph=0.5):
    return {"game_id": gid, "week": 1, "gtype": "REG", "kickoff": ko, "home": home, "away": away, "hs": hs, "as": as_,
            "status": "final" if hs is not None else "scheduled", "model": {"p_home": ph}}


CARDS = [
    _card("w1a", "2026-09-10T00:20:00Z", "AAA", "BBB", 27, 20), _card("w1b", "2026-09-13T17:00:00Z", "CCC", "DDD", 10, 31),
    _card("w1c", "2026-09-13T17:00:00Z", "EEE", "FFF", 24, 23), _card("w1d", "2026-09-13T20:00:00Z", "GGG", "HHH", 3, 30),
    _card("w7a", "2026-10-19T17:00:00Z", "BBB", "AAA", 17, 24), _card("w7b", "2026-10-19T17:00:00Z", "DDD", "CCC", 20, 21),
    _card("w8a", "2026-10-25T17:00:00Z", "AAA", "CCC", ph=0.6), _card("w8b", "2026-10-25T17:00:00Z", "EEE", "GGG", ph=0.55),
    _card("w8c", "2026-10-26T00:20:00Z", "BBB", "DDD", ph=0.4), _card("w8d", "2026-10-26T17:00:00Z", "FFF", "HHH", ph=0.5),
]
P = {"AAA": (0.95, 0.20), "BBB": (0.30, 0.01), "CCC": (0.45, 0.03), "DDD": (0.80, 0.10), "EEE": (0.70, 0.12),
     "FFF": (0.40, 0.02), "GGG": (0.02, 0.0), "HHH": (0.60, 0.08)}
NEXT = {"AAA": "w8a", "CCC": "w8a", "EEE": "w8b", "GGG": "w8b", "BBB": "w8c", "DDD": "w8c", "FFF": "w8d", "HHH": "w8d"}


def _season():
    rows, sim, ratings = {}, {}, {}
    for i, (t, (c, d)) in enumerate(TEAMS.items()):
        w = 6 - i % 4
        rows.setdefault(d, {"division": d, "conference": c, "teams": []})["teams"].append(
            {"team": t, "w": w, "l": 6 - w, "t": 0, "pf": 150 + 10 * w, "pa": 150 - 5 * w, "sos": 0.5 * i - 1, "sos_left": 2 - 0.4 * i,
             "games_left": 11, "rating": 4 - i})
        p, sb = P[t]
        sim[t] = {"p_playoffs": p, "p_div": p / 2, "p_sb": sb, "magic": {"playoffs": 9 if i == 0 else 14}, "tragic": {"playoffs": 13},
                  "clinched": {"playoffs": False}, "eliminated": {"playoffs": False},
                  "next_game": {"game_id": NEXT[t], "week": 8, "opp": "x", "home": True, "p_win": 0.5,
                                "if_win": {"p_playoffs": min(1, p + 0.1)}, "if_loss": {"p_playoffs": max(0, p - 0.1)}}}
        ratings[t] = {"values": {"rating": 4 - i, "off_rating": 2 - i / 2, "def_rating": 2 - i / 2}}
    return {"ok": True, "season": 2026, "phase": "regular", "standings": list(rows.values()), "sim": {"ok": True, "teams": sim},
            "ratings": ratings}


def _teams():
    out = {}
    for i, t in enumerate(TEAMS):
        out[t] = {"values": {"off_epa": 0.1 - 0.03 * i, "def_epa": -0.05 + 0.02 * ((i * 3) % 8), "off_pass_epa": 0.2 - 0.01 * i,
                             "off_rush_epa": -0.05 + 0.01 * ((i * 5) % 8), "st_epa_g": (i % 3) - 1.0, "sack_rate_def": 0.04 + 0.005 * i,
                             "ed_pass_rate": 0.45 + 0.02 * i, "pressure_rate_def": None}}
    return {"ok": True, "teams": out}


def test_block_race_and_profile():
    blk, log = RC.build(2026, _season(), _teams(), CARDS, None, NOW)
    assert blk["v"] == 1 and [m["key"] for m in blk["metrics"]] == ["p_playoffs", "p_div", "p_sb"]
    assert log["2026"]["p_playoffs"]["2026-10-24"]["AAA"] == 0.95 and blk["history"]["live_from"] == "2026-10-24"
    # magic numbers only within reach (games left 11): 9 shown, 14 not; wins
    assert blk["race"]["AAA"]["magic"] == 9 and "magic" not in blk["race"]["BBB"] and blk["race"]["AAA"]["unit"] == "wins"
    assert blk["race"]["AAA"]["sos"][1] == 1                     # the hardest schedule left (sos_left ranked)
    # pressure is null everywhere: the sack rate carries the pass-rush chip; the empty metric is dropped
    ids = [m["id"] for m in blk["profile"]["metrics"]]
    assert "pressure_rate_def" not in ids and "sack_rate_def" in ids
    assert ["Best pass rush", "+"] in blk["teams"]["HHH"]["chips"]
    assert all(len(x.get("chips") or []) <= 4 for x in blk["teams"].values())
    # the games that matter: measured swings on each team's next game
    assert blk["games"][0]["swing"] == 0.4 and set(blk["games"][0]["sides"]) <= set(TEAMS)
    assert [t["key"] for t in blk["tiers"]][:1] == ["contend"] and blk["quad"]["x"] == "off_epa"
    lk = blk["teams"]["AAA"]["luck"]
    assert lk["close"] == [2, 0] and blk["notes"]["close"].startswith("one-score")


def test_weekly_movers_name_the_game():
    seas = {"2026": {"p_playoffs": {"2026-10-17": {t: max(0.0, P[t][0] - (0.2 if t == "AAA" else 0.0)) for t in TEAMS}}}}
    blk, _ = RC.build(2026, _season(), _teams(), CARDS, seas, NOW)
    up = blk["movers"]["up"][0]
    assert up["team"] == "AAA" and up["why"][0] == "Beat BBB 24-17"


def test_rebuild_days_and_backfill():
    assert RC.rebuild_days(CARDS, "2026-10-24")[:3] == ["2026-09-10", "2026-09-15", "2026-09-22"]
    assert RC.rebuild_days(CARDS, "2026-10-24")[-1] == "2026-10-20"
    calls = []

    def fake(day):
        calls.append(day)
        return {"p_playoffs": {"AAA": 0.5}, "p_div": {"AAA": 0.3}, "p_sb": {"AAA": 0.05}}
    blk, log = RC.build(2026, _season(), _teams(), CARDS, None, NOW, run_asof=fake, budget_s=60)
    assert calls == RC.rebuild_days(CARDS, "2026-10-24")
    meta = log["2026"]["_meta"]
    assert meta["rebuilt"] == calls and meta["n"] == RC.REBUILD_N and blk["history"]["first"] == "2026-09-10"
    # a second build rebuilds nothing more
    calls.clear()
    RC.build(2026, _season(), _teams(), CARDS, log, NOW, run_asof=fake)
    assert calls == []
