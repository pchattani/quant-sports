"""oddsmarkets/tennis/analytics/follow_build.py: the Ace's follow cards from a synthetic payload tree."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from oddsmarkets.common import follow as FL
from oddsmarkets.tennis.analytics import follow_build as B

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
# pid -> (name, short, country, players_index rank)
P = {"1": ("Alpha Ace", "A. Ace", "ITA", 1), "2": ("Beta Baseline", "B. Baseline", "ESP", 2), "3": ("Gamma Grinder", "G. Grinder", "USA", 40),
     "4": ("Delta Dropshot", "D. Dropshot", "FRA", 499), "5": ("Echo Edge", "E. Edge", "GER", 500), "6": ("Foxtrot Far", "F. Far", "AUS", 501),
     "7": ("Golf Gone", "G. Gone", "SWE", 12), "8": ("Hotel Qualifier", "H. Qualifier", "CZE", 800), "x:old-p": ("Old Player", "O. Player", "GBR", 3)}


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M")


def write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def tree(tmp: Path) -> Path:
    data = tmp / "data"
    write(data / "atp" / "players_index.json", {"ok": True, "players": {k: [v[0], v[1], v[2], v[3]] for k, v in P.items()}})
    # this week: Basel; 1 v 6 tomorrow (6 is outside the top 500 but plays this week); 8 is in the draw only
    nxt = {"id": "basel-2026-QF-1-6", "event": "basel-2026", "round": "QF", "date": iso(NOW + timedelta(hours=26)), "status": "upcoming",
           "p1": "1", "p2": "6", "winner": None, "sets": [], "model": {"p1": 0.81}, "market": {"p1": 0.78}}
    started = {"id": "basel-2026-QF-2-3", "event": "basel-2026", "round": "QF", "date": iso(NOW - timedelta(hours=1)), "status": "upcoming",
               "p1": "2", "p2": "3", "winner": None, "sets": [], "model": {"p1": 0.6}}
    won = {"id": "basel-2026-R16-1-4", "event": "basel-2026", "round": "R16", "date": iso(NOW - timedelta(days=1)), "status": "done", "p1": "1", "p2": "4",
           "winner": "4", "sets": [[4, 6, None, None], [6, 7, 3, 7]], "model": {"p1": 0.75}}
    later = {"id": "basel-2026-R16-1-5", "event": "basel-2026", "round": "R16", "date": iso(NOW + timedelta(hours=3)), "status": "done", "p1": "1", "p2": "5",
             "winner": "5", "sets": [[0, 6, None, None], [0, 6, None, None]], "model": {"p1": 0.9}}
    write(data / "index.json", {"ok": True, "tours": {"atp": {"year": 2026, "today": [nxt, started], "upcoming": [], "live": [], "recent": [won, later],
                                                             "events_now": [{"event": "basel-2026", "name": "Swiss Indoors Basel", "level": "500"}]}}})
    write(data / "atp" / "events" / "basel-2026.json", {"ok": True, "event": {"id": "basel-2026", "champion": None},
                                                        "draw": {"slots": [[1, "1"], [2, "6"], [3, "2"], [4, "3"], [5, "8"]]},
                                                        "sim": {"players": {"1": {"p_title": 0.42}, "2": {"p_title": 0.2}}}, "results": [won]})
    write(data / "atp" / "2026" / "events.json", {"events": {"basel-2026": {"name": "Swiss Indoors Basel", "city": "Basel", "level": "500", "start": "2026-10-24",
                                                                             "end": "2026-11-01", "status": "live"},
                                                              "atp-finals-2026": {"name": "ATP Finals", "level": "finals", "start": "2026-11-15", "end": "2026-11-22"}}})
    write(data / "atp" / "2025" / "events.json", {"events": {"paris-2025": {"name": "Rolex Paris Masters", "city": "Paris", "level": "m1000"},
                                                              "atp-finals-2025": {"name": "ATP Finals", "level": "finals"}}})
    # career files: 1 has won 12 straight before losing to 4 yesterday; a result after the clock is never read
    res1 = [{"match": f"m{i}", "date": (NOW - timedelta(days=30 - i)).date().isoformat(), "event": "vienna-2026", "round": "R32", "opp": "3", "won": True,
             "status": "done", "score": "6-3 6-4", "p_pre": 0.7} for i in range(12)]
    res1.append({"match": "future", "date": (NOW + timedelta(days=2)).date().isoformat(), "event": "x", "round": "F", "opp": "2", "won": False, "status": "done",
                 "score": "0-6 0-6", "p_pre": 0.5})
    write(data / "atp" / "players" / "1.json", {"ok": True, "name": "Alpha Ace", "short": "A. Ace", "country": "ITA",
                                                "current": {"rank": 1, "points": 11000, "elo": {"all": 2136.3, "hard": 2090}, "elo_rank": 1},
                                                "odds": {"finals_qual": 1.0, "year_end_no1": 0.3}, "results": res1[::-1],
                                                "seasons": [{"year": 2026, "w": 12, "l": 1, "titles": 4}],
                                                "elo": [[(NOW - timedelta(days=40)).date().isoformat(), 2050.0], [(NOW - timedelta(days=2)).date().isoformat(), 2136.3]],
                                                "to_defend": [["paris-2025", "2026-11-02", 1000], ["atp-finals-2025", "2026-11-16", 1500]]})
    for pid in ("2", "3", "4", "5"):
        write(data / "atp" / "players" / f"{pid}.json", {"ok": True, "name": P[pid][0], "short": P[pid][1], "country": P[pid][2],
                                                         "current": {"rank": P[pid][3], "elo": {"all": 1800.0}, "elo_rank": int(pid) + 3},
                                                         "results": [{"match": f"r{pid}", "date": "2026-09-01", "event": "vienna-2026", "round": "R32", "opp": "1",
                                                                      "won": pid == "2", "status": "done", "score": "6-4 6-4", "p_pre": 0.3}]})
    write(data / "atp" / "players" / "7.json", {"ok": True, "name": "Golf Gone", "short": "G. Gone", "current": {},
                                                "results": [{"match": "old", "date": "2019-05-01", "event": "rome-2019", "round": "F", "opp": "1", "won": True,
                                                             "status": "done", "score": "6-4 6-4", "p_pre": 0.5}]})
    cat = {"1": {"qualified": True, "values": {"serve_rating": 1.3, "hold": 0.88, "return_rating": 0.9, "brk": 0.37, "games_won_pct": 0.6, "win_v_top10": 0.9,
                                               "tb_pct": 0.7, "dec_pct": 0.5, "titles": 4, "win_pct": 0.92, "tb_over": 2.4},
                 "pct": {"serve_rating": 100, "hold": 99, "return_rating": 97, "brk": 95, "games_won_pct": 98, "win_v_top10": 96, "tb_pct": 60, "dec_pct": 20}}}
    for pid in ("2", "3", "4", "5"):
        cat[pid] = {"qualified": True, "values": {"serve_rating": 0.1 * int(pid), "hold": 0.8, "return_rating": 0.2, "brk": 0.25, "games_won_pct": 0.5,
                                                  "win_v_top10": 0.3, "titles": 1, "win_pct": 0.6}, "pct": {"serve_rating": 50}}
    write(data / "atp" / "players.json", {"ok": True, "year": 2026, "players": cat,
                                          "metrics": [{"key": "serve_rating", "fmt": "2"}, {"key": "hold", "fmt": "pct"}, {"key": "return_rating", "fmt": "2"},
                                                      {"key": "brk", "fmt": "pct"}, {"key": "games_won_pct", "fmt": "pct"}, {"key": "win_v_top10", "fmt": "pct"},
                                                      {"key": "tb_pct", "fmt": "pct"}, {"key": "dec_pct", "fmt": "pct"}]})
    week_ago = (NOW - timedelta(days=8)).date().isoformat()
    write(data / "atp" / "race.json", {"ok": True, "as_of": NOW.date().isoformat(), "updated_at": iso(NOW - timedelta(hours=2)) + ":00Z", "n_sims": 10000, "finals_qual": {"1": 1.0, "2": 0.9, "3": 0.4},
                                       "year_end_no1": {"1": 0.3, "2": 0.7}})
    write(data / "atp" / "chance_log.json", {"2026": {"finals_qual": {week_ago: {"1": 1.0, "2": 0.6, "3": 0.5},
                                                                      (NOW + timedelta(days=3)).date().isoformat(): {"2": 0.0}},
                                                      "year_end_no1": {week_ago: {"1": 0.5, "2": 0.5}}}})
    return data


def read(data: Path, pid: str) -> dict:
    return json.loads((data / "follow" / "atp" / f"{pid}.json").read_text(encoding="utf-8"))


def test_selection_rule_is_rank_500_or_playing_this_week():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        data = tree(Path(d))
        ids, why = B.select(data, "atp")
    # rank <= 500 (1-5, 7), plus 6 (a match this week) and 8 (in the Basel draw); never an 'x:' id
    assert ids == ["1", "2", "3", "4", "5", "6", "7", "8"]
    assert why["5"] == "rank" and why["6"] == "week" and why["8"] == "week"


def test_selection_needs_an_active_player_once_the_index_has_last_match_dates(tmp_path):
    """1 Nov 2026: players_index's rank falls back to a player's last-known rank, so ~1,300 long-retired players
    qualified ("Not on tour since 2019"). With the last-match column a rank of 500 or better counts only for a current
    official ranking (rankings.json, or the index's official flag) or a tour-level match in the last 52 weeks."""
    data = tree(tmp_path)
    last = {"1": "2026-10-29", "2": "2026-10-28", "3": "2025-11-01", "4": "2025-10-29", "5": "2026-09-01", "6": "2026-10-29",
            "7": "2019-05-01", "8": "2026-01-01", "x:old-p": "2026-10-01"}
    off = {"2": 1}
    write(data / "atp" / "players_index.json", {"ok": True, "players": {k: [v[0], v[1], v[2], v[3], last[k], off.get(k, 0)] for k, v in P.items()}})
    write(data / "atp" / "rankings.json", {"official": [[1, "1", 11000, 0], [499, "4", 400, 0], [700, "8", 50, 0]]})
    ids, why = B.select(data, "atp", NOW)
    # 1 (official), 2 (official flag), 3 (played 363 days ago), 4 (official, though its last tour-level match is 366
    # days old), 5 (played in September); 6 and 8 play this week; 7 (2019) is out; never an 'x:' id
    assert ids == ["1", "2", "3", "4", "5", "6", "8"]
    assert why["4"] == "rank" and why["8"] == "week" and "7" not in why
    write(data / "atp" / "rankings.json", {"official": []})
    assert "4" not in B.select(data, "atp", NOW)[0]                  # 366 days and no official ranking: out
    n = B.build(data, "atp", NOW)
    assert n["n"] == 6 and not (data / "follow" / "atp" / "7.json").exists()


def test_every_selected_player_gets_a_small_card(tmp_path):
    data = tree(tmp_path)
    out = B.build(data, "atp", NOW)
    assert out["ids"] == ["1", "2", "3", "4", "5", "6", "7", "8"] and out["max"] <= FL.MAX_BYTES
    for pid in out["ids"]:
        c = read(data, pid)
        assert c["k"] == f"ace:atp:{pid}" and c["team"]["href"] == f"#/atp/player/{pid}" and c["sport"] == "tennis"
        assert FL.card_bytes(c) <= FL.MAX_BYTES
    c = read(data, "1")
    assert c["team"]["short"] == "Ace" and c["team"]["league"] == "ATP"
    assert c["now"]["standing"]["text"] == "No. 1 in the ATP rankings · 11,000 pts" and c["now"]["rating"]["rank"] == 1
    assert c["now"]["record"] == "12–1"
    # the profile: serve and return percentiles from this season's catalogue
    assert c["profile"]["strong"][0]["label"] == "Serve rating" and len(c["profile"]["weak"]) == 2
    assert 3 <= len(c["facts"]) <= 5
    # a player not on tour for years: an honest off-season card, no form, no chances
    g = read(data, "7")
    assert g["phase"] == "offseason" and "form" not in g["now"] and "chances" not in g and g["next_note"] == "Not on tour since 2019."


def test_no_look_ahead_and_the_chances(tmp_path):
    data = tree(tmp_path)
    B.build(data, "atp", NOW)
    c = read(data, "1")
    # the loss to 4 yesterday is merged in from the index; the loss to 5 stamped after the clock and the career
    # file's future result are not read
    assert c["last"]["id"] == "basel-2026-R16-1-4" and c["last"]["res"] == "L" and c["last"]["score"] == [0, 2]
    assert c["last"]["p"] == 0.75 and c["now"]["form"] == "WWWWL" and c["now"].get("streak") is None
    # the next match is tomorrow's; the one that started an hour ago is not next for 2 or 3
    assert [g["id"] for g in c["next"]] == ["basel-2026-QF-1-6"] and c["next"][0]["p"] == 0.81 and c["next"][0]["mkt"] == 0.78
    assert c["next"][0]["opp"]["name"] == "Far" and c["next"][0]["comp"] == "Basel · quarter-final"
    assert "next" not in read(data, "2")
    # chances: the Basel title, the year-end No. 1 (open) last; Finals at 100% kept, never a "clinched"
    keys = [x["key"] for x in c["chances"]]
    assert keys[-1] == "year_end_no1" and "p_event" in keys and "finals_qual" in keys
    yn = [x for x in c["chances"] if x["key"] == "year_end_no1"][0]
    assert yn["p"] == 0.3 and yn["d7"] == -0.2
    # the 7-day Finals change for 2: 0.9 now (race.json today) against 0.6 eight days ago, never the later 0.0
    f2 = [x for x in read(data, "2")["chances"] if x["key"] == "finals_qual"][0]
    assert f2["p"] == 0.9 and f2["d7"] == 0.3
    texts = " ".join(f["text"] for f in c["facts"])
    assert "simulated seasons" in texts and "clinched" not in texts
    assert all(" have " not in f["text"] and " are " not in f["text"][:20] for f in c["facts"])


def test_facts_name_the_player_in_the_singular(tmp_path):
    data = tree(tmp_path)
    B.build(data, "atp", NOW)
    kinds = {f["kind"]: f["text"] for f in read(data, "1")["facts"]}
    assert set(kinds) <= set(FL.KINDS)
    assert kinds.get("best_record") == "4 titles in 2026, the most on the ATP Tour."
    two = {f["kind"]: f["text"] for f in read(data, "2")["facts"]}
    assert "swing" in two and two["swing"] == "Finals chance up 30 points to 90% this week."
