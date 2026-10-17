"""Builder A (data layer): Savant chunking and typing, Stats API records, the Retrosheet parser, the Chadwick
crosswalk, ESPN lines and ESPN -> gamePk mapping, stores. Recorded fixtures only; no network."""
from __future__ import annotations

import io
import csv
from datetime import date

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball import canon
from oddsmarkets.baseball import store as st
from oddsmarkets.baseball.sources import chadwick, espn, retrosheet as rs, savant, statsapi

from .conftest import fixture_path, load_fixture_json, load_fixture_text


# ── Savant: the 25,000-row splitter ─────────────────────────────────────────

class FakeSavant:
    """Answers like Savant: `per_day` rows a day, silently capped at CAP; a day in `heavy` has more than CAP
    rows unless a team filter is given."""

    def __init__(self, per_day=9000, heavy=(), team_rows=40):
        self.per_day, self.heavy, self.team_rows = per_day, set(heavy), team_rows
        self.calls: list[tuple[str, str, str | None]] = []
        self.header = load_fixture_text("savant_2026-09-27.csv").splitlines()[0]

    def get_text(self, url, params):
        lo, hi = date.fromisoformat(params["game_date_gt"]), date.fromisoformat(params["game_date_lt"])
        team = (params.get("hfTeam") or "").rstrip("|") or None
        self.calls.append((str(lo), str(hi), team))
        rows = []
        d = hi
        while d >= lo:                                    # newest first, like Savant
            n = self.team_rows if team else (savant.CAP + 500 if str(d) in self.heavy else self.per_day)
            for k in range(n):
                row = dict.fromkeys(savant.COLUMNS, "")
                row.update(pitch_type="FF", game_date=str(d), release_speed="95.1", batter="1", pitcher="2",
                           game_type="R", home_team="NYY", away_team="BOS", game_pk=str(700000 + d.toordinal() % 1000),
                           at_bat_number=str((hash(team) % 50 if team else 0) * 1000 + k), pitch_number="1")
                rows.append(",".join(f'"{row[c]}"' if row[c] else "" for c in savant.COLUMNS))
            d = date.fromordinal(d.toordinal() - 1)
        rows = rows[: savant.CAP]
        return "\n".join([self.header] + rows) + "\n"


def _fake_rows_ok():
    # the fake row layout must line up with the fixture's Savant header at game_pk / at_bat_number / pitch_number
    c = FakeSavant(per_day=1)
    df = savant.parse_csv(c.get_text(None, {"game_date_gt": "2026-06-01", "game_date_lt": "2026-06-01"}))
    return df.loc[0, "game_pk"], df.loc[0, "at_bat_number"], df.loc[0, "pitch_number"], df.loc[0, "home_team"]


def test_fake_rows_line_up_with_header():
    pk, ab, pn, home = _fake_rows_ok()
    assert pk.isdigit() and ab == "0" and pn == "1" and home == "NYY"


def test_range_under_cap_is_one_request():
    c = FakeSavant(per_day=4000)
    capped = []
    frames = savant.fetch_range(c, "mlb", date(2026, 6, 1), date(2026, 6, 3), capped=capped)
    assert len(c.calls) == 1 and capped == []
    assert sum(len(f) for f in frames) == 12000


def test_capped_range_is_split_until_every_answer_is_under_cap():
    c = FakeSavant(per_day=9000)                  # 4 days = 36,000 rows -> capped, 2 days = 18,000 fine
    capped = []
    frames = savant.fetch_range(c, "mlb", date(2026, 6, 1), date(2026, 6, 4), capped=capped)
    df = savant.typed(pd.concat(frames, ignore_index=True))
    assert len(df) == 36000
    assert c.calls[0] == ("2026-06-01", "2026-06-04", None)
    assert ("2026-06-01", "2026-06-02", None) in c.calls and ("2026-06-03", "2026-06-04", None) in c.calls
    assert len(capped) == 1 and capped[0][3] == savant.CAP
    assert sorted(df["game_date"].dt.strftime("%Y-%m-%d").unique()) == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04"]


def test_capped_single_day_splits_by_pitching_team():
    c = FakeSavant(per_day=3000, heavy={"2026-06-02"}, team_rows=40)
    capped = []
    frames = savant.fetch_range(c, "mlb", date(2026, 6, 2), date(2026, 6, 2), teams=["NYY", "BOS", "TOR"],
                                capped=capped)
    teams = sorted(t for (_, _, t) in c.calls if t)
    assert teams == ["BOS", "NYY", "TOR"]
    assert sum(len(f) for f in frames) == 3 * 40
    assert capped[0][:3] == ["2026-06-02", "2026-06-02", None]


def test_failed_request_returns_none():
    class Down:
        def get_text(self, url, params):
            return None
    assert savant.fetch_range(Down(), "mlb", date(2026, 6, 1), date(2026, 6, 1)) is None


def test_html_answer_is_not_a_csv():
    assert savant.parse_csv("<html>busy</html>") is None
    assert len(savant.parse_csv("")) == 0


def test_aaa_search_params():
    p = savant.search_params("aaa", "2026-09-19", "2026-09-19")
    assert p["minors"] == "true" and p["hfLevel"] == "AAA|" and p["hfGT"] == "R|F|D|L|W|C|"
    assert "minors" not in savant.search_params("mlb", "2026-09-19", "2026-09-19")
    assert savant.search_params("mlb", "2026-09-19", "2026-09-19", team="TOR")["hfTeam"] == "TOR|"


# ── Savant: typing and Parquet ──────────────────────────────────────────────
# The Savant and Stats API fixtures are synthetic (tests/baseball/fixtures/make_synthetic.py): Savant's and
# the Stats API's layouts with invented ids, names, game pks and values; raw MLBAM answers are never re-hosted.

def test_csv_typing_and_parquet_round_trip(bullpen_roots):
    raw = savant.parse_csv(load_fixture_text("savant_2026-09-27.csv"))
    assert len(raw) == 200 and len(raw.columns) == 119
    df = savant.typed(raw)
    assert list(df.columns) == savant.COLUMNS
    assert df["release_speed"].dtype == np.float32 and df["plate_x"].dtype == np.float32
    assert str(df["game_pk"].dtype) == "Int32" and str(df["on_1b"].dtype) == "Int32"
    assert isinstance(df["pitch_type"].dtype, pd.CategoricalDtype)
    assert str(df["game_date"].dtype).startswith("datetime64")
    assert df["arm_angle"].notna().any() and df["umpire"].isna().all()
    # a season that lacks a column (early Statcast) still has it, all null
    old = savant.typed(raw.drop(columns=["bat_speed", "arm_angle"]))
    assert old["bat_speed"].isna().all() and old["arm_angle"].dtype == np.float32

    savant.write_day("mlb", 2026, "2026-09-27", df)
    aaa = savant.typed(savant.parse_csv(load_fixture_text("savant_aaa_2026-09-19.csv")))
    aaa["new_savant_col"] = pd.Series(["x"] * len(aaa)).astype("category")       # an unknown new column
    savant.write_day("mlb", 2026, "2026-09-19", aaa)
    info = savant.compact("mlb", 2026)
    assert info["rows"] == 250 and info["days"] == 2
    assert "bat_speed" in info["columns_present"] and "umpire" not in info["columns_present"]
    back = savant.load_season("mlb", 2026)
    assert len(back) == 250 and "new_savant_col" in back.columns
    assert back["game_pk"].dtype == np.int32 and back["pitcher"].dtype == np.int32
    assert str(back["on_1b"].dtype) == "Int32" and back["release_speed"].dtype == np.float32
    assert isinstance(back["pitch_type"].dtype, pd.CategoricalDtype)
    one = back[back["game_date"] == pd.Timestamp("2026-09-27")]
    src = df.sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)
    one = one.sort_values(["game_pk", "at_bat_number", "pitch_number"]).reset_index(drop=True)
    assert np.allclose(src["plate_x"].astype(float), one["plate_x"].astype(float), equal_nan=True)
    cols = savant.load_season("mlb", 2026, columns=["pitcher", "batter"])
    assert list(cols.columns) == ["pitcher", "batter"]


def test_duplicate_pitches_from_overlapping_splits_are_dropped():
    raw = savant.parse_csv(load_fixture_text("savant_2026-09-27.csv"))
    both = pd.concat([raw, raw.head(50)], ignore_index=True)
    assert len(savant.typed(both)) == 200


# ── Stats API ───────────────────────────────────────────────────────────────

def _schedule_games():
    d = load_fixture_json("schedule.json")
    return [g for day in d["dates"] for g in day["games"]]


def test_compact_game_postseason_and_regular():
    by = {str(g["gamePk"]): statsapi.compact_game(g) for g in _schedule_games()}
    g = by["990841"]
    assert g["gtype"] == "F" and g["status"] == "final" and g["date"] == "2026-09-30"
    assert g["series"] == {"desc": "NL Wild Card Series", "game": 2, "of": 3}
    assert g["home"] == "144" and g["away"] == "143" and (g["hs"], g["as"]) == (3, 4)
    assert g["umpire_hp"] == "9500051" and g["weather"] == {"temp": 71, "wind": "7 mph, Out To CF", "cond": "Clear"}
    assert len(g["lineups"]["144"]) == 9 and len(g["lineups"]["143"]) == 9
    assert len(g["innings"]) == 10                                          # extra innings
    assert sum(x[0] for x in g["innings"]) == 4 and sum(x[1] for x in g["innings"]) == 3
    assert g["probables"]["home"] == "9500047"
    reg = by["990679"]
    assert reg["gtype"] == "R" and reg["series"] is None and reg["decisions"]["w"]
    assert by["990490"]["status"] == "cancelled"


def test_rescheduled_game_keeps_the_better_record():
    store = st.new_store("mlb", 2026)
    g = next(x for x in _schedule_games() if x["gamePk"] == 990679)
    statsapi.take_game(store, g, st.merge_game)
    old = dict(g, officialDate="2026-05-01", status={"abstractGameState": "Final", "detailedState": "Postponed"})
    assert statsapi.take_game(store, old, st.merge_game) is False          # the postponed listing never wins
    assert store["games"]["990679"]["status"] == "final"
    same_day = dict(g, status={"abstractGameState": "Final", "detailedState": "Postponed"})
    statsapi.take_game(store, same_day, st.merge_game)                     # same date: a real postponement
    assert store["games"]["990679"]["status"] == "postponed"


def test_merge_game_keeps_richer_fields():
    store = st.new_store("mlb", 2026)
    g = statsapi.compact_game(next(x for x in _schedule_games() if x["gamePk"] == 990841))
    st.merge_game(store, dict(g, lines={"ml": [-103, -117]}, has_statcast=True, abs={"home": {}}))
    st.merge_game(store, g)                                                # a rescan with no lines / ABS
    rec = store["games"]["990841"]
    assert rec["lines"] == {"ml": [-103, -117]} and rec["has_statcast"] is True and rec["abs"] == {"home": {}}


def test_feed_extras_abs_mound_visits_and_order():
    ex = statsapi.feed_extras(load_fixture_json("feed_post_990841.json"))
    assert ex["abs"]["away"] == {"won": 2, "lost": 2, "left": 0}
    assert ex["abs"]["home"] == {"won": 1, "lost": 1, "left": 1}
    assert set(ex["lineups"]) == {"144", "143"} and len(ex["lineups"]["144"]) == 9
    sched = statsapi.compact_game(next(x for x in _schedule_games() if x["gamePk"] == 990841))
    assert ex["lineups"] == sched["lineups"]                                # the feed's batting order is the game's
    reg = statsapi.feed_extras(load_fixture_json("feed_regular_990679.json"))
    assert reg["abs"]["home"]["won"] == 2 and reg["mound_visits"] == {"home": 1, "away": 4}


def test_weeks_newest_first():
    w = statsapi.weeks(date(2026, 3, 1), date(2026, 3, 20))
    assert w[0] == (date(2026, 3, 14), date(2026, 3, 20)) and w[-1][0] == date(2026, 3, 1)


# ── canon ───────────────────────────────────────────────────────────────────

def test_canon_relocations_and_renames():
    assert canon.team_name("114", 2021) == "Cleveland Indians" and canon.team_name("114", 2022) == "Cleveland Guardians"
    assert canon.team_name("133", 2024) == "Oakland Athletics" and canon.team_name("133", 2025) == "Athletics"
    assert canon.team_abbr("133", 2024) == "OAK" and canon.team_abbr("133", 2026) == "ATH"
    assert canon.team_name("146", 2011) == "Florida Marlins" and canon.retro_code("120", 2004) == "MON"
    assert canon.team_league("117", 2012) == "NL" and canon.team_league("117", 2013) == "AL"
    assert canon.team_league("158", 1997) == "AL" and canon.team_division("158", 2026) == "NL Central"
    assert canon.tid_from_retro("ANA") == "108" and canon.tid_from_retro("ATH") == "133" and canon.tid_from_retro("WS1") == "142"
    assert canon.tid_from_espn("4") == "145" and canon.tid_from_abbr("AZ") == "109" and canon.tid_from_abbr("ARI") == "109"
    assert len(canon.TEAMS) == 30 and len(canon.ESPN_TO_TID) == 30
    assert canon.game_status("Final", "Postponed") == "postponed" and canon.game_status("Final", "Final") == "final"


# ── Retrosheet parser ───────────────────────────────────────────────────────

SYNTH = """id,TST202504010
version,2
info,visteam,VIS
info,hometeam,TST
info,date,2025/04/01
info,number,0
start,v1,"V One",0,1,8
start,v2,"V Two",0,2,6
start,v3,"V Three",0,3,3
start,v4,"V Four",0,4,5
start,v5,"V Five",0,5,7
start,v6,"V Six",0,6,9
start,v7,"V Seven",0,7,4
start,v8,"V Eight",0,8,2
start,v9,"V Nine",0,9,10
start,vp,"V Pitcher",0,0,1
start,h1,"H One",1,1,8
start,h2,"H Two",1,2,6
start,h3,"H Three",1,3,3
start,h4,"H Four",1,4,5
start,h5,"H Five",1,5,7
start,h6,"H Six",1,6,9
start,h7,"H Seven",1,7,4
start,h8,"H Eight",1,8,2
start,h9,"H Nine",1,9,10
start,hp,"H Pitcher",1,0,1
play,1,0,v1,32,BBBCC>B,W
play,1,0,v2,00,H,HP
play,1,0,v3,00,,NP
play,1,0,v3,00,,SB3;SB2
play,1,0,v3,22,BBCS,K+WP.B-1;3-H;2-3
play,1,0,v4,00,X,64(1)3/GDP.3-H
play,1,0,v5,00,X,E6/G6
play,1,0,v6,00,,CS2(E2).1-3
play,1,0,v6,00,,PO3(E1)
play,1,0,v6,00,,BK.3-H
play,1,0,v6,11,BX,DGR/L7
play,1,0,v7,00,F,FLE7/F
play,1,0,v7,01,FX,S9/L9.2-H;B-2
play,1,0,v8,00,,POCS3(25)
play,1,1,h1,00,X,S8/G
play,1,1,h2,00,X,8(B)83(1)/LDP
play,1,1,h3,00,X,D7/L7
play,1,1,h4,00,,IW
play,1,1,h5,00,X,S7/G6.2-H;1-3;B-2(TH)
play,1,1,h6,00,H,HP
play,1,1,h7,30,BBBB,W.3-H;2-3;1-2
play,1,1,h8,00,X,HR/F7.3-H;2-H;1-H
play,1,1,h9,00,X,3/G3
id,TST202504020
version,2
info,visteam,VIS
info,hometeam,TST
info,date,2025/04/02
info,number,0
start,v1,"V One",0,1,8
start,v2,"V Two",0,2,6
start,v3,"V Three",0,3,3
start,v9,"V Nine",0,9,10
start,vp,"V Pitcher",0,0,1
start,h1,"H One",1,1,8
start,h9,"H Nine",1,9,10
start,hp,"H Pitcher",1,0,1
radj,v9,2
play,10,0,v1,00,X,63/G6.2-3
play,10,0,v2,00,X,8/SF/F8.3-H
play,10,0,v3,00,X,K
radj,h9,2
sub,hpr,"Pinch Runner",1,9,12
play,10,1,h1,00,X,S9/G.2-H
"""
HANDS = {"v1": ("B", "R"), "vp": ("R", "R"), "hp": ("L", "L"), "h1": ("L", "L")}


def _synth():
    games = list(rs.iter_events({"eve/2025TST.EVA": SYNTH}, HANDS, 2025))
    return {g.gid: g for g in games}


def test_synthetic_game_base_out_states_runs_and_hits():
    g = _synth()["TST202504010"]
    r = [(x["event_cd"], x["bases_pre"], x["outs_pre"], x["runs_on_play"], x["outs_on_play"], x["bases_post"], x["pa"])
         for x in g.rows]
    expected = [
        ("bb", 0, 0, 0, 0, 1, True),        # W
        ("hbp", 1, 0, 0, 0, 3, True),       # HP forces the runner to second
        ("sb", 3, 0, 0, 0, 6, False),       # SB3;SB2 (NP skipped)
        ("k", 6, 0, 1, 0, 5, True),         # K+WP.B-1: batter safe, run scores
        ("out", 5, 0, 1, 2, 0, True),       # 64(1)3 GDP with a run in
        ("e", 0, 2, 0, 0, 1, True),         # E6
        ("cs", 1, 2, 0, 0, 4, False),       # CS2(E2).1-3: the error negates the out
        ("poe", 4, 2, 0, 0, 4, False),      # PO3(E1): no out, runner stays
        ("bk", 4, 2, 1, 0, 0, False),       # BK.3-H
        ("2b", 0, 2, 0, 0, 2, True),        # ground-rule double
        ("foul_err", 2, 2, 0, 0, 2, False),  # FLE7: nothing moves
        ("1b", 2, 2, 1, 0, 2, True),        # S9.2-H;B-2
        ("po", 2, 2, 0, 1, 0, False),       # POCS3(25) ends the half
        ("1b", 0, 0, 0, 0, 1, True),        # bottom 1: S8
        ("out", 1, 0, 0, 2, 0, True),       # 8(B)83(1) line-drive double play
        ("2b", 0, 2, 0, 0, 2, True),
        ("ibb", 2, 2, 0, 0, 3, True),       # IW: the runner on second is not forced
        ("1b", 3, 2, 1, 0, 6, True),        # S7.2-H;1-3;B-2
        ("hbp", 6, 2, 0, 0, 7, True),       # HP with second and third occupied: no force
        ("bb", 7, 2, 1, 0, 7, True),        # bases-loaded walk forces in a run
        ("hr", 7, 2, 4, 0, 0, True),        # grand slam
        ("out", 0, 2, 0, 1, 0, True),
    ]
    assert r == expected
    vis = [x for x in g.rows if x["half"] == 0]
    home = [x for x in g.rows if x["half"] == 1]
    assert sum(x["runs_on_play"] for x in vis) == 4 and sum(1 for x in vis if x["hit"]) == 2
    assert sum(x["runs_on_play"] for x in home) == 6 and sum(1 for x in home if x["hit"]) == 4
    assert sum(x["err"] for x in g.rows) >= 4
    first = g.rows[0]
    assert first["pitcher"] == "hp" and first["pit_hand"] == "L" and first["bat_hand"] == "R"   # switch hitter v. LHP
    assert first["balls"] == 3 and first["strikes"] == 2
    gdp = g.rows[4]
    assert gdp["fielded_by"] == 6 and gdp["bb_type"] is None
    s9 = g.rows[11]
    assert s9["hit_loc"] == "9" and s9["bb_type"] == "L" and s9["ab"]
    assert g.unparsed == 0


def test_extra_innings_automatic_runner_and_pinch_runner():
    g = _synth()["TST202504020"]
    top = [x for x in g.rows if x["half"] == 0]
    assert top[0]["bases_pre"] == 2 and top[0]["run2_pre"] == "v9" and top[0]["inning"] == 10
    assert top[1]["sf"] and not top[1]["ab"] and top[1]["runs_on_play"] == 1
    bot = [x for x in g.rows if x["half"] == 1]
    assert bot[0]["bases_pre"] == 2 and bot[0]["run2_pre"] == "hpr" and bot[0]["runs_on_play"] == 1


def test_split_and_advances():
    assert rs.split_top("CS2(E2/TH)/X", "/") == ["CS2(E2/TH)", "X"]
    adv = rs.parse_advances("1XH(82)(E3/TH);2-H(E7)(UR);BX2(8E4);3XH(25)")
    assert [(a["from"], a["to"], a["out"]) for a in adv] == [(1, 4, True), (2, 4, False), (0, 2, False), (3, 4, True)]
    assert rs.parse_advances("1XH(E1/TH)(525)")[0]["out"] is True


def test_real_games_reconcile_with_game_logs():
    files = {"eve/2025REG.EVA": load_fixture_text("retro_2025REG.EVA", "latin-1"),
             "post/2025WS.EVE": load_fixture_text("retro_2025WS.EVE", "latin-1"),
             "eve/ROS2025.ROS": load_fixture_text("retro_2025.ROS", "latin-1")}
    pa, stats = rs.games_to_frame(rs.iter_events(files, None, 2025))
    assert stats == {"games": 3, "unparsed": 0}
    gl = rs.parse_gamelog(load_fixture_text("retro_gl2025.txt", "latin-1"))
    assert sorted(gl["game_id"]) == ["TBA202507010", "WAS202505200"]
    v = rs.validate(pa, gl)
    assert v["games"] == 2 and v["runs_match"] == 1.0 and v["hits_match"] == 1.0
    tb = pa[pa["game_id"] == "TBA202507010"]
    tenth = tb[(tb["inning"] == 10)]
    assert (tenth.groupby("half")["bases_pre"].first() & 2 == 2).all()             # automatic runner each half
    play = tb[tb["event_tx"].astype(str).str.startswith("7/SF/F78D/NDP")].iloc[0]
    assert play["runs_on_play"] == 1 and play["outs_on_play"] == 2 and play["outs_post"] == 3
    ws = pa[pa["game_id"].astype(str).str.startswith("TOR2025")]
    assert set(ws["gtype"].astype(str)) == {"W"}
    assert pa["bat_hand"].astype(str).isin(["L", "R"]).mean() > 0.95
    assert pa["pa"].sum() > 200 and str(pa["half"].dtype) == "int8"


def test_gtype_from_file_names():
    assert rs._gtype_from_name("eve/2025ATL.EVN", "regular") == "R"
    assert rs._gtype_from_name("post/2025ALW1.EVE", None) == "F"
    assert rs._gtype_from_name("post/2025NLD2.EVE", None) == "D"
    assert rs._gtype_from_name("post/2025ALCS.EVE", None) == "L"
    assert rs._gtype_from_name("post/1910WS.EVE", None) == "W"


def test_notice_text():
    assert rs.NOTICE == ('The information used here was obtained free of charge from and is copyrighted by Retrosheet. '
                         'Interested parties may contact Retrosheet at "www.retrosheet.org".')


# ── Chadwick crosswalk ──────────────────────────────────────────────────────

def test_crosswalk_from_register_rows(bullpen_roots):
    rows = list(csv.DictReader(io.StringIO(load_fixture_text("chadwick_people.csv"))))
    people, mlbam = chadwick.build_crosswalk(rows)
    mlb = [r for r in rows if r["key_mlbam"] and r["mlb_played_first"]]
    minors = [r for r in rows if r["key_mlbam"] and not r["mlb_played_first"] and not r["key_retro"]]
    retro_only = [r for r in rows if not r["key_mlbam"] and r["key_retro"]]
    for r in mlb:
        p = people[r["key_mlbam"]]
        assert p["retro"] == r["key_retro"] and p["bbref"] == r["key_bbref"] and p["fg"] == r["key_fangraphs"]
        assert p["debut"] == int(r["mlb_played_first"])
    for r in minors:
        assert r["key_mlbam"] not in people and r["key_mlbam"] in mlbam
    for r in retro_only:
        assert f"r:{r['key_retro']}" in people
    players = {r["key_mlbam"]: {"name": "x"} for r in mlb + minors}
    hit, tot = chadwick.enrich_players(players, people, mlbam)
    assert (hit, tot) == (len(mlb) + len(minors), len(mlb) + len(minors))
    assert all(players[r["key_mlbam"]]["retro"] == r["key_retro"] for r in mlb)
    assert "ODC-BY" in chadwick.ATTRIBUTION


# ── ESPN ────────────────────────────────────────────────────────────────────

def test_espn_events_map_to_gamepks():
    games = {}
    for g in _schedule_games():
        rec = statsapi.compact_game(g)
        games[rec["gpk"]] = rec
    evs = load_fixture_json("espn_scoreboard_20260930.json")["events"]
    m = espn.match_events(evs, games)
    assert m == {"401907972": "990841", "401907897": "990846", "401907963": "990848", "401907975": "990842"}
    # an ESPN event dated the next UTC day (8 pm ET start) still maps; a wrong pairing never does
    assert espn.match_events(evs, {"x": dict(games["990848"], home="147", away="121")}) == {}


def test_espn_doubleheader_resolves_by_start_time():
    g1 = {"home": "147", "away": "111", "start": "2026-06-01T17:05:00Z", "date": "2026-06-01"}
    g2 = {"home": "147", "away": "111", "start": "2026-06-01T23:05:00Z", "date": "2026-06-01"}
    evs = [{"id": "B", "start": "2026-06-01T23:10Z", "home": "147", "away": "111"},
           {"id": "A", "start": "2026-06-01T17:05Z", "home": "147", "away": "111"}]
    assert espn.match_events(evs, {"1": g1, "2": g2}) == {"A": "1", "B": "2"}


def test_espn_lines_2026_open_close():
    ln = espn.compact_lines(load_fixture_json("espn_odds_401907972.json"))
    assert ln["src"] == "DraftKings" and ln["ml"] == [-103, -117]
    assert ln["rl"] == {"home": 1.5, "price": [-185, 152]}                  # away favourite lays the run
    assert ln["total"] == {"line": 7.0, "over": -118, "under": -102}
    assert ln["open"]["ml"] == [-108, -112] and ln["close"]["ml"] == [-103, -117]
    assert ln["open"]["total"]["line"] == 7.0 and ln["open"]["rl"]["home"] == 1.5


def test_espn_lines_2019_books_and_run_line_sign():
    ln = espn.compact_lines(load_fixture_json("espn_odds_2019.json"))
    assert len(ln["books"]) == 10 and ln["consensus"]["ml"][0] == -150
    assert ln["ml"][0] < 0 and ln["rl"]["home"] == -1.5                     # home favourite lays 1.5
    assert all(b["rl"] is None or b["rl"]["home"] == -1.5 for b in ln["books"] if b["ml"][0] is not None and b["ml"][0] < 0)


def test_espn_pickcenter_and_win_probability():
    sm = load_fixture_json("espn_summary_401907972.json")
    assert espn.lines_from_pickcenter(sm)["ml"] == [-103, -117]
    wp = espn.win_probability(sm)
    assert wp[0] == ["4019079720001990057", 0.449] and len(wp) == 6


# ── stores ──────────────────────────────────────────────────────────────────

def test_store_round_trip_and_complete_through(bullpen_roots):
    s = st.load("mlb", 2026)
    for g in _schedule_games():
        statsapi.take_game(s, g, st.merge_game)
    st.save(s)
    back = st.load("mlb", 2026)
    assert set(back["games"]) == {"990679", "990490", "990841", "990842", "990846", "990848"}
    assert back["umpires"] == {} and back["meta"]["complete_through"] is None
    assert st.complete_through(back) == "2026-09-30"
    assert st.season_path("mlb", 2026).parent == bullpen_roots["data"] / "mlb" / "2026"
    assert st.statcast_path("aaa", 2024) == bullpen_roots["raw"] / "statcast" / "aaa" / "2024.parquet"
    assert st.seasons_on_disk("mlb") == [2026]


def test_save_owned_merges_concurrent_phases(bullpen_roots):
    base = st.load("mlb", 2026)
    for g in _schedule_games():
        statsapi.take_game(base, g, st.merge_game)
    st.save_owned(base, ["schedule"])
    a, b, sch = st.load("mlb", 2026), st.load("mlb", 2026), st.load("mlb", 2026)
    a["games"]["990841"]["lines"] = {"ml": [-103, -117]}           # the ESPN process
    a["meta"]["espn_odds"] = {"990841": "x"}
    b["games"]["990841"]["has_statcast"] = True                    # the Savant process
    b["players"]["1"] = {"name": "P"}
    sch["games"]["990841"]["hs"] = 5                               # a schedule rescan holding no lines
    st.save_owned(a, ["espn"])
    st.save_owned(b, ["statcast", "people"])
    st.save_owned(sch, ["schedule"])
    final = st.load("mlb", 2026)
    g = final["games"]["990841"]
    assert g["lines"] == {"ml": [-103, -117]} and g["has_statcast"] is True and g["hs"] == 5
    assert final["meta"]["espn_odds"] == {"990841": "x"} and final["players"]["1"] == {"name": "P"}
    assert sch["games"]["990841"]["lines"] == {"ml": [-103, -117]}           # memory refreshed from disk
    assert not st.season_path("mlb", 2026).with_name("store.json.lock").exists()
