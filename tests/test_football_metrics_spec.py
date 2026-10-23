"""Footballer metrics-spec payload fields and accuracy fixes (23 Oct 2026)."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.football.analytics import players as PL


def _acc(**kw):
    a = {"player_id": "1", "name": "Taker", "team": "X", "matches": 3, "starts": 3, "_rat_w": 0.0, "_rat_min": 0.0, "top_speed": 0.0,
         "_conceded": 0.0, "_last": "", "_padj": 0.0, "shirt": None, **{k: 0.0 for k in PL.SUM_KEYS}}
    a.update(minutesPlayed=270.0, **kw)
    return a


def test_npxg_leaves_out_missed_penalties():
    now = datetime(2026, 10, 23, tzinfo=timezone.utc)
    # one scored penalty (incidents) and one missed (penaltyMiss); 2.0 xG in all
    r = PL.finalize_player("1", _acc(expectedGoals=2.0, goals=1.0, penaltyMiss=1.0, totalShots=5.0), {}, "F", {"pens": 1}, now)
    assert r["npxg"] == round(2.0 - 2 * PL.PEN_XG, 2)
    r = PL.finalize_player("1", _acc(expectedGoals=2.0, goals=1.0, totalShots=5.0), {}, "F", {"pens": 1}, now)
    assert r["npxg"] == round(2.0 - PL.PEN_XG, 2)


def _value_files(d):
    import json
    (d / "value").mkdir(parents=True)
    (d / "value" / "lines.json").write_text(json.dumps({"fields": ["id", "comp", "tid", "min", "apps", "gar90", "gar", "par", "pct", "role"],
                                                        "rows": [["1", "premier-league", 5, 900, 10, 0.12, 1.2, 3.0, 80, "CB"],
                                                                 ["2", "premier-league", 5, 300, 4, -0.05, -0.2, -0.5, None, "ST"]]}),
                                            encoding="utf-8")
    (d / "value" / "players.json").write_text(json.dumps({"fields": ["id", "name", "age", "nat", "role", "tid", "club", "league", "min",
                                                                     "apps", "gar90"],
                                                          "rows": [["1", "A", 25, "ENG", "CB", 5, "X", "premier-league", 2000, 25, 0.1],
                                                                   ["3", "C", 22, "ESP", "W", 6, "Y", "la-liga", 1500, 20, 0.2]]}),
                                              encoding="utf-8")


def test_value_fields_reach_players_live_lab_and_people(tmp_path):
    import json
    from oddsmarkets.football.analytics import value_fields as VF
    d = tmp_path
    _value_files(d)
    (d / "premier-league").mkdir()
    (d / "premier-league" / "players_live.json").write_text(json.dumps({"ok": True, "players": [
        {"player_id": "1", "name": "A"}, {"player_id": "3", "name": "C"}, {"player_id": "9", "name": "Z"}]}), encoding="utf-8")
    (d / "lab" / "season").mkdir(parents=True)
    (d / "lab" / "365").mkdir(parents=True)
    lab = {"window": "season", "fields": ["player_id", "name", "comp", "goals_90"],
           "rows": [["1", "A", "premier-league", 0.1], ["3", "C", "la-liga", 0.2]]}
    (d / "lab" / "season" / "premier-league.json").write_text(json.dumps(lab), encoding="utf-8")
    (d / "lab" / "365" / "all.json").write_text(json.dumps({**lab, "window": "365"}), encoding="utf-8")
    (d / "people").mkdir()
    (d / "people" / "1.json").write_text(json.dumps({"id": "1", "name": "A", "role": "FB"}), encoding="utf-8")
    (d / "people" / "3.json").write_text(json.dumps({"id": "3", "name": "C"}), encoding="utf-8")
    assert VF.roles(d) == {"1": "CB", "3": "W"}
    out = VF.apply(d, roles_before={"1": "FB"})
    assert out == {"players_live": 1, "lab": 2, "people": 2}
    live = {p["player_id"]: p for p in json.loads((d / "premier-league" / "players_live.json").read_text(encoding="utf-8"))["players"]}
    assert (live["1"]["role"], live["1"]["gar90"]) == ("CB", 0.12)
    assert (live["3"]["role"], live["3"]["gar90"]) == ("W", None)        # no line in this competition: role from 12 months
    assert live["9"]["role"] is None
    s = json.loads((d / "lab" / "season" / "premier-league.json").read_text(encoding="utf-8"))
    assert s["fields"][:4] == lab["fields"] and s["fields"][4:] == ["role", "gar90"]       # appended, positions kept
    assert s["rows"][0][4:] == ["CB", 0.12] and s["rows"][1][4:] == ["W", 0.2]
    y = json.loads((d / "lab" / "365" / "all.json").read_text(encoding="utf-8"))
    assert y["rows"][0][4:] == ["CB", 0.1]                                # other windows: the 12-month value
    assert json.loads((d / "people" / "1.json").read_text(encoding="utf-8"))["role"] == "CB"
    assert json.loads((d / "people" / "3.json").read_text(encoding="utf-8"))["role"] == "W"
    assert VF.apply(d, roles_before=VF.roles(d)) == {"players_live": 0, "lab": 0, "people": 0}   # idempotent


def test_value_fields_without_a_value_layer(tmp_path):
    from oddsmarkets.football.analytics import value_fields as VF
    assert VF.apply(tmp_path, {}) == {"players_live": 0, "lab": 0, "people": 0}
