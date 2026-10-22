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


# ── the thin rule: one venue's book at a time ─────────────────────────────────
def _src(mid, floor=(), elim=(), winner=None):
    return {"mid": dict(mid), "floor": set(floor), "eliminated": set(elim), "winner": winner, "unmatched": []}


def _overround_book():
    # ten runners quoted, implied total 1.25 (overround inside the band)
    return {"a": 0.30, "b": 0.20, "c": 0.17, "d": 0.14, "e": 0.11, "f": 0.09, "g": 0.08, "h": 0.07, "i": 0.05, "j": 0.04}


def test_overround_book_is_normalised_and_used():
    book = _overround_book()
    assert abs(sum(book.values()) - 1.25) < 1e-9
    t = M.assemble({"polymarket": _src(book)}, None, "champion")
    assert t["available"] is True and t["used"] == ["polymarket"] and t["reason"] is None
    assert t["books"]["polymarket"]["usable"] is True and t["books"]["polymarket"]["implied_total"] == 1.25
    assert abs(sum(t["probs"].values()) - 1.0) < 1e-4
    assert list(t["probs"])[:3] == ["a", "b", "c"]                  # order kept
    # power de-vig takes more of the margin from the longshots than from the favourite
    assert t["probs"]["a"] / t["probs"]["j"] > 0.30 / 0.04
    assert t["probs"]["a"] > 0.30 / 1.25


def test_noisy_overround_book_is_left_out_and_the_other_venue_prices():
    # the men's champion books of 21 Oct 2026 in miniature: Kalshi complete at 1.02, Polymarket at 1.48 with a fat tail
    ids = [f"t{i}" for i in range(12)]
    k = {f"t{i}": p for i, p in enumerate([0.30, 0.22, 0.15, 0.10, 0.08, 0.06, 0.04, 0.03, 0.02, 0.01, 0.005, 0.005])}
    pm = {f"t{i}": p for i, p in enumerate([0.31, 0.20, 0.15, 0.11, 0.09, 0.08, 0.10, 0.11, 0.10, 0.11, 0.06, 0.06])}
    assert abs(sum(pm.values()) - 1.48) < 1e-9
    t = M.assemble({"kalshi": _src(k), "polymarket": _src(pm)}, ids, "champion")
    assert t["available"] is True and t["used"] == ["kalshi"] and "polymarket" in t["note"] and "above" in t["note"]
    assert t["probs"] == M.assemble({"kalshi": _src(k)}, ids, "champion")["probs"]


def test_sparse_book_is_thin():
    # 3 of 20 runners quoted, implied total 0.30: runners missing, never normalised up to 1
    ids = [f"t{i}" for i in range(20)]
    t = M.assemble({"kalshi": _src({"t0": 0.15, "t1": 0.10, "t2": 0.05})}, ids, "conference:x")
    assert t["available"] is False and t["probs"] == {} and t["used"] == []
    assert t["reason"].startswith("thin") and "kalshi" in t["reason"] and "0.30" in t["reason"]
    assert t["books"]["kalshi"]["usable"] is False and t["books"]["kalshi"]["quoted"] == 3


def test_book_below_the_band_is_thin_even_when_well_covered():
    ids = [f"t{i}" for i in range(10)]
    t = M.assemble({"kalshi": _src({f"t{i}": 0.06 for i in range(10)})}, ids, "conference:x")     # 10 of 10, total 0.60
    assert t["available"] is False and "runners missing" in t["reason"]


def test_book_above_the_band_is_not_a_price():
    t = M.assemble({"polymarket": _src({f"t{i}": 0.2 for i in range(7)})}, None, "champion")       # total 1.40
    assert t["available"] is False and "above" in t["reason"]


def test_complete_short_list_is_usable():
    # Kalshi lists only the live runners of a conference (6 of 17 ACC teams, summing to 0.98 on 21 Oct 2026)
    ids = [f"t{i}" for i in range(17)]
    t = M.assemble({"kalshi": _src({"t0": 0.40, "t1": 0.25, "t2": 0.15, "t3": 0.10, "t4": 0.05, "t5": 0.03})}, ids, "conference:acc")
    assert t["available"] is True and t["used"] == ["kalshi"]
    assert abs(sum(t["probs"].values()) - 1.0) < 1e-4
    # ... but four or fewer runners at a lower total is not
    t = M.assemble({"kalshi": _src({"t0": 0.40, "t1": 0.25, "t2": 0.20})}, ids, "conference:acc")
    assert t["available"] is False


def test_pooling_with_one_thin_venue_uses_the_other():
    ids = [f"t{i}" for i in range(12)]
    good = {f"t{i}": p for i, p in enumerate([0.30, 0.20, 0.15, 0.10, 0.08, 0.06, 0.04, 0.03, 0.02, 0.01])}   # 10 of 12, 0.99
    sparse = {"t0": 0.05, "t5": 0.20, "t7": 0.05}                                                          # 3 of 12, 0.30
    alone = M.assemble({"kalshi": _src(good, floor=["t10", "t11"])}, ids, "champion")
    t = M.assemble({"kalshi": _src(good, floor=["t10", "t11"]), "polymarket": _src(sparse)}, ids, "champion")
    assert t["available"] is True and t["used"] == ["kalshi"] and t["sources"] == ["kalshi", "polymarket"]
    assert t["books"]["polymarket"]["usable"] is False and "polymarket" in t["note"]
    assert t["probs"] == alone["probs"]                       # the thin book's prices never enter the pool
    assert t["by_source"]["polymarket"]["t5"] == 0.2          # ... but stay on show
    assert t["probs"]["t10"] == 0.0 and t["probs"]["t11"] == 0.0
    assert abs(sum(t["probs"].values()) - 1.0) < 1e-4


def test_pooling_two_usable_books_with_different_runners():
    # Kalshi quotes x..v; Polymarket has no live quote on x (a spread too wide) but splits y..v the way Kalshi does
    k = {"x": 0.50, "y": 0.20, "z": 0.12, "u": 0.10, "v": 0.08}
    p = {"y": 0.40, "z": 0.24, "u": 0.20, "v": 0.16}
    ids = ["x", "y", "z", "u", "v", "w"]
    t = M.assemble({"kalshi": _src(k, floor=["w"]), "polymarket": _src(p)}, ids, "champion")
    assert t["used"] == ["kalshi", "polymarket"]
    # Polymarket only says how y..v split what x leaves, so x keeps Kalshi's half (a plain mean would give x 0.33)
    for r, v in k.items():
        assert abs(t["probs"][r] - v) < 1e-3, r
    assert t["probs"]["w"] == 0.0


def test_settled_market_is_not_priced():
    t = M.assemble({"kalshi": _src({"a": 0.5}, elim=["b"], winner="a")}, ["a", "b"], "champion")
    assert t["available"] is False and t["reason"].startswith("settled")
