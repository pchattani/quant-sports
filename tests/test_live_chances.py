"""scripts/live_chances.py: live win chances in the feed come from the site's own live model and from the numbers its
last build published, never from another model; pacing; and winprob.live_now is the one function both readers use."""
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("live_chances", ROOT / "scripts" / "live_chances.py")
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

from oddsmarkets.basketball.models import winprob as W  # noqa: E402
from oddsmarkets.basketball.sources import espn  # noqa: E402

MODEL = {"version": "wp-2", "K": 20.0, "beta": [5.3, -1.26, 6.3, 2.9, -0.7]}
NOW = 1_800_000_000


def feed_and_state(entry):
    feed = {"v": 1, "at": NOW, "sports": {"basketball": {"t": NOW, "g": {"1": dict(entry)}}}}
    state = {"boards": {"nba": {"g": {"1": dict(entry)}}, "wnba": {"g": {}}}}
    return feed, state


def index(model=MODEL, wp_s=4.5):
    return {"leagues": {"nba": {"wp_model": model, "today": [{"id": "1", "wp_s": wp_s}], "next_games": []}}}


@pytest.fixture
def fake_model(monkeypatch):
    seen = {}

    def live_now(model, pbp, game, league="nba", exp_margin_=None):
        seen.update(model=model, s=exp_margin_, league=league)
        return {"wp_home": 0.6123}
    monkeypatch.setattr(W, "live_now", live_now)
    monkeypatch.setattr(espn, "compact_pbp", lambda raw: {"plays": []})
    monkeypatch.setattr(espn, "compact_game", lambda raw: {"id": "1"})
    return seen


def test_chance_uses_the_published_model_and_margin(fake_model):
    feed, state = feed_and_state({"s": "live", "hs": 50, "as": 48, "p": 2, "c": "5:00"})
    calls = []
    n, used = lc.basketball(feed, state, NOW, lambda u, p=None: index(), summary=lambda lg, gid: calls.append((lg, gid)) or {"header": 1})
    assert (n, used, calls) == (1, 1, [("nba", "1")])
    assert feed["sports"]["basketball"]["g"]["1"]["wp"] == 0.6123
    assert fake_model["model"]["K"] == 20.0 and fake_model["model"]["beta"] == MODEL["beta"] and fake_model["s"] == 4.5


def test_no_published_model_no_chance(fake_model):
    feed, state = feed_and_state({"s": "live", "hs": 50, "as": 48, "p": 2, "c": "5:00"})
    calls = []
    n, used = lc.basketball(feed, state, NOW, lambda u, p=None: index(model=None), summary=lambda lg, gid: calls.append(gid) or {"header": 1})
    assert (n, used, calls) == (0, 0, []) and "wp" not in feed["sports"]["basketball"]["g"]["1"]
    assert not hasattr(lc, "fitted_model")          # the committed file is a different model from the build's refit


def test_pacing_and_age(fake_model):
    e = {"s": "live", "hs": 50, "as": 48, "p": 2, "c": "5:00"}
    feed, state = feed_and_state(e)
    calls = []
    get, summ = (lambda u, p=None: index()), (lambda lg, gid: calls.append(gid) or {"header": 1})
    lc.basketball(feed, state, NOW, get, summary=summ)
    # nothing moved: no new summary, the chance is carried into the next tick's (rewritten) feed
    feed2, _ = feed_and_state(e)
    assert lc.basketball(feed2, state, NOW + 30, get, summary=summ) == (1, 0) and feed2["sports"]["basketball"]["g"]["1"]["wp"] == 0.6123
    # the score moved 20 s after the last summary: too soon to ask again, the last chance stands for now
    e2 = dict(e, hs=52)
    feed3, st3 = feed_and_state(e2)
    state["boards"] = st3["boards"]
    assert lc.basketball(feed3, state, NOW + 20, get, summary=summ) == (1, 0)
    assert lc.basketball(feed_and_state(e2)[0], state, NOW + 50, get, summary=summ) == (1, 1) and len(calls) == 2
    # a chance that could not be refreshed for over four minutes is dropped
    e3 = dict(e2, hs=60)
    state["boards"]["nba"]["g"]["1"] = e3
    feed5 = feed_and_state(e3)[0]
    assert lc.basketball(feed5, state, NOW + 50 + 300, get, summary=lambda lg, gid: None) == (0, 1)
    assert "wp" not in feed5["sports"]["basketball"]["g"]["1"]
    # the game is over: forgotten
    state["boards"]["nba"]["g"]["1"] = dict(e3, s="final")
    assert lc.basketball(feed_and_state(dict(e3, s="final"))[0], state, NOW + 400, get, summary=summ) == (0, 0)
    assert state["chances"]["basketball"] == {}


def test_live_now_is_the_model_at_the_last_play(monkeypatch):
    model = dict(MODEL, ok=True)
    st = pd.DataFrame({"game_id": "1", "seq": [1, 2], "period": [1, 2], "clock_s": [700.0, 300.0], "margin": [2.0, -5.0],
                       "t_left": [2860.0, 1740.0], "poss": [1.0, -1.0], "exp_margin": 2.5, "league": "nba", "home_win": None,
                       "espn_wp": [None, 0.31]})
    monkeypatch.setattr(W, "states_from_pbp", lambda pbp, game, possessions=None, league="nba": st.copy())
    r = W.live_now(model, {"plays": [1]}, {"id": "1"}, "nba")
    assert r["wp_home"] == round(float(W.wp(model, {"margin": -5.0, "t_left": 1740.0, "period": 2, "poss": -1, "exp_margin": 2.5, "league": "nba"})), 4)
    assert (r["clock"], r["period"], r["espn_wp"]) == ("5:00", 2, 0.31)
    # the published pregame margin replaces the one read from the game
    r2 = W.live_now(model, {"plays": [1]}, {"id": "1"}, "nba", 9.0)
    assert r2["exp_margin"] == 9.0 and r2["wp_home"] > r["wp_home"]
    assert W.live_now(None, {"plays": [1]}, {}, "nba") is None and W.live_now(model, None, {}, "nba") is None


def test_the_build_publishes_what_the_live_loop_reads():
    b = (ROOT / "scripts" / "build_hardwood.py").read_text(encoding="utf-8")
    assert 'out["leagues"][lg]["wp_model"]' in b
    g = (ROOT / "oddsmarkets" / "basketball" / "analytics" / "games.py").read_text(encoding="utf-8")
    assert '"wp_s"' in g and "W.live_now(ctx.wp_model, raw, g, ctx.league)" in g
    kit = (ROOT / "docs" / "_design" / "quant.js").read_text(encoding="utf-8")
    assert "isNum(e.wp) ? e.wp : null" in kit
