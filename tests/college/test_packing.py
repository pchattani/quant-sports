"""Packed payload lists (oddsmarkets/college/packing.py), the TBA start-time rule and the women's region sites."""
import json

from oddsmarkets.college import canon
from oddsmarkets.college.hoops import build as B
from oddsmarkets.college.packing import is_packed, pack, pack_keyed, unpack


def test_pack_round_trip_drops_nulls_and_flattens_one_level():
    cards = [{"id": "1", "home": "5", "hs": 70, "neutral": True, "model": {"p_home": 0.61}, "market": {"spread_home": -3.5}},
             {"id": "2", "home": "6", "hs": None, "model": {"p_home": 0.4}, "result": {"cover": "home", "model_correct": False}},
             {"id": "3", "seed_dist": {"1": 0.5, "2": 0.5}, "line": [1, 2]}]
    p = pack(cards)
    assert is_packed(p) and "model.p_home" in p["$cols"] and "hs" in p["$cols"]
    back = unpack(json.loads(json.dumps(p)))
    assert back[0] == cards[0]
    assert back[1] == {k: v for k, v in cards[1].items() if v is not None}     # None reads as absent
    assert back[2] == cards[2]
    assert "seed_dist" in p["$cols"]                        # objects keyed by data (seeds, ids) stay whole
    many = cards[:2] * 50
    assert len(json.dumps(pack(many))) < 0.6 * len(json.dumps(many))


def test_pack_keyed_and_nested_unpack():
    players = {"10": {"name": "A", "values": {"pts": 12.5}, "pct": {}}, "11": {"name": "B", "values": {"pts": 3.0, "reb": 4.1}}}
    payload = {"ok": True, "players": pack_keyed(players), "page": {"roster": pack([{"id": "10", "gp": 3}])}}
    back = unpack(json.loads(json.dumps(payload)))
    assert back["players"]["10"] == players["10"]
    assert back["players"]["11"] == players["11"]
    assert back["page"]["roster"] == [{"id": "10", "gp": 3}]


def test_time_tba_midnight_eastern_placeholder():
    assert canon.time_tba({"status": "pre", "date": "2026-11-28T05:00Z"})          # 00:00 EST
    assert canon.time_tba({"status": "pre", "date": "2026-10-03T04:00Z"})          # 00:00 EDT
    assert canon.time_tba({"status": "pre", "date": "2026-10-03T19:00Z", "tba": True})
    assert not canon.time_tba({"status": "pre", "date": "2026-11-28T04:59Z"})      # a real 7 pm Hawaii tip-off
    assert not canon.time_tba({"status": "pre", "date": "2026-10-03T05:00Z"})      # 01:00 EDT
    assert not canon.time_tba({"status": "post", "date": "2026-11-28T05:00Z"})


def test_thin_wp_keeps_the_shape():
    s = [[0, 0.5], [1, 0.501], [2, 0.503], [3, 0.52], [4, 0.521], [5, 0.9], [6, 1.0]]
    t = B.thin_wp(s)
    assert t[0] == s[0] and t[-1] == s[-1] and [3, 0.52] in t and [5, 0.9] in t and [1, 0.501] not in t


def test_region_sites():
    g = lambda reg, note: {"region": reg, "round": "Sweet 16", "note": note}
    ncaa = [g("Regional 1", "NCAA Women's Championship - Regional 1 in Albany - Sweet 16"),
            g("Regional 2", "NCAA Women's Championship pres. by Capital One - Greenville Regional 2 - Sweet 16")]
    assert B.region_sites(ncaa, ["Regional 1", "Regional 2"]) == {"Regional 1": "Albany", "Regional 2": "Greenville"}
    assert B.region_sites([], ["Oklahoma City", "East"]) == {"Oklahoma City": "Oklahoma City"}
