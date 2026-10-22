"""The basketball payload writer on synthetic stores: every PAYLOADS.md file is written with its contract keys."""
import json

import pytest

from oddsmarkets.college.hoops import build as B
from oddsmarkets.college.hoops import data as D
from oddsmarkets.college.packing import is_packed, unpack

from .hoops_synth import make_level


@pytest.fixture
def built(tmp_path, monkeypatch):
    monkeypatch.setenv("CAMPUS_STORES", str(tmp_path / "stores"))
    monkeypatch.setenv("CAMPUS_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("CAMPUS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("CAMPUS_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(B, "current_season", lambda level: 2027)
    D._CACHE.clear()
    B._CTX.clear()
    make_level("mbb", seasons=(2025, 2026), current=2027)
    out = tmp_path / "data"
    res = B.build_level("mbb", out, sims=300, markets=False)
    return out, res


def raw(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def load(p):
    """A payload as the front end reads it (packed lists expanded)."""
    return unpack(raw(p))


def test_level_files(built):
    out, res = built
    assert res["ok"], res
    cal = load(out / "mbb" / "calibration.json")
    assert cal["ok"] and set(cal["summary"]) >= {"model", "elo", "close", "vs_close", "espn_predictor"}
    vc = cal["summary"]["vs_close"]
    assert vc["n"] > 0 and vc["ats_n"] > 0 and 0 <= vc["ats_hit"] <= 1
    assert cal["per_season"] and cal["calibration"] and cal["sim"]["tournament"]["n_seasons"] >= 1
    h = load(out / "mbb" / "history.json")
    assert h["ok"] and len(h["champions"]) == 2 and h["best_teams"]
    mk = load(out / "mbb" / "markets.json")
    assert mk["ok"] and mk["fetched"] is False and mk["model"]["champion"]
    careers = list((out / "mbb" / "players").glob("*.json"))
    assert careers
    c = load(careers[0])
    assert c["ok"] and c["seasons"] and c["current"]["log"]


def test_season_files(built):
    out, res = built
    d = out / "mbb" / "2026"
    s = load(d / "season.json")
    assert s["ok"] and s["phase"] == "offseason" and s["ratings"] and s["standings"] and s["power"]
    r = next(iter(s["ratings"].values()))
    assert set(r) >= {"rating", "off", "def", "tempo", "se", "rank", "games", "sos", "sos_rank", "luck"}
    st = next(iter(s["sim"]["teams"].values()))
    assert set(st) >= {"exp_w", "exp_l", "p_ncaa", "p_auto", "p_at_large", "seed_mean", "seed_dist", "p_round", "p_title"}
    sch = load(d / "schedule.json")
    assert sch["ok"] and all("id" in c and "home" in c for c in sch["games"])
    br = load(d / "bracket.json")
    assert br["ok"] and br["actual"]["regions"] and br["odds"] and br["rounds"][0] == "R64"
    champ = sum(v["p_round"]["Champion"] for v in br["odds"].values())
    assert champ == pytest.approx(1.0, abs=0.01)
    assert br["selection_fit"]["n_seasons"] == 2
    for f in ("teams", "players", "value", "moves", "fantasy", "lab_players", "lab_teams"):
        assert load(d / f"{f}.json")["ok"], f
    tp = load(next((d / "teams").glob("*.json")))
    # 2026 is past (current 2027): an archive season, its team pages read schedule.json and season.json rating_paths
    assert tp["ok"] and set(tp) >= {"rating", "rank_history", "stats", "roster", "units", "strengths", "needs", "moves",
                                    "odds", "suggestions"}
    assert "schedule" not in tp and "rating_path" not in tp and tp["suggestions"] == []
    assert s["fmt"] == B.FORMAT and sch["compact"] is True
    assert is_packed(raw(d / "schedule.json")["games"]) and is_packed(raw(d / "players.json")["players"])
    assert isinstance(load(d / "players.json")["players"], dict)
    gp = list((d / "games").glob("*.json"))
    assert gp                                   # previous season's postseason pages
    g = load(gp[0])
    assert g["ok"] and g["stype"] in ("ncaa", "conf", "nit", "wbit", "post") and g["box"] and g["pregame"]["model"]
    bx = next(iter(g["box"].values()))
    assert bx["players"] and isinstance(bx["players"][0], list) and len(bx["players"][0]) == len(B.ST.BOX_COLS)
    assert set(bx["names"]) <= {str(r[0]) for r in bx["players"]} | {str(x[0]) for x in bx["dnp"]}


def test_current_preseason(built):
    out, res = built
    d = out / "mbb" / "2027"
    s = load(d / "season.json")
    assert s["phase"] == "preseason" and s["sim"]["teams"]
    br = load(d / "bracket.json")
    assert br["actual"] is None and len(br["projected"]["regions"]) == 4 and br["bracketology"]
    assert sum(len(v) for v in br["projected"]["regions"].values()) == 68
    v = load(d / "value.json")
    assert v["ok"] and v["basis"] == "last_season"
    mv = load(d / "moves.json")
    assert mv["ok"]
    tp = load(next((d / "teams").glob("*.json")))
    assert isinstance(tp["schedule"], list) and tp["schedule"] and "rating_path" in tp     # the current season in full
    assert not list((d / "games").glob("*.json"))        # nothing played yet


def test_migrate_upgrades_an_old_season_folder(built):
    out, res = built
    d = out / "mbb" / "2026"
    # write 2026 back in the old format (lists plain, team pages with a schedule, no fmt), as the live site had it
    sch = load(d / "schedule.json")
    pl = load(d / "players.json")
    sea = raw(d / "season.json")
    sea.pop("fmt")
    tf = next((d / "teams").glob("*.json"))
    tp = load(tf)
    tp["schedule"] = [c for c in sch["games"] if tp["id"] in (c["home"], c["away"])]
    tp["rating_path"] = [["2026-01-01", 1.0]]
    for f, obj in (("schedule.json", sch), ("players.json", pl), ("season.json", sea)):
        (d / f).write_text(json.dumps(obj), encoding="utf-8")
    tf.write_text(json.dumps(tp), encoding="utf-8")
    n = B.migrate("mbb", out, 2026)
    assert n >= 4
    assert raw(d / "season.json")["fmt"] == B.FORMAT
    assert is_packed(raw(d / "schedule.json")["games"]) and load(d / "schedule.json")["games"] == sch["games"]
    assert load(d / "players.json")["players"] == pl["players"]
    t2 = load(tf)
    assert "schedule" not in t2 and "rating_path" not in t2 and t2["roster"] == tp["roster"]
    assert B.migrate("mbb", out, 2026) == 0                 # idempotent
