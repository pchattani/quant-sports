"""Valuation v2, transactions and trade ratings, the pick-value curve and the fantasy layer (analytics/valuation.py,
moves.py, fantasy.py, research/fantasy_backtest.py). Synthetic inputs only; no network."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.basketball.analytics import bio as BIO
from oddsmarkets.basketball.analytics import fantasy as FN
from oddsmarkets.basketball.analytics import moves as MV
from oddsmarkets.basketball.analytics import valuation as VV
from oddsmarkets.basketball.analytics import value as V

PRM = V.params_for("nba", pace=100.0, ppw=31.0)
FIT = {"aging": [[a, 0.5 if a < 25 else (0.0 if a < 30 else -0.5)] for a in range(19, 42)], "spread": {"s1": 1.5, "tau": 1.0},
       "surv": [2.5, -0.1, -0.05, 0.3, 0.5], "avail": 0.8, "min_cv": 0.25}


# ---------------------------------------------------------------------------------------------- bio

def test_age_and_season_age():
    assert BIO.age_at("2000-02-01", "2020-02-01") == pytest.approx(20.0, abs=0.01)
    assert BIO.season_age("nba", 2026, "2000-02-01") == pytest.approx(26.0, abs=0.01)
    assert BIO.season_age("wnba", 2026, "2000-07-01") == pytest.approx(26.0, abs=0.01)
    assert BIO.age_at(None, "2020-01-01") is None


def test_fill_dob_keeps_existing_and_fills_missing(monkeypatch):
    monkeypatch.setattr(BIO, "players", lambda lg: {"1": {"dob": "1990-01-01"}, "2": {"dob": "1991-01-01"}})
    out = BIO.fill_dob("nba", {"1": {"name": "a"}, "2": {"name": "b", "dob": "1999-09-09"}, "3": {"name": "c"}})
    assert out["1"]["dob"] == "1990-01-01" and out["2"]["dob"] == "1999-09-09" and "dob" not in out["3"]


# ---------------------------------------------------------------------------------------------- valuation v2

def _rows_by():
    """Synthetic seasons: players improve by 1.0 a season under 25, hold to 29, then lose 1.0 a season."""
    out = {}
    rng = np.random.default_rng(1)
    for s in range(2010, 2020):
        rows = []
        for i in range(120):
            age = 20 + (i % 18) + (s - 2010)
            base = 2.0 + (min(age, 25) - 25) * 1.0 - max(0, age - 29) * 1.0
            rows.append({"id": f"p{i}", "hpm": base + rng.normal(0, 0.3), "min": 1500.0, "gp": 70, "games": 82, "age": float(age),
                         "role": "G", "se": 1.0, "team": "1"})
        out[s] = rows
    return out


def test_aging_curve_recovers_the_shape():
    curve, info = VV.aging_curve(_rows_by())
    d = dict((a, v) for a, v in curve)
    assert info["n_pairs"] > 500
    assert d[22] > 0.3 and abs(d[27]) < 0.25 and d[33] < -0.3


def test_survival_fit_and_probability_monotone_in_age():
    rb = _rows_by()
    for s in rb:                                   # older players drop out next season
        rb[s] = [x for x in rb[s] if not (x["age"] > 34 and int(x["id"][1:]) % 2)]
    b, info = VV.survival_fit(rb, 2019)
    p_young = VV.p_survive(b, 24.0, 0.0, 1500.0)
    p_old = VV.p_survive(b, 37.0, 0.0, 1500.0)
    assert info["n"] > 200 and p_young > p_old


def test_project_discounts_floors_future_and_orders_band():
    slots = [{"games": 40, "avail": 0.8}] + [{"games": 82, "avail": 0.8}] * 3
    good = VV.project(5.0, 1.0, 34.0, 26.0, slots, FIT, PRM, seed=1)
    bad = VV.project(-4.0, 1.0, 20.0, 26.0, slots, FIT, PRM, seed=1)
    assert good["p10"] <= good["p50"] <= good["p90"]
    assert good["war"][1] > good["war"][0]          # a full season is worth more than half of one
    assert bad["war"][0] < 0 and all(w >= 0 for w in bad["war"][1:])   # future seasons floored at replacement
    disc = sum(VV.DISCOUNT ** k * w for k, w in enumerate(good["war"]))
    assert good["v"] == pytest.approx(disc)


def test_ageing_lowers_an_old_players_value():
    slots = [{"games": 82, "avail": 0.8}] * 4
    young = VV.project(3.0, 1.0, 30.0, 23.0, slots, FIT, PRM, seed=2)
    old = VV.project(3.0, 1.0, 30.0, 33.0, slots, FIT, PRM, seed=2)
    assert young["rates"][3] > old["rates"][3] and young["v"] > old["v"]


def test_positional_replacement_uses_the_next_tier_of_minutes():
    def P(pid, team, role, rate, mpg):
        return {"id": pid, "team": team, "role": role, "rate": rate, "mpg": mpg, "basis": "b"}
    lists = {}
    for t in ("A", "B", "C"):
        lists[t] = [P(f"{t}{i}", t, "G" if i % 2 else "B", 4.0 - i, 36.0 - 2 * i) for i in range(12)]
    minutes = {t: V.baseline_minutes(ps, PRM) for t, ps in lists.items()}
    pos = VV.positional_replacement(lists, minutes, "nba")
    assert set(pos) == {"G", "W", "B"}
    assert pos["G"]["repl"] < pos["G"]["top10"] and pos["W"]["repl"] == V.REPLACEMENT   # no wings: the league level


def test_availability_regresses_to_the_mean():
    assert VV.availability(0, 0, FIT) == pytest.approx(0.8)
    assert VV.availability(82, 82, FIT) > VV.availability(41, 82, FIT)


def test_injury_games_until_the_return_date():
    dates = ["2026-11-01", "2026-11-03", "2026-11-05", "2026-11-07"]
    assert VV.injury_games("Out", "Knee (return 2026-11-05)", dates, "2026-11-01") == 2
    assert VV.injury_games("Out", None, dates, "2026-11-01") == 10
    assert VV.injury_games("Day-To-Day", None, dates, "2026-11-01") == 1
    assert VV.injury_games(None, None, dates, "2026-11-01") == 0


# ---------------------------------------------------------------------------------------------- transactions

NAMES = MV.NameIndex({"1": "Jaren Jackson Jr.", "2": "John Konchar", "3": "Walter Clayton Jr.", "4": "D'Angelo Russell",
                      "5": "Ayo Dosunmu", "6": "Nikola Vucevic", "7": "Anfernee Simons", "8": "Kelly Olynyk", "9": "Cam Whitmore",
                      "10": "Saddiq Bey", "11": "Jordan Poole", "12": "Taurean Prince"},
                     {"6": [("2025-10-20", "2026-02-01", "CHI")], "7": [("2025-10-20", "2026-02-01", "BOS")]})
TEAMS = MV.TeamIndex({"BOS": {"name": "Boston Celtics", "location": "Boston", "abbr": "BOS"},
                      "CHI": {"name": "Chicago Bulls", "location": "Chicago", "abbr": "CHI"},
                      "WSH": {"name": "Washington Wizards", "location": "Washington", "abbr": "WSH"},
                      "NO": {"name": "New Orleans Pelicans", "location": "New Orleans", "abbr": "NO"},
                      "LAC": {"name": "LA Clippers", "location": "Los Angeles", "abbr": "LAC"},
                      "LAL": {"name": "Los Angeles Lakers", "location": "Los Angeles", "abbr": "LAL"}})


def test_names_normalise_accents_suffixes_and_typos():
    assert MV.norm("Jaren Jackson Jr.") == "jaren jackson"
    assert MV.norm("Nikola Vučević") == "nikola vucevic"
    assert NAMES.match("D'Angelo Russel") == "4"            # ESPN typo, close match
    assert NAMES.match("Ayo Dosunmo") == "5"
    assert NAMES.match("Someone Else") is None


def test_sentences_keep_abbreviations():
    s = MV.sentences("Acquired G Walter Clayton Jr. and F Kelly Olynyk from the L.A. Clippers. Waived F John Konchar.")
    assert len(s) == 2 and s[0].endswith("Clippers.")
    assert MV.sentence_type(s[1]) == "release" and MV.sentence_type(s[0]) == "trade"
    assert MV.sentence_type("Acquired G/F Someone off waivers from Boston.") == "claim"


def test_mentions_plural_tags_and_continuations():
    m = [n for _p, n in MV.mentions("Acquired Fs Kelly Olynyk and Cam Whitmore, G D'Angelo Russell from New Orleans for Gs Saddiq Bey and Jordan Poole.", NAMES)]
    assert m == ["Kelly Olynyk", "Cam Whitmore", "D'Angelo Russell", "Saddiq Bey", "Jordan Poole"]


def test_picks_parsing_counts_rounds_years_and_swaps():
    p = MV.picks_in("for F X, a 2026 first-round pick, a 2029 first-round pick and four second-round picks and a second-round pick swap")
    rounds = [(x["year"], x["round"], x["n"], x["swap"]) for x in p]
    assert (2026, 1, 1, False) in rounds and (2029, 1, 1, False) in rounds and (None, 2, 4, False) in rounds and (None, 2, 1, True) in rounds
    p2 = MV.picks_in("Acquired a 2028 first and second-round pick from New Jersey")
    assert sorted((x["year"], x["round"]) for x in p2) == [(2028, 1), (2028, 2)]
    assert MV.picks_in("2nd round picks in 2027 and 2030")[0]["round"] == 2
    assert MV._year("20227") == 2027
    assert MV.picks_in("the 22nd overall pick")[0]["overall"] == 22


def test_parse_row_directions_and_team_hint():
    r = MV.parse_row({"date": "2026-02-05", "team": "BOS", "text": "Acquired C Nikola Vucevic and draft consideration from Chicago in exchange for G Anfernee Simons and draft consideration."},
                     NAMES, TEAMS)
    s = r["sents"][0]
    assert s["in"] == ["6"] and s["out"] == ["7"] and s["teams"] == ["CHI"] and "draft consideration" in s["zero"]
    assert TEAMS.find("from the L.A. Clippers")[0][2] == "LAC"


def test_deals_pair_both_sides_and_do_not_chain_days():
    rows = [{"date": "2026-02-05", "team": "BOS", "text": "Acquired C Nikola Vucevic from Chicago in exchange for G Anfernee Simons."},
            {"date": "2026-02-05", "team": "CHI", "text": "Acquired G Anfernee Simons from Boston for C Nikola Vucevic."},
            {"date": "2026-02-06", "team": "CHI", "text": "Acquired F Taurean Prince from Boston for G Ayo Dosunmu."},
            {"date": "2026-02-06", "team": "BOS", "text": "Acquired G Ayo Dosunmu from Chicago for F Taurean Prince."}]
    parsed = [MV.parse_row(x, NAMES, TEAMS) for x in rows]
    deals = MV.build_deals(parsed, NAMES)
    assert len(deals) == 2                          # same two teams a day apart: two deals, not one chain
    d = [x for x in deals if x["date"] == "2026-02-05"][0]
    assert d["players"]["6"] == ["CHI", "BOS"] and d["players"]["7"] == ["BOS", "CHI"]


def test_pick_dedup_across_both_sides():
    rows = [{"date": "2026-02-04", "team": "LAL", "text": "Acquired G Saddiq Bey from Washington in exchange for a 2027 second-round pick."},
            {"date": "2026-02-04", "team": "WSH", "text": "Acquired a 2027 second-round pick from Los Angeles Lakers for G Saddiq Bey."}]
    deals = MV.build_deals([MV.parse_row(x, NAMES, TEAMS) for x in rows], NAMES)
    assert len(deals) == 1 and len(deals[0]["picks"]) == 1
    p = deals[0]["picks"][0]
    assert (p["from"], p["to"], p["year"], p["round"]) == ("LAL", "WSH", 2027, 2)


def test_pick_curve_is_non_increasing(monkeypatch):
    drafts = {y: [[o, 1 if o <= 30 else 2, o, "1", f"d{y}_{o}", "x", False] for o in range(1, 61)] for y in range(2005, 2015)}
    monkeypatch.setattr(BIO, "drafts", lambda lg: drafts)
    rng = np.random.default_rng(3)
    war_by = {}
    for y in range(2005, 2015):
        for j in range(1, 5):
            for o in range(1, 61):
                war_by.setdefault(y + j, {})[f"d{y}_{o}"] = max(0.0, 6.0 / o ** 0.7 + rng.normal(0, 0.8)) if o % 7 else 0.0
    c = MV.pick_curve("nba", war_by, 2020)
    vals = [v for _o, v in c["picks"]]
    assert c["n_drafts"] == 10 and all(a >= b - 1e-9 for a, b in zip(vals, vals[1:]))
    assert c["rounds"]["1"] > c["rounds"]["2"]
    v, lab = MV.pick_value(c, {"year": 2027, "round": 1, "overall": None, "n": 2, "swap": False}, 2026)
    assert v == pytest.approx(2 * c["rounds"]["1"] * VV.DISCOUNT ** 2) and "2027" in lab
    assert MV.pick_value(c, {"year": None, "round": 2, "overall": None, "n": 1, "swap": True}, 2026)[0] == 0.0


def test_grades_by_share():
    assert MV.grade(0.7, 5.0) == "A" and MV.grade(0.5, 5.0) == "C" and MV.grade(0.2, 5.0) == "F"
    assert MV.grade(0.9, 0.1) == "minor" and MV.grade(None, 5.0) is None


def test_season_of_date():
    assert MV.season_of_date("nba", "2026-07-06") == 2027 and MV.season_of_date("nba", "2026-02-05") == 2026
    assert MV.season_of_date("wnba", "2026-08-02") == 2026 and MV.season_of_date("wnba", "2026-11-20") == 2027


def test_rate_deals_realised_after_the_date_and_no_hindsight():
    rows_by = {2025: {"6": {"hpm": 3.0, "min": 2000, "gp": 70}, "7": {"hpm": 0.0, "min": 2000, "gp": 70}},
               2026: {"6": {"hpm": 10.0, "min": 2000, "gp": 70}, "7": {"hpm": 0.0, "min": 2000, "gp": 70}}}
    box = pd.DataFrame([{"player_id": "6", "date": d, "team": t, "sec": 1800, "team_poss": 100.0, "season": 2026}
                        for d, t in (("2026-01-10", "CHI"), ("2026-02-10", "BOS"), ("2026-02-12", "BOS"))] +
                       [{"player_id": "7", "date": "2026-02-10", "team": "CHI", "sec": 1800, "team_poss": 100.0, "season": 2026}])
    deal = {"id": "x", "date": "2026-02-05", "teams": ["BOS", "CHI"], "rows": [], "zero": [], "players": {"6": ["CHI", "BOS"], "7": ["BOS", "CHI"]}, "picks": []}
    ctx = {"rows": rows_by, "box": box, "games_left": {}, "valuation": {}, "names": {}, "current": 2027, "roster": {}, "slot_seasons": []}
    out = MV.rate_deals("nba", [deal], ctx, FIT, PRM, {"picks": [], "rounds": {}}, date(2026, 10, 1))
    bos = [s for s in out[0]["sides"] if s["team"] == "BOS"][0]
    vuc = bos["in"][0]
    # at the time: last completed season (3.0), not this season's 10.0
    assert vuc["rate"] < 4.0
    # realised: two games for Boston after the date at this season's 10.0
    exp = 2 * (10.0 - V.REPLACEMENT) * (30.0 / 48.0 * 100.0) / 100.0 / PRM["ppw"]
    assert vuc["realised"] == pytest.approx(exp) and vuc["gp_after"] == 2
    assert bos["grade_time"] in ("A", "B") and out[0]["winner_time"] == "BOS"


# ---------------------------------------------------------------------------------------------- fantasy

def test_game_stats_scale_with_minutes_pace_opponent_and_bump():
    r = {"pts": 0.6, "reb": 0.2, "ast": 0.15, "stl": 0.03, "blk": 0.02, "tpm": 0.06, "tpa": 0.16, "fgm": 0.22, "fga": 0.45, "ftm": 0.1,
         "fta": 0.12, "tov": 0.05}
    g = FN.game_stats(r, 30.0, 1.0, {}, {})
    assert g["pts"] == pytest.approx(18.0) and g["fga"] == pytest.approx(13.5)
    g2 = FN.game_stats(r, 30.0, 1.1, {"reb": 1.2}, {"fga": 1.2, "tpa": 1.2, "fta": 1.2})
    assert g2["reb"] == pytest.approx(0.2 * 30 * 1.1 * 1.2) and g2["fga"] == pytest.approx(13.5 * 1.1 * 1.2)
    assert g2["pts"] == pytest.approx(18.0 * 1.1 * 1.2)        # points follow the bumped shots at his efficiency


def test_nine_cat_z_and_punts():
    pg = {f"p{i}": {"pts": 10 + i, "reb": 5, "ast": 3, "stl": 1, "blk": 0.5, "tpm": 1, "fgm": 4 + 0.1 * i, "fga": 9, "ftm": 2, "fta": 2.5,
                    "tov": 2 + 0.2 * i} for i in range(30)}
    z = FN.nine_cat(pg, pool_n=20)
    assert z["p29"]["pts"] > z["p0"]["pts"] and z["p29"]["tov"] < z["p0"]["tov"]
    zp = FN.nine_cat(pg, cats=[c for c in FN.CATS9 if c != "tov"], pool_n=20)
    assert zp["p29"]["total"] > z["p29"]["total"]


def test_points_and_tiers():
    assert FN.points({"pts": 20, "reb": 10, "tov": 3}, {"pts": 1, "reb": 1.2, "tov": -1}) == pytest.approx(29.0)
    t = FN.tiers([10.0, 9.9, 9.8, 9.7, 7.0, 6.9, 6.8, 6.7, 3.0, 2.9, 2.8])
    assert t[:4] == [1, 1, 1, 1] and t[4] == 2 and t[-1] == 3


def test_team_schedule_rest_days():
    games = {"g1": {"stype": "reg", "date": "2026-10-21T23:00:00Z", "home": "A", "away": "B", "status": "pre"},
             "g2": {"stype": "reg", "date": "2026-10-22T23:00:00Z", "home": "C", "away": "A", "status": "pre"},
             "g3": {"stype": "reg", "date": "2026-10-25T23:00:00Z", "home": "A", "away": "C", "status": "pre"}}
    s = FN.team_schedule(games, ["A", "B", "C"])
    assert [x["rest"] for x in s["A"]] == [3, 0, 2]
    assert FN.week_start(date(2026, 10, 22)) == date(2026, 10, 19)


def test_rest_and_opponent_factors_from_boxes():
    rows = []
    for k in range(40):
        d = pd.Timestamp("2025-11-01") + pd.Timedelta(days=k * 2 + (1 if k % 3 == 0 else 0))
        for team, opp in (("A", "B"), ("B", "A")):
            for p in range(5):
                rows.append({"game_id": f"g{k}", "date": str(d.date()), "team": team, "opp": opp, "player_id": f"{team}{p}", "sec": 1800 if (k % 3 or p) else 1500,
                             "pts": 20 if team == "A" else 10, "oreb": 1, "dreb": 4, "ast": 3, "stl": 1, "blk": 1, "tpm": 1, "tpa": 3, "fgm": 7,
                             "fga": 15, "ftm": 3, "fta": 4, "tov": 2, "team_poss": 100.0})
    bx = pd.DataFrame(rows)
    rest = FN.rest_factors([bx])
    assert set(rest["min"]) == {"0", "1", "2", "3"}
    opp = FN.opponent_factors(bx, None)
    assert opp["B"]["pts"] > 1.0 > opp["A"]["pts"]            # B allows A's 20-point scorers


def test_backtest_spearman_and_blend():
    from oddsmarkets.basketball.research import fantasy_backtest as FB
    assert FB._spearman(list(range(20)), list(range(20))) == pytest.approx(1.0)
    assert FB._spearman([1, 2], [2, 1]) is None
    std = pd.Series({"a": 30.0})
    n = pd.Series({"a": 20})
    old = FB.BLEND
    FB.BLEND = 0.5
    try:
        assert FB._blend(20.0, "a", std, n) == pytest.approx(25.0)
        assert FB._blend(20.0, "b", std, pd.Series({"b": 1})) == 20.0
    finally:
        FB.BLEND = old
