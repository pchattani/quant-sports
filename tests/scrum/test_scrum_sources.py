"""The Quant Scrum's second-wave sources (2 Nov 2026): Wikipedia's rugbyboxes and results lists, the merge with ESPN
(referees, result-only tests before 1891, the source switch), ESPN core-API bios, Open-Meteo's weather window and
venue elevation (the altitude edge), and the referee, scoring-clock and caps pieces built from them."""
from __future__ import annotations

import html as _html
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from oddsmarkets.rugby import extras, nations, store, wiki
from oddsmarkets.rugby.ratings import Model, Params
from oddsmarkets.rugby.sources import espn, weather, wiki_html


def _box(params: dict) -> str:
    mw = {"parts": [{"template": {"target": {"wt": "rugbybox", "href": "./Template:Rugbybox"},
                                  "params": {k: {"wt": v} for k, v in params.items()}, "i": 0}}]}
    return "<div class=\"vevent\" data-mw='" + _html.escape(json.dumps(mw), quote=True).replace("'", "&#39;") + "'>x</div>"


BOX = {"date": "1 February 2019", "time": "21:00 CET (UTC+1)", "home": "(1 BP) {{ru-rt|FRA}}", "score": "19–24",
       "away": "{{ru|WAL}}", "stadium": "[[Stade de France]], [[Saint-Denis]]", "attendance": "60,000",
       "referee": "[[Wayne Barnes]] ([[Rugby Football Union|England]])"}


# ── parsing ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_rugbybox_parses_teams_score_time_venue_referee_and_crowd():
    rows = wiki.rows_from_boxes(_box(BOX), "2019 Six Nations Championship")
    assert len(rows) == 1
    r = rows[0]
    assert (r["home"], r["away"], r["hs"], r["as"]) == ("France", "Wales", 19, 24)
    assert r["date"] == "2019-02-01" and r["time_utc"] == "2019-02-01T20:00"
    assert r["venue"]["name"] == "Stade de France" and r["venue"]["city"] == "Saint-Denis"
    assert r["attendance"] == 60000 and r["referee"] == {"name": "Wayne Barnes", "union": "England"}
    assert r["comp"] == "six" and r["scope"] == "men"


@pytest.mark.parametrize("raw,want", [
    ("{{ru|NZL}}", "New Zealand"), ("{{Ru-rt|JAP}}", "Japan"), ("{{flagicon|TON}} Tonga", "Tonga"),
    ("{{RuA|AUS}}", None), ("{{ruA|SCO|name=Scotland XV}}", None), ("[[Barbarian F.C.|Barbarians]]", None),
    ("[[French Barbarians]] {{flagicon|FRA}}", None), ("{{Ru|FJI|colonial}}", "Fiji"), ("{{ru|USA}}", "United States"),
    ("{{flagicon|NZL}} [[Chiefs (rugby union)|Chiefs]]", None), ("Canada {{flagicon|CAN}}", "Canada"),
])
def test_side_keeps_full_tests_only(raw, want):
    assert wiki.side(raw, False) == want


def test_dates_times_scores_and_referees():
    assert wiki.parse_date("1950-01-14") == "1950-01-14"
    assert wiki.parse_date("Saturday 4 November 2023") == "2023-11-04"
    assert wiki.parse_date("November 20, 2026") == "2026-11-20"
    assert wiki.parse_date("06/01/1900") == "1900-01-06"
    assert wiki.parse_time_utc("2008-06-07", "14:05 (UTC+12)") == "2008-06-07T02:05"
    assert wiki.parse_time_utc("2019-02-01", "21:00 CET") is None
    assert wiki.parse_score("34 - 17") == (34, 17) and wiki.parse_score("Cancelled") is None
    assert wiki.parse_referee("Jaime Vial (Chile)") == {"name": "Jaime Vial", "union": "Chile"}
    assert wiki.parse_referee("") is None


def test_classify_competitions_and_scopes():
    assert wiki.classify("1950 Five Nations Championship") == ("six", "men")
    assert wiki.classify("2024 Women's Six Nations Championship") == ("w6n", "women")
    assert wiki.classify("2023 WXV") == ("wxv", "women")
    assert wiki.classify("2019 Rugby World Cup Pool A") == ("rwc", "men")
    assert wiki.classify("2019 Rugby World Cup – Europe qualification") == ("test", "men")
    assert wiki.classify("2012 Tri Nations Series")[0] == "trc"


def test_results_list_table_reads_our_side_first_and_the_city():
    html = ('<table class="wikitable"><tr><th>Date</th><th>Opponent</th><th>F</th><th>A</th><th>Venue</th><th>City</th><th>Winner</th></tr>'
            '<tr><td>1905-11-18</td><td><a href="./Scotland_national_rugby_union_team" title="Scotland national rugby union team">Scotland</a></td>'
            '<td>12</td><td>7</td><td>Inverleith</td><td>Edinburgh</td><td>New Zealand</td></tr>'
            '<tr><td>1903-08-15</td><td><a href="./Australia_national_rugby_union_team" title="Australia national rugby union team">Australia</a></td>'
            '<td>22</td><td>3</td><td>Sydney Cricket Ground</td><td>Sydney</td><td></td></tr></table>')
    rows = wiki.rows_from_tables(html, "List of New Zealand rugby union test matches")
    by = {r["date"]: r for r in rows}
    sco = by["1905-11-18"]
    assert sco["home"] == "Scotland" and sco["away"] == "New Zealand" and (sco["hs"], sco["as"]) == (7, 12) and sco["neutral"] is False
    aus = by["1903-08-15"]
    assert aus["home"] == "Australia" and (aus["hs"], aus["as"]) == (3, 22)


def test_fix_sides_turns_a_row_played_at_the_away_sides_ground():
    rows = [dict(r, kind="box", comp="six", event="") for r in [
        {"home": "Scotland", "away": "England", "venue": {"name": "Murrayfield", "city": "Edinburgh"}, "hs": 10, "as": 3},
        {"home": "Scotland", "away": "Wales", "venue": {"name": "Murrayfield", "city": "Edinburgh"}, "hs": 6, "as": 3},
        {"home": "Ireland", "away": "Scotland", "venue": {"name": "Murrayfield", "city": "Edinburgh"}, "hs": 9, "as": 12}]]
    wiki.fix_sides(rows)
    r = rows[2]
    assert (r["home"], r["away"], r["hs"], r["as"]) == ("Scotland", "Ireland", 12, 9) and r["neutral"] is False


def test_squad_tables_read_current_and_most_capped():
    html = ('<h2>Current squad</h2><table class="wikitable"><tr><th>Player</th><th>Position</th><th>Date of birth (age)</th><th>Caps</th><th>Club</th></tr>'
            '<tr><td>Ardie Savea</td><td>Number 8</td><td>14 October 1993 (age 33)</td><td>100</td><td>Hurricanes</td></tr></table>'
            '<h2>Most caps</h2><table class="wikitable"><tr><th>#</th><th>Player</th><th>Career</th><th>Caps</th></tr>'
            '<tr><td>1</td><td>Sam Whitelock</td><td>2010-2023</td><td>153</td></tr></table>')
    t = wiki.squad_tables(html)
    assert t["current"] == [{"name": "Ardie Savea", "caps": 100, "dob": "1993-10-14", "pos": "Number 8"}]
    assert t["most_caps"][0]["name"] == "Sam Whitelock" and t["most_caps"][0]["caps"] == 153


# ── the merge with ESPN ──────────────────────────────────────────────────────────────────────────────────────

def _espn(mid, d, h, a, hs, as_, hid="1", aid="2"):
    return {"id": mid, "date": d + "T15:00Z", "status": "final", "comp": "six", "neutral": False, "venue": {},
            "home": {"id": hid, "name": h}, "away": {"id": aid, "name": a}, "hs": hs, "as": as_}


def test_merge_attaches_referees_adds_old_tests_and_respects_the_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("RUGBY_STORES", str(tmp_path))
    rows = [
        {"date": "2019-02-01", "home": "France", "away": "Wales", "hs": 19, "as": 24, "venue": {}, "attendance": 60000,
         "referee": {"name": "Wayne Barnes", "union": "England"}, "comp": "six", "event": "Six Nations Championship",
         "page": "2019 Six Nations Championship", "scope": "men", "kind": "box", "neutral": False},
        {"date": "1880-02-28", "home": "England", "away": "Scotland", "hs": 23, "as": 1, "venue": {"city": "Manchester"},
         "attendance": None, "referee": None, "comp": "six", "event": "", "page": "1880 Home Nations", "scope": "men",
         "kind": "table", "neutral": False},
        {"date": "1931-01-01", "home": "France", "away": "Germany", "hs": 34, "as": 0, "venue": {}, "attendance": None,
         "referee": None, "comp": "test", "event": "", "page": "x", "scope": "men", "kind": "table", "neutral": False}]
    for r in rows:
        r["wid"] = wiki.wid(r)
    store.write_gz(tmp_path / "side" / "wiki" / "men.json.gz", {"rows": rows, "squads": {}})
    wiki._CACHE.clear()
    espn_rows = [_espn("100", "2019-02-01", "France", "Wales", 19, 24, "9", "4"), _espn("101", "2019-02-09", "Scotland", "Wales", 11, 18, "2", "4"),
                 _espn("102", "2019-03-16", "England", "Scotland", 38, 38, "1", "2")]
    out, rep = wiki.merge("men", [dict(m) for m in espn_rows])
    assert rep["matched_espn"] == 1 and rep["added"] == 2 and rep["referees_attached"] == 1
    fra = next(m for m in out if m["id"] == "100")
    assert fra["referee"]["name"] == "Wayne Barnes" and fra["attendance"] == 60000
    old = next(m for m in out if m["date"].startswith("1880"))
    assert old["ro"] == 1 and (old["hs"], old["as"]) == (8, 0) and old["home"]["id"] == "1" and old["source"] == "wikipedia"
    ger = next(m for m in out if m["date"].startswith("1931"))
    assert ger["away"]["id"] == "wGER" and ger["away"]["name"] == "Germany"
    monkeypatch.setenv("SOURCE_WIKIPEDIA_RUGBY_ENABLED", "0")
    out2, rep2 = wiki.merge("men", [dict(m) for m in espn_rows])
    assert len(out2) == 3 and rep2 == {"enabled": False}


def test_merge_reports_a_score_conflict_and_keeps_espn(tmp_path, monkeypatch):
    monkeypatch.setenv("RUGBY_STORES", str(tmp_path))
    r = {"date": "2019-02-01", "home": "France", "away": "Wales", "hs": 20, "as": 24, "venue": {}, "attendance": None,
         "referee": {"name": "X Y", "union": ""}, "comp": "six", "event": "", "page": "p", "scope": "men", "kind": "box", "neutral": False}
    r["wid"] = wiki.wid(r)
    store.write_gz(tmp_path / "side" / "wiki" / "men.json.gz", {"rows": [r], "squads": {}})
    wiki._CACHE.clear()
    out, rep = wiki.merge("men", [_espn("100", "2019-02-01", "France", "Wales", 19, 24)])
    assert rep["score_conflicts"] == 1 and "referee" not in out[0] and out[0]["hs"] == 19


# ── ESPN bios, weather, altitude ─────────────────────────────────────────────────────────────────────────────

def test_core_api_athlete_bio_converts_units():
    d = {"dateOfBirth": "1995-04-20T07:00Z", "height": 68.9, "weight": 178.6, "position": {"abbreviation": "FB"},
         "birthPlace": {"city": "Invercargill", "country": "New Zealand"}}
    assert espn.parse_athlete(d) == {"dob": "1995-04-20", "ht_cm": 175, "wt_kg": 81, "pos": "FB", "born": "New Zealand",
                                     "city": "Invercargill"}
    assert espn.parse_athlete({"height": 0, "weight": 1000}) == {}


def test_weather_window_averages_the_match_hours():
    h = {"time": [f"2024-11-09T{i:02d}:00" for i in range(24)], "temperature_2m": [10.0] * 15 + [12.0, 14.0, 16.0] + [9.0] * 6,
         "relative_humidity_2m": [80] * 24, "precipitation": [0.0] * 16 + [0.5, 1.0, 0.2] + [0.0] * 5,
         "wind_speed_10m": [20.0] * 24, "wind_gusts_10m": [30.0] * 16 + [45.0] + [30.0] * 7}
    w = weather.window(h, "2024-11-09T15")
    assert w == {"temp": 14.0, "rh": 80, "wind": 20.0, "gust": 45.0, "rain": 1.7}
    assert weather.window(h, "2024-11-10T15") is None


def test_altitude_edge_only_for_visitors_from_lower_down(monkeypatch):
    m = {"home": {"id": "5", "name": "South Africa"}, "away": {"id": "8", "name": "New Zealand"},
         "venue": {"name": "Ellis Park", "city": "Johannesburg", "elev": 1750}, "neutral": False, "date": "2024-08-31"}
    assert nations.altitude_edge(m) == 1
    assert nations.altitude_edge(dict(m, away={"id": "x", "name": "Namibia"})) == 0
    assert nations.altitude_edge(dict(m, venue={"elev": 20})) == 0
    assert nations.altitude_edge(dict(m, neutral=True)) == 0
    a = Model(Params(c_alt=4.0, split=False)).expect(m)
    b = Model(Params(c_alt=0.0, split=False)).expect(m)
    assert a["ctx"]["alt"] == 1 and abs((a["margin"] - b["margin"]) - 4.0) < 1e-9


# ── the payload pieces ───────────────────────────────────────────────────────────────────────────────────────

def _S(finals, upcoming=()):
    return SimpleNamespace(finals=finals, upcoming=list(upcoming), today="2026-11-02", scope="men",
                           now=datetime(2026, 11, 2, tzinfo=timezone.utc))


def test_referee_tendencies_count_penalties_cards_and_home_share(monkeypatch):
    fin = []
    for i in range(6):
        m = _espn(str(i), f"2020-02-0{i + 1}", "France", "Wales", 20, 10, "9", "4")
        m["referee"] = {"name": "Ref One", "union": "Ireland"}
        m["hstat"], m["astat"] = {"pens": 8, "yc": 1, "rc": 0, "tries": 2}, {"pens": 12, "yc": 0, "rc": 0, "tries": 1}
        fin.append(m)
    w = {"fc": {m["id"]: {"p_home": 0.5, "p_draw": 0.0, "p_away": 0.5} for m in fin}}
    up = [dict(_espn("u1", "2026-11-08", "England", "Australia", None, None), status="pre", referee={"name": "Ref One", "union": "Ireland"})]
    d = extras.referees_payload(_S(fin, up), w)
    r = d["refs"][0]
    assert r["name"] == "Ref One" and r["n"] == 6 and r["pens"] == 20.0 and r["home_pen_share"] == 0.4
    assert r["yc"] == 1.0 and r["home_win"] == 1.0 and r["home_vs_exp"] == 0.5
    assert d["upcoming"][0]["ref"] == "Ref One" and d["n"] == 6


def test_scoring_clock_bands_and_half_time_leads():
    m = _espn("1", "2020-02-01", "France", "Wales", 15, 3)
    m["events"] = [[5, "try", "h", "", "", 5, 0], [30, "pg", "a", "", "", 5, 3], [62, "try", "h", "", "", 10, 3],
                   [78, "try", "h", "", "", 15, 3]]
    c = extras.scoring_clock(_S([m]))
    assert c["n"] == 1 and c["bands"][0]["pts"] == 5 and c["bands"][2]["pts"] == 3 and c["bands"][7]["tries"] == 1
    assert c["ht_lead"] == {"n": 1, "won": 1.0, "drew": 0.0} and c["first_try"] == [[5, 1]]


def test_name_matching_for_career_caps():
    idx = {"full": {"ardie savea": "a1", "faf de klerk": "a2"}, "li": {("savea", "a"): ["a1"], ("klerk", "f"): ["a2"]}, "last": {}}
    assert extras.match_name(idx, "Ardie Savea") == "a1"
    assert extras.match_name(idx, "A. Savea") == "a1"
    assert extras.match_name(idx, "Faf de Klerk") == "a2"
    assert extras.match_name(idx, "Beauden Barrett") is None
    assert extras.fold("Jérôme Garcès") == "jerome garces"
