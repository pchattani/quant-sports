from oddsmarkets.golf.sources import espn


def _hole(n, strokes, rel):
    return {"value": float(strokes), "period": n, "scoreType": {"displayValue": rel}}


def test_scoreboard_rounds_and_holes_with_par_from_the_score_type():
    raw = {"events": [{"id": "1", "name": "Open", "date": "2025-06-01T04:00Z", "endDate": "2025-06-04T04:00Z",
                       "status": {"type": {"name": "STATUS_FINAL"}}, "season": {"slug": "regular-season"},
                       "competitions": [{"competitors": [
                           {"id": "9", "type": "athlete", "athlete": {"displayName": "A B", "flag": {"alt": "USA"}},
                            "linescores": [{"value": 12.0, "period": 1, "linescores": [_hole(1, 3, "-1"), _hole(2, 5, "+1"), _hole(3, 4, "E")]},
                                           {"value": 0.0, "period": 2, "linescores": []}]},
                           {"id": "77", "type": "team", "linescores": []}]}]}]}
    out = espn.parse_scoreboard(raw, "pga")
    assert out["events"][0]["status"] == "final" and out["events"][0]["start"] == "2025-06-01"
    assert out["events"][0]["field"] == ["9"]
    assert out["players"] == {"9": {"name": "A B", "country": "USA"}}
    assert out["rounds"] == [{"event": "1", "pid": "9", "round": 1, "strokes": 12, "holes": 3}]
    assert [(h["hole"], h["strokes"], h["par"]) for h in out["holes"]] == [(1, 3, 4), (2, 5, 4), (3, 4, 4)]


def test_leaderboard_positions_statuses_and_team_events():
    comp = lambda pid, pos, tie, st, rounds: {  # noqa: E731
        "id": pid, "uid": f"s:1100~a:{pid}", "athlete": {"displayName": pid}, "earnings": 1000.0,
        "status": {"type": {"name": st}, "position": {"displayName": pos, "isTie": tie}}, "score": {"value": sum(rounds)},
        "statistics": [{"name": "scoreToPar", "value": 1.0}, {"name": "cupPoints", "value": 5.0}],
        "linescores": [{"value": float(v), "period": i + 1, "displayValue": "+1", "outScore": 35, "inScore": 36} for i, v in enumerate(rounds)]
        + [{"value": 4.0, "period": 5, "isPlayoff": True}]}
    raw = {"events": [{"id": "5", "name": "Classic", "purse": 9e6, "tournament": {"major": True, "numberOfRounds": 4, "cutRound": 2, "cutScore": 1},
                       "courses": [{"id": "29", "name": "Club", "shotsToPar": 72, "holes": [{"number": 1, "shotsToPar": 4, "totalYards": 400}]}],
                       "winner": {"athlete": {"id": "1"}},
                       "competitions": [{"competitors": [comp("1", "T2", True, "STATUS_FINISH", [70, 71, 72, 73]),
                                                         comp("2", "CUT", False, "STATUS_CUT", [75, 76])]}]}]}
    out = espn.parse_leaderboard(raw, "pga")
    ev = out["event"]
    assert ev["major"] and ev["cut_round"] == 2 and ev["winner"] == "1" and not ev["team"]
    assert ev["courses"][0]["holes"] == [[1, 4, 400]]
    r = {x["pid"]: x for x in out["results"]}
    assert (r["1"]["pos"], r["1"]["tie"], r["1"]["status"], r["1"]["points"]) == (2, True, "finish", 5.0)
    assert (r["2"]["pos"], r["2"]["status"]) == (None, "cut")
    assert sorted((x["pid"], x["round"]) for x in out["rounds"]) == [("1", 1), ("1", 2), ("1", 3), ("1", 4), ("2", 1), ("2", 2)]
    team = {"events": [{"id": "6", "competitions": [{"competitors": [{"id": "126007", "uid": "s:1100~l:1106~t:126007"}]}]}]}
    t = espn.parse_leaderboard(team, "pga")
    assert t["event"]["team"] and t["results"] == [] and t["rounds"] == []
    assert espn.parse_leaderboard({"events": []}, "pga") is None
