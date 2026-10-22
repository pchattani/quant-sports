"""Counting stats follow the official count (nflverse's player stats): laterals, two-point tries, spikes, aborted snaps,
every tackle column and the credited player's own team (accuracy audit, 22 Oct 2026)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from oddsmarkets.nfl.analytics import players as PL

GID = "2026_03_SF_LA"


def _plays() -> pd.DataFrame:
    rows = [
        # 1: a 100-yard completion to WR1 who laterals to WR2 after 20 yards; WR2 scores
        dict(play_id=1, play_type="pass", posteam="SF", defteam="LA", passer_id="QB1", passer_player_id="QB1", receiver_id="WR1",
             receiver_player_id="WR1", complete_pass=1, yards_gained=100, passing_yards=100, receiving_yards=20,
             lateral_receiver_player_id="WR2", lateral_receiving_yards=80, pass_touchdown=1, td_player_id="WR2", qb_dropback=1,
             sack=0, qb_scramble=0, two_point_attempt=0, epa=4.0),
        # 2: a two-point pass: not an attempt, target or reception
        dict(play_id=2, play_type="pass", posteam="SF", defteam="LA", passer_id="QB1", passer_player_id="QB1", receiver_id="WR1",
             receiver_player_id="WR1", complete_pass=1, yards_gained=2, two_point_attempt=1, qb_dropback=1, sack=0, qb_scramble=0, epa=0.5),
        # 3: a spike: an attempt (incomplete)
        dict(play_id=3, play_type="qb_spike", posteam="SF", defteam="LA", passer_id=None, passer_player_id="QB1", qb_dropback=0,
             two_point_attempt=0),
        # 4: an aborted snap: the centre fumbles, the running back recovers and runs 8 yards (the carry is his)
        dict(play_id=4, play_type="run", posteam="SF", defteam="LA", rusher_id="C1", rusher_player_id="RB1", yards_gained=8,
             rushing_yards=8, qb_scramble=0, two_point_attempt=0, epa=0.3),
        # 5: an interception; the offence's tackle makes the tackle (his team is SF, not LA)
        dict(play_id=5, play_type="pass", posteam="SF", defteam="LA", passer_id="QB1", passer_player_id="QB1", receiver_id="WR1",
             receiver_player_id="WR1", complete_pass=0, incomplete_pass=0, interception=1, interception_player_id="CB1",
             solo_tackle_1_player_id="OT1", solo_tackle_1_team="SF", yards_gained=0, qb_dropback=1, sack=0, qb_scramble=0,
             two_point_attempt=0, epa=-4.0),
        # 6: a run with two solo tacklers and four assists (the old count read only the first of each)
        dict(play_id=6, play_type="run", posteam="SF", defteam="LA", rusher_id="RB1", rusher_player_id="RB1", yards_gained=3,
             rushing_yards=3, assist_tackle_1_player_id="LB1", assist_tackle_1_team="LA", assist_tackle_2_player_id="LB2",
             assist_tackle_2_team="LA", tackle_with_assist_1_player_id="DL1", tackle_with_assist_1_team="LA", qb_scramble=0,
             two_point_attempt=0, epa=-0.2),
        # 7: a punt: the gunner (SF, the posteam) makes the tackle
        dict(play_id=7, play_type="punt", posteam="SF", defteam="LA", punter_player_id="P1", solo_tackle_1_player_id="GUN1",
             solo_tackle_1_team="SF", kick_distance=45, return_yards=5, two_point_attempt=0),
    ]
    df = pd.DataFrame(rows)
    df["game_id"] = GID
    df["season_type"] = "REG"
    df["week"] = 3
    return df


def test_yardage_follows_the_official_columns():
    P = _plays()
    S = PL.scrimmage(P, two_point=False)
    assert 2 not in set(S["play_id"])
    assert 2 in set(PL.scrimmage(P)["play_id"])                           # the default keeps them (team metrics)
    X = S[S["play_type"] == "pass"]
    assert PL.pass_yards(X).tolist() == [100.0, 0.0]
    assert PL.rec_yards(X).tolist() == [20.0, 0.0]                        # the lateral's 80 are not WR1's
    lat = PL.lateral_yards(S, "receiving")
    assert lat.to_dict() == {("WR2", GID): 80.0}
    assert PL.lateral_yards(S, "receiving", tds=True).to_dict() == {("WR2", GID): 1.0}
    assert PL.td_credit(X.assign(pid="WR1"), "pass_touchdown").tolist() == [0.0, 0.0]


def test_yardage_falls_back_without_the_official_columns():
    X = pd.DataFrame({"complete_pass": [1, 0, 1], "yards_gained": [12, 0, -3]})
    assert PL.pass_yards(X).tolist() == [12.0, 0.0, -3.0]
    assert PL.rec_yards(X).tolist() == [12.0, 0.0, -3.0]
    assert PL.rush_yards(pd.DataFrame({"yards_gained": [4, np.nan]})).tolist() == [4.0, 0.0]


def test_pid_coalesces_in_order():
    P = _plays()
    run = P[P["play_id"] == 4]
    assert PL._pid(run, "rusher_player_id", "rusher_id").tolist() == ["RB1"]   # the carrier, not the centre
    spike = P[P["play_id"] == 3]
    assert PL._pid(spike, "passer_id", "passer_player_id").tolist() == ["QB1"]


def test_def_credits_every_column_and_own_team():
    C = PL.def_credits(_plays())
    tk = C[C["stat"] == "tackles"].set_index("pid")
    assert set(tk.index) == {"OT1", "LB1", "LB2", "DL1", "GUN1"}
    assert tk.loc["OT1", "team"] == "SF" and tk.loc["GUN1", "team"] == "SF" and tk.loc["LB2", "team"] == "LA"
    assert not bool(tk.loc["GUN1", "scrim"])                                # special teams: counted, not splash
    ints = C[C["stat"] == "ints"]
    assert ints["pid"].tolist() == ["CB1"] and ints["team"].tolist() == ["LA"]


def test_group_for_keeps_linemen_out():
    assert PL.group_for("OL", "DEF") == "OL"
    assert PL.group_for(None, "DEF") == "DEF"
    assert PL.group_for("DEF", "RB") == "DEF"


def test_box_score_counts_like_the_official_box():
    from oddsmarkets.nfl.analytics import games as GM
    P = _plays().assign(_epa=lambda d: d["epa"])
    box = GM.box_block(P, {"home": "LA", "away": "SF"}, {}, {})
    sf = box["away"]
    qb = {r["pid"]: r for r in sf["passing"]}["QB1"]
    assert (qb["att"], qb["cmp"], qb["yds"]) == (3, 1, 100)                # two passes + the spike; the two-point try is out
    rec = {r["pid"]: r for r in sf["receiving"]}
    assert (rec["WR1"]["tgt"], rec["WR1"]["yds"], rec["WR1"]["td"]) == (2, 20, 0)
    rush = {r["pid"]: r for r in sf["rushing"]}
    assert "C1" not in rush and rush["RB1"]["car"] == 2 and rush["RB1"]["yds"] == 11
    la_def = {r["pid"]: r for r in box["home"]["defense"]}
    assert set(la_def) == {"CB1", "LB1", "LB2", "DL1"}                     # OT1 and the gunner are SF's
    assert {r["pid"] for r in sf["defense"]} == {"OT1", "GUN1"}


def test_game_log_sums_to_the_season_rules():
    from oddsmarkets.nfl.analytics import careers as CR

    class Ctx:
        games = {GID: {"week": 3, "home": "LA", "away": "SF"}}

    logs = CR._gamelog(_plays(), Ctx())
    wr2 = logs["WR2"][0]
    assert wr2["x_yds"] == 80 and wr2["x_td"] == 1 and wr2["team"] == "SF"
    qb = logs["QB1"][0]
    assert qb["p_att"] == 3 and qb["p_yds"] == 100
    assert logs["RB1"][0]["r_car"] == 2 and "C1" not in logs
    assert logs["OT1"][0]["team"] == "SF" and logs["LB1"][0]["d_tkl"] == 1


def test_calibration_stamp_is_the_backtest_not_the_build():
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("build_gridiron_stamp", root / "scripts" / "build_gridiron.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.calibration_stamp({"game_model": {"generated_at": "2026-10-21T18:33:57Z"}}) == "2026-10-21T18:33:57Z"
    assert mod.calibration_stamp({"ep": {}}) is None


def test_load_release_passes_the_kind(monkeypatch):
    """NGS rushing / receiving used to read the passing file (the kind never reached the loader)."""
    from oddsmarkets.nfl.analytics.context import load_release
    from oddsmarkets.nfl.sources import nflverse as NV
    seen = []

    def fake(release, season=None, kind=None, columns=None):
        seen.append(kind)
        return pd.DataFrame({"season": [2026], "kind": [kind]})
    monkeypatch.setattr(NV, "load", fake)
    for k in ("passing", "rushing", "receiving"):
        df = load_release("nextgen_stats", None, None, k)
        assert df["kind"].tolist() == [k]
    assert seen == ["passing", "rushing", "receiving"]
