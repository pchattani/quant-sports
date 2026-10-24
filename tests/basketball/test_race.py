"""oddsmarkets/basketball/analytics/race.py: the Hardwood's league block and race log on a small synthetic season."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.basketball.analytics import race as RC
from oddsmarkets.common import league as LG

NOW = datetime(2026, 12, 20, 15, 0, tzinfo=timezone.utc)
T = ["1", "2", "3", "4"]


def _season(phase="regular", done=False):
    rows = {"East": [], "West": []}
    for i, t in enumerate(T):
        conf = "East" if i < 2 else "West"
        rows[conf].append({"team": t, "w": 12 - 2 * i, "l": 4 + 2 * i, "division": "Atlantic" if conf == "East" else "Pacific"})
    sim = {}
    for i, t in enumerate(T):
        p = [0.95, 0.6, 0.4, 0.05][i] if not done else [1.0, 1.0, 0.0, 0.0][i]
        sim[t] = {"p_playoffs": p, "p_div": [0.8, 0.2, 0.6, 0.4][i], "p_title": [0.3, 0.1, 0.02, 0.0][i] if not done else [0.7, 0.3, 0, 0][i],
                  "magic": {"postseason": [5, 40, 60, 90][i]}, "tragic": {"postseason": [90, 60, 30, 3][i]},
                  "clinched": {"postseason": False}, "eliminated": {"postseason": False},
                  "next": {"game": "g9", "date": "2026-12-21", "opp": "2" if t == "1" else "1", "home": t == "1", "p_win": 0.6,
                           "if_win": {"p_playoffs": min(1, p + 0.03)}, "if_loss": {"p_playoffs": max(0, p - 0.04)}} if t in ("1", "2") else None}
    return {"ok": True, "league": "nba", "season": 2027, "phase": phase, "format": {"games": 82, "seeding": "conference"},
            "teams": {t: {"abbr": "T" + t, "colour": "#123456"} for t in T}, "standings": rows, "sim": {"n_sims": 400, "teams": sim},
            "ratings": {t: {"off": 112 - i, "def": 108 + i, "net": 4 - 2 * i, "pace": 99 + i} for i, t in enumerate(T)},
            "schedule_difficulty": {t: {"played": 0.1 * i, "remaining": -0.1 * i, "n_played": 16, "n_remaining": 66} for i, t in enumerate(T)}}


def _cards(done=False):
    cards = [{"id": "g1", "date": "2026-12-15T00:00:00Z", "status": "post", "stype": "reg", "home": "1", "away": "2", "hs": 110, "as": 108, "period": 5},
             {"id": "g2", "date": "2026-12-16T00:00:00Z", "status": "post", "stype": "reg", "home": "3", "away": "4", "hs": 120, "as": 100, "period": 4},
             {"id": "g3", "date": "2026-12-17T00:00:00Z", "status": "post", "stype": "reg", "home": "2", "away": "3", "hs": 99, "as": 101, "period": 4}]
    if not done:
        cards.append({"id": "g9", "date": "2026-12-21T00:30:00Z", "status": "pre", "stype": "reg", "home": "1", "away": "2", "model": {"p_home": 0.6}})
    return cards


def _teams():
    return {"teams": {t: {"values": {"model_net": 4 - 2 * i, "model_off": 112 - i, "model_def": 108 + i, "pace": 99 + i, "efg": 0.55 - 0.01 * i,
                                     "opp_efg": 0.52 + 0.01 * i, "tov_pct": 0.12 + 0.01 * i, "opp_tov_pct": 0.14, "orb_pct": 0.25, "drb_pct": 0.75,
                                     "fg3": 0.36, "opp_fg3": 0.35, "tpar": 0.4 + 0.02 * i, "ftr": 0.2, "mov": 5 - 3 * i}} for i, t in enumerate(T)}}


def test_in_season_block_and_live_log():
    log = {"2027": {"p_playoffs": {"2026-12-13": {"1": 0.8, "2": 0.7, "3": 0.4, "4": 0.1}}, LG.META: {"live_from": "2026-12-13", "rebuilt": []}}}
    blk, out = RC.build("nba", 2027, _season(), _teams(), _cards(), log, NOW)
    assert sorted(out["2027"]["p_playoffs"]) == ["2026-12-13", "2026-12-20"]
    assert [m["key"] for m in blk["metrics"]] == ["p_playoffs", "p_div", "p_title"] and blk["metrics"][2]["label"] == "NBA title"
    assert blk["race"]["1"]["magic"] == 5 and "magic" not in blk["race"]["4"]          # 90 is beyond the 64 games left
    assert blk["race"]["4"]["elim"] == 3
    assert blk["race"]["1"]["unit"] == "wins" and blk["race"]["1"]["sos"][1] == 1    # schedule_difficulty remaining: 0 is the hardest
    assert blk["games"][0]["id"] == "g9" and set(blk["games"][0]["sides"]) == {"1", "2"}
    assert blk["teams"]["1"]["pct"]["model_net"] == 100 and blk["profile"]["early"] is False
    assert blk["teams"]["1"]["luck"]["close"] == [1, 0]                               # the overtime win counts as close
    assert blk["movers"]["up"][0]["team"] == "1"
    assert blk["quad"]["x"] == "model_off" and blk["quad"]["flipY"]


def test_a_finished_season_rebuilds_its_regular_season_and_takes_no_flat_live_snapshot():
    calls = []

    def run(day):
        calls.append(day)
        return {"p_playoffs": {t: 0.5 for t in T}, "p_title": {t: 0.25 for t in T}}
    blk, out = RC.build("wnba", 2026, _season(phase="playoffs", done=True), _teams(), _cards(done=True), None, NOW, run_asof=run)
    s = out["2026"]
    assert calls[0] == "2026-12-15" and "2026-12-18" in calls                       # first day, and the day after the last
    assert s[LG.META].get("live_from") is None and set(s[LG.META]["rebuilt"]) == set(calls)
    assert blk["history"]["live_from"] is None and blk["movers"] is None and blk["notes"]["season_over"]
    assert [x["key"] for x in blk["tiers"]] == ["alive", "missed"]


def test_asof_runner_counts_results_before_the_day(monkeypatch):
    from oddsmarkets.basketball.models import season_sim as SS
    seen = {}

    def fake(league, season, n, seed, through):
        seen.update(league=league, through=through, n=n)
        return {"teams": {"1": {"p_playoffs": 0.5, "p_title": 0.1}}}
    monkeypatch.setattr(SS, "for_season", fake)
    assert RC.asof_runner("nba", 2027)("2026-11-01") == {"p_playoffs": {"1": 0.5}, "p_title": {"1": 0.1}}
    assert seen == {"league": "nba", "through": "2026-10-31", "n": RC.REBUILD_N}
