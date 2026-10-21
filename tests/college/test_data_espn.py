"""sources/espn.py parsers on trimmed real ESPN answers (fetched 19 Oct 2026; no network)."""
import json
from pathlib import Path

from oddsmarkets.college import store as st
from oddsmarkets.college.sources import espn

FIX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_compact_event_basketball_ncaa_seeds_and_stats():
    d = fx("mbb_scoreboard.json")
    g = espn.compact_event("mbb", d["events"][0])
    assert g["stype"] == "ncaa" and g["round"] == "Round of 64" and g["region"] == "West"
    assert g["seeds"] == {"home": 1, "away": 16} and g["ranks"] == {"home": None, "away": None}
    assert g["status"] == "post" and g["hs"] == 92 and g["as"] == 58 and g["neutral"] is True
    ts = g["team_stats"][g["home"]]
    assert ts["pts"] == 92 and ts["fgm"] == 32 and ts["fga"] == 60 and set(ts) == {"fgm", "fga", "tpm", "tpa", "ftm", "fta", "reb", "ast", "pts"}
    reg = espn.compact_event("mbb", d["events"][2])
    assert reg["stype"] == "reg" and reg["seeds"] is None
    assert reg["ranks"]["away"] == 3                      # KU ranked 3rd (curatedRank), OSU unranked (99 -> None)
    assert reg["ranks"]["home"] is None
    for k in ("id", "date", "status", "stype", "round", "region", "note", "week", "neutral", "conf_game", "home", "away", "hs", "as",
              "periods", "line", "ranks", "seeds", "team_stats", "box", "odds", "predictor", "venue", "attendance", "has_pbp", "summary"):
        assert k in g


def test_compact_event_football_cfp_and_bowl():
    d = fx("cfb_scoreboard.json")
    by = {e["id"]: espn.compact_event("cfb", e) for e in d["events"]}
    assert by["401778319"]["stype"] == "bowl" and by["401778319"]["week"] == 1
    assert by["401779840"]["stype"] == "cfp" and by["401779840"]["round"] == "First Round"
    assert by["401779840"]["seeds"] == {"home": 8, "away": 9}
    assert by["401769076"]["round"] == "National Championship"
    assert by["401769072"]["round"] == "Quarterfinal"
    cal = espn.football_calendar(d)
    assert [2, 1, "Week 1", "2025-08-23", "2025-09-02"] in cal
    assert any(x[0] == 3 and x[1] == 999 for x in cal)


def test_compact_game_basketball_box():
    raw = fx("mbb_summary_2026.json")
    g = espn.compact_game("mbb", raw)
    assert g["summary"] is True and g["stype"] == "ncaa" and g["seeds"] == {"home": 1, "away": 16}
    box = g["box"][g["away"]]
    assert all(len(r) == len(st.BOX_COLS) for r in box["players"])
    assert set(box["team"]) == set(st.TEAM_BOX_KEYS)
    pts = sum(r[3] or 0 for r in box["players"])
    assert pts == g["as"] == 58
    assert g["odds"]["source"] == "pickcenter" and g["odds"]["spread_home"] == -30.5 and g["odds"]["open_spread_home"] == -29.5
    assert g["odds"]["total"] == 147.5 and g["odds"]["open_total"] == 150.5
    assert g["venue"]["city"] == "San Diego"
    pb = espn.compact_pbp_bb(raw)
    assert pb is not None and len(pb["plays"]) == 70 and len(pb["plays"][0]) == len(st.PBP_COLS)


def test_compact_game_basketball_2005_no_plays():
    raw = fx("mbb_summary_2005.json")
    g = espn.compact_game("mbb", raw)
    assert g["has_pbp"] is False and espn.compact_pbp_bb(raw) is None
    assert g["region"] == "Syracuse" and g["seeds"] == {"home": 7, "away": 10}
    assert g["odds"] is None
    assert all(len(r) == 17 for b in g["box"].values() for r in b["players"])


def test_compact_game_football_box_and_plays():
    raw = fx("cfb_summary_2025.json")
    g = espn.compact_game("cfb", raw)
    assert g["stype"] == "bowl" and g["hs"] == 25 and g["as"] == 21
    t = g["box"]["59"]["team"]
    assert t["pass_cmp"] == 22 and t["pass_att"] == 40 and t["penalties"] == 7 and t["penalty_yards"] == 49
    assert t["third_conv"] == 4 and t["third_att"] == 12 and t["possession_s"] == 28 * 60 + 49
    assert set(t) == set(st.FB_TEAM_KEYS)
    passing = g["box"]["59"]["players"]["passing"]
    assert passing["cols"][:3] == ["cmp", "att", "passing_yards"] and passing["rows"][0][1:4] == [22, 40, 254]
    kicking = g["box"]["59"]["players"]["kicking"]
    assert kicking["cols"][:2] == ["fgm", "fga"] and "xpm" in kicking["cols"]
    assert g["odds"]["spread_home"] == -3.5 and g["odds"]["ml_home"] == -180
    pl = espn.compact_plays_cfb(raw)
    assert len(pl["drives"]) == 4 and all(len(r) == len(st.DRIVE_COLS) for r in pl["drives"])
    assert all(len(r) == len(st.PLAY_COLS) for r in pl["plays"])
    cols = st.PLAY_COLS
    p = next(r for r in pl["plays"] if r[cols.index("type_id")] == 24)       # a pass reception
    assert p[cols.index("offense")] in ("59", "252") and p[cols.index("defense")] in ("59", "252")
    assert p[cols.index("offense")] != p[cols.index("defense")]
    assert any(r[cols.index("wp_home")] is not None for r in pl["plays"])
    assert pl["types"]["24"] == "Pass Reception"


def test_compact_game_football_2015_without_pickcenter_book():
    raw = fx("cfb_summary_2015.json")
    g = espn.compact_game("cfb", raw)
    assert g["odds"] is None                     # only "consensus" in pickcenter: the core odds call fills it
    assert espn.compact_plays_cfb(raw)["plays"]


def test_parse_odds_draftkings_close():
    o = espn.parse_odds(fx("odds_cfb_2025.json"))
    assert o["provider"] == "DraftKings" and o["source"] == "core"
    assert o["spread_home"] == -3.5 and o["open_spread_home"] == -2.5
    assert o["total"] == 55.5 and o["ml_home"] == -180 and o["ml_away"] == 150 and o["n_books"] == 1


def test_parse_odds_multi_book_home_relative():
    # 2016: away Kansas favoured by 9; ESPN's single spread is home-relative (+9 for the home underdog)
    o = espn.parse_odds(fx("odds_mbb_2016.json"))
    assert o["spread_home"] == 9.0 and o["total"] == 142.0
    assert o["n_books"] == 6                     # Opening, numberfire, teamrankings are not books
    assert o["open_spread_home"] == 9.5
    assert espn.parse_odds(fx("odds_mbb_2005.json")) is None


def test_signed_spread_flips_on_favourite_flags():
    assert espn._signed_spread(7.0, {"favorite": True}, {"favorite": False}) == -7.0
    assert espn._signed_spread(-7.0, {"favorite": False}, {"favorite": True}) == 7.0
    assert espn._signed_spread(-3.0, {"favorite": True}, {}) == -3.0


def test_parse_standings_membership_and_divisions():
    confs, members = espn.parse_standings("cfb", fx("cfb_standings_2024.json"))
    assert confs["8"]["short"] == "SEC" and confs["8"]["fbs"] is True
    assert members["251"] == {"conference": "8", "division": None}
    assert set(confs["37"]["divisions"]) == {"167", "168"}
    assert members["276"]["conference"] == "37" and members["276"]["division"] == "167"


def test_ranking_parse_and_week_labels():
    raw = fx("core_ranking_cfp_2024w15.json")
    rows = espn.parse_ranking(raw)
    assert rows[0][:2] == [1, "2483"] and len(rows) == 5
    assert espn.week_label("https://x/seasons/2024/types/2/weeks/15/rankings/21", raw) == "15"
    assert espn.week_label("https://x/seasons/2024/types/3/weeks/1/rankings/1", {"occurrence": {"last": True}}) == "final"
    assert espn.week_label("https://x/seasons/2024/types/1/weeks/1/rankings/1", {}) == "pre"


def test_roster_player_records():
    d = fx("cfb_roster.json")
    a = d["athletes"][0]["items"][0]
    p = espn.player_rec("cfb", a, "333")
    assert p["id"] and p["class"] in ("FR", "SO", "JR", "SR", "GR") and p["height_in"] and p["weight_lb"]
    assert p["hometown"] and p["teams"] == ["333"] and p["pool"] in ("QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "K", "P", "ATH")


def test_players_from_summary():
    ps = espn.players_from_summary("mbb", fx("mbb_summary_2026.json"))
    assert len(ps) > 15 and all(p["teams"] for p in ps.values())
    assert any(p["pos"] == "F" for p in ps.values())


def test_parse_odds_consensus_only_2013():
    # 2012-2013 core odds hold only consensus / numberfire / teamrankings: the consensus line is used
    o = espn.parse_odds(fx("odds_cfb_2013.json"))
    assert o["provider"] == "consensus" and o["n_books"] == 0 and o["source"] == "core"
    assert o["spread_home"] == 10.0            # home underdog by 10 (away favourite flag)
