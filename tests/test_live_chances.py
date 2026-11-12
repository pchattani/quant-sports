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
    monkeypatch.setattr(espn, "compact_pbp", lambda raw, min_plays=50: seen.update(min_plays=min_plays) or {"plays": []})
    monkeypatch.setattr(espn, "compact_game", lambda raw: {"id": "1"})
    return seen


def test_chance_uses_the_published_model_and_margin(fake_model):
    feed, state = feed_and_state({"s": "live", "hs": 50, "as": 48, "p": 2, "c": "5:00"})
    calls = []
    n, used = lc.basketball(feed, state, NOW, lambda u, p=None: index(), summary=lambda lg, gid: calls.append((lg, gid)) or {"header": 1})
    assert (n, used, calls) == (1, 1, [("nba", "1")])
    assert feed["sports"]["basketball"]["g"]["1"]["wp"] == 0.6123
    assert fake_model["model"]["K"] == 20.0 and fake_model["model"]["beta"] == MODEL["beta"] and fake_model["s"] == 4.5
    assert fake_model["min_plays"] == 1                # a live game has a chance from its first play, not its fiftieth


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


# ---------------------------------------------------------------------------------------------- Gridiron (NFL)

GID = "2026_10_WAS_NYG"


def nfl_feed_and_state(entry):
    feed = {"v": 1, "at": NOW, "sports": {"nfl": {"t": NOW, "g": {GID: dict(entry)}}}}
    state = {"boards": {"nfl": {"g": {GID: dict(entry, eid="401772999")}}}}
    return feed, state


def nfl_index(fit="fitkey", params="parkey", mu=-0.412, gid=GID):
    return {"season": 2026, "models": {"fits": {"wp": fit}, "game_params": params}, "games": [{"game_id": gid, "wp_mu": mu}], "live": []}


@pytest.fixture
def fake_nfl(monkeypatch):
    from oddsmarkets.nfl.models import live as L
    from oddsmarkets.nfl.sources import espn as nfl_espn
    seen = {}

    def live_wp(rec, pregame=None, season=None, home=None):
        seen.update(rec=rec, mu=(pregame or {}).get("margin"), season=season, home=home)
        return {"wp_home": 0.43219, "source": "wp_model"}
    monkeypatch.setattr(L, "live_wp", live_wp)
    monkeypatch.setattr(nfl_espn, "compact_summary", lambda raw, game_id=None, season=None: {"game_id": game_id, "season": season, "status": "live"})
    return seen


OWN = lambda: {"fit": "fitkey", "params": "parkey"}  # noqa: E731
NFL_LIVE = {"s": "live", "hs": 7, "as": 10, "p": 2, "c": "8:41"}


def test_gridiron_chance_uses_the_published_margin_and_the_same_fit(fake_nfl):
    feed, state = nfl_feed_and_state(NFL_LIVE)
    asked = []
    n, used = lc.gridiron(feed, state, NOW, lambda u, p=None: nfl_index(), summary=lambda eid: asked.append(eid) or {"header": 1}, own=OWN)
    assert (n, used, asked) == (1, 1, ["401772999"])
    assert feed["sports"]["nfl"]["g"][GID]["wp"] == 0.4322
    assert (fake_nfl["mu"], fake_nfl["season"], fake_nfl["home"]) == (-0.412, 2026, "NYG")
    assert fake_nfl["rec"]["game_id"] == GID
    # a card published with no margin: the build used 0, so does the feed
    feed, state = nfl_feed_and_state(NFL_LIVE)
    lc.gridiron(feed, state, NOW, lambda u, p=None: nfl_index(mu=None), summary=lambda eid: {"header": 1}, own=OWN)
    assert fake_nfl["mu"] == 0.0


@pytest.mark.parametrize("index", [nfl_index(fit="another"), nfl_index(params="another"), nfl_index(gid="2026_10_DAL_PHI"), None])
def test_gridiron_no_chance_from_a_model_the_build_did_not_use(fake_nfl, index):
    feed, state = nfl_feed_and_state(NFL_LIVE)
    asked = []
    n, used = lc.gridiron(feed, state, NOW, lambda u, p=None: index, summary=lambda eid: asked.append(eid) or {"header": 1}, own=OWN)
    assert (n, used, asked) == (0, 0, []) and "wp" not in feed["sports"]["nfl"]["g"][GID]


def test_gridiron_a_finished_summary_gives_no_chance_and_the_budget_is_shared(fake_nfl, monkeypatch):
    from oddsmarkets.nfl.models import live as L
    monkeypatch.setattr(L, "live_wp", lambda rec, pregame=None, season=None, home=None: {"wp_home": 1.0, "source": "final"})
    feed, state = nfl_feed_and_state(NFL_LIVE)
    assert lc.gridiron(feed, state, NOW, lambda u, p=None: nfl_index(), summary=lambda eid: {"header": 1}, own=OWN) == (0, 1)
    # the tick's summaries are one budget across the sites: none left, none asked
    feed, state = nfl_feed_and_state(NFL_LIVE)
    asked = []
    assert lc.gridiron(feed, state, NOW, lambda u, p=None: nfl_index(), summary=lambda eid: asked.append(eid), calls=lc.MAX_CALLS, own=OWN) == (0, lc.MAX_CALLS)
    assert asked == []


def test_the_gridiron_build_publishes_what_the_live_loop_reads():
    s = (ROOT / "oddsmarkets" / "nfl" / "analytics" / "season.py").read_text(encoding="utf-8")
    assert 'c["wp_mu"] = an.rnd((pr or {}).get("margin"), 3)' in s and 'adapters.live_wp(ctx, g, rec, {"margin": c.get("wp_mu")})' in s
    b = (ROOT / "scripts" / "build_gridiron.py").read_text(encoding="utf-8")
    assert "gp = GMm.params_key()" in b
    from oddsmarkets.nfl.models import game as GMm
    assert len(GMm.params_key()) == 12 and GMm.params_key() == GMm.params_key()


def test_the_feed_keeps_espn_event_id_for_nfl_in_the_state_only():
    spec2 = importlib.util.spec_from_file_location("live_feed", ROOT / "scripts" / "live_feed.py")
    lf = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(lf)
    board = {"events": [{"id": "401772999", "date": "2026-11-13T01:15Z", "season": {"year": 2026, "type": 2}, "week": {"number": 10},
                         "competitions": [{"status": {"period": 2, "displayClock": "8:41", "type": {"state": "in", "name": "STATUS_IN_PROGRESS", "shortDetail": "8:41 - 2nd"}},
                                           "competitors": [{"homeAway": "home", "score": "7", "team": {"abbreviation": "NYG"}},
                                                           {"homeAway": "away", "score": "10", "team": {"abbreviation": "WSH"}}]}]}]}
    got = lf.parse_espn_nfl(board)
    assert list(got) == [GID] and got[GID]["eid"] == "401772999"
    state = {}
    doc = lf.tick(state, NOW, lambda key: got if key == "nfl" else {})
    assert state["boards"]["nfl"]["g"][GID]["eid"] == "401772999"
    assert "eid" not in doc["sports"]["nfl"]["g"][GID] and doc["sports"]["nfl"]["g"][GID]["hs"] == 7
