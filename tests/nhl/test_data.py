"""Builder A (data layer) tests for The Quant Rink: parsing, situationCode decoding, on-ice reconstruction v
situationCode, coordinate normalisation, stints, tiebreakers, ESPN <-> gameId mapping, stores. No network."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from oddsmarkets.nhl import canon, derive
from oddsmarkets.nhl import store as st
from oddsmarkets.nhl.sources import edge, espn, moneypuck, nhl, stats

from .conftest import fixture_path, load_fixture


# ── seasons, situation codes ────────────────────────────────────────────────

def test_season_helpers():
    assert canon.norm_season(2026) == 20262027
    assert canon.norm_season("2026-27") == 20262027
    assert canon.norm_season(20092010) == 20092010
    assert canon.season_label(20262027) == "2026-27"
    assert canon.current_season(date(2026, 10, 1)) == 20262027
    assert canon.current_season(date(2027, 5, 1)) == 20262027
    assert canon.season_of_game(2026020009) == 20262027 and canon.game_type(2026020009) == 2
    assert nhl.series_of(2025030214) == {"round": 2, "series": 1, "game": 4}


def test_situation_code_decoding():
    assert canon.decode_situation("1551") == {"away_goalie": 1, "away_skaters": 5, "home_skaters": 5, "home_goalie": 1}
    d = canon.decode_situation("0651")                 # away net empty, 6 attackers
    assert (d["away_goalie"], d["away_skaters"], d["home_skaters"], d["home_goalie"]) == (0, 6, 5, 1)
    d = canon.decode_situation("1451")                 # home power play
    assert (d["away_skaters"], d["home_skaters"]) == (4, 5)
    assert canon.decode_situation(551)["home_goalie"] == 1 and canon.decode_situation(551)["away_goalie"] == 0
    assert canon.decode_situation(None) is None and canon.decode_situation("15a1") is None
    assert canon.strength_state(5, 4) == "PP" and canon.strength_state(4, 5) == "SH"
    assert canon.strength_state(5, 5) == "EV"
    assert canon.strength_state(5, 6, 1, 0) == "EN"        # opponent pulled its goalie
    assert canon.strength_state(6, 5, 0, 1) == "EV"        # extra attacker against 5: even skaters bar the goalie
    assert canon.strength_state(1, 0) == "PS"


# ── play-by-play parsing ────────────────────────────────────────────────────

def test_parse_modern_game(modern_game):
    ev, stn, chk = modern_game
    assert chk["events"] == len(ev) == 327
    assert set(ev["period"].unique()) == {1, 2, 3}
    goals = ev[ev["type"] == "goal"]
    assert len(goals) == 7 and set(goals["team"]) == {"PIT"}
    last = ev.iloc[-1]
    assert int(last["score_away"]) == 7 and int(last["score_home"]) == 0
    first_goal = goals.iloc[0]                           # score before the goal
    assert (int(first_goal["score_home"]), int(first_goal["score_away"])) == (0, 0)
    assert int(first_goal["sec"]) == 7 * 60 + 26         # 07:26 of the first
    assert first_goal["shooter"] == 8481582 and first_goal["assist1"] == 8471724
    # a blocked shot belongs to the shooting team (Malkin, PIT), the blocker is player2
    blk = ev[(ev["type"] == "blocked-shot") & (ev["shooter"] == 8471215)].iloc[0]
    assert blk["team"] == "PIT" and blk["player2"] == 8481546
    pen = ev[ev["type"] == "penalty"].iloc[0]
    assert pen["pen_type"] == "MIN" and pen["pen_min"] == 2 and pen["team"] == "PHI"
    assert ev["sec"].max() == 3600


def test_parse_2010_game(old_game):
    ev, stn, chk = old_game
    assert chk["events"] == len(ev) == 254
    assert chk["side_checked"] == 0                      # homeTeamDefendingSide not published in 2010-11
    assert chk["shots_xy"] == chk["shots"] > 0
    goals = ev[ev["type"] == "goal"]
    assert (goals["team"] == "BUF").sum() == 6 and (goals["team"] == "NJD").sum() == 1


# ── coordinate normalisation ────────────────────────────────────────────────

def test_coordinates_normalised_to_attack_plus_x(modern_game, old_game):
    for ev, _, chk in (modern_game, old_game):
        sh = ev[ev["type"].isin(derive.UNBLOCKED)]
        assert (sh["zone"] == sh["zone_raw"]).mean() == 1.0      # agrees with the NHL's own zone codes
        assert chk["zone_agree"] == chk["zone_checked"] > 50
        goals = ev[ev["type"] == "goal"]
        assert (goals["x"].astype(float) > 25).all()             # every goal scored in the attacking zone
        # normalisation is a 180-degree rotation: |x|, |y| unchanged
        ok = sh["x_raw"].notna()
        assert (sh.loc[ok, "x"].astype(float).abs() == sh.loc[ok, "x_raw"].astype(float).abs()).all()
        assert (sh.loc[ok, "y"].astype(float).abs() == sh.loc[ok, "y_raw"].astype(float).abs()).all()
    _, _, chk = modern_game
    assert chk["side_checked"] == 3 and chk["side_disagree"] == 0   # inferred side == homeTeamDefendingSide


def test_infer_directions_fallbacks():
    rows = [{"period": 1, "ptype": "REG", "type": "shot-on-goal", "x_raw": 80, "team_id": 1, "hside": None},
            {"period": 2, "ptype": "REG", "type": "faceoff", "x_raw": 0, "team_id": 1, "hside": None},
            {"period": 3, "ptype": "REG", "type": "faceoff", "x_raw": 0, "team_id": 1, "hside": "right"}]
    dirs, checked, dis = derive.infer_directions(rows, home_id=1)
    assert dirs == {1: 1, 2: -1, 3: -1}                  # vote; alternate; homeTeamDefendingSide "right" -> attack -x
    rows[0]["hside"] = "right"                           # contradicts the vote: counted, the vote wins
    dirs, checked, dis = derive.infer_directions(rows, home_id=1)
    assert dirs[1] == 1 and checked == 1 and dis == 1


# ── on-ice reconstruction v situationCode ───────────────────────────────────

def test_on_ice_matches_situation_code(modern_game, old_game):
    for ev, _, chk in (modern_game, old_game):
        assert chk["shifts"] is True
        assert chk["checked"] > 200
        assert chk["ok"] / chk["checked"] >= 0.98
        assert chk["ok_strict"] / chk["checked"] >= 0.98
        five = ev[(ev["sit"] == "1551") & ev["onice_ok"].fillna(False).astype(bool)]
        assert (five["n_home_sk"] == 5).all() and (five["n_away_sk"] == 5).all()
        assert five["home_g"].notna().all() and five["away_g"].notna().all()
        assert five["home_s6"].isna().all()


def test_on_ice_faceoff_takes_incoming_players(modern_game):
    ev, _, _ = modern_game
    fo = ev[ev["type"] == "faceoff"]
    # the faceoff winner and loser are on the ice for their own draw
    on = 0
    for r in fo.itertuples():
        ids = {getattr(r, c) for c in derive.HOME_COLS + derive.AWAY_COLS}
        on += (r.player1 in ids) and (r.player2 in ids)
    assert on / len(fo) >= 0.97


def test_shootout_and_no_shifts_excluded():
    raw = load_fixture("pbp_2026020006.json.gz")
    ev, stn, chk = derive.derive_game(raw, None)            # no shift charts (as 2009-10)
    assert chk["shifts"] is False and chk["checked"] == 0
    assert ev["home_s1"].isna().all() and stn.empty
    # a synthetic shootout attempt never gets on-ice players
    so = dict(raw["plays"][3])
    so = {**so, "periodDescriptor": {"number": 5, "periodType": "SO", "maxRegulationPeriods": 3}, "eventId": 9999,
          "sortOrder": 99999, "timeInPeriod": "00:00", "situationCode": "0101"}
    raw2 = {**raw, "plays": raw["plays"] + [so]}
    ev2, _, _ = derive.derive_game(raw2, load_fixture("shifts_2026020006.json.gz"))
    row = ev2[ev2["event_id"] == 9999].iloc[0]
    assert row["ptype"] == "SO" and int(row["sec"]) == 3900 and pd.isna(row["home_s1"]) and pd.isna(row["onice_ok"])


# ── stints ──────────────────────────────────────────────────────────────────

def test_stints(modern_game, old_game):
    for ev, stn, _ in (modern_game, old_game):
        assert int(stn["dur"].sum()) == 3600                 # three regulation periods, no gaps
        assert (stn["dur"] > 0).all()
        assert (stn["start"].diff().dropna() > 0).all()
        goals = ev[ev["type"] == "goal"]
        assert int(stn["home_goals"].sum()) == int((goals["is_home"] == True).sum())   # noqa: E712
        assert int(stn["away_goals"].sum()) == int((goals["is_home"] == False).sum())  # noqa: E712
        shots = ev[ev["type"].isin(derive.SHOT_TYPES)]
        assert int(stn["home_corsi"].sum() + stn["away_corsi"].sum()) == len(shots)
        assert stn["xg_home"].isna().all()                   # filled by builder B
        assert (stn.loc[stn["period"].diff() != 0, "start_zone"] == "N").all()   # every period opens at centre
        assert ev["stint"].notna().all()
        assert stn["bad"].mean() < 0.05
        assert set(stn["strength"]) >= {"5v5"}


# ── schedule, standings, box, players ───────────────────────────────────────

def test_schedule_parsing():
    raw = load_fixture("schedule_2026-09-30.json")
    games = nhl.week_games(raw)
    assert len(games) == 11
    g = next(x for x in games if x["game_id"] == 2026020006)
    assert (g["home"], g["away"], g["hs"], g["as"], g["status"]) == ("PHI", "PIT", 0, 7, "final")
    assert g["ot"] is False and g["so"] is False and g["period"] == 3 and g["date"] == "2026-09-30"
    assert g["venue"] == "Xfinity Mobile Arena" and g["lines"] is None
    up = next(x for x in games if x["game_id"] == 2026020009)
    assert up["status"] == "scheduled" and up["hs"] is None and up["date"] == "2026-10-01"
    assert nhl.status_of({"gameScheduleState": "PPD", "gameState": "FUT"}) == "postponed"
    assert nhl.status_of({"gameState": "CRIT"}) == "live"


def test_standings_parsing():
    s = nhl.compact_standings(load_fixture("standings_2026-09-30.json"), 20262027)
    assert len(s["rows"]) == 32 and s["date"] == "2026-09-30"
    top = s["rows"][0]
    assert top["team"] == "PIT" and top["pts"] == 2 and top["rw"] == 1 and top["division"] == "Metropolitan"
    assert {r["team"] for r in s["rows"]} == set(canon.teams(20262027))


def test_box_goalies_and_players():
    gl = nhl.goalies_from_box(load_fixture("box_2026020006.json.gz"))
    assert gl["away"]["starter"] == 8481668 and gl["away"]["used"] == [8481668]
    assert gl["home"]["starter"] == 8478435
    gp = nhl.goalies_from_pbp(load_fixture("pbp_2026020006.json.gz"), 20262027)
    assert gp["home"]["starter"] == 8478435
    ps = nhl.players_from_pbp(load_fixture("pbp_2026020006.json.gz"), 20262027)
    assert ps["8471215"]["name"] == "Evgeni Malkin" and ps["8471215"]["team"] == "PIT"


def test_shift_rows():
    rows = stats.compact_shifts(load_fixture("shifts_2026020006.json.gz"))
    assert len(rows) == 736                              # 743 rows less 7 goal markers
    r = rows[0]
    assert r["pid"] == 8471215 and (r["start"], r["end"]) == (34, 107) and r["period"] == 1


def test_partner_lines():
    lines = nhl.partner_lines(load_fixture("partner_now.json"))
    rec = lines[2026020009]
    assert rec["ml"] == [-170, 142]
    assert rec["puck_line"]["home"] == -1.5 and rec["total"]["line"] == 5.5


def test_edge_summary():
    raw = {"topShotSpeed": {"imperial": 99.1, "percentile": 0.9}, "skatingSpeed": {"speedMax": {"imperial": 24.6,
           "percentile": 0.99}, "burstsOver20": {"value": 40}}, "zoneTimeDetails": {"offensiveZonePctg": 0.47}}
    s = edge.summary("skater", raw)
    assert s["top_shot_mph"] == 99.1 and s["max_speed_mph"] == 24.6 and s["bursts_20"] == 40 and s["oz_pct"] == 0.47
    assert edge.summary("skater", None) is None


# ── ESPN ────────────────────────────────────────────────────────────────────

def test_espn_team_mapping():
    assert canon.abbr_from_espn("8", "LA") == "LAK"
    assert canon.abbr_from_espn("129764", "UTAH") == "UTA"
    assert canon.abbr_from_espn(None, "NJ") == "NJD"
    assert canon.abbr_from_espn("24", "ARI", 20202021) == "ARI"
    assert canon.abbr_from_espn("28", "WPG", 20102011) == "ATL"     # the code of that season


def test_espn_event_mapping():
    games = {str(g["game_id"]): g for g in nhl.week_games(load_fixture("schedule_2026-09-30.json"))}
    evs = load_fixture("espn_scoreboard_20260930.json")["events"]
    refs = [espn.event_ref(e, 20262027) for e in evs]
    m = espn.match_events(refs, games, season=20262027)
    assert len(m) == 3 and m["401891821"] == "2026020006"
    for r in refs:                                       # TOR v NYI, COL v LA map to the same pairs
        g = games[m[r["id"]]]
        assert (g["home"], g["away"]) == (r["home"], r["away"]) and (g["hs"], g["as"]) == (r["hs"], r["as"])
    assert refs[0]["attendance"] is None or refs[0]["attendance"] > 0
    # a start far from any game does not map
    far = [{**refs[0], "start": "2026-11-15T00:00Z"}]
    assert espn.match_events(far, games) == {}


def test_espn_pickcenter_lines():
    lines = espn.lines_from_pickcenter(load_fixture("espn_summary_401891821.json"))
    assert lines["src"] == "DraftKings"
    assert lines["ml"] == [-148, 124] and lines["puck_line"] == {"home": -1.5, "price": [180, -218]}
    assert lines["total"] == {"line": 6.5, "over": 110, "under": -130}
    assert lines["open"]["ml"] == [-142, 120] and lines["open"]["total"]["line"] == 5.5
    assert lines["close"]["ml"] == [-148, 124] and lines["close"]["puck_line"]["home"] == -1.5
    assert espn.attendance_from_summary(load_fixture("espn_summary_401891821.json")) == 19902


def test_espn_core_lines_home_underdog():
    lines = espn.compact_lines(load_fixture("espn_odds_401559298.json"))     # CGY @ CBJ, CBJ +1.5 at home
    assert lines["puck_line"]["home"] == 1.5
    assert lines["ml"][0] > 0 > lines["ml"][1]             # home underdog
    assert lines["src"] == "ESPN BET" and lines["ml"] == [135, -160]   # in-play DraftKings / Bet365 rows skipped
    sus = {b["name"] for b in lines["books"] if b.get("suspect")}
    assert {"DraftKings", "Bet365", "SugarHouse"} <= sus and "MGM" not in sus
    assert 1.0 < espn.overround([135, -160]) < 1.1
    assert lines["open"] and lines["close"]
    assert len(lines["books"]) >= 3 and all("live" not in str(b["name"]).lower() for b in lines["books"])
    assert lines["consensus"]["n_books"] >= 3


# ── MoneyPuck ───────────────────────────────────────────────────────────────

def test_moneypuck_slice_and_join(modern_game):
    mp = pd.read_parquet(fixture_path("moneypuck_shots_2026_slice.parquet"))
    assert len(mp) <= 300 and set(mp["nhl_game_id"].dropna().astype(int)) >= {2026020006, 2026020001}
    ev, _, _ = modern_game
    j = moneypuck.join_events(ev, mp[mp["nhl_game_id"] == 2026020006])
    assert len(j) == len(ev[ev["type"].isin(derive.UNBLOCKED)])
    assert j["mp_xg"].notna().mean() >= 0.97
    assert j.loc[j["type"] == "goal", "mp_xg"].notna().all()
    assert moneypuck.url(20092010).endswith("shots_2009.zip")


# ── canon: teams, formats, arenas ───────────────────────────────────────────

def test_teams_by_season():
    assert len(canon.teams(20092010)) == 30 and "ATL" in canon.teams(20102011) and "PHX" in canon.teams(20132014)
    t11 = canon.teams(20112012)
    assert "WPG" in t11 and "ATL" not in t11 and t11["WPG"]["division"] == "Southeast"
    assert canon.teams(20132014)["WPG"]["division"] == "Central"
    assert "ARI" in canon.teams(20142015) and "PHX" not in canon.teams(20142015)
    assert len(canon.teams(20172018)) == 31 and canon.teams(20172018)["VGK"]["division"] == "Pacific"
    cov = canon.teams(20202021)
    assert cov["TOR"]["division"] == "North" and cov["TOR"]["conference"] is None
    t21 = canon.teams(20212022)
    assert len(t21) == 32 and t21["SEA"]["division"] == "Pacific" and t21["ARI"]["division"] == "Central"
    t24 = canon.teams(20242025)
    assert "UTA" in t24 and "ARI" not in t24 and t24["UTA"]["id"] == 59
    assert canon.teams(20252026)["UTA"]["id"] == 68
    assert canon.abbr_from_id(53, 20202021) == "ARI" and canon.abbr_from_id(68, 20262027) == "UTA"
    assert canon.code_in_season("WPG", 20102011) == "ATL" and canon.code_in_season("UTA", 20152016) == "ARI"
    for s in canon.seasons_between(20092010, 20262027):
        divs = {}
        for a, t in canon.teams(s).items():
            divs.setdefault(t["division"], []).append(a)
        assert all(len(v) >= 5 for v in divs.values())


def test_formats():
    assert canon.games_per_team(20262027) == 84 and canon.games_per_team(20122013) == 48
    assert canon.games_per_team(20202021) == 56 and canon.games_per_team(20252026) == 82
    assert canon.formats(20112012)["playoff"]["kind"] == "conference"
    assert canon.formats(20132014)["playoff"]["kind"] == "divisional_wildcard"
    assert canon.formats(20192020)["playoff"]["teams"] == 24 and canon.formats(20192020)["paused"]
    assert canon.formats(20202021)["playoff"]["kind"] == "division_2021"
    assert canon.formats(20142015)["ot_skaters"] == 4 and canon.formats(20152016)["ot_skaters"] == 3


def test_arenas():
    assert canon.arena_for_game("Xfinity Mobile Arena", "PHI", 20262027)["club"] == "PHI"
    assert canon.arena_for_game("Wells Fargo Center")["key"] == "wellsfargo"
    assert canon.arena_for_game("Jobing.com Arena")["city"] == "Glendale"
    assert canon.arena_for_game("Avicii Arena")["city"] == "Stockholm"
    assert canon.arena_for_game("Michigan Stadium")["outdoor"] is True
    assert canon.arena_for_game("Somewhere Unknown", "EDM", 20152016)["name"] == "Rexall Place"
    assert canon.home_arena("EDM", 20162017)["name"] == "Rogers Place"
    assert canon.home_arena("NYI", 20162017)["name"] == "Barclays Center"
    assert canon.home_arena("UTA", 20242025)["city"] == "Salt Lake City"
    assert canon.home_arena("ARI", 20222023)["name"] == "Mullett Arena"
    for s in canon.seasons_between(20092010, 20262027):
        for a in canon.teams(s):
            assert canon.home_arena(a, s) is not None, (a, s)
    bos, tor = canon.home_arena("BOS", 20262027), canon.home_arena("TOR", 20262027)
    assert 640 < canon.haversine_km(bos["lat"], bos["lon"], tor["lat"], tor["lon"]) < 700


# ── tiebreakers ─────────────────────────────────────────────────────────────

def _g(gid, day, home, away, hs, as_, ot=False, so=False):
    return {"game_id": gid, "start": f"{day}T23:00:00Z", "home": home, "away": away, "hs": hs, "as": as_,
            "ot": ot, "so": so, "status": "final", "type": 2}


# Three clubs level on points, games, RW, ROW and W. A hosted B twice, B hosted A once: the first A-B game in A
# (game 1, an A win) is the odd game and is left out. Points among the three, odd game excluded:
#   A: g2 OT loss 1 + g3 win 2 + g4 loss 0 + g5 SO win 2 = 5 of 8 = .625
#   B: g2 OT win 2 + g3 loss 0 + g6 win 2 + g7 OT win 2   = 6 of 8 = .750
#   C: g4 win 2 + g5 SO loss 1 + g6 loss 0 + g7 OT loss 1  = 4 of 8 = .500
# -> B, A, C. Counting the odd game A would have 7 of 10 (.700) against B's 6 of 10 (.600) and lead.
THREE = [_g(1, "2025-10-10", "A", "B", 3, 1), _g(2, "2025-11-10", "B", "A", 2, 1, ot=True),
         _g(3, "2025-12-10", "A", "B", 4, 2), _g(4, "2025-10-20", "C", "A", 3, 0),
         _g(5, "2025-11-20", "A", "C", 2, 1, so=True), _g(6, "2025-10-25", "B", "C", 5, 2),
         _g(7, "2025-12-25", "C", "B", 2, 3, ot=True)]
LEVEL = {t: {"gp": 82, "pts": 100, "rw": 40, "row": 44, "w": 46, "gf": 250, "ga": 230} for t in "ABC"}


def test_tiebreak_three_way_head_to_head_with_odd_game():
    h2h = canon.head_to_head(["A", "B", "C"], THREE)
    assert h2h == {"A": (5, 8), "B": (6, 8), "C": (4, 8)}
    trace = []
    assert canon.order_tied(["A", "B", "C"], LEVEL, THREE, 20252026, trace=trace) == ["B", "A", "C"]
    assert [s for s, _ in trace][:5] == ["gp", "rw", "row", "w", "h2h"]


def test_tiebreak_earlier_steps_and_carry_on():
    rec = {t: dict(v) for t, v in LEVEL.items()}
    rec["C"]["rw"] = 41                                   # C wins on regulation wins, A and B carry on, and
    # head-to-head is then among A and B only (2 clubs: points, odd game 1 excluded): A 1 + 2 = 3, B 2 + 0 = 2
    assert canon.order_tied(["A", "B", "C"], rec, THREE, 20252026) == ["C", "A", "B"]
    rec = {t: dict(v) for t, v in LEVEL.items()}
    rec["A"]["gp"] = 81                                   # fewer games played first (points percentage)
    assert canon.order_tied(["A", "B", "C"], rec, THREE, 20252026)[0] == "A"
    # two clubs level after head-to-head go on to goal differential, then goals for
    two = [_g(1, "2025-10-10", "A", "B", 2, 1), _g(2, "2025-11-10", "B", "A", 2, 1)]
    rec = {t: dict(LEVEL[t]) for t in "AB"}
    rec["B"]["gf"] = 260
    assert canon.order_tied(["A", "B"], rec, two, 20252026) == ["B", "A"]
    rec["B"]["gf"], rec["B"]["ga"], rec["A"]["gf"], rec["A"]["ga"] = 260, 240, 250, 230
    assert canon.order_tied(["A", "B"], rec, two, 20252026) == ["B", "A"]        # same DIFF, more GF


def test_tiebreak_eras():
    assert [k for k, _ in canon.tiebreak_steps(20152016)] == ["gp", "row", "h2h", "diff"]
    assert [k for k, _ in canon.tiebreak_steps(20092010)] == ["gp", "w", "h2h", "diff"]
    assert canon.tiebreak_steps(20262027)[1][0] == "rw" and "Regulation Wins" in canon.tiebreak_steps(20262027)[1][1]
    rec = {t: dict(v) for t, v in LEVEL.items()}
    rec["A"]["rw"] = 45                                   # RW is not a step in 2015-16: H2H decides
    assert canon.order_tied(["A", "B", "C"], rec, THREE, 20152016) == ["B", "A", "C"]
    assert canon.order_tied(["A", "B", "C"], rec, THREE, 20252026)[0] == "A"


def test_records_and_rank():
    rec = canon.records_from_games(THREE)
    assert rec["A"]["pts"] == 2 + 1 + 2 + 0 + 2 and rec["A"]["gp"] == 5
    assert rec["B"]["rw"] == 1 and rec["B"]["row"] == 3 and rec["B"]["w"] == 3
    assert rec["C"]["otl"] == 2 and rec["A"]["otl"] == 1
    assert canon.game_points(_g(9, "2025-01-01", "A", "B", 3, 2, so=True)) == (2, 1)
    order = canon.rank(["A", "B", "C"], rec, THREE, 20252026)
    assert order[0] == "A" and rec["A"]["pts"] > rec["B"]["pts"]


def test_playoff_seeds_divisional_wildcard():
    season = 20252026
    ts = canon.teams(season)
    rec = {a: {"gp": 82, "pts": 120 - k, "rw": 40, "row": 44, "w": 46, "gf": 250, "ga": 230}
           for k, a in enumerate(sorted(ts))}
    seeds = canon.playoff_seeds(season, rec, [])
    for conf, s in seeds.items():
        tops = [a for v in s["divisions"].values() for a in v]
        assert len(tops) == 6 and len(s["wild_cards"]) == 2 and not set(tops) & set(s["wild_cards"])
        rest = [a for a, t in ts.items() if t["conference"] == conf and a not in tops]
        assert s["wild_cards"] == sorted(rest, key=lambda a: -rec[a]["pts"])[:2]
    old = canon.playoff_seeds(20112012, {a: {"gp": 82, "pts": 100 + k, "rw": 0, "row": 40, "w": 45, "gf": 1, "ga": 1}
                                         for k, a in enumerate(sorted(canon.teams(20112012)))}, [])
    for conf, eight in old.items():
        divs = {canon.teams(20112012)[a]["division"] for a in eight[:3]}
        assert len(eight) == 8 and len(divs) == 3            # division winners take seeds 1-3


# ── stores ──────────────────────────────────────────────────────────────────

def test_store_merge_and_owned_phases(rink_roots):
    s = st.load(20262027)
    games = nhl.week_games(load_fixture("schedule_2026-09-30.json"))
    for g in games:
        st.merge_game(s, g)
    st.save_owned(s, ["schedule"])
    # the ESPN process adds lines; the schedule process (stale copy) rescans without them
    a, b = st.load(20262027), st.load(20262027)
    a["games"]["2026020006"]["lines"] = {"src": "DraftKings", "ml": [-148, 124]}
    a["games"]["2026020006"]["attendance"] = 19902
    st.save_owned(a, ["espn"])
    b["games"]["2026020006"]["hs"] = 0
    st.save_owned(b, ["schedule"])
    disk = st.load(20262027)
    g = disk["games"]["2026020006"]
    assert g["lines"]["ml"] == [-148, 124] and g["attendance"] == 19902
    # a rescan that sees a final game as scheduled never reverts it
    st.merge_game(disk, {**g, "status": "scheduled", "hs": None, "as": None, "lines": None})
    assert disk["games"]["2026020006"]["status"] == "final" and disk["games"]["2026020006"]["lines"]
    assert st.complete_through(disk) == "2026-09-30"
    assert st.season_path(20262027).parent.parent == rink_roots["data"]


def test_build_season_from_raw(rink_roots):
    season = 20262027
    st.write_json_gz(st.pbp_path(season, 2026020006), load_fixture("pbp_2026020006.json.gz"))
    st.write_json_gz(st.shifts_path(season, 2026020006), load_fixture("shifts_2026020006.json.gz"))
    out = derive.build_season(season)
    assert out["games"] == 1 and out["events"] == 327 and out["rate"] >= 0.98
    ev = pd.read_parquet(st.events_path(season))
    stn = pd.read_parquet(st.stints_path(season))
    assert len(ev) == 327 and int(stn["dur"].sum()) == 3600
    for c in ("game_id", "sec", "type", "team", "x", "y", "zone", "shot_type", "shooter", "goalie", "assist1", "assist2",
              "strength", "score_home", "score_away", "home_s1", "home_s6", "home_g", "away_s1", "away_g", "onice_ok"):
        assert c in ev.columns
    for c in ("start", "end", "strength", "home_sog", "away_fenwick", "home_goals", "xg_home", "start_zone"):
        assert c in stn.columns
    chk = st.read_json(st.onice_check_path(season))
    assert chk["checked"] > 300 and chk["zone_agree"] == chk["zone_checked"]


# ── fetch loop: writes survive the periodic save_owned (which replaces the game and meta dicts) ──

class _FakeClient:
    used = 0

    def __init__(self, box, scoreboard, odds):
        self.box, self.scoreboard, self.odds = box, scoreboard, odds

    def get(self, url, params=None):
        self.used += 1
        if url.endswith("/boxscore"):
            return self.box
        if url.endswith("/scoreboard"):
            return self.scoreboard
        if url.endswith("/odds"):
            return self.odds
        return {"data": []}


def _fetch_module():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[2] / "scripts" / "nhl_fetch.py"
    spec = importlib.util.spec_from_file_location("nhl_fetch_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_phase_writes_survive_periodic_saves(rink_roots, monkeypatch):
    from datetime import datetime, timezone
    nf = _fetch_module()
    monkeypatch.setattr(nf, "SAVE_EVERY", 1)
    season = 20262027
    s = st.load(season)
    for g in nhl.week_games(load_fixture("schedule_2026-09-30.json")):
        st.merge_game(s, g)
    st.save_owned(s, ["schedule"])
    finals = [gid for gid, g in s["games"].items() if g["status"] == "final"]
    assert len(finals) == 3
    c = _FakeClient(load_fixture("box_2026020006.json.gz"), load_fixture("espn_scoreboard_20260930.json"),
                    load_fixture("espn_odds_401559298.json"))
    nf.box_phase(c, s, False, date(2026, 10, 1), None)
    st.save_owned(s, ["box"])
    disk = st.load(season)
    assert all(disk["games"][gid].get("goalies") for gid in finals)
    nf.espn_phase(c, s, False, datetime(2026, 10, 1, 20, tzinfo=timezone.utc))
    st.save_owned(s, ["espn"])
    disk = st.load(season)
    assert all(disk["games"][gid].get("lines") and disk["games"][gid].get("espn_id") for gid in finals)
    assert len(disk["meta"]["espn_odds"]) == 3 and disk["meta"]["espn_days"]


def test_tiebreak_all_tied_terminates_in_abbreviation_order():
    zero = {"gp": 0, "pts": 0, "rw": 0, "row": 0, "w": 0, "gf": 0, "ga": 0}
    rec = {t: dict(zero) for t in ("TOR", "BOS", "MTL")}
    assert canon.rank(["TOR", "BOS"], rec, [], 20262027) == ["BOS", "TOR"]
    trace = []
    assert canon.order_tied(["TOR", "MTL", "BOS"], rec, [], 20262027, trace=trace) == ["BOS", "MTL", "TOR"]
    assert trace[-1][0] == "unresolved"
    for season in (20092010, 20152016, 20262027):            # every era terminates
        assert canon.rank(list(rec), rec, [], season) == ["BOS", "MTL", "TOR"]
    assert canon.order_tied(["TOR", "BOS"], rec, [], 20262027, steps=[]) == ["BOS", "TOR"]


_TOI = """<table><tr><td align="center" valign="top" class="playerHeading + border" colspan="8">{num} {name}</td></tr>
<tr><td class="heading">Shift #</td><td>Per</td><td>Start</td><td>End</td><td>Duration</td><td>Event</td></tr>
<tr class="oddColor"><td>1</td><td>1</td><td>0:36 / 19:24</td><td>1:16 / 18:44</td><td>00:40</td><td>&nbsp;</td></tr>
<tr class=" evenColor"><td>2</td><td>OT</td><td>1:38 / 3:22</td><td>2:22 / 2:38</td><td>00:44</td><td>G</td></tr>
</table>"""


def test_toi_html_fallback():
    rows = stats.parse_toi_html(_TOI.format(num=4, name="BYRAM, BOWEN"))
    assert rows == [{"number": 4, "name": "BYRAM, BOWEN", "period": 1, "start": 36, "end": 76},
                    {"number": 4, "name": "BYRAM, BOWEN", "period": 4, "start": 98, "end": 142}]
    pbp = {"id": 2024021235, "homeTeam": {"id": 7}, "awayTeam": {"id": 1},
           "rosterSpots": [{"teamId": 7, "sweaterNumber": 4, "playerId": 8481524},
                           {"teamId": 1, "sweaterNumber": 4, "playerId": 8480000}]}
    fb = stats.shifts_from_toi_html(_TOI.format(num=4, name="A, B"), _TOI.format(num=9, name="C, D"), pbp)
    assert fb["source"] == "html" and fb["total"] == 2 and fb["unmatched"] == 2      # visitor #9 not in the roster
    assert stats.compact_shifts(fb)[0] == {"pid": 8481524, "team_id": 7, "team": None, "period": 1, "start": 36, "end": 76}
    assert stats.shifts_from_toi_html("", _TOI, pbp) is None


def test_espn_lines_reject_prices_stored_as_lines():
    """Some 2022-23 ESPN close blocks carry American prices in the line fields: never stored as a line, repaired in
    stored records, and line_fields falls back to the main line."""
    from oddsmarkets.nhl.models import _cdata as D
    from oddsmarkets.nhl.sources import espn as E
    assert E._tot(110.0, 110, -130) is None and E._tot(6.5, -110, -110)["line"] == 6.5
    assert E._pl(-250.0, -250, 210) is None and E._pl(-1.5, 150, -170)["home"] == -1.5
    rec = {"ml": [105, -125], "puck_line": {"home": 1.5, "price": [-250, 210]}, "total": {"line": 6.5, "over": 110, "under": -130},
           "open": None, "close": {"ml": [105, -125], "puck_line": {"home": -250.0, "price": [-250, 210]},
                                   "total": {"line": 110.0, "over": 110, "under": -130}}, "books": []}
    f = D.line_fields(rec)
    assert f["total_line"] == 6.5 and f["pl_home"] == 1.5 and f["ml_home"] == 105
    assert E.repair_lines(rec) == 2
    assert rec["close"] == {"ml": [105, -125], "puck_line": None, "total": None} and rec["total"]["line"] == 6.5
