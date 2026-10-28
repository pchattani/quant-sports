"""
Advanced player metrics, the one-row-per-person lab payloads and the match page's
lineup order: derived ratios are computed from the season totals, defending is
possession-adjusted per match, a person is one row in every view (window x scope)
and his duplicate ids fold into one, and starters keep the source's order within a
line so formations can be drawn.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from oddsmarkets.football.analytics.matches import match_details  # noqa: E402
from oddsmarkets.football.analytics.players import METRICS, aggregate_players  # noqa: E402

ADVANCED = ["npxg_xa_90", "ga_90", "finishing", "placement", "xa_per_kp", "shot_creation_90", "prog_actions_90",
            "def_actions_90", "padj_tkl_int_90", "ball_wins_90", "duels_90", "aerials_90", "loss_per_100"]


def _player(name, team, pos, sub=False, **stats):
    base = {"minutesPlayed": 90, "rating": 7.0}
    base.update(stats)
    return {"n": name, "t": team, "p": pos, "sub": sub, "s": base}


def _store() -> dict:
    # Match 1: Home had 70% of the ball; match 2: 30%. The midfielder makes 4
    # tackles + interceptions in each.
    lineups, sheets, matches = {}, {}, {}
    for gid, poss in (("1", 70), ("2", 30)):
        matches[gid] = {"home": "Home", "away": "Away", "hs": 1, "as": 0, "status": "finished", "date": f"2026-09-0{gid}T15:00:00Z"}
        sheets[gid] = {"home": {"ballPossession": poss}, "away": {"ballPossession": 100 - poss}}
        lineups[gid] = {
            "10": _player("Keeper", "Home", "G", saves=2),
            "11": _player("Right Back", "Home", "D", totalTackle=1),
            "12": _player("Left Back", "Home", "D"),
            "20": _player("Midfielder", "Home", "M", totalTackle=3, wonTackle=2, interceptionWon=1, ballRecovery=5,
                          touches=60, possessionLostCtrl=6, duelWon=5, duelLost=3, aerialWon=1, aerialLost=1,
                          progressiveBallCarriesCount=2, wonContest=1, keyPass=2, expectedAssists=0.3),
            "30": _player("Striker", "Home", "F", goals=1, expectedGoals=0.6, expectedGoalsOnTarget=0.9,
                          totalShots=4, onTargetScoringAttempt=2, keyPass=1, expectedAssists=0.1, goalAssist=1),
            "31": _player("Sub", "Home", "F", sub=True, minutesPlayed=10),
        }
    return {"matches": matches, "lineups": lineups, "team_stats": sheets, "players": {}, "shots": {}, "incidents": {}}


def test_advanced_metrics_are_catalogued_and_computed() -> None:
    keys = {m["key"] for m in METRICS if m["group"] == "Advanced"}
    assert set(ADVANCED) == keys
    rows = {r["name"]: r for r in aggregate_players(_store(), registry={})}
    st, mid = rows["Striker"], rows["Midfielder"]
    assert all(k in st for k in ADVANCED)
    assert st["ga_90"] == pytest.approx(2.0)                          # 2 goals + 2 assists in 180'
    assert st["npxg_xa_90"] == pytest.approx((1.2 + 0.2) / 2)
    assert st["finishing"] == pytest.approx((2 - 1.2) / 8, abs=1e-3)   # npG − npxG per non-penalty shot
    assert st["placement"] == pytest.approx((1.8 - 1.2) / 8, abs=1e-3)
    assert st["shot_creation_90"] == pytest.approx((8 + 2) / 2)
    assert mid["xa_per_kp"] == pytest.approx(0.6 / 4)
    assert mid["def_actions_90"] == pytest.approx(4.0)
    assert mid["ball_wins_90"] == pytest.approx((2 + 1 + 5))
    assert mid["duels_90"] == pytest.approx(8.0) and mid["aerials_90"] == pytest.approx(2.0)
    assert mid["prog_actions_90"] == pytest.approx(3.0)
    assert mid["loss_per_100"] == pytest.approx(10.0)
    assert rows["Keeper"]["finishing"] is None and rows["Keeper"]["xa_per_kp"] is None


def test_defending_is_possession_adjusted_per_match() -> None:
    mid = next(r for r in aggregate_players(_store(), registry={}) if r["name"] == "Midfielder")
    # 70% possession: opponent 30% -> ×50/30; 30% possession: opponent 70% -> ×50/70.
    expected = (4 * 50 / 30 + 4 * 50 / 70) / 2
    assert mid["padj_tkl_int_90"] == pytest.approx(expected, abs=1e-3)
    store = _store()
    store["team_stats"] = {}                                           # no sheets: unadjusted
    mid = next(r for r in aggregate_players(store, registry={}) if r["name"] == "Midfielder")
    assert mid["padj_tkl_int_90"] == pytest.approx(4.0)


def test_lineups_keep_the_source_order_within_a_line() -> None:
    out = match_details(_store(), registry={})["1"]["lineups"]["home"]
    assert [e["n"] for e in out] == ["Keeper", "Right Back", "Left Back", "Midfielder", "Striker", "Sub"]
    mid = next(e for e in out if e["n"] == "Midfielder")
    assert mid["pl"] == 6 and mid["pc"] == 2


def _lines(today=None):
    from datetime import datetime, timezone

    from oddsmarkets.football.analytics.people_lines import PeopleLines

    comps = {"premier-league": {"name": "Premier League", "short": "EPL", "kind": "league", "scope": "club"},
             "champions-league": {"name": "Champions League", "short": "UCL", "kind": "continental_club", "scope": "club"},
             "world-cup": {"name": "World Cup", "short": "World Cup", "kind": "international", "scope": "international"},
             "mls": {"name": "MLS", "short": "MLS", "kind": "league", "scope": "club"}}
    return PeopleLines(comps, today=today or datetime(2026, 9, 30, tzinfo=timezone.utc), intl_split_month=8)


def _read(path):
    d = json.loads(path.read_text(encoding="utf-8"))
    f = {k: i for i, k in enumerate(d["fields"])}
    return d, f, {r[f["player_id"]]: r for r in d["rows"]}


def test_a_one_competition_line_equals_the_competition_page(tmp_path) -> None:
    """The consolidated line of one competition is the competition's own season line (same arithmetic)."""
    store = _store()
    for m in store["matches"].values():
        m["season_id"] = 2
    pl = _lines()
    pl.add_store("premier-league", store, era_of=lambda m: "2026/27")
    pl.finish(tmp_path, frames={pid: "split" for pid in ("10", "11", "12", "20", "30", "31")})
    ref = {r["player_id"]: r for r in aggregate_players(store, registry={})}
    d, f, rows = _read(tmp_path / "lab" / "season" / "premier-league.json")
    assert set(rows) == {"10", "11", "12", "20", "30"}                  # the 20-minute sub is under the floor
    for pid, r in rows.items():
        for k in ("minutes", "matches", "goals_90", "npxg_xa_90", "padj_tkl_int_90", "pass_pct", "rating", "finishing", "loss_per_100"):
            assert r[f[k]] == (None if ref[pid].get(k) is None else round(float(ref[pid][k]), 3)), (pid, k)
    assert d["floor"] >= 90 and d["window"] == "season" and d["scope"] == "premier-league"
    idx = json.loads((tmp_path / "lab" / "index.json").read_text(encoding="utf-8"))
    assert idx["fields"] == d["fields"] and idx["scopes"]["season"]["all"]["n"] == 5
    assert {m["key"] for m in idx["metrics"]} == set(d["fields"][d["fields"].index("comp") + 1:])


def test_one_row_per_person_in_every_scope(tmp_path) -> None:
    """A player in a league, a European cup and a World Cup qualifier is one row per view; the scope picks what it sums."""
    league, cup = _store(), _store()
    for m in league["matches"].values():
        m["season_id"] = 2
    cup["matches"] = {"7": {**league["matches"]["1"], "date": "2026-09-16T19:00:00Z", "season_id": 9}}
    cup["lineups"] = {"7": {"30": _player("Striker", "Home", "F", goals=2, expectedGoals=1.1, totalShots=3)}}
    cup["team_stats"] = {}
    intl = {"matches": {"9": {"home": "Norway", "away": "Italy", "home_id": 4705, "away_id": 4707, "hs": 3, "as": 0,
                              "status": "finished", "date": "2026-09-09T18:00:00Z", "season_id": 5}},
            "lineups": {"9": {"30": _player("Striker", "Norway", "F", goals=1, expectedGoals=0.5, totalShots=2)}},
            "team_stats": {}, "players": {}, "incidents": {}, "shots": {}}
    for st in (league, cup):
        for m in st["matches"].values():
            m["home_id"], m["away_id"] = 17, 18
    pl = _lines()
    pl.add_store("premier-league", league, era_of=lambda m: "2026/27")
    pl.add_store("champions-league", cup, era_of=lambda m: "2026/27")
    pl.add_store("world-cup", intl, era_of=lambda m: "2026")
    (tmp_path / "players_lab.json").write_text("{}", encoding="utf-8")
    (tmp_path / "players_global.json").write_text("{}", encoding="utf-8")
    pl.finish(tmp_path, frames={"30": "split"}, people={"30": {"name": "Erling Striker", "dob": "2000-07-21"}},
              club_of={"30": {"tid": 17, "name": "Manchester City"}},
              clubs={"17": {"name": "Manchester City"}, "4705": {"name": "Norway"}}, factors={"premier-league": 1.2})
    lab = tmp_path / "lab" / "season"
    _d, f, allr = _read(lab / "all.json")
    _d, _f, club = _read(lab / "club.json")
    _d, _f, nat = _read(lab / "intl.json")
    _d, _f, ucl = _read(lab / "champions-league.json")
    st = allr["30"]
    assert st[f["name"]] == "Erling Striker" and st[f["age"]] == 26
    assert st[f["minutes"]] == 360 and st[f["matches"]] == 4                          # 2 league + 1 cup + 1 qualifier
    assert st[f["team"]] == "Manchester City" and st[f["tid"]] == 17 and st[f["comp"]] == "premier-league"
    assert st[f["goals_90"]] == pytest.approx(5 / 4) and st[f["mix"]] == "EPL 180' · UCL 90' · World Cup 90'"
    assert st[f["factor"]] == pytest.approx((1.2 * 180 + 90 + 90) / 360, abs=1e-4)
    assert club["30"][f["minutes"]] == 270 and club["30"][f["goals_90"]] == pytest.approx(4 / 3, abs=1e-3)
    assert nat["30"][f["minutes"]] == 90 and nat["30"][f["team"]] == "Norway" and nat["30"][f["tid"]] == 4705
    assert ucl["30"][f["minutes"]] == 90 and set(ucl) == {"30"}
    assert not (tmp_path / "players_lab.json").exists() and not (tmp_path / "players_global.json").exists()
    board = json.loads((tmp_path / "lab" / "leaders.json").read_text(encoding="utf-8"))["scopes"]
    assert [r["id"] for r in board["all"]["goals"]][:1] == ["30"] and board["all"]["goals"][0]["value"] == 5
    assert board["intl"]["goals"][0]["value"] == 1


def test_seasons_follow_the_players_own_frame(tmp_path) -> None:
    """A July international closes a European's season and is in a Brazilian's current one."""
    intl = {"matches": {"9": {"home": "Brazil", "away": "Norway", "hs": 1, "as": 1, "status": "finished",
                              "date": "2026-07-10T18:00:00Z", "season_id": 5}},
            "lineups": {"9": {"1": _player("European", "Norway", "F"), "2": _player("Brazilian", "Brazil", "F")}},
            "team_stats": {}, "players": {}, "incidents": {}, "shots": {}}
    old = {"matches": {"5": {"home": "Home", "away": "Away", "hs": 1, "as": 1, "status": "finished",
                             "date": "2024-03-01T15:00:00Z", "season_id": 1}},
           "lineups": {"5": {"1": _player("European", "Home", "F")}}, "team_stats": {}, "players": {}, "incidents": {}, "shots": {}}
    pl = _lines()
    pl.add_store("world-cup", intl, era_of=lambda m: "2026")
    pl.add_store("premier-league", old, era_of=lambda m: "2023/24")             # two seasons back: in no view
    pl.finish(tmp_path, frames={"1": "split", "2": "calendar"})
    _d, _f, now = _read(tmp_path / "lab" / "season" / "all.json")
    _d, _f, last = _read(tmp_path / "lab" / "last" / "all.json")
    _d, _f, y365 = _read(tmp_path / "lab" / "365" / "all.json")
    assert set(now) == {"2"} and set(last) == {"1"} and set(y365) == {"1", "2"}
    idx = json.loads((tmp_path / "lab" / "index.json").read_text(encoding="utf-8"))
    w = {x["key"]: x for x in idx["windows"]}
    assert w["season"]["eras"] == {"split": "2026/27", "calendar": "2026"} and w["last"]["eras"] == {"split": "2025/26", "calendar": "2025"}
    assert w["365"]["start"] == "2025-09-30" and w["ytd"]["start"] == "2026-01-01"


def test_duplicate_ids_merge_only_on_name_birth_date_and_nationality() -> None:
    from oddsmarkets.football.analytics.unified import same_person_aliases

    people = {"1097368": {"name": "Luis Gabriel Rey", "dob": "2002-09-14", "nat": "MEX"},
              "1097364": {"name": "Luis Gabriel Rey", "dob": "2002-09-14", "nat": "MEX"},
              "1139870": {"name": "Omar Ali", "dob": "1992-10-10", "nat": "QAT"},
              "992928": {"name": "Omar Ali", "dob": "1992-10-10", "nat": "GHA"},           # one birth date, two countries
              "5": {"name": "Rey", "dob": "2002-09-14", "nat": "MEX"},                      # not the exact name
              "6": {"name": "Luis Gabriel Rey", "nat": "MEX"}}                               # no birth date: never merged
    out = same_person_aliases(people, {"1097368": (1232, 14, 0), "1097364": (0, 0, 0)})
    assert out == {"1097364": "1097368"}
    # Without minutes the lower id is kept.
    assert same_person_aliases(people) == {"1097368": "1097364"}


def test_merged_ids_sum_into_one_line(tmp_path) -> None:
    a, b = _store(), _store()
    b["matches"] = {"3": {**a["matches"]["1"], "date": "2026-09-20T15:00:00Z"}}
    b["lineups"] = {"3": {"99": _player("Striker", "Home", "F", goals=1)}}
    pl = _lines()
    pl.add_store("premier-league", a, era_of=lambda m: "2026/27")
    pl.add_store("mls", b, era_of=lambda m: "2026")
    pl.merge_aliases({"99": "30"})
    pl.finish(tmp_path, frames={"30": "split"})
    _d, f, rows = _read(tmp_path / "lab" / "365" / "all.json")
    assert "99" not in rows and rows["30"][f["minutes"]] == 270 and rows["30"][f["goals_90"]] == pytest.approx(1.0)


def test_detail_queue_backfills_the_whole_previous_season() -> None:
    import importlib
    from datetime import datetime, timedelta, timezone

    fetcher = importlib.import_module("fetch_sofascore_leagues")
    now = datetime.now(timezone.utc)
    d = lambda days: (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    store = {"meta": {"season_id": 2}, "lineups": {"c2": {}}, "team_stats": {}, "matches": {
        "c1": {"status": "finished", "season_id": 2, "date": d(3), "stage": "league"},
        "c2": {"status": "finished", "season_id": 2, "date": d(10), "stage": "league"},         # has detail
        "p1": {"status": "finished", "season_id": 1, "date": d(120), "stage": "league"},
        "p2": {"status": "finished", "season_id": 1, "date": d(200), "stage": "league"},
        "p3": {"status": "finished", "season_id": 1, "date": d(400), "stage": "league"},        # over a year ago: still wanted
        "p4": {"status": "finished", "season_id": 1, "date": d(150), "stage": "qualifying"},    # no followed club in it
        "p5": {"status": "finished", "season_id": 1, "date": d(160), "stage": "qualifying", "home": "Followed"},
    }}
    q = fetcher.detail_queue(store, refresh=False, past_tier=fetcher.TIER_LEAGUE_PAST, club_followed={"Followed"})
    assert [g for g, _ in q] == ["c1", "p1", "p5", "p2", "p3"]
    assert [m["_tier"] for _, m in q] == [fetcher.TIER_NEW] + [fetcher.TIER_LEAGUE_PAST] * 4


def test_a_match_without_lineups_is_retried_then_given_up_on() -> None:
    import importlib
    from datetime import datetime, timedelta, timezone

    fetcher = importlib.import_module("fetch_sofascore_leagues")
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    store = {"meta": {"season_id": 2}, "lineups": {}, "matches": {
        "m": {"status": "finished", "season_id": 2, "date": "2026-10-10T18:00:00Z", "stage": "league"}}}
    queued = lambda when: [g for g, _ in fetcher.detail_queue(store, refresh=False, now=when)]  # noqa: E731
    assert queued(now) == ["m"]
    fetcher.record_miss(store, "m", "no-lineups", now)
    assert queued(now) == [] and queued(now + timedelta(days=1)) == ["m"]
    fetcher.record_miss(store, "m", "no-lineups", now)
    assert queued(now + timedelta(days=6)) == [] and queued(now + timedelta(days=7)) == ["m"]
    fetcher.record_miss(store, "m", "no-stats", now)
    assert store["detail_missing"]["m"]["final"] is True and queued(now + timedelta(days=400)) == []


def test_detail_order_is_by_tier_then_round_robin() -> None:
    import importlib

    fetcher = importlib.import_module("fetch_sofascore_leagues")
    T = fetcher
    queues = {"a": [("a1", {"_tier": T.TIER_NEW}), ("a2", {"_tier": T.TIER_LEAGUE_PAST}), ("a3", {"_tier": T.TIER_LEAGUE_PAST})],
              "b": [("b1", {"_tier": T.TIER_OTHER_PAST})],
              "c": [("c1", {"_tier": T.TIER_NEW}), ("c2", {"_tier": T.TIER_NEW}), ("c3", {"_tier": T.TIER_LEAGUE_PAST})]}
    assert [g for _s, g, _m in fetcher.interleave(queues)] == ["a1", "c1", "c2", "a2", "c3", "a3", "b1"]


def test_season_pages_ignore_backfilled_detail_from_last_season() -> None:
    from scripts.build_site_all import _season_view

    store = _store()
    store["meta"] = {"season_id": 2}
    store["matches"]["1"]["season_id"] = 2
    store["matches"]["2"]["season_id"] = 1                              # backfilled for the calendar views
    view = _season_view(store)
    assert set(view["lineups"]) == {"1"} and set(view["team_stats"]) == {"1"}
    assert set(store["lineups"]) == {"1", "2"}                          # the store itself is untouched
    st = next(r for r in aggregate_players(view, registry={}) if r["name"] == "Striker")
    assert st["minutes"] == 90 and st["goals"] == 1
    store["matches"]["2"]["season_id"] = 2
    assert _season_view(store) is store                                  # nothing to filter: no copy


def _value_rows(rows: list[tuple]) -> object:
    """A stand-in for value.Rows: (pid, slug, season key, ISO date, minutes, GAR) per player-match."""
    from datetime import date
    from types import SimpleNamespace

    import numpy as np

    comps = sorted({r[1] for r in rows})
    sids = sorted({r[2] for r in rows})
    ints = lambda xs: np.array(xs, dtype=np.int64)  # noqa: E731
    R = SimpleNamespace(pid=ints([int(r[0]) for r in rows]), comp=ints([comps.index(r[1]) for r in rows]),
                        sid=ints([sids.index(r[2]) for r in rows]), day=ints([date.fromisoformat(r[3]).toordinal() for r in rows]),
                        mins=np.array([float(r[4]) for r in rows]), comps=comps, sids=sids)
    return R, np.array([float(r[5]) for r in rows])


def test_value_views_tag_each_match_as_the_lab_does() -> None:
    """The value model's GAR by Lab window (28 Oct 2026): a club edition counts in its season, a national-team match by
    date in the person's frame, so a qualifying campaign that spans two seasons splits between them, a July World Cup
    closes a European's season, and an international line never takes club matches (Haaland's international line had
    repeated his club GAR)."""
    from datetime import datetime, timezone

    from oddsmarkets.football.analytics import value_fields as VF
    from oddsmarkets.football.analytics.people_lines import PeopleLines

    comps = {"premier-league": {"scope": "club"}, "world-cup": {"scope": "international"},
             "nations-league": {"scope": "international"}, "wc-qual-uefa": {"scope": "international"}}
    pl = PeopleLines(comps, today=datetime(2026, 9, 30, tzinfo=timezone.utc), intl_split_month=8)
    pl.merge_aliases({"99": "30"})
    R, gar = _value_rows([
        ("30", "premier-league", "26", "2026-09-01", 90, 0.5), ("30", "premier-league", "26", "2026-09-15", 90, 0.3),
        ("99", "premier-league", "26", "2026-09-20", 90, 0.1),                                  # a duplicate id of 30
        ("30", "premier-league", "25", "2026-03-01", 90, 0.2),
        ("30", "world-cup", "wc", "2026-07-01", 90, 0.4),                                       # the summer: 2025/26 for a European
        ("30", "nations-league", "nl", "2026-09-07", 90, -0.1),
        ("30", "wc-qual-uefa", "q", "2025-10-10", 90, 0.25), ("30", "wc-qual-uefa", "q", "2026-09-05", 90, 0.05),
        ("30", "premier-league", "23", "2023-09-01", 90, 9.0),                                  # three seasons back: no window
        ("30", "serie-a", "26", "2026-09-02", 90, 9.0),                                          # not a Lab competition
        ("40", "world-cup", "wc", "2026-07-01", 90, 0.7), ("40", "nations-league", "nl", "2026-09-07", 90, 0.1),
    ])
    era = {("premier-league", "26"): "2026/27", ("premier-league", "25"): "2025/26", ("premier-league", "23"): "2023/24"}
    out = pl.value_views(R, gar, lambda slug, key: era.get((slug, key)), {"30": "split", "40": "calendar"})
    w = out["windows"]
    assert set(out["intl"]) == {"world-cup", "nations-league", "wc-qual-uefa"}
    assert w["season"]["30"] == {"premier-league": [0.9, 270.0], "nations-league": [-0.1, 90.0], "wc-qual-uefa": [0.05, 90.0]}
    assert w["last"]["30"] == {"premier-league": [0.2, 90.0], "world-cup": [0.4, 90.0], "wc-qual-uefa": [0.25, 90.0]}
    assert w["365"]["30"]["wc-qual-uefa"] == [0.3, 180.0] and w["365"]["30"]["premier-league"] == [1.1, 360.0]
    assert w["ytd"]["30"]["wc-qual-uefa"] == [0.05, 90.0]
    assert "99" not in w["season"] and "serie-a" not in w["365"]["30"]
    # a calendar-frame player: the July World Cup and the September Nations League are both his 2026
    assert w["season"]["40"] == {"world-cup": [0.7, 90.0], "nations-league": [0.1, 90.0]} and "40" not in w["last"]
    intl = set(out["intl"])
    s_club = VF.windowed(w["season"]["30"], "club", intl, 270)
    s_intl = VF.windowed(w["season"]["30"], "intl", intl, 180)
    l_club = VF.windowed(w["last"]["30"], "club", intl, 90)
    l_intl = VF.windowed(w["last"]["30"], "intl", intl, 180)
    assert s_club == (0.3, 0.9) and s_intl == (round(90 * -0.05 / 180, 3), -0.05)
    assert l_club == (0.2, 0.2) and l_intl == (0.325, 0.65) and l_intl != l_club
    # GAR/90 reconciles with the line's own minutes
    assert abs(s_intl[0] * 180 / 90 - s_intl[1]) < 0.01 and abs(l_intl[0] * 180 / 90 - l_intl[1]) < 0.01
