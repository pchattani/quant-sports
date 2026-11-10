"""oddsmarkets/golf/follow_build.py: The Quant Green's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.golf import follow_build as B

NOW = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def ev(i, pos, st="finish", tie=False, tour="pga"):
    return {"id": f"e{i}", "tour": tour, "date": f"2026-0{i}-10", "name": f"Open {i}", "pos": pos, "tie": tie, "st": st}


def tree(tmp: Path) -> Path:
    data = tmp / "data"
    men = [{"rank": 1, "pid": "1", "name": "Ann Alpha", "rt": 2.5, "wins": 3, "top10": 9, "starts": 15, "d90": 0.4, "tour": "pga"},
           {"rank": 2, "pid": "2", "name": "Bob Beta Jr.", "rt": 1.2, "wins": 1, "top10": 4, "starts": 18, "d90": 0.02, "d365": -0.5, "tour": "liv"}]
    women = [{"rank": 1, "pid": "9", "name": "Cleo Gamma", "rt": 2.0, "wins": 2, "top10": 8, "starts": 14, "tour": "lpga"}]
    write(data / "rankings.json", {"men": men, "women": women})
    write(data / "index.json", {"week": [
        {"id": "w1", "name": "Live Classic", "course": "Pine Hill", "start": "2026-11-05", "end": "2026-11-08", "status": "live", "key": "lwin"},
        {"id": "w2", "name": "Ladies Open", "course": "Sea Links", "start": "2026-11-06", "end": "2026-11-09", "status": "upcoming", "key": "win"}]})
    write(data / "events" / "w1.json", {"players": [
        {"pid": "1", "st": "live", "pos": 3, "tie": True, "tp": -6, "win": 0.2, "lwin": 0.15, "t10": 0.6, "lt10": 0.7, "cut": 0.9},
        {"pid": "7", "st": "live", "pos": 1, "tie": False, "tp": -9, "win": 0.01, "lwin": 0.4, "lt10": 0.95},
        {"pid": "2", "st": "cut", "win": 0.05, "lwin": 0.0}]})
    write(data / "events" / "w2.json", {"players": [{"pid": "9", "st": "upcoming", "win": 0.22, "t10": 0.7, "cut": 0.95}]})
    write(data / "players" / "1.json", {"pid": "1", "name": "Ann Alpha", "cc": "USA", "stream": "men", "rank": 1, "rt": 2.5, "ranked": True,
                                        "summary": men[0], "events": [ev(8, 1), ev(7, 4, tie=True), ev(6, None, st="cut"), ev(5, 30), ev(4, 2), ev(3, 1)],
                                        "cur": {"q": True, "v": {k: 0.1 * i for i, k in enumerate(B.PROFILE)}, "pc": {k: 5 * i for i, k in enumerate(B.PROFILE)}}})
    write(data / "players" / "2.json", {"pid": "2", "name": "Bob Beta Jr.", "cc": "ENG", "stream": "men", "rank": 2, "rt": 1.2, "ranked": True,
                                        "summary": men[1], "events": [ev(8, None, st="wd", tour="liv"), ev(7, 12, tour="liv")]})
    write(data / "players" / "5.json", {"pid": "5", "name": "Dan Delta", "stream": "men", "rank": None, "rt": -0.4, "ranked": False, "events": []})
    write(data / "players" / "9.json", {"pid": "9", "name": "Cleo Gamma", "cc": "KOR", "stream": "women", "rank": 1, "rt": 2.0, "ranked": True,
                                        "summary": women[0], "events": [ev(8, 2, tour="lpga")]})
    return data


def cards(data: Path, scope: str) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (data / "follow" / scope).glob("*.json")}


def test_a_card_for_every_player_page_in_its_stream(tmp_path):
    data = tree(tmp_path)
    s = B.build(data, NOW)
    m, w = cards(data, "golfm"), cards(data, "golfw")
    assert set(m) == {"1", "2", "5"} and set(w) == {"9"} and s["golfm"]["n"] == 3 and s["golfw"]["n"] == 1
    for c in list(m.values()) + list(w.values()):
        assert c["k"].startswith("green:golf") and c["sport"] == "golf" and c["team"]["href"] == "#/player/" + c["k"].split(":")[2]
        assert FL.card_bytes(c) <= FL.MAX_BYTES and len({f["kind"] for f in c["facts"]}) == len(c["facts"]) <= FL.MAX_FACTS


def test_the_ranked_card_in_a_live_week(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    c = cards(data, "golfm")["1"]
    assert c["team"]["league"] == "Men’s golf" and c["team"]["group"] == "PGA Tour" and c["team"]["abbr"] == "USA"
    assert c["now"]["rating"]["rank"] == 1 and c["now"]["rating"]["of"] == 2 and c["now"]["standing"]["pos"] == 1
    # the last five finished events, oldest first: W a top 10, D another made cut, L a missed cut
    assert c["now"]["form"] == "WDLWW"
    # live: the chances from the scores so far (no cut chance once under way), the win last (the headline)
    assert [x["key"] for x in c["chances"]] == ["p_t10", "p_win"] and c["chances"][-1]["p"] == 0.15
    assert c["next_note"].startswith("Playing the Live Classic at Pine Hill now: T3 at −6.")
    kinds = [f["kind"] for f in c["facts"]]
    assert kinds[0] == "call" and "the 2nd best chance" in c["facts"][0]["text"]
    assert {"rating", "rating_move", "form_xp", "year"} <= set(kinds)
    assert "the most wins of anyone" in [f for f in c["facts"] if f["kind"] == "year"][0]["text"]
    assert c["last"]["comp"] == "Open 8 · 1" and c["last"]["res"] == "W"
    assert len(c["profile"]["strong"]) == 3 and len(c["profile"]["weak"]) == 2
    assert c["profile"]["strong"][0]["pct"] >= c["profile"]["weak"][0]["pct"]


def test_missed_cut_unranked_and_women(tmp_path):
    data = tree(tmp_path)
    B.build(data, NOW)
    b = cards(data, "golfm")["2"]
    # missed this week's cut: no chances, not "in the field"; a withdrawal is an L; the year-ago move (90 days too small)
    assert not b.get("chances") and b["next_note"].startswith("Not in the field")
    assert b["now"]["form"] == "DL" and b["team"]["short"] == "Beta Jr." and b["team"]["group"] == "LIV Golf"
    assert [f["text"] for f in b["facts"] if f["kind"] == "rating_move"] == ["Our rating is down 0.50 strokes a round on a year ago."]
    d = cards(data, "golfm")["5"]
    assert "rank" not in d["now"]["rating"] and d["now"]["standing"]["text"].startswith("Not in our ranking")
    g = cards(data, "golfw")["9"]
    assert g["team"]["league"] == "Women’s golf" and [x["key"] for x in g["chances"]] == ["p_cut", "p_t10", "p_win"]
    assert g["next_note"].startswith("Next: the Ladies Open at Sea Links, 6 Nov–9 Nov.") and "LPGA Tour player" in " ".join(f["text"] for f in g["facts"])


def test_prune_and_no_betting_words(tmp_path):
    import re
    data = tree(tmp_path)
    (data / "follow" / "golfm").mkdir(parents=True)
    (data / "follow" / "golfm" / "old.json").write_text("{}", encoding="utf-8")
    B.build(data, NOW)
    assert not (data / "follow" / "golfm" / "old.json").exists()
    text = json.dumps([cards(data, "golfm"), cards(data, "golfw")], ensure_ascii=False)
    assert not re.search(r"\b(priced?|pricing|edge|odds|bet)\b", text, re.I)
