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


def test_team_history_from_the_committed_lahman_copy(monkeypatch):
    from oddsmarkets.baseball.analytics import team_history as TH
    from oddsmarkets.baseball.sources import lahman
    monkeypatch.setattr(lahman, "load", lambda name: None)      # no cache on this machine: the committed copy is used
    d = TH.build([])
    assert d["ok"] and d["first"] == 1901 and d["lahman_last"] >= 2025
    ch = {c["season"]: c for c in d["champions"]}
    assert 1904 not in ch and 1994 not in ch                     # no World Series
    assert ch[1903]["fid"] == "BOS" and ch[2016]["fid"] == "CHC" and ch[2025]["fid"] == "LAD"
    assert ch[2025]["opp"]["fid"] == "TOR"
    assert d["franchises"]["NYY"]["titles"] == 27
    assert len(d["droughts"]) == 30 and d["droughts"][0]["years"] >= d["droughts"][-1]["years"]
    best = d["best"][0]
    assert best["season"] == 1906 and best["fid"] == "CHC"
    rec = {r["key"]: r for r in d["records"]}
    assert rec["most_w"]["value"] == 116 and any(a["fid"] == "SEA" and a["season"] == 2001 for a in rec["most_w"].get("also", []))


def test_award_history_from_the_committed_calls():
    from oddsmarkets.baseball.analytics import award_history as AH
    d = AH.build(2026, {"awards": {"al_mvp": {"rows": [{"pid": "1", "name": "A", "p": 0.7}, {"pid": "2", "name": "B", "p": 0.3}]}}}, True)
    assert d["ok"] and "2025" in d["seasons"] and "2015" in d["seasons"]
    w = d["seasons"]["2025"]["al_mvp"]["winner"]
    assert w["name"] == "Aaron Judge" and w["rank"] == 1
    assert d["seasons"]["2026"]["al_mvp"]["winner"] is None and d["seasons"]["2026"]["al_mvp"]["pick"]["pid"] == "1"
    s = d["summary"]
    assert s["n"] >= 55 and 0 < s["top_pick_won"] <= s["winner_in_top3"] <= s["n"]
    # a season still under way adds no call
    assert "2026" not in AH.build(2026, {"awards": {"al_mvp": {"rows": [{"pid": "1", "p": 1.0}]}}}, False)["seasons"]


def test_recap_calls_only_for_the_twelve_club_format():
    ctx = SimpleNamespace(level="mlb", season=2019, games={}, store={})
    assert SN.recap_calls(ctx) is None
    assert SN.recap_calls(SimpleNamespace(level="aaa", season=2025, games={}, store={})) is None


def test_on_il_drops_placements_with_no_end_after_a_season_and_a_winter():
    from datetime import date
    from oddsmarkets.baseball.analytics import moves as M
    st = {"1": [{"start": "2015-08-08", "end": None, "il": 15, "part": "arm", "club": "146"}],
          "2": [{"start": "2026-08-01", "end": None, "il": 60, "part": "knee", "club": "119"}],
          "3": [{"start": "2026-04-01", "end": "2026-05-01", "il": 10, "part": "back", "club": "147"}]}
    on = M.on_il(st, date(2026, 10, 28))
    assert set(on) == {"2"}


def test_form_ranks_each_player_against_their_own_season():
    from oddsmarkets.baseball.analytics import form as FM
    hit = {"players": {str(i): {"name": f"H{i}", "team": "147", "pos": "SS", "pa": 400, "values": {"xwoba_plus": 0.330}} for i in range(20)}}
    blocks = {str(i): {"rolling": [["2026-09-01", 0.300], ["2026-09-20", 0.330 + (i - 10) / 100]]} for i in range(20)}
    blocks["99"] = {"rolling": [["2026-09-20", 0.9]]}                     # not in the catalogue: left out
    out = FM.build("mlb", 2026, blocks, hit, {"players": {}})
    assert out["hitters"]["hot"][0]["pid"] == "19" and out["hitters"]["cold"][0]["pid"] == "0"
    assert out["hitters"]["hot"][0]["delta"] == 0.09 and out["asof"] == "2026-09-20"
    assert len(out["hitters"]["hot"]) == FM.TOP


def test_record_chases_pace_and_rank():
    from oddsmarkets.baseball.analytics import records as RD
    hit = {"team_games": 81, "players": {"1": {"name": "A", "team": "147", "values": {"hr": 33}}, "2": {"name": "B", "team": "119", "values": {"hr": 20}}}}
    out = RD.build(2026, hit, {"team_games": 81, "players": {}}, "regular")
    hr = out["stats"]["hr"]
    assert not out["final"] and hr["record"][2] == 73
    a = hr["leaders"][0]
    assert a["pid"] == "1" and a["pace"] == 66.0 and a["rank"] is not None and a["behind"] == 7.0
    fin = RD.build(2026, dict(hit, team_games=162), {"team_games": 162, "players": {}}, "offseason")
    assert fin["final"] and fin["stats"]["hr"]["leaders"][0]["pace"] == 33.0 and fin["stats"]["hr"]["leaders"][0]["rank"] is None
