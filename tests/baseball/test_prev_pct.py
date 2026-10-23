"""Kit v3 rail rings: last season's position / role percentiles ride on current.hitting / current.pitching."""
from __future__ import annotations

from oddsmarkets.baseball.analytics import careers as CR


def test_prev_pct_same_level_and_peer_group():
    cats = {("mlb", 2025, "hitters"): {"players": {"1": {"pos": "LF", "pa": 600, "qualified": True, "pct_role": {"xwoba_plus": 90}},
                                                   "2": {"pos": "SS", "pa": 500, "qualified": True, "pct_role": {"xwoba_plus": 40}}}},
            ("mlb", 2025, "pitchers"): {"players": {"3": {"role": "SP", "bf": 700, "qualified": True, "pct_role": {"k_pct": 70}},
                                                    "4": {"role": "RP", "bf": 250, "qualified": True, "pct_role": {"k_pct": 95}}}}}
    blocks = {"1": {"season": 2026, "level": "mlb", "hitting": {"pos": "RF"}},          # LF -> RF: same group (LF/RF)
              "2": {"season": 2026, "level": "mlb", "hitting": {"pos": "2B"}},          # SS -> 2B: no ring
              "3": {"season": 2026, "level": "mlb", "pitching": {"role": "SP"}},
              "4": {"season": 2026, "level": "mlb", "pitching": {"role": "SP"}},        # RP -> SP: no ring
              "5": {"season": 2026, "level": "aaa", "hitting": {"pos": "C"}}}
    n = CR.add_prev_pct(blocks, lambda lvl, s, kind: cats.get((lvl, s, kind)))
    assert n == 2
    assert blocks["1"]["hitting"]["prev_pct_pos"] == {"xwoba_plus": 90}
    assert blocks["1"]["hitting"]["prev_peer"] == {"level": "mlb", "season": 2025, "group": "LF/RF", "pa": 600, "qualified": True}
    assert "prev_pct_pos" not in blocks["2"]["hitting"]
    assert blocks["3"]["pitching"]["prev_peer"]["bf"] == 700 and blocks["3"]["pitching"]["prev_pct_pos"] == {"k_pct": 70}
    assert "prev_pct_pos" not in blocks["4"]["pitching"]
