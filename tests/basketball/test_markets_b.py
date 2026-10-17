"""Builder B markets: Kalshi / Polymarket parsing on payloads recorded 2026-10-01 (no network)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from oddsmarkets.basketball.sources import markets as M

FIX = json.loads((Path(__file__).parent / "fixtures" / "markets_b.json").read_text(encoding="utf-8"))


def _store(league, games=None, players=None):
    return {"league": league, "teams": FIX["teams"][league], "players": players or {}, "games": games or {}}


@pytest.fixture
def canned(monkeypatch):
    def kalshi(series, *a, **k):
        if series == "KXNBAWEST":
            return []
        return FIX["kalshi"].get(series, [])

    def poly(tag, *a, **k):
        return FIX["polymarket"].get(tag, [])

    monkeypatch.setattr(M, "kalshi_events", kalshi)
    monkeypatch.setattr(M, "polymarket_tag_events", poly)


def _abbr(league, tid):
    return FIX["teams"][league][tid]["abbr"]


def test_map_team_codes_and_labels():
    nba = FIX["teams"]["nba"]
    by = {v["abbr"]: t for t, v in nba.items()}
    assert M.map_team("Golden State", nba, "GSW") == by["GS"]
    assert M.map_team("Los Angeles C", nba, "LAC") == by["LAC"]
    assert M.map_team("Utah", nba, "UTA") == by["UTAH"]
    assert M.map_team("New York", nba, "NYK") == by["NY"]
    assert M.map_team("Boston Celtics", nba) == by["BOS"]
    assert M.map_team("Heat", nba) == by["MIA"]
    assert M.map_team("Golden State", nba) == by["GS"]
    assert M.map_team("Los Angeles Lakers", nba) == by["LAL"]
    assert M.map_team("Not A Team", nba) is None
    w = FIX["teams"]["wnba"]
    wb = {v["abbr"]: t for t, v in w.items()}
    assert M.map_team("Connecticut", w, "CONN") == wb["CON"]
    assert M.map_team("Las Vegas Aces", w) == wb["LV"]
    assert M.map_team("Golden State Valkyries", w) == wb["GS"]


def test_map_player():
    players = {"1": {"name": "Shai Gilgeous-Alexander"}, "2": {"name": "Victor Wembanyama"}, "3": {"name": "Jayson Tatum"},
               "4": {"name": "Jalen Williams"}, "5": {"name": "Jaylin Williams"}}
    assert M.map_player("Shai Gilgeous-Alexander", players) == "1"
    assert M.map_player("Victor Wembanyama", players) == "2"
    assert M.map_player("Wembanyama", players) == "2"
    assert M.map_player("Williams", players) is None
    assert M.map_player("Nobody Atall", players) is None


def test_champion_nba(canned):
    t = M.title_prices("nba", 2027, "champion", store=_store("nba"))
    assert t["available"], t["reason"]
    assert t["field"] == 30 and not t["unmatched"]
    assert set(t["sources"]) == {"kalshi", "polymarket"}
    assert len(t["by_source"]["kalshi"]) >= 12 and len(t["by_source"]["polymarket"]) >= 20
    assert set(t["by_source"]["kalshi"]) | set(t["floor"]) | set(t["eliminated"]) <= set(FIX["teams"]["nba"])
    assert sum(t["probs"].values()) == pytest.approx(1.0, abs=1e-3)
    assert 0.8 <= t["implied_total"] <= 1.3
    top = next(iter(t["probs"]))
    assert t["probs"][top] > 0.08
    assert t["markets"]["kalshi"] == "KXNBA-27" and t["markets"]["polymarket"] == "nba-2027-champion"


def test_conference_east_only_east_field(canned):
    t = M.title_prices("nba", 2027, "east", store=_store("nba"))
    assert t["field"] == 15
    assert t["available"], t["reason"]
    assert all(FIX["teams"]["nba"][r]["conference"].startswith("East") for r in t["probs"])


def test_wnba_champion_eliminated(canned):
    t = M.title_prices("wnba", 2026, "champion", store=_store("wnba"))
    assert t["field"] == 15
    assert t["available"], t["reason"]
    elim = {_abbr("wnba", r) for r in t["eliminated"]}
    assert {"CHI", "CON", "LA"} <= elim
    assert all(t["probs"][r] == 0.0 for r in t["eliminated"])
    assert sum(t["probs"].values()) == pytest.approx(1.0, abs=1e-3)


def test_mvp_players(canned):
    players = {"10": {"name": "Shai Gilgeous-Alexander"}, "11": {"name": "Victor Wembanyama"}, "12": {"name": "Jayson Tatum"},
               "13": {"name": "Nikola Jokic"}, "14": {"name": "Luka Doncic"}, "15": {"name": "Giannis Antetokounmpo"},
               "16": {"name": "Cade Cunningham"}, "17": {"name": "Anthony Edwards"}}
    t = M.title_prices("nba", 2027, "mvp", store=_store("nba", players=players))
    assert "10" in t["by_source"]["kalshi"] and "11" in t["by_source"]["kalshi"]
    assert t["field"] == len(set(t["by_source"]["kalshi"]) | set(t["floor"]) | set(t["eliminated"]))


def test_thin_market_rule():
    src = {"kalshi": {"mid": {"a": 0.5, "b": 0.3}, "floor": set(), "eliminated": set(), "winner": None, "unmatched": []}}
    t = M.assemble(src, ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], "champion")
    assert not t["available"] and t["reason"].startswith("thin")
    src["kalshi"]["mid"].update({"c": 0.1, "d": 0.08})
    src["kalshi"]["floor"] = {"e", "f"}
    t = M.assemble(src, ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"], "champion")
    assert t["available"] and t["probs"]["e"] == 0.0
    assert t["probs"]["a"] == pytest.approx(0.5 / 0.98, abs=1e-4)
    src["kalshi"]["winner"] = "a"
    assert M.assemble(src, ["a", "b"], "champion")["reason"].startswith("settled")


def test_win_totals(canned):
    wt = M.win_totals("nba", 2027, store=_store("nba"))
    assert len(wt) == 3
    for tid, v in wt.items():
        lad = v["ladder"]
        ks = sorted(lad)
        assert all(lad[a] >= lad[b] for a, b in zip(ks, ks[1:]))
        assert v["line"] % 1 == 0.5 and 0 < v["p_over"] < 1
        assert v["ticker"].endswith(_abbr("nba", tid)) or v["ticker"].endswith("BKN")


def test_binary_playoffs(canned):
    b = M.binary_prices("nba", 2027, "playoffs", store=_store("nba"))
    assert b["available"] and len(b["probs"]) >= 5
    by = {v["abbr"]: t for t, v in FIX["teams"]["nba"].items()}
    assert b["probs"][by["BOS"]] == pytest.approx(0.85, abs=0.01)


def test_futures_bundle(canned):
    f = M.futures("nba", 2027, store=_store("nba"))
    assert f["champion"]["available"] and "East" in f["conference"] and "win_totals" in f
    assert f["conference"]["West"]["available"] is False
    json.dumps(f, default=list)


def test_kalshi_game_date():
    assert M.kalshi_game_date("KXNBAGAME-26OCT03MIATOR") == date(2026, 10, 3)
    assert M.kalshi_game_date("KXWNBAGAME-26OCT01INDLV") == date(2026, 10, 1)
    assert M.kalshi_game_date("junk") is None


def test_game_prices(canned):
    nba = {v["abbr"]: t for t, v in FIX["teams"]["nba"].items()}
    games = {"g1": {"id": "g1", "date": "2026-10-03T23:00Z", "status": "pre", "stype": "pre", "home": nba["TOR"],
                    "away": nba["MIA"], "odds": {"provider": "DraftKings", "spread_home": -2.5, "total": 220.5,
                                                 "ml_home": -140, "ml_away": 120}},
             "g2": {"id": "g2", "date": "2026-10-04T23:00Z", "status": "pre", "stype": "pre", "home": nba["LAC"],
                    "away": nba["GS"], "odds": None}}
    out = M.game_prices("nba", "2026-10-03", store=_store("nba", games=games))
    r = out["g1"]
    srcs = {x["source"]: x["p_home"] for x in r["sources"]}
    assert "polymarket" in srcs and srcs["polymarket"] == pytest.approx(1 - 0.475, abs=1e-4)   # Heat 0.475 -> Raptors
    assert "kalshi" not in srcs                         # Kalshi preseason quotes are wider than 12c: no price
    assert r["p_home"] == pytest.approx(srcs["polymarket"]) and r["basis"] == "prediction_markets"
    assert srcs["draftkings_ml"] == pytest.approx((140 / 240) / (140 / 240 + 100 / 220), abs=1e-3)
    assert srcs["draftkings_spread"] > 0.5
    w = {v["abbr"]: t for t, v in FIX["teams"]["wnba"].items()}
    wg = {"w1": {"id": "w1", "date": "2026-10-02T00:00Z", "status": "pre", "stype": "post", "home": w["LV"], "away": w["IND"],
                 "odds": None}}
    out = M.game_prices("wnba", "2026-10-01", store=_store("wnba", games=wg))
    srcs = {x["source"]: x["p_home"] for x in out["w1"]["sources"]}
    assert srcs["kalshi"] == pytest.approx(0.62 / (0.62 + 0.375), abs=1e-3)
    assert srcs["polymarket"] == pytest.approx(0.63, abs=1e-3)
    assert out["w1"]["p_home"] == pytest.approx((srcs["kalshi"] + srcs["polymarket"]) / 2, abs=1e-4)


def test_never_raises_without_network(monkeypatch):
    monkeypatch.setattr(M, "kalshi_events", lambda *a, **k: None)
    monkeypatch.setattr(M, "polymarket_tag_events", lambda *a, **k: None)
    t = M.title_prices("nba", 2027, "champion", store=_store("nba"))
    assert t["available"] is False
    assert M.game_prices("nba", "2026-10-03", store=_store("nba")) == {}
    assert M.win_totals("nba", 2027, store=_store("nba")) == {}
