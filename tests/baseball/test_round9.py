"""Round 9 (28 Oct 2026) Bullpen fixes: game-page signatures and the postseason as played for finished seasons."""
from __future__ import annotations

from types import SimpleNamespace

from oddsmarkets.baseball.analytics import games as GM
from oddsmarkets.baseball.analytics import season as SN


def test_page_sig_rewrites_a_placeholder_when_its_teams_or_date_change():
    g = {"status": "pre", "hs": None, "as": None, "home": "31", "away": "21", "date": "2026-10-27", "start": "2026-10-28T00:00:00Z"}
    s0 = GM.page_sig(g, 0, ("v",))
    assert GM.page_sig({**g, "home": "158"}, 0, ("v",)) != s0
    assert GM.page_sig({**g, "away": "139"}, 0, ("v",)) != s0
    assert GM.page_sig({**g, "date": "2026-10-28"}, 0, ("v",)) != s0
    assert GM.page_sig({**g, "probables": {"home": "1", "away": None}}, 0, ("v",)) != s0
    # a final page's signature ignores them (no rebuild of every finished game when the fields were added)
    f = {**g, "status": "final", "hs": 3, "as": 2}
    assert GM.page_sig(f, 300, ("v",)) == GM.page_sig({**f, "start": "x", "venue": "9"}, 300, ("v",))


def _ctx(level, teams, games):
    store = {"teams": teams, "games": {g["gpk"]: g for g in games}}
    return SimpleNamespace(level=level, season=2025, store=store, games=store["games"])


def test_actual_postseason_triple_a_league_finals_and_championship():
    teams = {"1": {"name": "Jacksonville", "league": "IL"}, "2": {"name": "Scranton", "league": "IL"},
             "3": {"name": "Las Vegas", "league": "PCL"}, "4": {"name": "Tacoma", "league": "PCL"}}

    def g(gpk, d, gt, h, a, hs, as_, desc, of):
        return {"gpk": gpk, "date": d, "gtype": gt, "home": h, "away": a, "hs": hs, "as": as_, "status": "final",
                "series": {"desc": desc, "of": of}}
    games = [g("a", "2025-09-23", "W", "1", "2", 4, 5, "International League Championship", 3),
             g("b", "2025-09-24", "W", "1", "2", 6, 4, "International League Championship", 3),
             g("c", "2025-09-25", "W", "1", "2", 7, 4, "International League Championship", 3),
             g("d", "2025-09-23", "W", "3", "4", 7, 1, "Pacific Coast League Championship", 3),
             g("e", "2025-09-24", "W", "3", "4", 7, 3, "Pacific Coast League Championship", 3),
             g("f", "2025-09-27", "C", "1", "3", 8, 7, "Triple-A National Championship Game", 1),
             {"gpk": "x", "date": "2025-09-25", "gtype": "W", "home": "3", "away": "4", "status": "cancelled", "hs": None, "as": None}]
    out = SN.actual_postseason(_ctx("aaa", teams, games))
    assert out["actual"] and out["complete"] and out["champion"] == "1"
    rounds = [(s["round"], s["teams"], s["wins"], s["winner"], s["best_of"]) for s in out["series"]]
    assert rounds[0] == ("LC", ["1", "2"], [2, 1], "1", 3)
    assert rounds[1] == ("LC", ["3", "4"], [2, 0], "3", 3)
    assert rounds[2] == ("CH", ["1", "3"], [1, 0], "1", 1)
    assert out["series"][1]["games"] == ["d", "e"]                       # the cancelled "if necessary" game is left out
    assert out["teams"]["1"]["champion"] and out["teams"]["1"]["p_pennant"] == 1.0
    assert out["teams"]["2"]["reached"] == "LC" and out["teams"]["2"]["p_pennant"] == 0.0


def test_actual_postseason_none_without_postseason_games():
    assert SN.actual_postseason(_ctx("mlb", {}, [{"gpk": "1", "gtype": "R", "home": "a", "away": "b", "status": "final", "hs": 1, "as": 0}])) is None
