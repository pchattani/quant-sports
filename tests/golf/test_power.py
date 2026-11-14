"""The Quant Green's power rankings (oddsmarkets/golf/power_build.py) on a small synthetic data tree."""
from __future__ import annotations

import json
from pathlib import Path

from oddsmarkets.golf import power_build as G

TODAY = "2026-11-14"          # a Saturday: the week of 9 Nov is under way


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _tree(root: Path, live_e2: bool = False) -> None:
    """Three finished event weeks (e0 22 Oct, e1 29 Oct, e2 5 Nov) and this week's e3 (PGA, live chances) and e4 (DP
    World, under way without live chances). A won e2; B has not played since e1; C debuted in e2; D is short of rounds
    before e2."""
    ev = {"e0": ("2026-10-22", "Zero Open"), "e1": ("2026-10-29", "One Classic"), "e2": ("2026-11-05", "Two Championship pres. by Sponsor")}

    def player(pid, name, hist, rounds, rt, extra=None):
        h = [[ev[e][0], v, e] for e, v in hist]
        p = {"pid": pid, "name": name, "history": h, "form": [[ev[e][0], 1.0, rounds.get(e, 4), v] for e, v in hist],
             "events": [{"id": e, "date": ev[e][0], "name": ev[e][1], "pos": (1 if (pid == "A" and e == "e2") else 30), "tie": False,
                         "st": "finish"} for e, _ in reversed(hist)]}
        p.update(extra or {})
        _w(root / "players" / f"{pid}.json", p)
        return p

    player("A", "Alpha Adams", [("e0", 0.9), ("e1", 1.0), ("e2", 1.2)], {}, 1.5)
    player("B", "Bravo De Boer", [("e0", 1.4), ("e1", 1.4)], {}, 1.3)
    player("C", "Charlie Cole", [("e2", -0.5)], {}, 1.6)
    player("D", "Delta Dunn", [("e0", 0.2), ("e1", 0.3), ("e2", 0.4)], {"e0": 2}, 0.45)
    rows = [{"rank": 1, "pid": "C", "name": "Charlie Cole", "rt": 1.6, "wt": 12.0, "n": 24, "tour": "pga", "starts": 1, "wins": 0, "top10": 0, "l5": [["e2", 30, False, "finish"]]},
            {"rank": 2, "pid": "A", "name": "Alpha Adams", "rt": 1.5, "wt": 60.0, "n": 300, "tour": "pga", "starts": 20, "wins": 2, "top10": 8,
             "l5": [["e0", 30, False, "finish"], ["e1", 30, False, "finish"], ["e2", 1, False, "finish"]]},
            {"rank": 3, "pid": "B", "name": "Bravo De Boer", "rt": 1.3, "wt": 55.0, "n": 280, "tour": "eur", "starts": 18, "wins": 0, "top10": 3, "l5": []},
            {"rank": 4, "pid": "D", "name": "Delta Dunn", "rt": 0.45, "wt": 11.0, "n": 22, "tour": "pga", "starts": 3, "wins": 0, "top10": 0, "l5": []}]
    _w(root / "rankings.json", {"updated_at": TODAY, "min_weight": 10.0, "active_days": 400, "men": rows,
                                "women": [{"rank": i + 1, "pid": f"W{i}", "name": f"Woman {i}", "rt": 2.0 - i / 10, "wt": 50.0, "n": 200,
                                           "tour": "lpga", "starts": 10, "wins": 0, "top10": 2, "cc": "USA"} for i in range(3)]})
    for i in range(3):
        _w(root / "players" / f"W{i}.json", {"pid": f"W{i}", "history": [["2026-10-29", 2.0 - i / 10, "w1"]], "form": [["2026-10-29", 0.0, 4, 2.0]]})
    week = [{"id": "e3", "tour": "pga", "start": "2026-11-12", "status": "live", "key": "lwin", "name": "Three Open"},
            {"id": "e4", "tour": "eur", "start": "2026-11-12", "status": "live", "key": "win", "name": "Four Masters"}]
    if live_e2:
        week.append({"id": "e2", "tour": "pga", "start": "2026-11-05", "status": "live", "key": "win", "name": "Two Championship"})
    _w(root / "index.json", {"today": TODAY, "updated_at": TODAY + "T02:00+00:00", "week": week})
    _w(root / "events" / "e3.json", {"players": [{"pid": "A", "win": 0.05, "lwin": 0.21}]})
    _w(root / "events" / "e4.json", {"players": [{"pid": "B", "win": 0.12}]})
    cols = ["id", "n", "tour", "q", "sg", "c_ott", "c_app", "c_arg", "c_putt", "dist", "acc", "gir", "h4", "sand", "bog", "ppg", "bird"]
    _w(root / "scout" / "men.json", {"cols": cols, "metrics": [{"id": "c_ott", "tip": "Our estimate."}],
                                     "rows": [[p, p + " name", "pga", 1, 0.1 * i, 0.2 * i, 0.1, -0.1 * i, 0.3, 300 + i, 0.6, 0.7, 0.01, 0.5, 0.1, 1.7, 0.25]
                                              for i, p in enumerate("ABCD")] + [["X", "Not regular", "pga", 0, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9]]})
    wcols = ["id", "n", "tour", "q", "sg", "sg_e", "sg_w", "sg_f", "sg_b", "cut", "sd", "t10", "win", "great", "poor"]
    _w(root / "scout" / "women.json", {"cols": wcols, "rows": [[f"W{i}", f"Woman {i}", "lpga", 1] + [0.5 - i / 10] * 11 for i in range(3)]})


def test_snapshots_ranks_moves_and_no_look_ahead(tmp_path):
    _tree(tmp_path)
    res = G.build(tmp_path)
    assert res["leagues"] == ["men", "women"]
    d = json.loads((tmp_path / "power" / "men.json").read_text(encoding="utf-8"))
    # one snapshot per finished event week (weeks of 19 Oct, 26 Oct, 2 Nov), the last replaced by now
    assert [s["label"] for s in d["snapshots"]] == ["25 Oct", "1 Nov", "Now"]
    t = {x["id"]: x for x in d["teams"]}
    # after the week of 26 Oct: A's rating is the one he carried into e2 (1.2, the win not in it); B has not played since
    # e1, so his rating then is today's (1.3); C had not teed it up; D was short of 20 rounds before e2
    assert t["A"]["rpath"][1] == 1.2 and t["B"]["rpath"][1] == 1.3
    assert t["C"]["rpath"][:2] == [None, None] and t["D"]["rpath"][:2] == [None, None]
    assert (t["C"]["rank"], t["C"]["prev"]) == (1, None) and "New to the rankings" in t["C"]["note"]
    assert (t["A"]["rank"], t["A"]["prev"], t["A"]["move"]) == (2, 2, 0)
    assert (t["B"]["rank"], t["B"]["prev"], t["B"]["move"]) == (3, 1, -2)
    assert t["A"]["note"].startswith("Won the Two Championship") and "pres. by" not in t["A"]["note"]
    assert t["B"]["short"] == "De Boer" and t["A"]["abbr"] == "AA"
    # this week's chance: live where the event has live chances, none where it is under way without them
    assert t["A"]["chance"] == {"label": "Win this week", "p": 0.21} and "chance" not in t["B"]
    assert d["kind"] == "players" and d["phase"] == "season" and d["rating"]["fmt"] == "+2"
    assert len({x["colour"] for x in d["teams"]}) == len(d["teams"])          # colours tell the lines apart


def test_a_week_in_play_folds_into_now(tmp_path):
    _tree(tmp_path, live_e2=True)
    G.build(tmp_path)
    d = json.loads((tmp_path / "power" / "men.json").read_text(encoding="utf-8"))
    assert [s["label"] for s in d["snapshots"]] == ["25 Oct", "Now"]
    assert all(len(x["path"]) == 2 for x in d["teams"])


def test_groups_categories_and_splits(tmp_path):
    _tree(tmp_path)
    G.build(tmp_path)
    men = json.loads((tmp_path / "power" / "men.json").read_text(encoding="utf-8"))["players"]["groups"]
    assert [g["key"] for g in men] == ["ott", "app", "arg", "putt"]
    ott = men[0]
    assert ott["n"] == 4 and ott["top"][0]["id"] == "D" and ott["top"][0]["team"] == "PGA"     # the non-regular X is out
    assert "PGA Tour season statistics" in ott["min"] and ott["metric"]["tip"] == "Our estimate."
    women = json.loads((tmp_path / "power" / "women.json").read_text(encoding="utf-8"))
    assert [g["key"] for g in women["players"]["groups"]] == ["r12", "wknd", "front", "back"]
    idx = json.loads((tmp_path / "power.json").read_text(encoding="utf-8"))
    assert idx["default"] == "men" and [x["label"] for x in idx["leagues"]] == ["Men’s tours", "LPGA"]


def test_helpers():
    assert G.short_event("The ANNIKA driven by Gainbridge at Pelican") == "The ANNIKA"
    assert G.the_event("The ANNIKA driven by X") == "The ANNIKA" and G.the_event("U.S. Open") == "the U.S. Open"
    assert G.surname("Manon De Roey") == "De Roey" and G.surname("Davis Love III") == "Love"
    assert G.finish(4, True, "finish") == "T4" and G.finish(None, False, "cut") == "MC"
    assert G.tidy("Up 2 places this week; No start since X.") == "Up 2 places this week; no start since X."
