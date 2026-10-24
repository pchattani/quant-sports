"""oddsmarkets/baseball/analytics/race.py: the Bullpen's league block and race log, on synthetic payloads (no store, no
network): the rebuild schedule, the current chances, movers, the games that matter, chips, luck, tiers, Triple-A."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.baseball.analytics import race as RC
from oddsmarkets.common import league as LG

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)
TEAMS = {"1": ("AL", "AL East", "AAA"), "2": ("AL", "AL East", "BBB"), "3": ("AL", "AL West", "CCC"),
         "4": ("NL", "NL East", "DDD"), "5": ("NL", "NL East", "EEE"), "6": ("NL", "NL West", "FFF")}


def _cards():
    cards, k = [], 0
    days = ["2026-03-26", "2026-04-15", "2026-06-01", "2026-09-27"]
    pairs = [("1", "2"), ("3", "1"), ("4", "5"), ("6", "4"), ("2", "3"), ("5", "6")]
    for d in days:
        for h, a in pairs:
            k += 1
            cards.append({"gpk": str(k), "date": d, "start": d + "T23:00:00Z", "status": "final", "gtype": "R", "home": h, "away": a,
                          "hs": 5 if h in ("1", "4") else 3, "as": 2 if h in ("1", "4") else 4})
    # the postseason: a final on the 20th, the World Series game 1 on the 23rd, game 2 to come
    cards.append({"gpk": "90", "date": "2026-10-03", "start": "2026-10-03T23:00:00Z", "status": "final", "gtype": "D", "home": "1", "away": "3", "hs": 4, "as": 3})
    cards.append({"gpk": "91", "date": "2026-10-23", "start": "2026-10-24T00:00:00Z", "status": "final", "gtype": "W", "home": "4", "away": "1", "hs": 3, "as": 2})
    cards.append({"gpk": "92", "date": "2026-10-24", "start": "2026-10-25T00:00:00Z", "status": "pre", "gtype": "W", "home": "4", "away": "1", "hs": None, "as": None,
                  "model": {"p_home": 0.55}})
    return cards


def _season(level="mlb"):
    st = {}
    for t, (lg, dv, ab) in TEAMS.items():
        alive = t in ("1", "4")
        st.setdefault(dv, []).append({"tid": t, "abbr": ab, "league": lg, "division": dv, "w": 90 - int(t), "l": 72 + int(t), "rating": 1.0 - 0.3 * int(t),
                                      "off": 0.5 - 0.1 * int(t), "def": 0.1, "pit": 0.4 - 0.1 * int(t), "pythag_w": 85.0,
                                      "div_winner": t in ("1", "3", "4", "6"), "p_postseason": 1.0 if t in ("1", "3", "4", "6") else 0.0,
                                      "p_ws": (0.6 if t == "4" else 0.4) if alive else 0.0,
                                      "next": {"p_win": 0.5, "if_win": {"p_ws": 0.7 if t == "4" else 0.5}, "if_loss": {"p_ws": 0.45 if t == "4" else 0.3}} if alive else None})
    return {"ok": True, "level": level, "season": 2026, "phase": "postseason", "standings": st,
            "postseason": {"teams": {"1": {"p_ws": 0.4}, "4": {"p_ws": 0.6}},
                           "series": [{"round": "WS", "teams": ["4", "1"], "done": False, "next": {"gpk": "92"}}]}}


def _teams():
    v = {}
    for i, t in enumerate(TEAMS):
        v[t] = {"values": {"rating": 1.0 - 0.3 * int(t), "woba": 0.300 + 0.01 * i, "sp_ra9": 3.5 + 0.2 * i, "rp_ra9": 4.5 - 0.2 * i, "war_sp": 12.0 - i, "war_rp": 3.0 + 0.5 * i,
                           "def_rpg": 0.1 * (3 - i), "off_rpg": 0.2 - 0.05 * i, "pit_rpg": 0.1 * i, "baseruns_w": 80.0 + i, "barrel_pct": 0.08}}
    return {"ok": True, "teams": v}


def test_rebuild_schedule_weekly_then_through_the_postseason():
    ds = RC.rebuild_schedule(_cards(), "2026-10-24")
    assert ds[0] == "2026-04-02" and "2026-09-28" in ds                       # a week in, and the day after the last game
    assert "2026-10-03" in ds and "2026-10-05" in ds and ds[-1] == "2026-10-23"  # every two days from the first postseason day
    assert all(d < "2026-10-24" for d in ds)
    assert RC.rebuild_schedule([], "2026-10-24") == []


def test_the_mlb_block_and_race_log():
    seen = []

    def run(day):
        seen.append(day)
        return {"p_postseason": {t: 0.5 for t in TEAMS}, "p_div": {t: 0.3 for t in TEAMS}, "p_ws": {t: 0.1 for t in TEAMS}}
    blk, log = RC.build("mlb", 2026, _season(), _teams(), _cards(), None, NOW, run_asof=run)
    s = log["2026"]
    assert s[LG.META]["live_from"] == "2026-10-24" and seen and set(s[LG.META]["rebuilt"]) == set(seen)
    assert s["p_ws"]["2026-10-24"] == {"1": 0.4, "2": 0.0, "3": 0.0, "4": 0.6, "5": 0.0, "6": 0.0}
    assert s["p_div"]["2026-10-24"]["3"] == 1.0 and s["p_div"]["2026-10-24"]["2"] == 0.0     # the division from div_winner
    assert [m["key"] for m in blk["metrics"]] == ["p_postseason", "p_div", "p_ws"] and blk["notes"]["metric"] == "p_ws"
    assert [t["key"] for t in blk["tiers"]] == ["alive", "out_po", "missed"] and blk["tiers"][0]["teams"] == ["4", "1"]
    g = blk["games"][0]
    assert g["id"] == "92" and g["sides"] == {"4": [0.7, 0.45], "1": [0.5, 0.3]} and g["swing"] == 0.45
    assert blk["race"]["4"]["status"] == "clinched" and blk["race"]["2"]["status"] == "out"
    assert blk["race"]["4"]["next"]["opp"] == "1" and blk["race"]["4"]["next"]["home"] is True
    # chips on the rotation / bullpen / lineup dimensions
    names = {c[0] for t in blk["teams"].values() for c in t.get("chips") or []}
    assert any("rotation" in n for n in names) and any("lineup" in n for n in names)
    assert not any("power" in n for n in names)                    # every club at the same barrel rate: no ranking, no chip
    assert blk["teams"]["1"]["luck"]["x"] == 80.0 and blk["notes"]["luck_basis"].startswith("wins against BaseRuns")
    assert blk["quad"]["y"] == "prev_rpg" and blk["teams"]["1"]["vals"]["prev_rpg"] == 0.3
    # a second build the same day keeps the history and rebuilds nothing new
    seen.clear()
    blk2, log2 = RC.build("mlb", 2026, _season(), _teams(), _cards(), log, NOW, run_asof=run)
    assert seen == [] and log2["2026"]["p_ws"] == s["p_ws"]


def test_triple_a_has_no_chances_but_keeps_the_profile():
    sp = _season("aaa")
    blk, log = RC.build("aaa", 2026, sp, _teams(), _cards(), None, NOW, run_asof=None)
    assert blk["metrics"] == [] and blk["tiers"] == [] and blk["current"] == {} and log == {}
    assert blk["teams"]["1"]["pct"] and "no_sim" in blk["notes"]
