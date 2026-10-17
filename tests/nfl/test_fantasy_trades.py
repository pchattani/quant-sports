"""Valuation v2, the transactions parser and trade ratings, and the fantasy model (docs/VALUE_SECTIONS.md sections 4-5).
Synthetic data and one recorded ESPN fixture only (no network)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nfl.analytics import fantasy as F
from oddsmarkets.nfl.analytics import fantasy_model as FM
from oddsmarkets.nfl.analytics import transactions as TX
from oddsmarkets.nfl.analytics import valuation as VA
from tests.nfl.conftest import load_fixture_json


# ── valuation ────────────────────────────────────────────────────────────────

def _panel(n_players=120, seasons=range(2010, 2020), seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_players):
        talent = rng.normal(1.0, 0.6)
        age0 = rng.uniform(21, 30)
        for k, s in enumerate(seasons):
            age = age0 + k
            if age > 35:
                break
            lvl = talent - 0.08 * max(0.0, age - 27)          # decline after 27
            g = int(rng.integers(6, 18))
            rows.append({"pid": f"p{i}", "season": s, "pos": "WR", "age": round(age, 1), "games": g, "tg": 17,
                         "x": float(lvl + rng.normal(0, 0.9 / np.sqrt(g / 4))), "q": True, "name": f"P{i}", "team": "T"})
    return rows


def test_valuation_curves_shrink_and_age():
    c = VA.fit_curves(_panel())["WR"]
    assert 0.05 < c["b"] < 0.95 and c["k"] > 0
    # older players are expected to decline more than young ones
    assert VA.delta(c, 33) < VA.delta(c, 24)
    # shrinkage: a small sample sits closer to the mean than a big one with the same rate
    lo, r_lo = VA.current_level(c, 3.0, 3, None, 0, 26)
    hi, r_hi = VA.current_level(c, 3.0, 16, None, 0, 26)
    assert r_lo < r_hi and c["mean"] < lo < hi < 3.0
    assert VA.current_level(c, None, 0, None, 0, 26)[0] is None


def test_valuation_projection_floors_and_band():
    c = VA.fit_curves(_panel())["WR"]
    pj = VA.project(c, 1.5, 26.0, 10, 0.9, 3, rng=np.random.default_rng(1))
    assert len(pj["levels"]) == 4 and pj["games"][0] == pytest.approx(9.0)
    assert pj["lo"] <= pj["total"] <= pj["hi"]
    neg = VA.project(c, -2.0, 26.0, 10, 0.9, 3, rng=np.random.default_rng(1))
    assert neg["total"] == 0.0                                     # below replacement is worth nothing, not less
    # a QB-model level is carried toward the average QB
    q = VA.project(c, 8.0, 26.0, 10, 1.0, 3, qb_model=True, qb_target=0.7, rng=np.random.default_rng(1))
    assert q["levels"][3] < q["levels"][1] < 8.0 + 1e-9


def test_pick_curve_and_values():
    # value over the first seasons falls with the slot
    rows = [{"pid": f"p{i}", "season": s, "pos": "WR", "age": 22.0, "games": 16, "tg": 17, "x": 3.0 * np.exp(-i / 60.0)}
            for i in range(262) for s in range(2010, 2014)]
    draft = {f"p{i}": {"year": 2010, "round": min(7, i // 32 + 1), "pick": i + 1, "pos": "WR"} for i in range(262)}
    draft["p0"]["pos"] = "OT"                                     # linemen are excluded from the curve
    pc = VA.pick_curve(rows, draft, 2019, first=2008)
    assert pc["ok"] and len(pc["picks"]) == 262 and pc["n"] == 261
    assert pc["picks"][0] >= pc["picks"][100] >= pc["picks"][-1] >= 0
    v = VA.pick_value(pc, 2027, 1, None, 2026)
    assert v == pytest.approx(pc["rounds"]["1"])
    assert VA.pick_value(pc, 2028, 1, None, 2026) == pytest.approx(v * VA.DISCOUNT)
    assert VA.pick_value(pc, 2027, 1, None, 2026, conditional=True) == pytest.approx(v / 2)
    assert VA.pick_value(pc, 2027, None, 5, 2026) == pytest.approx(pc["picks"][4])
    assert VA.pick_value({"ok": False}, 2027, 1, None, 2026) is None


def test_valuation_build_payload_shape():
    rows = _panel()
    recs = {f"p{i}": {"pid": f"p{i}", "name": f"P{i}", "team": "KC", "pos": "WR", "age": 26.0, "games": 5, "gvar_pg": 0.2 * (i % 10),
                      "status": "ACT"} for i in range(40)}
    out = VA.build(2020, recs, {}, 35.0, -0.02, {"KC": 12}, 0.85, rows=rows, wpp=0.028, curve={"ok": False, "reason": "test"}, tg_cur=5,
                   roster={"p77": {"team": "KC", "status": "RES", "pos": "WR"}})
    assert out["ok"] and out["cols"][0] == "pid"
    by = {r[0]: dict(zip(out["cols"], r)) for r in out["rows"]}
    assert "p77" in by and by["p77"]["status"] == "RES"            # rostered without a game this season: still valued
    assert by["p9"]["value"] >= by["p1"]["value"]
    assert by["p9"]["wins"] == pytest.approx(by["p9"]["value"] * 0.85 * 0.028, abs=0.02)


# ── transactions ─────────────────────────────────────────────────────────────

def test_clauses_and_classify():
    cs = TX.clauses("Signed RB Elijah Mitchell to a contract. Released DE Brandon Graham. Traded WR A.J. Brown to New England for a "
                    "2028 first-round pick and a conditional 2027 fifth-round pick.")
    assert len(cs) == 3 and cs[2].startswith("Traded WR A.J. Brown")
    assert [TX.classify(c) for c in cs] == ["signing", "release", "trade"]
    assert TX.classify("Signed WR X to the practice squad.") == "practice"
    assert TX.classify("Acquired WR Y on waivers from Pittsburgh.") == "claim"
    assert TX.classify("Received an international exemption for TE Z.") == "other"


def test_parse_trade_forms_and_picks():
    d = date(2026, 10, 12)
    s = TX.parse_trade("ARI", d, "Traded WR Marvin Harrison Jr. and a 2027 sixth-round draft pick to Houston for 2027 second- and seventh-round draft picks.")
    assert s["counter"] == ["HOU"]
    assert [p["name"] for p in s["gives"]["players"]] == ["Marvin Harrison Jr"]
    assert [(k["year"], k["round"]) for k in s["gives"]["picks"]] == [(2027, 6)]
    assert sorted((k["year"], k["round"]) for k in s["gets"]["picks"]) == [(2027, 2), (2027, 7)]
    a = TX.parse_trade("NE", date(2026, 6, 1), "Acquired WR A.J. Brown from Philadelphia in exchange for a 2028 first-round draft pick and a conditional 2027 fifth-round draft pick.")
    assert a["counter"] == ["PHI"] and a["gets"]["players"][0]["name"] == "A.J. Brown"
    assert {(k["year"], k["round"], k["conditional"]) for k in a["gives"]["picks"]} == {(2028, 1, False), (2027, 5, True)}
    o = TX.parse_trade("MIN", date(2025, 4, 26), "Acquired QB Sam Howell and the 172nd 2025 pick from Seattle in exchange for the 142nd 2025 pick.")
    assert o["gets"]["picks"][0]["overall"] == 172 and o["gives"]["picks"][0]["overall"] == 142
    # no year: the next draft (late April)
    n = TX.parse_trade("DEN", date(2026, 3, 18), "Traded a first-round pick, a third-round pick and a fourth-round pick to Miami Dolphins for WR Jaylen Waddle and a fourth-round pick.")
    assert {k["year"] for k in n["gives"]["picks"]} == {2026} and len(n["gives"]["picks"]) == 3 and n["counter"] == ["MIA"]
    c = TX.parse_trade("NE", d, "Traded LB Marte Mapu to Houston for draft considerations.")
    assert c["gets"]["considerations"] and c["counter"] == ["HOU"]
    assert TX.parse_trade("ATL", d, "Waived S Jammie Robinson.") is None


def test_team_names_and_ambiguity():
    assert TX.team_from_text("the Los Angeles Rams") == ["LA"]
    assert sorted(TX.team_from_text("Los Angeles")) == ["LA", "LAC"]
    assert TX.team_from_text("N.Y. Jets") == ["NYJ"]
    assert TX.team_from_text("Philadelphia Eagles") == ["PHI"]
    assert TX.espn_team("WSH") == "WAS" and TX.espn_team("LAR") == "LA"


def test_merge_both_clubs_notes_from_fixture():
    fx = load_fixture_json("espn_transactions_slice.json")
    raw = [{"date": t["date"], "text": t["description"], "team": t["team"]["abbreviation"]} for t in fx["transactions"]]
    trades = TX.merge_sides(TX.trade_sides(raw, date(2026, 1, 1)))
    by = {frozenset(t["teams"]): t for t in trades}
    g = by[frozenset({"CLE", "LA"})]                                # three notes (two CLE, one LAR) -> one trade
    assert len(g["texts"]) == 3
    assert [p["name"] for p in g["gets"]["LA"]["players"]] == ["Myles Garrett"]
    assert {(k["year"], k["round"]) for k in g["gets"]["CLE"]["picks"]} == {(2027, 1), (2028, 2), (2029, 3)}
    assert [p["name"] for p in g["gets"]["CLE"]["players"]] == ["Jared Verse"]
    w = by[frozenset({"DEN", "MIA"})]
    assert len(w["gets"]["MIA"]["picks"]) == 3 and len(w["gets"]["DEN"]["picks"]) == 1
    j = by[frozenset({"PHI", "BAL"})]
    assert len(j["texts"]) == 2 and j["gets"]["BAL"]["players"][0]["name"] == "Cam Jurgens"
    # the Porter trade: DAL's note names the wrong club ("from Dallas") six days early; the assets still merge it
    p = [t for t in trades if "DAL" in t["teams"] and any("Porter" in x["text"] for x in t["texts"])]
    assert len(p) == 1 and set(p[0]["teams"]) == {"DAL", "PIT"}
    feed = TX.feed(raw, date(2026, 1, 1))
    assert any(f["type"] == "release" and f["team"] == "ATL" for f in feed)


def test_matcher_prefers_roster_and_fuzzy():
    people = {"a1": {"name": "Joe Tryon-Shoyinka", "pos": "DE", "last": 2026}, "b1": {"name": "Mike Williams", "pos": "WR", "last": 2026},
              "b2": {"name": "Mike Williams", "pos": "WR", "last": 2025}}
    m = TX.Matcher(people, {"b2": [(date(2026, 9, 1), "NYJ")], "b1": [(date(2026, 9, 1), "PIT")]})
    assert m.match("DE", "Joe Tyron-Shoyinka", date(2026, 10, 1)) == "a1"
    assert m.match("WR", "Mike Williams", date(2026, 10, 1), "NYJ") == "b2"
    assert m.match("WR", "Nobody Known", date(2026, 10, 1)) is None


def test_trade_rating_grades_and_winner():
    d = date(2026, 6, 1)
    rows_by = {("x", 2025): {"pid": "x", "season": 2025, "pos": "WR", "age": 26.0, "games": 16, "tg": 17, "x": 2.0},
               ("x", 2024): {"pid": "x", "season": 2024, "pos": "WR", "age": 25.0, "games": 16, "tg": 17, "x": 2.0}}
    curves = VA.fit_curves(_panel())
    pick = {"ok": True, "picks": [40.0 - 0.15 * i for i in range(262)], "rounds": {str(r): 40.0 - 4.8 * (r - 1) for r in range(1, 8)}}
    rc = TX.RateCtx(2026, rows_by, curves, pick, {"x": {"gvar_pg": 2.5, "games": 5}}, {"x": {"proj": [2.0, 1.9, 1.8, 1.7], "games": [10, 14, 12, 10]}},
                    {"x": [(2026, date(2026, 9, 10), "NE"), (2026, date(2026, 9, 17), "NE")]}, {("NE", 2026): [date(2026, 9, 10), date(2026, 9, 17), date(2026, 12, 1)]},
                    {"x": "NE"}, 0.85, 0.028, today=date(2026, 10, 15))
    t = {"date": d.isoformat(), "teams": ["NE", "PHI"], "texts": [{"team": "NE", "date": d.isoformat(), "text": "note"}],
         "gets": {"NE": {"players": [{"pid": "x", "name": "X", "pos": "WR"}], "picks": []},
                  "PHI": {"players": [], "picks": [{"year": 2027, "round": 7, "overall": None, "conditional": False}]}}}
    r = TX.rate(t, rc)
    ne = [s for s in r["sides"] if s["team"] == "NE"][0]
    phi = [s for s in r["sides"] if s["team"] == "PHI"][0]
    assert ne["net_at"] == pytest.approx(-phi["net_at"]) and ne["wins_now"] > 0 and r["winner"] == "NE"
    assert ne["real"] == pytest.approx(2.5 * 2)                     # two games for NE after the trade at 2.5 a game
    assert TX.grade(1.2) == "A" and TX.grade(0.31) == "B" and TX.grade(0.0) == "C" and TX.grade(-0.5) == "D" and TX.grade(-1.5) == "F"
    ol = TX.value_player(rc, "y", "G", "NE", d)
    assert ol["valued"] is False


def test_espn_transactions_paginates():
    from oddsmarkets.nfl.sources import espn as E

    class Fake:
        def __init__(self):
            self.calls = []

        def get(self, url, params=None):
            self.calls.append(params["page"])
            return {"pageCount": 2, "transactions": [{"date": "2026-10-0%dT07:00Z" % params["page"], "description": "Waived S X.", "team": {"abbreviation": "ATL", "displayName": "Atlanta Falcons"}}]}
    c = Fake()
    out = E.transactions(c, 2026)
    assert c.calls == [1, 2] and len(out) == 2 and out[0]["team"] == "ATL" and out[0]["text"] == "Waived S X."


# ── fantasy ──────────────────────────────────────────────────────────────────

def test_scoring_formats():
    line = {"pass_yds": 250, "pass_td": 2, "ints": 1, "rush_yds": 30, "rush_td": 1, "rec": 5, "rec_yds": 40, "rec_td": 0, "fl": 1, "two_pt": 1}
    std = 0.04 * 250 + 8 - 2 + 3 + 6 + 4 - 2 + 2
    assert F.points(line, "std") == pytest.approx(std)
    assert F.points(line, "half") == pytest.approx(std + 2.5)
    assert F.points(line, "ppr") == pytest.approx(std + 5)
    assert F.dst_pa_points(0) == 10 and F.dst_pa_points(6) == 7 and F.dst_pa_points(20) == 1 and F.dst_pa_points(40) == -4
    assert F.dst_pa_expected(3.0, 0.01) == pytest.approx(7.0, abs=1e-3)
    assert F.dst_pa_expected(14.0, 8.0) > F.dst_pa_expected(30.0, 8.0)
    assert F.kicker_points({"fg_made_40_49": 1, "fg_made_50_59": 1, "pat_made": 2, "fg_missed": 1}) == pytest.approx(4 + 5 + 2 - 1)


def test_expected_tables():
    T = pd.DataFrame({"yb": [0] * 200 + [5] * 200, "ab": [1] * 400, "catch": [1.0] * 400, "yds": [3.0] * 200 + [12.0] * 200,
                      "td": [0.5] * 200 + [0.0] * 200})
    C = pd.DataFrame({"yb": [0] * 50 + [5] * 50, "yds": [1.0] * 50 + [5.0] * 50, "td": [0.4] * 50 + [0.0] * 50})
    tab = F.fit_tables([T], [C], min_n=150)
    assert tab["t"]["0|1"][2] == pytest.approx(0.5) and tab["t"]["5|1"][1] == pytest.approx(12.0)
    T2, C2 = F.apply_tables(T.head(2), C.head(2), tab)
    assert T2["xtd"].iloc[0] == pytest.approx(0.5) and C2["xtd"].iloc[0] == pytest.approx(0.4) and C2["gl"].iloc[0] == 1.0


def _season(weeks=4):
    """Two teams, a QB, two WRs and an RB each; every week the same usage. WR1 of A takes 60% of targets."""
    rows = []
    for w in range(1, weeks + 1):
        for t, o in (("A", "B"), ("B", "A")):
            for pid, pos, tgt, car, att in ((t + "qb", "QB", 0, 3, 30), (t + "wr1", "WR", 18, 0, 0), (t + "wr2", "WR", 9, 0, 0), (t + "rb", "RB", 3, 20, 0)):
                rec = 0.65 * tgt
                rows.append({"pid": pid, "name": pid, "pos": pos, "team": t, "opp": o, "week": w, "game_id": f"g{w}", "att": att, "cmp": 0.65 * att,
                             "pass_yds": 7.0 * att, "pass_td": 1.5 if att else 0.0, "ints": 0.7 if att else 0.0, "car": car, "rush_yds": 4.3 * car,
                             "rush_td": 0.5 if car > 10 else 0.0, "rec": rec, "tgt": tgt, "rec_yds": 8.0 * tgt, "rec_td": 0.4 if tgt > 10 else 0.1, "fl": 0.0,
                             "two_pt": 0.0, "st_td": 0.0, "rz_tgt": 0.1 * tgt, "air": 8.0 * tgt, "xrec": rec, "xrec_yds": 8.0 * tgt, "xrec_td": 0.03 * tgt,
                             "car_pbp": car, "rz_car": 0.15 * car, "gl_car": 0.05 * car, "xrush_yds": 4.3 * car, "xrush_td": 0.025 * car,
                             "team_tgt": 30.0, "team_car": 23.0, "team_att": 30.0, "team_rz_tgt": 3.0, "team_rz_car": 3.45, "team_xrec_td": 0.9,
                             "team_xrush_td": 0.575, "team_air": 240.0, "fg_att": 0.0, "pat_att": 0.0})
    pw = pd.DataFrame(rows)
    for f in F.FORMATS:
        pw["fp_" + f] = F.points(pw, f)
    pw["xfp_ppr"] = pw["xrec"] + 0.1 * (pw["xrec_yds"] + pw["xrush_yds"]) + 6 * (pw["xrec_td"] + pw["xrush_td"])
    tw = pd.DataFrame([{"team": t, "opp": o, "week": w, "imp": 24.0 if t == "A" else 20.0, "oimp": 20.0 if t == "A" else 24.0, "final": w <= weeks,
                        "game_id": f"g{w}", "home": t == "A"} for w in range(1, weeks + 2) for t, o in (("A", "B"), ("B", "A"))])
    return pw, tw


def test_projection_usage_and_injury_redistribution():
    pw, tw = _season()
    P = dict(F.PARAMS)
    prep = FM.prepare(2026, 5, pw, pw.iloc[0:0], tw, P)
    roster = pd.DataFrame([{"pid": p, "team": p[0], "pos": {"qb": "QB", "wr1": "WR", "wr2": "WR", "rb": "RB"}[p[1:]], "name": p, "status": "ACT"}
                           for p in ("Aqb", "Awr1", "Awr2", "Arb", "Bqb", "Bwr1", "Bwr2", "Brb")])
    ctx = {"players": roster, "games": FM.week_games(tw, 5), "avail": {}, "qb": {"A": "Aqb", "B": "Bqb"}}
    pr = FM.project(prep, ctx, P).set_index("pid")
    assert pr.loc["Awr1", "tgt"] > pr.loc["Awr2", "tgt"] > 0
    assert pr.loc["Awr1", "tgt"] == pytest.approx(0.6 * 30.0, rel=0.1)
    assert pr.loc["Aqb", "att"] > 25 and pr.loc["Arb", "car"] > 15
    assert (pr["ppr"] >= pr["half"]).all() and (pr["half"] >= pr["std"]).all()
    # WR1 out: zero for him, his targets shared out (team-mates up), the team total capped
    ctx2 = dict(ctx, avail={"Awr1": 0.0})
    pr2 = FM.project(prep, ctx2, P).set_index("pid")
    assert pr2.loc["Awr1", "ppr"] == 0.0 and pr2.loc["Awr2", "tgt"] > pr.loc["Awr2", "tgt"]
    # the team's targets are not inflated: the vacated share is redistributed within the same capped total
    assert pr2.loc[["Awr2", "Arb"], "tgt"].sum() <= pr.loc[["Awr1", "Awr2", "Arb"], "tgt"].sum() + 1e-6
    # a bye: no rows for teams without a game
    ctx3 = dict(ctx, games={"A": ctx["games"]["A"]})
    assert set(FM.project(prep, ctx3, P)["team"]) == {"A"}


def test_starting_qb_and_week_context():
    pw, tw = _season()
    roster = pd.DataFrame([{"pid": "Aqb", "team": "A", "pos": "QB", "name": "a", "status": "ACT", "week": 5},
                           {"pid": "Aqb2", "team": "A", "pos": "QB", "name": "b", "status": "ACT", "week": 5},
                           {"pid": "Awr1", "team": "A", "pos": "WR", "name": "c", "status": "RES", "week": 5}])
    inj = pd.DataFrame([{"pid": "Aqb", "week": 5, "status": "Out", "injury": "Knee"}])
    ctx = FM.week_context(roster, inj, 5, tw, dict(F.PARAMS))
    assert ctx["avail"]["Aqb"] == 0.0 and ctx["avail"]["Awr1"] == 0.0 and ctx["inj"]["Aqb"] == ["Out", "Knee"]
    assert FM.starting_qbs(pw, pw.iloc[0:0], 5, roster, {}) == {"A": "Aqb"}
    assert FM.starting_qbs(pw, pw.iloc[0:0], 5, roster, ctx["avail"]) == {"A": "Aqb2"}


def test_backtest_metrics_and_band():
    bt = pd.DataFrame({"pos": ["WR"] * 6, "S": [2025] * 6, "w": [1, 1, 1, 2, 2, 2], "ppr": [10, 8, 2, 12, 6, 1], "act_ppr": [11, 7, 0, 15, 5, 3],
                       "std_fp_ppr": [5, 9, 3, 5, 9, 3], "last_fp_ppr": [6, 6, 6, 6, 6, 6], "played": [True, True, False, True, True, True]})
    m = FM.metrics(bt, "ppr")
    assert m["WR"]["model"]["mae"] == pytest.approx(np.mean([1, 1, 2, 3, 1, 2]), abs=1e-3)
    assert m["WR"]["model"]["mae"] < m["WR"]["season_to_date"]["mae"]
    lo, hi = FM.band(10.0, "WR", {"SD": {"WR": [2.0, 0.2]}})
    assert lo == pytest.approx(10 - 1.2816 * 4.0) and hi == pytest.approx(10 + 1.2816 * 4.0)
    assert FM.band(0.5, "WR", {"SD": {"WR": [2.0, 0.2]}})[0] == 0.0


def test_picks_rules():
    base = {"status": "ACT", "inj": None, "opp": "B", "imp": 26.0, "opp_f": 1.15, "ros_g": 10, "sos": 1.0, "tgt_sh3": 0.2, "tgt_sh": 0.2,
            "car_sh": 0.0, "car_sh3": 0.0, "td": 1, "xtd": 1.0, "xfp": 50.0}
    rows = []
    for i in range(60):                                              # 60 WRs: season ppg falls with i, this week rises for #30
        rows.append(dict(base, pid=f"w{i}", pos="WR", g=5, pts_ppr=100 - 2 * i, xfp=100 - 2 * i, ppr=max(15 - 0.2 * i, 0.5), ros_ppr=max(150 - 2 * i, 10)))
    rows[30].update(ppr=20.0)                                        # projected WR1 this week, WR31 so far
    rows[35].update(xfp=75.0, pts_ppr=30.0, td=0, xtd=3.0)           # buy low: usage worth 15 a game, scoring 6
    rows[2].update(pts_ppr=140.0, xfp=60.0, td=8, xtd=3.0)           # sell high
    rows[38].update(tgt_sh3=0.30, tgt_sh=0.18)                        # breakout
    p = FM.picks(rows, {"KC": {"next": 9.0, "weeks": [[6, "LV", 9.0]], "ros": 90}}, {"BAL": {"next": 8.0, "weeks": [[6, "CLE", 8.0]], "ros": 70}}, 6)
    assert p["start"][0]["pid"] == "w30"
    assert "w35" in [x["pid"] for x in p["buy_low"]] and "w2" in [x["pid"] for x in p["sell_high"]]
    assert "w38" in [x["pid"] for x in p["breakout"]]
    wv = [x["pid"] for x in p["waiver"]]
    assert wv and all(int(x[1:]) >= FM.WAIVER_N["WR"] for x in wv)    # only players outside the top scorers
    assert p["k"][0]["team"] == "KC" and p["dst"][0]["team"] == "BAL"
