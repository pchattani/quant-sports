"""oddsmarkets/baseball/analytics/performers.py: the Bullpen standings page's top and bottom performers."""
from oddsmarkets.baseball.analytics import performers as PF

POS = ["C", "1B", "2B", "3B", "SS", "CF", "LF", "RF", "DH"]


def _hitters(team_games=162):
    P = {}
    for i in range(45):
        P[str(i)] = {"name": f"H{i}", "team": str(100 + i % 6), "pos": POS[i % 9], "pa": 150 + 10 * i, "qualified": i > 40,
                     "values": {"war": i / 10 - 1, "war_600": i / 20, "xwoba_n": 0.25 + i / 1000, "woba": 0.3, "hr": i, "k_pct": 0.3 - i / 500,
                                "bb_pct": 0.08, "barrel_pct": 0.05, "hard_pct": 0.4, "chase_pct": 0.3 - i / 1000}}
    return {"ok": True, "team_games": team_games, "players": P, "updated_at": "2026-10-19T00:00:00Z"}


def _pitchers():
    P = {}
    for i in range(40):
        role = "SP" if i % 2 else "RP"
        P[str(1000 + i)] = {"name": f"P{i}", "team": str(100 + i % 6), "role": role, "bf": 100 + 15 * i, "qualified": False,
                            "values": {"war": i / 10, "xwoba_n": 0.35 - i / 1000, "k_pct": 0.2 + i / 400, "bb_pct": 0.08, "xfip": 4.5 - i / 20,
                                       "csw_pct": 0.28, "stuff_plus": 90 + i, "k_bb_pct": 0.1 + i / 500, "whiff_pct": 0.25}}
    return {"ok": True, "team_games": 162, "players": P}


def test_spec_minimums_positions_and_pitchers():
    doc = PF.build(_hitters(), _pitchers(), "mlb", "2026")
    v = {x["key"]: x for x in doc["views"]}
    assert list(v) == ["all", "c", "1b", "2b", "3b", "ss", "cf", "of", "dh", "sp", "rp"]
    # 200 PA over a full season, not the catalogue's batting-title flag: pa >= 200 is i >= 5
    assert v["all"]["n"] == 40 and v["of"]["n"] == sum(1 for i in range(5, 45) if POS[i % 9] in ("LF", "RF"))
    assert v["all"]["metrics"][0]["key"] == "war" and v["all"]["metrics"][0]["ours"]
    assert "hr" in [m["key"] for m in v["all"]["metrics"]] and "hr" not in [m["key"] for m in v["c"]["metrics"]]
    k = next(m for m in v["all"]["metrics"] if m["key"] == "k_pct")
    assert k["dir"] == "lower" and k["top"][0][1] == "H44"
    # starters 300 batters faced (odd i, 100 + 15 i >= 300: i >= 14), relievers 120 (even i >= 2)
    assert v["sp"]["n"] == len([i for i in range(14, 40) if i % 2]) and v["rp"]["n"] == len([i for i in range(2, 40, 2)])
    assert v["sp"]["kind"] == "pitcher" and "kind" not in v["all"]
    xw = next(m for m in v["sp"]["metrics"] if m["key"] == "xwoba_n")
    assert xw["dir"] == "lower" and xw["top"][0][1] == "P39"


def test_prorated_in_season_and_empty():
    doc = PF.build(_hitters(team_games=81), None, "aaa", 2026)
    assert doc["views"][0]["n"] == 45 and "100 plate appearances" in doc["views"][0]["min"]
    assert PF.build(None, None, "mlb", 2026) is None
    assert PF.build({"ok": False}, {"ok": True, "players": {}}, "mlb", 2026) is None
