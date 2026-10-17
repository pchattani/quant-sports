"""Data layer of The Quant Ace: tennis-data, ESPN, WTA and charting parsing, identity, merging,
stores and draws (recorded fixtures, no network)."""
from __future__ import annotations

import json
from collections import Counter

import pytest

from oddsmarkets.tennis import canon, store
from oddsmarkets.tennis.sources import charting, espn, tennisdata as td, wta

from .conftest import FIX, load


# ── tennis-data ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def td_atp():
    return td.parse(td.read_rows(FIX / "td_atp_2025_slice.csv"), "atp", 2025)


@pytest.fixture(scope="module")
def td_wta():
    return td.parse(td.read_rows(FIX / "td_wta_2025_slice.csv"), "wta", 2025)


def test_links_page_prefix():
    html = ('<A HREF="hrjk-85HytOjkhth76j_ygh4jf7/2026/2026.xlsx">2026</A> <A HREF="2026w/2026.xlsx">w</A>'
            '<A HREF="hrjk-85HytOjkhth76j_ygh4jf7/2012w/2012.xls">2012</A>')
    got = td.parse_links(html)
    assert got[("atp", 2026)] == "https://www.tennis-data.co.uk/hrjk-85HytOjkhth76j_ygh4jf7/2026/2026.xlsx"
    assert got[("wta", 2012)].endswith("/2012w/2012.xls")
    assert got[("wta", 2026)] == "https://www.tennis-data.co.uk/2026w/2026.xlsx"


def test_td_parse_atp(td_atp):
    assert len(td_atp) >= 300
    st = Counter(r["status"] for r in td_atp)
    assert st["ret"] > 0 and st["wo"] > 0 and st["done"] > 250
    ao = [r for r in td_atp if r["event"]["tid_hint"] == "australian-open"]
    rounds = Counter(r["round"] for r in ao)
    assert rounds["R128"] == 64 and rounds["R64"] == 32 and rounds["F"] == 1
    assert all(r["best_of"] == 5 for r in ao)
    assert {r["event"]["level"] for r in ao} == {"slam"}
    assert ao[0]["event"]["draw_size"] == 128
    for r in td_atp:
        assert r["winner"] == "a"
        if r["status"] == "done":
            w = sum(1 for s in r["sets"] if s[0] > s[1])
            assert w == r["sets_won"][0], r
    odds = [r for r in td_atp if r["odds"] and "ps" in r["odds"]]
    assert len(odds) > 0.9 * len(td_atp)
    assert all(o > 1 for r in odds for o in r["odds"]["ps"])


def test_td_parse_wta(td_wta):
    assert len(td_wta) >= 300
    assert all(r["best_of"] == 3 for r in td_wta)
    assert all(len(r["sets"]) <= 3 for r in td_wta)
    wo = [r for r in td_wta if r["status"] == "wo"]
    assert wo and all(len(r["sets"]) == 0 for r in wo)
    ret = [r for r in td_wta if r["status"] == "ret"]
    assert ret and any(len(r["sets"]) and r["sets"][-1][0] <= r["sets"][-1][1] for r in ret)
    lv = {r["event"]["tid_hint"]: r["event"]["level"] for r in td_wta}
    assert lv["australian-open"] == "slam" and lv["brisbane"] == "500"


def test_td_round_labels():
    full = ["1st Round"] * 16 + ["2nd Round"] * 8 + ["Quarterfinals"] * 4 + ["Semifinals"] * 2 + ["The Final"]
    lab = canon.td_round_labels(full)
    assert lab["1st Round"] == "R32" and lab["2nd Round"] == "R16" and lab["The Final"] == "F"
    # a Slam still in its first round: the bracket comes from the level, not from the rounds seen
    early = canon.td_round_labels(["1st Round"] * 30, level="slam")
    assert early["1st Round"] == "R128"
    # a 96-draw Masters in progress (32 first-round matches): R128
    assert canon.td_round_labels(["1st Round"] * 32, level="m1000", tid="indian-wells", tour="atp", year=2025)["1st Round"] == "R128"
    # 56-draw Masters in progress
    assert canon.td_round_labels(["1st Round"] * 24, level="m1000", tid="monte-carlo", tour="atp", year=2025)["1st Round"] == "R64"
    assert canon.td_round_labels(["Round Robin"] * 12 + ["Semifinals"] * 2 + ["The Final"])["Round Robin"] == "RR"
    assert canon.entrants(128, 32) == 96 and canon.entrants(32, 12) == 28 and canon.entrants(32, 16) == 32


def test_td_group_events_merges_split_numbers():
    rows = [{"WTA": 10, "Tournament": "Family Circle Cup", "Location": "Charleston", "Date": "2018-04-02",
             "Round": "1st Round", "Winner": "A X.", "Loser": "B Y."},
            {"WTA": 11, "Tournament": "Family Circle Cup", "Location": "Charleston", "Date": "2018-04-03",
             "Round": "2nd Round", "Winner": "A X.", "Loser": "C Z."},
            {"WTA": 12, "Tournament": "Adelaide International 1", "Location": "Adelaide", "Date": "2022-01-03",
             "Round": "1st Round", "Winner": "D X.", "Loser": "E Y."},
            {"WTA": 13, "Tournament": "Adelaide International 1", "Location": "Adelaide", "Date": "2022-01-10",
             "Round": "1st Round", "Winner": "F X.", "Loser": "G Y."}]
    groups = td.group_events(rows, "WTA")
    assert [len(g) for g in groups] == [2, 1, 1]


# ── canon: rules ────────────────────────────────────────────────────────────

def test_levels_and_tids():
    assert canon.level_from_series("wta", "WTA263") == "250"
    assert canon.level_from_series("atp", "International Gold") == "500"
    assert canon.level_from_series("atp", "Masters Cup") == "finals"
    assert canon.level_from_series("wta", "Tour Championships", "WTA Elite Trophy") == "other"
    assert canon.fix_level("wta", 2018, "indian-wells", "500", "Premier") == "m1000"
    assert canon.fix_level("wta", 2018, "doha", "500", "Premier") == "m1000"
    assert canon.fix_level("wta", 2017, "doha", "500", "Premier") == "500"
    assert canon.tid_for("atp", "French Open", "Paris", "slam") == "roland-garros"
    assert canon.tid_for("atp", "BNP Paribas Masters", "Paris", "m1000") == "paris"
    assert canon.tid_for("atp", "Western & Southern Financial Group Masters", "New York", "m1000") == "cincinnati"
    assert canon.tid_for("atp", "HSBC Championships", "London") == "queens"
    assert canon.tid_for("wta", "Rogers Cup", "Toronto", "m1000") == "canada"
    assert canon.tid_for("atp", "Masters Cup", "Turin", "finals") == "atp-finals"
    assert canon.tid_for("atp", "U.S. Men's Clay Court Championships", "Houston", "250") == "houston"
    assert canon.tid_for("atp", "Laver Cup", "Boston") == "skip"
    assert canon.tid_for("atp", "x", "'s-Hertogenbosch") == "s-hertogenbosch"


def test_final_set_rules_and_best_of():
    assert canon.final_set_rule("atp", "wimbledon", 2018) == ("adv", 0)
    assert canon.final_set_rule("atp", "wimbledon", 2019) == ("tb7", 12)
    assert canon.final_set_rule("wta", "wimbledon", 2022) == ("tb10", 6)
    assert canon.final_set_rule("atp", "australian-open", 2019) == ("tb10", 6)
    assert canon.final_set_rule("atp", "roland-garros", 2021) == ("adv", 0)
    assert canon.final_set_rule("atp", "us-open", 2010) == ("tb7", 6)
    assert canon.final_set_rule("atp", "us-open", 2022) == ("tb10", 6)
    assert canon.final_set_rule("atp", "indian-wells", 2005) == ("tb7", 6)
    assert canon.best_of("atp", "slam", "QF") == 5 and canon.best_of("atp", "slam", "Q3") == 3
    assert canon.best_of("wta", "slam", "F") == 3 and canon.best_of("atp", "m1000", "F") == 3


def test_points_tables():
    assert canon.points("atp", "slam", "W") == 2000 and canon.points("atp", "slam", "R128") == 10
    assert canon.points("atp", "m1000", "R64", 96) == 30 and canon.points("atp", "m1000", "R64", 56) == 10
    assert canon.points("atp", "250", "R32", 48) == 13 and canon.points("atp", "250", "R32", 28) == 0
    assert canon.points("wta", "slam", "SF") == 780 and canon.points("wta", "500", "F") == 325
    for tour in ("atp", "wta"):
        for lv in ("slam", "m1000", "500", "250"):
            t = canon.points_table(tour, lv)
            vals = [t[k] for k in ("W", "F", "SF", "QF", "R16") if k in t]
            assert vals == sorted(vals, reverse=True)
    assert canon.POINTS_VERIFY is True


# ── canon: names ────────────────────────────────────────────────────────────

def test_fold_and_parse():
    assert canon.fold("Báez, Sebastián") == "baez sebastian"
    assert canon.fold("Stan Wawrinka") == "stan wawrinka" and canon.fold("Ørjan") == "orjan"
    assert canon.parse_abbrev("Sinner J.") == (["sinner"], ["j"])
    assert canon.parse_abbrev("Fernandez L.A.") == (["fernandez"], ["l", "a"])
    assert canon.parse_abbrev("Ugo Carabelli C.") == (["ugo", "carabelli"], ["c"])
    assert canon.parse_abbrev("Auger-Aliassime F.") == (["auger", "aliassime"], ["f"])
    assert canon.parse_abbrev("Wang Xin.") == (["wang"], ["xin"])
    assert canon.parse_abbrev("Carlos Alcaraz") is None


@pytest.mark.parametrize("abbr,first,last,ok", [
    ("Sinner J.", "Jannik", "Sinner", True),
    ("Fernandez L.A.", "Leylah Annie", "Fernandez", True),
    ("Ugo Carabelli C.", "Camilo", "Ugo Carabelli", True),
    ("Auger-Aliassime F.", "Felix", "Auger-Aliassime", True),
    ("Auger Aliassime F.", "Félix", "Auger-Aliassime", True),
    ("Wang Xin.", "Xinyu", "Wang", True),
    ("Wang Xin.", "Xiyu", "Wang", False),
    ("Wang Ji.", None, "Wang Jiaqi", True),                 # ESPN full name in Chinese order
    ("Mpetshi Perricard G.", "Giovanni", "Mpetshi Perricard", True),
    ("De Minaur A.", "Alex", "de Minaur", True),
    ("Bautista R.", "Roberto", "Bautista Agut", True),
    ("Sinner J.", "Jakub", "Mensik", False),
])
def test_abbrev_matches(abbr, first, last, ok):
    sur, inits = canon.parse_abbrev(abbr)
    if first is None:
        fn, ln = canon.split_full(last)
    else:
        fn, ln = canon.name_tokens(first), canon.name_tokens(last)
    assert (canon.abbrev_matches(sur, inits, fn, ln) > 0) is ok


def test_registry_within_field_and_promotion(tmp_data):
    reg = canon.Registry("atp")
    a = reg.add("espn", first="Alexander", last="Zverev", espn="2375")
    b = reg.add("espn", first="Mischa", last="Zverev", espn="1030")
    assert reg.resolve_abbrev("td", "Zverev A.", field={a, b}, has_field=True) == a
    assert reg.resolve_abbrev("td", "Zverev M.", field={a, b}, has_field=True) == b
    # a tennis-data-only player later linked to a full name: redirect, no duplicate
    x = reg.resolve_abbrev("td", "Safin M.")
    assert x.startswith("x:") and reg.players[x].get("_abbrev")
    y = reg.add("charting", full="Marat Safin")
    assert y == x
    # an x: player that later gets an ESPN id is renamed and redirected
    z = reg.add("wta", first="Some", last="Player", wta="999")
    assert z.startswith("x:")
    z2 = reg.add("espn", full="Some Player", espn="12345")
    assert z2 == "12345" and reg.canonical(z) == "12345" and reg.players["12345"]["wta"] == "999"
    reg.save()
    reg2 = canon.Registry.load("atp")
    assert reg2.canonical(z) == "12345" and reg2.by_espn["2375"] == a


def test_registry_overrides():
    reg = canon.Registry("atp")
    reg.add("espn", first="Tomas", last="Barrios Vera", espn="9923")
    assert reg.resolve_abbrev("td", "Barrios M.", field={"9923"}, has_field=True) == "9923"


# ── ESPN ────────────────────────────────────────────────────────────────────

def test_espn_live_day():
    recs = espn.parse_scoreboard(load("espn_atp_20261001.json.gz"), "atp")
    assert recs and all(r["a"]["espn"] and r["b"]["espn"] for r in recs)          # TBD pairings skipped
    st = Counter(r["status"] for r in recs)
    assert st["done"] > 10 and st["upcoming"] > 0
    assert {r["event"]["tid_hint"] for r in recs} >= {"tokyo", "beijing"}
    assert {r["round"] for r in recs} <= set(canon.ROUNDS)
    for r in recs:
        if r["status"] == "live":
            assert r["live"]["set"] == len(r["sets"]) + 1 or r["live"]["games"] == [0, 0]
            assert r["winner"] is None
        if r["status"] == "done":
            assert r["winner"] in ("a", "b")
        for s in r["sets"]:
            if s[2] is not None:
                assert abs(s[0] - s[1]) == 1 and max(s[0], s[1]) == 7
                hi, lo = (s[2], s[3]) if s[0] > s[1] else (s[3], s[2])
                assert hi >= 7 and hi - lo >= 2 and (hi == 7 or hi - lo == 2)
    wrecs = espn.parse_scoreboard(load("espn_wta_20261001.json.gz"), "wta")
    assert wrecs and all(r["tour"] == "wta" for r in wrecs)
    assert not ({r["src_id"] for r in wrecs} & {r["src_id"] for r in recs})          # singles of each tour only


def test_espn_round_labels():
    lab = canon.espn_round_labels(["Qualifying 1st Round", "Qualifying Final", "Round 1", "Round 2", "Round 3",
                                   "Round 4", "Quarterfinal", "Semifinal", "Final"])
    assert lab == {"Qualifying 1st Round": "Q1", "Qualifying Final": "Q2", "Round 1": "R128", "Round 2": "R64",
                   "Round 3": "R32", "Round 4": "R16", "Quarterfinal": "QF", "Semifinal": "SF", "Final": "F"}
    assert canon.espn_round_labels(["Group Stage", "Semifinal", "Final"])["Group Stage"] == "RR"


def test_espn_rankings():
    rk = espn.parse_rankings(load("espn_rankings_atp.json.gz"))
    assert len(rk["rows"]) == 150 and rk["rows"][0][0] == 1 and rk["rows"][0][1]["espn"]
    assert rk["rows"][0][1]["last"] and rk["date"]


# ── WTA API ─────────────────────────────────────────────────────────────────

def test_wta_matches_and_stats():
    raw = load("wta_matches_1152_2026.json.gz")
    recs = wta.parse_matches(raw)
    assert recs and all(r["tour"] == "wta" for r in recs)
    by_id = {r["src_id"]: r for r in recs}
    wo = by_id["LS010"]
    assert wo["status"] == "wo" and wo["winner"] == "a" and wo["sets"] == [] and wo["a"]["last"] == "Mertens"
    tb = by_id["LS015"]                                         # Gibson d Morvayova 7-6(2) 7-6(1)
    assert tb["sets"] == [[7, 6, 7, 2], [7, 6, 7, 1]] and tb["winner"] == "a"
    b_won = by_id["LS017"]                                      # Winner "3": B won (Sasnovich d Kasatkina)
    assert b_won["winner"] == "b" and b_won["b"]["last"] == "Sasnovich"
    assert by_id["LS001"]["round"] == "F" and by_id["LS002"]["round"] == "SF" and by_id["LS030"]["round"] == "R32"
    assert by_id["RS014"]["round"] == "Q1" and by_id["RS005"]["round"] == "Q2"
    assert by_id["LS001"]["duration_min"] == 99
    st = wta.parse_stats(load("wta_stats_1152_2026_LS001.json"))
    a, b = st["a"], st["b"]
    assert a["aces"] == 5 and a["sv_pts"] == 53 and a["fs_in"] == 33 and a["fs_won"] == 22 and a["ss_won"] == 11
    assert a["rt_pts_won"] == b["sv_pts"] - b["fs_won"] - b["ss_won"]
    assert a["bp_faced"] == b["bp_opps"] and a["bp_saved"] == b["bp_opps"] - b["bp_conv"]
    assert sum(x["a"]["aces"] for x in st["by_set"]) == a["aces"]
    assert sum(x["b"]["sv_pts"] for x in st["by_set"]) == b["sv_pts"]


def test_wta_round_from_match_id():
    assert wta.round_from_match_id("LS001") == ("F", 0)
    assert wta.round_from_match_id("LS003") == ("SF", 1)
    assert wta.round_from_match_id("LS017") == ("R32", 1)
    assert wta.round_from_match_id("LS064") == ("R128", 0)
    assert wta.round_from_match_id("RS014") == (None, None)


def test_wta_draw():
    d = wta.parse_draw(load("wta_draw_1020_2026.json.gz"))
    assert d["size"] == 128 and len(d["slots"]) == 128
    assert d["slots"][0][1] == "324166" and d["slots"][0][2] == 1          # Rybakina, seed 1
    assert d["slots"][1][1] is None                                        # a bye
    assert sum(1 for s in d["slots"] if s[1] is None) == 32               # 96 players
    assert any(s[3] == "Q" for s in d["slots"])


# ── merging sources ─────────────────────────────────────────────────────────

def _store(tn_fetch, tour, year, parts):
    reg = canon.Registry(tour)
    s = store.new_store(tour, year)
    ing = tn_fetch.Ingest(s, reg)
    for src, recs in parts:
        ing.records(recs, src)
    store.drop_index(s)
    store.finalize_events(s)
    store.set_players(s, reg)
    return s, reg, ing


def test_merge_atp_espn_td(tmp_data, tn_fetch):
    e = espn.parse_scoreboard(load("espn_atp_20260925.json.gz"), "atp")
    t = td.parse(td.read_rows(FIX / "td_atp_2026_chengdu_hangzhou.csv"), "atp", 2026)
    s, reg, ing = _store(tn_fetch, "atp", 2026, [("espn", e), ("td", t)])
    rep = reg.report()["td"]
    assert rep["rate"] >= 0.99, rep                      # identity: >= 99% of tennis-data names inside the field
    main = [m for m in s["matches"].values() if m["level"] != "q"]
    td_m = [m for m in main if "td" in m["sources"]]
    assert len(td_m) == len(t)                           # one MATCH per real match
    both = [m for m in td_m if m["sources"] == ["espn", "td"]]
    assert len(both) >= 0.9 * len([m for m in main if "espn" in m["sources"] and m["status"] in store.FINAL])
    for m in both:
        assert m["winner"] == m["p1"] and m["odds"] and m["rank1"] is not None
        assert m["id"] == store.match_id(m["event"], m["round"], m["p1"], m["p2"])
        assert m["surface"] == "hard" and m["level"] == "250"
    assert any(x[2] is not None for m in both for x in m["sets"])     # ESPN's tiebreak points survive the merge
    assert {ev["tid"] for ev in s["events"].values()} >= {"chengdu", "hangzhou"}
    hz = s["events"]["hangzhou-2026"]
    assert hz["status"] == "done" and hz["champion"] and hz["draw"]["source"] == "reconstructed"
    assert hz["draw"]["complete"] and len([x for x in hz["draw"]["slots"] if x[1]]) >= 28


def test_merge_wta_three_sources(tmp_data, tn_fetch):
    e = espn.parse_scoreboard(load("espn_wta_20260925.json.gz"), "wta")
    w = wta.parse_matches(load("wta_matches_1152_2026.json.gz"), year=2026)
    final = next(r for r in w if r["src_id"] == "LS001")
    final["stats"] = wta.parse_stats(load("wta_stats_1152_2026_LS001.json"))
    t = td.parse(td.read_rows(FIX / "td_wta_2026_seoul_singapore.csv"), "wta", 2026)
    s, reg, ing = _store(tn_fetch, "wta", 2026, [("espn", e), ("wta", w), ("td", t)])
    assert reg.report()["td"]["rate"] >= 0.99
    sg = [m for m in s["matches"].values() if m["event"] == "singapore-2026" and m["level"] != "q"]
    assert sg and all("td" in m["sources"] for m in sg if m["status"] in store.FINAL)
    assert sum(1 for m in sg if set(m["sources"]) == {"espn", "td", "wta"}) >= 0.8 * len(sg)
    f = next(m for m in sg if m["round"] == "F")
    assert s["players"][f["p1"]]["name"].startswith("Leylah") and f["winner"] == f["p1"]
    assert f["stats"]["p1"]["aces"] == 5 and f["stats"]["p2"]["sv_pts"] == 69     # stats follow p1 = Fernandez
    assert f["odds"]["avg"][0] < f["odds"]["avg"][1] or f["odds"]["avg"][0] > 1
    assert f["duration_min"] == 99 and f["sets"] == [[7, 5, None, None], [6, 0, None, None]]
    ev = s["events"]["singapore-2026"]
    assert ev["indoor"] is True and ev["level"] == "500" and ev["wta"] == "1152"
    wo = [m for m in sg if m["status"] == "wo"]
    assert wo and wo[0]["sets"] == []
    p = s["players"][f["p1"]]
    assert p["wta"] and p["espn"]                                                   # ESPN and WTA ids linked


def test_merge_live_then_final(tmp_data, tn_fetch):
    """A live ESPN record is replaced by the final result, and the live block cleared."""
    live = espn.parse_scoreboard(load("espn_atp_20261001.json.gz"), "atp")
    lv = [r for r in live if r["status"] == "live"]
    if not lv:
        pytest.skip("no live match in the recorded day")
    r = json.loads(json.dumps(lv[0]))
    s, reg, ing = _store(tn_fetch, "atp", 2026, [("espn", [r])])
    m = next(iter(s["matches"].values()))
    assert m["status"] == "live" and m["live"] and m["winner"] is None
    fin = json.loads(json.dumps(r))
    fin.update(status="done", winner="b", live=None, sets=[[4, 6, None, None], [6, 3, None, None], [6, 7, 5, 7]])
    ing.records([fin], "espn")
    store.drop_index(s)
    (m2,) = s["matches"].values()
    assert m2["status"] == "done" and m2["live"] is None and m2["winner"] == m2["p1"]
    assert m2["sets"][-1] == [7, 6, 7, 5]                 # p1's view after the flip


def test_valid_score_and_conflict_rule():
    assert store.valid_score([[6, 4], [6, 4]], "done", 3)
    assert not store.valid_score([[6, 4], [6, 4], [2, 1]], "done", 3)
    assert not store.valid_score([[6, 7], [6, 7]], "done", 3)
    assert store.valid_score([[6, 4], [3, 6], [7, 6]], "done", 3)
    assert store.valid_score([[4, 6, None, None], [2, 1, None, None]], "ret", 3)
    assert store.valid_score([[6, 4], [3, 6], [6, 7], [7, 5], [6, 4]], "done", 5)


# ── stores ──────────────────────────────────────────────────────────────────

def test_store_roundtrip_and_redirects(tmp_data, tn_fetch):
    e = espn.parse_scoreboard(load("espn_atp_20260925.json.gz"), "atp")
    s, reg, _ = _store(tn_fetch, "atp", 2026, [("espn", e)])
    eid = next(iter(s["events"]))
    s["events"][eid]["_espn"] = "x-1"
    p = store.save(s)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert not any(k.startswith("_") for ev in raw["events"].values() for k in ev)
    assert raw["meta"]["event_src"][eid]["_espn"] == "x-1"
    pid = next(iter(raw["players"]))
    reg.redirects[pid] = "NEW"
    s2 = store.load("atp", 2026, reg)
    assert s2["events"][eid]["_espn"] == "x-1"
    assert "NEW" in s2["players"] and pid not in s2["players"]
    assert all(pid not in (m["p1"], m["p2"]) for m in s2["matches"].values())
    assert all(m["id"] == store.match_id(m["event"], m["round"], m["p1"], m["p2"]) for m in s2["matches"].values())
    for k in ("tour", "year", "updated_at", "players", "events", "matches", "rankings", "meta"):
        assert k in raw
    m = next(iter(raw["matches"].values()))
    for k in ("id", "event", "date", "round", "best_of", "surface", "indoor", "level", "p1", "p2", "winner", "status",
              "sets", "final_set_rule", "rank1", "rank2", "pts1", "pts2", "odds", "stats", "live", "sources", "duration_min"):
        assert k in m
    ev = next(iter(raw["events"].values()))
    for k in ("tid", "name", "year", "start", "end", "level", "surface", "indoor", "draw_size", "best_of", "city",
              "country", "espn", "wta", "status", "champion", "draw"):
        assert k in ev


def test_reconstruct_draw_eight():
    def M(r, a, b, d="2026-01-01"):
        return {"id": f"{r}{a}{b}", "round": r, "p1": a, "p2": b, "date": d}
    ms = [M("QF", "A", "B"), M("QF", "C", "D"), M("QF", "E", "F"), M("QF", "G", "H"),
          M("SF", "A", "C", "2026-01-02"), M("SF", "E", "G", "2026-01-02"), M("F", "A", "E", "2026-01-03")]
    d = store.reconstruct_draw(ms)
    assert d["size"] == 8 and d["complete"]
    assert [x[1] for x in d["slots"]] == ["A", "B", "C", "D", "E", "F", "G", "H"]
    # unplayed later rounds: first-round pairs still placed, bracket marked incomplete
    d2 = store.reconstruct_draw(ms[:4])
    assert not d2["complete"] and len([x for x in d2["slots"] if x[1]]) == 8
    # a bye: the seed appears first in the round of 16 of a 32 bracket
    ms3 = [M("R32", "A", "B"), M("R16", "S", "A")]
    d3 = store.reconstruct_draw(ms3)
    assert [x[1] for x in d3["slots"]] == ["S", None, "A", "B"]


# ── charting ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("first,second,server,expect", [
    ("6*", "", 1, {"outcome": "ace", "winner": 1, "rally_len": 1, "serve_dir": "t", "ace": True, "serve_no": 1}),
    ("4#", "", 2, {"outcome": "unreturnable", "winner": 2, "unret": True, "serve_dir": "wide"}),
    ("4n", "5d", 1, {"outcome": "df", "winner": 2, "df": True, "serve_no": 2, "first_dir": "wide", "first_fault": "n"}),
    ("5d", "4b38f1f3f3*", 2, {"outcome": "winner", "winner": 2, "rally_len": 5, "serve_no": 2, "return_depth": 8,
                              "return_wing": "bh", "ender_wing": "fh"}),
    ("4b2n#", "", 2, {"outcome": "forced", "winner": 2, "rally_len": 1, "unret": True}),
    ("6f37b2f1n@", "", 1, {"outcome": "unforced", "winner": 1, "rally_len": 3, "ender": 2, "ender_wing": "fh",
                           "return_depth": 7}),
    ("4+f28v1*", "", 1, {"outcome": "winner", "winner": 1, "snv": True, "rally_len": 3, "ender_shot": "v"}),
    ("c6f39b+3s2z1*", "", 2, {"outcome": "winner", "winner": 2, "rally_len": 5, "ender_shot": "z"}),
    ("S", "", 1, {"special": "S", "winner": 1}),
    ("R", "", 1, {"special": "R", "winner": 2}),
])
def test_charting_point_codes(first, second, server, expect):
    rec = charting.parse_point(first, second, server)
    for k, v in expect.items():
        assert rec[k] == v, (k, rec)


def test_charting_net_and_approaches():
    rec = charting.parse_point("6f39b+3s2z1*", "", 2)          # server (2) approaches with b+3, volley winner
    assert rec["net"][2] is True and rec["net"][1] is False
    shots = rec["shots"]
    assert [s["by"] for s in shots] == [1, 2, 1, 2] and shots[1]["approach"] is True and shots[0]["depth"] == 9
    rec2 = charting.parse_point("4f28f+1b2o3*", "", 1)         # server (1) approaches with f+1 and smashes a winner
    assert rec2["net"][1] is True and rec2["net"][2] is False and rec2["winner"] == 1


@pytest.mark.parametrize("pts,tb,side", [("0-0", False, "deuce"), ("15-0", False, "ad"), ("40-15", False, "deuce"), ("30-15", False, "ad"),
                                          ("40-40", False, "deuce"), ("AD-40", False, "ad"), ("40-AD", None, "ad"),
                                          ("3-2", True, "ad"), ("6-6", None, "deuce"), ("1-0", None, "ad")])
def test_charting_side(pts, tb, side):
    assert charting.side_from_score(pts, tb) == side


def test_charting_match_fixture():
    paths = {"charting-m-matches.csv": FIX / "charting_m_matches.csv", "charting-m-points-2020s.csv": FIX / "charting_m_points.csv"}
    rows = list(charting.iter_points(paths["charting-m-points-2020s.csv"]))
    agree = 0
    for r in rows:
        rec = charting.parse_point(r["first"], r["second"], int(r["svr"]), None, r["pts"], None)
        agree += rec["winner"] == int(r["winner"])
    assert len(rows) == 119 and agree / len(rows) >= 0.98
    table, info = charting.build_style("atp", paths)
    assert info["points"] == 119 and info["matches_with_points"] == 1
    sin = table["Jannik Sinner"]
    assert sin["points"] == 119 and sin["matches"] == 1
    assert 0 < sin["serve"]["first_in"] < 1 and abs(sum(sin["rally"]["dist"].values()) - 1) < 0.01
    d = sin["serve"]["direction"]["first_deuce"]
    assert abs((d["wide"] or 0) + (d["body"] or 0) + (d["t"] or 0) - 1) < 0.01
    ruud = table["Casper Ruud"]
    assert sin["sv_pts"] == ruud["rt_pts"] and sin["points_won"] + ruud["points_won"] == pytest.approx(1, abs=0.01)
    assert charting.LICENSE["name"] == "CC BY-NC-SA 4.0" and "Match Charting Project" in charting.LICENSE["attribution"]


def test_espn_group_stage_as_first_qualifying_round():
    lab = canon.espn_round_labels(["Group Stage", "Qualifying 2nd Round", "Qualifying Final", "Round 1", "Round 2",
                                   "Round 3", "Round 4", "Quarterfinal", "Semifinal", "Final"])
    assert lab["Group Stage"] == "Q1" and lab["Qualifying Final"] == "Q3" and lab["Round 1"] == "R128"


def test_identity_glitch_merges_on_shared_player_and_score(tmp_data):
    """ESPN names the wrong opponent: same event, round, winner and games -> one match, tennis-data's names."""
    s = store.new_store("atp", 2016)
    meta = {"name": "Ecuador Open", "city": "Quito", "start": "2016-02-01", "end": "2016-02-07", "level": "250",
            "surface": "clay", "indoor": False, "tid_hint": "quito"}
    eid = store.event_for(s, meta, "espn")
    base = {"tour": "atp", "year": 2016, "event": meta, "round": "R32", "date": "2016-02-02", "best_of": 3,
            "winner": "a", "status": "done", "odds": None, "stats": None, "live": None, "duration_min": None}
    e = dict(base, src="espn", a={}, b={}, sets=[[6, 4, None, None], [7, 6, 8, 6]])
    t = dict(base, src="td", a={"rank": 50}, b={"rank": 80}, sets=[[6, 4, None, None], [7, 6, None, None]],
             odds={"ps": [1.5, 2.6]})
    store.merge_record(s, e, eid, "ram", "federico-zeballos")
    store.merge_record(s, t, eid, "ram", "horacio-zeballos")
    (m,) = s["matches"].values()
    assert {m["p1"], m["p2"]} == {"ram", "horacio-zeballos"} and m["sets"][1] == [7, 6, 8, 6]
    assert m["odds"]["ps"] == [1.5, 2.6] and sorted(m["sources"]) == ["espn", "td"]
    assert any(c["kind"] == "identity" for c in s["meta"]["conflicts"])


def test_registry_surname_order_and_alternate_ids():
    reg = canon.Registry("wta")
    tm = reg.add("espn", first="Tatjana", last="Maria", espn="2346")
    reg.add("espn", first="Maria", last="Timofeeva", espn="10501")
    assert reg.resolve_abbrev("td", "Maria T.") == tm                     # usual order beats Chinese order
    v = reg.add("wta", first="Venus", last="Williams", wta="18251", country="USA")
    v2 = reg.add("wta", first="Venus", last="Williams", wta="230220", country="USA")
    assert v2 == v and reg.players[v]["wta_alt"] == ["230220"] and reg.by_wta["230220"] == v
    a = reg.resolve_abbrev("td", "Nobody X.")
    assert reg.resolve_abbrev("td", "Nobody X.") == a                     # one x: player per raw name


def test_registry_merge_keeps_espn_id():
    reg = canon.Registry("wta")
    e = reg.add("espn", first="Catherine", last="McNally", espn="3223")
    w = reg.add("wta", first="Caty", last="McNally", wta="320301")
    assert e != w
    keep = reg.merge(w, e)
    assert keep == "3223" and reg.canonical(w) == "3223" and reg.players["3223"]["wta"] == "320301"
    assert reg.resolve_abbrev("td", "McNally C.", field={"3223"}, has_field=True) == "3223"


def test_wta_slam_match_ids_use_round_id():
    assert wta.round_from_match_id("LS67664708") == (None, None)
    meta = {"name": "Australian Open", "city": "Melbourne", "level": "slam", "draw_size": 128, "start": "2026-01-18"}
    m = {"DrawMatchType": "S", "DrawLevelType": "M", "MatchID": "LS67664708", "RoundID": "1", "MatchState": "F",
         "Winner": "2", "PlayerIDA": "1", "PlayerIDB": "2", "PlayerNameFirstA": "A", "PlayerNameLastA": "One",
         "PlayerNameFirstB": "B", "PlayerNameLastB": "Two", "ScoreSet1A": "6", "ScoreSet1B": "1", "ScoreSet2A": "6",
         "ScoreSet2B": "2", "EventYear": 2026}
    assert wta.parse_match(m, meta)["round"] == "R128"
    q = dict(m, DrawLevelType="Q", RoundID="")
    assert wta.parse_match(q, meta) is None                       # Slam qualifying rows carry no round


def test_fill_from_history(tmp_data):
    old = store.new_store("atp", 2025)
    old["events"]["tokyo-2025"] = {"tid": "tokyo", "surface": "hard", "indoor": False, "level": "500", "start": "2025-09-24"}
    store.save(old)
    s = store.new_store("atp", 2026)
    s["events"]["tokyo-2026"] = {"tid": "tokyo", "surface": None, "indoor": None, "level": "250", "start": "2026-09-27"}
    assert store.fill_from_history(s) == 1
    assert s["events"]["tokyo-2026"]["surface"] == "hard" and s["events"]["tokyo-2026"]["level"] == "500"
