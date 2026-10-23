"""Kit v3 rail rings (Footballer): last season's formation-role percentiles in people/<pid>.json `current`."""
from __future__ import annotations

import json

from oddsmarkets.football.analytics import value_fields as VF

GROUPS = [{"id": "cb", "codes": ["CB"], "min": 450.0, "metrics": [("gar90", False), ("aerials_won_90", False), ("fouls_90", True)]},
          {"id": "st", "codes": ["ST"], "min": 450.0, "metrics": [("gar90", False)]}]


def _rows(n=8):
    return [{"player_id": i, "minutes": 2000, "aerials_won_90": float(i), "fouls_90": float(i)} for i in range(1, n + 1)]


def test_prev_role_pct_matches_the_front_end_rule():
    rows = _rows() + [{"player_id": 99, "minutes": 100, "aerials_won_90": 50.0}]       # under the minimum: not a peer
    prev = {str(i): {"role": "CB", "gar90": 0.01 * i} for i in range(1, 9)} | {"99": {"role": "CB", "gar90": 9.0}}
    got = VF.prev_role_pct(rows, prev, GROUPS, floor=600.0)
    assert set(got) == {str(i) for i in range(1, 9)}
    g, pc = got["8"]
    assert g == "cb" and pc["aerials_won_90"] == 94 and pc["gar90"] == 94     # (7 + 0.5) / 8
    assert pc["fouls_90"] == 6                                                # lower is better: turned round
    assert got["1"][1]["aerials_won_90"] == 6


def test_annotate_people_prev_writes_same_group_only(tmp_path, monkeypatch):
    monkeypatch.setattr(VF, "spec_groups", lambda: GROUPS)
    d = tmp_path
    (d / "lg" / "s" / "100").mkdir(parents=True)
    (d / "people").mkdir()
    (d / "lg" / "seasons.json").write_text(json.dumps({"seasons": [{"sid": 200, "season": "26/27", "path": ""},
                                                                    {"sid": 100, "season": "25/26", "path": "s/100/"}]}))
    (d / "lg" / "s" / "100" / "season.json").write_text(json.dumps({"players": _rows()}))
    (d / "lg" / "players_live.json").write_text(json.dumps({"players": [{"player_id": 8, "role": "CB"}, {"player_id": 7, "role": "ST"},
                                                                        {"player_id": 50, "role": "CB"}]}))
    for pid in (7, 8, 50):
        (d / "people" / f"{pid}.json").write_text(json.dumps({"id": str(pid)}))
    prev_lines = {(str(i), "lg"): {"role": "CB", "gar90": 0.01 * i, "min": 2000} for i in range(1, 9)}
    n = VF.annotate_people_prev(d, prev_lines, {"lg": "100"})
    assert n == 1
    doc = json.loads((d / "people" / "8.json").read_text())
    assert doc["current"]["prev_pct_pos"]["lg"]["aerials_won_90"] == 94
    assert doc["current"]["prev_peer"]["lg"] == {"sid": "100", "season": "25/26", "role": "CB", "group": "cb", "min": 2000}
    assert "current" not in json.loads((d / "people" / "7.json").read_text())     # CB last season, ST now: no ring
    assert "current" not in json.loads((d / "people" / "50.json").read_text())    # no line last season


def test_spec_groups_read_the_metrics_spec():
    gs = VF.spec_groups()
    assert {g["id"] for g in gs} >= {"cb", "fb", "dm_cm", "am_w", "st", "gk"}
    assert all(g["metrics"] for g in gs)
