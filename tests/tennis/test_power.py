"""The Ace's power rankings adapter (oddsmarkets/tennis/analytics/power_build.py) on a small synthetic data tree."""
import json
from pathlib import Path

import pytest

from oddsmarkets.tennis.analytics import power_build as PB

AS_OF = "2031-06-11"                      # a Wednesday: the week of 9 Jun is in play and folds into now
IDLE, RHO = 60.0, 0.5
# overall Elo after each match: [date, elo, surface]; p4 last played in February (pulled towards 1500 for the lay-off)
HIST = {
    "p1": [["2031-05-20", 1900.0, "clay"], ["2031-05-27", 1910.0, "clay"], ["2031-06-03", 1905.0, "clay"], ["2031-06-10", 1890.0, "grass"]],
    "p2": [["2031-05-20", 1850.0, "clay"], ["2031-05-28", 1870.0, "clay"], ["2031-06-04", 1890.0, "clay"], ["2031-06-05", 1920.0, "clay"]],
    "p3": [["2031-05-21", 1800.0, "clay"], ["2031-05-29", 1790.0, "clay"], ["2031-06-02", 1780.0, "clay"], ["2031-06-09", 1800.0, "grass"]],
    "p4": [["2031-01-20", 1850.0, "hard"], ["2031-02-10", 1880.0, "hard"]],
}


def _w(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def _pull(r, last, when):
    from datetime import date
    gap = (date.fromisoformat(when) - date.fromisoformat(last)).days
    return 1500 + (r - 1500) * RHO ** ((gap - IDLE) / 365) if gap > IDLE else r


def _tree(root: Path, season: bool = True):
    now = {p: (h[-1][1] if p != "p4" else _pull(1880.0, "2031-02-10", "2031-06-12")) for p, h in HIST.items()}
    order = sorted(now, key=lambda p: -now[p])
    _w(root / "index.json", {"tours": {"atp": {"year": 2031, "events_now": [{"event": "halle-2031", "name": "Halle Open", "level": "500"}] if season else [],
                                               "upcoming": []}}})
    _w(root / "atp" / "elo.json", {"ok": True, "as_of": AS_OF, "updated_at": "2031-06-11T12:00:00Z",
                                   "params": {"idle_days": IDLE, "rho": RHO},
                                   "current": {p: {"all": round(now[p], 1), "hard": 1800.0 + i, "clay": 1850.0 - i, "grass": 1700.0 + 10 * i, "rank": order.index(p) + 1}
                                               for i, p in enumerate(HIST)},
                                   "history": HIST})
    players = {}
    for i, p in enumerate(HIST):
        players[p] = {"name": f"Player {p.upper()}", "short": f"P. Name{p[-1]}", "country": "AAA", "qualified": i < 3,
                      "values": {"wins": 10 - i, "losses": i, "titles": 3 - i, "serve_rating": 1.0 - 0.2 * i, "return_rating": 0.2 * i,
                                 "hold": 0.8 - 0.01 * i, "brk": 0.2 + 0.01 * i, "elo_clay": 1850.0 - i},
                      "values_surface": {"clay": {"matches": 5 + i, "win_pct": 0.7, "titles": 1, "hold": 0.8, "brk": 0.3, "elo_surface": 1850.0 - i}}}
    _w(root / "atp" / "players.json", {"ok": True, "year": 2031, "floor": 8, "surface_floor": {"hard": 10, "clay": 6, "grass": 5}, "players": players})
    _w(root / "atp" / "rankings.json", {"ok": True, "official": [[1, "p2", 5000, 0], [2, "p1", 4000, 0]]})
    _w(root / "atp" / "race.json", {"ok": True, "finals_qual": {"p1": 0.9, "p2": 0.5}, "remaining_events": [{"id": "x"}] if season else [],
                                    "week": {"p2": [["rome-2031", "F", "W"]]}})
    _w(root / "atp" / "2031" / "events.json", {"ok": True, "events": {"rome-2031": {"name": "Italian Open", "level": "m1000", "city": "Rome"}}})


def test_ace_snapshots_pull_and_form(tmp_path):
    _tree(tmp_path)
    res = PB.build(tmp_path)
    assert res["leagues"] == ["atp"]                              # no WTA payloads: that tour is skipped
    d = json.loads((tmp_path / "power" / "atp.json").read_text(encoding="utf-8"))
    assert d["kind"] == "players" and d["step"] == "week" and d["phase"] == "season"
    # weeks of play end on Sundays (p4's in January and February, then 25 May, 1 Jun and 8 Jun); the week of 9 Jun (in
    # play) folds into now, which stands in for the last completed week: the move is against the week before (1 Jun)
    assert [s["label"] for s in d["snapshots"]] == ["26 Jan", "16 Feb", "25 May", "1 Jun", "Now"]
    by = {t["id"]: t for t in d["teams"]}
    # no look-ahead: at 1 Jun, p2's last match was 28 May (1870), not 4 Jun; p4 is pulled for the lay-off to 2 Jun
    raw = {"p1": 1910.0, "p2": 1870.0, "p3": 1790.0, "p4": _pull(1880.0, "2031-02-10", "2031-06-02")}
    avg = sum(raw.values()) / 4
    assert by["p2"]["rpath"][3] == pytest.approx(raw["p2"] - avg, abs=0.06)
    assert by["p4"]["rpath"][3] == pytest.approx(raw["p4"] - avg, abs=0.06)
    assert by["p1"]["path"][:2] == [None, None] and by["p4"]["path"][0] == 1     # not rated yet in January
    assert by["p2"]["rank"] == 1 and by["p2"]["prev"] == 2 and by["p2"]["move"] == 1
    # form from the rating's moves: p2 won three in a row, p1 lost its last two
    assert by["p2"]["form"] == "WWW" and by["p2"]["streak"] == "W3" and by["p1"]["form"] == "WLL"
    assert by["p2"]["record"] == "9–1" and {"label": "Ranking", "text": "1"} in by["p2"]["stats"]
    assert by["p2"]["chance"] == {"label": "Finals spot", "p": 0.5} and by["p2"]["href"] == "#/atp/player/p2"
    assert by["p2"]["note"] == "New No. 1, up from 2nd; won 3 straight."
    assert PB._week_line([["rome-2031", "F", "W"]], {"rome-2031": {"level": "m1000", "city": "Rome"}}, "atp") == "Champion in Rome"
    assert PB._week_line([["ao-2031", "SF", "A"]], {"ao-2031": {"level": "slam", "name": "Australian Open"}}, "atp") == "Into the semi-finals at the Australian Open"
    assert by["p2"]["short"] == "Name2" and by["p2"]["abbr"] == "NAM"
    assert len({by[p]["colour"] for p in by}) == 4               # the top eight never share a line colour
    g = {x["key"]: x for x in d["players"]["groups"]}
    assert list(g) == ["serve", "return", "clay"]               # hard and grass: nobody has the surface floor
    assert g["serve"]["n"] == 3 and g["serve"]["top"][0]["id"] == "p1" and g["return"]["top"][0]["id"] == "p3"
    assert g["clay"]["n"] == 3 and g["clay"]["metric"]["key"] == "elo_surface"   # p1 (5 clay matches) is under the floor of 6
    assert [s["label"] for s in g["serve"]["stats"]] == ["Hold %"]


def test_ace_offseason_final(tmp_path):
    _tree(tmp_path, season=False)
    PB.build(tmp_path)
    d = json.loads((tmp_path / "power" / "atp.json").read_text(encoding="utf-8"))
    assert d["phase"] == "offseason"
    assert [s["label"] for s in d["snapshots"]] == ["26 Jan", "16 Feb", "25 May", "1 Jun", "Final"]
    assert all("chance" not in t for t in d["teams"])
    # Final is the end of the last completed week of play (8 Jun), not now: p1's 10 Jun loss is not in it
    p1 = next(t for t in d["teams"] if t["id"] == "p1")
    raw8 = {"p1": 1905.0, "p2": 1920.0, "p3": 1780.0, "p4": _pull(1880.0, "2031-02-10", "2031-06-09")}
    assert p1["rpath"][-1] == pytest.approx(raw8["p1"] - sum(raw8.values()) / 4, abs=0.06)
