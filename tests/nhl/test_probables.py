"""Probable starting goalies (ESPN scoreboard, captured before the start): parsing, the capture history, the NHL id
mapping, the store field, the game card and the model's starter. No network."""
from __future__ import annotations

from oddsmarkets.nhl import store as st
from oddsmarkets.nhl.analytics import adapters, games
from oddsmarkets.nhl.sources import espn


def _comp(home=("Jeremy Swayman", "Expected"), away=("Juuse Saros", "Confirmed")):
    def side(ha, who):
        x = {"homeAway": ha, "team": {"id": "1" if ha == "home" else "27"}}
        if who:
            x["probables"] = [{"name": "probableStartingGoalie", "playerId": 1,
                               "athlete": {"id": "4712036" if ha == "home" else "3042109", "fullName": who[0]},
                               "status": {"id": "101", "name": who[1], "type": who[1].lower()}}]
        return x
    return {"competitors": [side("home", home), side("away", away)]}


PLAYERS = {"8480280": {"name": "Jeremy Swayman", "last": "Swayman", "pos": "G", "team": "BOS"},
           "8480022": {"name": "Michael DiPietro", "last": "DiPietro", "pos": "G", "team": "BOS"},
           "8477424": {"name": "Juuse Saros", "last": "Saros", "pos": "G", "team": "NSH"},
           "8400001": {"name": "Jeremy Swayman", "last": "Swayman", "pos": "C", "team": "XXX"}}
TEAMS = {"home": "BOS", "away": "NSH"}


def test_probables_parsed_from_the_scoreboard():
    p = espn.probables_of(_comp())
    assert p["home"] == {"espn": "4712036", "name": "Jeremy Swayman", "status": "projected"}
    assert p["away"]["status"] == "confirmed"
    assert espn.probables_of(_comp(None, None)) is None
    assert espn.probables_of({}) is None


def test_goalie_id_mapping_prefers_the_goalie_and_never_guesses():
    assert espn.nhl_goalie_id(PLAYERS, "BOS", "Jeremy Swayman") == "8480280"
    assert espn.nhl_goalie_id(PLAYERS, "BOS", "Jérémy Swayman") == "8480280"       # accents
    assert espn.nhl_goalie_id(PLAYERS, "BOS", "Mike DiPietro") == "8480022"                  # last name, team goalie
    assert espn.nhl_goalie_id(PLAYERS, "NSH", "Somebody Else") is None
    assert espn.nhl_goalie_id({}, "BOS", "Jeremy Swayman") is None


def test_capture_history_keeps_first_seen_and_confirmation_times():
    a = espn.update_probables(None, espn.probables_of(_comp()), "2026-10-22T12:32:00Z", PLAYERS, TEAMS)
    assert a["home"]["id"] == "8480280" and a["home"]["since"] == "2026-10-22T12:32:00Z"
    assert a["home"]["confirmed_at"] is None and a["away"]["confirmed_at"] == "2026-10-22T12:32:00Z"
    # same read an hour later: no new log entry, times kept
    b = espn.update_probables(a, espn.probables_of(_comp()), "2026-10-22T13:32:00Z", PLAYERS, TEAMS)
    assert b["home"]["log"] == a["home"]["log"] and len(b["home"]["log"]) == 1 and b["at"] == "2026-10-22T13:32:00Z"
    # confirmed later
    c = espn.update_probables(b, espn.probables_of(_comp(home=("Jeremy Swayman", "Confirmed"))), "2026-10-22T17:02:00Z",
                              PLAYERS, TEAMS)
    assert c["home"]["status"] == "confirmed" and c["home"]["confirmed_at"] == "2026-10-22T17:02:00Z"
    assert c["home"]["since"] == "2026-10-22T12:32:00Z" and len(c["home"]["log"]) == 2
    # a different goalie: new since, confirmation reset, logged
    d = espn.update_probables(c, espn.probables_of(_comp(home=("Michael DiPietro", "Expected"))), "2026-10-22T18:02:00Z",
                              PLAYERS, TEAMS)
    assert d["home"]["id"] == "8480022" and d["home"]["since"] == "2026-10-22T18:02:00Z"
    assert d["home"]["confirmed_at"] is None and d["home"]["log"][-1] == ["2026-10-22T18:02:00Z", "8480022", "projected"]
    assert d["away"] == c["away"]
    assert espn.update_probables(None, None, "x") is None


def test_store_owns_and_keeps_probables():
    assert "probables" in st.OWNED_GAME["espn"]
    s = {"games": {"1": {"game_id": 1, "status": "scheduled", "probables": {"home": {"name": "A"}}}}}
    st.merge_game(s, {"game_id": 1, "status": "scheduled", "probables": None})
    assert s["games"]["1"]["probables"] == {"home": {"name": "A"}}


def test_card_and_model_use_probables_only_before_the_start():
    pb = espn.update_probables(None, espn.probables_of(_comp()), "2026-10-22T12:32:00Z", PLAYERS, TEAMS)
    g = {"game_id": 2026020154, "status": "scheduled", "home": "BOS", "away": "NSH", "probables": pb}
    s = games.starters(g)
    assert s["home"]["pid"] == "8480280" and s["home"]["status"] == "projected" and s["home"]["at"] == "2026-10-22T12:32:00Z"
    assert s["away"]["status"] == "confirmed" and s["away"]["src"] == "ESPN"
    assert adapters._starter(g, "home") == "8480280"
    # recorded starters win; after the start the probables are ignored
    g2 = dict(g, status="final", goalies={"home": {"starter": 8480022}, "away": {"starter": 8477424}})
    assert games.starters(g2) == {"home": "8480022", "away": "8477424"}
    g3 = dict(g, status="live")
    assert adapters._starter(g3, "home") is None and games.probable_goalies(g3) is None
    # an unmapped name shows on the card but leaves the model on the usual starter
    pb2 = espn.update_probables(None, espn.probables_of(_comp(home=("Nobody Known", "Expected"))), "t", PLAYERS, TEAMS)
    g4 = dict(g, probables=pb2)
    assert games.starters(g4)["home"]["pid"] is None and adapters._starter(g4, "home") is None


def test_page_signature_unchanged_without_probables():
    g = {"status": "final", "hs": 1, "as": 2, "goalies": {"home": "1"}, "lines": None, "start": "x"}
    s0 = games.page_sig(g, 10, {"v": 1})
    assert games.page_sig(dict(g, probables=None), 10, {"v": 1}) == s0
    assert games.page_sig(dict(g, probables={"at": "t"}), 10, {"v": 1}) != s0
