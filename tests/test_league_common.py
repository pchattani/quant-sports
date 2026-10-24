"""oddsmarkets/common/league.py: the league pages' race log, movers with reasons, the games that matter, schedule
strength, profiles and chips, luck and tiers."""
from __future__ import annotations

from datetime import datetime, timezone

from oddsmarkets.common import league as LG

NOW = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)


def test_race_log_keeps_one_snapshot_a_day_and_never_trims():
    s = {}
    for d in range(1, 25):
        s = LG.roll_race(s, f"2026-10-{d:02d}", {"p_playoffs": {"A": 0.5 + d / 100}})
    assert len(s["p_playoffs"]) == 24                          # the whole season, unlike the 10-day chance log
    s2 = LG.roll_race(s, "2026-10-24", {"p_playoffs": {"A": 0.9}})
    assert s2["p_playoffs"]["2026-10-24"] == {"A": 0.9} and len(s2["p_playoffs"]) == 24
    assert s2[LG.META]["live_from"] == "2026-10-01"


def test_a_rebuilt_snapshot_never_replaces_a_live_one_and_is_listed():
    s = LG.roll_race({}, "2026-10-20", {"p_playoffs": {"A": 0.6}})
    s = LG.add_rebuilt(s, "2026-10-20", {"p_playoffs": {"A": 0.1}}, n=2000)
    assert s["p_playoffs"]["2026-10-20"] == {"A": 0.6} and s[LG.META]["rebuilt"] == []
    s = LG.add_rebuilt(s, "2026-10-10", {"p_playoffs": {"A": 0.4}}, n=2000)
    assert s[LG.META]["rebuilt"] == ["2026-10-10"] and s[LG.META]["n"] == 2000
    # a live build on a rebuilt day takes it over
    s = LG.roll_race(s, "2026-10-10", {"p_playoffs": {"A": 0.45}})
    assert s[LG.META]["rebuilt"] == [] and s["p_playoffs"]["2026-10-10"] == {"A": 0.45}
    h = LG.history_summary(s, ["p_playoffs"])
    assert h["first"] == "2026-10-10" and h["live_from"] == "2026-10-10" and h["days"] == 2


def test_rebuild_dates_stop_before_live_tracking():
    ds = LG.rebuild_dates("2026-10-01", "2026-10-10", 3, also=["2026-10-05", "2026-10-12"])
    assert ds == ["2026-10-01", "2026-10-04", "2026-10-05", "2026-10-07"]
    assert LG.rebuild_dates("2026-10-10", "2026-10-10", 3) == [] and LG.rebuild_dates(None, "2026-10-10", 3) == []


def test_backfill_respects_the_time_budget_and_skips_failures():
    t = [0.0]

    def clock():
        return t[0]

    def run(day):
        t[0] += 10
        return None if day == "2026-10-04" else {"p_playoffs": {"A": 0.5}}
    s, done = LG.backfill({}, ["2026-10-01", "2026-10-04", "2026-10-07", "2026-10-10"], run, budget_s=15, clock=clock)
    assert done == ["2026-10-01"]                               # 10 s, the failed date (20 s), then out of budget
    s, done = LG.backfill(s, ["2026-10-01", "2026-10-04", "2026-10-07"], run, budget_s=100, clock=clock)
    assert done == ["2026-10-07"] and sorted(s["p_playoffs"]) == ["2026-10-01", "2026-10-07"]


def test_merge_race_puts_back_lost_days_and_keeps_every_season():
    live = {"2026": {"p_playoffs": {"2026-10-01": {"A": 0.5}, "2026-10-02": {"A": 0.6}}, LG.META: {"rebuilt": ["2026-10-01"], "n": 2000}},
            "2025": {"p_playoffs": {"2025-10-01": {"A": 0.2}}}}
    new = {"2026": {"p_playoffs": {"2026-10-03": {"A": 0.7}}, LG.META: {"rebuilt": []}}}
    out, lost = LG.merge_race(live, new)
    assert lost == 3 and sorted(out["2026"]["p_playoffs"]) == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert out["2026"][LG.META]["rebuilt"] == ["2026-10-01"] and "2025" in out
    assert LG.merge_race(None, new) == (new, 0)


RES = [
    {"date": "2026-10-18", "home": "A", "away": "B", "hs": 4, "as": 1},
    {"date": "2026-10-19", "home": "C", "away": "A", "hs": 2, "as": 3, "ot": True},
    {"date": "2026-10-20", "home": "B", "away": "C", "hs": 1, "as": 2},
    {"date": "2026-10-21", "home": "D", "away": "B", "hs": 5, "as": 2},
    {"date": "2026-10-22", "home": "C", "away": "D", "hs": 0, "as": 3},
    {"date": "2026-10-10", "home": "A", "away": "D", "hs": 0, "as": 6},     # before the window
]


def test_team_window_and_records():
    r = LG.norm_results(RES)
    w = LG.team_window(r, "C", "2026-10-17")
    assert (w["w"], w["l"], w["otl"]) == (1, 1, 1) and LG.record_str(w, otl=True) == "1-1-1" and LG.record_str(w) == "1-1"
    assert LG.close_record(r, "A", 1) == [1, 0]                # the overtime win counts as close; 4-1 does not


def test_movers_name_their_reasons():
    seas = {"p_playoffs": {"2026-10-17": {"A": 0.40, "B": 0.60, "C": 0.5, "D": 0.5}}}
    cur = {"A": 0.55, "B": 0.40, "C": 0.5, "D": 0.6}
    mv = LG.movers(seas, "p_playoffs", cur, NOW, LG.norm_results(RES), lambda t: ["A", "B", "C", "D"],
                   {"A": "AAA", "B": "BBB", "C": "CCC", "D": "DDD"}, rating={"A": 0, "B": -1, "C": 1, "D": 0.5}, otl=True)
    up = {r["team"]: r for r in mv["up"]}
    down = {r["team"]: r for r in mv["down"]}
    assert up["A"]["why"][0] == "Went 2-0-0, beat CCC 3-2"     # the best win: the highest-rated opponent beaten
    assert down["B"]["why"][0] == "Went 0-3-0, lost to AAA 1-4"  # the worst loss: the weakest opponent (A rated 0 < D)
    assert mv["since"] == "2026-10-17" and mv["metric"] == "p_playoffs"
    wk = LG.mover_reasons("A", 0.1, "2026-10-19", "2026-10-24", LG.norm_results(RES), [], {}, weekly=True)
    assert wk == ["Beat C 3-2"]


def test_schedule_strength_and_ranks():
    sos = LG.schedule_strength([{"home": "A", "away": "B"}, {"home": "C", "away": "A"}], {"A": 0.0, "B": 1.0, "C": -1.0}, ["A", "B", "C"], hfa=0.1)
    assert sos["A"] == {"avg": round((1.0 - 0.1 + (-1.0 + 0.1)) / 2, 3), "n": 2, "home": 1}
    assert LG.ranks({"A": 2, "B": 5, "C": 2, "D": None}) == {"B": 1, "A": 2, "C": 2}
    assert LG.percentiles({"A": 1, "B": 2, "C": 3}) == {"A": 0, "B": 50, "C": 100}
    assert LG.percentiles({"A": 1, "B": 2, "C": 3}, higher_better=False)["A"] == 100


def test_matter_games_rank_measured_swings_first():
    up = [{"id": "g1", "start": "2026-10-25T00:00:00Z", "home": "A", "away": "B", "p_home": 0.6},
          {"id": "g2", "start": "2026-10-26T00:00:00Z", "home": "C", "away": "D", "p_home": 0.5},
          {"id": "g3", "start": "2026-11-05T00:00:00Z", "home": "A", "away": "C", "p_home": 0.5},   # outside the week
          {"id": "g4", "start": "2026-10-27T00:00:00Z", "home": "B", "away": "C", "p_home": 0.5}]
    nxt = {"A": {"game_id": "g1", "if_win": {"p": 0.7}, "if_loss": {"p": 0.6}},
           "B": {"game_id": "g1", "if_win": {"p": 0.5}, "if_loss": {"p": 0.45}},
           "C": {"game_id": "g2", "if_win": {"p": 0.5}, "if_loss": {"p": 0.2}}}
    rows = LG.matter_games(up, nxt, "p", NOW, sig=lambda g: (10.0, ["a play-off place in the balance"]))
    assert [r["id"] for r in rows] == ["g2", "g1", "g4"]
    assert rows[0]["swing"] == 0.3 and rows[1]["sides"]["A"] == [0.7, 0.6] and rows[2]["stakes"] == 10.0


SPEC = [{"id": "rating", "dir": "higher", "model": True},
        {"id": "off", "dir": "higher", "chip": "offence"},
        {"id": "def", "dir": "lower", "chip": "defence"},
        {"id": "pace", "dir": "higher", "style": True, "chip": "pace", "hi": "Fastest pace", "lo": "Slowest pace"}]


def _vals():
    return {t: {"rating": r, "off": o, "def": d, "pace": p} for t, r, o, d, p in [
        ("A", 5, 110, 100, 98), ("B", 3, 112, 108, 101), ("C", 0, 105, 104, 100), ("D", -2, 100, 103, 99), ("E", -6, 98, 112, 97)]}


def test_profile_hides_raw_rates_early_but_ranks_the_model():
    early = LG.profile(_vals(), SPEC, {t: 3 for t in "ABCDE"}, min_gp=10)
    assert set(early["A"]["pct"]) == {"rating"}
    full = LG.profile(_vals(), SPEC, {t: 12 for t in "ABCDE"}, min_gp=10)
    assert full["A"]["rank"]["def"] == 1 and full["E"]["pct"]["def"] == 0 and full["B"]["pct"]["off"] == 100


def test_chips_read_like_plain_english():
    prof = LG.profile(_vals(), SPEC, {t: 12 for t in "ABCDE"}, min_gp=10)
    a = LG.chips("A", prof, SPEC, 5, overall="rating")
    assert ["Best defence", "+"] in a and ["Top-3 offence", "+"] in a
    b = LG.chips("B", prof, SPEC, 5, overall="rating", sos_rank=1)
    assert ["Best offence", "+"] in b and ["Toughest schedule left", "s"] in b and ["Fastest pace", "s"] in b
    e = LG.chips("E", prof, SPEC, 5, overall="rating", luck={"flag": "lucky", "close_good": True})
    assert ["Worst offence", "-"] in e and ["Winning close games: luck?", "?"] in e and ["Slowest pace", "s"] in e
    # a decent team's weakest dimension at or under the 30th percentile is its weak spot
    prof["C"]["pct"].update({"off": 25, "def": 60}); prof["C"]["pct"]["rating"] = 60
    assert ["Offence is the weak spot", "-"] in LG.chips("C", prof, SPEC, 5, overall="rating")


def test_luck_flags_and_tiers():
    lk = LG.luck({"A": {"actual": 10, "expected": 7.0, "close": [5, 1]}, "B": {"actual": 4, "expected": 6.5, "close": [1, 4]},
                  "C": {"actual": 5, "expected": 5.4}}, threshold=2.0)
    assert lk["A"]["flag"] == "lucky" and lk["A"]["close_good"] and lk["B"]["flag"] == "unlucky" and lk["B"]["close_bad"]
    assert lk["C"]["flag"] is None
    assert round(LG.pythag(100, 100, 10, 2), 3) == 0.5
    tl = LG.tiers({"A": 0.95, "B": 0.8, "C": 0.5, "D": 0.1, "E": 0.01}, {"A": 0.3, "B": 0.03, "C": 0.01, "D": 0.0, "E": 0.0}, n=32)
    assert [(x["key"], x["teams"]) for x in tl] == [("contend", ["A"]), ("solid", ["B"]), ("bubble", ["C"]), ("long", ["D"]), ("rebuild", ["E"])]
    po = LG.tiers({"A": 1.0, "B": 1.0, "C": 0.0}, {"A": 0.6, "B": 0.0, "C": 0.0}, phase="postseason")
    assert [x["key"] for x in po] == ["alive", "out_po", "missed"]
    done = LG.tiers({"A": 1.0, "B": 1.0, "C": 0.0}, {"A": 1.0, "B": 0.0, "C": 0.0}, phase="complete")
    assert done[0] == {"key": "champion", "label": "Champions", "sub": "won the title", "teams": ["A"]}


def test_block_is_compact_and_carries_the_current_chances():
    prof = LG.profile(_vals(), SPEC, {t: 12 for t in "ABCDE"}, min_gp=10)
    blk = LG.block(now=NOW, phase="regular", metrics=[{"key": "p", "label": "Playoffs"}], current={"p": {"A": 0.91234}},
                   seas={"p": {"2026-10-24": {"A": 0.9}}}, movers_=None, games=[], race={"A": {"magic": 3}}, prof=prof, spec=SPEC,
                   chips_={"A": [["Best defence", "+"]]}, luck_={}, tiers_=[], quad=None, early=False, min_gp=10,
                   gp={"A": 12}, values=_vals())
    assert blk["current"] == {"p": {"A": 0.912}} and blk["teams"]["A"]["chips"] == [["Best defence", "+"]]
    assert blk["teams"]["A"]["vals"]["off"] == 110 and blk["history"]["live_from"] == "2026-10-24" and blk["v"] == 1
