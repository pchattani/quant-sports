"""store.py: paths, atomic gz round trips, merge rules; cc_fetch post-passes and a scoreboard pass on a fake client."""
import importlib.util
import json
from pathlib import Path

import pytest

from oddsmarkets.college import store as st

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def roots(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUS_STORES", str(tmp_path / "stores"))
    monkeypatch.setenv("CAMPUS_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("CAMPUS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CAMPUS_DATA", str(tmp_path / "data"))
    return tmp_path


def test_paths_follow_env(roots):
    p = st.paths()
    assert p["stores"] == roots / "stores" and p["raw"] == roots / "raw" and p["data"] == roots / "data"
    assert st.store_path("mbb", 2026) == roots / "stores" / "mbb" / "2026.json.gz"
    assert st.plays_path(2025) == roots / "raw" / "cfb" / "plays" / "2025.json.gz"
    assert st.pbp_path("wbb", 2024, "1") == roots / "raw" / "pbp" / "wbb" / "2024" / "1.json.gz"


def test_save_load_round_trip(roots):
    s = st.load("cfb", 2025)
    assert s["games"] == {} and s["meta"]["version"] == st.VERSION
    s["games"]["2"] = {"id": "2", "date": "2025-09-02T00:00:00Z", "status": "post", "odds": {"spread_home": -3.0, "source": "core"}}
    s["games"]["1"] = {"id": "1", "date": "2025-09-01T00:00:00Z", "status": "post", "odds": None}
    st.save(s)
    s2 = st.load("cfb", 2025)
    assert list(s2["games"]) == ["1", "2"]                      # date order
    assert s2["meta"]["odds_coverage"] == {"games": 2, "with_close": 1, "with_any": 1}
    assert st.seasons_on_disk("cfb") == [2025]
    assert not list((roots / "stores" / "cfb").glob("*.tmp"))


def test_merge_game_keeps_richer_fields(roots):
    s = st.new_store("mbb", 2026)
    st.merge_game(s, {"id": "9", "box": {"1": {}}, "odds": {"spread_home": -2.0, "source": "core"}, "predictor": {"home": 0.6},
                      "summary": True, "has_pbp": True, "ranks": {"home": 3, "away": None}, "stype": "ncaa"})
    st.merge_game(s, {"id": "9", "box": {}, "odds": {"spread_home": -1.0, "source": "scoreboard"}, "predictor": None,
                      "summary": False, "has_pbp": False, "ranks": {"home": None, "away": None}, "stype": "ncaa"})
    g = s["games"]["9"]
    assert g["box"] == {"1": {}} and g["odds"]["source"] == "core" and g["predictor"] == {"home": 0.6}
    assert g["summary"] is True and g["has_pbp"] is True and g["ranks"]["home"] == 3
    st.merge_game(s, {"id": "9", "odds": {"spread_home": -2.5, "source": "core"}})
    assert s["games"]["9"]["odds"]["spread_home"] == -2.5


def test_merge_team_and_player(roots):
    s = st.new_store("cfb", 2025)
    st.merge_team(s, "8", {"name": "A", "conference": "1", "member": True})
    st.merge_team(s, "8", {"name": "A2", "conference": "4", "abbr": None}, weak=("conference",))
    assert s["teams"]["8"]["conference"] == "1" and s["teams"]["8"]["name"] == "A2"
    st.merge_player(s, "p", {"name": "X", "pos": None, "class": "SO"}, "8")
    st.merge_player(s, "p", {"name": "X", "pos": "QB", "class": None, "teams": ["9"]})
    assert s["players"]["p"]["pos"] == "QB" and s["players"]["p"]["class"] == "SO" and s["players"]["p"]["teams"] == ["8", "9"]


def test_plays_and_pbp_round_trip(roots):
    pl = st.load_plays(2025)
    pl["games"]["1"] = {"drives": [[0, "1", 1, 900, 75, 3, 10, "Punt", 0]], "plays": []}
    st.save_plays(pl)
    assert st.load_plays(2025)["games"]["1"]["drives"][0][7] == "Punt"
    st.save_pbp("mbb", 2026, {"id": "5", "plays": [[1]], "types": {}, "wp": {}})
    assert st.load_pbp("mbb", 2026, "5")["plays"] == [[1]] and st.has_pbp_file("mbb", 2026, "5")


def _cc_fetch():
    spec = importlib.util.spec_from_file_location("cc_fetch", ROOT / "scripts" / "cc_fetch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeClient:
    used = failures = throttled = 0
    seconds = 0.0


def test_scoreboard_pass_with_fake_espn(roots, monkeypatch):
    cc = _cc_fetch()
    sb = json.loads((FIX / "mbb_scoreboard.json").read_text(encoding="utf-8"))
    stand = json.loads((FIX / "cfb_standings_2024.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(cc.espn, "calendar", lambda c, lv, y: ["20260320"])
    monkeypatch.setattr(cc.espn, "scoreboard_day", lambda c, lv, d: {"events": [e for e in sb["events"] if e["season"]["year"] == 2026]})
    monkeypatch.setattr(cc.espn, "conferences", lambda c, lv, y: ({"8": {"name": "Pac", "short": "Pac", "abbr": "p", "d1": True, "divisions": {}}},
                                                                 {"12": {"conference": "8", "division": None}}))
    f = cc.Fetcher("mbb", FakeClient(), workers=1)
    f.scoreboard(2026)
    f.close()
    s = st.load("mbb", 2026)
    assert set(s["games"]) == {e["id"] for e in sb["events"] if e["season"]["year"] == 2026}
    assert s["teams"]["12"]["member"] is True and s["teams"]["12"]["conference"] == "8"
    assert all(not t["member"] for k, t in s["teams"].items() if k != "12")
    assert s["meta"]["scanned"].get("20260320")
    assert all(g["round"] == "Round of 64" for g in s["games"].values())
    assert stand  # fixture loads


def test_post_pass_conf_games_and_cfp_seeds():
    cc = _cc_fetch()
    s = st.new_store("cfb", 2024)
    s["conferences"] = {"8": {"name": "SEC"}, "18": {"name": "FBS Independents"}}
    s["teams"] = {"a": {"member": True, "conference": "8"}, "b": {"member": True, "conference": "8"},
                  "c": {"member": True, "conference": "18"}, "d": {"member": True, "conference": "18"}}
    s["games"] = {"1": {"id": "1", "home": "a", "away": "b", "stype": "reg", "conf_game": False},
                  "2": {"id": "2", "home": "c", "away": "d", "stype": "reg", "conf_game": True},
                  "3": {"id": "3", "home": "a", "away": "c", "stype": "cfp", "conf_game": False, "seeds": None}}
    s["rankings"] = {"cfp_seeds": {"16": [[1, "a", 0, 0], [4, "c", 0, 0]]}}
    cc.post_pass(s)
    assert s["games"]["1"]["conf_game"] is True and s["games"]["2"]["conf_game"] is False
    assert s["games"]["3"]["seeds"] == {"home": 1, "away": 4}


def test_merge_player_drops_implausible_body_typos():
    """ESPN rosters carry typos such as a 5 lb lineman; they never overwrite a good value and are cleared if stored."""
    s = st.new_store("cfb", 2026)
    st.merge_player(s, "p", {"name": "X", "height_in": 75, "weight_lb": 240})
    st.merge_player(s, "p", {"weight_lb": 5, "height_in": 7})
    assert s["players"]["p"]["weight_lb"] == 240 and s["players"]["p"]["height_in"] == 75
    s["players"]["q"] = {"name": "Y", "height_in": 93, "weight_lb": 2, "teams": []}     # stored before the bounds
    st.merge_player(s, "q", {"class": "SR"})
    assert s["players"]["q"]["weight_lb"] is None and s["players"]["q"]["height_in"] == 93   # a 7'9" centre is real
