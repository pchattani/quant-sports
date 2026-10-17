"""Builder A: data layer, canon and tiebreakers for The Quant Gridiron (no network)."""
from __future__ import annotations

import random

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from oddsmarkets.nfl import canon, tiebreak
from oddsmarkets.nfl import store as st
from oddsmarkets.nfl.sources import espn, nflverse

from .conftest import fixture_path, load_fixture_json


# ── nflverse parsing ────────────────────────────────────────────────────────

def test_pbp_slice_and_derived_plays(gridiron_roots):
    pbp = pd.read_parquet(fixture_path("pbp_2025_slice.parquet"))
    ftn = pd.read_parquet(fixture_path("ftn_2025_slice.parquet"))
    part = pd.read_parquet(fixture_path("participation_2025_slice.parquet"))
    assert len(pbp) == 300
    assert (pbp["down"] == 4).sum() >= 100
    assert pbp["two_point_attempt"].sum() >= 2
    two = pbp[pbp["two_point_attempt"] == 1]
    assert two["two_point_conv_result"].isin(["success", "failure"]).all()
    info = nflverse.build_plays(2025, pbp=pbp, ftn=ftn, part=part)
    assert info["plays"] == 300
    out = pd.read_parquet(st.plays_path(2025))
    assert len(out) == 300                                  # left joins never duplicate plays
    jt = out[out["game_id"] == "2025_13_JAX_TEN"]
    # FTN charts scrimmage plays; participation covers nearly every play of the game
    assert info["ftn_matched"] >= 100 and jt["ftn_is_play_action"].notna().sum() == info["ftn_matched"]
    assert info["part_matched"] >= 100
    assert out.loc[out["game_id"] != "2025_13_JAX_TEN", "ftn_is_play_action"].isna().all()
    assert {"part_offense_players", "part_defense_coverage_type", "ftn_n_blitzers", "epa", "wp", "cpoe"} <= set(out.columns)
    assert nflverse.load_plays(2025, ["game_id", "nope"]).columns.tolist() == ["game_id"]


def test_ngs_slice_columns():
    ngs = pd.read_parquet(fixture_path("ngs_passing_slice.parquet"))
    assert set(nflverse.REQUIRED["nextgen_stats"]) <= set(ngs.columns)
    assert {"avg_time_to_throw", "completion_percentage_above_expectation"} <= set(ngs.columns)
    assert (ngs["season"] == 2025).all()


def test_compact_game_lines_and_kickoff(schedules):
    rows = schedules.to_dict("records")
    games = [nflverse.compact_game(r) for r in rows]
    by = {g["game_id"]: g for g in games}
    for r, g in zip(rows, games):
        if pd.notna(r["spread_line"]):
            assert g["lines"]["spread_home"] == -r["spread_line"]      # nflverse: positive = home favoured
            if pd.notna(r["home_moneyline"]) and abs(r["spread_line"]) >= 3:
                assert (r["home_moneyline"] < r["away_moneyline"]) == (g["lines"]["spread_home"] < 0)
        assert g["status"] == ("final" if pd.notna(r["home_score"]) else "scheduled")
        assert g["gtype"] in canon.GTYPES
    g = by["2026_04_PIT_CLE"]
    assert g["kickoff"] == "2026-10-02T00:15:00Z"            # Thursday 20:15 ET
    assert g["espn_id"] == "401872964" and g["stadium"] == "CLE00" and g["lat"] == pytest.approx(41.5061)
    assert sum(1 for x in games if x["season"] == 2022 and x["gtype"] == "REG") == 271     # BUF-CIN never completed
    assert all(x["neutral"] in (True, False) for x in games)


def test_schema_check(tmp_path):
    p = tmp_path / "x.parquet"
    pq.write_table(pa.table({"game_id": ["a"], "play_id": [1]}), p)
    assert "epa" in nflverse.check_schema("pbp", p)
    assert nflverse.check_schema("pbp_participation", tmp_path / "x.parquet") == ["nflverse_game_id"]


# ── the timestamp gate (mocked client) ──────────────────────────────────────

class FakeClient:
    def __init__(self):
        self.ts = "2026-10-01 12:00:00 EDT"
        self.etag = '"v1"'
        self.columns = {"game_id": ["g"], "season": [2026], "game_type": ["REG"], "week": [1], "gameday": ["2026-09-10"],
                        "home_team": ["SEA"], "away_team": ["NE"], "home_score": [13.0], "away_score": [10.0],
                        "spread_line": [3.0], "total_line": [44.5], "espn": ["1"], "stadium_id": ["SEA00"],
                        "roof": ["outdoors"], "surface": ["grass"]}
        self.calls = {"text": 0, "head": 0, "download": 0}

    def get_text(self, url, params=None):
        self.calls["text"] += 1
        return self.ts

    def head(self, url):
        self.calls["head"] += 1
        return {"etag": self.etag, "content-length": "100", "last-modified": "x"}

    def download(self, url, dest):
        self.calls["download"] += 1
        pq.write_table(pa.table(self.columns), dest)
        return {"etag": self.etag, "bytes": dest.stat().st_size}


def test_timestamp_gate(gridiron_roots):
    nflverse._TIMESTAMPS.clear()
    c = FakeClient()
    p = nflverse.fetch("schedules", c=c)
    assert p.exists() and c.calls == {"text": 1, "head": 1, "download": 1}
    # same release timestamp: no HEAD, no download (timestamp.txt read once per process)
    assert nflverse.fetch("schedules", c=c) == p
    assert c.calls == {"text": 1, "head": 1, "download": 1}
    # timestamp moved, file unchanged (same ETag): a HEAD only
    nflverse._TIMESTAMPS.clear()
    c.ts = "2026-10-01 13:00:00 EDT"
    nflverse.fetch("schedules", c=c)
    assert c.calls == {"text": 2, "head": 2, "download": 1}
    assert nflverse.load_manifest("schedules")["files"]["games.parquet"]["timestamp"] == c.ts
    # timestamp and ETag moved: download
    nflverse._TIMESTAMPS.clear()
    c.ts, c.etag = "2026-10-01 14:00:00 EDT", '"v2"'
    nflverse.fetch("schedules", c=c)
    assert c.calls["download"] == 2
    # a new version missing required columns is discarded; the good copy stays
    nflverse._TIMESTAMPS.clear()
    c.ts, c.etag = "2026-10-01 15:00:00 EDT", '"v3"'
    good = dict(c.columns)
    c.columns = {"game_id": ["g"]}
    assert nflverse.fetch("schedules", c=c) == p
    assert set(good) <= set(pq.read_schema(p).names)
    assert nflverse.load_manifest("schedules")["files"]["games.parquet"]["etag"] == '"v2"'
    nflverse._TIMESTAMPS.clear()


def test_release_file_names():
    assert nflverse.filename("pbp", 2025) == "play_by_play_2025.parquet"
    assert nflverse.files_for("nextgen_stats", None) == ["ngs_passing.parquet", "ngs_rushing.parquet", "ngs_receiving.parquet"]
    assert nflverse.files_for("espn_data", None) == ["qbr_season_level.parquet", "qbr_week_level.parquet"]
    assert nflverse.seasons("pbp_participation", 2026)[-1] == 2025
    assert nflverse.seasons("ftn_charting", 2026) == [2022, 2023, 2024, 2025, 2026]


# ── stores ──────────────────────────────────────────────────────────────────

def test_store_owned_merge(gridiron_roots, schedules):
    s = st.load(2026)
    for r in schedules[schedules["season"] == 2026].to_dict("records"):
        st.merge_game(s, nflverse.compact_game(r))
    st.save_owned(s, ["schedule"])
    stale = st.load(2026)                                       # the ESPN process loaded before the rebuild below
    gid = "2026_04_PIT_CLE"
    raw = load_fixture_json("espn_odds_401872947.json")
    ln = espn.compact_lines(raw)
    stale["games"][gid]["lines"] = {**(stale["games"][gid]["lines"] or {}), **{k: ln[k] for k in st.LINES_ESPN}}
    stale["meta"]["espn_odds"][gid] = {"at": st.now()}
    # meanwhile a schedules rebuild changes the nflverse line
    s2 = st.load(2026)
    s2["games"][gid]["lines"]["spread_home"] = 3.0
    s2["games"][gid]["referee"] = "Someone"
    st.save_owned(s2, ["schedule"])
    st.save_owned(stale, ["espn"])
    d = st.load(2026)["games"][gid]
    assert d["lines"]["spread_home"] == 3.0 and d["referee"] == "Someone"          # schedule half kept
    assert d["lines"]["open"]["spread_home"] == -8.5 and d["lines"]["books"]        # ESPN half kept
    # a later schedule rebuild keeps ESPN keys
    s3 = st.load(2026)
    for r in schedules[schedules["season"] == 2026].to_dict("records"):
        st.merge_game(s3, nflverse.compact_game(r))
    st.save_owned(s3, ["schedule"])
    d = st.load(2026)["games"][gid]
    assert d["lines"]["open"]["spread_home"] == -8.5 and d["lines"]["src"] == "nflverse"
    assert st.load(2026)["meta"]["espn_odds"][gid]
    assert not list(st.season_dir(2026).glob("*.lock"))


def test_merge_game_keeps_live(gridiron_roots):
    s = st.new_store(2026)
    g = {"game_id": "x", "week": 4, "status": "scheduled", "hs": None, "as": None, "lines": None}
    st.merge_game(s, g)
    s["games"]["x"].update(status="live", hs=7, live={"period": 2})
    st.merge_game(s, dict(g))
    assert s["games"]["x"]["status"] == "live" and s["games"]["x"]["hs"] == 7 and s["games"]["x"]["live"]
    st.merge_game(s, {**g, "status": "final", "hs": 21, "as": 17})
    assert s["games"]["x"]["status"] == "final" and s["games"]["x"]["hs"] == 21
    assert st.complete_through({"games": {"a": {"week": 1, "status": "final"}, "b": {"week": 2, "status": "scheduled"}}}) == 1


# ── ESPN ────────────────────────────────────────────────────────────────────

def test_espn_game_id_mapping(schedules):
    sb = load_fixture_json("espn_scoreboard_2026_w4.json")
    games = {g["game_id"]: g for g in (nflverse.compact_game(r) for r in schedules.to_dict("records"))}
    xw = {g["espn_id"]: gid for gid, g in games.items() if g.get("espn_id")}
    n = 0
    for ev in sb["events"]:
        by_xw = espn.map_game_id(ev, xw)
        by_week = espn.map_game_id(ev, None, games)
        assert by_xw == by_week and by_xw in games, ev["shortName"]
        assert games[by_xw]["espn_id"] == ev["id"]
        n += 1
    assert n == len(sb["events"]) >= 14
    ev = sb["events"][0]
    ref = espn.event_ref(ev)
    assert ref["home"] == "CLE" and ref["away"] == "PIT" and espn.map_game_id(ev) == "2026_04_PIT_CLE"
    # nearest-kickoff fallback when ESPN's week is unknown
    ref2 = {**ref, "week": None}
    assert espn.map_game_id(ref2, None, games) == "2026_04_PIT_CLE"
    # ESPN abbreviations and ids
    assert canon.abbr_from_espn("LAR", 2026) == "LA" and canon.abbr_from_espn("14", 2015) == "STL"
    assert canon.abbr_from_espn("WSH", 2026) == "WAS" and canon.abbr_from_espn("24", 2016) == "SD"
    # playoff weeks: ESPN seasontype 3 week 5 (Super Bowl) -> nflverse week reg_weeks + 4
    sbrow = schedules[(schedules["season"] == 2025) & (schedules["game_type"] == "SB")].iloc[0]
    sbref = {"id": "1", "season": 2025, "seasontype": 3, "week": 5, "home": sbrow["home_team"], "away": sbrow["away_team"],
             "start": None}
    assert espn.map_game_id(sbref) == sbrow["game_id"] and sbrow["week"] == 22


def test_espn_lines_by_book():
    l16 = espn.compact_lines(load_fixture_json("espn_odds_400874483.json"))
    assert l16["open"]["spread_home"] == 2.5 and l16["open"]["total"] == 43.0       # opener (initialSpread)
    assert l16["spread_home"] > 0 and l16["ml_home"] > 0                             # home (SF) underdog
    assert l16["consensus"]["n_books"] >= 8
    l19 = espn.compact_lines(load_fixture_json("espn_odds_401127927.json"))
    sus = {b["name"] for b in l19["books"] if b.get("suspect")}
    assert {"DraftKings", "Caesars Sportsbook"} <= sus                               # in-play captures
    assert l19["espn_src"] not in sus and l19["close"]["total"] == 48.5
    assert all("live" not in (b["name"] or "").lower() for b in l19["books"])
    l26 = espn.compact_lines(load_fixture_json("espn_odds_401872947.json"))
    assert l26["espn_src"] == "DraftKings"
    assert l26["open"] == {"spread_home": -8.5, "total": 47.5, "ml_home": -375, "ml_away": 295, "spread_price": [-110, -110],
                           "total_price": [-110, -110], "src": "DraftKings"}
    assert l26["close"]["spread_home"] == -7.0 and l26["close"]["ml_home"] == -310 and l26["close"]["total"] == 47.5


def test_espn_summary_compact():
    raw = load_fixture_json("espn_summary_401872947.json")
    rec = espn.compact_summary(raw, "2026_03_NYG_LA")
    assert rec["status"] == "final" and rec["home"] == "LA" and rec["away"] == "NYG"
    assert (rec["home_score"], rec["away_score"]) == (28, 6)
    assert len(rec["drives"]) == 21 and rec["drives"][0]["team"] == "NYG" and rec["drives"][0]["result"] == "PUNT"
    assert all(len(p) == 12 for p in rec["plays"]) and len(rec["plays"]) > 150
    p = rec["plays"][1]
    assert p[3] == "NYG" and p[4] == 1 and p[5] == 10 and p[6] == 70 and 0 <= p[11] <= 1
    assert sum(1 for p in rec["plays"] if p[11] is not None) > 150
    assert rec["odds"]["open"]["spread_home"] == -8.5 and rec["odds"]["close"]["ml_home"] == -310
    assert rec["wp_home"] == 1.0
    assert set(rec["injuries"]) == {"LA", "NYG"}
    assert rec["plays"][-1][9:11] == [28, 6]


# ── canon ───────────────────────────────────────────────────────────────────

def test_relocations_and_alignment():
    assert canon.abbr("LA", 2015) == "STL" and canon.abbr("STL", 2016) == "LA"
    assert canon.abbr("LAC", 2016) == "SD" and canon.abbr("SD", 2017) == "LAC"
    assert canon.abbr("LV", 2019) == "OAK" and canon.abbr("OAK", 2020) == "LV"
    assert canon.franchise("STL") == canon.franchise("LAR") == "LA"
    assert canon.team_name("WAS", 2021) == "Washington Football Team" and canon.team_name("WAS", 2022) == "Washington Commanders"
    t01, t02 = canon.teams(2001), canon.teams(2002)
    assert len(t01) == 31 and "HOU" not in t01 and t01["SEA"]["div"] == "AFC West" and t01["TB"]["div"] == "NFC Central"
    assert len(t02) == 32 and t02["SEA"]["div"] == "NFC West" and t02["HOU"]["div"] == "AFC South"
    assert canon.teams(2019)["OAK"]["div"] == "AFC West" and "LV" in canon.teams(2020)
    assert all(len(v) == 4 for v in canon.alignment(2026).values())
    assert sorted(canon.ESPN_TEAM_ID.values()) == sorted(canon.FRANCHISES)


def test_formats():
    f99, f19, f20, f21 = (canon.formats(s) for s in (1999, 2019, 2020, 2021))
    assert (f99["playoff_teams"], f99["wild_cards_per_conf"], f99["divisions_per_conf"]) == (12, 3, 3)
    assert (f19["playoff_teams"], f19["byes_per_conf"], f19["games"]) == (12, 2, 16)
    assert (f20["playoff_teams"], f20["byes_per_conf"], f20["games"]) == (14, 1, 16)
    assert (f21["games"], f21["reg_weeks"], f21["post_weeks"]["SB"]) == (17, 18, 22)
    assert canon.gtype_of_week(2020, 18) == "WC" and canon.gtype_of_week(2021, 18) == "REG"


def test_stadiums(schedules):
    for sid, rec in canon.STADIUMS.items():
        s = canon.stadium(sid)
        assert -60 < s["lat"] < 65 and -180 <= s["lon"] <= 180 and 0 <= s["altitude_m"] < 2500
        assert s["roof"] in ("outdoors", "dome", "retractable")
    assert canon.stadium("DEN00")["altitude_m"] == 1609 and canon.stadium("MEX00")["altitude_m"] == 2240
    for r in schedules.to_dict("records"):
        assert r["stadium_id"] in canon.STADIUMS, r["stadium_id"]
    # every club's regular home ground (non-neutral home games) lies within 80 km of its city
    home = schedules[schedules["location"] == "Home"].groupby(["season", "home_team"])["stadium_id"].agg(lambda s: s.mode()[0])
    for (season, team), sid in home.items():
        city = canon.CITY[team]
        s = canon.stadium(sid)
        assert canon.haversine_km(city[1], city[2], s["lat"], s["lon"]) < 80, (season, team, sid)
    assert canon.haversine_km(40.8135, -74.0745, 42.0909, -71.2643) == pytest.approx(276, abs=8)   # MetLife-Gillette


# ── tiebreakers: hand-worked ────────────────────────────────────────────────

def _teams(spec: dict[str, str]) -> dict:
    return {t: {"div": d, "conf": d.split()[0]} for t, d in spec.items()}


def _g(*rows):
    """rows of (winner, loser) or (home, away, hs, as)."""
    out = []
    for r in rows:
        if len(r) == 2:
            out.append({"home": r[0], "away": r[1], "hs": 20, "as": 10})
        else:
            out.append({"home": r[0], "away": r[1], "hs": r[2], "as": r[3]})
    return out


def test_two_club_division_head_to_head():
    teams = _teams({"A": "AFC X", "B": "AFC X", "E": "AFC Y", "F": "AFC Y"})
    games = _g(("A", "B"), ("E", "A"), ("B", "E"), ("F", "B"), ("A", "F"))      # A 2-1, B 1-2? -> equalise below
    games += _g(("B", "F"))                                                        # B 2-2? A 2-1: add A loss
    games += _g(("E", "A"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("A") == (2, 2, 0) and tb.record("B") == (2, 2, 0)
    assert tb.order(["A", "B"], "div") == ["A", "B"]
    assert tb.trace[0][0] == "h2h"


def test_two_club_division_split_goes_to_division_record():
    teams = _teams({"A": "AFC X", "B": "AFC X", "C": "AFC X", "N": "NFC Z"})
    games = _g(("A", "B"), ("B", "A"), ("A", "C"), ("C", "B"), ("N", "A"), ("B", "N"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("A") == tb.record("B") == (2, 2, 0)
    assert tb.order(["A", "B"], "div") == ["A", "B"]                              # A 2-1 in division, B 1-2
    assert [t[0] for t in tb.trace] == ["div_pct"]


def test_three_club_division_head_to_head_then_two_club():
    teams = _teams({"A": "AFC X", "B": "AFC X", "C": "AFC X", "D": "AFC X",
                    "E1": "AFC Y", "E2": "AFC Y", "E3": "AFC Y"})
    games = _g(("A", "B"), ("A", "B"), ("A", "C"), ("C", "A"), ("B", "C"), ("B", "C"),
               ("A", "E1"), ("E2", "A"), ("E3", "A"),
               ("B", "E1"), ("B", "E2"), ("E3", "B"),
               ("C", "E1"), ("C", "E2"), ("C", "E3"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("A") == tb.record("B") == tb.record("C") == (4, 3, 0)
    # head-to-head among the three: A 3-1, B 2-2, C 1-3 -> A; then B v C restart at two-club step 1: B 2-0
    assert tb.order(["A", "B", "C"], "div") == ["A", "B", "C"]
    assert tb.trace[0] == ("h2h", ("A", "B", "C"), "A")
    assert tb.trace[1] == ("h2h", ("B", "C"), "B")


def test_three_club_division_reverts_to_two_club_format():
    """C is eliminated on division record; A and B then restart at step 1 of the two-club format (A swept B),
    although B has the better record in common games and in the conference."""
    teams = _teams({"A": "AFC X", "B": "AFC X", "C": "AFC X", "D": "AFC X",
                    "E1": "AFC Y", "E2": "AFC Y", "E3": "AFC Y", "N1": "NFC Z", "N2": "NFC Z", "N3": "NFC Z"})
    games = _g(("A", "B"), ("A", "B"), ("B", "C"), ("B", "C"), ("C", "A"), ("C", "A"),
               ("A", "D"), ("D", "A"), ("B", "D"), ("D", "B"), ("D", "C"), ("D", "C"),
               ("A", "N1"), ("A", "N2"), ("A", "N3"), ("E1", "A"), ("E2", "A"), ("E3", "A"),
               ("B", "E1"), ("B", "E2"), ("B", "E3"), ("N1", "B"), ("N2", "B"), ("N3", "B"),
               ("C", "E1"), ("C", "E2"), ("C", "N1"), ("C", "N2"), ("E3", "C"), ("N3", "C"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("A") == tb.record("B") == tb.record("C") == (6, 6, 0)
    assert tb._metric("common_pct", ["A", "B"])["B"] > tb._metric("common_pct", ["A", "B"])["A"]
    assert tb._metric("conf_pct", ["A", "B"])["B"] > tb._metric("conf_pct", ["A", "B"])["A"]
    assert tb.order(["A", "B", "C"], "div") == ["A", "B", "C"]
    assert tb.trace[0] == ("div_pct:out", ("A", "B", "C"), ("A", "B"))
    assert tb.trace[1] == ("h2h", ("A", "B"), "A")


def test_four_club_division_restarts_three_club_format():
    """D is eliminated on common games; A, B, C restart at Step 1 of the three-club format (head-to-head among
    the three: A 3-1). Continuing to Step 4 instead would pick B (best conference record). A advances alone, so
    B, C and D (still tied) start again: head-to-head among the three gives C (3-1), then B over D."""
    teams = _teams({"A": "AFC X", "B": "AFC X", "C": "AFC X", "D": "AFC X", "E1": "AFC Y", "E2": "AFC Y",
                    "N1": "NFC V", "N2": "NFC V", "Z1": "NFC V", "Z2": "NFC V"})
    games = _g(("A", "B"), ("B", "A"), ("A", "C"), ("A", "C"), ("B", "C"), ("C", "B"),
               ("D", "A"), ("D", "A"), ("B", "D"), ("D", "B"), ("C", "D"), ("C", "D"),
               ("E1", "A"), ("E2", "A"), ("A", "N1"), ("A", "N2"),
               ("B", "E1"), ("B", "E2"), ("N1", "B"), ("N2", "B"),
               ("C", "E1"), ("E2", "C"), ("C", "N1"), ("N2", "C"),
               ("D", "E1"), ("E2", "D"), ("N1", "D"), ("N2", "D"), ("D", "Z1"), ("D", "Z2"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("A") == tb.record("B") == tb.record("C") == (5, 5, 0) and tb.record("D") == (6, 6, 0)
    conf = tb._metric("conf_pct", ["A", "B", "C"])
    assert conf["B"] > conf["C"] > conf["A"]
    assert tb.order(["A", "B", "C", "D"], "div") == ["A", "C", "B", "D"]
    assert tb.trace[0] == ("common_pct:out", ("A", "B", "C", "D"), ("A", "B", "C"))
    assert tb.trace[1] == ("h2h", ("A", "B", "C"), "A")
    assert tb.trace[2] == ("h2h", ("B", "C", "D"), "C")


def test_four_club_wildcard_restarts_at_step_two():
    """S is eliminated on conference record; P, Q, R restart at Step 2 (head-to-head sweep: P beat Q and R).
    Continuing to Step 4 instead would pick R (best record in common games)."""
    teams = _teams({"P": "AFC W", "Q": "AFC X", "R": "AFC Y", "S": "AFC Z",
                    **{f"E{i}": "AFC W" for i in range(1, 5)}, **{f"N{i}": "NFC V" for i in range(1, 7)}})
    games = _g(("P", "Q"), ("P", "R"), ("Q", "R"),
               ("P", "E1"), ("E2", "P"), ("E3", "P"), ("E4", "P"), ("P", "N1"), ("N2", "P"),
               ("Q", "E1"), ("Q", "E2"), ("E3", "Q"), ("E4", "Q"), ("Q", "N1"), ("N2", "Q"),
               ("R", "E1"), ("R", "E2"), ("R", "E3"), ("E4", "R"), ("R", "N1"), ("N2", "R"),
               ("S", "E1"), ("E2", "S"), ("E3", "S"), ("E4", "S"), ("S", "N3"), ("S", "N4"), ("S", "N5"), ("N6", "S"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert all(tb.record(t) == (4, 4, 0) for t in "PQRS")
    common = tb._metric("common_pct4", ["P", "Q", "R"])
    assert common["R"] > common["Q"] > common["P"]
    tb.division_order("AFC W")                      # the division reduction ranks P's division first
    tb.trace.clear()
    assert tb.order(["P", "Q", "R", "S"], "wc") == ["P", "Q", "R", "S"]
    assert tb.trace == [("conf_pct:out", ("P", "Q", "R", "S"), ("P", "Q", "R")),
                        ("h2h_sweep", ("P", "Q", "R"), "P"),
                        ("conf_pct:out", ("Q", "R", "S"), ("Q", "R")),
                        ("h2h_if", ("Q", "R"), "Q"),
                        ("conf_pct", ("R", "S"), "R")]


def test_wildcard_sweep_and_lost_to_each():
    teams = _teams({"P": "AFC X", "Q": "AFC Y", "R": "AFC Z"})
    tb = tiebreak.Table(_g(("P", "Q"), ("P", "R"), ("Q", "R"), ("Q", "P"), ("R", "P"), ("R", "Q")), 2026, teams=teams)
    # every club 2-2 and nobody swept: falls through to conference record (all equal) ... down to the coin
    assert sorted(tb.order(["P", "Q", "R"], "wc")) == ["P", "Q", "R"]
    tb = tiebreak.Table(_g(("P", "Q"), ("P", "R"), ("Q", "R")), 2026, teams=teams)
    tb2 = tiebreak.Table(_g(("P", "Q"), ("P", "R"), ("Q", "R"), ("Q", "P"), ("R", "P"), ("R", "Q")), 2026, teams=teams)
    assert tb2._sweep(["P", "Q", "R"]) is None
    assert tb._sweep(["P", "Q", "R"]) == ("won", "P")
    teams = _teams({"P": "AFC X", "Q": "AFC Y", "R": "AFC Z", "E1": "AFC W", "N1": "NFC V", "N2": "NFC V"})
    games = _g(("P", "R"), ("P", "E1"), ("N1", "P"), ("N2", "P"),
               ("Q", "R"), ("E1", "Q"), ("Q", "N1"), ("N2", "Q"),
               ("R", "N1"), ("R", "N2"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("P") == tb.record("Q") == tb.record("R") == (2, 2, 0)
    assert tb.order(["P", "Q", "R"], "wc") == ["P", "Q", "R"]
    assert tb.trace[0] == ("h2h_sweep:out", ("P", "Q", "R"), "R")                  # R lost to each
    assert tb.trace[1] == ("conf_pct", ("P", "Q"), "P")                            # P v Q never met: step 2
    assert tb.trace[2] == ("h2h_if", ("Q", "R"), "Q")


def test_wildcard_division_reduction_and_original_seeding():
    teams = _teams({"A1": "AFC X", "A2": "AFC X", "B": "AFC Y", "N1": "NFC V", "N2": "NFC V", "N3": "NFC V", "N4": "NFC V"})
    games = _g(("A2", "A1"), ("A2", "A1"), ("A1", "B"), ("B", "A2"),
               ("A1", "N1"), ("A1", "N2"), ("N3", "A1"),
               ("A2", "N1"), ("N2", "A2"), ("N3", "A2"),
               ("B", "N1"), ("B", "N2"), ("N3", "B"), ("N4", "B"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("A1") == tb.record("A2") == tb.record("B") == (3, 3, 0)
    assert tb.division_order("AFC X") == ["A2", "A1"]
    # step 1 removes A1 (below A2 in its division); B beat A2 head-to-head; then A2 over A1 by the division procedure
    assert tb.order(["A1", "A2", "B"], "wc") == ["B", "A2", "A1"]
    keys = [t[0] for t in tb.trace]
    assert ("div_reduce", ("A1", "A2", "B"), ("A2", "B")) in tb.trace and keys[-1] == "h2h"


def test_common_games_minimum_four_then_strength_of_victory():
    teams = _teams({"P": "AFC X", "Q": "AFC Y", "T1": "AFC W", "T2": "AFC W", "T3": "AFC W", "T4": "AFC W",
                    **{f"{x}{i}": "NFC V" for x in "EMN" for i in (1, 2, 3)}, "Z": "NFC V"})
    games = _g(("P", "T1"), ("T2", "P"), ("Q", "T3"), ("T4", "Q"),
               ("P", "E1"), ("P", "E2"), ("P", "E3"), ("E1", "Q"), ("E2", "Q"), ("E3", "Q"),
               ("N1", "P"), ("N2", "P"), ("N3", "P"), ("Q", "M1"), ("Q", "M2"), ("Q", "M3"),
               ("M1", "Z"), ("M1", "Z"), ("M2", "Z"), ("M2", "Z"), ("M3", "Z"), ("M3", "Z"))
    tb = tiebreak.Table(games, 2026, teams=teams)
    assert tb.record("P") == tb.record("Q") == (4, 4, 0)
    assert tb._metric("common_pct4", ["P", "Q"]) is None                            # 3 common games each
    assert tb._metric("common_pct", ["P", "Q"])["P"] == 1.0                         # would have decided it
    assert tb.order(["P", "Q"], "wc") == ["Q", "P"]
    assert tb.trace == [("sov", ("P", "Q"), "Q")]


def test_tie_games_and_coin_toss():
    teams = _teams({"A": "AFC X", "B": "AFC X"})
    tb = tiebreak.Table([{"home": "A", "away": "B", "hs": 20, "as": 20}], 2026, teams=teams)
    assert tb.record("A") == (0, 0, 1) and tb.pct("A") == 0.5
    seen = set()
    for seed in range(20):
        t = tiebreak.Table([{"home": "A", "away": "B", "hs": 20, "as": 20}], 2026, teams=teams, rng=random.Random(seed))
        o = t.order(["A", "B"], "div")
        seen.add(o[0])
        assert t.trace[-1][0] == "coin"
        assert tiebreak.Table([{"home": "A", "away": "B", "hs": 20, "as": 20}], 2026, teams=teams,
                              rng=random.Random(seed)).order(["A", "B"], "div") == o
    assert seen == {"A", "B"}


def test_net_touchdowns_step():
    teams = _teams({"A": "AFC X", "B": "AFC X"})
    g = [{"home": "A", "away": "B", "hs": 20, "as": 20}]
    tb = tiebreak.Table(g, 2026, teams=teams, tds={"A": (2, 2), "B": (3, 1)})
    assert tb.order(["A", "B"], "div") == ["B", "A"] and tb.trace[-1][0] == "net_td"


def test_procedure_text_is_complete():
    assert [k for k, _ in canon.DIVISION_TWO][-1] == "coin" and len(canon.DIVISION_TWO) == 12
    assert len(canon.WILDCARD_TWO) == 11 and len(canon.WILDCARD_THREE) == 12
    assert canon.WILDCARD_THREE[0][0] == "div_reduce" and canon.WILDCARD_THREE[1][0] == "h2h_sweep"
    assert canon.TIEBREAK_SOURCE.startswith("https://www.nfl.com/")


# ── tiebreakers: real seasons ───────────────────────────────────────────────

@pytest.mark.parametrize("season", [2022, 2025])
def test_seeding_matches_the_actual_playoff_field(schedules, season):
    s = schedules[schedules["season"] == season]
    games = [nflverse.compact_game(r) for r in s.to_dict("records")]
    tb = tiebreak.Table(games, season)
    seeds = tb.seeds()
    post = s[s["game_type"] != "REG"]
    assert set(seeds["AFC"]["seeds"]) | set(seeds["NFC"]["seeds"]) == set(post["home_team"]) | set(post["away_team"])
    for r in s[s["game_type"] == "WC"].to_dict("records"):
        conf = canon.conference_of(r["home_team"], season)
        sd = seeds[conf]["seeds"]
        hi, lo = sd.index(r["home_team"]) + 1, sd.index(r["away_team"]) + 1
        assert hi < lo and hi + lo == 9                                             # 2v7, 3v6, 4v5
    assert all(b not in set(s[s["game_type"] == "WC"][["home_team", "away_team"]].values.ravel())
               for b in seeds["AFC"]["byes"] + seeds["NFC"]["byes"])
