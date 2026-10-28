"""lab.json carries the value model's WAR beside the catalogue metrics (METRICS_SHOWCASE.md, 24 Oct 2026)."""
from __future__ import annotations

from oddsmarkets.basketball.analytics import season as SN


def _cat(players: dict) -> dict:
    return {"min_floor": 100, "players": players}


def test_value_columns_reads_war_by_player_id():
    vp = {"cols": ["id", "name", "war", "hpm"], "rows": [[101, "A", 3.2, 1.5], ["102", "B", -0.4, -2.0], ["bad"]]}
    assert SN.value_columns(vp) == {"101": {"war": 3.2}, "102": {"war": -0.4}}
    assert SN.value_columns(None) == {} and SN.value_columns({"cols": ["name"], "rows": []}) == {}


def test_lab_payload_appends_war_after_the_catalogue_metrics():
    cats = {2026: _cat({"101": {"name": "A", "team": "1", "pool": "G", "gp": 10, "min": 300, "qualified": True, "values": {"hpm": 1.5}},
                        "102": {"name": "B", "team": "2", "pool": "C", "gp": 9, "min": 250, "qualified": True, "values": {"hpm": -2.0}}})}
    out = SN.lab_payload("nba", cats, {2026: {"101": {"war": 3.2}}})
    f = out["fields"]
    assert f[-1] == "war" and f.index("hpm") < f.index("war")
    assert out["metrics"][-1]["key"] == "war" and out["metrics"][-1]["group"] == "Impact"
    rows = {r[0]: r for r in out["rows"]}
    assert rows["101"][f.index("war")] == 3.2
    assert rows["102"][f.index("war")] is None
    assert len(f) == len(rows["101"]) == len(rows["102"])


def test_lab_payload_without_value_is_unchanged():
    cats = {2026: _cat({"101": {"name": "A", "min": 300, "values": {}}})}
    out = SN.lab_payload("nba", cats)
    assert "war" not in out["fields"] and all(m["key"] != "war" for m in out["metrics"])


def test_lab_rows_carry_the_role_peer_group():
    """The Lab's "Compare within: Position" reads `role` (G / W / B): the catalogue's, else classify_roles' rule."""
    cats = {2025: _cat({"101": {"name": "A", "pool": "G", "min": 300, "qualified": True, "role": "G", "values": {}},
                        "102": {"name": "B", "pool": "F", "min": 300, "qualified": True, "role": "B", "values": {}}}),
            2026: _cat({"201": {"name": "C", "pool": "G", "min": 300, "qualified": True, "values": {}},
                        "202": {"name": "D", "pool": "C", "min": 300, "qualified": True, "values": {}},
                        "203": {"name": "E", "pool": "F", "min": 300, "qualified": True, "values": {}}})}
    out = SN.lab_payload("nba", cats)
    i = out["fields"].index("role")
    assert i == out["fields"].index("qualified") + 1
    got = {r[0]: r[i] for r in out["rows"]}
    assert got == {"101": "G", "102": "B", "201": "G", "202": "B", "203": "W"}
