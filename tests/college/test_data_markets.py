"""sources/markets.py on canned Kalshi / Polymarket answers (shapes fetched 19 Oct 2026), and the CFBD stub."""
import json
from pathlib import Path

import pytest

from oddsmarkets.college.sources import cfbd
from oddsmarkets.college.sources import markets as M

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_kalshi_cache(monkeypatch):
    monkeypatch.setattr(M, "KALSHI_GAP_S", 0.0)
    M._KCACHE.clear()
    yield
    M._KCACHE.clear()


def fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


TEAMS = {
    "61": {"name": "Georgia Bulldogs", "short": "Georgia", "location": "Georgia", "nickname": "Bulldogs", "abbr": "UGA", "conference": "8", "member": True},
    "251": {"name": "Texas Longhorns", "short": "Texas", "location": "Texas", "nickname": "Longhorns", "abbr": "TEX", "conference": "8", "member": True},
    "333": {"name": "Alabama Crimson Tide", "short": "Alabama", "location": "Alabama", "nickname": "Crimson Tide", "abbr": "ALA", "conference": "8", "member": True},
    "145": {"name": "Ole Miss Rebels", "short": "Ole Miss", "location": "Ole Miss", "nickname": "Rebels", "abbr": "MISS", "conference": "8", "member": True},
    "344": {"name": "Mississippi State Bulldogs", "short": "Mississippi St", "location": "Mississippi State", "nickname": "Bulldogs", "abbr": "MSST", "conference": "8", "member": True},
    "2439": {"name": "UNLV Rebels", "short": "UNLV", "location": "UNLV", "nickname": "Rebels", "abbr": "UNLV", "conference": "17", "member": True},
    "2390": {"name": "Miami Hurricanes", "short": "Miami", "location": "Miami", "nickname": "Hurricanes", "abbr": "MIA", "conference": "1", "member": True},
    "193": {"name": "Miami (OH) RedHawks", "short": "Miami OH", "location": "Miami (OH)", "nickname": "RedHawks", "abbr": "M-OH", "conference": "15", "member": True},
    "194": {"name": "Ohio State Buckeyes", "short": "Ohio State", "location": "Ohio State", "nickname": "Buckeyes", "abbr": "OSU", "conference": "5", "member": True},
    "248": {"name": "Houston Cougars", "short": "Houston", "location": "Houston", "nickname": "Cougars", "abbr": "HOU", "conference": "4", "member": True},
    "254": {"name": "Utah Utes", "short": "Utah", "location": "Utah", "nickname": "Utes", "abbr": "UTAH", "conference": "4", "member": True},
}


def test_map_team_labels():
    assert M.map_team("Ohio St.", TEAMS, "OSU") == "194"
    assert M.map_team("Mississippi St.", TEAMS, "MSST") == "344"
    assert M.map_team("Ole Miss", TEAMS, "MISS") == "145"
    assert M.map_team("Mississippi Rebels", TEAMS) == "145"
    assert M.map_team("Miami (FL)", TEAMS) == "2390"
    assert M.map_team("Miami (OH)", TEAMS) == "193"
    assert M.map_team("Georgia Bulldogs", TEAMS) == "61"
    assert M.map_team(None, TEAMS) is None


def test_map_player_duplicate_names():
    players = {"1": {"name": "Jeremiah Smith", "pos": "WR"}, "2": {"name": "Jeremiah Smith", "pos": "LB"}, "3": {"name": "Julian Sayin", "pos": "QB"}}
    assert M.map_player("Jeremiah Smith", players) == "1"
    assert M.map_player("Julian Sayin", players) == "3"


def test_futures_conference_title_from_canned_sources(monkeypatch):
    k_sec, p_sec = fx("k_sec.json"), fx("p_sec.json")
    monkeypatch.setattr(M, "kalshi_events", lambda series, status=None, **kw: [k_sec] if series == "KXNCAAFSEC" else [])
    monkeypatch.setattr(M, "_poly_events", lambda level: [p_sec])
    store = {"teams": TEAMS, "players": {}, "conferences": {"8": {"name": "Southeastern Conference", "short": "SEC", "abbr": "sec"}}}
    f = M.futures("cfb", 2026, store=store)
    sec = f["conference"]["8"]
    assert sec["sources"] == ["kalshi", "polymarket"]
    # only five of the sixteen SEC runners are in this small team table, so the field is thin (implied total < 0.8)
    assert sec["available"] is False and sec["reason"].startswith("thin")
    k, p = sec["by_source"]["kalshi"], sec["by_source"]["polymarket"]
    assert max(k, key=k.get) == "61" and max(p, key=p.get) == "61"     # Georgia the favourite in both canned books
    assert {"251", "333"} <= set(k) and {"251", "333"} <= set(p)
    assert f["champion"]["available"] is False and f["heisman"]["available"] is False
    assert f["win_totals"] == {}


def test_game_prices_canned(monkeypatch):
    k_game, p_game = fx("k_game.json"), fx("p_game.json")
    monkeypatch.setattr(M, "kalshi_events", lambda series, status=None, **kw: [k_game] if series == "KXNCAAFGAME" else [])
    store = {"teams": TEAMS, "games": {"401856837": {"id": "401856837", "date": "2026-10-24T20:00:00Z", "home": "254", "away": "248",
                                                    "odds": {"spread_home": -6.5, "total": 56.5, "provider": "DraftKings"}}}}
    gp = M.game_prices("cfb", "2026-10-24", store=store, poly_events=[p_game])
    r = gp["401856837"]
    srcs = {x["source"] for x in r["sources"]}
    assert {"kalshi", "polymarket", "espn_spread"} <= srcs
    assert r["basis"] == "prediction_markets" and 0.6 < r["p_home"] < 0.75


def test_spread_to_p():
    assert abs(M.spread_to_p(0.0, "mbb") - 0.5) < 1e-9
    assert M.spread_to_p(-7.0, "cfb") > 0.6 and M.spread_to_p(7.0, "cfb") < 0.4 and M.spread_to_p(None, "cfb") is None


def test_cfbd_without_key_is_off(monkeypatch):
    monkeypatch.delenv("CFBD_API_KEY", raising=False)
    assert cfbd.enabled() is False
    assert cfbd.lines(2024) is None and cfbd.get("/venues") is None
