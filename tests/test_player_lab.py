"""
Advanced player metrics, the Player lab payload and the match page's lineup
order: derived ratios are computed from the season totals, defending is
possession-adjusted per match, the lab file is column-oriented and consistent,
and starters keep the source's order within a line so formations can be drawn.
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


def test_the_lab_payload_is_consistent(tmp_path) -> None:
    import build_site_global as g

    players = aggregate_players(_store(), registry={})
    entries = [{"slug": "premier-league", "name": "Premier League", "kind": "league", "ok": True, "_players": players,
                "_teams": {"Home": {"slug": "home"}}},
               {"slug": "empty-cup", "name": "Empty", "kind": "cup", "ok": True, "_players": [], "_teams": {}}]
    n = g.build_lab(tmp_path, entries, {"premier-league": "EPL"}, {"premier-league": 1.1})
    lab = json.loads((tmp_path / "players_lab.json").read_text(encoding="utf-8"))
    assert n == len(lab["rows"]) == 5                                  # the 20-minute sub is under the floor
    assert set(lab["comps"]) == {"premier-league"} and lab["comps"]["premier-league"]["factor"] == 1.1
    assert all(len(r) == len(lab["fields"]) for r in lab["rows"])
    f = {k: i for i, k in enumerate(lab["fields"])}
    assert {"player_id", "name", "team", "position", "minutes", "comp", "team_slug", "padj_tkl_int_90", "finishing"} <= set(f)
    assert {m["key"] for m in lab["metrics"]} == set(lab["fields"][f["team_slug"] + 1:])
    st = next(r for r in lab["rows"] if r[f["name"]] == "Striker")
    assert st[f["comp"]] == "premier-league" and st[f["team_slug"]] == "home" and st[f["ga_90"]] == 2.0


def test_calendar_windows_merge_competitions_and_keep_the_club(tmp_path) -> None:
    """A player's window line spans competitions; his club is the latest club, never his national team."""
    from datetime import datetime, timezone

    import build_site_global as g

    league = _store()                                                  # two Home matches, 2 and 1 Sept
    intl = {"matches": {"9": {"home": "Norway", "away": "Italy", "hs": 3, "as": 0, "status": "finished", "date": "2026-09-09T18:00:00Z"}},
            "lineups": {"9": {"30": _player("Striker", "Norway", "F", goals=2, expectedGoals=1.5, totalShots=5)}},
            "team_stats": {}, "players": {}, "incidents": {}, "shots": {}}
    old = {"matches": {"5": {"home": "Home", "away": "Away", "hs": 1, "as": 1, "status": "finished", "date": "2025-03-01T15:00:00Z"}},
           "lineups": {"5": {"30": _player("Striker", "Home", "F", goals=1)}}, "team_stats": {}, "players": {}, "incidents": {}, "shots": {}}
    for slug, st in (("premier-league", league), ("world-cup", intl), ("old-cup", old)):
        (tmp_path / slug).mkdir()
        (tmp_path / slug / "store.json").write_text(json.dumps(st), encoding="utf-8")
    entries = [{"slug": "premier-league", "name": "Premier League", "kind": "league", "_teams": {"Home": {"slug": "home"}}},
               {"slug": "world-cup", "name": "World Cup", "kind": "cup", "family": "international", "_teams": {}},
               {"slug": "old-cup", "name": "Old Cup", "kind": "cup", "family": "cup", "_teams": {}}]
    out = g.build_lab_windows(tmp_path, entries, {"premier-league": "EPL", "world-cup": "World Cup"}, {"premier-league": 1.2},
                              now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    assert set(out) == {"365", "ytd"}
    lab = json.loads((tmp_path / "players_lab_365.json").read_text(encoding="utf-8"))
    f = {k: i for i, k in enumerate(lab["fields"])}
    st = next(r for r in lab["rows"] if r[f["name"]] == "Striker")
    assert st[f["minutes"]] == 270 and st[f["team"]] == "Home"             # 2 league + 1 international, club kept
    assert st[f["comp"]] == "premier-league" and st[f["mix"]].startswith("EPL 180'")
    assert st[f["factor"]] == pytest.approx((1.2 * 180 + 1.0 * 90) / 270, abs=1e-3)
    assert st[f["goals_90"]] == pytest.approx(4 / 3, abs=1e-3)              # the March 2025 match is outside the window
    assert lab["window"] == {"tag": "365", "label": "Last 12 months", "start": "2025-09-30", "end": "2026-09-30"}
    assert lab["comps"]["premier-league"]["first_detail"] == "2026-09-01"


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
