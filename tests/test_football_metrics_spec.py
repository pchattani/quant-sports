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
    lab = {"window": "season", "fields": ["player_id", "name", "comp", "minutes"],
           "rows": [["1", "A", "premier-league", 960], ["3", "C", "la-liga", 1500]]}
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
    assert live["3"]["role"] == "W" and "gar90" not in live["3"]         # no line in this competition: role from 12 months
    assert "role" not in live["9"] and "gar90" not in live["9"]          # unknown: no key (players_live writes no nulls)
    s = json.loads((d / "lab" / "season" / "premier-league.json").read_text(encoding="utf-8"))
    assert s["fields"][:4] == lab["fields"] and s["fields"][4:] == ["role", "gar90", "gar"]       # appended, positions kept
    # without the windowed value (no value layer this build): this season in one competition takes that competition's
    # line when its minutes are the row's (900 v 960); no line there: no value (role from 12 months)
    assert s["rows"][0][4:] == ["CB", 0.12, 1.2] and s["rows"][1][4:] == ["W", None, None]
    y = json.loads((d / "lab" / "365" / "all.json").read_text(encoding="utf-8"))
    assert y["rows"][0][4:] == ["CB", None, None]                         # 365: never another window's value
    assert json.loads((d / "people" / "1.json").read_text(encoding="utf-8"))["role"] == "CB"
    assert json.loads((d / "people" / "3.json").read_text(encoding="utf-8"))["role"] == "W"
    assert VF.apply(d, roles_before=VF.roles(d)) == {"players_live": 0, "lab": 0, "people": 0}   # idempotent


def test_value_fields_without_a_value_layer(tmp_path):
    from oddsmarkets.football.analytics import value_fields as VF
    assert VF.apply(tmp_path, {}) == {"players_live": 0, "lab": 0, "people": 0}


def test_lab_gar_sums_the_windowed_value_per_scope_and_feeds_a_gar_board(tmp_path):
    """Pooled views sum the value over the line's own matches in the scope (PeopleLines.value_views: GAR adds, GAR/90 =
    90 GAR / minutes); every window reads its own matches; leaders.json gains a `gar` board per scope (24 Oct 2026;
    windowed 28 Oct 2026). Without the windowed value a pooled row has no GAR (never another scope's or edition's)."""
    import json
    from oddsmarkets.football.analytics import value_fields as VF
    d = tmp_path
    (d / "value").mkdir()
    # lines.json holds each competition's latest edition: a 2023 qualifier and a summer World Cup would leak into
    # this season's pooled rows if they were summed (the 28 Oct bug); the windowed value leaves them out
    (d / "value" / "lines.json").write_text(json.dumps({"fields": ["id", "comp", "min", "gar90", "gar", "role"], "rows": [
        ["1", "premier-league", 900, 0.2, 2.0, "ST"], ["1", "champions-league", 450, 0.4, 2.0, "ST"], ["1", "nations-league", 180, -0.5, -1.0, "ST"],
        ["1", "euro-qualifiers", 630, 0.3, 2.1, "ST"], ["1", "world-cup", 450, 0.6, 3.0, "ST"],
        ["2", "premier-league", 600, 0.1, 0.67, "CB"]]}), encoding="utf-8")
    (d / "value" / "players.json").write_text(json.dumps({"fields": ["id", "role", "gar90", "gar"], "rows": [
        ["1", "ST", 0.25, 5.5], ["2", "CB", 0.08, 1.6]]}), encoding="utf-8")
    for w in ("season", "last", "365"):
        (d / "lab" / w).mkdir(parents=True)
    (d / "lab" / "index.json").write_text(json.dumps({"comps": {"premier-league": {"scope": "club"}, "champions-league": {"scope": "club"},
                                                                "nations-league": {"scope": "international"}}}), encoding="utf-8")
    base = {"fields": ["player_id", "name", "team", "tid", "comp", "mix", "minutes"],
            "rows": [["1", "A", "X", 5, "premier-league", "EPL", 1530], ["2", "B", "X", 5, "premier-league", "EPL", 600], ["9", "Z", "Y", 6, "la-liga", "", 300]]}
    mins = {"all": 1890, "club": 1350, "intl": 540}                    # each scope's own minutes, as the Lab writes them
    for sc in ("all", "club", "intl"):
        rows = [[*r[:6], mins[sc]] if r[0] == "1" else r for r in base["rows"]]
        (d / "lab" / "season" / f"{sc}.json").write_text(json.dumps({**base, "rows": rows}), encoding="utf-8")
    for sc, m in (("all", 3150), ("club", 2700), ("intl", 450)):
        rows = [["1", "A", "X", 5, "premier-league", "EPL", m]] + ([["2", "B", "X", 5, "premier-league", "EPL", 900]] if sc != "intl" else [])
        (d / "lab" / "last" / f"{sc}.json").write_text(json.dumps({**base, "rows": rows}), encoding="utf-8")
    (d / "lab" / "365" / "intl.json").write_text(json.dumps({**base, "rows": [["1", "A", "Norway", 7, "world-cup", "WC", 630]]}), encoding="utf-8")
    (d / "lab" / "leaders.json").write_text(json.dumps({"window": "season", "scopes": {"all": {"goals": []}, "club": {"goals": []}, "intl": {"goals": []}}}), encoding="utf-8")
    lab_value = {"intl": ["nations-league", "world-cup", "euro-qualifiers"], "windows": {
        "season": {"1": {"premier-league": [2.0, 900.0], "champions-league": [2.0, 450.0], "nations-league": [-1.0, 540.0]},
                   "2": {"premier-league": [0.67, 600.0]}},
        "last": {"1": {"premier-league": [5.4, 2700.0], "world-cup": [3.0, 450.0]}, "2": {"premier-league": [0.0, 900.0]}},
        "365": {"1": {"premier-league": [4.0, 1800.0], "nations-league": [-1.0, 180.0], "world-cup": [3.0, 450.0]}}}}
    prev = {("1", "premier-league"): {"role": "W", "gar90": 0.3, "min": 1800}, ("2", "premier-league"): {"role": "CB", "gar90": 0.0, "min": 900}}
    VF.apply(d, prev_lines=prev, prev_sid={}, lab_value=lab_value)
    rd = lambda w, sc: {r[0]: r[7:] for r in json.loads((d / "lab" / w / f"{sc}.json").read_text(encoding="utf-8"))["rows"]}
    a, c, i = rd("season", "all"), rd("season", "club"), rd("season", "intl")
    assert a["1"] == ["ST", round(90 * 3.0 / 1890, 3), 3.0]            # 2.0 + 2.0 - 1.0 over 1,890 minutes
    assert c["1"] == ["ST", round(90 * 4.0 / 1350, 3), 4.0]            # club competitions only
    assert i["1"] == ["ST", round(-90 / 540, 3), -1.0]                 # the Nations League alone, not the qualifier or World Cup
    assert a["9"] == [None, None, None] and i["2"][1:] == [None, None]
    la, lc, li = rd("last", "all"), rd("last", "club"), rd("last", "intl")
    assert lc["1"] == ["ST", 0.18, 5.4] and li["1"] == ["ST", 0.6, 3.0] and la["1"] == ["ST", round(90 * 8.4 / 3150, 3), 8.4]
    assert li["1"] != lc["1"] and la["2"][1:] == [0.0, 0.0]
    y = rd("365", "intl")
    assert y["1"] == ["ST", round(90 * 2.0 / 630, 3), 2.0]             # the Nations League and the World Cup, no club match
    # the value model must score half the row's minutes, or the row has no GAR
    assert VF.windowed({"nations-league": [1.0, 300.0]}, "intl", {"nations-league"}, 900) == (None, None)
    assert VF.windowed({"nations-league": [1.0, 450.0]}, "intl", {"nations-league"}, 900) == (0.2, 1.0)
    board = json.loads((d / "lab" / "leaders.json").read_text(encoding="utf-8"))["scopes"]
    assert [x["id"] for x in board["all"]["gar"]] == ["1", "2"] and board["all"]["gar"][0]["value"] == 3.0
    assert board["all"]["gar"][0]["gar90"] == a["1"][1] and board["all"]["goals"] == []
    assert board["intl"]["gar"] == [{"id": "1", "name": "A", "team": "X", "tid": 5, "comp": "premier-league", "mix": "EPL", "value": -1.0,
                                     "minutes": 540, "gar90": round(-90 / 540, 3)}]
    assert VF.apply(d, prev_lines=prev, prev_sid={}, lab_value=lab_value)["lab"] == 0      # idempotent
    # no windowed value: a pooled row has no GAR rather than another edition's or scope's
    VF.apply(d, prev_lines=prev, prev_sid={})
    assert rd("season", "intl")["1"] == ["ST", None, None] and rd("last", "club")["1"] == ["ST", None, None]
