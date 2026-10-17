"""Totals calibration in the game model and the edge-research helpers (synthetic data, no network)."""
from __future__ import annotations

import numpy as np
import pytest

from oddsmarkets.basketball.models import game as GM
from oddsmarkets.basketball.models import ratings as R
from oddsmarkets.basketball.research import evaluate as V
from oddsmarkets.basketball.research import lines as LN


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HARDWOOD_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDWOOD_DATA", str(tmp_path / "data"))
    GM.set_params("nba", None)
    yield
    GM.set_params("nba", None)


def test_fit_total_recovers_calibration():
    rng = np.random.default_rng(1)
    rows = []
    for k in range(3000):
        base = rng.normal(225, 8)
        post = k % 10 == 0
        tot = 8.0 + 0.97 * base - 6.0 * post + rng.normal(0, 3)
        rows.append({"base_total": base, "hs": tot / 2, "as": tot / 2, "stype": "post" if post else "reg"})
    f = GM.fit_total(rows)
    assert f["total_a"] == pytest.approx(8.0, abs=3.0)
    assert f["total_b"] == pytest.approx(0.97, abs=0.015)
    assert f["total_post"] == pytest.approx(-6.0, abs=0.5)
    assert GM.fit_total(rows[:50]) == {"total_a": 0.0, "total_b": 1.0, "total_post": 0.0}


def test_predict_applies_total_calibration_only_to_the_total():
    rt = {"teams": {"1": {"off": 118, "def": 112, "net": 6, "pace": 100}, "2": {"off": 114, "def": 116, "net": -2, "pace": 98}},
          "league_ortg": 115, "league_pace": 99}
    base = {"league": "nba", "ratings": rt}
    GM.set_params("nba", {"total_a": 0.0, "total_b": 1.0, "total_post": 0.0})
    a = GM.predict("1", "2", "2026-01-10", dict(base))
    GM.set_params("nba", {"total_a": 5.0, "total_b": 1.0, "total_post": -6.0})
    b = GM.predict("1", "2", "2026-01-10", dict(base))
    c = GM.predict("1", "2", "2026-05-10", {**base, "stype": "post"})
    assert b["margin"] == pytest.approx(a["margin"]) and b["p_home"] == pytest.approx(a["p_home"])
    assert b["total"] == pytest.approx(a["total"] + 5.0)
    assert c["total"] == pytest.approx(a["total"] - 1.0)
    assert b["pts_home"] - b["pts_away"] == pytest.approx(a["pts_home"] - a["pts_away"])
    assert b["total_raw"] == pytest.approx(a["total"])


def test_roster_prior_is_on_for_both_leagues():
    assert set(R.ROSTER_PRIOR_LEAGUES) == {"nba", "wnba"}


def test_margin_probs_sum_to_one_and_push_only_on_integers():
    w, e, l_ = V.margin_probs(3.0, 12.0, -3.5)
    assert e == pytest.approx(0.0) and w + l_ == pytest.approx(1.0)
    w, e, l_ = V.margin_probs(3.0, 12.0, -3.0)
    assert 0.02 < e < 0.05 and w + e + l_ == pytest.approx(1.0)
    w, e, l_ = V.margin_probs(0.0, 12.0, 0.0)          # pick'em: no ties in basketball, so no push
    assert e == pytest.approx(0.0) and w == pytest.approx(0.5, abs=1e-9)
    o, p, u = V.total_probs(220.0, 18.0, 220.0)
    assert o == pytest.approx(u) and o + p + u == pytest.approx(1.0)


def test_implied_mean_round_trip():
    for line, mu in ((-5.5, 4.0), (3.0, -2.5), (-10.0, 12.0)):
        w, e, l_ = V.margin_probs(mu, 12.5, line)
        assert V.implied_mean(float(w / (w + l_)), line, 12.5, "spread") == pytest.approx(mu, abs=1e-3)
    o, p, u = V.total_probs(231.0, 18.0, 228.5)
    assert V.implied_mean(float(o / (o + u)), 228.5, 18.0, "total") == pytest.approx(231.0, abs=1e-3)


def test_devig_and_line_parsing():
    a, b = LN.devig2(-110, -110)
    assert a == pytest.approx(0.5)
    assert LN.devig2(-110, None) is None
    books = [{"id": "58", "name": "ESPN BET", "live": False, "spread": -6.5, "total": 224.5, "ml_h": -240, "ml_a": 200,
              "open": {"ml_h": -290, "ml_a": 240, "sp_h": -7.5, "spo_h": -110, "spo_a": -110, "tot": 226.5, "over": -120, "under": 100},
              "close": {"ml_h": -240, "ml_a": 200, "sp_h": -6.5, "spo_h": -110, "spo_a": -110, "tot": 224.5, "over": -110, "under": -110}},
             {"id": "59", "name": "ESPN Bet - Live Odds", "live": True, "spread": 1.5, "total": 247.5}]
    g = LN.parse_game(books, "nba")
    assert g["src"] == "espn_espnbet" and g["open"]["sp_h"] == -7.5 and g["close"]["tot"] == 224.5
    snap = LN.parse_game([{"id": "1004", "name": "consensus", "live": False, "spread": 3.5, "total": 212.0,
                           "ml_h": 140, "ml_a": -159}], "nba")
    assert snap["open"] is None and snap["close"]["sp_h"] == 3.5 and snap["src"] == "espn_snap_1004"
    assert LN.parse_game([{"id": "1004", "name": "x", "live": False, "spread": 3.5, "total": 999.0}], "nba")["close"]["tot"] is None


def _box_game(gid, h_secs):
    from oddsmarkets.basketball.models._io import BOX_COLS  # noqa: F401
    def side(secs, pts):
        rows = [[f"{gid}p{i}", 1, s, pts // 5, 4, 9, 1, 3, 1, 2, 1, 4, 2, 1, 0, 1, 2, 0] for i, s in enumerate(secs)]
        return {"players": rows, "dnp": [], "team": {"fga": 9 * len(secs) if sum(secs) else 0, "oreb": len(secs) if sum(secs) else 0,
                                                    "fta": 2 * len(secs) if sum(secs) else 0, "tov": len(secs) if sum(secs) else 0}}
    return {"id": gid, "date": "2016-01-05T00:00Z", "status": "post", "stype": "reg", "home": "4", "away": "5",
            "hs": 100, "as": 95, "periods": 4, "box": {"4": side(h_secs, 100), "5": side([576] * 5, 95)}}


def test_box_frame_drops_a_missing_box_score():
    from oddsmarkets.basketball.models import _io
    ok = _io.box_frame({"g1": _box_game("g1", [576] * 5)})
    miss = _io.box_frame({"g2": _box_game("g2", [0] * 5)})
    assert set(ok["team"]) == {"4", "5"}
    assert set(miss["team"]) == {"5"}                       # the zero side contributes no player rows
    assert miss["team_poss"].iloc[0] == pytest.approx(ok["team_poss"].iloc[0])   # possessions from the real side only


def test_team_adjustment_needs_enough_box_games():
    import pandas as pd
    from oddsmarkets.basketball.models import impact as IM
    br = pd.DataFrame({"team": ["4", "4"], "frac": [2.5, 2.5], "team_ortg": [400.0, 400.0], "team_drtg": [50.0, 50.0],
                       "lg_ortg": [104.0, 104.0], "team_box_games": [1, 1], "x": [0.0, 1.0]}, index=["a", "b"])
    model = {"variants": {"box": {"features": ["x"], "mu": [0.5], "sd": [0.5], "coef_o": [0.0, 1.0], "coef_d": [0.0, -1.0]}}}
    out = IM.box_impact(br, model)
    assert out["o"].abs().max() <= 1.0 + 1e-9               # no +60 shift from a one-game team rating
    out2 = IM.box_impact(br.assign(team_box_games=40), model)
    assert out2["o"].abs().max() > 50
