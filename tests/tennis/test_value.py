"""The Value section (analytics/value.py, data/<T>/value.json and value_validation.json): metric definitions on synthetic
data, walk-forward without look-ahead, the ranking-points calendar, the payloads on the synthetic world, the glossary
and the front-end's references to it. No network."""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from oddsmarkets.tennis import analytics as an
from oddsmarkets.tennis.analytics import value as V

ROOT = Path(__file__).resolve().parents[2]


# ── small maths ───────────────────────────────────────────────────────────────────────────────────────────

def test_pythagorean_exponent_is_recovered():
    rng = np.random.default_rng(0)
    share = rng.uniform(0.3, 0.7, 20000)
    won = (rng.uniform(size=share.size) < V.pyth(share, 12.0)).astype(float)
    k = V.fit_k(V._logit(share), won)
    assert k == pytest.approx(12.0, rel=0.08)
    assert float(V.pyth(0.5, 20.0)) == pytest.approx(0.5)
    assert float(V.pyth(0.55, 20.0)) == pytest.approx(0.55 ** 20 / (0.55 ** 20 + 0.45 ** 20))


def test_set_probabilities_invert_the_match_probability():
    for bo, p in ((3, 0.5), (3, 0.8), (5, 0.3)):
        need = 2 if bo == 3 else 3
        q = V._set_win_prob(p, bo)
        assert V._from_sets(q, 0, 0, need) == pytest.approx(p, abs=1e-6)
    assert V._from_sets(0.5, 1, 0, 2) == pytest.approx(0.75)


def test_rank_correlation_and_bootstrap():
    x = np.arange(50.0)
    assert V.spearman(x, x ** 3) == pytest.approx(1.0)
    assert V.spearman(x, -x) == pytest.approx(-1.0)
    est, lo, hi = V.boot_ci(V.spearman, np.arange(50) % 10, x, x + np.random.default_rng(1).normal(0, 10, 50), n=200)
    assert lo <= est <= hi


def test_breakout_and_regression_events():
    rank = np.array([30.0, 30.0, 12.0, 100.0, 50.0, 1.0, 4.0])
    y = np.array([math.log(19 / 30), math.log(21 / 30), math.log(8 / 12), np.nan, math.log(76 / 50), math.log(3.0), math.log(9 / 4)])
    rise, fall = V._events(y, rank)
    # 30 -> 19 is a third better and 11 places; 30 -> 21 is not a third; 12 -> 8 is a third but only 4 places
    assert rise.tolist() == [True, False, False, False, False, False, False]
    # unobserved counts as a regression, never as a breakout; 50 -> 76 is half worse; No. 1 -> 3 is not 5 places; 4 -> 9 is
    assert fall.tolist() == [False, False, False, True, True, False, True]


def test_event_thresholds_by_rank():
    up, down = V.thresholds([1.0, 12.0, 30.0, 150.0])
    assert down[0] == pytest.approx(math.log(6.0)) and down[2] == pytest.approx(V.FALL)   # No. 1 must reach No. 6
    assert up[1] == pytest.approx(math.log(7 / 12)) and up[2] == pytest.approx(V.RISE)    # No. 12 must reach No. 7
    assert up[3] == pytest.approx(V.RISE) and down[3] == pytest.approx(V.FALL)


def test_implied_ranks_hand_out_official_ranks_in_model_order():
    ranks = {"a": 1.0, "b": 2.0, "c": 7.0, "d": 40.0}
    rating = {"a": 1900.0, "b": 1700.0, "c": 1950.0, "d": 1800.0}
    imp = V.implied_ranks(ranks, rating)
    assert imp == {"c": 1.0, "a": 2.0, "d": 7.0, "b": 40.0}


def test_model_rating_is_the_linear_blend():
    w = {"w_elo": 0.5, "w_sr": 0.2, "w_gelo": 1.0}
    elo = {"a": (1800.0, 1850.0, 1700.0, 1750.0, 50, 0)}
    gelo = {"a": (0.3, 0.4, 0.1, 0.2, 50)}
    sr = {"new": 0.0, "players": {"a": [0.5, 0.6, 0.2, 0.4]}}
    r = V.ratings_for(["a"], elo, gelo, sr, w, 2.0, 0.4, 0.2)["a"]
    assert r == pytest.approx(0.5 * 1800 + V.K_ELO * (0.2 * 2.0 * 0.5 + 1.0 * 0.3))
    rc = V.ratings_for(["a"], elo, gelo, sr, w, 2.0, 0.4, 0.2, surface="clay")["a"]
    assert rc == pytest.approx(0.5 * (0.4 * 1700 + 0.6 * 1800) + V.K_ELO * (0.2 * 2.0 * 0.2 + 1.0 * (0.2 * 0.1 + 0.8 * 0.3)))
    assert V.sr_beta(1.0) > 0


def test_reasons_group_the_age_terms():
    out = V.reasons({"gap": -0.3, "age": 0.05, "age2": 0.04, "age_na": 0.0, "idle": 0.01, "lr": -0.1})
    assert out[0] == ["gap", -0.3] and ["age", 0.09] in out and all(k != "age2" for k, _ in out)
    assert all(k != "idle" for k, _ in out)                  # below the 0.02 floor


# ── luck pieces on a hand-made match table ────────────────────────────────────────────────────────────────

def _table(rows: list[dict]) -> dict:
    """A minimal match table (the columns match_luck and luck_window read)."""
    keys = {"d": 0, "won": 0, "st": 0, "bo": 3, "g": 0, "gl": 0, "sw": 0, "sl": 0, "band": -1, "side": 0}
    T: dict = {}
    for k, dflt in keys.items():
        T[k] = np.array([r.get(k, dflt) for r in rows], dtype=np.int64)
    T["tl"] = np.array([r.get("tl", True) for r in rows], dtype=bool)
    for k in ("em", "eo", "ep", "fe", "tpw", "spw", "rpw", "bps", "bpf", "bpc", "bpo", "book", "rank", "orank", "pts"):
        T[k] = np.array([r.get(k, np.nan) for r in rows], dtype=float)
    for k in ("lvl", "rnd", "pid", "opp", "mid", "ev", "surf", "bsrc", "rule"):
        T[k] = np.array([r.get(k, "") for r in rows], dtype=object)
    T["n"] = len(rows)
    T["f5"] = 1.0
    T["by"] = {"a": np.arange(len(rows))}
    return T


PRM = {"k_games_bo3": 20.0, "k_games_bo5": 26.0, "k_points": 27.0, "bp_save_offset": 0.0, "bp_conv_offset": 0.0}


def test_close_match_luck_and_free_wins():
    d0 = date(2025, 3, 1).toordinal()
    rows = [
        # won 7-6 0-6 7-6: 14-18 in games, so the games say it was probably a loss -> most of a win is luck
        {"d": d0, "won": 1, "g": 14, "gl": 18, "lvl": "250", "rnd": "R32", "pid": "a", "ep": 0.5},
        # lost 4-6 4-6: the games agree with the result -> no luck
        {"d": d0 + 1, "won": 0, "g": 8, "gl": 12, "lvl": "250", "rnd": "R16", "pid": "a", "ep": 0.5},
        # a walkover received as the underdog (Elo 0.3): worth 0.7 of a win
        {"d": d0 + 2, "won": 1, "st": 3, "lvl": "250", "rnd": "QF", "pid": "a", "ep": 0.3},
        # the opponent retired with this player a set up (even match): worth 1 - P(win | 1-0) = 0.25
        {"d": d0 + 3, "won": 1, "st": 1, "sw": 1, "sl": 0, "g": 9, "gl": 4, "lvl": "250", "rnd": "SF", "pid": "a", "ep": 0.5},
    ]
    T = _table(rows)
    L = V.match_luck(T, PRM, {})
    assert 0.5 < 1 - L["pg"][0] < 1.0
    assert L["pg"][1] == pytest.approx(float(V.pyth((8.5) / 21.0, 20.0)))
    assert np.isnan(L["pg"][2]) and np.isnan(L["pg"][3])                 # only completed matches
    assert L["free"][2] == pytest.approx(0.7)
    assert L["free"][3] == pytest.approx(0.25, abs=1e-6)
    lw = V.luck_window(T, L, T["by"]["a"], d0, d0 + 10)
    assert lw["n"] == 3 and lw["w"] == 2                                  # the walkover is not a match played
    assert lw["close"] == pytest.approx((1 - L["pg"][0]) + (0 - L["pg"][1]))
    assert lw["free"] == pytest.approx(0.95) and lw["wo_rec"] == 1 and lw["ret_rec"] == 1
    assert lw["total"] == pytest.approx(lw["close"] + lw["draw"] + lw["free"])
    # a window that ends before the matches sees nothing
    assert V.luck_window(T, L, T["by"]["a"], d0 - 10, d0)["n"] == 0


def test_break_point_luck_uses_the_non_break_point_rates():
    rows = [{"d": 1, "won": 1, "g": 12, "gl": 8, "lvl": "250", "rnd": "R32", "pid": "a", "tpw": 0.55,
             "bpf": 10.0, "bps": 8.0, "spw": 0.6, "bpo": 8.0, "bpc": 2.0, "rpw": 0.4}]
    T = _table(rows)
    L = V.match_luck(T, dict(PRM, bp_save_offset=-0.05), {})
    lw = V.luck_window(T, L, T["by"]["a"], 0, 10)
    assert lw["bp_saved_exp"] == pytest.approx(10 * 0.55) and lw["bp_saved_over"] == pytest.approx(8 - 5.5)
    assert lw["bp_conv_over"] == pytest.approx(2 - 8 * 0.4)
    # points-to-games conversion is reported but not counted as luck
    assert lw["conv"] == pytest.approx(float(L["pg"][0] - L["pp"][0]))
    assert lw["total"] == pytest.approx(lw["close"] + lw["draw"] + lw["free"])


def test_draw_luck_is_zero_against_the_typical_draw_and_positive_against_a_weak_one():
    yr = 2025
    d = date(yr, 5, 1).toordinal()
    q = np.linspace(-150, 150, 19)                         # the typical opponents, relative to the field
    typ = {(yr, "250", "R32", 5): {"q": q, "mean": 1600.0}}
    base = {"d": d, "won": 1, "g": 12, "gl": 8, "lvl": "250", "rnd": "R32", "band": 5, "pid": "a", "em": 1650.0, "fe": 1600.0}
    rows = [dict(base, eo=1600.0 + x) for x in q] + [dict(base, eo=1400.0)]
    T = _table(rows)
    L = V.match_luck(T, PRM, typ)
    assert float(np.sum(L["draw"][:19])) == pytest.approx(0.0, abs=1e-9)   # facing the typical draw: no luck on average
    assert L["draw"][19] > 0.1                                             # a much weaker opponent than typical
    assert L["sos"][19] == pytest.approx(-200.0)


def test_typical_opponents_use_earlier_years_only():
    rows = []
    for y, eo in ((2020, 1500.0), (2021, 1700.0)):
        for i in range(50):
            rows.append({"d": date(y, 6, 1).toordinal(), "lvl": "250", "rnd": "R32", "band": 5, "eo": eo, "fe": 1500.0, "pid": "a"})
    typ = V.typical_opponents(_table(rows))
    assert typ[(2020, "250", "R32", 5)]["mean"] == pytest.approx(1500.0)        # first year: its own matches
    assert typ[(2021, "250", "R32", 5)]["mean"] == pytest.approx(1500.0)        # later: the years before only


# ── the ranking-points calendar ───────────────────────────────────────────────────────────────────────────

def test_points_view_held_dropping_and_earned():
    from oddsmarkets.tennis.analytics.rankings import drop_week

    def ev(end, pts):
        e = date.fromisoformat(end)
        return (e.toordinal(), date.fromisoformat(drop_week(e)).toordinal(), pts, end)
    eps = [ev("2025-01-26", 2000.0), ev("2025-06-08", 1000.0), ev("2025-11-16", 500.0), ev("2026-02-01", 250.0)]
    d = date(2025, 12, 1).toordinal()
    held, drop6, earn6 = V.points_view(eps, d, 182)
    assert held == 3500.0                                    # the three events inside the 52 weeks
    assert drop6 == 2000.0                                    # only January 2025 drops before 1 June 2026
    assert earn6 == 250.0                                     # the February 2026 event is earned in the window
    held, drop12, _ = V.points_view(eps, d, 365)
    assert drop12 == 3500.0                                   # in a 52-week ranking everything held drops within a year
    # the drop day is the Monday on or after the end + 364 days
    assert date.fromisoformat(drop_week("2025-01-26")).weekday() == 0
    assert date.fromisoformat(drop_week("2025-01-26")) >= date(2026, 1, 25)


def test_rank_lookups_never_see_the_future():
    rs = {"a": (np.array([10, 20, 30, 40]), np.array([50.0, 40.0, 30.0, 20.0]), np.array([1.0, 2.0, 3.0, 4.0]))}
    assert V.rank_before(rs, "a", 30) == (40.0, 2.0, 20)          # strictly before day 30
    assert V.rank_before(rs, "a", 200) is None                    # nothing within 120 days
    assert V.rank_near(rs, "a", 31, 5) == 30.0
    assert V.rank_near(rs, "a", 39, 5, before=40) is None          # an observation on or after `before` is not used


# ── ratings at dates agree with the models' own functions ─────────────────────────────────────────────────

def test_elo_and_game_share_states_match_ratings_at(ace_world):
    from oddsmarkets.tennis.models import elo as E
    from oddsmarkets.tennis.models import gelo as G
    td = an.TourData("atp", ace_world["today"])
    days = [date(2025, 6, 1), date(2026, 3, 1)]
    est = V.elo_states(td.elo, [x.toordinal() for x in days])
    gst = V.gelo_states(td.gelo, [x.toordinal() for x in days])
    for k, x in enumerate(days):
        ref = E.ratings_at(td.elo, x)
        gref = G.ratings_at(td.gelo, x)
        assert set(ref) == set(est[k])
        for p, r in ref.items():
            assert est[k][p][0] == pytest.approx(r["all"]) and est[k][p][2] == pytest.approx(r["clay"])
            assert est[k][p][4] == r["n"]
        for p, r in gref.items():
            assert gst[k][p][0] == pytest.approx(r["all"]) and gst[k][p][3] == pytest.approx(r["grass"])


# ── walk-forward: no look-ahead ───────────────────────────────────────────────────────────────────────────

def _panel(seed=0, years=range(2008, 2018)):
    rng = np.random.default_rng(seed)
    rows, cov = [], {}
    for y in years:
        for mth in V.SNAP_MONTHS:
            t = date(y, mth, 1).isoformat()
            cov[t] = {"n": 40, "obs12m": 40, "obs6m": 40}
            for i in range(40):
                rk = float(rng.integers(1, 150))
                gap = float(rng.normal(0, 0.5))
                row = {"pid": f"p{i}", "t": t, "rank": rk, "pts": 1000.0, "R": 1800.0, "imp": rk, "gap_raw": gap, "n12": 40,
                       "elo": 1800.0, "age": float(rng.uniform(18, 34)), "idle": 10, "d_elo": 0.0, "d_rank": 0.0, "held": 800.0,
                       "drop12": 800.0, "drop6": 400.0, "luck": 0.0, "draw": 0.0, "mk": 0.0, "tl12": 30}
                for h in ("12m", "6m"):
                    row[f"y{h}"] = -0.4 * gap + float(rng.normal(0, 0.3))
                    row[f"o{h}"] = 1
                    row[f"e{h}"] = 10.0 * gap
                rows.append(row)
    return {"rows": rows, "coverage": cov}


def test_walk_forward_predictions_never_use_unresolved_targets():
    panel = _panel()
    pr = V.walk_forward(panel, "12m", 10.0, 10.0, None, None, "atp")
    assert pr and min(r["year"] for r in pr) >= V.FIRST_PRED_YEAR["atp"]
    Y = 2014
    cut = date(Y, 1, 1)
    # scramble every target whose 12-month window had not closed by 1 January of Y (and every later row)
    panel2 = _panel()
    rng = np.random.default_rng(9)
    for r in panel2["rows"]:
        if date.fromisoformat(r["t"]) + timedelta(days=365 + V.RANK_AROUND) > cut:
            r["y12m"] = float(rng.normal(0, 3))
            r["e12m"] = float(rng.normal(0, 300))
    pr2 = V.walk_forward(panel2, "12m", 10.0, 10.0, None, None, "atp")
    a = {(r["pid"], r["t"]): r for r in pr if r["year"] == Y}
    b = {(r["pid"], r["t"]): r for r in pr2 if r["year"] == Y}
    assert a.keys() == b.keys() and a
    for k in a:
        assert a[k]["pred"] == pytest.approx(b[k]["pred"])
        assert a[k]["pred_e"] == pytest.approx(b[k]["pred_e"])
        assert a[k]["p_rise"] == pytest.approx(b[k]["p_rise"])
    # ... while a later year's model, which may use them, does change
    later = [r for r in pr if r["year"] == 2016]
    later2 = {(r["pid"], r["t"]): r["pred"] for r in pr2 if r["year"] == 2016}
    assert any(abs(r["pred"] - later2[(r["pid"], r["t"])]) > 1e-6 for r in later)
    # the planted signal is found out of sample
    ev = V.evaluate(pr, {})
    assert ev["pooled"]["dev"]["rho"][0] > 0.4


def test_features_never_see_matches_on_or_after_the_snapshot(ace_world):
    td = an.TourData("atp", ace_world["today"])
    C = V.Ctx(td)
    t = date(2026, 4, 1)
    d = t.toordinal()
    ranks = {p: (float(r), 1000.0) for p, r in list(ace_world["rank"].items())[:30]}
    E = V.elo_states(td.elo, [(t - timedelta(days=182)).toordinal(), d])
    G = V.gelo_states(td.gelo, [d])[0]
    f1 = V.features_at(C, t, ranks, E[1], G, None, E[0], 2.0)
    # rewrite the future: every row on or after the snapshot flips its result, gets a price and a rank
    fut = C.T["d"] >= d
    assert fut.any()
    C.T["won"][fut] = 1 - C.T["won"][fut]
    C.T["g"][fut], C.T["gl"][fut] = C.T["gl"][fut].copy(), C.T["g"][fut].copy()
    C.T["book"][fut] = 0.97
    C.T["rank"][fut] = 1.0
    C.rs = V.rank_series(C.T)
    C.L = V.match_luck(C.T, C.lp, C.typ)
    f2 = V.features_at(C, t, ranks, E[1], G, None, E[0], 2.0)
    assert f1.keys() == f2.keys() and f1
    for p in f1:
        for k in ("luck", "draw", "mk", "n12", "idle", "d_rank", "gap_raw", "tl12"):
            assert f1[p][k] == pytest.approx(f2[p][k]), (p, k)


# ── payloads on the synthetic world, the glossary and the front end ───────────────────────────────────────

def test_build_value_on_the_synthetic_world(ace_world):
    from oddsmarkets.tennis.analytics import players as PL
    td = an.TourData("atp", ace_world["today"])
    entries = {y: PL.season_entries(td, y) for y in td.years}
    pay, val = V.build_value(td, entries, {})
    assert pay["ok"] and val["ok"] and pay["tour"] == "atp"
    assert set(pay) >= {"breakout", "luck", "value", "market", "universe", "as_of"}
    b = pay["breakout"]["rows"]
    assert b and {r["pid"] for r in b} <= set(ace_world["pids"])
    assert all(r["rank"] <= V.UNIVERSE for r in b)
    lu = pay["luck"]["rows"]
    assert lu and all(r["52w"]["n"] >= V.MIN_LUCK for r in lu if "52w" in r)
    x = next(r["52w"] for r in lu if "52w" in r)
    assert x["total"] == pytest.approx((x["close"] or 0) + x["draw"] + x["free"], abs=0.02)
    vr = pay["value"]["rows"]
    assert vr and all(isinstance(r["mrank"], int) for r in vr)
    # the strongest planted player is near the top of the model ranking
    top = min(vr, key=lambda r: r["mrank"])["pid"]
    assert ace_world["rank"][top] <= 5
    assert val["definitions"]["universe"] == V.UNIVERSE and "luck_evidence" in val
    assert {r["pid"] for r in b} <= set(pay["names"]) and pay["names"][b[0]["pid"]].startswith("Player ")
    # a second call is served from the cache with the same history
    pay2, val2 = V.build_value(td, entries, {})
    assert val2["tuned"] == val["tuned"]


def test_glossary_covers_the_value_section():
    from oddsmarkets.tennis.analytics.glossary import build_glossary
    g = build_glossary()
    keys = {e["key"]: e for grp in g["groups"] for e in grp["entries"]}
    for e in V.VALUE_GLOSSARY:
        assert e["key"] in keys and keys[e["key"]]["desc"] and keys[e["key"]]["desc"] != e["label"]
    assert len({e["key"] for e in V.VALUE_GLOSSARY}) == len(V.VALUE_GLOSSARY)
    assert {"value_breakout", "value_luck", "value_rating"} <= {m["key"] for m in g["model"]}
    # every glossary link and payload the page uses exists
    js = (ROOT / "docs" / "ace" / "assets" / "js" / "value.js").read_text(encoding="utf-8")
    for k in re.findall(r"glossLink\('([a-z0-9_]+)'", js):
        assert k in keys, k
    assert "value.json" in js and "value_validation.json" in js
    assert "?." not in re.sub(r"'[^']*'", "''", js) and "??" not in js
    html = (ROOT / "docs" / "ace" / "index.html").read_text(encoding="utf-8")
    assert 'src="assets/js/value.js"' in html and 'assets/qk/quant.js' in html      # the kit shell (docs/REDESIGN.md)
    core = (ROOT / "docs" / "ace" / "assets" / "js" / "core.js").read_text(encoding="utf-8")
    assert "addRoute('value', 'value')" in core and "value: [['value', 'Player value'" in core   # routed and in the Value section
    for f in V.FKEYS:
        assert f in js, f                                     # every feature has a label on the page
