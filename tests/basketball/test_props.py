"""Kalshi player-prop availability (research/props.py, props_eval.py) and the availability split in game cards."""
from __future__ import annotations

from oddsmarkets.basketball.analytics.games import _av_card
from oddsmarkets.basketball.research import props as PR
from oddsmarkets.basketball.research import props_eval as E


def test_title_names_and_quotes():
    assert PR._title_name("Draymond Green: 10+ points") == "Draymond Green"
    assert PR._title_name("Julius Randle records 15+ points") == "Julius Randle"
    assert PR.fold("De'Aaron Fox") == "deaaronfox" and PR.fold("Jaren Jackson Jr.") == "jarenjackson"
    cs = [{"end_period_ts": 100, "yes_bid": {"close": "0.40"}, "yes_ask": {"close": "0.45"}},
          {"end_period_ts": 200, "yes_bid": {"close": "0.00"}, "yes_ask": {"close": "0.99"}}]
    assert PR.quote_at(cs, 150) == {"bid": 0.40, "ask": 0.45, "end": 100}
    assert PR.quote_at(cs, 99) is None
    rows = [{"pid": "1", "open_ts": 50, "candles": cs}, {"pid": "2", "open_ts": 300, "candles": []}, {"pid": None, "open_ts": 0}]
    st = PR.state_at(rows, 150)
    assert st["1"]["listed"] and st["1"]["bid"] == 0.40 and not st["2"]["listed"] and len(st) == 2


def test_override_rule():
    rates = {"listed_bid": 0.99, "listed_nobid": 0.9, "unlisted_regular": 0.2, "active_min": 2, "reg_min": 2,
             "reg_share": 0.5}
    state = {"a": {"listed": True, "bid": 0.3}, "b": {"listed": True, "bid": 0.0}, "c": {"listed": False, "bid": None}}
    team = {p: {} for p in ("a", "b", "c", "d", "e")}
    hist = {"c": [4, 3], "d": [4, 1], "e": [1, 1]}
    ov = E.overrides(state, team, hist, rates)
    assert ov["a"] == 0.99 and ov["b"] == 0.9
    assert ov["c"] == -1.0                       # an unlisted regular: the caller caps his streak rate at 0.2
    assert "d" not in ov and "e" not in ov       # listed in under half his games / too few games
    # one listed player: the team is not active, unlisted players keep the streak rate
    ov1 = E.overrides({"a": {"listed": True, "bid": 0.3}}, team, hist, rates)
    assert set(ov1) == {"a"}


def test_card_availability_is_each_teams_own_margin():
    m = {"model": "informed", "detail": {"injury_home": -1.234, "injury_away": 0.5}}
    assert _av_card(m) == {"av": [-1.23, -0.5]}
    assert _av_card({"model": "base", "detail": {"injury_home": 0.0, "injury_away": 0.0}}) == {}
