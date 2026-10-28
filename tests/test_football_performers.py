"""oddsmarkets/football/analytics/performers.py: the competition pages' top and bottom performers."""
import json

from oddsmarkets.football.analytics import performers as F


def _p(i, role, minutes, **v):
    return {"player_id": i, "name": f"P{i}", "team": "Club", "tid": 7, "role": role, "minutes": minutes, "gar90": v.pop("gar90", i / 100),
            "rating": 6 + i / 100, "npxg_xa_90": i / 50, "aerial_pct": 40 + i, "padj_tkl_int_90": i / 10, **v}


def test_qualification_positions_and_views():
    players = [_p(i, "CB", 500 + i) for i in range(8)] + [_p(100 + i, "ST", 600) for i in range(5)]
    players += [_p(200, "CB", 300), _p(201, "DF", 2000), _p(202, "GK", 800), _p(203, "CB", 455)]
    doc = F.build({"ok": True, "minutes_floor": 460, "players": players})
    v = {x["key"]: x for x in doc["views"]}
    # 450 minutes and the competition's floor (460): the 455-minute and 300-minute players are out; a coarse role
    # (DF: substitute-only) and a goalkeeper under 900 never qualify; five strikers are too few for a board
    assert v["all"]["n"] == 13 and v["cb"]["n"] == 8
    assert "st" not in v and "gk" not in v and "clubs" not in v
    cb = v["cb"]["metrics"]
    assert cb[0]["key"] == "gar90" and cb[0]["ours"]
    aer = next(m for m in cb if m["key"] == "aerial_pct")
    assert aer["fmt"] == "pct1" and aer["top"][0][3] == 0.47       # stored as a share
    assert aer["top"][0][2] == "7"                                 # the team is the club id
    assert "460 minutes" in v["cb"]["min"]


def test_signed_values_never_read_minus_zero():
    players = [_p(i, "CB", 900, gar90=-0.001 * i) for i in range(8)]
    g = next(m for m in F.build({"players": players})["views"][0]["metrics"] if m["key"] == "gar90")
    assert all(not (r[3] == 0 and str(r[3]).startswith("-")) for r in g["top"] + g["bot"])
    assert g["top"][0][3] == 0.0


def test_clubs_skip_possession_and_early_sides(tmp_path):
    teams = {f"C{i}": {"played": 6 if i else 3, "profile": {"xg_diff": {"v": i / 10}, "possession": {"v": 50 + i}, "xg_against": {"v": 2 - i / 10},
                                                            "field_tilt": {"v": 40 + i}}} for i in range(8)}
    ids = {"teams": {f"C{i}": {"team_id": 100 + i} for i in range(8)}}
    doc = F.build({"players": []}, {"teams": teams}, ids)
    clubs = doc["views"][-1]
    assert clubs["key"] == "clubs" and clubs["entity"] == "team" and clubs["n"] == 7     # C0 has 3 matches
    keys = [m["key"] for m in clubs["metrics"]]
    assert "possession" not in keys and "xg_diff" in keys
    xga = next(m for m in clubs["metrics"] if m["key"] == "xg_against")
    assert xga["dir"] == "lower" and xga["top"][0][0] == "107"
    # write_all: every folder with players_live, an empty document when nothing qualifies
    (tmp_path / "cup").mkdir()
    (tmp_path / "cup" / "players_live.json").write_text(json.dumps({"ok": True, "players": [_p(1, "CB", 90)]}), encoding="utf-8")
    (tmp_path / "other").mkdir()
    out = F.write_all(tmp_path)
    assert list(out) == ["cup"]
    assert json.loads((tmp_path / "cup" / "performers.json").read_text(encoding="utf-8"))["views"] == []


def test_value_fields_apply_writes_performers(tmp_path):
    from oddsmarkets.football.analytics import value_fields
    (tmp_path / "lg").mkdir()
    (tmp_path / "lg" / "players_live.json").write_text(json.dumps({"ok": True, "players": [_p(i, "CB", 900) for i in range(8)]}), encoding="utf-8")
    value_fields.apply(tmp_path)          # no value layer on disk: the performers are still written
    doc = json.loads((tmp_path / "lg" / "performers.json").read_text(encoding="utf-8"))
    assert [v["key"] for v in doc["views"]] == ["all", "cb"]
