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
