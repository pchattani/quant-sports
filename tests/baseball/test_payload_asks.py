"""Bullpen redesign payload asks (22 Oct 2026): per-season peers.json and league_types.json, the movement row in the
player file, roster columns, builder labels, and names written as UTF-8 (never double-encoded)."""
from __future__ import annotations

import json
from types import SimpleNamespace

from oddsmarkets.baseball import analytics as an
from oddsmarkets.baseball.analytics import careers as CR
from oddsmarkets.baseball.analytics import hitters as HT
from oddsmarkets.baseball.analytics import peers as PE
from oddsmarkets.baseball.analytics import pitchers as PT
from oddsmarkets.baseball.analytics import teams as TM


def _hit(pid, pos, pa, x):
    return {"name": pid, "team": "109", "pos": pos, "pa": pa, "values": {"xwoba_n": x, "k_pct": 0.2, "war_600": 2.0}}


def _pit(pid, role, bf, x):
    return {"name": pid, "team": "109", "role": role, "bf": bf, "values": {"xwoba_n": x, "stuff_plus": 100 + x}}


def test_peers_groups_floors_and_sorted_values():
    hit = {"ok": True, "team_games": 81, "players": {
        "a": _hit("a", "DH", 150, 0.34), "b": _hit("b", "DH", 90, 0.30), "c": _hit("c", "1B", 101, 0.36), "d": _hit("d", None, 120, 0.31),
        "e": _hit("e", "LF", 100, 0.33), "f": _hit("f", "RF", 99, 0.29)}}
    pit = {"ok": True, "team_games": 81, "league_types": {"FF": {"n": 1000, "velo": 94.1}, "SL": {"n": 500}},
           "players": {"p": _pit("p", "SP", 151, 0.30), "q": _pit("q", "RP", 61, 0.28), "r": _pit("r", "RP", 59, 0.27)}}
    out = PE.build(hit, pit, "mlb", 2026)
    G = out["groups"]
    # floors prorated by team games: 200 PA x 81/162 = 100; SP 150, RP 60
    assert G["DH"]["floor"] == {"field": "pa", "value": 100, "unit": "PA"} and G["DH"]["n"] == 1 and G["DH"]["xwoba_n"] == [0.34]
    assert G["LF/RF"]["n"] == 1                                      # f is one PA short
    assert G["ALL"]["n"] == 4 and G["ALL"]["xwoba_n"] == [0.31, 0.33, 0.34, 0.36]      # every qualified hitter, sorted
    assert G["SP"]["floor"]["value"] == 150 and G["RP"]["xwoba_n"] == [0.28]
    assert "chase_pct" not in G["DH"]                                # no values, no list
    assert PE.set_of("hitter", {"pos": "TWP"}) == "DH" and PE.set_of("pitcher", {"role": None}) == "SP"
    json.dumps(out, allow_nan=False)
    lt = PE.league_types(pit, "mlb", 2026)
    assert lt["ok"] and lt["league_types"]["FF"]["velo"] == 94.1
    assert PE.own_types(pit["league_types"], {"FF": {}, "CU": {}, "all": {}}) == {"FF": {"n": 1000, "velo": 94.1}}
    assert PE.own_types(pit["league_types"], None) is None


def test_movement_row_in_the_player_file(bullpen_roots):
    m = {"ok": True, "season": 2026, "snapshot": "2026-10-22", "phase": "offseason", "published": {"next": True, "deadline": False},
         "base_rates": {"next": 0.29}, "horizons": {"next": "2027 opening day"},
         "player_fields": ["pid", "name", "team", "p_next"], "players": [["600869", "Germán Márquez", "115", 0.8], ["1", "x"]]}
    an.write_json(bullpen_roots["data"] / "mlb" / "movement.json", m)
    rows = CR.movement_rows("mlb")
    assert set(rows) == {"600869"}                                   # a short row is skipped
    r = rows["600869"]
    assert r["row"] == {"pid": "600869", "name": "Germán Márquez", "team": "115", "p_next": 0.8}
    assert r["published"] == {"next": True, "deadline": False} and r["season"] == 2026 and r["base_rates"]["next"] == 0.29


def test_names_are_written_as_utf8_not_double_encoded(bullpen_roots):
    """The movement payload (and every payload) is UTF-8 on disk: "Machín" is c3 ad, never the double-encoded c3 83 c2 ad
    ("MachÃ­n" is what a cp1252 reader such as Windows PowerShell 5.1's Get-Content shows for the correct bytes)."""
    p = bullpen_roots["data"] / "mlb" / "movement.json"
    an.write_json(p, {"ok": True, "players": [["1", "Vimael Machín"]]})
    raw = p.read_bytes()
    assert "Machín".encode("utf-8") in raw and b"\xc3\x83" not in raw
    assert an.read_json(p)["players"][0][1] == "Vimael Machín"


def test_roster_columns():
    ctx = SimpleNamespace(store={"meta": {}}, players={}, name=lambda pid: str(pid))
    hp = {"h": {"name": "H", "team": "109", "pos": "1B", "pa": 500,
                "values": {"war": 3.0, "woba": 0.35, "xwoba_plus": 0.36, "proj_woba": 0.34, "woba_vl": 0.30, "woba_vr": 0.37}}}
    pp = {"p": {"name": "P", "team": "109", "role": "SP",
                "values": {"war": 2.0, "ip": 150, "ra9": 3.9, "stuff_plus": 104, "proj_woba": 0.31, "gs": 28, "xra9": 4.1,
                           "pitching_plus": 102, "p_start": 91}}}
    rows = {r["pid"]: r for r in TM.roster(ctx, "109", hp, pp)}
    assert {k: rows["h"][k] for k in TM.ROSTER_H} == {"proj_woba": 0.34, "woba_vl": 0.30, "woba_vr": 0.37}
    assert {k: rows["p"][k] for k in TM.ROSTER_P} == {"proj_woba": 0.31, "gs": 28, "xra9": 4.1, "pitching_plus": 102, "p_start": 91}


def test_builder_labels_ids_unchanged():
    h = {m["key"]: m for m in HT.METRICS}
    p = {m["key"]: m for m in PT.METRICS}
    assert h["g"]["label"] == "G (with a PA)" and h["bb"]["label"] == "uBB"
    assert p["r"]["label"] == "R (on the mound)" and p["bb"]["label"] == "uBB" and p["edge_pct"]["label"] == "Shadow%"
    assert "edge" not in p["edge_pct"]["label"].lower()
