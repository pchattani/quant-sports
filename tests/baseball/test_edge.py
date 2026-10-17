"""Edge research pieces (models/edge.py), the run-line orientation fix, backtest decision-time variants and the
game_env regression. No network, no data on disk."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.baseball.models import backtest as BT
from oddsmarkets.baseball.models import edge as E
from oddsmarkets.baseball.sources import markets as MK


# ── run lines stored the wrong way round ─────────────────────────────────────

def test_run_line_swapped_rule():
    # home -1.5 cannot cover more often than home wins; home +1.5 cannot cover less often
    assert MK.run_line_swapped(0.55, -1.5, 0.62)
    assert not MK.run_line_swapped(0.55, -1.5, 0.38)
    assert MK.run_line_swapped(0.45, 1.5, 0.40)
    assert not MK.run_line_swapped(0.45, 1.5, 0.62)
    assert not MK.run_line_swapped(None, -1.5, 0.7)
    assert not MK.run_line_swapped(0.5, None, 0.7)


def test_store_lines_orients_swapped_run_line():
    # gpk 661041 (2022): home -125 favourite at -1.5 stored at -180 / +155 (impossible); the fix reads +155
    g = {"lines": {"ml": [-125, 105], "rl": {"home": -1.5, "price": [-180, 155]}, "total": None}}
    ln = MK.store_lines(g, "close")
    assert ln["rl_home"] == -1.5
    assert ln["p_rl_home"] < ln["p_home"]
    assert ln["p_rl_home"] == pytest.approx(1 - (180 / 280) / (180 / 280 + 100 / 255), abs=1e-4)
    ok = {"lines": {"ml": [-125, 105], "rl": {"home": -1.5, "price": [155, -180]}, "total": None}}
    assert MK.store_lines(ok, "close")["p_rl_home"] == pytest.approx(ln["p_rl_home"], abs=1e-5)


def test_game_prices_orient_and_drop_in_game_lines():
    g = {"lines": {"src": "DraftKings", "ml": [-125, 105], "rl": {"home": -1.5, "price": [-180, 155]},
                   "total": {"line": 8.5, "over": -110, "under": -110},
                   "open": {"ml": [-120, 100], "rl": {"home": -1.5, "price": [-170, 145]},
                            "total": {"line": 18.5, "over": -110, "under": -110}},
                   "close": {"ml": [-125, 105], "rl": {"home": -1.5, "price": [-180, 155]},
                             "total": {"line": 8.5, "over": -110, "under": -110}},
                   "books": [{"id": "100", "name": "DraftKings", "ml": [-125, 105], "rl": {"home": -1.5, "price": [-180, 155]},
                              "total": {"line": 8.5, "over": -110, "under": -110}}]}}
    pr = E.game_prices(g)
    assert pr["close"]["rl_h"] == pytest.approx(2.55) and pr["close"]["rl_a"] == pytest.approx(1 + 100 / 180)
    assert pr["open"]["rl_h"] == pytest.approx(2.45)
    assert "tot" not in pr["open"]                      # an 18.5 total is an in-game line
    assert pr["close"]["tot"] == 8.5


# ── decision-time variants ───────────────────────────────────────────────────

def test_variant_game_open_hides_lineups_and_wind():
    g = {"gpk": "1", "lineups": {"1": list("abcdefghi")}, "weather": {"temp": 81, "wind": "12 mph, Out To CF", "cond": "Sunny"},
         "probables": {"home": "p1", "away": "p2"}, "umpire_hp": "u"}
    o = BT.variant_game(g, "open")
    assert o["lineups"] is None and "wind" not in o["weather"] and o["weather"]["temp"] == 81
    assert o["probables"] == g["probables"] and o["umpire_hp"] == "u"
    assert g["lineups"] and "wind" in g["weather"]          # the store record is untouched
    assert BT.variant_game(g, "post") is g
    with pytest.raises(ValueError):
        BT.variant_game(g, "noon")
    assert BT.cache_name("mlb", 2025, 1000) == f"mlb_2025_n1000_v{BT.VERSION}.json"
    assert BT.cache_name("mlb", 2025, 1000, "open").endswith("_open.json")


# ── Kalshi ───────────────────────────────────────────────────────────────────

def test_parse_kalshi_event():
    assert E.parse_kalshi_event("KXMLBGAME-26AUG021605DETATH", ["ATH", "DET"]) == \
        {"date": "2026-08-02", "hhmm": "1605", "away": "DET", "home": "ATH"}
    assert E.parse_kalshi_event("KXMLBGAME-25APR16ATHCWS", ["ATH", "CWS"]) == \
        {"date": "2025-04-16", "hhmm": None, "away": "ATH", "home": "CWS"}
    assert E.parse_kalshi_event("KXMLBGAME-26AUG02SFSD", ["SD", "SF"])["home"] == "SD"
    assert E.parse_kalshi_event("bad", ["A", "B"]) is None


def test_kalshi_quotes_relative_to_first_pitch():
    st = 1_000_000
    rows = [(st - 30 * 3600, None, 0.6, 0.0), (st - 20 * 3600, 0.50, 0.55, 5.0), (st - 2 * 3600, 0.52, 0.54, 10.0),
            (st - 3600, 0.53, 0.55, 1.0), (st, 0.60, 0.62, 3.0), (st + 3600, 0.90, 0.95, 50.0)]
    q = E.kalshi_quotes(rows, st)
    assert (q["open_bid"], q["open_ask"]) == (0.50, 0.55)
    assert (q["1h_bid"], q["1h_ask"]) == (0.53, 0.55)
    assert (q["close_bid"], q["close_ask"]) == (0.60, 0.62)
    assert q["volume_pre"] == pytest.approx(19.0)            # nothing traded in play counts


def test_match_kalshi_pairs_doubleheaders_by_time():
    kt = pd.DataFrame([
        {"event": "E1", "code": "DET", "date": "2026-08-02", "hhmm": "1305", "away": "DET", "home": "ATH", "result": 1.0,
         "candles": [(1785690000 - 7200, 0.40, 0.42, 1.0)]},
        {"event": "E2", "code": "ATH", "date": "2026-08-02", "hhmm": "1905", "away": "DET", "home": "ATH", "result": 0.0,
         "candles": []}])
    games = pd.DataFrame([
        {"gpk": "g2", "home_abbr": "ATH", "away_abbr": "DET", "start_time": "2026-08-02T23:05:00Z"},
        {"gpk": "g1", "home_abbr": "ATH", "away_abbr": "DET", "start_time": "2026-08-02T17:05:00Z"}])
    m = E.match_kalshi(kt, games).set_index("event")
    assert m.loc["E1", "gpk"] == "g1" and m.loc["E1", "k_home"] == 0
    assert m.loc["E2", "gpk"] == "g2" and m.loc["E2", "k_home"] == 1


# ── distributions, blends, walk-forward ──────────────────────────────────────

def test_p_over_p_cover_and_shift():
    d = np.zeros(31)
    d[[7, 8, 9, 10]] = [0.25, 0.25, 0.25, 0.25]
    assert E.p_over(d, 8.5) == pytest.approx(0.5)
    assert E.p_over(d, 8.0) == pytest.approx(2 / 3)          # the push at 8 is excluded
    md = {-2: 0.2, -1: 0.2, 1: 0.3, 2: 0.3}
    assert E.p_cover(md, -1.5) == pytest.approx(0.3)
    assert E.p_cover(md, 1.5) == pytest.approx(0.8)
    s = E.shift_dist(d, 0.5)
    k = np.arange(31)
    assert s.sum() == pytest.approx(1.0)
    assert (s * k).sum() == pytest.approx((d * k).sum() + 0.5, abs=1e-9)


def test_walk_forward_uses_only_earlier_months():
    rng = np.random.default_rng(0)
    n = 3000
    dates = np.repeat(["2025-04-15", "2025-05-15", "2025-06-15"], n)
    x = rng.normal(size=3 * n)
    # x predicts the result in April-May; in June it is pure noise: a fit that saw June would weaken b there
    y = np.where(dates < "2025-06", rng.random(3 * n) < E.sigmoid(1.5 * x), rng.random(3 * n) < 0.5).astype(float)
    df = pd.DataFrame({"date": dates, "season": 2025, "x": x, "y": y, "off": 0.0})
    p = E.walk_forward(df, ["x"], "y", "off", min_train=1000, l2=1e-3)
    apr, jun = df["date"] == "2025-04-15", df["date"] == "2025-06-15"
    assert np.allclose(p[apr], 0.5)                        # no earlier data: the offset alone
    b_jun = np.polyfit(x[jun], E.logit(p[jun]), 1)[0]
    assert b_jun == pytest.approx(1.5, abs=0.25)          # fitted on April-May only


def test_park_debias_is_walk_forward():
    df = pd.DataFrame({"date": ["2025-04-01", "2025-04-02", "2025-04-02", "2025-04-03"], "gpk": ["a", "b", "c", "d"],
                       "venue": ["v", "v", "w", "v"], "dev": [1.0, 2.0, 5.0, 0.0]})
    out = E.park_debias(df, "dev", k=0.0)
    assert out[0] == pytest.approx(1.0)                   # nothing earlier at v
    assert out[1] == pytest.approx(2.0 - 1.0)             # the earlier v game only
    assert out[2] == pytest.approx(5.0)                   # w has no history; same-day games never count
    assert out[3] == pytest.approx(0.0 - 1.5)


def test_fit_logistic_recovers_coefficient_with_offset():
    rng = np.random.default_rng(1)
    x = rng.normal(size=20000)
    off = rng.normal(scale=0.5, size=20000)
    y = (rng.random(20000) < E.sigmoid(off + 0.4 * x)).astype(float)
    b = E.fit_logistic(x[:, None], y, off, l2=1e-3)
    assert b[0] == pytest.approx(0.4, abs=0.05)


def test_boot_ci_groups():
    x = np.array([1.0, 1.0, -1.0, -1.0])
    est, lo, hi = E.boot_ci(x, np.array(["a", "a", "b", "b"]), n=500)
    assert est == pytest.approx(0.0) and lo <= est <= hi


# ── projections.game_env without dates (crashed before 2 October 2026) ───────

def test_game_env_without_dates(monkeypatch):
    from oddsmarkets.baseball.models import projections as PJ
    ne = len(PJ.EVENTS)
    prev = pd.Series({e: 100.0 for e in PJ.EVENTS})
    monkeypatch.setattr(PJ, "season_env", lambda level, s, partial=None: prev)
    monkeypatch.setattr(PJ, "league_days", lambda level, s: {f"04-{d:02d}": np.full(ne, 10.0) for d in range(1, 29)})
    to = pd.DataFrame({e: [20.0] for e in PJ.EVENTS})
    env = PJ.game_env("mlb", 2099, "ros", {2099: to}, dates=None)
    assert env is not None and np.isfinite(env).all() and env.sum() == pytest.approx(1.0)


def test_kalshi_price_includes_taker_fee():
    assert E.kalshi_dec(0.50) == pytest.approx(1 / (0.50 + 0.07 * 0.25))
    assert E.kalshi_dec(0.50) < 2.0
    assert E.kalshi_dec(0.0) is None and E.kalshi_dec(1.0) is None and E.kalshi_dec(None) is None
