"""College Hockey News parsers and politeness rules (oddsmarkets/college/sources/chn.py), on saved pages.

The fixtures (tests/college/fixtures/chn/*.html.gz) are CHN pages saved on 30 Oct 2026; they are private (never
exported to the public build repo), so these tests skip where the fixtures are absent."""
from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from oddsmarkets.college.sources import chn

FX = Path(__file__).parent / "fixtures" / "chn"


def page(name: str) -> str:
    p = FX / f"{name}.html.gz"
    if not p.exists():
        pytest.skip("CHN fixtures are private")
    return gzip.decompress(p.read_bytes()).decode("utf-8")


# ── robots and politeness ──────────────────────────────────────────────────────────────────────────────────

def test_robots_rules_disallow_old_boxes_and_api():
    rules = chn.parse_robots(page("robots_txt"))
    assert not chn.robots_allows(rules, "/box/final/20241025/bu_/con/")
    assert not chn.robots_allows(rules, "/box/final/20100123/mia/akf/")
    assert not chn.robots_allows(rules, "/box/final/19991010/a/b/")
    assert chn.robots_allows(rules, "/box/final/20251025/bu_/con/")
    assert chn.robots_allows(rules, "/box/final/20261001/bu_/wis/w")
    assert chn.robots_allows(rules, "/box/metrics.php?gd=110805")
    assert chn.robots_allows(rules, "/stats/team/Boston-University/10/overall,20152016")
    assert not chn.robots_allows(rules, "/reports/api/anything")
    assert not chn.robots_allows(rules, "/stats/custom/")
    assert not chn.robots_allows(rules, "/players/x?search=abc")
    assert not chn.robots_allows(rules, "/box/livebox.php?x=1")


def test_robots_wildcards_and_longest_match():
    rules = chn.parse_robots("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /*?q=\nDisallow: /end$\n"
                             "User-agent: CCBot\nDisallow: /\n")
    assert not chn.robots_allows(rules, "/a/c")
    assert chn.robots_allows(rules, "/a/b/c")
    assert not chn.robots_allows(rules, "/x/y?q=1")
    assert not chn.robots_allows(rules, "/end")
    assert chn.robots_allows(rules, "/end/more")
    assert chn.robots_allows(rules, "/free")


def test_switch_and_no_fetch_on_ci(monkeypatch):
    monkeypatch.setenv("CHN_ENABLED", "0")
    assert not chn.enabled()
    assert not chn.fetch_allowed()
    assert chn.Client().get("/anything") is None
    monkeypatch.setenv("CHN_ENABLED", "1")
    monkeypatch.setenv("CI", "true")
    assert chn.enabled() and not chn.fetch_allowed()
    assert chn.Client().offline


def test_user_agent_names_the_project():
    assert "TheQuantCampus" in chn.USER_AGENT and "@" not in chn.USER_AGENT
    assert chn.INTERVAL >= 2.0


def test_cache_paths_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("CHN_RAW", str(tmp_path))
    a = chn.cache_path("/stats/team/A/1/overall,20152016")
    b = chn.cache_path("/stats/team/A/1/overall,20162017")
    w = chn.cache_path("/women/stats/team/A/1/overall,20152016")
    assert len({a, b, w}) == 3 and str(a).startswith(str(tmp_path))


# ── team season pages ──────────────────────────────────────────────────────────────────────────────────────

def test_season_teams_by_conference():
    teams = chn.parse_season_teams(page("t_overall"))
    assert len(teams) == 60
    by = {t["name"]: t for t in teams}
    assert by["Boston University"]["conf"] == "Hockey East"
    assert by["Air Force"] == {"slug": "Air-Force", "chn_id": "1", "name": "Air Force", "conf": "Atlantic Hockey"}
    assert by["Northern Michigan"]["conf"] == "WCHA"


def test_overall_skaters_and_goalies():
    o = chn.parse_overall(page("t_overall"))
    assert o["record"].startswith("21-13-5")
    first = o["skaters"][0]
    assert first["name"] == "Danny O'Regan" and first["pos"] == "F" and first["cls"] == "Sr"
    assert (first["g"], first["a"], first["pts"], first["sh"], first["pm"], first["ppg"]) == (17, 27, 44, 137, 5, 7)
    assert first["chn_pid"] == "27630"
    g = o["goalies"][0]
    assert (g["name"], g["gp"], g["ga"], g["min"], g["sv"]) == ("Sean Maguire", 25, 55, 1372, 630)
    assert not any(s["name"].upper().startswith("TOTAL") for s in o["skaters"])


def test_gamebygame_old_and_current_layouts():
    g = chn.parse_gamebygame(page("t_gamebygame"), 2016)
    assert len(g) == 39
    x = g[0]
    assert x["date"] == "2016-03-26" and x["site"] == "neutral" and x["res"] == "L"
    assert x["gf"]["t"] == 2 and x["ga"]["t"] == 7 and x["sf"]["t"] == 21 and x["sa"]["t"] == 25
    assert (x["ppg"], x["ppo"], x["opp_ppg"], x["opp_ppo"], x["pim"], x["att"]) == (0, 2, 2, 4, 11, 4926)
    assert x["gd"] == "26577" and not x["gd_live"] and x["box"] == "/box/final/20160326/bu_/den/"
    cur = chn.parse_gamebygame(page("gbg_2027_xg"), 2027)
    assert cur[0]["xg"] == 2.66 and cur[0]["xga"] == 3.23 and cur[0]["att"] == 5800
    assert cur[0]["scorers"].startswith("Perron")


def test_gamebygame_rows_without_data():
    g = chn.parse_gamebygame(page("w_gbg"), 2018)
    assert g and all(x.get("nodata") for x in g)
    assert g[0]["box"].endswith("/w") and g[0]["date"] == "2018-02-25"


def test_attempt_tables_season_and_game():
    adv = chn.parse_attempt_tables(page("t_advanced"))
    r = adv[0]["rows"][0]
    assert r["name"] == "Ahti Oksanen" and r["all_tsa"] == 369 and r["ev_tsa"] == 289 and r["pp_g"] == 4
    m = chn.parse_attempt_tables(page("metrics"))
    kinds = [(t["team"], t["kind"]) for t in m]
    assert kinds == [("HC", "skaters"), ("Army", "skaters"), ("HC", "goalies")]
    gk = m[-1]["rows"]
    assert [x["team"] for x in gk] == ["HC", "Army", "Army"]
    assert gk[0]["all_sv"] == 21 and gk[0]["sh_ga"] == 1
    assert chn.metrics_has_data(page("metrics")) and not chn.metrics_has_data(page("m_old"))


def test_roster_bio():
    r = chn.parse_roster(page("roster"))
    a = r[0]
    assert a["name"] == "Carter Amico" and a["pos"] == "D" and a["ht_in"] == 77 and a["dob"] == "2007-03-15"
    assert a["last_team"].startswith("USA U-18") and a["draft"] == "2025-PHL-2"


# ── box scores ─────────────────────────────────────────────────────────────────────────────────────────────

def test_box_men():
    b = chn.parse_box(page("box"))
    assert b["away"]["name"] == "Boston University" and b["home"]["chn_id"] == "17"
    assert (b["away"]["score"], b["home"]["score"]) == (3, 1)
    assert b["away"]["shots"] == [12, 5, 3, 20] and b["home"]["xg"] == 2.3
    assert (b["away"]["ppg"], b["away"]["ppo"], b["away"]["fow"]) == (2, 3, 26)
    assert b["game_type"] == "Hockey East Game" and b["att"] == 2513 and b["venue"].startswith("Toscano Forum")
    assert b["date"] == "2025-10-25" and b["ot"] == 0 and not b["so"]
    assert len(b["goals"]) == 4 and b["goals"][0]["sit"] == "PP" and b["goals"][0]["t"] == 1180
    assert b["goals"][0]["scorer_pid"] == "59306" and b["goals"][0]["a2"] == "Conrad Fondrk"
    assert len(b["pens"]) == 5 and b["pens"][0]["inf"] == "Too Many Players"
    gk = [x for x in b["goalies"] if not x["en"]]
    assert [x["name"] for x in gk] == ["Mikhail Yegorov", "Tyler Muszelik"] and gk[0]["sec"] == 3600
    sk = b["skaters"][0]
    assert sk["name"] == "Owen McLaughlin" and sk["toi"] == 1185 and sk["team"] == "away"


def test_box_women_no_toi():
    b = chn.parse_box(page("w_box"))
    assert b["home"]["name"] == "Wisconsin" and b["home"]["score"] == 7
    assert all(s["toi"] is None for s in b["skaters"]) and {s["team"] for s in b["skaters"]} == {"home", "away"}


def test_scoreboard():
    s = chn.parse_scoreboard(page("sched"))
    assert len(s) == 27 and s[0]["gd"] == "110805" and s[0]["away"]["name"] == "Holy Cross" and s[0]["home"]["score"] == 1
