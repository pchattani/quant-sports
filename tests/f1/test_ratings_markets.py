"""Builder C: Elo ratings, Plackett-Luce, and F1 market mapping (offline, synthetic fixtures)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from oddsmarkets.common import ranking
from oddsmarkets.common.markets import consensus_field, devig
from oddsmarkets.f1.models import elo
from oddsmarkets.f1.sources import markets as f1m

# ── synthetic seasons ────────────────────────────────────────────────────────

TEAMS = {"a": "red", "b": "red", "c": "blue", "d": "blue", "e": "green", "f": "green"}


def _result(order, statuses=None, teams=TEAMS):
    statuses = statuses or {}
    rows, pos = [], 1
    finishers = [d for d in order if statuses.get(d, "Finished") == "Finished"]
    others = [d for d in order if d not in finishers]
    for d in finishers + others:
        st = statuses.get(d, "Finished")
        rows.append({"driver": d, "constructor": teams[d], "position": pos, "grid": pos,
                     "position_text": str(pos) if st == "Finished" else "R", "status": st})
        pos += 1
    return rows


def _store(year, races, quali=None):
    out = {"season": year, "races": {}, "drivers": {d: {"given": d.upper(), "family": d} for d in TEAMS},
           "constructors": {t: {"name": t} for t in set(TEAMS.values())}}
    for i, res in enumerate(races, 1):
        q = [{"driver": d, "constructor": TEAMS[d], "position": k + 1} for k, d in enumerate((quali or {}).get(i, []))]
        out["races"][str(i)] = {"name": f"GP {i}", "date": f"{year}-0{min(i, 9)}-01", "results": res, "qualifying": q}
    return out


BASE = ["a", "c", "e", "b", "d", "f"]


def test_a_consistently_faster_driver_rises():
    races = [_result(BASE) for _ in range(10)]
    h = elo.elo_history(stores={2020: _store(2020, races)})
    cur = h["current"]
    assert cur["a"]["elo"] > cur["c"]["elo"] > cur["e"]["elo"] > cur["f"]["elo"]
    assert cur["a"]["elo"] > 1500 > cur["f"]["elo"]
    # teammate Elo: a beats b, c beats d, e beats f every time
    assert cur["a"]["elo_teammate"] > cur["b"]["elo_teammate"]
    assert cur["e"]["elo_teammate"] > cur["f"]["elo_teammate"]
    # zero-sum field update
    assert abs(sum(v["elo"] for v in cur.values()) - 1500 * len(cur)) < 1e-6 * len(cur) + 0.5


def test_a_mechanical_dnf_costs_less_than_a_crash():
    warm = [_result(BASE) for _ in range(3)]
    mech = elo.elo_history(stores={2020: _store(2020, warm + [_result(BASE, {"a": "Engine"})])})
    crash = elo.elo_history(stores={2020: _store(2020, warm + [_result(BASE, {"a": "Accident"})])})
    amb = elo.elo_history(stores={2020: _store(2020, warm + [_result(BASE, {"a": "Retired"})])})
    pre = mech["races"][-1]["drivers"]["a"]["elo_pre"]
    d_mech = mech["races"][-1]["drivers"]["a"]["elo"] - pre
    d_crash = crash["races"][-1]["drivers"]["a"]["elo"] - pre
    d_amb = amb["races"][-1]["drivers"]["a"]["elo"] - pre
    assert d_mech == 0
    assert d_crash < d_amb < d_mech
    assert elo.status_class("Gearbox", "R") == elo.MECHANICAL
    assert elo.status_class("Collision", "R") == elo.DRIVER
    assert elo.status_class("+2 Laps", "14") == elo.FINISHED
    assert elo.status_class("Did not start", "W") == elo.EXCLUDED


def test_teammate_elo_moves_only_on_head_to_heads():
    warm = [_result(BASE) for _ in range(2)]
    # a retires mechanically: no head-to-head with b; c crashes: d wins the head-to-head
    last = _result(BASE, {"a": "Hydraulics", "c": "Spun off"})
    h = elo.elo_history(stores={2020: _store(2020, warm + [last])})
    rd = h["races"][-1]["drivers"]
    for d in ("a", "b"):
        assert rd[d]["elo_teammate"] == rd[d]["elo_teammate_pre"]
    assert rd["d"]["elo_teammate"] > rd["d"]["elo_teammate_pre"]
    assert rd["c"]["elo_teammate"] < rd["c"]["elo_teammate_pre"]
    # field Elo of b moved although its teammate Elo did not
    assert rd["b"]["elo"] != rd["b"]["elo_pre"]
    # an ambiguous "Retired" is not a head-to-head either
    h2 = elo.elo_history(stores={2020: _store(2020, warm + [_result(BASE, {"e": "Retired"})])})
    r2 = h2["races"][-1]["drivers"]
    assert r2["e"]["elo_teammate"] == r2["e"]["elo_teammate_pre"]
    assert r2["f"]["elo_teammate"] == r2["f"]["elo_teammate_pre"]


def test_ratings_regress_between_seasons_and_rookies_start_low():
    s1 = _store(2020, [_result(BASE) for _ in range(8)])
    teams2 = {**TEAMS, "g": "green"}
    order2 = ["a", "c", "e", "b", "d", "g"]
    s2 = _store(2021, [_result(order2, teams=teams2)])
    s2["drivers"]["g"] = {"given": "G", "family": "g"}
    h = elo.elo_history(stores={2020: s1, 2021: s2})
    end_2020 = {d: v for d, v in h["races"][7]["drivers"].items()}
    start_2021 = h["races"][8]["drivers"]
    expect = 1500 + (1 - elo.REGRESS) * (end_2020["a"]["elo"] - 1500)
    assert start_2021["a"]["elo_pre"] == pytest.approx(expect, abs=0.11)
    assert abs(start_2021["a"]["elo_pre"] - 1500) < abs(end_2020["a"]["elo"] - 1500)
    mean_pre = np.mean([v["elo_pre"] for d, v in start_2021.items() if d != "g"])
    assert start_2021["g"]["elo_pre"] == pytest.approx(mean_pre - elo.ROOKIE_OFFSET, abs=0.2)


def test_qualifying_elo_and_empty_history():
    q = {i: ["f", "e", "d", "c", "b", "a"] for i in range(1, 6)}
    h = elo.elo_history(stores={2020: _store(2020, [_result(BASE) for _ in range(5)], quali=q)})
    assert h["current"]["f"]["elo_quali"] > h["current"]["a"]["elo_quali"]
    empty = elo.elo_history(stores={})
    assert empty["races"] == [] and empty["current"] == {} and empty["all_time"] == []


# ── Plackett-Luce ────────────────────────────────────────────────────────────

def test_plackett_luce_recovers_planted_strengths():
    planted = {"w": 1.5, "x": 0.5, "y": -0.5, "z": -1.5}
    items, orders = ranking.sample_orders(planted, n=3000, seed=7)
    obs = [[items[i] for i in row] for row in orders]
    fit = ranking.fit_strengths(obs, ridge=0.01)
    assert abs(sum(fit.values())) < 1e-6
    for k, v in planted.items():
        assert fit[k] == pytest.approx(v, abs=0.15)


def test_plackett_luce_partial_orders_and_gradient():
    obs = [["a", "b"], ["a", "c"], ["b", "c"], ["a", "b", "c"]]
    fields = [["a", "b", "c"]] * 4
    items, arrays, ks = ranking._index(obs, fields)
    theta = np.array([0.3, -0.1, 0.2])
    _, g = ranking._loglik_grad(theta, arrays, ks, np.ones(4))
    eps = 1e-6
    for i in range(3):
        tp, tm = theta.copy(), theta.copy()
        tp[i] += eps
        tm[i] -= eps
        num = (ranking._loglik_grad(tp, arrays, ks, np.ones(4))[0] - ranking._loglik_grad(tm, arrays, ks, np.ones(4))[0]) / (2 * eps)
        assert g[i] == pytest.approx(num, abs=1e-5)
    fit = ranking.fit_strengths(obs, fields=fields)
    assert fit["a"] > fit["b"] > fit["c"]
    assert ranking.fit_strengths([]) == {}


def test_plackett_luce_probabilities_sum_to_one():
    s = {"a": 1.0, "b": 0.0, "c": -0.5, "d": -2.0}
    p = ranking.pl_probabilities(s, top_k=(1, 2, 3), n=20000, seed=1)
    assert sum(v["p_win"] for v in p.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(v["p_top1"] for v in p.values()) == pytest.approx(1.0, abs=1e-9)
    assert sum(v["p_top3"] for v in p.values()) == pytest.approx(3.0, abs=1e-9)
    exact = math.exp(1) / sum(math.exp(x) for x in s.values())
    assert p["a"]["p_win"] == pytest.approx(exact)
    assert p["a"]["p_top1"] == pytest.approx(exact, abs=0.015)
    assert sum(v["exp_pos"] for v in p.values()) == pytest.approx(10.0, abs=1e-6)
    assert ranking.pl_probabilities({}) == {}


# ── markets ──────────────────────────────────────────────────────────────────

F1_STORE = {
    "season": 2026,
    "races": {"16": {"name": "Bahrain Grand Prix", "date": "2026-10-04", "results": [], "qualifying": []}},
    "drivers": {
        "antonelli": {"code": "ANT", "given": "Andrea Kimi", "family": "Antonelli"},
        "russell": {"code": "RUS", "given": "George", "family": "Russell"},
        "sainz": {"code": "SAI", "given": "Carlos", "family": "Sainz"},
        "hulkenberg": {"code": "HUL", "given": "Nico", "family": "Hülkenberg"},
        "perez": {"code": "PER", "given": "Sergio", "family": "Pérez"},
        "max_verstappen": {"code": "VER", "given": "Max", "family": "Verstappen"},
        "norris": {"code": "NOR", "given": "Lando", "family": "Norris"},
        "alonso": {"code": "ALO", "given": "Fernando", "family": "Alonso"},
    },
    "constructors": {"mercedes": {"name": "Mercedes"}, "red_bull": {"name": "Red Bull"}, "rb": {"name": "RB F1 Team"},
                     "haas": {"name": "Haas F1 Team"}, "ferrari": {"name": "Ferrari"}, "audi": {"name": "Audi"},
                     "aston_martin": {"name": "Aston Martin"}, "cadillac": {"name": "Cadillac F1 Team"}},
}


def _k(label, bid, ask, **kw):
    return {"yes_sub_title": label, "yes_bid_dollars": bid, "yes_ask_dollars": ask, "occurrence_datetime": "2026-10-04T13:00:00Z", **kw}


def _p(label, bid, ask, closed=False, prices=None):
    return {"groupItemTitle": label, "bestBid": bid, "bestAsk": ask, "closed": closed, "outcomePrices": prices}


def test_driver_and_constructor_names_map_to_jolpica_ids():
    d = F1_STORE["drivers"]
    assert f1m.map_driver("Andrea Kimi Antonelli", d) == "antonelli"
    assert f1m.map_driver("Kimi Antonelli", d) == "antonelli"
    assert f1m.map_driver("Carlos Sainz Jr.", d) == "sainz"
    assert f1m.map_driver("Jr.", d) == "sainz"
    assert f1m.map_driver("Nico Hulkenberg", d) == "hulkenberg"
    assert f1m.map_driver("Sergio Perez", d) == "perez"
    assert f1m.map_driver("Verstappen", d) == "max_verstappen"
    assert f1m.map_driver("VER", d) == "max_verstappen"
    assert f1m.map_driver("Arvid Lindblad", d) is None
    c = F1_STORE["constructors"]
    assert f1m.map_constructor("Mercedes AMG Motorsport", c) == "mercedes"
    assert f1m.map_constructor("Red Bull Racing", c) == "red_bull"
    assert f1m.map_constructor("Racing Bulls", c) == "rb"
    assert f1m.map_constructor("Haas", c) == "haas"
    assert f1m.map_constructor("Audi F1 Team", c) == "audi"
    assert f1m.map_constructor("Cadillac", c) == "cadillac"


def _patch(monkeypatch, kalshi=None, poly=None, tag=None):
    monkeypatch.setattr(f1m, "kalshi_events", lambda series, *a, **k: (kalshi or {}).get(series, []))
    monkeypatch.setattr(f1m, "polymarket_event", lambda slug: (poly or {}).get(slug))
    monkeypatch.setattr(f1m, "polymarket_tag_events", lambda *a, **k: tag or [])


def test_title_market_pools_sources_devigs_and_keeps_written_off_runners(monkeypatch):
    kalshi = {"KXF1": [{"event_ticker": "KXF1-26", "markets": [
        _k("Andrea Kimi Antonelli", "0.92", "0.93"), _k("George Russell", "0.04", "0.05"),
        _k("Lando Norris", "0.00", "0.01"), _k("Carlos Sainz Jr.", "0.00", "0.01"), _k("Mystery Driver", "0.10", "0.12")]}]}
    poly = {"2026-f1-drivers-champion": {"slug": "2026-f1-drivers-champion", "markets": [
        _p("Kimi Antonelli", 0.90, 0.92), _p("George Russell", 0.05, 0.06), _p("Lando Norris", 0.006, 0.008),
        _p("Max Verstappen", 0.002, 0.003), _p("Nico Hülkenberg", None, 0.001, closed=True, prices='["0", "1"]'),
        _p("Sergio Pérez", None, 0.001, closed=True, prices='["0", "1"]'), _p("Fernando Alonso", None, 0.001, closed=True, prices='["0", "1"]'),
        _p("Other", 0, 1), _p("Driver A", 0, 1)]}}
    _patch(monkeypatch, kalshi, poly)
    out = f1m.title_prices("drivers", year=2026, store=F1_STORE)
    assert out["available"], out["reason"]
    assert out["sources"]["kalshi"]["antonelli"] == pytest.approx(0.925)
    assert out["mid"]["antonelli"] == pytest.approx((0.925 + 0.91) / 2, abs=1e-4)
    assert set(out["eliminated"]) == {"hulkenberg", "perez", "alonso"}
    assert out["floor"] == ["sainz"]                         # no bid, 1c ask: written off, not priced
    assert out["probs"]["sainz"] == 0.0 and out["probs"]["perez"] == 0.0
    assert sum(out["probs"].values()) == pytest.approx(1.0, abs=1e-4)
    mids = out["mid"]
    assert out["probs"]["russell"] == pytest.approx(mids["russell"] / sum(mids.values()), abs=1e-4)
    assert "Mystery Driver" in out["unmatched"]


def test_thin_title_market_is_not_published(monkeypatch):
    kalshi = {"KXF1CONSTRUCTORS": [{"event_ticker": "KXF1CONSTRUCTORS-26", "markets": [
        _k("Mercedes AMG Motorsport", "0.60", "0.62"), _k("Ferrari", "0.20", "0.22")]}]}
    _patch(monkeypatch, kalshi, {})
    out = f1m.title_prices("constructors", year=2026, store=F1_STORE)
    assert out["available"] is False and out["probs"] == {}
    assert "thin" in out["reason"]
    # a full field whose prices add to 1.6 is not a market either
    kalshi["KXF1CONSTRUCTORS"][0]["markets"] = [_k(n, "0.20", "0.22") for n in
                                                ("Mercedes", "Red Bull Racing", "Racing Bulls", "Haas", "Ferrari", "Audi", "Aston Martin", "Cadillac")]
    out = f1m.title_prices("constructors", year=2026, store=F1_STORE)
    assert out["available"] is False


def test_race_winner_matched_by_date_and_h2h_parsing(monkeypatch):
    race_ev = {"event_ticker": "KXF1RACE-BAH26", "title": "Bahrain Grand Prix Main Race Winner", "markets": [
        _k("Andrea Kimi Antonelli", "0.40", "0.41"), _k("George Russell", "0.21", "0.22"), _k("Max Verstappen", "0.13", "0.14"),
        _k("Lando Norris", "0.11", "0.12"), _k("Fernando Alonso", "0.04", "0.05"), _k("Carlos Sainz Jr.", "0.02", "0.03"),
        _k("Nico Hulkenberg", "0.0", "0.01"), _k("Sergio Perez", "0.0", "0.01")]}
    old_ev = {**race_ev, "event_ticker": "KXF1RACE-AZE26",
              "markets": [_k("George Russell", "0.5", "0.52", occurrence_datetime="2026-09-26T11:00:00Z")]}
    h2h_k = {"event_ticker": "KXF1H2H-BAH26VERNOR", "title": "F1 Matchup: Verstappen vs Norris",
             "markets": [_k("Max Verstappen", "0.55", "0.57"), _k("Lando Norris", "0.45", "0.47")]}
    poly_tag = [
        {"slug": "f1-bahrain-grand-prix-h2h-2026-10-04", "closed": False, "markets": [
            {"groupItemTitle": "Norris vs Verstappen", "outcomes": '["Norris", "Verstappen"]', "bestBid": 0.42, "bestAsk": 0.44, "closed": False},
            {"groupItemTitle": "Albon vs Jr.", "outcomes": '["Albon", "Jr."]', "bestBid": None, "bestAsk": 0.03, "closed": False},
            {"groupItemTitle": "Alonso vs Jr.", "outcomes": '["Alonso", "Jr."]', "bestBid": 0.6, "bestAsk": 0.62, "closed": False}]},
        {"slug": "f1-will-carlos-sainz-finish-ahead-of-fernando-alonso-in-the-2026-drivers-championship", "closed": False,
         "title": "F1: Will Carlos Sainz finish ahead of Fernando Alonso in the 2026 Drivers' Championship?",
         "markets": [{"bestBid": 0.87, "bestAsk": 0.92, "closed": False}]},
    ]
    _patch(monkeypatch, {"KXF1RACE": [old_ev, race_ev], "KXF1H2H": [h2h_k]}, {}, poly_tag)
    out = f1m.race_winner_prices(2026, 16, store=F1_STORE)
    assert out["available"] and out["markets"]["kalshi"] == "KXF1RACE-BAH26"
    assert max(out["probs"], key=out["probs"].get) == "antonelli"
    assert out["probs"]["perez"] == 0.0
    h = f1m.h2h_prices(year=2026, store=F1_STORE)
    vn = next(r for r in h["race"] if {r["a"], r["b"]} == {"max_verstappen", "norris"})
    assert vn["round"] == 16 and set(vn["sources"]) == {"kalshi", "polymarket"}
    p_ver_k = 0.56 / (0.56 + 0.46)
    p_ver = (p_ver_k + (1 - 0.43)) / 2
    p_a = vn["p_a"] if vn["a"] == "max_verstappen" else vn["p_b"]
    assert p_a == pytest.approx(p_ver, abs=1e-3)
    ao = next(r for r in h["race"] if {r["a"], r["b"]} == {"alonso", "sainz"})
    assert ao["a"] == "alonso" and ao["p_a"] == pytest.approx(0.61)
    assert not any("albon" in (r["a"], r["b"]) for r in h["race"])          # one-sided quote: not a price
    season = h["season"][0]
    assert season["a"] == "alonso" and season["p_a"] == pytest.approx(1 - 0.895, abs=1e-4)


def test_network_failure_is_not_an_error(monkeypatch):
    _patch(monkeypatch)
    assert f1m.title_prices("drivers", year=2026, store=F1_STORE)["available"] is False
    assert f1m.race_winner_prices(2026, 16, store=F1_STORE)["available"] is False
    assert f1m.h2h_prices(year=2026, store=F1_STORE) == {"race": [], "season": [], "markets": []}


def test_common_reexports_match_football():
    from oddsmarkets.common import prediction_markets as cpm
    from oddsmarkets.football.core import markets as fm
    from oddsmarkets.football.sources import prediction_markets as fpm
    from oddsmarkets.common import markets as cm
    assert cm.devig is fm.devig and cm.consensus is fm.consensus and cm.overround is fm.overround and cm.edge is fm.edge
    assert cpm._mid is fpm._mid and cpm.fold is fpm.fold and cpm.best_match is fpm.best_match and cpm._get is fpm._get
    assert cpm.kalshi_price({"yes_bid_dollars": "0.40", "yes_ask_dollars": "0.44"}) == pytest.approx(0.42)
    assert cpm.poly_price({"bestBid": None, "bestAsk": 0.01}) is None
    fair = consensus_field({"k": {"x": 2.0, "y": 2.0}, "p": {"x": 1.25, "y": 5.0}})
    assert sum(fair.values()) == pytest.approx(1.0)
    assert devig({"x": 2.0, "y": 2.0}) == {"x": 0.5, "y": 0.5}
