"""oddsmarkets/common/progression.py: the deep set, percentiles against each season's peers, and the reference."""
from __future__ import annotations

from oddsmarkets.common import progression as PR


def test_group_keys_put_headline_first_in_spec_order():
    keys = PR.group_keys("hockey", "forwards")
    assert keys[0] == "gar_60" and "p60" in keys[:9]
    assert len(keys) == len(set(keys)) and len(keys) > 20


def test_deep_keys_union_and_filter():
    have = {"gar_60", "p60", "rapm_def", "hits60"}
    k = PR.deep_keys("hockey", ["forwards", "defence"], have)
    assert set(k) <= have and k[0] == "gar_60" and "rapm_def" in k


def test_place_mid_rank_and_direction():
    pool = sorted([1.0, 2.0, 3.0, 4.0])
    assert PR.place(pool, 4.0) == 88 and PR.place(pool, 1.0) == 12
    assert PR.place(pool, 1.0, lower=True) == 88
    assert PR.place(pool, 2.5) == 50


def test_rnd_four_significant_figures():
    assert PR.rnd(0.123456) == 0.1235 and PR.rnd(12.3456) == 12.35 and PR.rnd(3) == 3 and PR.rnd(None) is None
    assert PR.rnd(float("nan")) is None


def test_builder_fills_rows_and_reference():
    pb = PR.Builder("hockey", {"skater": ["gar_60", "adj_xga60"]})
    hs = [pb.add(20242025, "skater", "forwards", {"gar_60": i / 10, "adj_xga60": 3 - i / 10}, True) for i in range(10)]
    small = pb.add(20242025, "skater", "forwards", {"gar_60": 5.0}, False)
    site = pb.add(20242025, "skater", "forwards", {"gar_60": 0.45, "adj_xga60": 2.5}, True, pct={"gar_60": 61})
    pb.finish()
    assert hs[9]["dv"] == [0.9, 2.1] and hs[9]["pg"] == "forwards"
    assert hs[9]["dp"][0] > 90 and hs[9]["dp"][1] > 90          # adj_xga60 is lower-is-better: the lowest ranks top
    assert "dp" not in small and small["dv"] == [5, None]
    assert site["dp"][0] == 61                                  # the site's own percentile wins
    ref = pb.reference(lengths={20242025: 82})
    g = ref["seasons"]["20242025"]["forwards"]
    assert g["n"] == 11 and len(g["m"]["gar_60"]) == 5 and ref["seasons"]["20242025"]["len"] == 82
    assert ref["groups"]["forwards"]["keys"] == ["gar_60", "adj_xga60"] and ref["q"] == [10, 25, 50, 75, 90]


def test_small_pool_gets_no_percentile():
    pb = PR.Builder("hockey", {"goalie": ["gsax100"]})
    h = [pb.add(2010, "goalie", "goalies", {"gsax100": i}, True) for i in range(3)]
    pb.finish()
    assert all("dp" not in x for x in h) and pb.reference()["seasons"] == {}
