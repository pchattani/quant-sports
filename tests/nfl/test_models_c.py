"""Builder C: team strength, game model, drive simulation, season simulation and tiebreakers, live WP, awards,
backtest and the market parsers. Synthetic data and recorded fixtures only (no network)."""
from __future__ import annotations

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oddsmarkets.nfl.models import _cdata as D
from oddsmarkets.nfl.models import award_winners as AW
from oddsmarkets.nfl.models import awards as AWD
from oddsmarkets.nfl.models import backtest as BT
from oddsmarkets.nfl.models import drive_sim as DS
from oddsmarkets.nfl.models import game as GM
from oddsmarkets.nfl.models import live as LV
from oddsmarkets.nfl.models import season_sim as SS
from oddsmarkets.nfl.models import synthetic_c as SC
from oddsmarkets.nfl.models import team_strength as TS
from oddsmarkets.nfl.sources import markets as M

FIX = Path(__file__).with_name("fixtures") / "markets_c.json"


@pytest.fixture(scope="module")
def lg():
    return SC.league((2021, 2022, 2023), seed=11)


@pytest.fixture(scope="module")
def chain(lg):
    u = lg["units"]
    return TS.season_chain([2021, 2022, 2023], units_of=lambda s: u[u["season"] == s])


# ── team strength ────────────────────────────────────────────────────────────

def _truth_net(tr):
    return np.array([SC.NP * (tr[t]["pass_team"] + tr[t]["qb_val"] - tr[t]["pass_def"]) +
                     SC.NR * (tr[t]["rush_off"] - tr[t]["rush_def"]) + tr[t]["st"] for t in SC.TEAMS])


def test_planted_strengths_recovered(lg, chain):
    for s in (2022, 2023):
        r, tr = chain["ends"][s], lg["truth"][s]
        net = np.array([r.teams[t]["net"] for t in SC.TEAMS])
        assert np.corrcoef(_truth_net(tr), net)[0, 1] > 0.65          # one 17-game season of realistic noise
        for unit in ("pass_def", "rush_off", "rush_def", "st"):
            a = np.array([tr[t][unit] for t in SC.TEAMS])
            b = np.array([r.teams[t][unit] for t in SC.TEAMS])
            assert np.corrcoef(a, b)[0, 1] > 0.5, unit
        po_t = np.array([tr[t]["pass_team"] + tr[t]["qb_val"] for t in SC.TEAMS])
        po = np.array([r.teams[t]["pass_off"] for t in SC.TEAMS])
        assert np.corrcoef(po_t, po)[0, 1] > 0.6


def test_qb_component_moves_the_rating(lg, chain):
    r = chain["ends"][2023].as_dict()
    tr = lg["truth"][2023]
    # a team's backup (rated from his own dropbacks, planted 0.15 EPA/play worse) lowers the team's net rating
    diffs = []
    for t in SC.TEAMS:
        b = tr[t]["backup"]
        if b in r["qbs"] and r["teams"][t]["qb"] == tr[t]["qb"]:
            diffs.append(TS.team_net(r, t, b) - TS.team_net(r, t))
    assert len(diffs) >= 5 and np.mean(diffs) < 0
    # an unknown QB gets the new-QB prior
    assert TS.qb_value(r, "nobody") == TS.params()["qb_new"]


def test_preseason_prior_regresses(chain):
    end = chain["ends"][2022]
    pr = TS.preseason_prior(end, 2023, TS.params())
    t = "BUF"
    assert abs(pr["teams"][t]["pass_def"]) <= abs(end.teams[t]["pass_def"]) + 1e-12


# ── game model ───────────────────────────────────────────────────────────────

def test_margin_pmf_and_probabilities():
    kk = np.ones(GM.KEY_MAX + 1)
    kk[3], kk[7], kk[0] = 2.5, 1.8, 0.1
    P = GM.margin_pmf([0.0, 3.0], 13.0, kk)
    assert np.allclose(P.sum(1), 1.0)
    i3 = np.nonzero(GM.SUPPORT == 3)[0][0]
    i4 = np.nonzero(GM.SUPPORT == 4)[0][0]
    assert P[0, i3] > P[0, i4] * 2                     # key number
    ph, pt = GM.win_probs(np.array([0.0]), 13.0, False, kk)
    assert abs(ph[0] - (1 - pt[0]) / 2) < 1e-9
    ph2, pt2 = GM.win_probs(np.array([0.0]), 13.0, True, kk)
    assert pt2[0] == 0 and abs(ph2[0] - 0.5) < 1e-9
    c = GM.cover_prob(3.0, 13.0, -3.0, kk)
    assert c["push"] > 0.05 and abs(c["home"] + c["push"] + c["away"] - 1) < 1e-9
    assert GM.ml_to_p(-150, 130) == pytest.approx((150 / 250) / (150 / 250 + 100 / 230))


def test_game_fit_on_walk_forward_rows(lg):
    u = lg["units"]
    wf = GM.walk_forward([2021, 2022, 2023], units_of=lambda s: u[u["season"] == s], games=lg["games"])
    assert len(wf) == len(lg["games"])
    p = GM.fit_from_rows(wf, min_rows=100)
    assert p["fitted"] and 0.4 < p["s"] < 1.6 and 8 < p["sigma"] < 22        # synthetic scores are noisier
    assert len(p["keys"]) == GM.KEY_MAX + 1


# ── drive simulation ─────────────────────────────────────────────────────────

def test_drive_sim_reproduces_planted_scoring():
    rates = {"TD": 0.25, "FG": 0.15, "PUNT": 0.40, "TO": 0.10, "DOWNS": 0.04, "MISS": 0.02, "HALF": 0.04,
             "SAFETY": 0.0, "OPPTD": 0.0}
    d = SC.drives(40000, seed=5, rates={**rates, "SAFETY": 1e-9, "OPPTD": 1e-9})
    m = DS.fit(d)
    p = DS.outcome_probs(np.array([50.0, 75.0, 90.0]), np.zeros(3), m)
    for k, v in rates.items():
        assert np.allclose(p[:, DS.CLASSES.index(k)], v, atol=0.02), k
    res = DS.simulate(0.0, 0.0, n=20000, season=2026, m=m, drives_half=10)
    try_ev = DS.P_2PT * 2 * DS.P_2PT_MAKE + (1 - DS.P_2PT) * DS.p_xp(2026)
    per_drive = rates["TD"] * (6 + try_ev) + rates["FG"] * 3
    reg = ~res["ot"]
    expect = 10 * per_drive                              # 5 drives a half each, two halves
    assert abs(res["hs"][reg].mean() - expect) < 0.6 and abs(res["as"][reg].mean() - expect) < 0.6


def test_drive_sim_calibrates_to_targets():
    out = DS.price(26.0, 19.0, season=2025, n=8000)
    assert abs(out["pts_h"] - 26.0) < 0.8 and abs(out["pts_a"] - 19.0) < 0.8
    assert 0 <= out["p_tie"] < 0.02 and out["p_home"] > 0.6


# ── tiebreakers ──────────────────────────────────────────────────────────────

def _frame(rows, season=2023):
    g = pd.DataFrame([{"game_id": f"g{i}", "season": season, "week": 1 + i // 16, "gtype": "REG",
                       "date": f"{season}-09-{10 + i % 15:02d}", "home": h, "away": a, "hs": hs, "as": as_,
                       "status": "final", "stadium": "", "roof": "outdoors", "temp": 60, "wind": 5,
                       "lines": {}} for i, (h, a, hs, as_) in enumerate(rows)])
    store = {"season": season, "games": {r["game_id"]: {**r} for r in g.to_dict("records")}}
    return D.games_from_store(store, season)


def _table(G, season=2023, restart=True):
    S0 = SS.build_state(season, G)
    cs = SS.ChunkStats(S0["conf_id"], S0["div_id"], S0["Gm"], S0["R"][None], S0["Wn"][None], S0["NPm"][None],
                       S0["PF"][None], S0["PA"][None])
    return S0, SS.FastTable(cs, 0, S0["teams"], S0["div_names"], S0["conf_names"], np.random.default_rng(0),
                            SS.steps(), restart)


def _a_table(G, season=2023):
    from oddsmarkets.nfl import tiebreak as TB
    return TB.Table([{"home": r.home, "away": r.away, "hs": r.hs, "as": r.as_, "gtype": "REG"}
                     for r in G.itertuples(index=False)], season, rng=random.Random(0))


def test_three_team_division_tie_head_to_head():
    # AFC East: BUF 2-0 v MIA, 1-1 v NE; MIA 2-0 v NE; v NYJ: BUF 0-2, MIA 1-1, NE 2-0; BUF, MIA, NE also beat PIT
    # once and NYJ loses at KC: BUF, MIA, NE 4-3, NYJ 3-4. Head-to-head among the three: BUF .750, MIA .500, NE .250
    # -> BUF wins the division; MIA v NE restarts at the two-club step 1 (MIA 2-0) -> BUF, MIA, NE, NYJ.
    rows = [("BUF", "MIA", 20, 10), ("MIA", "BUF", 10, 20), ("BUF", "NE", 20, 10), ("NE", "BUF", 20, 10),
            ("MIA", "NE", 20, 10), ("NE", "MIA", 10, 20),
            ("NYJ", "BUF", 20, 10), ("BUF", "NYJ", 10, 20), ("MIA", "NYJ", 20, 10), ("NYJ", "MIA", 20, 10),
            ("NE", "NYJ", 20, 10), ("NYJ", "NE", 10, 20),
            ("BUF", "PIT", 30, 0), ("MIA", "PIT", 30, 0), ("NE", "PIT", 30, 0), ("KC", "NYJ", 30, 0)]
    G = _frame(rows)
    S0, tb = _table(G)
    d = S0["div_names"].index("AFC East")
    order = [S0["teams"][i] for i in tb.division_order(d)]
    assert order == ["BUF", "MIA", "NE", "NYJ"]
    assert _a_table(G).division_order("AFC East") == order


def test_three_team_division_tie_falls_to_division_record():
    # BUF, MIA, NE split with each other (2-2 each among the three) and finish 4-4 (NYJ 3-4 after losing at KC);
    # head-to-head is level, the division record decides: BUF 4-2, MIA 3-3, NE 2-4 -> BUF; then MIA v NE restart:
    # h2h 1-1, division record MIA 3-3 v NE 2-4 -> MIA.
    rows = [("BUF", "MIA", 20, 10), ("MIA", "BUF", 20, 10), ("BUF", "NE", 20, 10), ("NE", "BUF", 20, 10),
            ("MIA", "NE", 20, 10), ("NE", "MIA", 20, 10),
            ("BUF", "NYJ", 20, 10), ("NYJ", "BUF", 10, 20), ("MIA", "NYJ", 20, 10), ("NYJ", "MIA", 20, 10),
            ("NE", "NYJ", 10, 20), ("NYJ", "NE", 20, 10),
            ("BUF", "PIT", 0, 30), ("BUF", "CIN", 0, 30), ("MIA", "PIT", 0, 30), ("MIA", "CLE", 30, 0),
            ("NE", "PIT", 30, 0), ("NE", "CLE", 30, 0), ("KC", "NYJ", 30, 0)]
    G = _frame(rows)
    S0, tb = _table(G)
    rec = {t: (S0["W"][S0["idx"][t]], S0["L"][S0["idx"][t]]) for t in ("BUF", "MIA", "NE")}
    assert len(set(rec.values())) == 1
    d = S0["div_names"].index("AFC East")
    order = [S0["teams"][i] for i in tb.division_order(d)]
    assert order == ["BUF", "MIA", "NE", "NYJ"]
    assert _a_table(G).division_order("AFC East") == order


def test_wild_card_two_club_conference_record():
    # BUF and PIT both 2-1 and never met: BUF 2-0 in the conference, PIT 0-1 -> BUF
    rows = [("BUF", "MIA", 20, 10), ("BUF", "NE", 20, 10), ("DAL", "BUF", 20, 10),
            ("PIT", "PHI", 20, 10), ("PIT", "NYG", 20, 10), ("CIN", "PIT", 20, 10)]
    G = _frame(rows)
    S0, tb = _table(G)
    i = S0["idx"]
    assert tb.pick_one([i["BUF"], i["PIT"]], "wc") == i["BUF"]
    assert _a_table(G).order(["BUF", "PIT"], "wc") == ["BUF", "PIT"]


def test_wild_card_three_club_sweep_then_two_club():
    # IND, KC, CLE (three divisions) all 3-2; IND beat KC and CLE (sweep) -> IND; then KC v CLE: KC won -> KC.
    rows = [("IND", "KC", 20, 10), ("IND", "CLE", 20, 10), ("IND", "DAL", 20, 10), ("NYG", "IND", 20, 10),
            ("PHI", "IND", 20, 10),
            ("KC", "CLE", 20, 10), ("KC", "WAS", 20, 10), ("KC", "CHI", 20, 10), ("DET", "KC", 20, 10),
            ("CLE", "GB", 20, 10), ("CLE", "MIN", 20, 10), ("CLE", "ATL", 20, 10)]
    G = _frame(rows)
    S0, tb = _table(G)
    i = S0["idx"]
    order = [S0["teams"][x] for x in tb.order([i["IND"], i["KC"], i["CLE"]], "wc")]
    assert order == ["IND", "KC", "CLE"]
    assert _a_table(G).order(["IND", "KC", "CLE"], "wc") == order


def test_fast_engine_matches_builder_a_table():
    agree = 0
    for k in range(12):
        L = SC.league((2023,), seed=500 + k, sd_unit=0.01)
        G = L["games"]
        S0, tb = _table(G, restart=False)
        a = _a_table(G).seeds()
        cs = tb.cs
        seeds, divw, _ = SS.seed_chunk(cs, S0["teams"], S0["div_names"], S0["conf_names"], SS.fmt(2023),
                                       np.random.default_rng(0), SS.steps(), False)
        for ci, c in enumerate(S0["conf_names"]):
            mine = [S0["teams"][x] for x in tb.seed_conference(ci, 3)]
            fast = [S0["teams"][x] for x in seeds[ci][0]]
            if tb.coin_used:
                continue
            assert mine == a[c]["seeds"] == fast
            agree += 1
    assert agree >= 10


# ── season simulation ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sim():
    L = SC.league((2024, 2025), seed=3, played_through_week=6)
    u = L["units"]
    ch = TS.season_chain([2024], units_of=lambda s: u[u["season"] == s])
    r = TS.fit(u, 2025, None, TS.preseason_prior(ch["ends"][2024], 2025)).as_dict()
    return SS.simulate(2025, n=4000, seed=1, state={"games": L["games"], "ratings": r})


def test_playoff_probabilities_sum(sim):
    T = sim["teams"]
    assert sum(v["p_playoffs"] for v in T.values()) == pytest.approx(14.0)
    assert sum(v["p_div"] for v in T.values()) == pytest.approx(8.0)
    assert sum(v["p_bye"] for v in T.values()) == pytest.approx(2.0)
    assert sum(v["p_conf"] for v in T.values()) == pytest.approx(2.0)
    assert sum(v["p_sb"] for v in T.values()) == pytest.approx(1.0)
    assert sum(v["p_reach"]["SB"] for v in T.values()) == pytest.approx(2.0)
    assert sum(v["p_reach"]["CON"] for v in T.values()) == pytest.approx(4.0)
    assert sum(v["p_reach"]["DIV"] for v in T.values()) == pytest.approx(8.0)
    assert sum(v["draft"]["p_pick1"] for v in T.values()) == pytest.approx(1.0)
    for v in T.values():
        assert sum(v["seed_dist"]) == pytest.approx(v["p_playoffs"])
        assert sum(v["win_dist"]) == pytest.approx(1.0, abs=1e-3)
        assert v["p_sb"] <= v["p_conf"] <= v["p_playoffs"] + 1e-9
        assert sum(v["draft"]["dist"]) == pytest.approx(1.0, abs=1e-3)


def test_interventional_next_game(sim):
    nx = [v["next"] for v in sim["teams"].values() if v["next"]]
    assert nx
    for n in nx:
        assert 0 < n["p_win"] < 1
    better = sum(1 for n in nx if n["if_win"]["p_playoffs"] >= n["if_loss"]["p_playoffs"] - 0.02)
    assert better >= 0.9 * len(nx)


def test_magic_numbers_division():
    W = np.array([10, 6, 5, 4])
    Rm = np.array([2, 2, 2, 2])
    mg = SS.magic_numbers(W, Rm, np.zeros(4, int), np.zeros(4, int), 7)
    assert mg[0]["clinched"]["division"]                    # 6 + 2 < 10
    assert mg[3]["eliminated"]["division"]
    assert mg[0]["clinched"]["playoffs"]


def test_season_sim_speed():
    import time
    L = SC.league((2025,), seed=4, played_through_week=3)
    t = time.perf_counter()
    SS.simulate(2025, n=20000, seed=0, state={"games": L["games"], "ratings": {"teams": {}, "league": {}}})
    assert time.perf_counter() - t < 40


# ── live ─────────────────────────────────────────────────────────────────────

def test_live_fallback_monotone_and_final():
    base = {"period": 4, "clock": "2:00", "status": "in", "possession": None, "yardline_100": None}
    lo = LV.live_wp({**base, "home_score": 17, "away_score": 20}, {"margin": 0})["wp_home"]
    hi = LV.live_wp({**base, "home_score": 24, "away_score": 20}, {"margin": 0})["wp_home"]
    assert lo < 0.5 < hi
    fin = LV.live_wp({"status": "final", "home_score": 10, "away_score": 3}, {"margin": 0})
    assert fin["wp_home"] == 1.0
    assert LV.secs_left(1, "15:00") == (3600.0, 1800.0)


# ── awards ───────────────────────────────────────────────────────────────────

def test_winners_table_complete():
    for aw in AWD.AWARDS:
        assert set(AW.WINNERS[aw]) == set(range(2006, 2026)), aw
    assert AW.WINNERS["mvp"][2025][0] == "Matthew Stafford" and AW.HAND_ENTERED is False


def test_conditional_logit_recovers_planted():
    rng = np.random.default_rng(0)
    beta = np.array([1.5, -0.7, 0.0])
    groups = []
    for _ in range(300):
        X = rng.normal(size=(12, 3))
        u = X @ beta
        p = np.exp(u - u.max())
        p /= p.sum()
        groups.append((X, int(rng.choice(12, p=p))))
    b = AWD.fit_clogit(groups, ridge=0.01)
    assert np.allclose(b, beta, atol=0.3)


def test_name_fold():
    assert AWD.fold("J. J. Watt") == AWD.fold("JJ Watt") == "jj watt"
    assert AWD.fold("Odell Beckham Jr.") == "odell beckham"


# ── backtest ─────────────────────────────────────────────────────────────────

def test_backtest_on_synthetic(lg):
    u = lg["units"]
    G = lg["games"].copy()
    rng = np.random.default_rng(2)
    G["line"] = G["margin"] * 0.0 + rng.normal(1.5, 1.0, len(G))
    wf = GM.walk_forward([2021, 2022, 2023], units_of=lambda s: u[u["season"] == s], games=G)
    out = BT.backtest(seasons=[2022, 2023], wf=wf, season_sims=0, write=False)
    m = out["metrics"]["model"]
    assert m["n"] > 400 and m["logloss"] < 0.693
    assert out["metrics"]["model"]["logloss"] <= out["metrics"]["elo"]["logloss"] + 0.03
    assert out["ats"]["n"] > 0 and "picks_p55" in out["ats"]


def test_elo_history_symmetry():
    rows = [("BUF", "MIA", 30, 0)] * 3
    G = _frame(rows)
    e = BT.elo_history(G)
    assert e.iloc[0] < e.iloc[1] < e.iloc[2]


# ── markets ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def fx():
    return json.loads(FIX.read_text(encoding="utf-8"))


def test_map_team_labels():
    t = M.teams_info(2026)
    assert M.map_team("Los Angeles R", t) == "LA"
    assert M.map_team("Los Angeles C", t) == "LAC"
    assert M.map_team("New York G", t) == "NYG"
    assert M.map_team(None, t, "JAC") == "JAX"
    assert M.map_team(None, t, "LAR") == "LA"
    assert M.map_team("Steelers", t) == "PIT"
    assert M.map_team("PIT Steelers", t) == "PIT"


def test_futures_from_fixture(fx):
    f = M.futures(2026, kalshi=fx["kalshi"], poly=fx["polymarket_tag"])
    assert f["champion"]["available"] and abs(sum(f["champion"]["probs"].values()) - 1) < 1e-3
    assert set(f["champion"]["sources"]) == {"kalshi", "polymarket"}
    assert f["conference"]["AFC"]["available"] and all(
        M.teams_info(2026)[t]["conf"] == "AFC" for t in f["conference"]["AFC"]["probs"])
    assert f["division"]["AFC East"]["available"] and max(f["division"]["AFC East"]["probs"], key=f["division"]["AFC East"]["probs"].get) == "BUF"
    assert f["top_seed"]["AFC"]["available"]
    assert 12 < sum(f["playoffs"]["probs"].values()) < 16 and len(f["playoffs"]["probs"]) == 32
    wt = f["win_totals"]["BUF"]["kalshi"]
    lad = [wt["ladder"][k] for k in sorted(wt["ladder"])]
    assert all(a >= b for a, b in zip(lad, lad[1:]))
    assert f["awards"]["mvp"]["available"] and "name:Josh Allen" in f["awards"]["mvp"]["probs"]


def test_game_prices_from_fixture(fx):
    gm = [{"game_id": "2026_04_PIT_CLE", "home": "CLE", "away": "PIT", "date": "2026-10-01", "week": 4},
          {"game_id": "2026_04_LA_PHI", "home": "PHI", "away": "LA", "date": "2026-10-04", "week": 4}]
    gp = M.game_prices(2026, games=gm, kalshi=fx["kalshi"], poly=fx["polymarket_games"])
    g = gp["2026_04_PIT_CLE"]
    assert g["basis"] == "prediction_markets" and 0.35 < g["p_home"] < 0.5
    assert {s["source"] for s in g["sources"]} == {"kalshi", "polymarket"}
    assert g["spread"]["kalshi"]["away"] and g["total"]["kalshi"] and g["team_total"]["kalshi"]["home"]
    tot = g["total"]["kalshi"]
    ks = sorted(tot)
    assert tot[ks[0]] > tot[ks[-1]]
    assert "2026_04_LA_PHI" in gp
