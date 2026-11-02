"""oddsmarkets/college/follow_build.py: the Campus's follow cards from a synthetic payload tree (every level shape: a
football list schedule, a hockey format-2 columnar schedule with ties, a basketball preseason)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.college import follow_build as B
from oddsmarkets.common import follow as FL

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
N = 12          # teams per level


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%MZ")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tid(i: int) -> str:
    return str(100 + i)


def level_tree(data: Path, L: str, S: int, phase: str) -> None:
    hk = L in B.HOCKEY
    teams = {tid(i): {"name": f"Team {i} Tigers", "short": f"Team {i}", "abbr": f"T{i}", "colour": "#123456", "conference": "c1" if i < 6 else "c2", "member": True}
             for i in range(N)}
    played = 0 if phase == "preseason" else 8
    stand = {"c1": [], "c2": []}
    for i in range(N):
        t = tid(i)
        games = []
        for k in range(played):
            d = NOW - timedelta(days=3 * (played - k))
            o = tid((i + k + 1) % N)
            win = i == 0 or (k + i) % 2 == 0
            tie = hk and i == 5 and k == 7
            us, them = (3, 3) if tie else ((4, 1) if win else (1, 4))
            games.append({"id": f"{L}{i}{k}", "season": S, "date": iso(d), "status": "post", "stype": "reg", "home": t, "away": o, "hs": us, "as": them,
                          "conf_game": k % 2 == 0, "model": {"p_home": 0.3 if i == 0 else 0.5, "p_tie": 0.1 if hk else None}})
        # a result dated after the build clock (a later rebuild's data): never read
        games.append({"id": f"{L}{i}late", "season": S, "date": iso(NOW + timedelta(hours=30)), "status": "post", "stype": "reg", "home": t, "away": tid((i + 1) % N),
                      "hs": 0, "as": 9, "model": {"p_home": 0.5}})
        games.append({"id": f"{L}{i}exh", "season": S, "date": iso(NOW - timedelta(days=40)), "status": "post", "stype": "exh", "home": t, "away": "999", "hs": 99, "as": 0})
        for k in range(3):
            games.append({"id": f"{L}{i}n{k}", "season": S, "date": iso(NOW + timedelta(days=2 + k * 3)), "status": "pre", "stype": "reg", "home": t, "away": tid((i + 5 + k) % N),
                          "conf_game": True, "model": {"p_home": 0.7, "p_tie": 0.08 if hk else None, "p_away": 0.22 if hk else None}, "market": {"p_home": 0.66}})
        if hk:
            cols = ["id", "season", "date", "status", "stype", "home", "away", "hs", "as", "conf_game", "model.p_home", "model.p_tie", "model.p_away", "market.p_home"]
            sched = {"$cols": cols, "$rows": [[g.get("id"), g.get("season"), g.get("date"), g.get("status"), g.get("stype"), g.get("home"), g.get("away"), g.get("hs"), g.get("as"),
                                               g.get("conf_game"), (g.get("model") or {}).get("p_home"), (g.get("model") or {}).get("p_tie"), (g.get("model") or {}).get("p_away"),
                                               (g.get("market") or {}).get("p_home")] for g in games]}
        else:
            sched = games
        w = sum(1 for g in games if g["status"] == "post" and g["stype"] == "reg" and g["date"] <= iso(NOW) and g["hs"] > g["as"])
        lo = sum(1 for g in games if g["status"] == "post" and g["stype"] == "reg" and g["date"] <= iso(NOW) and g["hs"] < g["as"])
        ti = played - w - lo
        rec = {"w": w, "l": lo, "conf_w": w // 2, "conf_l": lo // 2, "home": [w, lo] + ([ti] if hk else []), "away": [0, 0] + ([0] if hk else []),
               "streak": "W3", "conf_rank": 1 if i in (0, 6) else (i % 6) + 1}
        if hk:
            rec["t"] = ti
        stats = {"rating": {"v": 20 - i}, "off": {"v": 10 - i * 0.5}, "def": {"v": 5 - i * 0.3}, "ppg": {"v": 40 - i}, "sos": {"v": 1.0}}
        write(data / L / str(S) / "teams" / f"{t}.json", {
            "ok": True, "id": t, "level": L, "season": S, "team": teams[t], "record": rec,
            "rating": {"rating": 20 - i, "off": 10 - i * 0.5, "def": 5 - i * 0.3, "rank": i + 1}, "schedule": sched, "stats": stats,
            "strengths": [{"unit": "DL/edge" if L == "cfb" else "Defense (adj.)", "key": "def", "grade": "A", "pctl": 92.0}, {"unit": "QB" if L == "cfb" else "Guards", "key": "q", "grade": "B", "pctl": 70.0}],
            "needs": [{"unit": "OL", "key": "ol", "grade": "D", "pctl": 18.0}, {"unit": "QB" if L == "cfb" else "Guards", "key": "q", "grade": "B", "pctl": 70.0}],
            "odds": {("p_cfp" if L == "cfb" else "p_ncaa"): 0.9 if i == 0 else 0.2, "p_title": 0.3 if i == 0 else 0.01, "sos_rem": 5.0 - i, "n_rem": 3},
            "top_performers": {} if phase == "preseason" else {"key": "gar" if hk else "value_pg", "label": "GAR" if hk else "Value/game", "pool": B.POOL[L],
                                                              "overall": [{"id": f"p{i}", "name": f"Ace {i}", "pos": "F" if hk else "QB", "v": 5.0 - i * 0.1, "rank": i + 1, "n": 80}]},
            "roster": {"$cols": ["id", "name", "pos", "value"], "$rows": [[f"r{i}", f"Vet {i}", "G", 100.0 - i]]}, "roster_basis": "last_season" if phase == "preseason" else "season"})
        stand["c1" if i < 6 else "c2"].append({"team": t, "conf_rank": rec["conf_rank"]})
    write(data / L / str(S) / "teams.json", {"ok": True, "metrics": [{"key": "rating", "label": "Rating", "fmt": "signed1"}, {"key": "off", "label": "Offense", "fmt": "signed1", "group": "Model"},
                                                                        {"key": "def", "label": "Defense", "fmt": "signed1", "group": "Model"}, {"key": "ppg", "label": "Points/game", "fmt": "1"},
                                                                        {"key": "sos", "label": "SOS", "fmt": "signed1"}]})
    paths = {tid(i): [[(NOW - timedelta(days=45)).date().isoformat(), float(i)], [(NOW - timedelta(days=1)).date().isoformat(), 20.0 - i]] for i in range(N)}
    write(data / L / str(S) / "season.json", {"ok": True, "phase": phase, "conferences": {"c1": {"name": "Conf One", "short": "C1"}, "c2": {"name": "Conf Two", "short": "C2"}},
                                              "standings": stand, "power": [{"rank": i + 1, "team": tid(i), "rating": 20.0 - i} for i in range(N)],
                                              "rating_paths": paths, "polls": {"ap": [{"rank": 1, "team": tid(0)}]}, "sim": {"teams": {}}})
    key = "p_cfp" if L == "cfb" else "p_ncaa"
    write(data / L / "race_log.json", {str(S): {key: {(NOW - timedelta(days=8)).date().isoformat(): {tid(0): 0.6}, (NOW + timedelta(days=1)).date().isoformat(): {tid(0): 0.1}}}})
    write(data / L / "chance_log.json", {str(S): {key: {(NOW - timedelta(days=1)).date().isoformat(): {tid(0): 0.9}}}})
    write(data / L / "history.json", {"champions": []})
    return {"name": L, "current_season": S, "phase": "regular" if phase == "season" else phase, "teams": teams, "conferences": {"c1": {"short": "C1"}, "c2": {"short": "C2"}}}


def tree(tmp: Path) -> Path:
    data = tmp / "data"
    lv = {"cfb": level_tree(data, "cfb", 2026, "season"), "mbb": level_tree(data, "mbb", 2027, "preseason"), "mch": level_tree(data, "mch", 2027, "season")}
    write(data / "index.json", {"ok": True, "levels": lv})
    return data


def cards(data: Path, L: str) -> dict:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (data / "follow" / L).glob("*.json")}


def test_a_card_for_every_team_on_every_level(tmp_path):
    data = tree(tmp_path)
    for L in ("cfb", "mbb", "mch"):
        s = B.build(data, L, NOW)
        assert s["n"] == N and s["max"] <= FL.MAX_BYTES
        c = cards(data, L)
        assert set(c) == {tid(i) for i in range(N)}
        assert all(x["k"] == f"campus:{L}:{t}" and x["team"]["href"] == f"#/{L}/team/{t}" for t, x in c.items())


def test_football_card(tmp_path):
    data = tree(tmp_path)
    B.build(data, "cfb", NOW)
    c = cards(data, "cfb")[tid(0)]
    assert c["phase"] == "season" and c["team"]["league"] == "College football" and c["team"]["group"] == "C1"
    assert c["now"]["record"] == "8–0" and c["now"]["standing"]["text"] == "1st in the C1" and c["now"]["rating"]["rank"] == 1
    # no look-ahead: tomorrow's 0-9 is not the last result, and the log point after now is not the 7-day move
    assert c["last"]["res"] == "W" and "late" not in c["last"]["id"] and c["now"]["form"] == "WWWWW"
    assert c["chances"][-1]["key"] == "p_title" and abs(c["chances"][0]["d7"] - 0.3) < 1e-9
    assert len(c["next"]) == 3 and c["next"][0]["p"] == 0.7 and c["next"][0]["mkt"] == 0.66 and c["next"][0]["comp"] == "C1"
    assert c["profile"]["strong"][0]["label"] == "Defensive front" and c["profile"]["weak"] == [{"id": "ol", "label": "OL", "pct": 18, "text": "D"}]
    kinds = [f["kind"] for f in c["facts"]]
    assert len(kinds) == len(set(kinds)) == 5 and {"streak", "rating_move", "swing"} <= set(kinds)
    assert not ("rating" in kinds and "rating_move" in kinds)
    # a long shot's headline is the playoff place
    assert cards(data, "cfb")[tid(5)]["chances"][-1]["key"] == "p_cfp"


def test_hockey_columnar_schedule_and_ties(tmp_path):
    data = tree(tmp_path)
    B.build(data, "mch", NOW)
    c = cards(data, "mch")
    assert c[tid(5)]["last"]["res"] == "D" and c[tid(5)]["now"]["record"].count("–") == 2
    n = c[tid(0)]["next"][0]
    assert n["p"] == 0.7 and n["p_draw"] == 0.08 and "mkt" not in n
    assert c[tid(0)]["players"][0]["metric"] == "GAR"


def test_basketball_preseason(tmp_path):
    data = tree(tmp_path)
    B.build(data, "mbb", NOW)
    c = cards(data, "mbb")[tid(0)]
    assert c["phase"] == "preseason" and "record" not in c["now"] and c["now"]["rating"]["label"] == "Preseason rating"
    assert c["line"].startswith("Preseason: 1st of 12 in our ratings, AP No. 1")
    assert c["players"][0]["metric"] == "Value, last season"
    assert any(f["kind"] == "pctl" and "preseason" in f["text"] for f in c["facts"])


def test_rows_of_decodes_format_2():
    x = {"$cols": ["id", "model.p_home", "model.p_tie"], "$rows": [["1", 0.6, None]]}
    assert B.rows_of(x) == [{"id": "1", "model": {"p_home": 0.6}}]
    assert B.rows_of([{"id": "2"}]) == [{"id": "2"}]
